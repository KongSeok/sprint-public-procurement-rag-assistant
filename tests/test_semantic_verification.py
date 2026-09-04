"""EH2.6.c2 semantic verification execution contracts.

All fixtures are synthetic and offline.  Call logs live outside sealed adapter
state so exact runtime validation remains meaningful after one invocation.
"""

from concurrent.futures import ThreadPoolExecutor
import copy
from dataclasses import replace
import gc
import inspect
import json
from pathlib import Path
import pickle
import sys
from tempfile import TemporaryDirectory
from threading import Barrier
from types import ModuleType
import unittest
from weakref import ref

import midprojectrag.orchestration.execution_contracts as execution_contracts
from midprojectrag.orchestration import (
    HarnessRuntimeBinding,
    RequiredSlot,
    SemanticVerificationObligation,
    SemanticVerificationReceipt,
    create_harness_execution_config,
    execute_retrieval_fusion,
    execute_retrieval_lane,
    issue_compare_retrieval_obligations,
    issue_compare_semantic_verification_obligation,
    issue_fact_retrieval_obligations,
    issue_fact_semantic_verification_obligation,
    issue_followup_semantic_verification_obligation,
    validate_harness_runtime_binding,
    validate_semantic_verification_obligation,
    validate_semantic_verification_receipt,
)
from midprojectrag.retrieval.fusion import HybridChildRetriever

from tests.test_e1_followup_projection import _fixture as _followup_fixture
from tests.test_retrieval_obligations import (
    _SyntheticLane,
    _calls,
    _clock,
    _compare_bound,
    _fact_bound,
    _store,
)


class _SemanticVerifier:
    def __init__(self, *, raw_result, call_log_path):
        self.raw_result = raw_result
        self.call_log_path = str(call_log_path)

    def verify(self, request):
        with open(self.call_log_path, "a", encoding="utf-8") as handle:
            handle.write("verify\n")
        return self.raw_result


class _RaisingSemanticVerifier:
    def __init__(self, *, call_log_path):
        self.call_log_path = str(call_log_path)

    def verify(self, request):
        with open(self.call_log_path, "a", encoding="utf-8") as handle:
            handle.write("verify\n")
        raise RuntimeError("private-provider-secret-must-not-leak")


class _BadAbiVerifier:
    def __init__(self, *, call_log_path):
        self.call_log_path = str(call_log_path)

    def verify(self, request, optional=None):
        with open(self.call_log_path, "a", encoding="utf-8") as handle:
            handle.write("verify\n")
        return {
            "schema_version": "1.0",
            "disposition": "supported",
            "support_indexes": [0],
            "values": [],
        }


class _RequestRecordingVerifier:
    def __init__(self, *, raw_result, request_log_path):
        self.raw_result = raw_result
        self.request_log_path = str(request_log_path)

    def verify(self, request):
        with open(self.request_log_path, "w", encoding="utf-8") as handle:
            handle.write(
                "\t".join(
                    (
                        request.source_kind,
                        request.target_kind,
                        request.obligation_key,
                        str(request.target_doc_id),
                        str(request.field),
                        request.query,
                        str(hasattr(request, "to_dict")),
                        str(hasattr(request, "__dict__")),
                    )
                )
                + "\n"
            )
            for item in request.evidence:
                handle.write(
                    "\t".join(
                        (
                            str(item.index),
                            item.role,
                            item.doc_id,
                            item.content_kind,
                            item.content,
                            str(hasattr(item, "evidence_id")),
                        )
                    )
                    + "\n"
                )
        return self.raw_result


class _ReentrySemanticVerifier:
    def __init__(self, *, raw_result, call_log_path, reentry_module):
        self.raw_result = raw_result
        self.call_log_path = str(call_log_path)
        self.reentry_module = reentry_module

    def verify(self, request):
        with open(self.call_log_path, "a", encoding="utf-8") as handle:
            handle.write("verify\n")
        import importlib as _importlib

        _importlib.import_module(self.reentry_module).invoke()
        return self.raw_result


def _raw(disposition="supported", support_indexes=(0,), values=()):
    return {
        "schema_version": "1.0",
        "disposition": disposition,
        "support_indexes": list(support_indexes),
        "values": list(values),
    }


def _value(value_type, canonical_value, support_indexes=(0,)):
    return {
        "value_type": value_type,
        "canonical_value": canonical_value,
        "support_indexes": list(support_indexes),
    }


