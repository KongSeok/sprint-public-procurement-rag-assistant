from __future__ import annotations

import math
import copy
import unittest
from pathlib import Path

from midprojectrag.local_mini131_baseline import (
    EXPECTED_COUNTS,
    SET_BATCH_SIZE,
    SET_BATCH_SYSTEM,
    SET_FINAL_SYSTEM,
    SourceCase,
    _analytics_case_metrics,
    _analytics_evidence,
    _generation_output_contract,
    _import_core40,
    _set_batch_prompt,
    _set_case_metrics,
    _set_prompt_token_budget,
    _validate_page_candidate_binding,
    _validate_set_candidate_binding,
    _validate_set_final_plan,
    _validate_set_batch_plan,
    _visual_case_metrics,
    validate_candidate,
    verify_suite,
)
from midprojectrag.ingest.common import canonical_json, read_jsonl, sha256_text


class LocalMini131ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[2]
        cls.suite = verify_suite(
            repo_root=cls.repo_root,
            config_path=cls.repo_root
            / "configs/rag/gcp-local-kure-qwen3-8b-awq-mini131-v1.json",
        )

    def test_complete_129_plus_2_ledger_is_frozen(self) -> None:
        self.assertEqual(len(self.suite.cases), 129)
        self.assertEqual(len({case.case_id for case in self.suite.cases}), 129)
        counts: dict[str, int] = {}
        for case in self.suite.cases:
            counts[case.lane] = counts.get(case.lane, 0) + 1
        self.assertEqual(counts, EXPECTED_COUNTS["lanes"])
        self.assertEqual(self.suite.parser_receipt["counts"]["passed"], 2)

    def test_stack_generation_limit_is_bound_below_suite_ceiling(self) -> None:
        self.assertEqual(
            _generation_output_contract(self.suite),
            {
                "suite_output_ceiling_tokens": 1200,
                "stack_max_output_tokens": 1024,
                "within_suite_ceiling": True,
            },
        )

    def test_deterministic_and_semantic_receipts_have_distinct_roles(self) -> None:
        receipt_name = self.suite.public_receipt_path.name
        self.assertEqual(receipt_name, "mac-local-equivalent-receipt.json")
        self.assertNotEqual(
            receipt_name,
            "mac-local-equivalent-semantic-receipt.json",
        )

    def test_execution_projection_never_uses_integrated_candidate_or_gold(self) -> None:
        for case in self.suite.cases:
            if case.request_template is None:
                continue
            self.assertEqual(
                set(case.request_template),
                {"question", "history", "document_scope"},
            )
            self.assertNotIn("gold", case.request_template)
            self.assertNotIn("candidate", case.request_template)
            self.assertNotIn("judgment", case.request_template)

    def test_set_lane_scans_every_catalog_row_in_bounded_batches(self) -> None:
        batches = [
            self.suite.catalog_rows[offset : offset + SET_BATCH_SIZE]
            for offset in range(0, len(self.suite.catalog_rows), SET_BATCH_SIZE)
        ]
        self.assertEqual(len(batches), math.ceil(98 / SET_BATCH_SIZE))
        self.assertEqual(sum(len(batch) for batch in batches), 98)
        self.assertEqual(
            len({row["doc_id"] for batch in batches for row in batch}),
            98,
        )
        prompt = _set_batch_prompt("synthetic question", batches[0])
        self.assertIn("synthetic question", prompt)
        self.assertNotIn("required_doc_ids", prompt)
        self.assertNotIn("expected_count", prompt)

    def test_set_batch_plan_fails_closed_on_out_of_batch_identity(self) -> None:
        allowed = {"doc_" + "1" * 24}
        selected, reasons = _validate_set_batch_plan(
            {
                "matched_doc_ids": ["doc_" + "1" * 24],
                "reasons": [
                    {"doc_id": "doc_" + "1" * 24, "reason": "matched"}
                ],
            },
            allowed,
        )
        self.assertEqual(selected, ["doc_" + "1" * 24])
        self.assertEqual(reasons[selected[0]], "matched")
        with self.assertRaisesRegex(ValueError, "set_batch_plan_invalid"):
            _validate_set_batch_plan(
                {
                    "matched_doc_ids": ["doc_" + "2" * 24],
                    "reasons": [
                        {"doc_id": "doc_" + "2" * 24, "reason": "leak"}
                    ],
                },
                allowed,
            )

    def test_set_metrics_include_count_accuracy(self) -> None:
        first = "doc_" + "1" * 24
        second = "doc_" + "2" * 24
        metrics = _set_case_metrics(
            required={first, second},
            selected={first},
            expected_count=2,
        )
        self.assertEqual(metrics["precision"], 1.0)
        self.assertEqual(metrics["recall"], 0.5)
        self.assertFalse(metrics["exact_match"])
        self.assertFalse(metrics["count_match"])
        self.assertTrue(
            _set_case_metrics(
                required={first, second},
                selected={first},
                expected_count=1,
            )["count_match"]
        )
        with self.assertRaisesRegex(ValueError, "set_expected_count_invalid"):
            _set_case_metrics(
                required={first},
                selected={first},
                expected_count=True,
            )

    def test_analytics_prompt_projection_excludes_gold_and_comparisons(self) -> None:
        case = next(case for case in self.suite.cases if case.lane == "corpus_analytics")
        evidence = _analytics_evidence(self.suite, case)
        self.assertEqual(
            set(evidence),
            {"evidence_id", "source", "operation", "computed", "calculation_policy"},
        )
        serialized = str(evidence)
        self.assertNotIn("gold_expected", serialized)
        self.assertNotIn("comparisons", serialized)
        self.assertNotIn("passed", serialized)

    def test_analytics_metrics_preserve_exact_and_tolerance_outcomes(self) -> None:
        metrics = _analytics_case_metrics(
            {
                "passed": False,
                "comparisons": [
                    {"match": True, "reason": "exact", "tolerance": None},
                    {
                        "match": False,
                        "reason": "numeric_tolerance",
                        "tolerance": 0.01,
                    },
                ],
            }
        )
        self.assertFalse(metrics["case_passed"])
        self.assertEqual(metrics["comparison_count"], 2)
        self.assertEqual(metrics["comparison_match_rate"], 0.5)
        self.assertEqual(metrics["exact_comparison_match_rate"], 1.0)
        self.assertEqual(metrics["tolerance_comparison_match_rate"], 0.0)
        with self.assertRaisesRegex(ValueError, "analytics_metric_contract_invalid"):
            _analytics_case_metrics(
                {
                    "passed": True,
                    "comparisons": [
                        {"match": True, "reason": "exact", "tolerance": 0}
                    ],
                }
            )

    def test_visual_metrics_use_frozen_chunk_bindings_at_all_granularities(
        self,
    ) -> None:
        doc_id = "doc_" + "1" * 24
        chunk_id = "chunk_" + "2" * 24
        block_id = "block-1"
        object_id = "object-1"
        source_case = SourceCase(
            case_id="visual-synthetic",
            lane="visual",
            source={
                "retrieval_targets": {
                    "documents": [{"doc_id": doc_id}],
                    "pages": [{"doc_id": doc_id, "page": 2}],
                    "chunks": [{"doc_id": doc_id, "block_id": block_id}],
                    "objects": [{"doc_id": doc_id, "object_id": object_id}],
                }
            },
            source_sha256="0" * 64,
            request_template=None,
        )
        source_block_ids = [block_id, object_id]
        candidate = {
            "retrieval": [
                {
                    "chunk_id": chunk_id,
                    "doc_id": doc_id,
                    "source_block_ids": source_block_ids,
                }
            ]
        }
        chunk_by_id = {
            chunk_id: {
                "chunk_id": chunk_id,
                "doc_id": doc_id,
                "source_block_ids": source_block_ids,
                "page_start": 2,
                "page_end": 2,
            }
        }
        metrics = _visual_case_metrics(source_case, candidate, chunk_by_id)
        for granularity in ("document", "page", "chunk_or_block", "object"):
            with self.subTest(granularity=granularity):
                self.assertEqual(metrics[granularity]["recall_at_1"], 1.0)
                self.assertEqual(metrics[granularity]["recall_at_5"], 1.0)
                self.assertEqual(metrics[granularity]["recall_at_10"], 1.0)
                self.assertEqual(metrics[granularity]["mrr_at_10"], 1.0)

        changed = copy.deepcopy(candidate)
        changed["retrieval"][0]["source_block_ids"] = ["tampered"]
        with self.assertRaisesRegex(
            ValueError, "visual_retrieval_chunk_binding_invalid"
        ):
            _visual_case_metrics(source_case, changed, chunk_by_id)

    def test_set_preflight_measures_98_document_contract_max_final_prompt(
        self,
    ) -> None:
        class RecordingCounter:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str]] = []

            def count_chat(self, *, system: str, prompt: str) -> int:
                self.calls.append((system, prompt))
                return 100 if system == SET_BATCH_SYSTEM else 9000

        counter = RecordingCounter()
        budget = _set_prompt_token_budget(self.suite, counter)
        self.assertEqual(budget["set_case_count"], 13)
        self.assertEqual(budget["set_batch_count_per_case"], 7)
        self.assertEqual(budget["set_final_worst_case_document_count"], 98)
        self.assertEqual(budget["set_final_reason_probe_chars"], 400)
        self.assertEqual(budget["set_final_reason_probe_utf8_bytes"], 1200)
        self.assertEqual(
            budget["set_final_reason_contract_utf8_upper_bound_bytes"], 1600
        )
        self.assertTrue(budget["set_logical_context_ok"])
        self.assertFalse(budget["set_final_worst_case_logical_context_ok"])
        self.assertEqual(
            budget["set_final_overflow_policy"],
            "record_candidate_error_before_transport",
        )
        final_prompts = [
            prompt for system, prompt in counter.calls if system == SET_FINAL_SYSTEM
        ]
        self.assertEqual(len(final_prompts), 13)
        self.assertTrue(
            all(prompt.count('"batch_match_reason"') == 98 for prompt in final_prompts)
        )

    def test_resume_validator_rejects_request_adapter_and_system_tampering(self) -> None:
        source = read_jsonl(self.suite.stack.candidate_path)[0]
        provenance = source["index_provenance"]
        run_id = "unit-local-mini131"
        candidate = _import_core40(
            self.suite,
            run_id=run_id,
            index_provenance=provenance,
        )[0]
        for field in ("request", "adapter", "system"):
            with self.subTest(field=field):
                changed = copy.deepcopy(candidate)
                if field == "request":
                    changed["request"]["document_scope"] = {"mode": "all", "doc_ids": []}
                    changed["request_sha256"] = sha256_text(
                        canonical_json(changed["request"])
                    )
                elif field == "adapter":
                    changed["adapter"] = "deterministic_analytics"
                else:
                    changed["generation"]["system_sha256"] = "0" * 64
                with self.assertRaises(ValueError):
                    validate_candidate(
                        changed,
                        suite=self.suite,
                        run_id=run_id,
                        index_provenance=provenance,
                    )

    def test_set_global_final_plan_is_bounded_to_batch_union(self) -> None:
        doc_id = "doc_" + "1" * 24
        response = _validate_set_final_plan(
            {
                "status": "answered",
                "answer": "global result",
                "selected_doc_ids": [doc_id],
                "citations": [{"doc_id": doc_id, "reason": "global comparison"}],
                "abstention_reason": None,
            },
            {doc_id},
        )
        self.assertEqual(response["selected_doc_ids"], [doc_id])
        with self.assertRaisesRegex(ValueError, "set_final_plan_invalid"):
            _validate_set_final_plan(
                {
                    "status": "answered",
                    "answer": "escape",
                    "selected_doc_ids": ["doc_" + "2" * 24],
                    "citations": [
                        {"doc_id": "doc_" + "2" * 24, "reason": "escape"}
                    ],
                    "abstention_reason": None,
                },
                {doc_id},
            )

    def test_set_error_transcript_accepts_only_exact_batch_prefix(self) -> None:
        case = next(
            case for case in self.suite.cases if case.lane == "supplemental_set_rerun"
        )
        expected = [
            _set_batch_prompt(
                str(case.source["question"]),
                self.suite.catalog_rows[offset : offset + SET_BATCH_SIZE],
            )
            for offset in range(0, len(self.suite.catalog_rows), SET_BATCH_SIZE)
        ]
        error_response = {
            "status": "error",
            "answer": "",
            "citations": [],
            "selected_doc_ids": [],
            "abstention_reason": None,
            "error_code": "ollama_generation_truncated",
        }
        _validate_set_candidate_binding(
            suite=self.suite,
            question=str(case.source["question"]),
            expected_batch_prompts=expected,
            prompts=expected[:3],
            plans=[{"matched_doc_ids": [], "reasons": []}] * 2,
            response=error_response,
        )
        changed = list(expected[:3])
        changed[-1] += "tampered"
        with self.assertRaisesRegex(ValueError, "set_prompt_mismatch"):
            _validate_set_candidate_binding(
                suite=self.suite,
                question=str(case.source["question"]),
                expected_batch_prompts=expected,
                prompts=changed,
                plans=[{"matched_doc_ids": [], "reasons": []}] * 2,
                response=error_response,
            )

    def test_page_plan_is_bound_to_answer_and_citations(self) -> None:
        doc_id = "doc_" + "1" * 24
        chunk_id = "chunk_" + "2" * 24
        plan = {
            "status": "answered",
            "answer": "bound answer",
            "citation_chunk_ids": [chunk_id],
            "abstention_reason": None,
        }
        response = {
            "status": "answered",
            "answer": "bound answer",
            "citations": [{"doc_id": doc_id, "chunk_id": chunk_id}],
            "selected_doc_ids": [doc_id],
            "abstention_reason": None,
            "error_code": None,
        }
        _validate_page_candidate_binding(
            prompts=[f'<SOURCE chunk_id="{chunk_id}">evidence</SOURCE>'],
            plans=[plan],
            response=response,
        )
        changed = copy.deepcopy(response)
        changed["answer"] = "tampered"
        with self.assertRaisesRegex(ValueError, "page_plan_response_mismatch"):
            _validate_page_candidate_binding(
                prompts=[f'<SOURCE chunk_id="{chunk_id}">evidence</SOURCE>'],
                plans=[plan],
                response=changed,
            )


if __name__ == "__main__":
    unittest.main()
