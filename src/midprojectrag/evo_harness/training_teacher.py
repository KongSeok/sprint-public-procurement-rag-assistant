"""Deterministic, externally validated teacher actions for non-golden TRAIN data."""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import json,re,subprocess,time
from pathlib import Path
from typing import Any,Mapping,Sequence
from midprojectrag.ingest.common import canonical_json,sha256_file,sha256_text
from .experience import Experience
from .policy import Completion,LLMPolicy
from .runtime import load_hotline_tools
from .state import Budgets,action_from_json
from .training import read_jsonl,sft_examples_from_trajectory,validate_training_case
from .training_collection import _follow_request
from .worker_backend import PersistentMLXBackend

SCHEMA="evo-policy-teacher-collection-v1"
TEXT_TASKS=frozenset({"fact","compare","follow_up","abstain"})


def _norm(value:Any)->str:return re.sub(r"\s+","",str(value)).casefold()
def _digits(value:Any)->str:return re.sub(r"\D","",str(value))

def _present(text:str,key:str,value:Any)->bool:
    if key.endswith("amount") or key.endswith("amount_value"):
        return bool(_digits(value)) and _digits(value) in _digits(text)
    return bool(_norm(value)) and _norm(value) in _norm(text)

def _candidate_score(target:Mapping[str,Any],candidate:Mapping[str,Any])->int:
    text=str(candidate.get("excerpt", ""));facts=target.get("facts") if isinstance(target.get("facts"),Mapping) else {}
    return sum(int(_present(text,key,value)) for key,value in facts.items() if key!="reason" and not isinstance(value,bool))

def _query_variants(case:Mapping[str,Any],target:Mapping[str,Any],episode,doc_id:str)->list[str]:
    title=next((row.get("title") for row in episode.catalog if row.get("doc_id")==doc_id),None)
    if not isinstance(title,str) or not title:raise ValueError("teacher_catalog_title_missing")
    facts=target.get("facts") if isinstance(target.get("facts"),Mapping) else {}
    question=str(case.get("question",""))
    if any(k.endswith("amount") or k.endswith("amount_value") for k in facts) or "금액" in question:
        field="사업금액"
    elif any("agency" in k for k in facts) or "발주기관" in question:
        field="발주기관"
    else:
        field="사업명"
    base=re.sub(r"\s+"," ",title.replace("·"," ")).strip()
    variants=[base+" "+field]
    if field=="발주기관":variants.append(base+" 발주처 발주기관 수요기관")
    elif field=="사업금액":variants.append(base+" 사업비 예산 사업금액")
    return variants


class TeacherBackend:
    """Use the pinned backend only for exact chat-template token counts."""
    def __init__(self,delegate):
        self.delegate=delegate;self.identity=delegate.identity;self.pending=None;self.last_count=None
    def count_messages(self,messages):
        self.last_count=self.delegate.count_messages(messages);return self.last_count
    def set_action(self,action:Mapping[str,Any])->None:
        raw=canonical_json(dict(action));action_from_json(raw);self.pending=raw
    def complete(self,messages,*,max_tokens,timeout,json_schema=None):
        if self.pending is None or self.last_count is None:raise ValueError("teacher_action_not_staged")
        raw=self.pending;self.pending=None
        return Completion(raw,self.last_count,0,"stop")

def _supporting_handles(target:Mapping[str,Any],episode,*,require_docs:Sequence[str]=())->list[str]:
    facts=target.get("facts") if isinstance(target.get("facts"),Mapping) else {}
    handles=[]
    for key,value in facts.items():
        if key=="reason" or isinstance(value,bool):continue
        found=None
        for evidence_id,window in episode.windows.items():
            if _present(window["text"],key,value):found=episode.read_handle(evidence_id);break
        if found is None:return []
        if found not in handles:handles.append(found)
    if require_docs:
        covered={window["doc_id"] for window in episode.windows.values()}
        if not set(require_docs)<=covered:return []
    return handles


def _action(policy:LLMPolicy,backend:TeacherBackend,episode,tools,budget:Budgets,experience:Experience,
            events:list[dict[str,Any]],action:Mapping[str,Any],remaining)->tuple[dict[str,Any],dict[str,Any]|None]:
    backend.set_action(action);raw=policy.propose(episode,budget,remaining);parsed=action_from_json(raw)
    event={"ordinal":len(events)+1,"outcome":"attempted","tool":parsed["tool"],"arguments":deepcopy(parsed["arguments"])};events.append(event)
    if parsed["tool"]=="finish":event["outcome"]="completed";return parsed,None
    obs=tools.dispatch(episode,parsed,budget,remaining,experience);episode.last_observation=obs
    event.update(outcome="completed",observation=obs);return parsed,obs


