"""Synthetic-only persistence/provenance tests; never load private corpus or models."""
import base64
import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from midprojectrag.indexing.embeddings import EmbeddingBatch
from midprojectrag.indexing import visual_ocr_index as subject
from midprojectrag.ingest.common import canonical_json, sha256_file
from tests.indexing.test_visual_fusion import _visual_chunk


class FakeProvider:
    model = subject.KURE_MODEL_ID
    revision = subject.KURE_MODEL_REVISION
    dimensions = subject.KURE_DIMENSIONS
    prompt = ""

    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        vectors = np.zeros((len(texts), self.dimensions), dtype=np.float32)
        vectors[:, 0] = 1
        return EmbeddingBatch(vectors, len(texts))


class VisualOCRIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "crops").mkdir()
        # A transparent synthetic 1x1 PNG, not corpus-derived.
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")
        temporary = self.root / "pixel.png"
        temporary.write_bytes(png)
        digest = sha256_file(temporary)
        self.crop = self.root / "crops" / (digest + ".png")
        temporary.rename(self.crop)
        self.chunks = [_visual_chunk(1, 1), _visual_chunk(1, 1, evidence_type="layout", weight=0.8)]
        for c in self.chunks:
            c["crop_sha256"] = c["citation"]["crop_sha256"] = digest
        c = self.chunks[0]
        self.occurrences = [{**{k: copy.deepcopy(c[k]) for k in
                             ("doc_id", "occurrence_id", "page", "bbox", "crop_sha256")},
                            "placement_status": "page_bbox_verified", "retrieval_status": "eligible",
                            "crop_relpath": "crops/" + self.crop.name, "crop_media_type": "image/png",
                            "coordinate_space": "synthetic_pixels"}]
        self.chunks_path = self.root / "input-chunks.jsonl"
        self.occurrences_path = self.root / "input-occurrences.jsonl"
        self.write_inputs()
        self.provider = FakeProvider()
        self.common = dict(index_dir=self.root / "index", private_root=self.root, crop_root=self.root)

    def write_inputs(self):
        for path, rows in ((self.chunks_path, self.chunks), (self.occurrences_path, self.occurrences)):
            path.write_text("".join(canonical_json(r)+"\n" for r in rows), encoding="utf-8")

    def build(self):
        return subject.build(chunks_path=self.chunks_path, occurrences_path=self.occurrences_path,
                             provider=self.provider, **self.common)

    def test_roundtrip_deduplicates_occurrence_and_keeps_provenance(self):
        before = [sha256_file(p) for p in (self.chunks_path, self.occurrences_path, self.crop)]
        receipt = self.build()
        index, _, _ = subject.load(**self.common)
        self.assertEqual(index.vectors.shape, (2, 1024))
        self.assertEqual(receipt["occurrence_count"], 1)
        result = subject.search(provider=FakeProvider(), query="synthetic query", **self.common)
        self.assertEqual(len(result["hits"]), 1)
        self.assertEqual(result["hits"][0]["crop_path"], str(self.crop))
        self.assertEqual(result["hits"][0]["citation"], self.chunks[0]["citation"])
        self.assertEqual(before, [sha256_file(p) for p in (self.chunks_path, self.occurrences_path, self.crop)])
        for name in ("chunks.jsonl", "occurrences.jsonl", "vectors.npy", "metadata.json"):
            self.assertEqual((self.root / "index" / name).stat().st_mode & 0o777, 0o600)

    def test_occurrence_mismatch_rejected_before_embedding(self):
        self.occurrences[0]["page"] = 2
        self.write_inputs()
        with self.assertRaisesRegex(ValueError, "chunk_occurrence_mismatch"):
            self.build()
        self.assertEqual(self.provider.calls, 0)

    def test_changed_crop_rejected_before_embedding(self):
        self.crop.write_bytes(self.crop.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "visual_crop_checksum_mismatch"):
            self.build()
        self.assertEqual(self.provider.calls, 0)

    def test_caption_rejected(self):
        self.chunks = [_visual_chunk(1, 1, evidence_type="caption", weight=0.35)]
        self.chunks[0]["crop_sha256"] = self.chunks[0]["citation"]["crop_sha256"] = sha256_file(self.crop)
        self.write_inputs()
        with self.assertRaisesRegex(ValueError, "caption_not_enabled"):
            self.build()

    def test_duplicate_chunk_and_occurrence_rejected(self):
        self.chunks.append(copy.deepcopy(self.chunks[0]))
        self.write_inputs()
        with self.assertRaisesRegex(ValueError, "duplicate_visual_chunk_id"):
            self.build()
        self.chunks.pop()
        self.occurrences.append(copy.deepcopy(self.occurrences[0]))
        self.write_inputs()
        with self.assertRaisesRegex(ValueError, "duplicate_occurrence"):
            self.build()

    def test_tampered_vectors_rejected(self):
        self.build()
        path = self.root / "index" / "vectors.npy"
        path.write_bytes(path.read_bytes() + b"tampered")
        with self.assertRaisesRegex(ValueError, "index_file_checksum_mismatch"):
            subject.load(**self.common)

    def test_model_identity_rejected(self):
        self.provider.revision = "other"
        with self.assertRaisesRegex(ValueError, "visual_embedding_identity_mismatch"):
            self.build()

    def test_reload_model_identity_rejected(self):
        self.build()
        path = self.root / "index" / "metadata.json"
        metadata = json.loads(path.read_text())
        metadata["embedding"]["revision"] = "other"
        path.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, "index_identity_mismatch"):
            subject.load(**self.common)

    def test_no_overwrite(self):
        self.build()
        with self.assertRaisesRegex(ValueError, "index_already_exists"):
            self.build()
        self.assertEqual(self.provider.calls, 1)

    def test_output_escape_and_symlink_rejected(self):
        with self.assertRaisesRegex(ValueError, "output_outside_private_root"):
            subject._private_path(self.root.parent / "outside", self.root)
        (self.root / "link").symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "private_path_symlink"):
            subject._private_path(self.root / "link" / "index", self.root)

    def test_preview_escapes_untrusted_text(self):
        self.build()
        result = subject.search(provider=FakeProvider(), query='<script>alert("x")</script>', **self.common)
        result["hits"][0]["text"] = '<img src=x onerror="alert(1)">'
        document = subject.preview_html(result)
        self.assertNotIn("<script>", document)
        self.assertIn("&lt;img", document)
        self.assertIn("Content-Security-Policy", document)
        self.assertIn("data:image/png;base64,", document)

    def test_query_bounds(self):
        for query, top_k in (("", 5), ("q", 0), ("q", True), ("a"*4001, 5)):
            with self.assertRaises(ValueError):
                subject.search(provider=self.provider, query=query, top_k=top_k, **self.common)
        self.assertEqual(self.provider.calls, 0)


if __name__ == "__main__":
    unittest.main()
