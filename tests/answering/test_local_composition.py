from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from midprojectrag.local_application import (
    ApiGenerationAccess, GenerationSelection, build_local_first_pipeline,
)
from midprojectrag.indexing.budget import BudgetLedger
from midprojectrag.indexing.embeddings import EmbeddingCache
from midprojectrag.indexing.exact_index import ExactDenseIndex
from midprojectrag.stacks.local import LocalHashEmbeddingProvider, LocalTextCounter
from tests.stacks.local.test_pipeline_integration import _Opener, _chunk, _request


class ChatCounter(LocalTextCounter):
    def count_chat(self, *, system, prompt):
        return self.count(system) + self.count(prompt)


class ApiStub:
    base_url = "https://api.openai.com/v1/"

    def __init__(self, plan):
        self.plan = plan
        self.calls = []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            output_text=json.dumps({"result": self.plan}), status="completed",
            usage=SimpleNamespace(input_tokens=20, output_tokens=8),
        )


class LocalCompositionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.chunks = [_chunk(1, "지원센터 용역비용 57,000,000원"), _chunk(2, "냉각 시스템")]
        self.plan = dict(status="answered", answer="57,000,000원",
                         citation_chunk_ids=[self.chunks[0]["chunk_id"]], abstention_reason=None)
        provider = LocalHashEmbeddingProvider()
        self.components = dict(
            index=ExactDenseIndex(self.chunks, np.asarray(provider.embed([c["text"] for c in self.chunks]).vectors), engine="numpy"),
            embedding_provider=provider, embedding_counter=LocalTextCounter(),
            query_cache=EmbeddingCache(Path(self.temp.name) / "cache"), corpus_manifest_sha256="2" * 64,
            retrieval_top_k=2, context_top_k=2,
        )
        self.api = ApiStub(self.plan)
        self.approvals = []
        self.budget = BudgetLedger(Path(self.temp.name) / "budget.json", limit_usd=1)

    def access(self, authorize=None):
        def approve(payload):
            self.approvals.append(payload)
            return True
        return ApiGenerationAccess(self.api, LocalTextCounter(), self.budget, authorize or approve)

    def test_switch_only_generator_keeps_index_ranking_cache_and_citations(self):
        local = build_local_first_pipeline(
            self.components, local_counter=ChatCounter(), local_opener=_Opener(self.plan),
        )
        local_result = local.query(_request())
        self.assertEqual(local_result.response["status"], "answered")
        provider = self.components["embedding_provider"]
        for model in ("gpt-5-nano", "gpt-5-mini"):
            with self.subTest(model=model):
                api = build_local_first_pipeline(
                    self.components, generation=GenerationSelection("openai", model), api_access=self.access(),
                )
                with patch.object(provider, "embed", side_effect=AssertionError("cached query must not re-embed")):
                    result = api.query(_request())
                self.assertIs(api.index, local.index)
                self.assertIs(api.embedding_provider, local.embedding_provider)
                self.assertIs(api.query_cache, local.query_cache)
                self.assertEqual(result.response["status"], "answered")
                self.assertEqual(result.response["citations"], local_result.response["citations"])
                self.assertEqual(result.retrieval, local_result.retrieval)
                self.assertEqual(self.api.calls[-1]["model"], model)
                self.assertEqual(self.approvals[-1].prompt, self.api.calls[-1]["input"])
                self.assertEqual(self.approvals[-1].instructions, self.api.calls[-1]["instructions"])
                self.assertFalse(self.api.calls[-1]["store"])
                self.assertEqual(api.stack_id, "local_application_openai")
        self.assertEqual(local.stack_id, "local_application_ollama")
        self.assertEqual(len(self.api.calls), 2)

    def test_openai_needs_explicit_access_even_with_environment_key(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-only"}):
            with self.assertRaisesRegex(ValueError, "explicit_api_generation_access_required"):
                build_local_first_pipeline(self.components, generation=GenerationSelection("openai"))
        self.assertEqual(self.api.calls, [])

    def test_denied_payload_is_not_sent_and_budget_released(self):
        pipeline = build_local_first_pipeline(
            self.components, generation=GenerationSelection("openai"), api_access=self.access(lambda _: False),
        )
        result = pipeline.query(_request())
        self.assertEqual(result.response["status"], "error")
        self.assertEqual(self.api.calls, [])
        state = json.loads(self.budget.path.read_text())
        self.assertEqual(state["reservations"], {})
        self.assertEqual(float(state["committed_usd"]), 0)

    def test_approval_rechecked_on_every_dispatch_and_endpoint_drift_rejected(self):
        pipeline = build_local_first_pipeline(
            self.components, generation=GenerationSelection("openai"), api_access=self.access(),
        )
        pipeline.query(_request())
        pipeline.query(_request())
        self.assertEqual(len(self.approvals), 2)
        self.api.base_url = "https://elsewhere.example.com/v1"
        self.assertEqual(pipeline.query(_request()).response["status"], "error")
        self.assertEqual(len(self.api.calls), 2)

    def test_bad_provider_model_or_mixed_options_fail_closed(self):
        for config in (GenerationSelection("bad"), GenerationSelection("ollama", "gpt-5-mini"),
                       GenerationSelection("openai", "unapproved")):
            with self.subTest(config=config), self.assertRaises(ValueError):
                build_local_first_pipeline(self.components, generation=config)
        with self.assertRaisesRegex(ValueError, "options_conflict"):
            build_local_first_pipeline(self.components, api_access=self.access())

    def test_remote_embedder_is_not_a_local_retrieval_path(self):
        with patch.object(self.components["embedding_provider"], "requires_budget", True):
            with self.assertRaisesRegex(ValueError, "local_embedding_provider_required"):
                build_local_first_pipeline(self.components)

    def test_provider_failure_never_falls_back_to_local(self):
        pipeline = build_local_first_pipeline(
            self.components, generation=GenerationSelection("openai"), api_access=self.access(),
        )
        with patch.object(self.api, "create", side_effect=ValueError("synthetic_provider_failure")), \
             patch("midprojectrag.stacks.local.generation.OllamaGenerator", side_effect=AssertionError("no fallback")):
            self.assertEqual(pipeline.query(_request()).response["status"], "error")

    def test_unknown_scope_never_requests_api(self):
        pipeline = build_local_first_pipeline(
            self.components, generation=GenerationSelection("openai"), api_access=self.access(),
        )
        result = pipeline.query(_request(["doc_" + "f" * 24]))
        self.assertEqual(result.response["status"], "abstained")
        self.assertEqual(self.api.calls, [])
        self.assertEqual(self.approvals, [])

    def test_vllm_selection_preserves_local_retrieval_without_api(self):
        from tests.stacks.local.test_vllm_generation import _Backend, _models_payload, _chat_payload
        backend = _Backend([_models_payload(), _chat_payload(content=json.dumps(self.plan))])
        pipeline = build_local_first_pipeline(
            self.components, generation=GenerationSelection("vllm"), local_counter=ChatCounter(), vllm_backend=backend,
        )
        self.assertIs(pipeline.index, self.components["index"])
        self.assertEqual(pipeline.query(_request()).response["status"], "answered")
        self.assertEqual(pipeline.stack_id, "local_application_vllm")
        self.assertEqual(self.api.calls, [])

    def test_frozen_loader_still_binds_original_generator_and_profile(self):
        from midprojectrag.gcp_local_baseline import load_mac_pipeline
        verified = SimpleNamespace(config={"generation": {
            "mac_equivalent_model": "qwen3.8:27b-mlx", "max_output_tokens": 1024,
            "mac_transport_context_tokens": 32768, "context_tokens": 8192,
        }})
        with patch("midprojectrag.gcp_local_baseline.load_mac_retrieval_components", return_value=self.components), \
             patch("midprojectrag.stacks.local.qwen_tokenizer.PinnedQwenChatTokenCounter", return_value=ChatCounter()):
            pipeline = load_mac_pipeline(verified)
        self.assertEqual(pipeline.stack_id, "mac_local_equivalent")
        self.assertEqual(pipeline.generator.model, "qwen3.8:27b-mlx")
        self.assertIs(pipeline.index, self.components["index"])

    def test_local_retrieval_loader_does_not_load_qwen_or_rebuild_index(self):
        from midprojectrag.gcp_local_baseline import load_mac_retrieval_components
        from midprojectrag.indexing.embeddings import embedding_cache_namespace
        config_path = Path(__file__).resolve().parents[2] / "configs/rag/gcp-local-kure-qwen3-8b-awq-refined98-page-v1.json"
        config = json.loads(config_path.read_text())
        verified = SimpleNamespace(config=config, hf_cache_path=Path(self.temp.name),
                                   index_path=Path(self.temp.name) / "index", embedding_cache_path=Path(self.temp.name) / "cache")
        provider = self.components["embedding_provider"]
        with patch("midprojectrag.gcp_local_baseline.verify_dependency_lock"), \
             patch("midprojectrag.gcp_local_baseline._configure_hf_cache"), \
             patch("midprojectrag.gcp_local_baseline._load_chunks", return_value=self.chunks), \
             patch("midprojectrag.gcp_local_baseline.mac_index_config_sha256", return_value="a" * 64), \
             patch("midprojectrag.stacks.local.hf_embeddings.HuggingFaceTokenCounter", return_value=LocalTextCounter()), \
             patch("midprojectrag.stacks.local.hf_embeddings.KureEmbeddingProvider", return_value=provider), \
             patch("midprojectrag.stacks.local.qwen_tokenizer.PinnedQwenChatTokenCounter", side_effect=AssertionError("no generator load")), \
             patch.object(ExactDenseIndex, "load", return_value=self.components["index"]) as load:
            components = load_mac_retrieval_components(verified)
        self.assertNotIn("generator", components)
        self.assertIs(components["index"], self.components["index"])
        self.assertEqual(load.call_args.kwargs, {
            "expected_embedding_model": embedding_cache_namespace(provider, role="document"),
            "expected_dimensions": 1024, "expected_api_profile": "mac_local_equivalent",
            "expected_index_config_sha256": "a" * 64,
        })

    def test_generation_profiles_are_only_provider_model_settings(self):
        root = Path(__file__).resolve().parents[2] / "configs/rag"
        for name in ("ollama", "vllm", "openai-nano", "openai-mini"):
            config = json.loads((root / f"local-first-{name}.json").read_text())
            self.assertEqual(set(config), {"provider", "model"})
            self.assertEqual(GenerationSelection(**config).resolved_model(), config["model"])


if __name__ == "__main__":
    unittest.main()
