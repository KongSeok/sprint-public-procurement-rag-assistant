"""EH2.6.c3.2 rerank and derived-semantic acceptance tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import gc
import inspect
import json
import copy
import pickle
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest

import midprojectrag.orchestration as orchestration
import midprojectrag.orchestration.execution_contracts as execution_contracts
from midprojectrag.orchestration import (
    HarnessRuntimeBinding,
    RerankReceipt,
    SemanticVerificationReceipt,
    create_harness_execution_config,
    execute_retrieval_fusion,
    execute_retrieval_lane,
    issue_bridge_context_receipts,
    issue_derived_semantic_verification_obligation,
    issue_fact_retrieval_obligations,
    issue_fact_semantic_verification_obligation,
    issue_parent_context_receipts,
    validate_rerank_receipt,
    validate_semantic_verification_obligation,
)
from midprojectrag.retrieval.fusion import HybridChildRetriever

from tests.test_action_effect_receipts import _clone_slots, _context_store
from tests.test_retrieval_obligations import _SyntheticLane, _calls, _clock, _fact_bound


class _Reranker:
    def __init__(self, *, ordered_indexes, call_log_path, request_log_path, mode="valid"):
        self.ordered_indexes = tuple(ordered_indexes)
        self.call_log_path = str(call_log_path)
        self.request_log_path = str(request_log_path)
        self.mode = mode

    def rerank(self, request):
        with open(self.call_log_path, "a", encoding="utf-8") as handle:
            handle.write("rerank\n")
        with open(self.request_log_path, "w", encoding="utf-8") as handle:
            handle.write(
                "\t".join(
                    (
                        request.query,
                        str(hasattr(request, "__dict__")),
                        str(hasattr(request, "to_dict")),
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
                            str(hasattr(item, "stable_anchor")),
                        )
                    )
                    + "\n"
                )
        if self.mode == "provider_error":
            raise RuntimeError("private-provider-secret-must-not-leak")
        if self.mode == "mutating_provider_error":
            self.ordered_indexes = (0,)
            raise RuntimeError("private-mutating-provider-secret-must-not-leak")
        malformed = {
            "extra": {"schema_version": "1.0", "ordered_indexes": [0], "private": "raw-secret"},
            "version": {"schema_version": "9.9", "ordered_indexes": [0]},
            "tuple": {"schema_version": "1.0", "ordered_indexes": (0,)},
            "bool": {"schema_version": "1.0", "ordered_indexes": [True]},
            "negative": {"schema_version": "1.0", "ordered_indexes": [-1]},
            "duplicate": {"schema_version": "1.0", "ordered_indexes": [0, 0]},
            "empty": {"schema_version": "1.0", "ordered_indexes": []},
            "out_of_range": {"schema_version": "1.0", "ordered_indexes": [999]},
        }
        if self.mode in malformed:
            return malformed[self.mode]
        return {
            "schema_version": "1.0",
            "ordered_indexes": list(self.ordered_indexes),
        }


class _Verifier:
    def verify(self, request):
        return {
            "schema_version": "1.0",
            "disposition": "supported",
            "support_indexes": [0],
            "values": [],
        }


class _AuxVerifier:
    def __init__(self, *, call_log_path, request_log_path, support_indexes=(0,)):
        self.call_log_path = str(call_log_path)
        self.request_log_path = str(request_log_path)
        self.support_indexes = tuple(support_indexes)

    def verify(self, request):
        with open(self.call_log_path, "a", encoding="utf-8") as handle:
            handle.write("verify\n")
        with open(self.request_log_path, "w", encoding="utf-8") as handle:
            for item in request.evidence:
                handle.write(
                    "\t".join(
                        (
                            "evidence",
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
            for item in request.auxiliary_parent_context:
                handle.write(
                    "\t".join(
                        (
                            "parent",
                            item.parent_id,
                            item.parent_kind,
                            item.doc_id,
                            item.content,
                            str(hasattr(item, "index")),
                            str(hasattr(item, "evidence_id")),
                        )
                    )
                    + "\n"
                )
        return {
            "schema_version": "1.0",
            "disposition": "supported",
            "support_indexes": list(self.support_indexes),
            "values": [],
        }


class RerankDerivedSemanticAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.tempdir = Path(self._temporary.name)
        self._roots = {}

    def _case(self, *, name, ordered_indexes=(4, 0, 3, 1), unavailable=False, reranker_mode="valid", verifier=None):
        store = _context_store()
        seeds = tuple(item for item in store.evidence if item.kind == "text")
        specs = tuple((item.evidence_id, item.doc_id) for item in reversed(seeds))
        dense_log = self.tempdir / f"{name}-dense.log"
        lexical_log = self.tempdir / f"{name}-lexical.log"
        call_log = self.tempdir / f"{name}-rerank.log"
        request_log = self.tempdir / f"{name}-request.json"
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
        reranker = None if unavailable else _Reranker(
            ordered_indexes=ordered_indexes,
            call_log_path=call_log,
            request_log_path=request_log,
            mode=reranker_mode,
        )
        runtime = HarnessRuntimeBinding.for_test(
            store=store,
            retriever=retriever,
            verifier=_Verifier() if verifier is None else verifier,
            reranker=reranker,
            clock=_clock,
        )
        config = create_harness_execution_config(mode="e1_bounded")
        bound = _fact_bound(store)
        retrieval = issue_fact_retrieval_obligations(
            bound=bound, store=store, config=config, runtime=runtime
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
        parents = issue_parent_context_receipts(
            obligation=semantic, store=store, config=config, runtime=runtime
        )
        bridges = issue_bridge_context_receipts(
            obligation=semantic, store=store, config=config, runtime=runtime
        )
        self._roots[name] = (bound, retrieval, fusion)
        return {
            "store": store,
            "config": config,
            "runtime": runtime,
            "semantic": semantic,
            "parents": parents,
            "bridges": bridges,
            "reranker": reranker,
            "call_log": call_log,
            "request_log": request_log,
        }

    @staticmethod
    def _input(case):
        ids = list(case["semantic"].candidate_evidence_ids)
        roles = ["candidate"] * len(ids)
        for receipt in case["bridges"]:
            for evidence_id in receipt.linked_evidence_ids:
                if evidence_id not in ids:
                    ids.append(evidence_id)
                    roles.append("bridge")
        return tuple(ids), tuple(roles)

    @staticmethod
    def _execute(case):
        return execution_contracts.execute_semantic_rerank(
            obligation=case["semantic"],
            parent_receipts=case["parents"],
            bridge_receipts=case["bridges"],
            store=case["store"],
            config=case["config"],
            runtime=case["runtime"],
        )

    def test_public_surface_is_closed_and_executor_is_module_only(self):
        self.assertIs(orchestration.RerankReceipt, RerankReceipt)
        self.assertFalse(hasattr(orchestration, "execute_semantic_rerank"))
        with self.assertRaisesRegex(TypeError, "factory_required"):
            RerankReceipt()
        self.assertFalse(hasattr(RerankReceipt, "from_dict"))
        for function in (
            execution_contracts.execute_semantic_rerank,
            validate_rerank_receipt,
            issue_derived_semantic_verification_obligation,
        ):
            parameters = inspect.signature(function).parameters
            self.assertTrue({"obligation", "parent_receipts", "bridge_receipts", "store", "config", "runtime"} <= set(parameters))
            self.assertFalse(any(item.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD} for item in parameters.values()))

    def test_applied_rerank_is_idless_exact_once_and_preserves_global_role_order(self):
        case = self._case(name="applied")
        input_ids, input_roles = self._input(case)
        receipt = self._execute(case)
        expected_indexes = (4, 0, 3, 1)
        expected_ids = tuple(input_ids[index] for index in expected_indexes)
        expected_roles = tuple(input_roles[index] for index in expected_indexes)

        self.assertIs(type(receipt), RerankReceipt)
        self.assertEqual((receipt.outcome, receipt.call_performed, receipt.error_code), ("applied", True, "none"))
        self.assertEqual(receipt.input_evidence_ids, input_ids)
        self.assertEqual(receipt.ordered_evidence_ids, expected_ids)
        self.assertEqual(receipt.candidate_evidence_ids, tuple(item for item, role in zip(expected_ids, expected_roles) if role == "candidate"))
        self.assertEqual(receipt.bridge_evidence_ids, tuple(item for item, role in zip(expected_ids, expected_roles) if role == "bridge"))
        self.assertEqual((receipt.rerank_k, receipt.final_evidence_budget), (40, 6))
        self.assertEqual((receipt.input_count, receipt.effective_output_count), (len(input_ids), len(expected_ids)))
        self.assertEqual(receipt.input_evidence_roles, input_roles)
        self.assertEqual(receipt.semantic_obligation_sha256, case["semantic"].obligation_sha256)
        self.assertEqual(receipt.parent_context_receipt_sha256s, tuple(item.receipt_sha256 for item in case["parents"]))
        self.assertEqual(receipt.bridge_context_receipt_sha256s, tuple(item.receipt_sha256 for item in case["bridges"]))
        self.assertEqual(receipt.owner_plan_sha256, self._roots["applied"][0].trace.effective_plan_sha256)
        self.assertEqual(receipt.evidence_store_sha256, case["store"].bundle_sha256)
        self.assertEqual(receipt.execution_config_sha256, case["config"].config_sha256)
        self.assertEqual(receipt.runtime_binding_sha256, case["runtime"].binding_sha256)
        self.assertEqual(receipt.reranker_id, case["runtime"].reranker_id)
        for value in (receipt.prerequisite_sha256, receipt.reranker_implementation_sha256, receipt.reranker_config_sha256, receipt.result_sha256, receipt.receipt_sha256):
            self.assertRegex(value, r"^[0-9a-f]{64}$")
        self.assertEqual(_calls(case["call_log"]), ("rerank",))
        lines = case["request_log"].read_text(encoding="utf-8").splitlines()
        header = lines[0].split("\t")
        evidence = tuple(line.split("\t") for line in lines[1:])
        self.assertEqual(tuple(int(item[0]) for item in evidence), tuple(range(len(input_ids))))
        self.assertEqual(tuple(item[1] for item in evidence), input_roles)
        self.assertTrue(all(item[5:] == ["False", "False"] for item in evidence))
        self.assertEqual(header[1:], ["False", "False"])
        validate_rerank_receipt(
            receipt=receipt,
            obligation=case["semantic"],
            parent_receipts=case["parents"],
            bridge_receipts=case["bridges"],
            store=case["store"],
            config=case["config"],
            runtime=case["runtime"],
        )
        for operation in (copy.copy, copy.deepcopy, pickle.dumps):
            with self.assertRaisesRegex(TypeError, "not_serializable"):
                operation(receipt)

    def test_unavailable_is_zero_call_identity_prefix_and_can_issue_derived(self):
        case = self._case(name="unavailable", unavailable=True)
        input_ids, _roles = self._input(case)
        receipt = self._execute(case)
        self.assertEqual((receipt.outcome, receipt.call_performed, receipt.error_code), ("skipped_unavailable", False, "reranker_unavailable"))
        self.assertEqual(receipt.ordered_evidence_ids, input_ids[: min(40, len(input_ids))])
        self.assertFalse(case["call_log"].exists())
        derived = issue_derived_semantic_verification_obligation(
            obligation=case["semantic"],
            parent_receipts=case["parents"],
            bridge_receipts=case["bridges"],
            rerank_receipt=receipt,
            store=case["store"],
            config=case["config"],
            runtime=case["runtime"],
        )
        self.assertEqual(derived.derivation_kind, "reranked")
        self.assertEqual(derived.supplied_evidence_ids, receipt.ordered_evidence_ids[:6])
        validate_semantic_verification_obligation(
            obligation=derived,
            store=case["store"],
            config=case["config"],
            runtime=case["runtime"],
        )

    def test_bridge_only_output_is_legal_and_role_partitions_follow_global_order(self):
        case = self._case(name="bridge-only", ordered_indexes=(4, 3))
        input_ids, input_roles = self._input(case)
        receipt = self._execute(case)
        expected = (input_ids[4], input_ids[3])
        self.assertEqual(tuple(input_roles[index] for index in (4, 3)), ("bridge", "bridge"))
        self.assertEqual(receipt.ordered_evidence_ids, expected)
        self.assertEqual(receipt.candidate_evidence_ids, ())
        self.assertEqual(receipt.bridge_evidence_ids, expected)
        derived = issue_derived_semantic_verification_obligation(
            obligation=case["semantic"],
            parent_receipts=case["parents"],
            bridge_receipts=case["bridges"],
            rerank_receipt=receipt,
            store=case["store"],
            config=case["config"],
            runtime=case["runtime"],
        )
        self.assertEqual(derived.supplied_evidence_ids, expected)
        self.assertEqual(derived.candidate_evidence_ids, ())
        self.assertEqual(derived.bridge_evidence_ids, expected)
        self.assertEqual(derived.context_evidence_ids, ())
        self.assertEqual(derived.base_semantic_obligation_sha256, case["semantic"].obligation_sha256)
        self.assertEqual(derived.rerank_receipt_sha256, receipt.receipt_sha256)
        self.assertEqual(derived.parent_context_receipt_sha256s, tuple(item.receipt_sha256 for item in case["parents"]))
        self.assertEqual(derived.bridge_context_receipt_sha256s, tuple(item.receipt_sha256 for item in case["bridges"]))

    def test_provider_and_malformed_results_close_and_consume_without_derived_mint(self):
        cases = (("provider_error", "provider_error", "reranker_provider_error"),) + tuple(
            (mode, "contract_error", "reranker_contract_error")
            for mode in ("extra", "version", "tuple", "bool", "negative", "duplicate", "empty", "out_of_range")
        )
        for mode, outcome, error_code in cases:
            with self.subTest(mode=mode):
                case = self._case(name=f"failure-{mode}", reranker_mode=mode)
                receipt = self._execute(case)
                self.assertEqual((receipt.outcome, receipt.call_performed, receipt.error_code), (outcome, True, error_code))
                self.assertEqual(receipt.ordered_evidence_ids, ())
                self.assertEqual(receipt.candidate_evidence_ids, ())
                self.assertEqual(receipt.bridge_evidence_ids, ())
                public = json.dumps(receipt.to_dict(), ensure_ascii=False)
                self.assertNotIn("private-provider", public)
                self.assertNotIn("raw-secret", public)
                with self.assertRaisesRegex(ValueError, "rerank.*(failed|outcome)|derived.*rerank|contract"):
                    issue_derived_semantic_verification_obligation(
                        obligation=case["semantic"],
                        parent_receipts=case["parents"],
                        bridge_receipts=case["bridges"],
                        rerank_receipt=receipt,
                        store=case["store"],
                        config=case["config"],
                        runtime=case["runtime"],
                    )
                with self.assertRaisesRegex(ValueError, "already_consumed|rerank.*consumed"):
                    self._execute(case)
                self.assertEqual(_calls(case["call_log"]), ("rerank",))

    def test_provider_exception_with_post_call_drift_is_consumed_contract_error(self):
        case = self._case(
            name="mutating-provider-error",
            reranker_mode="mutating_provider_error",
        )

        receipt = self._execute(case)

        self.assertEqual(
            (receipt.outcome, receipt.call_performed, receipt.error_code),
            ("contract_error", True, "reranker_contract_error"),
        )
        self.assertEqual(receipt.ordered_evidence_ids, ())
        self.assertEqual(receipt.candidate_evidence_ids, ())
        self.assertEqual(receipt.bridge_evidence_ids, ())
        self.assertNotIn(
            "private-mutating-provider-secret",
            json.dumps(receipt.to_dict(), ensure_ascii=False),
        )
        case["reranker"].ordered_indexes = (4, 0, 3, 1)
        with self.assertRaisesRegex(ValueError, "already_consumed|rerank.*consumed"):
            self._execute(case)
        self.assertEqual(_calls(case["call_log"]), ("rerank",))

    def test_exact_complete_context_batches_and_authorities_are_required_pre_call(self):
        case = self._case(name="prerequisite")
        other = self._case(name="prerequisite-other")
        base = {
            "obligation": case["semantic"],
            "parent_receipts": case["parents"],
            "bridge_receipts": case["bridges"],
            "store": case["store"],
            "config": case["config"],
            "runtime": case["runtime"],
        }
        bad = (
            {"parent_receipts": case["parents"][:-1]},
            {"bridge_receipts": tuple(reversed(case["bridges"]))},
            {"parent_receipts": (_clone_slots(case["parents"][0]),) + case["parents"][1:]},
            {"parent_receipts": other["parents"]},
            {"bridge_receipts": other["bridges"]},
            {"store": type(case["store"]).from_dict(case["store"].to_dict())},
            {"config": type(case["config"]).from_dict(case["config"].to_dict())},
            {"runtime": other["runtime"]},
        )
        for override in bad:
            with self.subTest(mixed=tuple(override)):
                with self.assertRaises((TypeError, ValueError)):
                    execution_contracts.execute_semantic_rerank(**{**base, **override})
        self.assertEqual(_calls(case["call_log"]), ())
        receipt = execution_contracts.execute_semantic_rerank(**base)
        self.assertEqual(_calls(case["call_log"]), ("rerank",))
        with self.assertRaisesRegex(ValueError, "authority"):
            validate_rerank_receipt(receipt=_clone_slots(receipt), **base)

    def test_derived_verifier_uses_unindexed_auxiliary_parents_without_promotion(self):
        verifier_log = self.tempdir / "aux-verifier.log"
        request_log = self.tempdir / "aux-request.json"
        verifier = _AuxVerifier(
            call_log_path=verifier_log,
            request_log_path=request_log,
            support_indexes=(0, 1),
        )
        case = self._case(name="aux", ordered_indexes=(0, 3), verifier=verifier)
        rerank = self._execute(case)
        derived = issue_derived_semantic_verification_obligation(
            obligation=case["semantic"],
            parent_receipts=case["parents"],
            bridge_receipts=case["bridges"],
            rerank_receipt=rerank,
            store=case["store"],
            config=case["config"],
            runtime=case["runtime"],
        )
        semantic_receipt = execution_contracts.execute_semantic_verification(
            obligation=derived,
            store=case["store"],
            config=case["config"],
            runtime=case["runtime"],
        )
        lines = tuple(line.split("\t") for line in request_log.read_text(encoding="utf-8").splitlines())
        evidence = tuple(item for item in lines if item[0] == "evidence")
        auxiliary = tuple(item for item in lines if item[0] == "parent")
        self.assertEqual(tuple(int(item[1]) for item in evidence), tuple(range(len(derived.supplied_evidence_ids))))
        self.assertEqual(tuple(item[2] for item in evidence), ("candidate", "bridge"))
        self.assertTrue(all(item[6] == "False" for item in evidence))
        self.assertTrue(auxiliary)
        self.assertTrue(all(item[5:] == ["False", "False"] for item in auxiliary))
        parent_by_seed = {item.seed_evidence_id: item for item in case["parents"]}
        bridge_origin = {
            linked: item.seed_evidence_id
            for item in case["bridges"]
            for linked in item.linked_evidence_ids
        }
        expected_parent_ids = []
        for evidence_id, role in zip(derived.supplied_evidence_ids, ("candidate", "bridge")):
            seed = evidence_id if role == "candidate" else bridge_origin[evidence_id]
            parent_id = parent_by_seed[seed].parent_id
            if parent_id not in expected_parent_ids:
                expected_parent_ids.append(parent_id)
        self.assertEqual(tuple(item[1] for item in auxiliary), tuple(expected_parent_ids))
        self.assertEqual(semantic_receipt.verified_evidence_ids, derived.supplied_evidence_ids)
        public = json.dumps({"obligation": derived.to_dict(), "receipt": semantic_receipt.to_dict()}, ensure_ascii=False)
        for item in auxiliary:
            self.assertNotIn(item[1], public)
            self.assertNotIn(item[4], public)
        self.assertEqual(_calls(verifier_log), ("verify",))

        invalid_log = self.tempdir / "aux-index-verifier.log"
        invalid_case = self._case(
            name="aux-index",
            ordered_indexes=(0, 3),
            verifier=_AuxVerifier(
                call_log_path=invalid_log,
                request_log_path=self.tempdir / "aux-index-request.json",
                support_indexes=(2,),
            ),
        )
        invalid_rerank = self._execute(invalid_case)
        invalid_derived = issue_derived_semantic_verification_obligation(
            obligation=invalid_case["semantic"],
            parent_receipts=invalid_case["parents"],
            bridge_receipts=invalid_case["bridges"],
            rerank_receipt=invalid_rerank,
            store=invalid_case["store"],
            config=invalid_case["config"],
            runtime=invalid_case["runtime"],
        )
        with self.assertRaisesRegex(ValueError, "semantic_verifier_contract_error"):
            execution_contracts.execute_semantic_verification(
                obligation=invalid_derived,
                store=invalid_case["store"],
                config=invalid_case["config"],
                runtime=invalid_case["runtime"],
            )
        self.assertEqual(_calls(invalid_log), ("verify",))

    def test_base_and_derived_verifier_route_is_single_and_rerank_history_survives_gc(self):
        verifier_log = self.tempdir / "route-verifier.log"
        case = self._case(
            name="route",
            ordered_indexes=(0, 3),
            verifier=_AuxVerifier(
                call_log_path=verifier_log,
                request_log_path=self.tempdir / "route-request.json",
            ),
        )
        rerank = self._execute(case)
        derived = issue_derived_semantic_verification_obligation(
            obligation=case["semantic"],
            parent_receipts=case["parents"],
            bridge_receipts=case["bridges"],
            rerank_receipt=rerank,
            store=case["store"],
            config=case["config"],
            runtime=case["runtime"],
        )
        barrier = Barrier(3)

        def invoke(obligation):
            barrier.wait()
            try:
                return execution_contracts.execute_semantic_verification(
                    obligation=obligation,
                    store=case["store"],
                    config=case["config"],
                    runtime=case["runtime"],
                )
            except Exception as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = (
                pool.submit(invoke, case["semantic"]),
                pool.submit(invoke, derived),
            )
            barrier.wait()
            outcomes = tuple(future.result(timeout=2) for future in futures)
        self.assertEqual(sum(type(item) is SemanticVerificationReceipt for item in outcomes), 1)
        self.assertEqual(sum(type(item) is ValueError for item in outcomes), 1)
        self.assertRegex(str(next(item for item in outcomes if type(item) is ValueError)), "already_consumed|route|superseded")
        self.assertEqual(_calls(verifier_log), ("verify",))

        store = case["store"]
        config = case["config"]
        runtime = case["runtime"]
        _bound, retrieval, fusion = self._roots["route"]
        rerank_log = case["call_log"]
        del outcomes, futures, derived, rerank, case
        gc.collect()
        equivalent = issue_fact_semantic_verification_obligation(
            obligation=retrieval,
            fusion_receipt=fusion,
            store=store,
            config=config,
            runtime=runtime,
        )
        parents = issue_parent_context_receipts(
            obligation=equivalent, store=store, config=config, runtime=runtime
        )
        bridges = issue_bridge_context_receipts(
            obligation=equivalent, store=store, config=config, runtime=runtime
        )
        with self.assertRaisesRegex(ValueError, "already_consumed|rerank.*consumed|route"):
            execution_contracts.execute_semantic_rerank(
                obligation=equivalent,
                parent_receipts=parents,
                bridge_receipts=bridges,
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual(_calls(rerank_log), ("rerank",))


if __name__ == "__main__":
    unittest.main()
