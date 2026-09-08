#!/usr/bin/env python3
"""Benchmark immutable code representation work on a fixed tiny corpus."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import sys
import time
from types import CodeType, FunctionType

import midprojectrag.orchestration.execution_contracts as contracts


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRIVATE_ROOT = (
    PROJECT_ROOT
    / "resources/data_refined/private/diagnostics/controller-path/code-cache-opt1-20260908-001"
)
BENCHMARK_PATH = Path(__file__).resolve()
CONTRACTS_PATH = (
    PROJECT_ROOT / "src/midprojectrag/orchestration/execution_contracts.py"
)
REPEATED_ITERATIONS = 1000


def _plain(value: int) -> int:
    return value + 1


def _branch(value: int, enabled: bool = False) -> int:
    return value if enabled else -value


def _safe_constants() -> tuple[object, ...]:
    return (None, True, 7, 3.5, "controller", b"code")


def _nested_code(value: int) -> int:
    def inner(offset: int) -> int:
        return value + offset

    return inner(2)


def _negative_zero() -> float:
    return -0.0


def _positive_zero() -> float:
    return 0.0


def _unsafe_constant_bypass(value: int) -> bool:
    return value in {1, 2, 3}


def _nested_generator(values: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(value * 2 for value in values)


CORPUS: tuple[tuple[str, FunctionType], ...] = (
    ("plain", _plain),
    ("branch", _branch),
    ("safe_constants", _safe_constants),
    ("nested_code", _nested_code),
    ("negative_zero", _negative_zero),
    ("positive_zero", _positive_zero),
    ("unsafe_constant_bypass", _unsafe_constant_bypass),
    ("nested_generator", _nested_generator),
)


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _observe(function: FunctionType) -> tuple[dict[str, object], bytes]:
    code_payload = contracts._code_payload(function.__code__)
    canonical = _canonical_bytes(code_payload)
    function_sha256 = contracts._function_sha256(function)
    observation = {
        "code_payload_canonical_utf8_hex": canonical.hex(),
        "code_payload_canonical_bytes": len(canonical),
        "code_payload_sha256": sha256(canonical).hexdigest(),
        "function_sha256": function_sha256,
    }
    return observation, canonical + function_sha256.encode("ascii")


def _measure(
    iterations: int,
    *,
    expected: dict[str, dict[str, object]] | None,
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    consumed = sha256()
    first_observations: dict[str, dict[str, object]] = {}
    started_wall = time.perf_counter_ns()
    started_cpu = time.process_time_ns()
    for iteration in range(iterations):
        for name, function in CORPUS:
            observation, digest_input = _observe(function)
            if iteration == 0:
                first_observations[name] = observation
            if expected is not None and observation != expected[name]:
                raise RuntimeError("controller_code_representation_drift")
            consumed.update(name.encode("ascii"))
            consumed.update(digest_input)
    finished_cpu = time.process_time_ns()
    finished_wall = time.perf_counter_ns()
    return (
        {
            "iterations": iterations,
            "corpus_size": len(CORPUS),
            "code_payload_calls": iterations * len(CORPUS),
            "function_sha256_calls": iterations * len(CORPUS),
            "wall_seconds": (finished_wall - started_wall) / 1_000_000_000,
            "process_cpu_seconds": (
                finished_cpu - started_cpu
            ) / 1_000_000_000,
            "consumed_digest_sha256": consumed.hexdigest(),
        },
        first_observations,
    )


def _corpus_features() -> dict[str, object]:
    constants = [
        constant
        for _, function in CORPUS
        for constant in function.__code__.co_consts
    ]
    return {
        "nested_code_present": any(type(value) is CodeType for value in constants),
        "negative_zero_present": any(
            type(value) is float
            and value == 0.0
            and math.copysign(1.0, value) < 0
            for value in constants
        ),
        "positive_zero_present": any(
            type(value) is float
            and value == 0.0
            and math.copysign(1.0, value) > 0
            for value in constants
        ),
        "unsafe_frozenset_present": any(
            type(value) is frozenset for value in constants
        ),
    }


def _reserve_output(output_json: Path) -> Path:
    target = output_json.expanduser().resolve()
    root = PRIVATE_ROOT.resolve()
    if target.suffix != ".json" or not target.is_relative_to(root):
        raise ValueError("controller_code_benchmark_private_json_required")
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError("controller_code_benchmark_output_exists")
    return target


def run_benchmark(output_json: Path) -> dict[str, object]:
    expected_python = (PROJECT_ROOT / ".venv/bin/python3").absolute()
    if Path(sys.executable).absolute() != expected_python:
        raise RuntimeError("controller_code_benchmark_project_python_required")
    if os.environ.get("PYTHONPATH") != "src":
        raise RuntimeError("controller_code_benchmark_pythonpath_src_required")
    if Path(contracts.__file__).resolve() != CONTRACTS_PATH.resolve():
        raise RuntimeError("controller_code_benchmark_import_origin_mismatch")
    target = _reserve_output(output_json)
    source_before = {
        "benchmark": _file_sha256(BENCHMARK_PATH),
        "execution_contracts": _file_sha256(CONTRACTS_PATH),
    }
    features = _corpus_features()
    if not all(features.values()):
        raise RuntimeError("controller_code_benchmark_corpus_invalid")

    cold, observations = _measure(1, expected=None)
    repeated, repeated_first = _measure(
        REPEATED_ITERATIONS,
        expected=observations,
    )
    if repeated_first != observations:
        raise RuntimeError("controller_code_representation_drift")
    source_after = {
        "benchmark": _file_sha256(BENCHMARK_PATH),
        "execution_contracts": _file_sha256(CONTRACTS_PATH),
    }
    if source_after != source_before:
        raise RuntimeError("controller_code_benchmark_source_changed")
    result = {
        "schema_version": "1.0",
        "status": "PASS",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "benchmark": "PERF-CONTROLLER.1.OPT1-code-representation",
        "runtime": {
            "python_executable": sys.executable,
            "pythonpath_contract": "src",
            "execution_contracts_origin": str(Path(contracts.__file__).resolve()),
        },
        "measurement_scope": {
            "fixed_corpus": [name for name, _ in CORPUS],
            "features": features,
            "cold_iterations": 1,
            "repeated_iterations": REPEATED_ITERATIONS,
            "module_import_excluded": True,
            "digest_consumption_included": True,
        },
        "cold": cold,
        "repeated": repeated,
        "canonical_observations": observations,
        "source_before": source_before,
        "source_after": source_after,
        "source_unchanged": source_before == source_after,
        "limitations": [
            "This fixed microbenchmark is not a Controller trajectory benchmark.",
            "Canonical JSON encoding and digest consumption are included in both measurements.",
            "A timing change alone does not establish preserved validation semantics.",
        ],
    }
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(encoded)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-json", type=Path, required=True)
    arguments = parser.parse_args(argv)
    result = run_benchmark(arguments.output_json)
    print(
        json.dumps(
            {
                "status": result["status"],
                "output_json": str(arguments.output_json.resolve()),
                "cold_consumed_digest": result["cold"]["consumed_digest_sha256"],
                "repeated_consumed_digest": result["repeated"]["consumed_digest_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
