from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import numpy as np

from midprojectrag.ingest.common import canonical_json, sha256_text
from midprojectrag.indexing.budget import BudgetLedger
from midprojectrag.indexing.embeddings import (
    EmbeddingBatch,
    EmbeddingCache,
    embed_query,
    embed_chunks,
    embedding_cache_namespace,
)


class _Counter:
    def count(self, text: str) -> int:
        return len(text)


class _FakeProvider:
    model = "fake-embedding"
    dimensions = 3
    requires_budget = False
    max_input_tokens = 8191

    def __init__(self) -> None:
        self.calls = 0
        self.input_count = 0

    def embed(self, texts):
        self.calls += 1
        self.input_count += len(texts)
        return EmbeddingBatch(
            vectors=[[float(len(text)), 1.0, float(index + 1)] for index, text in enumerate(texts)],
            input_tokens=sum(map(len, texts)),
        )

    def estimate_cost(self, input_tokens):
        return Decimal("0")


class _ProviderWithoutInputLimit:
    model = "missing-limit"
    dimensions = 3
    requires_budget = False

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return EmbeddingBatch(vectors=[[1.0, 0.0, 0.0] for _ in texts], input_tokens=1)

    def estimate_cost(self, input_tokens):
        return Decimal("0")


class _NamespacedProvider(_FakeProvider):
    def __init__(self) -> None:
        super().__init__()
        self.roles: list[str] = []

    def cache_namespace(self, *, role: str) -> str:
        self.roles.append(role)
        return f"hf-namespace:{role}"


def _chunks() -> list[dict[str, object]]:
    config_hash = "1" * 64
    chunks: list[dict[str, object]] = []
    for index, text in enumerate(("가나다", "라마바"), start=1):
        doc_id = "doc_0123456789abcdef01234567"
        block_id = f"block_{index:024x}"
        content_hash = sha256_text(text)
        identity = {
            "block_id": block_id,
            "config_sha256": config_hash,
            "content_sha256": content_hash,
            "doc_id": doc_id,
            "page_end": index,
            "page_start": index,
            "part_count": 1,
            "part_index": 0,
        }
        chunks.append(
            {
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
                "content_sha256": content_hash,
                "config_sha256": config_hash,
            }
        )
    return chunks


