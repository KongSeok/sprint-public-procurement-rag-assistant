#!/usr/bin/env python3
"""Run/resume the frozen Qwen3.5 EvoHarness Mini131 PRE benchmark."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repo-root", required=True, type=Path)
    parser.add_argument("--source-config", required=True, type=Path)
    parser.add_argument("--runtime-data-root", required=True, type=Path)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--mlx-python", required=True, type=Path)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--model-manifest", required=True, type=Path)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--candidate-commit", required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")

    # Critical: configure the copied private cache before importing any
    # Transformers/SentenceTransformers-dependent project module.
    cache = (args.runtime_data_root.resolve() / "private" / "hf-cache").resolve()
    os.environ.update(HF_HOME=str(cache), HF_HUB_CACHE=str(cache / "hub"),
                      HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                      HF_HUB_DISABLE_TELEMETRY="1", TOKENIZERS_PARALLELISM="false",
                      PYTHONDONTWRITEBYTECODE="1", PYTORCH_ENABLE_MPS_FALLBACK="0")

    from midprojectrag.evo_harness.mini131_pre import run
    repo_root = Path(__file__).resolve().parents[1]
    lock_path = args.runtime_data_root.resolve() / "private" / ".evo-mini131-pre.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("evo_mini131_pre_already_running") from exc
        result = run(repo_root=repo_root, source_repo_root=args.source_repo_root,
                     source_config=args.source_config, runtime_data_root=args.runtime_data_root,
                     artifact_dir=args.artifacts, mlx_python=args.mlx_python,
                     model_dir=args.model_dir, model_manifest=args.model_manifest,
                     expected_revision=args.expected_revision, output_dir=args.output_dir,
                     candidate_commit=args.candidate_commit, limit=args.limit)
    finally:
        try: fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally: os.close(lock_fd)
    public = {"schema_version": result["schema_version"], "candidate_commit": result["candidate_commit"], "runner_commit": result["runner_commit"],
              "inventory": result["inventory"], "status_counts": result["status_counts"],
              "objective": result["objective"], "usage": result["usage"],
              "latency_seconds": result["latency_seconds"],
              "semantic_answer_quality": result["semantic_answer_quality"]}
    print(json.dumps(public, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
