"""Control plane for the frozen supplemental provisional baseline.

Preflight and scoring are offline. Provider execution is a separate, fail-closed
action that requires explicit approval for sending private golden questions and
retrieved RFP excerpts to OpenAI. Questions, answers and per-case reports remain
in ignored private paths; the public receipt contains aggregate values and hashes.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from midprojectrag.answering.generation import SYSTEM_INSTRUCTIONS
from midprojectrag.answering.pipeline import _build_prompt, _select_context_hits
from midprojectrag.indexing.exact_index import ExactDenseIndex
from midprojectrag.ingest.common import (
    canonical_json,
    read_jsonl,
    sha256_bytes,
    sha256_file,
    sha256_text,
    write_jsonl as write_runtime_jsonl,
)
from midprojectrag.indexing.embeddings import EmbeddingCache
from midprojectrag.stacks.api.config import api_config_sha256
from midprojectrag.stacks.api.generation import build_openai_answer_plan_schema
from midprojectrag.supplemental_evaluation import (
    dataset_sha256,
    score_answer_cases,
    score_set_cases,
    validate_supplemental_cases,
    write_json,
)


SCHEMA_VERSION = "1.0"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CONFIG_FIELDS = {
    "schema_version", "baseline_id", "evaluation_tier", "expected_counts",
    "artifacts", "runtime", "execution_contract", "outputs",
}
ARTIFACT_FIELDS = {
    "answer_cases", "answer_cases_sha256", "set_cases", "set_cases_sha256",
    "manifest", "manifest_sha256", "chunks", "chunks_sha256", "index_dir",
    "index_metadata_sha256", "tiktoken_cache_dir",
}
RUNTIME_FIELDS = {
    "api_profile", "embedding_model", "embedding_dimensions", "generator_model",
    "retrieval_top_k", "context_top_k", "max_citations", "max_output_tokens",
    "reasoning_effort", "case_interval_seconds", "budget_limit_usd",
}
EXECUTION_CONTRACT = {
    "provider_execution": "explicit_approval_required",
    "external_destination": "OpenAI API",
    "external_payload_classes": ["golden_set_questions", "retrieved_rfp_excerpts"],
    "explicit_egress_approval_required": True,
    "resume_policy": {
        "unit": "case",
        "case_identity_field": "case_id",
        "checkpoint_manifest_identity_fields": [
            "answer_eval_set_sha256",
            "set_eval_set_sha256",
            "config_sha256",
        ],
        "checkpoint": "atomic_jsonl_after_each_case",
        "reject_mismatched_hashes": True,
    },
    "private_output_policy": {
        "run_records": "evaluation/private/",
        "per_case_metrics": "evaluation/private/",
        "tracked_receipts_must_exclude": ["questions", "answers", "source_text"],
    },
}
OUTPUT_FIELDS = {
    "answer_runs", "set_runs", "answer_metrics", "set_metrics",
    "preflight_receipt", "receipt",
}
CASE_MARKER_FIELDS = {
    "schema_version",
    "baseline_id",
    "lane",
    "case_id",
    "eval_set_sha256",
    "config_sha256",
    "budget_ledger_identity_sha256",
    "state",
    "run_record_sha256",
}


@dataclass(frozen=True)
class VerifiedBaseline:
    repo_root: Path
    config: dict[str, Any]
    config_sha256: str
    answer_cases: list[dict[str, Any]]
    set_cases: list[dict[str, Any]]
    known_doc_ids: set[str]
    chunk_count: int


def _repo_root(config_path: Path) -> Path:
    for candidate in (config_path.resolve().parent, *config_path.resolve().parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise ValueError("repository_root_not_found")


def _relative_path(repo_root: Path, value: Any, *, prefix: str | None = None) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError("baseline_path_must_be_relative")
    candidate = (repo_root / value).resolve()
    try:
        relative = candidate.relative_to(repo_root.resolve()).as_posix()
    except ValueError as error:
        raise ValueError("baseline_path_outside_repository") from error
    if prefix is not None and not relative.startswith(prefix):
        raise ValueError("baseline_path_prefix_invalid")
    return candidate


def _load_config(config_path: Path) -> tuple[Path, dict[str, Any], str]:
    repo_root = _repo_root(config_path)
    value = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != CONFIG_FIELDS:
        raise ValueError("baseline_config_contract_invalid")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("baseline_config_version_invalid")
    if value.get("baseline_id") != "supplemental-provisional-v1":
        raise ValueError("baseline_id_invalid")
    if value.get("evaluation_tier") != "provisional":
        raise ValueError("baseline_evaluation_tier_invalid")
    if value.get("expected_counts") != {"answer": 56, "set": 13, "total": 69}:
        raise ValueError("baseline_expected_counts_invalid")
    artifacts, runtime, outputs = value.get("artifacts"), value.get("runtime"), value.get("outputs")
    if not isinstance(artifacts, dict) or set(artifacts) != ARTIFACT_FIELDS:
        raise ValueError("baseline_artifacts_contract_invalid")
    if not isinstance(runtime, dict) or set(runtime) != RUNTIME_FIELDS:
        raise ValueError("baseline_runtime_contract_invalid")
    if not isinstance(outputs, dict) or set(outputs) != OUTPUT_FIELDS:
        raise ValueError("baseline_outputs_contract_invalid")
    if value.get("execution_contract") != EXECUTION_CONTRACT:
        raise ValueError("baseline_execution_contract_not_frozen")
    for field in ("answer_cases_sha256", "set_cases_sha256", "manifest_sha256", "chunks_sha256", "index_metadata_sha256"):
        if not isinstance(artifacts.get(field), str) or SHA256_RE.fullmatch(artifacts[field]) is None:
            raise ValueError("baseline_artifact_hash_invalid")
    frozen_runtime = {
        "api_profile": "personal_experimental",
        "embedding_model": "text-embedding-3-small",
        "embedding_dimensions": 1536,
        "generator_model": "gpt-5-mini",
        "retrieval_top_k": 10,
        "context_top_k": 5,
        "max_citations": 3,
        "max_output_tokens": 2000,
        "reasoning_effort": "minimal",
        "case_interval_seconds": 0.5,
        "budget_limit_usd": 2.0,
    }
    if runtime != frozen_runtime:
        raise ValueError("baseline_runtime_not_frozen")
    for field in ("answer_cases", "set_cases", "manifest", "chunks", "index_dir", "tiktoken_cache_dir"):
        _relative_path(repo_root, artifacts[field])
    for field in ("answer_runs", "set_runs", "answer_metrics", "set_metrics"):
        _relative_path(repo_root, outputs[field], prefix="evaluation/private/")
    for field in ("preflight_receipt", "receipt"):
        _relative_path(repo_root, outputs[field], prefix="evaluation/baselines/supplemental-provisional-v1/")
    return repo_root, value, sha256_file(config_path)


def _verify_hash(path: Path, expected: str, code: str) -> None:
    if not path.is_file() or sha256_file(path) != expected:
        raise ValueError(code)


def verify_baseline(config_path: Path) -> VerifiedBaseline:
    """Verify frozen inputs and the existing dense index without network access."""

    repo_root, config, config_sha256 = _load_config(config_path)
    artifacts = config["artifacts"]
    paths = {
        key: _relative_path(repo_root, artifacts[key])
        for key in ("answer_cases", "set_cases", "manifest", "chunks", "index_dir", "tiktoken_cache_dir")
    }
    _verify_hash(paths["answer_cases"], artifacts["answer_cases_sha256"], "answer_cases_hash_mismatch")
    _verify_hash(paths["set_cases"], artifacts["set_cases_sha256"], "set_cases_hash_mismatch")
    _verify_hash(paths["manifest"], artifacts["manifest_sha256"], "manifest_hash_mismatch")
    _verify_hash(paths["chunks"], artifacts["chunks_sha256"], "chunks_hash_mismatch")
    _verify_hash(paths["index_dir"] / "metadata.json", artifacts["index_metadata_sha256"], "index_metadata_hash_mismatch")
    if not paths["tiktoken_cache_dir"].is_dir():
        raise ValueError("tiktoken_cache_missing")
    answer_cases = read_jsonl(paths["answer_cases"])
    set_cases = read_jsonl(paths["set_cases"])
    if len(answer_cases) != 56 or len(set_cases) != 13:
        raise ValueError("supplemental_case_count_mismatch")
    if dataset_sha256(answer_cases) != artifacts["answer_cases_sha256"]:
        raise ValueError("answer_cases_dataset_hash_mismatch")
    if dataset_sha256(set_cases) != artifacts["set_cases_sha256"]:
        raise ValueError("set_cases_dataset_hash_mismatch")
    if validate_supplemental_cases(answer_cases, set_cases, require_approved=False):
        raise ValueError("supplemental_provisional_contract_invalid")
    manifest_rows = read_jsonl(paths["manifest"])
    known_doc_ids = {row["doc_id"] for row in manifest_rows if isinstance(row.get("doc_id"), str)}
    if len(manifest_rows) != 98 or len(known_doc_ids) != 98:
        raise ValueError("refined_manifest_count_mismatch")
    chunks = read_jsonl(paths["chunks"])
    metadata = json.loads((paths["index_dir"] / "metadata.json").read_text(encoding="utf-8"))
    runtime = config["runtime"]
    if metadata.get("corpus_manifest_sha256") != artifacts["manifest_sha256"] or metadata.get("chunk_artifact_sha256") != artifacts["chunks_sha256"]:
        raise ValueError("index_corpus_binding_mismatch")
    # Preflight is deliberately read-only. The public ``load`` method takes an
    # advisory lock by opening ``.index.lock`` for append, which would mutate
    # filesystem metadata. Use the same verified loader without that lock.
    ExactDenseIndex._load_unlocked(
        paths["index_dir"], chunks,
        expected_embedding_model=runtime["embedding_model"],
        expected_dimensions=runtime["embedding_dimensions"],
        expected_api_profile=runtime["api_profile"],
        expected_index_config_sha256=metadata.get("index_config_sha256"),
    )
    return VerifiedBaseline(repo_root, config, config_sha256, answer_cases, set_cases, known_doc_ids, len(chunks))


def preflight_report(verified: VerifiedBaseline) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "passed": True,
        "baseline_id": verified.config["baseline_id"],
        "evaluation_tier": "provisional",
        "config_sha256": verified.config_sha256,
        "counts": {
            "answer_cases": len(verified.answer_cases),
            "set_cases": len(verified.set_cases),
            "total_cases": len(verified.answer_cases) + len(verified.set_cases),
            "documents": len(verified.known_doc_ids),
            "chunks": verified.chunk_count,
        },
        "provider_calls": 0,
        "private_corpus_egress": False,
        "execution_contract": verified.config["execution_contract"],
        "output_contract": {
            "private_run_records": True,
            "private_per_case_metrics": True,
            "public_aggregate_receipt": True,
        },
    }


def _metric_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "passed": report.get("passed"),
        "evaluation_tier": report.get("evaluation_tier"),
        "official_gold_ready": report.get("official_gold_ready"),
        "suite_complete": report.get("suite_complete"),
        "counts": report.get("counts"),
        "metric_coverage": report.get("metric_coverage"),
        "metrics": report.get("metrics"),
        "error_count": len(report.get("errors", [])),
    }


def _recorded_answer_cost(answer_runs: Sequence[Mapping[str, Any]]) -> Decimal:
    total = Decimal("0")
    for row in answer_runs:
        usage = row.get("usage")
        if not isinstance(usage, dict):
            raise ValueError("baseline_answer_cost_reconciliation_invalid")
        try:
            cost = Decimal(str(usage.get("cost_usd")))
        except (InvalidOperation, ValueError) as error:
            raise ValueError("baseline_answer_cost_reconciliation_invalid") from error
        if not cost.is_finite() or cost < 0:
            raise ValueError("baseline_answer_cost_reconciliation_invalid")
        total += cost
    return total


def _reconstruction_contract_sha256s(runtime: Mapping[str, Any]) -> dict[str, str]:
    provider_schema = build_openai_answer_plan_schema(runtime["max_citations"])
    return {
        "system_instructions": sha256_text(SYSTEM_INSTRUCTIONS),
        "transcript_export_module": sha256_file(Path(__file__)),
        "answering_pipeline_module": sha256_file(
            Path(_build_prompt.__code__.co_filename)
        ),
        "exact_dense_index_module": sha256_file(
            Path(ExactDenseIndex.search.__code__.co_filename)
        ),
        "provider_generation_module": sha256_file(
            Path(build_openai_answer_plan_schema.__code__.co_filename)
        ),
        "provider_response_schema": sha256_text(canonical_json(provider_schema)),
        "selection_runtime": sha256_text(
            canonical_json(
                {
                    "retrieval_top_k": runtime["retrieval_top_k"],
                    "context_top_k": runtime["context_top_k"],
                    "table_context_cap": None,
                }
            )
        ),
    }


def _attach_existing_transcript_receipt(
    verified: VerifiedBaseline,
    paths: Mapping[str, Path],
    receipt: dict[str, Any],
    answer_runs: Sequence[Mapping[str, Any]],
    set_runs: Sequence[Mapping[str, Any]],
) -> None:
    transcript_path = paths.get("chat_transcripts")
    if transcript_path is None or not transcript_path.is_file():
        return
    rows = read_jsonl(transcript_path)
    answer_hash = dataset_sha256(verified.answer_cases)
    set_hash = dataset_sha256(verified.set_cases)
    expected_cases = {
        **{("answer", case["case_id"]): case for case in verified.answer_cases},
        **{("set", case["case_id"]): case for case in verified.set_cases},
    }
    expected_runs = {
        **{("answer", row["case_id"]): row for row in answer_runs},
        **{("set", row["case_id"]): row for row in set_runs},
    }
    expected_source_hashes = {
        "answer_cases": answer_hash,
        "set_cases": set_hash,
        "answer_runs": dataset_sha256(answer_runs),
        "set_runs": dataset_sha256(set_runs),
        "manifest": verified.config["artifacts"]["manifest_sha256"],
        "chunks": verified.config["artifacts"]["chunks_sha256"],
        "index_metadata": verified.config["artifacts"][
            "index_metadata_sha256"
        ],
    }
    expected_contract_hashes = _reconstruction_contract_sha256s(
        verified.config["runtime"]
    )
    actual: set[tuple[str, str]] = set()
    exact_persisted_answers = 0
    for row in rows:
        lane, case_id = row.get("lane"), row.get("case_id")
        key = (lane, case_id)
        record_hash = row.get("record_sha256")
        unhashed = dict(row)
        unhashed.pop("record_sha256", None)
        expected_request = _request(
            expected_cases[key],
            max_citations=verified.config["runtime"]["max_citations"],
        )
        expected_assistant, expected_unavailable = (
            _assistant_transcript_projection(lane, expected_runs[key])
        )
        expected_execution = (
            {
                "timing_ms": expected_runs[key].get("timing_ms"),
                "usage": expected_runs[key].get("usage"),
                "cache_hit": expected_runs[key].get("cache_hit"),
            }
            if lane == "answer"
            else {"timing_ms": None, "usage": None, "cache_hit": None}
        )
        if (
            lane not in {"answer", "set"}
            or not isinstance(case_id, str)
            or key in actual
            or key not in expected_cases
            or key not in expected_runs
            or row.get("schema_version") != SCHEMA_VERSION
            or row.get("baseline_id") != verified.config["baseline_id"]
            or row.get("config_sha256") != verified.config_sha256
            or row.get("capture_mode") != "posthoc_reconstructed"
            or row.get("eval_set_sha256")
            != (answer_hash if lane == "answer" else set_hash)
            or row.get("source_artifact_sha256s") != expected_source_hashes
            or row.get("source_run_record_sha256")
            != sha256_text(canonical_json(expected_runs[key]))
            or row.get("reconstruction_contract_sha256s")
            != expected_contract_hashes
            or row.get("request") != expected_request
            or row.get("assistant") != expected_assistant
            or row.get("execution") != expected_execution
            or row.get("unavailable_fields")
            != sorted(set(expected_unavailable))
            or row.get("runtime_equivalence")
            != {
                "verification_level": "retrieved_doc_id_projection_only",
                "retrieved_chunk_ids": "runtime_unverified_not_persisted",
                "context_selection": "deterministic_replay_runtime_unverified",
                "provider_request": "reconstructed_not_runtime_captured",
            }
            or record_hash != sha256_text(canonical_json(unhashed))
        ):
            raise ValueError("baseline_transcript_artifact_invalid")
        vector, cache_key, retrieval_query = _cached_query_vector(
            verified, paths, expected_request
        )
        if (
            row.get("query_cache_key") != cache_key
            or row.get("retrieval_query") != retrieval_query
            or row.get("query_vector_sha256")
            != sha256_bytes(vector.tobytes(order="C"))
        ):
            raise ValueError("baseline_transcript_artifact_invalid")
        if (
            lane == "answer"
            and expected_runs[key].get("status") == "answered"
        ):
            exact_persisted_answers += 1
        actual.add(key)
    if actual != set(expected_cases):
        raise ValueError("baseline_transcript_artifact_invalid")
    receipt["artifact_sha256s"]["chat_transcripts"] = sha256_file(
        transcript_path
    )
    receipt["counts"]["chat_transcripts"] = len(rows)
    receipt["counts"]["chat_transcripts_posthoc_reconstructed"] = len(rows)
    receipt["counts"]["chat_transcripts_runtime_exact"] = 0
    receipt["counts"]["chat_transcripts_exact_persisted_answers"] = (
        exact_persisted_answers
    )
    receipt["counts"]["chat_transcripts_answers_unavailable_or_elided"] = (
        len(rows) - exact_persisted_answers
    )


def _score_existing_locked(
    verified: VerifiedBaseline, paths: Mapping[str, Path]
) -> dict[str, Any]:
    answer_runs, set_runs = _load_or_initialize_runs(
        verified, paths, initialize=False
    )
    manifest_hash = verified.config["artifacts"]["manifest_sha256"]
    answer_report = score_answer_cases(
        verified.answer_cases, answer_runs,
        known_doc_ids=verified.known_doc_ids,
        manifest_sha256=manifest_hash,
    )
    set_report = score_set_cases(
        verified.set_cases, set_runs,
        known_doc_ids=verified.known_doc_ids,
        manifest_sha256=manifest_hash,
    )
    write_json(paths["answer_metrics"], answer_report)
    write_json(paths["set_metrics"], set_report)
    budget_snapshot = _budget_snapshot(
        verified,
        paths,
        required=bool(answer_runs or set_runs),
        initialize=False,
    )
    if budget_snapshot is not None:
        if budget_snapshot.reserved_usd != Decimal("0"):
            raise ValueError("baseline_budget_reservations_pending")
        if budget_snapshot.committed_usd < _recorded_answer_cost(answer_runs):
            raise ValueError("baseline_budget_reconciliation_failed")
        if budget_snapshot.breached:
            raise ValueError("baseline_budget_breached")
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "baseline_id": verified.config["baseline_id"],
        "evaluation_tier": "provisional",
        "passed": bool(answer_report["passed"] and set_report["passed"]),
        "official_gold_ready": False,
        "config_sha256": verified.config_sha256,
        "artifact_sha256s": {
            "answer_cases": dataset_sha256(verified.answer_cases),
            "set_cases": dataset_sha256(verified.set_cases),
            "manifest": manifest_hash,
            "chunks": verified.config["artifacts"]["chunks_sha256"],
            "index_metadata": verified.config["artifacts"]["index_metadata_sha256"],
            "answer_runs": dataset_sha256(answer_runs),
            "set_runs": dataset_sha256(set_runs),
        },
        "counts": {"answer_cases": len(answer_runs), "set_cases": len(set_runs), "total_cases": len(answer_runs) + len(set_runs)},
        "runtime": dict(verified.config["runtime"]),
        "answer_score": _metric_summary(answer_report),
        "set_score": _metric_summary(set_report),
        "privacy": {"contains_questions": False, "contains_answers": False, "contains_source_text": False, "private_run_records_tracked": False},
    }
    if budget_snapshot is not None:
        receipt["provider_budget"] = {
            "limit_usd": float(budget_snapshot.limit_usd),
            "committed_usd": float(budget_snapshot.committed_usd),
            "reserved_usd": float(budget_snapshot.reserved_usd),
            "breached": budget_snapshot.breached,
        }
    _attach_existing_transcript_receipt(
        verified, paths, receipt, answer_runs, set_runs
    )
    write_json(paths["receipt"], receipt)
    return receipt


def score_existing(verified: VerifiedBaseline) -> dict[str, Any]:
    """Score local run records; never generates or transmits case content."""

    paths = _private_run_paths(verified)
    with _exclusive_run_lock(paths["run_lock"]):
        return _score_existing_locked(verified, paths)


@contextmanager
def _exclusive_run_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("baseline_run_already_locked") from error
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _private_run_paths(verified: VerifiedBaseline) -> dict[str, Path]:
    outputs = verified.config["outputs"]
    paths = {
        key: _relative_path(verified.repo_root, value)
        for key, value in outputs.items()
    }
    run_dir = paths["answer_runs"].parent
    if paths["set_runs"].parent != run_dir:
        raise ValueError("baseline_run_directory_mismatch")
    return {
        **paths,
        "checkpoint": run_dir / "run-state.json",
        "query_cache": run_dir / "query-cache",
        "budget_ledger": run_dir / "budget-ledger.json",
        "case_checkpoints": run_dir / "case-checkpoints",
        "run_lock": run_dir / ".run.lock",
        "chat_transcripts": run_dir / "chat-transcripts.jsonl",
    }


def _checkpoint_value(verified: VerifiedBaseline) -> dict[str, Any]:
    value = {
        "schema_version": SCHEMA_VERSION,
        "baseline_id": verified.config["baseline_id"],
        "config_sha256": verified.config_sha256,
        "answer_eval_set_sha256": dataset_sha256(verified.answer_cases),
        "set_eval_set_sha256": dataset_sha256(verified.set_cases),
    }
    value["budget_ledger_identity_sha256"] = sha256_text(
        canonical_json(
            {
                **value,
                "budget_limit_usd": verified.config["runtime"]["budget_limit_usd"],
            }
        )
    )
    return value


def _case_marker_path(
    paths: Mapping[str, Path], lane: str, case_id: str
) -> Path:
    identity = sha256_text(f"{lane}:{case_id}")
    return paths["case_checkpoints"] / f"{lane}-{identity}.json"


def _case_marker_value(
    verified: VerifiedBaseline,
    *,
    lane: str,
    case_id: str,
    state: str,
    run_record: Mapping[str, Any] | None,
) -> dict[str, Any]:
    checkpoint = _checkpoint_value(verified)
    return {
        "schema_version": SCHEMA_VERSION,
        "baseline_id": verified.config["baseline_id"],
        "lane": lane,
        "case_id": case_id,
        "eval_set_sha256": checkpoint[
            "answer_eval_set_sha256" if lane == "answer" else "set_eval_set_sha256"
        ],
        "config_sha256": verified.config_sha256,
        "budget_ledger_identity_sha256": checkpoint[
            "budget_ledger_identity_sha256"
        ],
        "state": state,
        "run_record_sha256": (
            sha256_text(canonical_json(run_record))
            if run_record is not None
            else None
        ),
    }


def _write_case_marker(
    verified: VerifiedBaseline,
    paths: Mapping[str, Path],
    *,
    lane: str,
    case_id: str,
    state: str,
    run_record: Mapping[str, Any] | None = None,
) -> None:
    if state not in {"started", "completed"} or (
        (state == "started") != (run_record is None)
    ):
        raise ValueError("baseline_case_marker_state_invalid")
    write_json(
        _case_marker_path(paths, lane, case_id),
        _case_marker_value(
            verified,
            lane=lane,
            case_id=case_id,
            state=state,
            run_record=run_record,
        ),
    )


def _initialize_budget_ledger(
    verified: VerifiedBaseline, paths: Mapping[str, Path]
) -> None:
    from midprojectrag.indexing.budget import BudgetLedger

    ledger_path = paths["budget_ledger"]
    BudgetLedger(
        ledger_path,
        limit_usd=verified.config["runtime"]["budget_limit_usd"],
    ).snapshot()
    state = json.loads(ledger_path.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise ValueError("baseline_budget_ledger_invalid")
    state["baseline_identity_sha256"] = _checkpoint_value(verified)[
        "budget_ledger_identity_sha256"
    ]
    write_json(ledger_path, state)


def _budget_snapshot(
    verified: VerifiedBaseline,
    paths: Mapping[str, Path],
    *,
    required: bool,
    initialize: bool,
) -> Any | None:
    from midprojectrag.indexing.budget import BudgetLedger

    ledger_path = paths["budget_ledger"]
    if not ledger_path.is_file():
        if required:
            raise ValueError("baseline_budget_ledger_missing")
        if not initialize:
            return None
        _initialize_budget_ledger(verified, paths)
    state = json.loads(ledger_path.read_text(encoding="utf-8"))
    if (
        not isinstance(state, dict)
        or state.get("baseline_identity_sha256")
        != _checkpoint_value(verified)["budget_ledger_identity_sha256"]
    ):
        raise ValueError("baseline_budget_ledger_identity_mismatch")
    return BudgetLedger(
        ledger_path,
        limit_usd=verified.config["runtime"]["budget_limit_usd"],
    ).snapshot()


def _validate_case_markers(
    verified: VerifiedBaseline,
    paths: Mapping[str, Path],
    answer_runs: Sequence[Mapping[str, Any]],
    set_runs: Sequence[Mapping[str, Any]],
) -> None:
    marker_dir = paths["case_checkpoints"]
    if marker_dir.exists() and not marker_dir.is_dir():
        raise ValueError("baseline_case_checkpoint_directory_invalid")
    run_by_key = {
        **{("answer", row["case_id"]): row for row in answer_runs},
        **{("set", row["case_id"]): row for row in set_runs},
    }
    case_ids = {
        "answer": {case["case_id"] for case in verified.answer_cases},
        "set": {case["case_id"] for case in verified.set_cases},
    }
    completed_keys: set[tuple[str, str]] = set()
    marker_paths = sorted(marker_dir.glob("*.json")) if marker_dir.is_dir() else []
    for marker_path in marker_paths:
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("baseline_case_checkpoint_invalid") from error
        if not isinstance(marker, dict) or set(marker) != CASE_MARKER_FIELDS:
            raise ValueError("baseline_case_checkpoint_invalid")
        lane = marker.get("lane")
        case_id = marker.get("case_id")
        if (
            lane not in {"answer", "set"}
            or not isinstance(case_id, str)
            or case_id not in case_ids[lane]
            or marker_path != _case_marker_path(paths, lane, case_id)
        ):
            raise ValueError("baseline_case_checkpoint_invalid")
        key = (lane, case_id)
        state = marker.get("state")
        if state == "started":
            if marker != _case_marker_value(
                verified,
                lane=lane,
                case_id=case_id,
                state="started",
                run_record=None,
            ):
                raise ValueError("baseline_case_checkpoint_invalid")
            raise ValueError("baseline_started_case_requires_budget_audit")
        run_record = run_by_key.get(key)
        if state != "completed" or run_record is None or marker != _case_marker_value(
            verified,
            lane=lane,
            case_id=case_id,
            state="completed",
            run_record=run_record,
        ):
            raise ValueError("baseline_case_checkpoint_invalid")
        completed_keys.add(key)
    if set(run_by_key) != completed_keys:
        raise ValueError("baseline_case_checkpoint_missing")


def _load_or_initialize_runs(
    verified: VerifiedBaseline,
    paths: Mapping[str, Path],
    *,
    initialize: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    checkpoint_path = paths["checkpoint"]
    expected_checkpoint = _checkpoint_value(verified)
    run_paths = (paths["answer_runs"], paths["set_runs"])
    existing_run_files = [path.exists() for path in run_paths]
    if checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint != expected_checkpoint:
            raise ValueError("baseline_checkpoint_identity_mismatch")
        if not all(existing_run_files):
            raise ValueError("baseline_run_file_missing")
    elif any(existing_run_files):
        raise ValueError("baseline_checkpoint_missing")
    elif not initialize:
        raise ValueError("baseline_checkpoint_missing")
    else:
        write_runtime_jsonl(paths["answer_runs"], [])
        write_runtime_jsonl(paths["set_runs"], [])
        paths["case_checkpoints"].mkdir(parents=True, exist_ok=True)
        _budget_snapshot(
            verified, paths, required=False, initialize=True
        )
        write_json(checkpoint_path, expected_checkpoint)

    answer_runs = read_jsonl(paths["answer_runs"])
    set_runs = read_jsonl(paths["set_runs"])
    answer_ids = {case["case_id"] for case in verified.answer_cases}
    set_ids = {case["case_id"] for case in verified.set_cases}
    answer_hash = expected_checkpoint["answer_eval_set_sha256"]
    set_hash = expected_checkpoint["set_eval_set_sha256"]
    if (
        len({row.get("case_id") for row in answer_runs}) != len(answer_runs)
        or any(
            row.get("case_id") not in answer_ids
            or row.get("eval_set_sha256") != answer_hash
            or row.get("config_sha256") != verified.config_sha256
            for row in answer_runs
        )
    ):
        raise ValueError("baseline_answer_checkpoint_invalid")
    if (
        len({row.get("case_id") for row in set_runs}) != len(set_runs)
        or any(
            row.get("case_id") not in set_ids
            or row.get("eval_set_sha256") != set_hash
            for row in set_runs
        )
    ):
        raise ValueError("baseline_set_checkpoint_invalid")
    _validate_case_markers(verified, paths, answer_runs, set_runs)
    _budget_snapshot(
        verified,
        paths,
        required=bool(answer_runs or set_runs),
        initialize=initialize,
    )
    return answer_runs, set_runs


def _load_openai_pipeline(verified: VerifiedBaseline, paths: Mapping[str, Path]) -> Any:
    """Create the provider stack only after the caller's egress gate passed."""

    try:
        from dotenv import load_dotenv
    except ImportError as error:
        raise RuntimeError("dotenv_dependency_missing") from error
    load_dotenv(verified.repo_root / ".env", override=False)
    if not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("openai_api_key_missing")

    from midprojectrag.answering.pipeline import RagPipeline
    from midprojectrag.indexing.budget import BudgetLedger
    from midprojectrag.indexing.embeddings import EmbeddingCache
    from midprojectrag.observability import NoopObserver
    from midprojectrag.stacks.api import (
        OpenAIEmbeddingProvider,
        OpenAIGenerator,
        TiktokenCounter,
        api_config_sha256,
    )

    artifacts = verified.config["artifacts"]
    runtime = verified.config["runtime"]
    chunks_path = _relative_path(verified.repo_root, artifacts["chunks"])
    index_dir = _relative_path(verified.repo_root, artifacts["index_dir"])
    tokenizer_cache = _relative_path(
        verified.repo_root, artifacts["tiktoken_cache_dir"]
    )
    chunks = read_jsonl(chunks_path)
    metadata = json.loads((index_dir / "metadata.json").read_text(encoding="utf-8"))
    index_config = json.loads(
        (index_dir / "index-config.json").read_text(encoding="utf-8")
    )
    index_config_sha256 = api_config_sha256(index_config)
    if index_config_sha256 != metadata.get("index_config_sha256"):
        raise ValueError("baseline_index_config_hash_mismatch")
    index = ExactDenseIndex.load(
        index_dir,
        chunks,
        expected_embedding_model=runtime["embedding_model"],
        expected_dimensions=runtime["embedding_dimensions"],
        expected_api_profile=runtime["api_profile"],
        expected_index_config_sha256=index_config_sha256,
    )
    generator = OpenAIGenerator(
        model=runtime["generator_model"],
        max_output_tokens=runtime["max_output_tokens"],
        max_citations=runtime["max_citations"],
        reasoning_effort=runtime["reasoning_effort"],
    )
    pipeline = RagPipeline(
        index=index,
        embedding_provider=OpenAIEmbeddingProvider(
            model=runtime["embedding_model"],
            dimensions=runtime["embedding_dimensions"],
            api_profile=runtime["api_profile"],
        ),
        embedding_counter=TiktokenCounter(
            runtime["embedding_model"], cache_dir=tokenizer_cache
        ),
        query_cache=EmbeddingCache(paths["query_cache"]),
        generator=generator,
        generation_counter=TiktokenCounter(
            runtime["generator_model"], cache_dir=tokenizer_cache
        ),
        budget=BudgetLedger(
            paths["budget_ledger"], limit_usd=runtime["budget_limit_usd"]
        ),
        corpus_manifest_sha256=artifacts["manifest_sha256"],
        stack_id="supplemental-provisional-v1",
        observer=NoopObserver(),
        retrieval_top_k=runtime["retrieval_top_k"],
        context_top_k=runtime["context_top_k"],
    )
    return pipeline, index_config_sha256


