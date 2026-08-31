from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from midprojectrag.answering.generation import SYSTEM_INSTRUCTIONS
from midprojectrag.answering.pipeline import (
    _build_prompt,
    _retrieval_query,
    _select_context_hits,
)
from midprojectrag.core40_baseline import (
    BASELINE_ID,
    EXECUTION_CONTRACT,
    FROZEN_RUNTIME,
    INTERRUPTED_ERROR_RECOVERY_MODE,
    RuntimeBundle,
    build_request,
    preflight_report,
    recover_interrupted_as_error,
    run_openai_baseline,
    verify_baseline,
)
from midprojectrag.evaluation import dataset_sha256, validate_case
from midprojectrag.ingest.common import (
    canonical_json,
    sha256_file,
    sha256_text,
    write_json,
    write_jsonl,
)
from midprojectrag.indexing.budget import BudgetLedger
from midprojectrag.indexing.embeddings import EmbeddingCache
from midprojectrag.indexing.exact_index import ExactDenseIndex, IndexSearchHit
from midprojectrag.stacks.api import api_config_sha256, build_api_index_config
from midprojectrag.stacks.api.generation import build_openai_answer_plan_schema


def _chunk(number: int) -> dict[str, object]:
    text = f"synthetic refined page {number}"
    doc_id = f"doc_{number:024x}"
    block_id = f"block_{number:024x}"
    config_sha256 = "c" * 64
    content_sha256 = sha256_text(text)
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
    axes: list[str] = []
    if task == "multi_doc_compare":
        required_docs.append(doc_two)
        evidence.append(
            {
                "doc_id": doc_two,
                "source_block_id": block_two,
                "locator_hash": sha256_text(f"locator-{task}-{number}-two"),
            }
        )
        axes = ["budget"]
    history: list[dict[str, object]] = []
    conversation = None
    if task == "follow_up":
        history = [
            {"turn_id": f"turn-{number}-1", "role": "user", "content": "prior question"},
            {
                "turn_id": f"turn-{number}-2",
                "role": "assistant",
                "content": "prior grounded answer",
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
            "reference_answer": None if task == "unknown" else "synthetic answer",
            "required_key_points": []
            if task == "unknown"
            else [{"point_id": f"kp_{aliases[task]}_{number}", "text": "point"}],
            "required_doc_ids": required_docs,
            "evidence_refs": evidence,
            "comparison_axes": axes,
            "abstain_reason": "insufficient_evidence" if task == "unknown" else None,
        },
        "difficulty": "medium",
        "tags": ["synthetic"],
        "source_manifest_sha256": manifest_sha256,
        "review": {"author": "fixture", "reviewer": "pending", "status": "draft"},
    }
    assert validate_case(case) == []
    return case


class _FakeAudit:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.value = {"embedding": None, "generation": None}

    def snapshot(self):
        return json.loads(json.dumps(self.value))


class _FakePipeline:
    def __init__(self, verified, audit, calls):
        self.verified = verified
        self.audit = audit
        self.calls = calls
        self.flushes = 0

    def query(self, request, *, trace_context=None):
        self.calls.append((request, trace_context))
        allowed = (
            set(request["document_scope"]["doc_ids"])
            if request["document_scope"]["mode"] == "explicit"
            else None
        )
        chunks = [
            chunk
            for chunk in self.verified.chunks
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
            for rank, chunk in enumerate(chunks, start=1)
        ]
        hits = [
            IndexSearchHit(row_id=-1, score=row["score"], chunk=chunk)
            for row, chunk in zip(retrieval, chunks, strict=True)
        ]
        prompt = _build_prompt(request, hits[:5])
        if request["document_scope"]["mode"] == "all":
            plan = {
                "status": "abstained",
                "answer": "",
                "citation_chunk_ids": [],
                "abstention_reason": "insufficient_evidence",
            }
            response = {
                "schema_version": "1.0",
                "request_id": request["request_id"],
                "status": "abstained",
                "answer": "제공된 문서에서 답변 근거를 찾지 못했습니다.",
                "citations": [],
                "abstention": {"reason": "insufficient_evidence", "detail": "synthetic"},
                "error": None,
                "trace_id": sha256_text(request["request_id"])[:32],
            }
        else:
            selected = chunks[0]
            plan = {
                "status": "answered",
                "answer": "synthetic grounded answer",
                "citation_chunk_ids": [selected["chunk_id"]],
                "abstention_reason": None,
            }
            response = {
                "schema_version": "1.0",
                "request_id": request["request_id"],
                "status": "answered",
                "answer": plan["answer"],
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
                "trace_id": sha256_text(request["request_id"])[:32],
            }
        self.audit.value = {
            "embedding": {
                "request_arguments": {
                    "model": "text-embedding-3-small",
                    "input": [request["question"]],
                    "dimensions": 1536,
                    "encoding_format": "float",
                },
                "response": {"vectors_omitted": True, "vectors_sha256": "d" * 64},
                "error": None,
            },
            "generation": {
                "request_arguments": {
                    "model": "gpt-5-mini",
                    "instructions": "synthetic",
                    "input": prompt,
                },
                "response": {
                    "status": "completed",
                    "output_text": json.dumps({"result": plan}),
                },
                "error": None,
            },
        }
        return SimpleNamespace(
            response=response,
            retrieval=retrieval,
            timing_ms={"retrieval": 1.0, "generation": 2.0, "total": 3.0},
            usage={
                "input_tokens": 10,
                "output_tokens": 5,
                "embedding_tokens": 2,
                "cost_usd": 0.0,
                "gpu_seconds": None,
                "peak_vram_gb": None,
            },
            cache_hit=False,
        )

    def flush_observability(self):
        self.flushes += 1


