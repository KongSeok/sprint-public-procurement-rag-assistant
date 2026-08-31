from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from midprojectrag.indexing.exact_index import ExactDenseIndex
from midprojectrag.supplemental_baseline import (
    _attach_existing_transcript_receipt,
    _build_chat_transcripts_locked,
    _exclusive_run_lock,
    _load_transcript_index,
    export_chat_transcripts,
    main,
    preflight_report,
    run_openai_baseline,
    verify_baseline,
)


class SupplementalBaselineTests(unittest.TestCase):
    @staticmethod
    def _verified():
        return type(
            "Verified",
            (),
            {
                "config": {
                    "baseline_id": "supplemental-provisional-v1",
                    "execution_contract": {
                        "explicit_egress_approval_required": True,
                    },
                },
                "config_sha256": "a" * 64,
                "answer_cases": [{"question": "secret"}] * 56,
                "set_cases": [{"question": "secret"}] * 13,
                "known_doc_ids": {f"doc_{index:024x}" for index in range(98)},
                "chunk_count": 9331,
            },
        )()

    @staticmethod
    def _run_fixture(root: Path):
        verified = SimpleNamespace(
            repo_root=root,
            config={
                "baseline_id": "supplemental-provisional-v1",
                "runtime": {
                    "max_citations": 3,
                    "case_interval_seconds": 0,
                    "api_profile": "personal_experimental",
                    "budget_limit_usd": 2.0,
                },
            },
            config_sha256="a" * 64,
            answer_cases=[
                {
                    "case_id": "supplemental-qa-test",
                    "question": "private answer question",
                }
            ],
            set_cases=[],
        )
        run_dir = root / "private-run"
        paths = {
            "answer_runs": run_dir / "answer.jsonl",
            "set_runs": run_dir / "set.jsonl",
            "checkpoint": run_dir / "run-state.json",
            "query_cache": run_dir / "query-cache",
            "budget_ledger": run_dir / "budget.json",
            "case_checkpoints": run_dir / "case-checkpoints",
            "run_lock": run_dir / ".run.lock",
        }
        return verified, paths

    @staticmethod
    def _successful_pipeline():
        class Pipeline:
            def query(self, request, *, trace_context):
                return SimpleNamespace(
                    response={
                        "status": "answered",
                        "answer": "private generated answer",
                        "citations": [{"doc_id": "doc_" + "1" * 24}],
                        "error": None,
                    },
                    retrieval=[{"doc_id": "doc_" + "1" * 24}],
                    timing_ms={"retrieval": 1, "generation": 2, "total": 3},
                    usage={
                        "embedding_tokens": 4,
                        "input_tokens": 5,
                        "output_tokens": 6,
                        "cost_usd": 0.001,
                    },
                    cache_hit=False,
                )

            def flush_observability(self) -> None:
                return None

        return Pipeline()

    def test_preflight_report_has_no_private_case_content(self) -> None:
        report = preflight_report(self._verified())
        self.assertTrue(report["passed"])
        self.assertEqual(report["provider_calls"], 0)
        self.assertEqual(report["counts"]["total_cases"], 69)
        self.assertTrue(report["execution_contract"]["explicit_egress_approval_required"])
        self.assertNotIn("secret", str(report))

    def test_cli_preflight_is_offline(self) -> None:
        output = io.StringIO()
        with (
            patch("midprojectrag.supplemental_baseline.verify_baseline", return_value=self._verified()),
            patch("midprojectrag.supplemental_baseline.score_existing") as score,
            redirect_stdout(output),
        ):
            status = main(["--preflight-only"])
        self.assertEqual(status, 0)
        score.assert_not_called()
        self.assertIn('"private_corpus_egress":false', output.getvalue())

    def test_score_existing_is_explicit_action(self) -> None:
        receipt = {"schema_version": "1.0", "passed": True}
        output = io.StringIO()
        with (
            patch("midprojectrag.supplemental_baseline.verify_baseline", return_value=self._verified()),
            patch("midprojectrag.supplemental_baseline.score_existing", return_value=receipt) as score,
            redirect_stdout(output),
        ):
            status = main(["--score-existing"])
        self.assertEqual(status, 0)
        score.assert_called_once()

    def test_provider_run_fails_before_stack_creation_without_egress_approval(self) -> None:
        with patch("midprojectrag.supplemental_baseline._load_openai_pipeline") as factory:
            with self.assertRaisesRegex(ValueError, "private_corpus_egress_not_approved"):
                run_openai_baseline(
                    self._verified(), approve_private_corpus_egress=False
                )
        factory.assert_not_called()

    def test_cli_provider_run_passes_explicit_approval_to_runner(self) -> None:
        receipt = {"schema_version": "1.0", "passed": True}
        verified = self._verified()
        output = io.StringIO()
        with (
            patch(
                "midprojectrag.supplemental_baseline.verify_baseline",
                return_value=verified,
            ),
            patch(
                "midprojectrag.supplemental_baseline.run_openai_baseline",
                return_value=receipt,
            ) as run,
            redirect_stdout(output),
        ):
            status = main(
                ["--run-openai", "--approve-private-corpus-egress"]
            )
        self.assertEqual(status, 0)
        run.assert_called_once_with(
            verified, approve_private_corpus_egress=True
        )

    def test_cli_exports_chat_transcripts_without_provider_approval(self) -> None:
        receipt = {
            "schema_version": "1.0",
            "passed": True,
            "provider_calls": 0,
        }
        verified = self._verified()
        output = io.StringIO()
        with (
            patch(
                "midprojectrag.supplemental_baseline.verify_baseline",
                return_value=verified,
            ),
            patch(
                "midprojectrag.supplemental_baseline.export_chat_transcripts",
                return_value=receipt,
            ) as export,
            redirect_stdout(output),
        ):
            status = main(["--export-chat-transcripts"])
        self.assertEqual(status, 0)
        export.assert_called_once_with(verified)
        self.assertEqual(json.loads(output.getvalue())["provider_calls"], 0)

    def test_provider_run_checkpoints_answer_and_set_without_private_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            answer_case = {
                "case_id": "supplemental-qa-test",
                "question": "private answer question",
            }
            set_case = {
                "case_id": "supplemental-set-test",
                "question": "private set question",
            }
            verified = SimpleNamespace(
                repo_root=root,
                config={
                    "baseline_id": "supplemental-provisional-v1",
                    "runtime": {
                        "max_citations": 3,
                        "case_interval_seconds": 0,
                        "api_profile": "personal_experimental",
                        "budget_limit_usd": 2.0,
                    },
                },
                config_sha256="a" * 64,
                answer_cases=[answer_case],
                set_cases=[set_case],
            )
            run_dir = root / "private-run"
            paths = {
                "answer_runs": run_dir / "answer.jsonl",
                "set_runs": run_dir / "set.jsonl",
                "checkpoint": run_dir / "run-state.json",
                "query_cache": run_dir / "query-cache",
                "budget_ledger": run_dir / "budget.json",
                "case_checkpoints": run_dir / "case-checkpoints",
                "run_lock": run_dir / ".run.lock",
            }

            class FakePipeline:
                def __init__(self) -> None:
                    self.requests: list[dict[str, object]] = []
                    self.flushed = False

                def query(self, request, *, trace_context):
                    self.requests.append(request)
                    return SimpleNamespace(
                        response={
                            "status": "answered",
                            "answer": "private generated answer",
                            "citations": [{"doc_id": "doc_" + "1" * 24}],
                            "error": None,
                        },
                        retrieval=[
                            {"doc_id": "doc_" + "1" * 24},
                            {"doc_id": "doc_" + "1" * 24},
                        ],
                        timing_ms={"retrieval": 1, "generation": 2, "total": 3},
                        usage={
                            "embedding_tokens": 4,
                            "input_tokens": 5,
                            "output_tokens": 6,
                            "cost_usd": 0.001,
                        },
                        cache_hit=False,
                    )

                def flush_observability(self) -> None:
                    self.flushed = True

            pipeline = FakePipeline()
            receipt = {"schema_version": "1.0", "passed": True}
            progress = io.StringIO()
            with (
                patch(
                    "midprojectrag.supplemental_baseline._private_run_paths",
                    return_value=paths,
                ),
                patch(
                    "midprojectrag.supplemental_baseline._load_openai_pipeline",
                    return_value=(pipeline, "b" * 64),
                ) as factory,
                patch(
                    "midprojectrag.supplemental_baseline._score_existing_locked",
                    return_value=receipt,
                ) as score,
                redirect_stderr(progress),
            ):
                self.assertEqual(
                    run_openai_baseline(
                        verified, approve_private_corpus_egress=True
                    ),
                    receipt,
                )
                # A complete resume scores without constructing the provider stack.
                factory.reset_mock()
                self.assertEqual(
                    run_openai_baseline(
                        verified, approve_private_corpus_egress=True
                    ),
                    receipt,
                )
                factory.assert_not_called()

            self.assertEqual(len(pipeline.requests), 2)
            self.assertTrue(pipeline.flushed)
            score.assert_called()
            answer_run = json.loads(paths["answer_runs"].read_text().splitlines()[0])
            set_run = json.loads(paths["set_runs"].read_text().splitlines()[0])
            self.assertEqual(answer_run["config_sha256"], "a" * 64)
            self.assertEqual(answer_run["answer"], "private generated answer")
            self.assertEqual(set_run["returned_doc_ids"], ["doc_" + "1" * 24])
            markers = sorted(paths["case_checkpoints"].glob("*.json"))
            self.assertEqual(len(markers), 2)
            self.assertTrue(
                all(
                    json.loads(path.read_text(encoding="utf-8"))["state"]
                    == "completed"
                    for path in markers
                )
            )
            self.assertNotIn("private answer question", progress.getvalue())
            self.assertNotIn("private generated answer", progress.getvalue())

    def test_started_case_blocks_automatic_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            verified, paths = self._run_fixture(Path(directory))

            class CrashingPipeline:
                def query(self, request, *, trace_context):
                    raise RuntimeError("provider_interrupted")

                def flush_observability(self) -> None:
                    return None

            with (
                patch(
                    "midprojectrag.supplemental_baseline._private_run_paths",
                    return_value=paths,
                ),
                patch(
                    "midprojectrag.supplemental_baseline._load_openai_pipeline",
                    return_value=(CrashingPipeline(), "b" * 64),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "provider_interrupted"):
                    run_openai_baseline(
                        verified, approve_private_corpus_egress=True
                    )

            marker = next(paths["case_checkpoints"].glob("*.json"))
            self.assertEqual(
                json.loads(marker.read_text(encoding="utf-8"))["state"],
                "started",
            )
            with (
                patch(
                    "midprojectrag.supplemental_baseline._private_run_paths",
                    return_value=paths,
                ),
                patch(
                    "midprojectrag.supplemental_baseline._load_openai_pipeline"
                ) as factory,
            ):
                with self.assertRaisesRegex(
                    ValueError, "baseline_started_case_requires_budget_audit"
                ):
                    run_openai_baseline(
                        verified, approve_private_corpus_egress=True
                    )
            factory.assert_not_called()

    def test_second_runner_is_rejected_by_exclusive_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            verified, paths = self._run_fixture(Path(directory))
            with _exclusive_run_lock(paths["run_lock"]):
                with (
                    patch(
                        "midprojectrag.supplemental_baseline._private_run_paths",
                        return_value=paths,
                    ),
                    patch(
                        "midprojectrag.supplemental_baseline._load_openai_pipeline"
                    ) as factory,
                ):
                    with self.assertRaisesRegex(
                        ValueError, "baseline_run_already_locked"
                    ):
                        run_openai_baseline(
                            verified, approve_private_corpus_egress=True
                        )
            factory.assert_not_called()

    def test_non_empty_resume_requires_bound_budget_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            verified, paths = self._run_fixture(Path(directory))
            receipt = {"schema_version": "1.0", "passed": True}
            with (
                patch(
                    "midprojectrag.supplemental_baseline._private_run_paths",
                    return_value=paths,
                ),
                patch(
                    "midprojectrag.supplemental_baseline._load_openai_pipeline",
                    return_value=(self._successful_pipeline(), "b" * 64),
                ),
                patch(
                    "midprojectrag.supplemental_baseline._score_existing_locked",
                    return_value=receipt,
                ),
            ):
                self.assertEqual(
                    run_openai_baseline(
                        verified, approve_private_corpus_egress=True
                    ),
                    receipt,
                )
            paths["budget_ledger"].unlink()
            with (
                patch(
                    "midprojectrag.supplemental_baseline._private_run_paths",
                    return_value=paths,
                ),
                patch(
                    "midprojectrag.supplemental_baseline._load_openai_pipeline"
                ) as factory,
            ):
                with self.assertRaisesRegex(
                    ValueError, "baseline_budget_ledger_missing"
                ):
                    run_openai_baseline(
                        verified, approve_private_corpus_egress=True
                    )
            factory.assert_not_called()

    def test_unexpected_cli_exception_is_sanitized(self) -> None:
        output = io.StringIO()
        errors = io.StringIO()
        secret = "PRIVATE_EXCEPTION_DETAIL"
        with (
            patch(
                "midprojectrag.supplemental_baseline.verify_baseline",
                side_effect=TypeError(secret),
            ),
            redirect_stdout(output),
            redirect_stderr(errors),
        ):
            status = main(["--preflight-only"])
        self.assertEqual(status, 2)
        payload = output.getvalue()
        self.assertNotIn(secret, payload + errors.getvalue())
        self.assertEqual(
            json.loads(payload)["error"]["code"],
            "supplemental_baseline_failed",
        )

    def test_chat_transcript_export_is_offline_private_and_reconstructed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            doc_id = "doc_" + "1" * 24
            chunk_id = "chunk_" + "2" * 24
            answer_case = {
                "case_id": "supplemental-qa-test",
                "question": "PRIVATE_ANSWER_QUESTION",
            }
            set_case = {
                "case_id": "supplemental-set-test",
                "question": "PRIVATE_SET_QUESTION",
            }
            verified = SimpleNamespace(
                repo_root=root,
                config={
                    "baseline_id": "supplemental-provisional-v1",
                    "artifacts": {
                        "manifest_sha256": "b" * 64,
                        "chunks_sha256": "c" * 64,
                        "index_metadata_sha256": "d" * 64,
                    },
                    "runtime": {
                        "embedding_model": "text-embedding-3-small",
                        "embedding_dimensions": 1,
                        "generator_model": "gpt-5-mini",
                        "retrieval_top_k": 10,
                        "context_top_k": 5,
                        "max_citations": 3,
                        "max_output_tokens": 2000,
                        "reasoning_effort": "minimal",
                    },
                },
                config_sha256="a" * 64,
                answer_cases=[answer_case],
                set_cases=[set_case],
            )
            answer_run = {
                "case_id": answer_case["case_id"],
                "status": "answered",
                "answer": "PRIVATE_FINAL_ANSWER",
                "retrieved_doc_ids": [doc_id],
                "cited_doc_ids": [doc_id],
                "timing_ms": {"retrieval": 1.0, "generation": 2.0, "total": 3.0},
                "usage": {
                    "embedding_tokens": 1,
                    "input_tokens": 2,
                    "output_tokens": 3,
                    "cost_usd": 0.001,
                },
                "cache_hit": True,
                "error": None,
            }
            set_run = {
                "case_id": set_case["case_id"],
                "returned_doc_ids": [doc_id],
                "error": None,
            }
            run_dir = root / "evaluation/private/run"
            paths = {
                "answer_runs": run_dir / "answer.jsonl",
                "set_runs": run_dir / "set.jsonl",
                "query_cache": run_dir / "query-cache",
                "receipt": root / "evaluation/baselines/receipt.json",
                "chat_transcripts": run_dir / "chat-transcripts.jsonl",
            }
            paths["receipt"].parent.mkdir(parents=True)
            paths["receipt"].write_text(
                json.dumps(
                    {
                        "baseline_id": verified.config["baseline_id"],
                        "config_sha256": verified.config_sha256,
                        "artifact_sha256s": {},
                        "counts": {},
                    }
                ),
                encoding="utf-8",
            )

            hit = SimpleNamespace(
                score=0.75,
                chunk={
                    "doc_id": doc_id,
                    "chunk_id": chunk_id,
                    "text": "PRIVATE_SOURCE_CONTEXT",
                    "page_start": 1,
                    "page_end": 1,
                    "section_path": [],
                    "source_block_ids": [],
                    "retrieval_role": "primary",
                    "chunker_id": "fixed-test",
                },
            )

            class OfflineIndex:
                def search(self, vector, *, top_k, allowed_doc_ids):
                    self.assertions = (top_k, allowed_doc_ids)
                    return [hit]

            index = OfflineIndex()
            with (
                patch(
                    "midprojectrag.supplemental_baseline._load_or_initialize_runs",
                    return_value=([answer_run], [set_run]),
                ),
                patch(
                    "midprojectrag.supplemental_baseline._load_transcript_index",
                    return_value=index,
                ),
                patch(
                    "midprojectrag.supplemental_baseline._cached_query_vector",
                    side_effect=[
                        (np.asarray([1.0], dtype=np.float32), "e" * 64, "user: PRIVATE_ANSWER_QUESTION"),
                        (np.asarray([1.0], dtype=np.float32), "f" * 64, "user: PRIVATE_SET_QUESTION"),
                        (np.asarray([1.0], dtype=np.float32), "e" * 64, "user: PRIVATE_ANSWER_QUESTION"),
                        (np.asarray([1.0], dtype=np.float32), "f" * 64, "user: PRIVATE_SET_QUESTION"),
                    ],
                ),
                patch(
                    "midprojectrag.supplemental_baseline._load_openai_pipeline"
                ) as provider_factory,
            ):
                report = _build_chat_transcripts_locked(verified, paths)

            provider_factory.assert_not_called()
            self.assertEqual(report["provider_calls"], 0)
            self.assertEqual(report["counts"]["transcripts"], 2)
            rows = [
                json.loads(line)
                for line in paths["chat_transcripts"].read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            self.assertEqual(len(rows), 2)
            self.assertIn(
                "PRIVATE_SOURCE_CONTEXT",
                rows[0]["provider_request"]["arguments"]["input"],
            )
            self.assertEqual(
                rows[0]["assistant"]["persisted_answer"],
                "PRIVATE_FINAL_ANSWER",
            )
            self.assertIn(
                "provider.raw_response_envelope", rows[0]["unavailable_fields"]
            )
            self.assertEqual(
                rows[0]["runtime_equivalence"]["verification_level"],
                "retrieved_doc_id_projection_only",
            )
            self.assertIn("assistant.status", rows[1]["unavailable_fields"])
            public_receipt = paths["receipt"].read_text(encoding="utf-8")
            self.assertNotIn("PRIVATE_", public_receipt)
            public_value = json.loads(public_receipt)
            self.assertEqual(public_value["counts"]["chat_transcripts"], 2)
            self.assertEqual(
                public_value["artifact_sha256s"]["chat_transcripts"],
                report["chat_transcripts_sha256"],
            )
            self.assertEqual(
                public_value["counts"]["chat_transcripts_runtime_exact"], 0
            )
            self.assertEqual(
                public_value["counts"][
                    "chat_transcripts_exact_persisted_answers"
                ],
                1,
            )
            stale_answer_run = dict(answer_run)
            stale_answer_run["answer"] = "DIFFERENT_PRIVATE_ANSWER"
            with self.assertRaisesRegex(
                ValueError, "baseline_transcript_artifact_invalid"
            ):
                _attach_existing_transcript_receipt(
                    verified,
                    paths,
                    public_value,
                    [stale_answer_run],
                    [set_run],
                )

    def test_chat_transcript_index_config_must_match_runtime_loader(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index_dir = root / "index"
            index_dir.mkdir()
            (index_dir / "metadata.json").write_text(
                json.dumps({"index_config_sha256": "a" * 64}),
                encoding="utf-8",
            )
            (index_dir / "index-config.json").write_text("{}", encoding="utf-8")
            verified = SimpleNamespace(
                repo_root=root,
                config={
                    "artifacts": {
                        "chunks": "chunks.jsonl",
                        "index_dir": "index",
                    },
                    "runtime": {
                        "embedding_model": "text-embedding-3-small",
                        "embedding_dimensions": 1536,
                        "api_profile": "personal_experimental",
                    },
                },
            )
            with (
                patch(
                    "midprojectrag.supplemental_baseline.read_jsonl",
                    return_value=[],
                ),
                patch(
                    "midprojectrag.supplemental_baseline.api_config_sha256",
                    return_value="b" * 64,
                ),
                patch.object(ExactDenseIndex, "_load_unlocked") as loader,
            ):
                with self.assertRaisesRegex(
                    ValueError, "baseline_index_config_hash_mismatch"
                ):
                    _load_transcript_index(verified)
            loader.assert_not_called()

    def test_chat_transcript_export_fails_closed_on_missing_query_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            verified = SimpleNamespace(
                config={
                    "baseline_id": "supplemental-provisional-v1",
                    "artifacts": {
                        "manifest_sha256": "b" * 64,
                        "chunks_sha256": "c" * 64,
                        "index_metadata_sha256": "d" * 64,
                    },
                    "runtime": {
                        "max_citations": 3,
                        "retrieval_top_k": 10,
                        "context_top_k": 5,
                    },
                },
                config_sha256="a" * 64,
                answer_cases=[
                    {
                        "case_id": "supplemental-qa-test",
                        "question": "PRIVATE_QUESTION",
                    }
                ],
                set_cases=[],
            )
            paths = {
                "chat_transcripts": root / "chat-transcripts.jsonl",
                "receipt": root / "receipt.json",
            }
            paths["receipt"].write_text(
                json.dumps(
                    {
                        "baseline_id": verified.config["baseline_id"],
                        "config_sha256": verified.config_sha256,
                        "artifact_sha256s": {},
                        "counts": {},
                    }
                ),
                encoding="utf-8",
            )
            run = {
                "case_id": "supplemental-qa-test",
                "retrieved_doc_ids": [],
            }
            with (
                patch(
                    "midprojectrag.supplemental_baseline._load_or_initialize_runs",
                    return_value=([run], []),
                ),
                patch(
                    "midprojectrag.supplemental_baseline._load_transcript_index",
                    return_value=SimpleNamespace(),
                ),
                patch(
                    "midprojectrag.supplemental_baseline._cached_query_vector",
                    side_effect=ValueError(
                        "baseline_transcript_query_cache_missing"
                    ),
                ),
            ):
                with self.assertRaisesRegex(
                    ValueError, "baseline_transcript_query_cache_missing"
                ):
                    _build_chat_transcripts_locked(verified, paths)
            self.assertFalse(paths["chat_transcripts"].exists())

    def test_frozen_private_assets_match_checked_in_preflight_receipt(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        config = repo_root / "evaluation/baselines/supplemental-provisional-v1/config.json"
        private_cases = repo_root / "evaluation/private/supplemental/build-v1/rag-56.draft.jsonl"
        if not private_cases.is_file():
            self.skipTest("private supplemental assets are not available")
        report = preflight_report(verify_baseline(config))
        receipt = json.loads(
            (config.parent / "preflight-receipt.json").read_text(encoding="utf-8")
        )
        self.assertEqual(report, receipt)


if __name__ == "__main__":
    unittest.main()
