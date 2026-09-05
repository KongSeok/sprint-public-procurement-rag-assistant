"""EH2.6.d2 controller decision permit contract tests.

The first RED intentionally names the new public surface.  EH2.5's state-only
``ActionDecisionTrace`` is not accepted as a controller/effect permit.
"""

from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import gc
import inspect
import pickle
import unittest
from unittest.mock import patch
from weakref import ref

import midprojectrag.orchestration as orchestration
import midprojectrag.orchestration.execution_contracts as execution_contracts
from midprojectrag.orchestration import (
    ControllerAction,
    ControllerDecisionReceipt,
    build_compare_coverage,
    build_compare_harness_state,
    build_e1_followup_harness_state,
    create_harness_execution_config,
    decide_controller_action,
    issue_harness_execution,
    validate_controller_decision_receipt,
)

import tests.test_execution_aggregate as execution_fixtures
import tests.test_action_effect_receipt_contract as effect_fixtures


class ControllerDecisionReceiptContractTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture = execution_fixtures.ExecutionAggregateContractTests(
            methodName="runTest"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self._fixture = fixture

    def tearDown(self) -> None:
        self.assertEqual(execution_fixtures._CLOCK_CALLS, 0)

    def _issued(self, name: str):
        store, config, runtime, state, dense_log, lexical_log = (
            self._fixture._case(name)
        )
        execution = issue_harness_execution(
            state=state,
            store=store,
            config=config,
            runtime=runtime,
        )
        decision = decide_controller_action(
            execution=execution,
            store=store,
            config=config,
            runtime=runtime,
        )
        return (
            store,
            config,
            runtime,
            state,
            execution,
            decision,
            dense_log,
            lexical_log,
        )

    def test_d2_initial_fact_decision_is_execution_and_ledger_bound(self):
        store, config, runtime, state, dense_log, lexical_log = (
            self._fixture._case("d2-initial")
        )
        execution = issue_harness_execution(
            state=state,
            store=store,
            config=config,
            runtime=runtime,
        )

        decision = decide_controller_action(
            execution=execution,
            store=store,
            config=config,
            runtime=runtime,
        )
        validate_controller_decision_receipt(
            receipt=decision,
            execution=execution,
            store=store,
            config=config,
            runtime=runtime,
        )

        self.assertIs(type(decision), ControllerDecisionReceipt)
        self.assertIs(type(decision.selected_action), ControllerAction)
        self.assertEqual(decision.stage, "controller_decision")
        self.assertEqual(
            decision.execution_identity_sha256,
            execution.execution_identity_sha256,
        )
        self.assertEqual(
            decision.execution_snapshot_sha256,
            execution.execution_snapshot_sha256,
        )
        self.assertEqual(decision.state_sha256, execution.state.state_sha256)
        self.assertEqual(decision.ledger_sha256, execution.ledger.ledger_sha256)
        self.assertEqual(decision.ledger_revision, 0)
        self.assertIsNone(decision.previous_transition_sha256)
        self.assertEqual(decision.decision_ordinal, 1)
        self.assertIs(decision.selected_action, decision.allowed_actions[0])
        self.assertEqual(decision.selected_action.kind, "retrieve_dense")
        self.assertEqual(
            decision.selected_action.obligation_key,
            execution.ledger.obligation_keys[0],
        )
        self.assertEqual(decision.reason_code, "first_eligible_nonterminal")
        self.assertIs(
            decide_controller_action(
                execution=execution,
                store=store,
                config=config,
                runtime=runtime,
            ),
            decision,
        )

        serialized = decision.to_dict()
        self.assertEqual(
            set(serialized),
            {
                "schema_version",
                "stage",
                "policy_id",
                "policy_sha256",
                "execution_identity_sha256",
                "execution_snapshot_sha256",
                "state_sha256",
                "ledger_sha256",
                "ledger_revision",
                "previous_transition_sha256",
                "decision_ordinal",
                "allowed_actions",
                "allowed_actions_sha256",
                "selected_action",
                "reason_code",
                "decision_sha256",
            },
        )
        for forbidden in (
            "state",
            "ledger",
            "query",
            "scope",
            "gold",
            "qrels",
            "effect",
            "answer",
            "citation",
        ):
            self.assertNotIn(forbidden, serialized)
        for forbidden_surface in (
            "issue_action_effect",
            "advance_execution_ledger",
            "reduce_harness_state",
            "step_harness_execution",
            "run_harness_execution",
        ):
            self.assertFalse(hasattr(orchestration, forbidden_surface))
        self.assertFalse(dense_log.exists())
        self.assertFalse(lexical_log.exists())

    def test_d2_initial_compare_order_is_obligation_major_and_selected_first(self):
        store, _evidence, bound = (
            execution_fixtures.harness_state_fixtures._compare_fixture()
        )
        coverage = build_compare_coverage(
            bound=bound,
            store=store,
            candidate_results={},
            verified_evidence={},
            missing_reasons={},
            contradicted_evidence={},
        )
        state = build_compare_harness_state(
            bound=bound,
            coverage=coverage,
            store=store,
        )
        runtime, dense_log, lexical_log = self._fixture._runtime_for_store(
            store, "d2-compare"
        )
        config = create_harness_execution_config(mode="e1_bounded")
        execution = issue_harness_execution(
            state=state,
            store=store,
            config=config,
            runtime=runtime,
        )
        receipt = decide_controller_action(
            execution=execution,
            store=store,
            config=config,
            runtime=runtime,
        )

        expected = []
        for key in execution.ledger.obligation_keys:
            expected.extend(
                (
                    ("retrieve_dense", key, None),
                    ("retrieve_lexical", key, None),
                )
            )
        expected.append(("abstain", None, None))
        self.assertEqual(
            tuple(
                (action.kind, action.obligation_key, action.target_evidence_id)
                for action in receipt.allowed_actions
            ),
            tuple(expected),
        )
        self.assertIs(receipt.selected_action, receipt.allowed_actions[0])
        self.assertFalse(dense_log.exists())
        self.assertFalse(lexical_log.exists())

    def test_d2_followup_fails_closed_until_source_authority_exists(self):
        (
            store,
            _evidence,
            registry,
            policy,
            bound,
            outcome,
            source_retriever,
        ) = execution_fixtures.followup_fixtures._fixture(slots=())
        source_calls = len(source_retriever.calls)
        state = build_e1_followup_harness_state(
            bound=bound,
            outcome=outcome,
            store=store,
            registry=registry,
            policy=policy,
        )
        runtime, dense_log, lexical_log = self._fixture._runtime_for_store(
            store, "d2-followup"
        )
        config = create_harness_execution_config(mode="e1_bounded")
        execution = issue_harness_execution(
            state=state,
            store=store,
            config=config,
            runtime=runtime,
        )

        with self.assertRaisesRegex(ValueError, "source_authority_not_ready"):
            decide_controller_action(
                execution=execution,
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual(len(source_retriever.calls), source_calls)
        self.assertFalse(dense_log.exists())
        self.assertFalse(lexical_log.exists())

    def test_d2_clone_nested_action_and_mixed_graph_fail_closed(self):
        (
            store,
            config,
            runtime,
            _state,
            execution,
            decision,
            dense_log,
            lexical_log,
        ) = self._issued("d2-drift")

        decision_clone = object.__new__(ControllerDecisionReceipt)
        for name in ControllerDecisionReceipt.__slots__:
            if name != "__weakref__":
                object.__setattr__(decision_clone, name, getattr(decision, name))
        with self.assertRaisesRegex(ValueError, "runtime_authority_required"):
            validate_controller_decision_receipt(
                receipt=decision_clone,
                execution=execution,
                store=store,
                config=config,
                runtime=runtime,
            )

        original_actions = decision.allowed_actions
        object.__setattr__(decision, "allowed_actions", tuple(list(original_actions)))
        self.addCleanup(
            object.__setattr__, decision, "allowed_actions", original_actions
        )
        with self.assertRaisesRegex(ValueError, "nested_identity_drift"):
            validate_controller_decision_receipt(
                receipt=decision,
                execution=execution,
                store=store,
                config=config,
                runtime=runtime,
            )
        object.__setattr__(decision, "allowed_actions", original_actions)

        first = original_actions[0]
        action_clone = object.__new__(ControllerAction)
        for name in ControllerAction.__slots__:
            if name != "__weakref__":
                object.__setattr__(action_clone, name, getattr(first, name))
        forged_actions = (action_clone, *original_actions[1:])
        object.__setattr__(decision, "allowed_actions", forged_actions)
        self.addCleanup(
            object.__setattr__, decision, "allowed_actions", original_actions
        )
        with self.assertRaisesRegex(ValueError, "nested_identity_drift"):
            validate_controller_decision_receipt(
                receipt=decision,
                execution=execution,
                store=store,
                config=config,
                runtime=runtime,
            )
        object.__setattr__(decision, "allowed_actions", original_actions)

        other_store, other_config, other_runtime, _other_state, _, _ = (
            self._fixture._case("d2-mixed")
        )
        with self.assertRaises(ValueError):
            validate_controller_decision_receipt(
                receipt=decision,
                execution=execution,
                store=other_store,
                config=other_config,
                runtime=other_runtime,
            )
        self.assertFalse(dense_log.exists())
        self.assertFalse(lexical_log.exists())

    def test_d2_repeat_is_single_winner_under_concurrency(self):
        store, config, runtime, state, dense_log, lexical_log = (
            self._fixture._case("d2-concurrent")
        )
        execution = issue_harness_execution(
            state=state,
            store=store,
            config=config,
            runtime=runtime,
        )

        def decide_once(_index):
            return decide_controller_action(
                execution=execution,
                store=store,
                config=config,
                runtime=runtime,
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            receipts = tuple(pool.map(decide_once, range(32)))
        self.assertTrue(all(receipt is receipts[0] for receipt in receipts))
        self.assertFalse(dense_log.exists())
        self.assertFalse(lexical_log.exists())

    def test_d2_gc_tombstone_prevents_remint_while_execution_is_live(self):
        (
            store,
            config,
            runtime,
            _state,
            execution,
            decision,
            dense_log,
            lexical_log,
        ) = self._issued("d2-gc")
        decision_weak = ref(decision)
        del decision
        gc.collect()
        self.assertIsNone(decision_weak())

        with self.assertRaisesRegex(ValueError, "already_issued"):
            decide_controller_action(
                execution=execution,
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertFalse(dense_log.exists())
        self.assertFalse(lexical_log.exists())

    def test_d2_values_are_closed_and_eh25_or_effect_values_do_not_promote(self):
        (
            store,
            config,
            runtime,
            state,
            execution,
            decision,
            dense_log,
            lexical_log,
        ) = self._issued("d2-closed")
        for value, label in (
            (decision, "controller_decision"),
            (decision.selected_action, "controller_action"),
        ):
            with self.assertRaisesRegex(TypeError, f"{label}_copy_forbidden"):
                copy.copy(value)
            with self.assertRaisesRegex(TypeError, f"{label}_copy_forbidden"):
                copy.deepcopy(value)
            with self.assertRaisesRegex(TypeError, f"{label}_pickle_forbidden"):
                pickle.dumps(value)
            self.assertEqual(repr(value), f"{type(value).__name__}(<redacted>)")
            self.assertFalse(hasattr(type(value), "from_dict"))
        with self.assertRaisesRegex(TypeError, "dataclass instance"):
            asdict(decision)
        with self.assertRaises(TypeError):
            ControllerAction()
        with self.assertRaises(TypeError):
            ControllerDecisionReceipt()

        preview = orchestration.decide_harness_action(state, store=store)
        with self.assertRaisesRegex(TypeError, "controller_decision_receipt_required"):
            validate_controller_decision_receipt(
                receipt=preview,
                execution=execution,
                store=store,
                config=config,
                runtime=runtime,
            )
        structural_effect = effect_fixtures._make()
        with self.assertRaisesRegex(TypeError, "controller_decision_receipt_required"):
            validate_controller_decision_receipt(
                receipt=structural_effect,
                execution=execution,
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertNotEqual(
            preview.execution_identity_sha256,
            decision.execution_identity_sha256,
        )
        self.assertFalse(dense_log.exists())
        self.assertFalse(lexical_log.exists())

    def test_d2_signatures_surface_and_dependency_drift_are_closed(self):
        self.assertEqual(
            tuple(inspect.signature(decide_controller_action).parameters),
            ("execution", "store", "config", "runtime"),
        )
        self.assertEqual(
            tuple(
                inspect.signature(
                    validate_controller_decision_receipt
                ).parameters
            ),
            ("receipt", "execution", "store", "config", "runtime"),
        )
        for function in (
            decide_controller_action,
            validate_controller_decision_receipt,
        ):
            for forbidden in (
                "action",
                "query",
                "scope",
                "evidence_id",
                "previous",
                "transition",
                "capability",
                "gold",
                "qrels",
            ):
                self.assertNotIn(forbidden, inspect.signature(function).parameters)

        (
            store,
            config,
            runtime,
            _state,
            execution,
            decision,
            dense_log,
            lexical_log,
        ) = self._issued("d2-dependency")
        for name, replacement in (
            ("_CONTROLLER_DECISION_POLICY_SHA256", "f" * 64),
            ("_d2_initial_action_specs", lambda _execution: ()),
            ("_CONTROLLER_ACTION_TOKEN", object()),
            ("_CONTROLLER_DECISION_TOKEN", object()),
        ):
            with self.subTest(name=name), patch.object(
                execution_contracts, name, replacement
            ):
                with self.assertRaisesRegex(ValueError, "dependency_drift"):
                    validate_controller_decision_receipt(
                        receipt=decision,
                        execution=execution,
                        store=store,
                        config=config,
                        runtime=runtime,
                    )
        with patch.object(ControllerAction, "to_dict", lambda _self: {}):
            with self.assertRaisesRegex(ValueError, "dependency_drift"):
                validate_controller_decision_receipt(
                    receipt=decision,
                    execution=execution,
                    store=store,
                    config=config,
                    runtime=runtime,
                )
        for forbidden_surface in (
            "issue_action_effect",
            "advance_execution_ledger",
            "reduce_harness_state",
            "step_harness_execution",
            "run_harness_execution",
            "replay_controller_decision",
        ):
            self.assertFalse(hasattr(orchestration, forbidden_surface))
        self.assertFalse(dense_log.exists())
        self.assertFalse(lexical_log.exists())


if __name__ == "__main__":
    unittest.main()
