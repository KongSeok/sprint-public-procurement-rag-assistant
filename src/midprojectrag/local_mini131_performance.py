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
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from statistics import fmean, median
from typing import Any

from midprojectrag.ingest.common import (
    canonical_json,
    read_jsonl,
    sha256_file,
    sha256_text,
)
from midprojectrag.evaluation import EXPECTED_METRIC_KEYS
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
from midprojectrag.mini131_report import (
    PRIMARY_CATEGORY_ORDER,
    PURPOSE_DEFINITIONS,
    SCENARIO_PURPOSES,
    VISUAL_SUBGROUP_DEFINITIONS,
    validate_records as validate_api_case_records,
)


RECORD_SCHEMA_VERSION = "local-mini131-golden-evaluation-record.v1"
SUMMARY_SCHEMA_VERSION = "local-mini131-golden-performance-summary.v2"
REPORT_SCHEMA_VERSION = "local-mini131-golden-performance-report.v2"
RECEIPT_SCHEMA_VERSION = "local-mini131-golden-performance-receipt.v2"
PERFORMANCE_DIRNAME = "performance-v1"
RECORDS_FILENAME = "golden-evaluation-records.jsonl"
SUMMARY_FILENAME = "golden-performance-summary.json"
HTML_FILENAME = "golden-performance-report.html"
RECEIPT_FILENAME = "mac-local-equivalent-performance-receipt.json"
DIFFICULTIES = ("easy", "medium", "hard")
EXPECTED_DIFFICULTY_COUNTS = {"easy": 41, "medium": 48, "hard": 40}
PUBLIC_PURPOSES = {
    "clause_fact_regression",
    "conditional_all_list",
    "corpus_analytics",
    "follow_up",
    "gold_source_alignment",
    "multi_doc_compare",
    "parser_regression",
    "single_doc",
    "unknown",
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
API_BASELINE_ID = "mini131-bundle-v1"
API_RECEIPT_RELATIVE_PATH = Path("evaluation/baselines/mini131-bundle-v1/receipt.json")
API_RECEIPT_SHA256 = "dabae64574285bd0efc7bfd31a280ba573ca375f38037a713abae261c36b2c2b"
API_CASE_RECORDS_SHA256 = "6d8b0cb9c1b393ad5b7bfc749e6f69bc2e3dbcff9f759860296d3ad4948fa87e"
API_GENERATOR = "gpt-5-mini"
LOCAL_GENERATOR = "qwen3.8:27b-mlx"
LOCAL_EMBEDDING = "nlpai-lab/KURE-v1"
PRIMARY_CATEGORY_KEYS = tuple(PRIMARY_CATEGORY_ORDER)
SCENARIO_KEYS = tuple(SCENARIO_PURPOSES)
VISUAL_SUBGROUP_KEYS = tuple(VISUAL_SUBGROUP_DEFINITIONS)
PUBLIC_COMMON_UNAVAILABLE_REASONS = {
    "metric_not_captured_by_frozen_local_run",
    "metric_not_applicable_to_local_candidate",
    "mac_local_equivalent_run_did_not_capture_gcp_gpu_telemetry",
    "local_candidate_response_not_normalized_to_api_contract",
}
PUBLIC_DETERMINISTIC_METRIC_NAMES = {
    "analytics_calculation.case_passed",
    "analytics_calculation.comparison_count",
    "analytics_calculation.comparison_match_rate",
    "analytics_calculation.exact_comparison_count",
    "analytics_calculation.exact_comparison_match_rate",
    "analytics_calculation.exact_matched_comparison_count",
    "analytics_calculation.matched_comparison_count",
    "analytics_calculation.tolerance_comparison_count",
    "analytics_calculation.tolerance_comparison_match_rate",
    "analytics_calculation.tolerance_matched_comparison_count",
    "citation_valid",
    "document_recall_at_1",
    "document_recall_at_5",
    "document_recall_at_10",
    "expected_behavior_match",
    "mrr_at_10",
    "set_count_match",
    "set_exact_match",
    "set_expected_count",
    "set_f1",
    "set_precision",
    "set_recall",
    "set_selected_count",
    "visual_retrieval.chunk_or_block.mrr_at_10",
    "visual_retrieval.chunk_or_block.recall_at_1",
    "visual_retrieval.chunk_or_block.recall_at_5",
    "visual_retrieval.chunk_or_block.recall_at_10",
    "visual_retrieval.chunk_or_block.target_count",
    "visual_retrieval.document.mrr_at_10",
    "visual_retrieval.document.recall_at_1",
    "visual_retrieval.document.recall_at_5",
    "visual_retrieval.document.recall_at_10",
    "visual_retrieval.document.target_count",
    "visual_retrieval.object.mrr_at_10",
    "visual_retrieval.object.recall_at_1",
    "visual_retrieval.object.recall_at_5",
    "visual_retrieval.object.recall_at_10",
    "visual_retrieval.object.target_count",
    "visual_retrieval.page.mrr_at_10",
    "visual_retrieval.page.recall_at_1",
    "visual_retrieval.page.recall_at_5",
    "visual_retrieval.page.recall_at_10",
    "visual_retrieval.page.target_count",
}
OBJECTIVE_COMPANION_KEYS = {
    "required_document_hit_count",
    "required_document_recall",
    "required_document_total",
    "set_exact_match_rate",
    "set_case_count",
    "set_macro_precision",
    "set_macro_recall",
    "set_macro_f1",
    "set_micro_precision",
    "set_micro_recall",
    "set_micro_f1",
    "set_true_positive_total",
    "set_false_positive_total",
    "set_false_negative_total",
    "visual_evidence_availability_rate",
    "visual_case_count",
    "visual_target_page",
    "visual_target_chunk",
    "visual_target_object_bridge",
    "analytics_numeric_evidence_availability_rate",
    "analytics_case_count",
    "analytics_deterministic_companion_case_count",
    "analytics_deterministic_companion_pass_count",
    "analytics_deterministic_companion_complete_rate",
    "analytics_deterministic_case_pass_count",
    "analytics_deterministic_case_pass_rate",
    "analytics_deterministic_field_count",
    "analytics_deterministic_field_pass_count",
    "analytics_deterministic_field_pass_rate",
    "analytics_numeric_evidence_field_count",
    "analytics_numeric_evidence_fields_per_case",
    "unknown_safe_abstention_pass_count",
    "unknown_case_count",
    "unknown_safe_abstention_rate",
}
EXPECTED_PURPOSE_COUNTS = {
    "single_doc": 10,
    "multi_doc_compare": 10,
    "follow_up": 10,
    "unknown": 10,
    "clause_fact_regression": 44,
    "conditional_all_list": 13,
    "gold_source_alignment": 12,
    "visual_table_figure": 10,
    "corpus_analytics": 10,
    "parser_regression": 2,
}
EXPECTED_PRIMARY_COUNTS = {
    "bid_rag_scenarios": 40,
    "clause_fact_regression": 44,
    "conditional_all_list": 13,
    "gold_source_alignment": 12,
    "visual_table_figure": 10,
    "corpus_analytics": 10,
    "parser_regression": 2,
}
EXPECTED_VISUAL_SUBGROUP_COUNTS = {
    "hwp_table": 3,
    "hwp_figure": 2,
    "pdf_table": 3,
    "pdf_figure": 2,
}


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
        return str(task_type)
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


def _api_display_mean(value: int | float | None) -> float | None:
    """Match the API report's conventional two-decimal, half-up score display."""

    if value is None:
        return None
    return float(
        Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )


def _partition_summary(
    records: Sequence[Mapping[str, Any]], key: str
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record[key])].append(record)
    return {name: _group_summary(grouped[name]) for name in sorted(grouped)}


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    return round(float(numerator) / float(denominator), 6) if denominator else None


def _required_doc_ids(record: Mapping[str, Any], *, nested_gold: bool = True) -> set[str]:
    expected = record.get("expected")
    if not isinstance(expected, Mapping):
        return set()
    values = expected.get("required_doc_ids")
    if not isinstance(values, list) and nested_gold:
        gold = expected.get("gold")
        values = gold.get("required_doc_ids") if isinstance(gold, Mapping) else None
    if not isinstance(values, list):
        return set()
    return {str(value) for value in values if isinstance(value, str) and value}


def _gold(record: Mapping[str, Any]) -> Mapping[str, Any]:
    expected = record.get("expected")
    gold = expected.get("gold") if isinstance(expected, Mapping) else None
    return gold if isinstance(gold, Mapping) else {}


