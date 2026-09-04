from copy import deepcopy
from types import MappingProxyType
import unittest

from midprojectrag.evidence import Evidence, EvidenceStore, Locator, ProvenanceParent
from midprojectrag.orchestration import (
    Belief,
    CatalogEntity,
    DeterministicPlanner,
    EvidenceBeliefEntry,
    FollowupEvidencePolicy,
    HarnessState,
    PlanningCatalog,
    PrimaryEvidenceProgress,
    Progress,
    bind_followup,
    bind_primary_evidence_progress,
    build_compare_coverage,
    build_compare_harness_state,
    build_followup_harness_state,
    default_compare_field_registry,
    default_rule_registry,
    execute_compare_slot_search,
    finalize_followup_retrieval,
    prepare_compare_slots,
    replay_harness_state,
    retrieve_followup_primary,
    validate_harness_state,
)
from midprojectrag.retrieval import Candidate, SearchResult
from midprojectrag.runtime_integrity import RuntimeRequest


def _store():
    parents = []
    evidence = []
    for page, doc_id, text in (
        (1, "doc-a", "사업A 예산 100원 수행기간 10일"),
        (2, "doc-b", "사업B 예산 200원 수행기간 20일"),
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


def _catalog():
    return PlanningCatalog.synthetic(
        "harness-state-fixture-v1",
        (
            CatalogEntity("사업A", "사업A", "business", ("doc-a",), "business_alias"),
            CatalogEntity("사업B", "사업B", "business", ("doc-b",), "business_alias"),
        ),
    )


def _search_result(store, evidence=()):
    return SearchResult(
        tuple(
            Candidate(item.evidence_id, item.doc_id, 1.0 / rank, "rrf", rank)
            for rank, item in enumerate(evidence, 1)
        ),
        {
            "lane": "rrf",
            "granularity": "child",
            "bundle_sha256": store.bundle_sha256,
        },
    )


class _Retriever:
    def __init__(self, *results):
        self.results = results
        self.calls = []

    def search(self, query, *, dense_k, lexical_k, scope):
        self.calls.append((query, dense_k, lexical_k, scope))
        return self.results[len(self.calls) - 1]


def _compare_fixture():
    store, evidence = _store()
    registry = default_rule_registry()
    planner = DeterministicPlanner.for_test(registry, _catalog())
    request = RuntimeRequest(
        question="사업A와 사업B의 예산을 비교해줘",
        document_scope={"mode": "explicit", "doc_ids": ["doc-a", "doc-b"]},
        options={"allow_global_fallback": True},
    )
    planning = planner.plan(request)
    bound = prepare_compare_slots(
        request=request,
        planning=planning,
        store=store,
        planner=planner,
        compare_registry=default_compare_field_registry(),
    )
    return store, evidence, bound


def _followup_fixture(*, sufficient):
    store, (ev_a, ev_b) = _store()
    registry = default_rule_registry()
    planner = DeterministicPlanner.for_test(registry, _catalog())
    request = RuntimeRequest(
        question="그 사업의 기간은?",
        history=(
            {
                "turn_id": "assistant-1",
                "role": "assistant",
                "content": "앞선 답변",
                "cited_doc_ids": ["doc-a"],
                "cited_evidence_ids": [ev_a.evidence_id],
            },
        ),
        document_scope={"mode": "all", "doc_ids": []},
        options={"allow_global_fallback": True},
        prior_citation_state={
            "cited_doc_ids": ["doc-a"],
            "cited_evidence_ids": [ev_a.evidence_id],
            "resolved_entities": [],
            "list_doc_ids": [],
            "comparison_doc_ids": [],
        },
    )
    bound = bind_followup(request, planner.plan(request), store, registry)
    retriever = _Retriever(
        _search_result(store, (ev_a,)),
        _search_result(store, (ev_b,)),
    )
    primary = retrieve_followup_primary(
        bound=bound, store=store, registry=registry, retriever=retriever
    )
    policy = FollowupEvidencePolicy.v1()
    progress = bind_primary_evidence_progress(
        bound=bound,
        primary=primary,
        store=store,
        registry=registry,
        policy=policy,
        verified_answer_evidence_ids=(ev_a.evidence_id,) if sufficient else (),
        verifier_id="deterministic-evidence-verifier-v1",
        verifier_config_sha256="1" * 64,
    )
    outcome = finalize_followup_retrieval(
        bound=bound,
        primary=primary,
        progress=progress,
        store=store,
        registry=registry,
        policy=policy,
        retriever=retriever,
    )
    return store, (ev_a, ev_b), registry, policy, bound, progress, outcome, retriever


class HarnessStateProjectionTests(unittest.TestCase):
    def test_compare_projection_preserves_canonical_open_slot_order(self):
        store, _evidence, bound = _compare_fixture()
        coverage = build_compare_coverage(
            bound=bound,
            store=store,
            candidate_results={},
            verified_evidence={},
            missing_reasons={},
            contradicted_evidence={},
        )
        state = build_compare_harness_state(
            bound=bound, coverage=coverage, store=store
        )
        required = tuple(slot.key for slot in bound.plan.required_slots)
        self.assertEqual(state.belief.source_kind, "compare")
        self.assertEqual(state.progress.required_obligation_keys, required)
        self.assertEqual(state.progress.open_obligation_keys, required)
        self.assertTrue(
            all(entry.observation_stage == "unsearched" for entry in state.belief.evidence_map)
        )
        self.assertFalse(state.progress.normal_stop_allowed)
        self.assertFalse(state.progress.abstain_required)
        self.assertEqual(state.progress.slot_coverage_ratio, 0.0)
        serialized = str(state.to_dict()).lower()
        self.assertNotIn(bound.plan.normalized_query.lower(), serialized)
        self.assertNotIn("gold", serialized)

    def test_compare_candidate_and_missing_are_not_verified_or_absent(self):
        store, (ev_a, _ev_b), bound = _compare_fixture()
        first, second = (slot.key for slot in bound.plan.required_slots)
        candidate_retriever = _Retriever(_search_result(store, (ev_a,)))
        candidate_receipt = execute_compare_slot_search(
            bound=bound,
            store=store,
            slot_key=first,
            retriever=candidate_retriever,
        )
        empty_retriever = _Retriever(_search_result(store))
        empty_receipt = execute_compare_slot_search(
            bound=bound,
            store=store,
            slot_key=second,
            retriever=empty_retriever,
        )
        coverage = build_compare_coverage(
            bound=bound,
            store=store,
            candidate_results={first: candidate_receipt, second: empty_receipt},
            verified_evidence={},
            missing_reasons={second: "no_candidate_yet"},
            contradicted_evidence={},
        )
        before = (len(candidate_retriever.calls), len(empty_retriever.calls))
        state = build_compare_harness_state(
            bound=bound, coverage=coverage, store=store
        )
        self.assertEqual(
            tuple(entry.observation_stage for entry in state.belief.evidence_map),
            ("candidate", "provisional_missing"),
        )
        self.assertEqual(state.progress.provisional_missing_obligation_keys, (second,))
        self.assertEqual(state.progress.confirmed_missing_obligation_keys, ())
        self.assertEqual(state.progress.verified_obligation_keys, ())
        self.assertEqual(
            (len(candidate_retriever.calls), len(empty_retriever.calls)), before
        )

    def test_followup_sufficient_uses_reserved_answer_obligation_and_stops(self):
        (
            store,
            (ev_a, _ev_b),
            registry,
            policy,
            bound,
            progress,
            outcome,
            retriever,
        ) = _followup_fixture(sufficient=True)
        before = len(retriever.calls)
        state = build_followup_harness_state(
            bound=bound,
            progress=progress,
            outcome=outcome,
            store=store,
            registry=registry,
            policy=policy,
        )
        self.assertEqual(state.progress.required_obligation_keys, ("$answer_support",))
        self.assertEqual(state.progress.verified_obligation_keys, ("$answer_support",))
        self.assertEqual(
            state.belief.evidence_map[0].verified_evidence_ids, (ev_a.evidence_id,)
        )
        self.assertTrue(state.progress.normal_stop_allowed)
        self.assertEqual(state.progress.answerability, "complete")
        self.assertEqual(len(retriever.calls), before)

    def test_followup_insufficient_keeps_fallback_candidates_provisional(self):
        (
            store,
            (ev_a, ev_b),
            registry,
            policy,
            bound,
            progress,
            outcome,
            retriever,
        ) = _followup_fixture(sufficient=False)
        before = len(retriever.calls)
        state = build_followup_harness_state(
            bound=bound,
            progress=progress,
            outcome=outcome,
            store=store,
            registry=registry,
            policy=policy,
        )
        answer = state.belief.evidence_map[0]
        self.assertEqual(answer.obligation_key, "$answer_support")
        self.assertEqual(answer.observation_stage, "candidate")
        self.assertEqual(
            answer.candidate_evidence_ids, (ev_a.evidence_id, ev_b.evidence_id)
        )
        self.assertEqual(state.progress.open_obligation_keys, ("$answer_support",))
        self.assertEqual(state.progress.confirmed_missing_obligation_keys, ())
        self.assertFalse(state.progress.normal_stop_allowed)
        self.assertFalse(state.progress.abstain_required)
        self.assertEqual(state.progress.answerability, "in_progress")
        self.assertEqual(len(retriever.calls), before)

    def test_state_and_children_are_factory_only_and_exact_store_bound(self):
        store, _evidence, bound = _compare_fixture()
        coverage = build_compare_coverage(
            bound=bound,
            store=store,
            candidate_results={},
            verified_evidence={},
            missing_reasons={},
            contradicted_evidence={},
        )
        state = build_compare_harness_state(
            bound=bound, coverage=coverage, store=store
        )
        for cls in (EvidenceBeliefEntry, Belief, Progress, HarnessState):
            with self.subTest(cls=cls), self.assertRaises(TypeError):
                cls()
        clone = object.__new__(HarnessState)
        for name in state.__dataclass_fields__:
            object.__setattr__(clone, name, getattr(state, name))
        self.assertEqual(clone.to_dict(), state.to_dict())
        with self.assertRaisesRegex(
            ValueError, "harness_state_runtime_authority_required"
        ):
            validate_harness_state(state=clone, store=store)
        cloned_store = EvidenceStore.from_dict(store.to_dict())
        with self.assertRaisesRegex(
            ValueError, "harness_state_store_identity_mismatch"
        ):
            validate_harness_state(state=state, store=cloned_store)

    def test_state_rejects_live_store_bundle_and_nested_payload_drift(self):
        store, (ev_a, _ev_b), bound = _compare_fixture()
        coverage = build_compare_coverage(
            bound=bound,
            store=store,
            candidate_results={},
            verified_evidence={},
            missing_reasons={},
            contradicted_evidence={},
        )
        state = build_compare_harness_state(
            bound=bound, coverage=coverage, store=store
        )
        object.__setattr__(store, "bundle_sha256", "f" * 64)
        with self.assertRaisesRegex(
            ValueError, "harness_state_store_bundle_mismatch"
        ):
            validate_harness_state(state=state, store=store)

        store, (ev_a, _ev_b), bound = _compare_fixture()
        coverage = build_compare_coverage(
            bound=bound,
            store=store,
            candidate_results={},
            verified_evidence={},
            missing_reasons={},
            contradicted_evidence={},
        )
        state = build_compare_harness_state(
            bound=bound, coverage=coverage, store=store
        )
        object.__setattr__(store.get(ev_a.evidence_id), "text", "ATTACK")
        with self.assertRaisesRegex(
            ValueError, "harness_state_store_payload_drift"
        ):
            validate_harness_state(state=state, store=store)

        store, (_ev_a, _ev_b), bound = _compare_fixture()
        coverage = build_compare_coverage(
            bound=bound,
            store=store,
            candidate_results={},
            verified_evidence={},
            missing_reasons={},
            contradicted_evidence={},
        )
        state = build_compare_harness_state(
            bound=bound, coverage=coverage, store=store
        )
        object.__setattr__(
            store,
            "_parents",
            MappingProxyType(
                {
                    **{
                        key: value
                        for key, value in store._parents.items()
                        if key != store.parents[0].parent_id
                    },
                    "wrong-key": store.parents[0],
                }
            ),
        )
        with self.assertRaisesRegex(
            ValueError, "harness_state_store_payload_drift"
        ):
            validate_harness_state(state=state, store=store)

    def test_followup_requires_the_exact_progress_inside_outcome(self):
        (
            store,
            _evidence,
            registry,
            policy,
            bound,
            progress,
            outcome,
            _retriever,
        ) = _followup_fixture(sufficient=True)
        clone = object.__new__(PrimaryProgressProxy)
        object.__setattr__(clone, "value", progress)
        with self.assertRaises(TypeError):
            build_followup_harness_state(
                bound=bound,
                progress=clone,
                outcome=outcome,
                store=store,
                registry=registry,
                policy=policy,
            )

        equal_looking = object.__new__(PrimaryEvidenceProgress)
        for name in progress.__dataclass_fields__:
            object.__setattr__(equal_looking, name, getattr(progress, name))
        self.assertEqual(equal_looking.to_dict(), progress.to_dict())
        with self.assertRaisesRegex(
            ValueError, "followup_outcome_progress_identity_mismatch"
        ):
            build_followup_harness_state(
                bound=bound,
                progress=equal_looking,
                outcome=outcome,
                store=store,
                registry=registry,
                policy=policy,
            )

    def test_replay_is_source_rebuilt_and_json_type_strict(self):
        store, _evidence, bound = _compare_fixture()
        coverage = build_compare_coverage(
            bound=bound,
            store=store,
            candidate_results={},
            verified_evidence={},
            missing_reasons={},
            contradicted_evidence={},
        )
        state = build_compare_harness_state(
            bound=bound, coverage=coverage, store=store
        )
        replayed = replay_harness_state(
            state.to_dict(), bound=bound, source_receipt=coverage, store=store
        )
        self.assertEqual(replayed.to_dict(), state.to_dict())
        self.assertIsNot(replayed, state)

        mutations = []
        extra = deepcopy(state.to_dict())
        extra["gold"] = "secret"
        mutations.append(extra)
        tuple_array = deepcopy(state.to_dict())
        tuple_array["progress"]["open_obligation_keys"] = tuple(
            tuple_array["progress"]["open_obligation_keys"]
        )
        mutations.append(tuple_array)
        bool_as_int = deepcopy(state.to_dict())
        bool_as_int["progress"]["normal_stop_allowed"] = 0
        mutations.append(bool_as_int)
        float_as_int = deepcopy(state.to_dict())
        float_as_int["progress"]["slot_coverage_ratio"] = 0
        mutations.append(float_as_int)
        for raw in mutations:
            with self.subTest(raw=raw), self.assertRaises((TypeError, ValueError)):
                replay_harness_state(
                    raw, bound=bound, source_receipt=coverage, store=store
                )

    def test_gold_cannot_influence_factory_or_serialization(self):
        store, _evidence, bound = _compare_fixture()
        coverage = build_compare_coverage(
            bound=bound,
            store=store,
            candidate_results={},
            verified_evidence={},
            missing_reasons={},
            contradicted_evidence={},
        )
        state = build_compare_harness_state(
            bound=bound, coverage=coverage, store=store
        )
        with self.assertRaises(TypeError):
            build_compare_harness_state(
                bound=bound,
                coverage=coverage,
                store=store,
                gold={"expected": "secret"},
            )
        serialized = str(state.to_dict()).lower()
        for forbidden in ("gold", "qrels", "expected", "question"):
            self.assertNotIn(forbidden, serialized)


class PrimaryProgressProxy:
    pass


if __name__ == "__main__":
    unittest.main()
