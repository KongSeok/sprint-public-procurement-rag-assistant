from __future__ import annotations

import gc
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
import weakref
from collections.abc import MutableSequence
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

from midprojectrag.ingest.common import canonical_json, sha256_text
from midprojectrag.ingest.pdf_visual import (
    LINES_TABLE_SETTINGS,
    PdfVisualError,
    PdfVisualLimits,
    _open_pdf,
    extract_pdf_visual_evidence,
)


ROOT = Path(__file__).resolve().parents[2]
DOC_ID = "doc_0123456789abcdef01234567"


def _horizontal_line(x0: float, x1: float, y: float) -> dict[str, object]:
    return {
        "object_type": "line",
        "orientation": "h",
        "x0": x0,
        "x1": x1,
        "top": y,
        "bottom": y,
        "width": x1 - x0,
        "height": 0,
    }


def _vertical_line(x: float, top: float, bottom: float) -> dict[str, object]:
    return {
        "object_type": "line",
        "orientation": "v",
        "x0": x,
        "x1": x,
        "top": top,
        "bottom": bottom,
        "width": 0,
        "height": bottom - top,
    }


class _FakeRow:
    def __init__(self, cells) -> None:
        self.cells = list(cells)


class _FakeTable:
    def __init__(
        self,
        *,
        matrix=None,
        bbox=(50, 200, 300, 350),
        row_cells=None,
    ) -> None:
        self.bbox = bbox
        self._matrix = (
            matrix if matrix is not None else [["Task", "M"], ["Build", "▲"]]
        )
        if row_cells is None:
            row_count = len(self._matrix)
            col_count = max((len(row) for row in self._matrix), default=0)
            left, top, right, bottom = bbox
            cell_width = (right - left) / col_count
            cell_height = (bottom - top) / row_count
            row_cells = [
                [
                    (
                        left + col * cell_width,
                        top + row * cell_height,
                        left + (col + 1) * cell_width,
                        top + (row + 1) * cell_height,
                    )
                    for col in range(col_count)
                ]
                for row in range(row_count)
            ]
        self.rows = [_FakeRow(cells) for cells in row_cells]
        self.cells = [
            cell for row in self.rows for cell in row.cells if cell is not None
        ]

    def extract(self):
        return [list(row) for row in self._matrix]


class _FakePage:
    def __init__(
        self,
        *,
        table=None,
        tables=None,
        images=None,
        text_lines=None,
        words=None,
        rects=None,
        lines=None,
        chars=None,
        bbox=(0, 0, 600, 800),
    ) -> None:
        self.bbox = bbox
        if table is not None and tables is not None:
            raise AssertionError("table and tables are mutually exclusive")
        self._tables = (
            list(tables)
            if tables is not None
            else [table if table is not None else _FakeTable()]
        )
        self.images = (
            list(images)
            if images is not None
            else [
                {"x0": 400, "top": 100, "x1": 500, "bottom": 180},
                {"x0": 350, "top": 500, "x1": 550, "bottom": 700},
            ]
        )
        self.rects = (
            list(rects)
            if rects is not None
            else [
                {
                    "x0": 55,
                    "top": 230,
                    "x1": 100,
                    "bottom": 250,
                    "fill": True,
                    "non_stroking_color": (0.1, 0.2, 0.3),
                },
                {
                    "x0": 110,
                    "top": 230,
                    "x1": 150,
                    "bottom": 250,
                    "fill": False,
                    "non_stroking_color": "must-not-be-used",
                },
                {
                    "x0": 10,
                    "top": 10,
                    "x1": 20,
                    "bottom": 20,
                    "fill": True,
                    "non_stroking_color": 0,
                },
            ]
        )
        self.lines = list(lines) if lines is not None else []
        self.chars = list(chars) if chars is not None else [{} for _ in range(30)]
        self._text_lines = (
            list(text_lines)
            if text_lines is not None
            else [
                {
                    "text": "Synthetic heading",
                    "x0": 50,
                    "top": 20,
                    "x1": 180,
                    "bottom": 40,
                },
                {
                    "text": "table cell text",
                    "x0": 60,
                    "top": 220,
                    "x1": 180,
                    "bottom": 240,
                },
                {
                    "text": "Following section",
                    "x0": 50,
                    "top": 420,
                    "x1": 190,
                    "bottom": 440,
                },
            ]
        )
        self._words = list(words) if words is not None else []
        self.objects = {
            "char": list(self.chars),
            "line": list(self.lines),
            "rect": list(self.rects),
            "image": list(self.images),
        }
        self.seen_settings = None
        self.seen_word_settings = None

    def find_tables(self, *, table_settings):
        self.seen_settings = dict(table_settings)
        return type("FakeTableFinder", (), {"tables": list(self._tables)})()

    def extract_text_lines(self, *, layout, strip, return_chars):
        if (layout, strip, return_chars) != (False, True, False):
            raise AssertionError("unexpected text extraction settings")
        return [dict(line) for line in self._text_lines]

    def extract_words(self, **settings):
        self.seen_word_settings = dict(settings)
        return [dict(word) for word in self._words]


class _FakePdf:
    def __init__(self, pages) -> None:
        self.pages = list(pages)
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _source(root: Path, name: str = "synthetic.pdf") -> tuple[Path, str]:
    data = b"%PDF-1.7\nsynthetic-local-fixture\n%%EOF\n"
    path = root / name
    path.write_bytes(data)
    return path, hashlib.sha256(data).hexdigest()


class PdfVisualEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(
            (ROOT / "contracts" / "pdf-visual-evidence.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator.check_schema(cls.schema)

    def _extract(
        self,
        source: Path,
        digest: str,
        page: _FakePage,
        *,
        analysis_sink=None,
    ):
        with patch(
            "midprojectrag.ingest.pdf_visual._open_pdf",
            return_value=_FakePdf([page]),
        ):
            kwargs = {
                "source_path": source,
                "doc_id": DOC_ID,
                "expected_sha256": digest,
            }
            if analysis_sink is not None:
                kwargs["analysis_sink"] = analysis_sink
            return extract_pdf_visual_evidence(
                **kwargs,
            )

    def test_deterministic_table_image_order_context_lines_strategy_and_schema(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            source, digest = _source(Path(name))
            first_page = _FakePage()
            first = self._extract(source, digest, first_page)
            second_page = _FakePage()
            second = self._extract(source, digest, second_page)

        self.assertEqual(first, second)
        self.assertEqual(first_page.seen_settings, dict(LINES_TABLE_SETTINGS))
        self.assertEqual(first_page.seen_settings["vertical_strategy"], "lines")
        self.assertEqual(first_page.seen_settings["horizontal_strategy"], "lines")
        self.assertEqual(
            [(row["node_type"], row["sequence_in_page"]) for row in first],
            [("image", 0), ("table", 1), ("image", 2)],
        )
        self.assertEqual(
            [row["status"] for row in first],
            [
                "image_geometry_candidate",
                "line_table_candidate",
                "image_geometry_candidate",
            ],
        )
        self.assertEqual(first[0]["preceding_text"]["text"], "Synthetic heading")
        self.assertEqual(first[1]["preceding_text"]["text"], "Synthetic heading")
        self.assertEqual(first[2]["preceding_text"]["text"], "Following section")

        table = first[1]
        self.assertEqual(table["content"]["matrix"], [["Task", "M"], ["Build", "▲"]])
        self.assertEqual(table["content"]["rows"], 2)
        self.assertEqual(table["content"]["cols"], 2)
        self.assertEqual(len(table["content"]["direct_fill_evidence"]), 1)
        self.assertEqual(
            table["content"]["direct_fill_evidence"][0]["raw_non_stroking_color"],
            [0.1, 0.2, 0.3],
        )
        self.assertNotIn("color_name", canonical_json(table))
        self.assertNotIn("ocr", canonical_json(first).lower())
        self.assertNotIn("asset", canonical_json(first).lower())

        for record in first:
            Draft202012Validator(self.schema).validate(record)
            self.assertEqual(
                record["content_sha256"],
                sha256_text(canonical_json(record["content"])),
            )
            if record["preceding_text"] is not None:
                self.assertEqual(
                    record["preceding_text"]["text_sha256"],
                    sha256_text(record["preceding_text"]["text"]),
                )

    def test_lines_table_settings_are_frozen_and_hash_commits_effective_values(self) -> None:
        import midprojectrag.ingest.pdf_visual as module

        original = dict(LINES_TABLE_SETTINGS)
        expected_hash = sha256_text(canonical_json(original))
        self.assertEqual(module.LINES_TABLE_SETTINGS_SHA256, expected_hash)
        try:
            with self.assertRaises(TypeError):
                LINES_TABLE_SETTINGS["vertical_strategy"] = "text"
        finally:
            if isinstance(LINES_TABLE_SETTINGS, dict):
                LINES_TABLE_SETTINGS.clear()
                LINES_TABLE_SETTINGS.update(original)
        self.assertEqual(dict(LINES_TABLE_SETTINGS), original)
        self.assertEqual(module.LINES_TABLE_SETTINGS_SHA256, expected_hash)

    def test_table_overlap_words_reconstruct_empty_cells_and_keep_milestone(self) -> None:
        table = _FakeTable(
            matrix=[["Task", "M", "M+1", "M+2"], [None, None, "◆", None]],
            bbox=(50, 200, 450, 300),
            row_cells=[
                [
                    (50, 200, 150, 250),
                    (150, 200, 250, 250),
                    (250, 200, 350, 250),
                    (350, 200, 450, 250),
                ],
                [
                    (50, 250, 150, 300),
                    (150, 250, 250, 300),
                    (250, 250, 350, 300),
                    (350, 250, 450, 300),
                ],
            ],
        )
        words = [
            {"text": "Build", "x0": 60, "top": 265, "x1": 105, "bottom": 280},
            {"text": "◆", "x0": 290, "top": 265, "x1": 305, "bottom": 280},
        ]
        page = _FakePage(
            table=table,
            images=[],
            rects=[],
            lines=[
                *(_horizontal_line(50, 450, y) for y in (200, 250, 300)),
                *(
                    _vertical_line(x, 200, 300)
                    for x in (50, 150, 250, 350, 450)
                ),
            ],
            words=words,
            text_lines=[
                {"text": "Schedule", "x0": 50, "top": 160, "x1": 120, "bottom": 180},
                *words,
            ],
        )

        with tempfile.TemporaryDirectory() as name:
            source, digest = _source(Path(name))
            records = self._extract(source, digest, page)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["node_type"], "table")
        self.assertEqual(
            records[0]["content"]["matrix"],
            [
                ["Task", "M", "M+1", "M+2"],
                ["Build", None, "◆", None],
            ],
        )
        self.assertEqual(records[0]["content"]["rows"], 2)
        self.assertEqual(records[0]["content"]["cols"], 4)

    def test_schedule_recovers_first_column_label_without_left_vertical_cell(self) -> None:
        table = _FakeTable(
            matrix=[["Task", "M", "M+1", "M+2"], [None, "▲", None, None]],
            bbox=(50, 200, 450, 300),
            row_cells=[
                [
                    (50, 200, 150, 250),
                    (150, 200, 250, 250),
                    (250, 200, 350, 250),
                    (350, 200, 450, 250),
                ],
                [
                    None,
                    (150, 250, 250, 300),
                    (250, 250, 350, 300),
                    (350, 250, 450, 300),
                ],
            ],
        )
        page = _FakePage(
            table=table,
            images=[],
            rects=[],
            lines=[
                *(_horizontal_line(50, 450, y) for y in (200, 250, 300)),
                *(
                    _vertical_line(x, 200, 300)
                    for x in (150, 250, 350, 450)
                ),
            ],
            words=[
                {
                    "text": "Schedule",
                    "x0": 70,
                    "top": 160,
                    "x1": 140,
                    "bottom": 180,
                },
                {
                    "text": "Build",
                    "x0": 80,
                    "top": 265,
                    "x1": 125,
                    "bottom": 280,
                },
            ],
            text_lines=[
                {"text": "Schedule", "x0": 70, "top": 160, "x1": 140, "bottom": 180},
                {"text": "Build", "x0": 80, "top": 265, "x1": 125, "bottom": 280},
            ],
        )

        with tempfile.TemporaryDirectory() as name:
            source, digest = _source(Path(name))
            records = self._extract(source, digest, page)

        self.assertEqual(len(records), 1)
        self.assertEqual(
            records[0]["content"]["matrix"],
            [
                ["Task", "M", "M+1", "M+2"],
                ["Build", "▲", None, None],
            ],
        )

    def test_true_no_label_column_keeps_m_column_and_reports_external_label_only_in_analysis(self) -> None:
        table = _FakeTable(
            matrix=[["M", "M+1"], [None, "▲"]],
            bbox=(180, 200, 380, 300),
            row_cells=[
                [(180, 200, 280, 250), (280, 200, 380, 250)],
                [(180, 250, 280, 300), (280, 250, 380, 300)],
            ],
        )
        page = _FakePage(
            table=table,
            images=[],
            rects=[],
            lines=[
                *(_horizontal_line(50, 380, y) for y in (200, 250, 300)),
                *(_vertical_line(x, 200, 300) for x in (180, 280, 380)),
            ],
            words=[
                {"text": "Build", "x0": 80, "top": 265, "x1": 125, "bottom": 280},
                {"text": "▲", "x0": 320, "top": 265, "x1": 335, "bottom": 280},
            ],
            text_lines=[
                {"text": "Schedule", "x0": 50, "top": 160, "x1": 120, "bottom": 180},
                {"text": "Build", "x0": 80, "top": 265, "x1": 125, "bottom": 280},
            ],
        )
        analyses = []

        with tempfile.TemporaryDirectory() as name:
            source, digest = _source(Path(name))
            records = self._extract(
                source,
                digest,
                page,
                analysis_sink=analyses,
            )

        expected_matrix = [["M", "M+1"], [None, "▲"]]
        self.assertEqual(records[0]["content"]["matrix"], expected_matrix)
        self.assertNotIn("Build", canonical_json(records[0]))
        self.assertEqual(len(analyses), 1)
        self.assertEqual(analyses[0].matrix, tuple(tuple(row) for row in expected_matrix))
        self.assertEqual(len(analyses[0].schedule_rows), 1)
        row = analyses[0].schedule_rows[0]
        self.assertEqual(row.label, "Build")
        self.assertEqual(row.milestone_periods, ("M+1",))
        self.assertFalse(row.recovered_matrix_cell)

    def test_external_label_requires_two_consistent_row_rules_not_one_decoration(self) -> None:
        def no_label_page(lines) -> _FakePage:
            return _FakePage(
                table=_FakeTable(
                    matrix=[["M", "M+1"], [None, "▲"]],
                    bbox=(180, 200, 380, 300),
                    row_cells=[
                        [(180, 200, 280, 250), (280, 200, 380, 250)],
                        [(180, 250, 280, 300), (280, 250, 380, 300)],
                    ],
                ),
                images=[],
                rects=[],
                lines=lines,
                words=[
                    {
                        "text": "Build",
                        "x0": 80,
                        "top": 265,
                        "x1": 125,
                        "bottom": 280,
                    }
                ],
                text_lines=[],
            )

        single_analyses = []
        consistent_analyses = []
        with tempfile.TemporaryDirectory() as name:
            source, digest = _source(Path(name))
            single = self._extract(
                source,
                digest,
                no_label_page([_horizontal_line(50, 380, 250)]),
                analysis_sink=single_analyses,
            )[0]
            consistent = self._extract(
                source,
                digest,
                no_label_page(
                    [
                        _horizontal_line(50, 380, 250),
                        _horizontal_line(50, 380, 300),
                    ]
                ),
                analysis_sink=consistent_analyses,
            )[0]

        expected_matrix = [["M", "M+1"], [None, "▲"]]
        self.assertEqual(single["content"]["matrix"], expected_matrix)
        self.assertEqual(consistent["content"]["matrix"], expected_matrix)
        self.assertEqual(single_analyses[0].schedule_rows, ())
        self.assertIn(
            "schedule_label_region_unavailable",
            single_analyses[0].reasons,
        )
        self.assertEqual(len(consistent_analyses[0].schedule_rows), 1)
        row = consistent_analyses[0].schedule_rows[0]
        self.assertEqual(row.label, "Build")
        self.assertFalse(row.recovered_matrix_cell)

    def test_empty_native_words_use_matrix_milestone_without_inventing_text(self) -> None:
        table = _FakeTable(
            matrix=[["Task", "M", "M+1"], ["Deploy", None, "▲"]],
            bbox=(50, 200, 350, 300),
            row_cells=[
                [
                    (50, 200, 150, 250),
                    (150, 200, 250, 250),
                    (250, 200, 350, 250),
                ],
                [
                    (50, 250, 150, 300),
                    (150, 250, 250, 300),
                    (250, 250, 350, 300),
                ],
            ],
        )
        analyses = []

        with tempfile.TemporaryDirectory() as name:
            source, digest = _source(Path(name))
            records = self._extract(
                source,
                digest,
                _FakePage(
                    table=table,
                    images=[],
                    rects=[],
                    lines=[],
                    words=[],
                    text_lines=[],
                ),
                analysis_sink=analyses,
            )

        self.assertEqual(
            records[0]["content"]["matrix"],
            [["Task", "M", "M+1"], ["Deploy", None, "▲"]],
        )
        self.assertEqual(len(analyses[0].schedule_rows), 1)
        row = analyses[0].schedule_rows[0]
        self.assertEqual(row.label, "Deploy")
        self.assertEqual(row.milestone_periods, ("M+1",))
        self.assertEqual(row.role, "milestone")
        self.assertFalse(row.recovered_matrix_cell)

    def test_matrix_label_geometry_conflict_keeps_matrix_and_rejects_word_bbox(self) -> None:
        def schedule_page(word_text: str) -> _FakePage:
            return _FakePage(
                table=_FakeTable(
                    matrix=[["Task", "M", "M+1"], ["Build", None, None]],
                    bbox=(50, 200, 350, 300),
                    row_cells=[
                        [
                            (50, 200, 150, 250),
                            (150, 200, 250, 250),
                            (250, 200, 350, 250),
                        ],
                        [
                            (50, 250, 150, 300),
                            (150, 250, 250, 300),
                            (250, 250, 350, 300),
                        ],
                    ],
                ),
                images=[],
                rects=[],
                lines=[],
                words=[
                    {
                        "text": word_text,
                        "x0": 60,
                        "top": 265,
                        "x1": 110,
                        "bottom": 280,
                    }
                ],
                text_lines=[],
            )

        matched_analyses = []
        conflict_analyses = []
        with tempfile.TemporaryDirectory() as name:
            source, digest = _source(Path(name))
            matched = self._extract(
                source,
                digest,
                schedule_page("Build"),
                analysis_sink=matched_analyses,
            )[0]
            conflict = self._extract(
                source,
                digest,
                schedule_page("Deploy"),
                analysis_sink=conflict_analyses,
            )[0]

        expected_matrix = [["Task", "M", "M+1"], ["Build", None, None]]
        self.assertEqual(matched["content"]["matrix"], expected_matrix)
        self.assertEqual(conflict["content"]["matrix"], expected_matrix)
        self.assertNotIn("Deploy", canonical_json(conflict))
        matched_row = matched_analyses[0].schedule_rows[0]
        conflict_row = conflict_analyses[0].schedule_rows[0]
        self.assertEqual(conflict_row.label, "Build")
        self.assertEqual(matched_row.label_bbox, (60.0, 265.0, 50.0, 15.0))
        self.assertNotEqual(
            conflict_row.label_bbox,
            (60.0, 265.0, 50.0, 15.0),
        )
        self.assertLess(conflict_row.confidence, matched_row.confidence)
        self.assertLess(conflict_row.confidence, 0.85)
        self.assertIn(
            "matrix_geometry_label_conflict",
            conflict_analyses[0].reasons,
        )

    def test_direct_fill_filters_hairline_and_near_white_but_keeps_black_bar(self) -> None:
        rects = [
            {
                "x0": 55,
                "top": 230,
                "x1": 100,
                "bottom": 250,
                "fill": True,
                "non_stroking_color": (0.1, 0.2, 0.3),
            },
            {
                "x0": 55,
                "top": 260,
                "x1": 150,
                "bottom": 260.2,
                "fill": True,
                "non_stroking_color": 0,
            },
            {
                "x0": 110,
                "top": 230,
                "x1": 150,
                "bottom": 250,
                "fill": True,
                "non_stroking_color": (1, 1, 1),
            },
            {
                "x0": 160,
                "top": 230,
                "x1": 200,
                "bottom": 250,
                "fill": True,
                "non_stroking_color": 0.99,
            },
            {
                "x0": 210,
                "top": 270,
                "x1": 250,
                "bottom": 290,
                "fill": True,
                "non_stroking_color": 0,
            },
        ]
        page = _FakePage(
            table=_FakeTable(
                matrix=[["Task", "M", "M+1"], ["Build", None, None]],
                bbox=(50, 200, 350, 350),
            ),
            images=[],
            rects=rects,
        )

        with tempfile.TemporaryDirectory() as name:
            source, digest = _source(Path(name))
            records = self._extract(source, digest, page)

        evidence = records[0]["content"]["direct_fill_evidence"]
        self.assertEqual(len(evidence), 2)
        self.assertEqual(evidence[0]["raw_non_stroking_color"], [0.1, 0.2, 0.3])
        self.assertEqual(
            evidence[0]["bbox"],
            {"x": 55.0, "y": 230.0, "w": 45.0, "h": 20.0},
        )
        self.assertEqual(evidence[1]["raw_non_stroking_color"], 0.0)
        self.assertEqual(
            evidence[1]["bbox"],
            {"x": 210.0, "y": 270.0, "w": 40.0, "h": 20.0},
        )

    def test_cmyk_white_background_is_filtered_but_substantive_black_is_kept(self) -> None:
        table = _FakeTable(
            matrix=[["Task", "M", "M+1"], ["Build", None, None]],
            bbox=(50, 200, 350, 350),
        )
        page = _FakePage(
            table=table,
            images=[],
            rects=[
                {
                    "x0": 60,
                    "top": 270,
                    "x1": 100,
                    "bottom": 290,
                    "fill": True,
                    "non_stroking_color": (0, 0, 0, 0),
                },
                {
                    "x0": 210,
                    "top": 270,
                    "x1": 250,
                    "bottom": 290,
                    "fill": True,
                    "non_stroking_color": (0, 0, 0, 1),
                },
            ],
        )

        with tempfile.TemporaryDirectory() as name:
            source, digest = _source(Path(name))
            records = self._extract(source, digest, page)

        evidence = records[0]["content"]["direct_fill_evidence"]
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["raw_non_stroking_color"], [0.0, 0.0, 0.0, 1.0])
        self.assertEqual(
            evidence[0]["bbox"],
            {"x": 210.0, "y": 270.0, "w": 40.0, "h": 20.0},
        )

    def test_overlapping_fill_coverage_uses_geometric_union_not_sum(self) -> None:
        table = _FakeTable(
            matrix=[["Task", "M", "M+1"], ["Build", None, None]],
            bbox=(50, 200, 350, 300),
            row_cells=[
                [
                    (50, 200, 150, 250),
                    (150, 200, 250, 250),
                    (250, 200, 350, 250),
                ],
                [
                    (50, 250, 150, 300),
                    (150, 250, 250, 300),
                    (250, 250, 350, 300),
                ],
            ],
        )
        duplicate_fill = {
            "x0": 160,
            "top": 260,
            "x1": 210,
            "bottom": 275,
            "fill": True,
            "non_stroking_color": (0.2, 0.4, 0.6),
        }
        analyses = []

        with tempfile.TemporaryDirectory() as name:
            source, digest = _source(Path(name))
            self._extract(
                source,
                digest,
                _FakePage(
                    table=table,
                    images=[],
                    rects=[duplicate_fill, dict(duplicate_fill)],
                    words=[],
                    text_lines=[],
                ),
                analysis_sink=analyses,
            )

        self.assertEqual(len(analyses[0].schedule_rows), 1)
        row = analyses[0].schedule_rows[0]
        self.assertEqual(row.active_periods, ())
        self.assertEqual(row.role, "label_only")

    def test_full_row_fill_is_full_span_not_ordinary_activity(self) -> None:
        table = _FakeTable(
            matrix=[["Task", "M", "M+1"], ["Build", None, None]],
            bbox=(50, 200, 350, 300),
            row_cells=[
                [
                    (50, 200, 150, 250),
                    (150, 200, 250, 250),
                    (250, 200, 350, 250),
                ],
                [
                    (50, 250, 150, 300),
                    (150, 250, 250, 300),
                    (250, 250, 350, 300),
                ],
            ],
        )
        analyses = []

        with tempfile.TemporaryDirectory() as name:
            source, digest = _source(Path(name))
            self._extract(
                source,
                digest,
                _FakePage(
                    table=table,
                    images=[],
                    rects=[
                        {
                            "x0": 50,
                            "top": 250,
                            "x1": 350,
                            "bottom": 300,
                            "fill": True,
                            "non_stroking_color": (0.2, 0.4, 0.6),
                        }
                    ],
                    words=[],
                    text_lines=[],
                ),
                analysis_sink=analyses,
            )

        row = analyses[0].schedule_rows[0]
        self.assertEqual(row.active_periods, ("M", "M+1"))
        self.assertEqual(row.role, "full_span")
        self.assertNotEqual(row.role, "activity")

    def test_full_page_empty_two_by_two_frame_is_suppressed_but_populated_table_remains(self) -> None:
        full_page_frame = _FakeTable(
            matrix=[[None, None], [None, None]],
            bbox=(0, 0, 600, 800),
            row_cells=[
                [(0, 0, 300, 400), (300, 0, 600, 400)],
                [(0, 400, 300, 800), (300, 400, 600, 800)],
            ],
        )
        populated_full_page = _FakeTable(
            matrix=[["Key", "Value"], ["A", "B"]],
            bbox=(0, 0, 600, 800),
            row_cells=[
                [(0, 0, 300, 400), (300, 0, 600, 400)],
                [(0, 400, 300, 800), (300, 400, 600, 800)],
            ],
        )
        bounded_table = _FakeTable(
            matrix=[["Key", "Value"], ["A", "B"]],
            bbox=(50, 200, 300, 350),
        )

        with tempfile.TemporaryDirectory() as name:
            source, digest = _source(Path(name))
            suppressed = self._extract(
                source,
                digest,
                _FakePage(
                    table=full_page_frame,
                    images=[],
                    rects=[],
                    text_lines=[],
                    words=[],
                    chars=[],
                    lines=[
                        *(
                            _horizontal_line(0, 600, y)
                            for y in (0, 400, 800)
                        ),
                        *(
                            _vertical_line(x, 0, 800)
                            for x in (0, 300, 600)
                        ),
                    ],
                ),
            )
            populated = self._extract(
                source,
                digest,
                _FakePage(
                    table=populated_full_page,
                    images=[],
                    rects=[],
                    text_lines=[],
                    words=[],
                    chars=[],
                ),
            )
            retained = self._extract(
                source,
                digest,
                _FakePage(
                    table=bounded_table,
                    images=[],
                    rects=[],
                    text_lines=[],
                    words=[],
                ),
            )

        self.assertEqual(suppressed, [])
        self.assertEqual(len(populated), 1)
        self.assertEqual(
            populated[0]["content"]["matrix"],
            [["Key", "Value"], ["A", "B"]],
        )
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0]["node_type"], "table")
        self.assertEqual(
            retained[0]["content"]["matrix"],
            [["Key", "Value"], ["A", "B"]],
        )

    def test_record_id_commits_bbox_source_method_and_preceding_context(self) -> None:
        def page(
            *,
            bbox=(50, 200, 300, 350),
            heading="Synthetic heading",
        ) -> _FakePage:
            return _FakePage(
                table=_FakeTable(bbox=bbox),
                images=[],
                rects=[],
                words=[],
                text_lines=[
                    {
                        "text": heading,
                        "x0": 50,
                        "top": 20,
                        "x1": 180,
                        "bottom": 40,
                    }
                ],
            )

        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source, digest = _source(root, "baseline.pdf")
            other_source = root / "other.pdf"
            other_data = b"%PDF-1.7\ndifferent-source-fixture\n%%EOF\n"
            other_source.write_bytes(other_data)
            other_digest = hashlib.sha256(other_data).hexdigest()

            baseline = self._extract(source, digest, page())[0]
            bbox_drift = self._extract(
                source,
                digest,
                page(bbox=(60, 200, 310, 350)),
            )[0]
            context_drift = self._extract(
                source,
                digest,
                page(heading="Changed heading"),
            )[0]
            source_drift = self._extract(
                other_source,
                other_digest,
                page(),
            )[0]
            with patch(
                "midprojectrag.ingest.pdf_visual.EXTRACTION_METHOD",
                "pdfplumber_lines_v2",
            ):
                method_drift = self._extract(source, digest, page())[0]

        variants = [bbox_drift, context_drift, source_drift, method_drift]
        self.assertTrue(
            all(
                record["content_sha256"] == baseline["content_sha256"]
                for record in variants
            )
        )
        self.assertTrue(
            all(record["record_id"] != baseline["record_id"] for record in variants)
        )
        self.assertEqual(
            len({baseline["record_id"], *(record["record_id"] for record in variants)}),
            5,
        )

    def test_source_checksum_is_verified_before_and_after_parse(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            source, digest = _source(Path(name))
            with patch(
                "midprojectrag.ingest.pdf_visual._open_pdf",
                return_value=_FakePdf([_FakePage()]),
            ):
                with self.assertRaisesRegex(
                    PdfVisualError, "^pdf_source_checksum_mismatch$"
                ):
                    extract_pdf_visual_evidence(
                        source_path=source,
                        doc_id=DOC_ID,
                        expected_sha256="0" * 64,
                    )

            with (
                patch(
                    "midprojectrag.ingest.pdf_visual._open_pdf",
                    return_value=_FakePdf([_FakePage()]),
                ),
                patch(
                    "midprojectrag.ingest.pdf_visual._sha256_stream",
                    side_effect=[digest, "f" * 64],
                ),
            ):
                with self.assertRaisesRegex(PdfVisualError, "^pdf_source_changed$"):
                    extract_pdf_visual_evidence(
                        source_path=source,
                        doc_id=DOC_ID,
                        expected_sha256=digest,
                    )

    def test_opened_descriptor_size_limit_is_rechecked_before_parse(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            source, digest = _source(Path(name))
            initial = source.stat()
            limits = replace(
                PdfVisualLimits(),
                max_file_bytes=initial.st_size,
            )
            oversized = type(
                "OversizedOpenedStat",
                (),
                {
                    "st_mode": initial.st_mode,
                    "st_dev": initial.st_dev,
                    "st_ino": initial.st_ino,
                    "st_size": initial.st_size + 1,
                },
            )()
            with (
                patch(
                    "midprojectrag.ingest.pdf_visual.os.fstat",
                    return_value=oversized,
                ),
                patch(
                    "midprojectrag.ingest.pdf_visual._open_pdf",
                    return_value=_FakePdf([_FakePage()]),
                ) as opener,
            ):
                with self.assertRaisesRegex(
                    PdfVisualError,
                    "^pdf_file_size_limit_exceeded$",
                ):
                    extract_pdf_visual_evidence(
                        source_path=source,
                        doc_id=DOC_ID,
                        expected_sha256=digest,
                        limits=limits,
                    )

        opener.assert_not_called()

    def test_path_policy_rejects_symlink_and_errors_do_not_leak_private_name(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source, _ = _source(root, "TOP-SECRET-proposal.pdf")
            link = root / "private-link.pdf"
            try:
                os.symlink(source.name, link)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            with self.assertRaises(PdfVisualError) as caught:
                extract_pdf_visual_evidence(source_path=link, doc_id=DOC_ID)

        self.assertEqual(str(caught.exception), "pdf_path_symlink_forbidden")
        self.assertNotIn("TOP-SECRET", str(caught.exception))
        self.assertNotIn("private-link", str(caught.exception))

    def test_page_object_table_and_text_bounds_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            source, digest = _source(Path(name))
            cases = [
                (
                    _FakePdf([_FakePage(), _FakePage()]),
                    replace(PdfVisualLimits(), max_pages=1),
                    "pdf_page_limit_exceeded",
                ),
                (
                    _FakePdf([_FakePage()]),
                    replace(PdfVisualLimits(), max_page_objects=1),
                    "pdf_page_objects_limit_exceeded",
                ),
                (
                    _FakePdf([_FakePage()]),
                    replace(PdfVisualLimits(), max_table_rows=1),
                    "pdf_table_row_limit_exceeded",
                ),
                (
                    _FakePdf([_FakePage()]),
                    replace(PdfVisualLimits(), max_text_chars_per_page=4),
                    "pdf_text_line_limit_exceeded",
                ),
            ]
            for fake_pdf, limits, expected_error in cases:
                with self.subTest(expected_error=expected_error):
                    with patch(
                        "midprojectrag.ingest.pdf_visual._open_pdf",
                        return_value=fake_pdf,
                    ):
                        with self.assertRaisesRegex(
                            PdfVisualError, f"^{expected_error}$"
                        ):
                            extract_pdf_visual_evidence(
                                source_path=source,
                                doc_id=DOC_ID,
                                expected_sha256=digest,
                                limits=limits,
                            )

    def test_multi_page_native_words_share_document_text_budget(self) -> None:
        pages = [
            _FakePage(
                tables=[],
                images=[],
                rects=[],
                lines=[],
                chars=[],
                text_lines=[],
                words=[
                    {
                        "text": text,
                        "x0": 50,
                        "top": 50,
                        "x1": 90,
                        "bottom": 70,
                    }
                ],
            )
            for text in ("ABCD", "EFGH")
        ]
        limits = replace(
            PdfVisualLimits(),
            max_text_chars_per_page=10,
            max_text_chars_per_document=6,
        )

        with tempfile.TemporaryDirectory() as name:
            source, digest = _source(Path(name))
            with patch(
                "midprojectrag.ingest.pdf_visual._open_pdf",
                return_value=_FakePdf(pages),
            ):
                with self.assertRaisesRegex(
                    PdfVisualError,
                    "^pdf_document_text_limit_exceeded$",
                ):
                    extract_pdf_visual_evidence(
                        source_path=source,
                        doc_id=DOC_ID,
                        expected_sha256=digest,
                        limits=limits,
                    )

    def test_visual_record_and_analysis_document_caps_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            source, digest = _source(Path(name))
            visual_pages = [
                _FakePage(
                    tables=[],
                    images=[
                        {"x0": 50, "top": 50, "x1": 100, "bottom": 100}
                    ],
                    rects=[],
                    lines=[],
                    chars=[],
                    text_lines=[],
                    words=[],
                )
                for _ in range(2)
            ]
            with patch(
                "midprojectrag.ingest.pdf_visual._open_pdf",
                return_value=_FakePdf(visual_pages),
            ):
                with self.assertRaisesRegex(
                    PdfVisualError,
                    "^pdf_visual_record_limit_exceeded$",
                ):
                    extract_pdf_visual_evidence(
                        source_path=source,
                        doc_id=DOC_ID,
                        expected_sha256=digest,
                        limits=replace(
                            PdfVisualLimits(),
                            max_visual_records_per_document=1,
                        ),
                    )

            analysis_pages = [
                _FakePage(
                    images=[],
                    rects=[],
                    lines=[],
                    chars=[],
                    text_lines=[],
                    words=[],
                )
                for _ in range(2)
            ]
            analyses = []
            with patch(
                "midprojectrag.ingest.pdf_visual._open_pdf",
                return_value=_FakePdf(analysis_pages),
            ):
                with self.assertRaisesRegex(
                    PdfVisualError,
                    "^pdf_analysis_limit_exceeded$",
                ):
                    extract_pdf_visual_evidence(
                        source_path=source,
                        doc_id=DOC_ID,
                        expected_sha256=digest,
                        limits=replace(
                            PdfVisualLimits(),
                            max_visual_records_per_document=10,
                            max_analyses_per_document=1,
                        ),
                        analysis_sink=analyses,
                    )
            self.assertEqual(analyses, [])

    def test_analysis_sink_requires_exact_builtin_list_before_parse_or_mutation(
        self,
    ) -> None:
        class _ListSubclass(list):
            def __init__(self, values) -> None:
                super().__init__(values)
                self.mutation_count = 0

            def append(self, value) -> None:
                self.mutation_count += 1
                super().append(value)

            def extend(self, values) -> None:
                self.mutation_count += 1
                super().extend(values)

        class _CustomMutableSequence(MutableSequence):
            def __init__(self, values) -> None:
                self._values = list(values)
                self.mutation_count = 0

            def __getitem__(self, index):
                return self._values[index]

            def __setitem__(self, index, value) -> None:
                self.mutation_count += 1
                self._values[index] = value

            def __delitem__(self, index) -> None:
                self.mutation_count += 1
                del self._values[index]

            def __len__(self) -> int:
                return len(self._values)

            def insert(self, index, value) -> None:
                self.mutation_count += 1
                self._values.insert(index, value)

        with tempfile.TemporaryDirectory() as name:
            source, digest = _source(Path(name))
            for sink in (
                _ListSubclass(["existing"]),
                _CustomMutableSequence(["existing"]),
            ):
                with self.subTest(sink_type=type(sink).__name__):
                    before = list(sink)
                    with patch(
                        "midprojectrag.ingest.pdf_visual._open_pdf"
                    ) as open_pdf:
                        with self.assertRaisesRegex(
                            PdfVisualError,
                            "^pdf_analysis_sink_invalid$",
                        ):
                            extract_pdf_visual_evidence(
                                source_path=source,
                                doc_id=DOC_ID,
                                expected_sha256=digest,
                                analysis_sink=sink,
                            )
                    open_pdf.assert_not_called()
                    self.assertEqual(list(sink), before)
                    self.assertEqual(sink.mutation_count, 0)

    def test_prepopulated_analysis_sink_is_atomic_on_validation_failures(
        self,
    ) -> None:
        def assert_unchanged(call, expected_error: str) -> None:
            marker = object()
            sink = [marker]
            with self.assertRaisesRegex(PdfVisualError, f"^{expected_error}$"):
                call(sink)
            self.assertEqual(len(sink), 1)
            self.assertIs(sink[0], marker)

        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source, digest = _source(root)
            input_cases = [
                (
                    "path_type",
                    "pdf_path_invalid",
                    {"source_path": str(source)},
                ),
                (
                    "doc_id",
                    "pdf_doc_id_invalid",
                    {"doc_id": "invalid"},
                ),
                (
                    "checksum_shape",
                    "pdf_expected_sha256_invalid",
                    {"expected_sha256": "invalid"},
                ),
                (
                    "limits_type",
                    "pdf_visual_limits_invalid",
                    {"limits": object()},
                ),
                (
                    "limits_value",
                    "pdf_visual_limits_invalid",
                    {"limits": replace(PdfVisualLimits(), max_pages=0)},
                ),
                (
                    "missing_source",
                    "pdf_path_unreadable",
                    {"source_path": root / "missing.pdf"},
                ),
            ]
            for label, expected_error, override in input_cases:
                with self.subTest(stage="input", case=label):
                    kwargs = {
                        "source_path": source,
                        "doc_id": DOC_ID,
                        "expected_sha256": digest,
                    }
                    kwargs.update(override)
                    assert_unchanged(
                        lambda sink, kwargs=kwargs: extract_pdf_visual_evidence(
                            **kwargs,
                            analysis_sink=sink,
                        ),
                        expected_error,
                    )

            first_page = _FakePage(
                images=[],
                rects=[],
                lines=[],
                words=[],
                text_lines=[],
            )
            invalid_second_page = _FakePage(
                tables=[],
                images=[],
                rects=[],
                lines=[],
                words=[],
                text_lines=[],
            )
            with patch.object(
                invalid_second_page,
                "extract_words",
                return_value={"not": "a list"},
            ):
                with patch(
                    "midprojectrag.ingest.pdf_visual._open_pdf",
                    return_value=_FakePdf([first_page, invalid_second_page]),
                ):
                    with self.subTest(stage="publication", case="later_page"):
                        assert_unchanged(
                            lambda sink: extract_pdf_visual_evidence(
                                source_path=source,
                                doc_id=DOC_ID,
                                expected_sha256=digest,
                                analysis_sink=sink,
                            ),
                            "pdf_words_invalid",
                        )

            with (
                patch(
                    "midprojectrag.ingest.pdf_visual._open_pdf",
                    return_value=_FakePdf([first_page]),
                ),
                patch(
                    "midprojectrag.ingest.pdf_visual._sha256_stream",
                    side_effect=[digest, "f" * 64],
                ),
            ):
                with self.subTest(stage="publication", case="source_recheck"):
                    assert_unchanged(
                        lambda sink: extract_pdf_visual_evidence(
                            source_path=source,
                            doc_id=DOC_ID,
                            expected_sha256=digest,
                            analysis_sink=sink,
                        ),
                        "pdf_source_changed",
                    )

            with patch(
                "midprojectrag.ingest.pdf_visual._open_pdf",
                return_value=_FakePdf([first_page, first_page]),
            ):
                with self.subTest(stage="publication", case="analysis_budget"):
                    assert_unchanged(
                        lambda sink: extract_pdf_visual_evidence(
                            source_path=source,
                            doc_id=DOC_ID,
                            expected_sha256=digest,
                            limits=replace(
                                PdfVisualLimits(),
                                max_analyses_per_document=1,
                            ),
                            analysis_sink=sink,
                        ),
                        "pdf_analysis_limit_exceeded",
                    )

    def test_absent_analysis_sink_does_not_retain_prior_page_analysis(self) -> None:
        class _ObservableAnalysis:
            def __init__(self, matrix) -> None:
                self.matrix = tuple(tuple(row) for row in matrix)
                self.recovered_cell_texts = ()

        weak_analyses = []
        retained_before_next_page = []

        def observable_analysis(**kwargs):
            if weak_analyses:
                gc.collect()
                retained_before_next_page.append(weak_analyses[-1]() is not None)
            analysis = _ObservableAnalysis(kwargs["matrix"])
            weak_analyses.append(weakref.ref(analysis))
            return analysis

        with tempfile.TemporaryDirectory() as name:
            source, digest = _source(Path(name))
            with (
                patch(
                    "midprojectrag.ingest.pdf_visual._open_pdf",
                    return_value=_FakePdf(
                        [
                            _FakePage(images=[], rects=[], words=[]),
                            _FakePage(images=[], rects=[], words=[]),
                        ]
                    ),
                ),
                patch(
                    "midprojectrag.ingest.pdf_visual._schedule_geometry_analysis",
                    side_effect=observable_analysis,
                ),
            ):
                extract_pdf_visual_evidence(
                    source_path=source,
                    doc_id=DOC_ID,
                    expected_sha256=digest,
                )

        self.assertNotIn(True, retained_before_next_page)

    def test_word_and_line_operational_degradation_fails_with_stable_codes(self) -> None:
        def exploding_lines(_page):
            raise RuntimeError("private renderer detail")

        cases = [
            (
                "word_exception",
                lambda page: patch.object(
                    page,
                    "extract_words",
                    side_effect=RuntimeError("private word detail"),
                ),
                "pdf_word_extraction_failed",
            ),
            (
                "word_non_list",
                lambda page: patch.object(
                    page,
                    "extract_words",
                    return_value={"not": "a list"},
                ),
                "pdf_words_invalid",
            ),
            (
                "lines_exception",
                lambda _page: patch.object(
                    _FakePage,
                    "lines",
                    property(exploding_lines),
                    create=True,
                ),
                "pdf_lines_invalid",
            ),
            (
                "lines_non_sequence",
                lambda page: patch.object(
                    page,
                    "lines",
                    {"not": "a sequence"},
                ),
                "pdf_lines_invalid",
            ),
        ]

        with tempfile.TemporaryDirectory() as name:
            source, digest = _source(Path(name))
            for label, degradation, error_code in cases:
                with self.subTest(case=label):
                    page = _FakePage(images=[], rects=[], words=[], lines=[])
                    with degradation(page):
                        with self.assertRaisesRegex(
                            PdfVisualError,
                            f"^{error_code}$",
                        ):
                            self._extract(source, digest, page)

    def test_successful_empty_words_and_lines_are_valid_unresolved_evidence(self) -> None:
        table = _FakeTable(
            matrix=[["M", "M+1"], [None, "▲"]],
            bbox=(180, 200, 380, 300),
            row_cells=[
                [(180, 200, 280, 250), (280, 200, 380, 250)],
                [(180, 250, 280, 300), (280, 250, 380, 300)],
            ],
        )
        page = _FakePage(
            table=table,
            images=[],
            rects=[],
            words=[],
            lines=[],
            text_lines=[],
        )
        analyses = []

        with tempfile.TemporaryDirectory() as name:
            source, digest = _source(Path(name))
            records = self._extract(
                source,
                digest,
                page,
                analysis_sink=analyses,
            )

        self.assertIsNotNone(page.seen_word_settings)
        self.assertEqual(
            records[0]["content"]["matrix"],
            [["M", "M+1"], [None, "▲"]],
        )
        self.assertEqual(analyses[0].schedule_rows, ())
        self.assertIn("schedule_label_region_unavailable", analyses[0].reasons)
        self.assertNotIn("pdfplumber.Page.extract_words", analyses[0].provenance)
        self.assertNotIn("pdfplumber.Page.lines", analyses[0].provenance)

    def test_table_and_image_bbox_must_be_inside_page(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            source, digest = _source(Path(name))
            cases = [
                (
                    _FakePage(table=_FakeTable(bbox=(-1, 200, 300, 350))),
                    "pdf_table_bbox_outside_page",
                ),
                (
                    _FakePage(
                        images=[
                            {"x0": 550, "top": 500, "x1": 601, "bottom": 700}
                        ]
                    ),
                    "pdf_image_bbox_outside_page",
                ),
            ]
            for page, expected_error in cases:
                with self.subTest(expected_error=expected_error):
                    with patch(
                        "midprojectrag.ingest.pdf_visual._open_pdf",
                        return_value=_FakePdf([page]),
                    ):
                        with self.assertRaisesRegex(
                            PdfVisualError, f"^{expected_error}$"
                        ):
                            extract_pdf_visual_evidence(
                                source_path=source,
                                doc_id=DOC_ID,
                                expected_sha256=digest,
                            )

    def test_module_import_does_not_import_optional_pdfplumber(self) -> None:
        import midprojectrag.ingest.pdf_visual as module

        self.assertNotIn("pdfplumber", vars(module))
        with patch.dict(sys.modules, {"pdfplumber": None}):
            with self.assertRaisesRegex(PdfVisualError, "^pdfplumber_unavailable$"):
                _open_pdf(io.BytesIO(b"synthetic"))

    def test_schema_is_strict(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            source, digest = _source(Path(name))
            record = self._extract(source, digest, _FakePage())[0]
        invalid = dict(record)
        invalid["unexpected"] = True
        self.assertFalse(Draft202012Validator(self.schema).is_valid(invalid))


if __name__ == "__main__":
    unittest.main()
