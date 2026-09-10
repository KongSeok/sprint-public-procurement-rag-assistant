"""Streamlit 시연용 복합 메타데이터 질문 처리.

팀 공용 생성 모듈을 수정하지 않고, 기간과 예산처럼 명시적인 조건이 함께
주어진 질문만 결정적으로 필터링한다. 조건을 완전히 해석하지 못하면 ``None``을
반환하여 기존 RAG 생성 경로가 처리하게 한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
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


def _amount_bounds(question: str) -> list[tuple[str, int]]:
    matches = re.findall(
        r"(\d+(?:\.\d+)?)\s*(억|천만|백만|만|원)\s*(미만|이하|이상|초과)",
        question,
    )
    return [
        (operator, int(float(number) * _AMOUNT_UNITS[unit]))
        for number, unit, operator in matches
    ]


def _period_bound(question: str) -> int | None:
    match = re.search(r"(\d+)\s*(개월|일)\s*(?:이내|미만|이하)", question)
    if match:
        value = int(match.group(1))
        return value * 30 if match.group(2) == "개월" else value
    if "짧은 사업" in question:
        return 90
    return None


def _publication_window_days(question: str) -> int | None:
    """'최근 N개월 게시/공개된 공고'의 조회 기간을 일수로 반환한다."""
    if not any(word in question for word in ("게시", "공개", "등록", "나온 공고", "공고일")):
        return None
    match = re.search(r"(?:최근\s*)?(\d+)\s*(개월|일)", question)
    if not match:
        return None
    value = int(match.group(1))
    return value * 30 if match.group(2) == "개월" else value


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


def _date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "to_pydatetime"):
        try:
            return value.to_pydatetime().date()
        except (TypeError, ValueError, AttributeError):
            pass
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        return None
    normalized = (
        text.replace("년", "-")
        .replace("월", "-")
        .replace("일", "")
        .replace(".", "-")
        .replace("/", "-")
    )
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", normalized)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _published_date(metadata: dict[str, Any]) -> date | None:
    for key in ("공개 일자_dt", "공개_일자", "공개 일자", "공고일", "게시일"):
        parsed = _date(metadata.get(key))
        if parsed is not None:
            return parsed
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


def _budget_condition_text(bounds: list[tuple[str, int]]) -> str:
    return " · ".join(f"예산 {bound:,}원 {operator}" for operator, bound in bounds)


def answer_period_budget_query(
    question: str,
    catalog: Iterable[tuple[str, str]],
    doc_metadata: dict[str, dict[str, Any]],
    chunks: Iterable[Any],
) -> CompoundAnswer | None:
    """사업기간/공개일과 예산을 함께 명시한 목록 질문을 처리한다."""
    amount_bounds = _amount_bounds(question)
    if not amount_bounds:
        return None

    publication_days = _publication_window_days(question)
    if publication_days is not None:
        dated_docs = [
            (doc_id, _published_date(doc_metadata.get(doc_id, {})))
            for doc_id, _business_name in catalog
        ]
        dated_docs = [(doc_id, published) for doc_id, published in dated_docs if published]
        if not dated_docs:
            return CompoundAnswer(
                "공개일 정보가 없어 최근 게시 공고를 판정할 수 없습니다.",
                (),
                "공개일 정보 없음",
            )
        latest = max(published for _doc_id, published in dated_docs)
        today = date.today()
        anchor = today if today - latest <= timedelta(days=180) else latest
        start = anchor - timedelta(days=publication_days)
        matched_dates: list[tuple[str, date, int]] = []
        unknown_budget = 0
        for doc_id, published in dated_docs:
            if not start <= published <= anchor:
                continue
            amount = _budget(doc_metadata.get(doc_id, {}))
            if amount is None:
                unknown_budget += 1
                continue
            if all(_passes_budget(amount, operator, bound) for operator, bound in amount_bounds):
                matched_dates.append((doc_id, published, amount))
        matched_dates.sort(key=lambda item: (-item[1].toordinal(), item[2], item[0]))
        anchor_note = (
            "오늘 기준"
            if anchor == today
            else f"교육용 데이터의 최신 공개일 {anchor.isoformat()} 기준"
        )
        condition = (
            f"{anchor_note} 최근 {publication_days}일({start.isoformat()}~{anchor.isoformat()}) · "
            f"{_budget_condition_text(amount_bounds)}"
        )
        if not matched_dates:
            return CompoundAnswer(
                f"두 조건을 모두 만족하는 공고를 찾지 못했습니다.\n\n적용 조건: {condition}",
                (),
                condition,
            )
        lines = [
            f"- {doc_id} — 공개일 {published.isoformat()}, 예산 {amount:,}원"
            for doc_id, published, amount in matched_dates
        ]
        note = (
            f"\n\n예산 정보가 없는 기간 내 공고 {unknown_budget}건은 결과에서 제외했습니다."
            if unknown_budget
            else ""
        )
        citations = ", ".join(doc_id for doc_id, _published, _amount in matched_dates)
        answer = (
            f"다음 {len(matched_dates)}개 공고가 두 조건을 모두 만족합니다.\n\n"
            + "\n".join(lines)
            + f"\n\n적용 조건: {condition}{note}\n\n[근거: {citations}]"
        )
        return CompoundAnswer(
            answer,
            tuple(item[0] for item in matched_dates),
            condition,
        )

    period_limit = _period_bound(question)
    if period_limit is None:
        return None

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
        if all(_passes_budget(amount, operator, bound) for operator, bound in amount_bounds):
            matched.append((doc_id, days, amount))

    matched.sort(key=lambda item: (item[1], item[2], item[0]))
    condition = f"기간 {period_limit}일 이내 · {_budget_condition_text(amount_bounds)}"
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
