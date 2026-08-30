from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, TextIO

from midprojectrag.ingest.common import (
    canonical_json,
    read_jsonl,
    require_sha256,
    require_within,
    sha256_file,
    sha256_text,
    write_json,
)
from midprojectrag.ingest.visual_bundle import (
    materialize_hwp_visual_bundle,
    verify_hwp_visual_bundle,
)


VISUAL_CORPUS_SCHEMA_VERSION = "1.0"
VISUAL_CORPUS_METHOD = "rhwp-visual-corpus-rollout-v1"
VISUAL_CORPUS_CONFIG = {
    "asset_policy": "magic-canonical-dual-provenance-unsupported-unlinked-v2",
    "bundle_method": "rhwp-ordered-visual-evidence-v1",
    "coordinate_space": "rhwp_css_px_96dpi",
    "image_link_policy": "render-key-page-sequence-bbox-exact-outside-unlinked-v2",
    "ordered_policy": "render-tree-text-table-image-v1",
    "table_join_policy": "canonical-block-render-key-exact-no-guess-v1",
}
VISUAL_CORPUS_CONFIG_SHA256 = sha256_text(canonical_json(VISUAL_CORPUS_CONFIG))

_DOC_ID_RE = re.compile(r"^doc_[0-9a-f]{24}$")
_RUN_ID_RE = re.compile(r"^run_[a-z0-9][a-z0-9_-]{0,62}$")
_ERROR_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ROLES = (
    "schedule",
    "image",
    "merged_nested_table",
    "long_multi_page_table",
    "layout_unresolved",
)


def _canonical_hash(value: Any) -> str:
    try:
        return sha256_text(canonical_json(value))
    except (TypeError, ValueError):
        raise ValueError("visual_corpus_value_invalid") from None


def _safe_error(error: BaseException, fallback: str = "visual_bundle_failed") -> str:
    value = str(error)
    return value if _ERROR_RE.fullmatch(value) is not None else fallback


def _nonnegative(value: Any) -> int | float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or value < 0
    ):
        return 0
    return value


def _role_score(record: Mapping[str, Any], role: str) -> tuple[float, ...]:
    if role == "schedule":
        return (
            float(
                _nonnegative(
                    record.get("schedule_fact_count", record.get("schedule_facts"))
                )
            ),
            float(_nonnegative(record.get("background_cells"))),
        )
    if role == "image":
        return (
            float(_nonnegative(record.get("image_count", record.get("images")))),
            float(_nonnegative(record.get("table_nested_image_count"))),
        )
    if role == "merged_nested_table":
        return (
            float(
                _nonnegative(
                    record.get("max_cells_per_table", record.get("max_table_cell_count"))
                )
            ),
            float(
                _nonnegative(
                    record.get("spanned_cell_count", record.get("spanned_cells"))
                )
            ),
            float(_nonnegative(record.get("merged_table_count", record.get("merged_tables")))),
            float(
                _nonnegative(
                    record.get("wrapper_flattened_count", record.get("wrapper_flattened"))
                )
            ),
        )
    if role == "long_multi_page_table":
        return (
            float(_nonnegative(record.get("max_table_page_span"))),
            float(
                _nonnegative(
                    record.get("multi_page_table_count", record.get("multi_page_tables"))
                )
            ),
        )
    if role == "layout_unresolved":
        return (
            float(
                _nonnegative(
                    record.get("layout_unresolved_count", record.get("unresolved_layouts"))
                )
            ),
            float(_nonnegative(record.get("nonbody_unlinked_count"))),
            float(_nonnegative(record.get("paragraph_anchor_candidate_count"))),
            float(_nonnegative(record.get("page_count"))),
            float(_nonnegative(record.get("table_count"))),
        )
    raise ValueError("visual_sample_role_invalid")


def _numeric_stats(record: Mapping[str, Any]) -> dict[str, int | float]:
    stats: dict[str, int | float] = {}
    for key, value in sorted(record.items()):
        if key == "doc_id" or isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and value >= 0:
            stats[str(key)] = value
    return stats


