from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np
from jsonschema import Draft202012Validator

from midprojectrag.ingest.common import canonical_json, sha256_text
from midprojectrag.indexing.chunking import TableChunkConfig, build_table_chunks
from midprojectrag.indexing.exact_index import ExactDenseIndex
from midprojectrag.indexing.visual_table_context import (
    enrich_table_chunks_with_visual_context,
)


DOC_ID = "doc_0123456789abcdef01234567"
BLOCK_ID = "block_0123456789abcdef01234567"


class _Counter:
    def count(self, text: str) -> int:
        return len(text)


def _source() -> tuple[dict[str, object], dict[str, dict[str, str]]]:
    cells = [
        {"row": 0, "col": 0, "row_span": 1, "col_span": 1, "is_header": True, "text": "업무"},
        {"row": 0, "col": 1, "row_span": 1, "col_span": 1, "is_header": True, "text": "기간"},
        {"row": 1, "col": 0, "row_span": 1, "col_span": 1, "is_header": False, "text": "분석"},
        {"row": 1, "col": 1, "row_span": 1, "col_span": 1, "is_header": False, "text": ""},
        {"row": 2, "col": 0, "row_span": 1, "col_span": 1, "is_header": False, "text": "개편"},
        {"row": 2, "col": 1, "row_span": 1, "col_span": 1, "is_header": False, "text": ""},
    ]
    structure = {
        "index": 0,
        "section": 0,
        "paragraph": 1,
        "control": 0,
        "rows": 3,
        "cols": 2,
        "cell_count": len(cells),
        "cells": cells,
    }
    text = "synthetic table"
    block = {
        "schema_version": "1.0",
        "block_id": BLOCK_ID,
        "doc_id": DOC_ID,
        "sequence": 1,
        "block_type": "table",
        "section_path": [],
        "page_start": 7,
        "page_end": 7,
        "bbox": None,
        "text": text,
        "content_sha256": sha256_text(text),
        "structure_sha256": sha256_text(canonical_json(structure)),
        "table_structure": structure,
        "extractor": "rhwp",
        "extractor_version": "0.8.4+adapter-v1",
        "source_locator": "section:0/paragraph:1/table:0",
        "retrieval_role": "structured_auxiliary",
    }
    context = {
        DOC_ID: {
            "project_name": "테스트 사업",
            "ordering_agency": "테스트 기관",
            "project_summary": "검색 컨텍스트 검증",
        }
    }
    return block, context


def _overlay(structure_sha256: str) -> dict[str, object]:
    bbox = {"x": 10.0, "y": 20.0, "w": 30.0, "h": 40.0}
    return {
        "schema_version": "1.0",
        "doc_id": DOC_ID,
        "block_id": BLOCK_ID,
        "structure_sha256": structure_sha256,
        "status": "verified_render",
        "page_start": 7,
        "page_end": 7,
        "coordinate_space": "rhwp_css_px_96dpi",
        "render_key": {"section": 0, "paragraph": 1, "control": 0},
        "page_contexts": [
            {
                "page": 7,
                "sequence_in_page": 4,
                "bbox": bbox,
                "preceding_text": {
                    "text": "샘플 일정",
                    "bbox": bbox,
                    "render_key": {"section": 0, "paragraph": 0},
                    "method": "nearest_prior_top_level_textline",
                },
            }
        ],
        "background_cells": [],
        "schedule_facts": [
            {
                "row": 2,
                "label": "개편",
                "periods": ["M+2", "M+3", "M+4"],
                "text": "작업 B: M+2~M+4",
                "evidence_cells": [
                    {"page": 7, "row": 2, "col": 1, "bbox": bbox, "period": "M+2"}
                ],
            }
        ],
    }


class VisualTableContextTests(unittest.TestCase):
    def _chunks(self) -> tuple[list[dict[str, object]], dict[str, object]]:
        block, context = _source()
        chunks = build_table_chunks(
            [block],
            context,
            counter=_Counter(),
            config=TableChunkConfig(max_rows=1, max_chars=2_400, max_tokens=600),
        )
        return chunks, _overlay(str(block["structure_sha256"]))

    def test_enriches_only_the_matching_row_and_is_deterministic(self) -> None:
        chunks, overlay = self._chunks()
        first = enrich_table_chunks_with_visual_context(chunks, [overlay])
        second = enrich_table_chunks_with_visual_context(chunks, [overlay])

        self.assertEqual(first, second)
        self.assertTrue(all(chunk["schema_version"] == "1.2" for chunk in first))
        self.assertTrue(all("[인접 문맥] 샘플 일정" in chunk["text"] for chunk in first))
        matching = [chunk for chunk in first if chunk["row_start"] == 2]
        nonmatching = [chunk for chunk in first if chunk["row_start"] != 2]
        self.assertEqual(len(matching), 1)
        self.assertIn("[시각 일정] 작업 B: M+2~M+4", matching[0]["text"])
        self.assertTrue(all("[시각 일정]" not in chunk["text"] for chunk in nonmatching))
        self.assertTrue(all(chunk["display_markdown"] == old["display_markdown"] for chunk, old in zip(first, chunks, strict=True)))

    def test_output_matches_schema_and_exact_index_consumer(self) -> None:
        chunks, overlay = self._chunks()
        enriched = enrich_table_chunks_with_visual_context(chunks, [overlay])
        schema = json.loads(
            (Path(__file__).resolve().parents[2] / "contracts" / "chunk.schema.json").read_text(encoding="utf-8")
        )
        for chunk in enriched:
            self.assertEqual(list(Draft202012Validator(schema).iter_errors(chunk)), [])
        vectors = np.eye(len(enriched), dtype=np.float32)
        index = ExactDenseIndex(enriched, vectors, engine="numpy")
        self.assertEqual(len(index.search(vectors[0], top_k=1)), 1)

    def test_rejects_duplicate_mismatch_and_budget_overflow(self) -> None:
        chunks, overlay = self._chunks()
        with self.assertRaisesRegex(ValueError, "visual_overlay_record_invalid"):
            enrich_table_chunks_with_visual_context(chunks, [overlay, overlay])
        mismatch = dict(overlay)
        mismatch["structure_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "visual_overlay_source_mismatch"):
            enrich_table_chunks_with_visual_context(chunks, [mismatch])
        with self.assertRaisesRegex(ValueError, "visual_context_budget_exceeded"):
            enrich_table_chunks_with_visual_context(chunks, [overlay], max_visual_chars=5)


if __name__ == "__main__":
    unittest.main()
