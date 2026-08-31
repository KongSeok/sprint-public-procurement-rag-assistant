"""Offline preparation and scoring for the 69 supplemental evaluation cases.

The module intentionally keeps private questions, answers, evidence text and review
overrides outside tracked code.  Public failures contain only stable IDs and error
codes.  It does not call providers or weaken the frozen core evaluation floors.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import re
import sys
import tempfile
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "1.0"
PROFILE = "supplemental"
EXPECTED_LANE_COUNTS = {
    "qa_regression_after_corrections": 44,
    "catalog_set_retrieval": 13,
    "answer_document_alignment_review": 12,
}
PINNED_HASHES = {
    "source": "2dab148e5c361f1d28facb1794a54da748b4b7da42252dbf1ad4668becbef79f",
    "disposition": "98a39d1e93a5adc34242eff2b47b1590d0fc212030ebcf233ed7216a64f910a6",
    "overrides": "535916fd703b3ce89a29b84858ae706c456457cdf9fd4845697b096fdc8e5a46",
    "legacy_csv": "5e4074d061bf4e38cad70446ff392e7aab8c6e7909f8bc90a7a6f2b270e6ed9d",
    "manifest": "6c91d30a4c01b12f1aae8924c88a2e5055446c841f5eabfbf687546fdc1fe1cb",
}
REQUIRED_CORRECTION_IDS = {
    "G01",
    "G21",
    "G23",
    "C14",
    "C23",
    "C25",
    "B1",
    "B14",
    "B23",
    "H13",
    "H22",
}
CATALOG_SUBTYPE_BY_CAPABILITY = {
    "list_condition": "list_condition",
    "single_doc": "single_lookup",
    "single_doc_reason": "purpose_qa",
    "compare_max": "argmax",
    "compare": "compare",
}
DIFFICULTY_MAP = {
    "very_easy": "easy",
    "easy": "easy",
    "medium": "medium",
    "hard": "hard",
    "very_hard": "hard",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DOC_ID_RE = re.compile(r"^doc_[0-9a-f]{24}$")
BLOCK_ID_RE = re.compile(r"^block_[0-9a-f]{24}$")
ERROR_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
RFC3339_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")
WHITESPACE_RE = re.compile(r"\s+")
CASE_ID_RE = re.compile(r"^supplemental-(qa|alignment|set)-[A-Za-z0-9._:-]+$")
ALLOWED_TASK_TYPES = {"single_doc", "multi_doc_compare", "unknown"}
ALLOWED_SET_SUBTYPES = set(CATALOG_SUBTYPE_BY_CAPABILITY.values())
DEFAULT_SET_DEFINITION = {
    "single_lookup": "question-described business; exact one-document target frozen to the manifest snapshot",
    "purpose_qa": "question-named business; exact source document target frozen to the manifest snapshot",
    "argmax": "apply the question filter, then select the maximum-valued target in the manifest snapshot",
    "compare": "the question-named comparison documents, frozen to the manifest snapshot",
    "list_condition": "all documents satisfying the explicit question condition in the manifest snapshot",
}
REVIEW_DECISION_FIELDS = {
    "schema_version",
    "case_id",
    "case_sha256",
    "reviewer",
    "reviewed_at",
    "decision",
    "answer_verified",
    "evidence_refs",
    "absence_scope_doc_ids",
    "notes",
}
ANSWER_CASE_FIELDS = {
    "schema_version",
    "case_id",
    "legacy_id",
    "profile",
    "lane",
    "task_type",
    "question",
    "difficulty",
    "source_manifest_sha256",
    "source_sha256s",
    "scope_doc_ids",
    "required_doc_ids",
    "gold",
    "evidence_refs",
    "absence_scope_doc_ids",
    "legacy_evidence_note",
    "legacy_scoring_notes",
    "source_labels",
    "supporting_sources",
    "supporting_refs",
    "reviewed_draft_sha256",
    "review",
    "enabled",
    "tags",
}
SET_CASE_FIELDS = {
    "schema_version",
    "case_id",
    "legacy_id",
    "profile",
    "subtype",
    "question",
    "difficulty",
    "source_manifest_sha256",
    "source_sha256s",
    "required_doc_ids",
    "expected_count",
    "required_fact_groups",
    "set_definition",
    "legacy_scoring_notes",
    "source_labels",
    "supporting_sources",
    "reviewed_draft_sha256",
    "review",
    "enabled",
    "tags",
}
ANSWER_RUN_FIELDS = {
    "schema_version",
    "case_id",
    "eval_set_sha256",
    "config_sha256",
    "status",
    "answer",
    "retrieved_doc_ids",
    "cited_doc_ids",
    "timing_ms",
    "usage",
    "cache_hit",
    "error",
}
ALLOWED_PATCH_FIELDS = {
    "question",
    "gold_answer",
    "required_facts",
    "scoring_notes",
    "answerability",
    "source_documents",
    "source_document_ids",
    "capability",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def dataset_sha256(rows: Sequence[Mapping[str, Any]]) -> str:
    payload = "".join(canonical_json(row) + "\n" for row in rows)
    return sha256_text(payload)


def case_sha256(case: Mapping[str, Any]) -> str:
    return sha256_text(canonical_json(case))


def _evaluation_readiness(
    cases: Sequence[Mapping[str, Any]],
    *,
    expected_count: int,
    require_approved: bool,
) -> tuple[str, bool, bool]:
    suite_complete = len(cases) == expected_count
    official_gold_ready = suite_complete and all(
        isinstance(case, Mapping)
        and isinstance(case.get("review"), Mapping)
        and case["review"].get("status") == "approved"
        and case.get("enabled") is True
        for case in cases
    )
    evaluation_tier = "official" if require_approved else "provisional"
    return evaluation_tier, official_gold_ready, suite_complete


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"non_object_jsonl_row:{line_number}")
            rows.append(value)
    return rows


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("non_object_json")
    return value


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    temporary.replace(path)


def write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    _atomic_write(path, "".join(canonical_json(row) + "\n" for row in rows))


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    _atomic_write(path, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def _issue(code: str, case_id: str | None = None) -> dict[str, str]:
    issue = {"code": code}
    if case_id is not None:
        issue["case_id"] = case_id
    return issue


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _clean_text(value: str) -> str:
    return WHITESPACE_RE.sub(" ", _nfc(value)).strip()


def _fold(value: str) -> str:
    return "".join(TOKEN_RE.findall(_nfc(value).casefold()))


def _tokens(value: str) -> set[str]:
    return {
        token.casefold()
        for token in TOKEN_RE.findall(_nfc(value))
        if len(token) >= 2 or token.isdigit()
    }


def normalize_fact_groups(value: Any) -> list[list[str]]:
    if not isinstance(value, list) or not value:
        raise ValueError("required_fact_groups_missing")
    if all(isinstance(item, str) and item.strip() for item in value):
        return [[_clean_text(item)] for item in value]
    groups: list[list[str]] = []
    for group in value:
        if not isinstance(group, list) or not group:
            raise ValueError("required_fact_group_invalid")
        normalized: list[str] = []
        for alternative in group:
            if not isinstance(alternative, str) or not alternative.strip():
                raise ValueError("required_fact_alternative_invalid")
            item = _clean_text(alternative)
            if item not in normalized:
                normalized.append(item)
        groups.append(normalized)
    return groups


def _unique_strings(value: Any, code: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(code)
    output: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ValueError(code)
        if item not in output:
            output.append(item)
    return output


def _load_manifest(
    path: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], str]:
    by_sha: dict[str, dict[str, Any]] = {}
    by_doc: dict[str, dict[str, Any]] = {}
    snapshot_ids: set[str] = set()
    for row in read_jsonl(path):
        source_sha = row.get("sha256")
        doc_id = row.get("doc_id")
        if not isinstance(source_sha, str) or SHA256_RE.fullmatch(source_sha) is None:
            raise ValueError("manifest_source_sha_invalid")
        if not isinstance(doc_id, str) or DOC_ID_RE.fullmatch(doc_id) is None:
            raise ValueError("manifest_doc_id_invalid")
        if source_sha in by_sha or doc_id in by_doc:
            raise ValueError("manifest_identity_duplicate")
        if row.get("index_eligible") is not True or row.get("status") != "ok":
            raise ValueError("manifest_document_not_index_eligible")
        snapshot_id = row.get("snapshot_id")
        if not isinstance(snapshot_id, str) or not snapshot_id:
            raise ValueError("manifest_snapshot_missing")
        snapshot_ids.add(snapshot_id)
        by_sha[source_sha] = row
        by_doc[doc_id] = row
    if len(snapshot_ids) != 1:
        raise ValueError("manifest_snapshot_not_unique")
    return by_sha, by_doc, next(iter(snapshot_ids))


def _validate_pinned_hashes(
    source_path: Path,
    disposition_path: Path,
    overrides_path: Path,
    legacy_csv_path: Path,
    manifest_path: Path,
    expected_hashes: Mapping[str, str] | None,
) -> dict[str, str]:
    actual = {
        "source": sha256_file(source_path),
        "disposition": sha256_file(disposition_path),
        "overrides": sha256_file(overrides_path),
        "legacy_csv": sha256_file(legacy_csv_path),
        "manifest": sha256_file(manifest_path),
    }
    if expected_hashes is not None:
        for label, expected in expected_hashes.items():
            if actual.get(label) != expected:
                raise ValueError(f"pinned_hash_mismatch:{label}")
    return actual


def _validate_overrides(overrides: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if overrides.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("override_schema_version_invalid")
    cases = overrides.get("cases")
    if not isinstance(cases, dict):
        raise ValueError("override_cases_missing")
    missing = sorted(REQUIRED_CORRECTION_IDS - set(cases))
    if missing:
        raise ValueError("required_correction_missing:" + ",".join(missing))
    normalized: dict[str, dict[str, Any]] = {}
    for case_id, value in cases.items():
        if not isinstance(case_id, str) or not isinstance(value, dict):
            raise ValueError("override_case_invalid")
        if case_id in REQUIRED_CORRECTION_IDS and value.get("resolved") is not True:
            raise ValueError(f"required_correction_unresolved:{case_id}")
        patch = value.get("patch", {})
        if not isinstance(patch, dict) or set(patch) - ALLOWED_PATCH_FIELDS:
            raise ValueError(f"override_patch_invalid:{case_id}")
        normalized[case_id] = copy.deepcopy(value)
    return normalized


def _apply_override(record: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(dict(record))
    patch = override.get("patch", {})
    if isinstance(patch, dict):
        for key, replacement in patch.items():
            value[key] = copy.deepcopy(replacement)
    return value


def _lane_ids(disposition: Mapping[str, Any]) -> dict[str, list[str]]:
    suites = disposition.get("supplemental_suites")
    if not isinstance(suites, dict):
        raise ValueError("supplemental_suites_missing")
    result: dict[str, list[str]] = {}
    all_ids: list[str] = []
    for lane, expected_count in EXPECTED_LANE_COUNTS.items():
        ids = suites.get(lane)
        if not isinstance(ids, list) or len(ids) != expected_count:
            raise ValueError(f"lane_count_invalid:{lane}")
        if any(not isinstance(case_id, str) for case_id in ids):
            raise ValueError(f"lane_id_invalid:{lane}")
        result[lane] = list(ids)
        all_ids.extend(ids)
    if len(set(all_ids)) != sum(EXPECTED_LANE_COUNTS.values()):
        raise ValueError("supplemental_lane_overlap")
    return result


def _source_sha256s(record: Mapping[str, Any]) -> list[str]:
    values = _unique_strings(record.get("source_document_ids"), "source_sha256s_missing")
    if any(SHA256_RE.fullmatch(value) is None for value in values):
        raise ValueError("source_sha256_invalid")
    return values


def _map_doc_ids(
    source_sha256s: Sequence[str], manifest_by_sha: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    output: list[str] = []
    for source_sha in source_sha256s:
        row = manifest_by_sha.get(source_sha)
        if row is None:
            raise ValueError("source_sha_unmapped")
        doc_id = row.get("doc_id")
        if not isinstance(doc_id, str):
            raise ValueError("manifest_doc_id_invalid")
        if doc_id not in output:
            output.append(doc_id)
    return output


def _difficulty(record: Mapping[str, Any]) -> tuple[str, str | None]:
    original = record.get("difficulty")
    if not isinstance(original, str) or original not in DIFFICULTY_MAP:
        raise ValueError("difficulty_invalid")
    normalized = DIFFICULTY_MAP[original]
    return normalized, original if normalized != original else None


def _supporting_sources(record: Mapping[str, Any]) -> list[str]:
    values = record.get("source_documents")
    if not isinstance(values, list):
        return []
    output: list[str] = []
    for item in values:
        if isinstance(item, str) and item.casefold().endswith(".csv"):
            label = _clean_text(Path(item).name)
            if label not in output:
                output.append(label)
    return output


def _source_labels(record: Mapping[str, Any]) -> list[str]:
    values = record.get("source_documents")
    if not isinstance(values, list):
        return []
    output: list[str] = []
    for item in values:
        if isinstance(item, str) and item.strip() and not item.casefold().endswith(".csv"):
            label = _clean_text(Path(item).name)
            if label not in output:
                output.append(label)
    return output


def _legacy_scoring_notes(record: Mapping[str, Any]) -> str | None:
    value = record.get("scoring_notes")
    if not isinstance(value, str) or not value.strip():
        return None
    return _clean_text(value)


def _load_legacy_csv(path: Path) -> dict[int, dict[str, str]]:
    csv.field_size_limit(sys.maxsize)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = {
            row_number: dict(row)
            for row_number, row in enumerate(csv.DictReader(handle), start=2)
        }
    if not rows or any("파일명" not in row for row in rows.values()):
        raise ValueError("legacy_csv_contract_invalid")
    return rows


def _build_supporting_refs(
    override: Mapping[str, Any],
    source_sha256s: Sequence[str],
    manifest_by_sha: Mapping[str, Mapping[str, Any]],
    legacy_csv_rows: Mapping[int, Mapping[str, str]],
    legacy_csv_sha256: str,
) -> list[dict[str, Any]]:
    specs = override.get("supporting_csv_refs", [])
    if not isinstance(specs, list):
        raise ValueError("supporting_csv_refs_invalid")
    refs: list[dict[str, Any]] = []
    for spec in specs:
        if not isinstance(spec, dict) or set(spec) != {
            "source_sha256",
            "row_number",
            "field",
            "expected_value_sha256",
        }:
            raise ValueError("supporting_csv_ref_invalid")
        source_sha = spec.get("source_sha256")
        row_number = spec.get("row_number")
        field = spec.get("field")
        expected_value_sha = spec.get("expected_value_sha256")
        if (
            not isinstance(source_sha, str)
            or source_sha not in source_sha256s
            or not isinstance(row_number, int)
            or row_number < 2
            or not isinstance(field, str)
            or not field
            or not isinstance(expected_value_sha, str)
            or SHA256_RE.fullmatch(expected_value_sha) is None
        ):
            raise ValueError("supporting_csv_ref_invalid")
        manifest_row = manifest_by_sha.get(source_sha)
        csv_row = legacy_csv_rows.get(row_number)
        if manifest_row is None or csv_row is None or field not in csv_row:
            raise ValueError("supporting_csv_locator_invalid")
        if _nfc(csv_row.get("파일명", "")) != _nfc(
            str(manifest_row.get("normalized_filename", ""))
        ):
            raise ValueError("supporting_csv_document_mismatch")
        value_sha = sha256_text(canonical_json(csv_row[field]))
        if value_sha != expected_value_sha:
            raise ValueError("supporting_csv_value_mismatch")
        doc_id = manifest_row.get("doc_id")
        if not isinstance(doc_id, str):
            raise ValueError("supporting_csv_doc_id_invalid")
        locator_hash = sha256_text(
            f"{legacy_csv_sha256}:row:{row_number}:field:{_nfc(field)}"
        )
        ref = {
            "source_type": "legacy_csv",
            "role": "supporting",
            "source_file_sha256": legacy_csv_sha256,
            "doc_id": doc_id,
            "row_number": row_number,
            "field": _clean_text(field),
            "value_sha256": value_sha,
            "locator_hash": locator_hash,
        }
        if ref not in refs:
            refs.append(ref)
    return refs


def _validate_supporting_refs(
    refs: Any,
    *,
    legacy_csv_rows: Mapping[int, Mapping[str, str]],
    legacy_csv_sha256: str,
    manifest_by_doc: Mapping[str, Mapping[str, Any]],
) -> bool:
    if not isinstance(refs, list):
        return False
    for ref in refs:
        if not isinstance(ref, dict) or set(ref) != {
            "source_type",
            "role",
            "source_file_sha256",
            "doc_id",
            "row_number",
            "field",
            "value_sha256",
            "locator_hash",
        }:
            return False
        doc_id = ref.get("doc_id")
        row_number = ref.get("row_number")
        field = ref.get("field")
        row = legacy_csv_rows.get(row_number) if isinstance(row_number, int) else None
        manifest_row = manifest_by_doc.get(doc_id) if isinstance(doc_id, str) else None
        if (
            ref.get("source_type") != "legacy_csv"
            or ref.get("role") != "supporting"
            or ref.get("source_file_sha256") != legacy_csv_sha256
            or row is None
            or manifest_row is None
            or not isinstance(field, str)
            or field not in row
            or _nfc(row.get("파일명", ""))
            != _nfc(str(manifest_row.get("normalized_filename", "")))
            or ref.get("value_sha256") != sha256_text(canonical_json(row[field]))
            or ref.get("locator_hash")
            != sha256_text(f"{legacy_csv_sha256}:row:{row_number}:field:{_nfc(field)}")
        ):
            return False
    return True


def _valid_reviewed_at(value: Any) -> bool:
    if (
        not isinstance(value, str)
        or RFC3339_DATETIME_RE.fullmatch(value) is None
    ):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _normalized_identity(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = _clean_text(value)
    if not normalized or len(normalized) > 128:
        return None
    return normalized


def _same_identity(left: Any, right: Any) -> bool:
    left_normalized = _normalized_identity(left)
    right_normalized = _normalized_identity(right)
    return (
        left_normalized is not None
        and right_normalized is not None
        and left_normalized.casefold() == right_normalized.casefold()
    )


def _load_blocks(blocks_dir: Path, doc_id: str) -> list[dict[str, Any]]:
    path = blocks_dir / f"{doc_id}.jsonl"
    if not path.is_file():
        raise ValueError(f"source_blocks_missing:{doc_id}")
    blocks: list[dict[str, Any]] = []
    for row in read_jsonl(path):
        if row.get("retrieval_role") != "primary":
            continue
        block_id = row.get("block_id")
        locator = row.get("source_locator")
        page = row.get("page_start")
        text = row.get("text")
        if (
            not isinstance(block_id, str)
            or BLOCK_ID_RE.fullmatch(block_id) is None
            or not isinstance(locator, str)
            or not locator
            or not isinstance(page, int)
            or page < 1
            or not isinstance(text, str)
        ):
            raise ValueError(f"source_block_invalid:{doc_id}")
        blocks.append(row)
    if not blocks:
        raise ValueError(f"source_blocks_empty:{doc_id}")
    return blocks


def _candidate_qrels(
    record: Mapping[str, Any],
    doc_ids: Sequence[str],
    blocks_dir: Path,
    limit_per_doc: int = 3,
) -> tuple[list[dict[str, Any]], list[str]]:
    fact_groups = normalize_fact_groups(record.get("required_facts"))
    query_parts = [
        record.get("gold_answer", ""),
        record.get("evidence", ""),
        *(alternative for group in fact_groups for alternative in group),
    ]
    query = " ".join(part for part in query_parts if isinstance(part, str))
    query_tokens = _tokens(query)
    candidates: list[dict[str, Any]] = []
    blockers: list[str] = []
    for doc_id in doc_ids:
        scored: list[tuple[float, int, dict[str, Any]]] = []
        for block in _load_blocks(blocks_dir, doc_id):
            text = block["text"]
            folded = _fold(text)
            matched_groups = sum(
                1
                for group in fact_groups
                if any(_fold(alternative) and _fold(alternative) in folded for alternative in group)
            )
            block_tokens = _tokens(text)
            overlap = len(query_tokens & block_tokens) / max(1, len(query_tokens))
            score = matched_groups * 10.0 + overlap
            scored.append((score, matched_groups, block))
        scored.sort(key=lambda item: (-item[0], item[2]["page_start"], item[2]["block_id"]))
        selected = scored[:limit_per_doc]
        if not selected or selected[0][0] <= 0:
            blockers.append(f"weak_qrel_candidates:{doc_id}")
        for rank, (score, matched_groups, block) in enumerate(selected, start=1):
            candidates.append(
                {
                    "doc_id": doc_id,
                    "source_block_id": block["block_id"],
                    "page": block["page_start"],
                    "locator_hash": sha256_text(block["source_locator"]),
                    "candidate_rank": rank,
                    "candidate_score": round(score, 6),
                    "matched_fact_group_count": matched_groups,
                }
            )
    return candidates, blockers


def _answer_case(
    record: Mapping[str, Any],
    lane: str,
    override: Mapping[str, Any],
    manifest_by_sha: Mapping[str, Mapping[str, Any]],
    manifest_sha256: str,
    legacy_csv_rows: Mapping[int, Mapping[str, str]],
    legacy_csv_sha256: str,
) -> dict[str, Any]:
    legacy_id = record["id"]
    source_sha256s = _source_sha256s(record)
    scope_doc_ids = _map_doc_ids(source_sha256s, manifest_by_sha)
    decision = override.get("gold_decision")
    if decision is None:
        decision = "abstain" if record.get("answerability") == "unanswerable" else "answer"
    if decision not in {"answer", "abstain", "source_conflict"}:
        raise ValueError(f"gold_decision_invalid:{legacy_id}")
    difficulty, original_difficulty = _difficulty(record)
    if decision == "abstain":
        task_type = "unknown"
        required_doc_ids: list[str] = []
        reference_answer: str | None = None
        fact_groups: list[list[str]] = []
        abstain_reason = override.get("abstain_reason", "insufficient_evidence")
    else:
        task_type = "multi_doc_compare" if len(scope_doc_ids) > 1 else "single_doc"
        required_doc_ids = list(scope_doc_ids)
        reference_answer = record.get("gold_answer")
        if not isinstance(reference_answer, str) or not reference_answer:
            raise ValueError(f"reference_answer_missing:{legacy_id}")
        reference_answer = _clean_text(reference_answer)
        fact_groups = normalize_fact_groups(record.get("required_facts"))
        abstain_reason = None
    comparison_axes = override.get("comparison_axes", [])
    if not isinstance(comparison_axes, list) or any(
        not isinstance(axis, str) or not axis for axis in comparison_axes
    ):
        raise ValueError(f"comparison_axes_invalid:{legacy_id}")
    comparison_axes = [_clean_text(axis) for axis in comparison_axes]
    if task_type == "multi_doc_compare" and not comparison_axes:
        raise ValueError(f"comparison_axes_missing:{legacy_id}")
    lane_name = "qa_regression" if lane == "qa_regression_after_corrections" else "answer_alignment"
    tags = [f"legacy-id:{legacy_id}", f"lane:{lane_name}"]
    if original_difficulty is not None:
        tags.append(f"legacy-difficulty:{original_difficulty}")
    question = record.get("question")
    evidence = record.get("evidence")
    if not isinstance(question, str) or not question:
        raise ValueError(f"question_missing:{legacy_id}")
    if not isinstance(evidence, str) or not evidence:
        raise ValueError(f"legacy_evidence_missing:{legacy_id}")
    supporting_refs = _build_supporting_refs(
        override,
        source_sha256s,
        manifest_by_sha,
        legacy_csv_rows,
        legacy_csv_sha256,
    )
    if decision == "source_conflict" and not supporting_refs:
        raise ValueError(f"source_conflict_support_missing:{legacy_id}")
    return {
        "schema_version": SCHEMA_VERSION,
        "case_id": f"supplemental-{'qa' if lane_name == 'qa_regression' else 'alignment'}-{legacy_id.lower()}",
        "legacy_id": legacy_id,
        "profile": PROFILE,
        "lane": lane_name,
        "task_type": task_type,
        "question": _clean_text(question),
        "difficulty": difficulty,
        "source_manifest_sha256": manifest_sha256,
        "source_sha256s": source_sha256s,
        "scope_doc_ids": scope_doc_ids,
        "required_doc_ids": required_doc_ids,
        "gold": {
            "decision": decision,
            "reference_answer": reference_answer,
            "required_fact_groups": fact_groups,
            "abstain_reason": abstain_reason,
            "comparison_axes": comparison_axes,
        },
        "evidence_refs": [],
        "absence_scope_doc_ids": [],
        "legacy_evidence_note": _clean_text(evidence),
        "legacy_scoring_notes": _legacy_scoring_notes(record),
        "source_labels": _source_labels(record),
        "supporting_sources": _supporting_sources(record),
        "supporting_refs": supporting_refs,
        "reviewed_draft_sha256": None,
        "review": {
            "author": "legacy-import",
            "reviewer": None,
            "status": "draft",
            "reviewed_at": None,
        },
        "enabled": False,
        "tags": tags,
    }


def _set_case(
    record: Mapping[str, Any],
    override: Mapping[str, Any],
    manifest_by_sha: Mapping[str, Mapping[str, Any]],
    manifest_sha256: str,
    snapshot_id: str,
) -> dict[str, Any]:
    legacy_id = record["id"]
    legacy_source_sha256s = _source_sha256s(record)
    target_source_sha256s = override.get("target_source_sha256s", legacy_source_sha256s)
    source_sha256s = _unique_strings(target_source_sha256s, "set_target_sha256s_missing")
    if any(SHA256_RE.fullmatch(value) is None for value in source_sha256s):
        raise ValueError(f"set_target_sha256_invalid:{legacy_id}")
    required_doc_ids = _map_doc_ids(source_sha256s, manifest_by_sha)
    subtype = override.get("catalog_subtype")
    if subtype is None:
        subtype = CATALOG_SUBTYPE_BY_CAPABILITY.get(record.get("capability"))
    if subtype not in set(CATALOG_SUBTYPE_BY_CAPABILITY.values()):
        raise ValueError(f"catalog_subtype_invalid:{legacy_id}")
    if legacy_id == "B14" and len(required_doc_ids) != 7:
        raise ValueError("b14_target_count_invalid")
    question = record.get("question")
    if not isinstance(question, str) or not question:
        raise ValueError(f"question_missing:{legacy_id}")
    difficulty, original_difficulty = _difficulty(record)
    description = override.get("set_definition")
    if not isinstance(description, str) or not description.strip():
        description = record.get("list_definition")
    if not isinstance(description, str) or not description:
        description = DEFAULT_SET_DEFINITION[subtype]
    tags = [f"legacy-id:{legacy_id}", f"subtype:{subtype}"]
    if original_difficulty is not None:
        tags.append(f"legacy-difficulty:{original_difficulty}")
    return {
        "schema_version": SCHEMA_VERSION,
        "case_id": f"supplemental-set-{legacy_id.lower()}",
        "legacy_id": legacy_id,
        "profile": PROFILE,
        "subtype": subtype,
        "question": _clean_text(question),
        "difficulty": difficulty,
        "source_manifest_sha256": manifest_sha256,
        "source_sha256s": source_sha256s,
        "required_doc_ids": required_doc_ids,
        "expected_count": len(required_doc_ids),
        "required_fact_groups": normalize_fact_groups(record.get("required_facts")),
        "set_definition": {
            "snapshot_id": snapshot_id,
            "manifest_sha256": manifest_sha256,
            "description": _clean_text(description),
        },
        "legacy_scoring_notes": _legacy_scoring_notes(record),
        "source_labels": _source_labels(record),
        "supporting_sources": _supporting_sources(record),
        "reviewed_draft_sha256": None,
        "review": {
            "author": "legacy-import",
            "reviewer": None,
            "status": "draft",
            "reviewed_at": None,
        },
        "enabled": False,
        "tags": tags,
    }


def _valid_unique_strings(value: Any, *, allow_empty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(isinstance(item, str) and bool(item) for item in value)
        and len(set(value)) == len(value)
    )


def _valid_doc_ids(value: Any, *, allow_empty: bool = False) -> bool:
    return _valid_unique_strings(value, allow_empty=allow_empty) and all(
        DOC_ID_RE.fullmatch(item) is not None for item in value
    )


def _valid_sha256s(value: Any) -> bool:
    return _valid_unique_strings(value) and all(
        SHA256_RE.fullmatch(item) is not None for item in value
    )


def _valid_fact_groups(value: Any, *, allow_empty: bool = False) -> bool:
    if not isinstance(value, list) or (not allow_empty and not value):
        return False
    return all(_valid_unique_strings(group) for group in value)


def _valid_supporting_ref_shapes(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    expected_fields = {
        "source_type",
        "role",
        "source_file_sha256",
        "doc_id",
        "row_number",
        "field",
        "value_sha256",
        "locator_hash",
    }
    return all(
        isinstance(ref, dict)
        and set(ref) == expected_fields
        and ref.get("source_type") == "legacy_csv"
        and ref.get("role") == "supporting"
        and isinstance(ref.get("source_file_sha256"), str)
        and SHA256_RE.fullmatch(ref["source_file_sha256"]) is not None
        and isinstance(ref.get("doc_id"), str)
        and DOC_ID_RE.fullmatch(ref["doc_id"]) is not None
        and isinstance(ref.get("row_number"), int)
        and ref["row_number"] >= 2
        and isinstance(ref.get("field"), str)
        and bool(ref["field"])
        and isinstance(ref.get("value_sha256"), str)
        and SHA256_RE.fullmatch(ref["value_sha256"]) is not None
        and isinstance(ref.get("locator_hash"), str)
        and SHA256_RE.fullmatch(ref["locator_hash"]) is not None
        for ref in value
    )


def _validate_review(
    review: Any,
    enabled: Any,
    case_id: str | None,
    *,
    require_approved: bool,
) -> list[dict[str, str]]:
    if not isinstance(review, dict) or set(review) != {
        "author",
        "reviewer",
        "status",
        "reviewed_at",
    }:
        return [_issue("review_invalid", case_id)]
    author = review.get("author")
    status = review.get("status")
    if _normalized_identity(author) is None:
        return [_issue("review_invalid", case_id)]
    if status == "approved":
        reviewer = review.get("reviewer")
        if (
            enabled is not True
            or _normalized_identity(reviewer) is None
            or _same_identity(reviewer, author)
            or not _valid_reviewed_at(review.get("reviewed_at"))
        ):
            return [_issue("approval_metadata_invalid", case_id)]
        return []
    if status in {"draft", "rejected"}:
        issues: list[dict[str, str]] = []
        if enabled is not False:
            issues.append(_issue("unapproved_case_enabled", case_id))
        if status == "draft" and (
            review.get("reviewer") is not None or review.get("reviewed_at") is not None
        ):
            issues.append(_issue("draft_review_metadata_present", case_id))
        if status == "rejected" and (
            _normalized_identity(review.get("reviewer")) is None
            or _same_identity(review.get("reviewer"), author)
            or not _valid_reviewed_at(review.get("reviewed_at"))
        ):
            issues.append(_issue("rejection_metadata_invalid", case_id))
        if require_approved:
            issues.append(_issue("case_not_approved", case_id))
        return issues
    return [_issue("review_status_invalid", case_id)]


def _validate_answer_case(
    case: Mapping[str, Any], *, require_approved: bool
) -> list[dict[str, str]]:
    case_id = case.get("case_id") if isinstance(case.get("case_id"), str) else None
    issues: list[dict[str, str]] = []
    if set(case) != ANSWER_CASE_FIELDS:
        issues.append(_issue("answer_case_fields_invalid", case_id))
    if (
        case.get("schema_version") != SCHEMA_VERSION
        or case.get("profile") != PROFILE
        or not isinstance(case_id, str)
        or CASE_ID_RE.fullmatch(case_id) is None
        or not case_id.startswith("supplemental-qa-")
        and not case_id.startswith("supplemental-alignment-")
        or case.get("lane") not in {"qa_regression", "answer_alignment"}
        or case.get("task_type") not in ALLOWED_TASK_TYPES
        or case.get("difficulty") not in {"easy", "medium", "hard"}
        or not isinstance(case.get("question"), str)
        or not case.get("question")
        or not isinstance(case.get("legacy_evidence_note"), str)
        or not case.get("legacy_evidence_note")
        or not isinstance(case.get("tags"), list)
    ):
        issues.append(_issue("answer_case_contract_invalid", case_id))
    if (
        not isinstance(case.get("source_manifest_sha256"), str)
        or SHA256_RE.fullmatch(case["source_manifest_sha256"]) is None
        or not _valid_sha256s(case.get("source_sha256s"))
        or not _valid_doc_ids(case.get("scope_doc_ids"))
        or len(case.get("source_sha256s", [])) != len(case.get("scope_doc_ids", []))
        or not _valid_doc_ids(case.get("required_doc_ids"), allow_empty=True)
        or not set(case.get("required_doc_ids", [])).issubset(case.get("scope_doc_ids", []))
    ):
        issues.append(_issue("answer_source_contract_invalid", case_id))
    if not _valid_unique_strings(case.get("source_labels"), allow_empty=True) or not _valid_unique_strings(
        case.get("supporting_sources"), allow_empty=True
    ):
        issues.append(_issue("answer_source_labels_invalid", case_id))
    if not _valid_supporting_ref_shapes(case.get("supporting_refs")):
        issues.append(_issue("answer_supporting_refs_invalid", case_id))
    scoring_notes = case.get("legacy_scoring_notes")
    if scoring_notes is not None and (not isinstance(scoring_notes, str) or not scoring_notes):
        issues.append(_issue("answer_scoring_notes_invalid", case_id))
    evidence_refs = case.get("evidence_refs")
    if not isinstance(evidence_refs, list):
        issues.append(_issue("answer_evidence_invalid", case_id))
        evidence_refs = []
    absence_scope_doc_ids = case.get("absence_scope_doc_ids")
    if not _valid_doc_ids(absence_scope_doc_ids, allow_empty=True):
        issues.append(_issue("absence_scope_doc_ids_invalid", case_id))
        absence_scope_doc_ids = []
    gold = case.get("gold")
    if not isinstance(gold, dict) or set(gold) != {
        "decision",
        "reference_answer",
        "required_fact_groups",
        "abstain_reason",
        "comparison_axes",
    }:
        issues.append(_issue("answer_gold_invalid", case_id))
        gold = {}
    decision = gold.get("decision")
    required_doc_ids = case.get("required_doc_ids", [])
    if decision in {"answer", "source_conflict"}:
        if (
            not required_doc_ids
            or not isinstance(gold.get("reference_answer"), str)
            or not gold.get("reference_answer")
            or not _valid_fact_groups(gold.get("required_fact_groups"))
            or gold.get("abstain_reason") is not None
        ):
            issues.append(_issue("answer_gold_incomplete", case_id))
        if decision == "source_conflict" and not case.get("supporting_refs"):
            issues.append(_issue("source_conflict_support_missing", case_id))
    elif decision == "abstain":
        if (
            required_doc_ids
            or gold.get("reference_answer") is not None
            or gold.get("required_fact_groups") != []
            or not isinstance(gold.get("abstain_reason"), str)
            or not gold.get("abstain_reason")
            or case.get("task_type") != "unknown"
        ):
            issues.append(_issue("abstain_gold_invalid", case_id))
    else:
        issues.append(_issue("answer_decision_invalid", case_id))
    axes = gold.get("comparison_axes")
    if not _valid_unique_strings(axes, allow_empty=True):
        issues.append(_issue("comparison_axes_invalid", case_id))
    if case.get("task_type") == "multi_doc_compare" and not axes:
        issues.append(_issue("comparison_axes_missing", case_id))
    review_issues = _validate_review(
        case.get("review"), case.get("enabled"), case_id, require_approved=require_approved
    )
    issues.extend(review_issues)
    review = case.get("review") if isinstance(case.get("review"), dict) else {}
    reviewed_draft_sha = case.get("reviewed_draft_sha256")
    if review.get("status") == "approved":
        if not isinstance(reviewed_draft_sha, str) or SHA256_RE.fullmatch(reviewed_draft_sha) is None:
            issues.append(_issue("reviewed_draft_hash_invalid", case_id))
    elif reviewed_draft_sha is not None:
        issues.append(_issue("unapproved_reviewed_draft_hash_present", case_id))
    if review.get("status") == "approved" and decision in {"answer", "source_conflict"}:
        evidence_doc_ids = {
            ref.get("doc_id") for ref in evidence_refs if isinstance(ref, dict)
        }
        if not set(required_doc_ids).issubset(evidence_doc_ids):
            issues.append(_issue("approved_evidence_coverage_missing", case_id))
        expected_absence = set(required_doc_ids) if decision == "source_conflict" else set()
        if set(absence_scope_doc_ids) != expected_absence:
            issues.append(_issue("approved_absence_scope_invalid", case_id))
    elif review.get("status") == "approved" and decision == "abstain":
        if set(absence_scope_doc_ids) != set(case.get("scope_doc_ids", [])):
            issues.append(_issue("approved_absence_scope_invalid", case_id))
    elif review.get("status") != "approved" and evidence_refs:
        issues.append(_issue("unapproved_evidence_present", case_id))
    if review.get("status") != "approved" and absence_scope_doc_ids:
        issues.append(_issue("unapproved_absence_scope_present", case_id))
    return issues


def _validate_set_case(
    case: Mapping[str, Any], *, require_approved: bool
) -> list[dict[str, str]]:
    case_id = case.get("case_id") if isinstance(case.get("case_id"), str) else None
    issues: list[dict[str, str]] = []
    required_doc_ids = case.get("required_doc_ids")
    set_definition = case.get("set_definition")
    if set(case) != SET_CASE_FIELDS:
        issues.append(_issue("set_case_fields_invalid", case_id))
    if (
        case.get("schema_version") != SCHEMA_VERSION
        or case.get("profile") != PROFILE
        or not isinstance(case_id, str)
        or not case_id.startswith("supplemental-set-")
        or CASE_ID_RE.fullmatch(case_id) is None
        or case.get("subtype") not in ALLOWED_SET_SUBTYPES
        or case.get("difficulty") not in {"easy", "medium", "hard"}
        or not isinstance(case.get("question"), str)
        or not case.get("question")
        or not _valid_sha256s(case.get("source_sha256s"))
        or not _valid_doc_ids(required_doc_ids)
        or len(case.get("source_sha256s", [])) != len(required_doc_ids or [])
        or case.get("expected_count") != len(required_doc_ids or [])
        or not _valid_fact_groups(case.get("required_fact_groups"))
        or not isinstance(case.get("source_manifest_sha256"), str)
        or SHA256_RE.fullmatch(case["source_manifest_sha256"]) is None
    ):
        issues.append(_issue("set_case_contract_invalid", case_id))
    if (
        not isinstance(set_definition, dict)
        or set(set_definition) != {"snapshot_id", "manifest_sha256", "description"}
        or not isinstance(set_definition.get("snapshot_id"), str)
        or not set_definition.get("snapshot_id")
        or set_definition.get("manifest_sha256") != case.get("source_manifest_sha256")
        or not isinstance(set_definition.get("description"), str)
        or not set_definition.get("description")
    ):
        issues.append(_issue("set_definition_invalid", case_id))
    if not _valid_unique_strings(case.get("source_labels"), allow_empty=True) or not _valid_unique_strings(
        case.get("supporting_sources"), allow_empty=True
    ):
        issues.append(_issue("set_source_labels_invalid", case_id))
    scoring_notes = case.get("legacy_scoring_notes")
    if scoring_notes is not None and (not isinstance(scoring_notes, str) or not scoring_notes):
        issues.append(_issue("set_scoring_notes_invalid", case_id))
    review = case.get("review") if isinstance(case.get("review"), dict) else {}
    reviewed_draft_sha = case.get("reviewed_draft_sha256")
    if review.get("status") == "approved":
        if not isinstance(reviewed_draft_sha, str) or SHA256_RE.fullmatch(reviewed_draft_sha) is None:
            issues.append(_issue("reviewed_draft_hash_invalid", case_id))
    elif reviewed_draft_sha is not None:
        issues.append(_issue("unapproved_reviewed_draft_hash_present", case_id))
    issues.extend(
        _validate_review(
            case.get("review"), case.get("enabled"), case_id, require_approved=require_approved
        )
    )
    return issues


def validate_supplemental_cases(
    answer_cases: Sequence[Mapping[str, Any]],
    set_cases: Sequence[Mapping[str, Any]],
    *,
    require_approved: bool = False,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if len(answer_cases) != 56:
        issues.append(_issue("answer_case_count_invalid"))
    if len(set_cases) != 13:
        issues.append(_issue("set_case_count_invalid"))
    lane_counts = Counter(case.get("lane") for case in answer_cases)
    if lane_counts != Counter({"qa_regression": 44, "answer_alignment": 12}):
        issues.append(_issue("answer_lane_count_invalid"))
    all_case_ids = [case.get("case_id") for case in [*answer_cases, *set_cases]]
    if any(not isinstance(case_id, str) for case_id in all_case_ids) or len(set(all_case_ids)) != len(all_case_ids):
        issues.append(_issue("case_id_duplicate_or_invalid"))
    for case in answer_cases:
        issues.extend(_validate_answer_case(case, require_approved=require_approved))
    for case in set_cases:
        issues.extend(_validate_set_case(case, require_approved=require_approved))
    return issues


def prepare_supplemental(
    *,
    source_path: Path,
    disposition_path: Path,
    overrides_path: Path,
    legacy_csv_path: Path,
    manifest_path: Path,
    blocks_dir: Path,
    output_dir: Path | None = None,
    expected_hashes: Mapping[str, str] | None = PINNED_HASHES,
) -> dict[str, Any]:
    input_hashes = _validate_pinned_hashes(
        source_path,
        disposition_path,
        overrides_path,
        legacy_csv_path,
        manifest_path,
        expected_hashes,
    )
    source_rows = read_jsonl(source_path)
    if len(source_rows) != 136:
        raise ValueError("source_case_count_invalid")
    source_by_id: dict[str, dict[str, Any]] = {}
    for row in source_rows:
        case_id = row.get("id")
        if not isinstance(case_id, str) or case_id in source_by_id:
            raise ValueError("source_case_id_duplicate_or_invalid")
        source_by_id[case_id] = row
    disposition = read_json(disposition_path)
    lanes = _lane_ids(disposition)
    overrides = _validate_overrides(read_json(overrides_path))
    manifest_by_sha, _, snapshot_id = _load_manifest(manifest_path)
    legacy_csv_rows = _load_legacy_csv(legacy_csv_path)
    answer_cases: list[dict[str, Any]] = []
    set_cases: list[dict[str, Any]] = []
    review_queue: list[dict[str, Any]] = []
    legacy_reference_count = 0
    legacy_mapped_reference_count = 0
    mapped_reference_count = 0
    for lane in (
        "qa_regression_after_corrections",
        "answer_document_alignment_review",
    ):
        for legacy_id in lanes[lane]:
            source_record = source_by_id.get(legacy_id)
            if source_record is None:
                raise ValueError(f"source_case_missing:{legacy_id}")
            legacy_source_sha256s = _source_sha256s(source_record)
            legacy_reference_count += len(legacy_source_sha256s)
            legacy_mapped_reference_count += len(
                _map_doc_ids(legacy_source_sha256s, manifest_by_sha)
            )
            override = overrides.get(legacy_id, {})
            record = _apply_override(source_record, override)
            case = _answer_case(
                record,
                lane,
                override,
                manifest_by_sha,
                input_hashes["manifest"],
                legacy_csv_rows,
                input_hashes["legacy_csv"],
            )
            mapped_reference_count += len(case["scope_doc_ids"])
            answer_cases.append(case)
            if case["gold"]["decision"] == "abstain":
                candidates: list[dict[str, Any]] = []
                blockers: list[str] = []
            else:
                candidates, blockers = _candidate_qrels(
                    record, case["scope_doc_ids"], blocks_dir
                )
            review_queue.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "case_id": case["case_id"],
                    "legacy_id": legacy_id,
                    "case_sha256": case_sha256(case),
                    "required_doc_ids": case["required_doc_ids"],
                    "candidates": candidates,
                    "blockers": blockers,
                }
            )
    for legacy_id in lanes["catalog_set_retrieval"]:
        source_record = source_by_id.get(legacy_id)
        if source_record is None:
            raise ValueError(f"source_case_missing:{legacy_id}")
        legacy_source_sha256s = _source_sha256s(source_record)
        legacy_reference_count += len(legacy_source_sha256s)
        legacy_mapped_reference_count += len(
            _map_doc_ids(legacy_source_sha256s, manifest_by_sha)
        )
        override = overrides.get(legacy_id, {})
        record = _apply_override(source_record, override)
        case = _set_case(
            record,
            override,
            manifest_by_sha,
            input_hashes["manifest"],
            snapshot_id,
        )
        mapped_reference_count += len(case["required_doc_ids"])
        set_cases.append(case)
    answer_cases.sort(key=lambda item: item["legacy_id"])
    set_cases.sort(key=lambda item: item["legacy_id"])
    review_queue.sort(key=lambda item: item["legacy_id"])
    review_index = sorted(
        (
            {
                "schema_version": SCHEMA_VERSION,
                "case_id": case["case_id"],
                "legacy_id": case["legacy_id"],
                "case_sha256": case_sha256(case),
                "review_kind": "answer" if "lane" in case else "set",
            }
            for case in [*answer_cases, *set_cases]
        ),
        key=lambda item: item["case_id"],
    )
    issues = validate_supplemental_cases(answer_cases, set_cases)
    evaluation_tier, official_gold_ready, suite_complete = _evaluation_readiness(
        [*answer_cases, *set_cases],
        expected_count=69,
        require_approved=False,
    )
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "passed": not issues,
        "profile": PROFILE,
        "evaluation_tier": evaluation_tier,
        "official_gold_ready": official_gold_ready,
        "suite_complete": suite_complete,
        "input_sha256": input_hashes,
        "snapshot_id": snapshot_id,
        "counts": {
            "source": len(source_rows),
            "answer_total": len(answer_cases),
            "qa_regression": sum(case["lane"] == "qa_regression" for case in answer_cases),
            "answer_alignment": sum(case["lane"] == "answer_alignment" for case in answer_cases),
            "set_retrieval": len(set_cases),
            "supplemental_total": len(answer_cases) + len(set_cases),
            "legacy_source_references": legacy_reference_count,
            "legacy_mapped_source_references": legacy_mapped_reference_count,
            "effective_mapped_references": mapped_reference_count,
            "review_queue": len(review_queue),
            "review_index": len(review_index),
            "approved": 0,
        },
        "subtype_counts": dict(sorted(Counter(case["subtype"] for case in set_cases).items())),
        "task_type_counts": dict(sorted(Counter(case["task_type"] for case in answer_cases).items())),
        "correction_ids": sorted(REQUIRED_CORRECTION_IDS),
        "dataset_sha256": {
            "answer_draft": dataset_sha256(answer_cases),
            "set_draft": dataset_sha256(set_cases),
            "review_queue": dataset_sha256(review_queue),
            "review_index": dataset_sha256(review_index),
        },
        "review_queue_blocker_count": sum(bool(item["blockers"]) for item in review_queue),
        "errors": issues,
    }
    if issues:
        return report
    if output_dir is not None:
        write_jsonl(output_dir / "rag-56.draft.jsonl", answer_cases)
        write_jsonl(output_dir / "set-13.draft.jsonl", set_cases)
        write_jsonl(output_dir / "evidence-review-queue.jsonl", review_queue)
        write_jsonl(output_dir / "review-case-index.jsonl", review_index)
        write_json(output_dir / "build-report.json", report)
    return report


def _load_block_index(
    blocks_dir: Path, doc_ids: Iterable[str]
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for doc_id in sorted(set(doc_ids)):
        for block in _load_blocks(blocks_dir, doc_id):
            block_id = block["block_id"]
            if block_id in result:
                raise ValueError("source_block_id_duplicate")
            result[block_id] = block
    return result


def _validate_decision_evidence(
    evidence_refs: Any,
    required_doc_ids: Sequence[str],
    block_index: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(evidence_refs, list):
        raise ValueError("review_evidence_invalid")
    normalized: list[dict[str, Any]] = []
    for ref in evidence_refs:
        if not isinstance(ref, dict):
            raise ValueError("review_evidence_invalid")
        doc_id = ref.get("doc_id")
        block_id = ref.get("source_block_id")
        page = ref.get("page")
        locator_hash = ref.get("locator_hash")
        block = block_index.get(block_id) if isinstance(block_id, str) else None
        if (
            not isinstance(doc_id, str)
            or doc_id not in required_doc_ids
            or block is None
            or block.get("doc_id") != doc_id
            or block.get("page_start") != page
            or sha256_text(block.get("source_locator", "")) != locator_hash
        ):
            raise ValueError("review_evidence_reference_invalid")
        value = {
            "doc_id": doc_id,
            "source_block_id": block_id,
            "page": page,
            "locator_hash": locator_hash,
        }
        if value not in normalized:
            normalized.append(value)
    if not set(required_doc_ids).issubset({ref["doc_id"] for ref in normalized}):
        raise ValueError("review_evidence_coverage_missing")
    return normalized


def _validate_review_decision_shape(decision: Mapping[str, Any]) -> None:
    if set(decision) != REVIEW_DECISION_FIELDS:
        raise ValueError("review_decision_fields_invalid")
    if decision.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("review_decision_schema_invalid")
    case_id = decision.get("case_id")
    case_hash = decision.get("case_sha256")
    reviewer = decision.get("reviewer")
    if (
        not isinstance(case_id, str)
        or CASE_ID_RE.fullmatch(case_id) is None
        or not isinstance(case_hash, str)
        or SHA256_RE.fullmatch(case_hash) is None
        or _normalized_identity(reviewer) is None
        or not _valid_reviewed_at(decision.get("reviewed_at"))
        or decision.get("decision") not in {"approved", "rejected"}
        or not isinstance(decision.get("answer_verified"), bool)
        or not isinstance(decision.get("evidence_refs"), list)
        or not _valid_doc_ids(decision.get("absence_scope_doc_ids"), allow_empty=True)
        or (
            decision.get("notes") is not None
            and not isinstance(decision.get("notes"), str)
        )
    ):
        raise ValueError(f"review_decision_invalid:{case_id}")
    for ref in decision["evidence_refs"]:
        if (
            not isinstance(ref, dict)
            or set(ref) != {"doc_id", "source_block_id", "page", "locator_hash"}
            or not isinstance(ref.get("doc_id"), str)
            or DOC_ID_RE.fullmatch(ref["doc_id"]) is None
            or not isinstance(ref.get("source_block_id"), str)
            or BLOCK_ID_RE.fullmatch(ref["source_block_id"]) is None
            or not isinstance(ref.get("page"), int)
            or ref["page"] < 1
            or not isinstance(ref.get("locator_hash"), str)
            or SHA256_RE.fullmatch(ref["locator_hash"]) is None
        ):
            raise ValueError(f"review_evidence_shape_invalid:{case_id}")


def finalize_supplemental(
    *,
    answer_draft_path: Path,
    set_draft_path: Path,
    decisions_path: Path,
    blocks_dir: Path,
    manifest_path: Path,
    legacy_csv_path: Path,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    answer_cases = read_jsonl(answer_draft_path)
    set_cases = read_jsonl(set_draft_path)
    decisions = read_jsonl(decisions_path)
    draft_issues = validate_supplemental_cases(answer_cases, set_cases)
    if draft_issues:
        raise ValueError("supplemental_draft_contract_invalid")
    manifest_by_sha, manifest_by_doc, _ = _load_manifest(manifest_path)
    del manifest_by_sha
    manifest_sha256 = sha256_file(manifest_path)
    legacy_csv_rows = _load_legacy_csv(legacy_csv_path)
    legacy_csv_sha256 = sha256_file(legacy_csv_path)
    all_cases = [*answer_cases, *set_cases]
    cases_by_id = {case["case_id"]: case for case in all_cases}
    if len(cases_by_id) != len(all_cases):
        raise ValueError("supplemental_draft_case_id_duplicate")
    for case in all_cases:
        if case.get("source_manifest_sha256") != manifest_sha256:
            raise ValueError(f"draft_manifest_hash_mismatch:{case.get('case_id')}")
        if "lane" in case and not _validate_supporting_refs(
            case.get("supporting_refs"),
            legacy_csv_rows=legacy_csv_rows,
            legacy_csv_sha256=legacy_csv_sha256,
            manifest_by_doc=manifest_by_doc,
        ):
            raise ValueError(f"draft_supporting_ref_invalid:{case.get('case_id')}")
    by_case: dict[str, dict[str, Any]] = {}
    for decision in decisions:
        _validate_review_decision_shape(decision)
        case_id = decision.get("case_id")
        if not isinstance(case_id, str) or case_id in by_case:
            raise ValueError("review_decision_duplicate_or_invalid")
        case = cases_by_id.get(case_id)
        if case is None:
            raise ValueError(f"review_decision_unknown_case:{case_id}")
        if decision.get("case_sha256") != case_sha256(case):
            raise ValueError(f"review_decision_case_hash_mismatch:{case_id}")
        by_case[case_id] = decision
    block_index = _load_block_index(
        blocks_dir,
        (
            doc_id
            for case in answer_cases
            for doc_id in case.get("scope_doc_ids", [])
            if isinstance(doc_id, str)
        ),
    )
    approved_answer: list[dict[str, Any]] = []
    approved_set: list[dict[str, Any]] = []
    rejected = 0
    finalized_issues: list[dict[str, str]] = []
    for case in all_cases:
        case_id = case.get("case_id")
        decision = by_case.get(case_id)
        if decision is None:
            continue
        if _same_identity(
            decision.get("reviewer"), case.get("review", {}).get("author")
        ):
            raise ValueError(f"reviewer_author_conflict:{case_id}")
        normalized_reviewer = _normalized_identity(decision.get("reviewer"))
        if normalized_reviewer is None or not _valid_reviewed_at(
            decision.get("reviewed_at")
        ):
            raise ValueError(f"review_metadata_missing:{case_id}")
        if decision.get("decision") == "rejected":
            rejected += 1
            continue
        if decision.get("decision") != "approved" or decision.get("answer_verified") is not True:
            raise ValueError(f"review_approval_invalid:{case_id}")
        finalized = copy.deepcopy(case)
        finalized["review"] = {
            "author": case["review"]["author"],
            "reviewer": normalized_reviewer,
            "status": "approved",
            "reviewed_at": decision["reviewed_at"],
        }
        finalized["reviewed_draft_sha256"] = decision["case_sha256"]
        finalized["enabled"] = True
        if "lane" in finalized:
            required_doc_ids = finalized["required_doc_ids"]
            gold_decision = finalized["gold"]["decision"]
            absence_scope = decision["absence_scope_doc_ids"]
            finalized["absence_scope_doc_ids"] = list(absence_scope)
            if gold_decision == "abstain":
                if decision["evidence_refs"] or set(absence_scope) != set(
                    finalized["scope_doc_ids"]
                ):
                    raise ValueError(f"abstain_review_scope_invalid:{case_id}")
                finalized["evidence_refs"] = []
            else:
                expected_absence_scope = (
                    set(required_doc_ids) if gold_decision == "source_conflict" else set()
                )
                if set(absence_scope) != expected_absence_scope:
                    raise ValueError(f"review_absence_scope_invalid:{case_id}")
                finalized["evidence_refs"] = _validate_decision_evidence(
                    decision.get("evidence_refs"), required_doc_ids, block_index
                )
            approved_answer.append(finalized)
            finalized_issues.extend(
                _validate_answer_case(finalized, require_approved=True)
            )
        else:
            if decision["evidence_refs"] or decision["absence_scope_doc_ids"]:
                raise ValueError(f"set_review_evidence_invalid:{case_id}")
            approved_set.append(finalized)
            finalized_issues.extend(_validate_set_case(finalized, require_approved=True))
    approved_answer.sort(key=lambda item: item["case_id"])
    approved_set.sort(key=lambda item: item["case_id"])
    issues = finalized_issues
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "passed": not issues,
        "counts": {
            "decisions": len(decisions),
            "approved_answer": len(approved_answer),
            "approved_set": len(approved_set),
            "rejected": rejected,
            "pending": len(answer_cases) + len(set_cases) - len(decisions),
        },
        "input_sha256": {
            "answer_draft": sha256_file(answer_draft_path),
            "set_draft": sha256_file(set_draft_path),
            "review_decisions": sha256_file(decisions_path),
            "manifest": manifest_sha256,
            "legacy_csv": legacy_csv_sha256,
        },
        "dataset_sha256": {
            "approved_answer": dataset_sha256(approved_answer),
            "approved_set": dataset_sha256(approved_set),
        },
        "errors": issues,
    }
    if output_dir is not None:
        write_jsonl(output_dir / "rag-approved.jsonl", approved_answer)
        write_jsonl(output_dir / "set-approved.jsonl", approved_set)
        write_json(output_dir / "finalize-report.json", report)
    return report


def _validate_approved_external_assets(
    answer_cases: Sequence[Mapping[str, Any]],
    set_cases: Sequence[Mapping[str, Any]],
    *,
    manifest_path: Path,
    legacy_csv_path: Path,
    blocks_dir: Path,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    _, manifest_by_doc, _ = _load_manifest(manifest_path)
    manifest_sha256 = sha256_file(manifest_path)
    legacy_csv_rows = _load_legacy_csv(legacy_csv_path)
    legacy_csv_sha256 = sha256_file(legacy_csv_path)
    block_index = _load_block_index(
        blocks_dir,
        (
            doc_id
            for case in answer_cases
            for doc_id in case.get("scope_doc_ids", [])
            if isinstance(doc_id, str)
        ),
    )
    for case in answer_cases:
        case_id = case.get("case_id") if isinstance(case.get("case_id"), str) else None
        if case.get("review", {}).get("status") != "approved":
            continue
        if case.get("source_manifest_sha256") != manifest_sha256 or any(
            doc_id not in manifest_by_doc for doc_id in case.get("scope_doc_ids", [])
        ):
            issues.append(_issue("approved_manifest_reference_invalid", case_id))
        if not _validate_supporting_refs(
            case.get("supporting_refs"),
            legacy_csv_rows=legacy_csv_rows,
            legacy_csv_sha256=legacy_csv_sha256,
            manifest_by_doc=manifest_by_doc,
        ):
            issues.append(_issue("approved_supporting_ref_invalid", case_id))
        if case.get("gold", {}).get("decision") in {"answer", "source_conflict"}:
            try:
                _validate_decision_evidence(
                    case.get("evidence_refs"), case.get("required_doc_ids", []), block_index
                )
            except ValueError:
                issues.append(_issue("approved_evidence_reference_invalid", case_id))
    for case in set_cases:
        case_id = case.get("case_id") if isinstance(case.get("case_id"), str) else None
        if case.get("review", {}).get("status") != "approved":
            continue
        if case.get("source_manifest_sha256") != manifest_sha256 or any(
            doc_id not in manifest_by_doc for doc_id in case.get("required_doc_ids", [])
        ):
            issues.append(_issue("approved_manifest_reference_invalid", case_id))
    return issues


def score_set_cases(
    cases: Sequence[Mapping[str, Any]],
    runs: Sequence[Mapping[str, Any]],
    *,
    known_doc_ids: Iterable[str],
    manifest_sha256: str,
    require_approved: bool = False,
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    known_docs = set(known_doc_ids)
    if not known_docs or any(
        not isinstance(doc_id, str) or DOC_ID_RE.fullmatch(doc_id) is None
        for doc_id in known_docs
    ):
        raise ValueError("known_doc_ids_invalid")
    if SHA256_RE.fullmatch(manifest_sha256) is None:
        raise ValueError("manifest_sha256_invalid")
    case_by_id: dict[str, Mapping[str, Any]] = {}
    seen_case_ids: set[str] = set()
    for case in cases:
        if not isinstance(case, Mapping):
            errors.append(_issue("set_case_id_duplicate_or_invalid"))
            continue
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or case_id in seen_case_ids:
            errors.append(_issue("set_case_id_duplicate_or_invalid"))
            continue
        seen_case_ids.add(case_id)
        try:
            case_errors = _validate_set_case(
                case, require_approved=require_approved
            )
        except (AttributeError, TypeError, ValueError):
            case_errors = [_issue("set_case_contract_invalid", case_id)]
        if case.get("source_manifest_sha256") != manifest_sha256:
            case_errors.append(_issue("set_case_manifest_hash_mismatch", case_id))
        required_doc_ids = case.get("required_doc_ids")
        if _valid_doc_ids(required_doc_ids) and any(
            doc_id not in known_docs for doc_id in required_doc_ids
        ):
            case_errors.append(_issue("set_case_unknown_doc_id", case_id))
        errors.extend(case_errors)
        if not case_errors:
            case_by_id[case_id] = case
    eval_hash = dataset_sha256(cases)
    run_by_id: dict[str, Mapping[str, Any]] = {}
    seen_run_ids: set[str] = set()
    for run in runs:
        if not isinstance(run, Mapping):
            errors.append(_issue("set_run_id_duplicate_or_invalid"))
            continue
        case_id = run.get("case_id")
        if not isinstance(case_id, str) or case_id in seen_run_ids:
            errors.append(_issue("set_run_id_duplicate_or_invalid"))
            continue
        seen_run_ids.add(case_id)
        run_errors: list[dict[str, str]] = []
        if set(run) != {
            "schema_version",
            "case_id",
            "eval_set_sha256",
            "returned_doc_ids",
            "error",
        } or run.get("schema_version") != SCHEMA_VERSION:
            run_errors.append(_issue("set_run_contract_invalid", case_id))
        if case_id not in case_by_id:
            run_errors.append(_issue("set_run_unknown_case", case_id))
        if run.get("eval_set_sha256") != eval_hash:
            run_errors.append(_issue("set_run_hash_mismatch", case_id))
        returned = run.get("returned_doc_ids")
        returned_valid = _valid_doc_ids(returned, allow_empty=True)
        if not returned_valid:
            run_errors.append(_issue("set_run_doc_ids_invalid", case_id))
        elif any(doc_id not in known_docs for doc_id in returned):
            run_errors.append(_issue("set_run_unknown_doc_id", case_id))
        run_error = run.get("error")
        error_shape_valid = run_error is None or (
            isinstance(run_error, dict)
            and set(run_error) == {"code"}
            and isinstance(run_error.get("code"), str)
            and ERROR_CODE_RE.fullmatch(run_error["code"]) is not None
        )
        if not error_shape_valid:
            run_errors.append(_issue("set_run_error_state_invalid", case_id))
        elif run_error is not None:
            run_errors.append(_issue("set_run_runtime_error", case_id))
        errors.extend(run_errors)
        if not run_errors:
            run_by_id[case_id] = run
    missing = sorted(set(case_by_id) - seen_run_ids)
    errors.extend(_issue("set_run_missing", case_id) for case_id in missing)
    per_case: list[dict[str, Any]] = []
    total_tp = total_fp = total_fn = 0
    for case_id in sorted(set(case_by_id) & set(run_by_id)):
        case = case_by_id[case_id]
        run = run_by_id[case_id]
        gold = set(case.get("required_doc_ids", []))
        returned_values = run.get("returned_doc_ids", [])
        predicted = set(returned_values) if isinstance(returned_values, list) else set()
        tp = len(gold & predicted)
        fp = len(predicted - gold)
        fn = len(gold - predicted)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        total_tp += tp
        total_fp += fp
        total_fn += fn
        per_case.append(
            {
                "case_id": case_id,
                "precision": round(precision, 6),
                "recall": round(recall, 6),
                "f1": round(f1, 6),
                "exact_set_match": predicted == gold,
                "count_accurate": len(predicted) == len(gold),
            }
        )
    def mean(key: str) -> float | None:
        if not per_case:
            return None
        return round(sum(float(item[key]) for item in per_case) / len(per_case), 6)

    micro_precision = total_tp / (total_tp + total_fp) if total_tp + total_fp else 0.0
    micro_recall = total_tp / (total_tp + total_fn) if total_tp + total_fn else 0.0
    micro_f1 = (
        2 * micro_precision * micro_recall / (micro_precision + micro_recall)
        if micro_precision + micro_recall
        else 0.0
    )
    evaluation_tier, official_gold_ready, suite_complete = _evaluation_readiness(
        cases, expected_count=13, require_approved=require_approved
    )
    official_gold_ready = official_gold_ready and len(case_by_id) == len(cases)
    if require_approved and not suite_complete:
        errors.append(_issue("official_suite_incomplete"))
    return {
        "schema_version": SCHEMA_VERSION,
        "passed": not errors,
        "profile": PROFILE,
        "evaluation_tier": evaluation_tier,
        "official_gold_ready": official_gold_ready,
        "suite_complete": suite_complete,
        "eval_set_sha256": eval_hash,
        "run_set_sha256": dataset_sha256(runs),
        "manifest_sha256": manifest_sha256,
        "counts": {"cases": len(cases), "runs": len(runs), "scored": len(per_case)},
        "metrics": {
            "macro_precision": mean("precision"),
            "macro_recall": mean("recall"),
            "macro_f1": mean("f1"),
            "micro_precision": round(micro_precision, 6),
            "micro_recall": round(micro_recall, 6),
            "micro_f1": round(micro_f1, 6),
            "exact_set_match": mean("exact_set_match"),
            "count_accuracy": mean("count_accurate"),
        },
        "per_case": per_case,
        "errors": errors,
    }


def _deduplicated(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _dcg(values: Sequence[int]) -> float:
    return sum(value / math.log2(index + 2) for index, value in enumerate(values))


def _mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def _lexical_fact_coverage(
    answer: str, fact_groups: Sequence[Sequence[str]]
) -> float | None:
    if not fact_groups:
        return None
    answer_tokens = set(TOKEN_RE.findall(unicodedata.normalize("NFC", answer).lower()))
    covered = 0
    for group in fact_groups:
        if any(
            bool(tokens := set(TOKEN_RE.findall(unicodedata.normalize("NFC", fact).lower())))
            and tokens <= answer_tokens
            for fact in group
        ):
            covered += 1
    return covered / len(fact_groups)


def score_answer_cases(
    cases: Sequence[Mapping[str, Any]],
    runs: Sequence[Mapping[str, Any]],
    *,
    known_doc_ids: Iterable[str],
    manifest_sha256: str,
    require_approved: bool = False,
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    known_docs = set(known_doc_ids)
    if not known_docs or any(
        not isinstance(doc_id, str) or DOC_ID_RE.fullmatch(doc_id) is None
        for doc_id in known_docs
    ):
        raise ValueError("known_doc_ids_invalid")
    if SHA256_RE.fullmatch(manifest_sha256) is None:
        raise ValueError("manifest_sha256_invalid")
    case_by_id: dict[str, Mapping[str, Any]] = {}
    seen_case_ids: set[str] = set()
    for case in cases:
        if not isinstance(case, Mapping):
            errors.append(_issue("answer_case_id_duplicate_or_invalid"))
            continue
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or case_id in seen_case_ids:
            errors.append(_issue("answer_case_id_duplicate_or_invalid"))
            continue
        seen_case_ids.add(case_id)
        try:
            case_errors = _validate_answer_case(
                case, require_approved=require_approved
            )
        except (AttributeError, TypeError, ValueError):
            case_errors = [_issue("answer_case_contract_invalid", case_id)]
        if case.get("source_manifest_sha256") != manifest_sha256:
            case_errors.append(_issue("answer_case_manifest_hash_mismatch", case_id))
        scope_doc_ids = case.get("scope_doc_ids")
        required_doc_ids = case.get("required_doc_ids")
        if _valid_doc_ids(scope_doc_ids) and _valid_doc_ids(
            required_doc_ids, allow_empty=True
        ) and any(
            doc_id not in known_docs
            for doc_id in [*scope_doc_ids, *required_doc_ids]
        ):
            case_errors.append(_issue("answer_case_unknown_doc_id", case_id))
        errors.extend(case_errors)
        if not case_errors:
            case_by_id[case_id] = case

    eval_hash = dataset_sha256(cases)
    run_by_id: dict[str, Mapping[str, Any]] = {}
    seen_run_ids: set[str] = set()
    config_hashes: set[str] = set()
    for run in runs:
        if not isinstance(run, Mapping):
            errors.append(_issue("answer_run_id_duplicate_or_invalid"))
            continue
        case_id = run.get("case_id")
        if not isinstance(case_id, str) or case_id in seen_run_ids:
            errors.append(_issue("answer_run_id_duplicate_or_invalid"))
            continue
        seen_run_ids.add(case_id)
        run_errors: list[dict[str, str]] = []
        if set(run) != ANSWER_RUN_FIELDS or run.get("schema_version") != SCHEMA_VERSION:
            run_errors.append(_issue("answer_run_contract_invalid", case_id))
        if case_id not in case_by_id:
            run_errors.append(_issue("answer_run_unknown_case", case_id))
        if run.get("eval_set_sha256") != eval_hash:
            run_errors.append(_issue("answer_run_hash_mismatch", case_id))
        config_sha256 = run.get("config_sha256")
        if not isinstance(config_sha256, str) or SHA256_RE.fullmatch(
            config_sha256
        ) is None:
            run_errors.append(_issue("answer_run_config_hash_invalid", case_id))
        status = run.get("status")
        answer = run.get("answer")
        response_valid = (
            status in {"answered", "abstained", "error"}
            and isinstance(answer, str)
            and len(answer) <= 30000
        )
        if not response_valid:
            run_errors.append(_issue("answer_run_response_invalid", case_id))
        elif (status == "answered" and not answer.strip()) or (
            status != "answered" and answer != ""
        ):
            run_errors.append(_issue("answer_run_answer_state_invalid", case_id))
        retrieved = run.get("retrieved_doc_ids")
        cited = run.get("cited_doc_ids")
        retrieved_valid = isinstance(retrieved, list) and len(retrieved) <= 100 and not any(
            not isinstance(doc_id, str)
            or DOC_ID_RE.fullmatch(doc_id) is None
            or doc_id not in known_docs
            for doc_id in retrieved
        )
        if not retrieved_valid:
            run_errors.append(_issue("answer_run_retrieved_doc_ids_invalid", case_id))
        cited_valid = (
            isinstance(cited, list)
            and len(cited) <= 20
            and not any(
                not isinstance(doc_id, str)
                or DOC_ID_RE.fullmatch(doc_id) is None
                or doc_id not in known_docs
                for doc_id in cited
            )
            and len(cited) == len(set(cited))
        )
        if not cited_valid:
            run_errors.append(_issue("answer_run_cited_doc_ids_invalid", case_id))
        elif retrieved_valid and not set(cited) <= set(retrieved):
            run_errors.append(_issue("answer_run_citation_not_retrieved", case_id))
        timing = run.get("timing_ms")
        usage = run.get("usage")
        if not isinstance(timing, dict) or set(timing) != {"retrieval", "generation", "total"} or any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            or value < 0
            for value in timing.values()
        ):
            run_errors.append(_issue("answer_run_timing_invalid", case_id))
        if not isinstance(usage, dict) or set(usage) != {
            "embedding_tokens",
            "input_tokens",
            "output_tokens",
            "cost_usd",
        }:
            run_errors.append(_issue("answer_run_usage_invalid", case_id))
        elif any(
            not isinstance(usage[field], int)
            or isinstance(usage[field], bool)
            or usage[field] < 0
            for field in ("embedding_tokens", "input_tokens", "output_tokens")
        ) or (
            not isinstance(usage["cost_usd"], (int, float))
            or isinstance(usage["cost_usd"], bool)
            or not math.isfinite(float(usage["cost_usd"]))
            or usage["cost_usd"] < 0
        ):
            run_errors.append(_issue("answer_run_usage_invalid", case_id))
        if not isinstance(run.get("cache_hit"), bool):
            run_errors.append(_issue("answer_run_cache_state_invalid", case_id))
        error = run.get("error")
        error_shape_valid = error is None or (
            isinstance(error, dict)
            and set(error) == {"code"}
            and isinstance(error.get("code"), str)
            and ERROR_CODE_RE.fullmatch(error["code"]) is not None
        )
        if (
            not error_shape_valid
            or (status == "error") != isinstance(error, dict)
        ):
            run_errors.append(_issue("answer_run_error_state_invalid", case_id))
        errors.extend(run_errors)
        if not run_errors:
            run_by_id[case_id] = run
            config_hashes.add(config_sha256)

    if len(config_hashes) > 1:
        errors.append(_issue("answer_run_config_hash_mixed"))

    missing = sorted(set(case_by_id) - seen_run_ids)
    errors.extend(_issue("answer_run_missing", case_id) for case_id in missing)
    recall_by_k: dict[int, list[float]] = {1: [], 3: [], 5: [], 10: []}
    reciprocal_ranks: list[float] = []
    ndcg_values: list[float] = []
    citation_coverages: list[float] = []
    lexical_coverages: list[float] = []
    abstention_matches: list[float] = []
    costs: list[float] = []
    total_ms: list[float] = []
    runtime_errors = 0
    per_case: list[dict[str, Any]] = []
    for case_id in sorted(set(case_by_id) & set(run_by_id)):
        case = case_by_id[case_id]
        run = run_by_id[case_id]
        retrieved = run.get("retrieved_doc_ids", [])
        ranked_docs = _deduplicated(retrieved) if isinstance(retrieved, list) else []
        cited_docs = set(run.get("cited_doc_ids", []))
        relevant = set(case.get("required_doc_ids", []))
        case_metrics: dict[str, Any] = {"case_id": case_id}
        if relevant:
            for k in recall_by_k:
                value = len(set(ranked_docs[:k]) & relevant) / len(relevant)
                recall_by_k[k].append(value)
                case_metrics[f"document_recall_at_{k}"] = round(value, 6)
            first = next(
                (index for index, doc_id in enumerate(ranked_docs[:10], start=1) if doc_id in relevant),
                None,
            )
            reciprocal_rank = 0.0 if first is None else 1.0 / first
            reciprocal_ranks.append(reciprocal_rank)
            seen: set[str] = set()
            relevance: list[int] = []
            for doc_id in ranked_docs[:10]:
                is_new = doc_id in relevant and doc_id not in seen
                relevance.append(int(is_new))
                if is_new:
                    seen.add(doc_id)
            ideal = _dcg([1] * min(len(relevant), 10))
            ndcg_value = 0.0 if ideal == 0 else _dcg(relevance) / ideal
            ndcg_values.append(ndcg_value)
            citation_coverage = len(cited_docs & relevant) / len(relevant)
            citation_coverages.append(citation_coverage)
            case_metrics.update(
                {
                    "mrr_at_10": round(reciprocal_rank, 6),
                    "ndcg_at_10": round(ndcg_value, 6),
                    "required_doc_citation_coverage": round(citation_coverage, 6),
                }
            )
        if run.get("status") == "error":
            case_metrics["abstention_behavior_match"] = None
        else:
            expected_abstain = case.get("gold", {}).get("decision") == "abstain"
            abstention_match = float(
                (run.get("status") == "abstained") == expected_abstain
            )
            abstention_matches.append(abstention_match)
            case_metrics["abstention_behavior_match"] = abstention_match
        lexical = _lexical_fact_coverage(
            run.get("answer", ""), case.get("gold", {}).get("required_fact_groups", [])
        )
        if lexical is not None and run.get("status") == "answered":
            lexical_coverages.append(lexical)
            case_metrics["lexical_required_fact_coverage"] = round(lexical, 6)
        runtime_errors += int(run.get("status") == "error")
        if isinstance(run.get("usage"), dict):
            costs.append(float(run["usage"].get("cost_usd", 0.0)))
        if isinstance(run.get("timing_ms"), dict):
            total_ms.append(float(run["timing_ms"].get("total", 0.0)))
        per_case.append(case_metrics)

    evaluation_tier, official_gold_ready, suite_complete = _evaluation_readiness(
        cases, expected_count=56, require_approved=require_approved
    )
    official_gold_ready = official_gold_ready and len(case_by_id) == len(cases)
    if require_approved and not suite_complete:
        errors.append(_issue("official_suite_incomplete"))
    scored_count = len(per_case)
    return {
        "schema_version": SCHEMA_VERSION,
        "passed": not errors,
        "profile": PROFILE,
        "evaluation_tier": evaluation_tier,
        "official_gold_ready": official_gold_ready,
        "suite_complete": suite_complete,
        "eval_set_sha256": eval_hash,
        "run_set_sha256": dataset_sha256(runs),
        "config_sha256": next(iter(config_hashes)) if len(config_hashes) == 1 else None,
        "manifest_sha256": manifest_sha256,
        "counts": {
            "cases": len(cases),
            "runs": len(runs),
            "scored": scored_count,
            "retrieval_eligible": len(reciprocal_ranks),
            "runtime_errors": runtime_errors,
        },
        "metric_coverage": {
            "retrieval": len(reciprocal_ranks),
            "citation": len(citation_coverages),
            "lexical_fact": len(lexical_coverages),
            "abstention": len(abstention_matches),
            "human_answer_quality": 0,
        },
        "metrics": {
            **{
                f"document_recall_at_{k}": _mean(values)
                for k, values in recall_by_k.items()
            },
            "mrr_at_10": _mean(reciprocal_ranks),
            "ndcg_at_10": _mean(ndcg_values),
            "required_doc_citation_coverage": _mean(citation_coverages),
            "abstention_behavior_match": _mean(abstention_matches),
            "lexical_required_fact_coverage": _mean(lexical_coverages),
            "response_error_rate": (
                None if not scored_count else round(runtime_errors / scored_count, 6)
            ),
            "total_cost_usd": round(sum(costs), 9),
            "mean_total_latency_ms": _mean(total_ms),
        },
        "per_case": per_case,
        "errors": errors,
        "warnings": [
            "provisional automatic metrics do not establish answer correctness or faithfulness",
            "lexical fact coverage is diagnostic only",
        ],
    }


def _prepare_command(args: argparse.Namespace) -> int:
    report = prepare_supplemental(
        source_path=args.source_136,
        disposition_path=args.disposition,
        overrides_path=args.overrides,
        legacy_csv_path=args.legacy_csv,
        manifest_path=args.manifest,
        blocks_dir=args.blocks_dir,
        output_dir=args.output_dir,
    )
    print(canonical_json(report))
    return 0 if report["passed"] else 2


def _validate_command(args: argparse.Namespace) -> int:
    answer_cases = read_jsonl(args.rag_cases)
    set_cases = read_jsonl(args.set_cases)
    issues = validate_supplemental_cases(
        answer_cases, set_cases, require_approved=args.require_approved
    )
    if args.require_approved:
        if args.manifest is None or args.legacy_csv is None or args.blocks_dir is None:
            raise ValueError("approved_validation_sources_required")
        issues.extend(
            _validate_approved_external_assets(
                answer_cases,
                set_cases,
                manifest_path=args.manifest,
                legacy_csv_path=args.legacy_csv,
                blocks_dir=args.blocks_dir,
            )
        )
    evaluation_tier, official_gold_ready, suite_complete = _evaluation_readiness(
        [*answer_cases, *set_cases],
        expected_count=69,
        require_approved=args.require_approved,
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "passed": not issues,
        "evaluation_tier": evaluation_tier,
        "official_gold_ready": official_gold_ready,
        "suite_complete": suite_complete,
        "counts": {"answer": len(answer_cases), "set": len(set_cases)},
        "errors": issues,
    }
    if args.output is not None:
        write_json(args.output, report)
    print(canonical_json(report))
    return 0 if report["passed"] else 2


def _finalize_command(args: argparse.Namespace) -> int:
    report = finalize_supplemental(
        answer_draft_path=args.rag_cases,
        set_draft_path=args.set_cases,
        decisions_path=args.review_decisions,
        blocks_dir=args.blocks_dir,
        manifest_path=args.manifest,
        legacy_csv_path=args.legacy_csv,
        output_dir=args.output_dir,
    )
    print(canonical_json(report))
    return 0 if report["passed"] else 2


def _score_set_command(args: argparse.Namespace) -> int:
    cases = read_jsonl(args.cases)
    runs = read_jsonl(args.runs)
    _, manifest_by_doc, _ = _load_manifest(args.manifest)
    report = score_set_cases(
        cases,
        runs,
        known_doc_ids=manifest_by_doc,
        manifest_sha256=sha256_file(args.manifest),
        require_approved=args.require_approved,
    )
    if args.output is not None:
        write_json(args.output, report)
    print(canonical_json(report))
    return 0 if report["passed"] else 2


def _score_answer_command(args: argparse.Namespace) -> int:
    cases = read_jsonl(args.cases)
    runs = read_jsonl(args.runs)
    _, manifest_by_doc, _ = _load_manifest(args.manifest)
    if args.require_approved and (
        args.legacy_csv is None or args.blocks_dir is None
    ):
        raise ValueError("approved_validation_sources_required")
    report = score_answer_cases(
        cases,
        runs,
        known_doc_ids=manifest_by_doc,
        manifest_sha256=sha256_file(args.manifest),
        require_approved=args.require_approved,
    )
    if args.require_approved:
        report["errors"].extend(
            _validate_approved_external_assets(
                cases,
                [],
                manifest_path=args.manifest,
                legacy_csv_path=args.legacy_csv,
                blocks_dir=args.blocks_dir,
            )
        )
        report["passed"] = not report["errors"]
    if args.output is not None:
        write_json(args.output, report)
    print(canonical_json(report))
    return 0 if report["passed"] else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="midprojectrag-supplemental-eval")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare-supplemental")
    prepare.add_argument("--source-136", type=Path, required=True)
    prepare.add_argument("--disposition", type=Path, required=True)
    prepare.add_argument("--overrides", type=Path, required=True)
    prepare.add_argument("--legacy-csv", type=Path, required=True)
    prepare.add_argument("--manifest", type=Path, required=True)
    prepare.add_argument("--blocks-dir", type=Path, required=True)
    prepare.add_argument("--output-dir", type=Path, required=True)
    prepare.set_defaults(handler=_prepare_command)

    validate = subparsers.add_parser("validate-supplemental")
    validate.add_argument("--rag-cases", type=Path, required=True)
    validate.add_argument("--set-cases", type=Path, required=True)
    validate.add_argument("--require-approved", action="store_true")
    validate.add_argument("--manifest", type=Path)
    validate.add_argument("--legacy-csv", type=Path)
    validate.add_argument("--blocks-dir", type=Path)
    validate.add_argument("--output", type=Path)
    validate.set_defaults(handler=_validate_command)

    finalize = subparsers.add_parser("finalize-supplemental")
    finalize.add_argument("--rag-cases", type=Path, required=True)
    finalize.add_argument("--set-cases", type=Path, required=True)
    finalize.add_argument("--review-decisions", type=Path, required=True)
    finalize.add_argument("--blocks-dir", type=Path, required=True)
    finalize.add_argument("--manifest", type=Path, required=True)
    finalize.add_argument("--legacy-csv", type=Path, required=True)
    finalize.add_argument("--output-dir", type=Path, required=True)
    finalize.set_defaults(handler=_finalize_command)

    score = subparsers.add_parser("score-set")
    score.add_argument("--cases", type=Path, required=True)
    score.add_argument("--runs", type=Path, required=True)
    score.add_argument("--manifest", type=Path, required=True)
    score.add_argument("--require-approved", action="store_true")
    score.add_argument("--output", type=Path)
    score.set_defaults(handler=_score_set_command)

    score_answer = subparsers.add_parser("score-answer")
    score_answer.add_argument("--cases", type=Path, required=True)
    score_answer.add_argument("--runs", type=Path, required=True)
    score_answer.add_argument("--manifest", type=Path, required=True)
    score_answer.add_argument("--require-approved", action="store_true")
    score_answer.add_argument("--legacy-csv", type=Path)
    score_answer.add_argument("--blocks-dir", type=Path)
    score_answer.add_argument("--output", type=Path)
    score_answer.set_defaults(handler=_score_answer_command)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except (json.JSONDecodeError, OSError, ValueError) as error:
        detail = str(error)
        if len(detail) > 256:
            detail = detail[:256]
        print(
            canonical_json(
                {
                    "schema_version": SCHEMA_VERSION,
                    "passed": False,
                    "error": "invalid_supplemental_evaluation_input",
                    "detail": detail,
                }
            )
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
