from dataclasses import FrozenInstanceError, replace
import unittest

from midprojectrag.evidence import Evidence, EvidenceStore, Locator, ProvenanceParent
from midprojectrag.orchestration import (
    BoundFollowup,
    CatalogEntity,
    DeterministicPlanner,
    FollowupEvidencePolicy,
    FollowupRetrievalAttempt,
    FollowupRetrievalOutcome,
    PlanningCatalog,
    PrimaryEvidenceProgress,
    VerifiedCitationState,
    bind_primary_evidence_progress,
    bind_followup,
    default_rule_registry,
    finalize_followup_retrieval,
    retrieve_followup_primary,
)
from midprojectrag.retrieval import Candidate, SearchResult
from midprojectrag.runtime_integrity import EvaluationCase, RuntimeRequest, project_runtime


def _evidence_store():
    parents = []
    evidence = []
    for page, doc_id, text in (
        (1, "doc-a", "alpha evidence"),
        (2, "doc-b", "beta evidence"),
    ):
        parent = ProvenanceParent(
            doc_id,
            "pdf_page",
            text,
            (f"block-{doc_id}",),
            Locator(page=page),
        )
        child = Evidence(
            doc_id,
            "text",
            text,
            parent.parent_id,
            (f"block-{doc_id}",),
            Locator(page=page, char_range=(0, len(text))),
        )
        parents.append(parent)
        evidence.append(child)
    return EvidenceStore(parents, evidence), tuple(evidence)


def _prior(doc_ids, evidence_ids, *, resolved=(), listed=(), compared=()):
    return {
        "cited_doc_ids": list(doc_ids),
        "cited_evidence_ids": list(evidence_ids),
        "resolved_entities": list(resolved),
        "list_doc_ids": list(listed),
        "comparison_doc_ids": list(compared),
    }


def _assistant_turn(doc_ids, evidence_ids):
    return {
        "turn_id": "assistant-1",
        "role": "assistant",
        "content": "근거가 있는 이전 답변",
        "cited_doc_ids": list(doc_ids),
        "cited_evidence_ids": list(evidence_ids),
    }


def _result(store, evidence=(), *, bundle=None, trace_granularity="child", ranks=None,
            candidate_granularity="child", doc_overrides=None):
    ranks = tuple(range(1, len(evidence) + 1)) if ranks is None else tuple(ranks)
    doc_overrides = {} if doc_overrides is None else doc_overrides
    candidates = tuple(
        Candidate(
            item.evidence_id,
            doc_overrides.get(item.evidence_id, item.doc_id),
            1.0 / rank,
            "rrf",
            rank,
            candidate_granularity,
        )
        for item, rank in zip(evidence, ranks)
    )
    return SearchResult(
        candidates,
        {
            "lane": "rrf",
            "granularity": trace_granularity,
            "bundle_sha256": store.bundle_sha256 if bundle is None else bundle,
        },
    )


