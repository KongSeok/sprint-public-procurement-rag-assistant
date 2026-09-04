import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from weakref import ref
import numpy as np

from midprojectrag.evidence.builder import build_store
import midprojectrag.retrieval.dense as dense_module
from midprojectrag.retrieval.dense import (
    KURE_IDENTITY,
    DenseChildLane,
    build_dense,
    load_dense,
    preflight_loaded_dense_artifact,
)
from midprojectrag.retrieval.contracts import RetrievalPostCallContractError
from midprojectrag.stacks.local.hf_embeddings import KureEmbeddingProvider
from tests.test_evidence_builder import chunk


class FakeKure:
    def __init__(self):
        self.__dict__.update(KURE_IDENTITY)
        self.calls = []

    def embed(self, texts):
        self.calls.append(tuple(texts))
        matrix = np.zeros((len(texts), 1024), dtype=np.float32)
        for i, text in enumerate(texts):
            matrix[i, 0 if "alpha" in text else 1] = 1
        return SimpleNamespace(vectors=matrix)


class ChildDenseTests(unittest.TestCase):
    def setUp(self):
        self.store = build_store([chunk("alpha"), chunk("beta", block="block_" + "c" * 24, doc="doc_" + "d" * 24)])

    def _loaded_lane(self):
        provider = FakeKure()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "private" / "dense"
            build_dense(self.store, provider, output_dir=target, data_root=root)
            return load_dense(
                self.store, provider, output_dir=target, data_root=root
            )

    def test_independent_actual_child_text_build_load_search(self):
        provider = FakeKure()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "private" / "dense"
            receipt = build_dense(self.store, provider, output_dir=target, data_root=root, batch_size=1)
            self.assertEqual(receipt["execution_kind"], "synthetic")
            self.assertEqual(provider.calls, [(e.text,) for e in self.store.candidates()])
            lane = load_dense(self.store, provider, output_dir=target, data_root=root)
            result = lane.search("alpha", 2)
            self.assertEqual(self.store.get(result.candidates[0].evidence_id).text, "alpha")
            self.assertTrue(all(c.granularity == "child" for c in result.candidates))
            before = len(provider.calls)
            self.assertEqual(lane.search("alpha", 2, allowed_doc_ids=frozenset()).candidates, ())
            self.assertEqual(before, len(provider.calls))
            self.assertEqual(len(lane.search("alpha", 2, allowed_doc_ids=frozenset({"doc_" + "d" * 24})).candidates), 1)
            with self.assertRaises(ValueError):
                lane.vectors.flags.writeable = True
            with self.assertRaises(FileExistsError):
                build_dense(self.store, provider, output_dir=target, data_root=root)

    def test_post_embed_contract_failure_is_typed_as_post_call(self):
        class Tokenizer:
            def __call__(self, _text, **_kwargs):
                return {"input_ids": [1]}

        class Encoder:
            def __init__(self):
                self.calls = []

            def encode(self, texts, **_kwargs):
                self.calls.append(tuple(texts))
                return np.zeros((len(texts), 3), dtype=np.float32)

        encoder = Encoder()
        provider = KureEmbeddingProvider(
            tokenizer=Tokenizer(),
            encoder=encoder,
        )
        vectors = np.zeros((2, 1024), dtype=np.float32)
        vectors[0, 0] = 1
        vectors[1, 1] = 1
        lane = DenseChildLane._from_verified(
            self.store,
            vectors,
            provider,
            artifact_sha256="a" * 64,
        )

        with self.assertRaisesRegex(
            RetrievalPostCallContractError,
            "dense_post_call_contract_error",
        ):
            lane.search("alpha", 1)
        self.assertEqual(encoder.calls, [("alpha",)])

    def test_identity_dimensions_and_artifact_tampering_fail_closed(self):
        provider = FakeKure()
        with self.assertRaises(ValueError):
            DenseChildLane(self.store, np.ones((2, 768)), provider)
        with self.assertRaises(ValueError):
            DenseChildLane(self.store, np.eye(2, 1024), provider)
        provider.revision = "wrong"
        with self.assertRaises(ValueError):
            DenseChildLane(self.store, np.ones((2, 1024)), provider)
        provider = FakeKure()
        with tempfile.TemporaryDirectory() as temp:
            root, target = Path(temp), Path(temp) / "private" / "dense"
            build_dense(self.store, provider, output_dir=target, data_root=root)
            path = target / "receipt.json"
            receipt = json.loads(path.read_text())
            receipt["rows_sha256"] = "0" * 64
            path.write_text(json.dumps(receipt))
            with self.assertRaises(ValueError):
                load_dense(self.store, provider, output_dir=target, data_root=root)

    def test_fake_provider_cannot_claim_real_execution(self):
        provider = FakeKure()
        provider.execution_kind = "real_local_model"
        with tempfile.TemporaryDirectory() as temp:
            root, target = Path(temp), Path(temp) / "private" / "dense"
            receipt = build_dense(self.store, provider, output_dir=target, data_root=root)
            self.assertEqual(receipt["execution_kind"], "synthetic")

    def test_identity_registry_rejects_malformed_entries_before_dereference(self):
        calls = []

        class Key:
            pass

        class ArmedReference:
            def __call__(self):
                calls.append("armed-reference")
                raise AssertionError("forged registry reference was invoked")

        class ArmedTuple(tuple):
            def __len__(self):
                calls.append("armed-len")
                raise AssertionError("tuple subclass length was invoked")

            def __getitem__(self, index):
                calls.append(("armed-getitem", index))
                raise AssertionError("tuple subclass item access was invoked")

        registry = dense_module._IdentityWeakRegistry()
        key = Key()
        weak = ref(key)
        storage = object.__getattribute__(registry, "_entries")
        malformed = (
            ("non-weak-reference", (ArmedReference(), object())),
            ("wrong-length", (weak, object(), object())),
            ("tuple-subclass", ArmedTuple((weak, object()))),
        )
        operations = (
            ("get", lambda: registry.get(key)),
            ("pop", lambda: registry.pop(key)),
            ("contains", lambda: registry.__contains__(key)),
            ("getitem", lambda: registry[key]),
            ("drop", lambda: registry._drop(id(key), weak)),
        )
        for malformed_name, entry in malformed:
            for operation_name, operation in operations:
                with self.subTest(
                    malformed=malformed_name, operation=operation_name
                ):
                    dict.__setitem__(storage, id(key), entry)
                    with self.assertRaisesRegex(
                        ValueError, "dense_production_registry_entry_drift"
                    ):
                        operation()
                    self.assertEqual(calls, [])

    def test_preflight_rejects_armed_registry_entry_before_call(self):
        lane = self._loaded_lane()
        registry = dense_module._LOADED_DENSE
        storage = object.__getattribute__(registry, "_entries")
        issued_entry = dict.__getitem__(storage, id(lane))
        calls = []

        class ArmedReference:
            def __call__(self):
                calls.append("armed-reference")
                raise AssertionError("forged registry reference was invoked")

        dict.__setitem__(
            storage,
            id(lane),
            (ArmedReference(), tuple.__getitem__(issued_entry, 1)),
        )
        try:
            with self.assertRaisesRegex(
                ValueError, "dense_production_registry_entry_drift"
            ):
                preflight_loaded_dense_artifact(lane, self.store)
        finally:
            dict.__setitem__(storage, id(lane), issued_entry)
        self.assertEqual(calls, [])

    def test_preflight_rejects_replaced_registry_storage_before_access(self):
        lane = self._loaded_lane()
        registry = dense_module._LOADED_DENSE
        issued_storage = object.__getattribute__(registry, "_entries")
        calls = []

        class ArmedStorage(dict):
            def get(self, key, default=None):
                calls.append(("get", key))
                raise AssertionError("forged registry storage was accessed")

        object.__setattr__(registry, "_entries", ArmedStorage())
        try:
            with self.assertRaisesRegex(
                ValueError, "dense_production_registry_storage_drift"
            ):
                preflight_loaded_dense_artifact(lane, self.store)
        finally:
            object.__setattr__(registry, "_entries", issued_storage)
        self.assertEqual(calls, [])

    def test_preflight_rejects_forged_checker_defaults_before_iteration(self):
        lane = self._loaded_lane()
        checker = dense_module._require_dense_production_search_dependencies
        issued_defaults = object.__getattribute__(checker, "__defaults__")
        calls = []

        class ArmedAuthority:
            def __iter__(self):
                calls.append("armed-authority")
                raise AssertionError("forged checker defaults were iterated")

        forged_defaults = list(issued_defaults)
        forged_defaults[1] = ArmedAuthority()
        object.__setattr__(checker, "__defaults__", tuple(forged_defaults))
        try:
            with self.assertRaisesRegex(
                ValueError, "dense_production_search_dependency_override"
            ):
                preflight_loaded_dense_artifact(lane, self.store)
        finally:
            object.__setattr__(checker, "__defaults__", issued_defaults)
        self.assertEqual(calls, [])

    def test_preflight_rejects_forged_registry_checker_defaults_before_iteration(self):
        lane = self._loaded_lane()
        checker = dense_module._require_pinned_dense_registry_authority
        issued_defaults = object.__getattribute__(checker, "__defaults__")
        calls = []

        class ArmedAuthority:
            def __iter__(self):
                calls.append("armed-registry-authority")
                raise AssertionError("forged registry defaults were iterated")

        forged_defaults = (
            tuple.__getitem__(issued_defaults, 0),
            ArmedAuthority(),
            tuple.__getitem__(issued_defaults, 2),
        )
        object.__setattr__(checker, "__defaults__", forged_defaults)
        try:
            with self.assertRaisesRegex(
                ValueError, "dense_production_search_dependency_override"
            ):
                preflight_loaded_dense_artifact(lane, self.store)
        finally:
            object.__setattr__(checker, "__defaults__", issued_defaults)
        self.assertEqual(calls, [])

    def test_preflight_rejects_issued_checker_replacement_before_call(self):
        lane = self._loaded_lane()
        calls = []

        class ArmedChecker:
            def __call__(self, *args, **kwargs):
                calls.append((args, kwargs))
                raise AssertionError("replacement dependency checker was invoked")

        with patch.object(
            dense_module,
            "_ISSUED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES",
            ArmedChecker(),
        ):
            with self.assertRaisesRegex(
                ValueError, "dense_production_search_dependency_override"
            ):
                preflight_loaded_dense_artifact(lane, self.store)
        self.assertEqual(calls, [])

    def test_public_entries_reject_coordinated_checker_replacement_before_call(self):
        lane = self._loaded_lane()
        calls = []

        def armed_checker(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("coordinated replacement checker was invoked")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            entries = (
                ("search", lambda: lane.search("alpha", 1)),
                (
                    "preflight",
                    lambda: preflight_loaded_dense_artifact(lane, self.store),
                ),
                (
                    "require",
                    lambda: dense_module.require_loaded_dense_artifact(
                        lane, self.store
                    ),
                ),
                (
                    "build",
                    lambda: build_dense(
                        self.store,
                        FakeKure(),
                        output_dir=root / "build",
                        data_root=root,
                    ),
                ),
                (
                    "load",
                    lambda: load_dense(
                        self.store,
                        FakeKure(),
                        output_dir=root / "load",
                        data_root=root,
                    ),
                ),
            )
            with (
                patch.object(
                    dense_module,
                    "_require_dense_production_search_dependencies",
                    armed_checker,
                ),
                patch.object(
                    dense_module,
                    "_ISSUED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES",
                    armed_checker,
                ),
                patch.object(
                    dense_module,
                    "_PINNED_REQUIRE_DENSE_PRODUCTION_SEARCH_DEPENDENCIES_CODE",
                    armed_checker.__code__,
                ),
            ):
                for name, entry in entries:
                    with self.subTest(entry=name), self.assertRaisesRegex(
                        ValueError, "dense_production_search_dependency_override"
                    ):
                        entry()
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
