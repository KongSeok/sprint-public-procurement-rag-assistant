from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from midprojectrag.ingest.common import canonical_json, sha256_text
from midprojectrag.ingest.table_layout import (
    COORDINATE_SPACE,
    build_table_layout_overlay,
    load_rhwp_layout_inputs,
    load_render_tree_directory,
)


DOC_ID = "doc_0123456789abcdef01234567"


def _structure(
    *,
    section: int = 0,
    paragraph: int = 7,
    control: int = 0,
    rows: int = 2,
    cols: int = 2,
    container_path=None,
    cells=None,
):
    if cells is None:
        cells = [
            {
                "row": 0,
                "col": 0,
                "row_span": rows,
                "col_span": cols,
                "is_header": False,
                "text": "value",
            }
        ]
    value = {
        "index": 0,
        "section": section,
        "paragraph": paragraph,
        "control": control,
        "rows": rows,
        "cols": cols,
        "cell_count": len(cells),
        "cells": cells,
    }
    if container_path is not None:
        value["container_path"] = container_path
    return value


def _block(number: int, structure) -> dict[str, object]:
    return {
        "block_type": "table",
        "doc_id": DOC_ID,
        "block_id": f"block_{number:024x}",
        "structure_sha256": sha256_text(canonical_json(structure)),
        "table_structure": structure,
    }


def _dump_page(
    page_index: int,
    *,
    section: int = 0,
    page_number: int | None = None,
    anchors=(),
):
    items = [
        {
            "kind": "table",
            "paraIndex": paragraph,
            "controlIndex": control,
        }
        for paragraph, control in anchors
    ]
    return {
        "pageIndex": page_index,
        "pageNumber": page_number if page_number is not None else page_index + 1,
        "section": section,
        "columns": [{"items": items}],
        "extras": [],
    }


def _dump(*pages):
    return {
        "schemaVersion": "1.0",
        "pageCount": len(pages),
        "pages": list(pages),
    }


def _table_node(
    *,
    paragraph: int = 7,
    control: int = 0,
    rows: int = 2,
    cols: int = 2,
    bbox=None,
    children=None,
):
    return {
        "type": "Table",
        "pi": paragraph,
        "ci": control,
        "rows": rows,
        "cols": cols,
        "bbox": bbox or {"x": 10, "y": 20, "w": 30, "h": 40},
        "children": children or [],
    }


def _page(*body_nodes, header_nodes=(), footer_nodes=(), bbox=None, page_index=None):
    value = {
        "type": "Page",
        "bbox": bbox or {"x": 0, "y": 0, "w": 100, "h": 100},
        "children": [
            {"type": "Header", "bbox": {}, "children": list(header_nodes)},
            {"type": "Body", "bbox": {}, "children": list(body_nodes)},
            {"type": "Footer", "bbox": {}, "children": list(footer_nodes)},
        ],
    }
    if page_index is not None:
        value["pageIndex"] = page_index
    return value


