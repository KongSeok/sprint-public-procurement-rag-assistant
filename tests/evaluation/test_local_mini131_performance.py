from __future__ import annotations

import copy
import json
import re
import stat
import tempfile
import unittest
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from statistics import fmean
from types import SimpleNamespace

from midprojectrag.ingest.common import (
    canonical_json,
    read_jsonl,
    sha256_file,
    sha256_text,
)
from midprojectrag.local_mini131_baseline import DEFAULT_CONFIG, verify_suite
from midprojectrag.local_mini131_performance import (
    RECORD_SCHEMA_VERSION,
    REPORT_SCHEMA_VERSION,
    SUMMARY_SCHEMA_VERSION,
    PerformancePaths,
    _load_parser_results,
    build_performance_evaluation,
    content_free_receipt,
    default_paths,
    render_html,
    resolve_final_judgments,
    validate_performance_evaluation,
    write_performance_outputs,
)
from midprojectrag.local_mini131_semantic import (
    default_paths as semantic_default_paths,
    load_ledger,
)


PRIVATE_QUESTION = "<script>privateQuestion()</script>"
PRIVATE_EXPECTED = "private expected answer sentinel"
PRIVATE_CANDIDATE = "private candidate answer sentinel"
PRIVATE_EVIDENCE = "private evidence sentinel"
PRIVATE_RATIONALE = "private rationale sentinel"
COMPONENTS = {
    "correctness",
    "faithfulness",
    "completeness",
    "factual_claim_coverage",
    "citation_validity",
    "abstention_quality",
}


def _write_private(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    path.chmod(0o600)


def _write_private_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600)
    path.write_text(
        "".join(canonical_json(row) + "\n" for row in rows),
        encoding="utf-8",
    )
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


def _plan() -> list[tuple[str, str, str]]:
    difficulty = ["easy"] * 41 + ["medium"] * 48 + ["hard"] * 40
    lane_and_purpose = (
        [("core40", "single_doc")] * 10
        + [("core40", "multi_doc_compare")] * 10
        + [("core40", "follow_up")] * 10
        + [("core40", "abstention")] * 10
        + [("supplemental_answer_legacy", "clause_fact_regression")] * 39
        + [("supplemental_answer_rerun", "clause_fact_regression")] * 5
        + [("supplemental_answer_rerun", "gold_source_alignment")] * 12
        + [("supplemental_set_rerun", "conditional_all_list")] * 13
        + [("visual", "visual_table_figure")] * 10
        + [("corpus_analytics", "corpus_analytics")] * 10
    )
    return [
        (lane, purpose, level)
        for (lane, purpose), level in zip(lane_and_purpose, difficulty, strict=True)
    ]


def _component_summary(records: Sequence[Mapping[str, object]]) -> dict[str, object]:
    return {
        name: {
            "eligible": 0 if name == "abstention_quality" else len(records),
            "mean": None if name == "abstention_quality" else 1.0,
        }
        for name in sorted(COMPONENTS)
    }


def _group_summary(records: Sequence[Mapping[str, object]]) -> dict[str, object]:
    rag = [row for row in records if row["asset_type"] == "rag"]
    accepted = sum(
        row["semantic_evaluation"]["verdict"] == "accepted"  # type: ignore[index]
        for row in rag
    )
    scores = [
        float(row["semantic_evaluation"]["score"])  # type: ignore[index]
        for row in rag
    ]
    return {
        "count": len(records),
        "rag_count": len(rag),
        "parser_count": len(records) - len(rag),
        "status": {
            name: sum(row["candidate"]["status"] == name for row in rag)  # type: ignore[index]
            for name in ("answered", "abstained", "error")
        },
        "accepted": accepted,
        "rejected": len(rag) - accepted,
        "acceptance_rate": round(accepted / len(rag), 6) if rag else None,
        "runtime_error_rate": 0.0 if rag else None,
        "mean_semantic_score": round(fmean(scores), 6) if scores else None,
        "components": _component_summary(rag),
        "behavior_checks": {
            "follow_up_success": {"eligible": 0, "passed": 0, "rate": None},
            "safe_abstention": {"eligible": 0, "passed": 0, "rate": None},
        },
        "deterministic_metrics": {
            "citation_valid": {"eligible": len(rag), "mean": 1.0}
        },
    }


