"""Deterministic validated visual/mixed teacher actions for non-golden TRAIN."""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
import json,subprocess,time
from pathlib import Path
from typing import Any,Mapping
from midprojectrag.ingest.common import canonical_json,sha256_file,sha256_text
from .experience import Experience
from .policy import LLMPolicy
from .runtime import load_hotline_tools
from .state import Budgets
from .training import read_jsonl,sft_examples_from_trajectory,validate_training_case
from .training_teacher import TeacherBackend,_action,_candidate_score,_query_variants,_result,_supporting_handles,_append,_replace_jsonl
from .visual_runtime import compose_visual_tools
from .worker_backend import PersistentMLXBackend

SCHEMA="evo-policy-visual-teacher-collection-v1"
VISUAL_TASKS=frozenset({"visual","mixed"})
VISUAL_SEARCH_QUERY="문서 삽입 이미지 도표 화면 시각 요소"
VISUAL_INSPECTION_QUESTION="이 crop에서 실제 삽입 이미지, 도표, 화면 또는 기타 시각 요소가 보이는지 판독하고, 보이는 시각 요소만 설명해줘."


def run_visual_teacher_case(case:Mapping[str,Any],target:Mapping[str,Any],*,tools,count_backend)->dict[str,Any]:
    validate_training_case(case)
    if case["split"]!="train": raise ValueError("visual_teacher_train_only")
    if case["task_type"] not in VISUAL_TASKS: raise ValueError("visual_teacher_task_required")
    if target.get("case_id")!=case["case_id"]: raise ValueError("visual_teacher_target_identity_mismatch")
    episode=tools.begin(deepcopy(case["request"])); budget=Budgets(); experience=Experience(); episode.recall_available=False
    backend=TeacherBackend(count_backend); policy=LLMPolicy(backend); events=[]; started=time.monotonic(); deadline=started+budget.seconds
    def remaining():
        value=deadline-time.monotonic()
        if value<=0: raise TimeoutError("visual_teacher_deadline")
        return value
    scope=list(case["request"]["document_scope"]["doc_ids"]); text_handles=[]
    if case["task_type"]=="mixed":
        for query in _query_variants(case,target,episode,scope[0])[:2]:
            _,obs=_action(policy,backend,episode,tools,budget,experience,events,{"tool":"search","arguments":{"query":query,"doc_ids":scope,"limit":10}},remaining)
            candidates=list((obs or {}).get("candidates",[])); ranked=sorted(enumerate(candidates),key=lambda pair:(-_candidate_score(target,pair[1]),pair[0]))
            for _,candidate in ranked[:min(2,budget.read_calls-episode.usage.read_calls)]:
                _action(policy,backend,episode,tools,budget,experience,events,{"tool":"read","arguments":{"evidence_ids":[candidate["id"]]}},remaining)
                text_handles=_supporting_handles(target,episode,require_docs=scope)
                if text_handles: break
            if text_handles: break
    _,vobs=_action(policy,backend,episode,tools,budget,experience,events,{"tool":"visual_search","arguments":{"query":VISUAL_SEARCH_QUERY,"doc_ids":scope,"limit":5}},remaining)
    visual_handle=None
    for candidate in list((vobs or {}).get("candidates",[]))[:budget.image_calls]:
        _,iobs=_action(policy,backend,episode,tools,budget,experience,events,{"tool":"inspect_image","arguments":{"evidence_id":candidate["id"],"question":VISUAL_INSPECTION_QUESTION}},remaining)
        if (iobs or {}).get("usable_in_finish") and isinstance((iobs or {}).get("finish_evidence_id"),str):
            visual_handle=iobs["finish_evidence_id"];break
    handles=[*text_handles,*([visual_handle] if visual_handle else [])]
    text_ok=case["task_type"]=="visual" or bool(text_handles); visual_ok=visual_handle is not None
    if text_ok and visual_ok:
        _action(policy,backend,episode,tools,budget,experience,events,{"tool":"finish","arguments":{"status":"answered","evidence_ids":handles,"unresolved":[]}},remaining)
        result=_result(episode,events,"answered",handles); success=True
    else:
        _action(policy,backend,episode,tools,budget,experience,events,{"tool":"finish","arguments":{"status":"needs_clarification","evidence_ids":[],"unresolved":["validated_visual_teacher_evidence_missing"]}},remaining)
        result=_result(episode,events,"needs_clarification",[]); success=False
    result["teacher_validation"]={"success":success,"text_supported":text_ok,"visual_inspection_usable":visual_ok,"required_docs_read":set(scope)<={w["doc_id"] for w in episode.windows.values()}}
    result["wall_seconds"]=time.monotonic()-started; return result


