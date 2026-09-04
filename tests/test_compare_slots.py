from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
import json
import unittest

import numpy as np

from midprojectrag.evidence import Evidence, EvidenceStore, Locator, ProvenanceParent
from midprojectrag.orchestration import (
    BoundCompare,
    CatalogDocument,
    CatalogEntity,
    CompareBindingTrace,
    CompareCoverage,
    CompareFieldRegistry,
    CompareSlotState,
    DeterministicPlanner,
    PlanningCatalog,
    PlanningResult,
    PlanningTrace,
    build_compare_coverage,
    default_compare_field_registry,
    default_rule_registry,
    prepare_compare_slots,
)
from midprojectrag.orchestration.compare_coverage import (
    CompareDocumentCoverage,
    CompareSearchReceipt,
    CompareVerificationReceipt,
    execute_compare_slot_search,
    verify_compare_slot_search,
)
from midprojectrag.retrieval import Candidate, SearchResult
from midprojectrag.retrieval.dense import DenseChildLane
from midprojectrag.retrieval.fusion import HybridChildRetriever
from midprojectrag.retrieval.kiwi_bm25 import KiwiBM25Lane, KiwiTokenizer
from midprojectrag.runtime_integrity import EvaluationCase, RuntimeRequest, project_runtime
from midprojectrag.stacks.local.hf_embeddings import KureEmbeddingProvider


def _store(doc_ids=("doc-a", "doc-b", "doc-c")):
    parents = []
    evidence = {}
    for index, doc_id in enumerate(doc_ids, 1):
        texts = (
            f"{doc_id} 예산 100원",
            f"{doc_id} 수행기간 10일",
            f"{doc_id} 예산 200원",
        )
        parent_text = "\n".join(texts)
        parent = ProvenanceParent(
            doc_id,
            "pdf_page",
            parent_text,
            (f"block-{doc_id}",),
            Locator(page=index),
        )
        parents.append(parent)
        cursor = 0
        for name, text in zip(("budget", "duration", "conflict"), texts):
            start = parent_text.index(text, cursor)
            cursor = start + len(text)
            child = Evidence(
                doc_id,
                "text",
                text,
                parent.parent_id,
                (f"block-{doc_id}",),
                Locator(page=index, char_range=(start, cursor)),
            )
            evidence[(doc_id, name)] = child
    return EvidenceStore(parents, evidence.values()), evidence


def _catalog(doc_ids=("doc-a", "doc-b", "doc-c")):
    aliases = ("사업A", "사업B", "사업C")
    return PlanningCatalog.synthetic(
        "compare-fixture-v1",
        tuple(
            CatalogEntity(alias, alias, "business", (doc_id,), "business_alias")
            for alias, doc_id in zip(aliases, doc_ids)
        ),
    )


def _request(question="예산과 수행기간을 비교해줘", doc_ids=("doc-a", "doc-b")):
    return RuntimeRequest(
        question=question,
        document_scope={"mode": "explicit", "doc_ids": list(doc_ids)},
        options={"allow_global_fallback": True},
    )


def _result(store, values=(), *, lane="rrf", bundle=None, granularity="child",
            ranks=None, candidate_lane="rrf", candidate_granularity="child",
            doc_override=None, raw_trace=None):
    values = tuple(values)
    ranks = tuple(range(1, len(values) + 1)) if ranks is None else tuple(ranks)
    candidates = tuple(
        Candidate(
            value.evidence_id,
            value.doc_id if doc_override is None else doc_override,
            1.0 / rank,
            candidate_lane,
            rank,
            candidate_granularity,
        )
        for value, rank in zip(values, ranks)
    )
    trace = {
        "lane": lane,
        "granularity": granularity,
        "bundle_sha256": store.bundle_sha256 if bundle is None else bundle,
    }
    if raw_trace:
        trace.update(raw_trace)
    return SearchResult(candidates, trace)


def _canonical_hash(value):
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


class _FakeRetriever:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def search(self, query, *, dense_k, lexical_k, scope):
        self.calls.append((query, dense_k, lexical_k, scope))
        return self.result


