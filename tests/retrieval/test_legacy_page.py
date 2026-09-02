from __future__ import annotations

from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from midprojectrag.evidence import Evidence, EvidenceStore, build_from_chunks
from midprojectrag.indexing.chunking import PageChunkConfig, build_page_chunks
from midprojectrag.ingest.common import canonical_json, sha256_text
from midprojectrag.retrieval.legacy_page import (
    LegacyPageArtifactPin, LegacyPageRetriever, load_legacy_page_retriever, read_pinned_page_chunks,
)


def fixture(*, split=False):
    blocks = []
    for index, text in enumerate(("A" * 500 if split else "alpha", "beta"), 1):
        blocks.append(dict(
            block_id="block_" + str(index) * 24, doc_id="doc_" + str(index) * 24,
            text=text, block_type="page_text", page_start=1, page_end=1,
            section_path=["section"], content_sha256=sha256_text(text), retrieval_role="primary",
        ))
    chunks = build_page_chunks(blocks, PageChunkConfig(max_chars=256 if split else 24000))
    store = build_from_chunks(chunks, max_chars=80)
    return chunks, store


def artifact(root, chunks, vectors):
    chunks_bytes = "".join(canonical_json(row) + "\n" for row in chunks).encode()
    rows_bytes = "".join(canonical_json({"chunk_id": row["chunk_id"], "doc_id": row["doc_id"]})
                         + "\n" for row in chunks).encode()
    buffer = io.BytesIO()
    np.save(buffer, vectors, allow_pickle=False)
    vectors_bytes = buffer.getvalue()
    digest = lambda value: hashlib.sha256(value).hexdigest()
    metadata = {
        "schema_version": "1.0", "engine": "numpy", "metric": "cosine_via_normalized_inner_product",
        "count": len(chunks), "dimensions": vectors.shape[1], "embedding_model": "synthetic-page-encoder-v1",
        "corpus_manifest_sha256": "1" * 64, "chunk_config_sha256": chunks[0]["config_sha256"],
        "chunk_artifact_sha256": digest(chunks_bytes), "vectors_sha256": digest(vectors_bytes),
        "rows_sha256": digest(rows_bytes), "index_sha256": None, "api_profile": "synthetic",
        "index_config_sha256": "2" * 64,
    }
    metadata_bytes = json.dumps(metadata).encode()
    for name, payload in (("metadata.json", metadata_bytes), ("rows.jsonl", rows_bytes),
                          ("vectors.npy", vectors_bytes), ("chunks.jsonl", chunks_bytes)):
        (root / name).write_bytes(payload)
    return LegacyPageArtifactPin(
        metadata_sha256=digest(metadata_bytes), chunks_sha256=digest(chunks_bytes),
        rows_sha256=digest(rows_bytes), vectors_sha256=digest(vectors_bytes),
        corpus_manifest_sha256=metadata["corpus_manifest_sha256"],
        chunk_config_sha256=metadata["chunk_config_sha256"], index_config_sha256=metadata["index_config_sha256"],
        embedding_model=metadata["embedding_model"], count=len(chunks), dimensions=vectors.shape[1],
        api_profile="synthetic",
    )


