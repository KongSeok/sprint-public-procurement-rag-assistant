from __future__ import annotations

import io
import copy
import json
import stat
import tempfile
import unittest
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path

from midprojectrag.eval_contracts.mini131.scorecard import expected_contract
from midprojectrag.ingest.common import canonical_json, read_jsonl, sha256_file, sha256_text
from midprojectrag.mini131_bundle import (
    BANNED_JUDGE_KEYS,
    BundlePaths,
    _expected_behavior,
    _expected_judge_config,
    _judgment_id,
    _objective_companion,
    _packet,
    _validate_packets,
    _validate_judgment_scores,
    build_judge_packets,
    main,
    merge_judgments,
    preflight,
)
from midprojectrag.mini131_report import validate_records


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(canonical_json(row) + "\n" for row in rows), encoding="utf-8")


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _case(case_id: str, *, lane: str = "answer") -> dict[str, object]:
    row: dict[str, object] = {
        "case_id": case_id,
        "question": f"private question {case_id}",
        "gold": {
            "decision": "answer",
            "reference_answer": f"private gold {case_id}",
        },
    }
    if lane == "answer":
        row.update({"required_doc_ids": ["doc_001"], "evidence_refs": [], "task_type": "qa"})
    elif lane == "set":
        row.update(
            {
                "required_doc_ids": ["doc_001"],
                "required_fact_groups": [],
                "expected_count": 1,
                "set_definition": {"field": "value"},
            }
        )
    elif lane == "core":
        row.update({"task_type": "single_document", "history": [], "document_scope": {"mode": "all"}})
    elif lane == "visual":
        row.update(
            {
                "document_scope": {"mode": "explicit"},
                "document_format": "hwp",
                "evidence_type": "table",
                "retrieval_targets": {"pages": [1]},
                "structure_or_visual_dependency": {"required": True},
                "page_reference_policy": "rendered_page",
            }
        )
    elif lane == "analytics":
        row.update(
            {
                "document_scope": {"mode": "corpus"},
                "calculation_contract": {"operation": "mean"},
            }
        )
    return row


def _transcript(case_id: str, answer: str, *, capture: str = "prospective_runtime_exact", suite: str | None = None) -> dict[str, object]:
    row: dict[str, object] = {
        "case_id": case_id,
        "capture_mode": capture,
        "generation_prompt": "private generation prompt",
        "request": {"question": f"private request {case_id}"},
        "provider_exchange": {
            "embedding": {"request": {"input": "private query"}, "response": {"ok": True}},
            "generation": {"request": {"model": "candidate"}, "response": {"ok": True}},
        },
        "assistant": {"final_answer": answer},
        "retrieval": [{"doc_id": "doc_001", "rank": 1}],
        "selected_context": [{"doc_id": "doc_001", "source_text": "private evidence"}],
    }
    if suite == "visual":
        number = int(case_id.rsplit("-", 1)[1])
        row["visual_companion"] = {
            "retrieval_targets": {
                "pages": [{"doc_id": "doc_001", "page": 1}],
                "chunks": [{"doc_id": "doc_001", "block_id": "block_001"}],
                "objects": [{"doc_id": "doc_001", "object_id": "block_001"}],
            },
            "target_page_first_rank": number if number <= 8 else None,
            "target_chunk_first_rank": number if number <= 7 else None,
            "target_object_bridge_first_rank": number if number <= 5 else None,
        }
        row["analytics_companion"] = None
    elif suite == "analytics":
        row["retrieval"] = []
        row["selected_context"] = []
        row["visual_companion"] = None
        row["analytics_companion"] = {
            "numeric_evidence": {"value": 1, "nested": {"count": 2}},
            "evidence_id": f"calc:{case_id}",
            "source": "executed_deterministic_refined98_calculation",
        }
    return row


def _run(case_id: str, answer: str, *, cost: float = 0.001) -> dict[str, object]:
    return {
        "case_id": case_id,
        "status": "answered",
        "answer": answer,
        "retrieved_doc_ids": ["doc_001"],
        "cited_doc_ids": ["doc_001"],
        "usage": {"cost_usd": cost},
    }


