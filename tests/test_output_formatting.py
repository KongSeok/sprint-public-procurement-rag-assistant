from __future__ import annotations

import unittest

from src.generation.output_formatting import move_citation_to_end


class OutputFormattingTests(unittest.TestCase):
    def test_moves_citation_after_added_note(self):
        answer = "답변입니다.\n[근거: 문서.hwp]\n\n※ 참고: 보완 내용"
        self.assertEqual(
            move_citation_to_end(answer),
            "답변입니다.\n\n※ 참고: 보완 내용\n\n[근거: 문서.hwp]",
        )

    def test_deduplicates_multiple_citation_blocks(self):
        answer = "답변\n[근거: A.hwp, B.pdf]\n참고\n[근거: B.pdf, C.hwp]"
        self.assertEqual(
            move_citation_to_end(answer),
            "답변\n\n참고\n\n[근거: A.hwp, B.pdf, C.hwp]",
        )

    def test_answer_without_citation_is_unchanged(self):
        self.assertEqual(move_citation_to_end("답변"), "답변")

    def test_internal_brackets_in_document_name_are_preserved(self):
        answer = "답변\n[근거: 기관_[재공고][긴급]문서.hwp]\n참고"
        self.assertEqual(
            move_citation_to_end(answer),
            "답변\n\n참고\n\n[근거: 기관_[재공고][긴급]문서.hwp]",
        )


if __name__ == "__main__":
    unittest.main()
