from copy import deepcopy
from dataclasses import replace
from types import FunctionType
import unittest
from unittest.mock import patch

import midprojectrag.orchestration.execution_contracts as execution_module
import midprojectrag.retrieval.fusion as fusion_module
from midprojectrag.evidence import Evidence, EvidenceStore, Locator, ProvenanceParent
from midprojectrag.orchestration import (
    HarnessExecutionConfig,
    HarnessRuntimeBinding,
    bind_production_harness_runtime,
    create_harness_execution_config,
    validate_harness_execution_config,
    validate_harness_runtime_binding,
)
from midprojectrag.retrieval.fusion import HybridChildRetriever


def _store():
    text = "사업 예산 100원"
    parent = ProvenanceParent(
        "doc-a", "pdf_page", text, ("block-a",), Locator(page=1)
    )
    child = Evidence(
        "doc-a",
        "text",
        text,
        parent.parent_id,
        ("block-a",),
        Locator(page=1, char_range=(0, len(text))),
    )
    return EvidenceStore((parent,), (child,))


class _Dense:
    calls = 0

    def search(self, *_args, **_kwargs):
        type(self).calls += 1
        raise AssertionError("dense execution is outside b2")


class _Lexical:
    calls = 0

    def search(self, *_args, **_kwargs):
        type(self).calls += 1
        raise AssertionError("lexical execution is outside b2")


class _Verifier:
    calls = 0

    def verify(self, *_args, **_kwargs):
        type(self).calls += 1
        raise AssertionError("verification is outside b2")


class _Reranker:
    calls = 0

    def rerank(self, *_args, **_kwargs):
        type(self).calls += 1
        raise AssertionError("reranking is outside b2")


def _clock():
    return 0


def _other_clock():
    return 1


def _replacement_search(self, *_args, **_kwargs):
    type(self).calls += 1
    raise AssertionError("replacement must not execute")


_SYNTHETIC_GLOBAL_BEHAVIOR = {"mode": "issued"}
_SYNTHETIC_HELPER_BEHAVIOR = {"mode": "issued"}


def _synthetic_helper():
    return _SYNTHETIC_HELPER_BEHAVIOR["mode"]


class _GlobalVerifier:
    def verify(self, *_args, **_kwargs):
        return _SYNTHETIC_GLOBAL_BEHAVIOR["mode"]


class _HelperVerifier:
    def verify(self, *_args, **_kwargs):
        return _synthetic_helper()


class _MutableDefaultVerifier:
    def verify(self, *_args, policy={"mode": "issued"}, **_kwargs):
        return policy["mode"]


def _synthetic_fixture(*, verifier=True, reranker=True):
    store = _store()
    retriever = HybridChildRetriever(store, _Dense(), _Lexical())
    binding = HarnessRuntimeBinding.for_test(
        store=store,
        retriever=retriever,
        verifier=_Verifier() if verifier else None,
        reranker=_Reranker() if reranker else None,
        clock=_clock,
    )
    return store, retriever, binding


