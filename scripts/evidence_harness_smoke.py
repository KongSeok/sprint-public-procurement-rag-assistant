"""Prepare/run a single SYNTHETIC local transport smoke, never gold evaluation."""
from __future__ import annotations

import argparse
from pathlib import Path

from midprojectrag.evidence import Evidence, EvidenceStore
from midprojectrag.orchestration.artifacts import write_private_json
from midprojectrag.orchestration.cli import main as run_harness


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true", help="Actually call pinned local model on synthetic text")
    parser.add_argument("--output-name", default="synthetic-live-trace.json")
    args = parser.parse_args()
    root = Path.cwd() / "private" / "evidence-harness"
    page = Evidence.create(doc_id="doc_000000000000000000000001", page=1, kind="page",
                           text="The alpha budget is 10 tokens.", source_block_ids=("block_000000000000000000000001",))
    child = Evidence.create(doc_id=page.doc_id, page=1, kind="text", text=page.text,
                            source_block_ids=page.source_block_ids, parent_id=page.evidence_id)
    request = {"schema_version": "1.0", "request_id": "synthetic-local-smoke", "question": "What is the alpha budget?",
               "history": [], "document_scope": {"mode": "explicit", "doc_ids": [page.doc_id]},
               "options": {"max_citations": 5}}
    for name, value in (("synthetic-evidence.json", EvidenceStore((page, child)).to_dict()), ("synthetic-request.json", request)):
        path = root / name
        if not path.exists():
            write_private_json(path, value, private_root=root)
    if args.run:
        return run_harness(["run", "--evidence", str(root / "synthetic-evidence.json"), "--request", str(root / "synthetic-request.json"),
                            "--output", str(root / args.output_name), "--synthetic", "--timeout-seconds", "180"])
    print("Synthetic smoke inputs prepared; provider calls=0.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
