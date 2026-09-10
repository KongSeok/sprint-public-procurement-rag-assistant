from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Any

from midprojectrag.ingest.common import require_sha256, sha256_file


@dataclass(frozen=True)
class FileArtifact:
    relpath: str
    sha256: str


@dataclass(frozen=True)
class CatalogArtifact(FileArtifact):
    snapshot_id: str


@dataclass(frozen=True)
class IndexArtifact:
    relpath: str
    metadata_sha256: str
    config_file_sha256: str


@dataclass(frozen=True)
class RagRuntimeConfig:
    schema_version: str
    runtime_id: str
    stack_id: str
    api_profile: str
    embedding_model: str
    embedding_dimensions: int
    generator_model: str
    max_output_tokens: int
    retrieval_top_k: int
    context_top_k: int
    max_citations: int
    fusion: str | None
    rrf_k: int | None
    table_retrieval_cap: int | None
    table_context_cap: int | None
    retrieval_manifest: FileArtifact
    chunks: FileArtifact
    table_chunks: FileArtifact | None
    table_layout: FileArtifact | None
    catalog_manifest: CatalogArtifact
    correction_set: FileArtifact | None
    index: IndexArtifact
    table_index: IndexArtifact | None
    query_cache_relpath: str
    tokenizer_cache_relpath: str
    budget_ledger_relpath: str
    budget_limit_usd: Decimal
    observability_backend: str
    config_sha256: str


def _object(value: Any, error_code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(error_code)
    return value


def _exact_keys(value: dict[str, Any], keys: set[str], error_code: str) -> None:
    if set(value) != keys:
        raise ValueError(error_code)


def _nonempty_string(value: Any, error_code: str, *, max_length: int = 128) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > max_length
    ):
        raise ValueError(error_code)
    return value


def _positive_int(value: Any, error_code: str, *, maximum: int = 100_000) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1 <= value <= maximum
    ):
        raise ValueError(error_code)
    return value


def _relative_path(value: Any, error_code: str) -> str:
    path = _nonempty_string(value, error_code, max_length=500)
    pure = PurePosixPath(path)
    if (
        pure.is_absolute()
        or "\\" in path
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.as_posix() != path
    ):
        raise ValueError(error_code)
    return path


def _file_artifact(value: Any, error_code: str) -> FileArtifact:
    item = _object(value, error_code)
    _exact_keys(item, {"path", "sha256"}, error_code)
    return FileArtifact(
        relpath=_relative_path(item["path"], error_code),
        sha256=require_sha256(item["sha256"], error_code),
    )


def _catalog_artifact(value: Any) -> CatalogArtifact:
    item = _object(value, "invalid_catalog_artifact")
    _exact_keys(item, {"path", "sha256", "snapshot_id"}, "invalid_catalog_artifact")
    return CatalogArtifact(
        relpath=_relative_path(item["path"], "invalid_catalog_artifact"),
        sha256=require_sha256(item["sha256"], "invalid_catalog_artifact"),
        snapshot_id=_nonempty_string(
            item["snapshot_id"], "invalid_catalog_artifact", max_length=128
        ),
    )


def _index_artifact(value: Any) -> IndexArtifact:
    item = _object(value, "invalid_index_artifact")
    _exact_keys(
        item,
        {"path", "metadata_sha256", "config_file_sha256"},
        "invalid_index_artifact",
    )
    return IndexArtifact(
        relpath=_relative_path(item["path"], "invalid_index_artifact"),
        metadata_sha256=require_sha256(
            item["metadata_sha256"], "invalid_index_artifact"
        ),
        config_file_sha256=require_sha256(
            item["config_file_sha256"], "invalid_index_artifact"
        ),
    )


def _budget_limit(value: Any) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("invalid_runtime_budget") from error
    if not parsed.is_finite() or parsed <= 0 or parsed > Decimal("100"):
        raise ValueError("invalid_runtime_budget")
    return parsed


