"""Scoped follow-up retrieval, verified progress, and one-shot fallback."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any, Protocol
from weakref import ReferenceType, ref

from midprojectrag.evidence import EvidenceStore
from midprojectrag.retrieval import SearchResult
from midprojectrag.runtime_integrity import ResolvedScope

from .contracts import RuleRegistry, SCOPE_ORIGINS
from .followup_binding import BoundFollowup


_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_RETRIEVAL_ATTEMPT_TOKEN = object()
_PRIMARY_PROGRESS_TOKEN = object()
_RETRIEVAL_OUTCOME_TOKEN = object()
_SEARCH_LANES = frozenset({"rrf", "dense", "lexical", "orchestration_empty_scope"})
_VERIFIER_IDS = frozenset({"deterministic-evidence-verifier-v1"})
_RETRIEVAL_ATTEMPT_AUTHORITIES: dict[
    int,
    tuple[
        ReferenceType[FollowupRetrievalAttempt],
        str,
        SearchResult,
        ResolvedScope,
        BoundFollowup,
        EvidenceStore,
    ],
] = {}
_PRIMARY_PROGRESS_AUTHORITIES: dict[
    int,
    tuple[
        ReferenceType[PrimaryEvidenceProgress],
        str,
        BoundFollowup,
        FollowupRetrievalAttempt,
        EvidenceStore,
        str,
    ],
] = {}
_RETRIEVAL_OUTCOME_AUTHORITIES: dict[
    int,
    tuple[
        ReferenceType[FollowupRetrievalOutcome],
        str,
        FollowupRetrievalAttempt,
        PrimaryEvidenceProgress,
        FollowupRetrievalAttempt | None,
        FollowupRetrievalTrace,
        BoundFollowup,
        EvidenceStore,
        str,
    ],
] = {}


class ChildRetriever(Protocol):
    def search(
        self,
        query: str,
        *,
        dense_k: int,
        lexical_k: int,
        scope: ResolvedScope,
    ) -> SearchResult: ...


def _sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def _drop_authority(
    authorities: dict[int, tuple[Any, ...]],
    identity: int,
    dead: ReferenceType[Any],
) -> None:
    current = authorities.get(identity)
    if current is not None and current[0] is dead:
        authorities.pop(identity, None)


def _register_attempt_authority(
    attempt: FollowupRetrievalAttempt,
    *,
    bound: BoundFollowup,
    store: EvidenceStore,
) -> None:
    identity = id(attempt)
    weak = ref(
        attempt,
        lambda dead, identity=identity: _drop_authority(
            _RETRIEVAL_ATTEMPT_AUTHORITIES, identity, dead
        ),
    )
    _RETRIEVAL_ATTEMPT_AUTHORITIES[identity] = (
        weak,
        _sha256(attempt.to_dict()),
        attempt.result,
        attempt.scope,
        bound,
        store,
    )


def _require_attempt_authority(
    attempt: FollowupRetrievalAttempt,
    *,
    bound: BoundFollowup | None = None,
    store: EvidenceStore | None = None,
) -> None:
    if type(attempt) is not FollowupRetrievalAttempt:
        raise TypeError("followup_retrieval_attempt_required")
    current = _RETRIEVAL_ATTEMPT_AUTHORITIES.get(id(attempt))
    if current is None or current[0]() is not attempt:
        raise ValueError("followup_attempt_runtime_authority_required")
    if current[2] is not attempt.result or current[3] is not attempt.scope:
        raise ValueError("followup_attempt_nested_identity_drift")
    if (
        type(attempt.result) is not SearchResult
        or type(attempt.scope) is not ResolvedScope
    ):
        raise ValueError("followup_attempt_nested_type_drift")
    if bound is not None and current[4] is not bound:
        raise ValueError("followup_attempt_bound_identity_mismatch")
    if store is not None and current[5] is not store:
        raise ValueError("followup_attempt_store_identity_mismatch")
    try:
        actual = _sha256(attempt.to_dict())
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("followup_attempt_runtime_authority_drift") from exc
    if current[1] != actual:
        raise ValueError("followup_attempt_runtime_authority_drift")


def _register_progress_authority(
    progress: PrimaryEvidenceProgress,
    *,
    bound: BoundFollowup,
    primary: FollowupRetrievalAttempt,
    store: EvidenceStore,
    policy: FollowupEvidencePolicy,
) -> None:
    identity = id(progress)
    weak = ref(
        progress,
        lambda dead, identity=identity: _drop_authority(
            _PRIMARY_PROGRESS_AUTHORITIES, identity, dead
        ),
    )
    _PRIMARY_PROGRESS_AUTHORITIES[identity] = (
        weak,
        _sha256(progress.to_dict()),
        bound,
        primary,
        store,
        policy.policy_sha256,
    )


def _require_progress_authority(
    progress: PrimaryEvidenceProgress,
    *,
    bound: BoundFollowup | None = None,
    primary: FollowupRetrievalAttempt | None = None,
    store: EvidenceStore | None = None,
    policy: FollowupEvidencePolicy | None = None,
) -> None:
    if type(progress) is not PrimaryEvidenceProgress:
        raise TypeError("primary_evidence_progress_required")
    current = _PRIMARY_PROGRESS_AUTHORITIES.get(id(progress))
    if current is None or current[0]() is not progress:
        raise ValueError("primary_progress_runtime_authority_required")
    if bound is not None and current[2] is not bound:
        raise ValueError("primary_progress_bound_identity_mismatch")
    if primary is not None and current[3] is not primary:
        raise ValueError("primary_progress_attempt_identity_mismatch")
    if store is not None and current[4] is not store:
        raise ValueError("primary_progress_store_identity_mismatch")
    if policy is not None:
        if type(policy) is not FollowupEvidencePolicy:
            raise TypeError("followup_evidence_policy_required")
        if current[5] != policy.policy_sha256:
            raise ValueError("primary_progress_policy_authority_mismatch")
    scalar_hash_fields = (
        progress.request_fingerprint,
        progress.binding_sha256,
        progress.primary_result_sha256,
        progress.evidence_bundle_sha256,
        progress.policy_sha256,
        progress.verifier_config_sha256,
        progress.progress_sha256,
    )
    if any(type(value) is not str for value in scalar_hash_fields):
        raise ValueError("primary_progress_scalar_type_drift")
    if type(progress.verifier_id) is not str or type(progress.sufficient) is not bool:
        raise ValueError("primary_progress_scalar_type_drift")
    if (
        type(progress.verified_answer_evidence_ids) is not tuple
        or type(progress.verified_slot_evidence) is not tuple
        or type(progress.missing_required_slot_keys) is not tuple
        or any(type(value) is not str for value in progress.verified_answer_evidence_ids)
        or any(type(value) is not str for value in progress.missing_required_slot_keys)
        or any(
            type(pair) is not tuple
            or len(pair) != 2
            or any(type(value) is not str for value in pair)
            for pair in progress.verified_slot_evidence
        )
    ):
        raise ValueError("primary_progress_collection_type_drift")
    try:
        actual = _sha256(progress.to_dict())
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("primary_progress_runtime_authority_drift") from exc
    if current[1] != actual:
        raise ValueError("primary_progress_runtime_authority_drift")


def _register_outcome_authority(
    outcome: FollowupRetrievalOutcome,
    *,
    bound: BoundFollowup,
    store: EvidenceStore,
    policy: FollowupEvidencePolicy,
) -> None:
    identity = id(outcome)
    weak = ref(
        outcome,
        lambda dead, identity=identity: _drop_authority(
            _RETRIEVAL_OUTCOME_AUTHORITIES, identity, dead
        ),
    )
    _RETRIEVAL_OUTCOME_AUTHORITIES[identity] = (
        weak,
        _sha256(outcome.to_dict()),
        outcome.primary,
        outcome.progress,
        outcome.fallback,
        outcome.trace,
        bound,
        store,
        policy.policy_sha256,
    )


def _require_outcome_authority(
    outcome: FollowupRetrievalOutcome,
    *,
    bound: BoundFollowup | None = None,
    store: EvidenceStore | None = None,
    policy: FollowupEvidencePolicy | None = None,
) -> None:
    if type(outcome) is not FollowupRetrievalOutcome:
        raise TypeError("followup_retrieval_outcome_required")
    current = _RETRIEVAL_OUTCOME_AUTHORITIES.get(id(outcome))
    if current is None or current[0]() is not outcome:
        raise ValueError("followup_outcome_runtime_authority_required")
    if (
        current[2] is not outcome.primary
        or current[3] is not outcome.progress
        or current[4] is not outcome.fallback
        or current[5] is not outcome.trace
    ):
        raise ValueError("followup_outcome_nested_identity_drift")
    if (
        type(outcome.primary) is not FollowupRetrievalAttempt
        or type(outcome.progress) is not PrimaryEvidenceProgress
        or (
            outcome.fallback is not None
            and type(outcome.fallback) is not FollowupRetrievalAttempt
        )
        or type(outcome.trace) is not FollowupRetrievalTrace
    ):
        raise ValueError("followup_outcome_nested_type_drift")
    if bound is not None and current[6] is not bound:
        raise ValueError("followup_outcome_bound_identity_mismatch")
    if store is not None and current[7] is not store:
        raise ValueError("followup_outcome_store_identity_mismatch")
    if policy is not None:
        if type(policy) is not FollowupEvidencePolicy:
            raise TypeError("followup_evidence_policy_required")
        if current[8] != policy.policy_sha256:
            raise ValueError("followup_outcome_policy_authority_mismatch")
    try:
        actual = _sha256(outcome.to_dict())
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("followup_outcome_runtime_authority_drift") from exc
    if current[1] != actual:
        raise ValueError("followup_outcome_runtime_authority_drift")


def _require_hash(value: str, code: str) -> None:
    if type(value) is not str or not _HEX64.fullmatch(value):
        raise ValueError(code)


def _scope_dict(scope: ResolvedScope) -> dict[str, Any]:
    return {
        "state": scope.state,
        "doc_ids": sorted(scope.doc_ids),
        "origin": scope.origin,
    }


def _ids(value: Any, code: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(code)
    if any(type(item) is not str or not item for item in value):
        raise ValueError(code)
    if len(value) != len(set(value)):
        raise ValueError(f"duplicate_{code}")
    return value


def _binding_sha256(bound: BoundFollowup) -> str:
    return bound.binding_sha256


def _validate_bound(
    bound: BoundFollowup, store: EvidenceStore, registry: RuleRegistry
) -> None:
    if type(bound) is not BoundFollowup:
        raise TypeError("bound_followup_required")
    if type(store) is not EvidenceStore:
        raise TypeError("evidence_store_required")
    if type(registry) is not RuleRegistry:
        raise TypeError("rule_registry_required")
    bound._validate(store=store)
    registry.validate_plan(bound.plan)
    if bound.citations.evidence_bundle_sha256 != store.bundle_sha256:
        raise ValueError("followup_store_binding_mismatch")
    if bound.trace.evidence_bundle_sha256 != store.bundle_sha256:
        raise ValueError("followup_trace_store_mismatch")


def _validate_result(
    result: SearchResult,
    store: EvidenceStore,
    *,
    allowed_doc_ids: frozenset[str] | None,
) -> None:
    if type(result) is not SearchResult:
        raise TypeError("search_result_required")
    if result.trace.get("bundle_sha256") != store.bundle_sha256:
        raise ValueError("search_result_bundle_mismatch")
    if result.trace.get("granularity") != "child":
        raise ValueError("search_result_granularity_mismatch")
    if result.trace.get("lane") not in _SEARCH_LANES:
        raise ValueError("search_result_lane_mismatch")
    for expected_rank, candidate in enumerate(result.candidates, 1):
        if candidate.rank != expected_rank or candidate.granularity != "child":
            raise ValueError("search_candidate_rank_or_granularity_mismatch")
        if candidate.lane not in _SEARCH_LANES - {"orchestration_empty_scope"}:
            raise ValueError("search_candidate_lane_mismatch")
        try:
            evidence = store.get(candidate.evidence_id)
        except KeyError as exc:
            raise ValueError("unknown_search_evidence") from exc
        if evidence.kind != "text" or evidence.doc_id != candidate.doc_id:
            raise ValueError("search_candidate_evidence_mismatch")
        if allowed_doc_ids is not None and candidate.doc_id not in allowed_doc_ids:
            raise ValueError("search_candidate_scope_escape")


def _project_result(result: SearchResult, store: EvidenceStore) -> SearchResult:
    """Drop provider-controlled trace bodies at the orchestration boundary."""

    return SearchResult(
        result.candidates,
        {
            "schema_version": "1.0",
            "lane": result.trace["lane"],
            "granularity": "child",
            "bundle_sha256": store.bundle_sha256,
            "candidate_count": len(result.candidates),
            "trace_projection": "followup-safe-v1",
        },
    )


@dataclass(frozen=True, slots=True, init=False)
class FollowupEvidencePolicy:
    policy_version: str
    min_verified_answer_evidence: int
    policy_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("followup_policy_factory_required")

    @classmethod
    def v1(cls) -> FollowupEvidencePolicy:
        payload = {
            "schema_version": "1.0",
            "policy_version": "followup-evidence-v1",
            "min_verified_answer_evidence": 1,
            "sufficiency_source": "verified_answer_evidence_and_required_slots",
        }
        result = object.__new__(cls)
        object.__setattr__(result, "policy_version", payload["policy_version"])
        object.__setattr__(
            result,
            "min_verified_answer_evidence",
            payload["min_verified_answer_evidence"],
        )
        object.__setattr__(result, "policy_sha256", _sha256(payload))
        result._validate()
        return result

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "policy_version": self.policy_version,
            "min_verified_answer_evidence": self.min_verified_answer_evidence,
            "sufficiency_source": "verified_answer_evidence_and_required_slots",
        }

    def _validate(self) -> None:
        if (
            self.policy_version != "followup-evidence-v1"
            or self.min_verified_answer_evidence != 1
        ):
            raise ValueError("unapproved_followup_evidence_policy")
        _require_hash(self.policy_sha256, "invalid_policy_sha256")
        if self.policy_sha256 != _sha256(self._payload()):
            raise ValueError("followup_policy_hash_mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "policy_sha256": self.policy_sha256}


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class FollowupRetrievalAttempt:
    attempt_kind: str
    result: SearchResult
    scope: ResolvedScope
    request_fingerprint: str
    effective_plan_sha256: str
    binding_sha256: str
    evidence_bundle_sha256: str
    result_sha256: str
    retriever_called: bool

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("followup_attempt_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        attempt_kind: str,
        result: SearchResult,
        scope: ResolvedScope,
        bound: BoundFollowup,
        store: EvidenceStore,
        retriever_called: bool,
        _token: object,
    ) -> FollowupRetrievalAttempt:
        if _token is not _RETRIEVAL_ATTEMPT_TOKEN:
            raise ValueError("followup_attempt_factory_required")
        result_sha256 = _sha256(result.to_dict())
        values = {
            "attempt_kind": attempt_kind,
            "result": result,
            "scope": scope,
            "request_fingerprint": bound.trace.request_fingerprint,
            "effective_plan_sha256": bound.trace.effective_plan_sha256,
            "binding_sha256": _binding_sha256(bound),
            "evidence_bundle_sha256": store.bundle_sha256,
            "result_sha256": result_sha256,
            "retriever_called": retriever_called,
        }
        attempt = object.__new__(cls)
        for name, value in values.items():
            object.__setattr__(attempt, name, value)
        attempt._validate_payload()
        _register_attempt_authority(attempt, bound=bound, store=store)
        attempt._validate()
        return attempt

    def _validate(self) -> None:
        _require_attempt_authority(self)
        self._validate_payload()

    def _validate_payload(self) -> None:
        if self.attempt_kind not in {"primary", "global_fallback"}:
            raise ValueError("invalid_followup_attempt_kind")
        if type(self.result) is not SearchResult:
            raise TypeError("search_result_required")
        if type(self.scope) is not ResolvedScope:
            raise TypeError("resolved_scope_required")
        for name in (
            "request_fingerprint",
            "effective_plan_sha256",
            "binding_sha256",
            "evidence_bundle_sha256",
            "result_sha256",
        ):
            _require_hash(getattr(self, name), f"invalid_{name}")
        if _sha256(self.result.to_dict()) != self.result_sha256:
            raise ValueError("followup_attempt_result_hash_mismatch")
        if type(self.retriever_called) is not bool:
            raise TypeError("invalid_retriever_called")
        if self.attempt_kind == "global_fallback" and (
            self.scope.state != "unfiltered"
            or self.scope.origin != "all"
            or not self.retriever_called
        ):
            raise ValueError("invalid_global_fallback_attempt")
        if not self.retriever_called and self.result.candidates:
            raise ValueError("uncalled_retriever_has_candidates")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "attempt_kind": self.attempt_kind,
            "result": self.result.to_dict(),
            "scope": _scope_dict(self.scope),
            "request_fingerprint": self.request_fingerprint,
            "effective_plan_sha256": self.effective_plan_sha256,
            "binding_sha256": self.binding_sha256,
            "evidence_bundle_sha256": self.evidence_bundle_sha256,
            "result_sha256": self.result_sha256,
            "retriever_called": self.retriever_called,
        }


def _validate_attempt(
    attempt: FollowupRetrievalAttempt,
    *,
    expected_kind: str,
    bound: BoundFollowup,
    store: EvidenceStore,
) -> None:
    _require_attempt_authority(attempt, bound=bound, store=store)
    attempt._validate()
    if attempt.attempt_kind != expected_kind:
        raise ValueError("followup_attempt_kind_mismatch")
    if attempt.request_fingerprint != bound.trace.request_fingerprint:
        raise ValueError("followup_attempt_request_mismatch")
    if attempt.effective_plan_sha256 != bound.trace.effective_plan_sha256:
        raise ValueError("followup_attempt_plan_mismatch")
    if attempt.binding_sha256 != _binding_sha256(bound):
        raise ValueError("followup_attempt_binding_mismatch")
    if attempt.evidence_bundle_sha256 != store.bundle_sha256:
        raise ValueError("followup_attempt_store_mismatch")
    if expected_kind == "primary" and (
        attempt.scope.state != bound.plan.scope_state
        or attempt.scope.origin != bound.plan.scope_origin
        or attempt.scope.doc_ids != frozenset(bound.plan.resolved_doc_ids)
    ):
        raise ValueError("followup_primary_scope_mismatch")
    allowed = None if attempt.scope.state == "unfiltered" else attempt.scope.doc_ids
    _validate_result(attempt.result, store, allowed_doc_ids=allowed)


def retrieve_followup_primary(
    *,
    bound: BoundFollowup,
    store: EvidenceStore,
    registry: RuleRegistry,
    retriever: ChildRetriever,
) -> FollowupRetrievalAttempt:
    """Run exactly one scoped primary lookup, or none for a closed empty scope."""

    _validate_bound(bound, store, registry)
    plan = bound.plan
    if type(plan.dense_k) is not int or type(plan.lexical_k) is not int:
        raise ValueError("followup_retrieval_budget_required")
    scope = ResolvedScope(
        state=plan.scope_state,
        doc_ids=frozenset(plan.resolved_doc_ids),
        origin=plan.scope_origin,
    )
    if scope.state == "empty":
        result = SearchResult(
            (),
            {
                "lane": "orchestration_empty_scope",
                "granularity": "child",
                "bundle_sha256": store.bundle_sha256,
                "empty_scope": True,
                "retriever_calls": 0,
            },
        )
        called = False
    else:
        search = getattr(retriever, "search", None)
        if not callable(search):
            raise TypeError("child_retriever_required")
        result = search(
            plan.normalized_query,
            dense_k=plan.dense_k,
            lexical_k=plan.lexical_k,
            scope=scope,
        )
        called = True
    _validate_result(
        result,
        store,
        allowed_doc_ids=None if scope.state == "unfiltered" else scope.doc_ids,
    )
    result = _project_result(result, store)
    return FollowupRetrievalAttempt._create(
        attempt_kind="primary",
        result=result,
        scope=scope,
        bound=bound,
        store=store,
        retriever_called=called,
        _token=_RETRIEVAL_ATTEMPT_TOKEN,
    )


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class PrimaryEvidenceProgress:
    request_fingerprint: str
    binding_sha256: str
    primary_result_sha256: str
    evidence_bundle_sha256: str
    policy_sha256: str
    verifier_id: str
    verifier_config_sha256: str
    verified_answer_evidence_ids: tuple[str, ...]
    verified_slot_evidence: tuple[tuple[str, str], ...]
    missing_required_slot_keys: tuple[str, ...]
    sufficient: bool
    progress_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("primary_progress_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        bound: BoundFollowup,
        primary: FollowupRetrievalAttempt,
        store: EvidenceStore,
        policy: FollowupEvidencePolicy,
        verified_answer_evidence_ids: tuple[str, ...],
        verified_slot_evidence: tuple[tuple[str, str], ...],
        verifier_id: str,
        verifier_config_sha256: str,
        _token: object,
    ) -> PrimaryEvidenceProgress:
        if _token is not _PRIMARY_PROGRESS_TOKEN:
            raise ValueError("primary_progress_factory_required")
        verified_ids = tuple(sorted(_ids(
            verified_answer_evidence_ids, "verified_answer_evidence_ids"
        )))
        if type(verified_slot_evidence) is not tuple:
            raise TypeError("verified_slot_evidence")
        pairs: list[tuple[str, str]] = []
        for pair in verified_slot_evidence:
            if (
                type(pair) is not tuple
                or len(pair) != 2
                or any(type(value) is not str or not value for value in pair)
            ):
                raise ValueError("invalid_verified_slot_evidence")
            pairs.append(pair)
        ordered_pairs = tuple(sorted(pairs))
        if len({key for key, _ in ordered_pairs}) != len(ordered_pairs):
            raise ValueError("duplicate_verified_slot_key")

        candidate_ids = {candidate.evidence_id for candidate in primary.result.candidates}
        if not set(verified_ids).issubset(candidate_ids):
            raise ValueError("verified_evidence_not_in_primary")
        for evidence_id in verified_ids:
            store.get(evidence_id)
        slots = {slot.key: slot for slot in bound.plan.required_slots}
        for slot_key, evidence_id in ordered_pairs:
            if slot_key not in slots:
                raise ValueError("unknown_verified_slot")
            if evidence_id not in verified_ids:
                raise ValueError("slot_evidence_not_verified")
            if store.get(evidence_id).doc_id != slots[slot_key].doc_id:
                raise ValueError("slot_evidence_document_mismatch")
        missing = tuple(sorted(set(slots) - {key for key, _ in ordered_pairs}))
        sufficient = (
            len(verified_ids) >= policy.min_verified_answer_evidence and not missing
        )
        if verifier_id not in _VERIFIER_IDS:
            raise ValueError("invalid_verifier_id")
        _require_hash(verifier_config_sha256, "invalid_verifier_config_sha256")
        payload = {
            "schema_version": "1.0",
            "request_fingerprint": bound.trace.request_fingerprint,
            "binding_sha256": _binding_sha256(bound),
            "primary_result_sha256": primary.result_sha256,
            "evidence_bundle_sha256": store.bundle_sha256,
            "policy_sha256": policy.policy_sha256,
            "verifier_id": verifier_id,
            "verifier_config_sha256": verifier_config_sha256,
            "verified_answer_evidence_ids": list(verified_ids),
            "verified_slot_evidence": [
                {"slot_key": key, "evidence_id": evidence_id}
                for key, evidence_id in ordered_pairs
            ],
            "missing_required_slot_keys": list(missing),
            "sufficient": sufficient,
        }
        result = object.__new__(cls)
        for name, value in (
            ("request_fingerprint", payload["request_fingerprint"]),
            ("binding_sha256", payload["binding_sha256"]),
            ("primary_result_sha256", payload["primary_result_sha256"]),
            ("evidence_bundle_sha256", payload["evidence_bundle_sha256"]),
            ("policy_sha256", payload["policy_sha256"]),
            ("verifier_id", verifier_id),
            ("verifier_config_sha256", verifier_config_sha256),
            ("verified_answer_evidence_ids", verified_ids),
            ("verified_slot_evidence", ordered_pairs),
            ("missing_required_slot_keys", missing),
            ("sufficient", sufficient),
            ("progress_sha256", _sha256(payload)),
        ):
            object.__setattr__(result, name, value)
        result._validate_payload(policy)
        _register_progress_authority(
            result,
            bound=bound,
            primary=primary,
            store=store,
            policy=policy,
        )
        result._validate(policy)
        return result

    def _validate(self, policy: FollowupEvidencePolicy) -> None:
        _require_progress_authority(self, policy=policy)
        self._validate_payload(policy)

    def _validate_payload(self, policy: FollowupEvidencePolicy) -> None:
        if type(policy) is not FollowupEvidencePolicy:
            raise TypeError("followup_evidence_policy_required")
        policy._validate()
        for name in (
            "request_fingerprint",
            "binding_sha256",
            "primary_result_sha256",
            "evidence_bundle_sha256",
            "policy_sha256",
            "verifier_config_sha256",
            "progress_sha256",
        ):
            _require_hash(getattr(self, name), f"invalid_{name}")
        if self.policy_sha256 != policy.policy_sha256:
            raise ValueError("primary_progress_policy_mismatch")
        if self.verifier_id not in _VERIFIER_IDS:
            raise ValueError("invalid_verifier_id")
        if type(self.sufficient) is not bool:
            raise TypeError("invalid_primary_sufficiency")
        expected = (
            len(self.verified_answer_evidence_ids)
            >= policy.min_verified_answer_evidence
            and not self.missing_required_slot_keys
        )
        if self.sufficient != expected:
            raise ValueError("primary_sufficiency_mismatch")
        if self.progress_sha256 != _sha256(self._payload()):
            raise ValueError("primary_progress_hash_mismatch")

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "request_fingerprint": self.request_fingerprint,
            "binding_sha256": self.binding_sha256,
            "primary_result_sha256": self.primary_result_sha256,
            "evidence_bundle_sha256": self.evidence_bundle_sha256,
            "policy_sha256": self.policy_sha256,
            "verifier_id": self.verifier_id,
            "verifier_config_sha256": self.verifier_config_sha256,
            "verified_answer_evidence_ids": list(self.verified_answer_evidence_ids),
            "verified_slot_evidence": [
                {"slot_key": key, "evidence_id": evidence_id}
                for key, evidence_id in self.verified_slot_evidence
            ],
            "missing_required_slot_keys": list(self.missing_required_slot_keys),
            "sufficient": self.sufficient,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "progress_sha256": self.progress_sha256}


def bind_primary_evidence_progress(
    *,
    bound: BoundFollowup,
    primary: FollowupRetrievalAttempt,
    store: EvidenceStore,
    registry: RuleRegistry,
    policy: FollowupEvidencePolicy,
    verified_answer_evidence_ids: tuple[str, ...],
    verified_slot_evidence: tuple[tuple[str, str], ...] = (),
    verifier_id: str,
    verifier_config_sha256: str,
) -> PrimaryEvidenceProgress:
    """Bind verifier output to candidates; no caller-provided sufficiency flag exists."""

    _validate_bound(bound, store, registry)
    _validate_attempt(
        primary, expected_kind="primary", bound=bound, store=store
    )
    if type(policy) is not FollowupEvidencePolicy:
        raise TypeError("followup_evidence_policy_required")
    policy._validate()
    progress = PrimaryEvidenceProgress._create(
        bound=bound,
        primary=primary,
        store=store,
        policy=policy,
        verified_answer_evidence_ids=verified_answer_evidence_ids,
        verified_slot_evidence=verified_slot_evidence,
        verifier_id=verifier_id,
        verifier_config_sha256=verifier_config_sha256,
        _token=_PRIMARY_PROGRESS_TOKEN,
    )
    _require_progress_authority(
        progress,
        bound=bound,
        primary=primary,
        store=store,
        policy=policy,
    )
    return progress


_FOLLOWUP_REASONS = frozenset(
    {
        "primary_sufficient",
        "primary_insufficient_fallback_not_authorized",
        "primary_insufficient_global_fallback_executed",
    }
)


@dataclass(frozen=True, slots=True)
class FollowupRetrievalTrace:
    request_fingerprint: str
    config_sha256: str
    effective_plan_sha256: str
    binding_sha256: str
    evidence_bundle_sha256: str
    policy_sha256: str
    primary_result_sha256: str
    progress_sha256: str
    fallback_result_sha256: str | None
    primary_scope_state: str
    primary_scope_origin: str
    primary_doc_ids: tuple[str, ...]
    primary_candidate_count: int
    verified_evidence_count: int
    required_slot_count: int
    verified_slot_count: int
    missing_slot_count: int
    sufficient: bool
    fallback_authorized: bool
    fallback_executed: bool
    fallback_candidate_count: int
    reason: str

    def __post_init__(self) -> None:
        for name in (
            "request_fingerprint",
            "config_sha256",
            "effective_plan_sha256",
            "binding_sha256",
            "evidence_bundle_sha256",
            "policy_sha256",
            "primary_result_sha256",
            "progress_sha256",
        ):
            _require_hash(getattr(self, name), f"invalid_{name}")
        if self.fallback_result_sha256 is not None:
            _require_hash(
                self.fallback_result_sha256, "invalid_fallback_result_sha256"
            )
        if self.primary_scope_state not in {"empty", "restricted"}:
            raise ValueError("invalid_followup_primary_scope_state")
        if self.primary_scope_origin not in SCOPE_ORIGINS:
            raise ValueError("invalid_followup_primary_scope_origin")
        object.__setattr__(
            self,
            "primary_doc_ids",
            _ids(tuple(self.primary_doc_ids), "primary_doc_ids"),
        )
        if (self.primary_scope_state == "restricted") != bool(self.primary_doc_ids):
            raise ValueError("inconsistent_followup_primary_scope")
        for name in (
            "primary_candidate_count",
            "verified_evidence_count",
            "required_slot_count",
            "verified_slot_count",
            "missing_slot_count",
            "fallback_candidate_count",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(f"invalid_{name}")
        if self.verified_slot_count + self.missing_slot_count != self.required_slot_count:
            raise ValueError("inconsistent_followup_slot_counts")
        if any(
            type(value) is not bool
            for value in (
                self.sufficient,
                self.fallback_authorized,
                self.fallback_executed,
            )
        ):
            raise TypeError("invalid_followup_retrieval_boolean")
        if self.reason not in _FOLLOWUP_REASONS:
            raise ValueError("invalid_followup_retrieval_reason")
        if self.fallback_executed != (self.fallback_result_sha256 is not None):
            raise ValueError("fallback_result_execution_mismatch")
        if not self.fallback_executed and self.fallback_candidate_count:
            raise ValueError("uncalled_fallback_has_candidates")
        expected_reason = (
            "primary_sufficient"
            if self.sufficient
            else (
                "primary_insufficient_global_fallback_executed"
                if self.fallback_authorized
                else "primary_insufficient_fallback_not_authorized"
            )
        )
        if self.reason != expected_reason:
            raise ValueError("followup_retrieval_reason_mismatch")
        if self.fallback_executed != (
            not self.sufficient and self.fallback_authorized
        ):
            raise ValueError("followup_fallback_decision_mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            **{
                name: (
                    list(value)
                    if name == "primary_doc_ids"
                    else value
                )
                for name, value in (
                    ("request_fingerprint", self.request_fingerprint),
                    ("config_sha256", self.config_sha256),
                    ("effective_plan_sha256", self.effective_plan_sha256),
                    ("binding_sha256", self.binding_sha256),
                    ("evidence_bundle_sha256", self.evidence_bundle_sha256),
                    ("policy_sha256", self.policy_sha256),
                    ("primary_result_sha256", self.primary_result_sha256),
                    ("progress_sha256", self.progress_sha256),
                    ("fallback_result_sha256", self.fallback_result_sha256),
                    ("primary_scope_state", self.primary_scope_state),
                    ("primary_scope_origin", self.primary_scope_origin),
                    ("primary_doc_ids", self.primary_doc_ids),
                    ("primary_candidate_count", self.primary_candidate_count),
                    ("verified_evidence_count", self.verified_evidence_count),
                    ("required_slot_count", self.required_slot_count),
                    ("verified_slot_count", self.verified_slot_count),
                    ("missing_slot_count", self.missing_slot_count),
                    ("sufficient", self.sufficient),
                    ("fallback_authorized", self.fallback_authorized),
                    ("fallback_executed", self.fallback_executed),
                    ("fallback_candidate_count", self.fallback_candidate_count),
                    ("reason", self.reason),
                )
            },
        }


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class FollowupRetrievalOutcome:
    primary: FollowupRetrievalAttempt
    progress: PrimaryEvidenceProgress
    fallback: FollowupRetrievalAttempt | None
    trace: FollowupRetrievalTrace

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("followup_outcome_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        primary: FollowupRetrievalAttempt,
        progress: PrimaryEvidenceProgress,
        fallback: FollowupRetrievalAttempt | None,
        trace: FollowupRetrievalTrace,
        bound: BoundFollowup,
        store: EvidenceStore,
        policy: FollowupEvidencePolicy,
        _token: object,
    ) -> FollowupRetrievalOutcome:
        if _token is not _RETRIEVAL_OUTCOME_TOKEN:
            raise ValueError("followup_outcome_factory_required")
        result = object.__new__(cls)
        for name, value in (
            ("primary", primary),
            ("progress", progress),
            ("fallback", fallback),
            ("trace", trace),
        ):
            object.__setattr__(result, name, value)
        result._validate_payload()
        _register_outcome_authority(
            result,
            bound=bound,
            store=store,
            policy=policy,
        )
        result._validate()
        return result

    def _validate(self) -> None:
        _require_outcome_authority(self)
        self._validate_payload()

    def _validate_payload(self) -> None:
        if type(self.primary) is not FollowupRetrievalAttempt:
            raise TypeError("followup_primary_attempt_required")
        if type(self.progress) is not PrimaryEvidenceProgress:
            raise TypeError("primary_evidence_progress_required")
        if self.fallback is not None and type(self.fallback) is not FollowupRetrievalAttempt:
            raise TypeError("followup_fallback_attempt_required")
        if type(self.trace) is not FollowupRetrievalTrace:
            raise TypeError("followup_retrieval_trace_required")
        if self.primary.result_sha256 != self.trace.primary_result_sha256:
            raise ValueError("outcome_primary_trace_mismatch")
        if self.progress.progress_sha256 != self.trace.progress_sha256:
            raise ValueError("outcome_progress_trace_mismatch")
        fallback_sha = None if self.fallback is None else self.fallback.result_sha256
        if fallback_sha != self.trace.fallback_result_sha256:
            raise ValueError("outcome_fallback_trace_mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "primary": self.primary.to_dict(),
            "progress": self.progress.to_dict(),
            "fallback": None if self.fallback is None else self.fallback.to_dict(),
            "trace": self.trace.to_dict(),
        }


def _fallback_authorized(bound: BoundFollowup) -> bool:
    return bool(
        bound.trace.fallback_authorized
        and bound.plan.allow_global_fallback
        and bound.trace.prior_scope_state == "unfiltered"
        and bound.trace.prior_scope_origin == "all"
        and bound.plan.scope_origin == "followup_citations"
        and bound.plan.scope_state == "restricted"
    )


def _build_followup_retrieval_trace(
    *,
    bound: BoundFollowup,
    primary: FollowupRetrievalAttempt,
    progress: PrimaryEvidenceProgress,
    fallback: FollowupRetrievalAttempt | None,
    store: EvidenceStore,
    policy: FollowupEvidencePolicy,
) -> FollowupRetrievalTrace:
    fallback_authorized = _fallback_authorized(bound)
    reason = (
        "primary_sufficient"
        if progress.sufficient
        else (
            "primary_insufficient_global_fallback_executed"
            if fallback_authorized
            else "primary_insufficient_fallback_not_authorized"
        )
    )
    return FollowupRetrievalTrace(
        request_fingerprint=bound.trace.request_fingerprint,
        config_sha256=bound.trace.config_sha256,
        effective_plan_sha256=bound.trace.effective_plan_sha256,
        binding_sha256=_binding_sha256(bound),
        evidence_bundle_sha256=store.bundle_sha256,
        policy_sha256=policy.policy_sha256,
        primary_result_sha256=primary.result_sha256,
        progress_sha256=progress.progress_sha256,
        fallback_result_sha256=(
            None if fallback is None else fallback.result_sha256
        ),
        primary_scope_state=primary.scope.state,
        primary_scope_origin=primary.scope.origin,
        primary_doc_ids=tuple(sorted(primary.scope.doc_ids)),
        primary_candidate_count=len(primary.result.candidates),
        verified_evidence_count=len(progress.verified_answer_evidence_ids),
        required_slot_count=len(bound.plan.required_slots),
        verified_slot_count=len(progress.verified_slot_evidence),
        missing_slot_count=len(progress.missing_required_slot_keys),
        sufficient=progress.sufficient,
        fallback_authorized=fallback_authorized,
        fallback_executed=fallback is not None,
        fallback_candidate_count=(
            0 if fallback is None else len(fallback.result.candidates)
        ),
        reason=reason,
    )


def validate_followup_retrieval_outcome(
    *,
    bound: BoundFollowup,
    outcome: FollowupRetrievalOutcome,
    store: EvidenceStore,
    registry: RuleRegistry,
    policy: FollowupEvidencePolicy,
) -> None:
    """Purely validate a factory-issued outcome and its full authority chain."""

    _validate_bound(bound, store, registry)
    if type(policy) is not FollowupEvidencePolicy:
        raise TypeError("followup_evidence_policy_required")
    policy._validate()
    _require_outcome_authority(
        outcome,
        bound=bound,
        store=store,
        policy=policy,
    )
    outcome._validate()
    _validate_attempt(
        outcome.primary,
        expected_kind="primary",
        bound=bound,
        store=store,
    )
    _require_progress_authority(
        outcome.progress,
        bound=bound,
        primary=outcome.primary,
        store=store,
        policy=policy,
    )
    outcome.progress._validate(policy)
    if (
        outcome.progress.request_fingerprint != bound.trace.request_fingerprint
        or outcome.progress.binding_sha256 != _binding_sha256(bound)
        or outcome.progress.primary_result_sha256
        != outcome.primary.result_sha256
        or outcome.progress.evidence_bundle_sha256 != store.bundle_sha256
        or outcome.progress.policy_sha256 != policy.policy_sha256
    ):
        raise ValueError("primary_progress_binding_mismatch")

    fallback_authorized = _fallback_authorized(bound)
    expected_fallback = not outcome.progress.sufficient and fallback_authorized
    if (outcome.fallback is not None) != expected_fallback:
        raise ValueError("followup_outcome_fallback_decision_mismatch")
    if outcome.fallback is not None:
        _validate_attempt(
            outcome.fallback,
            expected_kind="global_fallback",
            bound=bound,
            store=store,
        )

    expected_trace = _build_followup_retrieval_trace(
        bound=bound,
        primary=outcome.primary,
        progress=outcome.progress,
        fallback=outcome.fallback,
        store=store,
        policy=policy,
    )
    if _sha256(outcome.trace.to_dict()) != _sha256(expected_trace.to_dict()):
        raise ValueError("followup_outcome_trace_integrity_mismatch")


def finalize_followup_retrieval(
    *,
    bound: BoundFollowup,
    primary: FollowupRetrievalAttempt,
    progress: PrimaryEvidenceProgress,
    store: EvidenceStore,
    registry: RuleRegistry,
    policy: FollowupEvidencePolicy,
    retriever: ChildRetriever,
) -> FollowupRetrievalOutcome:
    """Execute at most one authorized global lookup after verified insufficiency."""

    _validate_bound(bound, store, registry)
    _validate_attempt(
        primary, expected_kind="primary", bound=bound, store=store
    )
    if type(policy) is not FollowupEvidencePolicy:
        raise TypeError("followup_evidence_policy_required")
    policy._validate()
    _require_progress_authority(
        progress,
        bound=bound,
        primary=primary,
        store=store,
        policy=policy,
    )
    progress._validate(policy)
    if (
        progress.request_fingerprint != bound.trace.request_fingerprint
        or progress.binding_sha256 != _binding_sha256(bound)
        or progress.primary_result_sha256 != primary.result_sha256
        or progress.evidence_bundle_sha256 != store.bundle_sha256
    ):
        raise ValueError("primary_progress_binding_mismatch")

    fallback_authorized = _fallback_authorized(bound)
    fallback = None
    if not progress.sufficient and fallback_authorized:
        search = getattr(retriever, "search", None)
        if not callable(search):
            raise TypeError("child_retriever_required")
        fallback_scope = ResolvedScope()
        fallback_result = search(
            bound.plan.normalized_query,
            dense_k=bound.plan.dense_k,
            lexical_k=bound.plan.lexical_k,
            scope=fallback_scope,
        )
        _validate_result(fallback_result, store, allowed_doc_ids=None)
        fallback_result = _project_result(fallback_result, store)
        fallback = FollowupRetrievalAttempt._create(
            attempt_kind="global_fallback",
            result=fallback_result,
            scope=fallback_scope,
            bound=bound,
            store=store,
            retriever_called=True,
            _token=_RETRIEVAL_ATTEMPT_TOKEN,
        )

    trace = _build_followup_retrieval_trace(
        bound=bound,
        primary=primary,
        progress=progress,
        fallback=fallback,
        store=store,
        policy=policy,
    )
    outcome = FollowupRetrievalOutcome._create(
        primary=primary,
        progress=progress,
        fallback=fallback,
        trace=trace,
        bound=bound,
        store=store,
        policy=policy,
        _token=_RETRIEVAL_OUTCOME_TOKEN,
    )
    validate_followup_retrieval_outcome(
        bound=bound,
        outcome=outcome,
        store=store,
        registry=registry,
        policy=policy,
    )
    return outcome
