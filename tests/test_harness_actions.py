from copy import deepcopy
import unittest

from midprojectrag.evidence import Evidence, EvidenceStore, Locator, ProvenanceParent
from midprojectrag.orchestration import (
    CatalogEntity,
    DeterministicPlanner,
    FollowupEvidencePolicy,
    PlanningCatalog,
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
    retrieve_followup_primary,
)
from midprojectrag.orchestration.actions import (
    ActionDecisionTrace,
    HarnessAction,
    allowed_harness_actions,
    decide_harness_action,
    replay_action_decision,
)
from midprojectrag.orchestration import harness_state as state_module
from midprojectrag.retrieval import Candidate, SearchResult
from midprojectrag.runtime_integrity import RuntimeRequest


class _Retriever:
    def __init__(self, *results):
        self.results = results
        self.calls = []

    def search(self, query, *, dense_k, lexical_k, scope):
        self.calls.append((query, dense_k, lexical_k, scope))
        return self.results[len(self.calls) - 1]


def _result(store, evidence=()):
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


def _catalog():
    return PlanningCatalog.synthetic(
        "harness-action-fixture-v1",
        (
            CatalogEntity("사업A", "사업A", "business", ("doc-a",), "business_alias"),
            CatalogEntity("사업B", "사업B", "business", ("doc-b",), "business_alias"),
        ),
    )


