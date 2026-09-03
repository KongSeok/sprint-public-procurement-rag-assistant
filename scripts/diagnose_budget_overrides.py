"""budget_overrides.csv에 들어간 2건(경희대, 한국철도공사 모바일오피스)이 진짜
재파싱된 원본 본문 기준으로도 맞는 값인지 재검증하는 진단 스크립트.

[2026-08-28] 이 두 건은 CSV의 1차 추출 텍스트(`data_list.csv`의 `텍스트` 컬럼,
품질이 낮다고 이미 문서화된 컬럼)만 보고 확정한 값이었다 - 원본 hwp를 재파싱한
진짜 본문은 그때 확인할 방법이 없었다(원본 파일 자체가 없었음). 그런데
`_apply_budget_overrides()`가 override 파일에 있는 문서의 `budget_unknown`을
바로 False로 바꿔버리기 때문에, `resolve_budget_from_text()`(merge_text 단계
에서 재파싱된 진짜 본문 기준으로 예산 후보를 재평가하는 함수)가 이 두 문서를
영영 다시 검사하지 않는 구조적 문제가 있었다 - 재파싱이 나중에 실제로 끝나도
그 결과가 이 두 문서에는 반영될 기회조차 없었던 것.

이 스크립트는 그 문제를 우회해서, override와 무관하게 두 문서의 "진짜 재파싱된
본문"(output/merged_docs.pkl, source=raw_parsed여야 함)에 대해 강제로 다시
예산 후보 탐지를 돌려본다. 재파싱은 이미 끝나 캐시돼 있으므로(step3/4/5를 이미
돌렸다면) 새로 몇 시간 기다릴 필요 없이 몇 초면 끝난다.

파이참에서 우클릭 > Run으로 실행하면 된다(인자 불필요).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_processing.load_metadata import _extract_budget_candidate  # noqa: E402
from src.data_processing.merge_text import load_merged  # noqa: E402

TARGETS = {
    "경희대학교_[입찰공고] 산학협력단 정보시스템 운영 용역업체 선정.hwp": 400_000_000,
    "한국철도공사 (용역)_모바일오피스 시스템 고도화 용역(총체 및 1차).hwp": 843_000_000,
}

_BUDGET_KEYWORDS = ["사업예산", "사업 금액", "사업금액", "사업비", "추정가격"]


def _print_keyword_context(text: str, window: int = 200):
    """_extract_budget_candidate가 못 찾더라도, 사람이 눈으로 확인할 수 있게
    예산 관련 키워드 주변 텍스트를 전부 보여준다."""
    found_any = False
    for kw in _BUDGET_KEYWORDS:
        start = 0
        while True:
            idx = text.find(kw, start)
            if idx == -1:
                break
            found_any = True
            s = max(0, idx - 20)
            e = min(len(text), idx + window)
            snippet = text[s:e].replace("\n", " ").replace("\r", " ")
            print(f"    ...{snippet}...")
            start = idx + len(kw)
    if not found_any:
        print("    (본문 전체에 예산 관련 키워드 자체가 없음)")


def main():
    df = load_merged()
    if df is None:
        print("output/merged_docs.pkl 캐시가 없습니다 - step2/step3을 먼저 실행해주세요.")
        return

    for doc_id, override_value in TARGETS.items():
        row = df[df["doc_id"] == doc_id]
        print("=" * 100)
        print(f"[{doc_id}]")
        if row.empty:
            print("  -> merged_docs.pkl에 이 문서가 없습니다 (제외됐거나 doc_id 불일치)")
            continue

        r = row.iloc[0]
        text = r["text"] if isinstance(r["text"], str) else ""
        print(f"  source(재파싱 여부) = {r['source']!r}  (raw_parsed면 진짜 원본 재파싱, csv_fallback이면 여전히 CSV 1차 텍스트)")
        print(f"  본문 길이 = {len(text)}자")
        print(f"  현재 override 확정값 = {override_value:,}원 (확인자: claude, 근거: CSV 1차 텍스트만)")
        print(f"  현재 사업_금액_출처 = {r.get('사업_금액_출처')!r} (override 때문에 manual_confirmed로 잠겨있어 자동 재검사 대상에서 빠져있던 상태)")
        print()

        source, snippet = _extract_budget_candidate(text)
        print(f"  [재파싱된 본문 기준 재탐지 결과] 분류={source!r}")
        if snippet:
            print(f"    스니펫: {snippet}")
        print()
        print("  [예산 관련 키워드 주변 본문 전체 (사람이 직접 읽고 확인)]")
        _print_keyword_context(text)
        print()

    print("=" * 100)
    print("확인 포인트:")
    print("1) source가 raw_parsed로 나오는지 (csv_fallback이면 원본 파일이 아직도 안 읽힌 것 - 원본 파일명/경로부터 확인)")
    print("2) 키워드 주변 본문에 실제로 400,000,000원 / 843,000,000원이 그대로 나오는지")
    print("3) 다르게 나온다면 budget_overrides.csv의 해당 행을 새 값으로 교체")


if __name__ == "__main__":
    main()
