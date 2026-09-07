"""Revision-two source outcomes authorize one bounded ordinal-three decision."""

from concurrent.futures import ThreadPoolExecutor
import gc
import inspect
import json
from threading import Barrier
import unittest
from unittest.mock import patch
from weakref import ref

import midprojectrag.orchestration as orchestration
import midprojectrag.orchestration.execution_contracts as contracts
from midprojectrag.orchestration import (
    decide_controller_action,
    validate_controller_decision_receipt,
    validate_harness_execution,
)
import tests.test_controller_lexical_transition as lexical_fixtures
from tests.test_retrieval_obligations import _calls, _clone_slots


class ControllerPostLexicalDecisionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = lexical_fixtures.ControllerLexicalTransitionTests(
            methodName="runTest"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def _case(self, **options):
        case = self.fixture._case(**options)
        case["after"] = self.fixture._execute(case)
        return case

    @staticmethod
    def _decide(case):
        return decide_controller_action(execution=case["after"], **case["env"])

    @staticmethod
    def _calls_snapshot(case):
        return _calls(case["dense_log"]), _calls(case["lexical_log"])

    def _effects(self, case):
        dense = self.fixture.fixture._read(case, case["first"])
        lexical = self.fixture._read(case, case["after"])
        return dense[0], dense[1], lexical[0], lexical[1]

    def _assert_abstain(self, decision, reason):
        self.assertEqual(decision.reason_code, reason)
        self.assertEqual(
            tuple(action.kind for action in decision.allowed_actions),
            ("abstain",),
        )
        self.assertIs(decision.selected_action, decision.allowed_actions[0])
        self.assertIsNone(decision.selected_action.obligation_key)
        self.assertIsNone(decision.selected_action.target_evidence_id)

    def test_revision_two_fact_and_compare_bind_exact_history_and_fuse(self):
        for compare in (False, True):
            with self.subTest(compare=compare):
                case = self._case(compare=compare)
                zero, one, two = case["before"], case["first"], case["after"]
                two_payload = two.to_dict()
                calls = self._calls_snapshot(case)
                decision = self._decide(case)
                dense, dense_transition, lexical, lexical_transition = (
                    self._effects(case)
                )
                self.assertEqual(
                    (
                        decision.decision_ordinal,
                        decision.ledger_revision,
                        decision.previous_transition_sha256,
                    ),
                    (3, 2, two.last_transition_sha256),
                )
                self.assertEqual(
                    tuple(action.kind for action in decision.allowed_actions),
                    ("fuse", "abstain"),
                )
                self.assertIs(decision.selected_action, decision.allowed_actions[0])
                self.assertEqual(
                    decision.selected_action.obligation_key,
                    two.ledger.obligation_keys[0],
                )
                self.assertEqual(decision.reason_code, "first_eligible_nonterminal")
                self.assertEqual(
                    two.ledger.consumed_lane_keys,
                    (
                        (two.ledger.obligation_keys[0], 1, "dense"),
                        (two.ledger.obligation_keys[0], 1, "lexical"),
                    ),
                )
                self.assertEqual(
                    lexical_transition.previous_transition_sha256,
                    dense_transition.transition_sha256,
                )
                self.assertEqual(
                    (dense.outcome, lexical.outcome),
                    ("applied", "applied"),
                )
                authority = contracts._require_harness_execution_authority(two)
                self.assertIs(authority[11], one)
                self.assertIs(authority[12], zero)
                self.assertIs(two.state, one.state)
                for execution in (zero, one, two):
                    validate_harness_execution(execution=execution, **case["env"])
                for execution, receipt in (
                    (zero, case["decision"]),
                    (one, case["second_decision"]),
                    (two, decision),
                ):
                    validate_controller_decision_receipt(
                        receipt=receipt, execution=execution, **case["env"],
                    )
                self.assertEqual(
                    {
                        case["decision"].policy_sha256,
                        case["second_decision"].policy_sha256,
                        decision.policy_sha256,
                    },
                    {contracts._CONTROLLER_DECISION_POLICY_SHA256},
                )
                self.assertEqual(two.to_dict(), two_payload)
                self.assertEqual(self._calls_snapshot(case), calls)

    def test_all_applied_empty_pairs_including_both_empty_are_fuse_eligible(self):
        for dense_mode, lexical_mode in (
            ("valid", "valid"),
            ("valid", "empty"),
            ("empty", "valid"),
            ("empty", "empty"),
        ):
            with self.subTest(dense=dense_mode, lexical=lexical_mode):
                case = self._case(mode=dense_mode, lexical_mode=lexical_mode)
                calls = self._calls_snapshot(case)
                decision = self._decide(case)
                dense, _dense_transition, lexical, _lexical_transition = (
                    self._effects(case)
                )
                self.assertEqual(
                    (dense.outcome, lexical.outcome),
                    (
                        "applied" if dense_mode == "valid" else "empty",
                        "applied" if lexical_mode == "valid" else "empty",
                    ),
                )
                self.assertEqual(decision.selected_action.kind, "fuse")
                self.assertEqual(
                    decision.selected_action.obligation_key,
                    case["after"].ledger.obligation_keys[0],
                )
                self.assertEqual(
                    tuple(action.kind for action in decision.allowed_actions),
                    ("fuse", "abstain"),
                )
                self.assertTrue(
                    all(
                        entry.observation_stage == "unsearched"
                        for entry in case["after"].state.belief.evidence_map
                    )
                )
                self.assertIs(case["after"].state, case["before"].state)
                self.assertEqual(self._calls_snapshot(case), calls)

        compare = self._case(compare=True, mode="empty", lexical_mode="empty")
        decision = self._decide(compare)
        self.assertEqual(decision.selected_action.kind, "fuse")
        self.assertEqual(
            decision.selected_action.obligation_key,
            compare["after"].ledger.obligation_keys[0],
        )
        self.assertGreater(len(compare["after"].ledger.obligation_keys), 1)
        self.assertEqual(
            {item[0] for item in compare["after"].ledger.consumed_lane_keys},
            {compare["after"].ledger.obligation_keys[0]},
        )

    def test_source_error_priority_is_closed_and_sanitized(self):
        cases = (
            (False, "valid", "provider_error", "provider_error"),
            (True, "empty", "provider_error", "provider_error"),
            (False, "provider_error", "valid", "provider_error"),
            (True, "provider_error", "empty", "provider_error"),
            (False, "provider_error", "post_call_contract", "contract_error"),
            (True, "valid", "pre_call_contract", "contract_error"),
        )
        for compare, dense_mode, lexical_mode, reason in cases:
            with self.subTest(
                compare=compare, dense=dense_mode, lexical=lexical_mode
            ):
                case = self._case(
                    compare=compare, mode=dense_mode, lexical_mode=lexical_mode
                )
                calls = self._calls_snapshot(case)
                dense, _dense_transition, lexical, _lexical_transition = (
                    self._effects(case)
                )
                decision = self._decide(case)
                self._assert_abstain(decision, reason)
                if dense_mode == "provider_error":
                    self.assertEqual(dense.outcome, "provider_error")
                if lexical_mode == "provider_error":
                    self.assertEqual(lexical.outcome, "provider_error")
                if lexical_mode.endswith("contract"):
                    self.assertEqual(lexical.outcome, "contract_error")
                payload = json.dumps(decision.to_dict(), sort_keys=True)
                for forbidden in (
                    "private-provider",
                    "private-post-call",
                    "gold-must-not-leak",
                    '"qrels"',
                    '"question"',
                ):
                    self.assertNotIn(forbidden, payload)
                self.assertEqual(self._calls_snapshot(case), calls)

    def test_budget_two_precedes_errors_and_budget_three_permits_fuse(self):
        cases = (
            (2, "valid", "valid", "action_budget_exhausted", "abstain"),
            (
                2,
                "provider_error",
                "post_call_contract",
                "action_budget_exhausted",
                "abstain",
            ),
            (3, "valid", "valid", "first_eligible_nonterminal", "fuse"),
            (
                3,
                "provider_error",
                "post_call_contract",
                "contract_error",
                "abstain",
            ),
        )
        for max_actions, dense_mode, lexical_mode, reason, kind in cases:
            with self.subTest(
                max_actions=max_actions,
                dense=dense_mode,
                lexical=lexical_mode,
            ):
                case = self._case(
                    max_actions=max_actions,
                    mode=dense_mode,
                    lexical_mode=lexical_mode,
                )
                calls = self._calls_snapshot(case)
                decision = self._decide(case)
                self.assertEqual(decision.reason_code, reason)
                self.assertEqual(decision.selected_action.kind, kind)
                self.assertEqual(
                    case["after"].ledger.nonterminal_action_count,
                    2,
                )
                self.assertEqual(self._calls_snapshot(case), calls)

    def test_round_one_and_decision_issuance_do_not_dispatch_more_work(self):
        case = self._case(max_rounds=1)
        calls = self._calls_snapshot(case)
        decision = self._decide(case)
        self.assertEqual(case["after"].ledger.round_indexes, (1,))
        self.assertEqual(decision.selected_action.kind, "fuse")
        self.assertEqual(self._calls_snapshot(case), calls)
        for forbidden_surface in (
            "execute_controller_fusion_step",
            "reduce_controller_state",
            "step_harness_execution",
            "run_harness_execution",
            "issue_harness_run_result",
        ):
            self.assertFalse(hasattr(orchestration, forbidden_surface))

    def test_repeated_and_barrier_concurrent_calls_return_one_exact_object(self):
        case = self._case()
        payload = case["after"].to_dict()
        calls = self._calls_snapshot(case)
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
        self.assertEqual(case["after"].to_dict(), payload)
        self.assertEqual(self._calls_snapshot(case), calls)

    def test_gc_tombstone_prevents_remint_while_snapshot_is_live(self):
        case = self._case()
        calls = self._calls_snapshot(case)
        decision = self._decide(case)
        weak = ref(decision)
        del decision
        gc.collect()
        self.assertIsNone(weak())
        with self.assertRaisesRegex(ValueError, "already_issued"):
            self._decide(case)
        self.assertEqual(self._calls_snapshot(case), calls)

    def test_clones_mixed_graphs_and_wrong_snapshots_fail_closed(self):
        case = self._case()
        decision = self._decide(case)
        calls = self._calls_snapshot(case)
        other = self._case(compare=True)
        for receipt, execution, env in (
            (_clone_slots(decision), case["after"], case["env"]),
            (decision, _clone_slots(case["after"]), case["env"]),
            (decision, case["first"], case["env"]),
            (case["second_decision"], case["after"], case["env"]),
            (decision, other["after"], other["env"]),
        ):
            with self.subTest(receipt=type(receipt), step=execution.step_index):
                with self.assertRaises((TypeError, ValueError)):
                    validate_controller_decision_receipt(
                        receipt=receipt, execution=execution, **env,
                    )
        with self.assertRaises((TypeError, ValueError)):
            decide_controller_action(
                execution=_clone_slots(case["after"]), **case["env"],
            )
        self.assertEqual(self._calls_snapshot(case), calls)

    def test_source_effect_transition_and_ledger_drift_rejects_issuance(self):
        for target in (
            "dense_source",
            "lexical_source",
            "dense_effect",
            "lexical_effect",
            "dense_transition",
            "lexical_transition",
            "ledger_actions",
            "ledger_lanes",
        ):
            with self.subTest(target=target):
                case = self._case()
                calls = self._calls_snapshot(case)
                dense, dense_transition, lexical, lexical_transition = (
                    self._effects(case)
                )
                if target == "dense_source":
                    object.__setattr__(case["receipt"], "receipt_sha256", "0" * 64)
                elif target == "lexical_source":
                    _obligation, receipt = self.fixture._lexical_source(case)
                    object.__setattr__(receipt, "receipt_sha256", "0" * 64)
                elif target == "dense_effect":
                    object.__setattr__(dense, "outcome", "empty")
                elif target == "lexical_effect":
                    object.__setattr__(lexical, "outcome", "empty")
                elif target == "dense_transition":
                    object.__setattr__(
                        dense_transition, "transition_sha256", "0" * 64
                    )
                elif target == "lexical_transition":
                    object.__setattr__(
                        lexical_transition, "transition_sha256", "0" * 64
                    )
                elif target == "ledger_actions":
                    object.__setattr__(
                        case["after"].ledger,
                        "consumed_action_sha256s",
                        case["after"].ledger.consumed_action_sha256s[:1],
                    )
                else:
                    object.__setattr__(
                        case["after"].ledger,
                        "consumed_lane_keys",
                        tuple(reversed(case["after"].ledger.consumed_lane_keys)),
                    )
                with self.assertRaises((TypeError, ValueError)):
                    self._decide(case)
                self.assertEqual(self._calls_snapshot(case), calls)

    def test_reason_selected_action_and_equal_value_tuple_drift_fail_closed(self):
        for target in ("reason", "selected", "action_tuple", "action_kind"):
            with self.subTest(target=target):
                case = self._case()
                decision = self._decide(case)
                calls = self._calls_snapshot(case)
                if target == "reason":
                    object.__setattr__(decision, "reason_code", "provider_error")
                elif target == "selected":
                    object.__setattr__(
                        decision, "selected_action", decision.allowed_actions[1]
                    )
                elif target == "action_tuple":
                    object.__setattr__(
                        decision,
                        "allowed_actions",
                        tuple(list(decision.allowed_actions)),
                    )
                else:
                    object.__setattr__(
                        decision.allowed_actions[0], "kind", "retrieve_lexical"
                    )
                with self.assertRaises((TypeError, ValueError)):
                    validate_controller_decision_receipt(
                        receipt=decision,
                        execution=case["after"],
                        **case["env"],
                    )
                self.assertEqual(self._calls_snapshot(case), calls)

    def test_dependency_pins_and_public_signature_remain_closed(self):
        self.assertEqual(
            tuple(inspect.signature(decide_controller_action).parameters),
            ("execution", "store", "config", "runtime"),
        )
        case = self._case()
        calls = self._calls_snapshot(case)
        for name in (
            "_require_controller_lexical_transition",
            "_require_controller_initial_transition",
            "_require_harness_execution_authority",
        ):
            invoked = []

            def replacement(**_kwargs):
                invoked.append(True)
                return None

            with self.subTest(name=name), patch.object(contracts, name, replacement):
                with self.assertRaisesRegex(ValueError, "dependency_drift"):
                    self._decide(case)
                self.assertEqual(invoked, [])
        decision = self._decide(case)
        self.assertEqual(decision.selected_action.kind, "fuse")
        self.assertEqual(self._calls_snapshot(case), calls)


if __name__ == "__main__":
    unittest.main()
