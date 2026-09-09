"""Support-audited non-golden seed v2; seed-v1 was rejected before tuning."""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
import json,re
from pathlib import Path
from typing import Any,Mapping,Sequence
from midprojectrag.ingest.common import canonical_json,sha256_file,sha256_text
from .training import freeze_splits,validate_exclusion_manifest
from .training_authoring import build_fresh_document_pool,_case,_target,_amount

SCHEMA="evo-nongolden-authoring-v2"
PARTITION_SCHEMA="evo-nongolden-supported-partition-v2"
SUPPORT_FIELDS=("project_name","ordering_agency","project_amount_value")
QUOTAS={
 "triple":{"sealed_holdout":2,"dev":2,"train":3},
 "name_amount":{"sealed_holdout":0,"dev":0,"train":4},
 "name_agency":{"sealed_holdout":2,"dev":2,"train":2},
 "other":{"sealed_holdout":2,"dev":2,"train":8},
}


def _norm(value:Any)->str: return re.sub(r"\s+","",str(value)).casefold()
def _digits(value:Any)->str: return re.sub(r"\D","",str(value))


def _chunk_texts(root:Path,stack_config:Path)->tuple[dict[str,str],dict[str,Any]]:
    cfg=json.loads(stack_config.read_text());corpus=cfg.get("corpus")
    if not isinstance(corpus,Mapping): raise ValueError("nongolden_v2_corpus_config_invalid")
    rel=corpus.get("chunks_path");h=corpus.get("chunks_sha256");n=corpus.get("chunk_count")
    if not isinstance(rel,str) or not isinstance(h,str) or not isinstance(n,int): raise ValueError("nongolden_v2_chunk_config_invalid")
    p=(root/rel).resolve()
    if root.resolve() not in p.parents or sha256_file(p)!=h: raise ValueError("nongolden_v2_chunks_hash_mismatch")
    rows=[]
    with p.open(encoding="utf-8") as f:
        for line in f:
            if line.strip(): rows.append(json.loads(line))
    if len(rows)!=n: raise ValueError("nongolden_v2_chunks_count_mismatch")
    by:dict[str,list[str]]={}
    for r in rows:
        if not isinstance(r,dict) or not isinstance(r.get("doc_id"),str) or not isinstance(r.get("text"),str): raise ValueError("nongolden_v2_chunk_invalid")
        by.setdefault(r["doc_id"],[]).append(r["text"])
    return {k:"\n".join(v) for k,v in by.items()},{"path":rel,"sha256":h,"count":n}


def build_supported_pool(*,source_repo_root:Path,stack_config:Path,mini131_config:Path,extra_evaluation_paths:Sequence[Path])->dict[str,Any]:
    base=build_fresh_document_pool(source_repo_root=source_repo_root,stack_config=stack_config,mini131_config=mini131_config,extra_evaluation_paths=extra_evaluation_paths)
    texts,chunk_receipt=_chunk_texts(source_repo_root.resolve(),stack_config.resolve());docs=[];counts=Counter()
    for raw in base["documents"]:
        row=deepcopy(raw);text=texts.get(row["doc_id"],"");supported=[]
        for key in SUPPORT_FIELDS:
            value=row.get(key);ok=False
            if value is not None:
                ok=(_digits(value) in _digits(text)) if key=="project_amount_value" else (_norm(value) in _norm(text))
            if ok:supported.append(key);counts[key]+=1
        row["supported_fields"]=supported;docs.append(row)
    receipt={"schema_version":"evo-nongolden-supported-pool-v2","base_pool_sha256":base["receipt"]["receipt_sha256"],
             "chunks":chunk_receipt,"fresh_doc_count":len(docs),"support_counts":dict(sorted(counts.items()))}
    receipt["receipt_sha256"]=sha256_text(canonical_json(receipt));return {"documents":docs,"texts":texts,"receipt":receipt}

def _category(row:Mapping[str,Any])->str:
    s=set(row.get("supported_fields",[]));name="project_name" in s;agency="ordering_agency" in s;amount="project_amount_value" in s
    if name and agency and amount:return "triple"
    if name and amount:return "name_amount"
    if name and agency:return "name_agency"
    return "other"


