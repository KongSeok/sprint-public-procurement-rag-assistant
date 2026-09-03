"""질문의 명시적 조건을 검색 메타데이터 필터로 변환한다.

실험 브랜치의 질의 필터 아이디어 중 오탐 위험이 낮은 예산·지자체 조건만
공통 파이프라인에 포함한다. 조건을 찾지 못하면 검색 결과를 제한하지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable


_BUDGET_RE = re.compile(
    r"(?P<amount>\d+(?:\.\d+)?)\s*억\s*(?:원)?\s*(?P<op>이상|초과|넘는|넘은)"
)
_LOCAL_GOV_RE = re.compile(r"지자체|지방자치단체")
_LOCAL_GOV_SUFFIX_RE = re.compile(r"(?:특별시|광역시|특별자치시|특별자치도|도|시|군|구)(?:청)?$")


@dataclass(frozen=True)
class QueryConstraints:
    minimum_budget: int | None = None
    budget_exclusive: bool = False
    local_government: bool = False
    organization: str | None = None

    def matches(self, metadata: dict) -> bool:
        if self.minimum_budget is not None:
            raw = metadata.get("사업_금액")
            try:
                budget = float(raw)
            except (TypeError, ValueError):
                return False
            if self.budget_exclusive:
                if budget <= self.minimum_budget:
                    return False
            elif budget < self.minimum_budget:
                return False

        org = str(metadata.get("발주_기관") or "").strip()
        if self.local_government and not _LOCAL_GOV_SUFFIX_RE.search(org):
            return False
        if self.organization and self.organization.casefold() not in org.casefold():
            return False
        return True


def parse_query_constraints(query: str, *, organization: str | None = None) -> QueryConstraints:
    match = _BUDGET_RE.search(query)
    minimum = int(float(match.group("amount")) * 100_000_000) if match else None
    exclusive = bool(match and match.group("op") in {"초과", "넘는", "넘은"})
    return QueryConstraints(
        minimum_budget=minimum,
        budget_exclusive=exclusive,
        local_government=bool(_LOCAL_GOV_RE.search(query)),
        organization=organization.strip() if organization and organization.strip() else None,
    )


def build_metadata_filter(
    query: str, *, organization: str | None = None
) -> Callable[[dict], bool] | None:
    constraints = parse_query_constraints(query, organization=organization)
    if constraints == QueryConstraints():
        return None
    return constraints.matches
