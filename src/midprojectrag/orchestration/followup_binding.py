"""History- and store-bound citation authority for follow-up planning."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any
from weakref import ReferenceType, ref

from midprojectrag.evidence import EvidenceStore
from midprojectrag.runtime_integrity import RuntimeRequest

from .contracts import QueryPlan, RuleRegistry, SCOPE_ORIGINS
from .planner import PlanningResult, PlanningTrace


_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_BOUND_FOLLOWUP_TOKEN = object()
_BOUND_FOLLOWUP_AUTHORITIES: dict[
    int,
    tuple[
        ReferenceType[BoundFollowup],
        str,
        PlanningResult,
        VerifiedCitationState,
        FollowupBindingTrace,
        QueryPlan,
        PlanningTrace,
        EvidenceStore,
    ],
] = {}


def _sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def _require_hash(value: str, code: str) -> None:
    if type(value) is not str or not _HEX64.fullmatch(value):
        raise ValueError(code)


def _bound_followup_payload(bound: BoundFollowup) -> dict[str, Any]:
    """Return the complete public payload whose exact object carries authority."""

    return {
        "planning": bound.planning.to_dict(),
        "citations": bound.citations.to_dict(),
        "trace": bound.trace.to_dict(),
    }


def _drop_bound_followup_authority(
    identity: int, dead: ReferenceType[Any]
) -> None:
    current = _BOUND_FOLLOWUP_AUTHORITIES.get(identity)
    if current is not None and current[0] is dead:
        _BOUND_FOLLOWUP_AUTHORITIES.pop(identity, None)


def _register_bound_followup_authority(
    bound: BoundFollowup, *, store: EvidenceStore
) -> None:
    """Bind authority to one factory-issued identity and its full payload."""

    identity = id(bound)
    weak = ref(
        bound,
        lambda dead, identity=identity: _drop_bound_followup_authority(
            identity, dead
        ),
    )
    _BOUND_FOLLOWUP_AUTHORITIES[identity] = (
        weak,
        _sha256(_bound_followup_payload(bound)),
        bound.planning,
        bound.citations,
        bound.trace,
        bound.planning.plan,
        bound.planning.trace,
        store,
    )


def _require_bound_followup_authority(
    bound: BoundFollowup, *, store: EvidenceStore | None = None
) -> None:
    """Require the exact factory-issued, unchanged BoundFollowup instance."""

    if type(bound) is not BoundFollowup:
        raise TypeError("bound_followup_required")
    current = _BOUND_FOLLOWUP_AUTHORITIES.get(id(bound))
    if current is None or current[0]() is not bound:
        raise ValueError("bound_followup_runtime_authority_required")
    if (
        current[2] is not bound.planning
        or current[3] is not bound.citations
        or current[4] is not bound.trace
    ):
        raise ValueError("bound_followup_nested_identity_drift")
    if (
        type(bound.planning) is not PlanningResult
        or type(bound.citations) is not VerifiedCitationState
        or type(bound.trace) is not FollowupBindingTrace
    ):
        raise ValueError("bound_followup_nested_type_drift")
    if (
        current[5] is not bound.planning.plan
        or current[6] is not bound.planning.trace
    ):
        raise ValueError("bound_followup_planning_identity_drift")
    if (
        type(bound.planning.plan) is not QueryPlan
        or type(bound.planning.trace) is not PlanningTrace
    ):
        raise ValueError("bound_followup_planning_type_drift")
    if store is not None and current[7] is not store:
        raise ValueError("bound_followup_store_identity_mismatch")
    try:
        actual = _sha256(_bound_followup_payload(bound))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("bound_followup_runtime_authority_drift") from exc
    if current[1] != actual:
        raise ValueError("bound_followup_runtime_authority_drift")


@dataclass(frozen=True, slots=True, init=False)
class VerifiedCitationState:
    """Store- and history-bound citations; callers cannot construct it raw."""

    cited_doc_ids: tuple[str, ...]
    cited_evidence_ids: tuple[str, ...]
    evidence_bundle_sha256: str
    source_history_index: int
    request_fingerprint: str
    source_turn_sha256: str
    state_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("verified_citation_factory_required")

    @classmethod
    def bind(
        cls, request: RuntimeRequest, store: EvidenceStore
    ) -> VerifiedCitationState:
        if type(request) is not RuntimeRequest:
            raise TypeError("runtime_request_required")
        if type(store) is not EvidenceStore:
            raise TypeError("evidence_store_required")
        prior = request.prior_citation_state
        if prior is None:
            raise ValueError("followup_citation_state_required")
        cited_docs = tuple(prior["cited_doc_ids"])
        cited_evidence = tuple(prior["cited_evidence_ids"])
        if not cited_docs or not cited_evidence:
            raise ValueError("evidence_backed_citations_required")

        assistant_turn: tuple[int, Any] | None = None
        for index in range(len(request.history) - 1, -1, -1):
            turn = request.history[index]
            if turn["role"] == "assistant":
                assistant_turn = (index, turn)
                break
        if assistant_turn is None:
            raise ValueError("assistant_citation_history_required")
        history_index, turn = assistant_turn
        if (
            tuple(turn.get("cited_doc_ids", ())) != cited_docs
            or tuple(turn.get("cited_evidence_ids", ())) != cited_evidence
        ):
            raise ValueError("citation_state_history_mismatch")

        if not set(cited_docs).issubset(store.doc_ids):
            raise ValueError("unknown_cited_document")

        resolved_docs: set[str] = set()
        for evidence_id in cited_evidence:
            try:
                evidence = store.get(evidence_id)
            except KeyError as exc:
                raise ValueError("unknown_cited_evidence") from exc
            resolved_docs.add(evidence.doc_id)
        if set(cited_docs) != resolved_docs:
            raise ValueError("cited_document_evidence_mismatch")

        ordered_docs = tuple(sorted(resolved_docs))
        ordered_evidence = tuple(sorted(cited_evidence))
        source_turn_sha256 = _sha256(dict(turn))
        payload = {
            "schema_version": "1.0",
            "cited_doc_ids": list(ordered_docs),
            "cited_evidence_ids": list(ordered_evidence),
            "evidence_bundle_sha256": store.bundle_sha256,
            "source_history_index": history_index,
            "request_fingerprint": request.fingerprint,
            "source_turn_sha256": source_turn_sha256,
        }
        result = object.__new__(cls)
        object.__setattr__(result, "cited_doc_ids", ordered_docs)
        object.__setattr__(result, "cited_evidence_ids", ordered_evidence)
        object.__setattr__(result, "evidence_bundle_sha256", store.bundle_sha256)
        object.__setattr__(result, "source_history_index", history_index)
        object.__setattr__(result, "request_fingerprint", request.fingerprint)
        object.__setattr__(result, "source_turn_sha256", source_turn_sha256)
        object.__setattr__(result, "state_sha256", _sha256(payload))
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "cited_doc_ids": list(self.cited_doc_ids),
            "cited_evidence_ids": list(self.cited_evidence_ids),
            "evidence_bundle_sha256": self.evidence_bundle_sha256,
            "source_history_index": self.source_history_index,
            "request_fingerprint": self.request_fingerprint,
            "source_turn_sha256": self.source_turn_sha256,
            "state_sha256": self.state_sha256,
        }


@dataclass(frozen=True, slots=True)
class FollowupBindingTrace:
    request_fingerprint: str
    config_sha256: str
    prior_plan_sha256: str
    effective_plan_sha256: str
    evidence_bundle_sha256: str
    citation_state_sha256: str
    prior_scope_state: str
    prior_scope_origin: str
    prior_resolved_doc_ids: tuple[str, ...]
    effective_scope_state: str
    effective_scope_origin: str
    inherited_doc_ids: tuple[str, ...]
    fallback_authorized: bool
    ignored_resolved_entity_count: int
    ignored_list_doc_count: int
    ignored_comparison_doc_count: int

    def __post_init__(self) -> None:
        for name in (
            "request_fingerprint",
            "config_sha256",
            "prior_plan_sha256",
            "effective_plan_sha256",
            "evidence_bundle_sha256",
            "citation_state_sha256",
        ):
            _require_hash(getattr(self, name), f"invalid_{name}")
        if self.prior_scope_state not in {"unfiltered", "empty", "restricted"}:
            raise ValueError("invalid_prior_scope_state")
        if self.effective_scope_state not in {"empty", "restricted"}:
            raise ValueError("invalid_effective_followup_scope")
        if self.prior_scope_origin not in SCOPE_ORIGINS:
            raise ValueError("invalid_prior_scope_origin")
        if self.effective_scope_origin not in SCOPE_ORIGINS:
            raise ValueError("invalid_effective_scope_origin")
        prior_ids = tuple(self.prior_resolved_doc_ids)
        inherited = tuple(self.inherited_doc_ids)
        for name, values in (
            ("prior_resolved_doc_ids", prior_ids),
            ("inherited_doc_ids", inherited),
        ):
            if len(values) != len(set(values)) or any(
                type(value) is not str or not value for value in values
            ):
                raise ValueError(f"invalid_{name}")
        object.__setattr__(self, "prior_resolved_doc_ids", prior_ids)
        if (self.effective_scope_state == "restricted") != bool(inherited):
            raise ValueError("inconsistent_followup_scope")
        object.__setattr__(self, "inherited_doc_ids", inherited)
        if type(self.fallback_authorized) is not bool:
            raise TypeError("invalid_fallback_authorized")
        for name in (
            "ignored_resolved_entity_count",
            "ignored_list_doc_count",
            "ignored_comparison_doc_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"invalid_{name}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "request_fingerprint": self.request_fingerprint,
            "config_sha256": self.config_sha256,
            "prior_plan_sha256": self.prior_plan_sha256,
            "effective_plan_sha256": self.effective_plan_sha256,
            "evidence_bundle_sha256": self.evidence_bundle_sha256,
            "citation_state_sha256": self.citation_state_sha256,
            "prior_scope_state": self.prior_scope_state,
            "prior_scope_origin": self.prior_scope_origin,
            "prior_resolved_doc_ids": list(self.prior_resolved_doc_ids),
            "effective_scope_state": self.effective_scope_state,
            "effective_scope_origin": self.effective_scope_origin,
            "inherited_doc_ids": list(self.inherited_doc_ids),
            "fallback_authorized": self.fallback_authorized,
            "ignored_resolved_entity_count": self.ignored_resolved_entity_count,
            "ignored_list_doc_count": self.ignored_list_doc_count,
            "ignored_comparison_doc_count": self.ignored_comparison_doc_count,
        }


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class BoundFollowup:
    planning: PlanningResult
    citations: VerifiedCitationState
    trace: FollowupBindingTrace

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("bound_followup_factory_required")

    @classmethod
    def _from_binding(
        cls,
        planning: PlanningResult,
        citations: VerifiedCitationState,
        trace: FollowupBindingTrace,
        store: EvidenceStore,
        *,
        _token: object,
    ) -> BoundFollowup:
        if _token is not _BOUND_FOLLOWUP_TOKEN:
            raise ValueError("bound_followup_factory_required")
        result = object.__new__(cls)
        object.__setattr__(result, "planning", planning)
        object.__setattr__(result, "citations", citations)
        object.__setattr__(result, "trace", trace)
        result._validate_payload()
        _register_bound_followup_authority(result, store=store)
        result._validate(store=store)
        return result

    def _validate(self, *, store: EvidenceStore | None = None) -> None:
        _require_bound_followup_authority(self, store=store)
        self._validate_payload()

    def _validate_payload(self) -> None:
        if type(self.planning) is not PlanningResult:
            raise TypeError("planning_result_required")
        if type(self.citations) is not VerifiedCitationState:
            raise TypeError("verified_citations_required")
        if type(self.trace) is not FollowupBindingTrace:
            raise TypeError("followup_binding_trace_required")
        plan = self.planning.plan
        if plan.query_type != "follow_up":
            raise ValueError("bound_plan_must_be_followup")
        if plan.inherited_doc_ids != self.trace.inherited_doc_ids:
            raise ValueError("followup_inherited_trace_mismatch")
        if (
            plan.scope_state != self.trace.effective_scope_state
            or plan.scope_origin != self.trace.effective_scope_origin
        ):
            raise ValueError("followup_scope_trace_mismatch")
        if self.planning.trace.request_fingerprint != self.trace.request_fingerprint:
            raise ValueError("followup_request_trace_mismatch")
        if self.planning.trace.config_sha256 != self.trace.config_sha256:
            raise ValueError("followup_config_trace_mismatch")
        if _sha256(self.planning.plan.to_dict()) != self.trace.effective_plan_sha256:
            raise ValueError("followup_effective_plan_hash_mismatch")
        if self.citations.state_sha256 != self.trace.citation_state_sha256:
            raise ValueError("followup_citation_trace_mismatch")
        if self.citations.request_fingerprint != self.trace.request_fingerprint:
            raise ValueError("followup_citation_request_mismatch")
        if self.citations.evidence_bundle_sha256 != self.trace.evidence_bundle_sha256:
            raise ValueError("followup_evidence_bundle_trace_mismatch")
        if not set(plan.inherited_doc_ids).issubset(self.citations.cited_doc_ids):
            raise ValueError("followup_scope_not_citation_bound")
        if plan.allow_global_fallback != self.trace.fallback_authorized:
            raise ValueError("followup_fallback_trace_mismatch")

    @property
    def plan(self) -> QueryPlan:
        return self.planning.plan

    @property
    def binding_sha256(self) -> str:
        return _sha256(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "planning": self.planning.to_dict(),
            "citations": self.citations.to_dict(),
            "trace": self.trace.to_dict(),
        }


def bind_followup(
    request: RuntimeRequest,
    planning: PlanningResult,
    store: EvidenceStore,
    registry: RuleRegistry,
) -> BoundFollowup:
    """Intersect verified prior citations with current hard scope."""

    if type(request) is not RuntimeRequest:
        raise TypeError("runtime_request_required")
    if type(planning) is not PlanningResult:
        raise TypeError("planning_result_required")
    if type(store) is not EvidenceStore:
        raise TypeError("evidence_store_required")
    if type(registry) is not RuleRegistry:
        raise TypeError("rule_registry_required")
    registry.validate_plan(planning.plan)
    if planning.trace.request_fingerprint != request.fingerprint:
        raise ValueError("followup_request_plan_mismatch")
    if planning.plan.query_type != "follow_up":
        raise ValueError("followup_plan_required")

    citations = VerifiedCitationState.bind(request, store)
    prior = planning.plan
    cited_docs = frozenset(citations.cited_doc_ids)
    user_explicit = request.document_scope["mode"] == "explicit"
    if prior.scope_origin == "all" and prior.scope_state == "unfiltered":
        effective = cited_docs
        effective_origin = (
            "combined" if prior.metadata_predicates else "followup_citations"
        )
    else:
        effective = frozenset(prior.resolved_doc_ids) & cited_docs
        effective_origin = (
            "user_explicit+followup_citations"
            if user_explicit and prior.scope_origin == "user_explicit"
            else "combined"
        )
    effective_ids = tuple(sorted(effective))
    effective_state = "restricted" if effective_ids else "empty"
    fallback_authorized = bool(
        not user_explicit
        and prior.scope_state == "unfiltered"
        and prior.scope_origin == "all"
        and prior.allow_global_fallback
        and not prior.metadata_predicates
        and not prior.unresolved_constraints
        and request.options.get("allow_global_fallback", False)
        and effective_ids
    )
    updated_plan = registry.make_plan(
        query_type=prior.query_type,
        normalized_query=prior.normalized_query,
        entities=prior.entities,
        resolved_doc_ids=effective_ids,
        inherited_doc_ids=effective_ids,
        scope_state=effective_state,
        scope_origin=effective_origin,
        constraints=prior.constraints,
        metadata_predicates=prior.metadata_predicates,
        required_slots=prior.required_slots,
        allow_global_fallback=fallback_authorized,
        unresolved_constraints=prior.unresolved_constraints,
    )
    old_trace = planning.trace
    updated_trace = PlanningTrace(
        request_fingerprint=old_trace.request_fingerprint,
        config_sha256=old_trace.config_sha256,
        catalog_sha256=old_trace.catalog_sha256,
        catalog_source_kind=old_trace.catalog_source_kind,
        catalog_source_sha256=old_trace.catalog_source_sha256,
        execution_kind=old_trace.execution_kind,
        matched_rule_ids=old_trace.matched_rule_ids,
        matched_rule_sources=old_trace.matched_rule_sources,
        scope_state=effective_state,
        scope_origin=effective_origin,
        resolved_doc_ids=effective_ids,
        predicate_statuses=old_trace.predicate_statuses,
    )
    binding_trace = FollowupBindingTrace(
        request_fingerprint=request.fingerprint,
        config_sha256=registry.config_sha256,
        prior_plan_sha256=_sha256(prior.to_dict()),
        effective_plan_sha256=_sha256(updated_plan.to_dict()),
        evidence_bundle_sha256=store.bundle_sha256,
        citation_state_sha256=citations.state_sha256,
        prior_scope_state=prior.scope_state,
        prior_scope_origin=prior.scope_origin,
        prior_resolved_doc_ids=prior.resolved_doc_ids,
        effective_scope_state=effective_state,
        effective_scope_origin=effective_origin,
        inherited_doc_ids=effective_ids,
        fallback_authorized=fallback_authorized,
        ignored_resolved_entity_count=len(request.prior_citation_state["resolved_entities"]),
        ignored_list_doc_count=len(request.prior_citation_state["list_doc_ids"]),
        ignored_comparison_doc_count=len(request.prior_citation_state["comparison_doc_ids"]),
    )
    return BoundFollowup._from_binding(
        PlanningResult(updated_plan, updated_trace),
        citations,
        binding_trace,
        store,
        _token=_BOUND_FOLLOWUP_TOKEN,
    )
