from __future__ import annotations

import copy
import unittest

from midprojectrag.supplemental_evaluation import score_set_cases
from tests.evaluation.supplemental_helpers import (
    SHA_A,
    attach_eval_hash,
    doc_id,
    make_set_case,
    make_set_run,
)


class SetRetrievalMetricTests(unittest.TestCase):
    def make_cases(self) -> list[dict[str, object]]:
        return [
            make_set_case(
                0, required_doc_ids=[doc_id(1), doc_id(2)], status="approved"
            ),
            make_set_case(1, required_doc_ids=[doc_id(3)], status="approved"),
        ]

    def score(
        self,
        cases: list[dict[str, object]],
        runs: list[dict[str, object]],
        *,
        known_doc_ids: set[str] | None = None,
        require_approved: bool | None = None,
    ) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "known_doc_ids": (
                {doc_id(index) for index in range(1, 31)}
                if known_doc_ids is None
                else known_doc_ids
            ),
            "manifest_sha256": SHA_A,
        }
        if require_approved is not None:
            kwargs["require_approved"] = require_approved
        return score_set_cases(cases, runs, **kwargs)

    def test_perfect_and_order_invariant_predictions_score_one(self) -> None:
        cases = self.make_cases()
        runs = [
            make_set_run(cases[0], [doc_id(2), doc_id(1)]),
            make_set_run(cases[1]),
        ]
        attach_eval_hash(cases, runs)
        report = self.score(cases, runs)
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["evaluation_tier"], "provisional")
        self.assertFalse(report["official_gold_ready"])
        self.assertFalse(report["suite_complete"])
        for value in report["metrics"].values():
            self.assertEqual(value, 1.0)
        self.assertTrue(all(item["exact_set_match"] for item in report["per_case"]))

    def test_extra_prediction_reduces_precision_but_not_recall(self) -> None:
        cases = self.make_cases()
        runs = [
            make_set_run(cases[0], [doc_id(1), doc_id(2), doc_id(9)]),
            make_set_run(cases[1]),
        ]
        attach_eval_hash(cases, runs)
        metrics = self.score(cases, runs)["metrics"]
        self.assertEqual(metrics["macro_precision"], 0.833333)
        self.assertEqual(metrics["macro_recall"], 1.0)
        self.assertEqual(metrics["micro_precision"], 0.75)
        self.assertEqual(metrics["micro_recall"], 1.0)
        self.assertEqual(metrics["exact_set_match"], 0.5)
        self.assertEqual(metrics["count_accuracy"], 0.5)

    def test_missing_prediction_reduces_recall_but_not_precision(self) -> None:
        cases = self.make_cases()
        runs = [
            make_set_run(cases[0], [doc_id(1)]),
            make_set_run(cases[1]),
        ]
        attach_eval_hash(cases, runs)
        metrics = self.score(cases, runs)["metrics"]
        self.assertEqual(metrics["macro_precision"], 1.0)
        self.assertEqual(metrics["macro_recall"], 0.75)
        self.assertEqual(metrics["micro_precision"], 1.0)
        self.assertEqual(metrics["micro_recall"], 0.666667)
        self.assertEqual(metrics["micro_f1"], 0.8)
        self.assertEqual(metrics["exact_set_match"], 0.5)
        self.assertEqual(metrics["count_accuracy"], 0.5)

    def test_draft_case_scores_as_explicitly_provisional_by_default(self) -> None:
        cases = [make_set_case(0, required_doc_ids=[doc_id(1)])]
        runs = [make_set_run(cases[0])]
        attach_eval_hash(cases, runs)
        report = self.score(cases, runs)
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["evaluation_tier"], "provisional")
        self.assertFalse(report["official_gold_ready"])
        self.assertEqual(report["metrics"]["exact_set_match"], 1.0)

    def test_official_only_gate_rejects_unreviewed_set_cases(self) -> None:
        cases = [make_set_case(0, required_doc_ids=[doc_id(1)])]
        runs = [make_set_run(cases[0])]
        attach_eval_hash(cases, runs)
        report = self.score(cases, runs, require_approved=True)
        self.assertFalse(report["passed"])
        self.assertEqual(report["evaluation_tier"], "official")
        self.assertFalse(report["official_gold_ready"])
        codes = {item["code"] for item in report["errors"]}
        self.assertIn("case_not_approved", codes)
        self.assertIn("official_suite_incomplete", codes)

    def test_complete_approved_suite_passes_official_gate(self) -> None:
        cases = [
            make_set_case(
                index,
                required_doc_ids=[doc_id(index + 1)],
                status="approved",
            )
            for index in range(13)
        ]
        runs = [make_set_run(case) for case in cases]
        attach_eval_hash(cases, runs)
        report = self.score(cases, runs, require_approved=True)
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["evaluation_tier"], "official")
        self.assertTrue(report["official_gold_ready"])
        self.assertTrue(report["suite_complete"])

    def test_unknown_but_well_formed_document_id_is_rejected(self) -> None:
        cases = self.make_cases()
        unknown_doc = doc_id(999)
        runs = [
            make_set_run(cases[0], [doc_id(1), doc_id(2), unknown_doc]),
            make_set_run(cases[1]),
        ]
        attach_eval_hash(cases, runs)
        report = self.score(cases, runs)
        self.assertFalse(report["passed"])
        self.assertIn(
            "set_run_unknown_doc_id", {item["code"] for item in report["errors"]}
        )

    def test_duplicate_bad_hash_runtime_error_and_missing_run_are_reported(self) -> None:
        cases = self.make_cases()
        duplicate = make_set_run(cases[0], [doc_id(1), doc_id(1)])
        attach_eval_hash(cases, [duplicate])
        duplicate["eval_set_sha256"] = "f" * 64
        duplicate["error"] = {"code": "synthetic_failure"}
        report = self.score(cases, [duplicate])
        codes = {issue["code"] for issue in report["errors"]}
        self.assertFalse(report["passed"])
        self.assertIn("set_run_doc_ids_invalid", codes)
        self.assertIn("set_run_hash_mismatch", codes)
        self.assertIn("set_run_runtime_error", codes)
        self.assertIn("set_run_missing", codes)

        unknown = copy.deepcopy(duplicate)
        unknown["case_id"] = "supplemental-set-unknown"
        report = self.score(cases, [unknown])
        self.assertIn("set_run_unknown_case", {item["code"] for item in report["errors"]})

    def test_invalid_unhashable_run_is_not_scored(self) -> None:
        cases = [make_set_case(0, required_doc_ids=[doc_id(1)])]
        run = make_set_run(cases[0])
        run["returned_doc_ids"] = [{}]
        attach_eval_hash(cases, [run])
        report = self.score(cases, [run])
        self.assertFalse(report["passed"])
        self.assertEqual(report["counts"]["scored"], 0)
        self.assertIn(
            "set_run_doc_ids_invalid", {item["code"] for item in report["errors"]}
        )


if __name__ == "__main__":
    unittest.main()
