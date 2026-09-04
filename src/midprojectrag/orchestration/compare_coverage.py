"""Immutable compare slot evidence and distinct-document coverage."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any, Protocol
from weakref import ReferenceType, ref

from midprojectrag.evidence import EvidenceStore
from midprojectrag.retrieval import Candidate, SearchResult
from midprojectrag.runtime_integrity import ResolvedScope

from .compare_slots import (
    BoundCompare,
    CompareFieldRegistry,
    compare_slot_budget,
    compare_slot_query,
    default_compare_field_registry,
)
from .contracts import RequiredSlot


_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SLOT_STATE_TOKEN = object()
_DOCUMENT_COVERAGE_TOKEN = object()
_COMPARE_COVERAGE_TOKEN = object()
_SEARCH_RECEIPT_TOKEN = object()
_VERIFICATION_RECEIPT_TOKEN = object()
_COMPARE_COVERAGE_AUTHORITIES: dict[
    int, tuple[ReferenceType[CompareCoverage], str]
] = {}
_SEARCH_LANES = frozenset({"rrf", "dense", "lexical"})
_SLOT_STATUSES = frozenset(
    {"unsearched", "candidate", "verified", "missing", "contradicted"}
)
_MISSING_REASONS = frozenset(
    {"no_candidate_yet", "candidates_unverified"}
)
_VERIFIER_IDS = frozenset({"deterministic-evidence-verifier-v1"})
_SEARCH_RESULT_FIELDS = frozenset({"candidates", "trace"})
_CANDIDATE_FIELDS = frozenset(
    {"evidence_id", "doc_id", "score", "lane", "rank", "granularity"}
)
_SAFE_TRACE_FIELDS = frozenset(
    {
        "schema_version",
        "lane",
        "granularity",
        "bundle_sha256",
        "candidate_count",
        "trace_projection",
    }
)
_SEARCH_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "slot",
        "request_fingerprint",
        "binding_sha256",
        "effective_plan_sha256",
        "evidence_bundle_sha256",
        "query_sha256",
        "dense_k",
        "lexical_k",
        "slot_ordinal",
        "slot_count",
        "budget_policy",
        "scope_doc_ids",
        "action",
        "retriever_profile",
        "source_trace_sha256",
        "lane",
        "result",
        "result_sha256",
        "receipt_sha256",
    }
)
_VERIFICATION_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "slot",
        "request_fingerprint",
        "binding_sha256",
        "effective_plan_sha256",
        "evidence_bundle_sha256",
        "search_receipt_sha256",
        "field_rule_id",
        "verifier_id",
        "verifier_config_sha256",
        "verification_level",
        "field_match_evidence_ids",
        "contradicted_evidence_ids",
        "receipt_sha256",
    }
)
_SLOT_STATE_FIELDS = frozenset(
    {
        "schema_version",
        "slot",
        "status",
        "candidate_evidence_ids",
        "verified_evidence_ids",
        "missing_reason",
        "absence_confirmed",
        "contradiction_state",
        "search_result_sha256",
        "verifier_id",
        "verifier_config_sha256",
        "slot_sha256",
    }
)
_DOCUMENT_COVERAGE_FIELDS = frozenset(
    {
        "doc_id",
        "required_slot_keys",
        "unsearched_slot_keys",
        "candidate_slot_keys",
        "verified_slot_keys",
        "missing_slot_keys",
        "contradicted_slot_keys",
        "accounted",
        "complete",
    }
)
_COVERAGE_FIELDS = frozenset(
    {
        "schema_version",
        "binding_sha256",
        "effective_plan_sha256",
        "evidence_bundle_sha256",
        "verifier_id",
        "verifier_config_sha256",
        "slots",
        "documents",
        "required_slot_count",
        "verified_slot_count",
        "missing_slot_count",
        "contradicted_slot_count",
        "open_slot_count",
        "accounted_slot_count",
        "covered_document_ids",
        "accounted_document_ids",
        "slot_coverage_ratio",
        "document_coverage_ratio",
        "accounted_complete",
        "coverage_complete",
        "normal_stop_allowed",
        "abstain_required",
        "answerability",
        "coverage_sha256",
    }
)


class CompareSlotRetriever(Protocol):
    def search(
        self,
        query: str,
        *,
        dense_k: int,
        lexical_k: int,
        scope: ResolvedScope,
    ) -> SearchResult: ...


def _canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _drop_compare_coverage_authority(
    identity: int, dead: ReferenceType[Any]
) -> None:
    current = _COMPARE_COVERAGE_AUTHORITIES.get(identity)
    if current is not None and current[0] is dead:
        _COMPARE_COVERAGE_AUTHORITIES.pop(identity, None)


def _register_compare_coverage_authority(coverage: CompareCoverage) -> None:
    """Bind a factory-issued coverage identity to its complete sealed payload."""

    identity = id(coverage)
    weak = ref(
        coverage,
        lambda dead, identity=identity: _drop_compare_coverage_authority(
            identity, dead
        ),
    )
    _COMPARE_COVERAGE_AUTHORITIES[identity] = (
        weak,
        _canonical_sha256(coverage.to_dict()),
    )


def _require_compare_coverage_authority(coverage: CompareCoverage) -> None:
    """Reject raw instances and any mutation after factory issuance."""

    if type(coverage) is not CompareCoverage:
        raise TypeError("compare_coverage_required")
    current = _COMPARE_COVERAGE_AUTHORITIES.get(id(coverage))
    if current is None or current[0]() is not coverage:
        raise ValueError("compare_coverage_runtime_authority_required")
    if current[1] != _canonical_sha256(coverage.to_dict()):
        raise ValueError("compare_coverage_runtime_authority_drift")


def _closed(value: Any, fields: frozenset[str], code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(code)
    if any(type(key) is not str for key in value):
        raise TypeError(code)
    return value


def _json_list(value: Any, code: str) -> list[Any]:
    if type(value) is not list:
        raise TypeError(code)
    return value


def _hash(value: Any, code: str) -> str:
    if type(value) is not str or not _HEX64.fullmatch(value):
        raise ValueError(code)
    return value


def _ids(value: Any, code: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(code)
    if any(type(item) is not str or not item for item in value):
        raise ValueError(code)
    if len(value) != len(set(value)):
        raise ValueError(f"duplicate_{code}")
    return value


def _mapping(value: Any, code: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise TypeError(code)
    return dict(value)


def _safe_search_payload(result: SearchResult, store: EvidenceStore) -> dict[str, Any]:
    if type(result) is not SearchResult:
        raise TypeError("search_result_required")
    if result.trace.get("bundle_sha256") != store.bundle_sha256:
        raise ValueError("compare_search_bundle_mismatch")
    if result.trace.get("granularity") != "child":
        raise ValueError("compare_search_granularity_mismatch")
    if result.trace.get("lane") not in _SEARCH_LANES:
        raise ValueError("compare_search_lane_mismatch")
    return {
        "schema_version": "1.0",
        "candidates": [candidate.to_dict() for candidate in result.candidates],
        "trace": {
            "schema_version": "1.0",
            "lane": result.trace["lane"],
            "granularity": "child",
            "bundle_sha256": store.bundle_sha256,
            "candidate_count": len(result.candidates),
            "trace_projection": "compare-safe-v1",
        },
    }


def _project_search_result(result: SearchResult, store: EvidenceStore) -> SearchResult:
    payload = _safe_search_payload(result, store)
    return SearchResult(result.candidates, payload["trace"])


def _validate_slot_result(
    slot: RequiredSlot,
    result: SearchResult,
    store: EvidenceStore,
    allowed_doc_ids: frozenset[str],
) -> tuple[tuple[str, ...], str]:
    payload = _safe_search_payload(result, store)
    result_lane = result.trace["lane"]
    evidence_ids: list[str] = []
    for expected_rank, candidate in enumerate(result.candidates, 1):
        if candidate.rank != expected_rank or candidate.granularity != "child":
            raise ValueError("compare_candidate_rank_or_granularity_mismatch")
        if candidate.lane not in _SEARCH_LANES:
            raise ValueError("compare_candidate_lane_mismatch")
        if candidate.lane != result_lane:
            raise ValueError("compare_candidate_result_lane_mismatch")
        if candidate.doc_id != slot.doc_id:
            raise ValueError("compare_slot_result_document_mismatch")
        if candidate.doc_id not in allowed_doc_ids:
            raise ValueError("compare_candidate_scope_escape")
        try:
            evidence = store.get(candidate.evidence_id)
        except KeyError as exc:
            raise ValueError("unknown_compare_candidate_evidence") from exc
        if evidence.doc_id != candidate.doc_id or evidence.kind != "text":
            raise ValueError("compare_candidate_evidence_mismatch")
        evidence_ids.append(candidate.evidence_id)
    return tuple(evidence_ids), _canonical_sha256(result.to_dict())


def _slot_for_key(bound: BoundCompare, slot_key: str) -> RequiredSlot:
    if type(slot_key) is not str or not slot_key:
        raise ValueError("invalid_compare_slot_key")
    for slot in bound.plan.required_slots:
        if slot.key == slot_key:
            return slot
    raise ValueError("unknown_compare_slot_key")


def _slot_query(bound: BoundCompare, slot: RequiredSlot) -> str:
    return compare_slot_query(bound=bound, slot=slot)


def _query_sha256(bound: BoundCompare, slot: RequiredSlot) -> str:
    return sha256(_slot_query(bound, slot).encode("utf-8")).hexdigest()


def _slot_budget(bound: BoundCompare, slot: RequiredSlot) -> tuple[int, int, int, int]:
    return compare_slot_budget(bound=bound, slot=slot)


def _validate_production_retriever(retriever: Any, store: EvidenceStore) -> None:
    """Reject an unapproved or instance-overridden retriever before query egress."""

    from midprojectrag.retrieval.dense import DenseChildLane
    from midprojectrag.retrieval.fusion import (
        HybridChildRetriever,
        require_production_hybrid,
    )
    from midprojectrag.retrieval.kiwi_bm25 import KiwiBM25Lane, KiwiTokenizer
    from midprojectrag.stacks.local.hf_embeddings import KureEmbeddingProvider

    if type(retriever) is not HybridChildRetriever:
        raise ValueError("compare_production_retriever_required")
    if type(retriever.dense) is not DenseChildLane:
        raise ValueError("compare_production_dense_lane_required")
    if type(retriever.lexical) is not KiwiBM25Lane:
        raise ValueError("compare_production_lexical_lane_required")
    if type(retriever.dense.provider) is not KureEmbeddingProvider:
        raise ValueError("compare_production_embedding_provider_required")
    if retriever.dense.provider.execution_kind != "real_local_model":
        raise ValueError("compare_production_embedding_execution_required")
    if type(retriever.lexical.tokenizer) is not KiwiTokenizer:
        raise ValueError("compare_production_tokenizer_required")
    component_stores = tuple(
        getattr(component, "store", None)
        for component in (retriever, retriever.dense, retriever.lexical)
    )
    if any(
        type(component_store) is not EvidenceStore
        or component_store.bundle_sha256 != store.bundle_sha256
        for component_store in component_stores
    ):
        raise ValueError("compare_production_retriever_store_mismatch")
    if tuple(retriever.dense.rows) != store.candidates() or tuple(
        retriever.lexical.rows
    ) != store.candidates():
        raise ValueError("compare_production_retriever_rows_mismatch")
    for component, method_name in (
        (retriever, "search"),
        (retriever.dense, "search"),
        (retriever.lexical, "search"),
        (retriever.dense.provider, "embed"),
        (retriever.lexical.tokenizer, "tokenize"),
    ):
        if method_name in vars(component):
            raise ValueError("compare_production_retriever_method_override")
    for value in (
        retriever.dense.artifact_sha256,
        retriever.lexical.artifact_sha256,
    ):
        _hash(value, "invalid_compare_production_artifact_sha256")
    # Exact class names and artifact-shaped hashes are not authority.  Require
    # the runtime binding minted only by the verified dense/lexical loaders and
    # the production hybrid factory, and revalidate it before query derivation.
    require_production_hybrid(retriever, store)


def _verifier_config_sha256(compare_registry: CompareFieldRegistry) -> str:
    return _canonical_sha256(
        {
            "schema_version": "1.0",
            "verifier_id": "deterministic-evidence-verifier-v1",
            "policy": "exact-slot-field-signal-observation-v1",
            "compare_config_sha256": compare_registry.config_sha256,
            "accepted_evidence_kind": "text",
            "terminal_verification": "blocked_pending_typed_claim_receipt",
            "contradiction_promotion": "blocked_pending_typed_receipt",
        }
    )


def _search_result_from_dict(raw: Mapping[str, Any]) -> SearchResult:
    value = _closed(raw, _SEARCH_RESULT_FIELDS, "compare_search_result_fields")
    candidates = tuple(
        Candidate(**_closed(item, _CANDIDATE_FIELDS, "compare_candidate_fields"))
        for item in _json_list(value["candidates"], "compare_search_candidates_array")
    )
    trace = _closed(value["trace"], _SAFE_TRACE_FIELDS, "compare_search_trace_fields")
    result = SearchResult(candidates, dict(trace))
    _validate_projected_search_result(result)
    return result


def _validate_projected_search_result(result: SearchResult) -> None:
    if type(result) is not SearchResult or set(result.trace) != _SAFE_TRACE_FIELDS:
        raise ValueError("compare_search_trace_fields")
    if result.trace.get("schema_version") != "1.0":
        raise ValueError("unsupported_compare_search_trace_version")
    if result.trace.get("trace_projection") != "compare-safe-v1":
        raise ValueError("compare_search_trace_projection_mismatch")
    candidate_count = result.trace.get("candidate_count")
    if type(candidate_count) is not int or candidate_count != len(result.candidates):
        raise ValueError("compare_search_trace_candidate_count_mismatch")


@dataclass(frozen=True, slots=True, init=False)
class CompareSearchReceipt:
    slot: RequiredSlot
    request_fingerprint: str
    binding_sha256: str
    effective_plan_sha256: str
    evidence_bundle_sha256: str
    query_sha256: str
    dense_k: int
    lexical_k: int
    slot_ordinal: int
    slot_count: int
    budget_policy: str
    scope_doc_ids: tuple[str, ...]
    action: str
    retriever_profile: str
    source_trace_sha256: str
    lane: str
    result: SearchResult
    result_sha256: str
    receipt_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("compare_search_receipt_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        bound: BoundCompare,
        store: EvidenceStore,
        slot: RequiredSlot,
        result: SearchResult,
        retriever_profile: str,
        source_trace_sha256: str,
        _token: object,
    ) -> CompareSearchReceipt:
        if _token is not _SEARCH_RECEIPT_TOKEN:
            raise ValueError("compare_search_receipt_factory_required")
        _validate_slot_result(
            slot, result, store, frozenset(bound.plan.resolved_doc_ids)
        )
        dense_k, lexical_k, slot_ordinal, slot_count = _slot_budget(bound, slot)
        result_hash = _canonical_sha256(result.to_dict())
        base = {
            "schema_version": "1.0",
            "slot": slot.to_dict(),
            "request_fingerprint": bound.trace.request_fingerprint,
            "binding_sha256": bound.binding_sha256,
            "effective_plan_sha256": bound.trace.effective_plan_sha256,
            "evidence_bundle_sha256": store.bundle_sha256,
            "query_sha256": _query_sha256(bound, slot),
            "dense_k": dense_k,
            "lexical_k": lexical_k,
            "slot_ordinal": slot_ordinal,
            "slot_count": slot_count,
            "budget_policy": "even_slot_partition_v1",
            "scope_doc_ids": [slot.doc_id],
            "action": "hybrid_child_search",
            "retriever_profile": retriever_profile,
            "source_trace_sha256": source_trace_sha256,
            "lane": result.trace["lane"],
            "result": result.to_dict(),
            "result_sha256": result_hash,
        }
        receipt = object.__new__(cls)
        for name, item in (
            ("slot", slot),
            ("request_fingerprint", base["request_fingerprint"]),
            ("binding_sha256", base["binding_sha256"]),
            ("effective_plan_sha256", base["effective_plan_sha256"]),
            ("evidence_bundle_sha256", base["evidence_bundle_sha256"]),
            ("query_sha256", base["query_sha256"]),
            ("dense_k", base["dense_k"]),
            ("lexical_k", base["lexical_k"]),
            ("slot_ordinal", base["slot_ordinal"]),
            ("slot_count", base["slot_count"]),
            ("budget_policy", base["budget_policy"]),
            ("scope_doc_ids", (slot.doc_id,)),
            ("action", base["action"]),
            ("retriever_profile", base["retriever_profile"]),
            ("source_trace_sha256", base["source_trace_sha256"]),
            ("lane", base["lane"]),
            ("result", result),
            ("result_sha256", result_hash),
            ("receipt_sha256", _canonical_sha256(base)),
        ):
            object.__setattr__(receipt, name, item)
        receipt._validate(bound, store)
        return receipt

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "slot": self.slot.to_dict(),
            "request_fingerprint": self.request_fingerprint,
            "binding_sha256": self.binding_sha256,
            "effective_plan_sha256": self.effective_plan_sha256,
            "evidence_bundle_sha256": self.evidence_bundle_sha256,
            "query_sha256": self.query_sha256,
            "dense_k": self.dense_k,
            "lexical_k": self.lexical_k,
            "slot_ordinal": self.slot_ordinal,
            "slot_count": self.slot_count,
            "budget_policy": self.budget_policy,
            "scope_doc_ids": list(self.scope_doc_ids),
            "action": self.action,
            "retriever_profile": self.retriever_profile,
            "source_trace_sha256": self.source_trace_sha256,
            "lane": self.lane,
            "result": self.result.to_dict(),
            "result_sha256": self.result_sha256,
        }

    def _validate(self, bound: BoundCompare, store: EvidenceStore) -> None:
        bound._validate()
        _validate_projected_search_result(self.result)
        if self.slot not in bound.plan.required_slots:
            raise ValueError("compare_search_receipt_slot_mismatch")
        for name in (
            "request_fingerprint",
            "binding_sha256",
            "effective_plan_sha256",
            "evidence_bundle_sha256",
            "query_sha256",
            "source_trace_sha256",
            "result_sha256",
            "receipt_sha256",
        ):
            _hash(getattr(self, name), f"invalid_{name}")
        if self.request_fingerprint != bound.trace.request_fingerprint:
            raise ValueError("compare_search_receipt_request_mismatch")
        if self.binding_sha256 != bound.binding_sha256:
            raise ValueError("compare_search_receipt_binding_mismatch")
        if self.effective_plan_sha256 != bound.trace.effective_plan_sha256:
            raise ValueError("compare_search_receipt_plan_mismatch")
        if self.evidence_bundle_sha256 != store.bundle_sha256:
            raise ValueError("compare_search_receipt_store_mismatch")
        if self.query_sha256 != _query_sha256(bound, self.slot):
            raise ValueError("compare_search_receipt_query_mismatch")
        dense_k, lexical_k, slot_ordinal, slot_count = _slot_budget(
            bound, self.slot
        )
        if self.dense_k != dense_k or self.lexical_k != lexical_k:
            raise ValueError("compare_search_receipt_budget_mismatch")
        if self.slot_ordinal != slot_ordinal or self.slot_count != slot_count:
            raise ValueError("compare_search_receipt_slot_ordinal_mismatch")
        if self.budget_policy != "even_slot_partition_v1":
            raise ValueError("compare_search_receipt_budget_policy_mismatch")
        if len(self.result.candidates) > self.dense_k + self.lexical_k:
            raise ValueError("compare_search_receipt_candidate_budget_exceeded")
        if self.scope_doc_ids != (self.slot.doc_id,):
            raise ValueError("compare_search_receipt_scope_mismatch")
        if self.action != "hybrid_child_search":
            raise ValueError("compare_search_receipt_action_mismatch")
        if self.retriever_profile not in {
            "hybrid_child_rrf_v1",
            "synthetic_test_fixture",
        }:
            raise ValueError("compare_search_receipt_profile_mismatch")
        if (
            bound.trace.execution_kind == "production"
            and self.retriever_profile != "hybrid_child_rrf_v1"
        ):
            raise ValueError("compare_production_retriever_required")
        if self.retriever_profile == "hybrid_child_rrf_v1" and self.lane != "rrf":
            raise ValueError("compare_hybrid_result_lane_mismatch")
        if self.lane not in _SEARCH_LANES or self.result.trace.get("lane") != self.lane:
            raise ValueError("compare_search_receipt_lane_mismatch")
        _validate_slot_result(
            self.slot,
            self.result,
            store,
            frozenset(bound.plan.resolved_doc_ids),
        )
        if self.result_sha256 != _canonical_sha256(self.result.to_dict()):
            raise ValueError("compare_search_receipt_result_mismatch")
        if self.receipt_sha256 != _canonical_sha256(self._payload()):
            raise ValueError("compare_search_receipt_hash_mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "receipt_sha256": self.receipt_sha256}

    @classmethod
    def from_dict(
        cls,
        raw: Mapping[str, Any],
        *,
        bound: BoundCompare,
        store: EvidenceStore,
        retriever: CompareSlotRetriever,
    ) -> CompareSearchReceipt:
        value = _closed(raw, _SEARCH_RECEIPT_FIELDS, "compare_search_receipt_fields")
        if value["schema_version"] != "1.0":
            raise ValueError("unsupported_compare_search_receipt_version")
        slot = RequiredSlot.from_dict(value["slot"])
        scope_doc_ids = tuple(
            _json_list(value["scope_doc_ids"], "compare_search_scope_doc_ids_array")
        )
        _ids(scope_doc_ids, "compare_search_scope_doc_ids")
        result = _search_result_from_dict(value["result"])
        for name in ("dense_k", "lexical_k", "slot_ordinal", "slot_count"):
            if type(value[name]) is not int or value[name] < 1:
                raise ValueError(f"invalid_compare_search_{name}")
        for name in ("budget_policy", "action", "retriever_profile", "lane"):
            if type(value[name]) is not str or not value[name]:
                raise ValueError(f"invalid_compare_search_{name}")

        # Validate the complete deterministic envelope before any provider call.
        # The temporary object is never returned as authority; a payload that is
        # internally consistent still has to reproduce exactly below.
        untrusted = object.__new__(cls)
        for name, item in (
            ("slot", slot),
            ("request_fingerprint", value["request_fingerprint"]),
            ("binding_sha256", value["binding_sha256"]),
            ("effective_plan_sha256", value["effective_plan_sha256"]),
            ("evidence_bundle_sha256", value["evidence_bundle_sha256"]),
            ("query_sha256", value["query_sha256"]),
            ("dense_k", value["dense_k"]),
            ("lexical_k", value["lexical_k"]),
            ("slot_ordinal", value["slot_ordinal"]),
            ("slot_count", value["slot_count"]),
            ("budget_policy", value["budget_policy"]),
            ("scope_doc_ids", scope_doc_ids),
            ("action", value["action"]),
            ("retriever_profile", value["retriever_profile"]),
            ("source_trace_sha256", value["source_trace_sha256"]),
            ("lane", value["lane"]),
            ("result", result),
            ("result_sha256", value["result_sha256"]),
            ("receipt_sha256", value["receipt_sha256"]),
        ):
            object.__setattr__(untrusted, name, item)
        untrusted._validate(bound, store)
        # Re-execution is intentional: an unkeyed JSON hash cannot prove that
        # a provider actually performed this bounded search.
        receipt = execute_compare_slot_search(
            bound=bound,
            store=store,
            slot_key=slot.key,
            retriever=retriever,
        )
        if _canonical_sha256(receipt.to_dict()) != _canonical_sha256(dict(value)):
            raise ValueError("compare_search_receipt_payload_mismatch")
        return receipt


def execute_compare_slot_search(
    *,
    bound: BoundCompare,
    store: EvidenceStore,
    slot_key: str,
    retriever: CompareSlotRetriever,
) -> CompareSearchReceipt:
    """Execute the bound query against exactly one slot document."""

    if type(bound) is not BoundCompare:
        raise TypeError("bound_compare_required")
    if type(store) is not EvidenceStore:
        raise TypeError("evidence_store_required")
    bound._validate()
    if bound.trace.status != "ready":
        raise ValueError("compare_binding_not_ready")
    if bound.trace.evidence_bundle_sha256 != store.bundle_sha256:
        raise ValueError("compare_store_binding_mismatch")
    dense_k, lexical_k, _slot_ordinal, _slot_count = _slot_budget(
        bound, _slot_for_key(bound, slot_key)
    )
    production = bound.trace.execution_kind == "production"
    if production:
        # Validate the complete approved local stack before deriving or sending
        # the slot query.  A rejected retriever must observe zero query calls.
        _validate_production_retriever(retriever, store)
    slot = _slot_for_key(bound, slot_key)
    search = getattr(retriever, "search", None)
    if not callable(search):
        raise TypeError("compare_slot_retriever_required")
    scope = ResolvedScope(
        "restricted",
        frozenset({slot.doc_id}),
        bound.plan.scope_origin,
    )
    slot_query = _slot_query(bound, slot)
    if production:
        # Invoke the approved class implementation directly so an instance
        # attribute cannot replace the outer hybrid search method.
        from midprojectrag.retrieval.fusion import HybridChildRetriever

        raw = HybridChildRetriever.search(
            retriever,
            slot_query,
            dense_k=dense_k,
            lexical_k=lexical_k,
            scope=scope,
        )
    else:
        raw = search(
            slot_query,
            dense_k=dense_k,
            lexical_k=lexical_k,
            scope=scope,
        )
    _validate_slot_result(slot, raw, store, frozenset({slot.doc_id}))
    if production:
        retriever_profile = "hybrid_child_rrf_v1"
    else:
        retriever_profile = "synthetic_test_fixture"
    source_trace_sha256 = _canonical_sha256(dict(raw.to_dict()["trace"]))
    projected = _project_search_result(raw, store)
    return CompareSearchReceipt._create(
        bound=bound,
        store=store,
        slot=slot,
        result=projected,
        retriever_profile=retriever_profile,
        source_trace_sha256=source_trace_sha256,
        _token=_SEARCH_RECEIPT_TOKEN,
    )


@dataclass(frozen=True, slots=True, init=False)
class CompareVerificationReceipt:
    slot: RequiredSlot
    request_fingerprint: str
    binding_sha256: str
    effective_plan_sha256: str
    evidence_bundle_sha256: str
    search_receipt_sha256: str
    field_rule_id: str
    verifier_id: str
    verifier_config_sha256: str
    verification_level: str
    field_match_evidence_ids: tuple[str, ...]
    contradicted_evidence_ids: tuple[str, ...]
    receipt_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("compare_verification_receipt_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        bound: BoundCompare,
        store: EvidenceStore,
        search_receipt: CompareSearchReceipt,
        compare_registry: CompareFieldRegistry,
        _token: object,
    ) -> CompareVerificationReceipt:
        if _token is not _VERIFICATION_RECEIPT_TOKEN:
            raise ValueError("compare_verification_receipt_factory_required")
        search_receipt._validate(bound, store)
        compare_registry._validate()
        if compare_registry.config_sha256 != default_compare_field_registry().config_sha256:
            raise ValueError("unapproved_compare_field_registry")
        rules = tuple(
            rule
            for rule in compare_registry.rules
            if rule.field == search_receipt.slot.field
        )
        if len(rules) != 1:
            raise ValueError("compare_slot_field_rule_unresolved")
        rule = rules[0]
        field_matches = tuple(
            candidate.evidence_id
            for candidate in search_receipt.result.candidates
            if rule.matches(store.get(candidate.evidence_id).text)
        )
        config_hash = _verifier_config_sha256(compare_registry)
        base = {
            "schema_version": "1.0",
            "slot": search_receipt.slot.to_dict(),
            "request_fingerprint": bound.trace.request_fingerprint,
            "binding_sha256": bound.binding_sha256,
            "effective_plan_sha256": bound.trace.effective_plan_sha256,
            "evidence_bundle_sha256": store.bundle_sha256,
            "search_receipt_sha256": search_receipt.receipt_sha256,
            "field_rule_id": rule.rule_id,
            "verifier_id": "deterministic-evidence-verifier-v1",
            "verifier_config_sha256": config_hash,
            # A lexical field signal is useful routing evidence, but it is not
            # proof that the chunk contains an answerable claim/value.  EH2.4
            # therefore records it without minting terminal verified evidence.
            "verification_level": "field_relevance_only",
            "field_match_evidence_ids": list(field_matches),
            # EH2.4 has no typed value-extraction/contradiction receipt.  Never
            # infer contradiction merely from two different text chunks.
            "contradicted_evidence_ids": [],
        }
        receipt = object.__new__(cls)
        for name, item in (
            ("slot", search_receipt.slot),
            ("request_fingerprint", base["request_fingerprint"]),
            ("binding_sha256", base["binding_sha256"]),
            ("effective_plan_sha256", base["effective_plan_sha256"]),
            ("evidence_bundle_sha256", base["evidence_bundle_sha256"]),
            ("search_receipt_sha256", base["search_receipt_sha256"]),
            ("field_rule_id", rule.rule_id),
            ("verifier_id", base["verifier_id"]),
            ("verifier_config_sha256", config_hash),
            ("verification_level", base["verification_level"]),
            ("field_match_evidence_ids", field_matches),
            ("contradicted_evidence_ids", ()),
            ("receipt_sha256", _canonical_sha256(base)),
        ):
            object.__setattr__(receipt, name, item)
        receipt._validate(bound, store, search_receipt, compare_registry)
        return receipt

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "slot": self.slot.to_dict(),
            "request_fingerprint": self.request_fingerprint,
            "binding_sha256": self.binding_sha256,
            "effective_plan_sha256": self.effective_plan_sha256,
            "evidence_bundle_sha256": self.evidence_bundle_sha256,
            "search_receipt_sha256": self.search_receipt_sha256,
            "field_rule_id": self.field_rule_id,
            "verifier_id": self.verifier_id,
            "verifier_config_sha256": self.verifier_config_sha256,
            "verification_level": self.verification_level,
            "field_match_evidence_ids": list(self.field_match_evidence_ids),
            "contradicted_evidence_ids": list(self.contradicted_evidence_ids),
        }

    def _validate(
        self,
        bound: BoundCompare,
        store: EvidenceStore,
        search_receipt: CompareSearchReceipt,
        compare_registry: CompareFieldRegistry,
    ) -> None:
        search_receipt._validate(bound, store)
        if self.slot != search_receipt.slot:
            raise ValueError("compare_verification_slot_mismatch")
        for name in (
            "request_fingerprint",
            "binding_sha256",
            "effective_plan_sha256",
            "evidence_bundle_sha256",
            "search_receipt_sha256",
            "verifier_config_sha256",
            "receipt_sha256",
        ):
            _hash(getattr(self, name), f"invalid_{name}")
        if self.request_fingerprint != bound.trace.request_fingerprint:
            raise ValueError("compare_verification_request_mismatch")
        if self.binding_sha256 != bound.binding_sha256:
            raise ValueError("compare_verification_binding_mismatch")
        if self.effective_plan_sha256 != bound.trace.effective_plan_sha256:
            raise ValueError("compare_verification_plan_mismatch")
        if self.evidence_bundle_sha256 != store.bundle_sha256:
            raise ValueError("compare_verification_store_mismatch")
        if self.search_receipt_sha256 != search_receipt.receipt_sha256:
            raise ValueError("compare_verification_search_mismatch")
        if self.verifier_id not in _VERIFIER_IDS:
            raise ValueError("invalid_compare_verifier_id")
        if self.verifier_config_sha256 != _verifier_config_sha256(compare_registry):
            raise ValueError("compare_verifier_config_mismatch")
        rule = next(
            (rule for rule in compare_registry.rules if rule.field == self.slot.field),
            None,
        )
        if rule is None or self.field_rule_id != rule.rule_id:
            raise ValueError("compare_verification_field_rule_mismatch")
        if self.verification_level != "field_relevance_only":
            raise ValueError("compare_semantic_verification_receipt_required")
        expected = tuple(
            candidate.evidence_id
            for candidate in search_receipt.result.candidates
            if rule.matches(store.get(candidate.evidence_id).text)
        )
        if self.field_match_evidence_ids != expected:
            raise ValueError("compare_field_match_evidence_mismatch")
        if self.contradicted_evidence_ids:
            raise ValueError("compare_contradiction_receipt_required")
        if self.receipt_sha256 != _canonical_sha256(self._payload()):
            raise ValueError("compare_verification_receipt_hash_mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "receipt_sha256": self.receipt_sha256}

    @classmethod
    def from_dict(
        cls,
        raw: Mapping[str, Any],
        *,
        bound: BoundCompare,
        store: EvidenceStore,
        search_receipt: CompareSearchReceipt,
        compare_registry: CompareFieldRegistry,
    ) -> CompareVerificationReceipt:
        value = _closed(
            raw, _VERIFICATION_RECEIPT_FIELDS, "compare_verification_receipt_fields"
        )
        if value["schema_version"] != "1.0":
            raise ValueError("unsupported_compare_verification_receipt_version")
        _json_list(
            value["field_match_evidence_ids"],
            "compare_field_match_evidence_ids_array",
        )
        _json_list(
            value["contradicted_evidence_ids"],
            "compare_contradicted_evidence_ids_array",
        )
        RequiredSlot.from_dict(value["slot"])
        receipt = cls._create(
            bound=bound,
            store=store,
            search_receipt=search_receipt,
            compare_registry=compare_registry,
            _token=_VERIFICATION_RECEIPT_TOKEN,
        )
        if _canonical_sha256(receipt.to_dict()) != _canonical_sha256(dict(value)):
            raise ValueError("compare_verification_receipt_payload_mismatch")
        return receipt


def verify_compare_slot_search(
    *,
    bound: BoundCompare,
    store: EvidenceStore,
    search_receipt: CompareSearchReceipt,
    compare_registry: CompareFieldRegistry,
) -> CompareVerificationReceipt:
    """Record field relevance only; semantic verification stays fail-closed."""

    if type(search_receipt) is not CompareSearchReceipt:
        raise TypeError("compare_search_receipt_required")
    return CompareVerificationReceipt._create(
        bound=bound,
        store=store,
        search_receipt=search_receipt,
        compare_registry=compare_registry,
        _token=_VERIFICATION_RECEIPT_TOKEN,
    )


def _document_coverage_payload(
    doc_id: str,
    states: tuple[CompareSlotState, ...],
) -> dict[str, Any]:
    if type(doc_id) is not str or not doc_id:
        raise ValueError("invalid_compare_coverage_doc_id")
    if type(states) is not tuple or not states or any(
        type(state) is not CompareSlotState or state.slot.doc_id != doc_id
        for state in states
    ):
        raise ValueError("invalid_compare_document_slot_states")
    grouped = {
        status: tuple(state.slot.key for state in states if state.status == status)
        for status in _SLOT_STATUSES
    }
    # EH2.4 can record a missing observation but cannot mint the bounded
    # absence receipt owned by EH2.6. Missing therefore remains open.
    accounted = (
        not grouped["unsearched"]
        and not grouped["candidate"]
        and not grouped["missing"]
    )
    complete = accounted and not grouped["contradicted"]
    return {
        "doc_id": doc_id,
        "required_slot_keys": [state.slot.key for state in states],
        "unsearched_slot_keys": list(grouped["unsearched"]),
        "candidate_slot_keys": list(grouped["candidate"]),
        "verified_slot_keys": list(grouped["verified"]),
        "missing_slot_keys": list(grouped["missing"]),
        "contradicted_slot_keys": list(grouped["contradicted"]),
        "accounted": accounted,
        "complete": complete,
    }


@dataclass(frozen=True, slots=True, init=False)
class CompareSlotState:
    slot: RequiredSlot
    status: str
    candidate_evidence_ids: tuple[str, ...]
    verified_evidence_ids: tuple[str, ...]
    missing_reason: str | None
    absence_confirmed: bool
    contradiction_state: str
    search_result_sha256: str | None
    verifier_id: str
    verifier_config_sha256: str
    slot_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("compare_slot_state_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        slot: RequiredSlot,
        status: str,
        candidate_evidence_ids: tuple[str, ...],
        verified_evidence_ids: tuple[str, ...],
        missing_reason: str | None,
        absence_confirmed: bool,
        contradiction_state: str,
        search_result_sha256: str | None,
        verifier_id: str,
        verifier_config_sha256: str,
        _token: object,
    ) -> CompareSlotState:
        if _token is not _SLOT_STATE_TOKEN:
            raise ValueError("compare_slot_state_factory_required")
        payload = {
            "schema_version": "1.0",
            "slot": slot.to_dict(),
            "status": status,
            "candidate_evidence_ids": list(candidate_evidence_ids),
            "verified_evidence_ids": list(verified_evidence_ids),
            "missing_reason": missing_reason,
            "absence_confirmed": absence_confirmed,
            "contradiction_state": contradiction_state,
            "search_result_sha256": search_result_sha256,
            "verifier_id": verifier_id,
            "verifier_config_sha256": verifier_config_sha256,
        }
        result = object.__new__(cls)
        for name, value in (
            ("slot", slot),
            ("status", status),
            ("candidate_evidence_ids", candidate_evidence_ids),
            ("verified_evidence_ids", verified_evidence_ids),
            ("missing_reason", missing_reason),
            ("absence_confirmed", absence_confirmed),
            ("contradiction_state", contradiction_state),
            ("search_result_sha256", search_result_sha256),
            ("verifier_id", verifier_id),
            ("verifier_config_sha256", verifier_config_sha256),
            ("slot_sha256", _canonical_sha256(payload)),
        ):
            object.__setattr__(result, name, value)
        result._validate()
        return result

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "slot": self.slot.to_dict(),
            "status": self.status,
            "candidate_evidence_ids": list(self.candidate_evidence_ids),
            "verified_evidence_ids": list(self.verified_evidence_ids),
            "missing_reason": self.missing_reason,
            "absence_confirmed": self.absence_confirmed,
            "contradiction_state": self.contradiction_state,
            "search_result_sha256": self.search_result_sha256,
            "verifier_id": self.verifier_id,
            "verifier_config_sha256": self.verifier_config_sha256,
        }

    def _validate(self) -> None:
        if type(self.slot) is not RequiredSlot:
            raise TypeError("compare_required_slot_required")
        if self.status not in _SLOT_STATUSES:
            raise ValueError("invalid_compare_slot_status")
        candidates = _ids(
            self.candidate_evidence_ids, "candidate_evidence_ids"
        )
        verified = _ids(self.verified_evidence_ids, "verified_evidence_ids")
        if not set(verified).issubset(candidates):
            raise ValueError("verified_evidence_not_candidate")
        if self.search_result_sha256 is not None:
            _hash(self.search_result_sha256, "invalid_search_result_sha256")
        if self.verifier_id not in _VERIFIER_IDS:
            raise ValueError("invalid_compare_verifier_id")
        _hash(self.verifier_config_sha256, "invalid_compare_verifier_config_sha256")
        if type(self.absence_confirmed) is not bool or self.absence_confirmed:
            raise ValueError("compare_absence_receipt_required")
        expected_shape = {
            "unsearched": (
                not candidates
                and not verified
                and self.missing_reason is None
                and self.contradiction_state == "unchecked"
                and self.search_result_sha256 is None
            ),
            "candidate": (
                not verified
                and self.missing_reason is None
                and self.contradiction_state == "unchecked"
                and self.search_result_sha256 is not None
            ),
            "verified": (
                bool(verified)
                and self.missing_reason is None
                and self.contradiction_state == "none"
                and self.search_result_sha256 is not None
            ),
            "missing": (
                not verified
                and self.missing_reason in _MISSING_REASONS
                and self.contradiction_state == "none"
                and self.search_result_sha256 is not None
            ),
            "contradicted": (
                len(verified) >= 2
                and self.missing_reason is None
                and self.contradiction_state == "confirmed"
                and self.search_result_sha256 is not None
            ),
        }[self.status]
        if not expected_shape:
            raise ValueError("compare_slot_state_shape_mismatch")
        if self.status == "missing":
            if (
                self.missing_reason == "no_candidate_yet"
                and candidates
            ):
                raise ValueError("missing_reason_candidate_mismatch")
            if (
                self.missing_reason == "candidates_unverified"
                and not candidates
            ):
                raise ValueError("missing_reason_candidate_mismatch")
        _hash(self.slot_sha256, "invalid_compare_slot_sha256")
        if self.slot_sha256 != _canonical_sha256(self._payload()):
            raise ValueError("compare_slot_hash_mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "slot_sha256": self.slot_sha256}

    @classmethod
    def from_dict(
        cls,
        raw: Mapping[str, Any],
        *,
        search_receipt: CompareSearchReceipt | None,
        verification_receipt: CompareVerificationReceipt | None,
    ) -> CompareSlotState:
        value = _closed(raw, _SLOT_STATE_FIELDS, "compare_slot_state_fields")
        if value["schema_version"] != "1.0":
            raise ValueError("unsupported_compare_slot_state_version")
        for name in ("candidate_evidence_ids", "verified_evidence_ids"):
            _json_list(value[name], f"compare_slot_{name}_array")
        slot = RequiredSlot.from_dict(value["slot"])
        if value["status"] == "contradicted":
            raise ValueError("compare_contradiction_receipt_required")
        if search_receipt is None:
            if value["status"] != "unsearched":
                raise ValueError("compare_search_receipt_required")
        else:
            if type(search_receipt) is not CompareSearchReceipt:
                raise TypeError("compare_search_receipt_required")
            if search_receipt.slot != slot:
                raise ValueError("compare_search_receipt_slot_mismatch")
            if tuple(value["candidate_evidence_ids"]) != tuple(
                candidate.evidence_id
                for candidate in search_receipt.result.candidates
            ):
                raise ValueError("compare_slot_candidates_receipt_mismatch")
            if value["search_result_sha256"] != search_receipt.result_sha256:
                raise ValueError("compare_slot_search_hash_mismatch")
        if verification_receipt is None:
            if value["status"] == "verified":
                raise ValueError("compare_verification_receipt_required")
            expected_verified: tuple[str, ...] = ()
        else:
            if type(verification_receipt) is not CompareVerificationReceipt:
                raise TypeError("compare_verification_receipt_required")
            if search_receipt is None:
                raise ValueError("verification_receipt_without_search_receipt")
            if verification_receipt.slot != slot:
                raise ValueError("compare_verification_slot_mismatch")
            if (
                verification_receipt.search_receipt_sha256
                != search_receipt.receipt_sha256
            ):
                raise ValueError("compare_verification_search_mismatch")
            # EH2.4 receipts only prove field relevance.  A future typed
            # claim/value receipt is required before a slot can be verified.
            expected_verified = ()
        if tuple(value["verified_evidence_ids"]) != expected_verified:
            raise ValueError("compare_slot_verification_receipt_mismatch")
        state = cls._create(
            slot=slot,
            status=value["status"],
            candidate_evidence_ids=tuple(value["candidate_evidence_ids"]),
            verified_evidence_ids=tuple(value["verified_evidence_ids"]),
            missing_reason=value["missing_reason"],
            absence_confirmed=value["absence_confirmed"],
            contradiction_state=value["contradiction_state"],
            search_result_sha256=value["search_result_sha256"],
            verifier_id=value["verifier_id"],
            verifier_config_sha256=value["verifier_config_sha256"],
            _token=_SLOT_STATE_TOKEN,
        )
        if _canonical_sha256(state.to_dict()) != _canonical_sha256(dict(value)):
            raise ValueError("compare_slot_state_payload_mismatch")
        return state


@dataclass(frozen=True, slots=True, init=False)
class CompareDocumentCoverage:
    doc_id: str
    required_slot_keys: tuple[str, ...]
    unsearched_slot_keys: tuple[str, ...]
    candidate_slot_keys: tuple[str, ...]
    verified_slot_keys: tuple[str, ...]
    missing_slot_keys: tuple[str, ...]
    contradicted_slot_keys: tuple[str, ...]
    accounted: bool
    complete: bool

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("compare_document_coverage_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        doc_id: str,
        states: tuple[CompareSlotState, ...],
        _token: object,
    ) -> CompareDocumentCoverage:
        if _token is not _DOCUMENT_COVERAGE_TOKEN:
            raise ValueError("compare_document_coverage_factory_required")
        payload = _document_coverage_payload(doc_id, states)
        result = object.__new__(cls)
        for name in _DOCUMENT_COVERAGE_FIELDS:
            value = payload[name]
            if name.endswith("_slot_keys"):
                value = tuple(value)
            object.__setattr__(result, name, value)
        result._validate(states)
        return result

    def _validate(self, states: tuple[CompareSlotState, ...]) -> None:
        expected = _document_coverage_payload(self.doc_id, states)
        if _canonical_sha256(self.to_dict()) != _canonical_sha256(expected):
            raise ValueError("compare_document_coverage_derived_mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "required_slot_keys": list(self.required_slot_keys),
            "unsearched_slot_keys": list(self.unsearched_slot_keys),
            "candidate_slot_keys": list(self.candidate_slot_keys),
            "verified_slot_keys": list(self.verified_slot_keys),
            "missing_slot_keys": list(self.missing_slot_keys),
            "contradicted_slot_keys": list(self.contradicted_slot_keys),
            "accounted": self.accounted,
            "complete": self.complete,
        }

    @classmethod
    def from_dict(
        cls,
        raw: Mapping[str, Any],
        *,
        states: tuple[CompareSlotState, ...],
    ) -> CompareDocumentCoverage:
        value = _closed(
            raw, _DOCUMENT_COVERAGE_FIELDS, "compare_document_coverage_fields"
        )
        for name in (
            "required_slot_keys",
            "unsearched_slot_keys",
            "candidate_slot_keys",
            "verified_slot_keys",
            "missing_slot_keys",
            "contradicted_slot_keys",
        ):
            _json_list(value[name], f"compare_document_{name}_array")
        result = cls._create(
            doc_id=value["doc_id"],
            states=states,
            _token=_DOCUMENT_COVERAGE_TOKEN,
        )
        if _canonical_sha256(result.to_dict()) != _canonical_sha256(dict(value)):
            raise ValueError("compare_document_coverage_payload_mismatch")
        return result


def _derived_coverage_payload(
    *,
    bound: BoundCompare,
    store: EvidenceStore,
    verifier_id: str,
    verifier_config_sha256: str,
    slots: tuple[CompareSlotState, ...],
) -> dict[str, Any]:
    documents = tuple(
        CompareDocumentCoverage._create(
            doc_id=doc_id,
            states=tuple(state for state in slots if state.slot.doc_id == doc_id),
            _token=_DOCUMENT_COVERAGE_TOKEN,
        )
        for doc_id in bound.plan.resolved_doc_ids
    )
    counts = {
        status: sum(state.status == status for state in slots)
        for status in _SLOT_STATUSES
    }
    required = len(slots)
    if required < 1 or not documents:
        raise ValueError("compare_slot_matrix_required")
    accounted_count = counts["verified"] + counts["contradicted"]
    normally_covered_count = counts["verified"]
    covered_docs = tuple(doc.doc_id for doc in documents if doc.complete)
    accounted_docs = tuple(doc.doc_id for doc in documents if doc.accounted)
    accounted_complete = accounted_count == required
    coverage_complete = (
        normally_covered_count == required
        and len(covered_docs) == len(documents)
    )
    normal_stop_allowed = coverage_complete and not counts["contradicted"]
    abstain_required = accounted_complete and bool(counts["contradicted"])
    if not accounted_complete:
        answerability = "in_progress"
    elif counts["contradicted"]:
        answerability = "conflict"
    else:
        answerability = "complete"
    return {
        "schema_version": "1.0",
        "binding_sha256": bound.binding_sha256,
        "effective_plan_sha256": bound.trace.effective_plan_sha256,
        "evidence_bundle_sha256": store.bundle_sha256,
        "verifier_id": verifier_id,
        "verifier_config_sha256": verifier_config_sha256,
        "slots": [state.to_dict() for state in slots],
        "documents": [document.to_dict() for document in documents],
        "required_slot_count": required,
        "verified_slot_count": counts["verified"],
        "missing_slot_count": counts["missing"],
        "contradicted_slot_count": counts["contradicted"],
        "open_slot_count": (
            counts["unsearched"] + counts["candidate"] + counts["missing"]
        ),
        "accounted_slot_count": accounted_count,
        "covered_document_ids": list(covered_docs),
        "accounted_document_ids": list(accounted_docs),
        "slot_coverage_ratio": normally_covered_count / required,
        "document_coverage_ratio": len(covered_docs) / len(documents),
        "accounted_complete": accounted_complete,
        "coverage_complete": coverage_complete,
        "normal_stop_allowed": normal_stop_allowed,
        "abstain_required": abstain_required,
        "answerability": answerability,
    }


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class CompareCoverage:
    binding_sha256: str
    effective_plan_sha256: str
    evidence_bundle_sha256: str
    verifier_id: str
    verifier_config_sha256: str
    slots: tuple[CompareSlotState, ...]
    documents: tuple[CompareDocumentCoverage, ...]
    required_slot_count: int
    verified_slot_count: int
    missing_slot_count: int
    contradicted_slot_count: int
    open_slot_count: int
    accounted_slot_count: int
    covered_document_ids: tuple[str, ...]
    accounted_document_ids: tuple[str, ...]
    slot_coverage_ratio: float
    document_coverage_ratio: float
    accounted_complete: bool
    coverage_complete: bool
    normal_stop_allowed: bool
    abstain_required: bool
    answerability: str
    coverage_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("compare_coverage_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        bound: BoundCompare,
        store: EvidenceStore,
        verifier_id: str,
        verifier_config_sha256: str,
        slots: tuple[CompareSlotState, ...],
        _token: object,
    ) -> CompareCoverage:
        if _token is not _COMPARE_COVERAGE_TOKEN:
            raise ValueError("compare_coverage_factory_required")
        documents = tuple(
            CompareDocumentCoverage._create(
                doc_id=doc_id,
                states=tuple(state for state in slots if state.slot.doc_id == doc_id),
                _token=_DOCUMENT_COVERAGE_TOKEN,
            )
            for doc_id in bound.plan.resolved_doc_ids
        )
        counts = {
            status: sum(state.status == status for state in slots)
            for status in _SLOT_STATUSES
        }
        required = len(slots)
        accounted_count = counts["verified"] + counts["contradicted"]
        normally_covered_count = counts["verified"]
        covered_docs = tuple(doc.doc_id for doc in documents if doc.complete)
        accounted_docs = tuple(doc.doc_id for doc in documents if doc.accounted)
        accounted_complete = bool(required) and accounted_count == required
        coverage_complete = (
            bool(required)
            and normally_covered_count == required
            and len(covered_docs) == len(documents)
        )
        normal_stop_allowed = coverage_complete and not counts["contradicted"]
        abstain_required = accounted_complete and bool(counts["contradicted"])
        if not accounted_complete:
            answerability = "in_progress"
        elif counts["contradicted"]:
            answerability = "conflict"
        else:
            answerability = "complete"
        base = {
            "schema_version": "1.0",
            "binding_sha256": bound.binding_sha256,
            "effective_plan_sha256": bound.trace.effective_plan_sha256,
            "evidence_bundle_sha256": store.bundle_sha256,
            "verifier_id": verifier_id,
            "verifier_config_sha256": verifier_config_sha256,
            "slots": [state.to_dict() for state in slots],
            "documents": [document.to_dict() for document in documents],
            "required_slot_count": required,
            "verified_slot_count": counts["verified"],
            "missing_slot_count": counts["missing"],
            "contradicted_slot_count": counts["contradicted"],
            "open_slot_count": counts["unsearched"] + counts["candidate"] + counts["missing"],
            "accounted_slot_count": accounted_count,
            "covered_document_ids": list(covered_docs),
            "accounted_document_ids": list(accounted_docs),
            "slot_coverage_ratio": normally_covered_count / required,
            "document_coverage_ratio": len(covered_docs) / len(documents),
            "accounted_complete": accounted_complete,
            "coverage_complete": coverage_complete,
            "normal_stop_allowed": normal_stop_allowed,
            "abstain_required": abstain_required,
            "answerability": answerability,
        }
        result = object.__new__(cls)
        for name, value in (
            ("binding_sha256", base["binding_sha256"]),
            ("effective_plan_sha256", base["effective_plan_sha256"]),
            ("evidence_bundle_sha256", base["evidence_bundle_sha256"]),
            ("verifier_id", verifier_id),
            ("verifier_config_sha256", verifier_config_sha256),
            ("slots", slots),
            ("documents", documents),
            ("required_slot_count", required),
            ("verified_slot_count", counts["verified"]),
            ("missing_slot_count", counts["missing"]),
            ("contradicted_slot_count", counts["contradicted"]),
            ("open_slot_count", counts["unsearched"] + counts["candidate"] + counts["missing"]),
            ("accounted_slot_count", accounted_count),
            ("covered_document_ids", covered_docs),
            ("accounted_document_ids", accounted_docs),
            ("slot_coverage_ratio", base["slot_coverage_ratio"]),
            ("document_coverage_ratio", base["document_coverage_ratio"]),
            ("accounted_complete", accounted_complete),
            ("coverage_complete", coverage_complete),
            ("normal_stop_allowed", normal_stop_allowed),
            ("abstain_required", abstain_required),
            ("answerability", answerability),
            ("coverage_sha256", _canonical_sha256(base)),
        ):
            object.__setattr__(result, name, value)
        _register_compare_coverage_authority(result)
        result._validate(bound, store)
        return result

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "binding_sha256": self.binding_sha256,
            "effective_plan_sha256": self.effective_plan_sha256,
            "evidence_bundle_sha256": self.evidence_bundle_sha256,
            "verifier_id": self.verifier_id,
            "verifier_config_sha256": self.verifier_config_sha256,
            "slots": [state.to_dict() for state in self.slots],
            "documents": [document.to_dict() for document in self.documents],
            "required_slot_count": self.required_slot_count,
            "verified_slot_count": self.verified_slot_count,
            "missing_slot_count": self.missing_slot_count,
            "contradicted_slot_count": self.contradicted_slot_count,
            "open_slot_count": self.open_slot_count,
            "accounted_slot_count": self.accounted_slot_count,
            "covered_document_ids": list(self.covered_document_ids),
            "accounted_document_ids": list(self.accounted_document_ids),
            "slot_coverage_ratio": self.slot_coverage_ratio,
            "document_coverage_ratio": self.document_coverage_ratio,
            "accounted_complete": self.accounted_complete,
            "coverage_complete": self.coverage_complete,
            "normal_stop_allowed": self.normal_stop_allowed,
            "abstain_required": self.abstain_required,
            "answerability": self.answerability,
        }

    def _validate(self, bound: BoundCompare, store: EvidenceStore) -> None:
        bound._validate()
        _require_compare_coverage_authority(self)
        if self.binding_sha256 != bound.binding_sha256:
            raise ValueError("compare_coverage_binding_mismatch")
        if self.effective_plan_sha256 != bound.trace.effective_plan_sha256:
            raise ValueError("compare_coverage_plan_mismatch")
        if self.evidence_bundle_sha256 != store.bundle_sha256:
            raise ValueError("compare_coverage_store_mismatch")
        if self.verifier_id != "deterministic-evidence-verifier-v1":
            raise ValueError("invalid_compare_verifier_id")
        if self.verifier_config_sha256 != _verifier_config_sha256(
            default_compare_field_registry()
        ):
            raise ValueError("compare_verifier_config_mismatch")
        if type(self.slots) is not tuple or any(
            type(state) is not CompareSlotState for state in self.slots
        ):
            raise TypeError("compare_slot_states_required")
        expected_slots = bound.plan.required_slots
        if tuple(state.slot for state in self.slots) != expected_slots:
            raise ValueError("compare_coverage_slot_matrix_mismatch")
        for state in self.slots:
            state._validate()
            if (
                state.verifier_id != self.verifier_id
                or state.verifier_config_sha256 != self.verifier_config_sha256
            ):
                raise ValueError("compare_slot_verifier_mismatch")
            # EH2.4 has only field-relevance receipts. It must not admit a
            # terminal state before the later typed value/contradiction leaf.
            if state.status in {"verified", "contradicted"}:
                raise ValueError("compare_terminal_slot_receipt_required")
            for evidence_id in (
                *state.candidate_evidence_ids,
                *state.verified_evidence_ids,
            ):
                try:
                    evidence = store.get(evidence_id)
                except KeyError as exc:
                    raise ValueError("unknown_compare_slot_evidence") from exc
                if evidence.doc_id != state.slot.doc_id or evidence.kind != "text":
                    raise ValueError("compare_slot_evidence_mismatch")
        if type(self.documents) is not tuple or any(
            type(document) is not CompareDocumentCoverage
            for document in self.documents
        ):
            raise TypeError("compare_document_coverages_required")
        if tuple(doc.doc_id for doc in self.documents) != bound.plan.resolved_doc_ids:
            raise ValueError("compare_document_coverage_mismatch")
        for document in self.documents:
            document._validate(
                tuple(
                    state
                    for state in self.slots
                    if state.slot.doc_id == document.doc_id
                )
            )
        expected_payload = _derived_coverage_payload(
            bound=bound,
            store=store,
            verifier_id=self.verifier_id,
            verifier_config_sha256=self.verifier_config_sha256,
            slots=self.slots,
        )
        if _canonical_sha256(self._payload()) != _canonical_sha256(expected_payload):
            raise ValueError("compare_coverage_derived_mismatch")
        if self.coverage_sha256 != _canonical_sha256(self._payload()):
            raise ValueError("compare_coverage_hash_mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "coverage_sha256": self.coverage_sha256}

    @classmethod
    def from_dict(
        cls,
        raw: Mapping[str, Any],
        *,
        bound: BoundCompare,
        store: EvidenceStore,
        candidate_results: Mapping[str, CompareSearchReceipt],
        verified_evidence: Mapping[str, CompareVerificationReceipt],
    ) -> CompareCoverage:
        if type(bound) is not BoundCompare:
            raise TypeError("bound_compare_required")
        if type(store) is not EvidenceStore:
            raise TypeError("evidence_store_required")
        bound._validate()
        if bound.trace.status != "ready":
            raise ValueError("compare_binding_not_ready")
        if bound.trace.evidence_bundle_sha256 != store.bundle_sha256:
            raise ValueError("compare_store_binding_mismatch")
        value = _closed(raw, _COVERAGE_FIELDS, "compare_coverage_fields")
        if value["schema_version"] != "1.0":
            raise ValueError("unsupported_compare_coverage_version")
        for name in (
            "slots",
            "documents",
            "covered_document_ids",
            "accounted_document_ids",
        ):
            _json_list(value[name], f"compare_coverage_{name}_array")
        searches = _mapping(
            candidate_results, "candidate_results_mapping_required"
        )
        verifications = _mapping(
            verified_evidence, "verified_evidence_mapping_required"
        )
        required = {slot.key: slot for slot in bound.plan.required_slots}
        serialized_slots: list[Mapping[str, Any]] = []
        searched_keys: set[str] = set()
        missing_reasons: dict[str, str] = {}
        for item in value["slots"]:
            if not isinstance(item, Mapping):
                raise TypeError("compare_slot_state_mapping_required")
            slot_value = item.get("slot")
            if not isinstance(slot_value, Mapping):
                raise TypeError("compare_required_slot_mapping_required")
            slot = RequiredSlot.from_dict(slot_value)
            if slot.key not in required or slot != required[slot.key]:
                raise ValueError("compare_coverage_slot_matrix_mismatch")
            if item.get("search_result_sha256") is not None:
                searched_keys.add(slot.key)
            if item.get("status") == "missing":
                missing_reasons[slot.key] = item.get("missing_reason")
            serialized_slots.append(item)
        if tuple(
            RequiredSlot.from_dict(item["slot"]).key for item in serialized_slots
        ) != tuple(required):
            raise ValueError("compare_coverage_slot_matrix_mismatch")
        if set(searches) != searched_keys:
            raise ValueError("compare_coverage_search_receipt_keys_mismatch")
        if not set(verifications).issubset(searches):
            raise ValueError("verified_slot_without_search_result")
        compare_registry = default_compare_field_registry()
        for slot_key, receipt in searches.items():
            if type(receipt) is not CompareSearchReceipt:
                raise TypeError("compare_search_receipt_required")
            if receipt.slot.key != slot_key:
                raise ValueError("compare_search_receipt_slot_mismatch")
            receipt._validate(bound, store)
        for slot_key, receipt in verifications.items():
            if type(receipt) is not CompareVerificationReceipt:
                raise TypeError("compare_verification_receipt_required")
            if receipt.slot.key != slot_key:
                raise ValueError("compare_verification_slot_mismatch")
            receipt._validate(bound, store, searches[slot_key], compare_registry)

        # Rebuild from the bound authority objects instead of trusting nested
        # slot/document booleans from JSON.  The exact payload comparison below
        # proves that every derived field matches this canonical reconstruction.
        result = build_compare_coverage(
            bound=bound,
            store=store,
            candidate_results=searches,
            verified_evidence=verifications,
            missing_reasons=missing_reasons,
            contradicted_evidence={},
        )
        if _canonical_sha256(result.to_dict()) != _canonical_sha256(dict(value)):
            raise ValueError("compare_coverage_payload_mismatch")
        return result


def build_compare_coverage(
    *,
    bound: BoundCompare,
    store: EvidenceStore,
    candidate_results: Mapping[str, CompareSearchReceipt],
    verified_evidence: Mapping[str, CompareVerificationReceipt],
    missing_reasons: Mapping[str, str],
    contradicted_evidence: Mapping[str, object],
) -> CompareCoverage:
    """Create coverage only from bound search and field-verification receipts."""

    if type(bound) is not BoundCompare:
        raise TypeError("bound_compare_required")
    if type(store) is not EvidenceStore:
        raise TypeError("evidence_store_required")
    bound._validate()
    if bound.trace.status != "ready":
        raise ValueError("compare_binding_not_ready")
    if bound.trace.evidence_bundle_sha256 != store.bundle_sha256:
        raise ValueError("compare_store_binding_mismatch")
    compare_registry = default_compare_field_registry()
    verifier_id = "deterministic-evidence-verifier-v1"
    verifier_config_sha256 = _verifier_config_sha256(compare_registry)

    results = _mapping(candidate_results, "candidate_results_mapping_required")
    verified_map = _mapping(verified_evidence, "verified_evidence_mapping_required")
    missing_map = _mapping(missing_reasons, "missing_reasons_mapping_required")
    contradicted_map = _mapping(
        contradicted_evidence, "contradicted_evidence_mapping_required"
    )
    required = {slot.key: slot for slot in bound.plan.required_slots}
    for mapping_value in (results, verified_map, missing_map, contradicted_map):
        if not set(mapping_value).issubset(required):
            raise ValueError("unknown_compare_slot_key")
    if set(missing_map) & set(contradicted_map):
        raise ValueError("missing_and_contradicted_slot_conflict")
    if not set(verified_map).issubset(results):
        raise ValueError("verified_slot_without_search_result")
    if not set(missing_map).issubset(results):
        raise ValueError("missing_slot_without_search_result")
    if contradicted_map:
        raise ValueError("compare_contradiction_receipt_required")

    for slot_key, receipt in results.items():
        if type(receipt) is not CompareSearchReceipt:
            raise TypeError("compare_search_receipt_required")
        if receipt.slot.key != slot_key:
            raise ValueError("compare_search_receipt_slot_mismatch")
        receipt._validate(bound, store)
    for slot_key, receipt in verified_map.items():
        if type(receipt) is not CompareVerificationReceipt:
            raise TypeError("compare_verification_receipt_required")
        search_receipt = results[slot_key]
        if receipt.slot.key != slot_key:
            raise ValueError("compare_verification_slot_mismatch")
        receipt._validate(bound, store, search_receipt, compare_registry)

    allowed_docs = frozenset(bound.plan.resolved_doc_ids)
    states: list[CompareSlotState] = []
    for slot in bound.plan.required_slots:
        if slot.key not in results:
            candidates: tuple[str, ...] = ()
            result_sha256 = None
        else:
            search_receipt = results[slot.key]
            candidates, result_sha256 = _validate_slot_result(
                slot, search_receipt.result, store, allowed_docs
            )
            if result_sha256 != search_receipt.result_sha256:
                raise ValueError("compare_search_receipt_result_mismatch")
        verification_receipt = verified_map.get(slot.key)
        # A field-signal hit is still only a candidate observation.  Do not
        # turn it into terminal support until the typed semantic verifier leaf.
        verified: tuple[str, ...] = ()
        for evidence_id in verified:
            if store.get(evidence_id).doc_id != slot.doc_id:
                raise ValueError("verified_evidence_document_mismatch")
        missing_reason = missing_map.get(slot.key)
        if missing_reason is not None and missing_reason not in _MISSING_REASONS:
            raise ValueError("invalid_compare_missing_reason")
        if missing_reason is not None:
            status = "missing"
            contradiction_state = "none"
        elif verified:
            status = "verified"
            contradiction_state = "none"
        elif result_sha256 is not None:
            status = "candidate"
            contradiction_state = "unchecked"
        else:
            status = "unsearched"
            contradiction_state = "unchecked"
        states.append(
            CompareSlotState._create(
                slot=slot,
                status=status,
                candidate_evidence_ids=candidates,
                verified_evidence_ids=verified,
                missing_reason=missing_reason,
                absence_confirmed=False,
                contradiction_state=contradiction_state,
                search_result_sha256=result_sha256,
                verifier_id=verifier_id,
                verifier_config_sha256=verifier_config_sha256,
                _token=_SLOT_STATE_TOKEN,
            )
        )
    return CompareCoverage._create(
        bound=bound,
        store=store,
        verifier_id=verifier_id,
        verifier_config_sha256=verifier_config_sha256,
        slots=tuple(states),
        _token=_COMPARE_COVERAGE_TOKEN,
    )
