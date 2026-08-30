from __future__ import annotations

import unittest
from types import SimpleNamespace

from midprojectrag.evaluation import validate_run_record
from midprojectrag.stacks.api import build_api_run_record


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
        timing_ms={"retrieval": 1.0, "generation": 0.0, "total": 1.0},
        usage={
            "input_tokens": 0,
            "output_tokens": 0,
            "embedding_tokens": 4,
            "cost_usd": 0.000001,
            "gpu_seconds": None,
            "peak_vram_gb": None,
        },
        cache_hit=False,
    )


def _context() -> dict[str, object]:
    return {
        "run_id": "run-api-001",
        "case_id": "dev-unknown-001",
        "eval_set_sha256": "b" * 64,
        "config_sha256": "c" * 64,
        "git_commit": "uncommitted",
        "environment": {
            "python_version": "3.12.0",
            "platform": "synthetic-test",
            "region": "local-test",
            "machine_type": "local-test",
            "vcpu": 4,
            "ram_gb": 16.0,
            "gpu_model": None,
            "disk_gb": 100.0,
            "dependency_lock_sha256": "d" * 64,
        },
    }


class RunRecordTests(unittest.TestCase):
    def test_builder_emits_evaluator_compatible_unjudged_record(self) -> None:
        record = build_api_run_record(
            _result(),
            context=_context(),
            corpus_manifest_sha256="e" * 64,
            generator_model="gpt-5-mini",
            embedding_model="text-embedding-3-small",
            seed=None,
            temperature=None,
        )
        self.assertEqual(validate_run_record(record), [])
        self.assertEqual(record["judgment"]["reviewer_ids"], [])
        self.assertEqual(record["reasoning_effort"], "minimal")
        self.assertNotIn("question", repr(record))
        self.assertNotIn("prompt", repr(record))

    def test_personal_large_record_is_explicit_and_evaluator_compatible(self) -> None:
        record = build_api_run_record(
            _result(),
            context=_context(),
            corpus_manifest_sha256="e" * 64,
            generator_model="gpt-5-nano",
            embedding_model="text-embedding-3-large",
            api_profile="personal_experimental",
            embedding_dimensions=3072,
            index_config_sha256="f" * 64,
            seed=None,
            temperature=None,
        )
        self.assertEqual(validate_run_record(record), [])
        self.assertEqual(record["api_profile"], "personal_experimental")
        self.assertEqual(record["embedding_dimensions"], 3072)
        self.assertEqual(record["reasoning_effort"], "minimal")

    def test_builder_rejects_reasoning_drift(self) -> None:
        with self.assertRaisesRegex(ValueError, "reasoning_effort_not_supported"):
            build_api_run_record(
                _result(),
                context=_context(),
                corpus_manifest_sha256="e" * 64,
                generator_model="gpt-5-mini",
                embedding_model="text-embedding-3-small",
                seed=None,
                temperature=None,
                reasoning_effort="low",
            )

    def test_assignment_profile_rejects_large_run_record(self) -> None:
        with self.assertRaisesRegex(ValueError, "run_record_contract_failed"):
            build_api_run_record(
                _result(),
                context=_context(),
                corpus_manifest_sha256="e" * 64,
                generator_model="gpt-5-nano",
                embedding_model="text-embedding-3-large",
                embedding_dimensions=3072,
                index_config_sha256="f" * 64,
                seed=None,
                temperature=None,
            )

    def test_builder_rejects_unknown_context_fields_fail_closed(self) -> None:
        context = _context()
        context["question"] = "restricted"
        with self.assertRaisesRegex(ValueError, "invalid_run_context"):
            build_api_run_record(
                _result(),
                context=context,
                corpus_manifest_sha256="e" * 64,
                generator_model="gpt-5-mini",
                embedding_model="text-embedding-3-small",
                seed=None,
                temperature=None,
            )


if __name__ == "__main__":
    unittest.main()