class CompareSlotTests(unittest.TestCase):
    def setUp(self):
        self.store, self.evidence = _store()
        self.routing = default_rule_registry()
        self.catalog = _catalog()
        self.planner = DeterministicPlanner.for_test(self.routing, self.catalog)
        self.fields = default_compare_field_registry()
        self.request = _request()
        self.planning = self.planner.plan(self.request)
        self.bound = self.prepare(self.request, self.planning)

    def prepare(self, request, planning=None, *, store=None, planner=None):
        return prepare_compare_slots(
            request=request,
            planning=(planner or self.planner).plan(request) if planning is None else planning,
            store=self.store if store is None else store,
            planner=self.planner if planner is None else planner,
            compare_registry=self.fields,
        )

    def search_receipt(self, slot_key, result, *, bound=None):
        retriever = _FakeRetriever(result)
        receipt = execute_compare_slot_search(
            bound=self.bound if bound is None else bound,
            store=self.store,
            slot_key=slot_key,
            retriever=retriever,
        )
        self.assertEqual(len(retriever.calls), 1)
        return receipt

    def verification_receipt(self, receipt, *, bound=None):
        return verify_compare_slot_search(
            bound=self.bound if bound is None else bound,
            store=self.store,
            search_receipt=receipt,
            compare_registry=self.fields,
        )

    def coverage(self, *, results=None, verified=None, missing=None, contradicted=None,
                 bound=None):
        return build_compare_coverage(
            bound=self.bound if bound is None else bound,
            store=self.store,
            candidate_results={} if results is None else results,
            verified_evidence={} if verified is None else verified,
            missing_reasons={} if missing is None else missing,
            contradicted_evidence={} if contradicted is None else contradicted,
        )

    def full_inputs(self):
        values = {
            "doc-a.budget": self.evidence[("doc-a", "budget")],
            "doc-a.duration": self.evidence[("doc-a", "duration")],
            "doc-b.budget": self.evidence[("doc-b", "budget")],
            "doc-b.duration": self.evidence[("doc-b", "duration")],
        }
        results = {
            key: self.search_receipt(
                key,
                _result(self.store, (value,), raw_trace={"qrels": {"secret": 99}}),
            )
            for key, value in values.items()
        }
        verified = {
            key: self.verification_receipt(receipt)
            for key, receipt in results.items()
        }
        return values, results, verified

    def test_registry_is_sealed_hashed_and_selects_only_explicit_generic_fields(self):
        self.assertRegex(self.fields.config_sha256, r"^[0-9a-f]{64}$")
        self.assertEqual(
            tuple(rule.field for rule in self.fields.select("예산과 수행기간 비교")),
            ("budget", "duration"),
        )
        self.assertEqual(self.fields.select("두 사업의 차이를 비교"), ())
        self.assertNotIn("gold", str(self.fields.to_dict()).lower())
        with self.assertRaises(TypeError):
            CompareFieldRegistry()
        with self.assertRaises(TypeError):
            replace(self.fields, max_slots=999)

    def test_prepare_creates_complete_doc_major_matrix_and_disables_fallback(self):
        self.assertEqual(self.planning.plan.required_slots, ())
        self.assertFalse(self.planning.plan.allow_global_fallback)
        self.assertEqual(self.bound.trace.status, "ready")
        self.assertEqual(self.bound.trace.scope_source, "user_explicit")
        self.assertEqual(
            tuple(slot.key for slot in self.bound.plan.required_slots),
            (
                "doc-a.budget",
                "doc-a.duration",
                "doc-b.budget",
                "doc-b.duration",
            ),
        )
        self.assertFalse(self.bound.plan.allow_global_fallback)
        self.assertEqual(
            tuple(
                constraint.value
                for constraint in self.bound.plan.constraints
                if constraint.kind == "comparison_field"
            ),
            ("budget", "duration"),
        )
        self.assertNotEqual(
            self.bound.trace.base_plan_sha256,
            self.bound.trace.effective_plan_sha256,
        )
        trace = self.bound.trace.to_dict()
        self.assertNotIn("question", trace)
        self.assertNotIn("qrels", str(trace).lower())

    def test_three_documents_form_the_full_cartesian_matrix_deterministically(self):
        request = _request(doc_ids=("doc-c", "doc-a", "doc-b"))
        first = self.prepare(request)
        second = self.prepare(request)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(
            tuple(slot.key for slot in first.plan.required_slots),
            tuple(
                f"{doc_id}.{field}"
                for doc_id in ("doc-c", "doc-a", "doc-b")
                for field in ("budget", "duration")
            ),
        )

    def test_named_single_document_business_entities_are_valid_targets(self):
        request = RuntimeRequest(question="사업A와 사업B의 예산을 비교해줘")
        bound = self.prepare(request)
        self.assertEqual(bound.trace.scope_source, "named_business_entities")
        self.assertEqual(bound.plan.resolved_doc_ids, ("doc-a", "doc-b"))
        self.assertEqual(
            tuple(slot.key for slot in bound.plan.required_slots),
            ("doc-a.budget", "doc-b.budget"),
        )

    def test_unresolved_scope_target_and_field_states_never_create_slots(self):
        cases = (
            (_request(doc_ids=("doc-a",)), "compare_requires_multiple_documents"),
            (RuntimeRequest(question="예산을 비교해줘"), "compare_scope_unresolved"),
            (_request(question="두 문서의 차이를 비교해줘"), "compare_fields_unresolved"),
            (_request(doc_ids=("doc-a", "missing-doc")), "compare_document_not_in_store"),
        )
        for request, reason in cases:
            with self.subTest(reason=reason):
                bound = self.prepare(request)
                self.assertEqual(bound.trace.status, "unresolved")
                self.assertEqual(bound.trace.reason, reason)
                self.assertEqual(bound.plan.required_slots, ())
                self.assertFalse(bound.plan.allow_global_fallback)
                self.assertIn(reason, bound.plan.unresolved_constraints)
                with self.assertRaisesRegex(ValueError, "compare_binding_not_ready"):
                    self.coverage(bound=bound)

    def test_negated_field_and_only_particle_preserve_the_requested_axis(self):
        request = _request("예산은 비교하지 말고 수행기간만 비교해줘")
        bound = self.prepare(request)
        self.assertEqual(bound.trace.status, "ready")
        self.assertEqual(bound.trace.selected_fields, ("duration",))
        self.assertEqual(
            bound.trace.required_slot_keys,
            ("doc-a.duration", "doc-b.duration"),
        )
        retriever = _FakeRetriever(_result(self.store))
        execute_compare_slot_search(
            bound=bound,
            store=self.store,
            slot_key="doc-a.duration",
            retriever=retriever,
        )
        slot_query = retriever.calls[0][0]
        self.assertEqual(slot_query, "사업 기간")
        self.assertNotIn("예산", slot_query)
        self.assertNotIn("비교하지", slot_query)
        self.assertNotIn("말고", slot_query)
        self.assertNotIn("빼고", slot_query)

    def test_mixed_supported_and_unsupported_axes_fail_closed(self):
        for question in (
            "예산과 투입 인력을 비교해줘",
            "예산과 기술지원 SLA를 비교해줘",
            "예산과 대상 비교",
            "예산 및 항목 비교",
            "예산과 기준 비교",
        ):
            with self.subTest(question=question):
                bound = self.prepare(_request(question))
                self.assertEqual(bound.trace.status, "unresolved")
                self.assertEqual(bound.trace.reason, "compare_fields_unsupported")
                self.assertEqual(bound.plan.required_slots, ())

    def test_unmatched_named_compare_targets_fail_closed(self):
        for question in (
            "사업A와 사업B와 사업Z의 예산을 비교해줘",
            "사업A, 사업B, 미등록사업의 예산 차이를 비교해줘",
        ):
            request = RuntimeRequest(
                question=question,
                document_scope={"mode": "all"},
                options={"allow_global_fallback": True},
            )
            with self.subTest(question=question):
                bound = self.prepare(request)
                self.assertEqual(bound.trace.status, "unresolved")
                self.assertEqual(bound.trace.reason, "compare_targets_unresolved")
                self.assertEqual(bound.plan.required_slots, ())

    def test_explicit_scope_cannot_silently_truncate_a_named_compare_target(self):
        request = _request(
            "사업A와 사업B와 사업C의 예산을 비교해줘",
            doc_ids=("doc-a", "doc-b"),
        )
        bound = self.prepare(request)
        self.assertEqual(bound.trace.status, "unresolved")
        self.assertEqual(bound.trace.reason, "compare_targets_unresolved")
        self.assertEqual(bound.trace.resolved_doc_ids, ("doc-a", "doc-b"))
        self.assertEqual(bound.plan.required_slots, ())

    def test_repeated_entity_word_cannot_hide_an_unsupported_axis(self):
        catalog = PlanningCatalog.synthetic(
            "repeated-entity-field-v1",
            (
                CatalogEntity("품질", "품질", "business", ("doc-a",), "business_alias"),
                CatalogEntity("사업B", "사업B", "business", ("doc-b",), "business_alias"),
            ),
        )
        planner = DeterministicPlanner.for_test(self.routing, catalog)
        request = RuntimeRequest(
            question="품질과 사업B의 예산과 품질을 비교해줘",
            document_scope={"mode": "all"},
            options={"allow_global_fallback": True},
        )
        bound = self.prepare(request, planner=planner)
        self.assertEqual(bound.trace.status, "unresolved")
        self.assertEqual(bound.trace.reason, "compare_fields_unsupported")
        self.assertEqual(bound.plan.required_slots, ())

    def test_multi_document_agency_alias_is_not_silently_compared(self):
        catalog = PlanningCatalog.synthetic(
            "agency-ambiguous-v1",
            (
                CatalogEntity(
                    "공통기관", "공통기관", "agency", ("doc-a", "doc-b"), "agency_alias"
                ),
            ),
        )
        planner = DeterministicPlanner.for_test(self.routing, catalog)
        request = RuntimeRequest(question="공통기관 사업의 예산 차이를 비교해줘")
        bound = self.prepare(request, planner=planner)
        self.assertEqual(bound.trace.reason, "compare_targets_ambiguous")
        self.assertEqual(bound.plan.required_slots, ())

    def test_entity_names_cannot_supply_the_comparison_field(self):
        catalog = PlanningCatalog.synthetic(
            "entity-field-contamination-v1",
            (
                CatalogEntity(
                    "유지보수 사업A",
                    "유지보수 사업A",
                    "business",
                    ("doc-a",),
                    "business_alias",
                ),
                CatalogEntity(
                    "사업B", "사업B", "business", ("doc-b",), "business_alias"
                ),
            ),
        )
        planner = DeterministicPlanner.for_test(self.routing, catalog)
        request = RuntimeRequest(
            question="유지보수 사업A와 사업B의 차이를 비교해줘"
        )
        bound = self.prepare(request, planner=planner)
        self.assertEqual(bound.trace.reason, "compare_fields_unresolved")
        self.assertEqual(bound.trace.selected_fields, ())

    def test_metadata_filters_require_resolution_and_filtered_scope_receipts(self):
        unsupported = RuntimeRequest(
            question="예산을 비교해줘",
            document_scope={"mode": "explicit", "doc_ids": ["doc-a", "doc-b"]},
            metadata_filters=(
                {"field": "not_supported", "operator": "eq", "value": "x"},
            ),
        )
        unsupported_bound = self.prepare(unsupported)
        self.assertEqual(
            unsupported_bound.trace.reason, "compare_metadata_unresolved"
        )
        supported = RuntimeRequest(
            question="예산을 비교해줘",
            document_scope={"mode": "explicit", "doc_ids": ["doc-a", "doc-b"]},
            metadata_filters=(
                {"field": "business_amount", "operator": "ge", "value": 1},
            ),
        )
        supported_bound = self.prepare(supported)
        self.assertEqual(
            supported_bound.trace.reason,
            "compare_metadata_scope_receipt_required",
        )
        self.assertEqual(supported_bound.plan.required_slots, ())

    def test_planning_is_replayed_and_evaluator_fields_cannot_select_targets(self):
        row_a = {
            **self.request.to_dict(),
            "required_doc_ids": ["gold-a"],
            "qrels": {"gold-evidence": 1},
            "reference_answer": "secret-a",
        }
        row_b = {
            **self.request.to_dict(),
            "required_doc_ids": ["gold-b"],
            "qrels": {"other": 99},
            "reference_answer": "secret-b",
        }
        request_a = project_runtime(row_a)
        request_b = project_runtime(row_b)
        self.assertEqual(request_a, request_b)
        self.assertEqual(self.prepare(request_a).to_dict(), self.prepare(request_b).to_dict())
        with self.assertRaisesRegex(TypeError, "runtime_request_required"):
            prepare_compare_slots(
                request=EvaluationCase(request_a, required_doc_ids=("gold-a",)),
                planning=self.planner.plan(request_a),
                store=self.store,
                planner=self.planner,
                compare_registry=self.fields,
            )

        forged_plan = replace(
            self.planning.plan,
            resolved_doc_ids=("doc-a", "doc-c"),
        )
        forged_trace = replace(
            self.planning.trace,
            resolved_doc_ids=("doc-a", "doc-c"),
        )
        forged = PlanningResult(forged_plan, forged_trace)
        with self.assertRaisesRegex(ValueError, "compare_planning_replay_mismatch"):
            self.prepare(self.request, forged)

    def test_binding_and_coverage_authority_objects_are_factory_sealed(self):
        with self.assertRaises(TypeError):
            BoundCompare(self.planning, self.bound.plan, self.bound.trace, "0" * 64)
        with self.assertRaises(TypeError):
            CompareSlotState()
        with self.assertRaises(TypeError):
            CompareCoverage()
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            self.bound.binding_sha256 = "0" * 64
        with self.assertRaises(TypeError):
            replace(self.bound, binding_sha256="0" * 64)

        issued = self.coverage()
        raw = object.__new__(CompareCoverage)
        for name in issued.__dataclass_fields__:
            object.__setattr__(raw, name, getattr(issued, name))
        with self.assertRaisesRegex(
            ValueError, "compare_coverage_runtime_authority_required"
        ):
            raw._validate(self.bound, self.store)

    def test_all_unsearched_coverage_cannot_forge_completion_with_recomputed_hash(self):
        coverage = self.coverage()
        self.assertEqual(
            tuple(state.status for state in coverage.slots),
            ("unsearched",) * 4,
        )

        # Reproduce the P1 exactly: keep every slot/document unsearched, forge
        # only the top-level completion projection, then recompute its public
        # digest. The factory identity still binds the original complete tree.
        forged_values = {
            "verified_slot_count": coverage.required_slot_count,
            "open_slot_count": 0,
            "accounted_slot_count": coverage.required_slot_count,
            "covered_document_ids": self.bound.plan.resolved_doc_ids,
            "accounted_document_ids": self.bound.plan.resolved_doc_ids,
            "slot_coverage_ratio": 1.0,
            "document_coverage_ratio": 1.0,
            "accounted_complete": True,
            "coverage_complete": True,
            "normal_stop_allowed": True,
            "abstain_required": False,
            "answerability": "complete",
        }
        for name, value in forged_values.items():
            object.__setattr__(coverage, name, value)
        unsigned = coverage.to_dict()
        unsigned.pop("coverage_sha256")
        object.__setattr__(coverage, "coverage_sha256", _canonical_hash(unsigned))

        with self.assertRaisesRegex(
            ValueError, "compare_coverage_runtime_authority_drift"
        ):
            coverage._validate(self.bound, self.store)

    def test_coverage_validation_rejects_post_mint_nested_state_drift(self):
        coverage = self.coverage()
        state = coverage.slots[0]
        object.__setattr__(state, "status", "candidate")
        object.__setattr__(state, "search_result_sha256", "0" * 64)
        unsigned_state = state.to_dict()
        unsigned_state.pop("slot_sha256")
        object.__setattr__(state, "slot_sha256", _canonical_hash(unsigned_state))
        unsigned_coverage = coverage.to_dict()
        unsigned_coverage.pop("coverage_sha256")
        object.__setattr__(
            coverage,
            "coverage_sha256",
            _canonical_hash(unsigned_coverage),
        )

        with self.assertRaisesRegex(
            ValueError, "compare_coverage_runtime_authority_drift"
        ):
            coverage._validate(self.bound, self.store)

    def test_unsearched_and_candidate_states_never_complete_coverage(self):
        initial = self.coverage()
        self.assertEqual(initial.open_slot_count, 4)
        self.assertEqual(
            tuple(state.status for state in initial.slots),
            ("unsearched",) * 4,
        )
        self.assertFalse(initial.accounted_complete)
        self.assertFalse(initial.coverage_complete)
        self.assertFalse(initial.normal_stop_allowed)
        empty_results = {
            slot.key: self.search_receipt(slot.key, _result(self.store))
            for slot in self.bound.plan.required_slots
        }
        searched = self.coverage(results=empty_results)
        self.assertEqual(
            tuple(state.status for state in searched.slots),
            ("candidate",) * 4,
        )
        self.assertFalse(searched.normal_stop_allowed)
        self.assertEqual(searched.slot_coverage_ratio, 0.0)

    def test_field_relevance_receipts_cannot_mint_terminal_verification(self):
        _values, results, verified = self.full_inputs()
        partial_verified = dict(verified)
        partial_verified.pop("doc-a.duration")
        partial = self.coverage(results=results, verified=partial_verified)
        self.assertEqual(partial.verified_slot_count, 0)
        self.assertEqual(partial.open_slot_count, 4)
        self.assertEqual(partial.covered_document_ids, ())
        self.assertFalse(partial.normal_stop_allowed)

        complete = self.coverage(results=results, verified=verified)
        self.assertEqual(complete.covered_document_ids, ())
        self.assertEqual(complete.slot_coverage_ratio, 0.0)
        self.assertEqual(complete.document_coverage_ratio, 0.0)
        self.assertFalse(complete.accounted_complete)
        self.assertFalse(complete.coverage_complete)
        self.assertFalse(complete.normal_stop_allowed)
        self.assertFalse(complete.abstain_required)
        self.assertEqual(complete.answerability, "in_progress")
        self.assertEqual(
            tuple(state.status for state in complete.slots),
            ("candidate",) * 4,
        )

    def test_field_words_in_non_answers_never_count_as_verified_values(self):
        parents = []
        children = {}
        weak_texts = {
            "budget": "예산 정보는 별도 문서를 참고하세요",
            "duration": "사업 기간 정보는 제공되지 않습니다",
        }
        for page, doc_id in enumerate(("doc-a", "doc-b"), 1):
            parent_text = "\n".join(weak_texts.values())
            parent = ProvenanceParent(
                doc_id,
                "pdf_page",
                parent_text,
                (f"weak-block-{doc_id}",),
                Locator(page=page),
            )
            parents.append(parent)
            for field, text in weak_texts.items():
                start = parent_text.index(text)
                children[(doc_id, field)] = Evidence(
                    doc_id,
                    "text",
                    text,
                    parent.parent_id,
                    (f"weak-block-{doc_id}",),
                    Locator(page=page, char_range=(start, start + len(text))),
                )
        weak_store = EvidenceStore(parents, children.values())
        bound = prepare_compare_slots(
            request=self.request,
            planning=self.planning,
            store=weak_store,
            planner=self.planner,
            compare_registry=self.fields,
        )
        results = {}
        verifications = {}
        for slot in bound.plan.required_slots:
            evidence = children[(slot.doc_id, slot.field)]
            receipt = execute_compare_slot_search(
                bound=bound,
                store=weak_store,
                slot_key=slot.key,
                retriever=_FakeRetriever(_result(weak_store, (evidence,))),
            )
            results[slot.key] = receipt
            verification = verify_compare_slot_search(
                bound=bound,
                store=weak_store,
                search_receipt=receipt,
                compare_registry=self.fields,
            )
            self.assertEqual(
                verification.field_match_evidence_ids,
                (evidence.evidence_id,),
            )
            verifications[slot.key] = verification
        coverage = build_compare_coverage(
            bound=bound,
            store=weak_store,
            candidate_results=results,
            verified_evidence=verifications,
            missing_reasons={},
            contradicted_evidence={},
        )
        self.assertEqual(coverage.verified_slot_count, 0)
        self.assertEqual(tuple(state.status for state in coverage.slots), ("candidate",) * 4)
        self.assertFalse(coverage.normal_stop_allowed)

    def test_missing_observation_is_visible_but_cannot_finish_without_absence_receipt(self):
        _values, results, verified = self.full_inputs()
        missing_key = "doc-b.duration"
        results[missing_key] = self.search_receipt(
            missing_key, _result(self.store)
        )
        verified.pop(missing_key)
        coverage = self.coverage(
            results=results,
            verified=verified,
            missing={missing_key: "no_candidate_yet"},
        )
        self.assertEqual(coverage.missing_slot_count, 1)
        self.assertIn(missing_key, coverage.documents[1].missing_slot_keys)
        self.assertEqual(coverage.open_slot_count, 4)
        self.assertFalse(coverage.coverage_complete)
        self.assertFalse(coverage.normal_stop_allowed)
        self.assertFalse(coverage.abstain_required)
        self.assertEqual(coverage.answerability, "in_progress")
        self.assertFalse(next(
            state.absence_confirmed
            for state in coverage.slots
            if state.slot.key == missing_key
        ))

    def test_untyped_contradiction_cannot_be_promoted(self):
        _values, results, verified = self.full_inputs()
        key = "doc-a.budget"
        conflict = self.evidence[("doc-a", "conflict")]
        first = self.evidence[("doc-a", "budget")]
        results[key] = self.search_receipt(
            key, _result(self.store, (first, conflict))
        )
        verified[key] = self.verification_receipt(results[key])
        with self.assertRaisesRegex(ValueError, "contradiction_receipt_required"):
            self.coverage(
                results=results,
                verified=verified,
                contradicted={key: (first.evidence_id, conflict.evidence_id)},
            )

    def test_candidate_results_are_store_child_scope_rank_and_document_bound(self):
        value = self.evidence[("doc-a", "budget")]
        key = "doc-a.budget"
        invalid_results = (
            _result(self.store, (value,), bundle="0" * 64),
            _result(self.store, (value,), granularity="page"),
            _result(self.store, (value,), lane="provider-secret"),
            _result(self.store, (value,), ranks=(2,)),
            _result(self.store, (value,), candidate_lane="provider-secret"),
            _result(self.store, (value,), candidate_granularity="page"),
            _result(self.store, (value,), doc_override="doc-b"),
            _result(
                self.store,
                (value,),
                lane="dense",
                candidate_lane="lexical",
            ),
        )
        patterns = (
            "bundle",
            "granularity",
            "lane",
            "rank_or_granularity",
            "candidate_lane",
            "rank_or_granularity",
            "result_document",
            "result_lane",
        )
        for result, pattern in zip(invalid_results, patterns):
            with self.subTest(pattern=pattern), self.assertRaisesRegex(ValueError, pattern):
                self.search_receipt(key, result)

        other_doc = self.evidence[("doc-b", "budget")]
        with self.assertRaisesRegex(ValueError, "result_document"):
            self.search_receipt(key, _result(self.store, (other_doc,)))

    def test_page_candidate_unknown_ids_and_provider_trace_bodies_are_rejected_or_dropped(self):
        parent = self.store.parent(self.evidence[("doc-a", "budget")].parent_id)
        page = Evidence(
            "doc-a",
            "page",
            parent.text,
            parent.parent_id,
            parent.source_block_ids,
            Locator(page=parent.locator.page, char_range=(0, len(parent.text))),
        )
        page_store = EvidenceStore(self.store.parents, self.store.evidence + (page,))
        page_result = _result(page_store, (page,))
        page_bound = self.prepare(self.request, store=page_store)
        with self.assertRaisesRegex(ValueError, "candidate_evidence_mismatch"):
            execute_compare_slot_search(
                bound=page_bound,
                store=page_store,
                slot_key="doc-a.budget",
                retriever=_FakeRetriever(page_result),
            )

        value = self.evidence[("doc-a", "budget")]
        _, results, verified = self.full_inputs()
        results["doc-a.budget"] = self.search_receipt(
            "doc-a.budget",
            _result(
                self.store,
                (value,),
                raw_trace={
                    "question": "secret question",
                    "qrels": {value.evidence_id: 99},
                    "expected": {"answer": "secret"},
                },
            ),
        )
        verified["doc-a.budget"] = self.verification_receipt(
            results["doc-a.budget"]
        )
        coverage = self.coverage(results=results, verified=verified)
        serialized = str(coverage.to_dict()).lower()
        self.assertNotIn("secret", serialized)
        self.assertNotIn("qrels", serialized)
        self.assertNotIn("expected", serialized)

    def test_raw_and_cross_slot_authority_inputs_fail_closed(self):
        value = self.evidence[("doc-a", "budget")]
        key = "doc-a.budget"
        result = _result(self.store, (value,))
        with self.assertRaisesRegex(TypeError, "compare_search_receipt_required"):
            self.coverage(results={key: result})

        receipt = self.search_receipt(key, result)
        with self.assertRaisesRegex(TypeError, "compare_verification_receipt_required"):
            self.coverage(results={key: receipt}, verified={key: (value.evidence_id,)})
        with self.assertRaisesRegex(ValueError, "unknown_compare_slot_key"):
            self.coverage(results={"unknown.slot": receipt})
        with self.assertRaisesRegex(ValueError, "search_receipt_slot_mismatch"):
            self.coverage(results={"doc-a.duration": receipt})
        with self.assertRaisesRegex(ValueError, "invalid_compare_missing_reason"):
            self.coverage(
                results={key: receipt}, missing={key: "arbitrary_reason"}
            )
        with self.assertRaisesRegex(ValueError, "missing_reason_candidate_mismatch"):
            self.coverage(results={key: receipt}, missing={key: "no_candidate_yet"})

    def test_field_bound_verification_blocks_cross_field_false_completion(self):
        budget = self.evidence[("doc-a", "budget")]
        duration = self.evidence[("doc-a", "duration")]
        budget_search = self.search_receipt(
            "doc-a.budget", _result(self.store, (duration,))
        )
        duration_search = self.search_receipt(
            "doc-a.duration", _result(self.store, (budget,))
        )
        budget_verification = self.verification_receipt(budget_search)
        duration_verification = self.verification_receipt(duration_search)
        self.assertEqual(budget_verification.field_match_evidence_ids, ())
        self.assertEqual(duration_verification.field_match_evidence_ids, ())
        coverage = self.coverage(
            results={
                "doc-a.budget": budget_search,
                "doc-a.duration": duration_search,
            },
            verified={
                "doc-a.budget": budget_verification,
                "doc-a.duration": duration_verification,
            },
        )
        self.assertEqual(coverage.verified_slot_count, 0)
        self.assertFalse(coverage.normal_stop_allowed)

        valid_budget_search = self.search_receipt(
            "doc-a.budget", _result(self.store, (budget,))
        )
        valid_budget_verification = self.verification_receipt(valid_budget_search)
        self.assertEqual(
            valid_budget_verification.field_match_evidence_ids,
            (budget.evidence_id,),
        )
        with self.assertRaisesRegex(ValueError, "verification_slot_mismatch"):
            self.coverage(
                results={"doc-a.duration": duration_search},
                verified={"doc-a.duration": valid_budget_verification},
            )

    def test_search_receipt_binds_slot_query_budget_scope_action_and_trace(self):
        budget_retriever = _FakeRetriever(
            _result(
                self.store,
                (self.evidence[("doc-a", "budget")],),
                raw_trace={"artifact_sha256": "2" * 64},
            )
        )
        duration_retriever = _FakeRetriever(
            _result(self.store, (self.evidence[("doc-a", "duration")],))
        )
        budget_receipt = execute_compare_slot_search(
            bound=self.bound,
            store=self.store,
            slot_key="doc-a.budget",
            retriever=budget_retriever,
        )
        duration_receipt = execute_compare_slot_search(
            bound=self.bound,
            store=self.store,
            slot_key="doc-a.duration",
            retriever=duration_retriever,
        )
        budget_query, dense_k, lexical_k, scope = budget_retriever.calls[0]
        duration_query = duration_retriever.calls[0][0]
        self.assertEqual(budget_query, "예산")
        self.assertEqual(duration_query, "사업 기간")
        self.assertNotEqual(budget_query, duration_query)
        self.assertNotIn("comparison_field", budget_query)
        self.assertEqual((dense_k, lexical_k), (13, 13))
        self.assertEqual(scope.doc_ids, frozenset({"doc-a"}))
        self.assertEqual(budget_receipt.scope_doc_ids, ("doc-a",))
        self.assertEqual((budget_receipt.slot_ordinal, budget_receipt.slot_count), (1, 4))
        self.assertEqual(budget_receipt.budget_policy, "even_slot_partition_v1")
        self.assertEqual(budget_receipt.action, "hybrid_child_search")
        self.assertEqual(budget_receipt.retriever_profile, "synthetic_test_fixture")
        self.assertRegex(budget_receipt.source_trace_sha256, r"^[0-9a-f]{64}$")
        with self.assertRaises(TypeError):
            CompareSearchReceipt()
        with self.assertRaises(TypeError):
            replace(budget_receipt, dense_k=999)

        _values, all_receipts, _matches = self.full_inputs()
        self.assertEqual(
            sum(receipt.dense_k for receipt in all_receipts.values()),
            self.bound.plan.dense_k,
        )
        self.assertEqual(
            sum(receipt.lexical_k for receipt in all_receipts.values()),
            self.bound.plan.lexical_k,
        )

    def test_production_retriever_is_rejected_before_it_observes_the_query(self):
        catalog = PlanningCatalog.from_metadata(
            "compare-production-v1",
            (
                CatalogDocument("doc-a", "사업A"),
                CatalogDocument("doc-b", "사업B"),
            ),
        )
        planner = DeterministicPlanner(self.routing, catalog)
        request = _request()
        bound = self.prepare(request, planner=planner)
        retriever = _FakeRetriever(
            _result(self.store, (self.evidence[("doc-a", "budget")],))
        )
        with self.assertRaisesRegex(ValueError, "production_retriever_required"):
            execute_compare_slot_search(
                bound=bound,
                store=self.store,
                slot_key="doc-a.budget",
                retriever=retriever,
            )
        self.assertEqual(retriever.calls, [])

    def test_exact_but_raw_hybrid_cannot_mint_a_production_search_receipt(self):
        catalog = PlanningCatalog.from_metadata(
            "compare-production-raw-hybrid-v1",
            (
                CatalogDocument("doc-a", "사업A"),
                CatalogDocument("doc-b", "사업B"),
            ),
        )
        planner = DeterministicPlanner(self.routing, catalog)
        bound = self.prepare(_request(), planner=planner)
        provider = KureEmbeddingProvider(batch_size=2, device="cpu")
        vectors = np.zeros((len(self.store.candidates()), 1024), dtype=np.float32)
        vectors[:, 0] = 1
        dense = DenseChildLane._from_verified(
            self.store,
            vectors,
            provider,
            artifact_sha256="1" * 64,
        )
        tokenizer = KiwiTokenizer()
        lexical = KiwiBM25Lane.build(self.store, tokenizer)
        raw_hybrid = HybridChildRetriever(self.store, dense, lexical)
        with self.assertRaisesRegex(ValueError, "hybrid_production_binding_required"):
            execute_compare_slot_search(
                bound=bound,
                store=self.store,
                slot_key="doc-a.budget",
                retriever=raw_hybrid,
            )
        self.assertIsNone(provider._encoder)
        self.assertIsNone(provider._counter._tokenizer)

    def test_raw_or_mutated_bound_compare_cannot_downgrade_production_authority(self):
        catalog = PlanningCatalog.from_metadata(
            "compare-production-bound-authority-v1",
            (
                CatalogDocument("doc-a", "사업A"),
                CatalogDocument("doc-b", "사업B"),
            ),
        )
        planner = DeterministicPlanner(self.routing, catalog)
        request = _request()
        production_bound = self.prepare(request, planner=planner)
        self.assertEqual(production_bound.trace.execution_kind, "production")
        self.assertEqual(
            production_bound.trace.catalog_source_kind,
            "production_metadata",
        )
        self.assertEqual(
            production_bound.trace.catalog_source_sha256,
            catalog.source_sha256,
        )
        self.assertEqual(
            production_bound.trace.planning_trace_sha256,
            _canonical_hash(production_bound.planning.trace.to_dict()),
        )
        self.assertEqual(
            production_bound.trace.planning_result_sha256,
            _canonical_hash(production_bound.planning.to_dict()),
        )

        downgraded_trace = PlanningTrace(
            **{
                **production_bound.planning.trace.to_dict(),
                "catalog_source_kind": "synthetic_fixture",
                "catalog_source_sha256": "0" * 64,
                "execution_kind": "synthetic",
            }
        )
        downgraded_planning = PlanningResult(
            production_bound.planning.plan,
            downgraded_trace,
        )

        raw_forgery = object.__new__(BoundCompare)
        for name, value in (
            ("planning", downgraded_planning),
            ("plan", production_bound.plan),
            ("trace", production_bound.trace),
            ("binding_sha256", production_bound.binding_sha256),
        ):
            object.__setattr__(raw_forgery, name, value)
        retriever = _FakeRetriever(
            _result(self.store, (self.evidence[("doc-a", "budget")],))
        )
        with self.assertRaisesRegex(
            ValueError, "bound_compare_runtime_authority_required"
        ):
            execute_compare_slot_search(
                bound=raw_forgery,
                store=self.store,
                slot_key="doc-a.budget",
                retriever=retriever,
            )
        self.assertEqual(retriever.calls, [])
        with self.assertRaisesRegex(
            ValueError, "bound_compare_runtime_authority_required"
        ):
            build_compare_coverage(
                bound=raw_forgery,
                store=self.store,
                candidate_results={},
                verified_evidence={},
                missing_reasons={},
                contradicted_evidence={},
            )

        # A factory-issued identity also loses authority if its nested planning
        # result is replaced after creation via object.__setattr__.
        mutated_bound = self.prepare(request, planner=planner)
        object.__setattr__(mutated_bound, "planning", downgraded_planning)
        retriever = _FakeRetriever(
            _result(self.store, (self.evidence[("doc-a", "budget")],))
        )
        with self.assertRaisesRegex(
            ValueError, "bound_compare_nested_identity_drift"
        ):
            execute_compare_slot_search(
                bound=mutated_bound,
                store=self.store,
                slot_key="doc-a.budget",
                retriever=retriever,
            )
        self.assertEqual(retriever.calls, [])

    def test_bound_compare_rejects_equal_payload_nested_identity_replacement(self):
        mutations = (
            (
                "planning",
                lambda bound: object.__setattr__(
                    bound,
                    "planning",
                    PlanningResult(bound.planning.plan, bound.planning.trace),
                ),
                "bound_compare_nested_identity_drift",
            ),
            (
                "effective_plan",
                lambda bound: object.__setattr__(bound, "plan", deepcopy(bound.plan)),
                "bound_compare_nested_identity_drift",
            ),
            (
                "binding_trace",
                lambda bound: object.__setattr__(
                    bound, "trace", deepcopy(bound.trace)
                ),
                "bound_compare_nested_identity_drift",
            ),
            (
                "planning_plan",
                lambda bound: object.__setattr__(
                    bound.planning, "plan", deepcopy(bound.planning.plan)
                ),
                "bound_compare_planning_identity_drift",
            ),
            (
                "planning_trace",
                lambda bound: object.__setattr__(
                    bound.planning, "trace", deepcopy(bound.planning.trace)
                ),
                "bound_compare_planning_identity_drift",
            ),
        )
        for name, mutate, error in mutations:
            with self.subTest(name=name):
                bound = self.prepare(self.request)
                before = deepcopy(bound.to_dict())
                mutate(bound)
                self.assertEqual(bound.to_dict(), before)
                retriever = _FakeRetriever(
                    _result(self.store, (self.evidence[("doc-a", "budget")],))
                )
                with self.assertRaisesRegex(ValueError, error):
                    execute_compare_slot_search(
                        bound=bound,
                        store=self.store,
                        slot_key="doc-a.budget",
                        retriever=retriever,
                    )
                self.assertEqual(retriever.calls, [])

    def test_closed_authority_dto_round_trips_and_rejects_shape_drift(self):
        _values, results, verified = self.full_inputs()
        coverage = self.coverage(results=results, verified=verified)
        registry = CompareFieldRegistry.from_dict(deepcopy(self.fields.to_dict()))
        self.assertEqual(registry, self.fields)
        trace = CompareBindingTrace.from_dict(deepcopy(self.bound.trace.to_dict()))
        self.assertEqual(trace, self.bound.trace)
        rebound = BoundCompare.from_dict(
            deepcopy(self.bound.to_dict()),
            request=self.request,
            planner=self.planner,
            store=self.store,
            compare_registry=self.fields,
        )
        self.assertEqual(rebound.to_dict(), self.bound.to_dict())

        key = "doc-a.budget"
        replay_raw = _result(self.store, (self.evidence[("doc-a", "budget")],))
        replay_receipt = self.search_receipt(key, replay_raw)
        restored_search = CompareSearchReceipt.from_dict(
            deepcopy(replay_receipt.to_dict()),
            bound=self.bound,
            store=self.store,
            retriever=_FakeRetriever(replay_raw),
        )
        self.assertEqual(restored_search.to_dict(), replay_receipt.to_dict())
        search = results[key]
        verification = CompareVerificationReceipt.from_dict(
            deepcopy(verified[key].to_dict()),
            bound=self.bound,
            store=self.store,
            search_receipt=search,
            compare_registry=self.fields,
        )
        state_raw = next(
            item for item in coverage.to_dict()["slots"] if item["slot"]["key"] == key
        )
        state = CompareSlotState.from_dict(
            deepcopy(state_raw),
            search_receipt=search,
            verification_receipt=verification,
        )
        self.assertEqual(state.to_dict(), state_raw)
        document_raw = coverage.to_dict()["documents"][0]
        doc_states = tuple(item for item in coverage.slots if item.slot.doc_id == "doc-a")
        document = CompareDocumentCoverage.from_dict(
            deepcopy(document_raw), states=doc_states
        )
        self.assertEqual(document.to_dict(), document_raw)
        restored = CompareCoverage.from_dict(
            deepcopy(coverage.to_dict()),
            bound=self.bound,
            store=self.store,
            candidate_results=results,
            verified_evidence=verified,
        )
        self.assertEqual(restored.to_dict(), coverage.to_dict())

        parser_cases = (
            (self.fields.to_dict(), CompareFieldRegistry.from_dict, {}),
            (self.bound.trace.to_dict(), CompareBindingTrace.from_dict, {}),
            (
                self.bound.to_dict(),
                BoundCompare.from_dict,
                {
                    "request": self.request,
                    "planner": self.planner,
                    "store": self.store,
                    "compare_registry": self.fields,
                },
            ),
            (
                replay_receipt.to_dict(),
                CompareSearchReceipt.from_dict,
                {
                    "bound": self.bound,
                    "store": self.store,
                    "retriever": _FakeRetriever(replay_raw),
                },
            ),
            (
                verified[key].to_dict(),
                CompareVerificationReceipt.from_dict,
                {
                    "bound": self.bound,
                    "store": self.store,
                    "search_receipt": results[key],
                    "compare_registry": self.fields,
                },
            ),
            (
                state_raw,
                CompareSlotState.from_dict,
                {
                    "search_receipt": results[key],
                    "verification_receipt": verified[key],
                },
            ),
            (
                document_raw,
                CompareDocumentCoverage.from_dict,
                {"states": doc_states},
            ),
            (
                coverage.to_dict(),
                CompareCoverage.from_dict,
                {
                    "bound": self.bound,
                    "store": self.store,
                    "candidate_results": results,
                    "verified_evidence": verified,
                },
            ),
        )
        for raw, parser, kwargs in parser_cases:
            with self.subTest(parser=parser.__qualname__):
                extra = deepcopy(raw)
                extra["unexpected"] = True
                with self.assertRaisesRegex((TypeError, ValueError), "fields"):
                    parser(extra, **kwargs)
                missing = deepcopy(raw)
                missing.pop(next(iter(missing)))
                with self.assertRaisesRegex((TypeError, ValueError), "fields"):
                    parser(missing, **kwargs)

    def test_invalid_search_receipt_replay_has_zero_retrieval_side_effects(self):
        key = "doc-a.budget"
        raw_result = _result(self.store, (self.evidence[("doc-a", "budget")],))
        receipt = self.search_receipt(key, raw_result)
        mutations = {
            "action": "evil_action",
            "dense_k": 999,
            "scope_doc_ids": ["doc-b"],
            "binding_sha256": "0" * 64,
            "receipt_sha256": "0" * 64,
        }
        for field, replacement in mutations.items():
            with self.subTest(field=field):
                payload = deepcopy(receipt.to_dict())
                payload[field] = replacement
                retriever = _FakeRetriever(raw_result)
                with self.assertRaises((TypeError, ValueError)):
                    CompareSearchReceipt.from_dict(
                        payload,
                        bound=self.bound,
                        store=self.store,
                        retriever=retriever,
                    )
                self.assertEqual(retriever.calls, [])

        trace_mutations = {
            "candidate_count": 999.0,
            "schema_version": "9.9",
            "trace_projection": "evil",
        }
        for field, replacement in trace_mutations.items():
            with self.subTest(trace_field=field):
                payload = deepcopy(receipt.to_dict())
                payload["result"]["trace"][field] = replacement
                payload["result_sha256"] = _canonical_hash(payload["result"])
                unsigned = dict(payload)
                unsigned.pop("receipt_sha256")
                payload["receipt_sha256"] = _canonical_hash(unsigned)
                retriever = _FakeRetriever(raw_result)
                with self.assertRaises((TypeError, ValueError)):
                    CompareSearchReceipt.from_dict(
                        payload,
                        bound=self.bound,
                        store=self.store,
                        retriever=retriever,
                    )
                self.assertEqual(retriever.calls, [])

    def test_replay_rejects_python_equal_but_json_distinct_scalar_types(self):
        forged_bound = deepcopy(self.bound.to_dict())
        forged_bound["effective_plan"]["dense_k"] = float(
            forged_bound["effective_plan"]["dense_k"]
        )
        with self.assertRaisesRegex(ValueError, "bound_compare_payload_mismatch"):
            BoundCompare.from_dict(
                forged_bound,
                request=self.request,
                planner=self.planner,
                store=self.store,
                compare_registry=self.fields,
            )

        _values, results, verified = self.full_inputs()
        coverage = self.coverage(results=results, verified=verified)
        forged_coverage = deepcopy(coverage.to_dict())
        forged_coverage["required_slot_count"] = float(
            forged_coverage["required_slot_count"]
        )
        forged_coverage["normal_stop_allowed"] = 0
        with self.assertRaisesRegex(ValueError, "compare_coverage_payload_mismatch"):
            CompareCoverage.from_dict(
                forged_coverage,
                bound=self.bound,
                store=self.store,
                candidate_results=results,
                verified_evidence=verified,
            )

    def test_coverage_replay_rejects_receipts_from_another_request_binding(self):
        _values, results, verified = self.full_inputs()
        coverage = self.coverage(results=results, verified=verified)
        other_request = _request("사업비와 계약 기간을 비교해줘")
        other_bound = self.prepare(other_request)
        self.assertEqual(
            tuple(slot.key for slot in other_bound.plan.required_slots),
            tuple(slot.key for slot in self.bound.plan.required_slots),
        )
        self.assertNotEqual(other_bound.binding_sha256, self.bound.binding_sha256)

        other_values = {
            "doc-a.budget": self.evidence[("doc-a", "budget")],
            "doc-a.duration": self.evidence[("doc-a", "duration")],
            "doc-b.budget": self.evidence[("doc-b", "budget")],
            "doc-b.duration": self.evidence[("doc-b", "duration")],
        }
        other_results = {
            key: self.search_receipt(
                key,
                _result(self.store, (evidence,)),
                bound=other_bound,
            )
            for key, evidence in other_values.items()
        }
        other_verified = {
            key: self.verification_receipt(receipt, bound=other_bound)
            for key, receipt in other_results.items()
        }
        with self.assertRaisesRegex(ValueError, "search_receipt_request_mismatch"):
            CompareCoverage.from_dict(
                deepcopy(coverage.to_dict()),
                bound=self.bound,
                store=self.store,
                candidate_results=other_results,
                verified_evidence=other_verified,
            )

    def test_inputs_and_serialized_payload_are_detached(self):
        _values, results, verified = self.full_inputs()
        coverage = self.coverage(results=results, verified=verified)
        original_hash = coverage.coverage_sha256
        results.clear()
        verified.clear()
        payload = coverage.to_dict()
        payload["slots"][0]["verified_evidence_ids"].clear()
        payload["covered_document_ids"].clear()
        self.assertEqual(coverage.coverage_sha256, original_hash)
        self.assertEqual(coverage.verified_slot_count, 0)
        self.assertEqual(coverage.covered_document_ids, ())
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            coverage.normal_stop_allowed = False
        with self.assertRaises(TypeError):
            replace(coverage, normal_stop_allowed=False)


if __name__ == "__main__":
    unittest.main()
