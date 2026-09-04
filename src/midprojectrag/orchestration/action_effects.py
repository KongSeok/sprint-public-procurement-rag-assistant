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


__all__ = ("SemanticValueSupport",)
