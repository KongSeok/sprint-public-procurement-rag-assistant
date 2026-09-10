#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
from midprojectrag import local_mini131_baseline as mini
from midprojectrag import local_mini131_semantic as sem
from midprojectrag.ingest.common import sha256_file

def load(root:Path, source_root:Path, config:Path):
    suite=mini.verify_suite(repo_root=source_root.resolve(),config_path=config.resolve())
    manifest=json.loads((root/'prepare-manifest.json').read_text())
    reviews=[json.loads(x) for x in (root/'primary-inputs.jsonl').read_text().splitlines() if x.strip()]
    maps=[json.loads(x) for x in (root/'review-map.jsonl').read_text().splitlines() if x.strip()]
    if len(reviews)!=129 or len(maps)!=129: raise ValueError('evo_semantic_prepare_incomplete')
    by_blind={r['blind_id']:r for r in reviews}; map_by={r['blind_id']:r for r in maps}
    statuses={}
    for blind,m in map_by.items(): statuses[m['case_id']]=by_blind[blind]['judge_input']['candidate']['status']
    candidates={case_id:{'response':{'status':status}} for case_id,status in statuses.items()}
    paths=sem.SemanticPaths(root/'prepare-manifest.json',root/'review-map.jsonl',root/'prepare-manifest.json',root/'prepare-manifest.json',source_root/'evaluation/rubric.md',source_root/'evaluation/baselines/mini131-bundle-v1/judge-config.json',root/'prepare-manifest.json',root,root/'primary-inputs.jsonl',root/'review-map.jsonl',root/'unused-semantic-score.json')
    return sem.SemanticLedger(suite,paths,manifest['review_config_sha256'],manifest['review_config']['judge_config_sha256'],manifest['review_config']['rubric_sha256'],'evo35-golden131-pre',tuple(reviews),by_blind,map_by,candidates,sha256_file(root/'prepare-manifest.json'))

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument('command',choices=['validate','secondary','adjudication','merge']); p.add_argument('--root',type=Path,required=True); p.add_argument('--source-root',type=Path,required=True); p.add_argument('--config',type=Path,required=True); p.add_argument('--decisions',type=Path,action='append',required=True); p.add_argument('--output',type=Path); a=p.parse_args(argv)
    ledger=load(a.root,a.source_root,a.config)
    if a.command=='validate':
        raw,_=sem.validate_decisions(ledger,a.decisions); print(json.dumps({'passed':True,'count':len(raw)})); return 0
    if a.output is None: raise ValueError('evo_semantic_output_required')
    if a.command=='secondary': rows=sem.select_secondary_inputs(ledger,a.decisions,output_path=a.output)
    elif a.command=='adjudication': rows=sem.select_adjudication_inputs(ledger,a.decisions,output_path=a.output)
    else:
        report=sem.merge_semantic_score(ledger,a.decisions,output_path=a.output); print(json.dumps({'passed':True,'counts':report['counts'],'metrics':report['metrics']})); return 0
    print(json.dumps({'passed':True,'selected':len(rows)})); return 0
if __name__=='__main__': raise SystemExit(main())
