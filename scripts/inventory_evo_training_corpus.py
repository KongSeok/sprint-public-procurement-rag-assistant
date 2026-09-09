#!/usr/bin/env python3
"""Build private corpus candidates and a content-safe receipt for Evo data authoring."""
from __future__ import annotations
import argparse,json,os
from pathlib import Path
from midprojectrag.evo_harness.training import write_jsonl_new
from midprojectrag.evo_harness.training_inventory import build_corpus_training_inventory
from midprojectrag.ingest.common import canonical_json

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-repo-root',type=Path,required=True);p.add_argument('--stack-config',type=Path,required=True);p.add_argument('--exclusion-manifest',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args(argv);os.umask(0o077)
    exclusion=json.loads(a.exclusion_manifest.read_text());result=build_corpus_training_inventory(source_repo_root=a.source_repo_root,stack_config=a.stack_config,exclusion_manifest=exclusion)
    a.output_dir.mkdir(parents=True,exist_ok=False,mode=0o700);write_jsonl_new(a.output_dir/'corpus-docs.jsonl',result['documents'])
    with (a.output_dir/'corpus-receipt.json').open('x',encoding='utf-8') as f:f.write(canonical_json(result['receipt'])+'\n')
    (a.output_dir/'corpus-receipt.json').chmod(0o600);print(canonical_json(result['receipt']));return 0
if __name__=='__main__':raise SystemExit(main())
