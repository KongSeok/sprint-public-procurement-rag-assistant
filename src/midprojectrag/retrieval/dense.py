"""Pinned KURE exact child lane; independent of legacy page vector identities."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
from types import CodeType, FunctionType, MappingProxyType, MemberDescriptorType
from weakref import ReferenceType, ref
import numpy as np

from midprojectrag.evidence import EvidenceStore, validate_evidence_store_snapshot
from midprojectrag.evidence.artifacts import file_sha, private_path, write_new_json
from midprojectrag.stacks.local.gcp_config import (
    KURE_MODEL_ID, KURE_MODEL_REVISION, KURE_DIMENSIONS, KURE_POOLING, KURE_PROMPT_VERSION,
)
from midprojectrag.stacks.local.hf_embeddings import (
    EmbeddingPostCallContractError,
    EmbeddingProviderError,
    HuggingFaceTokenCounter,
    KureEmbeddingProvider,
    _default_encoder_loader,
    _default_tokenizer_loader,
)
from .contracts import (
    Candidate,
    RetrievalPostCallContractError,
    RetrievalProviderError,
    SearchResult,
    validate_search,
)

try:  # Capture dependency handles before application-level monkeypatching.
    from sentence_transformers.sentence_transformer.model import (
        SentenceTransformer as _PINNED_SENTENCE_TRANSFORMER_CLASS,
    )
    from transformers.models.auto.tokenization_auto import (
        AutoTokenizer as _PINNED_AUTO_TOKENIZER_CLASS,
    )
    from transformers.tokenization_utils_base import (
        PreTrainedTokenizerBase as _PINNED_TOKENIZER_BASE_CLASS,
    )
    _PINNED_SENTENCE_TRANSFORMERS_VERSION = version("sentence-transformers")
    _PINNED_TRANSFORMERS_VERSION = version("transformers")
except (ImportError, PackageNotFoundError):  # Synthetic lanes remain usable without production extras.
    _PINNED_SENTENCE_TRANSFORMER_CLASS = None
    _PINNED_AUTO_TOKENIZER_CLASS = None
    _PINNED_TOKENIZER_BASE_CLASS = None
    _PINNED_SENTENCE_TRANSFORMERS_VERSION = None
    _PINNED_TRANSFORMERS_VERSION = None

_PINNED_AUTO_TOKENIZER_LOAD = (
    _PINNED_AUTO_TOKENIZER_CLASS.from_pretrained
    if _PINNED_AUTO_TOKENIZER_CLASS is not None
    else None
)

KURE_IDENTITY = MappingProxyType({"model": KURE_MODEL_ID, "revision": KURE_MODEL_REVISION,
    "dimensions": KURE_DIMENSIONS, "pooling": KURE_POOLING, "prompt_version": KURE_PROMPT_VERSION, "prompt": ""})
_VERIFIED_VECTOR_SNAPSHOT = object()
_LOADED_DENSE_ATTESTATION = object()


class _IdentityWeakRegistry:
    """Weak identity map that never evaluates a key object's ``__hash__``."""

    __slots__ = ("_entries", "__weakref__")

    def __init__(self) -> None:
        object.__setattr__(self, "_entries", {})

    def _drop(self, identity: int, dead: ReferenceType[object]) -> None:
        entries = object.__getattribute__(self, "_entries")
        if type(entries) is not dict or type(dead) is not ReferenceType:
            raise ValueError("dense_production_registry_entry_drift")
        current = dict.get(entries, identity)
        if current is None:
            return
        if type(current) is not tuple or tuple.__len__(current) != 2:
            raise ValueError("dense_production_registry_entry_drift")
        weak = tuple.__getitem__(current, 0)
        if type(weak) is not ReferenceType:
            raise ValueError("dense_production_registry_entry_drift")
        if weak is dead:
            dict.pop(entries, identity, None)

    def __setitem__(self, key: object, value: object) -> None:
        entries = object.__getattribute__(self, "_entries")
        if type(entries) is not dict:
            raise ValueError("dense_production_registry_storage_drift")
        identity = id(key)
        owner = ref(self)

        def drop(dead: ReferenceType[object], *, identity: int = identity) -> None:
            registry = owner()
            if registry is not None:
                registry._drop(identity, dead)

        weak = ref(key, drop)
        dict.__setitem__(entries, identity, (weak, value))

    def get(self, key: object, default=None):
        entries = object.__getattribute__(self, "_entries")
        if type(entries) is not dict:
            raise ValueError("dense_production_registry_storage_drift")
        current = dict.get(entries, id(key))
        if current is None:
            return default
        if type(current) is not tuple or tuple.__len__(current) != 2:
            raise ValueError("dense_production_registry_entry_drift")
        weak = tuple.__getitem__(current, 0)
        if type(weak) is not ReferenceType:
            raise ValueError("dense_production_registry_entry_drift")
        if weak() is not key:
            return default
        return tuple.__getitem__(current, 1)

    def pop(self, key: object, default=None):
        entries = object.__getattribute__(self, "_entries")
        if type(entries) is not dict:
            raise ValueError("dense_production_registry_storage_drift")
        identity = id(key)
        current = dict.get(entries, identity)
        if current is None:
            return default
        if type(current) is not tuple or tuple.__len__(current) != 2:
            raise ValueError("dense_production_registry_entry_drift")
        weak = tuple.__getitem__(current, 0)
        if type(weak) is not ReferenceType:
            raise ValueError("dense_production_registry_entry_drift")
        if weak() is not key:
            return default
        dict.pop(entries, identity, None)
        return tuple.__getitem__(current, 1)

    def __contains__(self, key: object) -> bool:
        entries = object.__getattribute__(self, "_entries")
        if type(entries) is not dict:
            raise ValueError("dense_production_registry_storage_drift")
        current = dict.get(entries, id(key))
        if current is None:
            return False
        if type(current) is not tuple or tuple.__len__(current) != 2:
            raise ValueError("dense_production_registry_entry_drift")
        weak = tuple.__getitem__(current, 0)
        if type(weak) is not ReferenceType:
            raise ValueError("dense_production_registry_entry_drift")
        return weak() is key

    def __getitem__(self, key: object):
        current = self.get(key, _VERIFIED_VECTOR_SNAPSHOT)
        if current is _VERIFIED_VECTOR_SNAPSHOT:
            raise KeyError(id(key))
        return current


_LOADED_DENSE = _IdentityWeakRegistry()
_LOADED_DENSE_RUNTIME = _IdentityWeakRegistry()
_LOADED_DENSE_SNAPSHOT = _IdentityWeakRegistry()
_BUILT_DENSE_RUNTIME = _IdentityWeakRegistry()
_ISSUED_KURE_EMBED = KureEmbeddingProvider.embed
_ISSUED_KURE_GET_ENCODER = KureEmbeddingProvider._get_encoder
_ISSUED_COUNTER_GET_TOKENIZER = HuggingFaceTokenCounter._get_tokenizer
_ISSUED_COUNTER_COUNT = HuggingFaceTokenCounter.count
_PINNED_KURE_EMBED = _ISSUED_KURE_EMBED
_PINNED_KURE_GET_ENCODER = _ISSUED_KURE_GET_ENCODER
_PINNED_COUNTER_GET_TOKENIZER = _ISSUED_COUNTER_GET_TOKENIZER
_PINNED_COUNTER_COUNT = _ISSUED_COUNTER_COUNT
_PINNED_KURE_INIT = KureEmbeddingProvider.__init__
_PINNED_COUNTER_INIT = HuggingFaceTokenCounter.__init__
_PINNED_KURE_NEW = KureEmbeddingProvider.__new__
_PINNED_COUNTER_NEW = HuggingFaceTokenCounter.__new__
_PINNED_KURE_GETATTRIBUTE = KureEmbeddingProvider.__getattribute__
_PINNED_COUNTER_GETATTRIBUTE = HuggingFaceTokenCounter.__getattribute__
_PINNED_KURE_SETATTRIBUTE = KureEmbeddingProvider.__setattr__
_PINNED_COUNTER_SETATTRIBUTE = HuggingFaceTokenCounter.__setattr__
_PINNED_KURE_HASH = KureEmbeddingProvider.__hash__
_PINNED_COUNTER_HASH = HuggingFaceTokenCounter.__hash__
_PINNED_KURE_EMBED_CODE = _ISSUED_KURE_EMBED.__code__
_PINNED_KURE_GET_ENCODER_CODE = _ISSUED_KURE_GET_ENCODER.__code__
_PINNED_COUNTER_GET_TOKENIZER_CODE = _ISSUED_COUNTER_GET_TOKENIZER.__code__
_PINNED_COUNTER_COUNT_CODE = _ISSUED_COUNTER_COUNT.__code__
_PINNED_KURE_INIT_CODE = _PINNED_KURE_INIT.__code__
_PINNED_COUNTER_INIT_CODE = _PINNED_COUNTER_INIT.__code__

_KURE_STATE_FIELDS = frozenset(
    {
        "model",
        "revision",
        "dimensions",
        "pooling",
        "prompt_version",
        "prompt",
        "batch_size",
        "device",
        "local_files_only",
        "trust_remote_code",
        "execution_kind",
        "_counter",
        "_encoder",
        "_encoder_loader",
    }
)
_COUNTER_STATE_FIELDS = frozenset(
    {
        "model",
        "revision",
        "local_files_only",
        "trust_remote_code",
        "_tokenizer",
        "_tokenizer_loader",
    }
)


def _require_pinned_function(
    owner: type,
    name: str,
    issued: FunctionType,
    issued_code: CodeType,
    code: str,
) -> None:
    namespace = type.__getattribute__(owner, "__dict__")
    current = namespace.get(name)
    if (
        type(current) is not FunctionType
        or current is not issued
        or object.__getattribute__(current, "__code__") is not issued_code
    ):
        raise ValueError(code)


def _require_pinned_provider_methods() -> None:
    if (
        _PINNED_KURE_EMBED is not _ISSUED_KURE_EMBED
        or _PINNED_KURE_GET_ENCODER is not _ISSUED_KURE_GET_ENCODER
        or _PINNED_COUNTER_GET_TOKENIZER is not _ISSUED_COUNTER_GET_TOKENIZER
        or _PINNED_COUNTER_COUNT is not _ISSUED_COUNTER_COUNT
        or type.__getattribute__(KureEmbeddingProvider, "__getattribute__")
        is not _PINNED_KURE_GETATTRIBUTE
        or type.__getattribute__(HuggingFaceTokenCounter, "__getattribute__")
        is not _PINNED_COUNTER_GETATTRIBUTE
        or type.__getattribute__(KureEmbeddingProvider, "__setattr__")
        is not _PINNED_KURE_SETATTRIBUTE
        or type.__getattribute__(HuggingFaceTokenCounter, "__setattr__")
        is not _PINNED_COUNTER_SETATTRIBUTE
        or type.__getattribute__(KureEmbeddingProvider, "__new__")
        is not _PINNED_KURE_NEW
        or type.__getattribute__(HuggingFaceTokenCounter, "__new__")
        is not _PINNED_COUNTER_NEW
        or type.__getattribute__(KureEmbeddingProvider, "__hash__")
        is not _PINNED_KURE_HASH
        or type.__getattribute__(HuggingFaceTokenCounter, "__hash__")
        is not _PINNED_COUNTER_HASH
    ):
        raise ValueError("dense_production_provider_method_override")
    for owner, name, method, method_code in (
        (KureEmbeddingProvider, "__init__", _PINNED_KURE_INIT, _PINNED_KURE_INIT_CODE),
        (KureEmbeddingProvider, "embed", _ISSUED_KURE_EMBED, _PINNED_KURE_EMBED_CODE),
        (
            KureEmbeddingProvider,
            "_get_encoder",
            _ISSUED_KURE_GET_ENCODER,
            _PINNED_KURE_GET_ENCODER_CODE,
        ),
        (HuggingFaceTokenCounter, "__init__", _PINNED_COUNTER_INIT, _PINNED_COUNTER_INIT_CODE),
        (HuggingFaceTokenCounter, "count", _ISSUED_COUNTER_COUNT, _PINNED_COUNTER_COUNT_CODE),
        (
            HuggingFaceTokenCounter,
            "_get_tokenizer",
            _ISSUED_COUNTER_GET_TOKENIZER,
            _PINNED_COUNTER_GET_TOKENIZER_CODE,
        ),
    ):
        _require_pinned_function(
            owner,
            name,
            method,
            method_code,
            "dense_production_provider_method_override",
        )


