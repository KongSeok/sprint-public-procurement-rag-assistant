from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from midprojectrag.corpus_analytics_baseline import (
    CASES_PATH,
    _build_enriched,
    _calculate,
    _compare_values,
    _load_and_bind_inputs,
    _verify_targets,
    _write_private_jsonl,
    linear_quantile,
)


class CorpusAnalyticsBaselineTests(unittest.TestCase):
    def test_linear_quantile_uses_frozen_n_minus_one_interpolation(self) -> None:
        values = [10, 20, 30, 40]
        self.assertEqual(linear_quantile(values, 0.25), 17.5)
        self.assertEqual(linear_quantile(values, 0.50), 25.0)
        self.assertEqual(linear_quantile(values, 0.75), 32.5)

    def test_comparison_applies_semantic_numeric_tolerances(self) -> None:
        comparisons = _compare_values(
            {
                "amount_won": 100.9,
                "share_percent": 50.009,
                "mean_to_median_ratio": 2.009,
                "count": 3,
            },
            {
                "amount_won": 100,
                "share_percent": 50.0,
                "mean_to_median_ratio": 2.0,
                "count": 3,
            },
            {"money_won": 1, "percentage_point": 0.01, "ratio": 0.01},
        )
        self.assertTrue(all(item["match"] for item in comparisons))

    def test_comparison_rejects_extra_or_missing_fields_and_list_items(self) -> None:
        comparisons = _compare_values(
            {"ids": ["a"], "extra": 1},
            {"ids": ["a", "b"]},
            {},
        )
        reasons = {item["reason"] for item in comparisons if not item["match"]}
        self.assertEqual(reasons, {"key_set_mismatch", "length_mismatch"})

    def test_private_jsonl_is_mode_0600_and_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "private" / "records.jsonl"
            _write_private_jsonl(path, [{"z": 1, "a": "value"}])
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"a": "value", "z": 1})

    @unittest.skipUnless(CASES_PATH.exists(), "frozen private analytics inputs are unavailable")
    def test_frozen_refined98_snapshot_recomputes_all_gold_fields(self) -> None:
        cases, target_contract, categories, _config = _load_and_bind_inputs()
        outputs, computed_targets = _calculate(_build_enriched(categories))
        _verify_targets(cases, target_contract, computed_targets)

        for case in cases:
            with self.subTest(case_id=case["case_id"]):
                comparisons = _compare_values(
                    outputs[case["case_id"]],
                    case["gold"]["expected"],
                    case["gold"]["numeric_tolerance"],
                )
                self.assertTrue(comparisons)
                self.assertTrue(all(item["match"] for item in comparisons))


if __name__ == "__main__":
    unittest.main()