def _partition(
    records: Sequence[Mapping[str, object]], key: str
) -> dict[str, dict[str, object]]:
    values: dict[str, list[Mapping[str, object]]] = {}
    for record in records:
        values.setdefault(str(record[key]), []).append(record)
    return {name: _group_summary(rows) for name, rows in sorted(values.items())}


def _synthetic_report() -> dict[str, object]:
    records: list[dict[str, object]] = []
    for index, (lane, purpose, difficulty) in enumerate(_plan(), start=1):
        accepted = index % 5 != 0
        question = PRIVATE_QUESTION if index == 1 else f"question {index}"
        expected = PRIVATE_EXPECTED if index == 1 else f"expected {index}"
        answer = PRIVATE_CANDIDATE if index == 1 else f"answer {index}"
        evidence = PRIVATE_EVIDENCE if index == 1 else f"evidence {index}"
        rationale = PRIVATE_RATIONALE if index == 1 else f"rationale {index}"
        records.append(
            {
                "schema_version": RECORD_SCHEMA_VERSION,
                "case_id": f"SYN-{index:03d}",
                "asset_type": "rag",
                "lane": lane,
                "purpose": purpose,
                "difficulty": difficulty,
                "official": False,
                "gold_review_status": "draft",
                "evaluation_status": {
                    "record_complete": True,
                    "quality_pass": accepted,
                    "gold_approved": False,
                    "official_eligible": False,
                },
                "question": question,
                "expected": {"key_points": [{"text": expected}]},
                "candidate": {
                    "status": "answered",
                    "answer": answer,
                    "chat": [],
                    "citations": [],
                    "selected_doc_ids": [],
                    "abstention_reason": None,
                    "error_code": None,
                },
                "retrieval": {
                    "retrieved_docs": [],
                    "cited_docs": [],
                    "evidence": [{"text": evidence}],
                },
                "deterministic_metrics": {
                    "case_id": f"SYN-{index:03d}",
                    "lane": lane,
                    "status": "answered",
                    "citation_valid": True,
                },
                "semantic_evaluation": {
                    "score": 100.0 if accepted else 50.0,
                    "verdict": "accepted" if accepted else "rejected",
                    "final_judge_role": "primary",
                    "component_scores": {
                        name: None if name == "abstention_quality" else 1.0
                        for name in COMPONENTS
                    },
                    "rationale": rationale,
                    "judgment_history": [],
                },
                "source_transcript": {},
                "provenance": {"source_case_sha256": "a" * 64},
            }
        )
    for index in range(1, 3):
        records.append(
            {
                "schema_version": RECORD_SCHEMA_VERSION,
                "case_id": f"PARSER-{index:03d}",
                "asset_type": "parser",
                "lane": "parser_regression",
                "purpose": "parser_regression",
                "difficulty": "not_applicable",
                "official": False,
                "gold_review_status": "not_applicable",
                "evaluation_status": {
                    "record_complete": True,
                    "quality_pass": True,
                    "gold_approved": False,
                    "official_eligible": False,
                },
                "question": f"parser check {index}",
                "expected": {"invariant": "preserved"},
                "candidate": {"status": "passed", "answer": "PASS"},
                "retrieval": {"retrieved_docs": [], "cited_docs": [], "evidence": []},
                "deterministic_metrics": {"passed": True, "checks": {}},
                "semantic_evaluation": None,
                "source_transcript": {},
                "provenance": {"parser_rerun_sha256": "b" * 64},
            }
        )

    rag = [row for row in records if row["asset_type"] == "rag"]
    difficulty_counts = dict(sorted(Counter(row["difficulty"] for row in rag).items()))
    summary = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "suite_id": "gcp-local-kure-qwen3-8b-awq-mini131-v1",
        "official": False,
        "evaluation_tier": "provisional_non_official",
        "gold_review_status": "draft",
        "evaluation_status": {
            "record_complete": True,
            "quality_pass": False,
            "gold_approved": False,
            "official_eligible": False,
        },
        "overall": _group_summary(records),
        "counts": {
            "total_assets": 131,
            "rag": 129,
            "parser": 2,
            "parser_passed": 2,
            "difficulty": difficulty_counts,
        },
        "by_difficulty": _partition(rag, "difficulty"),
        "by_purpose": _partition(records, "purpose"),
        "by_lane": _partition(records, "lane"),
        "failure_case_ids": {"runtime_error": [], "semantic_rejected": []},
        "frozen_aggregate_metrics": {},
        "limitations": {
            "human_gold_approved": False,
            "held_out_executed": False,
            "live_gcp_executed": False,
            "candidate_runtime": "mac_ollama_numpy",
            "judge_is_gold": False,
            "unreported_frozen_metrics_remain": True,
        },
    }
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "suite_id": "gcp-local-kure-qwen3-8b-awq-mini131-v1",
        "official": False,
        "records": records,
        "summary": summary,
        "source_hashes": {
            "candidates_sha256": "1" * 64,
            "deterministic_score_sha256": "2" * 64,
            "semantic_score_sha256": "3" * 64,
            "review_history_sha256": "4" * 64,
            "parser_rerun_sha256": "5" * 64,
        },
    }
    validate_performance_evaluation(report)
    return report


