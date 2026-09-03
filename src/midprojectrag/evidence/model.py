"""Immutable, content-addressed evidence DTOs; no parent-store or corpus I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import math
from typing import Any, Literal


_PARENT_KINDS = frozenset(
    {"pdf_page", "page_v1", "hwp_section_flow", "rendered_hwp_page"}
)
_EVIDENCE_KINDS = frozenset(
    {"page", "text", "table_row_group", "figure_object", "analytics_result"}
)
_LOCATOR_FIELDS = frozenset(
    {"page", "flow_id", "section_path", "object_id", "bbox", "row_range", "char_range"}
)
_PARENT_FIELDS = frozenset(
    {"doc_id", "kind", "text", "source_block_ids", "locator", "parent_id", "content_sha256"}
)
_EVIDENCE_FIELDS = frozenset(
    {
        "doc_id", "kind", "text", "parent_id", "source_block_ids", "locator",
        "source_chunk_ids", "crop_ref", "support_refs", "evidence_id", "content_sha256",
    }
)


def _string(value: Any, name: str, *, nonblank: bool = True) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be a string")
    if nonblank and not value.strip():
        raise ValueError(f"{name} must not be blank")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{name} must be valid UTF-8 text") from exc
    return value


def _optional_string(value: Any, name: str) -> str | None:
    return None if value is None else _string(value, name)


def _sequence(value: Any, name: str) -> tuple:
    if type(value) not in (tuple, list):
        raise TypeError(f"{name} must be a tuple or list")
    return tuple(value)


def _strings(
    value: Any, name: str, *, required: bool = False, unique: bool = True
) -> tuple[str, ...]:
    result = tuple(_string(item, name) for item in _sequence(value, name))
    if required and not result:
        raise ValueError(f"{name} must contain at least one source ID")
    if unique and len(result) != len(set(result)):
        raise ValueError(f"{name} must not contain duplicate IDs")
    return result


def _integer(value: Any, name: str, *, minimum: int) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer (not bool)")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _snapshot(value: Any, expected: frozenset[str], name: str) -> dict[str, Any]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise TypeError(f"{name} must be a JSON object with string keys")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ValueError(f"{name} fields differ: missing={missing}, unknown={unknown}")
    return value


def _json_array(value: Any, name: str, *, optional: bool = False) -> Any:
    if optional and value is None:
        return None
    if type(value) is not list:
        raise TypeError(f"{name} must be a JSON array")
    return value


def _identity(prefix: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return prefix + sha256(canonical.encode("utf-8")).hexdigest()


def _content_sha256(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _assert_computed(payload: dict[str, Any], name: str, expected: str) -> None:
    if _string(payload[name], name) != expected:
        raise ValueError(f"{name} does not match the canonical content")


def _parent_reference(value: Any) -> str:
    value = _string(value, "parent_id")
    digest = value.removeprefix("pr_")
    if not value.startswith("pr_") or len(digest) != 64 or any(
        char not in "0123456789abcdef" for char in digest
    ):
        raise ValueError("parent_id must be pr_ followed by a lowercase SHA-256 digest")
    return value


def _crop_reference(value: Any) -> str | None:
    if value is None:
        return None
    value = _string(value, "crop_ref")
    # A literal, portable local artifact path, never a URL or a decoded URI.
    if (
        value.startswith("/")
        or any(char in value for char in "\\:?#")
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        raise ValueError("crop_ref must be a local relative file path without traversal")
    return value


@dataclass(frozen=True, slots=True)
class Locator:
    """Source coordinates, without any claim that the referenced source exists."""

    page: int | None = None
    flow_id: str | None = None
    section_path: tuple[str, ...] = ()
    object_id: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    row_range: tuple[int, int] | None = None
    char_range: tuple[int, int] | None = None

    def __post_init__(self) -> None:
        if self.page is not None:
            _integer(self.page, "page", minimum=1)
        _optional_string(self.flow_id, "flow_id")
        _optional_string(self.object_id, "object_id")
        object.__setattr__(
            self, "section_path", _strings(self.section_path, "section_path", unique=False)
        )
        if self.bbox is not None:
            coordinates = _sequence(self.bbox, "bbox")
            if len(coordinates) != 4:
                raise ValueError("bbox must have four coordinates (x0, y0, x1, y1)")
            if any(type(value) not in (int, float) for value in coordinates):
                raise TypeError("bbox coordinates must be numbers (not bool)")
            try:
                bbox = tuple(float(value) for value in coordinates)
            except OverflowError as exc:
                raise ValueError("bbox coordinates must be finite") from exc
            if not all(math.isfinite(value) for value in bbox):
                raise ValueError("bbox coordinates must be finite")
            if any(type(raw) is int and int(converted) != raw for raw, converted in zip(coordinates, bbox)):
                raise ValueError("bbox integer precision loss")
            if bbox[0] > bbox[2] or bbox[1] > bbox[3]:
                raise ValueError("bbox must not have inverted coordinates")
            object.__setattr__(self, "bbox", bbox)
        if self.row_range is not None:
            rows = _sequence(self.row_range, "row_range")
            if len(rows) != 2:
                raise ValueError("row_range must have two inclusive endpoints")
            start, end = (_integer(value, "row_range", minimum=0) for value in rows)
            if start > end:
                raise ValueError("row_range start must not exceed its end")
            object.__setattr__(self, "row_range", (start, end))
        if self.char_range is not None:
            span = _sequence(self.char_range, "char_range")
            if len(span) != 2:
                raise ValueError("char_range must have two half-open endpoints")
            start, end = (_integer(value, "char_range", minimum=0) for value in span)
            if start >= end:
                raise ValueError("char_range must have positive length")
            object.__setattr__(self, "char_range", (start, end))

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "flow_id": self.flow_id,
            "section_path": list(self.section_path),
            "object_id": self.object_id,
            "bbox": None if self.bbox is None else list(self.bbox),
            "row_range": None if self.row_range is None else list(self.row_range),
            "char_range": None if self.char_range is None else list(self.char_range),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Locator:
        payload = _snapshot(payload, _LOCATOR_FIELDS, "Locator")
        return cls(
            page=payload["page"],
            flow_id=payload["flow_id"],
            section_path=_json_array(payload["section_path"], "section_path"),
            object_id=payload["object_id"],
            bbox=_json_array(payload["bbox"], "bbox", optional=True),
            row_range=_json_array(payload["row_range"], "row_range", optional=True),
            char_range=_json_array(payload["char_range"], "char_range", optional=True),
        )


@dataclass(frozen=True, slots=True)
class ProvenanceParent:
    """Content-addressed parent used for provenance, not as a retrieval candidate."""

    doc_id: str
    kind: Literal["pdf_page", "page_v1", "hwp_section_flow", "rendered_hwp_page"]
    text: str
    source_block_ids: tuple[str, ...]
    locator: Locator
    parent_id: str = field(init=False)
    content_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        _string(self.doc_id, "doc_id")
        if _string(self.kind, "kind") not in _PARENT_KINDS:
            raise ValueError("unsupported provenance parent kind")
        _string(self.text, "text", nonblank=False)
        object.__setattr__(
            self, "source_block_ids", _strings(self.source_block_ids, "source_block_ids", required=True)
        )
        if type(self.locator) is not Locator:
            raise TypeError("locator must be a Locator")
        if self.kind == "hwp_section_flow":
            if self.locator.flow_id is None or self.locator.page is not None:
                raise ValueError("hwp_section_flow requires flow_id and must not invent a page")
        elif self.locator.page is None:
            raise ValueError("page provenance parents require a physical page locator")
        object.__setattr__(self, "content_sha256", _content_sha256(self.text))
        object.__setattr__(self, "parent_id", _identity("pr_", self._identity_dict()))

    def _identity_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "kind": self.kind,
            "text": self.text,
            "source_block_ids": list(self.source_block_ids),
            "locator": self.locator.to_dict(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._identity_dict(),
            "parent_id": self.parent_id,
            "content_sha256": self.content_sha256,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ProvenanceParent:
        payload = _snapshot(payload, _PARENT_FIELDS, "ProvenanceParent")
        parent = cls(
            doc_id=payload["doc_id"],
            kind=payload["kind"],
            text=payload["text"],
            source_block_ids=_json_array(payload["source_block_ids"], "source_block_ids"),
            locator=Locator.from_dict(payload["locator"]),
        )
        _assert_computed(payload, "parent_id", parent.parent_id)
        _assert_computed(payload, "content_sha256", parent.content_sha256)
        return parent


@dataclass(frozen=True, slots=True)
class Evidence:
    """Retrievable evidence whose parent binding is checked by the future store."""

    doc_id: str
    kind: Literal["page", "text", "table_row_group", "figure_object", "analytics_result"]
    text: str
    parent_id: str
    source_block_ids: tuple[str, ...]
    locator: Locator
    source_chunk_ids: tuple[str, ...] = ()
    crop_ref: str | None = None
    support_refs: tuple[str, ...] = ()
    evidence_id: str = field(init=False)
    content_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        _string(self.doc_id, "doc_id")
        if _string(self.kind, "kind") not in _EVIDENCE_KINDS:
            raise ValueError("unsupported evidence kind")
        _string(self.text, "text", nonblank=not (self.kind == "figure_object" and self.crop_ref is not None))
        _parent_reference(self.parent_id)
        if type(self.locator) is not Locator:
            raise TypeError("locator must be a Locator")
        for name in ("source_block_ids", "source_chunk_ids", "support_refs"):
            object.__setattr__(
                self, name, _strings(getattr(self, name), name, required=name == "source_block_ids")
            )
        _crop_reference(self.crop_ref)
        object.__setattr__(self, "content_sha256", _content_sha256(self.text))
        object.__setattr__(self, "evidence_id", _identity("ev_", self._identity_dict()))

    def _identity_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "kind": self.kind,
            "text": self.text,
            "parent_id": self.parent_id,
            "source_block_ids": list(self.source_block_ids),
            "locator": self.locator.to_dict(),
            "source_chunk_ids": list(self.source_chunk_ids),
            "crop_ref": self.crop_ref,
            "support_refs": list(self.support_refs),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._identity_dict(),
            "evidence_id": self.evidence_id,
            "content_sha256": self.content_sha256,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Evidence:
        payload = _snapshot(payload, _EVIDENCE_FIELDS, "Evidence")
        evidence = cls(
            doc_id=payload["doc_id"],
            kind=payload["kind"],
            text=payload["text"],
            parent_id=payload["parent_id"],
            source_block_ids=_json_array(payload["source_block_ids"], "source_block_ids"),
            locator=Locator.from_dict(payload["locator"]),
            source_chunk_ids=_json_array(payload["source_chunk_ids"], "source_chunk_ids"),
            crop_ref=payload["crop_ref"],
            support_refs=_json_array(payload["support_refs"], "support_refs"),
        )
        _assert_computed(payload, "evidence_id", evidence.evidence_id)
        _assert_computed(payload, "content_sha256", evidence.content_sha256)
        return evidence
