from __future__ import annotations

import unittest

from src.retrieval.query_filters import build_metadata_filter, parse_query_constraints


class QueryFilterTest(unittest.TestCase):
    def test_budget_and_local_government_filter(self):
        predicate = build_metadata_filter("예산 3억 이상인 지자체 사업")
        self.assertTrue(predicate({"사업_금액": 300_000_000, "발주_기관": "서울특별시"}))
        self.assertFalse(predicate({"사업_금액": 299_000_000, "발주_기관": "서울특별시"}))
        self.assertFalse(predicate({"사업_금액": 500_000_000, "발주_기관": "한국전력공사"}))

    def test_exclusive_budget(self):
        constraints = parse_query_constraints("3억 초과 사업")
        self.assertFalse(constraints.matches({"사업_금액": 300_000_000, "발주_기관": ""}))
        self.assertTrue(constraints.matches({"사업_금액": 300_000_001, "발주_기관": ""}))

    def test_no_constraint_returns_none(self):
        self.assertIsNone(build_metadata_filter("사업 내용을 요약해줘"))


if __name__ == "__main__":
    unittest.main()
