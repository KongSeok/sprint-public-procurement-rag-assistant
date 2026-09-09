#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,os
from pathlib import Path
from midprojectrag.evo_harness.training import write_jsonl_new,validate_exclusion_manifest
from midprojectrag.evo_harness.training_authoring import build_fresh_document_pool,partition_documents,author_non_golden_cases
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
    p=argparse.ArgumentParser(description="Freeze deterministic non-golden Evo train/dev/sealed seed data.")
    for name in ("source-repo-root","stack-config","mini131-config","exclusion-manifest","output-dir"):
        p.add_argument("--"+name,type=Path,required=True)
    p.add_argument("--extra-evaluation",type=Path,action="append",default=[])
    a=p.parse_args(argv);os.umask(0o077)
    if a.output_dir.exists(): raise ValueError("nongolden_output_exists")
    exclusion=_load(a.exclusion_manifest);validate_exclusion_manifest(exclusion)
    pool=build_fresh_document_pool(source_repo_root=a.source_repo_root,stack_config=a.stack_config,
        mini131_config=a.mini131_config,extra_evaluation_paths=a.extra_evaluation)
    partition=partition_documents(pool["documents"])
    authored=author_non_golden_cases(partition["partitions"],exclusion_manifest=exclusion)
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
                  "document_partition":partition["receipt"]["splits"][split],**receipt}
            seal["seal_sha256"]=sha256_text(canonical_json(seal));_new_json(d/"seal.json",seal,0o400)
            case_path.chmod(0o400);target_path.chmod(0o400)
    bundle={"schema_version":"evo-nongolden-bundle-v1","pool":pool["receipt"],"partition":partition["receipt"],
            "authoring":authored["receipt"],"files":file_receipts,
            "sealed_holdout_seal_sha256":json.loads((a.output_dir/"sealed_holdout/seal.json").read_text())["seal_sha256"]}
    bundle["bundle_sha256"]=sha256_text(canonical_json(bundle));_new_json(a.output_dir/"bundle-receipt.json",bundle)
    print(canonical_json({"status":"frozen","bundle_sha256":bundle["bundle_sha256"],
                          "sealed_holdout_seal_sha256":bundle["sealed_holdout_seal_sha256"],
                          "case_counts":{k:v["case_count"] for k,v in file_receipts.items()}}));return 0

if __name__=="__main__": raise SystemExit(main())
