"""diagnose_pdf_table_overdetection.py 후속 - '중복/서식 표' 가설을 정량으로 검증한다.

[배경] 기초과학연구원 문서(49p, 표 67개)를 diagnose_pdf_table_overdetection.py로
찍어봤더니:
  - 2행x2열 표가 17개나 됨 - 표본을 보니 페이지 상단에 반복되는 "제목 | 문서번호
    ·개정번호·발행일·페이지" 양식 박스로 보임(문서 표준 서식 헤더).
  - 일부 표(4p, 5p 샘플)는 그 헤더 박스 밑에 이어지는 목차/본문 문단 전체를
    같은 "표"의 한 셀로 통째로 삼켜버린 경우도 있음(선/경계선을 표 경계로
    오인식한 것으로 추정).
이 두 가지 다 사실이라면, 표로 뽑힌 텍스트의 상당 부분이 이미 본문 텍스트
(PyMuPDF가 뽑는 page.get_text())에도 그대로 들어있다는 뜻이 된다. 그러면
표 내용을 문서 끝에 추가로 붙이는 지금 방식은 "새로운 정보 추가"가 아니라
"같은 내용 중복 삽입"이 되어 버려 - 위치 문제보다 이게 더 먼저 손볼 문제일 수
있다.

이 스크립트는 표 하나하나에 대해:
  1. 표의 각 셀 텍스트가 같은 페이지의 본문 텍스트(공백 제거 후 비교)에
     이미 그대로 들어있는지 검사 -> 완전중복 / 부분중복 / 표에만 있음(고유)
     로 분류.
  2. 표에 "문서번호"와 "개정번호"가 동시에 들어있으면 반복 서식 헤더 표로
     추정해서 별도 표시.
  3. 표별 상세 목록을 출력.
을 한다. 이 결과로 "표가 많아 보이는 이유"가 진짜 표가 많아서인지, 서식
헤더가 페이지마다 찍혀서인지, 본문과 중복되는 내용이라 걸러내도 되는지를
정량적으로 판단할 수 있다.

사용법: python scripts/diagnose_pdf_table_duplication.py "<파일명 또는 전체경로>"
"""
import re
import sys
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


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def main():
    if len(sys.argv) < 2:
        print('사용법: python scripts/diagnose_pdf_table_duplication.py "<파일명 또는 경로>"')
        sys.exit(1)

    pdf_path = _resolve_path(sys.argv[1])
    print(f"대상 파일: {pdf_path}")
    print()

    import fitz  # PyMuPDF - 실제 파이프라인(pdf_parser.py)이 본문 텍스트를 뽑는 것과 동일한 방법
    import pdfplumber

    doc = fitz.open(pdf_path)
    page_texts_norm = [_norm(page.get_text()) for page in doc]
    doc.close()

    dup_full = dup_partial = dup_none = 0
    header_like = 0
    detail = []  # (page_idx, table_idx, n_rows, status, ratio, is_header_like)

    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages, start=1):
            body_norm = page_texts_norm[page_idx - 1] if page_idx - 1 < len(page_texts_norm) else ""
            tables = page.find_tables()
            for t_idx, t in enumerate(tables, start=1):
                rows = t.extract()
                rows = [[c or "" for c in row] for row in rows if row]
                flat_cells = [c for row in rows for c in row if c.strip()]
                if not flat_cells:
                    continue

                found = sum(1 for c in flat_cells if _norm(c) and _norm(c) in body_norm)
                ratio = found / len(flat_cells)

                joined = " ".join(flat_cells)
                is_header_like = ("문서번호" in joined) and ("개정번호" in joined)
                if is_header_like:
                    header_like += 1

                if ratio >= 0.9:
                    status = "완전중복"
                    dup_full += 1
                elif ratio > 0:
                    status = "부분중복"
                    dup_partial += 1
                else:
                    status = "표에만있음(고유)"
                    dup_none += 1

                detail.append((page_idx, t_idx, len(rows), status, ratio, is_header_like))

    total = dup_full + dup_partial + dup_none
    print(f"검사한 표(빈 표 제외): {total}개")
    print(f"완전중복(표 내용이 이미 본문에 그대로 있음, 중복률≥90%): {dup_full}개")
    print(f"부분중복: {dup_partial}개")
    print(f"표에만 있음(고유 정보로 추정, 중복률 0%): {dup_none}개")
    print(f"헤더/개정이력 서식성 표(문서번호+개정번호 동시 포함)로 추정: {header_like}개")
    print()

    print("=" * 100)
    print("표별 상세:")
    for page_idx, t_idx, nrows, status, ratio, is_header in detail:
        tag = " [헤더성]" if is_header else ""
        print(f"  {page_idx}p 표#{t_idx}: {nrows}행, {status}(중복률 {ratio:.0%}){tag}")

    print()
    print("=" * 100)
    print("해석 가이드:")
    print("- 완전중복 비중이 높으면: 표로 뽑힌 내용이 이미 본문 텍스트에도 그대로 들어있다는 뜻 -")
    print("  표를 문서 끝에 추가로 붙이면 같은 내용이 두 번 들어가 임베딩/토큰 낭비가 됨. 이런 표는 걸러내는 게 나음.")
    print("- 헤더/개정이력성 표가 많으면: 매 페이지 반복되는 문서 양식(제목/문서번호/개정번호 박스)이 표로")
    print("  오검출되고 있다는 뜻 - 페이지마다 거의 똑같은 표가 수십 개 찍히는 원인. 필터링 대상 1순위.")
    print("- '표에만 있음' 비중이 크면: 진짜 표 안에만 있는 고유 정보가 많다는 뜻 - 이런 표는 위치 복원할 가치가 있음.")


if __name__ == "__main__":
    main()
