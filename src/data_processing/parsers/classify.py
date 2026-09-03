"""문서 유형 분류: scanned / table_heavy / plain_text.

1차로는 CSV의 기존 텍스트 길이로 근사 분류하고(원본 파일 없이도 가능),
원본 파일 파싱 결과가 있으면 실제 페이지수/표 개수 등으로 분류를 갱신한다.
설계안 문서 3절의 "문서 유형 분류 -> 파싱 전략 차등 적용"을 코드로 옮긴 것.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from ...config import SCAN_OR_TABLE_SUSPECT_LEN, SHORT_TEXT_LEN

DocType = Literal["scanned", "table_heavy", "short_text", "plain_text"]


@dataclass
class ClassificationResult:
    doc_type: DocType
    confidence: Literal["low", "medium", "high"]
    reason: str


def classify_by_text_length(text_len: int) -> ClassificationResult:
    """CSV 텍스트만 있을 때의 1차 근사 분류 (원본 파일 열기 전)."""
    if text_len < SCAN_OR_TABLE_SUSPECT_LEN:
        return ClassificationResult(
            doc_type="scanned",
            confidence="low",
            reason=f"텍스트 길이 {text_len}자 < {SCAN_OR_TABLE_SUSPECT_LEN}자, 스캔본/표위주 의심",
        )
    if text_len < SHORT_TEXT_LEN:
        return ClassificationResult(
            doc_type="short_text",
            confidence="low",
            reason=f"텍스트 길이 {text_len}자, 짧은 문서 (표위주일 가능성 있음)",
        )
    return ClassificationResult(
        doc_type="plain_text",
        confidence="low",
        reason=f"텍스트 길이 {text_len}자, 일반 텍스트로 추정",
    )


def classify_with_parse_result(
    text_len: int,
    n_tables: int,
    n_pages: Optional[int] = None,
    n_scanned_pages: Optional[int] = None,
    used_ocr: bool = False,
) -> ClassificationResult:
    """원본 파일 파싱 결과가 있을 때의 확정 분류."""
    if n_pages and n_scanned_pages is not None and n_pages > 0:
        if n_scanned_pages / n_pages > 0.5:
            reason = f"{n_scanned_pages}/{n_pages} 페이지가 텍스트 레이어 없음"
            if used_ocr:
                reason += " (OCR 적용됨)"
            return ClassificationResult("scanned", "high", reason)

    if n_tables >= 3 and text_len < 2000:
        return ClassificationResult(
            "table_heavy", "high",
            f"표 {n_tables}개 대비 본문 텍스트가 짧음({text_len}자) -> 표 위주 문서",
        )

    if text_len < SCAN_OR_TABLE_SUSPECT_LEN:
        return ClassificationResult(
            "scanned", "medium",
            f"텍스트 길이 {text_len}자로 매우 짧으나 표는 {n_tables}개 -> 파싱 실패 의심",
        )

    return ClassificationResult("plain_text", "high", f"본문 {text_len}자, 표 {n_tables}개")
