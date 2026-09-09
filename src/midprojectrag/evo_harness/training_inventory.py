"""Model-free historical-evaluation exclusion inventory for Evo policy training."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from itertools import combinations
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from midprojectrag.evaluation import normalize_question
from midprojectrag.ingest.common import canonical_json, sha256_file, sha256_text
from .training import build_exclusion_manifest, read_jsonl, validate_exclusion_manifest

INVENTORY_SCHEMA = "evo-training-exclusion-inventory-v1"
MINI131_SUITE_ID = "gcp-local-kure-qwen3-8b-awq-mini131-v1"
MINI131_RAG_COUNT = 129
QUESTION_SOURCES = (
    "core40", "supplemental_answers", "supplemental_sets", "visual", "analytics",
)


def _within(root: Path, value: str | Path) -> Path:
    root = root.resolve()
    path = (root / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
    if path != root and root not in path.parents:
        raise ValueError("training_inventory_path_outside_root")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("training_inventory_json_object_required")
    return value


def _docs(row: Mapping[str, Any]) -> list[str]:
    scope = row.get("document_scope")
    if isinstance(scope, Mapping) and isinstance(scope.get("doc_ids"), list):
        raw = scope["doc_ids"]
    else:
        raw = None
        for key in ("scope_doc_ids", "required_doc_ids", "source_document_ids"):
            if isinstance(row.get(key), list):
                raw = row[key]
                break
    if raw is None:
        return []
    if any(not isinstance(item, str) or not item for item in raw):
        raise ValueError("training_inventory_doc_ids_invalid")
    return sorted(set(raw))


def project_evaluation_rows(rows: Sequence[Mapping[str, Any]], *, source_id: str) -> list[dict[str, Any]]:
    if not source_id:
        raise ValueError("training_inventory_source_id_invalid")
    projected: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        question = row.get("question")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("training_inventory_question_required")
        base: dict[str, Any] = {"question": question, "source_id": source_id, "source_ordinal": index}
        for key in ("group_id", "conversation_id", "conversation", "task_type"):
            if key in row:
                base[key] = deepcopy(row[key])
        docs = _docs(row)
        if docs:
            base["document_scope"] = {"mode": "explicit", "doc_ids": docs}
            if "task_type" not in base:
                base["task_type"] = "multi_doc_compare" if len(docs) == 2 else "single_doc"
        projected.append(base)
        original = row.get("original_question")
        if isinstance(original, str) and original.strip() and normalize_question(original) != normalize_question(question):
            alternate = deepcopy(base)
            alternate["question"] = original
            alternate["source_variant"] = "original_question"
            projected.append(alternate)
    return projected


def _verified_source(root: Path, name: str, spec: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path_value = spec.get("path")
    expected_hash = spec.get("sha256")
    expected_count = spec.get("count")
    if not isinstance(path_value, str) or not isinstance(expected_hash, str) or not isinstance(expected_count, int):
        raise ValueError("training_inventory_source_spec_invalid")
    path = _within(root, path_value)
    if not path.is_file() or sha256_file(path) != expected_hash:
        raise ValueError(f"training_inventory_source_hash_mismatch:{name}")
    rows = read_jsonl(path)
    if len(rows) != expected_count:
        raise ValueError(f"training_inventory_source_count_mismatch:{name}")
    receipt = {"source_id": name, "path": path_value, "count": len(rows), "sha256": expected_hash}
    return rows, receipt


def build_historical_exclusion_inventory(*, source_repo_root: Path, mini131_config: Path,
                                         extra_evaluation_paths: Sequence[Path] = ()) -> dict[str, Any]:
    root = source_repo_root.resolve()
    config_path = _within(root, mini131_config)
    config = _read_json(config_path)
    if config.get("suite_id") != MINI131_SUITE_ID or not isinstance(config.get("sources"), Mapping):
        raise ValueError("training_inventory_mini131_config_invalid")
    projected: list[dict[str, Any]] = []
    source_receipts: list[dict[str, Any]] = []
    rag_rows = 0
    for name in QUESTION_SOURCES:
        spec = config["sources"].get(name)
        if not isinstance(spec, Mapping):
            raise ValueError("training_inventory_source_spec_invalid")
        rows, receipt = _verified_source(root, name, spec)
        rag_rows += len(rows)
        projected.extend(project_evaluation_rows(rows, source_id=f"mini131:{name}"))
        source_receipts.append(receipt)
    if rag_rows != MINI131_RAG_COUNT:
        raise ValueError("training_inventory_mini131_rag_count_mismatch")

    for extra in extra_evaluation_paths:
        path = _within(root, extra)
        rows = read_jsonl(path)
        rel = path.relative_to(root).as_posix()
        projected.extend(project_evaluation_rows(rows, source_id=f"historical:{rel}"))
        source_receipts.append({"source_id": f"historical:{rel}", "path": rel,
                                "count": len(rows), "sha256": sha256_file(path)})

    source_receipts = sorted(source_receipts, key=lambda row: row["source_id"])
    source_digest = sha256_text(canonical_json(source_receipts))
    manifest = build_exclusion_manifest(projected, source_id="evo35-historical-evaluation",
                                        source_sha256=source_digest)
    receipt: dict[str, Any] = {
        "schema_version": INVENTORY_SCHEMA,
        "mini131_rag_rows": rag_rows,
        "projected_exclusion_cases": len(projected),
        "source_count": len(source_receipts),
        "sources": source_receipts,
        "fingerprint_counts": {key: len(values) for key, values in manifest["fingerprints"].items()},
        "exclusion_manifest_sha256": manifest["manifest_sha256"],
    }
    receipt["receipt_sha256"] = sha256_text(canonical_json(receipt))
    return {"manifest": manifest, "receipt": receipt}


def build_corpus_training_inventory(*, source_repo_root: Path, stack_config: Path,
                                    exclusion_manifest: Mapping[str, Any]) -> dict[str, Any]:
    validate_exclusion_manifest(exclusion_manifest)
    root = source_repo_root.resolve()
    config_path = _within(root, stack_config)
    config = _read_json(config_path)
    corpus = config.get("corpus")
    if not isinstance(corpus, Mapping):
        raise ValueError("training_corpus_config_invalid")
    manifest_value = corpus.get("manifest_path")
    expected_hash = corpus.get("manifest_sha256")
    expected_count = corpus.get("document_count")
    if not isinstance(manifest_value, str) or not isinstance(expected_hash, str) or not isinstance(expected_count, int):
        raise ValueError("training_corpus_config_invalid")
    manifest_path = _within(root, manifest_value)
    if sha256_file(manifest_path) != expected_hash:
        raise ValueError("training_corpus_manifest_hash_mismatch")
    rows = read_jsonl(manifest_path)
    if len(rows) != expected_count:
        raise ValueError("training_corpus_document_count_mismatch")
    doc_ids = [row.get("doc_id") for row in rows]
    if any(not isinstance(doc_id, str) or not doc_id for doc_id in doc_ids) or len(set(doc_ids)) != len(doc_ids):
        raise ValueError("training_corpus_doc_id_invalid")
    ordered = sorted(doc_ids)
    blocked = set(exclusion_manifest["fingerprints"]["doc_pair_sha256"])
    pair_hashes = {sha256_text(canonical_json(list(pair))) for pair in combinations(ordered, 2)}
    blocked_in_corpus = pair_hashes & blocked
    docs = [{"doc_id": row["doc_id"], "extension": row.get("extension"),
             "page_count": row.get("page_count"), "index_eligible": row.get("index_eligible")}
            for row in sorted(rows, key=lambda item: item["doc_id"])]
    receipt: dict[str, Any] = {
        "schema_version": "evo-training-corpus-inventory-v1",
        "manifest_path": manifest_value,
        "manifest_sha256": expected_hash,
        "document_count": len(docs),
        "doc_id_set_sha256": sha256_text(canonical_json(ordered)),
        "extension_counts": dict(sorted(Counter(str(row.get("extension")) for row in rows).items())),
        "pair_space_count": len(pair_hashes),
        "excluded_pair_count": len(blocked_in_corpus),
        "available_pair_count": len(pair_hashes - blocked_in_corpus),
    }
    receipt["receipt_sha256"] = sha256_text(canonical_json(receipt))
    return {"documents": docs, "receipt": receipt}
