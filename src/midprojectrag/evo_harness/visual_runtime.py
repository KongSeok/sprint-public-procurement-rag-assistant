"""Bounded local KURE query child and composition for policy visual tools."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys

from midprojectrag.indexing import visual_ocr_index as index_api
from .state import HarnessError, Unsupported
from .visual import VisualAccess, VisualHotlineTools

SANDBOX = Path("/usr/bin/sandbox-exec")
NETWORK_POLICY = "(version 1) (allow default) (deny network*)"


def offline_command(command):
    if not SANDBOX.is_file():
        raise Unsupported("visual_network_sandbox_unavailable")
    return [str(SANDBOX), "-p", NETWORK_POLICY, *command]


def timeout_value(remaining):
    value = remaining()
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise TimeoutError("visual_deadline")
    return min(float(value), 120.0)


class QueryProcess:
    def __init__(self, *, python, hf_cache, index_dir, private_root, crop_root, work_dir):
        self.python = Path(python)
        if not self.python.is_absolute() or not self.python.is_file():
            raise Unsupported("visual_query_python_required")
        self.hf_cache = Path(hf_cache).resolve(strict=True)
        self.common = {name: str(Path(value).resolve(strict=True)) for name, value in
                       (("index_dir", index_dir), ("private_root", private_root), ("crop_root", crop_root))}
        self.work_dir = Path(work_dir)
        if not self.work_dir.is_absolute() or self.work_dir.is_symlink():
            raise HarnessError("visual_query_output_invalid")
        self.attempts = 0

    def __call__(self, *, query, allowed_doc_ids, top_k, remaining):
        timeout_value(remaining)
        command = offline_command([str(self.python), "-m", __name__])
        self.attempts += 1
        output = self.work_dir / f"search-{self.attempts:03d}"
        output.mkdir(parents=True, mode=0o700, exist_ok=False)
        request = {**self.common, "hf_cache": str(self.hf_cache), "query": query,
                   "doc_ids": None if allowed_doc_ids is None else sorted(allowed_doc_ids), "top_k": top_k}
        index_api._write(output / "request.json", request)
        command += ["--request", str(output / "request.json"), "--output", str(output / "result.json")]
        environment = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "PYTHONDONTWRITEBYTECODE": "1",
                       "PYTHONPATH": str(Path(__file__).resolve().parents[2]), "HF_HUB_OFFLINE": "1",
                       "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
                       "PYTORCH_ENABLE_MPS_FALLBACK": "0", "TOKENIZERS_PARALLELISM": "false"}
        for key in ("HOME", "TMPDIR", "LANG"):
            if key in os.environ:
                environment[key] = os.environ[key]
        try:
            with (output / "worker.log").open("xb") as log:
                (output / "worker.log").chmod(0o600)
                # Keep this child in the owning episode's process group so the
                # outer supervisor can reap all query work on total timeout.
                done = subprocess.run(command, env=environment, stdout=log, stderr=log,
                                      timeout=timeout_value(remaining), check=False)
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("visual_search_deadline") from exc
        timeout_value(remaining)
        if done.returncode:
            raise HarnessError("visual_search_worker_failed")
        return index_api._json(output / "result.json")


def compose_visual_tools(backend, *, base, index_dir, private_root, crop_root,
                         python, hf_cache, work_dir):
    searcher = QueryProcess(python=python, hf_cache=hf_cache, index_dir=index_dir,
                           private_root=private_root, crop_root=crop_root, work_dir=work_dir)
    access = VisualAccess(index_dir=index_dir, private_root=private_root, crop_root=crop_root,
                          searcher=searcher, inspector=backend.inspect_image)
    return VisualHotlineTools(access, base=base)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    os.umask(0o077)
    if args.output.exists():
        raise FileExistsError("visual_query_output_exists")
    request = index_api._json(args.request)
    if set(request) != {"index_dir", "private_root", "crop_root", "hf_cache", "query", "doc_ids", "top_k"}:
        raise ValueError("visual_query_request_invalid")
    docs = request["doc_ids"]
    if docs is not None and (type(docs) is not list or any(type(key) is not str or not key for key in docs)
                             or len(docs) != len(set(docs))):
        raise ValueError("visual_query_scope_invalid")
    provider = index_api.local_provider(Path(request["hf_cache"]), "mps")
    result = index_api.search(index_dir=Path(request["index_dir"]), private_root=Path(request["private_root"]),
                             crop_root=Path(request["crop_root"]), provider=provider,
                             query=request["query"], top_k=request["top_k"],
                             allowed_doc_ids=None if docs is None else frozenset(docs))
    index_api._write(args.output, result)
    print(json.dumps({"hits": len(result["hits"]), "query_input_tokens": result["input_tokens"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
