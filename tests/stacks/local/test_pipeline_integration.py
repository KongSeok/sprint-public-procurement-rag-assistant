from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import numpy as np

from midprojectrag.answering.pipeline import RagPipeline
from midprojectrag.cli import main
from midprojectrag.ingest.common import (
    canonical_json,
    sha256_file,
    sha256_text,
    write_json,
    write_jsonl,
)
from midprojectrag.indexing.embeddings import EmbeddingCache
from midprojectrag.indexing.exact_index import ExactDenseIndex
from midprojectrag.stacks.local import (
    OLLAMA_MODEL_DIGESTS,
    LocalHashEmbeddingProvider,
    LocalTextCounter,
    OllamaGenerator,
)


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = json.dumps(payload).encode("utf-8")

    def read(self, limit: int) -> bytes:
        return self.payload[:limit]

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:  # type: ignore[no-untyped-def]
        return False


class _Opener:
    def __init__(self, plan: dict[str, object]) -> None:
        self.calls = 0
        self.payloads = [
            {
                "models": [
                    {
                        "name": "qwen3.8:27b-mlx",
                        "model": "qwen3.8:27b-mlx",
                        "digest": OLLAMA_MODEL_DIGESTS["qwen3.8:27b-mlx"],
                        "capabilities": ["completion"],
                    }
                ]
            },
            {
                "model": "qwen3.8:27b-mlx",
                "message": {"content": json.dumps(plan)},
                "prompt_eval_count": 20,
                "eval_count": 8,
                "done": True,
                "done_reason": "stop",
            },
        ]

    def open(self, request, timeout):  # type: ignore[no-untyped-def]
        payload = self.payloads[self.calls]
        self.calls += 1
        return _Response(payload)


class _CliGenerator:
    model = "qwen3.8:27b-mlx"
    model_digest = OLLAMA_MODEL_DIGESTS[model]
    requires_budget = False
    seed = 0
    temperature = 0

    def __init__(
        self,
        plan: dict[str, object],
        *,
        max_output_tokens: int,
        context_tokens: int,
    ) -> None:
        self.plan = plan
        self.max_output_tokens = max_output_tokens
        self.context_tokens = context_tokens

    def generate(self, _prompt: str):  # type: ignore[no-untyped-def]
        return self.plan, 20, 8


def _chunk(index: int, text: str) -> dict[str, object]:
    doc_id = f"doc_{index:024x}"
    block_id = f"block_{index:024x}"
    config_sha256 = "1" * 64
    content_sha256 = sha256_text(text)
    identity = {
        "block_id": block_id,
        "config_sha256": config_sha256,
        "content_sha256": content_sha256,
        "doc_id": doc_id,
        "page_end": 1,
        "page_start": 1,
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
        "page_start": 1,
        "page_end": 1,
        "part_index": 0,
        "part_count": 1,
        "retrieval_role": "primary",
        "chunker_id": "page-v1",
        "config_sha256": config_sha256,
        "content_sha256": content_sha256,
    }


def _request(doc_ids: list[str] | None = None) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "request_id": "local-smoke-1",
        "question": "재생에너지 지원센터 용역비용은?",
        "history": [],
        "document_scope": {
            "mode": "explicit" if doc_ids is not None else "all",
            "doc_ids": doc_ids or [],
        },
        "options": {"max_citations": 3},
    }


