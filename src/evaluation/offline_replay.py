"""저장된 통합 모델 결과를 외부 API 호출 없이 재검증한다."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


_REQUIRED_FIELDS = {
    "query", "answer", "provider", "model", "abstained", "cited_doc_ids",
    "unsupported_citations", "evidence", "retrieval_config",
}


def validate_integrated_result(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = _REQUIRED_FIELDS - set(record)
    if missing:
        errors.append("missing_fields:" + ",".join(sorted(missing)))
        return errors
    if not isinstance(record["query"], str) or not record["query"].strip():
        errors.append("invalid_query")
    if not isinstance(record["answer"], str):
        errors.append("invalid_answer")
    if not isinstance(record["evidence"], list):
        errors.append("invalid_evidence")
        evidence = []
    else:
        evidence = record["evidence"]
    available = {
        item.get("doc_id") for item in evidence if isinstance(item, dict) and item.get("doc_id")
    }
    cited = record["cited_doc_ids"] if isinstance(record["cited_doc_ids"], (list, tuple)) else []
    calculated_unsupported = sorted(set(cited) - available)
    reported = record["unsupported_citations"]
    if not isinstance(reported, (list, tuple)) or sorted(reported) != calculated_unsupported:
        errors.append("unsupported_citation_mismatch")
    if calculated_unsupported:
        errors.append("unsupported_citations_present")
    return errors


def summarize_integrated_results(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(records)
    validations = [validate_integrated_result(row) for row in rows]
    answered = sum(not bool(row.get("abstained")) for row in rows)
    with_citations = sum(bool(row.get("cited_doc_ids")) for row in rows if not row.get("abstained"))
    return {
        "total": len(rows),
        "answered": answered,
        "abstained": len(rows) - answered,
        "valid": sum(not errors for errors in validations),
        "invalid": sum(bool(errors) for errors in validations),
        "answered_with_citation_rate": with_citations / answered if answered else 0.0,
        "errors": [
            {"index": index, "errors": errors}
            for index, errors in enumerate(validations)
            if errors
        ],
    }


def load_results(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    payload = json.loads(text)
    if isinstance(payload, dict) and set(payload) >= {"runtime", "result"}:
        return [payload["result"]]
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list) and all(isinstance(item, dict) for item in payload):
        return payload
    raise ValueError("통합 결과는 JSON 객체, 객체 배열 또는 JSONL이어야 합니다")
