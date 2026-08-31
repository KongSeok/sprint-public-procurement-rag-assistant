from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import midprojectrag.gcp_local_baseline as baseline
from midprojectrag.ingest.common import canonical_json, sha256_file
from midprojectrag.stacks.local.generation import LOCAL_SYSTEM_INSTRUCTIONS


CONFIG_SHA = "a" * 64
EVAL_SHA = "b" * 64
INDEX_SHA = "c" * 64
VECTORS_SHA = "d" * 64
OTHER_SHA = "e" * 64
CORPUS_SHA = "f" * 64
ROWS_SHA = "8" * 64
METADATA_SHA = "9" * 64
CHUNK_A = "chunk_" + "1" * 24
DOC_A = "doc_" + "2" * 24
DOC_B = "doc_" + "3" * 24
BLOCK_A = "block_" + "4" * 24

INDEX_PROVENANCE = {
    "schema_version": "1.0",
    "engine": "numpy",
    "count": 9331,
    "dimensions": 1024,
    "chunk_artifact_sha256": baseline.CHUNKS_SHA256,
    "index_config_sha256": INDEX_SHA,
    "vectors_sha256": VECTORS_SHA,
    "rows_sha256": ROWS_SHA,
    "metadata_sha256": METADATA_SHA,
}
EXPECTED_RUN_ID = (
    f"mac-{CONFIG_SHA[:12]}-{EVAL_SHA[:12]}-"
    f"{VECTORS_SHA[:12]}-{METADATA_SHA[:12]}"
)


def _case(
    case_id: str = "hardening-001",
    *,
    decision: str = "answer",
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "case_id": case_id,
        "task_type": "unknown" if decision == "abstain" else "single_doc",
        "question": "private hardening question",
        "history": [],
        "document_scope": (
            {"mode": "all", "doc_ids": []}
            if decision == "abstain"
            else {"mode": "explicit", "doc_ids": [DOC_A]}
        ),
        "review": {"author": "draft", "reviewer": "pending", "status": "draft"},
        "gold": {
            "decision": decision,
            "required_doc_ids": [] if decision == "abstain" else [DOC_A],
            "evidence_refs": (
                []
                if decision == "abstain"
                else [
                    {
                        "doc_id": DOC_A,
                        "source_block_id": BLOCK_A,
                        "locator_hash": CONFIG_SHA,
                    }
                ]
            ),
            "abstain_reason": "insufficient_evidence" if decision == "abstain" else None,
        },
    }


def _retrieval_row(
    rank: int,
    *,
    doc_id: str = DOC_A,
    score: float = 0.9,
) -> dict[str, object]:
    return {
        "rank": rank,
        "doc_id": doc_id,
        "chunk_id": f"chunk_{rank:024x}",
        "source_block_ids": [BLOCK_A],
        "score": score,
    }


def _candidate(
    case: dict[str, object],
    *,
    config_sha256: str = CONFIG_SHA,
    eval_set_sha256: str = EVAL_SHA,
    index_provenance: dict[str, object] | None = None,
    retrieval: list[dict[str, object]] | None = None,
    status: str = "abstained",
    run_id: str = EXPECTED_RUN_ID,
) -> dict[str, object]:
    request = baseline.build_golden_request(
        case,
        config_sha256=config_sha256,
        max_citations=3,
    )
    response = {
        "schema_version": "1.0",
        "request_id": request["request_id"],
        "status": status,
        "answer": (
            "제공된 문서에서 답변 근거를 찾지 못했습니다."
            if status == "abstained"
            else ""
        ),
        "citations": [],
        "abstention": (
            {"reason": "insufficient_evidence", "detail": "private"}
            if status == "abstained"
            else None
        ),
        "error": (
            {"code": "pipeline_failed", "message": "safe"}
            if status == "error"
            else None
        ),
        "trace_id": "trace-hardening",
    }
    result = SimpleNamespace(
        retrieval=list(retrieval or []),
        response=response,
        timing_ms={"retrieval": 1.0, "generation": 2.0, "total": 3.0},
        usage={
            "input_tokens": 1,
            "output_tokens": 1,
            "embedding_tokens": 1,
            "cost_usd": 0.0,
            "gpu_seconds": None,
            "peak_vram_gb": None,
        },
        cache_hit=False,
    )
    candidate = baseline.build_mac_candidate(
        case=case,
        request=request,
        result=result,
        run_id=run_id,
        config_sha256=config_sha256,
        eval_set_sha256=eval_set_sha256,
        index_provenance=(
            dict(INDEX_PROVENANCE)
            if index_provenance is None
            else index_provenance
        ),
        prompt=None,
        prompt_sha256=None,
    )
    return candidate


