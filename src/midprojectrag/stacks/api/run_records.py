from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any, Protocol

from midprojectrag.evaluation import validate_run_record

from .generation import DEFAULT_REASONING_EFFORT


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


def build_api_run_record(
    result: PipelineRunResult,
    *,
    context: Mapping[str, Any],
    corpus_manifest_sha256: str,
    generator_model: str,
    embedding_model: str,
    seed: int | None,
    temperature: float | None,
    api_profile: str = "assignment",
    embedding_dimensions: int | None = None,
    index_config_sha256: str | None = None,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> dict[str, Any]:
    """Compose and validate one metadata-bounded API run record."""

    if not isinstance(context, Mapping) or set(context) != RUN_CONTEXT_FIELDS:
        raise ValueError("invalid_run_context")
    if reasoning_effort != DEFAULT_REASONING_EFFORT:
        raise ValueError("reasoning_effort_not_supported")
    record = {
        "schema_version": "1.0",
        "run_id": context["run_id"],
        "case_id": context["case_id"],
        "stack_id": "api",
        "corpus_manifest_sha256": corpus_manifest_sha256,
        "eval_set_sha256": context["eval_set_sha256"],
        "config_sha256": context["config_sha256"],
        "git_commit": context["git_commit"],
        "generator_model": generator_model,
        "embedding_model": embedding_model,
        "api_profile": api_profile,
        "environment": copy.deepcopy(context["environment"]),
        "retrieval": copy.deepcopy(result.retrieval),
        "response": copy.deepcopy(result.response),
        "timing_ms": copy.deepcopy(result.timing_ms),
        "usage": copy.deepcopy(result.usage),
        "judgment": unjudged_judgment(),
        "seed": seed,
        "temperature": temperature,
        "reasoning_effort": reasoning_effort,
        "cache_hit": result.cache_hit,
    }
    if embedding_dimensions is not None:
        record["embedding_dimensions"] = embedding_dimensions
    if index_config_sha256 is not None:
        record["index_config_sha256"] = index_config_sha256
    if validate_run_record(record):
        raise ValueError("run_record_contract_failed")
    return record