class _FakeRetriever:
    def __init__(self, *outcomes):
        self.outcomes = outcomes
        self.calls = []

    def search(self, query, *, dense_k, lexical_k, scope):
        self.calls.append(
            {
                "query": query,
                "dense_k": dense_k,
                "lexical_k": lexical_k,
                "scope": scope,
            }
        )
        outcome = self.outcomes[len(self.calls) - 1]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class ActualCitationFollowupTests(unittest.TestCase):
    def setUp(self):
        self.store, (self.ev_a, self.ev_b) = _evidence_store()
        self.registry = default_rule_registry()
        self.catalog = PlanningCatalog.synthetic(
            "followup-fixture-v1",
            (
                CatalogEntity(
                    "예약발매시스템",
                    "예약발매시스템",
                    "business",
                    ("doc-a",),
                    "business_alias",
                ),
                CatalogEntity(
                    "다른사업",
                    "다른사업",
                    "business",
                    ("doc-b",),
                    "business_alias",
                ),
            ),
        )
        self.planner = DeterministicPlanner.for_test(self.registry, self.catalog)

    def request(
        self,
        *,
        question="그 사업의 기간은?",
        cited_docs=("doc-a",),
        cited_evidence=None,
        history_docs=None,
        history_evidence=None,
        document_scope=None,
        resolved=(),
        listed=("doc-b",),
        compared=("doc-b",),
        allow_fallback=True,
        include_assistant=True,
    ):
        cited_evidence = (
            (self.ev_a.evidence_id,)
            if cited_evidence is None
            else tuple(cited_evidence)
        )
        history_docs = tuple(cited_docs) if history_docs is None else tuple(history_docs)
        history_evidence = (
            cited_evidence if history_evidence is None else tuple(history_evidence)
        )
        history = (
            (_assistant_turn(history_docs, history_evidence),)
            if include_assistant
            else (
                {
                    "turn_id": "user-1",
                    "role": "user",
                    "content": "이전 질문",
                    "cited_doc_ids": [],
                    "cited_evidence_ids": [],
                },
            )
        )
        return RuntimeRequest(
            question=question,
            history=history,
            document_scope=(
                {"mode": "all", "doc_ids": []}
                if document_scope is None
                else document_scope
            ),
            options={"allow_global_fallback": allow_fallback},
            prior_citation_state=_prior(
                cited_docs,
                cited_evidence,
                resolved=resolved,
                listed=listed,
                compared=compared,
            ),
        )

    def bind(self, request):
        return bind_followup(
            request,
            self.planner.plan(request),
            self.store,
            self.registry,
        )

    def test_valid_state_is_history_and_store_bound(self):
        request = self.request(resolved=("ignored-alias",))
        bound = self.bind(request)
        self.assertEqual(bound.plan.query_type, "follow_up")
        self.assertEqual(bound.plan.resolved_doc_ids, ("doc-a",))
        self.assertEqual(bound.plan.inherited_doc_ids, ("doc-a",))
        self.assertEqual(bound.plan.scope_origin, "followup_citations")
        self.assertTrue(bound.plan.allow_global_fallback)
        self.assertEqual(bound.citations.evidence_bundle_sha256, self.store.bundle_sha256)
        self.assertEqual(bound.trace.ignored_resolved_entity_count, 1)
        self.assertEqual(bound.trace.ignored_list_doc_count, 1)
        self.assertEqual(bound.trace.ignored_comparison_doc_count, 1)
        self.assertNotIn("question", bound.trace.to_dict())
        self.assertNotIn("gold", str(bound.trace.to_dict()).lower())

    def test_auxiliary_prior_fields_never_widen_scope(self):
        request = self.request(
            resolved=("doc-b",), listed=("doc-b",), compared=("doc-b",)
        )
        bound = self.bind(request)
        self.assertEqual(bound.plan.resolved_doc_ids, ("doc-a",))
        self.assertNotIn("doc-b", bound.plan.resolved_doc_ids)

    def test_user_scope_intersects_citations_and_disables_fallback(self):
        partial = self.bind(
            self.request(
                document_scope={"mode": "explicit", "doc_ids": ["doc-a", "doc-b"]}
            )
        )
        self.assertEqual(partial.plan.resolved_doc_ids, ("doc-a",))
        self.assertEqual(partial.plan.scope_origin, "user_explicit+followup_citations")
        self.assertFalse(partial.plan.allow_global_fallback)

        empty = self.bind(
            self.request(document_scope={"mode": "explicit", "doc_ids": ["doc-b"]})
        )
        self.assertEqual(empty.plan.scope_state, "empty")
        self.assertEqual(empty.plan.resolved_doc_ids, ())
        self.assertEqual(empty.plan.inherited_doc_ids, ())
        self.assertFalse(empty.plan.allow_global_fallback)

    def test_entity_scope_intersects_citations_and_empty_is_closed(self):
        request = self.request(question="그 사업, 다른사업의 기간은?")
        bound = self.bind(request)
        self.assertEqual(bound.plan.scope_state, "empty")
        self.assertEqual(bound.plan.scope_origin, "combined")
        self.assertEqual(bound.plan.resolved_doc_ids, ())
        self.assertFalse(bound.plan.allow_global_fallback)

    def test_metadata_filter_never_authorizes_global_fallback_before_filtering(self):
        base = self.request()
        request = RuntimeRequest(
            **{
                **base.to_dict(),
                "metadata_filters": [
                    {"field": "business_amount", "operator": "ge", "value": 1}
                ],
            }
        )
        bound = self.bind(request)
        self.assertEqual(bound.plan.scope_origin, "combined")
        self.assertEqual(bound.plan.resolved_doc_ids, ("doc-a",))
        self.assertFalse(bound.plan.allow_global_fallback)

    def test_latest_assistant_turn_must_hold_the_same_citations(self):
        request = self.request()
        payload = request.to_dict()
        payload["history"].append(
            {
                "turn_id": "assistant-2",
                "role": "assistant",
                "content": "인용이 없는 더 최근 응답",
                "cited_doc_ids": [],
                "cited_evidence_ids": [],
            }
        )
        changed = RuntimeRequest.from_dict(payload)
        self.assertEqual(self.planner.plan(changed).plan.query_type, "fact")

    def test_citation_state_hash_is_bound_to_request_and_source_turn(self):
        first = self.bind(self.request())
        changed = self.request()
        payload = changed.to_dict()
        payload["history"][0]["content"] = "내용이 바뀐 이전 답변"
        changed = RuntimeRequest.from_dict(payload)
        second = self.bind(changed)
        self.assertNotEqual(
            first.citations.source_turn_sha256,
            second.citations.source_turn_sha256,
        )
        self.assertNotEqual(first.citations.state_sha256, second.citations.state_sha256)

    def test_invalid_or_partial_citation_state_fails_closed(self):
        cases = (
            self.request(cited_docs=()),
            self.request(cited_evidence=()),
            self.request(cited_docs=("doc-b",)),
            self.request(cited_evidence=("ev_" + "0" * 64,)),
            self.request(history_docs=("doc-b",)),
            self.request(history_evidence=(self.ev_b.evidence_id,)),
            self.request(include_assistant=False),
        )
        for request in cases:
            with self.subTest(request=request), self.assertRaises(ValueError):
                self.bind(request)

    def test_only_followup_runtime_request_is_accepted(self):
        followup = self.request()
        evaluation_case = EvaluationCase(followup, required_doc_ids=("doc-b",))
        with self.assertRaisesRegex(TypeError, "runtime_request_required"):
            bind_followup(
                evaluation_case,
                self.planner.plan(followup),
                self.store,
                self.registry,
            )
        ordinary = self.request(question="새 사업의 기간은?")
        planning = self.planner.plan(ordinary)
        self.assertEqual(planning.plan.query_type, "fact")
        with self.assertRaisesRegex(ValueError, "followup_plan_required"):
            bind_followup(ordinary, planning, self.store, self.registry)

    def test_evaluator_fields_cannot_change_binding(self):
        request = self.request()
        runtime_fields = request.to_dict()
        row_a = {
            **runtime_fields,
            "required_doc_ids": ["doc-a"],
            "required_evidence_ids": [self.ev_a.evidence_id],
            "qrels": {self.ev_a.evidence_id: 1},
            "reference_answer": "secret-a",
            "expected": {"answer": "a"},
        }
        row_b = {
            **runtime_fields,
            "required_doc_ids": ["doc-b"],
            "required_evidence_ids": [self.ev_b.evidence_id],
            "qrels": {self.ev_b.evidence_id: 99},
            "reference_answer": "secret-b",
            "expected": {"answer": "b"},
        }
        runtime_a = project_runtime(row_a)
        runtime_b = project_runtime(row_b)
        self.assertEqual(runtime_a, runtime_b)
        self.assertEqual(self.bind(runtime_a).to_dict(), self.bind(runtime_b).to_dict())

    def test_state_is_immutable_and_serialization_is_detached(self):
        bound = self.bind(self.request())
        self.assertFalse(hasattr(bound, "__dict__"))
        self.assertFalse(hasattr(bound.citations, "__dict__"))
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            bound.citations.cited_doc_ids = ("doc-b",)
        payload = bound.to_dict()
        payload["citations"]["cited_doc_ids"].append("doc-b")
        self.assertEqual(bound.citations.cited_doc_ids, ("doc-a",))

    def test_verified_citation_state_requires_factory(self):
        with self.assertRaises(TypeError):
            VerifiedCitationState(
                ("doc-a",),
                (self.ev_a.evidence_id,),
                self.store.bundle_sha256,
                0,
                "0" * 64,
            )

    def test_bound_followup_requires_factory(self):
        bound = self.bind(self.request())
        with self.assertRaises(TypeError):
            BoundFollowup(bound.planning, bound.citations, bound.trace)

    def _primary(self, bound, retriever):
        return retrieve_followup_primary(
            bound=bound,
            store=self.store,
            registry=self.registry,
            retriever=retriever,
        )

    def _progress(self, bound, primary, verified=()):
        return bind_primary_evidence_progress(
            bound=bound,
            primary=primary,
            store=self.store,
            registry=self.registry,
            policy=FollowupEvidencePolicy.v1(),
            verified_answer_evidence_ids=tuple(verified),
            verifier_id="deterministic-evidence-verifier-v1",
            verifier_config_sha256="1" * 64,
        )

    def _finalize(self, bound, primary, progress, retriever):
        return finalize_followup_retrieval(
            bound=bound,
            primary=primary,
            progress=progress,
            store=self.store,
            registry=self.registry,
            policy=FollowupEvidencePolicy.v1(),
            retriever=retriever,
        )

    def test_primary_scope_budget_and_verified_sufficiency_are_bound(self):
        bound = self.bind(self.request())
        retriever = _FakeRetriever(_result(self.store, (self.ev_a,)))
        primary = self._primary(bound, retriever)
        self.assertEqual(len(retriever.calls), 1)
        call = retriever.calls[0]
        self.assertEqual(call["query"], bound.plan.normalized_query)
        self.assertEqual(call["dense_k"], bound.plan.dense_k)
        self.assertEqual(call["lexical_k"], bound.plan.lexical_k)
        self.assertEqual(call["scope"].state, "restricted")
        self.assertEqual(call["scope"].doc_ids, frozenset({"doc-a"}))
        progress = self._progress(bound, primary, (self.ev_a.evidence_id,))
        self.assertTrue(progress.sufficient)
        outcome = self._finalize(bound, primary, progress, retriever)
        self.assertEqual(len(retriever.calls), 1)
        self.assertIsNone(outcome.fallback)
        self.assertEqual(outcome.trace.reason, "primary_sufficient")
        self.assertFalse(outcome.trace.fallback_executed)

    def test_candidate_presence_is_not_sufficiency_and_authorized_fallback_runs_once(self):
        bound = self.bind(self.request())
        primary_result = _result(self.store, (self.ev_a,))
        fallback_result = _result(self.store, (self.ev_b,))
        retriever = _FakeRetriever(primary_result, fallback_result)
        primary = self._primary(bound, retriever)
        progress = self._progress(bound, primary)
        self.assertEqual(len(primary.result.candidates), 1)
        self.assertFalse(progress.sufficient)
        outcome = self._finalize(bound, primary, progress, retriever)
        self.assertEqual(len(retriever.calls), 2)
        self.assertEqual(retriever.calls[1]["scope"].state, "unfiltered")
        self.assertEqual(retriever.calls[1]["scope"].origin, "all")
        self.assertIs(outcome.primary, primary)
        self.assertEqual(outcome.fallback.result.candidates, fallback_result.candidates)
        self.assertEqual(
            outcome.fallback.result.trace["trace_projection"], "followup-safe-v1"
        )
        self.assertEqual(
            outcome.trace.reason,
            "primary_insufficient_global_fallback_executed",
        )

    def test_explicit_and_empty_scopes_never_run_global_fallback(self):
        explicit = self.bind(
            self.request(document_scope={"mode": "explicit", "doc_ids": ["doc-a"]})
        )
        explicit_retriever = _FakeRetriever(_result(self.store, (self.ev_a,)))
        primary = self._primary(explicit, explicit_retriever)
        outcome = self._finalize(
            explicit,
            primary,
            self._progress(explicit, primary),
            explicit_retriever,
        )
        self.assertEqual(len(explicit_retriever.calls), 1)
        self.assertIsNone(outcome.fallback)
        self.assertEqual(
            outcome.trace.reason,
            "primary_insufficient_fallback_not_authorized",
        )

        empty = self.bind(
            self.request(document_scope={"mode": "explicit", "doc_ids": ["doc-b"]})
        )
        empty_retriever = _FakeRetriever()
        empty_primary = self._primary(empty, empty_retriever)
        self.assertEqual(len(empty_retriever.calls), 0)
        self.assertFalse(empty_primary.retriever_called)
        empty_outcome = self._finalize(
            empty,
            empty_primary,
            self._progress(empty, empty_primary),
            empty_retriever,
        )
        self.assertEqual(len(empty_retriever.calls), 0)
        self.assertIsNone(empty_outcome.fallback)

    def test_primary_result_contract_violations_fail_before_fallback(self):
        malformed = (
            _result(self.store, (self.ev_a,), bundle="0" * 64),
            _result(self.store, (self.ev_a,), trace_granularity="page"),
            _result(self.store, (self.ev_a,), candidate_granularity="page"),
            _result(self.store, (self.ev_a,), ranks=(2,)),
            _result(self.store, (self.ev_b,)),
            _result(
                self.store,
                (self.ev_a,),
                doc_overrides={self.ev_a.evidence_id: "doc-b"},
            ),
            SearchResult(
                (Candidate("ev_unknown", "doc-a", 1.0, "rrf", 1),),
                {
                    "lane": "rrf",
                    "granularity": "child",
                    "bundle_sha256": self.store.bundle_sha256,
                },
            ),
        )
        bound = self.bind(self.request())
        for result in malformed:
            retriever = _FakeRetriever(result, _result(self.store, (self.ev_b,)))
            with self.subTest(trace=result.trace), self.assertRaises(
                (TypeError, ValueError)
            ):
                self._primary(bound, retriever)
            self.assertEqual(len(retriever.calls), 1)

    def test_retriever_errors_and_invalid_fallback_are_not_retried(self):
        bound = self.bind(self.request())
        exploding = _FakeRetriever(RuntimeError("primary failed"))
        with self.assertRaisesRegex(RuntimeError, "primary failed"):
            self._primary(bound, exploding)
        self.assertEqual(len(exploding.calls), 1)

        malformed_fallback = _FakeRetriever(
            _result(self.store, (self.ev_a,)),
            _result(self.store, (self.ev_b,), bundle="0" * 64),
        )
        primary = self._primary(bound, malformed_fallback)
        progress = self._progress(bound, primary)
        with self.assertRaisesRegex(ValueError, "search_result_bundle_mismatch"):
            self._finalize(bound, primary, progress, malformed_fallback)
        self.assertEqual(len(malformed_fallback.calls), 2)

    def test_provider_trace_bodies_are_removed_at_orchestration_boundary(self):
        bound = self.bind(self.request())
        raw = SearchResult(
            _result(self.store, (self.ev_a,)).candidates,
            {
                "lane": "rrf",
                "granularity": "child",
                "bundle_sha256": self.store.bundle_sha256,
                "reference_answer": "TOP-SECRET-GOLD",
                "qrels": {self.ev_a.evidence_id: 99},
                "raw_query": bound.plan.normalized_query,
                "nested": {"expected": ["doc-b"]},
            },
        )
        retriever = _FakeRetriever(raw)
        primary = self._primary(bound, retriever)
        progress = self._progress(bound, primary, (self.ev_a.evidence_id,))
        outcome = self._finalize(bound, primary, progress, retriever)
        serialized = str(outcome.to_dict())
        self.assertNotIn("TOP-SECRET-GOLD", serialized)
        self.assertNotIn("reference_answer", serialized)
        self.assertNotIn("qrels", serialized)
        self.assertNotIn("raw_query", serialized)
        self.assertNotIn(bound.plan.normalized_query, serialized)
        self.assertEqual(
            set(primary.result.trace),
            {
                "schema_version",
                "lane",
                "granularity",
                "bundle_sha256",
                "candidate_count",
                "trace_projection",
            },
        )
        with self.assertRaisesRegex(ValueError, "invalid_verifier_id"):
            bind_primary_evidence_progress(
                bound=bound,
                primary=primary,
                store=self.store,
                registry=self.registry,
                policy=FollowupEvidencePolicy.v1(),
                verified_answer_evidence_ids=(self.ev_a.evidence_id,),
                verifier_id="TOP-SECRET-GOLD",
                verifier_config_sha256="1" * 64,
            )

    def test_progress_only_accepts_verified_primary_evidence(self):
        bound = self.bind(self.request())
        retriever = _FakeRetriever(_result(self.store, (self.ev_a,)))
        primary = self._primary(bound, retriever)
        with self.assertRaisesRegex(ValueError, "verified_evidence_not_in_primary"):
            self._progress(bound, primary, (self.ev_b.evidence_id,))
        with self.assertRaisesRegex(ValueError, "duplicate_verified_answer_evidence_ids"):
            self._progress(
                bound,
                primary,
                (self.ev_a.evidence_id, self.ev_a.evidence_id),
            )
        with self.assertRaises(TypeError):
            bind_primary_evidence_progress(
                bound=bound,
                primary=primary,
                store=self.store,
                registry=self.registry,
                policy=FollowupEvidencePolicy.v1(),
                verified_answer_evidence_ids=[self.ev_a.evidence_id],
                verifier_id="test",
                verifier_config_sha256="1" * 64,
            )

    def test_retrieval_contracts_are_sealed_immutable_and_detached(self):
        policy = FollowupEvidencePolicy.v1()
        with self.assertRaises(TypeError):
            FollowupEvidencePolicy()
        bound = self.bind(self.request())
        retriever = _FakeRetriever(_result(self.store, (self.ev_a,)))
        primary = self._primary(bound, retriever)
        progress = self._progress(bound, primary, (self.ev_a.evidence_id,))
        outcome = self._finalize(bound, primary, progress, retriever)
        for constructor, args in (
            (FollowupRetrievalAttempt, ()),
            (PrimaryEvidenceProgress, ()),
            (FollowupRetrievalOutcome, ()),
        ):
            with self.subTest(constructor=constructor), self.assertRaises(TypeError):
                constructor(*args)
        with self.assertRaises((TypeError, ValueError)):
            replace(primary, result_sha256="0" * 64)
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            progress.sufficient = False
        payload = outcome.to_dict()
        payload["primary"]["result"]["candidates"].clear()
        self.assertEqual(len(outcome.primary.result.candidates), 1)
        trace_text = str(outcome.trace.to_dict()).lower()
        self.assertNotIn(bound.plan.normalized_query.lower(), trace_text)
        self.assertNotIn("reference_answer", trace_text)
        self.assertEqual(policy.policy_sha256, FollowupEvidencePolicy.v1().policy_sha256)


if __name__ == "__main__":
    unittest.main()