class EmbeddingTests(unittest.TestCase):
    def test_legacy_provider_cache_namespace_is_byte_identical_model_fallback(self) -> None:
        provider = _FakeProvider()
        self.assertEqual(
            embedding_cache_namespace(provider, role="document"),
            provider.model,
        )
        expected = EmbeddingCache.key(
            corpus_manifest_sha256="1" * 64,
            chunk_config_sha256="2" * 64,
            model=provider.model,
            dimensions=provider.dimensions,
            content_sha256="3" * 64,
        )
        actual = EmbeddingCache.key(
            corpus_manifest_sha256="1" * 64,
            chunk_config_sha256="2" * 64,
            model=embedding_cache_namespace(provider, role="document"),
            dimensions=provider.dimensions,
            content_sha256="3" * 64,
        )
        self.assertEqual(actual, expected)

    def test_chunk_and_query_paths_request_distinct_cache_roles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider = _NamespacedProvider()
            cache = EmbeddingCache(Path(directory))
            embed_chunks(
                _chunks(),
                provider=provider,
                counter=_Counter(),
                cache=cache,
                corpus_manifest_sha256="2" * 64,
            )
            embed_query(
                "질문",
                provider=provider,
                counter=_Counter(),
                cache=cache,
                corpus_manifest_sha256="2" * 64,
            )
        self.assertEqual(provider.roles, ["document", "query"])

    def test_negative_batch_interval_fails_before_provider_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider = _FakeProvider()
            with self.assertRaisesRegex(ValueError, "invalid_embedding_batch_interval"):
                embed_chunks(
                    _chunks(),
                    provider=provider,
                    counter=_Counter(),
                    cache=EmbeddingCache(Path(directory)),
                    corpus_manifest_sha256="2" * 64,
                    batch_interval_seconds=-1,
                )
            self.assertEqual(provider.calls, 0)

    def test_provider_input_limit_is_required_without_shared_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider = _ProviderWithoutInputLimit()
            with self.assertRaisesRegex(ValueError, "invalid_embedding_input_limit"):
                embed_chunks(
                    _chunks(),
                    provider=provider,  # type: ignore[arg-type]
                    counter=_Counter(),
                    cache=EmbeddingCache(Path(directory)),
                    corpus_manifest_sha256="2" * 64,
                )
            self.assertEqual(provider.calls, 0)

    def test_cache_prevents_second_provider_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider = _FakeProvider()
            cache = EmbeddingCache(Path(directory))
            first = embed_chunks(
                _chunks(),
                provider=provider,
                counter=_Counter(),
                cache=cache,
                corpus_manifest_sha256="2" * 64,
            )
            second = embed_chunks(
                _chunks(),
                provider=provider,
                counter=_Counter(),
                cache=cache,
                corpus_manifest_sha256="2" * 64,
            )
            self.assertEqual(provider.calls, 1)
            self.assertEqual((first.cache_hits, first.cache_misses), (0, 2))
            self.assertEqual((second.cache_hits, second.cache_misses), (2, 0))
            np.testing.assert_allclose(first.vectors, second.vectors)
            np.testing.assert_allclose(np.linalg.norm(first.vectors, axis=1), np.ones(2))

    def test_same_content_is_embedded_once_then_fanned_out(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            chunks = _chunks()
            duplicate_content = dict(chunks[0])
            duplicate_content["doc_id"] = "doc_1123456789abcdef01234567"
            duplicate_content["source_block_ids"] = ["block_1123456789abcdef01234567"]
            duplicate_content["page_start"] = 9
            duplicate_content["page_end"] = 9
            identity = {
                "block_id": duplicate_content["source_block_ids"][0],
                "config_sha256": duplicate_content["config_sha256"],
                "content_sha256": duplicate_content["content_sha256"],
                "doc_id": duplicate_content["doc_id"],
                "page_end": 9,
                "page_start": 9,
                "part_count": 1,
                "part_index": 0,
            }
            duplicate_content["chunk_id"] = (
                f"chunk_{sha256_text(canonical_json(identity))[:24]}"
            )
            provider = _FakeProvider()
            result = embed_chunks(
                [chunks[0], duplicate_content],
                provider=provider,
                counter=_Counter(),
                cache=EmbeddingCache(Path(directory)),
                corpus_manifest_sha256="2" * 64,
            )
            self.assertEqual(provider.input_count, 1)
            self.assertEqual(result.cache_misses, 2)
            np.testing.assert_allclose(result.vectors[0], result.vectors[1])


class BudgetTests(unittest.TestCase):
    def test_reservation_hard_stop_happens_before_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = BudgetLedger(Path(directory) / "budget.json", limit_usd="0.01")
            reservation = ledger.reserve("0.006", "first")
            with self.assertRaisesRegex(ValueError, "budget_limit_exceeded"):
                ledger.reserve("0.005", "second")
            ledger.commit(reservation, "0.004")
            snapshot = ledger.snapshot()
            self.assertEqual(snapshot.committed_usd, Decimal("0.004000000"))
            self.assertEqual(snapshot.available_usd, Decimal("0.006000000"))

    def test_release_restores_available_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = BudgetLedger(Path(directory) / "budget.json", limit_usd=1)
            reservation = ledger.reserve("0.4", "failed-call")
            ledger.release(reservation)
            self.assertEqual(ledger.snapshot().available_usd, Decimal("1.000000000"))

    def test_estimate_miss_does_not_freeze_ledger_when_total_is_within_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = BudgetLedger(Path(directory) / "budget.json", limit_usd=1)
            reservation = ledger.reserve("0.1", "under-estimated")
            ledger.commit(reservation, "0.11")
            next_reservation = ledger.reserve("0.2", "next-call")
            ledger.release(next_reservation)
            snapshot = ledger.snapshot()
            self.assertFalse(snapshot.breached)
            self.assertEqual(snapshot.committed_usd, Decimal("0.110000000"))


if __name__ == "__main__":
    unittest.main()