class Mini131Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.paths = BundlePaths(
            legacy_cases=root / "legacy-cases.jsonl",
            legacy_runs=root / "legacy-runs.jsonl",
            legacy_transcripts=root / "legacy-transcripts.jsonl",
            legacy_config=root / "legacy-config.json",
            legacy_receipt=root / "legacy-receipt.json",
            gap_answer_cases=root / "gap-answer-cases.jsonl",
            gap_set_cases=root / "gap-set-cases.jsonl",
            gap_answer_runs=root / "gap-answer-runs.jsonl",
            gap_set_runs=root / "gap-set-runs.jsonl",
            gap_transcripts=root / "gap-transcripts.jsonl",
            gap_config=root / "gap-config.json",
            gap_receipt=root / "gap-receipt.json",
            core_cases=root / "core-cases.jsonl",
            core_runs=root / "core-runs.jsonl",
            core_transcripts=root / "core-transcripts.jsonl",
            core_config=root / "core-config.json",
            core_receipt=root / "core-receipt.json",
            visual_cases=root / "visual-cases.jsonl",
            analytics_cases=root / "analytics-cases.jsonl",
            analytics_calculations=root / "analytics-calculations.jsonl",
            visual_eda_runs=root / "visual-eda-runs.jsonl",
            visual_eda_transcripts=root / "visual-eda-transcripts.jsonl",
            visual_eda_config=root / "visual-eda-config.json",
            visual_eda_receipt=root / "visual-eda-receipt.json",
            parser_config=root / "parser-config.json",
            parser_receipt=root / "parser-receipt.json",
            rubric=root / "rubric.md",
            judge_config=root / "judge-config.json",
            scorecard_contract=root / "scorecard-v1.json",
            judge_packets=root / "private" / "judge-packets.jsonl",
            blind_judge_inputs=root / "private" / "blind-judge-inputs.jsonl",
            case_records=root / "private" / "case-records.jsonl",
            receipt=root / "public" / "receipt.json",
        )
        self.case_ids: list[str] = []
        self._write()

    def _write(self) -> None:
        self.paths.rubric.write_text("synthetic fixed rubric\n", encoding="utf-8")
        _write_json(self.paths.scorecard_contract, expected_contract())
        _write_json(
            self.paths.judge_config,
            _expected_judge_config(sha256_file(self.paths.rubric)),
        )
        _write_json(
            self.paths.legacy_config,
            {"baseline_id": "supplemental-provisional-v1"},
        )
        _write_json(self.paths.gap_config, {"baseline_id": "supplemental-mini-gap30-v1"})
        _write_json(self.paths.core_config, {"baseline_id": "core40-provisional-v1"})
        _write_json(
            self.paths.visual_eda_config,
            {"baseline_id": "visual-eda-mini-prospective-v1"},
        )
        gap_config_sha256 = sha256_file(self.paths.gap_config)
        core_config_sha256 = sha256_file(self.paths.core_config)
        visual_eda_config_sha256 = sha256_file(self.paths.visual_eda_config)
        legacy_ids = [f"legacy-{number:03d}" for number in range(1, 40)]
        gap_answer_ids = [f"gap-answer-{number:03d}" for number in range(1, 18)]
        set_ids = [f"gap-set-{number:03d}" for number in range(1, 14)]
        core_ids = [f"core-{number:03d}" for number in range(1, 41)]
        visual_ids = [f"visual-{number:03d}" for number in range(1, 11)]
        analytics_ids = [f"analytics-{number:03d}" for number in range(1, 11)]
        answer_ids = legacy_ids + gap_answer_ids
        self.case_ids = legacy_ids + gap_answer_ids + set_ids + core_ids + visual_ids + analytics_ids

        answer_cases = [_case(case_id) for case_id in answer_ids]
        _write_jsonl(self.paths.legacy_cases, answer_cases)
        _write_jsonl(self.paths.gap_answer_cases, answer_cases)
        legacy_runs = [_run(case_id, f"candidate {case_id}") for case_id in legacy_ids]
        legacy_runs.extend(
            {
                "case_id": case_id,
                "status": "abstained",
                "answer": "",
                "retrieved_doc_ids": [],
                "cited_doc_ids": [],
                "usage": {"cost_usd": 0.001},
            }
            for case_id in gap_answer_ids
        )
        _write_jsonl(self.paths.legacy_runs, legacy_runs)
        legacy_transcripts = [
            _transcript(
                case_id,
                f"candidate {case_id}" if case_id in legacy_ids else "",
                capture="posthoc_reconstructed",
            )
            for case_id in answer_ids
        ]
        legacy_transcripts.extend(
            _transcript(case_id, "", capture="posthoc_reconstructed") for case_id in set_ids
        )
        _write_jsonl(self.paths.legacy_transcripts, legacy_transcripts)

        _write_jsonl(self.paths.gap_set_cases, [_case(case_id, lane="set") for case_id in set_ids])
        gap_answer_runs = [
            {
                **_run(case_id, f"candidate {case_id}"),
                "baseline_id": "supplemental-mini-gap30-v1",
            }
            for case_id in gap_answer_ids
        ]
        gap_set_runs = [
            {
                "case_id": case_id,
                "status": "answered",
                "answer": f"candidate {case_id}",
                "selected_doc_ids": ["doc_001"],
                "citations": [{"doc_id": "doc_001", "reason": "evidence"}],
                "usage": {"cost_usd": 0.001},
                "baseline_id": "supplemental-mini-gap30-v1",
            }
            for case_id in set_ids
        ]
        gap_set_runs[0]["status"] = "error"
        gap_set_runs[0]["answer"] = ""
        _write_jsonl(self.paths.gap_answer_runs, gap_answer_runs)
        _write_jsonl(self.paths.gap_set_runs, gap_set_runs)
        gap_source_runtime_sha256 = "1" * 64
        gap_target_runtime_sha256 = "2" * 64
        gap_transcripts = [
            {
                **_transcript(case_id, f"candidate {case_id}"),
                "baseline_id": "supplemental-mini-gap30-v1",
                "config_sha256": gap_config_sha256,
            }
            for case_id in gap_answer_ids + set_ids
        ]
        provider_error = {
            "type": "BadRequestError",
            "message": (
                "Error code: 400 - Invalid schema: "
                "'uniqueItems' is not permitted"
            ),
        }
        gap_transcripts[len(gap_answer_ids)].update(
            {
                "capture_mode": (
                    "prospective_runtime_exact_recovered_provider_rejection"
                ),
                "provider_exchange": {
                    "embedding": None,
                    "generation": {
                        "attempt_number": 1,
                        "request_arguments": {"synthetic": True},
                        "response": None,
                        "error": copy.deepcopy(provider_error),
                    },
                },
                "assistant": {
                    "final_answer": "",
                    "final_response": {
                        "status": "error",
                        "answer": "",
                        "selected_doc_ids": [],
                        "citations": [],
                        "abstention_reason": None,
                        "error": {
                            "code": (
                                "gap30_set_schema_unique_items_provider_rejected"
                            ),
                            **copy.deepcopy(provider_error),
                        },
                    },
                },
                "runtime_error": copy.deepcopy(provider_error),
                "runtime_contract_amendment": {
                    "amendment_id": "gap30-set-schema-unique-items-400-v1",
                    "source_runtime_contract_sha256": (
                        gap_source_runtime_sha256
                    ),
                    "target_runtime_contract_sha256": (
                        gap_target_runtime_sha256
                    ),
                    "provider_attempt_policy": (
                        "failed set case is preserved as error and never retried"
                    ),
                },
            }
        )
        _write_jsonl(
            self.paths.gap_transcripts,
            gap_transcripts,
        )

        _write_jsonl(self.paths.core_cases, [_case(case_id, lane="core") for case_id in core_ids])
        core_runs = [
            {
                "case_id": case_id,
                "response": {"status": "answered", "answer": f"candidate {case_id}", "citations": [{"doc_id": "doc_001"}]},
                "retrieval": [{"doc_id": "doc_001", "rank": 1}],
                "usage": {"cost_usd": 0.001},
                "config_sha256": core_config_sha256,
            }
            for case_id in core_ids
        ]
        _write_jsonl(self.paths.core_runs, core_runs)
        core_transcripts = [
            {
                **_transcript(case_id, f"candidate {case_id}"),
                "baseline_id": "core40-provisional-v1",
                "config_sha256": core_config_sha256,
            }
            for case_id in core_ids
        ]
        for transcript in core_transcripts[:2]:
            transcript["capture_mode"] = "prospective_runtime_with_offline_recovery"
            transcript["recovery"] = {"mode": "explicit-interrupted-error-v1"}
        _write_jsonl(self.paths.core_transcripts, core_transcripts)

        _write_jsonl(self.paths.visual_cases, [_case(case_id, lane="visual") for case_id in visual_ids])
        _write_jsonl(self.paths.analytics_cases, [_case(case_id, lane="analytics") for case_id in analytics_ids])
        _write_jsonl(
            self.paths.analytics_calculations,
            [
                {
                    "case_id": case_id,
                    "passed": True,
                    "computed": {"value": 1, "nested": {"count": 2}},
                    "comparisons": [{"match": True}, {"match": True}],
                }
                for case_id in analytics_ids
            ],
        )
        visual_eda_runs = [
            {
                "case_id": case_id,
                "status": "answered",
                "answer": f"candidate {case_id}",
                "cited_evidence_ids": ["doc_001"],
                "retrieval": [{"doc_id": "doc_001", "rank": 1}],
                "usage": {"cost_usd": 0.001},
                "baseline_id": "visual-eda-mini-prospective-v1",
                "config_sha256": visual_eda_config_sha256,
            }
            for case_id in visual_ids + analytics_ids
        ]
        _write_jsonl(self.paths.visual_eda_runs, visual_eda_runs)
        _write_jsonl(
            self.paths.visual_eda_transcripts,
            [
                {
                    **_transcript(case_id, f"candidate {case_id}", suite="visual"),
                    "baseline_id": "visual-eda-mini-prospective-v1",
                    "config_sha256": visual_eda_config_sha256,
                }
                for case_id in visual_ids
            ]
            + [
                {
                    **_transcript(case_id, f"candidate {case_id}", suite="analytics"),
                    "baseline_id": "visual-eda-mini-prospective-v1",
                    "config_sha256": visual_eda_config_sha256,
                }
                for case_id in analytics_ids
            ],
        )

        parser_cases = []
        parser_results = []
        parser_check_fields = (
            "manifest_row_present",
            "input_sha256_match",
            "status_match",
            "extractor_match",
            "index_eligible_match",
            "block_count_match",
            "primary_text_chars_match",
            "page_count_match",
            "error_absent",
            "block_file_present",
            "block_file_count_match",
        )
        for number in (21, 22):
            case_id = f"C{number}"
            doc_id = f"doc_parser_{number}"
            parser_cases.append(
                {
                    "case_id": case_id,
                    "doc_id": doc_id,
                    "input_sha256": str(number % 10) * 64,
                    "expected_extractor": "rhwp",
                    "expected_status": "ok",
                    "expected_index_eligible": True,
                    "expected_block_count": number,
                    "expected_primary_text_chars": number * 100,
                    "expected_page_count": number - 10,
                }
            )
            parser_results.append(
                {
                    "case_id": case_id,
                    "doc_id": doc_id,
                    "passed": True,
                    "checks": {field: True for field in parser_check_fields},
                    "observed": {
                        "status": "ok",
                        "extractor": "rhwp",
                        "index_eligible": True,
                        "block_count": number,
                        "primary_text_chars": number * 100,
                        "page_count": number - 10,
                        "block_file_sha256": "a" * 64,
                    },
                }
            )
        parser_contract = {
            "current_invariant": "canonical_rhwp_extraction_and_indexability",
            "legacy_fallback_activation_scored": False,
            "semantic_judge_required": False,
        }
        manifest_sha256 = "b" * 64
        _write_json(
            self.paths.parser_config,
            {
                "schema_version": "1.0",
                "baseline_id": "parser-regression-rhwp-v1",
                "contract": parser_contract,
                "artifacts": {
                    "manifest": "resources/data_refined/private/manifest.extracted.jsonl",
                    "manifest_sha256": manifest_sha256,
                },
                "cases": parser_cases,
                "outputs": {
                    "receipt": "evaluation/baselines/parser-regression-rhwp-v1/receipt.json"
                },
            },
        )
        _write_json(
            self.paths.parser_receipt,
            {
                "schema_version": "1.0",
                "baseline_id": "parser-regression-rhwp-v1",
                "passed": True,
                "scoring_contract": {
                    "lane": "deterministic_etl_regression",
                    **parser_contract,
                },
                "artifacts": {
                    "config_sha256": sha256_file(self.paths.parser_config),
                    "manifest_sha256": manifest_sha256,
                },
                "counts": {"total": 2, "passed": 2, "failed": 0},
                "cases": parser_results,
            },
        )
        self.refresh_source_receipts()

    def refresh_source_receipts(self) -> None:
        _write_json(
            self.paths.legacy_receipt,
            {
                "schema_version": "1.0",
                "baseline_id": "supplemental-provisional-v1",
                "config_sha256": sha256_file(self.paths.legacy_config),
                "passed": True,
                "counts": {
                    "answer_cases": 56,
                    "set_cases": 13,
                    "total_cases": 69,
                    "chat_transcripts": 69,
                    "chat_transcripts_exact_persisted_answers": 39,
                },
                "artifact_sha256s": {
                    "answer_cases": sha256_file(self.paths.legacy_cases),
                    "answer_runs": sha256_file(self.paths.legacy_runs),
                    "set_cases": sha256_file(self.paths.gap_set_cases),
                    "chat_transcripts": sha256_file(self.paths.legacy_transcripts),
                },
                "answer_score": {"passed": True, "suite_complete": True},
                "set_score": {"passed": True, "suite_complete": True},
            },
        )
        gap_statuses = Counter(
            row["status"]
            for row in [
                *read_jsonl(self.paths.gap_answer_runs),
                *read_jsonl(self.paths.gap_set_runs),
            ]
        )
        _write_json(
            self.paths.gap_receipt,
            {
                "schema_version": "1.0",
                "baseline_id": "supplemental-mini-gap30-v1",
                "config_sha256": sha256_file(self.paths.gap_config),
                "passed": True,
                "suite_complete": True,
                "counts": {
                    "answer": 17,
                    "set": 13,
                    "transcripts": 30,
                    "completed": 30,
                    "remaining": 0,
                    "total": 30,
                },
                "status_counts": {
                    status: gap_statuses.get(status, 0)
                    for status in ("answered", "abstained", "error")
                },
                "provider_budget": {"breached": False},
                "artifact_sha256s": {
                    "answer_runs": sha256_file(self.paths.gap_answer_runs),
                    "set_runs": sha256_file(self.paths.gap_set_runs),
                    "chat_transcripts": sha256_file(self.paths.gap_transcripts),
                },
                "runtime_contract_amendment": {
                    "amendment_id": "gap30-set-schema-unique-items-400-v1",
                    "source_runtime_contract_sha256": "1" * 64,
                    "target_runtime_contract_sha256": "2" * 64,
                    "failed_provider_attempt_preserved": True,
                    "failed_case_retried": False,
                    "private_amendment_sha256": "3" * 64,
                },
            },
        )
        _write_json(
            self.paths.core_receipt,
            {
                "schema_version": "1.0",
                "baseline_id": "core40-provisional-v1",
                "config_sha256": sha256_file(self.paths.core_config),
                "passed": True,
                "counts": {"total": 40, "completed": 40, "remaining": 0},
                "provider_budget": {
                    "breached": False,
                    "reserved_usd": 0.01,
                },
                "artifact_sha256s": {
                    "run_records": sha256_file(self.paths.core_runs),
                    "chat_transcripts": sha256_file(self.paths.core_transcripts),
                },
                "runtime_contract_amendment": {
                    "recovery_code_amendment_id": (
                        "core40-mixed-runtime-recovery-v1"
                    ),
                    "source_runtime_contract_sha256": "4" * 64,
                    "target_runtime_contract_sha256": "5" * 64,
                    "failed_case_count": 2,
                    "failed_cases_retried": False,
                    "provider_attempts_preserved": True,
                    "provider_retries": 0,
                    "recovery_audit_count": 2,
                    "recovery_audit_sha256": "6" * 64,
                    "reserved_uncertain_usd": 0.01,
                },
            },
        )
        _write_json(
            self.paths.visual_eda_receipt,
            {
                "schema_version": "1.0",
                "baseline_id": "visual-eda-mini-prospective-v1",
                "config_sha256": sha256_file(self.paths.visual_eda_config),
                "passed": True,
                "counts": {"total": 20, "completed": 20, "remaining": 0},
                "provider_budget": {"breached": False},
                "artifact_sha256s": {
                    "run_records": sha256_file(self.paths.visual_eda_runs),
                    "chat_transcripts": sha256_file(self.paths.visual_eda_transcripts),
                },
            },
        )

    def judgments(self) -> Path:
        path = self.root / "judgments.jsonl"
        packets = {
            row["case_id"]: row for row in read_jsonl(self.paths.judge_packets)
        }
        review_config_sha256 = sha256_file(self.paths.judge_config)
        rows = []
        for case_id in self.case_ids:
            packet = packets[case_id]
            expected_behavior = _expected_behavior(packet)
            observed_status = packet["judge_input"]["candidate"]["status"]
            abstention_case = expected_behavior == "abstain"
            behavior_satisfied = (
                observed_status == "abstained"
                if abstention_case
                else observed_status == "answered"
            )
            row: dict[str, object] = {
                "schema_version": "1.0",
                "judgment_id": "pending",
                "case_id": case_id,
                "case_sha256": packet["hashes"]["case_sha256"],
                "run_record_sha256": packet["hashes"]["run_sha256"],
                "judge_input_sha256": packet["hashes"]["judge_input_sha256"],
                "review_config_sha256": review_config_sha256,
                "rubric_version": "gpt56-semantic-v2",
                "reviewer_type": "llm",
                "model": "gpt-5.6-sol",
                "judge_role": "primary",
                "expected_behavior": expected_behavior,
                "observed_status": observed_status,
                "scores": {
                    "correctness": None if abstention_case else 1,
                    "faithfulness": None if abstention_case else 1,
                    "completeness": None if abstention_case else 1,
                    "factual_claim_coverage": None if abstention_case else 1,
                    "citation_validity": None if abstention_case else 1,
                    "abstention_quality": 1 if abstention_case else None,
                },
                "matched_key_point_ids": [],
                "follow_up_success": None,
                "safe_abstention": behavior_satisfied if abstention_case else None,
                "critical_flags": [],
                "confidence": 0.9,
                "judge_decision": "accepted" if behavior_satisfied else "rejected",
                "rationale": "private rationale",
                "reviewed_at": "2026-08-31T12:00:00+09:00",
            }
            row["judgment_id"] = _judgment_id(row)
            rows.append(row)
        _write_jsonl(path, rows)
        return path


