"""Planner-, catalog-, and store-bound fact execution authority.

This module is provider-free.  It seals a deterministic fact plan against the
exact runtime request, planner, catalog, rule registry, and live evidence graph
before any retrieval query may be emitted.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import json
import math
import re
from types import MappingProxyType
from typing import Any
from weakref import ReferenceType, ref

from midprojectrag.evidence import EvidenceStore, validate_evidence_store_snapshot
from midprojectrag.runtime_integrity import (
    MetadataPredicate,
    RuntimeRequest,
    validate_runtime_request_snapshot,
)

from .contracts import (
    BudgetRule,
    PlanConstraint,
    PlanEntity,
    QueryPlan,
    RequiredSlot,
    RetrievalBudget,
    RoutingRule,
    RuleRegistry,
    default_rule_registry,
)
from .planner import (
    CatalogDocument,
    CatalogEntity,
    DeterministicPlanner,
    PlanningCatalog,
    PlanningResult,
    PlanningTrace,
)


_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_FACT_BINDING_TOKEN = object()
_FACT_TRACE_TOKEN = object()
_FACT_STATUSES = frozenset({"ready", "not_ready"})
_FACT_REASONS = frozenset(
    {
        "ready",
        "fact_scope_empty",
        "fact_metadata_unresolved",
        "fact_metadata_scope_receipt_required",
        "fact_scope_unresolved",
        "fact_catalog_universe_empty",
        "fact_document_not_in_catalog",
        "fact_document_not_in_store",
    }
)
_MAPPING_PROXY_TYPE = type(MappingProxyType({}))


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_hash(value: Any, code: str) -> str:
    if type(value) is not str or not _HEX64.fullmatch(value):
        raise ValueError(code)
    return value


def _require_ids(value: Any, code: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(code)
    if any(type(item) is not str or not item for item in value):
        raise ValueError(code)
    if len(value) != len(set(value)):
        raise ValueError(f"duplicate_{code}")
    return value


def _strict_json_value(value: Any, code: str) -> None:
    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(code)
        return
    if type(value) is list:
        for item in value:
            _strict_json_value(item, code)
        return
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise TypeError(code)
        for item in value.values():
            _strict_json_value(item, code)
        return
    raise TypeError(code)


def _exact_string_tuple(value: Any) -> bool:
    return type(value) is tuple and all(type(item) is str for item in value)


def _safe_frozen_json(value: Any) -> bool:
    if value is None or type(value) in {str, bool, int}:
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is tuple:
        return all(_safe_frozen_json(item) for item in value)
    if type(value) is _MAPPING_PROXY_TYPE:
        return all(
            type(key) is str and _safe_frozen_json(item)
            for key, item in value.items()
        )
    return False


def _safe_predicate_value(value: Any) -> bool:
    """Validate the planner's closed scalar-or-tuple predicate value shape.

    MetadataPredicate never legitimately contains mappings.  Keeping this
    narrower than ``_safe_frozen_json`` lets the planning boundary reject a
    forged mapping proxy without invoking its backing mapping.
    """

    if value is None or type(value) in {str, bool, int}:
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is tuple:
        return all(_safe_predicate_value(item) for item in value)
    return False


def _validate_budget_types(budget: Any) -> None:
    if type(budget) is not RetrievalBudget:
        raise ValueError("fact_registry_child_type_drift")
    for name in (
        "dense_k",
        "lexical_k",
        "rerank_k",
        "final_evidence_budget",
        "max_evidence_per_doc",
        "citation_budget",
    ):
        value = getattr(budget, name)
        if value is not None and type(value) is not int:
            raise ValueError("fact_registry_child_type_drift")


def _validate_planner_children_before_calls(planner: Any) -> None:
    """Reject forged child types before any overridable method is called."""

    if type(planner) is not DeterministicPlanner:
        raise TypeError("deterministic_planner_required")
    registry = planner.registry
    catalog = planner.catalog
    if type(registry) is not RuleRegistry or type(catalog) is not PlanningCatalog:
        raise ValueError("fact_planner_child_type_drift")
    if type(registry.registry_version) is not str:
        raise ValueError("fact_registry_child_type_drift")
    if type(registry.budgets) is not tuple or type(registry.rules) is not tuple:
        raise ValueError("fact_registry_child_type_drift")
    for rule in registry.budgets:
        if type(rule) is not BudgetRule or type(rule.query_type) is not str:
            raise ValueError("fact_registry_child_type_drift")
        _validate_budget_types(rule.budget)
    for rule in registry.rules:
        if (
            type(rule) is not RoutingRule
            or any(
                type(value) is not str
                for value in (rule.rule_id, rule.source, rule.output_query_type)
            )
            or type(rule.priority) is not int
            or not _exact_string_tuple(rule.signals)
        ):
            raise ValueError("fact_registry_child_type_drift")
    if any(
        type(value) is not str
        for value in (
            catalog.catalog_version,
            catalog.source_kind,
            catalog.source_sha256,
        )
    ):
        raise ValueError("fact_catalog_child_type_drift")
    if type(catalog.entities) is not tuple or type(catalog.source_documents) is not tuple:
        raise ValueError("fact_catalog_child_type_drift")
    for entity in catalog.entities:
        if (
            type(entity) is not CatalogEntity
            or any(
                type(value) is not str
                for value in (
                    entity.alias,
                    entity.canonical_value,
                    entity.kind,
                    entity.source,
                )
            )
            or not _exact_string_tuple(entity.doc_ids)
        ):
            raise ValueError("fact_catalog_child_type_drift")
    for document in catalog.source_documents:
        if type(document) is not CatalogDocument or any(
            type(value) is not str
            for value in (
                document.doc_id,
                document.title,
                document.agency,
                document.filename,
            )
        ):
            raise ValueError("fact_catalog_child_type_drift")


def _validate_planning_children_before_calls(planning: Any) -> None:
    if type(planning) is not PlanningResult:
        raise TypeError("fact_planning_result_required")
    plan = planning.plan
    trace = planning.trace
    if type(plan) is not QueryPlan or type(trace) is not PlanningTrace:
        raise TypeError("fact_planning_result_required")
    _validate_budget_types(plan.budget)
    for value in (
        plan.query_type,
        plan.normalized_query,
        plan.planner_version,
        plan.config_sha256,
        plan.scope_state,
        plan.scope_origin,
    ):
        if type(value) is not str:
            raise ValueError("fact_planning_child_type_drift")
    if any(
        not _exact_string_tuple(value)
        for value in (
            plan.resolved_doc_ids,
            plan.inherited_doc_ids,
            plan.unresolved_constraints,
        )
    ):
        raise ValueError("fact_planning_child_type_drift")
    if (
        type(plan.entities) is not tuple
        or type(plan.constraints) is not tuple
        or type(plan.metadata_predicates) is not tuple
        or type(plan.required_slots) is not tuple
        or type(plan.allow_global_fallback) is not bool
    ):
        raise ValueError("fact_planning_child_type_drift")
    for entity in plan.entities:
        if (
            type(entity) is not PlanEntity
            or any(type(value) is not str for value in (entity.value, entity.kind, entity.source))
            or not _exact_string_tuple(entity.resolved_doc_ids)
        ):
            raise ValueError("fact_planning_child_type_drift")
    for constraint in plan.constraints:
        if type(constraint) is not PlanConstraint or any(
            type(value) is not str
            for value in (
                constraint.kind,
                constraint.value,
                constraint.source,
                constraint.status,
            )
        ):
            raise ValueError("fact_planning_child_type_drift")
    for predicate in plan.metadata_predicates:
        if (
            type(predicate) is not MetadataPredicate
            or type(predicate.field) is not str
            or type(predicate.operator) is not str
            or not _safe_predicate_value(predicate.value)
        ):
            raise ValueError("fact_planning_child_type_drift")
    for slot in plan.required_slots:
        if type(slot) is not RequiredSlot or any(
            type(value) is not str for value in (slot.doc_id, slot.field)
        ):
            raise ValueError("fact_planning_child_type_drift")
    for value in (
        trace.request_fingerprint,
        trace.config_sha256,
        trace.catalog_sha256,
        trace.catalog_source_kind,
        trace.catalog_source_sha256,
        trace.execution_kind,
        trace.scope_state,
        trace.scope_origin,
    ):
        if type(value) is not str:
            raise ValueError("fact_planning_child_type_drift")
    if any(
        not _exact_string_tuple(value)
        for value in (
            trace.matched_rule_ids,
            trace.matched_rule_sources,
            trace.resolved_doc_ids,
            trace.predicate_statuses,
        )
    ):
        raise ValueError("fact_planning_child_type_drift")


def _validate_request_before_calls(request: Any) -> RuntimeRequest:
    if type(request) is not RuntimeRequest:
        raise TypeError("runtime_request_required")
    try:
        validate_runtime_request_snapshot(request)
    except (TypeError, ValueError) as exc:
        raise ValueError("fact_request_payload_drift") from exc
    if type(request.question) is not str or type(request.request_id) is not str:
        raise ValueError("fact_request_child_type_drift")
    for value in (
        request.history,
        request.document_scope,
        request.metadata_filters,
        request.options,
        request.prior_citation_state,
    ):
        if not _safe_frozen_json(value):
            raise ValueError("fact_request_child_type_drift")
    try:
        payload = RuntimeRequest.to_dict(request)
        canonical = RuntimeRequest.from_dict(payload)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("fact_request_payload_drift") from exc
    if canonical.to_dict() != payload:
        raise ValueError("fact_request_payload_drift")
    return canonical


def _planning_payload_hashes(
    planning: PlanningResult,
    registry: RuleRegistry,
) -> tuple[str, str, str]:
    """Reconstruct plan and trace through their closed public contracts."""

    _validate_planning_children_before_calls(planning)
    try:
        canonical_plan = registry.plan_from_dict(planning.plan.to_dict())
        trace_payload = planning.trace.to_dict()
        canonical_trace = PlanningTrace(**trace_payload)
        canonical = PlanningResult(canonical_plan, canonical_trace)
        supplied_payload = planning.to_dict()
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("fact_planning_integrity_mismatch") from exc
    if _canonical_json(supplied_payload) != _canonical_json(canonical.to_dict()):
        raise ValueError("fact_planning_integrity_mismatch")
    return (
        _canonical_sha256(trace_payload),
        _canonical_sha256(canonical.to_dict()),
        _canonical_sha256(canonical_plan.to_dict()),
    )


def _catalog_universe(catalog: PlanningCatalog) -> tuple[str, ...]:
    if catalog.source_kind == "production_metadata":
        return tuple(sorted(document.doc_id for document in catalog.source_documents))
    return tuple(
        sorted({doc_id for entity in catalog.entities for doc_id in entity.doc_ids})
    )


def _catalog_universe_sha256(
    catalog: PlanningCatalog,
    doc_ids: tuple[str, ...],
) -> str:
    return _canonical_sha256(
        {
            "schema_version": "1.0",
            "catalog_source_kind": catalog.source_kind,
            "catalog_doc_ids": list(doc_ids),
        }
    )


def _binding_reason(
    *,
    plan: QueryPlan,
    predicate_statuses: tuple[str, ...],
    catalog_doc_ids: tuple[str, ...],
    store: EvidenceStore,
) -> tuple[str, str]:
    if plan.scope_state == "empty":
        return "not_ready", "fact_scope_empty"
    if predicate_statuses and any(value != "supported" for value in predicate_statuses):
        return "not_ready", "fact_metadata_unresolved"
    if predicate_statuses:
        return "not_ready", "fact_metadata_scope_receipt_required"
    if plan.unresolved_constraints:
        return "not_ready", "fact_scope_unresolved"
    if not catalog_doc_ids:
        return "not_ready", "fact_catalog_universe_empty"
    if plan.scope_state == "restricted":
        catalog_ids = frozenset(catalog_doc_ids)
        resolved_ids = frozenset(plan.resolved_doc_ids)
        if not resolved_ids.issubset(catalog_ids):
            return "not_ready", "fact_document_not_in_catalog"
        if not resolved_ids.issubset(store.doc_ids):
            return "not_ready", "fact_document_not_in_store"
    return "ready", "ready"


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class FactBindingTrace:
    request_fingerprint: str
    config_sha256: str
    catalog_sha256: str
    catalog_source_kind: str
    catalog_source_sha256: str
    execution_kind: str
    planning_trace_sha256: str
    planning_result_sha256: str
    effective_plan_sha256: str
    catalog_doc_ids: tuple[str, ...]
    catalog_universe_sha256: str
    evidence_bundle_sha256: str
    scope_state: str
    scope_origin: str
    resolved_doc_ids: tuple[str, ...]
    status: str
    reason: str
    trace_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("fact_binding_trace_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        request_fingerprint: str,
        config_sha256: str,
        catalog_sha256: str,
        catalog_source_kind: str,
        catalog_source_sha256: str,
        execution_kind: str,
        planning_trace_sha256: str,
        planning_result_sha256: str,
        effective_plan_sha256: str,
        catalog_doc_ids: tuple[str, ...],
        catalog_universe_sha256: str,
        evidence_bundle_sha256: str,
        scope_state: str,
        scope_origin: str,
        resolved_doc_ids: tuple[str, ...],
        status: str,
        reason: str,
        _token: object,
    ) -> FactBindingTrace:
        if _token is not _FACT_TRACE_TOKEN:
            raise ValueError("fact_binding_trace_factory_required")
        result = object.__new__(cls)
        values = {
            "request_fingerprint": request_fingerprint,
            "config_sha256": config_sha256,
            "catalog_sha256": catalog_sha256,
            "catalog_source_kind": catalog_source_kind,
            "catalog_source_sha256": catalog_source_sha256,
            "execution_kind": execution_kind,
            "planning_trace_sha256": planning_trace_sha256,
            "planning_result_sha256": planning_result_sha256,
            "effective_plan_sha256": effective_plan_sha256,
            "catalog_doc_ids": catalog_doc_ids,
            "catalog_universe_sha256": catalog_universe_sha256,
            "evidence_bundle_sha256": evidence_bundle_sha256,
            "scope_state": scope_state,
            "scope_origin": scope_origin,
            "resolved_doc_ids": resolved_doc_ids,
            "status": status,
            "reason": reason,
        }
        for name, value in values.items():
            object.__setattr__(result, name, value)
        object.__setattr__(result, "trace_sha256", _canonical_sha256(result._payload()))
        result._validate()
        return result

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "request_fingerprint": self.request_fingerprint,
            "config_sha256": self.config_sha256,
            "catalog_sha256": self.catalog_sha256,
            "catalog_source_kind": self.catalog_source_kind,
            "catalog_source_sha256": self.catalog_source_sha256,
            "execution_kind": self.execution_kind,
            "planning_trace_sha256": self.planning_trace_sha256,
            "planning_result_sha256": self.planning_result_sha256,
            "effective_plan_sha256": self.effective_plan_sha256,
            "catalog_doc_ids": list(self.catalog_doc_ids),
            "catalog_universe_sha256": self.catalog_universe_sha256,
            "evidence_bundle_sha256": self.evidence_bundle_sha256,
            "scope_state": self.scope_state,
            "scope_origin": self.scope_origin,
            "resolved_doc_ids": list(self.resolved_doc_ids),
            "status": self.status,
            "reason": self.reason,
        }

    def _validate(self) -> None:
        for name in (
            "request_fingerprint",
            "config_sha256",
            "catalog_sha256",
            "catalog_source_sha256",
            "planning_trace_sha256",
            "planning_result_sha256",
            "effective_plan_sha256",
            "catalog_universe_sha256",
            "evidence_bundle_sha256",
            "trace_sha256",
        ):
            _require_hash(getattr(self, name), f"invalid_{name}")
        if self.catalog_source_kind not in {
            "production_metadata",
            "synthetic_fixture",
        }:
            raise ValueError("invalid_fact_catalog_source_kind")
        if self.execution_kind not in {"production", "synthetic"}:
            raise ValueError("invalid_fact_execution_kind")
        if (self.catalog_source_kind == "synthetic_fixture") != (
            self.execution_kind == "synthetic"
        ):
            raise ValueError("fact_execution_kind_mismatch")
        catalog_ids = _require_ids(self.catalog_doc_ids, "fact_catalog_doc_ids")
        resolved_ids = _require_ids(self.resolved_doc_ids, "fact_resolved_doc_ids")
        if catalog_ids != tuple(sorted(catalog_ids)):
            raise ValueError("fact_catalog_doc_order_mismatch")
        if self.scope_state not in {"empty", "restricted", "unfiltered"}:
            raise ValueError("invalid_fact_scope_state")
        if (self.scope_state == "restricted") != bool(resolved_ids):
            raise ValueError("inconsistent_fact_scope")
        if type(self.scope_origin) is not str or not self.scope_origin:
            raise ValueError("invalid_fact_scope_origin")
        if self.status not in _FACT_STATUSES or self.reason not in _FACT_REASONS:
            raise ValueError("invalid_fact_binding_disposition")
        if (self.status == "ready") != (self.reason == "ready"):
            raise ValueError("inconsistent_fact_binding_disposition")
        if self.trace_sha256 != _canonical_sha256(self._payload()):
            raise ValueError("fact_binding_trace_hash_mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "trace_sha256": self.trace_sha256}


@dataclass(frozen=True, slots=True, weakref_slot=True)
class _BoundFactAuthority:
    weak: ReferenceType[BoundFact]
    payload_sha256: str
    planning: PlanningResult
    planning_plan: QueryPlan
    planning_trace: PlanningTrace
    trace: FactBindingTrace
    request: RuntimeRequest
    request_children: tuple[Any, ...]
    planner: DeterministicPlanner
    registry: RuleRegistry
    registry_children: tuple[Any, ...]
    catalog: PlanningCatalog
    catalog_children: tuple[Any, ...]
    catalog_source_sha256: str
    store: EvidenceStore


_BOUND_FACT_AUTHORITIES: dict[int, _BoundFactAuthority] = {}


def _drop_bound_fact_authority(identity: int, dead: ReferenceType[Any]) -> None:
    current = _BOUND_FACT_AUTHORITIES.get(identity)
    if current is not None and current.weak is dead:
        _BOUND_FACT_AUTHORITIES.pop(identity, None)


def _bound_fact_payload(
    planning: PlanningResult,
    trace: FactBindingTrace,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "planning": planning.to_dict(),
        "trace": trace.to_dict(),
    }


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class BoundFact:
    planning: PlanningResult
    trace: FactBindingTrace
    binding_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("bound_fact_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        planning: PlanningResult,
        trace: FactBindingTrace,
        request: RuntimeRequest,
        planner: DeterministicPlanner,
        store: EvidenceStore,
        _token: object,
    ) -> BoundFact:
        if _token is not _FACT_BINDING_TOKEN:
            raise ValueError("bound_fact_factory_required")
        result = object.__new__(cls)
        object.__setattr__(result, "planning", planning)
        object.__setattr__(result, "trace", trace)
        object.__setattr__(
            result,
            "binding_sha256",
            _canonical_sha256(_bound_fact_payload(planning, trace)),
        )
        weak = ref(
            result,
            lambda dead, identity=id(result): _drop_bound_fact_authority(
                identity, dead
            ),
        )
        registry = planner.registry
        catalog = planner.catalog
        _BOUND_FACT_AUTHORITIES[id(result)] = _BoundFactAuthority(
            weak=weak,
            payload_sha256=_canonical_sha256(result.to_dict()),
            planning=planning,
            planning_plan=planning.plan,
            planning_trace=planning.trace,
            trace=trace,
            request=request,
            request_children=(
                request.history,
                request.document_scope,
                request.metadata_filters,
                request.options,
                request.prior_citation_state,
            ),
            planner=planner,
            registry=registry,
            registry_children=(
                registry.budgets,
                registry.rules,
                *registry.budgets,
                *registry.rules,
            ),
            catalog=catalog,
            catalog_children=(
                catalog.entities,
                catalog.source_documents,
                *catalog.entities,
                *catalog.source_documents,
            ),
            catalog_source_sha256=catalog.source_sha256,
            store=store,
        )
        _require_bound_fact_authority(result, store=store)
        return result

    @property
    def plan(self) -> QueryPlan:
        return self.planning.plan

    def to_dict(self) -> dict[str, Any]:
        return {
            **_bound_fact_payload(self.planning, self.trace),
            "binding_sha256": self.binding_sha256,
        }


def _validate_planner_authority(authority: _BoundFactAuthority) -> None:
    planner = authority.planner
    try:
        _validate_planner_children_before_calls(planner)
    except (TypeError, ValueError) as exc:
        raise ValueError("bound_fact_planner_type_drift") from exc
    if planner.registry is not authority.registry or planner.catalog is not authority.catalog:
        raise ValueError("bound_fact_planner_identity_drift")
    registry = authority.registry
    catalog = authority.catalog
    if (
        authority.registry_children[0] is not registry.budgets
        or authority.registry_children[1] is not registry.rules
        or any(
            issued is not actual
            for issued, actual in zip(
                authority.registry_children[2:],
                (*registry.budgets, *registry.rules),
            )
        )
        or len(authority.registry_children[2:])
        != len((*registry.budgets, *registry.rules))
    ):
        raise ValueError("bound_fact_registry_identity_drift")
    if (
        authority.catalog_children[0] is not catalog.entities
        or authority.catalog_children[1] is not catalog.source_documents
        or any(
            issued is not actual
            for issued, actual in zip(
                authority.catalog_children[2:],
                (*catalog.entities, *catalog.source_documents),
            )
        )
        or len(authority.catalog_children[2:])
        != len((*catalog.entities, *catalog.source_documents))
    ):
        raise ValueError("bound_fact_catalog_identity_drift")
    try:
        canonical_registry = RuleRegistry.from_dict(registry.to_dict())
        canonical_catalog = PlanningCatalog.from_dict(
            catalog.to_dict(),
            expected_source_sha256=authority.catalog_source_sha256,
        )
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("bound_fact_planner_payload_drift") from exc
    approved = default_rule_registry()
    if (
        canonical_registry.config_sha256 != approved.config_sha256
        or registry.config_sha256 != approved.config_sha256
    ):
        raise ValueError("bound_fact_registry_payload_drift")
    if canonical_catalog.to_dict() != catalog.to_dict():
        raise ValueError("bound_fact_catalog_payload_drift")


def _validate_request_authority(authority: _BoundFactAuthority) -> None:
    request = authority.request
    current_children = (
        request.history,
        request.document_scope,
        request.metadata_filters,
        request.options,
        request.prior_citation_state,
    )
    if any(
        issued is not actual
        for issued, actual in zip(authority.request_children, current_children)
    ):
        raise ValueError("bound_fact_request_identity_drift")
    try:
        _validate_request_before_calls(request)
    except (TypeError, ValueError) as exc:
        raise ValueError("bound_fact_request_payload_drift") from exc


def _validate_bound_fact_scalar_types(bound: BoundFact) -> None:
    """Reject forged scalar subclasses before hashing or set membership."""

    if type(bound.binding_sha256) is not str:
        raise ValueError("invalid_binding_sha256")
    _require_hash(bound.binding_sha256, "invalid_binding_sha256")
    trace = bound.trace
    if type(trace) is not FactBindingTrace:
        raise ValueError("bound_fact_trace_child_type_drift")
    hash_fields = (
        "request_fingerprint",
        "config_sha256",
        "catalog_sha256",
        "catalog_source_sha256",
        "planning_trace_sha256",
        "planning_result_sha256",
        "effective_plan_sha256",
        "catalog_universe_sha256",
        "evidence_bundle_sha256",
        "trace_sha256",
    )
    for name in hash_fields:
        _require_hash(getattr(trace, name), f"invalid_{name}")
    for name in (
        "catalog_source_kind",
        "execution_kind",
        "scope_state",
        "scope_origin",
        "status",
        "reason",
    ):
        if type(getattr(trace, name)) is not str:
            raise ValueError("bound_fact_trace_child_type_drift")
    _require_ids(trace.catalog_doc_ids, "fact_catalog_doc_ids")
    _require_ids(trace.resolved_doc_ids, "fact_resolved_doc_ids")


def _require_bound_fact_authority(
    bound: BoundFact,
    *,
    store: EvidenceStore,
) -> _BoundFactAuthority:
    if type(bound) is not BoundFact:
        raise TypeError("bound_fact_required")
    authority = _BOUND_FACT_AUTHORITIES.get(id(bound))
    if authority is None or authority.weak() is not bound:
        raise ValueError("bound_fact_runtime_authority_required")
    if (
        bound.planning is not authority.planning
        or bound.trace is not authority.trace
        or bound.planning.plan is not authority.planning_plan
        or bound.planning.trace is not authority.planning_trace
    ):
        raise ValueError("bound_fact_nested_identity_drift")
    _validate_bound_fact_scalar_types(bound)
    if type(store) is not EvidenceStore:
        raise TypeError("evidence_store_required")
    if store is not authority.store:
        raise ValueError("bound_fact_store_identity_mismatch")
    _validate_planner_authority(authority)
    _validate_request_authority(authority)
    try:
        validate_evidence_store_snapshot(store, bound.trace.evidence_bundle_sha256)
    except ValueError as exc:
        if str(exc) == "evidence_store_bundle_mismatch":
            raise ValueError("bound_fact_store_bundle_mismatch") from exc
        raise ValueError("bound_fact_store_payload_drift") from exc
    trace_hash, result_hash, plan_hash = _planning_payload_hashes(
        bound.planning,
        authority.registry,
    )
    try:
        replayed = DeterministicPlanner.plan(authority.planner, authority.request)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("bound_fact_planner_replay_failed") from exc
    if _canonical_json(replayed.to_dict()) != _canonical_json(bound.planning.to_dict()):
        raise ValueError("bound_fact_planning_replay_drift")
    bound.trace._validate()
    if (
        bound.trace.request_fingerprint != authority.request.fingerprint
        or bound.trace.config_sha256 != authority.registry.config_sha256
        or bound.trace.catalog_sha256 != authority.catalog.catalog_sha256
        or bound.trace.catalog_source_kind != authority.catalog.source_kind
        or bound.trace.catalog_source_sha256 != authority.catalog_source_sha256
        or bound.trace.execution_kind != bound.planning.trace.execution_kind
        or bound.trace.planning_trace_sha256 != trace_hash
        or bound.trace.planning_result_sha256 != result_hash
        or bound.trace.effective_plan_sha256 != plan_hash
        or bound.trace.evidence_bundle_sha256 != store.bundle_sha256
        or bound.trace.scope_state != bound.plan.scope_state
        or bound.trace.scope_origin != bound.plan.scope_origin
        or bound.trace.resolved_doc_ids != bound.plan.resolved_doc_ids
    ):
        raise ValueError("bound_fact_trace_source_mismatch")
    universe = _catalog_universe(authority.catalog)
    if (
        bound.trace.catalog_doc_ids != universe
        or bound.trace.catalog_universe_sha256
        != _catalog_universe_sha256(authority.catalog, universe)
    ):
        raise ValueError("bound_fact_catalog_universe_mismatch")
    expected_status, expected_reason = _binding_reason(
        plan=bound.plan,
        predicate_statuses=bound.planning.trace.predicate_statuses,
        catalog_doc_ids=universe,
        store=store,
    )
    if (bound.trace.status, bound.trace.reason) != (expected_status, expected_reason):
        raise ValueError("bound_fact_disposition_mismatch")
    if bound.binding_sha256 != _canonical_sha256(
        _bound_fact_payload(bound.planning, bound.trace)
    ):
        raise ValueError("bound_fact_hash_mismatch")
    if authority.payload_sha256 != _canonical_sha256(bound.to_dict()):
        raise ValueError("bound_fact_runtime_authority_drift")
    return authority


def bind_fact(
    *,
    request: RuntimeRequest,
    planning: PlanningResult,
    store: EvidenceStore,
    planner: DeterministicPlanner,
) -> BoundFact:
    """Seal one deterministic fact plan before retrieval."""

    if type(request) is not RuntimeRequest:
        raise TypeError("runtime_request_required")
    if type(planning) is not PlanningResult:
        raise TypeError("fact_planning_result_required")
    if type(store) is not EvidenceStore:
        raise TypeError("evidence_store_required")
    if type(planner) is not DeterministicPlanner:
        raise TypeError("deterministic_planner_required")
    _validate_request_before_calls(request)
    try:
        validate_evidence_store_snapshot(store, store.bundle_sha256)
    except ValueError as exc:
        raise ValueError("bound_fact_store_payload_drift") from exc
    _validate_planner_authority_for_binding(planner)
    trace_hash, result_hash, plan_hash = _planning_payload_hashes(
        planning,
        planner.registry,
    )
    replayed = DeterministicPlanner.plan(planner, request)
    if _canonical_json(replayed.to_dict()) != _canonical_json(planning.to_dict()):
        raise ValueError("fact_planning_replay_mismatch")
    if planning.plan.query_type != "fact":
        raise ValueError("fact_plan_required")
    universe = _catalog_universe(planner.catalog)
    status, reason = _binding_reason(
        plan=planning.plan,
        predicate_statuses=planning.trace.predicate_statuses,
        catalog_doc_ids=universe,
        store=store,
    )
    trace = FactBindingTrace._create(
        request_fingerprint=request.fingerprint,
        config_sha256=planner.registry.config_sha256,
        catalog_sha256=planner.catalog.catalog_sha256,
        catalog_source_kind=planner.catalog.source_kind,
        catalog_source_sha256=planner.catalog.source_sha256,
        execution_kind=planning.trace.execution_kind,
        planning_trace_sha256=trace_hash,
        planning_result_sha256=result_hash,
        effective_plan_sha256=plan_hash,
        catalog_doc_ids=universe,
        catalog_universe_sha256=_catalog_universe_sha256(planner.catalog, universe),
        evidence_bundle_sha256=store.bundle_sha256,
        scope_state=planning.plan.scope_state,
        scope_origin=planning.plan.scope_origin,
        resolved_doc_ids=planning.plan.resolved_doc_ids,
        status=status,
        reason=reason,
        _token=_FACT_TRACE_TOKEN,
    )
    return BoundFact._create(
        planning=planning,
        trace=trace,
        request=request,
        planner=planner,
        store=store,
        _token=_FACT_BINDING_TOKEN,
    )


def _validate_planner_authority_for_binding(planner: DeterministicPlanner) -> None:
    """Validate mutable-through-object.__setattr__ inputs before sealing them."""

    _validate_planner_children_before_calls(planner)
    try:
        canonical_registry = RuleRegistry.from_dict(planner.registry.to_dict())
        canonical_catalog = PlanningCatalog.from_dict(
            planner.catalog.to_dict(),
            expected_source_sha256=planner.catalog.source_sha256,
        )
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("fact_planner_integrity_mismatch") from exc
    if canonical_registry.config_sha256 != default_rule_registry().config_sha256:
        raise ValueError("unapproved_rule_registry")
    if canonical_catalog.to_dict() != planner.catalog.to_dict():
        raise ValueError("fact_catalog_integrity_mismatch")


def validate_bound_fact(*, bound: BoundFact, store: EvidenceStore) -> None:
    """Require the exact unchanged authority issued for the exact live store."""

    _require_bound_fact_authority(bound, store=store)


def replay_bound_fact(
    raw: Mapping[str, Any],
    *,
    request: RuntimeRequest,
    store: EvidenceStore,
    planner: DeterministicPlanner,
) -> BoundFact:
    """Rebuild from exact sources; never deserialize caller authority."""

    if type(raw) is not dict:
        raise TypeError("bound_fact_replay_mapping_required")
    _strict_json_value(raw, "bound_fact_replay_json_required")
    _validate_request_before_calls(request)
    _validate_planner_authority_for_binding(planner)
    if type(store) is not EvidenceStore:
        raise TypeError("evidence_store_required")
    try:
        validate_evidence_store_snapshot(store, store.bundle_sha256)
    except ValueError as exc:
        raise ValueError("bound_fact_store_payload_drift") from exc
    expected = bind_fact(
        request=request,
        planning=DeterministicPlanner.plan(planner, request),
        store=store,
        planner=planner,
    )
    if _canonical_json(raw) != _canonical_json(expected.to_dict()):
        raise ValueError("bound_fact_replay_payload_mismatch")
    return expected


__all__ = (
    "BoundFact",
    "FactBindingTrace",
    "bind_fact",
    "replay_bound_fact",
    "validate_bound_fact",
)
