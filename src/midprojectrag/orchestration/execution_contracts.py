"""Immutable execution config and exact live runtime authority for EH2.6.

This leaf binds capabilities only.  It never derives a query and never calls a
retriever, verifier, reranker, clock, model, or provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
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


SCHEMA_VERSION = "1.0"
HARNESS_EXECUTION_POLICY_ID = "bounded-evidence-controller-v1"
_CONFIG_TOKEN = object()
_RUNTIME_TOKEN = object()
_ISSUED_VALIDATE_EVIDENCE_STORE_SNAPSHOT = validate_evidence_store_snapshot
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
        if type(entry) is not tuple or len(entry) != 6:
            raise ValueError("harness_runtime_validation_dependency_drift")
        name, issued, code, defaults, kwdefaults, kwdefault_items = entry
        current = dict.get(_module_globals, name)
        current_kwdefaults = object.__getattribute__(issued, "__kwdefaults__")
        if (
            type(name) is not str
            or type(issued) is not FunctionType
            or type(code) is not CodeType
            or current is not issued
            or type(current) is not FunctionType
            or object.__getattribute__(current, "__code__") is not code
            or object.__getattribute__(current, "__defaults__") is not defaults
            or current_kwdefaults is not kwdefaults
            or (
                None
                if current_kwdefaults is None
                else tuple(sorted(dict.items(current_kwdefaults)))
            )
            != kwdefault_items
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
            if type(method_pin) is not tuple or len(method_pin) != 7:
                raise ValueError("harness_runtime_validation_dependency_drift")
            (
                name,
                wrapper_type,
                issued,
                code,
                defaults,
                kwdefaults,
                kwdefault_items,
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
            if (
                type(name) is not str
                or type(current) is not wrapper_type
                or function is not issued
                or type(function) is not FunctionType
                or object.__getattribute__(function, "__code__") is not code
                or object.__getattribute__(function, "__defaults__") is not defaults
                or current_kwdefaults is not kwdefaults
                or (
                    None
                    if current_kwdefaults is None
                    else tuple(sorted(dict.items(current_kwdefaults)))
                )
                != kwdefault_items
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


def _runtime_gate_function_pin(name, function):
    kwdefaults = object.__getattribute__(function, "__kwdefaults__")
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
    "HARNESS_EXECUTION_POLICY_ID",
    "HarnessExecutionConfig",
    "HarnessRuntimeBinding",
    "bind_production_harness_runtime",
    "create_harness_execution_config",
    "validate_harness_execution_config",
    "validate_harness_runtime_binding",
)