def load_runtime_config(path: Path) -> RagRuntimeConfig:
    try:
        with path.open("r", encoding="utf-8") as source:
            raw = json.load(source)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("runtime_config_load_failed") from error
    value = _object(raw, "invalid_runtime_config")
    _exact_keys(
        value,
        {
            "schema_version",
            "runtime_id",
            "stack_id",
            "api_profile",
            "embedding",
            "generation",
            "retrieval",
            "artifacts",
            "budget",
            "observability",
        },
        "invalid_runtime_config",
    )
    schema_version = value["schema_version"]
    if schema_version not in {"1.0", "1.1", "1.2"}:
        raise ValueError("unsupported_runtime_config_version")
    embedding = _object(value["embedding"], "invalid_runtime_embedding")
    generation = _object(value["generation"], "invalid_runtime_generation")
    retrieval = _object(value["retrieval"], "invalid_runtime_retrieval")
    artifacts = _object(value["artifacts"], "invalid_runtime_artifacts")
    budget = _object(value["budget"], "invalid_runtime_budget")
    observability = _object(value["observability"], "invalid_runtime_observability")
    _exact_keys(embedding, {"model", "dimensions"}, "invalid_runtime_embedding")
    _exact_keys(
        generation,
        {"model", "max_output_tokens"},
        "invalid_runtime_generation",
    )
    retrieval_keys = {"top_k", "context_top_k", "max_citations"}
    if schema_version == "1.2":
        retrieval_keys.update(
            {"fusion", "rrf_k", "table_retrieval_cap", "table_context_cap"}
        )
    _exact_keys(retrieval, retrieval_keys, "invalid_runtime_retrieval")
    artifact_keys = {
        "retrieval_manifest",
        "chunks",
        "catalog_manifest",
        "index",
        "query_cache_path",
        "tokenizer_cache_path",
        "budget_ledger_path",
    }
    if schema_version == "1.1":
        artifact_keys.add("correction_set")
    elif schema_version == "1.2":
        artifact_keys.update({"table_chunks", "table_layout", "table_index"})
    _exact_keys(artifacts, artifact_keys, "invalid_runtime_artifacts")
    _exact_keys(budget, {"limit_usd"}, "invalid_runtime_budget")
    _exact_keys(observability, {"backend"}, "invalid_runtime_observability")
    top_k = _positive_int(retrieval["top_k"], "invalid_runtime_retrieval", maximum=100)
    context_top_k = _positive_int(
        retrieval["context_top_k"], "invalid_runtime_retrieval", maximum=100
    )
    if context_top_k > top_k:
        raise ValueError("invalid_retrieval_context_limits")
    fusion = None
    rrf_k = None
    table_retrieval_cap = None
    table_context_cap = None
    if schema_version == "1.2":
        fusion = _nonempty_string(
            retrieval["fusion"], "invalid_runtime_retrieval", max_length=32
        )
        if fusion != "rrf-v1":
            raise ValueError("invalid_runtime_retrieval")
        rrf_k = _positive_int(
            retrieval["rrf_k"], "invalid_runtime_retrieval", maximum=10_000
        )
        table_retrieval_cap = _positive_int(
            retrieval["table_retrieval_cap"],
            "invalid_runtime_retrieval",
            maximum=100,
        )
        table_context_cap = _positive_int(
            retrieval["table_context_cap"],
            "invalid_runtime_retrieval",
            maximum=100,
        )
        if (
            table_retrieval_cap > top_k
            or table_context_cap > context_top_k
            or table_context_cap > table_retrieval_cap
        ):
            raise ValueError("invalid_retrieval_context_limits")
    return RagRuntimeConfig(
        schema_version=schema_version,
        runtime_id=_nonempty_string(value["runtime_id"], "invalid_runtime_id"),
        stack_id=_nonempty_string(value["stack_id"], "invalid_runtime_stack"),
        api_profile=_nonempty_string(value["api_profile"], "invalid_runtime_profile"),
        embedding_model=_nonempty_string(
            embedding["model"], "invalid_runtime_embedding"
        ),
        embedding_dimensions=_positive_int(
            embedding["dimensions"], "invalid_runtime_embedding", maximum=100_000
        ),
        generator_model=_nonempty_string(
            generation["model"], "invalid_runtime_generation"
        ),
        max_output_tokens=_positive_int(
            generation["max_output_tokens"],
            "invalid_runtime_generation",
            maximum=4_000,
        ),
        retrieval_top_k=top_k,
        context_top_k=context_top_k,
        max_citations=_positive_int(
            retrieval["max_citations"], "invalid_runtime_retrieval", maximum=20
        ),
        fusion=fusion,
        rrf_k=rrf_k,
        table_retrieval_cap=table_retrieval_cap,
        table_context_cap=table_context_cap,
        retrieval_manifest=_file_artifact(
            artifacts["retrieval_manifest"], "invalid_retrieval_manifest_artifact"
        ),
        chunks=_file_artifact(artifacts["chunks"], "invalid_chunk_artifact"),
        table_chunks=(
            _file_artifact(artifacts["table_chunks"], "invalid_table_chunk_artifact")
            if schema_version == "1.2"
            else None
        ),
        table_layout=(
            _file_artifact(artifacts["table_layout"], "invalid_table_layout_artifact")
            if schema_version == "1.2"
            else None
        ),
        catalog_manifest=_catalog_artifact(artifacts["catalog_manifest"]),
        correction_set=(
            _file_artifact(
                artifacts["correction_set"], "invalid_correction_set_artifact"
            )
            if schema_version == "1.1"
            else None
        ),
        index=_index_artifact(artifacts["index"]),
        table_index=(
            _index_artifact(artifacts["table_index"])
            if schema_version == "1.2"
            else None
        ),
        query_cache_relpath=_relative_path(
            artifacts["query_cache_path"], "invalid_query_cache_path"
        ),
        tokenizer_cache_relpath=_relative_path(
            artifacts["tokenizer_cache_path"], "invalid_tokenizer_cache_path"
        ),
        budget_ledger_relpath=_relative_path(
            artifacts["budget_ledger_path"], "invalid_budget_ledger_path"
        ),
        budget_limit_usd=_budget_limit(budget["limit_usd"]),
        observability_backend=_nonempty_string(
            observability["backend"], "invalid_runtime_observability"
        ),
        config_sha256=sha256_file(path),
    )
