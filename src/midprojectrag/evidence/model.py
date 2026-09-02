from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Iterable, Mapping


_ID = re.compile(r"ev_[0-9a-f]{24}\Z")
_KINDS = frozenset({"page", "text", "table", "figure"})
_FIELDS = frozenset(
    {"evidence_id", "doc_id", "page", "kind", "text", "source_block_ids",
     "parent_id", "object_id", "bbox", "crop_ref", "section_path", "content_sha256",
     "source_chunk_ids", "evidence_type", "support_refs", "row_range"}
)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _finite_number(value: Any) -> bool:
    if type(value) not in {int, float}:
        return False
    try:
        return math.isfinite(float(value))
    except (ValueError, OverflowError):
        return False


def _string(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(code)
    return value


def _strings(value: Any, code: str, *, empty: bool = False, unique: bool = True) -> tuple[str, ...]:
    if not isinstance(value, tuple) or (not empty and not value):
        raise ValueError(code)
    for item in value:
        _string(item, code)
    if unique and len(set(value)) != len(value):
        raise ValueError(code)
    return value


@dataclass(frozen=True)
class Evidence:
    """Canonical evidence. Use ``create`` to derive the content-bound ID.

    bbox uses (left, top, right, bottom), not (x, y, width, height).
    Object-only figures may have empty text: that is a capability requirement,
    never evidence that a text-only generator can see pixels.
    """

    evidence_id: str
    doc_id: str
    page: int | None
    kind: str
    text: str
    source_block_ids: tuple[str, ...]
    parent_id: str | None = None
    object_id: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    crop_ref: str | None = None
    section_path: tuple[str, ...] = ()
    source_chunk_ids: tuple[str, ...] = ()
    evidence_type: str | None = None
    support_refs: tuple[str, ...] = ()
    row_range: tuple[int, int] | None = None
    content_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        _string(self.doc_id, "invalid_evidence_doc_id")
        if self.page is not None and (type(self.page) is not int or self.page < 1):
            raise ValueError("invalid_evidence_page")
        if not isinstance(self.kind, str) or self.kind not in _KINDS:
            raise ValueError("invalid_evidence_kind")
        if not isinstance(self.text, str) or "\x00" in self.text:
            raise ValueError("invalid_evidence_text")
        if not self.text.strip() and not (self.kind == "figure" and self.crop_ref):
            raise ValueError("empty_evidence_text")
        _strings(self.source_block_ids, "invalid_evidence_source_refs")
        _strings(self.section_path, "invalid_evidence_section_path", empty=True, unique=False)
        _strings(self.source_chunk_ids, "invalid_evidence_source_chunk_ids", empty=True)
        _strings(self.support_refs, "invalid_evidence_support_refs", empty=True)
        if self.evidence_type is not None:
            _string(self.evidence_type, "invalid_evidence_type")
            if self.evidence_type in {"ocr", "layout", "caption"} and self.kind != "figure":
                raise ValueError("evidence_type_kind_mismatch")
        if self.row_range is not None and (
            self.kind != "table" or not isinstance(self.row_range, tuple) or len(self.row_range) != 2
            or any(type(row) is not int for row in self.row_range)
            or self.row_range[0] < 0 or self.row_range[1] < self.row_range[0]
        ):
            raise ValueError("invalid_evidence_row_range")
        if self.parent_id is not None and (
            not isinstance(self.parent_id, str) or not _ID.fullmatch(self.parent_id)
        ):
            raise ValueError("invalid_evidence_parent_id")
        if self.kind == "page" and self.parent_id is not None:
            raise ValueError("page_evidence_must_be_root")
        if self.kind != "page" and self.parent_id is None:
            raise ValueError("evidence_parent_required")
        if self.kind in {"table", "figure"}:
            _string(self.object_id, "evidence_object_id_required")
        elif self.object_id is not None:
            raise ValueError("unexpected_evidence_object_id")
        if self.crop_ref is not None:
            _string(self.crop_ref, "invalid_evidence_crop_ref")
            if self.kind not in {"table", "figure"}:
                raise ValueError("unexpected_evidence_crop_ref")
        if self.bbox is not None:
            if (
                not isinstance(self.bbox, tuple) or len(self.bbox) != 4
                or any(not _finite_number(x) for x in self.bbox)
                or self.bbox[0] >= self.bbox[2] or self.bbox[1] >= self.bbox[3]
            ):
                raise ValueError("invalid_evidence_bbox")
            object.__setattr__(self, "bbox", tuple(float(x) for x in self.bbox))
        object.__setattr__(self, "content_sha256", _digest(self.text))
        if not isinstance(self.evidence_id, str) or not _ID.fullmatch(self.evidence_id):
            raise ValueError("invalid_evidence_id")
        if self.evidence_id != self._expected_id():
            raise ValueError("evidence_identity_mismatch")

    def _identity(self) -> dict[str, Any]:
        return {
            "version": "evidence-v1", "doc_id": self.doc_id, "page": self.page,
            "kind": self.kind, "content_sha256": self.content_sha256,
            "source_block_ids": list(self.source_block_ids), "parent_id": self.parent_id,
            "object_id": self.object_id, "bbox": self.bbox,
            "crop_ref": self.crop_ref, "section_path": list(self.section_path),
            "source_chunk_ids": list(self.source_chunk_ids), "evidence_type": self.evidence_type,
            "support_refs": list(self.support_refs), "row_range": self.row_range,
        }

    def _expected_id(self) -> str:
        return "ev_" + _digest(_canonical(self._identity()))[:24]

    @classmethod
    def create(
        cls, *, doc_id: str, page: int | None, kind: str, text: str,
        source_block_ids: tuple[str, ...], parent_id: str | None = None,
        object_id: str | None = None, bbox: tuple[float, float, float, float] | None = None,
        crop_ref: str | None = None, section_path: tuple[str, ...] = (),
        source_chunk_ids: tuple[str, ...] = (), evidence_type: str | None = None,
        support_refs: tuple[str, ...] = (), row_range: tuple[int, int] | None = None,
    ) -> Evidence:
        # A provisional frozen instance is used only to compute canonical identity;
        # construction below applies every validation before the object is exposed.
        args = dict(doc_id=doc_id, page=page, kind=kind, text=text,
                    source_block_ids=source_block_ids, parent_id=parent_id,
                    object_id=object_id, bbox=bbox, crop_ref=crop_ref, section_path=section_path,
                    source_chunk_ids=source_chunk_ids, evidence_type=evidence_type,
                    support_refs=support_refs, row_range=row_range)
        provisional = object.__new__(cls)
        for key, value in args.items():
            object.__setattr__(provisional, key, value)
        try:
            object.__setattr__(provisional, "content_sha256", _digest(text))
            if bbox is not None:
                object.__setattr__(provisional, "bbox", tuple(float(x) for x in bbox))
            identity = provisional._expected_id()
        except (TypeError, AttributeError, ValueError, OverflowError):
            raise ValueError("invalid_evidence_fields") from None
        return cls(evidence_id=identity, **args)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id, "doc_id": self.doc_id, "page": self.page,
            "kind": self.kind, "text": self.text, "source_block_ids": list(self.source_block_ids),
            "parent_id": self.parent_id, "object_id": self.object_id,
            "bbox": list(self.bbox) if self.bbox is not None else None,
            "crop_ref": self.crop_ref, "section_path": list(self.section_path),
            "content_sha256": self.content_sha256,
            "source_chunk_ids": list(self.source_chunk_ids), "evidence_type": self.evidence_type,
            "support_refs": list(self.support_refs),
            "row_range": list(self.row_range) if self.row_range is not None else None,
        }

    @classmethod
    def from_dict(cls, value: Any) -> Evidence:
        if not isinstance(value, Mapping) or set(value) != _FIELDS:
            raise ValueError("invalid_evidence_shape")
        args = dict(value)
        for key in ("source_block_ids", "section_path", "source_chunk_ids", "support_refs"):
            if not isinstance(args[key], list):
                raise ValueError("invalid_evidence_shape")
            args[key] = tuple(args[key])
        for key in ("bbox", "row_range"):
            if args[key] is not None:
                if not isinstance(args[key], list):
                    raise ValueError("invalid_evidence_shape")
                args[key] = tuple(args[key])
        claimed_hash = args.pop("content_sha256")
        record = cls(**args)
        if claimed_hash != record.content_sha256:
            raise ValueError("evidence_content_hash_mismatch")
        return record


