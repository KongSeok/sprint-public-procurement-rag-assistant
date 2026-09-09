from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from src.evaluation.document_ids import extract_context_doc_ids
from src.evaluation.golden_set_v3_1 import (
    B15_ADDITIONAL_SOURCE_LABELS,
    GOLDEN_PATCH_VERSION,
    load_golden_set_v3_1,
)
from src.evaluation.scoring_v3 import scorer_v3_1


class EvaluationV31Tests(unittest.TestCase):
    def test_context_doc_id_keeps_internal_brackets(self):
        context = (
            "[문서: 한국철도공사 (용역)_[재공고][긴급][협상형]운행정보.hwp]\n"
            "본문\n[문서: 일반문서.pdf]\n"
        )
        self.assertEqual(
            extract_context_doc_ids(context),
            [
                "한국철도공사 (용역)_[재공고][긴급][협상형]운행정보.hwp",
                "일반문서.pdf",
            ],
        )

    def test_g22_style_answer_is_abstention(self):
        answer = (
            "확인되지 않습니다. 문서에는 사업예산이 986,945,000원으로 명시되어 있으나, "
            "국내 시장 평균 정보는 제공되어 있지 않습니다. [근거: 울산광역시_사업.hwp]"
        )
        status = scorer_v3_1.classify_response(answer)
        self.assertEqual(status["response_status"], "abstained")

    def test_answer_then_abstention_remains_partial(self):
        answer = "예산은 3억 원입니다. 계약기간은 확인할 수 없습니다."
        self.assertEqual(
            scorer_v3_1.classify_response(answer)["response_status"],
            "partial_answer",
        )

    def test_leading_abstention_then_definitive_claim_is_not_accepted(self):
        answer = "확인되지 않습니다. 그러나 결론적으로 시장 평균보다 낮습니다."
        self.assertNotEqual(
            scorer_v3_1.classify_response(answer)["response_status"],
            "abstained",
        )

    def test_g22_style_answer_scores_100_for_abstention_gold(self):
        row = {"id": "g22", "decision": "abstain", "required_fact_groups": []}
        prediction = {
            "answer": (
                "확인되지 않습니다. 사업예산은 986,945,000원이지만 시장 평균 자료는 "
                "제공되어 있지 않습니다."
            )
        }
        result = scorer_v3_1.score_item(row, prediction)
        self.assertEqual(result["end_to_end_score"], 100.0)
        self.assertTrue(result["abstention_match"])

    def test_b15_overlay_expands_expected_documents_to_15(self):
        original = [f"기존문서-{number:02d}.hwp" for number in range(12)]
        corpus = set(original).union(B15_ADDITIONAL_SOURCE_LABELS)
        base = pd.DataFrame(
            [{"id": "supplemental-set-b15", "expected_doc_id": original}]
        )
        with patch(
            "src.evaluation.golden_set_v3_1.load_golden_set_v3",
            return_value=base,
        ):
            result = load_golden_set_v3_1(corpus_doc_ids=corpus)
        self.assertEqual(len(result.iloc[0]["expected_doc_id"]), 15)
        self.assertEqual(result.iloc[0]["golden_patch_version"], GOLDEN_PATCH_VERSION)


if __name__ == "__main__":
    unittest.main()