class LocalMini131PerformanceUnitTests(unittest.TestCase):
    def test_schema_and_default_paths_are_frozen(self) -> None:
        self.assertEqual(
            RECORD_SCHEMA_VERSION,
            "local-mini131-golden-evaluation-record.v1",
        )
        self.assertEqual(
            SUMMARY_SCHEMA_VERSION,
            "local-mini131-golden-performance-summary.v1",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            suite = SimpleNamespace(
                private_judge_input_path=(
                    root / "evaluation/private/local-mini131/suite/blind-inputs.jsonl"
                ),
                public_receipt_path=(
                    root / "evaluation/baselines/suite/deterministic-receipt.json"
                ),
            )
            paths = default_paths(suite)
        expected_root = root / "evaluation/private/local-mini131/suite/performance-v1"
        self.assertEqual(paths.root, expected_root)
        self.assertEqual(paths.records.name, "golden-evaluation-records.jsonl")
        self.assertEqual(paths.summary.name, "golden-performance-summary.json")
        self.assertEqual(paths.html.name, "golden-performance-report.html")
        self.assertEqual(
            paths.receipt.name,
            "mac-local-equivalent-performance-receipt.json",
        )

    def test_incomplete_131_ledger_fails_closed(self) -> None:
        report = _synthetic_report()
        report["records"] = report["records"][:-1]
        with self.assertRaisesRegex(
            ValueError,
            "local_mini131_performance_record_count_mismatch",
        ):
            validate_performance_evaluation(report)

    def test_private_modes_content_free_receipt_and_aggregate_reconciliation(self) -> None:
        report = _synthetic_report()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private_root = root / "evaluation/private/local-mini131/suite/performance-v1"
            paths = PerformancePaths(
                root=private_root,
                records=private_root / "golden-evaluation-records.jsonl",
                summary=private_root / "golden-performance-summary.json",
                html=private_root / "golden-performance-report.html",
                receipt=root / "evaluation/baselines/suite/performance-receipt.json",
            )
            receipt = write_performance_outputs(report, paths)

            for output in (paths.records, paths.summary, paths.html):
                with self.subTest(output=output.name):
                    self.assertTrue(output.is_file())
                    self.assertFalse(output.is_symlink())
                    self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(paths.receipt.stat().st_mode), 0o644)
            self.assertEqual(
                json.loads(paths.receipt.read_text(encoding="utf-8")),
                receipt,
            )
            self.assertEqual(
                receipt["artifact_hashes"]["private_summary_sha256"],
                sha256_file(paths.summary),
            )

        expected_mean = round(
            fmean(
                float(row["semantic_evaluation"]["score"])
                for row in report["records"]
                if row["asset_type"] == "rag"
            ),
            6,
        )
        self.assertEqual(report["summary"]["overall"]["rag_count"], 129)
        self.assertEqual(
            report["summary"]["overall"]["mean_semantic_score"],
            expected_mean,
        )
        self.assertEqual(receipt["metrics"]["overall"], report["summary"]["overall"])
        self.assertEqual(receipt["counts"], report["summary"]["counts"])
        self.assertFalse(
            _nested_keys(receipt)
            & {
                "case_id",
                "case_ids",
                "question",
                "questions",
                "expected",
                "answer",
                "answers",
                "evidence",
                "rationale",
                "blind_id",
                "private_path",
            }
        )
        serialized = canonical_json(receipt)
        for value in (
            PRIVATE_QUESTION,
            PRIVATE_EXPECTED,
            PRIVATE_CANDIDATE,
            PRIVATE_EVIDENCE,
            PRIVATE_RATIONALE,
        ):
            self.assertNotIn(value, serialized)
        for flag in (
            "contains_case_ids",
            "contains_questions",
            "contains_expected_answers",
            "contains_candidate_answers",
            "contains_evidence",
            "contains_judge_rationales",
            "contains_private_paths",
        ):
            self.assertIs(receipt["privacy"][flag], False)
        for groups in (
            report["summary"]["by_difficulty"],
            report["summary"]["by_purpose"],
            report["summary"]["by_lane"],
        ):
            self.assertTrue(all("rag_count" in group for group in groups.values()))
        self.assertTrue(
            all(
                "eligible" in component
                for component in report["summary"]["overall"]["components"].values()
            )
        )

    def test_private_output_boundary_rejects_outside_and_symlink_paths(self) -> None:
        report = _synthetic_report()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private_root = root / "evaluation/private/local-mini131/suite/performance-v1"
            outside = root / "outside"
            outside.mkdir()
            private_root.mkdir(parents=True)
            (private_root / "escape").symlink_to(outside, target_is_directory=True)
            unsafe_records = (
                outside / "records.jsonl",
                private_root / "escape/records.jsonl",
            )
            for records in unsafe_records:
                paths = PerformancePaths(
                    root=private_root,
                    records=records,
                    summary=private_root / "summary.json",
                    html=private_root / "report.html",
                    receipt=root / "evaluation/baselines/suite/receipt.json",
                )
                with self.subTest(records=str(records.relative_to(root))):
                    with self.assertRaisesRegex(
                        ValueError,
                        r"local_mini131_performance_output_(?:not_private|symlink_forbidden)",
                    ):
                        write_performance_outputs(report, paths)
            self.assertFalse((outside / "records.jsonl").exists())

    def test_public_receipt_allowlist_rejects_or_drops_injected_private_content(self) -> None:
        report = _synthetic_report()
        report["summary"]["overall"]["question"] = PRIVATE_QUESTION
        report["summary"]["limitations"]["rationale"] = PRIVATE_RATIONALE
        receipt = content_free_receipt(report, {"records_sha256": "a" * 64})
        serialized = canonical_json(receipt)
        self.assertNotIn(PRIVATE_QUESTION, serialized)
        self.assertNotIn(PRIVATE_RATIONALE, serialized)
        self.assertNotIn("question", _nested_keys(receipt))
        self.assertNotIn("rationale", _nested_keys(receipt))

        report["summary"]["overall"]["mean_semantic_score"] = PRIVATE_CANDIDATE
        with self.assertRaisesRegex(
            ValueError,
            "local_mini131_performance_public_metric_invalid",
        ):
            content_free_receipt(report, {"records_sha256": "a" * 64})

        report = _synthetic_report()
        report["summary"]["limitations"]["candidate_runtime"] = PRIVATE_EVIDENCE
        with self.assertRaisesRegex(
            ValueError,
            "local_mini131_performance_public_limitations_invalid",
        ):
            content_free_receipt(report, {"records_sha256": "a" * 64})

        with self.assertRaisesRegex(
            ValueError,
            "local_mini131_performance_public_hash_invalid",
        ):
            content_free_receipt(_synthetic_report(), {"question": PRIVATE_QUESTION})

    def test_html_escapes_content_and_has_131_static_filterable_cards(self) -> None:
        rendered = render_html(_synthetic_report())
        self.assertIn("&lt;script&gt;privateQuestion()&lt;/script&gt;", rendered)
        self.assertNotIn(PRIVATE_QUESTION, rendered)
        self.assertEqual(
            len(re.findall(r'class="[^"]*\bcase\b[^"]*"', rendered)),
            131,
        )
        for control_id in ("search", "difficulty", "lane", "purpose", "verdict"):
            self.assertIn(f'id="{control_id}"', rendered)
        for attribute in (
            "data-difficulty=",
            "data-purpose=",
            "data-lane=",
            "data-verdict=",
        ):
            self.assertIn(attribute, rendered)
        self.assertNotRegex(rendered, r'(?i)<script[^>]+src=["\']https?://')
        self.assertNotRegex(rendered, r'(?i)<link[^>]+href=["\']https?://')


