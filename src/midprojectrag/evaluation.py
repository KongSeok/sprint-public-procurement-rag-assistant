from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping, Sequence

from midprojectrag.ingest.common import (
    canonical_json,
    read_jsonl,
    require_within,
    sha256_file,
    sha256_text,
    write_json,
)


TASK_TYPES = ("single_doc", "multi_doc_compare", "follow_up", "unknown")
SPLITS = ("dev", "heldout")
ABSTENTION_REASONS = ("insufficient_evidence", "out_of_scope", "ambiguous")
TASK_ALIASES = {
    "single_doc": "single",
    "multi_doc_compare": "multi",
    "follow_up": "followup",
    "unknown": "unknown",
}
DEFAULT_MINIMUM_CASES = {
    "dev": {task: 10 for task in TASK_TYPES},
    "heldout": {task: 5 for task in TASK_TYPES},
}
SAFE_ABSTENTION_ANSWERS = {
    "insufficient_evidence": "제공된 문서에서 답변 근거를 찾지 못했습니다.",
    "out_of_scope": "질문이 제공된 문서 범위를 벗어납니다.",
    "ambiguous": "질문이 모호하여 답변하려면 추가 정보가 필요합니다.",
}
STACK_IDS = ("api", "gcp_local")
REQUIRED_COMMON_THRESHOLDS = frozenset(
    {
        "metrics.retrieval.document_recall_at_5",
        "metrics.retrieval.all_required_docs_recalled_at_10",
        "metrics.answer.key_point_coverage",
        "metrics.answer.citation_validity",
        "metrics.answer.gold_citation_precision",
        "metrics.answer.faithfulness",
        "metrics.answer.follow_up_success",
        "metrics.answer.judgment_coverage",
        "metrics.abstention.recall",
        "metrics.abstention.safe_abstention_rate",
        "metrics.abstention.false_answer_rate",
        "metrics.operations.response_contract_error_rate",
        "metrics.operations.runtime_error_rate",
    }
)
REQUIRED_STACK_THRESHOLDS = {
    "metrics.operations.total_cost_usd": "api",
    "metrics.operations.api_cost_coverage": "api",
    "metrics.operations.local_gpu_usage_coverage": "gcp_local",
}
FROZEN_THRESHOLDS: dict[str, tuple[str, float, tuple[str, ...] | None]] = {
    "metrics.retrieval.document_recall_at_5": (">=", 0.9, None),
    "metrics.retrieval.all_required_docs_recalled_at_10": (">=", 0.8, None),
    "metrics.answer.key_point_coverage": (">=", 0.8, None),
    "metrics.answer.citation_validity": (">=", 0.95, None),
    "metrics.answer.gold_citation_precision": (">=", 0.95, None),
    "metrics.answer.faithfulness": (">=", 0.9, None),
    "metrics.answer.follow_up_success": (">=", 0.8, None),
    "metrics.answer.judgment_coverage": (">=", 1.0, None),
    "metrics.abstention.recall": (">=", 0.8, None),
    "metrics.abstention.safe_abstention_rate": (">=", 1.0, None),
    "metrics.abstention.false_answer_rate": ("<=", 0.2, None),
    "metrics.operations.response_contract_error_rate": ("<=", 0.0, None),
    "metrics.operations.runtime_error_rate": ("<=", 0.0, None),
    "metrics.operations.total_cost_usd": ("<=", 20.0, ("api",)),
    "metrics.operations.api_cost_coverage": (">=", 1.0, ("api",)),
    "metrics.operations.local_gpu_usage_coverage": (">=", 1.0, ("gcp_local",)),
}
REQUIRED_METRIC_SECTIONS = frozenset(
    {"retrieval", "answer", "abstention", "task_success", "operations"}
)
EXPECTED_METRIC_KEYS = {
    "retrieval": frozenset(
        {
            *(f"document_recall_at_{k}" for k in (1, 3, 5, 10)),
            *(f"source_block_recall_at_{k}" for k in (1, 3, 5, 10)),
            *(f"all_required_docs_recalled_at_{k}" for k in (1, 3, 5, 10)),
            "mrr_at_10",
            "ndcg_at_10",
        }
    ),
    "answer": frozenset(
        {
            "key_point_coverage",
            "correctness",
            "faithfulness",
            "factual_claim_coverage",
            "citation_validity",
            "gold_citation_precision",
            "follow_up_success",
            "judgment_coverage",
        }
    ),
    "abstention": frozenset(
        {"precision", "recall", "safe_abstention_rate", "false_answer_rate", "answerable_false_abstain_rate"}
    ),
    "task_success": frozenset(TASK_TYPES),
    "operations": frozenset(
        {
            "response_contract_error_rate",
            "runtime_error_rate",
            "latency_total_p50_ms",
            "latency_total_p95_ms",
            "latency_retrieval_p50_ms",
            "latency_generation_p50_ms",
            "total_cost_usd",
            "mean_cost_usd",
            "total_gpu_seconds",
            "mean_gpu_seconds",
            "peak_vram_gb",
            "api_cost_coverage",
            "local_gpu_usage_coverage",
        }
    ),
}

