"""입찰 참여 시작일이 추정(공개일자 대체)된 25건 문서에, 진짜로 본문에
명시적 기간(시작일~마감일 형태)이 없는지 범용으로 재확인하는 스크립트.

[2026-08-28] verify_all_missing_values.py의 3번 카테고리는 좁은 키워드 목록
(["참여 시작", "참가 시작", "접수 시작", "접수기간", "제안서 접수", "시작일"])
으로만 훑어서 25건 중 1건(인천광역시 동구)만 찾아냈다. 근데 그 1건에서 실제로
맞은 키워드가 "접수기간"이었던 걸 보면, 다른 문서들은 "등록기간"/"신청기간"/
"공고기간"/"참가신청" 같은 다른 단어를 썼을 가능성이 높다 - 즉 "나머지 24건은
본문에 날짜가 없다"는 결론은 키워드가 좁아서 생긴 착시일 수 있다.

그래서 이 스크립트는 특정 키워드에 기대지 않고, 본문 전체에서 "날짜 ~ 날짜"
또는 "날짜부터 날짜까지" 형태의 기간 표현 자체를 범용 정규식으로 찾는다 -
이러면 어떤 단어를 썼든 실제 신청/접수 기간이 명시돼 있으면 대부분 잡힌다.
찾은 기간의 시작 날짜가 공개일자와 얼마나 차이 나는지도 같이 계산해서,
차이가 큰(=추정치가 실제와 크게 어긋났을 가능성이 큰) 문서부터 보여준다.

파이참에서 우클릭 > Run으로 실행하면 된다(인자 불필요). 재파싱은 이미
캐시돼 있으므로 몇 초면 끝난다.
"""
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_processing.merge_text import load_merged  # noqa: E402

# "2025. 2. 20." / "2025-02-20" / "2025년 2월 20일" 형태 날짜 하나
_DATE_RE = re.compile(
    r"(\d{4})\s*[.\-년]\s*(\d{1,2})\s*[.\-월]\s*(\d{1,2})\s*일?"
)
# 두 날짜가 "~"/"부터"/"-"/"–" 등으로 근접하게 이어진 기간 표현 (사이 40자 이내)
_RANGE_RE = re.compile(
    r"(\d{4}\s*[.\-년]\s*\d{1,2}\s*[.\-월]\s*\d{1,2}\s*일?)\s*[^0-9]{0,10}[~\-–부터]{1,3}\s*.{0,40}?"
    r"(\d{4}\s*[.\-년]\s*\d{1,2}\s*[.\-월]\s*\d{1,2}\s*일?)"
)


def _parse_date(s: str):
    m = _DATE_RE.search(s)
    if not m:
        return None
    y, mo, d = m.groups()
    try:
        return datetime(int(y), int(mo), int(d))
    except ValueError:
        return None


def main():
    df = load_merged()
    if df is None:
        print("output/merged_docs.pkl 캐시가 없습니다 - step2/step3을 먼저 실행해주세요.")
        return

    targets = df[df["입찰참여시작일_추정"]]
    print(f"입찰 참여 시작일이 추정(공개일자 대체)된 문서: {len(targets)}건\n")

    results = []
    for _, r in targets.iterrows():
        text = r["text"] if isinstance(r["text"], str) else ""
        matches = list(_RANGE_RE.finditer(text))
        공개일 = r.get("공개 일자_dt")
        found_ranges = []
        for m in matches:
            start_dt = _parse_date(m.group(1))
            if start_dt is None:
                continue
            gap_days = None
            if 공개일 is not None and hasattr(공개일, "date"):
                gap_days = abs((start_dt.date() - 공개일.date()).days)
            found_ranges.append((start_dt, m.group(0).replace("\n", " ").strip(), gap_days))
        results.append((r["doc_id"], 공개일, found_ranges))

    with_range = [x for x in results if x[2]]
    without_range = [x for x in results if not x[2]]

    with_range.sort(key=lambda x: max((g[2] or 0) for g in x[2]), reverse=True)

    print("=" * 100)
    print(f"본문에 '날짜~날짜' 기간 표현이 있는 문서: {len(with_range)}건 (공개일자와 차이가 큰 순)")
    for doc_id, 공개일, ranges in with_range:
        print("-" * 100)
        print(f"  {doc_id}  (공개일자={공개일})")
        for start_dt, snippet, gap in ranges[:3]:
            gap_str = f"공개일자와 {gap}일 차이" if gap is not None else "공개일자 비교 불가"
            print(f"    [{gap_str}] {snippet[:120]}")

    print()
    print("=" * 100)
    print(f"본문에 기간 표현을 못 찾은 문서: {len(without_range)}건")
    for doc_id, 공개일, _ in without_range:
        print(f"  - {doc_id}")

    print()
    print("=" * 100)
    print(f"요약: {len(targets)}건 중 {len(with_range)}건은 본문에 실제 기간 표현이 있음(공개일자 추정과 다를 수 있으니 확인 필요),")
    print(f"      {len(without_range)}건은 이 범용 패턴으로도 못 찾음(표 안에 있거나, 정말 본문에 없거나 - 이 스크립트 한계로 100% 확신은 못 함).")
    print("공개일자와 차이가 큰(예: 1일 초과) 문서부터 원본을 직접 열어 확인해보는 걸 추천.")


if __name__ == "__main__":
    main()
