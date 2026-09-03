"""Closed, immutable contracts for deterministic planning.

This module describes plans and rule configuration.  It deliberately does not
inspect evaluation cases, execute routing rules, retrieve evidence, or call a
model.  Those responsibilities belong to later orchestration leaves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import re
from typing import Any, Iterable, Mapping

from midprojectrag.runtime_integrity import MetadataPredicate


SCHEMA_VERSION = "1.0"
QUERY_TYPES = (
    "fact",
    "compare",
    "follow_up",
    "exhaustive_list",
    "analytics",
    "table_visual",
    "unknown_or_out_of_scope",
)
RULE_SOURCES = frozenset({"history_citation", "query_expression"})
ENTITY_SOURCES = frozenset(
    {
        "user_query",
        "user_scope",
        "agency_alias",
        "business_alias",
        "filename_tag",
        "domain_synonym",
        "history_citation",
        "metadata_predicate",
    }
)
CONSTRAINT_SOURCES = frozenset(
    {"user_query", "user_scope", "history_citation", "metadata_predicate", "rule_registry"}
)
CONSTRAINT_STATUSES = frozenset({"resolved", "unresolved", "unsupported"})
SCOPE_STATES = frozenset({"unfiltered", "empty", "restricted"})
SCOPE_ORIGINS = frozenset(
    {
        "all",
        "user_explicit",
        "entity_resolution",
        "user_explicit+entity_resolution",
        "followup_citations",
        "metadata_filter",
        "combined",
    }
)

_BUDGET_FIELDS = (
    "dense_k",
    "lexical_k",
    "rerank_k",
    "final_evidence_budget",
    "max_evidence_per_doc",
    "citation_budget",
)
_ENTITY_FIELDS = frozenset({"value", "kind", "source", "resolved_doc_ids"})
_CONSTRAINT_FIELDS = frozenset({"kind", "value", "source", "status"})
_SLOT_FIELDS = frozenset({"doc_id", "field", "key"})
_RULE_FIELDS = frozenset(
    {"rule_id", "source", "output_query_type", "signals", "priority"}
)
_REGISTRY_FIELDS = frozenset(
    {"schema_version", "registry_version", "budgets", "rules", "config_sha256"}
)
_PLAN_FIELDS = frozenset(
    {
        "schema_version",
        "query_type",
        "normalized_query",
        "entities",
        "resolved_doc_ids",
        "inherited_doc_ids",
        "scope_state",
        "scope_origin",
        "constraints",
        "metadata_predicates",
        "required_slots",
        *_BUDGET_FIELDS,
        "allow_global_fallback",
        "unresolved_constraints",
        "planner_version",
        "config_sha256",
    }
)
_SLOT_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _closed(raw: Any, fields: frozenset[str], code: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping) or any(type(key) is not str for key in raw):
        raise TypeError(code)
    if set(raw) != fields:
        raise ValueError(code)
    return raw


def _text(value: Any, code: str, *, maximum: int = 4096) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise ValueError(code)
    value.encode("utf-8")
    return value


def _sequence(value: Any, code: str) -> tuple[Any, ...]:
    if type(value) not in (tuple, list):
        raise TypeError(code)
    return tuple(value)


def _json_array(value: Any, code: str) -> list[Any]:
    if type(value) is not list:
        raise TypeError(code)
    return value


def _texts(value: Any, code: str, *, maximum: int = 4096) -> tuple[str, ...]:
    result = tuple(_text(item, code, maximum=maximum) for item in _sequence(value, code))
    if len(result) != len(set(result)):
        raise ValueError(f"duplicate_{code}")
    return result


def _query_type(value: Any) -> str:
    if value not in QUERY_TYPES:
        raise ValueError("invalid_query_type")
    return value


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _metadata_predicate_from_dict(raw: Mapping[str, Any]) -> MetadataPredicate:
    _closed(
        raw,
        frozenset({"field", "operator", "value", "status"}),
        "metadata_predicate_fields",
    )
    if type(raw["value"]) is tuple:
        raise TypeError("metadata_predicate_value_json")
    predicate = MetadataPredicate.from_dict(
        {"field": raw["field"], "operator": raw["operator"], "value": raw["value"]}
    )
    if raw["status"] != predicate.status:
        raise ValueError("metadata_predicate_status_mismatch")
    return predicate


@dataclass(frozen=True, slots=True)
class RetrievalBudget:
    dense_k: int | None
    lexical_k: int | None
    rerank_k: int | None
    final_evidence_budget: int | None
    max_evidence_per_doc: int | None
    citation_budget: int | None

    def __post_init__(self) -> None:
        for name in _BUDGET_FIELDS:
            value = getattr(self, name)
            if value is not None and type(value) is not int:
                raise TypeError(f"invalid_{name}")
            if value is not None and value < 0:
                raise ValueError(f"invalid_{name}")

    @property
    def dynamic_fields(self) -> tuple[str, ...]:
        return tuple(name for name in _BUDGET_FIELDS if getattr(self, name) is None)

    def to_dict(self) -> dict[str, int | None]:
        return {name: getattr(self, name) for name in _BUDGET_FIELDS}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> RetrievalBudget:
        _closed(raw, frozenset(_BUDGET_FIELDS), "budget_fields")
        return cls(**{name: raw[name] for name in _BUDGET_FIELDS})


@dataclass(frozen=True, slots=True)
class BudgetRule:
    query_type: str
    budget: RetrievalBudget

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_type", _query_type(self.query_type))
        if type(self.budget) is not RetrievalBudget:
            raise TypeError("invalid_budget")

    def to_dict(self) -> dict[str, Any]:
        return {"query_type": self.query_type, "budget": self.budget.to_dict()}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> BudgetRule:
        _closed(raw, frozenset({"query_type", "budget"}), "budget_rule_fields")
        return cls(_query_type(raw["query_type"]), RetrievalBudget.from_dict(raw["budget"]))


@dataclass(frozen=True, slots=True)
class PlanEntity:
    value: str
    kind: str
    source: str
    resolved_doc_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _text(self.value, "invalid_entity_value"))
        object.__setattr__(self, "kind", _text(self.kind, "invalid_entity_kind", maximum=128))
        if self.source not in ENTITY_SOURCES:
            raise ValueError("invalid_entity_source")
        object.__setattr__(
            self,
            "resolved_doc_ids",
            _texts(self.resolved_doc_ids, "entity_doc_ids", maximum=256),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "kind": self.kind,
            "source": self.source,
            "resolved_doc_ids": list(self.resolved_doc_ids),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> PlanEntity:
        _closed(raw, _ENTITY_FIELDS, "entity_fields")
        _json_array(raw["resolved_doc_ids"], "entity_doc_ids_array")
        return cls(**raw)


@dataclass(frozen=True, slots=True)
class PlanConstraint:
    kind: str
    value: str
    source: str
    status: str = "resolved"

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _text(self.kind, "invalid_constraint_kind", maximum=128))
        object.__setattr__(self, "value", _text(self.value, "invalid_constraint_value"))
        if self.source not in CONSTRAINT_SOURCES:
            raise ValueError("invalid_constraint_source")
        if self.status not in CONSTRAINT_STATUSES:
            raise ValueError("invalid_constraint_status")

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "value": self.value,
            "source": self.source,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> PlanConstraint:
        _closed(raw, _CONSTRAINT_FIELDS, "constraint_fields")
        return cls(**raw)


@dataclass(frozen=True, slots=True)
class RequiredSlot:
    doc_id: str
    field: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "doc_id", _text(self.doc_id, "invalid_slot_doc_id", maximum=256))
        if type(self.field) is not str or not _SLOT_NAME.fullmatch(self.field):
            raise ValueError("invalid_slot_field")

    @property
    def key(self) -> str:
        return f"{self.doc_id}.{self.field}"

    def to_dict(self) -> dict[str, str]:
        return {"doc_id": self.doc_id, "field": self.field, "key": self.key}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> RequiredSlot:
        _closed(raw, _SLOT_FIELDS, "required_slot_fields")
        slot = cls(doc_id=raw["doc_id"], field=raw["field"])
        if raw["key"] != slot.key:
            raise ValueError("required_slot_key_mismatch")
        return slot


@dataclass(frozen=True, slots=True)
class RoutingRule:
    rule_id: str
    source: str
    output_query_type: str
    signals: tuple[str, ...] = ()
    priority: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_id", _text(self.rule_id, "invalid_rule_id", maximum=128))
        if self.source not in RULE_SOURCES:
            raise ValueError("invalid_rule_source")
        object.__setattr__(self, "output_query_type", _query_type(self.output_query_type))
        object.__setattr__(self, "signals", _texts(self.signals, "rule_signals", maximum=256))
        if type(self.priority) is not int or self.priority < 0:
            raise ValueError("invalid_rule_priority")

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "source": self.source,
            "output_query_type": self.output_query_type,
            "signals": list(self.signals),
            "priority": self.priority,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> RoutingRule:
        _closed(raw, _RULE_FIELDS, "routing_rule_fields")
        _json_array(raw["signals"], "routing_rule_signals_array")
        return cls(**raw)


@dataclass(frozen=True, slots=True)
class QueryPlan:
    query_type: str
    normalized_query: str
    budget: RetrievalBudget
    planner_version: str
    config_sha256: str
    entities: tuple[PlanEntity, ...] = ()
    resolved_doc_ids: tuple[str, ...] = ()
    inherited_doc_ids: tuple[str, ...] = ()
    scope_state: str = "unfiltered"
    scope_origin: str = "all"
    constraints: tuple[PlanConstraint, ...] = ()
    metadata_predicates: tuple[MetadataPredicate, ...] = ()
    required_slots: tuple[RequiredSlot, ...] = ()
    allow_global_fallback: bool = False
    unresolved_constraints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_type", _query_type(self.query_type))
        object.__setattr__(
            self, "normalized_query", _text(self.normalized_query, "invalid_normalized_query")
        )
        if type(self.budget) is not RetrievalBudget:
            raise TypeError("invalid_plan_budget")
        object.__setattr__(
            self, "planner_version", _text(self.planner_version, "invalid_planner_version", maximum=128)
        )
        if type(self.config_sha256) is not str or not _SHA256.fullmatch(self.config_sha256):
            raise ValueError("invalid_config_sha256")
        entities = tuple(self.entities)
        constraints = tuple(self.constraints)
        predicates = tuple(self.metadata_predicates)
        slots = tuple(self.required_slots)
        if any(type(value) is not PlanEntity for value in entities):
            raise TypeError("invalid_plan_entities")
        if any(type(value) is not PlanConstraint for value in constraints):
            raise TypeError("invalid_plan_constraints")
        if any(type(value) is not MetadataPredicate for value in predicates):
            raise TypeError("invalid_plan_metadata_predicates")
        if any(type(value) is not RequiredSlot for value in slots):
            raise TypeError("invalid_plan_required_slots")
        object.__setattr__(self, "entities", entities)
        object.__setattr__(self, "constraints", constraints)
        object.__setattr__(self, "metadata_predicates", predicates)
        object.__setattr__(self, "required_slots", slots)
        resolved = _texts(self.resolved_doc_ids, "resolved_doc_ids", maximum=256)
        inherited = _texts(self.inherited_doc_ids, "inherited_doc_ids", maximum=256)
        object.__setattr__(self, "resolved_doc_ids", resolved)
        object.__setattr__(self, "inherited_doc_ids", inherited)
        if not set(inherited).issubset(resolved):
            raise ValueError("inherited_doc_not_resolved")
        if self.scope_state not in SCOPE_STATES or self.scope_origin not in SCOPE_ORIGINS:
            raise ValueError("invalid_plan_scope")
        if (self.scope_state == "restricted") != bool(resolved):
            raise ValueError("inconsistent_plan_scope")
        if (self.scope_state == "unfiltered") != (self.scope_origin == "all"):
            raise ValueError("inconsistent_plan_scope_origin")
        resolved_set = set(resolved)
        keys = tuple(slot.key for slot in slots)
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate_required_slots")
        if any(slot.doc_id not in resolved_set for slot in slots):
            raise ValueError("slot_doc_not_resolved")
        if type(self.allow_global_fallback) is not bool:
            raise TypeError("invalid_global_fallback")
        if self.allow_global_fallback and (
            self.scope_state == "empty"
            or self.scope_origin in {"user_explicit", "user_explicit+entity_resolution"}
        ):
            raise ValueError("scope_cannot_global_fallback")
        if self.query_type == "unknown_or_out_of_scope" and self.allow_global_fallback:
            raise ValueError("unknown_query_cannot_fallback")
        unresolved = _texts(self.unresolved_constraints, "unresolved_constraints")
        needs_unresolved = (
            self.query_type == "unknown_or_out_of_scope"
            or any(value.status != "resolved" for value in constraints)
            or any(value.status != "supported" for value in predicates)
        )
        if needs_unresolved and not unresolved:
            raise ValueError("unresolved_constraints_required")
        object.__setattr__(self, "unresolved_constraints", unresolved)

    @property
    def dense_k(self) -> int | None:
        return self.budget.dense_k

    @property
    def lexical_k(self) -> int | None:
        return self.budget.lexical_k

    @property
    def rerank_k(self) -> int | None:
        return self.budget.rerank_k

    @property
    def final_evidence_budget(self) -> int | None:
        return self.budget.final_evidence_budget

    @property
    def max_evidence_per_doc(self) -> int | None:
        return self.budget.max_evidence_per_doc

    @property
    def citation_budget(self) -> int | None:
        return self.budget.citation_budget

    def constructor_dict(self) -> dict[str, Any]:
        return {
            "query_type": self.query_type,
            "normalized_query": self.normalized_query,
            "budget": self.budget,
            "planner_version": self.planner_version,
            "config_sha256": self.config_sha256,
            "entities": self.entities,
            "resolved_doc_ids": self.resolved_doc_ids,
            "inherited_doc_ids": self.inherited_doc_ids,
            "scope_state": self.scope_state,
            "scope_origin": self.scope_origin,
            "constraints": self.constraints,
            "metadata_predicates": self.metadata_predicates,
            "required_slots": self.required_slots,
            "allow_global_fallback": self.allow_global_fallback,
            "unresolved_constraints": self.unresolved_constraints,
        }

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "query_type": self.query_type,
            "normalized_query": self.normalized_query,
            "entities": [value.to_dict() for value in self.entities],
            "resolved_doc_ids": list(self.resolved_doc_ids),
            "inherited_doc_ids": list(self.inherited_doc_ids),
            "scope_state": self.scope_state,
            "scope_origin": self.scope_origin,
            "constraints": [value.to_dict() for value in self.constraints],
            "metadata_predicates": [value.to_dict() for value in self.metadata_predicates],
            "required_slots": [value.to_dict() for value in self.required_slots],
            "allow_global_fallback": self.allow_global_fallback,
            "unresolved_constraints": list(self.unresolved_constraints),
            "planner_version": self.planner_version,
            "config_sha256": self.config_sha256,
        }
        payload.update(self.budget.to_dict())
        return payload

    @classmethod
    def from_dict(
        cls, raw: Mapping[str, Any], *, registry: RuleRegistry
    ) -> QueryPlan:
        if type(registry) is not RuleRegistry:
            raise TypeError("rule_registry_required")
        _closed(raw, _PLAN_FIELDS, "query_plan_fields")
        if raw["schema_version"] != SCHEMA_VERSION:
            raise ValueError("unsupported_query_plan_version")
        array_fields = (
            "entities",
            "resolved_doc_ids",
            "inherited_doc_ids",
            "constraints",
            "metadata_predicates",
            "required_slots",
            "unresolved_constraints",
        )
        for name in array_fields:
            _json_array(raw[name], f"query_plan_{name}_array")
        budget = RetrievalBudget.from_dict({name: raw[name] for name in _BUDGET_FIELDS})
        plan = cls(
            query_type=raw["query_type"],
            normalized_query=raw["normalized_query"],
            budget=budget,
            planner_version=raw["planner_version"],
            config_sha256=raw["config_sha256"],
            entities=tuple(PlanEntity.from_dict(value) for value in raw["entities"]),
            resolved_doc_ids=raw["resolved_doc_ids"],
            inherited_doc_ids=raw["inherited_doc_ids"],
            scope_state=raw["scope_state"],
            scope_origin=raw["scope_origin"],
            constraints=tuple(PlanConstraint.from_dict(value) for value in raw["constraints"]),
            metadata_predicates=tuple(
                _metadata_predicate_from_dict(value) for value in raw["metadata_predicates"]
            ),
            required_slots=tuple(RequiredSlot.from_dict(value) for value in raw["required_slots"]),
            allow_global_fallback=raw["allow_global_fallback"],
            unresolved_constraints=raw["unresolved_constraints"],
        )
        registry.validate_plan(plan)
        return plan


@dataclass(frozen=True, slots=True)
class RuleRegistry:
    registry_version: str
    budgets: tuple[BudgetRule, ...]
    rules: tuple[RoutingRule, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "registry_version",
            _text(self.registry_version, "invalid_registry_version", maximum=128),
        )
        budgets = tuple(self.budgets)
        rules = tuple(self.rules)
        if any(type(value) is not BudgetRule for value in budgets):
            raise TypeError("invalid_budget_rules")
        if any(type(value) is not RoutingRule for value in rules):
            raise TypeError("invalid_routing_rules")
        budget_types = tuple(value.query_type for value in budgets)
        if len(budget_types) != len(set(budget_types)) or set(budget_types) != set(QUERY_TYPES):
            raise ValueError("budget_query_types")
        rule_ids = tuple(value.rule_id for value in rules)
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("duplicate_rule_ids")
        order = {value: index for index, value in enumerate(QUERY_TYPES)}
        object.__setattr__(self, "budgets", tuple(sorted(budgets, key=lambda value: order[value.query_type])))
        object.__setattr__(self, "rules", tuple(sorted(rules, key=lambda value: (-value.priority, value.rule_id))))

    @property
    def query_types(self) -> tuple[str, ...]:
        return tuple(rule.query_type for rule in self.budgets)

    def budget_for(self, query_type: str) -> RetrievalBudget:
        query_type = _query_type(query_type)
        return next(rule.budget for rule in self.budgets if rule.query_type == query_type)

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "registry_version": self.registry_version,
            "budgets": [value.to_dict() for value in self.budgets],
            "rules": [value.to_dict() for value in self.rules],
        }

    @property
    def config_sha256(self) -> str:
        return _canonical_sha256(self._payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "config_sha256": self.config_sha256}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> RuleRegistry:
        _closed(raw, _REGISTRY_FIELDS, "registry_fields")
        if raw["schema_version"] != SCHEMA_VERSION:
            raise ValueError("unsupported_registry_version")
        budgets = _json_array(raw["budgets"], "registry_budgets_array")
        rules = _json_array(raw["rules"], "registry_rules_array")
        registry = cls(
            registry_version=raw["registry_version"],
            budgets=tuple(BudgetRule.from_dict(value) for value in budgets),
            rules=tuple(RoutingRule.from_dict(value) for value in rules),
        )
        if raw["config_sha256"] != registry.config_sha256:
            raise ValueError("config_sha256_mismatch")
        return registry

    def make_plan(
        self,
        *,
        query_type: str,
        normalized_query: str,
        entities: Iterable[PlanEntity] = (),
        resolved_doc_ids: Iterable[str] = (),
        inherited_doc_ids: Iterable[str] = (),
        scope_state: str | None = None,
        scope_origin: str | None = None,
        constraints: Iterable[PlanConstraint] = (),
        metadata_predicates: Iterable[MetadataPredicate] = (),
        required_slots: Iterable[RequiredSlot] = (),
        allow_global_fallback: bool = False,
        unresolved_constraints: Iterable[str] = (),
    ) -> QueryPlan:
        query_type = _query_type(query_type)
        resolved_doc_ids = tuple(resolved_doc_ids)
        if scope_state is None:
            scope_state = "restricted" if resolved_doc_ids else "unfiltered"
        if scope_origin is None:
            scope_origin = "entity_resolution" if resolved_doc_ids else "all"
        return QueryPlan(
            query_type=query_type,
            normalized_query=normalized_query,
            budget=self.budget_for(query_type),
            planner_version=self.registry_version,
            config_sha256=self.config_sha256,
            entities=tuple(entities),
            resolved_doc_ids=resolved_doc_ids,
            inherited_doc_ids=tuple(inherited_doc_ids),
            scope_state=scope_state,
            scope_origin=scope_origin,
            constraints=tuple(constraints),
            metadata_predicates=tuple(metadata_predicates),
            required_slots=tuple(required_slots),
            allow_global_fallback=allow_global_fallback,
            unresolved_constraints=tuple(unresolved_constraints),
        )

    def validate_plan(self, plan: QueryPlan) -> None:
        if type(plan) is not QueryPlan:
            raise TypeError("query_plan_required")
        if (
            plan.planner_version != self.registry_version
            or plan.config_sha256 != self.config_sha256
            or plan.budget != self.budget_for(plan.query_type)
        ):
            raise ValueError("plan_registry_mismatch")

    def plan_from_dict(self, raw: Mapping[str, Any]) -> QueryPlan:
        return QueryPlan.from_dict(raw, registry=self)


def default_rule_registry() -> RuleRegistry:
    budgets = (
        BudgetRule("fact", RetrievalBudget(30, 30, 40, 6, 6, 6)),
        BudgetRule("compare", RetrievalBudget(50, 50, 60, 10, 2, 10)),
        BudgetRule("follow_up", RetrievalBudget(20, 20, 30, 6, 6, 6)),
        BudgetRule("exhaustive_list", RetrievalBudget(80, 80, None, None, None, None)),
        BudgetRule("analytics", RetrievalBudget(0, 0, 0, 0, 0, None)),
        BudgetRule("table_visual", RetrievalBudget(30, 30, 30, 8, 4, 8)),
        BudgetRule("unknown_or_out_of_scope", RetrievalBudget(0, 0, 0, 0, 0, 0)),
    )
    rules = (
        RoutingRule(
            "query.compare.v1",
            "query_expression",
            "compare",
            ("비교", "비교해줘", "비교해주세요", "비교하면", "비교해서", "비교하여", "차이", "차이점"),
            120,
        ),
        RoutingRule(
            "query.exhaustive-list.v1",
            "query_expression",
            "exhaustive_list",
            ("전체", "전부", "모두", "모든", "목록"),
            100,
        ),
        RoutingRule(
            "query.analytics.v1",
            "query_expression",
            "analytics",
            (
                "상위", "평균", "합계", "개수", "건수", "몇 개", "몇개",
                "몇 개인가", "몇 건", "몇건", "몇 건인가", "몇 건인가요",
                "몇건인가", "몇건인가요", "중앙값",
            ),
            110,
        ),
        RoutingRule(
            "query.table-visual.v1",
            "query_expression",
            "table_visual",
            (
                "표에", "표에서", "표의", "표를", "표로", "표 내용", "구성표",
                "평가표", "배점표", "가점표", "일정표", "그림", "도표", "조직도", "아키텍처",
            ),
            90,
        ),
        RoutingRule(
            "history.citation.v1",
            "history_citation",
            "follow_up",
            (
                "그 사업", "그 사업의", "그 사업은", "그 사업이", "그 사업을",
                "그 문서", "그 문서의", "그 문서는", "그 문서가", "그 문서를",
                "그중", "그중에서", "위 사업", "앞서", "그러면", "그럼", "이 중",
            ),
            130,
        ),
    )
    return RuleRegistry("planner-rules-v1", budgets, rules)
