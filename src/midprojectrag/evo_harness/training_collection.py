"""Live TRAIN/DEV trajectory collection for non-golden Evo policy data."""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
import json,re,subprocess,time
from pathlib import Path
from typing import Any,Mapping
from midprojectrag.ingest.common import canonical_json,sha256_file,sha256_text
from .experience import Experience
from .policy import AnswerComposer,LLMPolicy
from .runner import EpisodeRunner
from .runtime import load_hotline_tools
from .state import Budgets
from .training import read_jsonl,sft_examples_from_trajectory,validate_training_case
from .worker_backend import PersistentMLXBackend
from .visual_runtime import compose_visual_tools

SCHEMA="evo-policy-collection-v1"
TEXT_TASKS=frozenset({"fact","compare","follow_up","abstain"})
VISUAL_TASKS=frozenset({"visual","mixed"})


def _secure_append(path:Path,value:Mapping[str,Any])->None:
    import os
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
    with os.fdopen(fd,"a",encoding="utf-8") as f:
        f.write(canonical_json(dict(value))+"\n");f.flush();os.fsync(f.fileno())


def _secure_json(path:Path,value:Mapping[str,Any])->None:
    import os
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);tmp=path.with_name(path.name+".tmp")
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as f:
        f.write(json.dumps(dict(value),ensure_ascii=False,sort_keys=True,indent=2)+"\n");f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)


def _norm(value:Any)->str:
    return re.sub(r"\s+","",str(value)).casefold()


def _digits(value:Any)->str:
    return re.sub(r"\D","",str(value))


def _answer_has(answer:str,key:str,value:Any)->bool:
    if key.endswith("amount") or key.endswith("amount_value"):
        return bool(_digits(value)) and _digits(value) in _digits(answer)
    if isinstance(value,bool):
        return True
    return bool(_norm(value)) and _norm(value) in _norm(answer)

def evaluate_result(case:Mapping[str,Any],target:Mapping[str,Any],result:Mapping[str,Any])->dict[str,Any]:
    if target.get("case_id")!=case.get("case_id") or target.get("split")!=case.get("split"):
        raise ValueError("collection_target_identity_mismatch")
    status_ok=result.get("status")==target.get("terminal_status")
    actions=result.get("actions") if isinstance(result.get("actions"),list) else []
    completed_tools=[r.get("tool") for r in actions if isinstance(r,Mapping) and r.get("outcome")=="completed" and isinstance(r.get("tool"),str)]
    required=target.get("required_tools") if isinstance(target.get("required_tools"),list) else []
    tools_ok=all(tool in completed_tools for tool in required)
    response=result.get("response") if isinstance(result.get("response"),Mapping) else {}
    answer=response.get("answer") if isinstance(response.get("answer"),str) else ""
    facts=target.get("facts") if isinstance(target.get("facts"),Mapping) else {}
    fact_checks={k:_answer_has(answer,k,v) for k,v in facts.items() if k!="reason"}
    facts_ok=all(fact_checks.values()) if fact_checks else True
    if target.get("terminal_status")=="abstained": facts_ok=status_ok
    cited=response.get("cited_doc_ids") if isinstance(response.get("cited_doc_ids"),list) else []
    scope=case.get("request",{}).get("document_scope",{}).get("doc_ids",[])
    citation_ok=(target.get("terminal_status")!="answered") or (bool(cited) and set(cited)<=set(scope))
    return {"success":bool(status_ok and tools_ok and facts_ok and citation_ok),"status_ok":status_ok,
            "tools_ok":tools_ok,"facts_ok":facts_ok,"citation_ok":citation_ok,
            "fact_checks":fact_checks,"completed_tools":completed_tools}


def _follow_request(case:Mapping[str,Any],parent:Mapping[str,Any],parent_result:Mapping[str,Any])->dict[str,Any]:
    response=parent_result.get("response") if isinstance(parent_result.get("response"),Mapping) else None
    if parent_result.get("status")!="answered" or response is None: raise ValueError("collection_followup_parent_not_answered")
    prior=response.get("prior_citation_state") if isinstance(response.get("prior_citation_state"),Mapping) else {}
    docs=response.get("cited_doc_ids") if isinstance(response.get("cited_doc_ids"),list) else []
    ids=prior.get("cited_evidence_ids") if isinstance(prior.get("cited_evidence_ids"),list) else []
    if not docs or not ids: raise ValueError("collection_followup_parent_citations_missing")
    return {"question":case["question"],"history":[
        {"turn_id":parent["case_id"]+":u","role":"user","content":parent["question"]},
        {"turn_id":parent["case_id"]+":a","role":"assistant","content":response.get("answer",""),
         "cited_doc_ids":docs,"cited_evidence_ids":ids}],
        "document_scope":deepcopy(case["request"]["document_scope"]),"options":{"max_citations":3}}


