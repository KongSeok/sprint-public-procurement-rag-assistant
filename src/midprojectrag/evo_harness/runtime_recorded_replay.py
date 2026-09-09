"""Frozen-PRE search replay with live Qwen policy; no semantic answer judging."""
from __future__ import annotations
from collections import Counter
from hashlib import sha256
import json,time
from pathlib import Path
from typing import Any
from midprojectrag.evidence.artifacts import load_bundle
from midprojectrag.retrieval.contracts import Candidate,SearchResult
from midprojectrag.local_mini131_baseline import verify_suite
from .experience import Experience
from .mini131_pre import (_base_request,_end_to_end_followup,_is_followup,_read_records,
    _secure_append,_verify_candidate,runtime_failure_case_ids)
from .policy import AnswerComposer,Completion,LLMPolicy
from .runner import EpisodeRunner
from .state import Budgets,HarnessError
from .tools import HotlineTools
from .worker_backend import PersistentMLXBackend
from .runtime_replay import replay_record
SCHEMA="evo-runtime-recorded-replay-v1"
MODE="recorded_pre_search_results_hold_last_live_qwen_policy"
def _canonical(v:Any)->str:return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
def _index(store):
    out={};dup=set()
    for e in store.evidence:
        k=(e.doc_id,e.kind,e.text[:280])
        if k in out and out[k]!=e.evidence_id:dup.add(k)
        else:out[k]=e.evidence_id
    for k in dup:out.pop(k,None)
    return out
def recorded_search_batches(before,store):
    idx=_index(store); sections=[]; prior=before.get("prior_result")
    if type(prior) is dict:sections.append(prior)
    result=before.get("result")
    if type(result) is not dict:raise ValueError("recorded_replay_source_result_missing")
    sections.append(result); batches=[]
    for section in sections:
        for action in section.get("actions",[]):
            if type(action) is not dict or action.get("tool")!="search" or action.get("outcome")!="completed":continue
            obs=action.get("observation")
            if type(obs) is not dict:raise ValueError("recorded_replay_search_observation_missing")
            if obs.get("duplicate") is True or obs.get("empty_scope") is True:continue
            batch=[]
            for row in obs.get("candidates",[]):
                k=(row.get("doc_id"),row.get("kind"),row.get("excerpt")); eid=idx.get(k)
                if eid is None:raise ValueError("recorded_replay_candidate_not_unique")
                batch.append((eid,row["doc_id"]))
            batches.append(batch)
    return batches
class RecordedRetriever:
    def __init__(self,store,batches):
        self.store=store;self.batches=[tuple(x) for x in batches];self.used=0;self.consumed=0;self.reused=0
    def search(self,query,*,dense_k,lexical_k,scope):
        del query,dense_k,lexical_k
        if self.consumed<len(self.batches):
            batch=self.batches[self.consumed];self.consumed+=1
        elif self.batches:
            batch=self.batches[-1];self.reused+=1
        else:raise HarnessError("recorded_retrieval_exhausted")
        self.used+=1;allowed=scope.allowed_doc_ids
        rows=[x for x in batch if allowed is None or x[1] in allowed]
        cs=tuple(Candidate(eid,doc,1.0/rank,"recorded_pre",rank) for rank,(eid,doc) in enumerate(rows,1))
        return SearchResult(cs,{"lane":"recorded_pre","granularity":"child","batch":self.used})
class ReplayAnswerBackend:
    def __init__(self,backend):self.backend=backend;self.identity=backend.identity
    def count_messages(self,messages):return self.backend.count_messages(messages)
    def complete(self,messages,*,max_tokens,timeout,json_schema=None):
        del max_tokens,timeout,json_schema
        payload=json.loads(messages[-1]["content"]);labels=[];seen=set()
        for src in payload.get("sources",[]):
            if src.get("doc_id") in seen:continue
            seen.add(src.get("doc_id"));labels.append(src["label"])
            if len(labels)>=3:break
        if not labels and payload.get("sources"):labels=[payload["sources"][0]["label"]]
        text=json.dumps({"status":"answered","answer":"runtime replay","citations":labels},ensure_ascii=False,separators=(",",":"))
        return Completion(text,self.count_messages(messages),1)
def _catalog(root,store):
    out={d:"" for d in store.doc_ids};p=root/"private/manifest.extracted.jsonl"
    if p.is_file():
        for line in p.read_text().splitlines():
            if not line.strip():continue
            row=json.loads(line);doc=row.get("doc_id")
            if doc in out:out[doc]=row.get("metadata",{}).get("project_name","")
    return out
