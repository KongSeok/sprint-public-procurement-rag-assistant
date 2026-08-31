from __future__ import annotations

import hashlib
import csv
import json
from pathlib import Path
from typing import Any

from midprojectrag.supplemental_evaluation import (
    REQUIRED_CORRECTION_IDS,
    canonical_json,
    dataset_sha256,
)


SHA_A = "a" * 64
SNAPSHOT_ID = "snapshot_synthetic"


def doc_id(index: int) -> str:
    return f"doc_{index:024x}"


def block_id(index: int) -> str:
    return f"block_{index:024x}"


def source_sha(index: int) -> str:
    return hashlib.sha256(f"synthetic-source-{index}".encode()).hexdigest()


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(canonical_json(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def make_answer_case(
    index: int,
    *,
    lane: str = "qa_regression",
    status: str = "draft",
    manifest_sha256: str = SHA_A,
) -> dict[str, Any]:
    document_id = doc_id(index + 1)
    approved = status == "approved"
    case = {
        "schema_version": "1.0",
        "case_id": f"supplemental-{'qa' if lane == 'qa_regression' else 'alignment'}-x{index:03d}",
        "legacy_id": f"X{index:03d}",
        "profile": "supplemental",
        "lane": lane,
        "task_type": "single_doc",
        "question": f"synthetic question {index}",
        "difficulty": "medium",
        "source_manifest_sha256": manifest_sha256,
        "source_sha256s": [source_sha(index + 1)],
        "scope_doc_ids": [document_id],
        "required_doc_ids": [document_id],
        "gold": {
            "decision": "answer",
            "reference_answer": f"synthetic answer {index}",
            "required_fact_groups": [[f"synthetic fact {index}"]],
            "abstain_reason": None,
            "comparison_axes": [],
        },
        "evidence_refs": [],
        "absence_scope_doc_ids": [],
        "legacy_evidence_note": f"synthetic evidence note {index}",
        "legacy_scoring_notes": None,
        "source_labels": [f"synthetic-{index}.hwp"],
        "supporting_sources": ["synthetic.csv"],
        "supporting_refs": [],
        "reviewed_draft_sha256": SHA_A if approved else None,
        "review": {
            "author": "fixture-author",
            "reviewer": "fixture-reviewer" if approved else None,
            "status": status,
            "reviewed_at": "2026-08-31T01:00:00Z" if approved else None,
        },
        "enabled": approved,
        "tags": [f"legacy-id:X{index:03d}"],
    }
    if approved:
        case["evidence_refs"] = [
            {
                "doc_id": document_id,
                "source_block_id": block_id(index + 1),
                "page": 1,
                "locator_hash": hashlib.sha256(
                    f"section:synthetic/{index}".encode()
                ).hexdigest(),
            }
        ]
    return case


def make_set_case(
    index: int,
    *,
    required_doc_ids: list[str] | None = None,
    status: str = "draft",
    manifest_sha256: str = SHA_A,
) -> dict[str, Any]:
    targets = required_doc_ids or [doc_id(1000 + index)]
    approved = status == "approved"
    return {
        "schema_version": "1.0",
        "case_id": f"supplemental-set-s{index:03d}",
        "legacy_id": f"S{index:03d}",
        "profile": "supplemental",
        "subtype": "list_condition",
        "question": f"synthetic set question {index}",
        "difficulty": "hard",
        "source_manifest_sha256": manifest_sha256,
        "source_sha256s": [source_sha(1000 + index + offset) for offset in range(len(targets))],
        "required_doc_ids": targets,
        "expected_count": len(targets),
        "required_fact_groups": [[f"synthetic set fact {index}"]],
        "set_definition": {
            "snapshot_id": SNAPSHOT_ID,
            "manifest_sha256": manifest_sha256,
            "description": "synthetic set definition",
        },
        "legacy_scoring_notes": None,
        "source_labels": [f"synthetic-set-{index}.hwp"],
        "supporting_sources": ["synthetic.csv"],
        "reviewed_draft_sha256": SHA_A if approved else None,
        "review": {
            "author": "fixture-author",
            "reviewer": "fixture-reviewer" if approved else None,
            "status": status,
            "reviewed_at": "2026-08-31T01:00:00Z" if approved else None,
        },
        "enabled": approved,
        "tags": [f"legacy-id:S{index:03d}", "subtype:list_condition"],
    }


def make_draft_suites() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    answers = [make_answer_case(index) for index in range(44)]
    answers.extend(
        make_answer_case(index, lane="answer_alignment")
        for index in range(44, 56)
    )
    sets = [make_set_case(index) for index in range(13)]
    return answers, sets


def make_set_run(
    case: dict[str, Any],
    returned_doc_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "case_id": case["case_id"],
        "eval_set_sha256": "",
        "returned_doc_ids": (
            list(case["required_doc_ids"])
            if returned_doc_ids is None
            else list(returned_doc_ids)
        ),
        "error": None,
    }


def make_answer_run(
    case: dict[str, Any],
    *,
    status: str = "answered",
    config_sha256: str = SHA_A,
) -> dict[str, Any]:
    if status == "answered":
        answer = case["gold"]["reference_answer"] or "synthetic answer"
        cited_doc_ids = list(case["required_doc_ids"])
        error = None
    elif status == "abstained":
        answer = ""
        cited_doc_ids = []
        error = None
    else:
        answer = ""
        cited_doc_ids = []
        error = {"code": "synthetic_failure"}
    return {
        "schema_version": "1.0",
        "case_id": case["case_id"],
        "eval_set_sha256": "",
        "config_sha256": config_sha256,
        "status": status,
        "answer": answer,
        "retrieved_doc_ids": list(case["scope_doc_ids"]),
        "cited_doc_ids": cited_doc_ids,
        "timing_ms": {"retrieval": 10.0, "generation": 20.0, "total": 30.0},
        "usage": {
            "embedding_tokens": 10,
            "input_tokens": 20,
            "output_tokens": 30,
            "cost_usd": 0.001,
        },
        "cache_hit": False,
        "error": error,
    }


def attach_eval_hash(cases: list[dict[str, Any]], runs: list[dict[str, Any]]) -> None:
    value = dataset_sha256(cases)
    for run in runs:
        run["eval_set_sha256"] = value


def create_preparation_fixture(root: Path) -> dict[str, Any]:
    required_without_b14 = sorted(REQUIRED_CORRECTION_IDS - {"B14"})
    qa_ids = required_without_b14 + [
        f"Q{index:03d}" for index in range(1, 45 - len(required_without_b14))
    ]
    set_ids = ["B14", *[f"S{index:03d}" for index in range(1, 13)]]
    alignment_ids = [f"A{index:03d}" for index in range(1, 13)]
    selected_ids = [*qa_ids, *set_ids, *alignment_ids]
    unused_ids = [f"U{index:03d}" for index in range(1, 136 - len(selected_ids) + 1)]
    all_ids = [*selected_ids, *unused_ids]
    assert len(all_ids) == 136
    assert len(set(all_ids)) == 136

    catalog_capabilities = (
        "list_condition",
        "single_doc",
        "single_doc_reason",
        "compare_max",
        "compare",
    )
    source_rows: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []
    csv_rows: list[dict[str, str]] = []
    sha_by_legacy_id: dict[str, str] = {}
    doc_by_legacy_id: dict[str, str] = {}
    index_by_legacy_id: dict[str, int] = {}
    for index, legacy_id in enumerate(all_ids, start=1):
        sha = source_sha(index)
        document_id = doc_id(index)
        sha_by_legacy_id[legacy_id] = sha
        doc_by_legacy_id[legacy_id] = document_id
        index_by_legacy_id[legacy_id] = index
        filename = f"synthetic-{legacy_id}.hwp"
        capability = "single_doc"
        if legacy_id in set_ids:
            capability = catalog_capabilities[set_ids.index(legacy_id) % len(catalog_capabilities)]
        required_facts: list[Any]
        if legacy_id == qa_ids[0]:
            required_facts = [[f"fact {legacy_id}", f"alias {legacy_id}"]]
        else:
            required_facts = [f"fact {legacy_id}"]
        source_rows.append(
            {
                "id": legacy_id,
                "question": f"synthetic question {legacy_id}",
                "gold_answer": f"synthetic answer {legacy_id}",
                "required_facts": required_facts,
                "evidence": f"synthetic evidence {legacy_id}",
                "source_document_ids": [sha],
                "source_documents": [filename, "synthetic.csv"],
                "difficulty": "very_easy" if legacy_id == qa_ids[0] else "medium",
                "capability": capability,
                "answerability": "answerable",
            }
        )
        manifest_rows.append(
            {
                "sha256": sha,
                "doc_id": document_id,
                "index_eligible": True,
                "status": "ok",
                "snapshot_id": SNAPSHOT_ID,
                "normalized_filename": filename,
            }
        )
        csv_rows.append(
            {
                "파일명": filename,
                "사업 금액": f"synthetic amount {legacy_id}",
            }
        )

    source_path = root / "source.jsonl"
    disposition_path = root / "disposition.json"
    overrides_path = root / "overrides.json"
    manifest_path = root / "manifest.jsonl"
    legacy_csv_path = root / "legacy.csv"
    blocks_dir = root / "blocks"
    write_jsonl(source_path, source_rows)
    write_jsonl(manifest_path, manifest_rows)
    with legacy_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["파일명", "사업 금액"])
        writer.writeheader()
        writer.writerows(csv_rows)
    disposition_path.write_text(
        json.dumps(
            {
                "supplemental_suites": {
                    "qa_regression_after_corrections": qa_ids,
                    "catalog_set_retrieval": set_ids,
                    "answer_document_alignment_review": alignment_ids,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    overrides: dict[str, Any] = {
        "schema_version": "1.0",
        "cases": {
            case_id: {"resolved": True, "patch": {}}
            for case_id in sorted(REQUIRED_CORRECTION_IDS)
        },
    }
    b14_targets = ["B14", *unused_ids[:6]]
    overrides["cases"]["B14"].update(
        {
            "target_source_sha256s": [sha_by_legacy_id[item] for item in b14_targets],
            "catalog_subtype": "list_condition",
            "set_definition": "synthetic seven-document target",
        }
    )
    c25_index = index_by_legacy_id["C25"]
    c25_amount = f"synthetic amount C25"
    overrides["cases"]["C25"].update(
        {
            "gold_decision": "source_conflict",
            "supporting_csv_refs": [
                {
                    "source_sha256": sha_by_legacy_id["C25"],
                    "row_number": c25_index + 1,
                    "field": "사업 금액",
                    "expected_value_sha256": hashlib.sha256(
                        canonical_json(c25_amount).encode("utf-8")
                    ).hexdigest(),
                }
            ],
        }
    )
    overrides_path.write_text(
        json.dumps(overrides, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )

    answer_ids = [*qa_ids, *alignment_ids]
    blocks_dir.mkdir(parents=True, exist_ok=True)
    for legacy_id in answer_ids:
        index = index_by_legacy_id[legacy_id]
        locator = f"section:synthetic/{legacy_id}"
        write_jsonl(
            blocks_dir / f"{doc_by_legacy_id[legacy_id]}.jsonl",
            [
                {
                    "block_id": block_id(index),
                    "doc_id": doc_by_legacy_id[legacy_id],
                    "retrieval_role": "primary",
                    "source_locator": locator,
                    "page_start": 1,
                    "text": (
                        f"synthetic answer {legacy_id}; fact {legacy_id}; "
                        f"synthetic evidence {legacy_id}"
                    ),
                }
            ],
        )

    return {
        "source_path": source_path,
        "disposition_path": disposition_path,
        "overrides_path": overrides_path,
        "manifest_path": manifest_path,
        "legacy_csv_path": legacy_csv_path,
        "blocks_dir": blocks_dir,
        "qa_ids": qa_ids,
        "set_ids": set_ids,
        "alignment_ids": alignment_ids,
        "sha_by_legacy_id": sha_by_legacy_id,
        "doc_by_legacy_id": doc_by_legacy_id,
    }
