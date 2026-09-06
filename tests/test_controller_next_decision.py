"""d2.x.a: the next permit is derived from exact dense outcome and consumption."""

from concurrent.futures import ThreadPoolExecutor
import gc
import inspect
import json
from threading import Barrier
import unittest
from weakref import ref

from midprojectrag.orchestration import (
    decide_controller_action,
    validate_controller_decision_receipt,
    validate_harness_execution,
)
import tests.test_controller_initial_transition as transition_fixtures
from tests.test_retrieval_obligations import _calls, _clone_slots


class ControllerNextDecisionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = transition_fixtures.ControllerInitialTransitionTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def _case(self, **options):
        case = self.fixture._case(**options)
        case["after"] = self.fixture._advance(case)
        return case

    @staticmethod
    def _decide(case):
        return decide_controller_action(execution=case["after"], **case["env"])

    def _assert_no_dispatch(self, case, *, dense_called=True):
        self.assertEqual(_calls(case["dense_log"]), ("dense",) if dense_called else ())
        self.assertEqual(_calls(case["lexical_log"]), ())

    def test_successor_chain_and_stable_lexical_action_identity(self):
        case = self._case()
        decision = self._decide(case)
        after = case["after"]
        self.assertEqual(decision.decision_ordinal, 2)
        self.assertEqual(decision.ledger_revision, 1)
        self.assertEqual(decision.previous_transition_sha256, after.last_transition_sha256)
        self.assertEqual(decision.execution_snapshot_sha256, after.execution_snapshot_sha256)
        self.assertEqual(decision.ledger_sha256, after.ledger.ledger_sha256)
        self.assertEqual(decision.state_sha256, after.state.state_sha256)
        self.assertEqual(decision.reason_code, "first_eligible_nonterminal")
        self.assertEqual(tuple(action.kind for action in decision.allowed_actions), ("retrieve_lexical", "abstain"))
        initial_lexical = case["decision"].allowed_actions[1]
        self.assertEqual(decision.selected_action.action_sha256, initial_lexical.action_sha256)
        self.assertNotIn(decision.selected_action.action_sha256, after.ledger.consumed_action_sha256s)
        for execution, receipt in ((case["before"], case["decision"]), (after, decision)):
            validate_harness_execution(execution=execution, **case["env"])
            validate_controller_decision_receipt(receipt=receipt, execution=execution, **case["env"])
        self._assert_no_dispatch(case)

    def test_outcome_mapping_for_fact_and_compare(self):
        for compare in (False, True):
            for mode, kind, reason in (
                ("valid", "retrieve_lexical", "first_eligible_nonterminal"),
                ("empty", "retrieve_lexical", "first_eligible_nonterminal"),
                ("provider_error", "retrieve_lexical", "dense_provider_error_diagnostic"),
                ("post_call_contract", "abstain", "contract_error"),
                ("malformed", "abstain", "contract_error"),
                ("pre_call_contract", "abstain", "contract_error"),
            ):
                with self.subTest(compare=compare, mode=mode):
                    case = self._case(compare=compare, mode=mode)
                    decision = self._decide(case)
                    self.assertEqual(decision.selected_action.kind, kind)
                    self.assertEqual(decision.reason_code, reason)
                    expected_key = case["after"].ledger.obligation_keys[0] if kind == "retrieve_lexical" else None
                    self.assertEqual(decision.selected_action.obligation_key, expected_key)
                    self.assertEqual(tuple(action.kind for action in decision.allowed_actions),
                                     ("retrieve_lexical", "abstain") if kind == "retrieve_lexical" else ("abstain",))
                    self._assert_no_dispatch(case, dense_called=mode != "pre_call_contract")

    def test_action_budget_takes_precedence_over_contract_error(self):
        for mode in ("valid", "empty", "provider_error", "post_call_contract"):
            with self.subTest(mode=mode):
                case = self._case(mode=mode, max_actions=1)
                decision = self._decide(case)
                self.assertEqual(decision.reason_code, "action_budget_exhausted")
                self.assertEqual(tuple(action.kind for action in decision.allowed_actions), ("abstain",))
                self.assertIsNone(decision.selected_action.obligation_key)
                self.assertEqual(case["after"].ledger.nonterminal_action_count, 1)
                self._assert_no_dispatch(case)

    def test_one_round_still_allows_untouched_lexical_in_same_round(self):
        case = self._case(max_rounds=1)
        decision = self._decide(case)
        self.assertEqual(decision.selected_action.kind, "retrieve_lexical")
        self.assertEqual(case["after"].ledger.round_indexes, (1,))
        self._assert_no_dispatch(case)

    def test_one_remaining_action_is_not_an_exhausted_budget(self):
        for compare in (False, True):
            with self.subTest(compare=compare):
                case = self._case(compare=compare, max_actions=2)
                decision = self._decide(case)
                self.assertEqual(decision.selected_action.kind, "retrieve_lexical")
                self.assertEqual(case["after"].ledger.nonterminal_action_count, 1)
                self._assert_no_dispatch(case)

    def test_repeated_and_concurrent_calls_issue_one_exact_decision(self):
        case = self._case()
        before_payload = case["after"].to_dict()
        barrier = Barrier(4)
        def decide_together(_index):
            barrier.wait(timeout=10)
            return self._decide(case)
        with ThreadPoolExecutor(max_workers=4) as pool:
            decisions = list(pool.map(decide_together, range(4)))
        self.assertEqual(len({id(item) for item in decisions}), 1)
        self.assertIs(self._decide(case), decisions[0])
        self.assertEqual(case["after"].to_dict(), before_payload)
        self._assert_no_dispatch(case)

    def test_gc_does_not_allow_permit_remint_for_live_successor(self):
        case = self._case()
        decision = self._decide(case)
        weak = ref(decision)
        del decision
        gc.collect()
        self.assertIsNone(weak())
        with self.assertRaisesRegex(ValueError, "already_issued"):
            self._decide(case)
        self._assert_no_dispatch(case)

    def test_source_effect_and_ledger_drift_reject_before_another_call(self):
        for target in ("source", "effect", "ledger"):
            with self.subTest(target=target):
                case = self._case()
                decision = self._decide(case)
                effect, _transition = self.fixture._read(case, case["after"])
                if target == "source":
                    object.__setattr__(case["receipt"], "receipt_sha256", "0" * 64)
                elif target == "effect":
                    object.__setattr__(effect, "outcome", "empty")
                else:
                    object.__setattr__(case["after"].ledger, "consumed_lane_keys", ())
                with self.assertRaises((ValueError, TypeError)):
                    self._decide(case)
                with self.assertRaises((ValueError, TypeError)):
                    validate_controller_decision_receipt(receipt=decision, execution=case["after"], **case["env"])
                self._assert_no_dispatch(case)

    def test_equal_value_clone_and_other_snapshot_cannot_validate(self):
        case = self._case()
        decision = self._decide(case)
        with self.assertRaises((ValueError, TypeError)):
            validate_controller_decision_receipt(receipt=_clone_slots(decision), execution=case["after"], **case["env"])
        with self.assertRaises((ValueError, TypeError)):
            validate_controller_decision_receipt(receipt=decision, execution=case["before"], **case["env"])
        with self.assertRaises((ValueError, TypeError)):
            validate_controller_decision_receipt(receipt=case["decision"], execution=case["after"], **case["env"])
        other = self._case()
        with self.assertRaises((ValueError, TypeError)):
            validate_controller_decision_receipt(receipt=decision, execution=other["after"], **other["env"])
        self._assert_no_dispatch(case)

    def test_reason_and_equal_value_action_tuple_are_sealed(self):
        for target in ("reason", "action_tuple"):
            with self.subTest(target=target):
                case = self._case()
                decision = self._decide(case)
                if target == "reason":
                    object.__setattr__(decision, "reason_code", "dense_provider_error_diagnostic")
                else:
                    object.__setattr__(decision, "allowed_actions", tuple(list(decision.allowed_actions)))
                with self.assertRaises((ValueError, TypeError)):
                    validate_controller_decision_receipt(receipt=decision, execution=case["after"], **case["env"])
                self._assert_no_dispatch(case)

    def test_public_signature_and_safe_decision_projection(self):
        self.assertEqual(tuple(inspect.signature(decide_controller_action).parameters),
                         ("execution", "store", "config", "runtime"))
        case = self._case(mode="provider_error")
        payload = self._decide(case).to_dict()
        text = json.dumps(payload)
        for forbidden in ("private-provider", "gold-must-not-leak", '"qrels"', '"question"'):
            self.assertNotIn(forbidden, text)
        self.assertEqual(payload["previous_transition_sha256"], case["after"].last_transition_sha256)


if __name__ == "__main__":
    unittest.main()
