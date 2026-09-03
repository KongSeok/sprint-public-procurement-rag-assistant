from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from statistics import fmean
from typing import Any

from midprojectrag.evaluation import (
    BLOCK_ID_RE,
    CHUNK_ID_RE,
    DOC_ID_RE,
    dataset_sha256,
    validate_case,
    validate_request,
    validate_response,
)
from midprojectrag.ingest.common import (
    canonical_json,
    read_jsonl,
    require_sha256,
    require_within,
    sha256_file,
    sha256_text,
)
from midprojectrag.indexing.chunking import chunk_artifact_sha256
from midprojectrag.stacks.local.gcp_config import (
    KURE_DIMENSIONS,
    KURE_DOCUMENT_PROMPT,
    KURE_MAX_INPUT_TOKENS,
    KURE_MODEL_ID,
    KURE_MODEL_REVISION,
    KURE_POOLING,
    KURE_PROMPT_VERSION,
    KURE_QUERY_PROMPT,
)
from midprojectrag.stacks.local.vllm_generation import (
    QWEN3_AWQ_MODEL,
    QWEN3_AWQ_REVISION,
    VLLM_CONTEXT_TOKENS,
    VLLM_MAX_OUTPUT_TOKENS,
)
from midprojectrag.stacks.local.generation import LOCAL_SYSTEM_INSTRUCTIONS
from midprojectrag.stacks.local.qwen_tokenizer import (
    QWEN_TOKENIZER_ALLOW_PATTERNS,
    QWEN_TOKENIZER_IGNORE_PATTERNS,
)


BASELINE_ID = "gcp-local-kure-qwen3-8b-awq-refined98-page-v1"
MAC_LOCAL_EQUIVALENT = "mac_local_equivalent"
OFFICIAL_GCP_PROFILE = "gcp_local"
DISK_HARD_MAX_BYTES = 100_000_000_000
DISK_WARNING_USED_BYTES = 80_000_000_000
DISK_MIN_FREE_BYTES = 10_000_000_000
K_VALUES = (1, 3, 5, 10)
MAC_EMBEDDING_CALL_BATCH_SIZE = 512
MANIFEST_PATH = "resources/data_refined/private/manifest.extracted.jsonl"
MANIFEST_SHA256 = "6c91d30a4c01b12f1aae8924c88a2e5055446c841f5eabfbf687546fdc1fe1cb"
CHUNKS_PATH = "resources/data_refined/private/chunks.page-v1.jsonl"
CHUNKS_SHA256 = "bb82b593153a93f9373f0bdf7f5be7531e651fdab9c5df36b69d53df0a35b9a2"
CHUNK_CONFIG_SHA256 = "b4dbcabc483eff0f4193e38fb8e2f3c32748543ce156a4ec0ece7a4f834721cc"
CASES_PATH = "golden-set-final/dev.refined.review-candidate.jsonl"
CASES_SHA256 = "abb1b0b5b4ce6aa85d98e91c7b5cefd6f76f98a4b68fef2c1f534768028fae80"
EVAL_SET_SHA256 = "0f2df1d9c3fdc5b4d03f6d1aafab9529281bc85ddfab308d25298b033f4b54b6"
PRIVATE_OUTPUT_PREFIX = (
    f"resources/data_refined/private/outputs/local/{BASELINE_ID}/mac-local-equivalent/"
)

_ROOT_FIELDS = frozenset(
    {
        "schema_version",
        "baseline_id",
        "corpus",
        "evaluation",
        "embedding",
        "generation",
        "retrieval",
        "dependencies",
        "storage",
        "public_receipt_path",
    }
)
_NESTED_FIELDS = {
    "corpus": frozenset(
        {
            "manifest_path",
            "manifest_sha256",
            "document_count",
            "chunks_path",
            "chunks_sha256",
            "chunk_count",
            "chunker_id",
            "chunk_config_sha256",
        }
    ),
    "evaluation": frozenset(
        {
            "cases_path",
            "cases_sha256",
            "eval_set_sha256",
            "case_count",
            "review_status",
            "tier",
        }
    ),
    "embedding": frozenset(
        {
            "model",
            "revision",
            "dimensions",
            "max_input_tokens",
            "pooling",
            "prompt_version",
            "document_prompt",
            "query_prompt",
            "batch_size",
        }
    ),
    "generation": frozenset(
        {
            "official_model",
            "official_revision",
            "official_runtime",
            "quantization",
            "mac_equivalent_model",
            "mac_equivalent_digest",
            "context_tokens",
            "mac_transport_context_tokens",
            "max_output_tokens",
            "temperature",
            "thinking",
            "logical_context_counter",
        }
    ),
    "retrieval": frozenset(
        {
            "metric",
            "official_engine",
            "mac_equivalent_engine",
            "top_k",
            "context_top_k",
            "max_citations",
        }
    ),
    "dependencies": frozenset({"lock_path", "lock_sha256"}),
    "storage": frozenset(
        {
            "hard_max_bytes",
            "warning_used_bytes",
            "minimum_free_bytes",
            "hf_cache_path",
            "embedding_cache_path",
            "index_path",
            "candidate_path",
            "private_score_path",
        }
    ),
}


def _exact(value: Any, expected: Any, error_code: str) -> None:
    if type(value) is not type(expected) or value != expected:
        raise ValueError(error_code)


