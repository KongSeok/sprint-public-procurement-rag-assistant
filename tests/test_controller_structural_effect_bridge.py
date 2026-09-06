"""EH2.6.c4.0.e structural-effect bridge contract tests."""

from __future__ import annotations

import copy
import gc
import inspect
import pickle
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
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
from tests.test_retrieval_obligations import _SyntheticLane, _calls, _fact_bound, _store


class ControllerStructuralEffectBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.tempdir = Path(self._temporary.name)

    def _case(self, *, doc_ids=("doc-a",)):
        store = _store(doc_ids=doc_ids)
        dense_log = self.tempdir / "dense.log"
        lexical_log = self.tempdir / "lexical.log"
        retriever = HybridChildRetriever(
            store,
            _SyntheticLane(
                lane="dense",
                bundle_sha256=store.bundle_sha256,
                candidate_specs=(),
                call_log_path=str(dense_log),
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
            state=state, store=store, config=config, runtime=runtime
        )
        decision = decide_controller_action(
            execution=execution, store=store, config=config, runtime=runtime
        )
        case = (store, config, runtime, bound, execution, decision, dense_log, lexical_log)
        claim = execution_contracts._claim_controller_step(
            execution=execution, decision=decision, store=store, config=config, runtime=runtime
        )
        obligation = issue_fact_retrieval_obligations(
            bound=bound, store=store, config=config, runtime=runtime
        )[0]
        receipt = execute_retrieval_lane(
            obligation=obligation, lane="dense", store=store, config=config, runtime=runtime
        )
        projection = execution_contracts._prepare_controller_step_source(
            claim=claim, source_receipt=receipt, store=store, config=config, runtime=runtime
        )
        execution_contracts._source_controller_step(
            claim=claim, projection=projection, store=store, config=config, runtime=runtime
        )
        return case, claim, projection, receipt, dense_log, lexical_log

    @staticmethod
    def _bridge(case, claim, projection, target_context=None):
        store, config, runtime = case[0], case[1], case[2]
        return execution_contracts._prepare_controller_structural_effect_bridge(
            claim=claim,
            projection=projection,
            target_context=target_context,
            store=store,
            config=config,
            runtime=runtime,
        )

    def test_private_boundary_and_signature_are_not_public(self):
        prepare = execution_contracts._prepare_controller_structural_effect_bridge
        require = execution_contracts._require_controller_structural_effect_bridge
        self.assertTrue(callable(prepare))
        self.assertTrue(callable(require))
        self.assertEqual(
            tuple(inspect.signature(prepare).parameters),
            ("claim", "projection", "target_context", "store", "config", "runtime"),
        )
        self.assertEqual(
            tuple(inspect.signature(require).parameters),
            ("bridge", "store", "config", "runtime"),
        )
        self.assertNotIn("ControllerStructuralEffectBridge", orchestration.__all__)
        self.assertFalse(hasattr(orchestration, "prepare_controller_structural_effect_bridge"))

    def test_sourced_lane_produces_immutable_non_authorizing_bridge(self):
        case, claim, projection, receipt, dense_log, lexical_log = self._case()
        bridge = self._bridge(case, claim, projection)

        self.assertIs(bridge.claim, claim)
        self.assertIs(bridge.projection, projection)
        self.assertIsNone(bridge.target_context)
        self.assertEqual(bridge.source_receipt_sha256, receipt.receipt_sha256)
        self.assertEqual(bridge.source_receipt_kind, "lane_search")
        self.assertEqual(bridge.outcome, projection.outcome)
        self.assertEqual(len(bridge.structural_effect_sha256), 64)
        self.assertEqual(
            execution_contracts._controller_step_status(
                execution=case[4],
                decision=case[5],
                store=case[0],
                config=case[1],
                runtime=case[2],
            ),
            "sourced",
        )
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), (("dense",), ()))

        with self.assertRaisesRegex(AttributeError, "structural_effect_bridge_immutable"):
            bridge.outcome = "provider_error"
        self.assertEqual(repr(bridge), "_ControllerStructuralEffectBridge(<redacted>)")
        for operation in (copy.copy, copy.deepcopy, pickle.dumps):
            with self.assertRaisesRegex(TypeError, "structural_effect_bridge_not_serializable"):
                operation(bridge)

        self.assertIs(
            execution_contracts._require_controller_structural_effect_bridge(
                bridge=bridge,
                store=case[0],
                config=case[1],
                runtime=case[2],
            ),
            bridge,
        )

    def test_same_live_inputs_are_idempotent_and_no_provider_is_called(self):
        case, claim, projection, _receipt, dense_log, lexical_log = self._case()
        first = self._bridge(case, claim, projection)
        second = self._bridge(case, claim, projection)
        self.assertIs(first, second)
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), (("dense",), ()))

    def test_out_of_order_and_context_shape_fail_before_any_effect_transition(self):
        store = _store(doc_ids=("doc-a",))
        dense_log = self.tempdir / "out-of-order-dense.log"
        lexical_log = self.tempdir / "out-of-order-lexical.log"
        retriever = HybridChildRetriever(
            store,
            _SyntheticLane(lane="dense", bundle_sha256=store.bundle_sha256, candidate_specs=(), call_log_path=str(dense_log)),
            _SyntheticLane(lane="lexical", bundle_sha256=store.bundle_sha256, candidate_specs=(), call_log_path=str(lexical_log)),
        )
        runtime = HarnessRuntimeBinding.for_test(store=store, retriever=retriever, verifier=_NeverVerifier(), reranker=_NeverReranker(), clock=_never_clock)
        config = create_harness_execution_config(mode="e1_bounded")
        bound = _fact_bound(store)
        state = build_fact_harness_state(bound=bound, store=store)
        execution = issue_harness_execution(state=state, store=store, config=config, runtime=runtime)
        decision = decide_controller_action(execution=execution, store=store, config=config, runtime=runtime)
        case = (store, config, runtime, bound, execution, decision, dense_log, lexical_log)
        claim = execution_contracts._claim_controller_step(execution=execution, decision=decision, store=store, config=config, runtime=runtime)
        store, config, runtime, bound, execution, decision, dense_log, lexical_log = case
        obligation = execution_contracts.issue_fact_retrieval_obligations(
            bound=bound, store=store, config=config, runtime=runtime
        )[0]
        receipt = execution_contracts.execute_retrieval_lane(
            obligation=obligation, lane="dense", store=store, config=config, runtime=runtime
        )
        projection = execution_contracts._resolve_controller_source_outcome(
            execution=execution,
            decision=decision,
            source_receipt=receipt,
            store=store,
            config=config,
            runtime=runtime,
        )
        with self.assertRaisesRegex(ValueError, "controller_structural_effect_bridge_source_out_of_order"):
            self._bridge(case, claim, projection)
        prepared = execution_contracts._prepare_controller_step_source(
            claim=claim,
            source_receipt=receipt,
            store=store,
            config=config,
            runtime=runtime,
        )
        execution_contracts._source_controller_step(
            claim=claim,
            projection=prepared,
            store=store,
            config=config,
            runtime=runtime,
        )
        with self.assertRaisesRegex(TypeError, "controller_target_context_required"):
            self._bridge(case, claim, projection, target_context=object())
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), (("dense",), ()))

    def test_projection_clone_and_mixed_dependency_have_no_bridge_authority(self):
        case, claim, projection, _receipt, dense_log, lexical_log = self._case()
        forged = object.__new__(type(projection))
        for name in type(projection).__slots__:
            if name != "__weakref__":
                object.__setattr__(forged, name, getattr(projection, name))
        with self.assertRaisesRegex(ValueError, "controller_source_outcome_projection_authority_required"):
            self._bridge(case, claim, forged)

        other_config = create_harness_execution_config(
            mode="e1_bounded", max_context_targets_per_obligation=7
        )
        with self.assertRaisesRegex(ValueError, "controller_step_dependency_identity_mismatch"):
            execution_contracts._prepare_controller_structural_effect_bridge(
                claim=claim,
                projection=projection,
                target_context=None,
                store=case[0],
                config=other_config,
                runtime=case[2],
            )
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), (("dense",), ()))

    def test_projection_mutation_tombstones_sourced_step(self):
        case, claim, projection, _receipt, _dense_log, _lexical_log = self._case()
        object.__setattr__(projection, "outcome", "provider_error")
        with self.assertRaisesRegex(ValueError, "controller_source_outcome_projection_authority_required"):
            self._bridge(case, claim, projection)
        self.assertEqual(
            execution_contracts._controller_step_status(
                execution=case[4], decision=case[5], store=case[0], config=case[1], runtime=case[2]
            ),
            "failed",
        )

    def test_bridge_gc_keeps_live_root_tombstone_and_dead_root_cleanup_is_passive(self):
        case, claim, projection, _receipt, _dense_log, _lexical_log = self._case()
        bridge = self._bridge(case, claim, projection)
        bridge_weak = ref(bridge)
        del bridge
        gc.collect()
        self.assertIsNone(bridge_weak())
        with self.assertRaisesRegex(ValueError, "controller_structural_effect_bridge_remint_forbidden"):
            self._bridge(case, claim, projection)
