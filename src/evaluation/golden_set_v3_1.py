"""Golden Set v3의 검수 반영본을 읽는 실험용 오버레이.

원본 공유 파일과 ``review.status``는 변경하지 않는다. B15에서 원문 확인이
끝났지만 실행 파일에 빠진 세 문서만 런타임에 추가하고 패치 버전을 기록한다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .golden_set_v3 import GOLDEN_SET_V3_DIR, load_golden_set_v3


GOLDEN_PATCH_VERSION = "3.1.0-review-candidate"
B15_CASE_ID = "supplemental-set-b15"
B15_ADDITIONAL_SOURCE_LABELS = (
    "전북대학교_JST 공유대학(원) xAPI기반 LRS시스템 구축.hwp",
    "전북특별자치도 정읍시_정읍체육트레이닝센터 통합운영관리시스템 구.hwp",
    "파주도시관광공사_종량제봉투 판매관리 전산시스템 개선사업.hwp",
)


def _normalize_filename(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).removeprefix("refined_")).strip().casefold()


def _corpus_ids(corpus_doc_ids: set[str] | None) -> set[str]:
    if corpus_doc_ids is not None:
        return set(corpus_doc_ids)
    from ..data_processing.merge_text import load_merged

    frame = load_merged()
    if frame is None:
        raise RuntimeError("output/merged_docs.pkl 캐시가 없습니다.")
    return set(frame["doc_id"])


def load_golden_set_v3_1(
    corpus_doc_ids: set[str] | None = None,
    base_dir: Path = GOLDEN_SET_V3_DIR,
) -> pd.DataFrame:
    """기존 79문항에 B15 검수 후보 세 문서를 추가해 반환한다."""
    corpus_ids = _corpus_ids(corpus_doc_ids)
    frame = load_golden_set_v3(corpus_doc_ids=corpus_ids, base_dir=base_dir).copy()
    corpus_by_name = {_normalize_filename(doc_id): doc_id for doc_id in corpus_ids}
    missing = [
        label for label in B15_ADDITIONAL_SOURCE_LABELS
        if _normalize_filename(label) not in corpus_by_name
    ]
    if missing:
        raise ValueError(f"B15 추가 정답 문서를 코퍼스에서 찾지 못했습니다: {missing}")

    mask = frame["id"] == B15_CASE_ID
    if int(mask.sum()) != 1:
        raise ValueError(f"{B15_CASE_ID} 문항 수가 1개가 아닙니다: {int(mask.sum())}")
    index = frame.index[mask][0]
    expected = list(frame.at[index, "expected_doc_id"] or [])
    for label in B15_ADDITIONAL_SOURCE_LABELS:
        doc_id = corpus_by_name[_normalize_filename(label)]
        if doc_id not in expected:
            expected.append(doc_id)
    if len(expected) != 15:
        raise ValueError(f"B15 정답 문서가 15개가 아닙니다: {len(expected)}")
    frame.at[index, "expected_doc_id"] = expected
    frame["golden_patch_version"] = GOLDEN_PATCH_VERSION
    frame["golden_patch_note"] = ""
    frame.at[index, "golden_patch_note"] = "B15 원문 검수 후보 3개 추가: 12→15"
    return frame
