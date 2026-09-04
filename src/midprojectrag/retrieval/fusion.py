"""Same-child-unit reciprocal rank fusion with independent lane budgets."""
from dataclasses import dataclass
from hashlib import sha256
import json
from types import CodeType, FunctionType, MappingProxyType, MemberDescriptorType
from weakref import ReferenceType, ref

from midprojectrag.evidence import EvidenceStore, validate_evidence_store_snapshot
from midprojectrag.runtime_integrity import ResolvedScope
from . import dense as _DENSE_RUNTIME_MODULE
from . import kiwi_bm25 as _LEXICAL_RUNTIME_MODULE
from .contracts import Candidate, SearchResult


_HYBRID_PRODUCTION_BINDING = object()
_ISSUED_VALIDATE_EVIDENCE_STORE_SNAPSHOT = validate_evidence_store_snapshot
_ISSUED_JSON = json
_ISSUED_JSON_DUMPS = json.dumps
_ISSUED_SHA256 = sha256
_ISSUED_REQUIRE_LOADED_DENSE_ARTIFACT = object.__getattribute__(
    _DENSE_RUNTIME_MODULE, "require_loaded_dense_artifact"
)
_ISSUED_PREFLIGHT_LOADED_DENSE_ARTIFACT = object.__getattribute__(
    _DENSE_RUNTIME_MODULE, "preflight_loaded_dense_artifact"
)
_ISSUED_REQUIRE_LOADED_LEXICAL_ARTIFACT = object.__getattribute__(
    _LEXICAL_RUNTIME_MODULE, "require_loaded_lexical_artifact"
)
_ISSUED_PREFLIGHT_LOADED_LEXICAL_ARTIFACT = object.__getattribute__(
    _LEXICAL_RUNTIME_MODULE, "preflight_loaded_lexical_artifact"
)
_ISSUED_REF = ref
_PINNED_EVIDENCE_STORE_CLASS = EvidenceStore
_PINNED_EVIDENCE_STORE_GETATTRIBUTE = EvidenceStore.__getattribute__
_PINNED_EVIDENCE_STORE_CANDIDATES = type.__getattribute__(
    EvidenceStore, "__dict__"
)["candidates"]
_PINNED_EVIDENCE_STORE_CANDIDATES_CODE = object.__getattribute__(
    _PINNED_EVIDENCE_STORE_CANDIDATES, "__code__"
)
_PINNED_RESOLVED_SCOPE_CLASS = ResolvedScope
_PINNED_RESOLVED_SCOPE_GETATTRIBUTE = ResolvedScope.__getattribute__
_PINNED_RESOLVED_SCOPE_DESCRIPTORS = MappingProxyType({
    name: type.__getattribute__(ResolvedScope, "__dict__")[name]
    for name in ("state", "doc_ids", "origin")
})
_PINNED_RESOLVED_SCOPE_ALLOWED = type.__getattribute__(
    ResolvedScope, "__dict__"
)["allowed_doc_ids"]
_PINNED_CANDIDATE_CLASS = Candidate
_PINNED_SEARCH_RESULT_CLASS = SearchResult
_PINNED_CONTRACT_GETATTRIBUTES = MappingProxyType({
    Candidate: Candidate.__getattribute__,
    SearchResult: SearchResult.__getattribute__,
})
_PINNED_CONTRACT_DESCRIPTORS = MappingProxyType({
    Candidate: MappingProxyType({
        name: type.__getattribute__(Candidate, "__dict__")[name]
        for name in (
            "evidence_id",
            "doc_id",
            "score",
            "lane",
            "rank",
            "granularity",
        )
    }),
    SearchResult: MappingProxyType({
        name: type.__getattribute__(SearchResult, "__dict__")[name]
        for name in ("candidates", "trace")
    }),
})
_PINNED_CONTRACT_METHODS = tuple(
    (
        owner,
        name,
        type.__getattribute__(owner, "__dict__")[name],
        object.__getattribute__(
            type.__getattribute__(owner, "__dict__")[name], "__code__"
        ),
    )
    for owner, name in (
        (Candidate, "__init__"),
        (Candidate, "__post_init__"),
        (SearchResult, "__init__"),
        (SearchResult, "__post_init__"),
    )
)
_PRODUCTION_HYBRIDS: dict[
    int,
    tuple[ReferenceType[object], object, dict[str, object]],
] = {}
_ISSUED_PRODUCTION_HYBRIDS = _PRODUCTION_HYBRIDS


def _contract_classes_unchanged() -> bool:
    if (
        globals().get("Candidate") is not _PINNED_CANDIDATE_CLASS
        or globals().get("SearchResult") is not _PINNED_SEARCH_RESULT_CLASS
    ):
        return False
    for owner in (_PINNED_CANDIDATE_CLASS, _PINNED_SEARCH_RESULT_CLASS):
        namespace = type.__getattribute__(owner, "__dict__")
        if (
            type.__getattribute__(owner, "__getattribute__")
            is not _PINNED_CONTRACT_GETATTRIBUTES[owner]
            or any(
                namespace.get(name) is not descriptor
                or type(descriptor) is not MemberDescriptorType
                for name, descriptor in _PINNED_CONTRACT_DESCRIPTORS[
                    owner
                ].items()
            )
        ):
            return False
    return all(
        type.__getattribute__(owner, "__dict__").get(name) is method
        and type(method) is FunctionType
        and object.__getattribute__(method, "__code__") is code
        for owner, name, method, code in _PINNED_CONTRACT_METHODS
    )


_ISSUED_CONTRACT_CLASSES_UNCHANGED = _contract_classes_unchanged
_PINNED_CONTRACT_CLASSES_UNCHANGED = _ISSUED_CONTRACT_CLASSES_UNCHANGED


def _resolved_scope_class_unchanged() -> bool:
    namespace = type.__getattribute__(
        _PINNED_RESOLVED_SCOPE_CLASS, "__dict__"
    )
    return (
        globals().get("ResolvedScope") is _PINNED_RESOLVED_SCOPE_CLASS
        and type.__getattribute__(
            _PINNED_RESOLVED_SCOPE_CLASS, "__getattribute__"
        )
        is _PINNED_RESOLVED_SCOPE_GETATTRIBUTE
        and all(
            namespace.get(name) is descriptor
            and type(descriptor) is MemberDescriptorType
            for name, descriptor in _PINNED_RESOLVED_SCOPE_DESCRIPTORS.items()
        )
        and namespace.get("allowed_doc_ids")
        is _PINNED_RESOLVED_SCOPE_ALLOWED
        and type(_PINNED_RESOLVED_SCOPE_ALLOWED) is property
    )


_ISSUED_RESOLVED_SCOPE_CLASS_UNCHANGED = _resolved_scope_class_unchanged
_PINNED_RESOLVED_SCOPE_CLASS_UNCHANGED = (
    _ISSUED_RESOLVED_SCOPE_CLASS_UNCHANGED
)


def _resolved_scope_values(
    scope: ResolvedScope,
) -> tuple[str, frozenset[str] | None]:
    if not _PINNED_RESOLVED_SCOPE_CLASS_UNCHANGED() or type(
        scope
    ) is not _PINNED_RESOLVED_SCOPE_CLASS:
        raise ValueError("hybrid_scope_runtime_shape_drift")
    state = object.__getattribute__(scope, "state")
    doc_ids = object.__getattribute__(scope, "doc_ids")
    origin = object.__getattribute__(scope, "origin")
    if (
        type(state) is not str
        or state not in {"unfiltered", "empty", "restricted"}
        or type(doc_ids) is not frozenset
        or any(type(doc_id) is not str or not doc_id for doc_id in doc_ids)
        or type(origin) is not str
        or (state == "restricted") != bool(doc_ids)
    ):
        raise ValueError("invalid_hybrid_scope_or_budget")
    return state, None if state == "unfiltered" else doc_ids


