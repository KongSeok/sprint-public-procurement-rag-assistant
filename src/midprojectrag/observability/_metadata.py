from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any


ALLOWED_OBSERVATION_NAMES = frozenset(
    {
        "rag.query",
        "scope.resolve",
        "embed.query",
        "retrieve.dense",
        "context.build",
        "generate.answer",
        "contract.validate",
        "rag.index.build",
        "chunk.page",
        "embed.documents",
        "index.persist",
    }
)

ALLOWED_OBSERVATION_TYPES = frozenset(
    {"span", "chain", "embedding", "retriever", "generation", "guardrail"}
)

_IDENTIFIER_KEYS = frozenset(
    {
        "schema_version",
        "request_id",
        "trace_id",
        "run_id",
        "case_id",
        "stack_id",
        "api_profile",
        "stage",
        "scope_mode",
        "embedding_model",
        "generator_model",
        "index_type",
        "metric_name",
        "error_code",
        "environment",
        "region",
        "machine_type",
        "git_commit",
    }
)
_HASH_KEYS = frozenset(
    {"corpus_manifest_sha256", "eval_set_sha256", "config_sha256", "index_config_sha256"}
)
_ENUM_VALUES = {
    "status": frozenset({"started", "completed", "answered", "abstained", "error"}),
    "abstention_reason": frozenset({"insufficient_evidence", "ambiguous", "out_of_scope"}),
}
_NONNEGATIVE_INTEGER_KEYS = frozenset(
    {
        "top_k",
        "candidate_count",
        "retrieval_count",
        "context_count",
        "citation_count",
        "document_count",
        "history_turn_count",
        "max_citations",
        "chunk_count",
        "batch_size",
        "rank",
        "input_tokens",
        "output_tokens",
        "embedding_tokens",
        "embedding_dimensions",
        "cache_hits",
        "cache_misses",
        "vcpu",
    }
)
_NONNEGATIVE_NUMBER_KEYS = frozenset(
    {
        "duration_ms",
        "latency_ms",
        "retrieval_ms",
        "generation_ms",
        "total_ms",
        "cost_usd",
        "gpu_seconds",
        "peak_vram_gb",
        "ram_gb",
        "disk_gb",
    }
)
_FINITE_NUMBER_KEYS = frozenset({"score"})
_BOOLEAN_KEYS = frozenset({"cache_hit", "abstained", "contract_valid", "success"})
_IDENTIFIER_LIST_KEYS = frozenset({"doc_ids", "chunk_ids", "source_block_ids"})

