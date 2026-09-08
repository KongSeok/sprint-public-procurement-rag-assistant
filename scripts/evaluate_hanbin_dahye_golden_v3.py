#!/usr/bin/env python3
"""한빈 retrieval + 다혜 generation 통합본의 Golden Set v3 평가.

통합 버전: ``hanbin-dahye-v1``
- retrieval: ``feat/rag-pipeline-and-eval`` tip ``d51633b``
- generation: ``experiment/DH`` tip ``5ea75c7``
- 제외: uyt5041-lab/pi-six의 Evidence-Harness 및 생성 스택

API 응답을 매 문항마다 CSV에 저장하므로 중단 뒤 ``--resume``으로 이어갈 수 있다.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from src.config import OUTPUT_DIR  # noqa: E402
from src.data_processing.chunking import load_chunks  # noqa: E402
from src.evaluation.golden_set_v3 import load_golden_set_v3  # noqa: E402
from src.generation.dahye_generation import (  # noqa: E402
    DahyeGPT5MiniGenerator,
    build_dahye_context,
)
from src.generation.generation import (  # noqa: E402
    check_required_facts,
    compute_citation_coverage,
)
from src.retrieval.indexing import HybridIndex  # noqa: E402
from src.retrieval.query_filters import build_metadata_filter  # noqa: E402

VERSION = "hanbin-dahye-v1"

DAHYE_ABSTENTION_MARKERS = (
    "확인되지 않습니다",
    "답변할 수 없",
    "수행할 수 없",
    "확인할 수 없",
    "판단할 수 없",
    "판정할 수 없",
    "판정해줄 수 없",
    "계산할 수 없",
    "제공할 수 없",
    "받아들일 수 없",
    "확정할 수 없",
    "알려드릴 수 없",
    "불가능합니다",
    "제공된 문서 범위에서는",
)


def _dahye_abstention_match(answer: str | None, expected: bool) -> bool:
    """다혜님 원본 scoring notebook의 기권 표현 목록으로 일치 여부를 잰다."""
    actual = answer is None or any(marker in answer for marker in DAHYE_ABSTENTION_MARKERS)
    return actual == expected


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_DIR / "hanbin_dahye_v1_golden_v3.csv",
    )
    return parser.parse_args()


def _write(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


def _print_summary(result: pd.DataFrame) -> None:
    print(f"\n=== {VERSION} Golden Set v3 요약 ===")
    print(f"실행 완료: {len(result)}건")
    successful = result[result["generation_error"].isna()]
    print(f"생성 성공: {len(successful)}건 / 실패: {len(result) - len(successful)}건")
    if len(result):
        print(f"평균 retrieval recall: {result['retrieval_recall'].dropna().mean():.3f}")
        print(f"평균 citation coverage: {result['citation_coverage'].dropna().mean():.3f}")
        print(f"abstention 일치율: {result['abstention_match'].dropna().mean():.3f}")
    gradable = result[result["facts_total"].fillna(0) > 0]
    if len(gradable):
        print(f"사실 채점 가능: {len(gradable)}건")
        print(f"평균 fact coverage: {gradable['fact_coverage'].mean():.3f}")
        print(f"완전 통과율: {gradable['facts_pass'].mean():.3f}")
    for lane, group in result.groupby("lane"):
        lane_gradable = group[group["facts_total"].fillna(0) > 0]
        if len(lane_gradable):
            print(
                f"[{lane}] fact coverage={lane_gradable['fact_coverage'].mean():.3f}, "
                f"pass={lane_gradable['facts_pass'].mean():.3f} ({len(lane_gradable)}건)"
            )


def main() -> int:
    args = _parse_args()
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY가 없어 다혜님 gpt-5-mini 생성 평가를 실행할 수 없습니다.")
        return 2

    from openai import OpenAI

    golden = load_golden_set_v3()
    if args.limit:
        golden = golden.head(args.limit)

    completed: set[str] = set()
    rows: list[dict] = []
    if args.resume and args.output.exists():
        previous = pd.read_csv(args.output)
        rows = previous.to_dict("records")
        completed = set(previous["id"].astype(str))
        print(f"기존 결과 {len(completed)}건부터 재개")

    chunks = load_chunks()
    if chunks is None:
        raise RuntimeError("output/chunks.pkl이 없습니다")
    index = HybridIndex(chunks)
    generator = DahyeGPT5MiniGenerator(OpenAI())

    pending = golden[~golden["id"].astype(str).isin(completed)]
    for seq, (_, item) in enumerate(pending.iterrows(), start=1):
        expected = set(item["expected_doc_id"])
        top_k = 5 if item["lane"] == "answer" else max(10, len(expected) + 5)
        query = item["query"]
        print(f"[{seq}/{len(pending)}] {item['id']} ({item['lane']}, k={top_k})")

        hits = index.hybrid_search(
            query,
            k=top_k,
            meta_filter=build_metadata_filter(query),
            vector_weight=0.5,
            bm25_weight=0.5,
            expand_to_parent=True,
        )
        retrieved = [hit.doc_id for hit in hits]
        retrieved_set = set(retrieved)
        retrieval_recall = len(retrieved_set & expected) / len(expected) if expected else None

        answer = None
        error = None
        try:
            answer = generator.generate(query, build_dahye_context(hits))
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"

        facts_matched = facts_total = 0
        citation_matched = citation_total = 0
        if answer:
            facts_matched, facts_total = check_required_facts(
                answer, item.get("required_fact_groups")
            )
            citation_matched, citation_total = compute_citation_coverage(answer, expected)

        rows.append(
            {
                "version": VERSION,
                "id": item["id"],
                "lane": item["lane"],
                "source_lane": item["source_lane"],
                "query": query,
                "decision": item.get("decision"),
                "expected_doc_ids": " | ".join(sorted(expected)),
                "retrieved_doc_ids": " | ".join(retrieved),
                "retrieval_recall": retrieval_recall,
                "generated_answer": answer,
                "generation_error": error,
                "facts_matched": facts_matched,
                "facts_total": facts_total,
                "fact_coverage": facts_matched / facts_total if facts_total else None,
                "facts_pass": facts_matched == facts_total if facts_total else None,
                "citation_matched": citation_matched,
                "citation_total": citation_total,
                "citation_coverage": (
                    citation_matched / citation_total if citation_total else None
                ),
                "abstention_match": (
                    _dahye_abstention_match(answer, item.get("decision") == "abstain")
                ),
            }
        )
        _write(rows, args.output)
        time.sleep(0.2)

    result = pd.DataFrame(rows)
    _print_summary(result)
    print(f"상세 결과: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
