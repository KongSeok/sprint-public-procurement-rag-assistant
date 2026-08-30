from __future__ import annotations

import unittest

from midprojectrag.stacks.api import (
    api_config_sha256,
    build_api_index_config,
    build_api_run_config,
)


class ApiConfigTests(unittest.TestCase):
    def _index(self, model: str, dimensions: int) -> dict[str, object]:
        return build_api_index_config(
            api_profile="personal_experimental",
            corpus_manifest_sha256="1" * 64,
            chunk_artifact_sha256="2" * 64,
            chunk_config_sha256="3" * 64,
            embedding_model=model,
            embedding_dimensions=dimensions,
            index_engine="numpy",
            batch_size=128,
        )

    def test_four_run_hashes_are_unique_while_generators_share_each_index(self) -> None:
        index_hashes = {
            model: api_config_sha256(self._index(model, dimensions))
            for model, dimensions in (
                ("text-embedding-3-small", 1536),
                ("text-embedding-3-large", 3072),
            )
        }
        self.assertEqual(len(set(index_hashes.values())), 2)
        run_hashes = set()
        for index_hash in index_hashes.values():
            for generator in ("gpt-5-nano", "gpt-5-mini"):
                config = build_api_run_config(
                    index_config_sha256=index_hash,
                    generator_model=generator,
                    retrieval_top_k=10,
                    context_top_k=5,
                    max_output_tokens=1200,
                    max_citations=5,
                )
                self.assertEqual(config["reasoning_effort"], "minimal")
                self.assertEqual(config["case_interval_seconds"], 6.0)
                self.assertEqual(config["sdk_max_retries"], 2)
                self.assertEqual(config["response_schema_version"], "1.2")
                run_hashes.add(api_config_sha256(config))
        self.assertEqual(len(run_hashes), 4)

    def test_run_config_rejects_reasoning_and_interval_drift(self) -> None:
        arguments = {
            "index_config_sha256": "1" * 64,
            "generator_model": "gpt-5-mini",
            "retrieval_top_k": 10,
            "context_top_k": 5,
            "max_output_tokens": 1200,
            "max_citations": 3,
        }
        with self.assertRaisesRegex(ValueError, "reasoning_effort_not_supported"):
            build_api_run_config(**arguments, reasoning_effort="low")
        with self.assertRaisesRegex(ValueError, "invalid_case_interval_seconds"):
            build_api_run_config(**arguments, case_interval_seconds=-1)
        with self.assertRaisesRegex(ValueError, "prompt_version_not_allowlisted"):
            build_api_run_config(**arguments, prompt_version="unknown")

    def test_table_prompt_version_is_explicit_without_changing_legacy_default(self) -> None:
        arguments = {
            "index_config_sha256": "1" * 64,
            "generator_model": "gpt-5-mini",
            "retrieval_top_k": 10,
            "context_top_k": 5,
            "max_output_tokens": 1200,
            "max_citations": 3,
        }
        self.assertEqual(
            build_api_run_config(**arguments)["prompt_version"],
            "api-b0-page-v1",
        )
        self.assertEqual(
            build_api_run_config(
                **arguments,
                prompt_version="api-b1-page-table-v1",
            )["prompt_version"],
            "api-b1-page-table-v1",
        )

    def test_assignment_profile_rejects_large(self) -> None:
        with self.assertRaisesRegex(ValueError, "embedding_model_not_allowlisted"):
            build_api_index_config(
                api_profile="assignment",
                corpus_manifest_sha256="1" * 64,
                chunk_artifact_sha256="2" * 64,
                chunk_config_sha256="3" * 64,
                embedding_model="text-embedding-3-large",
                embedding_dimensions=None,
                index_engine="numpy",
                batch_size=128,
            )


if __name__ == "__main__":
    unittest.main()
