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
import midprojectrag.retrieval.fusion as fusion_module
import midprojectrag.retrieval.kiwi_bm25 as kiwi_module
import midprojectrag.orchestration.execution_contracts as execution_module
from midprojectrag.evidence import EvidenceStore
from midprojectrag.evidence.builder import build_store
from midprojectrag.retrieval.contracts import SearchResult
from midprojectrag.retrieval.dense import (
    KURE_IDENTITY,
    DenseChildLane,
    LoadedDenseArtifactAttestation,
    build_dense,
    load_dense,
    preflight_loaded_dense_artifact,
    require_loaded_dense_artifact,
)
from midprojectrag.retrieval.fusion import (
    HybridChildRetriever,
    HybridProductionBinding,
    fuse_rrf,
    preflight_production_hybrid,
    require_production_hybrid,
)
from midprojectrag.retrieval.kiwi_bm25 import (
    KiwiBM25Lane,
    KiwiTokenizer,
    LoadedLexicalArtifactAttestation,
    require_loaded_lexical_artifact,
)
from midprojectrag.orchestration.execution_contracts import (
    bind_production_harness_runtime,
    validate_harness_runtime_binding,
)
from midprojectrag.stacks.local.hf_embeddings import KureEmbeddingProvider
from midprojectrag.runtime_integrity import ResolvedScope
from tests.test_evidence_builder import chunk


def _replacement_hybrid_search(*_args, **_kwargs):
    raise AssertionError("replacement hybrid search must not execute")


def _replacement_fuse(*_args, **_kwargs):
    raise AssertionError("replacement fusion must not execute")


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


class _FakeSentenceTransformer:
    def __init__(self, **_kwargs):
        pass

    def encode(self, texts, **_kwargs):
        vectors = np.zeros((len(texts), 1024), dtype=np.float32)
        for index, text in enumerate(texts):
            vectors[index, 0 if "예산" in text or "정보시스템" in text else 1] = 1
        return vectors


_FakeSentenceTransformer.__module__ = "sentence_transformers.sentence_transformer.model"
_FakeSentenceTransformer.__qualname__ = "SentenceTransformer"


class _FakeTokenizerBase:
    pass


class _FakeHfTokenizer(_FakeTokenizerBase):
    def __call__(self, _text, **_kwargs):
        return {"input_ids": [1]}


def _fake_auto_tokenizer_load(**_kwargs):
    return _FakeHfTokenizer()


