"""Validated immutable evidence graph; no models, ranking, gold, or corpus I/O."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Iterable, Mapping

from .model import Evidence, ProvenanceParent


def _bound(parent: ProvenanceParent, child: Evidence) -> None:
    if parent.doc_id != child.doc_id or not set(child.source_block_ids) <= set(parent.source_block_ids):
        raise ValueError("evidence_source_binding_mismatch")
    a, b = parent.locator, child.locator
    if a.page != b.page or a.flow_id != b.flow_id:
        raise ValueError("evidence_page_flow_mismatch")
    if b.section_path[:len(a.section_path)] != a.section_path:
        raise ValueError("evidence_section_mismatch")
    if a.object_id is not None and a.object_id != b.object_id:
        raise ValueError("evidence_object_mismatch")
    if a.bbox is not None and (b.bbox is None or not (
        a.bbox[0] <= b.bbox[0] <= b.bbox[2] <= a.bbox[2]
        and a.bbox[1] <= b.bbox[1] <= b.bbox[3] <= a.bbox[3]
    )):
        raise ValueError("evidence_bbox_mismatch")
    if a.row_range is not None and (b.row_range is None or not (
        a.row_range[0] <= b.row_range[0] <= b.row_range[1] <= a.row_range[1]
    )):
        raise ValueError("evidence_rows_mismatch")
    if child.kind in {"text", "page"}:
        if b.char_range is None:
            if child.text not in parent.text:
                raise ValueError("evidence_text_not_in_parent")
        else:
            start, end = b.char_range
            if end > len(parent.text) or parent.text[start:end] != child.text:
                raise ValueError("evidence_text_span_mismatch")


@dataclass(frozen=True, slots=True, init=False)
class EvidenceStore:
    _parents: Mapping[str, ProvenanceParent]
    _evidence: Mapping[str, Evidence]
    _children: Mapping[str, tuple[Evidence, ...]]
    bundle_sha256: str

    def __init__(self, parents: Iterable[ProvenanceParent], evidence: Iterable[Evidence]):
        ps, es = {}, {}
        for items, cls, target, key in ((parents, ProvenanceParent, ps, "parent_id"),
                                        (evidence, Evidence, es, "evidence_id")):
            for value in items:
                if type(value) is not cls:
                    raise TypeError("invalid_evidence_store_node")
                value = cls.from_dict(value.to_dict())
                identity = getattr(value, key)
                if identity in target:
                    raise ValueError("duplicate_evidence_store_id")
                target[identity] = value
        children = defaultdict(list)
        incoming, dependents = {}, defaultdict(list)
        for identity, item in es.items():
            if item.parent_id not in ps:
                raise ValueError("evidence_parent_missing")
            _bound(ps[item.parent_id], item)
            children[item.parent_id].append(item)
            incoming[identity] = len(item.support_refs)
            for support in item.support_refs:
                if support not in es or es[support].doc_id != item.doc_id:
                    raise ValueError("evidence_support_missing_or_foreign")
                dependents[support].append(identity)
        ready = deque(key for key, count in incoming.items() if not count)
        visited = 0
        while ready:
            visited += 1
            for dependent in dependents[ready.popleft()]:
                incoming[dependent] -= 1
                if incoming[dependent] == 0:
                    ready.append(dependent)
        if visited != len(es):
            raise ValueError("evidence_support_cycle")
        object.__setattr__(self, "_parents", MappingProxyType(dict(sorted(ps.items()))))
        object.__setattr__(self, "_evidence", MappingProxyType(dict(sorted(es.items()))))
        object.__setattr__(self, "_children", MappingProxyType({
            key: tuple(sorted(values, key=lambda e: (e.locator.char_range or (0, 0), e.evidence_id)))
            for key, values in children.items()
        }))
        digest = sha256(json.dumps(self._payload(), ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        object.__setattr__(self, "bundle_sha256", digest)

    @property
    def parents(self) -> tuple[ProvenanceParent, ...]:
        return tuple(self._parents.values())

    @property
    def evidence(self) -> tuple[Evidence, ...]:
        return tuple(self._evidence.values())

    @property
    def doc_ids(self) -> frozenset[str]:
        return frozenset(p.doc_id for p in self.parents)

    def get(self, evidence_id: str) -> Evidence:
        return self._evidence[evidence_id]

    def parent(self, parent_id: str) -> ProvenanceParent:
        return self._parents[parent_id]

    def children(self, parent_id: str, *, kinds: tuple[str, ...] | None = None) -> tuple[Evidence, ...]:
        self.parent(parent_id)
        return tuple(e for e in self._children.get(parent_id, ()) if kinds is None or e.kind in kinds)

    def candidates(self, *, allowed_doc_ids: frozenset[str] | None = None,
                   kinds: tuple[str, ...] = ("text",)) -> tuple[Evidence, ...]:
        if allowed_doc_ids is not None and (not isinstance(allowed_doc_ids, frozenset)
                or any(not isinstance(d, str) for d in allowed_doc_ids)):
            raise TypeError("scope_requires_frozenset_or_none")
        return tuple(e for e in self.evidence if e.kind in kinds and
                     (allowed_doc_ids is None or e.doc_id in allowed_doc_ids))

    def for_document(self, doc_id: str, *, kinds: tuple[str, ...] | None = None) -> tuple[Evidence, ...]:
        return tuple(e for e in self.evidence if e.doc_id == doc_id and (kinds is None or e.kind in kinds))

    def bridge(self, evidence_id: str, *, kinds: tuple[str, ...]) -> tuple[Evidence, ...]:
        source = self.get(evidence_id)
        return tuple(e for e in self.evidence if e.evidence_id != source.evidence_id and e.kind in kinds
                     and e.doc_id == source.doc_id and (e.parent_id == source.parent_id
                     or e.evidence_id in source.support_refs or source.evidence_id in e.support_refs))

    def _payload(self) -> dict:
        return {"schema_version": "1.0", "parents": [p.to_dict() for p in self.parents],
                "evidence": [e.to_dict() for e in self.evidence]}

    def to_dict(self) -> dict:
        return self._payload() | {"bundle_sha256": self.bundle_sha256}

    @classmethod
    def from_dict(cls, payload: dict) -> EvidenceStore:
        if type(payload) is not dict or set(payload) != {"schema_version", "parents", "evidence", "bundle_sha256"}:
            raise ValueError("invalid_evidence_store_shape")
        if payload["schema_version"] != "1.0" or not all(type(payload[k]) is list for k in ("parents", "evidence")):
            raise ValueError("invalid_evidence_store_schema")
        store = cls((ProvenanceParent.from_dict(p) for p in payload["parents"]),
                    (Evidence.from_dict(e) for e in payload["evidence"]))
        if store.bundle_sha256 != payload["bundle_sha256"]:
            raise ValueError("evidence_bundle_hash_mismatch")
        return store
