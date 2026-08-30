from __future__ import annotations

import os
import tempfile
import time
import math
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol, Sequence

import numpy as np

from midprojectrag.ingest.common import canonical_json, require_sha256, sha256_text
from midprojectrag.indexing.budget import Budget
from midprojectrag.indexing.chunking import validate_chunk


@dataclass(frozen=True)
class EmbeddingBatch:
    vectors: Sequence[Sequence[float]]
    input_tokens: int | None


class EmbeddingProvider(Protocol):
    model: str
    dimensions: int
    requires_budget: bool
    max_input_tokens: int

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch: ...

    def estimate_cost(self, input_tokens: int) -> Decimal: ...


class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...


class EmbeddingCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    @staticmethod
    def key(
        *,
        corpus_manifest_sha256: str,
        chunk_config_sha256: str,
        model: str,
        dimensions: int,
        content_sha256: str,
    ) -> str:
        return sha256_text(
            canonical_json(
                {
                    "chunk_config_sha256": chunk_config_sha256,
                    "content_sha256": content_sha256,
                    "corpus_manifest_sha256": corpus_manifest_sha256,
                    "dimensions": dimensions,
                    "model": model,
                }
            )
        )

    def _path(self, key: str) -> Path:
        if len(key) != 64 or any(character not in "0123456789abcdef" for character in key):
            raise ValueError("invalid_embedding_cache_key")
        return self.root / key[:2] / f"{key}.npy"

    def get(self, key: str, dimensions: int) -> np.ndarray | None:
        path = self._path(key)
        if not path.is_file():
            return None
        vector = np.load(path, allow_pickle=False)
        if vector.shape != (dimensions,) or vector.dtype != np.float32 or not np.isfinite(vector).all():
            raise ValueError("embedding_cache_corrupt")
        return vector

    def put(self, key: str, vector: np.ndarray) -> None:
        path = self._path(key)
        value = np.asarray(vector, dtype=np.float32)
        if value.ndim != 1 or not np.isfinite(value).all():
            raise ValueError("invalid_cached_embedding")
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                np.save(output, value, allow_pickle=False)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class EmbeddingBuildResult:
    vectors: np.ndarray
    cache_hits: int
    cache_misses: int
    input_tokens: int
    cost_usd: Decimal


@dataclass(frozen=True)
class QueryEmbeddingResult:
    vector: np.ndarray
    cache_hit: bool
    input_tokens: int
    cost_usd: Decimal


def _validate_vectors(vectors: Sequence[Sequence[float]], expected: int, dimensions: int) -> np.ndarray:
    matrix = np.asarray(vectors, dtype=np.float32)
    if matrix.shape != (expected, dimensions):
        raise ValueError("embedding_shape_mismatch")
    if not np.isfinite(matrix).all():
        raise ValueError("embedding_non_finite")
    norms = np.linalg.norm(matrix, axis=1)
    if np.any(norms == 0):
        raise ValueError("embedding_zero_vector")
    return matrix


def l2_normalize(vectors: np.ndarray) -> np.ndarray:
    matrix = np.asarray(vectors, dtype=np.float32)
    if matrix.ndim != 2 or matrix.shape[0] < 1 or matrix.shape[1] < 1:
        raise ValueError("invalid_embedding_matrix")
    if not np.isfinite(matrix).all():
        raise ValueError("embedding_non_finite")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError("embedding_zero_vector")
    return np.ascontiguousarray(matrix / norms, dtype=np.float32)


def _embedding_input_limit(provider: EmbeddingProvider) -> int:
    try:
        input_limit = provider.max_input_tokens
    except AttributeError as error:
        raise ValueError("invalid_embedding_input_limit") from error
    if not isinstance(input_limit, int) or isinstance(input_limit, bool) or input_limit < 1:
        raise ValueError("invalid_embedding_input_limit")
    return input_limit


