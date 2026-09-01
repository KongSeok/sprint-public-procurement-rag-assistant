from __future__ import annotations

import json
import unittest
from decimal import Decimal

import numpy as np

from midprojectrag.stacks.local.gcp_config import (
    KURE_DIMENSIONS,
    KURE_MAX_INPUT_TOKENS,
    KURE_MODEL_ID,
    KURE_MODEL_REVISION,
    KURE_POOLING,
    KURE_PROMPT_VERSION,
)
from midprojectrag.stacks.local.hf_embeddings import (
    HuggingFaceTokenCounter,
    KureEmbeddingProvider,
)


class _Tokenizer:
    def __init__(self, counts: dict[str, int] | None = None) -> None:
        self.counts = counts or {}
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __call__(self, text: str, **kwargs: object) -> dict[str, list[int]]:
        self.calls.append((text, dict(kwargs)))
        count = self.counts.get(text, max(1, len(text)))
        return {"input_ids": list(range(count))}


class _Encoder:
    def __init__(self, result: np.ndarray | None = None) -> None:
        self.result = result
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def encode(self, texts: list[str], **kwargs: object) -> np.ndarray:
        self.calls.append((list(texts), dict(kwargs)))
        if self.result is not None:
            return self.result
        matrix = np.zeros((len(texts), KURE_DIMENSIONS), dtype=np.float32)
        for index in range(len(texts)):
            matrix[index, 0] = float(index + 1)
            matrix[index, 1] = 1.0
        return matrix


class HuggingFaceEmbeddingTests(unittest.TestCase):
    def test_loaders_are_lazy_pinned_and_offline_only(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        tokenizer = _Tokenizer({"둘": 2, "하나": 3})
        encoder = _Encoder()

        def tokenizer_loader(**kwargs: object) -> _Tokenizer:
            events.append(("tokenizer", dict(kwargs)))
            return tokenizer

        def encoder_loader(**kwargs: object) -> _Encoder:
            events.append(("encoder", dict(kwargs)))
            return encoder

        provider = KureEmbeddingProvider(
            tokenizer_loader=tokenizer_loader,
            encoder_loader=encoder_loader,
            batch_size=2,
        )
        self.assertEqual(events, [])
        result = provider.embed(["둘", "하나"])

        self.assertEqual([name for name, _kwargs in events], ["tokenizer", "encoder"])
        tokenizer_kwargs = events[0][1]
        self.assertEqual(tokenizer_kwargs["pretrained_model_name_or_path"], KURE_MODEL_ID)
        self.assertEqual(tokenizer_kwargs["revision"], KURE_MODEL_REVISION)
        self.assertEqual(tokenizer_kwargs["local_files_only"], True)
        self.assertEqual(tokenizer_kwargs["trust_remote_code"], False)
        encoder_kwargs = events[1][1]
        self.assertEqual(encoder_kwargs["model_name_or_path"], KURE_MODEL_ID)
        self.assertEqual(encoder_kwargs["revision"], KURE_MODEL_REVISION)
        self.assertEqual(encoder_kwargs["local_files_only"], True)
        self.assertEqual(encoder_kwargs["trust_remote_code"], False)
        self.assertEqual(encoder.calls[0][0], ["둘", "하나"])
        self.assertEqual(
            encoder.calls[0][1],
            {
                "batch_size": 2,
                "convert_to_numpy": True,
                "normalize_embeddings": False,
                "prompt": "",
                "show_progress_bar": False,
            },
        )
        self.assertEqual(result.input_tokens, 5)
        self.assertEqual(np.asarray(result.vectors).shape, (2, 1024))
        self.assertEqual(np.asarray(result.vectors)[:, 0].tolist(), [1.0, 2.0])
        self.assertEqual(provider.estimate_cost(1000), Decimal("0"))

    def test_tokenizer_counts_special_tokens_without_truncation(self) -> None:
        tokenizer = _Tokenizer({"가나다": 4})
        counter = HuggingFaceTokenCounter(tokenizer=tokenizer)
        self.assertEqual(counter.count("가나다"), 4)
        self.assertEqual(
            tokenizer.calls,
            [
                (
                    "가나다",
                    {
                        "add_special_tokens": True,
                        "return_attention_mask": False,
                        "return_token_type_ids": False,
                        "truncation": False,
                    },
                )
            ],
        )

    def test_over_limit_input_is_rejected_before_encoder_call(self) -> None:
        tokenizer = _Tokenizer({"too-long": KURE_MAX_INPUT_TOKENS + 1})
        encoder = _Encoder()
        provider = KureEmbeddingProvider(tokenizer=tokenizer, encoder=encoder)
        with self.assertRaisesRegex(ValueError, "embedding_input_token_limit_exceeded"):
            provider.embed(["too-long"])
        self.assertEqual(encoder.calls, [])

    def test_invalid_shape_and_non_finite_vectors_fail_closed(self) -> None:
        tokenizer = _Tokenizer({"a": 1})
        cases = (
            (
                np.ones((1, KURE_DIMENSIONS - 1), dtype=np.float32),
                "embedding_shape_mismatch",
            ),
            (
                np.full((1, KURE_DIMENSIONS), np.nan, dtype=np.float32),
                "embedding_non_finite",
            ),
        )
        for vectors, error_code in cases:
            with self.subTest(error_code=error_code):
                provider = KureEmbeddingProvider(
                    tokenizer=tokenizer,
                    encoder=_Encoder(vectors),
                )
                with self.assertRaisesRegex(ValueError, error_code):
                    provider.embed(["a"])

    def test_model_and_revision_are_exactly_allowlisted(self) -> None:
        with self.assertRaisesRegex(ValueError, "embedding_model_not_allowlisted"):
            KureEmbeddingProvider(model="other/model", tokenizer=_Tokenizer(), encoder=_Encoder())
        with self.assertRaisesRegex(ValueError, "embedding_revision_not_allowlisted"):
            KureEmbeddingProvider(revision="main", tokenizer=_Tokenizer(), encoder=_Encoder())
        with self.assertRaisesRegex(ValueError, "local_files_only_required"):
            KureEmbeddingProvider(
                local_files_only=False,
                tokenizer=_Tokenizer(),
                encoder=_Encoder(),
            )
        with self.assertRaisesRegex(ValueError, "trust_remote_code_not_allowed"):
            KureEmbeddingProvider(
                trust_remote_code=True,
                tokenizer=_Tokenizer(),
                encoder=_Encoder(),
            )

    def test_cache_namespace_records_role_revision_pooling_and_prompt(self) -> None:
        provider = KureEmbeddingProvider(tokenizer=_Tokenizer(), encoder=_Encoder())
        document = json.loads(provider.cache_namespace(role="document"))
        query = json.loads(provider.cache_namespace(role="query"))
        self.assertEqual(document["model"], KURE_MODEL_ID)
        self.assertEqual(document["revision"], KURE_MODEL_REVISION)
        self.assertEqual(document["pooling"], KURE_POOLING)
        self.assertEqual(document["prompt_version"], KURE_PROMPT_VERSION)
        self.assertEqual(document["prompt"], "")
        self.assertEqual(document["role"], "document")
        self.assertEqual(query["role"], "query")
        self.assertNotEqual(document, query)
        with self.assertRaisesRegex(ValueError, "embedding_role_not_supported"):
            provider.cache_namespace(role="other")


if __name__ == "__main__":
    unittest.main()
