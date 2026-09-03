"""Closed runtime DTOs. Evaluation labels never participate in projection.

Do not import evaluation, model, or retrieval implementations into this module.
Values that independently occur in a user request and a gold answer are legal;
provenance is enforced by allowlisted projection, not a text blacklist.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from types import MappingProxyType
from typing import Any, Mapping


class IntegrityError(ValueError):
    """Content-free error codes suitable for a privacy-preserving trace."""


RUNTIME_FIELDS = frozenset({
    "request_id", "question", "history", "document_scope", "metadata_filters",
    "options", "prior_citation_state",
})


def _closed(value: Any, keys: set[str] | frozenset[str], code: str) -> Mapping:
    if not isinstance(value, Mapping) or set(value) - keys:
        raise IntegrityError(code)
    return value


def _string(value: Any, code: str, *, maximum: int = 12000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise IntegrityError(code)
    return value


def _sequence(value: Any, code: str) -> tuple:
    if not isinstance(value, (list, tuple)):
        raise IntegrityError(code)
    return tuple(value)


def _ids(value: Any) -> tuple[str, ...]:
    values = tuple(_string(v, "invalid_id", maximum=256) for v in _sequence(value, "invalid_ids"))
    if len(values) != len(set(values)):
        raise IntegrityError("duplicate_ids")
    return values


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(k, str) for k in value):
            raise IntegrityError("invalid_json_key")
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise IntegrityError("invalid_json_value")


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_thaw(v) for v in value]
    return value


def _validate_runtime(raw: Mapping) -> dict:
    _closed(raw, RUNTIME_FIELDS, "unknown_runtime_field")
    result = dict(raw)
    _string(result["request_id"], "invalid_request_id", maximum=128)
    _string(result["question"], "invalid_question", maximum=4000)
    scope = _closed(result["document_scope"], {"mode", "doc_ids"}, "invalid_scope")
    ids = _ids(scope.get("doc_ids", ()))
    if scope.get("mode") not in ("all", "explicit") or (scope["mode"] == "all" and ids):
        raise IntegrityError("invalid_scope")
    result["document_scope"] = {"mode": scope["mode"], "doc_ids": ids}
    history = _sequence(result["history"], "invalid_history")
    if len(history) > 20:
        raise IntegrityError("history_limit")
    for turn in history:
        _closed(turn, {"turn_id", "role", "content", "cited_doc_ids", "cited_evidence_ids"}, "invalid_history")
        if turn.get("role") not in ("user", "assistant"):
            raise IntegrityError("invalid_history_role")
        _string(turn.get("content"), "invalid_history_content")
        if "turn_id" in turn:
            _string(turn["turn_id"], "invalid_turn_id", maximum=128)
        for key in ("cited_doc_ids", "cited_evidence_ids"):
            if key in turn:
                _ids(turn[key])
                if turn["role"] != "assistant" and turn[key]:
                    raise IntegrityError("user_turn_has_citations")
    for predicate in _sequence(result["metadata_filters"], "invalid_metadata_filters"):
        _closed(predicate, {"field", "operator", "value"}, "invalid_metadata_filter")
        _string(predicate.get("field"), "invalid_filter_field", maximum=128)
        _string(predicate.get("operator"), "invalid_filter_operator", maximum=32)
        if "value" not in predicate:
            raise IntegrityError("missing_filter_value")
        values = predicate["value"] if isinstance(predicate["value"], (list, tuple)) else [predicate["value"]]
        if any(isinstance(v, (Mapping, list, tuple)) for v in values):
            raise IntegrityError("invalid_filter_value")
        _freeze(values)
    options = dict(_closed(result["options"], {"max_citations", "profile", "allow_global_fallback"}, "invalid_options"))
    if "max_citations" in options and (type(options["max_citations"]) is not int or not 1 <= options["max_citations"] <= 1000):
        raise IntegrityError("invalid_citation_limit")
    if "profile" in options:
        _string(options["profile"], "invalid_profile", maximum=128)
    if "allow_global_fallback" in options and type(options["allow_global_fallback"]) is not bool:
        raise IntegrityError("invalid_fallback_option")
    prior = result["prior_citation_state"]
    if prior is not None:
        _closed(prior, {"cited_doc_ids", "cited_evidence_ids", "resolved_entities", "list_doc_ids", "comparison_doc_ids"}, "invalid_citation_state")
        for values in prior.values():
            _ids(values)
    return result


@dataclass(frozen=True)
class RuntimeRequest:
    question: str
    request_id: str = "runtime"
    history: tuple[Mapping, ...] = ()
    document_scope: Mapping = field(default_factory=lambda: {"mode": "all", "doc_ids": []})
    metadata_filters: tuple[Mapping, ...] = ()
    options: Mapping = field(default_factory=dict)
    prior_citation_state: Mapping | None = None

    def __post_init__(self) -> None:
        values = _validate_runtime({key: getattr(self, key) for key in RUNTIME_FIELDS})
        for key, value in values.items():
            object.__setattr__(self, key, _freeze(value))

    @classmethod
    def from_dict(cls, value: Mapping) -> RuntimeRequest:
        _closed(value, RUNTIME_FIELDS | {"schema_version"}, "unknown_runtime_field")
        if value.get("schema_version", "1.0") != "1.0":
            raise IntegrityError("unsupported_runtime_version")
        if "question" not in value:
            raise IntegrityError("missing_question")
        return cls(**{k: v for k, v in value.items() if k in RUNTIME_FIELDS})

    def to_dict(self) -> dict:
        return {key: _thaw(getattr(self, key)) for key in sorted(RUNTIME_FIELDS)}

    @property
    def fingerprint(self) -> str:
        return sha256(json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def project_runtime(evaluation_row: Mapping) -> RuntimeRequest:
    """Copy only real request fields. Never inspect gold, expected, qrels or IDs."""
    if not isinstance(evaluation_row, Mapping):
        raise IntegrityError("invalid_projection_input")
    return RuntimeRequest.from_dict({k: evaluation_row[k] for k in RUNTIME_FIELDS if k in evaluation_row})


@dataclass(frozen=True)
class EvaluationCase:
    runtime: RuntimeRequest
    required_doc_ids: tuple[str, ...] = ()
    required_evidence_ids: tuple[str, ...] = ()
    qrels: Mapping = field(default_factory=dict)
    reference_answer: str = ""
    expected: Any = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.runtime, RuntimeRequest):
            raise IntegrityError("invalid_case_runtime")
        object.__setattr__(self, "required_doc_ids", _ids(self.required_doc_ids))
        object.__setattr__(self, "required_evidence_ids", _ids(self.required_evidence_ids))
        object.__setattr__(self, "qrels", _freeze(self.qrels))
        object.__setattr__(self, "expected", _freeze(self.expected))
        if not isinstance(self.reference_answer, str):
            raise IntegrityError("invalid_reference_answer")

    @classmethod
    def from_dict(cls, row: Mapping) -> EvaluationCase:
        runtime = project_runtime(row)
        return cls(runtime, **{key: row[key] for key in (
            "required_doc_ids", "required_evidence_ids", "qrels", "reference_answer", "expected"
        ) if key in row})


@dataclass(frozen=True)
class ResolvedScope:
    state: str = "unfiltered"
    doc_ids: frozenset[str] = frozenset()
    origin: str = "all"

    def __post_init__(self) -> None:
        if not isinstance(self.doc_ids, frozenset) or any(not isinstance(v, str) or not v for v in self.doc_ids):
            raise IntegrityError("invalid_resolved_scope_ids")
        if self.state not in ("unfiltered", "empty", "restricted"):
            raise IntegrityError("invalid_scope_state")
        if (self.state == "restricted") != bool(self.doc_ids):
            raise IntegrityError("inconsistent_scope_state")
        if self.origin not in ("all", "user_explicit", "followup_citations", "metadata_filter"):
            raise IntegrityError("invalid_scope_origin")

    @classmethod
    def from_allowed(cls, ids: frozenset[str] | None, *, origin: str = "all") -> ResolvedScope:
        if ids is None:
            return cls(origin=origin)
        return cls("restricted" if ids else "empty", ids, origin)

    @classmethod
    def from_request(cls, request: RuntimeRequest) -> ResolvedScope:
        if not isinstance(request, RuntimeRequest):
            raise IntegrityError("request_type_required")
        if request.document_scope["mode"] == "all":
            return cls()
        return cls.from_allowed(frozenset(request.document_scope["doc_ids"]), origin="user_explicit")

    @property
    def allowed_doc_ids(self) -> frozenset[str] | None:
        return None if self.state == "unfiltered" else self.doc_ids

    def intersect(self, ids: frozenset[str] | None, *, origin: str = "metadata_filter") -> ResolvedScope:
        if ids is None:
            return self
        if not isinstance(ids, frozenset):
            raise IntegrityError("invalid_filter_scope")
        filtered = ids if self.state == "unfiltered" else self.doc_ids & ids
        return ResolvedScope.from_allowed(filtered, origin=origin)

    def to_dict(self) -> dict:
        return {"state": self.state, "doc_ids": sorted(self.doc_ids), "origin": self.origin}


def scoped_search(search, query: str, *, limit: int, scope: ResolvedScope):
    """Shared lane boundary: an empty result set never becomes a global query."""
    if not isinstance(scope, ResolvedScope):
        raise IntegrityError("scope_type_required")
    if type(limit) is not int or limit < 1:
        raise IntegrityError("invalid_search_limit")
    if scope.state == "empty":
        return ()
    return search(query, limit=limit, allowed_doc_ids=scope.allowed_doc_ids)


_TEXT_FILTERS = frozenset({"agency", "format", "title", "doc_id", "category"})
_ORDERED_FILTERS = frozenset({"business_amount", "published_at", "bid_start_at", "bid_deadline_at"})


@dataclass(frozen=True)
class MetadataPredicate:
    field: str
    operator: str
    value: Any

    def __post_init__(self) -> None:
        # Reuse exactly the request boundary, including recursive payload rejection.
        RuntimeRequest(question="filter-validation", metadata_filters=({
            "field": self.field, "operator": self.operator, "value": self.value,
        },))
        object.__setattr__(self, "value", _freeze(self.value))

    @classmethod
    def from_dict(cls, raw: Mapping) -> MetadataPredicate:
        _closed(raw, {"field", "operator", "value"}, "invalid_metadata_filter")
        if set(raw) != {"field", "operator", "value"}:
            raise IntegrityError("missing_filter_field")
        return cls(**raw)

    @property
    def status(self) -> str:
        if self.field in _TEXT_FILTERS:
            operators = {"eq", "ne", "in", "contains"}
        elif self.field in _ORDERED_FILTERS:
            operators = {"eq", "ne", "in", "gt", "ge", "lt", "le", "between"}
        elif self.field in {"urgent", "reannounce"}:
            operators = {"eq", "ne"}
        else:
            return "unsupported_filter"
        if self.operator not in operators:
            return "unsupported_filter"
        if self.operator in {"in", "between"}:
            if not isinstance(self.value, tuple) or (self.operator == "between" and len(self.value) != 2):
                return "unresolved_constraint"
        elif isinstance(self.value, tuple):
            return "unresolved_constraint"
        values = self.value if isinstance(self.value, tuple) else (self.value,)
        comparable = []
        for value in values:
            if self.field == "business_amount":
                if type(value) not in (int, float) or not math.isfinite(value):
                    return "unresolved_constraint"
                comparable.append(value)
            elif self.field in _ORDERED_FILTERS:
                if not isinstance(value, str):
                    return "unresolved_constraint"
                try:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    return "unresolved_constraint"
                comparable.append(parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed)
            elif self.field in _TEXT_FILTERS:
                if not isinstance(value, str) or not value.strip():
                    return "unresolved_constraint"
                comparable.append(value)
            elif type(value) is not bool:
                return "unresolved_constraint"
        if self.operator == "between" and comparable[0] > comparable[1]:
            return "unresolved_constraint"
        return "supported"

    def to_dict(self) -> dict:
        return {"field": self.field, "operator": self.operator, "value": _thaw(self.value), "status": self.status}