def _request(case: Mapping[str, Any], *, max_citations: int) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": f"eval-{case['case_id']}",
        "question": case["question"],
        "history": [],
        "document_scope": {"mode": "all", "doc_ids": []},
        "options": {"max_citations": max_citations},
    }


def _answer_run(
    case: Mapping[str, Any],
    result: Any,
    *,
    eval_set_sha256: str,
    config_sha256: str,
) -> dict[str, Any]:
    response = result.response
    status = response["status"]
    error = response.get("error")
    return {
        "schema_version": SCHEMA_VERSION,
        "case_id": case["case_id"],
        "eval_set_sha256": eval_set_sha256,
        "config_sha256": config_sha256,
        "status": status,
        "answer": response["answer"] if status == "answered" else "",
        "retrieved_doc_ids": [row["doc_id"] for row in result.retrieval],
        "cited_doc_ids": list(
            dict.fromkeys(item["doc_id"] for item in response.get("citations", []))
        ),
        "timing_ms": {
            key: float(result.timing_ms[key])
            for key in ("retrieval", "generation", "total")
        },
        "usage": {
            "embedding_tokens": int(result.usage["embedding_tokens"]),
            "input_tokens": int(result.usage["input_tokens"]),
            "output_tokens": int(result.usage["output_tokens"]),
            "cost_usd": float(result.usage["cost_usd"]),
        },
        "cache_hit": bool(result.cache_hit),
        "error": ({"code": error["code"]} if status == "error" else None),
    }


