"""Visual-source-gated non-golden authoring; seed-v2 remains reproducible."""
from __future__ import annotations
from collections import Counter
from typing import Any,Mapping,Sequence
from midprojectrag.ingest.common import canonical_json,sha256_text
from .training import freeze_splits,validate_exclusion_manifest
from .training_authoring import _case,_target
from .training_authoring_v2 import author_supported_cases,_supported,audit_support

SCHEMA="evo-nongolden-authoring-v3"
GATE_SCHEMA="evo-visual-source-gate-v1"
VISUAL_QUOTAS={"train":{"visual":6,"mixed":5},"dev":{"visual":2,"mixed":2},"sealed_holdout":{"visual":2,"mixed":2}}

def validate_visual_source_gate(gate:Mapping[str,Any],partitions:Mapping[str,Sequence[Mapping[str,Any]]])->set[str]:
    if gate.get("schema_version")!=GATE_SCHEMA: raise ValueError("nongolden_v3_visual_gate_schema_invalid")
    ids=gate.get("eligible_doc_ids"); actual=gate.get("gate_sha256")
    if not isinstance(ids,list) or ids!=sorted(set(ids)) or any(not isinstance(x,str) or not x for x in ids):
        raise ValueError("nongolden_v3_visual_gate_invalid")
    body=dict(gate);body.pop("gate_sha256",None)
    if actual!=sha256_text(canonical_json(body)): raise ValueError("nongolden_v3_visual_gate_hash_mismatch")
    known={d["doc_id"] for rows in partitions.values() for d in rows}
    if not set(ids)<=known: raise ValueError("nongolden_v3_visual_gate_unknown_doc")
    return set(ids)

def author_visual_gated_cases(partitions:Mapping[str,Sequence[Mapping[str,Any]]],*,exclusion_manifest:Mapping[str,Any],visual_source_gate:Mapping[str,Any])->dict[str,Any]:
    validate_exclusion_manifest(exclusion_manifest);eligible=validate_visual_source_gate(visual_source_gate,partitions)
    base=author_supported_cases(partitions,exclusion_manifest=exclusion_manifest);base_targets={t["case_id"]:t for t in base["targets"]}
    cases=[];targets=[];counts=Counter()
    for split in ("sealed_holdout","dev","train"):
        for c in base["cases"][split]:
            if c["task_type"] in {"visual","mixed"}: continue
            cases.append(c);targets.append(base_targets[c["case_id"]]);counts[f"{split}:{c['task_type']}"]+=1
        docs=list(partitions[split]);quota=VISUAL_QUOTAS[split]
        named=sorted((d for d in docs if d["doc_id"] in eligible and _supported(d,"project_name")),key=lambda r:sha256_text(r["doc_id"]))
        amount=sorted((d for d in docs if d["doc_id"] in eligible and _supported(d,"project_name","project_amount_value")),key=lambda r:sha256_text(r["doc_id"]))
        if len(named)<quota["visual"] or len(amount)<quota["mixed"]: raise ValueError(f"nongolden_v3_visual_capacity_insufficient:{split}")
        for n,doc in enumerate(named[:quota["visual"]],1):
            cid=f"ng3-{split}-visual-{n:02d}";q=f"{doc['project_name']} 문서에 삽입 이미지가 있는지 시각 근거로 확인해줘."
            c=_case(case_id=cid,group_id=cid,split=split,task_type="visual",question=q,doc_ids=[doc["doc_id"]])
            cases.append(c);targets.append(_target(c,status="answered",facts={"has_inserted_image":True},required_tools=("visual_search","inspect_image")));counts[f"{split}:visual"]+=1
        for n,doc in enumerate(amount[:quota["mixed"]],1):
            cid=f"ng3-{split}-mixed-{n:02d}";q=f"{doc['project_name']} 사업의 사업금액과 삽입 이미지 존재 여부를 텍스트와 시각 근거로 함께 확인해줘."
            c=_case(case_id=cid,group_id=cid,split=split,task_type="mixed",question=q,doc_ids=[doc["doc_id"]])
            cases.append(c);targets.append(_target(c,status="answered",facts={"project_amount_value":doc["project_amount_value"],"has_inserted_image":True},required_tools=("search","read","visual_search","inspect_image")));counts[f"{split}:mixed"]+=1
    frozen=freeze_splits(cases,exclusion=exclusion_manifest)
    ids={c["case_id"] for c in cases}
    if ids!={t["case_id"] for t in targets} or len(ids)!=len(targets): raise ValueError("nongolden_v3_target_case_mismatch")
    receipt={"schema_version":SCHEMA,"case_count":len(cases),"target_count":len(targets),"task_counts":dict(sorted(counts.items())),
             "split_receipt":frozen["receipt"],"visual_gate_sha256":visual_source_gate["gate_sha256"],
             "target_sequence_sha256":sha256_text(canonical_json([t["case_id"] for t in targets]))}
    receipt["receipt_sha256"]=sha256_text(canonical_json(receipt))
    return {"cases":frozen["cases"],"targets":targets,"receipt":receipt}

__all__=["GATE_SCHEMA","SCHEMA","VISUAL_QUOTAS","audit_support","author_visual_gated_cases","validate_visual_source_gate"]
