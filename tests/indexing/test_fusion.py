from __future__ import annotations

import unittest
from typing import Any, Sequence

import numpy as np

from midprojectrag.ingest.common import canonical_json, sha256_text
from midprojectrag.indexing.exact_index import ExactDenseIndex, IndexSearchHit
from midprojectrag.indexing.fusion import DualLaneIndex


def _chunk(index: int, doc: int, *, prefix: str) -> dict[str, Any]:
    text = f"{prefix}-chunk-{index}"
    doc_id = f"doc_{doc:024x}"
    block_id = f"block_{sha256_text(f'{prefix}:{index}')[:24]}"
    content_sha256 = sha256_text(text)
    config_sha256 = "1" * 64
    identity = {
        "block_id": block_id,
        "config_sha256": config_sha256,
        "content_sha256": content_sha256,
        "doc_id": doc_id,
        "page_end": index,
        "page_start": index,
        "part_count": 1,
        "part_index": 0,
    }
    return {
        "schema_version": "1.0",
        "chunk_id": f"chunk_{sha256_text(canonical_json(identity))[:24]}",
        "doc_id": doc_id,
        "text": text,
        "source_block_ids": [block_id],
        "section_path": [],
        "page_start": index,
        "page_end": index,
        "part_index": 0,
        "part_count": 1,
        "retrieval_role": "primary",
        "chunker_id": "page-v1",
        "config_sha256": config_sha256,
        "content_sha256": content_sha256,
    }


class _RecordingIndex:
    def __init__(
        self,
        hits: list[IndexSearchHit],
        *,
        dimensions: int = 2,
    ) -> None:
        self.hits = hits
        self.dimensions = dimensions
        self.calls: list[tuple[object, int, set[str] | None]] = []

    def search(
        self,
        query_vector: Sequence[float] | np.ndarray,
        *,
        top_k: int = 10,
        allowed_doc_ids: set[str] | None = None,
    ) -> list[IndexSearchHit]:
        self.calls.append((query_vector, top_k, allowed_doc_ids))
        hits = self.hits
        if allowed_doc_ids is not None:
            hits = [hit for hit in hits if hit.chunk["doc_id"] in allowed_doc_ids]
        return hits[:top_k]


class DualLaneIndexTests(unittest.TestCase):
    def test_independent_exact_searches_use_deterministic_rrf(self) -> None:
        page_chunks = [_chunk(index, index, prefix="page") for index in range(1, 4)]
        table_chunks = [_chunk(index, index + 3, prefix="table") for index in range(1, 4)]
        page_index = ExactDenseIndex(
            page_chunks,
            np.asarray([[1, 0], [0.8, 0.2], [0, 1]], dtype=np.float32),
            engine="numpy",
        )
        table_index = ExactDenseIndex(
            table_chunks,
            np.asarray([[0.99, 0.01], [0.7, 0.3], [0, 1]], dtype=np.float32),
            engine="numpy",
        )
        index = DualLaneIndex(
            page_index,
            table_index,
            rrf_k=60,
            table_retrieval_cap=2,
        )

        hits = index.search(np.asarray([1, 0], dtype=np.float32), top_k=4)

        self.assertEqual([hit.lane for hit in hits], ["page", "table", "page", "table"])
        self.assertEqual([hit.lane_rank for hit in hits], [1, 1, 2, 2])
        self.assertEqual(len([hit for hit in hits if hit.lane == "table"]), 2)
        self.assertAlmostEqual(hits[0].score, 1 / 61)
        self.assertAlmostEqual(hits[1].score, 1 / 61)
        self.assertAlmostEqual(hits[2].score, 1 / 62)
        self.assertAlmostEqual(hits[3].score, 1 / 62)
        self.assertAlmostEqual(hits[0].dense_score, 1.0)
        self.assertGreater(hits[1].dense_score, hits[3].dense_score)

    def test_same_query_and_explicit_scope_are_forwarded_to_both_lanes(self) -> None:
        allowed_page = _chunk(1, 1, prefix="page")
        denied_page = _chunk(2, 2, prefix="page")
        allowed_table = _chunk(1, 1, prefix="table")
        denied_table = _chunk(2, 2, prefix="table")
        page_index = _RecordingIndex(
            [
                IndexSearchHit(0, 0.9, allowed_page),
                IndexSearchHit(1, 0.8, denied_page),
            ]
        )
        table_index = _RecordingIndex(
            [
                IndexSearchHit(0, 0.95, allowed_table),
                IndexSearchHit(1, 0.7, denied_table),
            ]
        )
        index = DualLaneIndex(
            page_index,  # type: ignore[arg-type]
            table_index,  # type: ignore[arg-type]
            table_retrieval_cap=2,
        )
        query = np.asarray([1, 0], dtype=np.float32)
        scope = {allowed_page["doc_id"]}

        hits = index.search(query, top_k=4, allowed_doc_ids=scope)

        self.assertIs(page_index.calls[0][0], query)
        self.assertIs(table_index.calls[0][0], query)
        self.assertEqual(page_index.calls[0][1], 4)
        self.assertEqual(table_index.calls[0][1], 2)
        self.assertIs(page_index.calls[0][2], scope)
        self.assertIs(table_index.calls[0][2], scope)
        self.assertEqual({hit.chunk["doc_id"] for hit in hits}, scope)

    def test_duplicate_chunk_accumulates_both_reciprocal_ranks(self) -> None:
        chunk = _chunk(1, 1, prefix="shared")
        page_index = _RecordingIndex([IndexSearchHit(0, 0.9, chunk)])
        table_index = _RecordingIndex([IndexSearchHit(7, 0.8, chunk)])
        index = DualLaneIndex(
            page_index,  # type: ignore[arg-type]
            table_index,  # type: ignore[arg-type]
        )

        hits = index.search([1, 0], top_k=2)

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].lane, "page")
        self.assertEqual(hits[0].row_id, 0)
        self.assertAlmostEqual(hits[0].score, 2 / 61)

    def test_configuration_and_dimensions_are_validated(self) -> None:
        hit = IndexSearchHit(0, 1.0, _chunk(1, 1, prefix="page"))
        two_dimensions = _RecordingIndex([hit], dimensions=2)
        three_dimensions = _RecordingIndex([hit], dimensions=3)
        with self.assertRaisesRegex(ValueError, "dual_lane_dimension_mismatch"):
            DualLaneIndex(
                two_dimensions,  # type: ignore[arg-type]
                three_dimensions,  # type: ignore[arg-type]
            )
        with self.assertRaisesRegex(ValueError, "invalid_rrf_k"):
            DualLaneIndex(
                two_dimensions,  # type: ignore[arg-type]
                two_dimensions,  # type: ignore[arg-type]
                rrf_k=0,
            )
        with self.assertRaisesRegex(ValueError, "invalid_table_retrieval_cap"):
            DualLaneIndex(
                two_dimensions,  # type: ignore[arg-type]
                two_dimensions,  # type: ignore[arg-type]
                table_retrieval_cap=0,
            )
        index = DualLaneIndex(
            two_dimensions,  # type: ignore[arg-type]
            two_dimensions,  # type: ignore[arg-type]
        )
        with self.assertRaisesRegex(ValueError, "invalid_top_k"):
            index.search([1, 0], top_k=0)


if __name__ == "__main__":
    unittest.main()
