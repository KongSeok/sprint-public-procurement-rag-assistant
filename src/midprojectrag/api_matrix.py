from __future__ import annotations

import argparse
import copy
import fcntl
import json
import math
import os
import platform
import re
import shutil
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import fmean
from threading import Lock
from types import SimpleNamespace
from typing import Any, Protocol

from midprojectrag.evaluation import (
    TASK_TYPES,
    dataset_sha256,
    validate_case,
    validate_response,
    validate_run_record,
)
from midprojectrag.ingest.common import (
    canonical_json,
    read_jsonl,
    require_within,
    sha256_file,
    sha256_text,
    write_json,
    write_jsonl,
)
from midprojectrag.indexing.budget import BudgetLedger
from midprojectrag.indexing.chunking import validate_chunk
from midprojectrag.indexing.exact_index import ExactDenseIndex
from midprojectrag.observability import NoopObserver, Observer


EMBEDDING_MODELS = ("text-embedding-3-small", "text-embedding-3-large")
GENERATOR_MODELS = ("gpt-5-nano", "gpt-5-mini")
DEFAULT_DIMENSIONS = (
    ("text-embedding-3-small", 1536),
    ("text-embedding-3-large", 3072),
)
PERSONAL_API_PROFILE = "personal_experimental"
EXPECTED_DEV_COUNTS = {task: 10 for task in TASK_TYPES}
SAFE_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
GIT_COMMIT_RE = re.compile(r"^(?:uncommitted|[0-9a-f]{7,64})$")
ERROR_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
DEFAULT_CASE_INTERVAL_SECONDS = 6.0
REASONING_EFFORT = "minimal"


@dataclass(frozen=True)
class MatrixPaths:
    repo_root: Path
    private_root: Path
    chunks_path: Path
    chunk_metadata_path: Path
    manifest_path: Path
    dev_path: Path
    indexes_root: Path
    caches_root: Path
    outputs_root: Path
    tokenizer_cache_dir: Path
    budget_ledger_path: Path
    dependency_lock_path: Path

    @classmethod
    def from_repo_root(cls, repo_root: Path) -> "MatrixPaths":
        root = repo_root.resolve()
        private_root = root / "private" / "corpus_v1" / "private"
        return cls(
            repo_root=root,
            private_root=private_root,
            chunks_path=private_root / "chunks.page-v1.jsonl",
            chunk_metadata_path=private_root / "chunks.page-v1.jsonl.metadata.json",
            manifest_path=private_root / "manifest.rhwp.jsonl",
            dev_path=root / "evaluation" / "private" / "dev.jsonl",
            indexes_root=private_root / "indexes" / "api",
            caches_root=private_root / "caches" / "api",
            outputs_root=private_root / "outputs" / "api",
            tokenizer_cache_dir=private_root / "tiktoken-cache",
            budget_ledger_path=private_root / "api-budget.2x2.json",
            dependency_lock_path=root / "pyproject.toml",
        )


@dataclass(frozen=True)
class MatrixSettings:
    embedding_models: tuple[str, ...] = EMBEDDING_MODELS
    generator_models: tuple[str, ...] = GENERATOR_MODELS
    embedding_dimensions: tuple[tuple[str, int], ...] = DEFAULT_DIMENSIONS
    retrieval_top_k: int = 10
    context_top_k: int = 5
    max_citations: int = 3
    max_output_tokens: int = 2000
    reasoning_effort: str = REASONING_EFFORT
    case_interval_seconds: float = DEFAULT_CASE_INTERVAL_SECONDS
    max_api_budget_usd: Decimal = Decimal("5")
    observability: str = "disabled"
    approve_langfuse_metadata_egress: bool = False
    require_approved_dev: bool = False
    run_label: str = "dev40-provisional"
    git_commit: str = "uncommitted"
    expected_index_engine: str = "numpy"
    api_profile: str = PERSONAL_API_PROFILE

    def __post_init__(self) -> None:
        if self.embedding_models != EMBEDDING_MODELS:
            raise ValueError("matrix_embedding_models_mismatch")
        if self.generator_models != GENERATOR_MODELS:
            raise ValueError("matrix_generator_models_mismatch")
        dimensions = dict(self.embedding_dimensions)
        if len(dimensions) != len(self.embedding_dimensions) or set(dimensions) != set(EMBEDDING_MODELS):
            raise ValueError("matrix_embedding_dimensions_invalid")
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in dimensions.values()):
            raise ValueError("matrix_embedding_dimensions_invalid")
        if not 1 <= self.context_top_k <= self.retrieval_top_k:
            raise ValueError("matrix_retrieval_limits_invalid")
        if not 1 <= self.max_citations <= 20:
            raise ValueError("matrix_max_citations_invalid")
        if not 1 <= self.max_output_tokens <= 4000:
            raise ValueError("matrix_max_output_tokens_invalid")
        if self.reasoning_effort != REASONING_EFFORT:
            raise ValueError("matrix_reasoning_effort_must_be_minimal")
        interval = self.case_interval_seconds
        if (
            not isinstance(interval, (int, float))
            or isinstance(interval, bool)
            or not math.isfinite(interval)
            or interval < 0
        ):
            raise ValueError("matrix_case_interval_invalid")
        object.__setattr__(self, "case_interval_seconds", float(interval))
        try:
            budget = Decimal(str(self.max_api_budget_usd))
        except (InvalidOperation, ValueError) as error:
            raise ValueError("matrix_budget_invalid") from error
        if not budget.is_finite() or budget != Decimal("5"):
            raise ValueError("matrix_budget_must_equal_five_usd")
        if self.observability not in {"disabled", "memory", "langfuse"}:
            raise ValueError("matrix_observability_invalid")
        if self.observability == "langfuse" and not self.approve_langfuse_metadata_egress:
            raise ValueError("langfuse_metadata_egress_not_approved")
        if SAFE_LABEL_RE.fullmatch(self.run_label) is None:
            raise ValueError("matrix_run_label_invalid")
        if GIT_COMMIT_RE.fullmatch(self.git_commit) is None:
            raise ValueError("matrix_git_commit_invalid")
        if self.expected_index_engine not in {"numpy", "faiss"}:
            raise ValueError("matrix_index_engine_invalid")
        if self.api_profile != PERSONAL_API_PROFILE:
            raise ValueError("matrix_api_profile_mismatch")

    @property
    def dimensions_by_model(self) -> dict[str, int]:
        return dict(self.embedding_dimensions)


class _GenerationStartLimiter:
    """Serialize provider generation starts with a monotonic minimum interval."""

    def __init__(
        self,
        interval_seconds: float,
        *,
        monotonic: Callable[[], float],
        sleeper: Callable[[float], None],
    ) -> None:
        self.interval_seconds = interval_seconds
        self._monotonic = monotonic
        self._sleeper = sleeper
        self._last_started_at: float | None = None
        self._lock = Lock()

    def wait_for_start(self) -> None:
        with self._lock:
            now = self._now()
            if self._last_started_at is not None:
                remaining = self.interval_seconds - (now - self._last_started_at)
                while remaining > 0:
                    self._sleeper(remaining)
                    now = self._now()
                    remaining = self.interval_seconds - (now - self._last_started_at)
            self._last_started_at = now

    def _now(self) -> float:
        value = self._monotonic()
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise ValueError("matrix_monotonic_clock_invalid")
        return float(value)


