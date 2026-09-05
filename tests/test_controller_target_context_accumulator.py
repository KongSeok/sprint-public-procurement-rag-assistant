"""EH2.6.c4.0.d target-context accumulator contract tests."""

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
    create_harness_execution_config,
    execute_retrieval_fusion,
    execute_retrieval_lane,
    issue_bridge_context_receipts,
    issue_fact_retrieval_obligations,
    issue_fact_semantic_verification_obligation,
    issue_parent_context_receipts,
)
from midprojectrag.orchestration.action_effects import (
    validate_action_effect_receipt,
)
from midprojectrag.retrieval.fusion import HybridChildRetriever

from tests.test_action_effect_receipts import (
    _NeverReranker,
    _NeverVerifier,
    _context_store,
    _never_clock,
)
from tests.test_retrieval_obligations import (
    _SyntheticLane,
    _calls,
    _fact_bound,
)


class ControllerTargetContextAccumulatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.tempdir = Path(self._temporary.name)
        _NeverVerifier.calls = 0
        _NeverReranker.calls = 0
        self._root_graphs = {}

    def _case(
        self,
        *,
        name: str,
        context_limit: int = 8,
        preissue_context: bool = True,
    ):
        store = _context_store()
        seeds = tuple(item for item in store.evidence if item.kind == "text")
        specs = tuple(
            (item.evidence_id, item.doc_id) for item in reversed(seeds)
        )
        dense_log = self.tempdir / f"{name}-dense.log"
        lexical_log = self.tempdir / f"{name}-lexical.log"
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
            verifier=_NeverVerifier(),
            reranker=_NeverReranker(),
            clock=_never_clock,
        )
        config = create_harness_execution_config(
            mode="e1_bounded",
            max_context_targets_per_obligation=context_limit,
        )
        bound = _fact_bound(store)
        retrieval = issue_fact_retrieval_obligations(
            bound=bound,
            store=store,
            config=config,
            runtime=runtime,
        )[0]
        dense = execute_retrieval_lane(
            obligation=retrieval,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        lexical = execute_retrieval_lane(
            obligation=retrieval,
            lane="lexical",
            store=store,
            config=config,
            runtime=runtime,
        )
        fusion = execute_retrieval_fusion(
            obligation=retrieval,
            dense_receipt=dense,
            lexical_receipt=lexical,
            store=store,
            config=config,
            runtime=runtime,
        )
        semantic = issue_fact_semantic_verification_obligation(
            obligation=retrieval,
            fusion_receipt=fusion,
            store=store,
            config=config,
            runtime=runtime,
        )
        parents = (
            issue_parent_context_receipts(
                obligation=semantic,
                store=store,
                config=config,
                runtime=runtime,
            )
            if preissue_context
            else None
        )
        bridges = (
            issue_bridge_context_receipts(
                obligation=semantic,
                store=store,
                config=config,
                runtime=runtime,
            )
            if preissue_context
            else None
        )
        self._root_graphs[name] = (
            bound,
            retrieval,
            dense,
            lexical,
            fusion,
            semantic,
            parents,
            bridges,
        )
        return {
            "store": store,
            "config": config,
            "runtime": runtime,
            "semantic": semantic,
            "seeds": seeds,
            "parents": parents,
            "bridges": bridges,
            "dense_log": dense_log,
            "lexical_log": lexical_log,
        }

    @staticmethod
    def _accumulate(case, action_kind, target_evidence_id):
        return execution_contracts._accumulate_controller_target_context(
            obligation=case["semantic"],
            action_kind=action_kind,
            target_evidence_id=target_evidence_id,
            store=case["store"],
            config=case["config"],
            runtime=case["runtime"],
        )

    @staticmethod
    def _require(case, context):
        return execution_contracts._require_controller_target_context(
            context=context,
            store=case["store"],
            config=case["config"],
            runtime=case["runtime"],
        )

    def test_private_accumulator_boundary_and_signature_exist(self):
        accumulator = execution_contracts._accumulate_controller_target_context

        self.assertTrue(callable(accumulator))
        self.assertEqual(
            tuple(inspect.signature(accumulator).parameters),
            (
                "obligation",
                "action_kind",
                "target_evidence_id",
                "store",
                "config",
                "runtime",
            ),
        )
        self.assertNotIn("ControllerTargetContext", orchestration.__all__)
        self.assertFalse(
            hasattr(orchestration, "accumulate_controller_target_context")
        )

    def test_exact_one_selection_preserves_complete_rerank_batch_identity(self):
        case = self._case(name="exact-one")
        target = case["seeds"][1].evidence_id
        calls_before = (
            _calls(case["dense_log"]),
            _calls(case["lexical_log"]),
            _NeverVerifier.calls,
            _NeverReranker.calls,
        )

        expected = {
            "expand_parent": tuple(
                item
                for item in case["parents"]
                if item.seed_evidence_id == target
            ),
            "bridge_table": tuple(
                item
                for item in case["bridges"]
                if item.seed_evidence_id == target
                and item.bridge_kind == "table"
            ),
            "bridge_figure": tuple(
                item
                for item in case["bridges"]
                if item.seed_evidence_id == target
                and item.bridge_kind == "figure"
            ),
        }
        results = {}
        for action_kind, matches in expected.items():
            self.assertEqual(len(matches), 1)
            context = self._accumulate(case, action_kind, target)
            results[action_kind] = context
            self.assertIs(context.obligation, case["semantic"])
            self.assertEqual(context.action_kind, action_kind)
            self.assertEqual(context.target_evidence_id, target)
            self.assertIs(context.selected_receipt, matches[0])
            self.assertIs(context.parent_receipts, case["parents"])
            self.assertIs(context.bridge_receipts, case["bridges"])
            self.assertIs(self._require(case, context), context)

        self.assertEqual(
            (
                _calls(case["dense_log"]),
                _calls(case["lexical_log"]),
                _NeverVerifier.calls,
                _NeverReranker.calls,
            ),
            calls_before,
        )
        self.assertIsNot(
            results["bridge_table"].selected_receipt,
            results["bridge_figure"].selected_receipt,
        )

    def test_accumulator_issues_both_complete_batches_when_absent(self):
        case = self._case(name="issue-batches", preissue_context=False)
        target = case["seeds"][0].evidence_id

        context = self._accumulate(case, "expand_parent", target)
        parents = issue_parent_context_receipts(
            obligation=case["semantic"],
            store=case["store"],
            config=case["config"],
            runtime=case["runtime"],
        )
        bridges = issue_bridge_context_receipts(
            obligation=case["semantic"],
            store=case["store"],
            config=case["config"],
            runtime=case["runtime"],
        )

        self.assertIs(context.parent_receipts, parents)
        self.assertIs(context.bridge_receipts, bridges)
        self.assertEqual(len(parents), len(case["seeds"]))
        self.assertEqual(len(bridges), len(case["seeds"]) * 2)

    def test_value_is_private_immutable_nonserializable_and_non_authorizing(self):
        case = self._case(name="closed-value")
        target = case["seeds"][0].evidence_id
        context = self._accumulate(case, "expand_parent", target)

        with self.assertRaisesRegex(
            AttributeError, "controller_target_context_immutable"
        ):
            context.action_kind = "bridge_table"
        with self.assertRaisesRegex(
            TypeError, "controller_target_context_copy_forbidden"
        ):
            copy.copy(context)
        with self.assertRaisesRegex(
            TypeError, "controller_target_context_copy_forbidden"
        ):
            copy.deepcopy(context)
        with self.assertRaisesRegex(
            TypeError, "controller_target_context_pickle_forbidden"
        ):
            pickle.dumps(context)
        with self.assertRaisesRegex(TypeError, "invalid_action_effect_receipt"):
            validate_action_effect_receipt(receipt=context)
        self.assertIsNot(type(context), execution_contracts._ControllerStepClaim)
        self.assertFalse(hasattr(context, "decision"))
        self.assertFalse(hasattr(context, "effect"))
        self.assertFalse(hasattr(context, "transition"))
        self.assertNotIn("ControllerTargetContext", orchestration.__all__)
        self.assertFalse(hasattr(orchestration, "require_controller_target_context"))

    def test_caller_cannot_inject_receipts_batches_hashes_or_outcomes(self):
        case = self._case(name="injection")
        target = case["seeds"][0].evidence_id
        for field, value in (
            ("selected_receipt", case["parents"][0]),
            ("parent_receipts", case["parents"]),
            ("bridge_receipts", case["bridges"]),
            ("context_sha256", "0" * 64),
            ("outcome", "applied"),
        ):
            with self.subTest(field=field):
                kwargs = {
                    "obligation": case["semantic"],
                    "action_kind": "expand_parent",
                    "target_evidence_id": target,
                    "store": case["store"],
                    "config": case["config"],
                    "runtime": case["runtime"],
                    field: value,
                }
                with self.assertRaisesRegex(
                    TypeError, "unexpected keyword argument"
                ):
                    execution_contracts._accumulate_controller_target_context(
                        **kwargs
                    )

    def test_wrong_action_or_non_bounded_candidate_fails_before_new_calls(self):
        case = self._case(name="wrong-target", context_limit=1)
        included_target = sorted(case["semantic"].candidate_evidence_ids)[0]
        excluded_target = next(
            evidence_id
            for evidence_id in case["semantic"].candidate_evidence_ids
            if evidence_id != included_target
        )
        calls_before = (
            _calls(case["dense_log"]),
            _calls(case["lexical_log"]),
            _NeverVerifier.calls,
            _NeverReranker.calls,
        )
        with self.assertRaisesRegex(
            ValueError, "invalid_controller_target_context_action_kind"
        ):
            self._accumulate(case, "verify_slot", included_target)
        with self.assertRaisesRegex(
            ValueError, "controller_target_context_target_not_candidate"
        ):
            self._accumulate(case, "bridge_table", excluded_target)
        self.assertEqual(
            (
                _calls(case["dense_log"]),
                _calls(case["lexical_log"]),
                _NeverVerifier.calls,
                _NeverReranker.calls,
            ),
            calls_before,
        )

    def test_repeat_and_concurrent_accumulation_return_same_live_value(self):
        case = self._case(name="concurrent")
        target = case["seeds"][0].evidence_id

        def run(_index):
            return self._accumulate(case, "bridge_table", target)

        with ThreadPoolExecutor(max_workers=12) as pool:
            results = tuple(pool.map(run, range(24)))

        self.assertTrue(all(item is results[0] for item in results))
        self.assertIs(
            self._accumulate(case, "bridge_table", target), results[0]
        )

    def test_clone_mutation_reorder_and_cross_root_have_no_authority(self):
        case = self._case(name="authority")
        foreign = self._case(name="foreign")
        target = case["seeds"][0].evidence_id
        context = self._accumulate(case, "bridge_figure", target)
        clone = object.__new__(type(context))
        for name in type(context).__slots__:
            if name != "__weakref__":
                object.__setattr__(clone, name, getattr(context, name))
        with self.assertRaisesRegex(
            ValueError, "controller_target_context_authority_required"
        ):
            self._require(case, clone)

        original_batches = context.bridge_receipts
        object.__setattr__(
            context, "bridge_receipts", tuple(reversed(original_batches))
        )
        with self.assertRaisesRegex(
            ValueError, "controller_target_context_authority_required"
        ):
            self._require(case, context)
        object.__setattr__(context, "bridge_receipts", original_batches)
        self.assertIs(self._require(case, context), context)

        with self.assertRaisesRegex(
            ValueError, "controller_target_context_authority_required"
        ):
            self._require(foreign, context)

    def test_missing_duplicate_or_wrong_role_context_mutation_fails_closed(self):
        case = self._case(name="batch-integrity")
        target = case["seeds"][0].evidence_id
        context = self._accumulate(case, "bridge_table", target)
        original_parents = context.parent_receipts
        original_selected = context.selected_receipt
        wrong_role = next(
            receipt
            for receipt in context.bridge_receipts
            if receipt.seed_evidence_id == target
            and receipt.bridge_kind == "figure"
        )

        for mutated_parents in (
            original_parents[:-1],
            original_parents + (original_parents[0],),
        ):
            object.__setattr__(
                context, "parent_receipts", mutated_parents
            )
            with self.assertRaisesRegex(
                ValueError, "controller_target_context_authority_required"
            ):
                self._require(case, context)
            object.__setattr__(
                context, "parent_receipts", original_parents
            )

        object.__setattr__(context, "selected_receipt", wrong_role)
        with self.assertRaisesRegex(
            ValueError, "controller_target_context_authority_required"
        ):
            self._require(case, context)
        object.__setattr__(context, "selected_receipt", original_selected)

        self.assertIs(self._require(case, context), context)

    def test_live_root_gc_does_not_allow_equal_target_remint(self):
        case = self._case(name="gc")
        target = case["seeds"][0].evidence_id
        context = self._accumulate(case, "expand_parent", target)
        accumulator = execution_contracts._accumulate_controller_target_context
        closure = dict(
            zip(accumulator.__code__.co_freevars, accumulator.__closure__)
        )
        cache = closure["cache"].cell_contents
        context_weak = next(
            item for item in cache.values() if item() is context
        )
        self.assertIsNone(context_weak.__callback__)
        context_ref = ref(context)
        del context
        gc.collect()
        self.assertIsNone(context_ref())

        with self.assertRaisesRegex(
            ValueError, "controller_target_context_remint_forbidden"
        ):
            self._accumulate(case, "expand_parent", target)

    def test_dead_root_passively_retires_cache_and_tombstone_rows(self):
        case = self._case(name="dead-root")
        target = case["seeds"][0].evidence_id
        context = self._accumulate(case, "bridge_figure", target)
        semantic_ref = ref(case["semantic"])
        accumulator = execution_contracts._accumulate_controller_target_context
        closure = dict(
            zip(accumulator.__code__.co_freevars, accumulator.__closure__)
        )
        cache = closure["cache"].cell_contents
        old_key = next(key for key, item in cache.items() if item() is context)

        self._root_graphs.pop("dead-root")
        del context
        del case
        gc.collect()

        replacement = self._case(name="dead-root-replacement")
        replacement_target = replacement["seeds"][0].evidence_id
        replacement_context = self._accumulate(
            replacement, "bridge_figure", replacement_target
        )
        gc.collect()

        self.assertIsNone(semantic_ref())
        for name in (
            "cache",
            "cache_shadow",
            "known_keys",
            "known_keys_shadow",
            "root_by_key",
            "root_by_key_shadow",
        ):
            self.assertNotIn(old_key, closure[name].cell_contents)
        self.assertIs(
            self._require(replacement, replacement_context),
            replacement_context,
        )

    def test_runtime_dependency_drift_fails_before_accumulation(self):
        case = self._case(name="dependency-drift")
        target = case["seeds"][0].evidence_id
        calls_before = (
            _calls(case["dense_log"]),
            _calls(case["lexical_log"]),
        )
        with patch.object(
            execution_contracts,
            "issue_parent_context_receipts",
            lambda **_kwargs: (),
        ):
            with self.assertRaisesRegex(
                ValueError, "harness_runtime_validation_dependency_drift"
            ):
                self._accumulate(case, "expand_parent", target)
        self.assertEqual(
            (_calls(case["dense_log"]), _calls(case["lexical_log"])),
            calls_before,
        )

    def test_captured_selection_helper_code_drift_fails_before_selection(self):
        case = self._case(name="helper-code-drift")
        target = case["seeds"][0].evidence_id
        accumulator = execution_contracts._accumulate_controller_target_context
        closure = dict(
            zip(accumulator.__code__.co_freevars, accumulator.__closure__)
        )
        matching_receipts = closure["matching_receipts"].cell_contents
        issued_code = matching_receipts.__code__

        def wrong_selection(
            *,
            action_kind,
            target_evidence_id,
            parent_receipts,
            bridge_receipts,
            parent_authorities,
            bridge_authorities,
        ):
            return (bridge_receipts[-1],)

        try:
            matching_receipts.__code__ = wrong_selection.__code__
            with self.assertRaisesRegex(
                ValueError, "controller_target_context_dependency_drift"
            ):
                self._accumulate(case, "bridge_table", target)
        finally:
            matching_receipts.__code__ = issued_code

        context = self._accumulate(case, "bridge_table", target)
        self.assertEqual(context.selected_receipt.bridge_kind, "table")
        self.assertEqual(context.selected_receipt.seed_evidence_id, target)


if __name__ == "__main__":
    unittest.main()
