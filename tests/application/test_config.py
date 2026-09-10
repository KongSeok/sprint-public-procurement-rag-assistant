from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from midprojectrag.application.config import load_runtime_config


def _config(*, schema_version: str = "1.0") -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "runtime_id": "test-runtime",
        "stack_id": "api",
        "api_profile": "personal_experimental",
        "embedding": {"model": "text-embedding-3-small", "dimensions": 2},
        "generation": {"model": "gpt-5-nano", "max_output_tokens": 2000},
        "retrieval": {"top_k": 10, "context_top_k": 5, "max_citations": 3},
        "artifacts": {
            "retrieval_manifest": {
                "path": "private/manifest.jsonl",
                "sha256": "1" * 64,
            },
            "chunks": {"path": "private/chunks.jsonl", "sha256": "2" * 64},
            "catalog_manifest": {
                "path": "private/catalog.jsonl",
                "sha256": "3" * 64,
                "snapshot_id": "snapshot_test",
            },
            "index": {
                "path": "private/indexes/api/test",
                "metadata_sha256": "4" * 64,
                "config_file_sha256": "5" * 64,
            },
            "query_cache_path": "private/caches/api/test",
            "tokenizer_cache_path": "private/tiktoken-cache",
            "budget_ledger_path": "private/api-budget.ui.json",
        },
        "budget": {"limit_usd": "5.00"},
        "observability": {"backend": "disabled"},
    }


def _dual_config() -> dict[str, object]:
    value = _config(schema_version="1.2")
    value["retrieval"].update(
        {
            "fusion": "rrf-v1",
            "rrf_k": 60,
            "table_retrieval_cap": 3,
            "table_context_cap": 2,
        }
    )
    value["artifacts"]["table_chunks"] = {
        "path": "private/table-chunks.jsonl",
        "sha256": "6" * 64,
    }
    value["artifacts"]["table_layout"] = {
        "path": "private/table-layout-v1.jsonl",
        "sha256": "9" * 64,
    }
    value["artifacts"]["table_index"] = {
        "path": "private/indexes/api/test-table",
        "metadata_sha256": "7" * 64,
        "config_file_sha256": "8" * 64,
    }
    return value


class RuntimeConfigTests(unittest.TestCase):
    def _write(self, directory: str, value: dict[str, object]) -> Path:
        path = Path(directory) / "runtime.json"
        path.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path

    def test_loads_strict_versioned_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = load_runtime_config(self._write(directory, _config()))
        self.assertEqual(config.runtime_id, "test-runtime")
        self.assertEqual(config.embedding_model, "text-embedding-3-small")
        self.assertEqual(config.generator_model, "gpt-5-nano")
        self.assertEqual(config.max_output_tokens, 2000)
        self.assertIsNone(config.correction_set)
        self.assertEqual(len(config.config_sha256), 64)

    def test_version_1_1_requires_correction_set(self) -> None:
        value = _config(schema_version="1.1")
        value["artifacts"]["correction_set"] = {
            "path": "private/metadata-corrections/corrections.json",
            "sha256": "6" * 64,
        }
        with tempfile.TemporaryDirectory() as directory:
            config = load_runtime_config(self._write(directory, value))
        self.assertEqual(config.schema_version, "1.1")
        self.assertIsNotNone(config.correction_set)
        self.assertEqual(
            config.correction_set.relpath,
            "private/metadata-corrections/corrections.json",
        )

        missing = _config(schema_version="1.1")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "invalid_runtime_artifacts"):
                load_runtime_config(self._write(directory, missing))

    def test_version_1_2_loads_strict_dual_lane_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = load_runtime_config(self._write(directory, _dual_config()))
        self.assertEqual(config.schema_version, "1.2")
        self.assertEqual(config.fusion, "rrf-v1")
        self.assertEqual(config.rrf_k, 60)
        self.assertEqual(config.table_retrieval_cap, 3)
        self.assertEqual(config.table_context_cap, 2)
        self.assertIsNotNone(config.table_chunks)
        self.assertIsNotNone(config.table_layout)
        self.assertIsNotNone(config.table_index)
        self.assertIsNone(config.correction_set)

    def test_rejects_mixed_or_unsupported_config_shapes(self) -> None:
        mixed = _config(schema_version="1.0")
        mixed["artifacts"]["correction_set"] = {
            "path": "private/corrections.json",
            "sha256": "6" * 64,
        }
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "invalid_runtime_artifacts"):
                load_runtime_config(self._write(directory, mixed))

        unsupported = _config(schema_version="9.9")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "unsupported_runtime_config_version"):
                load_runtime_config(self._write(directory, unsupported))

    def test_rejects_path_traversal(self) -> None:
        value = _config()
        value["artifacts"]["chunks"]["path"] = "../chunks.jsonl"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "invalid_chunk_artifact"):
                load_runtime_config(self._write(directory, value))

    def test_rejects_unknown_fields_and_invalid_retrieval_limits(self) -> None:
        value = _config()
        value["unexpected"] = True
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "invalid_runtime_config"):
                load_runtime_config(self._write(directory, value))
        value = _config()
        value["retrieval"]["context_top_k"] = 11
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "invalid_retrieval_context_limits"):
                load_runtime_config(self._write(directory, value))

        value = _dual_config()
        value["retrieval"]["table_context_cap"] = 4
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "invalid_retrieval_context_limits"):
                load_runtime_config(self._write(directory, value))


if __name__ == "__main__":
    unittest.main()
