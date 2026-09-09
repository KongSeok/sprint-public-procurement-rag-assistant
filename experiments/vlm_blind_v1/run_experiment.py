"""Golden Set v3.1 + blind visual retrieval 통합 실험 실행기.

검색기와 생성기 구현은 변경하지 않는다. 기존 HybridIndex의 검색 결과에서만
시각 후보를 만들고, Golden Set의 정답 문서/page/bbox/hash를 VLM에 전달하지
않은 상태로 시각 근거를 생성한 뒤 기존 ``ask_rfp_v9``에 보조 컨텍스트로 넣는다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 검색 임베딩은 CPU, 로컬 VLM 서버는 별도 프로세스의 GPU를 사용한다.
# sentence-transformers/torch import보다 먼저 설정해야 한다.
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

import pandas as pd
from openai import OpenAI

from experiments.vlm_blind_v1.visual_retrieval import (
    ArchiveIndex,
    VISUAL_MODEL,
    build_visual_candidates,
    retrieve_candidate_doc_ids,
    select_and_read_visual_evidence,
)
from src.evaluation.document_ids import extract_context_doc_ids
from src.evaluation.golden_set_v3_1 import (
    GOLDEN_PATCH_VERSION,
    load_golden_set_v3_1,
)
from src.evaluation.scoring_v3 import scorer_v3_1 as scorer


ROOT = Path(__file__).resolve().parents[2]
GENERATION_MODEL = os.environ.get("GENERATION_MODEL", "gpt-5-mini")
GENERATION_SOURCE_COMMIT = "9c4429ee0963c76d1a08bfc06528e0c1349cb3c9"
VISUAL_BASE_URL = os.environ.get("VLM_BASE_URL", "http://127.0.0.1:8003/v1")
_CONTEXT_MARKER = "## 컨텍스트 (검색된 문서 조각)"
_QUESTION_MARKER = "## 질문"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, default=str) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _git_head() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except Exception:
        return None


def _extract_context(prompt: str) -> str:
    if _CONTEXT_MARKER not in prompt:
        return ""
    body = prompt.split(_CONTEXT_MARKER, 1)[1]
    return body.split(_QUESTION_MARKER, 1)[0].strip()


def _cited_doc_ids(answer: str | None) -> list[str]:
    match = re.search(r"^\[\s*근거\s*:\s*(.*)\]\s*$", str(answer or ""), re.MULTILINE)
    if not match:
        return []
    return [value.strip() for value in match.group(1).split(",") if value.strip()]


def _retrieval_recall(expected: list[str], retrieved: list[str]) -> float | None:
    expected_set = set(expected or [])
    if not expected_set:
        return None
    return len(expected_set.intersection(retrieved)) / len(expected_set)


def _context_fact_coverage(row: dict[str, Any], context: str) -> float | None:
    groups = scorer._BASE.fact_groups(row)
    if not groups or not context:
        return None
    matched = sum(
        any(scorer.option_matches(context, option) for option in group) for group in groups
    )
    return matched / len(groups)


def _visual_context(payload: dict[str, Any] | None) -> str:
    if not payload or not payload.get("evidence_text"):
        return ""
    doc_ids = list(
        dict.fromkeys(str(row["doc_id"]) for row in payload.get("selected", []))
    )
    headers = "\n".join(f"[문서: {doc_id}]" for doc_id in doc_ids)
    return (
        "\n\n## 시각 판독 보조 근거\n"
        f"{headers}\n{payload['evidence_text']}\n"
        "위 내용은 검색된 문서 안의 시각 후보를 판독한 결과이며, 원문에 보이는 "
        "내용만 답변 근거로 사용하세요."
    )


class _CapturingCompletions:
    def __init__(self, base: Any, evidence: str):
        self.base = base
        self.evidence = evidence
        self.last_prompt = ""

    def create(self, *args: Any, **kwargs: Any) -> Any:
        messages = kwargs.get("messages") or []
        if messages:
            messages = [dict(message) for message in messages]
            final = dict(messages[-1])
            if isinstance(final.get("content"), str):
                final["content"] += self.evidence
            messages[-1] = final
            kwargs["messages"] = messages
            self.last_prompt = str(final.get("content", ""))
        return self.base.create(*args, **kwargs)


class _CapturingClient:
    def __init__(self, base: OpenAI, evidence: str):
        class Chat:
            pass

        self.chat = Chat()
        self.chat.completions = _CapturingCompletions(base.chat.completions, evidence)


def _visual_stage(
    golden_rows: list[dict[str, Any]],
    index: Any,
    archive_path: Path,
    output_dir: Path,
) -> dict[str, dict[str, Any]]:
    evidence_path = output_dir / "visual_evidence.jsonl"
    completed = {str(row["id"]): row for row in _read_jsonl(evidence_path)}
    archive = ArchiveIndex(archive_path)
    visual_rows = [row for row in golden_rows if str(row.get("source_lane")) == "visual"]
    for number, row in enumerate(visual_rows, start=1):
        case_id = str(row["id"])
        if case_id in completed:
            continue
        started = time.perf_counter()
        candidate_docs = retrieve_candidate_doc_ids(index, str(row["query"]), k=6)
        candidate_root = output_dir / "visual_candidates" / case_id
        candidates, missing = build_visual_candidates(
            archive, candidate_docs, str(row["query"]), candidate_root
        )
        try:
            payload = select_and_read_visual_evidence(
                str(row["query"]), candidates, candidate_root, base_url=VISUAL_BASE_URL
            )
        except Exception as exc:
            payload = {
                "evidence_text": "",
                "selected": [],
                "error": f"{type(exc).__name__}: {exc}",
                "gold_locator_used": False,
            }
        payload.update(
            {
                "id": case_id,
                "candidate_doc_ids": candidate_docs,
                "missing_archive_doc_ids": missing,
                "elapsed_seconds": round(time.perf_counter() - started, 3),
            }
        )
        if payload.get("gold_locator_used") is not False:
            raise RuntimeError(f"{case_id}: gold locator 차단 검증 실패")
        _append_jsonl(evidence_path, payload)
        completed[case_id] = payload
        print(
            f"[VLM {number:02d}/{len(visual_rows)}] {case_id}: "
            f"선택 {len(payload.get('selected', []))}개"
        )
    return completed


def _generation_stage(
    golden_rows: list[dict[str, Any]],
    index: Any,
    chunks: list[Any],
    visual_by_id: dict[str, dict[str, Any]],
    output_dir: Path,
) -> list[dict[str, Any]]:
    from experiments.dahye_latest_20260909.answer_generation import ask_rfp_v9

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY가 없습니다.")
    child_chunks = [chunk for chunk in chunks if getattr(chunk, "strategy", "") != "parent"]
    doc_to_biz: dict[str, str] = {}
    for chunk in chunks:
        metadata = getattr(chunk, "metadata", {}) or {}
        business_name = metadata.get("사업명") or metadata.get("사업_명") or ""
        doc_to_biz.setdefault(str(chunk.doc_id), str(business_name))
    catalog = sorted(doc_to_biz.items())

    predictions_path = output_dir / "inference.jsonl"
    completed = {
        str(row["id"]): row
        for row in _read_jsonl(predictions_path)
        if row.get("id") and not row.get("execution_error")
    }
    base_client = OpenAI(api_key=api_key)
    for number, row in enumerate(golden_rows, start=1):
        case_id = str(row["id"])
        if case_id in completed:
            continue
        evidence = _visual_context(visual_by_id.get(case_id))
        client = _CapturingClient(base_client, evidence)
        started = time.perf_counter()
        answer = None
        error = None
        try:
            answer = ask_rfp_v9(
                str(row["query"]), client, index, child_chunks, catalog,
                model_name=GENERATION_MODEL,
            )
            if answer == "(답변 생성 실패)":
                error = "answer_generation_returned_failure"
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        context = _extract_context(client.chat.completions.last_prompt)
        retrieved = extract_context_doc_ids(context)
        if not retrieved:
            retrieved = _cited_doc_ids(answer)
        prediction = {
            "id": case_id,
            "answer": answer,
            "execution_error": error,
            "retrieved_doc_ids": retrieved,
            "retrieval_recall": _retrieval_recall(
                row.get("expected_doc_id") or [], retrieved
            ),
            "context_fact_coverage": _context_fact_coverage(row, context),
            "visual_evidence_used": bool(evidence),
            "visual_evidence_id": (visual_by_id.get(case_id) or {}).get("evidence_id"),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
        _append_jsonl(predictions_path, prediction)
        if not error:
            completed[case_id] = prediction
        print(f"[생성 {number:02d}/{len(golden_rows)}] {case_id}: {'오류' if error else '완료'}")

    all_attempts = _read_jsonl(predictions_path)
    final_by_id: dict[str, dict[str, Any]] = {}
    for prediction in all_attempts:
        case_id = str(prediction.get("id", ""))
        if case_id and (case_id not in final_by_id or not prediction.get("execution_error")):
            final_by_id[case_id] = prediction
    return [final_by_id[str(row["id"])] for row in golden_rows if str(row["id"]) in final_by_id]


def run(archive_path: Path, run_id: str) -> Path:
    os.chdir(ROOT)
    from src.data_processing.chunking import load_chunks
    from src.retrieval.embeddings import SentenceTransformerEmbedding
    from src.retrieval.indexing import HybridIndex

    output_dir = ROOT / "output" / "vlm_blind_v3_1_runs" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    chunks = load_chunks()
    if not chunks:
        raise RuntimeError("output/chunks.pkl을 읽지 못했습니다.")
    corpus_ids = {str(chunk.doc_id) for chunk in chunks}
    golden = load_golden_set_v3_1(corpus_doc_ids=corpus_ids)
    golden_rows = golden.to_dict("records")

    manifest = {
        "run_id": run_id,
        "develop_head": _git_head(),
        "generation_model": GENERATION_MODEL,
        "generation_source_commit": GENERATION_SOURCE_COMMIT,
        "scorer_version": scorer.SCORER_VERSION,
        "golden_patch_version": GOLDEN_PATCH_VERSION,
        "visual_model": VISUAL_MODEL,
        "visual_base_url": VISUAL_BASE_URL,
        "visual_candidate_source": "existing_hybrid_index_top_documents",
        "gold_document_locator_used": False,
        "archive_sha256": _sha256(archive_path),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(output_dir / "manifest.json", manifest)

    print(f"chunk {len(chunks):,}개, 문서 {len(corpus_ids)}개, 골든셋 {len(golden_rows)}문항")
    backend = SentenceTransformerEmbedding()
    if backend.name != "nlpai-lab/KURE-v1":
        raise RuntimeError(f"KURE-v1이 아닌 임베딩 백엔드입니다: {backend.name}")
    index = HybridIndex(chunks, persist=True, embedding_backend=backend)
    visual_by_id = _visual_stage(golden_rows, index, archive_path, output_dir)
    predictions = _generation_stage(golden_rows, index, chunks, visual_by_id, output_dir)
    details, summary = scorer.evaluate(golden_rows, predictions)
    summary.update(manifest)
    summary["visual_question_count"] = sum(
        str(row.get("source_lane")) == "visual" for row in golden_rows
    )
    summary["visual_evidence_used_count"] = sum(
        bool(row.get("visual_evidence_used")) for row in predictions
    )
    scorer.write_jsonl(output_dir / "scored_details.jsonl", details)
    pd.DataFrame(details).to_csv(
        output_dir / "scored_details.csv", index=False, encoding="utf-8-sig"
    )
    _write_json(output_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    print(f"\n결과 폴더: {output_dir}")
    return output_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument(
        "--run-id",
        default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    run(arguments.archive.expanduser().resolve(), arguments.run_id)
