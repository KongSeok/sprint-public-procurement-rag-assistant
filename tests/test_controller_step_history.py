"""EH2.6.c4.0.c one-step claim/history contract tests."""

from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
import gc
import inspect
from pathlib import Path
import pickle
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
from weakref import ref

import midprojectrag.orchestration as orchestration
import midprojectrag.orchestration.execution_contracts as execution_contracts
from midprojectrag.orchestration import (
    HarnessRuntimeBinding,
    build_fact_harness_state,
    create_harness_execution_config,
    decide_controller_action,
    execute_retrieval_lane,
    issue_fact_retrieval_obligations,
    issue_harness_execution,
)
from midprojectrag.retrieval.fusion import HybridChildRetriever

from tests.test_action_effect_receipts import (
    _NeverReranker,
    _NeverVerifier,
    _never_clock,
)
from tests.test_retrieval_obligations import (
    _SyntheticLane,
    _calls,
    _fact_bound,
    _store,
)


class ControllerStepHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.tempdir = Path(self._temporary.name)

    def _unexecuted_case(self, *, dense_delay_seconds=0.0):
        store = _store(doc_ids=("doc-a",))
        dense_log = self.tempdir / "dense.log"
        lexical_log = self.tempdir / "lexical.log"
        retriever = HybridChildRetriever(
            store,
            _SyntheticLane(
                lane="dense",
                bundle_sha256=store.bundle_sha256,
                candidate_specs=(),
                call_log_path=str(dense_log),
                delay_seconds=dense_delay_seconds,
            ),
            _SyntheticLane(
                lane="lexical",
                bundle_sha256=store.bundle_sha256,
                candidate_specs=(),
                call_log_path=str(lexical_log),
            ),
        )
        runtime = HarnessRuntimeBinding.for_test(
            store=store,
            retriever=retriever,
            verifier=_NeverVerifier(),
            reranker=_NeverReranker(),
            clock=_never_clock,
        )
        config = create_harness_execution_config(mode="e1_bounded")
        bound = _fact_bound(store)
        state = build_fact_harness_state(bound=bound, store=store)
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
            bound,
            execution,
            decision,
            dense_log,
            lexical_log,
        )

    @staticmethod
    def _status(case) -> str:
        store, config, runtime, _bound, execution, decision, *_logs = case
        return execution_contracts._controller_step_status(
            execution=execution,
            decision=decision,
            store=store,
            config=config,
            runtime=runtime,
        )

    @staticmethod
    def _claim(case):
        store, config, runtime, _bound, execution, decision, *_logs = case
        return execution_contracts._claim_controller_step(
            execution=execution,
            decision=decision,
            store=store,
            config=config,
            runtime=runtime,
        )

    def _source(self, case, claim):
        (
            store,
            config,
            runtime,
            bound,
            execution,
            decision,
            dense_log,
            lexical_log,
        ) = case
        obligation = issue_fact_retrieval_obligations(
            bound=bound,
            store=store,
            config=config,
            runtime=runtime,
        )[0]
        receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        projection = execution_contracts._prepare_controller_step_source(
            claim=claim,
            source_receipt=receipt,
            store=store,
            config=config,
            runtime=runtime,
        )
        execution_contracts._source_controller_step(
            claim=claim,
            projection=projection,
            store=store,
            config=config,
            runtime=runtime,
        )
        return projection, receipt, dense_log, lexical_log

    def test_private_boundary_and_signatures_exist(self):
        self.assertTrue(callable(execution_contracts._claim_controller_step))
        self.assertTrue(
            callable(execution_contracts._prepare_controller_step_source)
        )
        self.assertEqual(
            tuple(
                inspect.signature(
                    execution_contracts._claim_controller_step
                ).parameters
            ),
            ("execution", "decision", "store", "config", "runtime"),
        )
        self.assertNotIn("ControllerStepClaim", orchestration.__all__)
        self.assertFalse(hasattr(orchestration, "claim_controller_step"))
        self.assertFalse(
            hasattr(orchestration, "prepare_controller_step_source")
        )

    def test_pristine_to_claimed_performs_no_provider_call(self):
        case = self._unexecuted_case()
        dense_log, lexical_log = case[-2:]
        self.assertEqual(self._status(case), "pristine")

        claim = self._claim(case)

        self.assertIs(claim.execution, case[4])
        self.assertIs(claim.decision, case[5])
        self.assertIs(claim.selected_action, case[5].selected_action)
        self.assertEqual(self._status(case), "claimed")
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), ((), ()))

    def test_decision_claim_then_live_source_is_the_only_success_order(self):
        case = self._unexecuted_case()
        claim = self._claim(case)

        projection, receipt, dense_log, lexical_log = self._source(case, claim)

        self.assertIs(projection.source_receipt, receipt)
        self.assertEqual(self._status(case), "sourced")
        self.assertEqual(
            (_calls(dense_log), _calls(lexical_log)), (("dense",), ())
        )

    def test_concurrent_claim_has_exactly_one_winner(self):
        case = self._unexecuted_case()

        def attempt(_index):
            try:
                return self._claim(case)
            except ValueError as exc:
                return str(exc)

        with ThreadPoolExecutor(max_workers=16) as pool:
            results = tuple(pool.map(attempt, range(32)))

        claims = tuple(
            item
            for item in results
            if type(item) is execution_contracts._ControllerStepClaim
        )
        failures = tuple(item for item in results if type(item) is str)
        self.assertEqual(len(claims), 1)
        self.assertEqual(len(failures), 31)
        self.assertTrue(
            all(value == "controller_step_already_consumed" for value in failures)
        )
        self.assertEqual(self._status(case), "claimed")

    def test_preflight_rejection_does_not_create_history(self):
        case = self._unexecuted_case()
        with patch.object(
            execution_contracts,
            "validate_controller_decision_receipt",
            lambda **_kwargs: None,
        ):
            with self.assertRaisesRegex(
                ValueError, "harness_runtime_validation_dependency_drift"
            ):
                self._claim(case)

        self.assertEqual(self._status(case), "pristine")
        self.assertEqual((_calls(case[-2]), _calls(case[-1])), ((), ()))

    def test_claim_is_immutable_nonserializable_and_clone_has_no_authority(self):
        case = self._unexecuted_case()
        claim = self._claim(case)
        with self.assertRaisesRegex(
            AttributeError, "controller_step_claim_immutable"
        ):
            claim.step_key = ()
        with self.assertRaisesRegex(
            TypeError, "controller_step_claim_copy_forbidden"
        ):
            copy.copy(claim)
        with self.assertRaisesRegex(
            TypeError, "controller_step_claim_copy_forbidden"
        ):
            copy.deepcopy(claim)
        with self.assertRaisesRegex(
            TypeError, "controller_step_claim_pickle_forbidden"
        ):
            pickle.dumps(claim)
        forged = object.__new__(type(claim))
        for name in type(claim).__slots__:
            if name != "__weakref__":
                object.__setattr__(forged, name, getattr(claim, name))
        with self.assertRaisesRegex(
            ValueError, "controller_step_claim_authority_required"
        ):
            execution_contracts._fail_controller_step(claim=forged)
        self.assertFalse(hasattr(type(claim), "_create"))
        self.assertEqual(self._status(case), "claimed")

    def test_exact_claim_forced_mutation_permanently_tombstones_step(self):
        case = self._unexecuted_case()
        claim = self._claim(case)
        selected_action = claim.selected_action
        object.__setattr__(claim, "selected_action", object())

        with self.assertRaisesRegex(
            ValueError, "controller_step_claim_authority_required"
        ):
            execution_contracts._fail_controller_step(claim=claim)

        object.__setattr__(claim, "selected_action", selected_action)
        self.assertEqual(self._status(case), "failed")
        with self.assertRaisesRegex(ValueError, "controller_step_terminal"):
            execution_contracts._fail_controller_step(claim=claim)

    def test_explicit_fail_tombstones_a_sourced_step(self):
        case = self._unexecuted_case()
        claim = self._claim(case)
        _projection, _receipt, dense_log, lexical_log = self._source(case, claim)
        self.assertEqual(self._status(case), "sourced")

        execution_contracts._fail_controller_step(claim=claim)

        self.assertEqual(self._status(case), "failed")
        with self.assertRaisesRegex(ValueError, "controller_step_already_consumed"):
            self._claim(case)
        self.assertEqual(
            (_calls(dense_log), _calls(lexical_log)), (("dense",), ())
        )

    def test_structural_projection_clone_is_rejected_without_state_change(self):
        case = self._unexecuted_case()
        claim = self._claim(case)
        store, config, runtime, bound, execution, decision, *_logs = case
        obligation = issue_fact_retrieval_obligations(
            bound=bound,
            store=store,
            config=config,
            runtime=runtime,
        )[0]
        receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        projection = execution_contracts._prepare_controller_step_source(
            claim=claim,
            source_receipt=receipt,
            store=store,
            config=config,
            runtime=runtime,
        )
        forged = object.__new__(type(projection))
        for name in type(projection).__slots__:
            if name != "__weakref__":
                object.__setattr__(forged, name, getattr(projection, name))

        with self.assertRaisesRegex(
            ValueError,
            "controller_source_outcome_projection_authority_required",
        ):
            execution_contracts._source_controller_step(
                claim=claim,
                projection=forged,
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual(self._status(case), "claimed")
        execution_contracts._fail_controller_step(claim=claim)
        self.assertEqual(self._status(case), "failed")

    def test_direct_resolver_projection_has_no_step_authority(self):
        case = self._unexecuted_case()
        claim = self._claim(case)
        store, config, runtime, bound, execution, decision, *_logs = case
        obligation = issue_fact_retrieval_obligations(
            bound=bound,
            store=store,
            config=config,
            runtime=runtime,
        )[0]
        receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        projection = execution_contracts._resolve_controller_source_outcome(
            execution=execution,
            decision=decision,
            source_receipt=receipt,
            store=store,
            config=config,
            runtime=runtime,
        )

        with self.assertRaisesRegex(
            ValueError, "controller_step_source_not_prepared"
        ):
            execution_contracts._source_controller_step(
                claim=claim,
                projection=projection,
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual(self._status(case), "claimed")
        execution_contracts._fail_controller_step(claim=claim)

    def test_receipt_completed_before_claim_cannot_be_sourced_retroactively(self):
        case = self._unexecuted_case()
        store, config, runtime, bound, execution, decision, *_logs = case
        obligation = issue_fact_retrieval_obligations(
            bound=bound,
            store=store,
            config=config,
            runtime=runtime,
        )[0]
        receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        claim = self._claim(case)

        with self.assertRaisesRegex(
            ValueError, "controller_step_retroactive_source_forbidden"
        ):
            execution_contracts._prepare_controller_step_source(
                claim=claim,
                source_receipt=receipt,
                store=store,
                config=config,
                runtime=runtime,
            )

        self.assertEqual(self._status(case), "failed")
        self.assertEqual((_calls(case[-2]), _calls(case[-1])), (("dense",), ()))

    def test_provider_started_before_claim_cannot_finish_into_that_step(self):
        case = self._unexecuted_case(dense_delay_seconds=0.5)
        store, config, runtime, bound, execution, decision, dense_log, *_ = case
        obligation = issue_fact_retrieval_obligations(
            bound=bound,
            store=store,
            config=config,
            runtime=runtime,
        )[0]

        with ThreadPoolExecutor(max_workers=1) as pool:
            receipt_future = pool.submit(
                execute_retrieval_lane,
                obligation=obligation,
                lane="dense",
                store=store,
                config=config,
                runtime=runtime,
            )
            deadline = time.monotonic() + 2.0
            while _calls(dense_log) != ("dense",):
                if time.monotonic() >= deadline:
                    self.fail("synthetic provider did not start")
                time.sleep(0.01)
            claim = self._claim(case)
            receipt = receipt_future.result()

        with self.assertRaisesRegex(
            ValueError, "controller_step_retroactive_source_forbidden"
        ):
            execution_contracts._prepare_controller_step_source(
                claim=claim,
                source_receipt=receipt,
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual(self._status(case), "failed")

    def test_dependency_drift_after_child_dispatch_tombstones_claim(self):
        case = self._unexecuted_case()
        claim = self._claim(case)
        store, config, runtime, bound, execution, decision, *_logs = case
        obligation = issue_fact_retrieval_obligations(
            bound=bound,
            store=store,
            config=config,
            runtime=runtime,
        )[0]
        receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        projection = execution_contracts._prepare_controller_step_source(
            claim=claim,
            source_receipt=receipt,
            store=store,
            config=config,
            runtime=runtime,
        )

        with patch.object(
            execution_contracts,
            "validate_controller_decision_receipt",
            lambda **_kwargs: None,
        ):
            with self.assertRaisesRegex(
                ValueError, "harness_runtime_validation_dependency_drift"
            ):
                execution_contracts._source_controller_step(
                    claim=claim,
                    projection=projection,
                    store=store,
                    config=config,
                    runtime=runtime,
                )

        self.assertEqual(self._status(case), "failed")

    def test_dependency_drift_during_prepare_tombstones_claim(self):
        case = self._unexecuted_case()
        claim = self._claim(case)
        store, config, runtime, bound, _execution, _decision, *_logs = case
        obligation = issue_fact_retrieval_obligations(
            bound=bound,
            store=store,
            config=config,
            runtime=runtime,
        )[0]
        receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )

        with patch.object(
            execution_contracts,
            "validate_controller_decision_receipt",
            lambda **_kwargs: None,
        ):
            with self.assertRaisesRegex(
                ValueError, "harness_runtime_validation_dependency_drift"
            ):
                execution_contracts._prepare_controller_step_source(
                    claim=claim,
                    source_receipt=receipt,
                    store=store,
                    config=config,
                    runtime=runtime,
                )

        self.assertEqual(self._status(case), "failed")

    def test_status_replacer_drift_cannot_disable_failure_tombstone(self):
        case = self._unexecuted_case()
        claim = self._claim(case)
        store, config, runtime, bound, *_rest = case
        obligation = issue_fact_retrieval_obligations(
            bound=bound,
            store=store,
            config=config,
            runtime=runtime,
        )[0]
        receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        dependency_closure = dict(
            zip(
                execution_contracts._validate_controller_step_history_dependencies.__code__.co_freevars,
                execution_contracts._validate_controller_step_history_dependencies.__closure__,
            )
        )
        helper_pins = dependency_closure["helper_pins"].cell_contents
        replacer = next(
            row[0]
            for row in helper_pins
            if row[0].__name__ == "replace_status_unlocked"
        )

        def no_op_factory():
            first = second = third = None

            def no_op(*args, **_kwargs):
                _ = (first, second, third)
                return args[1]

            return no_op

        issued_code = replacer.__code__
        try:
            replacer.__code__ = no_op_factory().__code__
            with self.assertRaisesRegex(
                ValueError, "controller_step_history_dependency_drift"
            ):
                execution_contracts._prepare_controller_step_source(
                    claim=claim,
                    source_receipt=receipt,
                    store=store,
                    config=config,
                    runtime=runtime,
                )
        finally:
            replacer.__code__ = issued_code

        self.assertEqual(self._status(case), "failed")
        with self.assertRaisesRegex(ValueError, "controller_step_source_out_of_order"):
            execution_contracts._prepare_controller_step_source(
                claim=claim,
                source_receipt=receipt,
                store=store,
                config=config,
                runtime=runtime,
            )

    def test_decision_drift_after_child_dispatch_tombstones_claim(self):
        case = self._unexecuted_case()
        claim = self._claim(case)
        store, config, runtime, bound, _execution, decision, *_logs = case
        obligation = issue_fact_retrieval_obligations(
            bound=bound,
            store=store,
            config=config,
            runtime=runtime,
        )[0]
        receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        decision_ordinal = decision.decision_ordinal
        object.__setattr__(decision, "decision_ordinal", decision_ordinal + 7)

        with self.assertRaisesRegex(
            ValueError, "controller_step_history_authority_drift"
        ):
            execution_contracts._prepare_controller_step_source(
                claim=claim,
                source_receipt=receipt,
                store=store,
                config=config,
                runtime=runtime,
            )

        object.__setattr__(decision, "decision_ordinal", decision_ordinal)
        self.assertEqual(self._status(case), "failed")

    def test_source_attempt_registry_uses_no_executable_weakref_callbacks(self):
        case = self._unexecuted_case()
        store, config, runtime, bound, *_rest = case
        obligation = issue_fact_retrieval_obligations(
            bound=bound,
            store=store,
            config=config,
            runtime=runtime,
        )[0]
        receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        epoch_closure = dict(
            zip(
                execution_contracts._controller_source_attempt_epoch.__code__.co_freevars,
                execution_contracts._controller_source_attempt_epoch.__closure__,
            )
        )
        receipts = epoch_closure["receipts"].cell_contents
        receipt_ref = receipts[id(receipt)][0]

        self.assertIs(receipt_ref(), receipt)
        self.assertIsNone(receipt_ref.__callback__)

    def test_exact_projection_drift_after_child_call_tombstones_claim(self):
        case = self._unexecuted_case()
        claim = self._claim(case)
        store, config, runtime, bound, execution, decision, *_logs = case
        obligation = issue_fact_retrieval_obligations(
            bound=bound,
            store=store,
            config=config,
            runtime=runtime,
        )[0]
        receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        projection = execution_contracts._prepare_controller_step_source(
            claim=claim,
            source_receipt=receipt,
            store=store,
            config=config,
            runtime=runtime,
        )
        object.__setattr__(projection, "outcome", "provider_error")

        with self.assertRaisesRegex(
            ValueError, "controller_source_outcome_projection_authority_required"
        ):
            execution_contracts._source_controller_step(
                claim=claim,
                projection=projection,
                store=store,
                config=config,
                runtime=runtime,
            )

        self.assertEqual(self._status(case), "failed")

    def test_decision_drift_after_prepare_cannot_be_restored_at_source_binding(self):
        case = self._unexecuted_case()
        claim = self._claim(case)
        store, config, runtime, bound, _execution, decision, *_logs = case
        obligation = issue_fact_retrieval_obligations(
            bound=bound,
            store=store,
            config=config,
            runtime=runtime,
        )[0]
        receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        projection = execution_contracts._prepare_controller_step_source(
            claim=claim,
            source_receipt=receipt,
            store=store,
            config=config,
            runtime=runtime,
        )
        decision_ordinal = decision.decision_ordinal
        object.__setattr__(decision, "decision_ordinal", decision_ordinal + 7)

        with self.assertRaisesRegex(
            ValueError, "controller_step_history_authority_drift"
        ):
            execution_contracts._source_controller_step(
                claim=claim,
                projection=projection,
                store=store,
                config=config,
                runtime=runtime,
            )

        object.__setattr__(decision, "decision_ordinal", decision_ordinal)
        self.assertEqual(self._status(case), "failed")

    def test_source_attempt_registry_drift_at_binding_tombstones_claim(self):
        case = self._unexecuted_case()
        claim = self._claim(case)
        store, config, runtime, bound, *_rest = case
        obligation = issue_fact_retrieval_obligations(
            bound=bound,
            store=store,
            config=config,
            runtime=runtime,
        )[0]
        receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        projection = execution_contracts._prepare_controller_step_source(
            claim=claim,
            source_receipt=receipt,
            store=store,
            config=config,
            runtime=runtime,
        )
        epoch_closure = dict(
            zip(
                execution_contracts._controller_source_attempt_epoch.__code__.co_freevars,
                execution_contracts._controller_source_attempt_epoch.__closure__,
            )
        )
        receipts_shadow = epoch_closure["receipts_shadow"].cell_contents
        issued_entry = receipts_shadow[id(receipt)]
        receipts_shadow[id(receipt)] = tuple([*issued_entry])
        try:
            with self.assertRaisesRegex(
                ValueError, "controller_source_attempt_registry_drift"
            ):
                execution_contracts._source_controller_step(
                    claim=claim,
                    projection=projection,
                    store=store,
                    config=config,
                    runtime=runtime,
                )
        finally:
            receipts_shadow[id(receipt)] = issued_entry

        self.assertEqual(self._status(case), "failed")
        with self.assertRaisesRegex(ValueError, "controller_step_source_out_of_order"):
            execution_contracts._source_controller_step(
                claim=claim,
                projection=projection,
                store=store,
                config=config,
                runtime=runtime,
            )

    def test_sourced_projection_drift_tombstones_failed_on_next_read(self):
        case = self._unexecuted_case()
        claim = self._claim(case)
        projection, _receipt, _dense_log, _lexical_log = self._source(case, claim)
        object.__setattr__(projection, "outcome", "provider_error")

        self.assertEqual(self._status(case), "failed")
        with self.assertRaisesRegex(ValueError, "controller_step_terminal"):
            execution_contracts._fail_controller_step(claim=claim)

    def test_claim_gc_leaves_failed_tombstone_until_execution_gc(self):
        case = self._unexecuted_case()
        claim = self._claim(case)
        claim_weak = ref(claim)

        del claim
        gc.collect()

        self.assertIsNone(claim_weak())
        self.assertEqual(self._status(case), "failed")
        with self.assertRaisesRegex(ValueError, "controller_step_already_consumed"):
            self._claim(case)

    def test_claim_gc_during_root_drift_still_leaves_failed_tombstone(self):
        case = self._unexecuted_case()
        claim = self._claim(case)
        decision = case[5]
        decision_ordinal = decision.decision_ordinal
        claim_weak = ref(claim)
        object.__setattr__(decision, "decision_ordinal", decision_ordinal + 7)

        del claim
        gc.collect()

        object.__setattr__(decision, "decision_ordinal", decision_ordinal)
        self.assertIsNone(claim_weak())
        self.assertEqual(self._status(case), "failed")
        with self.assertRaisesRegex(ValueError, "controller_step_already_consumed"):
            self._claim(case)

    def test_sourced_projection_gc_fails_closed(self):
        case = self._unexecuted_case()
        claim = self._claim(case)
        projection, _receipt, _dense_log, _lexical_log = self._source(case, claim)
        projection_weak = ref(projection)

        del projection
        gc.collect()

        self.assertIsNone(projection_weak())
        self.assertEqual(self._status(case), "failed")
        with self.assertRaisesRegex(ValueError, "controller_step_terminal"):
            execution_contracts._fail_controller_step(claim=claim)

    def test_prepared_projection_gc_fails_closed_before_source_binding(self):
        case = self._unexecuted_case()
        claim = self._claim(case)
        store, config, runtime, bound, *_rest = case
        obligation = issue_fact_retrieval_obligations(
            bound=bound,
            store=store,
            config=config,
            runtime=runtime,
        )[0]
        receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        projection = execution_contracts._prepare_controller_step_source(
            claim=claim,
            source_receipt=receipt,
            store=store,
            config=config,
            runtime=runtime,
        )
        projection_weak = ref(projection)

        del projection
        gc.collect()

        self.assertIsNone(projection_weak())
        self.assertEqual(self._status(case), "failed")

    def test_prepared_projection_gc_during_root_drift_fails_closed(self):
        case = self._unexecuted_case()
        claim = self._claim(case)
        store, config, runtime, bound, _execution, decision, *_logs = case
        obligation = issue_fact_retrieval_obligations(
            bound=bound,
            store=store,
            config=config,
            runtime=runtime,
        )[0]
        receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        projection = execution_contracts._prepare_controller_step_source(
            claim=claim,
            source_receipt=receipt,
            store=store,
            config=config,
            runtime=runtime,
        )
        projection_weak = ref(projection)
        decision_ordinal = decision.decision_ordinal
        object.__setattr__(decision, "decision_ordinal", decision_ordinal + 7)

        del projection
        gc.collect()

        object.__setattr__(decision, "decision_ordinal", decision_ordinal)
        self.assertIsNone(projection_weak())
        self.assertEqual(self._status(case), "failed")

    def test_failed_dispatch_releases_source_attempt_permit(self):
        case = self._unexecuted_case(dense_delay_seconds=0.3)
        store, config, runtime, bound, *_middle, dense_log, _lexical_log = case
        obligation = issue_fact_retrieval_obligations(
            bound=bound,
            store=store,
            config=config,
            runtime=runtime,
        )[0]
        begin_closure = dict(
            zip(
                execution_contracts._begin_controller_source_attempt.__code__.co_freevars,
                execution_contracts._begin_controller_source_attempt.__closure__,
            )
        )
        attempts = begin_closure["attempts"].cell_contents
        attempts_shadow = begin_closure["attempts_shadow"].cell_contents
        self.assertEqual((len(attempts), len(attempts_shadow)), (0, 0))

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                execute_retrieval_lane,
                obligation=obligation,
                lane="dense",
                store=store,
                config=config,
                runtime=runtime,
            )
            deadline = time.monotonic() + 2.0
            while _calls(dense_log) != ("dense",):
                if time.monotonic() >= deadline:
                    self.fail("synthetic provider did not start")
                time.sleep(0.01)
            pending_ref = next(iter(attempts.values()))[0]
            self.assertIsNotNone(pending_ref())
            self.assertIsNone(pending_ref.__callback__)
            with patch.object(
                execution_contracts,
                "validate_controller_decision_receipt",
                lambda **_kwargs: None,
            ):
                with self.assertRaisesRegex(
                    ValueError, "harness_runtime_validation_dependency_drift"
                ):
                    future.result()

        gc.collect()
        self.assertEqual((len(attempts), len(attempts_shadow)), (0, 0))

    def test_history_releases_exact_root_after_execution_graph_gc(self):
        case = self._unexecuted_case()
        claim = self._claim(case)
        execution_weak = ref(case[4])
        decision_weak = ref(case[5])
        action_weak = ref(case[5].selected_action)
        claim_weak = ref(claim)

        del claim
        del case
        gc.collect()

        self.assertIsNone(claim_weak())
        self.assertIsNone(decision_weak())
        self.assertIsNone(action_weak())
        self.assertIsNone(execution_weak())

    def test_concurrent_source_and_failure_end_in_failed_terminal_state(self):
        case = self._unexecuted_case()
        claim = self._claim(case)
        store, config, runtime, bound, execution, decision, *_logs = case
        obligation = issue_fact_retrieval_obligations(
            bound=bound,
            store=store,
            config=config,
            runtime=runtime,
        )[0]
        receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        projection = execution_contracts._prepare_controller_step_source(
            claim=claim,
            source_receipt=receipt,
            store=store,
            config=config,
            runtime=runtime,
        )

        def source():
            try:
                execution_contracts._source_controller_step(
                    claim=claim,
                    projection=projection,
                    store=store,
                    config=config,
                    runtime=runtime,
                )
            except ValueError:
                pass

        def fail():
            execution_contracts._fail_controller_step(claim=claim)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = (pool.submit(source), pool.submit(fail))
            for future in futures:
                future.result()

        self.assertEqual(self._status(case), "failed")

    def test_effect_and_transition_edges_stay_dormant_without_exact_authority(self):
        case = self._unexecuted_case()
        claim = self._claim(case)
        projection, _receipt, _dense_log, _lexical_log = self._source(case, claim)

        with self.assertRaisesRegex(
            ValueError, "controller_step_effect_authority_not_ready"
        ):
            execution_contracts._bind_controller_step_effect(
                claim=claim,
                effect=object(),
                store=case[0],
                config=case[1],
                runtime=case[2],
            )
        with self.assertRaisesRegex(
            ValueError, "controller_step_transition_out_of_order"
        ):
            execution_contracts._complete_controller_step(
                claim=claim,
                transition=object(),
                store=case[0],
                config=case[1],
                runtime=case[2],
            )
        self.assertIsNotNone(projection)
        self.assertEqual(self._status(case), "sourced")


if __name__ == "__main__":
    unittest.main()
