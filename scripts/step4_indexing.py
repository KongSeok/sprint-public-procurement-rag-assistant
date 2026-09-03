"""6단계: Vector+BM25 하이브리드 인덱싱 + 샘플 질의 확인용. 파이참에서 우클릭 > Run.

step3에서 저장한 output/chunks.pkl 캐시가 있으면 그걸 바로 불러와 인덱싱한다
(빠름). 없으면 처음부터 다시 계산한다. 벡터 인덱스는 output/chroma_db/ 에
그대로 파일로 저장되어 다음 실행에서도 남아있다(단, 이 스크립트를 실행할
때마다 컬렉션을 새로 만들어 덮어쓴다).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_processing.chunking import chunk_all, load_chunks, save_chunks  # noqa: E402
from src.retrieval.indexing import HybridIndex  # noqa: E402
from src.data_processing.load_metadata import load_clean_metadata  # noqa: E402
from src.data_processing.merge_text import load_merged, merge_all, save_merged  # noqa: E402

if __name__ == "__main__":
    chunks = load_chunks()
    if chunks is None:
        print("[step4] 캐시(output/chunks.pkl) 없음 -> step2~3부터 다시 계산합니다...")
        df = load_merged()
        if df is None:
            df = merge_all(load_clean_metadata())
            save_merged(df)
            # [2026-08-27 수정] step3_chunking.py와 동일한 이유로 재로드 추가 -
            # load_merged()가 하는 정제(예산/마감일 재평가 + "<표>"/"<그림>"
            # 자리표시자 제거)를 캐시 유무와 무관하게 항상 똑같이 적용받기 위함.
            df = load_merged()
        chunks = chunk_all(df)
        save_chunks(chunks)
    else:
        print("[step4] 캐시(output/chunks.pkl) 불러옴")

    index = HybridIndex(chunks)
    print(f"인덱싱 완료: chunk {len(chunks)}개, 임베딩 백엔드={index.embedding_backend.name}")
    print(f"벡터 인덱스 저장 위치: {index.embedding_backend.name} -> output/chroma_db/")

    query = "학사정보시스템 고도화 사업 예산"
    print(f"\n샘플 질의: {query}")
    for h in index.hybrid_search(query, k=3):
        print(f"[{h.matched_by} {h.score:.3f}] {h.doc_id} :: {h.text[:60]}")
