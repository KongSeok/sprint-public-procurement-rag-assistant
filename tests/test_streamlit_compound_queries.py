from types import SimpleNamespace

from streamlit_demo.compound_queries import answer_period_budget_query


def _chunk(doc_id: str, days: int):
    return SimpleNamespace(
        doc_id=doc_id,
        text=f"사업기간: 계약일로부터 {days}일",
    )


def test_period_and_budget_conditions_are_both_applied():
    result = answer_period_budget_query(
        "3개월 이내의 사업 중 예산 10억 미만인 걸 모두 알려줘",
        [("under.hwp", ""), ("over.hwp", ""), ("long.hwp", "")],
        {
            "under.hwp": {"사업_금액": 900_000_000},
            "over.hwp": {"사업_금액": 1_100_000_000},
            "long.hwp": {"사업_금액": 100_000_000},
        },
        [_chunk("under.hwp", 90), _chunk("over.hwp", 60), _chunk("long.hwp", 120)],
    )

    assert result is not None
    assert result.doc_ids == ("under.hwp",)
    assert "over.hwp" not in result.answer
    assert "long.hwp" not in result.answer
    assert "기간 90일 이내 · 예산 1,000,000,000원 미만" in result.answer


def test_non_compound_question_falls_back_to_existing_rag():
    result = answer_period_budget_query("3개월 이내 사업을 알려줘", [], {}, [])
    assert result is None


def test_recent_publication_and_budget_are_both_applied():
    result = answer_period_budget_query(
        "최근 3개월 동안 게시된 공고 중 예산이 10억 미만인 공고를 모두 찾아줘",
        [("recent-under.hwp", ""), ("recent-over.hwp", ""), ("old.hwp", "")],
        {
            "recent-under.hwp": {"공개 일자": "2024-09-01", "사업_금액": 900_000_000},
            "recent-over.hwp": {"공개 일자": "2024-09-01", "사업_금액": 1_100_000_000},
            "old.hwp": {"공개 일자": "2024-04-01", "사업_금액": 100_000_000},
        },
        [],
    )

    assert result is not None
    assert result.doc_ids == ("recent-under.hwp",)
    assert "recent-over.hwp" not in result.answer
    assert "old.hwp" not in result.answer
    assert "교육용 데이터의 최신 공개일 2024-09-01 기준" in result.answer


def test_budget_range_applies_lower_and_upper_bounds():
    result = answer_period_budget_query(
        "최근 3개월 공개된 공고 중 예산 5억 이상 20억 미만을 찾아줘",
        [("low.hwp", ""), ("inside.hwp", ""), ("high.hwp", "")],
        {
            "low.hwp": {"공개 일자": "2024-09-01", "사업_금액": 400_000_000},
            "inside.hwp": {"공개 일자": "2024-09-01", "사업_금액": 900_000_000},
            "high.hwp": {"공개 일자": "2024-09-01", "사업_금액": 2_000_000_000},
        },
        [],
    )

    assert result is not None
    assert result.doc_ids == ("inside.hwp",)
    assert "예산 500,000,000원 이상" in result.answer
    assert "예산 2,000,000,000원 미만" in result.answer
