"""PDF 표 관련 두 가지를 한 번에 진단하는 스크립트.

[배경] analyze_table_handling_stats.py 결과, 폴백(문서 끝 일괄 첨부) 4건이
전부 PDF였고, 전부 "자리표시자 0개 vs 표 N개"였다. 이건 12절에서 고쳤던
"중첩 표" 문제와는 원인이 다르다 - HWP는 hwp5txt가 "<표>" 자리표시자를 본문에
남겨주기 때문에 위치 복원이 가능했지만, PDF 쪽(pdf_parser.py: PyMuPDF로 페이지
텍스트 추출 + pdfplumber로 표 추출, 서로 독립적인 두 패스)은애초에 표 위치를
표시하는 마커 자체가 없다. 즉 PDF는 표가 있는 모든 문서에서 100% 폴백(끝에
몰아서 첨부)이 발생하는 구조적 한계다.

여기에 더해 표 개수 자체도 의심스럽다:
  고려대학교(420개), 서울시립대학교(187개), 서울특별시(169개), 기초과학연구원(67개)
문서당 이 정도로 많은 "표"가 정말 다 의미있는 표인지, 아니면 pdfplumber가
표 형태가 아닌 것(줄글에 선이 좀 있는 블록, 서식/체크박스 등)을 표로
과다검출(false positive)한 건지 확인이 필요하다. 과다검출이라면 문서 끝에
수십~수백 개의 쓰레기 "표"를 몰아 붙이는 꼴이라 위치 복원보다 이 문제가
더 급할 수 있다.

이 스크립트는 지정한 PDF 하나에 대해:
  1. 페이지별 표 개수 분포 (특정 페이지에 몰려있는지, 전체적으로 퍼져있는지)
  2. 표 크기 분포 (행 x 열) - 1x1, 1xN처럼 비정상적으로 작은 "표"가 많은지
  3. 표 내용 샘플 몇 개를 실제로 눈으로 볼 수 있게 출력
  4. 완전히 텅 빈 셀만 있는 표(빈 표) 개수
을 보여준다.

사용법: python scripts/diagnose_pdf_table_overdetection.py "<파일명 또는 전체경로>"
파일명만 줘도 되고(문서관리 폴더 등에서 자동 탐색은 안 하니, 정확한 경로나
프로젝트 data/files 안에 있는 파일명을 주면 됨), 전체 경로를 줘도 된다.
"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import RAW_FILES_DIR  # noqa: E402


def _resolve_path(arg: str) -> Path:
    p = Path(arg)
    if p.exists():
        return p
    candidate = RAW_FILES_DIR / arg
    if candidate.exists():
        return candidate
    # 확장자 없이 줬을 수도 있으니 느슨하게 한 번 더 탐색
    matches = list(RAW_FILES_DIR.glob(f"*{arg}*"))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(f"'{arg}' 로 여러 파일이 매칭됩니다:")
        for m in matches:
            print(f"  - {m.name}")
        sys.exit(1)
    print(f"파일을 찾을 수 없습니다: {arg}")
    sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print('사용법: python scripts/diagnose_pdf_table_overdetection.py "<파일명 또는 경로>"')
        print("예: python scripts/diagnose_pdf_table_overdetection.py 기초과학연구원_2025년도 중이온가속기용 극저온시스템 운전 용역.pdf")
        sys.exit(1)

    pdf_path = _resolve_path(sys.argv[1])
    print(f"대상 파일: {pdf_path}")
    print()

    import pdfplumber

    per_page_counts = Counter()
    shape_counts = Counter()  # (rows, cols) -> count
    empty_table_count = 0
    total_tables = 0
    sample_tables = []  # (page_no, shape, rows) - 앞쪽 몇 개만 저장

    with pdfplumber.open(pdf_path) as pdf:
        n_pages = len(pdf.pages)
        for page_idx, page in enumerate(pdf.pages, start=1):
            tbls = page.extract_tables()
            per_page_counts[page_idx] = len(tbls)
            for tbl in tbls:
                rows = [[c or "" for c in row] for row in tbl if row]
                total_tables += 1
                shape = (len(rows), max((len(r) for r in rows), default=0))
                shape_counts[shape] += 1
                all_empty = all(not cell.strip() for row in rows for cell in row)
                if all_empty:
                    empty_table_count += 1
                if len(sample_tables) < 8:
                    sample_tables.append((page_idx, shape, rows))

    print(f"전체 페이지 수: {n_pages}")
    print(f"전체 표 개수: {total_tables}  (페이지당 평균 {total_tables / n_pages:.1f}개)")
    print(f"완전히 빈 표(모든 셀이 공백): {empty_table_count}개")
    print()

    print("=" * 100)
    print("페이지별 표 개수 분포 (표가 있는 페이지만, 상위 20개):")
    for page_idx, cnt in sorted(per_page_counts.items(), key=lambda x: -x[1])[:20]:
        if cnt:
            print(f"  {page_idx}페이지: {cnt}개")
    n_pages_with_tables = sum(1 for c in per_page_counts.values() if c)
    print(f"  ... 표가 1개 이상 있는 페이지: {n_pages_with_tables}/{n_pages}")
    print()

    print("=" * 100)
    print("표 크기(행 x 열) 분포 (많은 순 상위 15개):")
    for shape, cnt in sorted(shape_counts.items(), key=lambda x: -x[1])[:15]:
        print(f"  {shape[0]}행 x {shape[1]}열: {cnt}개")
    small_tables = sum(c for s, c in shape_counts.items() if s[0] <= 1 or s[1] <= 1)
    print(f"  (참고: 1행 이하 또는 1열 이하인 '표': {small_tables}개 - 진짜 표가 아닐 가능성 높음)")
    print()

    print("=" * 100)
    print(f"표 내용 샘플 (앞에서부터 {len(sample_tables)}개):")
    for page_idx, shape, rows in sample_tables:
        print(f"--- {page_idx}페이지, {shape[0]}행 x {shape[1]}열 ---")
        for row in rows[:5]:
            print(f"  {row}")
        if len(rows) > 5:
            print(f"  ... (총 {len(rows)}행 중 5행만 표시)")
        print()

    print("=" * 100)
    print("해석 가이드:")
    print("- '전체 표 개수'가 페이지 수보다 훨씬 많고 1x1/1xN 같은 작은 표 비중이 크면:")
    print("  pdfplumber 기본 설정(선/격자 기반 감지)이 표가 아닌 것(밑줄, 구분선, 서식 칸 등)을")
    print("  표로 과다검출하고 있을 가능성이 큼 - table_settings 튜닝이나 최소 크기 필터링을 고려.")
    print("- 표 내용 샘플이 실제로 봐도 진짜 표 같으면: 과다검출은 아니고 원래 표가 많은 문서(예: 규격서/체크리스트류)일 뿐임.")
    print("  이 경우엔 개수 문제가 아니라 '위치 복원' 문제만 남음 - 페이지 단위로라도 표를 해당 페이지 텍스트 뒤에")
    print("  끼워넣는 걸 고려할 만함(HWP처럼 문장 단위 정밀 복원은 PDF 구조상 어렵지만 페이지 단위는 가능).")


if __name__ == "__main__":
    main()
