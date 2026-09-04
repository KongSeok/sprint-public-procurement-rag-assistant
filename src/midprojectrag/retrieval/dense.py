"""Pinned KURE exact child lane; independent of legacy page vector identities."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
from types import MappingProxyType
from weakref import WeakKeyDictionary
import numpy as np

from midprojectrag.evidence import EvidenceStore
from midprojectrag.evidence.artifacts import file_sha, private_path, write_new_json
from midprojectrag.stacks.local.gcp_config import (
    KURE_MODEL_ID, KURE_MODEL_REVISION, KURE_DIMENSIONS, KURE_POOLING, KURE_PROMPT_VERSION,
)
from midprojectrag.stacks.local.hf_embeddings import (
    HuggingFaceTokenCounter,
    KureEmbeddingProvider,
    _default_encoder_loader,
    _default_tokenizer_loader,
)
from .contracts import Candidate, SearchResult, validate_search

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
_LOADED_DENSE: WeakKeyDictionary = WeakKeyDictionary()
_LOADED_DENSE_RUNTIME: WeakKeyDictionary = WeakKeyDictionary()
_BUILT_DENSE_RUNTIME: WeakKeyDictionary = WeakKeyDictionary()
_PINNED_KURE_EMBED = KureEmbeddingProvider.embed
_PINNED_KURE_GET_ENCODER = KureEmbeddingProvider._get_encoder
_PINNED_COUNTER_GET_TOKENIZER = HuggingFaceTokenCounter._get_tokenizer


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

    if type(provider) is not KureEmbeddingProvider:
        raise ValueError("dense_production_embedding_provider_required")
    counter = provider._counter
    if type(counter) is not HuggingFaceTokenCounter:
        raise ValueError("dense_production_token_counter_required")
    if provider._encoder_loader is _default_encoder_loader:
        provider._encoder_loader = _sealed_encoder_loader
    elif provider._encoder_loader is not _sealed_encoder_loader:
        raise ValueError("dense_production_encoder_loader_not_pinned")
    if counter._tokenizer_loader is _default_tokenizer_loader:
        counter._tokenizer_loader = _sealed_tokenizer_loader
    elif counter._tokenizer_loader is not _sealed_tokenizer_loader:
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

    encoder = _PINNED_KURE_GET_ENCODER(provider)
    tokenizer = _PINNED_COUNTER_GET_TOKENIZER(provider._counter)
    runtime = (encoder, tokenizer)
    _validate_loaded_runtime_objects(runtime)
    return runtime


def _digest(value) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _matrix_hash(matrix) -> str:
    value = np.asarray(matrix, dtype=np.float32)
    return sha256(value.tobytes(order="C")).hexdigest()


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
        expected = {
            "bundle_sha256", "rows_sha256", "receipt_sha256", "vectors_file_sha256",
            "vectors_content_sha256", "embedding_identity_sha256", "execution_kind",
            "provider_runtime_sha256",
        }
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


def _production_provider_runtime_sha256(
    provider, *, expected_runtime: tuple[object | None, object | None] | None = None,
    require_lazy: bool = False,
) -> str:
    """Validate a KURE adapter whose runtime objects came from pinned loaders."""

    if type(provider) is not KureEmbeddingProvider or provider.execution_kind != "real_local_model":
        raise ValueError("dense_production_embedding_provider_required")
    if any(name in vars(provider) for name in ("embed", "_get_encoder")):
        raise ValueError("dense_production_embedding_method_override")
    if provider._encoder_loader is not _sealed_encoder_loader:
        raise ValueError("dense_production_encoder_loader_not_pinned")
    counter = provider._counter
    if type(counter) is not HuggingFaceTokenCounter or any(
        name in vars(counter) for name in ("count", "_get_tokenizer")
    ):
        raise ValueError("dense_production_token_counter_required")
    if counter._tokenizer_loader is not _sealed_tokenizer_loader:
        raise ValueError("dense_production_tokenizer_loader_not_pinned")
    if (
        counter.model != provider.model
        or counter.revision != provider.revision
        or counter.local_files_only is not True
        or counter.trust_remote_code is not False
        or provider.local_files_only is not True
        or provider.trust_remote_code is not False
    ):
        raise ValueError("dense_production_provider_config_mismatch")
    current_runtime = (provider._encoder, counter._tokenizer)
    _validate_loaded_runtime_objects(current_runtime)
    if require_lazy and any(value is not None for value in current_runtime):
        raise ValueError("dense_production_provider_requires_fresh_lazy_runtime")
    if expected_runtime is not None and any(
        current is not expected for current, expected in zip(current_runtime, expected_runtime)
    ):
        raise ValueError("dense_production_provider_runtime_object_drift")
    return _digest(
        {
            "embedding_identity": _provider_identity(provider),
            "batch_size": provider.batch_size,
            "device": provider.device,
            "local_files_only": provider.local_files_only,
            "trust_remote_code": provider.trust_remote_code,
            "encoder_loader": "midprojectrag.retrieval.dense._sealed_encoder_loader",
            "tokenizer_loader": "midprojectrag.retrieval.dense._sealed_tokenizer_loader",
        }
    )


def _provider_identity(provider) -> dict:
    identity = {key: getattr(provider, key, None) for key in KURE_IDENTITY}
    if identity != KURE_IDENTITY:
        raise ValueError("child_embedding_identity_not_pinned_kure")
    return identity


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
        rows = store.candidates()
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

    def search(self, query: str, limit: int, *, allowed_doc_ids=None) -> SearchResult:
        validate_search(query, limit, allowed_doc_ids)
        indices = [i for i, e in enumerate(self.rows) if allowed_doc_ids is None or e.doc_id in allowed_doc_ids]
        trace = {"lane": "dense", "granularity": "child", "bundle_sha256": self.store.bundle_sha256,
                 "artifact_sha256": self.artifact_sha256, "embedding_identity": dict(self.identity),
                 "scoped_rows": len(indices), "requested_k": limit}
        if not indices:
            return SearchResult((), trace | {"empty_scope": True, "encoder_calls": 0})
        attestation = _LOADED_DENSE.get(self)
        if (
            type(attestation) is LoadedDenseArtifactAttestation
            and attestation.execution_kind == "real_local_model"
        ):
            require_loaded_dense_artifact(self, self.store, production=True)
            runtime = _LOADED_DENSE_RUNTIME[self]
            if all(value is None for value in runtime["query_runtime"]):
                runtime["query_runtime"] = _initialize_pinned_provider_runtime(
                    runtime["query_provider"]
                )
                require_loaded_dense_artifact(self, self.store, production=True)
            batch = _PINNED_KURE_EMBED(runtime["query_provider"], [query])
            _record_loaded_dense_runtime(self)
        else:
            batch = self.provider.embed([query])
        query_vector = normalize(batch.vectors, 1)[0]
        scores = self.vectors[indices] @ query_vector
        ranked = sorted(zip(indices, scores), key=lambda p: (-float(p[1]), self.rows[p[0]].evidence_id))[:limit]
        return SearchResult(tuple(Candidate(self.rows[i].evidence_id, self.rows[i].doc_id, float(score), "dense", rank)
                                  for rank, (i, score) in enumerate(ranked, 1)), trace | {"encoder_calls": 1})


def build_dense(store: EvidenceStore, provider, *, output_dir: Path, data_root: Path,
                batch_size: int = 16, progress=None) -> dict:
    identity = _provider_identity(provider)
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("invalid_dense_build_config")
    execution_kind = (
        "real_local_model"
        if type(provider) is KureEmbeddingProvider
        and provider.execution_kind == "real_local_model"
        else "synthetic"
    )
    if execution_kind == "real_local_model":
        _seal_provider_loaders(provider)
        _production_provider_runtime_sha256(provider, require_lazy=True)
        _initialize_pinned_provider_runtime(provider)
    target = private_path(output_dir, data_root)
    if target.exists():
        raise FileExistsError(target)
    rows = store.candidates()
    if not rows:
        raise ValueError("empty_child_store")
    batches = []
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i+batch_size]
        embedded = (
            _PINNED_KURE_EMBED(provider, [e.text for e in batch])
            if execution_kind == "real_local_model"
            else provider.embed([e.text for e in batch])
        )
        batches.append(normalize(embedded.vectors, len(batch)))
        if progress is not None:
            progress(i+len(batch), len(rows))
    matrix = np.concatenate(batches)
    runtime = None
    if execution_kind == "real_local_model":
        runtime = (provider._encoder, provider._counter._tokenizer)
        if any(value is None for value in runtime):
            raise ValueError("dense_production_runtime_initialization_incomplete")
        _production_provider_runtime_sha256(provider, expected_runtime=runtime)
    target.mkdir(parents=True, exist_ok=False, mode=0o700)
    descriptor = os.open(target / "vectors.npy", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        np.save(output, matrix, allow_pickle=False)
    receipt = {"schema_version": "1.0", "granularity": "child", "bundle_sha256": store.bundle_sha256,
               "embedding_identity": identity, "rows_sha256": _row_hash(rows), "count": len(rows),
               "vectors_sha256": file_sha(target / "vectors.npy"), "execution_kind": execution_kind}
    write_new_json(target / "receipt.json", receipt)
    if runtime is not None:
        _BUILT_DENSE_RUNTIME[provider] = {
            "runtime": runtime,
            "target": target,
            "bundle_sha256": store.bundle_sha256,
            "rows_sha256": receipt["rows_sha256"],
            "vectors_sha256": receipt["vectors_sha256"],
        }
    return receipt


def load_dense(store: EvidenceStore, provider, *, output_dir: Path, data_root: Path) -> DenseChildLane:
    identity = _provider_identity(provider)
    target = private_path(output_dir, data_root)
    if any(not (target / name).resolve().is_relative_to(target) for name in ("receipt.json", "vectors.npy")):
        raise ValueError("dense_artifact_symlink_escape")
    receipt = json.loads((target / "receipt.json").read_text())
    expected = {"schema_version": "1.0", "granularity": "child", "bundle_sha256": store.bundle_sha256,
                "embedding_identity": identity, "rows_sha256": _row_hash(store.candidates()),
                "count": len(store.candidates()), "vectors_sha256": file_sha(target / "vectors.npy")}
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
        current_runtime = (provider._encoder, provider._counter._tokenizer)
        if all(value is None for value in current_runtime):
            provider_runtime = _production_provider_runtime_sha256(
                provider, require_lazy=True
            )
            source_runtime = current_runtime
        else:
            built = _BUILT_DENSE_RUNTIME.get(provider)
            if (
                type(built) is not dict
                or built.get("target") != target
                or built.get("bundle_sha256") != store.bundle_sha256
                or built.get("rows_sha256") != receipt["rows_sha256"]
                or built.get("vectors_sha256") != receipt["vectors_sha256"]
                or any(
                    current is not expected
                    for current, expected in zip(
                        current_runtime, built.get("runtime", (None, None))
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
            provider._encoder = None
            provider._counter._tokenizer = None
            source_runtime = (None, None)
            provider_runtime = _production_provider_runtime_sha256(
                provider, require_lazy=True
            )
        query_provider = KureEmbeddingProvider(
            batch_size=provider.batch_size, device=provider.device
        )
        _seal_provider_loaders(query_provider)
        query_runtime_sha = _production_provider_runtime_sha256(
            query_provider, require_lazy=True
        )
        if query_runtime_sha != provider_runtime:
            raise ValueError("dense_sealed_query_provider_config_mismatch")
    payload = {
        "bundle_sha256": store.bundle_sha256,
        "rows_sha256": _row_hash(store.candidates()),
        "receipt_sha256": lane.artifact_sha256,
        "vectors_file_sha256": receipt["vectors_sha256"],
        "vectors_content_sha256": _matrix_hash(lane.vectors),
        "embedding_identity_sha256": _digest(identity),
        "execution_kind": receipt["execution_kind"],
        "provider_runtime_sha256": provider_runtime,
    }
    attestation = LoadedDenseArtifactAttestation(
        payload, _token=_LOADED_DENSE_ATTESTATION
    )
    _LOADED_DENSE[lane] = attestation
    if receipt["execution_kind"] == "real_local_model":
        _LOADED_DENSE_RUNTIME[lane] = {
            "source_provider": provider,
            "source_runtime": source_runtime,
            "query_provider": query_provider,
            "query_runtime": (None, None),
        }
    return lane


def _record_loaded_dense_runtime(lane: DenseChildLane) -> None:
    """Advance lazy runtime state only after the pinned class method loaded it."""

    if lane not in _LOADED_DENSE_RUNTIME:
        raise ValueError("loaded_dense_runtime_attestation_missing")
    runtime = _LOADED_DENSE_RUNTIME[lane]
    provider = runtime["query_provider"]
    current = (provider._encoder, provider._counter._tokenizer)
    if any(value is None for value in current):
        raise ValueError("loaded_dense_runtime_initialization_incomplete")
    runtime["query_runtime"] = current
    _production_provider_runtime_sha256(provider, expected_runtime=current)


def require_loaded_dense_artifact(
    lane: DenseChildLane, store: EvidenceStore, *, production: bool = False
) -> LoadedDenseArtifactAttestation:
    """Return a loader-issued proof after revalidating all mutable runtime state."""

    if type(lane) is not DenseChildLane or type(store) is not EvidenceStore:
        raise ValueError("loaded_dense_artifact_required")
    attestation = _LOADED_DENSE.get(lane)
    if type(attestation) is not LoadedDenseArtifactAttestation:
        raise ValueError("loaded_dense_artifact_required")
    if lane.store is not store or tuple(lane.rows) != store.candidates():
        raise ValueError("loaded_dense_store_or_rows_mismatch")
    checks = {
        "bundle_sha256": store.bundle_sha256,
        "rows_sha256": _row_hash(store.candidates()),
        "receipt_sha256": lane.artifact_sha256,
        "vectors_content_sha256": _matrix_hash(lane.vectors),
        "embedding_identity_sha256": _digest(_provider_identity(lane.provider)),
    }
    if any(getattr(attestation, name) != value for name, value in checks.items()):
        raise ValueError("loaded_dense_runtime_drift")
    if production:
        if attestation.execution_kind != "real_local_model":
            raise ValueError("loaded_dense_production_execution_required")
        runtime = _LOADED_DENSE_RUNTIME.get(lane)
        if type(runtime) is not dict or set(runtime) != {
            "source_provider", "source_runtime", "query_provider", "query_runtime"
        }:
            raise ValueError("loaded_dense_runtime_attestation_missing")
        if runtime["source_provider"] is not lane.provider:
            raise ValueError("loaded_dense_source_provider_drift")
        source_sha = _production_provider_runtime_sha256(
            lane.provider, expected_runtime=runtime["source_runtime"]
        )
        query_sha = _production_provider_runtime_sha256(
            runtime["query_provider"], expected_runtime=runtime["query_runtime"]
        )
        if (
            not attestation.provider_runtime_sha256
            or source_sha != attestation.provider_runtime_sha256
            or query_sha != attestation.provider_runtime_sha256
        ):
            raise ValueError("loaded_dense_provider_runtime_drift")
    return attestation
