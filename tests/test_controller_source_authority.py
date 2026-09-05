"""EH2.6.c4.0.a source-owner authority contract tests.

The first RED names only the private execution-owned reader.  It must recover
the exact source graph captured when the state was created without changing
the public execution payload or issuing effects/transitions.
"""

from __future__ import annotations

import gc
import inspect
import unittest
from unittest.mock import patch
from weakref import ref

import midprojectrag.orchestration as orchestration
import midprojectrag.orchestration.execution_contracts as execution_contracts
import midprojectrag.orchestration.harness_state as harness_state_module
from midprojectrag.orchestration import (
    build_compare_coverage,
    build_compare_harness_state,
    build_e1_followup_harness_state,
    build_fact_harness_state,
    build_followup_harness_state,
    create_harness_execution_config,
    issue_harness_execution,
)

import tests.test_execution_aggregate as execution_fixtures
import tests.test_e1_followup_projection as followup_fixtures
import tests.test_harness_state as state_fixtures
from tests.test_retrieval_obligations import _fact_bound, _store


class ControllerSourceAuthorityContractTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture = execution_fixtures.ExecutionAggregateContractTests(
            methodName="runTest"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self._fixture = fixture

    def tearDown(self) -> None:
        self.assertEqual(execution_fixtures._CLOCK_CALLS, 0)

    def test_c40_execution_recovers_exact_fact_source_without_public_surface(self):
        store = _store(doc_ids=("doc-a",))
        bound = _fact_bound(store)
        state = build_fact_harness_state(bound=bound, store=store)
        runtime, dense_log, lexical_log = self._fixture._runtime_for_store(
            store, "c40-fact-source"
        )
        config = create_harness_execution_config(mode="e1_bounded")
        execution = issue_harness_execution(
            state=state,
            store=store,
            config=config,
            runtime=runtime,
        )

        authority = execution_contracts._require_controller_source_owner(
            execution=execution,
            store=store,
            config=config,
            runtime=runtime,
        )

        self.assertEqual(authority.source_kind, "fact")
        self.assertIs(authority.source, bound)
        self.assertIs(authority.source_receipt, bound.trace)
        self.assertEqual(authority.projection_kind, "fact_initial")
        self.assertNotIn("ControllerSourceOwnerAuthority", orchestration.__all__)
        self.assertFalse(hasattr(orchestration, "require_controller_source_owner"))
        self.assertEqual(
            tuple(inspect.signature(issue_harness_execution).parameters),
            ("state", "store", "config", "runtime"),
        )
        self.assertFalse(dense_log.exists())
        self.assertFalse(lexical_log.exists())

    def test_c40_compare_and_e1_followup_recover_exact_source_graph(self):
        compare_store, _evidence, compare_bound = state_fixtures._compare_fixture()
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
        compare_runtime, dense_log, lexical_log = self._fixture._runtime_for_store(
            compare_store, "c40-compare-source"
        )
        config = create_harness_execution_config(mode="e1_bounded")
        compare_execution = issue_harness_execution(
            state=compare_state,
            store=compare_store,
            config=config,
            runtime=compare_runtime,
        )
        compare_owner = execution_contracts._require_controller_source_owner(
            execution=compare_execution,
            store=compare_store,
            config=config,
            runtime=compare_runtime,
        )
        self.assertEqual(compare_owner.source_kind, "compare")
        self.assertIs(compare_owner.source, compare_bound)
        self.assertIs(compare_owner.source_receipt, coverage)
        self.assertEqual(compare_owner.projection_kind, "compare_coverage")
        self.assertIsNone(compare_owner.source_progress)
        with patch.object(type(coverage), "_validate", lambda *_args: None):
            with self.assertRaisesRegex(
                ValueError, "controller_source_owner_dependency_drift"
            ):
                execution_contracts._require_controller_source_owner(
                    execution=compare_execution,
                    store=compare_store,
                    config=config,
                    runtime=compare_runtime,
                )

        followup = followup_fixtures._fixture(slots=())
        (
            followup_store,
            _evidence,
            registry,
            policy,
            followup_bound,
            outcome,
            _retriever,
        ) = followup
        followup_state = build_e1_followup_harness_state(
            bound=followup_bound,
            outcome=outcome,
            store=followup_store,
            registry=registry,
            policy=policy,
        )
        followup_runtime, fdense_log, flexical_log = (
            self._fixture._runtime_for_store(
                followup_store, "c40-followup-source"
            )
        )
        followup_execution = issue_harness_execution(
            state=followup_state,
            store=followup_store,
            config=config,
            runtime=followup_runtime,
        )
        followup_owner = execution_contracts._require_controller_source_owner(
            execution=followup_execution,
            store=followup_store,
            config=config,
            runtime=followup_runtime,
        )
        self.assertEqual(followup_owner.source_kind, "follow_up")
        self.assertIs(followup_owner.source, followup_bound)
        self.assertIs(followup_owner.source_receipt, outcome)
        self.assertIs(followup_owner.source_progress, outcome.progress)
        self.assertIs(followup_owner.registry, registry)
        self.assertIs(followup_owner.policy, policy)
        self.assertEqual(followup_owner.projection_kind, "followup_e1")
        for path in (dense_log, lexical_log, fdense_log, flexical_log):
            self.assertFalse(path.exists())

    def test_c40_legacy_followup_state_cannot_promote_to_controller_source(self):
        (
            store,
            _evidence,
            registry,
            policy,
            bound,
            progress,
            outcome,
            _retriever,
        ) = state_fixtures._followup_fixture(sufficient=False)
        state = build_followup_harness_state(
            bound=bound,
            progress=progress,
            outcome=outcome,
            store=store,
            registry=registry,
            policy=policy,
        )
        runtime, dense_log, lexical_log = self._fixture._runtime_for_store(
            store, "c40-legacy-followup"
        )
        config = create_harness_execution_config(mode="e1_bounded")
        execution = issue_harness_execution(
            state=state,
            store=store,
            config=config,
            runtime=runtime,
        )

        with self.assertRaisesRegex(
            ValueError, "controller_followup_source_not_e1_safe"
        ):
            execution_contracts._require_controller_source_owner(
                execution=execution,
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertFalse(dense_log.exists())
        self.assertFalse(lexical_log.exists())

    def test_c40_owner_lifetime_and_exact_store_identity_are_preserved(self):
        store = _store(doc_ids=("doc-a",))
        bound = _fact_bound(store)
        bound_weak = ref(bound)
        state = build_fact_harness_state(bound=bound, store=store)
        del bound
        gc.collect()
        self.assertIsNotNone(bound_weak())

        runtime, dense_log, lexical_log = self._fixture._runtime_for_store(
            store, "c40-owner-lifetime"
        )
        config = create_harness_execution_config(mode="e1_bounded")
        execution = issue_harness_execution(
            state=state,
            store=store,
            config=config,
            runtime=runtime,
        )
        owner = execution_contracts._require_controller_source_owner(
            execution=execution,
            store=store,
            config=config,
            runtime=runtime,
        )
        self.assertIs(owner.source, bound_weak())

        equal_store = _store(doc_ids=("doc-a",))
        self.assertEqual(equal_store.bundle_sha256, store.bundle_sha256)
        with self.assertRaisesRegex(
            ValueError, "harness_state_store_identity_mismatch"
        ):
            harness_state_module._require_harness_state_source_owner(
                state=state,
                store=equal_store,
            )
        self.assertFalse(dense_log.exists())
        self.assertFalse(lexical_log.exists())

    def test_c40_source_authority_dies_with_state_root(self):
        store = _store(doc_ids=("doc-a",))
        state = build_fact_harness_state(bound=_fact_bound(store), store=store)
        owner = harness_state_module._require_harness_state_source_owner(
            state=state,
            store=store,
        )
        state_weak = ref(state)
        owner_weak = ref(owner)
        del state
        del owner
        gc.collect()
        self.assertIsNone(state_weak())
        self.assertIsNone(owner_weak())

    def test_c40_equal_hash_payload_clone_cannot_inherit_source_owner(self):
        store = _store(doc_ids=("doc-a",))
        state = build_fact_harness_state(bound=_fact_bound(store), store=store)
        owner = harness_state_module._require_harness_state_source_owner(
            state=state,
            store=store,
        )
        with self.assertRaisesRegex(TypeError, "_source_owner"):
            harness_state_module.HarnessState._create(
                belief=state.belief,
                progress=state.progress,
                store=store,
                _token=harness_state_module._STATE_TOKEN,
                _source_owner=owner,
            )
        clone = harness_state_module.HarnessState._create(
            belief=state.belief,
            progress=state.progress,
            store=store,
            _token=harness_state_module._STATE_TOKEN,
        )

        self.assertIsNot(clone, state)
        self.assertEqual(clone.state_sha256, state.state_sha256)
        self.assertNotIn(
            "_source_owner",
            inspect.signature(harness_state_module.HarnessState._create).parameters,
        )
        with self.assertRaisesRegex(
            ValueError, "controller_source_owner_runtime_authority_required"
        ):
            harness_state_module._require_harness_state_source_owner(
                state=clone,
                store=store,
            )

        runtime, dense_log, lexical_log = self._fixture._runtime_for_store(
            store, "c40-equal-hash-clone"
        )
        config = create_harness_execution_config(mode="e1_bounded")
        with self.assertRaisesRegex(
            ValueError, "controller_source_owner_runtime_authority_required"
        ):
            issue_harness_execution(
                state=clone,
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertFalse(dense_log.exists())
        self.assertFalse(lexical_log.exists())

    def test_c40_state_source_reader_dependencies_are_closed(self):
        store = _store(doc_ids=("doc-a",))
        state = build_fact_harness_state(bound=_fact_bound(store), store=store)
        issued_reader = harness_state_module._require_harness_state_source_owner

        with patch.object(
            harness_state_module,
            "_read_controller_source_owner_authority",
            lambda **_kwargs: object(),
            create=True,
        ):
            with self.assertRaisesRegex(
                ValueError, "controller_source_owner_dependency_drift"
            ):
                issued_reader(state=state, store=store)

        with patch.object(
            harness_state_module,
            "_authority_record",
            lambda *_args, **_kwargs: (),
        ):
            with self.assertRaisesRegex(
                ValueError, "controller_source_owner_dependency_drift"
            ):
                issued_reader(state=state, store=store)

        with patch.object(
            harness_state_module.HarnessState,
            "_validate",
            lambda *_args, **_kwargs: None,
        ):
            with self.assertRaisesRegex(
                ValueError, "controller_source_owner_dependency_drift"
            ):
                issued_reader(state=state, store=store)

    def test_c40_source_validation_alias_drift_precedes_source_dereference(self):
        store = _store(doc_ids=("doc-a",))
        bound = _fact_bound(store)
        state = build_fact_harness_state(bound=bound, store=store)
        runtime, dense_log, lexical_log = self._fixture._runtime_for_store(
            store, "c40-validator-drift"
        )
        config = create_harness_execution_config(mode="e1_bounded")
        execution = issue_harness_execution(
            state=state,
            store=store,
            config=config,
            runtime=runtime,
        )
        issued_reader = execution_contracts._require_controller_source_owner

        with patch.object(
            harness_state_module,
            "_validate_controller_source_owner",
            lambda *_args, **_kwargs: None,
        ):
            object.__setattr__(bound.plan, "normalized_query", "mutated")
            with self.assertRaisesRegex(
                ValueError, "controller_source_owner_dependency_drift"
            ):
                issued_reader(
                    execution=execution,
                    store=store,
                    config=config,
                    runtime=runtime,
                )
        self.assertFalse(dense_log.exists())
        self.assertFalse(lexical_log.exists())

    def test_c40_clone_slot_mutation_and_reader_drift_fail_closed(self):
        store = _store(doc_ids=("doc-a",))
        state = build_fact_harness_state(bound=_fact_bound(store), store=store)
        runtime, dense_log, lexical_log = self._fixture._runtime_for_store(
            store, "c40-adversarial"
        )
        config = create_harness_execution_config(mode="e1_bounded")
        execution = issue_harness_execution(
            state=state,
            store=store,
            config=config,
            runtime=runtime,
        )
        execution_clone = self._fixture._clone_slots(execution)
        with self.assertRaisesRegex(
            ValueError, "harness_execution_runtime_authority_required"
        ):
            execution_contracts._require_controller_source_owner(
                execution=execution_clone,
                store=store,
                config=config,
                runtime=runtime,
            )

        issued_reader = execution_contracts._require_controller_source_owner
        with patch.object(
            execution_contracts,
            "_require_harness_state_source_owner",
            lambda **_kwargs: object(),
        ):
            with self.assertRaisesRegex(
                ValueError, "controller_source_owner_dependency_drift"
            ):
                issued_reader(
                    execution=execution,
                    store=store,
                    config=config,
                    runtime=runtime,
                )

        owner = issued_reader(
            execution=execution,
            store=store,
            config=config,
            runtime=runtime,
        )
        object.__setattr__(owner, "source_progress", object())
        with self.assertRaisesRegex(
            ValueError, "controller_source_owner_nested_identity_drift"
        ):
            issued_reader(
                execution=execution,
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertFalse(dense_log.exists())
        self.assertFalse(lexical_log.exists())


if __name__ == "__main__":
    unittest.main()
