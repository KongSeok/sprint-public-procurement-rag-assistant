"""Build the private, self-contained HTML review for the Mini 131 baseline.

The input and output contain golden questions, generated answers, evidence, and
judge rationales.  They therefore stay below ``evaluation/private`` and are
forced to mode ``0600``.  Standard output is deliberately content-free: a
successful invocation prints only the rendered case count and HTML SHA-256.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import stat
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from midprojectrag.ingest.common import (
    canonical_json,
    read_jsonl,
    sha256_file,
    sha256_text,
)


REPORT_SCHEMA_VERSION = "mini131-report.v1"
CASE_SCHEMA_VERSION = "mini131-case-record.v1"
EXPECTED_COUNTS = {
    "total": 131,
    "rag": 129,
    "parser": 2,
    "legacy_reconstructed": 39,
    "prospective_rerun": 90,
    "parser_local": 2,
}
RAG_LINEAGES = {"legacy_reconstructed", "prospective_rerun"}
ALL_LINEAGES = RAG_LINEAGES | {"parser_local"}
JUDGE_DECISIONS = {"accepted", "rejected", "needs_review", "needs_human"}
JUDGE_ROLES = {"primary", "secondary", "adjudicator"}
ROLE_DECISIONS = {
    "primary": {"accepted", "rejected", "needs_review"},
    "secondary": {"accepted", "rejected", "needs_review"},
    "adjudicator": {"accepted", "rejected", "needs_human"},
}
EXPECTED_BEHAVIORS = {"answer", "abstain", "source_conflict"}
RAG_STATUSES = {"answered", "abstained", "error"}
CASE_TYPES = {"rag", "parser"}
ALLOWED_COMPONENT_SCORES = {0, 0.5, 1}
ANSWER_SCORE_FIELDS = (
    "correctness",
    "faithfulness",
    "completeness",
    "factual_claim_coverage",
    "citation_validity",
)
ALL_SCORE_FIELDS = set(ANSWER_SCORE_FIELDS) | {"abstention_quality"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
JUDGMENT_FIELDS = {
    "schema_version",
    "judgment_id",
    "case_id",
    "case_sha256",
    "run_record_sha256",
    "judge_input_sha256",
    "review_config_sha256",
    "rubric_version",
    "reviewer_type",
    "model",
    "judge_role",
    "expected_behavior",
    "observed_status",
    "scores",
    "matched_key_point_ids",
    "follow_up_success",
    "safe_abstention",
    "critical_flags",
    "confidence",
    "judge_decision",
    "rationale",
    "reviewed_at",
}
JUDGMENT_WORKFLOW_FIELDS = {
    "secondary_required",
    "secondary_present",
    "adjudicator_required",
    "adjudicator_present",
    "primary_binary_recommendation",
    "secondary_unresolved",
    "disagreement",
    "critical_flag_mismatch",
    "final_judgment_id",
}
REQUIRED_CASE_FIELDS = {
    "schema_version",
    "case_id",
    "case_type",
    "lane",
    "question",
    "expected",
    "candidate",
    "retrieval",
    "judgment",
    "parser_result",
}
PRIVATE_HISTORY_FIELDS = (
    "source_transcript",
    "source_transcript_sha256",
    "judgment_history",
    "judgment_workflow",
)

# Shared presentation taxonomy for the API/local comparison report. These
# labels describe frozen categories; they do not assign scores or alter gold.
SCENARIO_PURPOSES = (
    "single_doc",
    "multi_doc_compare",
    "follow_up",
    "unknown",
)
PRIMARY_CATEGORY_ORDER = (
    "bid_rag_scenarios",
    "clause_fact_regression",
    "conditional_all_list",
    "gold_source_alignment",
    "visual_table_figure",
    "corpus_analytics",
    "parser_regression",
)
VISUAL_SUBGROUP_DEFINITIONS = {
    "hwp_table": {
        "label": "HWP 표",
        "meaning": "HWP 안의 행·열·병합셀 관계로 표현된 수치와 조건을 검색하고 답하는 문항입니다.",
    },
    "hwp_figure": {
        "label": "HWP 그림·도식",
        "meaning": "HWP 본문 텍스트가 아니라 삽입된 그림·도식에 있는 정보를 찾는 문항입니다.",
    },
    "pdf_table": {
        "label": "PDF 표",
        "meaning": "PDF에서 표의 행·열 구조와 셀 내용을 복원해 검색하고 답하는 문항입니다.",
    },
    "pdf_figure": {
        "label": "PDF 그림·도식",
        "meaning": "PDF 이미지·도식에만 있는 정보를 페이지와 원본 객체에 연결해 답하는 문항입니다.",
    },
}
PURPOSE_DEFINITIONS: dict[str, dict[str, str]] = {
    "bid_rag_scenarios": {
        "label": "입찰 RAG 질의응답 시나리오",
        "meaning": "실제 챗봇 업무를 단일 문서, 다중 문서, 후속 대화, 정보 없음 대응으로 나눠 종합적으로 확인합니다.",
        "failure": "낮으면 일반적인 입찰 상담 흐름에서 문서 선택, 비교, 문맥 유지 또는 안전한 기권 중 하나 이상이 불안정하다는 뜻입니다.",
    },
    "single_doc": {
        "label": "단일 문서 근거 답변",
        "meaning": "지정된 RFP 한 건에서 금액·기간·자격·요구사항 같은 정확한 사실을 찾아 근거와 함께 답하는 능력입니다.",
        "failure": "낮으면 맞는 문서를 보고도 필요한 조항을 놓치거나, 답은 맞지만 원문 페이지·근거를 제대로 연결하지 못할 수 있습니다.",
    },
    "multi_doc_compare": {
        "label": "다중 문서 비교·종합",
        "meaning": "두 건 이상의 RFP를 모두 찾아 동일한 기준으로 나누어 비교하고, 문서별 사실을 섞지 않는 능력입니다.",
        "failure": "낮으면 한 문서만 답하거나, 예산·기간·요구조건을 서로 뒤섞거나, 요청한 비교 축 일부를 빠뜨릴 수 있습니다.",
    },
    "follow_up": {
        "label": "후속 질문 문맥 유지",
        "meaning": "이전 사용자 질문과 이전 답변을 읽고 ‘그 사업’, ‘그 6개월’처럼 생략된 대상을 올바르게 이어서 답하는 능력입니다.",
        "failure": "낮으면 대화 주제를 다른 사업으로 바꾸거나, 앞서 확정한 조건을 잊거나, 대명사가 가리키는 대상을 잘못 해석할 수 있습니다.",
    },
    "unknown": {
        "label": "정보 없음·범위 밖 기권",
        "meaning": "원문에 없거나 실시간 조회·외부 행동이 필요한 질문에 사실을 지어내지 않고 ‘확인 불가’라고 안전하게 답하는 능력입니다.",
        "failure": "낮으면 낙찰업체·진행률·수주확률처럼 데이터에 없는 내용을 그럴듯하게 만들어 답할 위험이 있습니다.",
    },
    "clause_fact_regression": {
        "label": "문서 조항·사실 답변 회귀",
        "meaning": "이미 정답 근거가 확인된 금액·일정·자격·제출조건 같은 세부 사실을 스택 변경 후에도 계속 정확히 찾는지 검사합니다.",
        "failure": "낮으면 파서·청킹·검색·프롬프트를 바꾼 뒤 예전에 맞히던 조항을 놓치는 회귀가 많다는 뜻입니다.",
    },
    "conditional_all_list": {
        "label": "조건별 공고 전체 목록 검색",
        "meaning": "조건에 맞는 공고를 한두 건만 예시로 찾는 것이 아니라, 정답 문서 집합 전체를 빠짐없이 반환하는 능력입니다.",
        "failure": "낮으면 일부 공고만 찾거나 조건에 맞지 않는 공고를 섞습니다. 이 영역은 의미점수와 함께 Precision·Recall·F1·완전일치를 봐야 합니다.",
    },
    "gold_source_alignment": {
        "label": "정답·원문 일치 검수",
        "meaning": "후보 답변의 품질과 별개로, 골든 정답 자체가 실제 원문과 맞는지 교차 확인이 필요한 문항 묶음입니다.",
        "failure": "점수가 낮아도 모델 문제인지 골드 문제인지 바로 단정하면 안 됩니다. 사람 원문 검수 전까지 진단용 잠정 점수입니다.",
    },
    "visual_table_figure": {
        "label": "HWP/PDF 표·그림 검색·답변",
        "meaning": "일반 본문뿐 아니라 표의 행·열 관계와 그림·도식에만 있는 정보를 찾아 해당 페이지·객체에 연결하는 능력입니다.",
        "failure": "낮으면 페이지는 찾더라도 정답 표 청크나 그림 객체를 회수하지 못해 표 수치·도식 내용을 답하지 못할 수 있습니다.",
    },
    "corpus_analytics": {
        "label": "전체 말뭉치 통계·집계",
        "meaning": "Top-k 몇 건이 아니라 refined 전체 문서를 대상으로 평균·중앙값·분포·롱테일 같은 수치를 계산하고 설명하는 능력입니다.",
        "failure": "낮으면 일부 검색 결과만으로 전체 통계인 것처럼 답하거나, 분모·결측·0원·VAT 처리 규칙을 잘못 적용할 수 있습니다.",
    },
    "parser_regression": {
        "label": "문서 파싱 안정성 검사",
        "meaning": "두 특수 문서를 현재 rhwp 중심 전처리기가 정상 추출하고 인덱싱 가능한지 확인하는 로컬 ETL 회귀 테스트입니다.",
        "failure": "실패하면 질문 답변 이전 단계에서 원문이 검색 코퍼스에 들어오지 못합니다. LLM 의미점수에는 섞지 않습니다.",
    },
}


def _nonempty_string(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(code)
    return value


def _optional_string(value: Any, code: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError(code)
    return value


def _json_collection(value: Any, code: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(code)
    if any(not isinstance(item, (str, Mapping)) for item in value):
        raise ValueError(code)
    return value


def _score_from_judgment(judgment: Mapping[str, Any]) -> float | None:
    scores = judgment.get("scores")
    if not isinstance(scores, Mapping):
        return None
    abstention = scores.get("abstention_quality")
    if isinstance(abstention, (int, float)) and not isinstance(abstention, bool):
        derived = round(100.0 * float(abstention), 2)
    else:
        values = [scores.get(key) for key in ANSWER_SCORE_FIELDS]
        if not all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in values
        ):
            return None
        correctness, faithfulness, completeness, coverage, citations = map(float, values)
        derived = round(
            100.0
            * (
                0.35 * correctness
                + 0.25 * faithfulness
                + 0.20 * completeness
                + 0.10 * coverage
                + 0.10 * citations
            ),
            2,
        )
    return derived


def _valid_rfc3339(value: Any) -> bool:
    if not isinstance(value, str) or not RFC3339_RE.fullmatch(value):
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def _validate_judgment(
    value: Any,
    case_id: str,
    *,
    candidate_status: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("mini131_rag_judgment_invalid")
    if set(value) != JUDGMENT_FIELDS:
        raise ValueError("mini131_judgment_fields_invalid")
    if value.get("schema_version") != "1.0":
        raise ValueError("mini131_judgment_schema_invalid")
    for field in (
        "judgment_id",
        "case_sha256",
        "run_record_sha256",
        "judge_input_sha256",
        "review_config_sha256",
    ):
        if not isinstance(value.get(field), str) or not SHA256_RE.fullmatch(value[field]):
            raise ValueError(f"mini131_judgment_{field}_invalid")
    if value.get("model") != "gpt-5.6-sol":
        raise ValueError("mini131_judge_model_mismatch")
    if value.get("rubric_version") != "gpt56-semantic-v2":
        raise ValueError("mini131_judge_rubric_mismatch")
    if value.get("reviewer_type") != "llm":
        raise ValueError("mini131_judge_reviewer_type_mismatch")
    role = value.get("judge_role")
    if role not in JUDGE_ROLES:
        raise ValueError("mini131_judge_role_invalid")
    if value.get("judge_decision") not in ROLE_DECISIONS[str(role)]:
        raise ValueError("mini131_judge_decision_invalid")
    expected_behavior = value.get("expected_behavior")
    if expected_behavior not in EXPECTED_BEHAVIORS:
        raise ValueError("mini131_judge_expected_behavior_invalid")
    if value.get("observed_status") != candidate_status:
        raise ValueError("mini131_judge_observed_status_mismatch")
    scores = value.get("scores")
    if not isinstance(scores, Mapping):
        raise ValueError("mini131_judge_scores_invalid")
    if not ALL_SCORE_FIELDS.issubset(scores):
        raise ValueError("mini131_judge_score_fields_missing")
    abstention_quality = scores.get("abstention_quality")
    if abstention_quality is not None and (
        isinstance(abstention_quality, bool) or abstention_quality not in ALLOWED_COMPONENT_SCORES
    ):
        raise ValueError("mini131_abstention_quality_invalid")
    for field in ANSWER_SCORE_FIELDS:
        component = scores.get(field)
        if component is not None and (
            isinstance(component, bool) or component not in ALLOWED_COMPONENT_SCORES
        ):
            raise ValueError("mini131_answer_component_invalid")
    if expected_behavior == "abstain":
        if abstention_quality is None or any(
            scores.get(field) is not None for field in ANSWER_SCORE_FIELDS
        ):
            raise ValueError("mini131_abstention_score_mode_required")
    else:
        if abstention_quality is not None or any(
            scores.get(field) is None for field in ANSWER_SCORE_FIELDS
        ):
            raise ValueError("mini131_answer_score_mode_required")
    critical_flags = value.get("critical_flags")
    if not isinstance(critical_flags, list) or any(
        not isinstance(flag, str) or not flag.strip() for flag in critical_flags
    ):
        raise ValueError("mini131_critical_flags_invalid")
    matched_key_point_ids = value.get("matched_key_point_ids")
    if (
        not isinstance(matched_key_point_ids, list)
        or any(not isinstance(item, str) or not item for item in matched_key_point_ids)
        or len(matched_key_point_ids) != len(set(matched_key_point_ids))
    ):
        raise ValueError("mini131_matched_key_point_ids_invalid")
    for field in ("follow_up_success", "safe_abstention"):
        if value.get(field) is not None and not isinstance(value.get(field), bool):
            raise ValueError(f"mini131_{field}_invalid")
        if field not in value:
            raise ValueError(f"mini131_{field}_missing")
    _nonempty_string(value.get("rationale"), "mini131_judge_rationale_invalid")
    confidence = value.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise ValueError("mini131_judge_confidence_invalid")
    semantic_score = _score_from_judgment(value)
    if semantic_score is None:
        raise ValueError("mini131_judge_semantic_score_unavailable")
    decision = value["judge_decision"]
    safe_abstention = value.get("safe_abstention")
    if not _valid_rfc3339(value.get("reviewed_at")):
        raise ValueError("mini131_judgment_reviewed_at_invalid")
    if expected_behavior == "abstain":
        hard_rejection = candidate_status != "abstained" or safe_abstention is not True
    else:
        if safe_abstention is not None:
            raise ValueError("mini131_safe_abstention_scope_invalid")
        # An answerable/source-conflict case that abstained (or errored) is a
        # false abstention even when its component scores are otherwise high.
        hard_rejection = candidate_status != "answered"
    hard_rejection = hard_rejection or candidate_status == "error" or bool(critical_flags)
    if role == "adjudicator":
        final_accept = (
            not hard_rejection
            and semantic_score > 85
            and confidence >= 0.70
        )
        allowed_decisions = (
            {"accepted", "needs_human"}
            if final_accept
            else {"rejected", "needs_human"}
        )
    elif hard_rejection or semantic_score < 60:
        allowed_decisions = {"rejected"}
    elif semantic_score <= 85 or confidence < 0.70:
        allowed_decisions = {"needs_review"}
    else:
        allowed_decisions = {"accepted"}
    if decision not in allowed_decisions:
        raise ValueError("mini131_judge_decision_inconsistent")
    if value.get("case_id") not in (None, case_id):
        raise ValueError("mini131_judgment_case_mismatch")
    return value


def _validate_judgment_history(
    value: Any,
    *,
    final_judgment: Mapping[str, Any],
    workflow: Any,
    case_id: str,
    candidate_status: str,
) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("mini131_judgment_history_invalid")
    checked = [
        _validate_judgment(
            row,
            case_id,
            candidate_status=candidate_status,
        )
        for row in value
    ]
    roles = [str(row["judge_role"]) for row in checked]
    if len(roles) != len(set(roles)):
        raise ValueError("mini131_judgment_history_order_invalid")
    reviewed = [
        datetime.fromisoformat(str(row["reviewed_at"]).replace("Z", "+00:00"))
        for row in checked
    ]
    if reviewed != sorted(reviewed):
        raise ValueError("mini131_judgment_history_order_invalid")
    if dict(checked[-1]) != dict(final_judgment):
        raise ValueError("mini131_final_judgment_history_mismatch")

    if not isinstance(workflow, Mapping) or set(workflow) != JUDGMENT_WORKFLOW_FIELDS:
        raise ValueError("mini131_judgment_workflow_invalid")
    for field in (
        "secondary_required",
        "secondary_present",
        "adjudicator_required",
        "adjudicator_present",
        "secondary_unresolved",
        "disagreement",
        "critical_flag_mismatch",
    ):
        if not isinstance(workflow.get(field), bool):
            raise ValueError("mini131_judgment_workflow_invalid")
    if workflow.get("primary_binary_recommendation") not in {
        "accepted",
        "rejected",
    }:
        raise ValueError("mini131_judgment_workflow_invalid")
    if workflow.get("final_judgment_id") != final_judgment.get("judgment_id"):
        raise ValueError("mini131_judgment_workflow_history_mismatch")
    return checked


def _validate_record(value: Any, index: int) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("mini131_case_not_object")
    if not REQUIRED_CASE_FIELDS.issubset(value):
        raise ValueError("mini131_case_fields_missing")
    if value.get("schema_version") != CASE_SCHEMA_VERSION:
        raise ValueError("mini131_case_schema_mismatch")
    case_id = _nonempty_string(value.get("case_id"), "mini131_case_id_invalid")
    case_type = value.get("case_type")
    if case_type not in CASE_TYPES:
        raise ValueError("mini131_case_type_invalid")
    _nonempty_string(value.get("lane"), "mini131_lane_invalid")
    _nonempty_string(value.get("question"), "mini131_question_invalid")
    if value.get("expected") is None:
        raise ValueError("mini131_expected_missing")

    candidate = value.get("candidate")
    retrieval = value.get("retrieval")
    if not isinstance(candidate, Mapping):
        raise ValueError("mini131_candidate_invalid")
    if not isinstance(retrieval, Mapping):
        raise ValueError("mini131_retrieval_invalid")
    lineage = candidate.get("lineage")
    if lineage not in ALL_LINEAGES:
        raise ValueError("mini131_lineage_invalid")
    _nonempty_string(candidate.get("status"), "mini131_candidate_status_invalid")
    _optional_string(candidate.get("answer"), "mini131_candidate_answer_invalid")
    _json_collection(candidate.get("chat"), "mini131_candidate_chat_invalid")
    _json_collection(retrieval.get("retrieved_docs"), "mini131_retrieved_docs_invalid")
    _json_collection(retrieval.get("cited_docs"), "mini131_cited_docs_invalid")
    _json_collection(retrieval.get("evidence"), "mini131_evidence_invalid")
    private_history_presence = [field in value for field in PRIVATE_HISTORY_FIELDS]
    if any(private_history_presence) and not all(private_history_presence):
        raise ValueError("mini131_private_history_fields_incomplete")
    has_private_history = all(private_history_presence)

    if case_type == "rag":
        if lineage not in RAG_LINEAGES:
            raise ValueError("mini131_rag_lineage_invalid")
        if candidate.get("status") not in RAG_STATUSES:
            raise ValueError("mini131_rag_status_invalid")
        if candidate.get("status") == "answered" and not candidate.get("answer"):
            raise ValueError("mini131_answered_without_answer")
        final_judgment = _validate_judgment(
            value.get("judgment"),
            case_id,
            candidate_status=str(candidate.get("status")),
        )
        if has_private_history:
            source_transcript = value.get("source_transcript")
            source_transcript_sha256 = value.get("source_transcript_sha256")
            if not isinstance(source_transcript, Mapping):
                raise ValueError("mini131_source_transcript_invalid")
            if source_transcript.get("case_id") != case_id:
                raise ValueError("mini131_source_transcript_case_mismatch")
            if (
                not isinstance(source_transcript_sha256, str)
                or not SHA256_RE.fullmatch(source_transcript_sha256)
                or source_transcript_sha256
                != sha256_text(canonical_json(source_transcript))
            ):
                raise ValueError("mini131_source_transcript_hash_mismatch")
            _validate_judgment_history(
                value.get("judgment_history"),
                final_judgment=final_judgment,
                workflow=value.get("judgment_workflow"),
                case_id=case_id,
                candidate_status=str(candidate.get("status")),
            )
        if value.get("parser_result") is not None:
            raise ValueError("mini131_rag_parser_result_forbidden")
    else:
        if lineage != "parser_local":
            raise ValueError("mini131_parser_lineage_invalid")
        if value.get("judgment") is not None:
            raise ValueError("mini131_parser_judgment_forbidden")
        if has_private_history and (
            value.get("source_transcript") is not None
            or value.get("source_transcript_sha256") is not None
            or value.get("judgment_history") != []
            or value.get("judgment_workflow") is not None
        ):
            raise ValueError("mini131_parser_private_history_forbidden")
        parser_result = value.get("parser_result")
        if not isinstance(parser_result, Mapping) or not isinstance(parser_result.get("passed"), bool):
            raise ValueError("mini131_parser_result_invalid")
    # Copy to detach rendering from unusual Mapping implementations.
    return dict(value)


def validate_records(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    records = [_validate_record(value, index) for index, value in enumerate(values)]
    case_ids = [record["case_id"] for record in records]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("mini131_duplicate_case_id")
    type_counts = Counter(record["case_type"] for record in records)
    lineage_counts = Counter(record["candidate"]["lineage"] for record in records)
    actual = {
        "total": len(records),
        "rag": type_counts["rag"],
        "parser": type_counts["parser"],
        "legacy_reconstructed": lineage_counts["legacy_reconstructed"],
        "prospective_rerun": lineage_counts["prospective_rerun"],
        "parser_local": lineage_counts["parser_local"],
    }
    if actual != EXPECTED_COUNTS:
        raise ValueError("mini131_case_ledger_mismatch")
    return sorted(records, key=lambda record: (record["lane"], record["case_id"]))


def _json_pre(value: Any) -> str:
    return html.escape(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _text_pre(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _doc_label(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        for key in ("title", "document_title", "doc_id", "source"):
            if value.get(key):
                return str(value[key])
    return "document"


def _evidence_cards(evidence: Sequence[Any]) -> str:
    if not evidence:
        return '<p class="muted">저장된 evidence 없음</p>'
    cards: list[str] = []
    for number, item in enumerate(evidence, start=1):
        label = _doc_label(item)
        cards.append(
            '<details class="nested"><summary>'
            f'Evidence {number}: {html.escape(label)}</summary><pre>{_json_pre(item)}</pre></details>'
        )
    return "".join(cards)


def _chat_cards(chat: Sequence[Any]) -> str:
    if not chat:
        return '<p class="muted">저장된 chat 메시지 없음</p>'
    cards: list[str] = []
    for number, message in enumerate(chat, start=1):
        role = message.get("role", "message") if isinstance(message, Mapping) else "message"
        cards.append(
            '<details class="nested"><summary>'
            f'{number}. {html.escape(str(role))}</summary><pre>{_json_pre(message)}</pre></details>'
        )
    return "".join(cards)


def _judgment_history_cards(history: Sequence[Any]) -> str:
    if not history:
        return '<p class="muted">LLM judgment history not applicable.</p>'
    cards: list[str] = []
    for number, judgment in enumerate(history, start=1):
        role = (
            str(judgment.get("judge_role", "judge"))
            if isinstance(judgment, Mapping)
            else "judge"
        )
        decision = (
            str(judgment.get("judge_decision", "decision"))
            if isinstance(judgment, Mapping)
            else "decision"
        )
        cards.append(
            '<details class="nested"><summary>'
            f'{number}. {html.escape(role)} · {html.escape(decision)}'
            f'</summary><pre>{_json_pre(judgment)}</pre></details>'
        )
    return "".join(cards)


def _row_view(record: Mapping[str, Any]) -> dict[str, Any]:
    candidate = record["candidate"]
    judgment = record["judgment"]
    parser_result = record["parser_result"]
    if record["case_type"] == "rag":
        decision = str(judgment["judge_decision"])
        score = _score_from_judgment(judgment)
        failed = decision in {"rejected", "needs_review", "needs_human"} or candidate["status"] == "error"
    else:
        decision = "parser_passed" if parser_result["passed"] else "parser_failed"
        score = None
        failed = not parser_result["passed"]
    return {
        "record": record,
        "decision": decision,
        "score": score,
        "failed": failed,
    }


def _summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rag_rows = [row for row in rows if row["record"]["case_type"] == "rag"]
    parser_rows = [row for row in rows if row["record"]["case_type"] == "parser"]
    scores = [float(row["score"]) for row in rag_rows if row["score"] is not None]
    decisions = Counter(row["decision"] for row in rows)
    candidate_statuses = Counter(row["record"]["candidate"]["status"] for row in rows)
    return {
        "total": len(rows),
        "rag": len(rag_rows),
        "parser": len(parser_rows),
        "mean_semantic_score": round(sum(scores) / len(scores), 2) if scores else None,
        "judged": len(scores),
        "accepted": decisions["accepted"],
        "rejected": decisions["rejected"],
        "needs_review": decisions["needs_review"],
        "needs_human": decisions["needs_human"],
        "parser_passed": decisions["parser_passed"],
        "parser_failed": decisions["parser_failed"],
        "candidate_statuses": dict(sorted(candidate_statuses.items())),
    }


def _lane_summaries(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["record"]["lane"])].append(row)
    summaries: list[dict[str, Any]] = []
    for lane, items in sorted(grouped.items()):
        rag_scores = [float(item["score"]) for item in items if item["score"] is not None]
        decisions = Counter(item["decision"] for item in items)
        summaries.append(
            {
                "lane": lane,
                "total": len(items),
                "mean": round(sum(rag_scores) / len(rag_scores), 2) if rag_scores else None,
                "accepted": decisions["accepted"],
                "rejected": decisions["rejected"],
                "needs_review": decisions["needs_review"],
                "needs_human": decisions["needs_human"],
                "parser_passed": decisions["parser_passed"],
                "parser_failed": decisions["parser_failed"],
            }
        )
    return summaries


def _metric(value: Any) -> str:
    return "—" if value is None else html.escape(str(value))


def render_html(
    records: Sequence[Mapping[str, Any]],
    *,
    source_sha256: str,
    public_aggregate: Mapping[str, Any] | None = None,
) -> str:
    normalized = validate_records(records)
    rows = [_row_view(record) for record in normalized]
    summary = _summary(rows)
    lanes = _lane_summaries(rows)
    lane_options = "".join(
        f'<option value="{html.escape(item["lane"], quote=True)}">{html.escape(item["lane"])}</option>'
        for item in lanes
    )
    lane_table = "".join(
        "<tr>"
        f'<th scope="row">{html.escape(item["lane"])}</th>'
        f'<td>{item["total"]}</td><td>{_metric(item["mean"])}</td>'
        f'<td>{item["accepted"]}</td><td>{item["rejected"]}</td>'
        f'<td>{item["needs_review"] + item["needs_human"]}</td>'
        f'<td>{item["parser_passed"]}/{item["parser_failed"]}</td>'
        "</tr>"
        for item in lanes
    )
    cards: list[str] = []
    for row in rows:
        record = row["record"]
        candidate = record["candidate"]
        retrieval = record["retrieval"]
        judgment = record["judgment"]
        source_transcript = record.get("source_transcript")
        judgment_history = record.get("judgment_history", [])
        judgment_workflow = record.get("judgment_workflow")
        decision = row["decision"]
        score = row["score"]
        case_id = html.escape(str(record["case_id"]), quote=True)
        lane = html.escape(str(record["lane"]), quote=True)
        case_type = html.escape(str(record["case_type"]), quote=True)
        lineage = html.escape(str(candidate["lineage"]), quote=True)
        status = html.escape(str(candidate["status"]), quote=True)
        verdict = html.escape(decision, quote=True)
        score_text = "—" if score is None else f"{score:.2f}"
        judgment_html = (
            '<section><h3>Sol v2 judgment</h3>'
            f'<p class="rationale">{_text_pre(judgment["rationale"])}</p>'
            f'<pre>{_json_pre(judgment)}</pre></section>'
            if judgment is not None
            else '<section><h3>Parser deterministic result</h3>'
            f'<pre>{_json_pre(record["parser_result"])}</pre></section>'
        )
        source_transcript_html = (
            '<details class="group"><summary>Full source execution transcript '
            f'· SHA-256 {html.escape(str(record.get("source_transcript_sha256")))}'
            f'</summary><pre>{_json_pre(source_transcript)}</pre></details>'
            if source_transcript is not None
            else '<p class="muted">Parser-local case: source execution transcript not applicable.</p>'
        )
        judgment_history_html = (
            '<details class="group"><summary>Sol judgment history '
            f'({len(judgment_history)})</summary>'
            f'{_judgment_history_cards(judgment_history)}</details>'
            '<details class="group"><summary>Judgment workflow</summary>'
            f'<pre>{_json_pre(judgment_workflow)}</pre></details>'
            if judgment_history
            else '<p class="muted">Parser-local case: LLM judgment history not applicable.</p>'
        )
        cards.append(
            f'''<details class="case" data-lane="{lane}" data-type="{case_type}" data-lineage="{lineage}" data-status="{status}" data-verdict="{verdict}" data-failure="{int(row["failed"])}">
<summary><code>{case_id}</code><span class="badge">{lane}</span><span class="badge">{case_type}</span><span class="badge">{lineage}</span><span class="badge status">{status}</span><strong class="verdict">{verdict}</strong><span class="score">{score_text}</span></summary>
<div class="detail-grid">
<section><h3>Question</h3><pre>{_text_pre(record["question"])}</pre></section>
<section><h3>Expected / reference</h3><pre>{_json_pre(record["expected"])}</pre></section>
</div>
<section><h3>Candidate answer</h3><pre>{_text_pre(candidate["answer"])}</pre></section>
<details class="group"><summary>Conversation summary ({len(candidate["chat"])})</summary>{_chat_cards(candidate["chat"])}</details>
{source_transcript_html}
<details class="group"><summary>Retrieved / cited documents</summary><h3>Retrieved</h3><pre>{_json_pre(retrieval["retrieved_docs"])}</pre><h3>Cited</h3><pre>{_json_pre(retrieval["cited_docs"])}</pre></details>
<details class="group"><summary>Evidence ({len(retrieval["evidence"])})</summary>{_evidence_cards(retrieval["evidence"])}</details>
{judgment_history_html}
{judgment_html}
</details>'''
        )
    aggregate_html = (
        f'<details class="aggregate"><summary>Public aggregate receipt</summary><pre>{_json_pre(public_aggregate)}</pre></details>'
        if public_aggregate is not None
        else '<p class="muted">Public aggregate receipt not supplied.</p>'
    )
    return f'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><title>gpt-5-mini 131 baseline · Sol v2 review</title>
<style>
:root{{font-family:Inter,ui-sans-serif,system-ui,sans-serif;line-height:1.5;color-scheme:light dark}}body{{max-width:1320px;margin:auto;padding:24px}}h1{{margin-bottom:4px}}.sub{{margin-top:0;color:GrayText}}.notice{{border:1px solid #c98b17;background:color-mix(in srgb,#eaa416 10%,Canvas);padding:14px;border-radius:10px}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:10px;margin:18px 0}}.metric{{border:1px solid GrayText;border-radius:10px;padding:12px}}.metric strong{{display:block;font-size:1.5rem;font-variant-numeric:tabular-nums}}table{{border-collapse:collapse;width:100%;margin:16px 0}}th,td{{border-bottom:1px solid GrayText;text-align:right;padding:7px}}th:first-child,td:first-child{{text-align:left}}.controls{{display:flex;gap:8px;flex-wrap:wrap;align-items:center;position:sticky;top:0;z-index:4;padding:12px;margin:18px 0;background:Canvas;border:1px solid GrayText;border-radius:10px}}input,select{{font:inherit;padding:7px}}input[type=search]{{min-width:260px;flex:1}}details.case{{border:1px solid GrayText;border-radius:10px;margin:10px 0;padding:10px}}summary{{cursor:pointer}}details.case>summary{{display:flex;gap:7px;align-items:center;flex-wrap:wrap}}.badge{{border:1px solid GrayText;border-radius:999px;padding:2px 7px;font-size:.8rem}}.verdict{{margin-left:auto}}.score{{font-variant-numeric:tabular-nums;font-weight:700}}.detail-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}}section,.group,.aggregate{{margin:13px 0}}h3{{font-size:1rem;margin-bottom:5px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:color-mix(in srgb,CanvasText 7%,Canvas);padding:10px;border-radius:7px}}.nested{{margin:7px 0 7px 10px;border-left:3px solid color-mix(in srgb,CanvasText 18%,Canvas);padding-left:9px}}.rationale{{padding:10px;border-left:4px solid #4f7ddc}}.muted{{color:GrayText}}.hidden{{display:none}}#count{{font-variant-numeric:tabular-nums}}@media(max-width:650px){{body{{padding:12px}}.verdict{{margin-left:0}}input[type=search]{{min-width:100%}}}}
</style></head><body>
<h1>gpt-5-mini 131 baseline</h1><p class="sub">Fixed semantic judge: gpt-5.6-sol · rubric gpt56-semantic-v2 · source <code>{html.escape(source_sha256)}</code></p>
<aside class="notice"><strong>Lineage caveat</strong><br>RAG 129건 중 39건은 기존 Mini 후보 답변을 재사용한 <code>legacy_reconstructed</code>이며 원본 transcript가 명시한 범위까지만 사후 복원된 기록입니다. 90건은 provider request/response, retrieval evidence, prompt와 최종 응답을 포함한 정확한 실행 transcript를 남긴 <code>prospective_rerun</code>입니다. 모든 transcript는 case-record의 SHA-256으로 검증되며, primary/secondary/adjudicator 전체 판정 이력도 함께 표시됩니다. 나머지 2건은 LLM 채점 대상이 아닌 로컬 결정론적 parser 회귀(<code>parser_local</code>)입니다.</aside>
<div class="metrics"><div class="metric">전체<strong>{summary["total"]}</strong></div><div class="metric">RAG / parser<strong>{summary["rag"]} / {summary["parser"]}</strong></div><div class="metric">평균 의미점수<strong>{_metric(summary["mean_semantic_score"])}</strong></div><div class="metric">accepted<strong>{summary["accepted"]}</strong></div><div class="metric">rejected<strong>{summary["rejected"]}</strong></div><div class="metric">review/human<strong>{summary["needs_review"] + summary["needs_human"]}</strong></div><div class="metric">parser pass/fail<strong>{summary["parser_passed"]}/{summary["parser_failed"]}</strong></div></div>
<h2>Lane summary</h2><table><thead><tr><th>Lane</th><th>Cases</th><th>Mean</th><th>Accepted</th><th>Rejected</th><th>Review</th><th>Parser P/F</th></tr></thead><tbody>{lane_table}</tbody></table>
{aggregate_html}
<div class="controls"><input id="search" type="search" placeholder="case ID, 질문, 답변, 문서, evidence 검색" aria-label="검색"><select id="lane" aria-label="lane"><option value="">모든 lane</option>{lane_options}</select><select id="type" aria-label="case type"><option value="">모든 유형</option><option value="rag">rag</option><option value="parser">parser</option></select><select id="lineage" aria-label="lineage"><option value="">모든 lineage</option><option value="legacy_reconstructed">legacy reconstructed</option><option value="prospective_rerun">prospective rerun</option><option value="parser_local">parser local</option></select><select id="verdict" aria-label="verdict"><option value="">모든 판정</option><option value="accepted">accepted</option><option value="rejected">rejected</option><option value="needs_review">needs review</option><option value="needs_human">needs human</option><option value="parser_passed">parser passed</option><option value="parser_failed">parser failed</option></select><label><input id="failures" type="checkbox"> 실패/검토만</label><strong id="count">131 / 131</strong></div>
<main>{''.join(cards)}</main>
<script>
const cases=[...document.querySelectorAll('.case')];const q=document.querySelector('#search'),lane=document.querySelector('#lane'),type=document.querySelector('#type'),lineage=document.querySelector('#lineage'),verdict=document.querySelector('#verdict'),failures=document.querySelector('#failures'),count=document.querySelector('#count');function filter(){{const needle=q.value.toLocaleLowerCase();let visible=0;for(const el of cases){{const show=(!needle||el.textContent.toLocaleLowerCase().includes(needle))&&(!lane.value||el.dataset.lane===lane.value)&&(!type.value||el.dataset.type===type.value)&&(!lineage.value||el.dataset.lineage===lineage.value)&&(!verdict.value||el.dataset.verdict===verdict.value)&&(!failures.checked||el.dataset.failure==='1');el.classList.toggle('hidden',!show);visible+=Number(show)}}count.textContent=`${{visible}} / ${{cases.length}}`}}for(const el of [q,lane,type,lineage,verdict,failures])el.addEventListener('input',filter);
</script></body></html>'''


def _protect_private_input(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("mini131_private_input_symlink_forbidden")
    os.chmod(path, 0o600)
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ValueError("mini131_private_input_mode_invalid")


def _validated_private_html_output(path: Path) -> Path:
    """Return an absolute output path contained by a real ``evaluation/private``.

    The lexical boundary prevents a similarly named directory from being
    accepted, while resolved-path containment and explicit symlink checks keep
    an existing descendant link from redirecting the private report elsewhere.
    """

    absolute = path.expanduser().absolute()
    if absolute.suffix.lower() != ".html":
        raise ValueError("mini131_private_output_not_html")
    parts = absolute.parts
    boundary_index = next(
        (
            index
            for index in range(len(parts) - 1, 0, -1)
            if parts[index - 1 : index + 1] == ("evaluation", "private")
        ),
        None,
    )
    if boundary_index is None:
        raise ValueError("mini131_private_output_outside_evaluation_private")
    private_root = Path(*parts[: boundary_index + 1])
    if absolute == private_root:
        raise ValueError("mini131_private_output_invalid")

    evaluation_root = private_root.parent
    cursor = evaluation_root
    for component in absolute.relative_to(evaluation_root).parts[:-1]:
        cursor /= component
        if cursor.exists() and cursor.is_symlink():
            raise ValueError("mini131_private_output_symlink_forbidden")

    resolved_root = private_root.resolve(strict=False)
    resolved_output = absolute.resolve(strict=False)
    try:
        resolved_output.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError("mini131_private_output_outside_evaluation_private") from error
    return absolute


def _atomic_private_write(path: Path, content: str) -> None:
    path = _validated_private_html_output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("mini131_private_output_symlink_forbidden")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ValueError("mini131_private_output_mode_invalid")


def _validate_public_aggregate(
    value: Any,
    *,
    case_records_sha256: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("mini131_public_aggregate_invalid")
    if (
        value.get("baseline_id") != "mini131-bundle-v1"
        or value.get("stage") != "case_records_ready"
        or value.get("passed") is not True
    ):
        raise ValueError("mini131_public_aggregate_invalid")
    counts = value.get("counts")
    if not isinstance(counts, Mapping) or any(
        counts.get(field) != expected
        for field, expected in {
            "rag": 129,
            "parser": 2,
            "total": 131,
            "full_source_transcripts": 129,
        }.items()
    ):
        raise ValueError("mini131_public_aggregate_counts_mismatch")
    artifacts = value.get("artifact_sha256s")
    if (
        not isinstance(artifacts, Mapping)
        or artifacts.get("case_records") != case_records_sha256
    ):
        raise ValueError("mini131_public_aggregate_case_records_mismatch")
    privacy = value.get("privacy")
    expected_privacy_fields = {
        "contains_case_ids",
        "contains_questions",
        "contains_answers",
        "contains_gold",
        "contains_source_text",
        "contains_provider_payloads",
        "private_artifacts_tracked",
    }
    if (
        not isinstance(privacy, Mapping)
        or set(privacy) != expected_privacy_fields
        or any(item is not False for item in privacy.values())
    ):
        raise ValueError("mini131_public_aggregate_privacy_invalid")
    semantic_judge = value.get("semantic_judge")
    if (
        not isinstance(semantic_judge, Mapping)
        or semantic_judge.get("status") != "complete"
        or semantic_judge.get("history_validated") is not True
        or semantic_judge.get("trigger_resolution_complete") is not True
    ):
        raise ValueError("mini131_public_aggregate_judge_incomplete")
    return value


def generate_report(
    *,
    case_records_path: Path,
    output_path: Path,
    public_aggregate_path: Path | None = None,
) -> dict[str, Any]:
    output_path = _validated_private_html_output(output_path)
    _protect_private_input(case_records_path)
    records = read_jsonl(case_records_path)
    checked_records = validate_records(records)
    source_sha256 = sha256_file(case_records_path)
    public_aggregate: Mapping[str, Any] | None = None
    if public_aggregate_path is not None:
        loaded = json.loads(public_aggregate_path.read_text(encoding="utf-8"))
        public_aggregate = _validate_public_aggregate(
            loaded,
            case_records_sha256=source_sha256,
        )
        full_source_transcripts = sum(
            record["case_type"] == "rag"
            and all(field in record for field in PRIVATE_HISTORY_FIELDS)
            for record in checked_records
        )
        if full_source_transcripts != 129:
            raise ValueError("mini131_full_source_transcripts_incomplete")
    rendered = render_html(
        checked_records,
        source_sha256=source_sha256,
        public_aggregate=public_aggregate,
    )
    _atomic_private_write(output_path, rendered)
    return {"count": len(records), "sha256": sha256_file(output_path)}


def build_parser() -> argparse.ArgumentParser:
    run_root = Path("evaluation/private/supplemental/runs/provisional-v1")
    parser = argparse.ArgumentParser(description="Build the private Mini 131 baseline HTML")
    parser.add_argument("--case-records", type=Path, default=run_root / "case-records.jsonl")
    parser.add_argument("--public-aggregate", type=Path)
    parser.add_argument("--output", type=Path, default=run_root / "gpt56-baseline-score.html")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt = generate_report(
            case_records_path=args.case_records,
            output_path=args.output,
            public_aggregate_path=args.public_aggregate,
        )
        print(canonical_json(receipt))
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        code = str(error)
        if re.fullmatch(r"[a-z][a-z0-9_]{0,127}", code) is None:
            code = "mini131_report_failed"
        print(code, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
