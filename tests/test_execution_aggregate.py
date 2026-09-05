"""EH2.6.d1 controller ledger and execution aggregate contract tests.

This leaf seals only the initial execution authority.  Controller decisions,
effect minting, ledger advancement, reduction, transitions, and run loops remain
deliberately absent until d2/c4/d3.
"""

from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import gc
import inspect
from pathlib import Path
import pickle
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from weakref import ref

import midprojectrag.orchestration.execution_contracts as execution_contracts
from midprojectrag.orchestration import (
    ExecutionLedger,
    HarnessExecution,
    HarnessRuntimeBinding,
    build_compare_coverage,
    build_compare_harness_state,
    build_e1_followup_harness_state,
    build_fact_harness_state,
    create_harness_execution_config,
    issue_harness_execution,
    validate_harness_execution,
)
from midprojectrag.retrieval.fusion import HybridChildRetriever

from tests.test_retrieval_obligations import (
    _SyntheticLane,
    _fact_bound,
    _store,
)
import tests.test_e1_followup_projection as followup_fixtures
import tests.test_harness_state as harness_state_fixtures


_CLOCK_CALLS = 0


def _counting_clock() -> int:
    global _CLOCK_CALLS
    _CLOCK_CALLS += 1
    return 0


class ExecutionAggregateContractTests(unittest.TestCase):
    def setUp(self) -> None:
        global _CLOCK_CALLS
        _CLOCK_CALLS = 0
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.tempdir = Path(self._temporary.name)

    def _case(self, name: str = "initial"):
        store = _store(doc_ids=("doc-a",))
        runtime, dense_log, lexical_log = self._runtime_for_store(store, name)
        config = create_harness_execution_config(mode="e1_bounded")
        bound = _fact_bound(store)
        state = build_fact_harness_state(bound=bound, store=store)
        return store, config, runtime, state, dense_log, lexical_log

    def _runtime_for_store(self, store, name: str):
        dense_log = self.tempdir / f"{name}-dense.log"
        lexical_log = self.tempdir / f"{name}-lexical.log"
        specs = tuple((item.evidence_id, item.doc_id) for item in store.evidence)
        retriever = HybridChildRetriever(
            store,
            _SyntheticLane(
                lane="dense",
                bundle_sha256=store.bundle_sha256,
                candidate_specs=specs,
                call_log_path=str(dense_log),
            ),
            _SyntheticLane(
                lane="lexical",
                bundle_sha256=store.bundle_sha256,
                candidate_specs=specs,
                call_log_path=str(lexical_log),
            ),
        )
        runtime = HarnessRuntimeBinding.for_test(
            store=store,
            retriever=retriever,
            clock=_counting_clock,
        )
        return runtime, dense_log, lexical_log

    @staticmethod
    def _clone_slots(value):
        clone = object.__new__(type(value))
        for name in type(value).__slots__:
            if name != "__weakref__":
                object.__setattr__(clone, name, getattr(value, name))
        return clone

    def test_d1_initial_execution_is_exact_closed_and_non_authorizing(self):
        store, config, runtime, state, dense_log, lexical_log = self._case()

        execution = issue_harness_execution(
            state=state,
            store=store,
            config=config,
            runtime=runtime,
        )
        validate_harness_execution(
            execution=execution,
            store=store,
            config=config,
            runtime=runtime,
        )

        self.assertIs(type(execution), HarnessExecution)
        self.assertIs(type(execution.ledger), ExecutionLedger)
        self.assertIs(execution.initial_state, state)
        self.assertIs(execution.state, state)
        self.assertEqual(execution.stage, "harness_execution")
        self.assertEqual(execution.step_index, 0)
        self.assertIsNone(execution.last_transition_sha256)
        self.assertEqual(execution.ledger.stage, "execution_ledger")
        self.assertEqual(execution.ledger.revision, 0)
        self.assertIsNone(execution.ledger.previous_ledger_sha256)
        self.assertIs(
            execution.ledger.obligation_keys,
            state.progress.required_obligation_keys,
        )
        self.assertEqual(execution.ledger.round_indexes, (0,))
        self.assertEqual(execution.ledger.no_progress_streaks, (0,))
        self.assertEqual(execution.ledger.consumed_action_sha256s, ())
        self.assertEqual(execution.ledger.consumed_lane_keys, ())
        self.assertEqual(execution.ledger.unavailable_action_sha256s, ())
        self.assertEqual(execution.ledger.nonterminal_action_count, 0)

        self.assertEqual(
            set(execution.to_dict()),
            {
                "schema_version",
                "stage",
                "execution_identity_sha256",
                "source_kind",
                "source_binding_sha256",
                "source_receipt_sha256",
                "evidence_bundle_sha256",
                "execution_config_sha256",
                "runtime_binding_sha256",
                "initial_state_sha256",
                "state_sha256",
                "ledger_sha256",
                "last_transition_sha256",
                "step_index",
                "execution_snapshot_sha256",
            },
        )
        self.assertNotIn("state", execution.to_dict())
        self.assertNotIn("ledger", execution.to_dict())
        self.assertNotIn("execution_sha256", execution.to_dict())
        self.assertIs(
            issue_harness_execution(
                state=state,
                store=store,
                config=config,
                runtime=runtime,
            ),
            execution,
        )
        with self.assertRaisesRegex(TypeError, "execution_ledger_factory_required"):
            ExecutionLedger()
        with self.assertRaisesRegex(TypeError, "harness_execution_factory_required"):
            HarnessExecution()

        import midprojectrag.orchestration as public_api

        for forbidden in (
            "ControllerDecisionReceipt",
            "HarnessTransitionReceipt",
            "advance_execution_ledger",
            "consume_execution_action",
            "issue_action_effect",
            "reduce_harness_state",
            "run_harness_execution",
            "step_harness_execution",
        ):
            self.assertFalse(hasattr(public_api, forbidden), forbidden)
        self.assertFalse(dense_log.exists())
        self.assertFalse(lexical_log.exists())
        self.assertEqual(_CLOCK_CALLS, 0)

    def test_d1_clones_nested_identity_drift_and_mixed_dependencies_fail_closed(self):
        store, config, runtime, state, dense_log, lexical_log = self._case("drift")
        execution = issue_harness_execution(
            state=state, store=store, config=config, runtime=runtime
        )

        with self.assertRaisesRegex(ValueError, "runtime_authority_required"):
            validate_harness_execution(
                execution=self._clone_slots(execution),
                store=store,
                config=config,
                runtime=runtime,
            )

        original_obligations = execution.ledger.obligation_keys
        object.__setattr__(
            execution.ledger,
            "obligation_keys",
            tuple(list(original_obligations)),
        )
        self.addCleanup(
            object.__setattr__,
            execution.ledger,
            "obligation_keys",
            original_obligations,
        )
        with self.assertRaisesRegex(ValueError, "nested_identity_drift"):
            validate_harness_execution(
                execution=execution,
                store=store,
                config=config,
                runtime=runtime,
            )

        config_clone = type(config).from_dict(config.to_dict())
        with self.assertRaisesRegex(ValueError, "root_identity_mismatch"):
            issue_harness_execution(
                state=state,
                store=store,
                config=config_clone,
                runtime=runtime,
            )
        other_store, _other_config, other_runtime, _other_state, _, _ = self._case(
            "mixed"
        )
        with self.assertRaises(ValueError):
            validate_harness_execution(
                execution=execution,
                store=other_store,
                config=config,
                runtime=other_runtime,
            )
        rebuilt_state = build_fact_harness_state(
            bound=_fact_bound(store),
            store=store,
        )
        self.assertEqual(rebuilt_state.state_sha256, state.state_sha256)
        with self.assertRaisesRegex(ValueError, "root_identity_mismatch"):
            issue_harness_execution(
                state=rebuilt_state,
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertFalse(dense_log.exists())
        self.assertFalse(lexical_log.exists())
        self.assertEqual(_CLOCK_CALLS, 0)

    def test_d1_copy_pickle_repr_and_recursive_serialization_are_closed(self):
        store, config, runtime, state, dense_log, lexical_log = self._case("closed")
        execution = issue_harness_execution(
            state=state, store=store, config=config, runtime=runtime
        )

        for value, label in (
            (execution, "harness_execution"),
            (execution.ledger, "execution_ledger"),
        ):
            with self.assertRaisesRegex(TypeError, f"{label}_copy_forbidden"):
                copy.copy(value)
            with self.assertRaisesRegex(TypeError, f"{label}_copy_forbidden"):
                copy.deepcopy(value)
            with self.assertRaisesRegex(TypeError, f"{label}_pickle_forbidden"):
                pickle.dumps(value)
            rendered = repr(value)
            self.assertIn("<redacted>", rendered)
            self.assertNotIn(execution.execution_identity_sha256, rendered)
            self.assertFalse(hasattr(type(value), "from_dict"))
        with self.assertRaisesRegex(TypeError, "dataclass instance"):
            asdict(execution)

        self.assertEqual(
            set(execution.ledger.to_dict()),
            {
                "schema_version",
                "stage",
                "execution_identity_sha256",
                "revision",
                "previous_ledger_sha256",
                "obligation_keys",
                "round_indexes",
                "consumed_action_sha256s",
                "consumed_lane_keys",
                "unavailable_action_sha256s",
                "nonterminal_action_count",
                "no_progress_streaks",
                "ledger_sha256",
            },
        )
        serialized = str(execution.to_dict()) + str(execution.ledger.to_dict())
        for forbidden in ("question", "qrels", "expected_answer", "evidence_text"):
            self.assertNotIn(forbidden, serialized)
        self.assertFalse(dense_log.exists())
        self.assertFalse(lexical_log.exists())
        self.assertEqual(_CLOCK_CALLS, 0)

    def test_d1_repeat_is_single_winner_under_concurrency(self):
        store, config, runtime, state, dense_log, lexical_log = self._case(
            "concurrent"
        )

        def issue_once(_index):
            return issue_harness_execution(
                state=state,
                store=store,
                config=config,
                runtime=runtime,
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = tuple(pool.map(issue_once, range(32)))
        self.assertTrue(all(result is results[0] for result in results))
        self.assertFalse(dense_log.exists())
        self.assertFalse(lexical_log.exists())
        self.assertEqual(_CLOCK_CALLS, 0)

    def test_d1_gc_tombstone_prevents_reissue_while_state_root_is_live(self):
        store, config, runtime, state, dense_log, lexical_log = self._case("gc")
        execution = issue_harness_execution(
            state=state, store=store, config=config, runtime=runtime
        )
        execution_weak = ref(execution)
        del execution
        gc.collect()
        self.assertIsNone(execution_weak())

        with self.assertRaisesRegex(ValueError, "already_issued"):
            issue_harness_execution(
                state=state,
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertFalse(dense_log.exists())
        self.assertFalse(lexical_log.exists())
        self.assertEqual(_CLOCK_CALLS, 0)

    def test_d1_dependency_and_class_surface_drift_fail_before_calls(self):
        store, config, runtime, state, dense_log, lexical_log = self._case(
            "dependency"
        )
        execution = issue_harness_execution(
            state=state, store=store, config=config, runtime=runtime
        )

        with patch.object(
            execution_contracts,
            "validate_harness_state",
            lambda **_kwargs: None,
        ):
            with self.assertRaisesRegex(ValueError, "dependency_drift"):
                validate_harness_execution(
                    execution=execution,
                    store=store,
                    config=config,
                    runtime=runtime,
                )
        original_to_dict = ExecutionLedger.to_dict
        with patch.object(ExecutionLedger, "to_dict", lambda _self: {}):
            with self.assertRaisesRegex(ValueError, "dependency_drift"):
                validate_harness_execution(
                    execution=execution,
                    store=store,
                    config=config,
                    runtime=runtime,
                )
        self.assertIs(ExecutionLedger.to_dict, original_to_dict)
        for name, replacement in (
            ("SCHEMA_VERSION", "9.9"),
            ("_CONTROLLER_LANES", frozenset({"poison"})),
            ("_require_hash", lambda *_args: None),
            ("_d1_nonnegative_int", lambda value, _code: value),
            ("_d1_hash_tuple", lambda value, _code: value),
            ("_EXECUTION_LEDGER_TOKEN", object()),
            ("_HARNESS_EXECUTION_TOKEN", object()),
        ):
            with self.subTest(name=name), patch.object(
                execution_contracts,
                name,
                replacement,
            ):
                with self.assertRaisesRegex(ValueError, "dependency_drift"):
                    validate_harness_execution(
                        execution=execution,
                        store=store,
                        config=config,
                        runtime=runtime,
                    )
        self.assertFalse(dense_log.exists())
        self.assertFalse(lexical_log.exists())
        self.assertEqual(_CLOCK_CALLS, 0)

    def test_d1_public_signatures_do_not_accept_source_or_effect_authority(self):
        self.assertEqual(
            tuple(inspect.signature(issue_harness_execution).parameters),
            ("state", "store", "config", "runtime"),
        )
        self.assertEqual(
            tuple(inspect.signature(validate_harness_execution).parameters),
            ("execution", "store", "config", "runtime"),
        )
        for function in (issue_harness_execution, validate_harness_execution):
            parameters = inspect.signature(function).parameters
            for forbidden in (
                "bound",
                "source_receipt",
                "decision",
                "effect",
                "transition",
                "query",
                "gold",
                "qrels",
            ):
                self.assertNotIn(forbidden, parameters)

    def test_d1_compare_and_e1_followup_preserve_canonical_obligation_order(self):
        compare_store, _evidence, compare_bound = (
            harness_state_fixtures._compare_fixture()
        )
        coverage = build_compare_coverage(
            bound=compare_bound,
            store=compare_store,
            candidate_results={},
            verified_evidence={},
            missing_reasons={},
            contradicted_evidence={},
        )
        compare_state = build_compare_harness_state(
            bound=compare_bound,
            coverage=coverage,
            store=compare_store,
        )
        compare_runtime, compare_dense, compare_lexical = self._runtime_for_store(
            compare_store, "compare"
        )
        compare_config = create_harness_execution_config(mode="e1_bounded")
        compare_execution = issue_harness_execution(
            state=compare_state,
            store=compare_store,
            config=compare_config,
            runtime=compare_runtime,
        )
        self.assertEqual(compare_execution.source_kind, "compare")
        self.assertEqual(
            compare_execution.ledger.obligation_keys,
            tuple(slot.key for slot in compare_bound.plan.required_slots),
        )
        self.assertEqual(
            compare_execution.ledger.round_indexes,
            tuple(0 for _ in compare_bound.plan.required_slots),
        )

        followup = followup_fixtures._fixture(slots=())
        (
            followup_store,
            _followup_evidence,
            registry,
            policy,
            bound,
            outcome,
            source_retriever,
        ) = followup
        source_calls = len(source_retriever.calls)
        followup_state = build_e1_followup_harness_state(
            bound=bound,
            outcome=outcome,
            store=followup_store,
            registry=registry,
            policy=policy,
        )
        followup_runtime, followup_dense, followup_lexical = (
            self._runtime_for_store(followup_store, "followup")
        )
        followup_config = create_harness_execution_config(mode="e1_bounded")
        followup_execution = issue_harness_execution(
            state=followup_state,
            store=followup_store,
            config=followup_config,
            runtime=followup_runtime,
        )
        self.assertEqual(followup_execution.source_kind, "follow_up")
        self.assertIs(
            followup_execution.ledger.obligation_keys,
            followup_state.progress.required_obligation_keys,
        )
        self.assertEqual(len(source_retriever.calls), source_calls)
        for path in (
            compare_dense,
            compare_lexical,
            followup_dense,
            followup_lexical,
        ):
            self.assertFalse(path.exists())
        self.assertEqual(_CLOCK_CALLS, 0)

    def test_d1_rejects_e0_config_before_any_execution_call(self):
        store = _store(doc_ids=("doc-a",))
        runtime, dense_log, lexical_log = self._runtime_for_store(store, "e0")
        state = build_fact_harness_state(bound=_fact_bound(store), store=store)
        config = create_harness_execution_config(mode="e0_once")

        with self.assertRaisesRegex(ValueError, "e1_bounded"):
            issue_harness_execution(
                state=state,
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertFalse(dense_log.exists())
        self.assertFalse(lexical_log.exists())
        self.assertEqual(_CLOCK_CALLS, 0)

    def test_d1_rejects_presearched_compare_seed_before_controller_execution(self):
        store, (evidence, _other), bound = harness_state_fixtures._compare_fixture()
        first = bound.plan.required_slots[0].key
        retriever = harness_state_fixtures._Retriever(
            harness_state_fixtures._search_result(store, (evidence,))
        )
        receipt = harness_state_fixtures.execute_compare_slot_search(
            bound=bound,
            store=store,
            slot_key=first,
            retriever=retriever,
        )
        coverage = build_compare_coverage(
            bound=bound,
            store=store,
            candidate_results={first: receipt},
            verified_evidence={},
            missing_reasons={},
            contradicted_evidence={},
        )
        state = build_compare_harness_state(
            bound=bound,
            coverage=coverage,
            store=store,
        )
        runtime, dense_log, lexical_log = self._runtime_for_store(
            store, "presearched-compare"
        )
        config = create_harness_execution_config(mode="e1_bounded")
        before = len(retriever.calls)

        with self.assertRaisesRegex(ValueError, "e1_compare_seed_not_unsearched"):
            issue_harness_execution(
                state=state,
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual(len(retriever.calls), before)
        self.assertFalse(dense_log.exists())
        self.assertFalse(lexical_log.exists())
        self.assertEqual(_CLOCK_CALLS, 0)


if __name__ == "__main__":
    unittest.main()
