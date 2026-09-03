"""전체 파이프라인 오케스트레이션.

1. load_metadata  : CSV 로드 + 메타데이터 정제
2~3. merge_text   : 원본 파일 재파싱 시도 -> CSV 텍스트 폴백, 문서유형 분류
4. (merge_text에 포함) 메타데이터 정제는 load_metadata에서 처리
5. chunking       : 문서유형별 Recursive / Parent-Child 청킹
6. indexing       : Vector(chroma) + BM25 하이브리드 인덱스 구축
"""
from __future__ import annotations

from .data_processing.chunking import chunk_all, load_chunks, save_chunks
from .retrieval.indexing import HybridIndex
from .data_processing.load_metadata import load_clean_metadata
from .data_processing.merge_text import load_merged, merge_all, save_merged


def run_pipeline(persist_index: bool = True, use_cache: bool = True) -> tuple:
    """use_cache=True면 output/merged_docs.pkl, output/chunks.pkl 캐시를 재사용한다.
    files/ 폴더의 원본을 바꿨다면 use_cache=False로 실행해 강제로 다시 계산해야 한다.
    """
    merged = load_merged() if use_cache else None
    if merged is not None:
        print("[1-2/4] 캐시(output/merged_docs.pkl) 불러옴 -> 메타데이터/재파싱 단계 생략")
    else:
        print("[1/4] 메타데이터 로드/정제...")
        df = load_clean_metadata()
        print(f"  -> {len(df)}건, budget_unknown={df['budget_unknown'].sum()}건, 공고번호_결측={df['공고번호_결측'].sum()}건")

        print("[2/4] 원본 재파싱/텍스트 병합 + 문서유형 분류...")
        merged = merge_all(df)
        save_merged(merged)
    print("  -> source 분포:", merged["source"].value_counts().to_dict())
    print("  -> doc_type 분포:", merged["doc_type"].value_counts().to_dict())

    chunks = load_chunks() if use_cache else None
    if chunks is not None:
        print("[3/4] 캐시(output/chunks.pkl) 불러옴 -> Chunking 생략")
    else:
        print("[3/4] Chunking...")
        chunks = chunk_all(merged)
        save_chunks(chunks)
    from collections import Counter
    print(f"  -> 총 chunk {len(chunks)}개, 전략 분포: {dict(Counter(c.strategy for c in chunks))}")

    print("[4/4] Indexing (Vector + BM25)...")
    index = HybridIndex(chunks, persist=persist_index)
    print(f"  -> 임베딩 백엔드: {index.embedding_backend.name}")

    return merged, chunks, index


if __name__ == "__main__":
    run_pipeline()
