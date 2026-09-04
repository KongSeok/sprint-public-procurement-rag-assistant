"""Validated immutable evidence graph; no models, ranking, gold, or corpus I/O."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Iterable, Mapping
from weakref import ReferenceType, ref

from .model import Evidence, Locator, ProvenanceParent


_MAPPING_PROXY_TYPE = type(MappingProxyType({}))
_STORE_AUTHORITIES: dict[
    int,
    tuple[ReferenceType[object], object, object, object, str],
] = {}


def _drop_store_authority(identity: int, dead: ReferenceType[object]) -> None:
    current = _STORE_AUTHORITIES.get(identity)
    if current is not None and current[0] is dead:
        _STORE_AUTHORITIES.pop(identity, None)


def _exact_strings(value: object) -> bool:
    return type(value) is tuple and all(type(item) is str for item in value)


def _validate_locator_shape(locator: object) -> None:
    if type(locator) is not Locator:
        raise ValueError("evidence_store_node_type_drift")
    if locator.page is not None and type(locator.page) is not int:
        raise ValueError("evidence_store_node_type_drift")
    for value in (locator.flow_id, locator.object_id):
        if value is not None and type(value) is not str:
            raise ValueError("evidence_store_node_type_drift")
    if not _exact_strings(locator.section_path):
        raise ValueError("evidence_store_node_type_drift")
    for value, size, numeric_types in (
        (locator.bbox, 4, {int, float}),
        (locator.row_range, 2, {int}),
        (locator.char_range, 2, {int}),
    ):
        if value is None:
            continue
        if type(value) is not tuple or len(value) != size:
            raise ValueError("evidence_store_node_type_drift")
        if any(type(item) not in numeric_types for item in value):
            raise ValueError("evidence_store_node_type_drift")


def _validate_parent_shape(parent: object) -> None:
    if type(parent) is not ProvenanceParent:
        raise ValueError("evidence_store_node_type_drift")
    if any(
        type(value) is not str
        for value in (
            parent.doc_id,
            parent.kind,
            parent.text,
            parent.parent_id,
            parent.content_sha256,
        )
    ) or not _exact_strings(parent.source_block_ids):
        raise ValueError("evidence_store_node_type_drift")
    _validate_locator_shape(parent.locator)


def _validate_evidence_shape(evidence: object) -> None:
    if type(evidence) is not Evidence:
        raise ValueError("evidence_store_node_type_drift")
    if any(
        type(value) is not str
        for value in (
            evidence.doc_id,
            evidence.kind,
            evidence.text,
            evidence.parent_id,
            evidence.evidence_id,
            evidence.content_sha256,
        )
    ):
        raise ValueError("evidence_store_node_type_drift")
    if evidence.crop_ref is not None and type(evidence.crop_ref) is not str:
        raise ValueError("evidence_store_node_type_drift")
    if any(
        not _exact_strings(value)
        for value in (
            evidence.source_block_ids,
            evidence.source_chunk_ids,
            evidence.support_refs,
        )
    ):
        raise ValueError("evidence_store_node_type_drift")
    _validate_locator_shape(evidence.locator)


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


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
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
        identity = id(self)
        weak = ref(
            self,
            lambda dead, identity=identity: _drop_store_authority(identity, dead),
        )
        _STORE_AUTHORITIES[identity] = (
            weak,
            self._parents,
            self._evidence,
            self._children,
            self.bundle_sha256,
        )

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


def validate_evidence_store_snapshot(
    store: EvidenceStore,
    expected_bundle_sha256: str,
) -> None:
    """Validate both canonical payload and every live lookup index.

    Re-hashing ``to_dict()`` alone is insufficient because the serialized payload
    contains mapping values, not the private mapping keys or derived child index.
    This boundary reconstructs the canonical graph and checks the live indexes
    that retrieval methods actually consult.
    """

    if type(store) is not EvidenceStore:
        raise TypeError("evidence_store_required")
    if type(expected_bundle_sha256) is not str:
        raise TypeError("evidence_store_bundle_sha256_required")
    try:
        authority = _STORE_AUTHORITIES.get(id(store))
        if authority is None or authority[0]() is not store:
            raise ValueError("evidence_store_runtime_authority_required")
        if (
            authority[1] is not store._parents
            or authority[2] is not store._evidence
            or authority[3] is not store._children
        ):
            raise ValueError("evidence_store_index_drift")
        if type(store.bundle_sha256) is not str:
            raise ValueError("evidence_store_bundle_drift")
        if store.bundle_sha256 is not authority[4]:
            raise ValueError("evidence_store_bundle_mismatch")
        if any(
            type(mapping) is not _MAPPING_PROXY_TYPE
            for mapping in (store._parents, store._evidence, store._children)
        ):
            raise ValueError("evidence_store_index_drift")
        for key, parent in store._parents.items():
            if type(key) is not str:
                raise ValueError("evidence_store_index_drift")
            _validate_parent_shape(parent)
            if key != parent.parent_id:
                raise ValueError("evidence_store_index_drift")
        for key, evidence in store._evidence.items():
            if type(key) is not str:
                raise ValueError("evidence_store_index_drift")
            _validate_evidence_shape(evidence)
            if key != evidence.evidence_id:
                raise ValueError("evidence_store_index_drift")
        derived_children: dict[str, list[Evidence]] = defaultdict(list)
        for evidence in store._evidence.values():
            derived_children[evidence.parent_id].append(evidence)
        expected_children = {
            key: tuple(
                sorted(
                    values,
                    key=lambda item: (
                        item.locator.char_range or (0, 0),
                        item.evidence_id,
                    ),
                )
            )
            for key, values in derived_children.items()
        }
        child_keys = tuple(store._children.keys())
        if any(type(key) is not str for key in child_keys):
            raise ValueError("evidence_store_index_drift")
        if set(child_keys) != set(expected_children):
            raise ValueError("evidence_store_index_drift")
        for parent_id, children in store._children.items():
            if type(parent_id) is not str or type(children) is not tuple:
                raise ValueError("evidence_store_index_drift")
            if len(children) != len(expected_children[parent_id]) or any(
                type(child) is not Evidence
                or store._evidence.get(child.evidence_id) is not child
                or child is not expected
                for child, expected in zip(children, expected_children[parent_id])
            ):
                raise ValueError("evidence_store_index_drift")
        if store.bundle_sha256 != expected_bundle_sha256:
            raise ValueError("evidence_store_bundle_mismatch")
        payload = store.to_dict()
        canonical = EvidenceStore.from_dict(payload)
        if canonical.bundle_sha256 != expected_bundle_sha256:
            raise ValueError("evidence_store_bundle_mismatch")
        if tuple(store._parents) != tuple(canonical._parents):
            raise ValueError("evidence_store_index_drift")
        if tuple(store._evidence) != tuple(canonical._evidence):
            raise ValueError("evidence_store_index_drift")
        if frozenset(store._children) != frozenset(canonical._children):
            raise ValueError("evidence_store_index_drift")
        if store.parents != canonical.parents or store.evidence != canonical.evidence:
            raise ValueError("evidence_store_payload_drift")
        for parent_id, parent in canonical._parents.items():
            if store.parent(parent_id) != parent:
                raise ValueError("evidence_store_index_drift")
            if store.children(parent_id) != canonical.children(parent_id):
                raise ValueError("evidence_store_index_drift")
        for evidence_id, evidence in canonical._evidence.items():
            if store.get(evidence_id) != evidence:
                raise ValueError("evidence_store_index_drift")
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc) == "evidence_store_bundle_mismatch":
            raise
        raise ValueError("evidence_store_payload_drift") from exc


__all__ = ("EvidenceStore", "validate_evidence_store_snapshot")
