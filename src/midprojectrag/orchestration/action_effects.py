"""Pure semantic-verifier result contracts for EH2.6.

This module intentionally owns no runtime, query, evidence-store, controller, or
evaluation authority.  The normalizer below turns an untrusted verifier JSON
value into a closed, deterministic projection.  That projection is still only
a value object: an execution owner must bind it to an exact verifier call before
it can authorize an effect or a state transition.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
from types import MappingProxyType
import unicodedata
from typing import Any


_SCHEMA_VERSION = "1.0"
_DISPOSITIONS = frozenset({"supported", "unsupported", "contradicted"})
_VALUE_TYPES = frozenset(
    {"text", "krw_amount", "kst_datetime", "duration", "boolean", "number"}
)
_RESULT_FIELDS = frozenset(
    {"schema_version", "disposition", "support_indexes", "values"}
)
_RERANK_RESULT_FIELDS = frozenset({"schema_version", "ordered_indexes"})
_VALUE_FIELDS = frozenset(
    {"value_type", "canonical_value", "support_indexes"}
)
_FIELD = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_KRW_AMOUNT = re.compile(r"^(?:0|[1-9][0-9]*)$")
_KST_DATETIME = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}\+09:00$"
)
_CANONICAL_DECIMAL = re.compile(
    r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?$"
)
_DURATION = re.compile(
    r"^P"
    r"(?:(?P<years>[1-9][0-9]*)Y)?"
    r"(?:(?P<months>[1-9][0-9]*)M)?"
    r"(?:(?P<weeks>[1-9][0-9]*)W)?"
    r"(?:(?P<days>[1-9][0-9]*)D)?"
    r"(?:T"
    r"(?:(?P<hours>[1-9][0-9]*)H)?"
    r"(?:(?P<minutes>[1-9][0-9]*)M)?"
    r"(?:(?P<seconds>(?:[1-9][0-9]*(?:\.[0-9]*[1-9])?|0\.[0-9]*[1-9]))S)?"
    r")?$"
)
_TEXT_LIMIT = 4096
_SCALAR_LIMIT = 128
_FIELD_VALUE_TYPES = MappingProxyType({
    "budget": "krw_amount",
    "duration": "duration",
    "deadline": "kst_datetime",
    "joint_contract": "boolean",
    "subcontract": "boolean",
})
_VALUE_TOKEN = object()
_PROJECTION_TOKEN = object()
_RERANK_PROJECTION_TOKEN = object()
_ACTION_EFFECT_RECEIPT_TOKEN = object()

_ACTION_EFFECT_ACTION_KINDS = frozenset(
    {
        "retrieve_dense",
        "retrieve_lexical",
        "fuse",
        "expand_parent",
        "rerank",
        "bridge_table",
        "bridge_figure",
        "verify_slot",
        "stop",
        "abstain",
    }
)
_ACTION_EFFECT_SOURCE_KINDS = frozenset({"fact", "compare", "follow_up"})
_ACTION_EFFECT_SOURCE_RECEIPT_KINDS = frozenset(
    {
        "lane_search",
        "fusion",
        "parent_context",
        "bridge_context",
        "rerank",
        "semantic_verification",
        "absence_confirmation",
        "controller_decision",
    }
)
_ACTION_EFFECT_OUTCOMES = frozenset(
    {
        "applied",
        "empty",
        "unsupported",
        "unavailable",
        "deadline_discarded",
        "provider_error",
        "contract_error",
        "terminal",
    }
)
_ACTION_EFFECT_OBLIGATION_ACTIONS = frozenset(
    {
        "retrieve_dense",
        "retrieve_lexical",
        "fuse",
        "rerank",
        "verify_slot",
    }
)
_ACTION_EFFECT_EVIDENCE_ACTIONS = frozenset(
    {"expand_parent", "bridge_table", "bridge_figure"}
)
_ACTION_EFFECT_TERMINAL_ACTIONS = frozenset({"stop", "abstain"})
_ACTION_EFFECT_PROVIDER_ACTIONS = frozenset(
    {"retrieve_dense", "retrieve_lexical", "rerank", "verify_slot"}
)
_ACTION_EFFECT_CORE_ROWS = frozenset(
    {
        ("retrieve_dense", "lane_search", "applied", True),
        ("retrieve_dense", "lane_search", "empty", True),
        ("retrieve_dense", "lane_search", "provider_error", True),
        ("retrieve_dense", "lane_search", "contract_error", False),
        ("retrieve_dense", "lane_search", "contract_error", True),
        ("retrieve_lexical", "lane_search", "applied", True),
        ("retrieve_lexical", "lane_search", "empty", True),
        ("retrieve_lexical", "lane_search", "provider_error", True),
        ("retrieve_lexical", "lane_search", "contract_error", False),
        ("retrieve_lexical", "lane_search", "contract_error", True),
        ("fuse", "fusion", "applied", True),
        ("fuse", "fusion", "empty", True),
        ("expand_parent", "parent_context", "applied", True),
        ("bridge_table", "bridge_context", "applied", True),
        ("bridge_table", "bridge_context", "empty", True),
        ("bridge_figure", "bridge_context", "applied", True),
        ("bridge_figure", "bridge_context", "empty", True),
        ("rerank", "rerank", "applied", True),
        ("rerank", "rerank", "unavailable", False),
        ("rerank", "rerank", "provider_error", True),
        ("rerank", "rerank", "contract_error", True),
        ("verify_slot", "semantic_verification", "applied", True),
        ("verify_slot", "semantic_verification", "unsupported", True),
        ("verify_slot", "semantic_verification", "unavailable", False),
        ("verify_slot", "absence_confirmation", "empty", False),
        ("stop", "controller_decision", "terminal", False),
        ("abstain", "controller_decision", "terminal", False),
    }
)
_ACTION_EFFECT_PAYLOAD_FIELDS = frozenset(
    {
        "stage",
        "execution_sha256",
        "step_index",
        "controller_decision_sha256",
        "action_kind",
        "action_sha256",
        "obligation_key",
        "target_evidence_id",
        "before_state_sha256",
        "source_kind",
        "source_receipt_kind",
        "source_receipt_sha256",
        "outcome",
        "ordered_evidence_ids",
        "parent_context_receipt_sha256s",
        "bridge_context_receipt_sha256s",
        "absence_confirmation_sha256",
        "call_performed",
    }
)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _canonical_sha256(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _closed_dict(value: object, fields: frozenset[str], code: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise TypeError(code)
    if set(value) != fields:
        raise ValueError(code)
    if any(type(key) is not str for key in value):
        raise TypeError(code)
    return value


def _exact_ids(value: object, code: str, *, allow_empty: bool) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(code)
    result = tuple(value)
    if (not allow_empty and not result) or any(
        type(item) is not str or not item for item in result
    ):
        raise ValueError(code)
    if len(result) != len(set(result)):
        raise ValueError(f"duplicate_{code}")
    return result


def _exact_indexes(
    value: object,
    code: str,
    *,
    maximum: int,
) -> tuple[int, ...]:
    if type(value) is not list:
        raise TypeError(code)
    if len(value) > maximum:
        raise ValueError(code)
    result = tuple(value)
    if any(type(item) is not int or item < 0 for item in result):
        raise ValueError(code)
    if len(result) != len(set(result)):
        raise ValueError(f"duplicate_{code}")
    return result


def _support_ids_from_indexes(
    indexes: tuple[int, ...],
    *,
    supplied: tuple[str, ...],
    promotable: tuple[str, ...],
    code: str,
) -> tuple[str, ...]:
    if any(index >= len(supplied) for index in indexes):
        raise ValueError(code)
    selected = tuple(supplied[index] for index in indexes)
    if not set(selected).issubset(promotable):
        raise ValueError(code)
    selected_set = set(selected)
    return tuple(item for item in supplied if item in selected_set)


def _ordered_subset(
    values: tuple[str, ...],
    *,
    universe: tuple[str, ...],
    code: str,
) -> tuple[str, ...]:
    selected = set(values)
    if not selected.issubset(universe):
        raise ValueError(code)
    return tuple(item for item in universe if item in selected)


def _canonical_duration(value: str) -> str:
    """Return the accepted canonical ISO-8601 duration subset.

    The closed grammar permits ``PT0S``; positive, non-zero integer Y/M/D/H/M
    components; canonical positive decimal seconds; or one positive integer
    week component by itself.  Signs, leading zeros, fractional non-second
    components, mixed week/calendar forms, and empty date/time parts are not
    accepted.
    """

    if value == "PT0S":
        return value
    match = _DURATION.fullmatch(value)
    if match is None or not any(match.groupdict().values()):
        raise ValueError("invalid_semantic_canonical_value")
    groups = match.groupdict()
    if groups["weeks"] is not None and any(
        groups[name] is not None
        for name in ("years", "months", "days", "hours", "minutes", "seconds")
    ):
        raise ValueError("invalid_semantic_canonical_value")
    if "T" in value and not any(
        groups[name] is not None for name in ("hours", "minutes", "seconds")
    ):
        raise ValueError("invalid_semantic_canonical_value")
    return value


def _canonical_value(value_type: str, value: object) -> str:
    if type(value) is not str:
        raise TypeError("semantic_canonical_value_string_required")
    if value_type == "text":
        if len(value) > _TEXT_LIMIT:
            raise ValueError("semantic_canonical_value_too_long")
        normalized = unicodedata.normalize("NFC", value)
        if any(
            unicodedata.category(character).startswith("C")
            and character not in {"\t", "\n", "\r"}
            for character in normalized
        ):
            raise ValueError("invalid_semantic_canonical_value")
        canonical = " ".join(normalized.split())
        if not canonical or any(
            unicodedata.category(character).startswith("C")
            for character in canonical
        ):
            raise ValueError("invalid_semantic_canonical_value")
        if (
            len(canonical) > _TEXT_LIMIT
            or len(canonical.encode("utf-8")) > _TEXT_LIMIT
        ):
            raise ValueError("semantic_canonical_value_too_long")
        return canonical
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("invalid_semantic_canonical_value") from exc
    if len(value) > _SCALAR_LIMIT or len(encoded) > _SCALAR_LIMIT:
        raise ValueError("semantic_canonical_value_too_long")
    if value_type == "krw_amount":
        if _KRW_AMOUNT.fullmatch(value) is None:
            raise ValueError("invalid_semantic_canonical_value")
        return value
    if value_type == "kst_datetime":
        if _KST_DATETIME.fullmatch(value) is None:
            raise ValueError("invalid_semantic_canonical_value")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("invalid_semantic_canonical_value") from exc
        if (
            parsed.microsecond != 0
            or parsed.utcoffset() != timedelta(hours=9)
            or parsed.isoformat(timespec="seconds") != value
        ):
            raise ValueError("invalid_semantic_canonical_value")
        return value
    if value_type == "duration":
        return _canonical_duration(value)
    if value_type == "boolean":
        if value not in {"true", "false"}:
            raise ValueError("invalid_semantic_canonical_value")
        return value
    if value_type == "number":
        if _CANONICAL_DECIMAL.fullmatch(value) is None or value == "-0":
            raise ValueError("invalid_semantic_canonical_value")
        try:
            parsed = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("invalid_semantic_canonical_value") from exc
        if not parsed.is_finite():
            raise ValueError("invalid_semantic_canonical_value")
        return value
    raise ValueError("invalid_semantic_value_type")


def _field_value_type(field: str) -> str:
    return _FIELD_VALUE_TYPES.get(field, "text")


def _effect_require_hash(value: object, code: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or re.fullmatch(r"[0-9a-f]{64}", value) is None
    ):
        raise ValueError(code)
    return value


def _effect_string_tuple(
    value: object,
    code: str,
    *,
    hashes: bool = False,
) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(code)
    result = tuple(value)
    if any(type(item) is not str or not item for item in result):
        raise ValueError(code)
    if len(result) != len(set(result)):
        raise ValueError(f"duplicate_{code}")
    if hashes:
        for item in result:
            _effect_require_hash(item, code)
    return result


def _valid_action_effect_row(
    *,
    action_kind: str,
    source_receipt_kind: str,
    outcome: str,
    call_performed: bool,
) -> bool:
    row = (action_kind, source_receipt_kind, outcome, call_performed)
    if row in _ACTION_EFFECT_CORE_ROWS:
        return True
    if source_receipt_kind != "controller_decision":
        return False
    if action_kind in {"retrieve_dense", "retrieve_lexical", "bridge_table", "bridge_figure"}:
        if outcome == "unavailable" and call_performed is False:
            return True
    if action_kind not in _ACTION_EFFECT_TERMINAL_ACTIONS:
        if outcome == "deadline_discarded":
            if action_kind in _ACTION_EFFECT_PROVIDER_ACTIONS:
                return type(call_performed) is bool
            return call_performed is False
        if (
            outcome == "contract_error"
            and action_kind
            in {
                "fuse",
                "expand_parent",
                "rerank",
                "bridge_table",
                "bridge_figure",
                "verify_slot",
            }
        ):
            return type(call_performed) is bool
    return (
        action_kind == "verify_slot"
        and outcome == "provider_error"
        and call_performed is True
    )


def _validate_action_effect_receipt_payload(payload: dict[str, Any]) -> None:
    if type(payload["stage"]) is not str or payload["stage"] != "action_effect":
        raise ValueError("invalid_action_effect_stage")
    for field in (
        "execution_sha256",
        "controller_decision_sha256",
        "action_sha256",
        "before_state_sha256",
        "source_receipt_sha256",
    ):
        _effect_require_hash(payload[field], f"invalid_action_effect_{field}")
    step_index = payload["step_index"]
    if type(step_index) is not int or step_index < 1:
        raise ValueError("invalid_action_effect_step_index")

    action_kind = payload["action_kind"]
    if type(action_kind) is not str or action_kind not in _ACTION_EFFECT_ACTION_KINDS:
        raise ValueError("invalid_action_effect_action_kind")
    source_kind = payload["source_kind"]
    if type(source_kind) is not str or source_kind not in _ACTION_EFFECT_SOURCE_KINDS:
        raise ValueError("invalid_action_effect_source_kind")
    source_receipt_kind = payload["source_receipt_kind"]
    if (
        type(source_receipt_kind) is not str
        or source_receipt_kind not in _ACTION_EFFECT_SOURCE_RECEIPT_KINDS
    ):
        raise ValueError("invalid_action_effect_source_receipt_kind")
    outcome = payload["outcome"]
    if type(outcome) is not str or outcome not in _ACTION_EFFECT_OUTCOMES:
        raise ValueError("invalid_action_effect_outcome")
    call_performed = payload["call_performed"]
    if type(call_performed) is not bool:
        raise TypeError("invalid_action_effect_call_performed")

    obligation_key = payload["obligation_key"]
    target_evidence_id = payload["target_evidence_id"]
    if action_kind in _ACTION_EFFECT_TERMINAL_ACTIONS:
        if obligation_key is not None or target_evidence_id is not None:
            raise ValueError("invalid_action_effect_target")
    elif action_kind in _ACTION_EFFECT_OBLIGATION_ACTIONS:
        if (
            type(obligation_key) is not str
            or not obligation_key
            or target_evidence_id is not None
        ):
            raise ValueError("invalid_action_effect_target")
    elif action_kind in _ACTION_EFFECT_EVIDENCE_ACTIONS:
        if (
            type(obligation_key) is not str
            or not obligation_key
            or type(target_evidence_id) is not str
            or not target_evidence_id
        ):
            raise ValueError("invalid_action_effect_target")
    else:  # pragma: no cover - closed enum above makes this defensive only
        raise ValueError("invalid_action_effect_target")

    if source_kind == "follow_up" and action_kind in {
        "retrieve_dense",
        "retrieve_lexical",
        "fuse",
    }:
        raise ValueError("invalid_action_effect_source_kind_for_receipt")
    if not _valid_action_effect_row(
        action_kind=action_kind,
        source_receipt_kind=source_receipt_kind,
        outcome=outcome,
        call_performed=call_performed,
    ):
        raise ValueError("invalid_action_effect_matrix_row")

    ordered_evidence_ids = _effect_string_tuple(
        payload["ordered_evidence_ids"],
        "invalid_action_effect_ordered_evidence_ids",
    )
    parent_hashes = _effect_string_tuple(
        payload["parent_context_receipt_sha256s"],
        "invalid_action_effect_parent_context_receipt_sha256s",
        hashes=True,
    )
    bridge_hashes = _effect_string_tuple(
        payload["bridge_context_receipt_sha256s"],
        "invalid_action_effect_bridge_context_receipt_sha256s",
        hashes=True,
    )

    if outcome == "applied":
        if action_kind == "expand_parent":
            if ordered_evidence_ids:
                raise ValueError("parent_action_effect_must_not_promote_evidence")
        elif not ordered_evidence_ids:
            raise ValueError("applied_action_effect_requires_evidence")
    elif action_kind == "rerank" and outcome == "unavailable":
        if not ordered_evidence_ids:
            raise ValueError("unavailable_rerank_requires_identity_projection")
    elif ordered_evidence_ids:
        raise ValueError("nonapplied_action_effect_must_not_promote_evidence")

    context_actions = {"expand_parent", "bridge_table", "bridge_figure", "rerank", "verify_slot"}
    if action_kind not in context_actions and (parent_hashes or bridge_hashes):
        raise ValueError("action_effect_context_not_allowed")
    if source_receipt_kind == "controller_decision" and (parent_hashes or bridge_hashes):
        raise ValueError("controller_action_effect_context_not_allowed")
    source_sha256 = payload["source_receipt_sha256"]
    if source_receipt_kind == "parent_context":
        if parent_hashes != (source_sha256,) or bridge_hashes:
            raise ValueError("invalid_parent_action_effect_context")
    elif action_kind == "expand_parent" and parent_hashes:
        raise ValueError("invalid_parent_action_effect_context")
    if source_receipt_kind == "bridge_context":
        if bridge_hashes != (source_sha256,) or parent_hashes:
            raise ValueError("invalid_bridge_action_effect_context")
    elif action_kind in {"bridge_table", "bridge_figure"} and bridge_hashes:
        raise ValueError("invalid_bridge_action_effect_context")

    absence_sha256 = payload["absence_confirmation_sha256"]
    if absence_sha256 is not None:
        _effect_require_hash(
            absence_sha256,
            "invalid_action_effect_absence_confirmation_sha256",
        )
    if action_kind != "verify_slot" and absence_sha256 is not None:
        raise ValueError("action_effect_absence_not_allowed")
    if source_receipt_kind == "absence_confirmation":
        if absence_sha256 != source_sha256 or parent_hashes or bridge_hashes:
            raise ValueError("action_effect_absence_source_mismatch")
    elif source_receipt_kind == "semantic_verification" and outcome == "unsupported":
        if absence_sha256 is None or absence_sha256 == source_sha256:
            raise ValueError("unsupported_action_effect_requires_absence")
    elif absence_sha256 is not None:
        raise ValueError("action_effect_absence_not_allowed")

    if (
        source_receipt_kind == "controller_decision"
        and source_sha256 != payload["controller_decision_sha256"]
    ):
        raise ValueError("action_effect_controller_source_mismatch")


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class ActionEffectReceipt:
    """Closed structural action-effect value; never execution authority."""

    stage: str
    execution_sha256: str
    step_index: int
    controller_decision_sha256: str
    action_kind: str
    action_sha256: str
    obligation_key: str | None
    target_evidence_id: str | None
    before_state_sha256: str
    source_kind: str
    source_receipt_kind: str
    source_receipt_sha256: str
    outcome: str
    ordered_evidence_ids: tuple[str, ...]
    parent_context_receipt_sha256s: tuple[str, ...]
    bridge_context_receipt_sha256s: tuple[str, ...]
    absence_confirmation_sha256: str | None
    call_performed: bool
    effect_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("action_effect_receipt_factory_required")

    def __copy__(self) -> object:
        raise TypeError("action_effect_receipt_not_serializable")

    def __deepcopy__(self, memo: object) -> object:
        raise TypeError("action_effect_receipt_not_serializable")

    def __reduce__(self) -> object:
        raise TypeError("action_effect_receipt_not_serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        raise TypeError("action_effect_receipt_not_serializable")

    @classmethod
    def _create(
        cls,
        *,
        payload: dict[str, Any],
        _token: object,
    ) -> ActionEffectReceipt:
        if cls is not ActionEffectReceipt or _token is not _ACTION_EFFECT_RECEIPT_TOKEN:
            raise ValueError("action_effect_receipt_factory_required")
        closed = _closed_dict(
            payload,
            _ACTION_EFFECT_PAYLOAD_FIELDS,
            "action_effect_receipt_fields",
        )
        _validate_action_effect_receipt_payload(closed)
        result = object.__new__(cls)
        for field in _ACTION_EFFECT_PAYLOAD_FIELDS:
            object.__setattr__(result, field, closed[field])
        serialized = result._payload_dict()
        object.__setattr__(result, "effect_sha256", _canonical_sha256(serialized))
        validate_action_effect_receipt(receipt=result)
        return result

    def _payload_dict(self) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "stage": self.stage,
            "execution_sha256": self.execution_sha256,
            "step_index": self.step_index,
            "controller_decision_sha256": self.controller_decision_sha256,
            "action_kind": self.action_kind,
            "action_sha256": self.action_sha256,
            "obligation_key": self.obligation_key,
            "target_evidence_id": self.target_evidence_id,
            "before_state_sha256": self.before_state_sha256,
            "source_kind": self.source_kind,
            "source_receipt_kind": self.source_receipt_kind,
            "source_receipt_sha256": self.source_receipt_sha256,
            "outcome": self.outcome,
            "ordered_evidence_ids": list(self.ordered_evidence_ids),
            "parent_context_receipt_sha256s": list(
                self.parent_context_receipt_sha256s
            ),
            "bridge_context_receipt_sha256s": list(
                self.bridge_context_receipt_sha256s
            ),
            "absence_confirmation_sha256": self.absence_confirmation_sha256,
            "call_performed": self.call_performed,
        }

    def to_dict(self) -> dict[str, Any]:
        validate_action_effect_receipt(receipt=self)
        return {**self._payload_dict(), "effect_sha256": self.effect_sha256}


def validate_action_effect_receipt(*, receipt: ActionEffectReceipt) -> None:
    """Validate structure only; this grants no execution authority."""

    if type(receipt) is not ActionEffectReceipt:
        raise TypeError("invalid_action_effect_receipt")
    payload = {
        field: getattr(receipt, field)
        for field in _ACTION_EFFECT_PAYLOAD_FIELDS
    }
    _validate_action_effect_receipt_payload(payload)
    _effect_require_hash(receipt.effect_sha256, "invalid_action_effect_sha256")
    expected = _canonical_sha256(receipt._payload_dict())
    if receipt.effect_sha256 != expected:
        raise ValueError("action_effect_sha256_mismatch")


@dataclass(frozen=True, slots=True, init=False)
class SemanticValueSupport:
    """One canonical typed value and the evidence that supports it.

    This object carries no execution authority.  Its constructor is closed so
    all values pass through the same strict canonicalization boundary.
    """

    value_type: str
    canonical_value: str
    support_evidence_ids: tuple[str, ...]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("semantic_value_support_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        value_type: str,
        canonical_value: object,
        support_evidence_ids: tuple[str, ...],
        _token: object,
    ) -> SemanticValueSupport:
        if _token is not _VALUE_TOKEN:
            raise ValueError("semantic_value_support_factory_required")
        if type(value_type) is not str or value_type not in _VALUE_TYPES:
            raise ValueError("invalid_semantic_value_type")
        canonical = _canonical_value(value_type, canonical_value)
        support = _exact_ids(
            support_evidence_ids,
            "semantic_value_support_evidence_ids",
            allow_empty=False,
        )
        result = object.__new__(cls)
        object.__setattr__(result, "value_type", value_type)
        object.__setattr__(result, "canonical_value", canonical)
        object.__setattr__(result, "support_evidence_ids", support)
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "value_type": self.value_type,
            "canonical_value": self.canonical_value,
            "support_evidence_ids": list(self.support_evidence_ids),
        }


@dataclass(frozen=True, slots=True, init=False)
class _SemanticVerificationProjection:
    disposition: str
    field: str | None
    verified_evidence_ids: tuple[str, ...]
    contradicted_evidence_ids: tuple[str, ...]
    values: tuple[SemanticValueSupport, ...]
    result_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("semantic_verification_projection_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        disposition: str,
        field: str | None,
        verified_evidence_ids: tuple[str, ...],
        contradicted_evidence_ids: tuple[str, ...],
        values: tuple[SemanticValueSupport, ...],
        _token: object,
    ) -> _SemanticVerificationProjection:
        if _token is not _PROJECTION_TOKEN:
            raise ValueError("semantic_verification_projection_factory_required")
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "disposition": disposition,
            "field": field,
            "verified_evidence_ids": list(verified_evidence_ids),
            "contradicted_evidence_ids": list(contradicted_evidence_ids),
            "values": [value.to_dict() for value in values],
        }
        result = object.__new__(cls)
        object.__setattr__(result, "disposition", disposition)
        object.__setattr__(result, "field", field)
        object.__setattr__(result, "verified_evidence_ids", verified_evidence_ids)
        object.__setattr__(
            result, "contradicted_evidence_ids", contradicted_evidence_ids
        )
        object.__setattr__(result, "values", values)
        object.__setattr__(result, "result_sha256", _canonical_sha256(payload))
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "disposition": self.disposition,
            "field": self.field,
            "verified_evidence_ids": list(self.verified_evidence_ids),
            "contradicted_evidence_ids": list(self.contradicted_evidence_ids),
            "values": [value.to_dict() for value in self.values],
            "result_sha256": self.result_sha256,
        }


def _normalize_semantic_verifier_result(
    raw_result: object,
    *,
    field: str | None,
    ordered_supplied_ids: tuple[str, ...],
    promotable_ids: tuple[str, ...],
) -> _SemanticVerificationProjection:
    """Normalize one untrusted verifier result into a non-authoritative value.

    Evidence order is derived from the execution owner's supplied order rather
    than trusted from model output.  Only ``promotable_ids`` may support a claim;
    auxiliary parent context may be supplied separately by the execution owner
    but cannot appear in either support projection.
    """

    if field is not None and (
        type(field) is not str or _FIELD.fullmatch(field) is None
    ):
        raise ValueError("invalid_semantic_field")
    supplied = _exact_ids(
        ordered_supplied_ids, "semantic_supplied_evidence_ids", allow_empty=True
    )
    promotable = _exact_ids(
        promotable_ids, "semantic_promotable_evidence_ids", allow_empty=True
    )
    if _ordered_subset(
        promotable,
        universe=supplied,
        code="semantic_promotable_evidence_not_supplied",
    ) != promotable:
        raise ValueError("semantic_promotable_evidence_order_mismatch")

    raw = _closed_dict(
        raw_result, _RESULT_FIELDS, "semantic_verifier_result_fields"
    )
    if raw["schema_version"] != _SCHEMA_VERSION:
        raise ValueError("unsupported_semantic_verifier_result_version")
    disposition = raw["disposition"]
    if type(disposition) is not str or disposition not in _DISPOSITIONS:
        raise ValueError("invalid_semantic_disposition")
    raw_support_indexes = _exact_indexes(
        raw["support_indexes"],
        "semantic_support_indexes",
        maximum=len(promotable),
    )
    ordered_support = _support_ids_from_indexes(
        raw_support_indexes,
        supplied=supplied,
        promotable=promotable,
        code="semantic_support_index_not_promotable",
    )

    raw_values = raw["values"]
    if type(raw_values) is not list:
        raise TypeError("semantic_values_array_required")
    if field is None and raw_values:
        raise ValueError("semantic_values_forbidden_without_field")
    if field is not None and disposition == "supported" and len(raw_values) != 1:
        raise ValueError("semantic_supported_value_required")
    if disposition == "contradicted" and field is not None and len(raw_values) < 2:
        raise ValueError("semantic_contradiction_values_required")
    if disposition == "unsupported" and raw_values:
        raise ValueError("semantic_unsupported_values_forbidden")
    if len(raw_values) > len(promotable):
        raise ValueError("semantic_value_count_exceeds_promotable_evidence")

    values: list[SemanticValueSupport] = []
    value_keys: set[tuple[str, str]] = set()
    used_value_support: set[str] = set()
    for raw_value in raw_values:
        value = _closed_dict(
            raw_value, _VALUE_FIELDS, "semantic_value_support_fields"
        )
        value_type = value["value_type"]
        if type(value_type) is not str or value_type not in _VALUE_TYPES:
            raise ValueError("invalid_semantic_value_type")
        if field is not None and value_type != _field_value_type(field):
            raise ValueError("semantic_value_type_not_approved_for_field")
        canonical_value = _canonical_value(value_type, value["canonical_value"])
        support_indexes = _exact_indexes(
            value["support_indexes"],
            "semantic_value_support_indexes",
            maximum=len(promotable),
        )
        if not support_indexes:
            raise ValueError("semantic_value_support_indexes_required")
        ordered_value_support = _support_ids_from_indexes(
            support_indexes,
            supplied=supplied,
            promotable=promotable,
            code="semantic_value_support_index_not_promotable",
        )
        key = (value_type, canonical_value)
        if key in value_keys:
            raise ValueError("duplicate_semantic_canonical_value")
        value_keys.add(key)
        if disposition == "contradicted" and used_value_support.intersection(
            ordered_value_support
        ):
            raise ValueError("semantic_contradiction_support_not_independent")
        used_value_support.update(ordered_value_support)
        values.append(
            SemanticValueSupport._create(
                value_type=value_type,
                canonical_value=canonical_value,
                support_evidence_ids=ordered_value_support,
                _token=_VALUE_TOKEN,
            )
        )

    normalized_values = tuple(
        sorted(
            values,
            key=lambda value: (
                value.value_type,
                value.canonical_value,
                value.support_evidence_ids,
            ),
        )
    )
    value_union = set().union(
        *(set(value.support_evidence_ids) for value in normalized_values)
    )
    if field is not None and disposition in {"supported", "contradicted"}:
        if set(ordered_support) != value_union:
            raise ValueError("semantic_support_union_mismatch")
    elif value_union:
        raise ValueError("semantic_value_support_forbidden")

    if disposition == "supported":
        if not ordered_support:
            raise ValueError("semantic_supported_evidence_required")
        verified_ids = ordered_support
        contradicted_ids: tuple[str, ...] = ()
    elif disposition == "contradicted":
        if not ordered_support:
            raise ValueError("semantic_contradicted_evidence_required")
        if field is not None and len(
            {value.value_type for value in normalized_values}
        ) != 1:
            raise ValueError("semantic_contradiction_value_type_mismatch")
        verified_ids = ()
        contradicted_ids = ordered_support
    else:
        if ordered_support:
            raise ValueError("semantic_unsupported_support_forbidden")
        verified_ids = ()
        contradicted_ids = ()

    return _SemanticVerificationProjection._create(
        disposition=disposition,
        field=field,
        verified_evidence_ids=verified_ids,
        contradicted_evidence_ids=contradicted_ids,
        values=normalized_values,
        _token=_PROJECTION_TOKEN,
    )


@dataclass(frozen=True, slots=True, repr=False, init=False)
class _RerankProjection:
    """Closed, non-authoritative projection of one reranker result."""

    ordered_indexes: tuple[int, ...]
    result_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("rerank_projection_factory_required")

    def __copy__(self) -> object:
        raise TypeError("rerank_projection_not_serializable")

    def __deepcopy__(self, memo: object) -> object:
        raise TypeError("rerank_projection_not_serializable")

    def __reduce__(self) -> object:
        raise TypeError("rerank_projection_not_serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        raise TypeError("rerank_projection_not_serializable")

    @classmethod
    def _create(
        cls,
        *,
        ordered_indexes: tuple[int, ...],
        _token: object,
    ) -> _RerankProjection:
        if _token is not _RERANK_PROJECTION_TOKEN:
            raise ValueError("rerank_projection_factory_required")
        if (
            type(ordered_indexes) is not tuple
            or not ordered_indexes
            or any(type(index) is not int or index < 0 for index in ordered_indexes)
            or len(ordered_indexes) != len(set(ordered_indexes))
        ):
            raise ValueError("invalid_rerank_projection_indexes")
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "ordered_indexes": list(ordered_indexes),
        }
        result = object.__new__(cls)
        object.__setattr__(result, "ordered_indexes", ordered_indexes)
        object.__setattr__(result, "result_sha256", _canonical_sha256(payload))
        return result


def _normalize_reranker_result(
    raw_result: object,
    *,
    input_count: int,
    rerank_k: int,
) -> _RerankProjection:
    """Normalize an ID-less reranker response into a bounded index projection."""

    if type(input_count) is not int or input_count < 1:
        raise ValueError("invalid_reranker_input_count")
    if type(rerank_k) is not int or rerank_k < 1:
        raise ValueError("invalid_reranker_limit")
    raw = _closed_dict(
        raw_result,
        _RERANK_RESULT_FIELDS,
        "reranker_result_fields",
    )
    if raw["schema_version"] != _SCHEMA_VERSION:
        raise ValueError("unsupported_reranker_result_version")
    ordered_indexes = _exact_indexes(
        raw["ordered_indexes"],
        "reranker_ordered_indexes",
        maximum=min(rerank_k, input_count),
    )
    if not ordered_indexes:
        raise ValueError("reranker_ordered_indexes_required")
    if any(index >= input_count for index in ordered_indexes):
        raise ValueError("reranker_ordered_index_out_of_range")
    return _RerankProjection._create(
        ordered_indexes=ordered_indexes,
        _token=_RERANK_PROJECTION_TOKEN,
    )


__all__ = (
    "ActionEffectReceipt",
    "SemanticValueSupport",
    "validate_action_effect_receipt",
)
