from __future__ import annotations

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from midprojectrag.ingest.common import (
    canonical_json,
    sha256_file,
    sha256_text,
    write_json,
    write_jsonl,
)
from midprojectrag.indexing.budget import BudgetLedger
from midprojectrag.indexing.embeddings import EmbeddingCache
from midprojectrag.indexing.exact_index import ExactDenseIndex
from midprojectrag.stacks.api import (
    OpenAIEmbeddingProvider,
    api_config_sha256,
    build_api_index_config,
)
from midprojectrag.visual_eda_mini_baseline import (
    BASELINE_ID,
    EXECUTION_CONTRACT,
    EXPECTED_COUNTS,
    FROZEN_RUNTIME,
    RuntimeBundle,
    _AuditedOpenAIClient,
    _MiniAnswerGenerator,
    _ProviderAudit,
    _runtime_contract_sha256s,
    preflight_report,
    run_openai_baseline,
    verify_baseline,
)


class _Counter:
    def count(self, text: str) -> int:
        return max(1, len(text.split()))


class _Dumpable(SimpleNamespace):
    def model_dump(self, mode: str = "json"):
        del mode

        def convert(value):
            if isinstance(value, SimpleNamespace):
                return {key: convert(item) for key, item in vars(value).items()}
            if isinstance(value, list):
                return [convert(item) for item in value]
            return value

        return convert(self)


class _EmbeddingEndpoint:
    def __init__(self, calls):
        self.calls = calls

    def create(self, **kwargs):
        self.calls.append(("embedding", kwargs))
        vector = [0.0] * 1536
        vector[0] = 1.0
        return _Dumpable(
            data=[_Dumpable(index=0, embedding=vector)],
            usage=_Dumpable(total_tokens=3),
            model="text-embedding-3-small",
        )


class _GenerationEndpoint:
    def __init__(self, calls):
        self.calls = calls

    def create(self, **kwargs):
        self.calls.append(("generation", kwargs))
        prompt = kwargs["input"]
        if "calculation:analytics-" in prompt:
            start = prompt.index("calculation:analytics-")
            evidence_id = prompt[start:].split('"', 1)[0]
        else:
            marker = 'evidence_id="'
            start = prompt.index(marker) + len(marker)
            evidence_id = prompt[start:].split('"', 1)[0]
        plan = {
            "status": "answered",
            "answer": f"fixture answer from {evidence_id}",
            "cited_evidence_ids": [evidence_id],
            "abstention_reason": None,
        }
        output_text = json.dumps({"result": plan})
        return _Dumpable(
            status="completed",
            output_text=output_text,
            usage=_Dumpable(input_tokens=20, output_tokens=8),
            output=[{"type": "message", "content": output_text}],
        )


class _RawClient:
    def __init__(self, calls):
        self.embeddings = _EmbeddingEndpoint(calls)
        self.responses = _GenerationEndpoint(calls)


def _chunk(number: int) -> dict[str, object]:
    text = f"fixture page evidence {number}"
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
        "section_path": ["fixture"],
        "page_start": number,
        "page_end": number,
        "part_index": 0,
        "part_count": 1,
        "retrieval_role": "primary",
        "chunker_id": "page-v1",
        "config_sha256": config_sha256,
        "content_sha256": content_sha256,
    }


