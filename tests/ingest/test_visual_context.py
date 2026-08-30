from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from midprojectrag.ingest.common import canonical_json, sha256_text
from midprojectrag.ingest.visual_context import (
    COORDINATE_SPACE,
    _format_periods,
    build_body_image_evidence,
    build_ordered_visual_occurrences,
    build_table_visual_overlay,
)


DOC_ID = "doc_0123456789abcdef01234567"
BLOCK_ID = "block_0123456789abcdef01234567"
ROOT = Path(__file__).resolve().parents[2]


def _bbox(x: float, y: float, w: float, h: float) -> dict[str, float]:
    return {"x": x, "y": y, "w": w, "h": h}


def _text_line(text: str, *, paragraph: int, y: float) -> dict[str, object]:
    return {
        "type": "TextLine",
        "pi": paragraph,
        "bbox": _bbox(0, y, 100, 10),
        "children": [{"type": "TextRun", "text": text}],
    }


def _image(*, paragraph: int, control: int, bbox=None) -> dict[str, object]:
    return {
        "type": "Image",
        "pi": paragraph,
        "ci": control,
        "bbox": bbox or _bbox(10, 80, 20, 10),
    }


def _cell(
    row: int,
    col: int,
    bbox: dict[str, float],
    *,
    background: bool = False,
    children=(),
) -> dict[str, object]:
    values = list(children)
    if background:
        values.insert(0, {"type": "Rect", "bbox": dict(bbox)})
    return {
        "type": "Cell",
        "row": row,
        "col": col,
        "bbox": bbox,
        "children": values,
    }


def _canonical_cell(
    row: int,
    col: int,
    text: str,
    *,
    row_span: int = 1,
    col_span: int = 1,
    nested=None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "row": row,
        "col": col,
        "row_span": row_span,
        "col_span": col_span,
        "is_header": row == 0,
        "text": text,
    }
    if nested is not None:
        value["nested"] = nested
    return value


def _structure(*, merged_schedule_cell: bool = False, nested: bool = False):
    cells = [
        _canonical_cell(0, 0, "Period"),
        _canonical_cell(0, 1, "M", col_span=2),
        _canonical_cell(0, 3, "M+1", col_span=2),
        _canonical_cell(1, 0, "Task A"),
        _canonical_cell(
            1,
            1,
            "",
            col_span=2 if merged_schedule_cell else 1,
            nested=[{"rows": 1, "cols": 1}] if nested else None,
        ),
        _canonical_cell(1, 2, ""),
        _canonical_cell(1, 3, ""),
        _canonical_cell(1, 4, ""),
        _canonical_cell(2, 0, "Group", col_span=5),
    ]
    return {
        "index": 0,
        "section": 0,
        "paragraph": 7,
        "control": 0,
        "rows": 3,
        "cols": 5,
        "cell_count": len(cells),
        "cells": cells,
    }


def _block(structure) -> dict[str, object]:
    return {
        "block_type": "table",
        "doc_id": DOC_ID,
        "block_id": BLOCK_ID,
        "structure_sha256": sha256_text(canonical_json(structure)),
        "table_structure": structure,
    }


def _table(*, nested_image=None, group_background: bool = True):
    table_bbox = _bbox(0, 20, 100, 60)
    children = [
        _cell(0, 0, _bbox(0, 20, 20, 20)),
        _cell(0, 1, _bbox(20, 20, 40, 20)),
        _cell(0, 3, _bbox(60, 20, 40, 20)),
        _cell(1, 0, _bbox(0, 40, 20, 20)),
        _cell(
            1,
            1,
            _bbox(20, 40, 20, 20),
            background=True,
            children=(nested_image,) if nested_image is not None else (),
        ),
        _cell(1, 2, _bbox(40, 40, 20, 20), background=True),
        _cell(1, 3, _bbox(60, 40, 20, 20)),
        _cell(1, 4, _bbox(80, 40, 20, 20)),
        _cell(
            2,
            0,
            _bbox(0, 60, 100, 20),
            background=group_background,
            children=(_text_line("cell text must stay opaque", paragraph=7, y=62),),
        ),
    ]
    return {
        "type": "Table",
        "pi": 7,
        "ci": 0,
        "rows": 3,
        "cols": 5,
        "bbox": table_bbox,
        "children": children,
    }


