"""Deterministic non-golden task authoring for Evo policy training."""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping, Sequence
from midprojectrag.ingest.common import canonical_json, sha256_file, sha256_text
from .training import TRAINING_CASE_SCHEMA, freeze_splits, validate_exclusion_manifest

AUTHORING_SCHEMA="evo-nongolden-authoring-v1"
TARGET_SCHEMA="evo-nongolden-validation-target-v1"
PARTITION_SCHEMA="evo-nongolden-document-partition-v1"
DEFAULT_SPLIT_DOC_COUNTS={"sealed_holdout":6,"dev":6,"train":17}
MINI_SOURCES=("core40","supplemental_answers","supplemental_sets","visual","analytics")


def _rows(path:Path)->list[dict[str,Any]]:
    out=[]
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                v=json.loads(line)
                if not isinstance(v,dict): raise ValueError("nongolden_jsonl_object_required")
                out.append(v)
    return out


def _within(root:Path,value:str|Path)->Path:
    root=root.resolve();p=(root/value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
    if p!=root and root not in p.parents: raise ValueError("nongolden_path_outside_root")
    return p


def _doc_ids(row:Mapping[str,Any])->list[str]:
    scope=row.get("document_scope")
    if isinstance(scope,Mapping) and isinstance(scope.get("doc_ids"),list): raw=scope["doc_ids"]
    else:
        raw=[]
        for key in ("scope_doc_ids","required_doc_ids","source_document_ids"):
            if isinstance(row.get(key),list): raw=row[key];break
    if any(not isinstance(v,str) or not v for v in raw): raise ValueError("nongolden_doc_ids_invalid")
    return sorted(set(raw))


def historical_referenced_doc_ids(*,source_repo_root:Path,mini131_config:Path,extra_evaluation_paths:Sequence[Path])->tuple[str,...]:
    root=source_repo_root.resolve();cfg=json.loads(_within(root,mini131_config).read_text())
    if not isinstance(cfg.get("sources"),Mapping): raise ValueError("nongolden_mini131_config_invalid")
    paths=[];rag=0
    for name in MINI_SOURCES:
        spec=cfg["sources"].get(name)
        if not isinstance(spec,Mapping): raise ValueError("nongolden_mini131_source_invalid")
        p=_within(root,str(spec.get("path")))
        if sha256_file(p)!=spec.get("sha256"): raise ValueError("nongolden_mini131_source_hash_mismatch")
        rs=_rows(p)
        if len(rs)!=spec.get("count"): raise ValueError("nongolden_mini131_source_count_mismatch")
        rag+=len(rs);paths.append(rs)
    if rag!=129: raise ValueError("nongolden_mini131_rag_count_mismatch")
    for p in extra_evaluation_paths: paths.append(_rows(_within(root,p)))
    return tuple(sorted({doc for rs in paths for row in rs for doc in _doc_ids(row)}))

def _manifest_rows(root:Path,stack_config:Path)->tuple[list[dict[str,Any]],dict[str,Any]]:
    cfg=json.loads(_within(root,stack_config).read_text());corpus=cfg.get("corpus")
    if not isinstance(corpus,Mapping): raise ValueError("nongolden_corpus_config_invalid")
    rel=corpus.get("manifest_path");h=corpus.get("manifest_sha256");n=corpus.get("document_count")
    if not isinstance(rel,str) or not isinstance(h,str) or not isinstance(n,int): raise ValueError("nongolden_corpus_config_invalid")
    p=_within(root,rel)
    if sha256_file(p)!=h: raise ValueError("nongolden_corpus_manifest_hash_mismatch")
    rs=_rows(p)
    if len(rs)!=n: raise ValueError("nongolden_corpus_manifest_count_mismatch")
    return rs,{"path":rel,"sha256":h,"count":n}


def _visual(root:Path,doc_id:str)->dict[str,Any]:
    p=root.resolve()/"resources/data_refined/private/visual-wrapperfix-v2"/doc_id/"metadata.json"
    if not p.is_file(): raise ValueError("nongolden_visual_metadata_missing")
    v=json.loads(p.read_text())
    if not isinstance(v,dict) or v.get("doc_id")!=doc_id: raise ValueError("nongolden_visual_metadata_invalid")
    return v


def _doc(row:Mapping[str,Any],visual:Mapping[str,Any])->dict[str,Any]:
    m=row.get("metadata")
    if not isinstance(m,Mapping): raise ValueError("nongolden_document_metadata_missing")
    for key in ("project_name","ordering_agency","notice_number","project_summary"):
        if not isinstance(m.get(key),str) or not m[key]: raise ValueError("nongolden_document_metadata_incomplete")
    amount=m.get("project_amount_value")
    if amount is not None and (not isinstance(amount,str) or not amount.isdigit()): raise ValueError("nongolden_project_amount_invalid")
    assets=visual.get("asset_count")
    if not isinstance(assets,int) or assets<0: raise ValueError("nongolden_visual_asset_count_invalid")
    return {"doc_id":row["doc_id"],"project_name":m["project_name"],"ordering_agency":m["ordering_agency"],
            "notice_number":m["notice_number"],"project_summary":m["project_summary"],
            "project_amount_value":amount,"asset_count":assets,"source_sha256":row.get("sha256")}


def build_fresh_document_pool(*,source_repo_root:Path,stack_config:Path,mini131_config:Path,
                              extra_evaluation_paths:Sequence[Path])->dict[str,Any]:
    root=source_repo_root.resolve();rows,mr=_manifest_rows(root,stack_config)
    referenced=set(historical_referenced_doc_ids(source_repo_root=root,mini131_config=mini131_config,
                                                  extra_evaluation_paths=extra_evaluation_paths))
    docs=[]
    for row in rows:
        doc_id=row.get("doc_id")
        if not isinstance(doc_id,str) or not doc_id: raise ValueError("nongolden_doc_id_invalid")
        if doc_id in referenced or row.get("index_eligible") is not True: continue
        docs.append(_doc(row,_visual(root,doc_id)))
    docs.sort(key=lambda r:sha256_text(r["doc_id"]))
    receipt={"schema_version":"evo-nongolden-fresh-pool-v1","manifest":mr,
             "historical_referenced_doc_count":len(referenced),
             "historical_referenced_doc_set_sha256":sha256_text(canonical_json(sorted(referenced))),
             "fresh_doc_count":len(docs),"fresh_doc_set_sha256":sha256_text(canonical_json(sorted(r["doc_id"] for r in docs))),
             "visual_asset_positive_count":sum(r["asset_count"]>0 for r in docs),
             "amount_present_count":sum(r["project_amount_value"] is not None for r in docs)}
    receipt["receipt_sha256"]=sha256_text(canonical_json(receipt));return {"documents":docs,"receipt":receipt}

def partition_documents(documents:Sequence[Mapping[str,Any]],*,split_counts:Mapping[str,int]=DEFAULT_SPLIT_DOC_COUNTS)->dict[str,Any]:
    if set(split_counts)!={"train","dev","sealed_holdout"} or any(type(v) is not int or v<=0 for v in split_counts.values()):
        raise ValueError("nongolden_split_counts_invalid")
    ordered=sorted((deepcopy(dict(r)) for r in documents),key=lambda r:sha256_text(r["doc_id"]))
    if sum(split_counts.values())!=len(ordered): raise ValueError("nongolden_split_document_count_mismatch")
    parts={};cursor=0
    for split in ("sealed_holdout","dev","train"):
        n=split_counts[split];parts[split]=ordered[cursor:cursor+n];cursor+=n
    seen=set()
    for split,rows in parts.items():
        ids={r["doc_id"] for r in rows}
        if seen&ids: raise ValueError("nongolden_document_split_leakage")
        seen|=ids
    receipt={"schema_version":PARTITION_SCHEMA,"splits":{}}
    for split in ("sealed_holdout","dev","train"):
        ids=[r["doc_id"] for r in parts[split]]
        receipt["splits"][split]={"document_count":len(ids),"doc_id_set_sha256":sha256_text(canonical_json(sorted(ids))),
                                   "sequence_sha256":sha256_text(canonical_json(ids))}
    receipt["combined_sha256"]=sha256_text(canonical_json(receipt));return {"partitions":parts,"receipt":receipt}


def _case(*,case_id:str,group_id:str,split:str,task_type:str,question:str,doc_ids:Sequence[str],
          conversation_id:str|None=None,parent_case_id:str|None=None)->dict[str,Any]:
    req={"question":question,"history":[],"document_scope":{"mode":"explicit","doc_ids":list(doc_ids)},"options":{"max_citations":3}}
    row={"schema_version":TRAINING_CASE_SCHEMA,"case_id":case_id,"group_id":group_id,"task_type":task_type,
         "split":split,"question":question,"request":req}
    if conversation_id is not None: row["conversation_id"]=conversation_id
    if parent_case_id is not None: row["follow_up_parent_case_id"]=parent_case_id
    return row


def _target(case:Mapping[str,Any],*,status:str,facts:Mapping[str,Any],required_tools:Sequence[str]=())->dict[str,Any]:
    return {"schema_version":TARGET_SCHEMA,"case_id":case["case_id"],"split":case["split"],"task_type":case["task_type"],
            "terminal_status":status,"facts":deepcopy(dict(facts)),"required_tools":list(required_tools)}


def _amount(row:Mapping[str,Any])->int|None:
    v=row.get("project_amount_value");return int(v) if isinstance(v,str) and v.isdigit() else None


def _pairs(rows:Sequence[Mapping[str,Any]])->list[tuple[Mapping[str,Any],Mapping[str,Any]]]:
    eligible=[r for r in rows if _amount(r) is not None];out=[]
    for i in range(0,len(eligible)-1,2):
        a,b=eligible[i],eligible[i+1]
        if _amount(a)!=_amount(b): out.append((a,b))
    return out

def author_non_golden_cases(partitions:Mapping[str,Sequence[Mapping[str,Any]]],*,exclusion_manifest:Mapping[str,Any])->dict[str,Any]:
    validate_exclusion_manifest(exclusion_manifest);cases=[];targets=[];counts=Counter()
    for split in ("sealed_holdout","dev","train"):
        docs=list(partitions.get(split,()))
        if not docs: raise ValueError("nongolden_partition_missing")
        for n,doc in enumerate(docs,1):
            cid=f"ng-{split}-fact-{n:02d}"
            q=f"공고번호 {doc['notice_number']} 문서의 사업명과 발주기관을 알려줘."
            c=_case(case_id=cid,group_id=cid,split=split,task_type="fact",question=q,doc_ids=[doc["doc_id"]])
            cases.append(c)
            targets.append(_target(c,status="answered",facts={"project_name":doc["project_name"],"ordering_agency":doc["ordering_agency"]},required_tools=("search","read")))
            counts[f"{split}:fact"]+=1
        pairs=_pairs(docs)
        for n,(left,right) in enumerate(pairs,1):
            gid=f"ng-{split}-pair-{n:02d}";conv=f"conv-{gid}";parent_id=f"{gid}-compare"
            q=f"공고번호 {left['notice_number']}와 {right['notice_number']}의 사업금액을 비교해서 더 큰 공고와 두 금액을 알려줘."
            c=_case(case_id=parent_id,group_id=gid,split=split,task_type="compare",question=q,doc_ids=[left["doc_id"],right["doc_id"]],conversation_id=conv)
            winner=left if _amount(left)>_amount(right) else right
            cases.append(c)
            targets.append(_target(c,status="answered",facts={"left_amount":left["project_amount_value"],"right_amount":right["project_amount_value"],"winner_notice_number":winner["notice_number"]},required_tools=("search","read")))
            counts[f"{split}:compare"]+=1
            fid=f"{gid}-follow";fq=f"방금 비교한 공고번호 {left['notice_number']}와 {right['notice_number']} 중 사업금액이 더 큰 쪽의 발주기관만 다시 알려줘."
            f=_case(case_id=fid,group_id=gid,split=split,task_type="follow_up",question=fq,doc_ids=[left["doc_id"],right["doc_id"]],conversation_id=conv,parent_case_id=parent_id)
            cases.append(f)
            targets.append(_target(f,status="answered",facts={"ordering_agency":winner["ordering_agency"],"winner_notice_number":winner["notice_number"]},required_tools=("search","read")))
            counts[f"{split}:follow_up"]+=1
        for n,(target_doc,scoped_doc) in enumerate(zip(docs[::2],docs[1::2]),1):
            cid=f"ng-{split}-abstain-{n:02d}";q=f"공고번호 {target_doc['notice_number']}의 사업금액을 알려줘."
            c=_case(case_id=cid,group_id=cid,split=split,task_type="abstain",question=q,doc_ids=[scoped_doc["doc_id"]])
            cases.append(c);targets.append(_target(c,status="abstained",facts={"reason":"out_of_scope"}));counts[f"{split}:abstain"]+=1
        visual_limit=min(6 if split=="train" else 2,len(docs));visual_docs=[d for d in docs if d["asset_count"]>0][:visual_limit]
        for n,doc in enumerate(visual_docs,1):
            cid=f"ng-{split}-visual-{n:02d}";q=f"공고번호 {doc['notice_number']} 문서에 삽입 이미지가 있는지 시각 근거로 확인해줘."
            c=_case(case_id=cid,group_id=cid,split=split,task_type="visual",question=q,doc_ids=[doc["doc_id"]])
            cases.append(c);targets.append(_target(c,status="answered",facts={"has_inserted_image":True},required_tools=("visual_search","inspect_image")));counts[f"{split}:visual"]+=1
        for n,doc in enumerate([d for d in visual_docs if _amount(d) is not None],1):
            cid=f"ng-{split}-mixed-{n:02d}";q=f"공고번호 {doc['notice_number']} 문서의 사업금액과 삽입 이미지 존재 여부를 텍스트와 시각 근거를 함께 확인해줘."
            c=_case(case_id=cid,group_id=cid,split=split,task_type="mixed",question=q,doc_ids=[doc["doc_id"]])
            cases.append(c);targets.append(_target(c,status="answered",facts={"project_amount_value":doc["project_amount_value"],"has_inserted_image":True},required_tools=("search","read","visual_search","inspect_image")));counts[f"{split}:mixed"]+=1
    frozen=freeze_splits(cases,exclusion=exclusion_manifest)
    case_ids={c["case_id"] for c in cases};target_ids={t["case_id"] for t in targets}
    if case_ids!=target_ids or len(target_ids)!=len(targets): raise ValueError("nongolden_target_case_mismatch")
    receipt={"schema_version":AUTHORING_SCHEMA,"case_count":len(cases),"target_count":len(targets),"task_counts":dict(sorted(counts.items())),"split_receipt":frozen["receipt"],"target_sequence_sha256":sha256_text(canonical_json([t["case_id"] for t in targets]))}
    receipt["receipt_sha256"]=sha256_text(canonical_json(receipt))
    return {"cases":frozen["cases"],"targets":targets,"receipt":receipt}
