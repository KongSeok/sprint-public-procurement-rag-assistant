"""Streamlit 시연용 복합 메타데이터 질문 처리.

팀 공용 생성 모듈을 수정하지 않고, 기간과 예산처럼 명시적인 조건이 함께
주어진 질문만 결정적으로 필터링한다. 조건을 완전히 해석하지 못하면 ``None``을
반환하여 기존 RAG 생성 경로가 처리하게 한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable


_AMOUNT_UNITS = {
    "억": 100_000_000,
    "천만": 10_000_000,
    "백만": 1_000_000,
    "만": 10_000,
    "원": 1,
}


@dataclass(frozen=True)
class CompoundAnswer:
    answer: str
    doc_ids: tuple[str, ...]
    applied_conditions: str


def _amount_bound(question: str) -> tuple[str, int] | None:
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(억|천만|백만|만|원)\s*(미만|이하|이상|초과)",
        question,
    )
    if not match:
        return None
    amount = int(float(match.group(1)) * _AMOUNT_UNITS[match.group(2)])
    return match.group(3), amount


def _period_bound(question: str) -> int | None:
    match = re.search(r"(\d+)\s*(개월|일)\s*(?:이내|미만|이하)", question)
    if match:
        value = int(match.group(1))
        return value * 30 if match.group(2) == "개월" else value
    if "짧은 사업" in question:
        return 90
    return None


def _number(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    cleaned = re.sub(r"[^0-9.]", "", str(value))
    if not cleaned:
        return None
    try:
        return int(float(cleaned))
    except ValueError:
        return None


def _budget(metadata: dict[str, Any]) -> int | None:
    for key in ("사업_금액", "사업 금액", "사업_금액_정제", "사업금액"):
        amount = _number(metadata.get(key))
        if amount is not None:
            return amount
    return None


def _period_days(doc_id: str, chunks: Iterable[Any]) -> int | None:
    pattern = re.compile(
        r"(?:사업|용역|과업)\s*기간[^.\n]{0,40}"
        r"(?:계약체결일|계약일|착수일)[^.\n]{0,15}(?:로부터|~)\s*(\d+)\s*(일|개월)"
    )
    for chunk in chunks:
        if str(getattr(chunk, "doc_id", "")) != doc_id:
            continue
        match = pattern.search(str(getattr(chunk, "text", "")))
        if not match or int(match.group(1)) == 0:
            continue
        value = int(match.group(1))
        return value * 30 if match.group(2) == "개월" else value
    return None


def _passes_budget(amount: int, operator: str, bound: int) -> bool:
    return {
        "미만": amount < bound,
        "이하": amount <= bound,
        "이상": amount >= bound,
        "초과": amount > bound,
    }[operator]


def answer_period_budget_query(
    question: str,
    catalog: Iterable[tuple[str, str]],
    doc_metadata: dict[str, dict[str, Any]],
    chunks: Iterable[Any],
) -> CompoundAnswer | None:
    """기간+예산 조건을 모두 명시한 목록 질문만 처리한다."""
    period_limit = _period_bound(question)
    amount_bound = _amount_bound(question)
    if period_limit is None or amount_bound is None:
        return None

    operator, budget_limit = amount_bound
    matched: list[tuple[str, int, int]] = []
    unknown_budget = 0
    for doc_id, _business_name in catalog:
        days = _period_days(doc_id, chunks)
        if days is None or days > period_limit:
            continue
        amount = _budget(doc_metadata.get(doc_id, {}))
        if amount is None:
            unknown_budget += 1
            continue
        if _passes_budget(amount, operator, budget_limit):
            matched.append((doc_id, days, amount))

    matched.sort(key=lambda item: (item[1], item[2], item[0]))
    condition = f"기간 {period_limit}일 이내 · 예산 {budget_limit:,}원 {operator}"
    if not matched:
        answer = f"두 조건을 모두 만족하는 사업을 찾지 못했습니다.\n\n적용 조건: {condition}"
        return CompoundAnswer(answer, (), condition)

    lines = [
        f"- {doc_id} — {days}일, {amount:,}원"
        for doc_id, days, amount in matched
    ]
    note = (
        f"\n\n예산 정보가 없는 단기 사업 {unknown_budget}건은 결과에서 제외했습니다."
        if unknown_budget
        else ""
    )
    citations = ", ".join(doc_id for doc_id, _days, _amount in matched)
    answer = (
        f"다음 {len(matched)}개 사업이 두 조건을 모두 만족합니다.\n\n"
        + "\n".join(lines)
        + f"\n\n적용 조건: {condition}{note}\n\n[근거: {citations}]"
    )
    return CompoundAnswer(answer, tuple(item[0] for item in matched), condition)
