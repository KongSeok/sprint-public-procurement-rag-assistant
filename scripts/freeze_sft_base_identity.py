#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,os,re
from pathlib import Path
from midprojectrag.ingest.common import canonical_json, sha256_file

def main(argv=None):
 p=argparse.ArgumentParser(); p.add_argument('--model-id',required=True); p.add_argument('--revision',required=True); p.add_argument('--identity-dir',type=Path,required=True); p.add_argument('--output',type=Path,required=True); a=p.parse_args(argv)
 if a.model_id!='Qwen/Qwen3.5-9B' or not re.fullmatch(r'[0-9a-f]{40}',a.revision): raise ValueError('sft_base_identity_invalid')
 required=('config.json','tokenizer_config.json','tokenizer.json','chat_template.jinja'); d=a.identity_dir.resolve()
 files={name:{'sha256':sha256_file(d/name),'bytes':(d/name).stat().st_size} for name in required}
 value={'schema_version':'evo-sft-base-identity-v1','model_id':a.model_id,'revision':a.revision,'files':files}
 value['identity_sha256']=__import__('hashlib').sha256(canonical_json(value).encode()).hexdigest()
 a.output.parent.mkdir(parents=True,exist_ok=True); os.umask(0o077)
 with a.output.open('x',encoding='utf-8') as f:f.write(canonical_json(value)+'\n')
 print(canonical_json(value)); return 0
if __name__=='__main__': raise SystemExit(main())
