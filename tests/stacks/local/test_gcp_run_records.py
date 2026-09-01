from __future__ import annotations

import copy
import unittest
from types import SimpleNamespace

from midprojectrag.evaluation import validate_run_record
from midprojectrag.stacks.local.run_records import (
    GCP_EMBEDDING_DIMENSIONS,
    GCP_EMBEDDING_MODEL,
    GCP_EMBEDDING_MODEL_REVISION,
    GCP_GENERATOR_MODEL,
    GCP_GENERATOR_MODEL_REVISION,
    GCP_QUANTIZATION,
    GCP_RUNTIME,
    GCP_RUNTIME_VERSION,
    build_gcp_run_record,
)


def _result() -> SimpleNamespace:
    return SimpleNamespace(
        response={
            "schema_version": "1.0",
            "request_id": "req-1",
            "status": "abstained",
            "answer": "제공된 문서에서 답변 근거를 찾지 못했습니다.",
            "citations": [],
            "abstention": {
                "reason": "insufficient_evidence",
                "detail": "선택한 문서 범위에서 검색 근거를 찾지 못했습니다.",
            },
            "error": None,
            "trace_id": "a" * 32,
        },
        retrieval=[],
        timing_ms={"retrieval": 1.0, "generation": 2.0, "total": 3.0},
        usage={
            "input_tokens": 11,
            "output_tokens": 7,
            "embedding_tokens": 5,
            "cost_usd": None,
            "gpu_seconds": 2.5,
            "peak_vram_gb": 18.25,
        },
        cache_hit=False,
    )


def _context(*, disk_gb: float = 100.0) -> dict[str, object]:
    return {
        "run_id": "run-gcp-001",
        "case_id": "dev-unknown-001",
        "eval_set_sha256": "b" * 64,
        "config_sha256": "c" * 64,
        "git_commit": "uncommitted",
        "environment": {
            "python_version": "3.12.0",
            "platform": "linux-x86_64",
            "region": "us-central1",
            "machine_type": "g2-standard-4",
            "vcpu": 4,
            "ram_gb": 16.0,
            "gpu_model": "NVIDIA L4",
            "disk_gb": disk_gb,
            "dependency_lock_sha256": "d" * 64,
        },
    }


def _build(**overrides: object) -> dict[str, object]:
    arguments: dict[str, object] = {
        "context": _context(),
        "corpus_manifest_sha256": "e" * 64,
        "embedding_model_revision": GCP_EMBEDDING_MODEL_REVISION,
        "generator_model_revision": GCP_GENERATOR_MODEL_REVISION,
        "index_config_sha256": "f" * 64,
        "runtime_version": GCP_RUNTIME_VERSION,
        "seed": 7,
        "temperature": 0.0,
    }
    arguments.update(overrides)
    return build_gcp_run_record(_result(), **arguments)


class GcpRunRecordTests(unittest.TestCase):
    def test_builder_emits_official_reproducible_record(self) -> None:
        record = _build()

        self.assertEqual(validate_run_record(record), [])
        self.assertEqual(record["generator_model"], GCP_GENERATOR_MODEL)
        self.assertEqual(record["embedding_model"], GCP_EMBEDDING_MODEL)
        self.assertEqual(record["embedding_dimensions"], GCP_EMBEDDING_DIMENSIONS)
        self.assertEqual(record["embedding_model_revision"], GCP_EMBEDDING_MODEL_REVISION)
        self.assertEqual(record["generator_model_revision"], GCP_GENERATOR_MODEL_REVISION)
        self.assertEqual(record["runtime"], GCP_RUNTIME)
        self.assertEqual(record["runtime_version"], GCP_RUNTIME_VERSION)
        self.assertEqual(record["quantization"], GCP_QUANTIZATION)
        self.assertEqual(record["usage"]["cost_usd"], None)
        self.assertNotIn("api_profile", record)
        self.assertNotIn("reasoning_effort", record)
        self.assertNotIn("question", repr(record))
        self.assertNotIn("prompt", repr(record))

    def test_builder_requires_full_model_revisions_and_index_hash(self) -> None:
        invalid_values = (
            ("embedding_model_revision", "1" * 39),
            ("embedding_model_revision", "1" * 40),
            ("generator_model_revision", "2" * 41),
            ("generator_model_revision", "2" * 40),
            ("index_config_sha256", "f" * 63),
        )
        for field, value in invalid_values:
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "run_record_contract_failed"):
                    _build(**{field: value})

    def test_builder_requires_measured_gpu_usage_and_null_cost(self) -> None:
        mutations = {
            "cost": ("cost_usd", 0.0),
            "gpu_seconds": ("gpu_seconds", None),
            "peak_vram": ("peak_vram_gb", None),
        }
        for label, (field, value) in mutations.items():
            with self.subTest(label=label):
                result = _result()
                result.usage[field] = value
                with self.assertRaisesRegex(ValueError, "run_record_contract_failed"):
                    build_gcp_run_record(
                        result,
                        context=_context(),
                        corpus_manifest_sha256="e" * 64,
                        embedding_model_revision=GCP_EMBEDDING_MODEL_REVISION,
                        generator_model_revision=GCP_GENERATOR_MODEL_REVISION,
                        index_config_sha256="f" * 64,
                        runtime_version=GCP_RUNTIME_VERSION,
                        seed=7,
                        temperature=0.0,
                    )

    def test_builder_enforces_user_confirmed_100gb_gate(self) -> None:
        self.assertEqual(_build(context=_context(disk_gb=100.0))["environment"]["disk_gb"], 100.0)
        with self.assertRaisesRegex(ValueError, "run_record_contract_failed"):
            _build(context=_context(disk_gb=100.1))

    def test_builder_requires_observed_exact_runtime_version(self) -> None:
        with self.assertRaisesRegex(ValueError, "gcp_runtime_version_mismatch"):
            _build(runtime_version="0.8.5")

    def test_builder_rejects_unknown_context_fields_fail_closed(self) -> None:
        context = copy.deepcopy(_context())
        context["api_profile"] = "assignment"
        with self.assertRaisesRegex(ValueError, "invalid_run_context"):
            _build(context=context)


if __name__ == "__main__":
    unittest.main()