def partition_supported_documents(documents:Sequence[Mapping[str,Any]])->dict[str,Any]:
    buckets={k:[] for k in QUOTAS}
    for raw in documents:
        row=deepcopy(dict(raw));buckets[_category(row)].append(row)
    for key in buckets:buckets[key].sort(key=lambda r:sha256_text(r["doc_id"]))
    expected={key:sum(q.values()) for key,q in QUOTAS.items()}
    actual={key:len(rows) for key,rows in buckets.items()}
    if actual!=expected: raise ValueError("nongolden_v2_capability_inventory_changed")
    parts={"sealed_holdout":[],"dev":[],"train":[]}
    for key in ("triple","name_amount","name_agency","other"):
        cursor=0
        for split in ("sealed_holdout","dev","train"):
            n=QUOTAS[key][split];parts[split].extend(buckets[key][cursor:cursor+n]);cursor+=n
    for split in parts: parts[split].sort(key=lambda r:sha256_text(r["doc_id"]))
    seen=set();receipt={"schema_version":PARTITION_SCHEMA,"capability_counts":actual,"splits":{}}
    for split in ("sealed_holdout","dev","train"):
        ids=[r["doc_id"] for r in parts[split]]
        if seen&set(ids): raise ValueError("nongolden_v2_document_split_leakage")
        seen.update(ids)
        cats=Counter(_category(r) for r in parts[split])
        receipt["splits"][split]={"document_count":len(ids),"category_counts":dict(sorted(cats.items())),
            "doc_id_set_sha256":sha256_text(canonical_json(sorted(ids))),"sequence_sha256":sha256_text(canonical_json(ids))}
    receipt["combined_sha256"]=sha256_text(canonical_json(receipt));return {"partitions":parts,"receipt":receipt}


def _supported(row:Mapping[str,Any],*keys:str)->bool:
    s=set(row.get("supported_fields",[]));return all(k in s for k in keys)


def _pairs(rows:Sequence[Mapping[str,Any]])->list[tuple[Mapping[str,Any],Mapping[str,Any]]]:
    eligible=sorted((r for r in rows if _supported(r,"project_name","project_amount_value")),key=lambda r:sha256_text(r["doc_id"]))
    out=[]
    for i in range(0,len(eligible)-1,2):
        a,b=eligible[i],eligible[i+1]
        if _amount(a)!=_amount(b):out.append((a,b))
    return out

