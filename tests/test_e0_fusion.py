"""EH2.6.b4 fusion and state-free E0 control contract tests.

The fixtures are deliberately synthetic and offline.  Raw queries and poisoned
provider traces must remain behind the execution-contract authority boundary.
"""

from concurrent.futures import ThreadPoolExecutor
import gc
from inspect import signature
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Barrier
from types import FunctionType, ModuleType
import unittest
import weakref

import midprojectrag.orchestration.execution_contracts as execution_contracts
from midprojectrag.orchestration import (
    E0ControlReceipt,
    E0ObligationResult,
    FusionReceipt,
    create_harness_execution_config,
    execute_e0_control,
    execute_retrieval_fusion,
    execute_retrieval_lane,
    issue_compare_retrieval_obligations,
    issue_fact_retrieval_obligations,
    validate_e0_control_receipt,
    validate_fusion_receipt,
)

from tests.test_retrieval_obligations import (
    _calls,
    _compare_bound,
    _fact_bound,
    _runtime,
    _store,
)


_FORBIDDEN_RUNTIME_WORDS = (
    "qrels",
    "gold",
    "expected_answer",
    "reference_answer",
    "사업 예산은 얼마인가?",
    "gold-must-not-leak",
)


class E0FusionTests(unittest.TestCase):
    def setUp(self):
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.tempdir = Path(self._temporary.name)

    def _fact_case(
        self,
        *,
        name,
        mode="e0_once",
        dense_mode="valid",
        lexical_mode="valid",
        dense_delay=0.0,
        dense_reentry_module="",
    ):
        store = _store(doc_ids=("doc-a",))
        dense_log = self.tempdir / f"{name}-dense.log"
        lexical_log = self.tempdir / f"{name}-lexical.log"
        runtime = _runtime(
            store=store,
            dense_log=dense_log,
            lexical_log=lexical_log,
            dense_mode=dense_mode,
            lexical_mode=lexical_mode,
            dense_delay=dense_delay,
            dense_reentry_module=dense_reentry_module,
        )
        config = create_harness_execution_config(mode=mode)
        obligations = issue_fact_retrieval_obligations(
            bound=_fact_bound(store),
            store=store,
            config=config,
            runtime=runtime,
        )
        return store, config, runtime, obligations, dense_log, lexical_log

    def _compare_case(self, *, name, mode="e0_once"):
        store = _store()
        dense_log = self.tempdir / f"{name}-dense.log"
        lexical_log = self.tempdir / f"{name}-lexical.log"
        runtime = _runtime(
            store=store,
            dense_log=dense_log,
            lexical_log=lexical_log,
        )
        config = create_harness_execution_config(mode=mode)
        bound, _registry = _compare_bound(store)
        obligations = issue_compare_retrieval_obligations(
            bound=bound,
            store=store,
            config=config,
            runtime=runtime,
        )
        return store, config, runtime, obligations, dense_log, lexical_log

    def _lane_pair(self, *, obligation, store, config, runtime):
        dense = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        lexical = execute_retrieval_lane(
            obligation=obligation,
            lane="lexical",
            store=store,
            config=config,
            runtime=runtime,
        )
        return dense, lexical

    def _fuse(self, *, obligation, dense, lexical, store, config, runtime):
        return execute_retrieval_fusion(
            obligation=obligation,
            dense_receipt=dense,
            lexical_receipt=lexical,
            store=store,
            config=config,
            runtime=runtime,
        )

    def _copied_globals_clone(self, function):
        copied = dict(function.__globals__)

        def forged_checker(
            _module_globals=None,
            _function_pins=None,
            _object_pins=None,
            _module_attribute_pins=None,
            _class_pins=None,
            _authority_fields=None,
        ):
            return None

        forged_checker.__defaults__ = (copied, (), (), (), (), ())
        copied["_ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER"] = forged_checker
        copied["_PINNED_RUNTIME_GATE_DEPENDENCY_CHECKER_CODE"] = (
            forged_checker.__code__
        )
        copied["_ISSUED_RUNTIME_GATE_DEPENDENCY_DEFAULTS"] = (
            forged_checker.__defaults__
        )
        clone = FunctionType(
            function.__code__,
            copied,
            name=function.__name__,
            argdefs=function.__defaults__,
            closure=function.__closure__,
        )
        clone.__kwdefaults__ = {
            "_dependency_checker": forged_checker,
            "_dependency_checker_code": forged_checker.__code__,
        }
        return clone

    def test_b4_r1_normal_pair_mints_safe_stage_four_fusion_receipt(self):
        store, config, runtime, obligations, dense_log, lexical_log = self._fact_case(
            name="r1", mode="e1_bounded"
        )
        obligation = obligations[0]
        dense, lexical = self._lane_pair(
            obligation=obligation,
            store=store,
            config=config,
            runtime=runtime,
        )

        receipt = self._fuse(
            obligation=obligation,
            dense=dense,
            lexical=lexical,
            store=store,
            config=config,
            runtime=runtime,
        )

        self.assertIs(type(receipt), FusionReceipt)
        self.assertEqual((receipt.stage, receipt.stage_ordinal), ("fusion", 4))
        self.assertEqual((receipt.outcome, receipt.call_performed), ("applied", True))
        self.assertEqual(receipt.obligation_sha256, obligation.obligation_sha256)
        self.assertEqual(receipt.dense_receipt_sha256, dense.receipt_sha256)
        self.assertEqual(receipt.lexical_receipt_sha256, lexical.receipt_sha256)
        self.assertEqual(receipt.candidate_count, len(receipt.ordered_evidence_ids))
        self.assertEqual(
            len(receipt.ordered_evidence_ids),
            len(receipt.ordered_stable_anchors),
        )
        self.assertGreater(receipt.candidate_count, 0)
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), (("dense",), ("lexical",)))
        validate_fusion_receipt(
            receipt=receipt,
            obligation=obligation,
            dense_receipt=dense,
            lexical_receipt=lexical,
            store=store,
            config=config,
            runtime=runtime,
        )

        serialized = json.dumps(receipt.to_dict(), ensure_ascii=False)
        for forbidden in _FORBIDDEN_RUNTIME_WORDS:
            self.assertNotIn(forbidden, serialized)
            self.assertNotIn(forbidden, repr(receipt))

    def test_b4_r2_two_empty_lanes_still_execute_one_empty_fusion(self):
        store, config, runtime, obligations, _dense_log, _lexical_log = self._fact_case(
            name="r2",
            mode="e1_bounded",
            dense_mode="empty",
            lexical_mode="empty",
        )
        obligation = obligations[0]
        dense, lexical = self._lane_pair(
            obligation=obligation,
            store=store,
            config=config,
            runtime=runtime,
        )

        receipt = self._fuse(
            obligation=obligation,
            dense=dense,
            lexical=lexical,
            store=store,
            config=config,
            runtime=runtime,
        )

        self.assertEqual((receipt.outcome, receipt.call_performed), ("empty", True))
        self.assertEqual(receipt.ordered_evidence_ids, ())
        self.assertEqual(receipt.ordered_stable_anchors, ())
        self.assertEqual(receipt.candidate_count, 0)

    def test_b4_r3_swapped_lane_roles_are_rejected_before_fusion(self):
        store, config, runtime, obligations, _dense_log, _lexical_log = self._fact_case(
            name="r3", mode="e1_bounded"
        )
        obligation = obligations[0]
        dense, lexical = self._lane_pair(
            obligation=obligation,
            store=store,
            config=config,
            runtime=runtime,
        )

        with self.assertRaisesRegex(ValueError, "fusion.*lane|lane.*fusion"):
            self._fuse(
                obligation=obligation,
                dense=lexical,
                lexical=dense,
                store=store,
                config=config,
                runtime=runtime,
            )

        receipt = self._fuse(
            obligation=obligation,
            dense=dense,
            lexical=lexical,
            store=store,
            config=config,
            runtime=runtime,
        )
        self.assertEqual(receipt.outcome, "applied")

    def test_b4_r4_cross_obligation_receipts_cannot_be_mixed(self):
        store, config, runtime, obligations, _dense_log, _lexical_log = self._compare_case(
            name="r4", mode="e1_bounded"
        )
        first_dense, first_lexical = self._lane_pair(
            obligation=obligations[0],
            store=store,
            config=config,
            runtime=runtime,
        )

        with self.assertRaisesRegex(ValueError, "fusion.*identity|dependency.*identity"):
            self._fuse(
                obligation=obligations[1],
                dense=first_dense,
                lexical=first_lexical,
                store=store,
                config=config,
                runtime=runtime,
            )

        first = self._fuse(
            obligation=obligations[0],
            dense=first_dense,
            lexical=first_lexical,
            store=store,
            config=config,
            runtime=runtime,
        )
        second_dense, second_lexical = self._lane_pair(
            obligation=obligations[1],
            store=store,
            config=config,
            runtime=runtime,
        )
        second = self._fuse(
            obligation=obligations[1],
            dense=second_dense,
            lexical=second_lexical,
            store=store,
            config=config,
            runtime=runtime,
        )
        self.assertEqual((first.outcome, second.outcome), ("applied", "applied"))

    def test_b4_r5_error_lane_cannot_authorize_fusion(self):
        store, config, runtime, obligations, dense_log, lexical_log = self._fact_case(
            name="r5", mode="e1_bounded", dense_mode="provider_error"
        )
        obligation = obligations[0]
        dense, lexical = self._lane_pair(
            obligation=obligation,
            store=store,
            config=config,
            runtime=runtime,
        )
        self.assertEqual((dense.outcome, lexical.outcome), ("provider_error", "applied"))

        with self.assertRaisesRegex(ValueError, "fusion.*outcome|lane.*outcome"):
            self._fuse(
                obligation=obligation,
                dense=dense,
                lexical=lexical,
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), (("dense",), ("lexical",)))

    def test_b4_r6_fusion_pair_is_consumed_exactly_once(self):
        store, config, runtime, obligations, dense_log, lexical_log = self._fact_case(
            name="r6", mode="e1_bounded"
        )
        obligation = obligations[0]
        dense, lexical = self._lane_pair(
            obligation=obligation,
            store=store,
            config=config,
            runtime=runtime,
        )
        receipt = self._fuse(
            obligation=obligation,
            dense=dense,
            lexical=lexical,
            store=store,
            config=config,
            runtime=runtime,
        )

        with self.assertRaisesRegex(ValueError, "fusion.*already.*consumed"):
            self._fuse(
                obligation=obligation,
                dense=dense,
                lexical=lexical,
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual(receipt.outcome, "applied")
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), (("dense",), ("lexical",)))

    def test_b4_r7_concurrent_fusion_pair_has_one_winner(self):
        store, config, runtime, obligations, _dense_log, _lexical_log = self._fact_case(
            name="r7", mode="e1_bounded"
        )
        obligation = obligations[0]
        dense, lexical = self._lane_pair(
            obligation=obligation,
            store=store,
            config=config,
            runtime=runtime,
        )
        barrier = Barrier(3)

        def invoke():
            barrier.wait()
            try:
                return (
                    "receipt",
                    self._fuse(
                        obligation=obligation,
                        dense=dense,
                        lexical=lexical,
                        store=store,
                        config=config,
                        runtime=runtime,
                    ),
                )
            except Exception as exc:
                return "error", exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = (pool.submit(invoke), pool.submit(invoke))
            barrier.wait()
            outcomes = tuple(future.result(timeout=2) for future in futures)

        self.assertEqual(tuple(kind for kind, _ in outcomes).count("receipt"), 1)
        self.assertEqual(tuple(kind for kind, _ in outcomes).count("error"), 1)
        error = next(value for kind, value in outcomes if kind == "error")
        self.assertIs(type(error), ValueError)
        self.assertRegex(str(error), "fusion.*already.*consumed")

    def test_b4_r8_fusion_payload_or_authority_tamper_fails_validation(self):
        store, config, runtime, obligations, _dense_log, _lexical_log = self._fact_case(
            name="r8", mode="e1_bounded"
        )
        obligation = obligations[0]
        dense, lexical = self._lane_pair(
            obligation=obligation,
            store=store,
            config=config,
            runtime=runtime,
        )
        receipt = self._fuse(
            obligation=obligation,
            dense=dense,
            lexical=lexical,
            store=store,
            config=config,
            runtime=runtime,
        )
        object.__setattr__(receipt, "candidate_count", receipt.candidate_count + 1)

        with self.assertRaises(ValueError):
            validate_fusion_receipt(
                receipt=receipt,
                obligation=obligation,
                dense_receipt=dense,
                lexical_receipt=lexical,
                store=store,
                config=config,
                runtime=runtime,
            )

    def test_b4_r9_e0_fact_executes_dense_lexical_fusion_once(self):
        store, config, runtime, obligations, dense_log, lexical_log = self._fact_case(
            name="r9"
        )

        receipt = execute_e0_control(
            obligations=obligations,
            store=store,
            config=config,
            runtime=runtime,
        )

        self.assertIs(type(receipt), E0ControlReceipt)
        self.assertEqual((receipt.outcome, receipt.execution_complete), ("retrieved", True))
        self.assertEqual(receipt.nonempty_obligation_keys, ("$answer_support",))
        self.assertEqual(receipt.empty_obligation_keys, ())
        self.assertEqual(receipt.unavailable_obligation_keys, ())
        self.assertEqual(receipt.error_obligation_keys, ())
        self.assertEqual(len(receipt.ordered_results), 1)
        result = receipt.ordered_results[0]
        self.assertIs(type(result), E0ObligationResult)
        self.assertEqual((result.obligation_key, result.status), ("$answer_support", "retrieved"))
        self.assertTrue(result.attempted)
        self.assertIsInstance(result.dense_receipt_sha256, str)
        self.assertIsInstance(result.lexical_receipt_sha256, str)
        self.assertIsInstance(result.fusion_receipt_sha256, str)
        self.assertGreater(result.candidate_count, 0)
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), (("dense",), ("lexical",)))
        validate_e0_control_receipt(
            receipt=receipt,
            obligations=obligations,
            store=store,
            config=config,
            runtime=runtime,
        )

        serialized = json.dumps(receipt.to_dict(), ensure_ascii=False)
        for forbidden in _FORBIDDEN_RUNTIME_WORDS:
            self.assertNotIn(forbidden, serialized)
            self.assertNotIn(forbidden, repr(receipt))

    def test_b4_r10_e0_all_empty_is_complete_not_error(self):
        store, config, runtime, obligations, dense_log, lexical_log = self._fact_case(
            name="r10", dense_mode="empty", lexical_mode="empty"
        )

        receipt = execute_e0_control(
            obligations=obligations,
            store=store,
            config=config,
            runtime=runtime,
        )

        self.assertEqual((receipt.outcome, receipt.execution_complete), ("empty", True))
        self.assertEqual(receipt.nonempty_obligation_keys, ())
        self.assertEqual(receipt.empty_obligation_keys, ("$answer_support",))
        self.assertEqual(receipt.error_obligation_keys, ())
        result = receipt.ordered_results[0]
        self.assertEqual((result.status, result.candidate_count), ("empty", 0))
        self.assertTrue(result.attempted)
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), (("dense",), ("lexical",)))

    def test_b4_r11_e0_compare_preserves_canonical_obligation_order(self):
        store, config, runtime, obligations, dense_log, lexical_log = self._compare_case(
            name="r11"
        )

        receipt = execute_e0_control(
            obligations=obligations,
            store=store,
            config=config,
            runtime=runtime,
        )

        expected_keys = tuple(item.obligation_key for item in obligations)
        self.assertEqual(
            tuple(result.obligation_key for result in receipt.ordered_results),
            expected_keys,
        )
        self.assertEqual(receipt.nonempty_obligation_keys, expected_keys)
        self.assertEqual(receipt.outcome, "retrieved")
        self.assertTrue(receipt.execution_complete)
        self.assertTrue(all(result.status == "retrieved" for result in receipt.ordered_results))
        self.assertTrue(all(result.fusion_receipt_sha256 for result in receipt.ordered_results))
        self.assertEqual(_calls(dense_log), ("dense",) * len(obligations))
        self.assertEqual(_calls(lexical_log), ("lexical",) * len(obligations))

    def test_b4_r12_e0_provider_error_is_sanitized_and_incomplete(self):
        store, config, runtime, obligations, dense_log, lexical_log = self._fact_case(
            name="r12", dense_mode="provider_error"
        )

        receipt = execute_e0_control(
            obligations=obligations,
            store=store,
            config=config,
            runtime=runtime,
        )

        self.assertEqual((receipt.outcome, receipt.execution_complete), ("error", False))
        self.assertEqual(receipt.error_obligation_keys, ("$answer_support",))
        result = receipt.ordered_results[0]
        self.assertEqual(result.status, "error")
        self.assertTrue(result.attempted)
        self.assertEqual(result.error_code, "lane_provider_error")
        self.assertIsNone(result.fusion_receipt_sha256)
        self.assertEqual(result.candidate_count, 0)
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), (("dense",), ("lexical",)))
        serialized = json.dumps(receipt.to_dict(), ensure_ascii=False)
        self.assertNotIn("private-provider-detail-must-not-leak", serialized)

    def test_b4_r13_e0_replay_is_rejected_without_more_search(self):
        store, config, runtime, obligations, dense_log, lexical_log = self._fact_case(
            name="r13"
        )
        first = execute_e0_control(
            obligations=obligations,
            store=store,
            config=config,
            runtime=runtime,
        )

        with self.assertRaisesRegex(ValueError, "e0.*already.*consumed"):
            execute_e0_control(
                obligations=obligations,
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual(first.outcome, "retrieved")
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), (("dense",), ("lexical",)))

    def test_b4_r14_e0_rejects_partially_consumed_issuance_without_more_calls(self):
        store, config, runtime, obligations, dense_log, lexical_log = self._fact_case(
            name="r14"
        )
        execute_retrieval_lane(
            obligation=obligations[0],
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )

        with self.assertRaisesRegex(ValueError, "e0.*fresh|partial|already.*consumed"):
            execute_e0_control(
                obligations=obligations,
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), (("dense",), ()))

    def test_b4_r15_e0_requires_e0_mode_before_search(self):
        store, config, runtime, obligations, dense_log, lexical_log = self._fact_case(
            name="r15", mode="e1_bounded"
        )

        with self.assertRaisesRegex(ValueError, "e0.*mode|mode.*e0"):
            execute_e0_control(
                obligations=obligations,
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), ((), ()))

    def test_b4_r16_e0_requires_exact_canonical_issuance_set(self):
        variants = ("missing", "duplicate", "reordered")
        for variant in variants:
            with self.subTest(variant=variant):
                store, config, runtime, obligations, dense_log, lexical_log = self._compare_case(
                    name=f"r16-{variant}"
                )
                if variant == "missing":
                    supplied = obligations[:-1]
                elif variant == "duplicate":
                    supplied = obligations + (obligations[-1],)
                else:
                    supplied = tuple(reversed(obligations))

                with self.assertRaisesRegex(ValueError, "e0.*obligation|canonical.*obligation"):
                    execute_e0_control(
                        obligations=supplied,
                        store=store,
                        config=config,
                        runtime=runtime,
                    )
                self.assertEqual((_calls(dense_log), _calls(lexical_log)), ((), ()))

    def test_b4_r17_e0_payload_is_state_free_and_gold_free(self):
        store, config, runtime, obligations, _dense_log, _lexical_log = self._fact_case(
            name="r17", dense_mode="empty", lexical_mode="empty"
        )
        receipt = execute_e0_control(
            obligations=obligations,
            store=store,
            config=config,
            runtime=runtime,
        )
        payload = receipt.to_dict()
        serialized = json.dumps(payload, ensure_ascii=False).lower()

        for forbidden_key in (
            "state",
            "decision",
            "action",
            "transition",
            "verified",
            "ready",
            "qrels",
            "gold",
            "expected_answer",
            "reference_answer",
        ):
            self.assertNotIn(forbidden_key, payload)
            self.assertNotIn(f'"{forbidden_key}"', serialized)

    def test_b4_r18_public_api_and_dtos_have_no_evaluator_inputs(self):
        public_functions = (
            execute_retrieval_fusion,
            validate_fusion_receipt,
            execute_e0_control,
            validate_e0_control_receipt,
        )
        forbidden = {"gold", "qrels", "expected_answer", "reference_answer"}
        for function in public_functions:
            with self.subTest(function=function.__name__):
                names = set(signature(function).parameters)
                self.assertTrue(names.isdisjoint(forbidden))

        for receipt_type in (FusionReceipt, E0ObligationResult, E0ControlReceipt):
            with self.subTest(receipt_type=receipt_type.__name__):
                slots = set(receipt_type.__slots__)
                self.assertTrue(slots.isdisjoint(forbidden))
                with self.assertRaises(TypeError):
                    receipt_type()

    def test_b4_r19_fusion_and_e0_authorities_do_not_retain_request_graph(self):
        baseline = (
            len(execution_contracts._ISSUED_FUSION_RECEIPT_AUTHORITIES),
            len(execution_contracts._ISSUED_E0_CONTROL_RECEIPT_AUTHORITIES),
        )

        def build_graph():
            store, config, runtime, obligations, _dense_log, _lexical_log = (
                self._fact_case(name="r19")
            )
            receipt = execute_e0_control(
                obligations=obligations,
                store=store,
                config=config,
                runtime=runtime,
            )
            return tuple(
                weakref.ref(value)
                for value in (
                    store,
                    config,
                    runtime,
                    obligations[0],
                    receipt,
                )
            )

        references = build_graph()
        gc.collect()
        gc.collect()

        self.assertTrue(all(reference() is None for reference in references))
        self.assertEqual(
            (
                len(execution_contracts._ISSUED_FUSION_RECEIPT_AUTHORITIES),
                len(execution_contracts._ISSUED_E0_CONTROL_RECEIPT_AUTHORITIES),
            ),
            baseline,
        )

    def test_b4_r20_copied_globals_fusion_clone_cannot_claim_execution(self):
        store, config, runtime, obligations, _dense_log, _lexical_log = self._fact_case(
            name="r20", mode="e1_bounded"
        )
        obligation = obligations[0]
        dense, lexical = self._lane_pair(
            obligation=obligation,
            store=store,
            config=config,
            runtime=runtime,
        )
        clone = self._copied_globals_clone(execute_retrieval_fusion)

        with self.assertRaisesRegex(ValueError, "fusion_executor_authority_required"):
            clone(
                obligation=obligation,
                dense_receipt=dense,
                lexical_receipt=lexical,
                store=store,
                config=config,
                runtime=runtime,
            )

        receipt = self._fuse(
            obligation=obligation,
            dense=dense,
            lexical=lexical,
            store=store,
            config=config,
            runtime=runtime,
        )
        self.assertEqual(receipt.outcome, "applied")

    def test_b4_r21_copied_globals_e0_clone_cannot_start_providers(self):
        store, config, runtime, obligations, dense_log, lexical_log = self._fact_case(
            name="r21"
        )
        clone = self._copied_globals_clone(execute_e0_control)

        with self.assertRaisesRegex(
            ValueError, "e0_control_executor_authority_required"
        ):
            clone(
                obligations=obligations,
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), ((), ()))

        receipt = execute_e0_control(
            obligations=obligations,
            store=store,
            config=config,
            runtime=runtime,
        )
        self.assertEqual(receipt.outcome, "retrieved")

    def test_b4_r22_fusion_dependency_drift_rejects_before_rrf(self):
        store, config, runtime, obligations, _dense_log, _lexical_log = self._fact_case(
            name="r22", mode="e1_bounded"
        )
        obligation = obligations[0]
        dense, lexical = self._lane_pair(
            obligation=obligation,
            store=store,
            config=config,
            runtime=runtime,
        )
        original = execution_contracts._FUSION_RUNTIME_MODULE.fuse_rrf
        calls = []

        def forged_fusion(*args, **kwargs):
            calls.append((args, kwargs))
            return original(*args, **kwargs)

        try:
            execution_contracts._FUSION_RUNTIME_MODULE.fuse_rrf = forged_fusion
            with self.assertRaisesRegex(
                ValueError, "harness_runtime_validation_dependency_drift"
            ):
                self._fuse(
                    obligation=obligation,
                    dense=dense,
                    lexical=lexical,
                    store=store,
                    config=config,
                    runtime=runtime,
                )
        finally:
            execution_contracts._FUSION_RUNTIME_MODULE.fuse_rrf = original

        self.assertEqual(calls, [])
        receipt = self._fuse(
            obligation=obligation,
            dense=dense,
            lexical=lexical,
            store=store,
            config=config,
            runtime=runtime,
        )
        self.assertEqual(receipt.outcome, "applied")

    def test_b4_r23_concurrent_e0_control_has_one_winner(self):
        store, config, runtime, obligations, dense_log, lexical_log = self._fact_case(
            name="r23", dense_delay=0.05
        )
        barrier = Barrier(3)

        def invoke():
            barrier.wait()
            try:
                return (
                    "receipt",
                    execute_e0_control(
                        obligations=obligations,
                        store=store,
                        config=config,
                        runtime=runtime,
                    ),
                )
            except Exception as exc:
                return "error", exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = (pool.submit(invoke), pool.submit(invoke))
            barrier.wait()
            outcomes = tuple(future.result(timeout=2) for future in futures)

        self.assertEqual(tuple(kind for kind, _ in outcomes).count("receipt"), 1)
        self.assertEqual(tuple(kind for kind, _ in outcomes).count("error"), 1)
        error = next(value for kind, value in outcomes if kind == "error")
        self.assertIs(type(error), ValueError)
        self.assertRegex(str(error), "e0.*already.*consumed")
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), (("dense",), ("lexical",)))

    def test_b4_r24_e0_fails_closed_when_provider_replaces_child_executor(self):
        module_name = f"_midprojectrag_b4_executor_swap_{id(self)}"
        store, config, runtime, obligations, dense_log, lexical_log = self._fact_case(
            name="r24", dense_reentry_module=module_name
        )
        bridge = ModuleType(module_name)
        original = execution_contracts.execute_retrieval_lane
        forged_calls = []

        def forged_lane_executor(**kwargs):
            forged_calls.append(kwargs)
            return object()

        bridge.invoke = lambda: setattr(
            execution_contracts,
            "execute_retrieval_lane",
            forged_lane_executor,
        )
        sys.modules[module_name] = bridge
        baseline = len(execution_contracts._ISSUED_E0_CONTROL_RECEIPT_AUTHORITIES)
        try:
            with self.assertRaisesRegex(
                ValueError, "harness_runtime_validation_dependency_drift"
            ):
                execute_e0_control(
                    obligations=obligations,
                    store=store,
                    config=config,
                    runtime=runtime,
                )
        finally:
            execution_contracts.execute_retrieval_lane = original
            sys.modules.pop(module_name, None)

        self.assertEqual(forged_calls, [])
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), (("dense",), ()))
        self.assertEqual(
            len(execution_contracts._ISSUED_E0_CONTROL_RECEIPT_AUTHORITIES),
            baseline,
        )

    def test_b4_r25_next_obligation_lane_waits_for_prior_fusion(self):
        store, config, runtime, obligations, dense_log, lexical_log = self._compare_case(
            name="r25", mode="e1_bounded"
        )
        first_dense, first_lexical = self._lane_pair(
            obligation=obligations[0],
            store=store,
            config=config,
            runtime=runtime,
        )

        with self.assertRaisesRegex(ValueError, "fusion_execution_order_violation"):
            execute_retrieval_lane(
                obligation=obligations[1],
                lane="dense",
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), (("dense",), ("lexical",)))

        self._fuse(
            obligation=obligations[0],
            dense=first_dense,
            lexical=first_lexical,
            store=store,
            config=config,
            runtime=runtime,
        )
        second_dense = execute_retrieval_lane(
            obligation=obligations[1],
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        self.assertEqual(second_dense.outcome, "applied")
        self.assertEqual(_calls(dense_log), ("dense", "dense"))

    def test_b4_r26_fusion_progress_cell_replacement_cannot_replay_pair(self):
        store, config, runtime, obligations, _dense_log, _lexical_log = self._fact_case(
            name="r26", mode="e1_bounded"
        )
        obligation = obligations[0]
        dense, lexical = self._lane_pair(
            obligation=obligation,
            store=store,
            config=config,
            runtime=runtime,
        )
        first = self._fuse(
            obligation=obligation,
            dense=dense,
            lexical=lexical,
            store=store,
            config=config,
            runtime=runtime,
        )
        claim = execution_contracts._claim_fusion_execution
        closure = claim.__closure__
        self.assertIsNotNone(closure)
        cells = dict(zip(claim.__code__.co_freevars, closure))
        progress_cell = cells["progress"]
        original_progress = progress_cell.cell_contents
        try:
            progress_cell.cell_contents = {}
            with self.assertRaisesRegex(
                ValueError, "harness_runtime_validation_dependency_drift"
            ):
                self._fuse(
                    obligation=obligation,
                    dense=dense,
                    lexical=lexical,
                    store=store,
                    config=config,
                    runtime=runtime,
                )
        finally:
            progress_cell.cell_contents = original_progress

        self.assertEqual(first.outcome, "applied")
        with self.assertRaisesRegex(ValueError, "fusion_pair_already_consumed"):
            self._fuse(
                obligation=obligation,
                dense=dense,
                lexical=lexical,
                store=store,
                config=config,
                runtime=runtime,
            )

    def test_b4_r27_cleared_fusion_progress_cannot_replay_live_pair(self):
        store, config, runtime, obligations, _dense_log, _lexical_log = self._fact_case(
            name="r27", mode="e1_bounded"
        )
        obligation = obligations[0]
        dense, lexical = self._lane_pair(
            obligation=obligation,
            store=store,
            config=config,
            runtime=runtime,
        )
        first = self._fuse(
            obligation=obligation,
            dense=dense,
            lexical=lexical,
            store=store,
            config=config,
            runtime=runtime,
        )
        claim = execution_contracts._claim_fusion_execution
        cells = dict(zip(claim.__code__.co_freevars, claim.__closure__))
        progress = cells["progress"].cell_contents
        history = cells["history"].cell_contents
        saved_progress = dict(progress)
        saved_history = dict(history)
        self.assertEqual(set(saved_progress), set(saved_history))
        live_ledgers = tuple(
            entry[0]() for entry in saved_progress.values()
        )
        self.assertTrue(live_ledgers)
        self.assertTrue(all(ledger is not None for ledger in live_ledgers))
        first_reference = weakref.ref(first)
        del first
        gc.collect()
        gc.collect()
        self.assertIsNone(first_reference())
        try:
            progress.clear()
            with self.assertRaisesRegex(
                ValueError, "fusion_execution_authority_drift"
            ):
                self._fuse(
                    obligation=obligation,
                    dense=dense,
                    lexical=lexical,
                    store=store,
                    config=config,
                    runtime=runtime,
                )
        finally:
            progress.clear()
            history.clear()
            for identity, entry in saved_progress.items():
                if saved_history.get(identity) is entry and entry[0]() is not None:
                    progress[identity] = entry
                    history[identity] = entry


if __name__ == "__main__":
    unittest.main()
