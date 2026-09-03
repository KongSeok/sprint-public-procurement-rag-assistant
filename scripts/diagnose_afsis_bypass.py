"""한국농어촌공사 AFSIS 문서에 새로 추가한 "우회 추출"이 실제로 통하는지
확인하기 위한 1회성 진단 스크립트.

diagnose_afsis_error.py로 원인(문서 안 제어문자 때문에 pyhwp가 만드는 중간
XML이 깨져서 lxml이 못 읽음)을 확인한 다음 단계다. src/parsers/hwp_parser.py에
추가한 _bypass_extract_text/_bypass_extract_tables를 이 문서 하나에 직접
돌려서, 정말로 본문/표를 회복해오는지 눈으로 확인한다.

파이참에서 우클릭 > Run으로 실행하면 된다(인자 불필요).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import RAW_FILES_DIR  # noqa: E402
from src.data_processing.parsers import hwp_parser  # noqa: E402

TARGET = RAW_FILES_DIR / "한국농어촌공사_아세안+3 식량안보정보시스템(AFSIS) 3단계 협력(캄보디아.hwp"


def main():
    if not TARGET.exists():
        print(f"파일을 찾을 수 없음: {TARGET}")
        sys.exit(1)

    print(f"대상 파일: {TARGET}")
    print(f"파일 크기: {TARGET.stat().st_size / 1024:.0f} KB\n")

    print("=== 1) 우회 본문 추출 시도 ===")
    text, err = hwp_parser._bypass_extract_text(TARGET)
    if err:
        print(f"실패: {err}")
    else:
        print(f"성공: 텍스트 길이 {len(text)}자")
        print("--- 앞부분 300자 미리보기 ---")
        print(text[:300])

    print("\n=== 2) 우회 표 추출 시도 (시간이 좀 걸릴 수 있음) ===")
    tables, table_err = hwp_parser._bypass_extract_tables(TARGET)
    if table_err:
        print(f"실패: {table_err}")
    else:
        print(f"성공: 표 {len(tables)}개 추출")
        if tables:
            print("--- 첫 번째 표 미리보기(최대 5행) ---")
            for row in tables[0][:5]:
                print(row)

    print("\n=== 3) parse_hwp() 전체 경로로도 확인 (실제 파이프라인이 타는 경로) ===")
    result = hwp_parser.parse_hwp(TARGET, extract_tables_flag=True)
    print(f"ok={result.ok}, 텍스트 길이={len(result.text)}, 표 개수={result.n_tables}")
    if result.error:
        print(f"에러: {result.error}")
    if result.text_note:
        print(f"본문 우회 메모: {result.text_note}")
    if result.table_note:
        print(f"표 메모: {result.table_note}")


if __name__ == "__main__":
    main()