@dataclass(frozen=True)
class VerifiedInputs:
    chunks: list[dict[str, Any]]
    cases: list[dict[str, Any]]
    corpus_manifest_sha256: str
    eval_set_sha256: str
    chunk_artifact_sha256: str
    chunk_config_sha256: str
    review_statuses: dict[str, int]
    indexes: dict[str, ExactDenseIndex]
    index_metadata: dict[str, dict[str, Any]]
    index_metadata_sha256: dict[str, str]
    index_config: dict[str, dict[str, Any]]

    @property
    def evaluation_status(self) -> str:
        return (
            "reviewed_candidate"
            if self.review_statuses == {"approved": len(self.cases)}
            else "provisional_unreviewed_dev"
        )


@dataclass(frozen=True)
class ComboRuntime:
    embedding_model: str
    generator_model: str
    index: ExactDenseIndex
    index_metadata: Mapping[str, Any]
    query_cache_dir: Path
    tokenizer_cache_dir: Path
    budget: BudgetLedger
    observer: Observer
    corpus_manifest_sha256: str
    retrieval_top_k: int
    context_top_k: int
    max_citations: int
    max_output_tokens: int
    config: Mapping[str, Any]
    config_sha256: str
    api_profile: str
    index_config_sha256: str
    reasoning_effort: str
    generation_start_limiter: _GenerationStartLimiter


class PipelineLike(Protocol):
    def query(
        self,
        request: dict[str, Any],
        *,
        trace_context: Mapping[str, Any] | None = None,
    ) -> Any: ...

    def flush_observability(self) -> None: ...


PipelineFactory = Callable[[ComboRuntime], PipelineLike]
RunRecordBuilder = Callable[..., dict[str, Any]]
RunRecordValidator = Callable[[Any], list[dict[str, str]]]


def _require_private_path(path: Path, paths: MatrixPaths, error_code: str) -> Path:
    return require_within(path.resolve(), paths.private_root.resolve(), error_code)


def _profiled_model_dir(root: Path, settings: MatrixSettings, model: str) -> Path:
    resolved_root = root.resolve()
    profile_root = require_within(
        (resolved_root / settings.api_profile).resolve(),
        resolved_root,
        "matrix_profile_path_outside_api_root",
    )
    slug = f"{model}-{settings.dimensions_by_model[model]}"
    model_dir = require_within(
        (profile_root / slug).resolve(),
        profile_root,
        "matrix_model_path_outside_profile_root",
    )
    if model_dir.parent != profile_root or model_dir.name != slug:
        raise ValueError("matrix_profiled_model_path_mismatch")
    return model_dir


