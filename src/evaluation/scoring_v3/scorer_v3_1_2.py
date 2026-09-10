#!/usr/bin/env python3
"""결정론적 골든셋 채점기 v3.1.2.

v3.1.0의 응답/사실 채점은 그대로 유지한다. 인용은 내용과 형식을 분리해
정상(valid), 위치 오류(misplaced), 누락(missing)으로 진단하고, 실행 결과에
문항별 실패 원인을 추가한다.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from . import scorer_v3_1 as _V31


SCORER_VERSION = "3.1.2"
SCORING_SCHEMA_VERSION = "3.1.2"
_BASE = _V31._BASE
_CITATION_ANYWHERE_RE = re.compile(
    r"\[\s*근거\s*:\s*(.+)\](?=\s*(?:\n|$))", re.IGNORECASE
)
_CITATION_AT_END_RE = re.compile(
    r"\[\s*근거\s*:\s*(.+)\]\s*$", re.IGNORECASE
)


read_jsonl = _V31.read_jsonl
write_jsonl = _V31.write_jsonl
select_rows = _V31.select_rows
normalize_text = _V31.normalize_text
string_list = _V31.string_list
item_id = _V31.item_id
option_matches = _V31.option_matches
classify_response = _V31.classify_response


def _citation_diagnostics(answer: str | None) -> tuple[str, list[str]]:
    text = str(answer or "")
    matches = list(_CITATION_ANYWHERE_RE.finditer(text))
    if not matches:
        return "missing", []
    last = matches[-1]
    cited = [part.strip() for part in last.group(1).split(",") if part.strip()]
    status = "valid" if _CITATION_AT_END_RE.search(text) else "misplaced"
    return status, cited


def _add_citation_diagnostics(
    row: dict[str, Any], prediction: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    status, cited_raw = _citation_diagnostics(result.get("answer"))
    cited = _BASE.normalized_document_set(cited_raw)
    required = _BASE.gold_citation_set(row)
    retrieved = _BASE.prediction_document_set(prediction)
    matched = len(cited & required)
    result.update({
        "citation_status": status,
        "citation_format_pass": status == "valid",
        "citation_content_available": bool(cited_raw),
        "cited_doc_ids": cited_raw,
        "citation_recall": matched / len(required) if required else None,
        "citation_precision": matched / len(cited) if cited else (0.0 if required else None),
        "unsupported_citation_count": len(cited - retrieved) if retrieved else None,
    })
    return result


def _failure_reasons(result: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    status = result.get("response_status")
    if status == "execution_error":
        return ["execution_error"]
    if status == "empty_response":
        return ["empty_response"]
    if result.get("retrieval_recall") == 0:
        reasons.append("retrieval_failure")
    if result.get("context_fact_coverage") == 0:
        reasons.append("context_fact_missing")
    if result.get("abstention_match") is False:
        reasons.append("abstention_mismatch")
    if result.get("list_f1") is not None and result.get("list_f1") < 1:
        reasons.append("set_mismatch")
    if result.get("lexical_fact_score") is not None and result.get("lexical_fact_score") < 100:
        reasons.append("fact_incomplete_or_mismatch")
    citation_status = result.get("citation_status")
    if citation_status == "missing":
        reasons.append("citation_missing")
    elif citation_status == "misplaced":
        reasons.append("citation_misplaced")
    if (result.get("unsupported_citation_count") or 0) > 0:
        reasons.append("unsupported_citation")
    return reasons or ["none"]


def _configure_base() -> None:
    _BASE.SCORER_VERSION = SCORER_VERSION
    _BASE.SCORING_SCHEMA_VERSION = SCORING_SCHEMA_VERSION
    _BASE.classify_response = classify_response
    _BASE.option_matches = option_matches


def score_item(row: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
    _configure_base()
    result = _BASE.score_item(row, prediction)
    _add_citation_diagnostics(row, prediction, result)
    result["failure_reasons"] = _failure_reasons(result)
    return result


def evaluate(
    golden_rows: list[dict[str, Any]], prediction_rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    prediction_by_id = {item_id(row): row for row in prediction_rows}
    details = [score_item(row, prediction_by_id.get(item_id(row), {})) for row in golden_rows]
    _, summary = _V31.evaluate(golden_rows, prediction_rows)

    def mean(field: str) -> float | None:
        values = [float(row[field]) for row in details if row.get(field) is not None]
        return sum(values) / len(values) if values else None

    citation_counts = Counter(row["citation_status"] for row in details)
    reason_counts = Counter(
        reason for row in details for reason in row["failure_reasons"] if reason != "none"
    )
    summary.update({
        "scorer_version": SCORER_VERSION,
        "scoring_schema_version": SCORING_SCHEMA_VERSION,
        "citation_format_pass_rate": mean("citation_format_pass"),
        "citation_content_available_rate": mean("citation_content_available"),
        "citation_recall": mean("citation_recall"),
        "citation_precision": mean("citation_precision"),
        "citation_status_counts": dict(citation_counts),
        "failure_reason_counts": dict(reason_counts),
        "citation_update": "nested brackets in document IDs supported; content metrics separated from final-line format",
    })
    summary["limitations"] = list(summary.get("limitations") or []) + [
        "citation_misplaced는 인용 내용 점수는 계산하지만 형식 통과로 인정하지 않습니다.",
        "failure_reasons는 원인 후보를 분리하는 결정론적 진단값이며 인과관계 확정값이 아닙니다.",
    ]
    return details, summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="골든셋 결정론적 채점기 v3.1.2")
    parser.add_argument("--golden", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--details-output", type=Path)
    parser.add_argument("--include-disabled", action="store_true")
    parser.add_argument("--task-type", default="all")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    golden = select_rows(read_jsonl(args.golden), args.task_type, args.include_disabled)
    predictions = read_jsonl(args.predictions)
    details, summary = evaluate(golden, predictions)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.details_output:
        write_jsonl(args.details_output, details)


if __name__ == "__main__":
    main()
