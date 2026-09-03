from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
import unittest

from midprojectrag.orchestration import (
    CatalogDocument,
    CatalogEntity,
    DeterministicPlanner,
    PlanningCatalog,
    RoutingRule,
    RuleRegistry,
    default_rule_registry,
)
from midprojectrag.runtime_integrity import EvaluationCase, RuntimeRequest, project_runtime


def _catalog():
    return PlanningCatalog.synthetic(
        "synthetic-production-v1",
        (
            CatalogEntity(
                alias="서울 교통공사",
                canonical_value="서울교통공사",
                kind="agency",
                doc_ids=("doc-a", "doc-b"),
                source="agency_alias",
            ),
            CatalogEntity(
                alias="예약발매시스템 개량",
                canonical_value="예약발매시스템 개량",
                kind="business",
                doc_ids=("doc-a",),
                source="business_alias",
            ),
            CatalogEntity(
                alias="[긴급]",
                canonical_value="긴급",
                kind="filename_tag",
                doc_ids=("doc-b",),
                source="filename_tag",
            ),
        ),
    )


class DeterministicPlannerTests(unittest.TestCase):
    def setUp(self):
        self.registry = default_rule_registry()
        self.catalog = _catalog()
        self.planner = DeterministicPlanner.for_test(self.registry, self.catalog)

    def test_generic_query_types_are_rule_driven_and_traced(self):
        cases = (
            ("사업 기간을 알려줘", "fact", ()),
            ("예약발매시스템과 다른 사업의 차이를 비교해줘", "compare", ("query.compare.v1",)),
            ("사업 금액 상위 5개를 알려줘", "analytics", ("query.analytics.v1",)),
            ("조건에 맞는 모든 사업 목록", "exhaustive_list", ("query.exhaustive-list.v1",)),
            ("조직도 내용을 찾아줘", "table_visual", ("query.table-visual.v1",)),
        )
        for question, expected_type, expected_rules in cases:
            with self.subTest(question=question):
                result = self.planner.plan(RuntimeRequest(question=question))
                self.assertEqual(result.plan.query_type, expected_type)
                self.assertEqual(result.trace.matched_rule_ids, expected_rules)
                self.assertEqual(result.plan.config_sha256, self.registry.config_sha256)

    def test_followup_requires_actual_prior_citations_and_signal(self):
        request = RuntimeRequest(
            question="그 사업의 기간은?",
            history=(
                {
                    "turn_id": "assistant-1",
                    "role": "assistant",
                    "content": "이전 답변",
                    "cited_doc_ids": ["doc-a"],
                    "cited_evidence_ids": ["ev-a"],
                },
            ),
            prior_citation_state={
                "cited_doc_ids": ["doc-a"],
                "cited_evidence_ids": ["ev-a"],
                "resolved_entities": [],
                "list_doc_ids": [],
                "comparison_doc_ids": [],
            },
        )
        result = self.planner.plan(request)
        self.assertEqual(result.plan.query_type, "follow_up")
        self.assertEqual(result.trace.matched_rule_ids, ("history.citation.v1",))
        no_state = self.planner.plan(RuntimeRequest(question="그 사업의 기간은?"))
        self.assertEqual(no_state.plan.query_type, "fact")
        no_history = self.planner.plan(RuntimeRequest(
            question="그 사업의 기간은?",
            prior_citation_state=request.prior_citation_state,
        ))
        self.assertEqual(no_history.plan.query_type, "fact")
        unrelated = self.planner.plan(RuntimeRequest(
            question="새로운 사업 목록",
            prior_citation_state=request.prior_citation_state,
        ))
        self.assertEqual(unrelated.plan.query_type, "exhaustive_list")

    def test_entity_resolution_records_source_and_restricts_all_scope(self):
        result = self.planner.plan(RuntimeRequest(question="예약발매시스템 개량 기간"))
        self.assertEqual(result.plan.resolved_doc_ids, ("doc-a",))
        self.assertEqual(result.plan.entities[0].source, "business_alias")
        self.assertEqual(result.trace.scope_state, "restricted")
        self.assertEqual(result.trace.scope_origin, "entity_resolution")
        self.assertEqual(result.trace.resolved_doc_ids, ("doc-a",))

    def test_explicit_scope_intersection_stays_empty_and_never_becomes_global(self):
        result = self.planner.plan(RuntimeRequest(
            question="예약발매시스템 개량 기간",
            document_scope={"mode": "explicit", "doc_ids": ["doc-b"]},
            options={"allow_global_fallback": True},
        ))
        self.assertEqual(result.plan.resolved_doc_ids, ())
        self.assertEqual(result.plan.scope_state, "empty")
        self.assertEqual(result.plan.scope_origin, "user_explicit+entity_resolution")
        self.assertEqual(result.trace.scope_state, "empty")
        self.assertEqual(result.trace.scope_origin, "user_explicit+entity_resolution")
        self.assertFalse(result.plan.allow_global_fallback)

    def test_signal_and_ascii_alias_substrings_do_not_false_match(self):
        goal = self.planner.plan(RuntimeRequest(question="사업 목표를 알려줘"))
        self.assertEqual(goal.plan.query_type, "fact")
        ascii_catalog = PlanningCatalog.synthetic(
            "ascii-v1",
            (CatalogEntity("ERP", "ERP", "domain", ("doc-erp",), "domain_synonym"),),
        )
        planner = DeterministicPlanner.for_test(self.registry, ascii_catalog)
        result = planner.plan(RuntimeRequest(question="DERP 시스템 설명"))
        self.assertEqual(result.plan.resolved_doc_ids, ())
        self.assertEqual(result.trace.scope_state, "unfiltered")

    def test_metadata_predicates_preserve_status_and_unresolved_reasons(self):
        request = RuntimeRequest(
            question="금액 조건 사업",
            metadata_filters=(
                {"field": "business_amount", "operator": "ge", "value": 100_000_000},
                {"field": "business_amount", "operator": "between", "value": [10, 1]},
                {"field": "secret_gold_field", "operator": "eq", "value": "x"},
            ),
        )
        result = self.planner.plan(request)
        self.assertEqual(
            tuple(predicate.status for predicate in result.plan.metadata_predicates),
            ("supported", "unresolved_constraint", "unsupported_filter"),
        )
        self.assertEqual(
            result.plan.unresolved_constraints,
            (
                "metadata_predicate:1:unresolved_constraint",
                "metadata_predicate:2:unsupported_filter",
            ),
        )
        self.assertEqual(result.trace.predicate_statuses, (
            "supported", "unresolved_constraint", "unsupported_filter",
        ))

    def test_unknown_query_is_explicit_and_disables_fallback(self):
        result = self.planner.plan(RuntimeRequest(
            question="???",
            options={"allow_global_fallback": True},
        ))
        self.assertEqual(result.plan.query_type, "unknown_or_out_of_scope")
        self.assertEqual(result.plan.unresolved_constraints, ("no_semantic_query_token",))
        self.assertFalse(result.plan.allow_global_fallback)

    def test_only_runtime_request_is_accepted_and_gold_changes_cannot_change_plan(self):
        runtime = RuntimeRequest(question="사업 기간")
        with self.assertRaisesRegex(TypeError, "runtime_request_required"):
            self.planner.plan(EvaluationCase(runtime, required_doc_ids=("doc-a",)))
        row_a = {"question": "사업 기간", "required_doc_ids": ["doc-a"], "expected": {"x": 1}}
        row_b = {"question": "사업 기간", "required_doc_ids": ["doc-b"], "expected": {"x": 2}}
        result_a = self.planner.plan(project_runtime(row_a))
        result_b = self.planner.plan(project_runtime(row_b))
        self.assertEqual(result_a.to_dict(), result_b.to_dict())

    def test_trace_binds_request_registry_and_catalog_without_question_text(self):
        request = RuntimeRequest(question="서울 교통공사 사업")
        result = self.planner.plan(request)
        trace = result.trace.to_dict()
        self.assertEqual(trace["request_fingerprint"], request.fingerprint)
        self.assertEqual(trace["config_sha256"], self.registry.config_sha256)
        self.assertEqual(trace["catalog_sha256"], self.catalog.catalog_sha256)
        self.assertNotIn("question", trace)
        self.assertNotIn("expected", str(trace).lower())
        self.assertEqual(trace["execution_kind"], "synthetic")

    def test_reported_real_query_boundary_regressions(self):
        citations = {
            "cited_doc_ids": ["doc-a"],
            "cited_evidence_ids": ["ev-a"],
            "resolved_entities": [],
            "list_doc_ids": [],
            "comparison_doc_ids": [],
        }
        cases = (
            (RuntimeRequest(question="비교과시스템 개발 기간은?"), "fact"),
            (RuntimeRequest(question="그럼에도 새로운 사업 목록", prior_citation_state=citations), "exhaustive_list"),
            (RuntimeRequest(question="모든 사업을 보여줘"), "exhaustive_list"),
            (RuntimeRequest(question="사업이 몇 개인가?"), "analytics"),
            (RuntimeRequest(question="표에 있는 예산을 알려줘"), "table_visual"),
        )
        for request, expected in cases:
            with self.subTest(question=request.question):
                self.assertEqual(self.planner.plan(request).plan.query_type, expected)

    def test_common_list_count_and_compound_table_expressions_are_routed(self):
        cases = (
            ("사업을 전부 알려줘", "exhaustive_list"),
            ("사업은 총 몇 건인가요?", "analytics"),
            ("사업 건수를 알려줘", "analytics"),
            ("refined 98개 문서는 HWP와 PDF가 각각 몇 건이며, 각 형식의 비율은 얼마인가?", "analytics"),
            ("전체 문서가 몇 건인지 알려줘", "analytics"),
            ("사업이 몇 개인지 알려줘", "analytics"),
            ("구성표에서 배점을 알려줘", "table_visual"),
            ("신인도 가점표에서 배점을 알려줘", "table_visual"),
        )
        for question, expected in cases:
            with self.subTest(question=question):
                self.assertEqual(
                    self.planner.plan(RuntimeRequest(question=question)).plan.query_type,
                    expected,
                )

    def test_nested_alias_prefers_longest_and_ambiguous_exact_alias_fails_closed(self):
        nested = PlanningCatalog.synthetic("nested-v1", (
            CatalogEntity("서울교통공사", "서울교통공사", "agency", ("doc-specific",), "agency_alias"),
            CatalogEntity("서울", "서울", "region", ("doc-broad",), "domain_synonym"),
        ))
        result = DeterministicPlanner.for_test(self.registry, nested).plan(
            RuntimeRequest(question="서울교통공사 사업 기간")
        )
        self.assertEqual(result.plan.resolved_doc_ids, ("doc-specific",))
        ambiguous = PlanningCatalog.synthetic("ambiguous-v1", (
            CatalogEntity("동일명", "기관 동일명", "agency", ("doc-a",), "agency_alias"),
            CatalogEntity("동일명", "사업 동일명", "business", ("doc-b",), "business_alias"),
        ))
        result = DeterministicPlanner.for_test(self.registry, ambiguous).plan(
            RuntimeRequest(question="동일명 기간", options={"allow_global_fallback": True})
        )
        self.assertEqual(result.plan.scope_state, "empty")
        self.assertEqual(result.plan.resolved_doc_ids, ())
        self.assertFalse(result.plan.allow_global_fallback)
        self.assertRegex(result.plan.unresolved_constraints[0], r"^ambiguous_entity_alias:[0-9a-f]{12}$")

    def test_any_ambiguous_entity_makes_the_whole_entity_scope_empty(self):
        catalog = PlanningCatalog.synthetic("ambiguous-mixed-v1", (
            CatalogEntity("동일명", "기관 동일명", "agency", ("doc-a",), "agency_alias"),
            CatalogEntity("동일명", "사업 동일명", "business", ("doc-b",), "business_alias"),
            CatalogEntity("정상사업", "정상사업", "business", ("doc-good",), "business_alias"),
        ))
        result = DeterministicPlanner.for_test(self.registry, catalog).plan(
            RuntimeRequest(question="동일명과 정상사업 기간", options={"allow_global_fallback": True})
        )
        self.assertEqual(result.plan.scope_state, "empty")
        self.assertEqual(result.plan.resolved_doc_ids, ())
        self.assertFalse(result.plan.allow_global_fallback)

    def test_short_korean_alias_does_not_match_longer_compound(self):
        catalog = PlanningCatalog.synthetic("region-v1", (
            CatalogEntity("서울", "서울", "region", ("doc-seoul",), "domain_synonym"),
        ))
        planner = DeterministicPlanner.for_test(self.registry, catalog)
        for question in ("서울랜드 사업", "서울시 사업"):
            with self.subTest(question=question):
                result = planner.plan(RuntimeRequest(question=question))
                self.assertEqual(result.plan.resolved_doc_ids, ())
                self.assertEqual(result.plan.scope_state, "unfiltered")

    def test_partially_overlapping_alias_uses_only_the_longest_occurrence(self):
        catalog = PlanningCatalog.synthetic("overlap-v1", (
            CatalogEntity(
                "서울 교통 공사 사업", "서울 교통 공사 사업", "business",
                ("doc-long",), "business_alias",
            ),
            CatalogEntity(
                "공사 사업 운영", "공사 사업 운영", "business",
                ("doc-short",), "business_alias",
            ),
        ))
        result = DeterministicPlanner.for_test(self.registry, catalog).plan(
            RuntimeRequest(question="서울 교통 공사 사업 운영 기간")
        )
        self.assertEqual(result.plan.resolved_doc_ids, ("doc-long",))
        self.assertEqual(
            tuple(entity.value for entity in result.plan.entities),
            ("서울 교통 공사 사업",),
        )

    def test_catalog_lineage_is_sealed_and_custom_gold_rule_cannot_execute(self):
        entity = CatalogEntity("사업 기간", "사업 기간", "business", ("required-doc",), "business_alias")
        with self.assertRaisesRegex(ValueError, "planning_catalog_factory_required"):
            PlanningCatalog("raw", (entity,))
        production = PlanningCatalog.from_metadata("prod-v1", (
            CatalogDocument("doc-a", "예약발매시스템 개량", "서울 교통공사", "[긴급] 제안요청서.hwp"),
        ))
        planner = DeterministicPlanner(self.registry, production)
        result = planner.plan(RuntimeRequest(question="예약발매시스템 개량 기간"))
        self.assertEqual(result.trace.execution_kind, "production")
        self.assertEqual(result.trace.catalog_source_kind, "production_metadata")
        custom = RuleRegistry(
            "planner-rules-v1-gold",
            self.registry.budgets,
            (RoutingRule(
                "dev-multi-003", "query_expression", "compare", ("사업 기간",), 999
            ),),
        )
        with self.assertRaisesRegex(ValueError, "unapproved_rule_registry"):
            DeterministicPlanner.for_test(custom, self.catalog)

    def test_production_catalog_load_rederives_aliases_from_source_documents(self):
        catalog = PlanningCatalog.from_metadata("prod-v1", (
            CatalogDocument("doc-a", "정상 사업", "정상 기관", "[긴급] 정상.hwp"),
        ))
        self.assertEqual(
            PlanningCatalog.from_dict(
                catalog.to_dict(), expected_source_sha256=catalog.source_sha256
            ),
            catalog,
        )
        forged = deepcopy(catalog.to_dict())
        forged["entities"] = [
            CatalogEntity(
                "골든 질문", "골든 질문", "business", ("required-doc-secret",), "business_alias"
            ).to_dict()
        ]
        unsigned = {key: value for key, value in forged.items() if key != "catalog_sha256"}
        forged["catalog_sha256"] = sha256(json.dumps(
            unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        with self.assertRaisesRegex(ValueError, "catalog_entities_not_derived_from_source"):
            PlanningCatalog.from_dict(
                forged, expected_source_sha256=catalog.source_sha256
            )
        forged_source = deepcopy(catalog.to_dict())
        forged_source["source_documents"][0]["title"] = "골든 질문"
        changed_documents = forged_source["source_documents"]
        forged_source["source_sha256"] = sha256(json.dumps(
            {"source_kind": "production_metadata", "documents": changed_documents},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        unsigned = {
            key: value for key, value in forged_source.items() if key != "catalog_sha256"
        }
        forged_source["catalog_sha256"] = sha256(json.dumps(
            unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        with self.assertRaisesRegex(ValueError, "catalog_source_attestation_mismatch"):
            PlanningCatalog.from_dict(
                forged_source, expected_source_sha256=catalog.source_sha256
            )

    def test_catalog_replace_cannot_preserve_factory_authority(self):
        catalog = PlanningCatalog.from_metadata("prod-v1", (
            CatalogDocument("doc-a", "정상 사업", "정상 기관", "정상.hwp"),
        ))
        forged_entity = CatalogEntity(
            "골든 질문", "골든 질문", "business", ("gold-doc",), "business_alias"
        )
        with self.assertRaisesRegex(ValueError, "planning_catalog_factory_required"):
            replace(catalog, entities=(forged_entity,))

    def test_synthetic_catalog_hash_is_order_independent_and_roundtrips(self):
        first = CatalogEntity("짧음", "짧음", "business", ("doc-a",), "business_alias")
        second = CatalogEntity(
            "훨씬 긴 사업명", "훨씬 긴 사업명", "business", ("doc-b",), "business_alias"
        )
        forward = PlanningCatalog.synthetic("synthetic-v1", (first, second))
        reverse = PlanningCatalog.synthetic("synthetic-v1", (second, first))
        self.assertEqual(forward.source_sha256, reverse.source_sha256)
        self.assertEqual(forward.to_dict(), reverse.to_dict())
        self.assertEqual(
            PlanningCatalog.from_dict(
                forward.to_dict(), expected_source_sha256=forward.source_sha256
            ),
            forward,
        )
        payload = forward.to_dict()
        payload["entities"][0]["doc_ids"] = tuple(payload["entities"][0]["doc_ids"])
        with self.assertRaisesRegex(TypeError, "catalog_entity_doc_ids_array"):
            PlanningCatalog.from_dict(
                payload, expected_source_sha256=forward.source_sha256
            )


if __name__ == "__main__":
    unittest.main()
