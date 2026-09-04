"""B3 retrieval-obligation contract tests with synthetic, offline lanes only."""

from concurrent.futures import ThreadPoolExecutor
import gc
import json
from pathlib import Path
from queue import Empty, Queue
import sys
from tempfile import TemporaryDirectory
from threading import Barrier, Thread
from types import FunctionType, ModuleType
import unittest
import weakref

import midprojectrag.orchestration.execution_contracts as execution_contracts
import midprojectrag.orchestration.fact_binding as fact_binding_module
import midprojectrag.retrieval.fusion as fusion_module
from midprojectrag.evidence import Evidence, EvidenceStore, Locator, ProvenanceParent
from midprojectrag.orchestration import (
    CatalogEntity,
    DeterministicPlanner,
    HarnessRuntimeBinding,
    PlanningCatalog,
    bind_fact,
    create_harness_execution_config,
    default_compare_field_registry,
    default_rule_registry,
    execute_retrieval_lane,
    issue_compare_retrieval_obligations,
    issue_fact_retrieval_obligations,
    prepare_compare_slots,
    validate_lane_search_receipt,
    validate_retrieval_obligation,
)
from midprojectrag.retrieval.fusion import HybridChildRetriever
from midprojectrag.runtime_integrity import RuntimeRequest


def _clock():
    return 0


class _SyntheticLane:
    """Sealable lane whose only observation side effect is a tempfile append."""

    def __init__(
        self,
        *,
        lane,
        bundle_sha256,
        candidate_specs,
        call_log_path,
        mode="valid",
        delay_seconds=0.0,
        reentry_module="",
    ):
        self.lane = lane
        self.bundle_sha256 = bundle_sha256
        self.candidate_specs = tuple(candidate_specs)
        self.call_log_path = call_log_path
        self.mode = mode
        self.delay_seconds = delay_seconds
        self.reentry_module = reentry_module

    def search(self, query, limit, *, allowed_doc_ids):
        if self.mode == "pre_call_contract":
            raise ValueError("private-pre-call-contract-detail-must-not-leak")
        # Keep runtime-sealed instance/class/global state untouched.  The log is
        # deliberately outside the sealed authority and exists only in a
        # TemporaryDirectory owned by the test.
        with open(self.call_log_path, "a", encoding="utf-8") as handle:
            handle.write(f"{self.lane}\n")
        if self.delay_seconds:
            import time as _time

            _time.sleep(self.delay_seconds)
        if self.reentry_module:
            import importlib as _importlib

            try:
                _importlib.import_module(self.reentry_module).invoke()
            except Exception as exc:
                with open(self.call_log_path, "a", encoding="utf-8") as handle:
                    handle.write(f"reentry:{type(exc).__name__}:{exc}\n")
        if self.mode == "provider_error":
            from midprojectrag.retrieval.contracts import RetrievalProviderError

            raise RetrievalProviderError("private-provider-detail-must-not-leak")
        if self.mode == "post_call_contract":
            from midprojectrag.retrieval.contracts import (
                RetrievalPostCallContractError,
            )

            raise RetrievalPostCallContractError(
                "private-post-call-detail-must-not-leak"
            )
        if self.mode == "malformed":
            return {"not": "a SearchResult"}

        from midprojectrag.retrieval import Candidate as _Candidate
        from midprojectrag.retrieval import SearchResult as _SearchResult

        selected = tuple(
            spec
            for spec in self.candidate_specs
            if allowed_doc_ids is None or spec[1] in allowed_doc_ids
        )
        if self.mode == "empty":
            selected = ()
        elif self.mode != "over_limit":
            selected = selected[:limit]
        candidates = tuple(
            _Candidate(
                evidence_id,
                doc_id,
                1.0 / rank,
                self.lane,
                rank,
                "child",
            )
            for rank, (evidence_id, doc_id) in enumerate(selected, 1)
        )
        return _SearchResult(
            candidates,
            {
                "lane": self.lane,
                "granularity": "child",
                "bundle_sha256": self.bundle_sha256,
                # Poison fields prove that only the safe receipt projection is
                # serialized, never raw question/gold-lineage data.
                "question": query,
                "qrels": ["gold-must-not-leak"],
            },
        )


def _store(*, doc_ids=("doc-a", "doc-b"), chunks_per_doc=3):
    parents = []
    evidence = []
    for page, doc_id in enumerate(doc_ids, 1):
        chunks = tuple(
            f"{doc_id} 근거 {index}: 예산 {index + 1}원, 수행기간 {index + 1}일"
            for index in range(chunks_per_doc)
        )
        text = "\n".join(chunks)
        block_id = f"block-{doc_id}"
        parent = ProvenanceParent(
            doc_id,
            "pdf_page",
            text,
            (block_id,),
            Locator(page=page),
        )
        parents.append(parent)
        cursor = 0
        for chunk in chunks:
            start = text.index(chunk, cursor)
            cursor = start + len(chunk)
            evidence.append(
                Evidence(
                    doc_id,
                    "text",
                    chunk,
                    parent.parent_id,
                    (block_id,),
                    Locator(page=page, char_range=(start, cursor)),
                )
            )
    return EvidenceStore(parents, evidence)


def _planner(doc_ids):
    entities = tuple(
        CatalogEntity(
            f"사업{chr(65 + index)}",
            f"사업{chr(65 + index)}",
            "business",
            (doc_id,),
            "business_alias",
        )
        for index, doc_id in enumerate(doc_ids)
    )
    catalog = PlanningCatalog.synthetic("b3-retrieval-obligation-fixture-v1", entities)
    return DeterministicPlanner.for_test(default_rule_registry(), catalog)


def _fact_bound(store):
    planner = _planner(("doc-a",))
    request = RuntimeRequest(
        question="사업 예산은 얼마인가?",
        document_scope={"mode": "explicit", "doc_ids": ["doc-a"]},
    )
    return bind_fact(
        request=request,
        planning=planner.plan(request),
        store=store,
        planner=planner,
    )


def _compare_bound(store):
    planner = _planner(("doc-a", "doc-b"))
    registry = default_compare_field_registry()
    request = RuntimeRequest(
        question="예산과 수행기간을 비교해줘",
        document_scope={
            "mode": "explicit",
            "doc_ids": ["doc-a", "doc-b"],
        },
        options={"allow_global_fallback": True},
    )
    bound = prepare_compare_slots(
        request=request,
        planning=planner.plan(request),
        store=store,
        planner=planner,
        compare_registry=registry,
    )
    return bound, registry