def collect_visual_teacher(*,repo_root:Path,cases_path:Path,targets_path:Path,runtime_data_root:Path,artifact_dir:Path,
                           mlx_python:Path,model_dir:Path,model_manifest:Path,expected_revision:str,output_dir:Path,
                           candidate_commit:str,index_dir:Path,visual_private_root:Path,crop_root:Path,query_python:Path,hf_cache:Path,
                           limit:int|None=None)->dict[str,Any]:
    actual=subprocess.check_output(["git","rev-parse","HEAD"],cwd=repo_root,text=True).strip()
    if subprocess.run(["git","merge-base","--is-ancestor",candidate_commit,actual],cwd=repo_root).returncode!=0: raise ValueError("visual_teacher_candidate_not_ancestor")
    cases=read_jsonl(cases_path); targets=read_jsonl(targets_path)
    if any(c.get("split")!="train" for c in cases): raise ValueError("visual_teacher_train_only")
    for c in cases: validate_training_case(c)
    target_map={t.get("case_id"):t for t in targets}
    if len(target_map)!=len(targets) or set(target_map)!={c["case_id"] for c in cases}: raise ValueError("visual_teacher_target_set_mismatch")
    selected=[c for c in cases if c.get("task_type") in VISUAL_TASKS]
    if "private" not in output_dir.resolve().parts or output_dir.is_symlink(): raise ValueError("visual_teacher_private_output_required")
    output_dir.mkdir(parents=True,exist_ok=True,mode=0o700); records_path=output_dir/"records.jsonl"
    existing=read_jsonl(records_path) if records_path.exists() else []
    completed={r["case_id"] for r in existing}; base=load_hotline_tools(runtime_data_root.resolve(),artifact_dir.resolve(),device="mps"); attempted=0; generation=0
    with PersistentMLXBackend(python=mlx_python,model_dir=model_dir,model_manifest=model_manifest,expected_revision=expected_revision,startup_timeout=30.0,stderr_path=output_dir/"mlx-worker.stderr") as count_backend:
        generation+=1
        tools=compose_visual_tools(count_backend,base=base,index_dir=index_dir,private_root=visual_private_root,crop_root=crop_root,python=query_python,hf_cache=hf_cache,work_dir=output_dir/f"visual-query-{generation:02d}")
        for case in selected:
            if case["case_id"] in completed: continue
            if limit is not None and attempted>=limit: break
            try: result=run_visual_teacher_case(case,target_map[case["case_id"]],tools=tools,count_backend=count_backend)
            except Exception as exc: result={"status":"error","code":str(exc) if isinstance(exc,ValueError) else type(exc).__name__,"actions":[],"trajectory":[],"usage":{},"teacher_validation":{"success":False}}
            rec={"schema_version":SCHEMA,"case_id":case["case_id"],"task_type":case["task_type"],"split":"train","candidate_commit":candidate_commit,"runner_commit":actual,"case_sha256":sha256_text(canonical_json(case)),"target_sha256":sha256_text(canonical_json(target_map[case["case_id"]])),"result":result}
            _append(records_path,rec);existing.append(rec);completed.add(case["case_id"]);attempted+=1
    case_map={c["case_id"]:c for c in cases}; positives=[];status=Counter();task_total=Counter();task_success=Counter();usage=Counter()
    for rec in existing:
        if rec.get("case_id") not in {c["case_id"] for c in selected}: continue
        result=rec.get("result") if isinstance(rec.get("result"),Mapping) else {}; task=rec["task_type"];task_total[task]+=1;status[str(result.get("status"))]+=1
        if result.get("teacher_validation",{}).get("success"):
            task_success[task]+=1;positives.extend(sft_examples_from_trajectory(result,case_map[rec["case_id"]]))
        u=result.get("usage")
        if isinstance(u,Mapping): usage.update({k:v for k,v in u.items() if type(v) is int})
    _replace_jsonl(output_dir/"positive-sft.jsonl",positives)
    summary={"schema_version":SCHEMA,"mode":"deterministic_validated_visual_teacher_actions","candidate_commit":candidate_commit,"runner_commit":actual,"cases_sha256":sha256_file(cases_path),"targets_sha256":sha256_file(targets_path),"selected_count":len(selected),"completed_count":sum(task_total.values()),"success_count":sum(task_success.values()),"status_counts":dict(sorted(status.items())),"task_total":dict(sorted(task_total.items())),"task_success":dict(sorted(task_success.items())),"positive_sft_examples":len(positives),"positive_sft_sha256":sha256_file(output_dir/"positive-sft.jsonl"),"usage":dict(sorted(usage.items())),"policy_completion_calls":0,"sealed_holdout_executed":False,"teacher_uses_target_only_for_external_support_gate":True,"visual_index_metadata_sha256":sha256_file(index_dir/"metadata.json")}
    summary["summary_sha256"]=sha256_text(canonical_json(summary));(output_dir/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8");return summary
