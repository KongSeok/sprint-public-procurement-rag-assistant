"""Frozen, resumable OpenAI baseline for the 40 conversational RAG cases.

Preflight is read-only with respect to private runtime state and performs no
provider calls.  Live execution is available only behind an explicit egress
approval flag.  Every completed case atomically stores both its evaluator run
record and the exact private chat/provider audit transcript used to produce it.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import inspect
import json
import os
import platform
import re
import shutil
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from midprojectrag.answering.generation import SYSTEM_INSTRUCTIONS
from midprojectrag.answering.pipeline import (
    PipelineResult,
    RagPipeline,
    _build_prompt,
    _retrieval_query,
    _select_context_hits,
)
from midprojectrag.api_matrix import _provisional_metrics
from midprojectrag.evaluation import (
    TASK_TYPES,
    dataset_sha256,
    validate_case,
)
from midprojectrag.ingest.common import (
    canonical_json,
    read_jsonl,
    sha256_file,
    sha256_text,
    write_json,
)
from midprojectrag.indexing.budget import BudgetLedger
from midprojectrag.indexing.embeddings import EmbeddingCache, embedding_cache_namespace
from midprojectrag.indexing.exact_index import ExactDenseIndex, IndexSearchHit
from midprojectrag.observability import NoopObserver
from midprojectrag.stacks.api import (
    OpenAIEmbeddingProvider,
    OpenAIGenerator,
    TiktokenCounter,
    api_config_sha256,
    build_api_run_record,
)
from midprojectrag.stacks.api.generation import build_openai_answer_plan_schema


SCHEMA_VERSION = "1.0"
BASELINE_ID = "core40-provisional-v1"
INTERRUPTED_ERROR_RECOVERY_MODE = "explicit-interrupted-error-v1"
RUNTIME_CONTRACT_AMENDMENT_ID = "core40-mixed-runtime-recovery-v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CONFIG_FIELDS = {
    "schema_version",
    "baseline_id",
    "evaluation_tier",
    "expected_counts",
    "artifacts",
    "runtime",
    "execution_contract",
    "outputs",
}
ARTIFACT_FIELDS = {
    "cases",
    "cases_file_sha256",
    "cases_dataset_sha256",
    "cases_jsonl_canonical_sha256",
    "manifest",
    "manifest_sha256",
    "chunks",
    "chunks_sha256",
    "index_dir",
    "index_metadata_sha256",
    "index_config_file_sha256",
    "tiktoken_cache_dir",
}
RUNTIME_FIELDS = {
    "api_profile",
    "embedding_model",
    "embedding_dimensions",
    "generator_model",
    "openai_max_retries",
    "retrieval_top_k",
    "context_top_k",
    "max_citations",
    "max_output_tokens",
    "reasoning_effort",
    "case_interval_seconds",
    "budget_limit_usd",
    "git_commit",
}
OUTPUT_FIELDS = {
    "run_records",
    "chat_transcripts",
    "private_summary",
    "preflight_receipt",
    "receipt",
}
FROZEN_RUNTIME = {
    "api_profile": "personal_experimental",
    "embedding_model": "text-embedding-3-small",
    "embedding_dimensions": 1536,
    "generator_model": "gpt-5-mini",
    "openai_max_retries": 0,
    "retrieval_top_k": 10,
    "context_top_k": 5,
    "max_citations": 3,
    "max_output_tokens": 2000,
    "reasoning_effort": "minimal",
    "case_interval_seconds": 0.5,
    "budget_limit_usd": 2.0,
    "git_commit": "uncommitted",
}
EXECUTION_CONTRACT = {
    "provider_execution": "explicit_approval_required",
    "external_destination": "OpenAI API",
    "external_payload_classes": [
        "golden_set_questions",
        "conversation_history",
        "retrieved_rfp_excerpts",
    ],
    "explicit_egress_approval_required": True,
    "provider_attempt_policy": {
        "openai_sdk_max_retries": 0,
        "maximum_attempts_per_case": 1,
        "maximum_suite_calls": 80,
    },
    "resume_policy": {
        "unit": "case",
        "case_identity_field": "case_id",
        "checkpoint_identity_fields": [
            "cases_dataset_sha256",
            "config_sha256",
            "manifest_sha256",
            "index_metadata_sha256",
        ],
        "checkpoint": "atomic_private_json_after_each_case",
        "completed_cases_are_reused": True,
        "started_only_case_requires_budget_audit": True,
        "reject_mismatched_hashes": True,
    },
    "private_output_policy": {
        "directory_mode": "0700",
        "file_mode": "0600",
        "run_records": "evaluation/private/",
        "chat_transcripts": "evaluation/private/",
        "tracked_receipts_must_exclude": [
            "questions",
            "answers",
            "conversation_history",
            "source_text",
            "provider_request",
            "provider_response",
        ],
    },
    "transcript_contract": {
        "capture_time": "prospective_runtime",
        "request": "exact",
        "retrieval_query": "exact",
        "selected_context_with_source_text": "exact",
        "generation_provider_arguments": "exact",
        "generation_provider_response": "full_model_dump_when_available",
        "assistant_structured_plan": "exact",
        "assistant_final_response": "exact",
        "embedding_vectors": "omitted_with_sha256",
        "usage_timing_errors": "exact_available_runtime_values",
    },
}


@dataclass(frozen=True)
class VerifiedCore40:
    repo_root: Path
    config_path: Path
    config: dict[str, Any]
    config_sha256: str
    cases: list[dict[str, Any]]
    chunks: list[dict[str, Any]]
    chunk_by_id: dict[str, dict[str, Any]]
    known_doc_ids: set[str]
    index_metadata: dict[str, Any]
    index_config: dict[str, Any]
    index: ExactDenseIndex
    runtime_contract_sha256s: dict[str, str]

    @property
    def eval_set_sha256(self) -> str:
        return dataset_sha256(self.cases)


class AuditRecorder(Protocol):
    def reset(self) -> None: ...

    def snapshot(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class RuntimeBundle:
    pipeline: Any
    audit: AuditRecorder
    index_config_sha256: str


RuntimeFactory = Callable[[VerifiedCore40, Mapping[str, Path]], RuntimeBundle]


def _repo_root(config_path: Path) -> Path:
    for candidate in (config_path.resolve().parent, *config_path.resolve().parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise ValueError("repository_root_not_found")


def _relative_path(
    repo_root: Path,
    value: Any,
    *,
    prefix: str | None = None,
) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError("core40_path_must_be_relative")
    candidate = (repo_root / value).resolve()
    try:
        relative = candidate.relative_to(repo_root.resolve()).as_posix()
    except ValueError as error:
        raise ValueError("core40_path_outside_repository") from error
    if prefix is not None and not relative.startswith(prefix):
        raise ValueError("core40_path_prefix_invalid")
    return candidate


def _jsonl_canonical_sha256(rows: Sequence[Mapping[str, Any]]) -> str:
    payload = "\n".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for row in rows
    ) + "\n"
    return sha256_text(payload)


def _load_object(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(code) from error
    if not isinstance(value, dict):
        raise ValueError(code)
    return value


def _load_config(config_path: Path) -> tuple[Path, dict[str, Any], str]:
    repo_root = _repo_root(config_path)
    config = _load_object(config_path, "core40_config_invalid")
    if set(config) != CONFIG_FIELDS or config.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("core40_config_contract_invalid")
    if config.get("baseline_id") != BASELINE_ID:
        raise ValueError("core40_baseline_id_invalid")
    if config.get("evaluation_tier") != "provisional":
        raise ValueError("core40_evaluation_tier_invalid")
    if config.get("expected_counts") != {
        "single_doc": 10,
        "multi_doc_compare": 10,
        "follow_up": 10,
        "unknown": 10,
        "total": 40,
    }:
        raise ValueError("core40_expected_counts_invalid")
    artifacts = config.get("artifacts")
    runtime = config.get("runtime")
    outputs = config.get("outputs")
    if not isinstance(artifacts, dict) or set(artifacts) != ARTIFACT_FIELDS:
        raise ValueError("core40_artifacts_contract_invalid")
    if not isinstance(runtime, dict) or set(runtime) != RUNTIME_FIELDS:
        raise ValueError("core40_runtime_contract_invalid")
    if runtime != FROZEN_RUNTIME:
        raise ValueError("core40_runtime_not_frozen")
    if config.get("execution_contract") != EXECUTION_CONTRACT:
        raise ValueError("core40_execution_contract_not_frozen")
    if not isinstance(outputs, dict) or set(outputs) != OUTPUT_FIELDS:
        raise ValueError("core40_outputs_contract_invalid")
    for field in (
        "cases_file_sha256",
        "cases_dataset_sha256",
        "cases_jsonl_canonical_sha256",
        "manifest_sha256",
        "chunks_sha256",
        "index_metadata_sha256",
        "index_config_file_sha256",
    ):
        if not isinstance(artifacts.get(field), str) or SHA256_RE.fullmatch(artifacts[field]) is None:
            raise ValueError("core40_artifact_hash_invalid")
    if float(runtime["budget_limit_usd"]) > 2.0:
        raise ValueError("core40_budget_limit_exceeds_two_usd")
    for field in ("cases", "manifest", "chunks", "index_dir", "tiktoken_cache_dir"):
        _relative_path(repo_root, artifacts[field])
    for field in ("run_records", "chat_transcripts", "private_summary"):
        _relative_path(repo_root, outputs[field], prefix="evaluation/private/")
    public_prefix = f"evaluation/baselines/{BASELINE_ID}/"
    for field in ("preflight_receipt", "receipt"):
        _relative_path(repo_root, outputs[field], prefix=public_prefix)
    return repo_root, config, sha256_file(config_path)


def _require_hash(path: Path, expected: str, code: str) -> None:
    if not path.is_file() or sha256_file(path) != expected:
        raise ValueError(code)


def verify_baseline(config_path: Path) -> VerifiedCore40:
    """Verify all frozen inputs and index bytes without provider/network use."""

    repo_root, config, config_sha256 = _load_config(config_path)
    artifacts = config["artifacts"]
    paths = {
        field: _relative_path(repo_root, artifacts[field])
        for field in ("cases", "manifest", "chunks", "index_dir", "tiktoken_cache_dir")
    }
    _require_hash(paths["cases"], artifacts["cases_file_sha256"], "core40_cases_file_hash_mismatch")
    _require_hash(paths["manifest"], artifacts["manifest_sha256"], "core40_manifest_hash_mismatch")
    _require_hash(paths["chunks"], artifacts["chunks_sha256"], "core40_chunks_hash_mismatch")
    _require_hash(
        paths["index_dir"] / "metadata.json",
        artifacts["index_metadata_sha256"],
        "core40_index_metadata_hash_mismatch",
    )
    _require_hash(
        paths["index_dir"] / "index-config.json",
        artifacts["index_config_file_sha256"],
        "core40_index_config_file_hash_mismatch",
    )
    if not paths["tiktoken_cache_dir"].is_dir():
        raise ValueError("core40_tiktoken_cache_missing")

    cases = read_jsonl(paths["cases"])
    if len(cases) != 40 or any(validate_case(case) for case in cases):
        raise ValueError("core40_case_contract_invalid")
    if dataset_sha256(cases) != artifacts["cases_dataset_sha256"]:
        raise ValueError("core40_cases_dataset_hash_mismatch")
    if _jsonl_canonical_sha256(cases) != artifacts["cases_jsonl_canonical_sha256"]:
        raise ValueError("core40_cases_jsonl_canonical_hash_mismatch")
    if Counter(case["task_type"] for case in cases) != Counter({task: 10 for task in TASK_TYPES}):
        raise ValueError("core40_task_counts_invalid")
    if Counter(case["review"]["status"] for case in cases) != Counter({"draft": 40}):
        raise ValueError("core40_review_status_changed")
    case_ids = [case["case_id"] for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("core40_duplicate_case_id")
    if any(case["source_manifest_sha256"] != artifacts["manifest_sha256"] for case in cases):
        raise ValueError("core40_case_manifest_binding_mismatch")

    manifest_rows = read_jsonl(paths["manifest"])
    known_doc_ids = {
        row["doc_id"]
        for row in manifest_rows
        if isinstance(row.get("doc_id"), str) and row.get("index_eligible") is True
    }
    if not manifest_rows or len(known_doc_ids) != len(manifest_rows):
        raise ValueError("core40_refined_manifest_count_mismatch")
    referenced_doc_ids = {
        doc_id
        for case in cases
        for doc_id in (
            list(case["document_scope"]["doc_ids"])
            + list(case["gold"]["required_doc_ids"])
        )
    }
    if not referenced_doc_ids <= known_doc_ids:
        raise ValueError("core40_referenced_document_missing")

    chunks = read_jsonl(paths["chunks"])
    chunk_by_id = {chunk.get("chunk_id"): chunk for chunk in chunks}
    if len(chunk_by_id) != len(chunks) or None in chunk_by_id:
        raise ValueError("core40_chunk_identity_invalid")
    chunk_doc_ids = {chunk.get("doc_id") for chunk in chunks}
    if not referenced_doc_ids <= chunk_doc_ids:
        raise ValueError("core40_scoped_document_has_no_chunk")

    metadata = _load_object(paths["index_dir"] / "metadata.json", "core40_index_metadata_invalid")
    index_config = _load_object(paths["index_dir"] / "index-config.json", "core40_index_config_invalid")
    if len(chunks) != metadata.get("count"):
        raise ValueError("core40_refined_chunk_count_mismatch")
    if api_config_sha256(index_config) != metadata.get("index_config_sha256"):
        raise ValueError("core40_index_config_hash_mismatch")
    if (
        metadata.get("corpus_manifest_sha256") != artifacts["manifest_sha256"]
        or metadata.get("chunk_artifact_sha256") != artifacts["chunks_sha256"]
        or metadata.get("embedding_model") != config["runtime"]["embedding_model"]
        or metadata.get("dimensions") != config["runtime"]["embedding_dimensions"]
        or metadata.get("api_profile") != config["runtime"]["api_profile"]
    ):
        raise ValueError("core40_index_corpus_binding_mismatch")
    index = ExactDenseIndex._load_unlocked(
        paths["index_dir"],
        chunks,
        expected_embedding_model=config["runtime"]["embedding_model"],
        expected_dimensions=config["runtime"]["embedding_dimensions"],
        expected_api_profile=config["runtime"]["api_profile"],
        expected_index_config_sha256=metadata["index_config_sha256"],
    )
    return VerifiedCore40(
        repo_root=repo_root,
        config_path=config_path.resolve(),
        config=config,
        config_sha256=config_sha256,
        cases=cases,
        chunks=chunks,
        chunk_by_id=chunk_by_id,
        known_doc_ids=known_doc_ids,
        index_metadata=metadata,
        index_config=index_config,
        index=index,
        runtime_contract_sha256s=_contract_sha256s(),
    )


def _contract_sha256s() -> dict[str, str]:
    return {
        "system_instructions": sha256_text(SYSTEM_INSTRUCTIONS),
        "provider_response_schema": sha256_text(
            canonical_json(
                build_openai_answer_plan_schema(FROZEN_RUNTIME["max_citations"])
            )
        ),
        "prompt_builder_source": sha256_text(inspect.getsource(_build_prompt)),
        "retrieval_query_source": sha256_text(inspect.getsource(_retrieval_query)),
        "context_selector_source": sha256_text(
            inspect.getsource(_select_context_hits)
        ),
        "execution_contract": sha256_text(canonical_json(EXECUTION_CONTRACT)),
        "frozen_runtime": sha256_text(canonical_json(FROZEN_RUNTIME)),
        "rag_pipeline_module": sha256_file(
            Path(sys.modules[RagPipeline.__module__].__file__ or "")
        ),
        "indexing_embeddings_module": sha256_file(
            Path(sys.modules[EmbeddingCache.__module__].__file__ or "")
        ),
        "api_embeddings_module": sha256_file(
            Path(sys.modules[OpenAIEmbeddingProvider.__module__].__file__ or "")
        ),
        "budget_module": sha256_file(
            Path(sys.modules[BudgetLedger.__module__].__file__ or "")
        ),
        "exact_index_module": sha256_file(
            Path(sys.modules[ExactDenseIndex.__module__].__file__ or "")
        ),
        "api_generation_module": sha256_file(
            Path(sys.modules[OpenAIGenerator.__module__].__file__ or "")
        ),
        "core40_baseline_module": sha256_file(Path(__file__)),
    }


def _assert_runtime_contract_current(verified: VerifiedCore40) -> None:
    if _contract_sha256s() != verified.runtime_contract_sha256s:
        raise ValueError("core40_runtime_contract_drift")


def preflight_report(verified: VerifiedCore40) -> dict[str, Any]:
    runtime = verified.config["runtime"]
    return {
        "schema_version": SCHEMA_VERSION,
        "passed": True,
        "baseline_id": BASELINE_ID,
        "evaluation_tier": "provisional",
        "official_gold_ready": False,
        "review_statuses": {"draft": 40},
        "config_sha256": verified.config_sha256,
        "artifact_sha256s": {
            "cases_file": verified.config["artifacts"]["cases_file_sha256"],
            "cases_dataset": verified.eval_set_sha256,
            "cases_jsonl_canonical": verified.config["artifacts"]["cases_jsonl_canonical_sha256"],
            "manifest": verified.config["artifacts"]["manifest_sha256"],
            "chunks": verified.config["artifacts"]["chunks_sha256"],
            "index_metadata": verified.config["artifacts"]["index_metadata_sha256"],
            "index_config_file": verified.config["artifacts"]["index_config_file_sha256"],
            "index_config": verified.index_metadata["index_config_sha256"],
        },
        "runtime_contract_sha256s": copy.deepcopy(
            verified.runtime_contract_sha256s
        ),
        "runtime_contract_sha256": sha256_text(
            canonical_json(verified.runtime_contract_sha256s)
        ),
        "counts": {
            "cases": len(verified.cases),
            "single_doc": 10,
            "multi_doc_compare": 10,
            "follow_up": 10,
            "unknown": 10,
            "documents": len(verified.known_doc_ids),
            "chunks": len(verified.chunks),
            "history_cases": sum(bool(case["history"]) for case in verified.cases),
            "explicit_scope_cases": sum(
                case["document_scope"]["mode"] == "explicit"
                for case in verified.cases
            ),
        },
        "runtime": copy.deepcopy(runtime),
        "estimated_live_requests": {
            "generation_calls": 40,
            "query_embedding_calls_upper_bound": len(
                {
                    canonical_json(
                        {
                            "question": case["question"],
                            "history": case["history"],
                        }
                    )
                    for case in verified.cases
                }
            ),
            "total_provider_requests_upper_bound": 80,
            "corpus_embedding_calls": 0,
        },
        "provider_calls_performed": 0,
        "private_corpus_egress_performed": False,
        "execution_contract": copy.deepcopy(verified.config["execution_contract"]),
        "blockers": [
            "Explicit OpenAI egress approval is required before live execution.",
            "The 40 draft cases remain provisional until named human review approves them.",
        ],
    }


def write_preflight_receipt(verified: VerifiedCore40) -> dict[str, Any]:
    report = preflight_report(verified)
    path = _relative_path(
        verified.repo_root,
        verified.config["outputs"]["preflight_receipt"],
        prefix=f"evaluation/baselines/{BASELINE_ID}/",
    )
    write_json(path, report)
    return report


def build_request(case: Mapping[str, Any], *, config_sha256: str, max_citations: int) -> dict[str, Any]:
    request_material = f"{case['case_id']}:{config_sha256}"
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": f"req-{sha256_text(request_material)[:24]}",
        "question": case["question"],
        "history": copy.deepcopy(case["history"]),
        "document_scope": copy.deepcopy(case["document_scope"]),
        "options": {"max_citations": max_citations},
    }


def _runtime_paths(verified: VerifiedCore40) -> dict[str, Path]:
    outputs = {
        key: _relative_path(verified.repo_root, value)
        for key, value in verified.config["outputs"].items()
    }
    run_dir = outputs["run_records"].parent
    if outputs["chat_transcripts"].parent != run_dir or outputs["private_summary"].parent != run_dir:
        raise ValueError("core40_private_output_directory_mismatch")
    return {
        **outputs,
        "run_dir": run_dir,
        "run_state": run_dir / "run-state.json",
        "checkpoints": run_dir / "case-checkpoints",
        "query_cache": run_dir / "query-cache",
        "budget_ledger": run_dir / "budget-ledger.json",
        "recovery_audit": run_dir / "manual-recovery-audit.json",
        "run_lock": run_dir / ".run.lock",
    }


def _secure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)


def _write_private_json(path: Path, value: Mapping[str, Any]) -> None:
    _secure_directory(path.parent)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            json.dump(value, output, ensure_ascii=False, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _write_private_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    _secure_directory(path.parent)
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


@contextmanager
def _exclusive_run_lock(path: Path) -> Iterator[None]:
    _secure_directory(path.parent)
    with path.open("a+b") as lock:
        path.chmod(0o600)
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("core40_run_already_active") from error
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _checkpoint_identity(verified: VerifiedCore40) -> dict[str, Any]:
    _assert_runtime_contract_current(verified)
    artifacts = verified.config["artifacts"]
    identity = {
        "schema_version": SCHEMA_VERSION,
        "baseline_id": BASELINE_ID,
        "config_sha256": verified.config_sha256,
        "cases_dataset_sha256": verified.eval_set_sha256,
        "manifest_sha256": artifacts["manifest_sha256"],
        "chunks_sha256": artifacts["chunks_sha256"],
        "index_metadata_sha256": artifacts["index_metadata_sha256"],
        "index_config_sha256": verified.index_metadata["index_config_sha256"],
        "budget_limit_usd": verified.config["runtime"]["budget_limit_usd"],
        "runtime_contract_sha256s": copy.deepcopy(
            verified.runtime_contract_sha256s
        ),
        "runtime_contract_sha256": sha256_text(
            canonical_json(verified.runtime_contract_sha256s)
        ),
    }
    return identity


def _checkpoint_path(paths: Mapping[str, Path], case_id: str) -> Path:
    return paths["checkpoints"] / f"{sha256_text(case_id)}.json"


def _envelope(payload: Mapping[str, Any]) -> dict[str, Any]:
    copied = copy.deepcopy(dict(payload))
    return {"payload": copied, "payload_sha256": sha256_text(canonical_json(copied))}


def _read_checkpoint_payload(path: Path) -> dict[str, Any]:
    envelope = _load_object(path, "core40_checkpoint_invalid")
    if set(envelope) != {"payload", "payload_sha256"} or not isinstance(
        envelope["payload"], dict
    ):
        raise ValueError("core40_checkpoint_invalid")
    payload = envelope["payload"]
    if sha256_text(canonical_json(payload)) != envelope.get("payload_sha256"):
        raise ValueError("core40_checkpoint_hash_mismatch")
    return payload


def _validate_completed_checkpoint(
    payload: Mapping[str, Any],
    *,
    case_id: str,
    expected_identity: Mapping[str, Any],
) -> None:
    if payload.get("identity") != expected_identity or payload.get("case_id") != case_id:
        raise ValueError("core40_checkpoint_identity_mismatch")
    if (
        payload.get("state") != "completed"
        or not isinstance(payload.get("result"), dict)
        or not isinstance(payload.get("run_record"), dict)
        or not isinstance(payload.get("chat_transcript"), dict)
    ):
        raise ValueError("core40_checkpoint_invalid")
    expected_hashes = {
        "result_sha256": sha256_text(canonical_json(payload["result"])),
        "run_record_sha256": sha256_text(canonical_json(payload["run_record"])),
        "chat_transcript_sha256": sha256_text(
            canonical_json(payload["chat_transcript"])
        ),
    }
    if any(payload.get(key) != value for key, value in expected_hashes.items()):
        raise ValueError("core40_checkpoint_artifact_hash_mismatch")


def _load_checkpoint(path: Path, verified: VerifiedCore40, case_id: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = _read_checkpoint_payload(path)
    if payload.get("identity") != _checkpoint_identity(verified) or payload.get("case_id") != case_id:
        raise ValueError("core40_checkpoint_identity_mismatch")
    if payload.get("state") == "started":
        raise ValueError("core40_started_case_requires_budget_audit")
    if payload.get("state") == "interrupted":
        raise ValueError("core40_interrupted_case_requires_budget_audit")
    _validate_completed_checkpoint(
        payload,
        case_id=case_id,
        expected_identity=_checkpoint_identity(verified),
    )
    return payload


def _started_payload(verified: VerifiedCore40, case_id: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "core40_case_checkpoint",
        "state": "started",
        "case_id": case_id,
        "identity": _checkpoint_identity(verified),
    }


def _completed_payload(
    verified: VerifiedCore40,
    case_id: str,
    result: Mapping[str, Any],
    run_record: Mapping[str, Any],
    chat_transcript: Mapping[str, Any],
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "core40_case_checkpoint",
        "state": "completed",
        "case_id": case_id,
        "identity": _checkpoint_identity(verified),
        "result": copy.deepcopy(dict(result)),
        "run_record": copy.deepcopy(dict(run_record)),
        "chat_transcript": copy.deepcopy(dict(chat_transcript)),
    }
    payload.update(
        {
            "result_sha256": sha256_text(canonical_json(payload["result"])),
            "run_record_sha256": sha256_text(canonical_json(payload["run_record"])),
            "chat_transcript_sha256": sha256_text(canonical_json(payload["chat_transcript"])),
        }
    )
    return payload


def _interrupted_payload(
    verified: VerifiedCore40,
    case_id: str,
    request: Mapping[str, Any],
    provider_exchange: Mapping[str, Any],
    error: BaseException,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "core40_case_checkpoint",
        "state": "interrupted",
        "case_id": case_id,
        "identity": _checkpoint_identity(verified),
        "request": copy.deepcopy(dict(request)),
        "provider_exchange": copy.deepcopy(dict(provider_exchange)),
        "runtime_error": {
            "type": type(error).__name__,
            "message": str(error),
            "manual_budget_audit_required": True,
        },
    }


def _provider_exchange_requires_budget_audit(
    provider_exchange: Mapping[str, Any],
) -> bool:
    for lane in ("embedding", "generation"):
        event = provider_exchange.get(lane)
        if event is None:
            continue
        if not isinstance(event, Mapping):
            return True
        if event.get("error") is not None:
            return True
        if event.get("request_arguments") is not None and event.get("response") is None:
            return True
    return False


def _candidate_error_requires_budget_audit(
    result: Mapping[str, Any],
    provider_exchange: Mapping[str, Any],
) -> bool:
    response = result.get("response")
    if not isinstance(response, Mapping) or response.get("status") != "error":
        return False
    return any(
        isinstance(event, Mapping)
        and event.get("request_arguments") is not None
        for event in (
            provider_exchange.get("embedding"),
            provider_exchange.get("generation"),
        )
    )


def _recovery_identity_is_compatible(
    candidate: Any,
    current: Mapping[str, Any],
) -> bool:
    """Allow only the self-hash drift introduced by this recovery patch."""

    if candidate == current:
        return True
    if not isinstance(candidate, Mapping) or set(candidate) != set(current):
        return False
    ordinary_fields = set(current) - {
        "runtime_contract_sha256s",
        "runtime_contract_sha256",
    }
    if any(candidate.get(field) != current.get(field) for field in ordinary_fields):
        return False
    previous_contract = candidate.get("runtime_contract_sha256s")
    current_contract = current.get("runtime_contract_sha256s")
    if (
        not isinstance(previous_contract, Mapping)
        or not isinstance(current_contract, Mapping)
        or set(previous_contract) != set(current_contract)
        or any(
            not isinstance(value, str) or SHA256_RE.fullmatch(value) is None
            for value in previous_contract.values()
        )
    ):
        return False
    changed = {
        field
        for field in current_contract
        if previous_contract.get(field) != current_contract.get(field)
    }
    if changed != {"core40_baseline_module"}:
        return False
    return candidate.get("runtime_contract_sha256") == sha256_text(
        canonical_json(previous_contract)
    )


def _retrieval_records_from_hits(
    hits: Sequence[IndexSearchHit],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for rank, hit in enumerate(hits, start=1):
        chunk = hit.chunk
        record: dict[str, Any] = {
            "rank": rank,
            "doc_id": chunk["doc_id"],
            "chunk_id": chunk["chunk_id"],
            "score": hit.score,
        }
        source_block_ids = chunk.get("source_block_ids")
        if isinstance(source_block_ids, list):
            record["source_block_ids"] = list(source_block_ids)
        if chunk.get("retrieval_role") == "visual_auxiliary":
            record.update(
                {
                    "occurrence_id": chunk["occurrence_id"],
                    "evidence_ids": list(chunk["evidence_ids"]),
                    "evidence_type": chunk["evidence_type"],
                    "page": chunk["page"],
                    "bbox": dict(chunk["bbox"]),
                    "crop_sha256": chunk["crop_sha256"],
                }
            )
        lane = getattr(hit, "lane", None)
        if isinstance(lane, str):
            record.update(
                {
                    "lane": lane,
                    "lane_rank": getattr(hit, "lane_rank"),
                    "dense_score": getattr(hit, "dense_score"),
                }
            )
        records.append(record)
    return records


RecoveryCounterFactory = Callable[[str, Path], Any]


def _recovery_counter(model: str, cache_dir: Path) -> TiktokenCounter:
    return TiktokenCounter(model, cache_dir=cache_dir)


def _recoverable_interrupted_context(
    verified: VerifiedCore40,
    paths: Mapping[str, Path],
    case: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    counter_factory: RecoveryCounterFactory,
) -> dict[str, Any]:
    runtime = verified.config["runtime"]
    expected_request = build_request(
        case,
        config_sha256=verified.config_sha256,
        max_citations=runtime["max_citations"],
    )
    if payload.get("request") != expected_request:
        raise ValueError("core40_recovery_request_mismatch")
    runtime_error = payload.get("runtime_error")
    if (
        not isinstance(runtime_error, Mapping)
        or runtime_error.get("manual_budget_audit_required") is not True
        or not isinstance(runtime_error.get("type"), str)
        or not isinstance(runtime_error.get("message"), str)
    ):
        raise ValueError("core40_recovery_runtime_error_invalid")
    provider_exchange = payload.get("provider_exchange")
    if not isinstance(provider_exchange, Mapping) or set(provider_exchange) != {
        "embedding",
        "generation",
    }:
        raise ValueError("core40_recovery_provider_exchange_invalid")

    tokenizer_cache = _relative_path(
        verified.repo_root,
        verified.config["artifacts"]["tiktoken_cache_dir"],
    )
    embedding_counter = counter_factory(runtime["embedding_model"], tokenizer_cache)
    generation_counter = counter_factory(runtime["generator_model"], tokenizer_cache)
    retrieval_query = _retrieval_query(
        dict(expected_request),
        embedding_counter,
        max_tokens=8191,
    )

    embedding_event = provider_exchange.get("embedding")
    if not isinstance(embedding_event, Mapping) or set(embedding_event) != {
        "request_arguments",
        "response",
        "error",
    }:
        raise ValueError("core40_recovery_embedding_exchange_invalid")
    embedding_provider = OpenAIEmbeddingProvider(
        client=object(),
        model=runtime["embedding_model"],
        dimensions=runtime["embedding_dimensions"],
        api_profile=runtime["api_profile"],
    )
    expected_embedding_request = {
        "model": runtime["embedding_model"],
        "input": [retrieval_query],
        "dimensions": runtime["embedding_dimensions"],
        "encoding_format": "float",
    }
    if embedding_event.get("request_arguments") != expected_embedding_request:
        raise ValueError("core40_recovery_embedding_request_mismatch")
    embedding_response = embedding_event.get("response")
    if (
        embedding_event.get("error") is not None
        or not isinstance(embedding_response, Mapping)
        or embedding_response.get("vectors_omitted") is not True
        or not isinstance(embedding_response.get("vectors_sha256"), str)
        or SHA256_RE.fullmatch(embedding_response["vectors_sha256"]) is None
    ):
        raise ValueError("core40_recovery_embedding_response_invalid")

    cache_namespace = embedding_cache_namespace(embedding_provider, role="query")
    query_cache_key = EmbeddingCache.key(
        corpus_manifest_sha256=verified.config["artifacts"]["manifest_sha256"],
        chunk_config_sha256=sha256_text("query-v1"),
        model=cache_namespace,
        dimensions=runtime["embedding_dimensions"],
        content_sha256=sha256_text(retrieval_query),
    )
    query_vector = EmbeddingCache(paths["query_cache"]).get(
        query_cache_key,
        runtime["embedding_dimensions"],
    )
    if query_vector is None:
        raise ValueError("core40_recovery_query_cache_missing")
    scope = expected_request["document_scope"]
    allowed_doc_ids = set(scope["doc_ids"]) if scope["mode"] == "explicit" else None
    hits = verified.index.search(
        query_vector,
        top_k=runtime["retrieval_top_k"],
        allowed_doc_ids=allowed_doc_ids,
    )
    context_hits = _select_context_hits(
        hits,
        context_top_k=runtime["context_top_k"],
        table_context_cap=None,
    )
    if not context_hits:
        raise ValueError("core40_recovery_context_missing")
    generation_prompt = _build_prompt(dict(expected_request), context_hits)

    generation_event = provider_exchange.get("generation")
    if not isinstance(generation_event, Mapping) or set(generation_event) != {
        "request_arguments",
        "response",
        "error",
    }:
        raise ValueError("core40_recovery_generation_exchange_invalid")
    generation_arguments = generation_event.get("request_arguments")
    if not isinstance(generation_arguments, Mapping):
        raise ValueError("core40_recovery_generation_request_invalid")
    if generation_arguments.get("input") != generation_prompt:
        raise ValueError("core40_recovery_prompt_mismatch")
    expected_generation_request = {
        "model": runtime["generator_model"],
        "instructions": SYSTEM_INSTRUCTIONS,
        "input": generation_prompt,
        "store": False,
        "max_output_tokens": runtime["max_output_tokens"],
        "reasoning": {"effort": runtime["reasoning_effort"]},
        "text": {
            "format": {
                "type": "json_schema",
                "name": "rag_answer_plan",
                "strict": True,
                "schema": build_openai_answer_plan_schema(
                    runtime["max_citations"]
                ),
            }
        },
    }
    if dict(generation_arguments) != expected_generation_request:
        raise ValueError("core40_recovery_generation_request_mismatch")
    generation_error = generation_event.get("error")
    if (
        generation_event.get("response") is not None
        or not isinstance(generation_error, Mapping)
        or generation_error.get("type") != "APIConnectionError"
        or not isinstance(generation_error.get("message"), str)
        or not generation_error["message"]
    ):
        raise ValueError("core40_recovery_generation_error_invalid")

    embedding_tokens = embedding_counter.count(retrieval_query)
    usage = embedding_response.get("usage")
    if isinstance(usage, Mapping) and "total_tokens" in usage:
        observed_embedding_tokens = usage.get("total_tokens")
        if (
            not isinstance(observed_embedding_tokens, int)
            or isinstance(observed_embedding_tokens, bool)
            or observed_embedding_tokens < 0
        ):
            raise ValueError("core40_recovery_embedding_usage_invalid")
        embedding_tokens = observed_embedding_tokens
    generation_input_upper = (
        generation_counter.count(SYSTEM_INSTRUCTIONS)
        + generation_counter.count(generation_prompt)
        + 256
    )
    generator = OpenAIGenerator(
        client=object(),
        model=runtime["generator_model"],
        max_output_tokens=runtime["max_output_tokens"],
        max_citations=runtime["max_citations"],
        reasoning_effort=runtime["reasoning_effort"],
    )
    generation_cost_upper = generator.estimate_cost(
        generation_input_upper,
        runtime["max_output_tokens"],
    )
    embedding_cost = embedding_provider.estimate_cost(embedding_tokens)
    return {
        "request": expected_request,
        "provider_exchange": copy.deepcopy(dict(provider_exchange)),
        "retrieval_query": retrieval_query,
        "retrieval": _retrieval_records_from_hits(hits),
        "generation_prompt": generation_prompt,
        "embedding_tokens": embedding_tokens,
        "generation_input_upper": generation_input_upper,
        "generation_output_upper": runtime["max_output_tokens"],
        "generation_cost_upper": generation_cost_upper,
        "embedding_cost": embedding_cost,
        "query_cache_key_sha256": sha256_text(query_cache_key),
    }


def _recovery_budget_operation(case_id: str, generation_prompt: str) -> tuple[str, str]:
    operation = (
        f"{INTERRUPTED_ERROR_RECOVERY_MODE}:{BASELINE_ID}:{case_id}:"
        f"{sha256_text(generation_prompt)}"
    )
    return operation, sha256_text(operation)


def _authorized_recovery_reservations(
    checkpoint_payloads: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    authorized: dict[str, dict[str, Any]] = {}
    for case_id, payload in checkpoint_payloads.items():
        recovery = payload.get("recovery")
        if recovery is None:
            continue
        transcript = payload.get("chat_transcript")
        result = payload.get("result")
        if (
            payload.get("state") != "completed"
            or not isinstance(recovery, Mapping)
            or recovery.get("mode") != INTERRUPTED_ERROR_RECOVERY_MODE
            or recovery.get("provider_calls_performed") != 0
            or not isinstance(transcript, Mapping)
            or transcript.get("recovery") != recovery
            or not isinstance(result, Mapping)
            or not isinstance(result.get("response"), Mapping)
            or result["response"].get("status") != "error"
            or not isinstance(result["response"].get("error"), Mapping)
            or result["response"]["error"].get("code")
            != "provider_call_interrupted"
        ):
            raise ValueError("core40_recovery_provenance_invalid")
        provider_exchange = transcript.get("provider_exchange")
        generation = (
            provider_exchange.get("generation")
            if isinstance(provider_exchange, Mapping)
            else None
        )
        if (
            not isinstance(generation, Mapping)
            or generation.get("response") is not None
            or not isinstance(generation.get("error"), Mapping)
            or generation["error"].get("type") != "APIConnectionError"
            or sha256_text(canonical_json(provider_exchange))
            != recovery.get("original_provider_exchange_sha256")
        ):
            raise ValueError("core40_recovery_provenance_invalid")
        reconstruction = recovery.get("retrieval_reconstruction")
        budget = recovery.get("budget")
        generation_prompt = transcript.get("generation_prompt")
        if (
            not isinstance(reconstruction, Mapping)
            or not isinstance(budget, Mapping)
            or budget.get("accounting_mode")
            != "permanent_upper_bound_reservation"
            or not isinstance(generation_prompt, str)
            or sha256_text(generation_prompt)
            != reconstruction.get("generation_prompt_sha256")
        ):
            raise ValueError("core40_recovery_provenance_invalid")
        reservation_id = budget.get("reservation_id")
        operation_sha256 = budget.get("operation_sha256")
        _operation, expected_operation_sha256 = _recovery_budget_operation(
            case_id,
            generation_prompt,
        )
        try:
            reserved_usd = Decimal(str(budget["generation_cost_upper_usd"]))
        except Exception as error:
            raise ValueError("core40_recovery_provenance_invalid") from error
        if (
            not isinstance(reservation_id, str)
            or not reservation_id
            or reservation_id in authorized
            or operation_sha256 != expected_operation_sha256
            or reserved_usd <= 0
        ):
            raise ValueError("core40_recovery_provenance_invalid")
        authorized[reservation_id] = {
            "operation_sha256": operation_sha256,
            "reserved_usd": reserved_usd,
        }
    return authorized


def _ensure_recovery_budget_reservation(
    verified: VerifiedCore40,
    paths: Mapping[str, Path],
    *,
    case_id: str,
    generation_prompt: str,
    cost_upper: Decimal,
    authorized_reservations: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if cost_upper <= 0:
        raise ValueError("core40_recovery_cost_invalid")
    if not paths["budget_ledger"].is_file():
        raise ValueError("core40_recovery_budget_ledger_missing")
    ledger = BudgetLedger(
        paths["budget_ledger"],
        limit_usd=verified.config["runtime"]["budget_limit_usd"],
    )
    ledger.snapshot()
    operation, operation_sha256 = _recovery_budget_operation(
        case_id,
        generation_prompt,
    )

    def matching_reservations() -> tuple[dict[str, Any], list[tuple[str, Mapping[str, Any]]]]:
        state = _load_object(paths["budget_ledger"], "core40_recovery_budget_ledger_invalid")
        reservations = state.get("reservations")
        if not isinstance(reservations, dict):
            raise ValueError("core40_recovery_budget_ledger_invalid")
        matches = [
            (reservation_id, reservation)
            for reservation_id, reservation in reservations.items()
            if isinstance(reservation, Mapping)
            and reservation.get("operation_sha256") == operation_sha256
        ]
        unrelated: list[str] = []
        for reservation_id, reservation in reservations.items():
            if (
                isinstance(reservation, Mapping)
                and reservation.get("operation_sha256") == operation_sha256
            ):
                continue
            expected = authorized_reservations.get(reservation_id)
            try:
                reserved = Decimal(str(reservation.get("reserved_usd")))
            except Exception:
                reserved = Decimal("-1")
            if (
                not isinstance(reservation, Mapping)
                or not isinstance(expected, Mapping)
                or reservation.get("operation_sha256")
                != expected.get("operation_sha256")
                or reserved != expected.get("reserved_usd")
            ):
                unrelated.append(reservation_id)
        if unrelated:
            raise ValueError("core40_recovery_budget_outstanding_reservation")
        missing = set(authorized_reservations) - set(reservations)
        if missing:
            raise ValueError("core40_recovery_budget_reservation_missing")
        return state, matches

    _state, matches = matching_reservations()
    if len(matches) > 1:
        raise ValueError("core40_recovery_budget_duplicate_reservation")
    if matches:
        reservation_id, reservation = matches[0]
        try:
            reserved = Decimal(str(reservation.get("reserved_usd")))
        except Exception as error:
            raise ValueError("core40_recovery_budget_ledger_invalid") from error
        if reserved != cost_upper:
            raise ValueError("core40_recovery_budget_reservation_mismatch")
    else:
        reservation_id = ledger.reserve(cost_upper, operation)
        _state, matches = matching_reservations()
        if len(matches) != 1 or matches[0][0] != reservation_id:
            raise ValueError("core40_recovery_budget_reservation_missing")
    snapshot = ledger.snapshot()
    expected_reserved = sum(
        (item["reserved_usd"] for item in authorized_reservations.values()),
        Decimal("0"),
    )
    current_already_authorized = reservation_id in authorized_reservations
    if not current_already_authorized:
        expected_reserved += cost_upper
    if snapshot.breached or snapshot.reserved_usd < expected_reserved:
        raise ValueError("core40_recovery_budget_not_conservative")
    return {
        "accounting_mode": "permanent_upper_bound_reservation",
        "reservation_id": reservation_id,
        "operation_sha256": operation_sha256,
        "generation_cost_upper_usd": str(cost_upper),
        "ledger_committed_usd": str(snapshot.committed_usd),
        "ledger_reserved_usd": str(snapshot.reserved_usd),
        "ledger_available_usd": str(snapshot.available_usd),
        "ledger_breached": snapshot.breached,
    }


def _initialize_run_state(verified: VerifiedCore40, paths: Mapping[str, Path]) -> None:
    _secure_directory(paths["run_dir"])
    _secure_directory(paths["checkpoints"])
    expected = _checkpoint_identity(verified)
    if paths["run_state"].exists():
        if _load_object(paths["run_state"], "core40_run_state_invalid") != expected:
            raise ValueError("core40_run_state_identity_mismatch")
    else:
        if any(paths[field].exists() for field in ("run_records", "chat_transcripts", "private_summary")):
            raise ValueError("core40_run_state_missing")
        _write_private_json(paths["run_state"], expected)
    ledger = BudgetLedger(
        paths["budget_ledger"],
        limit_usd=verified.config["runtime"]["budget_limit_usd"],
    )
    ledger.snapshot()
    paths["budget_ledger"].chmod(0o600)
    ledger.lock_path.chmod(0o600)


def _completed_cases(
    verified: VerifiedCore40,
    paths: Mapping[str, Path],
) -> dict[str, dict[str, Any]]:
    completed: dict[str, dict[str, Any]] = {}
    known = {case["case_id"] for case in verified.cases}
    if paths["checkpoints"].exists():
        for path in paths["checkpoints"].glob("*.json"):
            envelope = _load_object(path, "core40_checkpoint_invalid")
            payload = envelope.get("payload") if isinstance(envelope, dict) else None
            case_id = payload.get("case_id") if isinstance(payload, dict) else None
            if not isinstance(case_id, str) or case_id not in known or path != _checkpoint_path(paths, case_id):
                raise ValueError("core40_checkpoint_unknown_case")
            checked = _load_checkpoint(path, verified, case_id)
            if checked is not None:
                completed[case_id] = checked
    return completed


def _environment(verified: VerifiedCore40) -> dict[str, Any]:
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        physical_pages = os.sysconf("SC_PHYS_PAGES")
        ram_gb = round(page_size * physical_pages / 1024**3, 3)
    except (AttributeError, OSError, ValueError):
        ram_gb = 1.0
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform()[:256],
        "region": "local",
        "machine_type": "local-api-baseline",
        "vcpu": max(1, os.cpu_count() or 1),
        "ram_gb": max(ram_gb, 0.001),
        "gpu_model": None,
        "disk_gb": max(round(shutil.disk_usage(verified.repo_root).total / 1024**3, 3), 0.001),
        "dependency_lock_sha256": sha256_file(verified.repo_root / "pyproject.toml"),
    }


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _json_safe(model_dump(mode="json"))
    return repr(value)


class _ProviderAudit:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._events: dict[str, Any] = {"embedding": None, "generation": None}

    def endpoint(self, endpoint: Any, lane: str) -> Any:
        audit = self

        class Endpoint:
            def create(self, **kwargs: Any) -> Any:
                event: dict[str, Any] = {
                    "request_arguments": _json_safe(copy.deepcopy(kwargs)),
                    "response": None,
                    "error": None,
                }
                audit._events[lane] = event
                try:
                    response = endpoint.create(**kwargs)
                except Exception as error:
                    event["error"] = {
                        "type": type(error).__name__,
                        "message": str(error),
                    }
                    raise
                dumped = _json_safe(response)
                if lane == "embedding" and isinstance(dumped, dict):
                    data = dumped.pop("data", None)
                    event["response"] = dumped
                    event["response"]["vectors_omitted"] = True
                    event["response"]["vectors_sha256"] = sha256_text(canonical_json(data))
                else:
                    event["response"] = dumped
                    output_text = getattr(response, "output_text", None)
                    if isinstance(event["response"], dict) and isinstance(output_text, str):
                        event["response"]["output_text"] = output_text
                return response

        return Endpoint()

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self._events)


class _AuditedOpenAIClient:
    def __init__(self, client: Any, audit: _ProviderAudit) -> None:
        self.embeddings = audit.endpoint(client.embeddings, "embedding")
        self.responses = audit.endpoint(client.responses, "generation")


def _load_openai_runtime(
    verified: VerifiedCore40,
    paths: Mapping[str, Path],
) -> RuntimeBundle:
    try:
        from dotenv import load_dotenv
        from openai import OpenAI
    except ImportError as error:
        raise RuntimeError("core40_openai_dependencies_missing") from error
    load_dotenv(verified.repo_root / ".env", override=False)
    if not os.environ.get("OPENAI_API_KEY") and os.environ.get("OPENAI_API_KEY_PRIVATE"):
        os.environ["OPENAI_API_KEY"] = os.environ["OPENAI_API_KEY_PRIVATE"]
    if not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("openai_api_key_missing")
    runtime = verified.config["runtime"]
    raw_client = OpenAI(max_retries=runtime["openai_max_retries"], timeout=120.0)
    audit = _ProviderAudit()
    client = _AuditedOpenAIClient(raw_client, audit)
    tokenizer_cache = _relative_path(
        verified.repo_root,
        verified.config["artifacts"]["tiktoken_cache_dir"],
    )
    pipeline = RagPipeline(
        index=verified.index,
        embedding_provider=OpenAIEmbeddingProvider(
            client=client,
            model=runtime["embedding_model"],
            dimensions=runtime["embedding_dimensions"],
            api_profile=runtime["api_profile"],
        ),
        embedding_counter=TiktokenCounter(
            runtime["embedding_model"], cache_dir=tokenizer_cache
        ),
        query_cache=EmbeddingCache(paths["query_cache"]),
        generator=OpenAIGenerator(
            client=client,
            model=runtime["generator_model"],
            max_output_tokens=runtime["max_output_tokens"],
            max_citations=runtime["max_citations"],
            reasoning_effort=runtime["reasoning_effort"],
        ),
        generation_counter=TiktokenCounter(
            runtime["generator_model"], cache_dir=tokenizer_cache
        ),
        budget=BudgetLedger(
            paths["budget_ledger"], limit_usd=runtime["budget_limit_usd"]
        ),
        corpus_manifest_sha256=verified.config["artifacts"]["manifest_sha256"],
        stack_id="api",
        observer=NoopObserver(),
        retrieval_top_k=runtime["retrieval_top_k"],
        context_top_k=runtime["context_top_k"],
    )
    return RuntimeBundle(
        pipeline=pipeline,
        audit=audit,
        index_config_sha256=verified.index_metadata["index_config_sha256"],
    )


def _result_dict(result: Any) -> dict[str, Any]:
    return {
        "response": copy.deepcopy(result.response),
        "retrieval": copy.deepcopy(result.retrieval),
        "timing_ms": copy.deepcopy(result.timing_ms),
        "usage": copy.deepcopy(result.usage),
        "cache_hit": bool(result.cache_hit),
    }


def _selected_context(
    verified: VerifiedCore40,
    result: Mapping[str, Any],
) -> tuple[list[IndexSearchHit], list[dict[str, Any]]]:
    hits: list[IndexSearchHit] = []
    for row in result["retrieval"]:
        chunk = verified.chunk_by_id.get(row.get("chunk_id"))
        if chunk is None:
            raise ValueError("core40_retrieval_chunk_missing")
        hits.append(
            IndexSearchHit(
                row_id=-1,
                score=float(row["score"]),
                chunk=chunk,
            )
        )
    selected = _select_context_hits(
        hits,
        context_top_k=verified.config["runtime"]["context_top_k"],
        table_context_cap=None,
    )
    source_rows = []
    for rank, hit in enumerate(selected, start=1):
        chunk = hit.chunk
        source_rows.append(
            {
                "context_rank": rank,
                "retrieval_rank": next(
                    row["rank"]
                    for row in result["retrieval"]
                    if row["chunk_id"] == chunk["chunk_id"]
                ),
                "score": hit.score,
                "doc_id": chunk["doc_id"],
                "chunk_id": chunk["chunk_id"],
                "source_block_ids": list(chunk["source_block_ids"]),
                "section_path": list(chunk["section_path"]),
                "page_start": chunk["page_start"],
                "page_end": chunk["page_end"],
                "content_sha256": chunk["content_sha256"],
                "source_text": chunk["text"],
            }
        )
    return selected, source_rows


def build_chat_transcript(
    verified: VerifiedCore40,
    case: Mapping[str, Any],
    request: Mapping[str, Any],
    result: Mapping[str, Any],
    provider_exchange: Mapping[str, Any],
) -> dict[str, Any]:
    selected_hits, selected_sources = _selected_context(verified, result)
    generation = provider_exchange.get("generation")
    expected_prompt = _build_prompt(dict(request), selected_hits) if selected_hits else None
    actual_prompt = None
    if isinstance(generation, Mapping):
        arguments = generation.get("request_arguments")
        if isinstance(arguments, Mapping):
            actual_prompt = arguments.get("input")
    if selected_hits and actual_prompt != expected_prompt:
        raise ValueError("core40_runtime_prompt_capture_mismatch")
    if not selected_hits and generation is not None:
        raise ValueError("core40_unexpected_generation_without_context")

    embedding = provider_exchange.get("embedding")
    retrieval_query = None
    if isinstance(embedding, Mapping):
        arguments = embedding.get("request_arguments")
        if isinstance(arguments, Mapping):
            inputs = arguments.get("input")
            if isinstance(inputs, list) and len(inputs) == 1 and isinstance(inputs[0], str):
                retrieval_query = inputs[0]
    if retrieval_query is None and result.get("cache_hit") is True:
        tokenizer_cache = _relative_path(
            verified.repo_root,
            verified.config["artifacts"]["tiktoken_cache_dir"],
        )
        retrieval_query = _retrieval_query(
            dict(request),
            TiktokenCounter(
                verified.config["runtime"]["embedding_model"],
                cache_dir=tokenizer_cache,
            ),
            max_tokens=8191,
        )
    if selected_hits and not isinstance(retrieval_query, str):
        raise ValueError("core40_retrieval_query_capture_missing")

    structured_plan = None
    provider_response = generation.get("response") if isinstance(generation, Mapping) else None
    if isinstance(provider_response, Mapping):
        output_text = provider_response.get("output_text")
        if isinstance(output_text, str):
            try:
                envelope = json.loads(output_text)
            except json.JSONDecodeError:
                envelope = None
            if isinstance(envelope, dict):
                structured_plan = envelope.get("result")
    transcript = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "core40_runtime_chat_transcript",
        "capture_mode": "prospective_runtime_exact",
        "baseline_id": BASELINE_ID,
        "case_id": case["case_id"],
        "eval_set_sha256": verified.eval_set_sha256,
        "config_sha256": verified.config_sha256,
        "request": copy.deepcopy(dict(request)),
        "retrieval_query": retrieval_query,
        "retrieval": copy.deepcopy(result["retrieval"]),
        "selected_context": selected_sources,
        "generation_prompt": expected_prompt,
        "provider_exchange": copy.deepcopy(dict(provider_exchange)),
        "assistant": {
            "structured_plan": structured_plan,
            "final_response": copy.deepcopy(result["response"]),
        },
        "timing_ms": copy.deepcopy(result["timing_ms"]),
        "usage": copy.deepcopy(result["usage"]),
        "cache_hit": result["cache_hit"],
        "runtime_error": copy.deepcopy(result["response"].get("error")),
    }
    transcript["integrity"] = {
        "request_sha256": sha256_text(canonical_json(transcript["request"])),
        "retrieval_query_sha256": (
            sha256_text(retrieval_query) if isinstance(retrieval_query, str) else None
        ),
        "selected_context_sha256": sha256_text(canonical_json(selected_sources)),
        "generation_prompt_sha256": (
            sha256_text(expected_prompt) if isinstance(expected_prompt, str) else None
        ),
        "provider_exchange_sha256": sha256_text(
            canonical_json(transcript["provider_exchange"])
        ),
        "final_response_sha256": sha256_text(
            canonical_json(transcript["assistant"]["final_response"])
        ),
    }
    return transcript


def _run_record(
    verified: VerifiedCore40,
    case: Mapping[str, Any],
    result: Any,
) -> dict[str, Any]:
    run_material = f"{case['case_id']}:{verified.config_sha256}"
    context = {
        "run_id": f"run_{sha256_text(run_material)[:24]}",
        "case_id": case["case_id"],
        "eval_set_sha256": verified.eval_set_sha256,
        "config_sha256": verified.config_sha256,
        "git_commit": verified.config["runtime"]["git_commit"],
        "environment": _environment(verified),
    }
    return build_api_run_record(
        result,
        context=context,
        corpus_manifest_sha256=verified.config["artifacts"]["manifest_sha256"],
        generator_model=verified.config["runtime"]["generator_model"],
        embedding_model=verified.config["runtime"]["embedding_model"],
        seed=None,
        temperature=None,
        api_profile=verified.config["runtime"]["api_profile"],
        embedding_dimensions=verified.config["runtime"]["embedding_dimensions"],
        index_config_sha256=verified.index_metadata["index_config_sha256"],
        reasoning_effort=verified.config["runtime"]["reasoning_effort"],
    )


def _runtime_contract_amendment(
    completed: Mapping[str, Mapping[str, Any]],
    *,
    current_identity: Mapping[str, Any],
    ledger_reserved_usd: Decimal,
) -> dict[str, Any] | None:
    recovered = [
        payload
        for payload in completed.values()
        if payload.get("recovery") is not None
    ]
    if not recovered:
        return None
    authorized = _authorized_recovery_reservations(completed)
    if len(authorized) != len(recovered):
        raise ValueError("core40_runtime_amendment_recovery_count_mismatch")
    reserved_uncertain = sum(
        (item["reserved_usd"] for item in authorized.values()),
        Decimal("0"),
    ).quantize(Decimal("0.000000001"))
    if ledger_reserved_usd != reserved_uncertain:
        raise ValueError("core40_runtime_amendment_budget_mismatch")

    target_runtime = current_identity.get("runtime_contract_sha256")
    if not isinstance(target_runtime, str) or SHA256_RE.fullmatch(target_runtime) is None:
        raise ValueError("core40_runtime_amendment_target_invalid")
    source_runtimes: set[str] = set()
    recovery_hashes: list[str] = []
    for payload in recovered:
        migration = payload.get("identity_migration")
        if migration is not None:
            if (
                not isinstance(migration, Mapping)
                or migration.get("mode") != INTERRUPTED_ERROR_RECOVERY_MODE
                or migration.get("provider_calls_performed") != 0
                or migration.get("to_runtime_contract_sha256") != target_runtime
                or not isinstance(
                    migration.get("from_runtime_contract_sha256"), str
                )
                or SHA256_RE.fullmatch(
                    migration["from_runtime_contract_sha256"]
                )
                is None
            ):
                raise ValueError("core40_runtime_amendment_migration_invalid")
            source_runtimes.add(migration["from_runtime_contract_sha256"])
        recovery_hashes.append(
            sha256_text(canonical_json(payload["recovery"]))
        )
    if len(source_runtimes) > 1:
        raise ValueError("core40_runtime_amendment_source_ambiguous")
    source_runtime = next(iter(source_runtimes), target_runtime)
    recovery_audit_sha256 = sha256_text(
        canonical_json(
            {
                "recovery_code_amendment_id": RUNTIME_CONTRACT_AMENDMENT_ID,
                "recovery_audit_sha256s": sorted(recovery_hashes),
            }
        )
    )
    return {
        "recovery_code_amendment_id": RUNTIME_CONTRACT_AMENDMENT_ID,
        "source_runtime_contract_sha256": source_runtime,
        "target_runtime_contract_sha256": target_runtime,
        "failed_case_count": len(recovered),
        "failed_cases_retried": False,
        "provider_attempts_preserved": True,
        "provider_retries": 0,
        "recovery_audit_count": len(recovery_hashes),
        "recovery_audit_sha256": recovery_audit_sha256,
        "reserved_uncertain_usd": float(reserved_uncertain),
    }


def _materialize(
    verified: VerifiedCore40,
    paths: Mapping[str, Path],
    completed: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    ordered = [completed[case["case_id"]] for case in verified.cases if case["case_id"] in completed]
    run_records = [row["run_record"] for row in ordered]
    transcripts = [row["chat_transcript"] for row in ordered]
    _write_private_jsonl(paths["run_records"], run_records)
    _write_private_jsonl(paths["chat_transcripts"], transcripts)
    metrics = _provisional_metrics(
        verified.cases,
        ordered,
        context_top_k=verified.config["runtime"]["context_top_k"],
    )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "core40_provisional_summary",
        "baseline_id": BASELINE_ID,
        "evaluation_tier": "provisional",
        "official_gold_ready": False,
        "config_sha256": verified.config_sha256,
        "eval_set_sha256": verified.eval_set_sha256,
        "counts": {
            "total": len(verified.cases),
            "completed": len(ordered),
            "remaining": len(verified.cases) - len(ordered),
        },
        "metrics": metrics,
        "warnings": [
            "The 40 cases are draft review candidates, so this result is provisional.",
            "Answer correctness and faithfulness remain unjudged until named human review.",
        ],
    }
    _write_private_json(paths["private_summary"], summary)
    ledger = BudgetLedger(
        paths["budget_ledger"],
        limit_usd=verified.config["runtime"]["budget_limit_usd"],
    ).snapshot()
    amendment = _runtime_contract_amendment(
        completed,
        current_identity=_checkpoint_identity(verified),
        ledger_reserved_usd=ledger.reserved_usd,
    )
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "baseline_id": BASELINE_ID,
        "evaluation_tier": "provisional",
        "official_gold_ready": False,
        "passed": len(ordered) == len(verified.cases) and not ledger.breached,
        "config_sha256": verified.config_sha256,
        "eval_set_sha256": verified.eval_set_sha256,
        "counts": summary["counts"],
        "provider_budget": {
            "limit_usd": float(ledger.limit_usd),
            "committed_usd": float(ledger.committed_usd),
            "reserved_usd": float(ledger.reserved_usd),
            "breached": ledger.breached,
        },
        "aggregate_metrics": metrics,
        "artifact_sha256s": {
            "run_records": sha256_file(paths["run_records"]),
            "chat_transcripts": sha256_file(paths["chat_transcripts"]),
            "private_summary": sha256_file(paths["private_summary"]),
        },
        "private_artifact_contents_exposed": False,
    }
    if amendment is not None:
        receipt["runtime_contract_amendment"] = amendment
    write_json(paths["receipt"], receipt)
    return receipt


def _migrate_checkpoint_identity(
    payload: Mapping[str, Any],
    *,
    current_identity: Mapping[str, Any],
) -> dict[str, Any]:
    migrated = copy.deepcopy(dict(payload))
    previous_identity = migrated.get("identity")
    if previous_identity == current_identity:
        return migrated
    if not _recovery_identity_is_compatible(previous_identity, current_identity):
        raise ValueError("core40_recovery_identity_mismatch")
    migrated["identity"] = copy.deepcopy(dict(current_identity))
    migrated["identity_migration"] = {
        "mode": INTERRUPTED_ERROR_RECOVERY_MODE,
        "from_runtime_contract_sha256": previous_identity[
            "runtime_contract_sha256"
        ],
        "to_runtime_contract_sha256": current_identity[
            "runtime_contract_sha256"
        ],
        "provider_calls_performed": 0,
    }
    return migrated


def recover_interrupted_as_error(
    verified: VerifiedCore40,
    *,
    case_id: str,
    counter_factory: RecoveryCounterFactory = _recovery_counter,
) -> dict[str, Any]:
    """Resolve one connection-interrupted case without any provider request.

    The operation is deliberately separate from live execution.  It accepts
    only an integrity-bound APIConnectionError checkpoint, rebuilds retrieval
    from the already-written query cache and frozen local index, and requires
    the rebuilt prompt to equal the captured provider request byte-for-byte.
    """

    if not isinstance(case_id, str) or not case_id:
        raise ValueError("core40_recovery_case_id_invalid")
    cases_by_id = {case["case_id"]: case for case in verified.cases}
    case = cases_by_id.get(case_id)
    if case is None:
        raise ValueError("core40_recovery_case_unknown")
    paths = _runtime_paths(verified)
    with _exclusive_run_lock(paths["run_lock"]):
        if not paths["run_state"].is_file():
            raise ValueError("core40_recovery_run_state_missing")
        current_identity = _checkpoint_identity(verified)
        run_state = _load_object(paths["run_state"], "core40_run_state_invalid")
        if not _recovery_identity_is_compatible(run_state, current_identity):
            raise ValueError("core40_recovery_run_state_identity_mismatch")

        known = set(cases_by_id)
        checkpoint_payloads: dict[str, dict[str, Any]] = {}
        for checkpoint_path in paths["checkpoints"].glob("*.json"):
            payload = _read_checkpoint_payload(checkpoint_path)
            checkpoint_case_id = payload.get("case_id")
            if (
                not isinstance(checkpoint_case_id, str)
                or checkpoint_case_id not in known
                or checkpoint_path != _checkpoint_path(paths, checkpoint_case_id)
            ):
                raise ValueError("core40_checkpoint_unknown_case")
            if not _recovery_identity_is_compatible(
                payload.get("identity"), current_identity
            ):
                raise ValueError("core40_recovery_identity_mismatch")
            state = payload.get("state")
            if state == "completed":
                _validate_completed_checkpoint(
                    payload,
                    case_id=checkpoint_case_id,
                    expected_identity=payload["identity"],
                )
            elif state == "interrupted" and checkpoint_case_id == case_id:
                pass
            elif state == "started":
                raise ValueError("core40_started_case_requires_budget_audit")
            elif state == "interrupted":
                raise ValueError("core40_recovery_multiple_interrupted_cases")
            else:
                raise ValueError("core40_checkpoint_invalid")
            checkpoint_payloads[checkpoint_case_id] = payload

        target_payload = checkpoint_payloads.get(case_id)
        if target_payload is None:
            raise ValueError("core40_recovery_checkpoint_missing")
        authorized_reservations = _authorized_recovery_reservations(
            checkpoint_payloads
        )
        original_payload_sha256 = sha256_text(canonical_json(target_payload))

        if target_payload.get("state") == "interrupted":
            context = _recoverable_interrupted_context(
                verified,
                paths,
                case,
                target_payload,
                counter_factory=counter_factory,
            )
            budget_provenance = _ensure_recovery_budget_reservation(
                verified,
                paths,
                case_id=case_id,
                generation_prompt=context["generation_prompt"],
                cost_upper=context["generation_cost_upper"],
                authorized_reservations=authorized_reservations,
            )
            trace_id = f"recovery-{sha256_text(f'{case_id}:{original_payload_sha256}')[:24]}"
            response = {
                "schema_version": SCHEMA_VERSION,
                "request_id": context["request"]["request_id"],
                "status": "error",
                "answer": "",
                "citations": [],
                "abstention": None,
                "error": {
                    "code": "provider_call_interrupted",
                    "message": "생성 API 연결 오류로 답변을 완료하지 못했습니다.",
                },
                "trace_id": trace_id,
            }
            total_cost = (
                context["embedding_cost"] + context["generation_cost_upper"]
            ).quantize(Decimal("0.000000001"))
            result_object = PipelineResult(
                response=response,
                retrieval=context["retrieval"],
                timing_ms={"retrieval": None, "generation": None, "total": 0.0},
                usage={
                    "input_tokens": context["generation_input_upper"],
                    "output_tokens": context["generation_output_upper"],
                    "embedding_tokens": context["embedding_tokens"],
                    "cost_usd": float(total_cost),
                    "gpu_seconds": None,
                    "peak_vram_gb": None,
                },
                cache_hit=True,
            )
            result = _result_dict(result_object)
            transcript = build_chat_transcript(
                verified,
                case,
                context["request"],
                result,
                context["provider_exchange"],
            )
            recovery_provenance = {
                "mode": INTERRUPTED_ERROR_RECOVERY_MODE,
                "provider_calls_performed": 0,
                "original_checkpoint_payload_sha256": original_payload_sha256,
                "original_provider_exchange_sha256": sha256_text(
                    canonical_json(context["provider_exchange"])
                ),
                "retrieval_reconstruction": {
                    "source": "existing_query_cache_and_frozen_local_index",
                    "query_cache_key_sha256": context["query_cache_key_sha256"],
                    "generation_prompt_sha256": sha256_text(
                        context["generation_prompt"]
                    ),
                    "prompt_match": True,
                },
                "budget": budget_provenance,
                "manual_audit_resolution": (
                    "captured_connection_error_recorded_without_provider_retry"
                ),
            }
            transcript["capture_mode"] = "prospective_runtime_with_offline_recovery"
            transcript["recovery"] = copy.deepcopy(recovery_provenance)
            run_record = _run_record(verified, case, result_object)
            recovered_payload = _completed_payload(
                verified,
                case_id,
                result,
                run_record,
                transcript,
            )
            recovered_payload["recovery"] = copy.deepcopy(recovery_provenance)
            if target_payload.get("identity") != current_identity:
                recovered_payload["identity_migration"] = {
                    "mode": INTERRUPTED_ERROR_RECOVERY_MODE,
                    "from_runtime_contract_sha256": target_payload["identity"][
                        "runtime_contract_sha256"
                    ],
                    "to_runtime_contract_sha256": current_identity[
                        "runtime_contract_sha256"
                    ],
                    "provider_calls_performed": 0,
                }
            checkpoint_payloads[case_id] = recovered_payload
        else:
            recovery_provenance = target_payload.get("recovery")
            if (
                not isinstance(recovery_provenance, Mapping)
                or recovery_provenance.get("mode")
                != INTERRUPTED_ERROR_RECOVERY_MODE
                or recovery_provenance.get("provider_calls_performed") != 0
            ):
                raise ValueError("core40_recovery_already_completed_without_provenance")
            budget = recovery_provenance.get("budget")
            reconstruction = recovery_provenance.get("retrieval_reconstruction")
            if not isinstance(budget, Mapping) or not isinstance(
                reconstruction, Mapping
            ):
                raise ValueError("core40_recovery_provenance_invalid")
            try:
                generation_cost_upper = Decimal(
                    str(budget["generation_cost_upper_usd"])
                )
            except Exception as error:
                raise ValueError("core40_recovery_provenance_invalid") from error
            transcript = target_payload["chat_transcript"]
            generation_prompt = transcript.get("generation_prompt")
            if not isinstance(generation_prompt, str) or sha256_text(
                generation_prompt
            ) != reconstruction.get("generation_prompt_sha256"):
                raise ValueError("core40_recovery_provenance_invalid")
            _ensure_recovery_budget_reservation(
                verified,
                paths,
                case_id=case_id,
                generation_prompt=generation_prompt,
                cost_upper=generation_cost_upper,
                authorized_reservations=authorized_reservations,
            )

        for checkpoint_case_id, payload in checkpoint_payloads.items():
            migrated = _migrate_checkpoint_identity(
                payload,
                current_identity=current_identity,
            )
            _write_private_json(
                _checkpoint_path(paths, checkpoint_case_id),
                _envelope(migrated),
            )
        _write_private_json(paths["run_state"], current_identity)

        completed = _completed_cases(verified, paths)
        partial_receipt = _materialize(verified, paths, completed)
        target = completed[case_id]
        audit = {
            "schema_version": SCHEMA_VERSION,
            "artifact_type": "core40_manual_recovery_audit",
            "baseline_id": BASELINE_ID,
            "mode": INTERRUPTED_ERROR_RECOVERY_MODE,
            "case_id": case_id,
            "provider_calls_performed": 0,
            "candidate_status": target["result"]["response"]["status"],
            "recovery": copy.deepcopy(target["recovery"]),
            "source_runtime_contract_sha256": run_state[
                "runtime_contract_sha256"
            ],
            "current_runtime_contract_sha256": current_identity[
                "runtime_contract_sha256"
            ],
            "completed_checkpoint_sha256": sha256_text(
                canonical_json(target)
            ),
            "partial_receipt_sha256": sha256_file(paths["receipt"]),
        }
        _write_private_json(paths["recovery_audit"], audit)
        ledger = BudgetLedger(
            paths["budget_ledger"],
            limit_usd=verified.config["runtime"]["budget_limit_usd"],
        ).snapshot()
        return {
            "schema_version": SCHEMA_VERSION,
            "passed": True,
            "baseline_id": BASELINE_ID,
            "action": INTERRUPTED_ERROR_RECOVERY_MODE,
            "case_id": case_id,
            "candidate_status": "error",
            "provider_calls_performed": 0,
            "counts": partial_receipt["counts"],
            "provider_budget": {
                "limit_usd": float(ledger.limit_usd),
                "committed_usd": float(ledger.committed_usd),
                "reserved_usd": float(ledger.reserved_usd),
                "available_usd": float(ledger.available_usd),
                "breached": ledger.breached,
            },
            "recovery_audit_sha256": sha256_file(paths["recovery_audit"]),
        }


def run_openai_baseline(
    verified: VerifiedCore40,
    *,
    approve_openai_egress: bool,
    runtime_factory: RuntimeFactory = _load_openai_runtime,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    if approve_openai_egress is not True:
        raise ValueError("core40_openai_egress_not_approved")
    paths = _runtime_paths(verified)
    with _exclusive_run_lock(paths["run_lock"]):
        _initialize_run_state(verified, paths)
        completed = _completed_cases(verified, paths)
        if len(completed) == len(verified.cases):
            return _materialize(verified, paths, completed)
        runtime = runtime_factory(verified, paths)
        if runtime.index_config_sha256 != verified.index_metadata["index_config_sha256"]:
            raise ValueError("core40_runtime_index_config_mismatch")
        interval = verified.config["runtime"]["case_interval_seconds"]
        try:
            for case in verified.cases:
                case_id = case["case_id"]
                if case_id in completed:
                    continue
                checkpoint = _checkpoint_path(paths, case_id)
                if checkpoint.exists():
                    _load_checkpoint(checkpoint, verified, case_id)
                    raise ValueError("core40_checkpoint_state_invalid")
                _write_private_json(checkpoint, _envelope(_started_payload(verified, case_id)))
                runtime.audit.reset()
                request = build_request(
                    case,
                    config_sha256=verified.config_sha256,
                    max_citations=verified.config["runtime"]["max_citations"],
                )
                try:
                    result_object = runtime.pipeline.query(
                        request,
                        trace_context={
                            "run_id": BASELINE_ID,
                            "case_id": case_id,
                            "eval_set_sha256": verified.eval_set_sha256,
                            "config_sha256": verified.config_sha256,
                            "api_profile": verified.config["runtime"]["api_profile"],
                            "index_config_sha256": runtime.index_config_sha256,
                        },
                    )
                except Exception as error:
                    provider_exchange = runtime.audit.snapshot()
                    _write_private_json(
                        checkpoint,
                        _envelope(
                            _interrupted_payload(
                                verified,
                                case_id,
                                request,
                                provider_exchange,
                                error,
                            )
                        ),
                    )
                    raise
                provider_exchange = runtime.audit.snapshot()
                if _provider_exchange_requires_budget_audit(provider_exchange):
                    uncertainty = ValueError(
                        "core40_provider_call_requires_budget_audit"
                    )
                    _write_private_json(
                        checkpoint,
                        _envelope(
                            _interrupted_payload(
                                verified,
                                case_id,
                                request,
                                provider_exchange,
                                uncertainty,
                            )
                        ),
                    )
                    raise uncertainty
                result = _result_dict(result_object)
                if _candidate_error_requires_budget_audit(
                    result,
                    provider_exchange,
                ):
                    uncertainty = ValueError(
                        "core40_provider_call_requires_budget_audit"
                    )
                    _write_private_json(
                        checkpoint,
                        _envelope(
                            _interrupted_payload(
                                verified,
                                case_id,
                                request,
                                provider_exchange,
                                uncertainty,
                            )
                        ),
                    )
                    raise uncertainty
                transcript = build_chat_transcript(
                    verified,
                    case,
                    request,
                    result,
                    provider_exchange,
                )
                run_record = _run_record(verified, case, result_object)
                payload = _completed_payload(
                    verified,
                    case_id,
                    result,
                    run_record,
                    transcript,
                )
                _write_private_json(checkpoint, _envelope(payload))
                completed[case_id] = payload
                _materialize(verified, paths, completed)
                print(
                    canonical_json(
                        {
                            "event": "case_completed",
                            "baseline_id": BASELINE_ID,
                            "completed": len(completed),
                            "total": len(verified.cases),
                            "case_id": case_id,
                            "status": result["response"]["status"],
                        }
                    ),
                    file=sys.stderr,
                    flush=True,
                )
                if len(completed) < len(verified.cases) and interval > 0:
                    sleeper(interval)
        finally:
            runtime.pipeline.flush_observability()
        if len(completed) != len(verified.cases):
            raise ValueError("core40_run_incomplete")
        return _materialize(verified, paths, completed)


def _error_code(error: BaseException, fallback: str) -> str:
    value = str(error)
    return value if re.fullmatch(r"^[a-z][a-z0-9_]{0,63}$", value) else fallback


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m midprojectrag.core40_baseline")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(f"evaluation/baselines/{BASELINE_ID}/config.json"),
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--write-preflight-receipt", action="store_true")
    actions.add_argument("--run-openai", action="store_true")
    actions.add_argument(
        "--recover-interrupted-as-error",
        metavar="CASE_ID",
        help=(
            "validate and record one interrupted APIConnectionError as an error "
            "without a provider retry"
        ),
    )
    parser.add_argument("--approve-openai-egress", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        verified = verify_baseline(args.config)
        if args.recover_interrupted_as_error:
            if args.approve_openai_egress:
                raise ValueError("core40_recovery_egress_flag_forbidden")
            result = recover_interrupted_as_error(
                verified,
                case_id=args.recover_interrupted_as_error,
            )
        elif args.run_openai:
            if not args.approve_openai_egress:
                raise ValueError("core40_openai_egress_not_approved")
            result = run_openai_baseline(
                verified,
                approve_openai_egress=True,
            )
        else:
            result = (
                write_preflight_receipt(verified)
                if args.write_preflight_receipt
                else preflight_report(verified)
            )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("passed") else 8
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {"passed": False, "error_code": _error_code(error, "core40_baseline_failed")},
                sort_keys=True,
            )
        )
        return 8
    except Exception:
        print(json.dumps({"passed": False, "error_code": "core40_baseline_failed"}, sort_keys=True))
        return 8


if __name__ == "__main__":
    raise SystemExit(main())
