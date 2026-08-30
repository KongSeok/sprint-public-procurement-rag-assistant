from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from midprojectrag.ingest.common import canonical_json, sha256_text, write_jsonl
from midprojectrag.indexing.chunking import (
    TableChunkConfig,
    build_table_chunks,
    build_table_chunks_from_manifest,
    validate_chunk,
)


DOC_ID = "doc_0123456789abcdef01234567"
BLOCK_ID = "block_0123456789abcdef01234567"


class _Counter:
    def count(self, text: str) -> int:
        return len(text)


def _table_block(*, rows: int = 4, cells=None, structure=None) -> dict[str, object]:
    if structure is None:
        if cells is None:
            cells = [
                {
                    "row": 0,
                    "col": 0,
                    "row_span": rows,
                    "col_span": 3,
                    "is_header": False,
                    "text": "기본 표 내용",
                }
            ]
        structure = {
            "index": 7,
            "section": 1,
            "paragraph": 42,
            "control": 3,
            "rows": rows,
            "cols": 3,
            "cell_count": len(cells),
            "cells": cells,
        }
    text = "table-searchable-text"
    return {
        "schema_version": "1.0",
        "block_id": BLOCK_ID,
        "doc_id": DOC_ID,
        "sequence": 100,
        "block_type": "table",
        "section_path": [],
        "page_start": None,
        "page_end": None,
        "bbox": None,
        "text": text,
        "content_sha256": sha256_text(text),
        "structure_sha256": sha256_text(canonical_json(structure)),
        "table_structure": structure,
        "extractor": "rhwp",
        "extractor_version": "0.8.4+adapter-v1",
        "source_locator": "section:1/paragraph:42/table:7",
        "retrieval_role": "structured_auxiliary",
    }


def _context() -> dict[str, dict[str, str]]:
    return {
        DOC_ID: {
            "project_name": "테스트 사업",
            "ordering_agency": "테스트 기관",
            "project_summary": "표 구조 검색을 검증하는 사업",
        }
    }


