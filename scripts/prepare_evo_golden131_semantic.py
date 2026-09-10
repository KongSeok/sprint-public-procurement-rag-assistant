#!/usr/bin/env python3
from __future__ import annotations
import argparse, copy, json, os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from midprojectrag import local_mini131_baseline as mini
from midprojectrag import local_mini131_semantic as sem
from midprojectrag.ingest.common import canonical_json, sha256_file, sha256_text
from midprojectrag.mini131_bundle import BLIND_JUDGE_INPUT_SCHEMA_VERSION, JUDGE_MODEL, JUDGE_RUBRIC, _assert_blind, _blind_id
IDENTITY_KEYS=frozenset({'case_id','lane','lineage','group_id','run_id','model'})

def strip_identity(v:Any, case_id:str)->Any:
    if isinstance(v,Mapping):
        out={}
        for k,x in v.items():
            lk=str(k).lower()
            if lk in IDENTITY_KEYS or lk.endswith('_case_id') or lk=='path' or (lk.endswith('_path') and lk!='section_path'):
                continue
            out[str(k)]=strip_identity(x,case_id)
        return out
    if isinstance(v,list): return [strip_identity(x,case_id) for x in v]
    if isinstance(v,str): return v.replace(case_id,'opaque-case')
    return copy.deepcopy(v)

def evidence_from(record:Mapping[str,Any])->list[dict[str,Any]]:
    out=[]
    for action in (record.get('result') or {}).get('actions') or []:
        if not isinstance(action,Mapping): continue
        obs=action.get('observation')
        if action.get('tool')=='search' and isinstance(obs,Mapping):
            for cand in obs.get('candidates') or []:
                if isinstance(cand,Mapping): out.append({k:copy.deepcopy(v) for k,v in cand.items() if k in {'doc_id','excerpt','kind'}})
    return out

def main(argv=None)->int:
    p=argparse.ArgumentParser(); p.add_argument('--source-repo-root',type=Path,required=True); p.add_argument('--source-config',type=Path,required=True); p.add_argument('--records',type=Path,required=True); p.add_argument('--output-dir',type=Path,required=True); p.add_argument('--shards',type=int,default=9); a=p.parse_args(argv)
    suite=mini.verify_suite(repo_root=a.source_repo_root.resolve(),config_path=a.source_config.resolve())
    records=[json.loads(x) for x in a.records.read_text(encoding='utf-8').splitlines() if x.strip()]
    if len(records)!=129 or len({r.get('case_id') for r in records})!=129: raise ValueError('evo_semantic_candidate_inventory_invalid')
    by_id={str(r['case_id']):r for r in records}
    if set(by_id)!=set(suite.cases_by_id): raise ValueError('evo_semantic_suite_identity_mismatch')
    rubric=a.source_repo_root/'evaluation/rubric.md'; judge_cfg=a.source_repo_root/'evaluation/baselines/mini131-bundle-v1/judge-config.json'
    review_cfg={'schema_version':'evo35-golden131-semantic-review-config.v1','model':JUDGE_MODEL,'reasoning_effort':'high','rubric_version':JUDGE_RUBRIC,'rubric_sha256':sha256_file(rubric),'judge_config_sha256':sha256_file(judge_cfg),'fresh_decisions_required':True}
    review_cfg_sha=sha256_text(canonical_json(review_cfg)); records_sha=sha256_file(a.records)
    rows=[]; maps=[]; statuses=Counter()
    for case_id in sorted(by_id):
        record=by_id[case_id]; source=suite.cases_by_id[case_id]
        cls=record.get('classification'); observed=record.get('observed') or {}; result=record.get('result') or {}; response=result.get('response') or {}
        raw_status=observed.get('status') if cls=='executed_text' else 'unsupported_specialist'
        status=raw_status if raw_status in {'answered','abstained'} else 'error'; statuses[status]+=1
        answer=response.get('answer','') if status!='error' else ''
        if not isinstance(answer,str): answer=''
        cited=observed.get('cited_doc_ids') or response.get('cited_doc_ids') or []
        evidence=evidence_from(record) if cls=='executed_text' else []
        judge_input={
            'question_kind':sem.QUESTION_KINDS[source.lane],
            'question':source.source['question'],
            'expected':mini._expected(source),
            'candidate':{'status':status,'answer':answer,'chat':[{'role':'user','content':source.source['question']},{'role':'assistant','content':answer}]},
            'retrieval':{'retrieved_docs':observed.get('retrieved_doc_ids') or [],'cited_docs':cited if status!='error' else [],'evidence':evidence,'evidence_status':'available' if evidence else 'unavailable','evaluation_status':'ready' if cls=='executed_text' else 'not_evaluated'}
        }
        if response.get('unresolved'): judge_input['candidate']['unresolved']=copy.deepcopy(response['unresolved'])
        if status=='abstained': judge_input['candidate']['abstention_reason']=response.get('abstention_reason') or (response.get('unresolved') or ['candidate_abstained'])
        judge_input=strip_identity(judge_input,case_id)
        binding=sha256_text(canonical_json({'source_sha256':record.get('source_sha256'),'records_sha256':records_sha,'review_config_sha256':review_cfg_sha}))
        judge_input['evaluation_context']={'schema_version':'evo35-fresh-review-binding.v1','fresh_review_binding_sha256':binding}
        _assert_blind(judge_input)
        serialized=canonical_json(judge_input).casefold()
        if case_id.casefold() in serialized or 'qwen' in serialized or '/resources/' in serialized: raise ValueError('evo_semantic_identity_leak')
        h=sha256_text(canonical_json(judge_input)); blind=_blind_id(h)
        rows.append({'schema_version':BLIND_JUDGE_INPUT_SCHEMA_VERSION,'blind_id':blind,'judge_input_sha256':h,'judge_input':judge_input})
        maps.append({'blind_id':blind,'case_id':case_id,'lane':source.lane,'judge_input_sha256':h,'source_case_sha256':source.source_sha256,'candidate_sha256':sha256_text(canonical_json(record)),'fresh_review_binding_sha256':binding})
    rows.sort(key=lambda r:r['blind_id']); maps.sort(key=lambda r:r['blind_id'])
    out=a.output_dir; out.mkdir(parents=True,exist_ok=False,mode=0o700); os.chmod(out,0o700)
    def write_jsonl(path,items):
        path.write_text(''.join(canonical_json(x)+'\n' for x in items),encoding='utf-8'); path.chmod(0o600)
    write_jsonl(out/'primary-inputs.jsonl',rows); write_jsonl(out/'review-map.jsonl',maps)
    for n in range(1,a.shards+1):
        s=len(rows)*(n-1)//a.shards; e=len(rows)*n//a.shards
        write_jsonl(out/f'primary-{n:02d}-of-{a.shards:02d}.jsonl',rows[s:e])
    manifest={
        'schema_version':'evo35-golden131-semantic-prepare.v1',
        'prepared_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
        'count':len(rows),'statuses':dict(statuses),'shards':a.shards,
        'records_sha256':records_sha,'suite_config_sha256':suite.config_sha256,
        'eval_set_sha256':suite.eval_set_sha256,'review_config':review_cfg,
        'review_config_sha256':review_cfg_sha,
        'primary_inputs_sha256':sha256_file(out/'primary-inputs.jsonl'),
        'review_map_sha256':sha256_file(out/'review-map.jsonl'),
        'semantic_judgment':'not_run','gold_review_status':'draft'
    }
    (out/'prepare-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    (out/'prepare-manifest.json').chmod(0o600)
    print(canonical_json(manifest)); return 0
if __name__=='__main__': raise SystemExit(main())