def _runtime(
    *,
    store,
    dense_log,
    lexical_log,
    dense_mode="valid",
    lexical_mode="valid",
    dense_delay=0.0,
    dense_reentry_module="",
):
    specs = tuple((item.evidence_id, item.doc_id) for item in store.evidence)
    retriever = HybridChildRetriever(
        store,
        _SyntheticLane(
            lane="dense",
            bundle_sha256=store.bundle_sha256,
            candidate_specs=specs,
            call_log_path=str(dense_log),
            mode=dense_mode,
            delay_seconds=dense_delay,
            reentry_module=dense_reentry_module,
        ),
        _SyntheticLane(
            lane="lexical",
            bundle_sha256=store.bundle_sha256,
            candidate_specs=specs,
            call_log_path=str(lexical_log),
            mode=lexical_mode,
        ),
    )
    return HarnessRuntimeBinding.for_test(
        store=store,
        retriever=retriever,
        clock=_clock,
    )


def _calls(path):
    path = Path(path)
    return () if not path.exists() else tuple(path.read_text(encoding="utf-8").splitlines())


class RetrievalObligationTests(unittest.TestCase):
    def setUp(self):
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.tempdir = Path(self._temporary.name)

    def _fact_case(
        self,
        *,
        name,
        chunks_per_doc=3,
        dense_mode="valid",
        lexical_mode="valid",
        dense_delay=0.0,
        dense_reentry_module="",
    ):
        store = _store(doc_ids=("doc-a",), chunks_per_doc=chunks_per_doc)
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
        config = create_harness_execution_config(mode="e1_bounded")
        obligations = issue_fact_retrieval_obligations(
            bound=_fact_bound(store),
            store=store,
            config=config,
            runtime=runtime,
        )
        return store, config, runtime, obligations, dense_log, lexical_log

    def _compare_case(
        self,
        *,
        name,
        dense_mode="valid",
        lexical_mode="valid",
    ):
        store = _store()
        dense_log = self.tempdir / f"{name}-dense.log"
        lexical_log = self.tempdir / f"{name}-lexical.log"
        runtime = _runtime(
            store=store,
            dense_log=dense_log,
            lexical_log=lexical_log,
            dense_mode=dense_mode,
            lexical_mode=lexical_mode,
        )
        config = create_harness_execution_config(mode="e1_bounded")
        bound, _registry = _compare_bound(store)
        obligations = issue_compare_retrieval_obligations(
            bound=bound,
            store=store,
            config=config,
            runtime=runtime,
        )
        return store, config, runtime, bound, obligations

    def test_b3_r1_fact_issues_exactly_one_answer_support_obligation(self):
        store, config, runtime, obligations, dense_log, lexical_log = self._fact_case(
            name="r1"
        )

        self.assertEqual(len(obligations), 1)
        obligation = obligations[0]
        self.assertEqual(obligation.source_kind, "fact")
        self.assertEqual(obligation.obligation_key, "$answer_support")
        self.assertEqual((obligation.ordinal, obligation.obligation_count), (1, 1))
        self.assertEqual(obligation.round_index, 1)
        self.assertEqual(obligation.scope_doc_ids, ("doc-a",))
        self.assertNotIn("query", obligation.to_dict())
        validate_retrieval_obligation(
            obligation=obligation,
            store=store,
            config=config,
            runtime=runtime,
        )
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), ((), ()))

    def test_b3_r2_compare_issues_complete_doc_by_field_matrix(self):
        store, config, runtime, bound, obligations = self._compare_case(name="r2")

        self.assertEqual(
            tuple(item.obligation_key for item in obligations),
            (
                "doc-a.budget",
                "doc-a.duration",
                "doc-b.budget",
                "doc-b.duration",
            ),
        )
        self.assertEqual(
            tuple(item.scope_doc_ids for item in obligations),
            (("doc-a",), ("doc-a",), ("doc-b",), ("doc-b",)),
        )
        self.assertEqual(
            tuple(item.ordinal for item in obligations),
            tuple(range(1, len(bound.plan.required_slots) + 1)),
        )
        self.assertTrue(all(item.obligation_count == 4 for item in obligations))
        for obligation in obligations:
            validate_retrieval_obligation(
                obligation=obligation,
                store=store,
                config=config,
                runtime=runtime,
            )

    def test_b3_r3_compare_budget_uses_quotient_and_ordered_remainder(self):
        _store_value, _config, _runtime_value, bound, obligations = self._compare_case(
            name="r3"
        )

        self.assertEqual(tuple(item.dense_k for item in obligations), (13, 13, 12, 12))
        self.assertEqual(tuple(item.lexical_k for item in obligations), (13, 13, 12, 12))
        self.assertEqual(sum(item.dense_k for item in obligations), bound.plan.dense_k)
        self.assertEqual(sum(item.lexical_k for item in obligations), bound.plan.lexical_k)

    def test_b3_r4_dense_success_is_safe_hashed_store_derived_receipt(self):
        store, config, runtime, obligations, dense_log, lexical_log = self._fact_case(
            name="r4"
        )
        obligation = obligations[0]

        receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )

        self.assertEqual((receipt.stage, receipt.stage_ordinal), ("lane_dense", 1))
        self.assertEqual((receipt.outcome, receipt.error_code), ("applied", "none"))
        self.assertTrue(receipt.call_performed)
        self.assertEqual(receipt.candidate_count, len(receipt.ordered_evidence_ids))
        self.assertTrue(all(anchor.doc_id == "doc-a" for anchor in receipt.ordered_stable_anchors))
        self.assertTrue(all(len(anchor.anchor_sha256) == 64 for anchor in receipt.ordered_stable_anchors))
        serialized = json.dumps(receipt.to_dict(), ensure_ascii=False)
        self.assertNotIn("사업 예산은 얼마인가?", serialized)
        self.assertNotIn("qrels", serialized.lower())
        self.assertNotIn("gold-must-not-leak", serialized)
        validate_lane_search_receipt(
            receipt=receipt,
            obligation=obligation,
            store=store,
            config=config,
            runtime=runtime,
        )
        self.assertEqual(_calls(dense_log), ("dense",))
        self.assertEqual(_calls(lexical_log), ())

    def test_b3_r4a_source_block_join_key_survives_chunk_locator_changes(self):
        store = _store(doc_ids=("doc-a",), chunks_per_doc=1)
        original = store.evidence[0]
        shifted = Evidence(
            original.doc_id,
            original.kind,
            original.text,
            original.parent_id,
            original.source_block_ids,
            Locator(
                page=original.locator.page,
                char_range=(100, 100 + len(original.text)),
            ),
        )

        original_anchor = execution_contracts._stable_anchor(original)
        shifted_anchor = execution_contracts._stable_anchor(shifted)

        self.assertEqual(
            original_anchor.source_block_anchor_sha256s,
            shifted_anchor.source_block_anchor_sha256s,
        )
        self.assertNotEqual(
            original_anchor.locator_identity_sha256,
            shifted_anchor.locator_identity_sha256,
        )
        self.assertNotEqual(
            original_anchor.anchor_sha256,
            shifted_anchor.anchor_sha256,
        )

    def test_b3_r5_empty_lane_is_a_successful_empty_receipt(self):
        store, config, runtime, obligations, dense_log, _lexical_log = self._fact_case(
            name="r5", dense_mode="empty"
        )
        obligation = obligations[0]

        receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )

        self.assertEqual((receipt.outcome, receipt.error_code), ("empty", "none"))
        self.assertEqual((receipt.candidate_count, receipt.ordered_evidence_ids), (0, ()))
        validate_lane_search_receipt(
            receipt=receipt,
            obligation=obligation,
            store=store,
            config=config,
            runtime=runtime,
        )
        self.assertEqual(_calls(dense_log), ("dense",))

    def test_b3_r6_preflight_failure_performs_no_call_and_does_not_consume(self):
        store, config, runtime, obligations, dense_log, _lexical_log = self._fact_case(
            name="r6"
        )
        obligation = obligations[0]
        wrong_config = create_harness_execution_config(mode="e1_bounded")

        with self.assertRaisesRegex(
            ValueError, "retrieval_obligation_config_identity_mismatch"
        ):
            execute_retrieval_lane(
                obligation=obligation,
                lane="dense",
                store=store,
                config=wrong_config,
                runtime=runtime,
            )
        self.assertEqual(_calls(dense_log), ())

        receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        self.assertEqual(receipt.outcome, "applied")
        self.assertEqual(_calls(dense_log), ("dense",))

    def test_b3_r7_dense_provider_error_still_allows_lexical_once(self):
        store, config, runtime, obligations, dense_log, lexical_log = self._fact_case(
            name="r7", dense_mode="provider_error"
        )
        obligation = obligations[0]

        dense_receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        lexical_receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="lexical",
            store=store,
            config=config,
            runtime=runtime,
        )

        self.assertEqual(
            (dense_receipt.outcome, dense_receipt.error_code),
            ("provider_error", "lane_provider_error"),
        )
        self.assertNotIn(
            "private-provider-detail-must-not-leak",
            json.dumps(dense_receipt.to_dict()),
        )
        self.assertEqual(
            (lexical_receipt.outcome, lexical_receipt.stage_ordinal),
            ("applied", 2),
        )
        for receipt in (dense_receipt, lexical_receipt):
            validate_lane_search_receipt(
                receipt=receipt,
                obligation=obligation,
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), (("dense",), ("lexical",)))

    def test_b3_r8_sequential_duplicate_dispatch_is_exactly_once(self):
        store, config, runtime, obligations, dense_log, _lexical_log = self._fact_case(
            name="r8"
        )
        obligation = obligations[0]

        receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        with self.assertRaisesRegex(ValueError, "retrieval_lane_already_consumed"):
            execute_retrieval_lane(
                obligation=obligation,
                lane="dense",
                store=store,
                config=config,
                runtime=runtime,
            )

        self.assertEqual(receipt.outcome, "applied")
        self.assertEqual(_calls(dense_log), ("dense",))

    def test_b3_r9_concurrent_duplicate_dispatch_is_exactly_once(self):
        store, config, runtime, obligations, dense_log, _lexical_log = self._fact_case(
            name="r9", dense_delay=0.05
        )
        obligation = obligations[0]
        barrier = Barrier(3)

        def invoke():
            barrier.wait()
            try:
                return (
                    "receipt",
                    execute_retrieval_lane(
                        obligation=obligation,
                        lane="dense",
                        store=store,
                        config=config,
                        runtime=runtime,
                    ),
                )
            except Exception as exc:
                return ("error", exc)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = (pool.submit(invoke), pool.submit(invoke))
            barrier.wait()
            outcomes = tuple(future.result(timeout=2) for future in futures)

        self.assertEqual(tuple(kind for kind, _value in outcomes).count("receipt"), 1)
        self.assertEqual(tuple(kind for kind, _value in outcomes).count("error"), 1)
        error = next(value for kind, value in outcomes if kind == "error")
        self.assertIs(type(error), ValueError)
        self.assertEqual(str(error), "retrieval_lane_already_consumed")
        receipt = next(value for kind, value in outcomes if kind == "receipt")
        self.assertEqual(receipt.outcome, "applied")
        self.assertEqual(_calls(dense_log), ("dense",))

    def test_b3_r10_reentrant_dispatch_fails_fast_without_deadlock(self):
        module_name = f"_midprojectrag_b3_reentry_{id(self)}"
        store, config, runtime, obligations, dense_log, _lexical_log = self._fact_case(
            name="r10", dense_reentry_module=module_name
        )
        obligation = obligations[0]
        bridge = ModuleType(module_name)
        bridge.invoke = lambda: execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        sys.modules[module_name] = bridge
        result_queue = Queue()

        def outer_call():
            try:
                result_queue.put(
                    (
                        "receipt",
                        execute_retrieval_lane(
                            obligation=obligation,
                            lane="dense",
                            store=store,
                            config=config,
                            runtime=runtime,
                        ),
                    )
                )
            except Exception as exc:
                result_queue.put(("error", exc))

        try:
            worker = Thread(target=outer_call, daemon=True)
            worker.start()
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive(), "reentrant lane dispatch deadlocked")
            try:
                kind, value = result_queue.get_nowait()
            except Empty as exc:
                self.fail(f"reentrant lane dispatch returned no outcome: {exc}")
        finally:
            sys.modules.pop(module_name, None)

        self.assertEqual(kind, "receipt")
        self.assertEqual(value.outcome, "applied")
        self.assertEqual(
            _calls(dense_log),
            ("dense", "reentry:ValueError:retrieval_lane_already_consumed"),
        )
        with self.assertRaisesRegex(ValueError, "retrieval_lane_already_consumed"):
            execute_retrieval_lane(
                obligation=obligation,
                lane="dense",
                store=store,
                config=config,
                runtime=runtime,
            )

    def test_b3_r10a_lexical_cannot_run_before_dense(self):
        store, config, runtime, obligations, dense_log, lexical_log = self._fact_case(
            name="r10a"
        )
        obligation = obligations[0]

        with self.assertRaisesRegex(ValueError, "retrieval_lane_order_violation"):
            execute_retrieval_lane(
                obligation=obligation,
                lane="lexical",
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), ((), ()))
        dense_receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        self.assertEqual(dense_receipt.outcome, "applied")

    def test_b3_r10b_ledger_state_reset_is_detected_before_second_call(self):
        store, config, runtime, obligations, dense_log, _lexical_log = self._fact_case(
            name="r10b"
        )
        obligation = obligations[0]
        execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        authority = execution_contracts._ISSUED_RETRIEVAL_OBLIGATION_AUTHORITIES[
            id(obligation)
        ]
        ledger = authority.ledger
        object.__setattr__(ledger, "_claimed", frozenset())
        object.__setattr__(ledger, "_closed", frozenset())
        object.__setattr__(ledger, "_status", "active")

        with self.assertRaisesRegex(
            ValueError, "retrieval_execution_ledger_drift"
        ):
            execute_retrieval_lane(
                obligation=obligation,
                lane="dense",
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual(_calls(dense_log), ("dense",))

    def test_b3_r10c_generic_core_rejects_a_forged_owner(self):
        store, config, runtime, obligations, dense_log, lexical_log = self._fact_case(
            name="r10c"
        )
        legitimate = execution_contracts._ISSUED_RETRIEVAL_OBLIGATION_AUTHORITIES[
            id(obligations[0])
        ]

        class FakeSource:
            binding_sha256 = "0" * 64

        with self.assertRaisesRegex(
            ValueError, "retrieval_source_owner_identity_mismatch"
        ):
            execution_contracts._issue_retrieval_obligations_from_owner(
                source_kind="fact",
                source=FakeSource(),
                source_projector=legitimate.source_projector,
                source_validator=legitimate.source_validator,
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), ((), ()))

    def test_b3_r10d_dispatch_integrity_error_terminates_without_provider_call(self):
        store, config, runtime, obligations, dense_log, lexical_log = self._fact_case(
            name="r10d"
        )
        obligation = obligations[0]
        original = fusion_module._FUSION_ENTRY_OBJECT_PINS
        try:
            fusion_module._FUSION_ENTRY_OBJECT_PINS = ()
            receipt = execute_retrieval_lane(
                obligation=obligation,
                lane="dense",
                store=store,
                config=config,
                runtime=runtime,
            )
        finally:
            fusion_module._FUSION_ENTRY_OBJECT_PINS = original

        self.assertEqual(
            (receipt.outcome, receipt.error_code, receipt.call_performed),
            ("contract_error", "lane_dispatch_contract_error", False),
        )
        validate_lane_search_receipt(
            receipt=receipt,
            obligation=obligation,
            store=store,
            config=config,
            runtime=runtime,
        )
        with self.assertRaisesRegex(ValueError, "retrieval_execution_terminated"):
            execute_retrieval_lane(
                obligation=obligation,
                lane="lexical",
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), ((), ()))

    def test_b3_r10e_public_owner_entry_rejects_core_monkeypatch(self):
        store, config, runtime, obligations, dense_log, lexical_log = self._fact_case(
            name="r10e"
        )
        legitimate = execution_contracts._ISSUED_RETRIEVAL_OBLIGATION_AUTHORITIES[
            id(obligations[0])
        ]
        original = execution_contracts._issue_retrieval_obligations_from_owner
        called = []

        def forged_core(**_kwargs):
            called.append(True)
            return ()

        try:
            execution_contracts._issue_retrieval_obligations_from_owner = forged_core
            with self.assertRaisesRegex(
                ValueError, "harness_runtime_validation_dependency_drift"
            ):
                issue_fact_retrieval_obligations(
                    bound=legitimate.source,
                    store=store,
                    config=config,
                    runtime=runtime,
                )
        finally:
            execution_contracts._issue_retrieval_obligations_from_owner = original
        self.assertEqual(called, [])
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), ((), ()))

    def test_b3_r10f_compare_lane_order_stops_at_fusion_boundary(self):
        store, config, runtime, _bound, obligations = self._compare_case(
            name="r10f"
        )
        first, second, _third, last = obligations
        dense_log = self.tempdir / "r10f-dense.log"
        lexical_log = self.tempdir / "r10f-lexical.log"

        with self.assertRaisesRegex(
            ValueError, "retrieval_lane_order_violation"
        ):
            execute_retrieval_lane(
                obligation=last,
                lane="dense",
                store=store,
                config=config,
                runtime=runtime,
            )
        first_dense = execute_retrieval_lane(
            obligation=first,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        with self.assertRaisesRegex(
            ValueError, "retrieval_lane_order_violation"
        ):
            execute_retrieval_lane(
                obligation=second,
                lane="dense",
                store=store,
                config=config,
                runtime=runtime,
            )
        first_lexical = execute_retrieval_lane(
            obligation=first,
            lane="lexical",
            store=store,
            config=config,
            runtime=runtime,
        )
        with self.assertRaisesRegex(
            ValueError, "fusion_execution_order_violation"
        ):
            execute_retrieval_lane(
                obligation=second,
                lane="dense",
                store=store,
                config=config,
                runtime=runtime,
            )

        self.assertEqual(
            (first_dense.outcome, first_lexical.outcome),
            ("applied", "applied"),
        )
        self.assertEqual(_calls(dense_log), ("dense",))
        self.assertEqual(_calls(lexical_log), ("lexical",))

    def test_b3_r10g_owner_code_drift_fails_before_forged_code_executes(self):
        store = _store(doc_ids=("doc-a",))
        dense_log = self.tempdir / "r10g-dense.log"
        lexical_log = self.tempdir / "r10g-lexical.log"
        runtime = _runtime(
            store=store,
            dense_log=dense_log,
            lexical_log=lexical_log,
        )
        config = create_harness_execution_config(mode="e1_bounded")
        bound = _fact_bound(store)
        validator = fact_binding_module.validate_bound_fact
        original_code = validator.__code__

        def forged_validator(*, bound, store):
            raise RuntimeError("OWNER_CODE_EXECUTED")

        try:
            validator.__code__ = forged_validator.__code__
            with self.assertRaisesRegex(
                ValueError, "retrieval_source_owner_global_drift"
            ):
                issue_fact_retrieval_obligations(
                    bound=bound,
                    store=store,
                    config=config,
                    runtime=runtime,
                )
        finally:
            validator.__code__ = original_code

        self.assertEqual((_calls(dense_log), _calls(lexical_log)), ((), ()))

    def test_b3_r10h_post_call_contract_error_records_actual_call_and_terminates(self):
        store, config, runtime, obligations, dense_log, lexical_log = self._fact_case(
            name="r10h", dense_mode="post_call_contract"
        )
        obligation = obligations[0]

        receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )

        self.assertEqual(
            (receipt.outcome, receipt.error_code, receipt.call_performed),
            ("contract_error", "lane_post_call_contract_error", True),
        )
        self.assertNotIn(
            "private-post-call-detail-must-not-leak",
            json.dumps(receipt.to_dict()),
        )
        with self.assertRaisesRegex(ValueError, "retrieval_execution_terminated"):
            execute_retrieval_lane(
                obligation=obligation,
                lane="lexical",
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), (("dense",), ()))

    def test_b3_r10i_untyped_synthetic_contract_error_is_not_provider_error(self):
        store, config, runtime, obligations, dense_log, lexical_log = self._fact_case(
            name="r10i", dense_mode="pre_call_contract"
        )
        obligation = obligations[0]

        receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )

        self.assertEqual(
            (receipt.outcome, receipt.error_code, receipt.call_performed),
            ("contract_error", "lane_dispatch_contract_error", False),
        )
        with self.assertRaisesRegex(ValueError, "retrieval_execution_terminated"):
            execute_retrieval_lane(
                obligation=obligation,
                lane="lexical",
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), ((), ()))

    def test_b3_r10j_owner_referenced_global_drift_fails_before_execution(self):
        store = _store(doc_ids=("doc-a",))
        dense_log = self.tempdir / "r10j-dense.log"
        lexical_log = self.tempdir / "r10j-lexical.log"
        runtime = _runtime(
            store=store,
            dense_log=dense_log,
            lexical_log=lexical_log,
        )
        config = create_harness_execution_config(mode="e1_bounded")
        bound = _fact_bound(store)
        original = fact_binding_module._require_bound_fact_authority

        def forged_global(*_args, **_kwargs):
            raise RuntimeError("OWNER_GLOBAL_EXECUTED")

        try:
            fact_binding_module._require_bound_fact_authority = forged_global
            with self.assertRaisesRegex(
                ValueError, "retrieval_source_owner_global_drift"
            ):
                issue_fact_retrieval_obligations(
                    bound=bound,
                    store=store,
                    config=config,
                    runtime=runtime,
                )
        finally:
            fact_binding_module._require_bound_fact_authority = original

        self.assertEqual((_calls(dense_log), _calls(lexical_log)), ((), ()))

    def test_b3_r10k_provider_error_rescue_terminates_before_next_obligation(self):
        store, config, runtime, _bound, obligations = self._compare_case(
            name="r10k-dense",
            dense_mode="provider_error",
        )
        first, second = obligations[:2]
        dense_receipt = execute_retrieval_lane(
            obligation=first,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        lexical_receipt = execute_retrieval_lane(
            obligation=first,
            lane="lexical",
            store=store,
            config=config,
            runtime=runtime,
        )
        with self.assertRaisesRegex(ValueError, "retrieval_execution_terminated"):
            execute_retrieval_lane(
                obligation=second,
                lane="dense",
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual(
            (dense_receipt.outcome, lexical_receipt.outcome),
            ("provider_error", "applied"),
        )
        self.assertEqual(_calls(self.tempdir / "r10k-dense-dense.log"), ("dense",))
        self.assertEqual(
            _calls(self.tempdir / "r10k-dense-lexical.log"),
            ("lexical",),
        )

        store, config, runtime, _bound, obligations = self._compare_case(
            name="r10k-lexical",
            lexical_mode="provider_error",
        )
        first, second = obligations[:2]
        execute_retrieval_lane(
            obligation=first,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        lexical_receipt = execute_retrieval_lane(
            obligation=first,
            lane="lexical",
            store=store,
            config=config,
            runtime=runtime,
        )
        with self.assertRaisesRegex(ValueError, "retrieval_execution_terminated"):
            execute_retrieval_lane(
                obligation=second,
                lane="dense",
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual(lexical_receipt.outcome, "provider_error")
        self.assertEqual(
            _calls(self.tempdir / "r10k-lexical-dense.log"),
            ("dense",),
        )
        self.assertEqual(
            _calls(self.tempdir / "r10k-lexical-lexical.log"),
            ("lexical",),
        )

    def test_b3_r10l_reissue_reuses_the_same_consumption_authority(self):
        store, config, runtime, obligations, dense_log, _lexical_log = self._fact_case(
            name="r10l"
        )
        authority = execution_contracts._ISSUED_RETRIEVAL_OBLIGATION_AUTHORITIES[
            id(obligations[0])
        ]

        public_again = issue_fact_retrieval_obligations(
            bound=authority.source,
            store=store,
            config=config,
            runtime=runtime,
        )
        private_again = execution_contracts._issue_retrieval_obligations_from_owner(
            source_kind="fact",
            source=authority.source,
            source_projector=authority.source_projector,
            source_validator=authority.source_validator,
            store=store,
            config=config,
            runtime=runtime,
        )

        self.assertEqual(len(public_again), len(obligations))
        self.assertEqual(len(private_again), len(obligations))
        self.assertTrue(
            all(left is right for left, right in zip(public_again, obligations))
        )
        self.assertTrue(
            all(left is right for left, right in zip(private_again, obligations))
        )
        receipt = execute_retrieval_lane(
            obligation=obligations[0],
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        self.assertEqual(receipt.outcome, "applied")
        for reissued in (public_again, private_again):
            with self.assertRaisesRegex(
                ValueError, "retrieval_lane_already_consumed"
            ):
                execute_retrieval_lane(
                    obligation=reissued[0],
                    lane="dense",
                    store=store,
                    config=config,
                    runtime=runtime,
                )
        self.assertEqual(_calls(dense_log), ("dense",))

    def test_b3_r10m_complete_ledger_rollback_is_rejected_by_external_authority(self):
        store, config, runtime, obligations, dense_log, _lexical_log = self._fact_case(
            name="r10m"
        )
        obligation = obligations[0]
        execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        authority = execution_contracts._ISSUED_RETRIEVAL_OBLIGATION_AUTHORITIES[
            id(obligation)
        ]
        ledger = authority.ledger
        object.__setattr__(ledger, "_claimed", frozenset())
        object.__setattr__(ledger, "_closed", frozenset())
        object.__setattr__(ledger, "_dense_provider_failed", frozenset())
        object.__setattr__(ledger, "_status", "active")
        object.__setattr__(ledger, "_revision", 0)
        object.__setattr__(ledger, "_previous_state_sha256", "0" * 64)
        object.__setattr__(
            ledger,
            "_state_sha256",
            execution_contracts._canonical_sha256(ledger._state_payload()),
        )

        with self.assertRaisesRegex(
            ValueError, "retrieval_execution_ledger_authority_drift"
        ):
            execute_retrieval_lane(
                obligation=obligation,
                lane="dense",
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual(_calls(dense_log), ("dense",))

    def test_b3_r10n_visible_authority_cannot_be_rolled_back_with_the_ledger(self):
        store, config, runtime, obligations, dense_log, _lexical_log = self._fact_case(
            name="r10n"
        )
        obligation = obligations[0]
        execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        obligation_authority = (
            execution_contracts._ISSUED_RETRIEVAL_OBLIGATION_AUTHORITIES[
                id(obligation)
            ]
        )
        ledger = obligation_authority.ledger
        object.__setattr__(ledger, "_claimed", frozenset())
        object.__setattr__(ledger, "_closed", frozenset())
        object.__setattr__(ledger, "_dense_provider_failed", frozenset())
        object.__setattr__(ledger, "_status", "active")
        object.__setattr__(ledger, "_revision", 0)
        object.__setattr__(ledger, "_previous_state_sha256", "0" * 64)
        rolled_back_sha256 = execution_contracts._canonical_sha256(
            ledger._state_payload()
        )
        object.__setattr__(ledger, "_state_sha256", rolled_back_sha256)
        visible_authority = (
            execution_contracts._ISSUED_RETRIEVAL_LEDGER_AUTHORITIES[id(ledger)]
        )
        object.__setattr__(
            visible_authority, "state_sha256", rolled_back_sha256
        )
        object.__setattr__(visible_authority, "revision", 0)

        with self.assertRaisesRegex(
            ValueError, "retrieval_execution_ledger_authority_drift"
        ):
            execute_retrieval_lane(
                obligation=obligation,
                lane="dense",
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual(_calls(dense_log), ("dense",))

    def test_b3_r10o_visible_issuance_registry_deletion_fails_closed(self):
        store, config, runtime, obligations, dense_log, _lexical_log = self._fact_case(
            name="r10o"
        )
        authority = execution_contracts._ISSUED_RETRIEVAL_OBLIGATION_AUTHORITIES[
            id(obligations[0])
        ]
        key = execution_contracts._issuance_key(
            source_kind="fact",
            source=authority.source,
            store=store,
            config=config,
            runtime=runtime,
        )
        visible = execution_contracts._ISSUED_RETRIEVAL_ISSUANCE_AUTHORITIES
        removed = visible.pop(key)
        try:
            with self.assertRaisesRegex(
                ValueError, "retrieval_issuance_authority_drift"
            ):
                issue_fact_retrieval_obligations(
                    bound=authority.source,
                    store=store,
                    config=config,
                    runtime=runtime,
                )
        finally:
            visible[key] = removed
        self.assertEqual(_calls(dense_log), ())

    def test_b3_r10p_new_owner_global_shadow_is_rejected_before_execution(self):
        store = _store(doc_ids=("doc-a",))
        dense_log = self.tempdir / "r10p-dense.log"
        lexical_log = self.tempdir / "r10p-lexical.log"
        runtime = _runtime(
            store=store,
            dense_log=dense_log,
            lexical_log=lexical_log,
        )
        config = create_harness_execution_config(mode="e1_bounded")
        bound = _fact_bound(store)
        calls = []

        def forged_type(*args, **kwargs):
            calls.append((args, kwargs))
            return type(*args, **kwargs)

        try:
            fact_binding_module.type = forged_type
            with self.assertRaisesRegex(
                ValueError, "retrieval_source_owner_global_drift"
            ):
                issue_fact_retrieval_obligations(
                    bound=bound,
                    store=store,
                    config=config,
                    runtime=runtime,
                )
        finally:
            del fact_binding_module.type

        self.assertEqual(calls, [])
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), ((), ()))

    def test_b3_r10q_owner_class_method_code_drift_is_rejected_before_execution(self):
        store = _store(doc_ids=("doc-a",))
        dense_log = self.tempdir / "r10q-dense.log"
        lexical_log = self.tempdir / "r10q-lexical.log"
        runtime = _runtime(
            store=store,
            dense_log=dense_log,
            lexical_log=lexical_log,
        )
        config = create_harness_execution_config(mode="e1_bounded")
        bound = _fact_bound(store)
        original_code = fact_binding_module.BoundFact.to_dict.__code__

        def forged_to_dict(self):
            raise RuntimeError("OWNER_CLASS_METHOD_EXECUTED")

        try:
            fact_binding_module.BoundFact.to_dict.__code__ = forged_to_dict.__code__
            with self.assertRaisesRegex(
                ValueError, "retrieval_source_owner_class_drift"
            ):
                issue_fact_retrieval_obligations(
                    bound=bound,
                    store=store,
                    config=config,
                    runtime=runtime,
                )
        finally:
            fact_binding_module.BoundFact.to_dict.__code__ = original_code

        self.assertEqual((_calls(dense_log), _calls(lexical_log)), ((), ()))

    def test_b3_r10r_issuance_authorities_evict_after_request_graph_dies(self):
        gc.collect()
        gc.collect()
        baseline = (
            len(execution_contracts._ISSUED_RETRIEVAL_ISSUANCE_AUTHORITIES),
            len(execution_contracts._ISSUED_RETRIEVAL_OBLIGATION_AUTHORITIES),
            len(execution_contracts._ISSUED_RETRIEVAL_LEDGER_AUTHORITIES),
        )
        store = _store(doc_ids=("doc-a",))
        dense_log = self.tempdir / "r10r-dense.log"
        lexical_log = self.tempdir / "r10r-lexical.log"
        runtime = _runtime(
            store=store,
            dense_log=dense_log,
            lexical_log=lexical_log,
        )
        config = create_harness_execution_config(mode="e1_bounded")
        bound = _fact_bound(store)
        obligations = issue_fact_retrieval_obligations(
            bound=bound,
            store=store,
            config=config,
            runtime=runtime,
        )
        references = tuple(
            weakref.ref(value)
            for value in (
                store,
                runtime,
                config,
                bound,
                obligations[0],
            )
        )

        del obligations, bound, config, runtime, store
        gc.collect()
        gc.collect()

        self.assertTrue(all(reference() is None for reference in references))
        self.assertEqual(
            (
                len(execution_contracts._ISSUED_RETRIEVAL_ISSUANCE_AUTHORITIES),
                len(execution_contracts._ISSUED_RETRIEVAL_OBLIGATION_AUTHORITIES),
                len(execution_contracts._ISSUED_RETRIEVAL_LEDGER_AUTHORITIES),
            ),
            baseline,
        )

    def test_b3_r10s_obligation_authority_ledger_swap_fails_closed(self):
        store, config, runtime, obligations, dense_log, _lexical_log = self._fact_case(
            name="r10s"
        )
        obligation = obligations[0]
        execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        authority = execution_contracts._ISSUED_RETRIEVAL_OBLIGATION_AUTHORITIES[
            id(obligation)
        ]
        replacement = execution_contracts._RetrievalExecutionLedger._create(
            (obligation.obligation_sha256,),
            _token=execution_contracts._RETRIEVAL_LEDGER_TOKEN,
        )
        object.__setattr__(authority, "ledger", replacement)

        with self.assertRaisesRegex(
            ValueError, "retrieval_obligation_runtime_authority_drift"
        ):
            execute_retrieval_lane(
                obligation=obligation,
                lane="dense",
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual(_calls(dense_log), ("dense",))

    def test_b3_r10t_receipt_authority_and_payload_tamper_fails_closed(self):
        store, config, runtime, obligations, _dense_log, _lexical_log = self._fact_case(
            name="r10t"
        )
        obligation = obligations[0]
        receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        object.__setattr__(receipt, "call_performed", False)
        checkpoint = {
            key: value
            for key, value in execution_contracts._lane_search_receipt_payload(
                receipt,
                include_hash=False,
            ).items()
            if key not in {"error_code", "result_sha256", "checkpoint_sha256"}
        }
        object.__setattr__(
            receipt,
            "checkpoint_sha256",
            execution_contracts._canonical_sha256(checkpoint),
        )
        object.__setattr__(
            receipt,
            "receipt_sha256",
            execution_contracts._canonical_sha256(
                execution_contracts._lane_search_receipt_payload(
                    receipt,
                    include_hash=False,
                )
            ),
        )
        authority = execution_contracts._ISSUED_LANE_SEARCH_RECEIPT_AUTHORITIES[
            id(receipt)
        ]
        object.__setattr__(
            authority,
            "issued_payload_sha256",
            receipt.receipt_sha256,
        )

        with self.assertRaisesRegex(
            ValueError, "lane_search_receipt_runtime_authority_drift"
        ):
            validate_lane_search_receipt(
                receipt=receipt,
                obligation=obligation,
                store=store,
                config=config,
                runtime=runtime,
            )

    def test_b3_r10u_call_performed_is_bound_to_the_outcome(self):
        store, config, runtime, obligations, _dense_log, _lexical_log = self._fact_case(
            name="r10u"
        )
        receipt = execute_retrieval_lane(
            obligation=obligations[0],
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        object.__setattr__(receipt, "call_performed", False)

        with self.assertRaisesRegex(
            ValueError, "lane_search_receipt_call_performed_mismatch"
        ):
            execution_contracts._validate_lane_search_receipt_payload(receipt)

    def test_b3_r10v_receipt_mint_requires_a_real_one_time_ledger_close(self):
        store, config, runtime, obligations, dense_log, _lexical_log = self._fact_case(
            name="r10v"
        )
        obligation = obligations[0]
        authority = execution_contracts._ISSUED_RETRIEVAL_OBLIGATION_AUTHORITIES[
            id(obligation)
        ]
        forged_permit = execution_contracts._LaneClosurePermit(
            ledger=authority.ledger,
            obligation_sha256=obligation.obligation_sha256,
            lane="dense",
            outcome="contract_error",
            transition_sha256="f" * 64,
            revision=0,
        )

        with self.assertRaisesRegex(
            ValueError, "retrieval_lane_transition_authority_required"
        ):
            execution_contracts._mint_lane_search_receipt(
                obligation=obligation,
                lane="dense",
                store=store,
                config=config,
                runtime=runtime,
                result=None,
                evidence_ids=(),
                anchors=(),
                outcome="contract_error",
                error_code="lane_dispatch_contract_error",
                result_sha256="f" * 64,
                call_performed=False,
                transition_permit=forged_permit,
            )

        receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        self.assertEqual(receipt.outcome, "applied")
        self.assertEqual(_calls(dense_log), ("dense",))

    def test_b3_r10w_ledger_transitions_require_the_public_lane_executor(self):
        store, config, runtime, obligations, dense_log, _lexical_log = self._fact_case(
            name="r10w"
        )
        obligation = obligations[0]
        authority = execution_contracts._ISSUED_RETRIEVAL_OBLIGATION_AUTHORITIES[
            id(obligation)
        ]
        ledger = authority.ledger

        with self.assertRaisesRegex(
            ValueError, "retrieval_lane_executor_authority_required"
        ):
            ledger._claim(obligation.obligation_sha256, "dense")
        with self.assertRaisesRegex(
            ValueError, "retrieval_lane_executor_authority_required"
        ):
            ledger._close(
                obligation.obligation_sha256,
                "dense",
                outcome="contract_error",
            )
        self.assertEqual(_calls(dense_log), ())

        receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        self.assertEqual(receipt.outcome, "applied")
        self.assertEqual(_calls(dense_log), ("dense",))

    def test_b3_r10x_ledger_executor_guard_ignores_module_global_spoofs(self):
        store, config, runtime, obligations, dense_log, _lexical_log = self._fact_case(
            name="r10x"
        )
        obligation = obligations[0]
        authority = execution_contracts._ISSUED_RETRIEVAL_OBLIGATION_AUTHORITIES[
            id(obligation)
        ]
        ledger = authority.ledger
        issued_frame_getter = execution_contracts._GET_FRAME
        issued_executor_code = (
            execution_contracts._ISSUED_EXECUTE_RETRIEVAL_LANE_CODE
        )
        forged_frame = type(
            "_ForgedFrame",
            (),
            {"f_code": issued_executor_code},
        )()

        try:
            execution_contracts._GET_FRAME = lambda _depth: forged_frame
            execution_contracts._ISSUED_EXECUTE_RETRIEVAL_LANE_CODE = (
                self.test_b3_r10x_ledger_executor_guard_ignores_module_global_spoofs.__code__
            )
            with self.assertRaisesRegex(
                ValueError, "retrieval_lane_executor_authority_required"
            ):
                ledger._claim(obligation.obligation_sha256, "dense")
            with self.assertRaisesRegex(
                ValueError, "retrieval_lane_executor_authority_required"
            ):
                ledger._close(
                    obligation.obligation_sha256,
                    "dense",
                    outcome="contract_error",
                )
        finally:
            execution_contracts._GET_FRAME = issued_frame_getter
            execution_contracts._ISSUED_EXECUTE_RETRIEVAL_LANE_CODE = (
                issued_executor_code
            )

        self.assertEqual(_calls(dense_log), ())
        receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        self.assertEqual(receipt.outcome, "applied")
        self.assertEqual(_calls(dense_log), ("dense",))

    def test_b3_r10y_executor_code_clone_cannot_use_copied_globals(self):
        store, config, runtime, obligations, dense_log, _lexical_log = self._fact_case(
            name="r10y"
        )
        obligation = obligations[0]
        cloned_globals = dict(execute_retrieval_lane.__globals__)
        forged_calls = []

        def forged_lane_dispatch(*_args, **_kwargs):
            forged_calls.append("called")
            from midprojectrag.retrieval import SearchResult

            return SearchResult((), {"lane": "dense"})

        def forged_dependency_checker(
            _module_globals=None,
            _function_pins=None,
            _object_pins=None,
            _module_attribute_pins=None,
            _class_pins=None,
            _authority_fields=None,
        ):
            return None

        forged_dependency_checker.__defaults__ = (
            cloned_globals,
            (),
            (),
            (),
            (),
            (),
        )
        cloned_globals["_ISSUED_HYBRID_SEARCH_LANE"] = forged_lane_dispatch
        cloned_globals["_ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER"] = (
            forged_dependency_checker
        )
        cloned_globals["_PINNED_RUNTIME_GATE_DEPENDENCY_CHECKER_CODE"] = (
            forged_dependency_checker.__code__
        )
        cloned_globals["_ISSUED_RUNTIME_GATE_DEPENDENCY_DEFAULTS"] = (
            forged_dependency_checker.__defaults__
        )
        cloned_executor = FunctionType(
            execute_retrieval_lane.__code__,
            cloned_globals,
            name=execute_retrieval_lane.__name__,
            argdefs=execute_retrieval_lane.__defaults__,
            closure=execute_retrieval_lane.__closure__,
        )
        cloned_executor.__kwdefaults__ = {
            "_dependency_checker": forged_dependency_checker,
            "_dependency_checker_code": forged_dependency_checker.__code__,
        }

        with self.assertRaisesRegex(
            ValueError, "retrieval_lane_executor_authority_required"
        ):
            cloned_executor(
                obligation=obligation,
                lane="dense",
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual(forged_calls, [])
        self.assertEqual(_calls(dense_log), ())

        receipt = execute_retrieval_lane(
            obligation=obligation,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        self.assertEqual(receipt.outcome, "applied")
        self.assertEqual(_calls(dense_log), ("dense",))

    def test_b3_r11_malformed_and_over_limit_results_close_as_contract_errors(self):
        cases = (("malformed", 3), ("over_limit", 31))
        for mode, chunks_per_doc in cases:
            with self.subTest(mode=mode):
                store, config, runtime, obligations, dense_log, _lexical_log = self._fact_case(
                    name=f"r11-{mode}",
                    chunks_per_doc=chunks_per_doc,
                    dense_mode=mode,
                )
                obligation = obligations[0]

                receipt = execute_retrieval_lane(
                    obligation=obligation,
                    lane="dense",
                    store=store,
                    config=config,
                    runtime=runtime,
                )

                self.assertEqual(
                    (receipt.outcome, receipt.error_code),
                    ("contract_error", "lane_result_contract_error"),
                )
                self.assertEqual((receipt.candidate_count, receipt.ordered_evidence_ids), (0, ()))
                validate_lane_search_receipt(
                    receipt=receipt,
                    obligation=obligation,
                    store=store,
                    config=config,
                    runtime=runtime,
                )
                with self.assertRaisesRegex(
                    ValueError, "retrieval_execution_terminated"
                ):
                    execute_retrieval_lane(
                        obligation=obligation,
                        lane="dense",
                        store=store,
                        config=config,
                        runtime=runtime,
                    )
                with self.assertRaisesRegex(
                    ValueError, "retrieval_execution_terminated"
                ):
                    execute_retrieval_lane(
                        obligation=obligation,
                        lane="lexical",
                        store=store,
                        config=config,
                        runtime=runtime,
                    )
                self.assertEqual(_calls(dense_log), ("dense",))


if __name__ == "__main__":
    unittest.main()