def _ranked_retrieval(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    retrieval = record.get("retrieval")
    values = retrieval.get("retrieved_docs") if isinstance(retrieval, Mapping) else None
    if not isinstance(values, list):
        return []

    def rank_key(item: Mapping[str, Any]) -> int:
        rank = item.get("rank")
        return rank if isinstance(rank, int) and not isinstance(rank, bool) else 10**9

    return sorted(
        (item for item in values if isinstance(item, Mapping)),
        key=rank_key,
    )


def _ranked_doc_ids(record: Mapping[str, Any]) -> list[str]:
    result: list[str] = []
    for item in _ranked_retrieval(record):
        doc_id = item.get("doc_id")
        if isinstance(doc_id, str):
            result.append(doc_id)
    return result


def _retrieved_blocks(record: Mapping[str, Any], k: int) -> set[str]:
    result: set[str] = set()
    for item in _ranked_retrieval(record)[:k]:
        values = item.get("source_block_ids")
        if isinstance(values, list):
            result.update(value for value in values if isinstance(value, str))
    return result


def _dcg(relevances: Sequence[int]) -> float:
    return sum(
        relevance / math.log2(index + 2)
        for index, relevance in enumerate(relevances)
    )


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return round(float(ordered[rank - 1]), 6)


def _metric_entry(
    value: int | float | None,
    *,
    eligible: int,
    expected_eligible: int | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    available = value is not None
    if not available:
        eligible = 0
        expected_eligible = expected_eligible or 0
        reason = reason or "metric_not_captured_by_frozen_local_run"
    elif reason is not None:
        raise ValueError("local_mini131_performance_available_metric_reason_invalid")
    denominator = expected_eligible if expected_eligible is not None else eligible
    return {
        "value": value,
        "eligible": eligible,
        "coverage": _ratio(eligible, denominator) if denominator else 0.0,
        "available": available,
        "reason": reason,
    }


def _common_evaluation_metrics(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, dict[str, Any]]]:
    """Apply the API/common metric formulas to the shared Core40 cases only."""

    core = [
        row
        for row in records
        if row.get("asset_type") == "rag" and row.get("lane") == "core40"
    ]
    if len(core) != 40:
        raise ValueError("local_mini131_performance_common_metric_scope_invalid")
    k_values = (1, 3, 5, 10)
    doc_recalls: dict[int, list[float]] = {k: [] for k in k_values}
    block_recalls: dict[int, list[float]] = {k: [] for k in k_values}
    all_required: dict[int, list[float]] = {k: [] for k in k_values}
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    key_point_coverages: list[float] = []
    answer_components: dict[str, list[float]] = {
        key: []
        for key in (
            "correctness",
            "faithfulness",
            "factual_claim_coverage",
            "citation_validity",
        )
    }
    gold_citation_precisions: list[float] = []
    follow_up_successes: list[float] = []
    judgment_complete: list[float] = []
    task_success: dict[str, list[float]] = {key: [] for key in SCENARIO_KEYS}
    total_latencies: list[float] = []
    retrieval_latencies: list[float] = []
    generation_latencies: list[float] = []
    costs: list[float] = []
    runtime_errors = 0
    true_positive_abstain = 0
    false_positive_abstain = 0
    false_negative_abstain = 0
    answerable_cases = 0
    answerable_abstentions = 0
    safe_abstentions: list[float] = []

    for record in core:
        candidate = record["candidate"]
        semantic = record["semantic_evaluation"]
        purpose = str(record["purpose"])
        gold = _gold(record)
        actual_abstain = gold.get("decision") == "abstain"
        predicted_abstain = candidate.get("status") == "abstained"
        reason_matches = candidate.get("abstention_reason") == gold.get("abstain_reason")
        successful_abstain = bool(
            predicted_abstain
            and semantic.get("safe_abstention") is True
            and reason_matches
        )
        if actual_abstain:
            safe_abstentions.append(float(successful_abstain))
        if actual_abstain and successful_abstain:
            true_positive_abstain += 1
        elif not actual_abstain and predicted_abstain:
            false_positive_abstain += 1
        elif actual_abstain and not successful_abstain:
            false_negative_abstain += 1
        if not actual_abstain:
            answerable_cases += 1
            answerable_abstentions += int(predicted_abstain)
        runtime_errors += int(candidate.get("status") == "error")
        if purpose in task_success:
            successful_response = (
                successful_abstain
                if actual_abstain
                else candidate.get("status") == "answered"
            )
            task_success[purpose].append(float(successful_response))

        relevant_docs = _required_doc_ids(record)
        evidence_refs = gold.get("evidence_refs")
        evidence_refs = evidence_refs if isinstance(evidence_refs, list) else []
        relevant_blocks = {
            str(item["source_block_id"])
            for item in evidence_refs
            if isinstance(item, Mapping) and isinstance(item.get("source_block_id"), str)
        }
        ranked_docs = _ranked_doc_ids(record)
        if relevant_docs:
            for k in k_values:
                top_docs = set(ranked_docs[:k])
                doc_recalls[k].append(len(top_docs & relevant_docs) / len(relevant_docs))
                if purpose == "multi_doc_compare":
                    all_required[k].append(float(relevant_docs <= top_docs))
                if relevant_blocks:
                    block_recalls[k].append(
                        len(_retrieved_blocks(record, k) & relevant_blocks)
                        / len(relevant_blocks)
                    )
            first_rank = next(
                (
                    index + 1
                    for index, doc_id in enumerate(ranked_docs[:10])
                    if doc_id in relevant_docs
                ),
                None,
            )
            reciprocal_ranks.append(0.0 if first_rank is None else 1.0 / first_rank)
            seen: set[str] = set()
            relevances: list[int] = []
            for doc_id in ranked_docs[:10]:
                is_new = doc_id in relevant_docs and doc_id not in seen
                relevances.append(int(is_new))
                if is_new:
                    seen.add(doc_id)
            ideal_dcg = _dcg([1] * min(len(relevant_docs), 10))
            ndcgs.append(0.0 if ideal_dcg == 0 else _dcg(relevances) / ideal_dcg)

        required_points = gold.get("required_key_points")
        point_ids = {
            str(item["point_id"])
            for item in (required_points if isinstance(required_points, list) else [])
            if isinstance(item, Mapping) and isinstance(item.get("point_id"), str)
        }
        matched = {
            str(value)
            for value in semantic.get("matched_key_point_ids", [])
            if isinstance(value, str)
        }
        if point_ids:
            key_point_coverages.append(len(point_ids & matched) / len(point_ids))
        components = semantic.get("component_scores")
        if isinstance(components, Mapping):
            for field, values in answer_components.items():
                score = components.get(field)
                if isinstance(score, (int, float)) and not isinstance(score, bool):
                    values.append(float(score))
        if purpose == "follow_up" and isinstance(semantic.get("follow_up_success"), bool):
            follow_up_successes.append(float(semantic["follow_up_success"]))
        complete = (
            isinstance(semantic.get("safe_abstention"), bool)
            if actual_abstain
            else isinstance(components, Mapping)
            and all(
                isinstance(components.get(field), (int, float))
                and not isinstance(components.get(field), bool)
                for field in answer_components
            )
            and (
                purpose != "follow_up"
                or isinstance(semantic.get("follow_up_success"), bool)
            )
        )
        judgment_complete.append(float(complete))

        gold_pairs = {
            (item.get("doc_id"), item.get("source_block_id"))
            for item in evidence_refs
            if isinstance(item, Mapping)
            and isinstance(item.get("doc_id"), str)
            and isinstance(item.get("source_block_id"), str)
        }
        scored_citations: list[float] = []
        for citation in candidate.get("citations", []):
            if not isinstance(citation, Mapping) or not gold_pairs:
                continue
            citation_blocks = {
                value
                for value in citation.get("source_block_ids", [])
                if isinstance(value, str)
            }
            scored_citations.append(
                float(
                    any(
                        (citation.get("doc_id"), block_id) in gold_pairs
                        for block_id in citation_blocks
                    )
                )
            )
        if scored_citations:
            gold_citation_precisions.append(fmean(scored_citations))

        transcript = record.get("source_transcript")
        timing = transcript.get("timing_ms") if isinstance(transcript, Mapping) else None
        if isinstance(timing, Mapping):
            for field, destination in (
                ("total", total_latencies),
                ("retrieval", retrieval_latencies),
                ("generation", generation_latencies),
            ):
                value = timing.get(field)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    destination.append(float(value))
        usage = transcript.get("usage") if isinstance(transcript, Mapping) else None
        cost = usage.get("cost_usd") if isinstance(usage, Mapping) else None
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            costs.append(float(cost))

    precision_denominator = true_positive_abstain + false_positive_abstain
    recall_denominator = true_positive_abstain + false_negative_abstain
    unavailable_gpu = "mac_local_equivalent_run_did_not_capture_gcp_gpu_telemetry"
    unavailable_api = "metric_not_applicable_to_local_candidate"
    unavailable_response_contract = (
        "local_candidate_response_not_normalized_to_api_contract"
    )
    values: dict[str, dict[str, dict[str, Any]]] = {
        "retrieval": {},
        "answer": {},
        "abstention": {},
        "task_success": {},
        "operations": {},
    }
    for k in k_values:
        values["retrieval"][f"document_recall_at_{k}"] = _metric_entry(
            round(fmean(doc_recalls[k]), 6), eligible=len(doc_recalls[k])
        )
        values["retrieval"][f"source_block_recall_at_{k}"] = _metric_entry(
            round(fmean(block_recalls[k]), 6), eligible=len(block_recalls[k])
        )
        values["retrieval"][f"all_required_docs_recalled_at_{k}"] = _metric_entry(
            round(fmean(all_required[k]), 6), eligible=len(all_required[k])
        )
    values["retrieval"]["mrr_at_10"] = _metric_entry(
        round(fmean(reciprocal_ranks), 6), eligible=len(reciprocal_ranks)
    )
    values["retrieval"]["ndcg_at_10"] = _metric_entry(
        round(fmean(ndcgs), 6), eligible=len(ndcgs)
    )
    values["answer"] = {
        "key_point_coverage": _metric_entry(
            round(fmean(key_point_coverages), 6), eligible=len(key_point_coverages)
        ),
        **{
            field: _metric_entry(round(fmean(items), 6), eligible=len(items))
            for field, items in answer_components.items()
        },
        "gold_citation_precision": _metric_entry(
            round(fmean(gold_citation_precisions), 6),
            eligible=len(gold_citation_precisions),
        ),
        "follow_up_success": _metric_entry(
            round(fmean(follow_up_successes), 6),
            eligible=len(follow_up_successes),
        ),
        "judgment_coverage": _metric_entry(
            round(fmean(judgment_complete), 6), eligible=len(judgment_complete)
        ),
    }
    values["abstention"] = {
        "precision": _metric_entry(
            _ratio(true_positive_abstain, precision_denominator),
            eligible=precision_denominator,
        ),
        "recall": _metric_entry(
            _ratio(true_positive_abstain, recall_denominator),
            eligible=recall_denominator,
        ),
        "safe_abstention_rate": _metric_entry(
            round(fmean(safe_abstentions), 6), eligible=len(safe_abstentions)
        ),
        "false_answer_rate": _metric_entry(
            _ratio(false_negative_abstain, recall_denominator),
            eligible=recall_denominator,
        ),
        "answerable_false_abstain_rate": _metric_entry(
            _ratio(answerable_abstentions, answerable_cases), eligible=answerable_cases
        ),
    }
    values["task_success"] = {
        key: _metric_entry(round(fmean(items), 6), eligible=len(items))
        for key, items in task_success.items()
    }
    values["operations"] = {
        "response_contract_error_rate": _metric_entry(
            None, eligible=0, reason=unavailable_response_contract
        ),
        "runtime_error_rate": _metric_entry(
            _ratio(runtime_errors, len(core)), eligible=len(core)
        ),
        "latency_total_p50_ms": _metric_entry(
            _percentile(total_latencies, 0.50), eligible=len(total_latencies)
        ),
        "latency_total_p95_ms": _metric_entry(
            _percentile(total_latencies, 0.95), eligible=len(total_latencies)
        ),
        "latency_retrieval_p50_ms": _metric_entry(
            _percentile(retrieval_latencies, 0.50), eligible=len(retrieval_latencies)
        ),
        "latency_generation_p50_ms": _metric_entry(
            _percentile(generation_latencies, 0.50), eligible=len(generation_latencies)
        ),
        "total_cost_usd": _metric_entry(round(sum(costs), 6), eligible=len(costs)),
        "mean_cost_usd": _metric_entry(
            round(fmean(costs), 6), eligible=len(costs)
        ),
        "total_gpu_seconds": _metric_entry(None, eligible=0, reason=unavailable_gpu),
        "mean_gpu_seconds": _metric_entry(None, eligible=0, reason=unavailable_gpu),
        "peak_vram_gb": _metric_entry(None, eligible=0, reason=unavailable_gpu),
        "api_cost_coverage": _metric_entry(None, eligible=0, reason=unavailable_api),
        "local_gpu_usage_coverage": _metric_entry(
            None, eligible=0, reason=unavailable_gpu
        ),
    }
    if set(values) != set(EXPECTED_METRIC_KEYS) or any(
        set(values[section]) != set(EXPECTED_METRIC_KEYS[section])
        for section in EXPECTED_METRIC_KEYS
    ):
        raise ValueError("local_mini131_performance_common_metric_keyset_invalid")
    return values


def _first_rank_summary(ranks: Sequence[float]) -> dict[str, Any]:
    values = [float(value) for value in ranks]
    return {
        "observed_count": len(values),
        "mean": round(fmean(values), 6) if values else None,
        "median": round(float(median(values)), 6) if values else None,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }


def _visual_target_summary(
    visual: Sequence[Mapping[str, Any]], key: str
) -> dict[str, Any]:
    eligible = 0
    ranks: list[float] = []
    for record in visual:
        metric = record.get("deterministic_metrics", {}).get("visual_retrieval", {}).get(key)
        if not isinstance(metric, Mapping):
            continue
        eligible += 1
        mrr = metric.get("mrr_at_10")
        recall = metric.get("recall_at_10")
        if (
            isinstance(mrr, (int, float))
            and not isinstance(mrr, bool)
            and float(mrr) > 0
            and isinstance(recall, (int, float))
            and float(recall) > 0
        ):
            ranks.append(round(1.0 / float(mrr), 6))
    return {
        "eligible_case_count": eligible,
        "hit_count": len(ranks),
        "hit_rate": _ratio(len(ranks), eligible),
        "first_rank": _first_rank_summary(ranks),
    }


def _numeric_leaf_count(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, (int, float)):
        return 1
    if isinstance(value, Mapping):
        return sum(_numeric_leaf_count(item) for item in value.values())
    if isinstance(value, list):
        return sum(_numeric_leaf_count(item) for item in value)
    return 0


def _objective_companion_metrics(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    rag = [row for row in records if row.get("asset_type") == "rag"]
    required_hit = 0
    required_total = 0
    set_precision: list[float] = []
    set_recall: list[float] = []
    set_f1: list[float] = []
    set_exact = 0
    set_tp = 0
    set_fp = 0
    set_fn = 0
    for record in rag:
        required = _required_doc_ids(record, nested_gold=False)
        if not required:
            continue
        returned = (
            {
                value
                for value in record["candidate"].get("selected_doc_ids", [])
                if isinstance(value, str)
            }
            if record.get("lane") == "supplemental_set_rerun"
            else set(_ranked_doc_ids(record))
        )
        required_hit += len(required & returned)
        required_total += len(required)
        if record.get("lane") == "supplemental_set_rerun":
            tp = len(required & returned)
            fp = len(returned - required)
            fn = len(required - returned)
            precision = tp / (tp + fp) if tp + fp else 0.0
            recall = tp / (tp + fn) if tp + fn else 0.0
            f1 = (
                2 * precision * recall / (precision + recall)
                if precision + recall
                else 0.0
            )
            set_precision.append(precision)
            set_recall.append(recall)
            set_f1.append(f1)
            set_exact += int(required == returned)
            set_tp += tp
            set_fp += fp
            set_fn += fn
    set_micro_precision = _ratio(set_tp, set_tp + set_fp)
    set_micro_recall = _ratio(set_tp, set_tp + set_fn)
    set_micro_f1 = (
        round(
            2
            * float(set_micro_precision)
            * float(set_micro_recall)
            / (float(set_micro_precision) + float(set_micro_recall)),
            6,
        )
        if set_micro_precision is not None
        and set_micro_recall is not None
        and set_micro_precision + set_micro_recall
        else 0.0
    )
    visual = [row for row in rag if row.get("lane") == "visual"]
    analytics = [row for row in rag if row.get("lane") == "corpus_analytics"]
    analytics_counts: list[int] = []
    analytics_field_total = 0
    analytics_field_passed = 0
    analytics_case_passed = 0
    analytics_companion = 0
    for record in analytics:
        deterministic = record.get("deterministic_metrics", {}).get(
            "analytics_calculation"
        )
        if isinstance(deterministic, Mapping):
            count = deterministic.get("comparison_count")
            matched = deterministic.get("matched_comparison_count")
            if isinstance(count, int) and isinstance(matched, int):
                analytics_field_total += count
                analytics_field_passed += matched
            analytics_case_passed += int(deterministic.get("case_passed") is True)
        transcript = record.get("source_transcript")
        companion = transcript.get("companion") if isinstance(transcript, Mapping) else None
        evidence = companion.get("analytics_evidence") if isinstance(companion, Mapping) else None
        if isinstance(evidence, Mapping):
            analytics_companion += int(
                evidence.get("source")
                == "executed_deterministic_refined98_calculation"
            )
            analytics_counts.append(_numeric_leaf_count(evidence.get("computed")))
    unknown = [row for row in rag if row.get("purpose") == "unknown"]
    unknown_safe = sum(
        row.get("semantic_evaluation", {}).get("safe_abstention") is True
        for row in unknown
    )
    metrics = {
        "required_document_hit_count": required_hit,
        "required_document_recall": _ratio(required_hit, required_total),
        "required_document_total": required_total,
        "set_exact_match_rate": _ratio(set_exact, len(set_precision)),
        "set_case_count": len(set_precision),
        "set_macro_precision": round(fmean(set_precision), 6),
        "set_macro_recall": round(fmean(set_recall), 6),
        "set_macro_f1": round(fmean(set_f1), 6),
        "set_micro_precision": set_micro_precision,
        "set_micro_recall": set_micro_recall,
        "set_micro_f1": set_micro_f1,
        "set_true_positive_total": set_tp,
        "set_false_positive_total": set_fp,
        "set_false_negative_total": set_fn,
        "visual_evidence_availability_rate": _ratio(
            sum(bool(row.get("retrieval", {}).get("evidence")) for row in visual),
            len(visual),
        ),
        "visual_case_count": len(visual),
        "visual_target_page": _visual_target_summary(visual, "page"),
        "visual_target_chunk": _visual_target_summary(visual, "chunk_or_block"),
        "visual_target_object_bridge": _visual_target_summary(visual, "object"),
        "analytics_numeric_evidence_availability_rate": _ratio(
            len(analytics_counts), len(analytics)
        ),
        "analytics_case_count": len(analytics),
        "analytics_deterministic_companion_case_count": analytics_companion,
        "analytics_deterministic_companion_pass_count": min(
            analytics_companion, analytics_case_passed
        ),
        "analytics_deterministic_companion_complete_rate": _ratio(
            analytics_companion, len(analytics)
        ),
        "analytics_deterministic_case_pass_count": analytics_case_passed,
        "analytics_deterministic_case_pass_rate": _ratio(
            analytics_case_passed, len(analytics)
        ),
        "analytics_deterministic_field_count": analytics_field_total,
        "analytics_deterministic_field_pass_count": analytics_field_passed,
        "analytics_deterministic_field_pass_rate": _ratio(
            analytics_field_passed, analytics_field_total
        ),
        "analytics_numeric_evidence_field_count": sum(analytics_counts),
        "analytics_numeric_evidence_fields_per_case": {
            "observed_case_count": len(analytics_counts),
            "mean": round(fmean(analytics_counts), 6) if analytics_counts else None,
            "min": min(analytics_counts) if analytics_counts else None,
            "max": max(analytics_counts) if analytics_counts else None,
        },
        "unknown_safe_abstention_pass_count": unknown_safe,
        "unknown_case_count": len(unknown),
        "unknown_safe_abstention_rate": _ratio(unknown_safe, len(unknown)),
    }
    return metrics


def _read_api_receipt(path: Path) -> dict[str, Any]:
    if (
        not path.is_file()
        or path.is_symlink()
        or stat.S_IMODE(path.stat().st_mode) != 0o644
        or sha256_file(path) != API_RECEIPT_SHA256
    ):
        raise ValueError("local_mini131_performance_api_receipt_invalid")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("local_mini131_performance_api_receipt_invalid") from error
    if not isinstance(value, dict):
        raise ValueError("local_mini131_performance_api_receipt_invalid")
    return value


def _load_api_baseline(
    ledger: SemanticLedger,
    local_records: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, Any]]:
    sources = ledger.suite.config.get("sources")
    integrated = sources.get("integrated_ledger") if isinstance(sources, Mapping) else None
    if not isinstance(integrated, Mapping):
        raise ValueError("local_mini131_performance_api_case_records_invalid")
    relative = integrated.get("path")
    expected_sha256 = integrated.get("sha256")
    if (
        not isinstance(relative, str)
        or expected_sha256 != API_CASE_RECORDS_SHA256
    ):
        raise ValueError("local_mini131_performance_api_case_records_invalid")
    case_path = ledger.suite.repo_root / relative
    if (
        not case_path.is_file()
        or case_path.is_symlink()
        or stat.S_IMODE(case_path.stat().st_mode) != 0o600
        or sha256_file(case_path) != expected_sha256
    ):
        raise ValueError("local_mini131_performance_api_case_records_invalid")
    try:
        api_records = validate_api_case_records(read_jsonl(case_path))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("local_mini131_performance_api_case_records_invalid") from error
    receipt_path = ledger.suite.repo_root / API_RECEIPT_RELATIVE_PATH
    receipt = _read_api_receipt(receipt_path)
    artifacts = receipt.get("artifact_sha256s")
    counts = receipt.get("counts")
    semantic = receipt.get("semantic_judge")
    if (
        receipt.get("schema_version") != "mini131-bundle.v1"
        or receipt.get("baseline_id") != API_BASELINE_ID
        or receipt.get("stage") != "case_records_ready"
        or receipt.get("passed") is not True
        or not isinstance(artifacts, Mapping)
        or artifacts.get("case_records") != expected_sha256
        or not isinstance(counts, Mapping)
        or counts.get("total") != 131
        or counts.get("rag") != 129
        or counts.get("parser") != 2
        or not isinstance(semantic, Mapping)
        or semantic.get("status") != "complete"
        or semantic.get("model") != JUDGE_MODEL
        or semantic.get("rubric_version") != JUDGE_RUBRIC
    ):
        raise ValueError("local_mini131_performance_api_receipt_invalid")
    api_by_id = {str(row["case_id"]): row for row in api_records}
    local_by_id = {str(row["case_id"]): row for row in local_records}
    if set(api_by_id) != set(local_by_id) or len(api_by_id) != 131:
        raise ValueError("local_mini131_performance_api_case_identity_mismatch")
    for case_id in api_by_id:
        api = api_by_id[case_id]
        local = local_by_id[case_id]
        if (
            api.get("question") != local.get("question")
            or canonical_json(api.get("expected"))
            != canonical_json(local.get("expected"))
            or api.get("lane") != local.get("lane")
            or api.get("case_type") != local.get("asset_type")
        ):
            raise ValueError("local_mini131_performance_api_case_identity_mismatch")
    reference = {
        "baseline_id": API_BASELINE_ID,
        "generator": API_GENERATOR,
        "mean_semantic_score": semantic.get("mean_semantic_score"),
        "accepted": int(counts.get("judge_decisions", {}).get("accepted", 0)),
        "rejected": int(counts.get("judge_decisions", {}).get("rejected", 0)),
        "rag_count": int(counts["rag"]),
        "parser_count": int(counts["parser"]),
        "case_records_sha256": expected_sha256,
        "receipt_sha256": API_RECEIPT_SHA256,
    }
    identity = {
        "validated": True,
        "case_count": 131,
        "rag_case_count": 129,
        "parser_case_count": 2,
        "question_expected_lane_exact_match": True,
        "api_case_records_sha256": expected_sha256,
        "api_receipt_sha256": API_RECEIPT_SHA256,
    }
    return api_by_id, reference, identity


def _same_item_comparison(
    records: Sequence[Mapping[str, Any]],
    api_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    score_deltas: list[float] = []
    local_higher = 0
    api_higher = 0
    equal_score = 0
    verdict_same = 0
    status_same = 0
    for local in sorted(records, key=lambda item: str(item["case_id"])):
        case_id = str(local["case_id"])
        api = api_by_id[case_id]
        if local["asset_type"] == "rag":
            api_judgment = api.get("judgment")
            if not isinstance(api_judgment, Mapping):
                raise ValueError("local_mini131_performance_api_judgment_missing")
            api_score = float(_judgment_semantic_score(api_judgment))
            local_score = float(local["semantic_evaluation"]["score"])
            api_verdict = str(api_judgment["judge_decision"])
            local_verdict = str(local["semantic_evaluation"]["verdict"])
            delta = round(local_score - api_score, 6)
            score_deltas.append(delta)
            local_higher += int(delta > 0)
            api_higher += int(delta < 0)
            equal_score += int(delta == 0)
        else:
            api_score = None
            local_score = None
            api_verdict = (
                "parser_passed"
                if api.get("parser_result", {}).get("passed") is True
                else "parser_failed"
            )
            local_verdict = (
                "parser_passed"
                if local.get("deterministic_metrics", {}).get("passed") is True
                else "parser_failed"
            )
            delta = None
        api_status = str(api.get("candidate", {}).get("status"))
        local_status = str(local.get("candidate", {}).get("status"))
        verdict_same += int(api_verdict == local_verdict)
        status_same += int(api_status == local_status)
        cases.append(
            {
                "case_id": case_id,
                "asset_type": str(local["asset_type"]),
                "lane": str(local["lane"]),
                "purpose": str(local["purpose"]),
                "api_score": api_score,
                "local_score": local_score,
                "score_delta_local_minus_api": delta,
                "api_verdict": api_verdict,
                "local_verdict": local_verdict,
                "verdict_changed": api_verdict != local_verdict,
                "api_status": api_status,
                "local_status": local_status,
                "status_changed": api_status != local_status,
            }
        )
    return {
        "case_count": len(cases),
        "rag_case_count": len(score_deltas),
        "parser_case_count": len(cases) - len(score_deltas),
        "mean_score_delta": round(fmean(score_deltas), 6),
        "local_higher_score": local_higher,
        "api_higher_score": api_higher,
        "equal_score": equal_score,
        "verdict_same": verdict_same,
        "verdict_changed": len(cases) - verdict_same,
        "status_same": status_same,
        "status_changed": len(cases) - status_same,
        "cases": cases,
    }


def _labeled_group_summary(
    key: str, records: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    definition = PURPOSE_DEFINITIONS[key]
    summary = _group_summary(records)
    summary["mean_semantic_score"] = _api_display_mean(
        summary["mean_semantic_score"]
    )
    return {
        "key": key,
        "label": definition["label"],
        "meaning": definition["meaning"],
        "failure": definition["failure"],
        **summary,
    }


def _primary_category_summaries(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        purpose = str(record["purpose"])
        key = "bid_rag_scenarios" if purpose in SCENARIO_KEYS else purpose
        grouped[key].append(record)
    if set(grouped) != set(PRIMARY_CATEGORY_KEYS):
        raise ValueError("local_mini131_performance_primary_category_mismatch")
    return {
        key: _labeled_group_summary(key, grouped[key])
        for key in PRIMARY_CATEGORY_KEYS
    }


def _scenario_summaries(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    grouped = {
        key: [row for row in records if row.get("purpose") == key]
        for key in SCENARIO_KEYS
    }
    if any(len(grouped[key]) != 10 for key in SCENARIO_KEYS):
        raise ValueError("local_mini131_performance_scenario_partition_mismatch")
    return {
        key: _labeled_group_summary(key, grouped[key]) for key in SCENARIO_KEYS
    }


def _visual_subgroup_summaries(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        if record.get("purpose") != "visual_table_figure":
            continue
        expected = record.get("expected")
        if not isinstance(expected, Mapping):
            raise ValueError("local_mini131_performance_visual_expected_invalid")
        key = f"{str(expected.get('document_format', '')).lower()}_{str(expected.get('evidence_type', '')).lower()}"
        if key not in VISUAL_SUBGROUP_DEFINITIONS:
            raise ValueError("local_mini131_performance_visual_subgroup_invalid")
        grouped[key].append(record)
    if set(grouped) != set(VISUAL_SUBGROUP_KEYS):
        raise ValueError("local_mini131_performance_visual_subgroup_mismatch")
    result: dict[str, dict[str, Any]] = {}
    for key in VISUAL_SUBGROUP_KEYS:
        definition = VISUAL_SUBGROUP_DEFINITIONS[key]
        summary = _group_summary(grouped[key])
        summary["mean_semantic_score"] = _api_display_mean(
            summary["mean_semantic_score"]
        )
        result[key] = {
            "key": key,
            "label": definition["label"],
            "meaning": definition["meaning"],
            **summary,
        }
    return result


def build_summary(
    records: Sequence[Mapping[str, Any]],
    *,
    deterministic_report: Mapping[str, Any],
    semantic_report: Mapping[str, Any],
    api_by_id: Mapping[str, Mapping[str, Any]],
    api_reference: Mapping[str, Any],
    case_identity: Mapping[str, Any],
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
    comparison = _same_item_comparison(records, api_by_id)
    api_parity = {
        "primary_categories": _primary_category_summaries(records),
        "scenario_breakdown": _scenario_summaries(records),
        "visual_subgroups": _visual_subgroup_summaries(records),
        "objective_companion_metrics": _objective_companion_metrics(records),
        "common_evaluation_metrics": _common_evaluation_metrics(records),
        "api_reference": copy.deepcopy(dict(api_reference)),
        "local_candidate": {
            "suite_id": SUITE_ID,
            "generator": LOCAL_GENERATOR,
            "embedding": LOCAL_EMBEDDING,
            "execution_profile": "mac_local_equivalent",
            "mean_semantic_score": overall["mean_semantic_score"],
            "accepted": overall["accepted"],
            "rejected": overall["rejected"],
            "rag_count": len(rag),
            "parser_count": len(parser),
        },
        "case_identity": copy.deepcopy(dict(case_identity)),
        "same_item_comparison": comparison,
    }
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
        "api_parity": api_parity,
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


def _validate_same_item_comparison(
    comparison: Any, records: Sequence[Mapping[str, Any]]
) -> None:
    aggregate_fields = {
        "case_count",
        "rag_case_count",
        "parser_case_count",
        "mean_score_delta",
        "local_higher_score",
        "api_higher_score",
        "equal_score",
        "verdict_same",
        "verdict_changed",
        "status_same",
        "status_changed",
        "cases",
    }
    case_fields = {
        "case_id",
        "asset_type",
        "lane",
        "purpose",
        "api_score",
        "local_score",
        "score_delta_local_minus_api",
        "api_verdict",
        "local_verdict",
        "verdict_changed",
        "api_status",
        "local_status",
        "status_changed",
    }
    if not isinstance(comparison, Mapping) or set(comparison) != aggregate_fields:
        raise ValueError("local_mini131_performance_same_item_comparison_invalid")
    cases = comparison["cases"]
    if not isinstance(cases, list) or len(cases) != len(records):
        raise ValueError("local_mini131_performance_same_item_comparison_invalid")
    local_by_id = {str(row["case_id"]): row for row in records}
    seen: set[str] = set()
    deltas: list[float] = []
    local_higher = 0
    api_higher = 0
    equal = 0
    verdict_same = 0
    status_same = 0
    for item in cases:
        if not isinstance(item, Mapping) or set(item) != case_fields:
            raise ValueError("local_mini131_performance_same_item_case_invalid")
        case_id = item["case_id"]
        if not isinstance(case_id, str) or case_id in seen or case_id not in local_by_id:
            raise ValueError("local_mini131_performance_same_item_case_invalid")
        seen.add(case_id)
        record = local_by_id[case_id]
        if (
            item["asset_type"] != record["asset_type"]
            or item["lane"] != record["lane"]
            or item["purpose"] != record["purpose"]
            or item["local_status"] != record["candidate"]["status"]
            or not isinstance(item["status_changed"], bool)
            or item["status_changed"]
            != (item["api_status"] != item["local_status"])
            or not isinstance(item["verdict_changed"], bool)
            or item["verdict_changed"]
            != (item["api_verdict"] != item["local_verdict"])
        ):
            raise ValueError("local_mini131_performance_same_item_case_invalid")
        if record["asset_type"] == "rag":
            semantic = record["semantic_evaluation"]
            local_score = float(semantic["score"])
            api_score = item["api_score"]
            if (
                not isinstance(api_score, (int, float))
                or isinstance(api_score, bool)
                or not math.isfinite(float(api_score))
                or not 0 <= float(api_score) <= 100
                or item["local_score"] != local_score
                or item["local_verdict"] != semantic["verdict"]
                or item["api_verdict"] not in FINAL_DECISIONS
            ):
                raise ValueError("local_mini131_performance_same_item_case_invalid")
            delta = round(local_score - float(api_score), 6)
            if item["score_delta_local_minus_api"] != delta:
                raise ValueError("local_mini131_performance_same_item_case_invalid")
            deltas.append(delta)
            local_higher += int(delta > 0)
            api_higher += int(delta < 0)
            equal += int(delta == 0)
        elif (
            item["api_score"] is not None
            or item["local_score"] is not None
            or item["score_delta_local_minus_api"] is not None
            or item["local_verdict"]
            != (
                "parser_passed"
                if record["deterministic_metrics"].get("passed") is True
                else "parser_failed"
            )
            or item["api_verdict"] not in {"parser_passed", "parser_failed"}
        ):
            raise ValueError("local_mini131_performance_same_item_case_invalid")
        verdict_same += int(not item["verdict_changed"])
        status_same += int(not item["status_changed"])
    if seen != set(local_by_id):
        raise ValueError("local_mini131_performance_same_item_comparison_invalid")
    expected = {
        "case_count": len(records),
        "rag_case_count": len(deltas),
        "parser_case_count": len(records) - len(deltas),
        "mean_score_delta": round(fmean(deltas), 6),
        "local_higher_score": local_higher,
        "api_higher_score": api_higher,
        "equal_score": equal,
        "verdict_same": verdict_same,
        "verdict_changed": len(records) - verdict_same,
        "status_same": status_same,
        "status_changed": len(records) - status_same,
    }
    if any(comparison.get(key) != value for key, value in expected.items()):
        raise ValueError("local_mini131_performance_same_item_reconciliation_failed")


def _validate_api_parity(
    api_parity: Any,
    *,
    records: Sequence[Mapping[str, Any]],
) -> None:
    if not isinstance(api_parity, Mapping) or set(api_parity) != {
        "primary_categories",
        "scenario_breakdown",
        "visual_subgroups",
        "objective_companion_metrics",
        "common_evaluation_metrics",
        "api_reference",
        "local_candidate",
        "case_identity",
        "same_item_comparison",
    }:
        raise ValueError("local_mini131_performance_api_parity_invalid")
    primary = api_parity["primary_categories"]
    scenarios = api_parity["scenario_breakdown"]
    visual = api_parity["visual_subgroups"]
    if (
        not isinstance(primary, Mapping)
        or set(primary) != set(PRIMARY_CATEGORY_KEYS)
        or {
            key: primary[key].get("count")
            for key in PRIMARY_CATEGORY_KEYS
            if isinstance(primary[key], Mapping)
        }
        != EXPECTED_PRIMARY_COUNTS
        or not isinstance(scenarios, Mapping)
        or set(scenarios) != set(SCENARIO_KEYS)
        or any(
            not isinstance(scenarios[key], Mapping)
            or scenarios[key].get("count") != 10
            for key in SCENARIO_KEYS
        )
        or not isinstance(visual, Mapping)
        or set(visual) != set(VISUAL_SUBGROUP_KEYS)
        or {
            key: visual[key].get("count")
            for key in VISUAL_SUBGROUP_KEYS
            if isinstance(visual[key], Mapping)
        }
        != EXPECTED_VISUAL_SUBGROUP_COUNTS
    ):
        raise ValueError("local_mini131_performance_api_partition_invalid")
    if (
        primary != _primary_category_summaries(records)
        or scenarios != _scenario_summaries(records)
        or visual != _visual_subgroup_summaries(records)
    ):
        raise ValueError("local_mini131_performance_api_partition_reconciliation_failed")
    objective = api_parity["objective_companion_metrics"]
    if not isinstance(objective, Mapping):
        raise ValueError("local_mini131_performance_objective_metric_mismatch")
    if objective != _objective_companion_metrics(records):
        raise ValueError("local_mini131_performance_objective_reconciliation_failed")
    common = api_parity["common_evaluation_metrics"]
    if not isinstance(common, Mapping) or set(common) != set(EXPECTED_METRIC_KEYS):
        raise ValueError("local_mini131_performance_common_metric_keyset_invalid")
    for section, expected_keys in EXPECTED_METRIC_KEYS.items():
        metrics = common.get(section)
        if not isinstance(metrics, Mapping) or set(metrics) != set(expected_keys):
            raise ValueError("local_mini131_performance_common_metric_keyset_invalid")
        for metric in metrics.values():
            if not isinstance(metric, Mapping) or set(metric) != {
                "value",
                "eligible",
                "coverage",
                "available",
                "reason",
            }:
                raise ValueError("local_mini131_performance_common_metric_invalid")
            value = metric.get("value")
            eligible = metric.get("eligible")
            coverage = metric.get("coverage")
            available = metric.get("available")
            reason = metric.get("reason")
            if (
                not isinstance(eligible, int)
                or isinstance(eligible, bool)
                or eligible < 0
                or not isinstance(coverage, (int, float))
                or isinstance(coverage, bool)
                or not 0 <= float(coverage) <= 1
                or not isinstance(available, bool)
                or (
                    available
                    and (
                        not isinstance(value, (int, float))
                        or isinstance(value, bool)
                        or not math.isfinite(float(value))
                        or eligible == 0
                        or reason is not None
                    )
                )
                or (
                    not available
                    and (
                        value is not None
                        or eligible != 0
                        or not isinstance(reason, str)
                        or not reason
                    )
                )
            ):
                raise ValueError("local_mini131_performance_common_metric_invalid")
    if common != _common_evaluation_metrics(records):
        raise ValueError("local_mini131_performance_common_metric_reconciliation_failed")
    reference = api_parity["api_reference"]
    local = api_parity["local_candidate"]
    identity = api_parity["case_identity"]
    overall = _group_summary(records)
    expected_local = {
        "suite_id": SUITE_ID,
        "generator": LOCAL_GENERATOR,
        "embedding": LOCAL_EMBEDDING,
        "execution_profile": "mac_local_equivalent",
        "mean_semantic_score": overall["mean_semantic_score"],
        "accepted": overall["accepted"],
        "rejected": overall["rejected"],
        "rag_count": overall["rag_count"],
        "parser_count": overall["parser_count"],
    }
    if (
        not isinstance(reference, Mapping)
        or set(reference) != {
            "baseline_id",
            "generator",
            "mean_semantic_score",
            "accepted",
            "rejected",
            "rag_count",
            "parser_count",
            "case_records_sha256",
            "receipt_sha256",
        }
        or reference.get("baseline_id") != API_BASELINE_ID
        or reference.get("generator") != API_GENERATOR
        or reference.get("mean_semantic_score") != 54.845
        or reference.get("accepted") != 58
        or reference.get("rejected") != 71
        or reference.get("rag_count") != 129
        or reference.get("parser_count") != 2
        or reference.get("case_records_sha256") != API_CASE_RECORDS_SHA256
        or reference.get("receipt_sha256") != API_RECEIPT_SHA256
        or not isinstance(local, Mapping)
        or local != expected_local
        or not isinstance(identity, Mapping)
        or set(identity) != {
            "validated",
            "case_count",
            "rag_case_count",
            "parser_case_count",
            "question_expected_lane_exact_match",
            "api_case_records_sha256",
            "api_receipt_sha256",
        }
        or identity.get("validated") is not True
        or identity.get("case_count") != 131
        or identity.get("rag_case_count") != 129
        or identity.get("parser_case_count") != 2
        or identity.get("question_expected_lane_exact_match") is not True
        or identity.get("api_case_records_sha256") != API_CASE_RECORDS_SHA256
        or identity.get("api_receipt_sha256") != API_RECEIPT_SHA256
    ):
        raise ValueError("local_mini131_performance_api_reference_invalid")
    _validate_same_item_comparison(api_parity["same_item_comparison"], records)


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
        purposes = Counter(str(row["purpose"]) for row in records)
        if purposes != Counter(EXPECTED_PURPOSE_COUNTS):
            raise ValueError("local_mini131_performance_purpose_partition_mismatch")
        _validate_api_parity(summary.get("api_parity"), records=records)


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
    api_by_id, api_reference, case_identity = _load_api_baseline(ledger, records)
    summary = build_summary(
        records,
        deterministic_report=deterministic_report,
        semantic_report=semantic_report,
        api_by_id=api_by_id,
        api_reference=api_reference,
        case_identity=case_identity,
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
            "api_case_records_sha256": case_identity["api_case_records_sha256"],
            "api_receipt_sha256": case_identity["api_receipt_sha256"],
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


def _companion_text(key: str, objective: Mapping[str, Any]) -> str:
    if key == "conditional_all_list":
        return (
            "Macro P/R/F1 "
            f"{objective['set_macro_precision']}/{objective['set_macro_recall']}/"
            f"{objective['set_macro_f1']}; 완전일치 {objective['set_exact_match_rate']}"
        )
    if key == "visual_table_figure":
        page = objective["visual_target_page"]
        chunk = objective["visual_target_chunk"]
        object_bridge = objective["visual_target_object_bridge"]
        return (
            f"페이지 {page['hit_count']}/{page['eligible_case_count']}; "
            f"표 청크 {chunk['hit_count']}/{chunk['eligible_case_count']}; "
            f"객체 {object_bridge['hit_count']}/{object_bridge['eligible_case_count']}"
        )
    if key == "corpus_analytics":
        return (
            f"결정론 수치 {objective['analytics_deterministic_field_pass_count']}/"
            f"{objective['analytics_deterministic_field_count']}"
        )
    if key == "unknown":
        return (
            f"안전 기권 {objective['unknown_safe_abstention_pass_count']}/"
            f"{objective['unknown_case_count']}"
        )
    if key == "parser_regression":
        return "ETL 회귀 2/2 PASS; 의미평균에서 제외"
    if key == "bid_rag_scenarios":
        return "단일·다중·후속·정보 없음 각 10문항"
    if key == "multi_doc_compare":
        return "필수 문서 회수 후 비교·종합 품질은 의미점수로 판정"
    return "정답 사실·근거·인용 품질은 동일 Sol rubric으로 판정"


def _parity_group_rows(
    items: Mapping[str, Mapping[str, Any]], objective: Mapping[str, Any]
) -> str:
    return "".join(
        "<tr>"
        f'<th scope="row">{html.escape(str(item["label"]))}</th>'
        f'<td class="meaning">{html.escape(str(item["meaning"]))}</td>'
        f'<td>{item["count"]}</td>'
        f'<td>{html.escape(str(item["mean_semantic_score"]))}</td>'
        f'<td>{item["accepted"]}/{item["rejected"]}</td>'
        f'<td>{html.escape(_companion_text(key, objective))}</td>'
        "</tr>"
        for key, item in items.items()
    )


def _visual_parity_rows(items: Mapping[str, Mapping[str, Any]]) -> str:
    return "".join(
        "<tr>"
        f'<th scope="row">{html.escape(str(item["label"]))}</th>'
        f'<td class="meaning">{html.escape(str(item["meaning"]))}</td>'
        f'<td>{item["count"]}</td>'
        f'<td>{html.escape(str(item["mean_semantic_score"]))}</td>'
        f'<td>{item["accepted"]}/{item["rejected"]}</td>'
        "</tr>"
        for item in items.values()
    )


def _common_metric_rows(
    items: Mapping[str, Mapping[str, Mapping[str, Any]]]
) -> str:
    rows: list[str] = []
    for section, metrics in items.items():
        for name, metric in metrics.items():
            rows.append(
                "<tr>"
                f"<th>{html.escape(section)}</th>"
                f"<td>{html.escape(name)}</td>"
                f"<td>{html.escape(str(metric['value']))}</td>"
                f"<td>{metric['eligible']}</td>"
                f"<td>{metric['coverage']}</td>"
                f"<td>{'available' if metric['available'] else 'unavailable'}</td>"
                f"<td>{html.escape(str(metric['reason'] or ''))}</td>"
                "</tr>"
            )
    return "".join(rows)


def render_html(report: Mapping[str, Any]) -> str:
    validate_performance_evaluation(report, require_complete=False)
    records = report["records"]
    summary = report["summary"]
    overall = summary["overall"]
    api_parity = summary.get("api_parity")
    if not isinstance(api_parity, Mapping):
        raise ValueError("local_mini131_performance_api_parity_invalid")
    objective = api_parity["objective_companion_metrics"]
    comparison = api_parity["same_item_comparison"]
    comparison_by_id = {
        str(item["case_id"]): item for item in comparison["cases"]
    }
    cards: list[str] = []
    for record in records:
        candidate = record["candidate"]
        semantic = record.get("semantic_evaluation")
        verdict = semantic["verdict"] if isinstance(semantic, Mapping) else "parser_passed"
        score = semantic["score"] if isinstance(semantic, Mapping) else None
        rationale = semantic["rationale"] if isinstance(semantic, Mapping) else "ETL deterministic PASS"
        components = semantic["component_scores"] if isinstance(semantic, Mapping) else None
        history = semantic["judgment_history"] if isinstance(semantic, Mapping) else []
        case_comparison = comparison_by_id[str(record["case_id"])]
        execution_lineage = candidate.get("execution_lineage")
        execution_mode = (
            str(execution_lineage.get("mode"))
            if isinstance(execution_lineage, Mapping)
            else "unknown"
        )
        failed = int(
            verdict in {"rejected", "parser_failed"}
            or candidate.get("status") == "error"
        )
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
            f'''<details class="case" data-lane="{html.escape(str(record['lane']), quote=True)}" data-purpose="{html.escape(str(record['purpose']), quote=True)}" data-difficulty="{html.escape(str(record['difficulty']), quote=True)}" data-type="{html.escape(str(record['asset_type']), quote=True)}" data-lineage="{html.escape(execution_mode, quote=True)}" data-status="{html.escape(str(candidate['status']), quote=True)}" data-verdict="{html.escape(str(verdict), quote=True)}" data-failure="{failed}" data-search="{html.escape(search, quote=True)}">
<summary><code>{html.escape(str(record['case_id']))}</code><span>{html.escape(str(record['difficulty']))}</span><span>{html.escape(str(record['purpose']))}</span><span>{html.escape(str(candidate['status']))}</span><strong>{html.escape(str(verdict))}</strong><b>{'—' if score is None else f'{float(score):.2f}'}</b></summary>
<div class="grid"><section><h3>골든 질문</h3><pre>{html.escape(str(record['question']))}</pre></section><section><h3>정답 기준</h3><pre>{_json_pre(record['expected'])}</pre></section></div>
<section><h3>로컬 Qwen 실제 답변</h3><pre>{html.escape(str(candidate['answer']))}</pre></section>
<div class="grid"><section><h3>API ↔ Local 동일 문항 비교</h3><pre>{_json_pre(case_comparison)}</pre></section><section><h3>구성 점수</h3><pre>{_json_pre(components)}</pre></section><section><h3>최종 판정 사유</h3><pre>{html.escape(str(rationale))}</pre></section></div>
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
    lineage_options = "".join(
        f'<option value="{html.escape(key, quote=True)}">{html.escape(key)}</option>'
        for key in sorted(
            {
                str(row.get("candidate", {}).get("execution_lineage", {}).get("mode", "unknown"))
                for row in records
            }
        )
    )
    api = api_parity["api_reference"]
    local = api_parity["local_candidate"]
    return f'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Local Qwen Mini131 · API 동일 기준 성능평가</title><style>
:root{{font-family:Inter,system-ui,sans-serif;line-height:1.55;color-scheme:light dark}}body{{max-width:1440px;margin:auto;padding:24px}}h1{{margin-bottom:4px}}h2{{margin-top:30px}}.sub{{color:GrayText;margin-top:0}}.notice{{border:1px solid #d18b18;border-radius:10px;padding:12px;background:color-mix(in srgb,#d18b18 10%,Canvas)}}.notice.info{{border-color:#4f7ddc;background:color-mix(in srgb,#4f7ddc 8%,Canvas)}}.metrics,.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px;margin:16px 0}}.metric,section,details.case{{border:1px solid GrayText;border-radius:10px;padding:11px}}.metric strong{{display:block;font-size:1.5rem}}table{{width:100%;border-collapse:collapse;margin:12px 0}}th,td{{padding:8px;border-bottom:1px solid GrayText;text-align:right;vertical-align:top}}th:first-child,td:first-child{{text-align:left}}td.meaning{{text-align:left;min-width:320px}}.controls{{position:sticky;top:0;z-index:2;display:flex;gap:8px;flex-wrap:wrap;padding:10px;background:Canvas;border:1px solid GrayText;border-radius:10px}}input,select{{font:inherit;padding:7px}}input[type=search]{{flex:1;min-width:260px}}details.case{{margin:10px 0}}details.case>summary{{display:flex;gap:8px;align-items:center;flex-wrap:wrap;cursor:pointer}}details.case>summary strong{{margin-left:auto}}details.case>summary span{{border:1px solid GrayText;border-radius:999px;padding:2px 7px;font-size:.8rem}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:color-mix(in srgb,CanvasText 7%,Canvas);padding:10px;border-radius:7px}}.hidden{{display:none!important}}@media(max-width:760px){{body{{padding:12px}}table{{display:block;overflow-x:auto}}td.meaning{{min-width:260px}}}}
</style></head><body>
<h1>Local Qwen Mini131 · API 동일 기준 성능평가</h1><p class="sub">qwen3.8:27b-mlx · KURE-v1 · fixed gpt-5.6-sol rubric · same 131 assets as gpt-5-mini API baseline</p>
<aside class="notice"><strong>잠정 성능평가</strong> 129개 RAG 답변과 parser 2건은 모두 기록·채점됐고 API 원장의 case ID·질문·정답·lane이 131/131 정확히 일치합니다. 다만 골드는 아직 사람 승인 전이고 이 실행은 Mac Ollama/NumPy이므로 공식 GCP 점수가 아닙니다.</aside>
<h2 id="question-set-scope">질문셋 출처와 평가 분모</h2><p>API 기준선과 로컬 후보 모두 동일한 <strong>RAG 129건 + parser 회귀 2건 = 131자산</strong>을 사용합니다. 의미점수는 parser를 제외한 129건에만 적용하며, parser 2건은 ETL 회귀 PASS/FAIL로 별도 집계합니다. 동일성 검증 원장 SHA-256은 <code>{html.escape(str(api_parity['case_identity']['api_case_records_sha256']))}</code>입니다.</p>
<h2 id="primary-category-results">평가 목적별 결과</h2><p>API 리포트와 같은 7개 업무 영역입니다. 서로 다른 능력을 전체 평균 하나로 섞지 않고 각 행을 독립적으로 봅니다.</p>
<table><thead><tr><th>평가 영역</th><th>의미</th><th>문항</th><th>로컬 의미점수</th><th>통과/실패</th><th>전용 지표</th></tr></thead><tbody>{_parity_group_rows(api_parity['primary_categories'], objective)}</tbody></table>
<h2 id="core40-scenario-results">입찰 RAG 시나리오 40 상세</h2><p>단일 문서·다중 비교·후속질문·정보 없음의 네 시나리오를 각각 10문항으로 분리했습니다.</p>
<table><thead><tr><th>세부 유형</th><th>의미</th><th>문항</th><th>로컬 의미점수</th><th>통과/실패</th><th>전용 지표</th></tr></thead><tbody>{_parity_group_rows(api_parity['scenario_breakdown'], objective)}</tbody></table>
<h2 id="visual-subgroup-results">HWP/PDF 표·그림 10 상세</h2><p>파일 형식과 정보 위치에 따라 네 유형으로 분리했습니다.</p>
<table><thead><tr><th>세부 유형</th><th>무엇을 시험하나</th><th>문항</th><th>로컬 의미점수</th><th>통과/실패</th></tr></thead><tbody>{_visual_parity_rows(api_parity['visual_subgroups'])}</tbody></table>
<h2 id="common-metric-results">공통 평가 지표</h2><p>API 평가 계약의 필드명을 그대로 사용했습니다. 측정하지 않은 값은 다른 지표로 대체하지 않고 <code>null</code>·eligible 0과 사유를 표시합니다.</p>
<table><thead><tr><th>영역</th><th>지표</th><th>값</th><th>적용</th><th>커버리지</th><th>가용성</th><th>사유</th></tr></thead><tbody>{_common_metric_rows(api_parity['common_evaluation_metrics'])}</tbody></table>
<h2 id="api-vs-local-results">API 기준선과 로컬 후보 동일 문항 비교</h2>
<table><thead><tr><th>후보</th><th>RAG</th><th>parser</th><th>의미평균</th><th>accepted</th><th>rejected</th></tr></thead><tbody><tr><th>{html.escape(str(api['generator']))}</th><td>{api['rag_count']}</td><td>{api['parser_count']}</td><td>{api['mean_semantic_score']}</td><td>{api['accepted']}</td><td>{api['rejected']}</td></tr><tr><th>{html.escape(str(local['generator']))}</th><td>{local['rag_count']}</td><td>{local['parser_count']}</td><td>{local['mean_semantic_score']}</td><td>{local['accepted']}</td><td>{local['rejected']}</td></tr></tbody></table>
<p>문항별 점수 비교: Local 우세 {comparison['local_higher_score']} / API 우세 {comparison['api_higher_score']} / 동점 {comparison['equal_score']}; 판정 변경 {comparison['verdict_changed']}건; 평균 점수 차이(Local−API) {comparison['mean_score_delta']}.</p>
<h2 id="overall-reference">전체 참고 집계</h2><p>아래는 평가영역별 문항 수 차이를 그대로 반영한 참고용 문항가중 집계입니다.</p>
<div class="metrics"><div class="metric">전체 자산<strong>{summary['counts']['total_assets']}</strong></div><div class="metric">RAG / parser<strong>{summary['counts']['rag']} / {summary['counts']['parser']}</strong></div><div class="metric">평균 의미점수<strong>{float(overall['mean_semantic_score']):.2f}</strong></div><div class="metric">승인 / 반려<strong>{overall['accepted']} / {overall['rejected']}</strong></div><div class="metric">답변 / 기권 / 오류<strong>{overall['status'].get('answered',0)} / {overall['status'].get('abstained',0)} / {overall['status'].get('error',0)}</strong></div></div>
<h2>채점 구성요소</h2><table><thead><tr><th>요소</th><th>적용 문항</th><th>평균</th></tr></thead><tbody>{_component_rows(overall['components'])}</tbody></table>
<h2>행동 검증</h2><table><thead><tr><th>검증</th><th>적용 문항</th><th>통과</th><th>통과율</th></tr></thead><tbody>{_behavior_rows(overall['behavior_checks'])}</tbody></table>
<h2>난이도별</h2><table><thead><tr><th>난이도</th><th>문항</th><th>승인</th><th>반려</th><th>평균점수</th><th>승인율</th></tr></thead><tbody>{_table_rows(summary['by_difficulty'])}</tbody></table>
<h2 id="per-case-records">문항별 상세 기록</h2><div class="controls"><input id="search" type="search" placeholder="case ID, 질문, 답변, evidence 검색"><select id="purpose"><option value="">모든 평가 목적</option>{purpose_options}</select><select id="lane"><option value="">모든 실행 lane</option>{lane_options}</select><select id="asset-type"><option value="">모든 자산 유형</option><option value="rag">rag</option><option value="parser">parser</option></select><select id="execution-lineage"><option value="">모든 실행 계보</option>{lineage_options}</select><select id="difficulty"><option value="">모든 난이도</option><option>easy</option><option>medium</option><option>hard</option><option>not_applicable</option></select><select id="verdict"><option value="">모든 판정</option><option>accepted</option><option>rejected</option><option>parser_passed</option></select><label><input id="failures" type="checkbox"> 실패만</label><strong id="visible">131 / 131</strong></div>
<div id="cases">{''.join(cards)}</div>
<script>const q=id=>document.getElementById(id);const cards=[...document.querySelectorAll('.case')];function filter(){{let n=0;for(const c of cards){{const ok=(!q('search').value||c.dataset.search.includes(q('search').value.toLowerCase()))&&(!q('difficulty').value||c.dataset.difficulty===q('difficulty').value)&&(!q('lane').value||c.dataset.lane===q('lane').value)&&(!q('purpose').value||c.dataset.purpose===q('purpose').value)&&(!q('asset-type').value||c.dataset.type===q('asset-type').value)&&(!q('execution-lineage').value||c.dataset.lineage===q('execution-lineage').value)&&(!q('verdict').value||c.dataset.verdict===q('verdict').value)&&(!q('failures').checked||c.dataset.failure==='1');c.classList.toggle('hidden',!ok);if(ok)n++}}q('visible').textContent=`${{n}} / ${{cards.length}}`;}}for(const id of ['search','difficulty','lane','purpose','asset-type','execution-lineage','verdict','failures'])q(id).addEventListener('input',filter);filter();</script>
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
            "api_parity": _public_api_parity(summary["api_parity"]),
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


def _public_nonnegative_int(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("local_mini131_performance_public_metric_invalid")
    return value


def _public_required_number(
    value: Any, *, minimum: float | None = None, maximum: float | None = None
) -> int | float:
    result = _public_optional_number(value, minimum=minimum, maximum=maximum)
    if result is None:
        raise ValueError("local_mini131_performance_public_metric_invalid")
    return result


def _public_api_group(
    value: Mapping[str, Any], *, expected_key: str, expected_label: str
) -> dict[str, Any]:
    if value.get("key") != expected_key or value.get("label") != expected_label:
        raise ValueError("local_mini131_performance_public_api_group_invalid")
    return {
        "key": expected_key,
        "label": expected_label,
        **_public_group_summary(value),
    }


def _public_common_metric(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != {"value", "eligible", "coverage", "available", "reason"}:
        raise ValueError("local_mini131_performance_public_common_metric_invalid")
    eligible = _public_nonnegative_int(value["eligible"])
    coverage = _public_required_number(value["coverage"], minimum=0, maximum=1)
    available = value["available"]
    reason = value["reason"]
    metric_value = value["value"]
    if not isinstance(available, bool):
        raise ValueError("local_mini131_performance_public_common_metric_invalid")
    if available:
        if eligible == 0 or reason is not None:
            raise ValueError("local_mini131_performance_public_common_metric_invalid")
        metric_value = _public_required_number(metric_value)
    elif (
        metric_value is not None
        or eligible != 0
        or float(coverage) != 0.0
        or reason not in PUBLIC_COMMON_UNAVAILABLE_REASONS
    ):
        raise ValueError("local_mini131_performance_public_common_metric_invalid")
    return {
        "value": metric_value,
        "eligible": eligible,
        "coverage": coverage,
        "available": available,
        "reason": reason,
    }


def _public_first_rank_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "observed_count",
        "mean",
        "median",
        "min",
        "max",
    }:
        raise ValueError("local_mini131_performance_public_objective_invalid")
    observed = _public_nonnegative_int(value["observed_count"])
    result = {
        "observed_count": observed,
        "mean": _public_optional_number(value["mean"], minimum=0),
        "median": _public_optional_number(value["median"], minimum=0),
        "min": _public_optional_number(value["min"], minimum=0),
        "max": _public_optional_number(value["max"], minimum=0),
    }
    rank_values = tuple(result[key] for key in ("mean", "median", "min", "max"))
    if (observed == 0 and any(item is not None for item in rank_values)) or (
        observed > 0 and any(item is None for item in rank_values)
    ):
        raise ValueError("local_mini131_performance_public_objective_invalid")
    return result


def _public_visual_target(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "eligible_case_count",
        "hit_count",
        "hit_rate",
        "first_rank",
    }:
        raise ValueError("local_mini131_performance_public_objective_invalid")
    eligible = _public_nonnegative_int(value["eligible_case_count"])
    hit = _public_nonnegative_int(value["hit_count"])
    if hit > eligible:
        raise ValueError("local_mini131_performance_public_objective_invalid")
    hit_rate = _public_optional_number(value["hit_rate"], minimum=0, maximum=1)
    if (eligible == 0) != (hit_rate is None):
        raise ValueError("local_mini131_performance_public_objective_invalid")
    return {
        "eligible_case_count": eligible,
        "hit_count": hit,
        "hit_rate": hit_rate,
        "first_rank": _public_first_rank_summary(value["first_rank"]),
    }


def _public_objective_metrics(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != OBJECTIVE_COMPANION_KEYS:
        raise ValueError("local_mini131_performance_public_objective_invalid")
    integer_keys = {
        "required_document_hit_count",
        "required_document_total",
        "set_case_count",
        "set_true_positive_total",
        "set_false_positive_total",
        "set_false_negative_total",
        "visual_case_count",
        "analytics_case_count",
        "analytics_deterministic_companion_case_count",
        "analytics_deterministic_companion_pass_count",
        "analytics_deterministic_case_pass_count",
        "analytics_deterministic_field_count",
        "analytics_deterministic_field_pass_count",
        "analytics_numeric_evidence_field_count",
        "unknown_safe_abstention_pass_count",
        "unknown_case_count",
    }
    rate_keys = {
        "required_document_recall",
        "set_exact_match_rate",
        "set_macro_precision",
        "set_macro_recall",
        "set_macro_f1",
        "set_micro_precision",
        "set_micro_recall",
        "set_micro_f1",
        "visual_evidence_availability_rate",
        "analytics_numeric_evidence_availability_rate",
        "analytics_deterministic_companion_complete_rate",
        "analytics_deterministic_case_pass_rate",
        "analytics_deterministic_field_pass_rate",
        "unknown_safe_abstention_rate",
    }
    result: dict[str, Any] = {
        key: _public_nonnegative_int(value[key]) for key in integer_keys
    }
    result.update(
        {
            key: _public_optional_number(value[key], minimum=0, maximum=1)
            for key in rate_keys
        }
    )
    for key in (
        "visual_target_page",
        "visual_target_chunk",
        "visual_target_object_bridge",
    ):
        result[key] = _public_visual_target(value[key])
    fields = value["analytics_numeric_evidence_fields_per_case"]
    if not isinstance(fields, Mapping) or set(fields) != {
        "observed_case_count",
        "mean",
        "min",
        "max",
    }:
        raise ValueError("local_mini131_performance_public_objective_invalid")
    observed = _public_nonnegative_int(fields["observed_case_count"])
    result["analytics_numeric_evidence_fields_per_case"] = {
        "observed_case_count": observed,
        "mean": _public_optional_number(fields["mean"], minimum=0),
        "min": _public_optional_number(fields["min"], minimum=0),
        "max": _public_optional_number(fields["max"], minimum=0),
    }
    return {key: result[key] for key in sorted(result)}


def _public_api_parity(value: Mapping[str, Any]) -> dict[str, Any]:
    primary = value.get("primary_categories")
    scenarios = value.get("scenario_breakdown")
    visual = value.get("visual_subgroups")
    objective = value.get("objective_companion_metrics")
    common = value.get("common_evaluation_metrics")
    reference = value.get("api_reference")
    local = value.get("local_candidate")
    identity = value.get("case_identity")
    comparison = value.get("same_item_comparison")
    if (
        not isinstance(primary, Mapping)
        or set(primary) != set(PRIMARY_CATEGORY_KEYS)
        or not isinstance(scenarios, Mapping)
        or set(scenarios) != set(SCENARIO_KEYS)
        or not isinstance(visual, Mapping)
        or set(visual) != set(VISUAL_SUBGROUP_KEYS)
        or not all(
            isinstance(item, Mapping)
            for group in (primary, scenarios, visual)
            for item in group.values()
        )
        or not isinstance(objective, Mapping)
        or not isinstance(common, Mapping)
        or not isinstance(reference, Mapping)
        or not isinstance(local, Mapping)
        or not isinstance(identity, Mapping)
        or not isinstance(comparison, Mapping)
    ):
        raise ValueError("local_mini131_performance_public_api_parity_invalid")
    safe_common: dict[str, Any] = {}
    for section, expected_keys in EXPECTED_METRIC_KEYS.items():
        metrics = common.get(section)
        if not isinstance(metrics, Mapping) or set(metrics) != set(expected_keys):
            raise ValueError("local_mini131_performance_public_api_parity_invalid")
        safe_common[section] = {
            name: _public_common_metric(metric)
            for name, metric in metrics.items()
            if isinstance(metric, Mapping)
        }
        if len(safe_common[section]) != len(expected_keys):
            raise ValueError("local_mini131_performance_public_api_parity_invalid")
    if (
        reference.get("baseline_id") != API_BASELINE_ID
        or reference.get("generator") != API_GENERATOR
        or reference.get("mean_semantic_score") != 54.845
        or reference.get("accepted") != 58
        or reference.get("rejected") != 71
        or reference.get("rag_count") != 129
        or reference.get("parser_count") != 2
        or reference.get("case_records_sha256") != API_CASE_RECORDS_SHA256
        or reference.get("receipt_sha256") != API_RECEIPT_SHA256
        or local.get("suite_id") != SUITE_ID
        or local.get("generator") != LOCAL_GENERATOR
        or local.get("embedding") != LOCAL_EMBEDDING
        or local.get("execution_profile") != "mac_local_equivalent"
        or local.get("rag_count") != 129
        or local.get("parser_count") != 2
        or not isinstance(local.get("accepted"), int)
        or isinstance(local.get("accepted"), bool)
        or not isinstance(local.get("rejected"), int)
        or isinstance(local.get("rejected"), bool)
        or local.get("accepted") + local.get("rejected") != 129
        or identity.get("validated") is not True
        or identity.get("question_expected_lane_exact_match") is not True
        or identity.get("api_case_records_sha256") != API_CASE_RECORDS_SHA256
        or identity.get("api_receipt_sha256") != API_RECEIPT_SHA256
        or identity.get("case_count") != 131
        or identity.get("rag_case_count") != 129
        or identity.get("parser_case_count") != 2
    ):
        raise ValueError("local_mini131_performance_public_api_parity_invalid")
    safe_reference = {
        "baseline_id": API_BASELINE_ID,
        "generator": API_GENERATOR,
        "mean_semantic_score": _public_required_number(
            reference["mean_semantic_score"], minimum=0, maximum=100
        ),
        "accepted": _public_nonnegative_int(reference["accepted"]),
        "rejected": _public_nonnegative_int(reference["rejected"]),
        "rag_count": _public_nonnegative_int(reference["rag_count"]),
        "parser_count": _public_nonnegative_int(reference["parser_count"]),
        "case_records_sha256": API_CASE_RECORDS_SHA256,
        "receipt_sha256": API_RECEIPT_SHA256,
    }
    safe_local = {
        "suite_id": SUITE_ID,
        "generator": LOCAL_GENERATOR,
        "embedding": LOCAL_EMBEDDING,
        "execution_profile": "mac_local_equivalent",
        "mean_semantic_score": _public_required_number(
            local["mean_semantic_score"], minimum=0, maximum=100
        ),
        "accepted": _public_nonnegative_int(local["accepted"]),
        "rejected": _public_nonnegative_int(local["rejected"]),
        "rag_count": _public_nonnegative_int(local["rag_count"]),
        "parser_count": _public_nonnegative_int(local["parser_count"]),
    }
    safe_identity = {
        "validated": True,
        "case_count": 131,
        "rag_case_count": 129,
        "parser_case_count": 2,
        "question_expected_lane_exact_match": True,
        "api_case_records_sha256": API_CASE_RECORDS_SHA256,
        "api_receipt_sha256": API_RECEIPT_SHA256,
    }
    safe_comparison = {
        key: (
            _public_required_number(comparison[key])
            if key == "mean_score_delta"
            else _public_nonnegative_int(comparison[key])
        )
        for key in (
            "case_count",
            "rag_case_count",
            "parser_case_count",
            "mean_score_delta",
            "local_higher_score",
            "api_higher_score",
            "equal_score",
            "verdict_same",
            "verdict_changed",
            "status_same",
            "status_changed",
        )
    }
    result = {
        "primary_categories": {
            key: _public_api_group(
                primary[key],
                expected_key=key,
                expected_label=PURPOSE_DEFINITIONS[key]["label"],
            )
            for key in PRIMARY_CATEGORY_KEYS
        },
        "scenario_breakdown": {
            key: _public_api_group(
                scenarios[key],
                expected_key=key,
                expected_label=PURPOSE_DEFINITIONS[key]["label"],
            )
            for key in SCENARIO_KEYS
        },
        "visual_subgroups": {
            key: _public_api_group(
                visual[key],
                expected_key=key,
                expected_label=VISUAL_SUBGROUP_DEFINITIONS[key]["label"],
            )
            for key in VISUAL_SUBGROUP_KEYS
        },
        "objective_companion_metrics": _public_objective_metrics(objective),
        "common_evaluation_metrics": safe_common,
        "api_reference": safe_reference,
        "local_candidate": safe_local,
        "case_identity": safe_identity,
        "same_item_comparison": safe_comparison,
    }
    _validate_content_free_receipt(result)
    return result


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
            name not in PUBLIC_DETERMINISTIC_METRIC_NAMES
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


def _validate_content_free_receipt(
    value: Any, *, path: tuple[str, ...] = ()
) -> None:
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
        for key, nested in value.items():
            name = str(key)
            if name in forbidden and not (
                name == "answer"
                and path
                and path[-1] == "common_evaluation_metrics"
            ):
                raise ValueError("local_mini131_performance_public_content_forbidden")
            _validate_content_free_receipt(nested, path=(*path, name))
    elif isinstance(value, list):
        for nested in value:
            _validate_content_free_receipt(nested, path=path)


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
