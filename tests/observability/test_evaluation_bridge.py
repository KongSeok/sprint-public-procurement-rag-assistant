from __future__ import annotations

import unittest

from midprojectrag.observability import MemoryObserver
from midprojectrag.observability.evaluation_bridge import export_run_judgment_scores


class EvaluationBridgeTests(unittest.TestCase):
    def test_exports_only_numeric_and_boolean_judgments(self) -> None:
        observer = MemoryObserver()
        exported = export_run_judgment_scores(
            {
                "response": {"trace_id": "b" * 32, "answer": "restricted"},
                "judgment": {
                    "correctness": 0.8,
                    "faithfulness": 1.0,
                    "factual_claim_coverage": None,
                    "citation_validity": 1.0,
                    "follow_up_success": None,
                    "safe_abstention": False,
                    "reviewer_ids": ["human-name-must-not-export"],
                },
            },
            observer,
        )
        self.assertEqual(exported, 4)
        self.assertEqual(
            [record.name for record in observer.scores],
            ["correctness", "faithfulness", "citation_validity", "safe_abstention"],
        )
        self.assertNotIn("human-name", repr(observer.scores))

    def test_invalid_trace_or_score_fails_instead_of_reporting_false_export_count(self) -> None:
        observer = MemoryObserver()
        with self.assertRaisesRegex(ValueError, "invalid_score_trace_id"):
            export_run_judgment_scores(
                {"response": {"trace_id": "trace-not-hex"}, "judgment": {"correctness": 1.0}},
                observer,
            )
        with self.assertRaisesRegex(ValueError, "invalid_judgment_score"):
            export_run_judgment_scores(
                {"response": {"trace_id": "a" * 32}, "judgment": {"correctness": 2.0}},
                observer,
            )
        self.assertEqual(observer.scores, ())


if __name__ == "__main__":
    unittest.main()
