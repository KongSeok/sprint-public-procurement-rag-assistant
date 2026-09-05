"""Project pinned Mini131 sources to private evaluator-only location sidecars.

No question, answer, candidate gold, runtime request, or model call is produced.
Structural availability is deliberately not semantic approval.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Mapping, Sequence

from .evidence.artifacts import load_bundle, private_path, write_new_json
from .stage_checkpoints import canonical_sha
from .stage_evaluation import MINI131_SUITE_COUNTS, SourceSnapshot, _hash, _identifier, _qrels, load_source_snapshot

SCHEMA = "mini131-stage-inputs-v1"
SOURCE_KEYS = frozenset({"core40", "supplemental_answers", "supplemental_sets", "visual",
                         "analytics", "analytics_calculations", "integrated_ledger", "parser_receipt"})
LANES = {"core40": "core40", "supplemental_answer_legacy": "answer56",
         "supplemental_answer_rerun": "answer56", "supplemental_set_rerun": "set13",
         "visual": "visual10", "corpus_analytics": "analytics10"}
EXPECTED_LANES = {"core40": 40, "supplemental_answer_legacy": 39, "supplemental_answer_rerun": 17,
                  "supplemental_set_rerun": 13, "visual": 10, "corpus_analytics": 10}


def _review(row: dict) -> dict:
    review = row.get("review", {})
    if type(review) is not dict:
        raise ValueError("invalid_source_review")
    status = review.get("status")
    if status not in {"draft", "approved", "rejected", "pending", "reviewed"}:
        status = "unrecognized" if status is not None else "not_recorded"
    previous = row.get("reviewed_draft_sha256")
    if previous is not None:
        _hash(previous)
    return {"source_review_status": status, "source_review_sha256": canonical_sha(review),
            "reviewed_draft_sha256": previous, "semantic_approval": "not_assessed_by_adapter"}


def build_inputs(cases: Sequence, ledger_rows: Mapping[str, dict], snapshot: SourceSnapshot,
                 source_file_hashes: Mapping[str, str], parser_receipt: dict) -> dict:
    """Validate identities and reuse only source-owned, exact block references."""
    if set(source_file_hashes) != SOURCE_KEYS:
        raise ValueError("mini131_source_files_incomplete")
    for value in source_file_hashes.values():
        _hash(value)
    if len(cases) != 129 or len(ledger_rows) != 131:
        raise ValueError("mini131_inventory_incomplete")
    if Counter(c.lane for c in cases) != Counter(EXPECTED_LANES):
        raise ValueError("mini131_lane_counts_mismatch")
    ids = [c.case_id for c in cases]
    parser_ids = [cid for cid, row in ledger_rows.items() if row.get("lane") == "parser_regression"]
    if len(set(ids)) != 129 or len(parser_ids) != 2 or set(ids) & set(parser_ids) or set(ids + parser_ids) != set(ledger_rows):
        raise ValueError("mini131_case_ledger_mismatch")
    if parser_receipt.get("artifacts", {}).get("manifest_sha256") != snapshot.manifest_sha256:
        raise ValueError("parser_manifest_mismatch")
    qrels, availability = [], []
    docs = {doc for doc, _ in snapshot.locators}
    for case in cases:
        _identifier(case.case_id)
        row, ledger = case.source, ledger_rows[case.case_id]
        if (row.get("case_id") != case.case_id or canonical_sha(row) != case.source_sha256
                or ledger.get("case_id") != case.case_id or ledger.get("lane") != case.lane
                or ledger.get("case_type") != "rag"):
            raise ValueError("source_case_identity_mismatch")
        suite = LANES[case.lane]
        manifest = (row.get("calculation_contract", {}).get("manifest_sha256")
                    if suite == "analytics10" else row.get("source_manifest_sha256"))
        if manifest != snapshot.manifest_sha256:
            raise ValueError("source_manifest_mismatch")
        gold = row.get("gold", {})
        refs = []
        reason = None
        if suite in {"visual10", "analytics10"}:
            status, reason = "not_applicable", "specialized_metric_required"
        elif suite == "set13":
            status, reason = "missing", "source_block_qrels_missing"
        else:
            decision = gold.get("decision")
            if decision not in {"answer", "abstain", "source_conflict"}:
                raise ValueError("unsupported_source_decision")
            refs = gold.get("evidence_refs") if suite == "core40" else row.get("evidence_refs")
            if type(refs) is not list:
                raise ValueError("invalid_source_evidence_refs")
            if decision == "abstain":
                if refs:
                    raise ValueError("abstention_positive_refs_require_review")
                status, reason = "not_applicable", "positive_recall_not_applicable_to_abstention"
            else:
                status = "ready" if refs else "missing"
                reason = None if refs else "source_block_qrels_missing"
        qrel = {"case_id": case.case_id, "suite": suite, "qrel_status": status,
                "required_anchors": [dict(ref) for ref in refs]}
        status, anchors, issue = _qrels(qrel, snapshot)
        # If even one original anchor is unresolved, do not shrink its gold denominator.
        qrel["qrel_status"] = status
        if status != "ready":
            qrel["required_anchors"] = []
        targets = gold.get("required_doc_ids", []) if suite == "core40" else row.get("required_doc_ids", [])
        if type(targets) is not list or any(type(doc) is not str or doc not in docs for doc in targets) or len(set(targets)) != len(targets):
            raise ValueError("invalid_required_document_targets")
        qrels.append(qrel)
        availability.append({"case_id": case.case_id, "suite": suite,
                             "source_row_sha256": case.source_sha256, "source_manifest_status": "matched",
                             "qrel_status": status, "reason": issue or reason,
                             "required_anchor_count": len(anchors), "required_doc_ids": list(targets),
                             **_review(row)})
    for cid in parser_ids:
        _identifier(cid)
        if ledger_rows[cid].get("case_id") != cid:
            raise ValueError("parser_ledger_identity_mismatch")
        qrels.append({"case_id": cid, "suite": "parser2", "qrel_status": "not_applicable", "required_anchors": []})
        availability.append({"case_id": cid, "suite": "parser2", "source_row_sha256": canonical_sha(parser_receipt),
                             "source_manifest_status": "matched", "qrel_status": "not_applicable",
                             "reason": "specialized_metric_required", "required_anchor_count": 0,
                             "required_doc_ids": [], **_review({})})
    counts = dict(Counter(row["suite"] for row in qrels))
    if counts != MINI131_SUITE_COUNTS:
        raise ValueError("mini131_suite_counts_mismatch")
    result = {"schema_version": SCHEMA, "case_count": len(qrels), "suite_counts": counts,
              "source_file_sha256s": dict(source_file_hashes), "source_snapshot_sha256": snapshot.snapshot_sha256,
              "qrel_counts": dict(Counter(row["qrel_status"] for row in qrels)),
              "formal_comparison_authorized": False, "model_calls": 0,
              "qrels": qrels, "cases": availability}
    return result | {"inputs_sha256": canonical_sha(result)}


def write_inputs(inputs: dict, *, output_dir: Path, data_root: Path) -> dict:
    """Exclusive private namespace; inventory is the last complete receipt."""
    body = {k: v for k, v in inputs.items() if k != "inputs_sha256"}
    if inputs.get("schema_version") != SCHEMA or inputs.get("inputs_sha256") != canonical_sha(body):
        raise ValueError("input_projection_hash_mismatch")
    target = private_path(output_dir, data_root)
    raw = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
                  for r in inputs["qrels"]).encode("utf-8")
    inventory = {k: v for k, v in inputs.items() if k != "qrels"}
    inventory["qrels_file_sha256"] = sha256(raw).hexdigest()
    inventory["publication_status"] = "complete"
    inventory["inventory_sha256"] = canonical_sha(inventory)
    target.mkdir(mode=0o700, exist_ok=False)
    descriptor = os.open(target / "qrels.jsonl", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(raw)
    write_new_json(target / "inventory.json", inventory)
    return inventory


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repo-root", "config", "data-root", "bundle", "manifest", "blocks-dir", "output-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        target = private_path(args.output_dir, args.data_root)
        if target.exists():
            raise ValueError("output_already_exists")
        # Imports the existing verifier only; no pipeline/generator is constructed.
        from .local_mini131_baseline import verify_suite
        suite = verify_suite(repo_root=args.repo_root, config_path=args.config)
        store, receipt = load_bundle(args.bundle, data_root=args.data_root)
        snapshot = load_source_snapshot(data_root=args.data_root, manifest=args.manifest, blocks_dir=args.blocks_dir,
                                        store=store, input_hashes=receipt["input_hashes"])
        result = build_inputs(suite.cases, suite.ledger_rows, snapshot,
                              {k: v["sha256"] for k, v in suite.config["sources"].items()}, suite.parser_receipt)
        result["input_config_sha256"] = suite.config_sha256
        result.pop("inputs_sha256")
        result["inputs_sha256"] = canonical_sha(result)
        inventory = write_inputs(result, output_dir=target, data_root=args.data_root)
        print(json.dumps({"status": "prepared", "case_count": inventory["case_count"],
                          "qrel_counts": inventory["qrel_counts"], "inventory_sha256": inventory["inventory_sha256"],
                          "model_calls": 0, "formal_comparison_authorized": False}))
        return 0
    except (ValueError, TypeError, AttributeError, KeyError, OSError, UnicodeError):
        print(json.dumps({"status": "rejected", "reason": "invalid_or_unavailable_private_stage_input"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
