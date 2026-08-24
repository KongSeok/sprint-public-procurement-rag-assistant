from __future__ import annotations

import copy
import unittest

from midprojectrag.evaluation import compare_reports, score_runs
from tests.evaluation.helpers import make_cases, make_runs, make_scoring_cases, scoring_kwargs


class MetricTests(unittest.TestCase):
    def test_perfect_synthetic_runs_score_expected_metrics(self) -> None:
        cases = make_scoring_cases("dev")
        report = score_runs(cases, make_runs(cases), **scoring_kwargs())
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["metrics"]["retrieval"]["document_recall_at_5"], 1.0)
        self.assertEqual(report["metrics"]["retrieval"]["all_required_docs_recalled_at_10"], 1.0)
        self.assertEqual(report["metrics"]["retrieval"]["mrr_at_10"], 1.0)
        self.assertEqual(report["metrics"]["answer"]["key_point_coverage"], 1.0)
        self.assertEqual(report["metrics"]["abstention"]["recall"], 1.0)
        self.assertEqual(report["metrics"]["abstention"]["false_answer_rate"], 0.0)
        self.assertEqual(report["metrics"]["operations"]["latency_total_p50_ms"], 200.0)
        self.assertEqual(report["metrics"]["operations"]["latency_total_p95_ms"], 380.0)

    def test_compare_rejects_different_corpus_snapshot(self) -> None:
        cases = make_scoring_cases("dev")
        baseline = score_runs(cases, make_runs(cases, stack_id="api"), **scoring_kwargs())
        candidate = score_runs(cases, make_runs(cases, stack_id="gcp_local"), **scoring_kwargs())
        candidate["corpus_manifest_sha256"] = "b" * 64
        comparison = compare_reports(baseline, candidate)
        self.assertFalse(comparison["passed"])
        self.assertEqual(comparison["errors"][0]["code"], "comparison_hash_mismatch")

    def test_compare_rejects_empty_reports(self) -> None:
        comparison = compare_reports({}, {})
        self.assertFalse(comparison["passed"])
        self.assertIn("invalid_score_report", {error["code"] for error in comparison["errors"]})

    def test_compare_rejects_same_stack_or_fabricated_shape(self) -> None:
        cases = make_scoring_cases("dev")
        baseline = score_runs(cases, make_runs(cases, stack_id="api"), **scoring_kwargs())
        same_stack = copy.deepcopy(baseline)
        comparison = compare_reports(baseline, same_stack)
        self.assertFalse(comparison["passed"])
        self.assertIn("comparison_stack_pair_invalid", {error["code"] for error in comparison["errors"]})

        fabricated = {
            "schema_version": "1.0",
            "passed": True,
            "stack_id": "gcp_local",
            "corpus_manifest_sha256": "a" * 64,
            "eval_set_sha256": baseline["eval_set_sha256"],
            "config_sha256": "c" * 64,
            "scoring_config_sha256": baseline["scoring_config_sha256"],
            "metrics": {"x": 1.0},
            "errors": [],
        }
        comparison = compare_reports(baseline, fabricated)
        self.assertFalse(comparison["passed"])
        self.assertIn("score_metric_section_missing", {error["code"] for error in comparison["errors"]})

        malformed_stack = copy.deepcopy(fabricated)
        malformed_stack["stack_id"] = []
        comparison = compare_reports(baseline, malformed_stack)
        self.assertFalse(comparison["passed"])
        self.assertIn("comparison_stack_pair_invalid", {error["code"] for error in comparison["errors"]})

    def test_compare_requires_complete_metrics_and_matching_counts(self) -> None:
        cases = make_scoring_cases("dev")
        baseline = score_runs(cases, make_runs(cases, stack_id="api"), **scoring_kwargs())
        candidate = score_runs(cases, make_runs(cases, stack_id="gcp_local"), **scoring_kwargs())
        del candidate["metrics"]["retrieval"]["mrr_at_10"]
        candidate["counts"]["cases"] += 1
        comparison = compare_reports(baseline, candidate)
        codes = {error["code"] for error in comparison["errors"]}
        self.assertFalse(comparison["passed"])
        self.assertIn("score_metric_missing", codes)
        self.assertIn("comparison_count_mismatch", codes)

        baseline = score_runs(cases, make_runs(cases, stack_id="api"), **scoring_kwargs())
        candidate = score_runs(cases, make_runs(cases, stack_id="gcp_local"), **scoring_kwargs())
        baseline["metrics"]["task_success"] = []
        candidate["metrics"]["task_success"] = []
        comparison = compare_reports(baseline, candidate)
        self.assertFalse(comparison["passed"])
        self.assertIn("invalid_score_metric_section", {error["code"] for error in comparison["errors"]})

        baseline = score_runs(cases, make_runs(cases, stack_id="api"), **scoring_kwargs())
        candidate = score_runs(cases, make_runs(cases, stack_id="gcp_local"), **scoring_kwargs())
        baseline["metrics"]["retrieval"]["document_recall_at_5"] = 0.0
        comparison = compare_reports(baseline, candidate)
        codes = {error["code"] for error in comparison["errors"]}
        self.assertFalse(comparison["passed"])
        self.assertIn("stale_threshold_evidence", codes)
        self.assertIn("source_thresholds_failed", codes)

    def test_scoring_config_is_mandatory_and_malformed_rules_fail_closed(self) -> None:
        cases = make_scoring_cases("dev")
        runs = make_runs(cases)
        missing = score_runs(cases, runs)
        self.assertFalse(missing["passed"])
        missing_codes = {error["code"] for error in missing["errors"]}
        self.assertIn("invalid_evaluation_config", missing_codes)
        self.assertIn("invalid_scoring_config_hash", missing_codes)

        kwargs = scoring_kwargs()
        kwargs["config"]["thresholds"]["metrics.answer.faithfulness"] = "disabled"
        malformed = score_runs(cases, runs, **kwargs)
        self.assertFalse(malformed["passed"])
        self.assertIn("invalid_threshold_rule", {error["code"] for error in malformed["errors"]})

        kwargs = scoring_kwargs()
        kwargs["config"]["minimum_cases"]["dev"] = []
        malformed_minimum = score_runs(cases, runs, **kwargs)
        self.assertFalse(malformed_minimum["passed"])
        self.assertIn("invalid_minimum_cases", {error["code"] for error in malformed_minimum["errors"]})

        kwargs = scoring_kwargs()
        kwargs["config"]["thresholds"]["metrics.retrieval.document_recall_at_5"]["value"] = 0.0
        weakened = score_runs(cases, runs, **kwargs)
        self.assertFalse(weakened["passed"])
        self.assertIn("frozen_threshold_changed", {error["code"] for error in weakened["errors"]})

        mismatch = score_runs(cases, runs, k_values=[5, 10], **scoring_kwargs())
        self.assertFalse(mismatch["passed"])
        self.assertIn("k_values_config_mismatch", {error["code"] for error in mismatch["errors"]})

        undersized_cases = make_cases("dev")
        undersized = score_runs(undersized_cases, make_runs(undersized_cases), **scoring_kwargs())
        self.assertFalse(undersized["passed"])
        self.assertIn("insufficient_scoring_cases", {error["code"] for error in undersized["errors"]})

    def test_missing_human_judgment_and_api_cost_fail_closed(self) -> None:
        cases = make_scoring_cases("dev")
        runs = make_runs(cases)
        runs[0]["judgment"]["correctness"] = None
        runs[1]["usage"]["cost_usd"] = None
        report = score_runs(cases, runs, **scoring_kwargs())
        codes = {error["code"] for error in report["errors"]}
        self.assertFalse(report["passed"])
        self.assertIn("human_judgment_missing", codes)
        self.assertIn("api_cost_missing", codes)
        self.assertLess(report["metrics"]["answer"]["judgment_coverage"], 1.0)
        self.assertLess(report["metrics"]["operations"]["api_cost_coverage"], 1.0)

    def test_multi_doc_citation_requires_matching_document_block_pair(self) -> None:
        cases = make_scoring_cases("dev")
        runs = make_runs(cases)
        multi_runs = [run for run in runs if run["case_id"].startswith("dev-multi-")][:2]
        for multi_run in multi_runs:
            citations = multi_run["response"]["citations"]
            citations[0]["source_block_ids"], citations[1]["source_block_ids"] = (
                citations[1]["source_block_ids"],
                citations[0]["source_block_ids"],
            )
        report = score_runs(cases, runs, **scoring_kwargs())
        self.assertFalse(report["passed"])
        self.assertLess(report["metrics"]["answer"]["gold_citation_precision"], 1.0)
        failed_thresholds = {
            result["metric"]
            for result in report["thresholds"]["results"]
            if result["passed"] is False
        }
        self.assertIn("metrics.answer.gold_citation_precision", failed_thresholds)

    def test_explicit_scope_rejects_retrieval_and_citations_from_other_documents(self) -> None:
        cases = make_scoring_cases("dev")
        case = cases[0]
        allowed_doc = case["gold"]["required_doc_ids"][0]
        case["document_scope"] = {"mode": "explicit", "doc_ids": [allowed_doc]}
        runs = make_runs(cases)
        rogue_doc = "doc_ffffffffffffffffffffffff"
        rogue_block = "block_ffffffffffffffffffffffff"
        runs[0]["retrieval"].append(
            {
                "rank": 2,
                "doc_id": rogue_doc,
                "chunk_id": "chunk_ffffffffffffffffffffffff",
                "source_block_ids": [rogue_block],
                "score": 0.5,
            }
        )
        runs[0]["response"]["citations"].append(
            {
                "doc_id": rogue_doc,
                "chunk_id": "chunk_ffffffffffffffffffffffff",
                "source_block_ids": [rogue_block],
                "locator": {"section_path": ["synthetic"], "page_start": 1, "page_end": 1},
            }
        )
        report = score_runs(cases, runs, **scoring_kwargs())
        codes = {error["code"] for error in report["errors"]}
        self.assertFalse(report["passed"])
        self.assertIn("retrieval_doc_outside_scope", codes)
        self.assertIn("citation_doc_outside_scope", codes)

    def test_unknown_success_requires_safe_reviewers_and_matching_reason(self) -> None:
        cases = make_scoring_cases("heldout")
        runs = make_runs(cases)
        unknown = next(run for run in runs if run["case_id"].startswith("heldout-unknown-"))
        unknown["judgment"]["safe_abstention"] = False
        report = score_runs(cases, runs, **scoring_kwargs())
        self.assertFalse(report["passed"])
        self.assertEqual(report["metrics"]["abstention"]["safe_abstention_rate"], 0.8)
        self.assertIn("unsafe_abstention", {error["code"] for error in report["errors"]})

        runs = make_runs(cases)
        unknown = next(run for run in runs if run["case_id"].startswith("heldout-unknown-"))
        unknown["judgment"]["reviewer_ids"] = []
        report = score_runs(cases, runs, **scoring_kwargs())
        self.assertFalse(report["passed"])
        self.assertEqual(report["metrics"]["abstention"]["recall"], 0.8)
        self.assertIn("human_judgment_missing", {error["code"] for error in report["errors"]})

        runs = make_runs(cases)
        unknown = next(run for run in runs if run["case_id"].startswith("heldout-unknown-"))
        unknown["response"]["abstention"]["reason"] = "out_of_scope"
        unknown["response"]["answer"] = "질문이 제공된 문서 범위를 벗어납니다."
        report = score_runs(cases, runs, **scoring_kwargs())
        self.assertFalse(report["passed"])
        self.assertEqual(report["metrics"]["abstention"]["recall"], 0.8)
        self.assertIn("abstention_reason_mismatch", {error["code"] for error in report["errors"]})

    def test_invalid_retrieval_rank_is_reported_without_crash(self) -> None:
        cases = make_scoring_cases("dev")
        runs = make_runs(cases)
        runs[0]["retrieval"][0]["rank"] = "first"
        report = score_runs(cases, runs, **scoring_kwargs())
        self.assertFalse(report["passed"])
        self.assertIn("invalid_rank", {error["code"] for error in report["errors"]})

    def test_unhashable_judgment_and_citation_values_do_not_crash_scoring(self) -> None:
        cases = make_scoring_cases("dev")
        runs = make_runs(cases)
        cases[0]["gold"]["required_key_points"] = None
        runs[0]["judgment"]["matched_key_point_ids"] = [[]]
        runs[0]["response"]["citations"][0]["source_block_ids"] = [[]]
        runs[0]["response"]["citations"][0]["doc_id"] = []
        report = score_runs(cases, runs, **scoring_kwargs())
        self.assertFalse(report["passed"])
        codes = {error["code"] for error in report["errors"]}
        self.assertIn("invalid_matched_key_points", codes)
        self.assertIn("invalid_key_points", codes)
        self.assertIn("invalid_block_id", codes)
        self.assertIn("invalid_doc_id", codes)

        fresh_cases = make_scoring_cases("dev")
        malformed_runs = make_runs(fresh_cases)
        malformed_runs[0] = []
        report = score_runs(fresh_cases, malformed_runs, **scoring_kwargs())
        self.assertFalse(report["passed"])
        self.assertIn("invalid_run_record", {error["code"] for error in report["errors"]})

    def test_local_stack_hardware_constraints_are_enforced(self) -> None:
        cases = make_scoring_cases("dev")
        runs = make_runs(cases, stack_id="gcp_local")
        runs[0]["environment"]["gpu_model"] = "NVIDIA T4"
        report = score_runs(cases, runs, **scoring_kwargs())
        self.assertFalse(report["passed"])
        self.assertIn("gcp_gpu_not_l4", {error["code"] for error in report["errors"]})


if __name__ == "__main__":
    unittest.main()