_ISSUED_RESOLVED_SCOPE_VALUES = _resolved_scope_values
_PINNED_RESOLVED_SCOPE_VALUES = _ISSUED_RESOLVED_SCOPE_VALUES


def _drop_production_hybrid(
    identity: int,
    dead: ReferenceType[object],
) -> None:
    current = dict.get(_ISSUED_PRODUCTION_HYBRIDS, identity)
    if current is not None and current[0] is dead:
        dict.pop(_ISSUED_PRODUCTION_HYBRIDS, identity, None)


def _register_production_hybrid(
    retriever: object,
    binding: object,
    snapshot: dict[str, object],
) -> None:
    identity = id(retriever)
    weak = _ISSUED_REF(
        retriever,
        lambda dead, identity=identity: _drop_production_hybrid(identity, dead),
    )
    dict.__setitem__(
        _ISSUED_PRODUCTION_HYBRIDS,
        identity,
        (weak, binding, snapshot),
    )


_ISSUED_REGISTER_PRODUCTION_HYBRID = _register_production_hybrid


def _production_hybrid_entry(
    retriever: object,
) -> tuple[object, dict[str, object]] | None:
    current = dict.get(_ISSUED_PRODUCTION_HYBRIDS, id(retriever))
    if current is None:
        return None
    if (
        type(current) is not tuple
        or len(current) != 3
        or type(current[0]) is not ReferenceType
        or type(current[2]) is not dict
    ):
        raise ValueError("hybrid_production_registry_entry_drift")
    if current[0]() is not retriever:
        return None
    return current[1], current[2]


_ISSUED_PRODUCTION_HYBRID_ENTRY = _production_hybrid_entry
_PINNED_PRODUCTION_HYBRID_ENTRY = _ISSUED_PRODUCTION_HYBRID_ENTRY


def _digest(value) -> str:
    return _ISSUED_SHA256(
        _ISSUED_JSON_DUMPS(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


_ISSUED_DIGEST = _digest


def _row_hash(store: EvidenceStore) -> str:
    return _ISSUED_DIGEST(
        [row.evidence_id for row in store.candidates()]
    )


_ISSUED_ROW_HASH = _row_hash


@dataclass(frozen=True, slots=True, init=False)
class HybridProductionBinding:
    """Opaque binding for an exact, loader-attested production hybrid stack."""

    bundle_sha256: str
    rows_sha256: str
    dense_attestation_sha256: str
    lexical_attestation_sha256: str
    dense_artifact_sha256: str
    lexical_artifact_sha256: str
    fusion_config_sha256: str
    binding_sha256: str

    def __init__(self, payload: dict, *, _token=None):
        if _token is not _HYBRID_PRODUCTION_BINDING:
            raise TypeError("hybrid_production_binding_is_factory_sealed")
        expected = {
            "bundle_sha256", "rows_sha256", "dense_attestation_sha256",
            "lexical_attestation_sha256", "dense_artifact_sha256",
            "lexical_artifact_sha256", "fusion_config_sha256",
        }
        if type(payload) is not dict or set(payload) != expected or any(
            type(value) is not str
            or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)
            for value in payload.values()
        ):
            raise ValueError("invalid_hybrid_production_binding")
        for name, value in payload.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "binding_sha256", _ISSUED_DIGEST(payload))


_HYBRID_BINDING_FIELDS = (
    "bundle_sha256",
    "rows_sha256",
    "dense_attestation_sha256",
    "lexical_attestation_sha256",
    "dense_artifact_sha256",
    "lexical_artifact_sha256",
    "fusion_config_sha256",
    "binding_sha256",
)
_PINNED_HYBRID_BINDING_GETATTRIBUTE = HybridProductionBinding.__getattribute__
_PINNED_HYBRID_BINDING_DESCRIPTORS = MappingProxyType({
    name: type.__getattribute__(HybridProductionBinding, "__dict__")[name]
    for name in _HYBRID_BINDING_FIELDS
})


def _preflight_hybrid_binding_shape(binding: HybridProductionBinding) -> None:
    if type(binding) is not HybridProductionBinding:
        raise ValueError("hybrid_production_binding_required")
    namespace = type.__getattribute__(HybridProductionBinding, "__dict__")
    if (
        type.__getattribute__(HybridProductionBinding, "__getattribute__")
        is not _PINNED_HYBRID_BINDING_GETATTRIBUTE
        or any(
            namespace.get(name) is not descriptor
            or type(descriptor) is not MemberDescriptorType
            for name, descriptor in _PINNED_HYBRID_BINDING_DESCRIPTORS.items()
        )
    ):
        raise ValueError("hybrid_production_binding_shape_drift")


