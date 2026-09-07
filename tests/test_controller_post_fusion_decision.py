"""Exact revision-three fusion state authorizes one bounded ordinal-four decision."""

from concurrent.futures import ThreadPoolExecutor
import gc
import inspect
from threading import Barrier
import unittest
from unittest.mock import patch
from weakref import ref

import midprojectrag.orchestration as orchestration
import midprojectrag.orchestration.execution_contracts as contracts
from midprojectrag.orchestration import (
    create_harness_execution_config,
    decide_controller_action,
    validate_controller_decision_receipt,
    validate_harness_execution,
)
import tests.test_controller_first_fusion_transition as fusion_fixtures
import tests.test_controller_initial_transition as initial_fixtures
from tests.test_action_effect_receipts import _NeverReranker, _NeverVerifier
from tests.test_retrieval_obligations import _calls, _clone_slots


class ControllerPostFusionDecisionTests(unittest.TestCase):
    _NON_DECISION_AUTHORITY_NAMES = (
        "_ISSUED_SEMANTIC_OBLIGATION_AUTHORITIES",
        "_ISSUED_PARENT_CONTEXT_RECEIPT_AUTHORITIES",
        "_ISSUED_BRIDGE_CONTEXT_RECEIPT_AUTHORITIES",
        "_ISSUED_RERANK_RECEIPT_AUTHORITIES",
        "_ISSUED_SEMANTIC_RECEIPT_AUTHORITIES",
        "_ISSUED_ABSENCE_CONFIRMATION_AUTHORITIES",
    )

    def setUp(self):
        self.fixture = fusion_fixtures.ControllerFirstFusionTransitionTests(
            methodName="runTest"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        _NeverVerifier.calls = 0
        _NeverReranker.calls = 0

    def _case(self, **options):
        case = self.fixture._case(**options)
        case["third"] = self.fixture._execute(case)
        return case

    @staticmethod
    def _decide(case):
        return decide_controller_action(execution=case["third"], **case["env"])

    @staticmethod
    def _calls_snapshot(case):
        return _calls(case["dense_log"]), _calls(case["lexical_log"])

    def _no_work_snapshot(self, case):
        return (
            self._calls_snapshot(case),
            _NeverVerifier.calls,
            _NeverReranker.calls,
            tuple(
                len(getattr(contracts, name))
                for name in self._NON_DECISION_AUTHORITY_NAMES
            ),
            tuple(
                case[name].to_dict()
                for name in ("before", "first", "second", "third")
            ),
        )

    @staticmethod
    def _effects(case):
        dense_effect, dense_transition = (
            contracts._require_controller_initial_transition(
                execution=case["first"], **case["env"]
            )
        )
        lexical_effect, lexical_transition = (
            contracts._require_controller_lexical_transition(
                execution=case["second"], **case["env"]
            )
        )
        fusion_effect, fusion_transition = (
            contracts._require_controller_first_fusion_transition(
                execution=case["third"], **case["env"]
            )
        )
        return (
            dense_effect,
            dense_transition,
            lexical_effect,
            lexical_transition,
            fusion_effect,
            fusion_transition,
        )

    def _assert_live_decision(self, case, decision, expected_kind):
        execution = case["third"]
        entry = execution.state.belief.evidence_map[0]
        self.assertEqual(
            (
                decision.decision_ordinal,
                decision.ledger_revision,
                decision.previous_transition_sha256,
            ),
            (4, 3, execution.last_transition_sha256),
        )
        self.assertEqual(decision.reason_code, "first_eligible_nonterminal")
        self.assertEqual(
            tuple(action.kind for action in decision.allowed_actions),
            (expected_kind, "abstain"),
        )
        self.assertIs(decision.selected_action, decision.allowed_actions[0])
        self.assertEqual(
            decision.selected_action.obligation_key,
            entry.obligation_key,
        )
        self.assertIsNone(decision.allowed_actions[1].obligation_key)
        self.assertIsNone(decision.allowed_actions[1].target_evidence_id)
        if expected_kind == "verify_slot":
            self.assertIsNone(decision.selected_action.target_evidence_id)
        else:
            self.assertEqual(
                decision.selected_action.target_evidence_id,
                sorted(entry.candidate_evidence_ids)[0],
            )
        validate_controller_decision_receipt(
            receipt=decision,
            execution=execution,
            **case["env"],
        )

    def test_fact_compare_all_normal_pairs_bind_state_and_choose_first_action(self):
        for compare in (False, True):
            for dense_mode, lexical_mode in (
                ("valid", "valid"),
                ("valid", "empty"),
                ("empty", "valid"),
                ("empty", "empty"),
            ):
                with self.subTest(
                    compare=compare,
                    dense=dense_mode,
                    lexical=lexical_mode,
                ):
                    case = self._case(
                        compare=compare,
                        mode=dense_mode,
                        lexical_mode=lexical_mode,
                    )
                    before = self._no_work_snapshot(case)
                    decision = self._decide(case)
                    fusion_effect = self._effects(case)[4]
                    expected_outcome = (
                        "empty"
                        if dense_mode == lexical_mode == "empty"
                        else "applied"
                    )
                    expected_kind = (
                        "verify_slot"
                        if expected_outcome == "empty"
                        else "expand_parent"
                    )
                    self.assertEqual(fusion_effect.outcome, expected_outcome)
                    self._assert_live_decision(case, decision, expected_kind)

                    execution = case["third"]
                    entry = execution.state.belief.evidence_map[0]
                    self.assertIs(
                        entry.candidate_evidence_ids,
                        fusion_effect.ordered_evidence_ids,
                    )
                    self.assertEqual(entry.verified_evidence_ids, ())
                    self.assertEqual(
                        execution.state.progress.open_obligation_keys,
                        execution.ledger.obligation_keys,
                    )
                    self.assertEqual(
                        (
                            execution.state.progress.slot_coverage_ratio,
                            execution.state.progress.answerability,
                            execution.state.progress.normal_stop_allowed,
                            execution.state.progress.abstain_required,
                        ),
                        (0.0, "in_progress", False, False),
                    )
                    if expected_kind == "expand_parent":
                        seed = case["env"]["store"].get(
                            decision.selected_action.target_evidence_id
                        )
                        parent = case["env"]["store"].parent(seed.parent_id)
                        self.assertEqual(parent.parent_id, seed.parent_id)
                    else:
                        self.assertEqual(
                            execution.state.progress.provisional_missing_obligation_keys,
                            (entry.obligation_key,),
                        )
                        self.assertEqual(
                            execution.state.progress.confirmed_missing_obligation_keys,
                            (),
                        )
                    self.assertTrue(
                        all(
                            current is previous
                            for current, previous in zip(
                                execution.state.belief.evidence_map[1:],
                                case["second"].state.belief.evidence_map[1:],
                            )
                        )
                    )
                    for predecessor in (
                        case["before"],
                        case["first"],
                        case["second"],
                        execution,
                    ):
                        validate_harness_execution(
                            execution=predecessor, **case["env"]
                        )
                    for predecessor, prior_decision in (
                        (case["before"], case["decision"]),
                        (case["first"], case["second_decision"]),
                        (case["second"], case["third_decision"]),
                    ):
                        validate_controller_decision_receipt(
                            receipt=prior_decision,
                            execution=predecessor,
                            **case["env"],
                        )
                    self.assertEqual(self._no_work_snapshot(case), before)

    def test_budget_three_abstains_and_budget_four_allows_parent(self):
        for maximum, modes, reason, kinds in (
            (3, ("valid", "valid"), "action_budget_exhausted", ("abstain",)),
            (3, ("empty", "empty"), "action_budget_exhausted", ("abstain",)),
            (
                4,
                ("valid", "valid"),
                "first_eligible_nonterminal",
                ("expand_parent", "abstain"),
            ),
            (
                4,
                ("empty", "empty"),
                "first_eligible_nonterminal",
                ("verify_slot", "abstain"),
            ),
        ):
            with self.subTest(maximum=maximum, modes=modes):
                case = self._case(
                    max_actions=maximum,
                    mode=modes[0],
                    lexical_mode=modes[1],
                )
                before = self._no_work_snapshot(case)
                decision = self._decide(case)
                self.assertEqual(decision.reason_code, reason)
                self.assertEqual(
                    tuple(action.kind for action in decision.allowed_actions),
                    kinds,
                )
                self.assertIs(decision.selected_action, decision.allowed_actions[0])
                if maximum == 3:
                    self.assertIsNone(decision.selected_action.obligation_key)
                    self.assertIsNone(decision.selected_action.target_evidence_id)
                self.assertEqual(self._no_work_snapshot(case), before)

    def test_round_one_is_authentic_and_round_cap_two_rejects_before_dispatch(self):
        case = self._case(max_rounds=1)
        before = self._no_work_snapshot(case)
        decision = self._decide(case)
        self.assertEqual(case["third"].ledger.round_indexes, (1,))
        self.assertEqual(decision.selected_action.kind, "expand_parent")
        self.assertEqual(self._no_work_snapshot(case), before)

        initial = self.fixture.fixture.fixture
        case_number = initial.case_number + 1
        with self.assertRaisesRegex(
            ValueError, "^retrieval_rounds_not_pinned_to_one$"
        ):
            self.fixture._case(max_rounds=2)
        self.assertEqual(
            (
                _calls(initial.root / f"dense-{case_number}.log"),
                _calls(initial.root / f"lexical-{case_number}.log"),
                _NeverVerifier.calls,
                _NeverReranker.calls,
            ),
            ((), (), 0, 0),
        )

    def test_config_bound_one_uses_first_sorted_seed_without_reordering_state(self):
        def bounded_config(**kwargs):
            return create_harness_execution_config(
                **kwargs,
                max_context_targets_per_obligation=1,
            )

        with patch.object(
            initial_fixtures,
            "create_harness_execution_config",
            bounded_config,
        ):
            case = self._case()
        candidates = case["third"].state.belief.evidence_map[0].candidate_evidence_ids
        self.assertGreater(len(candidates), 1)
        retained_order = tuple(candidates)
        owner = contracts._require_controller_source_owner(
            execution=case["third"], **case["env"]
        )
        _, _, rerank_k, final_budget = contracts._source_owner_plan_budget(
            owner.source
        )
        quota = min(
            case["env"]["config"].max_context_targets_per_obligation,
            final_budget,
            rerank_k,
            len(candidates),
        )
        self.assertEqual(quota, 1)
        decision = self._decide(case)
        self.assertEqual(
            decision.selected_action.target_evidence_id,
            tuple(sorted(candidates)[:quota])[0],
        )
        self.assertEqual(
            case["third"].state.belief.evidence_map[0].candidate_evidence_ids,
            retained_order,
        )

    def test_empty_is_exhaustion_intent_only_and_never_invokes_verifier(self):
        case = self._case(mode="empty", lexical_mode="empty")
        before = self._no_work_snapshot(case)
        decision = self._decide(case)
        self._assert_live_decision(case, decision, "verify_slot")
        state = case["third"].state
        entry = state.belief.evidence_map[0]
        self.assertEqual(entry.observation_stage, "provisional_missing")
        self.assertEqual(entry.candidate_evidence_ids, ())
        self.assertEqual(state.progress.confirmed_missing_obligation_keys, ())
        self.assertEqual((_NeverVerifier.calls, _NeverReranker.calls), (0, 0))
        self.assertEqual(self._no_work_snapshot(case), before)

    def test_repeated_and_barrier_concurrent_calls_return_one_exact_object(self):
        case = self._case(compare=True)
        before = self._no_work_snapshot(case)
        barrier = Barrier(4)

        def decide_together(_index):
            barrier.wait(timeout=10)
            return self._decide(case)

        with ThreadPoolExecutor(max_workers=4) as pool:
            decisions = tuple(pool.map(decide_together, range(4)))
        self.assertTrue(all(decision is decisions[0] for decision in decisions))
        self.assertIs(self._decide(case), decisions[0])
        self.assertIs(
            self._decide(case).selected_action,
            decisions[0].selected_action,
        )
        self.assertEqual(self._no_work_snapshot(case), before)

    def test_gc_tombstone_prevents_remint_while_snapshot_is_live(self):
        case = self._case()
        before = self._no_work_snapshot(case)
        decision = self._decide(case)
        weak = ref(decision)
        del decision
        gc.collect()
        self.assertIsNone(weak())
        with self.assertRaisesRegex(ValueError, "already_issued"):
            self._decide(case)
        self.assertEqual(self._no_work_snapshot(case), before)

    def test_clones_mixed_graphs_and_unsupported_later_snapshot_fail_closed(self):
        case = self._case()
        other = self._case(compare=True)
        decision = self._decide(case)
        before = self._no_work_snapshot(case)
        for receipt, execution, env in (
            (_clone_slots(decision), case["third"], case["env"]),
            (decision, _clone_slots(case["third"]), case["env"]),
            (decision, case["second"], case["env"]),
            (case["third_decision"], case["third"], case["env"]),
            (decision, other["third"], other["env"]),
        ):
            with self.subTest(receipt=type(receipt), step=execution.step_index):
                with self.assertRaises((TypeError, ValueError)):
                    validate_controller_decision_receipt(
                        receipt=receipt,
                        execution=execution,
                        **env,
                    )
        with self.assertRaises((TypeError, ValueError)):
            decide_controller_action(
                execution=_clone_slots(case["third"]), **case["env"]
            )
        later = _clone_slots(case["third"])
        object.__setattr__(later, "step_index", 4)
        with self.assertRaises((TypeError, ValueError)):
            decide_controller_action(execution=later, **case["env"])
        self.assertEqual(self._no_work_snapshot(case), before)

    def test_source_state_owner_effect_transition_and_ledger_drift_fail_closed(self):
        case = self._case()
        effects = self._effects(case)
        dense_effect, dense_transition = effects[:2]
        lexical_effect, lexical_transition = effects[2:4]
        fusion_effect, fusion_transition = effects[4:]
        obligation, dense, lexical = self.fixture._sources(case)
        fusion = self.fixture._fusion_sources(obligation)[0]
        entry = case["third"].state.belief.evidence_map[0]
        owner = contracts._require_controller_source_owner(
            execution=case["third"], **case["env"]
        )
        budget = owner.source.planning.plan.budget
        mutations = (
            (dense, "receipt_sha256", "0" * 64),
            (lexical, "receipt_sha256", "0" * 64),
            (fusion, "receipt_sha256", "0" * 64),
            (dense_effect, "source_receipt_sha256", "0" * 64),
            (lexical_effect, "source_receipt_sha256", "0" * 64),
            (fusion_effect, "source_receipt_sha256", "0" * 64),
            (
                entry,
                "candidate_evidence_ids",
                tuple(list(entry.candidate_evidence_ids)),
            ),
            (budget, "final_evidence_budget", 0),
            (dense_transition, "transition_sha256", "0" * 64),
            (lexical_transition, "transition_sha256", "0" * 64),
            (fusion_transition, "transition_sha256", "0" * 64),
            (
                case["third"].ledger,
                "consumed_action_sha256s",
                tuple(list(case["third"].ledger.consumed_action_sha256s)),
            ),
            (
                case["third"].ledger,
                "consumed_lane_keys",
                tuple(list(case["third"].ledger.consumed_lane_keys)),
            ),
        )
        before = self._no_work_snapshot(case)
        for target, attribute, replacement in mutations:
            with self.subTest(attribute=attribute):
                original = object.__getattribute__(target, attribute)
                object.__setattr__(target, attribute, replacement)
                try:
                    with self.assertRaises((TypeError, ValueError)):
                        self._decide(case)
                    self.assertEqual(self._no_work_snapshot(case)[0:4], before[0:4])
                finally:
                    object.__setattr__(target, attribute, original)
        decision = self._decide(case)
        self.assertEqual(decision.selected_action.kind, "expand_parent")

    def test_reason_action_target_and_equal_value_tuple_drift_fail_readback(self):
        case = self._case()
        decision = self._decide(case)
        before = self._no_work_snapshot(case)
        mutations = (
            (decision, "reason_code", "provider_error"),
            (decision, "reason_code", "contract_error"),
            (
                decision,
                "reason_code",
                "dense_provider_error_diagnostic",
            ),
            (decision, "reason_code", "action_budget_exhausted"),
            (decision, "selected_action", decision.allowed_actions[1]),
            (
                decision,
                "allowed_actions",
                tuple(list(decision.allowed_actions)),
            ),
            (
                decision.allowed_actions[0],
                "target_evidence_id",
                "not-store-backed-evidence",
            ),
        )
        for target, attribute, replacement in mutations:
            with self.subTest(attribute=attribute):
                original = object.__getattribute__(target, attribute)
                object.__setattr__(target, attribute, replacement)
                try:
                    with self.assertRaises((TypeError, ValueError)):
                        validate_controller_decision_receipt(
                            receipt=decision,
                            execution=case["third"],
                            **case["env"],
                        )
                finally:
                    object.__setattr__(target, attribute, original)
        validate_controller_decision_receipt(
            receipt=decision,
            execution=case["third"],
            **case["env"],
        )
        self.assertEqual(self._no_work_snapshot(case), before)

    def test_dependency_pins_and_public_surface_remain_closed(self):
        self.assertEqual(
            tuple(inspect.signature(decide_controller_action).parameters),
            ("execution", "store", "config", "runtime"),
        )
        case = self._case()
        before = self._no_work_snapshot(case)
        for name in (
            "_require_controller_first_fusion_transition",
            "_require_controller_lexical_transition",
            "_require_controller_initial_transition",
            "_require_controller_source_owner",
            "_source_owner_plan_budget",
            "_d2_post_fusion_action_plan",
        ):
            invoked = []

            def replacement(**_kwargs):
                invoked.append(True)
                return None

            with self.subTest(name=name), patch.object(
                contracts, name, replacement
            ):
                with self.assertRaisesRegex(ValueError, "dependency_drift"):
                    self._decide(case)
                self.assertEqual(invoked, [])
        decision = self._decide(case)
        self.assertEqual(decision.selected_action.kind, "expand_parent")
        self.assertEqual(self._no_work_snapshot(case), before)
        for forbidden_surface in (
            "execute_controller_parent_context_step",
            "execute_controller_verify_slot_step",
            "step_harness_execution",
            "run_harness_execution",
            "issue_harness_run_result",
        ):
            self.assertFalse(hasattr(orchestration, forbidden_surface))


if __name__ == "__main__":
    unittest.main()