def _result(episode,events,status:str,evidence_handles:Sequence[str])->dict[str,Any]:
    canonical=[episode.reference(handle,read=True) for handle in evidence_handles]
    cited_docs=sorted({episode.windows[eid]["doc_id"] for eid in canonical})
    response={"status":status,"answer":"" if status!="answered" else "teacher_evidence_validated","citations":[],
              "cited_doc_ids":cited_docs,"prior_citation_state":{"cited_doc_ids":cited_docs,
              "cited_evidence_ids":sorted(canonical),"resolved_entities":[],"list_doc_ids":[],"comparison_doc_ids":cited_docs if len(cited_docs)>1 else []}}
    return {"status":status,"code":None,"response":response,"actions":events,"trajectory":episode.trajectory,
            "usage":asdict(episode.usage),"semantic_verified":False,"teacher_generated_actions":True}


def run_teacher_case(case:Mapping[str,Any],target:Mapping[str,Any],*,tools,count_backend,
                     parent_case:Mapping[str,Any]|None=None,parent_result:Mapping[str,Any]|None=None)->dict[str,Any]:
    validate_training_case(case)
    if case["split"]!="train":raise ValueError("teacher_train_only")
    if case["task_type"] not in TEXT_TASKS:raise ValueError("teacher_text_task_required")
    if target.get("case_id")!=case["case_id"]:raise ValueError("teacher_target_identity_mismatch")
    request=deepcopy(case["request"]);follow=False
    if case["task_type"]=="follow_up":
        if parent_case is None or parent_result is None:raise ValueError("teacher_followup_parent_required")
        request=_follow_request(case,parent_case,parent_result);follow=True
    episode=tools.begin(request,follow_up=follow);budget=Budgets();experience=Experience();episode.recall_available=False
    backend=TeacherBackend(count_backend);policy=LLMPolicy(backend);events=[];started=time.monotonic();deadline=started+budget.seconds
    def remaining():
        value=deadline-time.monotonic()
        if value<=0:raise TimeoutError("teacher_deadline")
        return value
    if target.get("terminal_status")=="abstained":
        finish={"tool":"finish","arguments":{"status":"abstained","evidence_ids":[],"unresolved":[]}}
        _action(policy,backend,episode,tools,budget,experience,events,finish,remaining)
        result=_result(episode,events,"abstained",[]);result["teacher_validation"]={"success":True,"target_supported_in_read_windows":True,"required_docs_read":True}
        result["wall_seconds"]=time.monotonic()-started;return result
    scope=list(case["request"]["document_scope"]["doc_ids"])
    search_scopes=[[doc] for doc in scope] if case["task_type"] in {"compare","follow_up"} else [scope]
    required_docs=scope if case["task_type"] in {"compare","follow_up"} else scope
    handles=[]
    for narrowed in search_scopes:
        variants=_query_variants(case,target,episode,narrowed[0]);variants=variants[:1] if len(scope)>1 else variants[:2]
        for query in variants:
            search={"tool":"search","arguments":{"query":query,"doc_ids":narrowed,"limit":10}}
            _,obs=_action(policy,backend,episode,tools,budget,experience,events,search,remaining)
            candidates=list((obs or {}).get("candidates",[]))
            ranked=sorted(enumerate(candidates),key=lambda pair:(-_candidate_score(target,pair[1]),pair[0]))
            if ranked:
                top_score=_candidate_score(target,ranked[0][1]);read_cap=1 if top_score>0 else 2
                for _,candidate in ranked[:min(read_cap,budget.read_calls-episode.usage.read_calls)]:
                    read={"tool":"read","arguments":{"evidence_ids":[candidate["id"]]}}
                    _action(policy,backend,episode,tools,budget,experience,events,read,remaining)
                    handles=_supporting_handles(target,episode,require_docs=required_docs)
                    if handles and (len(scope)==1 or narrowed==search_scopes[-1]):break
            if handles and (len(scope)==1 or narrowed==search_scopes[-1]):break
            if episode.usage.read_calls>=budget.read_calls:break
        if handles and (len(scope)==1 or narrowed==search_scopes[-1]):break
        if episode.usage.read_calls>=budget.read_calls:break
    if handles:
        finish={"tool":"finish","arguments":{"status":"answered","evidence_ids":handles,"unresolved":[]}}
        _action(policy,backend,episode,tools,budget,experience,events,finish,remaining)
        result=_result(episode,events,"answered",handles);success=True
    else:
        finish={"tool":"finish","arguments":{"status":"needs_clarification","evidence_ids":[],"unresolved":["teacher_target_not_found_in_read_windows"]}}
        _action(policy,backend,episode,tools,budget,experience,events,finish,remaining)
        result=_result(episode,events,"needs_clarification",[]);success=False
    result["teacher_validation"]={"success":success,"target_supported_in_read_windows":bool(handles),
                                  "required_docs_read":set(required_docs)<={w["doc_id"] for w in episode.windows.values()}}
    result["wall_seconds"]=time.monotonic()-started
    return result


def _replace_jsonl(path:Path,rows:list[Mapping[str,Any]])->None:
    import os
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);tmp=path.with_name(path.name+".tmp")
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as f:
        for row in rows:f.write(canonical_json(dict(row))+"\n")
        f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)


def _append(path:Path,row:Mapping[str,Any])->None:
    import os
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
    with os.fdopen(fd,"a",encoding="utf-8") as f:f.write(canonical_json(dict(row))+"\n");f.flush();os.fsync(f.fileno())