class HarnessExecutionConfigTests(unittest.TestCase):
    def test_config_is_closed_hashed_factory_issued_and_round_trips(self):
        for mode in ("e0_once", "e1_bounded"):
            with self.subTest(mode=mode):
                config = create_harness_execution_config(
                    mode=mode,
                    max_nonterminal_actions=12,
                    max_retrieval_rounds_per_obligation=1,
                    max_no_progress_per_obligation=2,
                    max_context_targets_per_obligation=6,
                    timeout_ms=30_000,
                    rrf_k=60,
                )
                validate_harness_execution_config(config)
                raw = deepcopy(config.to_dict())
                replayed = HarnessExecutionConfig.from_dict(raw)
                self.assertEqual(replayed.to_dict(), raw)
                self.assertEqual(len(config.config_sha256), 64)

        with self.assertRaises(TypeError):
            HarnessExecutionConfig()
        with self.assertRaises(TypeError):
            replace(config, timeout_ms=1)
        clone = object.__new__(HarnessExecutionConfig)
        for name in HarnessExecutionConfig.__slots__:
            if name != "__weakref__":
                object.__setattr__(clone, name, getattr(config, name))
        with self.assertRaisesRegex(
            ValueError, "harness_execution_config_runtime_authority_required"
        ):
            validate_harness_execution_config(clone)
        copied = deepcopy(config)
        with self.assertRaisesRegex(
            ValueError, "harness_execution_config_runtime_authority_required"
        ):
            validate_harness_execution_config(copied)

    def test_config_rejects_unknown_version_bool_float_range_and_hash_drift(self):
        config = create_harness_execution_config(mode="e1_bounded")
        base = config.to_dict()
        invalid = (
            (base | {"extra": 1}, "harness_execution_config_fields"),
            (base | {"schema_version": "2.0"}, "unsupported_harness_execution_config_version"),
            (base | {"mode": "other"}, "invalid_harness_execution_mode"),
            (base | {"max_nonterminal_actions": True}, "invalid_max_nonterminal_actions"),
            (base | {"max_no_progress_per_obligation": 1.0}, "invalid_max_no_progress_per_obligation"),
            (base | {"max_context_targets_per_obligation": 0}, "invalid_max_context_targets_per_obligation"),
            (base | {"timeout_ms": -1}, "invalid_timeout_ms"),
            (base | {"max_retrieval_rounds_per_obligation": 2}, "retrieval_rounds_not_pinned_to_one"),
            (base | {"rrf_k": 61}, "rrf_constant_not_pinned"),
            (base | {"config_sha256": "0" * 64}, "harness_execution_config_hash_mismatch"),
        )
        for raw, code in invalid:
            with self.subTest(code=code), self.assertRaisesRegex(
                (TypeError, ValueError), code
            ):
                HarnessExecutionConfig.from_dict(raw)

        object.__setattr__(config, "timeout_ms", 1)
        with self.assertRaisesRegex(
            ValueError, "harness_execution_config_runtime_authority_drift"
        ):
            validate_harness_execution_config(config)

    def test_config_rejects_armed_slot_or_getattribute_before_access(self):
        config = create_harness_execution_config(mode="e1_bounded")
        calls = []

        def armed_timeout(_self):
            calls.append("timeout")
            return 30_000

        with patch.object(
            HarnessExecutionConfig, "timeout_ms", property(armed_timeout)
        ):
            with self.assertRaisesRegex(
                ValueError, "harness_execution_config_runtime_shape_drift"
            ):
                validate_harness_execution_config(config)
        self.assertEqual(calls, [])

        original_getattribute = HarnessExecutionConfig.__getattribute__

        def armed_getattribute(self, name):
            calls.append(name)
            return original_getattribute(self, name)

        with patch.object(
            HarnessExecutionConfig, "__getattribute__", armed_getattribute
        ):
            with self.assertRaisesRegex(
                ValueError, "harness_execution_config_runtime_shape_drift"
            ):
                validate_harness_execution_config(config)
        self.assertEqual(calls, [])


