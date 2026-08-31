from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from midprojectrag.api_matrix import (
    MatrixPaths,
    MatrixSettings,
    build_parser,
    preflight_matrix,
    run_matrix,
)
from midprojectrag.evaluation import validate_case
from midprojectrag.ingest.common import (
    canonical_json,
    sha256_file,
    sha256_text,
    write_json,
    write_jsonl,
)
from midprojectrag.indexing.chunking import chunk_artifact_sha256
from midprojectrag.indexing.budget import BudgetLedger
from midprojectrag.indexing.exact_index import ExactDenseIndex
from midprojectrag.observability import MemoryObserver
from midprojectrag.stacks.api import api_config_sha256, build_api_index_config


def _chunk(number: int) -> dict[str, object]:
    text = f"synthetic chunk {number}"
    doc_id = f"doc_{number:024x}"
    block_id = f"block_{number:024x}"
    content_sha256 = sha256_text(text)
    config_sha256 = "c" * 64
    identity = {
        "block_id": block_id,
        "config_sha256": config_sha256,
        "content_sha256": content_sha256,
        "doc_id": doc_id,
        "page_end": number,
        "page_start": number,
        "part_count": 1,
        "part_index": 0,
    }
    return {
        "schema_version": "1.0",
        "chunk_id": f"chunk_{sha256_text(canonical_json(identity))[:24]}",
        "doc_id": doc_id,
        "text": text,
        "source_block_ids": [block_id],
        "section_path": ["synthetic"],
        "page_start": number,
        "page_end": number,
        "part_index": 0,
        "part_count": 1,
        "retrieval_role": "primary",
        "chunker_id": "page-v1",
        "config_sha256": config_sha256,
        "content_sha256": content_sha256,
    }


def _case(task: str, number: int, manifest_sha256: str) -> dict[str, object]:
    aliases = {
        "single_doc": "single",
        "multi_doc_compare": "multi",
        "follow_up": "followup",
        "unknown": "unknown",
    }
    doc_one = "doc_000000000000000000000001"
    doc_two = "doc_000000000000000000000002"
    block_one = "block_000000000000000000000001"
    block_two = "block_000000000000000000000002"
    required_docs = [] if task == "unknown" else [doc_one]
    evidence = [] if task == "unknown" else [
        {
            "doc_id": doc_one,
            "source_block_id": block_one,
            "locator_hash": sha256_text(f"locator-{task}-{number}-one"),
        }
    ]
    comparison_axes: list[str] = []
    if task == "multi_doc_compare":
        required_docs.append(doc_two)
        evidence.append(
            {
                "doc_id": doc_two,
                "source_block_id": block_two,
                "locator_hash": sha256_text(f"locator-{task}-{number}-two"),
            }
        )
        comparison_axes = ["budget"]
    history: list[dict[str, object]] = []
    conversation = None
    if task == "follow_up":
        history = [
            {"turn_id": f"turn-{number}-1", "role": "user", "content": "prior question"},
            {
                "turn_id": f"turn-{number}-2",
                "role": "assistant",
                "content": "prior answer",
                "cited_doc_ids": [doc_one],
            },
        ]
        conversation = {
            "conversation_id": f"conversation-{number}",
            "turn_index": 3,
            "depends_on_turn_ids": [f"turn-{number}-2"],
        }
    decision = "abstain" if task == "unknown" else "answer"
    case = {
        "schema_version": "1.0",
        "case_id": f"dev-{aliases[task]}-{number:03d}",
        "group_id": f"group-{aliases[task]}-{number}",
        "split": "dev",
        "task_type": task,
        "question": f"synthetic private question {task} {number}",
        "history": history,
        "document_scope": {
            "mode": "all" if task == "unknown" else "explicit",
            "doc_ids": required_docs,
        },
        "conversation": conversation,
        "gold": {
            "decision": decision,
            "reference_answer": None if task == "unknown" else "synthetic reference",
            "required_key_points": []
            if task == "unknown"
            else [{"point_id": f"kp_{aliases[task]}_{number}", "text": "point"}],
            "required_doc_ids": required_docs,
            "evidence_refs": evidence,
            "comparison_axes": comparison_axes,
            "abstain_reason": "insufficient_evidence" if task == "unknown" else None,
        },
        "difficulty": "medium",
        "tags": ["synthetic"],
        "source_manifest_sha256": manifest_sha256,
        "review": {"author": "fixture", "reviewer": "pending", "status": "draft"},
    }
    assert validate_case(case) == []
    return case