class _UncertainPipeline:
    def __init__(self, audit):
        self.audit = audit
        self.flushes = 0

    def query(self, _request, *, trace_context=None):
        self.audit.value["generation"] = {
            "request_arguments": {"input": "private synthetic prompt"},
            "response": None,
            "error": {
                "type": "RuntimeError",
                "message": "synthetic uncertain provider transport",
            },
        }
        return SimpleNamespace()

    def flush_observability(self):
        self.flushes += 1


class _ProviderResponseThenCandidateErrorPipeline:
    def __init__(self, audit):
        self.audit = audit
        self.flushes = 0

    def query(self, request, *, trace_context=None):
        self.audit.value["embedding"] = {
            "request_arguments": {
                "model": "text-embedding-3-small",
                "input": [request["question"]],
                "dimensions": 1536,
                "encoding_format": "float",
            },
            "response": {
                "vectors_omitted": True,
                "vectors_sha256": "d" * 64,
            },
            "error": None,
        }
        return SimpleNamespace(
            response={
                "schema_version": "1.0",
                "request_id": request["request_id"],
                "status": "error",
                "answer": "",
                "citations": [],
                "abstention": None,
                "error": {
                    "code": "embedding_vector_invalid",
                    "message": "provider response vector failed validation",
                },
                "trace_id": sha256_text(request["request_id"])[:32],
            },
            retrieval=[],
            timing_ms={"retrieval": 0.0, "generation": 0.0, "total": 1.0},
            usage={
                "input_tokens": 0,
                "output_tokens": 0,
                "embedding_tokens": 0,
                "cost_usd": 0.0,
                "gpu_seconds": None,
                "peak_vram_gb": None,
            },
            cache_hit=False,
        )

    def flush_observability(self):
        self.flushes += 1