def embed_chunks(
    chunks: Sequence[dict[str, Any]],
    *,
    provider: EmbeddingProvider,
    counter: TokenCounter,
    cache: EmbeddingCache,
    corpus_manifest_sha256: str,
    budget: Budget | None = None,
    batch_size: int = 128,
    batch_interval_seconds: float = 0.0,
) -> EmbeddingBuildResult:
    if not chunks:
        raise ValueError("no_chunks_to_embed")
    require_sha256(corpus_manifest_sha256, "invalid_corpus_manifest_hash")
    if batch_size < 1:
        raise ValueError("invalid_embedding_batch_size")
    if (
        not isinstance(batch_interval_seconds, (int, float))
        or isinstance(batch_interval_seconds, bool)
        or not math.isfinite(batch_interval_seconds)
        or batch_interval_seconds < 0
    ):
        raise ValueError("invalid_embedding_batch_interval")
    if provider.requires_budget and budget is None:
        raise ValueError("budget_required")
    input_limit = _embedding_input_limit(provider)
    vectors: list[np.ndarray | None] = [None] * len(chunks)
    missing_by_key: dict[str, tuple[str, int, list[int]]] = {}
    cache_hits = 0
    seen_chunk_ids: set[str] = set()
    for index, chunk in enumerate(chunks):
        validate_chunk(chunk)
        chunk_id = chunk["chunk_id"]
        if chunk_id in seen_chunk_ids:
            raise ValueError("duplicate_chunk_id")
        seen_chunk_ids.add(chunk_id)
        text = chunk.get("text")
        content_sha256 = chunk.get("content_sha256")
        config_sha256 = chunk.get("config_sha256")
        if not isinstance(text, str) or not text:
            raise ValueError("invalid_chunk_text")
        if sha256_text(text) != content_sha256:
            raise ValueError("chunk_content_hash_mismatch")
        if not isinstance(config_sha256, str) or len(config_sha256) != 64:
            raise ValueError("invalid_chunk_config_hash")
        key = cache.key(
            corpus_manifest_sha256=corpus_manifest_sha256,
            chunk_config_sha256=config_sha256,
            model=provider.model,
            dimensions=provider.dimensions,
            content_sha256=content_sha256,
        )
        cached = cache.get(key, provider.dimensions)
        if cached is None:
            token_count = counter.count(text)
            if token_count < 1 or token_count > input_limit:
                raise ValueError("embedding_input_token_limit_exceeded")
            existing = missing_by_key.get(key)
            if existing is None:
                missing_by_key[key] = (text, token_count, [index])
            else:
                existing[2].append(index)
        else:
            vectors[index] = cached
            cache_hits += 1

    total_tokens = 0
    total_cost = Decimal("0")
    missing = [
        (key, text, token_count, indices)
        for key, (text, token_count, indices) in missing_by_key.items()
    ]
    last_provider_call_started: float | None = None
    for start in range(0, len(missing), batch_size):
        batch = missing[start : start + batch_size]
        predicted_tokens = sum(item[2] for item in batch)
        predicted_cost = (
            provider.estimate_cost(predicted_tokens)
            if provider.requires_budget
            else Decimal("0")
        )
        reserve_cost = max(predicted_cost, Decimal("0.000000001"))
        reservation_id: str | None = None
        operation_id = (
            f"embedding:{provider.model}:{provider.dimensions}:{start}:"
            f"{sha256_text('|'.join(item[0] for item in batch))}"
        )
        if provider.requires_budget and budget is not None:
            reservation_id = budget.reserve(reserve_cost, operation_id)
        try:
            if last_provider_call_started is not None and batch_interval_seconds:
                remaining = batch_interval_seconds - (
                    time.monotonic() - last_provider_call_started
                )
                if remaining > 0:
                    time.sleep(remaining)
            last_provider_call_started = time.monotonic()
            result = provider.embed([item[1] for item in batch])
            matrix = _validate_vectors(result.vectors, len(batch), provider.dimensions)
            actual_tokens = result.input_tokens if result.input_tokens is not None else predicted_tokens
            if actual_tokens < 0:
                raise ValueError("invalid_embedding_usage")
            actual_cost = (
                provider.estimate_cost(actual_tokens)
                if provider.requires_budget
                else Decimal("0")
            )
            if reservation_id is not None:
                budget.commit(reservation_id, actual_cost)
        except Exception:
            if reservation_id is not None:
                try:
                    budget.release(reservation_id)
                except ValueError as release_error:
                    if str(release_error) != "budget_reservation_missing":
                        raise
            raise
        for row, (key, _text, _token_count, chunk_indices) in zip(matrix, batch, strict=True):
            cache.put(key, row)
            for chunk_index in chunk_indices:
                vectors[chunk_index] = row
        total_tokens += actual_tokens
        total_cost += actual_cost

    if any(vector is None for vector in vectors):
        raise ValueError("embedding_result_incomplete")
    matrix = _validate_vectors([vector for vector in vectors if vector is not None], len(chunks), provider.dimensions)
    return EmbeddingBuildResult(
        vectors=l2_normalize(matrix),
        cache_hits=cache_hits,
        cache_misses=sum(len(item[3]) for item in missing),
        input_tokens=total_tokens,
        cost_usd=total_cost.quantize(Decimal("0.000000001")),
    )