def _set_run(
    case: Mapping[str, Any], result: Any, *, eval_set_sha256: str
) -> dict[str, Any]:
    response = result.response
    error = response.get("error")
    return {
        "schema_version": SCHEMA_VERSION,
        "case_id": case["case_id"],
        "eval_set_sha256": eval_set_sha256,
        "returned_doc_ids": list(
            dict.fromkeys(row["doc_id"] for row in result.retrieval)
        ),
        "error": ({"code": error["code"]} if response["status"] == "error" else None),
    }


def _run_openai_baseline_locked(
    verified: VerifiedBaseline, paths: Mapping[str, Path]
) -> dict[str, Any]:
    answer_runs, set_runs = _load_or_initialize_runs(verified, paths)
    answer_hash = dataset_sha256(verified.answer_cases)
    set_hash = dataset_sha256(verified.set_cases)
    completed_answer = {row["case_id"] for row in answer_runs}
    completed_set = {row["case_id"] for row in set_runs}
    total = len(verified.answer_cases) + len(verified.set_cases)
    completed = len(answer_runs) + len(set_runs)
    if completed == total:
        return _score_existing_locked(verified, paths)
    pipeline, index_config_sha256 = _load_openai_pipeline(verified, paths)
    interval = float(verified.config["runtime"]["case_interval_seconds"])
    try:
        for lane, cases in (
            ("answer", verified.answer_cases),
            ("set", verified.set_cases),
        ):
            completed_ids = completed_answer if lane == "answer" else completed_set
            for case in cases:
                if case["case_id"] in completed_ids:
                    continue
                _write_case_marker(
                    verified,
                    paths,
                    lane=lane,
                    case_id=case["case_id"],
                    state="started",
                )
                result = pipeline.query(
                    _request(
                        case,
                        max_citations=verified.config["runtime"]["max_citations"],
                    ),
                    trace_context={
                        "run_id": verified.config["baseline_id"],
                        "case_id": case["case_id"],
                        "eval_set_sha256": answer_hash if lane == "answer" else set_hash,
                        "config_sha256": verified.config_sha256,
                        "api_profile": verified.config["runtime"]["api_profile"],
                        "index_config_sha256": index_config_sha256,
                    },
                )
                if lane == "answer":
                    run_record = _answer_run(
                        case,
                        result,
                        eval_set_sha256=answer_hash,
                        config_sha256=verified.config_sha256,
                    )
                    answer_runs.append(run_record)
                    write_runtime_jsonl(paths["answer_runs"], answer_runs)
                else:
                    run_record = _set_run(
                        case, result, eval_set_sha256=set_hash
                    )
                    set_runs.append(run_record)
                    write_runtime_jsonl(paths["set_runs"], set_runs)
                _write_case_marker(
                    verified,
                    paths,
                    lane=lane,
                    case_id=case["case_id"],
                    state="completed",
                    run_record=run_record,
                )
                completed += 1
                print(
                    canonical_json(
                        {
                            "event": "case_completed",
                            "completed": completed,
                            "total": total,
                            "lane": lane,
                            "case_id": case["case_id"],
                            "status": result.response["status"],
                        }
                    ),
                    file=sys.stderr,
                    flush=True,
                )
                if completed < total and interval > 0:
                    time.sleep(interval)
    finally:
        pipeline.flush_observability()
    if completed != total:
        raise ValueError("supplemental_baseline_run_incomplete")
    return _score_existing_locked(verified, paths)


