"""Controller's selected lexical permit executes exactly once with chained provenance."""

from concurrent.futures import ThreadPoolExecutor
import gc
import inspect
import sys
from threading import Barrier
import unittest
from weakref import ref

import midprojectrag.orchestration as orchestration
import midprojectrag.orchestration.execution_contracts as contracts
from midprojectrag.orchestration import (
    decide_controller_action, validate_controller_decision_receipt,
    validate_harness_execution, validate_lane_search_receipt,
)
import tests.test_controller_initial_transition as initial_fixtures
from tests.test_retrieval_obligations import _calls, _clone_slots


class ControllerLexicalTransitionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = initial_fixtures.ControllerInitialTransitionTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def _case(self, **options):
        case = self.fixture._case(**options)
        case["first"] = self.fixture._advance(case)
        case["second_decision"] = decide_controller_action(execution=case["first"], **case["env"])
        return case

    @staticmethod
    def _execute(case):
        return contracts._execute_controller_lexical_step(
            execution=case["first"], decision=case["second_decision"], **case["env"],
        )

    @staticmethod
    def _read(case, after):
        return contracts._require_controller_lexical_transition(execution=after, **case["env"])

    def _lexical_source(self, case):
        dense_authority = contracts._read_lane_search_receipt_authority(case["receipt"])
        obligation = object.__getattribute__(dense_authority, "obligation")
        matches = []
        for authority in dict.values(contracts._ISSUED_LANE_SEARCH_RECEIPT_AUTHORITIES):
            receipt = object.__getattribute__(authority, "weak")()
            if (
                object.__getattribute__(authority, "obligation") is obligation
                and receipt is not None
                and object.__getattribute__(receipt, "lane") == "lexical"
            ):
                matches.append(receipt)
        self.assertEqual(len(matches), 1)
        return obligation, matches[0]

    def test_dense_and_lexical_execute_once_and_seal_revision_two(self):
        case = self._case()
        first = case["first"]
        before_payload = first.to_dict()
        after = self._execute(case)
        effect, transition = self._read(case, after)
        obligation, lexical_receipt = self._lexical_source(case)
        self.assertEqual((_calls(case["dense_log"]), _calls(case["lexical_log"])), (("dense",), ("lexical",)))
        self.assertIs(after.state, first.state)
        self.assertIs(after.initial_state, first.initial_state)
        self.assertEqual(first.to_dict(), before_payload)
        self.assertEqual((after.step_index, after.ledger.revision, after.ledger.nonterminal_action_count), (2, 2, 2))
        self.assertEqual(after.ledger.previous_ledger_sha256, first.ledger.ledger_sha256)
        self.assertEqual(after.ledger.round_indexes, (1,))
        self.assertEqual(after.ledger.no_progress_streaks, first.ledger.no_progress_streaks)
        self.assertEqual(after.ledger.consumed_action_sha256s,
                         first.ledger.consumed_action_sha256s + (case["second_decision"].selected_action.action_sha256,))
        key = first.ledger.obligation_keys[0]
        self.assertEqual(after.ledger.consumed_lane_keys, ((key, 1, "dense"), (key, 1, "lexical")))
        self.assertEqual((effect.step_index, effect.action_kind, effect.outcome), (2, "retrieve_lexical", "applied"))
        self.assertEqual(effect.execution_sha256, first.execution_identity_sha256)
        self.assertEqual(effect.controller_decision_sha256, case["second_decision"].decision_sha256)
        self.assertEqual(effect.source_receipt_sha256, lexical_receipt.receipt_sha256)
        self.assertEqual(effect.ordered_evidence_ids, lexical_receipt.ordered_evidence_ids)
        self.assertTrue(effect.call_performed)
        self.assertTrue(effect.ordered_evidence_ids)
        self.assertIs(contracts._read_lane_search_receipt_authority(lexical_receipt).obligation,
                      obligation)
        for field in (
            "execution_binding_sha256", "obligation_sha256", "obligation_key",
            "round_index", "query_sha256", "scope_state", "scope_origin",
            "scope_doc_ids", "scope_sha256", "evidence_store_sha256",
            "execution_config_sha256", "runtime_binding_sha256",
            "source_receipt_sha256",
        ):
            self.assertEqual(getattr(lexical_receipt, field), getattr(case["receipt"], field))
        self.assertEqual(transition.previous_transition_sha256, first.last_transition_sha256)
        self.assertEqual(transition.before_ledger_sha256, first.ledger.ledger_sha256)
        self.assertEqual(transition.after_ledger_sha256, after.ledger.ledger_sha256)
        self.assertEqual(transition.effect_sha256, effect.effect_sha256)
        self.assertEqual(transition.before_progress_sha256, transition.after_progress_sha256)
        self.assertEqual(after.last_transition_sha256, transition.transition_sha256)

    def test_compare_reuses_first_obligation_without_reissuing_dead_siblings(self):
        case = self._case(compare=True)
        gc.collect()
        after = self._execute(case)
        self.assertEqual(after.ledger.round_indexes, (1,) + (0,) * (len(after.ledger.obligation_keys) - 1))
        self.assertEqual({item[0] for item in after.ledger.consumed_lane_keys}, {after.ledger.obligation_keys[0]})
        self.assertEqual((_calls(case["dense_log"]), _calls(case["lexical_log"])), (("dense",), ("lexical",)))
        effect, _transition = self._read(case, after)
        self.assertEqual(effect.obligation_key, after.ledger.obligation_keys[0])
        obligation, lexical_receipt = self._lexical_source(case)
        self.assertIs(contracts._read_lane_search_receipt_authority(case["receipt"]).obligation,
                      obligation)
        for field in ("query_sha256", "scope_state", "scope_origin",
                      "scope_doc_ids", "scope_sha256"):
            self.assertEqual(getattr(lexical_receipt, field), getattr(case["receipt"], field))

    def test_lexical_outcomes_are_recorded_without_state_promotion(self):
        for dense_mode in ("valid", "empty"):
            for lexical_mode, outcome, called in (
                ("valid", "applied", True), ("empty", "empty", True),
                ("provider_error", "provider_error", True),
                ("post_call_contract", "contract_error", True),
                ("malformed", "contract_error", True),
                ("pre_call_contract", "contract_error", False),
            ):
                with self.subTest(dense_mode=dense_mode, lexical_mode=lexical_mode):
                    case = self._case(mode=dense_mode, lexical_mode=lexical_mode)
                    dense_effect, _first_transition = self.fixture._read(case, case["first"])
                    after = self._execute(case)
                    effect, _transition = self._read(case, after)
                    _obligation, lexical_receipt = self._lexical_source(case)
                    self.assertEqual(dense_effect.outcome,
                                     "applied" if dense_mode == "valid" else "empty")
                    self.assertEqual(effect.outcome, outcome)
                    self.assertEqual(effect.call_performed, called)
                    self.assertEqual(effect.ordered_evidence_ids,
                                     lexical_receipt.ordered_evidence_ids)
                    self.assertIs(after.state, case["first"].state)
                    self.assertEqual(after.ledger.nonterminal_action_count, 2)
                    self.assertEqual(_calls(case["lexical_log"]),
                                     ("lexical",) if called else ())

    def test_provider_error_diagnostic_lexical_does_not_erase_dense_error(self):
        case = self._case(mode="provider_error")
        self.assertEqual(case["second_decision"].reason_code, "dense_provider_error_diagnostic")
        after = self._execute(case)
        dense, _first_transition = self.fixture._read(case, case["first"])
        lexical, _second_transition = self._read(case, after)
        self.assertEqual(dense.outcome, "provider_error")
        self.assertEqual(lexical.outcome, "applied")
        self.assertIs(after.state, case["first"].state)
        with self.assertRaises(ValueError):
            decide_controller_action(execution=after, **case["env"])
        self.assertEqual(_calls(case["lexical_log"]), ("lexical",))

    def test_contract_error_and_exhausted_budget_do_not_dispatch_lexical(self):
        for options in ({"mode": "post_call_contract"}, {"max_actions": 1}):
            with self.subTest(options=options):
                case = self._case(**options)
                self.assertEqual(case["second_decision"].selected_action.kind, "abstain")
                with self.assertRaises((ValueError, TypeError)):
                    self._execute(case)
                self.assertEqual(_calls(case["lexical_log"]), ())

    def test_cloned_mixed_and_wrong_permits_fail_before_lexical_dispatch(self):
        for target in (
            "execution_clone", "decision_clone", "first_decision", "other_decision",
            "other_execution", "store", "config", "runtime",
        ):
            with self.subTest(target=target):
                case = self._case()
                execution = case["first"]
                decision = case["second_decision"]
                env = dict(case["env"])
                other = None
                if target == "execution_clone":
                    execution = _clone_slots(execution)
                elif target == "decision_clone":
                    decision = _clone_slots(decision)
                elif target == "first_decision":
                    decision = case["decision"]
                else:
                    other = self._case()
                    if target == "other_decision":
                        decision = other["second_decision"]
                    elif target == "other_execution":
                        execution = other["first"]
                    else:
                        env[target] = other["env"][target]
                with self.assertRaises((TypeError, ValueError)):
                    contracts._execute_controller_lexical_step(
                        execution=execution, decision=decision, **env,
                    )
                self.assertEqual(_calls(case["lexical_log"]), ())
                if other is not None:
                    self.assertEqual(_calls(other["lexical_log"]), ())

    def test_revision_chain_and_both_sources_survive_gc_and_revalidate(self):
        case = self._case()
        zero, one = case["before"], case["first"]
        two = self._execute(case)
        obligation, lexical_receipt = self._lexical_source(case)
        dense_receipt = case.pop("receipt")
        obligation_weak = ref(obligation)
        dense_weak = ref(dense_receipt)
        lexical_weak = ref(lexical_receipt)
        for name in ("claim", "projection", "bridge"):
            case.pop(name)
        del obligation, dense_receipt, lexical_receipt
        gc.collect()
        self.assertIsNotNone(obligation_weak())
        self.assertIsNotNone(dense_weak())
        self.assertIsNotNone(lexical_weak())
        for execution in (zero, one, two):
            validate_harness_execution(execution=execution, **case["env"])
        validate_controller_decision_receipt(
            receipt=case["second_decision"], execution=one, **case["env"],
        )
        for receipt in (dense_weak(), lexical_weak()):
            validate_lane_search_receipt(
                receipt=receipt, obligation=obligation_weak(), **case["env"],
            )
        self.fixture._read(case, one)
        self._read(case, two)
        with self.assertRaises((TypeError, ValueError)):
            self.fixture._read(case, two)
        with self.assertRaises((TypeError, ValueError)):
            self._read(case, one)
        authority = contracts._require_harness_execution_authority(two)
        self.assertIs(authority[11], one)
        self.assertIs(authority[12], zero)
        self.assertIsNot(authority[11], authority[12])

    def test_duplicate_and_concurrent_execution_dispatches_lexical_once(self):
        case = self._case()
        barrier = Barrier(4)

        def attempt(_index):
            barrier.wait(timeout=10)
            try:
                return self._execute(case)
            except (TypeError, ValueError) as error:
                return error

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(attempt, range(4)))
        issued = [result for result in results if not isinstance(result, Exception)]
        rejected = [result for result in results if isinstance(result, Exception)]
        self.assertEqual(len(issued), 1)
        self.assertEqual(len(rejected), 3)
        self._read(case, issued[0])
        with self.assertRaises((TypeError, ValueError)):
            self._execute(case)
        self.assertEqual(_calls(case["lexical_log"]), ("lexical",))

    def test_failure_after_lexical_dispatch_consumes_claim_without_successor(self):
        case = self._case()
        injected = []
        registration_code = contracts._register_harness_execution_successor.__code__

        def fail_registration(frame, event, _argument):
            if event == "call" and frame.f_code is registration_code:
                injected.append(True)
                sys.settrace(None)
                raise RuntimeError("synthetic-lexical-registration-failure")
            return fail_registration

        previous_trace = sys.gettrace()
        try:
            sys.settrace(fail_registration)
            with self.assertRaises(RuntimeError):
                self._execute(case)
        finally:
            sys.settrace(previous_trace)
        self.assertEqual(injected, [True])
        self.assertEqual(contracts._controller_step_status(
            execution=case["first"], decision=case["second_decision"], **case["env"],
        ), "failed")
        with self.assertRaises((TypeError, ValueError)):
            self._execute(case)
        with self.assertRaises((TypeError, ValueError)):
            self._read(case, case["first"])
        self.assertEqual(_calls(case["lexical_log"]), ("lexical",))

    def test_lexical_source_effect_transition_and_ledger_drift_fail_closed(self):
        for target in ("source", "effect", "transition", "ledger"):
            with self.subTest(target=target):
                case = self._case()
                after = self._execute(case)
                effect, transition = self._read(case, after)
                if target == "source":
                    _obligation, lexical_receipt = self._lexical_source(case)
                    object.__setattr__(lexical_receipt, "receipt_sha256", "0" * 64)
                elif target == "effect":
                    object.__setattr__(effect, "effect_sha256", "0" * 64)
                elif target == "transition":
                    object.__setattr__(transition, "transition_sha256", "0" * 64)
                else:
                    object.__setattr__(after.ledger, "consumed_lane_keys", ())
                with self.assertRaises((TypeError, ValueError)):
                    self._read(case, after)
                with self.assertRaises((TypeError, ValueError)):
                    validate_harness_execution(execution=after, **case["env"])
                self.assertEqual(_calls(case["lexical_log"]), ("lexical",))

    def test_serialized_clone_and_dependency_drift_are_non_authorizing(self):
        case = self._case()
        after = self._execute(case)
        with self.assertRaises((TypeError, ValueError)):
            self._read(case, _clone_slots(after))

        for name in ("_execute_controller_lexical_step", "_require_controller_lexical_transition"):
            with self.subTest(global_name=name):
                current = getattr(contracts, name)
                authentic_execute = contracts._execute_controller_lexical_step

                def replacement(**_kwargs):
                    return None

                setattr(contracts, name, replacement)
                try:
                    with self.assertRaisesRegex(ValueError, "dependency_drift"):
                        validate_harness_execution(execution=case["first"], **case["env"])
                    with self.assertRaisesRegex(ValueError, "dependency_drift"):
                        authentic_execute(
                            execution=case["first"], decision=case["second_decision"],
                            **case["env"],
                        )
                finally:
                    setattr(contracts, name, current)

    def test_private_entrypoint_signature_does_not_expand_public_api(self):
        self.assertEqual(
            tuple(inspect.signature(contracts._execute_controller_lexical_step).parameters),
            ("execution", "decision", "store", "config", "runtime"),
        )
        self.assertFalse(hasattr(orchestration, "execute_controller_lexical_step"))
        self.assertNotIn("HarnessTransitionReceipt", orchestration.__all__)
        self.assertTrue(callable(contracts._require_controller_lexical_transition))


if __name__ == "__main__":
    unittest.main()
