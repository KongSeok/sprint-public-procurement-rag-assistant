from __future__ import annotations

import io
import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from midprojectrag.ingest.common import canonical_json, sha256_file, sha256_text
from midprojectrag.mini131_report import (
    CASE_SCHEMA_VERSION,
    generate_report,
    main,
    render_html,
    validate_records,
)


def _judgment(case_id: str, *, decision: str = "accepted") -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "judgment_id": "a" * 64,
        "case_id": case_id,
        "case_sha256": "b" * 64,
        "run_record_sha256": "c" * 64,
        "judge_input_sha256": "d" * 64,
        "review_config_sha256": "e" * 64,
        "model": "gpt-5.6-sol",
        "rubric_version": "gpt56-semantic-v2",
        "reviewer_type": "llm",
        "judge_role": "primary",
        "expected_behavior": "answer",
        "observed_status": "answered",
        "judge_decision": decision,
        "scores": {
            "correctness": 1.0,
            "faithfulness": 1.0,
            "completeness": 1.0,
            "factual_claim_coverage": 1.0,
            "citation_validity": 1.0,
            "abstention_quality": None,
        },
        "critical_flags": [],
        "matched_key_point_ids": [],
        "follow_up_success": None,
        "safe_abstention": None,
        "confidence": 0.95,
        "rationale": "private judge rationale",
        "reviewed_at": "2026-08-31T12:00:00+09:00",
    }


def _rag_record(number: int, lineage: str) -> dict[str, object]:
    case_id = f"rag-{number:03d}"
    judgment = _judgment(case_id)
    source_transcript = {
        "case_id": case_id,
        "capture_mode": (
            "posthoc_reconstructed"
            if lineage == "legacy_reconstructed"
            else "prospective_runtime_exact"
        ),
        "generation_prompt": "<script>provider-secret</script>",
        "provider_exchange": {
            "embedding": {"request": {"input": "query"}, "response": {"ok": True}},
            "generation": {"request": {"model": "candidate"}, "response": {"ok": True}},
        },
        "retrieval": [{"doc_id": f"doc-{number:03d}", "rank": 1}],
        "selected_context": [{"doc_id": f"doc-{number:03d}", "text": "evidence"}],
        "assistant": {"final_answer": f"candidate {number}"},
    }
    return {
        "schema_version": CASE_SCHEMA_VERSION,
        "case_id": case_id,
        "case_type": "rag",
        "lane": "core" if number <= 40 else "supplemental",
        "question": "<script>private-secret</script>" if number == 1 else f"question {number}",
        "expected": {"reference_answer": f"expected {number}"},
        "candidate": {
            "status": "answered",
            "answer": f"candidate {number}",
            "lineage": lineage,
            "model": "gpt-5-mini",
            "chat": [{"role": "assistant", "content": f"candidate {number}"}],
        },
        "retrieval": {
            "retrieved_docs": [{"doc_id": f"doc-{number:03d}", "title": "문서"}],
            "cited_docs": [f"doc-{number:03d}"],
            "evidence": [{"doc_id": f"doc-{number:03d}", "page": 1, "text": "evidence"}],
        },
        "source_transcript": source_transcript,
        "source_transcript_sha256": sha256_text(canonical_json(source_transcript)),
        "judgment": judgment,
        "judgment_history": [judgment],
        "judgment_workflow": {
            "secondary_required": False,
            "secondary_present": False,
            "adjudicator_required": False,
            "adjudicator_present": False,
            "primary_binary_recommendation": "accepted",
            "secondary_unresolved": False,
            "disagreement": False,
            "critical_flag_mismatch": False,
            "final_judgment_id": judgment["judgment_id"],
        },
        "parser_result": None,
    }


def _parser_record(number: int, *, passed: bool = True) -> dict[str, object]:
    return {
        "schema_version": CASE_SCHEMA_VERSION,
        "case_id": f"parser-{number}",
        "case_type": "parser",
        "lane": "parser_regression",
        "question": f"parser fallback case {number}",
        "expected": {"fallback": "native_bodytext_fallback"},
        "candidate": {
            "status": "passed" if passed else "failed",
            "answer": "local deterministic check",
            "lineage": "parser_local",
            "model": None,
            "chat": [],
        },
        "retrieval": {"retrieved_docs": [], "cited_docs": [], "evidence": []},
        "source_transcript": None,
        "source_transcript_sha256": None,
        "judgment": None,
        "judgment_history": [],
        "judgment_workflow": None,
        "parser_result": {"passed": passed, "observed": "fallback chain"},
    }


