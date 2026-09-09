"""최신 생성 스냅샷(9c4429e)으로 골든셋 79문항을 생성하고 채점한다.

GCP 레포 루트에서 실행:
    python experiments/dahye_latest_20260909/run_golden_v3_latest.py

성공한 문항은 즉시 inference.jsonl에 저장한다. 같은 RUN_ID로 다시 실행하면
성공 문항은 건너뛰고 오류 문항만 재시도한다.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

import pandas as pd
from openai import OpenAI


ROOT = Path(__file__).resolve().parents[2]
RUN_ID = os.environ.get("RUN_ID", "dahye-latest-9c4429e-v1")
MODEL = os.environ.get("GENERATION_MODEL", "gpt-5-mini")
OUT_DIR = ROOT / "output" / "dahye_latest_runs" / RUN_ID
PREDICTIONS_PATH = OUT_DIR / "inference.jsonl"
DETAILS_PATH = OUT_DIR / "scored_details.jsonl"
DETAILS_CSV_PATH = OUT_DIR / "scored_details.csv"
SUMMARY_PATH = OUT_DIR / "summary.json"
MANIFEST_PATH = OUT_DIR / "manifest.json"
SOURCE_COMMIT = "9c4429ee0963c76d1a08bfc06528e0c1349cb3c9"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"모듈을 불러올 수 없습니다: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git_head() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except Exception:
        return None


def manifest() -> dict[str, Any]:
    scorer_path = ROOT / "scoring_v3" / "evaluate_golden_testset_v3.py"
    base_path = ROOT / "scoring_v3" / "_scorer_v2_base.py"
    generation_path = Path(__file__).with_name("answer_generation.py")
    prompts_path = Path(__file__).with_name("generation_prompts.py")
    golden_dir = ROOT / "data" / "golden_set_v3"
    tracked = [
        scorer_path,
        base_path,
        generation_path,
        prompts_path,
        golden_dir / "rag-56.draft.jsonl",
        golden_dir / "set-13.draft.jsonl",
        golden_dir / "document-structure-visual-qa.jsonl",
        ROOT / "output" / "chunks.pkl",
    ]
    missing = [str(path) for path in tracked if not path.exists()]
    if missing:
        raise FileNotFoundError("필수 파일이 없습니다:\n- " + "\n- ".join(missing))
    return {
        "run_id": RUN_ID,
        "model": MODEL,
        "source_branch_commit": SOURCE_COMMIT,
        "develop_head": git_head(),
        "files": {str(path.relative_to(ROOT)): sha256_file(path) for path in tracked},
    }


class CapturingCompletions:
    def __init__(self, base):
        self.base = base
        self.last_prompt = ""

    def create(self, *args, **kwargs):
        messages = kwargs.get("messages") or []
        self.last_prompt = str(messages[-1].get("content", "")) if messages else ""
        return self.base.create(*args, **kwargs)


class CapturingChat:
    def __init__(self, base):
        self.completions = CapturingCompletions(base.completions)


class CapturingClient:
    def __init__(self, base):
        self.chat = CapturingChat(base.chat)


def extract_context(prompt: str) -> str:
    marker = "## 컨텍스트 (검색된 문서 조각)"
    if marker not in prompt:
        return ""
    body = prompt.split(marker, 1)[1]
    return body.split("## 질문", 1)[0].strip()


def cited_doc_ids(answer: str) -> list[str]:
    match = re.search(r"\[\s*근거\s*:\s*(.+?)\]\s*$", str(answer), re.DOTALL)
    if not match:
        return []
    return [part.strip() for part in match.group(1).split(",") if part.strip()]


def context_doc_ids(context: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"\[문서:\s*(.+?)\]", context)))


def context_fact_coverage(scorer, row: dict[str, Any], context: str) -> float | None:
    groups = scorer._BASE.fact_groups(row)
    if not groups or not context:
        return None
    matched = sum(any(scorer.option_matches(context, option) for option in group) for group in groups)
    return matched / len(groups)


def retrieval_recall(expected: list[str], retrieved: list[str]) -> float | None:
    expected_set = set(expected or [])
    if not expected_set:
        return None
    return len(expected_set & set(retrieved)) / len(expected_set)


def main() -> None:
    os.chdir(ROOT)
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY가 없습니다. Jupyter 터미널에서 먼저 설정하세요.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    current_manifest = manifest()
    if MANIFEST_PATH.exists():
        old_manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        if old_manifest != current_manifest:
            raise RuntimeError(
                f"{RUN_ID}의 기존 실행 조건과 현재 조건이 다릅니다. "
                "RUN_ID를 새 값으로 바꿔 실행하세요."
            )
    else:
        write_json(MANIFEST_PATH, current_manifest)

    from experiments.dahye_latest_20260909.answer_generation import ask_rfp_v9
    from src.data_processing.chunking import load_chunks
    from src.evaluation.golden_set_v3 import load_golden_set_v3
    from src.retrieval.indexing import HybridIndex

    scorer = load_module(
        ROOT / "scoring_v3" / "evaluate_golden_testset_v3.py", "scorer_v3_0_1"
    )
    if scorer.SCORER_VERSION != "3.0.1":
        raise RuntimeError(f"채점기 버전이 3.0.1이 아닙니다: {scorer.SCORER_VERSION}")

    chunks = load_chunks()
    if not chunks:
        raise RuntimeError("output/chunks.pkl을 읽지 못했습니다.")
    child_chunks = [chunk for chunk in chunks if getattr(chunk, "strategy", "") != "parent"]
    corpus_doc_ids = {chunk.doc_id for chunk in chunks}
    golden = load_golden_set_v3(corpus_doc_ids=corpus_doc_ids)
    golden_rows = golden.to_dict("records")

    doc_to_biz: dict[str, str] = {}
    for chunk in chunks:
        meta = getattr(chunk, "metadata", {}) or {}
        biz = meta.get("사업명") or meta.get("사업_명") or ""
        doc_to_biz.setdefault(chunk.doc_id, str(biz))
    all_filenames_with_biz = sorted(doc_to_biz.items())

    print(f"chunk {len(chunks):,}개, 문서 {len(corpus_doc_ids)}개, 골든셋 {len(golden_rows)}문항")
    print("Chroma DB를 여는 중입니다. 기존 컬렉션이 맞으면 재사용됩니다.")
    index = HybridIndex(chunks, persist=True)
    client = CapturingClient(OpenAI())

    prior_rows = read_jsonl(PREDICTIONS_PATH)
    completed = {
        str(row.get("id")): row
        for row in prior_rows
        if row.get("id") and not row.get("execution_error")
    }
    if completed:
        print(f"안전 재개: 성공한 {len(completed)}문항은 건너뜁니다.")

    for number, row in enumerate(golden_rows, start=1):
        item_id = str(row["id"])
        if item_id in completed:
            continue
        client.chat.completions.last_prompt = ""
        started = time.perf_counter()
        answer = None
        error = None
        try:
            answer = ask_rfp_v9(
                row["query"], client, index, child_chunks, all_filenames_with_biz,
                model_name=MODEL,
            )
            if answer == "(답변 생성 실패)":
                error = "answer_generation_returned_failure"
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        context = extract_context(client.chat.completions.last_prompt)
        retrieved = context_doc_ids(context)
        if not retrieved and answer:
            retrieved = cited_doc_ids(answer)
        prediction = {
            "id": item_id,
            "answer": answer,
            "execution_error": error,
            "retrieved_doc_ids": retrieved,
            "retrieval_recall": retrieval_recall(row.get("expected_doc_id") or [], retrieved),
            "context_fact_coverage": context_fact_coverage(scorer, row, context),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
        append_jsonl(PREDICTIONS_PATH, prediction)
        if not error:
            completed[item_id] = prediction
        print(f"[{number:02d}/{len(golden_rows)}] {item_id}: {'오류' if error else '완료'}")

    # 같은 ID의 재시도 기록이 있으면 마지막 성공 결과를 우선한다.
    final_by_id: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(PREDICTIONS_PATH):
        item_id = str(row.get("id", ""))
        if not item_id:
            continue
        if item_id not in final_by_id or not row.get("execution_error"):
            final_by_id[item_id] = row
    predictions = [final_by_id[str(row["id"])] for row in golden_rows if str(row["id"]) in final_by_id]
    details, summary = scorer.evaluate(golden_rows, predictions)
    summary.update({
        "run_id": RUN_ID,
        "generation_model": MODEL,
        "generation_source_commit": SOURCE_COMMIT,
        "output_directory": str(OUT_DIR),
    })
    scorer.write_jsonl(DETAILS_PATH, details)
    pd.DataFrame(details).to_csv(DETAILS_CSV_PATH, index=False, encoding="utf-8-sig")
    write_json(SUMMARY_PATH, summary)
    print("\n실험 완료")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n결과 폴더: {OUT_DIR}")


if __name__ == "__main__":
    main()
