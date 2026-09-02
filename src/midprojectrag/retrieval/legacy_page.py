"""Read-only reuse of pinned legacy page vectors as *page* candidates.

Legacy vectors describe the original page parts, never newly split text children.
For a split page, its candidate score is the maximum original part similarity.
Callers may subsequently expand explicit children under a separate context policy.
This adapter does not load a model, access an evaluation set, or write index locks.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any

import numpy as np

from midprojectrag.evidence import Evidence, EvidenceStore
from midprojectrag.indexing.chunking import chunk_artifact_sha256, validate_chunk
from midprojectrag.retrieval.types import Candidate, positive_int, validate_lane, validate_query, validate_scope


@dataclass(frozen=True)
class LegacyPageArtifactPin:
    """Caller-reviewed immutable artifact identity; paths are supplied separately."""

    metadata_sha256: str
    chunks_sha256: str
    vectors_sha256: str
    rows_sha256: str
    corpus_manifest_sha256: str
    chunk_config_sha256: str
    index_config_sha256: str
    embedding_model: str
    count: int
    dimensions: int
    api_profile: str = "mac_local_equivalent"

    def __post_init__(self) -> None:
        for name in (
            "metadata_sha256", "chunks_sha256", "vectors_sha256", "rows_sha256",
            "corpus_manifest_sha256", "chunk_config_sha256", "index_config_sha256",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError("invalid_legacy_artifact_pin")
        positive_int(self.count, "invalid_legacy_artifact_pin")
        positive_int(self.dimensions, "invalid_legacy_artifact_pin")
        if any(not isinstance(value, str) or not value.strip()
               for value in (self.embedding_model, self.api_profile)):
            raise ValueError("invalid_legacy_artifact_pin")


KURE_PAGE_V1_PIN = LegacyPageArtifactPin(
    metadata_sha256="f003b7483f6d6d1d472d4f354d9b477095b3a38de79d6c551a16198319e0b76b",
    chunks_sha256="bb82b593153a93f9373f0bdf7f5be7531e651fdab9c5df36b69d53df0a35b9a2",
    vectors_sha256="a9aa5e8553cc2533101fd050ae48b5af8804ab85c000e57b677bb6a319542556",
    rows_sha256="da403a8dc1bd28c18354e9cedaa45df5e0dcc2dc10eb370aaaa921e787d18738",
    corpus_manifest_sha256="6c91d30a4c01b12f1aae8924c88a2e5055446c841f5eabfbf687546fdc1fe1cb",
    chunk_config_sha256="b4dbcabc483eff0f4193e38fb8e2f3c32748543ce156a4ec0ece7a4f834721cc",
    index_config_sha256="5d2a83397bb08c80995817e78355ea5d34091450cf58e7f00d44095bc383d5f8",
    embedding_model='{"backend":"sentence-transformers","model":"nlpai-lab/KURE-v1",'
                    '"pooling":"sentence-transformers-default","prompt":"",'
                    '"prompt_version":"kure-v1-empty-prompt-v1",'
                    '"revision":"4ed4540949c70b7da2c74004a915e1f2d5e46e4f","role":"document"}',
    count=9331,
    dimensions=1024,
)


def _page_mapping(store: EvidenceStore, chunks: Sequence[dict[str, Any]]) -> tuple[Evidence, ...]:
    if not isinstance(store, EvidenceStore) or isinstance(chunks, (str, bytes, Mapping)):
        raise ValueError("invalid_legacy_page_input")
    if not chunks:
        raise ValueError("empty_legacy_page_index")
    groups: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    seen: set[str] = set()
    configs: set[str] = set()
    for chunk in chunks:
        try:
            validate_chunk(chunk)
        except (TypeError, KeyError, AttributeError):
            raise ValueError("invalid_legacy_page_chunk") from None
        if (chunk["retrieval_role"] != "primary" or chunk["chunker_id"] != "page-v1"
                or chunk["page_start"] != chunk["page_end"]):
            raise ValueError("legacy_page_chunk_required")
        if chunk["chunk_id"] in seen:
            raise ValueError("duplicate_legacy_chunk_id")
        seen.add(chunk["chunk_id"])
        configs.add(chunk["config_sha256"])
        groups[(chunk["doc_id"], chunk["page_start"], chunk["source_block_ids"][0])].append(chunk)
    if len(configs) != 1:
        raise ValueError("mixed_legacy_page_chunk_configs")
    mapping: dict[str, Evidence] = {}
    page_keys: set[tuple[str, int]] = set()
    for (doc_id, page, block_id), parts in groups.items():
        if (doc_id, page) in page_keys:
            raise ValueError("ambiguous_legacy_page_source")
        page_keys.add((doc_id, page))
        parts.sort(key=lambda part: part["part_index"])
        if (len(parts) != parts[0]["part_count"]
                or [part["part_index"] for part in parts] != list(range(len(parts)))
                or any(part["part_count"] != len(parts) for part in parts)
                or any(part["section_path"] != parts[0]["section_path"] for part in parts)):
            raise ValueError("incomplete_or_inconsistent_legacy_page_parts")
        expected = Evidence.create(
            doc_id=doc_id, page=page, kind="page", text="\n\n".join(part["text"] for part in parts),
            source_block_ids=(block_id,), section_path=tuple(parts[0]["section_path"]),
            source_chunk_ids=tuple(part["chunk_id"] for part in parts),
        )
        try:
            actual = store.get(expected.evidence_id)
        except ValueError:
            raise ValueError("legacy_page_evidence_mismatch") from None
        if actual != expected:
            raise ValueError("legacy_page_evidence_mismatch")
        for part in parts:
            mapping[part["chunk_id"]] = actual
    return tuple(mapping[chunk["chunk_id"]] for chunk in chunks)


class LegacyPageRetriever:
    """Exact legacy-part cosine retrieval, max-pooled to validated page parents."""

    score_semantics = "max_legacy_page_part_cosine"
    embedding_unit = "legacy_page_part"
    candidate_unit = "page"

    def __init__(
        self, store: EvidenceStore, chunks: Sequence[dict[str, Any]], vectors: np.ndarray,
        query_embedder: Callable[[str], Sequence[float]], *, lane: str = "dense_page_legacy",
        provenance: Mapping[str, str | int] | None = None,
    ) -> None:
        self.lane = validate_lane(lane)
        self._pages = _page_mapping(store, chunks)
        if not callable(query_embedder):
            raise ValueError("invalid_query_embedder")
        matrix = np.asarray(vectors)
        if (matrix.ndim != 2 or matrix.shape[0] != len(self._pages) or matrix.shape[1] < 1
                or matrix.dtype != np.dtype("float32") or not np.isfinite(matrix).all()):
            raise ValueError("invalid_legacy_page_vectors")
        norms = np.linalg.norm(matrix, axis=1)
        if not np.allclose(norms, 1.0, rtol=0.0, atol=1e-5):
            raise ValueError("legacy_page_vectors_not_normalized")
        # Bytes-backed storage is detached and cannot be made writable by callers.
        self._vectors = np.frombuffer(matrix.tobytes(), dtype=np.float32).reshape(matrix.shape)
        self._query_embedder = query_embedder
        self.dimensions = int(matrix.shape[1])
        self.chunk_count = len(self._pages)
        self.page_count = len({page.evidence_id for page in self._pages})
        self.document_count = len({page.doc_id for page in self._pages})
        self.provenance = MappingProxyType(dict(provenance or {}))

    def search(
        self, query: str, *, limit: int, allowed_doc_ids: frozenset[str] | None = None,
    ) -> tuple[Candidate, ...]:
        validate_query(query)
        positive_int(limit, "invalid_retrieval_limit")
        scope = validate_scope(allowed_doc_ids)
        indices = np.asarray([
            index for index, page in enumerate(self._pages)
            if scope is None or page.doc_id in scope
        ], dtype=np.int64)
        if not indices.size:
            return ()
        try:
            supplied_query = self._query_embedder(query)
            if isinstance(supplied_query, (list, tuple)) and any(
                isinstance(component, (bool, np.bool_)) for component in supplied_query
            ):
                raise ValueError("invalid_query_vector")
            raw_query = np.asarray(supplied_query)
            if (raw_query.shape != (self.dimensions,) or raw_query.dtype.kind not in "iuf"
                    or not np.isfinite(raw_query).all()):
                raise ValueError("invalid_query_vector")
            query_vector = raw_query.astype(np.float64)
            scale = np.max(np.abs(query_vector))
            if not np.isfinite(scale) or scale == 0:
                raise ValueError("invalid_query_vector")
            query_vector = query_vector / scale
            query_vector = (query_vector / np.linalg.norm(query_vector)).astype(np.float32)
        except (TypeError, OverflowError):
            raise ValueError("invalid_query_vector") from None
        # Scope is applied before both embedding and scoring; no global top-k loss.
        scores = self._vectors[indices] @ query_vector
        by_page: dict[str, float] = {}
        for index, score in zip(indices, scores, strict=True):
            evidence_id = self._pages[int(index)].evidence_id
            bounded = max(-1.0, min(1.0, float(score)))
            by_page[evidence_id] = max(by_page.get(evidence_id, -1.0), bounded)
        ranked = sorted(by_page.items(), key=lambda item: (-item[1], item[0]))[:limit]
        return tuple(Candidate(evidence_id, score, self.lane, rank)
                     for rank, (evidence_id, score) in enumerate(ranked, 1))


def _pinned_bytes(path: Path, expected: str, code: str) -> bytes:
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected:
        raise ValueError(code)
    return payload


def _json_lines(payload: bytes) -> list[Any]:
    try:
        return [json.loads(line) for line in payload.decode("utf-8").splitlines() if line.strip()]
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("invalid_legacy_artifact_json") from None


def read_pinned_page_chunks(
    chunks_path: Path, *, pin: LegacyPageArtifactPin = KURE_PAGE_V1_PIN,
) -> tuple[dict[str, Any], ...]:
    """Read only the pinned primary chunks; useful before constructing the store."""
    if not isinstance(pin, LegacyPageArtifactPin):
        raise ValueError("invalid_legacy_artifact_pin")
    pin.__post_init__()
    chunks = _json_lines(_pinned_bytes(Path(chunks_path), pin.chunks_sha256, "legacy_chunks_hash_mismatch"))
    if len(chunks) != pin.count or chunk_artifact_sha256(chunks) != pin.chunks_sha256:
        raise ValueError("legacy_chunk_artifact_mismatch")
    for chunk in chunks:
        try:
            validate_chunk(chunk)
        except (TypeError, KeyError, AttributeError):
            raise ValueError("invalid_legacy_page_chunk") from None
        if (chunk["config_sha256"] != pin.chunk_config_sha256
                or chunk["chunker_id"] != "page-v1" or chunk["retrieval_role"] != "primary"
                or chunk["page_start"] != chunk["page_end"]):
            raise ValueError("legacy_chunk_config_mismatch")
    return tuple(chunks)


def load_legacy_page_retriever(
    store: EvidenceStore, *, index_dir: Path, chunks_path: Path,
    query_embedder: Callable[[str], Sequence[float]],
    pin: LegacyPageArtifactPin = KURE_PAGE_V1_PIN, lane: str = "dense_page_legacy",
) -> LegacyPageRetriever:
    """Verify complete in-memory artifact snapshots without creating a lock file.

    Hashes bind the exact bytes parsed, including the NPY payload. No mutable file
    is reopened after verification. The source directory may be read-only.
    """
    if not isinstance(pin, LegacyPageArtifactPin):
        raise ValueError("invalid_legacy_artifact_pin")
    pin.__post_init__()
    metadata_bytes = _pinned_bytes(Path(index_dir) / "metadata.json", pin.metadata_sha256,
                                   "legacy_metadata_hash_mismatch")
    try:
        metadata = json.loads(metadata_bytes)
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("invalid_legacy_index_metadata") from None
    expected_metadata = {
        "schema_version": "1.0", "engine": "numpy",
        "metric": "cosine_via_normalized_inner_product", "count": pin.count,
        "dimensions": pin.dimensions, "embedding_model": pin.embedding_model,
        "corpus_manifest_sha256": pin.corpus_manifest_sha256,
        "chunk_config_sha256": pin.chunk_config_sha256, "chunk_artifact_sha256": pin.chunks_sha256,
        "vectors_sha256": pin.vectors_sha256, "rows_sha256": pin.rows_sha256,
        "index_sha256": None, "api_profile": pin.api_profile,
        "index_config_sha256": pin.index_config_sha256,
    }
    if metadata != expected_metadata or any(type(metadata[name]) is not int for name in ("count", "dimensions")):
        raise ValueError("legacy_index_metadata_mismatch")
    chunks = read_pinned_page_chunks(chunks_path, pin=pin)
    rows = _json_lines(_pinned_bytes(Path(index_dir) / "rows.jsonl", pin.rows_sha256, "legacy_rows_hash_mismatch"))
    if rows != [{"chunk_id": chunk.get("chunk_id"), "doc_id": chunk.get("doc_id")}
                for chunk in chunks if isinstance(chunk, dict)]:
        raise ValueError("legacy_rows_alignment_mismatch")
    if any(not isinstance(chunk, dict) or chunk.get("config_sha256") != pin.chunk_config_sha256
           for chunk in chunks):
        raise ValueError("legacy_chunk_config_mismatch")
    vectors_bytes = _pinned_bytes(Path(index_dir) / "vectors.npy", pin.vectors_sha256, "legacy_vectors_hash_mismatch")
    try:
        vectors = np.load(io.BytesIO(vectors_bytes), allow_pickle=False)
    except (ValueError, TypeError, OSError):
        raise ValueError("invalid_legacy_vector_artifact") from None
    if not isinstance(vectors, np.ndarray) or vectors.shape != (pin.count, pin.dimensions):
        raise ValueError("legacy_vector_shape_mismatch")
    return LegacyPageRetriever(
        store, chunks, vectors, query_embedder, lane=lane,
        provenance={
            "metadata_sha256": pin.metadata_sha256, "chunks_sha256": pin.chunks_sha256,
            "vectors_sha256": pin.vectors_sha256, "rows_sha256": pin.rows_sha256,
            "index_config_sha256": pin.index_config_sha256, "embedding_model": pin.embedding_model,
            "count": pin.count, "dimensions": pin.dimensions,
            "retrieval_kind": "page_parent_maxpool", "embedding_unit": "legacy_page_part",
        },
    )