def embed_query(
    text: str,
    *,
    provider: EmbeddingProvider,
    counter: TokenCounter,
    cache: EmbeddingCache,
    corpus_manifest_sha256: str,
    budget: Budget | None = None,
) -> QueryEmbeddingResult:
    if not isinstance(text, str) or not text:
        raise ValueError("invalid_query_text")
    if provider.requires_budget and budget is None:
        raise ValueError("budget_required")
    input_limit = _embedding_input_limit(provider)
    require_sha256(corpus_manifest_sha256, "invalid_corpus_manifest_hash")
    token_count = counter.count(text)
    if token_count < 1 or token_count > input_limit:
        raise ValueError("embedding_input_token_limit_exceeded")
    content_sha256 = sha256_text(text)
    key = cache.key(
        corpus_manifest_sha256=corpus_manifest_sha256,
        chunk_config_sha256=sha256_text("query-v1"),
        model=provider.model,
        dimensions=provider.dimensions,
        content_sha256=content_sha256,
    )
    cached = cache.get(key, provider.dimensions)
    if cached is not None:
        return QueryEmbeddingResult(
            vector=l2_normalize(cached.reshape(1, -1))[0],
            cache_hit=True,
            input_tokens=0,
            cost_usd=Decimal("0.000000000"),
        )
    predicted_cost = (
        max(provider.estimate_cost(token_count), Decimal("0.000000001"))
        if provider.requires_budget
        else Decimal("0")
    )
    reservation_id: str | None = None
    if provider.requires_budget and budget is not None:
        reservation_id = budget.reserve(predicted_cost, f"query-embedding:{provider.model}:{content_sha256}")
    try:
        result = provider.embed([text])
        matrix = _validate_vectors(result.vectors, 1, provider.dimensions)
        actual_tokens = result.input_tokens if result.input_tokens is not None else token_count
        actual_cost = (
            provider.estimate_cost(actual_tokens)
            if provider.requires_budget
            else Decimal("0")
        )
        if reservation_id is not None:
            budget.commit(reservation_id, actual_cost)
    except Exception:
        if reservation_id is not None:
            try:
                budget.release(reservation_id)
            except ValueError as release_error:
                if str(release_error) != "budget_reservation_missing":
                    raise
        raise
    normalized = l2_normalize(matrix)[0]
    cache.put(key, normalized)
    return QueryEmbeddingResult(
        vector=normalized,
        cache_hit=False,
        input_tokens=actual_tokens,
        cost_usd=actual_cost.quantize(Decimal("0.000000001")),
    )
