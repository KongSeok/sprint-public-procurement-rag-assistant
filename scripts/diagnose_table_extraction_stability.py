"""표 추출 결과가 재파싱할 때마다 달라지는 문제(비결정성)를 진단한다.

[배경] 13절 패치(본문-표 중복 필터링) 적용 후 step2_merge_text.py를 다시
돌렸더니 "표가 1개 이상 추출된 문서 수"가 30건 -> 62건으로 뛰었다. 13절
패치는 merge_text.py의 후처리(문서 끝에 표를 붙일지 말지)만 건드렸을 뿐
parsed.n_tables 값 자체(=hwp5html/pdfplumber가 실제로 표를 몇 개 뽑았는지)엔
전혀 관여하지 않으므로, 이 변화는 패치 때문이 아니라 재파싱 자체가 돌릴
때마다 다른 결과를 내고 있다는 뜻이다.

유력한 원인: hwp_parser.extract_tables()가 hwp5html 서브프로세스에 90초
타임아웃을 걸어두는데(8절에서 실측: 1.3MB 문서 변환에 44.2초 소요 확인),
타임아웃이 나면 parse_note에 "표 추출 실패: hwp5html 타임아웃"이라고 조용히
기록되고 그 문서는 n_tables=0으로 처리된다. 컴퓨터가 그 순간 얼마나 바빴는지에
따라 어떤 실행에서는 시간 안에 끝나던 변환이 다른 실행에서는 타임아웃 날 수
있다.

이 스크립트는 (재파싱을 다시 하지 않고) 방금 만들어진 output/merged_docs.pkl
캐시의 parse_note만 훑어서:
  1. "타임아웃"이 언급된 문서가 몇 건, 어떤 문서인지
  2. 그 외 표 추출 실패 사유("표 추출 실패: ...")가 있는 문서가 몇 건, 어떤
     사유인지
  3. 전체 n_tables 분포
를 보여준다. 실행에 몇 초면 충분하다(재파싱 없음).

사용법: python scripts/diagnose_table_extraction_stability.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_processing.merge_text import load_merged  # noqa: E402


def main():
    df = load_merged()
    if df is None:
        print("output/merged_docs.pkl 캐시가 없습니다.")
        return

    notes = df["parse_note"].fillna("")

    timeout_mask = notes.str.contains("타임아웃", regex=False)
    fail_mask = notes.str.contains("표 추출 실패", regex=False)

    print(f"전체 문서: {len(df)}건")
    print(f"n_tables > 0 인 문서: {(df['n_tables'] > 0).sum()}건")
    print(f"n_tables == 0 인 문서: {(df['n_tables'] == 0).sum()}건")
    print()

    print("=" * 100)
    print(f"parse_note에 '타임아웃' 언급된 문서: {timeout_mask.sum()}건")
    if timeout_mask.any():
        for _, r in df[timeout_mask].iterrows():
            print(f"  - {r['doc_id']}")
            print(f"      {r['parse_note']}")
    print()

    print("=" * 100)
    print(f"parse_note에 '표 추출 실패' 언급된 문서(타임아웃 포함): {fail_mask.sum()}건")
    if fail_mask.any():
        for _, r in df[fail_mask].iterrows():
            print(f"  - {r['doc_id']} [{r['파일형식'] if '파일형식' in df.columns else '?'}]")
            print(f"      {r['parse_note']}")
    print()

    print("=" * 100)
    print("해석 가이드:")
    print("- 타임아웃 언급이 1건이라도 있으면: 이번 재파싱에서도 실제로 표 추출이 시간 초과로 실패한 문서가")
    print("  있다는 뜻 - 이 스크립트를 다시 몇 번 돌려서(재파싱 없이는 매번 같은 값만 나오니, step2_merge_text.py를")
    print("  다시 돌린 뒤 재실행) n_tables>0 문서 수가 실행마다 변하는지 직접 확인해볼 가치가 있음.")
    print("  변한다면 hwp5html 타임아웃을 더 늘리거나(현재 90초), 문서를 순차 처리 중 다른 무거운 프로세스와")
    print("  동시에 안 돌아가게 하거나, 실패한 문서만 골라 더 긴 타임아웃으로 재시도하는 로직이 필요함.")
    print("- 타임아웃 언급이 0건이면: 이번 실행 자체는 깨끗했다는 뜻 - 그래도 30건->62건으로 뛴 이전 실행에서")
    print("  타임아웃이 있었을 가능성은 남아있음(그 실행의 parse_note는 이미 이번 재파싱으로 덮어써져서 직접")
    print("  확인은 불가) - 확실히 하려면 step2_merge_text.py를 한 번 더 돌려서 표 있는 문서 수가 62에서")
    print("  또 바뀌는지 보는 게 제일 직접적인 검증임.")


if __name__ == "__main__":
    main()
