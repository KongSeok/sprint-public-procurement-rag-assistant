#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,os
from pathlib import Path
def main(argv=None):
    p=argparse.ArgumentParser(description='Replay PRE runtime failures with frozen PRE search outputs and live Qwen policy.')
    for name in ('source-repo-root','source-config','runtime-data-root','artifacts','mlx-python','model-dir','model-manifest','source-records','source-aggregate','output-dir'):
        p.add_argument('--'+name,required=True,type=Path)
    p.add_argument('--expected-revision',required=True);p.add_argument('--repaired-candidate',required=True);p.add_argument('--limit',type=int);p.add_argument('--offset',type=int,default=0)
    a=p.parse_args(argv);cache=a.runtime_data_root.resolve()/'private/hf-cache'
    os.environ.update(HF_HOME=str(cache),HF_HUB_CACHE=str(cache/'hub'),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',TOKENIZERS_PARALLELISM='false',PYTHONDONTWRITEBYTECODE='1')
    from midprojectrag.evo_harness.runtime_recorded_replay import run
    repo=Path(__file__).resolve().parents[1]
    out=run(repo_root=repo,source_repo_root=a.source_repo_root,source_config=a.source_config,runtime_data_root=a.runtime_data_root,
            artifact_dir=a.artifacts,mlx_python=a.mlx_python,model_dir=a.model_dir,model_manifest=a.model_manifest,
            expected_revision=a.expected_revision,source_records=a.source_records,source_aggregate=a.source_aggregate,
            output_dir=a.output_dir,repaired_candidate=a.repaired_candidate,limit=a.limit,offset=a.offset)
    print(json.dumps(out,ensure_ascii=False,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
