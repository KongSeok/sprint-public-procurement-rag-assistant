from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from midprojectrag.evaluation import dataset_sha256
from midprojectrag.ingest.common import sha256_file, sha256_text


MANIFEST_HASH = "a" * 64
CONFIG_HASH = "c" * 64
METRICS_CONFIG_PATH = Path(__file__).resolve().parents[2] / "evaluation" / "config" / "metrics.json"


def scoring_kwargs() -> dict[str, Any]:
    return {
        "config": json.loads(METRICS_CONFIG_PATH.read_text(encoding="utf-8")),
        "scoring_config_sha256": sha256_file(METRICS_CONFIG_PATH),
    }


def _doc_id(number: int) -> str:
    return f"doc_{number:024x}"


def _block_id(number: int) -> str:
    return f"block_{number:024x}"


def make_case(task_type: str, *, split: str = "dev", number: int = 1) -> dict[str, Any]:
    aliases = {
        "single_doc": "single",
        "multi_doc_compare": "multi",
        "follow_up": "followup",
        "unknown": "unknown",
    }
    split_offset = 0 if split == "dev" else 1000
    doc_one = _doc_id(split_offset + number * 10 + 1)
    doc_two = _doc_id(split_offset + number * 10 + 2)
    block_one = _block_id(split_offset + number * 10 + 1)
    block_two = _block_id(split_offset + number * 10 + 2)
    required_docs = [] if task_type == "unknown" else [doc_one]
    evidence: list[dict[str, str]] = []
    if task_type != "unknown":
        evidence.append(
            {
                "doc_id": doc_one,
                "source_block_id": block_one,
                "locator_hash": sha256_text(f"locator-{split}-{number}-one"),
            }
        )
    axes: list[str] = []
    if task_type == "multi_doc_compare":
        required_docs.append(doc_two)
        evidence.append(
            {
                "doc_id": doc_two,
                "source_block_id": block_two,
                "locator_hash": sha256_text(f"locator-{split}-{number}-two"),
            }
        )
        axes = ["budget"]
    history: list[dict[str, Any]] = []
    conversation: dict[str, Any] | None = None
    if task_type == "follow_up":
        history = [
            {"turn_id": f"turn-{split}-{number}-1", "role": "user", "content": "prior question"},
            {
                "turn_id": f"turn-{split}-{number}-2",
                "role": "assistant",
                "content": "prior answer",
                "cited_doc_ids": [doc_one],
            },
        ]
        conversation = {
            "conversation_id": f"conversation-{split}-{number}",
            "turn_index": 3,
            "depends_on_turn_ids": [f"turn-{split}-{number}-2"],
        }
    decision = "abstain" if task_type == "unknown" else "answer"
    key_points = [] if task_type == "unknown" else [{"point_id": f"kp_{split}_{number}", "text": "required point"}]
    return {
        "schema_version": "1.0",
        "case_id": f"{split}-{aliases[task_type]}-{number:03d}",
        "group_id": f"group-{split}-{aliases[task_type]}-{number}",
        "split": split,
        "task_type": task_type,
        "question": f"synthetic {split} {task_type} question {number}",
        "history": history,
        "document_scope": {"mode": "all", "doc_ids": []},
        "conversation": conversation,
        "gold": {
            "decision": decision,
            "reference_answer": None if task_type == "unknown" else "synthetic reference",
            "required_key_points": key_points,
            "required_doc_ids": required_docs,
            "evidence_refs": evidence,
            "comparison_axes": axes,
            "abstain_reason": "insufficient_evidence" if task_type == "unknown" else None,
        },
        "difficulty": "medium",
        "tags": ["synthetic"],
        "source_manifest_sha256": MANIFEST_HASH,
        "review": {"author": "author", "reviewer": "reviewer", "status": "approved"},
    }


def make_cases(split: str = "dev") -> list[dict[str, Any]]:
    return [
        make_case("single_doc", split=split, number=1),
        make_case("multi_doc_compare", split=split, number=2),
        make_case("follow_up", split=split, number=3),
        make_case("unknown", split=split, number=4),
    ]


def make_scoring_cases(split: str = "dev") -> list[dict[str, Any]]:
    per_task = 10 if split == "dev" else 5
    return [
        make_case(task_type, split=split, number=number)
        for task_type in ("single_doc", "multi_doc_compare", "follow_up", "unknown")
        for number in range(1, per_task + 1)
    ]


