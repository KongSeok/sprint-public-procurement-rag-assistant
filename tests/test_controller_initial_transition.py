"""First dense step: source-derived effect, consumption ledger and live successor."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import gc
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest

import midprojectrag.orchestration as orchestration
import midprojectrag.orchestration.execution_contracts as contracts
from midprojectrag.orchestration import (
    HarnessRuntimeBinding,
    build_compare_coverage,
    build_compare_harness_state,
    build_fact_harness_state,
    create_harness_execution_config,
    decide_controller_action,
    execute_retrieval_lane,
    issue_compare_retrieval_obligations,
    issue_fact_retrieval_obligations,
    issue_harness_execution,
    validate_harness_execution,
)
from midprojectrag.retrieval.fusion import HybridChildRetriever
from tests.test_action_effect_receipts import _NeverReranker, _NeverVerifier, _never_clock
from tests.test_retrieval_obligations import (
    _SyntheticLane, _calls, _clone_slots, _compare_bound, _fact_bound, _store,
)


class ControllerInitialTransitionTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.case_number = 0

    def _case(self, *, compare=False, mode="valid", lexical_mode="valid", max_actions=24, max_rounds=1):
        self.case_number += 1
        store = _store()
        dense_log = self.root / f"dense-{self.case_number}.log"
        lexical_log = self.root / f"lexical-{self.case_number}.log"
        specs = tuple((item.evidence_id, item.doc_id) for item in store.evidence)
        runtime = HarnessRuntimeBinding.for_test(
            store=store,
            retriever=HybridChildRetriever(
                store,
                _SyntheticLane(lane="dense", bundle_sha256=store.bundle_sha256,
                               candidate_specs=specs, call_log_path=str(dense_log), mode=mode),
                _SyntheticLane(lane="lexical", bundle_sha256=store.bundle_sha256,
                               candidate_specs=specs, call_log_path=str(lexical_log), mode=lexical_mode),
            ),
            verifier=_NeverVerifier(), reranker=_NeverReranker(), clock=_never_clock,
        )
        config = create_harness_execution_config(
            mode="e1_bounded", max_nonterminal_actions=max_actions,
            max_retrieval_rounds_per_obligation=max_rounds,
        )
        env = dict(store=store, config=config, runtime=runtime)
        if compare:
            bound, _registry = _compare_bound(store)
            coverage = build_compare_coverage(
                bound=bound, store=store, candidate_results={}, verified_evidence={},
                missing_reasons={}, contradicted_evidence={},
            )
            state = build_compare_harness_state(bound=bound, coverage=coverage, store=store)
            issuer = issue_compare_retrieval_obligations
        else:
            bound = _fact_bound(store)
            state = build_fact_harness_state(bound=bound, store=store)
            issuer = issue_fact_retrieval_obligations
        before = issue_harness_execution(state=state, **env)
        decision = decide_controller_action(execution=before, **env)
        claim = contracts._claim_controller_step(execution=before, decision=decision, **env)
        obligation = issuer(bound=bound, **env)[0]
        receipt = execute_retrieval_lane(obligation=obligation, lane="dense", **env)
        projection = contracts._prepare_controller_step_source(
            claim=claim, source_receipt=receipt, **env,
        )
        contracts._source_controller_step(claim=claim, projection=projection, **env)
        bridge = contracts._prepare_controller_structural_effect_bridge(
            claim=claim, projection=projection, target_context=None, **env,
        )
        return dict(env=env, before=before, decision=decision, claim=claim,
                    receipt=receipt, projection=projection, bridge=bridge,
                    dense_log=dense_log, lexical_log=lexical_log)

    @staticmethod
    def _advance(case):
        return contracts._advance_initial_controller_step(bridge=case["bridge"], **case["env"])

    @staticmethod
    def _read(case, after):
        return contracts._require_controller_initial_transition(execution=after, **case["env"])

    def test_first_dense_keeps_exact_state_and_consumes_one_lane(self):
        case = self._case()
        before = case["before"]
        before_payload = before.to_dict()
        after = self._advance(case)
        effect, transition = self._read(case, after)
        self.assertIs(after.state, before.state)
        self.assertIs(after.initial_state, before.initial_state)
        self.assertEqual(before.to_dict(), before_payload)
        self.assertEqual(after.execution_identity_sha256, before.execution_identity_sha256)
        self.assertNotEqual(after.execution_snapshot_sha256, before.execution_snapshot_sha256)
        self.assertEqual((after.step_index, after.ledger.revision), (1, 1))
        self.assertEqual(after.ledger.previous_ledger_sha256, before.ledger.ledger_sha256)
        self.assertEqual(after.ledger.consumed_action_sha256s, (case["bridge"].action_sha256,))
        self.assertEqual(after.ledger.consumed_lane_keys,
                         ((case["bridge"].obligation_key, 1, "dense"),))
        self.assertEqual(after.ledger.round_indexes, (1,))
        self.assertEqual(after.ledger.nonterminal_action_count, 1)
        self.assertEqual(after.ledger.no_progress_streaks, before.ledger.no_progress_streaks)
        self.assertEqual(effect.execution_sha256, before.execution_identity_sha256)
        self.assertEqual(effect.step_index, 1)
        self.assertEqual(effect.before_state_sha256, before.state.state_sha256)
        self.assertEqual(effect.source_receipt_sha256, case["receipt"].receipt_sha256)
        self.assertEqual(effect.outcome, "applied")
        self.assertEqual(effect.ordered_evidence_ids, case["projection"].ordered_evidence_ids)
        self.assertTrue(effect.ordered_evidence_ids)
        self.assertEqual(transition.execution_identity_sha256, before.execution_identity_sha256)
        self.assertEqual(transition.step_index, 1)
        self.assertEqual(transition.controller_decision_sha256, effect.controller_decision_sha256)
        self.assertEqual(transition.effect_sha256, effect.effect_sha256)
        self.assertEqual(transition.before_state_sha256, before.state.state_sha256)
        self.assertEqual(transition.after_state_sha256, after.state.state_sha256)
        self.assertEqual(transition.before_ledger_sha256, before.ledger.ledger_sha256)
        self.assertEqual(transition.after_ledger_sha256, after.ledger.ledger_sha256)
        self.assertIsNone(transition.previous_transition_sha256)
        self.assertEqual(transition.before_progress_sha256, transition.after_progress_sha256)
        self.assertTrue(transition.operational_progress)
        self.assertEqual(after.last_transition_sha256, transition.transition_sha256)
        self.assertEqual((_calls(case["dense_log"]), _calls(case["lexical_log"])), (("dense",), ()))

    def test_compare_consumes_only_first_obligation(self):
        case = self._case(compare=True)
        after = self._advance(case)
        self.assertGreater(len(after.ledger.obligation_keys), 1)
        self.assertEqual(after.ledger.round_indexes, (1,) + (0,) * (len(after.ledger.obligation_keys) - 1))
        self.assertEqual(after.ledger.no_progress_streaks, case["before"].ledger.no_progress_streaks)
        self.assertIs(after.state, case["before"].state)
        self._read(case, after)

    def test_source_outcomes_are_preserved_without_semantic_promotion(self):
        for mode, outcome, called in (
            ("empty", "empty", True),
            ("provider_error", "provider_error", True),
            ("post_call_contract", "contract_error", True),
            ("malformed", "contract_error", True),
            ("pre_call_contract", "contract_error", False),
        ):
            with self.subTest(mode=mode):
                case = self._case(mode=mode)
                after = self._advance(case)
                effect, _transition = self._read(case, after)
                self.assertEqual(effect.outcome, outcome)
                self.assertEqual(effect.call_performed, called)
                self.assertIs(after.state, case["before"].state)
                self.assertEqual(after.ledger.nonterminal_action_count, 1)
                self.assertEqual(after.ledger.round_indexes, (1,))
                self.assertEqual(effect.ordered_evidence_ids, ())
                self.assertEqual(_calls(case["dense_log"]), ("dense",) if called else ())
                serialized = json.dumps(effect.to_dict())
                for secret in ("private-provider", "private-post-call", "qrels", "gold-must-not-leak"):
                    self.assertNotIn(secret, serialized)

    def test_predecessor_and_successor_remain_live(self):
        case = self._case()
        after = self._advance(case)
        validate_harness_execution(execution=case["before"], **case["env"])
        validate_harness_execution(execution=after, **case["env"])
        first = self._read(case, after)
        second = self._read(case, after)
        self.assertIs(first[0], second[0])
        self.assertIs(first[1], second[1])
        self.assertEqual(contracts._controller_step_status(
            execution=case["before"], decision=case["decision"], **case["env"],
        ), "transitioned")

    def test_duplicate_and_concurrent_advance_cannot_mint_another_successor(self):
        case = self._case()
        barrier = Barrier(4)
        def attempt():
            barrier.wait(timeout=10)
            try:
                return self._advance(case)
            except ValueError as error:
                return error
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _index: attempt(), range(4)))
        issued = [result for result in results if not isinstance(result, ValueError)]
        self.assertTrue(issued)
        self.assertEqual(len({id(result) for result in issued}), 1)
        for error in (result for result in results if isinstance(result, ValueError)):
            self.assertRegex(str(error), "consum|transition|sourced|claim.*status|step.*state")
        self._read(case, issued[0])
        self.assertEqual(_calls(case["dense_log"]), ("dense",))

    def test_cloned_bridge_and_mixed_runtime_are_not_authority(self):
        case = self._case()
        with self.assertRaises((TypeError, ValueError)):
            contracts._advance_initial_controller_step(bridge=_clone_slots(case["bridge"]), **case["env"])
        other = self._case()
        with self.assertRaises((TypeError, ValueError)):
            contracts._advance_initial_controller_step(bridge=case["bridge"], **other["env"])
        self.assertEqual(_calls(case["dense_log"]), ("dense",))

    def test_successor_readback_rejects_clones(self):
        case = self._case()
        after = self._advance(case)
        with self.assertRaises((TypeError, ValueError)):
            self._read(case, _clone_slots(after))

    def test_tampered_effect_transition_and_ledger_are_rejected(self):
        for target in ("effect", "transition", "ledger"):
            with self.subTest(target=target):
                case = self._case()
                after = self._advance(case)
                effect, transition = self._read(case, after)
                value, field = {"effect": (effect, "effect_sha256"),
                                "transition": (transition, "transition_sha256"),
                                "ledger": (after.ledger, "ledger_sha256")}[target]
                object.__setattr__(value, field, "0" * 64)
                with self.assertRaises((TypeError, ValueError)):
                    self._read(case, after)

    def test_tuple_and_source_provenance_mutation_invalidates_successor(self):
        for target in ("lane_tuple", "round_tuple", "source"):
            with self.subTest(target=target):
                case = self._case()
                after = self._advance(case)
                if target == "lane_tuple":
                    object.__setattr__(after.ledger, "consumed_lane_keys", ())
                elif target == "round_tuple":
                    object.__setattr__(after.ledger, "round_indexes", (2,))
                else:
                    object.__setattr__(case["receipt"], "receipt_sha256", "0" * 64)
                with self.assertRaises((TypeError, ValueError)):
                    self._read(case, after)
                with self.assertRaises((TypeError, ValueError)):
                    validate_harness_execution(execution=after, **case["env"])

    def test_mid_registration_failure_consumes_claim_without_partial_success(self):
        case = self._case()
        injected = []
        registration_code = contracts._register_harness_execution_successor.__code__
        def fail_registration(frame, event, _argument):
            if event == "call" and frame.f_code is registration_code:
                injected.append(True)
                sys.settrace(None)
                raise RuntimeError("synthetic-registration-failure")
            return fail_registration
        previous_trace = sys.gettrace()
        try:
            sys.settrace(fail_registration)
            with self.assertRaises((RuntimeError, ValueError)):
                self._advance(case)
        finally:
            sys.settrace(previous_trace)
        self.assertEqual(injected, [True])
        self.assertEqual(contracts._controller_step_status(
            execution=case["before"], decision=case["decision"], **case["env"],
        ), "failed")
        with self.assertRaises(ValueError):
            self._advance(case)
        with self.assertRaises(ValueError):
            self._read(case, case["before"])
        self.assertEqual((_calls(case["dense_log"]), _calls(case["lexical_log"])), (("dense",), ()))

    def test_successor_keeps_provenance_alive_when_fixture_is_released(self):
        case = self._case()
        after = self._advance(case)
        env = case["env"]
        del case
        gc.collect()
        validate_harness_execution(execution=after, **env)
        effect, _transition = contracts._require_controller_initial_transition(execution=after, **env)
        self.assertEqual(effect.step_index, 1)

    def test_initial_transition_does_not_dispatch_a_second_action(self):
        case = self._case()
        after = self._advance(case)
        self._read(case, after)
        self.assertEqual(after.step_index, 1)
        self.assertEqual(_calls(case["dense_log"]), ("dense",))
        self.assertEqual(_calls(case["lexical_log"]), ())

    def test_mint_boundary_is_private(self):
        self.assertFalse(hasattr(orchestration, "advance_initial_controller_step"))
        self.assertNotIn("HarnessTransitionReceipt", orchestration.__all__)
        self.assertTrue(callable(contracts._advance_initial_controller_step))


if __name__ == "__main__":
    unittest.main()
