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
from midprojectrag.evidence import EvidenceStore, validate_evidence_store_snapshot
from midprojectrag.retrieval import dense as _DENSE_RUNTIME_MODULE
from midprojectrag.retrieval import fusion as _FUSION_RUNTIME_MODULE
from midprojectrag.retrieval import kiwi_bm25 as _LEXICAL_RUNTIME_MODULE
from midprojectrag.retrieval.contracts import Candidate, SearchResult
from midprojectrag.runtime_integrity import ResolvedScope

from . import compare_slots as _COMPARE_OWNER_MODULE
from . import fact_binding as _FACT_OWNER_MODULE


SCHEMA_VERSION = "1.0"
HARNESS_EXECUTION_POLICY_ID = "bounded-evidence-controller-v1"
_CONFIG_TOKEN = object()
_RUNTIME_TOKEN = object()
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
        dict.__setitem__(
            _ISSUED_RUNTIME_AUTHORITIES,
            identity,
            _HarnessRuntimeAuthority(
                weak=weak,
                issued_payload_sha256=issued_payload_sha256,
                **{
                    name: object.__getattribute__(authority, name)
                    for name in _RUNTIME_AUTHORITY_DRAFT_FIELDS
                },
            ),
        )
        try:
            validate_harness_runtime_binding(
                binding=result,
                store=authority.store,
                expected_execution_kind=authority.execution_kind,
            )
        except Exception:
            dict.pop(_ISSUED_RUNTIME_AUTHORITIES, identity, None)
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


def _drop_runtime_authority(
    identity: int,
    dead: ReferenceType[HarnessRuntimeBinding],
) -> None:
    current = dict.get(_ISSUED_RUNTIME_AUTHORITIES, identity)
    if current is not None and current.weak is dead:
        dict.pop(_ISSUED_RUNTIME_AUTHORITIES, identity, None)


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
    if type(authority) is not _HarnessRuntimeAuthority:
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
    )
)
_ISSUED_RUNTIME_GATE_FUNCTION_PINS = _RUNTIME_GATE_FUNCTION_PINS
_RUNTIME_GATE_OBJECT_PINS = (
    ("_RUNTIME_AUTHORITIES", _ISSUED_RUNTIME_AUTHORITIES, dict),
    ("_ISSUED_RUNTIME_AUTHORITIES", _ISSUED_RUNTIME_AUTHORITIES, dict),
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
    "E0ControlReceipt",
    "E0ObligationResult",
    "FusionReceipt",
    "HARNESS_EXECUTION_POLICY_ID",
    "HarnessExecutionConfig",
    "HarnessRuntimeBinding",
    "LaneSearchReceipt",
    "RetrievalObligation",
    "StableEvidenceAnchor",
    "bind_production_harness_runtime",
    "create_harness_execution_config",
    "execute_e0_control",
    "execute_retrieval_fusion",
    "execute_retrieval_lane",
    "issue_compare_retrieval_obligations",
    "issue_fact_retrieval_obligations",
    "validate_harness_execution_config",
    "validate_harness_runtime_binding",
    "validate_e0_control_receipt",
    "validate_fusion_receipt",
    "validate_lane_search_receipt",
    "validate_retrieval_obligation",
)
