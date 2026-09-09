#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,os
from pathlib import Path
from midprojectrag.evo_harness.training import write_jsonl_new,validate_exclusion_manifest
from midprojectrag.evo_harness.training_authoring_v2 import build_supported_pool,partition_supported_documents,audit_support
from midprojectrag.evo_harness.training_authoring_v3 import author_visual_gated_cases
from midprojectrag.ingest.common import canonical_json,sha256_file,sha256_text


def _load(path:Path):
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict): raise ValueError("nongolden_json_object_required")
    return value


def _new_json(path:Path,value,mode=0o600):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with path.open("x",encoding="utf-8") as stream: stream.write(canonical_json(value)+"\n")
    path.chmod(mode)


def main(argv=None):
    p=argparse.ArgumentParser(description="Freeze support- and visual-source-audited non-golden Evo seed v3 before tuning.")
    for name in ("source-repo-root","stack-config","mini131-config","exclusion-manifest","visual-source-gate","output-dir"):
        p.add_argument("--"+name,type=Path,required=True)
    p.add_argument("--extra-evaluation",type=Path,action="append",default=[])
    a=p.parse_args(argv);os.umask(0o077)
    if a.output_dir.exists(): raise ValueError("nongolden_output_exists")
    exclusion=_load(a.exclusion_manifest);validate_exclusion_manifest(exclusion);visual_gate=_load(a.visual_source_gate)
    pool=build_supported_pool(source_repo_root=a.source_repo_root,stack_config=a.stack_config,
        mini131_config=a.mini131_config,extra_evaluation_paths=a.extra_evaluation)
    partition=partition_supported_documents(pool["documents"])
    authored=author_visual_gated_cases(partition["partitions"],exclusion_manifest=exclusion,visual_source_gate=visual_gate)
    support=audit_support(authored["cases"],authored["targets"],pool["texts"])
    if support["failed_count"]: raise ValueError("nongolden_v3_support_audit_failed")
    target_map={row["case_id"]:row for row in authored["targets"]}
    a.output_dir.mkdir(parents=True,exist_ok=False,mode=0o700)
    file_receipts={}
    # Seal holdout first, before any train/dev artifact is written.
    for split in ("sealed_holdout","train","dev"):
        rows=authored["cases"][split]
        targets=[target_map[row["case_id"]] for row in rows]
        d=a.output_dir/split;d.mkdir(parents=True,exist_ok=False,mode=0o700)
        case_path=d/"cases.jsonl";target_path=d/"targets.jsonl"
        write_jsonl_new(case_path,rows);write_jsonl_new(target_path,targets)
        receipt={"case_count":len(rows),"cases_sha256":sha256_file(case_path),"targets_sha256":sha256_file(target_path),
                 "case_sequence_sha256":sha256_text(canonical_json([row["case_id"] for row in rows]))}
        file_receipts[split]=receipt
        if split=="sealed_holdout":
            seal={"schema_version":"evo-nongolden-sealed-holdout-v1","split":"sealed_holdout",
                  "document_partition":partition["receipt"]["splits"][split],"support_audit_sha256":support["receipt_sha256"],"visual_source_gate_sha256":visual_gate["gate_sha256"],**receipt}
            seal["seal_sha256"]=sha256_text(canonical_json(seal));_new_json(d/"seal.json",seal,0o400)
            case_path.chmod(0o400);target_path.chmod(0o400)
    bundle={"schema_version":"evo-nongolden-bundle-v1","pool":pool["receipt"],"partition":partition["receipt"],
            "authoring":authored["receipt"],"support_audit":support,"visual_source_gate_sha256":visual_gate["gate_sha256"],"files":file_receipts,
            "sealed_holdout_seal_sha256":json.loads((a.output_dir/"sealed_holdout/seal.json").read_text())["seal_sha256"]}
    bundle["bundle_sha256"]=sha256_text(canonical_json(bundle));_new_json(a.output_dir/"bundle-receipt.json",bundle)
    print(canonical_json({"status":"frozen","bundle_sha256":bundle["bundle_sha256"],
                          "sealed_holdout_seal_sha256":bundle["sealed_holdout_seal_sha256"],
                          "case_counts":{k:v["case_count"] for k,v in file_receipts.items()}}));return 0

if __name__=="__main__": raise SystemExit(main())