class LegacyPageTests(unittest.TestCase):
    def test_actual_units_are_page_only_even_when_child_text_is_identical(self):
        chunks, store = fixture()
        retriever = LegacyPageRetriever(store, chunks, np.eye(2, dtype=np.float32), lambda query: [1, 0])
        results = retriever.search("alpha", limit=2)
        self.assertTrue(all(store.get(hit.evidence_id).kind == "page" for hit in results))
        self.assertEqual(store.get(results[0].evidence_id).source_chunk_ids, (chunks[0]["chunk_id"],))
        self.assertEqual(retriever.embedding_unit, "legacy_page_part")

    def test_split_parts_pool_without_hiding_other_pages_before_limit(self):
        chunks, store = fixture(split=True)
        self.assertEqual(len(chunks), 3)
        retriever = LegacyPageRetriever(store, chunks, np.array([[1, 0], [1, 0], [0, 1]], dtype=np.float32),
                                        lambda query: [1, 0])
        results = retriever.search("x", limit=2)
        self.assertEqual(len(results), 2)
        self.assertEqual(retriever.chunk_count, 3)
        self.assertEqual(retriever.page_count, 2)
        self.assertEqual(results[0].score, 1.0)
        self.assertEqual(store.get(results[0].evidence_id).source_chunk_ids,
                         tuple(row["chunk_id"] for row in chunks[:2]))

    def test_scope_applies_before_scoring_and_empty_scope_never_embeds(self):
        chunks, store = fixture()
        calls = []
        retriever = LegacyPageRetriever(store, chunks, np.eye(2, dtype=np.float32),
                                        lambda query: calls.append(query) or [1, 0])
        self.assertEqual(retriever.search("x", limit=1, allowed_doc_ids=frozenset()), ())
        self.assertEqual(retriever.search("x", limit=1, allowed_doc_ids=frozenset({"absent"})), ())
        self.assertEqual(calls, [])
        result = retriever.search("x", limit=1, allowed_doc_ids=frozenset({chunks[1]["doc_id"]}))
        self.assertEqual(store.get(result[0].evidence_id).doc_id, chunks[1]["doc_id"])

    def test_text_or_provenance_change_cannot_reuse_vector(self):
        chunks, store = fixture()
        page = next(record for record in store.all() if record.kind == "page")
        for change in ({"text": page.text + "!"}, {"source_chunk_ids": ()}, {"section_path": ("other",)},
                       {"source_block_ids": ("other",)}, {"doc_id": "other"}, {"page": 2}):
            data = page.to_dict()
            del data["evidence_id"], data["content_sha256"]
            for field in ("source_block_ids", "section_path", "source_chunk_ids", "support_refs"):
                data[field] = tuple(data[field])
            changed = Evidence.create(**(data | change))
            altered = EvidenceStore([record for record in store.all() if record.kind == "page" and record != page]
                                    + [changed])
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "legacy_page_evidence_mismatch"):
                LegacyPageRetriever(altered, chunks, np.eye(2, dtype=np.float32), lambda query: [1, 0])

    def test_incomplete_parts_duplicate_rows_and_mutable_vectors_rejected_or_detached(self):
        chunks, store = fixture(split=True)
        with self.assertRaisesRegex(ValueError, "incomplete_or_inconsistent"):
            LegacyPageRetriever(store, chunks[1:], np.eye(2, dtype=np.float32), lambda query: [1, 0])
        with self.assertRaisesRegex(ValueError, "duplicate_legacy_chunk_id"):
            LegacyPageRetriever(store, [chunks[0], chunks[0]], np.eye(2, dtype=np.float32), lambda query: [1, 0])
        chunks, store = fixture()
        vectors = np.eye(2, dtype=np.float32)
        retriever = LegacyPageRetriever(store, chunks, vectors, lambda query: [1, 0])
        vectors[:] = 0
        chunks[0]["text"] = "changed after constructor"
        self.assertEqual(retriever.search("x", limit=1)[0].score, 1)

    def test_malformed_vectors_and_queries(self):
        chunks, store = fixture()
        for vectors in (np.eye(2), np.ones((2, 2), dtype=np.float32),
                        np.array([[float("nan"), 0], [0, 1]], dtype=np.float32)):
            with self.subTest(vectors=vectors), self.assertRaises(ValueError):
                LegacyPageRetriever(store, chunks, vectors, lambda query: [1, 0])
        for query in ([True, 0], [0, 0], [float("inf"), 0], [1], {"vector": [1, 0]}):
            retriever = LegacyPageRetriever(store, chunks, np.eye(2, dtype=np.float32), lambda _: query)
            with self.subTest(query=query), self.assertRaisesRegex(ValueError, "invalid_query_vector"):
                retriever.search("x", limit=1)

    def test_pinned_loader_reads_without_source_mutations_or_model_calls(self):
        chunks, store = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pin = artifact(root, chunks, np.eye(2, dtype=np.float32))
            before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in root.iterdir()}
            calls = []
            loaded = load_legacy_page_retriever(store, index_dir=root, chunks_path=root / "chunks.jsonl",
                                                query_embedder=lambda query: calls.append(query) or [1, 0], pin=pin)
            self.assertEqual(read_pinned_page_chunks(root / "chunks.jsonl", pin=pin), tuple(chunks))
            self.assertEqual(calls, [])
            self.assertEqual(loaded.provenance["retrieval_kind"], "page_parent_maxpool")
            self.assertEqual(before, {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in root.iterdir()})
            self.assertFalse((root / ".index.lock").exists())

    def test_each_artifact_hash_is_checked_before_reuse(self):
        chunks, store = fixture()
        for filename, code in (("metadata.json", "legacy_metadata_hash_mismatch"),
                               ("chunks.jsonl", "legacy_chunks_hash_mismatch"),
                               ("rows.jsonl", "legacy_rows_hash_mismatch"),
                               ("vectors.npy", "legacy_vectors_hash_mismatch")):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                pin = artifact(root, chunks, np.eye(2, dtype=np.float32))
                target = root / filename
                target.write_bytes(target.read_bytes() + b" ")
                with self.assertRaisesRegex(ValueError, code):
                    load_legacy_page_retriever(store, index_dir=root, chunks_path=root / "chunks.jsonl",
                                               query_embedder=lambda query: [1, 0], pin=pin)

    def test_repinning_metadata_cannot_change_model_or_shape_claim(self):
        chunks, store = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pin = artifact(root, chunks, np.eye(2, dtype=np.float32))
            metadata = json.loads((root / "metadata.json").read_bytes())
            metadata["embedding_model"] = "wrong-model"
            payload = json.dumps(metadata).encode()
            (root / "metadata.json").write_bytes(payload)
            repinned = replace(pin, metadata_sha256=hashlib.sha256(payload).hexdigest())
            with self.assertRaisesRegex(ValueError, "legacy_index_metadata_mismatch"):
                load_legacy_page_retriever(store, index_dir=root, chunks_path=root / "chunks.jsonl",
                                           query_embedder=lambda query: [1, 0], pin=repinned)


if __name__ == "__main__":
    unittest.main()
