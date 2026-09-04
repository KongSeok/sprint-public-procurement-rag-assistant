from collections import Counter
from pathlib import Path
import sys
import tempfile
from types import FunctionType
import unittest
from unittest.mock import patch

import midprojectrag.retrieval.kiwi_bm25 as kiwi_module
from midprojectrag.evidence.builder import build_store
from midprojectrag.retrieval.kiwi_bm25 import (
    KiwiBM25Lane,
    KiwiTokenizer,
    preflight_loaded_lexical_artifact,
    require_loaded_lexical_artifact,
)
from tests.test_evidence_builder import chunk


class FakeTokens:
    identity = {"engine": "synthetic", "version": "1"}

    def tokenize(self, text):
        return tuple(text.lower().split())


class KiwiBM25Tests(unittest.TestCase):
    def _store(self):
        return build_store(
            [
                chunk("정보시스템 구축 예산"),
                chunk(
                    "운영 기간 입찰 공고",
                    block="block_" + "c" * 24,
                    doc="doc_" + "d" * 24,
                ),
            ]
        )

    def _loaded_synthetic(self, root):
        store = self._store()
        target = root / "private" / "kiwi"
        KiwiBM25Lane.build(store, FakeTokens()).save(target, data_root=root)
        return store, KiwiBM25Lane.load(
            store, FakeTokens(), target, data_root=root
        )

    def _loaded_production(self, root):
        store = self._store()
        target = root / "private" / "kiwi"
        tokenizer = KiwiTokenizer()
        KiwiBM25Lane.build(store, tokenizer).save(target, data_root=root)
        lane = KiwiBM25Lane.load(store, tokenizer, target, data_root=root)
        return store, lane, tokenizer

    def test_independent_scope_tie_and_persistence(self):
        store = build_store([chunk("alpha common"), chunk("rescue common", block="block_" + "c" * 24, doc="doc_" + "d" * 24)])
        lane = KiwiBM25Lane.build(store, FakeTokens())
        hit = lane.search("rescue", 1)
        self.assertEqual(store.get(hit.candidates[0].evidence_id).text, "rescue common")
        self.assertEqual(hit.trace["query_tokens"], ("rescue",))
        self.assertEqual(lane.search("rescue", 1, allowed_doc_ids=frozenset({"doc_" + "b" * 24})).candidates, ())
        self.assertEqual(lane.search("rescue", 1, allowed_doc_ids=frozenset()).trace["tokenizer_calls"], 0)
        ties = lane.search("common", 2).candidates
        self.assertEqual([c.evidence_id for c in ties], sorted(c.evidence_id for c in ties))
        with tempfile.TemporaryDirectory() as temp:
            root, target = Path(temp), Path(temp) / "private" / "kiwi"
            lane.save(target, data_root=root)
            loaded = KiwiBM25Lane.load(store, FakeTokens(), target, data_root=root)
            self.assertEqual(loaded.search("rescue", 2).candidates, hit.candidates)
            with self.assertRaises(FileExistsError):
                lane.save(target, data_root=root)
            wrong = FakeTokens()
            wrong.identity = {"engine": "synthetic", "version": "2"}
            with self.assertRaises(ValueError):
                KiwiBM25Lane.load(store, wrong, target, data_root=root)

    def test_real_pinned_kiwi_korean_tokenization(self):
        tokenizer = KiwiTokenizer()
        tokens = tokenizer.tokenize("정보시스템의 구축과 운영비 100원 API")
        self.assertIn("구축", tokens)
        self.assertIn("api", tokens)
        self.assertIn("100", tokens)
        self.assertNotIn("의", tokens)
        self.assertEqual(tokenizer.identity["kiwi_version"], "0.23.2")
        self.assertEqual(len(tokenizer.identity["tokenizer_sha256"]), 64)
        self.assertIn("default.dict", tokenizer.identity["model_files_sha256"])

    def test_restricted_scores_ignore_out_of_scope_corpus(self):
        a, b, extra = "doc_" + "1" * 24, "doc_" + "2" * 24, "doc_" + "3" * 24
        base = build_store([chunk("alpha", doc=a), chunk("alpha alpha long long", block="block_" + "2" * 24, doc=b)])
        expanded = build_store([chunk("alpha", doc=a), chunk("alpha alpha long long", block="block_" + "2" * 24, doc=b),
                                chunk("alpha " + "noise " * 100, block="block_" + "3" * 24, doc=extra)])
        scope = frozenset({a, b})
        base_scores = {c.evidence_id: c.score for c in KiwiBM25Lane.build(base, FakeTokens()).search("alpha", 10, allowed_doc_ids=scope).candidates}
        expanded_scores = {c.evidence_id: c.score for c in KiwiBM25Lane.build(expanded, FakeTokens()).search("alpha", 10, allowed_doc_ids=scope).candidates}
        self.assertEqual(base_scores.keys(), expanded_scores.keys())
        for identity in base_scores:
            self.assertAlmostEqual(base_scores[identity], expanded_scores[identity])

    def test_loaded_registry_never_hashes_lane(self):
        calls = []
        registry_calls = []
        registry_code = kiwi_module._lookup_loaded_lexical_authority.__code__
        previous = sys.getprofile()

        def armed_hash(_lane):
            calls.append("hash")
            raise AssertionError("lane_hash_was_invoked")

        def profile(frame, event, _arg):
            if event == "call" and frame.f_code is registry_code:
                registry_calls.append(frame.f_code)

        with tempfile.TemporaryDirectory() as temp:
            store, lane = self._loaded_synthetic(Path(temp))
            proof = lane.loaded_artifact_attestation
            self.assertIs(
                require_loaded_lexical_artifact(lane, store),
                proof,
            )
            sys.setprofile(profile)
            try:
                with patch.object(KiwiBM25Lane, "__hash__", armed_hash):
                    with self.assertRaisesRegex(
                        ValueError, "loaded_lexical_search_method_override"
                    ):
                        preflight_loaded_lexical_artifact(lane, store)
                with patch.object(KiwiTokenizer, "__hash__", armed_hash):
                    with self.assertRaisesRegex(
                        ValueError,
                        "lexical_production_tokenizer_method_override",
                    ):
                        preflight_loaded_lexical_artifact(lane, store)
            finally:
                sys.setprofile(previous)
        self.assertEqual(calls, [])
        self.assertEqual(registry_calls, [])

    def test_public_preflight_has_zero_store_and_tokenizer_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            store, lane, _ = self._loaded_production(Path(temp))
            proof = lane.loaded_artifact_attestation
            tokenizer_calls = []
            store_validation_calls = []
            previous = sys.getprofile()

            def profile(frame, event, _arg):
                if event != "call":
                    return
                if frame.f_code is kiwi_module._PINNED_KIWI_TOKENIZE_CODE:
                    tokenizer_calls.append(frame.f_code)
                if (
                    frame.f_code
                    is kiwi_module.validate_evidence_store_snapshot.__code__
                ):
                    store_validation_calls.append(frame.f_code)

            sys.setprofile(profile)
            try:
                with patch.object(
                    type(store),
                    "candidates",
                    side_effect=AssertionError("store_was_traversed"),
                ) as candidates:
                    self.assertIs(
                        preflight_loaded_lexical_artifact(lane, store),
                        proof,
                    )
                    candidates.assert_not_called()
            finally:
                sys.setprofile(previous)
            self.assertEqual(tokenizer_calls, [])
            self.assertEqual(store_validation_calls, [])
            result = lane.search("입찰 공고", 2)
            self.assertTrue(result.candidates)
            self.assertEqual(result.trace["tokenizer_calls"], 2)

    def test_attestation_slot_descriptor_drift_has_zero_side_effects(self):
        with tempfile.TemporaryDirectory() as temp:
            store, lane, _ = self._loaded_production(Path(temp))
            getter_calls = []
            tokenizer_calls = []
            registry_calls = []
            store_validation_calls = []
            previous = sys.getprofile()

            def armed_getter(_proof):
                getter_calls.append("getter")
                raise AssertionError("attestation_getter_was_called")

            def armed_getattribute(_proof, _name):
                getter_calls.append("getattribute")
                raise AssertionError("attestation_getattribute_was_called")

            def profile(frame, event, _arg):
                if event != "call":
                    return
                if frame.f_code is kiwi_module._PINNED_KIWI_TOKENIZE_CODE:
                    tokenizer_calls.append(frame.f_code)
                if (
                    frame.f_code
                    is kiwi_module._lookup_loaded_lexical_authority.__code__
                ):
                    registry_calls.append(frame.f_code)
                if (
                    frame.f_code
                    is kiwi_module.validate_evidence_store_snapshot.__code__
                ):
                    store_validation_calls.append(frame.f_code)

            sys.setprofile(profile)
            try:
                with (
                    patch.object(
                        kiwi_module.LoadedLexicalArtifactAttestation,
                        "attestation_sha256",
                        property(armed_getter),
                    ),
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "loaded_lexical_attestation_descriptor_override",
                    ):
                        preflight_loaded_lexical_artifact(lane, store)
                with (
                    patch.object(
                        kiwi_module.LoadedLexicalArtifactAttestation,
                        "__getattribute__",
                        armed_getattribute,
                    ),
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "loaded_lexical_attestation_descriptor_override",
                    ):
                        preflight_loaded_lexical_artifact(lane, store)
            finally:
                sys.setprofile(previous)
            self.assertEqual(getter_calls, [])
            self.assertEqual(tokenizer_calls, [])
            self.assertEqual(registry_calls, [])
            self.assertEqual(store_validation_calls, [])

    def test_query_dispatch_rejects_mutable_alias_without_calling_it(self):
        with tempfile.TemporaryDirectory() as temp:
            _store, lane, _ = self._loaded_production(Path(temp))
            calls = []

            def armed_tokenize(_tokenizer, _text):
                calls.append("tokenize")
                raise AssertionError("mutable_alias_was_called")

            with patch.object(
                kiwi_module, "_PINNED_KIWI_TOKENIZE", armed_tokenize
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "lexical_production_dispatch_dependency_drift",
                ):
                    lane.search("입찰 공고", 2)
            self.assertEqual(calls, [])

    def test_runtime_tokenizer_code_drift_is_rejected_before_dispatch(self):
        tokenizer = KiwiTokenizer()
        runtime_tokenize = kiwi_module._PINNED_KIWI_RUNTIME_TOKENIZE
        original_code = runtime_tokenize.__code__

        def armed_runtime(*_args, **_kwargs):
            raise AssertionError("runtime_tokenizer_was_dispatched")

        try:
            runtime_tokenize.__code__ = armed_runtime.__code__
            with self.assertRaisesRegex(
                ValueError, "lexical_production_kiwi_runtime_required"
            ):
                tokenizer.tokenize("입찰 공고")
        finally:
            runtime_tokenize.__code__ = original_code

    def test_require_calls_public_preflight(self):
        with tempfile.TemporaryDirectory() as temp:
            store, lane = self._loaded_synthetic(Path(temp))
            calls = []
            preflight_code = preflight_loaded_lexical_artifact.__code__
            previous = sys.getprofile()

            def profile(frame, event, _arg):
                if event == "call" and frame.f_code is preflight_code:
                    calls.append(frame.f_code)

            sys.setprofile(profile)
            try:
                require_loaded_lexical_artifact(lane, store)
            finally:
                sys.setprofile(previous)
            self.assertEqual(calls, [preflight_code])

    def test_method_code_replacement_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            store, lane, _ = self._loaded_production(Path(temp))
            tokenize = KiwiTokenizer.__dict__["tokenize"]
            original_tokenize_code = tokenize.__code__
            try:
                tokenize.__code__ = (lambda _self, _text: ()).__code__
                with self.assertRaisesRegex(
                    ValueError,
                    "lexical_production_tokenizer_method_override",
                ):
                    require_loaded_lexical_artifact(
                        lane, store, production=True
                    )
            finally:
                tokenize.__code__ = original_tokenize_code

            search = KiwiBM25Lane.__dict__["search"]
            original_search_code = search.__code__
            try:
                search.__code__ = (lambda *_args, **_kwargs: None).__code__
                with self.assertRaisesRegex(
                    ValueError, "loaded_lexical_search_method_override"
                ):
                    require_loaded_lexical_artifact(
                        lane, store, production=True
                    )
            finally:
                search.__code__ = original_search_code

    def test_identity_drift_fails_before_store_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            store, lane, tokenizer = self._loaded_production(Path(temp))
            store_validation_calls = []
            validation_code = (
                kiwi_module.validate_evidence_store_snapshot.__code__
            )
            previous = sys.getprofile()

            def profile(frame, event, _arg):
                if event == "call" and frame.f_code is validation_code:
                    store_validation_calls.append(frame.f_code)

            original_tokens = lane.tokens
            lane.tokens = tuple(("forged",) for _ in original_tokens)
            sys.setprofile(profile)
            try:
                with patch.object(
                    type(store),
                    "candidates",
                    side_effect=AssertionError("store_was_traversed"),
                ):
                    with self.assertRaisesRegex(
                        ValueError, "loaded_lexical_snapshot_identity_drift"
                    ):
                        require_loaded_lexical_artifact(
                            lane, store, production=True
                        )
            finally:
                sys.setprofile(previous)
            lane.tokens = original_tokens
            self.assertEqual(store_validation_calls, [])

            original_runtime = tokenizer._kiwi
            tokenizer._kiwi = object()
            store_validation_calls.clear()
            sys.setprofile(profile)
            try:
                with patch.object(
                    type(store),
                    "candidates",
                    side_effect=AssertionError("store_was_traversed"),
                ):
                    with self.assertRaisesRegex(
                        ValueError, "lexical_production_kiwi_runtime_required"
                    ):
                        require_loaded_lexical_artifact(
                            lane, store, production=True
                        )
            finally:
                sys.setprofile(previous)
                tokenizer._kiwi = original_runtime
            self.assertEqual(store_validation_calls, [])

    def test_issued_config_and_proof_cannot_be_reauthorized(self):
        with tempfile.TemporaryDirectory() as temp:
            store, lane = self._loaded_synthetic(Path(temp))
            proof = lane.loaded_artifact_attestation
            lane.k1 = 3.25
            object.__setattr__(
                proof,
                "config_sha256",
                kiwi_module._digest({"k1": lane.k1, "b": lane.b}),
            )
            payload = {
                name: object.__getattribute__(proof, name)
                for name in kiwi_module._LEXICAL_ATTESTATION_FIELDS
            }
            object.__setattr__(
                proof, "attestation_sha256", kiwi_module._digest(payload)
            )
            with self.assertRaisesRegex(
                ValueError, "loaded_lexical_issued_config_drift"
            ):
                require_loaded_lexical_artifact(lane, store)

        with tempfile.TemporaryDirectory() as temp:
            store, lane = self._loaded_synthetic(Path(temp))
            proof = lane.loaded_artifact_attestation
            object.__setattr__(proof, "rows_sha256", "1" * 64)
            payload = {
                name: object.__getattribute__(proof, name)
                for name in kiwi_module._LEXICAL_ATTESTATION_FIELDS
            }
            object.__setattr__(
                proof, "attestation_sha256", kiwi_module._digest(payload)
            )
            with self.assertRaisesRegex(
                ValueError,
                "loaded_lexical_attestation_issued_payload_drift",
            ):
                require_loaded_lexical_artifact(lane, store)

    def test_validation_uses_builtin_counter_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            store, lane = self._loaded_synthetic(Path(temp))
            with (
                patch.object(
                    Counter,
                    "items",
                    side_effect=AssertionError("counter_override_was_called"),
                ),
            ):
                require_loaded_lexical_artifact(lane, store)

    def test_preflight_rejects_normalize_drift_without_dispatch(self):
        with tempfile.TemporaryDirectory() as temp:
            store, lane, _ = self._loaded_production(Path(temp))
            normalize_calls = []
            observed = []
            watched = {
                kiwi_module._lookup_loaded_lexical_authority.__code__,
                kiwi_module.validate_evidence_store_snapshot.__code__,
                kiwi_module._PINNED_KIWI_TOKENIZE_CODE,
            }
            previous = sys.getprofile()

            def armed_normalize(*_args, **_kwargs):
                normalize_calls.append("normalize")
                raise AssertionError("normalize_was_dispatched")

            def profile(frame, event, _arg):
                if event == "call" and frame.f_code in watched:
                    observed.append(frame.f_code)

            sys.setprofile(profile)
            try:
                with (
                    patch.object(
                        kiwi_module.unicodedata,
                        "normalize",
                        armed_normalize,
                    ),
                    patch.object(
                        type(store),
                        "candidates",
                        side_effect=AssertionError("store_was_traversed"),
                    ),
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "lexical_production_dispatch_dependency_drift",
                    ):
                        preflight_loaded_lexical_artifact(lane, store)
            finally:
                sys.setprofile(previous)
            self.assertEqual(normalize_calls, [])
            self.assertEqual(observed, [])

    def test_preflight_rejects_helper_alias_drift_without_dispatch(self):
        with tempfile.TemporaryDirectory() as temp:
            store, lane, _ = self._loaded_production(Path(temp))
            helper_calls = []
            observed = []
            watched = {
                kiwi_module._lookup_loaded_lexical_authority.__code__,
                kiwi_module.validate_evidence_store_snapshot.__code__,
                kiwi_module._PINNED_KIWI_TOKENIZE_CODE,
            }
            previous = sys.getprofile()

            def armed_helper(*_args, **_kwargs):
                helper_calls.append("helper")
                raise AssertionError("helper_was_dispatched")

            def profile(frame, event, _arg):
                if event == "call" and frame.f_code in watched:
                    observed.append(frame.f_code)

            sys.setprofile(profile)
            try:
                with (
                    patch.object(kiwi_module, "_read_lane_state", armed_helper),
                    patch.object(
                        type(store),
                        "candidates",
                        side_effect=AssertionError("store_was_traversed"),
                    ),
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "lexical_production_dispatch_dependency_drift",
                    ):
                        preflight_loaded_lexical_artifact(lane, store)
            finally:
                sys.setprofile(previous)
            self.assertEqual(helper_calls, [])
            self.assertEqual(observed, [])

    def test_registry_identity_is_pinned_before_registry_or_store_access(self):
        with tempfile.TemporaryDirectory() as temp:
            store, lane = self._loaded_synthetic(Path(temp))
            registry_calls = []

            class ArmedRegistry(dict):
                def get(self, *_args, **_kwargs):
                    registry_calls.append("get")
                    raise AssertionError("forged_registry_was_read")

                def items(self, *_args, **_kwargs):
                    registry_calls.append("items")
                    raise AssertionError("forged_registry_was_traversed")

            for forged_registry in ({}, ArmedRegistry()):
                with (
                    self.subTest(registry_type=type(forged_registry).__name__),
                    patch.object(
                        kiwi_module,
                        "_LOADED_LEXICAL_AUTHORITIES",
                        forged_registry,
                    ),
                    patch.object(
                        type(store),
                        "candidates",
                        side_effect=AssertionError("store_was_traversed"),
                    ) as candidates,
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "lexical_production_dispatch_dependency_drift",
                    ):
                        preflight_loaded_lexical_artifact(lane, store)
                    candidates.assert_not_called()
            self.assertEqual(registry_calls, [])

    def test_registry_authority_shape_and_weakref_are_checked_before_call(self):
        with tempfile.TemporaryDirectory() as temp:
            store, lane = self._loaded_synthetic(Path(temp))
            registry = kiwi_module._ISSUED_LOADED_LEXICAL_AUTHORITIES
            identity = id(lane)
            issued = dict.__getitem__(registry, identity)
            weak_calls = []

            class ArmedWeak:
                def __call__(self):
                    weak_calls.append("weak")
                    raise AssertionError("forged_weakref_was_called")

            values = list(tuple(issued))
            values[0] = ArmedWeak()
            forged_weak = kiwi_module._LoadedLexicalAuthority(*values)
            forged_shape = tuple.__new__(
                kiwi_module._LoadedLexicalAuthority,
                (tuple.__getitem__(issued, 0),),
            )
            try:
                for forged in (forged_weak, forged_shape):
                    with self.subTest(size=tuple.__len__(forged)):
                        dict.__setitem__(registry, identity, forged)
                        with patch.object(
                            type(store),
                            "candidates",
                            side_effect=AssertionError("store_was_traversed"),
                        ) as candidates:
                            with self.assertRaisesRegex(
                                ValueError,
                                "loaded_lexical_authority_registry_drift",
                            ):
                                preflight_loaded_lexical_artifact(lane, store)
                            candidates.assert_not_called()
            finally:
                dict.__setitem__(registry, identity, issued)
            self.assertEqual(weak_calls, [])

    def test_public_entries_reject_mutated_checker_defaults_before_call(self):
        with tempfile.TemporaryDirectory() as temp:
            store, lane = self._loaded_synthetic(Path(temp))
            checker = kiwi_module._validate_production_dispatch_dependencies
            checker_code = checker.__code__
            issued_defaults = checker.__defaults__
            copied_namespace = dict(issued_defaults[0])
            checker_calls = []
            previous = sys.getprofile()

            def profile(frame, event, _arg):
                if event == "call" and frame.f_code is checker_code:
                    checker_calls.append(frame.f_code)

            checker.__defaults__ = (copied_namespace, *issued_defaults[1:])
            sys.setprofile(profile)
            try:
                with patch.object(
                    type(store),
                    "candidates",
                    side_effect=AssertionError("store_was_traversed"),
                ) as candidates:
                    for entry, kwargs in (
                        (preflight_loaded_lexical_artifact, {}),
                        (require_loaded_lexical_artifact, {"production": False}),
                    ):
                        with self.subTest(entry=entry.__name__):
                            with self.assertRaisesRegex(
                                ValueError,
                                "lexical_production_dispatch_dependency_drift",
                            ):
                                entry(lane, store, **kwargs)
                    candidates.assert_not_called()
            finally:
                sys.setprofile(previous)
                checker.__defaults__ = issued_defaults
            self.assertEqual(checker_calls, [])

    def test_public_entries_reject_self_consistent_copied_namespace(self):
        with tempfile.TemporaryDirectory() as temp:
            store, lane = self._loaded_synthetic(Path(temp))
            checker = kiwi_module._validate_production_dispatch_dependencies
            checker_code = checker.__code__
            issued_defaults = checker.__defaults__
            copied_namespace = dict(issued_defaults[0])
            forged_defaults = (copied_namespace, *issued_defaults[1:])
            forged_checker = FunctionType(
                checker_code,
                copied_namespace,
                checker.__name__,
                forged_defaults,
            )
            copied_namespace["_validate_production_dispatch_dependencies"] = (
                forged_checker
            )
            copied_namespace[
                "_ISSUED_PRODUCTION_DISPATCH_DEPENDENCY_CHECKER"
            ] = forged_checker
            checker_calls = []
            previous = sys.getprofile()

            def profile(frame, event, _arg):
                if event == "call" and frame.f_code is checker_code:
                    checker_calls.append(frame.f_code)

            sys.setprofile(profile)
            try:
                with (
                    patch.object(
                        kiwi_module,
                        "_validate_production_dispatch_dependencies",
                        forged_checker,
                    ),
                    patch.object(
                        kiwi_module,
                        "_ISSUED_PRODUCTION_DISPATCH_DEPENDENCY_CHECKER",
                        forged_checker,
                    ),
                    patch.object(
                        kiwi_module,
                        "_PRODUCTION_DISPATCH_GLOBALS",
                        copied_namespace,
                    ),
                    patch.object(
                        kiwi_module,
                        "_PINNED_PRODUCTION_DISPATCH_DEPENDENCY_CHECKER_DEFAULTS",
                        forged_defaults,
                    ),
                    patch.object(
                        type(store),
                        "candidates",
                        side_effect=AssertionError("store_was_traversed"),
                    ) as candidates,
                ):
                    for entry, kwargs in (
                        (preflight_loaded_lexical_artifact, {}),
                        (require_loaded_lexical_artifact, {"production": False}),
                    ):
                        with self.subTest(entry=entry.__name__):
                            issued_kwdefaults = dict(entry.__kwdefaults__)
                            entry.__kwdefaults__.update(
                                {
                                    "_dependency_checker": forged_checker,
                                    "_dependency_checker_code": checker_code,
                                    "_dependency_checker_defaults": forged_defaults,
                                    "_dependency_checker_globals": copied_namespace,
                                }
                            )
                            try:
                                with self.assertRaisesRegex(
                                    ValueError,
                                    "lexical_production_dispatch_dependency_drift",
                                ):
                                    entry(lane, store, **kwargs)
                            finally:
                                entry.__kwdefaults__.clear()
                                entry.__kwdefaults__.update(issued_kwdefaults)
                    candidates.assert_not_called()
            finally:
                sys.setprofile(previous)
            self.assertEqual(checker_calls, [])


if __name__ == "__main__":
    unittest.main()
