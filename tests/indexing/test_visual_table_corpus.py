from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from midprojectrag.cli import main
from midprojectrag.ingest.common import (
    canonical_json,
    read_jsonl,
    sha256_file,
    sha256_text,
    write_json,
    write_jsonl,
)
from midprojectrag.indexing.chunking import TableChunkConfig, build_table_chunks
from midprojectrag.indexing.visual_table_context import (
    materialize_visual_table_corpus,
)


DOC_A = "doc_000000000000000000000001"
DOC_B = "doc_000000000000000000000002"
DOC_C = "doc_000000000000000000000003"
DOC_D = "doc_000000000000000000000004"
BLOCK_A = "block_000000000000000000000001"
BLOCK_B = "block_000000000000000000000002"


class _Counter:
    def count(self, text: str) -> int:
        return len(text)


def _table_block(doc_id: str, block_id: str, *, page: int, label: str) -> dict[str, object]:
    cells = [
        {
            "row": 0,
            "col": 0,
            "row_span": 1,
            "col_span": 1,
            "is_header": True,
            "text": "업무",
        },
        {
            "row": 0,
            "col": 1,
            "row_span": 1,
            "col_span": 1,
            "is_header": True,
            "text": "기간",
        },
        {
            "row": 1,
            "col": 0,
            "row_span": 1,
            "col_span": 1,
            "is_header": False,
            "text": label,
        },
        {
            "row": 1,
            "col": 1,
            "row_span": 1,
            "col_span": 1,
            "is_header": False,
            "text": "",
        },
    ]
    structure = {
        "index": 0,
        "section": 0,
        "paragraph": page,
        "control": 0,
        "rows": 2,
        "cols": 2,
        "cell_count": len(cells),
        "cells": cells,
    }
    text = f"synthetic table {label}"
    return {
        "schema_version": "1.0",
        "block_id": block_id,
        "doc_id": doc_id,
        "sequence": page,
        "block_type": "table",
        "section_path": ["합성 섹션"],
        "page_start": page,
        "page_end": page,
        "bbox": None,
        "text": text,
        "content_sha256": sha256_text(text),
        "structure_sha256": sha256_text(canonical_json(structure)),
        "table_structure": structure,
        "extractor": "rhwp",
        "extractor_version": "0.8.4+adapter-v1",
        "source_locator": f"section:0/paragraph:{page}/table:0",
        "retrieval_role": "structured_auxiliary",
    }


def _source_chunks() -> list[dict[str, object]]:
    blocks = [
        _table_block(DOC_A, BLOCK_A, page=2, label="분석"),
        _table_block(DOC_B, BLOCK_B, page=3, label="구축"),
    ]
    context = {
        DOC_A: {
            "project_name": "합성 사업 A",
            "ordering_agency": "합성 기관 A",
            "project_summary": "합성 요약 A",
        },
        DOC_B: {
            "project_name": "합성 사업 B",
            "ordering_agency": "합성 기관 B",
            "project_summary": "합성 요약 B",
        },
    }
    return build_table_chunks(
        blocks,
        context,
        counter=_Counter(),
        config=TableChunkConfig(max_rows=8, max_chars=2_400, max_tokens=600),
    )


def _overlay(chunk: dict[str, object], *, title: str) -> dict[str, object]:
    page = int(chunk["page_start"])
    block_id = str(chunk["source_block_ids"][0])
    bbox = {"x": 10.0, "y": 20.0, "w": 30.0, "h": 40.0}
    return {
        "schema_version": "1.0",
        "doc_id": chunk["doc_id"],
        "block_id": block_id,
        "structure_sha256": chunk["source_structure_sha256"],
        "status": "verified_render",
        "page_start": page,
        "page_end": page,
        "coordinate_space": "rhwp_css_px_96dpi",
        "render_key": {"section": 0, "paragraph": page, "control": 0},
        "page_contexts": [
            {
                "page": page,
                "sequence_in_page": 1,
                "bbox": bbox,
                "preceding_text": {
                    "text": title,
                    "bbox": bbox,
                    "render_key": {"section": 0, "paragraph": page - 1},
                    "method": "nearest_prior_top_level_textline",
                },
            }
        ],
        "background_cells": [],
        "schedule_facts": [],
    }