def _require_sha256(value: object, code: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(code)
    return value


def _validate_hybrid_binding_snapshot(binding: HybridProductionBinding) -> None:
    _preflight_hybrid_binding_shape(binding)
    fields = (
        "bundle_sha256",
        "rows_sha256",
        "dense_attestation_sha256",
        "lexical_attestation_sha256",
        "dense_artifact_sha256",
        "lexical_artifact_sha256",
        "fusion_config_sha256",
    )
    payload = {}
    for name in fields:
        value = object.__getattribute__(binding, name)
        payload[name] = _require_sha256(
            value, "hybrid_production_binding_payload_drift"
        )
    claimed = _require_sha256(
        object.__getattribute__(binding, "binding_sha256"),
        "hybrid_production_binding_payload_drift",
    )
    if claimed != _ISSUED_DIGEST(payload):
        raise ValueError("hybrid_production_binding_hash_mismatch")


def _hybrid_binding_values(binding: HybridProductionBinding) -> tuple[str, ...]:
    _validate_hybrid_binding_snapshot(binding)
    return tuple(
        object.__getattribute__(binding, name) for name in _HYBRID_BINDING_FIELDS
    )


_ISSUED_HYBRID_BINDING_VALUES = _hybrid_binding_values


def _function_unchanged(
    current: object,
    issued: FunctionType,
    code: CodeType,
    defaults: object,
    kwdefaults: dict[str, object] | None,
) -> bool:
    if current is not issued or type(current) is not FunctionType:
        return False
    if (
        object.__getattribute__(current, "__code__") is not code
        or object.__getattribute__(current, "__defaults__") is not defaults
    ):
        return False
    current_kwdefaults = object.__getattribute__(current, "__kwdefaults__")
    return (
        current_kwdefaults is None
        if kwdefaults is None
        else type(current_kwdefaults) is dict
        and dict(current_kwdefaults) == kwdefaults
    )


_ISSUED_FUNCTION_UNCHANGED = _function_unchanged


_FUSION_PREFLIGHT_HELPER_PINS = tuple(
    (
        name,
        function,
        object.__getattribute__(function, "__code__"),
        object.__getattribute__(function, "__defaults__"),
        object.__getattribute__(function, "__kwdefaults__"),
    )
    for name, function in (
        ("_production_hybrid_entry", _production_hybrid_entry),
        ("_ISSUED_PRODUCTION_HYBRID_ENTRY", _production_hybrid_entry),
        ("_PINNED_PRODUCTION_HYBRID_ENTRY", _production_hybrid_entry),
        ("_contract_classes_unchanged", _contract_classes_unchanged),
        ("_ISSUED_CONTRACT_CLASSES_UNCHANGED", _contract_classes_unchanged),
        ("_PINNED_CONTRACT_CLASSES_UNCHANGED", _contract_classes_unchanged),
        ("_resolved_scope_class_unchanged", _resolved_scope_class_unchanged),
        ("_ISSUED_RESOLVED_SCOPE_CLASS_UNCHANGED", _resolved_scope_class_unchanged),
        ("_PINNED_RESOLVED_SCOPE_CLASS_UNCHANGED", _resolved_scope_class_unchanged),
        ("_resolved_scope_values", _resolved_scope_values),
        ("_ISSUED_RESOLVED_SCOPE_VALUES", _resolved_scope_values),
        ("_PINNED_RESOLVED_SCOPE_VALUES", _resolved_scope_values),
        ("_function_unchanged", _function_unchanged),
        ("_ISSUED_FUNCTION_UNCHANGED", _function_unchanged),
        ("_hybrid_binding_values", _hybrid_binding_values),
        ("_ISSUED_HYBRID_BINDING_VALUES", _hybrid_binding_values),
        ("_validate_hybrid_binding_snapshot", _validate_hybrid_binding_snapshot),
        ("_preflight_hybrid_binding_shape", _preflight_hybrid_binding_shape),
        ("_require_sha256", _require_sha256),
        ("_digest", _digest),
    )
)
_ISSUED_FUSION_PREFLIGHT_HELPER_PINS = _FUSION_PREFLIGHT_HELPER_PINS
_FUSION_PREFLIGHT_OBJECT_PINS = (
    ("_PRODUCTION_HYBRIDS", _ISSUED_PRODUCTION_HYBRIDS, dict),
    ("_ISSUED_PRODUCTION_HYBRIDS", _ISSUED_PRODUCTION_HYBRIDS, dict),
    ("json", _ISSUED_JSON, type(_ISSUED_JSON)),
    ("_ISSUED_JSON", _ISSUED_JSON, type(_ISSUED_JSON)),
    ("sha256", _ISSUED_SHA256, type(_ISSUED_SHA256)),
    ("_ISSUED_SHA256", _ISSUED_SHA256, type(_ISSUED_SHA256)),
    (
        "_ISSUED_JSON_DUMPS",
        _ISSUED_JSON_DUMPS,
        type(_ISSUED_JSON_DUMPS),
    ),
    ("EvidenceStore", _PINNED_EVIDENCE_STORE_CLASS, type),
    (
        "_PINNED_EVIDENCE_STORE_CLASS",
        _PINNED_EVIDENCE_STORE_CLASS,
        type,
    ),
    (
        "_PINNED_EVIDENCE_STORE_GETATTRIBUTE",
        _PINNED_EVIDENCE_STORE_GETATTRIBUTE,
        type(_PINNED_EVIDENCE_STORE_GETATTRIBUTE),
    ),
    (
        "_PINNED_EVIDENCE_STORE_CANDIDATES",
        _PINNED_EVIDENCE_STORE_CANDIDATES,
        FunctionType,
    ),
    (
        "_PINNED_EVIDENCE_STORE_CANDIDATES_CODE",
        _PINNED_EVIDENCE_STORE_CANDIDATES_CODE,
        CodeType,
    ),
    (
        "_PINNED_RESOLVED_SCOPE_CLASS",
        _PINNED_RESOLVED_SCOPE_CLASS,
        type,
    ),
    (
        "_PINNED_RESOLVED_SCOPE_GETATTRIBUTE",
        _PINNED_RESOLVED_SCOPE_GETATTRIBUTE,
        type(_PINNED_RESOLVED_SCOPE_GETATTRIBUTE),
    ),
    (
        "_PINNED_RESOLVED_SCOPE_DESCRIPTORS",
        _PINNED_RESOLVED_SCOPE_DESCRIPTORS,
        type(_PINNED_RESOLVED_SCOPE_DESCRIPTORS),
    ),
    (
        "_PINNED_RESOLVED_SCOPE_ALLOWED",
        _PINNED_RESOLVED_SCOPE_ALLOWED,
        property,
    ),
    ("_PINNED_CANDIDATE_CLASS", _PINNED_CANDIDATE_CLASS, type),
    ("_PINNED_SEARCH_RESULT_CLASS", _PINNED_SEARCH_RESULT_CLASS, type),
    (
        "_PINNED_CONTRACT_GETATTRIBUTES",
        _PINNED_CONTRACT_GETATTRIBUTES,
        type(_PINNED_CONTRACT_GETATTRIBUTES),
    ),
    (
        "_PINNED_CONTRACT_DESCRIPTORS",
        _PINNED_CONTRACT_DESCRIPTORS,
        type(_PINNED_CONTRACT_DESCRIPTORS),
    ),
    ("_PINNED_CONTRACT_METHODS", _PINNED_CONTRACT_METHODS, tuple),
    ("_HYBRID_BINDING_FIELDS", _HYBRID_BINDING_FIELDS, tuple),
    (
        "_PINNED_HYBRID_BINDING_GETATTRIBUTE",
        _PINNED_HYBRID_BINDING_GETATTRIBUTE,
        type(_PINNED_HYBRID_BINDING_GETATTRIBUTE),
    ),
    (
        "_PINNED_HYBRID_BINDING_DESCRIPTORS",
        _PINNED_HYBRID_BINDING_DESCRIPTORS,
        type(_PINNED_HYBRID_BINDING_DESCRIPTORS),
    ),
    ("FunctionType", FunctionType, type),
    ("CodeType", CodeType, type),
    ("MemberDescriptorType", MemberDescriptorType, type),
)
_ISSUED_FUSION_PREFLIGHT_OBJECT_PINS = _FUSION_PREFLIGHT_OBJECT_PINS
_FUSION_PREFLIGHT_MODULE_ATTRIBUTE_PINS = (
    (_ISSUED_JSON, "dumps", _ISSUED_JSON_DUMPS),
)
_ISSUED_FUSION_PREFLIGHT_MODULE_ATTRIBUTE_PINS = (
    _FUSION_PREFLIGHT_MODULE_ATTRIBUTE_PINS
)


def fuse_rrf(dense: SearchResult, lexical: SearchResult, store: EvidenceStore, *, rrf_k=60) -> SearchResult:
    if (
        not _PINNED_CONTRACT_CLASSES_UNCHANGED()
        or type(dense) is not _PINNED_SEARCH_RESULT_CLASS
        or type(lexical) is not _PINNED_SEARCH_RESULT_CLASS
    ):
        raise ValueError("fusion_contract_runtime_shape_drift")
    if type(rrf_k) is not int or rrf_k != 60:
        raise ValueError("rrf_constant_not_pinned")
    scores, docs, sets = {}, {}, []
    for result, lane in ((dense, "dense"), (lexical, "lexical")):
        result_trace = object.__getattribute__(result, "trace")
        if result_trace.get("granularity") != "child" or result_trace.get("bundle_sha256") != object.__getattribute__(store, "bundle_sha256"):
            raise ValueError("fusion_lane_artifact_or_granularity_mismatch")
        ids = set()
        candidates = object.__getattribute__(result, "candidates")
        if type(candidates) is not tuple or any(
            type(candidate) is not _PINNED_CANDIDATE_CLASS
            for candidate in candidates
        ):
            raise ValueError("fusion_candidate_contract_mismatch")
        for position, c in enumerate(candidates, 1):
            evidence_id = object.__getattribute__(c, "evidence_id")
            doc_id = object.__getattribute__(c, "doc_id")
            e = store.get(evidence_id)
            if object.__getattribute__(c, "lane") != lane or object.__getattribute__(c, "granularity") != "child" or object.__getattribute__(c, "rank") != position or e.kind != "text" or e.doc_id != doc_id:
                raise ValueError("fusion_candidate_contract_mismatch")
            scores[evidence_id] = scores.get(evidence_id, 0) + 1 / (rrf_k + position)
            docs[evidence_id] = doc_id
            ids.add(evidence_id)
        sets.append(ids)
    a, b = sets
    ordered = sorted(scores, key=lambda identity: (-scores[identity], identity))
    candidates = tuple(_PINNED_CANDIDATE_CLASS(identity, docs[identity], scores[identity], "rrf", rank)
                       for rank, identity in enumerate(ordered, 1))
    return _PINNED_SEARCH_RESULT_CLASS(candidates, {"lane": "rrf", "rrf_k": rrf_k, "granularity": "child",
        "bundle_sha256": object.__getattribute__(store, "bundle_sha256"), "dense_only": sorted(a-b), "lexical_only": sorted(b-a),
        "both": sorted(a & b), "duplicate_count": len(a & b), "distinct_doc_count": len(set(docs.values())),
        "dense": object.__getattribute__(dense, "trace"), "lexical": object.__getattribute__(lexical, "trace")})


_ISSUED_FUSE_RRF = fuse_rrf
_PINNED_FUSE_RRF = _ISSUED_FUSE_RRF
_PINNED_FUSE_RRF_CODE = fuse_rrf.__code__
_PINNED_FUSE_RRF_DEFAULTS = fuse_rrf.__defaults__
_PINNED_FUSE_RRF_KWDEFAULTS = (
    None if fuse_rrf.__kwdefaults__ is None else dict(fuse_rrf.__kwdefaults__)
)


def _validate_fusion_entry_dependencies(
    _module_globals=None,
    _function_pins=None,
    _external_function_pins=None,
    _object_pins=None,
    _class_method_pins=None,
) -> None:
    """Authenticate factory/search dependencies before their first dispatch."""

    if type(_module_globals) is not dict or globals() is not _module_globals:
        raise ValueError("hybrid_production_entry_dependency_drift")
    for provided, canonical_name, issued_name in (
        (
            _function_pins,
            "_FUSION_ENTRY_FUNCTION_PINS",
            "_ISSUED_FUSION_ENTRY_FUNCTION_PINS",
        ),
        (
            _external_function_pins,
            "_FUSION_ENTRY_EXTERNAL_FUNCTION_PINS",
            "_ISSUED_FUSION_ENTRY_EXTERNAL_FUNCTION_PINS",
        ),
        (
            _object_pins,
            "_FUSION_ENTRY_OBJECT_PINS",
            "_ISSUED_FUSION_ENTRY_OBJECT_PINS",
        ),
        (
            _class_method_pins,
            "_FUSION_ENTRY_CLASS_METHOD_PINS",
            "_ISSUED_FUSION_ENTRY_CLASS_METHOD_PINS",
        ),
    ):
        if (
            type(provided) is not tuple
            or provided is not dict.get(_module_globals, canonical_name)
            or provided is not dict.get(_module_globals, issued_name)
        ):
            raise ValueError("hybrid_production_entry_dependency_drift")
    for entry in _function_pins:
        if type(entry) is not tuple or len(entry) != 5:
            raise ValueError("hybrid_production_entry_dependency_drift")
        name, issued, code, defaults, kwdefaults = entry
        current = dict.get(_module_globals, name)
        if (
            type(name) is not str
            or type(issued) is not FunctionType
            or type(code) is not CodeType
            or current is not issued
            or type(current) is not FunctionType
            or object.__getattribute__(current, "__code__") is not code
            or object.__getattribute__(current, "__defaults__") is not defaults
            or object.__getattribute__(current, "__kwdefaults__")
            is not kwdefaults
        ):
            raise ValueError("hybrid_production_entry_dependency_drift")
    for entry in _external_function_pins:
        if type(entry) is not tuple or len(entry) != 6:
            raise ValueError("hybrid_production_entry_dependency_drift")
        module, name, issued, code, defaults, kwdefaults = entry
        current = object.__getattribute__(module, name)
        if (
            type(name) is not str
            or type(issued) is not FunctionType
            or type(code) is not CodeType
            or current is not issued
            or type(current) is not FunctionType
            or object.__getattribute__(current, "__code__") is not code
            or object.__getattribute__(current, "__defaults__") is not defaults
            or object.__getattribute__(current, "__kwdefaults__")
            is not kwdefaults
        ):
            raise ValueError("hybrid_production_entry_dependency_drift")
    for entry in _object_pins:
        if type(entry) is not tuple or len(entry) != 3:
            raise ValueError("hybrid_production_entry_dependency_drift")
        name, issued, issued_type = entry
        current = dict.get(_module_globals, name)
        if current is not issued or type(current) is not issued_type:
            raise ValueError("hybrid_production_entry_dependency_drift")
    for entry in _class_method_pins:
        if type(entry) is not tuple or len(entry) != 6:
            raise ValueError("hybrid_production_entry_dependency_drift")
        owner, name, issued, code, defaults, kwdefaults = entry
        current = type.__getattribute__(owner, "__dict__").get(name)
        if type(current) is classmethod:
            current = object.__getattribute__(current, "__func__")
        if (
            current is not issued
            or type(current) is not FunctionType
            or object.__getattribute__(current, "__code__") is not code
            or object.__getattribute__(current, "__defaults__") is not defaults
            or object.__getattribute__(current, "__kwdefaults__")
            is not kwdefaults
        ):
            raise ValueError("hybrid_production_entry_dependency_drift")


_ISSUED_FUSION_ENTRY_DEPENDENCY_CHECKER = (
    _validate_fusion_entry_dependencies
)
_PINNED_FUSION_ENTRY_DEPENDENCY_CHECKER_CODE = (
    _validate_fusion_entry_dependencies.__code__
)


class HybridChildRetriever:
    def __init__(self, store, dense, lexical):
        self.store, self.dense, self.lexical = store, dense, lexical

    @classmethod
    def from_loaded_artifacts(
        cls,
        store,
        dense,
        lexical,
        *,
        _dependency_checker=None,
        _dependency_checker_code=None,
    ):
        """Build a production retriever from loader-attested exact lane objects."""

        module_namespace = globals()
        checker_defaults = (
            None
            if type(_dependency_checker) is not FunctionType
            else object.__getattribute__(_dependency_checker, "__defaults__")
        )
        if (
            _dependency_checker
            is not dict.get(
                module_namespace, "_ISSUED_FUSION_ENTRY_DEPENDENCY_CHECKER"
            )
            or type(_dependency_checker) is not FunctionType
            or object.__getattribute__(_dependency_checker, "__code__")
            is not _dependency_checker_code
            or _dependency_checker_code
            is not dict.get(
                module_namespace,
                "_PINNED_FUSION_ENTRY_DEPENDENCY_CHECKER_CODE",
            )
            or checker_defaults
            is not dict.get(
                module_namespace,
                "_ISSUED_FUSION_ENTRY_DEPENDENCY_DEFAULTS",
            )
            or type(checker_defaults) is not tuple
            or len(checker_defaults) != 5
            or tuple.__getitem__(checker_defaults, 0) is not module_namespace
            or object.__getattribute__(_dependency_checker, "__kwdefaults__")
            is not None
        ):
            raise ValueError("hybrid_production_entry_dependency_drift")
        _dependency_checker()
        if cls is not HybridChildRetriever or type(store) is not EvidenceStore:
            raise ValueError("exact_hybrid_production_factory_required")
        _ISSUED_PREFLIGHT_LOADED_DENSE_ARTIFACT(
            dense, store, production=True
        )
        _ISSUED_PREFLIGHT_LOADED_LEXICAL_ARTIFACT(lexical, store)
        dense_attestation = _ISSUED_REQUIRE_LOADED_DENSE_ARTIFACT(
            dense, store, production=True
        )
        lexical_attestation = _ISSUED_REQUIRE_LOADED_LEXICAL_ARTIFACT(
            lexical, store, production=True
        )
        retriever = cls(store, dense, lexical)
        binding = HybridProductionBinding(
            {
                "bundle_sha256": object.__getattribute__(
                    store, "bundle_sha256"
                ),
                "rows_sha256": _ISSUED_ROW_HASH(store),
                "dense_attestation_sha256": object.__getattribute__(
                    dense_attestation, "attestation_sha256"
                ),
                "lexical_attestation_sha256": object.__getattribute__(
                    lexical_attestation, "attestation_sha256"
                ),
                "dense_artifact_sha256": object.__getattribute__(
                    dense, "artifact_sha256"
                ),
                "lexical_artifact_sha256": object.__getattribute__(
                    lexical, "artifact_sha256"
                ),
                "fusion_config_sha256": _ISSUED_DIGEST(
                    {"algorithm": "reciprocal_rank_fusion", "rrf_k": 60}
                ),
            },
            _token=_HYBRID_PRODUCTION_BINDING,
        )
        namespace = object.__getattribute__(retriever, "__dict__")
        if type(namespace) is not dict or set(namespace) != {
            "store",
            "dense",
            "lexical",
        }:
            raise ValueError("hybrid_production_runtime_drift")
        snapshot = {
            "store": dict.__getitem__(namespace, "store"),
            "dense": dict.__getitem__(namespace, "dense"),
            "lexical": dict.__getitem__(namespace, "lexical"),
            "binding": binding,
            "binding_values": _ISSUED_HYBRID_BINDING_VALUES(binding),
        }
        _ISSUED_REGISTER_PRODUCTION_HYBRID(retriever, binding, snapshot)
        return retriever

    @property
    def production_binding(self) -> HybridProductionBinding:
        namespace = object.__getattribute__(self, "__dict__")
        return _PINNED_REQUIRE_PRODUCTION_HYBRID(
            self, dict.__getitem__(namespace, "store")
        )

    def search(
        self,
        query,
        *,
        dense_k,
        lexical_k,
        scope: ResolvedScope,
    ):
        module_namespace = globals()
        dependency_checker = dict.get(
            module_namespace, "_validate_fusion_entry_dependencies"
        )
        checker_defaults = (
            None
            if type(dependency_checker) is not FunctionType
            else object.__getattribute__(dependency_checker, "__defaults__")
        )
        if (
            dependency_checker
            is not dict.get(
                module_namespace, "_ISSUED_FUSION_ENTRY_DEPENDENCY_CHECKER"
            )
            or type(dependency_checker) is not FunctionType
            or object.__getattribute__(dependency_checker, "__code__")
            is not dict.get(
                module_namespace,
                "_PINNED_FUSION_ENTRY_DEPENDENCY_CHECKER_CODE",
            )
            or checker_defaults
            is not dict.get(
                module_namespace,
                "_ISSUED_FUSION_ENTRY_DEPENDENCY_DEFAULTS",
            )
            or type(checker_defaults) is not tuple
            or len(checker_defaults) != 5
            or tuple.__getitem__(checker_defaults, 0) is not module_namespace
            or object.__getattribute__(dependency_checker, "__kwdefaults__")
            is not None
        ):
            raise ValueError("hybrid_production_entry_dependency_drift")
        dependency_checker()
        namespace = object.__getattribute__(self, "__dict__")
        store = dict.__getitem__(namespace, "store")
        dense_lane = dict.__getitem__(namespace, "dense")
        lexical_lane = dict.__getitem__(namespace, "lexical")
        production = _PINNED_PRODUCTION_HYBRID_ENTRY(self) is not None
        if production:
            _PINNED_REQUIRE_PRODUCTION_HYBRID(self, store)
        scope_state, allowed_doc_ids = _PINNED_RESOLVED_SCOPE_VALUES(scope)
        if any(type(k) is not int or k < 1 for k in (dense_k, lexical_k)):
            raise ValueError("invalid_hybrid_scope_or_budget")
        if scope_state == "empty":
            empty = _PINNED_SEARCH_RESULT_CLASS((), {"granularity": "child", "bundle_sha256": object.__getattribute__(store, "bundle_sha256"),
                                      "empty_scope": True, "lane_calls": 0})
            return _PINNED_FUSE_RRF(empty, empty, store)
        if production:
            dense_search = type.__getattribute__(type(dense_lane), "__dict__").get(
                "search"
            )
            lexical_search = type.__getattribute__(
                type(lexical_lane), "__dict__"
            ).get("search")
            if type(dense_search) is not FunctionType or type(
                lexical_search
            ) is not FunctionType:
                raise ValueError("hybrid_production_method_override")
            dense = dense_search(
                dense_lane,
                query,
                dense_k,
                allowed_doc_ids=allowed_doc_ids,
            )
            lexical = lexical_search(
                lexical_lane,
                query,
                lexical_k,
                allowed_doc_ids=allowed_doc_ids,
            )
        else:
            dense = dense_lane.search(
                query, dense_k, allowed_doc_ids=allowed_doc_ids
            )
            lexical = lexical_lane.search(
                query, lexical_k, allowed_doc_ids=allowed_doc_ids
            )
        return _PINNED_FUSE_RRF(dense, lexical, store)


_PINNED_HYBRID_SEARCH = HybridChildRetriever.search
_PINNED_HYBRID_SEARCH_CODE = HybridChildRetriever.search.__code__
_PINNED_HYBRID_SEARCH_DEFAULTS = HybridChildRetriever.search.__defaults__
_PINNED_HYBRID_SEARCH_KWDEFAULTS = (
    None
    if HybridChildRetriever.search.__kwdefaults__ is None
    else dict(HybridChildRetriever.search.__kwdefaults__)
)
_PINNED_HYBRID_GETATTRIBUTE = HybridChildRetriever.__getattribute__
_PINNED_HYBRID_HASH = HybridChildRetriever.__hash__


def preflight_production_hybrid(
    retriever: HybridChildRetriever,
    store: EvidenceStore,
    _helper_pins=_FUSION_PREFLIGHT_HELPER_PINS,
    _object_pins=_FUSION_PREFLIGHT_OBJECT_PINS,
    _module_attribute_pins=_FUSION_PREFLIGHT_MODULE_ATTRIBUTE_PINS,
) -> tuple[HybridProductionBinding, dict[str, object]]:
    """Validate exact issued identities without traversing the evidence store."""

    module_namespace = globals()
    if (
        _helper_pins
        is not dict.get(
            module_namespace, "_ISSUED_FUSION_PREFLIGHT_HELPER_PINS"
        )
        or _helper_pins
        is not dict.get(module_namespace, "_FUSION_PREFLIGHT_HELPER_PINS")
        or type(_helper_pins) is not tuple
        or len(_helper_pins) != 20
    ):
        raise ValueError("hybrid_production_validation_dependency_drift")
    for entry in _helper_pins:
        if type(entry) is not tuple or len(entry) != 5:
            raise ValueError("hybrid_production_validation_dependency_drift")
        name, issued, code, defaults, kwdefaults = entry
        current = dict.get(module_namespace, name)
        if (
            type(name) is not str
            or type(issued) is not FunctionType
            or type(code) is not CodeType
            or current is not issued
            or type(current) is not FunctionType
            or object.__getattribute__(current, "__code__") is not code
            or object.__getattribute__(current, "__defaults__") is not defaults
            or object.__getattribute__(current, "__kwdefaults__")
            is not kwdefaults
        ):
            raise ValueError("hybrid_production_validation_dependency_drift")
    if (
        _object_pins
        is not dict.get(
            module_namespace, "_ISSUED_FUSION_PREFLIGHT_OBJECT_PINS"
        )
        or _object_pins
        is not dict.get(module_namespace, "_FUSION_PREFLIGHT_OBJECT_PINS")
        or type(_object_pins) is not tuple
    ):
        raise ValueError("hybrid_production_validation_dependency_drift")
    for entry in _object_pins:
        if type(entry) is not tuple or len(entry) != 3:
            raise ValueError("hybrid_production_validation_dependency_drift")
        name, issued, issued_type = entry
        current = dict.get(module_namespace, name)
        if (
            type(name) is not str
            or current is not issued
            or type(current) is not issued_type
        ):
            raise ValueError("hybrid_production_validation_dependency_drift")
    if (
        _module_attribute_pins
        is not dict.get(
            module_namespace,
            "_ISSUED_FUSION_PREFLIGHT_MODULE_ATTRIBUTE_PINS",
        )
        or _module_attribute_pins
        is not dict.get(
            module_namespace, "_FUSION_PREFLIGHT_MODULE_ATTRIBUTE_PINS"
        )
        or type(_module_attribute_pins) is not tuple
        or len(_module_attribute_pins) != 1
    ):
        raise ValueError("hybrid_production_validation_dependency_drift")
    for owner, name, issued in _module_attribute_pins:
        owner_namespace = object.__getattribute__(owner, "__dict__")
        if (
            type(name) is not str
            or type(owner_namespace) is not dict
            or dict.get(owner_namespace, name) is not issued
        ):
            raise ValueError("hybrid_production_validation_dependency_drift")
    store_namespace = type.__getattribute__(
        _PINNED_EVIDENCE_STORE_CLASS, "__dict__"
    )
    current_candidates = store_namespace.get("candidates")
    if (
        type.__getattribute__(
            _PINNED_EVIDENCE_STORE_CLASS, "__getattribute__"
        )
        is not _PINNED_EVIDENCE_STORE_GETATTRIBUTE
        or current_candidates is not _PINNED_EVIDENCE_STORE_CANDIDATES
        or type(current_candidates) is not FunctionType
        or object.__getattribute__(current_candidates, "__code__")
        is not _PINNED_EVIDENCE_STORE_CANDIDATES_CODE
    ):
        raise ValueError("hybrid_production_validation_dependency_drift")
    if type(retriever) is not HybridChildRetriever or type(store) is not EvidenceStore:
        raise ValueError("hybrid_production_binding_required")
    class_namespace = type.__getattribute__(HybridChildRetriever, "__dict__")
    current_search = class_namespace.get("search")
    current_fuse = globals().get("fuse_rrf")
    if (
        type.__getattribute__(HybridChildRetriever, "__getattribute__")
        is not _PINNED_HYBRID_GETATTRIBUTE
        or type.__getattribute__(HybridChildRetriever, "__hash__")
        is not _PINNED_HYBRID_HASH
        or any(
            name in class_namespace for name in ("store", "dense", "lexical")
        )
        or globals().get("_production_hybrid_entry")
        is not globals().get("_ISSUED_PRODUCTION_HYBRID_ENTRY")
        or globals().get("_PINNED_PRODUCTION_HYBRID_ENTRY")
        is not globals().get("_ISSUED_PRODUCTION_HYBRID_ENTRY")
        or globals().get("_PINNED_FUSE_RRF") is not _ISSUED_FUSE_RRF
        or globals().get("preflight_production_hybrid")
        is not globals().get("_ISSUED_PREFLIGHT_PRODUCTION_HYBRID")
        or globals().get("_PINNED_PREFLIGHT_PRODUCTION_HYBRID")
        is not globals().get("_ISSUED_PREFLIGHT_PRODUCTION_HYBRID")
        or globals().get("require_production_hybrid")
        is not globals().get("_ISSUED_REQUIRE_PRODUCTION_HYBRID")
        or globals().get("_PINNED_REQUIRE_PRODUCTION_HYBRID")
        is not globals().get("_ISSUED_REQUIRE_PRODUCTION_HYBRID")
        or globals().get("_contract_classes_unchanged")
        is not globals().get("_ISSUED_CONTRACT_CLASSES_UNCHANGED")
        or globals().get("_PINNED_CONTRACT_CLASSES_UNCHANGED")
        is not globals().get("_ISSUED_CONTRACT_CLASSES_UNCHANGED")
        or globals().get("_resolved_scope_class_unchanged")
        is not globals().get("_ISSUED_RESOLVED_SCOPE_CLASS_UNCHANGED")
        or globals().get("_PINNED_RESOLVED_SCOPE_CLASS_UNCHANGED")
        is not globals().get("_ISSUED_RESOLVED_SCOPE_CLASS_UNCHANGED")
        or globals().get("_resolved_scope_values")
        is not globals().get("_ISSUED_RESOLVED_SCOPE_VALUES")
        or globals().get("_PINNED_RESOLVED_SCOPE_VALUES")
        is not globals().get("_ISSUED_RESOLVED_SCOPE_VALUES")
        or not _PINNED_CONTRACT_CLASSES_UNCHANGED()
        or not _PINNED_RESOLVED_SCOPE_CLASS_UNCHANGED()
        or not _ISSUED_FUNCTION_UNCHANGED(
            current_search,
            _PINNED_HYBRID_SEARCH,
            _PINNED_HYBRID_SEARCH_CODE,
            _PINNED_HYBRID_SEARCH_DEFAULTS,
            _PINNED_HYBRID_SEARCH_KWDEFAULTS,
        )
        or not _ISSUED_FUNCTION_UNCHANGED(
            current_fuse,
            _PINNED_FUSE_RRF,
            _PINNED_FUSE_RRF_CODE,
            _PINNED_FUSE_RRF_DEFAULTS,
            _PINNED_FUSE_RRF_KWDEFAULTS,
        )
    ):
        raise ValueError("hybrid_production_method_override")
    entry = _ISSUED_PRODUCTION_HYBRID_ENTRY(retriever)
    if entry is None:
        raise ValueError("hybrid_production_binding_required")
    binding, snapshot = entry
    if type(binding) is not HybridProductionBinding or type(snapshot) is not dict:
        raise ValueError("hybrid_production_binding_required")
    if set(snapshot) != {
        "store",
        "dense",
        "lexical",
        "binding",
        "binding_values",
    }:
        raise ValueError("hybrid_production_binding_required")
    namespace = object.__getattribute__(retriever, "__dict__")
    if type(namespace) is not dict or set(namespace) != {
        "store",
        "dense",
        "lexical",
    }:
        raise ValueError("hybrid_production_runtime_drift")
    current = {
        "store": dict.__getitem__(namespace, "store"),
        "dense": dict.__getitem__(namespace, "dense"),
        "lexical": dict.__getitem__(namespace, "lexical"),
        "binding": binding,
    }
    if any(
        snapshot[name] is not value for name, value in current.items()
    ):
        raise ValueError("hybrid_production_nested_identity_drift")
    if current["store"] is not store or "search" in namespace:
        raise ValueError("hybrid_production_runtime_drift")
    current_binding_values = _ISSUED_HYBRID_BINDING_VALUES(binding)
    issued_binding_values = snapshot["binding_values"]
    if (
        type(issued_binding_values) is not tuple
        or any(type(value) is not str for value in issued_binding_values)
        or current_binding_values != issued_binding_values
    ):
        raise ValueError("hybrid_production_binding_drift")
    return binding, current


_ISSUED_PREFLIGHT_PRODUCTION_HYBRID = preflight_production_hybrid
_PINNED_PREFLIGHT_PRODUCTION_HYBRID = _ISSUED_PREFLIGHT_PRODUCTION_HYBRID


_FUSION_REQUIRE_HELPER_PINS = tuple(
    (
        name,
        function,
        object.__getattribute__(function, "__code__"),
        object.__getattribute__(function, "__defaults__"),
        object.__getattribute__(function, "__kwdefaults__"),
    )
    for name, function in (
        ("preflight_production_hybrid", preflight_production_hybrid),
        ("_ISSUED_PREFLIGHT_PRODUCTION_HYBRID", preflight_production_hybrid),
        ("_PINNED_PREFLIGHT_PRODUCTION_HYBRID", preflight_production_hybrid),
        (
            "validate_evidence_store_snapshot",
            validate_evidence_store_snapshot,
        ),
        (
            "_ISSUED_VALIDATE_EVIDENCE_STORE_SNAPSHOT",
            validate_evidence_store_snapshot,
        ),
        ("_row_hash", _row_hash),
        ("_ISSUED_ROW_HASH", _row_hash),
        ("_digest", _digest),
        ("_ISSUED_DIGEST", _digest),
        (
            "_ISSUED_REQUIRE_LOADED_DENSE_ARTIFACT",
            _ISSUED_REQUIRE_LOADED_DENSE_ARTIFACT,
        ),
        (
            "_ISSUED_REQUIRE_LOADED_LEXICAL_ARTIFACT",
            _ISSUED_REQUIRE_LOADED_LEXICAL_ARTIFACT,
        ),
    )
)
_ISSUED_FUSION_REQUIRE_HELPER_PINS = _FUSION_REQUIRE_HELPER_PINS
_FUSION_REQUIRE_EXTERNAL_FUNCTION_PINS = tuple(
    (
        module,
        name,
        function,
        object.__getattribute__(function, "__code__"),
        object.__getattribute__(function, "__defaults__"),
        object.__getattribute__(function, "__kwdefaults__"),
    )
    for module, name, function in (
        (
            _DENSE_RUNTIME_MODULE,
            "require_loaded_dense_artifact",
            _ISSUED_REQUIRE_LOADED_DENSE_ARTIFACT,
        ),
        (
            _LEXICAL_RUNTIME_MODULE,
            "require_loaded_lexical_artifact",
            _ISSUED_REQUIRE_LOADED_LEXICAL_ARTIFACT,
        ),
    )
)
_ISSUED_FUSION_REQUIRE_EXTERNAL_FUNCTION_PINS = (
    _FUSION_REQUIRE_EXTERNAL_FUNCTION_PINS
)


def require_production_hybrid(
    retriever: HybridChildRetriever,
    store: EvidenceStore,
    _helper_pins=_FUSION_REQUIRE_HELPER_PINS,
    _external_function_pins=_FUSION_REQUIRE_EXTERNAL_FUNCTION_PINS,
    _object_pins=_FUSION_PREFLIGHT_OBJECT_PINS,
    _module_attribute_pins=_FUSION_PREFLIGHT_MODULE_ATTRIBUTE_PINS,
) -> HybridProductionBinding:
    """Revalidate a factory-issued binding immediately before production use."""

    module_namespace = globals()
    if (
        _helper_pins
        is not dict.get(
            module_namespace, "_ISSUED_FUSION_REQUIRE_HELPER_PINS"
        )
        or _helper_pins
        is not dict.get(module_namespace, "_FUSION_REQUIRE_HELPER_PINS")
        or type(_helper_pins) is not tuple
        or len(_helper_pins) != 11
    ):
        raise ValueError("hybrid_production_validation_dependency_drift")
    for entry in _helper_pins:
        if type(entry) is not tuple or len(entry) != 5:
            raise ValueError("hybrid_production_validation_dependency_drift")
        name, issued, code, defaults, kwdefaults = entry
        current_function = dict.get(module_namespace, name)
        if (
            type(name) is not str
            or type(issued) is not FunctionType
            or type(code) is not CodeType
            or current_function is not issued
            or type(current_function) is not FunctionType
            or object.__getattribute__(current_function, "__code__") is not code
            or object.__getattribute__(current_function, "__defaults__")
            is not defaults
            or object.__getattribute__(current_function, "__kwdefaults__")
            is not kwdefaults
        ):
            raise ValueError("hybrid_production_validation_dependency_drift")
    if (
        _external_function_pins
        is not dict.get(
            module_namespace,
            "_ISSUED_FUSION_REQUIRE_EXTERNAL_FUNCTION_PINS",
        )
        or _external_function_pins
        is not dict.get(
            module_namespace, "_FUSION_REQUIRE_EXTERNAL_FUNCTION_PINS"
        )
        or type(_external_function_pins) is not tuple
        or len(_external_function_pins) != 2
    ):
        raise ValueError("hybrid_production_validation_dependency_drift")
    for entry in _external_function_pins:
        if type(entry) is not tuple or len(entry) != 6:
            raise ValueError("hybrid_production_validation_dependency_drift")
        module, name, issued, code, defaults, kwdefaults = entry
        current_function = object.__getattribute__(module, name)
        if (
            type(name) is not str
            or type(issued) is not FunctionType
            or type(code) is not CodeType
            or current_function is not issued
            or type(current_function) is not FunctionType
            or object.__getattribute__(current_function, "__code__") is not code
            or object.__getattribute__(current_function, "__defaults__")
            is not defaults
            or object.__getattribute__(current_function, "__kwdefaults__")
            is not kwdefaults
        ):
            raise ValueError("hybrid_production_validation_dependency_drift")
    if (
        _object_pins
        is not dict.get(
            module_namespace, "_ISSUED_FUSION_PREFLIGHT_OBJECT_PINS"
        )
        or _object_pins
        is not dict.get(module_namespace, "_FUSION_PREFLIGHT_OBJECT_PINS")
        or type(_object_pins) is not tuple
    ):
        raise ValueError("hybrid_production_validation_dependency_drift")
    for name, issued, issued_type in _object_pins:
        current_object = dict.get(module_namespace, name)
        if (
            type(name) is not str
            or current_object is not issued
            or type(current_object) is not issued_type
        ):
            raise ValueError("hybrid_production_validation_dependency_drift")
    if (
        _module_attribute_pins
        is not dict.get(
            module_namespace,
            "_ISSUED_FUSION_PREFLIGHT_MODULE_ATTRIBUTE_PINS",
        )
        or _module_attribute_pins
        is not dict.get(
            module_namespace, "_FUSION_PREFLIGHT_MODULE_ATTRIBUTE_PINS"
        )
        or type(_module_attribute_pins) is not tuple
        or len(_module_attribute_pins) != 1
    ):
        raise ValueError("hybrid_production_validation_dependency_drift")
    for owner, name, issued in _module_attribute_pins:
        owner_namespace = object.__getattribute__(owner, "__dict__")
        if (
            type(name) is not str
            or type(owner_namespace) is not dict
            or dict.get(owner_namespace, name) is not issued
        ):
            raise ValueError("hybrid_production_validation_dependency_drift")
    store_namespace = type.__getattribute__(
        _PINNED_EVIDENCE_STORE_CLASS, "__dict__"
    )
    current_candidates = store_namespace.get("candidates")
    if (
        type.__getattribute__(
            _PINNED_EVIDENCE_STORE_CLASS, "__getattribute__"
        )
        is not _PINNED_EVIDENCE_STORE_GETATTRIBUTE
        or current_candidates is not _PINNED_EVIDENCE_STORE_CANDIDATES
        or type(current_candidates) is not FunctionType
        or object.__getattribute__(current_candidates, "__code__")
        is not _PINNED_EVIDENCE_STORE_CANDIDATES_CODE
    ):
        raise ValueError("hybrid_production_validation_dependency_drift")
    binding, current = _ISSUED_PREFLIGHT_PRODUCTION_HYBRID(retriever, store)
    try:
        _ISSUED_VALIDATE_EVIDENCE_STORE_SNAPSHOT(
            store, object.__getattribute__(store, "bundle_sha256")
        )
    except ValueError as exc:
        raise ValueError("hybrid_production_store_payload_drift") from exc
    dense = _ISSUED_REQUIRE_LOADED_DENSE_ARTIFACT(
        current["dense"], store, production=True
    )
    lexical = _ISSUED_REQUIRE_LOADED_LEXICAL_ARTIFACT(
        current["lexical"], store, production=True
    )
    checks = {
        "bundle_sha256": object.__getattribute__(store, "bundle_sha256"),
        "rows_sha256": _ISSUED_ROW_HASH(store),
        "dense_attestation_sha256": object.__getattribute__(
            dense, "attestation_sha256"
        ),
        "lexical_attestation_sha256": object.__getattribute__(
            lexical, "attestation_sha256"
        ),
        "dense_artifact_sha256": object.__getattribute__(current["dense"], "artifact_sha256"),
        "lexical_artifact_sha256": object.__getattribute__(current["lexical"], "artifact_sha256"),
        "fusion_config_sha256": _ISSUED_DIGEST(
            {"algorithm": "reciprocal_rank_fusion", "rrf_k": 60}
        ),
    }
    if any(
        object.__getattribute__(binding, name) != value
        for name, value in checks.items()
    ):
        raise ValueError("hybrid_production_binding_drift")
    return binding


_ISSUED_REQUIRE_PRODUCTION_HYBRID = require_production_hybrid
_PINNED_REQUIRE_PRODUCTION_HYBRID = _ISSUED_REQUIRE_PRODUCTION_HYBRID


_FUSION_ENTRY_FUNCTION_PINS = tuple(
    (
        name,
        function,
        object.__getattribute__(function, "__code__"),
        object.__getattribute__(function, "__defaults__"),
        object.__getattribute__(function, "__kwdefaults__"),
    )
    for name, function in (
        ("_production_hybrid_entry", _production_hybrid_entry),
        ("_ISSUED_PRODUCTION_HYBRID_ENTRY", _production_hybrid_entry),
        ("_PINNED_PRODUCTION_HYBRID_ENTRY", _production_hybrid_entry),
        ("_register_production_hybrid", _register_production_hybrid),
        (
            "_ISSUED_REGISTER_PRODUCTION_HYBRID",
            _register_production_hybrid,
        ),
        ("_row_hash", _row_hash),
        ("_ISSUED_ROW_HASH", _row_hash),
        ("_digest", _digest),
        ("_ISSUED_DIGEST", _digest),
        ("_hybrid_binding_values", _hybrid_binding_values),
        ("_ISSUED_HYBRID_BINDING_VALUES", _hybrid_binding_values),
        ("_resolved_scope_values", _resolved_scope_values),
        ("_ISSUED_RESOLVED_SCOPE_VALUES", _resolved_scope_values),
        ("_PINNED_RESOLVED_SCOPE_VALUES", _resolved_scope_values),
        ("fuse_rrf", fuse_rrf),
        ("_ISSUED_FUSE_RRF", fuse_rrf),
        ("_PINNED_FUSE_RRF", fuse_rrf),
        ("preflight_production_hybrid", preflight_production_hybrid),
        ("_ISSUED_PREFLIGHT_PRODUCTION_HYBRID", preflight_production_hybrid),
        ("_PINNED_PREFLIGHT_PRODUCTION_HYBRID", preflight_production_hybrid),
        ("require_production_hybrid", require_production_hybrid),
        ("_ISSUED_REQUIRE_PRODUCTION_HYBRID", require_production_hybrid),
        ("_PINNED_REQUIRE_PRODUCTION_HYBRID", require_production_hybrid),
        (
            "_ISSUED_PREFLIGHT_LOADED_DENSE_ARTIFACT",
            _ISSUED_PREFLIGHT_LOADED_DENSE_ARTIFACT,
        ),
        (
            "_ISSUED_REQUIRE_LOADED_DENSE_ARTIFACT",
            _ISSUED_REQUIRE_LOADED_DENSE_ARTIFACT,
        ),
        (
            "_ISSUED_PREFLIGHT_LOADED_LEXICAL_ARTIFACT",
            _ISSUED_PREFLIGHT_LOADED_LEXICAL_ARTIFACT,
        ),
        (
            "_ISSUED_REQUIRE_LOADED_LEXICAL_ARTIFACT",
            _ISSUED_REQUIRE_LOADED_LEXICAL_ARTIFACT,
        ),
    )
)
_ISSUED_FUSION_ENTRY_FUNCTION_PINS = _FUSION_ENTRY_FUNCTION_PINS
_FUSION_ENTRY_EXTERNAL_FUNCTION_PINS = tuple(
    (
        module,
        name,
        function,
        object.__getattribute__(function, "__code__"),
        object.__getattribute__(function, "__defaults__"),
        object.__getattribute__(function, "__kwdefaults__"),
    )
    for module, name, function in (
        (
            _DENSE_RUNTIME_MODULE,
            "preflight_loaded_dense_artifact",
            _ISSUED_PREFLIGHT_LOADED_DENSE_ARTIFACT,
        ),
        (
            _DENSE_RUNTIME_MODULE,
            "require_loaded_dense_artifact",
            _ISSUED_REQUIRE_LOADED_DENSE_ARTIFACT,
        ),
        (
            _LEXICAL_RUNTIME_MODULE,
            "preflight_loaded_lexical_artifact",
            _ISSUED_PREFLIGHT_LOADED_LEXICAL_ARTIFACT,
        ),
        (
            _LEXICAL_RUNTIME_MODULE,
            "require_loaded_lexical_artifact",
            _ISSUED_REQUIRE_LOADED_LEXICAL_ARTIFACT,
        ),
    )
)
_ISSUED_FUSION_ENTRY_EXTERNAL_FUNCTION_PINS = (
    _FUSION_ENTRY_EXTERNAL_FUNCTION_PINS
)
_FUSION_ENTRY_OBJECT_PINS = (
    ("_PRODUCTION_HYBRIDS", _ISSUED_PRODUCTION_HYBRIDS, dict),
    ("_ISSUED_PRODUCTION_HYBRIDS", _ISSUED_PRODUCTION_HYBRIDS, dict),
    ("ref", _ISSUED_REF, type(_ISSUED_REF)),
    ("_ISSUED_REF", _ISSUED_REF, type(_ISSUED_REF)),
    ("EvidenceStore", _PINNED_EVIDENCE_STORE_CLASS, type),
    ("HybridProductionBinding", HybridProductionBinding, type),
    ("HybridChildRetriever", HybridChildRetriever, type),
    ("_HYBRID_PRODUCTION_BINDING", _HYBRID_PRODUCTION_BINDING, object),
    ("_DENSE_RUNTIME_MODULE", _DENSE_RUNTIME_MODULE, type(_DENSE_RUNTIME_MODULE)),
    (
        "_LEXICAL_RUNTIME_MODULE",
        _LEXICAL_RUNTIME_MODULE,
        type(_LEXICAL_RUNTIME_MODULE),
    ),
    (
        "_FUSION_PREFLIGHT_OBJECT_PINS",
        _FUSION_PREFLIGHT_OBJECT_PINS,
        tuple,
    ),
)
_ISSUED_FUSION_ENTRY_OBJECT_PINS = _FUSION_ENTRY_OBJECT_PINS

_factory_function = type.__getattribute__(
    HybridChildRetriever, "__dict__"
)["from_loaded_artifacts"].__func__
_factory_function.__kwdefaults__.update(
    {
        "_dependency_checker": _ISSUED_FUSION_ENTRY_DEPENDENCY_CHECKER,
        "_dependency_checker_code": _PINNED_FUSION_ENTRY_DEPENDENCY_CHECKER_CODE,
    }
)
_FUSION_ENTRY_CLASS_METHOD_PINS = tuple(
    (
        owner,
        name,
        function,
        object.__getattribute__(function, "__code__"),
        object.__getattribute__(function, "__defaults__"),
        object.__getattribute__(function, "__kwdefaults__"),
    )
    for owner, name, function in (
        (
            HybridChildRetriever,
            "__init__",
            type.__getattribute__(HybridChildRetriever, "__dict__")["__init__"],
        ),
        (HybridChildRetriever, "from_loaded_artifacts", _factory_function),
        (HybridChildRetriever, "search", _PINNED_HYBRID_SEARCH),
        (
            HybridProductionBinding,
            "__init__",
            type.__getattribute__(HybridProductionBinding, "__dict__")["__init__"],
        ),
    )
)
_ISSUED_FUSION_ENTRY_CLASS_METHOD_PINS = _FUSION_ENTRY_CLASS_METHOD_PINS
_FUSION_ENTRY_DEPENDENCY_DEFAULTS = (
    globals(),
    _FUSION_ENTRY_FUNCTION_PINS,
    _FUSION_ENTRY_EXTERNAL_FUNCTION_PINS,
    _FUSION_ENTRY_OBJECT_PINS,
    _FUSION_ENTRY_CLASS_METHOD_PINS,
)
_ISSUED_FUSION_ENTRY_DEPENDENCY_DEFAULTS = (
    _FUSION_ENTRY_DEPENDENCY_DEFAULTS
)
_validate_fusion_entry_dependencies.__defaults__ = (
    _FUSION_ENTRY_DEPENDENCY_DEFAULTS
)
_PINNED_HYBRID_SEARCH_DEFAULTS = _PINNED_HYBRID_SEARCH.__defaults__
_PINNED_HYBRID_SEARCH_KWDEFAULTS = (
    None
    if _PINNED_HYBRID_SEARCH.__kwdefaults__ is None
    else dict(_PINNED_HYBRID_SEARCH.__kwdefaults__)
)
