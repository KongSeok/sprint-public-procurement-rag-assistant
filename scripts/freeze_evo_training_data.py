#!/usr/bin/env python3
"""Freeze Evo policy exclusions/splits or export positive next-action SFT records."""
from __future__ import annotations
import argparse, json, os
from pathlib import Path

from midprojectrag.evo_harness.training import (
    build_exclusion_manifest, freeze_sft_examples, freeze_splits, read_jsonl, sft_examples_from_trajectory,
    validate_exclusion_manifest, write_jsonl_new,
)
from midprojectrag.ingest.common import canonical_json, sha256_file


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _new_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(canonical_json(value) + "\n")
    path.chmod(0o600)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    p=sub.add_parser("exclusion")
    p.add_argument("--cases",type=Path,nargs="+",required=True);p.add_argument("--source-id",required=True);p.add_argument("--output",type=Path,required=True)
    p=sub.add_parser("split")
    p.add_argument("--cases",type=Path,required=True);p.add_argument("--exclusion",type=Path,required=True);p.add_argument("--output-dir",type=Path,required=True)
    p=sub.add_parser("sft")
    p.add_argument("--case",type=Path,required=True);p.add_argument("--result",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
    p=sub.add_parser("sft-freeze")
    p.add_argument("--source",type=Path,action="append",required=True);p.add_argument("--exclusion",type=Path,required=True);p.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args(argv);os.umask(0o077)
    if args.command=="exclusion":
        rows=[]
        for path in args.cases: rows.extend(read_jsonl(path))
        source_hash=";".join(sha256_file(path) for path in args.cases)
        result=build_exclusion_manifest(rows,source_id=args.source_id,source_sha256=source_hash)
        _new_json(args.output,result);print(canonical_json({"status":"written","cases":len(rows),"manifest_sha256":result["manifest_sha256"]}));return 0
    if args.command=="split":
        exclusion=_load(args.exclusion);validate_exclusion_manifest(exclusion)
        frozen=freeze_splits(read_jsonl(args.cases),exclusion=exclusion)
        args.output_dir.mkdir(parents=True,exist_ok=False,mode=0o700)
        for split,rows in frozen["cases"].items(): write_jsonl_new(args.output_dir/f"{split}.jsonl",rows)
        _new_json(args.output_dir/"receipt.json",frozen["receipt"]);print(canonical_json(frozen["receipt"]));return 0
    if args.command=="sft-freeze":
        exclusion=_load(args.exclusion); validate_exclusion_manifest(exclusion)
        sources=[(f"source-{i}",read_jsonl(path)) for i,path in enumerate(args.source,1)]
        frozen=freeze_sft_examples(sources,exclusion=exclusion)
        args.output_dir.mkdir(parents=True,exist_ok=False,mode=0o700)
        output=args.output_dir/"train-positive-sft.jsonl"; write_jsonl_new(output,frozen["rows"])
        receipt=frozen["receipt"]
        for item,path in zip(receipt["sources"],args.source): item["sha256"]=sha256_file(path)
        receipt["output_sha256"]=sha256_file(output); receipt["exclusion_manifest_sha256"]=sha256_file(args.exclusion)
        _new_json(args.output_dir/"dataset-receipt.json",receipt); print(canonical_json(receipt)); return 0
    case=_load(args.case);result=_load(args.result);rows=sft_examples_from_trajectory(result,case)
    write_jsonl_new(args.output,rows);print(canonical_json({"status":"written","examples":len(rows)}));return 0

if __name__=="__main__": raise SystemExit(main())
