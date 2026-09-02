from __future__ import annotations

import builtins
from decimal import Decimal
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from midprojectrag.orchestration.llm import LocalJSONBackend
from midprojectrag.orchestration.local_runtime import (
    DeadlineGenerator, KURE_REVISION, compose_retriever, legacy_paths, verify_snapshot,
)
from midprojectrag.retrieval import Candidate
from tests.orchestration.test_controller import fixture


class CompositionTests(unittest.TestCase):
    def setUp(self):
        self.store, self.pages, self.children, self.table = fixture()

    def test_lexical_composition_never_imports_or_constructs_model_provider(self):
        original_import = builtins.__import__
        blocked = ("transformers", "sentence_transformers", "huggingface_hub",
                   "midprojectrag.stacks.local.hf_embeddings", "midprojectrag.retrieval.legacy_page")
        def guarded_import(name, *args, **kwargs):
            if any(name == prefix or name.startswith(prefix + ".") for prefix in blocked):
                raise AssertionError("lexical path activated an optional model")
            return original_import(name, *args, **kwargs)
        calls = []
        with patch("builtins.__import__", side_effect=guarded_import):
            retriever, provenance = compose_retriever(self.store, source_root=None, deadline=100, calls=calls)
            results = retriever.search("budget", limit=5)
        self.assertTrue(results)
        self.assertTrue(all(self.store.get(hit.evidence_id).kind != "page" for hit in results))
        self.assertEqual(provenance["profile"], "lexical_child")
        self.assertEqual(provenance["tier"], "provisional_non_official")
        self.assertEqual(provenance["reranker"], "identity-noop")
        self.assertIsNone(provenance["dense"])
        self.assertFalse(provenance["visual_enabled"])
        self.assertEqual(calls, [])

    def _compose_dense(self, root, calls):
        page = self.pages[0]
        captured = {}
        class FakeDense:
            lane = "dense_page_legacy"
            provenance = {"retrieval_kind": "page_parent_maxpool", "embedding_unit": "legacy_page_part"}
            def search(self, query, *, limit, allowed_doc_ids=None):
                vector = captured["query_embedder"](query)
                captured["vector"] = vector
                return (Candidate(page.evidence_id, 1.0, self.lane, 1),)
        def load(store, **kwargs):
            self.assertIs(store, self.store)
            captured.update(kwargs)
            return FakeDense()
        with patch("midprojectrag.orchestration.local_runtime.verify_snapshot", return_value={"model.safetensors": "verified"}) as verify, \
                patch("midprojectrag.retrieval.legacy_page.load_legacy_page_retriever", side_effect=load) as loader, \
                patch("midprojectrag.stacks.local.hf_embeddings.KureEmbeddingProvider") as provider_factory:
            provider = provider_factory.return_value
            provider.model = "nlpai-lab/KURE-v1"
            provider.revision = KURE_REVISION
            provider.embed.return_value = SimpleNamespace(vectors=((1.0, 0.0),), input_tokens=7)
            retriever, provenance = compose_retriever(self.store, source_root=root, deadline=100, calls=calls)
        return retriever, provenance, captured, provider, provider_factory, verify, loader

    def test_dense_uses_pinned_local_paths_lazy_embedding_and_explicit_units(self):
        calls = []
        source = Path("/synthetic/read-only-corpus")
        retriever, provenance, captured, provider, factory, verify, loader = self._compose_dense(source, calls)
        chunks, index, snapshot = legacy_paths(source)
        self.assertEqual(captured["chunks_path"], chunks)
        self.assertEqual(captured["index_dir"], index)
        verify.assert_called_once_with(snapshot)
        self.assertEqual(snapshot.name, KURE_REVISION)
        self.assertEqual(factory.call_args.kwargs["device"], "cpu")
        self.assertEqual(factory.call_args.kwargs["batch_size"], 1)
        self.assertTrue(callable(factory.call_args.kwargs["tokenizer_loader"]))
        self.assertTrue(callable(factory.call_args.kwargs["encoder_loader"]))
        provider.embed.assert_not_called()
        self.assertEqual(calls, [])
        with patch("midprojectrag.orchestration.local_runtime.time.monotonic", return_value=5):
            results = retriever.search("budget", limit=5)
        self.assertIn(self.pages[0].evidence_id, {row.evidence_id for row in results})
        provider.embed.assert_called_once_with(["budget"])
        self.assertEqual(captured["vector"], (1.0, 0.0))
        self.assertEqual(provenance["profile"], "kure_legacy_page_plus_lexical_child")
        self.assertEqual(provenance["tier"], "provisional_non_official")
        self.assertEqual(provenance["dense"]["retrieval_kind"], "page_parent_maxpool")
        self.assertEqual(provenance["dense"]["embedding_unit"], "legacy_page_part")
        self.assertTrue(provenance["dense"]["local_files_only"])
        self.assertEqual(provenance["dense"]["model_snapshot_files"], {"model.safetensors": "verified"})
        self.assertFalse(provenance["visual_enabled"])
        self.assertEqual(calls, [{"purpose": "query_embedding", "model": "nlpai-lab/KURE-v1",
                                  "revision": KURE_REVISION, "status": "completed", "input_tokens": 7,
                                  "elapsed_ms": 0}])

    def test_injected_model_loaders_use_verified_snapshot_and_keep_offline_flags(self):
        source = Path("/synthetic/read-only-corpus")
        _, _, _, _, factory, _, _ = self._compose_dense(source, [])
        tokenizer_loader = factory.call_args.kwargs["tokenizer_loader"]
        encoder_loader = factory.call_args.kwargs["encoder_loader"]
        tokenizer = Mock()
        encoder = Mock()
        modules = {
            "transformers": SimpleNamespace(AutoTokenizer=SimpleNamespace(from_pretrained=tokenizer)),
            "sentence_transformers": SimpleNamespace(SentenceTransformer=encoder),
        }
        with patch.dict("sys.modules", modules):
            tokenizer_loader(pretrained_model_name_or_path="remote/model", revision="other-revision",
                             local_files_only=True, trust_remote_code=False, use_fast=True)
            encoder_loader(model_name_or_path="remote/model", revision="other-revision",
                           local_files_only=True, trust_remote_code=False, device="cpu")
        snapshot = str(legacy_paths(source)[2])
        tokenizer.assert_called_once_with(pretrained_model_name_or_path=snapshot,
                                          local_files_only=True, trust_remote_code=False, use_fast=True)
        encoder.assert_called_once_with(model_name_or_path=snapshot,
                                        local_files_only=True, trust_remote_code=False, device="cpu")

    def test_embedding_deadline_before_dispatch_makes_no_attempt(self):
        calls = []
        _, _, captured, provider, _, _, _ = self._compose_dense(Path("/synthetic"), calls)
        with patch("midprojectrag.orchestration.local_runtime.time.monotonic", return_value=100):
            with self.assertRaisesRegex(TimeoutError, "embedding_deadline_exceeded"):
                captured["query_embedder"]("budget")
        provider.embed.assert_not_called()
        self.assertEqual(calls, [])

    def test_embedding_error_or_late_result_preserves_attempt_without_retry(self):
        for late in (False, True):
            calls = []
            _, _, captured, provider, _, _, _ = self._compose_dense(Path("/synthetic"), calls)
            if not late:
                provider.embed.side_effect = RuntimeError("synthetic provider failure")
            moments = [5, 5, 101, 101] if late else [5, 5, 5]
            with self.subTest(late=late), patch("midprojectrag.orchestration.local_runtime.time.monotonic", side_effect=moments):
                with self.assertRaises((RuntimeError, TimeoutError)):
                    captured["query_embedder"]("budget")
            provider.embed.assert_called_once_with(["budget"])
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["status"], "error")
            self.assertNotIn("response", calls[0])

    def test_bad_snapshot_stops_before_provider_or_index_loader(self):
        with patch("midprojectrag.orchestration.local_runtime.verify_snapshot", side_effect=ValueError("snapshot_sha256_mismatch")), \
                patch("midprojectrag.stacks.local.hf_embeddings.KureEmbeddingProvider") as provider, \
                patch("midprojectrag.retrieval.legacy_page.load_legacy_page_retriever") as loader:
            with self.assertRaisesRegex(ValueError, "snapshot_sha256_mismatch"):
                compose_retriever(self.store, source_root=Path("/synthetic"), deadline=100, calls=[])
        provider.assert_not_called()
        loader.assert_not_called()

    def test_composition_deadline_is_finite_before_any_provider(self):
        for deadline in (float("nan"), float("inf"), float("-inf"), True, "100"):
            with self.subTest(deadline=deadline), self.assertRaises(ValueError):
                compose_retriever(self.store, source_root=None, deadline=deadline, calls=[])