def run_openai_baseline(
    verified: VerifiedBaseline, *, approve_private_corpus_egress: bool
) -> dict[str, Any]:
    if approve_private_corpus_egress is not True:
        raise ValueError("private_corpus_egress_not_approved")
    paths = _private_run_paths(verified)
    with _exclusive_run_lock(paths["run_lock"]):
        return _run_openai_baseline_locked(verified, paths)


def _load_transcript_index(verified: VerifiedBaseline) -> ExactDenseIndex:
    artifacts = verified.config["artifacts"]
    runtime = verified.config["runtime"]
    chunks = read_jsonl(_relative_path(verified.repo_root, artifacts["chunks"]))
    index_dir = _relative_path(verified.repo_root, artifacts["index_dir"])
    metadata = json.loads(
        (index_dir / "metadata.json").read_text(encoding="utf-8")
    )
    index_config = json.loads(
        (index_dir / "index-config.json").read_text(encoding="utf-8")
    )
    index_config_sha256 = api_config_sha256(index_config)
    if index_config_sha256 != metadata.get("index_config_sha256"):
        raise ValueError("baseline_index_config_hash_mismatch")
    return ExactDenseIndex._load_unlocked(
        index_dir,
        chunks,
        expected_embedding_model=runtime["embedding_model"],
        expected_dimensions=runtime["embedding_dimensions"],
        expected_api_profile=runtime["api_profile"],
        expected_index_config_sha256=index_config_sha256,
    )