class TableLayoutOverlayTests(unittest.TestCase):
    def test_verified_body_match_uses_page_index_not_display_page_number(self) -> None:
        structure = _structure()
        result = build_table_layout_overlay(
            doc_id=DOC_ID,
            blocks=[_block(2, structure)],
            dump_pages=_dump(
                _dump_page(0, page_number=88, anchors=((7, 0),)),
            ),
            render_trees={
                0: _page(
                    _table_node(),
                    header_nodes=(_table_node(bbox={"x": 1, "y": 1, "w": 1, "h": 1}),),
                )
            },
        )

        self.assertEqual(len(result), 1)
        record = result[0]
        self.assertEqual(record["status"], "verified_render")
        self.assertEqual((record["page_start"], record["page_end"]), (1, 1))
        self.assertEqual(len(record["page_bboxes"]), 1)
        self.assertEqual(record["page_bboxes"][0]["page"], 1)
        self.assertEqual(record["coordinate_space"], COORDINATE_SPACE)
        self.assertEqual(
            record["render_key"],
            {"section": 0, "paragraph": 7, "control": 0},
        )

    def test_multi_page_nodes_are_deduplicated_and_overflow_is_not_clamped(self) -> None:
        structure = _structure()
        first = _table_node(bbox={"x": 10, "y": 20, "w": 30, "h": 40})
        overflow = _table_node(bbox={"x": 10, "y": 80, "w": 30, "h": 40})
        result = build_table_layout_overlay(
            doc_id=DOC_ID,
            blocks=[_block(3, structure)],
            dump_pages=_dump(
                _dump_page(0, anchors=((7, 0),)),
                _dump_page(1),
            ),
            render_trees={
                0: _page(first, dict(first)),
                1: _page(overflow),
            },
        )

        record = result[0]
        self.assertEqual((record["page_start"], record["page_end"]), (1, 2))
        self.assertEqual(len(record["page_bboxes"]), 2)
        second = record["page_bboxes"][1]
        self.assertEqual(second["bbox"], {"x": 10.0, "y": 80.0, "w": 30.0, "h": 40.0})
        self.assertFalse(second["bbox_valid"])

    def test_dump_anchor_without_verified_render_never_assigns_a_page(self) -> None:
        structure = _structure()
        result = build_table_layout_overlay(
            doc_id=DOC_ID,
            blocks=[_block(4, structure)],
            dump_pages=_dump(_dump_page(0, page_number=999, anchors=((7, 0),))),
            render_trees={0: _page()},
        )

        record = result[0]
        self.assertEqual(record["status"], "paragraph_anchor_candidate")
        self.assertTrue(record["anchor_present"])
        self.assertIsNone(record["page_start"])
        self.assertIsNone(record["page_end"])
        self.assertEqual(record["page_bboxes"], [])

    def test_header_footer_source_tables_are_explicitly_unlinked(self) -> None:
        structure = _structure(
            container_path=[{"kind": "header", "paragraph": 0, "control": 0}]
        )
        result = build_table_layout_overlay(
            doc_id=DOC_ID,
            blocks=[_block(5, structure)],
            dump_pages=_dump(_dump_page(0)),
            render_trees={
                0: _page(header_nodes=(_table_node(),))
            },
        )

        record = result[0]
        self.assertEqual(record["status"], "nonbody_unlinked")
        self.assertIsNone(record["page_start"])
        self.assertEqual(record["page_bboxes"], [])

    def test_wrapper_flattening_requires_exact_direct_nested_shape(self) -> None:
        nested = _structure(rows=3, cols=4, paragraph=1)
        wrapper_cell = {
            "row": 0,
            "col": 0,
            "row_span": 1,
            "col_span": 1,
            "is_header": False,
            "text": "",
            "nested": [nested],
        }
        wrapper = _structure(rows=1, cols=1, cells=[wrapper_cell])
        flattened = build_table_layout_overlay(
            doc_id=DOC_ID,
            blocks=[_block(6, wrapper)],
            dump_pages=_dump(_dump_page(0, anchors=((7, 0),))),
            render_trees={0: _page(_table_node(rows=3, cols=4))},
        )[0]
        mismatched = build_table_layout_overlay(
            doc_id=DOC_ID,
            blocks=[_block(7, wrapper)],
            dump_pages=_dump(_dump_page(0, anchors=((7, 0),))),
            render_trees={0: _page(_table_node(rows=3, cols=5))},
        )[0]

        self.assertEqual(flattened["status"], "verified_render")
        self.assertTrue(flattened["wrapper_flattened"])
        self.assertEqual(mismatched["status"], "paragraph_anchor_candidate")
        self.assertFalse(mismatched["wrapper_flattened"])

    def test_nested_render_table_cannot_impersonate_a_top_level_match(self) -> None:
        structure = _structure(rows=2, cols=2)
        nested_match = _table_node(rows=2, cols=2)
        top_level_mismatch = _table_node(
            rows=3,
            cols=3,
            children=[nested_match],
        )

        record = build_table_layout_overlay(
            doc_id=DOC_ID,
            blocks=[_block(8, structure)],
            dump_pages=_dump(_dump_page(0, anchors=((7, 0),))),
            render_trees={0: _page(top_level_mismatch)},
        )[0]

        self.assertEqual(record["status"], "paragraph_anchor_candidate")
        self.assertIsNone(record["page_start"])

    def test_records_are_sorted_by_stable_block_identity(self) -> None:
        first = _structure(paragraph=1)
        second = _structure(paragraph=2)
        records = build_table_layout_overlay(
            doc_id=DOC_ID,
            blocks=[_block(10, second), _block(9, first)],
            dump_pages=_dump(_dump_page(0)),
            render_trees={0: _page()},
        )
        self.assertEqual(
            [record["block_id"] for record in records],
            [f"block_{9:024x}", f"block_{10:024x}"],
        )


class RenderTreeDirectoryTests(unittest.TestCase):
    def test_loader_accepts_strict_numbering_and_embedded_page_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "render_tree_001.json").write_text(
                json.dumps(_page(page_index=0)), encoding="utf-8"
            )
            (root / "render_tree_002.json").write_text(
                json.dumps(_page(page_index=1)), encoding="utf-8"
            )

            pages = load_render_tree_directory(root)

        self.assertEqual(list(pages), [0, 1])

    def test_loader_rejects_gaps_duplicate_ordinals_and_payload_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gap = Path(temp_dir)
            (gap / "render_tree_001.json").write_text(
                json.dumps(_page()), encoding="utf-8"
            )
            (gap / "render_tree_003.json").write_text(
                json.dumps(_page()), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "render_tree_page_index_gap"):
                load_render_tree_directory(gap)

        with tempfile.TemporaryDirectory() as temp_dir:
            duplicate = Path(temp_dir)
            (duplicate / "render_tree_001.json").write_text(
                json.dumps(_page()), encoding="utf-8"
            )
            (duplicate / "render_tree_0001.json").write_text(
                json.dumps(_page()), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "render_tree_filename_invalid"):
                load_render_tree_directory(duplicate)

        with tempfile.TemporaryDirectory() as temp_dir:
            mismatch = Path(temp_dir)
            (mismatch / "render_tree_001.json").write_text(
                json.dumps(_page(page_index=4)), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "render_tree_page_index_mismatch"):
                load_render_tree_directory(mismatch)

    def test_bounded_rhwp_runner_loads_dump_and_render_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            command = root / "rhwp"
            command.write_bytes(b"binary")
            source = root / "source.hwp"
            source.write_bytes(b"source")

            def fake_run(argv, *, timeout_seconds, max_stdout_bytes):
                self.assertEqual(timeout_seconds, 15)
                if argv[1] == "dump-pages":
                    return 0, json.dumps(_dump(_dump_page(0))).encode("utf-8"), None
                self.assertEqual(argv[1], "export-render-tree")
                output_dir = Path(argv[-1])
                (output_dir / "render_tree_001.json").write_text(
                    json.dumps(_page()), encoding="utf-8"
                )
                return 0, b"", None

            with patch(
                "midprojectrag.ingest.table_layout._run_bounded",
                side_effect=fake_run,
            ):
                dump_pages, render_trees = load_rhwp_layout_inputs(
                    str(command.resolve()),
                    source,
                    timeout_seconds=15,
                )

        self.assertEqual(dump_pages["pageCount"], 1)
        self.assertEqual(list(render_trees), [0])


if __name__ == "__main__":
    unittest.main()
