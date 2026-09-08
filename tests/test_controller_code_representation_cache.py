"""Focused checks for the bounded immutable CodeType representation cache."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import inspect
import json
import math
from types import FunctionType
import unittest

import scripts.benchmark_controller_code_representation as benchmark
import midprojectrag.orchestration.execution_contracts as contracts


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _reference_function_payload(function: FunctionType) -> dict[str, object]:
    kwdefaults = function.__kwdefaults__
    return {
        "schema_version": contracts.SCHEMA_VERSION,
        "module": function.__module__,
        "qualname": function.__qualname__,
        "code": contracts._code_payload(function.__code__),
        "defaults": contracts._stable_code_value(function.__defaults__),
        "kwdefaults": (
            None
            if kwdefaults is None
            else {
                key: contracts._stable_code_value(value)
                for key, value in sorted(kwdefaults.items())
            }
        ),
    }


def _reference_function_input_bytes(function: FunctionType) -> bytes:
    return _canonical(_reference_function_payload(function))


def _reference_function_sha256(function: FunctionType) -> str:
    return sha256(_reference_function_input_bytes(function)).hexdigest()


def _cached_function_input_bytes(function: FunctionType) -> bytes:
    code = function.__code__
    code_bytes = contracts._read_code_payload_cache(code)
    if code_bytes is None:
        code_bytes = contracts._store_code_payload_cache(code)
    if code_bytes is None:
        raise AssertionError("cache-eligible function unexpectedly bypassed")
    kwdefaults = function.__kwdefaults__
    return contracts._canonical_function_sha256_bytes(
        code=code_bytes,
        defaults=contracts._stable_code_value(function.__defaults__),
        kwdefaults=(
            None
            if kwdefaults is None
            else {
                key: contracts._stable_code_value(value)
                for key, value in sorted(kwdefaults.items())
            }
        ),
        module=function.__module__,
        qualname=function.__qualname__,
    )


def _closure_value(function: FunctionType, name: str):
    cells = dict(zip(function.__code__.co_freevars, function.__closure__))
    return cells[name].cell_contents


class ControllerCodeRepresentationCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        contracts._clear_code_payload_cache()
        self.addCleanup(contracts._clear_code_payload_cache)

    def test_fixed_corpus_code_fragments_and_complete_hash_inputs_match(self):
        observations = {}
        for name, function in benchmark.CORPUS:
            with self.subTest(name=name):
                contracts._clear_code_payload_cache()
                expected_code = _canonical(
                    contracts._code_payload(function.__code__)
                )
                expected_input = _reference_function_input_bytes(function)
                expected_digest = sha256(expected_input).hexdigest()

                actual_digest = contracts._function_sha256(function)
                self.assertEqual(actual_digest, expected_digest)
                if contracts._code_payload_cache_safe(function.__code__):
                    cached = contracts._read_code_payload_cache(function.__code__)
                    self.assertEqual(cached, expected_code)
                    self.assertEqual(
                        _cached_function_input_bytes(function), expected_input
                    )
                else:
                    self.assertIsNone(
                        contracts._read_code_payload_cache(function.__code__)
                    )
                    self.assertEqual(
                        contracts._code_payload_cache_snapshot()["entries"], 0
                    )
                observations[name] = expected_code

        self.assertNotEqual(
            observations["negative_zero"], observations["positive_zero"]
        )
        negative = contracts._code_payload(benchmark._negative_zero.__code__)
        self.assertLess(
            math.copysign(
                1.0,
                next(
                    value
                    for value in negative["consts"]
                    if type(value) is float
                ),
            ),
            0,
        )

    def test_fixed_outer_encoding_preserves_unicode_escapes_and_nonfinite(self):
        def special(first=None, second=None, *, flag=None, missing=None):
            return first, second, flag, missing

        special.__defaults__ = ('한글"\\\n', float("inf"))
        special.__kwdefaults__ = {
            "flag": -0.0,
            "missing": float("nan"),
        }
        special.__module__ = 'módulo."\\\n'
        special.__qualname__ = '경로.<locals>.함수"\\'

        expected = _reference_function_input_bytes(special)
        actual = _cached_function_input_bytes(special)
        self.assertEqual(actual, expected)
        self.assertEqual(
            contracts._function_sha256(special), sha256(expected).hexdigest()
        )
        positions = [
            actual.index(field)
            for field in (
                b'"code":',
                b'"defaults":',
                b'"kwdefaults":',
                b'"module":',
                b'"qualname":',
                b'"schema_version":',
            )
        ]
        self.assertEqual(positions, sorted(positions))
        decoded = json.loads(actual)
        self.assertEqual(decoded["defaults"][1], {"type": "nonfinite-float"})
        self.assertEqual(
            decoded["kwdefaults"]["missing"], {"type": "nonfinite-float"}
        )
        self.assertLess(
            math.copysign(1.0, decoded["kwdefaults"]["flag"]), 0
        )

    def test_code_payload_is_fresh_without_cache_decode(self):
        code = benchmark._nested_code.__code__
        first = contracts._code_payload(code)
        second = contracts._code_payload(code)
        self.assertIsNot(first, second)
        self.assertIsNot(first["names"], second["names"])
        first["names"].append("poison")
        nested_first = next(
            value
            for value in first["consts"]
            if type(value) is dict and "varnames" in value
        )
        nested_first["varnames"].append("poison")
        third = contracts._code_payload(code)
        self.assertNotIn("poison", second["names"])
        self.assertNotIn("poison", third["names"])
        nested_third = next(
            value
            for value in third["consts"]
            if type(value) is dict and "varnames" in value
        )
        self.assertNotIn("poison", nested_third["varnames"])
        self.assertEqual(
            contracts._code_payload_cache_snapshot()["entries"], 0
        )

    def test_identity_and_original_bypass_paths(self):
        original = benchmark._plain.__code__.replace()
        distinct = benchmark._plain.__code__.replace()
        self.assertIsNot(original, distinct)
        self.assertEqual(
            _canonical(contracts._code_payload(original)),
            _canonical(contracts._code_payload(distinct)),
        )
        first = contracts._store_code_payload_cache(original)
        second = contracts._store_code_payload_cache(distinct)
        self.assertIsInstance(first, bytes)
        self.assertIsInstance(second, bytes)
        self.assertIs(contracts._read_code_payload_cache(original), first)
        self.assertEqual(
            contracts._code_payload_cache_snapshot()["entries"], 2
        )

        unsafe_codes = (
            benchmark._unsafe_constant_bypass.__code__,
            benchmark._plain.__code__.replace(co_consts=(None, ["mutable"])),
            benchmark._plain.__code__.replace(co_consts=(None, object())),
        )
        for code in unsafe_codes:
            with self.subTest(constant_type=type(code.co_consts[1]).__name__):
                contracts._clear_code_payload_cache()
                self.assertIsNone(contracts._store_code_payload_cache(code))
                function = FunctionType(
                    code, {"__name__": __name__}, "unsafe_observed"
                )
                self.assertEqual(
                    contracts._function_sha256(function),
                    _reference_function_sha256(function),
                )
                state = contracts._code_payload_cache_snapshot()
                self.assertEqual(state["entries"], 0)
                self.assertEqual(state["bypasses"], 2)

        contracts._clear_code_payload_cache()
        oversized = benchmark._plain.__code__.replace(
            co_consts=(
                None,
                "x" * (contracts._CODE_PAYLOAD_CACHE_MAX_CANONICAL_BYTES + 1),
            )
        )
        self.assertIsNone(contracts._store_code_payload_cache(oversized))
        self.assertEqual(
            contracts._code_payload_cache_snapshot()["entries"], 0
        )

        contracts._clear_code_payload_cache()
        surrogate = benchmark._plain.__code__.replace(co_consts=(None, "\ud800"))
        self.assertEqual(
            contracts._code_payload(surrogate)["consts"][1], "\ud800"
        )
        surrogate_function = FunctionType(
            surrogate, {"__name__": __name__}, "surrogate_observed"
        )
        with self.assertRaises(UnicodeEncodeError):
            _reference_function_sha256(surrogate_function)
        with self.assertRaises(UnicodeEncodeError):
            contracts._function_sha256(surrogate_function)
        self.assertEqual(
            contracts._code_payload_cache_snapshot()["entries"], 0
        )

    def test_bounds_mirror_eviction_and_concurrent_hits(self):
        base = benchmark._plain.__code__
        codes = [base.replace(co_consts=(None, value)) for value in range(129)]
        for code in codes:
            contracts._store_code_payload_cache(code)
        state = contracts._code_payload_cache_snapshot()
        self.assertEqual(state["entries"], 128)
        self.assertEqual(state["evictions"], 1)
        self.assertLessEqual(
            state["retained_bytes"],
            contracts._CODE_PAYLOAD_CACHE_MAX_CANONICAL_BYTES,
        )

        contracts._clear_code_payload_cache()
        chunk_size = (
            contracts._CODE_PAYLOAD_CACHE_MAX_CANONICAL_BYTES // 3 + 4096
        )
        byte_bound_codes = [
            base.replace(co_consts=(None, character * chunk_size))
            for character in ("a", "b", "c")
        ]
        for code in byte_bound_codes:
            contracts._store_code_payload_cache(code)
        byte_state = contracts._code_payload_cache_snapshot()
        self.assertLess(byte_state["entries"], len(byte_bound_codes))
        self.assertGreater(byte_state["evictions"], 0)
        self.assertLessEqual(
            byte_state["retained_bytes"],
            contracts._CODE_PAYLOAD_CACHE_MAX_CANONICAL_BYTES,
        )
        cache = _closure_value(contracts._read_code_payload_cache, "cache")
        mirror = _closure_value(contracts._read_code_payload_cache, "mirror")
        self.assertEqual(len(cache), len(mirror))
        self.assertTrue(all(mirror[key] is entry for key, entry in cache.items()))

        contracts._clear_code_payload_cache()
        expected = _reference_function_sha256(benchmark._safe_constants)
        with ThreadPoolExecutor(max_workers=8) as pool:
            digests = list(
                pool.map(
                    lambda _: contracts._function_sha256(
                        benchmark._safe_constants
                    ),
                    range(64),
                )
            )
        self.assertEqual(set(digests), {expected})
        self.assertEqual(
            contracts._code_payload_cache_snapshot()["entries"], 1
        )

    def test_live_fields_helper_pins_and_mirror_fail_closed(self):
        namespace = {"__name__": __name__, "LIVE_VALUE": 1}
        exec(
            "def observed(value=1, *, scale=2):\n"
            "    return (value + LIVE_VALUE) * scale\n",
            namespace,
        )
        function = namespace["observed"]
        initial = contracts._function_sha256(function)
        function.__defaults__ = (3,)
        defaults_changed = contracts._function_sha256(function)
        self.assertNotEqual(initial, defaults_changed)
        function.__kwdefaults__["scale"] = 4
        kwdefaults_changed = contracts._function_sha256(function)
        self.assertNotEqual(defaults_changed, kwdefaults_changed)
        function.__module__ = "changed.module"
        module_changed = contracts._function_sha256(function)
        self.assertNotEqual(kwdefaults_changed, module_changed)
        function.__qualname__ = "changed.qualname"
        qualname_changed = contracts._function_sha256(function)
        self.assertNotEqual(module_changed, qualname_changed)

        def replacement(value=1, *, scale=2):
            return (value - LIVE_VALUE) * scale

        function.__code__ = replacement.__code__
        code_changed = contracts._function_sha256(function)
        self.assertNotEqual(qualname_changed, code_changed)
        self.assertEqual(code_changed, _reference_function_sha256(function))

        global_before = contracts._function_behavior_sha256(function)
        namespace["LIVE_VALUE"] = 5
        self.assertNotEqual(
            global_before, contracts._function_behavior_sha256(function)
        )

        def factory():
            captured = [1]

            def closure():
                return captured[0]

            return closure, captured

        closure, captured = factory()
        closure_before = contracts._function_behavior_sha256(closure)
        captured[0] = 2
        self.assertNotEqual(
            closure_before, contracts._function_behavior_sha256(closure)
        )

        self.assertEqual(
            tuple(inspect.signature(contracts._store_code_payload_cache).parameters),
            ("code",),
        )
        helper = contracts._canonical_function_sha256_bytes
        original_code = helper.__code__
        try:
            helper.__code__ = (lambda **values: b"{}").__code__
            with self.assertRaisesRegex(
                ValueError, "harness_runtime_validation_dependency_drift"
            ):
                contracts._validate_runtime_gate_dependencies()
        finally:
            helper.__code__ = original_code

        original_kwdefaults = helper.__kwdefaults__
        try:
            helper.__kwdefaults__ = {"code": b"{}"}
            with self.assertRaisesRegex(
                ValueError, "harness_runtime_validation_dependency_drift"
            ):
                contracts._validate_runtime_gate_dependencies()
        finally:
            helper.__kwdefaults__ = original_kwdefaults
        contracts._validate_runtime_gate_dependencies()

        contracts._clear_code_payload_cache()
        code = benchmark._plain.__code__
        contracts._function_sha256(benchmark._plain)
        cache = _closure_value(contracts._read_code_payload_cache, "cache")
        mirror = _closure_value(contracts._read_code_payload_cache, "mirror")
        entry = mirror.pop(id(code))
        try:
            with self.assertRaisesRegex(
                ValueError, "harness_runtime_validation_dependency_drift"
            ):
                contracts._function_sha256(benchmark._plain)
        finally:
            mirror[id(code)] = entry
        self.assertIs(cache[id(code)], mirror[id(code)])
        contracts._clear_code_payload_cache()
        self.assertEqual(cache, {})
        self.assertEqual(mirror, {})


if __name__ == "__main__":
    unittest.main()
