"""Private, model-free Mini131 readiness audit; never issues formal approval."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from .evidence.artifacts import file_sha, load_bundle, private_path, write_new_json
from .runtime_integrity import RuntimeRequest, validate_runtime_request_snapshot
from .stage_checkpoints import canonical_sha
from .stage_document_qrels import validate_document_inventory
from .stage_evaluation import _json_object, _json_rows, load_source_snapshot
from .stage_inputs import build_inputs


def _source_request(case):
    """Same original projection as verify_suite, never gold-derived scope."""
    row = case.source
    if case.lane == "core40":
        return {"question": row["question"], "history": row["history"], "document_scope": row["document_scope"]}
    if case.lane in {"supplemental_answer_legacy", "supplemental_answer_rerun"}:
        ids = row["scope_doc_ids"]
        if type(ids) is not list or any(type(d) is not str for d in ids):
            raise ValueError("readiness_original_scope_invalid")
        return {"question": row["question"], "history": [],
                "document_scope": {"mode": "explicit", "doc_ids": ids} if ids else {"mode": "all", "doc_ids": []}}
    if case.lane == "visual":
        return {"question": row["question"], "history": [], "document_scope": row["document_scope"]}
    return None


def _request_readiness(template, known_docs):
    result = {"status": "unavailable", "reason": "runtime_request_missing", "fingerprint_sha256": None,
              "scope_mode": None, "scope_document_count": None, "history_turns": None,
              "actual_query_sha256": None, "query_token_budget": "not_checked"}
    if template is None:
        return result
    try:
        request = RuntimeRequest.from_dict(template)
        validate_runtime_request_snapshot(request)
    except (ValueError, TypeError, KeyError, AttributeError):
        return result | {"reason": "invalid_original_runtime_request"}
    scope = request.document_scope
    result.update(fingerprint_sha256=request.fingerprint, scope_mode=scope["mode"],
                  scope_document_count=len(scope["doc_ids"]), history_turns=len(request.history))
    if request.metadata_filters or request.options or request.prior_citation_state is not None:
        return result | {"reason": "recorder_request_feature_not_supported"}
    if not set(scope["doc_ids"]).issubset(known_docs):
        return result | {"reason": "request_scope_outside_snapshot"}
    return result | {"status": "available", "reason": None}


def audit_readiness(suite, inventory, qrels, *, snapshot, qrels_file_sha256):
    """Report technical candidates, not a paired denominator or a semantic verdict.

