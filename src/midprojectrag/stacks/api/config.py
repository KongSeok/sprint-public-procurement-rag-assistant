from __future__ import annotations

import math
from typing import Any, Mapping

from midprojectrag.ingest.common import canonical_json, require_sha256, sha256_text

from .embeddings import (
    OPENAI_API_PROFILES,
    OPENAI_EMBEDDING_MAX_TOKENS,
    OPENAI_EMBEDDING_MODEL_SPECS,
    resolve_embedding_dimensions,
)
from .generation import (
    ALLOWED_GENERATOR_MODELS,
    DEFAULT_REASONING_EFFORT,
    DEFAULT_SDK_MAX_RETRIES,
)


API_PROFILE_ASSIGNMENT = "assignment"
API_PROFILE_PERSONAL_EXPERIMENTAL = "personal_experimental"


def _positive_int(value: int, error_code: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(error_code)
    return value


def api_config_sha256(config: Mapping[str, Any]) -> str:
    return sha256_text(canonical_json(dict(config)))


def build_api_index_config(
    *,
    api_profile: str,
    corpus_manifest_sha256: str,
    chunk_artifact_sha256: str,
    chunk_config_sha256: str,
    embedding_model: str,
    embedding_dimensions: int | None,
    index_engine: str,
    batch_size: int,
) -> dict[str, Any]:
    models = OPENAI_API_PROFILES.get(api_profile)
    if models is None:
        raise ValueError("api_profile_not_allowlisted")
    if embedding_model not in models:
        raise ValueError("embedding_model_not_allowlisted")
    dimensions = resolve_embedding_dimensions(embedding_model, embedding_dimensions)
    require_sha256(corpus_manifest_sha256, "invalid_corpus_manifest_hash")
    require_sha256(chunk_artifact_sha256, "invalid_chunk_artifact_hash")
    require_sha256(chunk_config_sha256, "invalid_chunk_config_hash")
    if index_engine not in {"faiss", "numpy"}:
        raise ValueError("unsupported_index_engine")
    _positive_int(batch_size, "invalid_embedding_batch_size")
    spec = OPENAI_EMBEDDING_MODEL_SPECS[embedding_model]
    return {
        "schema_version": "1.0",
        "api_profile": api_profile,
        "corpus_manifest_sha256": corpus_manifest_sha256,
        "chunk_artifact_sha256": chunk_artifact_sha256,
        "chunk_config_sha256": chunk_config_sha256,
        "embedding_model": embedding_model,
        "embedding_dimensions": dimensions,
        "embedding_max_dimensions": spec.max_dimensions,
        "embedding_max_input_tokens": OPENAI_EMBEDDING_MAX_TOKENS,
        "normalization": "float32_l2",
        "index_engine": index_engine,
        "batch_size": batch_size,
    }


def build_api_run_config(
    *,
    index_config_sha256: str,
    generator_model: str,
    retrieval_top_k: int,
    context_top_k: int,
    max_output_tokens: int,
    max_citations: int,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
    case_interval_seconds: float = 6.0,
    prompt_version: str = "api-b0-page-v1",
) -> dict[str, Any]:
    require_sha256(index_config_sha256, "invalid_index_config_hash")
    if generator_model not in ALLOWED_GENERATOR_MODELS:
        raise ValueError("generator_model_not_allowlisted")
    for value, error_code in (
        (retrieval_top_k, "invalid_retrieval_top_k"),
        (context_top_k, "invalid_context_top_k"),
        (max_output_tokens, "invalid_max_output_tokens"),
        (max_citations, "invalid_max_citations"),
    ):
        _positive_int(value, error_code)
    if context_top_k > retrieval_top_k:
        raise ValueError("invalid_retrieval_context_limits")
    if reasoning_effort != DEFAULT_REASONING_EFFORT:
        raise ValueError("reasoning_effort_not_supported")
    if prompt_version not in {"api-b0-page-v1", "api-b1-page-table-v1"}:
        raise ValueError("prompt_version_not_allowlisted")
    if (
        not isinstance(case_interval_seconds, (int, float))
        or isinstance(case_interval_seconds, bool)
        or not math.isfinite(case_interval_seconds)
        or case_interval_seconds < 0
    ):
        raise ValueError("invalid_case_interval_seconds")
    return {
        "schema_version": "1.0",
        "index_config_sha256": index_config_sha256,
        "generator_model": generator_model,
        "retrieval_top_k": retrieval_top_k,
        "context_top_k": context_top_k,
        "max_output_tokens": max_output_tokens,
        "max_citations": max_citations,
        "reasoning_effort": reasoning_effort,
        "case_interval_seconds": float(case_interval_seconds),
        "sdk_max_retries": DEFAULT_SDK_MAX_RETRIES,
        "prompt_version": prompt_version,
        "response_schema_version": "1.2",
        "abstention_policy_version": "citation-safe-v1",
    }