class TableChunkingTests(unittest.TestCase):
    def test_verified_layout_links_only_top_level_table_chunks(self) -> None:
        nested = {
            "index": 0,
            "section": 1,
            "paragraph": 42,
            "rows": 2,
            "cols": 1,
            "cell_count": 2,
            "cells": [
                {"row": 0, "col": 0, "row_span": 1, "col_span": 1, "is_header": True, "text": "항목"},
                {"row": 1, "col": 0, "row_span": 1, "col_span": 1, "is_header": False, "text": "값"},
            ],
        }
        structure = {
            "index": 7,
            "section": 1,
            "paragraph": 42,
            "control": 3,
            "rows": 2,
            "cols": 1,
            "cell_count": 2,
            "cells": [
                {"row": 0, "col": 0, "row_span": 1, "col_span": 1, "is_header": True, "text": "구분"},
                {"row": 1, "col": 0, "row_span": 1, "col_span": 1, "is_header": False, "text": "부모", "nested": [nested]},
            ],
        }
        block = _table_block(structure=structure)
        block["page_start"] = 7
        block["page_end"] = 7
        layout = [
            {
                "schema_version": "1.0",
                "doc_id": DOC_ID,
                "block_id": BLOCK_ID,
                "structure_sha256": block["structure_sha256"],
                "status": "verified_render",
                "page_start": 4,
                "page_end": 5,
            }
        ]

        chunks = build_table_chunks(
            [block],
            _context(),
            counter=_Counter(),
            layout_records=layout,
        )

        parent = next(chunk for chunk in chunks if "/nested:" not in chunk["source_locator"])
        child = next(chunk for chunk in chunks if "/nested:" in chunk["source_locator"])
        self.assertEqual((parent["page_start"], parent["page_end"]), (4, 5))
        self.assertIsNone(child["page_start"])
        self.assertIsNone(child["page_end"])

    def test_layout_must_cover_the_exact_table_block_set(self) -> None:
        with self.assertRaisesRegex(ValueError, "table_layout_block_set_mismatch"):
            build_table_chunks(
                [_table_block()],
                _context(),
                counter=_Counter(),
                layout_records=[],
            )

    def test_merged_cells_are_expanded_and_markdown_is_escaped_deterministically(self) -> None:
        cells = [
            {"row": 0, "col": 0, "row_span": 2, "col_span": 1, "is_header": True, "text": "구분"},
            {"row": 0, "col": 1, "row_span": 1, "col_span": 2, "is_header": True, "text": "산출물"},
            {"row": 1, "col": 1, "row_span": 1, "col_span": 1, "is_header": True, "text": "목록"},
            {"row": 1, "col": 2, "row_span": 1, "col_span": 1, "is_header": True, "text": "점검"},
            {"row": 2, "col": 0, "row_span": 2, "col_span": 1, "is_header": False, "text": "연계 데이터"},
            {"row": 2, "col": 1, "row_span": 1, "col_span": 1, "is_header": False, "text": "목록 | 정의서 & 확인"},
            {"row": 2, "col": 2, "row_span": 1, "col_span": 1, "is_header": False, "text": "점검\n내역서"},
            {"row": 3, "col": 1, "row_span": 1, "col_span": 1, "is_header": False, "text": "두 번째 목록"},
            {"row": 3, "col": 2, "row_span": 1, "col_span": 1, "is_header": False, "text": "두 번째 점검"},
        ]
        block = _table_block(cells=cells)

        forward = build_table_chunks([block], _context(), counter=_Counter())
        reverse = build_table_chunks([dict(block)], _context(), counter=_Counter())

        self.assertEqual(forward, reverse)
        self.assertEqual(len(forward), 1)
        chunk = forward[0]
        self.assertEqual(chunk["header_source"], "explicit")
        self.assertIn("| 구분 | 산출물 &gt; 목록 | 산출물 &gt; 점검 |", chunk["display_markdown"])
        self.assertEqual(chunk["display_markdown"].count("| 연계 데이터 |"), 2)
        self.assertIn(r"목록 \| 정의서", chunk["display_markdown"])
        self.assertIn("&amp; 확인", chunk["display_markdown"])
        self.assertIn("점검<br>내역서", chunk["display_markdown"])
        self.assertIn("[사업명] 테스트 사업", chunk["text"])
        self.assertIn("[표 위치] section:1/paragraph:42/table:7", chunk["text"])
        self.assertIsNone(chunk["page_start"])
        validate_chunk(chunk)

    def test_large_table_splits_into_row_groups_and_repeats_header(self) -> None:
        cells = [
            {"row": 0, "col": 0, "row_span": 1, "col_span": 1, "is_header": True, "text": "항목"},
            {"row": 0, "col": 1, "row_span": 1, "col_span": 1, "is_header": True, "text": "값"},
        ]
        for row in range(1, 11):
            cells.extend(
                [
                    {"row": row, "col": 0, "row_span": 1, "col_span": 1, "is_header": False, "text": f"항목-{row}"},
                    {"row": row, "col": 1, "row_span": 1, "col_span": 1, "is_header": False, "text": f"값-{row}"},
                ]
            )
        structure = {
            "index": 0,
            "section": 0,
            "paragraph": 0,
            "rows": 11,
            "cols": 2,
            "cell_count": len(cells),
            "cells": cells,
        }
        chunks = build_table_chunks(
            [_table_block(structure=structure)],
            _context(),
            config=TableChunkConfig(max_rows=4, max_chars=2400, max_tokens=600),
            counter=_Counter(),
        )

        self.assertEqual(len(chunks), 3)
        self.assertEqual([(c["row_start"], c["row_end"]) for c in chunks], [(1, 4), (5, 8), (9, 10)])
        self.assertTrue(all("| 항목 | 값 |" in c["display_markdown"] for c in chunks))
        self.assertEqual([c["part_index"] for c in chunks], [0, 1, 2])
        self.assertTrue(all(c["part_count"] == 3 for c in chunks))

    def test_no_header_flag_uses_generic_columns_without_dropping_first_row(self) -> None:
        cells = [
            {"row": 0, "col": 0, "row_span": 1, "col_span": 1, "is_header": False, "text": "100"},
            {"row": 0, "col": 1, "row_span": 1, "col_span": 1, "is_header": False, "text": "200"},
            {"row": 1, "col": 0, "row_span": 1, "col_span": 1, "is_header": False, "text": "300"},
            {"row": 1, "col": 1, "row_span": 1, "col_span": 1, "is_header": False, "text": "400"},
        ]
        structure = {
            "index": 0,
            "section": 0,
            "paragraph": 0,
            "rows": 2,
            "cols": 2,
            "cell_count": len(cells),
            "cells": cells,
        }
        chunk = build_table_chunks([_table_block(structure=structure)], _context(), counter=_Counter())[0]
        self.assertEqual(chunk["header_source"], "generic")
        self.assertEqual(chunk["row_start"], 0)
        self.assertIn("| 열1 | 열2 |", chunk["display_markdown"])
        self.assertIn("| 100 | 200 |", chunk["display_markdown"])

    def test_partial_explicit_header_does_not_drop_the_first_row(self) -> None:
        cells = [
            {"row": 0, "col": 0, "row_span": 1, "col_span": 1, "is_header": True, "text": "구분"},
            {"row": 0, "col": 1, "row_span": 1, "col_span": 1, "is_header": False, "text": "실제 값"},
            {"row": 1, "col": 0, "row_span": 1, "col_span": 1, "is_header": False, "text": "A"},
            {"row": 1, "col": 1, "row_span": 1, "col_span": 1, "is_header": False, "text": "10"},
        ]
        structure = {
            "index": 0,
            "section": 0,
            "paragraph": 0,
            "rows": 2,
            "cols": 2,
            "cell_count": len(cells),
            "cells": cells,
        }

        chunk = build_table_chunks(
            [_table_block(structure=structure)], _context(), counter=_Counter()
        )[0]

        self.assertEqual(chunk["header_source"], "generic")
        self.assertEqual(chunk["row_start"], 0)
        self.assertIn("| 구분 | 실제 값 |", chunk["display_markdown"])

    def test_nonbody_header_footer_tables_are_not_indexed(self) -> None:
        repeated = _table_block()
        repeated["block_id"] = "block_aaaaaaaaaaaaaaaaaaaaaaaa"
        repeated_structure = dict(repeated["table_structure"])
        repeated_structure["container_path"] = [
            {"kind": "header", "paragraph": 0, "control": 0}
        ]
        repeated["table_structure"] = repeated_structure
        repeated["structure_sha256"] = sha256_text(canonical_json(repeated_structure))

        chunks = build_table_chunks(
            [repeated, _table_block()], _context(), counter=_Counter()
        )

        self.assertEqual({chunk["source_block_ids"][0] for chunk in chunks}, {BLOCK_ID})

    def test_table_chunk_matches_shared_json_schema(self) -> None:
        chunk = build_table_chunks(
            [_table_block()], _context(), counter=_Counter()
        )[0]
        schema_path = Path(__file__).resolve().parents[2] / "contracts" / "chunk.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        errors = list(Draft202012Validator(schema).iter_errors(chunk))

        self.assertEqual(errors, [])

    def test_nested_table_becomes_a_searchable_sibling_with_stable_locator(self) -> None:
        nested = {
            "index": 0,
            "section": 1,
            "paragraph": 42,
            "rows": 2,
            "cols": 2,
            "cell_count": 4,
            "cells": [
                {"row": 0, "col": 0, "row_span": 1, "col_span": 1, "is_header": True, "text": "등급"},
                {"row": 0, "col": 1, "row_span": 1, "col_span": 1, "is_header": True, "text": "점수"},
                {"row": 1, "col": 0, "row_span": 1, "col_span": 1, "is_header": False, "text": "A"},
                {"row": 1, "col": 1, "row_span": 1, "col_span": 1, "is_header": False, "text": "10"},
            ],
        }
        structure = {
            "index": 7,
            "section": 1,
            "paragraph": 42,
            "rows": 1,
            "cols": 1,
            "cell_count": 1,
            "cells": [
                {
                    "row": 0,
                    "col": 0,
                    "row_span": 1,
                    "col_span": 1,
                    "is_header": False,
                    "text": "평가 기준",
                    "nested": [nested],
                }
            ],
        }
        chunks = build_table_chunks(
            [_table_block(structure=structure)], _context(), counter=_Counter()
        )
        self.assertEqual(len(chunks), 2)
        child = next(chunk for chunk in chunks if "/nested:1" in chunk["source_locator"])
        self.assertIn("/cell:0,0/nested:1", child["source_locator"])
        self.assertIn("[상위 셀] 평가 기준", child["text"])
        self.assertIn("| A | 10 |", child["display_markdown"])

    def test_single_row_over_token_budget_uses_lossless_vertical_segments(self) -> None:
        cells = [
            {"row": 0, "col": 0, "row_span": 1, "col_span": 1, "is_header": False, "text": "가" * 700}
        ]
        structure = {
            "index": 0,
            "section": 0,
            "paragraph": 0,
            "rows": 1,
            "cols": 1,
            "cell_count": 1,
            "cells": cells,
        }
        chunks = build_table_chunks(
            [_table_block(structure=structure)],
            _context(),
            config=TableChunkConfig(max_rows=8, max_chars=2000, max_tokens=600),
            counter=_Counter(),
        )
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all("| 열 | 값 |" in chunk["display_markdown"] for chunk in chunks))
        self.assertEqual(sum(chunk["display_markdown"].count("가") for chunk in chunks), 700)
        self.assertTrue(all(len(chunk["text"]) <= 2000 for chunk in chunks))
        self.assertTrue(all(_Counter().count(chunk["text"]) <= 600 for chunk in chunks))

    def test_manifest_builder_allows_table_document_subset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blocks_dir = root / "blocks"
            blocks_dir.mkdir()
            second_doc = "doc_1123456789abcdef01234567"
            manifest = [
                {
                    "doc_id": DOC_ID,
                    "status": "ok",
                    "index_eligible": True,
                    "metadata": {
                        "project_name": "테스트 사업",
                        "ordering_agency": "테스트 기관",
                        "project_summary": "요약",
                    },
                },
                {
                    "doc_id": second_doc,
                    "status": "ok",
                    "index_eligible": True,
                    "metadata": {
                        "project_name": "PDF 사업",
                        "ordering_agency": "PDF 기관",
                        "project_summary": "표 블록 없음",
                    },
                },
            ]
            manifest_path = root / "manifest.jsonl"
            write_jsonl(manifest_path, manifest)
            write_jsonl(blocks_dir / f"{DOC_ID}.jsonl", [_table_block()])
            write_jsonl(
                blocks_dir / f"{second_doc}.jsonl",
                [
                    {
                        "schema_version": "1.0",
                        "block_id": "block_1123456789abcdef01234567",
                        "doc_id": second_doc,
                        "sequence": 0,
                        "block_type": "page_text",
                        "section_path": [],
                        "page_start": 1,
                        "page_end": 1,
                        "bbox": None,
                        "text": "본문",
                        "content_sha256": sha256_text("본문"),
                        "extractor": "pypdf",
                        "extractor_version": "1",
                        "source_locator": "page:1",
                        "retrieval_role": "primary",
                    }
                ],
            )

            chunks = build_table_chunks_from_manifest(
                manifest_path,
                blocks_dir,
                counter=_Counter(),
            )

            self.assertEqual({chunk["doc_id"] for chunk in chunks}, {DOC_ID})


if __name__ == "__main__":
    unittest.main()
