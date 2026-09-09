from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable


SCORER_VERSION = "2.0.0"
SCORING_SCHEMA_VERSION = "2.0"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: JSON 오류: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: JSON 객체가 아닙니다.")
            rows.append(row)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_text(value: Any) -> str:
    """비교용 정규화다. 원본 답변 저장값은 절대로 이 값으로 덮어쓰지 않는다."""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[^0-9a-z가-힣%]+", "", text)


def string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    if " | " in text:
        return [part.strip() for part in text.split(" | ") if part.strip()]
    return [text]


def item_id(row: dict[str, Any]) -> str:
    return str(row.get("id") or row.get("case_id") or "").strip()


def effective_disabled_reason(row: dict[str, Any]) -> str | None:
    flags = set(string_list(row.get("status_flags")))
    capability = str(row.get("capability") or row.get("task_type") or "qa")
    if row.get("enabled", True) is False:
        return "enabled_false"
    if "csv_only_unverified_reverify_with_raw_docs" in flags:
        return "csv_only_unverified"
    if capability == "followup" or "needs_multiturn_context_handling" in flags:
        return "followup_context_missing"
    return None


def select_rows(
    rows: list[dict[str, Any]], task_type: str = "all", include_disabled: bool = False
) -> list[dict[str, Any]]:
    selected = []
    for row in rows:
        if not include_disabled and effective_disabled_reason(row):
            continue
        row_task = str(row.get("task_type") or "qa")
        if task_type != "all" and row_task != task_type:
            continue
        selected.append(row)
    return selected


_CITATION_LINE_RE = re.compile(r"\[\s*근거\s*:\s*(.+?)\]\s*$", re.DOTALL)
_ABSTENTION_RE = re.compile(
    r"(?:"
    r"알\s*수\s*없|"
    r"확인\s*(?:할\s*수)?\s*없|"
    r"판단\s*(?:을\s*)?(?:해\s*드릴\s*)?(?:할\s*수|수)?\s*없|"
    r"판정\s*(?:을\s*)?(?:해\s*드릴\s*)?(?:할\s*수|수)?\s*없|"
    r"확정\s*(?:할\s*수)?\s*없|계산\s*(?:할\s*수)?\s*없|"
    r"예측\s*(?:할\s*수)?\s*없|제공\s*(?:할\s*수)?\s*없|"
    r"수행\s*(?:할\s*수)?\s*없|답변\s*(?:할\s*수)?\s*없|"
    r"명시\s*되어\s*있지\s*않|제공\s*되지\s*않|"
    r"정보(?:가|는)?\s*없|자료(?:가|는)?\s*없|불가능"
    r")",
    re.IGNORECASE,
)
_ABSTENTION_BOILERPLATE_RE = re.compile(
    r"(?:제공된\s*문서(?:의)?\s*범위에서는?|"
    r"검색된\s*문서(?:의)?\s*범위에서는?|"
    r"원문\s*전체\s*확인이\s*필요할\s*수\s*있습니다|"
    r"관련\s*자료를\s*추가로\s*확인해\s*주세요)",
    re.IGNORECASE,
)


def extract_cited_doc_ids(answer: str | None) -> list[str]:
    if not answer:
        return []
    match = _CITATION_LINE_RE.search(str(answer))
    if not match:
        return []
    return [part.strip() for part in match.group(1).split(",") if part.strip()]


def classify_response(
    answer: str | None, execution_error: str | None = None
) -> dict[str, Any]:
    """응답을 answered/partial_answer/abstained/empty_response/execution_error로 나눈다.

    partial_answer 판정은 규칙 기반 휴리스틱이므로 결과에 판정 방식도 함께 남긴다.
    """
    if execution_error and str(execution_error).strip():
        return {"response_status": "execution_error", "status_method": "explicit_error"}
    if answer is None or not str(answer).strip():
        return {"response_status": "empty_response", "status_method": "empty_guard"}

    body = _CITATION_LINE_RE.sub("", str(answer)).strip()
    if not _ABSTENTION_RE.search(body):
        return {"response_status": "answered", "status_method": "heuristic_v2"}

    residue = _ABSTENTION_RE.sub(" ", body)
    residue = _ABSTENTION_BOILERPLATE_RE.sub(" ", residue)
    residue_norm = normalize_text(residue)
    has_answer_signal = bool(re.search(r"\d", residue_norm)) or len(residue_norm) >= 15
    return {
        "response_status": "partial_answer" if has_answer_signal else "abstained",
        "status_method": "heuristic_v2",
    }


