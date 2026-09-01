from __future__ import annotations

import copy
import json
import stat
import tempfile
import unittest
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from midprojectrag.ingest.common import canonical_json, read_jsonl, sha256_file, sha256_text
from midprojectrag.local_mini131_baseline import SourceCase
from midprojectrag.local_mini131_semantic import (
    REVIEW_MAP_SCHEMA_VERSION,
    SemanticLedger,
    SemanticPaths,
    _fresh_review_projection,
    _merge_cli_result,
    _public_semantic_receipt_path,
    _validate_decision,
    merge_semantic_score,
    select_adjudication_inputs,
    select_secondary_inputs,
    validate_decisions,
)
from midprojectrag.eval_contracts.mini131.judge import (
    BLIND_ADJUDICATION_INPUT_SCHEMA_VERSION,
    BLIND_DECISION_SCHEMA_VERSION,
    BLIND_JUDGE_INPUT_SCHEMA_VERSION,
    blind_id as _blind_id,
)


def _write_private(path: Path, value: object, *, jsonl: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if jsonl:
        rows = value if isinstance(value, list) else [value]
        path.write_text(
            "".join(canonical_json(row) + "\n" for row in rows),
            encoding="utf-8",
        )
    else:
        path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)


def _nested_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, Mapping):
        for key, nested in value.items():
            keys.add(str(key))
            keys.update(_nested_keys(nested))
    elif isinstance(value, list):
        for nested in value:
            keys.update(_nested_keys(nested))
    return keys


def _changed_decision(
    decision: Mapping[str, object],
    *,
    role: str,
    judge_decision: str,
    reviewed_at: str,
    scores: Mapping[str, object] | None = None,
) -> dict[str, object]:
    changed = copy.deepcopy(dict(decision))
    changed["judge_role"] = role
    changed["judge_decision"] = judge_decision
    changed["reviewed_at"] = reviewed_at
    if scores is not None:
        changed["scores"] = copy.deepcopy(dict(scores))
    return changed


def _needs_review_scores() -> dict[str, object]:
    return {
        "correctness": 0.5,
        "faithfulness": 1,
        "completeness": 1,
        "factual_claim_coverage": 1,
        "citation_validity": 1,
        "abstention_quality": None,
    }


