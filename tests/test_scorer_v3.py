from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "evaluation" / "scoring_v3" / "scorer.py"
SPEC = importlib.util.spec_from_file_location("evaluate_golden_testset_v3", MODULE_PATH)
SCORER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(SCORER)


class ScorerV3Tests(unittest.TestCase):
    def test_real_abstention_phrase_is_recognized(self):
        answer = "확인되지 않습니다. 근거: 울산광역시_사업.hwp"
        self.assertEqual(SCORER.classify_response(answer)["response_status"], "abstained")

    def test_abstention_explanation_is_not_partial_answer(self):
        answer = "확인되지 않습니다. 문서에 인건비 금액이나 비율이 명시되어 있지 않습니다. 근거 문서: 사업.hwp"
        self.assertEqual(SCORER.classify_response(answer)["response_status"], "abstained")

    def test_positive_fact_plus_abstention_is_partial(self):
        answer = "예산은 3억 원입니다. 다만 기간은 확인할 수 없습니다."
        self.assertEqual(SCORER.classify_response(answer)["response_status"], "partial_answer")

    def test_top_level_abstention_decision_scores_100(self):
        item = {"id": "g22", "decision": "abstain", "required_fact_groups": []}
        result = SCORER.score_item(item, {"answer": "확인되지 않습니다."})
        self.assertEqual(result["response_status"], "abstained")
        self.assertEqual(result["end_to_end_score"], 100.0)

    def test_legal_percent_is_equivalent(self):
        self.assertTrue(SCORER.option_matches("계약금액의 100분의 10 이상", "계약금액의 10% 이상"))
        self.assertTrue(SCORER.option_matches("계약금액의 10% 이상", "계약금액의 100분의 10 이상"))

    def test_korean_money_won_suffix_is_equivalent(self):
        self.assertTrue(SCORER.option_matches("총 사업예산이 20억 미만", "20억원 미만"))

    def test_comparator_direction_is_preserved(self):
        self.assertFalse(SCORER.option_matches("총 사업예산이 20억 이상", "20억원 미만"))

    def test_josa_and_eomi_variants(self):
        self.assertTrue(SCORER.option_matches("GKL 그룹웨어 사업이 더 큽니다", "GKL 그룹웨어 사업이 더 큼"))
        self.assertTrue(SCORER.option_matches("이유가 명시되어 있지 않습니다", "이유가 명시되어 있지 않음"))

    def test_participation_paraphrase(self):
        self.assertTrue(SCORER.option_matches("해당 업체는 참여할 수 있습니다", "참여 가능"))

    def test_positive_negative_conflict_is_rejected(self):
        self.assertFalse(SCORER.option_matches("해당 업체는 참여할 수 없습니다", "참여 가능"))
        self.assertFalse(SCORER.option_matches("부가가치세 미포함", "부가가치세 포함"))

    def test_missing_required_number_is_rejected(self):
        self.assertFalse(SCORER.option_matches("제안서 본문의 페이지 제한은 확인되지 않습니다", "본문 200페이지"))
        self.assertFalse(SCORER.option_matches("제안서 제출부수는 확인되지 않습니다", "제안서 10부"))

    def test_partial_morph_overlap_is_not_enough(self):
        self.assertFalse(
            SCORER.option_matches(
                "입찰 안내와 제출요령은 원문 확인이 필요합니다",
                "입찰서 제출마감일 전일까지",
            )
        )
        self.assertFalse(
            SCORER.option_matches(
                "입찰참가 자격 조항을 확인해야 합니다",
                "다른 참가자격 충족 필요",
            )
        )


if __name__ == "__main__":
    unittest.main()