def _summary(records,*,aggregate,runner,candidate,suite_hash,target):
    before=Counter(r["selection"]["code"] for r in records);status=Counter(r["after"]["status"] for r in records)
    codes=Counter(str(r["after"].get("code")) for r in records if r["after"].get("code") is not None);usage=Counter()
    for r in records:usage.update(r["after"]["usage"])
    body={"schema_version":SCHEMA,"replay_mode":MODE,"selection_basis":"frozen_pre_runtime_terminal_code_only",
          "semantic_answer_quality":"not_evaluated","final_answer_backend":"deterministic_stub","policy_backend":"live_pinned_qwen35",
          "source_pre_candidate_commit":aggregate["candidate_commit"],"source_pre_records_sha256":aggregate["records_sha256"],
          "source_suite_sha256":suite_hash,"repaired_candidate_commit":candidate,"repaired_runner_commit":runner,
          "target_count":target,"completed_count":len(records),"before_code_counts":dict(sorted(before.items())),
          "after_status_counts":dict(sorted(status.items())),"after_code_counts":dict(sorted(codes.items())),"usage":dict(sorted(usage.items())),
          "recorded_search_batches_total":sum(r.get("recorded_search_batches_total",0) for r in records),
          "recorded_search_batches_used":sum(r.get("recorded_search_batches_used",0) for r in records),
          "recorded_search_batches_reused":sum(r.get("recorded_search_batches_reused",0) for r in records)}
    return body|{"summary_sha256":sha256(_canonical(body).encode()).hexdigest()}
def run(*,repo_root:Path,source_repo_root:Path,source_config:Path,runtime_data_root:Path,artifact_dir:Path,
        mlx_python:Path,model_dir:Path,model_manifest:Path,expected_revision:str,source_records:Path,
        source_aggregate:Path,output_dir:Path,repaired_candidate:str,limit:int|None=None):
    runner_commit=_verify_candidate(repo_root.resolve(),repaired_candidate);output_dir=output_dir.resolve();runtime_data_root=runtime_data_root.resolve()
    if "private" not in output_dir.parts or output_dir.is_symlink():raise ValueError("recorded_replay_private_output_required")
    output_dir.mkdir(parents=True,exist_ok=True,mode=0o700);rows=_read_records(source_records.resolve());aggregate=json.loads(source_aggregate.read_text())
    if aggregate.get("records_sha256")!=sha256(_canonical(rows).encode()).hexdigest():raise ValueError("recorded_replay_source_records_mismatch")
    selected=list(runtime_failure_case_ids(rows));selected_set=set(selected);before={r["case_id"]:r for r in rows if r.get("case_id") in selected_set}
    records_path=output_dir/"records.jsonl";existing=_read_records(records_path)
    if len({r.get("case_id") for r in existing})!=len(existing):raise ValueError("recorded_replay_duplicate_output_case")
    for r in existing:
        if r.get("repaired_candidate_commit")!=repaired_candidate or r.get("repaired_runner_commit")!=runner_commit or r.get("replay_mode")!=MODE:
            raise ValueError("recorded_replay_resume_identity_mismatch")
    completed={r["case_id"] for r in existing};pending=[x for x in selected if x not in completed]
    if limit is not None:
        if type(limit) is not int or limit<1:raise ValueError("recorded_replay_limit_invalid")
        pending=pending[:limit]
    suite=verify_suite(repo_root=source_repo_root.resolve(),config_path=source_config.resolve());cases={c.case_id:c for c in suite.cases}
    store,_=load_bundle(artifact_dir.resolve()/"compat",data_root=runtime_data_root);catalog=_catalog(runtime_data_root,store)
    backend=None
    try:
        for case_id in pending:
            if backend is None or not backend.alive:
                if backend is not None: backend.close()
                backend=PersistentMLXBackend(python=mlx_python,model_dir=model_dir,model_manifest=model_manifest,
                    expected_revision=expected_revision,startup_timeout=30.0,stderr_path=output_dir/"mlx-worker.stderr")
            answer=AnswerComposer(ReplayAnswerBackend(backend))
            case=cases[case_id];source=before[case_id];batches=recorded_search_batches(source,store);retriever=RecordedRetriever(store,batches)
            tools=HotlineTools(store,retriever,catalog=catalog,identity="recorded-pre-runtime-replay-v1")
            runner=EpisodeRunner(tools,LLMPolicy(backend),answer,budgets=Budgets(),experience=Experience());started=time.monotonic()
            result=_end_to_end_followup(runner,case)[0] if _is_followup(case) else runner.run(_base_request(case.request_template),record_trajectory=False)
            rec=replay_record(case,source,result,time.monotonic()-started);rec.update(replay_mode=MODE,repaired_candidate_commit=repaired_candidate,
                repaired_runner_commit=runner_commit,recorded_search_batches_total=len(batches),recorded_search_batches_used=retriever.used,
                recorded_search_batches_reused=retriever.reused)
            _secure_append(records_path,rec);existing.append(rec)
    finally:
        if backend is not None: backend.close()
    summary=_summary(existing,aggregate=aggregate,runner=runner_commit,candidate=repaired_candidate,suite_hash=suite.eval_set_sha256,target=len(selected))
    (output_dir/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,sort_keys=True,indent=2)+"\n");return summary