def _verify_head(repo_root:Path,candidate_commit:str)->str:
    actual=subprocess.check_output(["git","rev-parse","HEAD"],cwd=repo_root,text=True).strip()
    if subprocess.run(["git","merge-base","--is-ancestor",candidate_commit,actual],cwd=repo_root).returncode!=0:
        raise ValueError("collection_candidate_not_ancestor")
    return actual

def _replace_jsonl(path:Path,rows:list[Mapping[str,Any]])->None:
    import os
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);tmp=path.with_name(path.name+".tmp")
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as f:
        for row in rows: f.write(canonical_json(dict(row))+"\n")
        f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)


def collect_text(*,repo_root:Path,cases_path:Path,targets_path:Path,runtime_data_root:Path,artifact_dir:Path,
                 mlx_python:Path,model_dir:Path,model_manifest:Path,expected_revision:str,output_dir:Path,
                 candidate_commit:str,limit:int|None=None,export_sft:bool=False)->dict[str,Any]:
    runner_commit=_verify_head(repo_root.resolve(),candidate_commit);output_dir=output_dir.resolve()
    if "private" not in output_dir.parts or output_dir.is_symlink(): raise ValueError("collection_private_output_required")
    cases=read_jsonl(cases_path);targets=read_jsonl(targets_path)
    if any(c.get("split")=="sealed_holdout" for c in cases): raise ValueError("collection_sealed_holdout_forbidden")
    for c in cases: validate_training_case(c)
    target_map={t.get("case_id"):t for t in targets}
    if len(target_map)!=len(targets) or set(target_map)!={c["case_id"] for c in cases}: raise ValueError("collection_target_set_mismatch")
    selected=[c for c in cases if c.get("task_type") in TEXT_TASKS]
    output_dir.mkdir(parents=True,exist_ok=True,mode=0o700);records_path=output_dir/"records.jsonl"
    existing=read_jsonl(records_path) if records_path.exists() else []
    for r in existing:
        if r.get("candidate_commit")!=candidate_commit or r.get("runner_commit")!=runner_commit: raise ValueError("collection_resume_identity_mismatch")
    completed={r["case_id"] for r in existing};results={r["case_id"]:r.get("result") for r in existing}
    case_map={c["case_id"]:c for c in cases};tools=load_hotline_tools(runtime_data_root.resolve(),artifact_dir.resolve(),device="mps")
    backend=None;attempted=0;model_load_seconds=0.0;worker_manifest_sha256=None
    try:
        for case in selected:
            if case["case_id"] in completed: continue
            if limit is not None and attempted>=limit: break
            if backend is None or not backend.alive:
                if backend is not None: backend.close()
                backend=PersistentMLXBackend(python=mlx_python,model_dir=model_dir,model_manifest=model_manifest,
                    expected_revision=expected_revision,startup_timeout=30.0,stderr_path=output_dir/"mlx-worker.stderr")
                model_load_seconds+=backend.load_seconds;worker_manifest_sha256=backend.manifest_sha256
            runner=EpisodeRunner(tools,LLMPolicy(backend),AnswerComposer(backend),budgets=Budgets(),experience=Experience())
            started=time.monotonic()
            try:
                if case.get("task_type")=="follow_up":
                    pid=case.get("follow_up_parent_case_id");parent=case_map.get(pid);parent_result=results.get(pid)
                    if not isinstance(parent,Mapping) or not isinstance(parent_result,Mapping): raise ValueError("collection_followup_parent_missing")
                    request=_follow_request(case,parent,parent_result)
                    result=runner.run(request,follow_up=True,record_trajectory=True)
                else:
                    result=runner.run(deepcopy(case["request"]),record_trajectory=True)
            except ValueError as exc:
                result={"status":"error","code":str(exc),"response":None,"actions":[],"trajectory":[],"usage":{},"wall_seconds":time.monotonic()-started}
            evaluation=evaluate_result(case,target_map[case["case_id"]],result)
            record={"schema_version":SCHEMA,"case_id":case["case_id"],"split":case["split"],"task_type":case["task_type"],
                    "candidate_commit":candidate_commit,"runner_commit":runner_commit,"case_sha256":sha256_text(canonical_json(case)),
                    "target_sha256":sha256_text(canonical_json(target_map[case["case_id"]])),"evaluation":evaluation,
                    "result":result,"wall_seconds":time.monotonic()-started}
            _secure_append(records_path,record);existing.append(record);completed.add(case["case_id"]);results[case["case_id"]]=result;attempted+=1
    finally:
        if backend is not None: backend.close()
    relevant=[r for r in existing if r.get("case_id") in {c["case_id"] for c in selected}]
    positive=[]
    if export_sft:
        for r in relevant:
            if r.get("split")!="train" or not r.get("evaluation",{}).get("success"): continue
            positive.extend(sft_examples_from_trajectory(r["result"],case_map[r["case_id"]]))
        _replace_jsonl(output_dir/"positive-sft.jsonl",positive)
    statuses=Counter(str(r.get("result",{}).get("status")) for r in relevant);usage=Counter();task_total=Counter();task_success=Counter()
    for r in relevant:
        task_total[r["task_type"]]+=1
        if r.get("evaluation",{}).get("success"): task_success[r["task_type"]]+=1
        u=r.get("result",{}).get("usage",{})
        if isinstance(u,Mapping): usage.update({k:v for k,v in u.items() if type(v) is int})
    summary={"schema_version":SCHEMA,"mode":"live_pinned_qwen35_text_train_dev","candidate_commit":candidate_commit,
             "runner_commit":runner_commit,"cases_sha256":sha256_file(cases_path),"targets_sha256":sha256_file(targets_path),
             "selected_count":len(selected),"completed_count":len(relevant),"success_count":sum(task_success.values()),
             "status_counts":dict(sorted(statuses.items())),"task_total":dict(sorted(task_total.items())),
             "task_success":dict(sorted(task_success.items())),"usage":dict(sorted(usage.items())),
             "positive_sft_examples":len(positive) if export_sft else None,"model_load_seconds":model_load_seconds,
             "worker_manifest_sha256":worker_manifest_sha256,"sealed_holdout_executed":False}
    if export_sft: summary["positive_sft_sha256"]=sha256_file(output_dir/"positive-sft.jsonl")
    summary["summary_sha256"]=sha256_text(canonical_json(summary));_secure_json(output_dir/"summary.json",summary);return summary