def _exact_instance_state(instance: object, expected: frozenset[str], code: str) -> dict:
    try:
        state = object.__getattribute__(instance, "__dict__")
    except AttributeError as exc:
        raise ValueError(code) from exc
    if type(state) is not dict:
        raise ValueError(code)
    keys = tuple(state)
    if (
        len(keys) != len(expected)
        or any(type(key) is not str for key in keys)
        or frozenset(keys) != expected
    ):
        raise ValueError(code)
    return state


def _production_provider_state(provider) -> tuple[dict, dict]:
    if type(provider) is not KureEmbeddingProvider:
        raise ValueError("dense_production_embedding_provider_required")
    _require_pinned_provider_methods()
    state = _exact_instance_state(
        provider, _KURE_STATE_FIELDS, "dense_production_embedding_provider_required"
    )
    counter = state["_counter"]
    if type(counter) is not HuggingFaceTokenCounter:
        raise ValueError("dense_production_token_counter_required")
    counter_state = _exact_instance_state(
        counter, _COUNTER_STATE_FIELDS, "dense_production_token_counter_required"
    )
    return state, counter_state


def _sealed_tokenizer_loader(**kwargs):
    if (
        _PINNED_AUTO_TOKENIZER_LOAD is None
        or getattr(_PINNED_AUTO_TOKENIZER_LOAD, "__module__", None)
        != "transformers.models.auto.tokenization_auto"
        or getattr(_PINNED_AUTO_TOKENIZER_LOAD, "__qualname__", None)
        != "AutoTokenizer.from_pretrained"
        or _PINNED_TRANSFORMERS_VERSION != "4.57.6"
    ):
        raise RuntimeError("transformers_dependency_missing")
    return _PINNED_AUTO_TOKENIZER_LOAD(**kwargs)


def _sealed_encoder_loader(**kwargs):
    if (
        _PINNED_SENTENCE_TRANSFORMER_CLASS is None
        or _PINNED_SENTENCE_TRANSFORMER_CLASS.__module__
        != "sentence_transformers.sentence_transformer.model"
        or _PINNED_SENTENCE_TRANSFORMER_CLASS.__qualname__ != "SentenceTransformer"
        or _PINNED_SENTENCE_TRANSFORMERS_VERSION != "5.7.0"
    ):
        raise RuntimeError("sentence_transformers_dependency_missing")
    return _PINNED_SENTENCE_TRANSFORMER_CLASS(**kwargs)


def _seal_provider_loaders(provider) -> None:
    """Replace dynamic public factories with import-time captured handles."""

    state, counter_state = _production_provider_state(provider)
    if state["_encoder_loader"] is _default_encoder_loader:
        state["_encoder_loader"] = _sealed_encoder_loader
    elif state["_encoder_loader"] is not _sealed_encoder_loader:
        raise ValueError("dense_production_encoder_loader_not_pinned")
    if counter_state["_tokenizer_loader"] is _default_tokenizer_loader:
        counter_state["_tokenizer_loader"] = _sealed_tokenizer_loader
    elif counter_state["_tokenizer_loader"] is not _sealed_tokenizer_loader:
        raise ValueError("dense_production_tokenizer_loader_not_pinned")


def _validate_loaded_runtime_objects(runtime: tuple[object | None, object | None]) -> None:
    encoder, tokenizer = runtime
    if encoder is None and tokenizer is None:
        return
    if (
        _PINNED_SENTENCE_TRANSFORMER_CLASS is None
        or _PINNED_SENTENCE_TRANSFORMERS_VERSION != "5.7.0"
        or _PINNED_TRANSFORMERS_VERSION != "4.57.6"
        or type(encoder) is not _PINNED_SENTENCE_TRANSFORMER_CLASS
        or _PINNED_TOKENIZER_BASE_CLASS is None
        or not isinstance(tokenizer, _PINNED_TOKENIZER_BASE_CLASS)
    ):
        raise ValueError("dense_production_dependency_runtime_not_pinned")


def _initialize_pinned_provider_runtime(provider) -> tuple[object, object]:
    """Load dependency objects without exposing a user/corpus string to them."""

    state, counter_state = _production_provider_state(provider)
    try:
        encoder = _ISSUED_KURE_GET_ENCODER(provider)
        tokenizer = _ISSUED_COUNTER_GET_TOKENIZER(state["_counter"])
    except Exception as exc:
        raise RetrievalProviderError("dense_provider_error") from exc
    try:
        runtime = (encoder, tokenizer)
        if state["_encoder"] is not encoder or counter_state["_tokenizer"] is not tokenizer:
            raise ValueError("dense_production_provider_runtime_object_drift")
        _validate_loaded_runtime_objects(runtime)
        return runtime
    except RetrievalPostCallContractError:
        raise
    except Exception as exc:
        raise RetrievalPostCallContractError(
            "dense_post_call_contract_error"
        ) from exc


def _digest(value) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _matrix_hash(matrix) -> str:
    value = np.asarray(matrix, dtype=np.float32)
    return sha256(value.tobytes(order="C")).hexdigest()


_DENSE_ATTESTATION_PAYLOAD_FIELDS = (
    "bundle_sha256",
    "rows_sha256",
    "receipt_sha256",
    "vectors_file_sha256",
    "vectors_content_sha256",
    "embedding_identity_sha256",
    "execution_kind",
    "provider_runtime_sha256",
)
_DENSE_ATTESTATION_FIELDS = _DENSE_ATTESTATION_PAYLOAD_FIELDS + (
    "attestation_sha256",
)


@dataclass(frozen=True, slots=True, init=False)
class LoadedDenseArtifactAttestation:
    """Opaque proof that ``load_dense`` verified this exact lane instance."""

    bundle_sha256: str
    rows_sha256: str
    receipt_sha256: str
    vectors_file_sha256: str
    vectors_content_sha256: str
    embedding_identity_sha256: str
    execution_kind: str
    provider_runtime_sha256: str
    attestation_sha256: str

    def __init__(self, payload: dict, *, _token=None):
        if _token is not _LOADED_DENSE_ATTESTATION:
            raise TypeError("loaded_dense_attestation_is_loader_sealed")
        expected = frozenset(_DENSE_ATTESTATION_PAYLOAD_FIELDS)
        if type(payload) is not dict or set(payload) != expected:
            raise ValueError("invalid_loaded_dense_attestation")
        for name in expected:
            value = payload[name]
            if type(value) is not str:
                raise ValueError("invalid_loaded_dense_attestation")
            if name == "execution_kind":
                if value not in {"synthetic", "real_local_model"}:
                    raise ValueError("invalid_loaded_dense_attestation")
            elif name == "provider_runtime_sha256":
                if value and (len(value) != 64 or any(c not in "0123456789abcdef" for c in value)):
                    raise ValueError("invalid_loaded_dense_attestation")
            elif len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ValueError("invalid_loaded_dense_attestation")
            object.__setattr__(self, name, value)
        object.__setattr__(self, "attestation_sha256", _digest(payload))


_PINNED_DENSE_ATTESTATION_GETATTRIBUTE = (
    LoadedDenseArtifactAttestation.__getattribute__
)
_PINNED_DENSE_ATTESTATION_SLOT_DESCRIPTORS = tuple(
    (
        name,
        type.__getattribute__(LoadedDenseArtifactAttestation, "__dict__")[name],
    )
    for name in _DENSE_ATTESTATION_FIELDS
)


def _require_pinned_dense_attestation_shape() -> None:
    namespace = type.__getattribute__(LoadedDenseArtifactAttestation, "__dict__")
    if (
        type.__getattribute__(
            LoadedDenseArtifactAttestation, "__getattribute__"
        )
        is not _PINNED_DENSE_ATTESTATION_GETATTRIBUTE
        or any(
            namespace.get(name) is not issued
            for name, issued in _PINNED_DENSE_ATTESTATION_SLOT_DESCRIPTORS
        )
    ):
        raise ValueError("loaded_dense_attestation_descriptor_override")


@dataclass(frozen=True, slots=True)
class _LoadedDenseSnapshot:
    lane_state: dict
    store: EvidenceStore
    rows: tuple
    vectors: np.ndarray
    provider: object
    provider_state: dict
    provider_counter: object | None
    provider_counter_state: dict | None
    query_provider: object | None
    query_provider_state: dict | None
    query_counter: object | None
    query_counter_state: dict | None
    identity: object
    artifact_sha256: str
    issued_attestation_payload_sha256: str


@dataclass(slots=True)
class _LoadedDenseRuntime:
    source_provider: KureEmbeddingProvider
    source_runtime: tuple[object | None, object | None]
    query_provider: KureEmbeddingProvider
    query_runtime: tuple[object | None, object | None]


@dataclass(frozen=True, slots=True)
class _BuiltDenseRuntime:
    runtime: tuple[object, object]
    target: Path
    bundle_sha256: str
    rows_sha256: str
    vectors_sha256: str


def _validate_dense_attestation_snapshot(
    attestation: LoadedDenseArtifactAttestation,
) -> dict[str, str]:
    _require_pinned_dense_attestation_shape()
    if type(attestation) is not LoadedDenseArtifactAttestation:
        raise ValueError("loaded_dense_artifact_required")
    payload = {}
    for name in _DENSE_ATTESTATION_PAYLOAD_FIELDS:
        value = object.__getattribute__(attestation, name)
        if type(value) is not str:
            raise ValueError("loaded_dense_attestation_payload_drift")
        if name == "execution_kind":
            if value not in {"synthetic", "real_local_model"}:
                raise ValueError("loaded_dense_attestation_payload_drift")
        elif name == "provider_runtime_sha256":
            if value:
                _require_sha256(value, "loaded_dense_attestation_payload_drift")
        else:
            _require_sha256(value, "loaded_dense_attestation_payload_drift")
        payload[name] = value
    claimed = object.__getattribute__(attestation, "attestation_sha256")
    _require_sha256(claimed, "loaded_dense_attestation_payload_drift")
    if claimed != _digest(payload):
        raise ValueError("loaded_dense_attestation_hash_mismatch")
    return payload


