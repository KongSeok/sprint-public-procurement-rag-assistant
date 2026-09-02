from __future__ import annotations

import math
import unittest
from dataclasses import FrozenInstanceError

import numpy as np

from midprojectrag.evidence import Evidence, EvidenceStore
from midprojectrag.retrieval import (
    BM25Retriever,
    Candidate,
    DenseRetriever,
    HybridRetriever,
    IdentityReranker,
    select_context,
    validate_reranked,
)


def _fixture():
    records = []
    children = []
    for doc_id, texts in (
        ("doc_a", ("alpha budget 100", "alpha schedule")),
        ("doc_b", ("beta budget 200", "beta deadline")),
        ("doc_c", ("gamma contract",)),
    ):
        page = Evidence.create(
            doc_id=doc_id,
            page=1,
            kind="page",
            text="\n".join(texts),
            source_block_ids=(f"block_{doc_id}",),
        )
        records.append(page)
        for text in texts:
            child = Evidence.create(
                doc_id=doc_id,
                page=1,
                kind="text",
                text=text,
                source_block_ids=(f"block_{doc_id}",),
                parent_id=page.evidence_id,
            )
            records.append(child)
            children.append(child)
    return EvidenceStore(records), tuple(children)


class _Lane:
    def __init__(self, hits):
        self.hits = hits
        self.calls = []

    def search(self, query, *, limit, allowed_doc_ids=None):
        self.calls.append((query, limit, allowed_doc_ids))
        return self.hits


class CandidateTests(unittest.TestCase):
    def test_candidate_is_frozen(self):
        candidate = Candidate("ev_a", 0.5, "dense", 1)
        with self.assertRaises(FrozenInstanceError):
            candidate.rank = 2

    def test_invalid_scalar_contracts_fail(self):
        for field, value in (
            ("evidence_id", ""), ("evidence_id", []),
            ("score", float("nan")), ("score", float("inf")),
            ("score", True), ("score", "0.5"),
            ("rank", 0), ("rank", True), ("rank", 1.5),
            ("lane", ""), ("lane", []),
        ):
            with self.subTest(field=field, value=value):
                args = dict(evidence_id="ev_a", score=0.5, lane="dense", rank=1)
                args[field] = value
                with self.assertRaises(ValueError):
                    Candidate(**args)


