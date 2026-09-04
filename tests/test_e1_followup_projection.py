from hashlib import sha256
import inspect
import json
import unittest
from weakref import ref

import midprojectrag.orchestration.followup_retrieval as followup_retrieval_module
import midprojectrag.orchestration.harness_state as harness_state_module
from midprojectrag.evidence import Evidence, EvidenceStore, Locator, ProvenanceParent
from midprojectrag.orchestration import (
    CatalogEntity,
    DeterministicPlanner,
    FollowupEvidencePolicy,
    PlanningCatalog,
    PlanningResult,
    RequiredSlot,
    allowed_harness_actions,
    bind_followup,
    bind_primary_evidence_progress,
    build_e1_followup_harness_state,
    default_rule_registry,
    finalize_followup_retrieval,
    retrieve_followup_primary,
    validate_harness_state,
)
from midprojectrag.retrieval import Candidate, SearchResult
from midprojectrag.runtime_integrity import RuntimeRequest


def _callable_pin(function):
    kwdefaults = function.__kwdefaults__
    closure = function.__closure__
    return (
        function,
        function.__name__,
        function.__code__,
        function.__defaults__,
        kwdefaults,
        None if kwdefaults is None else tuple(sorted(kwdefaults.items())),
        function.__globals__,
        closure,
        None if closure is None else tuple(cell.cell_contents for cell in closure),
    )


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
        "e1-followup-projection-v1",
        (
            CatalogEntity("사업A", "사업A", "business", ("doc-a",), "business_alias"),
            CatalogEntity("사업B", "사업B", "business", ("doc-b",), "business_alias"),
        ),
    )


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


class _Retriever:
    def __init__(self, *results):
        self.results = results
        self.calls = []

    def search(self, query, *, dense_k, lexical_k, scope):
        self.calls.append((query, dense_k, lexical_k, scope))
        return self.results[len(self.calls) - 1]