def _date_keys(value: Any) -> set[str]:
    text = unicodedata.normalize("NFKC", str(value or ""))
    pattern = re.compile(r"(20\d{2})\s*(?:년|[./-])\s*(\d{1,2})\s*(?:월|[./-])\s*(\d{1,2})\s*일?")
    return {
        f"{match.group(1)}{int(match.group(2)):02d}{int(match.group(3)):02d}"
        for match in pattern.finditer(text)
    }


def _number_keys(value: Any) -> set[str]:
    text = unicodedata.normalize("NFKC", str(value or "")).replace(",", "")
    return {token.lstrip("0") or "0" for token in re.findall(r"\d+(?:\.\d+)?", text)}


def option_matches(answer: str, option: str, token_threshold: float = 0.4) -> bool:
    """기존 V4 어휘 채점과 가까운 결정론적 보조지표다. 의미 정답 판정이 아니다."""
    answer_norm = normalize_text(answer)
    option_norm = normalize_text(option)
    if option_norm and option_norm in answer_norm:
        return True

    option_dates = _date_keys(option)
    if option_dates and not option_dates.issubset(_date_keys(answer)):
        return False
    option_numbers = {n for n in _number_keys(option) if len(n) >= 2}
    if option_numbers and not option_numbers.issubset(_number_keys(answer)):
        return False

    tokens = re.findall(r"[0-9a-z가-힣%]+", unicodedata.normalize("NFKC", str(option)).casefold())
    suffixes = ("입니다", "이다", "한다", "된다", "있다", "없다", "이며", "해야", "까지", "부터")
    meaningful: list[str] = []
    for token in tokens:
        if token[:1].isdigit():
            continue
        for suffix in suffixes:
            if token.endswith(suffix) and len(token) > len(suffix):
                token = token[: -len(suffix)]
                break
        token = re.sub(r"(은|는|이|가|을|를|에|의|와|과|로|으로)$", "", token)
        token = normalize_text(token)
        if len(token) >= 2:
            meaningful.append(token)
    if not meaningful:
        return bool(option_dates or option_numbers)
    matched = sum(token in answer_norm for token in meaningful)
    return matched / len(meaningful) >= token_threshold


def fact_groups(row: dict[str, Any]) -> list[list[str]]:
    gold = row.get("gold") if isinstance(row.get("gold"), dict) else {}
    key_points = gold.get("required_key_points")
    if isinstance(key_points, list) and key_points:
        groups = []
        for point in key_points:
            if isinstance(point, dict):
                values = point.get("alternatives") or point.get("variants") or [point.get("text")]
            else:
                values = [point]
            clean = [str(value) for value in string_list(values) if str(value).strip()]
            if clean:
                groups.append(clean)
        return groups

    facts = row.get("required_fact_groups")
    if not facts:
        facts = row.get("required_facts", [])
    groups: list[list[str]] = []
    for fact in facts or []:
        alternatives = fact if isinstance(fact, list) else [fact]
        clean = [str(value) for value in alternatives if str(value).strip()]
        if clean:
            groups.append(clean)
    return groups


def expected_decision(row: dict[str, Any]) -> str:
    gold = row.get("gold") if isinstance(row.get("gold"), dict) else {}
    decision = str(gold.get("decision") or row.get("decision") or "").strip().lower()
    if decision:
        return decision
    return "abstain" if str(row.get("capability") or "").lower() == "abstain" else "answer"


def normalized_document_set(values: Any) -> set[str]:
    result = set()
    for value in string_list(values):
        if Path(value).suffix.lower() == ".csv":
            continue
        key = normalize_text(value)
        if key:
            result.add(key)
    return result


def gold_document_set(row: dict[str, Any]) -> set[str]:
    identifiers = normalized_document_set(
        row.get("expected_doc_id") or row.get("required_doc_ids") or row.get("source_document_ids")
    )
    return identifiers or normalized_document_set(row.get("source_labels") or row.get("source_documents"))