def _load_object(path: Path, error_code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(error_code) from error
    if not isinstance(value, dict):
        raise ValueError(error_code)
    return value


def load_verified_inputs(paths: MatrixPaths, settings: MatrixSettings) -> VerifiedInputs:
    """Verify all private inputs and both exact indexes before any API client exists."""

    if not paths.repo_root.is_dir() or not paths.private_root.is_dir():
        raise ValueError("matrix_data_root_missing")
    chunks_path = _require_private_path(paths.chunks_path, paths, "matrix_chunks_outside_private_root")
    metadata_path = _require_private_path(
        paths.chunk_metadata_path, paths, "matrix_chunk_metadata_outside_private_root"
    )
    manifest_path = _require_private_path(
        paths.manifest_path, paths, "matrix_manifest_outside_private_root"
    )
    indexes_root = _require_private_path(
        paths.indexes_root, paths, "matrix_indexes_outside_private_root"
    )
    _require_private_path(paths.caches_root, paths, "matrix_caches_outside_private_root")
    _require_private_path(paths.outputs_root, paths, "matrix_outputs_outside_private_root")
    _require_private_path(
        paths.tokenizer_cache_dir, paths, "matrix_tokenizer_cache_outside_private_root"
    )
    _require_private_path(
        paths.budget_ledger_path, paths, "matrix_budget_outside_private_root"
    )
    dev_path = require_within(
        paths.dev_path.resolve(),
        (paths.repo_root / "evaluation" / "private").resolve(),
        "matrix_dev_outside_evaluation_private_root",
    )
    dependency_path = require_within(
        paths.dependency_lock_path.resolve(), paths.repo_root, "matrix_dependency_file_outside_repo"
    )
    required_files = (chunks_path, metadata_path, manifest_path, dev_path, dependency_path)
    if any(not path.is_file() for path in required_files):
        raise ValueError("matrix_required_file_missing")
    if not paths.tokenizer_cache_dir.is_dir():
        raise ValueError("matrix_tokenizer_cache_missing")

    manifest_sha256 = sha256_file(manifest_path)
    metadata = _load_object(metadata_path, "matrix_chunk_metadata_invalid")
    expected_metadata_fields = {
        "schema_version",
        "source_manifest_sha256",
        "chunk_artifact_sha256",
        "config_sha256",
        "documents",
        "chunks",
    }
    if set(metadata) != expected_metadata_fields or metadata.get("schema_version") != "1.0":
        raise ValueError("matrix_chunk_metadata_invalid")
    if metadata.get("source_manifest_sha256") != manifest_sha256:
        raise ValueError("matrix_chunk_manifest_hash_mismatch")
    chunks_sha256 = sha256_file(chunks_path)
    if metadata.get("chunk_artifact_sha256") != chunks_sha256:
        raise ValueError("matrix_chunk_artifact_hash_mismatch")

    chunks = read_jsonl(chunks_path)
    if not chunks or metadata.get("chunks") != len(chunks):
        raise ValueError("matrix_chunk_count_mismatch")
    for chunk in chunks:
        validate_chunk(chunk)
    chunk_config_hashes = {chunk["config_sha256"] for chunk in chunks}
    if chunk_config_hashes != {metadata.get("config_sha256")}:
        raise ValueError("matrix_chunk_config_hash_mismatch")
    chunk_doc_ids = {chunk["doc_id"] for chunk in chunks}
    if metadata.get("documents") != len(chunk_doc_ids):
        raise ValueError("matrix_chunk_document_count_mismatch")

    manifest = read_jsonl(manifest_path)
    eligible_doc_ids = {
        row.get("doc_id")
        for row in manifest
        if row.get("status") == "ok" and row.get("index_eligible") is True
    }
    if chunk_doc_ids != eligible_doc_ids:
        raise ValueError("matrix_chunk_manifest_documents_mismatch")
    block_owners: dict[str, str] = {}
    for chunk in chunks:
        for block_id in chunk["source_block_ids"]:
            owner = block_owners.setdefault(block_id, chunk["doc_id"])
            if owner != chunk["doc_id"]:
                raise ValueError("matrix_block_owner_conflict")

    cases = read_jsonl(dev_path)
    if len(cases) != 40:
        raise ValueError("matrix_dev_case_count_mismatch")
    if Counter(case.get("task_type") for case in cases) != EXPECTED_DEV_COUNTS:
        raise ValueError("matrix_dev_task_distribution_mismatch")
    seen_case_ids: set[str] = set()
    review_statuses: Counter[str] = Counter()
    for index, case in enumerate(cases):
        if validate_case(case, f"dev[{index}]"):
            raise ValueError("matrix_dev_case_contract_failed")
        case_id = case["case_id"]
        if case_id in seen_case_ids:
            raise ValueError("matrix_duplicate_case_id")
        seen_case_ids.add(case_id)
        if case.get("split") != "dev" or case.get("source_manifest_sha256") != manifest_sha256:
            raise ValueError("matrix_dev_snapshot_mismatch")
        review = case.get("review")
        status = review.get("status") if isinstance(review, dict) else None
        review_statuses[str(status)] += 1
        scope = case["document_scope"]
        gold = case["gold"]
        referenced_docs = set(scope["doc_ids"]) | set(gold["required_doc_ids"])
        if not referenced_docs <= eligible_doc_ids:
            raise ValueError("matrix_dev_document_missing")
        for evidence in gold["evidence_refs"]:
            if block_owners.get(evidence["source_block_id"]) != evidence["doc_id"]:
                raise ValueError("matrix_dev_evidence_missing_or_mismatched")
    if settings.require_approved_dev and review_statuses != Counter({"approved": 40}):
        raise ValueError("matrix_dev_not_approved")

    indexes: dict[str, ExactDenseIndex] = {}
    index_metadata: dict[str, dict[str, Any]] = {}
    index_metadata_hashes: dict[str, str] = {}
    index_configs: dict[str, dict[str, Any]] = {}
    for model in settings.embedding_models:
        index_dir = _profiled_model_dir(indexes_root, settings, model)
        metadata_file = index_dir / "metadata.json"
        config_file = index_dir / "index-config.json"
        if not metadata_file.is_file() or not config_file.is_file():
            raise ValueError("matrix_index_missing")
        model_metadata = _load_object(metadata_file, "matrix_index_metadata_invalid")
        model_config = _load_object(config_file, "matrix_index_config_invalid")
        from midprojectrag.stacks.api import api_config_sha256, build_api_index_config

        model_config_sha256 = api_config_sha256(model_config)
        if model_metadata.get("embedding_model") != model:
            raise ValueError("matrix_index_embedding_model_mismatch")
        if model_metadata.get("dimensions") != settings.dimensions_by_model[model]:
            raise ValueError("matrix_index_dimensions_mismatch")
        if model_metadata.get("engine") != settings.expected_index_engine:
            raise ValueError("matrix_index_engine_mismatch")
        if (
            model_metadata.get("api_profile") != settings.api_profile
            or model_metadata.get("index_config_sha256") != model_config_sha256
            or model_config.get("api_profile") != settings.api_profile
            or model_config.get("embedding_model") != model
            or model_config.get("embedding_dimensions") != settings.dimensions_by_model[model]
            or model_config.get("index_engine") != settings.expected_index_engine
            or model_config.get("corpus_manifest_sha256") != manifest_sha256
            or model_config.get("chunk_config_sha256") != metadata["config_sha256"]
        ):
            raise ValueError("matrix_index_profile_config_mismatch")
        expected_model_config = build_api_index_config(
            api_profile=settings.api_profile,
            corpus_manifest_sha256=manifest_sha256,
            chunk_artifact_sha256=model_metadata.get("chunk_artifact_sha256"),
            chunk_config_sha256=metadata["config_sha256"],
            embedding_model=model,
            embedding_dimensions=settings.dimensions_by_model[model],
            index_engine=settings.expected_index_engine,
            batch_size=model_config.get("batch_size"),
        )
        if model_config != expected_model_config:
            raise ValueError("matrix_index_profile_config_mismatch")
        if model_metadata.get("corpus_manifest_sha256") != manifest_sha256:
            raise ValueError("matrix_index_manifest_hash_mismatch")
        if model_metadata.get("chunk_config_sha256") != metadata["config_sha256"]:
            raise ValueError("matrix_index_chunk_config_mismatch")
        index = ExactDenseIndex.load(
            index_dir,
            chunks,
            expected_embedding_model=model,
            expected_dimensions=settings.dimensions_by_model[model],
            expected_api_profile=settings.api_profile,
            expected_index_config_sha256=model_config_sha256,
        )
        if index.dimensions != settings.dimensions_by_model[model]:
            raise ValueError("matrix_loaded_index_dimensions_mismatch")
        indexes[model] = index
        index_metadata[model] = model_metadata
        index_metadata_hashes[model] = sha256_file(metadata_file)
        index_configs[model] = model_config

    return VerifiedInputs(
        chunks=chunks,
        cases=cases,
        corpus_manifest_sha256=manifest_sha256,
        eval_set_sha256=dataset_sha256(cases),
        chunk_artifact_sha256=chunks_sha256,
        chunk_config_sha256=metadata["config_sha256"],
        review_statuses=dict(sorted(review_statuses.items())),
        indexes=indexes,
        index_metadata=index_metadata,
        index_metadata_sha256=index_metadata_hashes,
        index_config=index_configs,
    )


def _default_pipeline_factory(runtime: ComboRuntime) -> PipelineLike:
    from midprojectrag.answering.pipeline import RagPipeline
    from midprojectrag.indexing.embeddings import EmbeddingCache
    from midprojectrag.stacks.api import (
        OpenAIEmbeddingProvider,
        OpenAIGenerator,
        TiktokenCounter,
    )

    embedding_provider = OpenAIEmbeddingProvider(
        model=runtime.embedding_model,
        dimensions=runtime.index.dimensions,
        api_profile=runtime.api_profile,
    )
    generator = OpenAIGenerator(
        model=runtime.generator_model,
        max_output_tokens=runtime.max_output_tokens,
        max_citations=runtime.max_citations,
        reasoning_effort=runtime.reasoning_effort,
        before_request=runtime.generation_start_limiter.wait_for_start,
    )
    return RagPipeline(
        index=runtime.index,
        embedding_provider=embedding_provider,
        embedding_counter=TiktokenCounter(
            runtime.embedding_model, cache_dir=runtime.tokenizer_cache_dir
        ),
        query_cache=EmbeddingCache(runtime.query_cache_dir),
        generator=generator,
        generation_counter=TiktokenCounter(
            runtime.generator_model, cache_dir=runtime.tokenizer_cache_dir
        ),
        budget=runtime.budget,
        corpus_manifest_sha256=runtime.corpus_manifest_sha256,
        stack_id="api",
        observer=runtime.observer,
        retrieval_top_k=runtime.retrieval_top_k,
        context_top_k=runtime.context_top_k,
    )


def _default_run_record_builder(**kwargs: Any) -> dict[str, Any]:
    from midprojectrag.stacks.api import build_api_run_record

    return build_api_run_record(**kwargs)


def _environment(paths: MatrixPaths) -> dict[str, Any]:
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        physical_pages = os.sysconf("SC_PHYS_PAGES")
        ram_gb = round(page_size * physical_pages / 1024**3, 3)
    except (AttributeError, OSError, ValueError):
        ram_gb = 1.0
    disk_gb = round(shutil.disk_usage(paths.repo_root).total / 1024**3, 3)
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform()[:256],
        "region": "local",
        "machine_type": "local-api-benchmark",
        "vcpu": max(1, os.cpu_count() or 1),
        "ram_gb": max(ram_gb, 0.001),
        "gpu_model": None,
        "disk_gb": max(disk_gb, 0.001),
        "dependency_lock_sha256": sha256_file(paths.dependency_lock_path),
    }