def _page(*body_nodes, page_index: int | None = None):
    value = {
        "type": "Page",
        "bbox": _bbox(0, 0, 100, 100),
        "children": [
            {"type": "Header", "bbox": _bbox(0, 0, 100, 0)},
            {
                "type": "Body",
                "bbox": _bbox(0, 0, 100, 100),
                "children": [
                    {
                        "type": "Column",
                        "col": 0,
                        "bbox": _bbox(0, 0, 100, 100),
                        "children": list(body_nodes),
                    }
                ],
            },
            {"type": "Footer", "bbox": _bbox(0, 100, 100, 0)},
        ],
    }
    if page_index is not None:
        value["pageIndex"] = page_index
    return value


def _dump(page_count: int = 1):
    return {
        "schemaVersion": "1.0",
        "pageCount": page_count,
        "pages": [
            {
                "pageIndex": index,
                "pageNumber": index + 1,
                "section": 0,
                "columns": [],
                "extras": [],
            }
            for index in range(page_count)
        ],
    }


def _layout(block, *, bbox=None, status: str = "verified_render"):
    table_bbox = bbox or _bbox(0, 20, 100, 60)
    return {
        "schema_version": "1.0",
        "doc_id": DOC_ID,
        "block_id": BLOCK_ID,
        "structure_sha256": block["structure_sha256"],
        "page_start": 1 if status == "verified_render" else None,
        "page_end": 1 if status == "verified_render" else None,
        "page_bboxes": (
            [
                {
                    "page": 1,
                    "bbox": table_bbox,
                    "page_bbox": _bbox(0, 0, 100, 100),
                    "bbox_valid": True,
                }
            ]
            if status == "verified_render"
            else []
        ),
        "coordinate_space": COORDINATE_SPACE,
        "render_key": {"section": 0, "paragraph": 7, "control": 0},
        "wrapper_flattened": False,
        "anchor_present": True,
        "status": status,
    }


