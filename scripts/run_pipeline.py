#!/usr/bin/env python3
"""파이프라인 실행 + 샘플 질의 데모.

사용법:
    python scripts/run_pipeline.py
    python scripts/run_pipeline.py --query "지자체 발주 예산 3억 이상 사업"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pipeline import run_pipeline  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="학사정보시스템 고도화 사업 예산")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--vector-weight", type=float, default=0.5)
    parser.add_argument("--bm25-weight", type=float, default=0.5)
    parser.add_argument("--org", default=None, help="발주 기관으로 메타데이터 필터링")
    parser.add_argument(
        "--rebuild", action="store_true",
        help="output/merged_docs.pkl, output/chunks.pkl 캐시를 무시하고 처음부터 다시 계산",
    )
    args = parser.parse_args()

    merged, chunks, index = run_pipeline(use_cache=not args.rebuild)

    meta_filter = None
    if args.org:
        meta_filter = lambda m: m.get("발주_기관") == args.org  # noqa: E731

    print(f"\n=== 하이브리드 검색 데모 ===\n질의: {args.query}")
    if args.org:
        print(f"메타데이터 필터: 발주 기관 = {args.org}")
    hits = index.hybrid_search(
        args.query, k=args.k, meta_filter=meta_filter,
        vector_weight=args.vector_weight, bm25_weight=args.bm25_weight,
    )
    if not hits:
        print("검색 결과 없음")
    for i, h in enumerate(hits, 1):
        print(f"\n[{i}] score={h.score:.3f} doc_id={h.doc_id}")
        print(f"    발주기관={h.metadata.get('발주_기관')} doc_type={h.metadata.get('doc_type')}")
        print(f"    {h.text[:120].replace(chr(10), ' ')}...")


if __name__ == "__main__":
    main()
