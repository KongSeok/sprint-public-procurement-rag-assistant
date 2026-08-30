from __future__ import annotations

import json
import math
import re
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from midprojectrag.ingest.common import canonical_json, sha256_text
from midprojectrag.ingest.rhwp_adapter import _run_bounded


LAYOUT_OVERLAY_SCHEMA_VERSION = "1.0"
COORDINATE_SPACE = "rhwp_css_px_96dpi"
MAX_PAGES = 10_000
MAX_RENDER_NODES = 1_000_000
MAX_RENDER_DEPTH = 256
MAX_RENDER_TREE_FILE_BYTES = 64 * 1024 * 1024
MAX_RENDER_TREE_TOTAL_BYTES = 512 * 1024 * 1024
MAX_LAYOUT_STDOUT_BYTES = 64 * 1024 * 1024

_DOC_ID_PATTERN = re.compile(r"^doc_[0-9a-f]{24}$")
_BLOCK_ID_PATTERN = re.compile(r"^block_[0-9a-f]{24}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_RENDER_TREE_FILENAME_PATTERN = re.compile(r"^render_tree_([0-9]{3,})\.json$")
_BBOX_FIELDS = ("x", "y", "w", "h")

RenderKey = tuple[int, int, int]


def _is_integer(value: Any, *, minimum: int = 0) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= minimum
    )


def _require_integer(value: Any, error_code: str, *, minimum: int = 0) -> int:
    if not _is_integer(value, minimum=minimum):
        raise ValueError(error_code)
    return value


def _render_key(value: RenderKey) -> dict[str, int]:
    section, paragraph, control = value
    return {
        "section": section,
        "paragraph": paragraph,
        "control": control,
    }


def _normalize_bbox(value: Any, error_code: str) -> dict[str, float]:
    if not isinstance(value, Mapping) or set(value) != set(_BBOX_FIELDS):
        raise ValueError(error_code)
    normalized: dict[str, float] = {}
    for field in _BBOX_FIELDS:
        raw = value.get(field)
        if (
            not isinstance(raw, (int, float))
            or isinstance(raw, bool)
            or not math.isfinite(float(raw))
        ):
            raise ValueError(error_code)
        normalized[field] = float(raw)
    if normalized["w"] < 0 or normalized["h"] < 0:
        raise ValueError(error_code)
    return normalized


def _bbox_within_page(
    bbox: Mapping[str, float], page_bbox: Mapping[str, float]
) -> bool:
    tolerance = 1e-6
    return (
        bbox["x"] >= page_bbox["x"] - tolerance
        and bbox["y"] >= page_bbox["y"] - tolerance
        and bbox["x"] + bbox["w"]
        <= page_bbox["x"] + page_bbox["w"] + tolerance
        and bbox["y"] + bbox["h"]
        <= page_bbox["y"] + page_bbox["h"] + tolerance
    )


def _parse_dump_pages(
    payload: Mapping[str, Any],
) -> tuple[dict[int, int], set[RenderKey]]:
    if payload.get("schemaVersion") != "1.0":
        raise ValueError("dump_pages_schema_invalid")
    page_count = _require_integer(
        payload.get("pageCount"), "dump_pages_count_invalid"
    )
    if page_count > MAX_PAGES:
        raise ValueError("dump_pages_count_exceeded")
    raw_pages = payload.get("pages")
    if not isinstance(raw_pages, list) or len(raw_pages) != page_count:
        raise ValueError("dump_pages_envelope_invalid")

    sections: dict[int, int] = {}
    anchors: set[RenderKey] = set()
    for raw_page in raw_pages:
        if not isinstance(raw_page, Mapping):
            raise ValueError("dump_page_invalid")
        page_index = _require_integer(
            raw_page.get("pageIndex"), "dump_page_index_invalid"
        )
        if page_index >= page_count or page_index in sections:
            raise ValueError("dump_page_index_invalid")
        section = _require_integer(
            raw_page.get("section"), "dump_page_section_invalid"
        )
        sections[page_index] = section

        columns = raw_page.get("columns")
        if not isinstance(columns, list):
            raise ValueError("dump_page_columns_invalid")
        for column in columns:
            if not isinstance(column, Mapping):
                raise ValueError("dump_page_column_invalid")
            items = column.get("items")
            if not isinstance(items, list):
                raise ValueError("dump_page_items_invalid")
            for item in items:
                if not isinstance(item, Mapping):
                    raise ValueError("dump_page_item_invalid")
                if item.get("kind") != "table":
                    continue
                paragraph = _require_integer(
                    item.get("paraIndex"), "dump_table_paragraph_invalid"
                )
                control = _require_integer(
                    item.get("controlIndex"), "dump_table_control_invalid"
                )
                anchors.add((section, paragraph, control))

    if set(sections) != set(range(page_count)):
        raise ValueError("dump_page_index_gap")
    return sections, anchors


