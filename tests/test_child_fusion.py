from dataclasses import replace
import unittest
from midprojectrag.evidence.builder import build_store
from midprojectrag.retrieval.contracts import Candidate, SearchResult
from midprojectrag.retrieval.fusion import HybridChildRetriever, fuse_rrf
from midprojectrag.runtime_integrity import ResolvedScope
from tests.test_evidence_builder import chunk


class ChildFusionTests(unittest.TestCase):
    def setUp(self):
        self.store = build_store([chunk("a"), chunk("b", block="block_" + "c" * 24, doc="doc_" + "d" * 24)])
        self.rows = self.store.candidates()

    def result(self, lane, rows):
        return SearchResult(tuple(Candidate(e.evidence_id, e.doc_id, 1.0, lane, i) for i, e in enumerate(rows, 1)),
                            {"granularity": "child", "bundle_sha256": self.store.bundle_sha256})

    def test_lexical_only_rescue_and_rrf_formula(self):
        dense = self.result("dense", self.rows[:1])
        lexical = self.result("lexical", self.rows[::-1])
        result = fuse_rrf(dense, lexical, self.store)
        self.assertEqual(len(result.candidates), 2)
        self.assertEqual(result.trace["lexical_only"], (self.rows[1].evidence_id,))
        self.assertEqual(result.trace["duplicate_count"], 1)
        self.assertEqual(result.trace["distinct_doc_count"], 2)
        self.assertAlmostEqual(result.candidates[0].score, 1/61 + 1/62)

    def test_mixed_granularity_refused(self):
        dense = self.result("dense", self.rows[:1])
        invalid = SearchResult((replace(dense.candidates[0], granularity="page"),), dense.trace)
        with self.assertRaises(ValueError):
            fuse_rrf(invalid, self.result("lexical", ()), self.store)

    def test_lane_budgets_independent_and_empty_has_no_lane_call(self):
        calls = []
        outer = self
        class Lane:
            def __init__(self, name): self.name = name
            def search(self, query, limit, *, allowed_doc_ids):
                calls.append((self.name, limit, allowed_doc_ids))
                return outer.result(self.name, ())
        hybrid = HybridChildRetriever(self.store, Lane("dense"), Lane("lexical"))
        hybrid.search("q", dense_k=30, lexical_k=50, scope=ResolvedScope())
        self.assertEqual(calls, [("dense", 30, None), ("lexical", 50, None)])
        hybrid.search("q", dense_k=30, lexical_k=50, scope=ResolvedScope.from_allowed(frozenset()))
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
