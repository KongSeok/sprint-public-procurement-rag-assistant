from __future__ import annotations

import unittest

from midprojectrag.stacks.local.gcp_config import (
    KURE_DIMENSIONS,
    KURE_DOCUMENT_PROMPT,
    KURE_MAX_INPUT_TOKENS,
    KURE_MODEL_ID,
    KURE_MODEL_REVISION,
    KURE_POOLING,
    KURE_PROMPT_VERSION,
    KURE_QUERY_PROMPT,
    build_gcp_index_config,
    gcp_config_sha256,
)


class GcpConfigTests(unittest.TestCase):
    def _build(self, **overrides: object) -> dict[str, object]:
        arguments: dict[str, object] = {
            "corpus_manifest_sha256": "1" * 64,
            "chunk_artifact_sha256": "2" * 64,
            "chunk_config_sha256": "3" * 64,
            "embedding_model": KURE_MODEL_ID,
            "embedding_revision": KURE_MODEL_REVISION,
            "embedding_dimensions": KURE_DIMENSIONS,
            "embedding_max_input_tokens": KURE_MAX_INPUT_TOKENS,
            "pooling": KURE_POOLING,
            "prompt_version": KURE_PROMPT_VERSION,
            "document_prompt": KURE_DOCUMENT_PROMPT,
            "query_prompt": KURE_QUERY_PROMPT,
            "index_engine": "faiss",
            "batch_size": 32,
        }
        arguments.update(overrides)
        return build_gcp_index_config(**arguments)  # type: ignore[arg-type]

    def test_index_config_records_the_exact_pinned_kure_identity(self) -> None:
        config = self._build()
        self.assertEqual(config["stack_id"], "gcp_local")
        self.assertEqual(config["embedding_model"], "nlpai-lab/KURE-v1")
        self.assertEqual(
            config["embedding_revision"],
            "4ed4540949c70b7da2c74004a915e1f2d5e46e4f",
        )
        self.assertEqual(config["embedding_dimensions"], 1024)
        self.assertEqual(config["embedding_max_input_tokens"], 8192)
        self.assertEqual(config["normalization"], "float32_l2")
        self.assertEqual(config["local_files_only"], True)
        self.assertEqual(config["trust_remote_code"], False)
        self.assertEqual(config["document_prompt"], "")
        self.assertEqual(config["query_prompt"], "")

    def test_index_config_rejects_every_identity_drift(self) -> None:
        cases = (
            ({"embedding_model": "other/model"}, "embedding_model_not_allowlisted"),
            ({"embedding_revision": "main"}, "embedding_revision_not_allowlisted"),
            ({"embedding_dimensions": 768}, "invalid_embedding_dimensions"),
            ({"embedding_max_input_tokens": 8191}, "invalid_embedding_input_limit"),
            ({"pooling": "mean"}, "embedding_pooling_not_allowlisted"),
            ({"prompt_version": "other"}, "embedding_prompt_version_not_allowlisted"),
            ({"document_prompt": "passage: "}, "embedding_prompt_not_allowlisted"),
            ({"query_prompt": "query: "}, "embedding_prompt_not_allowlisted"),
            ({"index_engine": "numpy"}, "unsupported_index_engine"),
            ({"batch_size": 0}, "invalid_embedding_batch_size"),
        )
        for overrides, error_code in cases:
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(ValueError, error_code):
                    self._build(**overrides)

    def test_config_hash_is_canonical_and_content_sensitive(self) -> None:
        first = self._build()
        reordered = dict(reversed(list(first.items())))
        self.assertEqual(gcp_config_sha256(first), gcp_config_sha256(reordered))
        changed = dict(first, batch_size=16)
        self.assertNotEqual(gcp_config_sha256(first), gcp_config_sha256(changed))


if __name__ == "__main__":
    unittest.main()
