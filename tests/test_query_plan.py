import json
import unittest
from dataclasses import FrozenInstanceError

from midprojectrag.orchestration import (
    PlanConstraint,
    PlanEntity,
    QueryPlan,
    RequiredSlot,
    RetrievalBudget,
    RoutingRule,
    RuleRegistry,
    default_rule_registry,
)
from midprojectrag.runtime_integrity import MetadataPredicate


class QueryPlanContractTests(unittest.TestCase):
    def test_default_registry_has_exact_query_types_and_budgets(self):
        registry = default_rule_registry()
        self.assertEqual(
            set(registry.query_types),
            {
                "fact", "compare", "follow_up", "exhaustive_list",
                "analytics", "table_visual", "unknown_or_out_of_scope",
            },
        )
        self.assertEqual(registry.budget_for("fact").to_dict(), {
            "dense_k": 30, "lexical_k": 30, "rerank_k": 40,
            "final_evidence_budget": 6, "max_evidence_per_doc": 6,
            "citation_budget": 6,
        })
        self.assertEqual(registry.budget_for("compare").to_dict(), {
            "dense_k": 50, "lexical_k": 50, "rerank_k": 60,
            "final_evidence_budget": 10, "max_evidence_per_doc": 2,
            "citation_budget": 10,
        })
        self.assertEqual(registry.budget_for("exhaustive_list").to_dict(), {
            "dense_k": 80, "lexical_k": 80, "rerank_k": None,
            "final_evidence_budget": None, "max_evidence_per_doc": None,
            "citation_budget": None,
        })

    def test_registry_is_content_hashed_closed_and_round_trips(self):
        registry = default_rule_registry()
        payload = registry.to_dict()
        self.assertRegex(payload["config_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(RuleRegistry.from_dict(json.loads(json.dumps(payload))), registry)
        payload["config_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "config_sha256_mismatch"):
            RuleRegistry.from_dict(payload)
        unknown = default_rule_registry().to_dict()
        unknown["gold_doc_ids"] = ["doc_answer"]
        with self.assertRaisesRegex(ValueError, "registry_fields"):
            RuleRegistry.from_dict(unknown)

    def test_registry_rejects_missing_budget_duplicate_rules_and_unallowlisted_source(self):
        registry = default_rule_registry()
        with self.assertRaisesRegex(ValueError, "budget_query_types"):
            RuleRegistry(
                registry_version="planner-rules-v1",
                budgets=registry.budgets[:-1],
                rules=registry.rules,
            )
        rule = RoutingRule(
            rule_id="query.compare.v1",
            source="query_expression",
            output_query_type="compare",
            signals=("비교",),
            priority=100,
        )
        with self.assertRaisesRegex(ValueError, "duplicate_rule_ids"):
            RuleRegistry(
                registry_version="planner-rules-v1",
                budgets=registry.budgets,
                rules=(rule, rule),
            )
        with self.assertRaisesRegex(ValueError, "invalid_rule_source"):
            RoutingRule(
                rule_id="gold.answer.v1",
                source="expected_document",
                output_query_type="fact",
                signals=("case-003",),
                priority=1,
            )

    def test_registry_factory_binds_plan_budget_version_and_hash(self):
        registry = default_rule_registry()
        plan = registry.make_plan(
            query_type="compare",
            normalized_query="두 사업의 예산을 비교",
            entities=(PlanEntity("기관 A", "agency", "user_query", ("doc-a",)),),
            resolved_doc_ids=("doc-a", "doc-b"),
            constraints=(PlanConstraint("comparison_field", "budget", "user_query"),),
            metadata_predicates=(MetadataPredicate("business_amount", "ge", 1),),
            required_slots=(RequiredSlot("doc-a", "budget"), RequiredSlot("doc-b", "budget")),
            allow_global_fallback=False,
            unresolved_constraints=(),
        )
        self.assertEqual(plan.budget, registry.budget_for("compare"))
        self.assertEqual(plan.planner_version, registry.registry_version)
        self.assertEqual(plan.config_sha256, registry.config_sha256)
        registry.validate_plan(plan)
        with self.assertRaisesRegex(ValueError, "plan_registry_mismatch"):
            registry.validate_plan(QueryPlan(
                **{**plan.constructor_dict(), "config_sha256": "1" * 64}
            ))

    def test_query_plan_is_immutable_closed_and_preserves_unresolved(self):
        registry = default_rule_registry()
        source_docs = ["doc-a"]
        unresolved = ["unsupported:budget_phrase"]
        plan = registry.make_plan(
            query_type="unknown_or_out_of_scope",
            normalized_query="지원하지 않는 요청",
            resolved_doc_ids=source_docs,
            unresolved_constraints=unresolved,
        )
        source_docs.append("doc-b")
        unresolved.clear()
        self.assertEqual(plan.resolved_doc_ids, ("doc-a",))
        self.assertEqual(plan.unresolved_constraints, ("unsupported:budget_phrase",))
        with self.assertRaises(FrozenInstanceError):
            plan.normalized_query = "changed"
        payload = plan.to_dict()
        self.assertEqual(registry.plan_from_dict(json.loads(json.dumps(payload))), plan)
        payload["expected_doc_ids"] = ["doc-answer"]
        with self.assertRaisesRegex(ValueError, "query_plan_fields"):
            registry.plan_from_dict(payload)

    def test_metadata_predicate_status_cannot_be_forged_or_silently_dropped(self):
        registry = default_rule_registry()
        plan = registry.make_plan(
            query_type="fact",
            normalized_query="금액이 1원 이상인 사업",
            metadata_predicates=(MetadataPredicate("business_amount", "ge", 1),),
        )
        payload = plan.to_dict()
        payload["metadata_predicates"][0]["status"] = "unsupported_filter"
        with self.assertRaisesRegex(ValueError, "metadata_predicate_status_mismatch"):
            registry.plan_from_dict(payload)

    def test_plan_loader_requires_registry_and_rejects_forged_hash_or_budget(self):
        registry = default_rule_registry()
        payload = registry.make_plan(
            query_type="fact", normalized_query="사업 금액"
        ).to_dict()
        with self.assertRaisesRegex(TypeError, "rule_registry_required"):
            QueryPlan.from_dict(payload, registry=None)
        payload["config_sha256"] = "f" * 64
        payload["dense_k"] = 999_999_999
        with self.assertRaisesRegex(ValueError, "plan_registry_mismatch"):
            registry.plan_from_dict(payload)

    def test_plan_loader_requires_json_arrays_for_every_array_field(self):
        registry = default_rule_registry()
        fields = (
            "entities",
            "resolved_doc_ids",
            "inherited_doc_ids",
            "constraints",
            "metadata_predicates",
            "required_slots",
            "unresolved_constraints",
        )
        for field in fields:
            for invalid in ({}, ()):
                with self.subTest(field=field, invalid=type(invalid).__name__):
                    payload = registry.make_plan(
                        query_type="fact", normalized_query="질문"
                    ).to_dict()
                    payload[field] = invalid
                    with self.assertRaisesRegex(TypeError, f"query_plan_{field}_array"):
                        registry.plan_from_dict(payload)

    def test_nested_and_registry_loaders_reject_python_tuples(self):
        registry = default_rule_registry()
        for field in ("budgets", "rules"):
            with self.subTest(registry_field=field):
                payload = registry.to_dict()
                payload[field] = tuple(payload[field])
                with self.assertRaisesRegex(TypeError, f"registry_{field}_array"):
                    RuleRegistry.from_dict(payload)

        rule_payload = registry.rules[0].to_dict()
        rule_payload["signals"] = tuple(rule_payload["signals"])
        with self.assertRaisesRegex(TypeError, "routing_rule_signals_array"):
            RoutingRule.from_dict(rule_payload)

        plan = registry.make_plan(
            query_type="fact",
            normalized_query="질문",
            entities=(PlanEntity("기관", "agency", "user_query", ("doc-a",)),),
            resolved_doc_ids=("doc-a",),
            metadata_predicates=(MetadataPredicate("business_amount", "in", [1, 2]),),
        )
        payload = plan.to_dict()
        payload["entities"][0]["resolved_doc_ids"] = ("doc-a",)
        with self.assertRaisesRegex(TypeError, "entity_doc_ids_array"):
            registry.plan_from_dict(payload)
        payload = plan.to_dict()
        payload["metadata_predicates"][0]["value"] = (1, 2)
        with self.assertRaisesRegex(TypeError, "metadata_predicate_value_json"):
            registry.plan_from_dict(payload)

    def test_metadata_predicate_is_deeply_immutable_inside_plan(self):
        registry = default_rule_registry()
        predicate = MetadataPredicate("business_amount", "ge", 1)
        plan = registry.make_plan(
            query_type="fact",
            normalized_query="사업 금액",
            metadata_predicates=(predicate,),
        )
        self.assertFalse(hasattr(predicate, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            predicate.value = 2
        self.assertEqual(plan.metadata_predicates[0].value, 1)
        registry.validate_plan(plan)

    def test_unknown_or_unsupported_constraints_must_be_explicit(self):
        registry = default_rule_registry()
        with self.assertRaisesRegex(ValueError, "unresolved_constraints_required"):
            registry.make_plan(
                query_type="unknown_or_out_of_scope",
                normalized_query="지원 범위 밖",
            )
        with self.assertRaisesRegex(ValueError, "unresolved_constraints_required"):
            registry.make_plan(
                query_type="fact",
                normalized_query="지원하지 않는 필터",
                metadata_predicates=(MetadataPredicate("unknown_field", "eq", "x"),),
            )

    def test_required_slot_identity_and_plan_cross_references_are_checked(self):
        self.assertEqual(RequiredSlot("doc-a", "business_amount").key, "doc-a.business_amount")
        with self.assertRaisesRegex(ValueError, "invalid_slot_field"):
            RequiredSlot("doc-a", "bad.field")
        registry = default_rule_registry()
        with self.assertRaisesRegex(ValueError, "duplicate_required_slots"):
            registry.make_plan(
                query_type="compare",
                normalized_query="비교",
                resolved_doc_ids=("doc-a", "doc-b"),
                required_slots=(RequiredSlot("doc-a", "budget"), RequiredSlot("doc-a", "budget")),
            )
        with self.assertRaisesRegex(ValueError, "slot_doc_not_resolved"):
            registry.make_plan(
                query_type="compare",
                normalized_query="비교",
                resolved_doc_ids=("doc-a", "doc-b"),
                required_slots=(RequiredSlot("doc-c", "budget"),),
            )

    def test_empty_or_user_explicit_scope_cannot_enable_global_fallback(self):
        registry = default_rule_registry()
        for state, origin, doc_ids in (
            ("empty", "metadata_filter", ()),
            ("empty", "user_explicit", ()),
            ("restricted", "user_explicit", ("doc-a",)),
        ):
            with self.subTest(state=state, origin=origin):
                with self.assertRaisesRegex(ValueError, "scope_cannot_global_fallback"):
                    registry.make_plan(
                        query_type="fact",
                        normalized_query="질문",
                        resolved_doc_ids=doc_ids,
                        scope_state=state,
                        scope_origin=origin,
                        allow_global_fallback=True,
                    )

    def test_budget_rejects_bool_negative_and_nonfinite_values(self):
        for value in (True, -1, 1.5, float("inf")):
            with self.subTest(value=value):
                with self.assertRaises((TypeError, ValueError)):
                    RetrievalBudget(value, 1, 1, 1, 1, 1)


if __name__ == "__main__":
    unittest.main()
