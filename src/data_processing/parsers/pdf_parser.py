"""pdf 파서.

- PyMuPDF(fitz): 페이지별 텍스트 추출 + 텍스트 밀도로 스캔본 여부 판정
- pdfplumber: 표 구조 추출
- 스캔본으로 판정된 페이지는 PyMuPDF로 이미지 렌더링 후 pytesseract(kor+eng)로 OCR
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

# PyMuPDF는 손상되거나 표준을 살짝 벗어난 PDF(정부/스캔 시스템 산출물에 흔함)를
# 열 때 "MuPDF error: syntax error: invalid key in dict" 같은 메시지를 C
# 레벨에서 콘솔에 직접 출력한다. 이건 Python 예외가 아니라 MuPDF 내부 경고라
# 대부분 무시하고 계속 진행해도 텍스트 추출 자체는 되는 경우가 많은데, 매
# 문서마다 여러 줄씩 찍혀서 진행상황 로그를 못 알아볼 지경으로 만든다.
# 콘솔 출력은 끄되, 내용은 잃지 않도록 parse_pdf()에서 문서별로 모아 mupdf_warnings
# 필드에 담아 반환한다(merge_text.py가 이걸 parse_note에 실어 표시).
fitz.TOOLS.mupdf_display_errors(False)
fitz.TOOLS.mupdf_display_warnings(False)

# 페이지당 이 글자수 미만이면 "텍스트 레이어가 사실상 없다 = 스캔본"으로 간주
SCAN_PAGE_CHAR_THRESHOLD = 20

# 윈도우 등에서 tesseract.exe가 PATH에 없을 때, 환경변수로 직접 경로를 지정할 수 있게 함.
# 예: TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
_TESSERACT_CMD_ENV = os.environ.get("TESSERACT_CMD")
if _TESSERACT_CMD_ENV:
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = _TESSERACT_CMD_ENV


@dataclass
class ParseResult:
    text: str = ""
    tables: list[list[list[str]]] = field(default_factory=list)
    n_tables: int = 0
    n_pages: int = 0
    n_scanned_pages: int = 0
    used_ocr: bool = False
    source: str = "pdf"
    error: str | None = None
    mupdf_warnings: str = ""

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def is_scanned(self) -> bool:
        return self.n_pages > 0 and self.n_scanned_pages / self.n_pages > 0.5


def _extract_tables(pdf_path: Path) -> list[list[list[str]]]:
    import pdfplumber

    tables: list[list[list[str]]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for tbl in page.extract_tables():
                rows = [[c or "" for c in row] for row in tbl if row]
                if rows:
                    tables.append(rows)
    return tables


def _ocr_page(page: "fitz.Page") -> str:
    import pytesseract
    from PIL import Image
    import io

    pix = page.get_pixmap(dpi=200)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    return pytesseract.image_to_string(img, lang="kor+eng")


def parse_pdf(pdf_path: Path, ocr_if_scanned: bool = True) -> ParseResult:
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return ParseResult(error=f"파일 없음: {pdf_path}")

    fitz.TOOLS.reset_mupdf_warnings()
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:  # noqa: BLE001
        return ParseResult(error=f"PDF 열기 실패: {e}")

    page_texts = []
    n_scanned = 0
    used_ocr = False

    for page in doc:
        raw = page.get_text().strip()
        if len(raw) < SCAN_PAGE_CHAR_THRESHOLD:
            n_scanned += 1
            if ocr_if_scanned:
                try:
                    raw = _ocr_page(page).strip()
                    used_ocr = True
                except Exception as e:  # noqa: BLE001
                    raw = ""
                    # OCR 실패는 치명적이지 않으므로 에러로 만들지 않고 빈 텍스트로 둠
        page_texts.append(raw)

    n_pages = doc.page_count
    doc.close()

    try:
        tables = _extract_tables(pdf_path)
    except Exception:  # noqa: BLE001
        tables = []

    warnings = "; ".join(fitz.TOOLS.mupdf_warnings())
    fitz.TOOLS.reset_mupdf_warnings()

    return ParseResult(
        text="\n\n".join(page_texts),
        tables=tables,
        n_tables=len(tables),
        n_pages=n_pages,
        n_scanned_pages=n_scanned,
        used_ocr=used_ocr,
        source="pdf",
        error=None,
        mupdf_warnings=warnings,
    )


if __name__ == "__main__":
    import sys
    result = parse_pdf(Path(sys.argv[1]))
    print(
        f"ok={result.ok} pages={result.n_pages} scanned={result.n_scanned_pages} "
        f"ocr_used={result.used_ocr} tables={result.n_tables} text_len={len(result.text)}"
    )