def _changed_judgment(
    row: dict[str, object],
    **changes: object,
) -> dict[str, object]:
    changed = copy.deepcopy(row)
    changed.update(changes)
    changed["judgment_id"] = _judgment_id(changed)
    return changed


def _answer_scores(value: int | float) -> dict[str, object]:
    return {
        "correctness": value,
        "faithfulness": value,
        "completeness": value,
        "factual_claim_coverage": value,
        "citation_validity": value,
        "abstention_quality": None,
    }


def _walk_keys(value: object) -> list[str]:
    keys: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            keys.append(str(key).lower())
            keys.extend(_walk_keys(nested))
    elif isinstance(value, list):
        for nested in value:
            keys.extend(_walk_keys(nested))
    return keys


class Mini131BundleTests(unittest.TestCase):
    def test_packet_strips_nested_source_identity_before_hashing(self) -> None:
        case = _case("private-case")
        case["gold"]["lineage"] = "source-lineage"  # type: ignore[index]
        transcript = _transcript("private-case", "candidate private-case")
        transcript["retrieval"][0].update(  # type: ignore[index, union-attr]
            {"case_id": "private-case", "lane": "dense", "lineage": "source"}
        )
        transcript["selected_context"][0].update(  # type: ignore[index, union-attr]
            {"case_id": "private-case", "lane": "primary", "lineage": "source"}
        )

        packet = _packet(
            case=case,
            run=_run("private-case", "candidate private-case"),
            transcript=transcript,
            lane="supplemental_answer_rerun",
            lineage="prospective_rerun",
        )

        judge_input = packet["judge_input"]
        self.assertFalse(
            set(_walk_keys(judge_input)) & {"case_id", "lane", "lineage"}
        )
        self.assertEqual(judge_input["question_kind"], "document_qa")
        self.assertEqual(
            packet["hashes"]["judge_input_sha256"],
            sha256_text(canonical_json(judge_input)),
        )

    def test_packet_validator_rejects_identity_fields_inside_judge_input(self) -> None:
        for field in ("case_id", "lane", "lineage"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                fixture = Mini131Fixture(Path(directory))
                build_judge_packets(fixture.paths)
                packets = read_jsonl(fixture.paths.judge_packets)
                packets[0]["judge_input"][field] = "identity-leak"
                with self.assertRaisesRegex(
                    ValueError, "mini131_judge_identity_leak"
                ):
                    _validate_packets(packets)

    def test_set_macro_and_micro_prf_are_computed_independently(self) -> None:
        packets = [
            {
                "lane": "supplemental_set_rerun",
                "judge_input": {
                    "expected": {"required_doc_ids": ["a", "b"]},
                    "retrieval": {
                        "retrieved_docs": ["a", "c"],
                        "cited_docs": [],
                        "evidence": [],
                    },
                },
            },
            {
                "lane": "supplemental_set_rerun",
                "judge_input": {
                    "expected": {"required_doc_ids": ["a"]},
                    "retrieval": {
                        "retrieved_docs": ["a", "b", "c"],
                        "cited_docs": [],
                        "evidence": [],
                    },
                },
            },
        ]
        metrics = _objective_companion(packets)
        self.assertEqual(metrics["set_macro_precision"], 0.416667)
        self.assertEqual(metrics["set_macro_recall"], 0.75)
        self.assertEqual(metrics["set_macro_f1"], 0.5)
        self.assertEqual(metrics["set_micro_precision"], 0.4)
        self.assertEqual(metrics["set_micro_recall"], 0.666667)
        self.assertEqual(metrics["set_micro_f1"], 0.5)

    def test_prepare_builds_exact_blind_129_packet_ledger_and_content_free_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Mini131Fixture(Path(directory))
            receipt = build_judge_packets(fixture.paths)
            packets = read_jsonl(fixture.paths.judge_packets)
            blind_rows = read_jsonl(fixture.paths.blind_judge_inputs)
            self.assertEqual(len(packets), 129)
            self.assertEqual(len(blind_rows), 129)
            self.assertEqual(receipt["counts"]["by_lineage"], {"legacy_reconstructed": 39, "prospective_rerun": 90})
            self.assertEqual(receipt["counts"]["by_lane"]["core40"], 40)
            self.assertEqual(receipt["counts"]["by_lane"]["supplemental_set_rerun"], 13)
            self.assertEqual(receipt["objective_companion_metrics"]["set_exact_match_rate"], 1.0)
            self.assertEqual(receipt["objective_companion_metrics"]["set_macro_precision"], 1.0)
            self.assertEqual(receipt["objective_companion_metrics"]["set_macro_recall"], 1.0)
            self.assertEqual(receipt["objective_companion_metrics"]["set_macro_f1"], 1.0)
            self.assertEqual(receipt["objective_companion_metrics"]["set_micro_precision"], 1.0)
            self.assertEqual(receipt["objective_companion_metrics"]["set_micro_recall"], 1.0)
            self.assertEqual(receipt["objective_companion_metrics"]["set_micro_f1"], 1.0)
            page_metrics = receipt["objective_companion_metrics"]["visual_target_page"]
            self.assertEqual(page_metrics["eligible_case_count"], 10)
            self.assertEqual(page_metrics["hit_rate"], 0.8)
            self.assertEqual(page_metrics["first_rank"], {"observed_count": 8, "mean": 4.5, "median": 4.5, "min": 1.0, "max": 8.0})
            self.assertEqual(receipt["objective_companion_metrics"]["visual_target_chunk"]["hit_rate"], 0.7)
            self.assertEqual(receipt["objective_companion_metrics"]["visual_target_object_bridge"]["hit_rate"], 0.5)
            self.assertEqual(receipt["objective_companion_metrics"]["analytics_deterministic_companion_case_count"], 10)
            self.assertEqual(receipt["objective_companion_metrics"]["analytics_deterministic_companion_pass_count"], 10)
            self.assertEqual(receipt["objective_companion_metrics"]["analytics_deterministic_companion_complete_rate"], 1.0)
            self.assertEqual(receipt["objective_companion_metrics"]["analytics_deterministic_case_pass_count"], 10)
            self.assertEqual(receipt["objective_companion_metrics"]["analytics_deterministic_case_pass_rate"], 1.0)
            self.assertEqual(receipt["objective_companion_metrics"]["analytics_deterministic_field_count"], 20)
            self.assertEqual(receipt["objective_companion_metrics"]["analytics_deterministic_field_pass_count"], 20)
            self.assertEqual(receipt["objective_companion_metrics"]["analytics_deterministic_field_pass_rate"], 1.0)
            self.assertEqual(receipt["objective_companion_metrics"]["analytics_numeric_evidence_field_count"], 20)
            self.assertEqual(
                receipt["objective_companion_metrics"]["analytics_numeric_evidence_fields_per_case"],
                {"observed_case_count": 10, "mean": 2.0, "min": 2, "max": 2},
            )
            self.assertEqual(receipt["costs"]["candidate_provider_usd"], 0.129)
            self.assertEqual(
                receipt["semantic_judge"]["review_config_sha256"],
                sha256_file(fixture.paths.judge_config),
            )
            self.assertEqual(
                receipt["semantic_judge"]["rubric_sha256"],
                sha256_file(fixture.paths.rubric),
            )
            self.assertEqual(
                receipt["scorecard_contract_sha256"],
                sha256_file(fixture.paths.scorecard_contract),
            )
            for field in (
                "legacy_receipt",
                "gap_receipt",
                "core_receipt",
                "visual_eda_receipt",
                "judge_config",
                "rubric",
                "scorecard_contract",
            ):
                self.assertEqual(
                    receipt["artifact_sha256s"]["inputs"][field],
                    sha256_file(getattr(fixture.paths, field)),
                )
            self.assertEqual(stat.S_IMODE(fixture.paths.judge_packets.stat().st_mode), 0o600)
            self.assertEqual(
                stat.S_IMODE(fixture.paths.blind_judge_inputs.stat().st_mode),
                0o600,
            )
            self.assertEqual(
                receipt["artifact_sha256s"]["blind_judge_inputs"],
                sha256_file(fixture.paths.blind_judge_inputs),
            )
            self.assertEqual(
                [row["blind_id"] for row in blind_rows],
                sorted(row["blind_id"] for row in blind_rows),
            )
            for row in blind_rows:
                self.assertEqual(
                    set(row),
                    {
                        "schema_version",
                        "blind_id",
                        "judge_input_sha256",
                        "judge_input",
                    },
                )
                self.assertFalse(set(row) & {"case_id", "lane", "lineage"})
                judge_keys = set(_walk_keys(row["judge_input"]))
                self.assertFalse(judge_keys & {"case_id", "lane", "lineage"})
                self.assertEqual(
                    row["judge_input_sha256"],
                    sha256_text(canonical_json(row["judge_input"])),
                )

            for packet in packets:
                judge_input = packet["judge_input"]
                self.assertEqual(
                    packet["hashes"]["transcript_sha256"],
                    sha256_text(canonical_json(packet["source_transcript"])),
                )
                self.assertIn("provider_exchange", packet["source_transcript"])
                keys = set(_walk_keys(judge_input))
                self.assertFalse(keys & BANNED_JUDGE_KEYS)
                self.assertNotIn("provider_exchange", keys)
                self.assertNotIn("generation_prompt", keys)
                self.assertNotIn("lineage", keys)
                self.assertNotIn("gpt-5-mini", canonical_json(judge_input))
                self.assertNotIn("legacy", str(judge_input["question_kind"]))
                self.assertNotIn("rerun", str(judge_input["question_kind"]))
            supplemental_answer_kinds = {
                packet["judge_input"]["question_kind"]
                for packet in packets
                if packet["lane"] in {
                    "supplemental_answer_legacy",
                    "supplemental_answer_rerun",
                }
            }
            self.assertEqual(supplemental_answer_kinds, {"document_qa"})
            public_text = fixture.paths.receipt.read_text(encoding="utf-8")
            self.assertNotIn("private question", public_text)
            self.assertNotIn("private gold", public_text)
            self.assertNotIn("candidate legacy", public_text)
            self.assertNotIn("private generation prompt", public_text)

    def test_prepare_rejects_scorecard_contract_drift_before_private_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Mini131Fixture(Path(directory))
            contract = expected_contract()
            contract["contract_id"] = "drifted"
            _write_json(fixture.paths.scorecard_contract, contract)

            with self.assertRaisesRegex(
                ValueError, "mini131_scorecard_contract_mismatch"
            ):
                build_judge_packets(fixture.paths)

            self.assertFalse(fixture.paths.judge_packets.exists())
            self.assertFalse(fixture.paths.blind_judge_inputs.exists())
            self.assertFalse(fixture.paths.receipt.exists())

    def test_merge_enforces_fixed_sol_v2_and_builds_report_compatible_131_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Mini131Fixture(Path(directory))
            build_judge_packets(fixture.paths)
            receipt = merge_judgments(fixture.paths, fixture.judgments())
            records = read_jsonl(fixture.paths.case_records)
            self.assertEqual(len(validate_records(records)), 131)
            self.assertEqual(receipt["counts"]["rag"], 129)
            self.assertEqual(receipt["counts"]["parser"], 2)
            self.assertEqual(receipt["counts"]["parser_passed"], 2)
            self.assertEqual(receipt["counts"]["full_source_transcripts"], 129)
            self.assertEqual(receipt["semantic_judge"]["model"], "gpt-5.6-sol")
            self.assertEqual(receipt["semantic_judge"]["rubric_version"], "gpt56-semantic-v2")
            self.assertEqual(receipt["semantic_judge"]["mean_semantic_score"], 100.0)
            self.assertEqual(stat.S_IMODE(fixture.paths.case_records.stat().st_mode), 0o600)
            rag_records = [row for row in records if row["case_type"] == "rag"]
            self.assertEqual(len(rag_records), 129)
            for record in rag_records:
                self.assertEqual(
                    record["source_transcript_sha256"],
                    sha256_text(canonical_json(record["source_transcript"])),
                )
                self.assertIn("provider_exchange", record["source_transcript"])

    def test_merge_rejects_wrong_model_and_exact_score_key_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Mini131Fixture(Path(directory))
            build_judge_packets(fixture.paths)
            judgments = read_jsonl(fixture.judgments())
            judgments[0]["model"] = "gpt-5-mini"
            wrong_model = fixture.root / "wrong-model.jsonl"
            _write_jsonl(wrong_model, judgments)
            with self.assertRaisesRegex(ValueError, "mini131_judge_model_mismatch"):
                merge_judgments(fixture.paths, wrong_model)

            judgments[0]["model"] = "gpt-5.6-sol"
            judgments[0]["scores"]["factual_claim_citation_coverage"] = judgments[0]["scores"].pop("factual_claim_coverage")
            wrong_key = fixture.root / "wrong-key.jsonl"
            _write_jsonl(wrong_key, judgments)
            with self.assertRaisesRegex(ValueError, "mini131_judge_score_fields_invalid"):
                merge_judgments(fixture.paths, wrong_key)

    def test_merge_rejects_judgment_bound_to_a_different_blind_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Mini131Fixture(Path(directory))
            build_judge_packets(fixture.paths)
            judgments = read_jsonl(fixture.judgments())
            judgments[0]["judge_input_sha256"] = "0" * 64
            mismatched = fixture.root / "mismatched-input-hash.jsonl"
            _write_jsonl(mismatched, judgments)
            with self.assertRaisesRegex(
                ValueError, "mini131_judgment_input_hash_mismatch"
            ):
                merge_judgments(fixture.paths, mismatched)

    def test_merge_rejects_tampered_blind_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Mini131Fixture(Path(directory))
            build_judge_packets(fixture.paths)
            blind_rows = read_jsonl(fixture.paths.blind_judge_inputs)
            blind_rows[0]["judge_input"]["candidate"]["answer"] = "tampered"
            _write_jsonl(fixture.paths.blind_judge_inputs, blind_rows)
            with self.assertRaisesRegex(
                ValueError, "mini131_blind_judge_inputs_mismatch"
            ):
                merge_judgments(fixture.paths, fixture.judgments())

    def test_merge_rejects_tampered_full_source_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Mini131Fixture(Path(directory))
            build_judge_packets(fixture.paths)
            judgments = fixture.judgments()
            packets = read_jsonl(fixture.paths.judge_packets)
            packets[0]["source_transcript"]["tampered"] = True
            _write_jsonl(fixture.paths.judge_packets, packets)
            with self.assertRaisesRegex(
                ValueError, "mini131_source_transcript_hash_mismatch"
            ):
                merge_judgments(fixture.paths, judgments)

    def test_prepare_rejects_source_run_or_transcript_not_bound_by_final_receipt(self) -> None:
        mutations = (
            ("legacy run", "legacy_runs", "mini131_legacy_receipt_answer_runs_sha256_mismatch"),
            ("legacy transcript", "legacy_transcripts", "mini131_legacy_receipt_chat_transcripts_sha256_mismatch"),
            ("gap run", "gap_answer_runs", "mini131_gap_receipt_answer_runs_sha256_mismatch"),
            ("gap transcript", "gap_transcripts", "mini131_gap_receipt_chat_transcripts_sha256_mismatch"),
            ("core run", "core_runs", "mini131_core_receipt_run_records_sha256_mismatch"),
            ("core transcript", "core_transcripts", "mini131_core_receipt_chat_transcripts_sha256_mismatch"),
            ("visual run", "visual_eda_runs", "mini131_visual_eda_receipt_run_records_sha256_mismatch"),
            ("visual transcript", "visual_eda_transcripts", "mini131_visual_eda_receipt_chat_transcripts_sha256_mismatch"),
        )
        for label, field, expected_error in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                fixture = Mini131Fixture(Path(directory))
                path = getattr(fixture.paths, field)
                rows = read_jsonl(path)
                rows[0]["receipt_drift"] = True
                _write_jsonl(path, rows)
                with self.assertRaisesRegex(ValueError, expected_error):
                    build_judge_packets(fixture.paths)

    def test_prepare_rejects_incomplete_or_misidentified_source_receipt(self) -> None:
        mutations = (
            (
                "legacy schema",
                "legacy_receipt",
                lambda value: value.__setitem__("schema_version", "0.9"),
                "mini131_legacy_receipt_schema_version_mismatch",
            ),
            (
                "legacy baseline",
                "legacy_receipt",
                lambda value: value.__setitem__("baseline_id", "wrong"),
                "mini131_legacy_receipt_baseline_id_mismatch",
            ),
            (
                "gap completion",
                "gap_receipt",
                lambda value: value.__setitem__("suite_complete", False),
                "mini131_gap_receipt_not_complete",
            ),
            (
                "gap explicit failed",
                "gap_receipt",
                lambda value: value.__setitem__("passed", False),
                "mini131_gap_receipt_not_passed",
            ),
            (
                "core passed",
                "core_receipt",
                lambda value: value.__setitem__("passed", False),
                "mini131_core_receipt_not_complete",
            ),
            (
                "visual counts",
                "visual_eda_receipt",
                lambda value: value["counts"].__setitem__("completed", 19),
                "mini131_visual_eda_receipt_counts_mismatch",
            ),
        )
        for label, field, mutate, expected_error in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                fixture = Mini131Fixture(Path(directory))
                path = getattr(fixture.paths, field)
                value = json.loads(path.read_text(encoding="utf-8"))
                mutate(value)
                _write_json(path, value)
                with self.assertRaisesRegex(ValueError, expected_error):
                    build_judge_packets(fixture.paths)

    def test_prepare_accepts_exact_core_and_gap_runtime_amendments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Mini131Fixture(Path(directory))
            receipt = build_judge_packets(fixture.paths)
            self.assertEqual(receipt["counts"]["rag"], 129)
            self.assertEqual(
                sum(
                    "recovery" in row
                    for row in read_jsonl(fixture.paths.core_transcripts)
                ),
                2,
            )
            self.assertEqual(
                sum(
                    row.get("capture_mode")
                    == "prospective_runtime_exact_recovered_provider_rejection"
                    for row in read_jsonl(fixture.paths.gap_transcripts)
                ),
                1,
            )

    def test_prepare_rejects_core_runtime_amendment_tampering(self) -> None:
        receipt_mutations = (
            (
                "extra public field",
                lambda value: value["runtime_contract_amendment"].__setitem__(
                    "case_id", "private-case"
                ),
                "mini131_core_receipt_runtime_amendment_invalid",
            ),
            (
                "wrong id",
                lambda value: value["runtime_contract_amendment"].__setitem__(
                    "recovery_code_amendment_id", "wrong"
                ),
                "mini131_core_receipt_runtime_amendment_id_mismatch",
            ),
            (
                "uppercase sha",
                lambda value: value["runtime_contract_amendment"].__setitem__(
                    "source_runtime_contract_sha256", "A" * 64
                ),
                (
                    "mini131_core_receipt_runtime_amendment_"
                    "source_runtime_contract_sha256_invalid"
                ),
            ),
            (
                "failed count",
                lambda value: value["runtime_contract_amendment"].__setitem__(
                    "failed_case_count", 1
                ),
                "mini131_core_receipt_runtime_amendment_count_mismatch",
            ),
            (
                "retry flag",
                lambda value: value["runtime_contract_amendment"].__setitem__(
                    "failed_cases_retried", True
                ),
                "mini131_core_receipt_runtime_amendment_retry_invalid",
            ),
            (
                "attempt preservation",
                lambda value: value["runtime_contract_amendment"].__setitem__(
                    "provider_attempts_preserved", False
                ),
                (
                    "mini131_core_receipt_runtime_amendment_"
                    "attempt_preservation_invalid"
                ),
            ),
            (
                "retry count bool",
                lambda value: value["runtime_contract_amendment"].__setitem__(
                    "provider_retries", False
                ),
                "mini131_core_receipt_runtime_amendment_retry_count_invalid",
            ),
            (
                "reserved budget",
                lambda value: value["runtime_contract_amendment"].__setitem__(
                    "reserved_uncertain_usd", 0.02
                ),
                "mini131_core_receipt_runtime_amendment_budget_mismatch",
            ),
        )
        for label, mutate, expected_error in receipt_mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                fixture = Mini131Fixture(Path(directory))
                value = json.loads(
                    fixture.paths.core_receipt.read_text(encoding="utf-8")
                )
                mutate(value)
                _write_json(fixture.paths.core_receipt, value)
                with self.assertRaisesRegex(ValueError, expected_error):
                    build_judge_packets(fixture.paths)

        with tempfile.TemporaryDirectory() as directory:
            fixture = Mini131Fixture(Path(directory))
            transcripts = read_jsonl(fixture.paths.core_transcripts)
            transcripts[0].pop("recovery")
            transcripts[0]["capture_mode"] = "prospective_runtime_exact"
            _write_jsonl(fixture.paths.core_transcripts, transcripts)
            fixture.refresh_source_receipts()
            with self.assertRaisesRegex(
                ValueError, "mini131_core_recovery_marker_count_mismatch"
            ):
                build_judge_packets(fixture.paths)

    def test_prepare_rejects_gap_runtime_amendment_or_rejection_tampering(self) -> None:
        receipt_mutations = (
            (
                "extra public field",
                lambda value: value["runtime_contract_amendment"].__setitem__(
                    "failed_case_id", "private-case"
                ),
                "mini131_gap_receipt_runtime_amendment_invalid",
            ),
            (
                "wrong id",
                lambda value: value["runtime_contract_amendment"].__setitem__(
                    "amendment_id", "wrong"
                ),
                "mini131_gap_receipt_runtime_amendment_id_mismatch",
            ),
            (
                "uppercase sha",
                lambda value: value["runtime_contract_amendment"].__setitem__(
                    "target_runtime_contract_sha256", "B" * 64
                ),
                (
                    "mini131_gap_receipt_runtime_amendment_"
                    "target_runtime_contract_sha256_invalid"
                ),
            ),
            (
                "retry flag",
                lambda value: value["runtime_contract_amendment"].__setitem__(
                    "failed_case_retried", True
                ),
                "mini131_gap_receipt_runtime_amendment_retry_invalid",
            ),
            (
                "attempt preservation",
                lambda value: value["runtime_contract_amendment"].__setitem__(
                    "failed_provider_attempt_preserved", False
                ),
                (
                    "mini131_gap_receipt_runtime_amendment_"
                    "attempt_preservation_invalid"
                ),
            ),
            (
                "status counts",
                lambda value: value["status_counts"].__setitem__("error", 2),
                "mini131_gap_receipt_status_counts_mismatch",
            ),
        )
        for label, mutate, expected_error in receipt_mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                fixture = Mini131Fixture(Path(directory))
                value = json.loads(
                    fixture.paths.gap_receipt.read_text(encoding="utf-8")
                )
                mutate(value)
                _write_json(fixture.paths.gap_receipt, value)
                with self.assertRaisesRegex(ValueError, expected_error):
                    build_judge_packets(fixture.paths)

        with tempfile.TemporaryDirectory() as directory:
            fixture = Mini131Fixture(Path(directory))
            transcripts = read_jsonl(fixture.paths.gap_transcripts)
            recovered = next(
                row
                for row in transcripts
                if row.get("capture_mode")
                == "prospective_runtime_exact_recovered_provider_rejection"
            )
            recovered["provider_exchange"]["generation"]["error"]["message"] = (
                "Error code: 400 - unrelated rejection"
            )
            _write_jsonl(fixture.paths.gap_transcripts, transcripts)
            fixture.refresh_source_receipts()
            with self.assertRaisesRegex(
                ValueError, "mini131_gap_recovery_provider_rejection_invalid"
            ):
                build_judge_packets(fixture.paths)

    def test_prepare_rejects_fixed_judge_config_or_rubric_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Mini131Fixture(Path(directory))
            config = json.loads(fixture.paths.judge_config.read_text(encoding="utf-8"))
            config["model"] = "gpt-5-mini"
            _write_json(fixture.paths.judge_config, config)
            with self.assertRaisesRegex(ValueError, "mini131_judge_config_mismatch"):
                build_judge_packets(fixture.paths)

        with tempfile.TemporaryDirectory() as directory:
            fixture = Mini131Fixture(Path(directory))
            fixture.paths.rubric.write_text("changed rubric\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "mini131_judge_config_mismatch"):
                build_judge_packets(fixture.paths)

    def test_merge_enforces_closed_judgment_schema_and_all_hash_bindings(self) -> None:
        mutations = (
            (
                "extra field",
                lambda row: row.__setitem__("semantic_score", 100.0),
                "mini131_judgment_fields_invalid",
            ),
            (
                "case hash",
                lambda row: row.__setitem__("case_sha256", "0" * 64),
                "mini131_judgment_case_sha256_mismatch",
            ),
            (
                "run hash",
                lambda row: row.__setitem__("run_record_sha256", "0" * 64),
                "mini131_judgment_run_record_sha256_mismatch",
            ),
            (
                "review config hash",
                lambda row: row.__setitem__("review_config_sha256", "0" * 64),
                "mini131_judgment_review_config_sha256_mismatch",
            ),
            (
                "observed status",
                lambda row: row.__setitem__("observed_status", "error"),
                "mini131_judgment_observed_status_mismatch",
            ),
            (
                "reviewed at",
                lambda row: row.__setitem__("reviewed_at", "2026-08-31"),
                "mini131_judgment_reviewed_at_invalid",
            ),
            (
                "judgment id",
                lambda row: row.__setitem__("judgment_id", "0" * 64),
                "mini131_judgment_id_mismatch",
            ),
        )
        for label, mutate, expected_error in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                fixture = Mini131Fixture(Path(directory))
                build_judge_packets(fixture.paths)
                judgments = read_jsonl(fixture.judgments())
                mutate(judgments[0])
                path = fixture.root / "mutated-judgments.jsonl"
                _write_jsonl(path, judgments)
                with self.assertRaisesRegex(ValueError, expected_error):
                    merge_judgments(fixture.paths, path)

    def test_score_mode_is_bound_to_expected_behavior(self) -> None:
        _validate_judgment_scores(_answer_scores(1), expected_behavior="answer")
        _validate_judgment_scores(
            {
                "correctness": None,
                "faithfulness": None,
                "completeness": None,
                "factual_claim_coverage": None,
                "citation_validity": None,
                "abstention_quality": 1,
            },
            expected_behavior="abstain",
        )
        with self.assertRaisesRegex(
            ValueError, "mini131_answer_abstention_quality_forbidden"
        ):
            _validate_judgment_scores(
                {
                    **_answer_scores(1),
                    "abstention_quality": 1,
                },
                expected_behavior="source_conflict",
            )
        with self.assertRaisesRegex(
            ValueError, "mini131_abstention_answer_components_forbidden"
        ):
            _validate_judgment_scores(
                {**_answer_scores(1), "abstention_quality": 1},
                expected_behavior="abstain",
            )

    def test_candidate_error_or_wrong_abstention_must_be_rejected(self) -> None:
        for status in ("abstained", "error"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                fixture = Mini131Fixture(Path(directory))
                case_id = "gap-answer-001"
                runs = read_jsonl(fixture.paths.gap_answer_runs)
                run = next(row for row in runs if row["case_id"] == case_id)
                run["status"] = status
                run["answer"] = ""
                _write_jsonl(fixture.paths.gap_answer_runs, runs)
                transcripts = read_jsonl(fixture.paths.gap_transcripts)
                transcript = next(row for row in transcripts if row["case_id"] == case_id)
                transcript["assistant"]["final_answer"] = ""
                _write_jsonl(fixture.paths.gap_transcripts, transcripts)
                fixture.refresh_source_receipts()
                build_judge_packets(fixture.paths)
                judgments = read_jsonl(fixture.judgments())
                target = next(row for row in judgments if row["case_id"] == case_id)
                self.assertEqual(target["judge_decision"], "rejected")
                merge_judgments(fixture.paths, fixture.root / "judgments.jsonl")
                target["judge_decision"] = "accepted"
                target["judgment_id"] = _judgment_id(target)
                invalid = fixture.root / "invalid-hard-rejection.jsonl"
                _write_jsonl(invalid, judgments)
                with self.assertRaisesRegex(
                    ValueError, "mini131_judge_decision_inconsistent"
                ):
                    merge_judgments(fixture.paths, invalid)

    def test_triggered_agreeing_secondary_resolves_without_adjudicator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Mini131Fixture(Path(directory))
            build_judge_packets(fixture.paths)
            judgments = read_jsonl(fixture.judgments())
            primary = judgments[0]
            primary["scores"] = {
                **_answer_scores(1),
                "factual_claim_coverage": 0,
                "citation_validity": 0,
            }
            primary["judge_decision"] = "needs_review"
            primary["judgment_id"] = _judgment_id(primary)
            secondary = _changed_judgment(
                primary,
                judge_role="secondary",
                scores=_answer_scores(0),
                judge_decision="rejected",
                reviewed_at="2026-08-31T12:01:00+09:00",
            )
            judgments.append(secondary)
            path = fixture.root / "secondary-resolved.jsonl"
            _write_jsonl(path, judgments)
            receipt = merge_judgments(fixture.paths, path)
            self.assertEqual(receipt["counts"]["secondary_triggered_cases"], 1)
            self.assertEqual(receipt["counts"]["adjudicated_cases"], 0)
            self.assertEqual(receipt["counts"]["judge_roles"]["secondary"], 1)
            records = read_jsonl(fixture.paths.case_records)
            record = next(row for row in records if row["case_id"] == primary["case_id"])
            self.assertEqual(record["judgment"]["judge_role"], "secondary")
            self.assertEqual(len(record["judgment_history"]), 2)
            self.assertTrue(record["judgment_workflow"]["secondary_required"])
            self.assertFalse(record["judgment_workflow"]["adjudicator_required"])

    def test_trigger_history_requires_secondary_and_disagreement_adjudication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Mini131Fixture(Path(directory))
            build_judge_packets(fixture.paths)
            judgments = read_jsonl(fixture.judgments())
            primary = judgments[0]
            primary["scores"] = {
                **_answer_scores(1),
                "factual_claim_coverage": 0,
                "citation_validity": 0,
            }
            primary["judge_decision"] = "needs_review"
            primary["judgment_id"] = _judgment_id(primary)
            missing_secondary = fixture.root / "missing-secondary.jsonl"
            _write_jsonl(missing_secondary, judgments)
            with self.assertRaisesRegex(
                ValueError, "mini131_secondary_judgment_missing"
            ):
                merge_judgments(fixture.paths, missing_secondary)

            secondary = _changed_judgment(
                primary,
                judge_role="secondary",
                scores=_answer_scores(1),
                judge_decision="accepted",
                reviewed_at="2026-08-31T12:01:00+09:00",
            )
            judgments.append(secondary)
            missing_adjudicator = fixture.root / "missing-adjudicator.jsonl"
            _write_jsonl(missing_adjudicator, judgments)
            with self.assertRaisesRegex(
                ValueError, "mini131_adjudicator_judgment_missing"
            ):
                merge_judgments(fixture.paths, missing_adjudicator)

            adjudicator = _changed_judgment(
                primary,
                judge_role="adjudicator",
                scores=_answer_scores(1),
                judge_decision="accepted",
                reviewed_at="2026-08-31T12:02:00+09:00",
            )
            judgments.append(adjudicator)
            adjudicated = fixture.root / "adjudicated.jsonl"
            _write_jsonl(adjudicated, judgments)
            receipt = merge_judgments(fixture.paths, adjudicated)
            self.assertEqual(receipt["counts"]["adjudicated_cases"], 1)
            self.assertTrue(receipt["semantic_judge"]["trigger_resolution_complete"])

            judgments[-1] = _changed_judgment(
                adjudicator,
                judge_decision="needs_human",
            )
            unresolved = fixture.root / "unresolved-adjudication.jsonl"
            _write_jsonl(unresolved, judgments)
            with self.assertRaisesRegex(
                ValueError, "mini131_adjudication_unresolved"
            ):
                merge_judgments(fixture.paths, unresolved)

    def test_parser_receipt_is_cryptographically_and_semantically_bound(self) -> None:
        mutations = (
            (
                "baseline",
                lambda value: value.__setitem__("baseline_id", "wrong"),
                "mini131_parser_receipt_baseline_id_mismatch",
            ),
            (
                "config hash",
                lambda value: value["artifacts"].__setitem__(
                    "config_sha256", "0" * 64
                ),
                "mini131_parser_receipt_config_sha256_mismatch",
            ),
            (
                "manifest hash",
                lambda value: value["artifacts"].__setitem__(
                    "manifest_sha256", "0" * 64
                ),
                "mini131_parser_receipt_manifest_sha256_mismatch",
            ),
            (
                "counts",
                lambda value: value["counts"].__setitem__("passed", 1),
                "mini131_parser_receipt_counts_mismatch",
            ),
            (
                "doc id",
                lambda value: value["cases"][0].__setitem__("doc_id", "wrong"),
                "mini131_parser_doc_id_mismatch",
            ),
            (
                "incomplete checks",
                lambda value: value["cases"][0]["checks"].pop(
                    "block_file_count_match"
                ),
                "mini131_parser_checks_invalid",
            ),
            (
                "false check",
                lambda value: value["cases"][0]["checks"].__setitem__(
                    "status_match", False
                ),
                "mini131_parser_checks_invalid",
            ),
            (
                "observed drift",
                lambda value: value["cases"][0]["observed"].__setitem__(
                    "page_count", 999
                ),
                "mini131_parser_observed_mismatch",
            ),
        )
        for label, mutate, expected_error in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                fixture = Mini131Fixture(Path(directory))
                build_judge_packets(fixture.paths)
                judgments = fixture.judgments()
                receipt = json.loads(
                    fixture.paths.parser_receipt.read_text(encoding="utf-8")
                )
                mutate(receipt)
                _write_json(fixture.paths.parser_receipt, receipt)
                with self.assertRaisesRegex(ValueError, expected_error):
                    merge_judgments(fixture.paths, judgments)

    def test_prepare_rejects_prospective_source_identity_drift(self) -> None:
        mutations = (
            (
                "gap transcript config",
                "gap_transcripts",
                lambda row: row.__setitem__("config_sha256", "0" * 64),
                "mini131_transcript_config_sha256_mismatch",
            ),
            (
                "core run config",
                "core_runs",
                lambda row: row.__setitem__("config_sha256", "0" * 64),
                "mini131_run_config_sha256_mismatch",
            ),
            (
                "visual transcript capture",
                "visual_eda_transcripts",
                lambda row: row.__setitem__("capture_mode", "posthoc_reconstructed"),
                "mini131_prospective_capture_mode_mismatch",
            ),
        )
        for label, field, mutate, expected_error in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                fixture = Mini131Fixture(Path(directory))
                path = getattr(fixture.paths, field)
                rows = read_jsonl(path)
                mutate(rows[0])
                _write_jsonl(path, rows)
                fixture.refresh_source_receipts()
                with self.assertRaisesRegex(ValueError, expected_error):
                    build_judge_packets(fixture.paths)

    def test_fail_closed_on_legacy39_drift_before_replacing_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Mini131Fixture(Path(directory))
            fixture.paths.judge_packets.parent.mkdir(parents=True)
            fixture.paths.judge_packets.write_text("keep", encoding="utf-8")
            rows = read_jsonl(fixture.paths.gap_answer_runs)[:-1]
            _write_jsonl(fixture.paths.gap_answer_runs, rows)
            fixture.refresh_source_receipts()
            with self.assertRaisesRegex(ValueError, "mini131_gap_answer_runs_count_mismatch"):
                build_judge_packets(fixture.paths)
            self.assertEqual(fixture.paths.judge_packets.read_text(encoding="utf-8"), "keep")

    def test_preflight_reports_missing_logical_names_without_private_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Mini131Fixture(Path(directory))
            fixture.paths.core_runs.unlink()
            report = preflight(fixture.paths)
            self.assertFalse(report["ready"])
            self.assertEqual(report["missing_inputs"], ["core_runs"])
            self.assertNotIn("private question", canonical_json(report))

    def test_cli_failure_is_content_free(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with redirect_stdout(output):
                status = main(["preflight", "--repo-root", directory])
            self.assertEqual(status, 1)
            result = json.loads(output.getvalue())
            self.assertFalse(result["ready"])
            self.assertTrue(result["missing_inputs"])
            self.assertNotIn(str(Path(directory).resolve()), output.getvalue())


if __name__ == "__main__":
    unittest.main()