def collect_visual(*,repo_root:Path,cases_path:Path,targets_path:Path,runtime_data_root:Path,artifact_dir:Path,
                   mlx_python:Path,model_dir:Path,model_manifest:Path,expected_revision:str,output_dir:Path,
                   candidate_commit:str,index_dir:Path,visual_private_root:Path,crop_root:Path,query_python:Path,
                   hf_cache:Path,limit:int|None=None,export_sft:bool=False)->dict[str,Any]:
    runner_commit=_verify_head(repo_root.resolve(),candidate_commit);output_dir=output_dir.resolve()
    if "private" not in output_dir.parts or output_dir.is_symlink(): raise ValueError("collection_private_output_required")
    cases=read_jsonl(cases_path);targets=read_jsonl(targets_path)
    if any(c.get("split")=="sealed_holdout" for c in cases): raise ValueError("collection_sealed_holdout_forbidden")
    for c in cases: validate_training_case(c)
    target_map={t.get("case_id"):t for t in targets}
    if len(target_map)!=len(targets) or set(target_map)!={c["case_id"] for c in cases}: raise ValueError("collection_target_set_mismatch")
    selected=[c for c in cases if c.get("task_type") in VISUAL_TASKS]
    output_dir.mkdir(parents=True,exist_ok=True,mode=0o700);records_path=output_dir/"records.jsonl"
    existing=read_jsonl(records_path) if records_path.exists() else []
    for r in existing:
        if r.get("candidate_commit")!=candidate_commit or r.get("runner_commit")!=runner_commit: raise ValueError("collection_resume_identity_mismatch")
    completed={r["case_id"] for r in existing}
    base=load_hotline_tools(runtime_data_root.resolve(),artifact_dir.resolve(),device="mps")
    backend=None;tools=None;attempted=0;model_load_seconds=0.0;worker_manifest_sha256=None;generation=0
    try:
        for case in selected:
            if case["case_id"] in completed: continue
            if limit is not None and attempted>=limit: break
            if backend is None or not backend.alive:
                if backend is not None: backend.close()
                backend=PersistentMLXBackend(python=mlx_python,model_dir=model_dir,model_manifest=model_manifest,
                    expected_revision=expected_revision,startup_timeout=30.0,stderr_path=output_dir/"mlx-worker.stderr")
                model_load_seconds+=backend.load_seconds;worker_manifest_sha256=backend.manifest_sha256;generation+=1
                tools=compose_visual_tools(backend,base=base,index_dir=index_dir,private_root=visual_private_root,
                    crop_root=crop_root,python=query_python,hf_cache=hf_cache,work_dir=output_dir/f"visual-query-{generation:02d}")
            runner=EpisodeRunner(tools,LLMPolicy(backend),AnswerComposer(backend),budgets=Budgets(),experience=Experience())
            started=time.monotonic()
            try:
                result=runner.run(deepcopy(case["request"]),record_trajectory=True)
            except ValueError as exc:
                result={"status":"error","code":str(exc),"response":None,"actions":[],"trajectory":[],"usage":{},"wall_seconds":time.monotonic()-started}
            evaluation=evaluate_result(case,target_map[case["case_id"]],result)
            record={"schema_version":SCHEMA,"case_id":case["case_id"],"split":case["split"],"task_type":case["task_type"],
                    "candidate_commit":candidate_commit,"runner_commit":runner_commit,"case_sha256":sha256_text(canonical_json(case)),
                    "target_sha256":sha256_text(canonical_json(target_map[case["case_id"]])),"evaluation":evaluation,
                    "result":result,"wall_seconds":time.monotonic()-started}
            _secure_append(records_path,record);existing.append(record);completed.add(case["case_id"]);attempted+=1
    finally:
        if backend is not None: backend.close()
    relevant=[r for r in existing if r.get("case_id") in {c["case_id"] for c in selected}]
    case_map={c["case_id"]:c for c in cases};positive=[]
    if export_sft:
        for r in relevant:
            if r.get("split")!="train" or not r.get("evaluation",{}).get("success"): continue
            positive.extend(sft_examples_from_trajectory(r["result"],case_map[r["case_id"]]))
        _replace_jsonl(output_dir/"positive-sft.jsonl",positive)
    statuses=Counter(str(r.get("result",{}).get("status")) for r in relevant);usage=Counter();task_total=Counter();task_success=Counter()
    for r in relevant:
        task_total[r["task_type"]]+=1
        if r.get("evaluation",{}).get("success"): task_success[r["task_type"]]+=1
        u=r.get("result",{}).get("usage",{})
        if isinstance(u,Mapping): usage.update({k:v for k,v in u.items() if type(v) is int})
    summary={"schema_version":SCHEMA,"mode":"live_pinned_qwen35_visual_train_dev","candidate_commit":candidate_commit,
             "runner_commit":runner_commit,"cases_sha256":sha256_file(cases_path),"targets_sha256":sha256_file(targets_path),
             "selected_count":len(selected),"completed_count":len(relevant),"success_count":sum(task_success.values()),
             "status_counts":dict(sorted(statuses.items())),"task_total":dict(sorted(task_total.items())),
             "task_success":dict(sorted(task_success.items())),"usage":dict(sorted(usage.items())),
             "positive_sft_examples":len(positive) if export_sft else None,"model_load_seconds":model_load_seconds,
             "worker_manifest_sha256":worker_manifest_sha256,"sealed_holdout_executed":False,
             "visual_index_metadata_sha256":sha256_file(index_dir/"metadata.json")}
    if export_sft: summary["positive_sft_sha256"]=sha256_file(output_dir/"positive-sft.jsonl")
    summary["summary_sha256"]=sha256_text(canonical_json(summary));_secure_json(output_dir/"summary.json",summary);return summary
