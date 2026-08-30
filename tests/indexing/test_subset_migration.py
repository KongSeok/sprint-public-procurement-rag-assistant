from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np

from midprojectrag.cli import main
from midprojectrag.ingest.common import (
    canonical_json,
    read_jsonl,
    sha256_file,
    sha256_text,
    write_json,
    write_jsonl,
)
from midprojectrag.indexing.chunking import chunk_artifact_sha256
from midprojectrag.indexing.exact_index import ExactDenseIndex
from midprojectrag.indexing.subset_migration import migrate_api_exact_index_subset
from midprojectrag.stacks.api import api_config_sha256, build_api_index_config


def _chunk(index: int, doc: int) -> dict[str, object]:
    text = f"page-{index}"
    doc_id = f"doc_{doc:024x}"
    block_id = f"block_{index:024x}"
    content_sha256 = sha256_text(text)
    identity = {
        "block_id": block_id,
        "config_sha256": "1" * 64,
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
        "config_sha256": "1" * 64,
        "content_sha256": content_sha256,
    }


class ApiIndexSubsetMigrationTests(unittest.TestCase):
    def _fixture(self, root: Path) -> dict[str, object]:
        source_data = root / "source"
        target_data = root / "target"
        source_private = source_data / "private"
        target_private = target_data / "private"
        source_index_dir = source_private / "indexes/api/source-index"
        output_dir = target_private / "indexes/api/migrated-index"
        source_private.mkdir(parents=True)
        target_private.mkdir(parents=True)

        source_chunks = [_chunk(1, 1), _chunk(2, 2), _chunk(3, 3)]
        target_chunks = [source_chunks[1], source_chunks[0]]
        source_chunks_path = source_private / "chunks.page-v1.jsonl"
        target_chunks_path = target_private / "chunks.page-v1.jsonl"
        write_jsonl(source_chunks_path, source_chunks)
        write_jsonl(target_chunks_path, target_chunks)

        source_config = build_api_index_config(
            api_profile="personal_experimental",
            corpus_manifest_sha256="2" * 64,
            chunk_artifact_sha256=chunk_artifact_sha256(source_chunks),
            chunk_config_sha256="1" * 64,
            embedding_model="text-embedding-3-small",
            embedding_dimensions=2,
            index_engine="numpy",
            batch_size=2,
        )
        source_index = ExactDenseIndex(
            source_chunks,
            np.asarray(
                [[0.123, 0.456], [0.789, 0.234], [-0.333, 0.777]],
                dtype=np.float32,
            ),
            engine="numpy",
        )
        source_index.save(
            source_index_dir,
            corpus_manifest_sha256="2" * 64,
            embedding_model="text-embedding-3-small",
            api_profile="personal_experimental",
            index_config_sha256=api_config_sha256(source_config),
        )
        write_json(source_index_dir / "index-config.json", source_config)

        target_manifest_path = target_private / "manifest.extracted.jsonl"
        write_jsonl(
            target_manifest_path,
            [
                {
                    "doc_id": target_chunks[0]["doc_id"],
                    "status": "ok",
                    "index_eligible": True,
                },
                {
                    "doc_id": target_chunks[1]["doc_id"],
                    "status": "ok",
                    "index_eligible": True,
                },
            ],
        )
        target_manifest_sha256 = sha256_file(target_manifest_path)
        target_sidecar_path = target_chunks_path.with_name(
            f"{target_chunks_path.name}.metadata.json"
        )
        write_json(
            target_sidecar_path,
            {
                "schema_version": "1.0",
                "source_manifest_sha256": target_manifest_sha256,
                "chunk_artifact_sha256": chunk_artifact_sha256(target_chunks),
                "config_sha256": "1" * 64,
                "documents": 2,
                "chunks": 2,
            },
        )
        return {
            "source_data": source_data,
            "target_data": target_data,
            "source_chunks": source_chunks,
            "target_chunks": target_chunks,
            "source_chunks_path": source_chunks_path,
            "target_chunks_path": target_chunks_path,
            "source_index_dir": source_index_dir,
            "target_manifest_path": target_manifest_path,
            "target_manifest_sha256": target_manifest_sha256,
            "target_sidecar_path": target_sidecar_path,
            "output_dir": output_dir,
        }

    def _migrate(self, fixture: dict[str, object]):
        return migrate_api_exact_index_subset(
            source_chunks_path=fixture["source_chunks_path"],
            source_index_dir=fixture["source_index_dir"],
            target_chunks_path=fixture["target_chunks_path"],
            target_chunk_metadata_path=fixture["target_sidecar_path"],
            target_manifest_path=fixture["target_manifest_path"],
            target_manifest_sha256=fixture["target_manifest_sha256"],
            output_dir=fixture["output_dir"],
        )

    def test_reorders_verified_vectors_and_writes_hash_bound_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            result = self._migrate(fixture)

            output_dir = fixture["output_dir"]
            vectors = np.load(output_dir / "vectors.npy", allow_pickle=False)
            source_vectors = np.load(
                fixture["source_index_dir"] / "vectors.npy",
                allow_pickle=False,
            )
            np.testing.assert_array_equal(
                vectors,
                source_vectors[[1, 0]],
            )
            self.assertEqual(
                read_jsonl(output_dir / "rows.jsonl"),
                [
                    {"chunk_id": chunk["chunk_id"], "doc_id": chunk["doc_id"]}
                    for chunk in fixture["target_chunks"]
                ],
            )
            self.assertFalse(result.provenance["network_access"])
            self.assertEqual(result.provenance["removed_count"], 1)
            self.assertEqual(
                result.provenance["target"]["index_metadata_file_sha256"],
                sha256_file(output_dir / "metadata.json"),
            )
            self.assertEqual(
                result.provenance_sha256,
                sha256_file(output_dir / "migration-provenance.json"),
            )
            loaded = ExactDenseIndex.load(
                output_dir,
                fixture["target_chunks"],
                expected_embedding_model="text-embedding-3-small",
                expected_dimensions=2,
                expected_api_profile="personal_experimental",
                expected_index_config_sha256=result.metadata["index_config_sha256"],
            )
            self.assertEqual(loaded.dimensions, 2)

    def test_refuses_valid_but_mutated_target_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            mutated = [dict(chunk) for chunk in fixture["target_chunks"]]
            mutated[0]["section_path"] = ["mutated"]
            write_jsonl(fixture["target_chunks_path"], mutated)
            sidecar = json.loads(
                fixture["target_sidecar_path"].read_text(encoding="utf-8")
            )
            sidecar["chunk_artifact_sha256"] = chunk_artifact_sha256(mutated)
            write_json(fixture["target_sidecar_path"], sidecar)
            with self.assertRaisesRegex(ValueError, "target_chunk_not_byte_identical"):
                self._migrate(fixture)
            self.assertFalse(fixture["output_dir"].exists())

    def test_refuses_duplicate_and_missing_target_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            duplicated = [fixture["target_chunks"][0], fixture["target_chunks"][0]]
            write_jsonl(fixture["target_chunks_path"], duplicated)
            with self.assertRaisesRegex(ValueError, "duplicate_target_chunk_id"):
                self._migrate(fixture)

        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            missing = [fixture["target_chunks"][0], _chunk(4, 1)]
            write_jsonl(fixture["target_chunks_path"], missing)
            sidecar = json.loads(
                fixture["target_sidecar_path"].read_text(encoding="utf-8")
            )
            sidecar["chunk_artifact_sha256"] = chunk_artifact_sha256(missing)
            sidecar["documents"] = 2
            write_json(fixture["target_sidecar_path"], sidecar)
            with self.assertRaisesRegex(ValueError, "target_chunk_missing_from_source"):
                self._migrate(fixture)

    def test_refuses_tampered_source_index_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            config_path = fixture["source_index_dir"] / "index-config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["unexpected"] = True
            write_json(config_path, config)
            with self.assertRaisesRegex(ValueError, "invalid_source_index_config"):
                self._migrate(fixture)
            self.assertFalse(fixture["output_dir"].exists())

    def test_cli_migrates_locally_without_egress_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            captured = io.StringIO()
            with redirect_stdout(captured):
                code = main(
                    [
                        "migrate-index-subset",
                        "--source-data-dir",
                        str(fixture["source_data"]),
                        "--source-chunks",
                        str(fixture["source_chunks_path"]),
                        "--source-index-dir",
                        str(fixture["source_index_dir"]),
                        "--target-data-dir",
                        str(fixture["target_data"]),
                        "--target-chunks",
                        str(fixture["target_chunks_path"]),
                        "--target-manifest",
                        str(fixture["target_manifest_path"]),
                        "--target-manifest-sha256",
                        fixture["target_manifest_sha256"],
                        "--output-dir",
                        str(fixture["output_dir"]),
                    ]
                )
            self.assertEqual(code, 0)
            summary = json.loads(captured.getvalue())
            self.assertTrue(summary["passed"])
            self.assertFalse(summary["network_access"])
            self.assertEqual(summary["source_chunks"], 3)
            self.assertEqual(summary["target_chunks"], 2)


if __name__ == "__main__":
    unittest.main()
