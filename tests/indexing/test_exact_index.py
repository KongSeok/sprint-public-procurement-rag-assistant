from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from midprojectrag.ingest.common import canonical_json, sha256_text
from midprojectrag.indexing.exact_index import ExactDenseIndex


def _chunk(
    index: int,
    doc: int,
    *,
    config_sha256: str = "1" * 64,
) -> dict[str, object]:
    text = f"chunk-{index}"
    doc_id = f"doc_{doc:024x}"
    block_id = f"block_{index:024x}"
    content_sha256 = sha256_text(text)
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


class ExactIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.chunks = [_chunk(1, 1), _chunk(2, 2), _chunk(3, 1)]
        self.vectors = np.asarray([[1, 0], [0, 1], [0.8, 0.2]], dtype=np.float32)

    def test_exact_cosine_and_explicit_scope(self) -> None:
        index = ExactDenseIndex(self.chunks, self.vectors, engine="numpy")
        all_hits = index.search([1, 0], top_k=3)
        self.assertEqual([hit.chunk["chunk_id"] for hit in all_hits], [self.chunks[0]["chunk_id"], self.chunks[2]["chunk_id"], self.chunks[1]["chunk_id"]])
        scoped = index.search([1, 0], top_k=3, allowed_doc_ids={self.chunks[1]["doc_id"]})
        self.assertEqual(len(scoped), 1)
        self.assertEqual(scoped[0].chunk["doc_id"], self.chunks[1]["doc_id"])

    def test_numpy_ties_use_stable_row_order(self) -> None:
        tied = np.asarray([[1, 0], [1, 0], [0, 1]], dtype=np.float32)
        index = ExactDenseIndex(self.chunks, tied, engine="numpy")
        hits = index.search([1, 0], top_k=2)
        self.assertEqual(
            [hit.chunk["chunk_id"] for hit in hits],
            [self.chunks[0]["chunk_id"], self.chunks[1]["chunk_id"]],
        )

    def test_one_physical_index_rejects_mixed_chunk_contracts(self) -> None:
        chunks = [
            _chunk(1, 1, config_sha256="1" * 64),
            _chunk(2, 2, config_sha256="2" * 64),
        ]
        with self.assertRaisesRegex(ValueError, "mixed_index_chunk_contracts"):
            ExactDenseIndex(
                chunks,
                np.asarray([[1, 0], [0, 1]], dtype=np.float32),
                engine="numpy",
            )

    def test_numpy_artifact_round_trip_and_hash_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            index = ExactDenseIndex(self.chunks, self.vectors, engine="numpy")
            metadata = index.save(output, corpus_manifest_sha256="2" * 64, embedding_model="fake")
            loaded = ExactDenseIndex.load(output, self.chunks)
            self.assertEqual(metadata["count"], 3)
            self.assertEqual(loaded.search([1, 0], top_k=1)[0].chunk["chunk_id"], self.chunks[0]["chunk_id"])
            tampered = list(self.chunks)
            tampered[0] = dict(tampered[0], text="tampered")
            with self.assertRaisesRegex(ValueError, "index_chunk_artifact_hash_mismatch"):
                ExactDenseIndex.load(output, tampered)

    def test_profiled_index_refuses_cross_config_overwrite_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            index = ExactDenseIndex(self.chunks, self.vectors, engine="numpy")
            index.save(
                output,
                corpus_manifest_sha256="2" * 64,
                embedding_model="text-embedding-3-small",
                api_profile="personal_experimental",
                index_config_sha256="3" * 64,
            )
            ExactDenseIndex.load(
                output,
                self.chunks,
                expected_embedding_model="text-embedding-3-small",
                expected_dimensions=2,
                expected_api_profile="personal_experimental",
                expected_index_config_sha256="3" * 64,
            )
            with self.assertRaisesRegex(ValueError, "index_expected_config_mismatch"):
                ExactDenseIndex.load(
                    output,
                    self.chunks,
                    expected_index_config_sha256="4" * 64,
                )
            with self.assertRaisesRegex(ValueError, "index_output_config_mismatch"):
                index.save(
                    output,
                    corpus_manifest_sha256="2" * 64,
                    embedding_model="text-embedding-3-large",
                    api_profile="personal_experimental",
                    index_config_sha256="4" * 64,
                )


if __name__ == "__main__":
    unittest.main()