class HarnessRuntimeBindingTests(unittest.TestCase):
    def setUp(self):
        for cls in (_Dense, _Lexical, _Verifier, _Reranker):
            cls.calls = 0

    def test_synthetic_binding_seals_components_and_is_provider_free(self):
        store, _retriever, binding = _synthetic_fixture()
        validate_harness_runtime_binding(
            binding=binding,
            store=store,
            expected_execution_kind="synthetic",
        )
        payload = binding.to_dict()
        self.assertEqual(payload["execution_kind"], "synthetic")
        self.assertEqual(payload["verifier_capability"], "available")
        self.assertEqual(payload["reranker_capability"], "available")
        self.assertEqual(payload["clock_kind"], "synthetic_test")
        self.assertFalse(hasattr(HarnessRuntimeBinding, "from_dict"))
        self.assertEqual(
            (_Dense.calls, _Lexical.calls, _Verifier.calls, _Reranker.calls),
            (0, 0, 0, 0),
        )
        serialized = str(payload).casefold()
        for forbidden in ("question", "gold", "qrels", "secret", "object at", "/users/"):
            self.assertNotIn(forbidden, serialized)

        with self.assertRaises(TypeError):
            HarnessRuntimeBinding()
        clone = object.__new__(HarnessRuntimeBinding)
        for name in HarnessRuntimeBinding.__slots__:
            if name != "__weakref__":
                object.__setattr__(clone, name, getattr(binding, name))
        with self.assertRaisesRegex(ValueError, "harness_runtime_authority_required"):
            validate_harness_runtime_binding(binding=clone, store=store)

    def test_runtime_rejects_store_component_and_execution_kind_drift(self):
        store, retriever, binding = _synthetic_fixture()
        with self.assertRaisesRegex(ValueError, "harness_runtime_store_identity_mismatch"):
            validate_harness_runtime_binding(binding=binding, store=_store())
        with self.assertRaisesRegex(ValueError, "harness_runtime_execution_kind_mismatch"):
            validate_harness_runtime_binding(
                binding=binding, store=store, expected_execution_kind="production"
            )

        retriever.dense = _Dense()
        with self.assertRaisesRegex(ValueError, "harness_runtime_nested_identity_drift"):
            validate_harness_runtime_binding(binding=binding, store=store)

    def test_runtime_rejects_method_and_clock_drift_without_calls(self):
        store, _retriever, binding = _synthetic_fixture()

        def replacement(self, *_args, **_kwargs):
            type(self).calls += 1
            raise AssertionError("replacement must not execute")

        with patch.object(_Dense, "search", replacement):
            with self.assertRaisesRegex(ValueError, "harness_runtime_method_override"):
                validate_harness_runtime_binding(binding=binding, store=store)
        self.assertEqual(_Dense.calls, 0)

        store, _retriever, binding = _synthetic_fixture()
        authority_clock = _clock
        self.assertIsInstance(authority_clock, FunctionType)
        original = authority_clock.__code__
        authority_clock.__code__ = _other_clock.__code__
        try:
            with self.assertRaisesRegex(ValueError, "harness_runtime_clock_drift"):
                validate_harness_runtime_binding(binding=binding, store=store)
        finally:
            authority_clock.__code__ = original

    def test_runtime_rejects_in_place_code_and_adapter_state_drift(self):
        store, retriever, binding = _synthetic_fixture()
        original = _Dense.search.__code__
        _Dense.search.__code__ = _replacement_search.__code__
        try:
            with self.assertRaisesRegex(
                ValueError, "harness_runtime_method_override"
            ):
                validate_harness_runtime_binding(binding=binding, store=store)
        finally:
            _Dense.search.__code__ = original
        self.assertEqual(_Dense.calls, 0)

        retriever.dense.mode = "drift"
        with self.assertRaisesRegex(
            ValueError, "harness_runtime_component_state_drift"
        ):
            validate_harness_runtime_binding(binding=binding, store=store)

    def test_synthetic_behavior_seals_class_global_and_clock_closure_state(self):
        class ClassStateDense:
            policy = {"mode": "issued"}

            def search(self, *_args, **_kwargs):
                return type(self).policy["mode"]

        def bind_with(*, dense, verifier, clock):
            store = _store()
            retriever = HybridChildRetriever(store, dense, _Lexical())
            binding = HarnessRuntimeBinding.for_test(
                store=store,
                retriever=retriever,
                verifier=verifier,
                reranker=None,
                clock=clock,
            )
            return store, binding

        store, binding = bind_with(
            dense=ClassStateDense(), verifier=None, clock=_clock
        )
        ClassStateDense.policy["mode"] = "drift"
        try:
            with self.assertRaisesRegex(
                ValueError, "harness_runtime_component_state_drift"
            ):
                validate_harness_runtime_binding(binding=binding, store=store)
        finally:
            ClassStateDense.policy["mode"] = "issued"

        store, binding = bind_with(
            dense=_Dense(), verifier=_GlobalVerifier(), clock=_clock
        )
        _SYNTHETIC_GLOBAL_BEHAVIOR["mode"] = "drift"
        try:
            with self.assertRaisesRegex(
                ValueError, "harness_runtime_component_state_drift"
            ):
                validate_harness_runtime_binding(binding=binding, store=store)
        finally:
            _SYNTHETIC_GLOBAL_BEHAVIOR["mode"] = "issued"

        clock_state = [0]

        def closure_clock():
            return clock_state[0]

        store, binding = bind_with(
            dense=_Dense(), verifier=None, clock=closure_clock
        )
        clock_state[0] = 1
        with self.assertRaisesRegex(ValueError, "harness_runtime_clock_drift"):
            validate_harness_runtime_binding(binding=binding, store=store)

    def test_synthetic_behavior_seals_helper_globals_and_mutable_defaults(self):
        def bind_with(verifier):
            store = _store()
            retriever = HybridChildRetriever(store, _Dense(), _Lexical())
            binding = HarnessRuntimeBinding.for_test(
                store=store,
                retriever=retriever,
                verifier=verifier,
                reranker=None,
                clock=_clock,
            )
            return store, binding

        store, binding = bind_with(_HelperVerifier())
        _SYNTHETIC_HELPER_BEHAVIOR["mode"] = "drift"
        try:
            with self.assertRaisesRegex(
                ValueError, "harness_runtime_component_state_drift"
            ):
                validate_harness_runtime_binding(binding=binding, store=store)
        finally:
            _SYNTHETIC_HELPER_BEHAVIOR["mode"] = "issued"

        store, binding = bind_with(_MutableDefaultVerifier())
        defaults = _MutableDefaultVerifier.verify.__kwdefaults__
        self.assertIsInstance(defaults, dict)
        defaults["policy"]["mode"] = "drift"
        try:
            with self.assertRaisesRegex(
                ValueError, "harness_runtime_component_state_drift"
            ):
                validate_harness_runtime_binding(binding=binding, store=store)
        finally:
            defaults["policy"]["mode"] = "issued"

    def test_runtime_rejects_same_code_helper_clone_by_exact_identity(self):
        store, _retriever, binding = _synthetic_fixture()
        issued = fusion_module._PINNED_PRODUCTION_HYBRID_ENTRY
        clone_globals = dict(issued.__globals__)
        clone_globals["_PRODUCTION_HYBRIDS"] = {}
        clone = FunctionType(
            issued.__code__,
            clone_globals,
            issued.__name__,
            issued.__defaults__,
            issued.__closure__,
        )
        clone.__module__ = issued.__module__
        clone.__qualname__ = issued.__qualname__
        self.assertEqual(
            execution_module._function_sha256(clone),
            execution_module._function_sha256(issued),
        )
        with patch.object(
            fusion_module, "_PINNED_PRODUCTION_HYBRID_ENTRY", clone
        ):
            with self.assertRaisesRegex(
                ValueError, "harness_runtime_component_state_drift"
            ):
                validate_harness_runtime_binding(binding=binding, store=store)

    def test_runtime_rejects_armed_descriptors_before_access(self):
        store, _retriever, binding = _synthetic_fixture()
        calls = []

        def armed_kind(_self):
            calls.append("kind")
            return "synthetic"

        with patch.object(
            HarnessRuntimeBinding, "execution_kind", property(armed_kind)
        ):
            with self.assertRaisesRegex(
                ValueError,
                "harness_runtime_validation_dependency_drift|harness_runtime_binding_shape_drift",
            ):
                validate_harness_runtime_binding(binding=binding, store=store)
        self.assertEqual(calls, [])

        original_getattribute = HarnessRuntimeBinding.__getattribute__

        def armed_getattribute(self, name):
            calls.append(name)
            return original_getattribute(self, name)

        with patch.object(
            HarnessRuntimeBinding, "__getattribute__", armed_getattribute
        ):
            with self.assertRaisesRegex(
                ValueError,
                "harness_runtime_validation_dependency_drift|harness_runtime_binding_shape_drift",
            ):
                validate_harness_runtime_binding(binding=binding, store=store)
        self.assertEqual(calls, [])

    def test_method_drift_fails_before_store_traversal(self):
        store, _retriever, binding = _synthetic_fixture()
        store_calls = []

        def armed_to_dict(_self):
            store_calls.append("store")
            raise AssertionError("store traversal must not run")

        with patch.object(_Dense, "search", _replacement_search), patch.object(
            EvidenceStore, "to_dict", armed_to_dict
        ):
            with self.assertRaisesRegex(
                ValueError, "harness_runtime_method_override"
            ):
                validate_harness_runtime_binding(binding=binding, store=store)
        self.assertEqual(store_calls, [])

    def test_root_gate_rejects_forged_checker_defaults_before_dispatch(self):
        store, _retriever, binding = _synthetic_fixture()
        checker = execution_module._validate_runtime_gate_dependencies
        original_defaults = checker.__defaults__
        self.assertIsInstance(original_defaults, tuple)
        forged_namespace = dict(original_defaults[0])
        forged_defaults = (forged_namespace, *original_defaults[1:])
        calls = []

        def armed_validate(*_args, **_kwargs):
            calls.append("validate")
            raise AssertionError("forged dispatch must not execute")

        checker.__defaults__ = forged_defaults
        try:
            with patch.object(
                execution_module,
                "_ISSUED_VALIDATE_HARNESS_RUNTIME_BINDING",
                armed_validate,
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "harness_runtime_validation_dependency_drift",
                ):
                    validate_harness_runtime_binding(
                        binding=binding,
                        store=store,
                    )
        finally:
            checker.__defaults__ = original_defaults
        self.assertEqual(calls, [])

    def test_runtime_registry_entry_is_typed_before_weakref_access(self):
        store, _retriever, binding = _synthetic_fixture()
        registry = execution_module._ISSUED_RUNTIME_AUTHORITIES
        identity = id(binding)
        original = dict.__getitem__(registry, identity)
        calls = []

        class ArmedAuthority:
            @property
            def weak(self):
                calls.append("weak")
                raise AssertionError("authority weak property must not execute")

        dict.__setitem__(registry, identity, ArmedAuthority())
        try:
            with self.assertRaisesRegex(
                ValueError,
                "harness_runtime_authority_required",
            ):
                validate_harness_runtime_binding(binding=binding, store=store)
        finally:
            dict.__setitem__(registry, identity, original)
        self.assertEqual(calls, [])

    def test_runtime_internal_class_dispatch_is_checked_before_call(self):
        store, retriever, _binding = _synthetic_fixture()
        for owner, name in (
            (execution_module._HarnessRuntimeAuthorityDraft, "to_dict"),
            (HarnessRuntimeBinding, "_create"),
        ):
            calls = []

            def armed_method(*_args, name=name, **_kwargs):
                calls.append(name)
                raise AssertionError("runtime class method must not execute")

            with self.subTest(name=name), patch.object(owner, name, armed_method):
                with self.assertRaisesRegex(
                    ValueError,
                    "harness_runtime_validation_dependency_drift",
                ):
                    HarnessRuntimeBinding.for_test(
                        store=store,
                        retriever=retriever,
                        verifier=None,
                        reranker=None,
                        clock=_clock,
                    )
            self.assertEqual(calls, [])

    def test_runtime_public_methods_use_the_root_gate(self):
        store, retriever, binding = _synthetic_fixture()
        for name, operation in (
            ("_require_harness_runtime_authority", binding.to_dict),
            (
                "_bind_harness_runtime",
                lambda: HarnessRuntimeBinding.for_test(
                    store=store,
                    retriever=retriever,
                    verifier=None,
                    reranker=None,
                    clock=_clock,
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

    def test_production_rejects_unapproved_semantic_adapters_without_calls(self):
        store = _store()
        retriever = HybridChildRetriever(store, _Dense(), _Lexical())
        with self.assertRaisesRegex(ValueError, "production_verifier_not_approved"):
            bind_production_harness_runtime(
                store=store,
                retriever=retriever,
                verifier=_Verifier(),
            )
        with self.assertRaisesRegex(ValueError, "production_reranker_not_approved"):
            bind_production_harness_runtime(
                store=store,
                retriever=retriever,
                reranker=_Reranker(),
            )
        with self.assertRaisesRegex(ValueError, "production_verifier_not_approved"):
            execution_module._bind_harness_runtime(
                execution_kind="production",
                store=store,
                retriever=retriever,
                verifier=_Verifier(),
                reranker=None,
                clock=execution_module._PRODUCTION_CLOCK,
            )
        self.assertEqual((_Verifier.calls, _Reranker.calls), (0, 0))


if __name__ == "__main__":
    unittest.main()
