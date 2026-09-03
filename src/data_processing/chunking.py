"""5단계: Chunking.

두 전략 제공:
  - recursive_chunk: 일반 문서용. RecursiveCharacterTextSplitter로 단순 분할.
  - parent_child_chunk: 표가 포함되었거나(table_heavy) 구조가 있는 문서용.
      parent = 큰 단위(PARENT_CHUNK_SIZE), child = parent 내부를 다시 작게 쪼갠 것.
      "검색은 작게, 답변 context는 크게" (멘토링 노트 6번 권고) 그대로 구현.

각 chunk에는 문서 메타데이터(doc_id, 발주기관, 예산, 마감일, 파일형식, 문서유형)를
그대로 attach해 인덱싱 단계에서 필터링에 쓸 수 있게 한다.

[2026-08-27] 분할하기 직전에 clean_text_for_chunking()으로 목차/페이지번호/장식
기호 같은 노이즈 줄을 지운다 - 아래 clean_text_for_chunking() docstring 참고.
"""
from __future__ import annotations

import pickle
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..config import CHUNK_OVERLAP, CHUNK_SIZE, CHUNKS_PATH, PARENT_CHUNK_OVERLAP, PARENT_CHUNK_SIZE

_CHILD_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP,
    separators=["\n\n", "\n", "。", ". ", " ", ""],
)
_PARENT_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=PARENT_CHUNK_SIZE, chunk_overlap=PARENT_CHUNK_OVERLAP,
    separators=["\n\n", "\n", "。", ". ", " ", ""],
)

# --- 청킹 직전 노이즈 제거 --------------------------------------------------
# 아래 4가지는 정규식으로 안전하게(오탐 위험 낮게) 잡을 수 있어서 자동으로
# 지운다. 목차/개정이력표/붙임 목록/표지/서명란/보일러플레이트 조항처럼 문서마다
# 형태가 들쭉날쭉하거나, 지우면 진짜 정보(예: 계약조항)까지 날아갈 위험이 있는
# 것들은 아직 자동화하지 않았다 - 실제 재파싱 텍스트 샘플을 몇 개 더 봐야 오탐
# 없이 잡을 수 있는 패턴을 만들 수 있어서, output/merged_docs_preview.csv에서
# 실제 사례를 몇 개 뽑아 보내주면 그걸 보고 이어서 다듬을 것.
#
# 1. 목차 dot-leader: "1. 사업개요 ......... 3" 처럼 제목과 페이지 번호 사이를
#    점(온점/가운뎃점/말줄임표)으로 채운 줄 전체를 지운다. "‥"(U+2025, 두 점)나
#    "…"(U+2026, 말줄임표)는 문자 하나가 시각적으로 점 2~3개를 나타내므로
#    반복 횟수 기준을 낮게(3) 잡는다 - 그래도 일반 문장에서 이 문자들이 3개나
#    연달아 나올 일은 거의 없어 오탐 위험은 낮다.
_DOT_LEADER_RE = re.compile(r"^.{1,60}?[.․‥…·]{3,}\s*\d{1,4}\s*$")
# 2. "- 3 -" 형태의 단독 페이지 번호 줄.
_PAGE_NUMBER_RE = re.compile(r"^\s*-\s*\d{1,4}\s*-\s*$")
# 3. 장식용 구분선. 아스키 문자(-=~_*)뿐 아니라 한글 문서에서 흔한 박스 그리기
#    문자(─━═ 등)와 ◇◆※도 포함 - 이런 기호만 3개 이상 반복된 줄 전체를 지운다.
_DECORATIVE_LINE_RE = re.compile(r"^[\-=~_*◇◆※─━═│┃╌╍]{3,}$")


def _is_noise_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False  # 빈 줄 자체는 여기서 지우지 않음(문단 구분 유지, 아래서 별도 정리)
    return bool(
        _DOT_LEADER_RE.match(stripped)
        or _PAGE_NUMBER_RE.match(stripped)
        or _DECORATIVE_LINE_RE.match(stripped)
    )


def clean_text_for_chunking(text: str) -> str:
    """청킹 직전에 목차 dot-leader/단독 페이지번호/장식 구분선 줄을 지운다.

    표 병합(merge_text._flatten_tables)이나 hwp5txt 추출 과정에서 생기는 완전히
    빈 줄이 노이즈 제거로 인해 3줄 이상 연달아 남을 수 있어, 그런 경우 빈 줄을
    최대 1개로 줄인다(문단 구분은 유지하되 불필요한 여백은 없앰). 이 함수가
    지우지 않는 것들(목차/표지/개정이력표/붙임 목록/서명란/반복 보일러플레이트
    조항)은 모듈 상단 주석 참고 - 문서마다 형태가 달라서 오탐 위험 없이 자동화
    하려면 실제 샘플이 더 필요하다."""
    if not text:
        return text
    lines = text.split("\n")
    kept = [ln for ln in lines if not _is_noise_line(ln)]
    cleaned = "\n".join(kept)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    text: str
    strategy: str  # "recursive" | "parent" | "child"
    parent_chunk_id: str | None
    metadata: dict[str, Any] = field(default_factory=dict)


