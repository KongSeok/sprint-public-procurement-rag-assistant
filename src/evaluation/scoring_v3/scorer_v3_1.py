#!/usr/bin/env python3
"""결정론적 골든셋 채점기 v3.1.0 실험판.

v3.0.1의 사실 매칭은 유지하고, 답변 첫 문장에서 최종 판단을 명시적으로
기권한 뒤 확인 가능한 배경 근거를 설명하는 응답을 정상 기권으로 처리한다.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from . import scorer as _V3


SCORER_VERSION = "3.1.0"
SCORING_SCHEMA_VERSION = "3.1"
_BASE = _V3._BASE
_LEADING_ABSTENTION_RE = re.compile(
    r"^\s*(?:확인\s*(?:되지\s*않|할\s*수\s*없)|알\s*수\s*없|"
    r"판단\s*(?:할\s*수)?\s*없|판정\s*(?:할\s*수)?\s*없)",
    re.IGNORECASE,
)
_DEFINITIVE_AFTER_ABSTENTION_RE = re.compile(
    r"(?:따라서|그러므로|결론적으로)?[^.!?\n]{0,50}"
    r"(?:낮|높|가능|불가능|충족|미충족)[^.!?\n]{0,12}"
    r"(?:습니다|입니다|합니다|된다|이다)",
    re.IGNORECASE,
)


read_jsonl = _V3.read_jsonl
write_jsonl = _V3.write_jsonl
select_rows = _V3.select_rows
normalize_text = _V3.normalize_text
string_list = _V3.string_list
item_id = _V3.item_id
option_matches = _V3.option_matches


def classify_response(answer: str | None, execution_error: str | None = None) -> dict[str, Any]:
    """명시적 선두 기권과 근거 설명을 분리한다."""
    if execution_error and str(execution_error).strip():
        return {"response_status": "execution_error", "status_method": "explicit_error"}
    if answer is None or not str(answer).strip():
        return {"response_status": "empty_response", "status_method": "empty_guard"}

    body = _BASE._CITATION_LINE_RE.sub("", str(answer)).strip()
    leading = _LEADING_ABSTENTION_RE.match(body)
    if leading:
        remainder = body[leading.end():]
        if not _DEFINITIVE_AFTER_ABSTENTION_RE.search(remainder):
            return {
                "response_status": "abstained",
                "status_method": "leading_abstention_with_context_v3_1",
            }
    return _V3.classify_response(answer, execution_error)


def _configure_base() -> None:
    _BASE.SCORER_VERSION = SCORER_VERSION
    _BASE.SCORING_SCHEMA_VERSION = SCORING_SCHEMA_VERSION
    _BASE.classify_response = classify_response
    _BASE.option_matches = option_matches


def score_item(row: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
    _configure_base()
    return _BASE.score_item(row, prediction)


def evaluate(
    golden_rows: list[dict[str, Any]], prediction_rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    _configure_base()
    details, summary = _BASE.evaluate(golden_rows, prediction_rows)
    summary["scorer_version"] = SCORER_VERSION
    summary["scoring_schema_version"] = SCORING_SCHEMA_VERSION
    summary["abstention_update"] = "leading explicit abstention with supporting context"
    summary["limitations"] = [
        "선두 기권 판정은 결정론적 휴리스틱이며 의미 기반 판정이 아닙니다.",
        "기권 뒤에 명백한 결론 표현이 있으면 partial_answer 판정을 유지합니다.",
        "lexical_fact_score는 의미 채점이 아닌 보조지표입니다.",
    ]
    return details, summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="골든셋 결정론적 채점기 v3.1")
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