class TableVisualOverlayTests(unittest.TestCase):
    def test_period_formatter_collapses_target_style_range_only(self) -> None:
        self.assertEqual(_format_periods(["M+2", "M+3", "M+4"]), "M+2~M+4")
        self.assertEqual(_format_periods(["M", "M+2", "M+3"]), "M, M+2~M+3")

    def test_atomic_order_context_direct_background_and_strict_schedule(self) -> None:
        structure = _structure()
        block = _block(structure)
        page = _page(
            _text_line("6. Schedule", paragraph=6, y=5),
            _table(),
            _text_line("Following section", paragraph=8, y=85),
            page_index=0,
        )

        result = build_table_visual_overlay(
            doc_id=DOC_ID,
            blocks=[block],
            layout_records=[_layout(block)],
            dump_pages=_dump(),
            render_trees={0: page},
        )

        self.assertEqual(len(result), 1)
        record = result[0]
        self.assertEqual(record["status"], "verified_render")
        self.assertEqual(record["page_contexts"][0]["sequence_in_page"], 1)
        self.assertEqual(
            record["page_contexts"][0]["preceding_text"],
            {
                "text": "6. Schedule",
                "bbox": _bbox(0, 5, 100, 10),
                "render_key": {"section": 0, "paragraph": 6},
                "method": "nearest_prior_top_level_textline",
            },
        )
        self.assertEqual(
            [(cell["row"], cell["col"]) for cell in record["background_cells"]],
            [(1, 1), (1, 2), (2, 0)],
        )
        self.assertEqual(len(record["schedule_facts"]), 1)
        fact = record["schedule_facts"][0]
        self.assertEqual(fact["label"], "Task A")
        self.assertEqual(fact["periods"], ["M"])
        self.assertEqual(fact["text"], "Task A: M")
        self.assertEqual(len(fact["evidence_cells"]), 2)

    def test_merged_empty_fill_anchors_form_verified_target_style_range(self) -> None:
        cells = [_canonical_cell(0, 0, "Period")]
        for index, label in enumerate(("M", "M+1", "M+2", "M+3", "M+4")):
            cells.append(_canonical_cell(0, 1 + index * 2, label, col_span=2))
        cells.extend(
            [
                _canonical_cell(1, 0, "Task B"),
                _canonical_cell(1, 1, "", col_span=2),
                _canonical_cell(1, 3, "", col_span=2),
                _canonical_cell(1, 5, "", col_span=2),
                _canonical_cell(1, 7, ""),
                _canonical_cell(1, 8, ""),
                _canonical_cell(1, 9, "", col_span=2),
            ]
        )
        structure = {
            "index": 0,
            "section": 0,
            "paragraph": 7,
            "control": 0,
            "rows": 2,
            "cols": 11,
            "cell_count": len(cells),
            "cells": cells,
        }
        block = _block(structure)
        render_cells = [_cell(0, 0, _bbox(0, 20, 20, 20))]
        for index in range(5):
            render_cells.append(
                _cell(0, 1 + index * 2, _bbox(20 + index * 16, 20, 16, 20))
            )
        render_cells.extend(
            [
                _cell(1, 0, _bbox(0, 40, 20, 20)),
                _cell(1, 1, _bbox(20, 40, 16, 20)),
                _cell(1, 3, _bbox(36, 40, 16, 20)),
                _cell(1, 5, _bbox(52, 40, 16, 20), background=True),
                _cell(1, 7, _bbox(68, 40, 8, 20), background=True),
                _cell(1, 8, _bbox(76, 40, 8, 20)),
                _cell(1, 9, _bbox(84, 40, 16, 20), background=True),
            ]
        )
        table = {
            "type": "Table",
            "pi": 7,
            "ci": 0,
            "rows": 2,
            "cols": 11,
            "bbox": _bbox(0, 20, 100, 40),
            "children": render_cells,
        }
        layout = _layout(block, bbox=_bbox(0, 20, 100, 40))

        fact = build_table_visual_overlay(
            doc_id=DOC_ID,
            blocks=[block],
            layout_records=[layout],
            dump_pages=_dump(),
            render_trees={
                0: _page(
                    _text_line("Schedule", paragraph=6, y=5), table, page_index=0
                )
            },
        )[0]["schedule_facts"][0]

        self.assertEqual(fact["periods"], ["M+2", "M+3", "M+4"])
        self.assertEqual(fact["text"], "Task B: M+2~M+4")

    def test_nested_schedule_cells_leave_raw_evidence_only(self) -> None:
        structure = _structure(nested=True)
        block = _block(structure)
        record = build_table_visual_overlay(
            doc_id=DOC_ID,
            blocks=[block],
            layout_records=[_layout(block)],
            dump_pages=_dump(),
            render_trees={
                0: _page(
                    _text_line("Heading", paragraph=6, y=5),
                    _table(),
                    page_index=0,
                )
            },
        )[0]
        self.assertTrue(record["background_cells"])
        self.assertEqual(record["schedule_facts"], [])

    def test_unrelated_invalid_last_row_does_not_suppress_valid_schedule_row(self) -> None:
        structure = _structure()
        block = _block(structure)
        table = _table()
        final_cell = next(
            child
            for child in table["children"]
            if child.get("type") == "Cell" and child.get("row") == 2
        )
        final_cell["bbox"] = _bbox(0, 75, 100, 20)
        final_cell["children"][0]["bbox"] = _bbox(0, 75, 100, 20)

        record = build_table_visual_overlay(
            doc_id=DOC_ID,
            blocks=[block],
            layout_records=[_layout(block)],
            dump_pages=_dump(),
            render_trees={
                0: _page(
                    _text_line("Heading", paragraph=6, y=5),
                    table,
                    page_index=0,
                )
            },
        )[0]

        self.assertEqual(record["schedule_facts"][0]["text"], "Task A: M")

    def test_subpixel_shared_border_rounding_keeps_label_and_headers_joined(self) -> None:
        structure = _structure()
        block = _block(structure)
        table = _table()
        label = next(
            child
            for child in table["children"]
            if child.get("type") == "Cell"
            and child.get("row") == 1
            and child.get("col") == 0
        )
        first_header = next(
            child
            for child in table["children"]
            if child.get("type") == "Cell"
            and child.get("row") == 0
            and child.get("col") == 1
        )
        label["bbox"] = _bbox(0, 40, 20.1, 20)
        first_header["bbox"] = _bbox(20, 20, 40.1, 20)

        record = build_table_visual_overlay(
            doc_id=DOC_ID,
            blocks=[block],
            layout_records=[_layout(block)],
            dump_pages=_dump(),
            render_trees={
                0: _page(
                    _text_line("Heading", paragraph=6, y=5),
                    table,
                    page_index=0,
                )
            },
        )[0]

        self.assertEqual(record["schedule_facts"][0]["text"], "Task A: M")

    def test_layout_bbox_mismatch_fails_closed_without_guessing_context(self) -> None:
        structure = _structure()
        block = _block(structure)
        layouts = []
        bbox_mismatch = _layout(block, bbox=_bbox(1, 20, 99, 60))
        layouts.append(("bbox", bbox_mismatch, _dump()))
        invalid_flag = _layout(block)
        invalid_flag["page_bboxes"][0]["bbox_valid"] = False
        layouts.append(("bbox_valid", invalid_flag, _dump()))
        page_bbox_mismatch = _layout(block)
        page_bbox_mismatch["page_bboxes"][0]["page_bbox"] = _bbox(1, 0, 99, 100)
        layouts.append(("page_bbox", page_bbox_mismatch, _dump()))
        wrong_section_dump = _dump()
        wrong_section_dump["pages"][0]["section"] = 1
        layouts.append(("section", _layout(block), wrong_section_dump))

        for label, layout, dump_pages in layouts:
            with self.subTest(label=label):
                record = build_table_visual_overlay(
                    doc_id=DOC_ID,
                    blocks=[block],
                    layout_records=[layout],
                    dump_pages=dump_pages,
                    render_trees={0: _page(_table(), page_index=0)},
                )[0]
                self.assertEqual(record["status"], "render_occurrence_unresolved")
                self.assertEqual(record["page_contexts"], [])
                self.assertEqual(record["background_cells"], [])
                self.assertEqual(record["schedule_facts"], [])

    def test_result_is_deterministic_and_rejects_page_set_mismatch(self) -> None:
        structure = _structure()
        block = _block(structure)
        kwargs = {
            "doc_id": DOC_ID,
            "blocks": [block],
            "layout_records": [_layout(block)],
            "dump_pages": _dump(),
            "render_trees": {0: _page(_table(), page_index=0)},
        }
        first = build_table_visual_overlay(**copy.deepcopy(kwargs))
        second = build_table_visual_overlay(**copy.deepcopy(kwargs))
        self.assertEqual(canonical_json(first), canonical_json(second))
        with self.assertRaisesRegex(ValueError, "render_tree_page_set_mismatch"):
            build_table_visual_overlay(
                doc_id=DOC_ID,
                blocks=[block],
                layout_records=[_layout(block)],
                dump_pages=_dump(page_count=2),
                render_trees={0: _page(_table(), page_index=0)},
            )

    def test_zero_area_page_text_table_image_and_rect_geometry_is_rejected(self) -> None:
        page = _page(page_index=0)
        page["bbox"]["w"] = 0
        with self.assertRaisesRegex(ValueError, "render_tree_page_bbox_invalid"):
            build_body_image_evidence(
                doc_id=DOC_ID, dump_pages=_dump(), render_trees={0: page}
            )

        text = _text_line("text", paragraph=1, y=5)
        text["bbox"]["h"] = 0
        with self.assertRaisesRegex(ValueError, "render_tree_text_bbox_invalid"):
            build_ordered_visual_occurrences(
                doc_id=DOC_ID,
                dump_pages=_dump(),
                render_trees={0: _page(text, page_index=0)},
                table_records=[],
                image_records=[],
            )

        table = _table()
        table["bbox"]["w"] = 0
        with self.assertRaisesRegex(ValueError, "render_tree_table_bbox_invalid"):
            build_ordered_visual_occurrences(
                doc_id=DOC_ID,
                dump_pages=_dump(),
                render_trees={0: _page(table, page_index=0)},
                table_records=[],
                image_records=[],
            )

        image = _image(paragraph=1, control=0)
        image["bbox"]["h"] = 0
        with self.assertRaisesRegex(ValueError, "render_tree_image_bbox_invalid"):
            build_body_image_evidence(
                doc_id=DOC_ID,
                dump_pages=_dump(),
                render_trees={0: _page(image, page_index=0)},
            )

        structure = _structure()
        block = _block(structure)
        table = _table()
        rect = next(
            grandchild
            for cell in table["children"]
            if cell.get("type") == "Cell"
            for grandchild in cell.get("children", [])
            if grandchild.get("type") == "Rect"
        )
        rect["bbox"]["w"] = 0
        with self.assertRaisesRegex(ValueError, "render_tree_rect_bbox_invalid"):
            build_table_visual_overlay(
                doc_id=DOC_ID,
                blocks=[block],
                layout_records=[_layout(block)],
                dump_pages=_dump(),
                render_trees={0: _page(table, page_index=0)},
            )


