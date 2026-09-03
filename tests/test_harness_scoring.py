import unittest
from midprojectrag.offline_harness import fact_matches, normalize_text, score_answer


class HarnessScoringTests(unittest.TestCase):
    def test_comma_money(self):
        self.assertTrue(fact_matches("사업금액은 150,000,000원", "사업금액 150000000원"))

    def test_korean_money_unit(self):
        self.assertTrue(fact_matches("1억 5천만원", "150000000원"))

    def test_amount_difference_not_equal(self):
        for other in ("150000원", "-150000000원", "150000000%", "1500000000원"):
            with self.subTest(other=other):
                self.assertFalse(fact_matches(other, "150000000원"))

    def test_money_label_parentheses_order(self):
        self.assertTrue(fact_matches("150,000원(계약금액)", "계약금액은 150000원"))

    def test_ambiguous_adjacent_numbers_not_added(self):
        self.assertFalse(fact_matches("100 200원", "300원"))

    def test_date_formats(self):
        for value in ("2026.09.03", "2026-9-3", "2026년 9월 3일"):
            self.assertTrue(fact_matches(value, "2026-09-03"))

    def test_date_order_matters(self):
        self.assertFalse(fact_matches("2026-03-09", "2026-09-03"))

    def test_invalid_date_not_repaired(self):
        self.assertNotEqual(normalize_text("2026-02-30"), normalize_text("2026-03-02"))

    def test_particle_parentheses_and_word_order(self):
        self.assertTrue(fact_matches("제출서류는 납세증명서(원본)", "원본 납세증명서 제출서류"))

    def test_numeric_entity_swaps_not_equal(self):
        self.assertFalse(fact_matches("a 20원 b 10원", "a 10원 b 20원"))
        self.assertFalse(fact_matches("a 20원, b 10원", "a 10원"))
        self.assertTrue(fact_matches("b 20원, a 10원", "a 10원"))

    def test_full_bracketed_filename(self):
        name = "[재공고][긴급] 운행정보기록(최종).hwp"
        self.assertTrue(fact_matches("첨부 파일: " + name, name))
        self.assertFalse(fact_matches("[재공고][긴급]", name))
        self.assertFalse(fact_matches("[재공고][긴급] 운행정보기록(초안).hwp", name))

    def test_allow_deny(self):
        self.assertFalse(fact_matches("공동수급 허용 불가", "공동수급 허용"))
        self.assertTrue(fact_matches("공동수급 허용", "공동수급 허용"))

    def test_filename_suffix_is_not_the_complete_filename(self):
        self.assertFalse(fact_matches("other-report.hwp", "report.hwp"))
        self.assertFalse(fact_matches("[재공고][긴급]사업.hwp", "[긴급]사업.hwp"))

    def test_obligation_and_inclusion_negation(self):
        self.assertFalse(fact_matches("제출 의무 아님", "제출 의무"))
        self.assertFalse(fact_matches("부가세 포함 아니오", "부가세 포함"))

    def test_scoped_negation_other_clause(self):
        self.assertTrue(fact_matches("공동수급 허용, 하도급 금지", "공동수급 허용"))

    def test_number_and_polarity_both_must_match(self):
        self.assertFalse(fact_matches("공동수급 2개 업체 허용 불가", "공동수급 2개 업체 허용"))

    def test_partial_abstention(self):
        score = score_answer("금액은 100원이며 기간은 확인할 수 없습니다", ["금액 100원", "기간 10일"], status="answered")
        self.assertEqual(score.fact_coverage, .5)
        self.assertEqual(score.answer_state, "partial_abstention")

    def test_total_abstention(self):
        score = score_answer("정보를 확인할 수 없습니다", ["금액 100원"], status="abstained")
        self.assertEqual(score.answer_state, "abstained")

    def test_error_not_safe_abstention(self):
        self.assertEqual(score_answer("", [], status="error").answer_state, "error")

    def test_or_within_and_between_groups(self):
        score = score_answer("공동수급 허용", [["공동수급 허용", "공동수급 가능"], ["금액 100원"]])
        self.assertEqual(score.fact_hits, (True, False))
        self.assertEqual(score.fact_coverage, .5)

    def test_no_gold_fact_denominator_is_unavailable_not_perfect(self):
        self.assertIsNone(score_answer("some answer", []).fact_coverage)

    def test_unknown_and_negated_assertions_not_credited(self):
        for answer, fact in (
            ("금액은 100원이 아닙니다", "금액 100원"),
            ("하도급 금지 아님", "하도급 금지"),
            ("공동수급 허용 여부를 확인할 수 없습니다", "공동수급 허용"),
        ):
            with self.subTest(answer=answer):
                self.assertFalse(fact_matches(answer, fact))

    def test_one_quantity_still_requires_correct_entity(self):
        answer = "서울사업과 부산사업 중 서울사업의 금액은 100원"
        self.assertFalse(fact_matches(answer, "부산사업 금액 100원"))
        self.assertTrue(fact_matches(answer, "서울사업 금액 100원"))

    def test_filename_punctuation_not_stripped(self):
        self.assertFalse(fact_matches("report.hwp-backup.pdf", "report.hwp"))
        self.assertFalse(fact_matches("(초안)보고서.hwp", "보고서.hwp"))

    def test_abstention_state_independent_of_gold_and_separator(self):
        for separator in (". ", "\n", "이며 "):
            answer = "금액은 100원입니다" + separator + "기간은 확인할 수 없습니다"
            for groups in ([], ["금액 100원"], ["금액 200원"]):
                self.assertEqual(score_answer(answer, groups).answer_state, "partial_abstention")
        self.assertEqual(score_answer("공동수급 허용 여부를 확인할 수 없습니다", ["공동수급 허용"]).answer_state, "abstained")


if __name__ == "__main__":
    unittest.main()