def _require_sha256(value: object, code: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(code)
    return value


def _production_provider_runtime_sha256(
    provider, *, expected_runtime: tuple[object | None, object | None] | None = None,
    require_lazy: bool = False,
) -> str:
    """Validate a KURE adapter whose runtime objects came from pinned loaders."""

    state, counter_state = _production_provider_state(provider)
    if state["execution_kind"] != "real_local_model":
        raise ValueError("dense_production_embedding_provider_required")
    if state["_encoder_loader"] is not _sealed_encoder_loader:
        raise ValueError("dense_production_encoder_loader_not_pinned")
    if counter_state["_tokenizer_loader"] is not _sealed_tokenizer_loader:
        raise ValueError("dense_production_tokenizer_loader_not_pinned")
    if (
        counter_state["model"] != state["model"]
        or counter_state["revision"] != state["revision"]
        or counter_state["local_files_only"] is not True
        or counter_state["trust_remote_code"] is not False
        or state["local_files_only"] is not True
        or state["trust_remote_code"] is not False
    ):
        raise ValueError("dense_production_provider_config_mismatch")
    current_runtime = (state["_encoder"], counter_state["_tokenizer"])
    _validate_loaded_runtime_objects(current_runtime)
    if require_lazy and any(value is not None for value in current_runtime):
        raise ValueError("dense_production_provider_requires_fresh_lazy_runtime")
    if expected_runtime is not None and any(
        current is not expected for current, expected in zip(current_runtime, expected_runtime)
    ):
        raise ValueError("dense_production_provider_runtime_object_drift")
    return _digest(
        {
            "embedding_identity": _provider_identity_from_state(state),
            "batch_size": state["batch_size"],
            "device": state["device"],
            "local_files_only": state["local_files_only"],
            "trust_remote_code": state["trust_remote_code"],
            "encoder_loader": "midprojectrag.retrieval.dense._sealed_encoder_loader",
            "tokenizer_loader": "midprojectrag.retrieval.dense._sealed_tokenizer_loader",
        }
    )


def _provider_identity_from_state(state: dict) -> dict:
    identity = {key: state.get(key) for key in KURE_IDENTITY}
    if identity != KURE_IDENTITY:
        raise ValueError("child_embedding_identity_not_pinned_kure")
    return identity


def _provider_identity(provider) -> dict:
    if type(provider) is KureEmbeddingProvider:
        state, _ = _production_provider_state(provider)
        return _provider_identity_from_state(state)
    try:
        state = object.__getattribute__(provider, "__dict__")
    except AttributeError as exc:
        raise ValueError("child_embedding_identity_not_pinned_kure") from exc
    if type(state) is not dict:
        raise ValueError("child_embedding_identity_not_pinned_kure")
    if any(type(key) is not str for key in tuple(state)):
        raise ValueError("child_embedding_identity_not_pinned_kure")
    return _provider_identity_from_state(state)


def _validated_store_rows(store: EvidenceStore) -> tuple:
    if type(store) is not EvidenceStore:
        raise TypeError("evidence_store_required")
    expected_bundle = object.__getattribute__(store, "bundle_sha256")
    if type(expected_bundle) is not str:
        raise ValueError("dense_store_payload_drift")
    try:
        validate_evidence_store_snapshot(store, expected_bundle)
    except ValueError as exc:
        raise ValueError("dense_store_payload_drift") from exc
    rows = store.candidates()
    if type(rows) is not tuple:
        raise ValueError("dense_store_payload_drift")
    return rows


def normalize(vectors, count):
    matrix = np.asarray(vectors, dtype=np.float32)
    if matrix.shape != (count, KURE_DIMENSIONS) or not np.isfinite(matrix).all():
        raise ValueError("invalid_child_vector_matrix")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError("zero_child_vector")
    return matrix / norms


def _row_hash(rows):
    return sha256(json.dumps([e.evidence_id for e in rows], separators=(",", ":")).encode()).hexdigest()


class DenseChildLane:
    def __init__(self, store: EvidenceStore, vectors, provider, *, artifact_sha256=None, _verified=None):
        if _verified is not _VERIFIED_VECTOR_SNAPSHOT:
            raise ValueError("raw_child_vectors_require_verified_artifact")
        identity = _provider_identity(provider)
        rows = _validated_store_rows(store)
        matrix = np.asarray(vectors, dtype=np.float32)
        if matrix.shape != (len(rows), KURE_DIMENSIONS) or not len(rows) or not np.isfinite(matrix).all():
            raise ValueError("invalid_child_vector_matrix")
        if not np.allclose(np.linalg.norm(matrix, axis=1), 1, atol=1e-5):
            raise ValueError("child_vectors_must_be_normalized")
        self.store, self.rows, self.provider = store, rows, provider
        self.vectors = np.frombuffer(matrix.tobytes(), dtype=np.float32).reshape(matrix.shape)
        self.identity = MappingProxyType(identity)
        self.artifact_sha256 = artifact_sha256 or sha256(self.vectors.tobytes()).hexdigest()

    @classmethod
    def _from_verified(cls, store, vectors, provider, *, artifact_sha256):
        # This compatibility constructor validates matrix shape but deliberately
        # does not mint production authority. Only load_dense may do that.
        return cls(store, vectors, provider, artifact_sha256=artifact_sha256,
                   _verified=_VERIFIED_VECTOR_SNAPSHOT)

    @property
    def loaded_artifact_attestation(self) -> LoadedDenseArtifactAttestation | None:
        return _LOADED_DENSE.get(self)

    def search(
        self,
        query: str,
        limit: int,
        *,
        allowed_doc_ids=None,
        _dependency_checker_identity=None,
        _dependency_checker_code_identity=None,
        _dependency_checker_defaults_identity=None,
        _dependency_checker_kwdefaults_identity=None,
        _dependency_checker_globals_identity=None,
    ) -> SearchResult:
        namespace = globals()
        dependency_checker = dict.get(
            namespace, "_require_dense_production_search_dependencies"
        )
        issued_checker = dict.get(
            namespace, "_ISSUED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES"
        )
        pinned_code = dict.get(
            namespace,
            "_PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_CODE",
        )
        if (
            type(dependency_checker) is not FunctionType
            or dependency_checker is not issued_checker
            or id(dependency_checker) != _dependency_checker_identity
            or object.__getattribute__(dependency_checker, "__code__")
            is not pinned_code
            or id(pinned_code) != _dependency_checker_code_identity
            or object.__getattribute__(dependency_checker, "__globals__")
            is not namespace
            or id(namespace) != _dependency_checker_globals_identity
            or id(object.__getattribute__(dependency_checker, "__defaults__"))
            != _dependency_checker_defaults_identity
            or id(object.__getattribute__(dependency_checker, "__kwdefaults__"))
            != _dependency_checker_kwdefaults_identity
        ):
            raise ValueError("dense_production_search_dependency_override")
        dependency_checker(include_traversal=True)
        _ISSUED_REQUIRE_PINNED_DENSE_REGISTRY_AUTHORITY()
        state = _ISSUED_DENSE_LANE_STATE(self)
        runtime = _ISSUED_LOADED_DENSE_RUNTIME.get(self)
        if runtime is not None:
            _ISSUED_REQUIRE_LOADED_DENSE_ARTIFACT(
                self, state["store"], production=True
            )
        elif _ISSUED_LOADED_DENSE.get(self) is not None:
            _ISSUED_REQUIRE_LOADED_DENSE_ARTIFACT(self, state["store"])
        _ISSUED_VALIDATE_SEARCH(query, limit, allowed_doc_ids)
        rows = state["rows"]
        store = state["store"]
        indices = [i for i, e in enumerate(rows) if allowed_doc_ids is None or e.doc_id in allowed_doc_ids]
        trace = {"lane": "dense", "granularity": "child", "bundle_sha256": object.__getattribute__(store, "bundle_sha256"),
                 "artifact_sha256": state["artifact_sha256"], "embedding_identity": dict(state["identity"]),
                 "scoped_rows": len(indices), "requested_k": limit}
        if not indices:
            return _ISSUED_SEARCH_RESULT(
                (), trace | {"empty_scope": True, "encoder_calls": 0}
            )
        if runtime is not None:
            if type(runtime) is not _ISSUED_LOADED_DENSE_RUNTIME_CLASS:
                raise ValueError("loaded_dense_runtime_attestation_missing")
            query_runtime = object.__getattribute__(runtime, "query_runtime")
            query_provider = object.__getattribute__(runtime, "query_provider")
            if all(value is None for value in query_runtime):
                initialized_runtime = _ISSUED_INITIALIZE_PINNED_PROVIDER_RUNTIME(
                    query_provider
                )
                object.__setattr__(
                    runtime,
                    "query_runtime",
                    initialized_runtime,
                )
                try:
                    _ISSUED_REQUIRE_LOADED_DENSE_ARTIFACT(
                        self, store, production=True
                    )
                except Exception as exc:
                    raise RetrievalPostCallContractError(
                        "dense_post_call_contract_error"
                    ) from exc
            _ISSUED_REQUIRE_PINNED_PROVIDER_METHODS()
            try:
                batch = _ISSUED_KURE_EMBED(query_provider, [query])
            except EmbeddingPostCallContractError as exc:
                raise RetrievalPostCallContractError(
                    "dense_post_call_contract_error"
                ) from exc
            except EmbeddingProviderError as exc:
                raise RetrievalProviderError("dense_provider_error") from exc
        else:
            try:
                batch = state["provider"].embed([query])
            except RetrievalPostCallContractError:
                raise
            except RetrievalProviderError:
                raise
            except EmbeddingPostCallContractError as exc:
                raise RetrievalPostCallContractError(
                    "dense_post_call_contract_error"
                ) from exc
            except EmbeddingProviderError as exc:
                raise RetrievalProviderError("dense_provider_error") from exc
        try:
            if runtime is not None:
                _ISSUED_RECORD_LOADED_DENSE_RUNTIME(self)
            query_vector = _ISSUED_NORMALIZE(batch.vectors, 1)[0]
            scores = state["vectors"][indices] @ query_vector
            ranked = sorted(
                zip(indices, scores),
                key=lambda p: (-float(p[1]), rows[p[0]].evidence_id),
            )[:limit]
            return _ISSUED_SEARCH_RESULT(
                tuple(
                    _ISSUED_CANDIDATE(
                        rows[i].evidence_id,
                        rows[i].doc_id,
                        float(score),
                        "dense",
                        rank,
                    )
                    for rank, (i, score) in enumerate(ranked, 1)
                ),
                trace | {"encoder_calls": 1},
            )
        except RetrievalPostCallContractError:
            raise
        except Exception as exc:
            raise RetrievalPostCallContractError(
                "dense_post_call_contract_error"
            ) from exc


_PINNED_DENSE_SEARCH = DenseChildLane.search
_PINNED_DENSE_GETATTRIBUTE = DenseChildLane.__getattribute__
_PINNED_DENSE_HASH = DenseChildLane.__hash__
_PINNED_DENSE_SEARCH_CODE = _PINNED_DENSE_SEARCH.__code__
_DENSE_LANE_STATE_FIELDS = frozenset(
    {"store", "rows", "provider", "vectors", "identity", "artifact_sha256"}
)


def _dense_lane_state(lane: DenseChildLane) -> dict:
    if type(lane) is not DenseChildLane:
        raise ValueError("loaded_dense_artifact_required")
    if (
        type.__getattribute__(DenseChildLane, "__getattribute__")
        is not _PINNED_DENSE_GETATTRIBUTE
        or type.__getattribute__(DenseChildLane, "__hash__")
        is not _PINNED_DENSE_HASH
    ):
        raise ValueError("loaded_dense_search_method_override")
    _require_pinned_function(
        DenseChildLane,
        "search",
        _PINNED_DENSE_SEARCH,
        _PINNED_DENSE_SEARCH_CODE,
        "loaded_dense_search_method_override",
    )
    try:
        state = object.__getattribute__(lane, "__dict__")
    except AttributeError as exc:
        raise ValueError("loaded_dense_snapshot_type_drift") from exc
    if type(state) is not dict:
        raise ValueError("loaded_dense_snapshot_type_drift")
    keys = tuple(state)
    if any(type(key) is not str for key in keys):
        raise ValueError("loaded_dense_snapshot_type_drift")
    if "search" in keys:
        raise ValueError("loaded_dense_search_method_override")
    if (
        len(keys) != len(_DENSE_LANE_STATE_FIELDS)
        or frozenset(keys) != _DENSE_LANE_STATE_FIELDS
    ):
        raise ValueError("loaded_dense_snapshot_type_drift")
    if type(state["rows"]) is not tuple or type(state["vectors"]) is not np.ndarray:
        raise ValueError("loaded_dense_snapshot_type_drift")
    if type(state["identity"]) is not type(KURE_IDENTITY):
        raise ValueError("loaded_dense_snapshot_type_drift")
    _require_sha256(state["artifact_sha256"], "loaded_dense_snapshot_type_drift")
    provider = state["provider"]
    if type(provider) is KureEmbeddingProvider:
        _production_provider_state(provider)
    else:
        try:
            provider_state = object.__getattribute__(provider, "__dict__")
        except AttributeError as exc:
            raise ValueError("child_embedding_identity_not_pinned_kure") from exc
        if type(provider_state) is not dict or any(
            type(key) is not str for key in tuple(provider_state)
        ):
            raise ValueError("child_embedding_identity_not_pinned_kure")
    return state


def build_dense(
    store: EvidenceStore,
    provider,
    *,
    output_dir: Path,
    data_root: Path,
    batch_size: int = 16,
    progress=None,
    _dependency_checker=None,
    _dependency_checker_code=None,
    _dependency_checker_defaults=None,
    _dependency_checker_kwdefaults=None,
    _dependency_checker_globals=None,
) -> dict:
    namespace = globals()
    if (
        _dependency_checker_globals is not namespace
        or _dependency_checker_globals
        is not dict.get(namespace, "_DENSE_PRODUCTION_GLOBALS")
        or _dependency_checker
        is not dict.get(
            namespace, "_ISSUED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES"
        )
        or _dependency_checker
        is not dict.get(
            namespace, "_require_dense_production_search_dependencies"
        )
        or type(_dependency_checker) is not FunctionType
        or object.__getattribute__(_dependency_checker, "__code__")
        is not _dependency_checker_code
        or _dependency_checker_code
        is not dict.get(
            namespace,
            "_PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_CODE",
        )
        or object.__getattribute__(_dependency_checker, "__globals__")
        is not namespace
        or object.__getattribute__(_dependency_checker, "__defaults__")
        is not _dependency_checker_defaults
        or _dependency_checker_defaults
        is not dict.get(
            namespace,
            "_PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_DEFAULTS",
        )
        or object.__getattribute__(_dependency_checker, "__kwdefaults__")
        is not _dependency_checker_kwdefaults
        or _dependency_checker_kwdefaults
        is not dict.get(
            namespace,
            "_PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_KWDEFAULTS",
        )
        or type(_dependency_checker_kwdefaults) is not dict
        or dict.__len__(_dependency_checker_kwdefaults) != 1
        or dict.get(_dependency_checker_kwdefaults, "include_traversal")
        is not False
    ):
        raise ValueError("dense_production_search_dependency_override")
    _dependency_checker(include_traversal=True)
    _ISSUED_REQUIRE_PINNED_DENSE_REGISTRY_AUTHORITY()
    identity = _provider_identity(provider)
    rows = _validated_store_rows(store)
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("invalid_dense_build_config")
    if type(provider) is KureEmbeddingProvider:
        provider_state, _ = _production_provider_state(provider)
        execution_kind = (
            "real_local_model"
            if provider_state["execution_kind"] == "real_local_model"
            else "synthetic"
        )
    else:
        execution_kind = "synthetic"
    if execution_kind == "real_local_model":
        _seal_provider_loaders(provider)
        _production_provider_runtime_sha256(provider, require_lazy=True)
        _initialize_pinned_provider_runtime(provider)
    target = private_path(output_dir, data_root)
    if target.exists():
        raise FileExistsError(target)
    if not rows:
        raise ValueError("empty_child_store")
    batches = []
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i+batch_size]
        if execution_kind == "real_local_model":
            _require_pinned_provider_methods()
        embedded = (
            _ISSUED_KURE_EMBED(provider, [e.text for e in batch])
            if execution_kind == "real_local_model"
            else provider.embed([e.text for e in batch])
        )
        batches.append(normalize(embedded.vectors, len(batch)))
        if progress is not None:
            progress(i+len(batch), len(rows))
    matrix = np.concatenate(batches)
    runtime = None
    if execution_kind == "real_local_model":
        provider_state, counter_state = _production_provider_state(provider)
        runtime = (provider_state["_encoder"], counter_state["_tokenizer"])
        if any(value is None for value in runtime):
            raise ValueError("dense_production_runtime_initialization_incomplete")
        _production_provider_runtime_sha256(provider, expected_runtime=runtime)
    if _provider_identity(provider) != identity:
        raise ValueError("child_embedding_identity_not_pinned_kure")
    current_rows = _validated_store_rows(store)
    if len(current_rows) != len(rows) or any(
        current is not issued for current, issued in zip(current_rows, rows)
    ):
        raise ValueError("dense_store_payload_drift")
    target.mkdir(parents=True, exist_ok=False, mode=0o700)
    descriptor = os.open(target / "vectors.npy", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        np.save(output, matrix, allow_pickle=False)
    bundle_sha256 = object.__getattribute__(store, "bundle_sha256")
    receipt = {"schema_version": "1.0", "granularity": "child", "bundle_sha256": bundle_sha256,
               "embedding_identity": identity, "rows_sha256": _row_hash(rows), "count": len(rows),
               "vectors_sha256": file_sha(target / "vectors.npy"), "execution_kind": execution_kind}
    write_new_json(target / "receipt.json", receipt)
    if runtime is not None:
        _BUILT_DENSE_RUNTIME[provider] = _BuiltDenseRuntime(
            runtime=runtime,
            target=target,
            bundle_sha256=bundle_sha256,
            rows_sha256=receipt["rows_sha256"],
            vectors_sha256=receipt["vectors_sha256"],
        )
    return receipt


def load_dense(
    store: EvidenceStore,
    provider,
    *,
    output_dir: Path,
    data_root: Path,
    _dependency_checker=None,
    _dependency_checker_code=None,
    _dependency_checker_defaults=None,
    _dependency_checker_kwdefaults=None,
    _dependency_checker_globals=None,
) -> DenseChildLane:
    namespace = globals()
    if (
        _dependency_checker_globals is not namespace
        or _dependency_checker_globals
        is not dict.get(namespace, "_DENSE_PRODUCTION_GLOBALS")
        or _dependency_checker
        is not dict.get(
            namespace, "_ISSUED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES"
        )
        or _dependency_checker
        is not dict.get(
            namespace, "_require_dense_production_search_dependencies"
        )
        or type(_dependency_checker) is not FunctionType
        or object.__getattribute__(_dependency_checker, "__code__")
        is not _dependency_checker_code
        or _dependency_checker_code
        is not dict.get(
            namespace,
            "_PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_CODE",
        )
        or object.__getattribute__(_dependency_checker, "__globals__")
        is not namespace
        or object.__getattribute__(_dependency_checker, "__defaults__")
        is not _dependency_checker_defaults
        or _dependency_checker_defaults
        is not dict.get(
            namespace,
            "_PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_DEFAULTS",
        )
        or object.__getattribute__(_dependency_checker, "__kwdefaults__")
        is not _dependency_checker_kwdefaults
        or _dependency_checker_kwdefaults
        is not dict.get(
            namespace,
            "_PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_KWDEFAULTS",
        )
        or type(_dependency_checker_kwdefaults) is not dict
        or dict.__len__(_dependency_checker_kwdefaults) != 1
        or dict.get(_dependency_checker_kwdefaults, "include_traversal")
        is not False
    ):
        raise ValueError("dense_production_search_dependency_override")
    _dependency_checker(include_traversal=True)
    _ISSUED_REQUIRE_PINNED_DENSE_REGISTRY_AUTHORITY()
    identity = _provider_identity(provider)
    rows = _validated_store_rows(store)
    bundle_sha256 = object.__getattribute__(store, "bundle_sha256")
    target = private_path(output_dir, data_root)
    if any(not (target / name).resolve().is_relative_to(target) for name in ("receipt.json", "vectors.npy")):
        raise ValueError("dense_artifact_symlink_escape")
    receipt = json.loads((target / "receipt.json").read_text())
    expected = {"schema_version": "1.0", "granularity": "child", "bundle_sha256": bundle_sha256,
                "embedding_identity": identity, "rows_sha256": _row_hash(rows),
                "count": len(rows), "vectors_sha256": file_sha(target / "vectors.npy")}
    if type(receipt) is not dict or set(receipt) != set(expected) | {"execution_kind"} or any(
        receipt.get(k) != v for k, v in expected.items()
    ) or receipt["execution_kind"] not in {"synthetic", "real_local_model"}:
        raise ValueError("dense_artifact_identity_mismatch")
    vectors = np.load(target / "vectors.npy", allow_pickle=False)
    lane = DenseChildLane._from_verified(
        store, vectors, provider, artifact_sha256=file_sha(target / "receipt.json")
    )
    source_runtime = None
    provider_runtime = ""
    if receipt["execution_kind"] == "real_local_model":
        _seal_provider_loaders(provider)
        provider_state, counter_state = _production_provider_state(provider)
        current_runtime = (provider_state["_encoder"], counter_state["_tokenizer"])
        if all(value is None for value in current_runtime):
            provider_runtime = _production_provider_runtime_sha256(
                provider, require_lazy=True
            )
            source_runtime = current_runtime
        else:
            built = _BUILT_DENSE_RUNTIME.get(provider)
            if (
                type(built) is not _BuiltDenseRuntime
                or object.__getattribute__(built, "target") != target
                or object.__getattribute__(built, "bundle_sha256") != bundle_sha256
                or object.__getattribute__(built, "rows_sha256") != receipt["rows_sha256"]
                or object.__getattribute__(built, "vectors_sha256") != receipt["vectors_sha256"]
                or any(
                    current is not expected
                    for current, expected in zip(
                        current_runtime, object.__getattribute__(built, "runtime")
                    )
                )
            ):
                raise ValueError("dense_loaded_runtime_lacks_build_attestation")
            _production_provider_runtime_sha256(
                provider, expected_runtime=current_runtime
            )
            # The build runtime is exposed through the caller's provider. Drop
            # its heavyweight caches after verification so the sealed query
            # provider does not coexist with a second KURE model in memory.
            _BUILT_DENSE_RUNTIME.pop(provider, None)
            provider_state["_encoder"] = None
            counter_state["_tokenizer"] = None
            source_runtime = (None, None)
            provider_runtime = _production_provider_runtime_sha256(
                provider, require_lazy=True
            )
        _require_pinned_provider_methods()
        query_provider = KureEmbeddingProvider(
            batch_size=provider_state["batch_size"], device=provider_state["device"]
        )
        _seal_provider_loaders(query_provider)
        query_runtime_sha = _production_provider_runtime_sha256(
            query_provider, require_lazy=True
        )
        if query_runtime_sha != provider_runtime:
            raise ValueError("dense_sealed_query_provider_config_mismatch")
    payload = {
        "bundle_sha256": bundle_sha256,
        "rows_sha256": _row_hash(rows),
        "receipt_sha256": object.__getattribute__(lane, "artifact_sha256"),
        "vectors_file_sha256": receipt["vectors_sha256"],
        "vectors_content_sha256": _matrix_hash(object.__getattribute__(lane, "vectors")),
        "embedding_identity_sha256": _digest(identity),
        "execution_kind": receipt["execution_kind"],
        "provider_runtime_sha256": provider_runtime,
    }
    _require_pinned_dense_attestation_shape()
    attestation = LoadedDenseArtifactAttestation(
        payload, _token=_LOADED_DENSE_ATTESTATION
    )
    _LOADED_DENSE[lane] = attestation
    lane_state = _dense_lane_state(lane)
    if type(provider) is KureEmbeddingProvider:
        issued_provider_state, issued_counter_state = _production_provider_state(
            provider
        )
        issued_provider_counter = issued_provider_state["_counter"]
    else:
        issued_provider_state = object.__getattribute__(provider, "__dict__")
        issued_provider_counter = None
        issued_counter_state = None
    if receipt["execution_kind"] == "real_local_model":
        issued_query_state, issued_query_counter_state = _production_provider_state(
            query_provider
        )
        issued_query_counter = issued_query_state["_counter"]
    else:
        query_provider = None
        issued_query_state = None
        issued_query_counter = None
        issued_query_counter_state = None
    _LOADED_DENSE_SNAPSHOT[lane] = _LoadedDenseSnapshot(
        lane_state=lane_state,
        store=lane_state["store"],
        rows=lane_state["rows"],
        vectors=lane_state["vectors"],
        provider=lane_state["provider"],
        provider_state=issued_provider_state,
        provider_counter=issued_provider_counter,
        provider_counter_state=issued_counter_state,
        query_provider=query_provider,
        query_provider_state=issued_query_state,
        query_counter=issued_query_counter,
        query_counter_state=issued_query_counter_state,
        identity=lane_state["identity"],
        artifact_sha256=lane_state["artifact_sha256"],
        issued_attestation_payload_sha256=_digest(
            {
                **payload,
                "attestation_sha256": object.__getattribute__(
                    attestation, "attestation_sha256"
                ),
            }
        ),
    )
    if receipt["execution_kind"] == "real_local_model":
        _LOADED_DENSE_RUNTIME[lane] = _LoadedDenseRuntime(
            source_provider=provider,
            source_runtime=source_runtime,
            query_provider=query_provider,
            query_runtime=(None, None),
        )
    return lane


def _record_loaded_dense_runtime(lane: DenseChildLane) -> None:
    """Advance lazy runtime state only after the pinned class method loaded it."""

    runtime = _LOADED_DENSE_RUNTIME.get(lane)
    if type(runtime) is not _LoadedDenseRuntime:
        raise ValueError("loaded_dense_runtime_attestation_missing")
    provider = object.__getattribute__(runtime, "query_provider")
    provider_state, counter_state = _production_provider_state(provider)
    current = (provider_state["_encoder"], counter_state["_tokenizer"])
    if any(value is None for value in current):
        raise ValueError("loaded_dense_runtime_initialization_incomplete")
    object.__setattr__(runtime, "query_runtime", current)
    _production_provider_runtime_sha256(provider, expected_runtime=current)


def _preflight_loaded_dense_context(
    lane: DenseChildLane,
    store: EvidenceStore,
    *,
    production: bool,
    _dependency_checker=None,
    _dependency_checker_code=None,
    _dependency_checker_defaults=None,
    _dependency_checker_kwdefaults=None,
    _dependency_checker_globals=None,
) -> tuple[
    dict,
    LoadedDenseArtifactAttestation,
    _LoadedDenseSnapshot,
    dict[str, str],
    _LoadedDenseRuntime | None,
]:
    """Validate live identities without traversing the store or vector matrix."""

    namespace = globals()
    if (
        _dependency_checker_globals is not namespace
        or _dependency_checker_globals
        is not dict.get(namespace, "_DENSE_PRODUCTION_GLOBALS")
        or _dependency_checker
        is not dict.get(
            namespace, "_ISSUED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES"
        )
        or _dependency_checker
        is not dict.get(
            namespace, "_require_dense_production_search_dependencies"
        )
        or type(_dependency_checker) is not FunctionType
        or object.__getattribute__(_dependency_checker, "__code__")
        is not _dependency_checker_code
        or _dependency_checker_code
        is not dict.get(
            namespace,
            "_PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_CODE",
        )
        or object.__getattribute__(_dependency_checker, "__globals__")
        is not namespace
        or object.__getattribute__(_dependency_checker, "__defaults__")
        is not _dependency_checker_defaults
        or _dependency_checker_defaults
        is not dict.get(
            namespace,
            "_PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_DEFAULTS",
        )
        or object.__getattribute__(_dependency_checker, "__kwdefaults__")
        is not _dependency_checker_kwdefaults
        or _dependency_checker_kwdefaults
        is not dict.get(
            namespace,
            "_PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_KWDEFAULTS",
        )
        or type(_dependency_checker_kwdefaults) is not dict
        or dict.__len__(_dependency_checker_kwdefaults) != 1
        or dict.get(_dependency_checker_kwdefaults, "include_traversal")
        is not False
    ):
        raise ValueError("dense_production_search_dependency_override")
    _dependency_checker()
    if type(production) is not bool:
        raise ValueError("invalid_dense_production_flag")
    if type(lane) is not DenseChildLane or type(store) is not EvidenceStore:
        raise ValueError("loaded_dense_artifact_required")
    # Registry implementation, storage descriptor, and exact backing dicts are
    # authenticated before either a registry lookup or lane/provider traversal.
    _ISSUED_REQUIRE_PINNED_DENSE_REGISTRY_AUTHORITY()
    _require_pinned_dense_attestation_shape()

    # This exact-class/method/container check deliberately precedes every
    # identity-registry lookup. In particular, a hostile replacement
    # ``__hash__`` is rejected by identity and is never invoked.
    current = _ISSUED_DENSE_LANE_STATE(lane)
    if current["store"] is not store:
        raise ValueError("loaded_dense_store_or_rows_mismatch")

    attestation = _ISSUED_LOADED_DENSE.get(lane)
    snapshot = _ISSUED_LOADED_DENSE_SNAPSHOT.get(lane)
    if (
        type(attestation) is not LoadedDenseArtifactAttestation
        or type(snapshot) is not _LoadedDenseSnapshot
    ):
        raise ValueError("loaded_dense_artifact_required")
    if object.__getattribute__(snapshot, "lane_state") is not object.__getattribute__(
        lane, "__dict__"
    ):
        raise ValueError("loaded_dense_snapshot_identity_drift")
    if any(
        issued is not current[name]
        for name, issued in (
            ("store", object.__getattribute__(snapshot, "store")),
            ("rows", object.__getattribute__(snapshot, "rows")),
            ("vectors", object.__getattribute__(snapshot, "vectors")),
            ("provider", object.__getattribute__(snapshot, "provider")),
            ("identity", object.__getattribute__(snapshot, "identity")),
            (
                "artifact_sha256",
                object.__getattribute__(snapshot, "artifact_sha256"),
            ),
        )
    ):
        raise ValueError("loaded_dense_snapshot_identity_drift")

    provider = current["provider"]
    provider_state = object.__getattribute__(provider, "__dict__")
    if provider_state is not object.__getattribute__(snapshot, "provider_state"):
        raise ValueError("loaded_dense_snapshot_identity_drift")
    if type(provider) is KureEmbeddingProvider:
        provider_state, counter_state = _production_provider_state(provider)
        counter = provider_state["_counter"]
        if (
            counter is not object.__getattribute__(snapshot, "provider_counter")
            or counter_state
            is not object.__getattribute__(snapshot, "provider_counter_state")
        ):
            raise ValueError("loaded_dense_snapshot_identity_drift")
    elif any(
        object.__getattribute__(snapshot, name) is not None
        for name in ("provider_counter", "provider_counter_state")
    ):
        raise ValueError("loaded_dense_snapshot_identity_drift")

    attestation_payload = _validate_dense_attestation_snapshot(attestation)
    issued_payload_sha256 = _digest(
        {
            **attestation_payload,
            "attestation_sha256": object.__getattribute__(
                attestation, "attestation_sha256"
            ),
        }
    )
    if issued_payload_sha256 != object.__getattribute__(
        snapshot, "issued_attestation_payload_sha256"
    ):
        raise ValueError("loaded_dense_attestation_issued_payload_drift")
    if (
        attestation_payload["receipt_sha256"] != current["artifact_sha256"]
        or attestation_payload["embedding_identity_sha256"]
        != _digest(_provider_identity(provider))
    ):
        raise ValueError("loaded_dense_runtime_drift")

    runtime = _ISSUED_LOADED_DENSE_RUNTIME.get(lane)
    if attestation_payload["execution_kind"] == "real_local_model":
        if type(runtime) is not _LoadedDenseRuntime:
            raise ValueError("loaded_dense_runtime_attestation_missing")
        source_provider = object.__getattribute__(runtime, "source_provider")
        query_provider = object.__getattribute__(runtime, "query_provider")
        source_runtime = object.__getattribute__(runtime, "source_runtime")
        query_runtime = object.__getattribute__(runtime, "query_runtime")
        if (
            source_provider is not provider
            or query_provider
            is not object.__getattribute__(snapshot, "query_provider")
            or type(source_runtime) is not tuple
            or len(source_runtime) != 2
            or type(query_runtime) is not tuple
            or len(query_runtime) != 2
        ):
            raise ValueError("loaded_dense_runtime_attestation_missing")
        query_state, query_counter_state = _production_provider_state(
            query_provider
        )
        if (
            query_state
            is not object.__getattribute__(snapshot, "query_provider_state")
            or query_state["_counter"]
            is not object.__getattribute__(snapshot, "query_counter")
            or query_counter_state
            is not object.__getattribute__(snapshot, "query_counter_state")
        ):
            raise ValueError("loaded_dense_snapshot_identity_drift")
        source_sha = _production_provider_runtime_sha256(
            source_provider, expected_runtime=source_runtime
        )
        query_sha = _production_provider_runtime_sha256(
            query_provider, expected_runtime=query_runtime
        )
        if (
            not attestation_payload["provider_runtime_sha256"]
            or source_sha != attestation_payload["provider_runtime_sha256"]
            or query_sha != attestation_payload["provider_runtime_sha256"]
        ):
            raise ValueError("loaded_dense_provider_runtime_drift")
    else:
        if runtime is not None or any(
            object.__getattribute__(snapshot, name) is not None
            for name in (
                "query_provider",
                "query_provider_state",
                "query_counter",
                "query_counter_state",
            )
        ):
            raise ValueError("loaded_dense_runtime_attestation_missing")
        if production:
            raise ValueError("loaded_dense_production_execution_required")
    return current, attestation, snapshot, attestation_payload, runtime


def preflight_loaded_dense_artifact(
    lane: DenseChildLane,
    store: EvidenceStore,
    *,
    production: bool = False,
    _dependency_checker=None,
    _dependency_checker_code=None,
    _dependency_checker_defaults=None,
    _dependency_checker_kwdefaults=None,
    _dependency_checker_globals=None,
) -> LoadedDenseArtifactAttestation:
    """Check dense execution authority with zero store/vector traversal or model calls."""

    namespace = globals()
    if (
        _dependency_checker_globals is not namespace
        or _dependency_checker_globals
        is not dict.get(namespace, "_DENSE_PRODUCTION_GLOBALS")
        or _dependency_checker
        is not dict.get(
            namespace, "_ISSUED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES"
        )
        or _dependency_checker
        is not dict.get(
            namespace, "_require_dense_production_search_dependencies"
        )
        or type(_dependency_checker) is not FunctionType
        or object.__getattribute__(_dependency_checker, "__code__")
        is not _dependency_checker_code
        or _dependency_checker_code
        is not dict.get(
            namespace,
            "_PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_CODE",
        )
        or object.__getattribute__(_dependency_checker, "__globals__")
        is not namespace
        or object.__getattribute__(_dependency_checker, "__defaults__")
        is not _dependency_checker_defaults
        or _dependency_checker_defaults
        is not dict.get(
            namespace,
            "_PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_DEFAULTS",
        )
        or object.__getattribute__(_dependency_checker, "__kwdefaults__")
        is not _dependency_checker_kwdefaults
        or _dependency_checker_kwdefaults
        is not dict.get(
            namespace,
            "_PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_KWDEFAULTS",
        )
        or type(_dependency_checker_kwdefaults) is not dict
        or dict.__len__(_dependency_checker_kwdefaults) != 1
        or dict.get(_dependency_checker_kwdefaults, "include_traversal")
        is not False
    ):
        raise ValueError("dense_production_search_dependency_override")
    _dependency_checker()
    _ISSUED_REQUIRE_PINNED_DENSE_REGISTRY_AUTHORITY()
    _, attestation, _, _, _ = _ISSUED_PREFLIGHT_LOADED_DENSE_CONTEXT(
        lane,
        store,
        production=production,
    )
    return attestation


def require_loaded_dense_artifact(
    lane: DenseChildLane,
    store: EvidenceStore,
    *,
    production: bool = False,
    _dependency_checker=None,
    _dependency_checker_code=None,
    _dependency_checker_defaults=None,
    _dependency_checker_kwdefaults=None,
    _dependency_checker_globals=None,
) -> LoadedDenseArtifactAttestation:
    """Return a loader-issued proof after revalidating all mutable runtime state."""

    namespace = globals()
    if (
        _dependency_checker_globals is not namespace
        or _dependency_checker_globals
        is not dict.get(namespace, "_DENSE_PRODUCTION_GLOBALS")
        or _dependency_checker
        is not dict.get(
            namespace, "_ISSUED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES"
        )
        or _dependency_checker
        is not dict.get(
            namespace, "_require_dense_production_search_dependencies"
        )
        or type(_dependency_checker) is not FunctionType
        or object.__getattribute__(_dependency_checker, "__code__")
        is not _dependency_checker_code
        or _dependency_checker_code
        is not dict.get(
            namespace,
            "_PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_CODE",
        )
        or object.__getattribute__(_dependency_checker, "__globals__")
        is not namespace
        or object.__getattribute__(_dependency_checker, "__defaults__")
        is not _dependency_checker_defaults
        or _dependency_checker_defaults
        is not dict.get(
            namespace,
            "_PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_DEFAULTS",
        )
        or object.__getattribute__(_dependency_checker, "__kwdefaults__")
        is not _dependency_checker_kwdefaults
        or _dependency_checker_kwdefaults
        is not dict.get(
            namespace,
            "_PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_KWDEFAULTS",
        )
        or type(_dependency_checker_kwdefaults) is not dict
        or dict.__len__(_dependency_checker_kwdefaults) != 1
        or dict.get(_dependency_checker_kwdefaults, "include_traversal")
        is not False
    ):
        raise ValueError("dense_production_search_dependency_override")
    _dependency_checker(include_traversal=True)
    _ISSUED_REQUIRE_PINNED_DENSE_REGISTRY_AUTHORITY()
    _ISSUED_PREFLIGHT_LOADED_DENSE_ARTIFACT(
        lane, store, production=production
    )
    current, attestation, _, attestation_payload, runtime = (
        _ISSUED_PREFLIGHT_LOADED_DENSE_CONTEXT(
            lane, store, production=production
        )
    )
    try:
        rows = _ISSUED_VALIDATED_STORE_ROWS(store)
    except (TypeError, ValueError) as exc:
        raise ValueError("loaded_dense_store_payload_drift") from exc
    if (
        len(current["rows"]) != len(rows)
        or any(issued is not actual for issued, actual in zip(current["rows"], rows))
    ):
        raise ValueError("loaded_dense_store_or_rows_mismatch")
    checks = {
        "bundle_sha256": object.__getattribute__(store, "bundle_sha256"),
        "rows_sha256": _ISSUED_ROW_HASH(rows),
        "receipt_sha256": current["artifact_sha256"],
        "vectors_content_sha256": _ISSUED_MATRIX_HASH(current["vectors"]),
        "embedding_identity_sha256": _ISSUED_DIGEST(
            _ISSUED_PROVIDER_IDENTITY(current["provider"])
        ),
    }
    if any(attestation_payload[name] != value for name, value in checks.items()):
        raise ValueError("loaded_dense_runtime_drift")
    if production:
        if type(runtime) is not _LoadedDenseRuntime:
            raise ValueError("loaded_dense_runtime_attestation_missing")
        source_provider = object.__getattribute__(runtime, "source_provider")
        query_provider = object.__getattribute__(runtime, "query_provider")
        source_runtime = object.__getattribute__(runtime, "source_runtime")
        query_runtime = object.__getattribute__(runtime, "query_runtime")
        source_sha = _production_provider_runtime_sha256(
            source_provider, expected_runtime=source_runtime
        )
        query_sha = _production_provider_runtime_sha256(
            query_provider, expected_runtime=query_runtime
        )
        if (
            not attestation_payload["provider_runtime_sha256"]
            or source_sha != attestation_payload["provider_runtime_sha256"]
            or query_sha != attestation_payload["provider_runtime_sha256"]
        ):
            raise ValueError("loaded_dense_provider_runtime_drift")
    return attestation


# Production search dispatch is deliberately routed through these import-time
# handles.  The public aliases remain part of the checked surface: replacing a
# helper after a harness was bound fails before a store, provider, or query is
# touched instead of silently changing the executed retrieval program.
_ISSUED_NORMALIZE = normalize
_ISSUED_VALIDATE_SEARCH = validate_search
_ISSUED_CANDIDATE = Candidate
_ISSUED_SEARCH_RESULT = SearchResult
_ISSUED_DENSE_LANE_STATE = _dense_lane_state
_ISSUED_REQUIRE_LOADED_DENSE_ARTIFACT = require_loaded_dense_artifact
_ISSUED_PREFLIGHT_LOADED_DENSE_ARTIFACT = preflight_loaded_dense_artifact
_ISSUED_PREFLIGHT_LOADED_DENSE_CONTEXT = _preflight_loaded_dense_context
_ISSUED_VALIDATED_STORE_ROWS = _validated_store_rows
_ISSUED_ROW_HASH = _row_hash
_ISSUED_MATRIX_HASH = _matrix_hash
_ISSUED_DIGEST = _digest
_ISSUED_PROVIDER_IDENTITY = _provider_identity
_ISSUED_INITIALIZE_PINNED_PROVIDER_RUNTIME = _initialize_pinned_provider_runtime
_ISSUED_RECORD_LOADED_DENSE_RUNTIME = _record_loaded_dense_runtime
_ISSUED_REQUIRE_PINNED_PROVIDER_METHODS = _require_pinned_provider_methods
_ISSUED_LOADED_DENSE = _LOADED_DENSE
_ISSUED_LOADED_DENSE_RUNTIME = _LOADED_DENSE_RUNTIME
_ISSUED_LOADED_DENSE_SNAPSHOT = _LOADED_DENSE_SNAPSHOT
_ISSUED_LOADED_DENSE_RUNTIME_CLASS = _LoadedDenseRuntime

_DENSE_PRODUCTION_FUNCTION_AUTHORITY = tuple(
    (name, function, object.__getattribute__(function, "__code__"))
    for name, function in (
        ("validate_search", validate_search),
        ("_require_pinned_function", _require_pinned_function),
        ("_require_pinned_provider_methods", _require_pinned_provider_methods),
        ("_exact_instance_state", _exact_instance_state),
        ("_production_provider_state", _production_provider_state),
        ("_sealed_tokenizer_loader", _sealed_tokenizer_loader),
        ("_sealed_encoder_loader", _sealed_encoder_loader),
        ("_validate_loaded_runtime_objects", _validate_loaded_runtime_objects),
        ("_initialize_pinned_provider_runtime", _initialize_pinned_provider_runtime),
        ("_digest", _digest),
        ("_require_pinned_dense_attestation_shape", _require_pinned_dense_attestation_shape),
        ("_validate_dense_attestation_snapshot", _validate_dense_attestation_snapshot),
        ("_require_sha256", _require_sha256),
        ("_production_provider_runtime_sha256", _production_provider_runtime_sha256),
        ("_provider_identity_from_state", _provider_identity_from_state),
        ("_provider_identity", _provider_identity),
        ("normalize", normalize),
        ("_dense_lane_state", _dense_lane_state),
        ("build_dense", build_dense),
        ("load_dense", load_dense),
        ("_record_loaded_dense_runtime", _record_loaded_dense_runtime),
        ("_preflight_loaded_dense_context", _preflight_loaded_dense_context),
        ("preflight_loaded_dense_artifact", preflight_loaded_dense_artifact),
        ("require_loaded_dense_artifact", require_loaded_dense_artifact),
    )
)
_DENSE_PRODUCTION_TRAVERSAL_FUNCTION_AUTHORITY = tuple(
    (name, function, object.__getattribute__(function, "__code__"))
    for name, function in (
        ("validate_evidence_store_snapshot", validate_evidence_store_snapshot),
        ("_validated_store_rows", _validated_store_rows),
        ("_matrix_hash", _matrix_hash),
        ("_row_hash", _row_hash),
    )
)
_DENSE_PRODUCTION_OBJECT_AUTHORITY = (
    ("np", np),
    ("json", json),
    ("sha256", sha256),
    ("CodeType", CodeType),
    ("FunctionType", FunctionType),
    ("MemberDescriptorType", MemberDescriptorType),
    ("ReferenceType", ReferenceType),
    ("ref", ref),
    ("EvidenceStore", EvidenceStore),
    ("KureEmbeddingProvider", KureEmbeddingProvider),
    ("HuggingFaceTokenCounter", HuggingFaceTokenCounter),
    ("EmbeddingProviderError", EmbeddingProviderError),
    ("EmbeddingPostCallContractError", EmbeddingPostCallContractError),
    ("Candidate", Candidate),
    ("SearchResult", SearchResult),
    ("RetrievalProviderError", RetrievalProviderError),
    ("RetrievalPostCallContractError", RetrievalPostCallContractError),
    ("LoadedDenseArtifactAttestation", LoadedDenseArtifactAttestation),
    ("_LoadedDenseSnapshot", _LoadedDenseSnapshot),
    ("_LoadedDenseRuntime", _LoadedDenseRuntime),
    ("_IdentityWeakRegistry", _IdentityWeakRegistry),
    ("KURE_IDENTITY", KURE_IDENTITY),
    ("KURE_DIMENSIONS", KURE_DIMENSIONS),
    ("_KURE_STATE_FIELDS", _KURE_STATE_FIELDS),
    ("_COUNTER_STATE_FIELDS", _COUNTER_STATE_FIELDS),
    ("_DENSE_ATTESTATION_PAYLOAD_FIELDS", _DENSE_ATTESTATION_PAYLOAD_FIELDS),
    ("_DENSE_ATTESTATION_FIELDS", _DENSE_ATTESTATION_FIELDS),
    ("_DENSE_LANE_STATE_FIELDS", _DENSE_LANE_STATE_FIELDS),
    ("_PINNED_DENSE_ATTESTATION_GETATTRIBUTE", _PINNED_DENSE_ATTESTATION_GETATTRIBUTE),
    ("_PINNED_DENSE_ATTESTATION_SLOT_DESCRIPTORS", _PINNED_DENSE_ATTESTATION_SLOT_DESCRIPTORS),
    ("_PINNED_DENSE_SEARCH", _PINNED_DENSE_SEARCH),
    ("_PINNED_DENSE_GETATTRIBUTE", _PINNED_DENSE_GETATTRIBUTE),
    ("_PINNED_DENSE_HASH", _PINNED_DENSE_HASH),
    ("_PINNED_DENSE_SEARCH_CODE", _PINNED_DENSE_SEARCH_CODE),
    ("_LOADED_DENSE", _LOADED_DENSE),
    ("_LOADED_DENSE_RUNTIME", _LOADED_DENSE_RUNTIME),
    ("_LOADED_DENSE_SNAPSHOT", _LOADED_DENSE_SNAPSHOT),
    ("_BUILT_DENSE_RUNTIME", _BUILT_DENSE_RUNTIME),
    ("_ISSUED_NORMALIZE", _ISSUED_NORMALIZE),
    ("_ISSUED_VALIDATE_SEARCH", _ISSUED_VALIDATE_SEARCH),
    ("_ISSUED_CANDIDATE", _ISSUED_CANDIDATE),
    ("_ISSUED_SEARCH_RESULT", _ISSUED_SEARCH_RESULT),
    ("_ISSUED_DENSE_LANE_STATE", _ISSUED_DENSE_LANE_STATE),
    ("_ISSUED_REQUIRE_LOADED_DENSE_ARTIFACT", _ISSUED_REQUIRE_LOADED_DENSE_ARTIFACT),
    ("_ISSUED_PREFLIGHT_LOADED_DENSE_ARTIFACT", _ISSUED_PREFLIGHT_LOADED_DENSE_ARTIFACT),
    ("_ISSUED_PREFLIGHT_LOADED_DENSE_CONTEXT", _ISSUED_PREFLIGHT_LOADED_DENSE_CONTEXT),
    ("_ISSUED_VALIDATED_STORE_ROWS", _ISSUED_VALIDATED_STORE_ROWS),
    ("_ISSUED_ROW_HASH", _ISSUED_ROW_HASH),
    ("_ISSUED_MATRIX_HASH", _ISSUED_MATRIX_HASH),
    ("_ISSUED_DIGEST", _ISSUED_DIGEST),
    ("_ISSUED_PROVIDER_IDENTITY", _ISSUED_PROVIDER_IDENTITY),
    ("_ISSUED_INITIALIZE_PINNED_PROVIDER_RUNTIME", _ISSUED_INITIALIZE_PINNED_PROVIDER_RUNTIME),
    ("_ISSUED_RECORD_LOADED_DENSE_RUNTIME", _ISSUED_RECORD_LOADED_DENSE_RUNTIME),
    ("_ISSUED_REQUIRE_PINNED_PROVIDER_METHODS", _ISSUED_REQUIRE_PINNED_PROVIDER_METHODS),
    ("_ISSUED_LOADED_DENSE", _ISSUED_LOADED_DENSE),
    ("_ISSUED_LOADED_DENSE_RUNTIME", _ISSUED_LOADED_DENSE_RUNTIME),
    ("_ISSUED_LOADED_DENSE_SNAPSHOT", _ISSUED_LOADED_DENSE_SNAPSHOT),
    ("_ISSUED_LOADED_DENSE_RUNTIME_CLASS", _ISSUED_LOADED_DENSE_RUNTIME_CLASS),
)
_DENSE_PRODUCTION_NUMPY_AUTHORITY = (
    np,
    (
        ("asarray", np.asarray),
        ("float32", np.float32),
        ("isfinite", np.isfinite),
        ("any", np.any),
        ("ndarray", np.ndarray),
    ),
    np.linalg,
    (("norm", np.linalg.norm),),
)
_DENSE_PRODUCTION_REGISTRY_METHOD_AUTHORITY = (
    _IdentityWeakRegistry,
    type.__getattribute__(_IdentityWeakRegistry, "__getattribute__"),
    type.__getattribute__(_IdentityWeakRegistry, "__setattr__"),
    type.__getattribute__(_IdentityWeakRegistry, "__dict__")["_entries"],
    tuple(
        (name, method, object.__getattribute__(method, "__code__"))
        for name, method in (
            ("__init__", _IdentityWeakRegistry.__init__),
            ("_drop", _IdentityWeakRegistry._drop),
            ("__setitem__", _IdentityWeakRegistry.__setitem__),
            ("get", _IdentityWeakRegistry.get),
            ("pop", _IdentityWeakRegistry.pop),
            ("__contains__", _IdentityWeakRegistry.__contains__),
            ("__getitem__", _IdentityWeakRegistry.__getitem__),
        )
    ),
)
_DENSE_PRODUCTION_REGISTRY_INSTANCE_AUTHORITY = tuple(
    (registry, object.__getattribute__(registry, "_entries"))
    for registry in (
        _LOADED_DENSE,
        _LOADED_DENSE_RUNTIME,
        _LOADED_DENSE_SNAPSHOT,
        _BUILT_DENSE_RUNTIME,
    )
)
_DENSE_PRODUCTION_CONTRACT_METHOD_AUTHORITY = tuple(
    (
        owner,
        name,
        method,
        object.__getattribute__(method, "__code__"),
    )
    for owner, name, method in (
        (Candidate, "__init__", Candidate.__init__),
        (Candidate, "__post_init__", Candidate.__post_init__),
        (SearchResult, "__init__", SearchResult.__init__),
        (SearchResult, "__post_init__", SearchResult.__post_init__),
    )
)
_DENSE_PRODUCTION_CONTRACT_SHAPE_AUTHORITY = tuple(
    (
        owner,
        type.__getattribute__(owner, "__getattribute__"),
        tuple((name, type.__getattribute__(owner, "__dict__")[name]) for name in fields),
    )
    for owner, fields in (
        (Candidate, ("evidence_id", "doc_id", "score", "lane", "rank", "granularity")),
        (SearchResult, ("candidates", "trace")),
    )
)
_DENSE_CONTRACT_GLOBALS = object.__getattribute__(validate_search, "__globals__")
_DENSE_CONTRACT_JSON = dict.get(_DENSE_CONTRACT_GLOBALS, "json")
_DENSE_CONTRACT_MATH = dict.get(_DENSE_CONTRACT_GLOBALS, "math")
_DENSE_PRODUCTION_CONTRACT_GLOBAL_AUTHORITY = (
    _DENSE_CONTRACT_GLOBALS,
    (
        ("Candidate", Candidate),
        ("SearchResult", SearchResult),
        ("freeze", dict.get(_DENSE_CONTRACT_GLOBALS, "freeze")),
        ("thaw", dict.get(_DENSE_CONTRACT_GLOBALS, "thaw")),
        ("json", _DENSE_CONTRACT_JSON),
        ("math", _DENSE_CONTRACT_MATH),
        ("Mapping", dict.get(_DENSE_CONTRACT_GLOBALS, "Mapping")),
        ("MappingProxyType", dict.get(_DENSE_CONTRACT_GLOBALS, "MappingProxyType")),
    ),
    (
        ("loads", _DENSE_CONTRACT_JSON.loads),
        ("dumps", _DENSE_CONTRACT_JSON.dumps),
    ),
    (("isfinite", _DENSE_CONTRACT_MATH.isfinite),),
)
_DENSE_PRODUCTION_GLOBALS = globals()


def _require_dense_production_search_dependencies(
    _module_globals=None,
    _functions=None,
    _traversal_functions=None,
    _objects=None,
    _numpy_authority=None,
    _registry_authority=None,
    _registry_instances=None,
    _contract_methods=None,
    _contract_shapes=None,
    _contract_globals=None,
    *,
    include_traversal: bool = False,
) -> None:
    """Fail closed on production-search dependency drift without invoking it."""

    namespace = globals()
    if type(_module_globals) is not dict or namespace is not _module_globals:
        raise ValueError("dense_production_search_dependency_override")
    current_checker = dict.get(
        namespace, "_require_dense_production_search_dependencies"
    )
    if (
        current_checker
        is not _ISSUED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES
        or type(current_checker) is not type(
            _ISSUED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES
        )
        or object.__getattribute__(current_checker, "__code__")
        is not _PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_CODE
    ):
        raise ValueError("dense_production_search_dependency_override")
    checker_defaults = object.__getattribute__(current_checker, "__defaults__")
    checker_kwdefaults = object.__getattribute__(
        current_checker, "__kwdefaults__"
    )
    expected_defaults = (
        namespace,
        dict.get(namespace, "_DENSE_PRODUCTION_FUNCTION_AUTHORITY"),
        dict.get(namespace, "_DENSE_PRODUCTION_TRAVERSAL_FUNCTION_AUTHORITY"),
        dict.get(namespace, "_DENSE_PRODUCTION_OBJECT_AUTHORITY"),
        dict.get(namespace, "_DENSE_PRODUCTION_NUMPY_AUTHORITY"),
        dict.get(namespace, "_DENSE_PRODUCTION_REGISTRY_METHOD_AUTHORITY"),
        dict.get(namespace, "_DENSE_PRODUCTION_REGISTRY_INSTANCE_AUTHORITY"),
        dict.get(namespace, "_DENSE_PRODUCTION_CONTRACT_METHOD_AUTHORITY"),
        dict.get(namespace, "_DENSE_PRODUCTION_CONTRACT_SHAPE_AUTHORITY"),
        dict.get(namespace, "_DENSE_PRODUCTION_CONTRACT_GLOBAL_AUTHORITY"),
    )
    if (
        type(checker_defaults) is not tuple
        or tuple.__len__(checker_defaults) != len(expected_defaults)
        or any(
            tuple.__getitem__(checker_defaults, index) is not issued
            for index, issued in enumerate(expected_defaults)
        )
        or checker_defaults
        is not dict.get(
            namespace,
            "_PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_DEFAULTS",
        )
        or type(checker_kwdefaults) is not dict
        or dict.__len__(checker_kwdefaults) != 1
        or dict.get(checker_kwdefaults, "include_traversal") is not False
        or checker_kwdefaults
        is not dict.get(
            namespace,
            "_PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_KWDEFAULTS",
        )
        or _functions is not dict.get(
            namespace, "_DENSE_PRODUCTION_FUNCTION_AUTHORITY"
        )
        or _traversal_functions is not dict.get(
            namespace, "_DENSE_PRODUCTION_TRAVERSAL_FUNCTION_AUTHORITY"
        )
        or _objects is not dict.get(
            namespace, "_DENSE_PRODUCTION_OBJECT_AUTHORITY"
        )
        or _numpy_authority is not dict.get(
            namespace, "_DENSE_PRODUCTION_NUMPY_AUTHORITY"
        )
        or _registry_authority is not dict.get(
            namespace, "_DENSE_PRODUCTION_REGISTRY_METHOD_AUTHORITY"
        )
        or _registry_instances is not dict.get(
            namespace, "_DENSE_PRODUCTION_REGISTRY_INSTANCE_AUTHORITY"
        )
        or _contract_methods is not dict.get(
            namespace, "_DENSE_PRODUCTION_CONTRACT_METHOD_AUTHORITY"
        )
        or _contract_shapes is not dict.get(
            namespace, "_DENSE_PRODUCTION_CONTRACT_SHAPE_AUTHORITY"
        )
        or _contract_globals is not dict.get(
            namespace, "_DENSE_PRODUCTION_CONTRACT_GLOBAL_AUTHORITY"
        )
    ):
        raise ValueError("dense_production_search_dependency_override")
    current_registry_checker = dict.get(
        namespace, "_require_pinned_dense_registry_authority"
    )
    if (
        current_registry_checker
        is not _ISSUED_REQUIRE_PINNED_DENSE_REGISTRY_AUTHORITY
        or type(current_registry_checker)
        is not type(_ISSUED_REQUIRE_PINNED_DENSE_REGISTRY_AUTHORITY)
        or object.__getattribute__(current_registry_checker, "__code__")
        is not _PINNED_REQUIRE_PINNED_DENSE_REGISTRY_AUTHORITY_CODE
    ):
        raise ValueError("dense_production_search_dependency_override")
    for name, issued, issued_code in _functions:
        current = dict.get(namespace, name)
        if (
            current is not issued
            or type(current) is not type(issued)
            or object.__getattribute__(current, "__code__") is not issued_code
        ):
            raise ValueError("dense_production_search_dependency_override")
    if type(include_traversal) is not bool:
        raise ValueError("dense_production_search_dependency_override")
    if include_traversal:
        for name, issued, issued_code in _traversal_functions:
            current = dict.get(namespace, name)
            if (
                current is not issued
                or type(current) is not type(issued)
                or object.__getattribute__(current, "__code__") is not issued_code
            ):
                raise ValueError("dense_production_search_dependency_override")
    for name, issued in _objects:
        if dict.get(namespace, name) is not issued:
            raise ValueError("dense_production_search_dependency_override")

    # Preserve the lane/provider-specific fail-closed diagnostics even when a
    # registry method is also hostile. These are class-namespace identity reads;
    # no lane, provider, store, weakref, or model object is traversed.
    if (
        type.__getattribute__(DenseChildLane, "__getattribute__")
        is not _PINNED_DENSE_GETATTRIBUTE
        or type.__getattribute__(DenseChildLane, "__hash__")
        is not _PINNED_DENSE_HASH
    ):
        raise ValueError("loaded_dense_search_method_override")
    if (
        type.__getattribute__(KureEmbeddingProvider, "__hash__")
        is not _PINNED_KURE_HASH
        or type.__getattribute__(HuggingFaceTokenCounter, "__hash__")
        is not _PINNED_COUNTER_HASH
    ):
        raise ValueError("dense_production_provider_method_override")

    issued_numpy, numpy_attributes, issued_linalg, linalg_attributes = (
        _numpy_authority
    )
    numpy_namespace = object.__getattribute__(issued_numpy, "__dict__")
    linalg_namespace = object.__getattribute__(issued_linalg, "__dict__")
    if (
        dict.get(namespace, "np") is not issued_numpy
        or dict.get(numpy_namespace, "linalg") is not issued_linalg
        or any(dict.get(numpy_namespace, name) is not issued for name, issued in numpy_attributes)
        or any(dict.get(linalg_namespace, name) is not issued for name, issued in linalg_attributes)
    ):
        raise ValueError("dense_production_search_dependency_override")

    for owner, name, issued, issued_code in _contract_methods:
        current = type.__getattribute__(owner, "__dict__").get(name)
        if (
            current is not issued
            or type(current) is not type(issued)
            or object.__getattribute__(current, "__code__") is not issued_code
        ):
            raise ValueError("dense_production_search_dependency_override")
    for owner, issued_getattribute, descriptors in _contract_shapes:
        owner_namespace = type.__getattribute__(owner, "__dict__")
        if (
            type.__getattribute__(owner, "__getattribute__")
            is not issued_getattribute
            or any(
                owner_namespace.get(name) is not issued
                for name, issued in descriptors
            )
        ):
            raise ValueError("dense_production_search_dependency_override")

    contract_namespace, contract_aliases, json_aliases, math_aliases = (
        _contract_globals
    )
    if any(
        dict.get(contract_namespace, name) is not issued
        for name, issued in contract_aliases
    ):
        raise ValueError("dense_production_search_dependency_override")
    contract_json = dict.get(contract_namespace, "json")
    contract_math = dict.get(contract_namespace, "math")
    if any(
        dict.get(object.__getattribute__(contract_json, "__dict__"), name)
        is not issued
        for name, issued in json_aliases
    ) or any(
        dict.get(object.__getattribute__(contract_math, "__dict__"), name)
        is not issued
        for name, issued in math_aliases
    ):
        raise ValueError("dense_production_search_dependency_override")


_ISSUED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES = (
    _require_dense_production_search_dependencies
)
_PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_CODE = (
    _require_dense_production_search_dependencies.__code__
)
_require_dense_production_search_dependencies.__defaults__ = (
    _DENSE_PRODUCTION_GLOBALS,
    _DENSE_PRODUCTION_FUNCTION_AUTHORITY,
    _DENSE_PRODUCTION_TRAVERSAL_FUNCTION_AUTHORITY,
    _DENSE_PRODUCTION_OBJECT_AUTHORITY,
    _DENSE_PRODUCTION_NUMPY_AUTHORITY,
    _DENSE_PRODUCTION_REGISTRY_METHOD_AUTHORITY,
    _DENSE_PRODUCTION_REGISTRY_INSTANCE_AUTHORITY,
    _DENSE_PRODUCTION_CONTRACT_METHOD_AUTHORITY,
    _DENSE_PRODUCTION_CONTRACT_SHAPE_AUTHORITY,
    _DENSE_PRODUCTION_CONTRACT_GLOBAL_AUTHORITY,
)
_PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_DEFAULTS = (
    _require_dense_production_search_dependencies.__defaults__
)
_PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_KWDEFAULTS = (
    _require_dense_production_search_dependencies.__kwdefaults__
)


def _require_pinned_dense_registry_authority(
    _module_globals=_DENSE_PRODUCTION_GLOBALS,
    _authority=_DENSE_PRODUCTION_REGISTRY_METHOD_AUTHORITY,
    _instances=_DENSE_PRODUCTION_REGISTRY_INSTANCE_AUTHORITY,
) -> None:
    """Validate identity registries before their first lookup."""

    namespace = globals()
    if type(_module_globals) is not dict or namespace is not _module_globals:
        raise ValueError("dense_production_search_dependency_override")
    current_checker = dict.get(namespace, "_require_pinned_dense_registry_authority")
    if (
        current_checker is not _ISSUED_REQUIRE_PINNED_DENSE_REGISTRY_AUTHORITY
        or type(current_checker)
        is not type(_ISSUED_REQUIRE_PINNED_DENSE_REGISTRY_AUTHORITY)
        or object.__getattribute__(current_checker, "__code__")
        is not _PINNED_REQUIRE_PINNED_DENSE_REGISTRY_AUTHORITY_CODE
    ):
        raise ValueError("dense_production_search_dependency_override")
    checker_defaults = object.__getattribute__(current_checker, "__defaults__")
    if (
        type(checker_defaults) is not tuple
        or tuple.__len__(checker_defaults) != 3
        or tuple.__getitem__(checker_defaults, 0) is not namespace
        or tuple.__getitem__(checker_defaults, 1)
        is not dict.get(namespace, "_DENSE_PRODUCTION_REGISTRY_METHOD_AUTHORITY")
        or tuple.__getitem__(checker_defaults, 2)
        is not dict.get(namespace, "_DENSE_PRODUCTION_REGISTRY_INSTANCE_AUTHORITY")
        or _authority
        is not dict.get(namespace, "_DENSE_PRODUCTION_REGISTRY_METHOD_AUTHORITY")
        or _instances
        is not dict.get(namespace, "_DENSE_PRODUCTION_REGISTRY_INSTANCE_AUTHORITY")
    ):
        raise ValueError("dense_production_search_dependency_override")
    (
        registry_class,
        registry_getattribute,
        registry_setattr,
        entries_descriptor,
        registry_methods,
    ) = _authority
    registry_namespace = type.__getattribute__(registry_class, "__dict__")
    if (
        dict.get(namespace, "_IdentityWeakRegistry") is not registry_class
        or type.__getattribute__(registry_class, "__getattribute__")
        is not registry_getattribute
        or type.__getattribute__(registry_class, "__setattr__")
        is not registry_setattr
        or type(entries_descriptor) is not MemberDescriptorType
        or registry_namespace.get("_entries") is not entries_descriptor
    ):
        raise ValueError("dense_production_search_dependency_override")
    for name, issued, issued_code in registry_methods:
        current = registry_namespace.get(name)
        if (
            current is not issued
            or type(current) is not type(issued)
            or object.__getattribute__(current, "__code__") is not issued_code
        ):
            raise ValueError("dense_production_search_dependency_override")
    for registry, issued_entries in _instances:
        if (
            type(registry) is not registry_class
            or type(issued_entries) is not dict
            or object.__getattribute__(registry, "_entries") is not issued_entries
        ):
            raise ValueError("dense_production_registry_storage_drift")


_ISSUED_REQUIRE_PINNED_DENSE_REGISTRY_AUTHORITY = (
    _require_pinned_dense_registry_authority
)
_PINNED_REQUIRE_PINNED_DENSE_REGISTRY_AUTHORITY_CODE = (
    _require_pinned_dense_registry_authority.__code__
)


for _dense_runtime_entry in (
    build_dense,
    load_dense,
    _preflight_loaded_dense_context,
    preflight_loaded_dense_artifact,
    require_loaded_dense_artifact,
):
    object.__getattribute__(_dense_runtime_entry, "__kwdefaults__").update(
        {
            "_dependency_checker": (
                _ISSUED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES
            ),
            "_dependency_checker_code": (
                _PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_CODE
            ),
            "_dependency_checker_defaults": (
                _PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_DEFAULTS
            ),
            "_dependency_checker_kwdefaults": (
                _PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_KWDEFAULTS
            ),
            "_dependency_checker_globals": _DENSE_PRODUCTION_GLOBALS,
        }
    )
del _dense_runtime_entry

object.__getattribute__(DenseChildLane.search, "__kwdefaults__").update(
    {
        "_dependency_checker_identity": id(
            _ISSUED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES
        ),
        "_dependency_checker_code_identity": id(
            _PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_CODE
        ),
        "_dependency_checker_defaults_identity": id(
            _PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_DEFAULTS
        ),
        "_dependency_checker_kwdefaults_identity": id(
            _PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_KWDEFAULTS
        ),
        "_dependency_checker_globals_identity": id(_DENSE_PRODUCTION_GLOBALS),
    }
)
