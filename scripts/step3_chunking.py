"""5단계: Chunking 결과 확인용. 파이참에서 우클릭 > Run.

step2에서 저장한 output/merged_docs.pkl 캐시가 있으면 그걸 불러와서 바로
Chunking하고(빠름), 없으면 처음부터 다시 계산한다(느림, 원본 파일 있으면
재파싱까지 포함). 결과는 output/chunks.pkl에 저장해 step4에서 재사용한다.
"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_processing.chunking import chunk_all, save_chunks  # noqa: E402
from src.data_processing.load_metadata import load_clean_metadata  # noqa: E402
from src.data_processing.merge_text import load_merged, merge_all, save_merged  # noqa: E402

if __name__ == "__main__":
    df = load_merged()
    if df is None:
        print("[step3] 캐시(output/merged_docs.pkl) 없음 -> step2부터 다시 계산합니다...")
        df = merge_all(load_clean_metadata())
        save_merged(df)
        # [2026-08-27 수정] 방금 만든 df를 그대로 쓰지 않고 load_merged()로 다시
        # 불러온다 - load_merged()에는 예산/마감일 재평가뿐 아니라 hwp5txt의
        # "<표>"/"<그림>" 자리표시자 제거(hwp_parser._strip_hwp5txt_placeholders)도
        # 들어있는데, 방금 저장만 하고 바로 chunk_all(df)로 넘어가면 이 재로드
        # 경로를 안 타서 그 정제가 적용 안 된 채로 청킹될 위험이 있었다. 캐시가
        # 있던 경우(else 분기)와 완전히 똑같은 경로를 타도록 통일.
        df = load_merged()
    else:
        print("[step3] 캐시(output/merged_docs.pkl) 불러옴")

    chunks = chunk_all(df)
    save_chunks(chunks)

    print()
    print(f"총 chunk 수: {len(chunks)} (문서 {len(df)}건)")
    print("전략 분포:", dict(Counter(c.strategy for c in chunks)))
    print()
    print("샘플 chunk 3개:")
    for c in chunks[:3]:
        print(f"- [{c.strategy}] {c.chunk_id} :: {c.text[:60]}...")