def _cached_query_vector(
    verified: VerifiedBaseline,
    paths: Mapping[str, Path],
    request: Mapping[str, Any],
) -> tuple[Any, str, str]:
    """Load the content-addressed cached query vector without a provider."""

    if request.get("history") != []:
        raise ValueError("baseline_transcript_history_not_frozen")
    query_text = f"user: {request['question']}"
    runtime = verified.config["runtime"]
    key = EmbeddingCache.key(
        corpus_manifest_sha256=verified.config["artifacts"]["manifest_sha256"],
        chunk_config_sha256=sha256_text("query-v1"),
        model=runtime["embedding_model"],
        dimensions=runtime["embedding_dimensions"],
        content_sha256=sha256_text(query_text),
    )
    vector = EmbeddingCache(paths["query_cache"]).get(
        key, runtime["embedding_dimensions"]
    )
    if vector is None:
        raise ValueError("baseline_transcript_query_cache_missing")
    return vector, key, query_text


def _transcript_source(hit: Any, *, retrieval_rank: int) -> dict[str, Any]:
    chunk = hit.chunk
    source = {
        "retrieval_rank": retrieval_rank,
        "score": float(hit.score),
        "doc_id": chunk["doc_id"],
        "chunk_id": chunk["chunk_id"],
        "source_text": chunk["text"],
    }
    for field in (
        "page",
        "page_start",
        "page_end",
        "section_path",
        "source_locator",
        "retrieval_role",
        "chunker_id",
        "occurrence_id",
        "evidence_type",
    ):
        if field in chunk:
            source[field] = chunk[field]
    return source