DOC_ID_RE = re.compile(r"^doc_[0-9a-f]{24}$")
BLOCK_ID_RE = re.compile(r"^block_[0-9a-f]{24}$")
CHUNK_ID_RE = re.compile(r"^chunk_[0-9a-f]{24}$")
VISUAL_CHUNK_ID_RE = re.compile(r"^vchunk_[0-9a-f]{24}$")
VISUAL_OCCURRENCE_ID_RE = re.compile(r"^vocc2_[0-9a-f]{24}$")
VISUAL_EVIDENCE_ID_RE = re.compile(r"^(?:ocr|cap)_[0-9a-f]{24}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CASE_ID_RE = re.compile(r"^(dev|heldout)-(single|multi|followup|unknown)-[0-9]{3}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
KEY_POINT_ID_RE = re.compile(r"^kp_[A-Za-z0-9._:-]{1,64}$")


def _issue(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _validate_required(
    value: Mapping[str, Any],
    required: Iterable[str],
    allowed: Iterable[str],
    path: str,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    required_set = set(required)
    allowed_set = set(allowed)
    for key in sorted(required_set - value.keys()):
        issues.append(_issue("required_field_missing", f"{path}.{key}", "required field is missing"))
    for key in sorted(value.keys() - allowed_set):
        issues.append(_issue("unknown_field", f"{path}.{key}", "field is not allowed by the contract"))
    return issues


def _validate_safe_id(value: Any, path: str) -> list[dict[str, str]]:
    if not isinstance(value, str) or SAFE_ID_RE.fullmatch(value) is None:
        return [_issue("invalid_id", path, "must be a non-empty portable identifier")]
    return []


def _validate_visual_evidence_binding(
    evidence_ids: Any,
    evidence_type: Any,
    path: str,
) -> list[dict[str, str]]:
    """Require evidence IDs to identify the lane that produced them.

    Layout chunks are projections of OCR layout output and therefore retain the
    ``ocr_`` evidence identity. Captions are independently generated and use
    ``cap_`` identities.
    """

    if (
        not isinstance(evidence_ids, list)
        or not isinstance(evidence_type, str)
        or evidence_type not in {"ocr", "layout", "caption"}
    ):
        return []
    expected_prefix = "cap_" if evidence_type == "caption" else "ocr_"
    if any(
        isinstance(evidence_id, str)
        and VISUAL_EVIDENCE_ID_RE.fullmatch(evidence_id) is not None
        and not evidence_id.startswith(expected_prefix)
        for evidence_id in evidence_ids
    ):
        return [
            _issue(
                "visual_evidence_prefix_mismatch",
                path,
                "caption evidence must use cap_ IDs; OCR and layout evidence must use ocr_ IDs",
            )
        ]
    return []


def _validate_doc_ids(value: Any, path: str, *, maximum: int = 20) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return [_issue("invalid_doc_ids", path, "must be an array")]
    issues: list[dict[str, str]] = []
    if len(value) > maximum:
        issues.append(_issue("too_many_doc_ids", path, f"must contain at most {maximum} document IDs"))
    if len(value) != len(set(item for item in value if isinstance(item, str))):
        issues.append(_issue("duplicate_doc_id", path, "document IDs must be unique"))
    for index, doc_id in enumerate(value):
        if not isinstance(doc_id, str) or DOC_ID_RE.fullmatch(doc_id) is None:
            issues.append(_issue("invalid_doc_id", f"{path}[{index}]", "must match the pseudonymous doc_id contract"))
    return issues


def _validate_history(value: Any, path: str) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return [_issue("invalid_history", path, "must be an array")]
    issues: list[dict[str, str]] = []
    if len(value) > 20:
        issues.append(_issue("history_too_long", path, "must contain at most 20 turns"))
    seen_turn_ids: set[str] = set()
    for index, turn in enumerate(value):
        turn_path = f"{path}[{index}]"
        if not isinstance(turn, dict):
            issues.append(_issue("invalid_history_turn", turn_path, "must be an object"))
            continue
        issues.extend(
            _validate_required(
                turn,
                ("turn_id", "role", "content"),
                ("turn_id", "role", "content", "cited_doc_ids"),
                turn_path,
            )
        )
        issues.extend(_validate_safe_id(turn.get("turn_id"), f"{turn_path}.turn_id"))
        turn_id = turn.get("turn_id")
        if isinstance(turn_id, str):
            if turn_id in seen_turn_ids:
                issues.append(_issue("duplicate_turn_id", f"{turn_path}.turn_id", "turn_id must be unique"))
            seen_turn_ids.add(turn_id)
        role = turn.get("role")
        if not isinstance(role, str) or role not in ("user", "assistant"):
            issues.append(_issue("invalid_role", f"{turn_path}.role", "must be user or assistant"))
        content = turn.get("content")
        if not isinstance(content, str) or not content.strip() or len(content) > 12000:
            issues.append(_issue("invalid_content", f"{turn_path}.content", "must be 1..12000 characters"))
        if "cited_doc_ids" in turn:
            issues.extend(_validate_doc_ids(turn["cited_doc_ids"], f"{turn_path}.cited_doc_ids"))
    return issues


def _validate_scope(value: Any, path: str) -> list[dict[str, str]]:
    if not isinstance(value, dict):
        return [_issue("invalid_document_scope", path, "must be an object")]
    issues = _validate_required(value, ("mode", "doc_ids"), ("mode", "doc_ids"), path)
    mode = value.get("mode")
    if not isinstance(mode, str) or mode not in ("all", "explicit"):
        issues.append(_issue("invalid_scope_mode", f"{path}.mode", "must be all or explicit"))
    doc_ids = value.get("doc_ids")
    issues.extend(_validate_doc_ids(doc_ids, f"{path}.doc_ids"))
    if isinstance(doc_ids, list):
        if mode == "all" and doc_ids:
            issues.append(_issue("all_scope_has_doc_ids", f"{path}.doc_ids", "all scope must not list document IDs"))
        if mode == "explicit" and not doc_ids:
            issues.append(_issue("explicit_scope_empty", f"{path}.doc_ids", "explicit scope needs at least one document ID"))
    return issues


def validate_request(value: Any, path: str = "request") -> list[dict[str, str]]:
    if not isinstance(value, dict):
        return [_issue("invalid_request", path, "request must be an object")]
    required = ("schema_version", "request_id", "question", "history", "document_scope", "options")
    issues = _validate_required(value, required, required, path)
    if value.get("schema_version") != "1.0":
        issues.append(_issue("invalid_schema_version", f"{path}.schema_version", "must equal 1.0"))
    issues.extend(_validate_safe_id(value.get("request_id"), f"{path}.request_id"))
    question = value.get("question")
    if not isinstance(question, str) or not question.strip() or len(question) > 4000:
        issues.append(_issue("invalid_question", f"{path}.question", "must be 1..4000 characters"))
    issues.extend(_validate_history(value.get("history"), f"{path}.history"))
    issues.extend(_validate_scope(value.get("document_scope"), f"{path}.document_scope"))
    options = value.get("options")
    if not isinstance(options, dict):
        issues.append(_issue("invalid_options", f"{path}.options", "must be an object"))
    else:
        issues.extend(_validate_required(options, ("max_citations",), ("max_citations",), f"{path}.options"))
        maximum = options.get("max_citations")
        if not isinstance(maximum, int) or isinstance(maximum, bool) or not 1 <= maximum <= 20:
            issues.append(_issue("invalid_max_citations", f"{path}.options.max_citations", "must be an integer from 1 to 20"))
    return issues


def _validate_locator(value: Any, path: str) -> list[dict[str, str]]:
    if not isinstance(value, dict):
        return [_issue("invalid_locator", path, "must be an object")]
    required = ("section_path", "page_start", "page_end")
    allowed = required + ("source_locator",)
    issues = _validate_required(value, required, allowed, path)
    sections = value.get("section_path")
    if not isinstance(sections, list) or any(not isinstance(item, str) or not item for item in sections):
        issues.append(_issue("invalid_section_path", f"{path}.section_path", "must be an array of non-empty strings"))
    source_locator = value.get("source_locator")
    if "source_locator" in value and (
        not isinstance(source_locator, str)
        or not source_locator.strip()
        or len(source_locator) > 1_000
    ):
        issues.append(
            _issue(
                "invalid_source_locator",
                f"{path}.source_locator",
                "must be a non-empty structure locator of at most 1000 characters",
            )
        )
    for name in ("page_start", "page_end"):
        page = value.get(name)
        if page is not None and (not isinstance(page, int) or isinstance(page, bool) or page < 1):
            issues.append(_issue("invalid_page", f"{path}.{name}", "must be null or an integer greater than zero"))
    start = value.get("page_start")
    end = value.get("page_end")
    if (start is None) != (end is None):
        issues.append(
            _issue(
                "incomplete_page_range",
                path,
                "page_start and page_end must both be present or both be null",
            )
        )
    elif start is None and end is None and "source_locator" not in value:
        issues.append(
            _issue(
                "missing_source_locator",
                f"{path}.source_locator",
                "page-less citations must include a verified structure locator",
            )
        )
    elif (
        isinstance(start, int)
        and not isinstance(start, bool)
        and isinstance(end, int)
        and not isinstance(end, bool)
        and end < start
    ):
        issues.append(_issue("invalid_page_range", path, "page_end must not precede page_start"))
    return issues


def _validate_citation(value: Any, path: str) -> list[dict[str, str]]:
    if not isinstance(value, dict):
        return [_issue("invalid_citation", path, "must be an object")]
    chunk_id = value.get("chunk_id")
    if isinstance(chunk_id, str) and VISUAL_CHUNK_ID_RE.fullmatch(chunk_id) is not None:
        return _validate_visual_citation(value, path)
    required = ("doc_id", "chunk_id", "source_block_ids", "locator")
    issues = _validate_required(value, required, required, path)
    doc_id = value.get("doc_id")
    if not isinstance(doc_id, str) or DOC_ID_RE.fullmatch(doc_id) is None:
        issues.append(_issue("invalid_doc_id", f"{path}.doc_id", "must match the doc_id contract"))
    chunk_id = value.get("chunk_id")
    if not isinstance(chunk_id, str) or CHUNK_ID_RE.fullmatch(chunk_id) is None:
        issues.append(_issue("invalid_chunk_id", f"{path}.chunk_id", "must match the chunk_id contract"))
    block_ids = value.get("source_block_ids")
    if not isinstance(block_ids, list) or not block_ids:
        issues.append(_issue("source_blocks_empty", f"{path}.source_block_ids", "must contain at least one source block"))
    else:
        if len(block_ids) != len(set(item for item in block_ids if isinstance(item, str))):
            issues.append(_issue("duplicate_source_block_id", f"{path}.source_block_ids", "source block IDs must be unique"))
        for index, block_id in enumerate(block_ids):
            if not isinstance(block_id, str) or BLOCK_ID_RE.fullmatch(block_id) is None:
                issues.append(_issue("invalid_block_id", f"{path}.source_block_ids[{index}]", "must match the block_id contract"))
    issues.extend(_validate_locator(value.get("locator"), f"{path}.locator"))
    return issues


def _validate_visual_citation(value: Mapping[str, Any], path: str) -> list[dict[str, str]]:
    required = (
        "doc_id",
        "chunk_id",
        "occurrence_id",
        "evidence_ids",
        "evidence_type",
        "locator",
    )
    issues = _validate_required(value, required, required, path)
    doc_id = value.get("doc_id")
    if not isinstance(doc_id, str) or DOC_ID_RE.fullmatch(doc_id) is None:
        issues.append(_issue("invalid_doc_id", f"{path}.doc_id", "must match the doc_id contract"))
    chunk_id = value.get("chunk_id")
    if not isinstance(chunk_id, str) or VISUAL_CHUNK_ID_RE.fullmatch(chunk_id) is None:
        issues.append(
            _issue(
                "invalid_visual_chunk_id",
                f"{path}.chunk_id",
                "must match the visual chunk_id contract",
            )
        )
    occurrence_id = value.get("occurrence_id")
    if (
        not isinstance(occurrence_id, str)
        or VISUAL_OCCURRENCE_ID_RE.fullmatch(occurrence_id) is None
    ):
        issues.append(
            _issue(
                "invalid_visual_occurrence_id",
                f"{path}.occurrence_id",
                "must match the visual occurrence contract",
            )
        )
    evidence_ids = value.get("evidence_ids")
    if not isinstance(evidence_ids, list) or not evidence_ids:
        issues.append(
            _issue(
                "visual_evidence_empty",
                f"{path}.evidence_ids",
                "must contain at least one visual evidence ID",
            )
        )
    else:
        if len(evidence_ids) != len(set(item for item in evidence_ids if isinstance(item, str))):
            issues.append(
                _issue(
                    "duplicate_visual_evidence_id",
                    f"{path}.evidence_ids",
                    "visual evidence IDs must be unique",
                )
            )
        for index, evidence_id in enumerate(evidence_ids):
            if (
                not isinstance(evidence_id, str)
                or VISUAL_EVIDENCE_ID_RE.fullmatch(evidence_id) is None
            ):
                issues.append(
                    _issue(
                        "invalid_visual_evidence_id",
                        f"{path}.evidence_ids[{index}]",
                        "must match the visual evidence contract",
                    )
                )
    evidence_type = value.get("evidence_type")
    if (
        not isinstance(evidence_type, str)
        or evidence_type not in {"ocr", "layout", "caption"}
    ):
        issues.append(
            _issue(
                "invalid_visual_evidence_type",
                f"{path}.evidence_type",
                "must be ocr, layout or caption",
            )
        )
    issues.extend(
        _validate_visual_evidence_binding(
            evidence_ids,
            evidence_type,
            f"{path}.evidence_ids",
        )
    )
    locator = value.get("locator")
    locator_path = f"{path}.locator"
    if not isinstance(locator, dict):
        issues.append(_issue("invalid_visual_locator", locator_path, "must be an object"))
        return issues
    locator_required = ("page", "bbox", "crop_sha256")
    issues.extend(_validate_required(locator, locator_required, locator_required, locator_path))
    page = locator.get("page")
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        issues.append(_issue("invalid_page", f"{locator_path}.page", "must be a positive integer"))
    bbox = locator.get("bbox")
    bbox_path = f"{locator_path}.bbox"
    if not isinstance(bbox, dict):
        issues.append(_issue("invalid_visual_bbox", bbox_path, "must be an object"))
    else:
        bbox_fields = ("x", "y", "w", "h")
        issues.extend(_validate_required(bbox, bbox_fields, bbox_fields, bbox_path))
        for field in bbox_fields:
            if not _is_number(bbox.get(field)):
                issues.append(
                    _issue(
                        "invalid_visual_bbox",
                        f"{bbox_path}.{field}",
                        "must be a finite number",
                    )
                )
        for field in ("w", "h"):
            if _is_number(bbox.get(field)) and float(bbox[field]) <= 0:
                issues.append(
                    _issue(
                        "invalid_visual_bbox",
                        f"{bbox_path}.{field}",
                        "must be greater than zero",
                    )
                )
    crop_sha256 = locator.get("crop_sha256")
    if not isinstance(crop_sha256, str) or SHA256_RE.fullmatch(crop_sha256) is None:
        issues.append(
            _issue(
                "invalid_visual_crop_hash",
                f"{locator_path}.crop_sha256",
                "must be a lowercase SHA-256",
            )
        )
    return issues


def validate_response(value: Any, path: str = "response") -> list[dict[str, str]]:
    if not isinstance(value, dict):
        return [_issue("invalid_response", path, "response must be an object")]
    required = ("schema_version", "request_id", "status", "answer", "citations", "abstention", "error", "trace_id")
    issues = _validate_required(value, required, required, path)
    if value.get("schema_version") != "1.0":
        issues.append(_issue("invalid_schema_version", f"{path}.schema_version", "must equal 1.0"))
    issues.extend(_validate_safe_id(value.get("request_id"), f"{path}.request_id"))
    issues.extend(_validate_safe_id(value.get("trace_id"), f"{path}.trace_id"))
    status = value.get("status")
    if not isinstance(status, str) or status not in ("answered", "abstained", "error"):
        issues.append(_issue("invalid_response_status", f"{path}.status", "must be answered, abstained or error"))
    answer = value.get("answer")
    if not isinstance(answer, str) or len(answer) > 30000:
        issues.append(_issue("invalid_answer", f"{path}.answer", "must be a string of at most 30000 characters"))
    citations = value.get("citations")
    if not isinstance(citations, list):
        issues.append(_issue("invalid_citations", f"{path}.citations", "must be an array"))
        citations = []
    elif len(citations) > 20:
        issues.append(_issue("too_many_citations", f"{path}.citations", "must contain at most 20 citations"))
    for index, citation in enumerate(citations):
        issues.extend(_validate_citation(citation, f"{path}.citations[{index}]"))

    abstention = value.get("abstention")
    error = value.get("error")
    if status == "answered":
        if not isinstance(answer, str) or not answer.strip():
            issues.append(_issue("answered_without_answer", f"{path}.answer", "answered status needs a non-empty answer"))
        if not citations:
            issues.append(_issue("answered_without_citation", f"{path}.citations", "answered status needs at least one citation"))
        if abstention is not None:
            issues.append(_issue("answered_with_abstention", f"{path}.abstention", "answered status cannot carry abstention data"))
        if error is not None:
            issues.append(_issue("answered_with_error", f"{path}.error", "answered status cannot carry an error"))
    elif status == "abstained":
        if not isinstance(answer, str) or not answer.strip():
            issues.append(_issue("abstained_without_explanation", f"{path}.answer", "abstention needs a safe explanation"))
        if citations:
            issues.append(_issue("abstained_with_citation", f"{path}.citations", "abstention cannot cite unsupported evidence"))
        if not isinstance(abstention, dict):
            issues.append(_issue("abstention_missing", f"{path}.abstention", "abstention data is required"))
        else:
            issues.extend(_validate_required(abstention, ("reason", "detail"), ("reason", "detail"), f"{path}.abstention"))
            reason = abstention.get("reason")
            if not isinstance(reason, str) or reason not in ABSTENTION_REASONS:
                issues.append(_issue("invalid_abstention_reason", f"{path}.abstention.reason", "reason is not supported"))
            expected_answer = SAFE_ABSTENTION_ANSWERS.get(reason) if isinstance(reason, str) else None
            if expected_answer is not None and answer != expected_answer:
                issues.append(_issue("nonstandard_abstention_answer", f"{path}.answer", "abstention answer must use the non-factual safe template"))
            detail = abstention.get("detail")
            if not isinstance(detail, str) or not detail.strip() or len(detail) > 2000:
                issues.append(_issue("invalid_abstention_detail", f"{path}.abstention.detail", "detail must be 1..2000 characters"))
        if error is not None:
            issues.append(_issue("abstained_with_error", f"{path}.error", "abstention and runtime error are distinct states"))
    elif status == "error":
        if citations:
            issues.append(_issue("error_with_citation", f"{path}.citations", "error status cannot carry citations"))
        if abstention is not None:
            issues.append(_issue("error_with_abstention", f"{path}.abstention", "runtime error is not abstention"))
        if not isinstance(error, dict):
            issues.append(_issue("error_detail_missing", f"{path}.error", "error status needs an error object"))
        else:
            issues.extend(_validate_required(error, ("code", "message"), ("code", "message"), f"{path}.error"))
            code = error.get("code")
            if not isinstance(code, str) or re.fullmatch(r"^[a-z][a-z0-9_]{0,63}$", code) is None:
                issues.append(_issue("invalid_error_code", f"{path}.error.code", "must be a stable lowercase code"))
            message = error.get("message")
            if not isinstance(message, str) or not message.strip() or len(message) > 2000:
                issues.append(_issue("invalid_error_message", f"{path}.error.message", "message must be 1..2000 characters"))
    return issues


def validate_case(value: Any, path: str = "case") -> list[dict[str, str]]:
    if not isinstance(value, dict):
        return [_issue("invalid_case", path, "evaluation case must be an object")]
    required = (
        "schema_version",
        "case_id",
        "group_id",
        "split",
        "task_type",
        "question",
        "history",
        "document_scope",
        "conversation",
        "gold",
        "difficulty",
        "tags",
        "source_manifest_sha256",
        "review",
    )
    issues = _validate_required(value, required, required, path)
    if value.get("schema_version") != "1.0":
        issues.append(_issue("invalid_schema_version", f"{path}.schema_version", "must equal 1.0"))
    case_id = value.get("case_id")
    case_id_match = CASE_ID_RE.fullmatch(case_id) if isinstance(case_id, str) else None
    if case_id_match is None:
        issues.append(_issue("invalid_case_id", f"{path}.case_id", "must match the split/task case ID convention"))
    issues.extend(_validate_safe_id(value.get("group_id"), f"{path}.group_id"))
    split = value.get("split")
    if split not in SPLITS:
        issues.append(_issue("invalid_split", f"{path}.split", "must be dev or heldout"))
    if isinstance(case_id, str) and split in SPLITS and not case_id.startswith(f"{split}-"):
        issues.append(_issue("case_id_split_mismatch", f"{path}.case_id", "case ID prefix must match split"))
    task_type = value.get("task_type")
    if task_type not in TASK_TYPES:
        issues.append(_issue("invalid_task_type", f"{path}.task_type", "task type is not supported"))
    elif case_id_match is not None and case_id_match.group(2) != TASK_ALIASES[task_type]:
        issues.append(_issue("case_id_task_mismatch", f"{path}.case_id", "case ID task segment must match task_type"))
    question = value.get("question")
    if not isinstance(question, str) or not question.strip() or len(question) > 4000:
        issues.append(_issue("invalid_question", f"{path}.question", "must be 1..4000 characters"))
    issues.extend(_validate_history(value.get("history"), f"{path}.history"))
    issues.extend(_validate_scope(value.get("document_scope"), f"{path}.document_scope"))
    difficulty = value.get("difficulty")
    if not isinstance(difficulty, str) or difficulty not in ("easy", "medium", "hard"):
        issues.append(_issue("invalid_difficulty", f"{path}.difficulty", "must be easy, medium or hard"))
    tags = value.get("tags")
    if not isinstance(tags, list) or any(not isinstance(tag, str) or not tag for tag in tags):
        issues.append(_issue("invalid_tags", f"{path}.tags", "must be an array of non-empty strings"))
    elif len(tags) != len(set(tags)):
        issues.append(_issue("duplicate_tag", f"{path}.tags", "tags must be unique"))
    manifest_hash = value.get("source_manifest_sha256")
    if not isinstance(manifest_hash, str) or SHA256_RE.fullmatch(manifest_hash) is None:
        issues.append(_issue("invalid_manifest_hash", f"{path}.source_manifest_sha256", "must be a lowercase SHA-256"))

    review = value.get("review")
    if not isinstance(review, dict):
        issues.append(_issue("invalid_review", f"{path}.review", "must be an object"))
    else:
        issues.extend(_validate_required(review, ("author", "reviewer", "status"), ("author", "reviewer", "status"), f"{path}.review"))
        review_status = review.get("status")
        if not isinstance(review_status, str) or review_status not in ("draft", "approved"):
            issues.append(_issue("invalid_review_status", f"{path}.review.status", "must be draft or approved"))
        for field in ("author", "reviewer"):
            identity = review.get(field)
            if not isinstance(identity, str) or not identity.strip() or len(identity) > 128:
                issues.append(_issue("invalid_reviewer_id", f"{path}.review.{field}", "must be a non-empty team identifier"))

    gold = value.get("gold")
    if not isinstance(gold, dict):
        issues.append(_issue("invalid_gold", f"{path}.gold", "must be an object"))
        return issues
    gold_required = (
        "decision",
        "reference_answer",
        "required_key_points",
        "required_doc_ids",
        "evidence_refs",
        "comparison_axes",
        "abstain_reason",
    )
    issues.extend(_validate_required(gold, gold_required, gold_required, f"{path}.gold"))
    decision = gold.get("decision")
    if not isinstance(decision, str) or decision not in ("answer", "abstain"):
        issues.append(_issue("invalid_gold_decision", f"{path}.gold.decision", "must be answer or abstain"))
    reference_answer = gold.get("reference_answer")
    if reference_answer is not None and (not isinstance(reference_answer, str) or len(reference_answer) > 12000):
        issues.append(_issue("invalid_reference_answer", f"{path}.gold.reference_answer", "must be null or at most 12000 characters"))
    required_doc_ids = gold.get("required_doc_ids")
    issues.extend(_validate_doc_ids(required_doc_ids, f"{path}.gold.required_doc_ids"))

    key_points = gold.get("required_key_points")
    point_ids: list[str] = []
    if not isinstance(key_points, list):
        issues.append(_issue("invalid_key_points", f"{path}.gold.required_key_points", "must be an array"))
        key_points = []
    for index, point in enumerate(key_points):
        point_path = f"{path}.gold.required_key_points[{index}]"
        if not isinstance(point, dict):
            issues.append(_issue("invalid_key_point", point_path, "must be an object"))
            continue
        issues.extend(_validate_required(point, ("point_id", "text"), ("point_id", "text"), point_path))
        point_id = point.get("point_id")
        if not isinstance(point_id, str) or KEY_POINT_ID_RE.fullmatch(point_id) is None:
            issues.append(_issue("invalid_key_point_id", f"{point_path}.point_id", "must match the key-point ID contract"))
        else:
            point_ids.append(point_id)
        text = point.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
            issues.append(_issue("invalid_key_point_text", f"{point_path}.text", "must be 1..2000 characters"))
    if len(point_ids) != len(set(point_ids)):
        issues.append(_issue("duplicate_key_point_id", f"{path}.gold.required_key_points", "point IDs must be unique"))

    evidence = gold.get("evidence_refs")
    evidence_docs: set[str] = set()
    if not isinstance(evidence, list):
        issues.append(_issue("invalid_evidence_refs", f"{path}.gold.evidence_refs", "must be an array"))
        evidence = []
    evidence_pairs: set[tuple[str, str]] = set()
    visual_evidence_keys: set[tuple[str, str, str, tuple[str, ...]]] = set()
    for index, reference in enumerate(evidence):
        evidence_path = f"{path}.gold.evidence_refs[{index}]"
        if not isinstance(reference, dict):
            issues.append(_issue("invalid_evidence_ref", evidence_path, "must be an object"))
            continue
        doc_id = reference.get("doc_id")
        if not isinstance(doc_id, str) or DOC_ID_RE.fullmatch(doc_id) is None:
            issues.append(_issue("invalid_doc_id", f"{evidence_path}.doc_id", "must match the doc_id contract"))
        else:
            evidence_docs.add(doc_id)
        is_visual_reference = any(
            field in reference
            for field in ("occurrence_id", "evidence_ids", "evidence_type")
        )
        if is_visual_reference:
            visual_fields = ("doc_id", "occurrence_id", "evidence_ids", "evidence_type")
            issues.extend(
                _validate_required(reference, visual_fields, visual_fields, evidence_path)
            )
            occurrence_id = reference.get("occurrence_id")
            if (
                not isinstance(occurrence_id, str)
                or VISUAL_OCCURRENCE_ID_RE.fullmatch(occurrence_id) is None
            ):
                issues.append(
                    _issue(
                        "invalid_visual_occurrence_id",
                        f"{evidence_path}.occurrence_id",
                        "must match the visual occurrence contract",
                    )
                )
            evidence_ids = reference.get("evidence_ids")
            if not isinstance(evidence_ids, list) or not evidence_ids:
                issues.append(
                    _issue(
                        "visual_evidence_empty",
                        f"{evidence_path}.evidence_ids",
                        "must contain at least one visual evidence ID",
                    )
                )
            else:
                if len(evidence_ids) != len(
                    set(item for item in evidence_ids if isinstance(item, str))
                ):
                    issues.append(
                        _issue(
                            "duplicate_visual_evidence_id",
                            f"{evidence_path}.evidence_ids",
                            "visual evidence IDs must be unique",
                        )
                    )
                for evidence_index, evidence_id in enumerate(evidence_ids):
                    if (
                        not isinstance(evidence_id, str)
                        or VISUAL_EVIDENCE_ID_RE.fullmatch(evidence_id) is None
                    ):
                        issues.append(
                            _issue(
                                "invalid_visual_evidence_id",
                                f"{evidence_path}.evidence_ids[{evidence_index}]",
                                "must match the visual evidence contract",
                            )
                        )
            evidence_type = reference.get("evidence_type")
            if (
                not isinstance(evidence_type, str)
                or evidence_type not in {"ocr", "layout", "caption"}
            ):
                issues.append(
                    _issue(
                        "invalid_visual_evidence_type",
                        f"{evidence_path}.evidence_type",
                        "must be ocr, layout or caption",
                    )
                )
            issues.extend(
                _validate_visual_evidence_binding(
                    evidence_ids,
                    evidence_type,
                    f"{evidence_path}.evidence_ids",
                )
            )
            if (
                isinstance(doc_id, str)
                and isinstance(occurrence_id, str)
                and isinstance(evidence_type, str)
                and isinstance(evidence_ids, list)
                and all(isinstance(item, str) for item in evidence_ids)
            ):
                visual_key = (
                    doc_id,
                    occurrence_id,
                    evidence_type,
                    tuple(sorted(evidence_ids)),
                )
                if visual_key in visual_evidence_keys:
                    issues.append(
                        _issue(
                            "duplicate_evidence_ref",
                            evidence_path,
                            "evidence reference must be unique",
                        )
                    )
                visual_evidence_keys.add(visual_key)
        else:
            text_fields = ("doc_id", "source_block_id", "locator_hash")
            issues.extend(
                _validate_required(reference, text_fields, text_fields, evidence_path)
            )
            block_id = reference.get("source_block_id")
            locator_hash = reference.get("locator_hash")
            if not isinstance(block_id, str) or BLOCK_ID_RE.fullmatch(block_id) is None:
                issues.append(_issue("invalid_block_id", f"{evidence_path}.source_block_id", "must match the block_id contract"))
            if not isinstance(locator_hash, str) or SHA256_RE.fullmatch(locator_hash) is None:
                issues.append(_issue("invalid_locator_hash", f"{evidence_path}.locator_hash", "must be a lowercase SHA-256"))
            if isinstance(doc_id, str) and isinstance(block_id, str):
                pair = (doc_id, block_id)
                if pair in evidence_pairs:
                    issues.append(_issue("duplicate_evidence_ref", evidence_path, "evidence reference must be unique"))
                evidence_pairs.add(pair)

    axes = gold.get("comparison_axes")
    if not isinstance(axes, list) or any(not isinstance(axis, str) or not axis for axis in axes):
        issues.append(_issue("invalid_comparison_axes", f"{path}.gold.comparison_axes", "must be an array of non-empty strings"))
        axes = []
    elif len(axes) != len(set(axes)):
        issues.append(_issue("duplicate_comparison_axis", f"{path}.gold.comparison_axes", "comparison axes must be unique"))

    abstain_reason = gold.get("abstain_reason")
    if abstain_reason is not None and abstain_reason not in ABSTENTION_REASONS:
        issues.append(_issue("invalid_abstention_reason", f"{path}.gold.abstain_reason", "reason is not supported"))

    conversation = value.get("conversation")
    history = value.get("history")
    if task_type == "unknown":
        if decision != "abstain" or reference_answer is not None or key_points or required_doc_ids or evidence or axes:
            issues.append(_issue("unknown_gold_not_empty", f"{path}.gold", "unknown cases must contain only an abstention decision and reason"))
        if abstain_reason not in ABSTENTION_REASONS:
            issues.append(_issue("unknown_reason_missing", f"{path}.gold.abstain_reason", "unknown case needs an abstention reason"))
    elif isinstance(task_type, str) and task_type in ("single_doc", "multi_doc_compare", "follow_up"):
        if decision != "answer":
            issues.append(_issue("answer_case_marked_abstain", f"{path}.gold.decision", "answerable task must use answer decision"))
        if not isinstance(reference_answer, str) or not reference_answer.strip():
            issues.append(_issue("reference_answer_missing", f"{path}.gold.reference_answer", "answerable task needs a reference answer"))
        if not key_points:
            issues.append(_issue("key_points_empty", f"{path}.gold.required_key_points", "answerable task needs at least one key point"))
        if not isinstance(required_doc_ids, list) or not required_doc_ids:
            issues.append(_issue("required_docs_empty", f"{path}.gold.required_doc_ids", "answerable task needs at least one required document"))
        if not evidence:
            issues.append(_issue("evidence_empty", f"{path}.gold.evidence_refs", "answerable task needs stable source evidence"))
        if isinstance(required_doc_ids, list):
            valid_required_docs = {doc_id for doc_id in required_doc_ids if isinstance(doc_id, str)}
            missing_evidence = sorted(valid_required_docs - evidence_docs)
            if missing_evidence:
                issues.append(_issue("required_doc_without_evidence", f"{path}.gold.evidence_refs", "every required document needs evidence"))
    if task_type == "single_doc" and isinstance(required_doc_ids, list) and len(required_doc_ids) != 1:
        issues.append(_issue("single_doc_cardinality", f"{path}.gold.required_doc_ids", "single_doc needs exactly one required document"))
    if task_type == "multi_doc_compare":
        if not isinstance(required_doc_ids, list) or len(required_doc_ids) < 2:
            issues.append(_issue("multi_doc_cardinality", f"{path}.gold.required_doc_ids", "multi_doc_compare needs at least two documents"))
        if not axes:
            issues.append(_issue("comparison_axes_empty", f"{path}.gold.comparison_axes", "comparison task needs at least one axis"))
    if task_type == "follow_up":
        if not isinstance(history, list) or not history:
            issues.append(_issue("follow_up_history_empty", f"{path}.history", "follow_up needs explicit history"))
        if not isinstance(conversation, dict):
            issues.append(_issue("conversation_missing", f"{path}.conversation", "follow_up needs conversation metadata"))
        else:
            conversation_required = ("conversation_id", "turn_index", "depends_on_turn_ids")
            issues.extend(_validate_required(conversation, conversation_required, conversation_required, f"{path}.conversation"))
            issues.extend(_validate_safe_id(conversation.get("conversation_id"), f"{path}.conversation.conversation_id"))
            turn_index = conversation.get("turn_index")
            if not isinstance(turn_index, int) or isinstance(turn_index, bool) or turn_index < 1:
                issues.append(_issue("invalid_turn_index", f"{path}.conversation.turn_index", "must be an integer greater than zero"))
            dependencies = conversation.get("depends_on_turn_ids")
            if not isinstance(dependencies, list) or not dependencies:
                issues.append(_issue("dependencies_empty", f"{path}.conversation.depends_on_turn_ids", "must list at least one prior turn"))
            else:
                if len(dependencies) != len(set(item for item in dependencies if isinstance(item, str))):
                    issues.append(_issue("duplicate_dependency", f"{path}.conversation.depends_on_turn_ids", "dependency turn IDs must be unique"))
                history_ids = (
                    {
                        turn.get("turn_id")
                        for turn in history
                        if isinstance(turn, dict) and isinstance(turn.get("turn_id"), str)
                    }
                    if isinstance(history, list)
                    else set()
                )
                for index, dependency in enumerate(dependencies):
                    issues.extend(_validate_safe_id(dependency, f"{path}.conversation.depends_on_turn_ids[{index}]"))
                    if isinstance(dependency, str) and dependency not in history_ids:
                        issues.append(_issue("dependency_not_in_history", f"{path}.conversation.depends_on_turn_ids[{index}]", "dependency must reference an explicit history turn"))
    elif conversation is not None:
        issues.append(_issue("unexpected_conversation", f"{path}.conversation", "only follow_up cases carry conversation metadata"))
    scope = value.get("document_scope")
    if (
        isinstance(scope, dict)
        and scope.get("mode") == "explicit"
        and isinstance(scope.get("doc_ids"), list)
        and isinstance(required_doc_ids, list)
        and not {doc_id for doc_id in required_doc_ids if isinstance(doc_id, str)}
        <= {doc_id for doc_id in scope["doc_ids"] if isinstance(doc_id, str)}
    ):
        issues.append(_issue("required_doc_outside_scope", f"{path}.document_scope.doc_ids", "explicit scope must contain every required document"))
    return issues


def dataset_sha256(cases: Sequence[Mapping[str, Any]]) -> str:
    return sha256_text(canonical_json(list(cases)))


def sequence_sha256(cases: Sequence[Mapping[str, Any]]) -> str:
    case_ids = [case.get("case_id") if isinstance(case, Mapping) else None for case in cases]
    return sha256_text(canonical_json(case_ids))


def normalize_question(value: str) -> str:
    """Canonicalize a question only for exact split-leakage detection."""
    collapsed = " ".join(value.split())
    return unicodedata.normalize("NFC", collapsed).casefold()


def validate_evaluation_config(value: Any, path: str = "config") -> list[dict[str, str]]:
    """Validate the frozen scoring gates without relying on optional packages."""
    if not isinstance(value, dict):
        return [_issue("invalid_evaluation_config", path, "must be a JSON object")]
    required = ("schema_version", "k_values", "minimum_cases", "thresholds")
    issues = _validate_required(value, required, required, path)
    if value.get("schema_version") != "1.0":
        issues.append(_issue("invalid_config_schema_version", f"{path}.schema_version", "must equal 1.0"))

    k_values = value.get("k_values")
    if (
        not isinstance(k_values, list)
        or not k_values
        or any(not isinstance(item, int) or isinstance(item, bool) or item <= 0 for item in k_values)
    ):
        issues.append(_issue("invalid_k_values", f"{path}.k_values", "must be positive integer cutoffs"))
    else:
        if len(k_values) != len(set(k_values)) or k_values != sorted(k_values):
            issues.append(_issue("invalid_k_values", f"{path}.k_values", "must be unique and sorted"))
        if k_values != [1, 3, 5, 10]:
            issues.append(_issue("required_k_values_changed", f"{path}.k_values", "must equal the frozen [1, 3, 5, 10] cutoffs"))

    minimum_cases = value.get("minimum_cases")
    if not isinstance(minimum_cases, dict):
        issues.append(_issue("invalid_minimum_cases", f"{path}.minimum_cases", "must define dev and heldout floors"))
    else:
        issues.extend(_validate_required(minimum_cases, SPLITS, SPLITS, f"{path}.minimum_cases"))
        for split in SPLITS:
            split_minimums = minimum_cases.get(split)
            if not isinstance(split_minimums, dict):
                issues.append(_issue("invalid_minimum_cases", f"{path}.minimum_cases.{split}", "must define every task"))
                continue
            issues.extend(
                _validate_required(
                    split_minimums,
                    TASK_TYPES,
                    TASK_TYPES,
                    f"{path}.minimum_cases.{split}",
                )
            )
            for task in TASK_TYPES:
                minimum = split_minimums.get(task)
                frozen_floor = DEFAULT_MINIMUM_CASES[split][task]
                if (
                    not isinstance(minimum, int)
                    or isinstance(minimum, bool)
                    or minimum < frozen_floor
                ):
                    issues.append(
                        _issue(
                            "minimum_case_floor_reduced",
                            f"{path}.minimum_cases.{split}.{task}",
                            f"must be an integer of at least {frozen_floor}",
                        )
                    )

    thresholds = value.get("thresholds")
    if not isinstance(thresholds, dict):
        issues.append(_issue("invalid_thresholds", f"{path}.thresholds", "must be a metric rule object"))
        return issues
    required_thresholds = REQUIRED_COMMON_THRESHOLDS | REQUIRED_STACK_THRESHOLDS.keys()
    for metric_path in sorted(required_thresholds - thresholds.keys()):
        issues.append(_issue("required_threshold_missing", f"{path}.thresholds.{metric_path}", "frozen hard gate is missing"))
    for metric_path, rule in sorted(thresholds.items()):
        rule_path = f"{path}.thresholds.{metric_path}"
        if not isinstance(metric_path, str) or not metric_path.startswith("metrics."):
            issues.append(_issue("invalid_threshold_path", rule_path, "must target a score-report metric"))
            continue
        if not isinstance(rule, dict):
            issues.append(_issue("invalid_threshold_rule", rule_path, "must be an object"))
            continue
        issues.extend(_validate_required(rule, ("operator", "value"), ("operator", "value", "applies_to"), rule_path))
        if rule.get("operator") not in (">=", "<=", "=="):
            issues.append(_issue("invalid_threshold_operator", f"{rule_path}.operator", "must be >=, <= or =="))
        if not _is_number(rule.get("value")):
            issues.append(_issue("invalid_threshold_value", f"{rule_path}.value", "must be a finite number"))
        applies_to = rule.get("applies_to")
        if applies_to is not None:
            if (
                not isinstance(applies_to, list)
                or not applies_to
                or any(not isinstance(item, str) or item not in STACK_IDS for item in applies_to)
                or len(applies_to) != len(set(applies_to))
            ):
                issues.append(_issue("invalid_threshold_stack", f"{rule_path}.applies_to", "must be a unique non-empty stack list"))
        required_stack = REQUIRED_STACK_THRESHOLDS.get(metric_path)
        if required_stack is not None and applies_to != [required_stack]:
            issues.append(_issue("threshold_stack_scope_changed", f"{rule_path}.applies_to", f"must apply only to {required_stack}"))
        if metric_path in REQUIRED_COMMON_THRESHOLDS and applies_to is not None:
            issues.append(_issue("common_threshold_scoped", f"{rule_path}.applies_to", "common hard gates must apply to both stacks"))

    for metric_path, (operator, expected, expected_stacks) in FROZEN_THRESHOLDS.items():
        rule = thresholds.get(metric_path)
        if isinstance(rule, dict):
            actual_stacks = tuple(rule["applies_to"]) if isinstance(rule.get("applies_to"), list) else None
            if (rule.get("operator"), rule.get("value"), actual_stacks) != (operator, expected, expected_stacks):
                issues.append(_issue("frozen_threshold_changed", f"{path}.thresholds.{metric_path}", "frozen evaluation target must not change"))
    return issues


def validate_dataset(
    dev_cases: Sequence[dict[str, Any]],
    heldout_cases: Sequence[dict[str, Any]],
    *,
    minimum_cases: Mapping[str, Mapping[str, int]] | None = None,
    known_doc_ids: set[str] | None = None,
    block_owners: Mapping[str, str] | None = None,
    block_locator_hashes: Mapping[str, str] | None = None,
    manifest_sha256: str | None = None,
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    split_cases = {"dev": list(dev_cases), "heldout": list(heldout_cases)}
    requested_minimums = minimum_cases if minimum_cases is not None else DEFAULT_MINIMUM_CASES
    effective_minimums: dict[str, dict[str, int]] = {split: {} for split in SPLITS}
    for split in SPLITS:
        split_minimums = requested_minimums.get(split) if isinstance(requested_minimums, Mapping) else None
        if not isinstance(split_minimums, Mapping):
            errors.append(_issue("invalid_minimum_cases", f"minimum_cases.{split}", "must define every task"))
            split_minimums = {}
        for task in TASK_TYPES:
            minimum = split_minimums.get(task)
            if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 1:
                errors.append(_issue("invalid_minimum_case_count", f"minimum_cases.{split}.{task}", "must be a positive integer"))
                minimum = 1
            effective_minimums[split][task] = minimum
    all_cases = split_cases["dev"] + split_cases["heldout"]

    for split, cases in split_cases.items():
        for index, case in enumerate(cases):
            errors.extend(validate_case(case, f"{split}[{index}]"))
            if not isinstance(case, dict):
                continue
            if case.get("split") != split:
                errors.append(_issue("file_split_mismatch", f"{split}[{index}].split", "case split does not match its dataset file"))
            review = case.get("review")
            if isinstance(review, dict) and review.get("status") != "approved":
                errors.append(_issue("case_not_approved", f"{split}[{index}].review.status", "evaluation case must be approved before use"))

    case_ids = [
        case.get("case_id")
        for case in all_cases
        if isinstance(case, dict) and isinstance(case.get("case_id"), str)
    ]
    duplicate_case_ids = sorted(case_id for case_id, count in Counter(case_ids).items() if count > 1)
    for case_id in duplicate_case_ids:
        errors.append(_issue("duplicate_case_id", "dataset", f"duplicate pseudonymous case ID: {case_id}"))

    dev_groups = {
        case.get("group_id")
        for case in dev_cases
        if isinstance(case, dict) and isinstance(case.get("group_id"), str)
    }
    heldout_groups = {
        case.get("group_id")
        for case in heldout_cases
        if isinstance(case, dict) and isinstance(case.get("group_id"), str)
    }
    for group_id in sorted(dev_groups & heldout_groups):
        errors.append(_issue("split_group_leakage", "dataset", f"group appears in dev and heldout: {group_id}"))

    question_hashes: dict[str, set[str]] = {}
    multi_doc_pairs: dict[str, set[tuple[str, ...]]] = {}
    for split, cases in split_cases.items():
        question_hashes[split] = {
            sha256_text(normalize_question(case["question"]))
            for case in cases
            if isinstance(case, dict) and isinstance(case.get("question"), str)
        }
        multi_doc_pairs[split] = {
            tuple(sorted(case["gold"]["required_doc_ids"]))
            for case in cases
            if isinstance(case, dict)
            and case.get("task_type") == "multi_doc_compare"
            and isinstance(case.get("gold"), dict)
            and isinstance(case["gold"].get("required_doc_ids"), list)
            and all(isinstance(doc_id, str) for doc_id in case["gold"]["required_doc_ids"])
        }
    if question_hashes["dev"] & question_hashes["heldout"]:
        errors.append(_issue("exact_question_leakage", "dataset", "an exact normalized question appears in both splits"))
    if multi_doc_pairs["dev"] & multi_doc_pairs["heldout"]:
        errors.append(_issue("multi_doc_pair_leakage", "dataset", "a multi-document comparison pair appears in both splits"))

    conversation_ids: dict[str, set[str]] = {}
    for split, cases in split_cases.items():
        conversation_ids[split] = {
            case["conversation"]["conversation_id"]
            for case in cases
            if isinstance(case, dict)
            and isinstance(case.get("conversation"), dict)
            and isinstance(case["conversation"].get("conversation_id"), str)
        }
    if conversation_ids["dev"] & conversation_ids["heldout"]:
        errors.append(_issue("conversation_split_leakage", "dataset", "a conversation ID appears in both splits"))

    counts: dict[str, dict[str, int]] = {}
    for split, cases in split_cases.items():
        task_counts = Counter(
            case.get("task_type")
            for case in cases
            if isinstance(case, dict) and isinstance(case.get("task_type"), str)
        )
        counts[split] = {task: task_counts[task] for task in TASK_TYPES}
        required_counts = effective_minimums.get(split, {})
        for task in TASK_TYPES:
            minimum = required_counts.get(task, 1)
            if task_counts[task] < minimum:
                errors.append(_issue("insufficient_task_cases", f"{split}.{task}", f"needs at least {minimum} approved cases"))

    manifest_hashes = {
        case.get("source_manifest_sha256")
        for case in all_cases
        if isinstance(case, dict) and isinstance(case.get("source_manifest_sha256"), str)
    }
    if len(manifest_hashes) > 1:
        errors.append(_issue("mixed_manifest_hashes", "dataset", "all cases must use one corpus manifest hash"))
    if manifest_sha256 is not None and manifest_hashes != {manifest_sha256}:
        errors.append(_issue("manifest_hash_mismatch", "dataset", "case manifest hash does not match the supplied manifest"))

    if known_doc_ids is not None or block_owners is not None:
        for split, cases in split_cases.items():
            for index, case in enumerate(cases):
                case_path = f"{split}[{index}]"
                if not isinstance(case, dict):
                    continue
                ids: list[str] = []
                scope = case.get("document_scope")
                if isinstance(scope, dict) and isinstance(scope.get("doc_ids"), list):
                    ids.extend(item for item in scope["doc_ids"] if isinstance(item, str))
                gold = case.get("gold")
                if not isinstance(gold, dict):
                    continue
                if isinstance(gold.get("required_doc_ids"), list):
                    ids.extend(item for item in gold["required_doc_ids"] if isinstance(item, str))
                evidence = gold.get("evidence_refs")
                if not isinstance(evidence, list):
                    evidence = []
                for reference in evidence:
                    if not isinstance(reference, dict):
                        continue
                    doc_id = reference.get("doc_id")
                    block_id = reference.get("source_block_id")
                    if isinstance(doc_id, str):
                        ids.append(doc_id)
                    if block_owners is not None and isinstance(block_id, str):
                        owner = block_owners.get(block_id)
                        if owner is None:
                            errors.append(_issue("evidence_block_missing", f"{case_path}.gold.evidence_refs", "source block is absent from the supplied block snapshot"))
                        elif owner != doc_id:
                            errors.append(_issue("evidence_block_owner_mismatch", f"{case_path}.gold.evidence_refs", "source block belongs to another document"))
                    if block_locator_hashes is not None and isinstance(block_id, str):
                        expected_locator_hash = block_locator_hashes.get(block_id)
                        if expected_locator_hash is not None and reference.get("locator_hash") != expected_locator_hash:
                            errors.append(_issue("evidence_locator_hash_mismatch", f"{case_path}.gold.evidence_refs", "locator hash does not match the supplied source block"))
                if known_doc_ids is not None and any(doc_id not in known_doc_ids for doc_id in ids):
                    errors.append(_issue("case_doc_missing", case_path, "case references a document absent from the supplied manifest"))

    return {
        "schema_version": "1.0",
        "passed": not errors,
        "dataset_sha256": dataset_sha256(all_cases),
        "dev_sha256": dataset_sha256(dev_cases),
        "heldout_sha256": dataset_sha256(heldout_cases),
        "sequence_sha256": sequence_sha256(all_cases),
        "dev_sequence_sha256": sequence_sha256(dev_cases),
        "heldout_sequence_sha256": sequence_sha256(heldout_cases),
        "counts": {
            "total": len(all_cases),
            "dev": counts["dev"],
            "heldout": counts["heldout"],
        },
        "errors": errors,
        "warnings": warnings,
    }


def validate_run_record(value: Any, path: str = "run") -> list[dict[str, str]]:
    if not isinstance(value, dict):
        return [_issue("invalid_run_record", path, "run record must be an object")]
    required = (
        "schema_version",
        "run_id",
        "case_id",
        "stack_id",
        "corpus_manifest_sha256",
        "eval_set_sha256",
        "config_sha256",
        "git_commit",
        "generator_model",
        "embedding_model",
        "environment",
        "retrieval",
        "response",
        "timing_ms",
        "usage",
        "judgment",
        "seed",
        "temperature",
        "cache_hit",
    )
    optional = (
        "api_profile",
        "embedding_dimensions",
        "index_config_sha256",
        "reasoning_effort",
    )
    issues = _validate_required(value, required, required + optional, path)
    if value.get("schema_version") != "1.0":
        issues.append(_issue("invalid_schema_version", f"{path}.schema_version", "must equal 1.0"))
    issues.extend(_validate_safe_id(value.get("run_id"), f"{path}.run_id"))
    case_id = value.get("case_id")
    if not isinstance(case_id, str) or CASE_ID_RE.fullmatch(case_id) is None:
        issues.append(_issue("invalid_case_id", f"{path}.case_id", "must match the evaluation case ID contract"))
    stack_id = value.get("stack_id")
    if not isinstance(stack_id, str) or stack_id not in ("api", "gcp_local"):
        issues.append(_issue("invalid_stack_id", f"{path}.stack_id", "must be api or gcp_local"))
    for field in ("corpus_manifest_sha256", "eval_set_sha256", "config_sha256"):
        digest = value.get(field)
        if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
            issues.append(_issue("invalid_sha256", f"{path}.{field}", "must be a lowercase SHA-256"))
    for field in ("generator_model", "embedding_model"):
        model = value.get(field)
        if not isinstance(model, str) or not model.strip() or len(model) > 256:
            issues.append(_issue("invalid_model_id", f"{path}.{field}", "must be a non-empty model identifier"))
    if stack_id == "api":
        generator_model = value.get("generator_model")
        if not isinstance(generator_model, str) or generator_model not in ("gpt-5-mini", "gpt-5-nano"):
            issues.append(_issue("api_generator_not_allowed", f"{path}.generator_model", "API generator is outside the assignment allowlist"))
        if value.get("reasoning_effort") != "minimal":
            issues.append(
                _issue(
                    "api_reasoning_effort_not_minimal",
                    f"{path}.reasoning_effort",
                    "API GPT-5 baseline runs must pin reasoning effort to minimal",
                )
            )
        api_profile = value.get("api_profile", "assignment")
        if api_profile not in ("assignment", "personal_experimental"):
            issues.append(
                _issue(
                    "api_profile_not_allowed",
                    f"{path}.api_profile",
                    "API profile must be assignment or personal_experimental",
                )
            )
        embedding_model = value.get("embedding_model")
        allowed_embeddings = (
            ("text-embedding-3-small",)
            if api_profile == "assignment"
            else ("text-embedding-3-small", "text-embedding-3-large")
        )
        if embedding_model not in allowed_embeddings:
            issues.append(
                _issue(
                    "api_embedding_not_allowed",
                    f"{path}.embedding_model",
                    "API embedding model is outside the selected profile allowlist",
                )
            )
        embedding_dimensions = value.get("embedding_dimensions")
        expected_dimensions = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
        }.get(embedding_model)
        if embedding_dimensions is not None and embedding_dimensions != expected_dimensions:
            issues.append(
                _issue(
                    "api_embedding_dimensions_mismatch",
                    f"{path}.embedding_dimensions",
                    "embedding dimensions must match the full-size 2x2 baseline",
                )
            )
        index_config_sha256 = value.get("index_config_sha256")
        if index_config_sha256 is not None and (
            not isinstance(index_config_sha256, str)
            or SHA256_RE.fullmatch(index_config_sha256) is None
        ):
            issues.append(
                _issue(
                    "invalid_sha256",
                    f"{path}.index_config_sha256",
                    "must be a lowercase SHA-256",
                )
            )
        if api_profile == "personal_experimental":
            if embedding_dimensions is None:
                issues.append(
                    _issue(
                        "required_field_missing",
                        f"{path}.embedding_dimensions",
                        "personal experimental API runs require embedding dimensions",
                    )
                )
            if index_config_sha256 is None:
                issues.append(
                    _issue(
                        "required_field_missing",
                        f"{path}.index_config_sha256",
                        "personal experimental API runs require the index config hash",
                    )
                )
    elif stack_id == "gcp_local":
        for field in optional:
            if field in value:
                issues.append(
                    _issue(
                        "api_only_field_forbidden",
                        f"{path}.{field}",
                        "API-only run metadata is forbidden on gcp_local records",
                    )
                )

    environment = value.get("environment")
    environment_fields = (
        "python_version",
        "platform",
        "region",
        "machine_type",
        "vcpu",
        "ram_gb",
        "gpu_model",
        "disk_gb",
        "dependency_lock_sha256",
    )
    if not isinstance(environment, dict):
        issues.append(_issue("invalid_environment", f"{path}.environment", "must be a reproducible environment object"))
    else:
        issues.extend(_validate_required(environment, environment_fields, environment_fields, f"{path}.environment"))
        for field in ("python_version", "platform"):
            item = environment.get(field)
            maximum_length = 64 if field == "python_version" else 256
            if not isinstance(item, str) or not item.strip() or len(item) > maximum_length:
                issues.append(_issue("invalid_environment_value", f"{path}.environment.{field}", "must be a non-empty environment identifier"))
        for field, maximum_length in (("region", 64), ("machine_type", 128)):
            item = environment.get(field)
            if not isinstance(item, str) or not item.strip() or len(item) > maximum_length:
                issues.append(
                    _issue(
                        "invalid_environment_value",
                        f"{path}.environment.{field}",
                        "must be a non-empty environment identifier",
                    )
                )
        vcpu = environment.get("vcpu")
        if not isinstance(vcpu, int) or isinstance(vcpu, bool) or vcpu < 1:
            issues.append(_issue("invalid_vcpu", f"{path}.environment.vcpu", "must be a positive integer"))
        for field in ("ram_gb", "disk_gb"):
            item = environment.get(field)
            if not _is_number(item) or item <= 0:
                issues.append(_issue("invalid_environment_value", f"{path}.environment.{field}", "must be a positive number"))
        gpu_model = environment.get("gpu_model")
        if gpu_model is not None and (not isinstance(gpu_model, str) or not gpu_model.strip() or len(gpu_model) > 256):
            issues.append(_issue("invalid_gpu_model", f"{path}.environment.gpu_model", "must be null or a non-empty GPU identifier"))
        dependency_hash = environment.get("dependency_lock_sha256")
        if not isinstance(dependency_hash, str) or SHA256_RE.fullmatch(dependency_hash) is None:
            issues.append(_issue("invalid_dependency_hash", f"{path}.environment.dependency_lock_sha256", "must be a lowercase SHA-256"))
        if stack_id == "gcp_local":
            if environment.get("region") not in ("us-central1", "us-east1"):
                issues.append(
                    _issue(
                        "gcp_region_not_allowed",
                        f"{path}.environment.region",
                        "GCP scenario region must be us-central1, or us-east1 for chunk4 allocations",
                    )
                )
            if environment.get("machine_type") != "g2-standard-4":
                issues.append(
                    _issue(
                        "gcp_machine_type_mismatch",
                        f"{path}.environment.machine_type",
                        "GCP scenario requires the exact g2-standard-4 machine type",
                    )
                )
            if isinstance(vcpu, int) and not isinstance(vcpu, bool) and vcpu > 4:
                issues.append(_issue("gcp_vcpu_limit_exceeded", f"{path}.environment.vcpu", "GCP scenario is limited to 4 vCPU"))
            if _is_number(environment.get("ram_gb")) and environment["ram_gb"] > 16:
                issues.append(_issue("gcp_ram_limit_exceeded", f"{path}.environment.ram_gb", "GCP scenario is limited to 16 GB RAM"))
            if not isinstance(gpu_model, str) or "L4" not in gpu_model:
                issues.append(_issue("gcp_gpu_not_l4", f"{path}.environment.gpu_model", "GCP scenario requires an NVIDIA L4"))
            if _is_number(environment.get("disk_gb")) and environment["disk_gb"] > 200:
                issues.append(_issue("gcp_disk_limit_exceeded", f"{path}.environment.disk_gb", "GCP scenario is limited to 200 GB disk"))
    git_commit = value.get("git_commit")
    if git_commit != "uncommitted" and (
        not isinstance(git_commit, str) or re.fullmatch(r"^[0-9a-f]{7,64}$", git_commit) is None
    ):
        issues.append(_issue("invalid_git_commit", f"{path}.git_commit", "must be uncommitted or a 7..64 character lowercase Git hash"))
    retrieval = value.get("retrieval")
    ranks: list[int] = []
    if not isinstance(retrieval, list):
        issues.append(_issue("invalid_retrieval", f"{path}.retrieval", "must be an array"))
        retrieval = []
    for index, hit in enumerate(retrieval):
        hit_path = f"{path}.retrieval[{index}]"
        if not isinstance(hit, dict):
            issues.append(_issue("invalid_retrieval_hit", hit_path, "must be an object"))
            continue
        chunk_id = hit.get("chunk_id")
        is_visual_hit = (
            isinstance(chunk_id, str)
            and VISUAL_CHUNK_ID_RE.fullmatch(chunk_id) is not None
        )
        common_hit_fields = ("rank", "doc_id", "chunk_id", "score")
        fusion_fields = ("lane", "lane_rank", "dense_score")
        if is_visual_hit:
            visual_fields = (
                "occurrence_id",
                "evidence_ids",
                "evidence_type",
                "page",
                "bbox",
                "crop_sha256",
            )
            hit_required = common_hit_fields + visual_fields
            issues.extend(
                _validate_required(
                    hit,
                    hit_required,
                    hit_required + fusion_fields,
                    hit_path,
                )
            )
        else:
            hit_required = common_hit_fields + ("source_block_ids",)
            issues.extend(
                _validate_required(
                    hit,
                    hit_required,
                    hit_required + fusion_fields,
                    hit_path,
                )
            )
        rank = hit.get("rank")
        if not isinstance(rank, int) or isinstance(rank, bool) or rank < 1:
            issues.append(_issue("invalid_rank", f"{hit_path}.rank", "must be a positive integer"))
        else:
            ranks.append(rank)
        doc_id = hit.get("doc_id")
        if not isinstance(doc_id, str) or DOC_ID_RE.fullmatch(doc_id) is None:
            issues.append(_issue("invalid_doc_id", f"{hit_path}.doc_id", "must match the doc_id contract"))
        if is_visual_hit:
            visual_citation = {
                "doc_id": hit.get("doc_id"),
                "chunk_id": chunk_id,
                "occurrence_id": hit.get("occurrence_id"),
                "evidence_ids": hit.get("evidence_ids"),
                "evidence_type": hit.get("evidence_type"),
                "locator": {
                    "page": hit.get("page"),
                    "bbox": hit.get("bbox"),
                    "crop_sha256": hit.get("crop_sha256"),
                },
            }
            issues.extend(_validate_visual_citation(visual_citation, hit_path))
        else:
            if not isinstance(chunk_id, str) or CHUNK_ID_RE.fullmatch(chunk_id) is None:
                issues.append(_issue("invalid_chunk_id", f"{hit_path}.chunk_id", "must match the chunk_id contract"))
            block_ids = hit.get("source_block_ids")
            if not isinstance(block_ids, list) or not block_ids:
                issues.append(_issue("source_blocks_empty", f"{hit_path}.source_block_ids", "must list stable source blocks"))
            else:
                if len(block_ids) != len(set(item for item in block_ids if isinstance(item, str))):
                    issues.append(_issue("duplicate_source_block_id", f"{hit_path}.source_block_ids", "source block IDs must be unique"))
                for block_index, block_id in enumerate(block_ids):
                    if not isinstance(block_id, str) or BLOCK_ID_RE.fullmatch(block_id) is None:
                        issues.append(_issue("invalid_block_id", f"{hit_path}.source_block_ids[{block_index}]", "must match the block_id contract"))
        if not _is_number(hit.get("score")):
            issues.append(_issue("invalid_score", f"{hit_path}.score", "must be a finite number"))
        present_fusion_fields = [field for field in fusion_fields if field in hit]
        if present_fusion_fields and len(present_fusion_fields) != len(fusion_fields):
            issues.append(
                _issue(
                    "incomplete_fusion_metadata",
                    hit_path,
                    "lane, lane_rank and dense_score must be present together",
                )
            )
        if "lane" in hit and (
            not isinstance(hit.get("lane"), str)
            or not hit["lane"]
            or len(hit["lane"]) > 64
        ):
            issues.append(_issue("invalid_lane", f"{hit_path}.lane", "must be a short non-empty string"))
        if "lane_rank" in hit and (
            not isinstance(hit.get("lane_rank"), int)
            or isinstance(hit.get("lane_rank"), bool)
            or hit["lane_rank"] < 1
        ):
            issues.append(_issue("invalid_lane_rank", f"{hit_path}.lane_rank", "must be a positive integer"))
        if "dense_score" in hit and not _is_number(hit.get("dense_score")):
            issues.append(_issue("invalid_dense_score", f"{hit_path}.dense_score", "must be a finite number"))
    if ranks and sorted(ranks) != list(range(1, len(ranks) + 1)):
        issues.append(_issue("non_contiguous_ranks", f"{path}.retrieval", "ranks must be unique and contiguous from one"))

    issues.extend(validate_response(value.get("response"), f"{path}.response"))
    timing = value.get("timing_ms")
    if not isinstance(timing, dict):
        issues.append(_issue("invalid_timing", f"{path}.timing_ms", "must be an object"))
    else:
        timing_allowed = ("retrieval", "generation", "total")
        issues.extend(_validate_required(timing, ("total",), timing_allowed, f"{path}.timing_ms"))
        total = timing.get("total")
        if not _is_number(total) or total < 0:
            issues.append(_issue("invalid_total_timing", f"{path}.timing_ms.total", "must be a non-negative number"))
        for field in ("retrieval", "generation"):
            if field in timing and timing[field] is not None and (not _is_number(timing[field]) or timing[field] < 0):
                issues.append(_issue("invalid_timing_value", f"{path}.timing_ms.{field}", "must be null or a non-negative number"))
    usage = value.get("usage")
    usage_fields = ("input_tokens", "output_tokens", "embedding_tokens", "cost_usd", "gpu_seconds", "peak_vram_gb")
    if not isinstance(usage, dict):
        issues.append(_issue("invalid_usage", f"{path}.usage", "must be an object"))
    else:
        issues.extend(_validate_required(usage, usage_fields, usage_fields, f"{path}.usage"))
        for field in usage_fields:
            item = usage.get(field)
            if item is not None and (not _is_number(item) or item < 0):
                issues.append(_issue("invalid_usage_value", f"{path}.usage.{field}", "must be null or a non-negative number"))
            elif field in ("input_tokens", "output_tokens", "embedding_tokens") and item is not None and not isinstance(item, int):
                issues.append(_issue("invalid_token_count", f"{path}.usage.{field}", "token counts must be integers"))
    judgment = value.get("judgment")
    judgment_fields = (
        "matched_key_point_ids",
        "correctness",
        "faithfulness",
        "factual_claim_coverage",
        "citation_validity",
        "follow_up_success",
        "safe_abstention",
        "reviewer_ids",
    )
    if not isinstance(judgment, dict):
        issues.append(_issue("invalid_judgment", f"{path}.judgment", "must be an object"))
    else:
        issues.extend(_validate_required(judgment, judgment_fields, judgment_fields, f"{path}.judgment"))
        point_ids = judgment.get("matched_key_point_ids")
        if not isinstance(point_ids, list) or any(not isinstance(item, str) or KEY_POINT_ID_RE.fullmatch(item) is None for item in point_ids):
            issues.append(_issue("invalid_matched_key_points", f"{path}.judgment.matched_key_point_ids", "must be valid key-point IDs"))
        elif len(point_ids) != len(set(point_ids)):
            issues.append(_issue("duplicate_matched_key_point", f"{path}.judgment.matched_key_point_ids", "matched key-point IDs must be unique"))
        for field in ("correctness", "faithfulness", "factual_claim_coverage", "citation_validity"):
            item = judgment.get(field)
            if item is not None and (not _is_number(item) or not 0 <= item <= 1):
                issues.append(_issue("invalid_judgment_score", f"{path}.judgment.{field}", "must be null or a number from zero to one"))
        follow_up_success = judgment.get("follow_up_success")
        if follow_up_success is not None and not isinstance(follow_up_success, bool):
            issues.append(_issue("invalid_follow_up_success", f"{path}.judgment.follow_up_success", "must be boolean or null"))
        safe_abstention = judgment.get("safe_abstention")
        if safe_abstention is not None and not isinstance(safe_abstention, bool):
            issues.append(_issue("invalid_safe_abstention", f"{path}.judgment.safe_abstention", "must be boolean or null"))
        reviewers = judgment.get("reviewer_ids")
        if not isinstance(reviewers, list) or any(not isinstance(item, str) or not item or len(item) > 128 for item in reviewers):
            issues.append(_issue("invalid_reviewer_ids", f"{path}.judgment.reviewer_ids", "must be an array of reviewer IDs"))
        elif len(reviewers) != len(set(reviewers)):
            issues.append(_issue("duplicate_reviewer_id", f"{path}.judgment.reviewer_ids", "reviewer IDs must be unique"))
    temperature = value.get("temperature")
    if temperature is not None and (not _is_number(temperature) or temperature < 0):
        issues.append(
            _issue(
                "invalid_temperature",
                f"{path}.temperature",
                "must be null when unsupported or a non-negative number",
            )
        )
    if value.get("seed") is not None and (not isinstance(value.get("seed"), int) or isinstance(value.get("seed"), bool)):
        issues.append(_issue("invalid_seed", f"{path}.seed", "must be an integer or null"))
    if not isinstance(value.get("cache_hit"), bool):
        issues.append(_issue("invalid_cache_hit", f"{path}.cache_hit", "must be boolean"))
    return issues


def _mean(values: Sequence[float]) -> float | None:
    return round(fmean(values), 6) if values else None


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return round(float(ordered[rank - 1]), 6)


def _ranked_docs(retrieval: Any) -> list[str]:
    if not isinstance(retrieval, list):
        return []
    ordered = sorted(
        (hit for hit in retrieval if isinstance(hit, dict) and isinstance(hit.get("rank"), int)),
        key=lambda item: item["rank"],
    )
    result: list[str] = []
    for hit in ordered:
        doc_id = hit.get("doc_id")
        if isinstance(doc_id, str):
            result.append(doc_id)
    return result


def _retrieved_blocks(retrieval: Any, k: int) -> set[str]:
    if not isinstance(retrieval, list):
        return set()
    result: set[str] = set()
    def rank_key(item: Mapping[str, Any]) -> int:
        rank = item.get("rank")
        return rank if isinstance(rank, int) and not isinstance(rank, bool) else 10**9

    for hit in sorted((item for item in retrieval if isinstance(item, dict)), key=rank_key)[:k]:
        blocks = hit.get("source_block_ids")
        if isinstance(blocks, list):
            result.update(block for block in blocks if isinstance(block, str))
    return result


def _dcg(relevances: Sequence[int]) -> float:
    return sum(relevance / math.log2(index + 2) for index, relevance in enumerate(relevances))


def _flatten_numbers(value: Any, prefix: str = "") -> dict[str, float]:
    flattened: dict[str, float] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else key
            flattened.update(_flatten_numbers(child, child_prefix))
    elif _is_number(value):
        flattened[prefix] = float(value)
    return flattened


def _lookup(value: Mapping[str, Any], dotted_path: str) -> Any:
    current: Any = value
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def evaluate_thresholds(report: Mapping[str, Any], config: Mapping[str, Any] | None) -> dict[str, Any]:
    config_errors = validate_evaluation_config(config)
    thresholds = config.get("thresholds", {}) if isinstance(config, dict) and isinstance(config.get("thresholds"), dict) else {}
    results: list[dict[str, Any]] = []
    for metric_path, rule in sorted(thresholds.items()):
        if not isinstance(rule, dict):
            continue
        applies_to = rule.get("applies_to")
        if isinstance(applies_to, list) and report.get("stack_id") not in applies_to:
            continue
        actual = _lookup(report, metric_path)
        operator = rule.get("operator")
        expected = rule.get("value")
        passed = False
        if _is_number(actual) and _is_number(expected):
            if operator == ">=":
                passed = actual >= expected
            elif operator == "<=":
                passed = actual <= expected
            elif operator == "==":
                passed = actual == expected
        results.append(
            {
                "metric": metric_path,
                "operator": operator,
                "expected": expected,
                "actual": actual,
                "passed": passed,
            }
        )
    return {
        "passed": not config_errors and bool(results) and all(item["passed"] for item in results),
        "results": results,
        "errors": config_errors,
    }


def score_runs(
    cases: Sequence[dict[str, Any]],
    runs: Sequence[dict[str, Any]],
    *,
    k_values: Sequence[int] = (1, 3, 5, 10),
    config: Mapping[str, Any] | None = None,
    scoring_config_sha256: str | None = None,
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    errors.extend(validate_evaluation_config(config))
    if not isinstance(scoring_config_sha256, str) or SHA256_RE.fullmatch(scoring_config_sha256) is None:
        errors.append(_issue("invalid_scoring_config_hash", "scoring_config_sha256", "a lowercase SHA-256 is required"))
    configured_k = config.get("k_values") if isinstance(config, Mapping) else None
    if not isinstance(configured_k, list) or list(k_values) != configured_k:
        errors.append(_issue("k_values_config_mismatch", "k_values", "scoring cutoffs must exactly match the frozen config"))
    case_map: dict[str, dict[str, Any]] = {}
    for index, case in enumerate(cases):
        case_issues = validate_case(case, f"cases[{index}]")
        errors.extend(case_issues)
        if not isinstance(case, dict):
            continue
        review = case.get("review")
        if not isinstance(review, dict) or review.get("status") != "approved":
            errors.append(_issue("case_not_approved", f"cases[{index}].review.status", "scoring requires approved evaluation cases"))
        case_id = case.get("case_id")
        if isinstance(case_id, str):
            if case_id in case_map:
                errors.append(_issue("duplicate_case_id", f"cases[{index}].case_id", "case ID must be unique"))
            case_map[case_id] = case

    case_splits = {
        case.get("split")
        for case in case_map.values()
        if isinstance(case.get("split"), str) and case.get("split") in SPLITS
    }
    if len(case_splits) != 1:
        errors.append(_issue("mixed_or_missing_score_split", "cases", "one score report must use exactly one evaluation split"))
    else:
        score_split = next(iter(case_splits))
        minimums_by_split = config.get("minimum_cases") if isinstance(config, Mapping) else None
        selected_minimums = minimums_by_split.get(score_split) if isinstance(minimums_by_split, Mapping) else None
        configured_minimums = selected_minimums if isinstance(selected_minimums, Mapping) else {}
        task_counts = Counter(
            case.get("task_type")
            for case in case_map.values()
            if isinstance(case.get("task_type"), str)
        )
        for task in TASK_TYPES:
            minimum = configured_minimums.get(task)
            if not isinstance(minimum, int) or isinstance(minimum, bool) or task_counts[task] < minimum:
                errors.append(_issue("insufficient_scoring_cases", f"cases.{score_split}.{task}", "score set does not meet the frozen task floor"))

    expected_eval_hash = dataset_sha256(cases)
    run_map: dict[str, dict[str, Any]] = {}
    response_contract_errors = 0
    for index, run in enumerate(runs):
        run_errors = validate_run_record(run, f"runs[{index}]")
        errors.extend(run_errors)
        if not isinstance(run, dict):
            continue
        if validate_response(run.get("response"), f"runs[{index}].response"):
            response_contract_errors += 1
        case_id = run.get("case_id")
        if not isinstance(case_id, str):
            continue
        if case_id not in case_map:
            errors.append(_issue("run_case_missing", f"runs[{index}].case_id", "run references an unknown case"))
            continue
        if case_id in run_map:
            errors.append(_issue("duplicate_run_case", f"runs[{index}].case_id", "only one run per case is allowed"))
        run_map[case_id] = run
        if run.get("eval_set_sha256") != expected_eval_hash:
            errors.append(_issue("eval_hash_mismatch", f"runs[{index}].eval_set_sha256", "run does not match the supplied evaluation set"))
        if run.get("corpus_manifest_sha256") != case_map[case_id].get("source_manifest_sha256"):
            errors.append(_issue("corpus_hash_mismatch", f"runs[{index}].corpus_manifest_sha256", "run and case corpus snapshots differ"))

    missing_runs = sorted(case_id for case_id in case_map if case_id not in run_map)
    for case_id in missing_runs:
        errors.append(_issue("case_run_missing", "runs", f"missing run for case: {case_id}"))

    stack_ids = {
        run.get("stack_id")
        for run in runs
        if isinstance(run, dict) and isinstance(run.get("stack_id"), str)
    }
    corpus_hashes = {
        run.get("corpus_manifest_sha256")
        for run in runs
        if isinstance(run, dict) and isinstance(run.get("corpus_manifest_sha256"), str)
    }
    config_hashes = {
        run.get("config_sha256")
        for run in runs
        if isinstance(run, dict) and isinstance(run.get("config_sha256"), str)
    }
    if len(stack_ids) != 1:
        errors.append(_issue("mixed_stack_ids", "runs", "one score report must contain one stack"))
    if len(corpus_hashes) != 1:
        errors.append(_issue("mixed_corpus_hashes", "runs", "one score report must contain one corpus snapshot"))
    if len(config_hashes) != 1:
        errors.append(_issue("mixed_config_hashes", "runs", "one score report must contain one configuration"))

    normalized_k = sorted(
        {
            int(k)
            for k in (configured_k if isinstance(configured_k, list) else k_values)
            if isinstance(k, int) and not isinstance(k, bool) and k > 0
        }
    )
    if not normalized_k:
        normalized_k = [1, 3, 5, 10]
    doc_recalls: dict[int, list[float]] = {k: [] for k in normalized_k}
    block_recalls: dict[int, list[float]] = {k: [] for k in normalized_k}
    all_required: dict[int, list[float]] = {k: [] for k in normalized_k}
    reciprocal_ranks: list[float] = []
    ndcg_at_10: list[float] = []
    key_point_coverages: list[float] = []
    correctness_scores: list[float] = []
    faithfulness_scores: list[float] = []
    factual_claim_coverages: list[float] = []
    judgment_citation_validities: list[float] = []
    gold_citation_precisions: list[float] = []
    follow_up_successes: list[float] = []
    total_latencies: list[float] = []
    retrieval_latencies: list[float] = []
    generation_latencies: list[float] = []
    costs: list[float] = []
    gpu_seconds: list[float] = []
    peak_vram: list[float] = []
    judgment_completeness: list[float] = []
    api_cost_completeness: list[float] = []
    local_gpu_completeness: list[float] = []
    safe_abstentions: list[float] = []
    true_positive_abstain = 0
    false_positive_abstain = 0
    false_negative_abstain = 0
    answerable_cases = 0
    answerable_abstentions = 0
    runtime_errors = 0
    task_success: dict[str, list[float]] = {task: [] for task in TASK_TYPES}

    for case_id, case in case_map.items():
        run = run_map.get(case_id)
        if run is None:
            continue
        response = run.get("response") if isinstance(run.get("response"), dict) else {}
        response_is_valid = not validate_response(response)
        status = response.get("status")
        gold = case.get("gold") if isinstance(case.get("gold"), dict) else {}
        judgment = run.get("judgment") if isinstance(run.get("judgment"), dict) else {}
        reviewers = judgment.get("reviewer_ids")
        minimum_reviewers = 2 if case.get("split") == "heldout" else 1
        valid_reviewers = (
            {reviewer for reviewer in reviewers if isinstance(reviewer, str) and reviewer}
            if isinstance(reviewers, list)
            else set()
        )
        reviewers_complete = len(valid_reviewers) >= minimum_reviewers
        actual_abstain = gold.get("decision") == "abstain"
        predicted_abstain = status == "abstained"
        safe_abstention = judgment.get("safe_abstention")
        response_abstention = response.get("abstention") if isinstance(response.get("abstention"), dict) else {}
        reason_matches = response_abstention.get("reason") == gold.get("abstain_reason")
        successful_abstain = (
            predicted_abstain
            and response_is_valid
            and safe_abstention is True
            and reviewers_complete
            and reason_matches
        )
        if actual_abstain and predicted_abstain and not reason_matches:
            errors.append(_issue("abstention_reason_mismatch", f"runs[{case_id}].response.abstention.reason", "response reason must match the sealed gold reason"))
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
            if predicted_abstain:
                answerable_abstentions += 1
        if status == "error":
            runtime_errors += 1
        task_type = case.get("task_type")
        if isinstance(task_type, str) and task_type in task_success:
            successful_response = successful_abstain if actual_abstain else status == "answered" and response_is_valid
            task_success[task_type].append(float(successful_response))

        relevant_docs = (
            {doc_id for doc_id in gold.get("required_doc_ids", []) if isinstance(doc_id, str)}
            if isinstance(gold.get("required_doc_ids"), list)
            else set()
        )
        evidence_refs = gold.get("evidence_refs", []) if isinstance(gold.get("evidence_refs"), list) else []
        relevant_blocks = {
            ref.get("source_block_id")
            for ref in evidence_refs
            if isinstance(ref, dict) and isinstance(ref.get("source_block_id"), str)
        }
        ranked_docs = _ranked_docs(run.get("retrieval"))
        scope = case.get("document_scope")
        if isinstance(scope, dict) and scope.get("mode") == "explicit" and isinstance(scope.get("doc_ids"), list):
            allowed_doc_ids = {doc_id for doc_id in scope["doc_ids"] if isinstance(doc_id, str)}
            retrieval = run.get("retrieval") if isinstance(run.get("retrieval"), list) else []
            for index, hit in enumerate(retrieval):
                if isinstance(hit, dict) and isinstance(hit.get("doc_id"), str) and hit["doc_id"] not in allowed_doc_ids:
                    errors.append(_issue("retrieval_doc_outside_scope", f"runs[{case_id}].retrieval[{index}].doc_id", "retrieval hit is outside the explicit document scope"))
            response_citations = response.get("citations") if isinstance(response.get("citations"), list) else []
            for index, citation in enumerate(response_citations):
                if isinstance(citation, dict) and isinstance(citation.get("doc_id"), str) and citation["doc_id"] not in allowed_doc_ids:
                    errors.append(_issue("citation_doc_outside_scope", f"runs[{case_id}].response.citations[{index}].doc_id", "citation is outside the explicit document scope"))
        if relevant_docs:
            for k in normalized_k:
                top_docs = set(ranked_docs[:k])
                doc_recalls[k].append(len(top_docs & relevant_docs) / len(relevant_docs))
                if task_type == "multi_doc_compare":
                    all_required[k].append(float(relevant_docs <= top_docs))
                if relevant_blocks:
                    retrieved_blocks = _retrieved_blocks(run.get("retrieval"), k)
                    block_recalls[k].append(len(retrieved_blocks & relevant_blocks) / len(relevant_blocks))
            first_rank = next((index + 1 for index, doc_id in enumerate(ranked_docs[:10]) if doc_id in relevant_docs), None)
            reciprocal_ranks.append(0.0 if first_rank is None else 1.0 / first_rank)
            seen_relevant_docs: set[str] = set()
            relevances: list[int] = []
            for doc_id in ranked_docs[:10]:
                is_new_relevant = doc_id in relevant_docs and doc_id not in seen_relevant_docs
                relevances.append(int(is_new_relevant))
                if is_new_relevant:
                    seen_relevant_docs.add(doc_id)
            ideal = [1] * min(len(relevant_docs), 10)
            ideal_dcg = _dcg(ideal)
            ndcg_at_10.append(0.0 if ideal_dcg == 0 else _dcg(relevances) / ideal_dcg)

        if actual_abstain:
            complete = isinstance(safe_abstention, bool) and reviewers_complete
            if safe_abstention is not True:
                errors.append(_issue("unsafe_abstention", f"runs[{case_id}].judgment.safe_abstention", "unknown-case abstention must be reviewed as safe"))
        else:
            human_fields = ("correctness", "faithfulness", "factual_claim_coverage", "citation_validity")
            complete = all(_is_number(judgment.get(field)) for field in human_fields)
            if task_type == "follow_up":
                complete = complete and isinstance(judgment.get("follow_up_success"), bool)
            complete = complete and len(valid_reviewers) >= minimum_reviewers
            if safe_abstention is not None:
                errors.append(_issue("unexpected_safe_abstention", f"runs[{case_id}].judgment.safe_abstention", "answerable cases must use null"))
        judgment_completeness.append(float(complete))
        if not complete:
            errors.append(_issue("human_judgment_missing", f"runs[{case_id}].judgment", "run lacks the required reviewed judgment fields"))
        required_key_points = gold.get("required_key_points")
        gold_points = {
            item.get("point_id")
            for item in (required_key_points if isinstance(required_key_points, list) else [])
            if isinstance(item, dict) and isinstance(item.get("point_id"), str)
        }
        matched_points = (
            {
                point_id
                for point_id in judgment.get("matched_key_point_ids", [])
                if isinstance(point_id, str)
            }
            if isinstance(judgment.get("matched_key_point_ids"), list)
            else set()
        )
        if gold_points:
            key_point_coverages.append(len(gold_points & matched_points) / len(gold_points))
        for field, destination in (
            ("correctness", correctness_scores),
            ("faithfulness", faithfulness_scores),
            ("factual_claim_coverage", factual_claim_coverages),
            ("citation_validity", judgment_citation_validities),
        ):
            score = judgment.get(field)
            if _is_number(score) and 0 <= score <= 1:
                destination.append(float(score))
        if task_type == "follow_up" and isinstance(judgment.get("follow_up_success"), bool):
            follow_up_successes.append(float(judgment["follow_up_success"]))

        citations = response.get("citations") if isinstance(response.get("citations"), list) else []
        gold_evidence_pairs = {
            (reference.get("doc_id"), reference.get("source_block_id"))
            for reference in evidence_refs
            if isinstance(reference, dict)
            and isinstance(reference.get("doc_id"), str)
            and isinstance(reference.get("source_block_id"), str)
        }
        gold_visual_evidence = {
            (
                reference.get("doc_id"),
                reference.get("occurrence_id"),
                reference.get("evidence_type"),
                frozenset(reference.get("evidence_ids", [])),
            )
            for reference in evidence_refs
            if isinstance(reference, dict)
            and isinstance(reference.get("doc_id"), str)
            and isinstance(reference.get("occurrence_id"), str)
            and isinstance(reference.get("evidence_type"), str)
            and isinstance(reference.get("evidence_ids"), list)
            and reference.get("evidence_ids")
            and all(isinstance(item, str) for item in reference["evidence_ids"])
        }
        scored_citations: list[float] = []
        for citation in citations:
            if not isinstance(citation, dict):
                continue
            chunk_id = citation.get("chunk_id")
            is_visual_citation = (
                isinstance(chunk_id, str)
                and VISUAL_CHUNK_ID_RE.fullmatch(chunk_id) is not None
            )
            if is_visual_citation:
                # A visual citation is scored only when the sealed case includes
                # visual gold. This avoids treating an unannotated evidence lane
                # as a false match while still scoring exact occurrence/evidence
                # identities whenever that gold exists.
                if not gold_visual_evidence:
                    continue
                citation_ids = citation.get("evidence_ids")
                visual_key = (
                    citation.get("doc_id"),
                    citation.get("occurrence_id"),
                    citation.get("evidence_type"),
                    frozenset(citation_ids)
                    if isinstance(citation_ids, list)
                    and all(isinstance(item, str) for item in citation_ids)
                    else frozenset(),
                )
                scored_citations.append(float(visual_key in gold_visual_evidence))
                continue
            if not gold_evidence_pairs:
                continue
            citation_blocks = (
                {
                    block_id
                    for block_id in citation.get("source_block_ids", [])
                    if isinstance(block_id, str)
                }
                if isinstance(citation.get("source_block_ids"), list)
                else set()
            )
            citation_doc_id = citation.get("doc_id")
            scored_citations.append(
                float(
                    isinstance(citation_doc_id, str)
                    and any(
                        (citation_doc_id, block_id) in gold_evidence_pairs
                        for block_id in citation_blocks
                    )
                )
            )
        if scored_citations:
            gold_citation_precisions.append(_mean(scored_citations))

        timing = run.get("timing_ms") if isinstance(run.get("timing_ms"), dict) else {}
        for field, destination in (
            ("total", total_latencies),
            ("retrieval", retrieval_latencies),
            ("generation", generation_latencies),
        ):
            item = timing.get(field)
            if _is_number(item) and item >= 0:
                destination.append(float(item))
        usage = run.get("usage") if isinstance(run.get("usage"), dict) else {}
        stack_id = run.get("stack_id")
        if stack_id == "api":
            has_cost = _is_number(usage.get("cost_usd")) and usage["cost_usd"] >= 0
            api_cost_completeness.append(float(has_cost))
            if not has_cost:
                errors.append(_issue("api_cost_missing", f"runs[{case_id}].usage.cost_usd", "every API run needs a non-negative cost measurement"))
        elif stack_id == "gcp_local":
            has_gpu = (
                _is_number(usage.get("gpu_seconds"))
                and usage["gpu_seconds"] >= 0
                and _is_number(usage.get("peak_vram_gb"))
                and usage["peak_vram_gb"] >= 0
            )
            local_gpu_completeness.append(float(has_gpu))
            if not has_gpu:
                errors.append(_issue("local_gpu_usage_missing", f"runs[{case_id}].usage", "every local run needs GPU seconds and peak VRAM"))
        for field, destination in (
            ("cost_usd", costs),
            ("gpu_seconds", gpu_seconds),
            ("peak_vram_gb", peak_vram),
        ):
            item = usage.get(field)
            if _is_number(item) and item >= 0:
                destination.append(float(item))

    precision_denominator = true_positive_abstain + false_positive_abstain
    recall_denominator = true_positive_abstain + false_negative_abstain
    total_scored = len(run_map)
    metrics: dict[str, Any] = {
        "retrieval": {
            **{f"document_recall_at_{k}": _mean(values) for k, values in doc_recalls.items()},
            **{f"source_block_recall_at_{k}": _mean(values) for k, values in block_recalls.items()},
            **{f"all_required_docs_recalled_at_{k}": _mean(values) for k, values in all_required.items()},
            "mrr_at_10": _mean(reciprocal_ranks),
            "ndcg_at_10": _mean(ndcg_at_10),
        },
        "answer": {
            "key_point_coverage": _mean(key_point_coverages),
            "correctness": _mean(correctness_scores),
            "faithfulness": _mean(faithfulness_scores),
            "factual_claim_coverage": _mean(factual_claim_coverages),
            "citation_validity": _mean(judgment_citation_validities),
            "gold_citation_precision": _mean(gold_citation_precisions),
            "follow_up_success": _mean(follow_up_successes),
            "judgment_coverage": _mean(judgment_completeness),
        },
        "abstention": {
            "precision": None if precision_denominator == 0 else round(true_positive_abstain / precision_denominator, 6),
            "recall": None if recall_denominator == 0 else round(true_positive_abstain / recall_denominator, 6),
            "safe_abstention_rate": _mean(safe_abstentions),
            "false_answer_rate": None if recall_denominator == 0 else round(false_negative_abstain / recall_denominator, 6),
            "answerable_false_abstain_rate": None if answerable_cases == 0 else round(answerable_abstentions / answerable_cases, 6),
        },
        "task_success": {task: _mean(values) for task, values in task_success.items()},
        "operations": {
            "response_contract_error_rate": None if total_scored == 0 else round(response_contract_errors / total_scored, 6),
            "runtime_error_rate": None if total_scored == 0 else round(runtime_errors / total_scored, 6),
            "latency_total_p50_ms": _percentile(total_latencies, 0.50),
            "latency_total_p95_ms": _percentile(total_latencies, 0.95),
            "latency_retrieval_p50_ms": _percentile(retrieval_latencies, 0.50),
            "latency_generation_p50_ms": _percentile(generation_latencies, 0.50),
            "total_cost_usd": round(sum(costs), 6) if costs else None,
            "mean_cost_usd": _mean(costs),
            "total_gpu_seconds": round(sum(gpu_seconds), 6) if gpu_seconds else None,
            "mean_gpu_seconds": _mean(gpu_seconds),
            "peak_vram_gb": round(max(peak_vram), 6) if peak_vram else None,
            "api_cost_coverage": _mean(api_cost_completeness),
            "local_gpu_usage_coverage": _mean(local_gpu_completeness),
        },
    }
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "passed": not errors,
        "stack_id": next(iter(stack_ids)) if len(stack_ids) == 1 else None,
        "corpus_manifest_sha256": next(iter(corpus_hashes)) if len(corpus_hashes) == 1 else None,
        "eval_set_sha256": expected_eval_hash,
        "config_sha256": next(iter(config_hashes)) if len(config_hashes) == 1 else None,
        "scoring_config_sha256": scoring_config_sha256,
        "counts": {
            "cases": len(case_map),
            "runs": len(run_map),
            "missing_runs": len(missing_runs),
            "by_task": {
                task: sum(isinstance(case, dict) and case.get("task_type") == task for case in cases)
                for task in TASK_TYPES
            },
        },
        "metrics": metrics,
        "errors": errors,
    }
    threshold_report = evaluate_thresholds(report, config)
    if report["stack_id"] == "api" and metrics["operations"]["total_cost_usd"] is not None:
        if metrics["operations"]["total_cost_usd"] > 20:
            report["errors"].append(_issue("api_budget_exceeded", "metrics.operations.total_cost_usd", "API evaluation spend exceeds USD 20"))
            report["passed"] = False
    report["thresholds"] = threshold_report
    report["passed"] = report["passed"] and threshold_report["passed"]
    return report


def _validate_comparison_report(label: str, report: Mapping[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if report.get("schema_version") != "1.0":
        errors.append(_issue("invalid_score_report", f"{label}.schema_version", "score report schema version is missing or unsupported"))
    report_stack_id = report.get("stack_id")
    if not isinstance(report_stack_id, str) or report_stack_id not in STACK_IDS:
        errors.append(_issue("invalid_score_report", f"{label}.stack_id", "score report stack is missing or unsupported"))
    if report.get("passed") is not True:
        errors.append(_issue("source_score_report_failed", f"{label}.passed", "only passed score reports can be compared"))
    for field in ("corpus_manifest_sha256", "eval_set_sha256", "config_sha256", "scoring_config_sha256"):
        digest = report.get(field)
        if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
            errors.append(_issue("invalid_score_report", f"{label}.{field}", "score report hash is missing or invalid"))

    counts = report.get("counts")
    if not isinstance(counts, dict):
        errors.append(_issue("invalid_score_report", f"{label}.counts", "score report counts object is missing"))
    else:
        for field in ("cases", "runs"):
            count = counts.get(field)
            if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                errors.append(_issue("invalid_score_report", f"{label}.counts.{field}", "must be a positive integer"))
        if counts.get("cases") != counts.get("runs") or counts.get("missing_runs") != 0:
            errors.append(_issue("incomplete_score_report", f"{label}.counts", "all cases must have exactly one run"))
        by_task = counts.get("by_task")
        if not isinstance(by_task, dict):
            errors.append(_issue("invalid_score_report", f"{label}.counts.by_task", "task counts are missing"))
        else:
            task_total = 0
            for task in TASK_TYPES:
                count = by_task.get(task)
                if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                    errors.append(_issue("invalid_score_report", f"{label}.counts.by_task.{task}", "must be a positive integer"))
                else:
                    task_total += count
            if isinstance(counts.get("cases"), int) and task_total != counts["cases"]:
                errors.append(_issue("invalid_score_report", f"{label}.counts.by_task", "task counts must sum to the case count"))

    metrics = report.get("metrics")
    if not isinstance(metrics, dict):
        errors.append(_issue("invalid_score_report", f"{label}.metrics", "score report metrics object is missing"))
    else:
        for section in sorted(REQUIRED_METRIC_SECTIONS - metrics.keys()):
            errors.append(_issue("score_metric_section_missing", f"{label}.metrics.{section}", "required metric section is missing"))
        for section, expected_keys in EXPECTED_METRIC_KEYS.items():
            section_metrics = metrics.get(section)
            if not isinstance(section_metrics, dict):
                errors.append(_issue("invalid_score_metric_section", f"{label}.metrics.{section}", "must be a metric object"))
                continue
            for key in sorted(expected_keys - section_metrics.keys()):
                errors.append(_issue("score_metric_missing", f"{label}.metrics.{section}.{key}", "emitted metric is missing"))
            for key in sorted(expected_keys & section_metrics.keys()):
                item = section_metrics[key]
                if item is not None and not _is_number(item):
                    errors.append(_issue("invalid_score_metric", f"{label}.metrics.{section}.{key}", "must be a finite number or null"))
        required_metrics = set(REQUIRED_COMMON_THRESHOLDS)
        if isinstance(report_stack_id, str):
            required_metrics.update(
                metric_path
                for metric_path, stack_id in REQUIRED_STACK_THRESHOLDS.items()
                if stack_id == report_stack_id
            )
        for metric_path in sorted(required_metrics):
            if not _is_number(_lookup(report, metric_path)):
                errors.append(_issue("score_metric_missing", f"{label}.{metric_path}", "required comparison metric is missing"))
        task_metrics = metrics.get("task_success")
        if isinstance(task_metrics, dict):
            for task in TASK_TYPES:
                if not _is_number(task_metrics.get(task)):
                    errors.append(_issue("score_metric_missing", f"{label}.metrics.task_success.{task}", "task success metric is missing"))
        operations = metrics.get("operations")
        if isinstance(operations, dict) and isinstance(report_stack_id, str):
            stack_required_operations = {
                "api": ("total_cost_usd", "mean_cost_usd", "api_cost_coverage"),
                "gcp_local": ("total_gpu_seconds", "mean_gpu_seconds", "peak_vram_gb", "local_gpu_usage_coverage"),
            }
            for key in stack_required_operations.get(report_stack_id, ()):
                if not _is_number(operations.get(key)):
                    errors.append(_issue("score_metric_missing", f"{label}.metrics.operations.{key}", "stack-specific operational metric is missing"))

    source_errors = report.get("errors")
    if not isinstance(source_errors, list):
        errors.append(_issue("invalid_score_report", f"{label}.errors", "score report errors array is missing"))
    elif source_errors:
        errors.append(_issue("source_score_report_has_errors", f"{label}.errors", "score report contains validation errors"))
    thresholds = report.get("thresholds")
    if not isinstance(thresholds, dict) or thresholds.get("passed") is not True:
        errors.append(_issue("source_thresholds_failed", f"{label}.thresholds", "score report hard gates are missing or failed"))
    else:
        results = thresholds.get("results")
        if not isinstance(results, list) or not results or thresholds.get("errors") != []:
            errors.append(_issue("invalid_score_report", f"{label}.thresholds", "threshold evidence is incomplete"))
        else:
            result_map: dict[str, dict[str, Any]] = {}
            for index, result in enumerate(results):
                metric_path = result.get("metric") if isinstance(result, dict) else None
                if not isinstance(metric_path, str) or metric_path in result_map:
                    errors.append(_issue("invalid_score_report", f"{label}.thresholds.results[{index}]", "threshold metric must be unique"))
                    continue
                result_map[metric_path] = result
            expected_rules = {
                metric_path: rule
                for metric_path, rule in FROZEN_THRESHOLDS.items()
                if rule[2] is None or report_stack_id in rule[2]
            }
            if result_map.keys() != expected_rules.keys():
                errors.append(_issue("invalid_score_report", f"{label}.thresholds.results", "threshold evidence must cover exactly the applicable frozen gates"))
            for metric_path, (operator, expected, _) in expected_rules.items():
                actual = _lookup(report, metric_path)
                recomputed = False
                if _is_number(actual):
                    if operator == ">=":
                        recomputed = actual >= expected
                    elif operator == "<=":
                        recomputed = actual <= expected
                    else:
                        recomputed = actual == expected
                evidence = result_map.get(metric_path)
                if (
                    not isinstance(evidence, dict)
                    or evidence.get("operator") != operator
                    or evidence.get("expected") != expected
                    or evidence.get("actual") != actual
                    or evidence.get("passed") is not recomputed
                ):
                    errors.append(_issue("stale_threshold_evidence", f"{label}.thresholds.{metric_path}", "threshold evidence does not match report metrics"))
                if not recomputed:
                    errors.append(_issue("source_thresholds_failed", f"{label}.{metric_path}", "frozen threshold is not satisfied"))
    return errors


def compare_reports(baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    errors = _validate_comparison_report("baseline", baseline)
    errors.extend(_validate_comparison_report("candidate", candidate))
    baseline_stack_id = baseline.get("stack_id")
    candidate_stack_id = candidate.get("stack_id")
    valid_stack_pair = (
        isinstance(baseline_stack_id, str)
        and isinstance(candidate_stack_id, str)
        and baseline_stack_id != candidate_stack_id
        and baseline_stack_id in STACK_IDS
        and candidate_stack_id in STACK_IDS
    )
    if not valid_stack_pair:
        errors.append(_issue("comparison_stack_pair_invalid", "stack_id", "comparison requires one API and one GCP-local report"))
    baseline_counts = baseline.get("counts")
    candidate_counts = candidate.get("counts")
    if isinstance(baseline_counts, dict) and isinstance(candidate_counts, dict):
        baseline_count_shape = {key: baseline_counts.get(key) for key in ("cases", "runs", "missing_runs", "by_task")}
        candidate_count_shape = {key: candidate_counts.get(key) for key in ("cases", "runs", "missing_runs", "by_task")}
        if baseline_count_shape != candidate_count_shape:
            errors.append(_issue("comparison_count_mismatch", "counts", "reports must cover the same case and task counts"))
    for field in ("corpus_manifest_sha256", "eval_set_sha256"):
        if baseline.get(field) != candidate.get(field):
            errors.append(_issue("comparison_hash_mismatch", field, "baseline and candidate must use the same snapshot"))
    baseline_scoring_hash = baseline.get("scoring_config_sha256")
    candidate_scoring_hash = candidate.get("scoring_config_sha256")
    if (
        not isinstance(baseline_scoring_hash, str)
        or SHA256_RE.fullmatch(baseline_scoring_hash) is None
        or not isinstance(candidate_scoring_hash, str)
        or SHA256_RE.fullmatch(candidate_scoring_hash) is None
        or baseline_scoring_hash != candidate_scoring_hash
    ):
        errors.append(_issue("comparison_scoring_config_mismatch", "scoring_config_sha256", "baseline and candidate must use the same scoring configuration"))
    baseline_metrics = _flatten_numbers(baseline.get("metrics", {}))
    candidate_metrics = _flatten_numbers(candidate.get("metrics", {}))
    deltas: dict[str, dict[str, float | None]] = {}
    for metric in sorted(baseline_metrics.keys() & candidate_metrics.keys()):
        baseline_value = baseline_metrics[metric]
        candidate_value = candidate_metrics[metric]
        deltas[metric] = {
            "baseline": round(baseline_value, 6),
            "candidate": round(candidate_value, 6),
            "delta": round(candidate_value - baseline_value, 6),
            "relative_delta": None if baseline_value == 0 else round((candidate_value - baseline_value) / abs(baseline_value), 6),
        }
    if not deltas:
        errors.append(_issue("comparison_metrics_missing", "metrics", "reports do not share numeric metrics"))
    return {
        "schema_version": "1.0",
        "passed": not errors,
        "baseline_stack_id": baseline.get("stack_id"),
        "candidate_stack_id": candidate.get("stack_id"),
        "corpus_manifest_sha256": baseline.get("corpus_manifest_sha256"),
        "eval_set_sha256": baseline.get("eval_set_sha256"),
        "deltas": deltas,
        "errors": errors,
    }


def _read_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("evaluation config must be a JSON object")
    return value


def _load_manifest_context(
    manifest: Path | None,
    blocks_dir: Path | None,
) -> tuple[set[str] | None, dict[str, str] | None, dict[str, str] | None, str | None]:
    if manifest is None:
        if blocks_dir is not None:
            raise ValueError("--blocks-dir requires --manifest")
        return None, None, None, None
    entries = read_jsonl(manifest)
    doc_ids = {entry.get("doc_id") for entry in entries if isinstance(entry.get("doc_id"), str)}
    owners: dict[str, str] | None = None
    locator_hashes: dict[str, str] | None = None
    if blocks_dir is not None:
        owners = {}
        locator_hashes = {}
        resolved_blocks_dir = blocks_dir.resolve()
        if not resolved_blocks_dir.is_dir():
            raise ValueError("blocks_directory_missing")
        for path in sorted(resolved_blocks_dir.glob("*.jsonl")):
            resolved_path = require_within(path, resolved_blocks_dir, "blocks_path_outside_directory")
            for block in read_jsonl(resolved_path):
                block_id = block.get("block_id")
                doc_id = block.get("doc_id")
                if isinstance(block_id, str) and isinstance(doc_id, str):
                    if block_id in owners:
                        raise ValueError("duplicate source block ID in block snapshot")
                    owners[block_id] = doc_id
                    source_locator = block.get("source_locator")
                    if not isinstance(source_locator, str) or not source_locator:
                        raise ValueError("source_block_locator_missing")
                    locator_hashes[block_id] = sha256_text(source_locator)
    return doc_ids, owners, locator_hashes, sha256_file(manifest)


def _emit(report: Mapping[str, Any], output: Path | None) -> None:
    if output is not None:
        write_json(output, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


def _validate_command(args: argparse.Namespace) -> int:
    dev_cases = read_jsonl(args.dev)
    heldout_cases = read_jsonl(args.heldout)
    if args.config is not None and args.minimum_per_task is not None:
        raise ValueError("--minimum-per-task is only allowed for synthetic validation without --config")
    config = _read_config(args.config)
    config_issues = validate_evaluation_config(config) if args.config is not None else []
    minimum_cases = config.get("minimum_cases") if isinstance(config.get("minimum_cases"), dict) else None
    if args.minimum_per_task is not None:
        minimum_cases = {
            split: {task: args.minimum_per_task for task in TASK_TYPES}
            for split in SPLITS
        }
    doc_ids, owners, locator_hashes, manifest_hash = _load_manifest_context(args.manifest, args.blocks_dir)
    report = validate_dataset(
        dev_cases,
        heldout_cases,
        minimum_cases=minimum_cases,
        known_doc_ids=doc_ids,
        block_owners=owners,
        block_locator_hashes=locator_hashes,
        manifest_sha256=manifest_hash,
    )
    if config_issues:
        report["errors"].extend(config_issues)
        report["passed"] = False
    _emit(report, args.output)
    return 0 if report["passed"] else 2


def _score_command(args: argparse.Namespace) -> int:
    cases = read_jsonl(args.cases)
    runs = read_jsonl(args.runs)
    config = _read_config(args.config)
    k_values = config.get("k_values", [1, 3, 5, 10])
    if not isinstance(k_values, list):
        raise ValueError("k_values must be a JSON array")
    report = score_runs(
        cases,
        runs,
        k_values=k_values,
        config=config,
        scoring_config_sha256=sha256_file(args.config) if args.config is not None else None,
    )
    _emit(report, args.output)
    return 0 if report["passed"] else 2


def _compare_command(args: argparse.Namespace) -> int:
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    if not isinstance(baseline, dict) or not isinstance(candidate, dict):
        raise ValueError("score reports must be JSON objects")
    report = compare_reports(baseline, candidate)
    _emit(report, args.output)
    return 0 if report["passed"] else 2


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="midprojectrag-eval")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate dev/heldout contracts and split isolation")
    validate.add_argument("--dev", type=Path, required=True)
    validate.add_argument("--held-out", dest="heldout", type=Path, required=True)
    validate.add_argument("--manifest", type=Path)
    validate.add_argument("--blocks-dir", type=Path)
    validate.add_argument("--config", type=Path)
    validate.add_argument("--minimum-per-task", type=_positive_int)
    validate.add_argument("--output", type=Path)
    validate.set_defaults(handler=_validate_command)

    score = subparsers.add_parser("score", help="score one stack without external calls")
    score.add_argument("--cases", type=Path, required=True)
    score.add_argument("--runs", type=Path, required=True)
    score.add_argument("--config", type=Path, required=True)
    score.add_argument("--output", type=Path)
    score.set_defaults(handler=_score_command)

    compare = subparsers.add_parser("compare", help="compare compatible aggregate score reports")
    compare.add_argument("--baseline", type=Path, required=True)
    compare.add_argument("--candidate", type=Path, required=True)
    compare.add_argument("--output", type=Path)
    compare.set_defaults(handler=_compare_command)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except json.JSONDecodeError:
        detail = "input is not valid JSON or JSONL"
    except FileNotFoundError:
        detail = "an input file does not exist"
    except PermissionError:
        detail = "an input or output path is not accessible"
    except OSError:
        detail = "an input or output operation failed"
    except ValueError as error:
        detail = str(error)
    print(
        json.dumps(
            {
                "schema_version": "1.0",
                "passed": False,
                "error": "invalid_evaluation_input",
                "detail": detail,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
