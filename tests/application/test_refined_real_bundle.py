from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from midprojectrag.application import load_rag_application
from midprojectrag.ingest.common import read_jsonl, sha256_file


class RefinedRealBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[2]
        cls.data_dir = cls.root / "resources" / "data_refined"
        cls.config_path = (
            cls.root
            / "configs"
            / "rag"
            / "api-small-nano-streamlit-refined98-page-v2.json"
        )
        required = (
            cls.config_path,
            cls.data_dir / "private" / "manifest.extracted.jsonl",
            cls.data_dir / "private" / "chunks.page-v1.jsonl",
            cls.data_dir / "private" / "catalog" / "refined-direct-v2.jsonl",
            cls.data_dir
            / "private"
            / "indexes"
            / "api"
            / "personal_experimental"
            / "text-embedding-3-small-1536"
            / "vectors.npy",
        )
        if not all(path.is_file() for path in required):
            raise unittest.SkipTest("private_refined98_page_bundle_unavailable")

    def test_loads_98_document_page_index_without_provider_or_credentials(self) -> None:
        with (
            mock.patch(
                "midprojectrag.application.composition._load_project_dotenv",
                side_effect=AssertionError("dotenv loaded during startup"),
            ),
            mock.patch(
                "midprojectrag.application.composition.OpenAIEmbeddingProvider",
                side_effect=AssertionError("embedding provider constructed eagerly"),
            ),
            mock.patch(
                "midprojectrag.application.composition.OpenAIGenerator",
                side_effect=AssertionError("generator constructed eagerly"),
            ),
        ):
            service = load_rag_application(self.config_path, self.data_dir)
            documents = service.list_documents()

        self.assertEqual(service.runtime.document_count, 98)
        self.assertEqual(len(documents), 98)
        self.assertEqual(service.runtime.embedding_model, "text-embedding-3-small")
        self.assertEqual(service.runtime.embedding_dimensions, 1536)
        self.assertEqual(service.runtime.generator_model, "gpt-5-nano")
        self.assertEqual(
            service.runtime.index_config_sha256,
            "b341f6dfd9c993c80964536ad0aea74c272f8dac7a6bb8e35ff4efb9e9b8f61b",
        )
        with self.assertRaisesRegex(RuntimeError, "metadata_catalog_unavailable"):
            service.list_document_cards()

    def test_bundle_is_hash_bound_page_only_and_contains_dedupe_inheritance(self) -> None:
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        artifacts = config["artifacts"]
        self.assertEqual(config["schema_version"], "1.0")
        self.assertNotIn("correction_set", artifacts)
        self.assertNotIn("table_chunks", artifacts)
        self.assertNotIn("table_index", artifacts)

        for key in ("retrieval_manifest", "chunks", "catalog_manifest"):
            artifact = artifacts[key]
            self.assertEqual(
                sha256_file(self.data_dir / artifact["path"]),
                artifact["sha256"],
            )
        index_dir = self.data_dir / artifacts["index"]["path"]
        self.assertEqual(
            sha256_file(index_dir / "metadata.json"),
            artifacts["index"]["metadata_sha256"],
        )
        self.assertEqual(
            sha256_file(index_dir / "index-config.json"),
            artifacts["index"]["config_file_sha256"],
        )

        retrieval = read_jsonl(self.data_dir / artifacts["retrieval_manifest"]["path"])
        catalog = read_jsonl(self.data_dir / artifacts["catalog_manifest"]["path"])
        identity = lambda row: (
            row["doc_id"],
            row["sha256"],
            row["normalized_filename"],
        )
        self.assertEqual(
            {identity(row) for row in retrieval},
            {identity(row) for row in catalog},
        )
        self.assertEqual(len(retrieval), 98)
        with (self.data_dir / artifacts["chunks"]["path"]).open(
            "r", encoding="utf-8"
        ) as source:
            self.assertEqual(sum(1 for _ in source), 9331)
        by_id = {row["doc_id"]: row for row in catalog}
        for doc_id in (
            "doc_4f3e8d34e23395541595fbf4",
            "doc_12c2a647de958f7a78d95899",
        ):
            metadata = by_id[doc_id]["metadata"]
            self.assertEqual(metadata["notice_round"], "00")
            self.assertEqual(metadata["notice_id_namespace"], "g2b")


if __name__ == "__main__":
    unittest.main()
