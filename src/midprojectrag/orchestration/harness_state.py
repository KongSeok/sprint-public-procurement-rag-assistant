"""Pure, authority-bound projection of orchestration evidence state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import json
import math
import re
from threading import RLock
from types import FunctionType
from typing import Any
from weakref import ReferenceType, ref

from midprojectrag.evidence import EvidenceStore, validate_evidence_store_snapshot

from .compare_coverage import CompareCoverage
from .compare_slots import BoundCompare
from .contracts import PlanConstraint, PlanEntity, RuleRegistry
from .fact_binding import BoundFact, validate_bound_fact
from . import followup_retrieval as _FOLLOWUP_RETRIEVAL_MODULE
from .followup_binding import BoundFollowup
from .followup_retrieval import (
    FollowupEvidencePolicy,
    FollowupRetrievalOutcome,
    PrimaryEvidenceProgress,
    validate_followup_retrieval_outcome,
)


def _e1_callable_pin(function: FunctionType) -> tuple[Any, ...]:
    kwdefaults = object.__getattribute__(function, "__kwdefaults__")
    closure = object.__getattribute__(function, "__closure__")
    return (
        function,
        object.__getattribute__(function, "__name__"),
        object.__getattribute__(function, "__code__"),
        object.__getattribute__(function, "__defaults__"),
        kwdefaults,
        None if kwdefaults is None else tuple(sorted(dict.items(kwdefaults))),
        object.__getattribute__(function, "__globals__"),
        closure,
        (
            None
            if closure is None
            else tuple(cell.cell_contents for cell in closure)
        ),
    )


def _e1_class_pin(owner: type) -> tuple[Any, ...]:
    namespace = type.__getattribute__(owner, "__dict__")
    names = tuple(sorted(namespace))
    members = []
    for name in names:
        member = namespace[name]
        callables = []
        if type(member) is FunctionType:
            callables.append(("function", _e1_callable_pin(member)))
        elif type(member) in {classmethod, staticmethod}:
            callables.append(
                (
                    "wrapped",
                    _e1_callable_pin(object.__getattribute__(member, "__func__")),
                )
            )
        elif type(member) is property:
            for role in ("fget", "fset", "fdel"):
                function = object.__getattribute__(member, role)
                if function is not None:
                    callables.append((role, _e1_callable_pin(function)))
        members.append((name, member, type(member), tuple(callables)))
    return names, tuple(members)


def _e1_module_pin(module: object) -> tuple[Any, ...]:
    namespace = object.__getattribute__(module, "__dict__")
    names = tuple(sorted(name for name in namespace if not name.startswith("__")))
    members = []
    for name in names:
        value = dict.__getitem__(namespace, name)
        members.append(
            (
                name,
                value,
                type(value),
                _e1_callable_pin(value) if type(value) is FunctionType else None,
                _e1_class_pin(value) if type(value) is type else None,
            )
        )
    return names, tuple(members)


_E1_FOLLOWUP_VALIDATOR_MODULE_PIN = _e1_module_pin(_FOLLOWUP_RETRIEVAL_MODULE)
del _e1_callable_pin
del _e1_class_pin
del _e1_module_pin


def _validate_callable_pin(function: object, pin: tuple[Any, ...]) -> None:
    (
        issued,
        name,
        code,
        defaults,
        kwdefaults,
        kwdefault_items,
        globals_state,
        closure,
        closure_values,
    ) = pin
    current_kwdefaults = object.__getattribute__(issued, "__kwdefaults__")
    current_closure = object.__getattribute__(issued, "__closure__")
    if (
        function is not issued
        or object.__getattribute__(issued, "__name__") != name
        or object.__getattribute__(issued, "__code__") is not code
        or object.__getattribute__(issued, "__defaults__") is not defaults
        or current_kwdefaults is not kwdefaults
        or (
            None
            if current_kwdefaults is None
            else tuple(sorted(dict.items(current_kwdefaults)))
        )
        != kwdefault_items
        or object.__getattribute__(issued, "__globals__") is not globals_state
        or current_closure is not closure
        or (
            None
            if current_closure is None
            else tuple(cell.cell_contents for cell in current_closure)
        )
        != closure_values
    ):
        raise ValueError("harness_state_projection_dependency_drift")


def _validate_class_pin(
    owner: object,
    pin: tuple[Any, ...],
    callable_validator: Any,
) -> None:
    names, members = pin
    namespace = type.__getattribute__(owner, "__dict__")
    if tuple(sorted(namespace)) != names:
        raise ValueError("harness_state_projection_dependency_drift")
    for name, issued, issued_type, callables in members:
        current = namespace.get(name)
        if current is not issued or type(current) is not issued_type:
            raise ValueError("harness_state_projection_dependency_drift")
        for role, callable_pin in callables:
            if role == "function":
                function = current
            elif role == "wrapped":
                function = object.__getattribute__(current, "__func__")
            else:
                function = object.__getattribute__(current, role)
            callable_validator(function, callable_pin)


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
_SOURCE_OWNER_TOKEN = object()
_ENTRY_AUTHORITIES: dict[int, tuple[Any, ...]] = {}
_BELIEF_AUTHORITIES: dict[int, tuple[Any, ...]] = {}
_PROGRESS_AUTHORITIES: dict[int, tuple[Any, ...]] = {}
_STATE_AUTHORITIES: dict[int, tuple[Any, ...]] = {}


class _ControllerSourceOwnerAuthority:
    """Private exact source graph retained for controller execution."""

    __slots__ = (
        "source_kind",
        "source",
        "source_receipt",
        "source_progress",
        "registry",
        "policy",
        "projection_kind",
        "__weakref__",
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("controller_source_owner_factory_required")

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("controller_source_owner_immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("controller_source_owner_immutable")

    def __repr__(self) -> str:
        return "_ControllerSourceOwnerAuthority(<redacted>)"

    @classmethod
    def _create(
        cls,
        *,
        source_kind: str,
        source: BoundFact | BoundCompare | BoundFollowup,
        source_receipt: Any,
        source_progress: PrimaryEvidenceProgress | None,
        registry: RuleRegistry | None,
        policy: FollowupEvidencePolicy | None,
        projection_kind: str,
        _token: object,
    ) -> _ControllerSourceOwnerAuthority:
        if cls is not _ControllerSourceOwnerAuthority or _token is not _SOURCE_OWNER_TOKEN:
            raise ValueError("controller_source_owner_factory_required")
        result = object.__new__(cls)
        for name, value in (
            ("source_kind", source_kind),
            ("source", source),
            ("source_receipt", source_receipt),
            ("source_progress", source_progress),
            ("registry", registry),
            ("policy", policy),
            ("projection_kind", projection_kind),
        ):
            object.__setattr__(result, name, value)
        return result


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


def _validate_controller_source_owner_impl(
    owner: _ControllerSourceOwnerAuthority,
    *,
    state: HarnessState,
    store: EvidenceStore,
) -> None:
    if type(owner) is not _ControllerSourceOwnerAuthority:
        raise TypeError("controller_source_owner_authority_required")
    if type(store) is not EvidenceStore:
        raise TypeError("evidence_store_required")
    belief = state.belief
    source = owner.source
    if owner.source_kind == "fact":
        if (
            type(source) is not BoundFact
            or owner.source_receipt is not source.trace
            or owner.source_progress is not None
            or owner.registry is not None
            or owner.policy is not None
            or owner.projection_kind != "fact_initial"
        ):
            raise ValueError("invalid_fact_controller_source_owner")
        validate_bound_fact(bound=source, store=store)
        source_receipt_sha256 = source.trace.trace_sha256
        source_config_sha256 = source.trace.config_sha256
    elif owner.source_kind == "compare":
        if (
            type(source) is not BoundCompare
            or type(owner.source_receipt) is not CompareCoverage
            or owner.source_progress is not None
            or owner.registry is not None
            or owner.policy is not None
            or owner.projection_kind != "compare_coverage"
        ):
            raise ValueError("invalid_compare_controller_source_owner")
        owner.source_receipt._validate(source, store)
        source_receipt_sha256 = owner.source_receipt.coverage_sha256
        source_config_sha256 = source.plan.config_sha256
    elif owner.source_kind == "follow_up":
        if (
            type(source) is not BoundFollowup
            or type(owner.source_receipt) is not FollowupRetrievalOutcome
            or owner.source_progress is not owner.source_receipt.progress
            or type(owner.registry) is not RuleRegistry
            or type(owner.policy) is not FollowupEvidencePolicy
            or owner.projection_kind not in {"followup_legacy", "followup_e1"}
        ):
            raise ValueError("invalid_followup_controller_source_owner")
        validate_followup_retrieval_outcome(
            bound=source,
            outcome=owner.source_receipt,
            store=store,
            registry=owner.registry,
            policy=owner.policy,
        )
        source_receipt_sha256 = _canonical_sha256(owner.source_receipt.to_dict())
        source_config_sha256 = source.trace.config_sha256
    else:
        raise ValueError("invalid_controller_source_owner_kind")

    plan = source.plan
    if (
        belief.source_kind != owner.source_kind
        or belief.binding_sha256 != source.binding_sha256
        or belief.source_receipt_sha256 != source_receipt_sha256
        or belief.request_fingerprint != source.trace.request_fingerprint
        or belief.effective_plan_sha256 != source.trace.effective_plan_sha256
        or belief.config_sha256 != source_config_sha256
        or belief.evidence_bundle_sha256 != store.bundle_sha256
        or belief.query_type != plan.query_type
        or belief.entities != plan.entities
        or belief.constraints != plan.constraints
        or belief.scope_state != plan.scope_state
        or belief.scope_origin != plan.scope_origin
        or belief.scope_doc_ids != plan.resolved_doc_ids
    ):
        raise ValueError("controller_source_owner_state_mismatch")


def _close_controller_source_owner_validator(
    implementation: FunctionType,
    fact_validator: FunctionType,
    followup_validator: FunctionType,
    compare_validator: FunctionType,
) -> FunctionType:
    global_pins = (
        ("_ControllerSourceOwnerAuthority", _ControllerSourceOwnerAuthority),
        ("EvidenceStore", EvidenceStore),
        ("BoundFact", BoundFact),
        ("BoundCompare", BoundCompare),
        ("BoundFollowup", BoundFollowup),
        ("CompareCoverage", CompareCoverage),
        ("FollowupRetrievalOutcome", FollowupRetrievalOutcome),
        ("PrimaryEvidenceProgress", PrimaryEvidenceProgress),
        ("RuleRegistry", RuleRegistry),
        ("FollowupEvidencePolicy", FollowupEvidencePolicy),
        ("validate_bound_fact", fact_validator),
        ("validate_followup_retrieval_outcome", followup_validator),
        ("_canonical_sha256", _canonical_sha256),
    )
    callable_pins = tuple(
        (
            function,
            object.__getattribute__(function, "__code__"),
            object.__getattribute__(function, "__defaults__"),
            object.__getattribute__(function, "__kwdefaults__"),
        )
        for function in (
            implementation,
            fact_validator,
            followup_validator,
            compare_validator,
            _canonical_sha256,
        )
    )
    module = globals()

    def validate_controller_source_owner(
        owner: _ControllerSourceOwnerAuthority,
        *,
        state: HarnessState,
        store: EvidenceStore,
    ) -> None:
        if module.get("_validate_controller_source_owner_impl") is not implementation:
            raise ValueError("controller_source_owner_dependency_drift")
        for name, issued in global_pins:
            if module.get(name) is not issued:
                raise ValueError("controller_source_owner_dependency_drift")
        if type.__getattribute__(CompareCoverage, "__dict__").get(
            "_validate"
        ) is not compare_validator:
            raise ValueError("controller_source_owner_dependency_drift")
        for function, code, defaults, kwdefaults in callable_pins:
            if (
                object.__getattribute__(function, "__code__") is not code
                or object.__getattribute__(function, "__defaults__") is not defaults
                or object.__getattribute__(function, "__kwdefaults__")
                is not kwdefaults
            ):
                raise ValueError("controller_source_owner_dependency_drift")
        implementation(owner, state=state, store=store)

    return validate_controller_source_owner


_validate_controller_source_owner = _close_controller_source_owner_validator(
    _validate_controller_source_owner_impl,
    validate_bound_fact,
    validate_followup_retrieval_outcome,
    CompareCoverage._validate,
)
del _close_controller_source_owner_validator


def _build_controller_source_owner_accessors(owner_validator: FunctionType):
    authority_lock = RLock()
    authorities: dict[int, tuple[Any, ...]] = {}
    authority_shadow: dict[int, tuple[Any, ...]] = {}
    owner_origins: dict[int, tuple[Any, ...]] = {}
    owner_origin_shadow: dict[int, tuple[Any, ...]] = {}
    module = globals()
    validator_pin = (
        object.__getattribute__(owner_validator, "__code__"),
        object.__getattribute__(owner_validator, "__defaults__"),
        object.__getattribute__(owner_validator, "__kwdefaults__"),
        object.__getattribute__(owner_validator, "__globals__"),
        object.__getattribute__(owner_validator, "__closure__"),
        tuple(
            cell.cell_contents
            for cell in (object.__getattribute__(owner_validator, "__closure__") or ())
        ),
    )

    def validate_dependencies() -> None:
        if module.get("_validate_controller_source_owner") is not owner_validator:
            raise ValueError("controller_source_owner_dependency_drift")
        closure = object.__getattribute__(owner_validator, "__closure__")
        if (
            object.__getattribute__(owner_validator, "__code__") is not validator_pin[0]
            or object.__getattribute__(owner_validator, "__defaults__")
            is not validator_pin[1]
            or object.__getattribute__(owner_validator, "__kwdefaults__")
            is not validator_pin[2]
            or object.__getattribute__(owner_validator, "__globals__")
            is not validator_pin[3]
            or closure is not validator_pin[4]
            or len(closure or ()) != len(validator_pin[5])
            or any(
                cell.cell_contents is not issued
                for cell, issued in zip(closure or (), validator_pin[5])
            )
        ):
            raise ValueError("controller_source_owner_dependency_drift")

    def drop(identity: int, dead: ReferenceType[Any]) -> None:
        with authority_lock:
            current = authorities.get(identity)
            if current is not None and current[0] is dead:
                authorities.pop(identity, None)
                authority_shadow.pop(identity, None)

    def drop_owner(identity: int, dead: ReferenceType[Any]) -> None:
        with authority_lock:
            current = owner_origins.get(identity)
            if current is not None and current[0] is dead:
                owner_origins.pop(identity, None)
                owner_origin_shadow.pop(identity, None)

    def require_owner_origin(
        *,
        owner: _ControllerSourceOwnerAuthority,
        state: HarnessState,
    ) -> tuple[Any, ...] | None:
        origin = owner_origins.get(id(owner))
        shadow = owner_origin_shadow.get(id(owner))
        if (origin is None) != (shadow is None) or (
            origin is not None and origin is not shadow
        ):
            raise ValueError("controller_source_owner_origin_authority_drift")
        if origin is None:
            return None
        if origin[0]() is not owner:
            raise ValueError("controller_source_owner_origin_authority_drift")
        if origin[1]() is not state:
            raise ValueError("controller_source_owner_root_identity_mismatch")
        return origin

    def register(
        *,
        state: HarnessState,
        owner: _ControllerSourceOwnerAuthority,
        store: EvidenceStore,
    ) -> tuple[Any, ...]:
        validate_dependencies()
        owner_validator(owner, state=state, store=store)
        identity = id(state)
        with authority_lock:
            origin = require_owner_origin(owner=owner, state=state)
            current = authorities.get(identity)
            shadow = authority_shadow.get(identity)
            if (current is None) != (shadow is None) or (
                current is not None and current is not shadow
            ):
                raise ValueError("controller_source_owner_authority_drift")
            if current is not None:
                if (
                    current[0]() is not state
                    or current[1] is not owner
                    or current[2] is not store
                ):
                    raise ValueError("controller_source_owner_already_registered")
                if origin is None or origin[2] != state.state_sha256:
                    raise ValueError("controller_source_owner_origin_authority_drift")
                return current
            state_weak = ref(
                state,
                lambda dead, key=identity: drop(key, dead),
            )
            record = (
                state_weak,
                owner,
                store,
                owner.source_kind,
                owner.source,
                owner.source_receipt,
                owner.source_progress,
                owner.registry,
                owner.policy,
                owner.projection_kind,
                state.state_sha256,
            )
            authorities[identity] = record
            authority_shadow[identity] = record
            if origin is not None:
                raise ValueError("controller_source_owner_origin_authority_drift")
            owner_weak = ref(
                owner,
                lambda dead, key=id(owner): drop_owner(key, dead),
            )
            origin_record = (owner_weak, state_weak, state.state_sha256)
            owner_origins[id(owner)] = origin_record
            owner_origin_shadow[id(owner)] = origin_record
            return record

    def require(
        *,
        state: HarnessState,
        store: EvidenceStore,
    ) -> tuple[Any, ...]:
        identity = id(state)
        with authority_lock:
            current = authorities.get(identity)
            shadow = authority_shadow.get(identity)
            if (
                current is None
                or current is not shadow
                or current[0]() is not state
                or current[2] is not store
            ):
                raise ValueError("controller_source_owner_runtime_authority_required")
            owner = current[1]
            origin = require_owner_origin(owner=owner, state=state)
            if (
                owner.source_kind != current[3]
                or owner.source is not current[4]
                or owner.source_receipt is not current[5]
                or owner.source_progress is not current[6]
                or owner.registry is not current[7]
                or owner.policy is not current[8]
                or owner.projection_kind != current[9]
                or state.state_sha256 != current[10]
                or origin is None
                or origin[2] != state.state_sha256
            ):
                raise ValueError("controller_source_owner_nested_identity_drift")
        validate_dependencies()
        owner_validator(owner, state=state, store=store)
        return current

    return register, require


(
    _register_controller_source_owner_authority,
    _read_controller_source_owner_authority,
) = _build_controller_source_owner_accessors(
    _validate_controller_source_owner,
)
del _build_controller_source_owner_accessors


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
            None,
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


def _build_controller_owned_state_creator(
    *,
    state_cls: type,
    store_cls: type,
    owner_cls: type,
    state_token: object,
    owner_token: object,
    state_authorities: dict[int, tuple[Any, ...]],
    authority_reader: FunctionType,
    owner_register: FunctionType,
    owner_reader: FunctionType,
):
    """Create and source-seal one state through a closure-held registrar."""

    state_create = type.__getattribute__(state_cls, "__dict__")["_create"].__func__
    state_validate = type.__getattribute__(state_cls, "__dict__")["_validate"]
    owner_create = type.__getattribute__(owner_cls, "__dict__")["_create"].__func__
    module = globals()
    global_pins = (
        ("HarnessState", state_cls),
        ("EvidenceStore", store_cls),
        ("_ControllerSourceOwnerAuthority", owner_cls),
        ("_STATE_TOKEN", state_token),
        ("_SOURCE_OWNER_TOKEN", owner_token),
        ("_STATE_AUTHORITIES", state_authorities),
        ("_authority_record", authority_reader),
    )
    callable_pins = []
    for function in (
        state_create,
        state_validate,
        owner_create,
        authority_reader,
        owner_register,
        owner_reader,
    ):
        closure = object.__getattribute__(function, "__closure__")
        callable_pins.append(
            (
                function,
                object.__getattribute__(function, "__code__"),
                object.__getattribute__(function, "__defaults__"),
                object.__getattribute__(function, "__kwdefaults__"),
                object.__getattribute__(function, "__globals__"),
                closure,
                tuple(cell.cell_contents for cell in (closure or ())),
            )
        )
    callable_pins = tuple(callable_pins)

    def validate_dependencies() -> None:
        for name, issued in global_pins:
            if module.get(name) is not issued:
                raise ValueError("controller_source_owner_dependency_drift")
        state_namespace = type.__getattribute__(state_cls, "__dict__")
        create_descriptor = state_namespace.get("_create")
        owner_create_descriptor = type.__getattribute__(owner_cls, "__dict__").get(
            "_create"
        )
        if (
            type(create_descriptor) is not classmethod
            or create_descriptor.__func__ is not state_create
            or state_namespace.get("_validate") is not state_validate
            or type(owner_create_descriptor) is not classmethod
            or owner_create_descriptor.__func__ is not owner_create
        ):
            raise ValueError("controller_source_owner_dependency_drift")
        for (
            function,
            code,
            defaults,
            kwdefaults,
            function_globals,
            closure,
            closure_contents,
        ) in callable_pins:
            current_closure = object.__getattribute__(function, "__closure__")
            if (
                object.__getattribute__(function, "__code__") is not code
                or object.__getattribute__(function, "__defaults__") is not defaults
                or object.__getattribute__(function, "__kwdefaults__")
                is not kwdefaults
                or object.__getattribute__(function, "__globals__")
                is not function_globals
                or current_closure is not closure
                or len(current_closure or ()) != len(closure_contents)
                or any(
                    cell.cell_contents is not issued
                    for cell, issued in zip(
                        current_closure or (),
                        closure_contents,
                    )
                )
            ):
                raise ValueError("controller_source_owner_dependency_drift")

    def create_controller_owned_state(
        *,
        belief: Belief,
        progress: Progress,
        store: EvidenceStore,
        source_kind: str,
        source: BoundFact | BoundCompare | BoundFollowup,
        source_receipt: Any,
        source_progress: PrimaryEvidenceProgress | None,
        registry: RuleRegistry | None,
        policy: FollowupEvidencePolicy | None,
        projection_kind: str,
    ) -> HarnessState:
        validate_dependencies()
        if type(store) is not store_cls:
            raise TypeError("evidence_store_required")
        state = state_create(
            state_cls,
            belief=belief,
            progress=progress,
            store=store,
            _token=state_token,
        )
        owner = owner_create(
            owner_cls,
            source_kind=source_kind,
            source=source,
            source_receipt=source_receipt,
            source_progress=source_progress,
            registry=registry,
            policy=policy,
            projection_kind=projection_kind,
            _token=owner_token,
        )
        source_record = owner_register(state=state, owner=owner, store=store)
        current = authority_reader(
            state_authorities,
            state,
            code="harness_state_runtime_authority_required",
        )
        if current[5] is not None:
            raise ValueError("harness_state_source_owner_already_attached")
        dict.__setitem__(
            state_authorities,
            id(state),
            (*current[:5], source_record),
        )
        state_validate(state, store=store)
        sealed = authority_reader(
            state_authorities,
            state,
            code="harness_state_runtime_authority_required",
        )
        if sealed[5] is not owner_reader(state=state, store=store):
            raise ValueError("harness_state_source_owner_identity_drift")
        return state

    return create_controller_owned_state


_create_controller_owned_harness_state = _build_controller_owned_state_creator(
    state_cls=HarnessState,
    store_cls=EvidenceStore,
    owner_cls=_ControllerSourceOwnerAuthority,
    state_token=_STATE_TOKEN,
    owner_token=_SOURCE_OWNER_TOKEN,
    state_authorities=_STATE_AUTHORITIES,
    authority_reader=_authority_record,
    owner_register=_register_controller_source_owner_authority,
    owner_reader=_read_controller_source_owner_authority,
)
del _build_controller_owned_state_creator


def _build_harness_state_source_owner_reader(
    *,
    state_cls: type,
    store_cls: type,
    owner_cls: type,
    state_authorities: dict[int, tuple[Any, ...]],
    state_validator: FunctionType,
    authority_reader: FunctionType,
    owner_register: FunctionType,
    owner_reader: FunctionType,
):
    """Close the exact-root reader over the source authority capabilities."""

    module = globals()
    global_pins = (
        ("HarnessState", state_cls),
        ("EvidenceStore", store_cls),
        ("_ControllerSourceOwnerAuthority", owner_cls),
        ("_STATE_AUTHORITIES", state_authorities),
        ("_authority_record", authority_reader),
    )

    def callable_pin(function: FunctionType) -> tuple[Any, ...]:
        closure = object.__getattribute__(function, "__closure__")
        return (
            function,
            object.__getattribute__(function, "__code__"),
            object.__getattribute__(function, "__defaults__"),
            object.__getattribute__(function, "__kwdefaults__"),
            object.__getattribute__(function, "__globals__"),
            closure,
            tuple(cell.cell_contents for cell in (closure or ())),
        )

    callable_pins = tuple(
        callable_pin(function)
        for function in (
            state_validator,
            authority_reader,
            owner_register,
            owner_reader,
        )
    )

    def validate_dependencies() -> None:
        for name, issued in global_pins:
            if module.get(name) is not issued:
                raise ValueError("controller_source_owner_dependency_drift")
        if (
            module.get("_register_controller_source_owner_authority")
            not in {None, owner_register}
            or module.get("_read_controller_source_owner_authority")
            not in {None, owner_reader}
        ):
            raise ValueError("controller_source_owner_dependency_drift")
        state_namespace = type.__getattribute__(state_cls, "__dict__")
        if state_namespace.get("_validate") is not state_validator:
            raise ValueError("controller_source_owner_dependency_drift")
        for (
            function,
            code,
            defaults,
            kwdefaults,
            function_globals,
            closure,
            closure_contents,
        ) in callable_pins:
            current_closure = object.__getattribute__(function, "__closure__")
            if (
                object.__getattribute__(function, "__code__") is not code
                or object.__getattribute__(function, "__defaults__") is not defaults
                or object.__getattribute__(function, "__kwdefaults__")
                is not kwdefaults
                or object.__getattribute__(function, "__globals__")
                is not function_globals
                or current_closure is not closure
                or len(current_closure or ()) != len(closure_contents)
                or any(
                    cell.cell_contents is not issued
                    for cell, issued in zip(
                        current_closure or (),
                        closure_contents,
                    )
                )
            ):
                raise ValueError("controller_source_owner_dependency_drift")

    def require_harness_state_source_owner(
        *,
        state: HarnessState,
        store: EvidenceStore,
    ) -> _ControllerSourceOwnerAuthority:
        """Return only the owner sealed onto this exact state root."""

        validate_dependencies()
        if type(state) is not state_cls:
            raise TypeError("harness_state_required")
        if type(store) is not store_cls:
            raise TypeError("evidence_store_required")
        state_validator(state, store=store)
        current = authority_reader(
            state_authorities,
            state,
            code="harness_state_runtime_authority_required",
        )
        source_record = owner_reader(state=state, store=store)
        if current[5] is not source_record:
            raise ValueError("harness_state_source_owner_identity_drift")
        owner = source_record[1]
        if type(owner) is not owner_cls:
            raise TypeError("controller_source_owner_authority_required")
        return owner

    return require_harness_state_source_owner


_require_harness_state_source_owner = _build_harness_state_source_owner_reader(
    state_cls=HarnessState,
    store_cls=EvidenceStore,
    owner_cls=_ControllerSourceOwnerAuthority,
    state_authorities=_STATE_AUTHORITIES,
    state_validator=HarnessState._validate,
    authority_reader=_authority_record,
    owner_register=_register_controller_source_owner_authority,
    owner_reader=_read_controller_source_owner_authority,
)
del _build_harness_state_source_owner_reader
del _register_controller_source_owner_authority
del _read_controller_source_owner_authority


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
    return _create_controller_owned_harness_state(
        belief=belief,
        progress=progress,
        store=store,
        source_kind="compare",
        source=bound,
        source_receipt=coverage,
        source_progress=None,
        registry=None,
        policy=None,
        projection_kind="compare_coverage",
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
    return _create_controller_owned_harness_state(
        belief=belief,
        progress=progress,
        store=store,
        source_kind="fact",
        source=bound,
        source_receipt=bound.trace,
        source_progress=None,
        registry=None,
        policy=None,
        projection_kind="fact_initial",
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
    return _create_controller_owned_harness_state(
        belief=belief,
        progress=projected_progress,
        store=store,
        source_kind="follow_up",
        source=bound,
        source_receipt=outcome,
        source_progress=progress,
        registry=registry,
        policy=policy,
        projection_kind="followup_legacy",
    )


def _build_e1_followup_harness_state_impl(
    *,
    bound: BoundFollowup,
    outcome: FollowupRetrievalOutcome,
    store: EvidenceStore,
    registry: RuleRegistry,
    policy: FollowupEvidencePolicy,
) -> HarnessState:
    """Project finalized follow-up candidates into a safe E1 initial state.

    EH2.3 progress is compatibility lineage, not terminal semantic authority.
    This boundary therefore ignores its verified/sufficient claims, performs no
    retrieval, and leaves every projected obligation open for E1 verification.
    """

    if bound.plan.metadata_predicates:
        raise ValueError("followup_metadata_scope_receipt_required")

    candidates: list[str] = []
    seen: set[str] = set()
    for attempt in (outcome.primary, outcome.fallback):
        if attempt is None:
            continue
        for candidate in attempt.result.candidates:
            if candidate.evidence_id not in seen:
                seen.add(candidate.evidence_id)
                candidates.append(candidate.evidence_id)
    ordered_candidates = tuple(candidates)

    entries = [
        EvidenceBeliefEntry._create(
            obligation_key="$answer_support",
            observation_stage=(
                "candidate" if ordered_candidates else "provisional_missing"
            ),
            candidate_evidence_ids=ordered_candidates,
            verified_evidence_ids=(),
            _token=_ENTRY_TOKEN,
        )
    ]
    for slot in bound.plan.required_slots:
        slot_candidates = tuple(
            evidence_id
            for evidence_id in ordered_candidates
            if store.get(evidence_id).doc_id == slot.doc_id
        )
        entries.append(
            EvidenceBeliefEntry._create(
                obligation_key=slot.key,
                observation_stage=(
                    "candidate" if slot_candidates else "provisional_missing"
                ),
                candidate_evidence_ids=slot_candidates,
                verified_evidence_ids=(),
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
    projected_progress = _make_progress(
        evidence_map=evidence_map,
        slot_coverage_ratio=0.0,
        answerability="in_progress",
        normal_stop_allowed=False,
        abstain_required=False,
    )
    return _create_controller_owned_harness_state(
        belief=belief,
        progress=projected_progress,
        store=store,
        source_kind="follow_up",
        source=bound,
        source_receipt=outcome,
        source_progress=outcome.progress,
        registry=registry,
        policy=policy,
        projection_kind="followup_e1",
    )


def _close_e1_followup_projection_boundary(
    implementation: FunctionType,
    followup_module: object,
    module_pin: tuple[Any, ...],
    module_pin_mirror: tuple[Any, ...],
    callable_validator: FunctionType,
    class_validator: FunctionType,
) -> FunctionType:
    """Capture the issued validation root outside mutable module aliases."""

    harness_globals = globals()

    def simple_pin(function: FunctionType) -> tuple[Any, ...]:
        return (
            function,
            object.__getattribute__(function, "__code__"),
            object.__getattribute__(function, "__defaults__"),
            object.__getattribute__(function, "__kwdefaults__"),
            object.__getattribute__(function, "__globals__"),
            object.__getattribute__(function, "__closure__"),
        )

    implementation_pin = simple_pin(implementation)
    callable_validator_pin = simple_pin(callable_validator)
    class_validator_pin = simple_pin(class_validator)

    def build_e1_followup_harness_state(
        *,
        bound: BoundFollowup,
        outcome: FollowupRetrievalOutcome,
        store: EvidenceStore,
        registry: RuleRegistry,
        policy: FollowupEvidencePolicy,
    ) -> HarnessState:
        """Validate sealed follow-up lineage and issue a safe E1 state."""

        if module_pin_mirror is not module_pin:
            raise ValueError("harness_state_projection_dependency_drift")
        for current, pin in (
            (implementation, implementation_pin),
            (callable_validator, callable_validator_pin),
            (class_validator, class_validator_pin),
        ):
            issued, code, defaults, kwdefaults, globals_state, closure = pin
            if (
                current is not issued
                or object.__getattribute__(current, "__code__") is not code
                or object.__getattribute__(current, "__defaults__") is not defaults
                or object.__getattribute__(current, "__kwdefaults__") is not kwdefaults
                or object.__getattribute__(current, "__globals__") is not globals_state
                or object.__getattribute__(current, "__closure__") is not closure
            ):
                raise ValueError("harness_state_projection_dependency_drift")
        if harness_globals.get("_validate_callable_pin") is not callable_validator:
            raise ValueError("harness_state_projection_dependency_drift")
        if harness_globals.get("_validate_class_pin") is not class_validator:
            raise ValueError("harness_state_projection_dependency_drift")

        names, members = module_pin
        namespace = object.__getattribute__(followup_module, "__dict__")
        if tuple(
            sorted(name for name in namespace if not name.startswith("__"))
        ) != names:
            raise ValueError("harness_state_projection_dependency_drift")
        outcome_validator = None
        for name, issued, issued_type, callable_pin, class_pin in members:
            current = namespace.get(name)
            if current is not issued or type(current) is not issued_type:
                raise ValueError("harness_state_projection_dependency_drift")
            if callable_pin is not None:
                callable_validator(current, callable_pin)
            if class_pin is not None:
                class_validator(current, class_pin, callable_validator)
            if name == "validate_followup_retrieval_outcome":
                outcome_validator = issued

        if (
            type(outcome_validator) is not FunctionType
            or harness_globals.get("validate_followup_retrieval_outcome")
            is not outcome_validator
        ):
            raise ValueError("harness_state_projection_dependency_drift")

        outcome_validator(
            bound=bound,
            outcome=outcome,
            store=store,
            registry=registry,
            policy=policy,
        )
        return implementation(
            bound=bound,
            outcome=outcome,
            store=store,
            registry=registry,
            policy=policy,
        )

    return build_e1_followup_harness_state


build_e1_followup_harness_state = _close_e1_followup_projection_boundary(
    _build_e1_followup_harness_state_impl,
    _FOLLOWUP_RETRIEVAL_MODULE,
    _E1_FOLLOWUP_VALIDATOR_MODULE_PIN,
    _E1_FOLLOWUP_VALIDATOR_MODULE_PIN,
    _validate_callable_pin,
    _validate_class_pin,
)
del _close_e1_followup_projection_boundary
del _E1_FOLLOWUP_VALIDATOR_MODULE_PIN
del _build_e1_followup_harness_state_impl


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
    "build_e1_followup_harness_state",
    "build_fact_harness_state",
    "build_followup_harness_state",
    "replay_harness_state",
    "validate_harness_state",
)
