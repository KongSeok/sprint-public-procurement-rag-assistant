from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import kiwipiepy
import sentence_transformers
import transformers

import midprojectrag.retrieval.dense as dense_module
import midprojectrag.retrieval.kiwi_bm25 as kiwi_module
from midprojectrag.evidence.builder import build_store
from midprojectrag.retrieval.dense import (
    KURE_IDENTITY,
    DenseChildLane,
    LoadedDenseArtifactAttestation,
    build_dense,
    load_dense,
    require_loaded_dense_artifact,
)
from midprojectrag.retrieval.fusion import (
    HybridChildRetriever,
    HybridProductionBinding,
    require_production_hybrid,
)
from midprojectrag.retrieval.kiwi_bm25 import (
    KiwiBM25Lane,
    KiwiTokenizer,
    LoadedLexicalArtifactAttestation,
    require_loaded_lexical_artifact,
)
from midprojectrag.stacks.local.hf_embeddings import KureEmbeddingProvider
from tests.test_evidence_builder import chunk


class _FakeKure:
    def __init__(self):
        self.__dict__.update(KURE_IDENTITY)

    def embed(self, texts):
        matrix = np.zeros((len(texts), 1024), dtype=np.float32)
        matrix[:, 0] = 1
        return SimpleNamespace(vectors=matrix)


class _FakeTokens:
    identity = {"engine": "synthetic", "version": "1"}

    def tokenize(self, text):
        return tuple(text.casefold().split())


