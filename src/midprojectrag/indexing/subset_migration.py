from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from midprojectrag.ingest.common import (
    canonical_json,
    read_jsonl,
    require_sha256,
    sha256_file,
    sha256_text,
    write_json,
)
from midprojectrag.indexing.chunking import chunk_artifact_sha256, validate_chunk
from midprojectrag.indexing.exact_index import ExactDenseIndex


_PAGE_SIDECAR_FIELDS = {
    "schema_version",
    "source_manifest_sha256",
    "chunk_artifact_sha256",
    "config_sha256",
    "documents",
    "chunks",
}
_INDEX_CONFIG_FIELDS = {
    "schema_version",
    "api_profile",
    "corpus_manifest_sha256",
    "chunk_artifact_sha256",
    "chunk_config_sha256",
    "embedding_model",
    "embedding_dimensions",
    "embedding_max_dimensions",
    "embedding_max_input_tokens",
    "normalization",
    "index_engine",
    "batch_size",
}


@dataclass(frozen=True)
class SubsetMigrationResult:
    metadata: dict[str, Any]
    index_config: dict[str, Any]
    provenance: dict[str, Any]
    provenance_sha256: str


def _config_sha256(config: dict[str, Any]) -> str:
    return sha256_text(canonical_json(config))


def _validated_index_config(config: dict[str, Any]) -> dict[str, Any]:
    if set(config) != _INDEX_CONFIG_FIELDS or config.get("schema_version") != "1.0":
        raise ValueError("invalid_source_index_config")
    for key in ("api_profile", "embedding_model"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError("invalid_source_index_config")
    for key in (
        "corpus_manifest_sha256",
        "chunk_artifact_sha256",
        "chunk_config_sha256",
    ):
        require_sha256(config.get(key), "invalid_source_index_config")
    for key in (
        "embedding_dimensions",
        "embedding_max_dimensions",
        "embedding_max_input_tokens",
        "batch_size",
    ):
        value = config.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError("invalid_source_index_config")
    if config["embedding_dimensions"] > config["embedding_max_dimensions"]:
        raise ValueError("invalid_source_index_config")
    if config.get("normalization") != "float32_l2":
        raise ValueError("invalid_source_index_config")
    if config.get("index_engine") not in {"faiss", "numpy"}:
        raise ValueError("invalid_source_index_config")
    return dict(config)


def _read_object(path: Path, error_code: str) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as source:
            value = json.load(source)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(error_code) from error
    if not isinstance(value, dict):
        raise ValueError(error_code)
    return value


def _unique_page_contract(
    chunks: Sequence[dict[str, Any]],
    *,
    empty_error: str,
    duplicate_error: str,
) -> tuple[str, str, str]:
    if not chunks:
        raise ValueError(empty_error)
    seen: set[str] = set()
    contracts: set[tuple[str, str, str]] = set()
    for chunk in chunks:
        validate_chunk(chunk)
        chunk_id = chunk.get("chunk_id")
        if not isinstance(chunk_id, str) or not chunk_id or chunk_id in seen:
            raise ValueError(duplicate_error)
        seen.add(chunk_id)
        contracts.add(
            (
                chunk["retrieval_role"],
                chunk["chunker_id"],
                chunk["config_sha256"],
            )
        )
    if len(contracts) != 1:
        raise ValueError("mixed_page_chunk_contracts")
    contract = next(iter(contracts))
    if contract[:2] != ("primary", "page-v1"):
        raise ValueError("page_chunk_lane_required")
    return contract


def _verified_source_index(
    source_index_dir: Path,
    source_chunks: Sequence[dict[str, Any]],
) -> tuple[ExactDenseIndex, dict[str, Any], dict[str, Any]]:
    index_config_path = source_index_dir / "index-config.json"
    metadata_path = source_index_dir / "metadata.json"
    index_config = _read_object(index_config_path, "source_index_config_read_failed")
    metadata = _read_object(metadata_path, "source_index_metadata_read_failed")

    index_config = _validated_index_config(index_config)

    index_config_hash = _config_sha256(index_config)
    source_chunk_hash = chunk_artifact_sha256(source_chunks)
    expected_metadata = {
        "engine": index_config["index_engine"],
        "dimensions": index_config["embedding_dimensions"],
        "embedding_model": index_config["embedding_model"],
        "corpus_manifest_sha256": index_config["corpus_manifest_sha256"],
        "chunk_config_sha256": index_config["chunk_config_sha256"],
        "chunk_artifact_sha256": source_chunk_hash,
        "api_profile": index_config["api_profile"],
        "index_config_sha256": index_config_hash,
    }
    if any(metadata.get(key) != value for key, value in expected_metadata.items()):
        raise ValueError("source_index_contract_mismatch")
    if index_config["chunk_artifact_sha256"] != source_chunk_hash:
        raise ValueError("source_index_chunk_hash_mismatch")

    try:
        index = ExactDenseIndex.load(
            source_index_dir,
            source_chunks,
            expected_embedding_model=index_config["embedding_model"],
            expected_dimensions=index_config["embedding_dimensions"],
            expected_api_profile=index_config["api_profile"],
            expected_index_config_sha256=index_config_hash,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RuntimeError) as error:
        raise ValueError("source_index_verification_failed") from error
    return index, index_config, metadata


def _verify_target_sidecar(
    *,
    target_chunks_path: Path,
    target_chunks: Sequence[dict[str, Any]],
    target_chunk_metadata_path: Path,
    target_manifest_sha256: str,
) -> dict[str, Any]:
    sidecar = _read_object(target_chunk_metadata_path, "target_chunk_metadata_read_failed")
    if set(sidecar) != _PAGE_SIDECAR_FIELDS or sidecar.get("schema_version") != "1.0":
        raise ValueError("invalid_target_chunk_metadata")
    canonical_chunk_hash = chunk_artifact_sha256(target_chunks)
    expected = {
        "source_manifest_sha256": target_manifest_sha256,
        "chunk_artifact_sha256": canonical_chunk_hash,
        "config_sha256": target_chunks[0]["config_sha256"],
        "documents": len({chunk["doc_id"] for chunk in target_chunks}),
        "chunks": len(target_chunks),
    }
    if any(sidecar.get(key) != value for key, value in expected.items()):
        raise ValueError("target_chunk_metadata_mismatch")
    if sha256_file(target_chunks_path) != canonical_chunk_hash:
        raise ValueError("target_chunk_file_not_canonical")
    return sidecar


def _verify_target_manifest(
    target_manifest_path: Path,
    target_manifest_sha256: str,
    target_chunks: Sequence[dict[str, Any]],
) -> None:
    require_sha256(target_manifest_sha256, "invalid_target_manifest_hash")
    if sha256_file(target_manifest_path) != target_manifest_sha256:
        raise ValueError("target_manifest_hash_mismatch")
    manifest = read_jsonl(target_manifest_path)
    eligible_doc_ids: set[str] = set()
    seen_doc_ids: set[str] = set()
    for row in manifest:
        doc_id = row.get("doc_id")
        if not isinstance(doc_id, str) or not doc_id or doc_id in seen_doc_ids:
            raise ValueError("invalid_target_manifest_documents")
        seen_doc_ids.add(doc_id)
        if row.get("status") == "ok" and row.get("index_eligible") is True:
            eligible_doc_ids.add(doc_id)
    if not eligible_doc_ids or {chunk["doc_id"] for chunk in target_chunks} != eligible_doc_ids:
        raise ValueError("target_manifest_document_mismatch")


def migrate_api_exact_index_subset(
    *,
    source_chunks_path: Path,
    source_index_dir: Path,
    target_chunks_path: Path,
    target_chunk_metadata_path: Path,
    target_manifest_path: Path,
    target_manifest_sha256: str,
    output_dir: Path,
) -> SubsetMigrationResult:
    """Reuse verified API vectors for a byte-identical page-chunk subset.

    This function is entirely local. It never constructs an embedding provider
    and has no network path. All validation finishes before an atomic target
    directory is published.
    """

    if output_dir.exists():
        raise ValueError("migration_output_already_exists")
    source_chunks = read_jsonl(source_chunks_path)
    target_chunks = read_jsonl(target_chunks_path)
    if sha256_file(source_chunks_path) != chunk_artifact_sha256(source_chunks):
        raise ValueError("source_chunk_file_not_canonical")
    source_contract = _unique_page_contract(
        source_chunks,
        empty_error="empty_source_chunks",
        duplicate_error="duplicate_source_chunk_id",
    )
    target_contract = _unique_page_contract(
        target_chunks,
        empty_error="empty_target_chunks",
        duplicate_error="duplicate_target_chunk_id",
    )
    if target_contract != source_contract:
        raise ValueError("target_page_chunk_contract_mismatch")

    _verify_target_manifest(
        target_manifest_path,
        target_manifest_sha256,
        target_chunks,
    )
    _verify_target_sidecar(
        target_chunks_path=target_chunks_path,
        target_chunks=target_chunks,
        target_chunk_metadata_path=target_chunk_metadata_path,
        target_manifest_sha256=target_manifest_sha256,
    )
    source_index, source_config, source_metadata = _verified_source_index(
        source_index_dir,
        source_chunks,
    )
    if source_config["chunk_config_sha256"] != source_contract[2]:
        raise ValueError("source_page_chunk_config_mismatch")

    source_rows: dict[str, tuple[int, str]] = {}
    for row_index, chunk in enumerate(source_chunks):
        source_rows[chunk["chunk_id"]] = (row_index, canonical_json(chunk))
    selected_rows: list[int] = []
    selection: list[dict[str, Any]] = []
    for target_row, chunk in enumerate(target_chunks):
        source = source_rows.get(chunk["chunk_id"])
        if source is None:
            raise ValueError("target_chunk_missing_from_source")
        source_row, source_bytes = source
        if canonical_json(chunk) != source_bytes:
            raise ValueError("target_chunk_not_byte_identical")
        selected_rows.append(source_row)
        selection.append(
            {
                "chunk_id": chunk["chunk_id"],
                "source_row": source_row,
                "target_row": target_row,
            }
        )

    selected_vectors = np.ascontiguousarray(
        source_index.vectors[np.asarray(selected_rows, dtype=np.int64)],
        dtype=np.float32,
    )
    target_config = dict(source_config)
    target_config["corpus_manifest_sha256"] = target_manifest_sha256
    target_config["chunk_artifact_sha256"] = chunk_artifact_sha256(target_chunks)
    target_config_hash = _config_sha256(target_config)
    target_index = ExactDenseIndex.from_normalized_vectors(
        target_chunks,
        selected_vectors,
        engine=source_config["index_engine"],
    )
    if (
        target_index.dimensions != source_index.dimensions
        or target_config["api_profile"] != source_config["api_profile"]
        or target_config["embedding_model"] != source_config["embedding_model"]
        or target_config["chunk_config_sha256"] != source_config["chunk_config_sha256"]
    ):
        raise ValueError("migrated_index_contract_mismatch")

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.migration.", dir=output_dir.parent)
    )
    published = False
    try:
        target_metadata = target_index.save(
            temporary,
            corpus_manifest_sha256=target_manifest_sha256,
            embedding_model=source_config["embedding_model"],
            api_profile=source_config["api_profile"],
            index_config_sha256=target_config_hash,
        )
        write_json(temporary / "index-config.json", target_config)
        provenance = {
            "schema_version": "1.0",
            "migration": "exact-dense-byte-identical-subset-v1",
            "network_access": False,
            "source": {
                "chunks_file_sha256": sha256_file(source_chunks_path),
                "chunk_artifact_sha256": chunk_artifact_sha256(source_chunks),
                "index_config_file_sha256": sha256_file(source_index_dir / "index-config.json"),
                "index_config_sha256": _config_sha256(source_config),
                "index_metadata_file_sha256": sha256_file(source_index_dir / "metadata.json"),
                "vectors_sha256": source_metadata["vectors_sha256"],
                "rows_sha256": source_metadata["rows_sha256"],
                "index_sha256": source_metadata["index_sha256"],
                "count": len(source_chunks),
            },
            "target": {
                "manifest_sha256": target_manifest_sha256,
                "chunks_file_sha256": sha256_file(target_chunks_path),
                "chunk_metadata_file_sha256": sha256_file(target_chunk_metadata_path),
                "chunk_artifact_sha256": chunk_artifact_sha256(target_chunks),
                "index_config_file_sha256": sha256_file(temporary / "index-config.json"),
                "index_config_sha256": target_config_hash,
                "index_metadata_file_sha256": sha256_file(temporary / "metadata.json"),
                "vectors_sha256": target_metadata["vectors_sha256"],
                "rows_sha256": target_metadata["rows_sha256"],
                "index_sha256": target_metadata["index_sha256"],
                "count": len(target_chunks),
            },
            "contract": {
                "retrieval_role": source_contract[0],
                "chunker_id": source_contract[1],
                "chunk_config_sha256": source_contract[2],
                "embedding_model": source_config["embedding_model"],
                "embedding_dimensions": source_config["embedding_dimensions"],
                "api_profile": source_config["api_profile"],
                "index_engine": source_config["index_engine"],
            },
            "selection_sha256": sha256_text(canonical_json(selection)),
            "selected_count": len(selection),
            "removed_count": len(source_chunks) - len(target_chunks),
        }
        write_json(temporary / "migration-provenance.json", provenance)
        provenance_sha256 = sha256_file(temporary / "migration-provenance.json")
        os.rename(temporary, output_dir)
        published = True
    finally:
        if not published:
            shutil.rmtree(temporary, ignore_errors=True)

    return SubsetMigrationResult(
        metadata=target_metadata,
        index_config=target_config,
        provenance=provenance,
        provenance_sha256=provenance_sha256,
    )


__all__ = ["SubsetMigrationResult", "migrate_api_exact_index_subset"]
