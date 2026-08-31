from __future__ import annotations

import json
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from midprojectrag.gcp_local_baseline import (
    MAC_LOCAL_EQUIVALENT,
    RecordingGenerator,
    build_golden_request,
    build_mac_candidate,
    content_free_receipt,
    evaluate_storage,
    run_golden_cases,
    score_provisional_candidates,
    validate_baseline_config,
)
from midprojectrag.ingest.common import sha256_text


SHA_A = "a" * 64
SHA_B = "b" * 64
INDEX_PROVENANCE = {
    "schema_version": "1.0",
    "engine": "numpy",
    "count": 9331,
    "dimensions": 1024,
    "chunk_artifact_sha256": "bb82b593153a93f9373f0bdf7f5be7531e651fdab9c5df36b69d53df0a35b9a2",
    "index_config_sha256": "c" * 64,
    "vectors_sha256": "d" * 64,
    "rows_sha256": "e" * 64,
    "metadata_sha256": "f" * 64,
}
DOC_A = "doc_" + "1" * 24
DOC_B = "doc_" + "2" * 24
BLOCK_A = "block_" + "3" * 24
BLOCK_B = "block_" + "4" * 24
CHUNK_A = "chunk_" + "5" * 24
CHUNK_B = "chunk_" + "6" * 24


def _case(
    case_id: str,
    *,
    required_docs: list[str],
    evidence_blocks: list[tuple[str, str]],
    decision: str = "answer",
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "case_id": case_id,
        "task_type": "unknown" if decision == "abstain" else "single_doc",
        "question": "private question",
        "history": [],
        "document_scope": (
            {"mode": "all", "doc_ids": []}
            if decision == "abstain"
            else {"mode": "explicit", "doc_ids": list(required_docs)}
        ),
        "review": {"author": "draft", "reviewer": "pending", "status": "draft"},
        "gold": {
            "decision": decision,
            "required_doc_ids": list(required_docs),
            "evidence_refs": [
                {"doc_id": doc_id, "source_block_id": block_id, "locator_hash": SHA_A}
                for doc_id, block_id in evidence_blocks
            ],
            "abstain_reason": "insufficient_evidence" if decision == "abstain" else None,
        },
    }