class LocalMini131SemanticTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[SemanticLedger, dict[str, object]]:
        case = SourceCase(
            case_id="EDA-001",
            lane="core40",
            source={
                "question": "질문",
                "gold": {
                    "decision": "answer",
                    "key_points": [{"point_id": "p1", "text": "정답"}],
                },
            },
            source_sha256="a" * 64,
            request_template=None,
        )
        suite = SimpleNamespace(
            cases_by_id={case.case_id: case},
            config_sha256="b" * 64,
            eval_set_sha256="c" * 64,
        )
        source_input = {
            "question_kind": "rag_qa",
            "question": "질문",
            "expected": copy.deepcopy(case.source["gold"]),
            "candidate": {
                "status": "answered",
                "answer": "정답",
                "chat": [
                    {"role": "user", "content": "질문"},
                    {"role": "assistant", "content": "정답"},
                ],
            },
            "retrieval": {
                "retrieved_docs": [],
                "cited_docs": [{"evidence_id": "calculation:EDA-001"}],
                "evidence": [{"evidence_id": "calculation:EDA-001"}],
            },
        }
        source_hash = sha256_text(canonical_json(source_input))
        review_input, binding = _fresh_review_projection(
            source_input,
            case_id=case.case_id,
            candidate_sha256="d" * 64,
            source_judge_input_sha256=source_hash,
            suite_config_sha256=suite.config_sha256,
            rubric_sha256="e" * 64,
            review_config_sha256="f" * 64,
        )
        review_hash = sha256_text(canonical_json(review_input))
        blind_id = _blind_id(review_hash)
        review_row = {
            "schema_version": BLIND_JUDGE_INPUT_SCHEMA_VERSION,
            "blind_id": blind_id,
            "judge_input_sha256": review_hash,
            "judge_input": review_input,
        }
        map_row = {
            "schema_version": REVIEW_MAP_SCHEMA_VERSION,
            "blind_id": blind_id,
            "case_id": case.case_id,
            "lane": case.lane,
            "candidate_sha256": "d" * 64,
            "source_opaque_id": f"judge-{source_hash[:24]}",
            "source_judge_input_sha256": source_hash,
            "judge_input_sha256": review_hash,
            "fresh_review_binding_sha256": binding,
        }
        candidate = {
            "case_id": case.case_id,
            "response": {"status": "answered", "answer": "정답"},
        }
        review_root = root / "review"
        paths = SemanticPaths(
            source_inputs=root / "source.jsonl",
            source_map=root / "source-map.jsonl",
            candidates=root / "candidates.jsonl",
            deterministic_score=root / "deterministic.json",
            rubric=root / "rubric.md",
            judge_config=root / "judge-config.json",
            adapter_config=root / "adapter-config.json",
            review_root=review_root,
            review_inputs=review_root / "primary-inputs.jsonl",
            review_map=review_root / "review-map.jsonl",
            semantic_score=root / "semantic-score.json",
        )
        _write_private(paths.deterministic_score, {"deterministic": True})
        _write_private(paths.review_inputs, [review_row], jsonl=True)
        _write_private(paths.review_map, [map_row], jsonl=True)
        ledger = SemanticLedger(
            suite=suite,
            paths=paths,
            review_config_sha256="f" * 64,
            inherited_judge_config_sha256="9" * 64,
            rubric_sha256="e" * 64,
            run_id="local-run",
            review_rows=(review_row,),
            review_by_id={blind_id: review_row},
            map_by_id={blind_id: map_row},
            candidate_by_case={case.case_id: candidate},
            deterministic_score_sha256=sha256_file(paths.deterministic_score),
        )
        decision = {
            "schema_version": BLIND_DECISION_SCHEMA_VERSION,
            "blind_id": blind_id,
            "judge_input_sha256": review_hash,
            "review_config_sha256": "f" * 64,
            "rubric_version": "gpt56-semantic-v2",
            "reviewer_type": "llm",
            "model": "gpt-5.6-sol",
            "judge_role": "primary",
            "scores": {
                "correctness": 1,
                "faithfulness": 1,
                "completeness": 1,
                "factual_claim_coverage": 1,
                "citation_validity": 1,
                "abstention_quality": None,
            },
            "matched_key_point_ids": ["p1"],
            "follow_up_success": None,
            "safe_abstention": None,
            "critical_flags": [],
            "confidence": 0.9,
            "judge_decision": "accepted",
            "rationale": "근거와 답변이 일치한다.",
            "reviewed_at": "2026-08-31T12:00:00+09:00",
        }
        return ledger, decision

    def test_fresh_projection_redacts_case_locator_and_changes_old_binding(self) -> None:
        source = {
            "question_kind": "corpus_analytics_qa",
            "question": "통계를 설명해줘",
            "expected": {"gold": {"decision": "answer"}},
            "candidate": {"status": "answered", "answer": "답"},
            "retrieval": {"evidence": [{"evidence_id": "calculation:EDA-001"}]},
        }
        source_hash = sha256_text(canonical_json(source))
        first, first_binding = _fresh_review_projection(
            source,
            case_id="EDA-001",
            candidate_sha256="1" * 64,
            source_judge_input_sha256=source_hash,
            suite_config_sha256="2" * 64,
            rubric_sha256="3" * 64,
            review_config_sha256="4" * 64,
        )
        second, second_binding = _fresh_review_projection(
            source,
            case_id="EDA-001",
            candidate_sha256="5" * 64,
            source_judge_input_sha256=source_hash,
            suite_config_sha256="2" * 64,
            rubric_sha256="3" * 64,
            review_config_sha256="4" * 64,
        )

        self.assertNotIn("EDA-001", canonical_json(first))
        self.assertIn("calculation:opaque-case", canonical_json(first))
        self.assertNotEqual(first_binding, second_binding)
        self.assertNotEqual(
            sha256_text(canonical_json(first)),
            sha256_text(canonical_json(second)),
        )
        self.assertNotEqual(source_hash, sha256_text(canonical_json(first)))

    def test_decision_is_bound_to_new_review_hash_and_rejects_old_judgment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger, decision = self._fixture(Path(directory))
            raw, judgment = _validate_decision(ledger, decision)
            self.assertEqual(raw, decision)
            self.assertEqual(judgment["case_id"], "EDA-001")
            self.assertEqual(judgment["run_record_sha256"], "d" * 64)
            self.assertEqual(judgment["judge_decision"], "accepted")

            old = copy.deepcopy(decision)
            old_hash = ledger.map_by_id[decision["blind_id"]][
                "source_judge_input_sha256"
            ]
            old["blind_id"] = _blind_id(old_hash)
            old["judge_input_sha256"] = old_hash
            with self.assertRaisesRegex(
                ValueError, "local_mini131_semantic_decision_binding_mismatch"
            ):
                _validate_decision(ledger, old)

    def test_merge_writes_separate_private_score_and_preserves_deterministic_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger, decision = self._fixture(Path(directory))
            decision_path = ledger.paths.review_root / "primary.jsonl"
            _write_private(decision_path, [decision], jsonl=True)
            before = ledger.paths.deterministic_score.read_bytes()

            with patch("midprojectrag.local_mini131_semantic.RAG_COUNT", 1):
                report = merge_semantic_score(ledger, [decision_path])

            self.assertEqual(report["semantic_judgment"], "complete")
            self.assertEqual(report["counts"]["accepted"], 1)
            self.assertEqual(report["metrics"]["mean_semantic_score"], 100.0)
            self.assertEqual(ledger.paths.deterministic_score.read_bytes(), before)
            self.assertEqual(stat.S_IMODE(ledger.paths.semantic_score.stat().st_mode), 0o600)
            history = ledger.paths.review_root / "review-history.jsonl"
            self.assertEqual(stat.S_IMODE(history.stat().st_mode), 0o600)
            rows = read_jsonl(history)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["review_input"], ledger.review_rows[0])
            self.assertEqual(rows[0]["review_output"], decision)

    def test_merge_emits_aggregate_only_public_semantic_receipt_mode_0644(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger, decision = self._fixture(Path(directory))
            decision_path = ledger.paths.review_root / "primary.jsonl"
            _write_private(decision_path, [decision], jsonl=True)

            with patch("midprojectrag.local_mini131_semantic.RAG_COUNT", 1):
                report = merge_semantic_score(ledger, [decision_path])

            receipt_path = _public_semantic_receipt_path(ledger.paths)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(stat.S_IMODE(receipt_path.stat().st_mode), 0o644)
            self.assertEqual(
                set(receipt),
                {
                    "schema_version",
                    "suite_id",
                    "official",
                    "evaluation_tier",
                    "gold_review_status",
                    "semantic_judgment",
                    "counts",
                    "metrics",
                    "judge",
                    "hashes",
                    "privacy",
                },
            )
            self.assertEqual(
                receipt["schema_version"],
                "local-mini131-semantic-receipt.v1",
            )
            self.assertFalse(receipt["official"])
            self.assertEqual(receipt["gold_review_status"], "draft")
            self.assertEqual(receipt["counts"], report["counts"])
            self.assertEqual(receipt["metrics"], report["metrics"])
            self.assertEqual(receipt["judge"]["model"], "gpt-5.6-sol")
            self.assertEqual(receipt["judge"]["reasoning_effort"], "high")
            self.assertEqual(
                receipt["hashes"]["private_semantic_score_sha256"],
                sha256_file(ledger.paths.semantic_score),
            )
            self.assertTrue(receipt["privacy"])
            self.assertTrue(all(value is False for value in receipt["privacy"].values()))
            self.assertFalse(
                _nested_keys(receipt)
                & {
                    "cases",
                    "case_id",
                    "question",
                    "answer",
                    "source",
                    "rationale",
                    "blind_id",
                    "run_id",
                }
            )
            public_text = canonical_json(receipt)
            for private_value in (
                "EDA-001",
                str(decision["blind_id"]),
                "private-run",
                "질문",
                "정답",
                "근거와 답변이 일치한다.",
            ):
                self.assertNotIn(private_value, public_text)

    def test_merge_with_custom_private_output_does_not_replace_public_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger, decision = self._fixture(Path(directory))
            decision_path = ledger.paths.review_root / "primary.jsonl"
            custom_output = ledger.paths.review_root / "experimental-score.json"
            _write_private(decision_path, [decision], jsonl=True)

            with patch("midprojectrag.local_mini131_semantic.RAG_COUNT", 1):
                merge_semantic_score(
                    ledger,
                    [decision_path],
                    output_path=custom_output,
                )

            self.assertTrue(custom_output.is_file())
            self.assertEqual(stat.S_IMODE(custom_output.stat().st_mode), 0o600)
            self.assertFalse(ledger.paths.semantic_score.exists())
            self.assertFalse(_public_semantic_receipt_path(ledger.paths).exists())

    def test_merge_cli_result_exposes_only_aggregate_metrics_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "semantic-score.json"
            _write_private(output, {"private": True})
            result = _merge_cli_result(
                {
                    "semantic_judgment": "complete",
                    "counts": {"rag_total": 129, "accepted": 1, "rejected": 128},
                    "metrics": {"mean_semantic_score": 50.0},
                    "cases": [{"case_id": "private-case"}],
                    "run_id": "private-run",
                },
                output,
            )
            self.assertEqual(
                set(result),
                {
                    "passed",
                    "semantic_judgment",
                    "counts",
                    "metrics",
                    "semantic_score_sha256",
                },
            )
            self.assertNotIn("private-case", canonical_json(result))
            self.assertNotIn("private-run", canonical_json(result))

    def test_select_secondary_inputs_selects_only_triggered_primary_and_seals_output(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger, decision = self._fixture(Path(directory))
            primary = _changed_decision(
                decision,
                role="primary",
                judge_decision="needs_review",
                reviewed_at="2026-08-31T12:00:00+09:00",
                scores=_needs_review_scores(),
            )
            primary_path = ledger.paths.review_root / "primary.jsonl"
            output_path = ledger.paths.review_root / "secondary-inputs.jsonl"
            _write_private(primary_path, [primary], jsonl=True)

            with patch("midprojectrag.local_mini131_semantic.RAG_COUNT", 1):
                selected = select_secondary_inputs(
                    ledger,
                    [primary_path],
                    output_path=output_path,
                )

            self.assertEqual(selected, [ledger.review_rows[0]])
            self.assertEqual(read_jsonl(output_path), selected)
            self.assertEqual(stat.S_IMODE(output_path.stat().st_mode), 0o600)
            self.assertFalse(
                _nested_keys(selected[0]) & {"case_id", "lane", "lineage"}
            )

    def test_select_secondary_inputs_rejects_incomplete_primary_ledger_without_output(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger, decision = self._fixture(Path(directory))
            primary_path = ledger.paths.review_root / "primary-incomplete.jsonl"
            output_path = ledger.paths.review_root / "must-not-write.jsonl"
            _write_private(primary_path, [decision], jsonl=True)

            with patch("midprojectrag.local_mini131_semantic.RAG_COUNT", 2):
                with self.assertRaisesRegex(
                    ValueError,
                    "local_mini131_semantic_primary_ledger_incomplete",
                ):
                    select_secondary_inputs(
                        ledger,
                        [primary_path],
                        output_path=output_path,
                    )

            self.assertFalse(output_path.exists())

    def test_select_adjudication_inputs_builds_bound_nonidentifying_packet(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger, decision = self._fixture(Path(directory))
            primary = _changed_decision(
                decision,
                role="primary",
                judge_decision="needs_review",
                reviewed_at="2026-08-31T12:00:00+09:00",
                scores=_needs_review_scores(),
            )
            secondary = _changed_decision(
                decision,
                role="secondary",
                judge_decision="accepted",
                reviewed_at="2026-08-31T12:01:00+09:00",
            )
            primary_path = ledger.paths.review_root / "primary.jsonl"
            secondary_path = ledger.paths.review_root / "secondary.jsonl"
            output_path = ledger.paths.review_root / "adjudication-inputs.jsonl"
            _write_private(primary_path, [primary], jsonl=True)
            _write_private(secondary_path, [secondary], jsonl=True)

            selected = select_adjudication_inputs(
                ledger,
                [secondary_path, primary_path],
                output_path=output_path,
            )

            self.assertEqual(len(selected), 1)
            packet = selected[0]
            self.assertEqual(
                set(packet),
                {
                    "schema_version",
                    "blind_id",
                    "judge_input_sha256",
                    "review_config_sha256",
                    "blind_input",
                    "primary_decision",
                    "secondary_decision",
                    "input_sha256",
                },
            )
            self.assertEqual(
                packet["schema_version"],
                BLIND_ADJUDICATION_INPUT_SCHEMA_VERSION,
            )
            self.assertEqual(packet["blind_input"], ledger.review_rows[0])
            self.assertEqual(packet["primary_decision"], primary)
            self.assertEqual(packet["secondary_decision"], secondary)
            payload = {
                key: value for key, value in packet.items() if key != "input_sha256"
            }
            self.assertEqual(
                packet["input_sha256"],
                sha256_text(canonical_json(payload)),
            )
            self.assertFalse(
                _nested_keys(packet) & {"case_id", "lane", "lineage"}
            )
            self.assertEqual(read_jsonl(output_path), selected)
            self.assertEqual(stat.S_IMODE(output_path.stat().st_mode), 0o600)

    def test_select_adjudication_inputs_rejects_missing_secondary_without_output(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger, decision = self._fixture(Path(directory))
            primary = _changed_decision(
                decision,
                role="primary",
                judge_decision="needs_review",
                reviewed_at="2026-08-31T12:00:00+09:00",
                scores=_needs_review_scores(),
            )
            primary_path = ledger.paths.review_root / "primary.jsonl"
            output_path = ledger.paths.review_root / "must-not-write.jsonl"
            _write_private(primary_path, [primary], jsonl=True)

            with self.assertRaisesRegex(
                ValueError,
                "local_mini131_semantic_secondary_ledger_mismatch",
            ):
                select_adjudication_inputs(
                    ledger,
                    [primary_path],
                    output_path=output_path,
                )

            self.assertFalse(output_path.exists())

    def test_merge_full_review_workflow_orders_roles_and_uses_adjudicator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger, decision = self._fixture(Path(directory))
            primary = _changed_decision(
                decision,
                role="primary",
                judge_decision="needs_review",
                reviewed_at="2026-08-31T12:00:00+09:00",
                scores=_needs_review_scores(),
            )
            secondary = _changed_decision(
                decision,
                role="secondary",
                judge_decision="accepted",
                reviewed_at="2026-08-31T12:01:00+09:00",
            )
            adjudicator = _changed_decision(
                decision,
                role="adjudicator",
                judge_decision="accepted",
                reviewed_at="2026-08-31T12:02:00+09:00",
            )
            paths: list[Path] = []
            for name, row in (
                ("adjudicator", adjudicator),
                ("primary", primary),
                ("secondary", secondary),
            ):
                path = ledger.paths.review_root / f"{name}.jsonl"
                _write_private(path, [row], jsonl=True)
                paths.append(path)

            raw, _judgments = validate_decisions(ledger, paths)
            self.assertEqual(
                [row["judge_role"] for row in raw],
                ["primary", "secondary", "adjudicator"],
            )
            with patch("midprojectrag.local_mini131_semantic.RAG_COUNT", 1):
                report = merge_semantic_score(ledger, paths)

            self.assertEqual(
                report["counts"]["judge_roles"],
                {
                    "adjudicator": 1,
                    "primary": 1,
                    "secondary": 1,
                },
            )
            self.assertEqual(report["cases"][0]["final_judge_role"], "adjudicator")
            self.assertTrue(report["cases"][0]["workflow"]["secondary_required"])
            self.assertTrue(report["cases"][0]["workflow"]["adjudicator_required"])
            history = read_jsonl(ledger.paths.review_root / "review-history.jsonl")
            self.assertEqual(
                [row["judge_role"] for row in history],
                ["primary", "secondary", "adjudicator"],
            )
            self.assertEqual(
                history[-1]["input_schema_version"],
                BLIND_ADJUDICATION_INPUT_SCHEMA_VERSION,
            )

    def test_merge_rejects_out_of_order_review_timestamps_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger, decision = self._fixture(Path(directory))
            primary = _changed_decision(
                decision,
                role="primary",
                judge_decision="needs_review",
                reviewed_at="2026-08-31T12:00:00+09:00",
                scores=_needs_review_scores(),
            )
            secondary = _changed_decision(
                decision,
                role="secondary",
                judge_decision="accepted",
                reviewed_at="2026-08-31T12:03:00+09:00",
            )
            adjudicator = _changed_decision(
                decision,
                role="adjudicator",
                judge_decision="accepted",
                reviewed_at="2026-08-31T12:02:00+09:00",
            )
            decision_path = ledger.paths.review_root / "out-of-order.jsonl"
            _write_private(
                decision_path,
                [adjudicator, secondary, primary],
                jsonl=True,
            )
            deterministic_before = ledger.paths.deterministic_score.read_bytes()

            with patch("midprojectrag.local_mini131_semantic.RAG_COUNT", 1):
                with self.assertRaisesRegex(
                    ValueError,
                    "local_mini131_semantic_review_order_invalid",
                ):
                    merge_semantic_score(ledger, [decision_path])

            self.assertEqual(
                ledger.paths.deterministic_score.read_bytes(),
                deterministic_before,
            )
            self.assertFalse(ledger.paths.semantic_score.exists())
            self.assertFalse(
                (ledger.paths.review_root / "review-history.jsonl").exists()
            )
            self.assertFalse(_public_semantic_receipt_path(ledger.paths).exists())

    def test_merge_rejects_incomplete_candidate_ledger_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger, decision = self._fixture(Path(directory))
            incomplete_ledger = replace(
                ledger,
                candidate_by_case={
                    **ledger.candidate_by_case,
                    "EDA-002": {
                        "case_id": "EDA-002",
                        "response": {"status": "answered", "answer": "답"},
                    },
                },
            )
            decision_path = ledger.paths.review_root / "primary-incomplete.jsonl"
            _write_private(decision_path, [decision], jsonl=True)
            deterministic_before = ledger.paths.deterministic_score.read_bytes()

            with self.assertRaisesRegex(
                ValueError,
                "local_mini131_semantic_judgment_ledger_incomplete",
            ):
                merge_semantic_score(incomplete_ledger, [decision_path])

            self.assertEqual(
                ledger.paths.deterministic_score.read_bytes(),
                deterministic_before,
            )
            self.assertFalse(ledger.paths.semantic_score.exists())
            self.assertFalse(
                (ledger.paths.review_root / "review-history.jsonl").exists()
            )


if __name__ == "__main__":
    unittest.main()
