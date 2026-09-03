"""Pinned KURE exact child lane; independent of legacy page vector identities."""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
from types import MappingProxyType
import numpy as np

from midprojectrag.evidence import EvidenceStore
from midprojectrag.evidence.artifacts import file_sha, private_path, write_new_json
from midprojectrag.stacks.local.gcp_config import (
    KURE_MODEL_ID, KURE_MODEL_REVISION, KURE_DIMENSIONS, KURE_POOLING, KURE_PROMPT_VERSION,
)
from midprojectrag.stacks.local.hf_embeddings import KureEmbeddingProvider
from .contracts import Candidate, SearchResult, validate_search

KURE_IDENTITY = MappingProxyType({"model": KURE_MODEL_ID, "revision": KURE_MODEL_REVISION,
    "dimensions": KURE_DIMENSIONS, "pooling": KURE_POOLING, "prompt_version": KURE_PROMPT_VERSION, "prompt": ""})
_VERIFIED_VECTOR_SNAPSHOT = object()


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
        return cls(store, vectors, provider, artifact_sha256=artifact_sha256,
                   _verified=_VERIFIED_VECTOR_SNAPSHOT)

    def search(self, query: str, limit: int, *, allowed_doc_ids=None) -> SearchResult:
        validate_search(query, limit, allowed_doc_ids)
        indices = [i for i, e in enumerate(self.rows) if allowed_doc_ids is None or e.doc_id in allowed_doc_ids]
        trace = {"lane": "dense", "granularity": "child", "bundle_sha256": self.store.bundle_sha256,
                 "artifact_sha256": self.artifact_sha256, "embedding_identity": dict(self.identity),
                 "scoped_rows": len(indices), "requested_k": limit}
        if not indices:
            return SearchResult((), trace | {"empty_scope": True, "encoder_calls": 0})
        query_vector = normalize(self.provider.embed([query]).vectors, 1)[0]
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
    target = private_path(output_dir, data_root)
    if target.exists():
        raise FileExistsError(target)
    rows = store.candidates()
    if not rows:
        raise ValueError("empty_child_store")
    batches = []
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i+batch_size]
        batches.append(normalize(provider.embed([e.text for e in batch]).vectors, len(batch)))
        if progress is not None:
            progress(i+len(batch), len(rows))
    matrix = np.concatenate(batches)
    target.mkdir(parents=True, exist_ok=False, mode=0o700)
    descriptor = os.open(target / "vectors.npy", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        np.save(output, matrix, allow_pickle=False)
    receipt = {"schema_version": "1.0", "granularity": "child", "bundle_sha256": store.bundle_sha256,
               "embedding_identity": identity, "rows_sha256": _row_hash(rows), "count": len(rows),
               "vectors_sha256": file_sha(target / "vectors.npy"), "execution_kind": execution_kind}
    write_new_json(target / "receipt.json", receipt)
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
    return DenseChildLane._from_verified(
        store, vectors, provider, artifact_sha256=file_sha(target / "receipt.json")
    )