def _combo_config(
    verified: VerifiedInputs,
    settings: MatrixSettings,
    embedding_model: str,
    generator_model: str,
) -> dict[str, Any]:
    from midprojectrag.stacks.api import build_api_run_config

    return build_api_run_config(
        index_config_sha256=verified.index_metadata[embedding_model][
            "index_config_sha256"
        ],
        generator_model=generator_model,
        retrieval_top_k=settings.retrieval_top_k,
        context_top_k=settings.context_top_k,
        max_output_tokens=settings.max_output_tokens,
        max_citations=settings.max_citations,
        reasoning_effort=settings.reasoning_effort,
        case_interval_seconds=settings.case_interval_seconds,
    )


def _request(case: Mapping[str, Any], config_sha256: str, max_citations: int) -> dict[str, Any]:
    request_material = f"{case['case_id']}:{config_sha256}"
    request_id = f"req-{sha256_text(request_material)[:24]}"
    return {
        "schema_version": "1.0",
        "request_id": request_id,
        "question": case["question"],
        "history": copy.deepcopy(case["history"]),
        "document_scope": copy.deepcopy(case["document_scope"]),
        "options": {"max_citations": max_citations},
    }


def _run_context(
    case_id: str,
    config_sha256: str,
    verified: VerifiedInputs,
    settings: MatrixSettings,
    environment: Mapping[str, Any],
) -> dict[str, Any]:
    run_id = f"run_{sha256_text(f'{case_id}:{config_sha256}')[:24]}"
    return {
        "run_id": run_id,
        "case_id": case_id,
        "eval_set_sha256": verified.eval_set_sha256,
        "config_sha256": config_sha256,
        "git_commit": settings.git_commit,
        "environment": copy.deepcopy(dict(environment)),
    }


def _result_dict(result: Any) -> dict[str, Any]:
    required = ("response", "retrieval", "timing_ms", "usage", "cache_hit")
    if any(not hasattr(result, field) for field in required):
        raise ValueError("matrix_pipeline_result_invalid")
    response = copy.deepcopy(result.response)
    if validate_response(response):
        raise ValueError("matrix_pipeline_response_contract_failed")
    retrieval = copy.deepcopy(result.retrieval)
    timing = copy.deepcopy(result.timing_ms)
    usage = copy.deepcopy(result.usage)
    if not isinstance(retrieval, list) or not isinstance(timing, dict) or not isinstance(usage, dict):
        raise ValueError("matrix_pipeline_result_invalid")
    if not isinstance(result.cache_hit, bool):
        raise ValueError("matrix_pipeline_result_invalid")
    return {
        "response": response,
        "retrieval": retrieval,
        "timing_ms": timing,
        "usage": usage,
        "cache_hit": result.cache_hit,
    }


def _build_evaluator_record(
    result: Any,
    *,
    context: Mapping[str, Any],
    verified: VerifiedInputs,
    embedding_model: str,
    generator_model: str,
    builder: RunRecordBuilder,
    validator: RunRecordValidator,
) -> tuple[dict[str, Any] | None, str | None]:
    kwargs = {
        "result": result,
        "context": context,
        "corpus_manifest_sha256": verified.corpus_manifest_sha256,
        "generator_model": generator_model,
        "embedding_model": embedding_model,
        "seed": None,
        "temperature": None,
        "reasoning_effort": REASONING_EFFORT,
        "api_profile": verified.index_metadata[embedding_model]["api_profile"],
        "embedding_dimensions": verified.indexes[embedding_model].dimensions,
        "index_config_sha256": verified.index_metadata[embedding_model][
            "index_config_sha256"
        ],
    }
    record = builder(**kwargs)
    if validator(record):
        raise ValueError("matrix_run_record_contract_failed")
    return record, None


def _envelope(payload: Mapping[str, Any]) -> dict[str, Any]:
    copied = copy.deepcopy(dict(payload))
    return {"payload": copied, "payload_sha256": sha256_text(canonical_json(copied))}


