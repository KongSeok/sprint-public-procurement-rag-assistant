"""EH2.6.c4.0.b typed controller source/outcome resolver tests."""

from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
import gc
import inspect
from pathlib import Path
import pickle
from tempfile import TemporaryDirectory
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


class ControllerSourceOutcomeResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.tempdir = Path(self._temporary.name)

    def _lane_case(self):
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
        return (
            store,
            config,
            runtime,
            execution,
            decision,
            receipt,
            dense_log,
            lexical_log,
        )

    def test_lane_receipt_resolves_without_an_additional_provider_call(self):
        (
            store,
            config,
            runtime,
            execution,
            decision,
            receipt,
            dense_log,
            lexical_log,
        ) = self._lane_case()
        calls_before = (_calls(dense_log), _calls(lexical_log))

        projection = execution_contracts._resolve_controller_source_outcome(
            execution=execution,
            decision=decision,
            source_receipt=receipt,
            store=store,
            config=config,
            runtime=runtime,
        )

        self.assertIs(projection.execution, execution)
        self.assertIs(projection.decision, decision)
        self.assertIs(projection.selected_action, decision.selected_action)
        self.assertIs(projection.source_receipt, receipt)
        self.assertEqual(projection.source_receipt_kind, "lane_search")
        self.assertEqual(projection.source_receipt_sha256, receipt.receipt_sha256)
        self.assertEqual(projection.native_outcome, receipt.outcome)
        self.assertEqual(projection.outcome, receipt.outcome)
        self.assertEqual(projection.ordered_evidence_ids, receipt.ordered_evidence_ids)
        self.assertEqual(projection.parent_context_receipt_sha256s, ())
        self.assertEqual(projection.bridge_context_receipt_sha256s, ())
        self.assertIsNone(projection.absence_confirmation_sha256)
        self.assertEqual(projection.call_performed, receipt.call_performed)
        self.assertEqual(
            (_calls(dense_log), _calls(lexical_log)),
            calls_before,
        )

    def test_projection_is_private_immutable_and_non_authorizing(self):
        (
            store,
            config,
            runtime,
            execution,
            decision,
            receipt,
            dense_log,
            lexical_log,
        ) = self._lane_case()
        projection = execution_contracts._resolve_controller_source_outcome(
            execution=execution,
            decision=decision,
            source_receipt=receipt,
            store=store,
            config=config,
            runtime=runtime,
        )

        with self.assertRaisesRegex(
            AttributeError, "controller_source_outcome_immutable"
        ):
            projection.outcome = "applied"
        with self.assertRaisesRegex(
            TypeError, "controller_source_outcome_copy_forbidden"
        ):
            copy.copy(projection)
        with self.assertRaisesRegex(
            TypeError, "controller_source_outcome_copy_forbidden"
        ):
            copy.deepcopy(projection)
        with self.assertRaisesRegex(
            TypeError, "controller_source_outcome_pickle_forbidden"
        ):
            pickle.dumps(projection)
        self.assertNotIn("ControllerSourceOutcomeProjection", orchestration.__all__)
        self.assertFalse(
            hasattr(orchestration, "resolve_controller_source_outcome")
        )
        self.assertEqual(
            tuple(
                inspect.signature(
                    execution_contracts._resolve_controller_source_outcome
                ).parameters
            ),
            (
                "execution",
                "decision",
                "source_receipt",
                "store",
                "config",
                "runtime",
            ),
        )
        self.assertEqual(
            (_calls(dense_log), _calls(lexical_log)), (("dense",), ())
        )

    def test_equal_payload_receipt_clone_is_not_live_authority(self):
        (
            store,
            config,
            runtime,
            execution,
            decision,
            receipt,
            dense_log,
            lexical_log,
        ) = self._lane_case()
        clone = object.__new__(type(receipt))
        for name in type(receipt).__slots__:
            if name != "__weakref__":
                object.__setattr__(clone, name, getattr(receipt, name))
        calls_before = (_calls(dense_log), _calls(lexical_log))

        with self.assertRaisesRegex(
            ValueError, "lane_search_receipt_runtime_authority_required"
        ):
            execution_contracts._resolve_controller_source_outcome(
                execution=execution,
                decision=decision,
                source_receipt=clone,
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual(
            (_calls(dense_log), _calls(lexical_log)), calls_before
        )

    def test_equal_payload_foreign_owner_is_rejected_after_exact_validation(self):
        (
            store,
            config,
            runtime,
            execution,
            decision,
            _receipt,
            dense_log,
            lexical_log,
        ) = self._lane_case()
        foreign_bound = _fact_bound(store)
        foreign_obligation = issue_fact_retrieval_obligations(
            bound=foreign_bound,
            store=store,
            config=config,
            runtime=runtime,
        )[0]
        foreign_receipt = execute_retrieval_lane(
            obligation=foreign_obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        calls_before = (_calls(dense_log), _calls(lexical_log))

        with self.assertRaisesRegex(
            ValueError, "controller_source_outcome_owner_identity_mismatch"
        ):
            execution_contracts._resolve_controller_source_outcome(
                execution=execution,
                decision=decision,
                source_receipt=foreign_receipt,
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual(
            (_calls(dense_log), _calls(lexical_log)), calls_before
        )

    def test_nonterminal_decision_cannot_be_used_as_terminal_source(self):
        (
            store,
            config,
            runtime,
            execution,
            decision,
            _receipt,
            dense_log,
            lexical_log,
        ) = self._lane_case()
        calls_before = (_calls(dense_log), _calls(lexical_log))

        with self.assertRaisesRegex(
            ValueError, "controller_source_outcome_action_mismatch"
        ):
            execution_contracts._resolve_controller_source_outcome(
                execution=execution,
                decision=decision,
                source_receipt=decision,
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual(
            (_calls(dense_log), _calls(lexical_log)), calls_before
        )

    def test_caller_cannot_supply_derived_outcome_or_hash_fields(self):
        (
            store,
            config,
            runtime,
            execution,
            decision,
            receipt,
            dense_log,
            lexical_log,
        ) = self._lane_case()
        calls_before = (_calls(dense_log), _calls(lexical_log))

        with self.assertRaisesRegex(TypeError, "unexpected keyword argument"):
            execution_contracts._resolve_controller_source_outcome(
                execution=execution,
                decision=decision,
                source_receipt=receipt,
                store=store,
                config=config,
                runtime=runtime,
                outcome="applied",
            )
        self.assertEqual(
            (_calls(dense_log), _calls(lexical_log)), calls_before
        )

    def test_decision_validator_drift_fails_before_source_resolution(self):
        (
            store,
            config,
            runtime,
            execution,
            decision,
            receipt,
            dense_log,
            lexical_log,
        ) = self._lane_case()
        calls_before = (_calls(dense_log), _calls(lexical_log))

        with patch.object(
            execution_contracts,
            "validate_controller_decision_receipt",
            lambda **_kwargs: None,
        ):
            with self.assertRaisesRegex(
                ValueError,
                "(controller_source_outcome|harness_runtime_validation)_dependency_drift",
            ):
                execution_contracts._resolve_controller_source_outcome(
                    execution=execution,
                    decision=decision,
                    source_receipt=receipt,
                    store=store,
                    config=config,
                    runtime=runtime,
                )
        self.assertEqual(
            (_calls(dense_log), _calls(lexical_log)), calls_before
        )

    def test_projection_mutation_and_structural_forgery_never_gain_authority(self):
        (
            store,
            config,
            runtime,
            execution,
            decision,
            receipt,
            dense_log,
            lexical_log,
        ) = self._lane_case()
        projection = execution_contracts._resolve_controller_source_outcome(
            execution=execution,
            decision=decision,
            source_receipt=receipt,
            store=store,
            config=config,
            runtime=runtime,
        )
        calls_before = (_calls(dense_log), _calls(lexical_log))
        forged = object.__new__(type(projection))
        for name in type(projection).__slots__:
            if name != "__weakref__":
                object.__setattr__(forged, name, getattr(projection, name))
        object.__setattr__(projection, "outcome", "provider_error")

        for candidate in (projection, forged):
            with self.assertRaisesRegex(
                ValueError,
                "controller_source_outcome_projection_authority_required",
            ):
                execution_contracts._require_controller_source_outcome_projection(
                    projection=candidate,
                    store=store,
                    config=config,
                    runtime=runtime,
                )
        self.assertFalse(
            hasattr(
                execution_contracts._ControllerSourceOutcomeProjection,
                "_create",
            )
        )
        self.assertFalse(
            hasattr(execution_contracts, "_CONTROLLER_SOURCE_OUTCOME_TOKEN")
        )
        self.assertEqual(
            (_calls(dense_log), _calls(lexical_log)), calls_before
        )

    def test_repeated_resolution_is_same_object_and_revalidated(self):
        (
            store,
            config,
            runtime,
            execution,
            decision,
            receipt,
            dense_log,
            lexical_log,
        ) = self._lane_case()
        first = execution_contracts._resolve_controller_source_outcome(
            execution=execution,
            decision=decision,
            source_receipt=receipt,
            store=store,
            config=config,
            runtime=runtime,
        )
        calls_before = (_calls(dense_log), _calls(lexical_log))
        second = execution_contracts._resolve_controller_source_outcome(
            execution=execution,
            decision=decision,
            source_receipt=receipt,
            store=store,
            config=config,
            runtime=runtime,
        )
        required = execution_contracts._require_controller_source_outcome_projection(
            projection=first,
            store=store,
            config=config,
            runtime=runtime,
        )

        self.assertIs(second, first)
        self.assertIs(required, first)
        self.assertEqual(
            (_calls(dense_log), _calls(lexical_log)), calls_before
        )

    def test_concurrent_resolution_has_one_identity(self):
        (
            store,
            config,
            runtime,
            execution,
            decision,
            receipt,
            dense_log,
            lexical_log,
        ) = self._lane_case()
        calls_before = (_calls(dense_log), _calls(lexical_log))

        def resolve(_index):
            return execution_contracts._resolve_controller_source_outcome(
                execution=execution,
                decision=decision,
                source_receipt=receipt,
                store=store,
                config=config,
                runtime=runtime,
            )

        with ThreadPoolExecutor(max_workers=16) as pool:
            projections = tuple(pool.map(resolve, range(32)))

        self.assertEqual(len({id(item) for item in projections}), 1)
        self.assertEqual(
            (_calls(dense_log), _calls(lexical_log)), calls_before
        )

    def test_projection_gc_tombstone_forbids_remint(self):
        (
            store,
            config,
            runtime,
            execution,
            decision,
            receipt,
            dense_log,
            lexical_log,
        ) = self._lane_case()
        projection = execution_contracts._resolve_controller_source_outcome(
            execution=execution,
            decision=decision,
            source_receipt=receipt,
            store=store,
            config=config,
            runtime=runtime,
        )
        projection_weak = ref(projection)
        del projection
        gc.collect()
        self.assertIsNone(projection_weak())
        calls_before = (_calls(dense_log), _calls(lexical_log))

        with self.assertRaisesRegex(
            ValueError,
            "controller_source_outcome_projection_remint_forbidden",
        ):
            execution_contracts._resolve_controller_source_outcome(
                execution=execution,
                decision=decision,
                source_receipt=receipt,
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual(
            (_calls(dense_log), _calls(lexical_log)), calls_before
        )

    def test_private_issuer_rejects_every_non_resolver_caller(self):
        (
            store,
            config,
            runtime,
            execution,
            decision,
            receipt,
            dense_log,
            lexical_log,
        ) = self._lane_case()
        projection = execution_contracts._resolve_controller_source_outcome(
            execution=execution,
            decision=decision,
            source_receipt=receipt,
            store=store,
            config=config,
            runtime=runtime,
        )
        values = tuple(
            (name, object.__getattribute__(projection, name))
            for name in type(projection).__slots__
            if name != "__weakref__"
        )

        with self.assertRaisesRegex(
            ValueError,
            "controller_source_outcome_resolver_authority_required",
        ):
            execution_contracts._issue_controller_source_outcome_projection(
                values=values
            )
        self.assertFalse(
            hasattr(
                execution_contracts,
                "_read_controller_source_outcome_projection_authority",
            )
        )
        self.assertEqual(
            (_calls(dense_log), _calls(lexical_log)), (("dense",), ())
        )

    def test_projection_reader_uses_sealed_dependencies(self):
        (
            store,
            config,
            runtime,
            execution,
            decision,
            receipt,
            dense_log,
            lexical_log,
        ) = self._lane_case()
        projection = execution_contracts._resolve_controller_source_outcome(
            execution=execution,
            decision=decision,
            source_receipt=receipt,
            store=store,
            config=config,
            runtime=runtime,
        )
        calls_before = (_calls(dense_log), _calls(lexical_log))

        with (
            patch.object(
                execution_contracts,
                "_resolve_controller_source_outcome",
                lambda **_kwargs: projection,
            ),
            patch.object(
                execution_contracts,
                "_ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER",
                lambda: None,
            ),
        ):
            with self.assertRaisesRegex(
                ValueError,
                "(controller_source_outcome|harness_runtime_validation)_dependency_drift",
            ):
                execution_contracts._require_controller_source_outcome_projection(
                    projection=projection,
                    store=store,
                    config=config,
                    runtime=runtime,
                )
        self.assertEqual(
            (_calls(dense_log), _calls(lexical_log)), calls_before
        )

    def test_global_validator_replacement_cannot_bypass_resolution_gate(self):
        (
            store,
            config,
            runtime,
            execution,
            decision,
            receipt,
            dense_log,
            lexical_log,
        ) = self._lane_case()
        calls_before = (_calls(dense_log), _calls(lexical_log))
        object.__setattr__(receipt, "outcome", "provider_error")

        with (
            patch.object(
                execution_contracts,
                "_ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER",
                lambda: None,
            ),
            patch.object(
                execution_contracts,
                "validate_controller_decision_receipt",
                lambda **_kwargs: None,
            ),
            patch.object(
                execution_contracts,
                "_require_controller_source_owner",
                lambda **_kwargs: object(),
            ),
            patch.object(
                execution_contracts,
                "validate_lane_search_receipt",
                lambda **_kwargs: None,
            ),
        ):
            with self.assertRaisesRegex(
                ValueError, "controller_source_outcome_dependency_drift"
            ):
                execution_contracts._resolve_controller_source_outcome(
                    execution=execution,
                    decision=decision,
                    source_receipt=receipt,
                    store=store,
                    config=config,
                    runtime=runtime,
                )
        self.assertEqual(
            (_calls(dense_log), _calls(lexical_log)), calls_before
        )


if __name__ == "__main__":
    unittest.main()
