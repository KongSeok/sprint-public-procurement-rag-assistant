from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from jsonschema import Draft202012Validator

from midprojectrag.ingest.common import canonical_json, sha256_text
from midprojectrag.ingest.visual_understanding import VisualRetrievalPolicy
from midprojectrag.indexing.exact_index import IndexSearchHit
from midprojectrag.indexing.visual_fusion import (
    VisualAugmentedIndex,
    VisualExactDenseIndex,
    validate_visual_chunk,
)


def _visual_chunk(
    index: int,
    doc: int,
    *,
    evidence_type: str = "ocr",
    weight: float = 1.0,
    answer_support: dict[str, Any] | None = None,
) -> dict[str, Any]:
    doc_id = f"doc_{doc:024x}"
    occurrence_id = f"vocc2_{index:024x}"
    evidence_prefix = "cap" if evidence_type == "caption" else "ocr"
    evidence_ids = [f"{evidence_prefix}_{index:024x}"]
    text = f"visual-{evidence_type}-{index}"
    content_sha256 = sha256_text(text)
    chunker_id = {
        "ocr": "image-ocr-v1",
        "layout": "image-layout-v1",
        "caption": "image-caption-v1",
    }[evidence_type]
    identity = {
        "doc_id": doc_id,
        "occurrence_id": occurrence_id,
        "evidence_ids": evidence_ids,
        "content_sha256": content_sha256,
        "evidence_type": evidence_type,
        "chunker_id": chunker_id,
    }
    if answer_support is not None:
        identity["answer_support"] = answer_support
    bbox = {"x": 10.0, "y": 20.0, "w": 30.0, "h": 40.0}
    crop_sha256 = f"{index:064x}"
    chunk = {
        "schema_version": "1.0",
        "chunk_id": "vchunk_" + sha256_text(canonical_json(identity))[:24],
        "doc_id": doc_id,
        "occurrence_id": occurrence_id,
        "evidence_ids": evidence_ids,
        "text": text,
        "evidence_type": evidence_type,
        "page": index,
        "bbox": bbox,
        "crop_sha256": crop_sha256,
        "retrieval_role": "visual_auxiliary",
        "chunker_id": chunker_id,
        "retrieval_weight": weight,
        "citation": {
            "doc_id": doc_id,
            "page": index,
            "bbox": bbox,
            "occurrence_id": occurrence_id,
            "crop_sha256": crop_sha256,
            "evidence_ids": evidence_ids,
        },
        "content_sha256": content_sha256,
    }
    if answer_support is not None:
        chunk["answer_support"] = answer_support
    return chunk


class _BaseIndex:
    dimensions = 2

    def __init__(self, hits: list[IndexSearchHit]) -> None:
        self.hits = hits

    def search(
        self,
        query_vector: Sequence[float] | np.ndarray,
        *,
        top_k: int = 10,
        allowed_doc_ids: set[str] | None = None,
    ) -> list[IndexSearchHit]:
        del query_vector
        hits = self.hits
        if allowed_doc_ids is not None:
            hits = [hit for hit in hits if hit.chunk["doc_id"] in allowed_doc_ids]
        return hits[:top_k]


