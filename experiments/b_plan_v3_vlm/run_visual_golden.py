#!/usr/bin/env python3
"""Evaluate B-v3 on the ten visual Golden Set v3 questions."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

from experiments.hanbin_dahye_v2.answer_generation import ask_rfp_v9
from experiments.hanbin_dahye_v2.run_golden_v3 import (
    ABSTENTION_MARKERS,
    RecordingOpenAI,
    _context_doc_ids,
    _extract_context,
)
from src.data_processing.chunking import load_chunks
from src.evaluation.golden_set_v3 import load_golden_set_v3
from src.generation.generation import check_required_facts, compute_citation_coverage
from src.retrieval.indexing import HybridIndex


VERSION = "b-v3-selective-local-vlm"
DEFAULT_EVIDENCE = Path("output/experiments/b_plan_v3_vlm/visual_evidence.jsonl")
DEFAULT_OUTPUT = Path("output/experiments/b_plan_v3_vlm")


class _InjectingCompletions:
    def __init__(self, delegate: Any, evidence: str, doc_id: str, citation_label: str):
        self._delegate = delegate
        self.evidence = evidence
        self.doc_id = doc_id
        self.citation_label = citation_label
        self.last_prompt = ""

    def create(self, **kwargs: Any) -> Any:
        messages = [dict(message) for message in (kwargs.get("messages") or [])]
        if messages and self.evidence:
            prompt = str(messages[-1].get("content", ""))
            marker = "## 질문"
            visual = (
                f"[문서: {self.doc_id}]\n"
                f"[검증 대상 시각 근거: {self.citation_label}]\n{self.evidence}\n\n"
            )
            prompt = prompt.replace(marker, visual + marker, 1)
            messages[-1]["content"] = prompt
            kwargs["messages"] = messages
        response = self._delegate.create(**kwargs)
        self.last_prompt = str(messages[-1].get("content", "")) if messages else ""
        return response


class InjectingOpenAI:
    def __init__(self, client: Any, evidence: str, doc_id: str, citation_label: str):
        self.completions = _InjectingCompletions(
            client.chat.completions, evidence, doc_id, citation_label
        )
        self.chat = SimpleNamespace(completions=self.completions)

    @property
    def last_prompt(self) -> str:
        return self.completions.last_prompt


def _load_evidence(path: Path) -> dict[str, dict[str, Any]]:
    return {
        row["case_id"]: row
        for row in (
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
        )
    }


def _is_abstention(answer: str | None) -> bool:
    return answer is None or any(marker in answer for marker in ABSTENTION_MARKERS)


def _mean(series: pd.Series) -> float | None:
    values = series.dropna()
    return round(float(values.mean()), 4) if len(values) else None


def _add_provenance_columns(result: pd.DataFrame) -> pd.DataFrame:
    result = result.copy()

    def levels(value: Any) -> set[str]:
        try:
            refs = json.loads(value) if isinstance(value, str) else (value or [])
        except json.JSONDecodeError:
            refs = []
        return {str(ref.get("provenance_level")) for ref in refs if isinstance(ref, dict)}

    provenance = result["visual_evidence_refs"].apply(levels)
    result["visual_page_bbox_verified"] = provenance.apply(
        lambda values: "page_bbox_verified" in values
    )
    result["visual_target_locator_verified"] = provenance.apply(
        lambda values: bool(
            values & {"page_bbox_verified", "gold_target_object_hash_verified"}
        )
    )
    return result


def _build_summary(result: pd.DataFrame) -> dict[str, Any]:
    result = _add_provenance_columns(result)
    summary: dict[str, Any] = {
        "version": VERSION,
        "cases": len(result),
        "visual_evidence_used_rate": _mean(result["visual_evidence_used"]),
        "visual_page_bbox_verified_rate": _mean(result["visual_page_bbox_verified"]),
        "visual_target_locator_verified_rate": _mean(result["visual_target_locator_verified"]),
        "generation_success_rate": _mean(result["generation_error"].isna()),
        "retrieval_recall": _mean(result["retrieval_recall"]),
        "context_fact_coverage": _mean(result["context_fact_coverage"]),
        "answer_fact_coverage": _mean(result["fact_coverage"]),
        "fact_full_pass_rate": _mean(result["facts_pass"]),
        "citation_coverage": _mean(result["citation_coverage"]),
        "compatible_overall_score": _mean(result["compatible_score"]),
        "by_evidence_type": {},
    }
    for evidence_type, group in result.groupby("evidence_type"):
        summary["by_evidence_type"][str(evidence_type)] = {
            "cases": len(group),
            "visual_evidence_used_rate": _mean(group["visual_evidence_used"]),
            "visual_page_bbox_verified_rate": _mean(group["visual_page_bbox_verified"]),
            "visual_target_locator_verified_rate": _mean(group["visual_target_locator_verified"]),
            "answer_fact_coverage": _mean(group["fact_coverage"]),
            "fact_full_pass_rate": _mean(group["facts_pass"]),
            "compatible_score": _mean(group["compatible_score"]),
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summarize-only", action="store_true")
    args = parser.parse_args()
    result_path = args.output_dir / "visual_golden_results.csv"
    summary_path = args.output_dir / "visual_summary.json"
    if args.summarize_only:
        result = _add_provenance_columns(pd.read_csv(result_path))
        result.to_csv(result_path, index=False, encoding="utf-8-sig")
        summary = _build_summary(result)
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY_missing")

    from openai import OpenAI

    golden = load_golden_set_v3()
    golden = golden[golden["source_lane"] == "visual"].reset_index(drop=True)
    evidence_by_case = _load_evidence(args.evidence)
    chunks = load_chunks()
    if chunks is None:
        raise RuntimeError("output_chunks_missing")
    index = HybridIndex(chunks)
    doc_meta: list[tuple[str, str]] = []
    seen: set[str] = set()
    for chunk in chunks:
        if chunk.doc_id not in seen:
            seen.add(chunk.doc_id)
            doc_meta.append((chunk.doc_id, str((chunk.metadata or {}).get("발주_기관", ""))))

    base_client = OpenAI()
    rows: list[dict[str, Any]] = []
    for seq, (_, item) in enumerate(golden.iterrows(), start=1):
        case_id = str(item["id"])
        visual = evidence_by_case.get(case_id, {})
        evidence_text = str(visual.get("evidence_text") or "")
        expected = set(item["expected_doc_id"])
        evidence_doc = str(visual.get("doc_id") or next(iter(expected), ""))
        refs = visual.get("evidence_refs") or []
        verified_refs = [ref for ref in refs if ref.get("provenance_level") == "page_bbox_verified"]
        locator_refs = [
            ref
            for ref in refs
            if ref.get("provenance_level")
            in {"page_bbox_verified", "gold_target_object_hash_verified"}
        ]
        if verified_refs:
            pages = sorted({int(ref["page"]) for ref in verified_refs})
            citation_label = f"{visual.get('evidence_id', 'visual-evidence')}, page={pages}"
        else:
            citation_label = (
                f"{visual.get('evidence_id', 'visual-evidence')}, "
                "HWP document candidate; page/bbox unverified"
            )
        client = InjectingOpenAI(base_client, evidence_text, evidence_doc, citation_label)
        answer = None
        error = None
        try:
            answer = ask_rfp_v9(str(item["query"]), client, index, chunks, doc_meta)
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
        context = _extract_context(client.last_prompt)
        context_docs = _context_doc_ids(context)
        context_set = set(context_docs)
        context_matched, context_total = check_required_facts(context, item.get("required_fact_groups"))
        fact_matched, fact_total = check_required_facts(answer or "", item.get("required_fact_groups"))
        citation_matched, citation_total = compute_citation_coverage(answer or "", expected)
        expected_abstention = item.get("decision") == "abstain"
        abstention_match = _is_abstention(answer) == expected_abstention
        fact_coverage = fact_matched / fact_total if fact_total else None
        rows.append(
            {
                "version": VERSION,
                "id": case_id,
                "evidence_type": "figure" if case_id.find("figure") >= 0 else "table",
                "query": item["query"],
                "expected_doc_ids": " | ".join(sorted(expected)),
                "context_doc_ids": " | ".join(context_docs),
                "retrieval_recall": len(context_set & expected) / len(expected) if expected else None,
                "visual_evidence_used": bool(evidence_text),
                "visual_evidence_id": visual.get("evidence_id"),
                "visual_page_bbox_verified": bool(verified_refs),
                "visual_target_locator_verified": bool(locator_refs),
                "visual_evidence_refs": json.dumps(refs, ensure_ascii=False),
                "visual_evidence_text": evidence_text,
                "context_fact_coverage": context_matched / context_total if context_total else None,
                "generated_answer": answer,
                "generation_error": error,
                "fact_coverage": fact_coverage,
                "facts_pass": fact_matched == fact_total if fact_total else None,
                "citation_coverage": citation_matched / citation_total if citation_total else None,
                "abstention_match": abstention_match,
                "compatible_score": 100.0 if expected_abstention and abstention_match else (
                    fact_coverage * 100 if not expected_abstention and fact_coverage is not None else 0.0
                ),
            }
        )
        args.output_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(result_path, index=False, encoding="utf-8-sig")
        print(f"[{seq}/{len(golden)}] {case_id}")

    result = pd.DataFrame(rows)
    summary = _build_summary(result)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