class LocalPipelineIntegrationTests(unittest.TestCase):
    def _pipeline(self, plan: dict[str, object], opener: _Opener) -> RagPipeline:
        chunks = [
            _chunk(1, "기업 재생에너지 지원센터 용역비용은 57,000,000원입니다."),
            _chunk(2, "중이온가속기 극저온 냉각 시스템 운영 용역"),
        ]
        provider = LocalHashEmbeddingProvider()
        vectors = np.asarray(provider.embed([row["text"] for row in chunks]).vectors)
        self.chunks = chunks
        return RagPipeline(
            index=ExactDenseIndex(chunks, vectors, engine="numpy"),
            embedding_provider=provider,
            embedding_counter=LocalTextCounter(),
            query_cache=EmbeddingCache(Path(self.temporary.name) / "cache"),
            generator=OllamaGenerator(max_output_tokens=100, opener=opener),
            generation_counter=LocalTextCounter(),
            budget=None,
            corpus_manifest_sha256="2" * 64,
            stack_id="mac_local_experimental",
            retrieval_top_k=2,
            context_top_k=2,
        )

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_answered_and_abstained_paths_keep_shared_contract(self) -> None:
        preview = _chunk(1, "기업 재생에너지 지원센터 용역비용은 57,000,000원입니다.")
        answered = {
            "status": "answered",
            "answer": "용역비용은 57,000,000원입니다.",
            "citation_chunk_ids": [preview["chunk_id"]],
            "abstention_reason": None,
        }
        opener = _Opener(answered)
        result = self._pipeline(answered, opener).query(_request())
        self.assertEqual(result.response["status"], "answered")
        self.assertEqual(result.response["citations"][0]["chunk_id"], preview["chunk_id"])
        self.assertEqual(opener.calls, 2)

        abstained = {
            "status": "abstained",
            "answer": "",
            "citation_chunk_ids": [],
            "abstention_reason": "insufficient_evidence",
        }
        result = self._pipeline(abstained, _Opener(abstained)).query(_request())
        self.assertEqual(result.response["status"], "abstained")

    def test_unknown_explicit_scope_never_calls_ollama(self) -> None:
        plan = {
            "status": "abstained",
            "answer": "",
            "citation_chunk_ids": [],
            "abstention_reason": "insufficient_evidence",
        }
        opener = _Opener(plan)
        result = self._pipeline(plan, opener).query(_request(["doc_ffffffffffffffffffffffff"]))
        self.assertEqual(result.response["status"], "abstained")
        self.assertEqual(opener.calls, 0)

    def test_local_cli_output_records_text_free_reproducibility_metadata(self) -> None:
        data_dir = Path(self.temporary.name)
        chunks = [_chunk(1, "기업 재생에너지 지원센터 용역비용은 57,000,000원입니다.")]
        chunks_path = data_dir / "private" / "chunks.jsonl"
        write_jsonl(chunks_path, chunks)
        provider = LocalHashEmbeddingProvider()
        vectors = np.asarray(provider.embed([chunks[0]["text"]]).vectors)
        index_dir = data_dir / "private" / "indexes" / "local"
        metadata = ExactDenseIndex(chunks, vectors, engine="numpy").save(
            index_dir,
            corpus_manifest_sha256="2" * 64,
            embedding_model=provider.model,
        )
        request_path = data_dir / "private" / "requests" / "local" / "request.json"
        write_json(request_path, _request())
        output_path = data_dir / "private" / "outputs" / "local" / "result.json"
        plan = {
            "status": "answered",
            "answer": "용역비용은 57,000,000원입니다.",
            "citation_chunk_ids": [chunks[0]["chunk_id"]],
            "abstention_reason": None,
        }
        generator = _CliGenerator(plan, max_output_tokens=100, context_tokens=4096)
        captured = io.StringIO()
        with patch(
            "midprojectrag.stacks.local.OllamaGenerator",
            return_value=generator,
        ) as generator_constructor:
            with redirect_stdout(captured):
                code = main(
                    [
                        "local-query",
                        "--data-dir",
                        str(data_dir),
                        "--chunks",
                        str(chunks_path),
                        "--index-dir",
                        str(index_dir),
                        "--request",
                        str(request_path),
                        "--output",
                        str(output_path),
                        "--cache-dir",
                        str(data_dir / "private" / "caches" / "local"),
                        "--ollama-base-url",
                        "http://127.0.0.1:11435",
                        "--max-output-tokens",
                        "100",
                        "--context-tokens",
                        "4096",
                        "--retrieval-top-k",
                        "1",
                        "--context-top-k",
                        "1",
                    ]
                )
        self.assertEqual(code, 0)
        generator_constructor.assert_called_once_with(
            model="qwen3.8:27b-mlx",
            base_url="http://127.0.0.1:11435",
            max_output_tokens=100,
            context_tokens=4096,
            timeout_seconds=180.0,
        )
        artifact = json.loads(output_path.read_text(encoding="utf-8"))
        reproducibility = artifact["reproducibility"]
        self.assertEqual(reproducibility["corpus_manifest_sha256"], "2" * 64)
        self.assertEqual(reproducibility["chunk_artifact_sha256"], metadata["chunk_artifact_sha256"])
        self.assertEqual(reproducibility["chunk_config_sha256"], metadata["chunk_config_sha256"])
        self.assertEqual(
            reproducibility["index_metadata_sha256"],
            sha256_file(index_dir / "metadata.json"),
        )
        self.assertEqual(reproducibility["index_vectors_sha256"], metadata["vectors_sha256"])
        self.assertEqual(reproducibility["index_rows_sha256"], metadata["rows_sha256"])
        query_config = reproducibility["query_config"]
        self.assertEqual(
            query_config,
            {
                "schema_version": "1.0",
                "stack_id": "mac_local_experimental",
                "embedding_model": "local-hash-char-v1",
                "generator_model": "qwen3.8:27b-mlx",
                "generator_model_digest": OLLAMA_MODEL_DIGESTS["qwen3.8:27b-mlx"],
                "seed": 0,
                "temperature": 0,
                "num_ctx": 4096,
                "max_output_tokens": 100,
                "retrieval_top_k": 1,
                "context_top_k": 1,
            },
        )
        expected_config_sha256 = hashlib.sha256(
            json.dumps(
                query_config,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(reproducibility["query_config_sha256"], expected_config_sha256)
        self.assertEqual(
            json.loads(captured.getvalue())["query_config_sha256"],
            expected_config_sha256,
        )
        self.assertNotIn(chunks[0]["text"], json.dumps(reproducibility, ensure_ascii=False))
        self.assertNotIn(_request()["question"], captured.getvalue())


if __name__ == "__main__":
    unittest.main()