class EvidenceStore:
    """Immutable source graph with explicit page-to-object bridges."""

    __slots__ = ("_records", "_by_id", "_children")

    def __setattr__(self, name: str, value: Any) -> None:
        if hasattr(self, name):
            raise AttributeError("evidence_store_is_immutable")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("evidence_store_is_immutable")

    def __init__(self, records: Iterable[Evidence]) -> None:
        if isinstance(records, (str, bytes, Mapping)):
            raise ValueError("invalid_evidence_records")
        try:
            materialized = tuple(records)
        except TypeError:
            raise ValueError("invalid_evidence_records") from None
        by_id: dict[str, Evidence] = {}
        for record in materialized:
            if not isinstance(record, Evidence):
                raise ValueError("invalid_evidence_record")
            # Revalidate even a dataclass object supplied by an untrusted loader.
            Evidence.from_dict(record.to_dict())
            if record.evidence_id in by_id:
                raise ValueError("duplicate_evidence_id")
            by_id[record.evidence_id] = record
        child_lists: dict[str, list[Evidence]] = {key: [] for key in by_id}
        for record in materialized:
            if record.parent_id is None:
                continue
            parent = by_id.get(record.parent_id)
            if parent is None:
                raise ValueError("evidence_parent_missing")
            if record.doc_id != parent.doc_id or record.page != parent.page:
                raise ValueError("evidence_parent_provenance_mismatch")
            if parent.kind not in {"page", "table", "figure"}:
                raise ValueError("invalid_evidence_parent_kind")
            child_lists[parent.evidence_id].append(record)
            seen = {record.evidence_id}
            cursor = parent
            while cursor.parent_id is not None:
                if cursor.evidence_id in seen:
                    raise ValueError("evidence_parent_cycle")
                seen.add(cursor.evidence_id)
                ancestor = by_id.get(cursor.parent_id)
                if ancestor is None:
                    raise ValueError("evidence_parent_missing")
                cursor = ancestor
            if cursor.kind != "page":
                raise ValueError("evidence_page_root_required")
        self._records = tuple(sorted(materialized, key=lambda item: item.evidence_id))
        self._by_id = MappingProxyType(by_id)
        self._children = MappingProxyType({
            key: tuple(sorted(items, key=lambda item: item.evidence_id))
            for key, items in child_lists.items()
        })

    def get(self, evidence_id: str) -> Evidence:
        if not isinstance(evidence_id, str) or evidence_id not in self._by_id:
            raise ValueError("unknown_evidence_id")
        return self._by_id[evidence_id]

    def all(self) -> tuple[Evidence, ...]:
        return self._records

    def children(self, evidence_id: str) -> tuple[Evidence, ...]:
        self.get(evidence_id)
        return self._children[evidence_id]

    def bridge(self, page_id: str, kind: str | None = None) -> tuple[Evidence, ...]:
        if self.get(page_id).kind != "page":
            raise ValueError("bridge_requires_page")
        if kind is not None and (not isinstance(kind, str) or kind not in {"table", "figure"}):
            raise ValueError("invalid_bridge_kind")
        pending = list(self.children(page_id))
        result: list[Evidence] = []
        while pending:
            current = pending.pop()
            if current.kind in {"table", "figure"} and (kind is None or current.kind == kind):
                result.append(current)
            pending.extend(self.children(current.evidence_id))
        return tuple(sorted(result, key=lambda item: item.evidence_id))

    @property
    def artifact_sha256(self) -> str:
        return _digest(_canonical([item.to_dict() for item in self._records]))

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": "evidence-store-v1", "artifact_sha256": self.artifact_sha256,
                "records": [item.to_dict() for item in self._records]}

    @classmethod
    def from_dict(cls, value: Any) -> EvidenceStore:
        if (not isinstance(value, Mapping)
                or set(value) != {"schema_version", "artifact_sha256", "records"}
                or value["schema_version"] != "evidence-store-v1"
                or not isinstance(value["records"], list)):
            raise ValueError("invalid_evidence_store_shape")
        store = cls(Evidence.from_dict(item) for item in value["records"])
        if store.artifact_sha256 != value["artifact_sha256"]:
            raise ValueError("evidence_store_hash_mismatch")
        return store