class VisualEdaMiniBaselineTests(unittest.TestCase):
    def _fixture(self, root: Path) -> Path:
        (root / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
        chunks = [_chunk(1), _chunk(2)]
        manifest_path = root / "resources/data_refined/private/manifest.extracted.jsonl"
        write_jsonl(
            manifest_path,
            [
                {"doc_id": chunk["doc_id"], "index_eligible": True}
                for chunk in chunks
            ],
        )
        manifest_sha256 = sha256_file(manifest_path)
        chunks_path = root / "resources/data_refined/private/chunks.page-v1.jsonl"
        write_jsonl(chunks_path, chunks)

        visual_cases = []
        for number in range(1, 11):
            chunk = chunks[(number - 1) % 2]
            evidence_type = "table" if number <= 6 else "figure"
            document_format = "hwp" if number <= 5 else "pdf"
            visual_cases.append(
                {
                    "case_id": f"visual-{number:03d}",
                    "question": f"fixture visual question {number}",
                    "document_format": document_format,
                    "evidence_type": evidence_type,
                    "document_scope": {
                        "mode": "explicit",
                        "doc_ids": [chunk["doc_id"]],
                    },
                    "retrieval_targets": {
                        "documents": [
                            {"doc_id": chunk["doc_id"], "relevance": 3}
                        ],
                        "pages": [
                            {
                                "doc_id": chunk["doc_id"],
                                "page": chunk["page_start"],
                                "relevance": 3,
                            }
                        ],
                        "chunks": [
                            {
                                "doc_id": chunk["doc_id"],
                                "block_id": chunk["source_block_ids"][0],
                                "relevance": 3,
                            }
                        ],
                        "objects": [
                            {
                                "doc_id": chunk["doc_id"],
                                "object_id": chunk["source_block_ids"][0],
                                "page": chunk["page_start"],
                                "relevance": 3,
                            }
                        ],
                    },
                    "gold": {
                        "reference_answer": f"SECRET VISUAL GOLD {number}"
                    },
                }
            )
        visual_cases_path = root / "golden-set-final/document-structure-visual-qa.jsonl"
        write_jsonl(visual_cases_path, visual_cases)

        analytics_cases = []
        calculation_rows = []
        for number in range(1, 11):
            case_id = f"analytics-{number:03d}"
            question = f"fixture analytics question {number}"
            operation = f"operation_{number}"
            analytics_cases.append(
                {
                    "case_id": case_id,
                    "question": question,
                    "document_scope": {
                        "mode": "target_sets",
                        "target_set_ids": ["corpus.all"],
                    },
                    "calculation_contract": {
                        "operation": operation,
                        "grain": "one row",
                        "formula": "fixture formula",
                        "amount_missing_policy": "exclude missing",
                    },
                    "gold": {
                        "reference_answer": f"SECRET ANALYTICS GOLD {number}",
                        "expected": {"value": number},
                    },
                }
            )
            calculation_rows.append(
                {
                    "case_id": case_id,
                    "operation": operation,
                    "question_sha256": sha256_text(question),
                    "computed": {"value": number},
                    "gold_expected": {"value": number},
                    "passed": True,
                }
            )
        analytics_cases_path = root / "golden-set-final/corpus-analytics-qa.jsonl"
        calculations_path = (
            root
            / "evaluation/private/corpus-analytics/corpus-analytics-deterministic-v1/case-results.jsonl"
        )
        write_jsonl(analytics_cases_path, analytics_cases)
        write_jsonl(calculations_path, calculation_rows)

        index_dir = (
            root
            / "resources/data_refined/private/indexes/api/personal_experimental/text-embedding-3-small-1536"
        )
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
        write_json(
            config_path,
            {
                "schema_version": "1.0",
                "baseline_id": BASELINE_ID,
                "evaluation_tier": "provisional",
                "expected_counts": EXPECTED_COUNTS,
                "artifacts": {
                    "visual_cases": "golden-set-final/document-structure-visual-qa.jsonl",
                    "visual_cases_sha256": sha256_file(visual_cases_path),
                    "analytics_cases": "golden-set-final/corpus-analytics-qa.jsonl",
                    "analytics_cases_sha256": sha256_file(analytics_cases_path),
                    "analytics_calculations": "evaluation/private/corpus-analytics/corpus-analytics-deterministic-v1/case-results.jsonl",
                    "analytics_calculations_sha256": sha256_file(calculations_path),
                    "manifest": "resources/data_refined/private/manifest.extracted.jsonl",
                    "manifest_sha256": manifest_sha256,
                    "page_chunks": "resources/data_refined/private/chunks.page-v1.jsonl",
                    "page_chunks_sha256": sha256_file(chunks_path),
                    "page_index_dir": "resources/data_refined/private/indexes/api/personal_experimental/text-embedding-3-small-1536",
                    "page_index_metadata_sha256": sha256_file(index_dir / "metadata.json"),
                    "page_index_config_sha256": sha256_file(index_dir / "index-config.json"),
                    "tiktoken_cache_dir": "resources/data_refined/private/tiktoken-cache",
                },
                "runtime": FROZEN_RUNTIME,
                "execution_contract": EXECUTION_CONTRACT,
                "outputs": {
                    "run_records": "evaluation/private/visual-eda-mini/runs/prospective-v1/run-records.jsonl",
                    "chat_transcripts": "evaluation/private/visual-eda-mini/runs/prospective-v1/chat-transcripts.jsonl",
                    "private_summary": "evaluation/private/visual-eda-mini/runs/prospective-v1/summary.json",
                    "preflight_receipt": f"evaluation/baselines/{BASELINE_ID}/preflight-receipt.json",
                    "receipt": f"evaluation/baselines/{BASELINE_ID}/receipt.json",
                },
            },
        )
        return config_path

    def _runtime_factory(self, calls):
        def factory(verified, paths):
            audit = _ProviderAudit()
            client = _AuditedOpenAIClient(_RawClient(calls), audit)
            runtime = verified.config["runtime"]
            return RuntimeBundle(
                embedding_provider=OpenAIEmbeddingProvider(
                    client=client,
                    model=runtime["embedding_model"],
                    dimensions=runtime["embedding_dimensions"],
                    api_profile=runtime["api_profile"],
                ),
                embedding_counter=_Counter(),
                generation_counter=_Counter(),
                generator=_MiniAnswerGenerator(
                    client=client,
                    model=runtime["generator_model"],
                    max_output_tokens=runtime["max_output_tokens"],
                    reasoning_effort=runtime["reasoning_effort"],
                ),
                budget=BudgetLedger(
                    paths["budget_ledger"], limit_usd=runtime["budget_limit_usd"]
                ),
                query_cache=EmbeddingCache(paths["query_cache"]),
                audit=audit,
                index_config_sha256=verified.index_metadata["index_config_sha256"],
            )

        return factory

    def test_live_execution_requires_explicit_egress_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            verified = verify_baseline(self._fixture(Path(directory)))
            factory_calls = []

            def factory(*_args):
                factory_calls.append(True)
                raise AssertionError("provider runtime must not be built")

            with self.assertRaisesRegex(
                ValueError, "visual_eda_openai_egress_not_approved"
            ):
                run_openai_baseline(
                    verified,
                    approve_openai_egress=False,
                    runtime_factory=factory,
                )
            self.assertEqual(factory_calls, [])

    def test_provider_attempt_contract_is_frozen_to_thirty_single_attempt_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            verified = verify_baseline(self._fixture(Path(directory)))
            self.assertEqual(verified.config["runtime"]["openai_max_retries"], 0)
            self.assertEqual(
                verified.config["execution_contract"]["provider_attempt_policy"],
                {
                    "sdk_max_retries": 0,
                    "maximum_attempts_per_case": 1,
                    "maximum_suite_calls": 30,
                },
            )
            estimated = 10 + 20
            self.assertEqual(estimated, 30)

    def test_runtime_contract_covers_code_prompts_schema_and_system_instructions(self):
        with tempfile.TemporaryDirectory() as directory:
            verified = verify_baseline(self._fixture(Path(directory)))
            contract = _runtime_contract_sha256s()
            self.assertEqual(verified.runtime_contract_sha256s, contract)
            self.assertNotIn(
                "midprojectrag.indexing.chunking",
                contract["module_bytes"],
            )
            self.assertEqual(
                set(contract), {"module_bytes", "prompt_contracts"}
            )
            self.assertEqual(
                set(contract["prompt_contracts"]),
                {
                    "analytics_prompt_instruction",
                    "answer_schema",
                    "prompt_format_contract",
                    "system_instructions",
                    "visual_prompt_instruction",
                },
            )
            self.assertIn(
                "midprojectrag.visual_eda_mini_baseline",
                contract["module_bytes"],
            )
            self.assertIn(
                "midprojectrag.answering.generation", contract["module_bytes"]
            )
            self.assertTrue(
                all(
                    len(value) == 64
                    and set(value) <= set("0123456789abcdef")
                    for group in contract.values()
                    for value in group.values()
                )
            )
            with patch(
                "midprojectrag.visual_eda_mini_baseline._estimated_cost",
                return_value={"fixture": True},
            ):
                report = preflight_report(verified)
            self.assertEqual(report["runtime_contract_sha256s"], contract)
            self.assertEqual(
                report["runtime_contract_sha256"],
                sha256_text(canonical_json(contract)),
            )

    def test_resume_rejects_runtime_prompt_contract_drift_before_provider_init(self):
        with tempfile.TemporaryDirectory() as directory:
            verified = verify_baseline(self._fixture(Path(directory)))
            with self.assertRaisesRegex(AssertionError, "stop after run state"):
                run_openai_baseline(
                    verified,
                    approve_openai_egress=True,
                    runtime_factory=lambda *_args: (_ for _ in ()).throw(
                        AssertionError("stop after run state")
                    ),
                )

            provider_factory_calls = []

            def unexpected_factory(*_args):
                provider_factory_calls.append(True)
                raise AssertionError("provider runtime must not be built")

            with patch(
                "midprojectrag.visual_eda_mini_baseline.SYSTEM_INSTRUCTIONS",
                "drifted system instructions",
            ):
                with self.assertRaisesRegex(
                    ValueError, "visual_eda_runtime_contract_drift"
                ):
                    run_openai_baseline(
                        verified,
                        approve_openai_egress=True,
                        runtime_factory=unexpected_factory,
                    )

            runner_path = Path(
                _runtime_contract_sha256s.__code__.co_filename
            ).resolve()

            def drifted_module_sha256(path):
                if Path(path).resolve() == runner_path:
                    return "0" * 64
                return sha256_file(path)

            with patch(
                "midprojectrag.visual_eda_mini_baseline.sha256_file",
                side_effect=drifted_module_sha256,
            ):
                with self.assertRaisesRegex(
                    ValueError, "visual_eda_runtime_contract_drift"
                ):
                    run_openai_baseline(
                        verified,
                        approve_openai_egress=True,
                        runtime_factory=unexpected_factory,
                    )
            self.assertEqual(provider_factory_calls, [])

    def test_records_exact_answers_companions_and_resumes_without_gold_leakage(self):
        with tempfile.TemporaryDirectory() as directory:
            verified = verify_baseline(self._fixture(Path(directory)))
            calls = []
            receipt = run_openai_baseline(
                verified,
                approve_openai_egress=True,
                runtime_factory=self._runtime_factory(calls),
                sleeper=lambda _seconds: None,
            )
            self.assertTrue(receipt["passed"])
            self.assertEqual(receipt["counts"]["completed"], 20)
            self.assertEqual(Counter(name for name, _args in calls), Counter({"embedding": 10, "generation": 20}))

            transcript_path = (
                verified.repo_root / verified.config["outputs"]["chat_transcripts"]
            )
            transcripts = [
                json.loads(line)
                for line in transcript_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(transcripts), 20)
            self.assertTrue(all(row["assistant"]["final_answer"] for row in transcripts))
            visual = next(row for row in transcripts if row["suite"] == "visual")
            analytics = next(row for row in transcripts if row["suite"] == "analytics")
            self.assertTrue(visual["selected_context"][0]["source_text"])
            self.assertIsNotNone(visual["visual_companion"]["target_page_first_rank"])
            self.assertIsNotNone(
                visual["visual_companion"]["target_object_bridge_first_rank"]
            )
            self.assertEqual(analytics["analytics_companion"]["numeric_evidence"], {"value": 1})
            self.assertIsNone(analytics["visual_companion"])
            provider_prompts = "\n".join(
                row["provider_exchange"]["generation"]["request_arguments"]["input"]
                for row in transcripts
            )
            self.assertNotIn("SECRET VISUAL GOLD", provider_prompts)
            self.assertNotIn("SECRET ANALYTICS GOLD", provider_prompts)
            self.assertNotIn("gold_expected", provider_prompts)
            self.assertNotIn("reference_answer", provider_prompts)
            self.assertEqual(transcript_path.stat().st_mode & 0o777, 0o600)
            public_text = json.dumps(receipt, ensure_ascii=False)
            self.assertNotIn("fixture answer", public_text)
            self.assertNotIn("fixture question", public_text)
            self.assertEqual(receipt["provider_budget"]["limit_usd"], 1.0)

            run_state = json.loads(
                (transcript_path.parent / "run-state.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                run_state["runtime_contract_sha256s"],
                verified.runtime_contract_sha256s,
            )
            checkpoint = next(
                (transcript_path.parent / "case-checkpoints").glob("*.json")
            )
            checkpoint_payload = json.loads(
                checkpoint.read_text(encoding="utf-8")
            )["payload"]
            self.assertEqual(
                checkpoint_payload["identity"]["runtime_contract_sha256s"],
                verified.runtime_contract_sha256s,
            )

            resumed = run_openai_baseline(
                verified,
                approve_openai_egress=True,
                runtime_factory=lambda *_args: (_ for _ in ()).throw(
                    AssertionError("completed resume must not build provider runtime")
                ),
            )
            self.assertTrue(resumed["passed"])
            self.assertEqual(Counter(name for name, _args in calls), Counter({"embedding": 10, "generation": 20}))


if __name__ == "__main__":
    unittest.main()