def _relative_path(value: Any, *, prefix: str | None = None) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("invalid_baseline_path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or value != path.as_posix():
        raise ValueError("invalid_baseline_path")
    if prefix is not None and not value.startswith(prefix):
        raise ValueError("baseline_path_boundary_violation")
    return value


def validate_baseline_config(value: Any) -> dict[str, Any]:
    """Validate the single frozen local/GCP baseline without accepting drift."""

    if not isinstance(value, dict) or set(value) != _ROOT_FIELDS:
        raise ValueError("invalid_baseline_config_shape")
    for section, fields in _NESTED_FIELDS.items():
        row = value.get(section)
        if not isinstance(row, dict) or set(row) != fields:
            raise ValueError(f"invalid_{section}_config_shape")

    _exact(value["schema_version"], "1.0", "invalid_schema_version")
    _exact(value["baseline_id"], BASELINE_ID, "baseline_id_not_frozen")
    corpus = value["corpus"]
    _exact(corpus["manifest_path"], MANIFEST_PATH, "manifest_path_not_frozen")
    _exact(corpus["chunks_path"], CHUNKS_PATH, "chunks_path_not_frozen")
    _exact(corpus["manifest_sha256"], MANIFEST_SHA256, "manifest_hash_not_frozen")
    _exact(corpus["chunks_sha256"], CHUNKS_SHA256, "chunks_hash_not_frozen")
    _exact(corpus["chunk_config_sha256"], CHUNK_CONFIG_SHA256, "chunk_config_hash_not_frozen")
    _exact(corpus["document_count"], 98, "document_count_not_frozen")
    _exact(corpus["chunk_count"], 9331, "chunk_count_not_frozen")
    _exact(corpus["chunker_id"], "page-v1", "chunker_not_frozen")

    evaluation = value["evaluation"]
    _exact(evaluation["cases_path"], CASES_PATH, "cases_path_not_frozen")
    _exact(evaluation["cases_sha256"], CASES_SHA256, "cases_hash_not_frozen")
    _exact(evaluation["eval_set_sha256"], EVAL_SET_SHA256, "eval_set_hash_not_frozen")
    _exact(evaluation["case_count"], 40, "case_count_not_frozen")
    _exact(evaluation["review_status"], "draft", "gold_review_status_not_frozen")
    _exact(evaluation["tier"], "provisional_non_official", "evaluation_tier_not_frozen")

    embedding = value["embedding"]
    _exact(embedding["model"], KURE_MODEL_ID, "embedding_model_not_allowlisted")
    _exact(embedding["revision"], KURE_MODEL_REVISION, "embedding_revision_not_pinned")
    _exact(embedding["dimensions"], KURE_DIMENSIONS, "embedding_dimensions_not_frozen")
    _exact(embedding["max_input_tokens"], KURE_MAX_INPUT_TOKENS, "embedding_limit_not_frozen")
    _exact(embedding["pooling"], KURE_POOLING, "embedding_pooling_not_frozen")
    _exact(embedding["prompt_version"], KURE_PROMPT_VERSION, "embedding_prompt_version_not_frozen")
    _exact(embedding["document_prompt"], KURE_DOCUMENT_PROMPT, "embedding_document_prompt_not_frozen")
    _exact(embedding["query_prompt"], KURE_QUERY_PROMPT, "embedding_query_prompt_not_frozen")
    if not isinstance(embedding["batch_size"], int) or isinstance(embedding["batch_size"], bool) or not 1 <= embedding["batch_size"] <= 128:
        raise ValueError("invalid_embedding_batch_size")

    generation = value["generation"]
    _exact(generation["official_model"], QWEN3_AWQ_MODEL, "generator_model_not_frozen")
    _exact(generation["official_revision"], QWEN3_AWQ_REVISION, "generator_revision_not_pinned")
    _exact(generation["official_runtime"], "vllm", "generator_runtime_not_frozen")
    _exact(generation["quantization"], "awq-int4", "generator_quantization_not_frozen")
    _exact(generation["mac_equivalent_model"], "qwen3.8:27b-mlx", "mac_model_not_frozen")
    _exact(
        generation["mac_equivalent_digest"],
        "5642e97495e1a088883805981563dcdc4a040c2f53388b7a41d1f24d3622cf7e",
        "mac_model_digest_not_frozen",
    )
    _exact(generation["context_tokens"], VLLM_CONTEXT_TOKENS, "generation_context_not_frozen")
    _exact(generation["mac_transport_context_tokens"], 32768, "mac_transport_contract_not_frozen")
    _exact(generation["max_output_tokens"], VLLM_MAX_OUTPUT_TOKENS, "generation_output_not_frozen")
    _exact(generation["temperature"], 0, "generation_temperature_not_frozen")
    _exact(generation["thinking"], False, "generation_thinking_not_frozen")
    _exact(
        generation["logical_context_counter"],
        "qwen3-awq-chat-template-v1",
        "generation_token_counter_not_frozen",
    )

    retrieval = value["retrieval"]
    frozen_retrieval = {
        "metric": "cosine_via_normalized_inner_product",
        "official_engine": "faiss",
        "mac_equivalent_engine": "numpy",
        "top_k": 10,
        "context_top_k": 5,
        "max_citations": 3,
    }
    for field, expected in frozen_retrieval.items():
        _exact(retrieval[field], expected, "retrieval_contract_not_frozen")

    dependencies = value["dependencies"]
    _exact(
        dependencies["lock_path"],
        "requirements/gcp-local-lock.txt",
        "dependency_lock_path_not_frozen",
    )
    _exact(
        dependencies["lock_sha256"],
        "eb7560d74cecf21a423aef1299bdca1733f53fd40706cb774573056b1ca87ea4",
        "dependency_lock_hash_not_frozen",
    )

    storage = value["storage"]
    frozen_storage = {
        "hard_max_bytes": DISK_HARD_MAX_BYTES,
        "warning_used_bytes": DISK_WARNING_USED_BYTES,
        "minimum_free_bytes": DISK_MIN_FREE_BYTES,
    }
    for field, expected in frozen_storage.items():
        _exact(storage[field], expected, "disk_contract_not_frozen")
    frozen_paths = {
        "hf_cache_path": "resources/data_refined/private/hf-cache",
        "embedding_cache_path": "resources/data_refined/private/caches/local/kure-v1-1024/page-v1",
        "index_path": "resources/data_refined/private/indexes/local/kure-v1-1024/page-v1",
        "candidate_path": PRIVATE_OUTPUT_PREFIX + "candidates.jsonl",
        "private_score_path": PRIVATE_OUTPUT_PREFIX + "provisional-score.json",
    }
    for field, expected in frozen_paths.items():
        _exact(storage[field], expected, "artifact_path_not_frozen")
    _exact(
        value["public_receipt_path"],
        f"evaluation/baselines/{BASELINE_ID}/mac-local-equivalent-receipt.json",
        "public_receipt_path_not_frozen",
    )
    return json.loads(json.dumps(value, ensure_ascii=False))


@dataclass(frozen=True)
class VerifiedBaseline:
    repo_root: Path
    config_path: Path
    config: dict[str, Any]
    config_sha256: str
    manifest_path: Path
    chunks_path: Path
    cases_path: Path
    dependency_lock_path: Path
    cases: list[dict[str, Any]]
    eval_set_sha256: str
    hf_cache_path: Path
    embedding_cache_path: Path
    index_path: Path
    candidate_path: Path
    private_score_path: Path
    public_receipt_path: Path


def _resolve_repo_path(repo_root: Path, relative: str) -> Path:
    return require_within(repo_root / relative, repo_root, "baseline_path_outside_repo")


def _count_jsonl_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8") as source:
        return sum(1 for line in source if line.strip())


def load_verified_baseline(
    *,
    repo_root: Path,
    config_path: Path,
) -> VerifiedBaseline:
    repo_root = repo_root.resolve()
    config_path = require_within(config_path.resolve(), repo_root, "config_path_outside_repo")
    try:
        with config_path.open("r", encoding="utf-8") as source:
            raw_config = json.load(source)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("baseline_config_read_failed") from error
    config = validate_baseline_config(raw_config)
    corpus = config["corpus"]
    evaluation = config["evaluation"]
    storage = config["storage"]
    dependencies = config["dependencies"]
    manifest_path = _resolve_repo_path(repo_root, corpus["manifest_path"])
    chunks_path = _resolve_repo_path(repo_root, corpus["chunks_path"])
    cases_path = _resolve_repo_path(repo_root, evaluation["cases_path"])
    dependency_lock_path = _resolve_repo_path(repo_root, dependencies["lock_path"])
    for path in (manifest_path, chunks_path, cases_path, dependency_lock_path):
        if not path.is_file():
            raise ValueError("baseline_artifact_missing")
    if sha256_file(manifest_path) != corpus["manifest_sha256"]:
        raise ValueError("baseline_manifest_hash_mismatch")
    if sha256_file(chunks_path) != corpus["chunks_sha256"]:
        raise ValueError("baseline_chunks_hash_mismatch")
    if sha256_file(cases_path) != evaluation["cases_sha256"]:
        raise ValueError("baseline_cases_hash_mismatch")
    if sha256_file(dependency_lock_path) != dependencies["lock_sha256"]:
        raise ValueError("baseline_dependency_lock_hash_mismatch")
    if _count_jsonl_rows(manifest_path) != corpus["document_count"]:
        raise ValueError("baseline_document_count_mismatch")
    if _count_jsonl_rows(chunks_path) != corpus["chunk_count"]:
        raise ValueError("baseline_chunk_count_mismatch")
    cases = read_jsonl(cases_path)
    if len(cases) != evaluation["case_count"]:
        raise ValueError("baseline_case_count_mismatch")
    computed_eval_hash = dataset_sha256(cases)
    if computed_eval_hash != evaluation["eval_set_sha256"]:
        raise ValueError("baseline_eval_set_hash_mismatch")
    for index, case in enumerate(cases):
        if validate_case(case, f"cases[{index}]"):
            raise ValueError("baseline_case_contract_invalid")
        if case.get("source_manifest_sha256") != corpus["manifest_sha256"]:
            raise ValueError("baseline_case_manifest_mismatch")
        review = case.get("review")
        if not isinstance(review, dict) or review.get("status") != evaluation["review_status"]:
            raise ValueError("baseline_case_review_status_mismatch")

    config_sha256 = sha256_text(canonical_json(config))
    return VerifiedBaseline(
        repo_root=repo_root,
        config_path=config_path,
        config=config,
        config_sha256=config_sha256,
        manifest_path=manifest_path,
        chunks_path=chunks_path,
        cases_path=cases_path,
        dependency_lock_path=dependency_lock_path,
        cases=cases,
        eval_set_sha256=computed_eval_hash,
        hf_cache_path=_resolve_repo_path(repo_root, storage["hf_cache_path"]),
        embedding_cache_path=_resolve_repo_path(repo_root, storage["embedding_cache_path"]),
        index_path=_resolve_repo_path(repo_root, storage["index_path"]),
        candidate_path=_resolve_repo_path(repo_root, storage["candidate_path"]),
        private_score_path=_resolve_repo_path(repo_root, storage["private_score_path"]),
        public_receipt_path=_resolve_repo_path(repo_root, config["public_receipt_path"]),
    )


def _tree_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for root, _directories, files in os.walk(path):
        for filename in files:
            try:
                total += (Path(root) / filename).stat().st_size
            except FileNotFoundError:
                continue
    return total


def local_workspace_storage(verified: VerifiedBaseline) -> dict[str, Any]:
    private_root = verified.repo_root / "resources/data_refined/private"
    used_bytes = _tree_size(private_root)
    free_bytes = shutil.disk_usage(verified.repo_root).free
    if used_bytes > DISK_HARD_MAX_BYTES:
        raise ValueError("baseline_working_set_exceeds_100gb")
    if free_bytes < DISK_MIN_FREE_BYTES:
        raise ValueError("disk_free_below_10gb")
    warning = used_bytes >= DISK_WARNING_USED_BYTES
    return {
        "passed": True,
        "warning": warning,
        "warning_code": "baseline_working_set_at_or_above_80gb" if warning else None,
        "working_set_bytes": used_bytes,
        "free_bytes": free_bytes,
        "hard_max_bytes": DISK_HARD_MAX_BYTES,
        "minimum_free_bytes": DISK_MIN_FREE_BYTES,
    }


def verify_dependency_lock(verified: VerifiedBaseline) -> dict[str, Any]:
    expected: dict[str, str] = {}
    with verified.dependency_lock_path.open("r", encoding="utf-8") as source:
        for line in source:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.count("==") != 1:
                raise ValueError("dependency_lock_line_invalid")
            name, pinned = stripped.split("==", 1)
            if not name or not pinned or name.casefold() in expected:
                raise ValueError("dependency_lock_line_invalid")
            expected[name.casefold()] = pinned
    mismatched: list[str] = []
    for name, pinned in expected.items():
        try:
            installed = package_version(name)
        except PackageNotFoundError:
            mismatched.append(name)
            continue
        if installed != pinned:
            mismatched.append(name)
    if mismatched:
        raise ValueError("dependency_lock_runtime_mismatch")
    return {
        "passed": True,
        "package_count": len(expected),
        "lock_sha256": verified.config["dependencies"]["lock_sha256"],
    }


def _configure_hf_cache(path: Path, *, offline: bool) -> None:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    os.environ["HF_HOME"] = str(path)
    os.environ["HF_HUB_CACHE"] = str(path / "hub")
    if offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    else:
        os.environ.pop("HF_HUB_OFFLINE", None)
        os.environ.pop("TRANSFORMERS_OFFLINE", None)


def prepare_kure_model(verified: VerifiedBaseline) -> dict[str, Any]:
    local_workspace_storage(verified)
    verify_dependency_lock(verified)
    _configure_hf_cache(verified.hf_cache_path, offline=False)
    try:
        from huggingface_hub import snapshot_download
    except ImportError as error:
        raise RuntimeError("huggingface_hub_dependency_missing") from error
    try:
        snapshot_download(
            repo_id=KURE_MODEL_ID,
            revision=KURE_MODEL_REVISION,
            cache_dir=str(verified.hf_cache_path / "hub"),
            local_files_only=False,
            max_workers=4,
        )
        snapshot_download(
            repo_id=QWEN3_AWQ_MODEL,
            revision=QWEN3_AWQ_REVISION,
            cache_dir=str(verified.hf_cache_path / "hub"),
            local_files_only=False,
            allow_patterns=list(QWEN_TOKENIZER_ALLOW_PATTERNS),
            ignore_patterns=list(QWEN_TOKENIZER_IGNORE_PATTERNS),
            max_workers=4,
        )
    except Exception as error:
        raise RuntimeError("baseline_model_assets_download_failed") from error
    _configure_hf_cache(verified.hf_cache_path, offline=True)
    from midprojectrag.stacks.local.hf_embeddings import (
        HuggingFaceTokenCounter,
        KureEmbeddingProvider,
    )

    counter = HuggingFaceTokenCounter()
    provider = KureEmbeddingProvider(batch_size=1, device="cpu")
    token_count = counter.count("KURE local readiness check")
    result = provider.embed(["KURE local readiness check"])
    if len(result.vectors) != 1 or len(result.vectors[0]) != KURE_DIMENSIONS:
        raise ValueError("kure_model_smoke_failed")
    qwen_counter = PinnedQwenChatTokenCounter()
    qwen_chat_tokens = qwen_counter.count_chat(
        system=LOCAL_SYSTEM_INSTRUCTIONS,
        prompt="Qwen local readiness check",
    )
    storage = local_workspace_storage(verified)
    return {
        "passed": True,
        "model": KURE_MODEL_ID,
        "revision": KURE_MODEL_REVISION,
        "dimensions": KURE_DIMENSIONS,
        "synthetic_input_tokens": token_count,
        "qwen_tokenizer_model": QWEN3_AWQ_MODEL,
        "qwen_tokenizer_revision": QWEN3_AWQ_REVISION,
        "qwen_synthetic_chat_tokens": qwen_chat_tokens,
        "working_set_bytes": storage["working_set_bytes"],
        "free_bytes": storage["free_bytes"],
    }


def _mac_index_identity(verified: VerifiedBaseline) -> dict[str, Any]:
    corpus = verified.config["corpus"]
    embedding = verified.config["embedding"]
    return {
        "schema_version": "1.0",
        "baseline_id": BASELINE_ID,
        "execution_profile": MAC_LOCAL_EQUIVALENT,
        "corpus_manifest_sha256": corpus["manifest_sha256"],
        "chunk_artifact_sha256": corpus["chunks_sha256"],
        "chunk_config_sha256": corpus["chunk_config_sha256"],
        "embedding": dict(embedding),
        "normalization": "float32_l2",
        "engine": verified.config["retrieval"]["mac_equivalent_engine"],
    }


def mac_index_config_sha256(verified: VerifiedBaseline) -> str:
    return sha256_text(canonical_json(_mac_index_identity(verified)))


_INDEX_PROVENANCE_FIELDS = frozenset(
    {
        "schema_version",
        "engine",
        "count",
        "dimensions",
        "chunk_artifact_sha256",
        "index_config_sha256",
        "vectors_sha256",
        "rows_sha256",
        "metadata_sha256",
    }
)


def validate_index_provenance(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _INDEX_PROVENANCE_FIELDS:
        raise ValueError("invalid_index_provenance_shape")
    _exact(value["schema_version"], "1.0", "invalid_index_provenance_schema")
    _exact(value["engine"], "numpy", "invalid_index_provenance_engine")
    _exact(value["count"], 9331, "invalid_index_provenance_count")
    _exact(value["dimensions"], KURE_DIMENSIONS, "invalid_index_provenance_dimensions")
    for field in (
        "chunk_artifact_sha256",
        "index_config_sha256",
        "vectors_sha256",
        "rows_sha256",
        "metadata_sha256",
    ):
        require_sha256(value[field], f"invalid_index_provenance_{field}")
    _exact(
        value["chunk_artifact_sha256"],
        CHUNKS_SHA256,
        "index_provenance_chunk_mismatch",
    )
    return json.loads(json.dumps(value, ensure_ascii=False))


def current_mac_index_provenance(verified: VerifiedBaseline) -> dict[str, Any]:
    """Load and hash the complete persisted index before reuse or scoring."""

    _configure_hf_cache(verified.hf_cache_path, offline=True)
    from midprojectrag.indexing.embeddings import embedding_cache_namespace
    from midprojectrag.indexing.exact_index import ExactDenseIndex
    from midprojectrag.stacks.local.hf_embeddings import KureEmbeddingProvider

    chunks = _load_chunks(verified)
    provider = KureEmbeddingProvider(batch_size=1, device="cpu")
    expected_index_hash = mac_index_config_sha256(verified)
    loaded = ExactDenseIndex.load(
        verified.index_path,
        chunks,
        expected_embedding_model=embedding_cache_namespace(provider, role="document"),
        expected_dimensions=KURE_DIMENSIONS,
        expected_api_profile=MAC_LOCAL_EQUIVALENT,
        expected_index_config_sha256=expected_index_hash,
    )
    metadata_path = verified.index_path / "metadata.json"
    with metadata_path.open("r", encoding="utf-8") as source:
        metadata = json.load(source)
    if not isinstance(metadata, dict):
        raise ValueError("invalid_index_metadata")
    provenance = {
        "schema_version": "1.0",
        "engine": loaded.engine,
        "count": len(loaded.rows),
        "dimensions": loaded.dimensions,
        "chunk_artifact_sha256": metadata.get("chunk_artifact_sha256"),
        "index_config_sha256": metadata.get("index_config_sha256"),
        "vectors_sha256": metadata.get("vectors_sha256"),
        "rows_sha256": metadata.get("rows_sha256"),
        "metadata_sha256": sha256_file(metadata_path),
    }
    validated = validate_index_provenance(provenance)
    if validated["index_config_sha256"] != expected_index_hash:
        raise ValueError("index_provenance_config_mismatch")
    return validated


def _resolve_embedding_device(requested: str) -> str:
    if requested in {"cpu", "mps"}:
        return requested
    if requested != "auto":
        raise ValueError("invalid_embedding_device")
    try:
        import torch
    except ImportError as error:
        raise RuntimeError("torch_dependency_missing") from error
    return "mps" if torch.backends.mps.is_available() else "cpu"


def _load_chunks(verified: VerifiedBaseline) -> list[dict[str, Any]]:
    chunks = read_jsonl(verified.chunks_path)
    corpus = verified.config["corpus"]
    if len(chunks) != corpus["chunk_count"] or chunk_artifact_sha256(chunks) != corpus["chunks_sha256"]:
        raise ValueError("baseline_chunk_artifact_mismatch")
    if any(
        row.get("chunker_id") != corpus["chunker_id"]
        or row.get("config_sha256") != corpus["chunk_config_sha256"]
        or row.get("retrieval_role") != "primary"
        for row in chunks
    ):
        raise ValueError("baseline_chunk_lane_mismatch")
    return chunks


def build_mac_semantic_index(
    verified: VerifiedBaseline,
    *,
    device: str = "auto",
) -> dict[str, Any]:
    local_workspace_storage(verified)
    verify_dependency_lock(verified)
    _configure_hf_cache(verified.hf_cache_path, offline=True)
    from midprojectrag.indexing.embeddings import (
        EmbeddingCache,
        embed_chunks,
        embedding_cache_namespace,
    )
    from midprojectrag.indexing.exact_index import ExactDenseIndex
    from midprojectrag.stacks.local.hf_embeddings import (
        HuggingFaceTokenCounter,
        KureEmbeddingProvider,
    )
    chunks = _load_chunks(verified)
    selected_device = _resolve_embedding_device(device)
    batch_size = verified.config["embedding"]["batch_size"]
    counter = HuggingFaceTokenCounter()
    provider = KureEmbeddingProvider(batch_size=batch_size, device=selected_device)
    cache = EmbeddingCache(verified.embedding_cache_path)
    embedded = embed_chunks(
        chunks,
        provider=provider,
        counter=counter,
        cache=cache,
        corpus_manifest_sha256=verified.config["corpus"]["manifest_sha256"],
        batch_size=MAC_EMBEDDING_CALL_BATCH_SIZE,
    )
    index = ExactDenseIndex(
        chunks,
        embedded.vectors,
        engine=verified.config["retrieval"]["mac_equivalent_engine"],
    )
    index_hash = mac_index_config_sha256(verified)
    metadata = index.save(
        verified.index_path,
        corpus_manifest_sha256=verified.config["corpus"]["manifest_sha256"],
        embedding_model=embedding_cache_namespace(provider, role="document"),
        api_profile=MAC_LOCAL_EQUIVALENT,
        index_config_sha256=index_hash,
    )
    storage = local_workspace_storage(verified)
    return {
        "passed": True,
        "execution_profile": MAC_LOCAL_EQUIVALENT,
        "official": False,
        "engine": metadata["engine"],
        "count": metadata["count"],
        "dimensions": metadata["dimensions"],
        "index_config_sha256": index_hash,
        "vectors_sha256": metadata["vectors_sha256"],
        "cache_hits": embedded.cache_hits,
        "cache_misses": embedded.cache_misses,
        "embedding_input_tokens": embedded.input_tokens,
        "device": selected_device,
        "provider_batch_size": batch_size,
        "embedding_call_batch_size": MAC_EMBEDDING_CALL_BATCH_SIZE,
        "working_set_bytes": storage["working_set_bytes"],
    }


def load_mac_retrieval_components(
    verified: VerifiedBaseline,
    *,
    embedding_device: str = "cpu",
) -> dict[str, Any]:
    """Load the frozen local retrieval artifacts without loading a generator."""
    verify_dependency_lock(verified)
    _configure_hf_cache(verified.hf_cache_path, offline=True)
    from midprojectrag.indexing.embeddings import (
        EmbeddingCache,
        embedding_cache_namespace,
    )
    from midprojectrag.indexing.exact_index import ExactDenseIndex
    from midprojectrag.stacks.local.hf_embeddings import (
        HuggingFaceTokenCounter,
        KureEmbeddingProvider,
    )

    chunks = _load_chunks(verified)
    selected_device = _resolve_embedding_device(embedding_device)
    batch_size = verified.config["embedding"]["batch_size"]
    counter = HuggingFaceTokenCounter()
    provider = KureEmbeddingProvider(batch_size=batch_size, device=selected_device)
    index_hash = mac_index_config_sha256(verified)
    index = ExactDenseIndex.load(
        verified.index_path,
        chunks,
        expected_embedding_model=embedding_cache_namespace(provider, role="document"),
        expected_dimensions=KURE_DIMENSIONS,
        expected_api_profile=MAC_LOCAL_EQUIVALENT,
        expected_index_config_sha256=index_hash,
    )
    retrieval = verified.config["retrieval"]
    return dict(
        index=index,
        embedding_provider=provider,
        embedding_counter=counter,
        query_cache=EmbeddingCache(verified.embedding_cache_path),
        corpus_manifest_sha256=verified.config["corpus"]["manifest_sha256"],
        retrieval_top_k=retrieval["top_k"],
        context_top_k=retrieval["context_top_k"],
    )


def load_mac_pipeline(
    verified: VerifiedBaseline,
    *,
    embedding_device: str = "cpu",
) -> Any:
    # Preserve the frozen evaluation entrypoint. Application model switches use
    # local_application instead and never inherit this profile ID.
    from midprojectrag.answering.pipeline import RagPipeline
    from midprojectrag.stacks.local.generation import OllamaGenerator
    from midprojectrag.stacks.local.qwen_tokenizer import PinnedQwenChatTokenCounter

    retrieval_components = load_mac_retrieval_components(
        verified, embedding_device=embedding_device,
    )
    generation_counter = PinnedQwenChatTokenCounter()
    generation = verified.config["generation"]
    generator = RecordingGenerator(
        OllamaGenerator(
            model=generation["mac_equivalent_model"],
            max_output_tokens=generation["max_output_tokens"],
            context_tokens=generation["mac_transport_context_tokens"],
        ),
        counter=generation_counter,
        system_instructions=LOCAL_SYSTEM_INSTRUCTIONS,
        logical_context_tokens=generation["context_tokens"],
    )
    return RagPipeline(
        **retrieval_components,
        generator=generator,
        generation_counter=generation_counter,
        budget=None,
        stack_id=MAC_LOCAL_EQUIVALENT,
    )


def _mean(values: Sequence[float]) -> float | None:
    return round(fmean(values), 6) if values else None


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return round(ordered[rank - 1], 6)


def _dcg(relevances: Sequence[int]) -> float:
    return sum(value / math.log2(index + 2) for index, value in enumerate(relevances))


def evaluate_storage(
    *,
    total_bytes: int,
    used_bytes: int,
    free_bytes: int,
) -> dict[str, Any]:
    """Enforce the user-confirmed decimal-GB disk boundary.

    GCP persistent-disk sizes are configured in decimal GB, so this guard uses
    1 GB = 1,000,000,000 bytes rather than GiB.
    """

    values = (total_bytes, used_bytes, free_bytes)
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values):
        raise ValueError("invalid_disk_measurement")
    if used_bytes + free_bytes > total_bytes + 1_000_000_000:
        raise ValueError("inconsistent_disk_measurement")
    if total_bytes > DISK_HARD_MAX_BYTES:
        raise ValueError("disk_capacity_exceeds_100gb")
    if free_bytes < DISK_MIN_FREE_BYTES:
        raise ValueError("disk_free_below_10gb")
    warning = used_bytes >= DISK_WARNING_USED_BYTES
    return {
        "passed": True,
        "warning": warning,
        "warning_code": "disk_used_at_or_above_80gb" if warning else None,
        "total_bytes": total_bytes,
        "used_bytes": used_bytes,
        "free_bytes": free_bytes,
        "hard_max_bytes": DISK_HARD_MAX_BYTES,
        "minimum_free_bytes": DISK_MIN_FREE_BYTES,
    }


def build_golden_request(
    case: Mapping[str, Any],
    *,
    config_sha256: str,
    max_citations: int,
) -> dict[str, Any]:
    require_sha256(config_sha256, "invalid_config_hash")
    case_id = case.get("case_id")
    question = case.get("question")
    history = case.get("history")
    document_scope = case.get("document_scope")
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("invalid_case_id")
    if not isinstance(question, str) or not question:
        raise ValueError("invalid_case_question")
    if not isinstance(history, list) or not isinstance(document_scope, dict):
        raise ValueError("invalid_case_request_fields")
    if type(max_citations) is not int or max_citations != 3:
        raise ValueError("max_citations_not_frozen")
    material = f"{case_id}:{config_sha256}"
    return {
        "schema_version": "1.0",
        "request_id": f"req-{sha256_text(material)[:24]}",
        "question": question,
        "history": json.loads(json.dumps(history, ensure_ascii=False)),
        "document_scope": json.loads(json.dumps(document_scope, ensure_ascii=False)),
        "options": {"max_citations": max_citations},
    }


@dataclass
class RecordingGenerator:
    """Enforce the logical 8K budget and retain the current private transcript."""

    delegate: Any
    counter: Any
    system_instructions: str = LOCAL_SYSTEM_INSTRUCTIONS
    logical_context_tokens: int = VLLM_CONTEXT_TOKENS
    last_prompt: str | None = None
    last_plan: dict[str, Any] | None = None

    @property
    def model(self) -> str:
        return self.delegate.model

    @property
    def max_output_tokens(self) -> int:
        return self.delegate.max_output_tokens

    @property
    def requires_budget(self) -> bool:
        return self.delegate.requires_budget

    def estimate_cost(self, input_tokens: int, output_tokens: int):  # type: ignore[no-untyped-def]
        return self.delegate.estimate_cost(input_tokens, output_tokens)

    def reset_transcript(self) -> None:
        self.last_prompt = None
        self.last_plan = None

    def generate(self, prompt: str):  # type: ignore[no-untyped-def]
        self.last_prompt = prompt
        count_chat = getattr(self.counter, "count_chat", None)
        if not callable(count_chat):
            raise ValueError("qwen_chat_counter_required")
        logical_tokens = count_chat(system=self.system_instructions, prompt=prompt)
        if logical_tokens + self.max_output_tokens > self.logical_context_tokens:
            raise ValueError("mac_logical_context_budget_exceeded")
        plan, input_tokens, output_tokens = self.delegate.generate(prompt)
        self.last_plan = json.loads(json.dumps(plan, ensure_ascii=False))
        return plan, input_tokens, output_tokens


def build_mac_candidate(
    *,
    case: Mapping[str, Any],
    request: Mapping[str, Any],
    result: Any,
    run_id: str,
    config_sha256: str,
    eval_set_sha256: str,
    index_provenance: Mapping[str, Any],
    prompt: str | None,
    prompt_sha256: str | None,
    generation_plan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    require_sha256(config_sha256, "invalid_config_hash")
    require_sha256(eval_set_sha256, "invalid_eval_set_hash")
    validated_provenance = validate_index_provenance(dict(index_provenance))
    if prompt_sha256 is not None:
        require_sha256(prompt_sha256, "invalid_prompt_hash")
    if (prompt is None) != (prompt_sha256 is None):
        raise ValueError("incomplete_prompt_transcript")
    if prompt is not None and sha256_text(prompt) != prompt_sha256:
        raise ValueError("prompt_hash_mismatch")
    case_id = case.get("case_id")
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("invalid_case_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("invalid_run_id")
    return {
        "schema_version": "1.0",
        "baseline_id": BASELINE_ID,
        "execution_profile": MAC_LOCAL_EQUIVALENT,
        "official": False,
        "run_id": run_id,
        "case_id": case_id,
        "case_sha256": sha256_text(canonical_json(dict(case))),
        "config_sha256": config_sha256,
        "eval_set_sha256": eval_set_sha256,
        "index_provenance": validated_provenance,
        "request": json.loads(json.dumps(dict(request), ensure_ascii=False)),
        "request_sha256": sha256_text(canonical_json(dict(request))),
        "prompt": prompt,
        "prompt_sha256": prompt_sha256,
        "generation_plan": (
            json.loads(json.dumps(dict(generation_plan), ensure_ascii=False))
            if generation_plan is not None
            else None
        ),
        "retrieval": json.loads(json.dumps(result.retrieval, ensure_ascii=False)),
        "response": json.loads(json.dumps(result.response, ensure_ascii=False)),
        "timing_ms": dict(result.timing_ms),
        "usage": dict(result.usage),
        "cache_hit": bool(result.cache_hit),
    }


_CANDIDATE_FIELDS = frozenset(
    {
        "schema_version",
        "baseline_id",
        "execution_profile",
        "official",
        "run_id",
        "case_id",
        "case_sha256",
        "config_sha256",
        "eval_set_sha256",
        "index_provenance",
        "request",
        "request_sha256",
        "prompt",
        "prompt_sha256",
        "generation_plan",
        "retrieval",
        "response",
        "timing_ms",
        "usage",
        "cache_hit",
    }
)


def validate_mac_candidate(
    value: Any,
    *,
    case: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _CANDIDATE_FIELDS:
        raise ValueError("invalid_candidate_shape")
    _exact(value["schema_version"], "1.0", "invalid_candidate_schema_version")
    _exact(value["baseline_id"], BASELINE_ID, "candidate_baseline_mismatch")
    _exact(value["execution_profile"], MAC_LOCAL_EQUIVALENT, "candidate_profile_mismatch")
    _exact(value["official"], False, "mac_candidate_cannot_be_official")
    for field in ("case_sha256", "config_sha256", "eval_set_sha256", "request_sha256"):
        require_sha256(value[field], f"invalid_candidate_{field}")
    validate_index_provenance(value["index_provenance"])
    if not isinstance(value["run_id"], str) or not value["run_id"]:
        raise ValueError("invalid_candidate_run_id")
    if not isinstance(value["case_id"], str) or not value["case_id"]:
        raise ValueError("invalid_candidate_case_id")
    request = value["request"]
    if not isinstance(request, dict) or sha256_text(canonical_json(request)) != value["request_sha256"]:
        raise ValueError("candidate_request_hash_mismatch")
    if validate_request(request):
        raise ValueError("candidate_request_invalid")
    if request.get("options") != {"max_citations": 3}:
        raise ValueError("candidate_request_not_frozen")
    prompt = value["prompt"]
    prompt_hash = value["prompt_sha256"]
    if (prompt is None) != (prompt_hash is None):
        raise ValueError("candidate_prompt_incomplete")
    if prompt is not None:
        if not isinstance(prompt, str) or not prompt or sha256_text(prompt) != prompt_hash:
            raise ValueError("candidate_prompt_hash_mismatch")
    plan = value["generation_plan"]
    if plan is not None and not isinstance(plan, dict):
        raise ValueError("candidate_generation_plan_invalid")
    retrieval = value["retrieval"]
    if not isinstance(retrieval, list) or len(retrieval) > 10:
        raise ValueError("candidate_retrieval_invalid")
    ranks = [
        row.get("rank")
        for row in retrieval
        if isinstance(row, dict)
    ]
    if len(ranks) != len(retrieval) or ranks != list(range(1, len(ranks) + 1)):
        raise ValueError("candidate_retrieval_rank_invalid")
    scope = request["document_scope"]
    allowed_doc_ids = set(scope["doc_ids"]) if scope["mode"] == "explicit" else None
    seen_chunks: set[str] = set()
    for row in retrieval:
        if not isinstance(row, dict) or set(row) != {
            "rank",
            "doc_id",
            "chunk_id",
            "source_block_ids",
            "score",
        }:
            raise ValueError("candidate_retrieval_row_shape_invalid")
        doc_id = row["doc_id"]
        chunk_id = row["chunk_id"]
        source_block_ids = row["source_block_ids"]
        score = row["score"]
        if not isinstance(doc_id, str) or DOC_ID_RE.fullmatch(doc_id) is None:
            raise ValueError("candidate_retrieval_doc_id_invalid")
        if not isinstance(chunk_id, str) or CHUNK_ID_RE.fullmatch(chunk_id) is None:
            raise ValueError("candidate_retrieval_chunk_id_invalid")
        if chunk_id in seen_chunks:
            raise ValueError("candidate_retrieval_chunk_duplicate")
        seen_chunks.add(chunk_id)
        if (
            not isinstance(source_block_ids, list)
            or not source_block_ids
            or len(source_block_ids) != len(set(source_block_ids))
            or any(
                not isinstance(block_id, str) or BLOCK_ID_RE.fullmatch(block_id) is None
                for block_id in source_block_ids
            )
        ):
            raise ValueError("candidate_retrieval_source_blocks_invalid")
        if (
            not isinstance(score, (int, float))
            or isinstance(score, bool)
            or not math.isfinite(float(score))
            or not -1.000001 <= float(score) <= 1.000001
        ):
            raise ValueError("candidate_retrieval_score_invalid")
        if allowed_doc_ids is not None and doc_id not in allowed_doc_ids:
            raise ValueError("candidate_retrieval_scope_violation")
    response = value["response"]
    if not isinstance(response, dict) or validate_response(response):
        raise ValueError("candidate_response_contract_invalid")
    if response.get("request_id") != request.get("request_id"):
        raise ValueError("candidate_response_request_mismatch")
    citations = response.get("citations")
    if allowed_doc_ids is not None and isinstance(citations, list) and any(
        not isinstance(citation, dict) or citation.get("doc_id") not in allowed_doc_ids
        for citation in citations
    ):
        raise ValueError("candidate_response_scope_violation")
    timing = value["timing_ms"]
    usage = value["usage"]
    if not isinstance(timing, dict) or set(timing) != {"retrieval", "generation", "total"}:
        raise ValueError("candidate_measurements_invalid")
    if any(
        not isinstance(timing[field], (int, float))
        or isinstance(timing[field], bool)
        or not math.isfinite(float(timing[field]))
        or float(timing[field]) < 0
        for field in timing
    ):
        raise ValueError("candidate_timing_invalid")
    if float(timing["total"]) + 1e-6 < float(timing["retrieval"]) + float(timing["generation"]):
        raise ValueError("candidate_timing_inconsistent")
    if not isinstance(usage, dict) or set(usage) != {
        "input_tokens",
        "output_tokens",
        "embedding_tokens",
        "cost_usd",
        "gpu_seconds",
        "peak_vram_gb",
    }:
        raise ValueError("candidate_measurements_invalid")
    if any(
        not isinstance(usage[field], int) or isinstance(usage[field], bool) or usage[field] < 0
        for field in ("input_tokens", "output_tokens", "embedding_tokens")
    ):
        raise ValueError("candidate_usage_invalid")
    if (
        not isinstance(usage["cost_usd"], (int, float))
        or isinstance(usage["cost_usd"], bool)
        or not math.isfinite(float(usage["cost_usd"]))
        or float(usage["cost_usd"]) != 0.0
        or usage["gpu_seconds"] is not None
        or usage["peak_vram_gb"] is not None
    ):
        raise ValueError("candidate_usage_invalid")
    if not isinstance(value["cache_hit"], bool):
        raise ValueError("candidate_cache_hit_invalid")
    if case is not None:
        if value["case_id"] != case.get("case_id"):
            raise ValueError("candidate_case_id_mismatch")
        if sha256_text(canonical_json(dict(case))) != value["case_sha256"]:
            raise ValueError("candidate_case_hash_mismatch")
        expected_request = build_golden_request(
            case,
            config_sha256=value["config_sha256"],
            max_citations=3,
        )
        if request != expected_request:
            raise ValueError("candidate_request_case_mismatch")
    return value


def _secure_write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            for row in rows:
                output.write(canonical_json(dict(row)))
                output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _load_candidate_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as source:
        for line in source:
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("invalid_candidate_row")
                rows.append(row)
    return rows


@contextmanager
def _exclusive_candidate_lock(path: Path):  # type: ignore[no-untyped-def]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    with path.open("a+b") as lock:
        path.chmod(0o600)
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("mac_baseline_run_already_active") from error
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _run_golden_cases_unlocked(
    *,
    pipeline: Any,
    cases: Sequence[Mapping[str, Any]],
    output_path: Path,
    run_id: str,
    config_sha256: str,
    eval_set_sha256: str,
    index_provenance: Mapping[str, Any],
    max_citations: int,
) -> dict[str, int]:
    validated_provenance = validate_index_provenance(dict(index_provenance))
    existing = _load_candidate_rows(output_path)
    case_map = {
        case.get("case_id"): case
        for case in cases
        if isinstance(case.get("case_id"), str)
    }
    if len(case_map) != len(cases):
        raise ValueError("invalid_or_duplicate_case_id")
    completed: dict[str, dict[str, Any]] = {}
    for row in existing:
        case_id = row.get("case_id")
        if case_id not in case_map:
            raise ValueError("candidate_case_not_selected")
        validate_mac_candidate(row, case=case_map[case_id])
        if (
            row.get("execution_profile") != MAC_LOCAL_EQUIVALENT
            or row.get("official") is not False
            or row.get("run_id") != run_id
            or row.get("config_sha256") != config_sha256
            or row.get("eval_set_sha256") != eval_set_sha256
            or row.get("index_provenance") != validated_provenance
        ):
            raise ValueError("candidate_resume_identity_mismatch")
        if not isinstance(case_id, str) or case_id in completed:
            raise ValueError("invalid_or_duplicate_candidate_case")
        completed[case_id] = row

    executed = 0
    resumed = 0
    requested_ids: set[str] = set()
    requested_order: list[str] = []
    for case in cases:
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id or case_id in requested_ids:
            raise ValueError("invalid_or_duplicate_case_id")
        requested_ids.add(case_id)
        requested_order.append(case_id)
        if case_id in completed:
            resumed += 1
            continue
        request = build_golden_request(
            case,
            config_sha256=config_sha256,
            max_citations=max_citations,
        )
        recorder = getattr(pipeline, "generator", None)
        reset = getattr(recorder, "reset_transcript", None)
        if callable(reset):
            reset()
        result = pipeline.query(
            request,
            trace_context={
                "run_id": run_id,
                "case_id": case_id,
                "eval_set_sha256": eval_set_sha256,
                "config_sha256": config_sha256,
                "index_config_sha256": validated_provenance["index_config_sha256"],
            },
        )
        prompt = getattr(recorder, "last_prompt", None)
        plan = getattr(recorder, "last_plan", None)
        prompt_sha256 = sha256_text(prompt) if isinstance(prompt, str) and prompt else None
        row = build_mac_candidate(
            case=case,
            request=request,
            result=result,
            run_id=run_id,
            config_sha256=config_sha256,
            eval_set_sha256=eval_set_sha256,
            index_provenance=validated_provenance,
            prompt=prompt,
            prompt_sha256=prompt_sha256,
            generation_plan=plan,
        )
        validate_mac_candidate(row, case=case)
        completed[case_id] = row
        executed += 1
        ordered = [completed[item] for item in requested_order if item in completed]
        _secure_write_jsonl(output_path, ordered)
    return {"executed": executed, "resumed": resumed, "total": len(requested_ids)}


def run_golden_cases(
    *,
    pipeline: Any,
    cases: Sequence[Mapping[str, Any]],
    output_path: Path,
    private_output_root: Path,
    run_id: str,
    config_sha256: str,
    eval_set_sha256: str,
    index_provenance: Mapping[str, Any],
    max_citations: int,
) -> dict[str, int]:
    validate_index_provenance(dict(index_provenance))
    private_output_root = private_output_root.resolve()
    private_output_root.mkdir(parents=True, exist_ok=True)
    safe_output = require_within(
        output_path.resolve(),
        private_output_root,
        "candidate_output_outside_private_root",
    )
    with _exclusive_candidate_lock(safe_output.with_suffix(safe_output.suffix + ".lock")):
        return _run_golden_cases_unlocked(
            pipeline=pipeline,
            cases=cases,
            output_path=safe_output,
            run_id=run_id,
            config_sha256=config_sha256,
            eval_set_sha256=eval_set_sha256,
            index_provenance=index_provenance,
            max_citations=max_citations,
        )


def _ranked_retrieval(candidate: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    retrieval = candidate.get("retrieval")
    if not isinstance(retrieval, list):
        return []
    return sorted(
        (row for row in retrieval if isinstance(row, Mapping)),
        key=lambda row: row.get("rank") if isinstance(row.get("rank"), int) else 10**9,
    )


def _citation_valid(candidate: Mapping[str, Any]) -> float | None:
    response = candidate.get("response")
    if not isinstance(response, Mapping) or response.get("status") == "error":
        return None
    citations = response.get("citations")
    if not isinstance(citations, list):
        return 0.0
    if response.get("status") == "abstained":
        return float(not citations)
    if response.get("status") != "answered" or not citations:
        return 0.0
    retrieved = {
        (row.get("doc_id"), row.get("chunk_id")): set(row.get("source_block_ids", []))
        for row in _ranked_retrieval(candidate)
        if isinstance(row.get("source_block_ids"), list)
    }
    for citation in citations:
        if not isinstance(citation, Mapping):
            return 0.0
        key = (citation.get("doc_id"), citation.get("chunk_id"))
        blocks = citation.get("source_block_ids")
        if key not in retrieved or not isinstance(blocks, list) or not set(blocks) <= retrieved[key]:
            return 0.0
    return 1.0


def score_provisional_candidates(
    cases: Sequence[Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    case_map: dict[str, Mapping[str, Any]] = {}
    for case in cases:
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id or case_id in case_map:
            raise ValueError("invalid_or_duplicate_case_id")
        case_map[case_id] = case
    candidate_map: dict[str, Mapping[str, Any]] = {}
    config_hashes: set[str] = set()
    eval_hashes: set[str] = set()
    run_ids: set[str] = set()
    index_provenances: set[str] = set()
    for candidate in candidates:
        if candidate.get("execution_profile") != MAC_LOCAL_EQUIVALENT:
            raise ValueError("official_or_unknown_profile_not_allowed")
        if candidate.get("official") is not False or "stack_id" in candidate:
            raise ValueError("mac_candidate_cannot_be_official")
        case_id = candidate.get("case_id")
        if not isinstance(case_id, str) or case_id not in case_map or case_id in candidate_map:
            raise ValueError("invalid_or_duplicate_candidate_case")
        validate_mac_candidate(candidate, case=case_map[case_id])
        candidate_map[case_id] = candidate
        if isinstance(candidate.get("config_sha256"), str):
            config_hashes.add(candidate["config_sha256"])
        if isinstance(candidate.get("eval_set_sha256"), str):
            eval_hashes.add(candidate["eval_set_sha256"])
        if isinstance(candidate.get("run_id"), str):
            run_ids.add(candidate["run_id"])
        index_provenances.add(canonical_json(candidate["index_provenance"]))
    if (
        len(config_hashes) != 1
        or len(eval_hashes) != 1
        or len(run_ids) != 1
        or len(index_provenances) != 1
    ):
        raise ValueError("candidate_hash_identity_mismatch")

    doc_recall = {k: [] for k in K_VALUES}
    block_recall = {k: [] for k in K_VALUES}
    all_docs = {k: [] for k in K_VALUES}
    reciprocal_ranks: list[float] = []
    ndcg_values: list[float] = []
    citation_validities: list[float] = []
    response_contract_validities: list[float] = []
    abstention_matches: list[float] = []
    total_latencies: list[float] = []
    retrieval_latencies: list[float] = []
    generation_latencies: list[float] = []
    errors = 0
    per_case: list[dict[str, Any]] = []

    for case_id, candidate in candidate_map.items():
        case = case_map[case_id]
        gold = case.get("gold") if isinstance(case.get("gold"), Mapping) else {}
        relevant_docs = {
            item for item in gold.get("required_doc_ids", []) if isinstance(item, str)
        }
        evidence = gold.get("evidence_refs", [])
        relevant_blocks = {
            row.get("source_block_id")
            for row in evidence
            if isinstance(row, Mapping) and isinstance(row.get("source_block_id"), str)
        } if isinstance(evidence, list) else set()
        ranked = _ranked_retrieval(candidate)
        ranked_docs = [row.get("doc_id") for row in ranked if isinstance(row.get("doc_id"), str)]
        case_metrics: dict[str, Any] = {"case_id": case_id}
        if relevant_docs:
            for k in K_VALUES:
                observed_docs = set(ranked_docs[:k])
                doc_value = len(observed_docs & relevant_docs) / len(relevant_docs)
                doc_recall[k].append(doc_value)
                if case.get("task_type") == "multi_doc_compare":
                    all_docs[k].append(float(relevant_docs <= observed_docs))
                case_metrics[f"document_recall_at_{k}"] = round(doc_value, 6)
                if relevant_blocks:
                    observed_blocks: set[str] = set()
                    for row in ranked[:k]:
                        blocks = row.get("source_block_ids")
                        if isinstance(blocks, list):
                            observed_blocks.update(item for item in blocks if isinstance(item, str))
                    block_value = len(observed_blocks & relevant_blocks) / len(relevant_blocks)
                    block_recall[k].append(block_value)
                    case_metrics[f"source_block_recall_at_{k}"] = round(block_value, 6)
            first_rank = next(
                (index + 1 for index, doc_id in enumerate(ranked_docs[:10]) if doc_id in relevant_docs),
                None,
            )
            reciprocal_rank = 0.0 if first_rank is None else 1.0 / first_rank
            reciprocal_ranks.append(reciprocal_rank)
            seen: set[str] = set()
            relevance: list[int] = []
            for doc_id in ranked_docs[:10]:
                matched = doc_id in relevant_docs and doc_id not in seen
                relevance.append(int(matched))
                if matched:
                    seen.add(doc_id)
            ideal = [1] * min(len(relevant_docs), 10)
            ndcg = 0.0 if not ideal else _dcg(relevance) / _dcg(ideal)
            ndcg_values.append(ndcg)
            case_metrics.update({"mrr_at_10": round(reciprocal_rank, 6), "ndcg_at_10": round(ndcg, 6)})

        response = candidate.get("response")
        status = response.get("status") if isinstance(response, Mapping) else None
        if status == "error":
            errors += 1
        contract_value = 0.0
        if isinstance(response, dict):
            contract_value = float(not validate_response(response))
        response_contract_validities.append(contract_value)
        citation_value = _citation_valid(candidate)
        if citation_value is not None:
            citation_validities.append(citation_value)
        expected_abstain = gold.get("decision") == "abstain"
        if status == "error":
            abstention_matches.append(0.0)
        else:
            behavior_matches = (status == "abstained") == expected_abstain
            if expected_abstain and status == "abstained" and isinstance(response, Mapping):
                abstention = response.get("abstention")
                behavior_matches = (
                    isinstance(abstention, Mapping)
                    and abstention.get("reason") == gold.get("abstain_reason")
                )
            abstention_matches.append(float(behavior_matches and bool(contract_value)))
        timing = candidate.get("timing_ms")
        if isinstance(timing, Mapping):
            for field, values in (
                ("total", total_latencies),
                ("retrieval", retrieval_latencies),
                ("generation", generation_latencies),
            ):
                value = timing.get(field)
                if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
                    values.append(float(value))
        case_metrics.update(
            {
                "status": status,
                "response_contract_valid": bool(contract_value),
                "citation_valid": None if citation_value is None else bool(citation_value),
            }
        )
        per_case.append(case_metrics)

    scored = len(candidate_map)
    suite_complete = scored == len(case_map) and scored > 0
    gold_approved = bool(cases) and all(
        isinstance(case.get("review"), Mapping)
        and case["review"].get("status") == "approved"
        for case in cases
    )
    return {
        "schema_version": "1.0",
        "baseline_id": BASELINE_ID,
        "execution_profile": MAC_LOCAL_EQUIVALENT,
        "evaluation_tier": "provisional_non_official",
        "official": False,
        "passed": False,
        "diagnostics_completed": scored > 0,
        "suite_complete": suite_complete,
        "semantic_judgment": "not_run",
        "semantic_blocker": "fixed_gpt_5_6_sol_judge_and_human_review_not_run",
        "gold_review_status": "approved" if gold_approved else "draft",
        "run_id": next(iter(run_ids)),
        "config_sha256": next(iter(config_hashes)),
        "eval_set_sha256": next(iter(eval_hashes)),
        "index_provenance": json.loads(next(iter(index_provenances))),
        "counts": {
            "selected": len(case_map),
            "scored": scored,
            "missing": len(case_map) - scored,
            "runtime_errors": errors,
        },
        "metrics": {
            "retrieval": {
                **{f"document_recall_at_{k}": _mean(values) for k, values in doc_recall.items()},
                **{f"source_block_recall_at_{k}": _mean(values) for k, values in block_recall.items()},
                **{f"all_required_docs_recalled_at_{k}": _mean(values) for k, values in all_docs.items()},
                "mrr_at_10": _mean(reciprocal_ranks),
                "ndcg_at_10": _mean(ndcg_values),
            },
            "contract": {
                "response_contract_validity": _mean(response_contract_validities),
                "citation_validity": _mean(citation_validities),
            },
            "behavior": {"abstention_match": _mean(abstention_matches)},
            "operations": {
                "runtime_error_rate": None if scored == 0 else round(errors / scored, 6),
                "latency_total_p50_ms": _percentile(total_latencies, 0.50),
                "latency_total_p95_ms": _percentile(total_latencies, 0.95),
                "latency_retrieval_p50_ms": _percentile(retrieval_latencies, 0.50),
                "latency_generation_p50_ms": _percentile(generation_latencies, 0.50),
            },
        },
        "per_case": sorted(per_case, key=lambda row: row["case_id"]),
    }


def content_free_receipt(report: Mapping[str, Any]) -> dict[str, Any]:
    required = (
        "schema_version",
        "baseline_id",
        "execution_profile",
        "evaluation_tier",
        "official",
        "passed",
        "diagnostics_completed",
        "suite_complete",
        "semantic_judgment",
        "semantic_blocker",
        "gold_review_status",
        "run_id",
        "config_sha256",
        "eval_set_sha256",
        "index_provenance",
        "counts",
        "metrics",
    )
    if any(field not in report for field in required):
        raise ValueError("invalid_provisional_report")
    frozen_strings = {
        "schema_version": "1.0",
        "baseline_id": BASELINE_ID,
        "execution_profile": MAC_LOCAL_EQUIVALENT,
        "evaluation_tier": "provisional_non_official",
        "semantic_judgment": "not_run",
        "semantic_blocker": "fixed_gpt_5_6_sol_judge_and_human_review_not_run",
    }
    if any(report.get(field) != expected for field, expected in frozen_strings.items()):
        raise ValueError("invalid_provisional_report_identity")
    if report.get("official") is not False or report.get("passed") is not False:
        raise ValueError("provisional_receipt_cannot_be_official")
    if not isinstance(report.get("diagnostics_completed"), bool) or not isinstance(
        report.get("suite_complete"), bool
    ):
        raise ValueError("invalid_provisional_completion_state")
    if report.get("gold_review_status") not in {"draft", "approved"}:
        raise ValueError("invalid_provisional_gold_status")
    run_id = report.get("run_id")
    if (
        not isinstance(run_id, str)
        or not 1 <= len(run_id) <= 128
        or any(not (character.isalnum() or character in "-._:") for character in run_id)
    ):
        raise ValueError("invalid_provisional_report_identity")
    require_sha256(report["config_sha256"], "invalid_config_hash")
    require_sha256(report["eval_set_sha256"], "invalid_eval_set_hash")
    validate_index_provenance(report["index_provenance"])
    counts = report.get("counts")
    if not isinstance(counts, dict) or set(counts) != {
        "selected",
        "scored",
        "missing",
        "runtime_errors",
    }:
        raise ValueError("invalid_provisional_counts")
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in counts.values()):
        raise ValueError("invalid_provisional_counts")
    metrics = report.get("metrics")
    metric_fields = {
        "retrieval": {
            *(f"document_recall_at_{k}" for k in K_VALUES),
            *(f"source_block_recall_at_{k}" for k in K_VALUES),
            *(f"all_required_docs_recalled_at_{k}" for k in K_VALUES),
            "mrr_at_10",
            "ndcg_at_10",
        },
        "contract": {"response_contract_validity", "citation_validity"},
        "behavior": {"abstention_match"},
        "operations": {
            "runtime_error_rate",
            "latency_total_p50_ms",
            "latency_total_p95_ms",
            "latency_retrieval_p50_ms",
            "latency_generation_p50_ms",
        },
    }
    if not isinstance(metrics, dict) or set(metrics) != set(metric_fields):
        raise ValueError("invalid_provisional_metrics")
    for section, fields in metric_fields.items():
        values = metrics.get(section)
        if not isinstance(values, dict) or set(values) != fields:
            raise ValueError("invalid_provisional_metrics")
        if any(
            value is not None
            and (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(float(value))
            )
            for value in values.values()
        ):
            raise ValueError("invalid_provisional_metrics")
    return {field: json.loads(json.dumps(report[field], ensure_ascii=False)) for field in required}


def _secure_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            json.dump(dict(value), output, ensure_ascii=False, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _write_public_receipt(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            json.dump(dict(value), output, ensure_ascii=False, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        path.chmod(0o644)
    finally:
        temporary.unlink(missing_ok=True)


def preflight_receipt(verified: VerifiedBaseline) -> dict[str, Any]:
    storage = local_workspace_storage(verified)
    dependencies = verify_dependency_lock(verified)
    kure_cached = False
    qwen_tokenizer_cached = False
    ollama_verified = False
    index_verified = False
    try:
        _configure_hf_cache(verified.hf_cache_path, offline=True)
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id=KURE_MODEL_ID,
            revision=KURE_MODEL_REVISION,
            cache_dir=str(verified.hf_cache_path / "hub"),
            local_files_only=True,
        )
        kure_cached = True
    except Exception:
        kure_cached = False
    try:
        _configure_hf_cache(verified.hf_cache_path, offline=True)
        from huggingface_hub import snapshot_download
        from midprojectrag.stacks.local.qwen_tokenizer import PinnedQwenChatTokenCounter

        snapshot_download(
            repo_id=QWEN3_AWQ_MODEL,
            revision=QWEN3_AWQ_REVISION,
            cache_dir=str(verified.hf_cache_path / "hub"),
            local_files_only=True,
            allow_patterns=list(QWEN_TOKENIZER_ALLOW_PATTERNS),
            ignore_patterns=list(QWEN_TOKENIZER_IGNORE_PATTERNS),
        )
        PinnedQwenChatTokenCounter().count_chat(
            system=LOCAL_SYSTEM_INSTRUCTIONS,
            prompt="Qwen preflight",
        )
        qwen_tokenizer_cached = True
    except Exception:
        qwen_tokenizer_cached = False
    try:
        from midprojectrag.stacks.local.generation import OllamaGenerator

        generator = OllamaGenerator(
            model=verified.config["generation"]["mac_equivalent_model"],
            max_output_tokens=verified.config["generation"]["max_output_tokens"],
            context_tokens=verified.config["generation"]["mac_transport_context_tokens"],
            timeout_seconds=10,
        )
        generator._verify_model()
        ollama_verified = True
    except Exception:
        ollama_verified = False
    try:
        current_mac_index_provenance(verified)
        index_verified = True
    except Exception:
        index_verified = False
    ready = kure_cached and qwen_tokenizer_cached and ollama_verified and index_verified
    return {
        "passed": ready,
        "contract_valid": True,
        "baseline_id": BASELINE_ID,
        "execution_profile": MAC_LOCAL_EQUIVALENT,
        "official": False,
        "config_sha256": verified.config_sha256,
        "corpus_manifest_sha256": verified.config["corpus"]["manifest_sha256"],
        "chunks_sha256": verified.config["corpus"]["chunks_sha256"],
        "eval_set_sha256": verified.eval_set_sha256,
        "document_count": verified.config["corpus"]["document_count"],
        "chunk_count": verified.config["corpus"]["chunk_count"],
        "case_count": len(verified.cases),
        "gold_review_status": verified.config["evaluation"]["review_status"],
        "kure_cached": kure_cached,
        "qwen_tokenizer_cached": qwen_tokenizer_cached,
        "ollama_verified": ollama_verified,
        "index_ready": index_verified,
        "storage": storage,
        "dependencies": dependencies,
    }


def execute_mac_cases(
    verified: VerifiedBaseline,
    *,
    limit: int | None = None,
    embedding_device: str = "cpu",
) -> dict[str, Any]:
    if limit is not None and (
        not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= len(verified.cases)
    ):
        raise ValueError("invalid_case_limit")
    selected = verified.cases if limit is None else verified.cases[:limit]
    index_provenance = current_mac_index_provenance(verified)
    pipeline = load_mac_pipeline(verified, embedding_device=embedding_device)
    run_id = (
        f"mac-{verified.config_sha256[:12]}-{verified.eval_set_sha256[:12]}-"
        f"{index_provenance['vectors_sha256'][:12]}-{index_provenance['metadata_sha256'][:12]}"
    )
    result = run_golden_cases(
        pipeline=pipeline,
        cases=selected,
        output_path=verified.candidate_path,
        private_output_root=verified.candidate_path.parent,
        run_id=run_id,
        config_sha256=verified.config_sha256,
        eval_set_sha256=verified.eval_set_sha256,
        index_provenance=index_provenance,
        max_citations=verified.config["retrieval"]["max_citations"],
    )
    pipeline.flush_observability()
    return {
        "passed": True,
        "baseline_id": BASELINE_ID,
        "execution_profile": MAC_LOCAL_EQUIVALENT,
        "official": False,
        "run_id": run_id,
        **result,
    }


def score_mac_candidates(verified: VerifiedBaseline) -> dict[str, Any]:
    candidates = _load_candidate_rows(verified.candidate_path)
    index_provenance = current_mac_index_provenance(verified)
    expected_run_id = (
        f"mac-{verified.config_sha256[:12]}-{verified.eval_set_sha256[:12]}-"
        f"{index_provenance['vectors_sha256'][:12]}-{index_provenance['metadata_sha256'][:12]}"
    )
    for candidate in candidates:
        if (
            candidate.get("baseline_id") != BASELINE_ID
            or candidate.get("config_sha256") != verified.config_sha256
            or candidate.get("eval_set_sha256") != verified.eval_set_sha256
            or candidate.get("run_id") != expected_run_id
            or candidate.get("index_provenance") != index_provenance
        ):
            raise ValueError("candidate_verified_baseline_identity_mismatch")
    report = score_provisional_candidates(verified.cases, candidates)
    _secure_write_json(verified.private_score_path, report)
    receipt = content_free_receipt(report)
    _write_public_receipt(verified.public_receipt_path, receipt)
    return receipt


def _default_config(repo_root: Path) -> Path:
    return repo_root / "configs/rag/gcp-local-kure-qwen3-8b-awq-refined98-page-v1.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pinned GCP-local baseline with Mac-equivalent proof")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight")
    commands.add_parser("prepare-model")
    index = commands.add_parser("index")
    index.add_argument("--device", choices=("auto", "cpu", "mps"), default="auto")
    run = commands.add_parser("run")
    run.add_argument("--limit", type=int)
    run.add_argument("--embedding-device", choices=("auto", "cpu", "mps"), default="cpu")
    commands.add_parser("score")
    all_command = commands.add_parser("all")
    all_command.add_argument("--limit", type=int)
    all_command.add_argument("--index-device", choices=("auto", "cpu", "mps"), default="auto")
    all_command.add_argument("--embedding-device", choices=("auto", "cpu", "mps"), default="cpu")
    return parser


def _safe_error(error: BaseException) -> str:
    value = str(error)
    if value and len(value) <= 96 and all(character.islower() or character.isdigit() or character == "_" for character in value):
        return value
    return "gcp_local_baseline_failed"


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    config_path = (args.config or _default_config(repo_root)).resolve()
    try:
        verified = load_verified_baseline(repo_root=repo_root, config_path=config_path)
        if args.command == "preflight":
            result = preflight_receipt(verified)
        elif args.command == "prepare-model":
            result = prepare_kure_model(verified)
        elif args.command == "index":
            result = build_mac_semantic_index(verified, device=args.device)
        elif args.command == "run":
            result = execute_mac_cases(
                verified,
                limit=args.limit,
                embedding_device=args.embedding_device,
            )
        elif args.command == "score":
            result = score_mac_candidates(verified)
        elif args.command == "all":
            index_result = build_mac_semantic_index(verified, device=args.index_device)
            run_result = execute_mac_cases(
                verified,
                limit=args.limit,
                embedding_device=args.embedding_device,
            )
            score_result = score_mac_candidates(verified)
            result = {
                "passed": True,
                "baseline_id": BASELINE_ID,
                "execution_profile": MAC_LOCAL_EQUIVALENT,
                "official": False,
                "index": index_result,
                "run": run_result,
                "score": score_result,
            }
        else:
            raise ValueError("unsupported_baseline_command")
    except (ValueError, RuntimeError, OSError) as error:
        print(json.dumps({"passed": False, "error": _safe_error(error)}, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