def _load_checkpoint(
    path: Path,
    *,
    case_id: str,
    run_id: str,
    config_sha256: str,
    embedding_model: str,
    generator_model: str,
    eval_set_sha256: str,
    corpus_manifest_sha256: str,
) -> dict[str, Any] | None:
    if not path.exists():
        return None
    envelope = _load_object(path, "matrix_checkpoint_invalid")
    if set(envelope) != {"payload", "payload_sha256"} or not isinstance(envelope["payload"], dict):
        raise ValueError("matrix_checkpoint_invalid")
    payload = envelope["payload"]
    if sha256_text(canonical_json(payload)) != envelope.get("payload_sha256"):
        raise ValueError("matrix_checkpoint_hash_mismatch")
    expected = {
        "case_id": case_id,
        "run_id": run_id,
        "config_sha256": config_sha256,
        "embedding_model": embedding_model,
        "generator_model": generator_model,
        "eval_set_sha256": eval_set_sha256,
        "corpus_manifest_sha256": corpus_manifest_sha256,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise ValueError("matrix_checkpoint_context_mismatch")
    state = payload.get("state")
    if state == "started":
        if set(payload) != {
            "schema_version",
            "artifact_type",
            "state",
            "case_id",
            "run_id",
            "embedding_model",
            "generator_model",
            "config_sha256",
            "eval_set_sha256",
            "corpus_manifest_sha256",
        }:
            raise ValueError("matrix_checkpoint_invalid")
        raise ValueError("matrix_incomplete_checkpoint_requires_budget_audit")
    completed_fields = {
        "schema_version",
        "artifact_type",
        "state",
        "evaluation_status",
        "case_id",
        "run_id",
        "embedding_model",
        "generator_model",
        "config_sha256",
        "eval_set_sha256",
        "corpus_manifest_sha256",
        "result",
        "evaluator_compatible",
        "evaluator_contract_error",
        "run_record",
    }
    if (
        state != "completed"
        or set(payload) != completed_fields
        or not isinstance(payload.get("result"), dict)
        or not isinstance(payload.get("evaluator_compatible"), bool)
        or (payload["evaluator_compatible"] != (payload.get("run_record") is not None))
        or (
            payload.get("evaluator_contract_error") is not None
            and not isinstance(payload.get("evaluator_contract_error"), str)
        )
    ):
        raise ValueError("matrix_checkpoint_invalid")
    return payload


def _write_started_checkpoint(
    path: Path,
    *,
    case_id: str,
    run_id: str,
    config_sha256: str,
    embedding_model: str,
    generator_model: str,
    verified: VerifiedInputs,
) -> None:
    write_json(
        path,
        _envelope(
            {
                "schema_version": "1.0",
                "artifact_type": "api_matrix_case_checkpoint",
                "state": "started",
                "case_id": case_id,
                "run_id": run_id,
                "embedding_model": embedding_model,
                "generator_model": generator_model,
                "config_sha256": config_sha256,
                "eval_set_sha256": verified.eval_set_sha256,
                "corpus_manifest_sha256": verified.corpus_manifest_sha256,
            }
        ),
    )


def _completed_payload(
    *,
    case_id: str,
    context: Mapping[str, Any],
    config_sha256: str,
    embedding_model: str,
    generator_model: str,
    verified: VerifiedInputs,
    result: Mapping[str, Any],
    run_record: Mapping[str, Any] | None,
    contract_error: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "artifact_type": "api_matrix_case_checkpoint",
        "state": "completed",
        "evaluation_status": verified.evaluation_status,
        "case_id": case_id,
        "run_id": context["run_id"],
        "embedding_model": embedding_model,
        "generator_model": generator_model,
        "config_sha256": config_sha256,
        "eval_set_sha256": verified.eval_set_sha256,
        "corpus_manifest_sha256": verified.corpus_manifest_sha256,
        "result": copy.deepcopy(dict(result)),
        "evaluator_compatible": run_record is not None,
        "evaluator_contract_error": contract_error,
        "run_record": copy.deepcopy(dict(run_record)) if run_record is not None else None,
    }


def _result_namespace(payload: Mapping[str, Any]) -> SimpleNamespace:
    result = payload["result"]
    return SimpleNamespace(
        response=result["response"],
        retrieval=result["retrieval"],
        timing_ms=result["timing_ms"],
        usage=result["usage"],
        cache_hit=result["cache_hit"],
    )


def _round_mean(values: Sequence[float]) -> float | None:
    return round(fmean(values), 6) if values else None


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return round(float(ordered[rank - 1]), 6)


def _dcg(relevances: Sequence[int]) -> float:
    return sum(value / math.log2(index + 2) for index, value in enumerate(relevances))


def _provisional_metrics(
    cases: Sequence[Mapping[str, Any]],
    payloads: Sequence[Mapping[str, Any]],
    *,
    context_top_k: int,
) -> dict[str, Any]:
    case_map = {case["case_id"]: case for case in cases}
    doc_recalls: dict[int, list[float]] = {k: [] for k in (1, 3, 5, 10)}
    block_recalls: dict[int, list[float]] = {k: [] for k in (1, 3, 5, 10)}
    all_required: dict[int, list[float]] = {k: [] for k in (1, 3, 5, 10)}
    reciprocal_ranks: list[float] = []
    ndcg: list[float] = []
    total_ms: list[float] = []
    retrieval_ms: list[float] = []
    generation_ms: list[float] = []
    costs: list[float] = []
    response_statuses: Counter[str] = Counter()
    cache_hits = 0
    contract_errors = 0
    answerable = 0
    answerable_abstained = 0
    unknown = 0
    unknown_abstained = 0
    answered_citation_counts: list[float] = []
    cited_required_doc_coverage: list[float] = []
    cited_gold_block_coverage: list[float] = []
    citation_context_membership = 0
    citation_total = 0
    for payload in payloads:
        case = case_map[payload["case_id"]]
        result = payload["result"]
        response = result["response"]
        status = response.get("status")
        response_statuses[str(status)] += 1
        contract_errors += int(bool(validate_response(response)))
        cache_hits += int(result.get("cache_hit") is True)
        decision = case["gold"]["decision"]
        if decision == "abstain":
            unknown += 1
            unknown_abstained += int(status == "abstained")
        else:
            answerable += 1
            answerable_abstained += int(status == "abstained")
        retrieval = sorted(
            (hit for hit in result["retrieval"] if isinstance(hit, dict)),
            key=lambda hit: hit.get("rank", 10**9),
        )
        ranked_docs = [hit.get("doc_id") for hit in retrieval if isinstance(hit.get("doc_id"), str)]
        relevant_docs = set(case["gold"]["required_doc_ids"])
        relevant_blocks = {
            reference["source_block_id"] for reference in case["gold"]["evidence_refs"]
        }
        citations = response.get("citations", [])
        cited_doc_ids = {
            citation.get("doc_id")
            for citation in citations
            if isinstance(citation, dict) and isinstance(citation.get("doc_id"), str)
        }
        cited_block_ids = {
            block_id
            for citation in citations
            if isinstance(citation, dict)
            for block_id in citation.get("source_block_ids", [])
            if isinstance(block_id, str)
        }
        if status == "answered":
            answered_citation_counts.append(float(len(citations)))
        if decision == "answer":
            cited_required_doc_coverage.append(
                len(cited_doc_ids & relevant_docs) / len(relevant_docs)
                if relevant_docs
                else 0.0
            )
            cited_gold_block_coverage.append(
                len(cited_block_ids & relevant_blocks) / len(relevant_blocks)
                if relevant_blocks
                else 0.0
            )
        context_chunk_ids = {
            hit.get("chunk_id")
            for hit in retrieval[:context_top_k]
            if isinstance(hit.get("chunk_id"), str)
        }
        for citation in citations:
            if isinstance(citation, dict):
                citation_total += 1
                citation_context_membership += int(
                    citation.get("chunk_id") in context_chunk_ids
                )
        if relevant_docs:
            for k in (1, 3, 5, 10):
                top = retrieval[:k]
                top_docs = {hit.get("doc_id") for hit in top}
                doc_recalls[k].append(len(top_docs & relevant_docs) / len(relevant_docs))
                retrieved_blocks = {
                    block_id
                    for hit in top
                    for block_id in hit.get("source_block_ids", [])
                    if isinstance(block_id, str)
                }
                block_recalls[k].append(
                    len(retrieved_blocks & relevant_blocks) / len(relevant_blocks)
                    if relevant_blocks
                    else 0.0
                )
                if case["task_type"] == "multi_doc_compare":
                    all_required[k].append(float(relevant_docs <= top_docs))
            first = next(
                (rank for rank, doc_id in enumerate(ranked_docs[:10], start=1) if doc_id in relevant_docs),
                None,
            )
            reciprocal_ranks.append(0.0 if first is None else 1.0 / first)
            seen: set[str] = set()
            relevance: list[int] = []
            for doc_id in ranked_docs[:10]:
                is_new = doc_id in relevant_docs and doc_id not in seen
                relevance.append(int(is_new))
                if is_new:
                    seen.add(doc_id)
            ideal_dcg = _dcg([1] * min(len(relevant_docs), 10))
            ndcg.append(0.0 if ideal_dcg == 0 else _dcg(relevance) / ideal_dcg)
        timing = result.get("timing_ms", {})
        for field, destination in (
            ("total", total_ms),
            ("retrieval", retrieval_ms),
            ("generation", generation_ms),
        ):
            value = timing.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                destination.append(float(value))
        cost = result.get("usage", {}).get("cost_usd")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool) and math.isfinite(cost):
            costs.append(float(cost))
    return {
        "retrieval": {
            **{f"document_recall_at_{k}": _round_mean(values) for k, values in doc_recalls.items()},
            **{f"source_block_recall_at_{k}": _round_mean(values) for k, values in block_recalls.items()},
            **{
                f"all_required_docs_recalled_at_{k}": _round_mean(values)
                for k, values in all_required.items()
            },
            "mrr_at_10": _round_mean(reciprocal_ranks),
            "ndcg_at_10": _round_mean(ndcg),
        },
        "response_behavior_unjudged": {
            "status_counts": dict(sorted(response_statuses.items())),
            "unknown_abstention_rate": None if not unknown else round(unknown_abstained / unknown, 6),
            "answerable_false_abstain_rate": (
                None if not answerable else round(answerable_abstained / answerable, 6)
            ),
            "response_contract_error_rate": (
                None if not payloads else round(contract_errors / len(payloads), 6)
            ),
        },
        "structural_citations_unjudged": {
            "answered_mean_citation_count": _round_mean(answered_citation_counts),
            "cited_required_doc_id_coverage": _round_mean(
                cited_required_doc_coverage
            ),
            "cited_gold_evidence_block_id_coverage": _round_mean(
                cited_gold_block_coverage
            ),
            "citation_context_membership_rate": (
                None
                if not citation_total
                else round(citation_context_membership / citation_total, 6)
            ),
        },
        "operations": {
            "latency_total_p50_ms": _percentile(total_ms, 0.5),
            "latency_total_p95_ms": _percentile(total_ms, 0.95),
            "latency_retrieval_p50_ms": _percentile(retrieval_ms, 0.5),
            "latency_generation_p50_ms": _percentile(generation_ms, 0.5),
            "latency_generation_p95_ms": _percentile(generation_ms, 0.95),
            "total_query_cost_usd": round(sum(costs), 9),
            "mean_query_cost_usd": _round_mean(costs),
            "query_cache_hit_rate": round(cache_hits / len(payloads), 6) if payloads else None,
        },
    }


