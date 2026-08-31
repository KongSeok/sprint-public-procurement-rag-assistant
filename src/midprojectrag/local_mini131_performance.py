"""Build the private per-question performance record for local Mini131.

The local runner, deterministic scorer, and blind Sol reviewer intentionally
write separate artifacts.  This module verifies those artifacts again and
joins them into a human-reviewable private ledger without making provider
calls or changing the frozen suite/reviewer configuration.
"""

from __future__ import annotations

import argparse
import copy
import html
import json
import math
import os
import re
import stat
import sys
import tempfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import fmean
from typing import Any

from midprojectrag.ingest.common import (
    canonical_json,
    read_jsonl,
    sha256_file,
    sha256_text,
)
from midprojectrag.local_mini131_baseline import (
    DEFAULT_CONFIG,
    EXPECTED_COUNTS,
    SUITE_ID,
    SourceCase,
    _expected,
    verify_suite,
)
from midprojectrag.local_mini131_semantic import (
    ROLE_ORDER,
    SemanticLedger,
    default_paths as semantic_paths,
    load_ledger,
    validate_decisions,
)
from midprojectrag.mini131_bundle import (
    JUDGE_MODEL,
    JUDGE_RUBRIC,
    _binary_recommendation,
    _judgment_semantic_score,
    _secondary_triggered,
)