Source-owned request templates are never filled from gold. The full input adapter
projection is rebuilt so an unrelated receipt cannot attach to these requests.
"""
    docs = validate_document_inventory(inventory, qrels, snapshot=snapshot, qrels_file_sha256=qrels_file_sha256)
    projected = build_inputs(suite.cases, suite.ledger_rows, snapshot,
                            {k: v["sha256"] for k, v in suite.config["sources"].items()}, suite.parser_receipt)
    projected.pop("inputs_sha256")
    projected["input_config_sha256"] = suite.config_sha256
    if (canonical_sha(projected) != inventory["inputs_sha256"] or projected["qrels"] != list(qrels)
            or projected["cases"] != inventory["cases"]):
        raise ValueError("readiness_verified_input_binding_mismatch")
    cases = {c.case_id: c for c in suite.cases}
    known_docs = {d for d, _ in snapshot.locators}
    rows = []
    for original in inventory["cases"]:
        cid, suite_name = original["case_id"], original["suite"]
        if suite_name == "parser2":
            request = _request_readiness(None, known_docs) | {"status": "not_applicable", "reason": "parser_receipt_only"}
        else:
            case = cases[cid]
            template, expected = case.request_template, _source_request(case)
            request = _request_readiness(template, known_docs)
            # Additional supported/unsupported options are checked separately. A
            # valid request for another question/scope must not earn readiness.
            if template is not None and (expected is None or type(template) is not dict
                    or any(template.get(k) != v for k, v in expected.items())):
                request = request | {"status": "unavailable", "reason": "source_request_mismatch"}
        technical = {}
        for unit, qrel_status in (("source_anchor", original["qrel_status"]), ("document", docs[cid].status)):
            reasons = []
            if qrel_status != "ready":
                reasons.append("qrels_" + qrel_status)
            if request["status"] != "available":
                reasons.append(request["reason"])
            technical[unit] = {"candidate": not reasons, "reasons": reasons}
        rows.append({"case_id": cid, "suite": suite_name, "source_row_sha256": original["source_row_sha256"],
                     "source_qrel_status": original["qrel_status"], "source_anchor_count": original["required_anchor_count"],
                     "document_qrel_status": docs[cid].status, "original_document_count": len(original["required_doc_ids"]),
                     "source_review_status": original["source_review_status"],
                     "source_review_sha256": original["source_review_sha256"],
                     "reviewed_draft_sha256": original["reviewed_draft_sha256"],
                     "approval_binding": "not_evaluated", "request": request, "technical": technical})
    def summarize(selected):
        return {"case_count": len(selected), "request_status_counts": dict(Counter(r["request"]["status"] for r in selected)),
                "technical_candidate_counts": {unit: sum(r["technical"][unit]["candidate"] for r in selected)
                                               for unit in ("source_anchor", "document")},
                "source_review_status_counts": dict(Counter(r["source_review_status"] for r in selected)),
                "approval_binding_counts": dict(Counter(r["approval_binding"] for r in selected))}
    report = {"schema_version": "retrieval-readiness-v1", "status": "audit_complete_decisions_pending",
              "request_binding_policy": "verified_source_question_history_scope_v1",
              "measurement_kind": "technical_readiness_not_quality_or_approval", "formal_comparison_authorized": False,
              "formal_pair_count": None, "model_calls": 0, "api_calls": 0, "generation_calls": 0,
              "index_runtime_validation": "not_performed", "query_token_budget": "not_checked",
              "input_inventory_sha256": inventory["inventory_sha256"], "source_snapshot_sha256": snapshot.snapshot_sha256,
              "source_file_sha256s": dict(inventory["source_file_sha256s"]), "input_config_sha256": suite.config_sha256,
              "cases": rows, "summary": summarize(rows),
              "by_suite": {s: summarize([r for r in rows if r["suite"] == s]) for s in inventory["suite_counts"]},
              "remaining_decisions": ["bind_human_qrel_approval", "set13_retrieval_scope_policy",
                                      "primary_metric_cutoff_threshold_and_fixed_pair_error_policy"],
              "approval_import_gaps": ["supplemental_finalizer_page_field_requires_validated_projection",
                                       "approved_only_output_cannot_replace_full_131_inventory"],
              "review_interpretation": "source_status_is_not_a_verdict_on_historical_human_review"}
    return report | {"report_sha256": canonical_sha(report)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repo-root", "config", "data-root", "bundle", "manifest", "blocks-dir", "inputs-dir", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        output = private_path(args.output, args.data_root)
        if output.exists():
            raise ValueError("readiness_new_output_required")
        inputs = private_path(args.inputs_dir, args.data_root)
        input_paths = (inputs / "inventory.json", inputs / "qrels.jsonl")
        before = {p.name: file_sha(p) for p in input_paths}
        inventory = _json_object(input_paths[0].read_bytes())
        raw = input_paths[1].read_bytes()
        from .local_mini131_baseline import verify_suite
        suite = verify_suite(repo_root=args.repo_root, config_path=args.config)
        store, receipt = load_bundle(args.bundle, data_root=args.data_root)
        snapshot = load_source_snapshot(data_root=args.data_root, manifest=args.manifest, blocks_dir=args.blocks_dir,
                                        store=store, input_hashes=receipt["input_hashes"])
        report = audit_readiness(suite, inventory, _json_rows(raw), snapshot=snapshot, qrels_file_sha256=before["qrels.jsonl"])
        after_suite = verify_suite(repo_root=args.repo_root, config_path=args.config)
        after = load_source_snapshot(data_root=args.data_root, manifest=args.manifest, blocks_dir=args.blocks_dir,
                                     store=store, input_hashes=receipt["input_hashes"])
        if (before != {p.name: file_sha(p) for p in input_paths} or after.snapshot_sha256 != snapshot.snapshot_sha256
                or after_suite.config_sha256 != suite.config_sha256 or after_suite.eval_set_sha256 != suite.eval_set_sha256):
            raise ValueError("readiness_input_changed_during_audit")
        report.pop("report_sha256")
        report["input_file_sha256s"] = before
        report["evidence_store_sha256"] = store.bundle_sha256
        report["report_sha256"] = canonical_sha(report)
        write_new_json(output, report)
        print(json.dumps({k: report[k] for k in ("status", "summary", "formal_comparison_authorized", "model_calls", "report_sha256")}))
        return 0
    except (ValueError, TypeError, AttributeError, KeyError, OSError, UnicodeError):
        print(json.dumps({"status": "rejected", "reason": "invalid_or_unavailable_private_readiness_input"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