class _FakePipeline:
    def __init__(
        self,
        runtime,
        calls,
        *,
        fail: bool = False,
        error_response: bool = False,
        leave_reservation: bool = False,
        clock=None,
    ):
        self.runtime = runtime
        self.calls = calls
        self.fail = fail
        self.error_response = error_response
        self.leave_reservation = leave_reservation
        self.clock = clock
        self.flushes = 0

    def query(self, request, *, trace_context=None):
        self.runtime.generation_start_limiter.wait_for_start()
        self.calls.append(
            (
                self.runtime.embedding_model,
                self.runtime.generator_model,
                request["request_id"],
                trace_context,
                self.clock() if self.clock is not None else None,
            )
        )
        if self.fail:
            raise RuntimeError("synthetic_interruption")
        scope = request["document_scope"]
        allowed = set(scope["doc_ids"]) if scope["mode"] == "explicit" else None
        chunks = [
            chunk
            for chunk in self.runtime.index.chunks
            if allowed is None or chunk["doc_id"] in allowed
        ]
        retrieval = [
            {
                "rank": rank,
                "doc_id": chunk["doc_id"],
                "chunk_id": chunk["chunk_id"],
                "source_block_ids": chunk["source_block_ids"],
                "score": 1.0 / rank,
            }
            for rank, chunk in enumerate(chunks[:10], start=1)
        ]
        trace_id = sha256_text(request["request_id"])[:32]
        if self.error_response:
            response = {
                "schema_version": "1.0",
                "request_id": request["request_id"],
                "status": "error",
                "answer": "",
                "citations": [],
                "abstention": None,
                "error": {
                    "code": "pipeline_failed",
                    "message": "synthetic safe failure",
                },
                "trace_id": trace_id,
            }
        elif scope["mode"] == "all":
            response = {
                "schema_version": "1.0",
                "request_id": request["request_id"],
                "status": "abstained",
                "answer": "제공된 문서에서 답변 근거를 찾지 못했습니다.",
                "citations": [],
                "abstention": {"reason": "insufficient_evidence", "detail": "synthetic"},
                "error": None,
                "trace_id": trace_id,
            }
        else:
            selected = chunks[0]
            response = {
                "schema_version": "1.0",
                "request_id": request["request_id"],
                "status": "answered",
                "answer": "synthetic grounded answer",
                "citations": [
                    {
                        "doc_id": selected["doc_id"],
                        "chunk_id": selected["chunk_id"],
                        "source_block_ids": selected["source_block_ids"],
                        "locator": {
                            "section_path": selected["section_path"],
                            "page_start": selected["page_start"],
                            "page_end": selected["page_end"],
                        },
                    }
                ],
                "abstention": None,
                "error": None,
                "trace_id": trace_id,
            }
        if self.leave_reservation:
            self.runtime.budget.reserve("0.001", "synthetic-unfinished")
        return SimpleNamespace(
            response=response,
            retrieval=retrieval,
            timing_ms={"retrieval": 1.0, "generation": 2.0, "total": 3.0},
            usage={
                "input_tokens": 10,
                "output_tokens": 5,
                "embedding_tokens": 2,
                "cost_usd": 0.001,
                "gpu_seconds": None,
                "peak_vram_gb": None,
            },
            cache_hit=False,
        )

    def flush_observability(self):
        self.flushes += 1


def _record_builder(**kwargs):
    return {
        "case_id": kwargs["context"]["case_id"],
        "embedding_model": kwargs["embedding_model"],
        "generator_model": kwargs["generator_model"],
        "reasoning_effort": kwargs["reasoning_effort"],
        "api_profile": kwargs["api_profile"],
        "embedding_dimensions": kwargs["embedding_dimensions"],
        "index_config_sha256": kwargs["index_config_sha256"],
    }


class _FakeClock:
    def __init__(self) -> None:
        self.value = 0.0
        self.sleeps = []

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


class _ShutdownObserver(MemoryObserver):
    def __init__(self) -> None:
        super().__init__()
        self.shutdown_calls = 0

    def shutdown(self) -> None:
        self.shutdown_calls += 1
        self.flush()


class ApiMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.paths = MatrixPaths.from_repo_root(self.root)
        self.paths.private_root.mkdir(parents=True)
        self.paths.tokenizer_cache_dir.mkdir(parents=True)
        self.paths.dependency_lock_path.write_text("[project]\nname='fixture'\n", encoding="utf-8")
        chunks = [_chunk(number) for number in range(1, 5)]
        manifest = [
            {"doc_id": chunk["doc_id"], "status": "ok", "index_eligible": True}
            for chunk in chunks
        ]
        write_jsonl(self.paths.manifest_path, manifest)
        manifest_sha256 = sha256_file(self.paths.manifest_path)
        write_jsonl(self.paths.chunks_path, chunks)
        write_json(
            self.paths.chunk_metadata_path,
            {
                "schema_version": "1.0",
                "source_manifest_sha256": manifest_sha256,
                "chunk_artifact_sha256": sha256_file(self.paths.chunks_path),
                "config_sha256": "c" * 64,
                "documents": 4,
                "chunks": 4,
            },
        )
        cases = [
            _case(task, number, manifest_sha256)
            for task in ("single_doc", "multi_doc_compare", "follow_up", "unknown")
            for number in range(1, 11)
        ]
        write_jsonl(self.paths.dev_path, cases)
        vectors = np.asarray([[1, 0], [0, 1], [1, 1], [1, -1]], dtype=np.float32)
        for model in ("text-embedding-3-small", "text-embedding-3-large"):
            profiled_index_dir = (
                self.paths.indexes_root / "personal_experimental" / f"{model}-2"
            )
            index_config = build_api_index_config(
                api_profile="personal_experimental",
                corpus_manifest_sha256=manifest_sha256,
                chunk_artifact_sha256=chunk_artifact_sha256(chunks),
                chunk_config_sha256="c" * 64,
                embedding_model=model,
                embedding_dimensions=2,
                index_engine="numpy",
                batch_size=128,
            )
            index_config_hash = api_config_sha256(index_config)
            ExactDenseIndex(chunks, vectors, engine="numpy").save(
                profiled_index_dir,
                corpus_manifest_sha256=manifest_sha256,
                embedding_model=model,
                api_profile="personal_experimental",
                index_config_sha256=index_config_hash,
            )
            write_json(profiled_index_dir / "index-config.json", index_config)
        self.settings = MatrixSettings(
            embedding_dimensions=(
                ("text-embedding-3-small", 2),
                ("text-embedding-3-large", 2),
            ),
            case_interval_seconds=0,
        )
        self.environment = {
            "python_version": "3.13.0",
            "platform": "synthetic-test",
            "region": "local-test",
            "machine_type": "local-test",
            "vcpu": 4,
            "ram_gb": 16.0,
            "gpu_model": None,
            "disk_gb": 100.0,
            "dependency_lock_sha256": "d" * 64,
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_preflight_is_local_and_marks_draft_dev_provisional(self) -> None:
        report = preflight_matrix(self.paths, self.settings)
        self.assertEqual(report["network_calls"], 0)
        self.assertEqual(report["cases"], 40)
        self.assertEqual(report["review_statuses"], {"draft": 40})
        self.assertEqual(report["evaluation_status"], "provisional_unreviewed_dev")
        self.assertEqual(report["indexes"]["text-embedding-3-large"]["dimensions"], 2)

    def test_matrix_checkpoints_every_case_and_resume_makes_no_calls(self) -> None:
        calls = []
        budget_ids = []

        def factory(runtime):
            budget_ids.append(id(runtime.budget))
            return _FakePipeline(runtime, calls)

        observer = _ShutdownObserver()
        summary = run_matrix(
            self.paths,
            self.settings,
            observer=observer,
            pipeline_factory=factory,
            run_record_builder=_record_builder,
            run_record_validator=lambda _record: [],
            environment=self.environment,
        )
        self.assertTrue(summary["matrix_complete"])
        self.assertEqual(observer.shutdown_calls, 1)
        self.assertEqual(len(calls), 160)
        self.assertTrue(all(call[3]["api_profile"] == "personal_experimental" for call in calls))
        self.assertTrue(all("question" not in call[3] for call in calls))
        self.assertEqual(len(set(budget_ids)), 1)
        self.assertEqual(len(summary["combos"]), 4)
        self.assertEqual(summary["error_count"], 0)
        self.assertEqual(summary["response_error_rate"], 0.0)
        self.assertTrue(summary["budget"]["clean"])
        self.assertEqual(summary["budget"]["matrix_committed_delta_usd"], "0E-9")
        self.assertTrue(all(combo["counts"]["completed"] == 40 for combo in summary["combos"]))
        self.assertTrue(all(combo["counts"]["errors"] == 0 for combo in summary["combos"]))
        self.assertTrue(
            all(combo["reasoning_effort"] == "minimal" for combo in summary["combos"])
        )
        self.assertTrue(
            all(combo["case_interval_seconds"] == 0.0 for combo in summary["combos"])
        )
        self.assertTrue(
            all(
                combo["metrics"]["structural_citations_unjudged"][
                    "citation_context_membership_rate"
                ]
                == 1.0
                for combo in summary["combos"]
            )
        )
        self.assertTrue(
            all(combo["counts"]["evaluator_compatible"] == 40 for combo in summary["combos"])
        )
        serialized = canonical_json(summary)
        self.assertNotIn("synthetic private question", serialized)
        self.assertNotIn("synthetic grounded answer", serialized)
        checkpoint_count = len(
            list(self.paths.outputs_root.glob("*/*/*/*/checkpoints/*.json"))
        )
        self.assertEqual(checkpoint_count, 160)
        for combo in summary["combos"]:
            summary_path = (
                self.paths.outputs_root
                / "personal_experimental"
                / f"{combo['embedding_model']}-2"
                / combo["generator_model"]
                / self.settings.run_label
                / "summary.provisional.json"
            )
            self.assertEqual(
                json.loads(summary_path.read_text(encoding="utf-8")),
                combo,
            )

        resumed = run_matrix(
            self.paths,
            self.settings,
            observer=MemoryObserver(),
            pipeline_factory=factory,
            run_record_builder=_record_builder,
            run_record_validator=lambda _record: [],
            environment=self.environment,
        )
        self.assertTrue(resumed["matrix_complete"])
        self.assertEqual(len(calls), 160)

    def test_generation_start_interval_is_global_across_all_combos(self) -> None:
        calls = []
        clock = _FakeClock()
        settings = replace(
            self.settings,
            run_label="interval",
            case_interval_seconds=6.0,
        )

        summary = run_matrix(
            self.paths,
            settings,
            pipeline_factory=lambda runtime: _FakePipeline(
                runtime,
                calls,
                clock=clock.monotonic,
            ),
            run_record_builder=_record_builder,
            run_record_validator=lambda _record: [],
            environment=self.environment,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
        )

        starts = [call[4] for call in calls]
        self.assertEqual(len(starts), 160)
        self.assertTrue(
            all(
                later - earlier >= 6.0
                for earlier, later in zip(starts, starts[1:])
            )
        )
        self.assertEqual(len(clock.sleeps), 159)
        self.assertEqual(summary["case_interval_seconds"], 6.0)
        self.assertTrue(
            all(combo["case_interval_seconds"] == 6.0 for combo in summary["combos"])
        )

    def test_new_error_response_fails_fast_after_completed_checkpoint(self) -> None:
        calls = []
        settings = replace(self.settings, run_label="error-response")

        with self.assertRaisesRegex(
            ValueError, "matrix_new_case_response_error"
        ):
            run_matrix(
                self.paths,
                settings,
                pipeline_factory=lambda runtime: _FakePipeline(
                    runtime,
                    calls,
                    error_response=True,
                ),
                run_record_builder=_record_builder,
                run_record_validator=lambda _record: [],
                environment=self.environment,
            )

        self.assertEqual(len(calls), 1)
        checkpoints = list(
            self.paths.outputs_root.glob(
                "*/*/*/error-response/checkpoints/*.json"
            )
        )
        self.assertEqual(len(checkpoints), 1)
        envelope = json.loads(checkpoints[0].read_text(encoding="utf-8"))
        self.assertEqual(envelope["payload"]["state"], "completed")
        self.assertEqual(
            envelope["payload"]["result"]["response"]["status"], "error"
        )

    def test_observer_shutdown_runs_when_verified_input_check_fails(self) -> None:
        observer = _ShutdownObserver()
        with self.assertRaisesRegex(ValueError, "matrix_dev_not_approved"):
            run_matrix(
                self.paths,
                replace(self.settings, require_approved_dev=True),
                observer=observer,
                environment=self.environment,
            )
        self.assertEqual(observer.shutdown_calls, 1)

    def test_existing_budget_reservation_blocks_before_pipeline(self) -> None:
        ledger = BudgetLedger(self.paths.budget_ledger_path, limit_usd=5)
        reservation_id = ledger.reserve("0.001", "synthetic-existing")
        calls = []
        try:
            with self.assertRaisesRegex(
                ValueError, "matrix_budget_reservation_requires_audit"
            ):
                run_matrix(
                    self.paths,
                    self.settings,
                    pipeline_factory=lambda runtime: _FakePipeline(runtime, calls),
                    run_record_builder=_record_builder,
                    run_record_validator=lambda _record: [],
                    environment=self.environment,
                )
            self.assertEqual(calls, [])
        finally:
            ledger.release(reservation_id)

    def test_new_unfinished_budget_reservation_stops_after_one_case(self) -> None:
        calls = []
        settings = replace(self.settings, run_label="budget-reserved")
        with self.assertRaisesRegex(
            ValueError, "matrix_budget_reservation_requires_audit"
        ):
            run_matrix(
                self.paths,
                settings,
                pipeline_factory=lambda runtime: _FakePipeline(
                    runtime,
                    calls,
                    leave_reservation=True,
                ),
                run_record_builder=_record_builder,
                run_record_validator=lambda _record: [],
                environment=self.environment,
            )
        self.assertEqual(len(calls), 1)

    def test_started_checkpoint_blocks_automatic_cost_replay(self) -> None:
        calls = []

        with self.assertRaisesRegex(RuntimeError, "synthetic_interruption"):
            run_matrix(
                self.paths,
                MatrixSettings(
                    embedding_dimensions=(
                        ("text-embedding-3-small", 2),
                        ("text-embedding-3-large", 2),
                    ),
                    run_label="interrupted",
                    case_interval_seconds=0,
                ),
                pipeline_factory=lambda runtime: _FakePipeline(runtime, calls, fail=True),
                run_record_builder=_record_builder,
                run_record_validator=lambda _record: [],
                environment=self.environment,
            )
        self.assertEqual(len(calls), 1)

        with self.assertRaisesRegex(
            ValueError, "matrix_incomplete_checkpoint_requires_budget_audit"
        ):
            run_matrix(
                self.paths,
                MatrixSettings(
                    embedding_dimensions=(
                        ("text-embedding-3-small", 2),
                        ("text-embedding-3-large", 2),
                    ),
                    run_label="interrupted",
                    case_interval_seconds=0,
                ),
                pipeline_factory=lambda runtime: _FakePipeline(runtime, calls),
                run_record_builder=_record_builder,
                run_record_validator=lambda _record: [],
                environment=self.environment,
            )
        self.assertEqual(len(calls), 1)

    def test_fail_closed_settings(self) -> None:
        with self.assertRaisesRegex(ValueError, "langfuse_metadata_egress_not_approved"):
            MatrixSettings(observability="langfuse")
        with self.assertRaisesRegex(ValueError, "matrix_budget_must_equal_five_usd"):
            MatrixSettings(max_api_budget_usd=6)
        with self.assertRaisesRegex(ValueError, "matrix_api_profile_mismatch"):
            MatrixSettings(api_profile="assignment")
        with self.assertRaisesRegex(ValueError, "matrix_case_interval_invalid"):
            MatrixSettings(case_interval_seconds=-1)
        with self.assertRaisesRegex(
            ValueError, "matrix_reasoning_effort_must_be_minimal"
        ):
            MatrixSettings(reasoning_effort="low")
        parsed = build_parser().parse_args(
            ["--repo-root", str(self.root), "--case-interval-seconds", "2.5"]
        )
        self.assertEqual(parsed.case_interval_seconds, 2.5)
        defaults = build_parser().parse_args(["--repo-root", str(self.root)])
        self.assertEqual(defaults.case_interval_seconds, 6.0)
        with self.assertRaisesRegex(ValueError, "matrix_dev_not_approved"):
            preflight_matrix(
                self.paths,
                MatrixSettings(
                    embedding_dimensions=(
                        ("text-embedding-3-small", 2),
                        ("text-embedding-3-large", 2),
                    ),
                    require_approved_dev=True,
                ),
            )


if __name__ == "__main__":
    unittest.main()