RECORD_SCHEMA_VERSION = "local-mini131-golden-evaluation-record.v1"
SUMMARY_SCHEMA_VERSION = "local-mini131-golden-performance-summary.v1"
REPORT_SCHEMA_VERSION = "local-mini131-golden-performance-report.v1"
RECEIPT_SCHEMA_VERSION = "local-mini131-golden-performance-receipt.v1"
PERFORMANCE_DIRNAME = "performance-v1"
RECORDS_FILENAME = "golden-evaluation-records.jsonl"
SUMMARY_FILENAME = "golden-performance-summary.json"
HTML_FILENAME = "golden-performance-report.html"
RECEIPT_FILENAME = "mac-local-equivalent-performance-receipt.json"
DIFFICULTIES = ("easy", "medium", "hard")
EXPECTED_DIFFICULTY_COUNTS = {"easy": 41, "medium": 48, "hard": 40}
PUBLIC_PURPOSES = {
    "abstention",
    "clause_fact_regression",
    "conditional_all_list",
    "corpus_analytics",
    "follow_up",
    "gold_source_alignment",
    "multi_doc_compare",
    "parser_regression",
    "single_doc",
    "visual_table_figure",
}
PUBLIC_LANES = {
    "core40",
    "corpus_analytics",
    "parser_regression",
    "supplemental_answer_legacy",
    "supplemental_answer_rerun",
    "supplemental_set_rerun",
    "visual",
}
COMPONENT_FIELDS = (
    "correctness",
    "faithfulness",
    "completeness",
    "factual_claim_coverage",
    "citation_validity",
    "abstention_quality",
)
RAG_STATUSES = {"answered", "abstained", "error"}
FINAL_DECISIONS = {"accepted", "rejected"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class PerformancePaths:
    root: Path
    records: Path
    summary: Path
    html: Path
    receipt: Path


def default_paths(suite: Any) -> PerformancePaths:
    root = suite.private_judge_input_path.parent / PERFORMANCE_DIRNAME
    return PerformancePaths(
        root=root,
        records=root / RECORDS_FILENAME,
        summary=root / SUMMARY_FILENAME,
        html=root / HTML_FILENAME,
        receipt=suite.public_receipt_path.with_name(RECEIPT_FILENAME),
    )


def default_decision_paths(ledger: SemanticLedger) -> list[Path]:
    root = ledger.paths.review_root
    return [
        root / "primary-decisions-1.jsonl",
        root / "primary-decisions-2.jsonl",
        root / "primary-decisions-3.jsonl",
        root / "secondary-decisions.jsonl",
        root / "adjudicator-decisions.jsonl",
    ]


def _read_private_json(path: Path, code: str) -> dict[str, Any]:
    if (
        not path.is_file()
        or path.is_symlink()
        or stat.S_IMODE(path.stat().st_mode) != 0o600
    ):
        raise ValueError(code)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(code) from error
    if not isinstance(value, dict):
        raise ValueError(code)
    return value


def _index_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    expected: int,
    code: str,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or not case_id or case_id in result:
            raise ValueError(code)
        result[case_id] = copy.deepcopy(dict(row))
    if len(result) != expected:
        raise ValueError(code)
    return result


def _adjudication_required(
    primary: Mapping[str, Any], secondary: Mapping[str, Any]
) -> bool:
    unresolved = secondary.get("judge_decision") == "needs_review"
    disagreement = (
        not unresolved
        and secondary.get("judge_decision") != _binary_recommendation(primary)
    )
    flags_differ = set(primary.get("critical_flags", [])) != set(
        secondary.get("critical_flags", [])
    )
    return bool(unresolved or disagreement or flags_differ)


def resolve_final_judgments(
    ledger: SemanticLedger,
    decision_paths: Sequence[Path],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    dict[str, dict[str, Any]],
]:
    """Validate every decision and return final/history/workflow by case."""

    raw, judgments = validate_decisions(ledger, decision_paths)
    _validate_review_history_binding(ledger, raw)
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for judgment in judgments:
        case_id = str(judgment["case_id"])
        role = str(judgment["judge_role"])
        if role in grouped.setdefault(case_id, {}):
            raise ValueError("local_mini131_performance_duplicate_judgment_role")
        grouped[case_id][role] = copy.deepcopy(judgment)
    if set(grouped) != set(ledger.candidate_by_case):
        raise ValueError("local_mini131_performance_judgment_ledger_mismatch")

    finals: dict[str, dict[str, Any]] = {}
    histories: dict[str, list[dict[str, Any]]] = {}
    workflows: dict[str, dict[str, Any]] = {}
    for case_id in sorted(grouped):
        by_role = grouped[case_id]
        primary = by_role.get("primary")
        if primary is None:
            raise ValueError("local_mini131_performance_primary_missing")
        secondary = by_role.get("secondary")
        adjudicator = by_role.get("adjudicator")
        secondary_required = _secondary_triggered(primary)
        if secondary_required != (secondary is not None):
            raise ValueError("local_mini131_performance_secondary_workflow_invalid")
        adjudicator_required = bool(
            secondary is not None and _adjudication_required(primary, secondary)
        )
        if adjudicator_required != (adjudicator is not None):
            raise ValueError("local_mini131_performance_adjudication_workflow_invalid")
        history = [copy.deepcopy(by_role[role]) for role in ROLE_ORDER if role in by_role]
        reviewed = [
            datetime.fromisoformat(str(row["reviewed_at"]).replace("Z", "+00:00"))
            for row in history
        ]
        if reviewed != sorted(reviewed):
            raise ValueError("local_mini131_performance_review_order_invalid")
        final = copy.deepcopy(adjudicator or secondary or primary)
        if final.get("judge_decision") not in FINAL_DECISIONS:
            raise ValueError("local_mini131_performance_final_unresolved")
        secondary_unresolved = bool(
            secondary is not None and secondary.get("judge_decision") == "needs_review"
        )
        disagreement = bool(
            secondary is not None
            and not secondary_unresolved
            and secondary.get("judge_decision") != _binary_recommendation(primary)
        )
        critical_flag_mismatch = bool(
            secondary is not None
            and set(primary.get("critical_flags", []))
            != set(secondary.get("critical_flags", []))
        )
        finals[case_id] = final
        histories[case_id] = history
        workflows[case_id] = {
            "secondary_required": secondary_required,
            "secondary_present": secondary is not None,
            "adjudicator_required": adjudicator_required,
            "adjudicator_present": adjudicator is not None,
            "primary_binary_recommendation": _binary_recommendation(primary),
            "secondary_unresolved": secondary_unresolved,
            "disagreement": disagreement,
            "critical_flag_mismatch": critical_flag_mismatch,
            "final_judgment_id": final["judgment_id"],
        }
    return finals, histories, workflows


def _validate_review_history_binding(
    ledger: SemanticLedger,
    decisions: Sequence[Mapping[str, Any]],
) -> None:
    history_path = ledger.paths.review_root / "review-history.jsonl"
    if (
        not history_path.is_file()
        or history_path.is_symlink()
        or stat.S_IMODE(history_path.stat().st_mode) != 0o600
    ):
        raise ValueError("local_mini131_performance_review_history_invalid")
    history_rows = read_jsonl(history_path)
    if len(history_rows) != len(decisions):
        raise ValueError("local_mini131_performance_review_history_count_invalid")
    expected = {
        (str(row["blind_id"]), str(row["judge_role"])): canonical_json(row)
        for row in decisions
    }
    if len(expected) != len(decisions):
        raise ValueError("local_mini131_performance_review_history_identity_invalid")
    observed: dict[tuple[str, str], str] = {}
    for history in history_rows:
        if not isinstance(history, Mapping):
            raise ValueError("local_mini131_performance_review_history_invalid")
        review_output = history.get("review_output")
        if not isinstance(review_output, Mapping):
            raise ValueError("local_mini131_performance_review_history_invalid")
        identity = (
            str(history.get("blind_id")),
            str(history.get("judge_role")),
        )
        if (
            identity in observed
            or identity
            != (
                str(review_output.get("blind_id")),
                str(review_output.get("judge_role")),
            )
            or history.get("output_sha256")
            != sha256_text(canonical_json(review_output))
        ):
            raise ValueError("local_mini131_performance_review_history_identity_invalid")
        history_without_hash = copy.deepcopy(dict(history))
        stored_history_sha256 = history_without_hash.pop("history_sha256", None)
        if stored_history_sha256 != sha256_text(canonical_json(history_without_hash)):
            raise ValueError("local_mini131_performance_review_history_hash_invalid")
        observed[identity] = canonical_json(review_output)
    if observed != expected:
        raise ValueError("local_mini131_performance_review_history_decision_mismatch")


def _evaluation_purpose(source_case: SourceCase) -> str:
    if source_case.lane == "core40":
        task_type = source_case.source.get("task_type")
        if task_type not in {"single_doc", "multi_doc_compare", "follow_up", "unknown"}:
            raise ValueError("local_mini131_performance_core_purpose_invalid")
        return "abstention" if task_type == "unknown" else str(task_type)
    if source_case.lane in {
        "supplemental_answer_legacy",
        "supplemental_answer_rerun",
    }:
        source_lane = source_case.source.get("lane")
        if source_lane == "answer_alignment":
            return "gold_source_alignment"
        if source_lane == "qa_regression":
            return "clause_fact_regression"
        raise ValueError("local_mini131_performance_answer_purpose_invalid")
    return {
        "supplemental_set_rerun": "conditional_all_list",
        "visual": "visual_table_figure",
        "corpus_analytics": "corpus_analytics",
    }[source_case.lane]


def _source_projection(
    source_case: SourceCase,
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    response = candidate["response"]
    evidence = (
        [copy.deepcopy(candidate["companion"])]
        if source_case.lane == "corpus_analytics"
        else copy.deepcopy(candidate["generation"]["prompts"])
    )
    history = candidate["request"].get("history", [])
    chat = copy.deepcopy(history) if isinstance(history, list) else []
    chat.extend(
        [
            {"role": "user", "content": source_case.source["question"]},
            {"role": "assistant", "content": response["answer"]},
        ]
    )
    return {
        "question": source_case.source["question"],
        "expected": _expected(source_case),
        "candidate_chat": chat,
        "retrieval": {
            "retrieved_docs": copy.deepcopy(candidate["retrieval"]),
            "cited_docs": copy.deepcopy(response["citations"]),
            "evidence": evidence,
        },
    }


def _load_deterministic_rows(
    ledger: SemanticLedger,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    report = _read_private_json(
        ledger.paths.deterministic_score,
        "local_mini131_performance_deterministic_score_invalid",
    )
    if (
        report.get("suite_id") != SUITE_ID
        or report.get("suite_config_sha256") != ledger.suite.config_sha256
        or report.get("eval_set_sha256") != ledger.suite.eval_set_sha256
        or report.get("suite_complete") is not True
        or report.get("counts", {}).get("rag_scored") != EXPECTED_COUNTS["rag"]
    ):
        raise ValueError("local_mini131_performance_deterministic_score_invalid")
    per_case = report.get("per_case")
    if not isinstance(per_case, list):
        raise ValueError("local_mini131_performance_deterministic_cases_invalid")
    indexed = _index_rows(
        per_case,
        expected=EXPECTED_COUNTS["rag"],
        code="local_mini131_performance_deterministic_cases_invalid",
    )
    if set(indexed) != set(ledger.candidate_by_case):
        raise ValueError("local_mini131_performance_deterministic_ledger_mismatch")
    for case_id, row in indexed.items():
        candidate = ledger.candidate_by_case[case_id]
        source_case = ledger.suite.cases_by_id[case_id]
        if (
            row.get("lane") != source_case.lane
            or row.get("status") != candidate["response"]["status"]
        ):
            raise ValueError("local_mini131_performance_deterministic_binding_mismatch")
    return report, indexed


def _load_semantic_report(
    ledger: SemanticLedger,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    report = _read_private_json(
        ledger.paths.semantic_score,
        "local_mini131_performance_semantic_score_invalid",
    )
    cases = report.get("cases")
    if (
        report.get("suite_id") != SUITE_ID
        or report.get("suite_config_sha256") != ledger.suite.config_sha256
        or report.get("eval_set_sha256") != ledger.suite.eval_set_sha256
        or report.get("semantic_judgment") != "complete"
        or report.get("deterministic_score_sha256")
        != ledger.deterministic_score_sha256
        or not isinstance(cases, list)
    ):
        raise ValueError("local_mini131_performance_semantic_score_invalid")
    indexed = _index_rows(
        cases,
        expected=EXPECTED_COUNTS["rag"],
        code="local_mini131_performance_semantic_cases_invalid",
    )
    if set(indexed) != set(ledger.candidate_by_case):
        raise ValueError("local_mini131_performance_semantic_ledger_mismatch")
    history_path = ledger.paths.review_root / "review-history.jsonl"
    if (
        not history_path.is_file()
        or history_path.is_symlink()
        or stat.S_IMODE(history_path.stat().st_mode) != 0o600
        or report.get("review_history_sha256") != sha256_file(history_path)
    ):
        raise ValueError("local_mini131_performance_review_history_invalid")
    history_rows = read_jsonl(history_path)
    if len(history_rows) != sum(report.get("counts", {}).get("judge_roles", {}).values()):
        raise ValueError("local_mini131_performance_review_history_count_invalid")
    return report, indexed


def _load_parser_results(ledger: SemanticLedger) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    path = ledger.paths.candidates.with_name("parser-rerun.json")
    payload = _read_private_json(path, "local_mini131_performance_parser_rerun_invalid")
    result = payload.get("result")
    cases = result.get("cases") if isinstance(result, Mapping) else None
    if (
        payload.get("schema_version") != "local-mini131-parser-rerun.v1"
        or payload.get("suite_id") != SUITE_ID
        or payload.get("run_id") != ledger.run_id
        or payload.get("receipt_sha256")
        != ledger.suite.config.get("sources", {}).get("parser_receipt", {}).get("sha256")
        or not isinstance(result, Mapping)
        or canonical_json(result) != canonical_json(ledger.suite.parser_receipt)
        or result.get("passed") is not True
        or result.get("counts") != {"total": 2, "passed": 2, "failed": 0}
        or not isinstance(cases, list)
    ):
        raise ValueError("local_mini131_performance_parser_rerun_invalid")
    return payload, _index_rows(
        cases,
        expected=EXPECTED_COUNTS["parser"],
        code="local_mini131_performance_parser_cases_invalid",
    )


def _rag_record(
    ledger: SemanticLedger,
    source_case: SourceCase,
    *,
    deterministic: Mapping[str, Any],
    final: Mapping[str, Any],
    history: Sequence[Mapping[str, Any]],
    workflow: Mapping[str, Any],
    semantic_score_sha256: str,
) -> dict[str, Any]:
    candidate = ledger.candidate_by_case[source_case.case_id]
    projection = _source_projection(source_case, candidate)
    difficulty = source_case.source.get("difficulty")
    if difficulty not in DIFFICULTIES:
        raise ValueError("local_mini131_performance_difficulty_invalid")
    final_score = _judgment_semantic_score(final)
    generation = ledger.suite.stack.config.get("generation", {})
    embedding = ledger.suite.stack.config.get("embedding", {})
    response = candidate["response"]
    candidate_sha256 = sha256_text(canonical_json(candidate))
    deterministic_sha256 = sha256_text(canonical_json(deterministic))
    return {
        "schema_version": RECORD_SCHEMA_VERSION,
        "case_id": source_case.case_id,
        "asset_type": "rag",
        "lane": source_case.lane,
        "purpose": _evaluation_purpose(source_case),
        "difficulty": difficulty,
        "official": False,
        "gold_review_status": "draft",
        "evaluation_status": {
            "record_complete": True,
            "quality_pass": final["judge_decision"] == "accepted",
            "gold_approved": False,
            "official_eligible": False,
        },
        "question": projection["question"],
        "expected": projection["expected"],
        "candidate": {
            "model": generation.get("mac_equivalent_model"),
            "embedding_model": embedding.get("model"),
            "execution_profile": "mac_local_equivalent",
            "status": response["status"],
            "answer": response["answer"],
            "chat": projection["candidate_chat"],
            "citations": copy.deepcopy(response["citations"]),
            "selected_doc_ids": copy.deepcopy(response["selected_doc_ids"]),
            "abstention_reason": response["abstention_reason"],
            "error_code": response["error_code"],
            "execution_lineage": copy.deepcopy(candidate["lineage"]),
            "candidate_sha256": candidate_sha256,
        },
        "retrieval": projection["retrieval"],
        "deterministic_metrics": copy.deepcopy(dict(deterministic)),
        "semantic_evaluation": {
            "judge_model": JUDGE_MODEL,
            "rubric_version": JUDGE_RUBRIC,
            "score": final_score,
            "verdict": final["judge_decision"],
            "final_judge_role": final["judge_role"],
            "component_scores": copy.deepcopy(final["scores"]),
            "confidence": final["confidence"],
            "rationale": final["rationale"],
            "critical_flags": copy.deepcopy(final["critical_flags"]),
            "matched_key_point_ids": copy.deepcopy(final["matched_key_point_ids"]),
            "expected_behavior": final["expected_behavior"],
            "observed_status": final["observed_status"],
            "follow_up_success": final["follow_up_success"],
            "safe_abstention": final["safe_abstention"],
            "workflow": copy.deepcopy(dict(workflow)),
            "final_judgment": copy.deepcopy(dict(final)),
            "judgment_history": [copy.deepcopy(dict(row)) for row in history],
        },
        "source_transcript": copy.deepcopy(candidate),
        "provenance": {
            "source_case_sha256": source_case.source_sha256,
            "candidate_sha256": candidate_sha256,
            "deterministic_case_sha256": deterministic_sha256,
            "semantic_score_sha256": semantic_score_sha256,
            "judge_input_sha256": final["judge_input_sha256"],
            "review_config_sha256": final["review_config_sha256"],
        },
    }


def _parser_records(
    ledger: SemanticLedger,
    parser_payload: Mapping[str, Any],
    parser_by_id: Mapping[str, Mapping[str, Any]],
    *,
    parser_rerun_sha256: str,
) -> list[dict[str, Any]]:
    ledger_rows = {
        case_id: row
        for case_id, row in ledger.suite.ledger_rows.items()
        if row.get("case_type") == "parser"
    }
    if set(ledger_rows) != set(parser_by_id):
        raise ValueError("local_mini131_performance_parser_ledger_mismatch")
    records: list[dict[str, Any]] = []
    for case_id in sorted(parser_by_id):
        source = ledger_rows[case_id]
        result = copy.deepcopy(dict(parser_by_id[case_id]))
        if result.get("passed") is not True:
            raise ValueError("local_mini131_performance_parser_failed")
        records.append(
            {
                "schema_version": RECORD_SCHEMA_VERSION,
                "case_id": case_id,
                "asset_type": "parser",
                "lane": "parser_regression",
                "purpose": "parser_regression",
                "difficulty": "not_applicable",
                "official": False,
                "gold_review_status": "not_applicable",
                "evaluation_status": {
                    "record_complete": True,
                    "quality_pass": True,
                    "gold_approved": False,
                    "official_eligible": False,
                },
                "question": copy.deepcopy(source["question"]),
                "expected": copy.deepcopy(source["expected"]),
                "candidate": {
                    "model": "pinned-rhwp-parser",
                    "execution_profile": "mac_local_parser_rerun",
                    "status": "passed",
                    "answer": "현재 정본 파서 추출 및 인덱싱 회귀 검증 통과",
                    "chat": [],
                    "citations": [],
                    "selected_doc_ids": [],
                    "abstention_reason": None,
                    "error_code": None,
                    "execution_lineage": {"mode": "fresh_local_parser_rerun"},
                },
                "retrieval": {"retrieved_docs": [], "cited_docs": [], "evidence": []},
                "deterministic_metrics": result,
                "semantic_evaluation": None,
                "source_transcript": result,
                "provenance": {
                    "parser_rerun_sha256": parser_rerun_sha256,
                    "source_receipt_sha256": parser_payload.get("receipt_sha256"),
                },
            }
        )
    return records


def _numeric_leaves(value: Any, *, prefix: str = "") -> dict[str, float]:
    result: dict[str, float] = {}
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key in {"case_id", "lane", "status"}:
                continue
            nested_prefix = f"{prefix}.{key}" if prefix else str(key)
            result.update(_numeric_leaves(nested, prefix=nested_prefix))
    elif isinstance(value, bool):
        result[prefix] = float(value)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if math.isfinite(number):
            result[prefix] = number
    return result


def _metric_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values: dict[str, list[float]] = defaultdict(list)
    for record in records:
        for key, value in _numeric_leaves(record.get("deterministic_metrics", {})).items():
            values[key].append(value)
    return {
        key: {"eligible": len(items), "mean": round(fmean(items), 6)}
        for key, items in sorted(values.items())
    }


def _component_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values: dict[str, list[float]] = defaultdict(list)
    for record in records:
        semantic = record.get("semantic_evaluation")
        components = semantic.get("component_scores") if isinstance(semantic, Mapping) else None
        if not isinstance(components, Mapping):
            continue
        for field in COMPONENT_FIELDS:
            value = components.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values[field].append(float(value))
    return {
        field: {
            "eligible": len(values.get(field, [])),
            "mean": (
                round(fmean(values[field]), 6) if values.get(field) else None
            ),
        }
        for field in COMPONENT_FIELDS
    }


def _behavior_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in ("follow_up_success", "safe_abstention"):
        values = [
            bool(row["semantic_evaluation"][field])
            for row in records
            if isinstance(row.get("semantic_evaluation"), Mapping)
            and isinstance(row["semantic_evaluation"].get(field), bool)
        ]
        result[field] = {
            "eligible": len(values),
            "passed": sum(values),
            "rate": round(sum(values) / len(values), 6) if values else None,
        }
    return result


def _group_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rag = [row for row in records if row.get("asset_type") == "rag"]
    scores = [float(row["semantic_evaluation"]["score"]) for row in rag]
    decisions = Counter(str(row["semantic_evaluation"]["verdict"]) for row in rag)
    statuses = Counter(str(row["candidate"]["status"]) for row in rag)
    return {
        "count": len(records),
        "rag_count": len(rag),
        "parser_count": len(records) - len(rag),
        "status": dict(sorted(statuses.items())),
        "accepted": decisions["accepted"],
        "rejected": decisions["rejected"],
        "acceptance_rate": (
            round(decisions["accepted"] / len(rag), 6) if rag else None
        ),
        "runtime_error_rate": (
            round(statuses["error"] / len(rag), 6) if rag else None
        ),
        "mean_semantic_score": round(fmean(scores), 6) if scores else None,
        "components": _component_summary(rag),
        "behavior_checks": _behavior_summary(rag),
        "deterministic_metrics": _metric_summary(rag),
    }


def _partition_summary(
    records: Sequence[Mapping[str, Any]], key: str
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record[key])].append(record)
    return {name: _group_summary(grouped[name]) for name in sorted(grouped)}


def build_summary(
    records: Sequence[Mapping[str, Any]],
    *,
    deterministic_report: Mapping[str, Any],
    semantic_report: Mapping[str, Any],
) -> dict[str, Any]:
    rag = [row for row in records if row.get("asset_type") == "rag"]
    parser = [row for row in records if row.get("asset_type") == "parser"]
    difficulty_counts = Counter(str(row["difficulty"]) for row in rag)
    if dict(difficulty_counts) != EXPECTED_DIFFICULTY_COUNTS:
        raise ValueError("local_mini131_performance_difficulty_partition_mismatch")
    overall = _group_summary(records)
    if (
        overall["mean_semantic_score"]
        != semantic_report.get("metrics", {}).get("mean_semantic_score")
        or overall["accepted"] != semantic_report.get("counts", {}).get("accepted")
        or overall["rejected"] != semantic_report.get("counts", {}).get("rejected")
    ):
        raise ValueError("local_mini131_performance_semantic_aggregate_mismatch")
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "suite_id": SUITE_ID,
        "official": False,
        "evaluation_tier": "provisional_non_official",
        "gold_review_status": "draft",
        "evaluation_status": {
            "record_complete": True,
            "quality_pass": False,
            "gold_approved": False,
            "official_eligible": False,
        },
        "overall": overall,
        "counts": {
            "total_assets": len(records),
            "rag": len(rag),
            "parser": len(parser),
            "parser_passed": sum(
                bool(row["deterministic_metrics"].get("passed")) for row in parser
            ),
            "difficulty": dict(sorted(difficulty_counts.items())),
        },
        "by_difficulty": _partition_summary(rag, "difficulty"),
        "by_purpose": _partition_summary(records, "purpose"),
        "by_lane": _partition_summary(records, "lane"),
        "failure_case_ids": {
            "runtime_error": [
                str(row["case_id"])
                for row in rag
                if row["candidate"]["status"] == "error"
            ],
            "semantic_rejected": [
                str(row["case_id"])
                for row in rag
                if row["semantic_evaluation"]["verdict"] == "rejected"
            ],
        },
        "frozen_aggregate_metrics": copy.deepcopy(
            deterministic_report.get("metrics", {})
        ),
        "limitations": {
            "human_gold_approved": False,
            "held_out_executed": False,
            "live_gcp_executed": False,
            "candidate_runtime": "mac_ollama_numpy",
            "judge_is_gold": False,
            "unreported_frozen_metrics_remain": True,
        },
    }


def validate_performance_evaluation(
    report: Mapping[str, Any], *, require_complete: bool = True
) -> None:
    records = report.get("records")
    summary = report.get("summary")
    if (
        report.get("schema_version") != REPORT_SCHEMA_VERSION
        or not isinstance(records, list)
        or not isinstance(summary, Mapping)
        or summary.get("schema_version") != SUMMARY_SCHEMA_VERSION
    ):
        raise ValueError("local_mini131_performance_report_invalid")
    case_ids: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping) or record.get("schema_version") != RECORD_SCHEMA_VERSION:
            raise ValueError("local_mini131_performance_record_invalid")
        case_id = record.get("case_id")
        if not isinstance(case_id, str) or not case_id or case_id in case_ids:
            raise ValueError("local_mini131_performance_record_identity_invalid")
        case_ids.add(case_id)
        if not isinstance(record.get("question"), str) or record.get("expected") is None:
            raise ValueError("local_mini131_performance_gold_record_invalid")
        candidate = record.get("candidate")
        if not isinstance(candidate, Mapping) or not isinstance(candidate.get("answer"), str):
            raise ValueError("local_mini131_performance_candidate_record_invalid")
        if record.get("asset_type") == "rag":
            semantic = record.get("semantic_evaluation")
            retrieval = record.get("retrieval")
            if (
                record.get("difficulty") not in DIFFICULTIES
                or candidate.get("status") not in RAG_STATUSES
                or not isinstance(retrieval, Mapping)
                or not isinstance(retrieval.get("evidence"), list)
                or not isinstance(record.get("deterministic_metrics"), Mapping)
                or not isinstance(semantic, Mapping)
                or semantic.get("verdict") not in FINAL_DECISIONS
                or not isinstance(semantic.get("score"), (int, float))
                or not isinstance(semantic.get("rationale"), str)
                or not semantic["rationale"].strip()
            ):
                raise ValueError("local_mini131_performance_rag_record_invalid")
        elif record.get("asset_type") == "parser":
            if (
                record.get("difficulty") != "not_applicable"
                or record.get("semantic_evaluation") is not None
                or record.get("deterministic_metrics", {}).get("passed") is not True
            ):
                raise ValueError("local_mini131_performance_parser_record_invalid")
        else:
            raise ValueError("local_mini131_performance_asset_type_invalid")
    if require_complete:
        asset_counts = Counter(str(row["asset_type"]) for row in records)
        if (
            len(records) != 131
            or asset_counts != Counter({"rag": 129, "parser": 2})
            or summary.get("counts", {}).get("total_assets") != 131
            or summary.get("counts", {}).get("difficulty")
            != EXPECTED_DIFFICULTY_COUNTS
        ):
            raise ValueError("local_mini131_performance_record_count_mismatch")


def build_performance_evaluation(
    ledger: SemanticLedger,
    decision_paths: Sequence[Path],
) -> dict[str, Any]:
    deterministic_report, deterministic_by_id = _load_deterministic_rows(ledger)
    semantic_report, semantic_by_id = _load_semantic_report(ledger)
    finals, histories, workflows = resolve_final_judgments(ledger, decision_paths)
    semantic_score_sha256 = sha256_file(ledger.paths.semantic_score)
    records: list[dict[str, Any]] = []
    for source_case in sorted(ledger.suite.cases, key=lambda row: (row.lane, row.case_id)):
        case_id = source_case.case_id
        final = finals[case_id]
        canonical = semantic_by_id[case_id]
        if (
            canonical.get("lane") != source_case.lane
            or canonical.get("semantic_score") != _judgment_semantic_score(final)
            or canonical.get("final_decision") != final.get("judge_decision")
            or canonical.get("final_judge_role") != final.get("judge_role")
            or canonical.get("final_judgment_id") != final.get("judgment_id")
            or canonical.get("workflow", {}).get("secondary_required")
            != workflows[case_id]["secondary_required"]
            or canonical.get("workflow", {}).get("adjudicator_required")
            != workflows[case_id]["adjudicator_required"]
        ):
            raise ValueError("local_mini131_performance_semantic_binding_mismatch")
        records.append(
            _rag_record(
                ledger,
                source_case,
                deterministic=deterministic_by_id[case_id],
                final=final,
                history=histories[case_id],
                workflow=workflows[case_id],
                semantic_score_sha256=semantic_score_sha256,
            )
        )
    parser_payload, parser_by_id = _load_parser_results(ledger)
    parser_rerun_path = ledger.paths.candidates.with_name("parser-rerun.json")
    parser_rerun_sha256 = sha256_file(parser_rerun_path)
    records.extend(
        _parser_records(
            ledger,
            parser_payload,
            parser_by_id,
            parser_rerun_sha256=parser_rerun_sha256,
        )
    )
    summary = build_summary(
        records,
        deterministic_report=deterministic_report,
        semantic_report=semantic_report,
    )
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "suite_id": SUITE_ID,
        "official": False,
        "records": records,
        "summary": summary,
        "source_hashes": {
            "candidates_sha256": sha256_file(ledger.paths.candidates),
            "deterministic_score_sha256": sha256_file(
                ledger.paths.deterministic_score
            ),
            "semantic_score_sha256": semantic_score_sha256,
            "review_history_sha256": semantic_report["review_history_sha256"],
            "parser_rerun_sha256": parser_rerun_sha256,
        },
    }
    validate_performance_evaluation(report)
    return report


