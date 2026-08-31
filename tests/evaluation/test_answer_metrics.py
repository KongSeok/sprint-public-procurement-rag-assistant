from __future__ import annotations

import unittest

from midprojectrag.supplemental_evaluation import score_answer_cases
from tests.evaluation.supplemental_helpers import (
    SHA_A,
    attach_eval_hash,
    doc_id,
    make_answer_case,
    make_answer_run,
)


class AnswerMetricTests(unittest.TestCase):
    def make_cases(self, *, status: str = "draft") -> list[dict[str, object]]:
        cases = [make_answer_case(index, status=status) for index in range(44)]
        cases.extend(
            make_answer_case(index, lane="answer_alignment", status=status)
            for index in range(44, 56)
        )
        return cases

    def score(
        self,
        cases: list[dict[str, object]],
        runs: list[dict[str, object]],
        *,
        require_approved: bool = False,
    ) -> dict[str, object]:
        return score_answer_cases(
            cases,
            runs,
            known_doc_ids={doc_id(index) for index in range(1, 100)},
            manifest_sha256=SHA_A,
            require_approved=require_approved,
        )

    def test_complete_draft_suite_scores_provisionally_without_name_error(self) -> None:
        cases = self.make_cases()
        runs = [make_answer_run(case) for case in cases]
        attach_eval_hash(cases, runs)
        report = self.score(cases, runs)
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["evaluation_tier"], "provisional")
        self.assertFalse(report["official_gold_ready"])
        self.assertTrue(report["suite_complete"])
        self.assertEqual(report["config_sha256"], SHA_A)
        self.assertEqual(report["counts"]["scored"], 56)
        self.assertEqual(report["metrics"]["document_recall_at_1"], 1.0)

    def test_complete_approved_suite_passes_official_gate(self) -> None:
        cases = self.make_cases(status="approved")
        runs = [make_answer_run(case) for case in cases]
        attach_eval_hash(cases, runs)
        report = self.score(cases, runs, require_approved=True)
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["evaluation_tier"], "official")
        self.assertTrue(report["official_gold_ready"])
        self.assertTrue(report["suite_complete"])

    def test_official_incomplete_suite_fails_closed(self) -> None:
        cases = [make_answer_case(0, status="approved")]
        runs = [make_answer_run(cases[0])]
        attach_eval_hash(cases, runs)
        report = self.score(cases, runs, require_approved=True)
        self.assertFalse(report["passed"])
        self.assertEqual(report["evaluation_tier"], "official")
        self.assertFalse(report["official_gold_ready"])
        self.assertIn(
            "official_suite_incomplete", {item["code"] for item in report["errors"]}
        )

    def test_invalid_run_is_reported_but_never_enters_metrics(self) -> None:
        cases = [make_answer_case(0)]
        run = make_answer_run(cases[0])
        run["retrieved_doc_ids"] = [{}]
        run["usage"]["cost_usd"] = "not-a-number"
        attach_eval_hash(cases, [run])
        report = self.score(cases, [run])
        codes = {item["code"] for item in report["errors"]}
        self.assertFalse(report["passed"])
        self.assertIn("answer_run_retrieved_doc_ids_invalid", codes)
        self.assertIn("answer_run_usage_invalid", codes)
        self.assertEqual(report["counts"]["scored"], 0)
        self.assertEqual(report["metrics"]["total_cost_usd"], 0)
        self.assertIsNone(report["metrics"]["mean_total_latency_ms"])

    def test_error_response_does_not_inflate_abstention_accuracy(self) -> None:
        cases = [make_answer_case(0)]
        runs = [make_answer_run(cases[0], status="error")]
        attach_eval_hash(cases, runs)
        report = self.score(cases, runs)
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["counts"]["runtime_errors"], 1)
        self.assertEqual(report["metric_coverage"]["abstention"], 0)
        self.assertIsNone(report["metrics"]["abstention_behavior_match"])
        self.assertIsNone(report["per_case"][0]["abstention_behavior_match"])
        self.assertEqual(report["metrics"]["response_error_rate"], 1.0)

    def test_citation_must_be_retrieved_and_config_must_be_single(self) -> None:
        cases = [make_answer_case(0), make_answer_case(1)]
        runs = [
            make_answer_run(cases[0]),
            make_answer_run(cases[1], config_sha256="b" * 64),
        ]
        runs[0]["retrieved_doc_ids"] = []
        attach_eval_hash(cases, runs)
        report = self.score(cases, runs)
        codes = {item["code"] for item in report["errors"]}
        self.assertFalse(report["passed"])
        self.assertIn("answer_run_citation_not_retrieved", codes)
        self.assertNotIn("answer_run_config_hash_mixed", codes)
        self.assertEqual(report["counts"]["scored"], 1)

        runs[0] = make_answer_run(cases[0])
        attach_eval_hash(cases, runs)
        report = self.score(cases, runs)
        self.assertIn(
            "answer_run_config_hash_mixed",
            {item["code"] for item in report["errors"]},
        )


if __name__ == "__main__":
    unittest.main()
