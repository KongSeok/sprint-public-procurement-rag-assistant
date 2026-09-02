"""Offline preparation entrypoint. Never called by the live query runtime."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from midprojectrag.evidence import EvidenceStore
from midprojectrag.orchestration.artifacts import read_json, write_private_json
from .gates import inspect_artifacts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Offline Evidence-Harness preparation, no training jobs")
    subs = parser.add_subparsers(dest="command", required=True)
    preflight = subs.add_parser("preflight")
    preflight.add_argument("--manifest", type=Path, required=True)
    export = subs.add_parser("export")
    export.add_argument("--trace", type=Path, required=True)
    export.add_argument("--evidence", type=Path, required=True)
    export.add_argument("--split-manifest", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--allow-synthetic", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            result = inspect_artifacts(read_json(args.manifest), base_dir=args.manifest.parent)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result["artifact_manifests_present"] else 3
        from .training import export_training_rows
        split = read_json(args.split_manifest)
        if (not isinstance(split, dict) or set(split) != {"training", "heldout"}
                or any(not isinstance(split[key], list) or any(not isinstance(i, str) for i in split[key]) for key in split)):
            raise ValueError("invalid_split_manifest")
        result = export_training_rows(read_json(args.trace), store=EvidenceStore.from_dict(read_json(args.evidence)),
                                      training_allowlist=frozenset(split["training"]), heldout_fingerprints=frozenset(split["heldout"]),
                                      allow_synthetic=args.allow_synthetic)
        write_private_json(args.output, result, private_root=Path.cwd() / "private" / "evidence-harness")
        print(json.dumps({"status": "preparation_only", "approved_for_runtime": False}))
        return 0
    except Exception:
        print(json.dumps({"status": "error", "reason": "offline_contract_failure"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
