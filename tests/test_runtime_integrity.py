"""Runtime requests must not depend on evaluator-only labels or mutable inputs."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
import unittest

from midprojectrag.runtime_integrity import (
    EvaluationCase, IntegrityError, RuntimeRequest, project_runtime,
    MetadataPredicate, ResolvedScope, scoped_search,
)


def request(**updates):
    value = {"request_id": "test-1", "question": "어떤 사업인가요?"}
    value.update(updates)
    return value


class RuntimeIntegrityTests(unittest.TestCase):
    def test_default_scope_is_all_and_evaluator_is_separate(self):
        case = EvaluationCase.from_dict({**request(), "required_doc_ids": ["gold-only"]})
        self.assertIsInstance(case.runtime, RuntimeRequest)
        self.assertEqual(case.required_doc_ids, ("gold-only",))
        self.assertEqual(case.runtime.to_dict()["document_scope"], {"mode": "all", "doc_ids": []})
        self.assertNotIn("gold-only", json.dumps(case.runtime.to_dict()))

    def test_direct_runtime_rejects_extra_fields(self):
        for key in ("gold", "qrels", "expected", "reference_answer", "required_doc_ids"):
            with self.subTest(key=key), self.assertRaises(IntegrityError):
                RuntimeRequest.from_dict(request(**{key: "sentinel"}))

    def test_no_scope_fallback_from_any_evaluator_field(self):
        for key in ("scope_doc_ids", "required_doc_ids", "expected_doc_ids", "absence_scope_doc_ids"):
            with self.subTest(key=key):
                runtime = project_runtime(request(**{key: ["sentinel"]}))
                self.assertEqual(runtime.to_dict()["document_scope"]["mode"], "all")
                self.assertNotIn("sentinel", json.dumps(runtime.to_dict()))

    def test_gold_metamorphic_runtime_bytes_and_hash_unchanged(self):
        original = request(required_doc_ids=["gold-A"], qrels={"ev-A": 3},
                           reference_answer="answer-A", expected={"scope": ["secret-A"]})
        changed = request(required_doc_ids=["gold-B"], qrels={"ev-B": 0},
                          reference_answer="answer-B", expected={"scope": ["secret-B"]})
        a, b = project_runtime(original), project_runtime(changed)
        self.assertEqual(a.to_dict(), b.to_dict())
        self.assertEqual(a.fingerprint, b.fingerprint)

    def test_real_user_scope_may_coincide_with_gold_value(self):
        runtime = project_runtime(request(document_scope={"mode": "explicit", "doc_ids": ["doc-A"]},
                                          required_doc_ids=["doc-A"]))
        self.assertEqual(runtime.to_dict()["document_scope"]["doc_ids"], ["doc-A"])

    def test_closed_nested_schemas(self):
        for extra in (
            {"options": {"expected": "answer"}},
            {"history": [{"role": "user", "content": "질문", "gold": {"answer": 1}}]},
            {"document_scope": {"mode": "all", "doc_ids": [], "required_doc_ids": ["hidden"]}},
            {"prior_citation_state": {"expected_doc_ids": ["hidden"]}},
            {"metadata_filters": [{"field": "agency", "operator": "eq", "value": {"gold": "hidden"}}]},
        ):
            with self.subTest(extra=extra), self.assertRaises(IntegrityError):
                project_runtime(request(**extra))

    def test_deeply_immutable_snapshot_and_fresh_serialization(self):
        raw = request(document_scope={"mode": "explicit", "doc_ids": ["doc-A"]},
                      history=[{"role": "assistant", "content": "답변", "cited_doc_ids": ["doc-A"]}])
        before = deepcopy(raw)
        runtime = project_runtime(raw)
        raw["document_scope"]["doc_ids"].append("doc-B")
        serialized = runtime.to_dict()
        serialized["history"][0]["cited_doc_ids"].append("doc-B")
        self.assertEqual(runtime.to_dict()["document_scope"], before["document_scope"])
        self.assertEqual(runtime.to_dict()["history"], before["history"])
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            runtime.question = "changed"
        with self.assertRaises(TypeError):
            runtime.document_scope["mode"] = "all"

    def test_projection_does_not_mutate_evaluation_case(self):
        raw = request(gold={"reference_answer": "secret"})
        saved = deepcopy(raw)
        project_runtime(raw)
        self.assertEqual(raw, saved)

    def test_malformed_runtime_types_fail(self):
        for values in ({"question": 3}, {"question": " "}, {"options": {"max_citations": True}},
                       {"history": "not-list"}, {"document_scope": {"mode": "all", "doc_ids": ["x"]}}):
            with self.subTest(values=values), self.assertRaises(IntegrityError):
                project_runtime(request(**values))

    def test_scope_three_states_and_zero_matches(self):
        for ids, state in ((None, "unfiltered"), (frozenset(), "empty"), (frozenset({"A"}), "restricted")):
            scope = ResolvedScope.from_allowed(ids)
            self.assertEqual(scope.state, state)
            self.assertEqual(scope.allowed_doc_ids, ids)
        self.assertEqual(ResolvedScope().intersect(frozenset()).state, "empty")
        empty = ResolvedScope.from_allowed(frozenset())
        self.assertEqual(empty.intersect(frozenset({"A"})).state, "empty")
        self.assertIs(empty.intersect(None), empty)

    def test_explicit_empty_is_not_all(self):
        runtime = project_runtime(request(document_scope={"mode": "explicit", "doc_ids": []}))
        scope = ResolvedScope.from_request(runtime)
        self.assertEqual(scope.state, "empty")
        self.assertEqual(scope.origin, "user_explicit")

    def test_empty_does_not_call_any_lane_or_embedder(self):
        def forbidden(*args, **kwargs):
            self.fail("empty filter performed search")
        empty = ResolvedScope.from_allowed(frozenset())
        for lane in ("dense", "lexical", "legacy"):
            with self.subTest(lane=lane):
                self.assertEqual(scoped_search(forbidden, "query", limit=30, scope=empty), ())

    def test_scope_is_forwarded_exactly(self):
        calls = []
        def capture(query, **kwargs):
            calls.append((query, kwargs))
            return ("candidate",)
        for ids in (None, frozenset({"A"})):
            scope = ResolvedScope.from_allowed(ids)
            self.assertEqual(scoped_search(capture, "query", limit=3, scope=scope), ("candidate",))
            self.assertEqual(calls[-1][1], {"limit": 3, "allowed_doc_ids": ids})

    def test_inconsistent_scope_fails(self):
        for state, ids in (("unfiltered", frozenset({"A"})), ("restricted", frozenset()), ("empty", frozenset({"A"}))):
            with self.subTest(state=state), self.assertRaises(IntegrityError):
                ResolvedScope(state, ids)

    def test_predicate_supported_vs_unresolved_vs_unsupported(self):
        for field, op, value, status in (
            ("agency", "eq", "기관", "supported"),
            ("business_amount", "ge", 100, "supported"),
            ("region_inferred", "eq", "서울", "unsupported_filter"),
            ("agency", "semantic_similarity", "기관", "unsupported_filter"),
            ("business_amount", "between", [10], "unresolved_constraint"),
            ("urgent", "eq", "yes", "unresolved_constraint"),
            ("business_amount", "ge", "banana", "unresolved_constraint"),
            ("business_amount", "between", [True, None], "unresolved_constraint"),
            ("business_amount", "between", [200, 100], "unresolved_constraint"),
            ("published_at", "ge", "not-a-date", "unresolved_constraint"),
            ("agency", "in", [None], "unresolved_constraint"),
        ):
            with self.subTest(field=field, op=op):
                p = MetadataPredicate(field, op, value)
                self.assertEqual(p.status, status)
                self.assertEqual(p.to_dict()["status"], status)

    def test_scope_and_filter_values_not_derived_from_gold(self):
        for gold_id in ("secret-A", "secret-B"):
            runtime = project_runtime(request(expected={"filters": [{"field": "doc_id", "value": gold_id}]}))
            self.assertEqual(runtime.metadata_filters, ())
            self.assertEqual(ResolvedScope.from_request(runtime).to_dict(),
                             {"state": "unfiltered", "doc_ids": [], "origin": "all"})


if __name__ == "__main__":
    unittest.main()