def collect_teacher(*,repo_root:Path,cases_path:Path,targets_path:Path,runtime_data_root:Path,artifact_dir:Path,
                    mlx_python:Path,model_dir:Path,model_manifest:Path,expected_revision:str,
                    output_dir:Path,candidate_commit:str,limit:int|None=None)->dict[str,Any]:
    actual=subprocess.check_output(["git","rev-parse","HEAD"],cwd=repo_root,text=True).strip()
    if subprocess.run(["git","merge-base","--is-ancestor",candidate_commit,actual],cwd=repo_root).returncode!=0:
        raise ValueError("teacher_candidate_not_ancestor")
    cases=read_jsonl(cases_path);targets=read_jsonl(targets_path)
    if any(c.get("split")!="train" for c in cases):raise ValueError("teacher_train_only")
    for c in cases:validate_training_case(c)
    target_map={t.get("case_id"):t for t in targets}
    if len(target_map)!=len(targets) or set(target_map)!={c["case_id"] for c in cases}:raise ValueError("teacher_target_set_mismatch")
    selected=[c for c in cases if c.get("task_type") in TEXT_TASKS]
    if "private" not in output_dir.resolve().parts or output_dir.is_symlink():raise ValueError("teacher_private_output_required")
    output_dir.mkdir(parents=True,exist_ok=True,mode=0o700);records_path=output_dir/"records.jsonl"
    existing=read_jsonl(records_path) if records_path.exists() else []
    for r in existing:
        if r.get("candidate_commit")!=candidate_commit or r.get("runner_commit")!=actual:raise ValueError("teacher_resume_identity_mismatch")
    completed={r["case_id"] for r in existing};results={r["case_id"]:r.get("result") for r in existing};case_map={c["case_id"]:c for c in cases}
    tools=load_hotline_tools(runtime_data_root.resolve(),artifact_dir.resolve(),device="mps");attempted=0
    with PersistentMLXBackend(python=mlx_python,model_dir=model_dir,model_manifest=model_manifest,
                              expected_revision=expected_revision,startup_timeout=30.0,
                              stderr_path=output_dir/"mlx-worker.stderr") as count_backend:
        for case in selected:
            if case["case_id"] in completed:continue
            if limit is not None and attempted>=limit:break
            parent=None;parent_result=None
            if case["task_type"]=="follow_up":
                pid=case.get("follow_up_parent_case_id");parent=case_map.get(pid);parent_result=results.get(pid)
            try:
                result=run_teacher_case(case,target_map[case["case_id"]],tools=tools,count_backend=count_backend,
                                        parent_case=parent,parent_result=parent_result)
            except Exception as exc:
                result={"status":"error","code":str(exc) if isinstance(exc,ValueError) else type(exc).__name__,
                        "actions":[],"trajectory":[],"usage":{},"teacher_validation":{"success":False}}
            rec={"schema_version":SCHEMA,"case_id":case["case_id"],"task_type":case["task_type"],"split":"train",
                 "candidate_commit":candidate_commit,"runner_commit":actual,"case_sha256":sha256_text(canonical_json(case)),
                 "target_sha256":sha256_text(canonical_json(target_map[case["case_id"]])),"result":result}
            _append(records_path,rec);existing.append(rec);completed.add(case["case_id"]);results[case["case_id"]]=result;attempted+=1
    positives=[];status=Counter();task_total=Counter();task_success=Counter();usage=Counter()
    for rec in existing:
        if rec.get("case_id") not in {c["case_id"] for c in selected}:continue
        result=rec.get("result") if isinstance(rec.get("result"),Mapping) else {}
        task=rec["task_type"];task_total[task]+=1;status[str(result.get("status"))]+=1
        if result.get("teacher_validation",{}).get("success"):
            task_success[task]+=1;positives.extend(sft_examples_from_trajectory(result,case_map[rec["case_id"]]))
        u=result.get("usage")
        if isinstance(u,Mapping):usage.update({k:v for k,v in u.items() if type(v) is int})
    _replace_jsonl(output_dir/"positive-sft.jsonl",positives)
    summary={"schema_version":SCHEMA,"mode":"deterministic_validated_teacher_actions","candidate_commit":candidate_commit,
             "runner_commit":actual,"cases_sha256":sha256_file(cases_path),"targets_sha256":sha256_file(targets_path),
             "selected_count":len(selected),"completed_count":sum(task_total.values()),"success_count":sum(task_success.values()),
             "status_counts":dict(sorted(status.items())),"task_total":dict(sorted(task_total.items())),
             "task_success":dict(sorted(task_success.items())),"positive_sft_examples":len(positives),
             "positive_sft_sha256":sha256_file(output_dir/"positive-sft.jsonl"),"usage":dict(sorted(usage.items())),
             "policy_completion_calls":0,"sealed_holdout_executed":False,"teacher_uses_target_only_for_external_support_gate":True}
    summary["summary_sha256"]=sha256_text(canonical_json(summary))
    (output_dir/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    return summary