def _json_pre(value: Any) -> str:
    return html.escape(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _table_rows(items: Mapping[str, Mapping[str, Any]]) -> str:
    rows: list[str] = []
    for name, item in items.items():
        rows.append(
            "<tr>"
            f"<th>{html.escape(name)}</th>"
            f"<td>{item.get('count', 0)}</td>"
            f"<td>{item.get('accepted', 0)}</td>"
            f"<td>{item.get('rejected', 0)}</td>"
            f"<td>{html.escape(str(item.get('mean_semantic_score')))}</td>"
            f"<td>{html.escape(str(item.get('acceptance_rate')))}</td>"
            "</tr>"
        )
    return "".join(rows)


def _component_rows(items: Mapping[str, Mapping[str, Any]]) -> str:
    return "".join(
        "<tr>"
        f"<th>{html.escape(name)}</th>"
        f"<td>{item.get('eligible', 0)}</td>"
        f"<td>{html.escape(str(item.get('mean')))}</td>"
        "</tr>"
        for name, item in items.items()
    )


def _behavior_rows(items: Mapping[str, Mapping[str, Any]]) -> str:
    return "".join(
        "<tr>"
        f"<th>{html.escape(name)}</th>"
        f"<td>{item.get('eligible', 0)}</td>"
        f"<td>{item.get('passed', 0)}</td>"
        f"<td>{html.escape(str(item.get('rate')))}</td>"
        "</tr>"
        for name, item in items.items()
    )


def render_html(report: Mapping[str, Any]) -> str:
    validate_performance_evaluation(report, require_complete=False)
    records = report["records"]
    summary = report["summary"]
    overall = summary["overall"]
    cards: list[str] = []
    for record in records:
        candidate = record["candidate"]
        semantic = record.get("semantic_evaluation")
        verdict = semantic["verdict"] if isinstance(semantic, Mapping) else "parser_passed"
        score = semantic["score"] if isinstance(semantic, Mapping) else None
        rationale = semantic["rationale"] if isinstance(semantic, Mapping) else "ETL deterministic PASS"
        components = semantic["component_scores"] if isinstance(semantic, Mapping) else None
        history = semantic["judgment_history"] if isinstance(semantic, Mapping) else []
        search = " ".join(
            str(value)
            for value in (
                record["case_id"],
                record["question"],
                candidate["answer"],
                record["lane"],
                record["purpose"],
            )
        ).lower()
        cards.append(
            f'''<details class="case" data-lane="{html.escape(str(record['lane']), quote=True)}" data-purpose="{html.escape(str(record['purpose']), quote=True)}" data-difficulty="{html.escape(str(record['difficulty']), quote=True)}" data-status="{html.escape(str(candidate['status']), quote=True)}" data-verdict="{html.escape(str(verdict), quote=True)}" data-search="{html.escape(search, quote=True)}">
<summary><code>{html.escape(str(record['case_id']))}</code><span>{html.escape(str(record['difficulty']))}</span><span>{html.escape(str(record['purpose']))}</span><span>{html.escape(str(candidate['status']))}</span><strong>{html.escape(str(verdict))}</strong><b>{'—' if score is None else f'{float(score):.2f}'}</b></summary>
<div class="grid"><section><h3>골든 질문</h3><pre>{html.escape(str(record['question']))}</pre></section><section><h3>정답 기준</h3><pre>{_json_pre(record['expected'])}</pre></section></div>
<section><h3>로컬 Qwen 실제 답변</h3><pre>{html.escape(str(candidate['answer']))}</pre></section>
<div class="grid"><section><h3>구성 점수</h3><pre>{_json_pre(components)}</pre></section><section><h3>최종 판정 사유</h3><pre>{html.escape(str(rationale))}</pre></section></div>
<details><summary>결정론 지표</summary><pre>{_json_pre(record['deterministic_metrics'])}</pre></details>
<details><summary>검색·인용·판정 근거</summary><pre>{_json_pre(record['retrieval'])}</pre></details>
<details><summary>판정 이력 ({len(history)})</summary><pre>{_json_pre(history)}</pre></details>
<details><summary>실행 원장·provenance</summary><pre>{_json_pre({'source_transcript': record['source_transcript'], 'provenance': record['provenance']})}</pre></details>
</details>'''
        )
    lane_options = "".join(
        f'<option value="{html.escape(key, quote=True)}">{html.escape(key)}</option>'
        for key in summary["by_lane"]
    )
    purpose_options = "".join(
        f'<option value="{html.escape(key, quote=True)}">{html.escape(key)}</option>'
        for key in summary["by_purpose"]
    )
    return f'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Local Qwen Mini131 골든셋 성능평가</title><style>
:root{{font-family:Inter,system-ui,sans-serif;line-height:1.55;color-scheme:light dark}}body{{max-width:1440px;margin:auto;padding:24px}}h1{{margin-bottom:4px}}.sub{{color:GrayText;margin-top:0}}.notice{{border:1px solid #d18b18;border-radius:10px;padding:12px;background:color-mix(in srgb,#d18b18 10%,Canvas)}}.metrics,.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px;margin:16px 0}}.metric,section,details.case{{border:1px solid GrayText;border-radius:10px;padding:11px}}.metric strong{{display:block;font-size:1.5rem}}table{{width:100%;border-collapse:collapse;margin:12px 0}}th,td{{padding:8px;border-bottom:1px solid GrayText;text-align:right}}th:first-child{{text-align:left}}.controls{{position:sticky;top:0;z-index:2;display:flex;gap:8px;flex-wrap:wrap;padding:10px;background:Canvas;border:1px solid GrayText;border-radius:10px}}input,select{{font:inherit;padding:7px}}input{{flex:1;min-width:260px}}details.case{{margin:10px 0}}details.case>summary{{display:flex;gap:8px;align-items:center;flex-wrap:wrap;cursor:pointer}}details.case>summary strong{{margin-left:auto}}details.case>summary span{{border:1px solid GrayText;border-radius:999px;padding:2px 7px;font-size:.8rem}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:color-mix(in srgb,CanvasText 7%,Canvas);padding:10px;border-radius:7px}}[hidden]{{display:none!important}}
</style></head><body>
<h1>Local Qwen Mini131 골든셋 성능평가</h1><p class="sub">qwen3.8:27b-mlx · KURE-v1 · fresh gpt-5.6-sol judge · 2026-09-01</p>
<aside class="notice"><strong>잠정 성능평가</strong> 129개 RAG 답변과 parser 2건은 모두 기록·채점됐지만, 골드는 아직 사람 승인 전이며 이 결과는 Mac Ollama/NumPy 실행입니다. 공식 GCP·held-out·human-approved 점수가 아닙니다.</aside>
<div class="metrics"><div class="metric">전체 자산<strong>{summary['counts']['total_assets']}</strong></div><div class="metric">RAG / parser<strong>{summary['counts']['rag']} / {summary['counts']['parser']}</strong></div><div class="metric">평균 의미점수<strong>{float(overall['mean_semantic_score']):.2f}</strong></div><div class="metric">승인 / 반려<strong>{overall['accepted']} / {overall['rejected']}</strong></div><div class="metric">답변 / 기권 / 오류<strong>{overall['status'].get('answered',0)} / {overall['status'].get('abstained',0)} / {overall['status'].get('error',0)}</strong></div></div>
<h2>채점 구성요소</h2><table><thead><tr><th>요소</th><th>적용 문항</th><th>평균</th></tr></thead><tbody>{_component_rows(overall['components'])}</tbody></table>
<h2>행동 검증</h2><table><thead><tr><th>검증</th><th>적용 문항</th><th>통과</th><th>통과율</th></tr></thead><tbody>{_behavior_rows(overall['behavior_checks'])}</tbody></table>
<h2>난이도별</h2><table><thead><tr><th>난이도</th><th>문항</th><th>승인</th><th>반려</th><th>평균점수</th><th>승인율</th></tr></thead><tbody>{_table_rows(summary['by_difficulty'])}</tbody></table>
<h2>평가 목적별</h2><table><thead><tr><th>목적</th><th>문항</th><th>승인</th><th>반려</th><th>평균점수</th><th>승인율</th></tr></thead><tbody>{_table_rows(summary['by_purpose'])}</tbody></table>
<h2>문항별 상세</h2><div class="controls"><input id="search" type="search" placeholder="질문·답변·ID 검색"><select id="difficulty"><option value="">모든 난이도</option><option>easy</option><option>medium</option><option>hard</option><option>not_applicable</option></select><select id="lane"><option value="">모든 lane</option>{lane_options}</select><select id="purpose"><option value="">모든 목적</option>{purpose_options}</select><select id="verdict"><option value="">모든 판정</option><option>accepted</option><option>rejected</option><option>parser_passed</option></select><span id="visible"></span></div>
<div id="cases">{''.join(cards)}</div>
<script>const q=id=>document.getElementById(id);const cards=[...document.querySelectorAll('.case')];function filter(){{let n=0;for(const c of cards){{const ok=(!q('search').value||c.dataset.search.includes(q('search').value.toLowerCase()))&&(!q('difficulty').value||c.dataset.difficulty===q('difficulty').value)&&(!q('lane').value||c.dataset.lane===q('lane').value)&&(!q('purpose').value||c.dataset.purpose===q('purpose').value)&&(!q('verdict').value||c.dataset.verdict===q('verdict').value);c.hidden=!ok;if(ok)n++}}q('visible').textContent=`${{n}} / ${{cards.length}}`;}}for(const id of ['search','difficulty','lane','purpose','verdict'])q(id).addEventListener('input',filter);filter();</script>
</body></html>'''


def _private_boundary(path: Path) -> Path:
    absolute = path.resolve(strict=False)
    parts = absolute.parts
    boundary: int | None = None
    for index in range(1, len(parts)):
        if parts[index - 1 : index + 1] == ("evaluation", "private"):
            boundary = index
    if boundary is None:
        raise ValueError("local_mini131_performance_output_not_private")
    root = Path(*parts[: boundary + 1])
    for parent in (root, *absolute.parents):
        if parent == root.parent:
            break
        if parent.exists() and parent.is_symlink():
            raise ValueError("local_mini131_performance_output_symlink_forbidden")
    return root


def _atomic_private_text(path: Path, content: str) -> None:
    _private_boundary(path)
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise ValueError("local_mini131_performance_output_invalid")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ValueError("local_mini131_performance_output_mode_invalid")


def _atomic_public_json(path: Path, value: Mapping[str, Any]) -> None:
    absolute = path.resolve(strict=False)
    if not any(
        absolute.parts[index - 1 : index + 1] == ("evaluation", "baselines")
        for index in range(1, len(absolute.parts))
    ):
        raise ValueError("local_mini131_performance_receipt_path_invalid")
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise ValueError("local_mini131_performance_receipt_path_invalid")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            json.dump(dict(value), output, ensure_ascii=False, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        path.chmod(0o644)
    finally:
        temporary.unlink(missing_ok=True)


def content_free_receipt(
    report: Mapping[str, Any], artifact_hashes: Mapping[str, str]
) -> dict[str, Any]:
    summary = report["summary"]
    safe_hashes: dict[str, str] = {}
    for name, digest in artifact_hashes.items():
        if (
            not re.fullmatch(r"[a-z][a-z0-9_]*_sha256", name)
            or not isinstance(digest, str)
            or not SHA256_RE.fullmatch(digest)
        ):
            raise ValueError("local_mini131_performance_public_hash_invalid")
        safe_hashes[name] = digest
    counts = summary["counts"]
    evaluation_status = summary["evaluation_status"]
    limitations = summary["limitations"]
    for key in (
        "record_complete",
        "quality_pass",
        "gold_approved",
        "official_eligible",
    ):
        if not isinstance(evaluation_status.get(key), bool):
            raise ValueError("local_mini131_performance_public_status_invalid")
    if (
        limitations.get("candidate_runtime") != "mac_ollama_numpy"
        or any(
            not isinstance(limitations.get(key), bool)
            for key in (
                "human_gold_approved",
                "held_out_executed",
                "live_gcp_executed",
                "judge_is_gold",
                "unreported_frozen_metrics_remain",
            )
        )
    ):
        raise ValueError("local_mini131_performance_public_limitations_invalid")
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "artifact_role": "per_question_performance_evaluation_receipt",
        "suite_id": SUITE_ID,
        "official": False,
        "passed": False,
        "evaluation_tier": "provisional_non_official",
        "gold_review_status": "draft",
        "evaluation_status": {
            key: bool(evaluation_status[key])
            for key in (
                "record_complete",
                "quality_pass",
                "gold_approved",
                "official_eligible",
            )
        },
        "candidate": {
            "generator": "qwen3.8:27b-mlx",
            "embedding": "nlpai-lab/KURE-v1",
            "execution_profile": "mac_local_equivalent",
        },
        "judge": {"model": JUDGE_MODEL, "rubric_version": JUDGE_RUBRIC},
        "counts": {
            "total_assets": int(counts["total_assets"]),
            "rag": int(counts["rag"]),
            "parser": int(counts["parser"]),
            "parser_passed": int(counts["parser_passed"]),
            "difficulty": {
                level: int(counts["difficulty"][level]) for level in DIFFICULTIES
            },
        },
        "metrics": {
            "overall": _public_group_summary(summary["overall"]),
            "by_difficulty": _public_partition(
                summary["by_difficulty"], set(DIFFICULTIES)
            ),
            "by_purpose": _public_partition(
                summary["by_purpose"], PUBLIC_PURPOSES
            ),
            "by_lane": _public_partition(summary["by_lane"], PUBLIC_LANES),
        },
        "artifact_hashes": dict(sorted(safe_hashes.items())),
        "limitations": {
            "human_gold_approved": bool(limitations["human_gold_approved"]),
            "held_out_executed": bool(limitations["held_out_executed"]),
            "live_gcp_executed": bool(limitations["live_gcp_executed"]),
            "candidate_runtime": str(limitations["candidate_runtime"]),
            "judge_is_gold": bool(limitations["judge_is_gold"]),
            "unreported_frozen_metrics_remain": bool(
                limitations["unreported_frozen_metrics_remain"]
            ),
        },
        "privacy": {
            "contains_case_ids": False,
            "contains_questions": False,
            "contains_expected_answers": False,
            "contains_candidate_answers": False,
            "contains_evidence": False,
            "contains_judge_rationales": False,
            "contains_private_paths": False,
            "private_artifacts_tracked": False,
        },
    }
    _validate_content_free_receipt(receipt)
    return receipt


def _public_metric_stats(value: Mapping[str, Any]) -> dict[str, Any]:
    eligible = value.get("eligible")
    mean = value.get("mean")
    if (
        not isinstance(eligible, int)
        or isinstance(eligible, bool)
        or eligible < 0
        or (
            mean is not None
            and (
                not isinstance(mean, (int, float))
                or isinstance(mean, bool)
                or not math.isfinite(float(mean))
            )
        )
    ):
        raise ValueError("local_mini131_performance_public_metric_invalid")
    return {"eligible": eligible, "mean": mean}


def _public_optional_number(
    value: Any, *, minimum: float | None = None, maximum: float | None = None
) -> int | float | None:
    if value is None:
        return None
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        raise ValueError("local_mini131_performance_public_metric_invalid")
    number = float(value)
    if (minimum is not None and number < minimum) or (
        maximum is not None and number > maximum
    ):
        raise ValueError("local_mini131_performance_public_metric_invalid")
    return value


def _public_group_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    components = value["components"]
    behavior = value["behavior_checks"]
    deterministic = value["deterministic_metrics"]
    safe_deterministic: dict[str, Any] = {}
    for name, metric in deterministic.items():
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[a-z][a-z0-9_.]*", name)
            or any(
                token in name.split(".")
                for token in (
                    "answer",
                    "blind_id",
                    "case_id",
                    "evidence",
                    "expected",
                    "private",
                    "question",
                    "rationale",
                )
            )
            or not isinstance(metric, Mapping)
        ):
            raise ValueError("local_mini131_performance_public_metric_invalid")
        safe_deterministic[name] = _public_metric_stats(metric)
    safe_behavior: dict[str, Any] = {}
    for name in ("follow_up_success", "safe_abstention"):
        item = behavior[name]
        eligible = item.get("eligible")
        passed = item.get("passed")
        rate = item.get("rate")
        if (
            not isinstance(eligible, int)
            or isinstance(eligible, bool)
            or not isinstance(passed, int)
            or isinstance(passed, bool)
            or not 0 <= passed <= eligible
            or (
                rate is not None
                and (
                    not isinstance(rate, (int, float))
                    or isinstance(rate, bool)
                    or not math.isfinite(float(rate))
                    or not 0 <= float(rate) <= 1
                )
            )
        ):
            raise ValueError("local_mini131_performance_public_metric_invalid")
        safe_behavior[name] = {
            "eligible": eligible,
            "passed": passed,
            "rate": rate,
        }
    status = value["status"]
    return {
        "count": int(value["count"]),
        "rag_count": int(value["rag_count"]),
        "parser_count": int(value["parser_count"]),
        "status": {
            key: int(status.get(key, 0)) for key in ("answered", "abstained", "error")
        },
        "accepted": int(value["accepted"]),
        "rejected": int(value["rejected"]),
        "acceptance_rate": _public_optional_number(
            value["acceptance_rate"], minimum=0, maximum=1
        ),
        "runtime_error_rate": _public_optional_number(
            value["runtime_error_rate"], minimum=0, maximum=1
        ),
        "mean_semantic_score": _public_optional_number(
            value["mean_semantic_score"], minimum=0, maximum=100
        ),
        "components": {
            field: _public_metric_stats(components[field])
            for field in COMPONENT_FIELDS
        },
        "behavior_checks": safe_behavior,
        "deterministic_metrics": dict(sorted(safe_deterministic.items())),
    }


def _public_partition(
    value: Mapping[str, Mapping[str, Any]], expected: set[str]
) -> dict[str, Any]:
    if set(value) != expected:
        raise ValueError("local_mini131_performance_public_partition_invalid")
    return {name: _public_group_summary(value[name]) for name in sorted(expected)}


def _validate_content_free_receipt(value: Any) -> None:
    forbidden = {
        "answer",
        "answers",
        "blind_id",
        "case_id",
        "case_ids",
        "evidence",
        "expected",
        "private_path",
        "question",
        "questions",
        "rationale",
    }
    if isinstance(value, Mapping):
        if forbidden.intersection(str(key) for key in value):
            raise ValueError("local_mini131_performance_public_content_forbidden")
        for nested in value.values():
            _validate_content_free_receipt(nested)
    elif isinstance(value, list):
        for nested in value:
            _validate_content_free_receipt(nested)


def write_performance_outputs(
    report: Mapping[str, Any], paths: PerformancePaths
) -> dict[str, Any]:
    validate_performance_evaluation(report)
    records_text = "".join(canonical_json(row) + "\n" for row in report["records"])
    summary_text = json.dumps(
        report["summary"], ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    html_text = render_html(report)
    _atomic_private_text(paths.records, records_text)
    _atomic_private_text(paths.summary, summary_text)
    _atomic_private_text(paths.html, html_text)
    artifact_hashes = {
        "private_records_sha256": sha256_file(paths.records),
        "private_summary_sha256": sha256_file(paths.summary),
        "private_html_sha256": sha256_file(paths.html),
        **copy.deepcopy(report["source_hashes"]),
    }
    receipt = content_free_receipt(report, artifact_hashes)
    _atomic_public_json(paths.receipt, receipt)
    return receipt


def run_performance_evaluation(
    *,
    repo_root: Path,
    config_path: Path,
    decision_paths: Sequence[Path] | None = None,
) -> dict[str, Any]:
    suite = verify_suite(repo_root=repo_root, config_path=config_path)
    ledger = load_ledger(suite)
    decisions = list(decision_paths) if decision_paths is not None else default_decision_paths(ledger)
    report = build_performance_evaluation(ledger, decisions)
    return write_performance_outputs(report, default_paths(suite))


def _safe_error(error: BaseException) -> str:
    code = str(error)
    return code if re.fullmatch(r"[a-z][a-z0-9_]{0,127}", code) else "local_mini131_performance_failed"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build private local Mini131 per-question performance report")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path)
    parser.add_argument("--decision", type=Path, action="append")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    config_path = (
        args.config.resolve()
        if args.config is not None
        else repo_root / DEFAULT_CONFIG
    )
    try:
        receipt = run_performance_evaluation(
            repo_root=repo_root,
            config_path=config_path,
            decision_paths=args.decision,
        )
        print(
            canonical_json(
                {
                    "schema_version": receipt["schema_version"],
                    "passed": True,
                    "counts": receipt["counts"],
                    "overall": receipt["metrics"]["overall"],
                    "receipt_sha256": sha256_file(
                        default_paths(
                            verify_suite(repo_root=repo_root, config_path=config_path)
                        ).receipt
                    ),
                    "private_content_exposed": False,
                }
            )
        )
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(
            canonical_json(
                {
                    "schema_version": RECEIPT_SCHEMA_VERSION,
                    "passed": False,
                    "error": {"code": _safe_error(error)},
                    "private_content_exposed": False,
                }
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
