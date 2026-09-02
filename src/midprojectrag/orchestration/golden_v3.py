"""Read-only adapter for the third golden-set evaluation inventory.

The shared v3 package is deliberately an inventory of lane-specific assets,
not one homogeneous JSONL.  This module validates that inventory and prepares
runtime requests without copying ``gold``/qrels into the request sent to the
orchestrator.  Scoring remains an offline concern.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from midprojectrag.evaluation import validate_request


INDEX_FILENAME = "third-golden-set-index.json"
EXPECTED_SET_ID = "third-integrated-evaluation-inventory-v3"
EXPECTED_COUNTS = {
    "total": 131,
    "rag": 129,
    "parser_regression": 2,
    "retained_original": 111,
    "new_purpose_built": 20,
    "excluded_unused": 25,
}
EXPECTED_LANES = {
    "core40": 40,
    "supplemental_answer_legacy": 39,
    "supplemental_answer_rerun": 17,
    "supplemental_set_rerun": 13,
    "visual": 10,
    "corpus_analytics": 10,
    "parser_regression": 2,
}
SOURCE_COUNTS = {
    "golden-set-final/dev.refined.review-candidate.jsonl": 40,
    "evaluation/private/supplemental/build-v1/rag-56.draft.jsonl": 56,
    "evaluation/private/supplemental/build-v1/set-13.draft.jsonl": 13,
    "golden-set-final/document-structure-visual-qa.jsonl": 10,
    "golden-set-final/corpus-analytics-qa.jsonl": 10,
}
NONVISUAL_REQUEST_SOURCES = (
    "golden-set-final/dev.refined.review-candidate.jsonl",
    "evaluation/private/supplemental/build-v1/rag-56.draft.jsonl",
    "evaluation/private/supplemental/build-v1/set-13.draft.jsonl",
)


@dataclass(frozen=True)
class GoldenV3Lane:
    lane: str
    count: int
    case_source: Path
    result_source: Path
    lineage: str | None


@dataclass(frozen=True)
class GoldenV3Inventory:
    root: Path
    index_sha256: str
    set_id: str
    status: str
    counts: Mapping[str, int]
    lanes: tuple[GoldenV3Lane, ...]
    source_sha256: Mapping[str, str]

    @property
    def lane_counts(self) -> dict[str, int]:
        return {lane.lane: lane.count for lane in self.lanes}

    @property
    def nonvisual_request_count(self) -> int:
        return sum(SOURCE_COUNTS.get(source, 0) for source in NONVISUAL_REQUEST_SOURCES)


def _read_json(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(code) from error
    if not isinstance(value, dict):
        raise ValueError(code)
    return value


def _relative(root: Path, value: Any, code: str) -> Path:
    if not isinstance(value, str) or not value or value != Path(value).as_posix():
        raise ValueError(code)
    candidate = (root / value).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError(code)
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _jsonl(path: Path, expected: int, code: str) -> tuple[dict[str, Any], ...]:
    if not path.is_file():
        raise ValueError(f"{code}_missing")
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(code)
                rows.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(code) from error
    if len(rows) != expected:
        raise ValueError(f"{code}_count_mismatch")
    case_ids = [row.get("case_id") for row in rows]
    if any(not isinstance(case_id, str) or not case_id for case_id in case_ids):
        raise ValueError(f"{code}_identity_invalid")
    if len(set(case_ids)) != len(case_ids):
        raise ValueError(f"{code}_duplicate_case_id")
    return tuple(rows)


def load_inventory(root: Path) -> GoldenV3Inventory:
    """Validate the v3 package and return content-free lane metadata."""

    root = root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError("golden_v3_root_missing")
    index_path = root / INDEX_FILENAME
    index = _read_json(index_path, "golden_v3_index_invalid")
    if index.get("set_id") != EXPECTED_SET_ID:
        raise ValueError("golden_v3_set_id_mismatch")
    if index.get("golden_set_semantics") != "not_a_single_gold_set":
        raise ValueError("golden_v3_semantics_invalid")
    if index.get("status") not in {"provisional", "approved"}:
        raise ValueError("golden_v3_status_invalid")

    contract = index.get("count_contract")
    counts = index.get("counts")
    if not isinstance(contract, Mapping) or not isinstance(counts, Mapping):
        raise ValueError("golden_v3_counts_missing")
    if contract.get("retained_original") != EXPECTED_COUNTS["retained_original"]:
        raise ValueError("golden_v3_retained_count_mismatch")
    if contract.get("new_purpose_built") != EXPECTED_COUNTS["new_purpose_built"]:
        raise ValueError("golden_v3_new_count_mismatch")
    if contract.get("excluded_unused") != EXPECTED_COUNTS["excluded_unused"]:
        raise ValueError("golden_v3_excluded_count_mismatch")
    if contract.get("formula") != "131 = 111 + 20":
        raise ValueError("golden_v3_formula_invalid")
    if counts.get("total") != EXPECTED_COUNTS["total"] or counts.get("rag") != EXPECTED_COUNTS["rag"]:
        raise ValueError("golden_v3_total_count_mismatch")
    if counts.get("parser_regression") != EXPECTED_COUNTS["parser_regression"]:
        raise ValueError("golden_v3_parser_count_mismatch")

    raw_lanes = index.get("lanes")
    if not isinstance(raw_lanes, list):
        raise ValueError("golden_v3_lanes_invalid")
    lanes: list[GoldenV3Lane] = []
    seen_lanes: set[str] = set()
    source_lane_counts: dict[str, int] = {}
    source_hashes: dict[str, str] = {}
    for raw in raw_lanes:
        if not isinstance(raw, Mapping):
            raise ValueError("golden_v3_lane_invalid")
        lane = raw.get("lane")
        count = raw.get("count")
        if not isinstance(lane, str) or lane in seen_lanes or type(count) is not int:
            raise ValueError("golden_v3_lane_invalid")
        if lane not in EXPECTED_LANES or count != EXPECTED_LANES[lane]:
            raise ValueError("golden_v3_lane_count_mismatch")
        case_source_value = raw.get("case_source")
        result_source_value = raw.get("result_source")
        case_source = _relative(root, case_source_value, "golden_v3_case_source_invalid")
        result_source = _relative(root, result_source_value, "golden_v3_result_source_invalid")
        if not result_source.exists():
            raise ValueError("golden_v3_result_source_missing")
        lineage = raw.get("lineage")
        if lineage is not None and not isinstance(lineage, str):
            raise ValueError("golden_v3_lineage_invalid")
        if case_source_value in SOURCE_COUNTS:
            expected = SOURCE_COUNTS[case_source_value]
            rows = _jsonl(case_source, expected, f"golden_v3_{lane}_source")
            source_hashes[case_source_value] = _sha256(case_source)
            source_lane_counts[case_source_value] = source_lane_counts.get(case_source_value, 0) + count
            if lane == "parser_regression":
                raise ValueError("golden_v3_parser_case_source_invalid")
            # The answer draft is intentionally referenced by two lanes.
            if lane == "core40" and any(row.get("case_id", "").startswith("supplemental-") for row in rows):
                raise ValueError("golden_v3_core_source_invalid")
        elif lane != "parser_regression":
            raise ValueError("golden_v3_unknown_case_source")
        seen_lanes.add(lane)
        lanes.append(GoldenV3Lane(lane, count, case_source, result_source, lineage))
    if set(seen_lanes) != set(EXPECTED_LANES):
        raise ValueError("golden_v3_lane_set_mismatch")
    if sum(lane.count for lane in lanes) != EXPECTED_COUNTS["total"]:
        raise ValueError("golden_v3_lane_total_mismatch")
    if source_lane_counts != {source: count for source, count in SOURCE_COUNTS.items()}:
        raise ValueError("golden_v3_source_lane_total_mismatch")

    return GoldenV3Inventory(
        root=root,
        index_sha256=_sha256(index_path),
        set_id=EXPECTED_SET_ID,
        status=str(index["status"]),
        counts={key: int(value) for key, value in counts.items() if key in {"total", "rag", "parser_regression", "supplemental_total", "supplemental_answer", "supplemental_set"}},
        lanes=tuple(lanes),
        source_sha256=dict(source_hashes),
    )


def _history(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    value = row.get("history")
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("golden_v3_history_invalid")
    return [dict(turn) for turn in value]


def _scope(row: Mapping[str, Any]) -> dict[str, Any]:
    value = row.get("document_scope")
    if isinstance(value, Mapping):
        return {"mode": value.get("mode"), "doc_ids": list(value.get("doc_ids", []))}
    values = row.get("scope_doc_ids")
    if values is None:
        values = row.get("required_doc_ids", [])
    if not isinstance(values, list):
        raise ValueError("golden_v3_scope_invalid")
    return {"mode": "explicit" if values else "all", "doc_ids": list(values)}


def build_runtime_requests(inventory: GoldenV3Inventory, *, include_visual: bool = False) -> tuple[dict[str, Any], ...]:
    """Build private request envelopes; gold and retrieval targets are omitted."""

    rows: list[dict[str, Any]] = []
    for source_name in NONVISUAL_REQUEST_SOURCES + (("golden-set-final/document-structure-visual-qa.jsonl",) if include_visual else ()):
        source_path = inventory.root / source_name
        expected = SOURCE_COUNTS[source_name]
        for row in _jsonl(source_path, expected, "golden_v3_request_source"):
            case_id = row.get("case_id")
            question = row.get("question")
            if not isinstance(case_id, str) or not isinstance(question, str) or not question.strip():
                raise ValueError("golden_v3_request_case_invalid")
            request = {
                "schema_version": "1.0",
                "request_id": case_id,
                "question": question,
                "history": _history(row),
                "document_scope": _scope(row),
                "options": {"max_citations": 5},
            }
            if validate_request(request):
                raise ValueError("golden_v3_request_invalid")
            rows.append({
                "case_id": case_id,
                "lane_source": source_name,
                "task_type": row.get("task_type", "visual_table_qa" if "visual" in source_name else "unknown"),
                "request": request,
            })
    if not rows or len({row["case_id"] for row in rows}) != len(rows):
        raise ValueError("golden_v3_request_identity_invalid")
    return tuple(rows)