def _write_combo_artifacts(
    combo_dir: Path,
    verified: VerifiedInputs,
    payloads: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
    config_sha256: str,
    embedding_model: str,
    generator_model: str,
) -> dict[str, Any]:
    provisional_path = combo_dir / "results.provisional.jsonl"
    evaluator_path = combo_dir / "runs.evaluator.jsonl"
    config_path = combo_dir / "config.json"
    summary_path = combo_dir / "summary.provisional.json"
    write_json(config_path, config)
    write_jsonl(provisional_path, [dict(payload) for payload in payloads])
    evaluator_records = [payload["run_record"] for payload in payloads if payload["run_record"] is not None]
    write_jsonl(evaluator_path, evaluator_records)
    error_count = sum(
        payload["result"]["response"].get("status") == "error"
        for payload in payloads
    )
    warnings = [
        "dev cases are not a formal score set until named human review is complete"
        if verified.evaluation_status == "provisional_unreviewed_dev"
        else "answer quality still requires human run judgments",
        "response behavior is unjudged; retrieval and operations metrics are provisional",
        "evaluator_compatible means schema-compatible only; draft or unjudged records are not score-ready",
        "structural citation ID metrics are automatic checks, not human citation-validity judgments",
        "query embedding cache is shared within each embedder: nano runs cold before mini runs warm, so do not compare retrieval latency, total latency, or total query cost between generators; compare generation latency separately",
        "OpenAI model aliases are moving identifiers and are not snapshot-pinned",
    ]
    if embedding_model == "text-embedding-3-large":
        warnings.append("text-embedding-3-large is a personal-account experiment outside the course allowlist")
    summary = {
        "schema_version": "1.0",
        "artifact_type": "api_matrix_combo_summary",
        "evaluation_status": verified.evaluation_status,
        "embedding_model": embedding_model,
        "generator_model": generator_model,
        "reasoning_effort": config["reasoning_effort"],
        "case_interval_seconds": config["case_interval_seconds"],
        "config_sha256": config_sha256,
        "eval_set_sha256": verified.eval_set_sha256,
        "corpus_manifest_sha256": verified.corpus_manifest_sha256,
        "counts": {
            "cases": len(verified.cases),
            "completed": len(payloads),
            "evaluator_compatible": len(evaluator_records),
            "errors": error_count,
            "human_judged": 0,
        },
        "response_error_rate": (
            None if not payloads else round(error_count / len(payloads), 6)
        ),
        "metrics": _provisional_metrics(
            verified.cases,
            payloads,
            context_top_k=int(config["context_top_k"]),
        ),
        "artifact_sha256": {
            "config": sha256_file(config_path),
            "provisional_results": sha256_file(provisional_path),
            "evaluator_runs": sha256_file(evaluator_path),
        },
        "warnings": warnings,
    }
    write_json(summary_path, summary)
    return summary


@contextmanager
def _matrix_lock(outputs_root: Path):
    outputs_root.mkdir(parents=True, exist_ok=True)
    lock_path = outputs_root / ".api-matrix.lock"
    with lock_path.open("a+b") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("matrix_run_already_active") from error
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def preflight_matrix(paths: MatrixPaths, settings: MatrixSettings) -> dict[str, Any]:
    verified = load_verified_inputs(paths, settings)
    return {
        "passed": True,
        "network_calls": 0,
        "evaluation_status": verified.evaluation_status,
        "review_statuses": verified.review_statuses,
        "cases": len(verified.cases),
        "reasoning_effort": settings.reasoning_effort,
        "case_interval_seconds": settings.case_interval_seconds,
        "eval_set_sha256": verified.eval_set_sha256,
        "corpus_manifest_sha256": verified.corpus_manifest_sha256,
        "indexes": {
            model: {
                "engine": verified.index_metadata[model]["engine"],
                "dimensions": verified.indexes[model].dimensions,
                "metadata_sha256": verified.index_metadata_sha256[model],
            }
            for model in settings.embedding_models
        },
    }