def _assistant_transcript_projection(
    lane: str, run: Mapping[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    unavailable = [
        "provider.raw_request_envelope",
        "provider.raw_response_envelope",
        "assistant.abstention_reason",
        "assistant.citation_chunk_ids",
        "assistant.full_citations",
        "assistant.trace_id",
    ]
    if lane == "answer":
        status = run.get("status")
        answered = status == "answered"
        if not answered:
            unavailable.append("assistant.rendered_answer")
        return (
            {
                "persisted_status": status,
                "persisted_answer": run.get("answer"),
                "persisted_answer_semantics": (
                    "exact_final_answer"
                    if answered
                    else "empty_placeholder_non_answered_text_not_persisted"
                ),
                "persisted_cited_doc_ids": run.get("cited_doc_ids"),
                "persisted_error": run.get("error"),
            },
            unavailable,
        )
    unavailable.extend(
        [
            "assistant.status",
            "assistant.rendered_answer",
            "assistant.cited_doc_ids",
            "execution.timing_ms",
            "execution.usage",
            "execution.cache_hit",
        ]
    )
    return (
        {
            "persisted_status": None,
            "persisted_answer": None,
            "persisted_answer_semantics": "not_persisted_for_set_lane",
            "persisted_cited_doc_ids": None,
            "persisted_error": run.get("error"),
        },
        unavailable,
    )


def _build_chat_transcripts_locked(
    verified: VerifiedBaseline, paths: Mapping[str, Path]
) -> dict[str, Any]:
    answer_runs, set_runs = _load_or_initialize_runs(
        verified, paths, initialize=False
    )
    expected_total = len(verified.answer_cases) + len(verified.set_cases)
    if len(answer_runs) + len(set_runs) != expected_total:
        raise ValueError("baseline_transcript_run_incomplete")
    receipt_path = paths["receipt"]
    if not receipt_path.is_file():
        raise ValueError("baseline_transcript_receipt_missing")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if (
        not isinstance(receipt, dict)
        or receipt.get("baseline_id") != verified.config["baseline_id"]
        or receipt.get("config_sha256") != verified.config_sha256
        or not isinstance(receipt.get("artifact_sha256s"), dict)
        or not isinstance(receipt.get("counts"), dict)
    ):
        raise ValueError("baseline_transcript_receipt_invalid")

    index = _load_transcript_index(verified)
    runtime = verified.config["runtime"]
    answer_hash = dataset_sha256(verified.answer_cases)
    set_hash = dataset_sha256(verified.set_cases)
    run_by_key = {
        **{("answer", row["case_id"]): row for row in answer_runs},
        **{("set", row["case_id"]): row for row in set_runs},
    }
    provider_schema = build_openai_answer_plan_schema(runtime["max_citations"])
    source_artifact_sha256s = {
        "answer_cases": answer_hash,
        "set_cases": set_hash,
        "answer_runs": dataset_sha256(answer_runs),
        "set_runs": dataset_sha256(set_runs),
        "manifest": verified.config["artifacts"]["manifest_sha256"],
        "chunks": verified.config["artifacts"]["chunks_sha256"],
        "index_metadata": verified.config["artifacts"][
            "index_metadata_sha256"
        ],
    }
    reconstruction_contract_sha256s = _reconstruction_contract_sha256s(runtime)
    rows: list[dict[str, Any]] = []
    exact_answer_count = 0
    unavailable_answer_count = 0
    for lane, cases in (
        ("answer", verified.answer_cases),
        ("set", verified.set_cases),
    ):
        for case in cases:
            run = run_by_key[(lane, case["case_id"])]
            request = _request(case, max_citations=runtime["max_citations"])
            vector, cache_key, retrieval_query = _cached_query_vector(
                verified, paths, request
            )
            query_vector_sha256 = sha256_bytes(vector.tobytes(order="C"))
            hits = index.search(
                vector,
                top_k=runtime["retrieval_top_k"],
                allowed_doc_ids=None,
            )
            reconstructed_doc_ids = [hit.chunk["doc_id"] for hit in hits]
            if lane == "answer":
                if reconstructed_doc_ids != run.get("retrieved_doc_ids"):
                    raise ValueError("baseline_transcript_retrieval_mismatch")
            elif list(dict.fromkeys(reconstructed_doc_ids)) != run.get(
                "returned_doc_ids"
            ):
                raise ValueError("baseline_transcript_retrieval_mismatch")

            context_hits = _select_context_hits(
                hits,
                context_top_k=runtime["context_top_k"],
                table_context_cap=None,
            )
            prompt = _build_prompt(request, context_hits) if context_hits else None
            selected_ids = {hit.chunk["chunk_id"] for hit in context_hits}
            retrieval = [
                {
                    "rank": rank,
                    "score": float(hit.score),
                    "doc_id": hit.chunk["doc_id"],
                    "chunk_id": hit.chunk["chunk_id"],
                    "selected_for_context": hit.chunk["chunk_id"] in selected_ids,
                }
                for rank, hit in enumerate(hits, start=1)
            ]
            rank_by_chunk_id = {
                hit.chunk["chunk_id"]: rank
                for rank, hit in enumerate(hits, start=1)
            }
            context_sources = [
                _transcript_source(
                    hit,
                    retrieval_rank=rank_by_chunk_id[hit.chunk["chunk_id"]],
                )
                for hit in context_hits
            ]
            assistant, unavailable_fields = _assistant_transcript_projection(
                lane, run
            )
            if lane == "answer" and run.get("status") == "answered":
                exact_answer_count += 1
            else:
                unavailable_answer_count += 1
            execution = (
                {
                    "timing_ms": run.get("timing_ms"),
                    "usage": run.get("usage"),
                    "cache_hit": run.get("cache_hit"),
                }
                if lane == "answer"
                else {"timing_ms": None, "usage": None, "cache_hit": None}
            )
            record = {
                "schema_version": SCHEMA_VERSION,
                "capture_mode": "posthoc_reconstructed",
                "baseline_id": verified.config["baseline_id"],
                "lane": lane,
                "case_id": case["case_id"],
                "eval_set_sha256": answer_hash if lane == "answer" else set_hash,
                "config_sha256": verified.config_sha256,
                "request": request,
                "retrieval_query": retrieval_query,
                "query_cache_key": cache_key,
                "query_vector_sha256": query_vector_sha256,
                "retrieval": retrieval,
                "context_sources": context_sources,
                "provider_request": {
                    "capture_status": "reconstructed_not_runtime_captured",
                    "runtime_transmission_status": "unavailable_not_persisted",
                    "arguments": (
                        {
                            "model": runtime["generator_model"],
                            "instructions": SYSTEM_INSTRUCTIONS,
                            "input": prompt,
                            "store": False,
                            "max_output_tokens": runtime["max_output_tokens"],
                            "reasoning": {"effort": runtime["reasoning_effort"]},
                            "text": {
                                "format": {
                                    "type": "json_schema",
                                    "name": "rag_answer_plan",
                                    "strict": True,
                                    "schema": provider_schema,
                                }
                            },
                        }
                        if prompt is not None
                        else None
                    ),
                },
                "assistant": assistant,
                "execution": execution,
                "runtime_equivalence": {
                    "verification_level": "retrieved_doc_id_projection_only",
                    "retrieved_chunk_ids": "runtime_unverified_not_persisted",
                    "context_selection": "deterministic_replay_runtime_unverified",
                    "provider_request": "reconstructed_not_runtime_captured",
                },
                "unavailable_fields": sorted(set(unavailable_fields)),
                "reconstruction_contract_sha256s": (
                    reconstruction_contract_sha256s
                ),
                "source_artifact_sha256s": source_artifact_sha256s,
                "source_run_record_sha256": sha256_text(canonical_json(run)),
            }
            record["record_sha256"] = sha256_text(canonical_json(record))
            rows.append(record)

    if len(rows) != expected_total or len({row["case_id"] for row in rows}) != len(
        rows
    ):
        raise ValueError("baseline_transcript_count_invalid")
    output_path = paths["chat_transcripts"]
    write_runtime_jsonl(output_path, rows)
    transcript_sha256 = sha256_file(output_path)
    _attach_existing_transcript_receipt(
        verified, paths, receipt, answer_runs, set_runs
    )
    write_json(receipt_path, receipt)
    return {
        "schema_version": SCHEMA_VERSION,
        "passed": True,
        "baseline_id": verified.config["baseline_id"],
        "capture_mode": "posthoc_reconstructed",
        "runtime_equivalence": "retrieved_doc_id_projection_only",
        "provider_calls": 0,
        "private_corpus_egress": False,
        "private_output": True,
        "counts": {
            "transcripts": len(rows),
            "answer_lane": len(answer_runs),
            "set_lane": len(set_runs),
            "exact_persisted_answers": exact_answer_count,
            "answers_unavailable_or_elided": unavailable_answer_count,
        },
        "chat_transcripts_sha256": transcript_sha256,
        "chat_transcripts_dataset_sha256": dataset_sha256(rows),
        "public_receipt_updated": True,
    }


def export_chat_transcripts(verified: VerifiedBaseline) -> dict[str, Any]:
    """Reconstruct private prompts/context from frozen local artifacts only."""

    paths = _private_run_paths(verified)
    with _exclusive_run_lock(paths["run_lock"]):
        return _build_chat_transcripts_locked(verified, paths)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify or score the frozen supplemental baseline")
    parser.add_argument("--config", type=Path, default=Path("evaluation/baselines/supplemental-provisional-v1/config.json"))
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--preflight-only", action="store_true")
    action.add_argument("--score-existing", action="store_true")
    action.add_argument("--run-openai", action="store_true")
    action.add_argument("--export-chat-transcripts", action="store_true")
    parser.add_argument("--approve-private-corpus-egress", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        verified = verify_baseline(args.config)
        if args.preflight_only:
            report = preflight_report(verified)
        elif args.score_existing:
            report = score_existing(verified)
        elif args.run_openai:
            report = run_openai_baseline(
                verified,
                approve_private_corpus_egress=args.approve_private_corpus_egress,
            )
        else:
            report = export_chat_transcripts(verified)
        print(canonical_json(report))
        return 0 if report["passed"] else 2
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RuntimeError) as error:
        code = str(error)
        if re.fullmatch(r"[a-z][a-z0-9_]{0,127}", code) is None:
            code = "supplemental_baseline_failed"
        print(canonical_json({"schema_version": SCHEMA_VERSION, "passed": False, "error": {"code": code}}))
        return 2
    except Exception:
        print(
            canonical_json(
                {
                    "schema_version": SCHEMA_VERSION,
                    "passed": False,
                    "error": {"code": "supplemental_baseline_failed"},
                }
            )
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