class BodyImageEvidenceTests(unittest.TestCase):
    def test_top_level_and_table_nested_images_preserve_atomic_context(self) -> None:
        nested = _image(paragraph=7, control=2, bbox=_bbox(22, 42, 5, 5))
        after_table = _image(paragraph=8, control=0, bbox=_bbox(10, 81, 20, 5))
        after_table_line = {
            "type": "TextLine",
            "pi": 8,
            "bbox": _bbox(0, 81, 100, 5),
            "children": [{"type": "TextRun", "text": ""}, after_table],
        }
        top_level = _image(paragraph=9, control=0, bbox=_bbox(10, 88, 20, 10))
        image_line = {
            "type": "TextLine",
            "pi": 9,
            "bbox": _bbox(0, 88, 100, 10),
            "children": [
                {"type": "TextRun", "text": ""},
                top_level,
            ],
        }
        page = _page(
            _text_line("Nearest heading", paragraph=6, y=5),
            _table(nested_image=nested),
            after_table_line,
            _text_line("Image heading", paragraph=8, y=82),
            image_line,
            page_index=0,
        )

        records = build_body_image_evidence(
            doc_id=DOC_ID,
            dump_pages=_dump(),
            render_trees={0: page},
        )

        self.assertEqual(len(records), 3)
        nested_record, after_table_record, top_record = records
        self.assertEqual(nested_record["container_kind"], "table_nested")
        self.assertEqual(nested_record["sequence_in_page"], 1)
        self.assertEqual(
            nested_record["preceding_text"]["text"], "Nearest heading"
        )
        self.assertEqual(after_table_record["container_kind"], "body")
        self.assertEqual(after_table_record["sequence_in_page"], 2)
        self.assertEqual(
            after_table_record["preceding_text"]["text"], "Nearest heading"
        )
        self.assertEqual(top_record["container_kind"], "body")
        self.assertEqual(top_record["sequence_in_page"], 4)
        self.assertEqual(top_record["preceding_text"]["text"], "Image heading")
        self.assertNotEqual(nested_record["occurrence_id"], top_record["occurrence_id"])
        self.assertTrue(all(row["status"] == "render_only_unlinked" for row in records))
        self.assertTrue(all(row["occurrence_id"].startswith("occ_") for row in records))

    def test_nonempty_mixed_textline_emits_image_after_its_text(self) -> None:
        mixed_image = _image(paragraph=2, control=1)
        mixed_line = {
            "type": "TextLine",
            "pi": 2,
            "bbox": _bbox(0, 10, 100, 10),
            "children": [
                {"type": "TextRun", "text": "Visible text"},
                mixed_image,
            ],
        }
        record = build_body_image_evidence(
            doc_id=DOC_ID,
            dump_pages=_dump(),
            render_trees={0: _page(mixed_line, page_index=0)},
        )[0]

        self.assertEqual(record["container_kind"], "body")
        self.assertEqual(record["preceding_text"]["text"], "Visible text")
        self.assertEqual(record["sequence_in_page"], 1)
        self.assertEqual(record["image_ordinal_in_page"], 0)

    def test_image_bbox_outside_render_page_is_preserved_without_link_key(self) -> None:
        image = _image(paragraph=2, control=1, bbox=_bbox(95, 10, 10, 10))
        image_line = {
            "type": "TextLine",
            "pi": 2,
            "bbox": _bbox(0, 10, 100, 10),
            "children": [{"type": "TextRun", "text": ""}, image],
        }
        result = build_body_image_evidence(
            doc_id=DOC_ID,
            dump_pages=_dump(),
            render_trees={0: _page(image_line, page_index=0)},
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], "render_only_unlinked")
        self.assertIsNone(result[0]["render_key"])
        self.assertEqual(result[0]["bbox"], _bbox(95.0, 10.0, 10.0, 10.0))

    def test_unkeyed_top_level_image_is_preserved_as_render_only(self) -> None:
        image = {"type": "Image", "bbox": _bbox(10, 10, 30, 40)}
        result = build_body_image_evidence(
            doc_id=DOC_ID,
            dump_pages=_dump(),
            render_trees={0: _page(image, page_index=0)},
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], "render_only_unlinked")
        self.assertIsNone(result[0]["render_key"])