def _run_matrix_impl(
    paths: MatrixPaths,
    settings: MatrixSettings,
    *,
    observer: Observer | None = None,
    pipeline_factory: PipelineFactory | None = None,
    run_record_builder: RunRecordBuilder | None = None,
    run_record_validator: RunRecordValidator = validate_run_record,
    environment: Mapping[str, Any] | None = None,
    monotonic: Callable[[], float],
    sleeper: Callable[[float], None],
) -> dict[str, Any]:
    """Run or resume the 2x2 matrix without silently repeating interrupted calls."""

    verified = load_verified_inputs(paths, settings)
    selected_observer = observer or NoopObserver()
    selected_factory = pipeline_factory or _default_pipeline_factory
    selected_builder = run_record_builder or _default_run_record_builder
    run_environment = copy.deepcopy(dict(environment or _environment(paths)))
    budget = BudgetLedger(paths.budget_ledger_path, limit_usd=settings.max_api_budget_usd)
    budget_at_start = budget.snapshot()
    if budget_at_start.breached:
        raise ValueError("matrix_budget_already_breached")
    if budget_at_start.reserved_usd != 0:
        raise ValueError("matrix_budget_reservation_requires_audit")
    generation_start_limiter = _GenerationStartLimiter(
        settings.case_interval_seconds,
        monotonic=monotonic,
        sleeper=sleeper,
    )
    combo_summaries: list[dict[str, Any]] = []
    outputs_root = _require_private_path(
        paths.outputs_root, paths, "matrix_outputs_outside_private_root"
    )
    try:
        with _matrix_lock(outputs_root):
            for embedding_model in settings.embedding_models:
                query_cache_dir = _profiled_model_dir(
                    paths.caches_root, settings, embedding_model
                )
                for generator_model in settings.generator_models:
                    config = _combo_config(
                        verified, settings, embedding_model, generator_model
                    )
                    config_sha256 = sha256_text(canonical_json(config))
                    model_output_dir = _profiled_model_dir(
                        outputs_root, settings, embedding_model
                    )
                    combo_dir = require_within(
                        (model_output_dir / generator_model / settings.run_label).resolve(),
                        model_output_dir,
                        "matrix_combo_output_outside_model_root",
                    )
                    checkpoint_dir = combo_dir / "checkpoints"
                    runtime = ComboRuntime(
                        embedding_model=embedding_model,
                        generator_model=generator_model,
                        index=verified.indexes[embedding_model],
                        index_metadata=verified.index_metadata[embedding_model],
                        query_cache_dir=query_cache_dir,
                        tokenizer_cache_dir=paths.tokenizer_cache_dir,
                        budget=budget,
                        observer=selected_observer,
                        corpus_manifest_sha256=verified.corpus_manifest_sha256,
                        retrieval_top_k=settings.retrieval_top_k,
                        context_top_k=settings.context_top_k,
                        max_citations=settings.max_citations,
                        max_output_tokens=settings.max_output_tokens,
                        config=config,
                        config_sha256=config_sha256,
                        api_profile=settings.api_profile,
                        index_config_sha256=verified.index_metadata[embedding_model][
                            "index_config_sha256"
                        ],
                        reasoning_effort=settings.reasoning_effort,
                        generation_start_limiter=generation_start_limiter,
                    )
                    pipeline = selected_factory(runtime)
                    payloads: list[dict[str, Any]] = []
                    try:
                        for case in verified.cases:
                            context = _run_context(
                                case["case_id"],
                                config_sha256,
                                verified,
                                settings,
                                run_environment,
                            )
                            checkpoint_path = checkpoint_dir / f"{case['case_id']}.json"
                            payload = _load_checkpoint(
                                checkpoint_path,
                                case_id=case["case_id"],
                                run_id=context["run_id"],
                                config_sha256=config_sha256,
                                embedding_model=embedding_model,
                                generator_model=generator_model,
                                eval_set_sha256=verified.eval_set_sha256,
                                corpus_manifest_sha256=verified.corpus_manifest_sha256,
                            )
                            if payload is None:
                                _write_started_checkpoint(
                                    checkpoint_path,
                                    case_id=case["case_id"],
                                    run_id=context["run_id"],
                                    config_sha256=config_sha256,
                                    embedding_model=embedding_model,
                                    generator_model=generator_model,
                                    verified=verified,
                                )
                                pipeline_result = pipeline.query(
                                    _request(case, config_sha256, settings.max_citations),
                                    trace_context={
                                        "run_id": context["run_id"],
                                        "case_id": context["case_id"],
                                        "eval_set_sha256": context["eval_set_sha256"],
                                        "config_sha256": context["config_sha256"],
                                        "api_profile": settings.api_profile,
                                        "index_config_sha256": runtime.index_config_sha256,
                                    },
                                )
                                result = _result_dict(pipeline_result)
                                run_record, contract_error = _build_evaluator_record(
                                    pipeline_result,
                                    context=context,
                                    verified=verified,
                                    embedding_model=embedding_model,
                                    generator_model=generator_model,
                                    builder=selected_builder,
                                    validator=run_record_validator,
                                )
                                payload = _completed_payload(
                                    case_id=case["case_id"],
                                    context=context,
                                    config_sha256=config_sha256,
                                    embedding_model=embedding_model,
                                    generator_model=generator_model,
                                    verified=verified,
                                    result=result,
                                    run_record=run_record,
                                    contract_error=contract_error,
                                )
                                write_json(checkpoint_path, _envelope(payload))
                                if result["response"].get("status") == "error":
                                    raise ValueError("matrix_new_case_response_error")
                                case_budget = budget.snapshot()
                                if case_budget.breached:
                                    raise ValueError("matrix_budget_breached")
                                if case_budget.reserved_usd != 0:
                                    raise ValueError(
                                        "matrix_budget_reservation_requires_audit"
                                    )
                            else:
                                result_namespace = _result_namespace(payload)
                                checkpoint_result = _result_dict(result_namespace)
                                if checkpoint_result != payload["result"]:
                                    raise ValueError("matrix_checkpoint_result_invalid")
                                if checkpoint_result["response"].get("status") == "error":
                                    raise ValueError("matrix_checkpoint_contains_error_response")
                                if payload.get("run_record") is not None:
                                    if run_record_validator(payload["run_record"]):
                                        raise ValueError("matrix_checkpoint_run_record_invalid")
                                else:
                                    run_record, contract_error = _build_evaluator_record(
                                        result_namespace,
                                        context=context,
                                        verified=verified,
                                        embedding_model=embedding_model,
                                        generator_model=generator_model,
                                        builder=selected_builder,
                                        validator=run_record_validator,
                                    )
                                    if run_record is not None:
                                        payload = {
                                            **payload,
                                            "evaluator_compatible": True,
                                            "evaluator_contract_error": None,
                                            "run_record": run_record,
                                        }
                                        write_json(checkpoint_path, _envelope(payload))
                                    elif contract_error != payload.get("evaluator_contract_error"):
                                        raise ValueError("matrix_checkpoint_contract_state_mismatch")
                            payloads.append(payload)
                    finally:
                        pipeline.flush_observability()
                    combo_summaries.append(
                        _write_combo_artifacts(
                            combo_dir,
                            verified,
                            payloads,
                            config,
                            config_sha256,
                            embedding_model,
                            generator_model,
                        )
                    )
            snapshot = budget.snapshot()
            error_count = sum(
                summary["counts"]["errors"] for summary in combo_summaries
            )
            completed_count = sum(
                summary["counts"]["completed"] for summary in combo_summaries
            )
            budget_clean = not snapshot.breached and snapshot.reserved_usd == 0
            matrix_committed_delta = (
                snapshot.committed_usd - budget_at_start.committed_usd
            )
            matrix_summary = {
                "schema_version": "1.0",
                "artifact_type": "api_matrix_2x2_summary",
                "evaluation_status": verified.evaluation_status,
                "matrix_complete": (
                    len(combo_summaries) == 4
                    and all(
                        summary["counts"]["completed"] == 40
                        for summary in combo_summaries
                    )
                    and error_count == 0
                    and budget_clean
                ),
                "reasoning_effort": settings.reasoning_effort,
                "case_interval_seconds": settings.case_interval_seconds,
                "error_count": error_count,
                "response_error_rate": (
                    None
                    if not completed_count
                    else round(error_count / completed_count, 6)
                ),
                "eval_set_sha256": verified.eval_set_sha256,
                "corpus_manifest_sha256": verified.corpus_manifest_sha256,
                "review_statuses": verified.review_statuses,
                "budget": {
                    "limit_usd": str(snapshot.limit_usd),
                    "committed_usd_at_start": str(
                        budget_at_start.committed_usd
                    ),
                    "committed_usd_at_end": str(snapshot.committed_usd),
                    "matrix_committed_delta_usd": str(matrix_committed_delta),
                    "committed_usd": str(snapshot.committed_usd),
                    "reserved_usd": str(snapshot.reserved_usd),
                    "available_usd": str(snapshot.available_usd),
                    "breached": snapshot.breached,
                    "clean": budget_clean,
                },
                "combos": combo_summaries,
                "comparison_guardrails": {
                    "query_cache_prewarmed": False,
                    "query_cache_shared_within_embedding": True,
                    "cold_generator": settings.generator_models[0],
                    "warm_generator": settings.generator_models[1],
                    "generator_comparison_metric": "metrics.operations.latency_generation_p50_ms",
                    "retrieval_latency_total_latency_and_total_cost_comparable_between_generators": False,
                },
                "formal_answer_quality_scored": False,
                "warnings": [
                    "No correctness, faithfulness, or citation-validity claim is made before human judgment.",
                    "A started-only checkpoint blocks automatic replay until the shared budget ledger is audited.",
                    "No query prewarm calls are added: nano is cache-cold and mini is cache-warm, so only generation latency is a fair generator-speed comparison.",
                ],
            }
            matrix_path = outputs_root / f"matrix-2x2-{settings.run_label}.provisional.json"
            write_json(matrix_path, matrix_summary)
            return matrix_summary
    finally:
        selected_observer.flush()