def _records() -> list[dict[str, object]]:
    rows = [_rag_record(number, "legacy_reconstructed") for number in range(1, 40)]
    rows.extend(_rag_record(number, "prospective_rerun") for number in range(40, 130))
    rows.extend([_parser_record(1), _parser_record(2)])
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(canonical_json(row) + "\n" for row in rows), encoding="utf-8")


def _public_aggregate(case_records: Path) -> dict[str, object]:
    scorecard_contract_sha256 = "f" * 64
    return {
        "baseline_id": "mini131-bundle-v1",
        "stage": "case_records_ready",
        "passed": True,
        "counts": {
            "rag": 129,
            "parser": 2,
            "total": 131,
            "full_source_transcripts": 129,
        },
        "artifact_sha256s": {
            "case_records": sha256_file(case_records),
            "inputs": {"scorecard_contract": scorecard_contract_sha256},
        },
        "scorecard_contract_sha256": scorecard_contract_sha256,
        "semantic_judge": {
            "status": "complete",
            "history_validated": True,
            "trigger_resolution_complete": True,
        },
        "privacy": {
            "contains_case_ids": False,
            "contains_questions": False,
            "contains_answers": False,
            "contains_gold": False,
            "contains_source_text": False,
            "contains_provider_payloads": False,
            "private_artifacts_tracked": False,
        },
    }


