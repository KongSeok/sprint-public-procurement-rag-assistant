"""Provider-neutral Mini131 reporting taxonomy."""

from __future__ import annotations


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

PURPOSE_DEFINITIONS = {
    "bid_rag_scenarios": {
        "label": "입찰 RAG 핵심 시나리오",
        "meaning": "단일 문서·비교·후속 질문·안전한 기권",
        "failure": "핵심 질의 유형을 안정적으로 처리하지 못함",
    },
    "single_doc": {
        "label": "단일 문서",
        "meaning": "한 문서의 조건·사실을 근거로 답변",
        "failure": "문서 사실을 찾거나 인용하지 못함",
    },
    "multi_doc_compare": {
        "label": "복수 문서 비교",
        "meaning": "여러 공고의 조건을 비교",
        "failure": "비교 대상이나 기준을 누락함",
    },
    "follow_up": {
        "label": "후속 질문",
        "meaning": "대화 문맥을 이어 답변",
        "failure": "선행 문맥을 잃음",
    },
    "unknown": {
        "label": "근거 부족",
        "meaning": "근거가 없을 때 안전하게 기권",
        "failure": "근거 없는 답을 생성함",
    },
    "clause_fact_regression": {
        "label": "조항·사실 회귀",
        "meaning": "기존 세부 조항 질의 재현",
        "failure": "세부 사실을 오답 처리함",
    },
    "conditional_all_list": {
        "label": "조건부 전체 목록",
        "meaning": "조건을 만족하는 문서를 빠짐없이 선택",
        "failure": "누락 또는 과선택이 발생함",
    },
    "gold_source_alignment": {
        "label": "골드 근거 정렬",
        "meaning": "정답과 근거 문서를 함께 맞춤",
        "failure": "답변과 근거가 불일치함",
    },
    "visual_table_figure": {
        "label": "표·그림 근거",
        "meaning": "HWP/PDF의 표·그림 근거를 회수",
        "failure": "시각 객체 또는 목표 페이지를 놓침",
    },
    "corpus_analytics": {
        "label": "코퍼스 분석",
        "meaning": "결정론적 집계 근거로 답변",
        "failure": "계산값 또는 비교를 틀림",
    },
    "parser_regression": {
        "label": "파서 회귀",
        "meaning": "정본 HWP 추출·인덱싱 불변식",
        "failure": "파싱 또는 인덱싱 회귀가 발생함",
    },
}

VISUAL_SUBGROUP_DEFINITIONS = {
    "hwp_table": {
        "label": "HWP 표",
        "meaning": "HWP 표 근거 검색",
    },
    "hwp_figure": {
        "label": "HWP 그림",
        "meaning": "HWP 그림 근거 검색",
    },
    "pdf_table": {
        "label": "PDF 표",
        "meaning": "PDF 표 근거 검색",
    },
    "pdf_figure": {
        "label": "PDF 그림",
        "meaning": "PDF 그림 근거 검색",
    },
}