class LocalMini131PerformancePrivateIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[2]
        config_path = cls.repo_root / DEFAULT_CONFIG
        if not config_path.is_file():
            raise unittest.SkipTest("canonical private Mini131 artifacts unavailable")
        try:
            cls.suite = verify_suite(
                repo_root=cls.repo_root,
                config_path=config_path,
            )
        except FileNotFoundError as error:
            raise unittest.SkipTest(
                "canonical private Mini131 artifacts unavailable"
            ) from error
        paths = semantic_default_paths(cls.suite)
        cls.decision_paths = [
            paths.review_root / "primary-decisions-1.jsonl",
            paths.review_root / "primary-decisions-2.jsonl",
            paths.review_root / "primary-decisions-3.jsonl",
            paths.review_root / "secondary-decisions.jsonl",
            paths.review_root / "adjudicator-decisions.jsonl",
        ]
        required = [
            paths.candidates,
            paths.deterministic_score,
            paths.semantic_score,
            paths.review_inputs,
            paths.review_map,
            paths.review_root / "review-history.jsonl",
            paths.candidates.with_name("parser-rerun.json"),
            *cls.decision_paths,
        ]
        if any(not path.is_file() for path in required):
            raise unittest.SkipTest("canonical private Mini131 artifacts unavailable")
        try:
            cls.ledger = load_ledger(cls.suite)
        except PermissionError as error:
            raise unittest.SkipTest(
                "canonical private Mini131 artifacts are unavailable in this sandbox"
            ) from error
        cls.report = build_performance_evaluation(cls.ledger, cls.decision_paths)

    def test_exact_131_join_difficulty_and_per_case_score_contract(self) -> None:
        records = self.report["records"]
        self.assertEqual(len(records), 131)
        self.assertEqual(len({row["case_id"] for row in records}), 131)
        self.assertEqual(
            Counter(row["asset_type"] for row in records),
            Counter({"rag": 129, "parser": 2}),
        )
        rag = [row for row in records if row["asset_type"] == "rag"]
        self.assertEqual(
            Counter(row["difficulty"] for row in rag),
            Counter({"easy": 41, "medium": 48, "hard": 40}),
        )
        for row in rag:
            with self.subTest(case_type="rag"):
                self.assertTrue(row["question"])
                self.assertIsNotNone(row["expected"])
                self.assertIn("answer", row["candidate"])
                self.assertIsInstance(row["retrieval"]["evidence"], list)
                self.assertIsInstance(row["deterministic_metrics"], Mapping)
                semantic = row["semantic_evaluation"]
                self.assertIsInstance(semantic["score"], (int, float))
                self.assertIn(semantic["verdict"], {"accepted", "rejected"})
                self.assertTrue(semantic["rationale"])
                self.assertEqual(set(semantic["component_scores"]), COMPONENTS)
                self.assertTrue(row["evaluation_status"]["record_complete"])
                self.assertFalse(row["evaluation_status"]["official_eligible"])
        self.assertTrue(
            all(
                row["semantic_evaluation"] is None
                and row["deterministic_metrics"]["passed"] is True
                for row in records
                if row["asset_type"] == "parser"
            )
        )

        summary = self.report["summary"]
        self.assertEqual(summary["counts"]["difficulty"], {
            "easy": 41,
            "medium": 48,
            "hard": 40,
        })
        self.assertEqual(
            {name: group["count"] for name, group in summary["by_purpose"].items()},
            {
                "abstention": 10,
                "clause_fact_regression": 44,
                "conditional_all_list": 13,
                "corpus_analytics": 10,
                "follow_up": 10,
                "gold_source_alignment": 12,
                "multi_doc_compare": 10,
                "parser_regression": 2,
                "single_doc": 10,
                "visual_table_figure": 10,
            },
        )
        self.assertTrue(summary["evaluation_status"]["record_complete"])
        self.assertFalse(summary["evaluation_status"]["quality_pass"])
        self.assertFalse(summary["official"])

    def test_final_adjudicator_and_aggregate_reconciliation(self) -> None:
        finals, histories, workflows = resolve_final_judgments(
            self.ledger,
            self.decision_paths,
        )
        adjudicated = [
            case_id
            for case_id, final in finals.items()
            if final["judge_role"] == "adjudicator"
        ]
        self.assertGreater(len(adjudicated), 0)
        for case_id in adjudicated:
            self.assertEqual(histories[case_id][-1]["judge_role"], "adjudicator")
            self.assertTrue(workflows[case_id]["adjudicator_required"])
            self.assertEqual(
                workflows[case_id]["final_judgment_id"],
                finals[case_id]["judgment_id"],
            )

        canonical = json.loads(
            self.ledger.paths.semantic_score.read_text(encoding="utf-8")
        )
        overall = self.report["summary"]["overall"]
        self.assertEqual(
            overall["mean_semantic_score"],
            canonical["metrics"]["mean_semantic_score"],
        )
        self.assertEqual(overall["accepted"], canonical["counts"]["accepted"])
        self.assertEqual(overall["rejected"], canonical["counts"]["rejected"])

    def test_deterministic_lane_mismatch_fails_closed(self) -> None:
        deterministic = json.loads(
            self.ledger.paths.deterministic_score.read_text(encoding="utf-8")
        )
        deterministic["per_case"][0]["lane"] = "tampered-lane"
        with tempfile.TemporaryDirectory() as directory:
            tampered = Path(directory) / "evaluation/private/tampered-score.json"
            _write_private(tampered, deterministic)
            paths = replace(self.ledger.paths, deterministic_score=tampered)
            ledger = replace(
                self.ledger,
                paths=paths,
                deterministic_score_sha256=sha256_file(tampered),
            )
            with self.assertRaisesRegex(
                ValueError,
                "local_mini131_performance_deterministic_binding_mismatch",
            ):
                build_performance_evaluation(ledger, self.decision_paths)

    def test_parser_rerun_must_match_frozen_receipt_exactly(self) -> None:
        source = self.ledger.paths.candidates.with_name("parser-rerun.json")
        payload = json.loads(source.read_text(encoding="utf-8"))
        payload["result"]["cases"][0]["observed"]["tampered"] = True
        with tempfile.TemporaryDirectory() as directory:
            private_root = (
                Path(directory)
                / "resources/data_refined/private/outputs/local/suite/run"
            )
            candidate_path = private_root / "candidates.jsonl"
            _write_private(candidate_path.with_name("parser-rerun.json"), payload)
            paths = replace(self.ledger.paths, candidates=candidate_path)
            ledger = replace(self.ledger, paths=paths)
            with self.assertRaisesRegex(
                ValueError,
                "local_mini131_performance_parser_rerun_invalid",
            ):
                _load_parser_results(ledger)

    def test_review_history_must_match_all_raw_decisions(self) -> None:
        history = read_jsonl(self.ledger.paths.review_root / "review-history.jsonl")
        history[0]["review_output"]["rationale"] += " tampered"
        history[0]["output_sha256"] = sha256_text(
            canonical_json(history[0]["review_output"])
        )
        history_without_hash = copy.deepcopy(history[0])
        history_without_hash.pop("history_sha256")
        history[0]["history_sha256"] = sha256_text(
            canonical_json(history_without_hash)
        )
        with tempfile.TemporaryDirectory() as directory:
            review_root = Path(directory) / "evaluation/private/review"
            decision_paths: list[Path] = []
            for source in self.decision_paths:
                target = review_root / source.name
                rows = read_jsonl(source)
                _write_private_jsonl(target, rows)
                decision_paths.append(target)
            _write_private_jsonl(review_root / "review-history.jsonl", history)
            paths = replace(self.ledger.paths, review_root=review_root)
            ledger = replace(self.ledger, paths=paths)
            with self.assertRaisesRegex(
                ValueError,
                "local_mini131_performance_review_history_decision_mismatch",
            ):
                resolve_final_judgments(ledger, decision_paths)


if __name__ == "__main__":
    unittest.main()
