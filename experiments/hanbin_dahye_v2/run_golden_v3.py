#!/usr/bin/env python3
"""한빈 Retrieval + 다혜 최신 Generation의 Golden Set v3 B-v2 평가."""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

from src.data_processing.chunking import load_chunks
from src.evaluation.golden_set_v3 import load_golden_set_v3
from src.generation.generation import check_required_facts, compute_citation_coverage
from src.retrieval.indexing import HybridIndex

from .answer_generation import ask_rfp_v9


VERSION = "hanbin-dahye-v2"
DEFAULT_OUTPUT_DIR = Path("output/experiments/hanbin_dahye_v2")
ABSTENTION_MARKERS = (
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


class _RecordingCompletions:
    """다혜님 함수를 바꾸지 않고 실제 전달 Context를 기록하는 API 래퍼."""

    def __init__(self, delegate: Any):
        self._delegate = delegate
        self.last_prompt = ""

    def create(self, **kwargs: Any) -> Any:
        messages = kwargs.get("messages") or []
        if messages:
            self.last_prompt = str(messages[-1].get("content", ""))
        return self._delegate.create(**kwargs)


class RecordingOpenAI:
    def __init__(self, client: Any):
        self.completions = _RecordingCompletions(client.chat.completions)
        self.chat = SimpleNamespace(completions=self.completions)

    @property
    def last_prompt(self) -> str:
        return self.completions.last_prompt

    def reset(self) -> None:
        self.completions.last_prompt = ""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="시험 실행할 앞쪽 문항 수")
    parser.add_argument("--resume", action="store_true", help="기존 CSV 다음부터 재개")
    parser.add_argument(
        "--summarize-only",
        action="store_true",
        help="API를 호출하지 않고 기존 상세 CSV의 요약 JSON만 다시 생성",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def _extract_context(prompt: str) -> str:
    marker = "## 컨텍스트 (검색된 문서 조각)"
    if marker not in prompt:
        return ""
    context = prompt.rsplit(marker, 1)[1]
    return context.rsplit("## 질문", 1)[0].strip()


def _context_doc_ids(context: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"\[문서:\s*(.+?)\]", context)))


def _is_abstention(answer: str | None) -> bool:
    return answer is None or any(marker in answer for marker in ABSTENTION_MARKERS)