class SemanticVerificationExecutionTests(unittest.TestCase):
    def setUp(self):
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.tempdir = Path(self._temporary.name)

    def _runtime(self, *, store, verifier, name):
        specs = tuple((item.evidence_id, item.doc_id) for item in store.evidence)
        retriever = HybridChildRetriever(
            store,
            _SyntheticLane(
                lane="dense",
                bundle_sha256=store.bundle_sha256,
                candidate_specs=specs,
                call_log_path=str(self.tempdir / f"{name}-dense.log"),
            ),
            _SyntheticLane(
                lane="lexical",
                bundle_sha256=store.bundle_sha256,
                candidate_specs=specs,
                call_log_path=str(self.tempdir / f"{name}-lexical.log"),
            ),
        )
        return HarnessRuntimeBinding.for_test(
            store=store,
            retriever=retriever,
            verifier=verifier,
            clock=_clock,
        )

    def _retrieval_case(self, *, name, source_kind="fact", verifier=None):
        store = _store(doc_ids=("doc-a",) if source_kind == "fact" else ("doc-a", "doc-b"))
        runtime = self._runtime(store=store, verifier=verifier, name=name)
        config = create_harness_execution_config(mode="e1_bounded")
        if source_kind == "fact":
            obligations = issue_fact_retrieval_obligations(
                bound=_fact_bound(store), store=store, config=config, runtime=runtime
            )
        else:
            bound, _registry = _compare_bound(store)
            obligations = issue_compare_retrieval_obligations(
                bound=bound, store=store, config=config, runtime=runtime
            )
        obligation = obligations[0]
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
        fusion = execute_retrieval_fusion(
            obligation=obligation,
            dense_receipt=dense,
            lexical_receipt=lexical,
            store=store,
            config=config,
            runtime=runtime,
        )
        issue = (
            issue_fact_semantic_verification_obligation
            if source_kind == "fact"
            else issue_compare_semantic_verification_obligation
        )
        semantic = issue(
            obligation=obligation,
            fusion_receipt=fusion,
            store=store,
            config=config,
            runtime=runtime,
        )
        return store, config, runtime, semantic

    def test_fact_supported_is_one_exact_call_and_trace_free_receipt(self):
        call_log = self.tempdir / "fact-verifier.log"
        verifier = _SemanticVerifier(raw_result=_raw(), call_log_path=call_log)
        store, config, runtime, obligation = self._retrieval_case(
            name="fact-supported", verifier=verifier
        )

        receipt = execution_contracts.execute_semantic_verification(
            obligation=obligation,
            store=store,
            config=config,
            runtime=runtime,
        )

        self.assertIs(type(obligation), SemanticVerificationObligation)
        self.assertIs(type(receipt), SemanticVerificationReceipt)
        self.assertEqual((receipt.disposition, receipt.call_performed), ("supported", True))
        self.assertEqual(receipt.verified_evidence_ids, (obligation.candidate_evidence_ids[0],))
        self.assertEqual(receipt.contradicted_evidence_ids, ())
        self.assertEqual(receipt.values, ())
        self.assertEqual(_calls(call_log), ("verify",))
        validate_semantic_verification_obligation(
            obligation=obligation, store=store, config=config, runtime=runtime
        )
        validate_semantic_verification_receipt(
            receipt=receipt,
            obligation=obligation,
            store=store,
            config=config,
            runtime=runtime,
        )
        serialized = json.dumps(receipt.to_dict(), ensure_ascii=False)
        obligation_payload = obligation.to_dict()
        self.assertEqual(
            set(obligation_payload),
            {
                "schema_version",
                "source_kind",
                "target_kind",
                "obligation_key",
                "target_doc_id",
                "field",
                "execution_kind",
                "owner_binding_sha256",
                "retrieval_obligation_sha256",
                "candidate_receipt_sha256",
                "source_state_sha256",
                "query_sha256",
                "evidence_store_sha256",
                "execution_config_sha256",
                "runtime_binding_sha256",
                "candidate_evidence_ids",
                "bridge_evidence_ids",
                "context_evidence_ids",
                "supplied_evidence_ids",
                "ordered_stable_anchors",
                "obligation_sha256",
            },
        )
        self.assertEqual(obligation.bridge_evidence_ids, ())
        self.assertEqual(obligation.context_evidence_ids, ())
        self.assertEqual(
            obligation.supplied_evidence_ids,
            obligation.candidate_evidence_ids,
        )
        for forbidden in (
            "사업 예산은 얼마인가?",
            "doc-a 근거 0",
            "gold",
            "qrels",
            "private-provider",
        ):
            self.assertNotIn(forbidden, serialized)
            self.assertNotIn(forbidden, repr(receipt))

    def test_private_request_is_owner_derived_contiguous_and_idless(self):
        request_log = self.tempdir / "request.json"
        verifier = _RequestRecordingVerifier(
            raw_result=_raw(), request_log_path=request_log
        )
        store, config, runtime, obligation = self._retrieval_case(
            name="request-shape", verifier=verifier
        )
        authority = execution_contracts._read_semantic_obligation_authority(
            obligation
        )
        private_request = execution_contracts._semantic_verifier_request(
            obligation=obligation,
            authority=authority,
        )
        for private_value in (private_request, *private_request.evidence):
            with self.subTest(private_type=type(private_value).__name__):
                with self.assertRaisesRegex(TypeError, "not_serializable"):
                    pickle.dumps(private_value)
                with self.assertRaisesRegex(TypeError, "not_serializable"):
                    copy.copy(private_value)
                with self.assertRaisesRegex(TypeError, "not_serializable"):
                    copy.deepcopy(private_value)

        execution_contracts.execute_semantic_verification(
            obligation=obligation,
            store=store,
            config=config,
            runtime=runtime,
        )

        lines = request_log.read_text(encoding="utf-8").splitlines()
        header = lines[0].split("\t")
        evidence = tuple(line.split("\t") for line in lines[1:])
        self.assertEqual(header[5], "사업 예산은 얼마인가?")
        self.assertEqual(header[:3], ["fact", "answer_support", "$answer_support"])
        self.assertEqual(header[6:], ["False", "False"])
        self.assertEqual(
            [int(item[0]) for item in evidence],
            list(range(len(evidence))),
        )
        self.assertTrue(all(item[1] == "candidate" for item in evidence))
        self.assertTrue(all(item[5] == "False" for item in evidence))
        self.assertEqual(
            [item[2] for item in evidence],
            ["doc-a"] * len(evidence),
        )
        with self.assertRaisesRegex(TypeError, "factory_required"):
            execution_contracts._SemanticVerifierRequest()
        with self.assertRaisesRegex(TypeError, "factory_required"):
            execution_contracts._SemanticVerifierEvidence()

    def test_compare_value_is_field_derived_and_typed(self):
        call_log = self.tempdir / "compare-verifier.log"
        verifier = _SemanticVerifier(
            raw_result=_raw(values=(_value("krw_amount", "100"),)),
            call_log_path=call_log,
        )
        store, config, runtime, obligation = self._retrieval_case(
            name="compare-supported", source_kind="compare", verifier=verifier
        )

        receipt = execution_contracts.execute_semantic_verification(
            obligation=obligation, store=store, config=config, runtime=runtime
        )

        self.assertEqual((obligation.target_doc_id, obligation.field), ("doc-a", "budget"))
        self.assertEqual(receipt.values[0].value_type, "krw_amount")
        self.assertEqual(receipt.values[0].canonical_value, "100")
        self.assertEqual(_calls(call_log), ("verify",))

    def test_unsupported_and_contradicted_receipts_are_end_to_end(self):
        unsupported_log = self.tempdir / "unsupported.log"
        store, config, runtime, obligation = self._retrieval_case(
            name="unsupported",
            verifier=_SemanticVerifier(
                raw_result=_raw("unsupported", ()),
                call_log_path=unsupported_log,
            ),
        )
        unsupported = execution_contracts.execute_semantic_verification(
            obligation=obligation, store=store, config=config, runtime=runtime
        )
        self.assertEqual(unsupported.disposition, "unsupported")
        self.assertEqual(unsupported.verified_evidence_ids, ())
        self.assertEqual(unsupported.contradicted_evidence_ids, ())
        validate_semantic_verification_receipt(
            receipt=unsupported,
            obligation=obligation,
            store=store,
            config=config,
            runtime=runtime,
        )

        contradicted_log = self.tempdir / "contradicted.log"
        verifier = _SemanticVerifier(
            raw_result=_raw(
                "contradicted",
                (0, 1),
                (
                    _value("krw_amount", "100", (0,)),
                    _value("krw_amount", "200", (1,)),
                ),
            ),
            call_log_path=contradicted_log,
        )
        store, config, runtime, obligation = self._retrieval_case(
            name="contradicted", source_kind="compare", verifier=verifier
        )
        contradicted = execution_contracts.execute_semantic_verification(
            obligation=obligation, store=store, config=config, runtime=runtime
        )
        self.assertEqual(contradicted.disposition, "contradicted")
        self.assertEqual(
            contradicted.contradicted_evidence_ids,
            obligation.candidate_evidence_ids[:2],
        )
        self.assertEqual(
            tuple(item.canonical_value for item in contradicted.values),
            ("100", "200"),
        )
        validate_semantic_verification_receipt(
            receipt=contradicted,
            obligation=obligation,
            store=store,
            config=config,
            runtime=runtime,
        )

    def test_followup_target_is_rebuilt_from_exact_c1_projection(self):
        fixture = _followup_fixture(primary_ids=(0,), fallback_ids=(1,))
        store, _evidence, registry, policy, bound, outcome, _retriever = fixture
        call_log = self.tempdir / "followup-verifier.log"
        runtime = self._runtime(
            store=store,
            verifier=_SemanticVerifier(raw_result=_raw(), call_log_path=call_log),
            name="followup",
        )
        config = create_harness_execution_config(mode="e1_bounded")
        obligation = issue_followup_semantic_verification_obligation(
            bound=bound,
            outcome=outcome,
            obligation_key="$answer_support",
            store=store,
            registry=registry,
            policy=policy,
            config=config,
            runtime=runtime,
        )

        receipt = execution_contracts.execute_semantic_verification(
            obligation=obligation, store=store, config=config, runtime=runtime
        )

        self.assertEqual(obligation.source_kind, "follow_up")
        self.assertIsNotNone(obligation.source_state_sha256)
        self.assertEqual(receipt.disposition, "supported")
        self.assertEqual(_calls(call_log), ("verify",))

    def test_followup_field_slot_is_typed_and_source_state_is_unchanged(self):
        slot = RequiredSlot("doc-a", "duration")
        fixture = _followup_fixture(
            explicit_scope=True,
            slots=(slot,),
            primary_ids=(0,),
            fallback_ids=(),
        )
        store, _evidence, registry, policy, bound, outcome, _retriever = fixture
        call_log = self.tempdir / "followup-slot.log"
        runtime = self._runtime(
            store=store,
            verifier=_SemanticVerifier(
                raw_result=_raw(
                    values=(_value("duration", "P10D", (0,)),)
                ),
                call_log_path=call_log,
            ),
            name="followup-slot",
        )
        config = create_harness_execution_config(mode="e1_bounded")
        obligation = issue_followup_semantic_verification_obligation(
            bound=bound,
            outcome=outcome,
            obligation_key=slot.key,
            store=store,
            registry=registry,
            policy=policy,
            config=config,
            runtime=runtime,
        )
        authority = execution_contracts._read_semantic_obligation_authority(
            obligation
        )
        source_state = authority.source_state
        before = source_state.to_dict()

        receipt = execution_contracts.execute_semantic_verification(
            obligation=obligation, store=store, config=config, runtime=runtime
        )

        self.assertEqual((obligation.target_doc_id, obligation.field), ("doc-a", "duration"))
        self.assertEqual(receipt.values[0].value_type, "duration")
        self.assertEqual(receipt.values[0].canonical_value, "P10D")
        self.assertIs(authority.source_state, source_state)
        self.assertEqual(source_state.to_dict(), before)

    def test_unavailable_is_zero_call_and_truthful_receipt(self):
        store, config, runtime, obligation = self._retrieval_case(
            name="unavailable", verifier=None
        )

        receipt = execution_contracts.execute_semantic_verification(
            obligation=obligation, store=store, config=config, runtime=runtime
        )

        self.assertEqual((receipt.disposition, receipt.call_performed), ("unavailable", False))
        self.assertEqual(receipt.verified_evidence_ids, ())
        self.assertEqual(receipt.contradicted_evidence_ids, ())
        self.assertEqual(receipt.values, ())

    def test_bad_abi_is_rejected_before_call(self):
        call_log = self.tempdir / "bad-abi.log"
        store, config, runtime, obligation = self._retrieval_case(
            name="bad-abi",
            verifier=_BadAbiVerifier(call_log_path=call_log),
        )

        with self.assertRaisesRegex(ValueError, "semantic_verifier_protocol"):
            execution_contracts.execute_semantic_verification(
                obligation=obligation, store=store, config=config, runtime=runtime
            )
        self.assertEqual(_calls(call_log), ())

        with self.assertRaisesRegex(ValueError, "semantic_verifier_protocol"):
            execution_contracts.execute_semantic_verification(
                obligation=obligation, store=store, config=config, runtime=runtime
            )
        self.assertEqual(_calls(call_log), ())

    def test_post_call_dependency_drift_is_sanitized_and_consumes_attempt(self):
        call_log = self.tempdir / "post-call-drift.log"
        module_name = f"_midprojectrag_semantic_drift_{id(self)}"
        bridge = ModuleType(module_name)
        bridge.invoke = lambda: setattr(
            execution_contracts, "SCHEMA_VERSION", "9.9"
        )
        sys.modules[module_name] = bridge
        store, config, runtime, obligation = self._retrieval_case(
            name="post-call-drift",
            verifier=_ReentrySemanticVerifier(
                raw_result=_raw(),
                call_log_path=call_log,
                reentry_module=module_name,
            ),
        )
        original = execution_contracts.SCHEMA_VERSION
        try:
            with self.assertRaisesRegex(
                ValueError, "semantic_verifier_contract_error"
            ) as raised:
                execution_contracts.execute_semantic_verification(
                    obligation=obligation,
                    store=store,
                    config=config,
                    runtime=runtime,
                )
            self.assertNotIn("9.9", str(raised.exception))
        finally:
            execution_contracts.SCHEMA_VERSION = original
            sys.modules.pop(module_name, None)
        with self.assertRaisesRegex(ValueError, "already_consumed"):
            execution_contracts.execute_semantic_verification(
                obligation=obligation,
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual(_calls(call_log), ("verify",))

    def test_malformed_or_provider_error_consumes_attempt_and_sanitizes(self):
        cases = (
            (
                "malformed",
                _SemanticVerifier(
                    raw_result={"secret": "provider-body"},
                    call_log_path=self.tempdir / "malformed.log",
                ),
                self.tempdir / "malformed.log",
                "semantic_verifier_contract_error",
            ),
            (
                "provider",
                _RaisingSemanticVerifier(call_log_path=self.tempdir / "provider.log"),
                self.tempdir / "provider.log",
                "semantic_verifier_provider_error",
            ),
        )
        for name, verifier, call_log, expected in cases:
            with self.subTest(name=name):
                store, config, runtime, obligation = self._retrieval_case(
                    name=name, verifier=verifier
                )
                with self.assertRaisesRegex(ValueError, expected) as raised:
                    execution_contracts.execute_semantic_verification(
                        obligation=obligation,
                        store=store,
                        config=config,
                        runtime=runtime,
                    )
                self.assertNotIn("secret", str(raised.exception))
                self.assertNotIn("private-provider", str(raised.exception))
                with self.assertRaisesRegex(ValueError, "already_consumed"):
                    execution_contracts.execute_semantic_verification(
                        obligation=obligation,
                        store=store,
                        config=config,
                        runtime=runtime,
                    )
                self.assertEqual(_calls(call_log), ("verify",))

    def test_concurrent_execution_has_one_winner_and_one_call(self):
        call_log = self.tempdir / "concurrent.log"
        store, config, runtime, obligation = self._retrieval_case(
            name="concurrent",
            verifier=_SemanticVerifier(raw_result=_raw(), call_log_path=call_log),
        )
        barrier = Barrier(3)

        def invoke():
            barrier.wait()
            try:
                return execution_contracts.execute_semantic_verification(
                    obligation=obligation, store=store, config=config, runtime=runtime
                )
            except Exception as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = (pool.submit(invoke), pool.submit(invoke))
            barrier.wait()
            outcomes = tuple(future.result(timeout=2) for future in futures)

        self.assertEqual(sum(type(item) is SemanticVerificationReceipt for item in outcomes), 1)
        error = next(item for item in outcomes if type(item) is ValueError)
        self.assertRegex(str(error), "already_consumed")
        self.assertEqual(_calls(call_log), ("verify",))

    def test_success_history_survives_receipt_gc_then_clears_with_source(self):
        call_log = self.tempdir / "receipt-gc.log"
        store, config, runtime, obligation = self._retrieval_case(
            name="receipt-gc",
            verifier=_SemanticVerifier(raw_result=_raw(), call_log_path=call_log),
        )
        authority = execution_contracts._read_semantic_obligation_authority(
            obligation
        )
        execution_key = execution_contracts._semantic_execution_key(
            authority, obligation
        )
        source = authority.source
        source_weak = ref(source)
        receipt = execution_contracts.execute_semantic_verification(
            obligation=obligation, store=store, config=config, runtime=runtime
        )
        receipt_weak = ref(receipt)
        del receipt
        gc.collect()
        self.assertIsNone(receipt_weak())
        with self.assertRaisesRegex(ValueError, "already_consumed"):
            execution_contracts.execute_semantic_verification(
                obligation=obligation, store=store, config=config, runtime=runtime
            )
        self.assertEqual(_calls(call_log), ("verify",))
        self.assertEqual(
            execution_contracts._semantic_execution_status(execution_key),
            "completed",
        )

        del source
        del authority
        del obligation
        gc.collect()
        self.assertIsNone(source_weak())
        self.assertIsNone(
            execution_contracts._semantic_execution_status(execution_key)
        )

    def test_mismatched_fusion_and_empty_candidates_fail_before_verifier(self):
        log_a = self.tempdir / "mismatch-a.log"
        store_a, config_a, runtime_a, semantic_a = self._retrieval_case(
            name="mismatch-a",
            verifier=_SemanticVerifier(raw_result=_raw(), call_log_path=log_a),
        )
        authority_a = execution_contracts._read_semantic_obligation_authority(
            semantic_a
        )
        log_b = self.tempdir / "mismatch-b.log"
        _store_b, _config_b, _runtime_b, semantic_b = self._retrieval_case(
            name="mismatch-b",
            verifier=_SemanticVerifier(raw_result=_raw(), call_log_path=log_b),
        )
        authority_b = execution_contracts._read_semantic_obligation_authority(
            semantic_b
        )
        with self.assertRaises((TypeError, ValueError)):
            issue_fact_semantic_verification_obligation(
                obligation=authority_a.retrieval_obligation,
                fusion_receipt=authority_b.fusion_receipt,
                store=store_a,
                config=config_a,
                runtime=runtime_a,
            )
        self.assertEqual(_calls(log_a), ())
        self.assertEqual(_calls(log_b), ())

        empty_store = _store(doc_ids=("doc-a",))
        empty_log = self.tempdir / "empty-verifier.log"
        empty_specs = tuple(
            (item.evidence_id, item.doc_id) for item in empty_store.evidence
        )
        empty_retriever = HybridChildRetriever(
            empty_store,
            _SyntheticLane(
                lane="dense",
                bundle_sha256=empty_store.bundle_sha256,
                candidate_specs=empty_specs,
                call_log_path=str(self.tempdir / "empty-dense.log"),
                mode="empty",
            ),
            _SyntheticLane(
                lane="lexical",
                bundle_sha256=empty_store.bundle_sha256,
                candidate_specs=empty_specs,
                call_log_path=str(self.tempdir / "empty-lexical.log"),
                mode="empty",
            ),
        )
        empty_runtime = HarnessRuntimeBinding.for_test(
            store=empty_store,
            retriever=empty_retriever,
            verifier=_SemanticVerifier(
                raw_result=_raw(), call_log_path=empty_log
            ),
            clock=_clock,
        )
        empty_config = create_harness_execution_config(mode="e1_bounded")
        retrieval = issue_fact_retrieval_obligations(
            bound=_fact_bound(empty_store),
            store=empty_store,
            config=empty_config,
            runtime=empty_runtime,
        )[0]
        dense = execute_retrieval_lane(
            obligation=retrieval,
            lane="dense",
            store=empty_store,
            config=empty_config,
            runtime=empty_runtime,
        )
        lexical = execute_retrieval_lane(
            obligation=retrieval,
            lane="lexical",
            store=empty_store,
            config=empty_config,
            runtime=empty_runtime,
        )
        fusion = execute_retrieval_fusion(
            obligation=retrieval,
            dense_receipt=dense,
            lexical_receipt=lexical,
            store=empty_store,
            config=empty_config,
            runtime=empty_runtime,
        )
        self.assertEqual(fusion.outcome, "empty")
        with self.assertRaisesRegex(ValueError, "candidates_required"):
            issue_fact_semantic_verification_obligation(
                obligation=retrieval,
                fusion_receipt=fusion,
                store=empty_store,
                config=empty_config,
                runtime=empty_runtime,
            )
        self.assertEqual(_calls(empty_log), ())

    def test_public_signatures_take_no_raw_semantic_authority(self):
        public_functions = (
            issue_fact_semantic_verification_obligation,
            issue_compare_semantic_verification_obligation,
            issue_followup_semantic_verification_obligation,
            execution_contracts.execute_semantic_verification,
            validate_semantic_verification_receipt,
        )
        forbidden = {
            "query",
            "field",
            "evidence_ids",
            "candidate_ids",
            "disposition",
            "values",
            "raw_result",
            "gold",
            "qrels",
            "expected_answer",
        }
        for function in public_functions:
            with self.subTest(function=function.__name__):
                parameters = inspect.signature(function).parameters
                self.assertTrue(forbidden.isdisjoint(parameters))
                self.assertTrue(
                    all(
                        parameter.kind
                        not in {
                            inspect.Parameter.VAR_POSITIONAL,
                            inspect.Parameter.VAR_KEYWORD,
                        }
                        for parameter in parameters.values()
                    )
                )

    def test_runtime_authority_visible_or_shadow_single_swap_fails_closed(self):
        store = _store(doc_ids=("doc-a",))
        runtime = self._runtime(store=store, verifier=None, name="runtime-mirror")
        identity = id(runtime)
        visible = execution_contracts._ISSUED_RUNTIME_AUTHORITIES
        shadow = execution_contracts._ISSUED_RUNTIME_AUTHORITY_SHADOW
        original = visible[identity]
        forged = replace(original)

        visible[identity] = forged
        try:
            with self.assertRaisesRegex(ValueError, "harness_runtime_authority_required"):
                validate_harness_runtime_binding(binding=runtime, store=store)
        finally:
            visible[identity] = original

        shadow[identity] = forged
        try:
            with self.assertRaisesRegex(ValueError, "harness_runtime_authority_required"):
                validate_harness_runtime_binding(binding=runtime, store=store)
        finally:
            shadow[identity] = original

        validate_harness_runtime_binding(binding=runtime, store=store)

    def test_semantic_global_or_unicode_rebinding_fails_before_call(self):
        cases = ("schema", "unicode")
        for name in cases:
            with self.subTest(name=name):
                call_log = self.tempdir / f"{name}-dependency.log"
                store, config, runtime, obligation = self._retrieval_case(
                    name=f"{name}-dependency",
                    verifier=_SemanticVerifier(
                        raw_result=_raw(), call_log_path=call_log
                    ),
                )
                if name == "schema":
                    original = execution_contracts.SCHEMA_VERSION
                    execution_contracts.SCHEMA_VERSION = "9.9"
                    restore = lambda: setattr(
                        execution_contracts, "SCHEMA_VERSION", original
                    )
                else:
                    unicode_module = execution_contracts._ACTION_EFFECTS_MODULE.unicodedata
                    original = unicode_module.normalize
                    unicode_module.normalize = lambda form, value: value
                    restore = lambda: setattr(unicode_module, "normalize", original)
                try:
                    with self.assertRaisesRegex(
                        ValueError,
                        "harness_runtime_validation_dependency_drift",
                    ):
                        execution_contracts.execute_semantic_verification(
                            obligation=obligation,
                            store=store,
                            config=config,
                            runtime=runtime,
                        )
                finally:
                    restore()
                self.assertEqual(_calls(call_log), ())

    def test_equal_payload_obligation_clone_and_mixed_store_fail_closed(self):
        call_log = self.tempdir / "clone.log"
        store, config, runtime, obligation = self._retrieval_case(
            name="clone",
            verifier=_SemanticVerifier(raw_result=_raw(), call_log_path=call_log),
        )
        clone = object.__new__(SemanticVerificationObligation)
        for name in SemanticVerificationObligation.__slots__:
            if name != "__weakref__":
                object.__setattr__(clone, name, getattr(obligation, name))
        with self.assertRaisesRegex(ValueError, "semantic_verification_obligation.*authority"):
            execution_contracts.execute_semantic_verification(
                obligation=clone, store=store, config=config, runtime=runtime
            )
        with self.assertRaises((TypeError, ValueError)):
            execution_contracts.execute_semantic_verification(
                obligation=obligation,
                store=_store(doc_ids=("doc-a",)),
                config=config,
                runtime=runtime,
            )
        self.assertEqual(_calls(call_log), ())


if __name__ == "__main__":
    unittest.main()