class Mini131ReportTests(unittest.TestCase):
    def test_renders_complete_filterable_report_and_escapes_private_text(self) -> None:
        records = _records()
        report = render_html(
            records,
            source_sha256="a" * 64,
            public_aggregate={"mean_score": 100.0, "contains_private_text": False},
        )
        self.assertEqual(len(validate_records(records)), 131)
        self.assertIn("39건은 기존 Mini 후보", report)
        self.assertIn("90건은 provider request/response", report)
        self.assertIn("parser 회귀", report)
        self.assertIn('id="lane"', report)
        self.assertIn('id="lineage"', report)
        self.assertIn("Lane summary", report)
        self.assertIn("Conversation summary", report)
        self.assertIn("Full source execution transcript", report)
        self.assertIn("provider_exchange", report)
        self.assertIn("Sol judgment history", report)
        self.assertIn("Judgment workflow", report)
        self.assertIn("Evidence", report)
        self.assertIn("private judge rationale", report)
        self.assertIn("&lt;script&gt;private-secret&lt;/script&gt;", report)
        self.assertIn("&lt;script&gt;provider-secret&lt;/script&gt;", report)
        self.assertNotIn("<script>private-secret</script>", report)
        self.assertNotIn("<script>provider-secret</script>", report)
        self.assertNotIn('src="http', report)
        self.assertNotIn('<link rel="stylesheet"', report)

    def test_cli_atomically_replaces_output_with_private_modes_and_content_free_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_root = root / "evaluation/private/supplemental/runs/provisional-v1"
            run_root.mkdir(parents=True)
            case_records = run_root / "case-records.jsonl"
            aggregate = root / "evaluation/public/aggregate.json"
            aggregate.parent.mkdir(parents=True)
            output = run_root / "gpt56-baseline-score.html"
            _write_jsonl(case_records, _records())
            os.chmod(case_records, 0o644)
            aggregate.write_text(
                json.dumps(_public_aggregate(case_records)),
                encoding="utf-8",
            )
            output.write_text("old report", encoding="utf-8")
            os.chmod(output, 0o644)
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                status_code = main(
                    [
                        "--case-records",
                        str(case_records),
                        "--public-aggregate",
                        str(aggregate),
                        "--output",
                        str(output),
                    ]
                )
            receipt = json.loads(stdout.getvalue())
            self.assertEqual(status_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertEqual(set(receipt), {"count", "sha256"})
            self.assertEqual(receipt["count"], 131)
            self.assertEqual(len(receipt["sha256"]), 64)
            self.assertNotIn("private-secret", stdout.getvalue())
            self.assertNotEqual(output.read_text(encoding="utf-8"), "old report")
            self.assertEqual(stat.S_IMODE(case_records.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)

    def test_invalid_ledger_fails_before_replacing_existing_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_root = root / "evaluation/private/supplemental/runs/provisional-v1"
            run_root.mkdir(parents=True)
            case_records = run_root / "case-records.jsonl"
            output = run_root / "gpt56-baseline-score.html"
            _write_jsonl(case_records, _records()[:-1])
            output.write_text("keep this", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "mini131_case_ledger_mismatch"):
                generate_report(case_records_path=case_records, output_path=output)
            self.assertEqual(output.read_text(encoding="utf-8"), "keep this")

    def test_source_transcript_and_public_receipt_hashes_fail_closed(self) -> None:
        records = _records()
        records[0]["source_transcript"]["tampered"] = True  # type: ignore[index]
        with self.assertRaisesRegex(
            ValueError, "mini131_source_transcript_hash_mismatch"
        ):
            validate_records(records)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_root = root / "evaluation/private/supplemental/runs/provisional-v1"
            run_root.mkdir(parents=True)
            case_records = run_root / "case-records.jsonl"
            output = run_root / "gpt56-baseline-score.html"
            aggregate = root / "evaluation/public/aggregate.json"
            aggregate.parent.mkdir(parents=True)
            _write_jsonl(case_records, _records())
            public = _public_aggregate(case_records)
            public["artifact_sha256s"]["case_records"] = "0" * 64  # type: ignore[index]
            aggregate.write_text(json.dumps(public), encoding="utf-8")
            output.write_text("keep this", encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError, "mini131_public_aggregate_case_records_mismatch"
            ):
                generate_report(
                    case_records_path=case_records,
                    public_aggregate_path=aggregate,
                    output_path=output,
                )
            self.assertEqual(output.read_text(encoding="utf-8"), "keep this")

            public = _public_aggregate(case_records)
            public["scorecard_contract_sha256"] = "0" * 64
            aggregate.write_text(json.dumps(public), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError,
                "mini131_public_aggregate_scorecard_contract_mismatch",
            ):
                generate_report(
                    case_records_path=case_records,
                    public_aggregate_path=aggregate,
                    output_path=output,
                )
            self.assertEqual(output.read_text(encoding="utf-8"), "keep this")

    def test_legacy_fixture_without_full_transcript_fields_remains_renderable(self) -> None:
        records = _records()
        for record in records:
            for field in (
                "source_transcript",
                "source_transcript_sha256",
                "judgment_history",
                "judgment_workflow",
            ):
                record.pop(field)
        self.assertEqual(len(validate_records(records)), 131)
        report = render_html(records, source_sha256="a" * 64)
        self.assertIn("source execution transcript not applicable", report)

    def test_fixed_sol_v2_judge_is_enforced(self) -> None:
        records = _records()
        records[0]["judgment"]["model"] = "gpt-5-mini"  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "mini131_judge_model_mismatch"):
            validate_records(records)

    def test_exact_v2_score_key_and_half_step_components_are_enforced(self) -> None:
        records = _records()
        scores = records[0]["judgment"]["scores"]  # type: ignore[index]
        scores["factual_claim_citation_coverage"] = scores.pop("factual_claim_coverage")
        with self.assertRaisesRegex(ValueError, "mini131_judge_score_fields_missing"):
            validate_records(records)

        records = _records()
        records[0]["judgment"]["scores"]["correctness"] = 0.25  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "mini131_answer_component_invalid"):
            validate_records(records)

    def test_closed_judgment_cannot_add_an_explicit_semantic_score(self) -> None:
        records = _records()
        records[0]["judgment"]["semantic_score"] = 0.0  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "mini131_judgment_fields_invalid"):
            validate_records(records)

    def test_judge_decision_must_follow_score_confidence_and_flags(self) -> None:
        records = _records()
        judgment = records[0]["judgment"]  # type: ignore[assignment]
        for field in (
            "correctness",
            "faithfulness",
            "completeness",
            "factual_claim_coverage",
            "citation_validity",
        ):
            judgment["scores"][field] = 0.0  # type: ignore[index]
        judgment["confidence"] = 0.1
        judgment["critical_flags"] = ["material_hallucination"]
        with self.assertRaisesRegex(ValueError, "mini131_judge_decision_inconsistent"):
            validate_records(records)

        records = _records()
        judgment = records[0]["judgment"]  # type: ignore[assignment]
        judgment["confidence"] = 0.5
        with self.assertRaisesRegex(ValueError, "mini131_judge_decision_inconsistent"):
            validate_records(records)

    def test_adjudicator_acceptance_uses_the_frozen_above_85_threshold(self) -> None:
        records = _records()
        judgment = records[0]["judgment"]  # type: ignore[assignment]
        judgment["judge_role"] = "adjudicator"
        judgment["scores"]["factual_claim_coverage"] = 0.5  # type: ignore[index]
        judgment["scores"]["citation_validity"] = 0.0  # type: ignore[index]
        judgment["judge_decision"] = "accepted"
        with self.assertRaisesRegex(ValueError, "mini131_judge_decision_inconsistent"):
            validate_records(records)

        judgment["judge_decision"] = "rejected"
        self.assertEqual(len(validate_records(records)), 131)

    def test_unknown_abstention_allows_null_answer_components(self) -> None:
        records = _records()
        judgment = records[0]["judgment"]  # type: ignore[assignment]
        for field in (
            "correctness",
            "faithfulness",
            "completeness",
            "factual_claim_coverage",
            "citation_validity",
        ):
            judgment["scores"][field] = None  # type: ignore[index]
        judgment["scores"]["abstention_quality"] = 0.5  # type: ignore[index]
        judgment["safe_abstention"] = True  # type: ignore[index]
        judgment["expected_behavior"] = "abstain"  # type: ignore[index]
        judgment["observed_status"] = "abstained"  # type: ignore[index]
        judgment["judge_decision"] = "rejected"  # type: ignore[index]
        records[0]["candidate"]["status"] = "abstained"  # type: ignore[index]
        self.assertEqual(len(validate_records(records)), 131)
        report = render_html(records, source_sha256="a" * 64)
        self.assertIn('<span class="score">50.00</span>', report)

    def test_null_answer_component_without_abstention_score_fails_closed(self) -> None:
        records = _records()
        records[0]["judgment"]["scores"]["completeness"] = None  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "mini131_answer_score_mode_required"):
            validate_records(records)

    def test_expected_behavior_selects_exact_score_mode(self) -> None:
        records = _records()
        judgment = records[0]["judgment"]  # type: ignore[assignment]
        judgment["scores"]["abstention_quality"] = 1.0  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "mini131_answer_score_mode_required"):
            validate_records(records)

        records = _records()
        judgment = records[0]["judgment"]  # type: ignore[assignment]
        judgment["expected_behavior"] = "abstain"
        with self.assertRaisesRegex(ValueError, "mini131_abstention_score_mode_required"):
            validate_records(records)

    def test_observed_status_mismatch_requires_rejection(self) -> None:
        records = _records()
        judgment = records[0]["judgment"]  # type: ignore[assignment]
        records[0]["candidate"]["status"] = "abstained"  # type: ignore[index]
        judgment["observed_status"] = "abstained"
        judgment["judge_decision"] = "accepted"
        with self.assertRaisesRegex(ValueError, "mini131_judge_decision_inconsistent"):
            validate_records(records)

        judgment["judge_decision"] = "rejected"
        self.assertEqual(len(validate_records(records)), 131)

    def test_needs_review_is_included_in_failure_review_filter(self) -> None:
        records = _records()
        judgment = records[0]["judgment"]  # type: ignore[assignment]
        judgment["scores"]["correctness"] = 0.5  # type: ignore[index]
        judgment["judge_decision"] = "needs_review"
        report = render_html(records, source_sha256="a" * 64)
        self.assertRegex(
            report,
            r'data-verdict="needs_review"[^>]*data-failure="1"',
        )

    def test_html_output_must_stay_under_real_evaluation_private_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case_records = root / "case-records.jsonl"
            output = root / "public/gpt56-baseline-score.html"
            _write_jsonl(case_records, _records())
            with self.assertRaisesRegex(
                ValueError,
                "mini131_private_output_outside_evaluation_private",
            ):
                generate_report(case_records_path=case_records, output_path=output)
            self.assertFalse(output.exists())

    def test_private_output_cannot_escape_through_descendant_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            private_root = root / "evaluation/private"
            outside = root / "outside"
            private_root.mkdir(parents=True)
            outside.mkdir()
            (private_root / "escape").symlink_to(outside, target_is_directory=True)
            case_records = private_root / "case-records.jsonl"
            _write_jsonl(case_records, _records())
            with self.assertRaisesRegex(
                ValueError,
                "mini131_private_output_symlink_forbidden",
            ):
                generate_report(
                    case_records_path=case_records,
                    output_path=private_root / "escape/report.html",
                )
            self.assertFalse((outside / "report.html").exists())

    def test_required_judgment_state_fields_fail_closed(self) -> None:
        for field, error in (
            ("critical_flags", "mini131_judgment_fields_invalid"),
            ("matched_key_point_ids", "mini131_judgment_fields_invalid"),
            ("follow_up_success", "mini131_judgment_fields_invalid"),
            ("safe_abstention", "mini131_judgment_fields_invalid"),
        ):
            records = _records()
            del records[0]["judgment"][field]  # type: ignore[index]
            with self.assertRaisesRegex(ValueError, error):
                validate_records(records)


if __name__ == "__main__":
    unittest.main()