class VisualTableCorpusTests(unittest.TestCase):
    _PRESERVED_FIELDS = {
        "doc_id",
        "display_markdown",
        "display_sha256",
        "source_block_ids",
        "section_path",
        "page_start",
        "page_end",
        "source_locator",
        "row_start",
        "row_end",
        "part_index",
        "part_count",
        "retrieval_role",
        "source_structure_sha256",
        "table_structure_sha256",
        "header_source",
    }

    def _fixture(self, root: Path) -> dict[str, object]:
        private = root / "private"
        private.mkdir()
        chunks = _source_chunks()
        source_path = private / "chunks.table-md-rowgroup-v1.jsonl"
        write_jsonl(source_path, chunks)
        manifest = private / "manifest.jsonl"
        write_jsonl(
            manifest,
            [
                {
                    "doc_id": DOC_A,
                    "status": "ok",
                    "index_eligible": True,
                    "extension": ".hwp",
                },
                {
                    "doc_id": DOC_B,
                    "status": "ok",
                    "index_eligible": True,
                    "extension": ".hwp",
                },
                {
                    "doc_id": DOC_C,
                    "status": "ok",
                    "index_eligible": True,
                    "extension": ".pdf",
                },
                {
                    "doc_id": DOC_D,
                    "status": "ok",
                    "index_eligible": True,
                    "extension": ".hwpx",
                },
            ],
        )
        overlays = [
            _overlay(chunks[0], title="A 추진일정"),
            _overlay(chunks[1], title="B 추진일정"),
        ]
        overlay_a = private / "visual-v1" / DOC_A / "table-visual-v1.jsonl"
        overlay_b = private / "visual-v1" / DOC_B / "table-visual-v1.jsonl"
        write_jsonl(overlay_a, [overlays[0]])
        write_jsonl(overlay_b, [overlays[1]])
        corpus_metadata = private / "visual-v1" / "corpus-run-v1.metadata.json"
        write_json(
            corpus_metadata,
            {
                "schema_version": "1.0",
                "method": "rhwp-visual-corpus-rollout-v1",
                "source_manifest_sha256": sha256_file(manifest),
                "requested": 2,
                "succeeded": 2,
                "failed": 0,
                "document_ids": [DOC_A, DOC_B],
                "artifact_set_digest": "b" * 64,
            },
        )
        return {
            "private": private,
            "chunks": chunks,
            "source_path": source_path,
            "manifest": manifest,
            "overlays": overlays,
            "overlay_paths": [overlay_a, overlay_b],
            "corpus_metadata": corpus_metadata,
        }

    def _materialize(
        self,
        fixture: dict[str, object],
        *,
        suffix: str,
        overlay_paths: list[Path] | None = None,
    ) -> tuple[dict[str, object], Path, Path]:
        private = fixture["private"]
        assert isinstance(private, Path)
        output = private / f"chunks.table-md-visual-context-v2.{suffix}.jsonl"
        metadata_output = output.with_name(f"{output.name}.metadata.json")
        result = materialize_visual_table_corpus(
            source_chunks_path=fixture["source_path"],
            overlay_paths=overlay_paths or fixture["overlay_paths"],
            corpus_metadata_path=fixture["corpus_metadata"],
            output_path=output,
            metadata_output=metadata_output,
            private_root=private,
        )
        return result, output, metadata_output

    def test_materializes_one_global_config_and_preserves_source_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            metadata, output, metadata_output = self._materialize(
                fixture, suffix="first"
            )

            enriched = read_jsonl(output)
            source_by_block = {
                chunk["source_block_ids"][0]: chunk for chunk in fixture["chunks"]
            }
            enriched_by_block = {
                chunk["source_block_ids"][0]: chunk for chunk in enriched
            }
            self.assertEqual(set(enriched_by_block), set(source_by_block))
            self.assertEqual(len(enriched), len(fixture["chunks"]))
            self.assertEqual(
                {chunk["config_sha256"] for chunk in enriched},
                {metadata["config_sha256"]},
            )
            self.assertTrue(
                all(
                    chunk["schema_version"] == "1.2"
                    and chunk["chunker_id"] == "table-md-visual-context-v2"
                    for chunk in enriched
                )
            )
            for block_id, source in source_by_block.items():
                actual = enriched_by_block[block_id]
                self.assertEqual(
                    {field: actual[field] for field in self._PRESERVED_FIELDS},
                    {field: source[field] for field in self._PRESERVED_FIELDS},
                )
            self.assertIn("[인접 문맥] A 추진일정", enriched_by_block[BLOCK_A]["text"])
            self.assertIn("[인접 문맥] B 추진일정", enriched_by_block[BLOCK_B]["text"])
            self.assertEqual(json.loads(metadata_output.read_text()), metadata)
            self.assertEqual(metadata["documents"], 2)
            self.assertEqual(metadata["chunks"], 2)
            self.assertEqual(metadata["chunker_id"], "table-md-visual-context-v2")
            self.assertEqual(metadata["retrieval_role"], "structured_auxiliary")

    def test_local_index_accepts_exact_hwp_subset_of_eligible_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            metadata, output, metadata_output = self._materialize(
                fixture, suffix="local-index"
            )
            private = fixture["private"]
            manifest = fixture["manifest"]
            assert isinstance(private, Path)
            assert isinstance(manifest, Path)
            captured = io.StringIO()
            with redirect_stdout(captured):
                code = main(
                    [
                        "local-index",
                        "--data-dir",
                        str(private.parent),
                        "--chunks",
                        str(output),
                        "--chunk-metadata",
                        str(metadata_output),
                        "--output-dir",
                        str(private / "indexes/local/visual-v2"),
                        "--cache-dir",
                        str(private / "caches/local/visual-v2"),
                        "--manifest",
                        str(manifest),
                        "--manifest-sha256",
                        sha256_file(manifest),
                    ]
                )

            self.assertEqual(code, 0, captured.getvalue())
            summary = json.loads(captured.getvalue())
            self.assertTrue(summary["passed"])
            self.assertEqual(summary["chunks"], len(fixture["chunks"]))
            self.assertEqual(metadata["documents"], 2)

    def test_local_index_rejects_incomplete_visual_v2_hwp_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            private = fixture["private"]
            manifest = fixture["manifest"]
            assert isinstance(private, Path)
            assert isinstance(manifest, Path)
            source_path = private / "chunks.incomplete-v1.jsonl"
            write_jsonl(source_path, [fixture["chunks"][0]])
            output = private / "chunks.incomplete-v2.jsonl"
            metadata_output = output.with_name(f"{output.name}.metadata.json")
            materialize_visual_table_corpus(
                source_chunks_path=source_path,
                overlay_paths=[fixture["overlay_paths"][0]],
                corpus_metadata_path=fixture["corpus_metadata"],
                output_path=output,
                metadata_output=metadata_output,
                private_root=private,
            )
            captured = io.StringIO()
            with redirect_stdout(captured):
                code = main(
                    [
                        "local-index",
                        "--data-dir",
                        str(private.parent),
                        "--chunks",
                        str(output),
                        "--chunk-metadata",
                        str(metadata_output),
                        "--output-dir",
                        str(private / "indexes/local/incomplete-v2"),
                        "--cache-dir",
                        str(private / "caches/local/incomplete-v2"),
                        "--manifest",
                        str(manifest),
                        "--manifest-sha256",
                        sha256_file(manifest),
                    ]
                )

            self.assertEqual(code, 8)
            self.assertEqual(
                json.loads(captured.getvalue()),
                {"passed": False, "error": "chunk_manifest_document_mismatch"},
            )

    def test_local_index_rejects_inconsistent_visual_v2_aggregate_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            _metadata, output, metadata_output = self._materialize(
                fixture, suffix="bad-counts"
            )
            private = fixture["private"]
            manifest = fixture["manifest"]
            assert isinstance(private, Path)
            assert isinstance(manifest, Path)
            tampered = json.loads(metadata_output.read_text(encoding="utf-8"))
            tampered["context_counts"]["chunks_with_prior_context"] = (
                tampered["chunks"] + 1
            )
            write_json(metadata_output, tampered)
            captured = io.StringIO()
            with redirect_stdout(captured):
                code = main(
                    [
                        "local-index",
                        "--data-dir",
                        str(private.parent),
                        "--chunks",
                        str(output),
                        "--chunk-metadata",
                        str(metadata_output),
                        "--output-dir",
                        str(private / "indexes/local/bad-counts"),
                        "--cache-dir",
                        str(private / "caches/local/bad-counts"),
                        "--manifest",
                        str(manifest),
                        "--manifest-sha256",
                        sha256_file(manifest),
                    ]
                )

            self.assertEqual(code, 8)
            self.assertEqual(
                json.loads(captured.getvalue()),
                {"passed": False, "error": "invalid_chunk_metadata"},
            )

    def test_local_index_rejects_noncanonical_chunk_hash_rebinding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            _metadata, output, metadata_output = self._materialize(
                fixture, suffix="noncanonical"
            )
            private = fixture["private"]
            manifest = fixture["manifest"]
            assert isinstance(private, Path)
            assert isinstance(manifest, Path)
            output.write_text(
                "".join(
                    json.dumps(record, ensure_ascii=False, sort_keys=False) + "\n"
                    for record in read_jsonl(output)
                ),
                encoding="utf-8",
            )
            tampered = json.loads(metadata_output.read_text(encoding="utf-8"))
            tampered["chunk_artifact_sha256"] = sha256_file(output)
            write_json(metadata_output, tampered)
            captured = io.StringIO()
            with redirect_stdout(captured):
                code = main(
                    [
                        "local-index",
                        "--data-dir",
                        str(private.parent),
                        "--chunks",
                        str(output),
                        "--chunk-metadata",
                        str(metadata_output),
                        "--output-dir",
                        str(private / "indexes/local/noncanonical"),
                        "--cache-dir",
                        str(private / "caches/local/noncanonical"),
                        "--manifest",
                        str(manifest),
                        "--manifest-sha256",
                        sha256_file(manifest),
                    ]
                )

            self.assertEqual(code, 8)
            self.assertEqual(
                json.loads(captured.getvalue()),
                {"passed": False, "error": "chunk_artifact_hash_mismatch"},
            )

    def test_local_index_keeps_legacy_table_v1_subset_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            private = fixture["private"]
            manifest = fixture["manifest"]
            source_path = fixture["source_path"]
            assert isinstance(private, Path)
            assert isinstance(manifest, Path)
            assert isinstance(source_path, Path)
            chunks = fixture["chunks"]
            metadata_output = source_path.with_name(f"{source_path.name}.metadata.json")
            write_json(
                metadata_output,
                {
                    "schema_version": "1.1",
                    "source_manifest_sha256": sha256_file(manifest),
                    "chunk_artifact_sha256": sha256_file(source_path),
                    "config_sha256": chunks[0]["config_sha256"],
                    "documents": 2,
                    "eligible_documents": 4,
                    "chunks": len(chunks),
                    "retrieval_role": "structured_auxiliary",
                    "chunker_id": "table-md-rowgroup-v1",
                    "coverage_policy": "eligible_subset",
                    "tokenizer_id": "cl100k_base-pinned",
                },
            )
            captured = io.StringIO()
            with redirect_stdout(captured):
                code = main(
                    [
                        "local-index",
                        "--data-dir",
                        str(private.parent),
                        "--chunks",
                        str(source_path),
                        "--chunk-metadata",
                        str(metadata_output),
                        "--output-dir",
                        str(private / "indexes/local/legacy-table-v1"),
                        "--cache-dir",
                        str(private / "caches/local/legacy-table-v1"),
                        "--manifest",
                        str(manifest),
                        "--manifest-sha256",
                        sha256_file(manifest),
                    ]
                )

            self.assertEqual(code, 0, captured.getvalue())
            self.assertTrue(json.loads(captured.getvalue())["passed"])

    def test_overlay_path_and_record_order_do_not_change_hash_or_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            first, first_output, _first_metadata = self._materialize(
                fixture, suffix="first"
            )
            combined = fixture["private"] / "visual-v1" / "combined.jsonl"
            write_jsonl(combined, list(reversed(fixture["overlays"])))
            second, second_output, _second_metadata = self._materialize(
                fixture,
                suffix="second",
                overlay_paths=[combined],
            )

            self.assertEqual(first["overlay_artifact_sha256"], second["overlay_artifact_sha256"])
            self.assertEqual(first["config_sha256"], second["config_sha256"])
            self.assertEqual(first["chunk_artifact_sha256"], second["chunk_artifact_sha256"])
            self.assertEqual(first_output.read_bytes(), second_output.read_bytes())
            expected_overlay_hash = sha256_text(
                "".join(
                    canonical_json(record) + "\n"
                    for record in sorted(
                        fixture["overlays"],
                        key=lambda value: (value["doc_id"], value["block_id"]),
                    )
                )
            )
            self.assertEqual(first["overlay_artifact_sha256"], expected_overlay_hash)

    def test_rejects_missing_and_duplicate_overlay_join(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            with self.assertRaisesRegex(ValueError, "^visual_overlay_block_missing$"):
                self._materialize(
                    fixture,
                    suffix="missing",
                    overlay_paths=[fixture["overlay_paths"][0]],
                )
            duplicate = fixture["private"] / "visual-v1" / "duplicate.jsonl"
            write_jsonl(duplicate, [fixture["overlays"][0]])
            with self.assertRaisesRegex(ValueError, "^visual_overlay_record_invalid$"):
                self._materialize(
                    fixture,
                    suffix="duplicate",
                    overlay_paths=[*fixture["overlay_paths"], duplicate],
                )

    def test_metadata_binds_every_input_and_published_chunk_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            metadata, output, metadata_output = self._materialize(
                fixture, suffix="binding"
            )

            self.assertEqual(
                metadata["source_chunk_artifact_sha256"],
                sha256_file(fixture["source_path"]),
            )
            self.assertEqual(
                metadata["corpus_metadata_sha256"],
                sha256_file(fixture["corpus_metadata"]),
            )
            self.assertEqual(metadata["chunk_artifact_sha256"], sha256_file(output))
            self.assertEqual(json.loads(metadata_output.read_text()), metadata)

            original = metadata["corpus_metadata_sha256"]
            corpus_metadata = json.loads(fixture["corpus_metadata"].read_text())
            corpus_metadata["artifact_set_digest"] = "c" * 64
            write_json(fixture["corpus_metadata"], corpus_metadata)
            rebound, _rebound_output, _rebound_metadata = self._materialize(
                fixture, suffix="rebound"
            )
            self.assertNotEqual(rebound["corpus_metadata_sha256"], original)
            self.assertEqual(
                rebound["corpus_metadata_sha256"],
                sha256_file(fixture["corpus_metadata"]),
            )

    def test_rejects_input_or_output_outside_private_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = self._fixture(root)
            outside = root / "outside.jsonl"
            write_jsonl(outside, fixture["chunks"])
            private = fixture["private"]
            with self.assertRaisesRegex(
                ValueError, "^visual_corpus_path_outside_private_root$"
            ):
                materialize_visual_table_corpus(
                    source_chunks_path=outside,
                    overlay_paths=fixture["overlay_paths"],
                    corpus_metadata_path=fixture["corpus_metadata"],
                    output_path=private / "safe.jsonl",
                    metadata_output=private / "safe.metadata.json",
                    private_root=private,
                )
            with self.assertRaisesRegex(
                ValueError, "^visual_corpus_path_outside_private_root$"
            ):
                materialize_visual_table_corpus(
                    source_chunks_path=fixture["source_path"],
                    overlay_paths=fixture["overlay_paths"],
                    corpus_metadata_path=fixture["corpus_metadata"],
                    output_path=root / "escaped.jsonl",
                    metadata_output=private / "safe.metadata.json",
                    private_root=private,
                )


if __name__ == "__main__":
    unittest.main()
