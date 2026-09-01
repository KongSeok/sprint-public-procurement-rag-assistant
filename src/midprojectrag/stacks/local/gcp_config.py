from __future__ import annotations

from typing import Any, Mapping

from midprojectrag.ingest.common import canonical_json, require_sha256, sha256_text


KURE_MODEL_ID = "nlpai-lab/KURE-v1"
KURE_MODEL_REVISION = "4ed4540949c70b7da2c74004a915e1f2d5e46e4f"
KURE_DIMENSIONS = 1024
KURE_MAX_INPUT_TOKENS = 8192
KURE_POOLING = "sentence-transformers-default"
KURE_PROMPT_VERSION = "kure-v1-empty-prompt-v1"
KURE_DOCUMENT_PROMPT = ""
KURE_QUERY_PROMPT = ""
GCP_LOCAL_STACK_ID = "gcp_local"
GCP_INDEX_ENGINE = "faiss"


def gcp_config_sha256(config: Mapping[str, Any]) -> str:
    return sha256_text(canonical_json(dict(config)))


def _require_exact(value: Any, expected: Any, error_code: str) -> None:
    if value != expected or type(value) is not type(expected):
        raise ValueError(error_code)


def build_gcp_index_config(
    *,
    corpus_manifest_sha256: str,
    chunk_artifact_sha256: str,
    chunk_config_sha256: str,
    embedding_model: str = KURE_MODEL_ID,
    embedding_revision: str = KURE_MODEL_REVISION,
    embedding_dimensions: int = KURE_DIMENSIONS,
    embedding_max_input_tokens: int = KURE_MAX_INPUT_TOKENS,
    pooling: str = KURE_POOLING,
    prompt_version: str = KURE_PROMPT_VERSION,
    document_prompt: str = KURE_DOCUMENT_PROMPT,
    query_prompt: str = KURE_QUERY_PROMPT,
    index_engine: str = GCP_INDEX_ENGINE,
    batch_size: int = 32,
) -> dict[str, Any]:
    """Build the immutable semantic-index identity for the GCP baseline."""

    require_sha256(corpus_manifest_sha256, "invalid_corpus_manifest_hash")
    require_sha256(chunk_artifact_sha256, "invalid_chunk_artifact_hash")
    require_sha256(chunk_config_sha256, "invalid_chunk_config_hash")
    _require_exact(embedding_model, KURE_MODEL_ID, "embedding_model_not_allowlisted")
    _require_exact(
        embedding_revision,
        KURE_MODEL_REVISION,
        "embedding_revision_not_allowlisted",
    )
    _require_exact(
        embedding_dimensions,
        KURE_DIMENSIONS,
        "invalid_embedding_dimensions",
    )
    _require_exact(
        embedding_max_input_tokens,
        KURE_MAX_INPUT_TOKENS,
        "invalid_embedding_input_limit",
    )
    _require_exact(pooling, KURE_POOLING, "embedding_pooling_not_allowlisted")
    _require_exact(
        prompt_version,
        KURE_PROMPT_VERSION,
        "embedding_prompt_version_not_allowlisted",
    )
    _require_exact(
        document_prompt,
        KURE_DOCUMENT_PROMPT,
        "embedding_prompt_not_allowlisted",
    )
    _require_exact(
        query_prompt,
        KURE_QUERY_PROMPT,
        "embedding_prompt_not_allowlisted",
    )
    _require_exact(index_engine, GCP_INDEX_ENGINE, "unsupported_index_engine")
    if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size < 1:
        raise ValueError("invalid_embedding_batch_size")
    return {
        "schema_version": "1.0",
        "stack_id": GCP_LOCAL_STACK_ID,
        "corpus_manifest_sha256": corpus_manifest_sha256,
        "chunk_artifact_sha256": chunk_artifact_sha256,
        "chunk_config_sha256": chunk_config_sha256,
        "embedding_model": embedding_model,
        "embedding_revision": embedding_revision,
        "embedding_dimensions": embedding_dimensions,
        "embedding_max_input_tokens": embedding_max_input_tokens,
        "pooling": pooling,
        "prompt_version": prompt_version,
        "document_prompt": document_prompt,
        "query_prompt": query_prompt,
        "local_files_only": True,
        "trust_remote_code": False,
        "normalization": "float32_l2",
        "index_engine": index_engine,
        "batch_size": batch_size,
    }