class _DeterministicCounter:
    def count(self, text):
        return max(1, len(text.encode("utf-8")) // 4)


class _RecoverableConnectionPipeline:
    def __init__(
        self,
        verified,
        paths,
        audit,
        counter,
        *,
        prompt_suffix="",
        error_type="APIConnectionError",
    ):
        self.verified = verified
        self.paths = paths
        self.audit = audit
        self.counter = counter
        self.prompt_suffix = prompt_suffix
        self.error_type = error_type
        self.flushes = 0

    def query(self, request, *, trace_context=None):
        runtime = self.verified.config["runtime"]
        retrieval_query = _retrieval_query(
            request,
            self.counter,
            max_tokens=8191,
        )
        query_vector = np.zeros((runtime["embedding_dimensions"],), dtype=np.float32)
        query_vector[0] = 1.0
        query_cache_key = EmbeddingCache.key(
            corpus_manifest_sha256=self.verified.config["artifacts"]["manifest_sha256"],
            chunk_config_sha256=sha256_text("query-v1"),
            model=runtime["embedding_model"],
            dimensions=runtime["embedding_dimensions"],
            content_sha256=sha256_text(retrieval_query),
        )
        EmbeddingCache(self.paths["query_cache"]).put(query_cache_key, query_vector)
        scope = request["document_scope"]
        allowed = set(scope["doc_ids"]) if scope["mode"] == "explicit" else None
        hits = self.verified.index.search(
            query_vector,
            top_k=runtime["retrieval_top_k"],
            allowed_doc_ids=allowed,
        )
        context_hits = _select_context_hits(
            hits,
            context_top_k=runtime["context_top_k"],
            table_context_cap=None,
        )
        prompt = _build_prompt(request, context_hits) + self.prompt_suffix
        self.audit.value = {
            "embedding": {
                "request_arguments": {
                    "model": runtime["embedding_model"],
                    "input": [retrieval_query],
                    "dimensions": runtime["embedding_dimensions"],
                    "encoding_format": "float",
                },
                "response": {
                    "object": "list",
                    "model": runtime["embedding_model"],
                    "usage": {"prompt_tokens": 7, "total_tokens": 7},
                    "vectors_omitted": True,
                    "vectors_sha256": "d" * 64,
                },
                "error": None,
            },
            "generation": {
                "request_arguments": {
                    "model": runtime["generator_model"],
                    "instructions": SYSTEM_INSTRUCTIONS,
                    "input": prompt,
                    "store": False,
                    "max_output_tokens": runtime["max_output_tokens"],
                    "reasoning": {"effort": runtime["reasoning_effort"]},
                    "text": {
                        "format": {
                            "type": "json_schema",
                            "name": "rag_answer_plan",
                            "strict": True,
                            "schema": build_openai_answer_plan_schema(
                                runtime["max_citations"]
                            ),
                        }
                    },
                },
                "response": None,
                "error": {
                    "type": self.error_type,
                    "message": "synthetic connection failure",
                },
            },
        }
        return SimpleNamespace()

    def flush_observability(self):
        self.flushes += 1


class _InterruptAtCasePipeline:
    def __init__(self, verified, paths, audit, counter, target_case_id, calls):
        self.audit = audit
        self.target_case_id = target_case_id
        self.normal = _FakePipeline(verified, audit, calls)
        self.interrupted = _RecoverableConnectionPipeline(
            verified,
            paths,
            audit,
            counter,
        )
        self.flushes = 0

    def query(self, request, *, trace_context=None):
        if trace_context["case_id"] == self.target_case_id:
            return self.interrupted.query(request, trace_context=trace_context)
        return self.normal.query(request, trace_context=trace_context)

    def flush_observability(self):
        self.flushes += 1


class Core40BaselineTests(unittest.TestCase):
    def _fixture(self, root: Path) -> Path:
        (root / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
        manifest = root / "resources/data_refined/private/manifest.extracted.jsonl"
        write_jsonl(
            manifest,
            [
                {"doc_id": f"doc_{number:024x}", "index_eligible": True}
                for number in (1, 2)
            ],
        )
        manifest_sha256 = sha256_file(manifest)
        chunks = [_chunk(1), _chunk(2)]
        chunks_path = root / "resources/data_refined/private/chunks.page-v1.jsonl"
        write_jsonl(chunks_path, chunks)
        cases = [
            _case(task, number, manifest_sha256)
            for task in ("single_doc", "multi_doc_compare", "follow_up", "unknown")
            for number in range(1, 11)
        ]
        cases_path = root / "golden-set-final/dev.refined.review-candidate.jsonl"
        write_jsonl(cases_path, cases)

        index_dir = root / "resources/data_refined/private/indexes/api/personal_experimental/text-embedding-3-small-1536"
        vectors = np.zeros((2, 1536), dtype=np.float32)
        vectors[0, 0] = 1.0
        vectors[1, 1] = 1.0
        index_config = build_api_index_config(
            api_profile="personal_experimental",
            corpus_manifest_sha256=manifest_sha256,
            chunk_artifact_sha256=sha256_file(chunks_path),
            chunk_config_sha256="c" * 64,
            embedding_model="text-embedding-3-small",
            embedding_dimensions=1536,
            index_engine="numpy",
            batch_size=128,
        )
        write_json(index_dir / "index-config.json", index_config)
        ExactDenseIndex.from_normalized_vectors(chunks, vectors, engine="numpy").save(
            index_dir,
            corpus_manifest_sha256=manifest_sha256,
            embedding_model="text-embedding-3-small",
            api_profile="personal_experimental",
            index_config_sha256=api_config_sha256(index_config),
        )
        (root / "resources/data_refined/private/tiktoken-cache").mkdir(parents=True)

        config_path = root / f"evaluation/baselines/{BASELINE_ID}/config.json"
        config = {
            "schema_version": "1.0",
            "baseline_id": BASELINE_ID,
            "evaluation_tier": "provisional",
            "expected_counts": {
                "single_doc": 10,
                "multi_doc_compare": 10,
                "follow_up": 10,
                "unknown": 10,
                "total": 40,
            },
            "artifacts": {
                "cases": "golden-set-final/dev.refined.review-candidate.jsonl",
                "cases_file_sha256": sha256_file(cases_path),
                "cases_dataset_sha256": dataset_sha256(cases),
                "cases_jsonl_canonical_sha256": sha256_text(
                    "\n".join(canonical_json(case) for case in cases) + "\n"
                ),
                "manifest": "resources/data_refined/private/manifest.extracted.jsonl",
                "manifest_sha256": manifest_sha256,
                "chunks": "resources/data_refined/private/chunks.page-v1.jsonl",
                "chunks_sha256": sha256_file(chunks_path),
                "index_dir": "resources/data_refined/private/indexes/api/personal_experimental/text-embedding-3-small-1536",
                "index_metadata_sha256": sha256_file(index_dir / "metadata.json"),
                "index_config_file_sha256": sha256_file(index_dir / "index-config.json"),
                "tiktoken_cache_dir": "resources/data_refined/private/tiktoken-cache",
            },
            "runtime": dict(FROZEN_RUNTIME),
            "execution_contract": EXECUTION_CONTRACT,
            "outputs": {
                "run_records": "evaluation/private/core40/runs/provisional-v1/run-records.jsonl",
                "chat_transcripts": "evaluation/private/core40/runs/provisional-v1/chat-transcripts.jsonl",
                "private_summary": "evaluation/private/core40/runs/provisional-v1/summary.json",
                "preflight_receipt": f"evaluation/baselines/{BASELINE_ID}/preflight-receipt.json",
                "receipt": f"evaluation/baselines/{BASELINE_ID}/receipt.json",
            },
        }
        write_json(config_path, config)
        return config_path

    def _create_recoverable_interruption(
        self,
        verified,
        *,
        prompt_suffix="",
        error_type="APIConnectionError",
    ):
        audit = _FakeAudit()
        counter = _DeterministicCounter()
        holder = {}

        def factory(checked, paths):
            pipeline = _RecoverableConnectionPipeline(
                checked,
                paths,
                audit,
                counter,
                prompt_suffix=prompt_suffix,
                error_type=error_type,
            )
            holder["pipeline"] = pipeline
            return RuntimeBundle(
                pipeline=pipeline,
                audit=audit,
                index_config_sha256=checked.index_metadata["index_config_sha256"],
            )

        with self.assertRaisesRegex(
            ValueError,
            "core40_provider_call_requires_budget_audit",
        ):
            run_openai_baseline(
                verified,
                approve_openai_egress=True,
                runtime_factory=factory,
                sleeper=lambda _seconds: None,
            )
        return verified.cases[0]["case_id"], counter, holder["pipeline"]

    def test_preflight_is_offline_and_preserves_scope_history_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._fixture(Path(directory))
            verified = verify_baseline(config_path)
            report = preflight_report(verified)
            self.assertTrue(report["passed"])
            self.assertEqual(report["provider_calls_performed"], 0)
            self.assertEqual(report["runtime"]["openai_max_retries"], 0)
            self.assertEqual(
                report["execution_contract"]["provider_attempt_policy"],
                {
                    "openai_sdk_max_retries": 0,
                    "maximum_attempts_per_case": 1,
                    "maximum_suite_calls": 80,
                },
            )
            self.assertEqual(report["counts"]["history_cases"], 10)
            self.assertEqual(report["counts"]["explicit_scope_cases"], 30)
            self.assertEqual(
                {
                    "indexing_embeddings_module",
                    "api_embeddings_module",
                    "budget_module",
                    "exact_index_module",
                },
                {
                    key
                    for key in report["runtime_contract_sha256s"]
                    if key in {
                        "indexing_embeddings_module",
                        "api_embeddings_module",
                        "budget_module",
                        "exact_index_module",
                    }
                },
            )
            follow_up = next(case for case in verified.cases if case["task_type"] == "follow_up")
            request = build_request(follow_up, config_sha256=verified.config_sha256, max_citations=3)
            self.assertEqual(request["history"], follow_up["history"])
            self.assertEqual(request["document_scope"], follow_up["document_scope"])

    def test_live_runtime_requires_explicit_egress_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            verified = verify_baseline(self._fixture(Path(directory)))
            factory_calls = []

            def factory(*_args):
                factory_calls.append(True)
                raise AssertionError("must not create provider runtime")

            with self.assertRaisesRegex(ValueError, "core40_openai_egress_not_approved"):
                run_openai_baseline(
                    verified,
                    approve_openai_egress=False,
                    runtime_factory=factory,
                )
            self.assertEqual(factory_calls, [])

    def test_runtime_records_exact_transcripts_and_resumes_completed_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            verified = verify_baseline(self._fixture(Path(directory)))
            calls = []
            bundles = []

            def factory(checked, _paths):
                audit = _FakeAudit()
                pipeline = _FakePipeline(checked, audit, calls)
                bundle = RuntimeBundle(
                    pipeline=pipeline,
                    audit=audit,
                    index_config_sha256=checked.index_metadata["index_config_sha256"],
                )
                bundles.append(bundle)
                return bundle

            receipt = run_openai_baseline(
                verified,
                approve_openai_egress=True,
                runtime_factory=factory,
                sleeper=lambda _seconds: None,
            )
            self.assertTrue(receipt["passed"])
            self.assertEqual(receipt["counts"]["completed"], 40)
            self.assertEqual(len(calls), 40)
            transcript_path = verified.repo_root / verified.config["outputs"]["chat_transcripts"]
            transcripts = [json.loads(line) for line in transcript_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(transcripts), 40)
            follow_up = next(row for row in transcripts if row["case_id"].startswith("dev-followup"))
            self.assertTrue(follow_up["request"]["history"])
            self.assertEqual(follow_up["request"]["document_scope"]["mode"], "explicit")
            self.assertTrue(follow_up["selected_context"][0]["source_text"])
            self.assertEqual(
                follow_up["generation_prompt"],
                follow_up["provider_exchange"]["generation"]["request_arguments"]["input"],
            )
            self.assertIsNotNone(follow_up["assistant"]["structured_plan"])
            self.assertEqual(transcript_path.stat().st_mode & 0o777, 0o600)

            resumed = run_openai_baseline(
                verified,
                approve_openai_egress=True,
                runtime_factory=lambda *_args: (_ for _ in ()).throw(
                    AssertionError("completed resume must not create provider runtime")
                ),
            )
            self.assertTrue(resumed["passed"])
            self.assertEqual(len(calls), 40)

            with patch(
                "midprojectrag.core40_baseline._contract_sha256s",
                return_value={
                    **verified.runtime_contract_sha256s,
                    "prompt_builder_source": "0" * 64,
                },
            ):
                with self.assertRaisesRegex(
                    ValueError, "core40_runtime_contract_drift"
                ):
                    run_openai_baseline(
                        verified,
                        approve_openai_egress=True,
                        runtime_factory=lambda *_args: (_ for _ in ()).throw(
                            AssertionError("runtime drift must fail before provider setup")
                        ),
                    )

    def test_uncertain_provider_exchange_stops_with_interrupted_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            verified = verify_baseline(self._fixture(Path(directory)))
            audit = _FakeAudit()
            pipeline = _UncertainPipeline(audit)

            def factory(checked, _paths):
                return RuntimeBundle(
                    pipeline=pipeline,
                    audit=audit,
                    index_config_sha256=checked.index_metadata["index_config_sha256"],
                )

            with self.assertRaisesRegex(
                ValueError, "core40_provider_call_requires_budget_audit"
            ):
                run_openai_baseline(
                    verified,
                    approve_openai_egress=True,
                    runtime_factory=factory,
                    sleeper=lambda _seconds: None,
                )

            checkpoint_dir = (
                verified.repo_root
                / "evaluation/private/core40/runs/provisional-v1/case-checkpoints"
            )
            checkpoints = list(checkpoint_dir.glob("*.json"))
            self.assertEqual(len(checkpoints), 1)
            envelope = json.loads(checkpoints[0].read_text(encoding="utf-8"))
            payload = envelope["payload"]
            self.assertEqual(payload["state"], "interrupted")
            self.assertTrue(
                payload["runtime_error"]["manual_budget_audit_required"]
            )
            self.assertIsNotNone(
                payload["provider_exchange"]["generation"]["error"]
            )
            self.assertEqual(pipeline.flushes, 1)
            with self.assertRaisesRegex(
                ValueError, "core40_interrupted_case_requires_budget_audit"
            ):
                run_openai_baseline(
                    verified,
                    approve_openai_egress=True,
                    runtime_factory=lambda *_args: (_ for _ in ()).throw(
                        AssertionError("interrupted resume must not reach provider")
                    ),
                )

    def test_candidate_error_after_provider_response_requires_budget_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            verified = verify_baseline(self._fixture(Path(directory)))
            audit = _FakeAudit()
            pipeline = _ProviderResponseThenCandidateErrorPipeline(audit)

            def factory(checked, _paths):
                return RuntimeBundle(
                    pipeline=pipeline,
                    audit=audit,
                    index_config_sha256=checked.index_metadata["index_config_sha256"],
                )

            with self.assertRaisesRegex(
                ValueError, "core40_provider_call_requires_budget_audit"
            ):
                run_openai_baseline(
                    verified,
                    approve_openai_egress=True,
                    runtime_factory=factory,
                    sleeper=lambda _seconds: None,
                )

            run_dir = (
                verified.repo_root
                / "evaluation/private/core40/runs/provisional-v1"
            )
            checkpoints = list((run_dir / "case-checkpoints").glob("*.json"))
            self.assertEqual(len(checkpoints), 1)
            envelope = json.loads(checkpoints[0].read_text(encoding="utf-8"))
            payload = envelope["payload"]
            self.assertEqual(payload["state"], "interrupted")
            self.assertTrue(
                payload["runtime_error"]["manual_budget_audit_required"]
            )
            self.assertIsNotNone(
                payload["provider_exchange"]["embedding"]["response"]
            )
            self.assertIsNone(
                payload["provider_exchange"]["embedding"]["error"]
            )
            self.assertNotIn("result", payload)
            self.assertFalse((run_dir / "run-records.jsonl").exists())
            self.assertFalse((run_dir / "chat-transcripts.jsonl").exists())
            self.assertEqual(pipeline.flushes, 1)

            with self.assertRaisesRegex(
                ValueError, "core40_interrupted_case_requires_budget_audit"
            ):
                run_openai_baseline(
                    verified,
                    approve_openai_egress=True,
                    runtime_factory=lambda *_args: (_ for _ in ()).throw(
                        AssertionError("interrupted resume must not reach provider")
                    ),
                )

    def test_explicit_recovery_records_error_without_retry_and_resume_skips_case(self):
        with tempfile.TemporaryDirectory() as directory:
            verified = verify_baseline(self._fixture(Path(directory)))
            case_id, counter, interrupted_pipeline = self._create_recoverable_interruption(
                verified
            )
            run_dir = (
                verified.repo_root
                / "evaluation/private/core40/runs/provisional-v1"
            )
            checkpoint_path = next((run_dir / "case-checkpoints").glob("*.json"))
            interrupted = json.loads(checkpoint_path.read_text(encoding="utf-8"))[
                "payload"
            ]
            original_exchange = interrupted["provider_exchange"]

            recovered = recover_interrupted_as_error(
                verified,
                case_id=case_id,
                counter_factory=lambda _model, _path: counter,
            )
            self.assertTrue(recovered["passed"])
            self.assertEqual(recovered["provider_calls_performed"], 0)
            self.assertEqual(recovered["candidate_status"], "error")
            self.assertEqual(recovered["counts"]["completed"], 1)
            self.assertGreater(recovered["provider_budget"]["reserved_usd"], 0)
            first_reserved = recovered["provider_budget"]["reserved_usd"]

            completed = json.loads(checkpoint_path.read_text(encoding="utf-8"))[
                "payload"
            ]
            self.assertEqual(completed["state"], "completed")
            self.assertEqual(completed["result"]["response"]["status"], "error")
            self.assertEqual(
                completed["chat_transcript"]["provider_exchange"],
                original_exchange,
            )
            self.assertTrue(completed["chat_transcript"]["retrieval"])
            self.assertEqual(
                completed["chat_transcript"]["generation_prompt"],
                original_exchange["generation"]["request_arguments"]["input"],
            )
            self.assertEqual(
                completed["recovery"]["mode"],
                INTERRUPTED_ERROR_RECOVERY_MODE,
            )
            self.assertEqual(completed["recovery"]["provider_calls_performed"], 0)
            self.assertEqual(interrupted_pipeline.flushes, 1)
            public_receipt_path = (
                verified.repo_root / verified.config["outputs"]["receipt"]
            )
            first_amendment = json.loads(
                public_receipt_path.read_text(encoding="utf-8")
            )["runtime_contract_amendment"]
            self.assertEqual(first_amendment["failed_case_count"], 1)
            self.assertFalse(first_amendment["failed_cases_retried"])
            self.assertTrue(first_amendment["provider_attempts_preserved"])
            self.assertEqual(first_amendment["provider_retries"], 0)
            self.assertEqual(first_amendment["recovery_audit_count"], 1)

            idempotent = recover_interrupted_as_error(
                verified,
                case_id=case_id,
                counter_factory=lambda _model, _path: counter,
            )
            self.assertEqual(
                idempotent["provider_budget"]["reserved_usd"],
                first_reserved,
            )
            self.assertEqual(
                json.loads(public_receipt_path.read_text(encoding="utf-8"))[
                    "runtime_contract_amendment"
                ],
                first_amendment,
            )

            calls = []

            def factory(checked, _paths):
                audit = _FakeAudit()
                return RuntimeBundle(
                    pipeline=_FakePipeline(checked, audit, calls),
                    audit=audit,
                    index_config_sha256=checked.index_metadata[
                        "index_config_sha256"
                    ],
                )

            receipt = run_openai_baseline(
                verified,
                approve_openai_egress=True,
                runtime_factory=factory,
                sleeper=lambda _seconds: None,
            )
            self.assertTrue(receipt["passed"])
            self.assertEqual(receipt["counts"]["completed"], 40)
            self.assertEqual(len(calls), 39)
            transcripts = [
                json.loads(line)
                for line in (run_dir / "chat-transcripts.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(len(transcripts), 40)
            self.assertEqual(transcripts[0]["assistant"]["final_response"]["status"], "error")

    def test_multiple_recoveries_keep_prior_upper_bound_reservations(self):
        with tempfile.TemporaryDirectory() as directory:
            verified = verify_baseline(self._fixture(Path(directory)))
            first_case_id, counter, _pipeline = self._create_recoverable_interruption(
                verified
            )
            first = recover_interrupted_as_error(
                verified,
                case_id=first_case_id,
                counter_factory=lambda _model, _path: counter,
            )
            first_reserved = first["provider_budget"]["reserved_usd"]
            second_case_id = "dev-followup-005"
            calls = []

            def factory(checked, paths):
                audit = _FakeAudit()
                return RuntimeBundle(
                    pipeline=_InterruptAtCasePipeline(
                        checked,
                        paths,
                        audit,
                        counter,
                        second_case_id,
                        calls,
                    ),
                    audit=audit,
                    index_config_sha256=checked.index_metadata[
                        "index_config_sha256"
                    ],
                )

            with self.assertRaisesRegex(
                ValueError,
                "core40_provider_call_requires_budget_audit",
            ):
                run_openai_baseline(
                    verified,
                    approve_openai_egress=True,
                    runtime_factory=factory,
                    sleeper=lambda _seconds: None,
                )
            second = recover_interrupted_as_error(
                verified,
                case_id=second_case_id,
                counter_factory=lambda _model, _path: counter,
            )
            self.assertTrue(second["passed"])
            self.assertEqual(second["provider_calls_performed"], 0)
            self.assertGreater(
                second["provider_budget"]["reserved_usd"],
                first_reserved,
            )
            self.assertLessEqual(
                second["provider_budget"]["committed_usd"]
                + second["provider_budget"]["reserved_usd"],
                second["provider_budget"]["limit_usd"],
            )
            public_receipt = json.loads(
                (
                    verified.repo_root / verified.config["outputs"]["receipt"]
                ).read_text(encoding="utf-8")
            )
            amendment = public_receipt["runtime_contract_amendment"]
            self.assertEqual(
                set(amendment),
                {
                    "recovery_code_amendment_id",
                    "source_runtime_contract_sha256",
                    "target_runtime_contract_sha256",
                    "failed_case_count",
                    "failed_cases_retried",
                    "provider_attempts_preserved",
                    "provider_retries",
                    "recovery_audit_count",
                    "recovery_audit_sha256",
                    "reserved_uncertain_usd",
                },
            )
            self.assertEqual(amendment["failed_case_count"], 2)
            self.assertEqual(amendment["recovery_audit_count"], 2)
            self.assertFalse(amendment["failed_cases_retried"])
            self.assertTrue(amendment["provider_attempts_preserved"])
            self.assertEqual(amendment["provider_retries"], 0)
            self.assertEqual(
                amendment["reserved_uncertain_usd"],
                second["provider_budget"]["reserved_usd"],
            )
            amendment_text = canonical_json(amendment)
            for forbidden in (
                "dev-single",
                "dev-followup",
                "case_id",
                "question",
                "answer",
                "provider_request",
                "provider_response",
                "source_text",
            ):
                self.assertNotIn(forbidden, amendment_text)
            run_dir = (
                verified.repo_root
                / "evaluation/private/core40/runs/provisional-v1"
            )
            ledger_path = run_dir / "budget-ledger.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(len(ledger["reservations"]), 2)
            reservation_ids = {
                json.loads(path.read_text(encoding="utf-8"))["payload"][
                    "recovery"
                ]["budget"]["reservation_id"]
                for path in (run_dir / "case-checkpoints").glob("*.json")
                if "recovery"
                in json.loads(path.read_text(encoding="utf-8"))["payload"]
            }
            self.assertEqual(reservation_ids, set(ledger["reservations"]))

            idempotent = recover_interrupted_as_error(
                verified,
                case_id=second_case_id,
                counter_factory=lambda _model, _path: counter,
            )
            self.assertEqual(
                idempotent["provider_budget"]["reserved_usd"],
                second["provider_budget"]["reserved_usd"],
            )

            budget = BudgetLedger(ledger_path, limit_usd=2)
            budget.reserve("0.000000001", "unproven-transient-operation")
            with self.assertRaisesRegex(
                ValueError,
                "core40_recovery_budget_outstanding_reservation",
            ):
                recover_interrupted_as_error(
                    verified,
                    case_id=second_case_id,
                    counter_factory=lambda _model, _path: counter,
                )

    def test_recovery_fails_closed_on_cache_miss_or_prompt_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            verified = verify_baseline(self._fixture(Path(directory)))
            case_id, counter, _pipeline = self._create_recoverable_interruption(
                verified
            )
            run_dir = (
                verified.repo_root
                / "evaluation/private/core40/runs/provisional-v1"
            )
            for cache_file in (run_dir / "query-cache").rglob("*.npy"):
                cache_file.unlink()
            with self.assertRaisesRegex(
                ValueError,
                "core40_recovery_query_cache_missing",
            ):
                recover_interrupted_as_error(
                    verified,
                    case_id=case_id,
                    counter_factory=lambda _model, _path: counter,
                )
            ledger = json.loads(
                (run_dir / "budget-ledger.json").read_text(encoding="utf-8")
            )
            self.assertEqual(ledger["reservations"], {})
            checkpoint = json.loads(
                next((run_dir / "case-checkpoints").glob("*.json")).read_text(
                    encoding="utf-8"
                )
            )["payload"]
            self.assertEqual(checkpoint["state"], "interrupted")

        with tempfile.TemporaryDirectory() as directory:
            verified = verify_baseline(self._fixture(Path(directory)))
            case_id, counter, _pipeline = self._create_recoverable_interruption(
                verified,
                prompt_suffix=" tampered",
            )
            with self.assertRaisesRegex(
                ValueError,
                "core40_recovery_prompt_mismatch",
            ):
                recover_interrupted_as_error(
                    verified,
                    case_id=case_id,
                    counter_factory=lambda _model, _path: counter,
                )

    def test_recovery_rejects_non_connection_error(self):
        with tempfile.TemporaryDirectory() as directory:
            verified = verify_baseline(self._fixture(Path(directory)))
            case_id, counter, _pipeline = self._create_recoverable_interruption(
                verified,
                error_type="RuntimeError",
            )
            with self.assertRaisesRegex(
                ValueError,
                "core40_recovery_generation_error_invalid",
            ):
                recover_interrupted_as_error(
                    verified,
                    case_id=case_id,
                    counter_factory=lambda _model, _path: counter,
                )

    def test_recovery_migrates_only_core_module_identity_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            verified = verify_baseline(self._fixture(Path(directory)))
            case_id, counter, _pipeline = self._create_recoverable_interruption(
                verified
            )
            run_dir = (
                verified.repo_root
                / "evaluation/private/core40/runs/provisional-v1"
            )
            run_state_path = run_dir / "run-state.json"
            previous_identity = json.loads(run_state_path.read_text(encoding="utf-8"))
            previous_identity["runtime_contract_sha256s"][
                "core40_baseline_module"
            ] = "0" * 64
            previous_identity["runtime_contract_sha256"] = sha256_text(
                canonical_json(previous_identity["runtime_contract_sha256s"])
            )
            write_json(run_state_path, previous_identity)
            checkpoint_path = next((run_dir / "case-checkpoints").glob("*.json"))
            envelope = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            envelope["payload"]["identity"] = previous_identity
            envelope["payload_sha256"] = sha256_text(
                canonical_json(envelope["payload"])
            )
            write_json(checkpoint_path, envelope)

            result = recover_interrupted_as_error(
                verified,
                case_id=case_id,
                counter_factory=lambda _model, _path: counter,
            )
            self.assertTrue(result["passed"])
            migrated = json.loads(checkpoint_path.read_text(encoding="utf-8"))[
                "payload"
            ]
            self.assertNotEqual(
                migrated["identity"]["runtime_contract_sha256"],
                previous_identity["runtime_contract_sha256"],
            )
            self.assertEqual(
                migrated["identity_migration"]["from_runtime_contract_sha256"],
                previous_identity["runtime_contract_sha256"],
            )

        with tempfile.TemporaryDirectory() as directory:
            verified = verify_baseline(self._fixture(Path(directory)))
            case_id, counter, _pipeline = self._create_recoverable_interruption(
                verified
            )
            run_dir = (
                verified.repo_root
                / "evaluation/private/core40/runs/provisional-v1"
            )
            run_state_path = run_dir / "run-state.json"
            invalid_identity = json.loads(run_state_path.read_text(encoding="utf-8"))
            invalid_identity["runtime_contract_sha256s"]["prompt_builder_source"] = (
                "0" * 64
            )
            invalid_identity["runtime_contract_sha256"] = sha256_text(
                canonical_json(invalid_identity["runtime_contract_sha256s"])
            )
            write_json(run_state_path, invalid_identity)
            with self.assertRaisesRegex(
                ValueError,
                "core40_recovery_run_state_identity_mismatch",
            ):
                recover_interrupted_as_error(
                    verified,
                    case_id=case_id,
                    counter_factory=lambda _model, _path: counter,
                )


if __name__ == "__main__":
    unittest.main()