def select_hwp_visual_samples(
    structural_stats: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Select five unique, content-free structural risk representatives.

    One document may cover multiple roles (the known schedule document also
    carries image evidence).  Remaining slots prefer the strongest wrapper
    stress and then aggregate structural risk; ties always use ``doc_id``.
    """

    if isinstance(structural_stats, (str, bytes)) or not isinstance(
        structural_stats, Sequence
    ):
        raise ValueError("visual_sample_stats_invalid")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in structural_stats:
        if not isinstance(raw, Mapping):
            raise ValueError("visual_sample_stats_invalid")
        record = dict(raw)
        doc_id = record.get("doc_id")
        if (
            not isinstance(doc_id, str)
            or _DOC_ID_RE.fullmatch(doc_id) is None
            or doc_id in seen
        ):
            raise ValueError("visual_sample_doc_id_invalid")
        seen.add(doc_id)
        records.append(record)
    if len(records) < 5:
        raise ValueError("visual_sample_insufficient_documents")

    selected: dict[str, set[str]] = {}
    for role in _ROLES:
        ranked = sorted(
            records,
            key=lambda value: (
                tuple(-number for number in _role_score(value, role)),
                str(value["doc_id"]),
            ),
        )
        if not any(_role_score(ranked[0], role)):
            raise ValueError(f"visual_sample_{role}_evidence_missing")
        doc_id = str(ranked[0]["doc_id"])
        selected.setdefault(doc_id, set()).add(role)

    # When one document covers two roles, retain a separate wrapper/nested
    # stress representative before using a broad aggregate risk fallback.
    fill_rank = sorted(
        records,
        key=lambda value: (
            -float(
                _nonnegative(
                    value.get("wrapper_flattened_count", value.get("wrapper_flattened"))
                )
            ),
            -float(_nonnegative(value.get("risk_score"))),
            -float(_nonnegative(value.get("table_count"))),
            str(value["doc_id"]),
        ),
    )
    for record in fill_rank:
        if len(selected) >= 5:
            break
        selected.setdefault(str(record["doc_id"]), set()).add("coverage_control")
    if len(selected) != 5:
        raise ValueError("visual_sample_selection_failed")

    by_doc_id = {str(record["doc_id"]): record for record in records}
    documents = [
        {
            "doc_id": doc_id,
            "roles": sorted(roles),
            "stats": _numeric_stats(by_doc_id[doc_id]),
        }
        for doc_id, roles in sorted(selected.items())
    ]
    policy = {
        "fill_policy": "wrapper-then-risk-score-then-table-count-doc-id-v1",
        "required_roles": list(_ROLES),
        "role_score_policy": "numeric-desc-doc-id-asc-v1",
        "sample_size": 5,
    }
    return {
        "schema_version": VISUAL_CORPUS_SCHEMA_VERSION,
        "method": "hwp-visual-structural-risk-sample-v1",
        "selection_policy_sha256": _canonical_hash(policy),
        "documents": documents,
    }


def build_hwp_visual_structural_stats(
    documents: Sequence[Mapping[str, Any]],
    *,
    existing_visual_root: Path | None = None,
) -> list[dict[str, int | str]]:
    """Derive numeric-only sample features from canonical/local artifacts."""

    stats: list[dict[str, int | str]] = []
    for document in sorted(documents, key=lambda value: str(value.get("doc_id", ""))):
        doc_id = document.get("doc_id")
        blocks = document.get("blocks")
        layouts = document.get("layout_records")
        if (
            not isinstance(doc_id, str)
            or _DOC_ID_RE.fullmatch(doc_id) is None
            or not isinstance(blocks, Sequence)
            or isinstance(blocks, (str, bytes))
            or not isinstance(layouts, Sequence)
            or isinstance(layouts, (str, bytes))
        ):
            raise ValueError("visual_sample_stats_invalid")
        table_blocks = [
            block
            for block in blocks
            if isinstance(block, Mapping) and block.get("block_type") == "table"
        ]
        max_cells = 0
        merged_tables = 0
        spanned_cells = 0
        for block in table_blocks:
            structure = block.get("table_structure")
            if not isinstance(structure, Mapping):
                raise ValueError("visual_sample_stats_invalid")
            cell_count = structure.get("cell_count")
            if isinstance(cell_count, int) and not isinstance(cell_count, bool):
                max_cells = max(max_cells, cell_count)
            cells = structure.get("cells")
            if not isinstance(cells, list):
                raise ValueError("visual_sample_stats_invalid")
            merged = 0
            for cell in cells:
                if not isinstance(cell, Mapping):
                    raise ValueError("visual_sample_stats_invalid")
                if _nonnegative(cell.get("row_span")) > 1 or _nonnegative(
                    cell.get("col_span")
                ) > 1:
                    merged += 1
            if merged:
                merged_tables += 1
                spanned_cells += merged
        layout_statuses = Counter(
            str(layout.get("status", ""))
            for layout in layouts
            if isinstance(layout, Mapping)
        )
        if "" in layout_statuses:
            raise ValueError("visual_sample_stats_invalid")
        spans = [
            int(layout["page_end"]) - int(layout["page_start"]) + 1
            for layout in layouts
            if isinstance(layout, Mapping)
            and isinstance(layout.get("page_start"), int)
            and not isinstance(layout.get("page_start"), bool)
            and isinstance(layout.get("page_end"), int)
            and not isinstance(layout.get("page_end"), bool)
        ]
        wrapper_count = sum(
            layout.get("wrapper_flattened") is True
            for layout in layouts
            if isinstance(layout, Mapping)
        )
        invalid_bbox_count = sum(
            page_bbox.get("bbox_valid") is not True
            for layout in layouts
            if isinstance(layout, Mapping)
            for page_bbox in (
                layout.get("page_bboxes")
                if isinstance(layout.get("page_bboxes"), list)
                else []
            )
            if isinstance(page_bbox, Mapping)
        )
        anchor_missing = sum(
            layout.get("anchor_present") is not True
            for layout in layouts
            if isinstance(layout, Mapping)
        )
        image_count = 0
        schedule_fact_count = 0
        background_cells = 0
        if existing_visual_root is not None:
            bundle_root = existing_visual_root / doc_id
            metadata_path = bundle_root / "metadata.json"
            table_path = bundle_root / "table-visual-v1.jsonl"
            try:
                if metadata_path.is_file() and not metadata_path.is_symlink():
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                    if isinstance(metadata, Mapping) and isinstance(
                        metadata.get("images"), int
                    ):
                        image_count = max(0, int(metadata["images"]))
                if table_path.is_file() and not table_path.is_symlink():
                    visual_tables = read_jsonl(table_path)
                    schedule_fact_count = sum(
                        len(record.get("schedule_facts", []))
                        for record in visual_tables
                        if isinstance(record.get("schedule_facts"), list)
                    )
                    background_cells = sum(
                        len(record.get("background_cells", []))
                        for record in visual_tables
                        if isinstance(record.get("background_cells"), list)
                    )
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                raise ValueError("visual_sample_existing_artifact_invalid") from None
        page_count = document.get("page_count")
        if not isinstance(page_count, int) or isinstance(page_count, bool):
            raise ValueError("visual_sample_stats_invalid")
        unresolved = sum(
            count
            for status, count in layout_statuses.items()
            if status != "verified_render"
        )
        risk_score = (
            page_count
            + len(table_blocks)
            + unresolved * 20
            + wrapper_count * 50
            + (max(spans) if spans else 0) * 10
            + min(max_cells, 2_000) // 10
        )
        stats.append(
            {
                "doc_id": doc_id,
                "page_count": page_count,
                "table_count": len(table_blocks),
                "schedule_fact_count": schedule_fact_count,
                "image_count": image_count,
                "wrapper_flattened_count": wrapper_count,
                "spanned_cell_count": spanned_cells,
                "merged_table_count": merged_tables,
                "max_cells_per_table": max_cells,
                "max_table_page_span": max(spans) if spans else 0,
                "multi_page_table_count": sum(span > 1 for span in spans),
                "layout_unresolved_count": layout_statuses.get(
                    "paragraph_anchor_candidate", 0
                ),
                "nonbody_unlinked_count": layout_statuses.get(
                    "nonbody_unlinked", 0
                ),
                "paragraph_anchor_candidate_count": layout_statuses.get(
                    "paragraph_anchor_candidate", 0
                ),
                "invalid_bbox_count": invalid_bbox_count,
                "anchor_missing_count": anchor_missing,
                "background_cells": background_cells,
                "risk_score": risk_score,
            }
        )
    if len({str(record["doc_id"]) for record in stats}) != len(stats):
        raise ValueError("visual_sample_doc_id_invalid")
    return stats


def _merge_counts(target: Counter[str], values: Mapping[str, Any]) -> None:
    for key, value in values.items():
        if (
            not isinstance(key, str)
            or not key
            or not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
        ):
            raise ValueError("visual_corpus_status_counts_invalid")
        target[key] += value


def _document_paths(output_root: Path, doc_id: str) -> dict[str, Path]:
    root = output_root / doc_id
    return {
        "table_output": root / "table-visual-v1.jsonl",
        "image_output": root / "images-v1.jsonl",
        "ordered_output": root / "ordered-v1.jsonl",
        "metadata_output": root / "metadata.json",
    }


def _validate_runner_roots(
    *, output_root: Path, asset_root: Path, private_root: Path, report_output: Path | None
) -> tuple[Path, Path, Path, Path | None]:
    if not private_root.is_dir() or private_root.is_symlink():
        raise ValueError("visual_corpus_private_root_invalid")
    resolved_private = private_root.resolve(strict=True)
    resolved_output = require_within(
        output_root, resolved_private, "visual_corpus_output_outside_private_root"
    )
    resolved_assets = require_within(
        asset_root, resolved_private, "visual_corpus_asset_outside_private_root"
    )
    resolved_report = (
        require_within(
            report_output,
            resolved_private,
            "visual_corpus_report_outside_private_root",
        )
        if report_output is not None
        else None
    )
    for path in (output_root, asset_root):
        if path.exists() and (path.is_symlink() or not path.is_dir()):
            raise ValueError("visual_corpus_private_path_invalid")
        path.mkdir(parents=True, exist_ok=True)
    return resolved_private, resolved_output, resolved_assets, resolved_report


def run_hwp_visual_corpus(
    *,
    command: str,
    documents: Sequence[Mapping[str, Any]],
    output_root: Path,
    asset_root: Path,
    private_root: Path,
    config_sha256: str,
    expected_rhwp_sha256: str,
    continue_on_error: bool = False,
    stream: TextIO | None = None,
    run_id: str = "run_visual_corpus_v1",
    mode: str = "corpus",
    selection_sha256: str = "0" * 64,
    source_manifest_sha256: str = "0" * 64,
    table_layout_artifact_sha256: str = "0" * 64,
    report_output: Path | None = None,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """Materialize or strictly reuse a sorted set of HWP visual bundles."""

    if mode not in {"sample", "corpus"}:
        raise ValueError("visual_corpus_mode_invalid")
    if not isinstance(run_id, str) or _RUN_ID_RE.fullmatch(run_id) is None:
        raise ValueError("visual_corpus_run_id_invalid")
    config_sha256 = require_sha256(config_sha256, "visual_corpus_config_invalid")
    expected_rhwp_sha256 = require_sha256(
        expected_rhwp_sha256, "visual_corpus_rhwp_hash_invalid"
    )
    selection_sha256 = require_sha256(
        selection_sha256, "visual_corpus_selection_hash_invalid"
    )
    source_manifest_sha256 = require_sha256(
        source_manifest_sha256, "visual_corpus_manifest_hash_invalid"
    )
    table_layout_artifact_sha256 = require_sha256(
        table_layout_artifact_sha256, "visual_corpus_layout_hash_invalid"
    )
    if (
        not isinstance(timeout_seconds, int)
        or isinstance(timeout_seconds, bool)
        or timeout_seconds < 1
    ):
        raise ValueError("visual_corpus_timeout_invalid")
    if not isinstance(documents, Sequence) or isinstance(documents, (str, bytes)):
        raise ValueError("visual_corpus_documents_invalid")
    resolved_private, resolved_output, resolved_assets, resolved_report = (
        _validate_runner_roots(
            output_root=output_root,
            asset_root=asset_root,
            private_root=private_root,
            report_output=report_output,
        )
    )
    if (
        not isinstance(command, str)
        or not Path(command).is_absolute()
        or not Path(command).is_file()
        or Path(command).is_symlink()
        or sha256_file(Path(command)) != expected_rhwp_sha256
    ):
        raise ValueError("visual_corpus_rhwp_identity_invalid")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in documents:
        if not isinstance(raw, Mapping):
            raise ValueError("visual_corpus_document_invalid")
        document = dict(raw)
        doc_id = document.get("doc_id")
        if (
            not isinstance(doc_id, str)
            or _DOC_ID_RE.fullmatch(doc_id) is None
            or doc_id in seen
        ):
            raise ValueError("visual_corpus_document_id_invalid")
        seen.add(doc_id)
        source_path = document.get("source_path")
        if not isinstance(source_path, Path):
            raise ValueError("visual_corpus_source_invalid")
        document["expected_source_sha256"] = require_sha256(
            document.get("expected_source_sha256"),
            "visual_corpus_source_hash_invalid",
        )
        page_count = document.get("page_count")
        if (
            not isinstance(page_count, int)
            or isinstance(page_count, bool)
            or page_count < 0
            or not isinstance(document.get("blocks"), Sequence)
            or isinstance(document.get("blocks"), (str, bytes))
            or not isinstance(document.get("layout_records"), Sequence)
            or isinstance(document.get("layout_records"), (str, bytes))
        ):
            raise ValueError("visual_corpus_document_invalid")
        normalized.append(document)
    if not normalized:
        raise ValueError("visual_corpus_no_documents")

    table_counts: Counter[str] = Counter()
    image_counts: Counter[str] = Counter()
    ordered_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    results: list[dict[str, Any]] = []
    run_totals: Counter[str] = Counter(
        {"requested": len(normalized), "succeeded": 0, "materialized": 0, "reused": 0, "failed": 0}
    )
    bundle_totals: Counter[str] = Counter()

    for document in sorted(normalized, key=lambda value: str(value["doc_id"])):
        doc_id = str(document["doc_id"])
        paths = _document_paths(resolved_output, doc_id)
        paths["metadata_output"].parent.mkdir(parents=True, exist_ok=True)
        kwargs = {
            "command": command,
            "source_path": document["source_path"],
            "doc_id": doc_id,
            "blocks": document["blocks"],
            "layout_records": document["layout_records"],
            **paths,
            "asset_root": resolved_assets,
            "private_root": resolved_private,
            "config_sha256": config_sha256,
            "expected_source_sha256": document["expected_source_sha256"],
            "expected_rhwp_sha256": expected_rhwp_sha256,
        }
        verify_kwargs = {**kwargs, "expected_page_count": document["page_count"]}
        attempts = 0
        terminal_state: str
        metadata: dict[str, Any] | None = None
        try:
            try:
                metadata = verify_hwp_visual_bundle(**verify_kwargs)
                terminal_state = "reused"
            except ValueError:
                attempts = 1
                materialize_hwp_visual_bundle(
                    **kwargs, timeout_seconds=timeout_seconds
                )
                metadata = verify_hwp_visual_bundle(**verify_kwargs)
                terminal_state = "materialized"
        except Exception as error:
            error_code = _safe_error(error, "visual_corpus_materialize_failed")
            results.append(
                {
                    "doc_id": doc_id,
                    "terminal_state": "failed",
                    "attempts": attempts,
                    "source_sha256": document["expected_source_sha256"],
                    "blocks_sha256": _canonical_hash(list(document["blocks"])),
                    "layout_records_sha256": _canonical_hash(
                        list(document["layout_records"])
                    ),
                    "artifact_set_id": None,
                    "metadata_sha256": None,
                    "error_code": error_code,
                    "counts": {
                        "page_count": 0,
                        "tables": 0,
                        "images": 0,
                        "ordered_occurrences": 0,
                        "asset_count": 0,
                        "asset_reference_count": 0,
                        "asset_bytes": 0,
                        "asset_references_reconciled": False,
                    },
                    "table_status_counts": {},
                    "image_status_counts": {},
                    "ordered_status_counts": {},
                }
            )
            status_counts["failed"] += 1
            run_totals["failed"] += 1
            if not continue_on_error:
                break
            continue

        assert metadata is not None
        metadata_path = paths["metadata_output"]
        result = {
            "doc_id": doc_id,
            "terminal_state": terminal_state,
            "attempts": attempts,
            "source_sha256": metadata["source_sha256"],
            "blocks_sha256": metadata["blocks_sha256"],
            "layout_records_sha256": metadata["layout_records_sha256"],
            "artifact_set_id": metadata["artifact_set_id"],
            "metadata_sha256": sha256_file(metadata_path),
            "error_code": None,
            "counts": {
                "page_count": metadata["page_count"],
                "tables": metadata["tables"],
                "images": metadata["images"],
                "ordered_occurrences": metadata["ordered_occurrences"],
                "asset_count": metadata["asset_count"],
                "asset_reference_count": metadata["asset_reference_count"],
                "asset_bytes": metadata["asset_bytes"],
                "asset_references_reconciled": metadata[
                    "asset_references_reconciled"
                ],
            },
            "table_status_counts": metadata["table_status_counts"],
            "image_status_counts": metadata["image_status_counts"],
            "ordered_status_counts": metadata["ordered_status_counts"],
        }
        results.append(result)
        status_counts[terminal_state] += 1
        run_totals[terminal_state] += 1
        run_totals["succeeded"] += 1
        for key, value in result["counts"].items():
            if key != "asset_references_reconciled":
                bundle_totals[key] += value
        _merge_counts(table_counts, metadata["table_status_counts"])
        _merge_counts(image_counts, metadata["image_status_counts"])
        _merge_counts(ordered_counts, metadata["ordered_status_counts"])

    passed = (
        run_totals["succeeded"] == run_totals["requested"]
        and run_totals["failed"] == 0
    )
    artifact_rows = [
        {
            "artifact_set_id": row.get("artifact_set_id"),
            "doc_id": row["doc_id"],
            "metadata_sha256": row.get("metadata_sha256"),
        }
        for row in results
    ]
    report = {
        "schema_version": VISUAL_CORPUS_SCHEMA_VERSION,
        "run_id": run_id,
        "mode": mode,
        "selection_sha256": selection_sha256,
        "config_sha256": config_sha256,
        "source_manifest_sha256": source_manifest_sha256,
        "table_layout_artifact_sha256": table_layout_artifact_sha256,
        "rhwp_binary_sha256": expected_rhwp_sha256,
        "selected_documents": sorted(seen),
        "passed": passed,
        "document_status_counts": {
            name: status_counts.get(name, 0)
            for name in ("materialized", "reused", "failed")
        },
        "totals": {
            name: run_totals.get(name, 0)
            for name in ("requested", "succeeded", "materialized", "reused", "failed")
        },
        "bundle_totals": {
            **{
                name: bundle_totals.get(name, 0)
                for name in (
                    "page_count",
                    "tables",
                    "images",
                    "ordered_occurrences",
                    "asset_count",
                    "asset_reference_count",
                    "asset_bytes",
                )
            },
            "asset_references_reconciled": passed,
        },
        "table_status_counts": dict(sorted(table_counts.items())),
        "image_status_counts": dict(sorted(image_counts.items())),
        "ordered_status_counts": dict(sorted(ordered_counts.items())),
        "artifact_set_digest": _canonical_hash(artifact_rows),
        "documents": results,
    }
    if resolved_report is not None:
        write_json(resolved_report, report)
    if stream is not None:
        stream.write(canonical_json(report) + "\n")
    return report


def load_hwp_visual_documents(
    *,
    data_dir: Path,
    manifest_path: Path,
    blocks_dir: Path,
    layout_path: Path,
    doc_ids: Sequence[str] | None = None,
    expected_hwp: int = 94,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Load hash-verified runner inputs without leaking source labels."""

    data_dir = data_dir.resolve(strict=True)
    manifest_path = require_within(
        manifest_path, data_dir, "visual_corpus_manifest_outside_data_dir"
    )
    blocks_dir = require_within(
        blocks_dir, data_dir, "visual_corpus_blocks_outside_data_dir"
    )
    layout_path = require_within(
        layout_path, data_dir, "visual_corpus_layout_outside_data_dir"
    )
    rows = read_jsonl(manifest_path)
    eligible: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        doc_id = row.get("doc_id")
        if not isinstance(doc_id, str) or _DOC_ID_RE.fullmatch(doc_id) is None:
            raise ValueError("visual_corpus_manifest_invalid")
        if doc_id in eligible:
            raise ValueError("visual_corpus_manifest_duplicate")
        if (
            row.get("status") == "ok"
            and row.get("index_eligible") is True
            and row.get("extension") == ".hwp"
        ):
            eligible[doc_id] = row
    if len(eligible) != expected_hwp:
        raise ValueError("visual_corpus_hwp_count_mismatch")
    requested = sorted(doc_ids) if doc_ids is not None else sorted(eligible)
    if (
        not requested
        or len(requested) != len(set(requested))
        or any(doc_id not in eligible for doc_id in requested)
    ):
        raise ValueError("visual_corpus_selection_invalid")

    layouts_by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in read_jsonl(layout_path):
        doc_id = record.get("doc_id")
        if doc_id not in eligible:
            raise ValueError("visual_corpus_layout_doc_invalid")
        layouts_by_doc[str(doc_id)].append(record)
    documents: list[dict[str, Any]] = []
    for doc_id in requested:
        row = eligible[doc_id]
        source_path = require_within(
            data_dir / str(row.get("source_relpath", "")),
            data_dir,
            "visual_corpus_source_outside_data_dir",
        )
        source_sha256 = require_sha256(
            row.get("sha256"), "visual_corpus_source_hash_invalid"
        )
        if (
            not source_path.is_file()
            or source_path.is_symlink()
            or sha256_file(source_path) != source_sha256
        ):
            raise ValueError("visual_corpus_source_hash_mismatch")
        block_path = require_within(
            blocks_dir / f"{doc_id}.jsonl",
            blocks_dir,
            "visual_corpus_block_outside_blocks_dir",
        )
        blocks = read_jsonl(block_path)
        layout_records = sorted(
            layouts_by_doc.get(doc_id, []), key=lambda value: str(value.get("block_id", ""))
        )
        table_ids = {
            block.get("block_id")
            for block in blocks
            if block.get("block_type") == "table"
        }
        if (
            len(table_ids) != len(layout_records)
            or table_ids != {record.get("block_id") for record in layout_records}
        ):
            raise ValueError("visual_corpus_layout_reconciliation_failed")
        page_count = row.get("page_count")
        if not isinstance(page_count, int) or isinstance(page_count, bool) or page_count < 0:
            raise ValueError("visual_corpus_page_count_invalid")
        documents.append(
            {
                "doc_id": doc_id,
                "source_path": source_path,
                "expected_source_sha256": source_sha256,
                "page_count": page_count,
                "blocks": blocks,
                "layout_records": layout_records,
            }
        )
    return documents, {
        "source_manifest_sha256": sha256_file(manifest_path),
        "table_layout_artifact_sha256": sha256_file(layout_path),
    }


__all__ = [
    "VISUAL_CORPUS_CONFIG",
    "VISUAL_CORPUS_CONFIG_SHA256",
    "VISUAL_CORPUS_METHOD",
    "VISUAL_CORPUS_SCHEMA_VERSION",
    "build_hwp_visual_structural_stats",
    "load_hwp_visual_documents",
    "run_hwp_visual_corpus",
    "select_hwp_visual_samples",
]