_fake_auto_tokenizer_load.__module__ = "transformers.models.auto.tokenization_auto"
_fake_auto_tokenizer_load.__qualname__ = "AutoTokenizer.from_pretrained"


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
        provider = KureEmbeddingProvider(batch_size=2, device="cpu")
        with (
            patch.object(
                dense_module,
                "_PINNED_SENTENCE_TRANSFORMER_CLASS",
                _FakeSentenceTransformer,
            ),
            patch.object(
                dense_module,
                "_PINNED_TOKENIZER_BASE_CLASS",
                _FakeTokenizerBase,
            ),
            patch.object(
                dense_module,
                "_PINNED_AUTO_TOKENIZER_LOAD",
                _fake_auto_tokenizer_load,
            ),
        ):
            build_dense(
                self.store,
                provider,
                output_dir=dense_dir,
                data_root=root,
                batch_size=2,
            )
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
            with (
                patch.object(
                    dense_module,
                    "_PINNED_SENTENCE_TRANSFORMER_CLASS",
                    _FakeSentenceTransformer,
                ),
                patch.object(
                    dense_module,
                    "_PINNED_TOKENIZER_BASE_CLASS",
                    _FakeTokenizerBase,
                ),
                patch.object(
                    dense_module,
                    "_PINNED_AUTO_TOKENIZER_LOAD",
                    _fake_auto_tokenizer_load,
                ),
            ):
                result = dense.search("예산", 2)
                require_loaded_dense_artifact(dense, self.store, production=True)
            self.assertTrue(result.candidates)
            runtime = dense_module._LOADED_DENSE_RUNTIME.get(dense)
            self.assertIsNot(runtime.query_provider, public_provider)

    def test_dense_search_rejects_post_binding_dispatch_alias_patch_before_call(self):
        with tempfile.TemporaryDirectory() as temp:
            dense, _, _, _ = self._loaded_production_lanes(Path(temp))
            calls = []

            def armed_dispatch(*_args, **_kwargs):
                calls.append("dispatch")
                raise AssertionError("patched dispatch must not execute")

            with patch.object(
                dense_module,
                "_PINNED_KURE_GET_ENCODER",
                armed_dispatch,
            ):
                with self.assertRaisesRegex(
                    ValueError, "dense_production_provider_method_override"
                ):
                    dense.search("예산", 2)
            self.assertEqual(calls, [])

    def test_dense_search_rejects_post_binding_normalize_patch_before_call(self):
        with tempfile.TemporaryDirectory() as temp:
            dense, lexical, _, _ = self._loaded_production_lanes(Path(temp))
            retriever = HybridChildRetriever.from_loaded_artifacts(
                self.store, dense, lexical
            )
            binding = bind_production_harness_runtime(
                store=self.store,
                retriever=retriever,
            )
            validate_harness_runtime_binding(
                binding=binding,
                store=self.store,
                expected_execution_kind="production",
            )
            calls = []

            def armed_normalize(*_args, **_kwargs):
                calls.append("normalize")
                raise AssertionError("patched normalize must not execute")

            with (
                patch.object(
                    dense_module,
                    "_PINNED_SENTENCE_TRANSFORMER_CLASS",
                    _FakeSentenceTransformer,
                ),
                patch.object(
                    dense_module,
                    "_PINNED_TOKENIZER_BASE_CLASS",
                    _FakeTokenizerBase,
                ),
                patch.object(
                    dense_module,
                    "_PINNED_AUTO_TOKENIZER_LOAD",
                    _fake_auto_tokenizer_load,
                ),
                patch.object(dense_module, "normalize", armed_normalize),
            ):
                with self.assertRaisesRegex(
                    ValueError, "dense_production_search_dependency_override"
                ):
                    validate_harness_runtime_binding(
                        binding=binding,
                        store=self.store,
                        expected_execution_kind="production",
                    )
                with self.assertRaisesRegex(
                    ValueError, "dense_production_search_dependency_override"
                ):
                    dense.search("예산", 2)
            self.assertEqual(calls, [])

    def test_dense_search_dependency_preflight_covers_helpers_numpy_and_registries(self):
        with tempfile.TemporaryDirectory() as temp:
            dense, _, _, _ = self._loaded_production_lanes(Path(temp))
            dependency_calls = []
            store_calls = []

            def armed_dependency(*_args, **_kwargs):
                dependency_calls.append("dependency")
                raise AssertionError("drifted dependency must not execute")

            def armed_store(*_args, **_kwargs):
                store_calls.append("store")
                raise AssertionError("store traversal must not execute")

            cases = (
                (dense_module, "validate_search"),
                (dense_module, "_dense_lane_state"),
                (dense_module, "SearchResult"),
                (dense_module, "_LOADED_DENSE_RUNTIME"),
                (dense_module.np, "asarray"),
                (dense_module.np.linalg, "norm"),
            )
            for owner, name in cases:
                with self.subTest(name=name), patch.object(
                    owner, name, armed_dependency
                ), patch.object(type(self.store), "candidates", armed_store):
                    with self.assertRaisesRegex(
                        ValueError, "dense_production_search_dependency_override"
                    ):
                        dense.search("예산", 2)
                self.assertEqual(dependency_calls, [])
                self.assertEqual(store_calls, [])

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

    def test_dense_authority_registries_never_call_component_hash(self):
        def forbidden_hash(_component):
            raise AssertionError("component_hash_must_not_run")

        class StandaloneKey:
            __hash__ = forbidden_hash

        registry = dense_module._IdentityWeakRegistry()
        key = StandaloneKey()
        registry[key] = "issued"
        self.assertEqual(registry.get(key), "issued")
        self.assertEqual(registry.pop(key), "issued")

        with tempfile.TemporaryDirectory() as temp:
            dense, _, _, _ = self._loaded_production_lanes(Path(temp))
            for owner, expected_error in (
                (DenseChildLane, "loaded_dense_search_method_override"),
                (
                    KureEmbeddingProvider,
                    "dense_production_provider_method_override",
                ),
            ):
                with self.subTest(owner=owner.__name__), patch.object(
                    owner, "__hash__", forbidden_hash
                ), patch.object(
                    dense_module._IdentityWeakRegistry,
                    "get",
                    side_effect=AssertionError("registry_lookup_must_not_run"),
                ):
                    with self.assertRaisesRegex(ValueError, expected_error):
                        require_loaded_dense_artifact(
                            dense, self.store, production=True
                        )

    def test_dense_public_preflight_has_zero_store_vector_or_model_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            dense, _, _, _ = self._loaded_production_lanes(Path(temp))
            proof = dense.loaded_artifact_attestation
            runtime = dense_module._LOADED_DENSE_RUNTIME.get(dense)
            before = runtime.query_runtime
            with (
                patch(
                    "midprojectrag.retrieval.dense.validate_evidence_store_snapshot",
                    side_effect=AssertionError("store_validator_must_not_run"),
                ),
                patch.object(
                    type(self.store),
                    "candidates",
                    side_effect=AssertionError("store_traversal_must_not_run"),
                ),
                patch(
                    "midprojectrag.retrieval.dense._matrix_hash",
                    side_effect=AssertionError("vector_hash_must_not_run"),
                ),
            ):
                self.assertIs(
                    preflight_loaded_dense_artifact(
                        dense, self.store, production=True
                    ),
                    proof,
                )
            self.assertIs(runtime.query_runtime, before)
            self.assertEqual(before, (None, None))

    def test_dense_attestation_descriptor_drift_rejected_before_getter_call(self):
        with tempfile.TemporaryDirectory() as temp:
            dense, _, _, _ = self._loaded_production_lanes(Path(temp))
            calls = []

            def armed_field(_proof):
                calls.append("field")
                raise AssertionError("attestation field getter must not run")

            with patch.object(
                LoadedDenseArtifactAttestation,
                "rows_sha256",
                property(armed_field),
            ):
                with self.assertRaisesRegex(
                    ValueError, "loaded_dense_attestation_descriptor_override"
                ):
                    preflight_loaded_dense_artifact(
                        dense, self.store, production=True
                    )
            self.assertEqual(calls, [])

            def armed_getattribute(_proof, _name):
                calls.append("getattribute")
                raise AssertionError("attestation getattribute must not run")

            with patch.object(
                LoadedDenseArtifactAttestation,
                "__getattribute__",
                armed_getattribute,
            ):
                with self.assertRaisesRegex(
                    ValueError, "loaded_dense_attestation_descriptor_override"
                ):
                    preflight_loaded_dense_artifact(
                        dense, self.store, production=True
                    )
            self.assertEqual(calls, [])

    def test_dense_and_provider_function_code_drift_fails_before_use(self):
        def forbidden(*_args, **_kwargs):
            raise AssertionError("drifted_method_must_not_run")

        with tempfile.TemporaryDirectory() as temp:
            dense, _, _, _ = self._loaded_production_lanes(Path(temp))
            cases = (
                (
                    DenseChildLane.search,
                    "loaded_dense_search_method_override",
                ),
                (
                    KureEmbeddingProvider.embed,
                    "dense_production_provider_method_override",
                ),
                (
                    KureEmbeddingProvider._get_encoder,
                    "dense_production_provider_method_override",
                ),
                (
                    dense_module.HuggingFaceTokenCounter.count,
                    "dense_production_provider_method_override",
                ),
                (
                    dense_module.HuggingFaceTokenCounter._get_tokenizer,
                    "dense_production_provider_method_override",
                ),
            )
            for method, expected_error in cases:
                with self.subTest(method=method.__qualname__):
                    original_code = method.__code__
                    method.__code__ = forbidden.__code__
                    try:
                        with self.assertRaisesRegex(ValueError, expected_error):
                            require_loaded_dense_artifact(
                                dense, self.store, production=True
                            )
                    finally:
                        method.__code__ = original_code

    def test_dense_provider_preflight_precedes_store_traversal(self):
        def forbidden_getattribute(_provider, _name):
            raise AssertionError("provider_getattribute_must_not_run")

        with tempfile.TemporaryDirectory() as temp:
            dense, _, _, _ = self._loaded_production_lanes(Path(temp))
            with (
                patch.object(
                    KureEmbeddingProvider,
                    "__getattribute__",
                    forbidden_getattribute,
                ),
                patch.object(
                    type(self.store),
                    "candidates",
                    side_effect=AssertionError("store_traversal_must_not_run"),
                ),
            ):
                with self.assertRaisesRegex(
                    ValueError, "dense_production_provider_method_override"
                ):
                    require_loaded_dense_artifact(
                        dense, self.store, production=True
                    )

    def test_dense_container_preflight_never_hashes_untrusted_keys(self):
        class ArmedKey:
            armed = False

            def __hash__(self):
                if self.armed:
                    raise AssertionError("untrusted_container_key_hash_ran")
                return 17

        with tempfile.TemporaryDirectory() as temp:
            dense, _, provider, _ = self._loaded_production_lanes(Path(temp))
            key = ArmedKey()
            provider.__dict__[key] = "forged"
            key.armed = True
            with self.assertRaisesRegex(
                ValueError, "dense_production_embedding_provider_required"
            ):
                require_loaded_dense_artifact(
                    dense, self.store, production=True
                )

    def test_dense_issued_proof_payload_rehash_does_not_restore_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            dense, _, _, _ = self._loaded_production_lanes(Path(temp))
            proof = dense.loaded_artifact_attestation
            object.__setattr__(proof, "rows_sha256", "0" * 64)
            fields = (
                "bundle_sha256",
                "rows_sha256",
                "receipt_sha256",
                "vectors_file_sha256",
                "vectors_content_sha256",
                "embedding_identity_sha256",
                "execution_kind",
                "provider_runtime_sha256",
            )
            payload = {
                name: object.__getattribute__(proof, name) for name in fields
            }
            object.__setattr__(
                proof, "attestation_sha256", dense_module._digest(payload)
            )
            with self.assertRaisesRegex(
                ValueError, "loaded_dense_attestation_issued_payload_drift"
            ):
                require_loaded_dense_artifact(
                    dense, self.store, production=True
                )

    def test_dense_issued_lane_scalar_and_proof_cannot_drift_together(self):
        with tempfile.TemporaryDirectory() as temp:
            dense, _, _, _ = self._loaded_production_lanes(Path(temp))
            forged = "0" * 64
            dense.artifact_sha256 = forged
            proof = dense.loaded_artifact_attestation
            object.__setattr__(proof, "receipt_sha256", forged)
            fields = (
                "bundle_sha256",
                "rows_sha256",
                "receipt_sha256",
                "vectors_file_sha256",
                "vectors_content_sha256",
                "embedding_identity_sha256",
                "execution_kind",
                "provider_runtime_sha256",
            )
            payload = {
                name: object.__getattribute__(proof, name) for name in fields
            }
            object.__setattr__(
                proof, "attestation_sha256", dense_module._digest(payload)
            )
            with self.assertRaisesRegex(
                ValueError, "loaded_dense_snapshot_identity_drift"
            ):
                require_loaded_dense_artifact(
                    dense, self.store, production=True
                )

    def test_production_harness_runtime_binding_reuses_exact_attestations(self):
        with tempfile.TemporaryDirectory() as temp:
            dense, lexical, _, _ = self._loaded_production_lanes(Path(temp))
            retriever = HybridChildRetriever.from_loaded_artifacts(
                self.store, dense, lexical
            )
            binding = bind_production_harness_runtime(
                store=self.store,
                retriever=retriever,
            )
            validate_harness_runtime_binding(
                binding=binding,
                store=self.store,
                expected_execution_kind="production",
            )
            payload = binding.to_dict()
            self.assertEqual(payload["verifier_capability"], "unavailable")
            self.assertEqual(payload["reranker_capability"], "unavailable")
            self.assertEqual(payload["clock_kind"], "monotonic_ns")

    def test_loader_validators_reject_class_method_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            dense, lexical, _, _ = self._loaded_production_lanes(Path(temp))
            retriever = HybridChildRetriever.from_loaded_artifacts(
                self.store, dense, lexical
            )
            with patch.object(DenseChildLane, "search", lambda *_a, **_k: None):
                with self.assertRaisesRegex(
                    ValueError, "loaded_dense_search_method_override"
                ):
                    require_loaded_dense_artifact(
                        dense, self.store, production=True
                    )
            with patch.object(KiwiBM25Lane, "search", lambda *_a, **_k: None):
                with self.assertRaisesRegex(
                    ValueError, "loaded_lexical_search_method_override"
                ):
                    require_loaded_lexical_artifact(
                        lexical, self.store, production=True
                    )
            with patch.object(KiwiTokenizer, "tokenize", lambda *_a, **_k: ()):
                with self.assertRaisesRegex(
                    ValueError, "lexical_production_tokenizer_method_override"
                ):
                    require_loaded_lexical_artifact(
                        lexical, self.store, production=True
                    )
            with patch.object(HybridChildRetriever, "search", lambda *_a, **_k: None):
                with self.assertRaisesRegex(
                    ValueError, "hybrid_production_method_override"
                ):
                    require_production_hybrid(retriever, self.store)
            with patch.object(fusion_module, "fuse_rrf", lambda *_a, **_k: None):
                with self.assertRaisesRegex(
                    ValueError, "hybrid_production_method_override"
                ):
                    require_production_hybrid(retriever, self.store)

    def test_loader_and_hybrid_proof_hash_drift_is_rejected(self):
        for target in ("dense", "lexical", "hybrid"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temp:
                dense, lexical, _, _ = self._loaded_production_lanes(Path(temp))
                retriever = HybridChildRetriever.from_loaded_artifacts(
                    self.store, dense, lexical
                )
                if target == "dense":
                    proof = dense.loaded_artifact_attestation
                    object.__setattr__(proof, "attestation_sha256", "0" * 64)
                    with self.assertRaisesRegex(
                        ValueError, "loaded_dense_attestation_hash_mismatch"
                    ):
                        require_loaded_dense_artifact(
                            dense, self.store, production=True
                        )
                elif target == "lexical":
                    proof = lexical.loaded_artifact_attestation
                    object.__setattr__(proof, "attestation_sha256", "0" * 64)
                    with self.assertRaisesRegex(
                        ValueError, "loaded_lexical_attestation_hash_mismatch"
                    ):
                        require_loaded_lexical_artifact(
                            lexical, self.store, production=True
                        )
                else:
                    proof = retriever.production_binding
                    object.__setattr__(proof, "binding_sha256", "0" * 64)
                    with self.assertRaisesRegex(
                        ValueError, "hybrid_production_binding_hash_mismatch"
                    ):
                        require_production_hybrid(retriever, self.store)

    def test_hybrid_preflight_rejects_code_hash_and_descriptor_drift_without_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            dense, lexical, _, _ = self._loaded_production_lanes(Path(temp))
            retriever = HybridChildRetriever.from_loaded_artifacts(
                self.store, dense, lexical
            )
            hash_calls = []

            def armed_hash(_self):
                hash_calls.append("hash")
                raise AssertionError("hybrid hash must not execute")

            with patch.object(HybridChildRetriever, "__hash__", armed_hash):
                with self.assertRaisesRegex(
                    ValueError, "hybrid_production_method_override"
                ):
                    require_production_hybrid(retriever, self.store)
            self.assertEqual(hash_calls, [])

            original_search_code = HybridChildRetriever.search.__code__
            HybridChildRetriever.search.__code__ = _replacement_hybrid_search.__code__
            try:
                with self.assertRaisesRegex(
                    ValueError, "hybrid_production_method_override"
                ):
                    require_production_hybrid(retriever, self.store)
            finally:
                HybridChildRetriever.search.__code__ = original_search_code

            original_fuse_code = fusion_module.fuse_rrf.__code__
            fusion_module.fuse_rrf.__code__ = _replacement_fuse.__code__
            try:
                with self.assertRaisesRegex(
                    ValueError, "hybrid_production_method_override"
                ):
                    require_production_hybrid(retriever, self.store)
            finally:
                fusion_module.fuse_rrf.__code__ = original_fuse_code

            descriptor_calls = []

            def armed_binding_sha(_self):
                descriptor_calls.append("descriptor")
                raise AssertionError("binding descriptor must not execute")

            with patch.object(
                HybridProductionBinding,
                "binding_sha256",
                property(armed_binding_sha),
            ):
                with self.assertRaisesRegex(
                    ValueError, "hybrid_production_binding_shape_drift"
                ):
                    require_production_hybrid(retriever, self.store)
            self.assertEqual(descriptor_calls, [])

    def test_hybrid_data_descriptors_fail_before_access_or_lane_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            dense, lexical, _, _ = self._loaded_production_lanes(Path(temp))
            retriever = HybridChildRetriever.from_loaded_artifacts(
                self.store, dense, lexical
            )
            binding = bind_production_harness_runtime(
                store=self.store,
                retriever=retriever,
            )
            for name in ("store", "dense", "lexical"):
                calls = []

                def armed_descriptor(_retriever, name=name):
                    calls.append(name)
                    raise AssertionError("hybrid descriptor must not execute")

                with self.subTest(name=name), patch.object(
                    HybridChildRetriever,
                    name,
                    property(armed_descriptor),
                    create=True,
                ):
                    for operation in (
                        lambda: preflight_production_hybrid(
                            retriever, self.store
                        ),
                        lambda: require_production_hybrid(
                            retriever, self.store
                        ),
                        lambda: validate_harness_runtime_binding(
                            binding=binding,
                            store=self.store,
                            expected_execution_kind="production",
                        ),
                        lambda: retriever.search(
                            "예산",
                            dense_k=1,
                            lexical_k=1,
                            scope=ResolvedScope(),
                        ),
                    ):
                        with self.assertRaisesRegex(
                            ValueError, "hybrid_production_method_override"
                        ):
                            operation()
                self.assertEqual(calls, [])

    def test_fusion_does_not_dispatch_dynamic_result_serializers(self):
        empty = SearchResult(
            (),
            {
                "granularity": "child",
                "bundle_sha256": self.store.bundle_sha256,
            },
        )
        calls = []

        def armed_to_dict(_result):
            calls.append("to_dict")
            raise AssertionError("result serializer must not execute")

        with patch.object(SearchResult, "to_dict", armed_to_dict):
            result = fuse_rrf(empty, empty, self.store)
        self.assertEqual(result.candidates, ())
        self.assertEqual(calls, [])

    def test_resolved_scope_descriptor_drift_fails_before_access(self):
        with tempfile.TemporaryDirectory() as temp:
            dense, lexical, _, _ = self._loaded_production_lanes(Path(temp))
            retriever = HybridChildRetriever.from_loaded_artifacts(
                self.store, dense, lexical
            )
            binding = bind_production_harness_runtime(
                store=self.store,
                retriever=retriever,
            )
            calls = []

            def armed_scope(_scope):
                calls.append("scope")
                raise AssertionError("scope descriptor must not execute")

            with patch.object(
                ResolvedScope,
                "allowed_doc_ids",
                property(armed_scope),
            ):
                for operation in (
                    lambda: preflight_production_hybrid(
                        retriever, self.store
                    ),
                    lambda: require_production_hybrid(
                        retriever, self.store
                    ),
                    lambda: validate_harness_runtime_binding(
                        binding=binding,
                        store=self.store,
                        expected_execution_kind="production",
                    ),
                    lambda: retriever.search(
                        "예산",
                        dense_k=1,
                        lexical_k=1,
                        scope=ResolvedScope(),
                    ),
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "hybrid_production_method_override|hybrid_scope_runtime_shape_drift",
                    ):
                        operation()
            self.assertEqual(calls, [])

    def test_runtime_rejects_replaced_public_preflight_before_call(self):
        with tempfile.TemporaryDirectory() as temp:
            dense, lexical, _, _ = self._loaded_production_lanes(Path(temp))
            retriever = HybridChildRetriever.from_loaded_artifacts(
                self.store, dense, lexical
            )
            binding = bind_production_harness_runtime(
                store=self.store,
                retriever=retriever,
            )
            for module, name in (
                (dense_module, "preflight_loaded_dense_artifact"),
                (kiwi_module, "preflight_loaded_lexical_artifact"),
                (fusion_module, "preflight_production_hybrid"),
            ):
                calls = []

                def armed_preflight(*_args, name=name, **_kwargs):
                    calls.append(name)
                    raise AssertionError("replacement preflight must not execute")

                with self.subTest(name=name), patch.object(
                    module, name, armed_preflight
                ):
                    for operation in (
                        lambda: bind_production_harness_runtime(
                            store=self.store,
                            retriever=retriever,
                        ),
                        lambda: validate_harness_runtime_binding(
                            binding=binding,
                            store=self.store,
                            expected_execution_kind="production",
                        ),
                    ):
                        with self.assertRaisesRegex(
                            ValueError,
                            "harness_runtime_validation_dependency_drift",
                        ):
                            operation()
                self.assertEqual(calls, [])

    def test_runtime_rejects_fusion_helper_drift_before_helper_call(self):
        with tempfile.TemporaryDirectory() as temp:
            dense, lexical, _, _ = self._loaded_production_lanes(Path(temp))
            retriever = HybridChildRetriever.from_loaded_artifacts(
                self.store, dense, lexical
            )
            binding = bind_production_harness_runtime(
                store=self.store,
                retriever=retriever,
            )
            for name in (
                "_function_unchanged",
                "_hybrid_binding_values",
                "validate_evidence_store_snapshot",
                "_row_hash",
                "_digest",
            ):
                calls = []

                def armed_helper(*_args, name=name, **_kwargs):
                    calls.append(name)
                    raise AssertionError("replacement helper must not execute")

                with self.subTest(name=name), patch.object(
                    fusion_module, name, armed_helper
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "hybrid_production_validation_dependency_drift|harness_runtime_attestation_drift",
                    ):
                        validate_harness_runtime_binding(
                            binding=binding,
                            store=self.store,
                            expected_execution_kind="production",
                        )
                self.assertEqual(calls, [])

    def test_runtime_entrypoints_reject_internal_helper_drift_before_call(self):
        with tempfile.TemporaryDirectory() as temp:
            dense, lexical, _, _ = self._loaded_production_lanes(Path(temp))
            retriever = HybridChildRetriever.from_loaded_artifacts(
                self.store, dense, lexical
            )
            binding = bind_production_harness_runtime(
                store=self.store,
                retriever=retriever,
            )
            for name, operation in (
                (
                    "_validated_production_runtime_functions",
                    lambda: bind_production_harness_runtime(
                        store=self.store,
                        retriever=retriever,
                    ),
                ),
                (
                    "_require_harness_runtime_authority",
                    lambda: validate_harness_runtime_binding(
                        binding=binding,
                        store=self.store,
                        expected_execution_kind="production",
                    ),
                ),
                (
                    "_validate_harness_runtime_binding",
                    lambda: validate_harness_runtime_binding(
                        binding=binding,
                        store=self.store,
                        expected_execution_kind="production",
                    ),
                ),
                (
                    "_validate_method_authority",
                    lambda: validate_harness_runtime_binding(
                        binding=binding,
                        store=self.store,
                        expected_execution_kind="production",
                    ),
                ),
                (
                    "_function_behavior_sha256",
                    lambda: validate_harness_runtime_binding(
                        binding=binding,
                        store=self.store,
                        expected_execution_kind="production",
                    ),
                ),
                (
                    "validate_evidence_store_snapshot",
                    lambda: validate_harness_runtime_binding(
                        binding=binding,
                        store=self.store,
                        expected_execution_kind="production",
                    ),
                ),
            ):
                calls = []

                def armed_helper(*_args, name=name, **_kwargs):
                    calls.append(name)
                    raise AssertionError("runtime helper must not execute")

                with self.subTest(name=name), patch.object(
                    execution_module, name, armed_helper
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "harness_runtime_validation_dependency_drift",
                    ):
                        operation()
                self.assertEqual(calls, [])

    def test_runtime_entrypoint_rejects_registry_replacement_before_lookup(self):
        with tempfile.TemporaryDirectory() as temp:
            dense, lexical, _, _ = self._loaded_production_lanes(Path(temp))
            retriever = HybridChildRetriever.from_loaded_artifacts(
                self.store, dense, lexical
            )
            binding = bind_production_harness_runtime(
                store=self.store,
                retriever=retriever,
            )
            calls = []

            class ArmedRegistry(dict):
                def get(self, *_args, **_kwargs):
                    calls.append("registry")
                    raise AssertionError("runtime registry must not execute")

            with patch.object(
                execution_module, "_RUNTIME_AUTHORITIES", ArmedRegistry()
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "harness_runtime_validation_dependency_drift",
                ):
                    validate_harness_runtime_binding(
                        binding=binding,
                        store=self.store,
                        expected_execution_kind="production",
                    )
            self.assertEqual(calls, [])

    def test_hybrid_preflight_rejects_registry_entry_callable_before_call(self):
        with tempfile.TemporaryDirectory() as temp:
            dense, lexical, _, _ = self._loaded_production_lanes(Path(temp))
            retriever = HybridChildRetriever.from_loaded_artifacts(
                self.store, dense, lexical
            )
            registry = fusion_module._ISSUED_PRODUCTION_HYBRIDS
            identity = id(retriever)
            original = dict.__getitem__(registry, identity)
            calls = []

            class ArmedReference:
                def __call__(self):
                    calls.append("reference")
                    raise AssertionError("registry entry callable must not execute")

            dict.__setitem__(
                registry,
                identity,
                (ArmedReference(), original[1], original[2]),
            )
            try:
                with self.assertRaisesRegex(
                    ValueError, "hybrid_production_registry_entry_drift"
                ):
                    preflight_production_hybrid(retriever, self.store)
            finally:
                dict.__setitem__(registry, identity, original)
            self.assertEqual(calls, [])

    def test_hybrid_requires_pinned_store_candidates_before_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            dense, lexical, _, _ = self._loaded_production_lanes(Path(temp))
            retriever = HybridChildRetriever.from_loaded_artifacts(
                self.store, dense, lexical
            )
            binding = bind_production_harness_runtime(
                store=self.store,
                retriever=retriever,
            )
            calls = []

            def armed_candidates(*_args, **_kwargs):
                calls.append("candidates")
                raise AssertionError("store candidates must not execute")

            with patch.object(EvidenceStore, "candidates", armed_candidates):
                with self.assertRaisesRegex(
                    ValueError,
                    "hybrid_production_validation_dependency_drift",
                ):
                    validate_harness_runtime_binding(
                        binding=binding,
                        store=self.store,
                        expected_execution_kind="production",
                    )
            self.assertEqual(calls, [])

    def test_hybrid_factory_rejects_dependency_drift_before_call(self):
        with tempfile.TemporaryDirectory() as temp:
            dense, lexical, _, _ = self._loaded_production_lanes(Path(temp))
            for owner, name in (
                (fusion_module, "_ISSUED_REQUIRE_LOADED_DENSE_ARTIFACT"),
                (fusion_module, "_ISSUED_ROW_HASH"),
                (fusion_module, "_ISSUED_HYBRID_BINDING_VALUES"),
                (fusion_module, "_ISSUED_REGISTER_PRODUCTION_HYBRID"),
                (HybridChildRetriever, "__init__"),
            ):
                calls = []

                def armed_dependency(*_args, name=name, **_kwargs):
                    calls.append(name)
                    raise AssertionError("factory dependency must not execute")

                with self.subTest(name=name), patch.object(
                    owner, name, armed_dependency
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "hybrid_production_entry_dependency_drift",
                    ):
                        HybridChildRetriever.from_loaded_artifacts(
                            self.store, dense, lexical
                        )
                self.assertEqual(calls, [])

    def test_hybrid_search_rejects_entry_drift_before_call(self):
        with tempfile.TemporaryDirectory() as temp:
            dense, lexical, _, _ = self._loaded_production_lanes(Path(temp))
            retriever = HybridChildRetriever.from_loaded_artifacts(
                self.store, dense, lexical
            )
            calls = []

            def armed_entry(*_args, **_kwargs):
                calls.append("entry")
                return None

            with patch.object(
                fusion_module,
                "_PINNED_PRODUCTION_HYBRID_ENTRY",
                armed_entry,
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "hybrid_production_entry_dependency_drift",
                ):
                    retriever.search(
                        "예산",
                        dense_k=1,
                        lexical_k=1,
                        scope=ResolvedScope(),
                    )
            self.assertEqual(calls, [])

    def test_hybrid_entries_reject_forged_checker_defaults_before_call(self):
        with tempfile.TemporaryDirectory() as temp:
            dense, lexical, _, _ = self._loaded_production_lanes(Path(temp))
            retriever = HybridChildRetriever.from_loaded_artifacts(
                self.store, dense, lexical
            )
            checker = fusion_module._validate_fusion_entry_dependencies
            original_defaults = checker.__defaults__
            self.assertIsInstance(original_defaults, tuple)
            forged_namespace = dict(original_defaults[0])
            forged_defaults = (forged_namespace, *original_defaults[1:])

            for name, operation in (
                (
                    "_ISSUED_PREFLIGHT_LOADED_DENSE_ARTIFACT",
                    lambda: HybridChildRetriever.from_loaded_artifacts(
                        self.store, dense, lexical
                    ),
                ),
                (
                    "_PINNED_PRODUCTION_HYBRID_ENTRY",
                    lambda: retriever.search(
                        "예산",
                        dense_k=1,
                        lexical_k=1,
                        scope=ResolvedScope(),
                    ),
                ),
            ):
                calls = []

                def armed_dependency(*_args, name=name, **_kwargs):
                    calls.append(name)
                    raise AssertionError("forged dependency must not execute")

                checker.__defaults__ = forged_defaults
                try:
                    with self.subTest(name=name), patch.object(
                        fusion_module, name, armed_dependency
                    ):
                        with self.assertRaisesRegex(
                            ValueError,
                            "hybrid_production_entry_dependency_drift",
                        ):
                            operation()
                finally:
                    checker.__defaults__ = original_defaults
                self.assertEqual(calls, [])

    def test_hybrid_preflight_rejects_nested_dependency_drift_before_access(self):
        with tempfile.TemporaryDirectory() as temp:
            dense, lexical, _, _ = self._loaded_production_lanes(Path(temp))
            retriever = HybridChildRetriever.from_loaded_artifacts(
                self.store, dense, lexical
            )
            calls = []

            class ArmedMapping(dict):
                def __getitem__(self, _key):
                    calls.append("mapping")
                    raise AssertionError("nested dependency must not be accessed")

            with patch.object(
                fusion_module,
                "_PINNED_CONTRACT_GETATTRIBUTES",
                ArmedMapping(),
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "hybrid_production_validation_dependency_drift",
                ):
                    preflight_production_hybrid(retriever, self.store)
            self.assertEqual(calls, [])

    def test_hybrid_preflight_rejects_json_dispatch_drift_before_call(self):
        with tempfile.TemporaryDirectory() as temp:
            dense, lexical, _, _ = self._loaded_production_lanes(Path(temp))
            retriever = HybridChildRetriever.from_loaded_artifacts(
                self.store, dense, lexical
            )
            calls = []

            def armed_dumps(*_args, **_kwargs):
                calls.append("dumps")
                raise AssertionError("json dispatch must not execute")

            with patch.object(fusion_module.json, "dumps", armed_dumps):
                with self.assertRaisesRegex(
                    ValueError,
                    "hybrid_production_validation_dependency_drift",
                ):
                    preflight_production_hybrid(retriever, self.store)
            self.assertEqual(calls, [])

    def test_hybrid_rehashed_proof_and_method_drift_fail_before_store_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            dense, lexical, _, _ = self._loaded_production_lanes(Path(temp))
            retriever = HybridChildRetriever.from_loaded_artifacts(
                self.store, dense, lexical
            )
            proof = retriever.production_binding
            object.__setattr__(proof, "rows_sha256", "1" * 64)
            payload = {
                name: object.__getattribute__(proof, name)
                for name in (
                    "bundle_sha256",
                    "rows_sha256",
                    "dense_attestation_sha256",
                    "lexical_attestation_sha256",
                    "dense_artifact_sha256",
                    "lexical_artifact_sha256",
                    "fusion_config_sha256",
                )
            }
            object.__setattr__(proof, "binding_sha256", fusion_module._digest(payload))
            with self.assertRaisesRegex(
                ValueError, "hybrid_production_binding_drift"
            ):
                require_production_hybrid(retriever, self.store)

        with tempfile.TemporaryDirectory() as temp:
            dense, lexical, _, _ = self._loaded_production_lanes(Path(temp))
            retriever = HybridChildRetriever.from_loaded_artifacts(
                self.store, dense, lexical
            )
            store_calls = []

            def armed_to_dict(_self):
                store_calls.append("store")
                raise AssertionError("store traversal must not execute")

            with patch.object(
                HybridChildRetriever, "search", _replacement_hybrid_search
            ), patch.object(self.store.__class__, "to_dict", armed_to_dict):
                with self.assertRaisesRegex(
                    ValueError, "hybrid_production_method_override"
                ):
                    require_production_hybrid(retriever, self.store)
            self.assertEqual(store_calls, [])

    def test_production_runtime_binding_validation_calls_no_model_helpers(self):
        with tempfile.TemporaryDirectory() as temp:
            dense, lexical, _, _ = self._loaded_production_lanes(Path(temp))
            retriever = HybridChildRetriever.from_loaded_artifacts(
                self.store, dense, lexical
            )
            runtime = dense_module._LOADED_DENSE_RUNTIME.get(dense)
            before = runtime.query_runtime
            with patch.object(
                kiwi_module,
                "_issue_production_tokenizer_runtime_sha256",
                side_effect=AssertionError("tokenizer probe must not execute"),
            ):
                binding = bind_production_harness_runtime(
                    store=self.store,
                    retriever=retriever,
                )
                validate_harness_runtime_binding(
                    binding=binding,
                    store=self.store,
                    expected_execution_kind="production",
                )
            self.assertIs(runtime.query_runtime, before)
            self.assertEqual(before, (None, None))


if __name__ == "__main__":
    unittest.main()