class SnapshotTests(unittest.TestCase):
    def test_tiny_pinned_snapshot_reads_only_local_files_and_returns_detached_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / KURE_REVISION
            (snapshot / "1_Pooling").mkdir(parents=True)
            payloads = {"config.json": b"synthetic config", "1_Pooling/config.json": b"synthetic pooling"}
            for name, payload in payloads.items():
                (snapshot / name).write_bytes(payload)
            pins = {name: hashlib.sha256(payload).hexdigest() for name, payload in payloads.items()}
            before = {name: (snapshot / name).stat().st_mtime_ns for name in payloads}
            with patch("midprojectrag.orchestration.local_runtime.SNAPSHOT_PINS", pins):
                receipt = verify_snapshot(snapshot)
                self.assertEqual(receipt, pins)
                receipt["config.json"] = "changed receipt"
                self.assertNotEqual(receipt, pins)
            self.assertEqual(before, {name: (snapshot / name).stat().st_mtime_ns for name in payloads})

    def test_wrong_revision_missing_snapshot_and_hash_mismatch_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path in (root / "wrong-revision", root / KURE_REVISION):
                with self.subTest(path=path), self.assertRaisesRegex(ValueError, "pinned_snapshot_missing"):
                    verify_snapshot(path)
            snapshot = root / KURE_REVISION
            snapshot.mkdir()
            (snapshot / "model.safetensors").write_bytes(b"tampered synthetic model")
            with patch("midprojectrag.orchestration.local_runtime.SNAPSHOT_PINS", {"model.safetensors": "0" * 64}):
                with self.assertRaisesRegex(ValueError, "snapshot_sha256_mismatch"):
                    verify_snapshot(snapshot)


