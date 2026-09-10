from __future__ import annotations

import unittest

from src.evaluation.scoring_v3 import scorer_v3_1_2


class ScorerV312Tests(unittest.TestCase):
    def setUp(self):
        self.doc_id = "기관_[재공고][긴급]정보시스템 구축.hwp"
        self.row = {
            "id": "nested-bracket-citation",
            "required_fact_groups": [["예산 3억"]],
            "expected_doc_id": [self.doc_id],
        }
        self.prediction = {"retrieved_doc_ids": [self.doc_id]}

    def test_nested_brackets_are_valid_at_end(self):
        result = scorer_v3_1_2.score_item(
            self.row,
            {
                **self.prediction,
                "answer": f"예산 3억입니다.\n[근거: {self.doc_id}]",
            },
        )
        self.assertEqual(result["citation_status"], "valid")
        self.assertTrue(result["citation_format_pass"])
        self.assertEqual(result["cited_doc_ids"], [self.doc_id])
        self.assertEqual(result["citation_recall"], 1.0)
        self.assertEqual(result["citation_precision"], 1.0)

    def test_nested_brackets_are_misplaced_when_note_follows(self):
        result = scorer_v3_1_2.score_item(
            self.row,
            {
                **self.prediction,
                "answer": f"예산 3억입니다.\n[근거: {self.doc_id}]\n※ 참고: 설명",
            },
        )
        self.assertEqual(result["citation_status"], "misplaced")
        self.assertFalse(result["citation_format_pass"])
        self.assertEqual(result["citation_recall"], 1.0)
        self.assertIn("citation_misplaced", result["failure_reasons"])

    def test_multiple_nested_bracket_documents(self):
        second = "학교_[사전공개]분석.pdf"
        status, cited = scorer_v3_1_2._citation_diagnostics(
            f"답변\n[근거: {self.doc_id}, {second}]"
        )
        self.assertEqual(status, "valid")
        self.assertEqual(cited, [self.doc_id, second])


if __name__ == "__main__":
    unittest.main()