def _fixture(
    *,
    cited_doc_ids=("doc-a",),
    explicit_scope=False,
    slots=(),
    primary_ids=(0,),
    fallback_ids=(1,),
    verified_ids=(),
    verified_slots=(),
    metadata=False,
):
    store, evidence = _store()
    registry = default_rule_registry()
    planner = DeterministicPlanner.for_test(registry, _catalog())
    cited = tuple(item for item in evidence if item.doc_id in cited_doc_ids)
    request_kwargs = {
        "question": "그 사업의 기간은?",
        "history": (
            {
                "turn_id": "assistant-1",
                "role": "assistant",
                "content": "앞선 답변",
                "cited_doc_ids": list(cited_doc_ids),
                "cited_evidence_ids": [item.evidence_id for item in cited],
            },
        ),
        "document_scope": (
            {"mode": "explicit", "doc_ids": list(cited_doc_ids)}
            if explicit_scope
            else {"mode": "all", "doc_ids": []}
        ),
        "options": {"allow_global_fallback": True},
        "prior_citation_state": {
            "cited_doc_ids": list(cited_doc_ids),
            "cited_evidence_ids": [item.evidence_id for item in cited],
            "resolved_entities": [],
            "list_doc_ids": [],
            "comparison_doc_ids": [],
        },
    }
    if metadata:
        request_kwargs["metadata_filters"] = (
            {"field": "business_amount", "operator": "ge", "value": 1},
        )
    request = RuntimeRequest(**request_kwargs)
    planning = planner.plan(request)
    if slots:
        prior = planning.plan
        planning = PlanningResult(
            registry.make_plan(
                query_type=prior.query_type,
                normalized_query=prior.normalized_query,
                entities=prior.entities,
                resolved_doc_ids=prior.resolved_doc_ids,
                inherited_doc_ids=prior.inherited_doc_ids,
                scope_state=prior.scope_state,
                scope_origin=prior.scope_origin,
                constraints=prior.constraints,
                metadata_predicates=prior.metadata_predicates,
                required_slots=slots,
                allow_global_fallback=prior.allow_global_fallback,
                unresolved_constraints=prior.unresolved_constraints,
            ),
            planning.trace,
        )
    bound = bind_followup(request, planning, store, registry)
    retriever = _Retriever(
        _result(store, tuple(evidence[index] for index in primary_ids)),
        _result(store, tuple(evidence[index] for index in fallback_ids)),
    )
    primary = retrieve_followup_primary(
        bound=bound,
        store=store,
        registry=registry,
        retriever=retriever,
    )
    policy = FollowupEvidencePolicy.v1()
    progress = bind_primary_evidence_progress(
        bound=bound,
        primary=primary,
        store=store,
        registry=registry,
        policy=policy,
        verified_answer_evidence_ids=tuple(
            evidence[index].evidence_id for index in verified_ids
        ),
        verified_slot_evidence=tuple(
            (key, evidence[index].evidence_id) for key, index in verified_slots
        ),
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
    return store, evidence, registry, policy, bound, outcome, retriever


class E1FollowupProjectionTests(unittest.TestCase):
    def _build(self, fixture):
        store, _evidence, registry, policy, bound, outcome, retriever = fixture
        before = len(retriever.calls)
        state = build_e1_followup_harness_state(
            bound=bound,
            outcome=outcome,
            store=store,
            registry=registry,
            policy=policy,
        )
        self.assertEqual(len(retriever.calls), before)
        validate_harness_state(state=state, store=store)
        return state

    def test_old_verified_claim_is_downgraded_and_cannot_stop(self):
        fixture = _fixture(verified_ids=(0,))
        state = self._build(fixture)
        answer = state.belief.evidence_map[0]
        self.assertEqual(answer.obligation_key, "$answer_support")
        self.assertEqual(answer.observation_stage, "candidate")
        self.assertEqual(answer.verified_evidence_ids, ())
        self.assertEqual(state.progress.verified_obligation_keys, ())
        self.assertEqual(state.progress.slot_coverage_ratio, 0.0)
        self.assertEqual(state.progress.answerability, "in_progress")
        self.assertFalse(state.progress.normal_stop_allowed)
        self.assertFalse(state.progress.abstain_required)
        action_kinds = {item.kind for item in allowed_harness_actions(state, store=fixture[0])}
        self.assertNotIn("retrieve_dense", action_kinds)
        self.assertNotIn("retrieve_lexical", action_kinds)
        self.assertNotIn("stop", action_kinds)
        self.assertEqual(self._build(fixture).to_dict(), state.to_dict())

        outcome = fixture[5]
        expected_source = sha256(
            json.dumps(
                outcome.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(state.belief.source_receipt_sha256, expected_source)

    def test_primary_then_fallback_order_is_first_seen_deduplicated(self):
        fixture = _fixture(primary_ids=(0,), fallback_ids=(0, 1))
        state = self._build(fixture)
        ev_a, ev_b = fixture[1]
        self.assertEqual(
            state.belief.evidence_map[0].candidate_evidence_ids,
            (ev_a.evidence_id, ev_b.evidence_id),
        )
        self.assertEqual(len(fixture[6].calls), 2)

    def test_actual_slots_receive_only_same_document_candidates(self):
        slots = (RequiredSlot("doc-a", "duration"), RequiredSlot("doc-b", "duration"))
        fixture = _fixture(
            cited_doc_ids=("doc-a", "doc-b"),
            explicit_scope=True,
            slots=slots,
            primary_ids=(0, 1),
            verified_ids=(0, 1),
            verified_slots=((slots[0].key, 0), (slots[1].key, 1)),
        )
        state = self._build(fixture)
        ev_a, ev_b = fixture[1]
        answer, slot_a, slot_b = state.belief.evidence_map
        self.assertEqual(
            tuple(entry.obligation_key for entry in state.belief.evidence_map),
            ("$answer_support", slots[0].key, slots[1].key),
        )
        self.assertEqual(answer.candidate_evidence_ids, (ev_a.evidence_id, ev_b.evidence_id))
        self.assertEqual(slot_a.candidate_evidence_ids, (ev_a.evidence_id,))
        self.assertEqual(slot_b.candidate_evidence_ids, (ev_b.evidence_id,))
        self.assertTrue(
            all(entry.observation_stage == "candidate" for entry in state.belief.evidence_map)
        )
        self.assertEqual(state.progress.open_obligation_keys, tuple(
            entry.obligation_key for entry in state.belief.evidence_map
        ))

    def test_empty_approved_paths_remain_provisional_not_absent(self):
        slots = (RequiredSlot("doc-a", "duration"),)
        fixture = _fixture(
            explicit_scope=True,
            slots=slots,
            primary_ids=(),
            fallback_ids=(),
        )
        state = self._build(fixture)
        self.assertEqual(
            tuple(entry.observation_stage for entry in state.belief.evidence_map),
            ("provisional_missing", "provisional_missing"),
        )
        self.assertEqual(state.progress.confirmed_missing_obligation_keys, ())
        self.assertEqual(state.progress.verified_obligation_keys, ())
        self.assertEqual(state.progress.open_obligation_keys, ("$answer_support", slots[0].key))

    def test_metadata_predicate_fails_closed_without_filtered_scope_receipt(self):
        fixture = _fixture(metadata=True, primary_ids=(0,), fallback_ids=())
        store, _evidence, registry, policy, bound, outcome, retriever = fixture
        before = len(retriever.calls)
        with self.assertRaisesRegex(
            ValueError, "followup_metadata_scope_receipt_required"
        ):
            build_e1_followup_harness_state(
                bound=bound,
                outcome=outcome,
                store=store,
                registry=registry,
                policy=policy,
            )
        self.assertEqual(len(retriever.calls), before)

    def test_public_surface_is_closed_and_foreign_outcome_is_rejected(self):
        fixture = _fixture(primary_ids=(0,), fallback_ids=(1,))
        store, _evidence, registry, policy, bound, outcome, retriever = fixture
        self.assertEqual(
            tuple(inspect.signature(build_e1_followup_harness_state).parameters),
            ("bound", "outcome", "store", "registry", "policy"),
        )
        before = len(retriever.calls)
        with self.assertRaises(TypeError):
            build_e1_followup_harness_state(
                bound=bound,
                outcome=outcome,
                store=store,
                registry=registry,
                policy=policy,
                gold={"expected": "secret"},
            )

        clone = object.__new__(type(outcome))
        for name in outcome.__dataclass_fields__:
            object.__setattr__(clone, name, getattr(outcome, name))
        self.assertEqual(clone.to_dict(), outcome.to_dict())
        with self.assertRaises(ValueError):
            build_e1_followup_harness_state(
                bound=bound,
                outcome=clone,
                store=store,
                registry=registry,
                policy=policy,
            )
        cloned_store = EvidenceStore.from_dict(store.to_dict())
        with self.assertRaises(ValueError):
            build_e1_followup_harness_state(
                bound=bound,
                outcome=outcome,
                store=cloned_store,
                registry=registry,
                policy=policy,
            )
        self.assertEqual(len(retriever.calls), before)

        serialized = json.dumps(self._build(fixture).to_dict(), ensure_ascii=False)
        for forbidden in ("gold", "qrels", "expected", "question", "verifier_config"):
            self.assertNotIn(forbidden, serialized.lower())

        equivalent = build_e1_followup_harness_state(
            bound=bound,
            outcome=outcome,
            store=store,
            registry=default_rule_registry(),
            policy=FollowupEvidencePolicy.v1(),
        )
        self.assertEqual(equivalent.to_dict(), self._build(fixture).to_dict())

    def test_validator_and_dependency_drift_fail_before_projection(self):
        fixture = _fixture(primary_ids=(0,), fallback_ids=(1,))
        store, _evidence, registry, policy, bound, outcome, retriever = fixture
        clone = object.__new__(type(outcome))
        for name in outcome.__dataclass_fields__:
            object.__setattr__(clone, name, getattr(outcome, name))
        before = len(retriever.calls)

        original_global = harness_state_module.validate_followup_retrieval_outcome
        no_op = lambda **_kwargs: None
        harness_state_module.validate_followup_retrieval_outcome = no_op
        harness_state_module._ISSUED_VALIDATE_FOLLOWUP_RETRIEVAL_OUTCOME = no_op
        try:
            with self.assertRaisesRegex(
                ValueError, "harness_state_projection_dependency_drift"
            ):
                build_e1_followup_harness_state(
                    bound=bound,
                    outcome=clone,
                    store=store,
                    registry=registry,
                    policy=policy,
                )
        finally:
            harness_state_module.validate_followup_retrieval_outcome = original_global
            del harness_state_module._ISSUED_VALIDATE_FOLLOWUP_RETRIEVAL_OUTCOME

        closure_names = set(build_e1_followup_harness_state.__code__.co_freevars)
        self.assertNotIn("outcome_validator", closure_names)
        self.assertNotIn("outcome_validator_pin", closure_names)
        self.assertFalse(
            hasattr(harness_state_module, "_build_e1_followup_harness_state_impl")
        )

        closure_cells = dict(
            zip(
                build_e1_followup_harness_state.__code__.co_freevars,
                build_e1_followup_harness_state.__closure__,
            )
        )
        original_module_pin = closure_cells["module_pin"].cell_contents
        names, members = original_module_pin
        replacement_members = []
        replacement_validator = lambda **_kwargs: None
        for name, issued, issued_type, callable_pin, class_pin in members:
            if name == "validate_followup_retrieval_outcome":
                replacement_members.append(
                    (
                        name,
                        replacement_validator,
                        type(replacement_validator),
                        _callable_pin(replacement_validator),
                        None,
                    )
                )
            else:
                replacement_members.append(
                    (name, issued, issued_type, callable_pin, class_pin)
                )
        closure_cells["module_pin"].cell_contents = (
            names,
            tuple(replacement_members),
        )
        harness_state_module.validate_followup_retrieval_outcome = (
            replacement_validator
        )
        followup_retrieval_module.validate_followup_retrieval_outcome = (
            replacement_validator
        )
        try:
            with self.assertRaisesRegex(
                ValueError, "harness_state_projection_dependency_drift"
            ):
                build_e1_followup_harness_state(
                    bound=bound,
                    outcome=clone,
                    store=store,
                    registry=registry,
                    policy=policy,
                )
        finally:
            closure_cells["module_pin"].cell_contents = original_module_pin
            harness_state_module.validate_followup_retrieval_outcome = original_global
            followup_retrieval_module.validate_followup_retrieval_outcome = (
                original_global
            )

        original_record = followup_retrieval_module._RETRIEVAL_OUTCOME_AUTHORITIES[
            id(outcome)
        ]
        forged_record = (ref(clone), *original_record[1:])
        followup_retrieval_module._RETRIEVAL_OUTCOME_AUTHORITIES[id(clone)] = (
            forged_record
        )
        try:
            with self.assertRaisesRegex(
                ValueError, "followup_outcome_authority_mirror_drift"
            ):
                build_e1_followup_harness_state(
                    bound=bound,
                    outcome=clone,
                    store=store,
                    registry=registry,
                    policy=policy,
                )
        finally:
            followup_retrieval_module._RETRIEVAL_OUTCOME_AUTHORITIES.pop(
                id(clone), None
            )
            followup_retrieval_module._RETRIEVAL_OUTCOME_AUTHORITY_MIRROR.pop(
                id(clone), None
            )
        self.assertIs(
            followup_retrieval_module._RETRIEVAL_OUTCOME_AUTHORITIES[id(outcome)],
            followup_retrieval_module._RETRIEVAL_OUTCOME_AUTHORITY_MIRROR[
                id(outcome)
            ],
        )

        validator = followup_retrieval_module.validate_followup_retrieval_outcome
        original_code = validator.__code__
        validator.__code__ = (lambda **_kwargs: None).__code__
        try:
            with self.assertRaisesRegex(
                ValueError, "harness_state_projection_dependency_drift"
            ):
                build_e1_followup_harness_state(
                    bound=bound,
                    outcome=outcome,
                    store=store,
                    registry=registry,
                    policy=policy,
                )
        finally:
            validator.__code__ = original_code

        original_defaults = validator.__defaults__
        validator.__defaults__ = ()
        try:
            with self.assertRaisesRegex(
                ValueError, "harness_state_projection_dependency_drift"
            ):
                build_e1_followup_harness_state(
                    bound=bound,
                    outcome=outcome,
                    store=store,
                    registry=registry,
                    policy=policy,
                )
        finally:
            validator.__defaults__ = original_defaults

        original_dependency = followup_retrieval_module._require_outcome_authority
        followup_retrieval_module._require_outcome_authority = lambda *_args, **_kwargs: None
        try:
            with self.assertRaisesRegex(
                ValueError, "harness_state_projection_dependency_drift"
            ):
                build_e1_followup_harness_state(
                    bound=bound,
                    outcome=outcome,
                    store=store,
                    registry=registry,
                    policy=policy,
                )
        finally:
            followup_retrieval_module._require_outcome_authority = original_dependency

        helper = harness_state_module._validate_callable_pin
        original_helper_code = helper.__code__
        helper.__code__ = (lambda *_args, **_kwargs: None).__code__
        harness_state_module._ISSUED_E1_CALLABLE_PIN_VALIDATOR = helper
        try:
            with self.assertRaisesRegex(
                ValueError, "harness_state_projection_dependency_drift"
            ):
                build_e1_followup_harness_state(
                    bound=bound,
                    outcome=outcome,
                    store=store,
                    registry=registry,
                    policy=policy,
                )
        finally:
            helper.__code__ = original_helper_code
            del harness_state_module._ISSUED_E1_CALLABLE_PIN_VALIDATOR
        self.assertEqual(len(retriever.calls), before)


if __name__ == "__main__":
    unittest.main()