class RetrieverProductionAttestationTests(unittest.TestCase):
    def setUp(self):
        self.store = build_store(
            [
                chunk("정보시스템 구축 예산"),
                chunk(
                    "운영 기간 입찰 공고",
                    block="block_" + "c" * 24,
                    doc="doc_" + "d" * 24,
                ),
            ]
        )

    def _loaded_production_lanes(self, root: Path):
        dense_dir = root / "private" / "dense"
        build_provider = KureEmbeddingProvider(batch_size=2, device="cpu")

        encoder = object.__new__(dense_module._PINNED_SENTENCE_TRANSFORMER_CLASS)
        hf_tokenizer = object.__new__(dense_module._PINNED_TOKENIZER_BASE_CLASS)

        def fake_get_encoder(provider):
            provider._encoder = encoder
            return encoder

        def fake_get_tokenizer(counter):
            counter._tokenizer = hf_tokenizer
            return hf_tokenizer

        def fake_embed(_provider, texts):
            vectors = np.zeros((len(texts), 1024), dtype=np.float32)
            for index in range(len(vectors)):
                vectors[index, index] = 1
            return SimpleNamespace(vectors=vectors)

        # Exercise the production build/load handoff without loading the
        # heavyweight model. Patching the module-private pinned call is test
        # instrumentation; application callers cannot inject through the
        # provider constructor or instance methods and retain production status.
        with (
            patch(
                "midprojectrag.retrieval.dense._PINNED_KURE_GET_ENCODER",
                side_effect=fake_get_encoder,
            ),
            patch(
                "midprojectrag.retrieval.dense._PINNED_COUNTER_GET_TOKENIZER",
                side_effect=fake_get_tokenizer,
            ),
            patch(
                "midprojectrag.retrieval.dense._PINNED_KURE_EMBED",
                side_effect=fake_embed,
            ),
        ):
            build_dense(
                self.store,
                build_provider,
                output_dir=dense_dir,
                data_root=root,
                batch_size=2,
            )
        provider = build_provider
        dense = load_dense(
            self.store, provider, output_dir=dense_dir, data_root=root
        )

        tokenizer = KiwiTokenizer()
        lexical_dir = root / "private" / "lexical"
        KiwiBM25Lane.build(self.store, tokenizer).save(lexical_dir, data_root=root)
        lexical = KiwiBM25Lane.load(
            self.store, tokenizer, lexical_dir, data_root=root
        )
        return dense, lexical, provider, tokenizer

    def test_only_loaders_mint_lane_attestations_and_factory_binding(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dense, lexical, _, _ = self._loaded_production_lanes(root)
            dense_proof = require_loaded_dense_artifact(
                dense, self.store, production=True
            )
            lexical_proof = require_loaded_lexical_artifact(
                lexical, self.store, production=True
            )
            self.assertEqual(dense.loaded_artifact_attestation, dense_proof)
            self.assertEqual(lexical.loaded_artifact_attestation, lexical_proof)

            raw = HybridChildRetriever(self.store, dense, lexical)
            with self.assertRaisesRegex(
                ValueError, "hybrid_production_binding_required"
            ):
                require_production_hybrid(raw, self.store)
            retriever = HybridChildRetriever.from_loaded_artifacts(
                self.store, dense, lexical
            )
            binding = require_production_hybrid(retriever, self.store)
            self.assertIsInstance(binding, HybridProductionBinding)
            self.assertEqual(retriever.production_binding, binding)
            self.assertEqual(binding.bundle_sha256, self.store.bundle_sha256)

    def test_sealed_proofs_cannot_be_constructed_through_public_initializer(self):
        for cls in (
            LoadedDenseArtifactAttestation,
            LoadedLexicalArtifactAttestation,
            HybridProductionBinding,
        ):
            with self.subTest(cls=cls.__name__):
                with self.assertRaises(TypeError):
                    cls({})

    def test_private_dense_constructor_and_raw_lexical_constructor_have_no_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            dense, lexical, provider, tokenizer = self._loaded_production_lanes(
                Path(temp)
            )
            raw_dense = DenseChildLane._from_verified(
                self.store,
                dense.vectors,
                provider,
                artifact_sha256=dense.artifact_sha256,
            )
            self.assertIsNone(raw_dense.loaded_artifact_attestation)
            with self.assertRaisesRegex(ValueError, "loaded_dense_artifact_required"):
                HybridChildRetriever.from_loaded_artifacts(
                    self.store, raw_dense, lexical
                )

            raw_lexical = KiwiBM25Lane(
                self.store,
                tokenizer,
                lexical.tokens,
                k1=lexical.k1,
                b=lexical.b,
                artifact_sha256=lexical.artifact_sha256,
            )
            self.assertIsNone(raw_lexical.loaded_artifact_attestation)
            with self.assertRaisesRegex(ValueError, "loaded_lexical_artifact_required"):
                HybridChildRetriever.from_loaded_artifacts(
                    self.store, dense, raw_lexical
                )

    def test_loaded_synthetic_artifacts_never_gain_production_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dense_dir = root / "private" / "dense"
            fake_provider = _FakeKure()
            build_dense(
                self.store,
                fake_provider,
                output_dir=dense_dir,
                data_root=root,
            )
            dense = load_dense(
                self.store,
                fake_provider,
                output_dir=dense_dir,
                data_root=root,
            )
            lexical_dir = root / "private" / "lexical"
            KiwiBM25Lane.build(self.store, _FakeTokens()).save(
                lexical_dir, data_root=root
            )
            lexical = KiwiBM25Lane.load(
                self.store, _FakeTokens(), lexical_dir, data_root=root
            )
            self.assertIsNotNone(dense.loaded_artifact_attestation)
            self.assertIsNotNone(lexical.loaded_artifact_attestation)
            with self.assertRaisesRegex(
                ValueError, "loaded_dense_production_execution_required"
            ):
                HybridChildRetriever.from_loaded_artifacts(
                    self.store, dense, lexical
                )

    def test_runtime_vector_token_and_private_adapter_mutation_fail_closed(self):
        mutations = (
            "vectors",
            "provider_encoder",
            "provider_tokenizer",
            "tokens",
            "tokenizer",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                dense, lexical, provider, tokenizer = self._loaded_production_lanes(
                    Path(temp)
                )
                if mutation == "vectors":
                    changed = np.array(dense.vectors, copy=True)
                    changed[:] = np.roll(changed, 1, axis=1)
                    dense.vectors = changed
                elif mutation == "provider_encoder":
                    provider._encoder = object()
                elif mutation == "provider_tokenizer":
                    provider._counter._tokenizer = object()
                elif mutation == "tokens":
                    lexical.tokens = tuple(("forged",) for _ in lexical.tokens)
                else:
                    tokenizer._kiwi = object()
                with self.assertRaises(ValueError):
                    HybridChildRetriever.from_loaded_artifacts(
                        self.store, dense, lexical
                    )

    def test_production_search_uses_hidden_kure_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            dense, _, public_provider, _ = self._loaded_production_lanes(Path(temp))
            seen = []
            encoder = object.__new__(
                dense_module._PINNED_SENTENCE_TRANSFORMER_CLASS
            )
            hf_tokenizer = object.__new__(dense_module._PINNED_TOKENIZER_BASE_CLASS)

            def fake_get_encoder(hidden_provider):
                hidden_provider._encoder = encoder
                return encoder

            def fake_get_tokenizer(counter):
                counter._tokenizer = hf_tokenizer
                return hf_tokenizer

            def fake_embed(hidden_provider, texts):
                seen.append(hidden_provider)
                matrix = np.zeros((len(texts), 1024), dtype=np.float32)
                matrix[:, 0] = 1
                return SimpleNamespace(vectors=matrix)

            with (
                patch(
                    "midprojectrag.retrieval.dense._PINNED_KURE_GET_ENCODER",
                    side_effect=fake_get_encoder,
                ),
                patch(
                    "midprojectrag.retrieval.dense._PINNED_COUNTER_GET_TOKENIZER",
                    side_effect=fake_get_tokenizer,
                ),
                patch(
                    "midprojectrag.retrieval.dense._PINNED_KURE_EMBED",
                    side_effect=fake_embed,
                ),
            ):
                result = dense.search("예산", 2)
            self.assertTrue(result.candidates)
            self.assertEqual(len(seen), 1)
            self.assertIsNot(seen[0], public_provider)
            require_loaded_dense_artifact(dense, self.store, production=True)

    def test_kiwi_add_user_word_drift_is_checked_on_the_actual_query(self):
        with tempfile.TemporaryDirectory() as temp:
            _, lexical, _, public_tokenizer = self._loaded_production_lanes(
                Path(temp)
            )
            query = "고유변조토큰"
            before = KiwiTokenizer.tokenize(public_tokenizer, query)
            public_tokenizer._kiwi.add_user_word(query, "NNP", 100.0)
            after = KiwiTokenizer.tokenize(public_tokenizer, query)
            self.assertNotEqual(before, after)
            with self.assertRaisesRegex(
                ValueError, "lexical_exposed_tokenizer_runtime_drift"
            ):
                lexical.search(query, 2)

    def test_public_hf_factory_monkeypatch_cannot_become_pinned_runtime(self):
        fake_encoder = object()
        fake_tokenizer = object()
        captured_encoder = dense_module._PINNED_SENTENCE_TRANSFORMER_CLASS
        captured_tokenizer_load = dense_module._PINNED_AUTO_TOKENIZER_LOAD
        with (
            patch.object(
                sentence_transformers,
                "SentenceTransformer",
                return_value=fake_encoder,
            ),
            patch.object(
                transformers.AutoTokenizer,
                "from_pretrained",
                return_value=fake_tokenizer,
            ),
        ):
            forged = (
                sentence_transformers.SentenceTransformer(),
                transformers.AutoTokenizer.from_pretrained("forged"),
            )
            self.assertIs(
                dense_module._PINNED_SENTENCE_TRANSFORMER_CLASS,
                captured_encoder,
            )
            self.assertIs(
                dense_module._PINNED_AUTO_TOKENIZER_LOAD,
                captured_tokenizer_load,
            )
            with self.assertRaisesRegex(
                ValueError, "dense_production_dependency_runtime_not_pinned"
            ):
                dense_module._validate_loaded_runtime_objects(forged)

    def test_public_kiwi_constructor_monkeypatch_is_not_used(self):
        class FakeKiwi:
            def __init__(self, **_kwargs):
                pass

            def add_user_word(self, *_args):
                pass

            def tokenize(self, _text):
                return ()

        with patch.object(kiwipiepy, "Kiwi", FakeKiwi):
            tokenizer = KiwiTokenizer()
        self.assertIs(type(tokenizer._kiwi), kiwi_module._PINNED_KIWI_CLASS)
        self.assertIsNot(type(tokenizer._kiwi), FakeKiwi)


if __name__ == "__main__":
    unittest.main()
