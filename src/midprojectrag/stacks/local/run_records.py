from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any, Protocol

from midprojectrag.evaluation import validate_run_record


GCP_EMBEDDING_MODEL = "nlpai-lab/KURE-v1"
GCP_GENERATOR_MODEL = "Qwen/Qwen3-8B-AWQ"
GCP_EMBEDDING_MODEL_REVISION = "4ed4540949c70b7da2c74004a915e1f2d5e46e4f"
GCP_GENERATOR_MODEL_REVISION = "4da05a8edb55c6046cce958586c33b61da07bb79"
GCP_EMBEDDING_DIMENSIONS = 1024
GCP_RUNTIME = "vllm"
GCP_RUNTIME_VERSION = "0.8.5.post1"
GCP_QUANTIZATION = "awq-int4"

RUN_CONTEXT_FIELDS = frozenset(
    {
        "run_id",
        "case_id",
        "eval_set_sha256",
        "config_sha256",
        "git_commit",
        "environment",
    }
)


class PipelineRunResult(Protocol):
    response: dict[str, Any]
    retrieval: list[dict[str, Any]]
    timing_ms: dict[str, float]
    usage: dict[str, int | float | None]
    cache_hit: bool


def unjudged_judgment() -> dict[str, Any]:
    return {
        "matched_key_point_ids": [],
        "correctness": None,
        "faithfulness": None,
        "factual_claim_coverage": None,
        "citation_validity": None,
        "follow_up_success": None,
        "safe_abstention": None,
        "reviewer_ids": [],
    }


def build_gcp_run_record(
    result: PipelineRunResult,
    *,
    context: Mapping[str, Any],
    corpus_manifest_sha256: str,
    embedding_model_revision: str,
    generator_model_revision: str,
    index_config_sha256: str,
    runtime_version: str,
    seed: int | None,
    temperature: float | None,
) -> dict[str, Any]:
    """Compose and validate one official GCP-local evaluation run record."""

    if not isinstance(context, Mapping) or set(context) != RUN_CONTEXT_FIELDS:
        raise ValueError("invalid_run_context")
    if runtime_version != GCP_RUNTIME_VERSION:
        raise ValueError("gcp_runtime_version_mismatch")
    record = {
        "schema_version": "1.0",
        "run_id": context["run_id"],
        "case_id": context["case_id"],
        "stack_id": "gcp_local",
        "corpus_manifest_sha256": corpus_manifest_sha256,
        "eval_set_sha256": context["eval_set_sha256"],
        "config_sha256": context["config_sha256"],
        "git_commit": context["git_commit"],
        "generator_model": GCP_GENERATOR_MODEL,
        "embedding_model": GCP_EMBEDDING_MODEL,
        "embedding_dimensions": GCP_EMBEDDING_DIMENSIONS,
        "index_config_sha256": index_config_sha256,
        "embedding_model_revision": embedding_model_revision,
        "generator_model_revision": generator_model_revision,
        "runtime": GCP_RUNTIME,
        "runtime_version": runtime_version,
        "quantization": GCP_QUANTIZATION,
        "environment": copy.deepcopy(context["environment"]),
        "retrieval": copy.deepcopy(result.retrieval),
        "response": copy.deepcopy(result.response),
        "timing_ms": copy.deepcopy(result.timing_ms),
        "usage": copy.deepcopy(result.usage),
        "judgment": unjudged_judgment(),
        "seed": seed,
        "temperature": temperature,
        "cache_hit": result.cache_hit,
    }
    if validate_run_record(record):
        raise ValueError("run_record_contract_failed")
    return record
