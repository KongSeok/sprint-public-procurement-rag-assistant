"""한국철도공사 예약발매시스템 개량 ISMP 용역.hwp의 예산 불일치를 확인한다.

[배경] 13절의 `budget_overrides.csv`에 팀원이 웹 검색으로 확인했다는
470,251,968원이 확정값으로 들어가 있는데, 우리 쪽 텍스트 검색으로는 본문에서
"185억"이라는 훨씬 큰 숫자도 발견된 적이 있었다(정규식이 "원" 접미사가 없어
자동 탐지는 놓쳤음). 두 값의 규모가 40배 가까이 차이 나서, override
CSV에는 "100% 확신은 아니므로 원본에서 직접 확인 추천"이라고 메모만 남겨두고
확정하지 않았었다.

이 스크립트는 지금까지의 표 관련 패치(11~14절 - inline 위치 복원, 중첩 표
제거, Gantt표 복원, 중복 표 필터링, 타임아웃 상향)가 다 반영된 최신
본문에서 "185억"이 실제로 어떤 문맥에 등장하는지(무엇에 대한 금액인지),
그리고 470,251,968원(4.7억) 관련 문구도 본문에 있는지 같이 보여준다 -
숫자만 보고 판단하지 않고 앞뒤 문장을 읽고 판단할 수 있게 하는 목적이다.

사용법: python scripts/check_ismp_budget_context.py
(파일명을 인자로 주면 다른 문서도 같은 방식으로 확인 가능:
 python scripts/check_ismp_budget_context.py "다른문서.hwp" "찾을 숫자 패턴")
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_processing.merge_text import load_merged  # noqa: E402

DEFAULT_DOC_ID = "한국철도공사 (용역)_예약발매시스템 개량 ISMP 용역.hwp"
DEFAULT_PATTERNS = ["185억", "470,251,968", "4,702,", "4억", "47,0", "예산", "사업비", "사업 금액", "사업금액"]

CONTEXT_CHARS = 200


def _print_contexts(text: str, pattern: str, label: str):
    matches = list(re.finditer(re.escape(pattern), text))
    print(f"\n--- '{pattern}' 검색: {len(matches)}건 ---")
    for i, m in enumerate(matches, start=1):
        start = max(0, m.start() - CONTEXT_CHARS)
        end = min(len(text), m.end() + CONTEXT_CHARS)
        snippet = text[start:end].replace("\n", " ⏎ ")
        print(f"  [{label} #{i}] ...{snippet}...")


def main():
    doc_id = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DOC_ID
    patterns = sys.argv[2:] if len(sys.argv) > 2 else DEFAULT_PATTERNS

    df = load_merged()
    if df is None:
        print("output/merged_docs.pkl 캐시가 없습니다.")
        return

    rows = df[df["doc_id"] == doc_id]
    if len(rows) == 0:
        print(f"doc_id를 찾을 수 없음: {doc_id!r}")
        print("혹시 오탈자인지 확인하려면 아래 후보들을 참고:")
        candidates = df[df["doc_id"].str.contains("예약발매|ISMP", regex=True, na=False)]
        for cid in candidates["doc_id"]:
            print(f"  - {cid}")
        return

    row = rows.iloc[0]
    print(f"대상 문서: {doc_id}")
    print(f"source: {row['source']}, n_tables: {row['n_tables']}")
    print(f"parse_note: {row['parse_note']}")
    print(f"사업_금액_출처: {row.get('사업_금액_출처')}")
    print(f"사업_금액_후보텍스트: {row.get('사업_금액_후보텍스트')}")
    print(f"전체 텍스트 길이: {len(row['text'])}자")

    text = row["text"]
    for p in patterns:
        _print_contexts(text, p, p)


if __name__ == "__main__":
    main()