def _compare_fixture(*, with_bridges=False, candidate=False):
    parents = []
    evidence = []
    searchable = []
    for page, doc_id, text in (
        (1, "doc-a", "사업A 예산 100원"),
        (2, "doc-b", "사업B 예산 200원"),
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
        searchable.append(child)
        if with_bridges and doc_id == "doc-a":
            evidence.extend(
                (
                    Evidence(
                        doc_id,
                        "table_row_group",
                        "예산 | 100원",
                        parent.parent_id,
                        (f"block-{doc_id}",),
                        Locator(page=page, row_range=(0, 1)),
                    ),
                    Evidence(
                        doc_id,
                        "figure_object",
                        "예산 구조도",
                        parent.parent_id,
                        (f"block-{doc_id}",),
                        Locator(page=page, bbox=(0.0, 0.0, 1.0, 1.0)),
                    ),
                )
            )
    store = EvidenceStore(parents, evidence)
    registry = default_rule_registry()
    planner = DeterministicPlanner.for_test(registry, _catalog())
    request = RuntimeRequest(
        question="사업A와 사업B의 예산을 비교해줘",
        document_scope={"mode": "explicit", "doc_ids": ["doc-a", "doc-b"]},
        options={"allow_global_fallback": True},
    )
    bound = prepare_compare_slots(
        request=request,
        planning=planner.plan(request),
        store=store,
        planner=planner,
        compare_registry=default_compare_field_registry(),
    )
    results = {}
    retriever = None
    if candidate:
        first_key = bound.plan.required_slots[0].key
        retriever = _Retriever(_result(store, (searchable[0],)))
        results[first_key] = execute_compare_slot_search(
            bound=bound,
            store=store,
            slot_key=first_key,
            retriever=retriever,
        )
    coverage = build_compare_coverage(
        bound=bound,
        store=store,
        candidate_results=results,
        verified_evidence={},
        missing_reasons={},
        contradicted_evidence={},
    )
    state = build_compare_harness_state(bound=bound, coverage=coverage, store=store)
    return store, tuple(searchable), state, retriever


def _followup_fixture(*, sufficient=False, empty=False):
    parent = ProvenanceParent(
        "doc-a", "pdf_page", "사업A 수행기간 10일", ("block-a",), Locator(page=1)
    )
    child = Evidence(
        "doc-a",
        "text",
        parent.text,
        parent.parent_id,
        ("block-a",),
        Locator(page=1, char_range=(0, len(parent.text))),
    )
    store = EvidenceStore((parent,), (child,))
    registry = default_rule_registry()
    catalog = PlanningCatalog.synthetic(
        "harness-action-followup-fixture-v1",
        (CatalogEntity("사업A", "사업A", "business", ("doc-a",), "business_alias"),),
    )
    planner = DeterministicPlanner.for_test(registry, catalog)
    request = RuntimeRequest(
        question="그 사업의 기간은?",
        history=(
            {
                "turn_id": "assistant-1",
                "role": "assistant",
                "content": "앞선 답변",
                "cited_doc_ids": ["doc-a"],
                "cited_evidence_ids": [child.evidence_id],
            },
        ),
        document_scope={"mode": "all", "doc_ids": []},
        options={"allow_global_fallback": True},
        prior_citation_state={
            "cited_doc_ids": ["doc-a"],
            "cited_evidence_ids": [child.evidence_id],
            "resolved_entities": [],
            "list_doc_ids": [],
            "comparison_doc_ids": [],
        },
    )
    bound = bind_followup(request, planner.plan(request), store, registry)
    response = _result(store, () if empty else (child,))
    retriever = _Retriever(response, response)
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
        verified_answer_evidence_ids=(child.evidence_id,) if sufficient else (),
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
    state = build_followup_harness_state(
        bound=bound,
        progress=progress,
        outcome=outcome,
        store=store,
        registry=registry,
        policy=policy,
    )
    return store, child, state, retriever


def _contradicted_state(store, candidate, base_state, *, mixed=False):
    entries = tuple(
        state_module.EvidenceBeliefEntry._create(
            obligation_key=entry.obligation_key,
            observation_stage=(
                "contradicted" if index == 0 or not mixed else entry.observation_stage
            ),
            candidate_evidence_ids=(
                (candidate.evidence_id,)
                if index == 0 or not mixed
                else entry.candidate_evidence_ids
            ),
            verified_evidence_ids=(),
            _token=state_module._ENTRY_TOKEN,
        )
        for index, entry in enumerate(base_state.belief.evidence_map)
    )
    original = base_state.belief
    belief = state_module._make_belief(
        source_kind=original.source_kind,
        request_fingerprint=original.request_fingerprint,
        binding_sha256=original.binding_sha256,
        effective_plan_sha256=original.effective_plan_sha256,
        config_sha256=original.config_sha256,
        evidence_bundle_sha256=original.evidence_bundle_sha256,
        query_type=original.query_type,
        entities=original.entities,
        constraints=original.constraints,
        scope_state=original.scope_state,
        scope_origin=original.scope_origin,
        scope_doc_ids=original.scope_doc_ids,
        evidence_map=entries,
        source_receipt_sha256=original.source_receipt_sha256,
    )
    progress = state_module._make_progress(
        evidence_map=entries,
        slot_coverage_ratio=0.0,
        answerability="conflict",
        normal_stop_allowed=False,
        abstain_required=not mixed,
    )
    return state_module.HarnessState._create(
        belief=belief,
        progress=progress,
        store=store,
        _token=state_module._STATE_TOKEN,
    )


class HarnessAllowedActionsTests(unittest.TestCase):
    def test_unsearched_compare_is_obligation_major_and_has_one_abstain(self):
        store, _evidence, state, _retriever = _compare_fixture()
        actions = allowed_harness_actions(state, store=store)
        expected = []
        for key in state.progress.required_obligation_keys:
            expected.extend(
                (("retrieve_dense", key, None), ("retrieve_lexical", key, None))
            )
        expected.append(("abstain", None, None))
        self.assertEqual(
            tuple((item.kind, item.obligation_key, item.evidence_id) for item in actions),
            tuple(expected),
        )
        self.assertEqual(sum(item.kind == "abstain" for item in actions), 1)
        self.assertNotIn("fuse", {item.kind for item in actions})

    def test_candidate_eligibility_uses_sealed_parent_and_bridges(self):
        store, evidence, state, retriever = _compare_fixture(
            with_bridges=True, candidate=True
        )
        calls_before = len(retriever.calls)
        actions = allowed_harness_actions(state, store=store)
        first_key = state.progress.required_obligation_keys[0]
        candidate_id = evidence[0].evidence_id
        self.assertEqual(
            tuple(
                (item.kind, item.obligation_key, item.evidence_id)
                for item in actions[:5]
            ),
            (
                ("expand_parent", first_key, candidate_id),
                ("bridge_table", first_key, candidate_id),
                ("bridge_figure", first_key, candidate_id),
                ("rerank", first_key, None),
                ("verify_slot", first_key, None),
            ),
        )
        self.assertEqual(len(retriever.calls), calls_before)

    def test_followup_candidate_has_no_retrieval_and_empty_is_safe_abstain(self):
        store, child, state, retriever = _followup_fixture(sufficient=False)
        before = len(retriever.calls)
        actions = allowed_harness_actions(state, store=store)
        self.assertEqual(
            tuple((item.kind, item.evidence_id) for item in actions),
            (
                ("expand_parent", child.evidence_id),
                ("rerank", None),
                ("verify_slot", None),
                ("abstain", None),
            ),
        )
        self.assertNotIn("retrieve_dense", {item.kind for item in actions})
        self.assertEqual(len(retriever.calls), before)

        empty_store, _child, empty_state, empty_retriever = _followup_fixture(
            sufficient=False, empty=True
        )
        empty_before = len(empty_retriever.calls)
        empty_actions = allowed_harness_actions(empty_state, store=empty_store)
        self.assertEqual(tuple(item.kind for item in empty_actions), ("abstain",))
        self.assertEqual(len(empty_retriever.calls), empty_before)

    def test_terminal_gates_are_exact(self):
        stop_store, _child, stop_state, stop_retriever = _followup_fixture(
            sufficient=True
        )
        before = len(stop_retriever.calls)
        self.assertEqual(
            tuple(item.kind for item in allowed_harness_actions(stop_state, store=stop_store)),
            ("stop",),
        )
        self.assertEqual(len(stop_retriever.calls), before)

        store, evidence, base_state, _retriever = _compare_fixture()
        contradicted = _contradicted_state(store, evidence[0], base_state)
        actions = allowed_harness_actions(contradicted, store=store)
        self.assertEqual(tuple(item.kind for item in actions), ("abstain",))

        mixed = _contradicted_state(store, evidence[0], base_state, mixed=True)
        self.assertFalse(mixed.progress.abstain_required)
        self.assertTrue(mixed.progress.open_obligation_keys)
        mixed_actions = allowed_harness_actions(mixed, store=store)
        self.assertEqual(tuple(item.kind for item in mixed_actions), ("abstain",))
        mixed_decision = decide_harness_action(mixed, store=store)
        self.assertEqual(mixed_decision.reason_code, "abstain_required")

    def test_actions_are_factory_only_and_bound_to_exact_context(self):
        store, _evidence, state, _retriever = _compare_fixture()
        with self.assertRaises(TypeError):
            HarnessAction()
        action = allowed_harness_actions(state, store=store)[0]
        clone = object.__new__(HarnessAction)
        for name in action.__dataclass_fields__:
            object.__setattr__(clone, name, getattr(action, name))
        self.assertEqual(clone.to_dict(), action.to_dict())
        with self.assertRaisesRegex(
            ValueError, "harness_action_runtime_authority_required"
        ):
            clone._validate(state=state, store=store)
        cloned_store = EvidenceStore.from_dict(store.to_dict())
        with self.assertRaisesRegex(ValueError, "harness_state_store_identity_mismatch"):
            allowed_harness_actions(state, store=cloned_store)


class HarnessActionDecisionTests(unittest.TestCase):
    def test_decision_selects_first_action_and_chains_nonterminal(self):
        store, _evidence, state, _retriever = _compare_fixture()
        first = decide_harness_action(state, store=store)
        second = decide_harness_action(state, store=store, previous=first)
        self.assertEqual(first.policy_id, "bounded-deterministic-e1-v1")
        self.assertEqual(first.decision_ordinal, 1)
        self.assertIsNone(first.previous_decision_sha256)
        self.assertIs(first.selected_action, first.allowed_actions[0])
        self.assertEqual(first.selected_action.kind, "retrieve_dense")
        self.assertEqual(first.reason_code, "first_eligible_nonterminal")
        self.assertEqual(second.decision_ordinal, 2)
        self.assertEqual(second.previous_decision_sha256, first.decision_sha256)
        self.assertEqual(
            second.execution_identity_sha256, first.execution_identity_sha256
        )

    def test_terminal_decisions_have_gate_reason_and_cannot_continue(self):
        store, _child, state, _retriever = _followup_fixture(sufficient=True)
        decision = decide_harness_action(state, store=store)
        self.assertEqual(decision.selected_action.kind, "stop")
        self.assertEqual(decision.reason_code, "normal_stop_allowed")
        with self.assertRaisesRegex(
            ValueError, "terminal_action_decision_cannot_continue"
        ):
            decide_harness_action(state, store=store, previous=decision)

        empty_store, _child, empty_state, _retriever = _followup_fixture(
            sufficient=False, empty=True
        )
        safe = decide_harness_action(empty_state, store=empty_store)
        self.assertEqual(safe.selected_action.kind, "abstain")
        self.assertEqual(
            safe.reason_code, "no_eligible_nonterminal_safe_abstain"
        )

    def test_decision_and_previous_require_factory_identity(self):
        store, _evidence, state, _retriever = _compare_fixture()
        with self.assertRaises(TypeError):
            ActionDecisionTrace()
        decision = decide_harness_action(state, store=store)
        clone = object.__new__(ActionDecisionTrace)
        for name in decision.__dataclass_fields__:
            object.__setattr__(clone, name, getattr(decision, name))
        self.assertEqual(clone.to_dict(), decision.to_dict())
        with self.assertRaisesRegex(
            ValueError, "action_decision_runtime_authority_required"
        ):
            decide_harness_action(state, store=store, previous=clone)

    def test_replay_is_exact_json_and_does_not_execute_retrieval(self):
        store, _evidence, state, retriever = _compare_fixture(candidate=True)
        calls_before = len(retriever.calls)
        decision = decide_harness_action(state, store=store)
        replayed = replay_action_decision(
            decision.to_dict(), state=state, store=store
        )
        self.assertEqual(replayed.to_dict(), decision.to_dict())
        self.assertIsNot(replayed, decision)
        self.assertEqual(len(retriever.calls), calls_before)

        mutations = []
        extra = deepcopy(decision.to_dict())
        extra["gold"] = {"expected": "secret"}
        mutations.append(extra)
        tuple_array = deepcopy(decision.to_dict())
        tuple_array["allowed_actions"] = tuple(tuple_array["allowed_actions"])
        mutations.append(tuple_array)
        bool_ordinal = deepcopy(decision.to_dict())
        bool_ordinal["decision_ordinal"] = True
        mutations.append(bool_ordinal)
        float_ordinal = deepcopy(decision.to_dict())
        float_ordinal["decision_ordinal"] = 1.0
        mutations.append(float_ordinal)
        forged_selection = deepcopy(decision.to_dict())
        forged_selection["selected_action"] = deepcopy(
            forged_selection["allowed_actions"][-1]
        )
        mutations.append(forged_selection)
        for raw in mutations:
            with self.subTest(raw=raw), self.assertRaises((TypeError, ValueError)):
                replay_action_decision(raw, state=state, store=store)
        self.assertEqual(len(retriever.calls), calls_before)

    def test_gold_and_caller_action_fields_are_not_accepted(self):
        store, _evidence, state, _retriever = _compare_fixture()
        with self.assertRaises(TypeError):
            decide_harness_action(state, store=store, gold={"expected": "secret"})
        with self.assertRaises(TypeError):
            allowed_harness_actions(
                state,
                store=store,
                query="caller supplied query",
                scope=("doc-a",),
            )
        serialized = str(decide_harness_action(state, store=store).to_dict()).lower()
        for forbidden in ("gold", "qrels", "expected", "question", "query", "scope"):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
