from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from midprojectrag.ingest.common import (
    read_jsonl,
    require_sha256,
    sha256_file,
    write_json,
    write_jsonl,
)
from midprojectrag.indexing.chunking import chunk_artifact_sha256, validate_chunk
from midprojectrag.indexing.embeddings import l2_normalize


@dataclass(frozen=True)
class IndexSearchHit:
    row_id: int
    score: float
    chunk: dict[str, Any]


def _safe_rows(chunks: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    lane_contracts: set[tuple[str, str, str]] = set()
    for chunk in chunks:
        validate_chunk(chunk)
        lane_contracts.add(
            (
                chunk["retrieval_role"],
                chunk["chunker_id"],
                chunk["config_sha256"],
            )
        )
        chunk_id = chunk.get("chunk_id")
        if not isinstance(chunk_id, str) or not chunk_id or chunk_id in seen:
            raise ValueError("invalid_or_duplicate_index_chunk_id")
        seen.add(chunk_id)
        rows.append(
            {
                "chunk_id": chunk_id,
                "doc_id": chunk.get("doc_id"),
            }
        )
    if len(lane_contracts) != 1:
        raise ValueError("mixed_index_chunk_contracts")
    return rows


def _atomic_numpy(path: Path, matrix: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            np.save(output, matrix, allow_pickle=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _index_lock(output_dir: Path, *, exclusive: bool) -> Iterable[None]:
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / ".index.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


class ExactDenseIndex:
    """Exact cosine index; FAISS is production, NumPy is a local smoke fallback."""

    def __init__(
        self,
        chunks: Sequence[dict[str, Any]],
        vectors: np.ndarray,
        *,
        engine: str = "faiss",
    ) -> None:
        self._initialize(chunks, l2_normalize(vectors), engine=engine)

    def _initialize(
        self,
        chunks: Sequence[dict[str, Any]],
        matrix: np.ndarray,
        *,
        engine: str,
    ) -> None:
        if engine not in {"faiss", "numpy"}:
            raise ValueError("unsupported_index_engine")
        if len(chunks) < 1:
            raise ValueError("empty_index")
        if matrix.shape[0] != len(chunks):
            raise ValueError("index_row_count_mismatch")
        self.chunks = list(chunks)
        self.rows = _safe_rows(chunks)
        self.vectors = matrix
        self.engine = engine
        self._faiss = None
        self._index = None
        if engine == "faiss":
            try:
                import faiss
            except ImportError as error:
                raise RuntimeError("faiss_dependency_missing") from error
            self._faiss = faiss
            self._index = faiss.IndexFlatIP(matrix.shape[1])
            self._index.add(matrix)

    @classmethod
    def from_normalized_vectors(
        cls,
        chunks: Sequence[dict[str, Any]],
        vectors: np.ndarray,
        *,
        engine: str = "faiss",
    ) -> "ExactDenseIndex":
        """Construct from a verified normalized artifact without changing bytes."""

        matrix = np.asarray(vectors, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[0] < 1 or matrix.shape[1] < 1:
            raise ValueError("invalid_embedding_matrix")
        if not np.isfinite(matrix).all():
            raise ValueError("embedding_non_finite")
        norms = np.linalg.norm(matrix, axis=1)
        if np.any(norms == 0) or not np.allclose(norms, 1.0, rtol=0.0, atol=1e-5):
            raise ValueError("embedding_matrix_not_normalized")
        instance = cls.__new__(cls)
        instance._initialize(
            chunks,
            np.ascontiguousarray(matrix, dtype=np.float32),
            engine=engine,
        )
        return instance

    @property
    def dimensions(self) -> int:
        return int(self.vectors.shape[1])

    def _candidate_rows(self, allowed_doc_ids: set[str] | None) -> np.ndarray:
        if allowed_doc_ids is None:
            return np.arange(len(self.rows), dtype=np.int64)
        if not allowed_doc_ids:
            return np.empty((0,), dtype=np.int64)
        return np.asarray(
            [index for index, row in enumerate(self.rows) if row["doc_id"] in allowed_doc_ids],
            dtype=np.int64,
        )

    def search(
        self,
        query_vector: Sequence[float] | np.ndarray,
        *,
        top_k: int = 10,
        allowed_doc_ids: set[str] | None = None,
    ) -> list[IndexSearchHit]:
        if top_k < 1:
            raise ValueError("invalid_top_k")
        query = np.asarray(query_vector, dtype=np.float32)
        if query.shape != (self.dimensions,) or not np.isfinite(query).all():
            raise ValueError("invalid_query_vector")
        norm = float(np.linalg.norm(query))
        if norm == 0 or not np.isfinite(norm):
            raise ValueError("query_zero_vector")
        query = np.ascontiguousarray(query / norm, dtype=np.float32)
        candidate_rows = self._candidate_rows(allowed_doc_ids)
        if candidate_rows.size == 0:
            return []
        limit = min(top_k, int(candidate_rows.size))
        if self.engine == "faiss":
            search_count = int(candidate_rows.size)
            if allowed_doc_ids is None:
                scores, indices = self._index.search(query.reshape(1, -1), search_count)
                faiss_pairs = [
                    (int(row), float(score))
                    for row, score in zip(indices[0], scores[0], strict=True)
                    if int(row) >= 0
                ]
            else:
                scoped = np.ascontiguousarray(self.vectors[candidate_rows], dtype=np.float32)
                temporary_index = self._faiss.IndexFlatIP(self.dimensions)
                temporary_index.add(scoped)
                scores, local_indices = temporary_index.search(query.reshape(1, -1), search_count)
                faiss_pairs = [
                    (int(candidate_rows[int(local_row)]), float(score))
                    for local_row, score in zip(local_indices[0], scores[0], strict=True)
                    if int(local_row) >= 0
                ]
            faiss_pairs.sort(key=lambda item: (-item[1], item[0]))
            ranked_rows = np.asarray([item[0] for item in faiss_pairs[:limit]], dtype=np.int64)
            ranked_scores = np.asarray([item[1] for item in faiss_pairs[:limit]], dtype=np.float32)
        else:
            scores = self.vectors[candidate_rows] @ query
            order = np.argsort(-scores, kind="stable")[:limit]
            ranked_rows = candidate_rows[order]
            ranked_scores = scores[order]
        return [
            IndexSearchHit(row_id=int(row), score=float(score), chunk=self.chunks[int(row)])
            for row, score in zip(ranked_rows, ranked_scores, strict=True)
            if int(row) >= 0
        ]

    def save(
        self,
        output_dir: Path,
        *,
        corpus_manifest_sha256: str,
        embedding_model: str,
        api_profile: str | None = None,
        index_config_sha256: str | None = None,
    ) -> dict[str, Any]:
        with _index_lock(output_dir, exclusive=True):
            return self._save_unlocked(
                output_dir,
                corpus_manifest_sha256=corpus_manifest_sha256,
                embedding_model=embedding_model,
                api_profile=api_profile,
                index_config_sha256=index_config_sha256,
            )

    def _save_unlocked(
        self,
        output_dir: Path,
        *,
        corpus_manifest_sha256: str,
        embedding_model: str,
        api_profile: str | None,
        index_config_sha256: str | None,
    ) -> dict[str, Any]:
        require_sha256(corpus_manifest_sha256, "invalid_corpus_manifest_hash")
        if (api_profile is None) != (index_config_sha256 is None):
            raise ValueError("incomplete_index_profile_metadata")
        if api_profile is not None and (
            not isinstance(api_profile, str) or not api_profile.strip()
        ):
            raise ValueError("invalid_index_api_profile")
        if index_config_sha256 is not None:
            require_sha256(index_config_sha256, "invalid_index_config_hash")
        output_dir.mkdir(parents=True, exist_ok=True)
        planned_identity = {
            "engine": self.engine,
            "dimensions": self.dimensions,
            "embedding_model": embedding_model,
            "corpus_manifest_sha256": corpus_manifest_sha256,
            "chunk_config_sha256": self.chunks[0]["config_sha256"],
            "chunk_artifact_sha256": chunk_artifact_sha256(self.chunks),
            "api_profile": api_profile,
            "index_config_sha256": index_config_sha256,
        }
        existing_metadata_path = output_dir / "metadata.json"
        if existing_metadata_path.is_file():
            try:
                with existing_metadata_path.open("r", encoding="utf-8") as source:
                    existing_metadata = json.load(source)
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise ValueError("index_output_config_mismatch") from error
            if not isinstance(existing_metadata, dict) or any(
                existing_metadata.get(key) != value for key, value in planned_identity.items()
            ):
                raise ValueError("index_output_config_mismatch")
        vectors_path = output_dir / "vectors.npy"
        rows_path = output_dir / "rows.jsonl"
        index_path = output_dir / "index.faiss"
        _atomic_numpy(vectors_path, self.vectors)
        write_jsonl(rows_path, self.rows)
        if self.engine == "faiss":
            descriptor, name = tempfile.mkstemp(prefix=".index.faiss.", dir=output_dir)
            os.close(descriptor)
            temporary = Path(name)
            try:
                self._faiss.write_index(self._index, str(temporary))
                os.replace(temporary, index_path)
            finally:
                temporary.unlink(missing_ok=True)
        else:
            index_path.unlink(missing_ok=True)
        metadata = {
            "schema_version": "1.0",
            "engine": self.engine,
            "metric": "cosine_via_normalized_inner_product",
            "count": len(self.rows),
            "dimensions": self.dimensions,
            "embedding_model": embedding_model,
            "corpus_manifest_sha256": corpus_manifest_sha256,
            "chunk_config_sha256": self.chunks[0]["config_sha256"],
            "chunk_artifact_sha256": chunk_artifact_sha256(self.chunks),
            "vectors_sha256": sha256_file(vectors_path),
            "rows_sha256": sha256_file(rows_path),
            "index_sha256": sha256_file(index_path) if index_path.is_file() else None,
            "api_profile": api_profile,
            "index_config_sha256": index_config_sha256,
        }
        write_json(output_dir / "metadata.json", metadata)
        return metadata

    @classmethod
    def load(
        cls,
        output_dir: Path,
        chunks: Sequence[dict[str, Any]],
        *,
        expected_embedding_model: str | None = None,
        expected_dimensions: int | None = None,
        expected_api_profile: str | None = None,
        expected_index_config_sha256: str | None = None,
    ) -> "ExactDenseIndex":
        with _index_lock(output_dir, exclusive=False):
            return cls._load_unlocked(
                output_dir,
                chunks,
                expected_embedding_model=expected_embedding_model,
                expected_dimensions=expected_dimensions,
                expected_api_profile=expected_api_profile,
                expected_index_config_sha256=expected_index_config_sha256,
            )

    @classmethod
    def _load_unlocked(
        cls,
        output_dir: Path,
        chunks: Sequence[dict[str, Any]],
        *,
        expected_embedding_model: str | None,
        expected_dimensions: int | None,
        expected_api_profile: str | None,
        expected_index_config_sha256: str | None,
    ) -> "ExactDenseIndex":
        with (output_dir / "metadata.json").open("r", encoding="utf-8") as source:
            metadata = json.load(source)
        if not isinstance(metadata, dict) or metadata.get("schema_version") != "1.0":
            raise ValueError("invalid_index_metadata")
        expected_values = {
            "embedding_model": expected_embedding_model,
            "dimensions": expected_dimensions,
            "api_profile": expected_api_profile,
            "index_config_sha256": expected_index_config_sha256,
        }
        if any(
            expected is not None and metadata.get(key) != expected
            for key, expected in expected_values.items()
        ):
            raise ValueError("index_expected_config_mismatch")
        vectors_path = output_dir / "vectors.npy"
        rows_path = output_dir / "rows.jsonl"
        if sha256_file(vectors_path) != metadata.get("vectors_sha256"):
            raise ValueError("index_vectors_hash_mismatch")
        if sha256_file(rows_path) != metadata.get("rows_sha256"):
            raise ValueError("index_rows_hash_mismatch")
        if chunk_artifact_sha256(chunks) != metadata.get("chunk_artifact_sha256"):
            raise ValueError("index_chunk_artifact_hash_mismatch")
        stored_rows = read_jsonl(rows_path)
        if stored_rows != _safe_rows(chunks):
            raise ValueError("index_rows_do_not_match_chunks")
        vectors = np.load(vectors_path, allow_pickle=False)
        instance = cls.from_normalized_vectors(
            chunks,
            vectors,
            engine=metadata.get("engine"),
        )
        if instance.dimensions != metadata.get("dimensions") or len(chunks) != metadata.get("count"):
            raise ValueError("index_shape_metadata_mismatch")
        if instance.engine == "faiss":
            index_path = output_dir / "index.faiss"
            if sha256_file(index_path) != metadata.get("index_sha256"):
                raise ValueError("faiss_index_hash_mismatch")
            loaded_index = instance._faiss.read_index(str(index_path))
            if loaded_index.ntotal != len(chunks) or loaded_index.d != instance.dimensions:
                raise ValueError("faiss_index_shape_mismatch")
            # Search from the verified vectors, not a separately persisted
            # FAISS object. This prevents mixed artifacts from making all-scope
            # and explicit-scope searches use different vector snapshots.
        return instance
