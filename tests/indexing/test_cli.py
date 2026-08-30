from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from midprojectrag.cli import main
from midprojectrag.ingest.common import sha256_file, sha256_text, write_json, write_jsonl


class BaselineCliTests(unittest.TestCase):
    def test_local_query_rejects_external_ollama_url_before_file_access(self) -> None:
        captured = io.StringIO()
        with redirect_stdout(captured):
            code = main(
                [
                    "local-query",
                    "--data-dir",
                    "/tmp/data",
                    "--chunks",
                    "/tmp/data/missing-chunks.jsonl",
                    "--index-dir",
                    "/tmp/data/private/indexes/local/missing-index",
                    "--request",
                    "/tmp/data/missing-request.json",
                    "--output",
                    "/tmp/data/private/outputs/local/result.json",
                    "--cache-dir",
                    "/tmp/data/private/caches/local",
                    "--ollama-base-url",
                    "http://example.com:11434",
                ]
            )
        self.assertEqual(code, 8)
        self.assertEqual(
            json.loads(captured.getvalue())["error"],
            "ollama_loopback_url_required",
        )

    def test_tokenizer_cache_requires_explicit_static_download_confirmation(self) -> None:
        captured = io.StringIO()
        with patch("urllib.request.urlopen") as urlopen:
            with redirect_stdout(captured):
                code = main(["tokenizer-cache", "--data-dir", "/tmp/data"])
        self.assertEqual(code, 6)
        self.assertEqual(
            json.loads(captured.getvalue())["error"],
            "static_tokenizer_download_not_approved",
        )
        urlopen.assert_not_called()

    def test_chunk_builds_private_deterministic_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            blocks_dir = data_dir / "blocks"
            blocks_dir.mkdir()
            doc_id = "doc_0123456789abcdef01234567"
            text = "합성 제안요청서 본문"
            write_jsonl(
                data_dir / "manifest.jsonl",
                [{"doc_id": doc_id, "status": "ok", "index_eligible": True}],
            )
            write_jsonl(
                blocks_dir / f"{doc_id}.jsonl",
                [
                    {
                        "block_id": "block_0123456789abcdef01234567",
                        "doc_id": doc_id,
                        "sequence": 0,
                        "block_type": "page_text",
                        "section_path": [],
                        "page_start": 1,
                        "page_end": 1,
                        "text": text,
                        "content_sha256": sha256_text(text),
                        "retrieval_role": "primary",
                    }
                ],
            )
            output = data_dir / "chunks.jsonl"
            captured = io.StringIO()
            with redirect_stdout(captured):
                code = main(
                    [
                        "chunk",
                        "--data-dir",
                        str(data_dir),
                        "--manifest",
                        str(data_dir / "manifest.jsonl"),
                        "--blocks-dir",
                        str(blocks_dir),
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(code, 0)
            summary = json.loads(captured.getvalue())
            self.assertEqual(summary["chunks"], 1)
            self.assertEqual(summary["documents"], 1)
            self.assertNotIn(text, captured.getvalue())
            self.assertTrue(output.is_file())
            metadata = json.loads(
                output.with_name(f"{output.name}.metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["chunks"], 1)
            self.assertEqual(metadata["chunk_artifact_sha256"], summary["artifact_sha256"])

    def test_index_requires_explicit_corpus_egress_confirmation(self) -> None:
        captured = io.StringIO()
        with redirect_stdout(captured):
            code = main(
                [
                    "index",
                    "--data-dir",
                    "/tmp/data",
                    "--chunks",
                    "/tmp/data/chunks.jsonl",
                    "--output-dir",
                    "/tmp/data/index",
                    "--cache-dir",
                    "/tmp/data/cache",
                    "--budget-ledger",
                    "/tmp/data/budget.json",
                    "--manifest-sha256",
                    "0" * 64,
                ]
            )
        self.assertEqual(code, 6)
        self.assertEqual(json.loads(captured.getvalue())["error"], "external_corpus_egress_not_approved")

    def test_langfuse_requires_its_own_metadata_egress_confirmation(self) -> None:
        captured = io.StringIO()
        with redirect_stdout(captured):
            code = main(
                [
                    "query",
                    "--data-dir",
                    "/tmp/data",
                    "--chunks",
                    "/tmp/data/chunks.jsonl",
                    "--index-dir",
                    "/tmp/data/index",
                    "--request",
                    "/tmp/data/request.json",
                    "--output",
                    "/tmp/data/result.json",
                    "--cache-dir",
                    "/tmp/data/cache",
                    "--budget-ledger",
                    "/tmp/data/budget.json",
                    "--observability",
                    "langfuse",
                    "--approve-external-corpus-egress",
                ]
            )
        self.assertEqual(code, 7)
        self.assertEqual(json.loads(captured.getvalue())["error"], "langfuse_metadata_egress_not_approved")

    def test_langfuse_env_default_cannot_bypass_metadata_egress_confirmation(self) -> None:
        captured = io.StringIO()
        with patch.dict("os.environ", {"MIDPROJECTRAG_OBSERVABILITY": " LANGFUSE "}):
            with redirect_stdout(captured):
                code = main(
                    [
                        "query",
                        "--data-dir",
                        "/tmp/data",
                        "--chunks",
                        "/tmp/data/chunks.jsonl",
                        "--index-dir",
                        "/tmp/data/index",
                        "--request",
                        "/tmp/data/request.json",
                        "--output",
                        "/tmp/data/result.json",
                        "--cache-dir",
                        "/tmp/data/cache",
                        "--budget-ledger",
                        "/tmp/data/budget.json",
                        "--approve-external-corpus-egress",
                    ]
                )
        self.assertEqual(code, 7)
        self.assertEqual(json.loads(captured.getvalue())["error"], "langfuse_metadata_egress_not_approved")

    def test_safe_error_code_does_not_echo_path_or_provider_details(self) -> None:
        from midprojectrag.cli import _safe_error_code

        self.assertEqual(_safe_error_code(ValueError("safe_machine_code"), "fallback"), "safe_machine_code")
        self.assertEqual(
            _safe_error_code(RuntimeError("/private/source.hwp: restricted content"), "fallback"),
            "fallback",
        )

    def test_api_index_rejects_local_artifact_root_before_provider_init(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            captured = io.StringIO()
            with patch("midprojectrag.stacks.api.OpenAIEmbeddingProvider") as provider:
                with redirect_stdout(captured):
                    code = main(
                        [
                            "index",
                            "--data-dir",
                            str(data_dir),
                            "--chunks",
                            str(data_dir / "private/chunks.jsonl"),
                            "--output-dir",
                            str(data_dir / "private/indexes/local"),
                            "--cache-dir",
                            str(data_dir / "private/caches/api"),
                            "--budget-ledger",
                            str(data_dir / "private/api-budget.json"),
                            "--manifest-sha256",
                            "0" * 64,
                            "--approve-external-corpus-egress",
                        ]
                    )
            self.assertEqual(code, 6)
            self.assertEqual(
                json.loads(captured.getvalue())["error"],
                "api_index_output_outside_stack_root",
            )
            provider.assert_not_called()

    def test_local_index_rejects_api_artifact_root_before_provider_init(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            captured = io.StringIO()
            with patch("midprojectrag.stacks.local.LocalHashEmbeddingProvider") as provider:
                with redirect_stdout(captured):
                    code = main(
                        [
                            "local-index",
                            "--data-dir",
                            str(data_dir),
                            "--chunks",
                            str(data_dir / "private/chunks.jsonl"),
                            "--output-dir",
                            str(data_dir / "private/indexes/api"),
                            "--cache-dir",
                            str(data_dir / "private/caches/local"),
                            "--manifest-sha256",
                            "0" * 64,
                        ]
                    )
            self.assertEqual(code, 8)
            self.assertEqual(
                json.loads(captured.getvalue())["error"],
                "local_index_output_outside_stack_root",
            )
            provider.assert_not_called()

    def test_api_query_rejects_local_artifact_root_before_provider_init(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            captured = io.StringIO()
            with (
                patch("midprojectrag.stacks.api.OpenAIEmbeddingProvider") as embedding_provider,
                patch("midprojectrag.stacks.api.OpenAIGenerator") as generator,
                redirect_stdout(captured),
            ):
                code = main(
                    [
                        "query",
                        "--data-dir",
                        str(data_dir),
                        "--chunks",
                        str(data_dir / "private/chunks.jsonl"),
                        "--index-dir",
                        str(data_dir / "private/indexes/api"),
                        "--request",
                        str(data_dir / "private/request.json"),
                        "--output",
                        str(data_dir / "private/outputs/local/result.json"),
                        "--cache-dir",
                        str(data_dir / "private/caches/api"),
                        "--budget-ledger",
                        str(data_dir / "private/api-budget.json"),
                        "--observability",
                        "disabled",
                        "--approve-external-corpus-egress",
                    ]
                )
            self.assertEqual(code, 7)
            self.assertEqual(
                json.loads(captured.getvalue())["error"],
                "api_query_output_outside_stack_root",
            )
            embedding_provider.assert_not_called()
            generator.assert_not_called()

    def test_local_query_rejects_api_artifact_root_before_ollama_init(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            captured = io.StringIO()
            with patch("midprojectrag.stacks.local.OllamaGenerator") as generator:
                with redirect_stdout(captured):
                    code = main(
                        [
                            "local-query",
                            "--data-dir",
                            str(data_dir),
                            "--chunks",
                            str(data_dir / "private/chunks.jsonl"),
                            "--index-dir",
                            str(data_dir / "private/indexes/local"),
                            "--request",
                            str(data_dir / "private/request.json"),
                            "--output",
                            str(data_dir / "private/outputs/api/result.json"),
                            "--cache-dir",
                            str(data_dir / "private/caches/local"),
                        ]
                    )
            self.assertEqual(code, 8)
            self.assertEqual(
                json.loads(captured.getvalue())["error"],
                "local_query_output_outside_stack_root",
            )
            generator.assert_not_called()

    def test_index_rejects_chunk_sidecar_from_another_manifest_before_provider_init(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            blocks_dir = data_dir / "blocks"
            blocks_dir.mkdir()
            doc_id = "doc_0123456789abcdef01234567"
            text = "합성 본문"
            manifest = data_dir / "manifest.jsonl"
            chunks = data_dir / "chunks.jsonl"
            write_jsonl(
                manifest,
                [{"doc_id": doc_id, "status": "ok", "index_eligible": True}],
            )
            write_jsonl(
                blocks_dir / f"{doc_id}.jsonl",
                [
                    {
                        "block_id": "block_0123456789abcdef01234567",
                        "doc_id": doc_id,
                        "sequence": 0,
                        "block_type": "page_text",
                        "section_path": [],
                        "page_start": 1,
                        "page_end": 1,
                        "text": text,
                        "content_sha256": sha256_text(text),
                        "retrieval_role": "primary",
                    }
                ],
            )
            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(
                        [
                            "chunk",
                            "--data-dir",
                            str(data_dir),
                            "--manifest",
                            str(manifest),
                            "--blocks-dir",
                            str(blocks_dir),
                            "--output",
                            str(chunks),
                        ]
                    ),
                    0,
                )
            metadata_path = chunks.with_name(f"{chunks.name}.metadata.json")
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["source_manifest_sha256"] = "f" * 64
            write_json(metadata_path, metadata)
            captured = io.StringIO()
            with redirect_stdout(captured):
                code = main(
                    [
                        "index",
                        "--data-dir",
                        str(data_dir),
                        "--manifest",
                        str(manifest),
                        "--manifest-sha256",
                        sha256_file(manifest),
                        "--chunks",
                        str(chunks),
                        "--output-dir",
                        str(data_dir / "private/indexes/api"),
                        "--cache-dir",
                        str(data_dir / "private/caches/api"),
                        "--budget-ledger",
                        str(data_dir / "budget.json"),
                        "--approve-external-corpus-egress",
                    ]
                )
            self.assertEqual(code, 6)
            self.assertEqual(json.loads(captured.getvalue())["error"], "chunk_manifest_hash_mismatch")


if __name__ == "__main__":
    unittest.main()
