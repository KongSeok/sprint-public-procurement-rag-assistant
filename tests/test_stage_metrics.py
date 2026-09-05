import unittest
from dataclasses import FrozenInstanceError
from types import MappingProxyType

from midprojectrag.stage_metrics import StageInput, score_stages


A = ("doc-a", "block-a", "a" * 64)
B = ("doc-b", "block-b", "b" * 64)
C = ("doc-c", "block-c", "c" * 64)
NOISE = ("doc-x", "block-x", "d" * 64)
METRIC_KEYS = {"status", "value", "numerator", "denominator", "reason"}


def stage(*rows):
    return StageInput(tuple(frozenset(row) for row in rows))


class StageMetricsTests(unittest.TestCase):
    def assert_available(self, metric, numerator, denominator):
        self.assertEqual(metric, {
            "status": "available", "value": numerator / denominator,
            "numerator": numerator, "denominator": denominator, "reason": None,
        })

    def assert_unscored(self, metric, status):
        self.assertEqual(set(metric), METRIC_KEYS)
        self.assertEqual(metric["status"], status)
        self.assertIsNone(metric["value"])
        self.assertTrue(metric["reason"])

    def test_context_loss_and_asymmetric_rescue_have_gold_denominators(self):
        result = score_stages(frozenset({A, B, C}), {
            "lane_dense": stage({A}, {NOISE}),
            "lane_lexical": stage({B}, {C}, {NOISE}),
            "fusion": stage({A}, {B}, {NOISE}),
            "final_context": stage({B}, {NOISE}),
        })
        self.assert_available(result["pre_required_recall"], 2, 3)
        self.assert_available(result["post_required_recall"], 1, 3)
        self.assert_available(result["relevant_retention"], 1, 2)
        self.assert_available(result["lexical_rescue"], 1, 2)
        self.assert_available(result["dense_rescue"], 1, 1)

    def test_cutoffs_slice_raw_rows_without_rank_compaction(self):
        result = score_stages(frozenset({A, B}), {
            "fusion": stage({A}, {A}, set(), {B})
        }, ks=(1, 2, 3, 4, 20))
        for cutoff in (1, 2, 3):
            self.assert_available(result["stage_recall"]["fusion"][str(cutoff)], 1, 2)
        for cutoff in (4, 20):
            self.assert_available(result["stage_recall"]["fusion"][str(cutoff)], 2, 2)

    def test_one_candidate_can_cover_multiple_anchors_once(self):
        result = score_stages(frozenset({A, B}), {"fusion": stage({A, B}, {B})})
        self.assert_available(result["stage_recall"]["fusion"]["1"], 2, 2)
        self.assert_available(result["pre_required_recall"], 2, 2)

    def test_ready_executed_empty_result_is_zero_not_unavailable(self):
        result = score_stages(frozenset({A}), {
            name: StageInput() for name in ("lane_dense", "lane_lexical", "fusion", "final_context")
        })
        for name in ("pre_required_recall", "post_required_recall", "lexical_rescue", "dense_rescue"):
            self.assert_available(result[name], 0, 1)
        self.assert_unscored(result["relevant_retention"], "not_applicable")
        self.assertEqual(result["relevant_retention"]["denominator"], 0)

    def test_retention_does_not_credit_post_context_new_gold(self):
        result = score_stages(frozenset({A, B}), {
            "fusion": stage({A}), "final_context": stage({B})
        })
        self.assert_available(result["post_required_recall"], 1, 2)
        self.assert_available(result["relevant_retention"], 0, 1)

    def test_rescue_requires_relevant_anchor_to_survive_fusion(self):
        result = score_stages(frozenset({A}), {
            "lane_dense": StageInput(), "lane_lexical": stage({A, NOISE}),
            "fusion": stage({NOISE}),
        })
        self.assert_available(result["lexical_rescue"], 0, 1)
        self.assert_unscored(result["dense_rescue"], "not_applicable")

    def test_missing_stage_is_unavailable_even_when_denominator_would_be_zero(self):
        result = score_stages(frozenset({A}), {
            "lane_dense": stage({A}), "fusion": StageInput()
        })
        self.assert_unscored(result["lexical_rescue"], "unavailable")
        self.assert_unscored(result["relevant_retention"], "unavailable")
        self.assertIsNone(result["lexical_rescue"]["denominator"])

    def test_unavailable_stage_carries_reason_and_precedes_zero_denominator(self):
        result = score_stages(frozenset({A}), {
            "lane_dense": stage({A}), "lane_lexical": StageInput(status="unavailable", reason="provider_error"),
            "fusion": StageInput(), "final_context": StageInput(status="unavailable", reason="unresolved_anchor"),
        })
        self.assert_unscored(result["lexical_rescue"], "unavailable")
        self.assertIn("provider_error", result["lexical_rescue"]["reason"])
        self.assert_unscored(result["relevant_retention"], "unavailable")
        self.assertIn("unresolved_anchor", result["relevant_retention"]["reason"])

    def test_absent_and_explicit_unavailable_stages_are_not_fake_zero(self):
        result = score_stages(frozenset({A}), {"rerank": StageInput(status="unavailable")})
        self.assertEqual(len(result["stage_recall"]), 6)
        for metrics in result["stage_recall"].values():
            for metric in metrics.values():
                self.assert_unscored(metric, "unavailable")

    def test_missing_or_inapplicable_qrels_propagate_without_partial_scores(self):
        for qrel_status, expected_status in (("missing", "unavailable"), ("not_applicable", "not_applicable")):
            with self.subTest(qrel_status=qrel_status):
                result = score_stages(frozenset(), {"fusion": stage({A})}, qrel_status=qrel_status)
                for name, metric in result.items():
                    if name != "stage_recall":
                        self.assert_unscored(metric, expected_status)
                        self.assertIsNone(metric["numerator"])
                        self.assertIsNone(metric["denominator"])
                for metrics in result["stage_recall"].values():
                    for metric in metrics.values():
                        self.assert_unscored(metric, expected_status)

    def test_configurable_pre_context_stage_does_not_change_fusion_rescue(self):
        result = score_stages(frozenset({A, B}), {
            "lane_dense": stage({A}), "lane_lexical": stage({B}),
            "fusion": stage({A, B}), "rerank": stage({B}), "final_context": stage({B}),
        }, pre_context_stage="rerank")
        self.assert_available(result["pre_required_recall"], 1, 2)
        self.assert_available(result["relevant_retention"], 1, 1)
        self.assert_available(result["lexical_rescue"], 1, 1)

    def test_anchor_matching_preserves_doc_block_and_locator_identity(self):
        variants = (("other-doc", A[1], A[2]), (A[0], "other-block", A[2]), (A[0], A[1], "f" * 64))
        result = score_stages(frozenset({A}), {"fusion": stage(set(variants))})
        self.assert_available(result["pre_required_recall"], 0, 1)

    def test_input_mapping_and_stage_remain_unchanged(self):
        item = stage({A}, {B})
        inputs = MappingProxyType({"fusion": item})
        first = score_stages(frozenset({A}), inputs)
        first["stage_recall"]["fusion"]["1"]["value"] = -1
        self.assert_available(score_stages(frozenset({A}), inputs)["stage_recall"]["fusion"]["1"], 1, 1)
        self.assertEqual(inputs["fusion"].rows, (frozenset({A}), frozenset({B})))
        with self.assertRaises(FrozenInstanceError):
            item.status = "unavailable"

    def test_rejects_invalid_qrels(self):
        for required, status in ((frozenset(), "ready"), (frozenset({A}), "missing"), (frozenset({A}), "not_applicable"), (frozenset({A}), "draft"), ({A}, "ready"), (frozenset({("doc", "block")}), "ready"), (frozenset({("", "block", "hash")}), "ready")):
            with self.subTest(required=required, status=status), self.assertRaises(ValueError):
                score_stages(required, {}, qrel_status=status)

    def test_rejects_invalid_cutoffs(self):
        for cutoffs in ((), (True,), (0,), (-1,), (1.0,), ("1",), (1, 1), [1, 3], ([],)):
            with self.subTest(cutoffs=cutoffs), self.assertRaises(ValueError):
                score_stages(frozenset({A}), {}, ks=cutoffs)

    def test_rejects_invalid_stage_inputs(self):
        invalid = (
            {"status": "error"}, {"status": True}, {"rows": []},
            {"rows": ({A},)}, {"rows": (frozenset({("doc", "block", 3)}),)},
            {"reason": "provider_error"}, {"status": "unavailable", "reason": " "},
            {"status": "unavailable", "reason": 3},
            {"status": "unavailable", "rows": (frozenset({A}),)},
        )
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValueError):
                StageInput(**values)
        for stages in ([], {"unknown": StageInput()}, {"fusion": {}}, {True: StageInput()}):
            with self.subTest(stages=stages), self.assertRaises(ValueError):
                score_stages(frozenset({A}), stages)
        for name in ("missing", True, None):
            with self.subTest(name=name), self.assertRaises(ValueError):
                score_stages(frozenset({A}), {}, pre_context_stage=name)


if __name__ == "__main__":
    unittest.main()