class OrderedVisualOccurrenceTests(unittest.TestCase):
    def _inputs(self):
        structure = _structure()
        block = _block(structure)
        table = _table()
        image = _image(paragraph=9, control=0, bbox=_bbox(10, 88, 20, 10))
        image_line = {
            "type": "TextLine",
            "pi": 9,
            "bbox": _bbox(0, 88, 100, 10),
            "children": [{"type": "TextRun", "text": ""}, image],
        }
        page = _page(
            _text_line("6. Schedule", paragraph=6, y=5),
            table,
            _text_line("7. Diagram", paragraph=8, y=82),
            image_line,
            page_index=0,
        )
        table_records = build_table_visual_overlay(
            doc_id=DOC_ID,
            blocks=[block],
            layout_records=[_layout(block)],
            dump_pages=_dump(),
            render_trees={0: page},
        )
        image_records = [
            {
                "schema_version": "1.0",
                "doc_id": DOC_ID,
                "occurrence_id": "occ_aaaaaaaaaaaaaaaaaaaaaaaa",
                "node_type": "image",
                "status": "verified_asset_render",
                "container_kind": "body",
                "page_start": 1,
                "page_end": 1,
                "sequence_in_page": 3,
                "bbox": _bbox(10, 88, 20, 10),
                "coordinate_space": COORDINATE_SPACE,
                "render_key": {"section": 0, "paragraph": 9, "control": 0},
                "link_method": "doclang_picture_render_image_global_ordinal_exact_count",
            }
        ]
        return block, page, table_records, image_records

    def test_builds_one_atomic_page_order_with_exact_table_and_image_links(self) -> None:
        block, page, table_records, image_records = self._inputs()
        result = build_ordered_visual_occurrences(
            doc_id=DOC_ID,
            dump_pages=_dump(),
            render_trees={0: page},
            table_records=table_records,
            image_records=image_records,
        )

        self.assertEqual(
            [record["node_type"] for record in result],
            ["text", "table", "text", "image"],
        )
        self.assertEqual(
            [record["sequence_in_page"] for record in result], [0, 1, 2, 3]
        )
        self.assertEqual(result[1]["status"], "verified_table_link")
        self.assertEqual(result[1]["linked_block_id"], block["block_id"])
        self.assertEqual(result[3]["status"], "verified_image_link")
        self.assertEqual(
            result[3]["linked_image_occurrence_id"],
            "occ_aaaaaaaaaaaaaaaaaaaaaaaa",
        )
        self.assertNotIn(
            "cell text must stay opaque",
            [record["text"] for record in result if record["text"]],
        )
        schema = json.loads(
            (ROOT / "contracts" / "ordered-visual-occurrence.schema.json").read_text(
                encoding="utf-8"
            )
        )
        validator = Draft202012Validator(schema)
        for record in result:
            validator.validate(record)
        repeated = build_ordered_visual_occurrences(
            doc_id=DOC_ID,
            dump_pages=_dump(),
            render_trees={0: copy.deepcopy(page)},
            table_records=copy.deepcopy(table_records),
            image_records=copy.deepcopy(image_records),
        )
        self.assertEqual(canonical_json(result), canonical_json(repeated))

    def test_unsupported_source_asset_never_links_ordered_image(self) -> None:
        _block_value, page, table_records, _image_records = self._inputs()
        unsupported = {
            "doc_id": DOC_ID,
            "occurrence_id": "occ_cccccccccccccccccccccccc",
            "status": "unsupported_source_asset",
        }
        result = build_ordered_visual_occurrences(
            doc_id=DOC_ID,
            dump_pages=_dump(),
            render_trees={0: page},
            table_records=table_records,
            image_records=[unsupported],
        )

        image_record = next(
            record for record in result if record["node_type"] == "image"
        )
        self.assertEqual(image_record["status"], "render_only_unlinked")
        self.assertIsNone(image_record["linked_image_occurrence_id"])

    def test_bbox_mismatch_never_guesses_a_link_and_duplicates_are_rejected(self) -> None:
        _block_value, page, table_records, image_records = self._inputs()
        mismatched = copy.deepcopy(table_records)
        mismatched[0]["page_contexts"][0]["bbox"]["x"] += 1
        result = build_ordered_visual_occurrences(
            doc_id=DOC_ID,
            dump_pages=_dump(),
            render_trees={0: page},
            table_records=mismatched,
            image_records=image_records,
        )

        table = next(record for record in result if record["node_type"] == "table")
        image = next(record for record in result if record["node_type"] == "image")
        self.assertEqual(table["status"], "render_only_unlinked")
        self.assertIsNone(table["linked_block_id"])
        self.assertEqual(image["status"], "verified_image_link")

        duplicate_images = image_records + [
            {**image_records[0], "occurrence_id": "occ_bbbbbbbbbbbbbbbbbbbbbbbb"}
        ]
        with self.assertRaisesRegex(ValueError, "ordered_image_link_duplicate"):
            build_ordered_visual_occurrences(
                doc_id=DOC_ID,
                dump_pages=_dump(),
                render_trees={0: page},
                table_records=table_records,
                image_records=duplicate_images,
            )

        with self.assertRaisesRegex(
            ValueError, "ordered_image_occurrence_duplicate"
        ):
            build_ordered_visual_occurrences(
                doc_id=DOC_ID,
                dump_pages=_dump(),
                render_trees={0: page},
                table_records=table_records,
                image_records=image_records + [copy.deepcopy(image_records[0])],
            )

        duplicate_tables = table_records + [
            {**table_records[0], "block_id": "block_bbbbbbbbbbbbbbbbbbbbbbbb"}
        ]
        with self.assertRaisesRegex(ValueError, "ordered_table_link_duplicate"):
            build_ordered_visual_occurrences(
                doc_id=DOC_ID,
                dump_pages=_dump(),
                render_trees={0: page},
                table_records=duplicate_tables,
                image_records=image_records,
            )

        with self.assertRaisesRegex(ValueError, "ordered_table_block_duplicate"):
            build_ordered_visual_occurrences(
                doc_id=DOC_ID,
                dump_pages=_dump(),
                render_trees={0: page},
                table_records=table_records + [copy.deepcopy(table_records[0])],
                image_records=image_records,
            )

    def test_mixed_textline_preserves_text_then_verified_image_occurrence(self) -> None:
        image = _image(paragraph=2, control=1, bbox=_bbox(10, 10, 20, 10))
        mixed_line = {
            "type": "TextLine",
            "pi": 2,
            "bbox": _bbox(0, 10, 100, 10),
            "children": [
                {"type": "TextRun", "text": "Visible text"},
                image,
            ],
        }
        image_records = [
            {
                "schema_version": "1.0",
                "doc_id": DOC_ID,
                "occurrence_id": "occ_cccccccccccccccccccccccc",
                "node_type": "image",
                "status": "verified_asset_render",
                "container_kind": "body",
                "page_start": 1,
                "page_end": 1,
                "sequence_in_page": 1,
                "bbox": _bbox(10, 10, 20, 10),
                "coordinate_space": COORDINATE_SPACE,
                "render_key": {"section": 0, "paragraph": 2, "control": 1},
                "link_method": "doclang_picture_render_image_global_ordinal_exact_count",
            }
        ]

        result = build_ordered_visual_occurrences(
            doc_id=DOC_ID,
            dump_pages=_dump(),
            render_trees={0: _page(mixed_line, page_index=0)},
            table_records=[],
            image_records=image_records,
        )

        self.assertEqual(
            [(record["node_type"], record["sequence_in_page"]) for record in result],
            [("text", 0), ("image", 1)],
        )
        self.assertEqual(result[1]["status"], "verified_image_link")
        self.assertEqual(result[1]["preceding_text"]["text"], "Visible text")

    def test_rejects_inconsistent_schedule_and_context_page_range(self) -> None:
        _block_value, page, table_records, image_records = self._inputs()
        inconsistent = copy.deepcopy(table_records)
        inconsistent[0]["schedule_facts"][0]["text"] = "wrong"
        with self.assertRaisesRegex(
            ValueError, "ordered_table_schedule_fact_invalid"
        ):
            build_ordered_visual_occurrences(
                doc_id=DOC_ID,
                dump_pages=_dump(),
                render_trees={0: page},
                table_records=inconsistent,
                image_records=image_records,
            )

        outside = copy.deepcopy(table_records)
        outside[0]["page_start"] = 2
        outside[0]["page_end"] = 2
        with self.assertRaisesRegex(
            ValueError, "ordered_table_context_page_outside_range"
        ):
            build_ordered_visual_occurrences(
                doc_id=DOC_ID,
                dump_pages=_dump(),
                render_trees={0: page},
                table_records=outside,
                image_records=image_records,
            )

        reversed_range = copy.deepcopy(table_records)
        reversed_range[0]["page_start"] = 2
        reversed_range[0]["page_end"] = 1
        with self.assertRaisesRegex(ValueError, "ordered_table_page_range_invalid"):
            build_ordered_visual_occurrences(
                doc_id=DOC_ID,
                dump_pages=_dump(),
                render_trees={0: page},
                table_records=reversed_range,
                image_records=image_records,
            )

    def test_ordered_stream_keeps_outside_page_table_explicitly_unlinked(self) -> None:
        structure = _structure()
        block = _block(structure)
        table = _table()
        table["bbox"] = _bbox(0, 50, 100, 60)
        result = build_ordered_visual_occurrences(
            doc_id=DOC_ID,
            dump_pages=_dump(),
            render_trees={0: _page(table, page_index=0)},
            table_records=[],
            image_records=[],
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["node_type"], "table")
        self.assertEqual(result[0]["status"], "render_only_unlinked")
        self.assertIsNone(result[0]["linked_block_id"])
        self.assertEqual(result[0]["link_method"], "unlinked")

    def test_ordered_stream_keeps_unkeyed_image_explicitly_unlinked(self) -> None:
        image = {"type": "Image", "bbox": _bbox(10, 10, 30, 40)}
        result = build_ordered_visual_occurrences(
            doc_id=DOC_ID,
            dump_pages=_dump(),
            render_trees={0: _page(image, page_index=0)},
            table_records=[],
            image_records=[],
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["node_type"], "image")
        self.assertEqual(result[0]["status"], "render_only_unlinked")
        self.assertIsNone(result[0]["render_key"])
        self.assertEqual(result[0]["link_method"], "unlinked")

    def test_ordered_stream_keeps_outside_page_image_explicitly_unlinked(self) -> None:
        bbox = _bbox(95, 10, 10, 10)
        image = _image(paragraph=2, control=1, bbox=bbox)
        stale_exact_candidate = {
            "schema_version": "1.0",
            "doc_id": DOC_ID,
            "occurrence_id": "occ_dddddddddddddddddddddddd",
            "node_type": "image",
            "status": "verified_asset_render",
            "container_kind": "body",
            "page_start": 1,
            "page_end": 1,
            "sequence_in_page": 0,
            "bbox": bbox,
            "coordinate_space": COORDINATE_SPACE,
            "render_key": {"section": 0, "paragraph": 2, "control": 1},
            "link_method": "doclang_picture_render_image_global_ordinal_exact_count",
        }

        result = build_ordered_visual_occurrences(
            doc_id=DOC_ID,
            dump_pages=_dump(),
            render_trees={0: _page(image, page_index=0)},
            table_records=[],
            image_records=[stale_exact_candidate],
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["node_type"], "image")
        self.assertEqual(result[0]["status"], "render_only_unlinked")
        self.assertIsNone(result[0]["render_key"])
        self.assertIsNone(result[0]["linked_image_occurrence_id"])
        self.assertEqual(result[0]["link_method"], "unlinked")
        schema = json.loads(
            (ROOT / "contracts" / "ordered-visual-occurrence.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator(schema).validate(result[0])


if __name__ == "__main__":
    unittest.main()
