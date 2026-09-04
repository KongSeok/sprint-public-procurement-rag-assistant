"""Pure, authority-bound projection of orchestration evidence state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import json
import math
import re
from typing import Any
from weakref import ReferenceType, ref

from midprojectrag.evidence import EvidenceStore, validate_evidence_store_snapshot

from .compare_coverage import CompareCoverage
from .compare_slots import BoundCompare
from .contracts import PlanConstraint, PlanEntity, RuleRegistry
from .fact_binding import BoundFact, validate_bound_fact
from .followup_binding import BoundFollowup
from .followup_retrieval import (
    FollowupEvidencePolicy,
    FollowupRetrievalOutcome,
    PrimaryEvidenceProgress,
    validate_followup_retrieval_outcome,
)


_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_KINDS = frozenset({"fact", "compare", "follow_up"})
_OBSERVATION_STAGES = frozenset(
    {
        "unsearched",
        "candidate",
        "verified",
        "provisional_missing",
        "confirmed_missing",
        "contradicted",
    }
)
_ANSWERABILITY = frozenset({"in_progress", "complete", "partial", "conflict"})
_ENTRY_TOKEN = object()
_BELIEF_TOKEN = object()
_PROGRESS_TOKEN = object()
_STATE_TOKEN = object()
_ENTRY_AUTHORITIES: dict[int, tuple[Any, ...]] = {}
_BELIEF_AUTHORITIES: dict[int, tuple[Any, ...]] = {}
_PROGRESS_AUTHORITIES: dict[int, tuple[Any, ...]] = {}
_STATE_AUTHORITIES: dict[int, tuple[Any, ...]] = {}


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


def _require_ids(value: Any, code: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(code)
    if (not allow_empty and not value) or any(
        type(item) is not str or not item for item in value
    ):
        raise ValueError(code)
    if len(value) != len(set(value)):
        raise ValueError(f"duplicate_{code}")
    return value


def _drop_authority(
    authorities: dict[int, tuple[Any, ...]],
    identity: int,
    dead: ReferenceType[Any],
) -> None:
    current = authorities.get(identity)
    if current is not None and current[0] is dead:
        authorities.pop(identity, None)


def _register_authority(
    authorities: dict[int, tuple[Any, ...]],
    value: Any,
    payload: Mapping[str, Any],
    *context: Any,
) -> None:
    identity = id(value)
    weak = ref(
        value,
        lambda dead, identity=identity, authorities=authorities: _drop_authority(
            authorities, identity, dead
        ),
    )
    authorities[identity] = (weak, _canonical_sha256(payload), *context)


def _authority_record(
    authorities: dict[int, tuple[Any, ...]],
    value: Any,
    *,
    code: str,
) -> tuple[Any, ...]:
    current = authorities.get(id(value))
    if current is None or current[0]() is not value:
        raise ValueError(code)
    return current


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


def _validate_store_snapshot(store: EvidenceStore, expected_bundle_sha256: str) -> None:
    """Re-hash the live graph so frozen-object bypasses cannot alter authority."""

    try:
        validate_evidence_store_snapshot(store, expected_bundle_sha256)
    except ValueError as exc:
        if str(exc) == "evidence_store_bundle_mismatch":
            raise ValueError("harness_state_store_bundle_mismatch") from exc
        raise ValueError("harness_state_store_payload_drift") from exc


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class EvidenceBeliefEntry:
    obligation_key: str
    observation_stage: str
    candidate_evidence_ids: tuple[str, ...]
    verified_evidence_ids: tuple[str, ...]
    entry_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("evidence_belief_entry_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        obligation_key: str,
        observation_stage: str,
        candidate_evidence_ids: tuple[str, ...],
        verified_evidence_ids: tuple[str, ...],
        _token: object,
    ) -> EvidenceBeliefEntry:
        if _token is not _ENTRY_TOKEN:
            raise ValueError("evidence_belief_entry_factory_required")
        candidates = _require_ids(candidate_evidence_ids, "candidate_evidence_ids")
        verified = _require_ids(verified_evidence_ids, "verified_evidence_ids")
        base = {
            "schema_version": "1.0",
            "obligation_key": obligation_key,
            "observation_stage": observation_stage,
            "candidate_evidence_ids": list(candidates),
            "verified_evidence_ids": list(verified),
        }
        result = object.__new__(cls)
        object.__setattr__(result, "obligation_key", obligation_key)
        object.__setattr__(result, "observation_stage", observation_stage)
        object.__setattr__(result, "candidate_evidence_ids", candidates)
        object.__setattr__(result, "verified_evidence_ids", verified)
        object.__setattr__(result, "entry_sha256", _canonical_sha256(base))
        result._validate_payload()
        _register_authority(_ENTRY_AUTHORITIES, result, result.to_dict())
        result._validate()
        return result

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "obligation_key": self.obligation_key,
            "observation_stage": self.observation_stage,
            "candidate_evidence_ids": list(self.candidate_evidence_ids),
            "verified_evidence_ids": list(self.verified_evidence_ids),
        }

    def _validate_payload(self) -> None:
        if type(self.obligation_key) is not str or not self.obligation_key:
            raise ValueError("invalid_obligation_key")
        if self.observation_stage not in _OBSERVATION_STAGES:
            raise ValueError("invalid_observation_stage")
        candidates = _require_ids(
            self.candidate_evidence_ids, "candidate_evidence_ids"
        )
        verified = _require_ids(self.verified_evidence_ids, "verified_evidence_ids")
        if not set(verified).issubset(candidates):
            raise ValueError("verified_evidence_not_candidate")
        if self.observation_stage == "unsearched" and (candidates or verified):
            raise ValueError("unsearched_obligation_has_evidence")
        if self.observation_stage == "candidate" and (
            not candidates or verified
        ):
            raise ValueError("candidate_obligation_shape_mismatch")
        if self.observation_stage == "verified" and not verified:
            raise ValueError("verified_obligation_requires_evidence")
        if self.observation_stage in {"provisional_missing", "confirmed_missing"} and verified:
            raise ValueError("missing_obligation_has_verified_evidence")
        _require_hash(self.entry_sha256, "invalid_entry_sha256")
        if self.entry_sha256 != _canonical_sha256(self._payload()):
            raise ValueError("evidence_belief_entry_hash_mismatch")

    def _validate(self) -> None:
        current = _authority_record(
            _ENTRY_AUTHORITIES,
            self,
            code="evidence_belief_entry_runtime_authority_required",
        )
        self._validate_payload()
        if current[1] != _canonical_sha256(self.to_dict()):
            raise ValueError("evidence_belief_entry_runtime_authority_drift")

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "entry_sha256": self.entry_sha256}


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class Belief:
    source_kind: str
    request_fingerprint: str
    binding_sha256: str
    effective_plan_sha256: str
    config_sha256: str
    evidence_bundle_sha256: str
    query_type: str
    entities: tuple[PlanEntity, ...]
    constraints: tuple[PlanConstraint, ...]
    scope_state: str
    scope_origin: str
    scope_doc_ids: tuple[str, ...]
    evidence_map: tuple[EvidenceBeliefEntry, ...]
    source_receipt_sha256: str
    belief_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("belief_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        source_kind: str,
        request_fingerprint: str,
        binding_sha256: str,
        effective_plan_sha256: str,
        config_sha256: str,
        evidence_bundle_sha256: str,
        query_type: str,
        entities: tuple[PlanEntity, ...],
        constraints: tuple[PlanConstraint, ...],
        scope_state: str,
        scope_origin: str,
        scope_doc_ids: tuple[str, ...],
        evidence_map: tuple[EvidenceBeliefEntry, ...],
        source_receipt_sha256: str,
        _token: object,
    ) -> Belief:
        if _token is not _BELIEF_TOKEN:
            raise ValueError("belief_factory_required")
        result = object.__new__(cls)
        for name, value in (
            ("source_kind", source_kind),
            ("request_fingerprint", request_fingerprint),
            ("binding_sha256", binding_sha256),
            ("effective_plan_sha256", effective_plan_sha256),
            ("config_sha256", config_sha256),
            ("evidence_bundle_sha256", evidence_bundle_sha256),
            ("query_type", query_type),
            ("entities", entities),
            ("constraints", constraints),
            ("scope_state", scope_state),
            ("scope_origin", scope_origin),
            ("scope_doc_ids", scope_doc_ids),
            ("evidence_map", evidence_map),
            ("source_receipt_sha256", source_receipt_sha256),
        ):
            object.__setattr__(result, name, value)
        object.__setattr__(result, "belief_sha256", _canonical_sha256(result._payload()))
        result._validate_payload()
        _register_authority(
            _BELIEF_AUTHORITIES,
            result,
            result.to_dict(),
            result.entities,
            result.constraints,
            result.scope_doc_ids,
            result.evidence_map,
            tuple(result.evidence_map),
        )
        result._validate()
        return result

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "source_kind": self.source_kind,
            "request_fingerprint": self.request_fingerprint,
            "binding_sha256": self.binding_sha256,
            "effective_plan_sha256": self.effective_plan_sha256,
            "config_sha256": self.config_sha256,
            "evidence_bundle_sha256": self.evidence_bundle_sha256,
            "query_type": self.query_type,
            "entities": [value.to_dict() for value in self.entities],
            "constraints": [value.to_dict() for value in self.constraints],
            "scope_state": self.scope_state,
            "scope_origin": self.scope_origin,
            "scope_doc_ids": list(self.scope_doc_ids),
            "evidence_map": [value.to_dict() for value in self.evidence_map],
            "source_receipt_sha256": self.source_receipt_sha256,
        }

    def _validate_payload(self) -> None:
        if self.source_kind not in _SOURCE_KINDS:
            raise ValueError("invalid_belief_source_kind")
        for name in (
            "request_fingerprint",
            "binding_sha256",
            "effective_plan_sha256",
            "config_sha256",
            "evidence_bundle_sha256",
            "source_receipt_sha256",
            "belief_sha256",
        ):
            _require_hash(getattr(self, name), f"invalid_{name}")
        if self.query_type != self.source_kind:
            raise ValueError("belief_query_source_mismatch")
        if type(self.entities) is not tuple or any(
            type(value) is not PlanEntity for value in self.entities
        ):
            raise TypeError("belief_entities_required")
        if type(self.constraints) is not tuple or any(
            type(value) is not PlanConstraint for value in self.constraints
        ):
            raise TypeError("belief_constraints_required")
        scope_doc_ids = _require_ids(self.scope_doc_ids, "belief_scope_doc_ids")
        if self.scope_state not in {"empty", "restricted", "unfiltered"}:
            raise ValueError("invalid_belief_scope_state")
        if (self.scope_state == "restricted") != bool(scope_doc_ids):
            raise ValueError("inconsistent_belief_scope")
        if type(self.scope_origin) is not str or not self.scope_origin:
            raise ValueError("invalid_belief_scope_origin")
        if type(self.evidence_map) is not tuple or not self.evidence_map:
            raise ValueError("belief_evidence_map_required")
        if any(type(value) is not EvidenceBeliefEntry for value in self.evidence_map):
            raise TypeError("invalid_belief_evidence_map")
        for value in self.evidence_map:
            value._validate()
        keys = tuple(value.obligation_key for value in self.evidence_map)
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate_belief_obligation")
        if self.belief_sha256 != _canonical_sha256(self._payload()):
            raise ValueError("belief_hash_mismatch")

    def _validate(self) -> None:
        current = _authority_record(
            _BELIEF_AUTHORITIES, self, code="belief_runtime_authority_required"
        )
        if (
            current[2] is not self.entities
            or current[3] is not self.constraints
            or current[4] is not self.scope_doc_ids
            or current[5] is not self.evidence_map
            or any(
                issued is not actual
                for issued, actual in zip(current[6], self.evidence_map)
            )
            or len(current[6]) != len(self.evidence_map)
        ):
            raise ValueError("belief_nested_identity_drift")
        self._validate_payload()
        if current[1] != _canonical_sha256(self.to_dict()):
            raise ValueError("belief_runtime_authority_drift")

    def entry(self, obligation_key: str) -> EvidenceBeliefEntry:
        self._validate()
        for value in self.evidence_map:
            if value.obligation_key == obligation_key:
                return value
        raise KeyError(obligation_key)

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "belief_sha256": self.belief_sha256}


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class Progress:
    required_obligation_keys: tuple[str, ...]
    verified_obligation_keys: tuple[str, ...]
    provisional_missing_obligation_keys: tuple[str, ...]
    confirmed_missing_obligation_keys: tuple[str, ...]
    contradicted_obligation_keys: tuple[str, ...]
    open_obligation_keys: tuple[str, ...]
    slot_coverage_ratio: float
    answerability: str
    normal_stop_allowed: bool
    abstain_required: bool
    progress_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("harness_progress_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        required_obligation_keys: tuple[str, ...],
        verified_obligation_keys: tuple[str, ...],
        provisional_missing_obligation_keys: tuple[str, ...],
        confirmed_missing_obligation_keys: tuple[str, ...],
        contradicted_obligation_keys: tuple[str, ...],
        open_obligation_keys: tuple[str, ...],
        slot_coverage_ratio: float,
        answerability: str,
        normal_stop_allowed: bool,
        abstain_required: bool,
        _token: object,
    ) -> Progress:
        if _token is not _PROGRESS_TOKEN:
            raise ValueError("harness_progress_factory_required")
        result = object.__new__(cls)
        for name, value in (
            ("required_obligation_keys", required_obligation_keys),
            ("verified_obligation_keys", verified_obligation_keys),
            (
                "provisional_missing_obligation_keys",
                provisional_missing_obligation_keys,
            ),
            ("confirmed_missing_obligation_keys", confirmed_missing_obligation_keys),
            ("contradicted_obligation_keys", contradicted_obligation_keys),
            ("open_obligation_keys", open_obligation_keys),
            ("slot_coverage_ratio", slot_coverage_ratio),
            ("answerability", answerability),
            ("normal_stop_allowed", normal_stop_allowed),
            ("abstain_required", abstain_required),
        ):
            object.__setattr__(result, name, value)
        object.__setattr__(
            result, "progress_sha256", _canonical_sha256(result._payload())
        )
        result._validate_payload()
        _register_authority(
            _PROGRESS_AUTHORITIES,
            result,
            result.to_dict(),
            result.required_obligation_keys,
            result.verified_obligation_keys,
            result.provisional_missing_obligation_keys,
            result.confirmed_missing_obligation_keys,
            result.contradicted_obligation_keys,
            result.open_obligation_keys,
        )
        result._validate()
        return result

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "required_obligation_keys": list(self.required_obligation_keys),
            "verified_obligation_keys": list(self.verified_obligation_keys),
            "provisional_missing_obligation_keys": list(
                self.provisional_missing_obligation_keys
            ),
            "confirmed_missing_obligation_keys": list(
                self.confirmed_missing_obligation_keys
            ),
            "contradicted_obligation_keys": list(self.contradicted_obligation_keys),
            "open_obligation_keys": list(self.open_obligation_keys),
            "slot_coverage_ratio": self.slot_coverage_ratio,
            "answerability": self.answerability,
            "normal_stop_allowed": self.normal_stop_allowed,
            "abstain_required": self.abstain_required,
        }

    def _validate_payload(self) -> None:
        required = _require_ids(
            self.required_obligation_keys,
            "required_obligation_keys",
            allow_empty=False,
        )
        groups = {
            "verified": _require_ids(
                self.verified_obligation_keys, "verified_obligation_keys"
            ),
            "provisional": _require_ids(
                self.provisional_missing_obligation_keys,
                "provisional_missing_obligation_keys",
            ),
            "confirmed": _require_ids(
                self.confirmed_missing_obligation_keys,
                "confirmed_missing_obligation_keys",
            ),
            "contradicted": _require_ids(
                self.contradicted_obligation_keys,
                "contradicted_obligation_keys",
            ),
            "open": _require_ids(self.open_obligation_keys, "open_obligation_keys"),
        }
        required_set = set(required)
        if any(not set(values).issubset(required_set) for values in groups.values()):
            raise ValueError("progress_obligation_outside_required")
        terminal_sets = (
            set(groups["verified"]),
            set(groups["confirmed"]),
            set(groups["contradicted"]),
        )
        if any(left & right for index, left in enumerate(terminal_sets) for right in terminal_sets[index + 1 :]):
            raise ValueError("progress_terminal_state_overlap")
        if not set(groups["provisional"]).issubset(groups["open"]):
            raise ValueError("provisional_missing_must_be_open")
        if set(groups["open"]) & set().union(*terminal_sets):
            raise ValueError("open_terminal_state_overlap")
        if set().union(*terminal_sets, set(groups["open"])) != required_set:
            raise ValueError("progress_obligation_partition_mismatch")
        if type(self.slot_coverage_ratio) is not float or not math.isfinite(
            self.slot_coverage_ratio
        ):
            raise TypeError("invalid_slot_coverage_ratio")
        expected_ratio = len(groups["verified"]) / len(required)
        if self.slot_coverage_ratio != expected_ratio:
            raise ValueError("slot_coverage_ratio_mismatch")
        if self.answerability not in _ANSWERABILITY:
            raise ValueError("invalid_harness_answerability")
        if type(self.normal_stop_allowed) is not bool or type(self.abstain_required) is not bool:
            raise TypeError("invalid_harness_gate")
        if self.normal_stop_allowed and self.abstain_required:
            raise ValueError("conflicting_harness_terminal_gate")
        if self.normal_stop_allowed and (
            groups["open"] or groups["contradicted"] or groups["confirmed"]
        ):
            raise ValueError("normal_stop_progress_mismatch")
        if self.abstain_required and not groups["contradicted"]:
            raise ValueError("abstain_progress_mismatch")
        _require_hash(self.progress_sha256, "invalid_harness_progress_sha256")
        if self.progress_sha256 != _canonical_sha256(self._payload()):
            raise ValueError("harness_progress_hash_mismatch")

    def _validate(self) -> None:
        current = _authority_record(
            _PROGRESS_AUTHORITIES,
            self,
            code="harness_progress_runtime_authority_required",
        )
        attrs = (
            self.required_obligation_keys,
            self.verified_obligation_keys,
            self.provisional_missing_obligation_keys,
            self.confirmed_missing_obligation_keys,
            self.contradicted_obligation_keys,
            self.open_obligation_keys,
        )
        if any(issued is not actual for issued, actual in zip(current[2:], attrs)):
            raise ValueError("harness_progress_nested_identity_drift")
        self._validate_payload()
        if current[1] != _canonical_sha256(self.to_dict()):
            raise ValueError("harness_progress_runtime_authority_drift")

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "progress_sha256": self.progress_sha256}


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class HarnessState:
    belief: Belief
    progress: Progress
    state_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("harness_state_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        belief: Belief,
        progress: Progress,
        store: EvidenceStore,
        _token: object,
    ) -> HarnessState:
        if _token is not _STATE_TOKEN:
            raise ValueError("harness_state_factory_required")
        result = object.__new__(cls)
        object.__setattr__(result, "belief", belief)
        object.__setattr__(result, "progress", progress)
        object.__setattr__(
            result,
            "state_sha256",
            _canonical_sha256(
                {
                    "schema_version": "1.0",
                    "belief": belief.to_dict(),
                    "progress": progress.to_dict(),
                }
            ),
        )
        result._validate_payload()
        _register_authority(
            _STATE_AUTHORITIES,
            result,
            result.to_dict(),
            belief,
            progress,
            store,
        )
        result._validate(store=store)
        return result

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "belief": self.belief.to_dict(),
            "progress": self.progress.to_dict(),
        }

    def _validate_payload(self) -> None:
        if type(self.belief) is not Belief or type(self.progress) is not Progress:
            raise TypeError("invalid_harness_state_children")
        self.belief._validate()
        self.progress._validate()
        if tuple(entry.obligation_key for entry in self.belief.evidence_map) != (
            self.progress.required_obligation_keys
        ):
            raise ValueError("harness_belief_progress_obligation_mismatch")
        stages = {
            entry.obligation_key: entry.observation_stage
            for entry in self.belief.evidence_map
        }
        expected = {
            "verified": set(self.progress.verified_obligation_keys),
            "provisional_missing": set(
                self.progress.provisional_missing_obligation_keys
            ),
            "confirmed_missing": set(
                self.progress.confirmed_missing_obligation_keys
            ),
            "contradicted": set(self.progress.contradicted_obligation_keys),
        }
        for stage, keys in expected.items():
            if any(stages[key] != stage for key in keys):
                raise ValueError("harness_belief_progress_stage_mismatch")
        if set(self.progress.open_obligation_keys) != {
            key
            for key, stage in stages.items()
            if stage in {"unsearched", "candidate", "provisional_missing"}
        }:
            raise ValueError("harness_open_obligation_mismatch")
        _require_hash(self.state_sha256, "invalid_harness_state_sha256")
        if self.state_sha256 != _canonical_sha256(self._payload()):
            raise ValueError("harness_state_hash_mismatch")

    def _validate(self, *, store: EvidenceStore | None = None) -> None:
        current = _authority_record(
            _STATE_AUTHORITIES,
            self,
            code="harness_state_runtime_authority_required",
        )
        if current[2] is not self.belief or current[3] is not self.progress:
            raise ValueError("harness_state_nested_identity_drift")
        if store is not None and current[4] is not store:
            raise ValueError("harness_state_store_identity_mismatch")
        self._validate_payload()
        if store is not None:
            _validate_store_snapshot(store, self.belief.evidence_bundle_sha256)
        if current[1] != _canonical_sha256(self.to_dict()):
            raise ValueError("harness_state_runtime_authority_drift")

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "state_sha256": self.state_sha256}


def _make_belief(
    *,
    source_kind: str,
    request_fingerprint: str,
    binding_sha256: str,
    effective_plan_sha256: str,
    config_sha256: str,
    evidence_bundle_sha256: str,
    query_type: str,
    entities: tuple[PlanEntity, ...],
    constraints: tuple[PlanConstraint, ...],
    scope_state: str,
    scope_origin: str,
    scope_doc_ids: tuple[str, ...],
    evidence_map: tuple[EvidenceBeliefEntry, ...],
    source_receipt_sha256: str,
) -> Belief:
    return Belief._create(
        source_kind=source_kind,
        request_fingerprint=request_fingerprint,
        binding_sha256=binding_sha256,
        effective_plan_sha256=effective_plan_sha256,
        config_sha256=config_sha256,
        evidence_bundle_sha256=evidence_bundle_sha256,
        query_type=query_type,
        entities=entities,
        constraints=constraints,
        scope_state=scope_state,
        scope_origin=scope_origin,
        scope_doc_ids=scope_doc_ids,
        evidence_map=evidence_map,
        source_receipt_sha256=source_receipt_sha256,
        _token=_BELIEF_TOKEN,
    )


def _make_progress(
    *,
    evidence_map: tuple[EvidenceBeliefEntry, ...],
    slot_coverage_ratio: float,
    answerability: str,
    normal_stop_allowed: bool,
    abstain_required: bool,
) -> Progress:
    required = tuple(entry.obligation_key for entry in evidence_map)
    by_stage = {
        stage: tuple(
            entry.obligation_key
            for entry in evidence_map
            if entry.observation_stage == stage
        )
        for stage in _OBSERVATION_STAGES
    }
    return Progress._create(
        required_obligation_keys=required,
        verified_obligation_keys=by_stage["verified"],
        provisional_missing_obligation_keys=by_stage["provisional_missing"],
        confirmed_missing_obligation_keys=by_stage["confirmed_missing"],
        contradicted_obligation_keys=by_stage["contradicted"],
        open_obligation_keys=tuple(
            entry.obligation_key
            for entry in evidence_map
            if entry.observation_stage
            in {"unsearched", "candidate", "provisional_missing"}
        ),
        slot_coverage_ratio=slot_coverage_ratio,
        answerability=answerability,
        normal_stop_allowed=normal_stop_allowed,
        abstain_required=abstain_required,
        _token=_PROGRESS_TOKEN,
    )


def build_compare_harness_state(
    *,
    bound: BoundCompare,
    coverage: CompareCoverage,
    store: EvidenceStore,
) -> HarnessState:
    """Project one sealed compare coverage receipt without executing work."""

    if type(bound) is not BoundCompare:
        raise TypeError("bound_compare_required")
    if type(coverage) is not CompareCoverage:
        raise TypeError("compare_coverage_required")
    if type(store) is not EvidenceStore:
        raise TypeError("evidence_store_required")
    coverage._validate(bound, store)
    stage_map = {
        "unsearched": "unsearched",
        "candidate": "candidate",
        "verified": "verified",
        "missing": "provisional_missing",
        "contradicted": "contradicted",
    }
    evidence_map = tuple(
        EvidenceBeliefEntry._create(
            obligation_key=slot.slot.key,
            observation_stage=stage_map[slot.status],
            candidate_evidence_ids=slot.candidate_evidence_ids,
            verified_evidence_ids=slot.verified_evidence_ids,
            _token=_ENTRY_TOKEN,
        )
        for slot in coverage.slots
    )
    belief = _make_belief(
        source_kind="compare",
        request_fingerprint=bound.trace.request_fingerprint,
        binding_sha256=bound.binding_sha256,
        effective_plan_sha256=bound.trace.effective_plan_sha256,
        config_sha256=bound.plan.config_sha256,
        evidence_bundle_sha256=store.bundle_sha256,
        query_type=bound.plan.query_type,
        entities=bound.plan.entities,
        constraints=bound.plan.constraints,
        scope_state=bound.plan.scope_state,
        scope_origin=bound.plan.scope_origin,
        scope_doc_ids=bound.plan.resolved_doc_ids,
        evidence_map=evidence_map,
        source_receipt_sha256=coverage.coverage_sha256,
    )
    progress = _make_progress(
        evidence_map=evidence_map,
        slot_coverage_ratio=coverage.slot_coverage_ratio,
        answerability=coverage.answerability,
        normal_stop_allowed=coverage.normal_stop_allowed,
        abstain_required=coverage.abstain_required,
    )
    return HarnessState._create(
        belief=belief, progress=progress, store=store, _token=_STATE_TOKEN
    )


def build_fact_harness_state(
    *,
    bound: BoundFact,
    store: EvidenceStore,
) -> HarnessState:
    """Project a ready fact binding into one unsearched answer obligation."""

    validate_bound_fact(bound=bound, store=store)
    if bound.trace.status != "ready":
        raise ValueError("fact_binding_not_ready")
    evidence_map = (
        EvidenceBeliefEntry._create(
            obligation_key="$answer_support",
            observation_stage="unsearched",
            candidate_evidence_ids=(),
            verified_evidence_ids=(),
            _token=_ENTRY_TOKEN,
        ),
    )
    belief = _make_belief(
        source_kind="fact",
        request_fingerprint=bound.trace.request_fingerprint,
        binding_sha256=bound.binding_sha256,
        effective_plan_sha256=bound.trace.effective_plan_sha256,
        config_sha256=bound.trace.config_sha256,
        evidence_bundle_sha256=bound.trace.evidence_bundle_sha256,
        query_type=bound.plan.query_type,
        entities=bound.plan.entities,
        constraints=bound.plan.constraints,
        scope_state=bound.plan.scope_state,
        scope_origin=bound.plan.scope_origin,
        scope_doc_ids=bound.plan.resolved_doc_ids,
        evidence_map=evidence_map,
        source_receipt_sha256=bound.trace.trace_sha256,
    )
    progress = _make_progress(
        evidence_map=evidence_map,
        slot_coverage_ratio=0.0,
        answerability="in_progress",
        normal_stop_allowed=False,
        abstain_required=False,
    )
    return HarnessState._create(
        belief=belief,
        progress=progress,
        store=store,
        _token=_STATE_TOKEN,
    )


def build_followup_harness_state(
    *,
    bound: BoundFollowup,
    progress: PrimaryEvidenceProgress,
    outcome: FollowupRetrievalOutcome,
    store: EvidenceStore,
    registry: RuleRegistry,
    policy: FollowupEvidencePolicy,
) -> HarnessState:
    """Project one sealed follow-up outcome without executing retrieval again."""

    if type(progress) is not PrimaryEvidenceProgress:
        raise TypeError("primary_evidence_progress_required")
    validate_followup_retrieval_outcome(
        bound=bound,
        outcome=outcome,
        store=store,
        registry=registry,
        policy=policy,
    )
    if outcome.progress is not progress:
        raise ValueError("followup_outcome_progress_identity_mismatch")
    candidates: list[str] = []
    seen: set[str] = set()
    for attempt in (outcome.primary, outcome.fallback):
        if attempt is None:
            continue
        for candidate in attempt.result.candidates:
            if candidate.evidence_id not in seen:
                seen.add(candidate.evidence_id)
                candidates.append(candidate.evidence_id)
    verified_answer = progress.verified_answer_evidence_ids
    answer_stage = (
        "verified"
        if verified_answer
        else ("candidate" if candidates else "provisional_missing")
    )
    entries = [
        EvidenceBeliefEntry._create(
            obligation_key="$answer_support",
            observation_stage=answer_stage,
            candidate_evidence_ids=tuple(candidates),
            verified_evidence_ids=verified_answer,
            _token=_ENTRY_TOKEN,
        )
    ]
    verified_slots = dict(progress.verified_slot_evidence)
    for slot in bound.plan.required_slots:
        evidence_id = verified_slots.get(slot.key)
        entries.append(
            EvidenceBeliefEntry._create(
                obligation_key=slot.key,
                observation_stage=(
                    "verified" if evidence_id is not None else "provisional_missing"
                ),
                candidate_evidence_ids=(
                    () if evidence_id is None else (evidence_id,)
                ),
                verified_evidence_ids=(
                    () if evidence_id is None else (evidence_id,)
                ),
                _token=_ENTRY_TOKEN,
            )
        )
    evidence_map = tuple(entries)
    belief = _make_belief(
        source_kind="follow_up",
        request_fingerprint=bound.trace.request_fingerprint,
        binding_sha256=bound.binding_sha256,
        effective_plan_sha256=bound.trace.effective_plan_sha256,
        config_sha256=bound.trace.config_sha256,
        evidence_bundle_sha256=store.bundle_sha256,
        query_type=bound.plan.query_type,
        entities=bound.plan.entities,
        constraints=bound.plan.constraints,
        scope_state=bound.plan.scope_state,
        scope_origin=bound.plan.scope_origin,
        scope_doc_ids=bound.plan.resolved_doc_ids,
        evidence_map=evidence_map,
        source_receipt_sha256=_canonical_sha256(outcome.to_dict()),
    )
    verified_count = sum(
        entry.observation_stage == "verified" for entry in evidence_map
    )
    projected_progress = _make_progress(
        evidence_map=evidence_map,
        slot_coverage_ratio=verified_count / len(evidence_map),
        answerability="complete" if progress.sufficient else "in_progress",
        normal_stop_allowed=progress.sufficient,
        abstain_required=False,
    )
    return HarnessState._create(
        belief=belief,
        progress=projected_progress,
        store=store,
        _token=_STATE_TOKEN,
    )


def validate_harness_state(*, state: HarnessState, store: EvidenceStore) -> None:
    """Require the exact unchanged state issued for the exact EvidenceStore."""

    if type(state) is not HarnessState:
        raise TypeError("harness_state_required")
    if type(store) is not EvidenceStore:
        raise TypeError("evidence_store_required")
    state._validate(store=store)
    for entry in state.belief.evidence_map:
        for evidence_id in entry.candidate_evidence_ids:
            try:
                evidence = store.get(evidence_id)
            except KeyError as exc:
                raise ValueError("harness_state_unknown_evidence") from exc
            if state.belief.scope_state != "unfiltered" and (
                evidence.doc_id not in state.belief.scope_doc_ids
            ):
                if state.belief.source_kind != "follow_up":
                    raise ValueError("harness_state_evidence_scope_escape")


def replay_harness_state(
    raw: Mapping[str, Any],
    *,
    bound: BoundCompare | BoundFollowup | BoundFact,
    source_receipt: CompareCoverage | FollowupRetrievalOutcome | None,
    store: EvidenceStore,
    progress: PrimaryEvidenceProgress | None = None,
    registry: RuleRegistry | None = None,
    policy: FollowupEvidencePolicy | None = None,
) -> HarnessState:
    """Rebuild a state from sealed sources and compare exact canonical JSON."""

    if type(raw) is not dict:
        raise TypeError("harness_state_replay_mapping_required")
    _strict_json_value(raw, "harness_state_replay_json_required")
    if type(bound) is BoundFact and source_receipt is None:
        if progress is not None or registry is not None or policy is not None:
            raise ValueError("fact_harness_replay_arguments_mismatch")
        expected = build_fact_harness_state(bound=bound, store=store)
    elif type(bound) is BoundCompare and type(source_receipt) is CompareCoverage:
        if progress is not None or registry is not None or policy is not None:
            raise ValueError("compare_harness_replay_arguments_mismatch")
        expected = build_compare_harness_state(
            bound=bound,
            coverage=source_receipt,
            store=store,
        )
    elif type(bound) is BoundFollowup and type(source_receipt) is FollowupRetrievalOutcome:
        if (
            type(progress) is not PrimaryEvidenceProgress
            or type(registry) is not RuleRegistry
            or type(policy) is not FollowupEvidencePolicy
        ):
            raise TypeError("followup_harness_replay_arguments_required")
        expected = build_followup_harness_state(
            bound=bound,
            progress=progress,
            outcome=source_receipt,
            store=store,
            registry=registry,
            policy=policy,
        )
    else:
        raise TypeError("harness_state_source_mismatch")
    if _canonical_json(raw) != _canonical_json(expected.to_dict()):
        raise ValueError("harness_state_replay_payload_mismatch")
    return expected


__all__ = (
    "Belief",
    "EvidenceBeliefEntry",
    "HarnessState",
    "Progress",
    "build_compare_harness_state",
    "build_fact_harness_state",
    "build_followup_harness_state",
    "replay_harness_state",
    "validate_harness_state",
)