def _shutdown_observer(observer: Observer) -> None:
    shutdown = getattr(observer, "shutdown", None)
    try:
        if callable(shutdown):
            shutdown()
        else:
            observer.flush()
    except Exception:
        # Observability teardown must never replace the benchmark outcome.
        return


def run_matrix(
    paths: MatrixPaths,
    settings: MatrixSettings,
    *,
    observer: Observer | None = None,
    pipeline_factory: PipelineFactory | None = None,
    run_record_builder: RunRecordBuilder | None = None,
    run_record_validator: RunRecordValidator = validate_run_record,
    environment: Mapping[str, Any] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Run the matrix and always terminate the observer on normal or error exit."""

    selected_observer = observer or NoopObserver()
    try:
        return _run_matrix_impl(
            paths,
            settings,
            observer=selected_observer,
            pipeline_factory=pipeline_factory,
            run_record_builder=run_record_builder,
            run_record_validator=run_record_validator,
            environment=environment,
            monotonic=monotonic,
            sleeper=sleeper,
        )
    finally:
        _shutdown_observer(selected_observer)


def _error_code(error: BaseException, fallback: str) -> str:
    value = str(error)
    return value if ERROR_CODE_RE.fullmatch(value) else fallback


def _nonnegative_finite_float(value: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError("must be a non-negative finite number") from error
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative finite number")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m midprojectrag.api_matrix")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--run-label", default="dev40-provisional")
    parser.add_argument("--git-commit", default="uncommitted")
    parser.add_argument(
        "--case-interval-seconds",
        type=_nonnegative_finite_float,
        default=DEFAULT_CASE_INTERVAL_SECONDS,
    )
    parser.add_argument("--observability", choices=("disabled", "memory", "langfuse"), default="disabled")
    parser.add_argument("--approve-langfuse-metadata-egress", action="store_true")
    parser.add_argument("--approve-private-corpus-egress", action="store_true")
    parser.add_argument("--require-approved-dev", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = MatrixSettings(
            observability=args.observability,
            approve_langfuse_metadata_egress=args.approve_langfuse_metadata_egress,
            require_approved_dev=args.require_approved_dev,
            run_label=args.run_label,
            git_commit=args.git_commit,
            case_interval_seconds=args.case_interval_seconds,
        )
        paths = MatrixPaths.from_repo_root(args.repo_root)
        if args.preflight_only:
            print(json.dumps(preflight_matrix(paths, settings), sort_keys=True))
            return 0
        if not args.approve_private_corpus_egress:
            raise ValueError("private_corpus_egress_not_approved")
        try:
            from dotenv import load_dotenv
        except ImportError as error:
            raise RuntimeError("dotenv_dependency_missing") from error
        load_dotenv(paths.repo_root / ".env", override=False)
        standard_key = os.environ.get("OPENAI_API_KEY", "")
        private_key = os.environ.get("OPENAI_API_KEY_PRIVATE", "")
        if not standard_key.strip() and private_key.strip():
            os.environ["OPENAI_API_KEY"] = private_key
        if not os.environ.get("OPENAI_API_KEY"):
            raise ValueError("openai_api_key_missing")
        from midprojectrag.observability import create_observer

        summary = run_matrix(paths, settings, observer=create_observer(settings.observability))
        safe = {
            "passed": summary["matrix_complete"],
            "evaluation_status": summary["evaluation_status"],
            "eval_set_sha256": summary["eval_set_sha256"],
            "combos_completed": len(summary["combos"]),
            "error_count": summary["error_count"],
            "response_error_rate": summary["response_error_rate"],
            "case_interval_seconds": summary["case_interval_seconds"],
            "budget": summary["budget"],
        }
        print(json.dumps(safe, sort_keys=True))
        return 0 if safe["passed"] else 8
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RuntimeError) as error:
        print(json.dumps({"passed": False, "error_code": _error_code(error, "api_matrix_failed")}, sort_keys=True))
        return 8
    except Exception:
        print(json.dumps({"passed": False, "error_code": "api_matrix_failed"}, sort_keys=True))
        return 8


if __name__ == "__main__":
    sys.exit(main())
