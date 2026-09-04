"""Validated immutable evidence graph; no models, ranking, gold, or corpus I/O."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from hashlib import sha256
import json
from types import CodeType, FunctionType, MappingProxyType
from typing import Iterable, Mapping
from weakref import ReferenceType, ref

from . import model as _MODEL_RUNTIME_MODULE
from .model import Evidence, Locator, ProvenanceParent


_MAPPING_PROXY_TYPE = type(MappingProxyType({}))
_STORE_AUTHORITIES: dict[
    int,
    tuple[ReferenceType[object], object, object, object, str],
] = {}
_ISSUED_STORE_AUTHORITIES = _STORE_AUTHORITIES


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


def _validate_evidence_store_snapshot(
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
        authority = dict.get(_ISSUED_STORE_AUTHORITIES, id(store))
        if (
            type(authority) is not tuple
            or len(authority) != 5
            or type(authority[0]) is not ReferenceType
            or type(authority[1]) is not _MAPPING_PROXY_TYPE
            or type(authority[2]) is not _MAPPING_PROXY_TYPE
            or type(authority[3]) is not _MAPPING_PROXY_TYPE
            or type(authority[4]) is not str
            or authority[0]() is not store
        ):
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


_ISSUED_VALIDATE_EVIDENCE_STORE_SNAPSHOT_CORE = (
    _validate_evidence_store_snapshot
)


def _validate_store_validation_dependencies(
    _module_globals=None,
    _global_pins=None,
    _model_attribute_pins=None,
    _class_namespace_pins=None,
    _function_pins=None,
    _external_attribute_pins=None,
) -> None:
    """Authenticate every callable and descriptor before store traversal."""

    live_globals = globals()
    if type(_module_globals) is not dict or _module_globals is not live_globals:
        raise ValueError("evidence_store_validation_dependency_drift")
    for name, supplied in (
        ("_STORE_VALIDATION_GLOBAL_PINS", _global_pins),
        ("_STORE_VALIDATION_MODEL_ATTRIBUTE_PINS", _model_attribute_pins),
        ("_STORE_VALIDATION_CLASS_NAMESPACE_PINS", _class_namespace_pins),
        ("_STORE_VALIDATION_FUNCTION_PINS", _function_pins),
        ("_STORE_VALIDATION_EXTERNAL_ATTRIBUTE_PINS", _external_attribute_pins),
    ):
        if (
            supplied is not dict.get(live_globals, name)
            or supplied is not dict.get(live_globals, "_ISSUED" + name)
            or type(supplied) is not tuple
        ):
            raise ValueError("evidence_store_validation_dependency_drift")

    for entry in _global_pins:
        if type(entry) is not tuple or len(entry) != 3:
            raise ValueError("evidence_store_validation_dependency_drift")
        name, issued, issued_type = entry
        if (
            type(name) is not str
            or dict.get(live_globals, name) is not issued
            or type(issued) is not issued_type
        ):
            raise ValueError("evidence_store_validation_dependency_drift")

    model_namespace = object.__getattribute__(
        _MODEL_RUNTIME_MODULE, "__dict__"
    )
    if type(model_namespace) is not dict:
        raise ValueError("evidence_store_validation_dependency_drift")
    for entry in _model_attribute_pins:
        if type(entry) is not tuple or len(entry) != 2:
            raise ValueError("evidence_store_validation_dependency_drift")
        name, issued = entry
        if type(name) is not str or dict.get(model_namespace, name) is not issued:
            raise ValueError("evidence_store_validation_dependency_drift")

    for entry in _class_namespace_pins:
        if type(entry) is not tuple or len(entry) != 3:
            raise ValueError("evidence_store_validation_dependency_drift")
        owner, expected_size, issued_items = entry
        if (
            type(owner) is not type
            or type(expected_size) is not int
            or type(issued_items) is not tuple
        ):
            raise ValueError("evidence_store_validation_dependency_drift")
        namespace = type.__getattribute__(owner, "__dict__")
        if type(namespace) is not _MAPPING_PROXY_TYPE or len(namespace) != expected_size:
            raise ValueError("evidence_store_validation_dependency_drift")
        for name, issued in issued_items:
            if type(name) is not str or namespace.get(name) is not issued:
                raise ValueError("evidence_store_validation_dependency_drift")

    for entry in _function_pins:
        if type(entry) is not tuple or len(entry) != 7:
            raise ValueError("evidence_store_validation_dependency_drift")
        (
            function,
            code,
            defaults,
            kwdefaults,
            kwdefault_items,
            closure,
            closure_values,
        ) = entry
        current_kwdefaults = object.__getattribute__(function, "__kwdefaults__")
        current_closure = object.__getattribute__(function, "__closure__")
        if (
            type(function) is not FunctionType
            or type(code) is not CodeType
            or object.__getattribute__(function, "__code__") is not code
            or object.__getattribute__(function, "__defaults__") is not defaults
            or current_kwdefaults is not kwdefaults
            or current_closure is not closure
        ):
            raise ValueError("evidence_store_validation_dependency_drift")
        if current_kwdefaults is None:
            if kwdefault_items is not None:
                raise ValueError("evidence_store_validation_dependency_drift")
        elif (
            type(current_kwdefaults) is not dict
            or type(kwdefault_items) is not tuple
            or len(current_kwdefaults) != len(kwdefault_items)
            or any(
                dict.get(current_kwdefaults, name) is not issued
                for name, issued in kwdefault_items
            )
        ):
            raise ValueError("evidence_store_validation_dependency_drift")
        if current_closure is None:
            if closure_values is not None:
                raise ValueError("evidence_store_validation_dependency_drift")
        elif (
            type(current_closure) is not tuple
            or type(closure_values) is not tuple
            or len(current_closure) != len(closure_values)
            or any(
                object.__getattribute__(cell, "cell_contents") is not issued
                for cell, issued in zip(current_closure, closure_values)
            )
        ):
            raise ValueError("evidence_store_validation_dependency_drift")

    for entry in _external_attribute_pins:
        if type(entry) is not tuple or len(entry) != 3:
            raise ValueError("evidence_store_validation_dependency_drift")
        owner, name, issued = entry
        owner_namespace = object.__getattribute__(owner, "__dict__")
        if (
            type(owner_namespace) is not dict
            or type(name) is not str
            or dict.get(owner_namespace, name) is not issued
        ):
            raise ValueError("evidence_store_validation_dependency_drift")


_ISSUED_STORE_VALIDATION_DEPENDENCY_CHECKER = (
    _validate_store_validation_dependencies
)
_PINNED_STORE_VALIDATION_DEPENDENCY_CHECKER_CODE = (
    _validate_store_validation_dependencies.__code__
)


def validate_evidence_store_snapshot(
    store: EvidenceStore,
    expected_bundle_sha256: str,
    *,
    _dependency_checker=None,
    _dependency_checker_code=None,
    _dependency_checker_defaults=None,
) -> None:
    """Validate an issued store after authenticating the validation runtime."""

    module_namespace = globals()
    if (
        _dependency_checker
        is not dict.get(
            module_namespace, "_ISSUED_STORE_VALIDATION_DEPENDENCY_CHECKER"
        )
        or type(_dependency_checker) is not FunctionType
        or object.__getattribute__(_dependency_checker, "__code__")
        is not _dependency_checker_code
        or _dependency_checker_code
        is not dict.get(
            module_namespace,
            "_PINNED_STORE_VALIDATION_DEPENDENCY_CHECKER_CODE",
        )
        or _dependency_checker_defaults
        is not dict.get(
            module_namespace,
            "_ISSUED_STORE_VALIDATION_DEPENDENCY_CHECKER_DEFAULTS",
        )
        or object.__getattribute__(_dependency_checker, "__defaults__")
        is not _dependency_checker_defaults
    ):
        raise ValueError("evidence_store_validation_dependency_drift")
    _dependency_checker()
    _ISSUED_VALIDATE_EVIDENCE_STORE_SNAPSHOT_CORE(
        store, expected_bundle_sha256
    )


_ISSUED_VALIDATE_EVIDENCE_STORE_SNAPSHOT_PUBLIC = (
    validate_evidence_store_snapshot
)


def _store_validation_function_pin(function):
    kwdefaults = object.__getattribute__(function, "__kwdefaults__")
    closure = object.__getattribute__(function, "__closure__")
    return (
        function,
        object.__getattribute__(function, "__code__"),
        object.__getattribute__(function, "__defaults__"),
        kwdefaults,
        (
            None
            if kwdefaults is None
            else tuple(dict.items(kwdefaults))
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


def _store_validation_class_pin(owner):
    namespace = type.__getattribute__(owner, "__dict__")
    return owner, len(namespace), tuple(namespace.items())


_STORE_VALIDATION_MODEL_NAMES = (
    "_PARENT_KINDS",
    "_EVIDENCE_KINDS",
    "_LOCATOR_FIELDS",
    "_PARENT_FIELDS",
    "_EVIDENCE_FIELDS",
    "_string",
    "_optional_string",
    "_sequence",
    "_strings",
    "_integer",
    "_snapshot",
    "_json_array",
    "_identity",
    "_content_sha256",
    "_assert_computed",
    "_parent_reference",
    "_crop_reference",
    "Locator",
    "ProvenanceParent",
    "Evidence",
    "json",
    "math",
    "sha256",
)
_STORE_VALIDATION_MODEL_ATTRIBUTE_PINS = tuple(
    (name, object.__getattribute__(_MODEL_RUNTIME_MODULE, name))
    for name in _STORE_VALIDATION_MODEL_NAMES
)
_ISSUED_STORE_VALIDATION_MODEL_ATTRIBUTE_PINS = (
    _STORE_VALIDATION_MODEL_ATTRIBUTE_PINS
)

_STORE_VALIDATION_CLASSES = (
    EvidenceStore,
    Locator,
    ProvenanceParent,
    Evidence,
)
_STORE_VALIDATION_CLASS_NAMESPACE_PINS = tuple(
    _store_validation_class_pin(owner) for owner in _STORE_VALIDATION_CLASSES
)
_ISSUED_STORE_VALIDATION_CLASS_NAMESPACE_PINS = (
    _STORE_VALIDATION_CLASS_NAMESPACE_PINS
)

_STORE_VALIDATION_OWN_FUNCTIONS = (
    _drop_store_authority,
    _exact_strings,
    _validate_locator_shape,
    _validate_parent_shape,
    _validate_evidence_shape,
    _bound,
    _validate_evidence_store_snapshot,
)
_STORE_VALIDATION_MODEL_FUNCTIONS = tuple(
    function
    for name, function in _STORE_VALIDATION_MODEL_ATTRIBUTE_PINS
    if type(function) is FunctionType
)
_STORE_VALIDATION_CLASS_FUNCTIONS = tuple(
    function
    for owner, _size, items in _STORE_VALIDATION_CLASS_NAMESPACE_PINS
    for _name, descriptor in items
    for function in (
        (
            descriptor
            if type(descriptor) is FunctionType
            else descriptor.__func__
            if type(descriptor) in (classmethod, staticmethod)
            else descriptor.fget
            if type(descriptor) is property
            else None
        ),
    )
    if type(function) is FunctionType
)
_STORE_VALIDATION_FUNCTION_PINS = tuple(
    _store_validation_function_pin(function)
    for function in (
        _STORE_VALIDATION_OWN_FUNCTIONS
        + _STORE_VALIDATION_MODEL_FUNCTIONS
        + _STORE_VALIDATION_CLASS_FUNCTIONS
    )
)
_ISSUED_STORE_VALIDATION_FUNCTION_PINS = (
    _STORE_VALIDATION_FUNCTION_PINS
)

_STORE_VALIDATION_GLOBAL_PINS = tuple(
    (name, value, type(value))
    for name, value in (
        ("defaultdict", defaultdict),
        ("deque", deque),
        ("sha256", sha256),
        ("json", json),
        ("CodeType", CodeType),
        ("FunctionType", FunctionType),
        ("MappingProxyType", MappingProxyType),
        ("ReferenceType", ReferenceType),
        ("ref", ref),
        ("_MODEL_RUNTIME_MODULE", _MODEL_RUNTIME_MODULE),
        ("Evidence", Evidence),
        ("Locator", Locator),
        ("ProvenanceParent", ProvenanceParent),
        ("EvidenceStore", EvidenceStore),
        ("_MAPPING_PROXY_TYPE", _MAPPING_PROXY_TYPE),
        ("_STORE_AUTHORITIES", _ISSUED_STORE_AUTHORITIES),
        ("_ISSUED_STORE_AUTHORITIES", _ISSUED_STORE_AUTHORITIES),
        ("_drop_store_authority", _drop_store_authority),
        ("_exact_strings", _exact_strings),
        ("_validate_locator_shape", _validate_locator_shape),
        ("_validate_parent_shape", _validate_parent_shape),
        ("_validate_evidence_shape", _validate_evidence_shape),
        ("_bound", _bound),
        (
            "_validate_evidence_store_snapshot",
            _validate_evidence_store_snapshot,
        ),
        (
            "_ISSUED_VALIDATE_EVIDENCE_STORE_SNAPSHOT_CORE",
            _ISSUED_VALIDATE_EVIDENCE_STORE_SNAPSHOT_CORE,
        ),
        (
            "validate_evidence_store_snapshot",
            _ISSUED_VALIDATE_EVIDENCE_STORE_SNAPSHOT_PUBLIC,
        ),
        (
            "_ISSUED_VALIDATE_EVIDENCE_STORE_SNAPSHOT_PUBLIC",
            _ISSUED_VALIDATE_EVIDENCE_STORE_SNAPSHOT_PUBLIC,
        ),
    )
)
_ISSUED_STORE_VALIDATION_GLOBAL_PINS = _STORE_VALIDATION_GLOBAL_PINS

_STORE_VALIDATION_EXTERNAL_ATTRIBUTE_PINS = (
    (json, "dumps", json.dumps),
    (
        _MODEL_RUNTIME_MODULE.math,
        "isfinite",
        _MODEL_RUNTIME_MODULE.math.isfinite,
    ),
)
_ISSUED_STORE_VALIDATION_EXTERNAL_ATTRIBUTE_PINS = (
    _STORE_VALIDATION_EXTERNAL_ATTRIBUTE_PINS
)

_validate_store_validation_dependencies.__defaults__ = (
    globals(),
    _STORE_VALIDATION_GLOBAL_PINS,
    _STORE_VALIDATION_MODEL_ATTRIBUTE_PINS,
    _STORE_VALIDATION_CLASS_NAMESPACE_PINS,
    _STORE_VALIDATION_FUNCTION_PINS,
    _STORE_VALIDATION_EXTERNAL_ATTRIBUTE_PINS,
)
_ISSUED_STORE_VALIDATION_DEPENDENCY_CHECKER_DEFAULTS = (
    _validate_store_validation_dependencies.__defaults__
)
validate_evidence_store_snapshot.__kwdefaults__.update(
    {
        "_dependency_checker": _ISSUED_STORE_VALIDATION_DEPENDENCY_CHECKER,
        "_dependency_checker_code": (
            _PINNED_STORE_VALIDATION_DEPENDENCY_CHECKER_CODE
        ),
        "_dependency_checker_defaults": (
            _ISSUED_STORE_VALIDATION_DEPENDENCY_CHECKER_DEFAULTS
        ),
    }
)


__all__ = ("EvidenceStore", "validate_evidence_store_snapshot")