def _body_nodes(page_tree: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if page_tree.get("type") != "Page":
        raise ValueError("render_tree_page_invalid")
    children = page_tree.get("children")
    if not isinstance(children, list):
        raise ValueError("render_tree_children_invalid")
    bodies = [
        child
        for child in children
        if isinstance(child, Mapping) and child.get("type") == "Body"
    ]
    if len(bodies) != 1:
        raise ValueError("render_tree_body_invalid")
    return bodies


def _walk_body_tables(
    bodies: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    tables: list[Mapping[str, Any]] = []
    stack: list[tuple[Mapping[str, Any], int]] = [
        (body, 0) for body in reversed(bodies)
    ]
    seen_objects: set[int] = set()
    visited = 0
    while stack:
        node, depth = stack.pop()
        if depth > MAX_RENDER_DEPTH:
            raise ValueError("render_tree_depth_exceeded")
        identity = id(node)
        if identity in seen_objects:
            raise ValueError("render_tree_cycle_or_alias")
        seen_objects.add(identity)
        visited += 1
        if visited > MAX_RENDER_NODES:
            raise ValueError("render_tree_node_limit_exceeded")

        if node.get("type") == "Table":
            tables.append(node)
            # Nested table nodes belong to cells of this top-level body table.
            # They are mapped through the canonical parent structure, not as
            # independent top-level candidates sharing the same render key.
            continue
        children = node.get("children", [])
        if not isinstance(children, list):
            raise ValueError("render_tree_children_invalid")
        for child in reversed(children):
            if not isinstance(child, Mapping):
                raise ValueError("render_tree_child_invalid")
            stack.append((child, depth + 1))
    return tables


def _collect_render_tables(
    render_trees: Mapping[int, Mapping[str, Any]],
    sections: Mapping[int, int],
) -> dict[RenderKey, list[dict[str, Any]]]:
    if set(render_trees) != set(sections):
        raise ValueError("render_tree_page_set_mismatch")

    by_key: dict[RenderKey, list[dict[str, Any]]] = {}
    fingerprints: set[tuple[Any, ...]] = set()
    for page_index in sorted(render_trees):
        if not _is_integer(page_index):
            raise ValueError("render_tree_page_index_invalid")
        page_tree = render_trees[page_index]
        if not isinstance(page_tree, Mapping):
            raise ValueError("render_tree_page_invalid")
        embedded_page_index = page_tree.get("pageIndex")
        if embedded_page_index is not None and embedded_page_index != page_index:
            raise ValueError("render_tree_page_index_mismatch")
        page_bbox = _normalize_bbox(
            page_tree.get("bbox"), "render_tree_page_bbox_invalid"
        )
        section = sections[page_index]
        for node in _walk_body_tables(_body_nodes(page_tree)):
            paragraph = node.get("pi")
            control = node.get("ci")
            rows = node.get("rows")
            cols = node.get("cols")
            if not all(
                _is_integer(value)
                for value in (paragraph, control, rows, cols)
            ) or rows == 0 or cols == 0:
                continue
            try:
                bbox = _normalize_bbox(
                    node.get("bbox"), "render_tree_table_bbox_invalid"
                )
            except ValueError:
                # A malformed visual node is not strong enough evidence to
                # attach a page or bbox to a canonical source table.
                continue
            key = (section, paragraph, control)
            fingerprint = (
                key,
                page_index,
                rows,
                cols,
                *(bbox[field] for field in _BBOX_FIELDS),
            )
            if fingerprint in fingerprints:
                continue
            fingerprints.add(fingerprint)
            by_key.setdefault(key, []).append(
                {
                    "page": page_index + 1,
                    "bbox": bbox,
                    "page_bbox": page_bbox,
                    "bbox_valid": _bbox_within_page(bbox, page_bbox),
                    "rows": rows,
                    "cols": cols,
                }
            )
    return by_key


def _is_nonbody_table(structure: Mapping[str, Any]) -> bool:
    path = structure.get("container_path")
    if path is None or path == []:
        return False
    if not isinstance(path, list):
        raise ValueError("table_container_path_invalid")
    for item in path:
        if not isinstance(item, Mapping) or not isinstance(item.get("kind"), str):
            raise ValueError("table_container_path_invalid")
    return True


def _wrapper_dimensions(structure: Mapping[str, Any]) -> tuple[int, int] | None:
    if structure.get("rows") != 1 or structure.get("cols") != 1:
        return None
    cells = structure.get("cells")
    if not isinstance(cells, list) or len(cells) != 1:
        return None
    cell = cells[0]
    if not isinstance(cell, Mapping):
        return None
    nested = cell.get("nested")
    if not isinstance(nested, list) or len(nested) != 1:
        return None
    nested_table = nested[0]
    if not isinstance(nested_table, Mapping):
        return None
    rows = nested_table.get("rows")
    cols = nested_table.get("cols")
    if not _is_integer(rows, minimum=1) or not _is_integer(cols, minimum=1):
        return None
    return rows, cols


def _canonical_table_identity(
    block: Mapping[str, Any], expected_doc_id: str
) -> tuple[str, str, Mapping[str, Any], RenderKey]:
    if block.get("doc_id") != expected_doc_id:
        raise ValueError("table_block_doc_id_mismatch")
    block_id = block.get("block_id")
    if not isinstance(block_id, str) or _BLOCK_ID_PATTERN.fullmatch(block_id) is None:
        raise ValueError("table_block_id_invalid")
    structure = block.get("table_structure")
    if not isinstance(structure, Mapping):
        raise ValueError("table_structure_invalid")
    structure_sha256 = block.get("structure_sha256")
    if (
        not isinstance(structure_sha256, str)
        or _SHA256_PATTERN.fullmatch(structure_sha256) is None
        or sha256_text(canonical_json(structure)) != structure_sha256
    ):
        raise ValueError("table_structure_hash_invalid")
    section = _require_integer(
        structure.get("section"), "table_section_invalid"
    )
    paragraph = _require_integer(
        structure.get("paragraph"), "table_paragraph_invalid"
    )
    control = _require_integer(
        structure.get("control"), "table_control_invalid"
    )
    _require_integer(structure.get("rows"), "table_rows_invalid", minimum=1)
    _require_integer(structure.get("cols"), "table_cols_invalid", minimum=1)
    return block_id, structure_sha256, structure, (section, paragraph, control)


def build_table_layout_overlay(
    *,
    doc_id: str,
    blocks: Sequence[Mapping[str, Any]],
    dump_pages: Mapping[str, Any],
    render_trees: Mapping[int, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Join canonical top-level HWP tables to verified rhwp page geometry.

    `page_start` and `page_end` are populated only when a body render node has
    the same structural key and compatible dimensions. A dump-pages paragraph
    hit alone is deliberately reported as a candidate with null page fields.
    """
    if not isinstance(doc_id, str) or _DOC_ID_PATTERN.fullmatch(doc_id) is None:
        raise ValueError("doc_id_invalid")
    if not isinstance(blocks, Sequence) or isinstance(blocks, (str, bytes)):
        raise ValueError("table_blocks_invalid")
    if not isinstance(dump_pages, Mapping):
        raise ValueError("dump_pages_invalid")
    if not isinstance(render_trees, Mapping):
        raise ValueError("render_trees_invalid")

    sections, anchors = _parse_dump_pages(dump_pages)
    render_tables = _collect_render_tables(render_trees, sections)
    records: list[dict[str, Any]] = []
    seen_block_ids: set[str] = set()

    if any(not isinstance(block, Mapping) for block in blocks):
        raise ValueError("table_block_invalid")
    table_blocks = [block for block in blocks if block.get("block_type") == "table"]
    for block in sorted(
        table_blocks,
        key=lambda value: (
            str(value.get("block_id", "")),
            str(value.get("structure_sha256", "")),
        ),
    ):
        block_id, structure_sha256, structure, key = _canonical_table_identity(
            block, doc_id
        )
        if block_id in seen_block_ids:
            raise ValueError("duplicate_table_block_id")
        seen_block_ids.add(block_id)

        base: dict[str, Any] = {
            "schema_version": LAYOUT_OVERLAY_SCHEMA_VERSION,
            "doc_id": doc_id,
            "block_id": block_id,
            "structure_sha256": structure_sha256,
            "page_start": None,
            "page_end": None,
            "page_bboxes": [],
            "coordinate_space": COORDINATE_SPACE,
            "render_key": _render_key(key),
            "wrapper_flattened": False,
            "anchor_present": key in anchors,
        }
        if _is_nonbody_table(structure):
            base["status"] = "nonbody_unlinked"
            records.append(base)
            continue

        rows = structure["rows"]
        cols = structure["cols"]
        candidates = render_tables.get(key, [])
        matches = [
            candidate
            for candidate in candidates
            if (candidate["rows"], candidate["cols"]) == (rows, cols)
        ]
        wrapper_flattened = False
        if not matches:
            wrapper_dimensions = _wrapper_dimensions(structure)
            if wrapper_dimensions is not None:
                matches = [
                    candidate
                    for candidate in candidates
                    if (candidate["rows"], candidate["cols"])
                    == wrapper_dimensions
                ]
                wrapper_flattened = bool(matches)

        if not matches:
            # dump-pages is useful for diagnosing a likely paragraph anchor,
            # but it cannot prove the rendered page geometry. Never promote
            # that candidate into page_start/page_end.
            base["status"] = "paragraph_anchor_candidate"
            records.append(base)
            continue

        page_bboxes = [
            {
                "page": candidate["page"],
                "bbox": candidate["bbox"],
                "page_bbox": candidate["page_bbox"],
                "bbox_valid": candidate["bbox_valid"],
            }
            for candidate in sorted(
                matches,
                key=lambda candidate: (
                    candidate["page"],
                    *(candidate["bbox"][field] for field in _BBOX_FIELDS),
                ),
            )
        ]
        pages = [value["page"] for value in page_bboxes]
        base.update(
            {
                "status": "verified_render",
                "page_start": min(pages),
                "page_end": max(pages),
                "page_bboxes": page_bboxes,
                "wrapper_flattened": wrapper_flattened,
            }
        )
        records.append(base)
    return records


def load_render_tree_directory(
    directory: Path,
    *,
    max_file_bytes: int = MAX_RENDER_TREE_FILE_BYTES,
    max_total_bytes: int = MAX_RENDER_TREE_TOTAL_BYTES,
) -> dict[int, dict[str, Any]]:
    """Load `rhwp export-render-tree` pages with strict numbering and bounds."""
    directory = directory.resolve()
    if not directory.is_dir():
        raise ValueError("render_tree_directory_invalid")
    if max_file_bytes <= 0 or max_total_bytes <= 0:
        raise ValueError("render_tree_size_limit_invalid")

    pages: dict[int, dict[str, Any]] = {}
    total_bytes = 0
    candidates = sorted(
        path for path in directory.iterdir() if path.name.startswith("render_tree_")
    )
    if not candidates:
        raise ValueError("render_tree_files_missing")
    for path in candidates:
        match = _RENDER_TREE_FILENAME_PATTERN.fullmatch(path.name)
        if match is None or not path.is_file() or path.is_symlink():
            raise ValueError("render_tree_filename_invalid")
        ordinal = int(match.group(1))
        if ordinal < 1 or match.group(1) != f"{ordinal:03d}":
            raise ValueError("render_tree_filename_invalid")
        page_index = ordinal - 1
        if page_index in pages:
            raise ValueError("render_tree_page_duplicate")
        size = path.stat().st_size
        if size > max_file_bytes:
            raise ValueError("render_tree_file_too_large")
        total_bytes += size
        if total_bytes > max_total_bytes:
            raise ValueError("render_tree_total_too_large")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("render_tree_json_invalid") from error
        if not isinstance(payload, dict) or payload.get("type") != "Page":
            raise ValueError("render_tree_page_invalid")
        embedded_page_index = payload.get("pageIndex")
        if embedded_page_index is not None:
            if not _is_integer(embedded_page_index):
                raise ValueError("render_tree_page_index_invalid")
            if embedded_page_index != page_index:
                raise ValueError("render_tree_page_index_mismatch")
        pages[page_index] = payload

    if len(pages) > MAX_PAGES:
        raise ValueError("render_tree_page_limit_exceeded")
    if set(pages) != set(range(len(pages))):
        raise ValueError("render_tree_page_index_gap")
    return dict(sorted(pages.items()))


def load_rhwp_layout_inputs(
    command: str,
    source_path: Path,
    *,
    timeout_seconds: int = 120,
) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    """Run pinned rhwp layout exports without retaining unbounded subprocess output."""

    if (
        not isinstance(command, str)
        or not command
        or not Path(command).is_absolute()
        or not Path(command).is_file()
    ):
        raise ValueError("rhwp_layout_command_invalid")
    source_path = source_path.resolve()
    if not source_path.is_file():
        raise ValueError("rhwp_layout_source_invalid")
    if (
        not isinstance(timeout_seconds, int)
        or isinstance(timeout_seconds, bool)
        or timeout_seconds < 1
    ):
        raise ValueError("rhwp_layout_timeout_invalid")

    returncode, stdout, run_error = _run_bounded(
        [command, "dump-pages", str(source_path), "--json"],
        timeout_seconds=timeout_seconds,
        max_stdout_bytes=MAX_LAYOUT_STDOUT_BYTES,
    )
    if run_error is not None or returncode != 0:
        raise ValueError("rhwp_dump_pages_failed")
    try:
        dump_pages = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("rhwp_dump_pages_invalid_json") from error
    if not isinstance(dump_pages, dict):
        raise ValueError("rhwp_dump_pages_invalid_json")

    with tempfile.TemporaryDirectory(prefix="midprojectrag-layout-") as directory:
        returncode, _stdout, run_error = _run_bounded(
            [command, "export-render-tree", str(source_path), "-o", directory],
            timeout_seconds=timeout_seconds,
            max_stdout_bytes=1024 * 1024,
        )
        if run_error is not None or returncode != 0:
            raise ValueError("rhwp_render_tree_failed")
        render_trees = load_render_tree_directory(Path(directory))
    return dump_pages, render_trees


__all__ = [
    "COORDINATE_SPACE",
    "LAYOUT_OVERLAY_SCHEMA_VERSION",
    "build_table_layout_overlay",
    "load_rhwp_layout_inputs",
    "load_render_tree_directory",
]