def _write_index_metadata(index_path: Path) -> None:
    index_path.mkdir(parents=True, exist_ok=True)
    vectors_path = index_path / "vectors.npy"
    rows_path = index_path / "rows.jsonl"
    vectors_path.write_bytes(b"synthetic normalized vectors")
    rows_path.write_text('{"chunk_id":"' + CHUNK_A + '","doc_id":"' + DOC_A + '"}\n')
    metadata = {
        "schema_version": "1.0",
        "engine": "numpy",
        "metric": "cosine_via_normalized_inner_product",
        "count": 1,
        "dimensions": 1024,
        "embedding_model": "synthetic-kure-namespace",
        "corpus_manifest_sha256": CORPUS_SHA,
        "chunk_config_sha256": CONFIG_SHA,
        "chunk_artifact_sha256": OTHER_SHA,
        "vectors_sha256": VECTORS_SHA,
        "rows_sha256": sha256_file(rows_path),
        "index_sha256": None,
        "api_profile": baseline.MAC_LOCAL_EQUIVALENT,
        "index_config_sha256": INDEX_SHA,
    }
    # Provenance tests intentionally control the recorded vector digest rather
    # than loading the synthetic bytes as an actual NumPy artifact.
    (index_path / "metadata.json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )


def _verified(root: Path, cases: list[dict[str, object]]) -> SimpleNamespace:
    index_path = root / "index"
    _write_index_metadata(index_path)
    return SimpleNamespace(
        repo_root=root,
        config_sha256=CONFIG_SHA,
        eval_set_sha256=EVAL_SHA,
        cases=cases,
        candidate_path=root / "private" / "candidates.jsonl",
        private_score_path=root / "private" / "score.json",
        public_receipt_path=root / "public" / "receipt.json",
        index_path=index_path,
        hf_cache_path=root / "hf-cache",
        config={
            "corpus": {
                "manifest_sha256": CORPUS_SHA,
                "chunks_sha256": OTHER_SHA,
                "document_count": 1,
                "chunk_count": 1,
            },
            "evaluation": {"review_status": "draft"},
            "generation": {
                "mac_equivalent_model": "qwen3.8:27b-mlx",
                "max_output_tokens": 1024,
                "mac_transport_context_tokens": 32768,
            },
        },
    )


class GcpLocalBaselineHardeningTests(unittest.TestCase):
    def test_qwen_chat_template_and_full_system_prompt_drive_exact_8192_guard(self) -> None:
        class ChatCounter:
            def __init__(self, tokens: int) -> None:
                self.tokens = tokens
                self.calls: list[tuple[str, str]] = []

            def count_chat(
                self,
                *,
                system: str,
                prompt: str,
            ) -> int:
                self.calls.append((system, prompt))
                return self.tokens

        class Delegate:
            model = "qwen3.8:27b-mlx"
            max_output_tokens = 1024
            requires_budget = False

            def __init__(self) -> None:
                self.calls = 0

            def estimate_cost(self, input_tokens, output_tokens):  # type: ignore[no-untyped-def]
                return 0

            def generate(self, prompt):  # type: ignore[no-untyped-def]
                self.calls += 1
                return {"status": "abstained"}, 1, 1

        boundary_counter = ChatCounter(8192 - 1024)
        delegate = Delegate()
        recorder = baseline.RecordingGenerator(
            delegate=delegate,
            counter=boundary_counter,
            logical_context_tokens=8192,
        )
        recorder.generate("private prompt")
        self.assertEqual(delegate.calls, 1)
        self.assertEqual(
            boundary_counter.calls,
            [(LOCAL_SYSTEM_INSTRUCTIONS, "private prompt")],
        )

        over_counter = ChatCounter(8192 - 1024 + 1)
        blocked_delegate = Delegate()
        blocked = baseline.RecordingGenerator(
            delegate=blocked_delegate,
            counter=over_counter,
            logical_context_tokens=8192,
        )
        with self.assertRaisesRegex(ValueError, "mac_logical_context_budget_exceeded"):
            blocked.generate("private prompt")
        self.assertEqual(blocked_delegate.calls, 0)

    def test_score_rejects_candidate_provenance_drift_from_verified_and_current_index(self) -> None:
        case = _case()
        cases = [case]
        scenarios = (
            ("config_sha256", OTHER_SHA),
            ("eval_set_sha256", OTHER_SHA),
            ("index_config_sha256", OTHER_SHA),
            ("vectors_sha256", OTHER_SHA),
        )
        for field, value in scenarios:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                verified = _verified(Path(directory), cases)
                config_sha256 = OTHER_SHA if field == "config_sha256" else CONFIG_SHA
                eval_set_sha256 = OTHER_SHA if field == "eval_set_sha256" else EVAL_SHA
                provenance = dict(INDEX_PROVENANCE)
                if field in {"index_config_sha256", "vectors_sha256"}:
                    provenance[field] = value
                candidate = _candidate(
                    case,
                    config_sha256=config_sha256,
                    eval_set_sha256=eval_set_sha256,
                    index_provenance=provenance,
                )
                verified.candidate_path.parent.mkdir(parents=True, exist_ok=True)
                verified.candidate_path.write_text(
                    canonical_json(candidate) + "\n",
                    encoding="utf-8",
                )
                with (
                    patch.object(
                        baseline,
                        "current_mac_index_provenance",
                        return_value=dict(INDEX_PROVENANCE),
                    ),
                    self.assertRaisesRegex(
                        ValueError,
                        "candidate_verified_baseline_identity_mismatch",
                    ),
                ):
                    baseline.score_mac_candidates(verified)

    def test_resume_rejects_index_or_vector_provenance_drift(self) -> None:
        case = _case()
        stale_provenance = dict(INDEX_PROVENANCE)
        stale_provenance["vectors_sha256"] = OTHER_SHA
        candidate = _candidate(case, index_provenance=stale_provenance)

        class UnusedPipeline:
            def query(self, request, *, trace_context):  # type: ignore[no-untyped-def]
                raise AssertionError("resume mismatch must fail before execution")

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "private" / "candidates.jsonl"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(canonical_json(candidate) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "candidate_resume_identity_mismatch"):
                baseline.run_golden_cases(
                    pipeline=UnusedPipeline(),
                    cases=[case],
                    output_path=output,
                    private_output_root=output.parent,
                    run_id=EXPECTED_RUN_ID,
                    config_sha256=CONFIG_SHA,
                    eval_set_sha256=EVAL_SHA,
                    index_provenance=INDEX_PROVENANCE,
                    max_citations=3,
                )

    def test_preflight_passed_is_false_when_models_or_index_are_incomplete(self) -> None:
        class MissingGenerator:
            def __init__(self, **_kwargs: object) -> None:
                pass

            def _verify_model(self) -> None:
                raise ValueError("model missing")

        with tempfile.TemporaryDirectory() as directory:
            verified = _verified(Path(directory), [_case()])
            for child in verified.index_path.iterdir():
                child.unlink()
            missing_hub = SimpleNamespace(
                snapshot_download=lambda **_kwargs: (_ for _ in ()).throw(
                    RuntimeError("snapshot missing")
                )
            )
            with (
                patch.object(baseline, "local_workspace_storage", return_value={"passed": True}),
                patch.object(baseline, "verify_dependency_lock", return_value={"passed": True}),
                patch.object(baseline, "_configure_hf_cache"),
                patch.dict(sys.modules, {"huggingface_hub": missing_hub}),
                patch(
                    "midprojectrag.stacks.local.generation.OllamaGenerator",
                    MissingGenerator,
                ),
            ):
                receipt = baseline.preflight_receipt(verified)
            self.assertFalse(receipt["kure_cached"])
            self.assertFalse(receipt["ollama_verified"])
            self.assertFalse(receipt["index_ready"])
            self.assertFalse(receipt["passed"])

    def test_preflight_rejects_metadata_name_without_complete_index_artifacts(self) -> None:
        class ReadyGenerator:
            def __init__(self, **_kwargs: object) -> None:
                pass

            def _verify_model(self) -> None:
                return None

        class ReadyQwenCounter:
            def count_chat(self, *, system: str, prompt: str) -> int:
                return 1

        with tempfile.TemporaryDirectory() as directory:
            verified = _verified(Path(directory), [_case()])
            for child in verified.index_path.iterdir():
                child.unlink()
            (verified.index_path / "metadata.json").write_text("{}", encoding="utf-8")
            ready_hub = SimpleNamespace(snapshot_download=lambda **_kwargs: "cached")
            with (
                patch.object(baseline, "local_workspace_storage", return_value={"passed": True}),
                patch.object(baseline, "verify_dependency_lock", return_value={"passed": True}),
                patch.object(baseline, "_configure_hf_cache"),
                patch.dict(sys.modules, {"huggingface_hub": ready_hub}),
                patch(
                    "midprojectrag.stacks.local.generation.OllamaGenerator",
                    ReadyGenerator,
                ),
                patch(
                    "midprojectrag.stacks.local.qwen_tokenizer.PinnedQwenChatTokenCounter",
                    ReadyQwenCounter,
                ),
            ):
                receipt = baseline.preflight_receipt(verified)
            self.assertTrue(receipt["kure_cached"])
            self.assertTrue(receipt["qwen_tokenizer_cached"])
            self.assertTrue(receipt["ollama_verified"])
            self.assertFalse(receipt["index_ready"])
            self.assertFalse(receipt["passed"])

    def test_runtime_error_contributes_zero_to_abstention_denominator(self) -> None:
        case = _case(decision="abstain")
        candidate = _candidate(case, status="error")
        report = baseline.score_provisional_candidates([case], [candidate])
        self.assertEqual(report["counts"]["runtime_errors"], 1)
        self.assertEqual(report["metrics"]["behavior"]["abstention_match"], 0.0)

    def test_candidate_rejects_scope_topk_measurement_cost_and_extra_field_drift(self) -> None:
        case = _case()
        scenarios: list[tuple[str, dict[str, object], str]] = []

        out_of_scope = _candidate(
            case,
            retrieval=[_retrieval_row(1, doc_id=DOC_B)],
        )
        scenarios.append(
            ("out_of_scope", out_of_scope, "candidate_retrieval_scope_violation")
        )

        over_top_k = _candidate(
            case,
            retrieval=[_retrieval_row(rank) for rank in range(1, 12)],
        )
        scenarios.append(
            ("top_k", over_top_k, "candidate_retrieval_invalid")
        )

        nonfinite_score = _candidate(
            case,
            retrieval=[_retrieval_row(1, score=math.nan)],
        )
        scenarios.append(
            ("score", nonfinite_score, "candidate_retrieval_score_invalid")
        )

        nonfinite_timing = _candidate(case)
        nonfinite_timing["timing_ms"]["total"] = math.inf  # type: ignore[index]
        scenarios.append(("timing", nonfinite_timing, "candidate_timing_invalid"))

        nonzero_cost = _candidate(case)
        nonzero_cost["usage"]["cost_usd"] = 0.01  # type: ignore[index]
        scenarios.append(("cost", nonzero_cost, "candidate_usage_invalid"))

        extra_field = _candidate(case)
        extra_field["unexpected"] = "drift"
        scenarios.append(("extra", extra_field, "invalid_candidate_shape"))

        for name, candidate, error_code in scenarios:
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, error_code):
                    baseline.validate_mac_candidate(candidate, case=case)


if __name__ == "__main__":
    unittest.main()