class LexicalTests(unittest.TestCase):
    def setUp(self):
        self.store, self.rows = _fixture()
        self.ids = tuple(row.evidence_id for row in self.rows)
        self.retriever = BM25Retriever(self.store, evidence_ids=self.ids)

    def test_bm25_ranks_matching_children_only(self):
        hits = self.retriever.search("budget", limit=3)
        self.assertEqual({hit.evidence_id for hit in hits}, {self.ids[0], self.ids[2]})
        self.assertEqual([hit.rank for hit in hits], [1, 2])
        self.assertTrue(all(hit.score > 0 and hit.lane == "lexical" for hit in hits))

    def test_no_match_is_no_candidate_not_semantic_abstention(self):
        self.assertEqual(self.retriever.search("absent", limit=2), ())
        self.assertEqual(self.retriever.search("!!!", limit=2), ())

    def test_scope_and_empty_scope(self):
        hits = self.retriever.search("budget", limit=3, allowed_doc_ids=frozenset({"doc_b"}))
        self.assertEqual([hit.evidence_id for hit in hits], [self.ids[2]])
        self.assertEqual(self.retriever.search("budget", limit=3, allowed_doc_ids=frozenset()), ())

    def test_unicode_compatibility_normalization(self):
        self.assertEqual(
            self.retriever.search("ＡＬＰＨＡ", limit=2),
            self.retriever.search("alpha", limit=2),
        )

    def test_query_word_repetition_does_not_inflate_score(self):
        self.assertEqual(
            self.retriever.search("budget budget", limit=2),
            self.retriever.search("budget", limit=2),
        )

    def test_rejects_invalid_params_and_index_ids(self):
        for kwargs in (
            {"k1": 0}, {"k1": float("inf")}, {"b": 1.1}, {"b": True},
            {"evidence_ids": [self.ids[0], self.ids[0]]},
            {"evidence_ids": "ev_a"}, {"evidence_ids": [[]]},
            {"evidence_ids": ["unknown"]},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                BM25Retriever(self.store, **kwargs)

    def test_all_records_default_and_empty_selection_are_explicit(self):
        all_hits = BM25Retriever(self.store).search("alpha", limit=10)
        self.assertEqual(len(all_hits), 3)
        self.assertEqual(BM25Retriever(self.store, evidence_ids=()).search("alpha", limit=1), ())

    def test_invalid_query_limit_scope_fail(self):
        for query, limit, scope in (("", 2, None), ("x", True, None), ("x", 2, {"doc_a"}), ("x", 2, frozenset({1}))):
            with self.subTest(query=query, limit=limit, scope=scope), self.assertRaises(ValueError):
                self.retriever.search(query, limit=limit, allowed_doc_ids=scope)


class DenseTests(unittest.TestCase):
    def setUp(self):
        self.store, self.rows = _fixture()
        self.ids = tuple(row.evidence_id for row in self.rows[:3])
        self.calls = []

    def _embed(self, query):
        self.calls.append(query)
        return (1, 0)

    def test_cosine_alignment_and_late_query_call(self):
        retriever = DenseRetriever(self.store, ((4, 0), (1, 1), (-1, 0)), self._embed, evidence_ids=self.ids)
        self.assertEqual(self.calls, [])
        hits = retriever.search("budget", limit=3)
        self.assertEqual([hit.evidence_id for hit in hits], list(self.ids))
        self.assertEqual([hit.rank for hit in hits], [1, 2, 3])
        self.assertAlmostEqual(hits[1].score, 1 / math.sqrt(2))
        self.assertEqual(self.calls, ["budget"])

    def test_numpy_vectors_are_supported_without_new_provider(self):
        vectors = np.asarray([[1, 0], [0, 1], [-1, 0]], dtype=np.float32)
        retriever = DenseRetriever(self.store, vectors, lambda query: np.asarray([1, 0], dtype=np.float32), evidence_ids=self.ids)
        self.assertEqual(retriever.search("x", limit=1)[0].evidence_id, self.ids[0])

    def test_scope_excluded_rows_and_empty_scope_avoid_embedding(self):
        retriever = DenseRetriever(self.store, ((1, 0), (1, 1), (0, 1)), self._embed, evidence_ids=self.ids)
        self.assertEqual(retriever.search("x", limit=1, allowed_doc_ids=frozenset()), ())
        self.assertEqual(retriever.search("x", limit=1, allowed_doc_ids=frozenset({"absent"})), ())
        self.assertEqual(self.calls, [])
        hits = retriever.search("x", limit=3, allowed_doc_ids=frozenset({"doc_b"}))
        self.assertEqual([hit.evidence_id for hit in hits], [self.ids[2]])

    def test_finite_extreme_vectors_normalize_without_overflow(self):
        retriever = DenseRetriever(self.store, ((1e308, 1e308),), lambda query: (1e-320, 1e-320), evidence_ids=self.ids[:1])
        self.assertAlmostEqual(retriever.search("x", limit=1)[0].score, 1)

    def test_bad_alignment_and_vectors_fail(self):
        for vectors in ((), ((1, 0),), ((1, 0), (1,), (0, 1)), ((0, 0), (1, 0), (0, 1)), ((float("nan"), 0), (1, 0), (0, 1)), ((True, 0), (1, 0), (0, 1)), "bad"):
            with self.subTest(vectors=vectors), self.assertRaises(ValueError):
                DenseRetriever(self.store, vectors, self._embed, evidence_ids=self.ids)

    def test_bad_embedder_and_query_vectors_fail(self):
        with self.assertRaisesRegex(ValueError, "invalid_query_embedder"):
            DenseRetriever(self.store, ((1, 0),), None, evidence_ids=self.ids[:1])
        for vector in ((1,), (0, 0), (float("inf"), 0), "invalid", (True, 1), (value for value in (1, 2))):
            with self.subTest(vector=vector):
                retriever = DenseRetriever(self.store, ((1, 0),), lambda query: vector, evidence_ids=self.ids[:1])
                with self.assertRaisesRegex(ValueError, "invalid_query_vector"):
                    retriever.search("x", limit=1)


class HybridTests(unittest.TestCase):
    def setUp(self):
        self.store, self.rows = _fixture()
        self.a, self.b, self.c = (self.rows[index].evidence_id for index in (0, 2, 4))

    def test_rrf_boosts_cross_lane_hits_and_stable_tie(self):
        dense = _Lane((Candidate(self.a, 0.9, "dense", 1), Candidate(self.b, 0.1, "dense", 2)))
        lexical = _Lane((Candidate(self.b, 5.0, "lexical", 1), Candidate(self.c, 3.0, "lexical", 2)))
        retriever = HybridRetriever(self.store, {"lexical": lexical, "dense": dense})
        result = retriever.search_with_lanes("x", limit=3)
        self.assertEqual(result.candidates[0].evidence_id, self.b)
        self.assertAlmostEqual(result.candidates[0].score, 1 / 61 + 1 / 62)
        self.assertEqual([lane for lane, hits in result.by_lane], ["dense", "lexical"])
        self.assertEqual([hit.rank for hit in result.candidates], [1, 2, 3])
        self.assertTrue(all(hit.lane == "hybrid" for hit in result.candidates))

    def test_duplicate_per_lane_contributes_only_once(self):
        lane = _Lane((Candidate(self.a, 3, "dense", 1), Candidate(self.a, 2, "dense", 2), Candidate(self.b, 1, "dense", 3)))
        result = HybridRetriever(self.store, {"dense": lane}).search_with_lanes("x", limit=3)
        self.assertAlmostEqual(result.candidates[0].score, 1 / 61)
        self.assertAlmostEqual(result.candidates[1].score, 1 / 62)
        self.assertEqual(len(result.by_lane[0][1]), 2)

    def test_scope_is_reapplied_before_rank_even_for_buggy_lane(self):
        lane = _Lane((Candidate(self.a, 1, "dense", 1), Candidate(self.b, 0.8, "dense", 2)))
        scope = frozenset({"doc_b"})
        result = HybridRetriever(self.store, {"dense": lane}).search_with_lanes("x", limit=2, allowed_doc_ids=scope)
        self.assertEqual([hit.evidence_id for hit in result.candidates], [self.b])
        self.assertAlmostEqual(result.candidates[0].score, 1 / 61)
        self.assertEqual(lane.calls, [("x", 2, scope)])
        self.assertEqual(result.by_lane[0][1][0].rank, 1)

    def test_unknown_evidence_fails_even_if_adapter_ignores_scope(self):
        lane = _Lane((Candidate("ev_unknown", 1, "dense", 1),))
        with self.assertRaises(ValueError):
            HybridRetriever(self.store, {"dense": lane}).search("x", limit=1, allowed_doc_ids=frozenset({"doc_a"}))

    def test_wrong_lane_overlong_or_mutable_results_fail(self):
        for hits, limit in (
            ((Candidate(self.a, 1, "visual", 1),), 1),
            ((Candidate(self.a, 1, "dense", 1), Candidate(self.b, 1, "dense", 2)), 1),
            ([Candidate(self.a, 1, "dense", 1)], 1),
        ):
            with self.subTest(hits=hits), self.assertRaises(ValueError):
                HybridRetriever(self.store, {"dense": _Lane(hits)}).search("x", limit=limit)

    def test_empty_scope_calls_no_lane(self):
        lane = _Lane(())
        result = HybridRetriever(self.store, {"dense": lane}).search_with_lanes("x", limit=1, allowed_doc_ids=frozenset())
        self.assertEqual(result.candidates, ())
        self.assertEqual(result.by_lane, (("dense", ()),))
        self.assertEqual(lane.calls, [])

    def test_stable_tie_ignores_lane_mapping_order(self):
        dense = _Lane((Candidate(self.a, 1, "dense", 1),))
        visual = _Lane((Candidate(self.b, 1, "visual", 1),))
        first = HybridRetriever(self.store, {"dense": dense, "visual": visual}).search("x", limit=2)
        second = HybridRetriever(self.store, {"visual": visual, "dense": dense}).search("x", limit=2)
        self.assertEqual(first, second)
        self.assertEqual([hit.evidence_id for hit in first], sorted((self.a, self.b)))

    def test_optional_visual_is_generic_lane_not_implicit_load(self):
        visual = _Lane((Candidate(self.c, 0.7, "visual", 1),))
        self.assertEqual(HybridRetriever(self.store, {"visual": visual}).search("figure", limit=1)[0].evidence_id, self.c)

    def test_bad_hybrid_configuration_fails(self):
        for lanes, rrf_k in (({}, 60), ({"": _Lane(())}, 60), ({"dense": object()}, 60), ({"dense": _Lane(())}, True), ({"dense": _Lane(())}, 0)):
            with self.subTest(lanes=lanes, rrf_k=rrf_k), self.assertRaises(ValueError):
                HybridRetriever(self.store, lanes, rrf_k=rrf_k)


class RerankerAndContextTests(unittest.TestCase):
    def setUp(self):
        self.store, self.rows = _fixture()
        self.candidates = tuple(Candidate(row.evidence_id, 1 / rank, "hybrid", rank) for rank, row in enumerate(self.rows, 1))

    def _context(self, **kwargs):
        params = dict(max_chars=1000, max_items=5, per_doc_limit=3)
        params.update(kwargs)
        return select_context(self.store, self.candidates, **params)

    def test_identity_is_marked_nonlearned_and_preserves_result(self):
        reranker = IdentityReranker()
        self.assertFalse(reranker.is_learned)
        self.assertEqual(reranker.policy_id, "identity-reranker-v1")
        self.assertIs(reranker.rerank("x", self.candidates), self.candidates)

    def test_reranker_cannot_insert_or_duplicate_evidence(self):
        for reranked in ((Candidate("unknown", 1, "rerank", 1),), (self.candidates[0], self.candidates[0])):
            with self.subTest(reranked=reranked), self.assertRaises(ValueError):
                validate_reranked(self.candidates, reranked)
        self.assertEqual(validate_reranked(self.candidates, self.candidates[:1]), self.candidates[:1])

    def test_round_robin_document_coverage_before_second_item(self):
        context = self._context(max_items=3)
        self.assertEqual([row.doc_id for row in context], ["doc_a", "doc_b", "doc_c"])

    def test_per_document_limit(self):
        self.assertEqual(len(self._context(per_doc_limit=1)), 3)

    def test_reranked_tuple_order_is_not_undone_by_original_rank_fields(self):
        reversed_candidates = tuple(reversed(self.candidates))
        context = select_context(self.store, reversed_candidates, max_chars=1000, max_items=1, per_doc_limit=1)
        self.assertEqual(context[0].evidence_id, self.rows[-1].evidence_id)

    def test_mandatory_refs_are_first_and_deduplicated(self):
        required = self.rows[3].evidence_id
        context = self._context(required_ids=(required, required), max_items=3)
        self.assertEqual(context[0].evidence_id, required)
        self.assertEqual([row.doc_id for row in context], ["doc_b", "doc_a", "doc_c"])

    def test_mandatory_prior_round_ref_not_in_current_candidates_is_retained(self):
        required = self.rows[-1].evidence_id
        context = select_context(self.store, self.candidates[:1], max_chars=1000, max_items=2, per_doc_limit=1, required_ids=(required,))
        self.assertEqual([row.evidence_id for row in context], [required, self.rows[0].evidence_id])

    def test_mandatory_budget_failure_is_explicit(self):
        for overrides in (
            dict(max_chars=1), dict(max_items=1), dict(per_doc_limit=1),
        ):
            with self.subTest(overrides=overrides), self.assertRaisesRegex(ValueError, "context_budget_exceeded"):
                self._context(required_ids=tuple(row.evidence_id for row in self.rows[:2]), **overrides)

    def test_optional_oversized_evidence_is_skipped_never_truncated(self):
        context = self._context(max_chars=14)
        self.assertEqual(len(context), 1)
        self.assertEqual(context[0].text, "alpha schedule")

    def test_unknown_ids_fail_even_when_context_would_already_be_full(self):
        bad = self.candidates + (Candidate("ev_unknown", 0, "dense", 99),)
        with self.assertRaises(ValueError):
            select_context(self.store, bad, max_chars=1, max_items=1, per_doc_limit=1)
        with self.assertRaises(ValueError):
            self._context(required_ids=("ev_unknown",))

    def test_bad_budget_types_and_nested_ids_fail(self):
        for overrides in (
            dict(max_items=True), dict(max_chars=0), dict(per_doc_limit=1.1),
            dict(required_ids="ev_a"), dict(required_ids=([],)),
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self._context(**overrides)


if __name__ == "__main__":
    unittest.main()