class VisualFusionTests(unittest.TestCase):
    def test_visual_contract_rejects_mutated_citation_and_caption_weight(self) -> None:
        chunk = _visual_chunk(1, 1)
        validate_visual_chunk(chunk)

        mutated = dict(chunk)
        mutated["citation"] = {**chunk["citation"], "page": 2}
        with self.assertRaisesRegex(ValueError, "visual_chunk_citation_mismatch"):
            validate_visual_chunk(mutated)

        caption = _visual_chunk(2, 1, evidence_type="caption", weight=0.36)
        with self.assertRaisesRegex(ValueError, "visual_caption_weight_exceeded"):
            validate_visual_chunk(caption)

    def test_visual_contract_enforces_evidence_prefix_by_type(self) -> None:
        schema = json.loads(
            (Path(__file__).parents[2] / "contracts" / "visual-chunk-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        schema_validator = Draft202012Validator(schema)
        caption = _visual_chunk(3, 1, evidence_type="caption", weight=0.35)
        caption["evidence_ids"] = ["ocr_" + "3" * 24]
        caption["citation"] = {
            **caption["citation"],
            "evidence_ids": list(caption["evidence_ids"]),
        }
        with self.assertRaisesRegex(ValueError, "invalid_visual_chunk_evidence_ids"):
            validate_visual_chunk(caption)
        self.assertTrue(list(schema_validator.iter_errors(caption)))

        ocr = _visual_chunk(4, 1)
        ocr["evidence_ids"] = ["cap_" + "4" * 24]
        ocr["citation"] = {
            **ocr["citation"],
            "evidence_ids": list(ocr["evidence_ids"]),
        }
        with self.assertRaisesRegex(ValueError, "invalid_visual_chunk_evidence_ids"):
            validate_visual_chunk(ocr)
        self.assertTrue(list(schema_validator.iter_errors(ocr)))

    def test_exact_visual_search_is_scoped_and_stable(self) -> None:
        chunks = [_visual_chunk(1, 1), _visual_chunk(2, 2)]
        index = VisualExactDenseIndex(
            chunks,
            np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        )

        hits = index.search(
            [1.0, 0.0],
            top_k=2,
            allowed_doc_ids={chunks[1]["doc_id"]},
        )

        self.assertEqual([hit.chunk["doc_id"] for hit in hits], [chunks[1]["doc_id"]])

    def test_augmented_rrf_caps_caption_and_keeps_it_below_base(self) -> None:
        base_chunks = [
            {"chunk_id": "chunk_" + f"{index:024x}", "doc_id": f"doc_{index:024x}"}
            for index in (1, 2)
        ]
        base = _BaseIndex(
            [
                IndexSearchHit(row_id=index, score=1.0 - index / 10, chunk=chunk)
                for index, chunk in enumerate(base_chunks)
            ]
        )
        visual_chunks = [
            _visual_chunk(3, 3, evidence_type="caption", weight=0.35),
            _visual_chunk(4, 3, evidence_type="caption", weight=0.35),
            _visual_chunk(5, 4, evidence_type="caption", weight=0.35),
            _visual_chunk(6, 5, evidence_type="ocr", weight=1.0),
        ]
        visual = VisualExactDenseIndex(
            visual_chunks,
            np.asarray(
                [[1.0, 0.0], [0.99, 0.01], [0.98, 0.02], [0.97, 0.03]],
                dtype=np.float32,
            ),
        )
        fused = VisualAugmentedIndex(
            base,
            visual,
            visual_retrieval_cap=4,
            policy=VisualRetrievalPolicy(caption_per_query=2, caption_per_document=1),
        )

        hits = fused.search([1.0, 0.0], top_k=6)

        captions = [hit for hit in hits if hit.chunk.get("evidence_type") == "caption"]
        self.assertEqual(len(captions), 2)
        self.assertEqual(len({hit.chunk["doc_id"] for hit in captions}), 2)
        lowest_base = min(hit.score for hit in hits if hit.lane != "visual")
        self.assertTrue(all(hit.score < lowest_base for hit in captions))
        ocr_rank = next(
            index for index, hit in enumerate(hits) if hit.chunk.get("evidence_type") == "ocr"
        )
        self.assertTrue(all(ocr_rank < hits.index(hit) for hit in captions))

    def test_full_base_top_k_reserves_visual_quota_and_overfetches_past_filtered_captions(self) -> None:
        base_chunks = [
            {"chunk_id": "chunk_" + f"{index:024x}", "doc_id": f"doc_{index:024x}"}
            for index in (10, 11, 12)
        ]
        base = _BaseIndex(
            [
                IndexSearchHit(row_id=index, score=1.0 - index / 10, chunk=chunk)
                for index, chunk in enumerate(base_chunks)
            ]
        )
        visual_chunks = [
            _visual_chunk(20, 20, evidence_type="caption", weight=0.35),
            _visual_chunk(21, 20, evidence_type="caption", weight=0.35),
            _visual_chunk(22, 20, evidence_type="caption", weight=0.35),
            _visual_chunk(23, 23, evidence_type="ocr", weight=1.0),
        ]
        visual = VisualExactDenseIndex(
            visual_chunks,
            np.asarray(
                [[1.0, 0.0], [0.999, 0.001], [0.998, 0.002], [0.997, 0.003]],
                dtype=np.float32,
            ),
        )
        fused = VisualAugmentedIndex(
            base,
            visual,
            visual_retrieval_cap=2,
            policy=VisualRetrievalPolicy(caption_per_query=1, caption_per_document=1),
        )

        hits = fused.search([1.0, 0.0], top_k=3)

        self.assertEqual(len(hits), 3)
        self.assertEqual(sum(hit.lane != "visual" for hit in hits), 1)
        self.assertEqual(
            [hit.chunk.get("evidence_type") for hit in hits if hit.lane == "visual"],
            ["ocr", "caption"],
        )
        caption = next(hit for hit in hits if hit.chunk.get("evidence_type") == "caption")
        self.assertEqual(hits[-1], caption)
        self.assertLess(caption.score, min(hit.score for hit in hits[:-1]))

    def test_dimension_mismatch_is_rejected(self) -> None:
        visual = VisualExactDenseIndex(
            [_visual_chunk(1, 1)], np.asarray([[1.0, 0.0, 0.0]], dtype=np.float32)
        )
        with self.assertRaisesRegex(ValueError, "visual_lane_dimension_mismatch"):
            VisualAugmentedIndex(_BaseIndex([]), visual)


if __name__ == "__main__":
    unittest.main()