SAFE_METADATA_KEYS = frozenset(
    _IDENTIFIER_KEYS
    | _HASH_KEYS
    | frozenset(_ENUM_VALUES)
    | _NONNEGATIVE_INTEGER_KEYS
    | _NONNEGATIVE_NUMBER_KEYS
    | _FINITE_NUMBER_KEYS
    | _BOOLEAN_KEYS
    | _IDENTIFIER_LIST_KEYS
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_REQUEST_ID_RE = re.compile(r"^req_[0-9a-f]{24}$")
_RUN_ID_RE = re.compile(r"^run_[0-9a-f]{24}$")
_CASE_ID_RE = re.compile(r"^(?:dev|heldout)-(?:single|multi|followup|unknown)-[0-9]{3}$")
_DOC_ID_RE = re.compile(r"^doc_[0-9a-f]{24}$")
_CHUNK_ID_RE = re.compile(r"^chunk_[0-9a-f]{24}$")
_BLOCK_ID_RE = re.compile(r"^block_[0-9a-f]{24}$")
_ERROR_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_GIT_COMMIT_RE = re.compile(r"^(?:uncommitted|[0-9a-f]{7,64})$")

_IDENTIFIER_ENUMS = {
    "schema_version": frozenset({"1.0"}),
    "stack_id": frozenset({"api", "gcp_local", "mac_local_experimental"}),
    "api_profile": frozenset({"assignment", "personal_experimental"}),
    "stage": frozenset({"chunk", "index", "query", "evaluation"}),
    "scope_mode": frozenset({"all", "explicit"}),
    "embedding_model": frozenset(
        {"text-embedding-3-small", "text-embedding-3-large", "local-hash-char-v1"}
    ),
    "generator_model": frozenset({"gpt-5-mini", "gpt-5-nano", "qwen3.8:27b-mlx"}),
    "index_type": frozenset({"faiss", "numpy", "IndexFlatIP"}),
    "metric_name": frozenset(
        {
            "correctness",
            "faithfulness",
            "factual_claim_coverage",
            "citation_validity",
            "follow_up_success",
            "safe_abstention",
            "document_recall_at_5",
            "mrr_at_10",
            "all_required_docs_at_10",
            "task_success",
        }
    ),
    "environment": frozenset({"api_local", "gcp_local", "synthetic_test"}),
    "region": frozenset({"us-central1", "us-east1", "local-test"}),
    "machine_type": frozenset({"g2-standard-4", "local-test"}),
}

_IDENTIFIER_PATTERNS = {
    "request_id": _REQUEST_ID_RE,
    "trace_id": _TRACE_ID_RE,
    "run_id": _RUN_ID_RE,
    "case_id": _CASE_ID_RE,
    "error_code": _ERROR_CODE_RE,
    "git_commit": _GIT_COMMIT_RE,
}

_LIST_PATTERNS = {
    "doc_ids": _DOC_ID_RE,
    "chunk_ids": _CHUNK_ID_RE,
    "source_block_ids": _BLOCK_ID_RE,
}

ALLOWED_SCORE_NAMES = frozenset(
    {
        "correctness",
        "faithfulness",
        "factual_claim_coverage",
        "citation_validity",
        "follow_up_success",
        "safe_abstention",
        "document_recall_at_5",
        "mrr_at_10",
        "all_required_docs_at_10",
        "task_success",
    }
)


def valid_observation_name(value: object) -> bool:
    return isinstance(value, str) and value in ALLOWED_OBSERVATION_NAMES


def valid_observation_type(value: object) -> bool:
    return isinstance(value, str) and value in ALLOWED_OBSERVATION_TYPES


def valid_trace_id(value: object) -> bool:
    return isinstance(value, str) and _TRACE_ID_RE.fullmatch(value) is not None


def valid_score(name: object, value: object) -> bool:
    if not isinstance(name, str) or name not in ALLOWED_SCORE_NAMES:
        return False
    if isinstance(value, bool):
        return True
    return _is_finite_number(value) and 0 <= value <= 1


def sanitize_metadata(value: object) -> dict[str, Any]:
    """Return metadata only when the complete payload is explicitly safe.

    Unknown keys, raw text payloads, malformed values, non-finite numbers and
    oversized identifier lists cause the entire payload to be rejected. It
    never stringifies arbitrary objects because doing so could disclose source
    or user content through ``repr``/``str``.
    """
    safe = safe_metadata_or_none(value)
    return safe if safe is not None else {}


def safe_observation_io_or_none(value: object | None) -> dict[str, Any] | None:
    """Validate privacy-safe observation input/output without stringifying it.

    Observation I/O intentionally uses the same narrow field allowlist as
    metadata. Raw questions, history, prompts, source text and generated
    answers therefore cannot reach a sink through the I/O fields either.
    ``None`` means that no I/O value should be emitted.
    """

    if value is None:
        return None
    return safe_metadata_or_none(value)


def safe_metadata_or_none(value: object) -> dict[str, Any] | None:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        return None
    sanitized: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str) or key not in SAFE_METADATA_KEYS:
            return None
        clean = _sanitize_value(key, item)
        if clean is _DROP:
            return None
        sanitized[key] = clean
    return sanitized


class _Drop:
    pass


_DROP = _Drop()


def _sanitize_value(key: str, value: object) -> Any:
    if key in _IDENTIFIER_KEYS:
        allowed = _IDENTIFIER_ENUMS.get(key)
        pattern = _IDENTIFIER_PATTERNS.get(key)
        if isinstance(value, str) and (
            (allowed is not None and value in allowed)
            or (pattern is not None and pattern.fullmatch(value) is not None)
        ):
            return value
        return _DROP
    if key in _HASH_KEYS:
        if isinstance(value, str) and _SHA256_RE.fullmatch(value):
            return value
        return _DROP
    if key in _ENUM_VALUES:
        if isinstance(value, str) and value in _ENUM_VALUES[key]:
            return value
        return _DROP
    if key in _NONNEGATIVE_INTEGER_KEYS:
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return _DROP
    if key in _NONNEGATIVE_NUMBER_KEYS:
        if _is_finite_number(value) and value >= 0:
            return value
        return _DROP
    if key in _FINITE_NUMBER_KEYS:
        if _is_finite_number(value):
            return value
        return _DROP
    if key in _BOOLEAN_KEYS:
        if isinstance(value, bool):
            return value
        return _DROP
    if key in _IDENTIFIER_LIST_KEYS:
        if not isinstance(value, (list, tuple)) or len(value) > 50:
            return _DROP
        result: list[str] = []
        pattern = _LIST_PATTERNS[key]
        for item in value:
            if not isinstance(item, str) or pattern.fullmatch(item) is None:
                return _DROP
            result.append(item)
        return result
    return _DROP


def _is_finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
