#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,os
from pathlib import Path

def main(argv=None):
    p=argparse.ArgumentParser(description="Collect deterministic validated TRAIN teacher actions for Evo SFT.")
    for name in ("cases","targets","runtime-data-root","artifacts","mlx-python","model-dir","model-manifest","output-dir"):
        p.add_argument("--"+name,type=Path,required=True)
    p.add_argument("--expected-revision",required=True);p.add_argument("--candidate-commit",required=True);p.add_argument("--limit",type=int)
    a=p.parse_args(argv);os.umask(0o077)
    cache=a.runtime_data_root.resolve()/"private/hf-cache"
    os.environ.update(HF_HOME=str(cache),HF_HUB_CACHE=str(cache/"hub"),HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1",TOKENIZERS_PARALLELISM="false",PYTHONDONTWRITEBYTECODE="1")
    from midprojectrag.evo_harness.training_teacher import collect_teacher
    repo=Path(__file__).resolve().parents[1]
    result=collect_teacher(repo_root=repo,cases_path=a.cases,targets_path=a.targets,runtime_data_root=a.runtime_data_root,
        artifact_dir=a.artifacts,mlx_python=a.mlx_python,model_dir=a.model_dir,model_manifest=a.model_manifest,
        expected_revision=a.expected_revision,output_dir=a.output_dir,candidate_commit=a.candidate_commit,limit=a.limit)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return 0

if __name__=="__main__":raise SystemExit(main())
