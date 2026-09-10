from __future__ import annotations

import unittest

from src.evaluation.scoring_v3 import scorer_v3_1_1


class ScorerV311Tests(unittest.TestCase):
    def setUp(self):
        self.row = {
            "id": "case-1",
            "required_fact_groups": [["예산 3억"]],
            "expected_doc_id": ["문서.hwp"],
        }
        self.prediction = {"retrieved_doc_ids": ["문서.hwp"]}

    def test_valid_citation_at_end(self):
        prediction = {**self.prediction, "answer": "예산 3억입니다.\n[근거: 문서.hwp]"}
        result = scorer_v3_1_1.score_item(self.row, prediction)
        self.assertEqual(result["citation_status"], "valid")
        self.assertTrue(result["citation_format_pass"])
        self.assertEqual(result["citation_recall"], 1.0)

    def test_misplaced_citation_keeps_content_score(self):
        prediction = {
            **self.prediction,
            "answer": "예산 3억입니다.\n[근거: 문서.hwp]\n\n※ 참고: 추가 설명",
        }
        result = scorer_v3_1_1.score_item(self.row, prediction)
        self.assertEqual(result["citation_status"], "misplaced")
        self.assertFalse(result["citation_format_pass"])
        self.assertTrue(result["citation_content_available"])
        self.assertEqual(result["citation_recall"], 1.0)
        self.assertIn("citation_misplaced", result["failure_reasons"])

    def test_missing_citation_is_distinct(self):
        prediction = {**self.prediction, "answer": "예산 3억입니다."}
        result = scorer_v3_1_1.score_item(self.row, prediction)
        self.assertEqual(result["citation_status"], "missing")
        self.assertFalse(result["citation_content_available"])
        self.assertIn("citation_missing", result["failure_reasons"])


if __name__ == "__main__":
    unittest.main()
