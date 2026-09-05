from copy import deepcopy
from itertools import permutations
import unittest

from midprojectrag.stage_metrics import StageInput, score_stages
from midprojectrag.stage_ranking import score_rankings

A, B, X = ("doc-a", "block-a", "hash-a"), ("doc-b", "block-b", "hash-b"), ("doc-x", "block-x", "hash-x")


class StageRankingTests(unittest.TestCase):
    def score(self, rows, **kwargs):
        stages = {"lane_dense": StageInput(tuple(frozenset(row) for row in rows))}
        return score_rankings(frozenset({A, B}), stages, required_doc_ids=frozenset({"doc-a", "doc-b"}),
                              document_status="ready", **kwargs)

    def metric(self, scores, unit="source_anchor", k=10, metric="ndcg"):
        return scores[unit]["lane_dense"][str(k)][metric]

    def test_full_gold_denominator_not_only_retrieved_gold(self):
        self.assertAlmostEqual(self.metric(self.score([{A}]))["value"], 0.6131471927654584)
        self.assertEqual(self.metric(self.score([{A}, {B}]))["value"], 1)

    def test_duplicates_compress_unique_ranking_without_changing_raw_recall(self):
        stages = {"lane_dense": StageInput((frozenset({A}), frozenset({A}), frozenset({B})))}
        before = deepcopy(stages)
        raw = score_stages(frozenset({A, B}), stages, ks=(2,), pre_context_stage="lane_dense")
        ranking = score_rankings(frozenset({A, B}), stages, ks=(2,))
        self.assertEqual(raw["stage_recall"]["lane_dense"]["2"]["value"], .5)
        self.assertEqual(self.metric(ranking, k=2)["value"], 1)
        self.assertEqual(stages, before)

    def test_grouped_anchor_rank_not_fabricated_document_can_still_be_known(self):
        same_doc = (A[0], "another-block", "another-hash")
        scores = self.score([{A, same_doc}])
        self.assertEqual(self.metric(scores)["reason"], "grouped_source_anchor_rank")
        self.assertIsNone(self.metric(scores)["value"])
        self.assertAlmostEqual(self.metric(scores, "document")["value"], .6131471927654584)
        self.assertEqual(self.metric(self.score([{A, B}]), "document")["reason"], "grouped_document_rank")

    def test_document_gold_independent_of_anchor_gold(self):
        result = score_rankings(frozenset({A}), {"lane_dense": StageInput((frozenset({A}),))},
                                required_doc_ids=frozenset({"doc-a", "doc-b"}), document_status="ready")
        self.assertEqual(self.metric(result)["value"], 1)
        self.assertAlmostEqual(self.metric(result, "document")["value"], .6131471927654584)

    def test_empty_executed_is_zero_but_missing_is_null(self):
        self.assertEqual(self.metric(self.score([]))["value"], 0)
        result = score_rankings(frozenset({A}), {})
        self.assertIsNone(self.metric(result)["value"])
        self.assertIsNone(self.metric(result, "document")["value"])
        self.assertEqual(self.metric(self.score([set()]))["reason"], "unresolved_empty_rank_row")

    def test_source_missing_does_not_hide_document_ready(self):
        result = score_rankings(frozenset(), {"lane_dense": StageInput((frozenset({A}),))}, source_status="missing",
                                required_doc_ids=frozenset({"doc-a"}), document_status="ready")
        self.assertIsNone(self.metric(result)["value"])
        self.assertEqual(self.metric(result, "document")["value"], 1)
        na = score_rankings(frozenset(), {}, source_status="not_applicable", document_status="not_applicable")
        self.assertEqual(self.metric(na)["status"], "not_applicable")

    def test_rr_cutoff_and_score_bounds(self):
        result = self.score([{X}, {A}, {B}])
        self.assertEqual(self.metric(result, k=1, metric="rr")["value"], 0)
        self.assertEqual(self.metric(result, metric="rr")["value"], .5)
        for items in permutations([A, A, B, X]):
            result = self.score([{a} for a in items])
            for unit in result.values():
                for at_k in unit["lane_dense"].values():
                    for value in at_k.values():
                        self.assertLessEqual(0, value["value"])
                        self.assertLessEqual(value["value"], 1)

    def test_invalid_inputs_refused(self):
        for kwargs in ({"ks": (True,)}, {"ks": (0,)}, {"ks": (1, 1)}, {"source_status": "missing"}):
            with self.assertRaises(ValueError): self.score([{A}], **kwargs)
        with self.assertRaises(ValueError):
            score_rankings(frozenset({A}), {}, required_doc_ids=frozenset({"doc-a"}), document_status="missing")


if __name__ == "__main__":
    unittest.main()