class DeadlineGeneratorTests(unittest.TestCase):
    @staticmethod
    def configure_provider(factory):
        provider = factory.return_value
        provider.model = "qwen3.8:27b-mlx"
        provider.model_digest = "synthetic-verified-digest"
        provider.max_output_tokens = 1800
        provider.system_instructions = "synthetic answer system"
        provider.generate.return_value = ({"answer": "synthetic"}, 7, 9)
        provider.estimate_cost.return_value = Decimal("0")
        return provider

    def test_answer_uses_same_budget_backend_identity_and_bounded_timeout(self):
        backend = LocalJSONBackend(deadline=20, per_call_seconds=30, max_calls=3)
        backend.calls.append({"purpose": "verify", "status": "completed"})
        with patch("midprojectrag.stacks.local.generation.OllamaGenerator") as factory, \
                patch("midprojectrag.orchestration.local_runtime.time.monotonic", return_value=5):
            provider = self.configure_provider(factory)
            generator = DeadlineGenerator(backend)
            self.assertIs(generator.backend, backend)
            provider.generate.assert_not_called()
            result = generator.generate("synthetic answer prompt")
            self.assertEqual(generator.estimate_cost(7, 9), Decimal("0"))
        self.assertEqual(result, ({"answer": "synthetic"}, 7, 9))
        self.assertEqual(factory.call_args.kwargs["timeout_seconds"], 7.5)
        self.assertEqual(factory.call_args.kwargs["model"], backend.model)
        self.assertEqual(factory.call_args.kwargs["base_url"], backend.base_url)
        self.assertEqual(backend.calls[-1], {
            "purpose": "answer", "model": "qwen3.8:27b-mlx", "model_digest": "synthetic-verified-digest",
            "status": "completed", "prompt": "synthetic answer prompt", "response": {"answer": "synthetic"},
            "input_tokens": 7, "output_tokens": 9, "elapsed_ms": 0,
        })

    def test_answer_dispatch_stops_at_shared_call_ceiling_or_deadline(self):
        for exhausted_calls in (False, True):
            backend = LocalJSONBackend(deadline=100 if exhausted_calls else 6, max_calls=1)
            if exhausted_calls:
                backend.calls.append({"purpose": "verify", "status": "completed"})
            with self.subTest(exhausted_calls=exhausted_calls), \
                    patch("midprojectrag.stacks.local.generation.OllamaGenerator") as factory, \
                    patch("midprojectrag.orchestration.local_runtime.time.monotonic", return_value=5):
                provider = self.configure_provider(factory)
                generator = DeadlineGenerator(backend)
                with self.assertRaisesRegex(TimeoutError, "generation_budget_exhausted"):
                    generator.generate("synthetic prompt")
                self.assertEqual(factory.call_count, 1)  # Constructor validation only.
                provider.generate.assert_not_called()
            self.assertFalse(any(row.get("purpose") == "answer" for row in backend.calls))

    def test_provider_failure_and_late_answer_remain_errors_without_retry(self):
        for late in (False, True):
            backend = LocalJSONBackend(deadline=100)
            with self.subTest(late=late), patch("midprojectrag.stacks.local.generation.OllamaGenerator") as factory:
                provider = self.configure_provider(factory)
                generator = DeadlineGenerator(backend)
                if not late:
                    provider.generate.side_effect = RuntimeError("synthetic provider failure")
                moments = [5, 5, 100, 101, 101] if late else [5, 5, 6]
                with patch("midprojectrag.orchestration.local_runtime.time.monotonic", side_effect=moments):
                    with self.assertRaises((RuntimeError, TimeoutError)):
                        generator.generate("synthetic prompt")
            provider.generate.assert_called_once_with("synthetic prompt")
            self.assertEqual(len(backend.calls), 1)
            self.assertEqual(backend.calls[0]["status"], "error")
            self.assertEqual(backend.calls[0]["error_type"], "TimeoutError" if late else "RuntimeError")
            self.assertIsNone(backend.calls[0]["cause_type"])
            self.assertEqual(backend.calls[0]["elapsed_ms"], 96000 if late else 1000)
            self.assertNotIn("synthetic provider failure", str(backend.calls[0]))
            if late:
                self.assertEqual(backend.calls[0]["input_tokens"], 7)
                self.assertEqual(backend.calls[0]["output_tokens"], 9)

    def test_answer_failure_keeps_safe_cause_type_without_exception_messages(self):
        backend = LocalJSONBackend(deadline=100)
        error = RuntimeError("private answer provider text")
        error.__cause__ = TimeoutError("private transport text")
        with patch("midprojectrag.stacks.local.generation.OllamaGenerator") as factory, \
                patch("midprojectrag.orchestration.local_runtime.time.monotonic", return_value=5):
            provider = self.configure_provider(factory)
            provider.generate.side_effect = error
            generator = DeadlineGenerator(backend)
            with self.assertRaises(RuntimeError):
                generator.generate("synthetic answer prompt")
        provider.generate.assert_called_once()
        self.assertEqual(len(backend.calls), 1)
        receipt = backend.calls[0]
        self.assertEqual(receipt["error_type"], "RuntimeError")
        self.assertEqual(receipt["cause_type"], "TimeoutError")
        self.assertEqual(receipt["elapsed_ms"], 0)
        self.assertNotIn("private answer provider text", str(receipt))
        self.assertNotIn("private transport text", str(receipt))
        self.assertNotIn("response", receipt)


if __name__ == "__main__":
    unittest.main()