def make_response(case: dict[str, Any]) -> dict[str, Any]:
    if case["gold"]["decision"] == "abstain":
        return {
            "schema_version": "1.0",
            "request_id": f"req-{case['case_id']}",
            "status": "abstained",
            "answer": "제공된 문서에서 답변 근거를 찾지 못했습니다.",
            "citations": [],
            "abstention": {"reason": "insufficient_evidence", "detail": "No supporting source block was retrieved."},
            "error": None,
            "trace_id": f"trace-{case['case_id']}",
        }
    citations = []
    for reference in case["gold"]["evidence_refs"]:
        citations.append(
            {
                "doc_id": reference["doc_id"],
                "chunk_id": f"chunk_{reference['source_block_id'][-24:]}",
                "source_block_ids": [reference["source_block_id"]],
                "locator": {"section_path": ["synthetic"], "page_start": 1, "page_end": 1},
            }
        )
    return {
        "schema_version": "1.0",
        "request_id": f"req-{case['case_id']}",
        "status": "answered",
        "answer": "synthetic grounded answer",
        "citations": citations,
        "abstention": None,
        "error": None,
        "trace_id": f"trace-{case['case_id']}",
    }


def make_runs(cases: list[dict[str, Any]], *, stack_id: str = "api") -> list[dict[str, Any]]:
    eval_hash = dataset_sha256(cases)
    runs: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        retrieval = []
        for rank, reference in enumerate(case["gold"]["evidence_refs"], start=1):
            retrieval.append(
                {
                    "rank": rank,
                    "doc_id": reference["doc_id"],
                    "chunk_id": f"chunk_{reference['source_block_id'][-24:]}",
                    "source_block_ids": [reference["source_block_id"]],
                    "score": 1.0 - rank / 100,
                }
            )
        matched_points = [point["point_id"] for point in case["gold"]["required_key_points"]]
        runs.append(
            {
                "schema_version": "1.0",
                "run_id": f"run-{stack_id}-{index}",
                "case_id": case["case_id"],
                "stack_id": stack_id,
                "corpus_manifest_sha256": MANIFEST_HASH,
                "eval_set_sha256": eval_hash,
                "config_sha256": CONFIG_HASH,
                "git_commit": "abcdef0",
                "generator_model": "gpt-5-mini" if stack_id == "api" else "synthetic-hf-generator",
                "embedding_model": "text-embedding-3-small" if stack_id == "api" else "synthetic-hf-embedding",
                **({"reasoning_effort": "minimal"} if stack_id == "api" else {}),
                "environment": {
                    "python_version": "3.12.13",
                    "platform": "synthetic-test",
                    "region": "us-central1" if stack_id == "gcp_local" else "local-test",
                    "machine_type": "g2-standard-4" if stack_id == "gcp_local" else "synthetic-test",
                    "vcpu": 4,
                    "ram_gb": 16.0,
                    "gpu_model": "NVIDIA L4" if stack_id == "gcp_local" else None,
                    "disk_gb": 100.0,
                    "dependency_lock_sha256": "d" * 64,
                },
                "retrieval": retrieval,
                "response": make_response(case),
                "timing_ms": {"retrieval": 10.0, "generation": 20.0, "total": float(index * 10)},
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "embedding_tokens": 4,
                    "cost_usd": 0.01 if stack_id == "api" else None,
                    "gpu_seconds": 0.5 if stack_id == "gcp_local" else None,
                    "peak_vram_gb": 1.0 if stack_id == "gcp_local" else None,
                },
                "judgment": {
                    "matched_key_point_ids": matched_points,
                    "correctness": None if case["task_type"] == "unknown" else 1.0,
                    "faithfulness": None if case["task_type"] == "unknown" else 1.0,
                    "factual_claim_coverage": None if case["task_type"] == "unknown" else 1.0,
                    "citation_validity": None if case["task_type"] == "unknown" else 1.0,
                    "follow_up_success": True if case["task_type"] == "follow_up" else None,
                    "safe_abstention": True if case["task_type"] == "unknown" else None,
                    "reviewer_ids": ["reviewer-a", "reviewer-b"],
                },
                "seed": 7,
                "temperature": 0.0,
                "cache_hit": False,
            }
        )
    return runs
