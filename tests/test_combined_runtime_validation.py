"""Focused checks for one-pass production runtime attestation validation."""

from pathlib import Path
import sys
import tempfile
import unittest

import midprojectrag.retrieval.dense as dense_module
import midprojectrag.retrieval.kiwi_bm25 as lexical_module
import tests.test_retriever_production_attestation as attestation_fixture
from midprojectrag.orchestration.execution_contracts import (
    bind_production_harness_runtime,
    validate_harness_runtime_binding,
)
from midprojectrag.retrieval.fusion import (
    HybridChildRetriever,
    require_production_hybrid,
)


class CombinedRuntimeValidationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = attestation_fixture.RetrieverProductionAttestationTests(
            "test_only_loaders_mint_lane_attestations_and_factory_binding"
        )
        self.fixture.setUp()
        self.store = self.fixture.store

    def _loaded_runtime(self, root: Path):
        dense, lexical, _, _ = self.fixture._loaded_production_lanes(root)
        retriever = HybridChildRetriever.from_loaded_artifacts(
            self.store, dense, lexical
        )
        return dense, lexical, retriever

    def test_combined_return_reuses_exact_attestations_and_default_shape(self):
        with tempfile.TemporaryDirectory() as temp:
            dense, lexical, retriever = self._loaded_runtime(Path(temp))

            binding = require_production_hybrid(retriever, self.store)
            combined = require_production_hybrid(
                retriever,
                self.store,
                include_attestations=True,
            )

            self.assertIs(require_production_hybrid(retriever, self.store), binding)
            self.assertIs(retriever.production_binding, binding)
            self.assertIs(type(combined), tuple)
            self.assertEqual(len(combined), 3)
            self.assertIs(combined[0], binding)
            self.assertIs(combined[1], dense.loaded_artifact_attestation)
            self.assertIs(combined[2], lexical.loaded_artifact_attestation)

    def test_attestation_option_requires_exact_bool(self):
        for value in (None, 0, 1, "true", object()):
            with self.subTest(value=value), self.assertRaisesRegex(
                ValueError, "invalid_hybrid_attestation_option"
            ):
                require_production_hybrid(
                    object(),
                    object(),
                    include_attestations=value,
                )

    def test_attestation_default_drift_is_pinned_before_validation(self):
        kwdefaults = require_production_hybrid.__kwdefaults__
        original = dict(kwdefaults)
        try:
            kwdefaults["include_attestations"] = True
            with self.assertRaisesRegex(
                ValueError, "hybrid_production_validation_dependency_drift"
            ):
                require_production_hybrid(
                    object(),
                    object(),
                    include_attestations=False,
                )
        finally:
            kwdefaults.clear()
            kwdefaults.update(original)

    def test_runtime_validation_runs_each_lane_full_guard_once(self):
        with tempfile.TemporaryDirectory() as temp:
            _dense, _lexical, retriever = self._loaded_runtime(Path(temp))
            binding = bind_production_harness_runtime(
                store=self.store,
                retriever=retriever,
            )

            _, validate_counts = self._profile_lane_guards(
                lambda: validate_harness_runtime_binding(
                    binding=binding,
                    store=self.store,
                    expected_execution_kind="production",
                )
            )
            self.assertEqual(validate_counts, {"dense": 1, "lexical": 1})

    def _profile_lane_guards(self, operation):
        codes = {
            dense_module.require_loaded_dense_artifact.__code__: "dense",
            lexical_module.require_loaded_lexical_artifact.__code__: "lexical",
        }
        calls = {"dense": 0, "lexical": 0}

        def profile(frame, event, _arg):
            if event == "call" and frame.f_code in codes:
                calls[codes[frame.f_code]] += 1

        previous = sys.getprofile()
        sys.setprofile(profile)
        try:
            result = operation()
        finally:
            sys.setprofile(previous)
        return result, calls


if __name__ == "__main__":
    unittest.main()
