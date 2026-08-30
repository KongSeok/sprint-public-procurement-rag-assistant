from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from midprojectrag.ingest.common import canonical_json, sha256_text


VISUAL_CONTEXT_SCHEMA_VERSION = "1.0"
COORDINATE_SPACE = "rhwp_css_px_96dpi"
EXTRACTION_METHOD = "rhwp_render_tree_body_v1"
MAX_CONTEXT_CHARS = 500
MAX_PAGES = 10_000
MAX_RENDER_NODES = 1_000_000
MAX_RENDER_DEPTH = 256
SCHEDULE_BOUNDARY_TOLERANCE = 0.5

_DOC_ID_PATTERN = re.compile(r"^doc_[0-9a-f]{24}$")
_BLOCK_ID_PATTERN = re.compile(r"^block_[0-9a-f]{24}$")
_IMAGE_OCCURRENCE_ID_PATTERN = re.compile(r"^occ_[0-9a-f]{24}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_PERIOD_PATTERN = re.compile(r"^M(?:\+([1-9][0-9]*))?$")
_BBOX_FIELDS = ("x", "y", "w", "h")

RenderKey = tuple[int, int, int]


def _is_integer(value: Any, *, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _require_integer(value: Any, error_code: str, *, minimum: int = 0) -> int:
    if not _is_integer(value, minimum=minimum):
        raise ValueError(error_code)
    return value


def _normalize_bbox(value: Any, error_code: str) -> dict[str, float]:
    if not isinstance(value, Mapping) or set(value) != set(_BBOX_FIELDS):
        raise ValueError(error_code)
    result: dict[str, float] = {}
    for field in _BBOX_FIELDS:
        raw = value.get(field)
        if (
            not isinstance(raw, (int, float))
            or isinstance(raw, bool)
            or not math.isfinite(float(raw))
        ):
            raise ValueError(error_code)
        result[field] = float(raw)
    if result["w"] <= 0 or result["h"] <= 0:
        raise ValueError(error_code)
    return result


def _bbox_equal(left: Mapping[str, float], right: Mapping[str, float]) -> bool:
    return all(abs(left[field] - right[field]) <= 1e-6 for field in _BBOX_FIELDS)


def _bbox_contains(outer: Mapping[str, float], inner: Mapping[str, float]) -> bool:
    tolerance = 1e-6
    return (
        inner["x"] >= outer["x"] - tolerance
        and inner["y"] >= outer["y"] - tolerance
        and inner["x"] + inner["w"] <= outer["x"] + outer["w"] + tolerance
        and inner["y"] + inner["h"] <= outer["y"] + outer["h"] + tolerance
    )


def _render_key(key: RenderKey) -> dict[str, int]:
    section, paragraph, control = key
    return {"section": section, "paragraph": paragraph, "control": control}


def _parse_dump_pages(payload: Mapping[str, Any]) -> dict[int, int]:
    if payload.get("schemaVersion") != "1.0":
        raise ValueError("dump_pages_schema_invalid")
    page_count = _require_integer(payload.get("pageCount"), "dump_pages_count_invalid")
    if page_count > MAX_PAGES:
        raise ValueError("dump_pages_count_exceeded")
    pages = payload.get("pages")
    if not isinstance(pages, list) or len(pages) != page_count:
        raise ValueError("dump_pages_envelope_invalid")

    sections: dict[int, int] = {}
    for page in pages:
        if not isinstance(page, Mapping):
            raise ValueError("dump_page_invalid")
        page_index = _require_integer(page.get("pageIndex"), "dump_page_index_invalid")
        if page_index >= page_count or page_index in sections:
            raise ValueError("dump_page_index_invalid")
        sections[page_index] = _require_integer(
            page.get("section"), "dump_page_section_invalid"
        )
    if set(sections) != set(range(page_count)):
        raise ValueError("dump_page_index_gap")
    return sections


def _body(page: Mapping[str, Any], page_index: int) -> tuple[Mapping[str, Any], dict[str, float]]:
    if page.get("type") != "Page":
        raise ValueError("render_tree_page_invalid")
    embedded_index = page.get("pageIndex")
    if embedded_index is not None and embedded_index != page_index:
        raise ValueError("render_tree_page_index_mismatch")
    page_bbox = _normalize_bbox(page.get("bbox"), "render_tree_page_bbox_invalid")
    children = page.get("children")
    if not isinstance(children, list):
        raise ValueError("render_tree_children_invalid")
    bodies = [
        child
        for child in children
        if isinstance(child, Mapping) and child.get("type") == "Body"
    ]
    if len(bodies) != 1:
        raise ValueError("render_tree_body_invalid")
    return bodies[0], page_bbox


def _children(node: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = node.get("children", [])
    if not isinstance(raw, list):
        raise ValueError("render_tree_children_invalid")
    if any(not isinstance(child, Mapping) for child in raw):
        raise ValueError("render_tree_child_invalid")
    return list(raw)


def _text_line_payload(
    line: Mapping[str, Any],
    *,
    shared_seen: set[int],
    counter: list[int],
    starting_depth: int,
) -> tuple[str, list[Mapping[str, Any]]]:
    text_parts: list[str] = []
    images: list[Mapping[str, Any]] = []
    stack = [(child, starting_depth + 1) for child in reversed(_children(line))]
    while stack:
        node, depth = stack.pop()
        if depth > MAX_RENDER_DEPTH:
            raise ValueError("render_tree_depth_exceeded")
        identity = id(node)
        if identity in shared_seen:
            raise ValueError("render_tree_cycle_or_alias")
        shared_seen.add(identity)
        counter[0] += 1
        if counter[0] > MAX_RENDER_NODES:
            raise ValueError("render_tree_node_limit_exceeded")
        node_type = node.get("type")
        if node_type == "TextRun":
            text = node.get("text")
            if not isinstance(text, str):
                raise ValueError("render_tree_text_invalid")
            text_parts.append(text)
            continue
        if node_type == "Image":
            images.append(node)
            continue
        if node_type == "Table":
            # A table nested in a text line is still atomic. Its text must not
            # leak into the line that becomes adjacent-page context.
            continue
        for child in reversed(_children(node)):
            stack.append((child, depth + 1))
    return "".join(text_parts).strip(), images


def _context_record(
    *, section: int, node: Mapping[str, Any], text: str
) -> dict[str, Any]:
    paragraph = _require_integer(node.get("pi"), "render_tree_text_paragraph_invalid")
    return {
        "text": text[:MAX_CONTEXT_CHARS],
        "bbox": _normalize_bbox(node.get("bbox"), "render_tree_text_bbox_invalid"),
        "render_key": {"section": section, "paragraph": paragraph},
        "method": "nearest_prior_top_level_textline",
    }


def _atomic_body_flow(
    *, page_index: int, section: int, page: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], Mapping[str, Any]]:
    body, page_bbox = _body(page, page_index)
    events: list[dict[str, Any]] = []
    seen: set[int] = set()
    counter = [0]
    preceding_text: dict[str, Any] | None = None
    stack: list[tuple[Mapping[str, Any], int]] = [(body, 0)]

    while stack:
        node, depth = stack.pop()
        if depth > MAX_RENDER_DEPTH:
            raise ValueError("render_tree_depth_exceeded")
        identity = id(node)
        if identity in seen:
            raise ValueError("render_tree_cycle_or_alias")
        seen.add(identity)
        counter[0] += 1
        if counter[0] > MAX_RENDER_NODES:
            raise ValueError("render_tree_node_limit_exceeded")

        node_type = node.get("type")
        if node_type == "Table":
            events.append(
                {
                    "kind": "table",
                    "node": node,
                    "sequence_in_page": len(events),
                    "bbox": _normalize_bbox(
                        node.get("bbox"), "render_tree_table_bbox_invalid"
                    ),
                    "preceding_text": preceding_text,
                }
            )
            # Critical ordering rule: cell TextLine nodes are not top-level
            # context and cannot be emitted after their enclosing table.
            continue

        if node_type == "TextLine":
            text, images = _text_line_payload(
                node,
                shared_seen=seen,
                counter=counter,
                starting_depth=depth,
            )
            if text:
                preceding_text = _context_record(section=section, node=node, text=text)
                events.append(
                    {
                        "kind": "text",
                        "node": node,
                        "sequence_in_page": len(events),
                        "bbox": preceding_text["bbox"],
                        "preceding_text": preceding_text,
                        "text": preceding_text["text"],
                    }
                )
            for image in images:
                events.append(
                    {
                        "kind": "image",
                        "node": image,
                        "sequence_in_page": len(events),
                        "bbox": _normalize_bbox(
                            image.get("bbox"), "render_tree_image_bbox_invalid"
                        ),
                        "preceding_text": preceding_text,
                    }
                )
            continue

        if node_type == "Image":
            events.append(
                {
                    "kind": "image",
                    "node": node,
                    "sequence_in_page": len(events),
                    "bbox": _normalize_bbox(
                        node.get("bbox"), "render_tree_image_bbox_invalid"
                    ),
                    "preceding_text": preceding_text,
                }
            )
            continue

        for child in reversed(_children(node)):
            stack.append((child, depth + 1))
    return events, page_bbox


def _validated_flows(
    *, dump_pages: Mapping[str, Any], render_trees: Mapping[int, Mapping[str, Any]]
) -> tuple[
    dict[int, int],
    dict[int, list[dict[str, Any]]],
    dict[int, dict[str, float]],
]:
    if not isinstance(dump_pages, Mapping):
        raise ValueError("dump_pages_invalid")
    if not isinstance(render_trees, Mapping):
        raise ValueError("render_trees_invalid")
    sections = _parse_dump_pages(dump_pages)
    if set(render_trees) != set(sections):
        raise ValueError("render_tree_page_set_mismatch")
    flows: dict[int, list[dict[str, Any]]] = {}
    page_bboxes: dict[int, dict[str, float]] = {}
    for page_index in sorted(render_trees):
        if not _is_integer(page_index):
            raise ValueError("render_tree_page_index_invalid")
        page = render_trees[page_index]
        if not isinstance(page, Mapping):
            raise ValueError("render_tree_page_invalid")
        events, page_bbox = _atomic_body_flow(
            page_index=page_index,
            section=sections[page_index],
            page=page,
        )
        flows[page_index] = events
        page_bboxes[page_index] = dict(page_bbox)
    return sections, flows, page_bboxes


def _canonical_table(
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
    key = (
        _require_integer(structure.get("section"), "table_section_invalid"),
        _require_integer(structure.get("paragraph"), "table_paragraph_invalid"),
        _require_integer(structure.get("control"), "table_control_invalid"),
    )
    _require_integer(structure.get("rows"), "table_rows_invalid", minimum=1)
    _require_integer(structure.get("cols"), "table_cols_invalid", minimum=1)
    return block_id, structure_sha256, structure, key


def _layout_index(
    layout_records: Sequence[Mapping[str, Any]], *, doc_id: str
) -> dict[str, Mapping[str, Any]]:
    if not isinstance(layout_records, Sequence) or isinstance(
        layout_records, (str, bytes)
    ):
        raise ValueError("table_layout_records_invalid")
    result: dict[str, Mapping[str, Any]] = {}
    for record in layout_records:
        if not isinstance(record, Mapping):
            raise ValueError("table_layout_record_invalid")
        if record.get("doc_id") != doc_id:
            raise ValueError("table_layout_doc_id_mismatch")
        block_id = record.get("block_id")
        if not isinstance(block_id, str) or _BLOCK_ID_PATTERN.fullmatch(block_id) is None:
            raise ValueError("table_layout_block_id_invalid")
        if block_id in result:
            raise ValueError("duplicate_table_layout_block_id")
        result[block_id] = record
    return result


def _layout_occurrences(
    *,
    record: Mapping[str, Any],
    key: RenderKey,
    structure: Mapping[str, Any],
    flows: Mapping[int, Sequence[dict[str, Any]]],
    sections: Mapping[int, int],
    page_bboxes: Mapping[int, Mapping[str, float]],
) -> list[tuple[int, dict[str, Any]]]:
    expected_key = _render_key(key)
    if record.get("render_key") != expected_key:
        raise ValueError("table_layout_render_key_mismatch")
    raw_page_bboxes = record.get("page_bboxes")
    if not isinstance(raw_page_bboxes, list):
        raise ValueError("table_layout_page_bboxes_invalid")
    rows = structure["rows"]
    cols = structure["cols"]
    page_start = _require_integer(
        record.get("page_start"), "table_layout_page_start_invalid", minimum=1
    )
    page_end = _require_integer(
        record.get("page_end"), "table_layout_page_end_invalid", minimum=1
    )
    if page_end < page_start:
        raise ValueError("table_layout_page_range_invalid")
    matches: list[tuple[int, dict[str, Any]]] = []
    seen: set[tuple[int, str]] = set()
    for raw in raw_page_bboxes:
        if not isinstance(raw, Mapping):
            raise ValueError("table_layout_page_bbox_invalid")
        page_number = _require_integer(
            raw.get("page"), "table_layout_page_invalid", minimum=1
        )
        page_index = page_number - 1
        if (
            page_number < page_start
            or page_number > page_end
            or sections.get(page_index) != key[0]
        ):
            return []
        bbox = _normalize_bbox(raw.get("bbox"), "table_layout_bbox_invalid")
        declared_page_bbox = _normalize_bbox(
            raw.get("page_bbox"), "table_layout_page_bbox_invalid"
        )
        bbox_valid = raw.get("bbox_valid")
        if not isinstance(bbox_valid, bool):
            raise ValueError("table_layout_bbox_valid_invalid")
        render_page_bbox = page_bboxes.get(page_index)
        if (
            render_page_bbox is None
            or not _bbox_equal(declared_page_bbox, render_page_bbox)
            or bbox_valid is not True
            or not _bbox_contains(declared_page_bbox, bbox)
        ):
            return []
        fingerprint = (page_number, canonical_json(bbox))
        if fingerprint in seen:
            raise ValueError("duplicate_table_layout_page_bbox")
        seen.add(fingerprint)
        candidates: list[dict[str, Any]] = []
        for event in flows.get(page_index, []):
            if event["kind"] != "table" or not _bbox_equal(event["bbox"], bbox):
                continue
            node = event["node"]
            if (
                node.get("pi") == key[1]
                and node.get("ci") == key[2]
                and node.get("rows") == rows
                and node.get("cols") == cols
            ):
                candidates.append(event)
        if len(candidates) != 1:
            return []
        matches.append((page_number, candidates[0]))
    pages = [page for page, _event in matches]
    if not pages or min(pages) != page_start or max(pages) != page_end:
        return []
    return matches


def _render_cells(
    *, table: Mapping[str, Any], page: int
) -> tuple[dict[tuple[int, int], dict[str, Any]], list[dict[str, Any]], set[int]]:
    rows = _require_integer(table.get("rows"), "render_tree_table_rows_invalid", minimum=1)
    cols = _require_integer(table.get("cols"), "render_tree_table_cols_invalid", minimum=1)
    table_bbox = _normalize_bbox(table.get("bbox"), "render_tree_table_bbox_invalid")
    cells: dict[tuple[int, int], dict[str, Any]] = {}
    backgrounds: list[dict[str, Any]] = []
    ambiguous_rows: set[int] = set()
    for child in _children(table):
        if child.get("type") != "Cell":
            continue
        row = _require_integer(child.get("row"), "render_tree_cell_row_invalid")
        col = _require_integer(child.get("col"), "render_tree_cell_col_invalid")
        if row >= rows or col >= cols or (row, col) in cells:
            ambiguous_rows.add(row)
            continue
        bbox = _normalize_bbox(child.get("bbox"), "render_tree_cell_bbox_invalid")
        if not _bbox_contains(table_bbox, bbox):
            ambiguous_rows.add(row)
        rects = [node for node in _children(child) if node.get("type") == "Rect"]
        valid_rects = []
        for rect in rects:
            rect_bbox = _normalize_bbox(
                rect.get("bbox"), "render_tree_rect_bbox_invalid"
            )
            if _bbox_contains(bbox, rect_bbox):
                valid_rects.append(rect_bbox)
            else:
                ambiguous_rows.add(row)
        if len(valid_rects) > 1:
            ambiguous_rows.add(row)
        cells[(row, col)] = {"node": child, "bbox": bbox}
        if valid_rects:
            backgrounds.append(
                {
                    "page": page,
                    "row": row,
                    "col": col,
                    "bbox": bbox,
                    "kind": "background_present",
                }
            )
    backgrounds.sort(
        key=lambda value: (
            value["page"],
            value["row"],
            value["col"],
            *(value["bbox"][field] for field in _BBOX_FIELDS),
        )
    )
    return cells, backgrounds, ambiguous_rows


def _canonical_cells(
    structure: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], bool]:
    rows = structure["rows"]
    cols = structure["cols"]
    raw_cells = structure.get("cells")
    if not isinstance(raw_cells, list):
        raise ValueError("table_cells_invalid")
    cells: list[dict[str, Any]] = []
    nested = bool(structure.get("container_path"))
    for raw in raw_cells:
        if not isinstance(raw, Mapping):
            raise ValueError("table_cell_invalid")
        row = _require_integer(raw.get("row"), "table_cell_row_invalid")
        col = _require_integer(raw.get("col"), "table_cell_col_invalid")
        row_span = _require_integer(
            raw.get("row_span"), "table_cell_row_span_invalid", minimum=1
        )
        col_span = _require_integer(
            raw.get("col_span"), "table_cell_col_span_invalid", minimum=1
        )
        text = raw.get("text")
        if not isinstance(text, str):
            raise ValueError("table_cell_text_invalid")
        if row + row_span > rows or col + col_span > cols:
            raise ValueError("table_cell_span_invalid")
        if raw.get("nested"):
            nested = True
        cells.append(
            {
                "row": row,
                "col": col,
                "row_span": row_span,
                "col_span": col_span,
                "text": text.strip(),
            }
        )
    return cells, nested


def _period_value(label: str) -> int | None:
    match = _PERIOD_PATTERN.fullmatch(label)
    if match is None:
        return None
    suffix = match.group(1)
    return 0 if suffix is None else int(suffix)


def _format_periods(periods: Sequence[str]) -> str:
    """Collapse only numerically contiguous, already-verified period runs."""
    parsed = [(label, _period_value(label)) for label in periods]
    if any(value is None for _label, value in parsed):
        return ", ".join(periods)
    runs: list[list[tuple[str, int]]] = []
    for label, raw_value in parsed:
        value = int(raw_value)
        if not runs or value != runs[-1][-1][1] + 1:
            runs.append([(label, value)])
        else:
            runs[-1].append((label, value))
    return ", ".join(
        run[0][0] if len(run) == 1 else f"{run[0][0]}~{run[-1][0]}"
        for run in runs
    )


def _schedule_facts(
    *,
    page: int,
    structure: Mapping[str, Any],
    render_cells: Mapping[tuple[int, int], Mapping[str, Any]],
    backgrounds: Sequence[Mapping[str, Any]],
    ambiguous_rows: set[int],
    globally_ambiguous: bool,
) -> list[dict[str, Any]]:
    canonical_cells, nested = _canonical_cells(structure)
    if globally_ambiguous or nested:
        return []

    header_groups: dict[int, list[dict[str, Any]]] = {}
    for cell in canonical_cells:
        period_value = _period_value(cell["text"])
        rendered = render_cells.get((cell["row"], cell["col"]))
        if period_value is None or rendered is None:
            continue
        header_groups.setdefault(cell["row"], []).append(
            {
                "label": cell["text"],
                "value": period_value,
                "bbox": rendered["bbox"],
            }
        )

    valid_groups: list[tuple[int, list[dict[str, Any]]]] = []
    for row, headers in header_groups.items():
        if row in ambiguous_rows:
            continue
        ordered = sorted(headers, key=lambda value: value["bbox"]["x"])
        values = [value["value"] for value in ordered]
        labels = [value["label"] for value in ordered]
        nonoverlapping = all(
            left["bbox"]["x"] + left["bbox"]["w"]
            <= right["bbox"]["x"] + SCHEDULE_BOUNDARY_TOLERANCE
            for left, right in zip(ordered, ordered[1:])
        )
        if (
            len(ordered) >= 2
            and len(set(labels)) == len(labels)
            and values[0] == 0
            and values == sorted(set(values))
            and nonoverlapping
        ):
            valid_groups.append((row, ordered))
    if len(valid_groups) != 1:
        return []
    header_row, headers = valid_groups[0]
    first_header_x = headers[0]["bbox"]["x"]

    canonical_by_anchor: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for cell in canonical_cells:
        canonical_by_anchor.setdefault((cell["row"], cell["col"]), []).append(cell)

    backgrounds_by_row: dict[int, list[Mapping[str, Any]]] = {}
    for background in backgrounds:
        backgrounds_by_row.setdefault(background["row"], []).append(background)

    facts: list[dict[str, Any]] = []
    for row in sorted(backgrounds_by_row):
        if row <= header_row or row in ambiguous_rows:
            continue
        row_backgrounds = backgrounds_by_row[row]
        # A background extending into the label/group area is presentation
        # shading, not unambiguous schedule evidence.
        if any(
            value["bbox"]["x"] + value["bbox"]["w"] / 2
            < first_header_x - SCHEDULE_BOUNDARY_TOLERANCE
            for value in row_backgrounds
        ):
            continue

        evidence: list[dict[str, Any]] = []
        row_invalid = False
        for background in row_backgrounds:
            center = background["bbox"]["x"] + background["bbox"]["w"] / 2
            matching_headers = [
                header
                for header in headers
                if header["bbox"]["x"] - SCHEDULE_BOUNDARY_TOLERANCE
                <= center
                <= header["bbox"]["x"]
                + header["bbox"]["w"]
                + SCHEDULE_BOUNDARY_TOLERANCE
            ]
            if not matching_headers:
                continue
            if len(matching_headers) != 1:
                row_invalid = True
                break
            canonical = canonical_by_anchor.get(
                (background["row"], background["col"]), []
            )
            if (
                len(canonical) != 1
                or canonical[0]["text"]
                or canonical[0]["row_span"] != 1
            ):
                row_invalid = True
                break
            evidence.append(
                {
                    "page": page,
                    "row": background["row"],
                    "col": background["col"],
                    "bbox": background["bbox"],
                    "period": matching_headers[0]["label"],
                }
            )
        if row_invalid or not evidence:
            continue

        labels: list[tuple[float, str]] = []
        for cell in canonical_cells:
            if cell["row"] != row or not cell["text"] or _period_value(cell["text"]) is not None:
                continue
            rendered = render_cells.get((cell["row"], cell["col"]))
            if rendered is None:
                continue
            right = rendered["bbox"]["x"] + rendered["bbox"]["w"]
            if right <= first_header_x + SCHEDULE_BOUNDARY_TOLERANCE:
                labels.append((right, cell["text"]))
        if not labels:
            continue
        labels.sort(key=lambda item: item[0])
        nearest_right = labels[-1][0]
        nearest = {text for right, text in labels if abs(right - nearest_right) <= 1e-6}
        if len(nearest) != 1:
            continue
        label = next(iter(nearest))

        header_order = {header["label"]: index for index, header in enumerate(headers)}
        evidence.sort(
            key=lambda value: (
                header_order[value["period"]],
                value["col"],
                value["bbox"]["x"],
            )
        )
        periods = list(dict.fromkeys(value["period"] for value in evidence))
        facts.append(
            {
                "row": row,
                "label": label,
                "periods": periods,
                "text": f"{label}: {_format_periods(periods)}",
                "evidence_cells": evidence,
            }
        )
    return facts


def build_table_visual_overlay(
    *,
    doc_id: str,
    blocks: Sequence[Mapping[str, Any]],
    layout_records: Sequence[Mapping[str, Any]],
    dump_pages: Mapping[str, Any],
    render_trees: Mapping[int, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Materialize ordered table context and direct background evidence.

    The function only enriches a table after the existing layout artifact
    proves the canonical block-to-render link. It never guesses a page, table,
    heading, fill color, or schedule period.
    """
    if not isinstance(doc_id, str) or _DOC_ID_PATTERN.fullmatch(doc_id) is None:
        raise ValueError("doc_id_invalid")
    if not isinstance(blocks, Sequence) or isinstance(blocks, (str, bytes)):
        raise ValueError("table_blocks_invalid")
    sections, flows, page_bboxes = _validated_flows(
        dump_pages=dump_pages, render_trees=render_trees
    )
    layouts = _layout_index(layout_records, doc_id=doc_id)
    table_blocks = [block for block in blocks if isinstance(block, Mapping) and block.get("block_type") == "table"]
    if any(not isinstance(block, Mapping) for block in blocks):
        raise ValueError("table_block_invalid")

    records: list[dict[str, Any]] = []
    seen_blocks: set[str] = set()
    for block in sorted(table_blocks, key=lambda value: str(value.get("block_id", ""))):
        block_id, structure_sha256, structure, key = _canonical_table(block, doc_id)
        if block_id in seen_blocks:
            raise ValueError("duplicate_table_block_id")
        seen_blocks.add(block_id)
        base: dict[str, Any] = {
            "schema_version": VISUAL_CONTEXT_SCHEMA_VERSION,
            "doc_id": doc_id,
            "block_id": block_id,
            "structure_sha256": structure_sha256,
            "status": "layout_missing",
            "page_start": None,
            "page_end": None,
            "coordinate_space": COORDINATE_SPACE,
            "render_key": _render_key(key),
            "page_contexts": [],
            "background_cells": [],
            "schedule_facts": [],
        }
        layout = layouts.get(block_id)
        if layout is None:
            records.append(base)
            continue
        if layout.get("structure_sha256") != structure_sha256:
            raise ValueError("table_layout_structure_hash_mismatch")
        if layout.get("status") != "verified_render":
            base["status"] = "layout_unresolved"
            records.append(base)
            continue
        page_start = _require_integer(
            layout.get("page_start"), "table_layout_page_start_invalid", minimum=1
        )
        page_end = _require_integer(
            layout.get("page_end"), "table_layout_page_end_invalid", minimum=1
        )
        if page_end < page_start:
            raise ValueError("table_layout_page_range_invalid")
        base["page_start"] = page_start
        base["page_end"] = page_end
        occurrences = _layout_occurrences(
            record=layout,
            key=key,
            structure=structure,
            flows=flows,
            sections=sections,
            page_bboxes=page_bboxes,
        )
        expected_count = len(layout.get("page_bboxes", []))
        if not occurrences or len(occurrences) != expected_count:
            base["status"] = "render_occurrence_unresolved"
            records.append(base)
            continue

        contexts: list[dict[str, Any]] = []
        backgrounds: list[dict[str, Any]] = []
        facts: list[dict[str, Any]] = []
        for page, event in occurrences:
            contexts.append(
                {
                    "page": page,
                    "sequence_in_page": event["sequence_in_page"],
                    "bbox": event["bbox"],
                    "preceding_text": event["preceding_text"],
                }
            )
            render_cells, page_backgrounds, ambiguous_rows = _render_cells(
                table=event["node"], page=page
            )
            backgrounds.extend(page_backgrounds)
            facts.extend(
                _schedule_facts(
                    page=page,
                    structure=structure,
                    render_cells=render_cells,
                    backgrounds=page_backgrounds,
                    ambiguous_rows=ambiguous_rows,
                    globally_ambiguous=bool(layout.get("wrapper_flattened")),
                )
            )
        base.update(
            {
                "status": "verified_render",
                "page_contexts": sorted(
                    contexts, key=lambda value: (value["page"], value["sequence_in_page"])
                ),
                "background_cells": sorted(
                    backgrounds,
                    key=lambda value: (value["page"], value["row"], value["col"]),
                ),
                "schedule_facts": sorted(
                    facts,
                    key=lambda value: (
                        value["evidence_cells"][0]["page"], value["row"], value["label"]
                    ),
                ),
            }
        )
        records.append(base)

    unknown_layouts = set(layouts) - seen_blocks
    if unknown_layouts:
        raise ValueError("table_layout_block_unknown")
    return records


def _deep_body_images(
    *,
    body: Mapping[str, Any],
    atomic_events: Sequence[Mapping[str, Any]],
) -> list[tuple[Mapping[str, Any], str, Mapping[str, Any] | None]]:
    atomic_images = {
        id(event["node"]): event for event in atomic_events if event["kind"] == "image"
    }
    atomic_tables = {
        id(event["node"]): event for event in atomic_events if event["kind"] == "table"
    }
    atomic_nodes = {id(event["node"]): event for event in atomic_events}
    images: list[tuple[Mapping[str, Any], str, Mapping[str, Any] | None]] = []
    seen: set[int] = set()
    visited = 0
    stack: list[
        tuple[
            Mapping[str, Any],
            int,
            Mapping[str, Any] | None,
            Mapping[str, Any] | None,
        ]
    ] = [
        (body, 0, None, None)
    ]
    while stack:
        node, depth, enclosing_table, enclosing_anchor = stack.pop()
        if depth > MAX_RENDER_DEPTH:
            raise ValueError("render_tree_depth_exceeded")
        identity = id(node)
        if identity in seen:
            raise ValueError("render_tree_cycle_or_alias")
        seen.add(identity)
        visited += 1
        if visited > MAX_RENDER_NODES:
            raise ValueError("render_tree_node_limit_exceeded")
        node_type = node.get("type")
        node_anchor = atomic_nodes.get(identity) or enclosing_anchor
        if node_type == "Table" and enclosing_table is None:
            enclosing_table = atomic_tables.get(identity)
        if node_type == "Image":
            anchor = atomic_images.get(identity) or enclosing_table or node_anchor
            kind = "table_nested" if enclosing_table is not None else "body"
            images.append((node, kind, anchor))
            continue
        for child in reversed(_children(node)):
            stack.append((child, depth + 1, enclosing_table, node_anchor))
    return images


def build_body_image_evidence(
    *,
    doc_id: str,
    dump_pages: Mapping[str, Any],
    render_trees: Mapping[int, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return render-only Body image occurrences for later bounded asset linking.

    Top-level tables remain atomic for reading order. Images inside their cells
    are nevertheless enumerated for global DocLang asset-count reconciliation;
    they inherit the table sequence/context and are explicitly marked nested.
    """
    if not isinstance(doc_id, str) or _DOC_ID_PATTERN.fullmatch(doc_id) is None:
        raise ValueError("doc_id_invalid")
    sections, flows, page_bboxes = _validated_flows(
        dump_pages=dump_pages, render_trees=render_trees
    )
    records: list[dict[str, Any]] = []
    for page_index in sorted(render_trees):
        page = render_trees[page_index]
        body, _page_bbox = _body(page, page_index)
        images = _deep_body_images(body=body, atomic_events=flows[page_index])
        for ordinal, (node, container_kind, anchor) in enumerate(images):
            raw_paragraph = node.get("pi")
            raw_control = node.get("ci")
            if raw_paragraph is None and raw_control is None:
                render_key = None
            elif raw_paragraph is None or raw_control is None:
                raise ValueError("render_tree_image_key_partial")
            else:
                paragraph = _require_integer(
                    raw_paragraph, "render_tree_image_paragraph_invalid"
                )
                control = _require_integer(
                    raw_control, "render_tree_image_control_invalid"
                )
                render_key = _render_key(
                    (sections[page_index], paragraph, control)
                )
            bbox = _normalize_bbox(node.get("bbox"), "render_tree_image_bbox_invalid")
            if not _bbox_contains(page_bboxes[page_index], bbox):
                # A RenderTree image may expose geometry that extends beyond
                # the page that contains the occurrence.  Keep the evidence
                # and its reading-order position, but discard the render key:
                # page containment is part of the exact asset-link contract,
                # so retaining the key here could enable a false ordinal link.
                render_key = None
            sequence = anchor["sequence_in_page"] if anchor is not None else ordinal
            preceding = anchor.get("preceding_text") if anchor is not None else None
            identity = {
                "doc_id": doc_id,
                "page": page_index + 1,
                "image_ordinal_in_page": ordinal,
                "sequence_in_page": sequence,
                "render_key": render_key,
                "bbox": bbox,
                "container_kind": container_kind,
            }
            records.append(
                {
                    "schema_version": VISUAL_CONTEXT_SCHEMA_VERSION,
                    "doc_id": doc_id,
                    "occurrence_id": f"occ_{sha256_text(canonical_json(identity))[:24]}",
                    "node_type": "image",
                    "status": "render_only_unlinked",
                    "page": page_index + 1,
                    "sequence_in_page": sequence,
                    "image_ordinal_in_page": ordinal,
                    "bbox": bbox,
                    "coordinate_space": COORDINATE_SPACE,
                    "render_key": render_key,
                    "preceding_text": preceding,
                    "container_kind": container_kind,
                    "extraction_method": EXTRACTION_METHOD,
                }
            )
    return records


def _ordered_link_key(
    *,
    page: int,
    sequence_in_page: int,
    bbox: Mapping[str, float],
    render_key: Mapping[str, int],
) -> tuple[int, int, str, int, int, int]:
    return (
        page,
        sequence_in_page,
        canonical_json(dict(bbox)),
        render_key["section"],
        render_key["paragraph"],
        render_key["control"],
    )


def _full_render_key(value: Any, error_code: str) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != {
        "section",
        "paragraph",
        "control",
    }:
        raise ValueError(error_code)
    return {
        "section": _require_integer(value.get("section"), error_code),
        "paragraph": _require_integer(value.get("paragraph"), error_code),
        "control": _require_integer(value.get("control"), error_code),
    }


def _validate_linked_schedule_facts(
    value: Any, *, page_start: int, page_end: int
) -> None:
    if not isinstance(value, list):
        raise ValueError("ordered_table_schedule_facts_invalid")
    for fact in value:
        if not isinstance(fact, Mapping):
            raise ValueError("ordered_table_schedule_fact_invalid")
        label = fact.get("label")
        row = fact.get("row")
        periods = fact.get("periods")
        text = fact.get("text")
        evidence = fact.get("evidence_cells")
        if (
            not isinstance(label, str)
            or not label
            or not _is_integer(row)
            or not isinstance(periods, list)
            or not periods
            or any(
                not isinstance(period, str) or _period_value(period) is None
                for period in periods
            )
            or len(set(periods)) != len(periods)
            or [int(_period_value(period)) for period in periods]
            != sorted(int(_period_value(period)) for period in periods)
            or text != f"{label}: {_format_periods(periods)}"
            or not isinstance(evidence, list)
            or not evidence
        ):
            raise ValueError("ordered_table_schedule_fact_invalid")
        evidence_periods: list[str] = []
        for cell in evidence:
            if not isinstance(cell, Mapping):
                raise ValueError("ordered_table_schedule_evidence_invalid")
            page = _require_integer(
                cell.get("page"),
                "ordered_table_schedule_evidence_invalid",
                minimum=1,
            )
            period = cell.get("period")
            if (
                page < page_start
                or page > page_end
                or not isinstance(period, str)
                or period not in periods
            ):
                raise ValueError("ordered_table_schedule_evidence_invalid")
            evidence_row = _require_integer(
                cell.get("row"), "ordered_table_schedule_evidence_invalid"
            )
            if evidence_row != row:
                raise ValueError("ordered_table_schedule_evidence_invalid")
            _require_integer(
                cell.get("col"), "ordered_table_schedule_evidence_invalid"
            )
            _normalize_bbox(
                cell.get("bbox"), "ordered_table_schedule_evidence_invalid"
            )
            evidence_periods.append(period)
        if list(dict.fromkeys(evidence_periods)) != periods:
            raise ValueError("ordered_table_schedule_periods_mismatch")


def _table_occurrence_links(
    records: Sequence[Mapping[str, Any]], *, doc_id: str
) -> dict[tuple[int, int, str, int, int, int], list[str]]:
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise ValueError("ordered_table_records_invalid")
    links: dict[tuple[int, int, str, int, int, int], list[str]] = {}
    seen_blocks: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("ordered_table_record_invalid")
        if record.get("doc_id") != doc_id:
            raise ValueError("ordered_table_doc_id_mismatch")
        if (
            record.get("schema_version") != VISUAL_CONTEXT_SCHEMA_VERSION
            or record.get("coordinate_space") != COORDINATE_SPACE
        ):
            raise ValueError("ordered_table_contract_invalid")
        block_id = record.get("block_id")
        if not isinstance(block_id, str) or _BLOCK_ID_PATTERN.fullmatch(block_id) is None:
            raise ValueError("ordered_table_block_id_invalid")
        if block_id in seen_blocks:
            raise ValueError("ordered_table_block_duplicate")
        seen_blocks.add(block_id)
        status = record.get("status")
        if status not in {
            "layout_missing",
            "layout_unresolved",
            "render_occurrence_unresolved",
            "verified_render",
        }:
            raise ValueError("ordered_table_status_invalid")
        if status != "verified_render":
            continue
        page_start = _require_integer(
            record.get("page_start"), "ordered_table_page_start_invalid", minimum=1
        )
        page_end = _require_integer(
            record.get("page_end"), "ordered_table_page_end_invalid", minimum=1
        )
        if page_end < page_start:
            raise ValueError("ordered_table_page_range_invalid")
        render_key = _full_render_key(
            record.get("render_key"), "ordered_table_render_key_invalid"
        )
        contexts = record.get("page_contexts")
        if not isinstance(contexts, list) or not contexts:
            raise ValueError("ordered_table_contexts_invalid")
        for context in contexts:
            if not isinstance(context, Mapping):
                raise ValueError("ordered_table_context_invalid")
            page = _require_integer(
                context.get("page"), "ordered_table_page_invalid", minimum=1
            )
            if page < page_start or page > page_end:
                raise ValueError("ordered_table_context_page_outside_range")
            sequence = _require_integer(
                context.get("sequence_in_page"),
                "ordered_table_sequence_invalid",
            )
            bbox = _normalize_bbox(
                context.get("bbox"), "ordered_table_bbox_invalid"
            )
            key = _ordered_link_key(
                page=page,
                sequence_in_page=sequence,
                bbox=bbox,
                render_key=render_key,
            )
            if key in links:
                raise ValueError("ordered_table_link_duplicate")
            links[key] = [block_id]
        context_pages = [
            _require_integer(
                context.get("page"), "ordered_table_page_invalid", minimum=1
            )
            for context in contexts
        ]
        if min(context_pages) != page_start or max(context_pages) != page_end:
            raise ValueError("ordered_table_context_range_mismatch")
        _validate_linked_schedule_facts(
            record.get("schedule_facts"),
            page_start=page_start,
            page_end=page_end,
        )
    return links


def _image_occurrence_links(
    records: Sequence[Mapping[str, Any]], *, doc_id: str
) -> dict[tuple[int, int, str, int, int, int], list[str]]:
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise ValueError("ordered_image_records_invalid")
    links: dict[tuple[int, int, str, int, int, int], list[str]] = {}
    seen_occurrence_ids: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("ordered_image_record_invalid")
        if record.get("doc_id") != doc_id:
            raise ValueError("ordered_image_doc_id_mismatch")
        status = record.get("status")
        if status not in {
            "verified_asset_render",
            "asset_only_unlinked",
            "unsupported_source_asset",
            "render_only_missing_asset",
        }:
            raise ValueError("ordered_image_status_invalid")
        occurrence_id = record.get("occurrence_id")
        if (
            not isinstance(occurrence_id, str)
            or _IMAGE_OCCURRENCE_ID_PATTERN.fullmatch(occurrence_id) is None
        ):
            raise ValueError("ordered_image_occurrence_id_invalid")
        if occurrence_id in seen_occurrence_ids:
            raise ValueError("ordered_image_occurrence_duplicate")
        seen_occurrence_ids.add(occurrence_id)
        if status != "verified_asset_render":
            continue
        container_kind = record.get("container_kind")
        if container_kind not in {"body", "table_nested"}:
            raise ValueError("ordered_image_contract_invalid")
        if container_kind != "body":
            continue
        if (
            record.get("schema_version") != VISUAL_CONTEXT_SCHEMA_VERSION
            or record.get("node_type") != "image"
            or record.get("coordinate_space") != COORDINATE_SPACE
            or record.get("link_method")
            != "doclang_picture_render_image_global_ordinal_exact_count"
        ):
            raise ValueError("ordered_image_contract_invalid")
        page_start = _require_integer(
            record.get("page_start"), "ordered_image_page_invalid", minimum=1
        )
        page_end = _require_integer(
            record.get("page_end"), "ordered_image_page_invalid", minimum=1
        )
        if page_start != page_end:
            raise ValueError("ordered_image_page_range_invalid")
        sequence = _require_integer(
            record.get("sequence_in_page"), "ordered_image_sequence_invalid"
        )
        bbox = _normalize_bbox(record.get("bbox"), "ordered_image_bbox_invalid")
        render_key = _full_render_key(
            record.get("render_key"), "ordered_image_render_key_invalid"
        )
        key = _ordered_link_key(
            page=page_start,
            sequence_in_page=sequence,
            bbox=bbox,
            render_key=render_key,
        )
        if key in links:
            raise ValueError("ordered_image_link_duplicate")
        links[key] = [occurrence_id]
    return links


def _ordered_occurrence_id(
    *,
    doc_id: str,
    page: int,
    sequence_in_page: int,
    node_type: str,
    bbox: Mapping[str, float],
    render_key: Mapping[str, int] | None,
) -> str:
    identity = {
        "doc_id": doc_id,
        "page": page,
        "sequence_in_page": sequence_in_page,
        "node_type": node_type,
        "bbox": dict(bbox),
        "render_key": dict(render_key) if render_key is not None else None,
    }
    return f"vocc_{sha256_text(canonical_json(identity))[:24]}"


def build_ordered_visual_occurrences(
    *,
    doc_id: str,
    dump_pages: Mapping[str, Any],
    render_trees: Mapping[int, Mapping[str, Any]],
    table_records: Sequence[Mapping[str, Any]],
    image_records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Build one deterministic top-level text/table/image reading-order stream.

    Tables remain atomic: their descendant TextLine nodes never become sibling
    occurrences. Canonical table and verified image identifiers are attached
    only after exact page, sequence, bbox, and render-key matches; ambiguous or
    stale candidates leave the render occurrence explicitly unlinked.
    """
    if not isinstance(doc_id, str) or _DOC_ID_PATTERN.fullmatch(doc_id) is None:
        raise ValueError("doc_id_invalid")
    sections, flows, page_bboxes = _validated_flows(
        dump_pages=dump_pages, render_trees=render_trees
    )
    table_links = _table_occurrence_links(table_records, doc_id=doc_id)
    image_links = _image_occurrence_links(image_records, doc_id=doc_id)
    occurrences: list[dict[str, Any]] = []

    for page_index in sorted(flows):
        section = sections[page_index]
        page = page_index + 1
        for event in flows[page_index]:
            node_type = event["kind"]
            node = event["node"]
            sequence = event["sequence_in_page"]
            bbox = event["bbox"]
            bbox_inside_page = _bbox_contains(page_bboxes[page_index], bbox)
            if node_type == "text":
                render_key: dict[str, int] = {
                    "section": section,
                    "paragraph": _require_integer(
                        node.get("pi"), "ordered_text_paragraph_invalid"
                    ),
                }
                status = "render_text"
                text = event["text"]
                linked_block_id = None
                linked_image_occurrence_id = None
                preceding_text = None
                link_method = "top_level_textline"
            else:
                raw_paragraph = node.get("pi")
                raw_control = node.get("ci")
                if node_type == "image" and raw_paragraph is None and raw_control is None:
                    render_key = None
                    link_key = None
                else:
                    render_key = _render_key(
                        (
                            section,
                            _require_integer(
                                raw_paragraph,
                                f"ordered_{node_type}_paragraph_invalid",
                            ),
                            _require_integer(
                                raw_control, f"ordered_{node_type}_control_invalid"
                            ),
                        )
                    )
                    link_key = _ordered_link_key(
                        page=page,
                        sequence_in_page=sequence,
                        bbox=bbox,
                        render_key=render_key,
                    )
                    if node_type == "image" and not bbox_inside_page:
                        # Mirror build_body_image_evidence: preserve the
                        # occurrence but make exact linking impossible when
                        # its geometry cannot be proven to belong to the page.
                        render_key = None
                        link_key = None
                text = None
                preceding_text = event["preceding_text"]
                if node_type == "table":
                    # Some multi-page RenderTree tables expose the whole-table
                    # bbox on one page, extending beyond that page.  Preserve
                    # the occurrence and its order, but never attach a
                    # canonical table ID when page containment is not proven.
                    candidates = (
                        table_links.get(link_key, [])
                        if bbox_inside_page and link_key is not None
                        else []
                    )
                    if len(candidates) == 1:
                        status = "verified_table_link"
                        linked_block_id = candidates[0]
                        link_method = (
                            "table_overlay_page_sequence_bbox_render_key_exact"
                        )
                    else:
                        status = "render_only_unlinked"
                        linked_block_id = None
                        link_method = "unlinked"
                    linked_image_occurrence_id = None
                else:
                    candidates = (
                        image_links.get(link_key, []) if link_key is not None else []
                    )
                    if len(candidates) == 1:
                        status = "verified_image_link"
                        linked_image_occurrence_id = candidates[0]
                        link_method = (
                            "image_evidence_page_sequence_bbox_render_key_exact"
                        )
                    else:
                        status = "render_only_unlinked"
                        linked_image_occurrence_id = None
                        link_method = "unlinked"
                    linked_block_id = None

            occurrences.append(
                {
                    "schema_version": VISUAL_CONTEXT_SCHEMA_VERSION,
                    "ordered_occurrence_id": _ordered_occurrence_id(
                        doc_id=doc_id,
                        page=page,
                        sequence_in_page=sequence,
                        node_type=node_type,
                        bbox=bbox,
                        render_key=render_key,
                    ),
                    "doc_id": doc_id,
                    "page": page,
                    "sequence_in_page": sequence,
                    "node_type": node_type,
                    "status": status,
                    "bbox": bbox,
                    "coordinate_space": COORDINATE_SPACE,
                    "render_key": render_key,
                    "text": text,
                    "linked_block_id": linked_block_id,
                    "linked_image_occurrence_id": linked_image_occurrence_id,
                    "preceding_text": preceding_text,
                    "link_method": link_method,
                }
            )
    return occurrences


__all__ = [
    "COORDINATE_SPACE",
    "EXTRACTION_METHOD",
    "VISUAL_CONTEXT_SCHEMA_VERSION",
    "build_body_image_evidence",
    "build_ordered_visual_occurrences",
    "build_table_visual_overlay",
]