def _write_rows(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


def _mean(series: pd.Series) -> float | None:
    values = series.dropna()
    return round(float(values.mean()), 4) if len(values) else None


def _document_mention_coverage(row: pd.Series) -> float | None:
    """엄격한 [근거: ...] 형식과 별개로 답변 내 문서명 언급 비율을 진단한다."""
    expected = [
        value.strip()
        for value in str(row.get("expected_doc_ids", "")).split(" | ")
        if value.strip()
    ]
    if not expected:
        return None
    answer = str(row.get("generated_answer", ""))
    return sum(doc_id in answer for doc_id in expected) / len(expected)


def _build_summary(result: pd.DataFrame) -> dict[str, Any]:
    document_mentions = result.apply(_document_mention_coverage, axis=1)
    successful = result[result["generation_error"].isna()]
    gradable = result[result["facts_total"].fillna(0) > 0]
    summary: dict[str, Any] = {
        "version": VERSION,
        "cases": int(len(result)),
        "generation_success_rate": round(len(successful) / len(result), 4)
        if len(result)
        else None,
        "retrieval_recall": _mean(result["retrieval_recall"]),
        "all_required_docs_retrieved_rate": _mean(result["retrieval_recall"] == 1),
        "context_fact_coverage": _mean(gradable["context_fact_coverage"]),
        "context_fact_full_rate": _mean(gradable["context_fact_coverage"] == 1),
        "answer_fact_coverage": _mean(gradable["fact_coverage"]),
        "fact_full_pass_rate": _mean(gradable["facts_pass"]),
        "citation_coverage": _mean(result["citation_coverage"]),
        "document_mention_coverage": _mean(document_mentions),
        "abstention_match_rate": _mean(result["abstention_match"]),
        "compatible_overall_score": _mean(result["compatible_score"]),
        "lanes": {},
    }
    group_column = "source_lane" if "source_lane" in result.columns else "lane"
    for lane, group in result.groupby(group_column):
        lane_gradable = group[group["facts_total"].fillna(0) > 0]
        lane_document_mentions = group.apply(_document_mention_coverage, axis=1)
        summary["lanes"][str(lane)] = {
            "cases": int(len(group)),
            "retrieval_recall": _mean(group["retrieval_recall"]),
            "all_required_docs_retrieved_rate": _mean(
                group["retrieval_recall"] == 1
            ),
            "context_fact_coverage": _mean(lane_gradable["context_fact_coverage"]),
            "context_fact_full_rate": _mean(
                lane_gradable["context_fact_coverage"] == 1
            ),
            "answer_fact_coverage": _mean(lane_gradable["fact_coverage"]),
            "citation_coverage": _mean(group["citation_coverage"]),
            "document_mention_coverage": _mean(lane_document_mentions),
            "abstention_match_rate": _mean(group["abstention_match"]),
            "compatible_score": _mean(group["compatible_score"]),
        }
    return summary


def main() -> int:
    args = _parse_args()
    output_csv = args.output_dir / "golden_v3_results.csv"
    summary_json = args.output_dir / "summary.json"

    if args.summarize_only:
        if not output_csv.exists():
            print(f"상세 결과가 없습니다: {output_csv}")
            return 2
        summary = _build_summary(pd.read_csv(output_csv))
        summary_json.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY가 없어 gpt-5-mini 평가를 실행할 수 없습니다.")
        return 2

    from openai import OpenAI

    golden = load_golden_set_v3()
    if args.limit:
        golden = golden.head(args.limit)

    rows: list[dict[str, Any]] = []
    completed: set[str] = set()
    if args.resume and output_csv.exists():
        previous = pd.read_csv(output_csv)
        rows = previous.to_dict("records")
        completed = set(previous["id"].astype(str))
        print(f"기존 결과 {len(completed)}건부터 재개")

    chunks = load_chunks()
    if chunks is None:
        raise RuntimeError("output/chunks.pkl이 없습니다")
    index = HybridIndex(chunks)

    seen_docs: set[str] = set()
    all_filenames_with_biz: list[tuple[str, str]] = []
    for chunk in chunks:
        if chunk.doc_id in seen_docs:
            continue
        seen_docs.add(chunk.doc_id)
        all_filenames_with_biz.append(
            (chunk.doc_id, str((chunk.metadata or {}).get("발주_기관", "")))
        )

    recording_client = RecordingOpenAI(OpenAI())
    pending = golden[~golden["id"].astype(str).isin(completed)]
    for seq, (_, item) in enumerate(pending.iterrows(), start=1):
        case_id = str(item["id"])
        query = str(item["query"])
        expected = set(item["expected_doc_id"])
        print(f"[{seq}/{len(pending)}] {case_id} ({item['lane']})")

        answer = None
        error = None
        recording_client.reset()
        try:
            answer = ask_rfp_v9(
                query,
                recording_client,
                index,
                chunks,
                all_filenames_with_biz,
            )
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"

        context = _extract_context(recording_client.last_prompt)
        context_docs = _context_doc_ids(context)
        context_doc_set = set(context_docs)
        retrieval_recall = (
            len(context_doc_set & expected) / len(expected) if expected else None
        )

        context_facts_matched, context_facts_total = check_required_facts(
            context, item.get("required_fact_groups")
        )
        facts_matched, facts_total = check_required_facts(
            answer or "", item.get("required_fact_groups")
        )
        citation_matched, citation_total = compute_citation_coverage(
            answer or "", expected
        )
        expected_abstention = item.get("decision") == "abstain"
        abstention_match = _is_abstention(answer) == expected_abstention
        fact_coverage = facts_matched / facts_total if facts_total else None
        compatible_score = (
            100.0 if abstention_match else 0.0
        ) if expected_abstention else (
            fact_coverage * 100 if fact_coverage is not None else None
        )

        rows.append(
            {
                "version": VERSION,
                "id": case_id,
                "lane": item["lane"],
                "source_lane": item["source_lane"],
                "query": query,
                "decision": item.get("decision"),
                "expected_doc_ids": " | ".join(sorted(expected)),
                "context_doc_ids": " | ".join(context_docs),
                "retrieval_recall": retrieval_recall,
                "context_facts_matched": context_facts_matched,
                "context_facts_total": context_facts_total,
                "context_fact_coverage": (
                    context_facts_matched / context_facts_total
                    if context_facts_total
                    else None
                ),
                "generated_answer": answer,
                "generation_error": error,
                "facts_matched": facts_matched,
                "facts_total": facts_total,
                "fact_coverage": fact_coverage,
                "facts_pass": facts_matched == facts_total if facts_total else None,
                "citation_matched": citation_matched,
                "citation_total": citation_total,
                "citation_coverage": (
                    citation_matched / citation_total if citation_total else None
                ),
                "abstention_match": abstention_match,
                "compatible_score": compatible_score,
            }
        )
        _write_rows(rows, output_csv)
        time.sleep(0.2)

    result = pd.DataFrame(rows)
    summary = _build_summary(result)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"상세 결과: {output_csv}")
    print(f"요약 결과: {summary_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