def _base_metadata(row) -> dict[str, Any]:
    # 입찰_참여_마감일은 원본 CSV 날짜(입찰 참여 마감일_dt)가 아니라 정제된 값
    # (입찰참여마감일_정제)을 써야 한다 - 사업_금액과 대칭으로, 사람이
    # deadline_overrides.csv에 확정한 마감일이 있으면 그 값이 여기 반영된다.
    # 예전엔 이 필드가 원본 컬럼을 그대로 읽어서, 사람이 후보를 확인해 확정해도
    # 인덱싱에는 전혀 반영되지 않는 구멍이 있었다(2026-08-27 발견).
    deadline = row.get("입찰참여마감일_정제")
    return {
        "발주_기관": row.get("발주 기관"),
        "사업_금액": row.get("사업_금액_정제"),
        "budget_unknown": bool(row.get("budget_unknown")),
        "입찰_참여_마감일": str(deadline) if deadline is not None and pd.notna(deadline) else None,
        "입찰참여마감일_결측": bool(row.get("입찰참여마감일_결측")),
        "파일형식": row.get("파일형식"),
        "doc_type": row.get("doc_type"),
        "source": row.get("source"),
    }


def recursive_chunk(row) -> list[Chunk]:
    doc_id = row["doc_id"]
    text = clean_text_for_chunking(row["text"] or "")
    meta = _base_metadata(row)
    pieces = _CHILD_SPLITTER.split_text(text) if text.strip() else []
    return [
        Chunk(
            chunk_id=f"{doc_id}::rec::{i}",
            doc_id=doc_id,
            text=piece,
            strategy="recursive",
            parent_chunk_id=None,
            metadata=meta,
        )
        for i, piece in enumerate(pieces)
    ]


def parent_child_chunk(row) -> list[Chunk]:
    doc_id = row["doc_id"]
    text = clean_text_for_chunking(row["text"] or "")
    meta = _base_metadata(row)
    chunks: list[Chunk] = []
    if not text.strip():
        return chunks

    parents = _PARENT_SPLITTER.split_text(text)
    for p_i, parent_text in enumerate(parents):
        parent_id = f"{doc_id}::parent::{p_i}"
        chunks.append(
            Chunk(
                chunk_id=parent_id, doc_id=doc_id, text=parent_text,
                strategy="parent", parent_chunk_id=None, metadata=meta,
            )
        )
        children = _CHILD_SPLITTER.split_text(parent_text)
        for c_i, child_text in enumerate(children):
            chunks.append(
                Chunk(
                    chunk_id=f"{parent_id}::child::{c_i}", doc_id=doc_id,
                    text=child_text, strategy="child", parent_chunk_id=parent_id,
                    metadata=meta,
                )
            )
    return chunks


def chunk_document(row) -> list[Chunk]:
    """문서 유형에 따라 전략을 선택한다.

    table_heavy 문서, 혹은 표가 별도 추출된(raw_parsed + n_tables>0) 문서는
    Parent-Child로. 그 외(plain_text/short_text/scanned)는 Recursive로.
    scanned은 OCR 결과라 노이즈가 많을 수 있어 일단 Recursive로 두고,
    추후 Golden Set 평가에서 별도 취급 여부를 판단한다.
    """
    doc_type = row.get("doc_type")
    n_tables = row.get("n_tables", 0) or 0
    if doc_type == "table_heavy" or n_tables > 0:
        return parent_child_chunk(row)
    return recursive_chunk(row)


def chunk_all(merged_df) -> list[Chunk]:
    all_chunks: list[Chunk] = []
    for _, row in merged_df.iterrows():
        all_chunks.extend(chunk_document(row))
    return all_chunks


def save_chunks(chunks: list[Chunk], path: Path = CHUNKS_PATH) -> None:
    """chunk_all() 결과를 output/chunks.pkl에 저장 (다음 단계에서 재사용)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(chunks, f)
    print(f"[chunking] 저장됨: {path}")


def load_chunks(path: Path = CHUNKS_PATH) -> Optional[list[Chunk]]:
    """캐시된 chunk가 있으면 불러오고, 없으면 None."""
    if not path.exists():
        return None
    with open(path, "rb") as f:
        return pickle.load(f)


if __name__ == "__main__":
    # [2026-08-27 수정] 예전엔 무조건 merge_all(load_clean_metadata())을 불러서
    # output/merged_docs.pkl 캐시가 있어도 매번 처음부터 재파싱했다(hwp 96건
    # 기준 최대 몇 시간). scripts/step3_chunking.py와 똑같이 load_merged()로
    # 캐시를 먼저 확인하고, 없을 때만 merge_all()로 폴백하도록 맞췄다 - 이
    # 블록은 `python -m src.chunking`으로 직접 돌릴 때를 위한 것이라, 평소
    # 작업 흐름(scripts/step*.py)과 똑같이 캐시를 존중해야 한다.
    from .load_metadata import load_clean_metadata
    from .merge_text import load_merged, merge_all, save_merged

    df = load_merged()
    if df is None:
        print("[chunking] 캐시(output/merged_docs.pkl) 없음 -> 처음부터 재파싱합니다...")
        df = merge_all(load_clean_metadata())
        save_merged(df)
    else:
        print("[chunking] 캐시(output/merged_docs.pkl) 불러옴")

    chunks = chunk_all(df)
    print(f"총 chunk 수: {len(chunks)} (문서 {len(df)}건)")
    from collections import Counter
    print(Counter(c.strategy for c in chunks))