def gold_citation_set(row: dict[str, Any]) -> set[str]:
    """답변의 인용은 사람이 읽는 파일명을 우선 사용하므로 해시 ID보다 라벨을 먼저 본다."""
    labels = normalized_document_set(
        row.get("expected_doc_id") or row.get("source_labels") or row.get("source_documents")
    )
    return labels or normalized_document_set(row.get("required_doc_ids") or row.get("source_document_ids"))


def prediction_document_set(row: dict[str, Any]) -> set[str]:
    for key in (
        "returned_document_ids", "document_ids", "returned_documents",
        "answer_documents", "source_documents", "retrieved_doc_ids",
    ):
        values = normalized_document_set(row.get(key))
        if values:
            return values
    return set()


def _base_result(row: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
    answer = prediction.get("answer", prediction.get("generated_answer"))
    error = prediction.get("execution_error", prediction.get("generation_error"))
    status = classify_response(answer, error)
    return {
        "id": item_id(row),
        "question": row.get("question") or row.get("query"),
        "task_type": row.get("task_type") or "qa",
        "capability": row.get("capability") or "qa",
        "answer": answer,
        "execution_error": error,
        "retrieved_doc_ids": string_list(
            prediction.get("retrieved_doc_ids") or prediction.get("context_doc_ids")
        ),
        "retrieval_recall": prediction.get("retrieval_recall"),
        "context_fact_coverage": prediction.get("context_fact_coverage"),
        "elapsed_seconds": prediction.get("elapsed_seconds"),
        **status,
        "scorer_version": SCORER_VERSION,
        "scoring_schema_version": SCORING_SCHEMA_VERSION,
    }


def score_item(row: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
    result = _base_result(row, prediction)
    status = result["response_status"]
    capability = str(row.get("capability") or "").lower()
    is_set = capability == "list_condition" or str(row.get("lane") or "").lower() == "set"

    result.update({
        "scoring_layer": "set" if is_set else "lexical_fact",
        "scoring_status": "scored",
        "lexical_fact_score": None,
        "conditional_score": None,
        "end_to_end_score": 0.0,
        "facts_matched": None,
        "facts_total": None,
        "exact_fact_pass": None,
        "abstention_match": None,
        "list_precision": None,
        "list_recall": None,
        "list_f1": None,
        "exact_set_match": None,
        "count_accuracy": None,
    })

    if status in {"execution_error", "empty_response"}:
        result["scoring_status"] = status
        return _add_citation_scores(row, prediction, result)

    if is_set:
        expected = gold_document_set(row)
        returned = prediction_document_set(prediction)
        if not expected:
            result["scoring_status"] = "unscorable_missing_gold_document_set"
            result["end_to_end_score"] = None
            return _add_citation_scores(row, prediction, result)
        tp = len(expected & returned)
        precision = tp / len(returned) if returned else 0.0
        recall = tp / len(expected)
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        result.update({
            "list_precision": precision,
            "list_recall": recall,
            "list_f1": f1,
            "exact_set_match": returned == expected,
            "count_accuracy": len(returned) == len(expected),
            "conditional_score": f1 * 100,
            "end_to_end_score": f1 * 100,
            "expected_document_count": len(expected),
            "returned_document_count": len(returned),
        })
        return _add_citation_scores(row, prediction, result)

    decision = expected_decision(row)
    expected_abstention = decision == "abstain"
    actual_abstention = status == "abstained"
    result["abstention_match"] = actual_abstention == expected_abstention
    if expected_abstention:
        score = 100.0 if actual_abstention else 0.0
        result.update({
            "scoring_layer": "abstention",
            "conditional_score": score,
            "end_to_end_score": score,
            "exact_fact_pass": bool(score == 100),
        })
        return _add_citation_scores(row, prediction, result)

    groups = fact_groups(row)
    if not groups:
        result["scoring_status"] = "unscorable_missing_required_facts"
        result["end_to_end_score"] = None
        return _add_citation_scores(row, prediction, result)
    answer = str(result.get("answer") or "")
    matches = [any(option_matches(answer, option) for option in group) for group in groups]
    score = sum(matches) / len(matches) * 100
    result.update({
        "lexical_fact_score": score,
        "conditional_score": score,
        "end_to_end_score": score,
        "facts_matched": sum(matches),
        "facts_total": len(matches),
        "exact_fact_pass": all(matches),
    })
    return _add_citation_scores(row, prediction, result)


def _add_citation_scores(
    row: dict[str, Any], prediction: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    cited_raw = extract_cited_doc_ids(result.get("answer"))
    cited = normalized_document_set(cited_raw)
    required = gold_citation_set(row)
    retrieved = prediction_document_set(prediction)
    matched = len(cited & required)
    result.update({
        "citation_format_pass": bool(cited_raw),
        "cited_doc_ids": cited_raw,
        "citation_recall": matched / len(required) if required else None,
        "citation_precision": matched / len(cited) if cited else (0.0 if required else None),
        "unsupported_citation_count": len(cited - retrieved) if retrieved else None,
    })
    return result


def evaluate(
    golden_rows: list[dict[str, Any]], prediction_rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    golden_ids = [item_id(row) for row in golden_rows]
    prediction_ids = [item_id(row) for row in prediction_rows]
    if not all(golden_ids) or len(golden_ids) != len(set(golden_ids)):
        raise ValueError("골든셋 ID가 비어 있거나 중복되었습니다.")
    if not all(prediction_ids) or len(prediction_ids) != len(set(prediction_ids)):
        raise ValueError("예측 결과 ID가 비어 있거나 중복되었습니다.")

    predictions = dict(zip(prediction_ids, prediction_rows))
    details = [score_item(row, predictions.get(item_id(row), {})) for row in golden_rows]
    unknown_prediction_ids = sorted(set(prediction_ids) - set(golden_ids))

    def mean(field: str, rows: list[dict[str, Any]] = details) -> float | None:
        values = [float(row[field]) for row in rows if row.get(field) is not None]
        return sum(values) / len(values) if values else None

    valid_responses = [
        row for row in details if row["response_status"] not in {"execution_error", "empty_response"}
    ]
    scorable = [row for row in details if row.get("end_to_end_score") is not None]
    set_rows = [row for row in details if row.get("list_f1") is not None]
    status_counts = {
        status: sum(row["response_status"] == status for row in details)
        for status in ("answered", "partial_answer", "abstained", "empty_response", "execution_error")
    }
    summary = {
        "scorer_version": SCORER_VERSION,
        "scoring_schema_version": SCORING_SCHEMA_VERSION,
        "evaluated_count": len(details),
        "scorable_count": len(scorable),
        "response_status_counts": status_counts,
        "generation_success_rate": len(valid_responses) / len(details) if details else 0.0,
        "execution_error_rate": status_counts["execution_error"] / len(details) if details else 0.0,
        "empty_response_rate": status_counts["empty_response"] / len(details) if details else 0.0,
        "conditional_score": mean("conditional_score"),
        "end_to_end_score": mean("end_to_end_score", scorable),
        "average_lexical_fact_score": mean("lexical_fact_score"),
        "retrieval_recall": mean("retrieval_recall"),
        "context_fact_coverage": mean("context_fact_coverage"),
        "abstention_match_rate": mean("abstention_match"),
        "citation_format_pass_rate": mean("citation_format_pass"),
        "citation_recall": mean("citation_recall"),
        "citation_precision": mean("citation_precision"),
        "list_macro_precision": mean("list_precision", set_rows),
        "list_macro_recall": mean("list_recall", set_rows),
        "list_macro_f1": mean("list_f1", set_rows),
        "exact_set_match_rate": mean("exact_set_match", set_rows),
        "count_accuracy": mean("count_accuracy", set_rows),
        "unknown_prediction_ids": unknown_prediction_ids,
        "limitations": [
            "lexical_fact_score는 의미 채점이 아닌 결정론적 보조지표입니다.",
            "partial_answer는 heuristic_v2 규칙 판정입니다.",
            "LLM correctness/faithfulness/completeness는 이 버전에 포함되지 않았습니다.",
        ],
    }
    return details, summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="골든셋 공용 결정론적 채점기 v2")
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
