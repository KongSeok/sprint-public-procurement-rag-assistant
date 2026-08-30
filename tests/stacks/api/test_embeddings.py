from __future__ import annotations

import hashlib
import tempfile
import unittest
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from midprojectrag.ingest.common import sha256_text
from midprojectrag.stacks.api import (
    OpenAIEmbeddingProvider,
    TIKTOKEN_ASSETS,
    TiktokenCounter,
    warm_tiktoken_cache,
)


class ApiEmbeddingTests(unittest.TestCase):
    def test_model_specs_keep_assignment_small_and_personal_large_distinct(self) -> None:
        small = OpenAIEmbeddingProvider(client=object())
        self.assertEqual(small.dimensions, 1536)
        self.assertEqual(small.estimate_cost(1_000_000), Decimal("0.020000000"))
        with self.assertRaisesRegex(ValueError, "embedding_model_not_allowlisted"):
            OpenAIEmbeddingProvider(
                client=object(),
                model="text-embedding-3-large",
            )

        large = OpenAIEmbeddingProvider(
            client=object(),
            model="text-embedding-3-large",
            api_profile="personal_experimental",
        )
        self.assertEqual(large.dimensions, 3072)
        self.assertEqual(large.estimate_cost(1_000_000), Decimal("0.130000000"))
        with self.assertRaisesRegex(ValueError, "invalid_embedding_dimensions"):
            OpenAIEmbeddingProvider(
                client=object(),
                model="text-embedding-3-large",
                dimensions=3073,
                api_profile="personal_experimental",
            )

    def test_tiktoken_counter_fails_closed_without_implicit_download(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch("urllib.request.urlopen") as urlopen:
                with self.assertRaisesRegex(RuntimeError, "tiktoken_encoding_cache_missing"):
                    TiktokenCounter(cache_dir=Path(directory))
            urlopen.assert_not_called()

    def test_tiktoken_counter_reads_verified_bytes_without_hidden_cache_io(self) -> None:
        payload = b"YQ== 0\nYg== 1\n"
        expected_hash = hashlib.sha256(payload).hexdigest()
        url = "https://example.invalid/cl100k_base.tiktoken"
        cache_key = hashlib.sha1(url.encode("utf-8")).hexdigest()
        asset = (url, expected_hash, len(payload))
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            for directory in (Path(first), Path(second)):
                (directory / cache_key).write_bytes(payload)
            with patch.dict(TIKTOKEN_ASSETS, {"cl100k_base": asset}, clear=True):
                with patch("tiktoken.load.read_file_cached") as generic_loader:
                    with patch("urllib.request.urlopen") as urlopen:
                        self.assertEqual(TiktokenCounter(cache_dir=Path(first)).count("ab"), 2)
                        self.assertEqual(TiktokenCounter(cache_dir=Path(second)).count("ab"), 2)
            generic_loader.assert_not_called()
            urlopen.assert_not_called()

    def test_tokenizer_warmup_hash_verifies_before_atomic_write(self) -> None:
        payload = b"synthetic tokenizer vocabulary"
        expected_hash = sha256_text(payload.decode("ascii"))

        @contextmanager
        def fake_response():
            yield SimpleNamespace(read=lambda _limit: payload)

        assets = {
            "synthetic": (
                "https://example.invalid/synthetic.tiktoken",
                expected_hash,
                len(payload),
            )
        }
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(TIKTOKEN_ASSETS, assets, clear=True):
                with patch("urllib.request.urlopen", return_value=fake_response()):
                    result = warm_tiktoken_cache(Path(directory))
            self.assertEqual(result, {"synthetic": expected_hash})
            files = list(Path(directory).iterdir())
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].read_bytes(), payload)

    def test_tokenizer_warmup_rejects_unpinned_and_oversized_payload(self) -> None:
        @contextmanager
        def unexpected_response():
            yield SimpleNamespace(read=lambda _limit: b"unexpected")

        @contextmanager
        def oversized_response():
            yield SimpleNamespace(read=lambda limit: b"x" * limit)

        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                TIKTOKEN_ASSETS,
                {"synthetic": ("https://example.invalid/tokenizer", "0" * 64, 64)},
                clear=True,
            ):
                with patch("urllib.request.urlopen", return_value=unexpected_response()):
                    with self.assertRaisesRegex(ValueError, "tokenizer_asset_hash_mismatch"):
                        warm_tiktoken_cache(Path(directory))
            self.assertEqual(list(Path(directory).iterdir()), [])
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                TIKTOKEN_ASSETS,
                {"synthetic": ("https://example.invalid/tokenizer", "0" * 64, 8)},
                clear=True,
            ):
                with patch("urllib.request.urlopen", return_value=oversized_response()):
                    with self.assertRaisesRegex(ValueError, "tokenizer_asset_too_large"):
                        warm_tiktoken_cache(Path(directory))
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_openai_adapter_validates_allowlist_and_orders_response(self) -> None:
        response = SimpleNamespace(
            data=[
                SimpleNamespace(index=1, embedding=[0.0, 1.0]),
                SimpleNamespace(index=0, embedding=[1.0, 0.0]),
            ],
            usage=SimpleNamespace(total_tokens=4),
        )
        provider = OpenAIEmbeddingProvider(
            client=SimpleNamespace(
                embeddings=SimpleNamespace(create=lambda **_kwargs: response)
            ),
            dimensions=2,
        )
        result = provider.embed(["a", "b"])
        self.assertEqual(result.vectors, [[1.0, 0.0], [0.0, 1.0]])
        self.assertEqual(result.input_tokens, 4)
        with self.assertRaisesRegex(ValueError, "embedding_model_not_allowlisted"):
            OpenAIEmbeddingProvider(client=object(), model="other")

        duplicate_response = SimpleNamespace(
            data=[
                SimpleNamespace(index=0, embedding=[1.0, 0.0]),
                SimpleNamespace(index=0, embedding=[0.0, 1.0]),
            ],
            usage=SimpleNamespace(total_tokens=4),
        )
        duplicate_provider = OpenAIEmbeddingProvider(
            client=SimpleNamespace(
                embeddings=SimpleNamespace(create=lambda **_kwargs: duplicate_response)
            ),
            dimensions=2,
        )
        with self.assertRaisesRegex(ValueError, "embedding_response_index_mismatch"):
            duplicate_provider.embed(["a", "b"])


if __name__ == "__main__":
    unittest.main()
