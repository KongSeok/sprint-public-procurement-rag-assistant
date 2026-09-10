#!/usr/bin/env python3
from __future__ import annotations
import argparse, platform
from importlib import metadata
from pathlib import Path
from midprojectrag.evo_harness.training import BACKEND_RECEIPT_SCHEMA
from midprojectrag.ingest.common import canonical_json

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument('--output',type=Path,required=True); a=p.parse_args(argv)
    versions={}
    for name in ('torch','bitsandbytes'):
        try: versions[name]=metadata.version(name)
        except metadata.PackageNotFoundError: versions[name]=None
    r={'schema_version':BACKEND_RECEIPT_SCHEMA,'mode':'qlora4','probe':'linear4bit_nf4_forward','available':False,
       'versions':versions,'platform':{'system':platform.system(),'machine':platform.machine(),'python':platform.python_version()},'device':'unavailable'}
    try:
        import torch, bitsandbytes as bnb
        if torch.cuda.is_available(): device=torch.device('cuda')
        elif hasattr(torch.backends,'mps') and torch.backends.mps.is_available(): device=torch.device('mps')
        elif hasattr(torch,'xpu') and torch.xpu.is_available(): device=torch.device('xpu')
        else: device=torch.device('cpu')
        r['device']=str(device)
        layer=bnb.nn.Linear4bit(16,16,bias=False,compute_dtype=torch.bfloat16,compress_statistics=True,quant_type='nf4').to(device)
        x=torch.zeros((1,16),dtype=torch.bfloat16,device=device)
        with torch.no_grad(): y=layer(x)
        if tuple(y.shape)!=(1,16) or not bool(torch.isfinite(y).all().item()): raise RuntimeError('probe_invalid')
        r['available']=True
    except Exception as e:
        r['error_type']=type(e).__name__
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x',encoding='utf-8') as f: f.write(canonical_json(r)+'\n')
    a.output.chmod(0o600); print(canonical_json(r)); return 0 if r['available'] else 2
if __name__=='__main__': raise SystemExit(main())
