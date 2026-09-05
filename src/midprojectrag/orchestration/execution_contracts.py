"""Immutable execution config and exact live runtime authority for EH2.6.

This leaf binds capabilities only.  It never derives a query and never calls a
retriever, verifier, reranker, clock, model, or provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
from sys import _getframe as _GET_FRAME
from threading import Lock
from time import monotonic_ns as _PRODUCTION_CLOCK
from types import (
    BuiltinFunctionType,
    CodeType,
    FunctionType,
    GetSetDescriptorType,
    MappingProxyType,
    MemberDescriptorType,
)
from typing import Any, Mapping
from weakref import ReferenceType, ref

import midprojectrag.evidence as _EVIDENCE_RUNTIME_MODULE
from midprojectrag.evidence import (
    Evidence,
    EvidenceStore,
    ProvenanceParent,
    validate_evidence_store_snapshot,
)
from midprojectrag.retrieval import dense as _DENSE_RUNTIME_MODULE
from midprojectrag.retrieval import fusion as _FUSION_RUNTIME_MODULE
from midprojectrag.retrieval import kiwi_bm25 as _LEXICAL_RUNTIME_MODULE
from midprojectrag.retrieval.contracts import Candidate, SearchResult
from midprojectrag.runtime_integrity import ResolvedScope

from . import action_effects as _ACTION_EFFECTS_MODULE
from . import compare_slots as _COMPARE_OWNER_MODULE
from . import fact_binding as _FACT_OWNER_MODULE
from .action_effects import SemanticValueSupport
from .contracts import RuleRegistry
from .followup_binding import BoundFollowup
from .followup_retrieval import (
    FollowupEvidencePolicy,
    FollowupRetrievalAttempt,
    FollowupRetrievalOutcome,
)
from .harness_state import HarnessState, build_e1_followup_harness_state, validate_harness_state


SCHEMA_VERSION = "1.0"
HARNESS_EXECUTION_POLICY_ID = "bounded-evidence-controller-v1"
_CONFIG_TOKEN = object()
_RUNTIME_TOKEN = object()
_SEMANTIC_OBLIGATION_TOKEN = object()
_SEMANTIC_REQUEST_TOKEN = object()
_SEMANTIC_RECEIPT_TOKEN = object()
_PARENT_CONTEXT_RECEIPT_TOKEN = object()
_BRIDGE_CONTEXT_RECEIPT_TOKEN = object()
_RERANK_RECEIPT_TOKEN = object()
_RERANK_REQUEST_TOKEN = object()
_ABSENCE_CONFIRMATION_TOKEN = object()
_ISSUED_VALIDATE_EVIDENCE_STORE_SNAPSHOT = validate_evidence_store_snapshot
_ISSUED_HYBRID_SEARCH_LANE = type.__getattribute__(
    object.__getattribute__(_FUSION_RUNTIME_MODULE, "HybridChildRetriever"),
    "__dict__",
)["search_lane"]
_ISSUED_HYBRID_SEARCH_LANE_CODE = object.__getattribute__(
    _ISSUED_HYBRID_SEARCH_LANE, "__code__"
)
_ISSUED_HYBRID_SEARCH_LANE_DEFAULTS = object.__getattribute__(
    _ISSUED_HYBRID_SEARCH_LANE, "__defaults__"
)
_ISSUED_HYBRID_SEARCH_LANE_KWDEFAULTS = object.__getattribute__(
    _ISSUED_HYBRID_SEARCH_LANE, "__kwdefaults__"
)
_ISSUED_HYBRID_LANE_PROVIDER_ERROR = object.__getattribute__(
    _FUSION_RUNTIME_MODULE, "HybridLaneProviderError"
)
_ISSUED_HYBRID_LANE_POST_CALL_CONTRACT_ERROR = object.__getattribute__(
    _FUSION_RUNTIME_MODULE, "HybridLanePostCallContractError"
)
def _owner_callable_pin(function: FunctionType) -> tuple[object, ...]:
    kwdefaults = object.__getattribute__(function, "__kwdefaults__")
    return (
        function,
        object.__getattribute__(function, "__name__"),
        object.__getattribute__(function, "__code__"),
        object.__getattribute__(function, "__defaults__"),
        kwdefaults,
        (
            None
            if kwdefaults is None
            else tuple(sorted(dict.items(kwdefaults)))
        ),
        object.__getattribute__(function, "__globals__"),
        object.__getattribute__(function, "__closure__"),
    )


def _owner_class_pin(owner: type) -> tuple[tuple[str, ...], tuple[tuple[object, ...], ...]]:
    namespace = type.__getattribute__(owner, "__dict__")
    names = tuple(sorted(namespace))
    members = []
    for name in names:
        member = namespace[name]
        callables = []
        if type(member) is FunctionType:
            callables.append(("function", _owner_callable_pin(member)))
        elif type(member) in {classmethod, staticmethod}:
            callables.append(
                (
                    "wrapped",
                    _owner_callable_pin(
                        object.__getattribute__(member, "__func__")
                    ),
                )
            )
        elif type(member) is property:
            for role in ("fget", "fset", "fdel"):
                function = object.__getattribute__(member, role)
                if function is not None:
                    callables.append((role, _owner_callable_pin(function)))
        members.append((name, member, type(member), tuple(callables)))
    return names, tuple(members)


def _owner_module_pins(
    module: object,
) -> tuple[tuple[str, ...], tuple[tuple[object, ...], ...]]:
    namespace = object.__getattribute__(module, "__dict__")
    pins = []
    names = tuple(
        sorted(name for name in namespace if not name.startswith("__"))
    )
    for name in names:
        value = dict.__getitem__(namespace, name)
        pins.append(
            (
                name,
                value,
                type(value),
                _owner_callable_pin(value)
                if type(value) is FunctionType
                else None,
                _owner_class_pin(value) if type(value) is type else None,
            )
        )
    return names, tuple(pins)


_RETRIEVAL_OWNER_SPECS = MappingProxyType(
    {
        "fact": (
            _FACT_OWNER_MODULE,
            object.__getattribute__(_FACT_OWNER_MODULE, "BoundFact"),
            object.__getattribute__(_FACT_OWNER_MODULE, "_FactRetrievalSource"),
            _owner_callable_pin(
                object.__getattribute__(
                    _FACT_OWNER_MODULE, "_project_fact_retrieval_source"
                )
            ),
            _owner_callable_pin(
                object.__getattribute__(
                    _FACT_OWNER_MODULE, "validate_bound_fact"
                )
            ),
            _owner_module_pins(_FACT_OWNER_MODULE),
        ),
        "compare": (
            _COMPARE_OWNER_MODULE,
            object.__getattribute__(_COMPARE_OWNER_MODULE, "BoundCompare"),
            object.__getattribute__(
                _COMPARE_OWNER_MODULE, "_CompareRetrievalSource"
            ),
            _owner_callable_pin(
                object.__getattribute__(
                    _COMPARE_OWNER_MODULE,
                    "_project_compare_retrieval_sources",
                )
            ),
            _owner_callable_pin(
                object.__getattribute__(
                    _COMPARE_OWNER_MODULE, "validate_bound_compare"
                )
            ),
            _owner_module_pins(_COMPARE_OWNER_MODULE),
        ),
    }
)
_ISSUED_RETRIEVAL_OWNER_SPECS = _RETRIEVAL_OWNER_SPECS
_ACTION_EFFECTS_NORMALIZER = object.__getattribute__(
    _ACTION_EFFECTS_MODULE, "_normalize_semantic_verifier_result"
)
_ACTION_EFFECTS_PROJECTION_CLASS = object.__getattribute__(
    _ACTION_EFFECTS_MODULE, "_SemanticVerificationProjection"
)
_ACTION_EFFECTS_RERANK_NORMALIZER = object.__getattribute__(
    _ACTION_EFFECTS_MODULE, "_normalize_reranker_result"
)
_ACTION_EFFECTS_RERANK_PROJECTION_CLASS = object.__getattribute__(
    _ACTION_EFFECTS_MODULE, "_RerankProjection"
)
_ACTION_EFFECTS_MODULE_PIN = _owner_module_pins(_ACTION_EFFECTS_MODULE)
_ISSUED_ACTION_EFFECTS_NORMALIZER = _ACTION_EFFECTS_NORMALIZER
_ISSUED_ACTION_EFFECTS_PROJECTION_CLASS = _ACTION_EFFECTS_PROJECTION_CLASS
_ISSUED_ACTION_EFFECTS_RERANK_NORMALIZER = _ACTION_EFFECTS_RERANK_NORMALIZER
_ISSUED_ACTION_EFFECTS_RERANK_PROJECTION_CLASS = (
    _ACTION_EFFECTS_RERANK_PROJECTION_CLASS
)
_ISSUED_ACTION_EFFECTS_MODULE_PIN = _ACTION_EFFECTS_MODULE_PIN
del _owner_callable_pin
del _owner_class_pin
del _owner_module_pins
_CONFIG_FIELDS = frozenset(
    {
        "schema_version",
        "mode",
        "policy_id",
        "max_nonterminal_actions",
        "max_retrieval_rounds_per_obligation",
        "max_no_progress_per_obligation",
        "max_context_targets_per_obligation",
        "timeout_ms",
        "rrf_k",
        "config_sha256",
    }
)
_CONFIG_SLOT_NAMES = (
    "mode",
    "policy_id",
    "max_nonterminal_actions",
    "max_retrieval_rounds_per_obligation",
    "max_no_progress_per_obligation",
    "max_context_targets_per_obligation",
    "timeout_ms",
    "rrf_k",
    "config_sha256",
)
_RUNTIME_HASH_FIELDS = (
    "evidence_bundle_sha256",
    "hybrid_binding_sha256",
    "dense_attestation_sha256",
    "dense_artifact_sha256",
    "dense_config_sha256",
    "dense_implementation_sha256",
    "lexical_attestation_sha256",
    "lexical_artifact_sha256",
    "lexical_config_sha256",
    "lexical_implementation_sha256",
    "fusion_config_sha256",
    "fusion_implementation_sha256",
    "verifier_implementation_sha256",
    "verifier_config_sha256",
    "reranker_implementation_sha256",
    "reranker_config_sha256",
    "clock_implementation_sha256",
    "binding_sha256",
)
_RUNTIME_SLOT_NAMES = (
    "execution_kind",
    "evidence_bundle_sha256",
    "hybrid_binding_sha256",
    "dense_attestation_sha256",
    "dense_artifact_sha256",
    "dense_config_sha256",
    "dense_implementation_sha256",
    "lexical_attestation_sha256",
    "lexical_artifact_sha256",
    "lexical_config_sha256",
    "lexical_implementation_sha256",
    "fusion_config_sha256",
    "fusion_implementation_sha256",
    "verifier_capability",
    "verifier_id",
    "verifier_implementation_sha256",
    "verifier_config_sha256",
    "reranker_capability",
    "reranker_id",
    "reranker_implementation_sha256",
    "reranker_config_sha256",
    "clock_kind",
    "clock_implementation_sha256",
    "binding_sha256",
)
_PRODUCTION_RUNTIME_FUNCTION_PINS = tuple(
    (
        module,
        name,
        object.__getattribute__(module, name),
        object.__getattribute__(
            object.__getattribute__(module, name), "__code__"
        ),
        object.__getattribute__(
            object.__getattribute__(module, name), "__defaults__"
        ),
        object.__getattribute__(
            object.__getattribute__(module, name), "__kwdefaults__"
        ),
    )
    for module, name in (
        (_DENSE_RUNTIME_MODULE, "preflight_loaded_dense_artifact"),
        (_DENSE_RUNTIME_MODULE, "require_loaded_dense_artifact"),
        (_LEXICAL_RUNTIME_MODULE, "preflight_loaded_lexical_artifact"),
        (_LEXICAL_RUNTIME_MODULE, "require_loaded_lexical_artifact"),
        (_FUSION_RUNTIME_MODULE, "preflight_production_hybrid"),
        (_FUSION_RUNTIME_MODULE, "require_production_hybrid"),
    )
)
_ISSUED_PRODUCTION_RUNTIME_FUNCTION_PINS = _PRODUCTION_RUNTIME_FUNCTION_PINS


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _require_hash(value: Any, code: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(code)
    return value


def _require_positive_int(value: Any, code: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(code)
    return value


def _validated_production_runtime_functions() -> tuple[
    tuple[object, str, FunctionType, CodeType, object, object], ...
]:
    pins = _ISSUED_PRODUCTION_RUNTIME_FUNCTION_PINS
    if type(pins) is not tuple or len(pins) != 6:
        raise ValueError("harness_runtime_validation_dependency_drift")
    for entry in pins:
        if type(entry) is not tuple or len(entry) != 6:
            raise ValueError("harness_runtime_validation_dependency_drift")
        module, name, issued, code, defaults, kwdefaults = entry
        if (
            type(name) is not str
            or type(issued) is not FunctionType
            or type(code) is not CodeType
            or object.__getattribute__(module, name) is not issued
            or object.__getattribute__(issued, "__code__") is not code
            or object.__getattribute__(issued, "__defaults__") is not defaults
            or object.__getattribute__(issued, "__kwdefaults__")
            is not kwdefaults
        ):
            raise ValueError("harness_runtime_validation_dependency_drift")
    return pins


def _production_runtime_callables(
    pins: tuple[
        tuple[object, str, FunctionType, CodeType, object, object], ...
    ],
) -> tuple[FunctionType, ...]:
    if pins is not _ISSUED_PRODUCTION_RUNTIME_FUNCTION_PINS:
        raise ValueError("harness_runtime_validation_dependency_drift")
    return tuple(entry[2] for entry in pins)


def _config_values(config: HarnessExecutionConfig) -> dict[str, Any]:
    _preflight_config_shape(config)
    return {
        name: object.__getattribute__(config, name) for name in _CONFIG_SLOT_NAMES
    }


def _config_payload(config: HarnessExecutionConfig) -> dict[str, Any]:
    values = _config_values(config)
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": values["mode"],
        "policy_id": values["policy_id"],
        "max_nonterminal_actions": values["max_nonterminal_actions"],
        "max_retrieval_rounds_per_obligation": (
            values["max_retrieval_rounds_per_obligation"]
        ),
        "max_no_progress_per_obligation": values[
            "max_no_progress_per_obligation"
        ],
        "max_context_targets_per_obligation": (
            values["max_context_targets_per_obligation"]
        ),
        "timeout_ms": values["timeout_ms"],
        "rrf_k": values["rrf_k"],
    }


def _validate_config_scalars(config: HarnessExecutionConfig) -> None:
    values = _config_values(config)
    if type(values["mode"]) is not str or values["mode"] not in {
        "e0_once",
        "e1_bounded",
    }:
        raise ValueError("invalid_harness_execution_mode")
    if type(values["policy_id"]) is not str or (
        values["policy_id"] != HARNESS_EXECUTION_POLICY_ID
    ):
        raise ValueError("execution_policy_id_mismatch")
    _require_positive_int(
        values["max_nonterminal_actions"], "invalid_max_nonterminal_actions"
    )
    _require_positive_int(
        values["max_retrieval_rounds_per_obligation"],
        "invalid_max_retrieval_rounds_per_obligation",
    )
    if values["max_retrieval_rounds_per_obligation"] != 1:
        raise ValueError("retrieval_rounds_not_pinned_to_one")
    _require_positive_int(
        values["max_no_progress_per_obligation"],
        "invalid_max_no_progress_per_obligation",
    )
    _require_positive_int(
        values["max_context_targets_per_obligation"],
        "invalid_max_context_targets_per_obligation",
    )
    _require_positive_int(values["timeout_ms"], "invalid_timeout_ms")
    _require_positive_int(values["rrf_k"], "invalid_rrf_k")
    if values["rrf_k"] != 60:
        raise ValueError("rrf_constant_not_pinned")
    _require_hash(
        values["config_sha256"], "invalid_harness_execution_config_hash"
    )


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class HarnessExecutionConfig:
    mode: str
    policy_id: str
    max_nonterminal_actions: int
    max_retrieval_rounds_per_obligation: int
    max_no_progress_per_obligation: int
    max_context_targets_per_obligation: int
    timeout_ms: int
    rrf_k: int
    config_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("harness_execution_config_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        mode: str,
        policy_id: str,
        max_nonterminal_actions: int,
        max_retrieval_rounds_per_obligation: int,
        max_no_progress_per_obligation: int,
        max_context_targets_per_obligation: int,
        timeout_ms: int,
        rrf_k: int,
        _token: object,
    ) -> HarnessExecutionConfig:
        if _token is not _CONFIG_TOKEN:
            raise ValueError("harness_execution_config_factory_required")
        result = object.__new__(cls)
        values = {
            "mode": mode,
            "policy_id": policy_id,
            "max_nonterminal_actions": max_nonterminal_actions,
            "max_retrieval_rounds_per_obligation": (
                max_retrieval_rounds_per_obligation
            ),
            "max_no_progress_per_obligation": max_no_progress_per_obligation,
            "max_context_targets_per_obligation": (
                max_context_targets_per_obligation
            ),
            "timeout_ms": timeout_ms,
            "rrf_k": rrf_k,
        }
        for name, value in values.items():
            object.__setattr__(result, name, value)
        object.__setattr__(result, "config_sha256", "0" * 64)
        _validate_config_scalars(result)
        object.__setattr__(result, "config_sha256", _canonical_sha256(_config_payload(result)))
        identity = id(result)
        weak = ref(
            result,
            lambda dead, identity=identity: _drop_config_authority(identity, dead),
        )
        _CONFIG_AUTHORITIES[identity] = (
            weak,
            _canonical_sha256(
                {
                    **_config_payload(result),
                    "config_sha256": object.__getattribute__(
                        result, "config_sha256"
                    ),
                }
            ),
        )
        validate_harness_execution_config(result)
        return result

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> HarnessExecutionConfig:
        if type(raw) is not dict or any(type(key) is not str for key in raw):
            raise TypeError("harness_execution_config_fields")
        if set(raw) != _CONFIG_FIELDS:
            raise ValueError("harness_execution_config_fields")
        if type(raw["schema_version"]) is not str or raw["schema_version"] != SCHEMA_VERSION:
            raise ValueError("unsupported_harness_execution_config_version")
        claimed = _require_hash(
            raw["config_sha256"], "invalid_harness_execution_config_hash"
        )
        result = create_harness_execution_config(
            mode=raw["mode"],
            policy_id=raw["policy_id"],
            max_nonterminal_actions=raw["max_nonterminal_actions"],
            max_retrieval_rounds_per_obligation=(
                raw["max_retrieval_rounds_per_obligation"]
            ),
            max_no_progress_per_obligation=raw["max_no_progress_per_obligation"],
            max_context_targets_per_obligation=(
                raw["max_context_targets_per_obligation"]
            ),
            timeout_ms=raw["timeout_ms"],
            rrf_k=raw["rrf_k"],
        )
        if object.__getattribute__(result, "config_sha256") != claimed:
            raise ValueError("harness_execution_config_hash_mismatch")
        return result

    def to_dict(self) -> dict[str, Any]:
        validate_harness_execution_config(self)
        return {
            **_config_payload(self),
            "config_sha256": object.__getattribute__(self, "config_sha256"),
        }


_PINNED_CONFIG_GETATTRIBUTE = HarnessExecutionConfig.__getattribute__
_PINNED_CONFIG_SLOT_DESCRIPTORS = {
    name: type.__getattribute__(HarnessExecutionConfig, "__dict__")[name]
    for name in _CONFIG_SLOT_NAMES
}


def _preflight_config_shape(config: HarnessExecutionConfig) -> None:
    if type(config) is not HarnessExecutionConfig:
        raise TypeError("harness_execution_config_required")
    namespace = type.__getattribute__(HarnessExecutionConfig, "__dict__")
    if (
        type.__getattribute__(HarnessExecutionConfig, "__getattribute__")
        is not _PINNED_CONFIG_GETATTRIBUTE
        or any(
            namespace.get(name) is not descriptor
            or type(descriptor) is not MemberDescriptorType
            for name, descriptor in _PINNED_CONFIG_SLOT_DESCRIPTORS.items()
        )
    ):
        raise ValueError("harness_execution_config_runtime_shape_drift")


_CONFIG_AUTHORITIES: dict[
    int,
    tuple[ReferenceType[HarnessExecutionConfig], str],
] = {}


def _drop_config_authority(
    identity: int,
    dead: ReferenceType[HarnessExecutionConfig],
) -> None:
    current = _CONFIG_AUTHORITIES.get(identity)
    if current is not None and current[0] is dead:
        _CONFIG_AUTHORITIES.pop(identity, None)


def create_harness_execution_config(
    *,
    mode: str,
    policy_id: str = HARNESS_EXECUTION_POLICY_ID,
    max_nonterminal_actions: int = 24,
    max_retrieval_rounds_per_obligation: int = 1,
    max_no_progress_per_obligation: int = 2,
    max_context_targets_per_obligation: int = 8,
    timeout_ms: int = 30_000,
    rrf_k: int = 60,
) -> HarnessExecutionConfig:
    return HarnessExecutionConfig._create(
        mode=mode,
        policy_id=policy_id,
        max_nonterminal_actions=max_nonterminal_actions,
        max_retrieval_rounds_per_obligation=(
            max_retrieval_rounds_per_obligation
        ),
        max_no_progress_per_obligation=max_no_progress_per_obligation,
        max_context_targets_per_obligation=max_context_targets_per_obligation,
        timeout_ms=timeout_ms,
        rrf_k=rrf_k,
        _token=_CONFIG_TOKEN,
    )


def validate_harness_execution_config(config: HarnessExecutionConfig) -> None:
    if type(config) is not HarnessExecutionConfig:
        raise TypeError("harness_execution_config_required")
    _preflight_config_shape(config)
    authority = _CONFIG_AUTHORITIES.get(id(config))
    if authority is None or authority[0]() is not config:
        raise ValueError("harness_execution_config_runtime_authority_required")
    try:
        _validate_config_scalars(config)
        payload = _config_payload(config)
        expected_config_sha256 = _canonical_sha256(payload)
        full_sha256 = _canonical_sha256(
            {
                **payload,
                "config_sha256": object.__getattribute__(
                    config, "config_sha256"
                ),
            }
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("harness_execution_config_runtime_authority_drift") from exc
    if (
        object.__getattribute__(config, "config_sha256")
        != expected_config_sha256
        or authority[1] != full_sha256
    ):
        raise ValueError("harness_execution_config_runtime_authority_drift")


def _stable_code_value(value: Any) -> Any:
    if value is None or type(value) in {str, bool, int, float}:
        if type(value) is float and not math.isfinite(value):
            return {"type": "nonfinite-float"}
        return value
    if type(value) is bytes:
        return {"bytes": value.hex()}
    if type(value) is tuple:
        return [_stable_code_value(item) for item in value]
    if type(value) is CodeType:
        return _code_payload(value)
    value_type = type(value)
    return {
        "type": f"{value_type.__module__}.{value_type.__qualname__}",
    }


def _stable_state_value(value: Any) -> Any:
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("synthetic_component_state_not_sealable")
        return value
    if type(value) is bytes:
        return {"bytes": value.hex()}
    if type(value) in {tuple, list}:
        return [_stable_state_value(item) for item in value]
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise ValueError("synthetic_component_state_not_sealable")
        return {
            key: _stable_state_value(item)
            for key, item in sorted(dict.items(value))
        }
    raise ValueError("synthetic_component_state_not_sealable")


def _class_behavior_payload(
    component_class: type,
    *,
    recursive: bool = True,
    seen: frozenset[int] = frozenset(),
) -> dict[str, Any]:
    """Describe mutable class state without invoking user descriptors."""

    if type(component_class) is not type:
        raise ValueError("synthetic_component_state_not_sealable")
    qualified_name = (
        f"{type.__getattribute__(component_class, '__module__')}."
        f"{type.__getattribute__(component_class, '__qualname__')}"
    )
    if id(component_class) in seen:
        return {"class": qualified_name, "cycle": True}
    nested_seen = seen | {id(component_class)}
    namespace = type.__getattribute__(component_class, "__dict__")
    attributes: dict[str, Any] = {}
    for name, value in namespace.items():
        if type(name) is not str:
            raise ValueError("synthetic_component_state_not_sealable")
        if name in {
            "__module__",
            "__dict__",
            "__weakref__",
            "__doc__",
            "__annotations__",
            "__dataclass_fields__",
            "__dataclass_params__",
        }:
            continue
        if type(value) is FunctionType:
            attributes[name] = (
                _function_behavior_payload(
                    value,
                    recursive=True,
                    seen=nested_seen,
                )
                if recursive
                else {
                    "function_identity": id(value),
                    "function_sha256": _function_sha256(value),
                }
            )
        elif type(value) is staticmethod:
            function = value.__func__
            if type(function) is not FunctionType:
                raise ValueError("synthetic_component_state_not_sealable")
            attributes[name] = {"staticmethod": (
                _function_behavior_payload(
                    function,
                    recursive=True,
                    seen=nested_seen,
                )
                if recursive
                else {
                    "function_identity": id(function),
                    "function_sha256": _function_sha256(function),
                }
            )}
        elif type(value) is classmethod:
            function = value.__func__
            if type(function) is not FunctionType:
                raise ValueError("synthetic_component_state_not_sealable")
            attributes[name] = {"classmethod": (
                _function_behavior_payload(
                    function,
                    recursive=True,
                    seen=nested_seen,
                )
                if recursive
                else {
                    "function_identity": id(function),
                    "function_sha256": _function_sha256(function),
                }
            )}
        elif type(value) is property:
            functions = (value.fget, value.fset, value.fdel)
            attributes[name] = {
                "property": [
                    None
                    if function is None
                    else (
                        _function_behavior_payload(
                            function,
                            recursive=True,
                            seen=nested_seen,
                        )
                        if recursive
                        else {
                            "function_identity": id(function),
                            "function_sha256": _function_sha256(function),
                        }
                    )
                    for function in functions
                ]
            }
        elif type(value) in {MemberDescriptorType, GetSetDescriptorType}:
            attributes[name] = {
                "descriptor": f"{type(value).__module__}.{type(value).__qualname__}"
            }
        else:
            attributes[name] = _stable_state_value(value)
    return {
        "class": qualified_name,
        "attributes": attributes,
    }


def _behavior_dependency_payload(
    value: Any,
    *,
    recursive: bool,
    seen: frozenset[int],
) -> Any:
    if (
        value is None
        or type(value) in {str, bool, int, float, bytes, tuple, list, dict}
    ):
        return {"state": _stable_state_value(value)}
    if type(value) is FunctionType:
        qualified_name = (
            f"{object.__getattribute__(value, '__module__')}."
            f"{object.__getattribute__(value, '__qualname__')}"
        )
        if id(value) in seen:
            return {
                "function": qualified_name,
                "function_sha256": _function_sha256(value),
                "cycle": True,
            }
        if recursive:
            return {
                "function": qualified_name,
                "behavior": _function_behavior_payload(
                    value,
                    recursive=True,
                    seen=seen,
                ),
            }
        return {
            "function": qualified_name,
            "identity": id(value),
            "function_sha256": _function_sha256(value),
        }
    if type(value) is type:
        if not recursive:
            return {
                "class": (
                    f"{type.__getattribute__(value, '__module__')}."
                    f"{type.__getattribute__(value, '__qualname__')}"
                ),
                "identity": id(value),
            }
        result = {
            "class": _class_behavior_payload(
                value,
                recursive=recursive,
                seen=seen,
            )
        }
        return result
    if not recursive:
        value_type = type(value)
        return {
            "opaque_runtime_dependency": {
                "type": f"{value_type.__module__}.{value_type.__qualname__}",
                "identity": id(value),
            }
        }
    raise ValueError("synthetic_component_state_not_sealable")


def _function_behavior_payload(
    function: FunctionType,
    *,
    recursive: bool = True,
    seen: frozenset[int] = frozenset(),
) -> dict[str, Any]:
    """Seal direct global and closure dependencies without calling the function."""

    if type(function) is not FunctionType:
        raise ValueError("synthetic_component_state_not_sealable")
    qualified_name = (
        f"{object.__getattribute__(function, '__module__')}."
        f"{object.__getattribute__(function, '__qualname__')}"
    )
    if id(function) in seen:
        return {
            "function": qualified_name,
            "function_sha256": _function_sha256(function),
            "cycle": True,
        }
    nested_seen = seen | {id(function)}
    code = object.__getattribute__(function, "__code__")
    globals_state = object.__getattribute__(function, "__globals__")
    closure = object.__getattribute__(function, "__closure__")
    defaults = object.__getattribute__(function, "__defaults__")
    kwdefaults = object.__getattribute__(function, "__kwdefaults__")
    if type(code) is not CodeType or type(globals_state) is not dict:
        raise ValueError("synthetic_component_state_not_sealable")
    global_dependencies: dict[str, Any] = {}
    for name in _code_global_names(code):
        if type(name) is not str:
            raise ValueError("synthetic_component_state_not_sealable")
        if name in globals_state:
            global_dependencies[name] = _behavior_dependency_payload(
                dict.__getitem__(globals_state, name),
                recursive=recursive,
                seen=nested_seen,
            )
    closure_dependencies = []
    if closure is not None:
        if type(closure) is not tuple or len(closure) != len(code.co_freevars):
            raise ValueError("synthetic_component_state_not_sealable")
        for name, cell in zip(code.co_freevars, closure):
            try:
                contents = cell.cell_contents
            except ValueError as exc:
                raise ValueError("synthetic_component_state_not_sealable") from exc
            closure_dependencies.append(
                {
                    "name": name,
                    "value": _behavior_dependency_payload(
                        contents,
                        recursive=recursive,
                        seen=nested_seen,
                    ),
                }
            )
    return {
        "function": qualified_name,
        "function_sha256": _function_sha256(function),
        "defaults": _behavior_dependency_payload(
            defaults,
            recursive=recursive,
            seen=nested_seen,
        ),
        "kwdefaults": _behavior_dependency_payload(
            kwdefaults,
            recursive=recursive,
            seen=nested_seen,
        ),
        "globals": global_dependencies,
        "closure": closure_dependencies,
    }


def _code_global_names(code: CodeType) -> tuple[str, ...]:
    names: list[str] = []

    def visit(current: CodeType) -> None:
        for name in current.co_names:
            if name not in names:
                names.append(name)
        for constant in current.co_consts:
            if type(constant) is CodeType:
                visit(constant)

    visit(code)
    return tuple(names)


def _function_behavior_sha256(
    function: FunctionType,
    *,
    recursive: bool = True,
) -> str:
    return _canonical_sha256(
        _function_behavior_payload(function, recursive=recursive)
    )


def _component_behavior_sha256(
    component: object,
    method: FunctionType,
) -> str:
    return _canonical_sha256(
        {
            "instance_state_sha256": _component_state_sha256(component),
            "class_state": _class_behavior_payload(
                type(component), recursive=True
            ),
            "method_behavior": _function_behavior_payload(
                method, recursive=True
            ),
        }
    )


def _class_and_function_behavior_sha256(
    component: object,
    method: FunctionType,
) -> str:
    """Seal behavior when exact nested instance identities are tracked separately."""

    return _canonical_sha256(
        {
            "class_state": _class_behavior_payload(
                type(component), recursive=False
            ),
            "method_behavior": _function_behavior_payload(
                method, recursive=False
            ),
        }
    )


def _code_payload(code: CodeType) -> dict[str, Any]:
    return {
        "argcount": code.co_argcount,
        "posonlyargcount": code.co_posonlyargcount,
        "kwonlyargcount": code.co_kwonlyargcount,
        "nlocals": code.co_nlocals,
        "stacksize": code.co_stacksize,
        "flags": code.co_flags,
        "code": code.co_code.hex(),
        "consts": [_stable_code_value(value) for value in code.co_consts],
        "names": list(code.co_names),
        "varnames": list(code.co_varnames),
        "freevars": list(code.co_freevars),
        "cellvars": list(code.co_cellvars),
    }


def _function_sha256(function: FunctionType) -> str:
    if type(function) is not FunctionType:
        raise ValueError("harness_runtime_method_override")
    module = object.__getattribute__(function, "__module__")
    qualname = object.__getattribute__(function, "__qualname__")
    code = object.__getattribute__(function, "__code__")
    defaults = object.__getattribute__(function, "__defaults__")
    kwdefaults = object.__getattribute__(function, "__kwdefaults__")
    if type(module) is not str or type(qualname) is not str or type(code) is not CodeType:
        raise ValueError("harness_runtime_method_override")
    if defaults is not None and type(defaults) is not tuple:
        raise ValueError("harness_runtime_method_override")
    if kwdefaults is not None and (
        type(kwdefaults) is not dict
        or any(type(key) is not str for key in kwdefaults)
    ):
        raise ValueError("harness_runtime_method_override")
    return _canonical_sha256(
        {
            "schema_version": SCHEMA_VERSION,
            "module": module,
            "qualname": qualname,
            "code": _code_payload(code),
            "defaults": _stable_code_value(defaults),
            "kwdefaults": (
                None
                if kwdefaults is None
                else {
                    key: _stable_code_value(value)
                    for key, value in sorted(dict.items(kwdefaults))
                }
            ),
        }
    )


def _instance_dict(component: object) -> dict[str, Any]:
    try:
        value = object.__getattribute__(component, "__dict__")
    except AttributeError:
        return {}
    if type(value) is not dict:
        raise ValueError("harness_runtime_method_override")
    return value


def _component_state_sha256(component: object) -> str:
    namespace = _instance_dict(component)
    component_class = type(component)
    for base in type.__getattribute__(component_class, "__mro__"):
        class_namespace = type.__getattribute__(base, "__dict__")
        if any(
            type(value) is MemberDescriptorType and name != "__weakref__"
            for name, value in class_namespace.items()
        ):
            raise ValueError("synthetic_component_state_not_sealable")
    return _canonical_sha256(
        {
            "schema_version": SCHEMA_VERSION,
            "class": (
                f"{component_class.__module__}.{component_class.__qualname__}"
            ),
            "state": _stable_state_value(namespace),
        }
    )


def _declared_method(component: object, method_name: str) -> FunctionType:
    component_class = type(component)
    if type(component_class) is not type or type(method_name) is not str:
        raise ValueError("harness_runtime_method_override")
    if method_name in _instance_dict(component):
        raise ValueError("harness_runtime_method_override")
    mro = type.__getattribute__(component_class, "__mro__")
    if type(mro) is not tuple:
        raise ValueError("harness_runtime_method_override")
    for base in mro:
        namespace = type.__getattribute__(base, "__dict__")
        candidate = namespace.get(method_name)
        if candidate is not None:
            if type(candidate) is not FunctionType:
                raise ValueError("harness_runtime_method_override")
            return candidate
    raise ValueError("harness_runtime_method_override")


@dataclass(frozen=True, slots=True)
class _ComponentAuthority:
    component: object | None
    component_class: type | None
    component_getattribute: object | None
    method_name: str
    method: FunctionType | None
    method_code: CodeType | None
    method_sha256: str
    state_sha256: str


def _component_descriptor(
    *,
    role: str,
    execution_kind: str,
    component: object | None,
    method_name: str,
) -> tuple[dict[str, str], _ComponentAuthority]:
    if component is None:
        implementation = _canonical_sha256(
            {"schema_version": SCHEMA_VERSION, "role": role, "capability": "unavailable"}
        )
        return (
            {
                f"{role}_capability": "unavailable",
                f"{role}_id": "none",
                f"{role}_implementation_sha256": implementation,
                f"{role}_config_sha256": _canonical_sha256(
                    {"schema_version": SCHEMA_VERSION, "role": role, "config": "none"}
                ),
            },
            _ComponentAuthority(
                None, None, None, method_name, None, None, "", ""
            ),
        )
    method = _declared_method(component, method_name)
    implementation = _function_sha256(method)
    state_sha256 = _component_behavior_sha256(component, method)
    return (
        {
            f"{role}_capability": "available",
            f"{role}_id": f"{execution_kind}-{role}-v1",
            f"{role}_implementation_sha256": implementation,
            f"{role}_config_sha256": _canonical_sha256(
                {
                    "schema_version": SCHEMA_VERSION,
                    "execution_kind": execution_kind,
                    "role": role,
                    "implementation_sha256": implementation,
                    "state_sha256": state_sha256,
                }
            ),
        },
        _ComponentAuthority(
            component,
            type(component),
            type.__getattribute__(type(component), "__getattribute__"),
            method_name,
            method,
            object.__getattribute__(method, "__code__"),
            implementation,
            state_sha256,
        ),
    )


def _runtime_values(binding: HarnessRuntimeBinding) -> dict[str, str]:
    _preflight_runtime_binding_shape(binding)
    return {
        name: object.__getattribute__(binding, name)
        for name in _RUNTIME_SLOT_NAMES
    }


def _runtime_payload(binding: HarnessRuntimeBinding) -> dict[str, str]:
    values = _runtime_values(binding)
    return {
        "schema_version": SCHEMA_VERSION,
        **{
            name: values[name]
            for name in _RUNTIME_SLOT_NAMES
            if name != "binding_sha256"
        },
    }


def _validate_runtime_scalars(binding: HarnessRuntimeBinding) -> None:
    values = _runtime_values(binding)
    if type(values["execution_kind"]) is not str or values["execution_kind"] not in {
        "production",
        "synthetic",
    }:
        raise ValueError("invalid_harness_runtime_execution_kind")
    for name in _RUNTIME_HASH_FIELDS:
        _require_hash(values[name], f"invalid_{name}")
    for role in ("verifier", "reranker"):
        capability = values[f"{role}_capability"]
        identity = values[f"{role}_id"]
        if type(capability) is not str or capability not in {"available", "unavailable"}:
            raise ValueError("harness_runtime_capability_drift")
        if type(identity) is not str or not identity:
            raise ValueError("harness_runtime_capability_drift")
        if (capability == "unavailable") != (identity == "none"):
            raise ValueError("harness_runtime_capability_drift")
    if type(values["clock_kind"]) is not str or values["clock_kind"] not in {
        "monotonic_ns",
        "synthetic_test",
    }:
        raise ValueError("harness_runtime_clock_drift")
    if (values["execution_kind"] == "production") != (
        values["clock_kind"] == "monotonic_ns"
    ):
        raise ValueError("harness_runtime_clock_drift")


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class HarnessRuntimeBinding:
    execution_kind: str
    evidence_bundle_sha256: str
    hybrid_binding_sha256: str
    dense_attestation_sha256: str
    dense_artifact_sha256: str
    dense_config_sha256: str
    dense_implementation_sha256: str
    lexical_attestation_sha256: str
    lexical_artifact_sha256: str
    lexical_config_sha256: str
    lexical_implementation_sha256: str
    fusion_config_sha256: str
    fusion_implementation_sha256: str
    verifier_capability: str
    verifier_id: str
    verifier_implementation_sha256: str
    verifier_config_sha256: str
    reranker_capability: str
    reranker_id: str
    reranker_implementation_sha256: str
    reranker_config_sha256: str
    clock_kind: str
    clock_implementation_sha256: str
    binding_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("harness_runtime_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        payload: Mapping[str, str],
        authority: _HarnessRuntimeAuthorityDraft,
        _token: object,
    ) -> HarnessRuntimeBinding:
        if _token is not _RUNTIME_TOKEN:
            raise ValueError("harness_runtime_factory_required")
        result = object.__new__(cls)
        for name, value in payload.items():
            object.__setattr__(result, name, value)
        object.__setattr__(result, "binding_sha256", "0" * 64)
        _validate_runtime_scalars(result)
        object.__setattr__(result, "binding_sha256", _canonical_sha256(_runtime_payload(result)))
        identity = id(result)
        weak = ref(
            result,
            lambda dead, identity=identity: _drop_runtime_authority(identity, dead),
        )
        issued_payload_sha256 = _canonical_sha256(
            {
                **_runtime_payload(result),
                "binding_sha256": object.__getattribute__(
                    result, "binding_sha256"
                ),
            }
        )
        issued_authority = _HarnessRuntimeAuthority(
            weak=weak,
            issued_payload_sha256=issued_payload_sha256,
            **{
                name: object.__getattribute__(authority, name)
                for name in _RUNTIME_AUTHORITY_DRAFT_FIELDS
            },
        )
        dict.__setitem__(_ISSUED_RUNTIME_AUTHORITIES, identity, issued_authority)
        dict.__setitem__(
            _ISSUED_RUNTIME_AUTHORITY_SHADOW, identity, issued_authority
        )
        try:
            validate_harness_runtime_binding(
                binding=result,
                store=authority.store,
                expected_execution_kind=authority.execution_kind,
            )
        except Exception:
            dict.pop(_ISSUED_RUNTIME_AUTHORITIES, identity, None)
            dict.pop(_ISSUED_RUNTIME_AUTHORITY_SHADOW, identity, None)
            raise
        return result

    @classmethod
    def for_test(
        cls,
        *,
        store: EvidenceStore,
        retriever: object,
        verifier: object | None = None,
        reranker: object | None = None,
        clock: FunctionType,
        _dependency_checker=None,
        _dependency_checker_code=None,
    ) -> HarnessRuntimeBinding:
        module_namespace = globals()
        checker_defaults = (
            None
            if type(_dependency_checker) is not FunctionType
            else object.__getattribute__(_dependency_checker, "__defaults__")
        )
        if (
            _dependency_checker
            is not dict.get(
                module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER"
            )
            or type(_dependency_checker) is not FunctionType
            or object.__getattribute__(_dependency_checker, "__code__")
            is not _dependency_checker_code
            or _dependency_checker_code
            is not dict.get(
                module_namespace, "_PINNED_RUNTIME_GATE_DEPENDENCY_CHECKER_CODE"
            )
            or checker_defaults
            is not dict.get(
                module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_DEFAULTS"
            )
            or type(checker_defaults) is not tuple
            or len(checker_defaults) != 6
            or tuple.__getitem__(checker_defaults, 0) is not module_namespace
            or object.__getattribute__(_dependency_checker, "__kwdefaults__")
            is not None
        ):
            raise ValueError("harness_runtime_validation_dependency_drift")
        _dependency_checker()
        if cls is not HarnessRuntimeBinding:
            raise TypeError("harness_runtime_factory_required")
        return _ISSUED_BIND_HARNESS_RUNTIME(
            execution_kind="synthetic",
            store=store,
            retriever=retriever,
            verifier=verifier,
            reranker=reranker,
            clock=clock,
        )

    def to_dict(
        self,
        *,
        _dependency_checker=None,
        _dependency_checker_code=None,
    ) -> dict[str, str]:
        module_namespace = globals()
        checker_defaults = (
            None
            if type(_dependency_checker) is not FunctionType
            else object.__getattribute__(_dependency_checker, "__defaults__")
        )
        if (
            _dependency_checker
            is not dict.get(
                module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER"
            )
            or type(_dependency_checker) is not FunctionType
            or object.__getattribute__(_dependency_checker, "__code__")
            is not _dependency_checker_code
            or _dependency_checker_code
            is not dict.get(
                module_namespace, "_PINNED_RUNTIME_GATE_DEPENDENCY_CHECKER_CODE"
            )
            or checker_defaults
            is not dict.get(
                module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_DEFAULTS"
            )
            or type(checker_defaults) is not tuple
            or len(checker_defaults) != 6
            or tuple.__getitem__(checker_defaults, 0) is not module_namespace
            or object.__getattribute__(_dependency_checker, "__kwdefaults__")
            is not None
        ):
            raise ValueError("harness_runtime_validation_dependency_drift")
        _dependency_checker()
        authority = _ISSUED_REQUIRE_HARNESS_RUNTIME_AUTHORITY(self)
        _ISSUED_VALIDATE_HARNESS_RUNTIME_BINDING(
            binding=self,
            authority=authority,
            store=authority.store,
            expected_execution_kind=None,
        )
        return {
            **_runtime_payload(self),
            "binding_sha256": object.__getattribute__(self, "binding_sha256"),
        }


_PINNED_RUNTIME_GETATTRIBUTE = HarnessRuntimeBinding.__getattribute__
_PINNED_RUNTIME_SLOT_DESCRIPTORS = {
    name: type.__getattribute__(HarnessRuntimeBinding, "__dict__")[name]
    for name in _RUNTIME_SLOT_NAMES
}


def _preflight_runtime_binding_shape(binding: HarnessRuntimeBinding) -> None:
    if type(binding) is not HarnessRuntimeBinding:
        raise TypeError("harness_runtime_binding_required")
    namespace = type.__getattribute__(HarnessRuntimeBinding, "__dict__")
    if (
        type.__getattribute__(HarnessRuntimeBinding, "__getattribute__")
        is not _PINNED_RUNTIME_GETATTRIBUTE
        or any(
            namespace.get(name) is not descriptor
            or type(descriptor) is not MemberDescriptorType
            for name, descriptor in _PINNED_RUNTIME_SLOT_DESCRIPTORS.items()
        )
    ):
        raise ValueError("harness_runtime_binding_shape_drift")


@dataclass(frozen=True, slots=True)
class _HarnessRuntimeAuthorityDraft:
    execution_kind: str
    store: EvidenceStore
    retriever: object
    retriever_class: type
    retriever_getattribute: object
    retriever_method: FunctionType
    retriever_method_code: CodeType
    retriever_method_sha256: str
    retriever_behavior_sha256: str
    dense: object
    dense_class: type
    dense_getattribute: object
    dense_method: FunctionType
    dense_method_code: CodeType
    dense_method_sha256: str
    dense_state_sha256: str
    lexical: object
    lexical_class: type
    lexical_getattribute: object
    lexical_method: FunctionType
    lexical_method_code: CodeType
    lexical_method_sha256: str
    lexical_state_sha256: str
    fusion_module: object
    fusion_method: FunctionType
    fusion_method_code: CodeType
    fusion_method_sha256: str
    fusion_behavior_sha256: str
    verifier: _ComponentAuthority
    reranker: _ComponentAuthority
    clock: object
    clock_code: CodeType | None
    clock_behavior_sha256: str
    production_hybrid_binding: object | None
    dense_attestation: object | None
    lexical_attestation: object | None
    production_runtime_functions: object | None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__slots__}


@dataclass(frozen=True, slots=True)
class _HarnessRuntimeAuthority:
    weak: ReferenceType[HarnessRuntimeBinding]
    issued_payload_sha256: str
    execution_kind: str
    store: EvidenceStore
    retriever: object
    retriever_class: type
    retriever_getattribute: object
    retriever_method: FunctionType
    retriever_method_code: CodeType
    retriever_method_sha256: str
    retriever_behavior_sha256: str
    dense: object
    dense_class: type
    dense_getattribute: object
    dense_method: FunctionType
    dense_method_code: CodeType
    dense_method_sha256: str
    dense_state_sha256: str
    lexical: object
    lexical_class: type
    lexical_getattribute: object
    lexical_method: FunctionType
    lexical_method_code: CodeType
    lexical_method_sha256: str
    lexical_state_sha256: str
    fusion_module: object
    fusion_method: FunctionType
    fusion_method_code: CodeType
    fusion_method_sha256: str
    fusion_behavior_sha256: str
    verifier: _ComponentAuthority
    reranker: _ComponentAuthority
    clock: object
    clock_code: CodeType | None
    clock_behavior_sha256: str
    production_hybrid_binding: object | None
    dense_attestation: object | None
    lexical_attestation: object | None
    production_runtime_functions: object | None


_RUNTIME_AUTHORITY_DRAFT_FIELDS = tuple(
    name
    for name in _HarnessRuntimeAuthorityDraft.__slots__
    if name != "__weakref__"
)
_ISSUED_RUNTIME_AUTHORITY_DRAFT_FIELDS = _RUNTIME_AUTHORITY_DRAFT_FIELDS


_RUNTIME_AUTHORITIES: dict[int, _HarnessRuntimeAuthority] = {}
_ISSUED_RUNTIME_AUTHORITIES = _RUNTIME_AUTHORITIES
_RUNTIME_AUTHORITY_SHADOW: dict[int, _HarnessRuntimeAuthority] = {}
_ISSUED_RUNTIME_AUTHORITY_SHADOW = _RUNTIME_AUTHORITY_SHADOW


def _drop_runtime_authority(
    identity: int,
    dead: ReferenceType[HarnessRuntimeBinding],
) -> None:
    current = dict.get(_ISSUED_RUNTIME_AUTHORITIES, identity)
    shadow = dict.get(_ISSUED_RUNTIME_AUTHORITY_SHADOW, identity)
    if current is shadow and current is not None and current.weak is dead:
        dict.pop(_ISSUED_RUNTIME_AUTHORITIES, identity, None)
        dict.pop(_ISSUED_RUNTIME_AUTHORITY_SHADOW, identity, None)


def _clock_descriptor(
    execution_kind: str,
    clock: object,
) -> tuple[dict[str, str], CodeType | None]:
    if execution_kind == "production":
        if clock is not _PRODUCTION_CLOCK or type(clock) is not BuiltinFunctionType:
            raise ValueError("harness_runtime_clock_drift")
        return (
            {
                "clock_kind": "monotonic_ns",
                "clock_implementation_sha256": _canonical_sha256(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "clock": "time.monotonic_ns",
                    }
                ),
            },
            None,
        )
    if type(clock) is not FunctionType:
        raise ValueError("synthetic_clock_function_required")
    code = object.__getattribute__(clock, "__code__")
    if type(code) is not CodeType:
        raise ValueError("synthetic_clock_function_required")
    return (
        {
            "clock_kind": "synthetic_test",
            "clock_implementation_sha256": _function_sha256(clock),
        },
        code,
    )


def _synthetic_lane_payload(
    *,
    store: EvidenceStore,
    dense_method: FunctionType,
    dense_state_sha256: str,
    lexical_method: FunctionType,
    lexical_state_sha256: str,
    fusion_method: FunctionType,
) -> dict[str, str]:
    dense_implementation = _function_sha256(dense_method)
    lexical_implementation = _function_sha256(lexical_method)
    fusion_implementation = _function_sha256(fusion_method)
    dense_config = _canonical_sha256(
        {
            "schema_version": SCHEMA_VERSION,
            "lane": "dense",
            "implementation": dense_implementation,
            "state_sha256": dense_state_sha256,
        }
    )
    lexical_config = _canonical_sha256(
        {
            "schema_version": SCHEMA_VERSION,
            "lane": "lexical",
            "implementation": lexical_implementation,
            "state_sha256": lexical_state_sha256,
        }
    )
    fusion_config = _canonical_sha256(
        {"schema_version": SCHEMA_VERSION, "algorithm": "rrf", "rrf_k": 60}
    )
    return {
        "hybrid_binding_sha256": _canonical_sha256(
            {
                "schema_version": SCHEMA_VERSION,
                "execution_kind": "synthetic",
                "bundle_sha256": object.__getattribute__(
                    store, "bundle_sha256"
                ),
                "dense_implementation_sha256": dense_implementation,
                "dense_state_sha256": dense_state_sha256,
                "lexical_implementation_sha256": lexical_implementation,
                "lexical_state_sha256": lexical_state_sha256,
                "fusion_implementation_sha256": fusion_implementation,
            }
        ),
        "dense_attestation_sha256": _canonical_sha256(
            {"schema_version": SCHEMA_VERSION, "lane": "dense", "authority": "synthetic_test"}
        ),
        "dense_artifact_sha256": dense_config,
        "dense_config_sha256": dense_config,
        "dense_implementation_sha256": dense_implementation,
        "lexical_attestation_sha256": _canonical_sha256(
            {"schema_version": SCHEMA_VERSION, "lane": "lexical", "authority": "synthetic_test"}
        ),
        "lexical_artifact_sha256": lexical_config,
        "lexical_config_sha256": lexical_config,
        "lexical_implementation_sha256": lexical_implementation,
        "fusion_config_sha256": fusion_config,
        "fusion_implementation_sha256": fusion_implementation,
    }


def _hybrid_instance_parts(
    retriever: object,
    retriever_class: type,
) -> tuple[object, object, object]:
    if type(retriever) is not retriever_class:
        raise ValueError("harness_runtime_hybrid_binding_required")
    namespace = _instance_dict(retriever)
    if set(namespace) != {"store", "dense", "lexical"}:
        raise ValueError("harness_runtime_hybrid_binding_required")
    return (
        dict.__getitem__(namespace, "store"),
        dict.__getitem__(namespace, "dense"),
        dict.__getitem__(namespace, "lexical"),
    )


def _bind_harness_runtime(
    *,
    execution_kind: str,
    store: EvidenceStore,
    retriever: object,
    verifier: object | None,
    reranker: object | None,
    clock: object,
) -> HarnessRuntimeBinding:
    from midprojectrag.retrieval import fusion as fusion_module
    from midprojectrag.retrieval.fusion import HybridChildRetriever

    if type(execution_kind) is not str or execution_kind not in {"production", "synthetic"}:
        raise ValueError("invalid_harness_runtime_execution_kind")
    if execution_kind == "production":
        if verifier is not None:
            raise ValueError("production_verifier_not_approved")
        if reranker is not None:
            raise ValueError("production_reranker_not_approved")
    if type(store) is not EvidenceStore:
        raise TypeError("evidence_store_required")
    if type(retriever) is not HybridChildRetriever:
        raise ValueError("harness_runtime_hybrid_binding_required")
    retriever_store, dense, lexical = _hybrid_instance_parts(
        retriever, HybridChildRetriever
    )
    if retriever_store is not store:
        raise ValueError("harness_runtime_store_identity_mismatch")
    retriever_method = _declared_method(retriever, "search")
    preflight_hybrid = None
    preflight_dense = None
    preflight_lexical = None
    production_runtime_functions = None
    require_dense = None
    require_lexical = None
    require_hybrid = None
    if execution_kind == "production":
        from midprojectrag.retrieval.dense import DenseChildLane
        from midprojectrag.retrieval.kiwi_bm25 import (
            KiwiBM25Lane,
            KiwiTokenizer,
        )
        from midprojectrag.stacks.local.hf_embeddings import KureEmbeddingProvider

        production_runtime_functions = (
            _validated_production_runtime_functions()
        )
        (
            preflight_loaded_dense_artifact,
            require_dense,
            preflight_loaded_lexical_artifact,
            require_lexical,
            preflight_production_hybrid,
            require_hybrid,
        ) = _production_runtime_callables(production_runtime_functions)

        if type(dense) is not DenseChildLane or type(lexical) is not KiwiBM25Lane:
            raise ValueError("harness_runtime_attestation_drift")
        preflight_dense = preflight_loaded_dense_artifact(
            dense, store, production=True
        )
        preflight_lexical = preflight_loaded_lexical_artifact(lexical, store)
        preflight_hybrid, _ = preflight_production_hybrid(retriever, store)
        dense_namespace = _instance_dict(dense)
        lexical_namespace = _instance_dict(lexical)
        if (
            "store" not in dense_namespace
            or "provider" not in dense_namespace
            or "store" not in lexical_namespace
            or "tokenizer" not in lexical_namespace
            or dict.__getitem__(dense_namespace, "store") is not store
            or dict.__getitem__(lexical_namespace, "store") is not store
            or type(dict.__getitem__(dense_namespace, "provider"))
            is not KureEmbeddingProvider
            or type(dict.__getitem__(lexical_namespace, "tokenizer"))
            is not KiwiTokenizer
        ):
            raise ValueError("harness_runtime_attestation_drift")
    dense_method = _declared_method(dense, "search")
    lexical_method = _declared_method(lexical, "search")
    fusion_method = fusion_module.fuse_rrf
    if type(fusion_method) is not FunctionType:
        raise ValueError("harness_runtime_method_override")
    dense_state_sha256 = _function_behavior_sha256(
        dense_method, recursive=False
    )
    lexical_state_sha256 = _function_behavior_sha256(
        lexical_method, recursive=False
    )
    retriever_behavior_sha256 = _function_behavior_sha256(
        retriever_method, recursive=False
    )
    fusion_behavior_sha256 = _function_behavior_sha256(
        fusion_method, recursive=False
    )
    clock_behavior_sha256 = ""
    if execution_kind == "synthetic":
        dense_state_sha256 = _component_behavior_sha256(dense, dense_method)
        lexical_state_sha256 = _component_behavior_sha256(
            lexical, lexical_method
        )
        retriever_behavior_sha256 = _class_and_function_behavior_sha256(
            retriever, retriever_method
        )

    verifier_payload, verifier_authority = _component_descriptor(
        role="verifier",
        execution_kind=execution_kind,
        component=verifier,
        method_name="verify",
    )
    reranker_payload, reranker_authority = _component_descriptor(
        role="reranker",
        execution_kind=execution_kind,
        component=reranker,
        method_name="rerank",
    )
    clock_payload, clock_code = _clock_descriptor(execution_kind, clock)
    if execution_kind == "synthetic":
        clock_behavior_sha256 = _function_behavior_sha256(clock)
    try:
        _ISSUED_VALIDATE_EVIDENCE_STORE_SNAPSHOT(
            store, object.__getattribute__(store, "bundle_sha256")
        )
    except ValueError as exc:
        raise ValueError("harness_runtime_store_payload_drift") from exc

    production_hybrid = None
    dense_attestation = None
    lexical_attestation = None
    if execution_kind == "production":
        try:
            production_hybrid = require_hybrid(retriever, store)
            dense_attestation = require_dense(
                dense, store, production=True
            )
            lexical_attestation = require_lexical(
                lexical, store, production=True
            )
        except ValueError as exc:
            raise ValueError("harness_runtime_attestation_drift") from exc
        if (
            production_hybrid is not preflight_hybrid
            or dense_attestation is not preflight_dense
            or lexical_attestation is not preflight_lexical
        ):
            raise ValueError("harness_runtime_attestation_drift")
        lane_payload = {
            "hybrid_binding_sha256": object.__getattribute__(
                production_hybrid, "binding_sha256"
            ),
            "dense_attestation_sha256": object.__getattribute__(
                dense_attestation, "attestation_sha256"
            ),
            "dense_artifact_sha256": object.__getattribute__(
                dense, "artifact_sha256"
            ),
            "dense_config_sha256": object.__getattribute__(
                dense_attestation, "embedding_identity_sha256"
            ),
            "dense_implementation_sha256": _function_sha256(dense_method),
            "lexical_attestation_sha256": object.__getattribute__(
                lexical_attestation, "attestation_sha256"
            ),
            "lexical_artifact_sha256": object.__getattribute__(
                lexical, "artifact_sha256"
            ),
            "lexical_config_sha256": object.__getattribute__(
                lexical_attestation, "config_sha256"
            ),
            "lexical_implementation_sha256": _function_sha256(lexical_method),
            "fusion_config_sha256": object.__getattribute__(
                production_hybrid, "fusion_config_sha256"
            ),
            "fusion_implementation_sha256": _function_sha256(fusion_method),
        }
    else:
        lane_payload = _synthetic_lane_payload(
            store=store,
            dense_method=dense_method,
            dense_state_sha256=dense_state_sha256,
            lexical_method=lexical_method,
            lexical_state_sha256=lexical_state_sha256,
            fusion_method=fusion_method,
        )
    payload = {
        "execution_kind": execution_kind,
        "evidence_bundle_sha256": object.__getattribute__(
            store, "bundle_sha256"
        ),
        **lane_payload,
        **verifier_payload,
        **reranker_payload,
        **clock_payload,
    }
    authority = _HarnessRuntimeAuthorityDraft(
        execution_kind=execution_kind,
        store=store,
        retriever=retriever,
        retriever_class=type(retriever),
        retriever_getattribute=type.__getattribute__(
            type(retriever), "__getattribute__"
        ),
        retriever_method=retriever_method,
        retriever_method_code=object.__getattribute__(
            retriever_method, "__code__"
        ),
        retriever_method_sha256=_function_sha256(retriever_method),
        retriever_behavior_sha256=retriever_behavior_sha256,
        dense=dense,
        dense_class=type(dense),
        dense_getattribute=type.__getattribute__(type(dense), "__getattribute__"),
        dense_method=dense_method,
        dense_method_code=object.__getattribute__(dense_method, "__code__"),
        dense_method_sha256=_function_sha256(dense_method),
        dense_state_sha256=dense_state_sha256,
        lexical=lexical,
        lexical_class=type(lexical),
        lexical_getattribute=type.__getattribute__(
            type(lexical), "__getattribute__"
        ),
        lexical_method=lexical_method,
        lexical_method_code=object.__getattribute__(lexical_method, "__code__"),
        lexical_method_sha256=_function_sha256(lexical_method),
        lexical_state_sha256=lexical_state_sha256,
        fusion_module=fusion_module,
        fusion_method=fusion_method,
        fusion_method_code=object.__getattribute__(fusion_method, "__code__"),
        fusion_method_sha256=_function_sha256(fusion_method),
        fusion_behavior_sha256=fusion_behavior_sha256,
        verifier=verifier_authority,
        reranker=reranker_authority,
        clock=clock,
        clock_code=clock_code,
        clock_behavior_sha256=clock_behavior_sha256,
        production_hybrid_binding=production_hybrid,
        dense_attestation=dense_attestation,
        lexical_attestation=lexical_attestation,
        production_runtime_functions=production_runtime_functions,
    )
    return HarnessRuntimeBinding._create(
        payload=payload,
        authority=authority,
        _token=_RUNTIME_TOKEN,
    )


_ISSUED_BIND_HARNESS_RUNTIME = _bind_harness_runtime


def bind_production_harness_runtime(
    *,
    store: EvidenceStore,
    retriever: object,
    verifier: object | None = None,
    reranker: object | None = None,
    _dependency_checker=None,
    _dependency_checker_code=None,
) -> HarnessRuntimeBinding:
    module_namespace = globals()
    checker_defaults = (
        None
        if type(_dependency_checker) is not FunctionType
        else object.__getattribute__(_dependency_checker, "__defaults__")
    )
    if (
        _dependency_checker
        is not dict.get(
            module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER"
        )
        or type(_dependency_checker) is not FunctionType
        or object.__getattribute__(_dependency_checker, "__code__")
        is not _dependency_checker_code
        or _dependency_checker_code
        is not dict.get(
            module_namespace, "_PINNED_RUNTIME_GATE_DEPENDENCY_CHECKER_CODE"
        )
        or checker_defaults
        is not dict.get(
            module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_DEFAULTS"
        )
        or type(checker_defaults) is not tuple
        or len(checker_defaults) != 6
        or tuple.__getitem__(checker_defaults, 0) is not module_namespace
        or object.__getattribute__(_dependency_checker, "__kwdefaults__")
        is not None
    ):
        raise ValueError("harness_runtime_validation_dependency_drift")
    _dependency_checker()
    if verifier is not None:
        raise ValueError("production_verifier_not_approved")
    if reranker is not None:
        raise ValueError("production_reranker_not_approved")
    return _ISSUED_BIND_HARNESS_RUNTIME(
        execution_kind="production",
        store=store,
        retriever=retriever,
        verifier=None,
        reranker=None,
        clock=_PRODUCTION_CLOCK,
    )


_ISSUED_BIND_PRODUCTION_HARNESS_RUNTIME = bind_production_harness_runtime


def _require_harness_runtime_authority(
    binding: HarnessRuntimeBinding,
) -> _HarnessRuntimeAuthority:
    if type(binding) is not HarnessRuntimeBinding:
        raise TypeError("harness_runtime_binding_required")
    authority = dict.get(_ISSUED_RUNTIME_AUTHORITIES, id(binding))
    shadow = dict.get(_ISSUED_RUNTIME_AUTHORITY_SHADOW, id(binding))
    if type(authority) is not _HarnessRuntimeAuthority or authority is not shadow:
        raise ValueError("harness_runtime_authority_required")
    weak = object.__getattribute__(authority, "weak")
    if type(weak) is not ReferenceType or weak() is not binding:
        raise ValueError("harness_runtime_authority_required")
    return authority


def _validate_component_authority(component: _ComponentAuthority) -> None:
    if component.component is None:
        if (
            component.component_class is not None
            or component.component_getattribute is not None
            or component.method is not None
            or component.method_code is not None
            or component.method_sha256
            or component.state_sha256
        ):
            raise ValueError("harness_runtime_capability_drift")
        return
    if type(component.component) is not component.component_class:
        raise ValueError("harness_runtime_capability_drift")
    if (
        type.__getattribute__(component.component_class, "__getattribute__")
        is not component.component_getattribute
    ):
        raise ValueError("harness_runtime_method_override")
    current = _declared_method(component.component, component.method_name)
    if (
        current is not component.method
        or object.__getattribute__(current, "__code__")
        is not component.method_code
        or _function_sha256(current) != component.method_sha256
    ):
        raise ValueError("harness_runtime_method_override")
    if (
        _component_behavior_sha256(component.component, current)
        != component.state_sha256
    ):
        raise ValueError("harness_runtime_component_state_drift")


def _validate_method_authority(
    *,
    component: object,
    component_class: type,
    component_getattribute: object,
    method: FunctionType,
    method_code: CodeType,
    method_sha256: str,
) -> None:
    if type(component) is not component_class:
        raise ValueError("harness_runtime_nested_identity_drift")
    if (
        type.__getattribute__(component_class, "__getattribute__")
        is not component_getattribute
    ):
        raise ValueError("harness_runtime_method_override")
    current = _declared_method(component, "search")
    if (
        current is not method
        or object.__getattribute__(current, "__code__") is not method_code
        or _function_sha256(current) != method_sha256
    ):
        raise ValueError("harness_runtime_method_override")


def _validate_harness_runtime_binding(
    *,
    binding: HarnessRuntimeBinding,
    authority: _HarnessRuntimeAuthority,
    store: EvidenceStore,
    expected_execution_kind: str | None,
) -> None:
    _preflight_runtime_binding_shape(binding)
    try:
        _validate_runtime_scalars(binding)
    except (TypeError, ValueError) as exc:
        raise ValueError("harness_runtime_authority_drift") from exc
    values = _runtime_values(binding)
    execution_kind = values["execution_kind"]
    if expected_execution_kind is not None:
        if type(expected_execution_kind) is not str or expected_execution_kind not in {
            "production",
            "synthetic",
        }:
            raise ValueError("harness_runtime_execution_kind_mismatch")
        if execution_kind != expected_execution_kind:
            raise ValueError("harness_runtime_execution_kind_mismatch")
    if type(store) is not EvidenceStore:
        raise TypeError("evidence_store_required")
    if store is not authority.store:
        raise ValueError("harness_runtime_store_identity_mismatch")
    if execution_kind != authority.execution_kind:
        raise ValueError("harness_runtime_execution_kind_mismatch")
    retriever = authority.retriever
    _validate_method_authority(
        component=retriever,
        component_class=authority.retriever_class,
        component_getattribute=authority.retriever_getattribute,
        method=authority.retriever_method,
        method_code=authority.retriever_method_code,
        method_sha256=authority.retriever_method_sha256,
    )
    retriever_store, current_dense, current_lexical = _hybrid_instance_parts(
        retriever, authority.retriever_class
    )
    if (
        retriever_store is not store
        or current_dense is not authority.dense
        or current_lexical is not authority.lexical
    ):
        raise ValueError("harness_runtime_nested_identity_drift")
    _validate_method_authority(
        component=authority.dense,
        component_class=authority.dense_class,
        component_getattribute=authority.dense_getattribute,
        method=authority.dense_method,
        method_code=authority.dense_method_code,
        method_sha256=authority.dense_method_sha256,
    )
    _validate_method_authority(
        component=authority.lexical,
        component_class=authority.lexical_class,
        component_getattribute=authority.lexical_getattribute,
        method=authority.lexical_method,
        method_code=authority.lexical_method_code,
        method_sha256=authority.lexical_method_sha256,
    )
    if execution_kind == "synthetic" and (
        _class_and_function_behavior_sha256(
            retriever, authority.retriever_method
        )
        != authority.retriever_behavior_sha256
        or _component_behavior_sha256(
            authority.dense, authority.dense_method
        )
        != authority.dense_state_sha256
        or _component_behavior_sha256(
            authority.lexical, authority.lexical_method
        )
        != authority.lexical_state_sha256
    ):
        raise ValueError("harness_runtime_component_state_drift")
    if execution_kind == "production" and (
        _function_behavior_sha256(
            authority.retriever_method, recursive=False
        )
        != authority.retriever_behavior_sha256
        or _function_behavior_sha256(
            authority.dense_method, recursive=False
        )
        != authority.dense_state_sha256
        or _function_behavior_sha256(
            authority.lexical_method, recursive=False
        )
        != authority.lexical_state_sha256
    ):
        raise ValueError("harness_runtime_method_override")
    current_fusion = object.__getattribute__(authority.fusion_module, "fuse_rrf")
    if (
        current_fusion is not authority.fusion_method
        or type(current_fusion) is not FunctionType
        or object.__getattribute__(current_fusion, "__code__")
        is not authority.fusion_method_code
        or _function_sha256(current_fusion) != authority.fusion_method_sha256
    ):
        raise ValueError("harness_runtime_method_override")
    if (
        _function_behavior_sha256(current_fusion, recursive=False)
        != authority.fusion_behavior_sha256
    ):
        raise ValueError("harness_runtime_method_override")
    _validate_component_authority(authority.verifier)
    _validate_component_authority(authority.reranker)
    if execution_kind == "synthetic":
        if (
            type(authority.clock) is not FunctionType
            or object.__getattribute__(authority.clock, "__code__")
            is not authority.clock_code
            or _function_sha256(authority.clock)
            != values["clock_implementation_sha256"]
            or _function_behavior_sha256(authority.clock)
            != authority.clock_behavior_sha256
        ):
            raise ValueError("harness_runtime_clock_drift")
    else:
        if authority.clock is not _PRODUCTION_CLOCK:
            raise ValueError("harness_runtime_clock_drift")
        production_runtime_functions = (
            _validated_production_runtime_functions()
        )
        if production_runtime_functions is not authority.production_runtime_functions:
            raise ValueError("harness_runtime_validation_dependency_drift")
        (
            preflight_loaded_dense_artifact,
            require_dense,
            preflight_loaded_lexical_artifact,
            require_lexical,
            preflight_production_hybrid,
            require_hybrid,
        ) = _production_runtime_callables(production_runtime_functions)
        from midprojectrag.retrieval.dense import DenseChildLane
        from midprojectrag.retrieval.kiwi_bm25 import (
            KiwiBM25Lane,
            KiwiTokenizer,
        )
        from midprojectrag.stacks.local.hf_embeddings import KureEmbeddingProvider

        dense_namespace = _instance_dict(authority.dense)
        lexical_namespace = _instance_dict(authority.lexical)
        if (
            authority.dense_class is not DenseChildLane
            or authority.lexical_class is not KiwiBM25Lane
            or "store" not in dense_namespace
            or "provider" not in dense_namespace
            or "store" not in lexical_namespace
            or "tokenizer" not in lexical_namespace
            or dict.__getitem__(dense_namespace, "store") is not store
            or dict.__getitem__(lexical_namespace, "store") is not store
            or type(dict.__getitem__(dense_namespace, "provider"))
            is not KureEmbeddingProvider
            or type(dict.__getitem__(lexical_namespace, "tokenizer"))
            is not KiwiTokenizer
        ):
            raise ValueError("harness_runtime_attestation_drift")
        preflight_dense = preflight_loaded_dense_artifact(
            authority.dense, store, production=True
        )
        preflight_lexical = preflight_loaded_lexical_artifact(
            authority.lexical, store
        )
        preflight_hybrid, _ = preflight_production_hybrid(retriever, store)

    try:
        _ISSUED_VALIDATE_EVIDENCE_STORE_SNAPSHOT(
            store, values["evidence_bundle_sha256"]
        )
    except ValueError as exc:
        raise ValueError("harness_runtime_store_payload_drift") from exc

    if execution_kind == "synthetic":
        if authority.production_runtime_functions is not None:
            raise ValueError("harness_runtime_validation_dependency_drift")
        expected_lanes = _synthetic_lane_payload(
            store=store,
            dense_method=authority.dense_method,
            dense_state_sha256=authority.dense_state_sha256,
            lexical_method=authority.lexical_method,
            lexical_state_sha256=authority.lexical_state_sha256,
            fusion_method=authority.fusion_method,
        )
        if any(values[name] != expected for name, expected in expected_lanes.items()):
            raise ValueError("harness_runtime_authority_drift")
    else:
        try:
            current_hybrid = require_hybrid(retriever, store)
            current_dense = require_dense(
                authority.dense, store, production=True
            )
            current_lexical = require_lexical(
                authority.lexical, store, production=True
            )
        except ValueError as exc:
            raise ValueError("harness_runtime_attestation_drift") from exc
        if (
            current_hybrid is not authority.production_hybrid_binding
            or current_dense is not authority.dense_attestation
            or current_lexical is not authority.lexical_attestation
            or current_hybrid is not preflight_hybrid
            or current_dense is not preflight_dense
            or current_lexical is not preflight_lexical
        ):
            raise ValueError("harness_runtime_attestation_drift")
        expected_runtime = {
            "hybrid_binding_sha256": object.__getattribute__(
                current_hybrid, "binding_sha256"
            ),
            "dense_attestation_sha256": object.__getattribute__(
                current_dense, "attestation_sha256"
            ),
            "dense_artifact_sha256": object.__getattribute__(
                authority.dense, "artifact_sha256"
            ),
            "dense_config_sha256": object.__getattribute__(
                current_dense, "embedding_identity_sha256"
            ),
            "dense_implementation_sha256": authority.dense_method_sha256,
            "lexical_attestation_sha256": object.__getattribute__(
                current_lexical, "attestation_sha256"
            ),
            "lexical_artifact_sha256": object.__getattribute__(
                authority.lexical, "artifact_sha256"
            ),
            "lexical_config_sha256": object.__getattribute__(
                current_lexical, "config_sha256"
            ),
            "lexical_implementation_sha256": authority.lexical_method_sha256,
            "fusion_config_sha256": object.__getattribute__(
                current_hybrid, "fusion_config_sha256"
            ),
            "fusion_implementation_sha256": authority.fusion_method_sha256,
        }
        if any(
            values[name] != expected for name, expected in expected_runtime.items()
        ):
            raise ValueError("harness_runtime_attestation_drift")
    payload = _runtime_payload(binding)
    binding_sha256 = values["binding_sha256"]
    if (
        binding_sha256 != _canonical_sha256(payload)
        or authority.issued_payload_sha256
        != _canonical_sha256({**payload, "binding_sha256": binding_sha256})
    ):
        raise ValueError("harness_runtime_authority_drift")


_ISSUED_REQUIRE_HARNESS_RUNTIME_AUTHORITY = _require_harness_runtime_authority
_ISSUED_VALIDATE_HARNESS_RUNTIME_BINDING = _validate_harness_runtime_binding


def _validate_runtime_gate_dependencies(
    _module_globals=None,
    _function_pins=None,
    _object_pins=None,
    _module_attribute_pins=None,
    _class_pins=None,
    _authority_fields=None,
) -> None:
    """Authenticate validation dependencies without invoking application code."""

    if type(_module_globals) is not dict or globals() is not _module_globals:
        raise ValueError("harness_runtime_validation_dependency_drift")
    if (
        _function_pins
        is not dict.get(_module_globals, "_RUNTIME_GATE_FUNCTION_PINS")
        or _function_pins
        is not dict.get(_module_globals, "_ISSUED_RUNTIME_GATE_FUNCTION_PINS")
        or type(_function_pins) is not tuple
    ):
        raise ValueError("harness_runtime_validation_dependency_drift")
    for entry in _function_pins:
        if type(entry) is not tuple or len(entry) != 8:
            raise ValueError("harness_runtime_validation_dependency_drift")
        (
            name,
            issued,
            code,
            defaults,
            kwdefaults,
            kwdefault_items,
            closure,
            closure_values,
        ) = entry
        current = dict.get(_module_globals, name)
        current_kwdefaults = object.__getattribute__(issued, "__kwdefaults__")
        current_closure = object.__getattribute__(issued, "__closure__")
        if (
            type(name) is not str
            or type(issued) is not FunctionType
            or type(code) is not CodeType
            or current is not issued
            or type(current) is not FunctionType
            or object.__getattribute__(current, "__code__") is not code
            or object.__getattribute__(current, "__defaults__") is not defaults
            or current_closure is not closure
            or current_kwdefaults is not kwdefaults
            or (
                None
                if current_kwdefaults is None
                else tuple(sorted(dict.items(current_kwdefaults)))
            )
            != kwdefault_items
        ):
            raise ValueError("harness_runtime_validation_dependency_drift")
        if current_closure is None:
            if closure_values is not None:
                raise ValueError("harness_runtime_validation_dependency_drift")
        elif (
            type(current_closure) is not tuple
            or type(closure_values) is not tuple
            or len(current_closure) != len(closure_values)
            or any(
                object.__getattribute__(cell, "cell_contents") is not issued_value
                for cell, issued_value in zip(current_closure, closure_values)
            )
        ):
            raise ValueError("harness_runtime_validation_dependency_drift")
    if (
        _object_pins
        is not dict.get(_module_globals, "_RUNTIME_GATE_OBJECT_PINS")
        or _object_pins
        is not dict.get(_module_globals, "_ISSUED_RUNTIME_GATE_OBJECT_PINS")
        or type(_object_pins) is not tuple
    ):
        raise ValueError("harness_runtime_validation_dependency_drift")
    for entry in _object_pins:
        if type(entry) is not tuple or len(entry) != 3:
            raise ValueError("harness_runtime_validation_dependency_drift")
        name, issued, issued_type = entry
        current = dict.get(_module_globals, name)
        if (
            type(name) is not str
            or current is not issued
            or type(current) is not issued_type
        ):
            raise ValueError("harness_runtime_validation_dependency_drift")
    if (
        _module_attribute_pins
        is not dict.get(
            _module_globals, "_RUNTIME_GATE_MODULE_ATTRIBUTE_PINS"
        )
        or _module_attribute_pins
        is not dict.get(
            _module_globals, "_ISSUED_RUNTIME_GATE_MODULE_ATTRIBUTE_PINS"
        )
        or type(_module_attribute_pins) is not tuple
    ):
        raise ValueError("harness_runtime_validation_dependency_drift")
    for entry in _module_attribute_pins:
        if type(entry) is not tuple or len(entry) != 3:
            raise ValueError("harness_runtime_validation_dependency_drift")
        owner, name, issued = entry
        owner_namespace = object.__getattribute__(owner, "__dict__")
        if (
            type(owner_namespace) is not dict
            or type(name) is not str
            or dict.get(owner_namespace, name) is not issued
        ):
            raise ValueError("harness_runtime_validation_dependency_drift")
    if (
        _class_pins is not dict.get(_module_globals, "_RUNTIME_GATE_CLASS_PINS")
        or _class_pins
        is not dict.get(_module_globals, "_ISSUED_RUNTIME_GATE_CLASS_PINS")
        or type(_class_pins) is not tuple
    ):
        raise ValueError("harness_runtime_validation_dependency_drift")
    for entry in _class_pins:
        if type(entry) is not tuple or len(entry) != 4:
            raise ValueError("harness_runtime_validation_dependency_drift")
        owner, issued_getattribute, slot_pins, method_pins = entry
        if type(owner) is not type:
            raise ValueError("harness_runtime_validation_dependency_drift")
        namespace = type.__getattribute__(owner, "__dict__")
        if (
            type(namespace) is not MappingProxyType
            or type.__getattribute__(owner, "__getattribute__")
            is not issued_getattribute
            or type(slot_pins) is not tuple
            or type(method_pins) is not tuple
        ):
            raise ValueError("harness_runtime_validation_dependency_drift")
        for slot_pin in slot_pins:
            if type(slot_pin) is not tuple or len(slot_pin) != 3:
                raise ValueError("harness_runtime_validation_dependency_drift")
            name, descriptor, descriptor_type = slot_pin
            if (
                type(name) is not str
                or namespace.get(name) is not descriptor
                or type(descriptor) is not descriptor_type
            ):
                raise ValueError("harness_runtime_validation_dependency_drift")
        for method_pin in method_pins:
            if type(method_pin) is not tuple or len(method_pin) != 9:
                raise ValueError("harness_runtime_validation_dependency_drift")
            (
                name,
                wrapper_type,
                issued,
                code,
                defaults,
                kwdefaults,
                kwdefault_items,
                closure,
                closure_values,
            ) = method_pin
            current = namespace.get(name)
            if type(current) is classmethod:
                function = object.__getattribute__(current, "__func__")
            else:
                function = current
            current_kwdefaults = (
                None
                if type(function) is not FunctionType
                else object.__getattribute__(function, "__kwdefaults__")
            )
            current_closure = (
                None
                if type(function) is not FunctionType
                else object.__getattribute__(function, "__closure__")
            )
            if (
                type(name) is not str
                or type(current) is not wrapper_type
                or function is not issued
                or type(function) is not FunctionType
                or object.__getattribute__(function, "__code__") is not code
                or object.__getattribute__(function, "__defaults__") is not defaults
                or current_closure is not closure
                or current_kwdefaults is not kwdefaults
                or (
                    None
                    if current_kwdefaults is None
                    else tuple(sorted(dict.items(current_kwdefaults)))
                )
                != kwdefault_items
            ):
                raise ValueError("harness_runtime_validation_dependency_drift")
            if current_closure is None:
                if closure_values is not None:
                    raise ValueError("harness_runtime_validation_dependency_drift")
            elif (
                type(current_closure) is not tuple
                or type(closure_values) is not tuple
                or len(current_closure) != len(closure_values)
                or any(
                    object.__getattribute__(cell, "cell_contents")
                    is not issued_value
                    for cell, issued_value in zip(
                        current_closure, closure_values
                    )
                )
            ):
                raise ValueError("harness_runtime_validation_dependency_drift")
    if (
        _authority_fields is not _RUNTIME_AUTHORITY_DRAFT_FIELDS
        or _authority_fields
        is not dict.get(
            _module_globals, "_ISSUED_RUNTIME_AUTHORITY_DRAFT_FIELDS"
        )
        or type(_authority_fields) is not tuple
    ):
        raise ValueError("harness_runtime_validation_dependency_drift")


_ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER = _validate_runtime_gate_dependencies
_PINNED_RUNTIME_GATE_DEPENDENCY_CHECKER_CODE = (
    _validate_runtime_gate_dependencies.__code__
)


def validate_harness_runtime_binding(
    *,
    binding: HarnessRuntimeBinding,
    store: EvidenceStore,
    expected_execution_kind: str | None = None,
    _dependency_checker=None,
    _dependency_checker_code=None,
) -> None:
    module_namespace = globals()
    checker_defaults = (
        None
        if type(_dependency_checker) is not FunctionType
        else object.__getattribute__(_dependency_checker, "__defaults__")
    )
    if (
        _dependency_checker
        is not dict.get(
            module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER"
        )
        or type(_dependency_checker) is not FunctionType
        or object.__getattribute__(_dependency_checker, "__code__")
        is not _dependency_checker_code
        or _dependency_checker_code
        is not dict.get(
            module_namespace, "_PINNED_RUNTIME_GATE_DEPENDENCY_CHECKER_CODE"
        )
        or checker_defaults
        is not dict.get(
            module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_DEFAULTS"
        )
        or type(checker_defaults) is not tuple
        or len(checker_defaults) != 6
        or tuple.__getitem__(checker_defaults, 0) is not module_namespace
        or object.__getattribute__(_dependency_checker, "__kwdefaults__")
        is not None
    ):
        raise ValueError("harness_runtime_validation_dependency_drift")
    _dependency_checker()
    authority = _ISSUED_REQUIRE_HARNESS_RUNTIME_AUTHORITY(binding)
    _ISSUED_VALIDATE_HARNESS_RUNTIME_BINDING(
        binding=binding,
        authority=authority,
        store=store,
        expected_execution_kind=expected_execution_kind,
    )


_ISSUED_VALIDATE_HARNESS_RUNTIME_BINDING_PUBLIC = (
    validate_harness_runtime_binding
)


# EH2.6.d1 controller-level execution authority.  This is intentionally
# separate from `_RetrievalExecutionLedger`, which owns only b3 lane execution.
_EXECUTION_LEDGER_TOKEN = object()
_HARNESS_EXECUTION_TOKEN = object()
_CONTROLLER_LANES = frozenset({"dense", "lexical"})


def _d1_nonnegative_int(value: object, code: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(code)
    return value


def _d1_hash_tuple(value: object, code: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(code)
    if len(value) != len(set(value)):
        raise ValueError(f"duplicate_{code}")
    for item in value:
        _require_hash(item, code)
    return value


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False, repr=False)
class ExecutionLedger:
    """Immutable controller consumption snapshot; d1 issues revision zero only."""

    stage: str
    execution_identity_sha256: str
    revision: int
    previous_ledger_sha256: str | None
    obligation_keys: tuple[str, ...]
    round_indexes: tuple[int, ...]
    consumed_action_sha256s: tuple[str, ...]
    consumed_lane_keys: tuple[tuple[str, int, str], ...]
    unavailable_action_sha256s: tuple[str, ...]
    nonterminal_action_count: int
    no_progress_streaks: tuple[int, ...]
    ledger_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("execution_ledger_factory_required")

    def __repr__(self) -> str:
        return "ExecutionLedger(<redacted>)"

    def __copy__(self) -> ExecutionLedger:
        raise TypeError("execution_ledger_copy_forbidden")

    def __deepcopy__(self, memo: object) -> ExecutionLedger:
        raise TypeError("execution_ledger_copy_forbidden")

    def __reduce__(self) -> object:
        raise TypeError("execution_ledger_pickle_forbidden")

    def __reduce_ex__(self, protocol: int) -> object:
        raise TypeError("execution_ledger_pickle_forbidden")

    @classmethod
    def _create_initial(
        cls,
        *,
        execution_identity_sha256: str,
        obligation_keys: tuple[str, ...],
        _token: object,
    ) -> ExecutionLedger:
        if _token is not _EXECUTION_LEDGER_TOKEN:
            raise ValueError("execution_ledger_factory_required")
        result = object.__new__(cls)
        object.__setattr__(result, "stage", "execution_ledger")
        object.__setattr__(
            result, "execution_identity_sha256", execution_identity_sha256
        )
        object.__setattr__(result, "revision", 0)
        object.__setattr__(result, "previous_ledger_sha256", None)
        object.__setattr__(result, "obligation_keys", obligation_keys)
        object.__setattr__(
            result, "round_indexes", tuple(0 for _ in obligation_keys)
        )
        object.__setattr__(result, "consumed_action_sha256s", ())
        object.__setattr__(result, "consumed_lane_keys", ())
        object.__setattr__(result, "unavailable_action_sha256s", ())
        object.__setattr__(result, "nonterminal_action_count", 0)
        object.__setattr__(
            result, "no_progress_streaks", tuple(0 for _ in obligation_keys)
        )
        object.__setattr__(result, "ledger_sha256", "0" * 64)
        object.__setattr__(
            result, "ledger_sha256", _canonical_sha256(result._payload())
        )
        result._validate_payload()
        return result

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "stage": self.stage,
            "execution_identity_sha256": self.execution_identity_sha256,
            "revision": self.revision,
            "previous_ledger_sha256": self.previous_ledger_sha256,
            "obligation_keys": list(self.obligation_keys),
            "round_indexes": list(self.round_indexes),
            "consumed_action_sha256s": list(self.consumed_action_sha256s),
            "consumed_lane_keys": [list(value) for value in self.consumed_lane_keys],
            "unavailable_action_sha256s": list(
                self.unavailable_action_sha256s
            ),
            "nonterminal_action_count": self.nonterminal_action_count,
            "no_progress_streaks": list(self.no_progress_streaks),
        }

    def _validate_payload(self) -> None:
        if self.stage != "execution_ledger":
            raise ValueError("invalid_execution_ledger_stage")
        _require_hash(
            self.execution_identity_sha256,
            "invalid_execution_identity_sha256",
        )
        _d1_nonnegative_int(self.revision, "invalid_execution_ledger_revision")
        if self.revision == 0:
            if self.previous_ledger_sha256 is not None:
                raise ValueError("initial_execution_ledger_has_previous")
        else:
            _require_hash(
                self.previous_ledger_sha256,
                "invalid_previous_execution_ledger_sha256",
            )
        if (
            type(self.obligation_keys) is not tuple
            or not self.obligation_keys
            or any(type(value) is not str or not value for value in self.obligation_keys)
            or len(self.obligation_keys) != len(set(self.obligation_keys))
        ):
            raise ValueError("invalid_execution_ledger_obligations")
        for name, values in (
            ("round_indexes", self.round_indexes),
            ("no_progress_streaks", self.no_progress_streaks),
        ):
            if type(values) is not tuple or len(values) != len(self.obligation_keys):
                raise ValueError(f"invalid_execution_ledger_{name}")
            for value in values:
                _d1_nonnegative_int(value, f"invalid_execution_ledger_{name}")
        consumed = _d1_hash_tuple(
            self.consumed_action_sha256s,
            "execution_ledger_consumed_action_sha256s",
        )
        unavailable = _d1_hash_tuple(
            self.unavailable_action_sha256s,
            "execution_ledger_unavailable_action_sha256s",
        )
        if not set(unavailable).issubset(consumed):
            raise ValueError("unavailable_action_not_consumed")
        if type(self.consumed_lane_keys) is not tuple:
            raise TypeError("execution_ledger_consumed_lane_keys")
        if len(self.consumed_lane_keys) != len(set(self.consumed_lane_keys)):
            raise ValueError("duplicate_execution_ledger_consumed_lane_keys")
        obligation_set = set(self.obligation_keys)
        for value in self.consumed_lane_keys:
            if (
                type(value) is not tuple
                or len(value) != 3
                or type(value[0]) is not str
                or value[0] not in obligation_set
                or type(value[1]) is not int
                or value[1] < 1
                or type(value[2]) is not str
                or value[2] not in _CONTROLLER_LANES
            ):
                raise ValueError("invalid_execution_ledger_consumed_lane_key")
        _d1_nonnegative_int(
            self.nonterminal_action_count,
            "invalid_execution_ledger_nonterminal_action_count",
        )
        if self.nonterminal_action_count != len(consumed):
            raise ValueError("execution_ledger_action_count_mismatch")
        _require_hash(self.ledger_sha256, "invalid_execution_ledger_sha256")
        if self.ledger_sha256 != _canonical_sha256(self._payload()):
            raise ValueError("execution_ledger_hash_mismatch")

    def to_dict(self) -> dict[str, Any]:
        self._validate_payload()
        return {**self._payload(), "ledger_sha256": self.ledger_sha256}


class HarnessExecution:
    """Exact live controller aggregate; d1 exposes only the initial snapshot."""

    __slots__ = (
        "stage",
        "execution_identity_sha256",
        "source_kind",
        "source_binding_sha256",
        "source_receipt_sha256",
        "evidence_bundle_sha256",
        "execution_config_sha256",
        "runtime_binding_sha256",
        "initial_state",
        "state",
        "ledger",
        "last_transition_sha256",
        "step_index",
        "execution_snapshot_sha256",
        "__weakref__",
    )

    stage: str
    execution_identity_sha256: str
    source_kind: str
    source_binding_sha256: str
    source_receipt_sha256: str
    evidence_bundle_sha256: str
    execution_config_sha256: str
    runtime_binding_sha256: str
    initial_state: HarnessState
    state: HarnessState
    ledger: ExecutionLedger
    last_transition_sha256: str | None
    step_index: int
    execution_snapshot_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("harness_execution_factory_required")

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("harness_execution_immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("harness_execution_immutable")

    def __repr__(self) -> str:
        return "HarnessExecution(<redacted>)"

    def __copy__(self) -> HarnessExecution:
        raise TypeError("harness_execution_copy_forbidden")

    def __deepcopy__(self, memo: object) -> HarnessExecution:
        raise TypeError("harness_execution_copy_forbidden")

    def __reduce__(self) -> object:
        raise TypeError("harness_execution_pickle_forbidden")

    def __reduce_ex__(self, protocol: int) -> object:
        raise TypeError("harness_execution_pickle_forbidden")

    @classmethod
    def _create_initial(
        cls,
        *,
        execution_identity_sha256: str,
        initial_state: HarnessState,
        ledger: ExecutionLedger,
        config: HarnessExecutionConfig,
        runtime: HarnessRuntimeBinding,
        _token: object,
    ) -> HarnessExecution:
        if _token is not _HARNESS_EXECUTION_TOKEN:
            raise ValueError("harness_execution_factory_required")
        belief = initial_state.belief
        result = object.__new__(cls)
        for name, value in (
            ("stage", "harness_execution"),
            ("execution_identity_sha256", execution_identity_sha256),
            ("source_kind", belief.source_kind),
            ("source_binding_sha256", belief.binding_sha256),
            ("source_receipt_sha256", belief.source_receipt_sha256),
            ("evidence_bundle_sha256", belief.evidence_bundle_sha256),
            ("execution_config_sha256", config.config_sha256),
            ("runtime_binding_sha256", runtime.binding_sha256),
            ("initial_state", initial_state),
            ("state", initial_state),
            ("ledger", ledger),
            ("last_transition_sha256", None),
            ("step_index", 0),
        ):
            object.__setattr__(result, name, value)
        object.__setattr__(result, "execution_snapshot_sha256", "0" * 64)
        object.__setattr__(
            result,
            "execution_snapshot_sha256",
            _canonical_sha256(result._payload()),
        )
        result._validate_payload()
        return result

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "stage": self.stage,
            "execution_identity_sha256": self.execution_identity_sha256,
            "source_kind": self.source_kind,
            "source_binding_sha256": self.source_binding_sha256,
            "source_receipt_sha256": self.source_receipt_sha256,
            "evidence_bundle_sha256": self.evidence_bundle_sha256,
            "execution_config_sha256": self.execution_config_sha256,
            "runtime_binding_sha256": self.runtime_binding_sha256,
            "initial_state_sha256": self.initial_state.state_sha256,
            "state_sha256": self.state.state_sha256,
            "ledger_sha256": self.ledger.ledger_sha256,
            "last_transition_sha256": self.last_transition_sha256,
            "step_index": self.step_index,
        }

    def _validate_payload(self) -> None:
        if self.stage != "harness_execution":
            raise ValueError("invalid_harness_execution_stage")
        if self.source_kind not in {"fact", "compare", "follow_up"}:
            raise ValueError("invalid_harness_execution_source_kind")
        for name in (
            "execution_identity_sha256",
            "source_binding_sha256",
            "source_receipt_sha256",
            "evidence_bundle_sha256",
            "execution_config_sha256",
            "runtime_binding_sha256",
            "execution_snapshot_sha256",
        ):
            _require_hash(getattr(self, name), f"invalid_{name}")
        if type(self.initial_state) is not HarnessState or type(self.state) is not HarnessState:
            raise TypeError("harness_execution_state_required")
        if type(self.ledger) is not ExecutionLedger:
            raise TypeError("harness_execution_ledger_required")
        self.ledger._validate_payload()
        if self.ledger.execution_identity_sha256 != self.execution_identity_sha256:
            raise ValueError("harness_execution_ledger_identity_mismatch")
        if self.ledger.obligation_keys != self.initial_state.progress.required_obligation_keys:
            raise ValueError("harness_execution_obligation_order_mismatch")
        if self.source_kind != self.initial_state.belief.source_kind:
            raise ValueError("harness_execution_source_kind_mismatch")
        if self.source_binding_sha256 != self.initial_state.belief.binding_sha256:
            raise ValueError("harness_execution_source_binding_mismatch")
        if self.source_receipt_sha256 != self.initial_state.belief.source_receipt_sha256:
            raise ValueError("harness_execution_source_receipt_mismatch")
        if self.evidence_bundle_sha256 != self.initial_state.belief.evidence_bundle_sha256:
            raise ValueError("harness_execution_bundle_mismatch")
        _d1_nonnegative_int(self.step_index, "invalid_harness_execution_step_index")
        if self.step_index != self.ledger.revision:
            raise ValueError("harness_execution_step_ledger_mismatch")
        if self.step_index == 0:
            if self.initial_state is not self.state or self.last_transition_sha256 is not None:
                raise ValueError("invalid_initial_harness_execution")
        else:
            _require_hash(
                self.last_transition_sha256,
                "invalid_harness_execution_last_transition_sha256",
            )
        if self.execution_snapshot_sha256 != _canonical_sha256(self._payload()):
            raise ValueError("harness_execution_hash_mismatch")

    def to_dict(self) -> dict[str, Any]:
        self._validate_payload()
        return {
            **self._payload(),
            "execution_snapshot_sha256": self.execution_snapshot_sha256,
        }


def _d1_execution_identity_payload(
    *,
    state: HarnessState,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
) -> dict[str, Any]:
    belief = state.belief
    return {
        "schema_version": SCHEMA_VERSION,
        "authority_kind": "harness_execution_identity",
        "source_kind": belief.source_kind,
        "source_binding_sha256": belief.binding_sha256,
        "source_receipt_sha256": belief.source_receipt_sha256,
        "evidence_bundle_sha256": belief.evidence_bundle_sha256,
        "execution_config_sha256": config.config_sha256,
        "runtime_binding_sha256": runtime.binding_sha256,
        "initial_state_sha256": state.state_sha256,
        "obligation_keys": list(state.progress.required_obligation_keys),
    }


def _build_harness_execution_authority_accessors(
    ledger_cls: type,
    execution_cls: type,
    canonical_sha256: Any,
):
    authority_lock = Lock()
    authorities: dict[int, tuple[Any, ...]] = {}
    authority_shadow: dict[int, tuple[Any, ...]] = {}
    histories: dict[str, tuple[Any, ...]] = {}
    history_shadow: dict[str, tuple[Any, ...]] = {}

    def _drop_execution(identity: int, dead: ReferenceType[Any]) -> None:
        with authority_lock:
            current = authorities.get(identity)
            if current is not None and current[0] is dead:
                authorities.pop(identity, None)
                authority_shadow.pop(identity, None)

    def _drop_root(
        execution_identity_sha256: str,
        dead: ReferenceType[Any],
    ) -> None:
        with authority_lock:
            current = histories.get(execution_identity_sha256)
            if current is not None and current[0] is dead:
                histories.pop(execution_identity_sha256, None)
                history_shadow.pop(execution_identity_sha256, None)

    def issue(
        *,
        execution_identity_sha256: str,
        state: HarnessState,
        store: EvidenceStore,
        config: HarnessExecutionConfig,
        runtime: HarnessRuntimeBinding,
    ) -> HarnessExecution:
        with authority_lock:
            current = histories.get(execution_identity_sha256)
            shadow = history_shadow.get(execution_identity_sha256)
            if (current is None) != (shadow is None) or (
                current is not None and current is not shadow
            ):
                raise ValueError("harness_execution_history_authority_drift")
            if current is not None:
                if (
                    current[0]() is not state
                    or current[1] is not store
                    or current[2] is not config
                    or current[3] is not runtime
                ):
                    raise ValueError("harness_execution_root_identity_mismatch")
                issued = current[4]()
                if issued is None:
                    raise ValueError("harness_execution_already_issued")
                return issued

            ledger = ledger_cls._create_initial(
                execution_identity_sha256=execution_identity_sha256,
                obligation_keys=state.progress.required_obligation_keys,
                _token=_EXECUTION_LEDGER_TOKEN,
            )
            execution = execution_cls._create_initial(
                execution_identity_sha256=execution_identity_sha256,
                initial_state=state,
                ledger=ledger,
                config=config,
                runtime=runtime,
                _token=_HARNESS_EXECUTION_TOKEN,
            )
            execution_identity = id(execution)
            execution_weak = ref(
                execution,
                lambda dead, identity=execution_identity: _drop_execution(
                    identity, dead
                ),
            )
            authority = (
                execution_weak,
                canonical_sha256(execution.to_dict()),
                state,
                state,
                ledger,
                store,
                config,
                runtime,
                None,
                (
                    ledger.obligation_keys,
                    ledger.round_indexes,
                    ledger.consumed_action_sha256s,
                    ledger.consumed_lane_keys,
                    ledger.unavailable_action_sha256s,
                    ledger.no_progress_streaks,
                ),
            )
            authorities[execution_identity] = authority
            authority_shadow[execution_identity] = authority
            state_weak = ref(
                state,
                lambda dead, key=execution_identity_sha256: _drop_root(key, dead),
            )
            history = (state_weak, store, config, runtime, execution_weak)
            histories[execution_identity_sha256] = history
            history_shadow[execution_identity_sha256] = history
            return execution

    def require(execution: object) -> tuple[Any, ...]:
        with authority_lock:
            identity = id(execution)
            current = authorities.get(identity)
            shadow = authority_shadow.get(identity)
            if (
                current is None
                or current is not shadow
                or current[0]() is not execution
            ):
                raise ValueError("harness_execution_runtime_authority_required")
            history = histories.get(execution.execution_identity_sha256)
            if history is None or history is not history_shadow.get(
                execution.execution_identity_sha256
            ):
                raise ValueError("harness_execution_history_authority_drift")
            if history[0]() is not current[2] or history[4]() is not execution:
                raise ValueError("harness_execution_history_authority_drift")
            return current

    return issue, require


(
    _issue_harness_execution_authority,
    _require_harness_execution_authority,
) = _build_harness_execution_authority_accessors(
    ExecutionLedger,
    HarnessExecution,
    _canonical_sha256,
)
del _build_harness_execution_authority_accessors


def _build_harness_execution_public_api(
    *,
    ledger_cls: type,
    execution_cls: type,
    state_cls: type,
    store_cls: type,
    config_cls: type,
    runtime_cls: type,
    state_validator: Any,
    config_validator: Any,
    runtime_validator: Any,
    identity_payload: Any,
    canonical_sha256: Any,
    authority_issuer: Any,
    authority_reader: Any,
):
    d1_global_pins = (
        ("SCHEMA_VERSION", SCHEMA_VERSION),
        ("_CONTROLLER_LANES", _CONTROLLER_LANES),
        ("_EXECUTION_LEDGER_TOKEN", _EXECUTION_LEDGER_TOKEN),
        ("_HARNESS_EXECUTION_TOKEN", _HARNESS_EXECUTION_TOKEN),
        ("_require_hash", _require_hash),
        ("_d1_nonnegative_int", _d1_nonnegative_int),
        ("_d1_hash_tuple", _d1_hash_tuple),
        ("ref", ref),
    )
    callable_pins = tuple(
        (
            function,
            object.__getattribute__(function, "__code__"),
            object.__getattribute__(function, "__defaults__"),
            object.__getattribute__(function, "__kwdefaults__"),
        )
        for function in (
            state_validator,
            config_validator,
            runtime_validator,
            identity_payload,
            canonical_sha256,
            authority_issuer,
            authority_reader,
            _require_hash,
            _d1_nonnegative_int,
            _d1_hash_tuple,
        )
    )
    class_pins = []
    for owner in (ledger_cls, execution_cls):
        namespace = type.__getattribute__(owner, "__dict__")
        members = []
        for name in sorted(namespace):
            member = namespace[name]
            function = None
            if type(member) is FunctionType:
                function = member
            elif type(member) in {classmethod, staticmethod}:
                function = object.__getattribute__(member, "__func__")
            members.append(
                (
                    name,
                    member,
                    type(member),
                    None
                    if function is None
                    else (
                        function,
                        object.__getattribute__(function, "__code__"),
                        object.__getattribute__(function, "__defaults__"),
                        object.__getattribute__(function, "__kwdefaults__"),
                    ),
                )
            )
        class_pins.append((owner, tuple(members)))
    class_pins = tuple(class_pins)

    def validate_dependencies() -> None:
        module = globals()
        for name, issued in d1_global_pins:
            if module.get(name) is not issued:
                raise ValueError("harness_execution_dependency_drift")
        for name, issued in (
            ("ExecutionLedger", ledger_cls),
            ("HarnessExecution", execution_cls),
            ("HarnessState", state_cls),
            ("EvidenceStore", store_cls),
            ("HarnessExecutionConfig", config_cls),
            ("HarnessRuntimeBinding", runtime_cls),
            ("validate_harness_state", state_validator),
            ("validate_harness_execution_config", config_validator),
            ("validate_harness_runtime_binding", runtime_validator),
            ("_d1_execution_identity_payload", identity_payload),
            ("_canonical_sha256", canonical_sha256),
            ("_issue_harness_execution_authority", authority_issuer),
            ("_require_harness_execution_authority", authority_reader),
        ):
            if module.get(name) is not issued:
                raise ValueError("harness_execution_dependency_drift")
        for function, code, defaults, kwdefaults in callable_pins:
            if (
                object.__getattribute__(function, "__code__") is not code
                or object.__getattribute__(function, "__defaults__") is not defaults
                or object.__getattribute__(function, "__kwdefaults__")
                is not kwdefaults
            ):
                raise ValueError("harness_execution_dependency_drift")
        for owner, members in class_pins:
            namespace = type.__getattribute__(owner, "__dict__")
            if tuple(sorted(namespace)) != tuple(value[0] for value in members):
                raise ValueError("harness_execution_dependency_drift")
            for name, issued, issued_type, function_pin in members:
                current = namespace.get(name)
                if current is not issued or type(current) is not issued_type:
                    raise ValueError("harness_execution_dependency_drift")
                if function_pin is not None:
                    function = (
                        current
                        if type(current) is FunctionType
                        else object.__getattribute__(current, "__func__")
                    )
                    if (
                        function is not function_pin[0]
                        or object.__getattribute__(function, "__code__")
                        is not function_pin[1]
                        or object.__getattribute__(function, "__defaults__")
                        is not function_pin[2]
                        or object.__getattribute__(function, "__kwdefaults__")
                        is not function_pin[3]
                    ):
                        raise ValueError("harness_execution_dependency_drift")

    def issue_harness_execution(
        *,
        state: HarnessState,
        store: EvidenceStore,
        config: HarnessExecutionConfig,
        runtime: HarnessRuntimeBinding,
    ) -> HarnessExecution:
        """Seal one zero-consumption E1 aggregate without executing work."""

        validate_dependencies()
        if type(state) is not state_cls:
            raise TypeError("harness_state_required")
        if type(store) is not store_cls:
            raise TypeError("evidence_store_required")
        if type(config) is not config_cls:
            raise TypeError("harness_execution_config_required")
        if type(runtime) is not runtime_cls:
            raise TypeError("harness_runtime_binding_required")
        state_validator(state=state, store=store)
        if state.belief.source_kind == "compare" and any(
            entry.observation_stage != "unsearched"
            for entry in state.belief.evidence_map
        ):
            raise ValueError("e1_compare_seed_not_unsearched")
        config_validator(config)
        if config.mode != "e1_bounded":
            raise ValueError("e1_bounded_execution_config_required")
        runtime_validator(binding=runtime, store=store)
        if state.belief.evidence_bundle_sha256 != runtime.evidence_bundle_sha256:
            raise ValueError("harness_execution_runtime_bundle_mismatch")
        execution_identity_sha256 = canonical_sha256(
            identity_payload(state=state, config=config, runtime=runtime)
        )
        execution = authority_issuer(
            execution_identity_sha256=execution_identity_sha256,
            state=state,
            store=store,
            config=config,
            runtime=runtime,
        )
        validate_harness_execution(
            execution=execution,
            store=store,
            config=config,
            runtime=runtime,
        )
        return execution

    def validate_harness_execution(
        *,
        execution: HarnessExecution,
        store: EvidenceStore,
        config: HarnessExecutionConfig,
        runtime: HarnessRuntimeBinding,
    ) -> None:
        """Require the exact unchanged d1 aggregate and dependency graph."""

        validate_dependencies()
        if type(execution) is not execution_cls:
            raise TypeError("harness_execution_required")
        if type(store) is not store_cls:
            raise TypeError("evidence_store_required")
        if type(config) is not config_cls:
            raise TypeError("harness_execution_config_required")
        if type(runtime) is not runtime_cls:
            raise TypeError("harness_runtime_binding_required")
        authority = authority_reader(execution)
        if (
            authority[2] is not execution.initial_state
            or authority[3] is not execution.state
            or authority[4] is not execution.ledger
            or authority[5] is not store
            or authority[6] is not config
            or authority[7] is not runtime
            or authority[8] is not None
            or any(
                issued is not actual
                for issued, actual in zip(
                    authority[9],
                    (
                        execution.ledger.obligation_keys,
                        execution.ledger.round_indexes,
                        execution.ledger.consumed_action_sha256s,
                        execution.ledger.consumed_lane_keys,
                        execution.ledger.unavailable_action_sha256s,
                        execution.ledger.no_progress_streaks,
                    ),
                )
            )
        ):
            raise ValueError("harness_execution_nested_identity_drift")
        state_validator(state=execution.initial_state, store=store)
        if execution.state is not execution.initial_state:
            state_validator(state=execution.state, store=store)
        config_validator(config)
        if config.mode != "e1_bounded":
            raise ValueError("e1_bounded_execution_config_required")
        runtime_validator(binding=runtime, store=store)
        execution._validate_payload()
        ledger = execution.ledger
        if any(
            value > config.max_retrieval_rounds_per_obligation
            for value in ledger.round_indexes
        ):
            raise ValueError("execution_ledger_round_budget_exceeded")
        if any(
            value > config.max_no_progress_per_obligation
            for value in ledger.no_progress_streaks
        ):
            raise ValueError("execution_ledger_no_progress_budget_exceeded")
        if ledger.nonterminal_action_count > config.max_nonterminal_actions:
            raise ValueError("execution_ledger_action_budget_exceeded")
        expected_identity = canonical_sha256(
            identity_payload(
                state=execution.initial_state,
                config=config,
                runtime=runtime,
            )
        )
        if execution.execution_identity_sha256 != expected_identity:
            raise ValueError("harness_execution_identity_mismatch")
        if authority[1] != canonical_sha256(execution.to_dict()):
            raise ValueError("harness_execution_runtime_authority_drift")

    issue_harness_execution.__name__ = "issue_harness_execution"
    issue_harness_execution.__qualname__ = "issue_harness_execution"
    validate_harness_execution.__name__ = "validate_harness_execution"
    validate_harness_execution.__qualname__ = "validate_harness_execution"
    return issue_harness_execution, validate_harness_execution


(
    issue_harness_execution,
    validate_harness_execution,
) = _build_harness_execution_public_api(
    ledger_cls=ExecutionLedger,
    execution_cls=HarnessExecution,
    state_cls=HarnessState,
    store_cls=EvidenceStore,
    config_cls=HarnessExecutionConfig,
    runtime_cls=HarnessRuntimeBinding,
    state_validator=validate_harness_state,
    config_validator=validate_harness_execution_config,
    runtime_validator=validate_harness_runtime_binding,
    identity_payload=_d1_execution_identity_payload,
    canonical_sha256=_canonical_sha256,
    authority_issuer=_issue_harness_execution_authority,
    authority_reader=_require_harness_execution_authority,
)
del _build_harness_execution_public_api


_RETRIEVAL_OBLIGATION_TOKEN = object()
_LANE_SEARCH_RECEIPT_TOKEN = object()
_FUSION_RECEIPT_TOKEN = object()
_E0_CONTROL_RECEIPT_TOKEN = object()
_RETRIEVAL_LEDGER_TOKEN = object()
_LOCK_TYPE = type(Lock())
_RETRIEVAL_SOURCE_KINDS = frozenset({"fact", "compare"})
_RETRIEVAL_LANES = frozenset({"dense", "lexical"})
_LANE_OUTCOMES = frozenset(
    {"applied", "empty", "provider_error", "contract_error"}
)
_LANE_ERROR_CODES = frozenset(
    {
        "none",
        "lane_provider_error",
        "lane_dispatch_contract_error",
        "lane_post_call_contract_error",
        "lane_result_contract_error",
    }
)
_FUSION_OUTCOMES = frozenset({"applied", "empty"})
_E0_STATUSES = frozenset({"retrieved", "empty", "unavailable", "error"})
_E0_ERROR_CODES = frozenset(
    {
        "none",
        "capability_unavailable",
        "lane_provider_error",
        "lane_dispatch_contract_error",
        "lane_post_call_contract_error",
        "lane_result_contract_error",
        "fusion_contract_error",
        "execution_terminated_before_obligation",
    }
)


def _exact_string_tuple(value: object) -> bool:
    return type(value) is tuple and all(
        type(item) is str and bool(item) for item in value
    )


def _query_sha256(query: str) -> str:
    if type(query) is not str or not query.strip():
        raise ValueError("invalid_retrieval_query")
    return sha256(query.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class StableEvidenceAnchor:
    """Store evidence locator plus chunk-invariant source-block join keys."""

    doc_id: str
    source_block_ids: tuple[str, ...]
    source_block_anchor_sha256s: tuple[str, ...]
    evidence_kind: str
    locator_identity_sha256: str
    anchor_sha256: str

    def __post_init__(self) -> None:
        if type(self.doc_id) is not str or not self.doc_id:
            raise ValueError("invalid_stable_anchor_doc_id")
        if not _exact_string_tuple(self.source_block_ids):
            raise ValueError("invalid_stable_anchor_source_blocks")
        if (
            type(self.source_block_anchor_sha256s) is not tuple
            or len(self.source_block_anchor_sha256s)
            != len(self.source_block_ids)
        ):
            raise ValueError("invalid_stable_source_block_anchors")
        for source_block_id, source_anchor_sha256 in zip(
            self.source_block_ids,
            self.source_block_anchor_sha256s,
        ):
            _require_hash(
                source_anchor_sha256,
                "invalid_stable_source_block_anchor_hash",
            )
            if source_anchor_sha256 != _canonical_sha256(
                {
                    "schema_version": SCHEMA_VERSION,
                    "anchor_kind": "source_block",
                    "doc_id": self.doc_id,
                    "source_block_id": source_block_id,
                }
            ):
                raise ValueError("stable_source_block_anchor_hash_mismatch")
        if type(self.evidence_kind) is not str or not self.evidence_kind:
            raise ValueError("invalid_stable_anchor_kind")
        _require_hash(
            self.locator_identity_sha256,
            "invalid_stable_anchor_locator_hash",
        )
        _require_hash(self.anchor_sha256, "invalid_stable_anchor_hash")
        if self.anchor_sha256 != _canonical_sha256(self._payload()):
            raise ValueError("stable_anchor_hash_mismatch")

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "doc_id": self.doc_id,
            "source_block_ids": list(self.source_block_ids),
            "source_block_anchor_sha256s": list(
                self.source_block_anchor_sha256s
            ),
            "evidence_kind": self.evidence_kind,
            "locator_identity_sha256": self.locator_identity_sha256,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "anchor_sha256": self.anchor_sha256}


def _stable_anchor(evidence: object) -> StableEvidenceAnchor:
    try:
        doc_id = object.__getattribute__(evidence, "doc_id")
        source_block_ids = object.__getattribute__(evidence, "source_block_ids")
        evidence_kind = object.__getattribute__(evidence, "kind")
        locator = object.__getattribute__(evidence, "locator")
        locator_payload = {
            "page": object.__getattribute__(locator, "page"),
            "flow_id": object.__getattribute__(locator, "flow_id"),
            "section_path": list(
                object.__getattribute__(locator, "section_path")
            ),
            "object_id": object.__getattribute__(locator, "object_id"),
            "bbox": (
                None
                if object.__getattribute__(locator, "bbox") is None
                else list(object.__getattribute__(locator, "bbox"))
            ),
            "row_range": (
                None
                if object.__getattribute__(locator, "row_range") is None
                else list(object.__getattribute__(locator, "row_range"))
            ),
            "char_range": (
                None
                if object.__getattribute__(locator, "char_range") is None
                else list(object.__getattribute__(locator, "char_range"))
            ),
        }
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("invalid_retrieval_evidence_anchor") from exc
    locator_identity_sha256 = _canonical_sha256(locator_payload)
    source_block_anchor_sha256s = tuple(
        _canonical_sha256(
            {
                "schema_version": SCHEMA_VERSION,
                "anchor_kind": "source_block",
                "doc_id": doc_id,
                "source_block_id": source_block_id,
            }
        )
        for source_block_id in source_block_ids
    )
    base = {
        "schema_version": SCHEMA_VERSION,
        "doc_id": doc_id,
        "source_block_ids": list(source_block_ids),
        "source_block_anchor_sha256s": list(
            source_block_anchor_sha256s
        ),
        "evidence_kind": evidence_kind,
        "locator_identity_sha256": locator_identity_sha256,
    }
    return StableEvidenceAnchor(
        doc_id=doc_id,
        source_block_ids=source_block_ids,
        source_block_anchor_sha256s=source_block_anchor_sha256s,
        evidence_kind=evidence_kind,
        locator_identity_sha256=locator_identity_sha256,
        anchor_sha256=_canonical_sha256(base),
    )


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class RetrievalObligation:
    source_kind: str
    obligation_key: str
    ordinal: int
    obligation_count: int
    execution_kind: str
    execution_binding_sha256: str
    source_receipt_sha256: str
    query_sha256: str
    scope_state: str
    scope_origin: str
    scope_doc_ids: tuple[str, ...]
    scope_sha256: str
    dense_k: int
    lexical_k: int
    round_index: int
    evidence_store_sha256: str
    execution_config_sha256: str
    runtime_binding_sha256: str
    obligation_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("retrieval_obligation_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        payload: Mapping[str, Any],
        _token: object,
    ) -> RetrievalObligation:
        if _token is not _RETRIEVAL_OBLIGATION_TOKEN:
            raise ValueError("retrieval_obligation_factory_required")
        result = object.__new__(cls)
        for name in cls.__slots__:
            if name != "__weakref__":
                object.__setattr__(result, name, payload[name])
        _validate_retrieval_obligation_payload(result)
        return result

    def to_dict(self) -> dict[str, Any]:
        _validate_retrieval_obligation_payload(self)
        return _retrieval_obligation_payload(self, include_hash=True)


def _retrieval_obligation_payload(
    obligation: RetrievalObligation,
    *,
    include_hash: bool,
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "source_kind": object.__getattribute__(obligation, "source_kind"),
        "obligation_key": object.__getattribute__(obligation, "obligation_key"),
        "ordinal": object.__getattribute__(obligation, "ordinal"),
        "obligation_count": object.__getattribute__(obligation, "obligation_count"),
        "execution_kind": object.__getattribute__(obligation, "execution_kind"),
        "execution_binding_sha256": object.__getattribute__(
            obligation, "execution_binding_sha256"
        ),
        "source_receipt_sha256": object.__getattribute__(
            obligation, "source_receipt_sha256"
        ),
        "query_sha256": object.__getattribute__(obligation, "query_sha256"),
        "scope_state": object.__getattribute__(obligation, "scope_state"),
        "scope_origin": object.__getattribute__(obligation, "scope_origin"),
        "scope_doc_ids": list(
            object.__getattribute__(obligation, "scope_doc_ids")
        ),
        "scope_sha256": object.__getattribute__(obligation, "scope_sha256"),
        "dense_k": object.__getattribute__(obligation, "dense_k"),
        "lexical_k": object.__getattribute__(obligation, "lexical_k"),
        "round_index": object.__getattribute__(obligation, "round_index"),
        "evidence_store_sha256": object.__getattribute__(
            obligation, "evidence_store_sha256"
        ),
        "execution_config_sha256": object.__getattribute__(
            obligation, "execution_config_sha256"
        ),
        "runtime_binding_sha256": object.__getattribute__(
            obligation, "runtime_binding_sha256"
        ),
    }
    if include_hash:
        payload["obligation_sha256"] = object.__getattribute__(
            obligation, "obligation_sha256"
        )
    return payload


def _validate_retrieval_obligation_payload(
    obligation: RetrievalObligation,
) -> None:
    if type(obligation) is not RetrievalObligation:
        raise TypeError("retrieval_obligation_required")
    source_kind = object.__getattribute__(obligation, "source_kind")
    if type(source_kind) is not str or source_kind not in _RETRIEVAL_SOURCE_KINDS:
        raise ValueError("invalid_retrieval_obligation_source")
    for name in ("obligation_key", "scope_origin"):
        value = object.__getattribute__(obligation, name)
        if type(value) is not str or not value:
            raise ValueError("invalid_retrieval_obligation_identity")
    ordinal = object.__getattribute__(obligation, "ordinal")
    count = object.__getattribute__(obligation, "obligation_count")
    if (
        type(ordinal) is not int
        or type(count) is not int
        or ordinal < 1
        or count < ordinal
    ):
        raise ValueError("invalid_retrieval_obligation_ordinal")
    execution_kind = object.__getattribute__(obligation, "execution_kind")
    if type(execution_kind) is not str or execution_kind not in {
        "production",
        "synthetic",
    }:
        raise ValueError("invalid_retrieval_obligation_execution_kind")
    scope_state = object.__getattribute__(obligation, "scope_state")
    scope_doc_ids = object.__getattribute__(obligation, "scope_doc_ids")
    if (
        type(scope_state) is not str
        or scope_state not in {"unfiltered", "restricted"}
        or not _exact_string_tuple(scope_doc_ids)
        or (scope_state == "restricted") != bool(scope_doc_ids)
        or len(scope_doc_ids) != len(set(scope_doc_ids))
    ):
        raise ValueError("invalid_retrieval_obligation_scope")
    for name in ("dense_k", "lexical_k"):
        value = object.__getattribute__(obligation, name)
        if type(value) is not int or value < 1:
            raise ValueError("invalid_retrieval_obligation_budget")
    if object.__getattribute__(obligation, "round_index") != 1:
        raise ValueError("invalid_retrieval_obligation_round")
    for name in (
        "execution_binding_sha256",
        "source_receipt_sha256",
        "query_sha256",
        "scope_sha256",
        "evidence_store_sha256",
        "execution_config_sha256",
        "runtime_binding_sha256",
        "obligation_sha256",
    ):
        _require_hash(
            object.__getattribute__(obligation, name),
            f"invalid_{name}",
        )
    expected_scope_sha256 = _canonical_sha256(
        {
            "schema_version": SCHEMA_VERSION,
            "state": scope_state,
            "origin": object.__getattribute__(obligation, "scope_origin"),
            "doc_ids": list(scope_doc_ids),
        }
    )
    if object.__getattribute__(obligation, "scope_sha256") != expected_scope_sha256:
        raise ValueError("retrieval_obligation_scope_hash_mismatch")
    if object.__getattribute__(obligation, "obligation_sha256") != _canonical_sha256(
        _retrieval_obligation_payload(obligation, include_hash=False)
    ):
        raise ValueError("retrieval_obligation_hash_mismatch")


@dataclass(frozen=True, slots=True)
class _RetrievalLedgerAuthority:
    ledger_weak: ReferenceType[object]
    state_sha256: str
    revision: int


_RETRIEVAL_LEDGER_AUTHORITIES: dict[int, _RetrievalLedgerAuthority] = {}
_ISSUED_RETRIEVAL_LEDGER_AUTHORITIES = _RETRIEVAL_LEDGER_AUTHORITIES


def _build_retrieval_ledger_authority_accessors(
    visible: dict[int, _RetrievalLedgerAuthority],
) -> tuple[FunctionType, FunctionType, FunctionType, FunctionType]:
    """Keep an immutable, closure-private mirror of the public audit registry."""

    shadow: dict[int, tuple[ReferenceType[object], str, int]] = {}
    authority_lock = Lock()

    def _drop_when_dead(identity: int, dead: ReferenceType[object]) -> None:
        with authority_lock:
            sealed = dict.get(shadow, identity)
            if (
                type(sealed) is tuple
                and len(sealed) == 3
                and tuple.__getitem__(sealed, 0) is dead
            ):
                dict.pop(visible, identity, None)
                dict.pop(shadow, identity, None)

    def _validated_unlocked(ledger: object) -> _RetrievalLedgerAuthority | None:
        identity = id(ledger)
        current = dict.get(visible, identity)
        sealed = dict.get(shadow, identity)
        if current is None and sealed is None:
            return None
        if (
            type(current) is not _RetrievalLedgerAuthority
            or type(sealed) is not tuple
            or len(sealed) != 3
            or object.__getattribute__(current, "ledger_weak")
            is not tuple.__getitem__(sealed, 0)
            or tuple.__getitem__(sealed, 0)() is not ledger
            or object.__getattribute__(current, "state_sha256")
            != tuple.__getitem__(sealed, 1)
            or object.__getattribute__(current, "revision")
            != tuple.__getitem__(sealed, 2)
        ):
            raise ValueError("retrieval_execution_ledger_authority_drift")
        return current

    def register(
        ledger: object,
        state_sha256: str,
        revision: int,
    ) -> _RetrievalLedgerAuthority:
        with authority_lock:
            if _validated_unlocked(ledger) is not None:
                raise ValueError("retrieval_execution_ledger_authority_drift")
            ledger_weak = ref(
                ledger,
                lambda dead, identity=id(ledger): _drop_when_dead(
                    identity, dead
                ),
            )
            authority = _RetrievalLedgerAuthority(
                ledger_weak=ledger_weak,
                state_sha256=state_sha256,
                revision=revision,
            )
            identity = id(ledger)
            dict.__setitem__(visible, identity, authority)
            dict.__setitem__(
                shadow,
                identity,
                (ledger_weak, state_sha256, revision),
            )
            return authority

    def read(ledger: object) -> _RetrievalLedgerAuthority:
        with authority_lock:
            current = _validated_unlocked(ledger)
            if current is None:
                raise ValueError("retrieval_execution_ledger_authority_drift")
            return current

    def replace(
        ledger: object,
        expected_state_sha256: str,
        expected_revision: int,
        state_sha256: str,
        revision: int,
    ) -> _RetrievalLedgerAuthority:
        with authority_lock:
            current = _validated_unlocked(ledger)
            if (
                current is None
                or object.__getattribute__(current, "state_sha256")
                != expected_state_sha256
                or object.__getattribute__(current, "revision")
                != expected_revision
            ):
                raise ValueError("retrieval_execution_ledger_authority_drift")
            ledger_weak = object.__getattribute__(current, "ledger_weak")
            authority = _RetrievalLedgerAuthority(
                ledger_weak=ledger_weak,
                state_sha256=state_sha256,
                revision=revision,
            )
            identity = id(ledger)
            dict.__setitem__(visible, identity, authority)
            dict.__setitem__(
                shadow,
                identity,
                (ledger_weak, state_sha256, revision),
            )
            return authority

    def unregister(ledger: object) -> None:
        with authority_lock:
            if _validated_unlocked(ledger) is None:
                raise ValueError("retrieval_execution_ledger_authority_drift")
            identity = id(ledger)
            dict.pop(visible, identity)
            dict.pop(shadow, identity)

    return register, read, replace, unregister


(
    _register_retrieval_ledger_authority,
    _read_retrieval_ledger_authority,
    _replace_retrieval_ledger_authority,
    _unregister_retrieval_ledger_authority,
) = _build_retrieval_ledger_authority_accessors(
    _ISSUED_RETRIEVAL_LEDGER_AUTHORITIES
)


class _RetrievalExecutionLedger:
    """Monotonic exact-once ledger shared by one issued obligation set."""

    __slots__ = (
        "_obligation_sha256s",
        "_claimed",
        "_closed",
        "_dense_provider_failed",
        "_status",
        "_revision",
        "_previous_state_sha256",
        "_state_sha256",
        "_lock",
        "__weakref__",
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("retrieval_execution_ledger_factory_required")

    @classmethod
    def _create(
        cls,
        obligation_sha256s: tuple[str, ...],
        *,
        _token: object,
    ) -> _RetrievalExecutionLedger:
        if _token is not _RETRIEVAL_LEDGER_TOKEN:
            raise ValueError("retrieval_execution_ledger_factory_required")
        if (
            type(obligation_sha256s) is not tuple
            or not obligation_sha256s
            or len(obligation_sha256s) != len(set(obligation_sha256s))
        ):
            raise ValueError("invalid_retrieval_execution_ledger")
        for value in obligation_sha256s:
            _require_hash(value, "invalid_retrieval_execution_ledger")
        result = object.__new__(cls)
        object.__setattr__(result, "_obligation_sha256s", obligation_sha256s)
        object.__setattr__(result, "_claimed", frozenset())
        object.__setattr__(result, "_closed", frozenset())
        object.__setattr__(result, "_dense_provider_failed", frozenset())
        object.__setattr__(result, "_status", "active")
        object.__setattr__(result, "_revision", 0)
        object.__setattr__(result, "_previous_state_sha256", "0" * 64)
        object.__setattr__(result, "_state_sha256", "0" * 64)
        object.__setattr__(result, "_lock", Lock())
        object.__setattr__(
            result,
            "_state_sha256",
            _canonical_sha256(result._state_payload()),
        )
        _register_retrieval_ledger_authority(
            result,
            object.__getattribute__(result, "_state_sha256"),
            0,
        )
        result._validate()
        return result

    def _state_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "obligation_sha256s": list(
                object.__getattribute__(self, "_obligation_sha256s")
            ),
            "claimed": [
                list(pair)
                for pair in sorted(object.__getattribute__(self, "_claimed"))
            ],
            "closed": [
                list(pair)
                for pair in sorted(object.__getattribute__(self, "_closed"))
            ],
            "dense_provider_failed": sorted(
                object.__getattribute__(self, "_dense_provider_failed")
            ),
            "status": object.__getattribute__(self, "_status"),
            "revision": object.__getattribute__(self, "_revision"),
            "previous_state_sha256": object.__getattribute__(
                self, "_previous_state_sha256"
            ),
        }

    def _advance(
        self,
        *,
        claimed: frozenset[tuple[str, str]],
        closed: frozenset[tuple[str, str]],
        dense_provider_failed: frozenset[str],
        status: str,
    ) -> str:
        self._validate()
        current = object.__getattribute__(self, "_state_sha256")
        object.__setattr__(self, "_claimed", claimed)
        object.__setattr__(self, "_closed", closed)
        object.__setattr__(
            self, "_dense_provider_failed", dense_provider_failed
        )
        object.__setattr__(self, "_status", status)
        object.__setattr__(self, "_previous_state_sha256", current)
        object.__setattr__(
            self,
            "_revision",
            object.__getattribute__(self, "_revision") + 1,
        )
        updated = _canonical_sha256(self._state_payload())
        object.__setattr__(self, "_state_sha256", updated)
        _replace_retrieval_ledger_authority(
            self,
            current,
            object.__getattribute__(self, "_revision") - 1,
            updated,
            object.__getattribute__(self, "_revision"),
        )
        return updated

    def _validate(self) -> None:
        obligation_sha256s = object.__getattribute__(
            self, "_obligation_sha256s"
        )
        claimed = object.__getattribute__(self, "_claimed")
        closed = object.__getattribute__(self, "_closed")
        dense_provider_failed = object.__getattribute__(
            self, "_dense_provider_failed"
        )
        status = object.__getattribute__(self, "_status")
        revision = object.__getattribute__(self, "_revision")
        previous_state_sha256 = object.__getattribute__(
            self, "_previous_state_sha256"
        )
        state_sha256 = object.__getattribute__(self, "_state_sha256")
        lock = object.__getattribute__(self, "_lock")
        allowed = frozenset(
            (obligation_sha256, lane)
            for obligation_sha256 in obligation_sha256s
            for lane in _RETRIEVAL_LANES
        )
        if (
            type(obligation_sha256s) is not tuple
            or not obligation_sha256s
            or len(obligation_sha256s) != len(set(obligation_sha256s))
            or type(claimed) is not frozenset
            or type(closed) is not frozenset
            or type(dense_provider_failed) is not frozenset
            or not closed.issubset(claimed)
            or not claimed.issubset(allowed)
            or not dense_provider_failed.issubset(
                frozenset(obligation_sha256s)
            )
            or any(
                (obligation_sha256, "dense") not in closed
                for obligation_sha256 in dense_provider_failed
            )
            or type(status) is not str
            or status not in {"active", "terminated"}
            or type(revision) is not int
            or revision < 0
            or revision != len(claimed) + len(closed)
            or type(lock) is not _LOCK_TYPE
        ):
            raise ValueError("retrieval_execution_ledger_drift")
        _require_hash(
            previous_state_sha256, "retrieval_execution_ledger_drift"
        )
        _require_hash(state_sha256, "retrieval_execution_ledger_drift")
        if state_sha256 != _canonical_sha256(self._state_payload()):
            raise ValueError("retrieval_execution_ledger_hash_mismatch")
        authority = _read_retrieval_ledger_authority(self)
        if (
            type(authority) is not _RetrievalLedgerAuthority
            or object.__getattribute__(authority, "ledger_weak")() is not self
            or object.__getattribute__(authority, "state_sha256")
            != state_sha256
            or object.__getattribute__(authority, "revision") != revision
        ):
            raise ValueError("retrieval_execution_ledger_authority_drift")

    def _expected_pair(self) -> tuple[str, str] | None:
        closed = object.__getattribute__(self, "_closed")
        for obligation_sha256 in object.__getattribute__(
            self, "_obligation_sha256s"
        ):
            dense = (obligation_sha256, "dense")
            if dense not in closed:
                return dense
            lexical = (obligation_sha256, "lexical")
            if lexical not in closed:
                return lexical
        return None

    def _precheck(self, obligation_sha256: str, lane: str) -> None:
        with object.__getattribute__(self, "_lock"):
            self._validate()
            pair = (obligation_sha256, lane)
            if obligation_sha256 not in object.__getattribute__(
                self, "_obligation_sha256s"
            ) or lane not in _RETRIEVAL_LANES:
                raise ValueError("retrieval_execution_ledger_mismatch")
            if object.__getattribute__(self, "_status") != "active":
                raise ValueError("retrieval_execution_terminated")
            claimed = object.__getattribute__(self, "_claimed")
            if pair in claimed:
                raise ValueError("retrieval_lane_already_consumed")
            if pair != self._expected_pair():
                raise ValueError("retrieval_lane_order_violation")

    def _claim(self, obligation_sha256: str, lane: str) -> None:
        with object.__getattribute__(self, "_lock"):
            self._validate()
            pair = (obligation_sha256, lane)
            if obligation_sha256 not in object.__getattribute__(
                self, "_obligation_sha256s"
            ) or lane not in _RETRIEVAL_LANES:
                raise ValueError("retrieval_execution_ledger_mismatch")
            if object.__getattribute__(self, "_status") != "active":
                raise ValueError("retrieval_execution_terminated")
            claimed = object.__getattribute__(self, "_claimed")
            if pair in claimed:
                raise ValueError("retrieval_lane_already_consumed")
            if pair != self._expected_pair():
                raise ValueError("retrieval_lane_order_violation")
            self._advance(
                claimed=claimed | {pair},
                closed=object.__getattribute__(self, "_closed"),
                dense_provider_failed=object.__getattribute__(
                    self, "_dense_provider_failed"
                ),
                status=object.__getattribute__(self, "_status"),
            )

    def _close(
        self,
        obligation_sha256: str,
        lane: str,
        *,
        outcome: str,
    ) -> _LaneClosurePermit:
        with object.__getattribute__(self, "_lock"):
            self._validate()
            pair = (obligation_sha256, lane)
            claimed = object.__getattribute__(self, "_claimed")
            closed = object.__getattribute__(self, "_closed")
            if (
                type(outcome) is not str
                or outcome not in _LANE_OUTCOMES
                or pair not in claimed
                or pair in closed
            ):
                raise ValueError("retrieval_execution_ledger_transition_error")
            updated_closed = closed | {pair}
            dense_provider_failed = object.__getattribute__(
                self, "_dense_provider_failed"
            )
            if lane == "dense" and outcome == "provider_error":
                dense_provider_failed = dense_provider_failed | {
                    obligation_sha256
                }
            terminate = (
                outcome == "contract_error"
                or (lane == "lexical" and outcome == "provider_error")
                or (
                    lane == "lexical"
                    and obligation_sha256 in dense_provider_failed
                )
            )
            transition_sha256 = self._advance(
                claimed=claimed,
                closed=updated_closed,
                dense_provider_failed=dense_provider_failed,
                status="terminated" if terminate else "active",
            )
            return _register_lane_closure_permit(
                ledger=self,
                obligation_sha256=obligation_sha256,
                lane=lane,
                outcome=outcome,
                transition_sha256=transition_sha256,
            )


@dataclass(frozen=True, slots=True, weakref_slot=True)
class _LaneClosurePermit:
    ledger: _RetrievalExecutionLedger
    obligation_sha256: str
    lane: str
    outcome: str
    transition_sha256: str
    revision: int


def _build_lane_closure_permit_accessors() -> tuple[
    FunctionType,
    FunctionType,
    FunctionType,
]:
    """Issue and consume one receipt permit for each real ledger close."""

    permits: dict[int, tuple[object, ...]] = {}
    ledger_progress: dict[int, tuple[ReferenceType[object], int]] = {}
    permit_lock = Lock()

    def _drop_permit(identity: int, dead: ReferenceType[object]) -> None:
        with permit_lock:
            current = dict.get(permits, identity)
            if (
                type(current) is tuple
                and len(current) == 8
                and tuple.__getitem__(current, 0) is dead
            ):
                dict.pop(permits, identity, None)

    def _drop_ledger(identity: int, dead: ReferenceType[object]) -> None:
        with permit_lock:
            current = dict.get(ledger_progress, identity)
            if (
                type(current) is tuple
                and len(current) == 2
                and tuple.__getitem__(current, 0) is dead
            ):
                dict.pop(ledger_progress, identity, None)

    def _snapshot(
        permit: _LaneClosurePermit,
        weak: ReferenceType[_LaneClosurePermit],
        consumed: bool,
    ) -> tuple[object, ...]:
        return (
            weak,
            object.__getattribute__(permit, "ledger"),
            object.__getattribute__(permit, "obligation_sha256"),
            object.__getattribute__(permit, "lane"),
            object.__getattribute__(permit, "outcome"),
            object.__getattribute__(permit, "transition_sha256"),
            object.__getattribute__(permit, "revision"),
            consumed,
        )

    def _validated_unlocked(
        permit: _LaneClosurePermit,
    ) -> tuple[object, ...]:
        current = dict.get(permits, id(permit))
        if (
            type(permit) is not _LaneClosurePermit
            or type(current) is not tuple
            or len(current) != 8
            or tuple.__getitem__(current, 0)() is not permit
        ):
            raise ValueError("retrieval_lane_transition_authority_required")
        expected = _snapshot(
            permit,
            tuple.__getitem__(current, 0),
            tuple.__getitem__(current, 7),
        )
        if any(
            current_value is not expected_value
            for current_value, expected_value in zip(current, expected)
        ):
            raise ValueError("retrieval_lane_transition_authority_drift")
        return current

    def register(
        *,
        ledger: _RetrievalExecutionLedger,
        obligation_sha256: str,
        lane: str,
        outcome: str,
        transition_sha256: str,
    ) -> _LaneClosurePermit:
        with permit_lock:
            if type(ledger) is not _RetrievalExecutionLedger:
                raise ValueError("retrieval_lane_transition_ledger_mismatch")
            ledger._validate()
            revision = object.__getattribute__(ledger, "_revision")
            if (
                type(obligation_sha256) is not str
                or type(lane) is not str
                or type(outcome) is not str
                or lane not in _RETRIEVAL_LANES
                or outcome not in _LANE_OUTCOMES
                or object.__getattribute__(ledger, "_state_sha256")
                != transition_sha256
                or (obligation_sha256, lane)
                not in object.__getattribute__(ledger, "_closed")
            ):
                raise ValueError("retrieval_lane_transition_mismatch")
            progress = dict.get(ledger_progress, id(ledger))
            previous_revision = 0
            if progress is not None:
                if (
                    type(progress) is not tuple
                    or len(progress) != 2
                    or tuple.__getitem__(progress, 0)() is not ledger
                ):
                    raise ValueError("retrieval_lane_transition_authority_drift")
                previous_revision = tuple.__getitem__(progress, 1)
            if revision != previous_revision + 2:
                raise ValueError("retrieval_lane_transition_revision_mismatch")
            permit = _LaneClosurePermit(
                ledger=ledger,
                obligation_sha256=obligation_sha256,
                lane=lane,
                outcome=outcome,
                transition_sha256=transition_sha256,
                revision=revision,
            )
            permit_weak = ref(
                permit,
                lambda dead, identity=id(permit): _drop_permit(
                    identity, dead
                ),
            )
            ledger_weak = ref(
                ledger,
                lambda dead, identity=id(ledger): _drop_ledger(
                    identity, dead
                ),
            )
            dict.__setitem__(
                permits,
                id(permit),
                _snapshot(permit, permit_weak, False),
            )
            dict.__setitem__(
                ledger_progress,
                id(ledger),
                (ledger_weak, revision),
            )
            return permit

    def consume(
        permit: _LaneClosurePermit,
        *,
        ledger: _RetrievalExecutionLedger,
        obligation_sha256: str,
        lane: str,
        outcome: str,
    ) -> str:
        with permit_lock:
            current = _validated_unlocked(permit)
            if (
                tuple.__getitem__(current, 7) is not False
                or object.__getattribute__(permit, "ledger") is not ledger
                or object.__getattribute__(permit, "obligation_sha256")
                != obligation_sha256
                or object.__getattribute__(permit, "lane") != lane
                or object.__getattribute__(permit, "outcome") != outcome
            ):
                raise ValueError("retrieval_lane_transition_consumption_mismatch")
            updated = tuple.__getitem__(current, slice(0, 7)) + (True,)
            dict.__setitem__(permits, id(permit), updated)
            return object.__getattribute__(permit, "transition_sha256")

    def validate_consumed(
        permit: _LaneClosurePermit,
        *,
        ledger: _RetrievalExecutionLedger,
        obligation_sha256: str,
        lane: str,
        outcome: str,
        transition_sha256: str,
    ) -> None:
        with permit_lock:
            current = _validated_unlocked(permit)
            if (
                tuple.__getitem__(current, 7) is not True
                or object.__getattribute__(permit, "ledger") is not ledger
                or object.__getattribute__(permit, "obligation_sha256")
                != obligation_sha256
                or object.__getattribute__(permit, "lane") != lane
                or object.__getattribute__(permit, "outcome") != outcome
                or object.__getattribute__(permit, "transition_sha256")
                != transition_sha256
            ):
                raise ValueError("retrieval_lane_transition_consumption_mismatch")

    return register, consume, validate_consumed


(
    _register_lane_closure_permit,
    _consume_lane_closure_permit,
    _validate_consumed_lane_closure_permit,
) = _build_lane_closure_permit_accessors()


@dataclass(frozen=True, slots=True)
class _RetrievalObligationAuthority:
    weak: ReferenceType[RetrievalObligation]
    issued_payload_sha256: str
    source: object
    source_projector: FunctionType
    source_projector_code: CodeType
    source_validator: FunctionType
    source_validator_code: CodeType
    projection_ordinal: int
    raw_query: str
    store: EvidenceStore
    config: HarnessExecutionConfig
    runtime: HarnessRuntimeBinding
    ledger: _RetrievalExecutionLedger


@dataclass(frozen=True, slots=True)
class _RetrievalIssuanceAuthority:
    source_kind: str
    source_weak: ReferenceType[object]
    store_weak: ReferenceType[EvidenceStore]
    config_weak: ReferenceType[HarnessExecutionConfig]
    runtime_weak: ReferenceType[HarnessRuntimeBinding]
    obligation_weaks: tuple[ReferenceType[RetrievalObligation], ...]


_RETRIEVAL_OBLIGATION_AUTHORITIES: dict[
    int, _RetrievalObligationAuthority
] = {}
_ISSUED_RETRIEVAL_OBLIGATION_AUTHORITIES = (
    _RETRIEVAL_OBLIGATION_AUTHORITIES
)


def _build_retrieval_obligation_authority_accessors(
    visible: dict[int, _RetrievalObligationAuthority],
) -> tuple[FunctionType, FunctionType, FunctionType, FunctionType]:
    """Seal obligation authority fields outside the mutable audit registry."""

    shadow: dict[int, tuple[object, ...]] = {}
    authority_lock = Lock()

    def _snapshot(authority: _RetrievalObligationAuthority) -> tuple[object, ...]:
        return tuple(
            object.__getattribute__(authority, name)
            for name in (
                "weak",
                "issued_payload_sha256",
                "source",
                "source_projector",
                "source_projector_code",
                "source_validator",
                "source_validator_code",
                "projection_ordinal",
                "raw_query",
                "store",
                "config",
                "runtime",
                "ledger",
            )
        )

    def _validated_unlocked(
        obligation: RetrievalObligation,
    ) -> _RetrievalObligationAuthority | None:
        identity = id(obligation)
        current = dict.get(visible, identity)
        sealed = dict.get(shadow, identity)
        if current is None and sealed is None:
            return None
        if (
            type(current) is not _RetrievalObligationAuthority
            or type(sealed) is not tuple
            or len(sealed) != 13
            or tuple.__getitem__(sealed, 0)() is not obligation
        ):
            raise ValueError("retrieval_obligation_runtime_authority_drift")
        current_snapshot = _snapshot(current)
        if any(
            current_value is not sealed_value
            for current_value, sealed_value in zip(current_snapshot, sealed)
        ):
            raise ValueError("retrieval_obligation_runtime_authority_drift")
        return current

    def register(
        obligation: RetrievalObligation,
        authority: _RetrievalObligationAuthority,
    ) -> None:
        with authority_lock:
            if (
                type(authority) is not _RetrievalObligationAuthority
                or _validated_unlocked(obligation) is not None
                or object.__getattribute__(authority, "weak")()
                is not obligation
            ):
                raise ValueError("retrieval_obligation_runtime_authority_drift")
            identity = id(obligation)
            sealed = _snapshot(authority)
            dict.__setitem__(visible, identity, authority)
            dict.__setitem__(shadow, identity, sealed)

    def read(
        obligation: RetrievalObligation,
    ) -> _RetrievalObligationAuthority:
        with authority_lock:
            current = _validated_unlocked(obligation)
            if current is None:
                raise ValueError("retrieval_obligation_runtime_authority_required")
            return current

    def unregister(obligation: RetrievalObligation) -> None:
        with authority_lock:
            if _validated_unlocked(obligation) is None:
                raise ValueError("retrieval_obligation_runtime_authority_drift")
            identity = id(obligation)
            dict.pop(visible, identity)
            dict.pop(shadow, identity)

    def drop_when_dead(
        identity: int,
        dead: ReferenceType[RetrievalObligation],
    ) -> None:
        with authority_lock:
            sealed = dict.get(shadow, identity)
            if (
                type(sealed) is tuple
                and len(sealed) == 13
                and tuple.__getitem__(sealed, 0) is dead
            ):
                dict.pop(visible, identity, None)
                dict.pop(shadow, identity, None)

    return register, read, unregister, drop_when_dead


(
    _register_retrieval_obligation_authority,
    _read_retrieval_obligation_authority,
    _unregister_retrieval_obligation_authority,
    _drop_retrieval_obligation_authority_when_dead,
) = _build_retrieval_obligation_authority_accessors(
    _ISSUED_RETRIEVAL_OBLIGATION_AUTHORITIES
)


_RETRIEVAL_ISSUANCE_AUTHORITIES: dict[
    tuple[str, int, int, int, int], _RetrievalIssuanceAuthority
] = {}
_ISSUED_RETRIEVAL_ISSUANCE_AUTHORITIES = (
    _RETRIEVAL_ISSUANCE_AUTHORITIES
)


def _build_retrieval_issuance_authority_accessors(
    visible: dict[
        tuple[str, int, int, int, int], _RetrievalIssuanceAuthority
    ],
) -> tuple[FunctionType, FunctionType, FunctionType]:
    """Mirror issuance identities privately so deleting the audit row fails closed."""

    shadow: dict[
        tuple[str, int, int, int, int],
        tuple[
            str,
            ReferenceType[object],
            ReferenceType[EvidenceStore],
            ReferenceType[HarnessExecutionConfig],
            ReferenceType[HarnessRuntimeBinding],
            tuple[ReferenceType[RetrievalObligation], ...],
        ],
    ] = {}
    authority_lock = Lock()

    def _validated_unlocked(
        key: tuple[str, int, int, int, int],
    ) -> _RetrievalIssuanceAuthority | None:
        current = dict.get(visible, key)
        sealed = dict.get(shadow, key)
        if current is None and sealed is None:
            return None
        if (
            type(current) is not _RetrievalIssuanceAuthority
            or type(sealed) is not tuple
            or len(sealed) != 6
            or object.__getattribute__(current, "source_kind")
            != tuple.__getitem__(sealed, 0)
            or object.__getattribute__(current, "source_weak")
            is not tuple.__getitem__(sealed, 1)
            or object.__getattribute__(current, "store_weak")
            is not tuple.__getitem__(sealed, 2)
            or object.__getattribute__(current, "config_weak")
            is not tuple.__getitem__(sealed, 3)
            or object.__getattribute__(current, "runtime_weak")
            is not tuple.__getitem__(sealed, 4)
            or object.__getattribute__(current, "obligation_weaks")
            is not tuple.__getitem__(sealed, 5)
        ):
            raise ValueError("retrieval_issuance_authority_drift")
        return current

    def read(
        key: tuple[str, int, int, int, int],
    ) -> _RetrievalIssuanceAuthority | None:
        with authority_lock:
            return _validated_unlocked(key)

    def register_or_read(
        key: tuple[str, int, int, int, int],
        candidate: _RetrievalIssuanceAuthority,
    ) -> _RetrievalIssuanceAuthority:
        with authority_lock:
            current = _validated_unlocked(key)
            if current is not None:
                return current
            if type(candidate) is not _RetrievalIssuanceAuthority:
                raise ValueError("retrieval_issuance_authority_drift")
            sealed = (
                object.__getattribute__(candidate, "source_kind"),
                object.__getattribute__(candidate, "source_weak"),
                object.__getattribute__(candidate, "store_weak"),
                object.__getattribute__(candidate, "config_weak"),
                object.__getattribute__(candidate, "runtime_weak"),
                object.__getattribute__(candidate, "obligation_weaks"),
            )
            dict.__setitem__(visible, key, candidate)
            dict.__setitem__(shadow, key, sealed)
            return candidate

    def drop_when_source_dead(
        key: tuple[str, int, int, int, int],
        dead: ReferenceType[object],
    ) -> None:
        with authority_lock:
            current = _validated_unlocked(key)
            if current is None:
                return
            if (
                object.__getattribute__(current, "source_weak") is not dead
                or dead() is not None
            ):
                raise ValueError("retrieval_issuance_authority_drift")
            dict.pop(visible, key)
            dict.pop(shadow, key)

    return read, register_or_read, drop_when_source_dead


(
    _read_retrieval_issuance_authority,
    _register_or_read_retrieval_issuance_authority,
    _drop_retrieval_issuance_when_source_dead,
) = _build_retrieval_issuance_authority_accessors(
    _ISSUED_RETRIEVAL_ISSUANCE_AUTHORITIES
)


def _drop_retrieval_obligation_authority(
    identity: int,
    dead: ReferenceType[RetrievalObligation],
) -> None:
    _drop_retrieval_obligation_authority_when_dead(identity, dead)


def _owner_projection_values(
    source_kind: str,
    projection: object,
) -> dict[str, Any]:
    if type(source_kind) is not str or source_kind not in _RETRIEVAL_SOURCE_KINDS:
        raise ValueError("invalid_retrieval_owner_projection")
    projection_class = tuple.__getitem__(
        _ISSUED_RETRIEVAL_OWNER_SPECS[source_kind], 2
    )
    if type(projection) is not projection_class:
        raise ValueError("invalid_retrieval_owner_projection")
    try:
        ordinal = object.__getattribute__(projection, "ordinal")
        obligation_key = object.__getattribute__(projection, "obligation_key")
        query = object.__getattribute__(projection, "query")
        scope_origin = object.__getattribute__(projection, "scope_origin")
        dense_k = object.__getattribute__(projection, "dense_k")
        lexical_k = object.__getattribute__(projection, "lexical_k")
        execution_kind = object.__getattribute__(projection, "execution_kind")
        evidence_bundle_sha256 = object.__getattribute__(
            projection, "evidence_bundle_sha256"
        )
        source_receipt_sha256 = object.__getattribute__(
            projection, "source_receipt_sha256"
        )
        if source_kind == "fact":
            scope_state = object.__getattribute__(projection, "scope_state")
            scope_doc_ids = object.__getattribute__(projection, "scope_doc_ids")
        else:
            scope_state = "restricted"
            scope_doc_ids = (object.__getattribute__(projection, "doc_id"),)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("invalid_retrieval_owner_projection") from exc
    values = {
        "ordinal": ordinal,
        "obligation_key": obligation_key,
        "query": query,
        "scope_state": scope_state,
        "scope_origin": scope_origin,
        "scope_doc_ids": scope_doc_ids,
        "dense_k": dense_k,
        "lexical_k": lexical_k,
        "execution_kind": execution_kind,
        "evidence_bundle_sha256": evidence_bundle_sha256,
        "source_receipt_sha256": source_receipt_sha256,
    }
    if (
        type(ordinal) is not int
        or ordinal < 1
        or type(obligation_key) is not str
        or not obligation_key
        or type(query) is not str
        or not query.strip()
        or type(scope_state) is not str
        or scope_state not in {"unfiltered", "restricted"}
        or type(scope_origin) is not str
        or not scope_origin
        or not _exact_string_tuple(scope_doc_ids)
        or (scope_state == "restricted") != bool(scope_doc_ids)
        or type(dense_k) is not int
        or dense_k < 1
        or type(lexical_k) is not int
        or lexical_k < 1
        or type(execution_kind) is not str
        or execution_kind not in {"production", "synthetic"}
    ):
        raise ValueError("invalid_retrieval_owner_projection")
    _require_hash(
        evidence_bundle_sha256,
        "invalid_retrieval_projection_bundle_hash",
    )
    _require_hash(
        source_receipt_sha256,
        "invalid_retrieval_projection_source_hash",
    )
    return values


def _require_retrieval_owner(
    *,
    source_kind: str,
    source: object,
    source_projector: FunctionType,
    source_validator: FunctionType,
) -> None:
    """Accept only the two pinned owner modules and their exact live functions."""

    if type(source_kind) is not str or source_kind not in _RETRIEVAL_SOURCE_KINDS:
        raise ValueError("invalid_retrieval_source_kind")
    spec = _ISSUED_RETRIEVAL_OWNER_SPECS[source_kind]
    (
        module,
        source_class,
        projection_class,
        projector_pin,
        validator_pin,
        module_snapshot,
    ) = spec
    projector = tuple.__getitem__(projector_pin, 0)
    validator = tuple.__getitem__(validator_pin, 0)
    if (
        object.__getattribute__(module, source_class.__name__) is not source_class
        or object.__getattribute__(module, projection_class.__name__)
        is not projection_class
        or type(source) is not source_class
        or source_projector is not projector
        or source_validator is not validator
        or type(source_projector) is not FunctionType
        or type(source_validator) is not FunctionType
    ):
        raise ValueError("retrieval_source_owner_identity_mismatch")
    module_namespace = object.__getattribute__(module, "__dict__")
    if (
        type(module_snapshot) is not tuple
        or len(module_snapshot) != 2
        or type(tuple.__getitem__(module_snapshot, 0)) is not tuple
        or tuple(
            sorted(
                name
                for name in module_namespace
                if not name.startswith("__")
            )
        )
        != tuple.__getitem__(module_snapshot, 0)
    ):
        raise ValueError("retrieval_source_owner_global_drift")
    module_pins = tuple.__getitem__(module_snapshot, 1)
    if type(module_pins) is not tuple:
        raise ValueError("retrieval_source_owner_global_drift")
    for name, issued, issued_type, callable_pin, class_pin in module_pins:
        current = dict.get(module_namespace, name)
        if current is not issued or type(current) is not issued_type:
            raise ValueError("retrieval_source_owner_global_drift")
        if callable_pin is None:
            pass
        else:
            (
                pinned_function,
                pinned_name,
                pinned_code,
                pinned_defaults,
                pinned_kwdefaults,
                pinned_kwdefault_items,
                pinned_globals,
                pinned_closure,
            ) = callable_pin
            current_kwdefaults = object.__getattribute__(current, "__kwdefaults__")
            current_kwdefault_items = (
                None
                if current_kwdefaults is None
                else tuple(sorted(dict.items(current_kwdefaults)))
            )
            if (
                current is not pinned_function
                or object.__getattribute__(current, "__name__") != pinned_name
                or object.__getattribute__(current, "__code__") is not pinned_code
                or object.__getattribute__(current, "__defaults__")
                is not pinned_defaults
                or current_kwdefaults is not pinned_kwdefaults
                or current_kwdefault_items != pinned_kwdefault_items
                or object.__getattribute__(current, "__globals__")
                is not pinned_globals
                or object.__getattribute__(current, "__closure__")
                is not pinned_closure
            ):
                raise ValueError("retrieval_source_owner_global_drift")
        if class_pin is None:
            continue
        class_names, class_members = class_pin
        class_namespace = type.__getattribute__(current, "__dict__")
        if (
            type(class_names) is not tuple
            or type(class_members) is not tuple
            or tuple(sorted(class_namespace)) != class_names
        ):
            raise ValueError("retrieval_source_owner_class_drift")
        for (
            member_name,
            issued_member,
            issued_member_type,
            member_callable_pins,
        ) in class_members:
            current_member = class_namespace.get(member_name)
            if (
                current_member is not issued_member
                or type(current_member) is not issued_member_type
                or type(member_callable_pins) is not tuple
            ):
                raise ValueError("retrieval_source_owner_class_drift")
            current_callables = []
            if type(current_member) is FunctionType:
                current_callables.append(("function", current_member))
            elif type(current_member) in {classmethod, staticmethod}:
                current_callables.append(
                    (
                        "wrapped",
                        object.__getattribute__(current_member, "__func__"),
                    )
                )
            elif type(current_member) is property:
                for role in ("fget", "fset", "fdel"):
                    function = object.__getattribute__(current_member, role)
                    if function is not None:
                        current_callables.append((role, function))
            if len(current_callables) != len(member_callable_pins):
                raise ValueError("retrieval_source_owner_class_drift")
            for (role, function), (pinned_role, pin) in zip(
                current_callables,
                member_callable_pins,
            ):
                (
                    pinned_function,
                    pinned_name,
                    pinned_code,
                    pinned_defaults,
                    pinned_kwdefaults,
                    pinned_kwdefault_items,
                    pinned_globals,
                    pinned_closure,
                ) = pin
                current_kwdefaults = object.__getattribute__(
                    function, "__kwdefaults__"
                )
                current_kwdefault_items = (
                    None
                    if current_kwdefaults is None
                    else tuple(sorted(dict.items(current_kwdefaults)))
                )
                if (
                    role != pinned_role
                    or function is not pinned_function
                    or object.__getattribute__(function, "__name__")
                    != pinned_name
                    or object.__getattribute__(function, "__code__")
                    is not pinned_code
                    or object.__getattribute__(function, "__defaults__")
                    is not pinned_defaults
                    or current_kwdefaults is not pinned_kwdefaults
                    or current_kwdefault_items != pinned_kwdefault_items
                    or object.__getattribute__(function, "__globals__")
                    is not pinned_globals
                    or object.__getattribute__(function, "__closure__")
                    is not pinned_closure
                ):
                    raise ValueError("retrieval_source_owner_class_drift")
    for function, pin in (
        (source_projector, projector_pin),
        (source_validator, validator_pin),
    ):
        (
            issued,
            name,
            code,
            defaults,
            kwdefaults,
            kwdefault_items,
            function_globals,
            closure,
        ) = pin
        current_kwdefaults = object.__getattribute__(function, "__kwdefaults__")
        current_kwdefault_items = (
            None
            if current_kwdefaults is None
            else tuple(sorted(dict.items(current_kwdefaults)))
        )
        if (
            issued is not function
            or object.__getattribute__(module, name) is not function
            or object.__getattribute__(function, "__name__") != name
            or object.__getattribute__(function, "__code__") is not code
            or object.__getattribute__(function, "__defaults__") is not defaults
            or current_kwdefaults is not kwdefaults
            or current_kwdefault_items != kwdefault_items
            or object.__getattribute__(function, "__globals__")
            is not function_globals
            or function_globals is not module_namespace
            or object.__getattribute__(function, "__closure__") is not closure
        ):
            raise ValueError("retrieval_source_owner_callable_drift")


def _normalized_owner_projections(
    *,
    source_kind: str,
    projected: object,
) -> tuple[dict[str, Any], ...]:
    raw_values = (projected,) if source_kind == "fact" else projected
    if type(raw_values) is not tuple or not raw_values:
        raise ValueError("retrieval_owner_projection_required")
    values = tuple(
        _owner_projection_values(source_kind, item) for item in raw_values
    )
    if tuple(item["ordinal"] for item in values) != tuple(
        range(1, len(values) + 1)
    ):
        raise ValueError("retrieval_owner_projection_order_mismatch")
    keys = tuple(item["obligation_key"] for item in values)
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate_retrieval_obligation_key")
    return values


def _projection_safe_payload(
    values: Mapping[str, Any],
    *,
    count: int,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ordinal": values["ordinal"],
        "obligation_count": count,
        "obligation_key": values["obligation_key"],
        "query_sha256": _query_sha256(values["query"]),
        "scope_state": values["scope_state"],
        "scope_origin": values["scope_origin"],
        "scope_doc_ids": list(values["scope_doc_ids"]),
        "dense_k": values["dense_k"],
        "lexical_k": values["lexical_k"],
        "execution_kind": values["execution_kind"],
        "evidence_store_sha256": values["evidence_bundle_sha256"],
        "source_receipt_sha256": values["source_receipt_sha256"],
    }


def _issuance_key(
    *,
    source_kind: str,
    source: object,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
) -> tuple[str, int, int, int, int]:
    return (
        source_kind,
        id(source),
        id(store),
        id(config),
        id(runtime),
    )


def _cached_retrieval_issuance(
    *,
    key: tuple[str, int, int, int, int],
    source_kind: str,
    source: object,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
) -> tuple[RetrievalObligation, ...] | None:
    current = _read_retrieval_issuance_authority(key)
    if current is None:
        return None
    current_source = object.__getattribute__(current, "source_weak")()
    current_store = object.__getattribute__(current, "store_weak")()
    current_config = object.__getattribute__(current, "config_weak")()
    current_runtime = object.__getattribute__(current, "runtime_weak")()
    obligation_weaks = object.__getattribute__(current, "obligation_weaks")
    if (
        type(current) is not _RetrievalIssuanceAuthority
        or object.__getattribute__(current, "source_kind") != source_kind
        or current_source is not source
        or current_store is not store
        or current_config is not config
        or current_runtime is not runtime
    ):
        raise ValueError("retrieval_issuance_authority_drift")
    if (
        type(obligation_weaks) is not tuple
        or not obligation_weaks
        or any(type(value) is not ReferenceType for value in obligation_weaks)
    ):
        raise ValueError("retrieval_issuance_authority_drift")
    current_obligations = tuple(value() for value in obligation_weaks)
    if any(obligation is None for obligation in current_obligations):
        raise ValueError("retrieval_issuance_expired")
    if any(
        type(obligation) is not RetrievalObligation
        for obligation in current_obligations
    ):
        raise ValueError("retrieval_issuance_authority_drift")
    ledgers = set()
    for obligation in current_obligations:
        authority = _require_retrieval_obligation_authority(obligation)
        if (
            authority.source is not source
            or authority.store is not store
            or authority.config is not config
            or authority.runtime is not runtime
        ):
            raise ValueError("retrieval_issuance_authority_drift")
        ledgers.add(id(authority.ledger))
    if len(ledgers) != 1:
        raise ValueError("retrieval_issuance_authority_drift")
    return current_obligations


def _issue_retrieval_obligations_from_owner(
    *,
    source_kind: str,
    source: object,
    source_projector: FunctionType,
    source_validator: FunctionType,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    _dependency_checker=None,
    _dependency_checker_code=None,
) -> tuple[RetrievalObligation, ...]:
    """Internal core mint called only by fact/compare owner APIs."""

    module_namespace = globals()
    checker_defaults = (
        None
        if type(_dependency_checker) is not FunctionType
        else object.__getattribute__(_dependency_checker, "__defaults__")
    )
    if (
        _dependency_checker
        is not dict.get(
            module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER"
        )
        or type(_dependency_checker) is not FunctionType
        or object.__getattribute__(_dependency_checker, "__code__")
        is not _dependency_checker_code
        or _dependency_checker_code
        is not dict.get(
            module_namespace, "_PINNED_RUNTIME_GATE_DEPENDENCY_CHECKER_CODE"
        )
        or checker_defaults
        is not dict.get(
            module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_DEFAULTS"
        )
        or type(checker_defaults) is not tuple
        or len(checker_defaults) != 6
        or tuple.__getitem__(checker_defaults, 0) is not module_namespace
        or object.__getattribute__(_dependency_checker, "__kwdefaults__")
        is not None
    ):
        raise ValueError("harness_runtime_validation_dependency_drift")
    _dependency_checker()
    _require_retrieval_owner(
        source_kind=source_kind,
        source=source,
        source_projector=source_projector,
        source_validator=source_validator,
    )
    if type(store) is not EvidenceStore:
        raise TypeError("evidence_store_required")
    if type(config) is not HarnessExecutionConfig:
        raise TypeError("harness_execution_config_required")
    if type(runtime) is not HarnessRuntimeBinding:
        raise TypeError("harness_runtime_binding_required")
    validate_harness_execution_config(config)
    validate_harness_runtime_binding(binding=runtime, store=store)
    source_validator(bound=source, store=store)
    issuance_key = _issuance_key(
        source_kind=source_kind,
        source=source,
        store=store,
        config=config,
        runtime=runtime,
    )
    cached = _cached_retrieval_issuance(
        key=issuance_key,
        source_kind=source_kind,
        source=source,
        store=store,
        config=config,
        runtime=runtime,
    )
    if cached is not None:
        return cached
    projected = source_projector(bound=source, store=store)
    values = _normalized_owner_projections(
        source_kind=source_kind,
        projected=projected,
    )
    count = len(values)
    runtime_kind = object.__getattribute__(runtime, "execution_kind")
    bundle_sha256 = object.__getattribute__(store, "bundle_sha256")
    source_binding_sha256 = object.__getattribute__(source, "binding_sha256")
    if any(
        item["execution_kind"] != runtime_kind
        or item["evidence_bundle_sha256"] != bundle_sha256
        or item["source_receipt_sha256"] != source_binding_sha256
        for item in values
    ):
        raise ValueError("retrieval_source_runtime_mismatch")
    safe_sources = tuple(
        _projection_safe_payload(item, count=count) for item in values
    )
    execution_binding_sha256 = _canonical_sha256(
        {
            "schema_version": SCHEMA_VERSION,
            "source_kind": source_kind,
            "source_receipt_sha256": source_binding_sha256,
            "evidence_store_sha256": bundle_sha256,
            "execution_config_sha256": object.__getattribute__(
                config, "config_sha256"
            ),
            "runtime_binding_sha256": object.__getattribute__(
                runtime, "binding_sha256"
            ),
            "obligations": list(safe_sources),
        }
    )
    issued: list[tuple[RetrievalObligation, Mapping[str, Any]]] = []
    for item, safe in zip(values, safe_sources):
        scope_sha256 = _canonical_sha256(
            {
                "schema_version": SCHEMA_VERSION,
                "state": item["scope_state"],
                "origin": item["scope_origin"],
                "doc_ids": list(item["scope_doc_ids"]),
            }
        )
        base = {
            "source_kind": source_kind,
            "obligation_key": item["obligation_key"],
            "ordinal": item["ordinal"],
            "obligation_count": count,
            "execution_kind": item["execution_kind"],
            "execution_binding_sha256": execution_binding_sha256,
            "source_receipt_sha256": item["source_receipt_sha256"],
            "query_sha256": safe["query_sha256"],
            "scope_state": item["scope_state"],
            "scope_origin": item["scope_origin"],
            "scope_doc_ids": item["scope_doc_ids"],
            "scope_sha256": scope_sha256,
            "dense_k": item["dense_k"],
            "lexical_k": item["lexical_k"],
            "round_index": 1,
            "evidence_store_sha256": bundle_sha256,
            "execution_config_sha256": object.__getattribute__(
                config, "config_sha256"
            ),
            "runtime_binding_sha256": object.__getattribute__(
                runtime, "binding_sha256"
            ),
        }
        obligation = RetrievalObligation._create(
            payload={
                **base,
                "obligation_sha256": _canonical_sha256(
                    {"schema_version": SCHEMA_VERSION, **base}
                ),
            },
            _token=_RETRIEVAL_OBLIGATION_TOKEN,
        )
        issued.append((obligation, item))
    ledger = _RetrievalExecutionLedger._create(
        tuple(
            object.__getattribute__(obligation, "obligation_sha256")
            for obligation, _item in issued
        ),
        _token=_RETRIEVAL_LEDGER_TOKEN,
    )
    for obligation, item in issued:
        identity = id(obligation)
        weak = ref(
            obligation,
            lambda dead, identity=identity,
            drop=_drop_retrieval_obligation_authority: (
                drop(identity, dead)
            ),
        )
        _register_retrieval_obligation_authority(
            obligation,
            _RetrievalObligationAuthority(
                weak=weak,
                issued_payload_sha256=_canonical_sha256(
                    obligation.to_dict()
                ),
                source=source,
                source_projector=source_projector,
                source_projector_code=object.__getattribute__(
                    source_projector, "__code__"
                ),
                source_validator=source_validator,
                source_validator_code=object.__getattribute__(
                    source_validator, "__code__"
                ),
                projection_ordinal=item["ordinal"],
                raw_query=item["query"],
                store=store,
                config=config,
                runtime=runtime,
                ledger=ledger,
            ),
        )
    obligations = tuple(obligation for obligation, _item in issued)
    source_weak = ref(
        source,
        lambda dead, key=issuance_key,
        drop=_drop_retrieval_issuance_when_source_dead: drop(key, dead),
    )
    issuance = _RetrievalIssuanceAuthority(
        source_kind=source_kind,
        source_weak=source_weak,
        store_weak=ref(store),
        config_weak=ref(config),
        runtime_weak=ref(runtime),
        obligation_weaks=tuple(ref(obligation) for obligation in obligations),
    )
    winner = _register_or_read_retrieval_issuance_authority(
        issuance_key,
        issuance,
    )
    if winner is not issuance:
        cached = _cached_retrieval_issuance(
            key=issuance_key,
            source_kind=source_kind,
            source=source,
            store=store,
            config=config,
            runtime=runtime,
        )
        if cached is None:
            raise ValueError("retrieval_issuance_authority_drift")
        for obligation, _item in issued:
            _unregister_retrieval_obligation_authority(obligation)
        _unregister_retrieval_ledger_authority(ledger)
        return cached
    return obligations


def issue_fact_retrieval_obligations(
    *,
    bound: object,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    _dependency_checker=None,
    _dependency_checker_code=None,
) -> tuple[RetrievalObligation, ...]:
    """Issue the sole fact obligation from the pinned fact owner."""

    module_namespace = globals()
    checker_defaults = (
        None
        if type(_dependency_checker) is not FunctionType
        else object.__getattribute__(_dependency_checker, "__defaults__")
    )
    if (
        _dependency_checker
        is not dict.get(
            module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER"
        )
        or type(_dependency_checker) is not FunctionType
        or object.__getattribute__(_dependency_checker, "__code__")
        is not _dependency_checker_code
        or _dependency_checker_code
        is not dict.get(
            module_namespace, "_PINNED_RUNTIME_GATE_DEPENDENCY_CHECKER_CODE"
        )
        or checker_defaults
        is not dict.get(
            module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_DEFAULTS"
        )
        or type(checker_defaults) is not tuple
        or len(checker_defaults) != 6
        or tuple.__getitem__(checker_defaults, 0) is not module_namespace
        or object.__getattribute__(_dependency_checker, "__kwdefaults__")
        is not None
    ):
        raise ValueError("harness_runtime_validation_dependency_drift")
    _dependency_checker()
    spec = _ISSUED_RETRIEVAL_OWNER_SPECS["fact"]
    return _issue_retrieval_obligations_from_owner(
        source_kind="fact",
        source=bound,
        source_projector=tuple.__getitem__(tuple.__getitem__(spec, 3), 0),
        source_validator=tuple.__getitem__(tuple.__getitem__(spec, 4), 0),
        store=store,
        config=config,
        runtime=runtime,
    )


def issue_compare_retrieval_obligations(
    *,
    bound: object,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    _dependency_checker=None,
    _dependency_checker_code=None,
) -> tuple[RetrievalObligation, ...]:
    """Issue the complete compare matrix from the pinned compare owner."""

    module_namespace = globals()
    checker_defaults = (
        None
        if type(_dependency_checker) is not FunctionType
        else object.__getattribute__(_dependency_checker, "__defaults__")
    )
    if (
        _dependency_checker
        is not dict.get(
            module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER"
        )
        or type(_dependency_checker) is not FunctionType
        or object.__getattribute__(_dependency_checker, "__code__")
        is not _dependency_checker_code
        or _dependency_checker_code
        is not dict.get(
            module_namespace, "_PINNED_RUNTIME_GATE_DEPENDENCY_CHECKER_CODE"
        )
        or checker_defaults
        is not dict.get(
            module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_DEFAULTS"
        )
        or type(checker_defaults) is not tuple
        or len(checker_defaults) != 6
        or tuple.__getitem__(checker_defaults, 0) is not module_namespace
        or object.__getattribute__(_dependency_checker, "__kwdefaults__")
        is not None
    ):
        raise ValueError("harness_runtime_validation_dependency_drift")
    _dependency_checker()
    spec = _ISSUED_RETRIEVAL_OWNER_SPECS["compare"]
    return _issue_retrieval_obligations_from_owner(
        source_kind="compare",
        source=bound,
        source_projector=tuple.__getitem__(tuple.__getitem__(spec, 3), 0),
        source_validator=tuple.__getitem__(tuple.__getitem__(spec, 4), 0),
        store=store,
        config=config,
        runtime=runtime,
    )


def _require_retrieval_obligation_authority(
    obligation: RetrievalObligation,
) -> _RetrievalObligationAuthority:
    if type(obligation) is not RetrievalObligation:
        raise TypeError("retrieval_obligation_required")
    authority = _read_retrieval_obligation_authority(obligation)
    if (
        type(authority) is not _RetrievalObligationAuthority
        or authority.weak() is not obligation
    ):
        raise ValueError("retrieval_obligation_runtime_authority_required")
    _validate_retrieval_obligation_payload(obligation)
    if authority.issued_payload_sha256 != _canonical_sha256(
        obligation.to_dict()
    ):
        raise ValueError("retrieval_obligation_runtime_authority_drift")
    if type(authority.ledger) is not _RetrievalExecutionLedger:
        raise ValueError("retrieval_execution_ledger_identity_mismatch")
    authority.ledger._validate()
    if object.__getattribute__(obligation, "obligation_sha256") not in (
        object.__getattribute__(authority.ledger, "_obligation_sha256s")
    ):
        raise ValueError("retrieval_execution_ledger_identity_mismatch")
    return authority


def _validate_lane_dispatch_dependency() -> None:
    hybrid_class = object.__getattribute__(
        _FUSION_RUNTIME_MODULE, "HybridChildRetriever"
    )
    current = type.__getattribute__(hybrid_class, "__dict__").get(
        "search_lane"
    )
    if (
        current is not _ISSUED_HYBRID_SEARCH_LANE
        or type(current) is not FunctionType
        or object.__getattribute__(current, "__code__")
        is not _ISSUED_HYBRID_SEARCH_LANE_CODE
        or object.__getattribute__(current, "__defaults__")
        is not _ISSUED_HYBRID_SEARCH_LANE_DEFAULTS
        or object.__getattribute__(current, "__kwdefaults__")
        is not _ISSUED_HYBRID_SEARCH_LANE_KWDEFAULTS
    ):
        raise ValueError("harness_lane_dispatch_dependency_drift")


def validate_retrieval_obligation(
    *,
    obligation: RetrievalObligation,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    _dependency_checker=None,
    _dependency_checker_code=None,
) -> None:
    """Revalidate exact live source/config/runtime before query dispatch."""

    module_namespace = globals()
    checker_defaults = (
        None
        if type(_dependency_checker) is not FunctionType
        else object.__getattribute__(_dependency_checker, "__defaults__")
    )
    if (
        _dependency_checker
        is not dict.get(
            module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER"
        )
        or type(_dependency_checker) is not FunctionType
        or object.__getattribute__(_dependency_checker, "__code__")
        is not _dependency_checker_code
        or _dependency_checker_code
        is not dict.get(
            module_namespace, "_PINNED_RUNTIME_GATE_DEPENDENCY_CHECKER_CODE"
        )
        or checker_defaults
        is not dict.get(
            module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_DEFAULTS"
        )
        or type(checker_defaults) is not tuple
        or len(checker_defaults) != 6
        or tuple.__getitem__(checker_defaults, 0) is not module_namespace
        or object.__getattribute__(_dependency_checker, "__kwdefaults__")
        is not None
    ):
        raise ValueError("harness_runtime_validation_dependency_drift")
    _dependency_checker()
    authority = _require_retrieval_obligation_authority(obligation)
    if store is not authority.store:
        raise ValueError("retrieval_obligation_store_identity_mismatch")
    if config is not authority.config:
        raise ValueError("retrieval_obligation_config_identity_mismatch")
    if runtime is not authority.runtime:
        raise ValueError("retrieval_obligation_runtime_identity_mismatch")
    validate_harness_execution_config(config)
    validate_harness_runtime_binding(
        binding=runtime,
        store=store,
        expected_execution_kind=object.__getattribute__(
            obligation, "execution_kind"
        ),
    )
    _validate_lane_dispatch_dependency()
    _require_retrieval_owner(
        source_kind=object.__getattribute__(obligation, "source_kind"),
        source=authority.source,
        source_projector=authority.source_projector,
        source_validator=authority.source_validator,
    )
    for function, code in (
        (authority.source_validator, authority.source_validator_code),
        (authority.source_projector, authority.source_projector_code),
    ):
        if (
            type(function) is not FunctionType
            or object.__getattribute__(function, "__code__") is not code
        ):
            raise ValueError("retrieval_source_owner_callable_drift")
    authority.source_validator(bound=authority.source, store=store)
    projected = authority.source_projector(
        bound=authority.source,
        store=store,
    )
    values = _normalized_owner_projections(
        source_kind=object.__getattribute__(obligation, "source_kind"),
        projected=projected,
    )
    ordinal = authority.projection_ordinal
    if ordinal > len(values):
        raise ValueError("retrieval_owner_projection_order_mismatch")
    current = values[ordinal - 1]
    expected = {
        "obligation_key": object.__getattribute__(
            obligation, "obligation_key"
        ),
        "ordinal": object.__getattribute__(obligation, "ordinal"),
        "query_sha256": object.__getattribute__(obligation, "query_sha256"),
        "scope_state": object.__getattribute__(obligation, "scope_state"),
        "scope_origin": object.__getattribute__(obligation, "scope_origin"),
        "scope_doc_ids": object.__getattribute__(obligation, "scope_doc_ids"),
        "dense_k": object.__getattribute__(obligation, "dense_k"),
        "lexical_k": object.__getattribute__(obligation, "lexical_k"),
        "execution_kind": object.__getattribute__(
            obligation, "execution_kind"
        ),
        "evidence_bundle_sha256": object.__getattribute__(
            obligation, "evidence_store_sha256"
        ),
        "source_receipt_sha256": object.__getattribute__(
            obligation, "source_receipt_sha256"
        ),
    }
    actual = {
        **{name: current[name] for name in expected if name != "query_sha256"},
        "query_sha256": _query_sha256(current["query"]),
    }
    if actual != expected or current["query"] != authority.raw_query:
        raise ValueError("retrieval_obligation_source_projection_drift")
    if len(values) != object.__getattribute__(obligation, "obligation_count"):
        raise ValueError("retrieval_obligation_count_drift")
    if (
        object.__getattribute__(store, "bundle_sha256")
        != object.__getattribute__(obligation, "evidence_store_sha256")
        or object.__getattribute__(config, "config_sha256")
        != object.__getattribute__(obligation, "execution_config_sha256")
        or object.__getattribute__(runtime, "binding_sha256")
        != object.__getattribute__(obligation, "runtime_binding_sha256")
    ):
        raise ValueError("retrieval_obligation_dependency_hash_mismatch")


def _validate_lane_result(
    *,
    result: object,
    lane: str,
    limit: int,
    obligation: RetrievalObligation,
    store: EvidenceStore,
) -> tuple[tuple[str, ...], tuple[StableEvidenceAnchor, ...], str]:
    if type(result) is not SearchResult:
        raise ValueError("lane_search_result_type_mismatch")
    candidates = object.__getattribute__(result, "candidates")
    trace = object.__getattribute__(result, "trace")
    if (
        type(candidates) is not tuple
        or type(trace) is not MappingProxyType
        or trace.get("lane") != lane
        or trace.get("granularity") != "child"
        or trace.get("bundle_sha256")
        != object.__getattribute__(store, "bundle_sha256")
        or len(candidates) > limit
    ):
        raise ValueError("lane_search_result_contract_mismatch")
    evidence_ids: list[str] = []
    anchors: list[StableEvidenceAnchor] = []
    allowed_doc_ids = (
        None
        if object.__getattribute__(obligation, "scope_state") == "unfiltered"
        else frozenset(object.__getattribute__(obligation, "scope_doc_ids"))
    )
    for rank, candidate in enumerate(candidates, 1):
        if type(candidate) is not Candidate:
            raise ValueError("lane_search_candidate_type_mismatch")
        evidence_id = object.__getattribute__(candidate, "evidence_id")
        doc_id = object.__getattribute__(candidate, "doc_id")
        score = object.__getattribute__(candidate, "score")
        if (
            type(evidence_id) is not str
            or not evidence_id
            or type(doc_id) is not str
            or not doc_id
            or type(score) not in (int, float)
            or not math.isfinite(score)
            or object.__getattribute__(candidate, "lane") != lane
            or object.__getattribute__(candidate, "rank") != rank
            or object.__getattribute__(candidate, "granularity") != "child"
            or (allowed_doc_ids is not None and doc_id not in allowed_doc_ids)
        ):
            raise ValueError("lane_search_candidate_contract_mismatch")
        try:
            evidence = EvidenceStore.get(store, evidence_id)
        except KeyError as exc:
            raise ValueError("lane_search_candidate_unknown_evidence") from exc
        if (
            object.__getattribute__(evidence, "doc_id") != doc_id
            or object.__getattribute__(evidence, "kind") != "text"
        ):
            raise ValueError("lane_search_candidate_evidence_mismatch")
        evidence_ids.append(evidence_id)
        anchors.append(_stable_anchor(evidence))
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("duplicate_lane_search_candidate")
    safe_result = {
        "schema_version": SCHEMA_VERSION,
        "lane": lane,
        "ordered_evidence_ids": evidence_ids,
        "ordered_stable_anchors": [anchor.to_dict() for anchor in anchors],
    }
    return tuple(evidence_ids), tuple(anchors), _canonical_sha256(safe_result)


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class LaneSearchReceipt:
    stage: str
    stage_ordinal: int
    lane: str
    execution_binding_sha256: str
    obligation_sha256: str
    obligation_key: str
    round_index: int
    query_sha256: str
    scope_state: str
    scope_origin: str
    scope_doc_ids: tuple[str, ...]
    scope_sha256: str
    candidate_limit: int
    evidence_store_sha256: str
    execution_config_sha256: str
    runtime_binding_sha256: str
    retrieval_config_sha256: str
    source_receipt_sha256: str
    ledger_transition_sha256: str
    ordered_evidence_ids: tuple[str, ...]
    ordered_stable_anchors: tuple[StableEvidenceAnchor, ...]
    candidate_count: int
    call_performed: bool
    outcome: str
    error_code: str
    result_sha256: str
    checkpoint_sha256: str
    receipt_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("lane_search_receipt_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        payload: Mapping[str, Any],
        _token: object,
    ) -> LaneSearchReceipt:
        if _token is not _LANE_SEARCH_RECEIPT_TOKEN:
            raise ValueError("lane_search_receipt_factory_required")
        result = object.__new__(cls)
        for name in cls.__slots__:
            if name != "__weakref__":
                object.__setattr__(result, name, payload[name])
        _validate_lane_search_receipt_payload(result)
        return result

    def to_dict(self) -> dict[str, Any]:
        _validate_lane_search_receipt_payload(self)
        return _lane_search_receipt_payload(self, include_hash=True)


def _lane_search_receipt_payload(
    receipt: LaneSearchReceipt,
    *,
    include_hash: bool,
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "stage": object.__getattribute__(receipt, "stage"),
        "stage_ordinal": object.__getattribute__(receipt, "stage_ordinal"),
        "lane": object.__getattribute__(receipt, "lane"),
        "execution_binding_sha256": object.__getattribute__(
            receipt, "execution_binding_sha256"
        ),
        "obligation_sha256": object.__getattribute__(
            receipt, "obligation_sha256"
        ),
        "obligation_key": object.__getattribute__(receipt, "obligation_key"),
        "round_index": object.__getattribute__(receipt, "round_index"),
        "query_sha256": object.__getattribute__(receipt, "query_sha256"),
        "scope_state": object.__getattribute__(receipt, "scope_state"),
        "scope_origin": object.__getattribute__(receipt, "scope_origin"),
        "scope_doc_ids": list(
            object.__getattribute__(receipt, "scope_doc_ids")
        ),
        "scope_sha256": object.__getattribute__(receipt, "scope_sha256"),
        "candidate_limit": object.__getattribute__(receipt, "candidate_limit"),
        "evidence_store_sha256": object.__getattribute__(
            receipt, "evidence_store_sha256"
        ),
        "execution_config_sha256": object.__getattribute__(
            receipt, "execution_config_sha256"
        ),
        "runtime_binding_sha256": object.__getattribute__(
            receipt, "runtime_binding_sha256"
        ),
        "retrieval_config_sha256": object.__getattribute__(
            receipt, "retrieval_config_sha256"
        ),
        "source_receipt_sha256": object.__getattribute__(
            receipt, "source_receipt_sha256"
        ),
        "ledger_transition_sha256": object.__getattribute__(
            receipt, "ledger_transition_sha256"
        ),
        "ordered_evidence_ids": list(
            object.__getattribute__(receipt, "ordered_evidence_ids")
        ),
        "ordered_stable_anchors": [
            anchor.to_dict()
            for anchor in object.__getattribute__(
                receipt, "ordered_stable_anchors"
            )
        ],
        "candidate_count": object.__getattribute__(receipt, "candidate_count"),
        "call_performed": object.__getattribute__(receipt, "call_performed"),
        "outcome": object.__getattribute__(receipt, "outcome"),
        "error_code": object.__getattribute__(receipt, "error_code"),
        "result_sha256": object.__getattribute__(receipt, "result_sha256"),
        "checkpoint_sha256": object.__getattribute__(
            receipt, "checkpoint_sha256"
        ),
    }
    if include_hash:
        payload["receipt_sha256"] = object.__getattribute__(
            receipt, "receipt_sha256"
        )
    return payload


def _validate_lane_search_receipt_payload(receipt: LaneSearchReceipt) -> None:
    if type(receipt) is not LaneSearchReceipt:
        raise TypeError("lane_search_receipt_required")
    lane = object.__getattribute__(receipt, "lane")
    if type(lane) is not str or lane not in _RETRIEVAL_LANES:
        raise ValueError("invalid_lane_search_receipt_lane")
    if object.__getattribute__(receipt, "stage") != f"lane_{lane}":
        raise ValueError("lane_search_receipt_stage_mismatch")
    if object.__getattribute__(receipt, "stage_ordinal") != (
        1 if lane == "dense" else 2
    ):
        raise ValueError("lane_search_receipt_stage_ordinal_mismatch")
    for name in ("obligation_key", "scope_origin"):
        value = object.__getattribute__(receipt, name)
        if type(value) is not str or not value:
            raise ValueError("invalid_lane_search_receipt_identity")
    if object.__getattribute__(receipt, "round_index") != 1:
        raise ValueError("invalid_lane_search_receipt_round")
    scope_state = object.__getattribute__(receipt, "scope_state")
    scope_doc_ids = object.__getattribute__(receipt, "scope_doc_ids")
    if (
        type(scope_state) is not str
        or scope_state not in {"unfiltered", "restricted"}
        or not _exact_string_tuple(scope_doc_ids)
        or (scope_state == "restricted") != bool(scope_doc_ids)
    ):
        raise ValueError("invalid_lane_search_receipt_scope")
    if (
        type(object.__getattribute__(receipt, "candidate_limit")) is not int
        or object.__getattribute__(receipt, "candidate_limit") < 1
        or type(object.__getattribute__(receipt, "candidate_count")) is not int
        or object.__getattribute__(receipt, "candidate_count") < 0
        or type(object.__getattribute__(receipt, "call_performed")) is not bool
    ):
        raise ValueError("invalid_lane_search_receipt_count")
    ids = object.__getattribute__(receipt, "ordered_evidence_ids")
    anchors = object.__getattribute__(receipt, "ordered_stable_anchors")
    if (
        not _exact_string_tuple(ids) and ids != ()
    ) or type(anchors) is not tuple or any(
        type(anchor) is not StableEvidenceAnchor for anchor in anchors
    ):
        raise ValueError("invalid_lane_search_receipt_projection")
    if (
        len(ids) != len(anchors)
        or len(ids) != object.__getattribute__(receipt, "candidate_count")
        or len(ids) > object.__getattribute__(receipt, "candidate_limit")
    ):
        raise ValueError("lane_search_receipt_candidate_count_mismatch")
    outcome = object.__getattribute__(receipt, "outcome")
    error_code = object.__getattribute__(receipt, "error_code")
    if outcome not in _LANE_OUTCOMES or type(outcome) is not str:
        raise ValueError("invalid_lane_search_receipt_outcome")
    if error_code not in _LANE_ERROR_CODES or type(error_code) is not str:
        raise ValueError("invalid_lane_search_receipt_error")
    if (
        (outcome == "applied") != bool(ids)
        or (outcome == "empty") != (not ids and error_code == "none")
        or (outcome in {"provider_error", "contract_error"})
        != (error_code != "none")
    ):
        raise ValueError("lane_search_receipt_outcome_mismatch")
    call_performed = object.__getattribute__(receipt, "call_performed")
    expected_call_performed = error_code != "lane_dispatch_contract_error"
    if call_performed is not expected_call_performed:
        raise ValueError("lane_search_receipt_call_performed_mismatch")
    for name in (
        "execution_binding_sha256",
        "obligation_sha256",
        "query_sha256",
        "scope_sha256",
        "evidence_store_sha256",
        "execution_config_sha256",
        "runtime_binding_sha256",
        "retrieval_config_sha256",
        "source_receipt_sha256",
        "ledger_transition_sha256",
        "result_sha256",
        "checkpoint_sha256",
        "receipt_sha256",
    ):
        _require_hash(
            object.__getattribute__(receipt, name),
            f"invalid_{name}",
        )
    checkpoint = {
        key: value
        for key, value in _lane_search_receipt_payload(
            receipt, include_hash=False
        ).items()
        if key not in {"error_code", "result_sha256", "checkpoint_sha256"}
    }
    if object.__getattribute__(receipt, "checkpoint_sha256") != _canonical_sha256(
        checkpoint
    ):
        raise ValueError("lane_search_checkpoint_hash_mismatch")
    if object.__getattribute__(receipt, "receipt_sha256") != _canonical_sha256(
        _lane_search_receipt_payload(receipt, include_hash=False)
    ):
        raise ValueError("lane_search_receipt_hash_mismatch")


@dataclass(frozen=True, slots=True)
class _LaneSearchReceiptAuthority:
    weak: ReferenceType[LaneSearchReceipt]
    obligation: RetrievalObligation
    store: EvidenceStore
    config: HarnessExecutionConfig
    runtime: HarnessRuntimeBinding
    result: SearchResult | None
    transition_permit: _LaneClosurePermit
    issued_payload_sha256: str


_LANE_SEARCH_RECEIPT_AUTHORITIES: dict[int, _LaneSearchReceiptAuthority] = {}
_ISSUED_LANE_SEARCH_RECEIPT_AUTHORITIES = _LANE_SEARCH_RECEIPT_AUTHORITIES


def _build_lane_search_receipt_authority_accessors(
    visible: dict[int, _LaneSearchReceiptAuthority],
) -> tuple[FunctionType, FunctionType, FunctionType]:
    """Seal receipt authority fields while retaining weak lifecycle cleanup."""

    shadow: dict[int, tuple[object, ...]] = {}
    authority_lock = Lock()

    def _snapshot(authority: _LaneSearchReceiptAuthority) -> tuple[object, ...]:
        return tuple(
            object.__getattribute__(authority, name)
            for name in (
                "weak",
                "obligation",
                "store",
                "config",
                "runtime",
                "result",
                "transition_permit",
                "issued_payload_sha256",
            )
        )

    def _validated_unlocked(
        receipt: LaneSearchReceipt,
    ) -> _LaneSearchReceiptAuthority | None:
        identity = id(receipt)
        current = dict.get(visible, identity)
        sealed = dict.get(shadow, identity)
        if current is None and sealed is None:
            return None
        if (
            type(current) is not _LaneSearchReceiptAuthority
            or type(sealed) is not tuple
            or len(sealed) != 8
            or tuple.__getitem__(sealed, 0)() is not receipt
        ):
            raise ValueError("lane_search_receipt_runtime_authority_drift")
        current_snapshot = _snapshot(current)
        if any(
            current_value is not sealed_value
            for current_value, sealed_value in zip(current_snapshot, sealed)
        ):
            raise ValueError("lane_search_receipt_runtime_authority_drift")
        return current

    def register(
        receipt: LaneSearchReceipt,
        authority: _LaneSearchReceiptAuthority,
    ) -> None:
        with authority_lock:
            if (
                type(authority) is not _LaneSearchReceiptAuthority
                or _validated_unlocked(receipt) is not None
                or object.__getattribute__(authority, "weak")() is not receipt
            ):
                raise ValueError("lane_search_receipt_runtime_authority_drift")
            identity = id(receipt)
            dict.__setitem__(visible, identity, authority)
            dict.__setitem__(shadow, identity, _snapshot(authority))

    def read(receipt: LaneSearchReceipt) -> _LaneSearchReceiptAuthority:
        with authority_lock:
            current = _validated_unlocked(receipt)
            if current is None:
                raise ValueError("lane_search_receipt_runtime_authority_required")
            return current

    def drop_when_dead(
        identity: int,
        dead: ReferenceType[LaneSearchReceipt],
    ) -> None:
        with authority_lock:
            sealed = dict.get(shadow, identity)
            if (
                type(sealed) is tuple
                and len(sealed) == 8
                and tuple.__getitem__(sealed, 0) is dead
            ):
                dict.pop(visible, identity, None)
                dict.pop(shadow, identity, None)

    return register, read, drop_when_dead


(
    _register_lane_search_receipt_authority,
    _read_lane_search_receipt_authority,
    _drop_lane_search_receipt_authority_when_dead,
) = _build_lane_search_receipt_authority_accessors(
    _ISSUED_LANE_SEARCH_RECEIPT_AUTHORITIES
)


def _drop_lane_search_receipt_authority(
    identity: int,
    dead: ReferenceType[LaneSearchReceipt],
) -> None:
    _drop_lane_search_receipt_authority_when_dead(identity, dead)


def _mint_lane_search_receipt(
    *,
    obligation: RetrievalObligation,
    lane: str,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    result: SearchResult | None,
    evidence_ids: tuple[str, ...],
    anchors: tuple[StableEvidenceAnchor, ...],
    outcome: str,
    error_code: str,
    result_sha256: str,
    call_performed: bool,
    transition_permit: _LaneClosurePermit,
) -> LaneSearchReceipt:
    obligation_authority = _require_retrieval_obligation_authority(obligation)
    ledger_transition_sha256 = _consume_lane_closure_permit(
        transition_permit,
        ledger=object.__getattribute__(obligation_authority, "ledger"),
        obligation_sha256=object.__getattribute__(
            obligation, "obligation_sha256"
        ),
        lane=lane,
        outcome=outcome,
    )
    runtime_config_name = f"{lane}_config_sha256"
    base = {
        "stage": f"lane_{lane}",
        "stage_ordinal": 1 if lane == "dense" else 2,
        "lane": lane,
        "execution_binding_sha256": object.__getattribute__(
            obligation, "execution_binding_sha256"
        ),
        "obligation_sha256": object.__getattribute__(
            obligation, "obligation_sha256"
        ),
        "obligation_key": object.__getattribute__(
            obligation, "obligation_key"
        ),
        "round_index": 1,
        "query_sha256": object.__getattribute__(obligation, "query_sha256"),
        "scope_state": object.__getattribute__(obligation, "scope_state"),
        "scope_origin": object.__getattribute__(obligation, "scope_origin"),
        "scope_doc_ids": object.__getattribute__(obligation, "scope_doc_ids"),
        "scope_sha256": object.__getattribute__(obligation, "scope_sha256"),
        "candidate_limit": object.__getattribute__(obligation, f"{lane}_k"),
        "evidence_store_sha256": object.__getattribute__(
            obligation, "evidence_store_sha256"
        ),
        "execution_config_sha256": object.__getattribute__(
            config, "config_sha256"
        ),
        "runtime_binding_sha256": object.__getattribute__(
            runtime, "binding_sha256"
        ),
        "retrieval_config_sha256": object.__getattribute__(
            runtime, runtime_config_name
        ),
        "source_receipt_sha256": object.__getattribute__(
            obligation, "source_receipt_sha256"
        ),
        "ledger_transition_sha256": ledger_transition_sha256,
        "ordered_evidence_ids": evidence_ids,
        "ordered_stable_anchors": anchors,
        "candidate_count": len(evidence_ids),
        "call_performed": call_performed,
        "outcome": outcome,
        "error_code": error_code,
        "result_sha256": result_sha256,
    }
    provisional = object.__new__(LaneSearchReceipt)
    for name, value in base.items():
        object.__setattr__(provisional, name, value)
    object.__setattr__(provisional, "checkpoint_sha256", "0" * 64)
    checkpoint_payload = {
        "schema_version": SCHEMA_VERSION,
        **{
            key: value
            for key, value in _lane_search_receipt_payload(
                provisional, include_hash=False
            ).items()
            if key not in {"error_code", "result_sha256", "checkpoint_sha256"}
        },
    }
    base["checkpoint_sha256"] = _canonical_sha256(checkpoint_payload)
    provisional_with_checkpoint = object.__new__(LaneSearchReceipt)
    for name, value in base.items():
        object.__setattr__(provisional_with_checkpoint, name, value)
    receipt_payload = _lane_search_receipt_payload(
        provisional_with_checkpoint, include_hash=False
    )
    receipt = LaneSearchReceipt._create(
        payload={
            **base,
            "receipt_sha256": _canonical_sha256(receipt_payload),
        },
        _token=_LANE_SEARCH_RECEIPT_TOKEN,
    )
    identity = id(receipt)
    weak = ref(
        receipt,
        lambda dead, identity=identity,
        drop=_drop_lane_search_receipt_authority: drop(
            identity, dead
        ),
    )
    _register_lane_search_receipt_authority(
        receipt,
        _LaneSearchReceiptAuthority(
            weak=weak,
            obligation=obligation,
            store=store,
            config=config,
            runtime=runtime,
            result=result,
            transition_permit=transition_permit,
            issued_payload_sha256=_canonical_sha256(receipt.to_dict()),
        ),
    )
    return receipt


def execute_retrieval_lane(
    *,
    obligation: RetrievalObligation,
    lane: str,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    _dependency_checker=None,
    _dependency_checker_code=None,
) -> LaneSearchReceipt:
    """Consume and execute one dense or lexical lane exactly once."""

    module_namespace = globals()
    checker_defaults = (
        None
        if type(_dependency_checker) is not FunctionType
        else object.__getattribute__(_dependency_checker, "__defaults__")
    )
    if (
        _dependency_checker
        is not dict.get(
            module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER"
        )
        or type(_dependency_checker) is not FunctionType
        or object.__getattribute__(_dependency_checker, "__code__")
        is not _dependency_checker_code
        or _dependency_checker_code
        is not dict.get(
            module_namespace, "_PINNED_RUNTIME_GATE_DEPENDENCY_CHECKER_CODE"
        )
        or checker_defaults
        is not dict.get(
            module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_DEFAULTS"
        )
        or type(checker_defaults) is not tuple
        or len(checker_defaults) != 6
        or tuple.__getitem__(checker_defaults, 0) is not module_namespace
        or object.__getattribute__(_dependency_checker, "__kwdefaults__")
        is not None
    ):
        raise ValueError("harness_runtime_validation_dependency_drift")
    _dependency_checker()
    if type(obligation) is not RetrievalObligation:
        raise TypeError("retrieval_obligation_required")
    if type(lane) is not str or lane not in _RETRIEVAL_LANES:
        raise ValueError("invalid_retrieval_lane")
    authority = _require_retrieval_obligation_authority(obligation)
    if store is not authority.store:
        raise ValueError("retrieval_obligation_store_identity_mismatch")
    if config is not authority.config:
        raise ValueError("retrieval_obligation_config_identity_mismatch")
    if runtime is not authority.runtime:
        raise ValueError("retrieval_obligation_runtime_identity_mismatch")
    obligation_sha256 = object.__getattribute__(
        obligation, "obligation_sha256"
    )
    _validate_e0_child_execution_caller(authority.ledger)
    authority.ledger._precheck(obligation_sha256, lane)
    _validate_fusion_lane_advance(
        ledger=authority.ledger,
        obligation_sha256=obligation_sha256,
    )
    validate_retrieval_obligation(
        obligation=obligation,
        store=store,
        config=config,
        runtime=runtime,
    )
    scope = ResolvedScope(
        state=object.__getattribute__(obligation, "scope_state"),
        doc_ids=frozenset(
            object.__getattribute__(obligation, "scope_doc_ids")
        ),
        origin=object.__getattribute__(obligation, "scope_origin"),
    )
    limit = object.__getattribute__(obligation, f"{lane}_k")
    query = authority.raw_query
    authority.ledger._claim(obligation_sha256, lane)
    raw_result: object = None
    provider_failed = False
    dispatch_contract_failed = False
    result_contract_failed = False
    call_performed = False
    try:
        raw_result = _ISSUED_HYBRID_SEARCH_LANE(
            _require_harness_runtime_authority(runtime).retriever,
            query,
            lane=lane,
            limit=limit,
            scope=scope,
        )
        call_performed = True
    except _ISSUED_HYBRID_LANE_POST_CALL_CONTRACT_ERROR:
        dispatch_contract_failed = True
        call_performed = True
    except _ISSUED_HYBRID_LANE_PROVIDER_ERROR:
        provider_failed = True
        call_performed = True
    except Exception:
        dispatch_contract_failed = True
    evidence_ids: tuple[str, ...] = ()
    anchors: tuple[StableEvidenceAnchor, ...] = ()
    result_sha256 = ""
    if not provider_failed and not dispatch_contract_failed:
        try:
            evidence_ids, anchors, result_sha256 = _validate_lane_result(
                result=raw_result,
                lane=lane,
                limit=limit,
                obligation=obligation,
                store=store,
            )
        except (TypeError, ValueError):
            result_contract_failed = True
    outcome = (
        "provider_error"
        if provider_failed
        else "contract_error"
        if dispatch_contract_failed or result_contract_failed
        else "applied"
        if evidence_ids
        else "empty"
    )
    transition_permit = authority.ledger._close(
        obligation_sha256,
        lane,
        outcome=outcome,
    )
    if provider_failed:
        return _mint_lane_search_receipt(
            obligation=obligation,
            lane=lane,
            store=store,
            config=config,
            runtime=runtime,
            result=None,
            evidence_ids=(),
            anchors=(),
            outcome="provider_error",
            error_code="lane_provider_error",
            result_sha256=_canonical_sha256(
                {
                    "schema_version": SCHEMA_VERSION,
                    "lane": lane,
                    "outcome": "provider_error",
                }
            ),
            call_performed=call_performed,
            transition_permit=transition_permit,
        )
    if dispatch_contract_failed or result_contract_failed:
        error_code = (
            "lane_post_call_contract_error"
            if dispatch_contract_failed and call_performed
            else "lane_dispatch_contract_error"
            if dispatch_contract_failed
            else "lane_result_contract_error"
        )
        return _mint_lane_search_receipt(
            obligation=obligation,
            lane=lane,
            store=store,
            config=config,
            runtime=runtime,
            result=None,
            evidence_ids=(),
            anchors=(),
            outcome="contract_error",
            error_code=error_code,
            result_sha256=_canonical_sha256(
                {
                    "schema_version": SCHEMA_VERSION,
                    "lane": lane,
                    "outcome": "contract_error",
                    "error_code": error_code,
                }
            ),
            call_performed=call_performed,
            transition_permit=transition_permit,
        )
    return _mint_lane_search_receipt(
        obligation=obligation,
        lane=lane,
        store=store,
        config=config,
        runtime=runtime,
        result=raw_result,
        evidence_ids=evidence_ids,
        anchors=anchors,
        outcome=outcome,
        error_code="none",
        result_sha256=result_sha256,
        call_performed=call_performed,
        transition_permit=transition_permit,
    )


def validate_lane_search_receipt(
    *,
    receipt: LaneSearchReceipt,
    obligation: RetrievalObligation,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    _dependency_checker=None,
    _dependency_checker_code=None,
) -> None:
    module_namespace = globals()
    checker_defaults = (
        None
        if type(_dependency_checker) is not FunctionType
        else object.__getattribute__(_dependency_checker, "__defaults__")
    )
    if (
        _dependency_checker
        is not dict.get(
            module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER"
        )
        or type(_dependency_checker) is not FunctionType
        or object.__getattribute__(_dependency_checker, "__code__")
        is not _dependency_checker_code
        or _dependency_checker_code
        is not dict.get(
            module_namespace, "_PINNED_RUNTIME_GATE_DEPENDENCY_CHECKER_CODE"
        )
        or checker_defaults
        is not dict.get(
            module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_DEFAULTS"
        )
        or type(checker_defaults) is not tuple
        or len(checker_defaults) != 6
        or tuple.__getitem__(checker_defaults, 0) is not module_namespace
        or object.__getattribute__(_dependency_checker, "__kwdefaults__")
        is not None
    ):
        raise ValueError("harness_runtime_validation_dependency_drift")
    _dependency_checker()
    if type(receipt) is not LaneSearchReceipt:
        raise TypeError("lane_search_receipt_required")
    validate_retrieval_obligation(
        obligation=obligation,
        store=store,
        config=config,
        runtime=runtime,
    )
    authority = _read_lane_search_receipt_authority(receipt)
    if (
        type(authority) is not _LaneSearchReceiptAuthority
        or authority.weak() is not receipt
    ):
        raise ValueError("lane_search_receipt_runtime_authority_required")
    if (
        authority.obligation is not obligation
        or authority.store is not store
        or authority.config is not config
        or authority.runtime is not runtime
    ):
        raise ValueError("lane_search_receipt_dependency_identity_mismatch")
    obligation_authority = _require_retrieval_obligation_authority(obligation)
    _validate_consumed_lane_closure_permit(
        object.__getattribute__(authority, "transition_permit"),
        ledger=object.__getattribute__(obligation_authority, "ledger"),
        obligation_sha256=object.__getattribute__(
            receipt, "obligation_sha256"
        ),
        lane=object.__getattribute__(receipt, "lane"),
        outcome=object.__getattribute__(receipt, "outcome"),
        transition_sha256=object.__getattribute__(
            receipt, "ledger_transition_sha256"
        ),
    )
    _validate_lane_search_receipt_payload(receipt)
    if authority.issued_payload_sha256 != _canonical_sha256(receipt.to_dict()):
        raise ValueError("lane_search_receipt_runtime_authority_drift")
    outcome = object.__getattribute__(receipt, "outcome")
    if outcome in {"applied", "empty"}:
        evidence_ids, anchors, result_sha256 = _validate_lane_result(
            result=authority.result,
            lane=object.__getattribute__(receipt, "lane"),
            limit=object.__getattribute__(receipt, "candidate_limit"),
            obligation=obligation,
            store=store,
        )
        if (
            evidence_ids
            != object.__getattribute__(receipt, "ordered_evidence_ids")
            or anchors
            != object.__getattribute__(receipt, "ordered_stable_anchors")
            or result_sha256
            != object.__getattribute__(receipt, "result_sha256")
        ):
            raise ValueError("lane_search_receipt_result_drift")
    elif authority.result is not None:
        raise ValueError("lane_search_receipt_error_result_mismatch")


_ISSUED_EXECUTE_RETRIEVAL_LANE = execute_retrieval_lane
_ISSUED_EXECUTE_RETRIEVAL_LANE_CODE = object.__getattribute__(
    _ISSUED_EXECUTE_RETRIEVAL_LANE, "__code__"
)


def _seal_retrieval_ledger_executor_methods() -> None:
    """Bind ledger mutation to the issued executor without mutable globals."""

    namespace = type.__getattribute__(_RetrievalExecutionLedger, "__dict__")
    claim_impl = namespace["_claim"]
    close_impl = namespace["_close"]
    frame_getter = _GET_FRAME
    executor_code = _ISSUED_EXECUTE_RETRIEVAL_LANE_CODE
    executor_globals = globals()

    def guarded_claim(
        self: _RetrievalExecutionLedger,
        obligation_sha256: str,
        lane: str,
    ) -> None:
        caller = frame_getter(1)
        if (
            object.__getattribute__(caller, "f_code") is not executor_code
            or object.__getattribute__(caller, "f_globals")
            is not executor_globals
        ):
            raise ValueError("retrieval_lane_executor_authority_required")
        _ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER()
        claim_impl(self, obligation_sha256, lane)

    def guarded_close(
        self: _RetrievalExecutionLedger,
        obligation_sha256: str,
        lane: str,
        *,
        outcome: str,
    ) -> _LaneClosurePermit:
        caller = frame_getter(1)
        if (
            object.__getattribute__(caller, "f_code") is not executor_code
            or object.__getattribute__(caller, "f_globals")
            is not executor_globals
        ):
            raise ValueError("retrieval_lane_executor_authority_required")
        _ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER()
        return close_impl(
            self,
            obligation_sha256,
            lane,
            outcome=outcome,
        )

    guarded_claim.__name__ = "_claim"
    guarded_claim.__qualname__ = "_RetrievalExecutionLedger._claim"
    guarded_close.__name__ = "_close"
    guarded_close.__qualname__ = "_RetrievalExecutionLedger._close"
    type.__setattr__(_RetrievalExecutionLedger, "_claim", guarded_claim)
    type.__setattr__(_RetrievalExecutionLedger, "_close", guarded_close)


_seal_retrieval_ledger_executor_methods()
del _seal_retrieval_ledger_executor_methods


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class FusionReceipt:
    """Safe same-round RRF checkpoint issued from two live lane receipts."""

    stage: str
    stage_ordinal: int
    execution_binding_sha256: str
    obligation_sha256: str
    obligation_key: str
    round_index: int
    query_sha256: str
    scope_state: str
    scope_origin: str
    scope_doc_ids: tuple[str, ...]
    scope_sha256: str
    evidence_store_sha256: str
    execution_config_sha256: str
    runtime_binding_sha256: str
    retrieval_config_sha256: str
    source_receipt_sha256: str
    dense_receipt_sha256: str
    lexical_receipt_sha256: str
    rrf_k: int
    ordered_evidence_ids: tuple[str, ...]
    ordered_stable_anchors: tuple[StableEvidenceAnchor, ...]
    dense_only_evidence_ids: tuple[str, ...]
    lexical_only_evidence_ids: tuple[str, ...]
    both_evidence_ids: tuple[str, ...]
    candidate_count: int
    duplicate_count: int
    distinct_doc_count: int
    call_performed: bool
    outcome: str
    result_sha256: str
    checkpoint_sha256: str
    receipt_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("fusion_receipt_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        payload: Mapping[str, Any],
        _token: object,
    ) -> FusionReceipt:
        if _token is not _FUSION_RECEIPT_TOKEN:
            raise ValueError("fusion_receipt_factory_required")
        result = object.__new__(cls)
        for name in cls.__slots__:
            if name != "__weakref__":
                object.__setattr__(result, name, payload[name])
        _validate_fusion_receipt_payload(result)
        return result

    def to_dict(self) -> dict[str, Any]:
        _validate_fusion_receipt_payload(self)
        return _fusion_receipt_payload(self, include_hash=True)


def _fusion_receipt_payload(
    receipt: FusionReceipt,
    *,
    include_hash: bool,
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "stage": object.__getattribute__(receipt, "stage"),
        "stage_ordinal": object.__getattribute__(receipt, "stage_ordinal"),
        "execution_binding_sha256": object.__getattribute__(
            receipt, "execution_binding_sha256"
        ),
        "obligation_sha256": object.__getattribute__(
            receipt, "obligation_sha256"
        ),
        "obligation_key": object.__getattribute__(receipt, "obligation_key"),
        "round_index": object.__getattribute__(receipt, "round_index"),
        "query_sha256": object.__getattribute__(receipt, "query_sha256"),
        "scope_state": object.__getattribute__(receipt, "scope_state"),
        "scope_origin": object.__getattribute__(receipt, "scope_origin"),
        "scope_doc_ids": list(
            object.__getattribute__(receipt, "scope_doc_ids")
        ),
        "scope_sha256": object.__getattribute__(receipt, "scope_sha256"),
        "evidence_store_sha256": object.__getattribute__(
            receipt, "evidence_store_sha256"
        ),
        "execution_config_sha256": object.__getattribute__(
            receipt, "execution_config_sha256"
        ),
        "runtime_binding_sha256": object.__getattribute__(
            receipt, "runtime_binding_sha256"
        ),
        "retrieval_config_sha256": object.__getattribute__(
            receipt, "retrieval_config_sha256"
        ),
        "source_receipt_sha256": object.__getattribute__(
            receipt, "source_receipt_sha256"
        ),
        "dense_receipt_sha256": object.__getattribute__(
            receipt, "dense_receipt_sha256"
        ),
        "lexical_receipt_sha256": object.__getattribute__(
            receipt, "lexical_receipt_sha256"
        ),
        "rrf_k": object.__getattribute__(receipt, "rrf_k"),
        "ordered_evidence_ids": list(
            object.__getattribute__(receipt, "ordered_evidence_ids")
        ),
        "ordered_stable_anchors": [
            anchor.to_dict()
            for anchor in object.__getattribute__(
                receipt, "ordered_stable_anchors"
            )
        ],
        "dense_only_evidence_ids": list(
            object.__getattribute__(receipt, "dense_only_evidence_ids")
        ),
        "lexical_only_evidence_ids": list(
            object.__getattribute__(receipt, "lexical_only_evidence_ids")
        ),
        "both_evidence_ids": list(
            object.__getattribute__(receipt, "both_evidence_ids")
        ),
        "candidate_count": object.__getattribute__(receipt, "candidate_count"),
        "duplicate_count": object.__getattribute__(receipt, "duplicate_count"),
        "distinct_doc_count": object.__getattribute__(
            receipt, "distinct_doc_count"
        ),
        "call_performed": object.__getattribute__(receipt, "call_performed"),
        "outcome": object.__getattribute__(receipt, "outcome"),
        "result_sha256": object.__getattribute__(receipt, "result_sha256"),
        "checkpoint_sha256": object.__getattribute__(
            receipt, "checkpoint_sha256"
        ),
    }
    if include_hash:
        payload["receipt_sha256"] = object.__getattribute__(
            receipt, "receipt_sha256"
        )
    return payload


def _validate_fusion_receipt_payload(receipt: FusionReceipt) -> None:
    if type(receipt) is not FusionReceipt:
        raise TypeError("fusion_receipt_required")
    if (
        object.__getattribute__(receipt, "stage") != "fusion"
        or object.__getattribute__(receipt, "stage_ordinal") != 4
        or object.__getattribute__(receipt, "round_index") != 1
        or object.__getattribute__(receipt, "rrf_k") != 60
        or object.__getattribute__(receipt, "call_performed") is not True
    ):
        raise ValueError("fusion_receipt_stage_mismatch")
    for name in ("obligation_key", "scope_origin"):
        value = object.__getattribute__(receipt, name)
        if type(value) is not str or not value:
            raise ValueError("invalid_fusion_receipt_identity")
    scope_state = object.__getattribute__(receipt, "scope_state")
    scope_doc_ids = object.__getattribute__(receipt, "scope_doc_ids")
    if (
        type(scope_state) is not str
        or scope_state not in {"unfiltered", "restricted"}
        or not _exact_string_tuple(scope_doc_ids)
        or (scope_state == "restricted") != bool(scope_doc_ids)
    ):
        raise ValueError("invalid_fusion_receipt_scope")
    ids = object.__getattribute__(receipt, "ordered_evidence_ids")
    anchors = object.__getattribute__(receipt, "ordered_stable_anchors")
    partitions = tuple(
        object.__getattribute__(receipt, name)
        for name in (
            "dense_only_evidence_ids",
            "lexical_only_evidence_ids",
            "both_evidence_ids",
        )
    )
    if (
        (not _exact_string_tuple(ids) and ids != ())
        or len(ids) != len(set(ids))
        or type(anchors) is not tuple
        or any(type(anchor) is not StableEvidenceAnchor for anchor in anchors)
        or len(ids) != len(anchors)
        or any(
            (not _exact_string_tuple(values) and values != ())
            or tuple(sorted(values)) != values
            or len(values) != len(set(values))
            for values in partitions
        )
        or set(partitions[0]) & set(partitions[1])
        or set(partitions[0]) & set(partitions[2])
        or set(partitions[1]) & set(partitions[2])
        or set(ids) != set().union(*partitions)
    ):
        raise ValueError("invalid_fusion_receipt_projection")
    candidate_count = object.__getattribute__(receipt, "candidate_count")
    duplicate_count = object.__getattribute__(receipt, "duplicate_count")
    distinct_doc_count = object.__getattribute__(receipt, "distinct_doc_count")
    outcome = object.__getattribute__(receipt, "outcome")
    if (
        type(candidate_count) is not int
        or candidate_count != len(ids)
        or type(duplicate_count) is not int
        or duplicate_count != len(partitions[2])
        or type(distinct_doc_count) is not int
        or distinct_doc_count < 0
        or distinct_doc_count > candidate_count
        or type(outcome) is not str
        or outcome not in _FUSION_OUTCOMES
        or (outcome == "applied") != bool(ids)
    ):
        raise ValueError("fusion_receipt_outcome_mismatch")
    for name in (
        "execution_binding_sha256",
        "obligation_sha256",
        "query_sha256",
        "scope_sha256",
        "evidence_store_sha256",
        "execution_config_sha256",
        "runtime_binding_sha256",
        "retrieval_config_sha256",
        "source_receipt_sha256",
        "dense_receipt_sha256",
        "lexical_receipt_sha256",
        "result_sha256",
        "checkpoint_sha256",
        "receipt_sha256",
    ):
        _require_hash(
            object.__getattribute__(receipt, name),
            f"invalid_{name}",
        )
    checkpoint = {
        key: value
        for key, value in _fusion_receipt_payload(
            receipt, include_hash=False
        ).items()
        if key not in {"result_sha256", "checkpoint_sha256"}
    }
    if object.__getattribute__(receipt, "checkpoint_sha256") != _canonical_sha256(
        checkpoint
    ):
        raise ValueError("fusion_checkpoint_hash_mismatch")
    if object.__getattribute__(receipt, "receipt_sha256") != _canonical_sha256(
        _fusion_receipt_payload(receipt, include_hash=False)
    ):
        raise ValueError("fusion_receipt_hash_mismatch")


@dataclass(frozen=True, slots=True, init=False)
class E0ObligationResult:
    obligation_key: str
    obligation_sha256: str
    ordinal: int
    attempted: bool
    dense_receipt_sha256: str | None
    lexical_receipt_sha256: str | None
    fusion_receipt_sha256: str | None
    candidate_count: int
    status: str
    error_code: str
    result_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("e0_obligation_result_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        payload: Mapping[str, Any],
        _token: object,
    ) -> E0ObligationResult:
        if _token is not _E0_CONTROL_RECEIPT_TOKEN:
            raise ValueError("e0_obligation_result_factory_required")
        result = object.__new__(cls)
        for name in cls.__slots__:
            object.__setattr__(result, name, payload[name])
        result.__post_init__()
        return result

    def __post_init__(self) -> None:
        if type(self.obligation_key) is not str or not self.obligation_key:
            raise ValueError("invalid_e0_obligation_identity")
        _require_hash(self.obligation_sha256, "invalid_e0_obligation_hash")
        if type(self.ordinal) is not int or self.ordinal < 1:
            raise ValueError("invalid_e0_obligation_ordinal")
        if type(self.attempted) is not bool:
            raise ValueError("invalid_e0_obligation_attempted")
        for value in (
            self.dense_receipt_sha256,
            self.lexical_receipt_sha256,
            self.fusion_receipt_sha256,
        ):
            if value is not None:
                _require_hash(value, "invalid_e0_child_receipt_hash")
        if type(self.candidate_count) is not int or self.candidate_count < 0:
            raise ValueError("invalid_e0_candidate_count")
        if self.status not in _E0_STATUSES or type(self.status) is not str:
            raise ValueError("invalid_e0_obligation_status")
        if self.error_code not in _E0_ERROR_CODES or type(self.error_code) is not str:
            raise ValueError("invalid_e0_obligation_error")
        if self.status in {"retrieved", "empty"}:
            if (
                not self.attempted
                or self.dense_receipt_sha256 is None
                or self.lexical_receipt_sha256 is None
                or self.fusion_receipt_sha256 is None
                or self.error_code != "none"
                or (self.status == "retrieved") != (self.candidate_count > 0)
            ):
                raise ValueError("e0_obligation_result_mismatch")
        elif (
            self.error_code == "none"
            or self.fusion_receipt_sha256 is not None
            or self.candidate_count != 0
            or (
                not self.attempted
                and (
                    self.dense_receipt_sha256 is not None
                    or self.lexical_receipt_sha256 is not None
                )
            )
        ):
            raise ValueError("e0_obligation_result_mismatch")
        if self.result_sha256 != _canonical_sha256(self._payload()):
            raise ValueError("e0_obligation_result_hash_mismatch")

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "obligation_key": self.obligation_key,
            "obligation_sha256": self.obligation_sha256,
            "ordinal": self.ordinal,
            "attempted": self.attempted,
            "dense_receipt_sha256": self.dense_receipt_sha256,
            "lexical_receipt_sha256": self.lexical_receipt_sha256,
            "fusion_receipt_sha256": self.fusion_receipt_sha256,
            "candidate_count": self.candidate_count,
            "status": self.status,
            "error_code": self.error_code,
        }

    def to_dict(self) -> dict[str, Any]:
        self.__post_init__()
        return {**self._payload(), "result_sha256": self.result_sha256}


def _make_e0_obligation_result(
    *,
    obligation: RetrievalObligation,
    attempted: bool,
    dense_receipt: LaneSearchReceipt | None,
    lexical_receipt: LaneSearchReceipt | None,
    fusion_receipt: FusionReceipt | None,
    status: str,
    error_code: str,
) -> E0ObligationResult:
    base = {
        "obligation_key": object.__getattribute__(obligation, "obligation_key"),
        "obligation_sha256": object.__getattribute__(
            obligation, "obligation_sha256"
        ),
        "ordinal": object.__getattribute__(obligation, "ordinal"),
        "attempted": attempted,
        "dense_receipt_sha256": (
            None
            if dense_receipt is None
            else object.__getattribute__(dense_receipt, "receipt_sha256")
        ),
        "lexical_receipt_sha256": (
            None
            if lexical_receipt is None
            else object.__getattribute__(lexical_receipt, "receipt_sha256")
        ),
        "fusion_receipt_sha256": (
            None
            if fusion_receipt is None
            else object.__getattribute__(fusion_receipt, "receipt_sha256")
        ),
        "candidate_count": (
            0
            if fusion_receipt is None
            else object.__getattribute__(fusion_receipt, "candidate_count")
        ),
        "status": status,
        "error_code": error_code,
    }
    provisional = object.__new__(E0ObligationResult)
    for name, value in base.items():
        object.__setattr__(provisional, name, value)
    return E0ObligationResult._create(
        payload={
            **base,
            "result_sha256": _canonical_sha256(provisional._payload()),
        },
        _token=_E0_CONTROL_RECEIPT_TOKEN,
    )


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class E0ControlReceipt:
    mode: str
    source_kind: str
    execution_binding_sha256: str
    source_receipt_sha256: str
    evidence_store_sha256: str
    execution_config_sha256: str
    runtime_binding_sha256: str
    ordered_obligation_sha256s: tuple[str, ...]
    ordered_results: tuple[E0ObligationResult, ...]
    nonempty_obligation_keys: tuple[str, ...]
    empty_obligation_keys: tuple[str, ...]
    unavailable_obligation_keys: tuple[str, ...]
    error_obligation_keys: tuple[str, ...]
    outcome: str
    execution_complete: bool
    receipt_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("e0_control_receipt_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        payload: Mapping[str, Any],
        _token: object,
    ) -> E0ControlReceipt:
        if _token is not _E0_CONTROL_RECEIPT_TOKEN:
            raise ValueError("e0_control_receipt_factory_required")
        result = object.__new__(cls)
        for name in cls.__slots__:
            if name != "__weakref__":
                object.__setattr__(result, name, payload[name])
        _validate_e0_control_receipt_payload(result)
        return result

    def to_dict(self) -> dict[str, Any]:
        _validate_e0_control_receipt_payload(self)
        return _e0_control_receipt_payload(self, include_hash=True)


def _e0_control_receipt_payload(
    receipt: E0ControlReceipt,
    *,
    include_hash: bool,
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "mode": object.__getattribute__(receipt, "mode"),
        "source_kind": object.__getattribute__(receipt, "source_kind"),
        "execution_binding_sha256": object.__getattribute__(
            receipt, "execution_binding_sha256"
        ),
        "source_receipt_sha256": object.__getattribute__(
            receipt, "source_receipt_sha256"
        ),
        "evidence_store_sha256": object.__getattribute__(
            receipt, "evidence_store_sha256"
        ),
        "execution_config_sha256": object.__getattribute__(
            receipt, "execution_config_sha256"
        ),
        "runtime_binding_sha256": object.__getattribute__(
            receipt, "runtime_binding_sha256"
        ),
        "ordered_obligation_sha256s": list(
            object.__getattribute__(receipt, "ordered_obligation_sha256s")
        ),
        "ordered_results": [
            result.to_dict()
            for result in object.__getattribute__(receipt, "ordered_results")
        ],
        "nonempty_obligation_keys": list(
            object.__getattribute__(receipt, "nonempty_obligation_keys")
        ),
        "empty_obligation_keys": list(
            object.__getattribute__(receipt, "empty_obligation_keys")
        ),
        "unavailable_obligation_keys": list(
            object.__getattribute__(receipt, "unavailable_obligation_keys")
        ),
        "error_obligation_keys": list(
            object.__getattribute__(receipt, "error_obligation_keys")
        ),
        "outcome": object.__getattribute__(receipt, "outcome"),
        "execution_complete": object.__getattribute__(
            receipt, "execution_complete"
        ),
    }
    if include_hash:
        payload["receipt_sha256"] = object.__getattribute__(
            receipt, "receipt_sha256"
        )
    return payload


def _validate_e0_control_receipt_payload(receipt: E0ControlReceipt) -> None:
    if type(receipt) is not E0ControlReceipt:
        raise TypeError("e0_control_receipt_required")
    if object.__getattribute__(receipt, "mode") != "e0_once":
        raise ValueError("e0_control_mode_mismatch")
    source_kind = object.__getattribute__(receipt, "source_kind")
    if type(source_kind) is not str or source_kind not in _RETRIEVAL_SOURCE_KINDS:
        raise ValueError("invalid_e0_control_source")
    hashes = object.__getattribute__(receipt, "ordered_obligation_sha256s")
    results = object.__getattribute__(receipt, "ordered_results")
    if (
        type(hashes) is not tuple
        or not hashes
        or len(hashes) != len(set(hashes))
        or type(results) is not tuple
        or len(results) != len(hashes)
        or any(type(result) is not E0ObligationResult for result in results)
    ):
        raise ValueError("invalid_e0_control_results")
    for index, (value, result) in enumerate(zip(hashes, results), 1):
        _require_hash(value, "invalid_e0_obligation_hash")
        result.__post_init__()
        if result.obligation_sha256 != value or result.ordinal != index:
            raise ValueError("e0_control_result_order_mismatch")
    expected_partitions = {
        "nonempty_obligation_keys": tuple(
            result.obligation_key
            for result in results
            if result.status == "retrieved"
        ),
        "empty_obligation_keys": tuple(
            result.obligation_key for result in results if result.status == "empty"
        ),
        "unavailable_obligation_keys": tuple(
            result.obligation_key
            for result in results
            if result.status == "unavailable"
        ),
        "error_obligation_keys": tuple(
            result.obligation_key for result in results if result.status == "error"
        ),
    }
    for name, expected in expected_partitions.items():
        actual = object.__getattribute__(receipt, name)
        if actual != expected or (not _exact_string_tuple(actual) and actual != ()):
            raise ValueError("e0_control_partition_mismatch")
    statuses = tuple(result.status for result in results)
    expected_outcome = (
        "error"
        if "error" in statuses
        else "unavailable"
        if "unavailable" in statuses
        else "empty"
        if all(status == "empty" for status in statuses)
        else "retrieved"
    )
    if (
        object.__getattribute__(receipt, "outcome") != expected_outcome
        or object.__getattribute__(receipt, "execution_complete")
        is not all(status in {"retrieved", "empty"} for status in statuses)
    ):
        raise ValueError("e0_control_outcome_mismatch")
    for name in (
        "execution_binding_sha256",
        "source_receipt_sha256",
        "evidence_store_sha256",
        "execution_config_sha256",
        "runtime_binding_sha256",
        "receipt_sha256",
    ):
        _require_hash(
            object.__getattribute__(receipt, name),
            f"invalid_{name}",
        )
    if object.__getattribute__(receipt, "receipt_sha256") != _canonical_sha256(
        _e0_control_receipt_payload(receipt, include_hash=False)
    ):
        raise ValueError("e0_control_receipt_hash_mismatch")


def _validate_fusion_result(
    *,
    result: object,
    obligation: RetrievalObligation,
    dense_result: SearchResult,
    lexical_result: SearchResult,
    store: EvidenceStore,
    rrf_k: int,
) -> tuple[
    tuple[str, ...],
    tuple[StableEvidenceAnchor, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    int,
    str,
]:
    if type(result) is not SearchResult or rrf_k != 60:
        raise ValueError("fusion_search_result_type_mismatch")
    candidates = object.__getattribute__(result, "candidates")
    trace = object.__getattribute__(result, "trace")
    if (
        type(candidates) is not tuple
        or type(trace) is not MappingProxyType
        or trace.get("lane") != "rrf"
        or trace.get("rrf_k") != rrf_k
        or trace.get("granularity") != "child"
        or trace.get("bundle_sha256")
        != object.__getattribute__(store, "bundle_sha256")
    ):
        raise ValueError("fusion_search_result_contract_mismatch")
    dense_candidates = object.__getattribute__(dense_result, "candidates")
    lexical_candidates = object.__getattribute__(lexical_result, "candidates")
    dense_ids = tuple(
        object.__getattribute__(candidate, "evidence_id")
        for candidate in dense_candidates
    )
    lexical_ids = tuple(
        object.__getattribute__(candidate, "evidence_id")
        for candidate in lexical_candidates
    )
    dense_set = set(dense_ids)
    lexical_set = set(lexical_ids)
    expected_scores: dict[str, float] = {}
    for values in (dense_ids, lexical_ids):
        for position, evidence_id in enumerate(values, 1):
            expected_scores[evidence_id] = expected_scores.get(
                evidence_id, 0.0
            ) + 1 / (rrf_k + position)
    expected_ids = tuple(
        sorted(
            expected_scores,
            key=lambda identity: (-expected_scores[identity], identity),
        )
    )
    if len(candidates) != len(expected_ids):
        raise ValueError("fusion_candidate_set_mismatch")
    allowed_doc_ids = (
        None
        if object.__getattribute__(obligation, "scope_state") == "unfiltered"
        else frozenset(object.__getattribute__(obligation, "scope_doc_ids"))
    )
    anchors: list[StableEvidenceAnchor] = []
    doc_ids: set[str] = set()
    for rank, (candidate, expected_id) in enumerate(
        zip(candidates, expected_ids), 1
    ):
        if type(candidate) is not Candidate:
            raise ValueError("fusion_candidate_contract_mismatch")
        evidence_id = object.__getattribute__(candidate, "evidence_id")
        doc_id = object.__getattribute__(candidate, "doc_id")
        score = object.__getattribute__(candidate, "score")
        if (
            evidence_id != expected_id
            or type(doc_id) is not str
            or not doc_id
            or type(score) not in (int, float)
            or not math.isfinite(score)
            or score != expected_scores[evidence_id]
            or object.__getattribute__(candidate, "lane") != "rrf"
            or object.__getattribute__(candidate, "rank") != rank
            or object.__getattribute__(candidate, "granularity") != "child"
            or (allowed_doc_ids is not None and doc_id not in allowed_doc_ids)
        ):
            raise ValueError("fusion_candidate_contract_mismatch")
        try:
            evidence = EvidenceStore.get(store, evidence_id)
        except KeyError as exc:
            raise ValueError("fusion_candidate_unknown_evidence") from exc
        if (
            object.__getattribute__(evidence, "doc_id") != doc_id
            or object.__getattribute__(evidence, "kind") != "text"
        ):
            raise ValueError("fusion_candidate_evidence_mismatch")
        anchors.append(_stable_anchor(evidence))
        doc_ids.add(doc_id)
    dense_only = tuple(sorted(dense_set - lexical_set))
    lexical_only = tuple(sorted(lexical_set - dense_set))
    both = tuple(sorted(dense_set & lexical_set))
    if (
        tuple(trace.get("dense_only", ())) != dense_only
        or tuple(trace.get("lexical_only", ())) != lexical_only
        or tuple(trace.get("both", ())) != both
        or trace.get("duplicate_count") != len(both)
        or trace.get("distinct_doc_count") != len(doc_ids)
    ):
        raise ValueError("fusion_trace_partition_mismatch")
    safe_result = {
        "schema_version": SCHEMA_VERSION,
        "lane": "rrf",
        "rrf_k": rrf_k,
        "ordered_evidence_ids": list(expected_ids),
        "ordered_stable_anchors": [anchor.to_dict() for anchor in anchors],
        "dense_only_evidence_ids": list(dense_only),
        "lexical_only_evidence_ids": list(lexical_only),
        "both_evidence_ids": list(both),
        "duplicate_count": len(both),
        "distinct_doc_count": len(doc_ids),
    }
    return (
        expected_ids,
        tuple(anchors),
        dense_only,
        lexical_only,
        both,
        len(doc_ids),
        _canonical_sha256(safe_result),
    )


@dataclass(frozen=True, slots=True, weakref_slot=True)
class _FusionExecutionClaim:
    ledger: _RetrievalExecutionLedger
    obligation_sha256: str
    dense_receipt: LaneSearchReceipt
    lexical_receipt: LaneSearchReceipt


@dataclass(frozen=True, slots=True, weakref_slot=True)
class _FusionClosurePermit:
    claim: _FusionExecutionClaim
    outcome: str
    result_sha256: str


@dataclass(frozen=True, slots=True)
class _FusionReceiptAuthority:
    weak: ReferenceType[FusionReceipt]
    obligation: RetrievalObligation
    dense_receipt: LaneSearchReceipt
    lexical_receipt: LaneSearchReceipt
    store: EvidenceStore
    config: HarnessExecutionConfig
    runtime: HarnessRuntimeBinding
    result: SearchResult
    execution_permit: _FusionClosurePermit
    issued_payload_sha256: str


_FUSION_RECEIPT_AUTHORITIES: dict[int, _FusionReceiptAuthority] = {}
_ISSUED_FUSION_RECEIPT_AUTHORITIES = _FUSION_RECEIPT_AUTHORITIES


def _build_fusion_receipt_authority_accessors(
    visible: dict[int, _FusionReceiptAuthority],
) -> tuple[FunctionType, FunctionType, FunctionType]:
    shadow: dict[int, tuple[object, ...]] = {}
    authority_lock = Lock()

    def snapshot(authority: _FusionReceiptAuthority) -> tuple[object, ...]:
        return tuple(
            object.__getattribute__(authority, name)
            for name in (
                "weak",
                "obligation",
                "dense_receipt",
                "lexical_receipt",
                "store",
                "config",
                "runtime",
                "result",
                "execution_permit",
                "issued_payload_sha256",
            )
        )

    def register(
        receipt: FusionReceipt,
        authority: _FusionReceiptAuthority,
    ) -> None:
        with authority_lock:
            identity = id(receipt)
            if (
                type(receipt) is not FusionReceipt
                or type(authority) is not _FusionReceiptAuthority
                or object.__getattribute__(authority, "weak")() is not receipt
                or dict.get(visible, identity) is not None
                or dict.get(shadow, identity) is not None
            ):
                raise ValueError("fusion_receipt_runtime_authority_drift")
            values = snapshot(authority)
            dict.__setitem__(visible, identity, authority)
            dict.__setitem__(shadow, identity, values)

    def read(receipt: FusionReceipt) -> _FusionReceiptAuthority:
        with authority_lock:
            current = dict.get(visible, id(receipt))
            sealed = dict.get(shadow, id(receipt))
            if (
                type(current) is not _FusionReceiptAuthority
                or type(sealed) is not tuple
                or len(sealed) != 10
                or tuple.__getitem__(sealed, 0)() is not receipt
                or any(
                    current_value is not sealed_value
                    for current_value, sealed_value in zip(
                        snapshot(current), sealed
                    )
                )
            ):
                raise ValueError("fusion_receipt_runtime_authority_drift")
            return current

    def drop_when_dead(identity: int, dead: ReferenceType[FusionReceipt]) -> None:
        with authority_lock:
            sealed = dict.get(shadow, identity)
            if (
                type(sealed) is tuple
                and len(sealed) == 10
                and tuple.__getitem__(sealed, 0) is dead
            ):
                dict.pop(visible, identity, None)
                dict.pop(shadow, identity, None)

    return register, read, drop_when_dead


(
    _register_fusion_receipt_authority,
    _read_fusion_receipt_authority,
    _drop_fusion_receipt_authority_when_dead,
) = _build_fusion_receipt_authority_accessors(
    _ISSUED_FUSION_RECEIPT_AUTHORITIES
)


def _drop_fusion_receipt_authority(
    identity: int,
    dead: ReferenceType[FusionReceipt],
) -> None:
    _drop_fusion_receipt_authority_when_dead(identity, dead)


def _build_fusion_execution_accessors(
    *,
    executor_code: CodeType,
    mint_code: CodeType,
    lane_executor_code: CodeType,
    module_globals: dict[str, Any],
) -> tuple[
    FunctionType,
    FunctionType,
    FunctionType,
    FunctionType,
    FunctionType,
    FunctionType,
    FunctionType,
]:
    progress: dict[
        int,
        tuple[ReferenceType[_RetrievalExecutionLedger], tuple[tuple[str, str], ...]],
    ] = {}
    history: dict[
        int,
        tuple[ReferenceType[_RetrievalExecutionLedger], tuple[tuple[str, str], ...]],
    ] = {}
    claims: dict[int, tuple[object, ...]] = {}
    permits: dict[int, tuple[object, ...]] = {}
    progress_lock = Lock()
    frame_getter = _GET_FRAME

    def drop_claim(identity: int, dead: ReferenceType[object]) -> None:
        with progress_lock:
            current = dict.get(claims, identity)
            if current is not None and tuple.__getitem__(current, 0) is dead:
                dict.pop(claims, identity, None)

    def drop_permit(identity: int, dead: ReferenceType[object]) -> None:
        with progress_lock:
            current = dict.get(permits, identity)
            if current is not None and tuple.__getitem__(current, 0) is dead:
                dict.pop(permits, identity, None)

    def drop_ledger(identity: int, dead: ReferenceType[object]) -> None:
        with progress_lock:
            current = dict.get(progress, identity)
            sealed = dict.get(history, identity)
            if (
                current is not None
                and sealed is current
                and tuple.__getitem__(current, 0) is dead
            ):
                dict.pop(progress, identity, None)
                dict.pop(history, identity, None)

    def claim(
        *,
        ledger: _RetrievalExecutionLedger,
        obligation: RetrievalObligation,
        dense_receipt: LaneSearchReceipt,
        lexical_receipt: LaneSearchReceipt,
    ) -> _FusionExecutionClaim:
        caller = frame_getter(1)
        if (
            object.__getattribute__(caller, "f_code") is not executor_code
            or object.__getattribute__(caller, "f_globals") is not module_globals
        ):
            raise ValueError("fusion_executor_authority_required")
        _ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER()
        with progress_lock:
            ledger._validate()
            ledger_id = id(ledger)
            obligation_sha256 = object.__getattribute__(
                obligation, "obligation_sha256"
            )
            for recorded in tuple(dict.values(claims)):
                if (
                    type(recorded) is not tuple
                    or len(recorded) != 6
                    or type(tuple.__getitem__(recorded, 0)) is not ReferenceType
                    or tuple.__getitem__(recorded, 0)() is None
                    or tuple.__getitem__(recorded, 5)
                    not in {"pending", "complete", "error"}
                ):
                    raise ValueError("fusion_execution_authority_drift")
                if (
                    tuple.__getitem__(recorded, 1) is ledger
                    and tuple.__getitem__(recorded, 2) == obligation_sha256
                ):
                    raise ValueError("fusion_pair_already_consumed")
            current = dict.get(progress, ledger_id)
            sealed = dict.get(history, ledger_id)
            entries: tuple[tuple[str, str], ...] = ()
            if (current is None) is not (sealed is None):
                raise ValueError("fusion_execution_authority_drift")
            if current is not None:
                if (
                    type(current) is not tuple
                    or len(current) != 2
                    or sealed is not current
                    or tuple.__getitem__(current, 0)() is not ledger
                    or type(tuple.__getitem__(current, 1)) is not tuple
                ):
                    raise ValueError("fusion_execution_authority_drift")
                entries = tuple.__getitem__(current, 1)
            obligations = object.__getattribute__(ledger, "_obligation_sha256s")
            try:
                index = obligations.index(obligation_sha256)
            except ValueError as exc:
                raise ValueError("fusion_execution_ledger_mismatch") from exc
            expected_pairs = frozenset(
                (value, lane)
                for value in obligations[: index + 1]
                for lane in ("dense", "lexical")
            )
            if (
                object.__getattribute__(ledger, "_claimed") != expected_pairs
                or object.__getattribute__(ledger, "_closed") != expected_pairs
                or object.__getattribute__(ledger, "_status") != "active"
            ):
                raise ValueError("fusion_execution_order_violation")
            expected_previous = tuple(
                (value, "complete") for value in obligations[:index]
            )
            if entries != expected_previous:
                if any(value == obligation_sha256 for value, _ in entries):
                    raise ValueError("fusion_pair_already_consumed")
                raise ValueError("fusion_execution_order_violation")
            claim_value = _FusionExecutionClaim(
                ledger=ledger,
                obligation_sha256=obligation_sha256,
                dense_receipt=dense_receipt,
                lexical_receipt=lexical_receipt,
            )
            claim_weak = ref(
                claim_value,
                lambda dead, identity=id(claim_value): drop_claim(
                    identity, dead
                ),
            )
            dict.__setitem__(
                claims,
                id(claim_value),
                (
                    claim_weak,
                    ledger,
                    obligation_sha256,
                    dense_receipt,
                    lexical_receipt,
                    "pending",
                ),
            )
            ledger_weak = (
                tuple.__getitem__(current, 0)
                if current is not None
                else ref(
                    ledger,
                    lambda dead, identity=ledger_id: drop_ledger(identity, dead),
                )
            )
            progress_entry = (
                ledger_weak,
                entries + ((obligation_sha256, "pending"),),
            )
            dict.__setitem__(progress, ledger_id, progress_entry)
            dict.__setitem__(history, ledger_id, progress_entry)
            return claim_value

    def close(
        claim_value: _FusionExecutionClaim,
        *,
        outcome: str,
        result_sha256: str,
    ) -> _FusionClosurePermit:
        caller = frame_getter(1)
        if (
            object.__getattribute__(caller, "f_code") is not executor_code
            or object.__getattribute__(caller, "f_globals") is not module_globals
        ):
            raise ValueError("fusion_executor_authority_required")
        _ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER()
        with progress_lock:
            current = dict.get(claims, id(claim_value))
            if (
                type(current) is not tuple
                or len(current) != 6
                or tuple.__getitem__(current, 0)() is not claim_value
                or tuple.__getitem__(current, 5) != "pending"
                or outcome not in _FUSION_OUTCOMES
            ):
                raise ValueError("fusion_execution_claim_mismatch")
            _require_hash(result_sha256, "invalid_fusion_result_hash")
            ledger = tuple.__getitem__(current, 1)
            obligation_sha256 = tuple.__getitem__(current, 2)
            progress_entry = dict.get(progress, id(ledger))
            history_entry = dict.get(history, id(ledger))
            if history_entry is not progress_entry:
                raise ValueError("fusion_execution_authority_drift")
            entries = tuple.__getitem__(progress_entry, 1)
            if entries[-1] != (obligation_sha256, "pending"):
                raise ValueError("fusion_execution_authority_drift")
            completed_entry = (
                tuple.__getitem__(progress_entry, 0),
                entries[:-1] + ((obligation_sha256, "complete"),),
            )
            dict.__setitem__(progress, id(ledger), completed_entry)
            dict.__setitem__(history, id(ledger), completed_entry)
            dict.__setitem__(claims, id(claim_value), current[:-1] + ("complete",))
            permit = _FusionClosurePermit(
                claim=claim_value,
                outcome=outcome,
                result_sha256=result_sha256,
            )
            permit_weak = ref(
                permit,
                lambda dead, identity=id(permit): drop_permit(identity, dead),
            )
            dict.__setitem__(
                permits,
                id(permit),
                (permit_weak, claim_value, outcome, result_sha256, False, None),
            )
            return permit

    def fail(claim_value: _FusionExecutionClaim) -> None:
        caller = frame_getter(1)
        if (
            object.__getattribute__(caller, "f_code") is not executor_code
            or object.__getattribute__(caller, "f_globals") is not module_globals
        ):
            raise ValueError("fusion_executor_authority_required")
        _ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER()
        with progress_lock:
            current = dict.get(claims, id(claim_value))
            if (
                type(current) is not tuple
                or len(current) != 6
                or tuple.__getitem__(current, 0)() is not claim_value
                or tuple.__getitem__(current, 5) != "pending"
            ):
                raise ValueError("fusion_execution_claim_mismatch")
            ledger = tuple.__getitem__(current, 1)
            obligation_sha256 = tuple.__getitem__(current, 2)
            progress_entry = dict.get(progress, id(ledger))
            history_entry = dict.get(history, id(ledger))
            if history_entry is not progress_entry:
                raise ValueError("fusion_execution_authority_drift")
            entries = tuple.__getitem__(progress_entry, 1)
            error_entry = (
                tuple.__getitem__(progress_entry, 0),
                entries[:-1] + ((obligation_sha256, "error"),),
            )
            dict.__setitem__(progress, id(ledger), error_entry)
            dict.__setitem__(history, id(ledger), error_entry)
            dict.__setitem__(claims, id(claim_value), current[:-1] + ("error",))

    def consume(
        permit: _FusionClosurePermit,
        receipt: FusionReceipt,
    ) -> None:
        caller = frame_getter(1)
        if (
            object.__getattribute__(caller, "f_code") is not mint_code
            or object.__getattribute__(caller, "f_globals") is not module_globals
        ):
            raise ValueError("fusion_receipt_mint_authority_required")
        _ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER()
        with progress_lock:
            current = dict.get(permits, id(permit))
            if (
                type(current) is not tuple
                or len(current) != 6
                or tuple.__getitem__(current, 0)() is not permit
                or tuple.__getitem__(current, 4) is not False
                or tuple.__getitem__(current, 5) is not None
            ):
                raise ValueError("fusion_execution_permit_mismatch")
            receipt_weak = ref(receipt)
            dict.__setitem__(
                permits,
                id(permit),
                current[:4] + (True, receipt_weak),
            )

    def validate(permit: _FusionClosurePermit, receipt: FusionReceipt) -> None:
        with progress_lock:
            current = dict.get(permits, id(permit))
            if (
                type(current) is not tuple
                or len(current) != 6
                or tuple.__getitem__(current, 0)() is not permit
                or tuple.__getitem__(current, 4) is not True
                or type(tuple.__getitem__(current, 5)) is not ReferenceType
                or tuple.__getitem__(current, 5)() is not receipt
            ):
                raise ValueError("fusion_execution_permit_mismatch")

    def pristine(ledger: _RetrievalExecutionLedger) -> bool:
        with progress_lock:
            for recorded in tuple(dict.values(claims)):
                if (
                    type(recorded) is not tuple
                    or len(recorded) != 6
                    or type(tuple.__getitem__(recorded, 0)) is not ReferenceType
                    or tuple.__getitem__(recorded, 0)() is None
                    or tuple.__getitem__(recorded, 5)
                    not in {"pending", "complete", "error"}
                ):
                    raise ValueError("fusion_execution_authority_drift")
                if tuple.__getitem__(recorded, 1) is ledger:
                    return False
            current = dict.get(progress, id(ledger))
            sealed = dict.get(history, id(ledger))
            if (current is None) is not (sealed is None):
                raise ValueError("fusion_execution_authority_drift")
            if current is None:
                return True
            if (
                type(current) is not tuple
                or len(current) != 2
                or sealed is not current
                or tuple.__getitem__(current, 0)() is not ledger
            ):
                raise ValueError("fusion_execution_authority_drift")
            return tuple.__getitem__(current, 1) == ()

    def validate_lane_advance(
        *,
        ledger: _RetrievalExecutionLedger,
        obligation_sha256: str,
    ) -> None:
        """Block obligation N+1 lanes until obligation N fusion is complete."""

        caller = frame_getter(1)
        if (
            object.__getattribute__(caller, "f_code") is not lane_executor_code
            or object.__getattribute__(caller, "f_globals") is not module_globals
        ):
            raise ValueError("retrieval_lane_executor_authority_required")
        with progress_lock:
            ledger._validate()
            obligations = object.__getattribute__(ledger, "_obligation_sha256s")
            try:
                index = obligations.index(obligation_sha256)
            except ValueError as exc:
                raise ValueError("fusion_execution_ledger_mismatch") from exc
            current = dict.get(progress, id(ledger))
            sealed = dict.get(history, id(ledger))
            entries: tuple[tuple[str, str], ...] = ()
            if (current is None) is not (sealed is None):
                raise ValueError("fusion_execution_authority_drift")
            if current is not None:
                if (
                    type(current) is not tuple
                    or len(current) != 2
                    or sealed is not current
                    or tuple.__getitem__(current, 0)() is not ledger
                    or type(tuple.__getitem__(current, 1)) is not tuple
                ):
                    raise ValueError("fusion_execution_authority_drift")
                entries = tuple.__getitem__(current, 1)
            expected_previous = tuple(
                (value, "complete") for value in obligations[:index]
            )
            if entries != expected_previous:
                raise ValueError("fusion_execution_order_violation")

    return claim, close, fail, consume, validate, pristine, validate_lane_advance


def _mint_fusion_receipt(
    *,
    obligation: RetrievalObligation,
    dense_receipt: LaneSearchReceipt,
    lexical_receipt: LaneSearchReceipt,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    result: SearchResult,
    evidence_ids: tuple[str, ...],
    anchors: tuple[StableEvidenceAnchor, ...],
    dense_only: tuple[str, ...],
    lexical_only: tuple[str, ...],
    both: tuple[str, ...],
    distinct_doc_count: int,
    outcome: str,
    result_sha256: str,
    execution_permit: _FusionClosurePermit,
) -> FusionReceipt:
    base = {
        "stage": "fusion",
        "stage_ordinal": 4,
        "execution_binding_sha256": obligation.execution_binding_sha256,
        "obligation_sha256": obligation.obligation_sha256,
        "obligation_key": obligation.obligation_key,
        "round_index": obligation.round_index,
        "query_sha256": obligation.query_sha256,
        "scope_state": obligation.scope_state,
        "scope_origin": obligation.scope_origin,
        "scope_doc_ids": obligation.scope_doc_ids,
        "scope_sha256": obligation.scope_sha256,
        "evidence_store_sha256": obligation.evidence_store_sha256,
        "execution_config_sha256": config.config_sha256,
        "runtime_binding_sha256": runtime.binding_sha256,
        "retrieval_config_sha256": runtime.fusion_config_sha256,
        "source_receipt_sha256": obligation.source_receipt_sha256,
        "dense_receipt_sha256": dense_receipt.receipt_sha256,
        "lexical_receipt_sha256": lexical_receipt.receipt_sha256,
        "rrf_k": config.rrf_k,
        "ordered_evidence_ids": evidence_ids,
        "ordered_stable_anchors": anchors,
        "dense_only_evidence_ids": dense_only,
        "lexical_only_evidence_ids": lexical_only,
        "both_evidence_ids": both,
        "candidate_count": len(evidence_ids),
        "duplicate_count": len(both),
        "distinct_doc_count": distinct_doc_count,
        "call_performed": True,
        "outcome": outcome,
        "result_sha256": result_sha256,
    }
    provisional = object.__new__(FusionReceipt)
    for name, value in base.items():
        object.__setattr__(provisional, name, value)
    object.__setattr__(provisional, "checkpoint_sha256", "0" * 64)
    checkpoint = {
        key: value
        for key, value in _fusion_receipt_payload(
            provisional, include_hash=False
        ).items()
        if key not in {"result_sha256", "checkpoint_sha256"}
    }
    base["checkpoint_sha256"] = _canonical_sha256(checkpoint)
    with_checkpoint = object.__new__(FusionReceipt)
    for name, value in base.items():
        object.__setattr__(with_checkpoint, name, value)
    receipt = FusionReceipt._create(
        payload={
            **base,
            "receipt_sha256": _canonical_sha256(
                _fusion_receipt_payload(with_checkpoint, include_hash=False)
            ),
        },
        _token=_FUSION_RECEIPT_TOKEN,
    )
    _consume_fusion_execution_permit(execution_permit, receipt)
    identity = id(receipt)
    weak = ref(
        receipt,
        lambda dead, identity=identity,
        drop=_drop_fusion_receipt_authority: drop(identity, dead),
    )
    _register_fusion_receipt_authority(
        receipt,
        _FusionReceiptAuthority(
            weak=weak,
            obligation=obligation,
            dense_receipt=dense_receipt,
            lexical_receipt=lexical_receipt,
            store=store,
            config=config,
            runtime=runtime,
            result=result,
            execution_permit=execution_permit,
            issued_payload_sha256=_canonical_sha256(receipt.to_dict()),
        ),
    )
    return receipt


def _validate_fusion_inputs(
    *,
    obligation: RetrievalObligation,
    dense_receipt: LaneSearchReceipt,
    lexical_receipt: LaneSearchReceipt,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
) -> tuple[_LaneSearchReceiptAuthority, _LaneSearchReceiptAuthority]:
    for receipt, lane in (
        (dense_receipt, "dense"),
        (lexical_receipt, "lexical"),
    ):
        validate_lane_search_receipt(
            receipt=receipt,
            obligation=obligation,
            store=store,
            config=config,
            runtime=runtime,
        )
        if object.__getattribute__(receipt, "lane") != lane:
            raise ValueError("fusion_lane_role_mismatch")
        if object.__getattribute__(receipt, "outcome") not in {
            "applied",
            "empty",
        }:
            raise ValueError("fusion_lane_outcome_mismatch")
    identity_names = (
        "execution_binding_sha256",
        "obligation_sha256",
        "obligation_key",
        "round_index",
        "query_sha256",
        "scope_state",
        "scope_origin",
        "scope_doc_ids",
        "scope_sha256",
        "evidence_store_sha256",
        "execution_config_sha256",
        "runtime_binding_sha256",
        "source_receipt_sha256",
    )
    if any(
        object.__getattribute__(dense_receipt, name)
        != object.__getattribute__(lexical_receipt, name)
        or object.__getattribute__(dense_receipt, name)
        != object.__getattribute__(obligation, name)
        for name in identity_names
        if hasattr(obligation, name)
    ):
        raise ValueError("fusion_receipt_identity_mismatch")
    dense_authority = _read_lane_search_receipt_authority(dense_receipt)
    lexical_authority = _read_lane_search_receipt_authority(lexical_receipt)
    if (
        dense_authority.obligation is not obligation
        or lexical_authority.obligation is not obligation
        or dense_authority.store is not store
        or lexical_authority.store is not store
        or dense_authority.config is not config
        or lexical_authority.config is not config
        or dense_authority.runtime is not runtime
        or lexical_authority.runtime is not runtime
        or type(dense_authority.result) is not SearchResult
        or type(lexical_authority.result) is not SearchResult
    ):
        raise ValueError("fusion_receipt_dependency_identity_mismatch")
    return dense_authority, lexical_authority


def execute_retrieval_fusion(
    *,
    obligation: RetrievalObligation,
    dense_receipt: LaneSearchReceipt,
    lexical_receipt: LaneSearchReceipt,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    _dependency_checker=None,
    _dependency_checker_code=None,
) -> FusionReceipt:
    """Fuse one exact normal dense/lexical pair exactly once."""

    module_namespace = globals()
    checker_defaults = (
        None
        if type(_dependency_checker) is not FunctionType
        else object.__getattribute__(_dependency_checker, "__defaults__")
    )
    if (
        _dependency_checker
        is not dict.get(module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER")
        or type(_dependency_checker) is not FunctionType
        or object.__getattribute__(_dependency_checker, "__code__")
        is not _dependency_checker_code
        or _dependency_checker_code
        is not dict.get(module_namespace, "_PINNED_RUNTIME_GATE_DEPENDENCY_CHECKER_CODE")
        or checker_defaults
        is not dict.get(module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_DEFAULTS")
        or type(checker_defaults) is not tuple
        or len(checker_defaults) != 6
        or tuple.__getitem__(checker_defaults, 0) is not module_namespace
        or object.__getattribute__(_dependency_checker, "__kwdefaults__") is not None
    ):
        raise ValueError("harness_runtime_validation_dependency_drift")
    _dependency_checker()
    dense_authority, lexical_authority = _validate_fusion_inputs(
        obligation=obligation,
        dense_receipt=dense_receipt,
        lexical_receipt=lexical_receipt,
        store=store,
        config=config,
        runtime=runtime,
    )
    obligation_authority = _require_retrieval_obligation_authority(obligation)
    _validate_e0_child_execution_caller(obligation_authority.ledger)
    claim = _claim_fusion_execution(
        ledger=obligation_authority.ledger,
        obligation=obligation,
        dense_receipt=dense_receipt,
        lexical_receipt=lexical_receipt,
    )
    try:
        raw_result = _require_harness_runtime_authority(runtime).fusion_method(
            dense_authority.result,
            lexical_authority.result,
            store,
            rrf_k=config.rrf_k,
        )
        (
            evidence_ids,
            anchors,
            dense_only,
            lexical_only,
            both,
            distinct_doc_count,
            result_sha256,
        ) = _validate_fusion_result(
            result=raw_result,
            obligation=obligation,
            dense_result=dense_authority.result,
            lexical_result=lexical_authority.result,
            store=store,
            rrf_k=config.rrf_k,
        )
    except Exception:
        _fail_fusion_execution(claim)
        raise ValueError("fusion_contract_error") from None
    outcome = "applied" if evidence_ids else "empty"
    permit = _close_fusion_execution(
        claim,
        outcome=outcome,
        result_sha256=result_sha256,
    )
    return _mint_fusion_receipt(
        obligation=obligation,
        dense_receipt=dense_receipt,
        lexical_receipt=lexical_receipt,
        store=store,
        config=config,
        runtime=runtime,
        result=raw_result,
        evidence_ids=evidence_ids,
        anchors=anchors,
        dense_only=dense_only,
        lexical_only=lexical_only,
        both=both,
        distinct_doc_count=distinct_doc_count,
        outcome=outcome,
        result_sha256=result_sha256,
        execution_permit=permit,
    )


def validate_fusion_receipt(
    *,
    receipt: FusionReceipt,
    obligation: RetrievalObligation,
    dense_receipt: LaneSearchReceipt,
    lexical_receipt: LaneSearchReceipt,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    _dependency_checker=None,
    _dependency_checker_code=None,
) -> None:
    module_namespace = globals()
    checker_defaults = (
        None
        if type(_dependency_checker) is not FunctionType
        else object.__getattribute__(_dependency_checker, "__defaults__")
    )
    if (
        _dependency_checker
        is not dict.get(module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER")
        or type(_dependency_checker) is not FunctionType
        or object.__getattribute__(_dependency_checker, "__code__")
        is not _dependency_checker_code
        or _dependency_checker_code
        is not dict.get(module_namespace, "_PINNED_RUNTIME_GATE_DEPENDENCY_CHECKER_CODE")
        or checker_defaults
        is not dict.get(module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_DEFAULTS")
        or type(checker_defaults) is not tuple
        or len(checker_defaults) != 6
        or tuple.__getitem__(checker_defaults, 0) is not module_namespace
        or object.__getattribute__(_dependency_checker, "__kwdefaults__") is not None
    ):
        raise ValueError("harness_runtime_validation_dependency_drift")
    _dependency_checker()
    dense_authority, lexical_authority = _validate_fusion_inputs(
        obligation=obligation,
        dense_receipt=dense_receipt,
        lexical_receipt=lexical_receipt,
        store=store,
        config=config,
        runtime=runtime,
    )
    if type(receipt) is not FusionReceipt:
        raise TypeError("fusion_receipt_required")
    authority = _read_fusion_receipt_authority(receipt)
    if (
        authority.weak() is not receipt
        or authority.obligation is not obligation
        or authority.dense_receipt is not dense_receipt
        or authority.lexical_receipt is not lexical_receipt
        or authority.store is not store
        or authority.config is not config
        or authority.runtime is not runtime
    ):
        raise ValueError("fusion_receipt_dependency_identity_mismatch")
    _validate_consumed_fusion_execution_permit(
        authority.execution_permit, receipt
    )
    _validate_fusion_receipt_payload(receipt)
    if authority.issued_payload_sha256 != _canonical_sha256(receipt.to_dict()):
        raise ValueError("fusion_receipt_runtime_authority_drift")
    values = _validate_fusion_result(
        result=authority.result,
        obligation=obligation,
        dense_result=dense_authority.result,
        lexical_result=lexical_authority.result,
        store=store,
        rrf_k=config.rrf_k,
    )
    expected = (
        receipt.ordered_evidence_ids,
        receipt.ordered_stable_anchors,
        receipt.dense_only_evidence_ids,
        receipt.lexical_only_evidence_ids,
        receipt.both_evidence_ids,
        receipt.distinct_doc_count,
        receipt.result_sha256,
    )
    if values != expected:
        raise ValueError("fusion_receipt_result_drift")


(
    _claim_fusion_execution,
    _close_fusion_execution,
    _fail_fusion_execution,
    _consume_fusion_execution_permit,
    _validate_consumed_fusion_execution_permit,
    _fusion_execution_pristine,
    _validate_fusion_lane_advance,
) = _build_fusion_execution_accessors(
    executor_code=object.__getattribute__(execute_retrieval_fusion, "__code__"),
    mint_code=object.__getattribute__(_mint_fusion_receipt, "__code__"),
    lane_executor_code=object.__getattribute__(execute_retrieval_lane, "__code__"),
    module_globals=globals(),
)


def _validate_e0_obligation_set(
    *,
    obligations: tuple[RetrievalObligation, ...],
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    require_fresh: bool,
) -> _RetrievalExecutionLedger:
    if type(obligations) is not tuple or not obligations:
        raise ValueError("e0_canonical_obligation_set_required")
    if type(require_fresh) is not bool:
        raise ValueError("invalid_e0_freshness_gate")
    validate_harness_execution_config(config)
    if object.__getattribute__(config, "mode") != "e0_once":
        raise ValueError("e0_control_mode_required")
    first = obligations[0]
    if type(first) is not RetrievalObligation:
        raise TypeError("retrieval_obligation_required")
    first_authority = _require_retrieval_obligation_authority(first)
    ledger = first_authority.ledger
    expected_hashes = object.__getattribute__(ledger, "_obligation_sha256s")
    supplied_hashes = tuple(
        object.__getattribute__(obligation, "obligation_sha256")
        if type(obligation) is RetrievalObligation
        else ""
        for obligation in obligations
    )
    if supplied_hashes != expected_hashes:
        raise ValueError("e0_canonical_obligation_set_mismatch")
    source_kind = object.__getattribute__(first, "source_kind")
    source_receipt_sha256 = object.__getattribute__(
        first, "source_receipt_sha256"
    )
    execution_binding_sha256 = object.__getattribute__(
        first, "execution_binding_sha256"
    )
    for index, obligation in enumerate(obligations, 1):
        if type(obligation) is not RetrievalObligation:
            raise TypeError("retrieval_obligation_required")
        validate_retrieval_obligation(
            obligation=obligation,
            store=store,
            config=config,
            runtime=runtime,
        )
        authority = _require_retrieval_obligation_authority(obligation)
        if (
            authority.ledger is not ledger
            or object.__getattribute__(obligation, "ordinal") != index
            or object.__getattribute__(obligation, "obligation_count")
            != len(obligations)
            or object.__getattribute__(obligation, "source_kind") != source_kind
            or object.__getattribute__(obligation, "source_receipt_sha256")
            != source_receipt_sha256
            or object.__getattribute__(obligation, "execution_binding_sha256")
            != execution_binding_sha256
        ):
            raise ValueError("e0_canonical_obligation_set_mismatch")
    ledger._validate()
    if require_fresh and _e0_execution_consumed(ledger):
        raise ValueError("e0_control_already_consumed")
    if require_fresh and (
        object.__getattribute__(ledger, "_claimed") != frozenset()
        or object.__getattribute__(ledger, "_closed") != frozenset()
        or object.__getattribute__(ledger, "_dense_provider_failed")
        != frozenset()
        or object.__getattribute__(ledger, "_status") != "active"
        or object.__getattribute__(ledger, "_revision") != 0
        or not _fusion_execution_pristine(ledger)
    ):
        raise ValueError("e0_fresh_obligation_set_required")
    return ledger


@dataclass(frozen=True, slots=True, weakref_slot=True)
class _E0ExecutionClaim:
    ledger: _RetrievalExecutionLedger
    obligations: tuple[RetrievalObligation, ...]


@dataclass(frozen=True, slots=True, weakref_slot=True)
class _E0ClosurePermit:
    claim: _E0ExecutionClaim
    outcome: str


@dataclass(frozen=True, slots=True)
class _E0ControlReceiptAuthority:
    weak: ReferenceType[E0ControlReceipt]
    obligations: tuple[RetrievalObligation, ...]
    store: EvidenceStore
    config: HarnessExecutionConfig
    runtime: HarnessRuntimeBinding
    dense_receipts: tuple[LaneSearchReceipt | None, ...]
    lexical_receipts: tuple[LaneSearchReceipt | None, ...]
    fusion_receipts: tuple[FusionReceipt | None, ...]
    execution_permit: _E0ClosurePermit
    issued_payload_sha256: str


_E0_CONTROL_RECEIPT_AUTHORITIES: dict[int, _E0ControlReceiptAuthority] = {}
_ISSUED_E0_CONTROL_RECEIPT_AUTHORITIES = _E0_CONTROL_RECEIPT_AUTHORITIES


def _build_e0_receipt_authority_accessors(
    visible: dict[int, _E0ControlReceiptAuthority],
) -> tuple[FunctionType, FunctionType, FunctionType]:
    shadow: dict[int, tuple[object, ...]] = {}
    authority_lock = Lock()

    def snapshot(authority: _E0ControlReceiptAuthority) -> tuple[object, ...]:
        return tuple(
            object.__getattribute__(authority, name)
            for name in (
                "weak",
                "obligations",
                "store",
                "config",
                "runtime",
                "dense_receipts",
                "lexical_receipts",
                "fusion_receipts",
                "execution_permit",
                "issued_payload_sha256",
            )
        )

    def register(
        receipt: E0ControlReceipt,
        authority: _E0ControlReceiptAuthority,
    ) -> None:
        with authority_lock:
            identity = id(receipt)
            if (
                type(receipt) is not E0ControlReceipt
                or type(authority) is not _E0ControlReceiptAuthority
                or object.__getattribute__(authority, "weak")() is not receipt
                or dict.get(visible, identity) is not None
                or dict.get(shadow, identity) is not None
            ):
                raise ValueError("e0_control_receipt_runtime_authority_drift")
            values = snapshot(authority)
            dict.__setitem__(visible, identity, authority)
            dict.__setitem__(shadow, identity, values)

    def read(receipt: E0ControlReceipt) -> _E0ControlReceiptAuthority:
        with authority_lock:
            current = dict.get(visible, id(receipt))
            sealed = dict.get(shadow, id(receipt))
            if (
                type(current) is not _E0ControlReceiptAuthority
                or type(sealed) is not tuple
                or len(sealed) != 10
                or tuple.__getitem__(sealed, 0)() is not receipt
                or any(
                    current_value is not sealed_value
                    for current_value, sealed_value in zip(
                        snapshot(current), sealed
                    )
                )
            ):
                raise ValueError("e0_control_receipt_runtime_authority_drift")
            return current

    def drop_when_dead(
        identity: int,
        dead: ReferenceType[E0ControlReceipt],
    ) -> None:
        with authority_lock:
            sealed = dict.get(shadow, identity)
            if (
                type(sealed) is tuple
                and len(sealed) == 10
                and tuple.__getitem__(sealed, 0) is dead
            ):
                dict.pop(visible, identity, None)
                dict.pop(shadow, identity, None)

    return register, read, drop_when_dead


(
    _register_e0_control_receipt_authority,
    _read_e0_control_receipt_authority,
    _drop_e0_control_receipt_authority_when_dead,
) = _build_e0_receipt_authority_accessors(
    _ISSUED_E0_CONTROL_RECEIPT_AUTHORITIES
)


def _drop_e0_control_receipt_authority(
    identity: int,
    dead: ReferenceType[E0ControlReceipt],
) -> None:
    _drop_e0_control_receipt_authority_when_dead(identity, dead)


def _build_e0_execution_accessors(
    *,
    executor_code: CodeType,
    mint_code: CodeType,
    lane_executor_code: CodeType,
    fusion_executor_code: CodeType,
    module_globals: dict[str, Any],
) -> tuple[
    FunctionType,
    FunctionType,
    FunctionType,
    FunctionType,
    FunctionType,
    FunctionType,
    FunctionType,
]:
    executions: dict[int, tuple[object, ...]] = {}
    claims: dict[int, tuple[object, ...]] = {}
    permits: dict[int, tuple[object, ...]] = {}
    execution_lock = Lock()
    frame_getter = _GET_FRAME

    def drop_claim(identity: int, dead: ReferenceType[object]) -> None:
        with execution_lock:
            current = dict.get(claims, identity)
            if current is not None and tuple.__getitem__(current, 0) is dead:
                dict.pop(claims, identity, None)

    def drop_permit(identity: int, dead: ReferenceType[object]) -> None:
        with execution_lock:
            current = dict.get(permits, identity)
            if current is not None and tuple.__getitem__(current, 0) is dead:
                dict.pop(permits, identity, None)

    def drop_ledger(identity: int, dead: ReferenceType[object]) -> None:
        with execution_lock:
            current = dict.get(executions, identity)
            if current is not None and tuple.__getitem__(current, 0) is dead:
                dict.pop(executions, identity, None)

    def claim(
        *,
        ledger: _RetrievalExecutionLedger,
        obligations: tuple[RetrievalObligation, ...],
    ) -> _E0ExecutionClaim:
        caller = frame_getter(1)
        if (
            object.__getattribute__(caller, "f_code") is not executor_code
            or object.__getattribute__(caller, "f_globals") is not module_globals
        ):
            raise ValueError("e0_control_executor_authority_required")
        _ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER()
        with execution_lock:
            current = dict.get(executions, id(ledger))
            if current is not None:
                if (
                    type(current) is not tuple
                    or len(current) != 3
                    or tuple.__getitem__(current, 0)() is not ledger
                ):
                    raise ValueError("e0_control_execution_authority_drift")
                raise ValueError("e0_control_already_consumed")
            ledger._validate()
            if (
                object.__getattribute__(ledger, "_claimed") != frozenset()
                or object.__getattribute__(ledger, "_closed") != frozenset()
                or object.__getattribute__(ledger, "_status") != "active"
                or object.__getattribute__(ledger, "_revision") != 0
            ):
                raise ValueError("e0_fresh_obligation_set_required")
            claim_value = _E0ExecutionClaim(
                ledger=ledger,
                obligations=obligations,
            )
            claim_weak = ref(
                claim_value,
                lambda dead, identity=id(claim_value): drop_claim(
                    identity, dead
                ),
            )
            ledger_weak = ref(
                ledger,
                lambda dead, identity=id(ledger): drop_ledger(identity, dead),
            )
            dict.__setitem__(
                claims,
                id(claim_value),
                (claim_weak, ledger, obligations, "pending"),
            )
            dict.__setitem__(
                executions,
                id(ledger),
                (ledger_weak, "pending", claim_weak),
            )
            return claim_value

    def close(
        claim_value: _E0ExecutionClaim,
        *,
        outcome: str,
    ) -> _E0ClosurePermit:
        caller = frame_getter(1)
        if (
            object.__getattribute__(caller, "f_code") is not executor_code
            or object.__getattribute__(caller, "f_globals") is not module_globals
        ):
            raise ValueError("e0_control_executor_authority_required")
        _ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER()
        with execution_lock:
            current = dict.get(claims, id(claim_value))
            if (
                type(current) is not tuple
                or len(current) != 4
                or tuple.__getitem__(current, 0)() is not claim_value
                or tuple.__getitem__(current, 3) != "pending"
                or outcome not in _E0_STATUSES
            ):
                raise ValueError("e0_control_execution_claim_mismatch")
            ledger = tuple.__getitem__(current, 1)
            execution = dict.get(executions, id(ledger))
            if (
                type(execution) is not tuple
                or len(execution) != 3
                or tuple.__getitem__(execution, 2)() is not claim_value
                or tuple.__getitem__(execution, 1) != "pending"
            ):
                raise ValueError("e0_control_execution_authority_drift")
            dict.__setitem__(
                claims, id(claim_value), current[:-1] + ("complete",)
            )
            dict.__setitem__(
                executions,
                id(ledger),
                (tuple.__getitem__(execution, 0), "complete", execution[2]),
            )
            permit = _E0ClosurePermit(claim=claim_value, outcome=outcome)
            permit_weak = ref(
                permit,
                lambda dead, identity=id(permit): drop_permit(identity, dead),
            )
            dict.__setitem__(
                permits,
                id(permit),
                (permit_weak, claim_value, outcome, False, None),
            )
            return permit

    def fail(claim_value: _E0ExecutionClaim) -> None:
        caller = frame_getter(1)
        if (
            object.__getattribute__(caller, "f_code") is not executor_code
            or object.__getattribute__(caller, "f_globals") is not module_globals
        ):
            raise ValueError("e0_control_executor_authority_required")
        _ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER()
        with execution_lock:
            current = dict.get(claims, id(claim_value))
            if (
                type(current) is not tuple
                or len(current) != 4
                or tuple.__getitem__(current, 0)() is not claim_value
                or tuple.__getitem__(current, 3) != "pending"
            ):
                raise ValueError("e0_control_execution_claim_mismatch")
            ledger = tuple.__getitem__(current, 1)
            execution = dict.get(executions, id(ledger))
            dict.__setitem__(claims, id(claim_value), current[:-1] + ("error",))
            dict.__setitem__(
                executions,
                id(ledger),
                (tuple.__getitem__(execution, 0), "error", execution[2]),
            )

    def consume(permit: _E0ClosurePermit, receipt: E0ControlReceipt) -> None:
        caller = frame_getter(1)
        if (
            object.__getattribute__(caller, "f_code") is not mint_code
            or object.__getattribute__(caller, "f_globals") is not module_globals
        ):
            raise ValueError("e0_control_receipt_mint_authority_required")
        _ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER()
        with execution_lock:
            current = dict.get(permits, id(permit))
            if (
                type(current) is not tuple
                or len(current) != 5
                or tuple.__getitem__(current, 0)() is not permit
                or tuple.__getitem__(current, 3) is not False
                or tuple.__getitem__(current, 4) is not None
            ):
                raise ValueError("e0_control_execution_permit_mismatch")
            dict.__setitem__(
                permits,
                id(permit),
                current[:3] + (True, ref(receipt)),
            )

    def validate(permit: _E0ClosurePermit, receipt: E0ControlReceipt) -> None:
        with execution_lock:
            current = dict.get(permits, id(permit))
            if (
                type(current) is not tuple
                or len(current) != 5
                or tuple.__getitem__(current, 0)() is not permit
                or tuple.__getitem__(current, 3) is not True
                or type(tuple.__getitem__(current, 4)) is not ReferenceType
                or tuple.__getitem__(current, 4)() is not receipt
            ):
                raise ValueError("e0_control_execution_permit_mismatch")

    def consumed(ledger: _RetrievalExecutionLedger) -> bool:
        with execution_lock:
            current = dict.get(executions, id(ledger))
            if current is None:
                return False
            if (
                type(current) is not tuple
                or len(current) != 3
                or tuple.__getitem__(current, 0)() is not ledger
            ):
                raise ValueError("e0_control_execution_authority_drift")
            return True

    def validate_child_caller(ledger: _RetrievalExecutionLedger) -> None:
        with execution_lock:
            current = dict.get(executions, id(ledger))
            if current is None:
                return
            if (
                type(current) is not tuple
                or len(current) != 3
                or tuple.__getitem__(current, 0)() is not ledger
            ):
                raise ValueError("e0_control_execution_authority_drift")
            if tuple.__getitem__(current, 1) != "pending":
                raise ValueError("e0_control_already_consumed")
            caller = frame_getter(1)
            parent = frame_getter(2)
            if (
                object.__getattribute__(caller, "f_code")
                not in {lane_executor_code, fusion_executor_code}
                or object.__getattribute__(caller, "f_globals")
                is not module_globals
                or
                object.__getattribute__(parent, "f_code") is not executor_code
                or object.__getattribute__(parent, "f_globals") is not module_globals
            ):
                raise ValueError("e0_child_executor_authority_required")

    return claim, close, fail, consume, validate, consumed, validate_child_caller


def _mint_e0_control_receipt(
    *,
    obligations: tuple[RetrievalObligation, ...],
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    results: tuple[E0ObligationResult, ...],
    dense_receipts: tuple[LaneSearchReceipt | None, ...],
    lexical_receipts: tuple[LaneSearchReceipt | None, ...],
    fusion_receipts: tuple[FusionReceipt | None, ...],
    outcome: str,
    execution_complete: bool,
    execution_permit: _E0ClosurePermit,
) -> E0ControlReceipt:
    base = {
        "mode": "e0_once",
        "source_kind": obligations[0].source_kind,
        "execution_binding_sha256": obligations[0].execution_binding_sha256,
        "source_receipt_sha256": obligations[0].source_receipt_sha256,
        "evidence_store_sha256": obligations[0].evidence_store_sha256,
        "execution_config_sha256": config.config_sha256,
        "runtime_binding_sha256": runtime.binding_sha256,
        "ordered_obligation_sha256s": tuple(
            obligation.obligation_sha256 for obligation in obligations
        ),
        "ordered_results": results,
        "nonempty_obligation_keys": tuple(
            result.obligation_key
            for result in results
            if result.status == "retrieved"
        ),
        "empty_obligation_keys": tuple(
            result.obligation_key for result in results if result.status == "empty"
        ),
        "unavailable_obligation_keys": tuple(
            result.obligation_key
            for result in results
            if result.status == "unavailable"
        ),
        "error_obligation_keys": tuple(
            result.obligation_key for result in results if result.status == "error"
        ),
        "outcome": outcome,
        "execution_complete": execution_complete,
    }
    provisional = object.__new__(E0ControlReceipt)
    for name, value in base.items():
        object.__setattr__(provisional, name, value)
    receipt = E0ControlReceipt._create(
        payload={
            **base,
            "receipt_sha256": _canonical_sha256(
                _e0_control_receipt_payload(provisional, include_hash=False)
            ),
        },
        _token=_E0_CONTROL_RECEIPT_TOKEN,
    )
    _consume_e0_execution_permit(execution_permit, receipt)
    identity = id(receipt)
    weak = ref(
        receipt,
        lambda dead, identity=identity,
        drop=_drop_e0_control_receipt_authority: drop(identity, dead),
    )
    _register_e0_control_receipt_authority(
        receipt,
        _E0ControlReceiptAuthority(
            weak=weak,
            obligations=obligations,
            store=store,
            config=config,
            runtime=runtime,
            dense_receipts=dense_receipts,
            lexical_receipts=lexical_receipts,
            fusion_receipts=fusion_receipts,
            execution_permit=execution_permit,
            issued_payload_sha256=_canonical_sha256(receipt.to_dict()),
        ),
    )
    return receipt


def execute_e0_control(
    *,
    obligations: tuple[RetrievalObligation, ...],
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    _dependency_checker=None,
    _dependency_checker_code=None,
) -> E0ControlReceipt:
    """Run the state-free dense/lexical/RRF control once."""

    module_namespace = globals()
    checker_defaults = (
        None
        if type(_dependency_checker) is not FunctionType
        else object.__getattribute__(_dependency_checker, "__defaults__")
    )
    if (
        _dependency_checker
        is not dict.get(module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER")
        or type(_dependency_checker) is not FunctionType
        or object.__getattribute__(_dependency_checker, "__code__")
        is not _dependency_checker_code
        or _dependency_checker_code
        is not dict.get(module_namespace, "_PINNED_RUNTIME_GATE_DEPENDENCY_CHECKER_CODE")
        or checker_defaults
        is not dict.get(module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_DEFAULTS")
        or type(checker_defaults) is not tuple
        or len(checker_defaults) != 6
        or tuple.__getitem__(checker_defaults, 0) is not module_namespace
        or object.__getattribute__(_dependency_checker, "__kwdefaults__") is not None
    ):
        raise ValueError("harness_runtime_validation_dependency_drift")
    _dependency_checker()
    lane_executor = execute_retrieval_lane
    lane_validator = validate_lane_search_receipt
    fusion_executor = execute_retrieval_fusion
    fusion_validator = validate_fusion_receipt
    result_factory = _make_e0_obligation_result
    fail_execution = _fail_e0_execution

    def revalidate_dependencies() -> None:
        current_defaults = (
            None
            if type(_dependency_checker) is not FunctionType
            else object.__getattribute__(_dependency_checker, "__defaults__")
        )
        if (
            _dependency_checker
            is not dict.get(
                module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER"
            )
            or type(_dependency_checker) is not FunctionType
            or object.__getattribute__(_dependency_checker, "__code__")
            is not _dependency_checker_code
            or _dependency_checker_code
            is not dict.get(
                module_namespace, "_PINNED_RUNTIME_GATE_DEPENDENCY_CHECKER_CODE"
            )
            or current_defaults
            is not dict.get(
                module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_DEFAULTS"
            )
            or current_defaults is not checker_defaults
            or type(current_defaults) is not tuple
            or len(current_defaults) != 6
            or tuple.__getitem__(current_defaults, 0) is not module_namespace
            or object.__getattribute__(_dependency_checker, "__kwdefaults__")
            is not None
        ):
            raise ValueError("harness_runtime_validation_dependency_drift")
        _dependency_checker()

    ledger = _validate_e0_obligation_set(
        obligations=obligations,
        store=store,
        config=config,
        runtime=runtime,
        require_fresh=True,
    )
    claim = _claim_e0_execution(ledger=ledger, obligations=obligations)
    results: list[E0ObligationResult] = []
    dense_receipts: list[LaneSearchReceipt | None] = []
    lexical_receipts: list[LaneSearchReceipt | None] = []
    fusion_receipts: list[FusionReceipt | None] = []
    try:
        for index, obligation in enumerate(obligations):
            dense = lane_executor(
                obligation=obligation,
                lane="dense",
                store=store,
                config=config,
                runtime=runtime,
            )
            revalidate_dependencies()
            if type(dense) is not LaneSearchReceipt:
                raise TypeError("e0_dense_receipt_required")
            lane_validator(
                receipt=dense,
                obligation=obligation,
                store=store,
                config=config,
                runtime=runtime,
            )
            if object.__getattribute__(dense, "lane") != "dense":
                raise ValueError("e0_control_child_lane_mismatch")
            lexical: LaneSearchReceipt | None = None
            fusion: FusionReceipt | None = None
            dense_outcome = object.__getattribute__(dense, "outcome")
            if dense_outcome == "provider_error":
                lexical = lane_executor(
                    obligation=obligation,
                    lane="lexical",
                    store=store,
                    config=config,
                    runtime=runtime,
                )
                revalidate_dependencies()
                if type(lexical) is not LaneSearchReceipt:
                    raise TypeError("e0_lexical_receipt_required")
                lane_validator(
                    receipt=lexical,
                    obligation=obligation,
                    store=store,
                    config=config,
                    runtime=runtime,
                )
                if object.__getattribute__(lexical, "lane") != "lexical":
                    raise ValueError("e0_control_child_lane_mismatch")
                result = result_factory(
                    obligation=obligation,
                    attempted=True,
                    dense_receipt=dense,
                    lexical_receipt=lexical,
                    fusion_receipt=None,
                    status="error",
                    error_code=dense.error_code,
                )
            elif dense_outcome == "contract_error":
                result = result_factory(
                    obligation=obligation,
                    attempted=True,
                    dense_receipt=dense,
                    lexical_receipt=None,
                    fusion_receipt=None,
                    status="error",
                    error_code=dense.error_code,
                )
            else:
                lexical = lane_executor(
                    obligation=obligation,
                    lane="lexical",
                    store=store,
                    config=config,
                    runtime=runtime,
                )
                revalidate_dependencies()
                if type(lexical) is not LaneSearchReceipt:
                    raise TypeError("e0_lexical_receipt_required")
                lane_validator(
                    receipt=lexical,
                    obligation=obligation,
                    store=store,
                    config=config,
                    runtime=runtime,
                )
                if object.__getattribute__(lexical, "lane") != "lexical":
                    raise ValueError("e0_control_child_lane_mismatch")
                lexical_outcome = object.__getattribute__(lexical, "outcome")
                if lexical_outcome in {"provider_error", "contract_error"}:
                    result = result_factory(
                        obligation=obligation,
                        attempted=True,
                        dense_receipt=dense,
                        lexical_receipt=lexical,
                        fusion_receipt=None,
                        status="error",
                        error_code=lexical.error_code,
                    )
                else:
                    try:
                        fusion = fusion_executor(
                            obligation=obligation,
                            dense_receipt=dense,
                            lexical_receipt=lexical,
                            store=store,
                            config=config,
                            runtime=runtime,
                        )
                    except ValueError:
                        revalidate_dependencies()
                        result = result_factory(
                            obligation=obligation,
                            attempted=True,
                            dense_receipt=dense,
                            lexical_receipt=lexical,
                            fusion_receipt=None,
                            status="error",
                            error_code="fusion_contract_error",
                        )
                    else:
                        revalidate_dependencies()
                        if type(fusion) is not FusionReceipt:
                            raise TypeError("e0_fusion_receipt_required")
                        fusion_validator(
                            receipt=fusion,
                            obligation=obligation,
                            dense_receipt=dense,
                            lexical_receipt=lexical,
                            store=store,
                            config=config,
                            runtime=runtime,
                        )
                        result = result_factory(
                            obligation=obligation,
                            attempted=True,
                            dense_receipt=dense,
                            lexical_receipt=lexical,
                            fusion_receipt=fusion,
                            status=(
                                "retrieved"
                                if fusion.outcome == "applied"
                                else "empty"
                            ),
                            error_code="none",
                        )
            dense_receipts.append(dense)
            lexical_receipts.append(lexical)
            fusion_receipts.append(fusion)
            results.append(result)
            if result.status == "error":
                for remaining in obligations[index + 1 :]:
                    dense_receipts.append(None)
                    lexical_receipts.append(None)
                    fusion_receipts.append(None)
                    results.append(
                        result_factory(
                            obligation=remaining,
                            attempted=False,
                            dense_receipt=None,
                            lexical_receipt=None,
                            fusion_receipt=None,
                            status="error",
                            error_code="execution_terminated_before_obligation",
                        )
                    )
                break
    except Exception:
        fail_execution(claim)
        raise
    result_tuple = tuple(results)
    statuses = tuple(result.status for result in result_tuple)
    outcome = (
        "error"
        if "error" in statuses
        else "unavailable"
        if "unavailable" in statuses
        else "empty"
        if all(status == "empty" for status in statuses)
        else "retrieved"
    )
    execution_complete = all(
        status in {"retrieved", "empty"} for status in statuses
    )
    permit = _close_e0_execution(claim, outcome=outcome)
    return _mint_e0_control_receipt(
        obligations=obligations,
        store=store,
        config=config,
        runtime=runtime,
        results=result_tuple,
        dense_receipts=tuple(dense_receipts),
        lexical_receipts=tuple(lexical_receipts),
        fusion_receipts=tuple(fusion_receipts),
        outcome=outcome,
        execution_complete=execution_complete,
        execution_permit=permit,
    )


def validate_e0_control_receipt(
    *,
    receipt: E0ControlReceipt,
    obligations: tuple[RetrievalObligation, ...],
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    _dependency_checker=None,
    _dependency_checker_code=None,
) -> None:
    module_namespace = globals()
    checker_defaults = (
        None
        if type(_dependency_checker) is not FunctionType
        else object.__getattribute__(_dependency_checker, "__defaults__")
    )
    if (
        _dependency_checker
        is not dict.get(module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER")
        or type(_dependency_checker) is not FunctionType
        or object.__getattribute__(_dependency_checker, "__code__")
        is not _dependency_checker_code
        or _dependency_checker_code
        is not dict.get(module_namespace, "_PINNED_RUNTIME_GATE_DEPENDENCY_CHECKER_CODE")
        or checker_defaults
        is not dict.get(module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_DEFAULTS")
        or type(checker_defaults) is not tuple
        or len(checker_defaults) != 6
        or tuple.__getitem__(checker_defaults, 0) is not module_namespace
        or object.__getattribute__(_dependency_checker, "__kwdefaults__") is not None
    ):
        raise ValueError("harness_runtime_validation_dependency_drift")
    _dependency_checker()
    _validate_e0_obligation_set(
        obligations=obligations,
        store=store,
        config=config,
        runtime=runtime,
        require_fresh=False,
    )
    if type(receipt) is not E0ControlReceipt:
        raise TypeError("e0_control_receipt_required")
    authority = _read_e0_control_receipt_authority(receipt)
    if (
        authority.weak() is not receipt
        or authority.obligations is not obligations
        or authority.store is not store
        or authority.config is not config
        or authority.runtime is not runtime
    ):
        raise ValueError("e0_control_receipt_dependency_identity_mismatch")
    _validate_consumed_e0_execution_permit(authority.execution_permit, receipt)
    _validate_e0_control_receipt_payload(receipt)
    if authority.issued_payload_sha256 != _canonical_sha256(receipt.to_dict()):
        raise ValueError("e0_control_receipt_runtime_authority_drift")
    results = object.__getattribute__(receipt, "ordered_results")
    for index, obligation in enumerate(obligations):
        result = results[index]
        dense = authority.dense_receipts[index]
        lexical = authority.lexical_receipts[index]
        fusion = authority.fusion_receipts[index]
        for child, lane in ((dense, "dense"), (lexical, "lexical")):
            if child is not None:
                validate_lane_search_receipt(
                    receipt=child,
                    obligation=obligation,
                    store=store,
                    config=config,
                    runtime=runtime,
                )
                if child.lane != lane:
                    raise ValueError("e0_control_child_lane_mismatch")
        if fusion is not None:
            if dense is None or lexical is None:
                raise ValueError("e0_control_fusion_dependency_mismatch")
            validate_fusion_receipt(
                receipt=fusion,
                obligation=obligation,
                dense_receipt=dense,
                lexical_receipt=lexical,
                store=store,
                config=config,
                runtime=runtime,
            )
        if (
            result.dense_receipt_sha256
            != (None if dense is None else dense.receipt_sha256)
            or result.lexical_receipt_sha256
            != (None if lexical is None else lexical.receipt_sha256)
            or result.fusion_receipt_sha256
            != (None if fusion is None else fusion.receipt_sha256)
        ):
            raise ValueError("e0_control_child_receipt_mismatch")


# EH2.6.c2 semantic verification -------------------------------------------------

_SEMANTIC_SOURCE_KINDS = frozenset({"fact", "compare", "follow_up"})
_SEMANTIC_TARGET_KINDS = frozenset({"answer_support", "field_value"})
_SEMANTIC_ROLES = frozenset({"candidate", "bridge", "context"})
_SEMANTIC_DISPOSITIONS = frozenset(
    {"supported", "unsupported", "contradicted", "unavailable"}
)


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class SemanticVerificationObligation:
    """Trace-free verifier target issued only from an exact source owner."""

    derivation_kind: str
    source_kind: str
    target_kind: str
    obligation_key: str
    target_doc_id: str | None
    field: str | None
    execution_kind: str
    owner_binding_sha256: str
    retrieval_obligation_sha256: str | None
    candidate_receipt_sha256: str
    source_state_sha256: str | None
    base_semantic_obligation_sha256: str | None
    parent_context_receipt_sha256s: tuple[str, ...]
    bridge_context_receipt_sha256s: tuple[str, ...]
    rerank_receipt_sha256: str | None
    owner_plan_sha256: str | None
    owner_plan_config_sha256: str | None
    rerank_k: int | None
    final_evidence_budget: int | None
    query_sha256: str
    evidence_store_sha256: str
    execution_config_sha256: str
    runtime_binding_sha256: str
    candidate_evidence_ids: tuple[str, ...]
    bridge_evidence_ids: tuple[str, ...]
    context_evidence_ids: tuple[str, ...]
    supplied_evidence_ids: tuple[str, ...]
    ordered_stable_anchors: tuple[StableEvidenceAnchor, ...]
    obligation_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("semantic_verification_obligation_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        payload: Mapping[str, Any],
        _token: object,
    ) -> SemanticVerificationObligation:
        if _token is not _SEMANTIC_OBLIGATION_TOKEN:
            raise ValueError("semantic_verification_obligation_factory_required")
        result = object.__new__(cls)
        for name in cls.__slots__:
            if name != "__weakref__":
                object.__setattr__(result, name, payload[name])
        _validate_semantic_verification_obligation_payload(result)
        return result

    def to_dict(self) -> dict[str, Any]:
        _validate_semantic_verification_obligation_payload(self)
        return _semantic_verification_obligation_payload(self, include_hash=True)


def _semantic_verification_obligation_payload(
    obligation: SemanticVerificationObligation,
    *,
    include_hash: bool,
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "derivation_kind": object.__getattribute__(
            obligation, "derivation_kind"
        ),
        "source_kind": object.__getattribute__(obligation, "source_kind"),
        "target_kind": object.__getattribute__(obligation, "target_kind"),
        "obligation_key": object.__getattribute__(obligation, "obligation_key"),
        "target_doc_id": object.__getattribute__(obligation, "target_doc_id"),
        "field": object.__getattribute__(obligation, "field"),
        "execution_kind": object.__getattribute__(obligation, "execution_kind"),
        "owner_binding_sha256": object.__getattribute__(
            obligation, "owner_binding_sha256"
        ),
        "retrieval_obligation_sha256": object.__getattribute__(
            obligation, "retrieval_obligation_sha256"
        ),
        "candidate_receipt_sha256": object.__getattribute__(
            obligation, "candidate_receipt_sha256"
        ),
        "source_state_sha256": object.__getattribute__(
            obligation, "source_state_sha256"
        ),
        "base_semantic_obligation_sha256": object.__getattribute__(
            obligation, "base_semantic_obligation_sha256"
        ),
        "parent_context_receipt_sha256s": list(
            object.__getattribute__(
                obligation, "parent_context_receipt_sha256s"
            )
        ),
        "bridge_context_receipt_sha256s": list(
            object.__getattribute__(
                obligation, "bridge_context_receipt_sha256s"
            )
        ),
        "rerank_receipt_sha256": object.__getattribute__(
            obligation, "rerank_receipt_sha256"
        ),
        "owner_plan_sha256": object.__getattribute__(
            obligation, "owner_plan_sha256"
        ),
        "owner_plan_config_sha256": object.__getattribute__(
            obligation, "owner_plan_config_sha256"
        ),
        "rerank_k": object.__getattribute__(obligation, "rerank_k"),
        "final_evidence_budget": object.__getattribute__(
            obligation, "final_evidence_budget"
        ),
        "query_sha256": object.__getattribute__(obligation, "query_sha256"),
        "evidence_store_sha256": object.__getattribute__(
            obligation, "evidence_store_sha256"
        ),
        "execution_config_sha256": object.__getattribute__(
            obligation, "execution_config_sha256"
        ),
        "runtime_binding_sha256": object.__getattribute__(
            obligation, "runtime_binding_sha256"
        ),
        "candidate_evidence_ids": list(
            object.__getattribute__(obligation, "candidate_evidence_ids")
        ),
        "bridge_evidence_ids": list(
            object.__getattribute__(obligation, "bridge_evidence_ids")
        ),
        "context_evidence_ids": list(
            object.__getattribute__(obligation, "context_evidence_ids")
        ),
        "supplied_evidence_ids": list(
            object.__getattribute__(obligation, "supplied_evidence_ids")
        ),
        "ordered_stable_anchors": [
            anchor.to_dict()
            for anchor in object.__getattribute__(
                obligation, "ordered_stable_anchors"
            )
        ],
    }
    if include_hash:
        payload["obligation_sha256"] = object.__getattribute__(
            obligation, "obligation_sha256"
        )
    return payload


def _validate_semantic_verification_obligation_payload(
    obligation: SemanticVerificationObligation,
) -> None:
    if type(obligation) is not SemanticVerificationObligation:
        raise TypeError("semantic_verification_obligation_required")
    derivation_kind = object.__getattribute__(obligation, "derivation_kind")
    source_kind = object.__getattribute__(obligation, "source_kind")
    target_kind = object.__getattribute__(obligation, "target_kind")
    obligation_key = object.__getattribute__(obligation, "obligation_key")
    target_doc_id = object.__getattribute__(obligation, "target_doc_id")
    field = object.__getattribute__(obligation, "field")
    if (
        derivation_kind not in {"base", "reranked"}
        or type(source_kind) is not str
        or source_kind not in _SEMANTIC_SOURCE_KINDS
        or type(target_kind) is not str
        or target_kind not in _SEMANTIC_TARGET_KINDS
        or type(obligation_key) is not str
        or not obligation_key
    ):
        raise ValueError("invalid_semantic_verification_target")
    if target_kind == "answer_support":
        if obligation_key != "$answer_support" or target_doc_id is not None or field is not None:
            raise ValueError("invalid_semantic_verification_target")
    elif (
        type(target_doc_id) is not str
        or not target_doc_id
        or type(field) is not str
        or not field
    ):
        raise ValueError("invalid_semantic_verification_target")
    if source_kind == "fact" and target_kind != "answer_support":
        raise ValueError("invalid_semantic_verification_target")
    if source_kind == "compare" and target_kind != "field_value":
        raise ValueError("invalid_semantic_verification_target")
    execution_kind = object.__getattribute__(obligation, "execution_kind")
    if execution_kind not in {"production", "synthetic"}:
        raise ValueError("invalid_semantic_verification_execution_kind")
    for name in (
        "owner_binding_sha256",
        "candidate_receipt_sha256",
        "query_sha256",
        "evidence_store_sha256",
        "execution_config_sha256",
        "runtime_binding_sha256",
        "obligation_sha256",
    ):
        _require_hash(
            object.__getattribute__(obligation, name),
            f"invalid_semantic_{name}",
        )
    retrieval_sha = object.__getattribute__(
        obligation, "retrieval_obligation_sha256"
    )
    state_sha = object.__getattribute__(obligation, "source_state_sha256")
    if source_kind in {"fact", "compare"}:
        _require_hash(retrieval_sha, "invalid_semantic_retrieval_obligation_sha256")
        if state_sha is not None:
            raise ValueError("semantic_source_state_mismatch")
    else:
        if retrieval_sha is not None:
            raise ValueError("semantic_retrieval_obligation_mismatch")
        _require_hash(state_sha, "invalid_semantic_source_state_sha256")
    base_sha = object.__getattribute__(
        obligation, "base_semantic_obligation_sha256"
    )
    parent_shas = _exact_string_tuple_value(
        object.__getattribute__(
            obligation, "parent_context_receipt_sha256s"
        ),
        "semantic_parent_context_receipt_sha256s",
        allow_empty=True,
    )
    bridge_receipt_shas = _exact_string_tuple_value(
        object.__getattribute__(
            obligation, "bridge_context_receipt_sha256s"
        ),
        "semantic_bridge_context_receipt_sha256s",
        allow_empty=True,
    )
    rerank_receipt_sha = object.__getattribute__(
        obligation, "rerank_receipt_sha256"
    )
    owner_plan_sha = object.__getattribute__(obligation, "owner_plan_sha256")
    owner_plan_config_sha = object.__getattribute__(
        obligation, "owner_plan_config_sha256"
    )
    rerank_k = object.__getattribute__(obligation, "rerank_k")
    final_budget = object.__getattribute__(obligation, "final_evidence_budget")
    candidates = _exact_string_tuple_value(
        object.__getattribute__(obligation, "candidate_evidence_ids"),
        "semantic_candidate_evidence_ids",
        allow_empty=derivation_kind == "reranked",
    )
    bridges = _exact_string_tuple_value(
        object.__getattribute__(obligation, "bridge_evidence_ids"),
        "semantic_bridge_evidence_ids",
        allow_empty=True,
    )
    contexts = _exact_string_tuple_value(
        object.__getattribute__(obligation, "context_evidence_ids"),
        "semantic_context_evidence_ids",
        allow_empty=True,
    )
    supplied = _exact_string_tuple_value(
        object.__getattribute__(obligation, "supplied_evidence_ids"),
        "semantic_supplied_evidence_ids",
        allow_empty=False,
    )
    if derivation_kind == "base":
        if (
            base_sha is not None
            or parent_shas
            or bridge_receipt_shas
            or rerank_receipt_sha is not None
            or owner_plan_sha is not None
            or owner_plan_config_sha is not None
            or rerank_k is not None
            or final_budget is not None
            or bridges
            or contexts
            or supplied != candidates
        ):
            raise ValueError("semantic_base_derivation_binding_mismatch")
    else:
        for name, value in (
            ("base_semantic_obligation_sha256", base_sha),
            ("rerank_receipt_sha256", rerank_receipt_sha),
            ("owner_plan_sha256", owner_plan_sha),
            ("owner_plan_config_sha256", owner_plan_config_sha),
        ):
            _require_hash(value, f"invalid_semantic_{name}")
        for name, values in (
            ("parent_context_receipt_sha256s", parent_shas),
            ("bridge_context_receipt_sha256s", bridge_receipt_shas),
        ):
            for value in values:
                _require_hash(value, f"invalid_semantic_{name}")
        if (
            type(rerank_k) is not int
            or rerank_k < 1
            or type(final_budget) is not int
            or final_budget < 1
            or final_budget > rerank_k
            or len(supplied) > final_budget
            or contexts
            or set(candidates).intersection(bridges)
            or set(candidates).union(bridges) != set(supplied)
            or tuple(item for item in supplied if item in set(candidates))
            != candidates
            or tuple(item for item in supplied if item in set(bridges))
            != bridges
        ):
            raise ValueError("semantic_reranked_derivation_binding_mismatch")
    anchors = object.__getattribute__(obligation, "ordered_stable_anchors")
    if (
        type(anchors) is not tuple
        or len(anchors) != len(supplied)
        or any(type(anchor) is not StableEvidenceAnchor for anchor in anchors)
    ):
        raise ValueError("semantic_stable_anchor_mismatch")
    expected_sha = _canonical_sha256(
        _semantic_verification_obligation_payload(obligation, include_hash=False)
    )
    if object.__getattribute__(obligation, "obligation_sha256") != expected_sha:
        raise ValueError("semantic_verification_obligation_hash_mismatch")


def _exact_string_tuple_value(
    value: object,
    code: str,
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(code)
    if (not allow_empty and not value) or any(
        type(item) is not str or not item for item in value
    ):
        raise ValueError(code)
    if len(value) != len(set(value)):
        raise ValueError(f"duplicate_{code}")
    return value


@dataclass(frozen=True, slots=True, repr=False, init=False)
class _SemanticVerifierEvidence:
    index: int
    role: str
    doc_id: str
    content_kind: str
    content: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("semantic_verifier_request_factory_required")

    def __reduce__(self) -> object:
        raise TypeError("semantic_verifier_request_not_serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        raise TypeError("semantic_verifier_request_not_serializable")

    @classmethod
    def _create(
        cls,
        *,
        index: int,
        role: str,
        doc_id: str,
        content_kind: str,
        content: str,
        _token: object,
    ) -> _SemanticVerifierEvidence:
        if _token is not _SEMANTIC_REQUEST_TOKEN:
            raise ValueError("semantic_verifier_request_factory_required")
        result = object.__new__(cls)
        for name, value in (
            ("index", index),
            ("role", role),
            ("doc_id", doc_id),
            ("content_kind", content_kind),
            ("content", content),
        ):
            object.__setattr__(result, name, value)
        return result


@dataclass(frozen=True, slots=True, repr=False, init=False)
class _SemanticVerifierParentContext:
    parent_id: str
    parent_kind: str
    doc_id: str
    content: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("semantic_verifier_parent_context_factory_required")

    def __copy__(self) -> object:
        raise TypeError("semantic_verifier_parent_context_not_serializable")

    def __deepcopy__(self, memo: object) -> object:
        raise TypeError("semantic_verifier_parent_context_not_serializable")

    def __reduce__(self) -> object:
        raise TypeError("semantic_verifier_parent_context_not_serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        raise TypeError("semantic_verifier_parent_context_not_serializable")

    @classmethod
    def _create(
        cls,
        *,
        parent_id: str,
        parent_kind: str,
        doc_id: str,
        content: str,
        _token: object,
    ) -> _SemanticVerifierParentContext:
        if _token is not _SEMANTIC_REQUEST_TOKEN:
            raise ValueError("semantic_verifier_parent_context_factory_required")
        if any(
            type(value) is not str or (name != "content" and not value)
            for name, value in (
                ("parent_id", parent_id),
                ("parent_kind", parent_kind),
                ("doc_id", doc_id),
                ("content", content),
            )
        ):
            raise ValueError("semantic_verifier_parent_context_mismatch")
        result = object.__new__(cls)
        for name, value in (
            ("parent_id", parent_id),
            ("parent_kind", parent_kind),
            ("doc_id", doc_id),
            ("content", content),
        ):
            object.__setattr__(result, name, value)
        return result


@dataclass(frozen=True, slots=True, repr=False, init=False)
class _SemanticVerifierRequest:
    source_kind: str
    target_kind: str
    obligation_key: str
    target_doc_id: str | None
    field: str | None
    query: str
    evidence: tuple[_SemanticVerifierEvidence, ...]
    auxiliary_parent_context: tuple[_SemanticVerifierParentContext, ...]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("semantic_verifier_request_factory_required")

    def __reduce__(self) -> object:
        raise TypeError("semantic_verifier_request_not_serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        raise TypeError("semantic_verifier_request_not_serializable")

    @classmethod
    def _create(
        cls,
        *,
        source_kind: str,
        target_kind: str,
        obligation_key: str,
        target_doc_id: str | None,
        field: str | None,
        query: str,
        evidence: tuple[_SemanticVerifierEvidence, ...],
        auxiliary_parent_context: tuple[_SemanticVerifierParentContext, ...],
        _token: object,
    ) -> _SemanticVerifierRequest:
        if _token is not _SEMANTIC_REQUEST_TOKEN:
            raise ValueError("semantic_verifier_request_factory_required")
        result = object.__new__(cls)
        for name, value in (
            ("source_kind", source_kind),
            ("target_kind", target_kind),
            ("obligation_key", obligation_key),
            ("target_doc_id", target_doc_id),
            ("field", field),
            ("query", query),
            ("evidence", evidence),
            ("auxiliary_parent_context", auxiliary_parent_context),
        ):
            object.__setattr__(result, name, value)
        return result


@dataclass(frozen=True, slots=True)
class _SemanticVerificationObligationAuthority:
    weak: ReferenceType[SemanticVerificationObligation]
    issued_payload_sha256: str
    issuance_key: tuple[object, ...]
    source: object
    candidate_receipt: object
    source_state: HarnessState | None
    retrieval_obligation: RetrievalObligation | None
    fusion_receipt: FusionReceipt | None
    dense_receipt: LaneSearchReceipt | None
    lexical_receipt: LaneSearchReceipt | None
    registry: RuleRegistry | None
    policy: FollowupEvidencePolicy | None
    raw_query: str
    evidence: tuple[Evidence, ...]
    roles: tuple[str, ...]
    origin_seed_ids: tuple[str, ...]
    auxiliary_parents: tuple[ProvenanceParent, ...]
    base_obligation: SemanticVerificationObligation | None
    base_issuance_key: tuple[object, ...] | None
    parent_receipts: tuple[ParentContextReceipt, ...]
    bridge_receipts: tuple[BridgeContextReceipt, ...]
    rerank_receipt: object | None
    route_key: tuple[object, ...]
    execution_key: tuple[object, ...]
    owner_plan_sha256: str | None
    owner_plan_config_sha256: str | None
    rerank_k: int | None
    final_evidence_budget: int | None
    store: EvidenceStore
    config: HarnessExecutionConfig
    runtime: HarnessRuntimeBinding
    verifier_authority: _ComponentAuthority


_SEMANTIC_OBLIGATION_AUTHORITIES: dict[
    int, _SemanticVerificationObligationAuthority
] = {}
_ISSUED_SEMANTIC_OBLIGATION_AUTHORITIES = _SEMANTIC_OBLIGATION_AUTHORITIES


def _build_semantic_obligation_accessors(
    visible: dict[int, _SemanticVerificationObligationAuthority],
) -> tuple[
    FunctionType,
    FunctionType,
    FunctionType,
    FunctionType,
    FunctionType,
    FunctionType,
    FunctionType,
]:
    shadow: dict[int, tuple[object, ...]] = {}
    cache: dict[tuple[object, ...], ReferenceType[SemanticVerificationObligation]] = {}
    history: dict[tuple[object, ...], str] = {}
    history_shadow: dict[tuple[object, ...], str] = {}
    source_refs: dict[int, ReferenceType[object]] = {}
    source_execution_keys: dict[int, set[tuple[object, ...]]] = {}
    authority_lock = Lock()

    def drop_source(identity: int, dead: ReferenceType[object]) -> None:
        with authority_lock:
            if dict.get(source_refs, identity) is not dead:
                return
            keys = dict.pop(source_execution_keys, identity, set())
            for execution_key in tuple(keys):
                dict.pop(history, execution_key, None)
                dict.pop(history_shadow, execution_key, None)
            dict.pop(source_refs, identity, None)

    def snapshot(authority: _SemanticVerificationObligationAuthority) -> tuple[object, ...]:
        return tuple(
            object.__getattribute__(authority, name)
            for name in _SemanticVerificationObligationAuthority.__slots__
        )

    def validated_unlocked(
        obligation: SemanticVerificationObligation,
    ) -> _SemanticVerificationObligationAuthority | None:
        identity = id(obligation)
        current = dict.get(visible, identity)
        sealed = dict.get(shadow, identity)
        if current is None and sealed is None:
            return None
        if (
            type(current) is not _SemanticVerificationObligationAuthority
            or type(sealed) is not tuple
            or object.__getattribute__(current, "weak")() is not obligation
            or len(sealed) != len(_SemanticVerificationObligationAuthority.__slots__)
            or any(
                object.__getattribute__(current, name) is not sealed_value
                for name, sealed_value in zip(
                    _SemanticVerificationObligationAuthority.__slots__, sealed
                )
            )
        ):
            raise ValueError("semantic_verification_obligation_authority_drift")
        return current

    def register(
        obligation: SemanticVerificationObligation,
        authority: _SemanticVerificationObligationAuthority,
    ) -> None:
        with authority_lock:
            if validated_unlocked(obligation) is not None:
                raise ValueError("semantic_verification_obligation_authority_drift")
            identity = id(obligation)
            dict.__setitem__(visible, identity, authority)
            dict.__setitem__(shadow, identity, snapshot(authority))
            dict.__setitem__(cache, authority.issuance_key, authority.weak)
            source = object.__getattribute__(authority, "source")
            source_identity = id(source)
            source_weak = dict.get(source_refs, source_identity)
            if source_weak is None or source_weak() is not source:
                if source_weak is not None:
                    raise ValueError("semantic_verification_source_history_drift")
                source_weak = ref(
                    source,
                    lambda dead, source_identity=source_identity: drop_source(
                        source_identity, dead
                    ),
                )
                dict.__setitem__(source_refs, source_identity, source_weak)
                dict.__setitem__(source_execution_keys, source_identity, set())
            execution_key = object.__getattribute__(authority, "execution_key")
            dict.__getitem__(source_execution_keys, source_identity).add(
                execution_key
            )

    def read(
        obligation: SemanticVerificationObligation,
    ) -> _SemanticVerificationObligationAuthority:
        with authority_lock:
            current = validated_unlocked(obligation)
            if current is None:
                raise ValueError("semantic_verification_obligation_authority_required")
            return current

    def cached(
        issuance_key: tuple[object, ...],
    ) -> SemanticVerificationObligation | None:
        with authority_lock:
            weak = dict.get(cache, issuance_key)
            if weak is None:
                return None
            current = weak()
            if current is None:
                dict.pop(cache, issuance_key, None)
                return None
            validated_unlocked(current)
            return current

    def drop(
        identity: int,
        dead: ReferenceType[SemanticVerificationObligation],
    ) -> None:
        with authority_lock:
            sealed = dict.get(shadow, identity)
            if type(sealed) is tuple and sealed and tuple.__getitem__(sealed, 0) is dead:
                current = dict.get(visible, identity)
                if type(current) is _SemanticVerificationObligationAuthority:
                    key = object.__getattribute__(current, "issuance_key")
                    if dict.get(cache, key) is dead:
                        dict.pop(cache, key, None)
                dict.pop(visible, identity, None)
                dict.pop(shadow, identity, None)

    def transition(
        execution_key: tuple[object, ...],
        expected: str | None,
        updated: str,
    ) -> None:
        with authority_lock:
            current = dict.get(history, execution_key)
            mirror = dict.get(history_shadow, execution_key)
            if current is not mirror:
                raise ValueError("semantic_verification_history_drift")
            if current != expected:
                raise ValueError("semantic_verification_already_consumed")
            dict.__setitem__(history, execution_key, updated)
            dict.__setitem__(history_shadow, execution_key, updated)

    def status(execution_key: tuple[object, ...]) -> str | None:
        with authority_lock:
            current = dict.get(history, execution_key)
            mirror = dict.get(history_shadow, execution_key)
            if current is not mirror:
                raise ValueError("semantic_verification_history_drift")
            return current

    return register, read, cached, drop, transition, status, drop_source


(
    _register_semantic_obligation_authority,
    _read_semantic_obligation_authority,
    _cached_semantic_obligation,
    _drop_semantic_obligation_authority,
    _transition_semantic_execution,
    _semantic_execution_status,
    _drop_semantic_source_history,
) = _build_semantic_obligation_accessors(
    _ISSUED_SEMANTIC_OBLIGATION_AUTHORITIES
)


def _semantic_execution_key(
    authority: _SemanticVerificationObligationAuthority,
    obligation: SemanticVerificationObligation,
) -> tuple[object, ...]:
    execution_key = object.__getattribute__(authority, "execution_key")
    if type(execution_key) is not tuple:
        raise ValueError("semantic_verification_execution_authority_drift")
    return execution_key


def _semantic_public_entry(
    dependency_checker: object,
    dependency_checker_code: object,
) -> None:
    module_namespace = globals()
    checker_defaults = (
        None
        if type(dependency_checker) is not FunctionType
        else object.__getattribute__(dependency_checker, "__defaults__")
    )
    if (
        dependency_checker
        is not dict.get(module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER")
        or type(dependency_checker) is not FunctionType
        or object.__getattribute__(dependency_checker, "__code__")
        is not dependency_checker_code
        or dependency_checker_code
        is not dict.get(
            module_namespace, "_PINNED_RUNTIME_GATE_DEPENDENCY_CHECKER_CODE"
        )
        or checker_defaults
        is not dict.get(module_namespace, "_ISSUED_RUNTIME_GATE_DEPENDENCY_DEFAULTS")
        or type(checker_defaults) is not tuple
        or len(checker_defaults) != 6
        or tuple.__getitem__(checker_defaults, 0) is not module_namespace
        or object.__getattribute__(dependency_checker, "__kwdefaults__") is not None
    ):
        raise ValueError("harness_runtime_validation_dependency_drift")
    dependency_checker()


def _semantic_common_preflight(
    *,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
) -> _HarnessRuntimeAuthority:
    validate_harness_execution_config(config)
    if object.__getattribute__(config, "mode") != "e1_bounded":
        raise ValueError("semantic_verification_requires_e1_bounded")
    validate_harness_runtime_binding(binding=runtime, store=store)
    runtime_authority = _require_harness_runtime_authority(runtime)
    return runtime_authority


def _semantic_owner_plan_budget(
    authority: _SemanticVerificationObligationAuthority,
) -> tuple[str, str, int, int]:
    if type(authority) is not _SemanticVerificationObligationAuthority:
        raise TypeError("semantic_verification_obligation_authority_required")
    source = object.__getattribute__(authority, "source")
    planning = object.__getattribute__(source, "planning")
    plan = object.__getattribute__(planning, "plan")
    budget = object.__getattribute__(plan, "budget")
    rerank_k = object.__getattribute__(budget, "rerank_k")
    final_evidence_budget = object.__getattribute__(
        budget, "final_evidence_budget"
    )
    owner_plan_config_sha256 = object.__getattribute__(plan, "config_sha256")
    _require_hash(
        owner_plan_config_sha256,
        "invalid_semantic_owner_plan_config_sha256",
    )
    if (
        type(rerank_k) is not int
        or rerank_k < 1
        or type(final_evidence_budget) is not int
        or final_evidence_budget < 1
        or final_evidence_budget > rerank_k
    ):
        raise ValueError("invalid_semantic_owner_rerank_budget")
    return (
        _canonical_sha256(plan.to_dict()),
        owner_plan_config_sha256,
        rerank_k,
        final_evidence_budget,
    )


def _derive_followup_semantic_target(
    *,
    bound: BoundFollowup,
    outcome: FollowupRetrievalOutcome,
    obligation_key: str,
    store: EvidenceStore,
    registry: RuleRegistry,
    policy: FollowupEvidencePolicy,
) -> tuple[HarnessState, str, str | None, str | None, tuple[str, ...]]:
    state = build_e1_followup_harness_state(
        bound=bound,
        outcome=outcome,
        store=store,
        registry=registry,
        policy=policy,
    )
    validate_harness_state(state=state, store=store)
    if type(obligation_key) is not str or not obligation_key:
        raise ValueError("invalid_semantic_verification_target")
    entry = next(
        (
            item
            for item in object.__getattribute__(
                object.__getattribute__(state, "belief"), "evidence_map"
            )
            if object.__getattribute__(item, "obligation_key") == obligation_key
        ),
        None,
    )
    if entry is None:
        raise ValueError("unknown_semantic_verification_obligation_key")
    candidates = object.__getattribute__(entry, "candidate_evidence_ids")
    if not candidates:
        raise ValueError("semantic_verification_candidates_required")
    if obligation_key == "$answer_support":
        return state, "answer_support", None, None, candidates
    slot = next(
        (
            item
            for item in object.__getattribute__(
                object.__getattribute__(bound, "plan"), "required_slots"
            )
            if object.__getattribute__(item, "key") == obligation_key
        ),
        None,
    )
    if slot is None:
        raise ValueError("unknown_semantic_verification_obligation_key")
    return (
        state,
        "field_value",
        object.__getattribute__(slot, "doc_id"),
        object.__getattribute__(slot, "field"),
        candidates,
    )


def _create_semantic_verification_obligation(
    *,
    source_kind: str,
    target_kind: str,
    obligation_key: str,
    target_doc_id: str | None,
    field: str | None,
    owner_binding_sha256: str,
    retrieval_obligation_sha256: str | None,
    candidate_receipt_sha256: str,
    source_state: HarnessState | None,
    raw_query: str,
    candidate_evidence_ids: tuple[str, ...],
    ordered_stable_anchors: tuple[StableEvidenceAnchor, ...],
    issuance_key: tuple[object, ...],
    source: object,
    candidate_receipt: object,
    retrieval_obligation: RetrievalObligation | None,
    fusion_receipt: FusionReceipt | None,
    dense_receipt: LaneSearchReceipt | None,
    lexical_receipt: LaneSearchReceipt | None,
    registry: RuleRegistry | None,
    policy: FollowupEvidencePolicy | None,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    verifier_authority: _ComponentAuthority,
) -> SemanticVerificationObligation:
    cached = _cached_semantic_obligation(issuance_key)
    if cached is not None:
        _validate_semantic_verification_obligation_exact(
            obligation=cached, store=store, config=config, runtime=runtime
        )
        return cached
    evidence = tuple(store.get(evidence_id) for evidence_id in candidate_evidence_ids)
    if field is not None and any(
        object.__getattribute__(item, "doc_id") != target_doc_id
        for item in evidence
    ):
        raise ValueError("semantic_verification_target_doc_mismatch")
    supplied = candidate_evidence_ids
    payload = {
        "derivation_kind": "base",
        "source_kind": source_kind,
        "target_kind": target_kind,
        "obligation_key": obligation_key,
        "target_doc_id": target_doc_id,
        "field": field,
        "execution_kind": object.__getattribute__(runtime, "execution_kind"),
        "owner_binding_sha256": owner_binding_sha256,
        "retrieval_obligation_sha256": retrieval_obligation_sha256,
        "candidate_receipt_sha256": candidate_receipt_sha256,
        "source_state_sha256": (
            None
            if source_state is None
            else object.__getattribute__(source_state, "state_sha256")
        ),
        "base_semantic_obligation_sha256": None,
        "parent_context_receipt_sha256s": (),
        "bridge_context_receipt_sha256s": (),
        "rerank_receipt_sha256": None,
        "owner_plan_sha256": None,
        "owner_plan_config_sha256": None,
        "rerank_k": None,
        "final_evidence_budget": None,
        "query_sha256": _query_sha256(raw_query),
        "evidence_store_sha256": object.__getattribute__(store, "bundle_sha256"),
        "execution_config_sha256": object.__getattribute__(config, "config_sha256"),
        "runtime_binding_sha256": object.__getattribute__(runtime, "binding_sha256"),
        "candidate_evidence_ids": candidate_evidence_ids,
        "bridge_evidence_ids": (),
        "context_evidence_ids": (),
        "supplied_evidence_ids": supplied,
        "ordered_stable_anchors": ordered_stable_anchors,
    }
    temporary = object.__new__(SemanticVerificationObligation)
    for name, value in payload.items():
        object.__setattr__(temporary, name, value)
    object.__setattr__(temporary, "obligation_sha256", "0" * 64)
    payload["obligation_sha256"] = _canonical_sha256(
        _semantic_verification_obligation_payload(temporary, include_hash=False)
    )
    result = SemanticVerificationObligation._create(
        payload=payload, _token=_SEMANTIC_OBLIGATION_TOKEN
    )
    identity = id(result)
    weak = ref(
        result,
        lambda dead, identity=identity: _drop_semantic_obligation_authority(
            identity, dead
        ),
    )
    authority = _SemanticVerificationObligationAuthority(
        weak=weak,
        issued_payload_sha256=_canonical_sha256(result.to_dict()),
        issuance_key=issuance_key,
        source=source,
        candidate_receipt=candidate_receipt,
        source_state=source_state,
        retrieval_obligation=retrieval_obligation,
        fusion_receipt=fusion_receipt,
        dense_receipt=dense_receipt,
        lexical_receipt=lexical_receipt,
        registry=registry,
        policy=policy,
        raw_query=raw_query,
        evidence=evidence,
        roles=tuple("candidate" for _ in evidence),
        origin_seed_ids=candidate_evidence_ids,
        auxiliary_parents=(),
        base_obligation=None,
        base_issuance_key=None,
        parent_receipts=(),
        bridge_receipts=(),
        rerank_receipt=None,
        route_key=(
            "semantic-route-v1",
            issuance_key,
            obligation_key,
            id(store),
            id(config),
            id(runtime),
        ),
        execution_key=(
            "semantic-execution-v2",
            "base",
            issuance_key,
            object.__getattribute__(result, "obligation_sha256"),
            id(store),
            id(config),
            id(runtime),
        ),
        owner_plan_sha256=None,
        owner_plan_config_sha256=None,
        rerank_k=None,
        final_evidence_budget=None,
        store=store,
        config=config,
        runtime=runtime,
        verifier_authority=verifier_authority,
    )
    _register_semantic_obligation_authority(result, authority)
    return result


def _issue_retrieval_semantic_verification_obligation(
    *,
    expected_source_kind: str,
    obligation: RetrievalObligation,
    fusion_receipt: FusionReceipt,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
) -> SemanticVerificationObligation:
    runtime_authority = _semantic_common_preflight(
        store=store, config=config, runtime=runtime
    )
    if (
        type(obligation) is not RetrievalObligation
        or object.__getattribute__(obligation, "source_kind")
        != expected_source_kind
    ):
        raise ValueError("semantic_verification_source_kind_mismatch")
    fusion_authority = _read_fusion_receipt_authority(fusion_receipt)
    validate_fusion_receipt(
        receipt=fusion_receipt,
        obligation=obligation,
        dense_receipt=object.__getattribute__(fusion_authority, "dense_receipt"),
        lexical_receipt=object.__getattribute__(fusion_authority, "lexical_receipt"),
        store=store,
        config=config,
        runtime=runtime,
    )
    candidates = object.__getattribute__(fusion_receipt, "ordered_evidence_ids")
    if (
        object.__getattribute__(fusion_receipt, "outcome") != "applied"
        or not candidates
    ):
        raise ValueError("semantic_verification_candidates_required")
    retrieval_authority = _require_retrieval_obligation_authority(obligation)
    _require_retrieval_owner(
        source_kind=expected_source_kind,
        source=object.__getattribute__(retrieval_authority, "source"),
        source_projector=object.__getattribute__(
            retrieval_authority, "source_projector"
        ),
        source_validator=object.__getattribute__(
            retrieval_authority, "source_validator"
        ),
    )
    projected = object.__getattribute__(retrieval_authority, "source_projector")(
        bound=object.__getattribute__(retrieval_authority, "source"),
        store=store,
    )
    normalized = _normalized_owner_projections(
        source_kind=expected_source_kind, projected=projected
    )
    ordinal = object.__getattribute__(retrieval_authority, "projection_ordinal")
    if ordinal < 1 or ordinal > len(normalized):
        raise ValueError("semantic_verification_projection_mismatch")
    normalized_target = normalized[ordinal - 1]
    raw_target = projected if expected_source_kind == "fact" else projected[ordinal - 1]
    raw_query = object.__getattribute__(retrieval_authority, "raw_query")
    if (
        normalized_target["query"] != raw_query
        or normalized_target["obligation_key"]
        != object.__getattribute__(obligation, "obligation_key")
    ):
        raise ValueError("semantic_verification_projection_mismatch")
    if expected_source_kind == "fact":
        target_kind, target_doc_id, field = "answer_support", None, None
    else:
        target_kind = "field_value"
        target_doc_id = object.__getattribute__(raw_target, "doc_id")
        field = object.__getattribute__(raw_target, "field")
    anchors = object.__getattribute__(fusion_receipt, "ordered_stable_anchors")
    issuance_key = (
        "semantic-v1",
        expected_source_kind,
        id(object.__getattribute__(retrieval_authority, "source")),
        ordinal,
        id(fusion_receipt),
        id(store),
        id(config),
        id(runtime),
    )
    return _create_semantic_verification_obligation(
        source_kind=expected_source_kind,
        target_kind=target_kind,
        obligation_key=object.__getattribute__(obligation, "obligation_key"),
        target_doc_id=target_doc_id,
        field=field,
        owner_binding_sha256=object.__getattribute__(
            obligation, "execution_binding_sha256"
        ),
        retrieval_obligation_sha256=object.__getattribute__(
            obligation, "obligation_sha256"
        ),
        candidate_receipt_sha256=object.__getattribute__(
            fusion_receipt, "receipt_sha256"
        ),
        source_state=None,
        raw_query=raw_query,
        candidate_evidence_ids=candidates,
        ordered_stable_anchors=anchors,
        issuance_key=issuance_key,
        source=object.__getattribute__(retrieval_authority, "source"),
        candidate_receipt=fusion_receipt,
        retrieval_obligation=obligation,
        fusion_receipt=fusion_receipt,
        dense_receipt=object.__getattribute__(fusion_authority, "dense_receipt"),
        lexical_receipt=object.__getattribute__(fusion_authority, "lexical_receipt"),
        registry=None,
        policy=None,
        store=store,
        config=config,
        runtime=runtime,
        verifier_authority=object.__getattribute__(runtime_authority, "verifier"),
    )


def issue_fact_semantic_verification_obligation(
    *,
    obligation: RetrievalObligation,
    fusion_receipt: FusionReceipt,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    _dependency_checker=None,
    _dependency_checker_code=None,
) -> SemanticVerificationObligation:
    _semantic_public_entry(_dependency_checker, _dependency_checker_code)
    return _issue_retrieval_semantic_verification_obligation(
        expected_source_kind="fact",
        obligation=obligation,
        fusion_receipt=fusion_receipt,
        store=store,
        config=config,
        runtime=runtime,
    )


def issue_compare_semantic_verification_obligation(
    *,
    obligation: RetrievalObligation,
    fusion_receipt: FusionReceipt,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    _dependency_checker=None,
    _dependency_checker_code=None,
) -> SemanticVerificationObligation:
    _semantic_public_entry(_dependency_checker, _dependency_checker_code)
    return _issue_retrieval_semantic_verification_obligation(
        expected_source_kind="compare",
        obligation=obligation,
        fusion_receipt=fusion_receipt,
        store=store,
        config=config,
        runtime=runtime,
    )


def issue_followup_semantic_verification_obligation(
    *,
    bound: BoundFollowup,
    outcome: FollowupRetrievalOutcome,
    obligation_key: str,
    store: EvidenceStore,
    registry: RuleRegistry,
    policy: FollowupEvidencePolicy,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    _dependency_checker=None,
    _dependency_checker_code=None,
) -> SemanticVerificationObligation:
    _semantic_public_entry(_dependency_checker, _dependency_checker_code)
    runtime_authority = _semantic_common_preflight(
        store=store, config=config, runtime=runtime
    )
    state, target_kind, target_doc_id, field, candidates = (
        _derive_followup_semantic_target(
            bound=bound,
            outcome=outcome,
            obligation_key=obligation_key,
            store=store,
            registry=registry,
            policy=policy,
        )
    )
    raw_query = object.__getattribute__(
        object.__getattribute__(bound, "plan"), "normalized_query"
    )
    outcome_sha256 = _canonical_sha256(outcome.to_dict())
    issuance_key = (
        "semantic-v1",
        "follow_up",
        id(bound),
        id(outcome),
        obligation_key,
        id(store),
        id(config),
        id(runtime),
    )
    return _create_semantic_verification_obligation(
        source_kind="follow_up",
        target_kind=target_kind,
        obligation_key=obligation_key,
        target_doc_id=target_doc_id,
        field=field,
        owner_binding_sha256=object.__getattribute__(bound, "binding_sha256"),
        retrieval_obligation_sha256=None,
        candidate_receipt_sha256=outcome_sha256,
        source_state=state,
        raw_query=raw_query,
        candidate_evidence_ids=candidates,
        ordered_stable_anchors=tuple(
            _stable_anchor(store.get(evidence_id)) for evidence_id in candidates
        ),
        issuance_key=issuance_key,
        source=bound,
        candidate_receipt=outcome,
        retrieval_obligation=None,
        fusion_receipt=None,
        dense_receipt=None,
        lexical_receipt=None,
        registry=registry,
        policy=policy,
        store=store,
        config=config,
        runtime=runtime,
        verifier_authority=object.__getattribute__(runtime_authority, "verifier"),
    )


def _validate_semantic_verification_obligation_exact(
    *,
    obligation: SemanticVerificationObligation,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
) -> _SemanticVerificationObligationAuthority:
    runtime_authority = _semantic_common_preflight(
        store=store, config=config, runtime=runtime
    )
    _validate_semantic_verification_obligation_payload(obligation)
    authority = _read_semantic_obligation_authority(obligation)
    if (
        object.__getattribute__(authority, "store") is not store
        or object.__getattribute__(authority, "config") is not config
        or object.__getattribute__(authority, "runtime") is not runtime
        or object.__getattribute__(authority, "verifier_authority")
        is not object.__getattribute__(runtime_authority, "verifier")
    ):
        raise ValueError("semantic_verification_obligation_dependency_identity_mismatch")
    if object.__getattribute__(authority, "issued_payload_sha256") != _canonical_sha256(
        obligation.to_dict()
    ):
        raise ValueError("semantic_verification_obligation_authority_drift")
    evidence = object.__getattribute__(authority, "evidence")
    supplied = object.__getattribute__(obligation, "supplied_evidence_ids")
    roles = object.__getattribute__(authority, "roles")
    derivation_kind = object.__getattribute__(obligation, "derivation_kind")
    if derivation_kind == "base":
        expected_roles = tuple("candidate" for _ in evidence)
    else:
        candidate_ids = set(
            object.__getattribute__(obligation, "candidate_evidence_ids")
        )
        bridge_ids = set(
            object.__getattribute__(obligation, "bridge_evidence_ids")
        )
        expected_roles = tuple(
            "candidate" if evidence_id in candidate_ids else "bridge"
            for evidence_id in supplied
        )
        if any(evidence_id not in candidate_ids | bridge_ids for evidence_id in supplied):
            raise ValueError("semantic_verification_evidence_authority_drift")
    if (
        type(evidence) is not tuple
        or len(evidence) != len(supplied)
        or type(roles) is not tuple
        or roles != expected_roles
    ):
        raise ValueError("semantic_verification_evidence_authority_drift")
    for index, item in enumerate(evidence):
        if (
            type(item) is not Evidence
            or store.get(supplied[index]) is not item
            or _stable_anchor(item).to_dict()
            != object.__getattribute__(
                obligation, "ordered_stable_anchors"
            )[index].to_dict()
        ):
            raise ValueError("semantic_verification_evidence_authority_drift")
    raw_query = object.__getattribute__(authority, "raw_query")
    if object.__getattribute__(obligation, "query_sha256") != _query_sha256(raw_query):
        raise ValueError("semantic_verification_query_authority_drift")
    if derivation_kind == "reranked":
        base = object.__getattribute__(authority, "base_obligation")
        parents = object.__getattribute__(authority, "parent_receipts")
        bridges = object.__getattribute__(authority, "bridge_receipts")
        rerank_receipt = object.__getattribute__(authority, "rerank_receipt")
        if (
            type(base) is not SemanticVerificationObligation
            or type(parents) is not tuple
            or type(bridges) is not tuple
            or type(rerank_receipt) is not RerankReceipt
        ):
            raise ValueError("semantic_derived_authority_drift")
        base_authority = _validate_semantic_verification_obligation_exact(
            obligation=base, store=store, config=config, runtime=runtime
        )
        rerank_authority = _validate_rerank_receipt_exact(
            receipt=rerank_receipt,
            obligation=base,
            parent_receipts=parents,
            bridge_receipts=bridges,
            store=store,
            config=config,
            runtime=runtime,
        )
        final_budget = object.__getattribute__(
            obligation, "final_evidence_budget"
        )
        expected_evidence = object.__getattribute__(
            rerank_authority, "ordered_evidence"
        )[:final_budget]
        expected_origins = object.__getattribute__(
            rerank_authority, "ordered_origin_seed_ids"
        )[:final_budget]
        if (
            object.__getattribute__(base, "derivation_kind") != "base"
            or object.__getattribute__(authority, "source")
            is not object.__getattribute__(base_authority, "source")
            or object.__getattribute__(authority, "base_issuance_key")
            != object.__getattribute__(base_authority, "issuance_key")
            or object.__getattribute__(obligation, "base_semantic_obligation_sha256")
            != object.__getattribute__(base, "obligation_sha256")
            or object.__getattribute__(obligation, "parent_context_receipt_sha256s")
            != tuple(object.__getattribute__(item, "receipt_sha256") for item in parents)
            or object.__getattribute__(obligation, "bridge_context_receipt_sha256s")
            != tuple(object.__getattribute__(item, "receipt_sha256") for item in bridges)
            or object.__getattribute__(obligation, "rerank_receipt_sha256")
            != object.__getattribute__(rerank_receipt, "receipt_sha256")
            or object.__getattribute__(obligation, "owner_plan_sha256")
            != object.__getattribute__(rerank_receipt, "owner_plan_sha256")
            or object.__getattribute__(obligation, "owner_plan_config_sha256")
            != object.__getattribute__(rerank_receipt, "owner_plan_config_sha256")
            or object.__getattribute__(obligation, "rerank_k")
            != object.__getattribute__(rerank_receipt, "rerank_k")
            or len(supplied) > final_budget
            or len(evidence) != len(expected_evidence)
            or any(current is not expected for current, expected in zip(evidence, expected_evidence))
            or object.__getattribute__(authority, "origin_seed_ids")
            != expected_origins
        ):
            raise ValueError("semantic_derived_authority_drift")
        return authority
    source_kind = object.__getattribute__(obligation, "source_kind")
    if source_kind in {"fact", "compare"}:
        retrieval = object.__getattribute__(authority, "retrieval_obligation")
        fusion = object.__getattribute__(authority, "fusion_receipt")
        dense = object.__getattribute__(authority, "dense_receipt")
        lexical = object.__getattribute__(authority, "lexical_receipt")
        if (
            type(retrieval) is not RetrievalObligation
            or type(fusion) is not FusionReceipt
            or type(dense) is not LaneSearchReceipt
            or type(lexical) is not LaneSearchReceipt
        ):
            raise ValueError("semantic_verification_source_authority_drift")
        validate_fusion_receipt(
            receipt=fusion,
            obligation=retrieval,
            dense_receipt=dense,
            lexical_receipt=lexical,
            store=store,
            config=config,
            runtime=runtime,
        )
        retrieval_authority = _require_retrieval_obligation_authority(retrieval)
        if object.__getattribute__(retrieval_authority, "source") is not object.__getattribute__(authority, "source"):
            raise ValueError("semantic_verification_source_authority_drift")
        if (
            object.__getattribute__(fusion, "ordered_evidence_ids")
            != object.__getattribute__(obligation, "candidate_evidence_ids")
            or object.__getattribute__(fusion, "receipt_sha256")
            != object.__getattribute__(obligation, "candidate_receipt_sha256")
        ):
            raise ValueError("semantic_verification_candidate_receipt_drift")
        projected = object.__getattribute__(retrieval_authority, "source_projector")(
            bound=object.__getattribute__(retrieval_authority, "source"), store=store
        )
        normalized = _normalized_owner_projections(
            source_kind=source_kind, projected=projected
        )
        ordinal = object.__getattribute__(retrieval_authority, "projection_ordinal")
        raw_target = projected if source_kind == "fact" else projected[ordinal - 1]
        if normalized[ordinal - 1]["query"] != raw_query:
            raise ValueError("semantic_verification_projection_mismatch")
        if source_kind == "compare" and (
            object.__getattribute__(raw_target, "doc_id")
            != object.__getattribute__(obligation, "target_doc_id")
            or object.__getattribute__(raw_target, "field")
            != object.__getattribute__(obligation, "field")
        ):
            raise ValueError("semantic_verification_projection_mismatch")
    else:
        bound = object.__getattribute__(authority, "source")
        outcome = object.__getattribute__(authority, "candidate_receipt")
        registry = object.__getattribute__(authority, "registry")
        policy = object.__getattribute__(authority, "policy")
        rebuilt, target_kind, target_doc_id, field, candidates = (
            _derive_followup_semantic_target(
                bound=bound,
                outcome=outcome,
                obligation_key=object.__getattribute__(obligation, "obligation_key"),
                store=store,
                registry=registry,
                policy=policy,
            )
        )
        source_state = object.__getattribute__(authority, "source_state")
        if (
            type(source_state) is not HarnessState
            or rebuilt.to_dict() != source_state.to_dict()
            or object.__getattribute__(source_state, "state_sha256")
            != object.__getattribute__(obligation, "source_state_sha256")
            or target_kind != object.__getattribute__(obligation, "target_kind")
            or target_doc_id != object.__getattribute__(obligation, "target_doc_id")
            or field != object.__getattribute__(obligation, "field")
            or candidates != object.__getattribute__(obligation, "candidate_evidence_ids")
            or _canonical_sha256(outcome.to_dict())
            != object.__getattribute__(obligation, "candidate_receipt_sha256")
            or object.__getattribute__(bound, "binding_sha256")
            != object.__getattribute__(obligation, "owner_binding_sha256")
        ):
            raise ValueError("semantic_verification_followup_source_drift")
        validate_harness_state(state=source_state, store=store)
    return authority


def validate_semantic_verification_obligation(
    *,
    obligation: SemanticVerificationObligation,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    _dependency_checker=None,
    _dependency_checker_code=None,
) -> None:
    _semantic_public_entry(_dependency_checker, _dependency_checker_code)
    _validate_semantic_verification_obligation_exact(
        obligation=obligation, store=store, config=config, runtime=runtime
    )


# EH2.6.c3.1 bounded parent/bridge source receipts -----------------------------

_CONTEXT_BRIDGE_KIND_PAIRS = (
    ("table", "table_row_group"),
    ("figure", "figure_object"),
)
_CONTEXT_PENDING = object()
_CONTEXT_COMPLETED = object()
_CONTEXT_FAILED = object()


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class ParentContextReceipt:
    """Content-free proof that a semantic seed resolved to its exact parent."""

    outcome: str
    semantic_obligation_sha256: str
    seed_evidence_id: str
    seed_stable_anchor: StableEvidenceAnchor
    parent_id: str
    parent_kind: str
    parent_doc_id: str
    parent_content_sha256: str
    parent_locator_sha256: str
    evidence_store_sha256: str
    execution_config_sha256: str
    runtime_binding_sha256: str
    receipt_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("parent_context_receipt_factory_required")

    def __copy__(self) -> object:
        raise TypeError("parent_context_receipt_not_serializable")

    def __deepcopy__(self, memo: object) -> object:
        raise TypeError("parent_context_receipt_not_serializable")

    def __reduce__(self) -> object:
        raise TypeError("parent_context_receipt_not_serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        raise TypeError("parent_context_receipt_not_serializable")

    @classmethod
    def _create(
        cls,
        *,
        payload: Mapping[str, Any],
        _token: object,
    ) -> ParentContextReceipt:
        if _token is not _PARENT_CONTEXT_RECEIPT_TOKEN:
            raise ValueError("parent_context_receipt_factory_required")
        result = object.__new__(cls)
        for name in cls.__slots__:
            if name != "__weakref__":
                object.__setattr__(result, name, payload[name])
        _validate_parent_context_receipt_payload(result)
        return result

    def to_dict(self) -> dict[str, Any]:
        _validate_parent_context_receipt_payload(self)
        return _parent_context_receipt_payload(self, include_hash=True)


def _parent_context_receipt_payload(
    receipt: ParentContextReceipt,
    *,
    include_hash: bool,
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "outcome": object.__getattribute__(receipt, "outcome"),
        "semantic_obligation_sha256": object.__getattribute__(
            receipt, "semantic_obligation_sha256"
        ),
        "seed_evidence_id": object.__getattribute__(
            receipt, "seed_evidence_id"
        ),
        "seed_stable_anchor": object.__getattribute__(
            receipt, "seed_stable_anchor"
        ).to_dict(),
        "parent_id": object.__getattribute__(receipt, "parent_id"),
        "parent_kind": object.__getattribute__(receipt, "parent_kind"),
        "parent_doc_id": object.__getattribute__(receipt, "parent_doc_id"),
        "parent_content_sha256": object.__getattribute__(
            receipt, "parent_content_sha256"
        ),
        "parent_locator_sha256": object.__getattribute__(
            receipt, "parent_locator_sha256"
        ),
        "evidence_store_sha256": object.__getattribute__(
            receipt, "evidence_store_sha256"
        ),
        "execution_config_sha256": object.__getattribute__(
            receipt, "execution_config_sha256"
        ),
        "runtime_binding_sha256": object.__getattribute__(
            receipt, "runtime_binding_sha256"
        ),
    }
    if include_hash:
        payload["receipt_sha256"] = object.__getattribute__(
            receipt, "receipt_sha256"
        )
    return payload


def _validate_parent_context_receipt_payload(
    receipt: ParentContextReceipt,
) -> None:
    if type(receipt) is not ParentContextReceipt:
        raise TypeError("parent_context_receipt_required")
    if object.__getattribute__(receipt, "outcome") != "applied":
        raise ValueError("parent_context_receipt_outcome_mismatch")
    for name in ("seed_evidence_id", "parent_id", "parent_kind", "parent_doc_id"):
        value = object.__getattribute__(receipt, name)
        if type(value) is not str or not value:
            raise ValueError("invalid_parent_context_receipt_identity")
    for name in (
        "semantic_obligation_sha256",
        "parent_content_sha256",
        "parent_locator_sha256",
        "evidence_store_sha256",
        "execution_config_sha256",
        "runtime_binding_sha256",
        "receipt_sha256",
    ):
        _require_hash(object.__getattribute__(receipt, name), f"invalid_{name}")
    anchor = object.__getattribute__(receipt, "seed_stable_anchor")
    if type(anchor) is not StableEvidenceAnchor:
        raise TypeError("parent_context_seed_anchor_required")
    if object.__getattribute__(anchor, "doc_id") != object.__getattribute__(
        receipt, "parent_doc_id"
    ):
        raise ValueError("parent_context_seed_parent_doc_mismatch")
    expected = _canonical_sha256(
        _parent_context_receipt_payload(receipt, include_hash=False)
    )
    if object.__getattribute__(receipt, "receipt_sha256") != expected:
        raise ValueError("parent_context_receipt_hash_mismatch")


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class BridgeContextReceipt:
    """Content-free exact result of one table or figure bridge lookup."""

    bridge_kind: str
    evidence_kind: str
    outcome: str
    semantic_obligation_sha256: str
    seed_evidence_id: str
    seed_stable_anchor: StableEvidenceAnchor
    linked_evidence_ids: tuple[str, ...]
    ordered_stable_anchors: tuple[StableEvidenceAnchor, ...]
    evidence_store_sha256: str
    execution_config_sha256: str
    runtime_binding_sha256: str
    receipt_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("bridge_context_receipt_factory_required")

    def __copy__(self) -> object:
        raise TypeError("bridge_context_receipt_not_serializable")

    def __deepcopy__(self, memo: object) -> object:
        raise TypeError("bridge_context_receipt_not_serializable")

    def __reduce__(self) -> object:
        raise TypeError("bridge_context_receipt_not_serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        raise TypeError("bridge_context_receipt_not_serializable")

    @classmethod
    def _create(
        cls,
        *,
        payload: Mapping[str, Any],
        _token: object,
    ) -> BridgeContextReceipt:
        if _token is not _BRIDGE_CONTEXT_RECEIPT_TOKEN:
            raise ValueError("bridge_context_receipt_factory_required")
        result = object.__new__(cls)
        for name in cls.__slots__:
            if name != "__weakref__":
                object.__setattr__(result, name, payload[name])
        _validate_bridge_context_receipt_payload(result)
        return result

    def to_dict(self) -> dict[str, Any]:
        _validate_bridge_context_receipt_payload(self)
        return _bridge_context_receipt_payload(self, include_hash=True)


def _bridge_context_receipt_payload(
    receipt: BridgeContextReceipt,
    *,
    include_hash: bool,
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "bridge_kind": object.__getattribute__(receipt, "bridge_kind"),
        "evidence_kind": object.__getattribute__(receipt, "evidence_kind"),
        "outcome": object.__getattribute__(receipt, "outcome"),
        "semantic_obligation_sha256": object.__getattribute__(
            receipt, "semantic_obligation_sha256"
        ),
        "seed_evidence_id": object.__getattribute__(
            receipt, "seed_evidence_id"
        ),
        "seed_stable_anchor": object.__getattribute__(
            receipt, "seed_stable_anchor"
        ).to_dict(),
        "linked_evidence_ids": list(
            object.__getattribute__(receipt, "linked_evidence_ids")
        ),
        "ordered_stable_anchors": [
            anchor.to_dict()
            for anchor in object.__getattribute__(
                receipt, "ordered_stable_anchors"
            )
        ],
        "evidence_store_sha256": object.__getattribute__(
            receipt, "evidence_store_sha256"
        ),
        "execution_config_sha256": object.__getattribute__(
            receipt, "execution_config_sha256"
        ),
        "runtime_binding_sha256": object.__getattribute__(
            receipt, "runtime_binding_sha256"
        ),
    }
    if include_hash:
        payload["receipt_sha256"] = object.__getattribute__(
            receipt, "receipt_sha256"
        )
    return payload


def _validate_bridge_context_receipt_payload(
    receipt: BridgeContextReceipt,
) -> None:
    if type(receipt) is not BridgeContextReceipt:
        raise TypeError("bridge_context_receipt_required")
    bridge_kind = object.__getattribute__(receipt, "bridge_kind")
    evidence_kind = object.__getattribute__(receipt, "evidence_kind")
    expected_evidence_kind = dict(_CONTEXT_BRIDGE_KIND_PAIRS).get(bridge_kind)
    if expected_evidence_kind is None or evidence_kind != expected_evidence_kind:
        raise ValueError("bridge_context_kind_mismatch")
    outcome = object.__getattribute__(receipt, "outcome")
    if outcome not in {"applied", "empty"}:
        raise ValueError("bridge_context_outcome_mismatch")
    seed_evidence_id = object.__getattribute__(receipt, "seed_evidence_id")
    if type(seed_evidence_id) is not str or not seed_evidence_id:
        raise ValueError("invalid_bridge_context_seed_evidence_id")
    for name in (
        "semantic_obligation_sha256",
        "evidence_store_sha256",
        "execution_config_sha256",
        "runtime_binding_sha256",
        "receipt_sha256",
    ):
        _require_hash(object.__getattribute__(receipt, name), f"invalid_{name}")
    seed_anchor = object.__getattribute__(receipt, "seed_stable_anchor")
    linked_ids = _exact_string_tuple_value(
        object.__getattribute__(receipt, "linked_evidence_ids"),
        "bridge_context_linked_evidence_ids",
        allow_empty=True,
    )
    anchors = object.__getattribute__(receipt, "ordered_stable_anchors")
    if (
        type(seed_anchor) is not StableEvidenceAnchor
        or type(anchors) is not tuple
        or len(anchors) != len(linked_ids)
        or any(
            type(anchor) is not StableEvidenceAnchor
            or object.__getattribute__(anchor, "evidence_kind") != evidence_kind
            or object.__getattribute__(anchor, "doc_id")
            != object.__getattribute__(seed_anchor, "doc_id")
            for anchor in anchors
        )
    ):
        raise ValueError("bridge_context_anchor_mismatch")
    if (outcome == "applied") is not bool(linked_ids):
        raise ValueError("bridge_context_outcome_mismatch")
    expected = _canonical_sha256(
        _bridge_context_receipt_payload(receipt, include_hash=False)
    )
    if object.__getattribute__(receipt, "receipt_sha256") != expected:
        raise ValueError("bridge_context_receipt_hash_mismatch")


@dataclass(frozen=True, slots=True)
class _ParentContextReceiptAuthority:
    weak: ReferenceType[ParentContextReceipt]
    root_source_weak: ReferenceType[object]
    semantic_issuance_key: tuple[object, ...]
    seed: Evidence
    seed_anchor: StableEvidenceAnchor
    parent: ProvenanceParent
    store: EvidenceStore
    config: HarnessExecutionConfig
    runtime: HarnessRuntimeBinding
    execution_key: tuple[object, ...]
    issued_payload_sha256: str


@dataclass(frozen=True, slots=True)
class _BridgeContextReceiptAuthority:
    weak: ReferenceType[BridgeContextReceipt]
    root_source_weak: ReferenceType[object]
    semantic_issuance_key: tuple[object, ...]
    seed: Evidence
    seed_anchor: StableEvidenceAnchor
    bridge_kind: str
    evidence_kind: str
    linked_evidence: tuple[Evidence, ...]
    linked_anchors: tuple[StableEvidenceAnchor, ...]
    store: EvidenceStore
    config: HarnessExecutionConfig
    runtime: HarnessRuntimeBinding
    execution_key: tuple[object, ...]
    issued_payload_sha256: str


_PARENT_CONTEXT_RECEIPT_AUTHORITIES: dict[
    int, _ParentContextReceiptAuthority
] = {}
_ISSUED_PARENT_CONTEXT_RECEIPT_AUTHORITIES = (
    _PARENT_CONTEXT_RECEIPT_AUTHORITIES
)
_BRIDGE_CONTEXT_RECEIPT_AUTHORITIES: dict[
    int, _BridgeContextReceiptAuthority
] = {}
_ISSUED_BRIDGE_CONTEXT_RECEIPT_AUTHORITIES = (
    _BRIDGE_CONTEXT_RECEIPT_AUTHORITIES
)


def _build_context_receipt_accessors(
    visible: dict[int, object],
    authority_type: type,
    error_prefix: str,
) -> tuple[FunctionType, FunctionType, FunctionType]:
    shadow: dict[int, tuple[object, ...]] = {}
    authority_lock = Lock()

    def snapshot(authority: object) -> tuple[object, ...]:
        return tuple(
            object.__getattribute__(authority, name)
            for name in type.__getattribute__(authority_type, "__slots__")
        )

    def register(receipt: object, authority: object) -> None:
        if type(authority) is not authority_type:
            raise TypeError(f"{error_prefix}_authority_required")
        with authority_lock:
            identity = id(receipt)
            if dict.get(visible, identity) is not None or dict.get(shadow, identity) is not None:
                raise ValueError(f"{error_prefix}_authority_drift")
            dict.__setitem__(visible, identity, authority)
            dict.__setitem__(shadow, identity, snapshot(authority))

    def read(receipt: object) -> object:
        with authority_lock:
            identity = id(receipt)
            current = dict.get(visible, identity)
            sealed = dict.get(shadow, identity)
            slots = type.__getattribute__(authority_type, "__slots__")
            if (
                type(current) is not authority_type
                or type(sealed) is not tuple
                or object.__getattribute__(current, "weak")() is not receipt
                or len(sealed) != len(slots)
                or any(
                    object.__getattribute__(current, name) is not value
                    for name, value in zip(slots, sealed)
                )
            ):
                raise ValueError(f"{error_prefix}_authority_required")
            return current

    def drop(identity: int, dead: ReferenceType[object]) -> None:
        with authority_lock:
            sealed = dict.get(shadow, identity)
            if type(sealed) is tuple and sealed and tuple.__getitem__(sealed, 0) is dead:
                dict.pop(visible, identity, None)
                dict.pop(shadow, identity, None)

    return register, read, drop


(
    _register_parent_context_receipt_authority,
    _read_parent_context_receipt_authority,
    _drop_parent_context_receipt_authority,
) = _build_context_receipt_accessors(
    _ISSUED_PARENT_CONTEXT_RECEIPT_AUTHORITIES,
    _ParentContextReceiptAuthority,
    "parent_context_receipt",
)
(
    _register_bridge_context_receipt_authority,
    _read_bridge_context_receipt_authority,
    _drop_bridge_context_receipt_authority,
) = _build_context_receipt_accessors(
    _ISSUED_BRIDGE_CONTEXT_RECEIPT_AUTHORITIES,
    _BridgeContextReceiptAuthority,
    "bridge_context_receipt",
)


def _build_context_issuance_accessors() -> tuple[
    FunctionType,
    FunctionType,
    FunctionType,
    FunctionType,
    FunctionType,
]:
    history: dict[tuple[object, ...], object] = {}
    history_shadow: dict[tuple[object, ...], object] = {}
    cache: dict[tuple[object, ...], tuple[object, ...]] = {}
    cache_shadow: dict[tuple[object, ...], tuple[object, ...]] = {}
    source_refs: dict[int, ReferenceType[object]] = {}
    source_keys: dict[int, set[tuple[object, ...]]] = {}
    issuance_lock = Lock()

    def drop_source(
        identity: int,
        dead: ReferenceType[object],
    ) -> None:
        with issuance_lock:
            if dict.get(source_refs, identity) is not dead:
                return
            keys = dict.pop(source_keys, identity, set())
            for key in tuple(keys):
                dict.pop(history, key, None)
                dict.pop(history_shadow, key, None)
                dict.pop(cache, key, None)
                dict.pop(cache_shadow, key, None)
            dict.pop(source_refs, identity, None)

    def begin(
        source: object,
        execution_key: tuple[object, ...],
        receipt_type: type,
    ) -> tuple[object, ...] | None:
        with issuance_lock:
            source_identity = id(source)
            source_weak = dict.get(source_refs, source_identity)
            if source_weak is None:
                source_weak = ref(
                    source,
                    lambda dead, source_identity=source_identity: drop_source(
                        source_identity, dead
                    ),
                )
                dict.__setitem__(source_refs, source_identity, source_weak)
                dict.__setitem__(source_keys, source_identity, set())
            elif source_weak() is not source:
                raise ValueError("context_receipt_source_history_drift")
            current = dict.get(history, execution_key)
            mirror = dict.get(history_shadow, execution_key)
            if current is not mirror:
                raise ValueError("context_receipt_issuance_history_drift")
            if current is None:
                dict.__setitem__(history, execution_key, _CONTEXT_PENDING)
                dict.__setitem__(history_shadow, execution_key, _CONTEXT_PENDING)
                dict.__getitem__(source_keys, source_identity).add(execution_key)
                return None
            if current is not _CONTEXT_COMPLETED:
                raise ValueError("context_receipt_issuance_already_consumed")
            cached = dict.get(cache, execution_key)
            cached_mirror = dict.get(cache_shadow, execution_key)
            if cached is not cached_mirror or type(cached) is not tuple:
                raise ValueError("context_receipt_issuance_history_drift")
            if any(type(item) is not receipt_type for item in cached):
                raise ValueError("context_receipt_issuance_already_consumed")
            return cached

    def complete(
        execution_key: tuple[object, ...],
        receipts: tuple[object, ...],
    ) -> None:
        with issuance_lock:
            if (
                dict.get(history, execution_key) is not _CONTEXT_PENDING
                or dict.get(history_shadow, execution_key) is not _CONTEXT_PENDING
            ):
                raise ValueError("context_receipt_issuance_history_drift")
            dict.__setitem__(cache, execution_key, receipts)
            dict.__setitem__(cache_shadow, execution_key, receipts)
            dict.__setitem__(history, execution_key, _CONTEXT_COMPLETED)
            dict.__setitem__(history_shadow, execution_key, _CONTEXT_COMPLETED)

    def fail(execution_key: tuple[object, ...]) -> None:
        with issuance_lock:
            if (
                dict.get(history, execution_key) is not _CONTEXT_PENDING
                or dict.get(history_shadow, execution_key) is not _CONTEXT_PENDING
            ):
                raise ValueError("context_receipt_issuance_history_drift")
            dict.__setitem__(history, execution_key, _CONTEXT_FAILED)
            dict.__setitem__(history_shadow, execution_key, _CONTEXT_FAILED)

    def status(execution_key: tuple[object, ...]) -> object | None:
        with issuance_lock:
            current = dict.get(history, execution_key)
            mirror = dict.get(history_shadow, execution_key)
            if current is not mirror:
                raise ValueError("context_receipt_issuance_history_drift")
            return current

    return begin, complete, fail, status, drop_source


(
    _begin_context_receipt_issuance,
    _complete_context_receipt_issuance,
    _fail_context_receipt_issuance,
    _context_receipt_issuance_status,
    _drop_context_receipt_source_history,
) = _build_context_issuance_accessors()


def _context_seed_evidence_ids(
    obligation: SemanticVerificationObligation,
    semantic_authority: _SemanticVerificationObligationAuthority,
    config: HarnessExecutionConfig,
) -> tuple[str, ...]:
    if object.__getattribute__(obligation, "derivation_kind") != "base":
        raise ValueError("semantic_context_requires_base_obligation")
    candidates = object.__getattribute__(obligation, "candidate_evidence_ids")
    _, _, rerank_k, final_evidence_budget = _semantic_owner_plan_budget(
        semantic_authority
    )
    limit = min(
        object.__getattribute__(config, "max_context_targets_per_obligation"),
        final_evidence_budget,
        rerank_k,
        len(candidates),
    )
    return tuple(sorted(candidates)[:limit])


def _context_issuance_key(
    family: str,
    semantic_authority: _SemanticVerificationObligationAuthority,
    obligation: SemanticVerificationObligation,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
) -> tuple[object, ...]:
    return (
        "semantic-context-v1",
        family,
        object.__getattribute__(semantic_authority, "issuance_key"),
        object.__getattribute__(obligation, "obligation_sha256"),
        id(store),
        id(config),
        id(runtime),
    )


def _parent_locator_sha256(parent: ProvenanceParent) -> str:
    locator = object.__getattribute__(parent, "locator")
    return _canonical_sha256(locator.to_dict())


def _mint_parent_context_receipt(
    *,
    obligation: SemanticVerificationObligation,
    semantic_authority: _SemanticVerificationObligationAuthority,
    seed: Evidence,
    parent: ProvenanceParent,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    execution_key: tuple[object, ...],
) -> ParentContextReceipt:
    seed_anchor = _stable_anchor(seed)
    payload = {
        "outcome": "applied",
        "semantic_obligation_sha256": object.__getattribute__(
            obligation, "obligation_sha256"
        ),
        "seed_evidence_id": object.__getattribute__(seed, "evidence_id"),
        "seed_stable_anchor": seed_anchor,
        "parent_id": object.__getattribute__(parent, "parent_id"),
        "parent_kind": object.__getattribute__(parent, "kind"),
        "parent_doc_id": object.__getattribute__(parent, "doc_id"),
        "parent_content_sha256": object.__getattribute__(
            parent, "content_sha256"
        ),
        "parent_locator_sha256": _parent_locator_sha256(parent),
        "evidence_store_sha256": object.__getattribute__(
            store, "bundle_sha256"
        ),
        "execution_config_sha256": object.__getattribute__(
            config, "config_sha256"
        ),
        "runtime_binding_sha256": object.__getattribute__(
            runtime, "binding_sha256"
        ),
    }
    temporary = object.__new__(ParentContextReceipt)
    for name, value in payload.items():
        object.__setattr__(temporary, name, value)
    object.__setattr__(temporary, "receipt_sha256", "0" * 64)
    payload["receipt_sha256"] = _canonical_sha256(
        _parent_context_receipt_payload(temporary, include_hash=False)
    )
    receipt = ParentContextReceipt._create(
        payload=payload, _token=_PARENT_CONTEXT_RECEIPT_TOKEN
    )
    identity = id(receipt)
    weak = ref(
        receipt,
        lambda dead, identity=identity: _drop_parent_context_receipt_authority(
            identity, dead
        ),
    )
    _register_parent_context_receipt_authority(
        receipt,
        _ParentContextReceiptAuthority(
            weak=weak,
            root_source_weak=ref(
                object.__getattribute__(semantic_authority, "source")
            ),
            semantic_issuance_key=object.__getattribute__(
                semantic_authority, "issuance_key"
            ),
            seed=seed,
            seed_anchor=seed_anchor,
            parent=parent,
            store=store,
            config=config,
            runtime=runtime,
            execution_key=execution_key,
            issued_payload_sha256=_canonical_sha256(receipt.to_dict()),
        ),
    )
    return receipt


def _mint_bridge_context_receipt(
    *,
    obligation: SemanticVerificationObligation,
    semantic_authority: _SemanticVerificationObligationAuthority,
    seed: Evidence,
    bridge_kind: str,
    evidence_kind: str,
    linked_evidence: tuple[Evidence, ...],
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    execution_key: tuple[object, ...],
) -> BridgeContextReceipt:
    seed_anchor = _stable_anchor(seed)
    linked_anchors = tuple(_stable_anchor(item) for item in linked_evidence)
    linked_ids = tuple(
        object.__getattribute__(item, "evidence_id") for item in linked_evidence
    )
    payload = {
        "bridge_kind": bridge_kind,
        "evidence_kind": evidence_kind,
        "outcome": "applied" if linked_ids else "empty",
        "semantic_obligation_sha256": object.__getattribute__(
            obligation, "obligation_sha256"
        ),
        "seed_evidence_id": object.__getattribute__(seed, "evidence_id"),
        "seed_stable_anchor": seed_anchor,
        "linked_evidence_ids": linked_ids,
        "ordered_stable_anchors": linked_anchors,
        "evidence_store_sha256": object.__getattribute__(
            store, "bundle_sha256"
        ),
        "execution_config_sha256": object.__getattribute__(
            config, "config_sha256"
        ),
        "runtime_binding_sha256": object.__getattribute__(
            runtime, "binding_sha256"
        ),
    }
    temporary = object.__new__(BridgeContextReceipt)
    for name, value in payload.items():
        object.__setattr__(temporary, name, value)
    object.__setattr__(temporary, "receipt_sha256", "0" * 64)
    payload["receipt_sha256"] = _canonical_sha256(
        _bridge_context_receipt_payload(temporary, include_hash=False)
    )
    receipt = BridgeContextReceipt._create(
        payload=payload, _token=_BRIDGE_CONTEXT_RECEIPT_TOKEN
    )
    identity = id(receipt)
    weak = ref(
        receipt,
        lambda dead, identity=identity: _drop_bridge_context_receipt_authority(
            identity, dead
        ),
    )
    _register_bridge_context_receipt_authority(
        receipt,
        _BridgeContextReceiptAuthority(
            weak=weak,
            root_source_weak=ref(
                object.__getattribute__(semantic_authority, "source")
            ),
            semantic_issuance_key=object.__getattribute__(
                semantic_authority, "issuance_key"
            ),
            seed=seed,
            seed_anchor=seed_anchor,
            bridge_kind=bridge_kind,
            evidence_kind=evidence_kind,
            linked_evidence=linked_evidence,
            linked_anchors=linked_anchors,
            store=store,
            config=config,
            runtime=runtime,
            execution_key=execution_key,
            issued_payload_sha256=_canonical_sha256(receipt.to_dict()),
        ),
    )
    return receipt


def _validate_parent_context_receipt_exact(
    *,
    receipt: ParentContextReceipt,
    obligation: SemanticVerificationObligation,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
) -> _ParentContextReceiptAuthority:
    semantic_authority = _validate_semantic_verification_obligation_exact(
        obligation=obligation, store=store, config=config, runtime=runtime
    )
    _validate_parent_context_receipt_payload(receipt)
    authority = _read_parent_context_receipt_authority(receipt)
    execution_key = _context_issuance_key(
        "parent", semantic_authority, obligation, store, config, runtime
    )
    root_source = object.__getattribute__(semantic_authority, "source")
    if (
        object.__getattribute__(authority, "root_source_weak")() is not root_source
        or object.__getattribute__(authority, "semantic_issuance_key")
        != object.__getattribute__(semantic_authority, "issuance_key")
        or object.__getattribute__(authority, "store") is not store
        or object.__getattribute__(authority, "config") is not config
        or object.__getattribute__(authority, "runtime") is not runtime
        or object.__getattribute__(authority, "execution_key") != execution_key
        or _context_receipt_issuance_status(execution_key)
        is not _CONTEXT_COMPLETED
    ):
        raise ValueError("parent_context_receipt_dependency_identity_mismatch")
    if object.__getattribute__(authority, "issued_payload_sha256") != _canonical_sha256(
        receipt.to_dict()
    ):
        raise ValueError("parent_context_receipt_authority_drift")
    seed = object.__getattribute__(authority, "seed")
    parent = object.__getattribute__(authority, "parent")
    seed_id = object.__getattribute__(receipt, "seed_evidence_id")
    if (
        seed_id
        not in _context_seed_evidence_ids(
            obligation, semantic_authority, config
        )
        or EvidenceStore.get(store, seed_id) is not seed
        or EvidenceStore.parent(store, object.__getattribute__(seed, "parent_id"))
        is not parent
        or object.__getattribute__(receipt, "seed_stable_anchor")
        is not object.__getattribute__(authority, "seed_anchor")
        or object.__getattribute__(receipt, "semantic_obligation_sha256")
        != object.__getattribute__(obligation, "obligation_sha256")
        or object.__getattribute__(receipt, "parent_id")
        != object.__getattribute__(parent, "parent_id")
        or object.__getattribute__(receipt, "parent_kind")
        != object.__getattribute__(parent, "kind")
        or object.__getattribute__(receipt, "parent_doc_id")
        != object.__getattribute__(parent, "doc_id")
        or object.__getattribute__(receipt, "parent_content_sha256")
        != object.__getattribute__(parent, "content_sha256")
        or object.__getattribute__(receipt, "parent_locator_sha256")
        != _parent_locator_sha256(parent)
        or object.__getattribute__(receipt, "evidence_store_sha256")
        != object.__getattribute__(store, "bundle_sha256")
        or object.__getattribute__(receipt, "execution_config_sha256")
        != object.__getattribute__(config, "config_sha256")
        or object.__getattribute__(receipt, "runtime_binding_sha256")
        != object.__getattribute__(runtime, "binding_sha256")
    ):
        raise ValueError("parent_context_receipt_projection_mismatch")
    return authority


def _validate_bridge_context_receipt_exact(
    *,
    receipt: BridgeContextReceipt,
    obligation: SemanticVerificationObligation,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
) -> _BridgeContextReceiptAuthority:
    semantic_authority = _validate_semantic_verification_obligation_exact(
        obligation=obligation, store=store, config=config, runtime=runtime
    )
    _validate_bridge_context_receipt_payload(receipt)
    authority = _read_bridge_context_receipt_authority(receipt)
    execution_key = _context_issuance_key(
        "bridge", semantic_authority, obligation, store, config, runtime
    )
    root_source = object.__getattribute__(semantic_authority, "source")
    if (
        object.__getattribute__(authority, "root_source_weak")() is not root_source
        or object.__getattribute__(authority, "semantic_issuance_key")
        != object.__getattribute__(semantic_authority, "issuance_key")
        or object.__getattribute__(authority, "store") is not store
        or object.__getattribute__(authority, "config") is not config
        or object.__getattribute__(authority, "runtime") is not runtime
        or object.__getattribute__(authority, "execution_key") != execution_key
        or _context_receipt_issuance_status(execution_key)
        is not _CONTEXT_COMPLETED
    ):
        raise ValueError("bridge_context_receipt_dependency_identity_mismatch")
    if object.__getattribute__(authority, "issued_payload_sha256") != _canonical_sha256(
        receipt.to_dict()
    ):
        raise ValueError("bridge_context_receipt_authority_drift")
    seed = object.__getattribute__(authority, "seed")
    seed_id = object.__getattribute__(receipt, "seed_evidence_id")
    evidence_kind = object.__getattribute__(authority, "evidence_kind")
    linked = EvidenceStore.bridge(store, seed_id, kinds=(evidence_kind,))
    issued_linked = object.__getattribute__(authority, "linked_evidence")
    if (
        seed_id
        not in _context_seed_evidence_ids(
            obligation, semantic_authority, config
        )
        or EvidenceStore.get(store, seed_id) is not seed
        or object.__getattribute__(receipt, "seed_stable_anchor")
        is not object.__getattribute__(authority, "seed_anchor")
        or object.__getattribute__(receipt, "bridge_kind")
        != object.__getattribute__(authority, "bridge_kind")
        or object.__getattribute__(receipt, "evidence_kind") != evidence_kind
        or type(linked) is not tuple
        or len(linked) != len(issued_linked)
        or any(current is not issued for current, issued in zip(linked, issued_linked))
        or object.__getattribute__(receipt, "linked_evidence_ids")
        != tuple(object.__getattribute__(item, "evidence_id") for item in linked)
        or object.__getattribute__(receipt, "ordered_stable_anchors")
        is not object.__getattribute__(authority, "linked_anchors")
        or object.__getattribute__(receipt, "semantic_obligation_sha256")
        != object.__getattribute__(obligation, "obligation_sha256")
        or object.__getattribute__(receipt, "evidence_store_sha256")
        != object.__getattribute__(store, "bundle_sha256")
        or object.__getattribute__(receipt, "execution_config_sha256")
        != object.__getattribute__(config, "config_sha256")
        or object.__getattribute__(receipt, "runtime_binding_sha256")
        != object.__getattribute__(runtime, "binding_sha256")
    ):
        raise ValueError("bridge_context_receipt_projection_mismatch")
    return authority


def issue_parent_context_receipts(
    *,
    obligation: SemanticVerificationObligation,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    _dependency_checker=None,
    _dependency_checker_code=None,
) -> tuple[ParentContextReceipt, ...]:
    _semantic_public_entry(_dependency_checker, _dependency_checker_code)
    semantic_authority = _validate_semantic_verification_obligation_exact(
        obligation=obligation, store=store, config=config, runtime=runtime
    )
    seed_ids = _context_seed_evidence_ids(
        obligation, semantic_authority, config
    )
    execution_key = _context_issuance_key(
        "parent", semantic_authority, obligation, store, config, runtime
    )
    cached = _begin_context_receipt_issuance(
        object.__getattribute__(semantic_authority, "source"),
        execution_key,
        ParentContextReceipt,
    )
    if cached is not None:
        for receipt in cached:
            _validate_parent_context_receipt_exact(
                receipt=receipt,
                obligation=obligation,
                store=store,
                config=config,
                runtime=runtime,
            )
        return cached
    try:
        receipts = tuple(
            _mint_parent_context_receipt(
                obligation=obligation,
                semantic_authority=semantic_authority,
                seed=EvidenceStore.get(store, seed_id),
                parent=EvidenceStore.parent(
                    store,
                    object.__getattribute__(
                        EvidenceStore.get(store, seed_id), "parent_id"
                    ),
                ),
                store=store,
                config=config,
                runtime=runtime,
                execution_key=execution_key,
            )
            for seed_id in seed_ids
        )
        _complete_context_receipt_issuance(execution_key, receipts)
        return receipts
    except Exception:
        _fail_context_receipt_issuance(execution_key)
        raise


def issue_bridge_context_receipts(
    *,
    obligation: SemanticVerificationObligation,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    _dependency_checker=None,
    _dependency_checker_code=None,
) -> tuple[BridgeContextReceipt, ...]:
    _semantic_public_entry(_dependency_checker, _dependency_checker_code)
    semantic_authority = _validate_semantic_verification_obligation_exact(
        obligation=obligation, store=store, config=config, runtime=runtime
    )
    seed_ids = _context_seed_evidence_ids(
        obligation, semantic_authority, config
    )
    execution_key = _context_issuance_key(
        "bridge", semantic_authority, obligation, store, config, runtime
    )
    cached = _begin_context_receipt_issuance(
        object.__getattribute__(semantic_authority, "source"),
        execution_key,
        BridgeContextReceipt,
    )
    if cached is not None:
        for receipt in cached:
            _validate_bridge_context_receipt_exact(
                receipt=receipt,
                obligation=obligation,
                store=store,
                config=config,
                runtime=runtime,
            )
        return cached
    try:
        receipts = tuple(
            _mint_bridge_context_receipt(
                obligation=obligation,
                semantic_authority=semantic_authority,
                seed=EvidenceStore.get(store, seed_id),
                bridge_kind=bridge_kind,
                evidence_kind=evidence_kind,
                linked_evidence=EvidenceStore.bridge(
                    store, seed_id, kinds=(evidence_kind,)
                ),
                store=store,
                config=config,
                runtime=runtime,
                execution_key=execution_key,
            )
            for bridge_kind, evidence_kind in _CONTEXT_BRIDGE_KIND_PAIRS
            for seed_id in seed_ids
        )
        _complete_context_receipt_issuance(execution_key, receipts)
        return receipts
    except Exception:
        _fail_context_receipt_issuance(execution_key)
        raise


def validate_parent_context_receipt(
    *,
    receipt: ParentContextReceipt,
    obligation: SemanticVerificationObligation,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    _dependency_checker=None,
    _dependency_checker_code=None,
) -> None:
    _semantic_public_entry(_dependency_checker, _dependency_checker_code)
    _validate_parent_context_receipt_exact(
        receipt=receipt,
        obligation=obligation,
        store=store,
        config=config,
        runtime=runtime,
    )


def validate_bridge_context_receipt(
    *,
    receipt: BridgeContextReceipt,
    obligation: SemanticVerificationObligation,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    _dependency_checker=None,
    _dependency_checker_code=None,
) -> None:
    _semantic_public_entry(_dependency_checker, _dependency_checker_code)
    _validate_bridge_context_receipt_exact(
        receipt=receipt,
        obligation=obligation,
        store=store,
        config=config,
        runtime=runtime,
    )


# EH2.6.c3.2 bounded rerank and derived semantic obligation -------------------

_RERANK_OUTCOMES = frozenset(
    {"applied", "skipped_unavailable", "provider_error", "contract_error"}
)
_RERANK_ERROR_CODES = frozenset(
    {
        "none",
        "reranker_unavailable",
        "reranker_provider_error",
        "reranker_contract_error",
    }
)
_RERANK_PENDING = object()
_RERANK_COMPLETED = object()
_RERANK_FAILED = object()


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class RerankReceipt:
    """Content-free owner-bound projection of one bounded rerank attempt."""

    stage: str
    outcome: str
    error_code: str
    call_performed: bool
    semantic_obligation_sha256: str
    prerequisite_sha256: str
    parent_context_receipt_sha256s: tuple[str, ...]
    bridge_context_receipt_sha256s: tuple[str, ...]
    owner_plan_sha256: str
    owner_plan_config_sha256: str
    query_sha256: str
    rerank_k: int
    final_evidence_budget: int
    input_evidence_ids: tuple[str, ...]
    input_evidence_roles: tuple[str, ...]
    input_count: int
    ordered_evidence_ids: tuple[str, ...]
    ordered_stable_anchors: tuple[StableEvidenceAnchor, ...]
    candidate_evidence_ids: tuple[str, ...]
    bridge_evidence_ids: tuple[str, ...]
    effective_output_count: int
    reranker_id: str
    reranker_implementation_sha256: str
    reranker_config_sha256: str
    evidence_store_sha256: str
    execution_config_sha256: str
    runtime_binding_sha256: str
    result_sha256: str
    receipt_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("rerank_receipt_factory_required")

    def __copy__(self) -> object:
        raise TypeError("rerank_receipt_not_serializable")

    def __deepcopy__(self, memo: object) -> object:
        raise TypeError("rerank_receipt_not_serializable")

    def __reduce__(self) -> object:
        raise TypeError("rerank_receipt_not_serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        raise TypeError("rerank_receipt_not_serializable")

    @classmethod
    def _create(
        cls,
        *,
        payload: Mapping[str, Any],
        _token: object,
    ) -> RerankReceipt:
        if _token is not _RERANK_RECEIPT_TOKEN:
            raise ValueError("rerank_receipt_factory_required")
        result = object.__new__(cls)
        for name in cls.__slots__:
            if name != "__weakref__":
                object.__setattr__(result, name, payload[name])
        _validate_rerank_receipt_payload(result)
        return result

    def to_dict(self) -> dict[str, Any]:
        _validate_rerank_receipt_payload(self)
        return _rerank_receipt_payload(self, include_hash=True)


def _rerank_receipt_payload(
    receipt: RerankReceipt,
    *,
    include_hash: bool,
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "stage": object.__getattribute__(receipt, "stage"),
        "outcome": object.__getattribute__(receipt, "outcome"),
        "error_code": object.__getattribute__(receipt, "error_code"),
        "call_performed": object.__getattribute__(receipt, "call_performed"),
        "semantic_obligation_sha256": object.__getattribute__(
            receipt, "semantic_obligation_sha256"
        ),
        "prerequisite_sha256": object.__getattribute__(
            receipt, "prerequisite_sha256"
        ),
        "parent_context_receipt_sha256s": list(
            object.__getattribute__(
                receipt, "parent_context_receipt_sha256s"
            )
        ),
        "bridge_context_receipt_sha256s": list(
            object.__getattribute__(
                receipt, "bridge_context_receipt_sha256s"
            )
        ),
        "owner_plan_sha256": object.__getattribute__(
            receipt, "owner_plan_sha256"
        ),
        "owner_plan_config_sha256": object.__getattribute__(
            receipt, "owner_plan_config_sha256"
        ),
        "query_sha256": object.__getattribute__(receipt, "query_sha256"),
        "rerank_k": object.__getattribute__(receipt, "rerank_k"),
        "final_evidence_budget": object.__getattribute__(
            receipt, "final_evidence_budget"
        ),
        "input_evidence_ids": list(
            object.__getattribute__(receipt, "input_evidence_ids")
        ),
        "input_evidence_roles": list(
            object.__getattribute__(receipt, "input_evidence_roles")
        ),
        "input_count": object.__getattribute__(receipt, "input_count"),
        "ordered_evidence_ids": list(
            object.__getattribute__(receipt, "ordered_evidence_ids")
        ),
        "ordered_stable_anchors": [
            anchor.to_dict()
            for anchor in object.__getattribute__(
                receipt, "ordered_stable_anchors"
            )
        ],
        "candidate_evidence_ids": list(
            object.__getattribute__(receipt, "candidate_evidence_ids")
        ),
        "bridge_evidence_ids": list(
            object.__getattribute__(receipt, "bridge_evidence_ids")
        ),
        "effective_output_count": object.__getattribute__(
            receipt, "effective_output_count"
        ),
        "reranker_id": object.__getattribute__(receipt, "reranker_id"),
        "reranker_implementation_sha256": object.__getattribute__(
            receipt, "reranker_implementation_sha256"
        ),
        "reranker_config_sha256": object.__getattribute__(
            receipt, "reranker_config_sha256"
        ),
        "evidence_store_sha256": object.__getattribute__(
            receipt, "evidence_store_sha256"
        ),
        "execution_config_sha256": object.__getattribute__(
            receipt, "execution_config_sha256"
        ),
        "runtime_binding_sha256": object.__getattribute__(
            receipt, "runtime_binding_sha256"
        ),
        "result_sha256": object.__getattribute__(receipt, "result_sha256"),
    }
    if include_hash:
        payload["receipt_sha256"] = object.__getattribute__(
            receipt, "receipt_sha256"
        )
    return payload


def _validate_rerank_receipt_payload(receipt: RerankReceipt) -> None:
    if type(receipt) is not RerankReceipt:
        raise TypeError("rerank_receipt_required")
    outcome = object.__getattribute__(receipt, "outcome")
    error_code = object.__getattribute__(receipt, "error_code")
    call_performed = object.__getattribute__(receipt, "call_performed")
    if (
        object.__getattribute__(receipt, "stage") != "semantic_rerank"
        or outcome not in _RERANK_OUTCOMES
        or error_code not in _RERANK_ERROR_CODES
        or type(call_performed) is not bool
    ):
        raise ValueError("invalid_rerank_receipt_outcome")
    expected_error = {
        "applied": "none",
        "skipped_unavailable": "reranker_unavailable",
        "provider_error": "reranker_provider_error",
        "contract_error": "reranker_contract_error",
    }[outcome]
    if error_code != expected_error or call_performed is (
        outcome == "skipped_unavailable"
    ):
        raise ValueError("invalid_rerank_receipt_outcome")
    for name in (
        "semantic_obligation_sha256",
        "prerequisite_sha256",
        "owner_plan_sha256",
        "owner_plan_config_sha256",
        "query_sha256",
        "reranker_implementation_sha256",
        "reranker_config_sha256",
        "evidence_store_sha256",
        "execution_config_sha256",
        "runtime_binding_sha256",
        "result_sha256",
        "receipt_sha256",
    ):
        _require_hash(object.__getattribute__(receipt, name), f"invalid_{name}")
    for name in (
        "parent_context_receipt_sha256s",
        "bridge_context_receipt_sha256s",
    ):
        values = _exact_string_tuple_value(
            object.__getattribute__(receipt, name),
            f"rerank_{name}",
            allow_empty=True,
        )
        for value in values:
            _require_hash(value, f"invalid_rerank_{name}")
    rerank_k = object.__getattribute__(receipt, "rerank_k")
    final_budget = object.__getattribute__(receipt, "final_evidence_budget")
    input_count = object.__getattribute__(receipt, "input_count")
    effective_count = object.__getattribute__(receipt, "effective_output_count")
    if (
        type(rerank_k) is not int
        or rerank_k < 1
        or type(final_budget) is not int
        or final_budget < 1
        or final_budget > rerank_k
        or type(input_count) is not int
        or input_count < 1
        or type(effective_count) is not int
        or effective_count < 0
        or effective_count > min(rerank_k, input_count)
    ):
        raise ValueError("invalid_rerank_receipt_budget")
    inputs = _exact_string_tuple_value(
        object.__getattribute__(receipt, "input_evidence_ids"),
        "rerank_input_evidence_ids",
        allow_empty=False,
    )
    roles = object.__getattribute__(receipt, "input_evidence_roles")
    ordered = _exact_string_tuple_value(
        object.__getattribute__(receipt, "ordered_evidence_ids"),
        "rerank_ordered_evidence_ids",
        allow_empty=outcome in {"provider_error", "contract_error"},
    )
    candidates = _exact_string_tuple_value(
        object.__getattribute__(receipt, "candidate_evidence_ids"),
        "rerank_candidate_evidence_ids",
        allow_empty=True,
    )
    bridges = _exact_string_tuple_value(
        object.__getattribute__(receipt, "bridge_evidence_ids"),
        "rerank_bridge_evidence_ids",
        allow_empty=True,
    )
    anchors = object.__getattribute__(receipt, "ordered_stable_anchors")
    role_by_id = dict(zip(inputs, roles)) if type(roles) is tuple else {}
    expected_candidates = tuple(
        item for item in ordered if role_by_id.get(item) == "candidate"
    )
    expected_bridges = tuple(
        item for item in ordered if role_by_id.get(item) == "bridge"
    )
    if (
        len(inputs) != input_count
        or type(roles) is not tuple
        or len(roles) != input_count
        or any(role not in {"candidate", "bridge"} for role in roles)
        or len(ordered) != effective_count
        or not set(ordered).issubset(inputs)
        or set(candidates).intersection(bridges)
        or set(candidates).union(bridges) != set(ordered)
        or candidates != expected_candidates
        or bridges != expected_bridges
        or type(anchors) is not tuple
        or len(anchors) != effective_count
        or any(type(anchor) is not StableEvidenceAnchor for anchor in anchors)
    ):
        raise ValueError("rerank_receipt_projection_mismatch")
    if outcome in {"provider_error", "contract_error"} and (
        ordered or candidates or bridges or anchors or effective_count
    ):
        raise ValueError("rerank_failure_projection_mismatch")
    if outcome == "skipped_unavailable" and ordered != inputs[: min(rerank_k, input_count)]:
        raise ValueError("rerank_unavailable_identity_projection_mismatch")
    reranker_id = object.__getattribute__(receipt, "reranker_id")
    if (outcome == "skipped_unavailable") is not (reranker_id == "none"):
        raise ValueError("rerank_receipt_capability_mismatch")
    expected = _canonical_sha256(
        _rerank_receipt_payload(receipt, include_hash=False)
    )
    if object.__getattribute__(receipt, "receipt_sha256") != expected:
        raise ValueError("rerank_receipt_hash_mismatch")


@dataclass(frozen=True, slots=True, repr=False, init=False)
class _RerankerEvidence:
    index: int
    role: str
    doc_id: str
    content_kind: str
    content: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("reranker_request_factory_required")

    def __copy__(self) -> object:
        raise TypeError("reranker_request_not_serializable")

    def __deepcopy__(self, memo: object) -> object:
        raise TypeError("reranker_request_not_serializable")

    def __reduce__(self) -> object:
        raise TypeError("reranker_request_not_serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        raise TypeError("reranker_request_not_serializable")

    @classmethod
    def _create(
        cls,
        *,
        index: int,
        role: str,
        doc_id: str,
        content_kind: str,
        content: str,
        _token: object,
    ) -> _RerankerEvidence:
        if _token is not _RERANK_REQUEST_TOKEN:
            raise ValueError("reranker_request_factory_required")
        if (
            type(index) is not int
            or index < 0
            or role not in {"candidate", "bridge"}
            or type(doc_id) is not str
            or not doc_id
            or type(content_kind) is not str
            or not content_kind
            or type(content) is not str
        ):
            raise ValueError("reranker_request_evidence_mismatch")
        result = object.__new__(cls)
        for name, value in (
            ("index", index),
            ("role", role),
            ("doc_id", doc_id),
            ("content_kind", content_kind),
            ("content", content),
        ):
            object.__setattr__(result, name, value)
        return result


@dataclass(frozen=True, slots=True, repr=False, init=False)
class _RerankerRequest:
    query: str
    evidence: tuple[_RerankerEvidence, ...]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("reranker_request_factory_required")

    def __copy__(self) -> object:
        raise TypeError("reranker_request_not_serializable")

    def __deepcopy__(self, memo: object) -> object:
        raise TypeError("reranker_request_not_serializable")

    def __reduce__(self) -> object:
        raise TypeError("reranker_request_not_serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        raise TypeError("reranker_request_not_serializable")

    @classmethod
    def _create(
        cls,
        *,
        query: str,
        evidence: tuple[_RerankerEvidence, ...],
        _token: object,
    ) -> _RerankerRequest:
        if _token is not _RERANK_REQUEST_TOKEN:
            raise ValueError("reranker_request_factory_required")
        if (
            type(query) is not str
            or not query
            or type(evidence) is not tuple
            or not evidence
            or any(
                type(item) is not _RerankerEvidence or item.index != index
                for index, item in enumerate(evidence)
            )
        ):
            raise ValueError("reranker_request_mismatch")
        result = object.__new__(cls)
        object.__setattr__(result, "query", query)
        object.__setattr__(result, "evidence", evidence)
        return result


@dataclass(frozen=True, slots=True)
class _RerankReceiptAuthority:
    weak: ReferenceType[RerankReceipt]
    root_source_weak: ReferenceType[object]
    semantic_issuance_key: tuple[object, ...]
    parent_receipts: tuple[ParentContextReceipt, ...]
    bridge_receipts: tuple[BridgeContextReceipt, ...]
    input_evidence: tuple[Evidence, ...]
    input_roles: tuple[str, ...]
    origin_seed_ids: tuple[str, ...]
    ordered_evidence: tuple[Evidence, ...]
    ordered_roles: tuple[str, ...]
    ordered_origin_seed_ids: tuple[str, ...]
    store: EvidenceStore
    config: HarnessExecutionConfig
    runtime: HarnessRuntimeBinding
    execution_key: tuple[object, ...]
    route_key: tuple[object, ...]
    projection: object | None
    issued_payload_sha256: str


_RERANK_RECEIPT_AUTHORITIES: dict[int, _RerankReceiptAuthority] = {}
_ISSUED_RERANK_RECEIPT_AUTHORITIES = _RERANK_RECEIPT_AUTHORITIES


def _build_rerank_receipt_accessors(
    visible: dict[int, _RerankReceiptAuthority],
) -> tuple[FunctionType, FunctionType, FunctionType]:
    shadow: dict[int, tuple[object, ...]] = {}
    authority_lock = Lock()

    def snapshot(authority: _RerankReceiptAuthority) -> tuple[object, ...]:
        return tuple(
            object.__getattribute__(authority, name)
            for name in _RerankReceiptAuthority.__slots__
        )

    def register(
        receipt: RerankReceipt,
        authority: _RerankReceiptAuthority,
    ) -> None:
        with authority_lock:
            identity = id(receipt)
            if dict.get(visible, identity) is not None or dict.get(
                shadow, identity
            ) is not None:
                raise ValueError("rerank_receipt_authority_drift")
            dict.__setitem__(visible, identity, authority)
            dict.__setitem__(shadow, identity, snapshot(authority))

    def read(receipt: RerankReceipt) -> _RerankReceiptAuthority:
        with authority_lock:
            identity = id(receipt)
            current = dict.get(visible, identity)
            sealed = dict.get(shadow, identity)
            if (
                type(current) is not _RerankReceiptAuthority
                or type(sealed) is not tuple
                or object.__getattribute__(current, "weak")() is not receipt
                or len(sealed) != len(_RerankReceiptAuthority.__slots__)
                or any(
                    object.__getattribute__(current, name) is not value
                    for name, value in zip(
                        _RerankReceiptAuthority.__slots__, sealed
                    )
                )
            ):
                raise ValueError("rerank_receipt_authority_required")
            return current

    def drop(identity: int, dead: ReferenceType[RerankReceipt]) -> None:
        with authority_lock:
            sealed = dict.get(shadow, identity)
            if (
                type(sealed) is tuple
                and sealed
                and tuple.__getitem__(sealed, 0) is dead
            ):
                dict.pop(visible, identity, None)
                dict.pop(shadow, identity, None)

    return register, read, drop


(
    _register_rerank_receipt_authority,
    _read_rerank_receipt_authority,
    _drop_rerank_receipt_authority,
) = _build_rerank_receipt_accessors(_ISSUED_RERANK_RECEIPT_AUTHORITIES)


def _build_semantic_route_accessors() -> tuple[
    FunctionType,
    FunctionType,
    FunctionType,
    FunctionType,
    FunctionType,
    FunctionType,
]:
    routes: dict[tuple[object, ...], str] = {}
    route_shadow: dict[tuple[object, ...], str] = {}
    history: dict[tuple[object, ...], object] = {}
    history_shadow: dict[tuple[object, ...], object] = {}
    cache: dict[tuple[object, ...], RerankReceipt] = {}
    cache_shadow: dict[tuple[object, ...], RerankReceipt] = {}
    source_refs: dict[int, ReferenceType[object]] = {}
    source_keys: dict[int, set[tuple[str, tuple[object, ...]]]] = {}
    route_lock = Lock()

    def drop_source(identity: int, dead: ReferenceType[object]) -> None:
        with route_lock:
            if dict.get(source_refs, identity) is not dead:
                return
            keys = dict.pop(source_keys, identity, set())
            for family, key in tuple(keys):
                if family == "route":
                    dict.pop(routes, key, None)
                    dict.pop(route_shadow, key, None)
                else:
                    dict.pop(history, key, None)
                    dict.pop(history_shadow, key, None)
                    dict.pop(cache, key, None)
                    dict.pop(cache_shadow, key, None)
            dict.pop(source_refs, identity, None)

    def register_source(
        source: object,
        family: str,
        key: tuple[object, ...],
    ) -> None:
        source_identity = id(source)
        source_weak = dict.get(source_refs, source_identity)
        if source_weak is None:
            source_weak = ref(
                source,
                lambda dead, source_identity=source_identity: drop_source(
                    source_identity, dead
                ),
            )
            dict.__setitem__(source_refs, source_identity, source_weak)
            dict.__setitem__(source_keys, source_identity, set())
        elif source_weak() is not source:
            raise ValueError("semantic_route_source_history_drift")
        dict.__getitem__(source_keys, source_identity).add((family, key))

    def claim_base(source: object, route_key: tuple[object, ...]) -> None:
        with route_lock:
            register_source(source, "route", route_key)
            current = dict.get(routes, route_key)
            mirror = dict.get(route_shadow, route_key)
            if current != mirror:
                raise ValueError("semantic_route_history_drift")
            if current is not None:
                raise ValueError("semantic_route_already_consumed")
            dict.__setitem__(routes, route_key, "base_pending")
            dict.__setitem__(route_shadow, route_key, "base_pending")

    def complete_base(route_key: tuple[object, ...]) -> None:
        with route_lock:
            if (
                dict.get(routes, route_key) != "base_pending"
                or dict.get(route_shadow, route_key) != "base_pending"
            ):
                raise ValueError("semantic_route_history_drift")
            dict.__setitem__(routes, route_key, "base_consumed")
            dict.__setitem__(route_shadow, route_key, "base_consumed")

    def begin_rerank(
        source: object,
        route_key: tuple[object, ...],
        execution_key: tuple[object, ...],
    ) -> RerankReceipt | None:
        with route_lock:
            register_source(source, "route", route_key)
            register_source(source, "rerank", execution_key)
            route = dict.get(routes, route_key)
            route_mirror = dict.get(route_shadow, route_key)
            current = dict.get(history, execution_key)
            mirror = dict.get(history_shadow, execution_key)
            if route != route_mirror or current is not mirror:
                raise ValueError("semantic_route_history_drift")
            if current is None:
                if route is not None:
                    raise ValueError("semantic_route_already_consumed")
                dict.__setitem__(routes, route_key, "rerank_pending")
                dict.__setitem__(route_shadow, route_key, "rerank_pending")
                dict.__setitem__(history, execution_key, _RERANK_PENDING)
                dict.__setitem__(history_shadow, execution_key, _RERANK_PENDING)
                return None
            if current is _RERANK_COMPLETED and route == "rerank_consumed":
                receipt = dict.get(cache, execution_key)
                if (
                    receipt is not dict.get(cache_shadow, execution_key)
                    or type(receipt) is not RerankReceipt
                ):
                    raise ValueError("semantic_rerank_history_drift")
            raise ValueError("semantic_rerank_already_consumed")

    def complete_rerank(
        route_key: tuple[object, ...],
        execution_key: tuple[object, ...],
        receipt: RerankReceipt,
    ) -> None:
        with route_lock:
            if (
                dict.get(routes, route_key) != "rerank_pending"
                or dict.get(route_shadow, route_key) != "rerank_pending"
                or dict.get(history, execution_key) is not _RERANK_PENDING
                or dict.get(history_shadow, execution_key) is not _RERANK_PENDING
            ):
                raise ValueError("semantic_rerank_history_drift")
            dict.__setitem__(cache, execution_key, receipt)
            dict.__setitem__(cache_shadow, execution_key, receipt)
            dict.__setitem__(history, execution_key, _RERANK_COMPLETED)
            dict.__setitem__(history_shadow, execution_key, _RERANK_COMPLETED)
            dict.__setitem__(routes, route_key, "rerank_consumed")
            dict.__setitem__(route_shadow, route_key, "rerank_consumed")

    def fail_rerank(
        route_key: tuple[object, ...],
        execution_key: tuple[object, ...],
    ) -> None:
        with route_lock:
            if (
                dict.get(routes, route_key) != "rerank_pending"
                or dict.get(route_shadow, route_key) != "rerank_pending"
                or dict.get(history, execution_key) is not _RERANK_PENDING
                or dict.get(history_shadow, execution_key) is not _RERANK_PENDING
            ):
                raise ValueError("semantic_rerank_history_drift")
            dict.__setitem__(history, execution_key, _RERANK_FAILED)
            dict.__setitem__(history_shadow, execution_key, _RERANK_FAILED)
            dict.__setitem__(routes, route_key, "rerank_consumed")
            dict.__setitem__(route_shadow, route_key, "rerank_consumed")

    def status(route_key: tuple[object, ...]) -> str | None:
        with route_lock:
            current = dict.get(routes, route_key)
            mirror = dict.get(route_shadow, route_key)
            if current != mirror:
                raise ValueError("semantic_route_history_drift")
            return current

    return claim_base, complete_base, begin_rerank, complete_rerank, fail_rerank, status


(
    _claim_base_semantic_route,
    _complete_base_semantic_route,
    _begin_semantic_rerank,
    _complete_semantic_rerank,
    _fail_semantic_rerank,
    _semantic_route_status,
) = _build_semantic_route_accessors()


def _validate_complete_context_receipts(
    *,
    obligation: SemanticVerificationObligation,
    semantic_authority: _SemanticVerificationObligationAuthority,
    parent_receipts: tuple[ParentContextReceipt, ...],
    bridge_receipts: tuple[BridgeContextReceipt, ...],
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
) -> tuple[
    tuple[_ParentContextReceiptAuthority, ...],
    tuple[_BridgeContextReceiptAuthority, ...],
]:
    if object.__getattribute__(obligation, "derivation_kind") != "base":
        raise ValueError("semantic_rerank_requires_base_obligation")
    if type(parent_receipts) is not tuple or type(bridge_receipts) is not tuple:
        raise TypeError("semantic_rerank_context_receipt_tuple_required")
    expected_batches = []
    for family, receipts, receipt_type in (
        ("parent", parent_receipts, ParentContextReceipt),
        ("bridge", bridge_receipts, BridgeContextReceipt),
    ):
        execution_key = _context_issuance_key(
            family,
            semantic_authority,
            obligation,
            store,
            config,
            runtime,
        )
        if _context_receipt_issuance_status(execution_key) is not _CONTEXT_COMPLETED:
            raise ValueError("semantic_rerank_context_receipts_incomplete")
        cached = _begin_context_receipt_issuance(
            object.__getattribute__(semantic_authority, "source"),
            execution_key,
            receipt_type,
        )
        if (
            cached is None
            or receipts is not cached
        ):
            raise ValueError("semantic_rerank_context_receipt_identity_mismatch")
        expected_batches.append(cached)
    parent_authorities = tuple(
        _validate_parent_context_receipt_exact(
            receipt=receipt,
            obligation=obligation,
            store=store,
            config=config,
            runtime=runtime,
        )
        for receipt in parent_receipts
    )
    bridge_authorities = tuple(
        _validate_bridge_context_receipt_exact(
            receipt=receipt,
            obligation=obligation,
            store=store,
            config=config,
            runtime=runtime,
        )
        for receipt in bridge_receipts
    )
    return parent_authorities, bridge_authorities


def _rerank_prerequisite_sha256(
    *,
    obligation: SemanticVerificationObligation,
    parent_receipts: tuple[ParentContextReceipt, ...],
    bridge_receipts: tuple[BridgeContextReceipt, ...],
    owner_plan_sha256: str,
    owner_plan_config_sha256: str,
    rerank_k: int,
    final_evidence_budget: int,
) -> str:
    return _canonical_sha256(
        {
            "schema_version": SCHEMA_VERSION,
            "semantic_obligation_sha256": object.__getattribute__(
                obligation, "obligation_sha256"
            ),
            "parent_context_receipt_sha256s": [
                object.__getattribute__(item, "receipt_sha256")
                for item in parent_receipts
            ],
            "parent_context_receipt_count": len(parent_receipts),
            "bridge_context_receipt_sha256s": [
                object.__getattribute__(item, "receipt_sha256")
                for item in bridge_receipts
            ],
            "bridge_context_receipt_count": len(bridge_receipts),
            "owner_plan_sha256": owner_plan_sha256,
            "owner_plan_config_sha256": owner_plan_config_sha256,
            "rerank_k": rerank_k,
            "final_evidence_budget": final_evidence_budget,
        }
    )


def _rerank_evidence_pool(
    *,
    obligation: SemanticVerificationObligation,
    semantic_authority: _SemanticVerificationObligationAuthority,
    bridge_authorities: tuple[_BridgeContextReceiptAuthority, ...],
) -> tuple[tuple[Evidence, ...], tuple[str, ...], tuple[str, ...]]:
    evidence: list[Evidence] = []
    roles: list[str] = []
    origins: list[str] = []
    seen: set[str] = set()
    for item in object.__getattribute__(semantic_authority, "evidence"):
        evidence_id = object.__getattribute__(item, "evidence_id")
        if evidence_id in seen:
            raise ValueError("semantic_rerank_candidate_duplicate")
        seen.add(evidence_id)
        evidence.append(item)
        roles.append("candidate")
        origins.append(evidence_id)
    for bridge_authority in bridge_authorities:
        seed_id = object.__getattribute__(
            object.__getattribute__(bridge_authority, "seed"), "evidence_id"
        )
        for item in object.__getattribute__(bridge_authority, "linked_evidence"):
            evidence_id = object.__getattribute__(item, "evidence_id")
            if evidence_id in seen:
                continue
            seen.add(evidence_id)
            evidence.append(item)
            roles.append("bridge")
            origins.append(seed_id)
    result = (tuple(evidence), tuple(roles), tuple(origins))
    if not result[0] or len(result[0]) != len(result[1]) or len(result[0]) != len(result[2]):
        raise ValueError("semantic_rerank_evidence_pool_mismatch")
    return result


def _validate_reranker_protocol(reranker: _ComponentAuthority) -> None:
    _validate_component_authority(reranker)
    component = object.__getattribute__(reranker, "component")
    if component is None:
        return
    method = object.__getattribute__(reranker, "method")
    code = object.__getattribute__(reranker, "method_code")
    if (
        type(method) is not FunctionType
        or type(code) is not CodeType
        or object.__getattribute__(method, "__defaults__") is not None
        or object.__getattribute__(method, "__kwdefaults__") is not None
        or object.__getattribute__(code, "co_argcount") != 2
        or object.__getattribute__(code, "co_posonlyargcount") != 0
        or object.__getattribute__(code, "co_kwonlyargcount") != 0
        or object.__getattribute__(code, "co_flags") & 0x0C
    ):
        raise ValueError("semantic_reranker_protocol_mismatch")


def _reranker_request(
    *,
    query: str,
    evidence: tuple[Evidence, ...],
    roles: tuple[str, ...],
) -> _RerankerRequest:
    items = tuple(
        _RerankerEvidence._create(
            index=index,
            role=roles[index],
            doc_id=object.__getattribute__(item, "doc_id"),
            content_kind=object.__getattribute__(item, "kind"),
            content=object.__getattribute__(item, "text"),
            _token=_RERANK_REQUEST_TOKEN,
        )
        for index, item in enumerate(evidence)
    )
    return _RerankerRequest._create(
        query=query,
        evidence=items,
        _token=_RERANK_REQUEST_TOKEN,
    )


def _rerank_execution_key(
    *,
    semantic_authority: _SemanticVerificationObligationAuthority,
    obligation: SemanticVerificationObligation,
    prerequisite_sha256: str,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
) -> tuple[object, ...]:
    return (
        "semantic-rerank-v1",
        object.__getattribute__(semantic_authority, "issuance_key"),
        object.__getattribute__(obligation, "obligation_key"),
        prerequisite_sha256,
        id(store),
        id(config),
        id(runtime),
    )


def _mint_rerank_receipt(
    *,
    obligation: SemanticVerificationObligation,
    semantic_authority: _SemanticVerificationObligationAuthority,
    parent_receipts: tuple[ParentContextReceipt, ...],
    bridge_receipts: tuple[BridgeContextReceipt, ...],
    evidence: tuple[Evidence, ...],
    roles: tuple[str, ...],
    origins: tuple[str, ...],
    ordered_indexes: tuple[int, ...],
    projection: object | None,
    outcome: str,
    error_code: str,
    call_performed: bool,
    result_sha256: str,
    owner_plan_sha256: str,
    owner_plan_config_sha256: str,
    rerank_k: int,
    final_evidence_budget: int,
    prerequisite_sha256: str,
    execution_key: tuple[object, ...],
) -> RerankReceipt:
    store = object.__getattribute__(semantic_authority, "store")
    config = object.__getattribute__(semantic_authority, "config")
    runtime = object.__getattribute__(semantic_authority, "runtime")
    ordered_evidence = tuple(evidence[index] for index in ordered_indexes)
    ordered_roles = tuple(roles[index] for index in ordered_indexes)
    ordered_origins = tuple(origins[index] for index in ordered_indexes)
    ordered_ids = tuple(
        object.__getattribute__(item, "evidence_id") for item in ordered_evidence
    )
    candidate_ids = tuple(
        evidence_id
        for evidence_id, role in zip(ordered_ids, ordered_roles)
        if role == "candidate"
    )
    bridge_ids = tuple(
        evidence_id
        for evidence_id, role in zip(ordered_ids, ordered_roles)
        if role == "bridge"
    )
    payload = {
        "stage": "semantic_rerank",
        "outcome": outcome,
        "error_code": error_code,
        "call_performed": call_performed,
        "semantic_obligation_sha256": object.__getattribute__(
            obligation, "obligation_sha256"
        ),
        "prerequisite_sha256": prerequisite_sha256,
        "parent_context_receipt_sha256s": tuple(
            object.__getattribute__(item, "receipt_sha256")
            for item in parent_receipts
        ),
        "bridge_context_receipt_sha256s": tuple(
            object.__getattribute__(item, "receipt_sha256")
            for item in bridge_receipts
        ),
        "owner_plan_sha256": owner_plan_sha256,
        "owner_plan_config_sha256": owner_plan_config_sha256,
        "query_sha256": object.__getattribute__(obligation, "query_sha256"),
        "rerank_k": rerank_k,
        "final_evidence_budget": final_evidence_budget,
        "input_evidence_ids": tuple(
            object.__getattribute__(item, "evidence_id") for item in evidence
        ),
        "input_evidence_roles": roles,
        "input_count": len(evidence),
        "ordered_evidence_ids": ordered_ids,
        "ordered_stable_anchors": tuple(
            _stable_anchor(item) for item in ordered_evidence
        ),
        "candidate_evidence_ids": candidate_ids,
        "bridge_evidence_ids": bridge_ids,
        "effective_output_count": len(ordered_evidence),
        "reranker_id": object.__getattribute__(runtime, "reranker_id"),
        "reranker_implementation_sha256": object.__getattribute__(
            runtime, "reranker_implementation_sha256"
        ),
        "reranker_config_sha256": object.__getattribute__(
            runtime, "reranker_config_sha256"
        ),
        "evidence_store_sha256": object.__getattribute__(
            store, "bundle_sha256"
        ),
        "execution_config_sha256": object.__getattribute__(
            config, "config_sha256"
        ),
        "runtime_binding_sha256": object.__getattribute__(
            runtime, "binding_sha256"
        ),
        "result_sha256": result_sha256,
    }
    temporary = object.__new__(RerankReceipt)
    for name, value in payload.items():
        object.__setattr__(temporary, name, value)
    object.__setattr__(temporary, "receipt_sha256", "0" * 64)
    payload["receipt_sha256"] = _canonical_sha256(
        _rerank_receipt_payload(temporary, include_hash=False)
    )
    receipt = RerankReceipt._create(
        payload=payload,
        _token=_RERANK_RECEIPT_TOKEN,
    )
    identity = id(receipt)
    weak = ref(
        receipt,
        lambda dead, identity=identity: _drop_rerank_receipt_authority(
            identity, dead
        ),
    )
    _register_rerank_receipt_authority(
        receipt,
        _RerankReceiptAuthority(
            weak=weak,
            root_source_weak=ref(
                object.__getattribute__(semantic_authority, "source")
            ),
            semantic_issuance_key=object.__getattribute__(
                semantic_authority, "issuance_key"
            ),
            parent_receipts=parent_receipts,
            bridge_receipts=bridge_receipts,
            input_evidence=evidence,
            input_roles=roles,
            origin_seed_ids=origins,
            ordered_evidence=ordered_evidence,
            ordered_roles=ordered_roles,
            ordered_origin_seed_ids=ordered_origins,
            store=store,
            config=config,
            runtime=runtime,
            execution_key=execution_key,
            route_key=object.__getattribute__(semantic_authority, "route_key"),
            projection=projection,
            issued_payload_sha256=_canonical_sha256(receipt.to_dict()),
        ),
    )
    return receipt


def _validate_rerank_receipt_exact(
    *,
    receipt: RerankReceipt,
    obligation: SemanticVerificationObligation,
    parent_receipts: tuple[ParentContextReceipt, ...],
    bridge_receipts: tuple[BridgeContextReceipt, ...],
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
) -> _RerankReceiptAuthority:
    semantic_authority = _validate_semantic_verification_obligation_exact(
        obligation=obligation, store=store, config=config, runtime=runtime
    )
    if object.__getattribute__(obligation, "derivation_kind") != "base":
        raise ValueError("semantic_rerank_requires_base_obligation")
    _, bridge_authorities = _validate_complete_context_receipts(
        obligation=obligation,
        semantic_authority=semantic_authority,
        parent_receipts=parent_receipts,
        bridge_receipts=bridge_receipts,
        store=store,
        config=config,
        runtime=runtime,
    )
    owner_plan_sha, owner_config_sha, rerank_k, final_budget = (
        _semantic_owner_plan_budget(semantic_authority)
    )
    prerequisite_sha = _rerank_prerequisite_sha256(
        obligation=obligation,
        parent_receipts=parent_receipts,
        bridge_receipts=bridge_receipts,
        owner_plan_sha256=owner_plan_sha,
        owner_plan_config_sha256=owner_config_sha,
        rerank_k=rerank_k,
        final_evidence_budget=final_budget,
    )
    execution_key = _rerank_execution_key(
        semantic_authority=semantic_authority,
        obligation=obligation,
        prerequisite_sha256=prerequisite_sha,
        store=store,
        config=config,
        runtime=runtime,
    )
    evidence, roles, origins = _rerank_evidence_pool(
        obligation=obligation,
        semantic_authority=semantic_authority,
        bridge_authorities=bridge_authorities,
    )
    _validate_rerank_receipt_payload(receipt)
    authority = _read_rerank_receipt_authority(receipt)
    ordered_evidence = object.__getattribute__(authority, "ordered_evidence")
    if (
        object.__getattribute__(authority, "root_source_weak")()
        is not object.__getattribute__(semantic_authority, "source")
        or object.__getattribute__(authority, "semantic_issuance_key")
        != object.__getattribute__(semantic_authority, "issuance_key")
        or object.__getattribute__(authority, "parent_receipts")
        is not parent_receipts
        or object.__getattribute__(authority, "bridge_receipts")
        is not bridge_receipts
        or object.__getattribute__(authority, "store") is not store
        or object.__getattribute__(authority, "config") is not config
        or object.__getattribute__(authority, "runtime") is not runtime
        or object.__getattribute__(authority, "execution_key") != execution_key
        or object.__getattribute__(authority, "route_key")
        != object.__getattribute__(semantic_authority, "route_key")
        or _semantic_route_status(
            object.__getattribute__(semantic_authority, "route_key")
        )
        != "rerank_consumed"
        or object.__getattribute__(authority, "input_evidence") != evidence
        or any(
            current is not expected
            for current, expected in zip(
                object.__getattribute__(authority, "input_evidence"), evidence
            )
        )
        or object.__getattribute__(authority, "input_roles") != roles
        or object.__getattribute__(authority, "origin_seed_ids") != origins
        or object.__getattribute__(receipt, "prerequisite_sha256")
        != prerequisite_sha
        or object.__getattribute__(receipt, "owner_plan_sha256")
        != owner_plan_sha
        or object.__getattribute__(receipt, "owner_plan_config_sha256")
        != owner_config_sha
        or object.__getattribute__(receipt, "rerank_k") != rerank_k
        or object.__getattribute__(receipt, "final_evidence_budget")
        != final_budget
        or object.__getattribute__(receipt, "semantic_obligation_sha256")
        != object.__getattribute__(obligation, "obligation_sha256")
        or object.__getattribute__(receipt, "ordered_evidence_ids")
        != tuple(
            object.__getattribute__(item, "evidence_id")
            for item in ordered_evidence
        )
        or object.__getattribute__(authority, "issued_payload_sha256")
        != _canonical_sha256(receipt.to_dict())
    ):
        raise ValueError("rerank_receipt_authority_drift")
    return authority


def _rerank_sanitized_result_sha256(
    *,
    outcome: str,
    obligation: SemanticVerificationObligation,
    prerequisite_sha256: str,
    ordered_indexes: tuple[int, ...],
) -> str:
    return _canonical_sha256(
        {
            "schema_version": SCHEMA_VERSION,
            "outcome": outcome,
            "semantic_obligation_sha256": object.__getattribute__(
                obligation, "obligation_sha256"
            ),
            "prerequisite_sha256": prerequisite_sha256,
            "ordered_indexes": list(ordered_indexes),
        }
    )


def execute_semantic_rerank(
    *,
    obligation: SemanticVerificationObligation,
    parent_receipts: tuple[ParentContextReceipt, ...],
    bridge_receipts: tuple[BridgeContextReceipt, ...],
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    _dependency_checker=None,
    _dependency_checker_code=None,
) -> RerankReceipt:
    """Execute the exact c3.2 rerank branch; intentionally module-visible."""

    _semantic_public_entry(_dependency_checker, _dependency_checker_code)
    _validate_action_effects_dependency()
    semantic_authority = _validate_semantic_verification_obligation_exact(
        obligation=obligation, store=store, config=config, runtime=runtime
    )
    if object.__getattribute__(obligation, "derivation_kind") != "base":
        raise ValueError("semantic_rerank_requires_base_obligation")
    _, bridge_authorities = _validate_complete_context_receipts(
        obligation=obligation,
        semantic_authority=semantic_authority,
        parent_receipts=parent_receipts,
        bridge_receipts=bridge_receipts,
        store=store,
        config=config,
        runtime=runtime,
    )
    owner_plan_sha, owner_config_sha, rerank_k, final_budget = (
        _semantic_owner_plan_budget(semantic_authority)
    )
    evidence, roles, origins = _rerank_evidence_pool(
        obligation=obligation,
        semantic_authority=semantic_authority,
        bridge_authorities=bridge_authorities,
    )
    prerequisite_sha = _rerank_prerequisite_sha256(
        obligation=obligation,
        parent_receipts=parent_receipts,
        bridge_receipts=bridge_receipts,
        owner_plan_sha256=owner_plan_sha,
        owner_plan_config_sha256=owner_config_sha,
        rerank_k=rerank_k,
        final_evidence_budget=final_budget,
    )
    runtime_authority = _semantic_common_preflight(
        store=store, config=config, runtime=runtime
    )
    reranker = object.__getattribute__(runtime_authority, "reranker")
    _validate_reranker_protocol(reranker)
    request = _reranker_request(
        query=object.__getattribute__(semantic_authority, "raw_query"),
        evidence=evidence,
        roles=roles,
    )
    route_key = object.__getattribute__(semantic_authority, "route_key")
    execution_key = _rerank_execution_key(
        semantic_authority=semantic_authority,
        obligation=obligation,
        prerequisite_sha256=prerequisite_sha,
        store=store,
        config=config,
        runtime=runtime,
    )
    cached = _begin_semantic_rerank(
        object.__getattribute__(semantic_authority, "source"),
        route_key,
        execution_key,
    )
    if cached is not None:
        _validate_rerank_receipt_exact(
            receipt=cached,
            obligation=obligation,
            parent_receipts=parent_receipts,
            bridge_receipts=bridge_receipts,
            store=store,
            config=config,
            runtime=runtime,
        )
        return cached
    if object.__getattribute__(reranker, "component") is None:
        ordered_indexes = tuple(range(min(rerank_k, len(evidence))))
        result_sha = _rerank_sanitized_result_sha256(
            outcome="skipped_unavailable",
            obligation=obligation,
            prerequisite_sha256=prerequisite_sha,
            ordered_indexes=ordered_indexes,
        )
        try:
            receipt = _mint_rerank_receipt(
                obligation=obligation,
                semantic_authority=semantic_authority,
                parent_receipts=parent_receipts,
                bridge_receipts=bridge_receipts,
                evidence=evidence,
                roles=roles,
                origins=origins,
                ordered_indexes=ordered_indexes,
                projection=None,
                outcome="skipped_unavailable",
                error_code="reranker_unavailable",
                call_performed=False,
                result_sha256=result_sha,
                owner_plan_sha256=owner_plan_sha,
                owner_plan_config_sha256=owner_config_sha,
                rerank_k=rerank_k,
                final_evidence_budget=final_budget,
                prerequisite_sha256=prerequisite_sha,
                execution_key=execution_key,
            )
            _complete_semantic_rerank(route_key, execution_key, receipt)
            return receipt
        except Exception:
            _fail_semantic_rerank(route_key, execution_key)
            raise ValueError("semantic_reranker_contract_error") from None
    provider_failed = False
    try:
        raw_result = object.__getattribute__(reranker, "method")(
            object.__getattribute__(reranker, "component"), request
        )
    except Exception:
        provider_failed = True
        raw_result = None
    try:
        _semantic_public_entry(_dependency_checker, _dependency_checker_code)
        _validate_action_effects_dependency()
        authority_after = _validate_semantic_verification_obligation_exact(
            obligation=obligation,
            store=store,
            config=config,
            runtime=runtime,
        )
        if authority_after is not semantic_authority:
            raise ValueError("semantic_verification_obligation_authority_drift")
        _, bridge_after = _validate_complete_context_receipts(
            obligation=obligation,
            semantic_authority=semantic_authority,
            parent_receipts=parent_receipts,
            bridge_receipts=bridge_receipts,
            store=store,
            config=config,
            runtime=runtime,
        )
        if _semantic_owner_plan_budget(semantic_authority) != (
            owner_plan_sha,
            owner_config_sha,
            rerank_k,
            final_budget,
        ):
            raise ValueError("semantic_owner_plan_drift")
        if _rerank_evidence_pool(
            obligation=obligation,
            semantic_authority=semantic_authority,
            bridge_authorities=bridge_after,
        ) != (evidence, roles, origins):
            raise ValueError("semantic_rerank_evidence_pool_drift")
        runtime_after = _semantic_common_preflight(
            store=store, config=config, runtime=runtime
        )
        reranker_after = object.__getattribute__(runtime_after, "reranker")
        _validate_reranker_protocol(reranker_after)
        if reranker_after is not reranker:
            raise ValueError("semantic_reranker_authority_drift")
        if provider_failed:
            outcome = "provider_error"
            projection = None
            ordered_indexes = ()
        else:
            projection = _ISSUED_ACTION_EFFECTS_RERANK_NORMALIZER(
                raw_result,
                input_count=len(evidence),
                rerank_k=rerank_k,
            )
            if type(projection) is not _ISSUED_ACTION_EFFECTS_RERANK_PROJECTION_CLASS:
                raise ValueError("semantic_reranker_projection_mismatch")
            ordered_indexes = object.__getattribute__(
                projection, "ordered_indexes"
            )
            outcome = "applied"
    except Exception:
        outcome = "contract_error"
        projection = None
        ordered_indexes = ()
    error_code = {
        "applied": "none",
        "provider_error": "reranker_provider_error",
        "contract_error": "reranker_contract_error",
    }[outcome]
    result_sha = (
        object.__getattribute__(projection, "result_sha256")
        if projection is not None
        else _rerank_sanitized_result_sha256(
            outcome=outcome,
            obligation=obligation,
            prerequisite_sha256=prerequisite_sha,
            ordered_indexes=(),
        )
    )
    try:
        receipt = _mint_rerank_receipt(
            obligation=obligation,
            semantic_authority=semantic_authority,
            parent_receipts=parent_receipts,
            bridge_receipts=bridge_receipts,
            evidence=evidence,
            roles=roles,
            origins=origins,
            ordered_indexes=ordered_indexes,
            projection=projection,
            outcome=outcome,
            error_code=error_code,
            call_performed=True,
            result_sha256=result_sha,
            owner_plan_sha256=owner_plan_sha,
            owner_plan_config_sha256=owner_config_sha,
            rerank_k=rerank_k,
            final_evidence_budget=final_budget,
            prerequisite_sha256=prerequisite_sha,
            execution_key=execution_key,
        )
        _complete_semantic_rerank(route_key, execution_key, receipt)
        return receipt
    except Exception:
        _fail_semantic_rerank(route_key, execution_key)
        raise ValueError("semantic_reranker_contract_error") from None


def validate_rerank_receipt(
    *,
    receipt: RerankReceipt,
    obligation: SemanticVerificationObligation,
    parent_receipts: tuple[ParentContextReceipt, ...],
    bridge_receipts: tuple[BridgeContextReceipt, ...],
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    _dependency_checker=None,
    _dependency_checker_code=None,
) -> None:
    _semantic_public_entry(_dependency_checker, _dependency_checker_code)
    _validate_action_effects_dependency()
    _validate_rerank_receipt_exact(
        receipt=receipt,
        obligation=obligation,
        parent_receipts=parent_receipts,
        bridge_receipts=bridge_receipts,
        store=store,
        config=config,
        runtime=runtime,
    )


def issue_derived_semantic_verification_obligation(
    *,
    obligation: SemanticVerificationObligation,
    parent_receipts: tuple[ParentContextReceipt, ...],
    bridge_receipts: tuple[BridgeContextReceipt, ...],
    rerank_receipt: RerankReceipt,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    _dependency_checker=None,
    _dependency_checker_code=None,
) -> SemanticVerificationObligation:
    _semantic_public_entry(_dependency_checker, _dependency_checker_code)
    semantic_authority = _validate_semantic_verification_obligation_exact(
        obligation=obligation, store=store, config=config, runtime=runtime
    )
    if object.__getattribute__(obligation, "derivation_kind") != "base":
        raise ValueError("semantic_derived_recursion_forbidden")
    parent_authorities, _ = _validate_complete_context_receipts(
        obligation=obligation,
        semantic_authority=semantic_authority,
        parent_receipts=parent_receipts,
        bridge_receipts=bridge_receipts,
        store=store,
        config=config,
        runtime=runtime,
    )
    rerank_authority = _validate_rerank_receipt_exact(
        receipt=rerank_receipt,
        obligation=obligation,
        parent_receipts=parent_receipts,
        bridge_receipts=bridge_receipts,
        store=store,
        config=config,
        runtime=runtime,
    )
    if object.__getattribute__(rerank_receipt, "outcome") not in {
        "applied",
        "skipped_unavailable",
    }:
        raise ValueError("semantic_derived_rerank_outcome_failed")
    final_budget = object.__getattribute__(
        rerank_receipt, "final_evidence_budget"
    )
    evidence = object.__getattribute__(rerank_authority, "ordered_evidence")[
        :final_budget
    ]
    roles = object.__getattribute__(rerank_authority, "ordered_roles")[
        :final_budget
    ]
    origins = object.__getattribute__(
        rerank_authority, "ordered_origin_seed_ids"
    )[:final_budget]
    supplied = tuple(
        object.__getattribute__(item, "evidence_id") for item in evidence
    )
    if not supplied:
        raise ValueError("semantic_derived_evidence_required")
    candidates = tuple(
        evidence_id
        for evidence_id, role in zip(supplied, roles)
        if role == "candidate"
    )
    bridges = tuple(
        evidence_id
        for evidence_id, role in zip(supplied, roles)
        if role == "bridge"
    )
    parent_by_seed = {
        object.__getattribute__(authority, "seed").evidence_id: object.__getattribute__(
            authority, "parent"
        )
        for authority in parent_authorities
    }
    auxiliary_parents: list[ProvenanceParent] = []
    seen_parent_ids: set[str] = set()
    for origin in origins:
        parent = parent_by_seed.get(origin)
        if parent is None:
            continue
        parent_id = object.__getattribute__(parent, "parent_id")
        if parent_id not in seen_parent_ids:
            seen_parent_ids.add(parent_id)
            auxiliary_parents.append(parent)
    owner_plan_sha = object.__getattribute__(rerank_receipt, "owner_plan_sha256")
    owner_config_sha = object.__getattribute__(
        rerank_receipt, "owner_plan_config_sha256"
    )
    rerank_k = object.__getattribute__(rerank_receipt, "rerank_k")
    issuance_key = (
        "semantic-reranked-v1",
        object.__getattribute__(semantic_authority, "issuance_key"),
        object.__getattribute__(rerank_receipt, "receipt_sha256"),
        id(store),
        id(config),
        id(runtime),
    )
    cached = _cached_semantic_obligation(issuance_key)
    if cached is not None:
        _validate_semantic_verification_obligation_exact(
            obligation=cached, store=store, config=config, runtime=runtime
        )
        return cached
    payload = {
        "derivation_kind": "reranked",
        "source_kind": object.__getattribute__(obligation, "source_kind"),
        "target_kind": object.__getattribute__(obligation, "target_kind"),
        "obligation_key": object.__getattribute__(obligation, "obligation_key"),
        "target_doc_id": object.__getattribute__(obligation, "target_doc_id"),
        "field": object.__getattribute__(obligation, "field"),
        "execution_kind": object.__getattribute__(obligation, "execution_kind"),
        "owner_binding_sha256": object.__getattribute__(
            obligation, "owner_binding_sha256"
        ),
        "retrieval_obligation_sha256": object.__getattribute__(
            obligation, "retrieval_obligation_sha256"
        ),
        "candidate_receipt_sha256": object.__getattribute__(
            obligation, "candidate_receipt_sha256"
        ),
        "source_state_sha256": object.__getattribute__(
            obligation, "source_state_sha256"
        ),
        "base_semantic_obligation_sha256": object.__getattribute__(
            obligation, "obligation_sha256"
        ),
        "parent_context_receipt_sha256s": tuple(
            object.__getattribute__(item, "receipt_sha256")
            for item in parent_receipts
        ),
        "bridge_context_receipt_sha256s": tuple(
            object.__getattribute__(item, "receipt_sha256")
            for item in bridge_receipts
        ),
        "rerank_receipt_sha256": object.__getattribute__(
            rerank_receipt, "receipt_sha256"
        ),
        "owner_plan_sha256": owner_plan_sha,
        "owner_plan_config_sha256": owner_config_sha,
        "rerank_k": rerank_k,
        "final_evidence_budget": final_budget,
        "query_sha256": object.__getattribute__(obligation, "query_sha256"),
        "evidence_store_sha256": object.__getattribute__(
            obligation, "evidence_store_sha256"
        ),
        "execution_config_sha256": object.__getattribute__(
            obligation, "execution_config_sha256"
        ),
        "runtime_binding_sha256": object.__getattribute__(
            obligation, "runtime_binding_sha256"
        ),
        "candidate_evidence_ids": candidates,
        "bridge_evidence_ids": bridges,
        "context_evidence_ids": (),
        "supplied_evidence_ids": supplied,
        "ordered_stable_anchors": tuple(_stable_anchor(item) for item in evidence),
    }
    temporary = object.__new__(SemanticVerificationObligation)
    for name, value in payload.items():
        object.__setattr__(temporary, name, value)
    object.__setattr__(temporary, "obligation_sha256", "0" * 64)
    payload["obligation_sha256"] = _canonical_sha256(
        _semantic_verification_obligation_payload(temporary, include_hash=False)
    )
    result = SemanticVerificationObligation._create(
        payload=payload, _token=_SEMANTIC_OBLIGATION_TOKEN
    )
    identity = id(result)
    weak = ref(
        result,
        lambda dead, identity=identity: _drop_semantic_obligation_authority(
            identity, dead
        ),
    )
    runtime_authority = _semantic_common_preflight(
        store=store, config=config, runtime=runtime
    )
    authority = _SemanticVerificationObligationAuthority(
        weak=weak,
        issued_payload_sha256=_canonical_sha256(result.to_dict()),
        issuance_key=issuance_key,
        source=object.__getattribute__(semantic_authority, "source"),
        candidate_receipt=object.__getattribute__(
            semantic_authority, "candidate_receipt"
        ),
        source_state=object.__getattribute__(semantic_authority, "source_state"),
        retrieval_obligation=object.__getattribute__(
            semantic_authority, "retrieval_obligation"
        ),
        fusion_receipt=object.__getattribute__(semantic_authority, "fusion_receipt"),
        dense_receipt=object.__getattribute__(semantic_authority, "dense_receipt"),
        lexical_receipt=object.__getattribute__(
            semantic_authority, "lexical_receipt"
        ),
        registry=object.__getattribute__(semantic_authority, "registry"),
        policy=object.__getattribute__(semantic_authority, "policy"),
        raw_query=object.__getattribute__(semantic_authority, "raw_query"),
        evidence=evidence,
        roles=roles,
        origin_seed_ids=origins,
        auxiliary_parents=tuple(auxiliary_parents),
        base_obligation=obligation,
        base_issuance_key=object.__getattribute__(
            semantic_authority, "issuance_key"
        ),
        parent_receipts=parent_receipts,
        bridge_receipts=bridge_receipts,
        rerank_receipt=rerank_receipt,
        route_key=object.__getattribute__(semantic_authority, "route_key"),
        execution_key=(
            "semantic-execution-v2",
            "reranked",
            object.__getattribute__(semantic_authority, "issuance_key"),
            object.__getattribute__(rerank_receipt, "receipt_sha256"),
            id(store),
            id(config),
            id(runtime),
        ),
        owner_plan_sha256=owner_plan_sha,
        owner_plan_config_sha256=owner_config_sha,
        rerank_k=rerank_k,
        final_evidence_budget=final_budget,
        store=store,
        config=config,
        runtime=runtime,
        verifier_authority=object.__getattribute__(runtime_authority, "verifier"),
    )
    _register_semantic_obligation_authority(result, authority)
    return result


def _validate_snapshot_callable(
    function: object,
    pin: tuple[object, ...],
    code: str,
) -> None:
    if type(function) is not FunctionType or type(pin) is not tuple or len(pin) != 8:
        raise ValueError(code)
    (
        issued,
        name,
        issued_code,
        defaults,
        kwdefaults,
        kwdefault_items,
        function_globals,
        closure,
    ) = pin
    current_kwdefaults = object.__getattribute__(function, "__kwdefaults__")
    if (
        function is not issued
        or object.__getattribute__(function, "__name__") != name
        or object.__getattribute__(function, "__code__") is not issued_code
        or object.__getattribute__(function, "__defaults__") is not defaults
        or current_kwdefaults is not kwdefaults
        or (
            None
            if current_kwdefaults is None
            else tuple(sorted(dict.items(current_kwdefaults)))
        )
        != kwdefault_items
        or object.__getattribute__(function, "__globals__") is not function_globals
        or object.__getattribute__(function, "__closure__") is not closure
    ):
        raise ValueError(code)


def _validate_snapshot_class(
    owner: object,
    pin: tuple[object, ...],
    code: str,
) -> None:
    if type(owner) is not type or type(pin) is not tuple or len(pin) != 2:
        raise ValueError(code)
    names, members = pin
    namespace = type.__getattribute__(owner, "__dict__")
    if tuple(sorted(namespace)) != names:
        raise ValueError(code)
    for name, issued, issued_type, callable_pins in members:
        current = namespace.get(name)
        if current is not issued or type(current) is not issued_type:
            raise ValueError(code)
        current_callables: list[tuple[str, FunctionType]] = []
        if type(current) is FunctionType:
            current_callables.append(("function", current))
        elif type(current) in {classmethod, staticmethod}:
            current_callables.append(
                ("wrapped", object.__getattribute__(current, "__func__"))
            )
        elif type(current) is property:
            for role in ("fget", "fset", "fdel"):
                function = object.__getattribute__(current, role)
                if function is not None:
                    current_callables.append((role, function))
        if len(current_callables) != len(callable_pins):
            raise ValueError(code)
        for (role, function), (pinned_role, callable_pin) in zip(
            current_callables, callable_pins
        ):
            if role != pinned_role:
                raise ValueError(code)
            _validate_snapshot_callable(function, callable_pin, code)


def _validate_action_effects_dependency() -> None:
    module = _ACTION_EFFECTS_MODULE
    snapshot = _ISSUED_ACTION_EFFECTS_MODULE_PIN
    if type(snapshot) is not tuple or len(snapshot) != 2:
        raise ValueError("semantic_normalizer_dependency_drift")
    names, members = snapshot
    namespace = object.__getattribute__(module, "__dict__")
    if tuple(sorted(name for name in namespace if not name.startswith("__"))) != names:
        raise ValueError("semantic_normalizer_dependency_drift")
    for name, issued, issued_type, callable_pin, class_pin in members:
        current = dict.get(namespace, name)
        if current is not issued or type(current) is not issued_type:
            raise ValueError("semantic_normalizer_dependency_drift")
        if callable_pin is not None:
            _validate_snapshot_callable(
                current, callable_pin, "semantic_normalizer_dependency_drift"
            )
        if class_pin is not None:
            _validate_snapshot_class(
                current, class_pin, "semantic_normalizer_dependency_drift"
            )
    if (
        dict.get(namespace, "_normalize_semantic_verifier_result")
        is not _ISSUED_ACTION_EFFECTS_NORMALIZER
        or dict.get(namespace, "_SemanticVerificationProjection")
        is not _ISSUED_ACTION_EFFECTS_PROJECTION_CLASS
        or dict.get(namespace, "_normalize_reranker_result")
        is not _ISSUED_ACTION_EFFECTS_RERANK_NORMALIZER
        or dict.get(namespace, "_RerankProjection")
        is not _ISSUED_ACTION_EFFECTS_RERANK_PROJECTION_CLASS
        or dict.get(namespace, "SemanticValueSupport") is not SemanticValueSupport
    ):
        raise ValueError("semantic_normalizer_dependency_drift")


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class SemanticVerificationReceipt:
    stage: str
    source_kind: str
    target_kind: str
    obligation_key: str
    target_doc_id: str | None
    field: str | None
    semantic_obligation_sha256: str
    owner_binding_sha256: str
    candidate_receipt_sha256: str
    query_sha256: str
    evidence_store_sha256: str
    execution_config_sha256: str
    runtime_binding_sha256: str
    verifier_id: str
    verifier_implementation_sha256: str
    verifier_config_sha256: str
    supplied_evidence_ids: tuple[str, ...]
    ordered_stable_anchors: tuple[StableEvidenceAnchor, ...]
    disposition: str
    verified_evidence_ids: tuple[str, ...]
    contradicted_evidence_ids: tuple[str, ...]
    values: tuple[SemanticValueSupport, ...]
    call_performed: bool
    result_sha256: str
    receipt_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("semantic_verification_receipt_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        payload: Mapping[str, Any],
        _token: object,
    ) -> SemanticVerificationReceipt:
        if _token is not _SEMANTIC_RECEIPT_TOKEN:
            raise ValueError("semantic_verification_receipt_factory_required")
        result = object.__new__(cls)
        for name in cls.__slots__:
            if name != "__weakref__":
                object.__setattr__(result, name, payload[name])
        _validate_semantic_verification_receipt_payload(result)
        return result

    def to_dict(self) -> dict[str, Any]:
        _validate_semantic_verification_receipt_payload(self)
        return _semantic_verification_receipt_payload(self, include_hash=True)


def _semantic_verification_receipt_payload(
    receipt: SemanticVerificationReceipt,
    *,
    include_hash: bool,
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "stage": object.__getattribute__(receipt, "stage"),
        "source_kind": object.__getattribute__(receipt, "source_kind"),
        "target_kind": object.__getattribute__(receipt, "target_kind"),
        "obligation_key": object.__getattribute__(receipt, "obligation_key"),
        "target_doc_id": object.__getattribute__(receipt, "target_doc_id"),
        "field": object.__getattribute__(receipt, "field"),
        "semantic_obligation_sha256": object.__getattribute__(
            receipt, "semantic_obligation_sha256"
        ),
        "owner_binding_sha256": object.__getattribute__(
            receipt, "owner_binding_sha256"
        ),
        "candidate_receipt_sha256": object.__getattribute__(
            receipt, "candidate_receipt_sha256"
        ),
        "query_sha256": object.__getattribute__(receipt, "query_sha256"),
        "evidence_store_sha256": object.__getattribute__(
            receipt, "evidence_store_sha256"
        ),
        "execution_config_sha256": object.__getattribute__(
            receipt, "execution_config_sha256"
        ),
        "runtime_binding_sha256": object.__getattribute__(
            receipt, "runtime_binding_sha256"
        ),
        "verifier_id": object.__getattribute__(receipt, "verifier_id"),
        "verifier_implementation_sha256": object.__getattribute__(
            receipt, "verifier_implementation_sha256"
        ),
        "verifier_config_sha256": object.__getattribute__(
            receipt, "verifier_config_sha256"
        ),
        "supplied_evidence_ids": list(
            object.__getattribute__(receipt, "supplied_evidence_ids")
        ),
        "ordered_stable_anchors": [
            anchor.to_dict()
            for anchor in object.__getattribute__(
                receipt, "ordered_stable_anchors"
            )
        ],
        "disposition": object.__getattribute__(receipt, "disposition"),
        "verified_evidence_ids": list(
            object.__getattribute__(receipt, "verified_evidence_ids")
        ),
        "contradicted_evidence_ids": list(
            object.__getattribute__(receipt, "contradicted_evidence_ids")
        ),
        "values": [
            value.to_dict()
            for value in object.__getattribute__(receipt, "values")
        ],
        "call_performed": object.__getattribute__(receipt, "call_performed"),
        "result_sha256": object.__getattribute__(receipt, "result_sha256"),
    }
    if include_hash:
        payload["receipt_sha256"] = object.__getattribute__(
            receipt, "receipt_sha256"
        )
    return payload


def _validate_semantic_verification_receipt_payload(
    receipt: SemanticVerificationReceipt,
) -> None:
    if type(receipt) is not SemanticVerificationReceipt:
        raise TypeError("semantic_verification_receipt_required")
    if object.__getattribute__(receipt, "stage") != "semantic_verification":
        raise ValueError("invalid_semantic_verification_stage")
    disposition = object.__getattribute__(receipt, "disposition")
    if disposition not in _SEMANTIC_DISPOSITIONS:
        raise ValueError("invalid_semantic_disposition")
    for name in (
        "semantic_obligation_sha256",
        "owner_binding_sha256",
        "candidate_receipt_sha256",
        "query_sha256",
        "evidence_store_sha256",
        "execution_config_sha256",
        "runtime_binding_sha256",
        "verifier_implementation_sha256",
        "verifier_config_sha256",
        "result_sha256",
        "receipt_sha256",
    ):
        _require_hash(object.__getattribute__(receipt, name), f"invalid_{name}")
    supplied = _exact_string_tuple_value(
        object.__getattribute__(receipt, "supplied_evidence_ids"),
        "semantic_receipt_supplied_ids",
        allow_empty=False,
    )
    verified = _exact_string_tuple_value(
        object.__getattribute__(receipt, "verified_evidence_ids"),
        "semantic_receipt_verified_ids",
        allow_empty=True,
    )
    contradicted = _exact_string_tuple_value(
        object.__getattribute__(receipt, "contradicted_evidence_ids"),
        "semantic_receipt_contradicted_ids",
        allow_empty=True,
    )
    if not set(verified).issubset(supplied) or not set(contradicted).issubset(supplied):
        raise ValueError("semantic_receipt_evidence_not_supplied")
    values = object.__getattribute__(receipt, "values")
    if type(values) is not tuple or any(
        type(value) is not SemanticValueSupport for value in values
    ):
        raise TypeError("semantic_receipt_values_required")
    call_performed = object.__getattribute__(receipt, "call_performed")
    if type(call_performed) is not bool:
        raise TypeError("semantic_receipt_call_performed_bool_required")
    verifier_id = object.__getattribute__(receipt, "verifier_id")
    if disposition == "unavailable":
        if call_performed or verifier_id != "none" or verified or contradicted or values:
            raise ValueError("semantic_unavailable_receipt_mismatch")
    elif not call_performed or verifier_id == "none":
        raise ValueError("semantic_called_receipt_mismatch")
    if disposition == "supported" and (not verified or contradicted):
        raise ValueError("semantic_supported_receipt_mismatch")
    if disposition == "contradicted" and (not contradicted or verified):
        raise ValueError("semantic_contradicted_receipt_mismatch")
    if disposition == "unsupported" and (verified or contradicted or values):
        raise ValueError("semantic_unsupported_receipt_mismatch")
    anchors = object.__getattribute__(receipt, "ordered_stable_anchors")
    if type(anchors) is not tuple or len(anchors) != len(supplied) or any(
        type(anchor) is not StableEvidenceAnchor for anchor in anchors
    ):
        raise ValueError("semantic_receipt_anchor_mismatch")
    expected = _canonical_sha256(
        _semantic_verification_receipt_payload(receipt, include_hash=False)
    )
    if object.__getattribute__(receipt, "receipt_sha256") != expected:
        raise ValueError("semantic_verification_receipt_hash_mismatch")


@dataclass(frozen=True, slots=True)
class _SemanticVerificationReceiptAuthority:
    weak: ReferenceType[SemanticVerificationReceipt]
    obligation: SemanticVerificationObligation
    store: EvidenceStore
    config: HarnessExecutionConfig
    runtime: HarnessRuntimeBinding
    projection: object | None
    execution_key: tuple[object, ...]
    issued_payload_sha256: str


_SEMANTIC_RECEIPT_AUTHORITIES: dict[int, _SemanticVerificationReceiptAuthority] = {}
_ISSUED_SEMANTIC_RECEIPT_AUTHORITIES = _SEMANTIC_RECEIPT_AUTHORITIES


def _build_semantic_receipt_accessors(
    visible: dict[int, _SemanticVerificationReceiptAuthority],
) -> tuple[FunctionType, FunctionType, FunctionType]:
    shadow: dict[int, tuple[object, ...]] = {}
    authority_lock = Lock()

    def snapshot(authority: _SemanticVerificationReceiptAuthority) -> tuple[object, ...]:
        return tuple(
            object.__getattribute__(authority, name)
            for name in _SemanticVerificationReceiptAuthority.__slots__
        )

    def register(
        receipt: SemanticVerificationReceipt,
        authority: _SemanticVerificationReceiptAuthority,
    ) -> None:
        with authority_lock:
            identity = id(receipt)
            if dict.get(visible, identity) is not None or dict.get(shadow, identity) is not None:
                raise ValueError("semantic_verification_receipt_authority_drift")
            dict.__setitem__(visible, identity, authority)
            dict.__setitem__(shadow, identity, snapshot(authority))

    def read(receipt: SemanticVerificationReceipt) -> _SemanticVerificationReceiptAuthority:
        with authority_lock:
            identity = id(receipt)
            current = dict.get(visible, identity)
            sealed = dict.get(shadow, identity)
            if (
                type(current) is not _SemanticVerificationReceiptAuthority
                or type(sealed) is not tuple
                or object.__getattribute__(current, "weak")() is not receipt
                or len(sealed) != len(_SemanticVerificationReceiptAuthority.__slots__)
                or any(
                    object.__getattribute__(current, name) is not value
                    for name, value in zip(
                        _SemanticVerificationReceiptAuthority.__slots__, sealed
                    )
                )
            ):
                raise ValueError("semantic_verification_receipt_authority_required")
            return current

    def drop(identity: int, dead: ReferenceType[SemanticVerificationReceipt]) -> None:
        with authority_lock:
            sealed = dict.get(shadow, identity)
            if type(sealed) is tuple and sealed and tuple.__getitem__(sealed, 0) is dead:
                dict.pop(visible, identity, None)
                dict.pop(shadow, identity, None)

    return register, read, drop


(
    _register_semantic_receipt_authority,
    _read_semantic_receipt_authority,
    _drop_semantic_receipt_authority,
) = _build_semantic_receipt_accessors(_ISSUED_SEMANTIC_RECEIPT_AUTHORITIES)


def _validate_semantic_verifier_protocol(
    verifier: _ComponentAuthority,
) -> None:
    _validate_component_authority(verifier)
    component = object.__getattribute__(verifier, "component")
    if component is None:
        return
    method = object.__getattribute__(verifier, "method")
    code = object.__getattribute__(verifier, "method_code")
    if (
        type(method) is not FunctionType
        or type(code) is not CodeType
        or object.__getattribute__(method, "__defaults__") is not None
        or object.__getattribute__(method, "__kwdefaults__") is not None
        or object.__getattribute__(code, "co_argcount") != 2
        or object.__getattribute__(code, "co_posonlyargcount") != 0
        or object.__getattribute__(code, "co_kwonlyargcount") != 0
        or object.__getattribute__(code, "co_flags") & 0x0C
    ):
        raise ValueError("semantic_verifier_protocol_mismatch")


def _semantic_verifier_request(
    *,
    obligation: SemanticVerificationObligation,
    authority: _SemanticVerificationObligationAuthority,
) -> _SemanticVerifierRequest:
    evidence = tuple(
        _SemanticVerifierEvidence._create(
            index=index,
            role=object.__getattribute__(authority, "roles")[index],
            doc_id=object.__getattribute__(item, "doc_id"),
            content_kind=object.__getattribute__(item, "kind"),
            content=object.__getattribute__(item, "text"),
            _token=_SEMANTIC_REQUEST_TOKEN,
        )
        for index, item in enumerate(object.__getattribute__(authority, "evidence"))
    )
    if any(
        item.index != index
        or item.role not in _SEMANTIC_ROLES
        or type(item.doc_id) is not str
        or not item.doc_id
        or type(item.content_kind) is not str
        or type(item.content) is not str
        for index, item in enumerate(evidence)
    ):
        raise ValueError("semantic_verifier_request_mismatch")
    auxiliary_parent_context = tuple(
        _SemanticVerifierParentContext._create(
            parent_id=object.__getattribute__(parent, "parent_id"),
            parent_kind=object.__getattribute__(parent, "kind"),
            doc_id=object.__getattribute__(parent, "doc_id"),
            content=object.__getattribute__(parent, "text"),
            _token=_SEMANTIC_REQUEST_TOKEN,
        )
        for parent in object.__getattribute__(authority, "auxiliary_parents")
    )
    return _SemanticVerifierRequest._create(
        source_kind=object.__getattribute__(obligation, "source_kind"),
        target_kind=object.__getattribute__(obligation, "target_kind"),
        obligation_key=object.__getattribute__(obligation, "obligation_key"),
        target_doc_id=object.__getattribute__(obligation, "target_doc_id"),
        field=object.__getattribute__(obligation, "field"),
        query=object.__getattribute__(authority, "raw_query"),
        evidence=evidence,
        auxiliary_parent_context=auxiliary_parent_context,
        _token=_SEMANTIC_REQUEST_TOKEN,
    )


def _mint_semantic_verification_receipt(
    *,
    obligation: SemanticVerificationObligation,
    authority: _SemanticVerificationObligationAuthority,
    projection: object | None,
    disposition: str,
    call_performed: bool,
    result_sha256: str,
    execution_key: tuple[object, ...],
) -> SemanticVerificationReceipt:
    runtime = object.__getattribute__(authority, "runtime")
    if projection is None:
        verified: tuple[str, ...] = ()
        contradicted: tuple[str, ...] = ()
        values: tuple[SemanticValueSupport, ...] = ()
    else:
        if type(projection) is not _ISSUED_ACTION_EFFECTS_PROJECTION_CLASS:
            raise ValueError("semantic_verifier_projection_mismatch")
        verified = object.__getattribute__(projection, "verified_evidence_ids")
        contradicted = object.__getattribute__(
            projection, "contradicted_evidence_ids"
        )
        values = object.__getattribute__(projection, "values")
    payload = {
        "stage": "semantic_verification",
        "source_kind": object.__getattribute__(obligation, "source_kind"),
        "target_kind": object.__getattribute__(obligation, "target_kind"),
        "obligation_key": object.__getattribute__(obligation, "obligation_key"),
        "target_doc_id": object.__getattribute__(obligation, "target_doc_id"),
        "field": object.__getattribute__(obligation, "field"),
        "semantic_obligation_sha256": object.__getattribute__(
            obligation, "obligation_sha256"
        ),
        "owner_binding_sha256": object.__getattribute__(
            obligation, "owner_binding_sha256"
        ),
        "candidate_receipt_sha256": object.__getattribute__(
            obligation, "candidate_receipt_sha256"
        ),
        "query_sha256": object.__getattribute__(obligation, "query_sha256"),
        "evidence_store_sha256": object.__getattribute__(
            obligation, "evidence_store_sha256"
        ),
        "execution_config_sha256": object.__getattribute__(
            obligation, "execution_config_sha256"
        ),
        "runtime_binding_sha256": object.__getattribute__(
            obligation, "runtime_binding_sha256"
        ),
        "verifier_id": object.__getattribute__(runtime, "verifier_id"),
        "verifier_implementation_sha256": object.__getattribute__(
            runtime, "verifier_implementation_sha256"
        ),
        "verifier_config_sha256": object.__getattribute__(
            runtime, "verifier_config_sha256"
        ),
        "supplied_evidence_ids": object.__getattribute__(
            obligation, "supplied_evidence_ids"
        ),
        "ordered_stable_anchors": object.__getattribute__(
            obligation, "ordered_stable_anchors"
        ),
        "disposition": disposition,
        "verified_evidence_ids": verified,
        "contradicted_evidence_ids": contradicted,
        "values": values,
        "call_performed": call_performed,
        "result_sha256": result_sha256,
    }
    temporary = object.__new__(SemanticVerificationReceipt)
    for name, value in payload.items():
        object.__setattr__(temporary, name, value)
    object.__setattr__(temporary, "receipt_sha256", "0" * 64)
    payload["receipt_sha256"] = _canonical_sha256(
        _semantic_verification_receipt_payload(temporary, include_hash=False)
    )
    receipt = SemanticVerificationReceipt._create(
        payload=payload, _token=_SEMANTIC_RECEIPT_TOKEN
    )
    identity = id(receipt)
    weak = ref(
        receipt,
        lambda dead, identity=identity: _drop_semantic_receipt_authority(
            identity, dead
        ),
    )
    _register_semantic_receipt_authority(
        receipt,
        _SemanticVerificationReceiptAuthority(
            weak=weak,
            obligation=obligation,
            store=object.__getattribute__(authority, "store"),
            config=object.__getattribute__(authority, "config"),
            runtime=runtime,
            projection=projection,
            execution_key=execution_key,
            issued_payload_sha256=_canonical_sha256(receipt.to_dict()),
        ),
    )
    return receipt


def execute_semantic_verification(
    *,
    obligation: SemanticVerificationObligation,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    _dependency_checker=None,
    _dependency_checker_code=None,
) -> SemanticVerificationReceipt:
    """Execute one exact semantic verifier attempt.

    This entry remains module-visible but is intentionally not re-exported from
    ``midprojectrag.orchestration`` until the EH2.6.d deadline/action permit owns
    production ordering.
    """

    _semantic_public_entry(_dependency_checker, _dependency_checker_code)
    _validate_action_effects_dependency()
    authority = _validate_semantic_verification_obligation_exact(
        obligation=obligation, store=store, config=config, runtime=runtime
    )
    verifier = object.__getattribute__(authority, "verifier_authority")
    _validate_semantic_verifier_protocol(verifier)
    execution_key = _semantic_execution_key(authority, obligation)
    derivation_kind = object.__getattribute__(obligation, "derivation_kind")
    route_key = object.__getattribute__(authority, "route_key")
    is_base = derivation_kind == "base"
    if is_base:
        if _semantic_execution_status(execution_key) is not None:
            raise ValueError("semantic_verification_already_consumed")
        _claim_base_semantic_route(
            object.__getattribute__(authority, "source"), route_key
        )
    elif _semantic_route_status(route_key) != "rerank_consumed":
        raise ValueError("semantic_derived_route_not_ready")
    _transition_semantic_execution(execution_key, None, "pending")
    if object.__getattribute__(verifier, "component") is None:
        result_sha256 = _canonical_sha256(
            {
                "schema_version": SCHEMA_VERSION,
                "disposition": "unavailable",
                "semantic_obligation_sha256": object.__getattribute__(
                    obligation, "obligation_sha256"
                ),
            }
        )
        try:
            receipt = _mint_semantic_verification_receipt(
                obligation=obligation,
                authority=authority,
                projection=None,
                disposition="unavailable",
                call_performed=False,
                result_sha256=result_sha256,
                execution_key=execution_key,
            )
        except Exception:
            _transition_semantic_execution(execution_key, "pending", "failed")
            if is_base:
                _complete_base_semantic_route(route_key)
            raise ValueError("semantic_verifier_contract_error") from None
        _transition_semantic_execution(execution_key, "pending", "completed")
        if is_base:
            _complete_base_semantic_route(route_key)
        return receipt
    request = _semantic_verifier_request(
        obligation=obligation, authority=authority
    )
    try:
        raw_result = object.__getattribute__(verifier, "method")(
            object.__getattribute__(verifier, "component"), request
        )
    except Exception:
        _transition_semantic_execution(execution_key, "pending", "failed")
        if is_base:
            _complete_base_semantic_route(route_key)
        raise ValueError("semantic_verifier_provider_error") from None
    try:
        _semantic_public_entry(_dependency_checker, _dependency_checker_code)
        _validate_action_effects_dependency()
        authority_after = _validate_semantic_verification_obligation_exact(
            obligation=obligation, store=store, config=config, runtime=runtime
        )
        if authority_after is not authority:
            raise ValueError("semantic_verification_obligation_authority_drift")
        projection = _ISSUED_ACTION_EFFECTS_NORMALIZER(
            raw_result,
            field=object.__getattribute__(obligation, "field"),
            ordered_supplied_ids=object.__getattribute__(
                obligation, "supplied_evidence_ids"
            ),
            promotable_ids=(
                object.__getattribute__(obligation, "supplied_evidence_ids")
                if derivation_kind == "reranked"
                else (
                    object.__getattribute__(obligation, "candidate_evidence_ids")
                    + object.__getattribute__(obligation, "bridge_evidence_ids")
                )
            ),
        )
    except Exception:
        _transition_semantic_execution(execution_key, "pending", "failed")
        if is_base:
            _complete_base_semantic_route(route_key)
        raise ValueError("semantic_verifier_contract_error") from None
    disposition = object.__getattribute__(projection, "disposition")
    result_sha256 = object.__getattribute__(projection, "result_sha256")
    try:
        receipt = _mint_semantic_verification_receipt(
            obligation=obligation,
            authority=authority,
            projection=projection,
            disposition=disposition,
            call_performed=True,
            result_sha256=result_sha256,
            execution_key=execution_key,
        )
    except Exception:
        _transition_semantic_execution(execution_key, "pending", "failed")
        if is_base:
            _complete_base_semantic_route(route_key)
        raise ValueError("semantic_verifier_contract_error") from None
    _transition_semantic_execution(execution_key, "pending", "completed")
    if is_base:
        _complete_base_semantic_route(route_key)
    return receipt


def validate_semantic_verification_receipt(
    *,
    receipt: SemanticVerificationReceipt,
    obligation: SemanticVerificationObligation,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    _dependency_checker=None,
    _dependency_checker_code=None,
) -> None:
    _semantic_public_entry(_dependency_checker, _dependency_checker_code)
    _validate_action_effects_dependency()
    obligation_authority = _validate_semantic_verification_obligation_exact(
        obligation=obligation, store=store, config=config, runtime=runtime
    )
    _validate_semantic_verification_receipt_payload(receipt)
    authority = _read_semantic_receipt_authority(receipt)
    execution_key = _semantic_execution_key(obligation_authority, obligation)
    if (
        object.__getattribute__(authority, "obligation") is not obligation
        or object.__getattribute__(authority, "store") is not store
        or object.__getattribute__(authority, "config") is not config
        or object.__getattribute__(authority, "runtime") is not runtime
        or object.__getattribute__(authority, "execution_key") != execution_key
        or _semantic_execution_status(execution_key) != "completed"
    ):
        raise ValueError("semantic_verification_receipt_dependency_identity_mismatch")
    if object.__getattribute__(authority, "issued_payload_sha256") != _canonical_sha256(
        receipt.to_dict()
    ):
        raise ValueError("semantic_verification_receipt_authority_drift")
    for receipt_name, obligation_name in (
        ("semantic_obligation_sha256", "obligation_sha256"),
        ("owner_binding_sha256", "owner_binding_sha256"),
        ("candidate_receipt_sha256", "candidate_receipt_sha256"),
        ("query_sha256", "query_sha256"),
        ("evidence_store_sha256", "evidence_store_sha256"),
        ("execution_config_sha256", "execution_config_sha256"),
        ("runtime_binding_sha256", "runtime_binding_sha256"),
        ("supplied_evidence_ids", "supplied_evidence_ids"),
        ("ordered_stable_anchors", "ordered_stable_anchors"),
    ):
        if object.__getattribute__(receipt, receipt_name) != object.__getattribute__(
            obligation, obligation_name
        ):
            raise ValueError("semantic_verification_receipt_obligation_mismatch")
    projection = object.__getattribute__(authority, "projection")
    if projection is None:
        if object.__getattribute__(receipt, "disposition") != "unavailable":
            raise ValueError("semantic_verification_receipt_projection_mismatch")
    elif (
        type(projection) is not _ISSUED_ACTION_EFFECTS_PROJECTION_CLASS
        or object.__getattribute__(receipt, "disposition")
        != object.__getattribute__(projection, "disposition")
        or object.__getattribute__(receipt, "verified_evidence_ids")
        is not object.__getattribute__(projection, "verified_evidence_ids")
        or object.__getattribute__(receipt, "contradicted_evidence_ids")
        is not object.__getattribute__(projection, "contradicted_evidence_ids")
        or object.__getattribute__(receipt, "values")
        is not object.__getattribute__(projection, "values")
        or object.__getattribute__(receipt, "result_sha256")
        != object.__getattribute__(projection, "result_sha256")
    ):
        raise ValueError("semantic_verification_receipt_projection_mismatch")


# EH2.6.c3.3 bounded absence confirmation ------------------------------------

_ABSENCE_REASONS = frozenset(
    {
        "bounded_no_candidate",
        "bounded_no_verified_support",
        "followup_approved_paths_exhausted",
    }
)


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class AbsenceConfirmationReceipt:
    """Content-free proof that one bounded obligation exhausted its paths."""

    stage: str
    source_kind: str
    reason: str
    execution_kind: str
    obligation_key: str
    owner_binding_sha256: str
    owner_plan_sha256: str
    owner_plan_config_sha256: str
    owner_budget_sha256: str
    source_receipt_sha256: str
    query_sha256: str
    scope_doc_ids: tuple[str, ...]
    scope_sha256: str
    evidence_store_sha256: str
    execution_config_sha256: str
    runtime_binding_sha256: str
    retrieval_obligation_sha256: str | None
    dense_receipt_sha256: str | None
    lexical_receipt_sha256: str | None
    fusion_receipt_sha256: str | None
    semantic_obligation_sha256: str | None
    semantic_receipt_sha256: str | None
    followup_outcome_sha256: str | None
    primary_receipt_sha256: str | None
    fallback_receipt_sha256: str | None
    fallback_authorized: bool | None
    fallback_executed: bool | None
    candidate_count: int
    supplied_count: int
    support_count: int
    call_performed: bool
    prerequisite_sha256: str
    receipt_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("absence_confirmation_receipt_factory_required")

    def __copy__(self) -> object:
        raise TypeError("absence_confirmation_receipt_not_serializable")

    def __deepcopy__(self, memo: object) -> object:
        raise TypeError("absence_confirmation_receipt_not_serializable")

    def __reduce__(self) -> object:
        raise TypeError("absence_confirmation_receipt_not_serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        raise TypeError("absence_confirmation_receipt_not_serializable")

    @classmethod
    def _create(
        cls,
        *,
        payload: Mapping[str, Any],
        _token: object,
    ) -> AbsenceConfirmationReceipt:
        if _token is not _ABSENCE_CONFIRMATION_TOKEN:
            raise ValueError("absence_confirmation_receipt_factory_required")
        result = object.__new__(cls)
        for name in cls.__slots__:
            if name != "__weakref__":
                object.__setattr__(result, name, payload[name])
        _validate_absence_confirmation_receipt_payload(result)
        return result

    def to_dict(self) -> dict[str, Any]:
        _validate_absence_confirmation_receipt_payload(self)
        return _absence_confirmation_receipt_payload(self, include_hash=True)


def _absence_confirmation_receipt_payload(
    receipt: AbsenceConfirmationReceipt,
    *,
    include_hash: bool,
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        **{
            name: (
                list(value)
                if name == "scope_doc_ids"
                else value
            )
            for name, value in (
                ("stage", object.__getattribute__(receipt, "stage")),
                ("source_kind", object.__getattribute__(receipt, "source_kind")),
                ("reason", object.__getattribute__(receipt, "reason")),
                ("execution_kind", object.__getattribute__(receipt, "execution_kind")),
                ("obligation_key", object.__getattribute__(receipt, "obligation_key")),
                ("owner_binding_sha256", object.__getattribute__(receipt, "owner_binding_sha256")),
                ("owner_plan_sha256", object.__getattribute__(receipt, "owner_plan_sha256")),
                ("owner_plan_config_sha256", object.__getattribute__(receipt, "owner_plan_config_sha256")),
                ("owner_budget_sha256", object.__getattribute__(receipt, "owner_budget_sha256")),
                ("source_receipt_sha256", object.__getattribute__(receipt, "source_receipt_sha256")),
                ("query_sha256", object.__getattribute__(receipt, "query_sha256")),
                ("scope_doc_ids", object.__getattribute__(receipt, "scope_doc_ids")),
                ("scope_sha256", object.__getattribute__(receipt, "scope_sha256")),
                ("evidence_store_sha256", object.__getattribute__(receipt, "evidence_store_sha256")),
                ("execution_config_sha256", object.__getattribute__(receipt, "execution_config_sha256")),
                ("runtime_binding_sha256", object.__getattribute__(receipt, "runtime_binding_sha256")),
                ("retrieval_obligation_sha256", object.__getattribute__(receipt, "retrieval_obligation_sha256")),
                ("dense_receipt_sha256", object.__getattribute__(receipt, "dense_receipt_sha256")),
                ("lexical_receipt_sha256", object.__getattribute__(receipt, "lexical_receipt_sha256")),
                ("fusion_receipt_sha256", object.__getattribute__(receipt, "fusion_receipt_sha256")),
                ("semantic_obligation_sha256", object.__getattribute__(receipt, "semantic_obligation_sha256")),
                ("semantic_receipt_sha256", object.__getattribute__(receipt, "semantic_receipt_sha256")),
                ("followup_outcome_sha256", object.__getattribute__(receipt, "followup_outcome_sha256")),
                ("primary_receipt_sha256", object.__getattribute__(receipt, "primary_receipt_sha256")),
                ("fallback_receipt_sha256", object.__getattribute__(receipt, "fallback_receipt_sha256")),
                ("fallback_authorized", object.__getattribute__(receipt, "fallback_authorized")),
                ("fallback_executed", object.__getattribute__(receipt, "fallback_executed")),
                ("candidate_count", object.__getattribute__(receipt, "candidate_count")),
                ("supplied_count", object.__getattribute__(receipt, "supplied_count")),
                ("support_count", object.__getattribute__(receipt, "support_count")),
                ("call_performed", object.__getattribute__(receipt, "call_performed")),
                ("prerequisite_sha256", object.__getattribute__(receipt, "prerequisite_sha256")),
            )
        },
    }
    if include_hash:
        payload["receipt_sha256"] = object.__getattribute__(receipt, "receipt_sha256")
    return payload


def _validate_absence_confirmation_receipt_payload(
    receipt: AbsenceConfirmationReceipt,
) -> None:
    if type(receipt) is not AbsenceConfirmationReceipt:
        raise TypeError("absence_confirmation_receipt_required")
    source_kind = object.__getattribute__(receipt, "source_kind")
    reason = object.__getattribute__(receipt, "reason")
    if (
        object.__getattribute__(receipt, "stage") != "absence_confirmation"
        or source_kind not in _SEMANTIC_SOURCE_KINDS
        or reason not in _ABSENCE_REASONS
        or object.__getattribute__(receipt, "execution_kind") not in {"production", "synthetic"}
        or type(object.__getattribute__(receipt, "obligation_key")) is not str
        or not object.__getattribute__(receipt, "obligation_key")
    ):
        raise ValueError("invalid_absence_confirmation_identity")
    for name in (
        "owner_binding_sha256", "owner_plan_sha256", "owner_plan_config_sha256",
        "owner_budget_sha256", "source_receipt_sha256", "query_sha256",
        "scope_sha256", "evidence_store_sha256", "execution_config_sha256",
        "runtime_binding_sha256", "prerequisite_sha256", "receipt_sha256",
    ):
        _require_hash(object.__getattribute__(receipt, name), f"invalid_absence_{name}")
    for name in (
        "retrieval_obligation_sha256", "dense_receipt_sha256",
        "lexical_receipt_sha256", "fusion_receipt_sha256",
        "semantic_obligation_sha256", "semantic_receipt_sha256",
        "followup_outcome_sha256", "primary_receipt_sha256",
        "fallback_receipt_sha256",
    ):
        value = object.__getattribute__(receipt, name)
        if value is not None:
            _require_hash(value, f"invalid_absence_{name}")
    scope_doc_ids = object.__getattribute__(receipt, "scope_doc_ids")
    if not _exact_string_tuple(scope_doc_ids) or len(scope_doc_ids) != len(set(scope_doc_ids)):
        raise ValueError("invalid_absence_scope_projection")
    counts = tuple(
        object.__getattribute__(receipt, name)
        for name in ("candidate_count", "supplied_count", "support_count")
    )
    if any(type(value) is not int or value < 0 for value in counts):
        raise ValueError("invalid_absence_confirmation_count")
    retrieval_proof = tuple(
        object.__getattribute__(receipt, name)
        for name in (
            "retrieval_obligation_sha256", "dense_receipt_sha256",
            "lexical_receipt_sha256", "fusion_receipt_sha256",
        )
    )
    semantic_proof = tuple(
        object.__getattribute__(receipt, name)
        for name in ("semantic_obligation_sha256", "semantic_receipt_sha256")
    )
    followup_proof = tuple(
        object.__getattribute__(receipt, name)
        for name in ("followup_outcome_sha256", "primary_receipt_sha256")
    )
    fallback_authorized = object.__getattribute__(receipt, "fallback_authorized")
    fallback_executed = object.__getattribute__(receipt, "fallback_executed")
    fallback_proof = object.__getattribute__(receipt, "fallback_receipt_sha256")
    if reason == "bounded_no_candidate":
        valid_matrix = (
            source_kind in _RETRIEVAL_SOURCE_KINDS
            and all(value is not None for value in retrieval_proof)
            and all(value is None for value in semantic_proof + followup_proof)
            and fallback_proof is None
            and fallback_authorized is None
            and fallback_executed is None
            and counts == (0, 0, 0)
        )
    elif reason == "bounded_no_verified_support":
        valid_matrix = (
            all(value is None for value in retrieval_proof + followup_proof)
            and all(value is not None for value in semantic_proof)
            and fallback_proof is None
            and fallback_authorized is None
            and fallback_executed is None
            and counts[1] > 0
            and counts[2] == 0
        )
    else:
        valid_matrix = (
            source_kind == "follow_up"
            and all(value is None for value in retrieval_proof + semantic_proof)
            and all(value is not None for value in followup_proof)
            and type(fallback_authorized) is bool
            and type(fallback_executed) is bool
            and fallback_executed is fallback_authorized
            and (fallback_proof is not None) is fallback_authorized
            and counts == (0, 0, 0)
        )
    if not valid_matrix or object.__getattribute__(receipt, "call_performed") is not False:
        raise ValueError("absence_confirmation_proof_matrix_mismatch")
    if object.__getattribute__(receipt, "receipt_sha256") != _canonical_sha256(
        _absence_confirmation_receipt_payload(receipt, include_hash=False)
    ):
        raise ValueError("absence_confirmation_receipt_hash_mismatch")


@dataclass(frozen=True, slots=True)
class _AbsenceConfirmationAuthority:
    receipt: AbsenceConfirmationReceipt
    root_weak: ReferenceType[object]
    prerequisite_weaks: tuple[ReferenceType[object], ...]
    prerequisite_payload_sha256s: tuple[str, ...]
    store_weak: ReferenceType[EvidenceStore]
    config_weak: ReferenceType[HarnessExecutionConfig]
    runtime_weak: ReferenceType[HarnessRuntimeBinding]
    root_payload_sha256: str
    owner_projection: tuple[str, str, str, str]
    issued_payload_sha256: str


_ABSENCE_CONFIRMATION_AUTHORITIES: dict[tuple[object, ...], _AbsenceConfirmationAuthority] = {}
_ISSUED_ABSENCE_CONFIRMATION_AUTHORITIES = _ABSENCE_CONFIRMATION_AUTHORITIES


def _build_absence_confirmation_authority_accessors(
    visible: dict[tuple[object, ...], _AbsenceConfirmationAuthority],
) -> tuple[FunctionType, FunctionType, FunctionType, FunctionType]:
    """Seal the root-lifetime completion cache outside its visible audit map."""

    shadow: dict[tuple[object, ...], tuple[object, ...]] = {}
    known_keys: set[tuple[object, ...]] = set()
    authority_lock = Lock()

    def snapshot(authority: _AbsenceConfirmationAuthority) -> tuple[object, ...]:
        return tuple(
            object.__getattribute__(authority, name)
            for name in _AbsenceConfirmationAuthority.__slots__
        )

    def validated_unlocked(
        key: tuple[object, ...],
    ) -> _AbsenceConfirmationAuthority | None:
        current = dict.get(visible, key)
        sealed = dict.get(shadow, key)
        if current is None and sealed is None:
            if key in known_keys:
                raise ValueError("absence_confirmation_completion_authority_drift")
            return None
        if (
            type(current) is not _AbsenceConfirmationAuthority
            or type(sealed) is not tuple
            or len(sealed) != len(_AbsenceConfirmationAuthority.__slots__)
            or any(
                object.__getattribute__(current, name) is not value
                for name, value in zip(
                    _AbsenceConfirmationAuthority.__slots__, sealed
                )
            )
        ):
            raise ValueError("absence_confirmation_completion_authority_drift")
        return current

    def register_or_read(
        key: tuple[object, ...],
        authority: _AbsenceConfirmationAuthority,
    ) -> _AbsenceConfirmationAuthority:
        with authority_lock:
            current = validated_unlocked(key)
            if current is not None:
                return current
            if type(authority) is not _AbsenceConfirmationAuthority:
                raise TypeError("absence_confirmation_authority_required")
            values = snapshot(authority)
            dict.__setitem__(visible, key, authority)
            dict.__setitem__(shadow, key, values)
            known_keys.add(key)
            return authority

    def read(
        key: tuple[object, ...],
    ) -> _AbsenceConfirmationAuthority | None:
        with authority_lock:
            return validated_unlocked(key)

    def find(receipt: AbsenceConfirmationReceipt) -> _AbsenceConfirmationAuthority:
        with authority_lock:
            if set(visible) != set(shadow) or set(visible) != known_keys:
                raise ValueError("absence_confirmation_completion_authority_drift")
            matched = None
            for key in tuple(known_keys):
                current = validated_unlocked(key)
                if current is not None and object.__getattribute__(current, "receipt") is receipt:
                    if matched is not None:
                        raise ValueError("absence_confirmation_completion_authority_drift")
                    matched = current
            if matched is None:
                raise ValueError("absence_confirmation_runtime_authority_required")
            return matched

    def drop_root(root_identity: int, dead: ReferenceType[object]) -> None:
        with authority_lock:
            for key in tuple(known_keys):
                current = validated_unlocked(key)
                if (
                    current is not None
                    and tuple.__getitem__(key, 0) == root_identity
                    and object.__getattribute__(current, "root_weak") is dead
                ):
                    dict.pop(visible, key)
                    dict.pop(shadow, key)
                    known_keys.remove(key)

    return register_or_read, read, find, drop_root


(
    _register_or_read_absence_confirmation_authority,
    _read_absence_confirmation_authority,
    _find_absence_confirmation_authority,
    _drop_absence_confirmation_root,
) = _build_absence_confirmation_authority_accessors(
    _ISSUED_ABSENCE_CONFIRMATION_AUTHORITIES
)


def _mint_absence_confirmation_receipt(payload: Mapping[str, Any]) -> AbsenceConfirmationReceipt:
    temporary = object.__new__(AbsenceConfirmationReceipt)
    for name, value in payload.items():
        object.__setattr__(temporary, name, value)
    object.__setattr__(temporary, "receipt_sha256", "0" * 64)
    sealed = dict(payload)
    sealed["receipt_sha256"] = _canonical_sha256(
        _absence_confirmation_receipt_payload(temporary, include_hash=False)
    )
    return AbsenceConfirmationReceipt._create(
        payload=sealed, _token=_ABSENCE_CONFIRMATION_TOKEN
    )


def _absence_owner_projection(root: object) -> tuple[str, str, str, str, str, tuple[str, ...], str]:
    plan = object.__getattribute__(root, "plan")
    binding_sha256 = object.__getattribute__(root, "binding_sha256")
    plan_sha256 = _canonical_sha256(plan.to_dict())
    plan_config_sha256 = object.__getattribute__(plan, "config_sha256")
    budget_sha256 = _canonical_sha256(object.__getattribute__(plan, "budget").to_dict())
    query_sha256 = _query_sha256(object.__getattribute__(plan, "normalized_query"))
    scope_doc_ids = object.__getattribute__(plan, "resolved_doc_ids")
    scope_sha256 = _canonical_sha256(
        {
            "schema_version": SCHEMA_VERSION,
            "state": object.__getattribute__(plan, "scope_state"),
            "origin": object.__getattribute__(plan, "scope_origin"),
            "doc_ids": list(scope_doc_ids),
        }
    )
    for value, code in (
        (binding_sha256, "invalid_absence_owner_binding"),
        (plan_config_sha256, "invalid_absence_owner_plan_config"),
    ):
        _require_hash(value, code)
    return (
        binding_sha256, plan_sha256, plan_config_sha256, budget_sha256,
        query_sha256, scope_doc_ids, scope_sha256,
    )


def _validate_cached_absence_confirmation_authority(
    *,
    authority: _AbsenceConfirmationAuthority,
    root: object,
    prerequisites: tuple[object, ...],
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    payload: Mapping[str, Any],
) -> AbsenceConfirmationReceipt:
    if type(authority) is not _AbsenceConfirmationAuthority:
        raise TypeError("absence_confirmation_authority_required")
    receipt = object.__getattribute__(authority, "receipt")
    _validate_absence_confirmation_receipt_payload(receipt)
    prerequisite_weaks = object.__getattribute__(authority, "prerequisite_weaks")
    prerequisite_hashes = object.__getattribute__(
        authority, "prerequisite_payload_sha256s"
    )
    if (
        object.__getattribute__(authority, "root_weak")() is not root
        or object.__getattribute__(authority, "store_weak")() is not store
        or object.__getattribute__(authority, "config_weak")() is not config
        or object.__getattribute__(authority, "runtime_weak")() is not runtime
        or type(prerequisite_weaks) is not tuple
        or type(prerequisite_hashes) is not tuple
        or len(prerequisite_weaks) != len(prerequisites)
        or len(prerequisite_hashes) != len(prerequisites)
        or any(
            weak() is not item
            or _canonical_sha256(item.to_dict()) != prerequisite_hashes[index]
            for index, (weak, item) in enumerate(
                zip(prerequisite_weaks, prerequisites)
            )
        )
        or object.__getattribute__(authority, "root_payload_sha256")
        != _canonical_sha256(root.to_dict())
        or object.__getattribute__(authority, "owner_projection")
        != tuple(
            payload[name]
            for name in (
                "owner_binding_sha256",
                "owner_plan_sha256",
                "owner_plan_config_sha256",
                "owner_budget_sha256",
            )
        )
        or any(
            object.__getattribute__(receipt, name) != value
            for name, value in payload.items()
        )
        or object.__getattribute__(authority, "issued_payload_sha256")
        != _canonical_sha256(receipt.to_dict())
    ):
        raise ValueError("absence_confirmation_completion_authority_drift")
    return receipt


def _register_or_read_absence_confirmation(
    *,
    root: object,
    prerequisites: tuple[object, ...],
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
    payload: Mapping[str, Any],
) -> AbsenceConfirmationReceipt:
    prerequisite_sha256 = payload["prerequisite_sha256"]
    key = (
        id(root), payload["obligation_key"], payload["reason"], prerequisite_sha256,
        id(store), id(config), id(runtime),
    )
    cached = _read_absence_confirmation_authority(key)
    if cached is not None:
        return _validate_cached_absence_confirmation_authority(
            authority=cached,
            root=root,
            prerequisites=prerequisites,
            store=store,
            config=config,
            runtime=runtime,
            payload=payload,
        )
    receipt = _mint_absence_confirmation_receipt(payload)
    root_identity = id(root)
    root_weak = ref(
        root,
        lambda dead, root_identity=root_identity: _drop_absence_confirmation_root(
            root_identity, dead
        ),
    )
    authority = _AbsenceConfirmationAuthority(
        receipt=receipt,
        root_weak=root_weak,
        prerequisite_weaks=tuple(ref(item) for item in prerequisites),
        prerequisite_payload_sha256s=tuple(
            _canonical_sha256(item.to_dict()) for item in prerequisites
        ),
        store_weak=ref(store),
        config_weak=ref(config),
        runtime_weak=ref(runtime),
        root_payload_sha256=_canonical_sha256(root.to_dict()),
        owner_projection=tuple(
            payload[name]
            for name in (
                "owner_binding_sha256",
                "owner_plan_sha256",
                "owner_plan_config_sha256",
                "owner_budget_sha256",
            )
        ),
        issued_payload_sha256=_canonical_sha256(receipt.to_dict()),
    )
    current = _register_or_read_absence_confirmation_authority(key, authority)
    return _validate_cached_absence_confirmation_authority(
        authority=current,
        root=root,
        prerequisites=prerequisites,
        store=store,
        config=config,
        runtime=runtime,
        payload=payload,
    )


def issue_retrieval_absence_confirmation(
    *,
    obligation: RetrievalObligation,
    dense_receipt: LaneSearchReceipt,
    lexical_receipt: LaneSearchReceipt,
    fusion_receipt: FusionReceipt,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
) -> AbsenceConfirmationReceipt:
    """Issue ``bounded_no_candidate`` from one exact normal-empty lane pair."""

    _ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER()
    validate_fusion_receipt(
        receipt=fusion_receipt,
        obligation=obligation,
        dense_receipt=dense_receipt,
        lexical_receipt=lexical_receipt,
        store=store,
        config=config,
        runtime=runtime,
    )
    if (
        object.__getattribute__(dense_receipt, "outcome") != "empty"
        or object.__getattribute__(lexical_receipt, "outcome") != "empty"
        or object.__getattribute__(fusion_receipt, "outcome") != "empty"
        or object.__getattribute__(dense_receipt, "candidate_count") != 0
        or object.__getattribute__(lexical_receipt, "candidate_count") != 0
        or object.__getattribute__(fusion_receipt, "candidate_count") != 0
    ):
        raise ValueError("retrieval_absence_requires_normal_empty_fusion")
    retrieval_authority = _require_retrieval_obligation_authority(obligation)
    root = object.__getattribute__(retrieval_authority, "source")
    owner = _absence_owner_projection(root)
    projected = object.__getattribute__(retrieval_authority, "source_projector")(
        bound=root, store=store
    )
    projections = _normalized_owner_projections(
        source_kind=object.__getattribute__(obligation, "source_kind"),
        projected=projected,
    )
    source_projection = projections[
        object.__getattribute__(retrieval_authority, "projection_ordinal") - 1
    ]
    if (
        source_projection["obligation_key"]
        != object.__getattribute__(obligation, "obligation_key")
        or _query_sha256(source_projection["query"])
        != object.__getattribute__(obligation, "query_sha256")
        or source_projection["scope_doc_ids"]
        != object.__getattribute__(obligation, "scope_doc_ids")
        or source_projection["source_receipt_sha256"]
        != object.__getattribute__(obligation, "source_receipt_sha256")
    ):
        raise ValueError("retrieval_absence_owner_projection_mismatch")
    prerequisite_sha256 = _canonical_sha256(
        {
            "schema_version": SCHEMA_VERSION,
            "reason": "bounded_no_candidate",
            "retrieval_obligation_sha256": object.__getattribute__(obligation, "obligation_sha256"),
            "dense_receipt_sha256": object.__getattribute__(dense_receipt, "receipt_sha256"),
            "lexical_receipt_sha256": object.__getattribute__(lexical_receipt, "receipt_sha256"),
            "fusion_receipt_sha256": object.__getattribute__(fusion_receipt, "receipt_sha256"),
        }
    )
    payload = {
        "stage": "absence_confirmation",
        "source_kind": object.__getattribute__(obligation, "source_kind"),
        "reason": "bounded_no_candidate",
        "execution_kind": object.__getattribute__(obligation, "execution_kind"),
        "obligation_key": object.__getattribute__(obligation, "obligation_key"),
        "owner_binding_sha256": owner[0],
        "owner_plan_sha256": owner[1],
        "owner_plan_config_sha256": owner[2],
        "owner_budget_sha256": owner[3],
        "source_receipt_sha256": object.__getattribute__(obligation, "source_receipt_sha256"),
        "query_sha256": object.__getattribute__(obligation, "query_sha256"),
        "scope_doc_ids": object.__getattribute__(obligation, "scope_doc_ids"),
        "scope_sha256": object.__getattribute__(obligation, "scope_sha256"),
        "evidence_store_sha256": object.__getattribute__(store, "bundle_sha256"),
        "execution_config_sha256": object.__getattribute__(config, "config_sha256"),
        "runtime_binding_sha256": object.__getattribute__(runtime, "binding_sha256"),
        "retrieval_obligation_sha256": object.__getattribute__(obligation, "obligation_sha256"),
        "dense_receipt_sha256": object.__getattribute__(dense_receipt, "receipt_sha256"),
        "lexical_receipt_sha256": object.__getattribute__(lexical_receipt, "receipt_sha256"),
        "fusion_receipt_sha256": object.__getattribute__(fusion_receipt, "receipt_sha256"),
        "semantic_obligation_sha256": None,
        "semantic_receipt_sha256": None,
        "followup_outcome_sha256": None,
        "primary_receipt_sha256": None,
        "fallback_receipt_sha256": None,
        "fallback_authorized": None,
        "fallback_executed": None,
        "candidate_count": 0,
        "supplied_count": 0,
        "support_count": 0,
        "call_performed": False,
        "prerequisite_sha256": prerequisite_sha256,
    }
    return _register_or_read_absence_confirmation(
        root=root,
        prerequisites=(obligation, dense_receipt, lexical_receipt, fusion_receipt),
        store=store,
        config=config,
        runtime=runtime,
        payload=payload,
    )


def issue_semantic_absence_confirmation(
    *,
    obligation: SemanticVerificationObligation,
    receipt: SemanticVerificationReceipt,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
) -> AbsenceConfirmationReceipt:
    """Issue ``bounded_no_verified_support`` from an actual derived verify."""

    _ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER()
    if type(obligation) is not SemanticVerificationObligation:
        raise TypeError("semantic_verification_obligation_required")
    if type(receipt) is not SemanticVerificationReceipt:
        raise TypeError("semantic_verification_receipt_required")
    validate_semantic_verification_receipt(
        receipt=receipt,
        obligation=obligation,
        store=store,
        config=config,
        runtime=runtime,
    )
    if (
        object.__getattribute__(obligation, "derivation_kind") != "reranked"
        or object.__getattribute__(receipt, "disposition") != "unsupported"
        or object.__getattribute__(receipt, "call_performed") is not True
        or not object.__getattribute__(obligation, "supplied_evidence_ids")
        or object.__getattribute__(receipt, "verified_evidence_ids")
        or object.__getattribute__(receipt, "contradicted_evidence_ids")
        or object.__getattribute__(receipt, "values")
    ):
        raise ValueError("semantic_absence_requires_called_derived_unsupported")
    semantic_authority = _validate_semantic_verification_obligation_exact(
        obligation=obligation, store=store, config=config, runtime=runtime
    )
    receipt_authority = _read_semantic_receipt_authority(receipt)
    if object.__getattribute__(receipt_authority, "obligation") is not obligation:
        raise ValueError("semantic_absence_lineage_mismatch")
    root = object.__getattribute__(semantic_authority, "source")
    planning = object.__getattribute__(root, "planning")
    owner_plan = object.__getattribute__(planning, "plan")
    owner_plan_sha256 = _canonical_sha256(owner_plan.to_dict())
    owner_plan_config_sha256 = object.__getattribute__(owner_plan, "config_sha256")
    retrieval = object.__getattribute__(semantic_authority, "retrieval_obligation")
    expected_owner_binding_sha256 = (
        object.__getattribute__(root, "binding_sha256")
        if retrieval is None
        else object.__getattribute__(retrieval, "execution_binding_sha256")
    )
    if (
        owner_plan_sha256
        != object.__getattribute__(obligation, "owner_plan_sha256")
        or owner_plan_config_sha256
        != object.__getattribute__(obligation, "owner_plan_config_sha256")
        or expected_owner_binding_sha256
        != object.__getattribute__(obligation, "owner_binding_sha256")
    ):
        raise ValueError("semantic_absence_owner_projection_mismatch")
    if retrieval is not None:
        scope_doc_ids = object.__getattribute__(retrieval, "scope_doc_ids")
        scope_sha256 = object.__getattribute__(retrieval, "scope_sha256")
    else:
        scope_doc_ids = object.__getattribute__(owner_plan, "resolved_doc_ids")
        scope_sha256 = _canonical_sha256(
            {
                "schema_version": SCHEMA_VERSION,
                "state": object.__getattribute__(owner_plan, "scope_state"),
                "origin": object.__getattribute__(owner_plan, "scope_origin"),
                "doc_ids": list(scope_doc_ids),
            }
        )
    prerequisite_sha256 = _canonical_sha256(
        {
            "schema_version": SCHEMA_VERSION,
            "reason": "bounded_no_verified_support",
            "semantic_obligation_sha256": object.__getattribute__(obligation, "obligation_sha256"),
            "semantic_receipt_sha256": object.__getattribute__(receipt, "receipt_sha256"),
        }
    )
    payload = {
        "stage": "absence_confirmation",
        "source_kind": object.__getattribute__(obligation, "source_kind"),
        "reason": "bounded_no_verified_support",
        "execution_kind": object.__getattribute__(obligation, "execution_kind"),
        "obligation_key": object.__getattribute__(obligation, "obligation_key"),
        "owner_binding_sha256": object.__getattribute__(obligation, "owner_binding_sha256"),
        "owner_plan_sha256": owner_plan_sha256,
        "owner_plan_config_sha256": owner_plan_config_sha256,
        "owner_budget_sha256": _canonical_sha256(object.__getattribute__(owner_plan, "budget").to_dict()),
        "source_receipt_sha256": object.__getattribute__(obligation, "candidate_receipt_sha256"),
        "query_sha256": object.__getattribute__(obligation, "query_sha256"),
        "scope_doc_ids": scope_doc_ids,
        "scope_sha256": scope_sha256,
        "evidence_store_sha256": object.__getattribute__(store, "bundle_sha256"),
        "execution_config_sha256": object.__getattribute__(config, "config_sha256"),
        "runtime_binding_sha256": object.__getattribute__(runtime, "binding_sha256"),
        "retrieval_obligation_sha256": None,
        "dense_receipt_sha256": None,
        "lexical_receipt_sha256": None,
        "fusion_receipt_sha256": None,
        "semantic_obligation_sha256": object.__getattribute__(obligation, "obligation_sha256"),
        "semantic_receipt_sha256": object.__getattribute__(receipt, "receipt_sha256"),
        "followup_outcome_sha256": None,
        "primary_receipt_sha256": None,
        "fallback_receipt_sha256": None,
        "fallback_authorized": None,
        "fallback_executed": None,
        "candidate_count": len(object.__getattribute__(obligation, "candidate_evidence_ids")),
        "supplied_count": len(object.__getattribute__(obligation, "supplied_evidence_ids")),
        "support_count": 0,
        "call_performed": False,
        "prerequisite_sha256": prerequisite_sha256,
    }
    return _register_or_read_absence_confirmation(
        root=root,
        prerequisites=(obligation, receipt),
        store=store,
        config=config,
        runtime=runtime,
        payload=payload,
    )


def issue_followup_absence_confirmation(
    *,
    bound: BoundFollowup,
    outcome: FollowupRetrievalOutcome,
    obligation_key: str,
    store: EvidenceStore,
    registry: RuleRegistry,
    policy: FollowupEvidencePolicy,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
) -> AbsenceConfirmationReceipt:
    """Issue exhaustion only for an empty target across approved follow-up paths."""

    _ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER()
    _semantic_common_preflight(store=store, config=config, runtime=runtime)
    if type(bound) is not BoundFollowup:
        raise TypeError("bound_followup_required")
    if type(outcome) is not FollowupRetrievalOutcome:
        raise TypeError("followup_retrieval_outcome_required")
    plan = object.__getattribute__(bound, "plan")
    if (
        object.__getattribute__(plan, "scope_state") != "restricted"
        or not object.__getattribute__(plan, "resolved_doc_ids")
        or object.__getattribute__(plan, "unresolved_constraints")
        or object.__getattribute__(plan, "metadata_predicates")
    ):
        raise ValueError("followup_absence_resolved_scope_required")
    state = build_e1_followup_harness_state(
        bound=bound,
        outcome=outcome,
        store=store,
        registry=registry,
        policy=policy,
    )
    validate_harness_state(state=state, store=store)
    bound_execution_kind = object.__getattribute__(
        object.__getattribute__(
            object.__getattribute__(bound, "planning"), "trace"
        ),
        "execution_kind",
    )
    validate_harness_runtime_binding(
        binding=runtime,
        store=store,
        expected_execution_kind=bound_execution_kind,
    )
    if type(obligation_key) is not str or not obligation_key:
        raise ValueError("invalid_followup_absence_obligation_key")
    entry = next(
        (
            item
            for item in object.__getattribute__(
                object.__getattribute__(state, "belief"), "evidence_map"
            )
            if object.__getattribute__(item, "obligation_key") == obligation_key
        ),
        None,
    )
    if entry is None:
        raise ValueError("unknown_followup_absence_obligation_key")
    if (
        object.__getattribute__(entry, "candidate_evidence_ids")
        or object.__getattribute__(entry, "observation_stage") != "provisional_missing"
    ):
        raise ValueError("followup_absence_target_candidate_present")
    primary = object.__getattribute__(outcome, "primary")
    fallback = object.__getattribute__(outcome, "fallback")
    trace = object.__getattribute__(outcome, "trace")
    fallback_authorized = object.__getattribute__(trace, "fallback_authorized")
    fallback_executed = object.__getattribute__(trace, "fallback_executed")
    if (
        object.__getattribute__(primary, "retriever_called") is not True
        or object.__getattribute__(outcome, "progress").sufficient
        or type(fallback_authorized) is not bool
        or type(fallback_executed) is not bool
        or fallback_executed is not fallback_authorized
        or (fallback is not None) is not fallback_authorized
        or (
            fallback is not None
            and object.__getattribute__(fallback, "retriever_called") is not True
        )
    ):
        raise ValueError("followup_absence_approved_paths_incomplete")
    outcome_sha256 = _canonical_sha256(outcome.to_dict())
    primary_sha256 = object.__getattribute__(primary, "result_sha256")
    fallback_sha256 = (
        None
        if fallback is None
        else object.__getattribute__(fallback, "result_sha256")
    )
    prerequisite_sha256 = _canonical_sha256(
        {
            "schema_version": SCHEMA_VERSION,
            "reason": "followup_approved_paths_exhausted",
            "obligation_key": obligation_key,
            "source_state_sha256": object.__getattribute__(state, "state_sha256"),
            "followup_outcome_sha256": outcome_sha256,
            "primary_receipt_sha256": primary_sha256,
            "fallback_receipt_sha256": fallback_sha256,
        }
    )
    owner = _absence_owner_projection(bound)
    payload = {
        "stage": "absence_confirmation",
        "source_kind": "follow_up",
        "reason": "followup_approved_paths_exhausted",
        "execution_kind": bound_execution_kind,
        "obligation_key": obligation_key,
        "owner_binding_sha256": owner[0],
        "owner_plan_sha256": owner[1],
        "owner_plan_config_sha256": owner[2],
        "owner_budget_sha256": owner[3],
        "source_receipt_sha256": outcome_sha256,
        "query_sha256": owner[4],
        "scope_doc_ids": owner[5],
        "scope_sha256": owner[6],
        "evidence_store_sha256": object.__getattribute__(store, "bundle_sha256"),
        "execution_config_sha256": object.__getattribute__(config, "config_sha256"),
        "runtime_binding_sha256": object.__getattribute__(runtime, "binding_sha256"),
        "retrieval_obligation_sha256": None,
        "dense_receipt_sha256": None,
        "lexical_receipt_sha256": None,
        "fusion_receipt_sha256": None,
        "semantic_obligation_sha256": None,
        "semantic_receipt_sha256": None,
        "followup_outcome_sha256": outcome_sha256,
        "primary_receipt_sha256": primary_sha256,
        "fallback_receipt_sha256": fallback_sha256,
        "fallback_authorized": fallback_authorized,
        "fallback_executed": fallback_executed,
        "candidate_count": 0,
        "supplied_count": 0,
        "support_count": 0,
        "call_performed": False,
        "prerequisite_sha256": prerequisite_sha256,
    }
    prerequisites = (outcome, primary) + (() if fallback is None else (fallback,))
    return _register_or_read_absence_confirmation(
        root=bound,
        prerequisites=prerequisites,
        store=store,
        config=config,
        runtime=runtime,
        payload=payload,
    )


def validate_absence_confirmation_receipt(
    *,
    receipt: AbsenceConfirmationReceipt,
    store: EvidenceStore,
    config: HarnessExecutionConfig,
    runtime: HarnessRuntimeBinding,
) -> None:
    """Purely audit an issued receipt without invoking any execution capability."""

    _ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER()
    _validate_absence_confirmation_receipt_payload(receipt)
    validate_harness_execution_config(config)
    validate_harness_runtime_binding(binding=runtime, store=store)
    match = _find_absence_confirmation_authority(receipt)
    root = match.root_weak()
    live_prerequisites = tuple(weak() for weak in match.prerequisite_weaks)
    expected_types: tuple[type, ...]
    if object.__getattribute__(receipt, "reason") == "bounded_no_candidate":
        expected_types = (
            RetrievalObligation,
            LaneSearchReceipt,
            LaneSearchReceipt,
            FusionReceipt,
        )
    elif object.__getattribute__(receipt, "reason") == "bounded_no_verified_support":
        expected_types = (
            SemanticVerificationObligation,
            SemanticVerificationReceipt,
        )
    else:
        expected_types = (
            FollowupRetrievalOutcome,
            FollowupRetrievalAttempt,
        ) + (
            (FollowupRetrievalAttempt,)
            if object.__getattribute__(receipt, "fallback_authorized")
            else ()
        )
    if (
        len(match.prerequisite_payload_sha256s) != len(live_prerequisites)
        or len(expected_types) != len(live_prerequisites)
        or any(
            item is not None
            and (
                type(item) is not expected_types[index]
                or _canonical_sha256(item.to_dict())
                != match.prerequisite_payload_sha256s[index]
            )
            for index, item in enumerate(live_prerequisites)
        )
    ):
        raise ValueError("absence_confirmation_prerequisite_drift")
    if (
        root is None
        or match.store_weak() is not store
        or match.config_weak() is not config
        or match.runtime_weak() is not runtime
        or match.root_payload_sha256 != _canonical_sha256(root.to_dict())
        or match.issued_payload_sha256 != _canonical_sha256(receipt.to_dict())
        or object.__getattribute__(receipt, "evidence_store_sha256") != object.__getattribute__(store, "bundle_sha256")
        or object.__getattribute__(receipt, "execution_config_sha256") != object.__getattribute__(config, "config_sha256")
        or object.__getattribute__(receipt, "runtime_binding_sha256") != object.__getattribute__(runtime, "binding_sha256")
        or match.owner_projection != (
            object.__getattribute__(receipt, "owner_binding_sha256"),
            object.__getattribute__(receipt, "owner_plan_sha256"),
            object.__getattribute__(receipt, "owner_plan_config_sha256"),
            object.__getattribute__(receipt, "owner_budget_sha256"),
        )
    ):
        raise ValueError("absence_confirmation_runtime_authority_drift")


(
    _claim_e0_execution,
    _close_e0_execution,
    _fail_e0_execution,
    _consume_e0_execution_permit,
    _validate_consumed_e0_execution_permit,
    _e0_execution_consumed,
    _validate_e0_child_execution_caller,
) = _build_e0_execution_accessors(
    executor_code=object.__getattribute__(execute_e0_control, "__code__"),
    mint_code=object.__getattribute__(_mint_e0_control_receipt, "__code__"),
    lane_executor_code=object.__getattribute__(execute_retrieval_lane, "__code__"),
    fusion_executor_code=object.__getattribute__(
        execute_retrieval_fusion, "__code__"
    ),
    module_globals=globals(),
)


def _runtime_gate_function_pin(name, function):
    kwdefaults = object.__getattribute__(function, "__kwdefaults__")
    closure = object.__getattribute__(function, "__closure__")
    return (
        name,
        function,
        object.__getattribute__(function, "__code__"),
        object.__getattribute__(function, "__defaults__"),
        kwdefaults,
        (
            None
            if kwdefaults is None
            else tuple(sorted(dict.items(kwdefaults)))
        ),
        closure,
        (
            None
            if closure is None
            else tuple(
                object.__getattribute__(cell, "cell_contents")
                for cell in closure
            )
        ),
    )


_RUNTIME_GATE_PUBLIC_KWDEFAULTS = {
    "_dependency_checker": _ISSUED_RUNTIME_GATE_DEPENDENCY_CHECKER,
    "_dependency_checker_code": _PINNED_RUNTIME_GATE_DEPENDENCY_CHECKER_CODE,
}
bind_production_harness_runtime.__kwdefaults__.update(
    _RUNTIME_GATE_PUBLIC_KWDEFAULTS
)
validate_harness_runtime_binding.__kwdefaults__.update(
    _RUNTIME_GATE_PUBLIC_KWDEFAULTS
)
_issue_retrieval_obligations_from_owner.__kwdefaults__.update(
    _RUNTIME_GATE_PUBLIC_KWDEFAULTS
)
issue_fact_retrieval_obligations.__kwdefaults__.update(
    _RUNTIME_GATE_PUBLIC_KWDEFAULTS
)
issue_compare_retrieval_obligations.__kwdefaults__.update(
    _RUNTIME_GATE_PUBLIC_KWDEFAULTS
)
validate_retrieval_obligation.__kwdefaults__.update(
    _RUNTIME_GATE_PUBLIC_KWDEFAULTS
)
execute_retrieval_lane.__kwdefaults__.update(
    _RUNTIME_GATE_PUBLIC_KWDEFAULTS
)
validate_lane_search_receipt.__kwdefaults__.update(
    _RUNTIME_GATE_PUBLIC_KWDEFAULTS
)
execute_retrieval_fusion.__kwdefaults__.update(
    _RUNTIME_GATE_PUBLIC_KWDEFAULTS
)
validate_fusion_receipt.__kwdefaults__.update(
    _RUNTIME_GATE_PUBLIC_KWDEFAULTS
)
execute_e0_control.__kwdefaults__.update(_RUNTIME_GATE_PUBLIC_KWDEFAULTS)
validate_e0_control_receipt.__kwdefaults__.update(
    _RUNTIME_GATE_PUBLIC_KWDEFAULTS
)
issue_fact_semantic_verification_obligation.__kwdefaults__.update(
    _RUNTIME_GATE_PUBLIC_KWDEFAULTS
)
issue_compare_semantic_verification_obligation.__kwdefaults__.update(
    _RUNTIME_GATE_PUBLIC_KWDEFAULTS
)
issue_followup_semantic_verification_obligation.__kwdefaults__.update(
    _RUNTIME_GATE_PUBLIC_KWDEFAULTS
)
validate_semantic_verification_obligation.__kwdefaults__.update(
    _RUNTIME_GATE_PUBLIC_KWDEFAULTS
)
issue_parent_context_receipts.__kwdefaults__.update(
    _RUNTIME_GATE_PUBLIC_KWDEFAULTS
)
issue_bridge_context_receipts.__kwdefaults__.update(
    _RUNTIME_GATE_PUBLIC_KWDEFAULTS
)
validate_parent_context_receipt.__kwdefaults__.update(
    _RUNTIME_GATE_PUBLIC_KWDEFAULTS
)
validate_bridge_context_receipt.__kwdefaults__.update(
    _RUNTIME_GATE_PUBLIC_KWDEFAULTS
)
execute_semantic_rerank.__kwdefaults__.update(
    _RUNTIME_GATE_PUBLIC_KWDEFAULTS
)
validate_rerank_receipt.__kwdefaults__.update(
    _RUNTIME_GATE_PUBLIC_KWDEFAULTS
)
issue_derived_semantic_verification_obligation.__kwdefaults__.update(
    _RUNTIME_GATE_PUBLIC_KWDEFAULTS
)
execute_semantic_verification.__kwdefaults__.update(
    _RUNTIME_GATE_PUBLIC_KWDEFAULTS
)
validate_semantic_verification_receipt.__kwdefaults__.update(
    _RUNTIME_GATE_PUBLIC_KWDEFAULTS
)
_runtime_for_test_function = type.__getattribute__(
    HarnessRuntimeBinding, "__dict__"
)["for_test"].__func__
_runtime_for_test_function.__kwdefaults__.update(
    _RUNTIME_GATE_PUBLIC_KWDEFAULTS
)
_runtime_to_dict_function = type.__getattribute__(
    HarnessRuntimeBinding, "__dict__"
)["to_dict"]
_runtime_to_dict_function.__kwdefaults__.update(
    _RUNTIME_GATE_PUBLIC_KWDEFAULTS
)


_RUNTIME_GATE_FUNCTION_PINS = tuple(
    _runtime_gate_function_pin(name, function)
    for name, function in (
        ("validate_evidence_store_snapshot", validate_evidence_store_snapshot),
        (
            "_ISSUED_VALIDATE_EVIDENCE_STORE_SNAPSHOT",
            _ISSUED_VALIDATE_EVIDENCE_STORE_SNAPSHOT,
        ),
        ("_require_hash", _require_hash),
        (
            "validate_harness_execution_config",
            validate_harness_execution_config,
        ),
        ("_canonical_sha256", _canonical_sha256),
        ("_stable_code_value", _stable_code_value),
        ("_stable_state_value", _stable_state_value),
        ("_class_behavior_payload", _class_behavior_payload),
        ("_behavior_dependency_payload", _behavior_dependency_payload),
        ("_function_behavior_payload", _function_behavior_payload),
        ("_code_global_names", _code_global_names),
        ("_function_behavior_sha256", _function_behavior_sha256),
        ("_component_behavior_sha256", _component_behavior_sha256),
        (
            "_class_and_function_behavior_sha256",
            _class_and_function_behavior_sha256,
        ),
        ("_code_payload", _code_payload),
        ("_function_sha256", _function_sha256),
        ("_instance_dict", _instance_dict),
        ("_component_state_sha256", _component_state_sha256),
        ("_declared_method", _declared_method),
        ("_component_descriptor", _component_descriptor),
        ("_runtime_values", _runtime_values),
        ("_runtime_payload", _runtime_payload),
        ("_validate_runtime_scalars", _validate_runtime_scalars),
        ("_preflight_runtime_binding_shape", _preflight_runtime_binding_shape),
        ("_clock_descriptor", _clock_descriptor),
        ("_synthetic_lane_payload", _synthetic_lane_payload),
        ("_hybrid_instance_parts", _hybrid_instance_parts),
        ("_validated_production_runtime_functions", _validated_production_runtime_functions),
        ("_production_runtime_callables", _production_runtime_callables),
        ("_bind_harness_runtime", _bind_harness_runtime),
        ("_ISSUED_BIND_HARNESS_RUNTIME", _ISSUED_BIND_HARNESS_RUNTIME),
        (
            "bind_production_harness_runtime",
            bind_production_harness_runtime,
        ),
        (
            "_ISSUED_BIND_PRODUCTION_HARNESS_RUNTIME",
            _ISSUED_BIND_PRODUCTION_HARNESS_RUNTIME,
        ),
        ("_require_harness_runtime_authority", _require_harness_runtime_authority),
        (
            "_ISSUED_REQUIRE_HARNESS_RUNTIME_AUTHORITY",
            _ISSUED_REQUIRE_HARNESS_RUNTIME_AUTHORITY,
        ),
        ("_validate_component_authority", _validate_component_authority),
        ("_validate_method_authority", _validate_method_authority),
        ("_validate_harness_runtime_binding", _validate_harness_runtime_binding),
        (
            "_ISSUED_VALIDATE_HARNESS_RUNTIME_BINDING",
            _ISSUED_VALIDATE_HARNESS_RUNTIME_BINDING,
        ),
        (
            "validate_harness_runtime_binding",
            validate_harness_runtime_binding,
        ),
        (
            "_ISSUED_VALIDATE_HARNESS_RUNTIME_BINDING_PUBLIC",
            _ISSUED_VALIDATE_HARNESS_RUNTIME_BINDING_PUBLIC,
        ),
        ("_exact_string_tuple", _exact_string_tuple),
        ("_query_sha256", _query_sha256),
        ("_stable_anchor", _stable_anchor),
        ("_retrieval_obligation_payload", _retrieval_obligation_payload),
        (
            "_validate_retrieval_obligation_payload",
            _validate_retrieval_obligation_payload,
        ),
        (
            "_register_retrieval_ledger_authority",
            _register_retrieval_ledger_authority,
        ),
        (
            "_read_retrieval_ledger_authority",
            _read_retrieval_ledger_authority,
        ),
        (
            "_replace_retrieval_ledger_authority",
            _replace_retrieval_ledger_authority,
        ),
        (
            "_unregister_retrieval_ledger_authority",
            _unregister_retrieval_ledger_authority,
        ),
        ("_register_lane_closure_permit", _register_lane_closure_permit),
        ("_consume_lane_closure_permit", _consume_lane_closure_permit),
        (
            "_validate_consumed_lane_closure_permit",
            _validate_consumed_lane_closure_permit,
        ),
        (
            "_register_retrieval_obligation_authority",
            _register_retrieval_obligation_authority,
        ),
        (
            "_read_retrieval_obligation_authority",
            _read_retrieval_obligation_authority,
        ),
        (
            "_unregister_retrieval_obligation_authority",
            _unregister_retrieval_obligation_authority,
        ),
        (
            "_drop_retrieval_obligation_authority_when_dead",
            _drop_retrieval_obligation_authority_when_dead,
        ),
        (
            "_drop_retrieval_obligation_authority",
            _drop_retrieval_obligation_authority,
        ),
        ("_owner_projection_values", _owner_projection_values),
        ("_require_retrieval_owner", _require_retrieval_owner),
        ("_normalized_owner_projections", _normalized_owner_projections),
        ("_projection_safe_payload", _projection_safe_payload),
        (
            "_issue_retrieval_obligations_from_owner",
            _issue_retrieval_obligations_from_owner,
        ),
        ("_issuance_key", _issuance_key),
        (
            "_read_retrieval_issuance_authority",
            _read_retrieval_issuance_authority,
        ),
        (
            "_register_or_read_retrieval_issuance_authority",
            _register_or_read_retrieval_issuance_authority,
        ),
        (
            "_drop_retrieval_issuance_when_source_dead",
            _drop_retrieval_issuance_when_source_dead,
        ),
        ("_cached_retrieval_issuance", _cached_retrieval_issuance),
        (
            "issue_fact_retrieval_obligations",
            issue_fact_retrieval_obligations,
        ),
        (
            "issue_compare_retrieval_obligations",
            issue_compare_retrieval_obligations,
        ),
        (
            "_require_retrieval_obligation_authority",
            _require_retrieval_obligation_authority,
        ),
        (
            "_validate_lane_dispatch_dependency",
            _validate_lane_dispatch_dependency,
        ),
        ("validate_retrieval_obligation", validate_retrieval_obligation),
        ("_validate_lane_result", _validate_lane_result),
        ("_lane_search_receipt_payload", _lane_search_receipt_payload),
        (
            "_validate_lane_search_receipt_payload",
            _validate_lane_search_receipt_payload,
        ),
        (
            "_register_lane_search_receipt_authority",
            _register_lane_search_receipt_authority,
        ),
        (
            "_read_lane_search_receipt_authority",
            _read_lane_search_receipt_authority,
        ),
        (
            "_drop_lane_search_receipt_authority_when_dead",
            _drop_lane_search_receipt_authority_when_dead,
        ),
        (
            "_drop_lane_search_receipt_authority",
            _drop_lane_search_receipt_authority,
        ),
        ("_mint_lane_search_receipt", _mint_lane_search_receipt),
        ("execute_retrieval_lane", execute_retrieval_lane),
        ("validate_lane_search_receipt", validate_lane_search_receipt),
        ("_fusion_receipt_payload", _fusion_receipt_payload),
        ("_validate_fusion_receipt_payload", _validate_fusion_receipt_payload),
        ("_make_e0_obligation_result", _make_e0_obligation_result),
        ("_e0_control_receipt_payload", _e0_control_receipt_payload),
        (
            "_validate_e0_control_receipt_payload",
            _validate_e0_control_receipt_payload,
        ),
        ("_validate_fusion_result", _validate_fusion_result),
        (
            "_build_fusion_receipt_authority_accessors",
            _build_fusion_receipt_authority_accessors,
        ),
        (
            "_register_fusion_receipt_authority",
            _register_fusion_receipt_authority,
        ),
        ("_read_fusion_receipt_authority", _read_fusion_receipt_authority),
        (
            "_drop_fusion_receipt_authority_when_dead",
            _drop_fusion_receipt_authority_when_dead,
        ),
        ("_drop_fusion_receipt_authority", _drop_fusion_receipt_authority),
        (
            "_build_fusion_execution_accessors",
            _build_fusion_execution_accessors,
        ),
        ("_claim_fusion_execution", _claim_fusion_execution),
        ("_close_fusion_execution", _close_fusion_execution),
        ("_fail_fusion_execution", _fail_fusion_execution),
        (
            "_consume_fusion_execution_permit",
            _consume_fusion_execution_permit,
        ),
        (
            "_validate_consumed_fusion_execution_permit",
            _validate_consumed_fusion_execution_permit,
        ),
        ("_fusion_execution_pristine", _fusion_execution_pristine),
        ("_validate_fusion_lane_advance", _validate_fusion_lane_advance),
        ("_mint_fusion_receipt", _mint_fusion_receipt),
        ("_validate_fusion_inputs", _validate_fusion_inputs),
        ("execute_retrieval_fusion", execute_retrieval_fusion),
        ("validate_fusion_receipt", validate_fusion_receipt),
        ("_validate_e0_obligation_set", _validate_e0_obligation_set),
        (
            "_build_e0_receipt_authority_accessors",
            _build_e0_receipt_authority_accessors,
        ),
        (
            "_register_e0_control_receipt_authority",
            _register_e0_control_receipt_authority,
        ),
        (
            "_read_e0_control_receipt_authority",
            _read_e0_control_receipt_authority,
        ),
        (
            "_drop_e0_control_receipt_authority_when_dead",
            _drop_e0_control_receipt_authority_when_dead,
        ),
        (
            "_drop_e0_control_receipt_authority",
            _drop_e0_control_receipt_authority,
        ),
        ("_build_e0_execution_accessors", _build_e0_execution_accessors),
        ("_claim_e0_execution", _claim_e0_execution),
        ("_close_e0_execution", _close_e0_execution),
        ("_fail_e0_execution", _fail_e0_execution),
        ("_consume_e0_execution_permit", _consume_e0_execution_permit),
        (
            "_validate_consumed_e0_execution_permit",
            _validate_consumed_e0_execution_permit,
        ),
        ("_e0_execution_consumed", _e0_execution_consumed),
        (
            "_validate_e0_child_execution_caller",
            _validate_e0_child_execution_caller,
        ),
        ("_mint_e0_control_receipt", _mint_e0_control_receipt),
        ("execute_e0_control", execute_e0_control),
        ("validate_e0_control_receipt", validate_e0_control_receipt),
        ("build_e1_followup_harness_state", build_e1_followup_harness_state),
        ("validate_harness_state", validate_harness_state),
        ("_ACTION_EFFECTS_NORMALIZER", _ACTION_EFFECTS_NORMALIZER),
        (
            "_ISSUED_ACTION_EFFECTS_NORMALIZER",
            _ISSUED_ACTION_EFFECTS_NORMALIZER,
        ),
        ("_ACTION_EFFECTS_RERANK_NORMALIZER", _ACTION_EFFECTS_RERANK_NORMALIZER),
        (
            "_ISSUED_ACTION_EFFECTS_RERANK_NORMALIZER",
            _ISSUED_ACTION_EFFECTS_RERANK_NORMALIZER,
        ),
        ("_exact_string_tuple_value", _exact_string_tuple_value),
        (
            "_semantic_verification_obligation_payload",
            _semantic_verification_obligation_payload,
        ),
        (
            "_validate_semantic_verification_obligation_payload",
            _validate_semantic_verification_obligation_payload,
        ),
        (
            "_build_semantic_obligation_accessors",
            _build_semantic_obligation_accessors,
        ),
        (
            "_register_semantic_obligation_authority",
            _register_semantic_obligation_authority,
        ),
        (
            "_read_semantic_obligation_authority",
            _read_semantic_obligation_authority,
        ),
        ("_cached_semantic_obligation", _cached_semantic_obligation),
        (
            "_drop_semantic_obligation_authority",
            _drop_semantic_obligation_authority,
        ),
        (
            "_transition_semantic_execution",
            _transition_semantic_execution,
        ),
        ("_semantic_execution_status", _semantic_execution_status),
        ("_drop_semantic_source_history", _drop_semantic_source_history),
        ("_semantic_execution_key", _semantic_execution_key),
        ("_semantic_public_entry", _semantic_public_entry),
        ("_semantic_common_preflight", _semantic_common_preflight),
        ("_semantic_owner_plan_budget", _semantic_owner_plan_budget),
        (
            "_derive_followup_semantic_target",
            _derive_followup_semantic_target,
        ),
        (
            "_create_semantic_verification_obligation",
            _create_semantic_verification_obligation,
        ),
        (
            "_issue_retrieval_semantic_verification_obligation",
            _issue_retrieval_semantic_verification_obligation,
        ),
        (
            "issue_fact_semantic_verification_obligation",
            issue_fact_semantic_verification_obligation,
        ),
        (
            "issue_compare_semantic_verification_obligation",
            issue_compare_semantic_verification_obligation,
        ),
        (
            "issue_followup_semantic_verification_obligation",
            issue_followup_semantic_verification_obligation,
        ),
        (
            "_validate_semantic_verification_obligation_exact",
            _validate_semantic_verification_obligation_exact,
        ),
        (
            "validate_semantic_verification_obligation",
            validate_semantic_verification_obligation,
        ),
        ("_parent_context_receipt_payload", _parent_context_receipt_payload),
        (
            "_validate_parent_context_receipt_payload",
            _validate_parent_context_receipt_payload,
        ),
        ("_bridge_context_receipt_payload", _bridge_context_receipt_payload),
        (
            "_validate_bridge_context_receipt_payload",
            _validate_bridge_context_receipt_payload,
        ),
        ("_build_context_receipt_accessors", _build_context_receipt_accessors),
        (
            "_register_parent_context_receipt_authority",
            _register_parent_context_receipt_authority,
        ),
        (
            "_read_parent_context_receipt_authority",
            _read_parent_context_receipt_authority,
        ),
        (
            "_drop_parent_context_receipt_authority",
            _drop_parent_context_receipt_authority,
        ),
        (
            "_register_bridge_context_receipt_authority",
            _register_bridge_context_receipt_authority,
        ),
        (
            "_read_bridge_context_receipt_authority",
            _read_bridge_context_receipt_authority,
        ),
        (
            "_drop_bridge_context_receipt_authority",
            _drop_bridge_context_receipt_authority,
        ),
        ("_build_context_issuance_accessors", _build_context_issuance_accessors),
        ("_begin_context_receipt_issuance", _begin_context_receipt_issuance),
        (
            "_complete_context_receipt_issuance",
            _complete_context_receipt_issuance,
        ),
        ("_fail_context_receipt_issuance", _fail_context_receipt_issuance),
        ("_context_receipt_issuance_status", _context_receipt_issuance_status),
        (
            "_drop_context_receipt_source_history",
            _drop_context_receipt_source_history,
        ),
        ("_context_seed_evidence_ids", _context_seed_evidence_ids),
        ("_context_issuance_key", _context_issuance_key),
        ("_parent_locator_sha256", _parent_locator_sha256),
        ("_mint_parent_context_receipt", _mint_parent_context_receipt),
        ("_mint_bridge_context_receipt", _mint_bridge_context_receipt),
        (
            "_validate_parent_context_receipt_exact",
            _validate_parent_context_receipt_exact,
        ),
        (
            "_validate_bridge_context_receipt_exact",
            _validate_bridge_context_receipt_exact,
        ),
        ("issue_parent_context_receipts", issue_parent_context_receipts),
        ("issue_bridge_context_receipts", issue_bridge_context_receipts),
        ("validate_parent_context_receipt", validate_parent_context_receipt),
        ("validate_bridge_context_receipt", validate_bridge_context_receipt),
        ("_rerank_receipt_payload", _rerank_receipt_payload),
        ("_validate_rerank_receipt_payload", _validate_rerank_receipt_payload),
        ("_build_rerank_receipt_accessors", _build_rerank_receipt_accessors),
        ("_register_rerank_receipt_authority", _register_rerank_receipt_authority),
        ("_read_rerank_receipt_authority", _read_rerank_receipt_authority),
        ("_drop_rerank_receipt_authority", _drop_rerank_receipt_authority),
        ("_build_semantic_route_accessors", _build_semantic_route_accessors),
        ("_claim_base_semantic_route", _claim_base_semantic_route),
        ("_complete_base_semantic_route", _complete_base_semantic_route),
        ("_begin_semantic_rerank", _begin_semantic_rerank),
        ("_complete_semantic_rerank", _complete_semantic_rerank),
        ("_fail_semantic_rerank", _fail_semantic_rerank),
        ("_semantic_route_status", _semantic_route_status),
        ("_validate_complete_context_receipts", _validate_complete_context_receipts),
        ("_rerank_prerequisite_sha256", _rerank_prerequisite_sha256),
        ("_rerank_evidence_pool", _rerank_evidence_pool),
        ("_validate_reranker_protocol", _validate_reranker_protocol),
        ("_reranker_request", _reranker_request),
        ("_rerank_execution_key", _rerank_execution_key),
        ("_mint_rerank_receipt", _mint_rerank_receipt),
        ("_validate_rerank_receipt_exact", _validate_rerank_receipt_exact),
        ("_rerank_sanitized_result_sha256", _rerank_sanitized_result_sha256),
        ("execute_semantic_rerank", execute_semantic_rerank),
        ("validate_rerank_receipt", validate_rerank_receipt),
        (
            "issue_derived_semantic_verification_obligation",
            issue_derived_semantic_verification_obligation,
        ),
        ("_validate_snapshot_callable", _validate_snapshot_callable),
        ("_validate_snapshot_class", _validate_snapshot_class),
        ("_validate_action_effects_dependency", _validate_action_effects_dependency),
        (
            "_semantic_verification_receipt_payload",
            _semantic_verification_receipt_payload,
        ),
        (
            "_validate_semantic_verification_receipt_payload",
            _validate_semantic_verification_receipt_payload,
        ),
        (
            "_build_semantic_receipt_accessors",
            _build_semantic_receipt_accessors,
        ),
        (
            "_register_semantic_receipt_authority",
            _register_semantic_receipt_authority,
        ),
        ("_read_semantic_receipt_authority", _read_semantic_receipt_authority),
        ("_drop_semantic_receipt_authority", _drop_semantic_receipt_authority),
        ("_validate_semantic_verifier_protocol", _validate_semantic_verifier_protocol),
        ("_semantic_verifier_request", _semantic_verifier_request),
        ("_mint_semantic_verification_receipt", _mint_semantic_verification_receipt),
        ("execute_semantic_verification", execute_semantic_verification),
        (
            "validate_semantic_verification_receipt",
            validate_semantic_verification_receipt,
        ),
        (
            "_absence_confirmation_receipt_payload",
            _absence_confirmation_receipt_payload,
        ),
        (
            "_validate_absence_confirmation_receipt_payload",
            _validate_absence_confirmation_receipt_payload,
        ),
        (
            "_build_absence_confirmation_authority_accessors",
            _build_absence_confirmation_authority_accessors,
        ),
        (
            "_register_or_read_absence_confirmation_authority",
            _register_or_read_absence_confirmation_authority,
        ),
        (
            "_read_absence_confirmation_authority",
            _read_absence_confirmation_authority,
        ),
        (
            "_find_absence_confirmation_authority",
            _find_absence_confirmation_authority,
        ),
        (
            "_drop_absence_confirmation_root",
            _drop_absence_confirmation_root,
        ),
        (
            "_mint_absence_confirmation_receipt",
            _mint_absence_confirmation_receipt,
        ),
        ("_absence_owner_projection", _absence_owner_projection),
        (
            "_validate_cached_absence_confirmation_authority",
            _validate_cached_absence_confirmation_authority,
        ),
        (
            "_register_or_read_absence_confirmation",
            _register_or_read_absence_confirmation,
        ),
        (
            "issue_retrieval_absence_confirmation",
            issue_retrieval_absence_confirmation,
        ),
        (
            "issue_semantic_absence_confirmation",
            issue_semantic_absence_confirmation,
        ),
        (
            "issue_followup_absence_confirmation",
            issue_followup_absence_confirmation,
        ),
        (
            "validate_absence_confirmation_receipt",
            validate_absence_confirmation_receipt,
        ),
    )
)
_ISSUED_RUNTIME_GATE_FUNCTION_PINS = _RUNTIME_GATE_FUNCTION_PINS
_RUNTIME_GATE_OBJECT_PINS = (
    ("SCHEMA_VERSION", SCHEMA_VERSION, str),
    ("FunctionType", FunctionType, type),
    ("CodeType", CodeType, type),
    ("_RUNTIME_AUTHORITIES", _ISSUED_RUNTIME_AUTHORITIES, dict),
    ("_ISSUED_RUNTIME_AUTHORITIES", _ISSUED_RUNTIME_AUTHORITIES, dict),
    (
        "_RUNTIME_AUTHORITY_SHADOW",
        _ISSUED_RUNTIME_AUTHORITY_SHADOW,
        dict,
    ),
    (
        "_ISSUED_RUNTIME_AUTHORITY_SHADOW",
        _ISSUED_RUNTIME_AUTHORITY_SHADOW,
        dict,
    ),
    (
        "_PRODUCTION_RUNTIME_FUNCTION_PINS",
        _ISSUED_PRODUCTION_RUNTIME_FUNCTION_PINS,
        tuple,
    ),
    (
        "_ISSUED_PRODUCTION_RUNTIME_FUNCTION_PINS",
        _ISSUED_PRODUCTION_RUNTIME_FUNCTION_PINS,
        tuple,
    ),
    ("EvidenceStore", EvidenceStore, type),
    ("HarnessRuntimeBinding", HarnessRuntimeBinding, type),
    ("StableEvidenceAnchor", StableEvidenceAnchor, type),
    ("Evidence", Evidence, type),
    ("ProvenanceParent", ProvenanceParent, type),
    ("RuleRegistry", RuleRegistry, type),
    ("BoundFollowup", BoundFollowup, type),
    ("FollowupEvidencePolicy", FollowupEvidencePolicy, type),
    ("FollowupRetrievalAttempt", FollowupRetrievalAttempt, type),
    ("FollowupRetrievalOutcome", FollowupRetrievalOutcome, type),
    ("HarnessState", HarnessState, type),
    ("SemanticValueSupport", SemanticValueSupport, type),
    ("RetrievalObligation", RetrievalObligation, type),
    ("_RetrievalLedgerAuthority", _RetrievalLedgerAuthority, type),
    ("_RetrievalExecutionLedger", _RetrievalExecutionLedger, type),
    ("_LaneClosurePermit", _LaneClosurePermit, type),
    (
        "_RetrievalObligationAuthority",
        _RetrievalObligationAuthority,
        type,
    ),
    ("_RetrievalIssuanceAuthority", _RetrievalIssuanceAuthority, type),
    ("LaneSearchReceipt", LaneSearchReceipt, type),
    ("_LaneSearchReceiptAuthority", _LaneSearchReceiptAuthority, type),
    ("FusionReceipt", FusionReceipt, type),
    ("_FusionExecutionClaim", _FusionExecutionClaim, type),
    ("_FusionClosurePermit", _FusionClosurePermit, type),
    ("_FusionReceiptAuthority", _FusionReceiptAuthority, type),
    ("E0ObligationResult", E0ObligationResult, type),
    ("E0ControlReceipt", E0ControlReceipt, type),
    ("_E0ExecutionClaim", _E0ExecutionClaim, type),
    ("_E0ClosurePermit", _E0ClosurePermit, type),
    ("_E0ControlReceiptAuthority", _E0ControlReceiptAuthority, type),
    (
        "SemanticVerificationObligation",
        SemanticVerificationObligation,
        type,
    ),
    ("_SemanticVerifierEvidence", _SemanticVerifierEvidence, type),
    ("_SemanticVerifierParentContext", _SemanticVerifierParentContext, type),
    ("_SemanticVerifierRequest", _SemanticVerifierRequest, type),
    (
        "_SemanticVerificationObligationAuthority",
        _SemanticVerificationObligationAuthority,
        type,
    ),
    ("ParentContextReceipt", ParentContextReceipt, type),
    ("BridgeContextReceipt", BridgeContextReceipt, type),
    ("RerankReceipt", RerankReceipt, type),
    ("_RerankerEvidence", _RerankerEvidence, type),
    ("_RerankerRequest", _RerankerRequest, type),
    ("_RerankReceiptAuthority", _RerankReceiptAuthority, type),
    (
        "_ParentContextReceiptAuthority",
        _ParentContextReceiptAuthority,
        type,
    ),
    (
        "_BridgeContextReceiptAuthority",
        _BridgeContextReceiptAuthority,
        type,
    ),
    ("SemanticVerificationReceipt", SemanticVerificationReceipt, type),
    (
        "_SemanticVerificationReceiptAuthority",
        _SemanticVerificationReceiptAuthority,
        type,
    ),
    ("Candidate", Candidate, type),
    ("SearchResult", SearchResult, type),
    ("ResolvedScope", ResolvedScope, type),
    ("Lock", Lock, type(Lock)),
    ("_GET_FRAME", _GET_FRAME, BuiltinFunctionType),
    (
        "_ISSUED_EXECUTE_RETRIEVAL_LANE",
        _ISSUED_EXECUTE_RETRIEVAL_LANE,
        FunctionType,
    ),
    (
        "_ISSUED_EXECUTE_RETRIEVAL_LANE_CODE",
        _ISSUED_EXECUTE_RETRIEVAL_LANE_CODE,
        CodeType,
    ),
    (
        "_RETRIEVAL_OBLIGATION_AUTHORITIES",
        _ISSUED_RETRIEVAL_OBLIGATION_AUTHORITIES,
        dict,
    ),
    (
        "_ISSUED_RETRIEVAL_OBLIGATION_AUTHORITIES",
        _ISSUED_RETRIEVAL_OBLIGATION_AUTHORITIES,
        dict,
    ),
    (
        "_RETRIEVAL_LEDGER_AUTHORITIES",
        _ISSUED_RETRIEVAL_LEDGER_AUTHORITIES,
        dict,
    ),
    (
        "_ISSUED_RETRIEVAL_LEDGER_AUTHORITIES",
        _ISSUED_RETRIEVAL_LEDGER_AUTHORITIES,
        dict,
    ),
    (
        "_RETRIEVAL_ISSUANCE_AUTHORITIES",
        _ISSUED_RETRIEVAL_ISSUANCE_AUTHORITIES,
        dict,
    ),
    (
        "_ISSUED_RETRIEVAL_ISSUANCE_AUTHORITIES",
        _ISSUED_RETRIEVAL_ISSUANCE_AUTHORITIES,
        dict,
    ),
    (
        "_LANE_SEARCH_RECEIPT_AUTHORITIES",
        _ISSUED_LANE_SEARCH_RECEIPT_AUTHORITIES,
        dict,
    ),
    (
        "_ISSUED_LANE_SEARCH_RECEIPT_AUTHORITIES",
        _ISSUED_LANE_SEARCH_RECEIPT_AUTHORITIES,
        dict,
    ),
    (
        "_FUSION_RECEIPT_AUTHORITIES",
        _ISSUED_FUSION_RECEIPT_AUTHORITIES,
        dict,
    ),
    (
        "_ISSUED_FUSION_RECEIPT_AUTHORITIES",
        _ISSUED_FUSION_RECEIPT_AUTHORITIES,
        dict,
    ),
    (
        "_E0_CONTROL_RECEIPT_AUTHORITIES",
        _ISSUED_E0_CONTROL_RECEIPT_AUTHORITIES,
        dict,
    ),
    (
        "_ISSUED_E0_CONTROL_RECEIPT_AUTHORITIES",
        _ISSUED_E0_CONTROL_RECEIPT_AUTHORITIES,
        dict,
    ),
    (
        "_SEMANTIC_OBLIGATION_AUTHORITIES",
        _ISSUED_SEMANTIC_OBLIGATION_AUTHORITIES,
        dict,
    ),
    (
        "_ISSUED_SEMANTIC_OBLIGATION_AUTHORITIES",
        _ISSUED_SEMANTIC_OBLIGATION_AUTHORITIES,
        dict,
    ),
    (
        "_SEMANTIC_RECEIPT_AUTHORITIES",
        _ISSUED_SEMANTIC_RECEIPT_AUTHORITIES,
        dict,
    ),
    (
        "_ISSUED_SEMANTIC_RECEIPT_AUTHORITIES",
        _ISSUED_SEMANTIC_RECEIPT_AUTHORITIES,
        dict,
    ),
    (
        "_ABSENCE_CONFIRMATION_AUTHORITIES",
        _ISSUED_ABSENCE_CONFIRMATION_AUTHORITIES,
        dict,
    ),
    (
        "_ISSUED_ABSENCE_CONFIRMATION_AUTHORITIES",
        _ISSUED_ABSENCE_CONFIRMATION_AUTHORITIES,
        dict,
    ),
    (
        "_PARENT_CONTEXT_RECEIPT_AUTHORITIES",
        _ISSUED_PARENT_CONTEXT_RECEIPT_AUTHORITIES,
        dict,
    ),
    (
        "_ISSUED_PARENT_CONTEXT_RECEIPT_AUTHORITIES",
        _ISSUED_PARENT_CONTEXT_RECEIPT_AUTHORITIES,
        dict,
    ),
    (
        "_BRIDGE_CONTEXT_RECEIPT_AUTHORITIES",
        _ISSUED_BRIDGE_CONTEXT_RECEIPT_AUTHORITIES,
        dict,
    ),
    (
        "_ISSUED_BRIDGE_CONTEXT_RECEIPT_AUTHORITIES",
        _ISSUED_BRIDGE_CONTEXT_RECEIPT_AUTHORITIES,
        dict,
    ),
    (
        "_RERANK_RECEIPT_AUTHORITIES",
        _ISSUED_RERANK_RECEIPT_AUTHORITIES,
        dict,
    ),
    (
        "_ISSUED_RERANK_RECEIPT_AUTHORITIES",
        _ISSUED_RERANK_RECEIPT_AUTHORITIES,
        dict,
    ),
    (
        "_ISSUED_HYBRID_SEARCH_LANE",
        _ISSUED_HYBRID_SEARCH_LANE,
        FunctionType,
    ),
    (
        "_ISSUED_HYBRID_SEARCH_LANE_CODE",
        _ISSUED_HYBRID_SEARCH_LANE_CODE,
        CodeType,
    ),
    (
        "_ISSUED_HYBRID_SEARCH_LANE_DEFAULTS",
        _ISSUED_HYBRID_SEARCH_LANE_DEFAULTS,
        type(_ISSUED_HYBRID_SEARCH_LANE_DEFAULTS),
    ),
    (
        "_ISSUED_HYBRID_SEARCH_LANE_KWDEFAULTS",
        _ISSUED_HYBRID_SEARCH_LANE_KWDEFAULTS,
        type(_ISSUED_HYBRID_SEARCH_LANE_KWDEFAULTS),
    ),
    (
        "_RETRIEVAL_OBLIGATION_TOKEN",
        _RETRIEVAL_OBLIGATION_TOKEN,
        object,
    ),
    ("_LANE_SEARCH_RECEIPT_TOKEN", _LANE_SEARCH_RECEIPT_TOKEN, object),
    ("_FUSION_RECEIPT_TOKEN", _FUSION_RECEIPT_TOKEN, object),
    ("_E0_CONTROL_RECEIPT_TOKEN", _E0_CONTROL_RECEIPT_TOKEN, object),
    ("_RETRIEVAL_LEDGER_TOKEN", _RETRIEVAL_LEDGER_TOKEN, object),
    ("_SEMANTIC_OBLIGATION_TOKEN", _SEMANTIC_OBLIGATION_TOKEN, object),
    ("_SEMANTIC_REQUEST_TOKEN", _SEMANTIC_REQUEST_TOKEN, object),
    ("_SEMANTIC_RECEIPT_TOKEN", _SEMANTIC_RECEIPT_TOKEN, object),
    ("_PARENT_CONTEXT_RECEIPT_TOKEN", _PARENT_CONTEXT_RECEIPT_TOKEN, object),
    ("_BRIDGE_CONTEXT_RECEIPT_TOKEN", _BRIDGE_CONTEXT_RECEIPT_TOKEN, object),
    ("_RERANK_RECEIPT_TOKEN", _RERANK_RECEIPT_TOKEN, object),
    ("_RERANK_REQUEST_TOKEN", _RERANK_REQUEST_TOKEN, object),
    ("_ABSENCE_CONFIRMATION_TOKEN", _ABSENCE_CONFIRMATION_TOKEN, object),
    ("_LOCK_TYPE", _LOCK_TYPE, type),
    (
        "_RETRIEVAL_OWNER_SPECS",
        _ISSUED_RETRIEVAL_OWNER_SPECS,
        MappingProxyType,
    ),
    (
        "_ISSUED_RETRIEVAL_OWNER_SPECS",
        _ISSUED_RETRIEVAL_OWNER_SPECS,
        MappingProxyType,
    ),
    (
        "_ISSUED_HYBRID_LANE_PROVIDER_ERROR",
        _ISSUED_HYBRID_LANE_PROVIDER_ERROR,
        type,
    ),
    (
        "_ISSUED_HYBRID_LANE_POST_CALL_CONTRACT_ERROR",
        _ISSUED_HYBRID_LANE_POST_CALL_CONTRACT_ERROR,
        type,
    ),
    ("_RETRIEVAL_SOURCE_KINDS", _RETRIEVAL_SOURCE_KINDS, frozenset),
    ("_RETRIEVAL_LANES", _RETRIEVAL_LANES, frozenset),
    ("_LANE_OUTCOMES", _LANE_OUTCOMES, frozenset),
    ("_LANE_ERROR_CODES", _LANE_ERROR_CODES, frozenset),
    ("_FUSION_OUTCOMES", _FUSION_OUTCOMES, frozenset),
    ("_E0_STATUSES", _E0_STATUSES, frozenset),
    ("_E0_ERROR_CODES", _E0_ERROR_CODES, frozenset),
    ("_SEMANTIC_SOURCE_KINDS", _SEMANTIC_SOURCE_KINDS, frozenset),
    ("_SEMANTIC_TARGET_KINDS", _SEMANTIC_TARGET_KINDS, frozenset),
    ("_SEMANTIC_ROLES", _SEMANTIC_ROLES, frozenset),
    ("_SEMANTIC_DISPOSITIONS", _SEMANTIC_DISPOSITIONS, frozenset),
    ("_ABSENCE_REASONS", _ABSENCE_REASONS, frozenset),
    ("_CONTEXT_BRIDGE_KIND_PAIRS", _CONTEXT_BRIDGE_KIND_PAIRS, tuple),
    ("_CONTEXT_PENDING", _CONTEXT_PENDING, object),
    ("_CONTEXT_COMPLETED", _CONTEXT_COMPLETED, object),
    ("_CONTEXT_FAILED", _CONTEXT_FAILED, object),
    ("_RERANK_OUTCOMES", _RERANK_OUTCOMES, frozenset),
    ("_RERANK_ERROR_CODES", _RERANK_ERROR_CODES, frozenset),
    ("_RERANK_PENDING", _RERANK_PENDING, object),
    ("_RERANK_COMPLETED", _RERANK_COMPLETED, object),
    ("_RERANK_FAILED", _RERANK_FAILED, object),
    ("_ComponentAuthority", _ComponentAuthority, type),
    (
        "_HarnessRuntimeAuthorityDraft",
        _HarnessRuntimeAuthorityDraft,
        type,
    ),
    ("_HarnessRuntimeAuthority", _HarnessRuntimeAuthority, type),
    ("_RUNTIME_TOKEN", _RUNTIME_TOKEN, object),
    ("ref", ref, type(ref)),
    ("ReferenceType", ReferenceType, type),
    ("MappingProxyType", MappingProxyType, type),
    (
        "_RUNTIME_AUTHORITY_DRAFT_FIELDS",
        _ISSUED_RUNTIME_AUTHORITY_DRAFT_FIELDS,
        tuple,
    ),
    (
        "_ISSUED_RUNTIME_AUTHORITY_DRAFT_FIELDS",
        _ISSUED_RUNTIME_AUTHORITY_DRAFT_FIELDS,
        tuple,
    ),
    (
        "bind_production_harness_runtime",
        _ISSUED_BIND_PRODUCTION_HARNESS_RUNTIME,
        FunctionType,
    ),
    (
        "_ISSUED_BIND_PRODUCTION_HARNESS_RUNTIME",
        _ISSUED_BIND_PRODUCTION_HARNESS_RUNTIME,
        FunctionType,
    ),
    (
        "validate_harness_runtime_binding",
        _ISSUED_VALIDATE_HARNESS_RUNTIME_BINDING_PUBLIC,
        FunctionType,
    ),
    (
        "_ISSUED_VALIDATE_HARNESS_RUNTIME_BINDING_PUBLIC",
        _ISSUED_VALIDATE_HARNESS_RUNTIME_BINDING_PUBLIC,
        FunctionType,
    ),
    ("_DENSE_RUNTIME_MODULE", _DENSE_RUNTIME_MODULE, type(_DENSE_RUNTIME_MODULE)),
    ("_FUSION_RUNTIME_MODULE", _FUSION_RUNTIME_MODULE, type(_FUSION_RUNTIME_MODULE)),
    ("_FACT_OWNER_MODULE", _FACT_OWNER_MODULE, type(_FACT_OWNER_MODULE)),
    ("_COMPARE_OWNER_MODULE", _COMPARE_OWNER_MODULE, type(_COMPARE_OWNER_MODULE)),
    (
        "_LEXICAL_RUNTIME_MODULE",
        _LEXICAL_RUNTIME_MODULE,
        type(_LEXICAL_RUNTIME_MODULE),
    ),
    ("_EVIDENCE_RUNTIME_MODULE", _EVIDENCE_RUNTIME_MODULE, type(_EVIDENCE_RUNTIME_MODULE)),
    ("_ACTION_EFFECTS_MODULE", _ACTION_EFFECTS_MODULE, type(_ACTION_EFFECTS_MODULE)),
    (
        "_ACTION_EFFECTS_NORMALIZER",
        _ISSUED_ACTION_EFFECTS_NORMALIZER,
        FunctionType,
    ),
    (
        "_ISSUED_ACTION_EFFECTS_NORMALIZER",
        _ISSUED_ACTION_EFFECTS_NORMALIZER,
        FunctionType,
    ),
    (
        "_ACTION_EFFECTS_PROJECTION_CLASS",
        _ISSUED_ACTION_EFFECTS_PROJECTION_CLASS,
        type,
    ),
    (
        "_ISSUED_ACTION_EFFECTS_PROJECTION_CLASS",
        _ISSUED_ACTION_EFFECTS_PROJECTION_CLASS,
        type,
    ),
    (
        "_ACTION_EFFECTS_RERANK_NORMALIZER",
        _ISSUED_ACTION_EFFECTS_RERANK_NORMALIZER,
        FunctionType,
    ),
    (
        "_ISSUED_ACTION_EFFECTS_RERANK_NORMALIZER",
        _ISSUED_ACTION_EFFECTS_RERANK_NORMALIZER,
        FunctionType,
    ),
    (
        "_ACTION_EFFECTS_RERANK_PROJECTION_CLASS",
        _ISSUED_ACTION_EFFECTS_RERANK_PROJECTION_CLASS,
        type,
    ),
    (
        "_ISSUED_ACTION_EFFECTS_RERANK_PROJECTION_CLASS",
        _ISSUED_ACTION_EFFECTS_RERANK_PROJECTION_CLASS,
        type,
    ),
    (
        "_ACTION_EFFECTS_MODULE_PIN",
        _ISSUED_ACTION_EFFECTS_MODULE_PIN,
        tuple,
    ),
    (
        "_ISSUED_ACTION_EFFECTS_MODULE_PIN",
        _ISSUED_ACTION_EFFECTS_MODULE_PIN,
        tuple,
    ),
    ("_PRODUCTION_CLOCK", _PRODUCTION_CLOCK, BuiltinFunctionType),
    ("json", json, type(json)),
    ("math", math, type(math)),
    ("sha256", sha256, type(sha256)),
)
_ISSUED_RUNTIME_GATE_OBJECT_PINS = _RUNTIME_GATE_OBJECT_PINS
_RUNTIME_GATE_MODULE_ATTRIBUTE_PINS = (
    (json, "dumps", json.dumps),
    (math, "isfinite", math.isfinite),
    (
        _EVIDENCE_RUNTIME_MODULE,
        "validate_evidence_store_snapshot",
        _ISSUED_VALIDATE_EVIDENCE_STORE_SNAPSHOT,
    ),
    (
        _EVIDENCE_RUNTIME_MODULE,
        "ProvenanceParent",
        ProvenanceParent,
    ),
    (
        _FUSION_RUNTIME_MODULE,
        "fuse_rrf",
        object.__getattribute__(_FUSION_RUNTIME_MODULE, "fuse_rrf"),
    ),
    (
        _FUSION_RUNTIME_MODULE,
        "HybridChildRetriever",
        object.__getattribute__(_FUSION_RUNTIME_MODULE, "HybridChildRetriever"),
    ),
    (
        _FUSION_RUNTIME_MODULE,
        "HybridLaneProviderError",
        _ISSUED_HYBRID_LANE_PROVIDER_ERROR,
    ),
    (
        _FUSION_RUNTIME_MODULE,
        "HybridLanePostCallContractError",
        _ISSUED_HYBRID_LANE_POST_CALL_CONTRACT_ERROR,
    ),
    (
        _FACT_OWNER_MODULE,
        "BoundFact",
        object.__getattribute__(_FACT_OWNER_MODULE, "BoundFact"),
    ),
    (
        _FACT_OWNER_MODULE,
        "_FactRetrievalSource",
        object.__getattribute__(_FACT_OWNER_MODULE, "_FactRetrievalSource"),
    ),
    (
        _FACT_OWNER_MODULE,
        "_project_fact_retrieval_source",
        object.__getattribute__(
            _FACT_OWNER_MODULE, "_project_fact_retrieval_source"
        ),
    ),
    (
        _FACT_OWNER_MODULE,
        "validate_bound_fact",
        object.__getattribute__(_FACT_OWNER_MODULE, "validate_bound_fact"),
    ),
    (
        _COMPARE_OWNER_MODULE,
        "BoundCompare",
        object.__getattribute__(_COMPARE_OWNER_MODULE, "BoundCompare"),
    ),
    (
        _COMPARE_OWNER_MODULE,
        "_CompareRetrievalSource",
        object.__getattribute__(
            _COMPARE_OWNER_MODULE, "_CompareRetrievalSource"
        ),
    ),
    (
        _COMPARE_OWNER_MODULE,
        "_project_compare_retrieval_sources",
        object.__getattribute__(
            _COMPARE_OWNER_MODULE, "_project_compare_retrieval_sources"
        ),
    ),
    (
        _COMPARE_OWNER_MODULE,
        "validate_bound_compare",
        object.__getattribute__(_COMPARE_OWNER_MODULE, "validate_bound_compare"),
    ),
    (
        _ACTION_EFFECTS_MODULE,
        "_normalize_semantic_verifier_result",
        _ISSUED_ACTION_EFFECTS_NORMALIZER,
    ),
    (
        _ACTION_EFFECTS_MODULE,
        "_SemanticVerificationProjection",
        _ISSUED_ACTION_EFFECTS_PROJECTION_CLASS,
    ),
    (
        _ACTION_EFFECTS_MODULE,
        "_normalize_reranker_result",
        _ISSUED_ACTION_EFFECTS_RERANK_NORMALIZER,
    ),
    (
        _ACTION_EFFECTS_MODULE,
        "_RerankProjection",
        _ISSUED_ACTION_EFFECTS_RERANK_PROJECTION_CLASS,
    ),
    (
        _ACTION_EFFECTS_MODULE,
        "SemanticValueSupport",
        SemanticValueSupport,
    ),
    (
        object.__getattribute__(_ACTION_EFFECTS_MODULE, "unicodedata"),
        "normalize",
        object.__getattribute__(
            object.__getattribute__(_ACTION_EFFECTS_MODULE, "unicodedata"),
            "normalize",
        ),
    ),
    (
        object.__getattribute__(_ACTION_EFFECTS_MODULE, "unicodedata"),
        "category",
        object.__getattribute__(
            object.__getattribute__(_ACTION_EFFECTS_MODULE, "unicodedata"),
            "category",
        ),
    ),
)
_ISSUED_RUNTIME_GATE_MODULE_ATTRIBUTE_PINS = (
    _RUNTIME_GATE_MODULE_ATTRIBUTE_PINS
)


def _runtime_gate_class_pin(owner, method_names):
    namespace = type.__getattribute__(owner, "__dict__")
    slot_names = type.__getattribute__(owner, "__slots__")
    if type(slot_names) is str:
        slot_names = (slot_names,)
    slot_pins = tuple(
        (name, namespace.get(name), type(namespace.get(name)))
        for name in slot_names
    )
    method_pins = []
    for name in method_names:
        current = namespace.get(name)
        wrapper_type = type(current)
        function = (
            object.__getattribute__(current, "__func__")
            if type(current) is classmethod
            else current
        )
        kwdefaults = object.__getattribute__(function, "__kwdefaults__")
        closure = object.__getattribute__(function, "__closure__")
        method_pins.append(
            (
                name,
                wrapper_type,
                function,
                object.__getattribute__(function, "__code__"),
                object.__getattribute__(function, "__defaults__"),
                kwdefaults,
                (
                    None
                    if kwdefaults is None
                    else tuple(sorted(dict.items(kwdefaults)))
                ),
                closure,
                (
                    None
                    if closure is None
                    else tuple(
                        object.__getattribute__(cell, "cell_contents")
                        for cell in closure
                    )
                ),
            )
        )
    return (
        owner,
        type.__getattribute__(owner, "__getattribute__"),
        slot_pins,
        tuple(method_pins),
    )


_RUNTIME_GATE_CLASS_PINS = (
    _runtime_gate_class_pin(
        HarnessRuntimeBinding,
        ("__init__", "_create", "for_test", "to_dict"),
    ),
    _runtime_gate_class_pin(_ComponentAuthority, ("__init__",)),
    _runtime_gate_class_pin(
        _HarnessRuntimeAuthorityDraft,
        ("__init__", "to_dict"),
    ),
    _runtime_gate_class_pin(_HarnessRuntimeAuthority, ("__init__",)),
    _runtime_gate_class_pin(
        StableEvidenceAnchor,
        ("__init__", "__post_init__", "_payload", "to_dict"),
    ),
    _runtime_gate_class_pin(
        RetrievalObligation,
        ("__init__", "_create", "to_dict"),
    ),
    _runtime_gate_class_pin(_RetrievalLedgerAuthority, ("__init__",)),
    _runtime_gate_class_pin(
        _RetrievalExecutionLedger,
        (
            "__init__",
            "_create",
            "_state_payload",
            "_advance",
            "_validate",
            "_expected_pair",
            "_precheck",
            "_claim",
            "_close",
        ),
    ),
    _runtime_gate_class_pin(_LaneClosurePermit, ("__init__",)),
    _runtime_gate_class_pin(_RetrievalObligationAuthority, ("__init__",)),
    _runtime_gate_class_pin(_RetrievalIssuanceAuthority, ("__init__",)),
    _runtime_gate_class_pin(
        LaneSearchReceipt,
        ("__init__", "_create", "to_dict"),
    ),
    _runtime_gate_class_pin(_LaneSearchReceiptAuthority, ("__init__",)),
    _runtime_gate_class_pin(
        FusionReceipt,
        ("__init__", "_create", "to_dict"),
    ),
    _runtime_gate_class_pin(_FusionExecutionClaim, ("__init__",)),
    _runtime_gate_class_pin(_FusionClosurePermit, ("__init__",)),
    _runtime_gate_class_pin(_FusionReceiptAuthority, ("__init__",)),
    _runtime_gate_class_pin(
        E0ObligationResult,
        ("__init__", "_create", "__post_init__", "_payload", "to_dict"),
    ),
    _runtime_gate_class_pin(
        E0ControlReceipt,
        ("__init__", "_create", "to_dict"),
    ),
    _runtime_gate_class_pin(_E0ExecutionClaim, ("__init__",)),
    _runtime_gate_class_pin(_E0ClosurePermit, ("__init__",)),
    _runtime_gate_class_pin(_E0ControlReceiptAuthority, ("__init__",)),
    _runtime_gate_class_pin(
        SemanticVerificationObligation,
        ("__init__", "_create", "to_dict"),
    ),
    _runtime_gate_class_pin(
        _SemanticVerifierEvidence,
        ("__init__", "__reduce__", "__reduce_ex__", "_create"),
    ),
    _runtime_gate_class_pin(
        _SemanticVerifierParentContext,
        (
            "__init__",
            "__copy__",
            "__deepcopy__",
            "__reduce__",
            "__reduce_ex__",
            "_create",
        ),
    ),
    _runtime_gate_class_pin(
        _SemanticVerifierRequest,
        ("__init__", "__reduce__", "__reduce_ex__", "_create"),
    ),
    _runtime_gate_class_pin(
        _SemanticVerificationObligationAuthority,
        ("__init__",),
    ),
    _runtime_gate_class_pin(
        ParentContextReceipt,
        (
            "__init__",
            "__copy__",
            "__deepcopy__",
            "__reduce__",
            "__reduce_ex__",
            "_create",
            "to_dict",
        ),
    ),
    _runtime_gate_class_pin(
        BridgeContextReceipt,
        (
            "__init__",
            "__copy__",
            "__deepcopy__",
            "__reduce__",
            "__reduce_ex__",
            "_create",
            "to_dict",
        ),
    ),
    _runtime_gate_class_pin(_ParentContextReceiptAuthority, ("__init__",)),
    _runtime_gate_class_pin(_BridgeContextReceiptAuthority, ("__init__",)),
    _runtime_gate_class_pin(
        RerankReceipt,
        (
            "__init__",
            "__copy__",
            "__deepcopy__",
            "__reduce__",
            "__reduce_ex__",
            "_create",
            "to_dict",
        ),
    ),
    _runtime_gate_class_pin(
        _RerankerEvidence,
        (
            "__init__",
            "__copy__",
            "__deepcopy__",
            "__reduce__",
            "__reduce_ex__",
            "_create",
        ),
    ),
    _runtime_gate_class_pin(
        _RerankerRequest,
        (
            "__init__",
            "__copy__",
            "__deepcopy__",
            "__reduce__",
            "__reduce_ex__",
            "_create",
        ),
    ),
    _runtime_gate_class_pin(_RerankReceiptAuthority, ("__init__",)),
    _runtime_gate_class_pin(
        SemanticVerificationReceipt,
        ("__init__", "_create", "to_dict"),
    ),
    _runtime_gate_class_pin(
        _SemanticVerificationReceiptAuthority,
        ("__init__",),
    ),
    _runtime_gate_class_pin(
        AbsenceConfirmationReceipt,
        (
            "__init__",
            "__copy__",
            "__deepcopy__",
            "__reduce__",
            "__reduce_ex__",
            "_create",
            "to_dict",
        ),
    ),
    _runtime_gate_class_pin(_AbsenceConfirmationAuthority, ("__init__",)),
)
_ISSUED_RUNTIME_GATE_CLASS_PINS = _RUNTIME_GATE_CLASS_PINS
_RUNTIME_GATE_DEPENDENCY_DEFAULTS = (
    globals(),
    _RUNTIME_GATE_FUNCTION_PINS,
    _RUNTIME_GATE_OBJECT_PINS,
    _RUNTIME_GATE_MODULE_ATTRIBUTE_PINS,
    _RUNTIME_GATE_CLASS_PINS,
    _RUNTIME_AUTHORITY_DRAFT_FIELDS,
)
_ISSUED_RUNTIME_GATE_DEPENDENCY_DEFAULTS = (
    _RUNTIME_GATE_DEPENDENCY_DEFAULTS
)
_validate_runtime_gate_dependencies.__defaults__ = (
    _RUNTIME_GATE_DEPENDENCY_DEFAULTS
)


__all__ = (
    "AbsenceConfirmationReceipt",
    "BridgeContextReceipt",
    "E0ControlReceipt",
    "E0ObligationResult",
    "ExecutionLedger",
    "FusionReceipt",
    "HARNESS_EXECUTION_POLICY_ID",
    "HarnessExecution",
    "HarnessExecutionConfig",
    "HarnessRuntimeBinding",
    "LaneSearchReceipt",
    "ParentContextReceipt",
    "RerankReceipt",
    "RetrievalObligation",
    "SemanticValueSupport",
    "SemanticVerificationObligation",
    "SemanticVerificationReceipt",
    "StableEvidenceAnchor",
    "bind_production_harness_runtime",
    "create_harness_execution_config",
    "execute_e0_control",
    "execute_retrieval_fusion",
    "execute_retrieval_lane",
    "issue_compare_retrieval_obligations",
    "issue_compare_semantic_verification_obligation",
    "issue_bridge_context_receipts",
    "issue_fact_retrieval_obligations",
    "issue_fact_semantic_verification_obligation",
    "issue_followup_semantic_verification_obligation",
    "issue_parent_context_receipts",
    "issue_derived_semantic_verification_obligation",
    "issue_retrieval_absence_confirmation",
    "issue_semantic_absence_confirmation",
    "issue_followup_absence_confirmation",
    "issue_harness_execution",
    "validate_bridge_context_receipt",
    "validate_harness_execution",
    "validate_harness_execution_config",
    "validate_harness_runtime_binding",
    "validate_e0_control_receipt",
    "validate_fusion_receipt",
    "validate_lane_search_receipt",
    "validate_parent_context_receipt",
    "validate_rerank_receipt",
    "validate_retrieval_obligation",
    "validate_semantic_verification_obligation",
    "validate_semantic_verification_receipt",
    "validate_absence_confirmation_receipt",
)
