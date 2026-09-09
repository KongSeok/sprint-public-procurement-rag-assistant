#!/usr/bin/env python3
"""Build hash-only historical-evaluation exclusions before Evo training data authoring."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path

from midprojectrag.evo_harness.training_inventory import build_historical_exclusion_inventory
from midprojectrag.ingest.common import canonical_json


def _write_new(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(canonical_json(value) + "\n")
    path.chmod(0o600)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repo-root", type=Path, required=True)
    parser.add_argument("--mini131-config", type=Path, required=True)
    parser.add_argument("--extra-eval", type=Path, action="append", default=[])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    os.umask(0o077)
    result = build_historical_exclusion_inventory(
        source_repo_root=args.source_repo_root,
        mini131_config=args.mini131_config,
        extra_evaluation_paths=args.extra_eval,
    )
    args.output_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    _write_new(args.output_dir / "exclusion-manifest.json", result["manifest"])
    _write_new(args.output_dir / "inventory-receipt.json", result["receipt"])
    print(json.dumps(result["receipt"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