def author_supported_cases(partitions:Mapping[str,Sequence[Mapping[str,Any]]],*,exclusion_manifest:Mapping[str,Any])->dict[str,Any]:
    validate_exclusion_manifest(exclusion_manifest);cases=[];targets=[];counts=Counter()
    for split in ("sealed_holdout","dev","train"):
        docs=list(partitions.get(split,()))
        if not docs: raise ValueError("nongolden_v2_partition_missing")
        amount_docs=sorted((d for d in docs if _supported(d,"project_name","project_amount_value")),key=lambda r:sha256_text(r["doc_id"]))
        agency_docs=sorted((d for d in docs if _supported(d,"project_name","ordering_agency")),key=lambda r:sha256_text(r["doc_id"]))
        for n,doc in enumerate(amount_docs,1):
            cid=f"ng2-{split}-fact-amount-{n:02d}";q=f"{doc['project_name']} 사업의 사업금액을 문서 근거로 알려줘."
            c=_case(case_id=cid,group_id=cid,split=split,task_type="fact",question=q,doc_ids=[doc["doc_id"]])
            cases.append(c);targets.append(_target(c,status="answered",facts={"project_amount_value":doc["project_amount_value"]},required_tools=("search","read")));counts[f"{split}:fact"]+=1
        for n,doc in enumerate(agency_docs,1):
            cid=f"ng2-{split}-fact-agency-{n:02d}";q=f"{doc['project_name']} 사업의 발주기관을 문서 근거로 알려줘."
            c=_case(case_id=cid,group_id=cid,split=split,task_type="fact",question=q,doc_ids=[doc["doc_id"]])
            cases.append(c);targets.append(_target(c,status="answered",facts={"ordering_agency":doc["ordering_agency"]},required_tools=("search","read")));counts[f"{split}:fact"]+=1
        for n,(left,right) in enumerate(_pairs(docs),1):
            gid=f"ng2-{split}-pair-{n:02d}";conv=f"conv-{gid}";pid=f"{gid}-compare"
            q=f"{left['project_name']}와 {right['project_name']}의 사업금액을 비교해 더 큰 사업과 두 금액을 알려줘."
            parent=_case(case_id=pid,group_id=gid,split=split,task_type="compare",question=q,doc_ids=[left["doc_id"],right["doc_id"]],conversation_id=conv)
            winner=left if _amount(left)>_amount(right) else right
            cases.append(parent);targets.append(_target(parent,status="answered",facts={"left_amount":left["project_amount_value"],"right_amount":right["project_amount_value"],"winner_project_name":winner["project_name"],"winner_amount":winner["project_amount_value"]},required_tools=("search","read")));counts[f"{split}:compare"]+=1
            for suffix,fq,facts in (
                ("name",f"방금 비교한 {left['project_name']}와 {right['project_name']} 중 금액이 더 큰 사업명만 다시 알려줘.",{"winner_project_name":winner["project_name"]}),
                ("amount",f"방금 비교한 {left['project_name']}와 {right['project_name']} 중 금액이 더 큰 쪽의 금액만 다시 알려줘.",{"winner_amount":winner["project_amount_value"]}),):
                fid=f"{gid}-follow-{suffix}";follow=_case(case_id=fid,group_id=gid,split=split,task_type="follow_up",question=fq,doc_ids=[left["doc_id"],right["doc_id"]],conversation_id=conv,parent_case_id=pid)
                cases.append(follow);targets.append(_target(follow,status="answered",facts=facts,required_tools=("search","read")));counts[f"{split}:follow_up"]+=1
        named=sorted((d for d in docs if _supported(d,"project_name")),key=lambda r:sha256_text(r["doc_id"]))
        for n,(target_doc,scoped_doc) in enumerate(zip(named[::2],named[1::2]),1):
            if _supported(target_doc,"project_amount_value"):
                q=f"{target_doc['project_name']} 사업의 사업금액을 알려줘."
            else:q=f"{target_doc['project_name']} 사업의 발주기관을 알려줘."
            cid=f"ng2-{split}-abstain-{n:02d}";c=_case(case_id=cid,group_id=cid,split=split,task_type="abstain",question=q,doc_ids=[scoped_doc["doc_id"]])
            cases.append(c);targets.append(_target(c,status="abstained",facts={"reason":"out_of_scope"}));counts[f"{split}:abstain"]+=1
        visual_docs=[d for d in named if d["asset_count"]>0][:min(6 if split=="train" else 2,len(named))]
        for n,doc in enumerate(visual_docs,1):
            cid=f"ng2-{split}-visual-{n:02d}";q=f"{doc['project_name']} 문서에 삽입 이미지가 있는지 시각 근거로 확인해줘."
            c=_case(case_id=cid,group_id=cid,split=split,task_type="visual",question=q,doc_ids=[doc["doc_id"]])
            cases.append(c);targets.append(_target(c,status="answered",facts={"has_inserted_image":True},required_tools=("visual_search","inspect_image")));counts[f"{split}:visual"]+=1
        mixed_docs=amount_docs[:min(6 if split=="train" else 2,len(amount_docs))]
        for n,doc in enumerate(mixed_docs,1):
            cid=f"ng2-{split}-mixed-{n:02d}";q=f"{doc['project_name']} 사업의 사업금액과 삽입 이미지 존재 여부를 텍스트와 시각 근거로 함께 확인해줘."
            c=_case(case_id=cid,group_id=cid,split=split,task_type="mixed",question=q,doc_ids=[doc["doc_id"]])
            cases.append(c);targets.append(_target(c,status="answered",facts={"project_amount_value":doc["project_amount_value"],"has_inserted_image":True},required_tools=("search","read","visual_search","inspect_image")));counts[f"{split}:mixed"]+=1
    frozen=freeze_splits(cases,exclusion=exclusion_manifest);ids={c["case_id"] for c in cases}
    if ids!={t["case_id"] for t in targets} or len(ids)!=len(targets): raise ValueError("nongolden_v2_target_case_mismatch")
    receipt={"schema_version":SCHEMA,"case_count":len(cases),"target_count":len(targets),"task_counts":dict(sorted(counts.items())),"split_receipt":frozen["receipt"],"target_sequence_sha256":sha256_text(canonical_json([t["case_id"] for t in targets]))}
    receipt["receipt_sha256"]=sha256_text(canonical_json(receipt));return {"cases":frozen["cases"],"targets":targets,"receipt":receipt}


def audit_support(cases:Mapping[str,Sequence[Mapping[str,Any]]],targets:Sequence[Mapping[str,Any]],texts:Mapping[str,str])->dict[str,Any]:
    target_map={t["case_id"]:t for t in targets};checked=0;failed=0;counts=Counter()
    for split,rows in cases.items():
        for c in rows:
            target=target_map[c["case_id"]]
            if target["terminal_status"]!="answered" or c["task_type"]=="visual":continue
            text="\n".join(texts.get(d,"") for d in c["request"]["document_scope"]["doc_ids"]);ok=True
            for key,value in target["facts"].items():
                if isinstance(value,bool):continue
                present=(_digits(value) in _digits(text)) if key.endswith("amount") or key.endswith("amount_value") else (_norm(value) in _norm(text))
                ok=ok and present
            checked+=1;failed+=int(not ok);counts[f"{split}:{c['task_type']}:{'pass' if ok else 'fail'}"]+=1
    receipt={"schema_version":"evo-nongolden-support-audit-v2","checked_count":checked,"failed_count":failed,"counts":dict(sorted(counts.items()))}
    receipt["receipt_sha256"]=sha256_text(canonical_json(receipt));return receipt