def _candidate(
    case: dict[str, object],
    *,
    retrieval: list[dict[str, object]],
    status: str = "answered",
    citations: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    request = build_golden_request(case, config_sha256=SHA_A, max_citations=3)
    response = {
        "schema_version": "1.0",
        "request_id": request["request_id"],
        "status": status,
        "answer": (
            "grounded answer"
            if status == "answered"
            else (
                "제공된 문서에서 답변 근거를 찾지 못했습니다."
                if status == "abstained"
                else ""
            )
        ),
        "citations": citations or [],
        "abstention": (
            {"reason": "insufficient_evidence", "detail": "private"}
            if status == "abstained"
            else None
        ),
        "error": {"code": "pipeline_failed", "message": "safe"} if status == "error" else None,
        "trace_id": "trace-test",
    }
    result = SimpleNamespace(
        retrieval=retrieval,
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
    return build_mac_candidate(
        case=case,
        request=request,
        result=result,
        run_id="mac-run-001",
        config_sha256=SHA_A,
        eval_set_sha256=SHA_B,
        index_provenance=INDEX_PROVENANCE,
        prompt="private prompt" if status == "answered" else None,
        prompt_sha256=sha256_text("private prompt") if status == "answered" else None,
    )


class GcpLocalBaselineTests(unittest.TestCase):
    def test_frozen_public_config_matches_contract_and_rejects_drift(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        config_path = (
            repo_root
            / "configs/rag/gcp-local-kure-qwen3-8b-awq-refined98-page-v1.json"
        )
        config = json.loads(config_path.read_text(encoding="utf-8"))
        validated = validate_baseline_config(config)
        self.assertEqual(validated["corpus"]["chunk_count"], 9331)
        self.assertEqual(validated["embedding"]["dimensions"], 1024)
        self.assertEqual(validated["retrieval"]["top_k"], 10)
        self.assertEqual(validated["retrieval"]["context_top_k"], 5)

        changed = copy.deepcopy(config)
        changed["embedding"]["revision"] = "main"
        with self.assertRaisesRegex(ValueError, "embedding_revision_not_pinned"):
            validate_baseline_config(changed)

        changed = copy.deepcopy(config)
        changed["corpus"]["manifest_path"] = (
            "resources/data_refined/private/other-manifest.jsonl"
        )
        with self.assertRaisesRegex(ValueError, "manifest_path_not_frozen"):
            validate_baseline_config(changed)

        changed = copy.deepcopy(config)
        changed["storage"]["hard_max_bytes"] = 200_000_000_000
        with self.assertRaisesRegex(ValueError, "disk_contract_not_frozen"):
            validate_baseline_config(changed)

        changed = copy.deepcopy(config)
        changed["generation"]["mac_transport_context_tokens"] = 8192
        with self.assertRaisesRegex(ValueError, "mac_transport_contract_not_frozen"):
            validate_baseline_config(changed)

    def test_storage_contract_accepts_100gb_and_rejects_larger_or_low_free(self) -> None:
        accepted = evaluate_storage(
            total_bytes=100_000_000_000,
            used_bytes=79_999_999_999,
            free_bytes=20_000_000_001,
        )
        self.assertTrue(accepted["passed"])
        self.assertFalse(accepted["warning"])

        warning = evaluate_storage(
            total_bytes=100_000_000_000,
            used_bytes=80_000_000_000,
            free_bytes=20_000_000_000,
        )
        self.assertTrue(warning["passed"])
        self.assertTrue(warning["warning"])

        with self.assertRaisesRegex(ValueError, "disk_capacity_exceeds_100gb"):
            evaluate_storage(
                total_bytes=100_000_000_001,
                used_bytes=1,
                free_bytes=100_000_000_000,
            )
        with self.assertRaisesRegex(ValueError, "disk_free_below_10gb"):
            evaluate_storage(
                total_bytes=100_000_000_000,
                used_bytes=90_000_000_001,
                free_bytes=9_999_999_999,
            )

    def test_request_is_deterministic_and_never_contains_gold(self) -> None:
        case = _case(
            "dev-single-001",
            required_docs=[DOC_A],
            evidence_blocks=[(DOC_A, BLOCK_A)],
        )
        request = build_golden_request(case, config_sha256=SHA_A, max_citations=3)
        self.assertEqual(request["options"], {"max_citations": 3})
        self.assertEqual(request["question"], "private question")
        self.assertNotIn("gold", json.dumps(request))
        self.assertEqual(
            request["request_id"],
            "req-" + sha256_text("dev-single-001:" + SHA_A)[:24],
        )

    def test_provisional_metrics_cover_retrieval_contract_and_abstention(self) -> None:
        cases = [
            _case(
                "dev-single-001",
                required_docs=[DOC_A, DOC_B],
                evidence_blocks=[(DOC_A, BLOCK_A), (DOC_B, BLOCK_B)],
            ),
            _case(
                "dev-unknown-001",
                required_docs=[],
                evidence_blocks=[],
                decision="abstain",
            ),
        ]
        retrieval = [
            {
                "rank": 1,
                "doc_id": DOC_A,
                "chunk_id": CHUNK_A,
                "source_block_ids": [BLOCK_A],
                "score": 0.9,
            },
            {
                "rank": 2,
                "doc_id": DOC_B,
                "chunk_id": CHUNK_B,
                "source_block_ids": [BLOCK_B],
                "score": 0.8,
            },
        ]
        candidates = [
            _candidate(
                cases[0],
                retrieval=retrieval,
                citations=[
                    {
                        "doc_id": DOC_A,
                        "chunk_id": CHUNK_A,
                        "source_block_ids": [BLOCK_A],
                        "locator": {
                            "section_path": [],
                            "page_start": 1,
                            "page_end": 1,
                        },
                    }
                ],
            ),
            _candidate(cases[1], retrieval=[], status="abstained"),
        ]

        report = score_provisional_candidates(cases, candidates)
        self.assertEqual(report["evaluation_tier"], "provisional_non_official")
        self.assertEqual(report["semantic_judgment"], "not_run")
        self.assertFalse(report["official"])
        self.assertEqual(report["counts"]["scored"], 2)
        self.assertEqual(report["metrics"]["retrieval"]["document_recall_at_1"], 0.5)
        self.assertEqual(report["metrics"]["retrieval"]["document_recall_at_3"], 1.0)
        self.assertEqual(report["metrics"]["retrieval"]["source_block_recall_at_1"], 0.5)
        self.assertEqual(report["metrics"]["retrieval"]["mrr_at_10"], 1.0)
        self.assertEqual(report["metrics"]["contract"]["citation_validity"], 1.0)
        self.assertEqual(report["metrics"]["behavior"]["abstention_match"], 1.0)

        receipt = content_free_receipt(report)
        serialized = json.dumps(receipt, ensure_ascii=False)
        self.assertNotIn("private question", serialized)
        self.assertNotIn("per_case", receipt)
        self.assertFalse(receipt["official"])

    def test_mac_candidate_can_never_claim_official_gcp(self) -> None:
        case = _case(
            "dev-single-001",
            required_docs=[DOC_A],
            evidence_blocks=[(DOC_A, BLOCK_A)],
        )
        request = build_golden_request(case, config_sha256=SHA_A, max_citations=3)
        result = SimpleNamespace(
            response={
                "schema_version": "1.0",
                "request_id": request["request_id"],
                "status": "abstained",
                "answer": "제공된 문서에서 답변 근거를 찾지 못했습니다.",
                "citations": [],
                "abstention": {"reason": "insufficient_evidence", "detail": "private"},
                "error": None,
                "trace_id": "trace-test",
            },
            retrieval=[],
            timing_ms={"retrieval": 1.0, "generation": 0.0, "total": 1.0},
            usage={"input_tokens": 0, "output_tokens": 0, "embedding_tokens": 1, "cost_usd": 0.0, "gpu_seconds": None, "peak_vram_gb": None},
            cache_hit=False,
        )
        candidate = build_mac_candidate(
            case=case,
            request=request,
            result=result,
            run_id="mac-run-001",
            config_sha256=SHA_A,
            eval_set_sha256=SHA_B,
            index_provenance=INDEX_PROVENANCE,
            prompt=None,
            prompt_sha256=None,
        )
        self.assertEqual(candidate["execution_profile"], MAC_LOCAL_EQUIVALENT)
        self.assertFalse(candidate["official"])
        self.assertNotIn("stack_id", candidate)

    def test_logical_8k_guard_blocks_mac_transport_before_delegate(self) -> None:
        class Counter:
            def count_chat(self, *, system, prompt):  # type: ignore[no-untyped-def]
                return 8000

        class Delegate:
            model = "qwen3.8:27b-mlx"
            max_output_tokens = 1024
            requires_budget = False
            called = False

            def estimate_cost(self, input_tokens, output_tokens):  # type: ignore[no-untyped-def]
                return 0

            def generate(self, prompt):  # type: ignore[no-untyped-def]
                self.called = True
                raise AssertionError("must not call delegate")

        delegate = Delegate()
        recorder = RecordingGenerator(delegate=delegate, counter=Counter())
        with self.assertRaisesRegex(ValueError, "mac_logical_context_budget_exceeded"):
            recorder.generate("private prompt")
        self.assertFalse(delegate.called)

    def test_output_boundary_and_corrupt_resume_fail_closed(self) -> None:
        case = _case(
            "dev-single-001",
            required_docs=[DOC_A],
            evidence_blocks=[(DOC_A, BLOCK_A)],
        )

        class UnusedPipeline:
            def query(self, request, *, trace_context):  # type: ignore[no-untyped-def]
                raise AssertionError("must not execute")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "private"
            outside = Path(directory) / "outside.jsonl"
            with self.assertRaisesRegex(ValueError, "candidate_output_outside_private_root"):
                run_golden_cases(
                    pipeline=UnusedPipeline(),
                    cases=[case],
                    output_path=outside,
                    private_output_root=root,
                    run_id="mac-run-001",
                    config_sha256=SHA_A,
                    eval_set_sha256=SHA_B,
                    index_provenance=INDEX_PROVENANCE,
                    max_citations=3,
                )

            output = root / "candidates.jsonl"
            root.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(
                    {
                        "execution_profile": MAC_LOCAL_EQUIVALENT,
                        "official": False,
                        "run_id": "mac-run-001",
                        "case_id": "dev-single-001",
                        "config_sha256": SHA_A,
                        "eval_set_sha256": SHA_B,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "invalid_candidate_shape"):
                run_golden_cases(
                    pipeline=UnusedPipeline(),
                    cases=[case],
                    output_path=output,
                    private_output_root=root,
                    run_id="mac-run-001",
                    config_sha256=SHA_A,
                    eval_set_sha256=SHA_B,
                    index_provenance=INDEX_PROVENANCE,
                    max_citations=3,
                )

    def test_runner_is_resumable_and_writes_private_jsonl(self) -> None:
        cases = [
            _case(
                "dev-single-001",
                required_docs=[DOC_A],
                evidence_blocks=[(DOC_A, BLOCK_A)],
            ),
            _case(
                "dev-single-002",
                required_docs=[DOC_A],
                evidence_blocks=[(DOC_A, BLOCK_A)],
            ),
        ]

        class FakePipeline:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def query(self, request, *, trace_context):  # type: ignore[no-untyped-def]
                self.calls.append(trace_context["case_id"])
                return SimpleNamespace(
                    response={
                        "schema_version": "1.0",
                        "request_id": request["request_id"],
                        "status": "abstained",
                        "answer": "제공된 문서에서 답변 근거를 찾지 못했습니다.",
                        "citations": [],
                        "abstention": {"reason": "insufficient_evidence", "detail": "private"},
                        "error": None,
                        "trace_id": "trace-test",
                    },
                    retrieval=[],
                    timing_ms={"retrieval": 1.0, "generation": 0.0, "total": 1.0},
                    usage={"input_tokens": 0, "output_tokens": 0, "embedding_tokens": 1, "cost_usd": 0.0, "gpu_seconds": None, "peak_vram_gb": None},
                    cache_hit=False,
                )

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "private" / "candidates.jsonl"
            pipeline = FakePipeline()
            first = run_golden_cases(
                pipeline=pipeline,
                cases=cases[:1],
                output_path=output,
                private_output_root=output.parent,
                run_id="mac-run-001",
                config_sha256=SHA_A,
                eval_set_sha256=SHA_B,
                index_provenance=INDEX_PROVENANCE,
                max_citations=3,
            )
            second = run_golden_cases(
                pipeline=pipeline,
                cases=cases,
                output_path=output,
                private_output_root=output.parent,
                run_id="mac-run-001",
                config_sha256=SHA_A,
                eval_set_sha256=SHA_B,
                index_provenance=INDEX_PROVENANCE,
                max_citations=3,
            )

            self.assertEqual(first["executed"], 1)
            self.assertEqual(second["executed"], 1)
            self.assertEqual(second["resumed"], 1)
            self.assertEqual(pipeline.calls, ["dev-single-001", "dev-single-002"])
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["case_id"] for row in rows], ["dev-single-001", "dev-single-002"])
            self.assertTrue(all(row["prompt"] is None for row in rows))

    def test_public_receipt_rejects_injected_metric_fields(self) -> None:
        case = _case(
            "dev-unknown-001",
            required_docs=[],
            evidence_blocks=[],
            decision="abstain",
        )
        report = score_provisional_candidates(
            [case],
            [_candidate(case, retrieval=[], status="abstained")],
        )
        report["metrics"]["contract"]["private_text"] = "leak"
        with self.assertRaisesRegex(ValueError, "invalid_provisional_metrics"):
            content_free_receipt(report)


if __name__ == "__main__":
    unittest.main()
