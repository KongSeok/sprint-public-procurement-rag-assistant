"""EH2.6.c3.3 bounded absence confirmation acceptance tests."""

from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
import inspect
import json
from pathlib import Path
import pickle
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from concurrent.futures import ThreadPoolExecutor
import gc
from weakref import ref

import midprojectrag.orchestration as orchestration
import midprojectrag.orchestration.execution_contracts as execution_contracts
from midprojectrag.orchestration import (
    CatalogDocument,
    DeterministicPlanner,
    FollowupEvidencePolicy,
    HarnessRuntimeBinding,
    PlanningCatalog,
    RequiredSlot,
    bind_followup,
    bind_primary_evidence_progress,
    create_harness_execution_config,
    execute_retrieval_fusion,
    execute_retrieval_lane,
    finalize_followup_retrieval,
    issue_fact_retrieval_obligations,
    retrieve_followup_primary,
    default_rule_registry,
)
from midprojectrag.retrieval.fusion import HybridChildRetriever
from midprojectrag.runtime_integrity import RuntimeRequest

from tests.test_retrieval_obligations import (
    _SyntheticLane,
    _calls,
    _clock,
    _compare_bound,
    _fact_bound,
    _runtime as _retrieval_runtime,
    _store,
)
import tests.test_rerank_derived_semantic as rerank_fixture_module
import tests.test_semantic_verification as semantic_fixture_module
from tests.test_semantic_verification import (
    _RaisingSemanticVerifier,
    _SemanticVerifier,
    _raw,
)
from tests.test_action_effect_receipts import _clone_slots
from tests.test_e1_followup_projection import _fixture as _followup_fixture
import tests.test_followup as followup_fixture_module


class AbsenceConfirmationAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.tempdir = Path(self._temporary.name)
        # Reused c3.2 fixture retains its owner roots here, exactly as its own
        # acceptance tests do; absence must bind that live root, not a rebuild.
        self._roots = {}

    def _retrieval_case(
        self,
        *,
        name="fact-empty",
        source_kind="fact",
        dense_mode="empty",
        lexical_mode="empty",
    ):
        store = _store(
            doc_ids=("doc-a",) if source_kind == "fact" else ("doc-a", "doc-b")
        )
        specs = tuple((item.evidence_id, item.doc_id) for item in store.evidence)
        retriever = HybridChildRetriever(
            store,
            _SyntheticLane(
                lane="dense",
                bundle_sha256=store.bundle_sha256,
                candidate_specs=specs,
                call_log_path=str(self.tempdir / f"{name}-dense.log"),
                mode=dense_mode,
            ),
            _SyntheticLane(
                lane="lexical",
                bundle_sha256=store.bundle_sha256,
                candidate_specs=specs,
                call_log_path=str(self.tempdir / f"{name}-lexical.log"),
                mode=lexical_mode,
            ),
        )
        runtime = HarnessRuntimeBinding.for_test(
            store=store,
            retriever=retriever,
            clock=_clock,
        )
        config = create_harness_execution_config(mode="e1_bounded")
        if source_kind == "fact":
            bound = _fact_bound(store)
            obligations = issue_fact_retrieval_obligations(
                bound=bound, store=store, config=config, runtime=runtime
            )
        else:
            bound, _registry = _compare_bound(store)
            obligations = orchestration.issue_compare_retrieval_obligations(
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
        fusion = None
        if dense.outcome in {"applied", "empty"} and lexical.outcome in {
            "applied",
            "empty",
        }:
            fusion = execute_retrieval_fusion(
                obligation=obligation,
                dense_receipt=dense,
                lexical_receipt=lexical,
                store=store,
                config=config,
                runtime=runtime,
            )
        return bound, store, config, runtime, obligation, dense, lexical, fusion

    def _empty_retrieval_case(self):
        return self._retrieval_case()

    def _all_empty_compare_cases(self, *, name):
        store = _store(doc_ids=("doc-a", "doc-b"))
        runtime = _retrieval_runtime(
            store=store,
            dense_log=self.tempdir / f"{name}-dense.log",
            lexical_log=self.tempdir / f"{name}-lexical.log",
            dense_mode="empty",
            lexical_mode="empty",
        )
        config = create_harness_execution_config(mode="e1_bounded")
        bound, _registry = _compare_bound(store)
        obligations = orchestration.issue_compare_retrieval_obligations(
            bound=bound, store=store, config=config, runtime=runtime
        )
        cases = []
        for obligation in obligations:
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
            cases.append(
                (bound, store, config, runtime, obligation, dense, lexical, fusion)
            )
        return tuple(cases)

    def _derived_semantic_case(
        self,
        *,
        name,
        disposition="unsupported",
        reranker_unavailable=False,
        provider_error=False,
        malformed=False,
        ordered_indexes=(0, 3),
    ):
        verifier_log = self.tempdir / f"{name}-verifier.log"
        if provider_error:
            verifier = _RaisingSemanticVerifier(call_log_path=verifier_log)
        else:
            verifier = _SemanticVerifier(
                raw_result=(
                    {"secret": "malformed-provider-body"}
                    if malformed
                    else _raw(
                        disposition,
                        () if disposition == "unsupported" else (0, 1),
                    )
                ),
                call_log_path=verifier_log,
            )
        case = rerank_fixture_module.RerankDerivedSemanticAcceptanceTests._case(
            self,
            name=name,
            ordered_indexes=ordered_indexes,
            unavailable=reranker_unavailable,
            verifier=verifier,
        )
        rerank = rerank_fixture_module.RerankDerivedSemanticAcceptanceTests._execute(
            case
        )
        derived = orchestration.issue_derived_semantic_verification_obligation(
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
        return case, rerank, derived, semantic_receipt, verifier_log

    def _derived_from_base_semantic(
        self,
        *,
        obligation,
        store,
        config,
        runtime,
    ):
        parents = orchestration.issue_parent_context_receipts(
            obligation=obligation, store=store, config=config, runtime=runtime
        )
        bridges = orchestration.issue_bridge_context_receipts(
            obligation=obligation, store=store, config=config, runtime=runtime
        )
        rerank = execution_contracts.execute_semantic_rerank(
            obligation=obligation,
            parent_receipts=parents,
            bridge_receipts=bridges,
            store=store,
            config=config,
            runtime=runtime,
        )
        derived = orchestration.issue_derived_semantic_verification_obligation(
            obligation=obligation,
            parent_receipts=parents,
            bridge_receipts=bridges,
            rerank_receipt=rerank,
            store=store,
            config=config,
            runtime=runtime,
        )
        semantic_receipt = execution_contracts.execute_semantic_verification(
            obligation=derived, store=store, config=config, runtime=runtime
        )
        return derived, semantic_receipt

    def _followup_case(
        self,
        *,
        name,
        explicit_scope=False,
        slots=(),
        primary_ids=(),
        fallback_ids=(),
        cited_doc_ids=("doc-a",),
        metadata=False,
    ):
        fixture = _followup_fixture(
            cited_doc_ids=cited_doc_ids,
            explicit_scope=explicit_scope,
            slots=slots,
            primary_ids=primary_ids,
            fallback_ids=fallback_ids,
            metadata=metadata,
        )
        store, evidence, registry, policy, bound, outcome, retriever = fixture
        runtime = _retrieval_runtime(
            store=store,
            dense_log=self.tempdir / f"{name}-dense.log",
            lexical_log=self.tempdir / f"{name}-lexical.log",
        )
        config = create_harness_execution_config(mode="e1_bounded")
        return {
            "store": store,
            "evidence": evidence,
            "registry": registry,
            "policy": policy,
            "bound": bound,
            "outcome": outcome,
            "retriever": retriever,
            "runtime": runtime,
            "config": config,
        }

    @staticmethod
    def _issue_semantic(case):
        fixture, _rerank, obligation, receipt, _log = case
        return execution_contracts.issue_semantic_absence_confirmation(
            obligation=obligation,
            receipt=receipt,
            store=fixture["store"],
            config=fixture["config"],
            runtime=fixture["runtime"],
        )

    @staticmethod
    def _issue_followup(case, obligation_key):
        return execution_contracts.issue_followup_absence_confirmation(
            bound=case["bound"],
            outcome=case["outcome"],
            obligation_key=obligation_key,
            store=case["store"],
            registry=case["registry"],
            policy=case["policy"],
            config=case["config"],
            runtime=case["runtime"],
        )

    @staticmethod
    def _issue_retrieval(case):
        (
            _bound,
            store,
            config,
            runtime,
            obligation,
            dense,
            lexical,
            fusion,
        ) = case
        return execution_contracts.issue_retrieval_absence_confirmation(
            obligation=obligation,
            dense_receipt=dense,
            lexical_receipt=lexical,
            fusion_receipt=fusion,
            store=store,
            config=config,
            runtime=runtime,
        )

    def test_public_surface_is_closed_and_receipt_is_factory_only(self) -> None:
        receipt_type = orchestration.AbsenceConfirmationReceipt
        self.assertIs(receipt_type, execution_contracts.AbsenceConfirmationReceipt)
        self.assertIs(
            orchestration.validate_absence_confirmation_receipt,
            execution_contracts.validate_absence_confirmation_receipt,
        )
        for private_name in (
            "issue_retrieval_absence_confirmation",
            "issue_semantic_absence_confirmation",
            "issue_followup_absence_confirmation",
        ):
            self.assertFalse(hasattr(orchestration, private_name))
            self.assertTrue(hasattr(execution_contracts, private_name))
        with self.assertRaisesRegex(TypeError, "factory_required"):
            receipt_type()
        self.assertFalse(hasattr(receipt_type, "from_dict"))
        parameters = inspect.signature(
            orchestration.validate_absence_confirmation_receipt
        ).parameters
        self.assertEqual(tuple(parameters), ("receipt", "store", "config", "runtime"))
        self.assertTrue(
            all(item.kind is inspect.Parameter.KEYWORD_ONLY for item in parameters.values())
        )
        required_signatures = {
            execution_contracts.issue_retrieval_absence_confirmation: (
                "obligation",
                "dense_receipt",
                "lexical_receipt",
                "fusion_receipt",
                "store",
                "config",
                "runtime",
            ),
            execution_contracts.issue_semantic_absence_confirmation: (
                "obligation",
                "receipt",
                "store",
                "config",
                "runtime",
            ),
            execution_contracts.issue_followup_absence_confirmation: (
                "bound",
                "outcome",
                "obligation_key",
                "store",
                "registry",
                "policy",
                "config",
                "runtime",
            ),
        }
        for function, required in required_signatures.items():
            with self.subTest(function=function.__name__):
                actual = inspect.signature(function).parameters
                self.assertTrue(set(required) <= set(actual))
                self.assertTrue(
                    all(
                        item.kind is inspect.Parameter.KEYWORD_ONLY
                        for name, item in actual.items()
                        if name in required
                    )
                )
                self.assertFalse(
                    any(
                        item.kind
                        in {
                            inspect.Parameter.VAR_POSITIONAL,
                            inspect.Parameter.VAR_KEYWORD,
                        }
                        for item in actual.values()
                    )
                )
                self.assertFalse(
                    {
                        "reason",
                        "evidence_ids",
                        "query",
                        "gold",
                        "qrels",
                        "deadline",
                        "timeout",
                        "action",
                        "state",
                        "effect",
                    }.intersection(actual)
                )

    def test_fact_and_compare_normal_all_empty_mint_no_candidate(self) -> None:
        for source_kind in ("fact", "compare"):
            with self.subTest(source_kind=source_kind):
                case = self._retrieval_case(
                    name=f"{source_kind}-all-empty", source_kind=source_kind
                )
                receipt = self._issue_retrieval(case)
                self.assertEqual(receipt.reason, "bounded_no_candidate")
                self.assertEqual(receipt.source_kind, source_kind)
                self.assertEqual(
                    (
                        receipt.candidate_count,
                        receipt.supplied_count,
                        receipt.support_count,
                    ),
                    (0, 0, 0),
                )
                self.assertFalse(receipt.call_performed)

    def test_every_compare_slot_can_close_only_after_its_own_all_empty_pair(self) -> None:
        cases = self._all_empty_compare_cases(name="compare-matrix-empty")
        self.assertEqual(
            tuple(case[4].obligation_key for case in cases),
            (
                "doc-a.budget",
                "doc-a.duration",
                "doc-b.budget",
                "doc-b.duration",
            ),
        )
        receipts = tuple(self._issue_retrieval(case) for case in cases)
        self.assertEqual(
            tuple(receipt.obligation_key for receipt in receipts),
            tuple(case[4].obligation_key for case in cases),
        )
        self.assertTrue(
            all(receipt.reason == "bounded_no_candidate" for receipt in receipts)
        )
        self.assertEqual(
            _calls(self.tempdir / "compare-matrix-empty-dense.log"),
            ("dense",) * len(cases),
        )
        self.assertEqual(
            _calls(self.tempdir / "compare-matrix-empty-lexical.log"),
            ("lexical",) * len(cases),
        )

    def test_partial_and_one_empty_top_k_do_not_mint(self) -> None:
        partial = self._retrieval_case(name="partial")
        base = {
            "obligation": partial[4],
            "dense_receipt": partial[5],
            "lexical_receipt": partial[6],
            "fusion_receipt": partial[7],
            "store": partial[1],
            "config": partial[2],
            "runtime": partial[3],
        }
        for override in (
            {"lexical_receipt": None},
            {"fusion_receipt": None},
        ):
            with self.subTest(override=tuple(override)):
                with self.assertRaises((TypeError, ValueError)):
                    execution_contracts.issue_retrieval_absence_confirmation(
                        **{**base, **override}
                    )

        one_empty = self._retrieval_case(
            name="one-empty", dense_mode="empty", lexical_mode="valid"
        )
        with self.assertRaises((TypeError, ValueError)):
            self._issue_retrieval(one_empty)

    def test_mixed_retrieval_lineage_does_not_mint(self) -> None:
        first = self._retrieval_case(name="mixed-first")
        second = self._retrieval_case(name="mixed-second")
        with self.assertRaises((TypeError, ValueError)):
            execution_contracts.issue_retrieval_absence_confirmation(
                obligation=first[4],
                dense_receipt=first[5],
                lexical_receipt=second[6],
                fusion_receipt=first[7],
                store=first[1],
                config=first[2],
                runtime=first[3],
            )
        with self.assertRaises((TypeError, ValueError)):
            execution_contracts.issue_retrieval_absence_confirmation(
                obligation=first[4],
                dense_receipt=_clone_slots(first[5]),
                lexical_receipt=first[6],
                fusion_receipt=first[7],
                store=first[1],
                config=first[2],
                runtime=first[3],
            )

    def test_derived_unsupported_mints_no_verified_support_including_skipped_reranker(
        self,
    ) -> None:
        for reranker_unavailable in (False, True):
            with self.subTest(reranker_unavailable=reranker_unavailable):
                case = self._derived_semantic_case(
                    name=f"derived-unsupported-{reranker_unavailable}",
                    reranker_unavailable=reranker_unavailable,
                )
                receipt = self._issue_semantic(case)
                fixture, rerank, obligation, semantic, verifier_log = case
                self.assertEqual(receipt.reason, "bounded_no_verified_support")
                self.assertEqual(receipt.source_kind, "fact")
                self.assertEqual(receipt.candidate_count, len(obligation.candidate_evidence_ids))
                self.assertEqual(receipt.supplied_count, len(obligation.supplied_evidence_ids))
                self.assertEqual(receipt.support_count, 0)
                self.assertGreater(receipt.supplied_count, 0)
                self.assertFalse(receipt.call_performed)
                self.assertTrue(semantic.call_performed)
                self.assertEqual(semantic.disposition, "unsupported")
                self.assertEqual(
                    rerank.outcome,
                    "skipped_unavailable" if reranker_unavailable else "applied",
                )
                self.assertEqual(
                    _calls(fixture["call_log"]),
                    () if reranker_unavailable else ("rerank",),
                )
                self.assertEqual(
                    verifier_log.read_text(encoding="utf-8").splitlines(),
                    ["verify"],
                )
                orchestration.validate_absence_confirmation_receipt(
                    receipt=receipt,
                    store=fixture["store"],
                    config=fixture["config"],
                    runtime=fixture["runtime"],
                )

    def test_compare_and_followup_derived_unsupported_can_mint(self) -> None:
        compare_log = self.tempdir / "compare-derived-verifier.log"
        compare_verifier = _SemanticVerifier(
            raw_result=_raw("unsupported", ()), call_log_path=compare_log
        )
        # Reuse c2's canonical compare retrieval/semantic factory path.
        self._runtime = (
            semantic_fixture_module.SemanticVerificationExecutionTests._runtime.__get__(
                self
            )
        )
        store, config, runtime, base = (
            semantic_fixture_module.SemanticVerificationExecutionTests._retrieval_case(
                self,
                name="compare-derived",
                source_kind="compare",
                verifier=compare_verifier,
            )
        )
        derived, semantic_receipt = self._derived_from_base_semantic(
            obligation=base, store=store, config=config, runtime=runtime
        )
        compare_absence = execution_contracts.issue_semantic_absence_confirmation(
            obligation=derived,
            receipt=semantic_receipt,
            store=store,
            config=config,
            runtime=runtime,
        )
        self.assertEqual(
            (compare_absence.source_kind, compare_absence.reason),
            ("compare", "bounded_no_verified_support"),
        )
        self.assertEqual(_calls(compare_log), ("verify",))

        followup = _followup_fixture(primary_ids=(0,), fallback_ids=(1,))
        (
            followup_store,
            _evidence,
            registry,
            policy,
            bound,
            outcome,
            _retriever,
        ) = followup
        followup_log = self.tempdir / "followup-derived-verifier.log"
        followup_runtime = (
            semantic_fixture_module.SemanticVerificationExecutionTests._runtime(
                self,
                store=followup_store,
                verifier=_SemanticVerifier(
                    raw_result=_raw("unsupported", ()),
                    call_log_path=followup_log,
                ),
                name="followup-derived",
            )
        )
        followup_config = create_harness_execution_config(mode="e1_bounded")
        followup_base = orchestration.issue_followup_semantic_verification_obligation(
            bound=bound,
            outcome=outcome,
            obligation_key="$answer_support",
            store=followup_store,
            registry=registry,
            policy=policy,
            config=followup_config,
            runtime=followup_runtime,
        )
        followup_derived, followup_semantic_receipt = self._derived_from_base_semantic(
            obligation=followup_base,
            store=followup_store,
            config=followup_config,
            runtime=followup_runtime,
        )
        followup_absence = execution_contracts.issue_semantic_absence_confirmation(
            obligation=followup_derived,
            receipt=followup_semantic_receipt,
            store=followup_store,
            config=followup_config,
            runtime=followup_runtime,
        )
        self.assertEqual(
            (followup_absence.source_kind, followup_absence.reason),
            ("follow_up", "bounded_no_verified_support"),
        )
        self.assertEqual(_calls(followup_log), ("verify",))

    def test_bridge_only_derived_unsupported_records_zero_candidates(self) -> None:
        case = self._derived_semantic_case(
            name="bridge-only-unsupported",
            ordered_indexes=(4, 3),
        )
        receipt = self._issue_semantic(case)
        obligation = case[2]
        self.assertEqual(obligation.candidate_evidence_ids, ())
        self.assertTrue(obligation.bridge_evidence_ids)
        self.assertEqual(receipt.candidate_count, 0)
        self.assertEqual(receipt.supplied_count, len(obligation.supplied_evidence_ids))
        self.assertGreater(receipt.supplied_count, 0)
        self.assertEqual(receipt.support_count, 0)

    def test_base_unsupported_and_skipped_rerank_alone_do_not_mint(self) -> None:
        case = rerank_fixture_module.RerankDerivedSemanticAcceptanceTests._case(
            self,
            name="base-unsupported",
            ordered_indexes=(0, 3),
            verifier=_SemanticVerifier(
                raw_result=_raw("unsupported", ()),
                call_log_path=self.tempdir / "base-unsupported-verifier.log",
            ),
        )
        base_receipt = execution_contracts.execute_semantic_verification(
            obligation=case["semantic"],
            store=case["store"],
            config=case["config"],
            runtime=case["runtime"],
        )
        with self.assertRaises((TypeError, ValueError)):
            execution_contracts.issue_semantic_absence_confirmation(
                obligation=case["semantic"],
                receipt=base_receipt,
                store=case["store"],
                config=case["config"],
                runtime=case["runtime"],
            )

        skipped_case = rerank_fixture_module.RerankDerivedSemanticAcceptanceTests._case(
            self, name="skipped-alone", unavailable=True
        )
        skipped = rerank_fixture_module.RerankDerivedSemanticAcceptanceTests._execute(
            skipped_case
        )
        with self.assertRaises((TypeError, ValueError)):
            execution_contracts.issue_semantic_absence_confirmation(
                obligation=skipped_case["semantic"],
                receipt=skipped,
                store=skipped_case["store"],
                config=skipped_case["config"],
                runtime=skipped_case["runtime"],
            )

    def test_supported_contradicted_unavailable_and_error_do_not_mint(self) -> None:
        for disposition in ("supported", "contradicted"):
            with self.subTest(disposition=disposition):
                case = self._derived_semantic_case(
                    name=f"semantic-{disposition}", disposition=disposition
                )
                with self.assertRaises((TypeError, ValueError)):
                    self._issue_semantic(case)

        # Reuse c3.2's complete owner graph while asking its fixture to bind no
        # verifier. This reaches a genuinely reranked-derived unavailable receipt.
        issued_test_verifier = rerank_fixture_module._Verifier
        rerank_fixture_module._Verifier = lambda: None
        try:
            unavailable_case = rerank_fixture_module.RerankDerivedSemanticAcceptanceTests._case(
                self, name="semantic-unavailable", verifier=None
            )
        finally:
            rerank_fixture_module._Verifier = issued_test_verifier
        unavailable_rerank = rerank_fixture_module.RerankDerivedSemanticAcceptanceTests._execute(
            unavailable_case
        )
        unavailable_obligation = (
            orchestration.issue_derived_semantic_verification_obligation(
                obligation=unavailable_case["semantic"],
                parent_receipts=unavailable_case["parents"],
                bridge_receipts=unavailable_case["bridges"],
                rerank_receipt=unavailable_rerank,
                store=unavailable_case["store"],
                config=unavailable_case["config"],
                runtime=unavailable_case["runtime"],
            )
        )
        unavailable = execution_contracts.execute_semantic_verification(
            obligation=unavailable_obligation,
            store=unavailable_case["store"],
            config=unavailable_case["config"],
            runtime=unavailable_case["runtime"],
        )
        self.assertEqual((unavailable.disposition, unavailable.call_performed), ("unavailable", False))
        with self.assertRaises((TypeError, ValueError)):
            execution_contracts.issue_semantic_absence_confirmation(
                obligation=unavailable_obligation,
                receipt=unavailable,
                store=unavailable_case["store"],
                config=unavailable_case["config"],
                runtime=unavailable_case["runtime"],
            )

        with self.assertRaisesRegex(ValueError, "semantic_verifier_provider_error"):
            self._derived_semantic_case(
                name="semantic-provider-error", provider_error=True
            )
        with self.assertRaisesRegex(ValueError, "semantic_verifier_contract_error"):
            self._derived_semantic_case(
                name="semantic-contract-error", malformed=True
            )

    def test_followup_empty_answer_support_closes_both_fallback_branches(self) -> None:
        for explicit_scope, expected_flags in (
            (False, (True, True)),
            (True, (False, False)),
        ):
            with self.subTest(explicit_scope=explicit_scope):
                case = self._followup_case(
                    name=f"followup-answer-{explicit_scope}",
                    explicit_scope=explicit_scope,
                )
                before_calls = len(case["retriever"].calls)
                receipt = self._issue_followup(case, "$answer_support")
                self.assertEqual(receipt.reason, "followup_approved_paths_exhausted")
                self.assertEqual(receipt.source_kind, "follow_up")
                self.assertEqual(receipt.obligation_key, "$answer_support")
                self.assertEqual(
                    (receipt.fallback_authorized, receipt.fallback_executed),
                    expected_flags,
                )
                self.assertEqual(
                    (
                        receipt.candidate_count,
                        receipt.supplied_count,
                        receipt.support_count,
                    ),
                    (0, 0, 0),
                )
                self.assertFalse(receipt.call_performed)
                self.assertRegex(receipt.primary_receipt_sha256, r"^[0-9a-f]{64}$")
                if explicit_scope:
                    self.assertIsNone(receipt.fallback_receipt_sha256)
                else:
                    self.assertRegex(
                        receipt.fallback_receipt_sha256, r"^[0-9a-f]{64}$"
                    )
                self.assertEqual(len(case["retriever"].calls), before_calls)
                self.assertFalse(
                    (self.tempdir / f"followup-answer-{explicit_scope}-dense.log").exists()
                )
                self.assertFalse(
                    (self.tempdir / f"followup-answer-{explicit_scope}-lexical.log").exists()
                )

    def test_followup_production_source_rejects_synthetic_runtime(self) -> None:
        store, evidence = followup_fixture_module._evidence_store()
        registry = default_rule_registry()
        catalog = PlanningCatalog.from_metadata(
            "prod-followup-absence-v1",
            (
                CatalogDocument("doc-a", "사업A"),
                CatalogDocument("doc-b", "사업B"),
            ),
        )
        planner = DeterministicPlanner(registry, catalog)
        request = RuntimeRequest(
            question="그 사업의 기간은?",
            history=(
                followup_fixture_module._assistant_turn(
                    ("doc-a",), (evidence[0].evidence_id,)
                ),
            ),
            document_scope={"mode": "all", "doc_ids": []},
            options={"allow_global_fallback": True},
            prior_citation_state=followup_fixture_module._prior(
                ("doc-a",), (evidence[0].evidence_id,)
            ),
        )
        bound = bind_followup(request, planner.plan(request), store, registry)
        retriever = followup_fixture_module._FakeRetriever(
            followup_fixture_module._result(store),
            followup_fixture_module._result(store),
        )
        primary = retrieve_followup_primary(
            bound=bound,
            store=store,
            registry=registry,
            retriever=retriever,
        )
        policy = FollowupEvidencePolicy.v1()
        progress = bind_primary_evidence_progress(
            bound=bound,
            primary=primary,
            store=store,
            registry=registry,
            policy=policy,
            verified_answer_evidence_ids=(),
            verifier_id="deterministic-evidence-verifier-v1",
            verifier_config_sha256="1" * 64,
        )
        outcome = finalize_followup_retrieval(
            bound=bound,
            primary=primary,
            progress=progress,
            store=store,
            registry=registry,
            policy=policy,
            retriever=retriever,
        )
        runtime = _retrieval_runtime(
            store=store,
            dense_log=self.tempdir / "prod-mismatch-dense.log",
            lexical_log=self.tempdir / "prod-mismatch-lexical.log",
        )

        self.assertEqual(bound.planning.trace.execution_kind, "production")
        self.assertEqual(runtime.execution_kind, "synthetic")
        with self.assertRaisesRegex(
            ValueError, "harness_runtime_execution_kind_mismatch"
        ):
            execution_contracts.issue_followup_absence_confirmation(
                bound=bound,
                outcome=outcome,
                obligation_key="$answer_support",
                store=store,
                registry=registry,
                policy=policy,
                config=create_harness_execution_config(mode="e1_bounded"),
                runtime=runtime,
            )
        self.assertFalse((self.tempdir / "prod-mismatch-dense.log").exists())
        self.assertFalse((self.tempdir / "prod-mismatch-lexical.log").exists())

    def test_followup_required_slot_empty_is_per_target_not_whole_result(self) -> None:
        slot = RequiredSlot("doc-a", "duration")
        case = self._followup_case(
            name="followup-slot-per-target",
            explicit_scope=True,
            cited_doc_ids=("doc-a", "doc-b"),
            slots=(slot,),
            primary_ids=(1,),
        )
        self.assertEqual(len(case["outcome"].primary.result.candidates), 1)
        self.assertEqual(case["outcome"].primary.result.candidates[0].doc_id, "doc-b")

        receipt = self._issue_followup(case, slot.key)

        self.assertEqual(receipt.obligation_key, slot.key)
        self.assertEqual(receipt.candidate_count, 0)
        with self.assertRaises((TypeError, ValueError)):
            self._issue_followup(case, "$answer_support")

    def test_followup_target_candidate_or_authorized_fallback_candidate_does_not_mint(
        self,
    ) -> None:
        slot = RequiredSlot("doc-a", "duration")
        cases = (
            (
                self._followup_case(
                    name="followup-primary-candidate",
                    explicit_scope=True,
                    slots=(slot,),
                    primary_ids=(0,),
                ),
                slot.key,
            ),
            (
                self._followup_case(
                    name="followup-fallback-candidate",
                    primary_ids=(),
                    fallback_ids=(0,),
                ),
                "$answer_support",
            ),
        )
        for case, obligation_key in cases:
            with self.subTest(reason=case["outcome"].trace.reason):
                with self.assertRaises((TypeError, ValueError)):
                    self._issue_followup(case, obligation_key)

    def test_followup_unresolved_metadata_skipped_and_mixed_lineage_do_not_mint(
        self,
    ) -> None:
        # Reuse the canonical follow-up fixture that intentionally intersects
        # citations with a disjoint explicit scope, producing a zero-call empty scope.
        helper = followup_fixture_module.ActualCitationFollowupTests()
        helper.setUp()
        bound = helper.bind(
            helper.request(document_scope={"mode": "explicit", "doc_ids": ["doc-b"]})
        )
        retriever = followup_fixture_module._FakeRetriever()
        policy = FollowupEvidencePolicy.v1()
        primary = retrieve_followup_primary(
            bound=bound,
            store=helper.store,
            registry=helper.registry,
            retriever=retriever,
        )
        progress = bind_primary_evidence_progress(
            bound=bound,
            primary=primary,
            store=helper.store,
            registry=helper.registry,
            policy=policy,
            verified_answer_evidence_ids=(),
            verifier_id="deterministic-evidence-verifier-v1",
            verifier_config_sha256="1" * 64,
        )
        outcome = finalize_followup_retrieval(
            bound=bound,
            primary=primary,
            progress=progress,
            store=helper.store,
            registry=helper.registry,
            policy=policy,
            retriever=retriever,
        )
        unresolved = self._followup_case(name="followup-unresolved")
        unresolved.update(
            store=helper.store,
            registry=helper.registry,
            policy=policy,
            bound=bound,
            outcome=outcome,
            retriever=retriever,
        )
        unresolved["runtime"] = _retrieval_runtime(
            store=helper.store,
            dense_log=self.tempdir / "followup-unresolved-dense.log",
            lexical_log=self.tempdir / "followup-unresolved-lexical.log",
        )
        self.assertFalse(primary.retriever_called)
        with self.assertRaises((TypeError, ValueError)):
            self._issue_followup(unresolved, "$answer_support")

        metadata = self._followup_case(
            name="followup-metadata", metadata=True
        )
        with self.assertRaises((TypeError, ValueError)):
            self._issue_followup(metadata, "$answer_support")

        authorized = self._followup_case(name="followup-skipped-authorized")
        issued_outcome = authorized["outcome"]
        issued_fallback = issued_outcome.fallback
        object.__setattr__(issued_outcome, "fallback", None)
        try:
            with self.assertRaisesRegex(
                ValueError,
                "followup_outcome_nested_identity_drift|fallback.*(decision|incomplete)",
            ):
                self._issue_followup(authorized, "$answer_support")
        finally:
            object.__setattr__(issued_outcome, "fallback", issued_fallback)

        other = self._followup_case(name="followup-mixed-other")
        mixed = {**authorized, "outcome": other["outcome"]}
        with self.assertRaises((TypeError, ValueError)):
            self._issue_followup(mixed, "$answer_support")

    def test_provider_error_is_never_retrieval_absence_authority(self) -> None:
        case = self._retrieval_case(
            name="retrieval-provider-error",
            dense_mode="provider_error",
            lexical_mode="empty",
        )
        self.assertEqual(case[5].outcome, "provider_error")
        self.assertIsNone(case[7])
        with self.assertRaises((TypeError, ValueError)):
            self._issue_retrieval(case)

    def test_receipt_is_noncopyable_frozen_and_has_no_promotion_authority(self) -> None:
        case = self._retrieval_case(name="closed-dto")
        receipt = self._issue_retrieval(case)
        with self.assertRaises(FrozenInstanceError):
            receipt.reason = "forged"
        self.assertFalse(hasattr(receipt, "__dict__"))
        for authority_name in (
            "candidate_evidence_ids",
            "verified_evidence_ids",
            "contradicted_evidence_ids",
            "citations",
            "state",
            "effect",
            "transition",
            "normal_stop_allowed",
            "abstain_required",
        ):
            self.assertFalse(hasattr(receipt, authority_name))
        for operation in (copy.copy, copy.deepcopy, pickle.dumps):
            with self.subTest(operation=operation.__name__):
                with self.assertRaisesRegex(TypeError, "not_serializable"):
                    operation(receipt)

        payload = receipt.to_dict()
        self.assertEqual(
            set(payload),
            {
                "schema_version",
                "stage",
                "source_kind",
                "reason",
                "execution_kind",
                "obligation_key",
                "owner_binding_sha256",
                "owner_plan_sha256",
                "owner_plan_config_sha256",
                "owner_budget_sha256",
                "source_receipt_sha256",
                "query_sha256",
                "scope_doc_ids",
                "scope_sha256",
                "evidence_store_sha256",
                "execution_config_sha256",
                "runtime_binding_sha256",
                "retrieval_obligation_sha256",
                "dense_receipt_sha256",
                "lexical_receipt_sha256",
                "fusion_receipt_sha256",
                "semantic_obligation_sha256",
                "semantic_receipt_sha256",
                "followup_outcome_sha256",
                "primary_receipt_sha256",
                "fallback_receipt_sha256",
                "fallback_authorized",
                "fallback_executed",
                "candidate_count",
                "supplied_count",
                "support_count",
                "call_performed",
                "prerequisite_sha256",
                "receipt_sha256",
            },
        )
        self.assertEqual(payload["stage"], "absence_confirmation")
        self.assertEqual(payload["call_performed"], False)
        forbidden = {
            "query",
            "evidence_id",
            "evidence_ids",
            "anchor",
            "text",
            "value",
            "parent",
            "context",
            "citation",
            "gold",
            "qrels",
            "timeout",
            "deadline",
            "action",
            "effect",
            "state",
            "ready",
            "abstain",
        }
        self.assertFalse(forbidden.intersection(payload))
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        for private_value in ("사업 예산은 얼마인가?", "gold-must-not-leak", "qrels"):
            self.assertNotIn(private_value, serialized)

    def test_reason_specific_proof_matrix_is_exact(self) -> None:
        retrieval_case = self._retrieval_case(name="proof-retrieval")
        retrieval = self._issue_retrieval(retrieval_case)
        semantic_case = self._derived_semantic_case(name="proof-semantic")
        semantic = self._issue_semantic(semantic_case)
        followup_case = self._followup_case(name="proof-followup")
        followup = self._issue_followup(followup_case, "$answer_support")

        retrieval_proofs = {
            "retrieval_obligation_sha256",
            "dense_receipt_sha256",
            "lexical_receipt_sha256",
            "fusion_receipt_sha256",
        }
        semantic_proofs = {
            "semantic_obligation_sha256",
            "semantic_receipt_sha256",
        }
        followup_proofs = {
            "followup_outcome_sha256",
            "primary_receipt_sha256",
            "fallback_receipt_sha256",
        }
        for name in retrieval_proofs:
            self.assertRegex(getattr(retrieval, name), r"^[0-9a-f]{64}$")
        self.assertEqual(
            (
                retrieval.retrieval_obligation_sha256,
                retrieval.dense_receipt_sha256,
                retrieval.lexical_receipt_sha256,
                retrieval.fusion_receipt_sha256,
            ),
            (
                retrieval_case[4].obligation_sha256,
                retrieval_case[5].receipt_sha256,
                retrieval_case[6].receipt_sha256,
                retrieval_case[7].receipt_sha256,
            ),
        )
        for name in semantic_proofs | followup_proofs:
            self.assertIsNone(getattr(retrieval, name))
        self.assertIsNone(retrieval.fallback_authorized)
        self.assertIsNone(retrieval.fallback_executed)

        for name in semantic_proofs:
            self.assertRegex(getattr(semantic, name), r"^[0-9a-f]{64}$")
        self.assertEqual(
            (
                semantic.semantic_obligation_sha256,
                semantic.semantic_receipt_sha256,
            ),
            (
                semantic_case[2].obligation_sha256,
                semantic_case[3].receipt_sha256,
            ),
        )
        for name in retrieval_proofs | followup_proofs:
            self.assertIsNone(getattr(semantic, name))
        self.assertIsNone(semantic.fallback_authorized)
        self.assertIsNone(semantic.fallback_executed)

        for name in followup_proofs:
            self.assertRegex(getattr(followup, name), r"^[0-9a-f]{64}$")
        expected_outcome_sha256 = sha256(
            json.dumps(
                followup_case["outcome"].to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(followup.followup_outcome_sha256, expected_outcome_sha256)
        self.assertEqual(followup.source_receipt_sha256, expected_outcome_sha256)
        self.assertEqual(
            followup.primary_receipt_sha256,
            followup_case["outcome"].primary.result_sha256,
        )
        self.assertEqual(
            followup.fallback_receipt_sha256,
            followup_case["outcome"].fallback.result_sha256,
        )
        for name in retrieval_proofs | semantic_proofs:
            self.assertIsNone(getattr(followup, name))
        self.assertIs(followup.fallback_authorized, True)
        self.assertIs(followup.fallback_executed, True)

        for receipt in (retrieval, semantic, followup):
            for name in (
                "owner_binding_sha256",
                "owner_plan_sha256",
                "owner_plan_config_sha256",
                "owner_budget_sha256",
                "source_receipt_sha256",
                "query_sha256",
                "scope_sha256",
                "evidence_store_sha256",
                "execution_config_sha256",
                "runtime_binding_sha256",
                "prerequisite_sha256",
                "receipt_sha256",
            ):
                self.assertRegex(getattr(receipt, name), r"^[0-9a-f]{64}$")

    def test_exact_repeat_validation_clone_rejection_and_concurrent_single_winner(self) -> None:
        case = self._retrieval_case(name="replay-concurrent")
        barrier = Barrier(9)

        def invoke():
            barrier.wait()
            return self._issue_retrieval(case)

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = tuple(pool.submit(invoke) for _ in range(8))
            barrier.wait()
            results = tuple(future.result(timeout=3) for future in futures)
        first = results[0]
        self.assertTrue(all(item is first for item in results))
        self.assertIs(self._issue_retrieval(case), first)
        orchestration.validate_absence_confirmation_receipt(
            receipt=first, store=case[1], config=case[2], runtime=case[3]
        )
        with self.assertRaises((TypeError, ValueError)):
            orchestration.validate_absence_confirmation_receipt(
                receipt=_clone_slots(first),
                store=case[1],
                config=case[2],
                runtime=case[3],
            )
        self.assertEqual(
            _calls(self.tempdir / "replay-concurrent-dense.log"), ("dense",)
        )
        self.assertEqual(
            _calls(self.tempdir / "replay-concurrent-lexical.log"), ("lexical",)
        )

    def test_exact_repeat_rejects_a_corrupted_cached_receipt(self) -> None:
        case = self._retrieval_case(name="cached-replay-tamper")
        receipt = self._issue_retrieval(case)
        object.__setattr__(receipt, "candidate_count", 1)
        try:
            with self.assertRaises(ValueError):
                self._issue_retrieval(case)
        finally:
            # Keep global weak-lifetime cleanup deterministic if the assertion
            # itself fails while exercising a vulnerable implementation.
            object.__setattr__(receipt, "candidate_count", 0)

    def test_visible_absence_authority_replacement_or_injection_cannot_authorize_clone(
        self,
    ) -> None:
        case = self._retrieval_case(name="absence-authority-mirror")
        receipt = self._issue_retrieval(case)
        clone = _clone_slots(receipt)
        visible = execution_contracts._ISSUED_ABSENCE_CONFIRMATION_AUTHORITIES
        key, original = next(
            (key, authority)
            for key, authority in tuple(visible.items())
            if authority.receipt is receipt
        )
        forged = replace(original, receipt=clone)

        visible[key] = forged
        try:
            with self.assertRaisesRegex(
                ValueError,
                "absence_confirmation_(runtime|completion)_authority_(required|drift)",
            ):
                orchestration.validate_absence_confirmation_receipt(
                    receipt=clone, store=case[1], config=case[2], runtime=case[3]
                )
        finally:
            visible[key] = original

        injected_key = (key[0] + 1, *key[1:])
        self.assertNotIn(injected_key, visible)
        visible[injected_key] = forged
        try:
            with self.assertRaisesRegex(
                ValueError,
                "absence_confirmation_(runtime|completion)_authority_(required|drift)",
            ):
                orchestration.validate_absence_confirmation_receipt(
                    receipt=clone, store=case[1], config=case[2], runtime=case[3]
                )
        finally:
            visible.pop(injected_key, None)

        orchestration.validate_absence_confirmation_receipt(
            receipt=receipt, store=case[1], config=case[2], runtime=case[3]
        )

    def test_validator_requires_exact_dependencies_without_provider_replay(self) -> None:
        case = self._retrieval_case(name="validator-exact")
        receipt = self._issue_retrieval(case)
        other = self._retrieval_case(name="validator-other")
        bad_dependencies = (
            {"store": type(case[1]).from_dict(case[1].to_dict())},
            {"config": type(case[2]).from_dict(case[2].to_dict())},
            {"runtime": other[3]},
        )
        base = {"receipt": receipt, "store": case[1], "config": case[2], "runtime": case[3]}
        for override in bad_dependencies:
            with self.subTest(dependency=tuple(override)):
                with self.assertRaises((TypeError, ValueError)):
                    orchestration.validate_absence_confirmation_receipt(
                        **{**base, **override}
                    )
        self.assertEqual(_calls(self.tempdir / "validator-exact-dense.log"), ("dense",))
        self.assertEqual(_calls(self.tempdir / "validator-exact-lexical.log"), ("lexical",))

    def test_prerequisite_gc_preserves_validation_and_root_gc_releases_history(self) -> None:
        case = self._retrieval_case(name="gc")
        bound, store, config, runtime, obligation, dense, lexical, fusion = case
        receipt = self._issue_retrieval(case)
        prerequisite_refs = tuple(ref(item) for item in (obligation, dense, lexical, fusion))
        root_ref = ref(bound)
        receipt_ref = ref(receipt)

        del case, obligation, dense, lexical, fusion
        gc.collect()
        self.assertTrue(all(item() is None for item in prerequisite_refs))
        orchestration.validate_absence_confirmation_receipt(
            receipt=receipt, store=store, config=config, runtime=runtime
        )

        del receipt, bound
        gc.collect()
        self.assertIsNone(root_ref())
        self.assertIsNone(receipt_ref())

    def test_normal_empty_fact_mints_bounded_no_candidate(self) -> None:
        (
            _bound,
            store,
            config,
            runtime,
            obligation,
            dense,
            lexical,
            fusion,
        ) = self._empty_retrieval_case()

        receipt = self._issue_retrieval(
            (_bound, store, config, runtime, obligation, dense, lexical, fusion)
        )

        self.assertEqual(receipt.reason, "bounded_no_candidate")
        self.assertEqual(receipt.source_kind, "fact")
        self.assertEqual(
            (receipt.candidate_count, receipt.supplied_count, receipt.support_count),
            (0, 0, 0),
        )
        self.assertFalse(receipt.call_performed)


if __name__ == "__main__":
    unittest.main()
