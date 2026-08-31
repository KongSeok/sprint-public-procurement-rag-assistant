from __future__ import annotations

import copy
import json
import math
import re
import stat
import tempfile
import unittest
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from statistics import fmean
from types import SimpleNamespace

from midprojectrag.ingest.common import (
    canonical_json,
    read_jsonl,
    sha256_file,
    sha256_text,
)
from midprojectrag.evaluation import EXPECTED_METRIC_KEYS
from midprojectrag.local_mini131_baseline import DEFAULT_CONFIG, verify_suite
from midprojectrag.local_mini131_performance import (
    RECORD_SCHEMA_VERSION,
    REPORT_SCHEMA_VERSION,
    SUMMARY_SCHEMA_VERSION,
    PerformancePaths,
    _common_evaluation_metrics,
    _load_parser_results,
    _objective_companion_metrics,
    _primary_category_summaries,
    _scenario_summaries,
    _visual_subgroup_summaries,
    build_performance_evaluation,
    content_free_receipt,
    default_paths,
    render_html,
    resolve_final_judgments,
    validate_performance_evaluation,
    write_performance_outputs,
)
from midprojectrag.local_mini131_semantic import (
    default_paths as semantic_default_paths,
    load_ledger,
)


PRIVATE_QUESTION = "<script>privateQuestion()</script>"
PRIVATE_EXPECTED = "private expected answer sentinel"
PRIVATE_CANDIDATE = "private candidate answer sentinel"
PRIVATE_EVIDENCE = "private evidence sentinel"
PRIVATE_RATIONALE = "private rationale sentinel"
COMPONENTS = {
    "correctness",
    "faithfulness",
    "completeness",
    "factual_claim_coverage",
    "citation_validity",
    "abstention_quality",
}
PRIMARY_CATEGORIES = {
    "bid_rag_scenarios",
    "clause_fact_regression",
    "conditional_all_list",
    "gold_source_alignment",
    "visual_table_figure",
    "corpus_analytics",
    "parser_regression",
}
SCENARIO_CATEGORIES = {
    "single_doc",
    "multi_doc_compare",
    "follow_up",
    "unknown",
}
VISUAL_SUBGROUPS = {"hwp_table", "hwp_figure", "pdf_table", "pdf_figure"}
API_PARITY_KEYS = {
    "primary_categories",
    "scenario_breakdown",
    "visual_subgroups",
    "objective_companion_metrics",
    "common_evaluation_metrics",
    "api_reference",
    "local_candidate",
    "case_identity",
    "same_item_comparison",
}
COMMON_METRIC_ENTRY_KEYS = {
    "value",
    "eligible",
    "coverage",
    "available",
    "reason",
}
PUBLIC_PRIVATE_FIELD_KEYS = {
    "case_id",
    "case_ids",
    "cases",
    "question",
    "questions",
    "expected",
    "answer",
    "answers",
    "evidence",
    "rationale",
    "blind_id",
    "private_path",
}
SAFE_STRUCTURAL_ANSWER_PATHS = {
    ("summary", "api_parity", "common_evaluation_metrics", "answer"),
    ("metrics", "api_parity", "common_evaluation_metrics", "answer"),
}


def _write_private(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    path.chmod(0o600)


def _write_private_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600)
    path.write_text(
        "".join(canonical_json(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    path.chmod(0o600)


def _nested_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, Mapping):
        for key, nested in value.items():
            keys.add(str(key))
            keys.update(_nested_keys(nested))
    elif isinstance(value, list):
        for nested in value:
            keys.update(_nested_keys(nested))
    return keys


def _nested_key_paths(
    value: object,
    prefix: tuple[str, ...] = (),
) -> set[tuple[str, ...]]:
    paths: set[tuple[str, ...]] = set()
    if isinstance(value, Mapping):
        for key, nested in value.items():
            path = (*prefix, str(key))
            paths.add(path)
            paths.update(_nested_key_paths(nested, path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            paths.update(_nested_key_paths(nested, (*prefix, f"[{index}]")))
    return paths


def _unexpected_public_private_key_paths(value: object) -> set[tuple[str, ...]]:
    return {
        path
        for path in _nested_key_paths(value)
        if path[-1] in PUBLIC_PRIVATE_FIELD_KEYS
        and path not in SAFE_STRUCTURAL_ANSWER_PATHS
    }


def _plan() -> list[tuple[str, str, str]]:
    difficulty = ["easy"] * 41 + ["medium"] * 48 + ["hard"] * 40
    lane_and_purpose = (
        [("core40", "single_doc")] * 10
        + [("core40", "multi_doc_compare")] * 10
        + [("core40", "follow_up")] * 10
        + [("core40", "unknown")] * 10
        + [("supplemental_answer_legacy", "clause_fact_regression")] * 39
        + [("supplemental_answer_rerun", "clause_fact_regression")] * 5
        + [("supplemental_answer_rerun", "gold_source_alignment")] * 12
        + [("supplemental_set_rerun", "conditional_all_list")] * 13
        + [("visual", "visual_table_figure")] * 10
        + [("corpus_analytics", "corpus_analytics")] * 10
    )
    return [
        (lane, purpose, level)
        for (lane, purpose), level in zip(lane_and_purpose, difficulty, strict=True)
    ]


def _component_summary(records: Sequence[Mapping[str, object]]) -> dict[str, object]:
    return {
        name: {
            "eligible": 0 if name == "abstention_quality" else len(records),
            "mean": None if name == "abstention_quality" else 1.0,
        }
        for name in sorted(COMPONENTS)
    }


def _group_summary(records: Sequence[Mapping[str, object]]) -> dict[str, object]:
    rag = [row for row in records if row["asset_type"] == "rag"]
    accepted = sum(
        row["semantic_evaluation"]["verdict"] == "accepted"  # type: ignore[index]
        for row in rag
    )
    scores = [
        float(row["semantic_evaluation"]["score"])  # type: ignore[index]
        for row in rag
    ]
    return {
        "count": len(records),
        "rag_count": len(rag),
        "parser_count": len(records) - len(rag),
        "status": {
            name: sum(row["candidate"]["status"] == name for row in rag)  # type: ignore[index]
            for name in ("answered", "abstained", "error")
        },
        "accepted": accepted,
        "rejected": len(rag) - accepted,
        "acceptance_rate": round(accepted / len(rag), 6) if rag else None,
        "runtime_error_rate": 0.0 if rag else None,
        "mean_semantic_score": round(fmean(scores), 6) if scores else None,
        "components": _component_summary(rag),
        "behavior_checks": {
            "follow_up_success": {"eligible": 0, "passed": 0, "rate": None},
            "safe_abstention": {"eligible": 0, "passed": 0, "rate": None},
        },
        "deterministic_metrics": {
            "citation_valid": {"eligible": len(rag), "mean": 1.0}
        },
    }


def _partition(
    records: Sequence[Mapping[str, object]], key: str
) -> dict[str, dict[str, object]]:
    values: dict[str, list[Mapping[str, object]]] = {}
    for record in records:
        values.setdefault(str(record[key]), []).append(record)
    return {name: _group_summary(rows) for name, rows in sorted(values.items())}


def _parity_group(
    key: str,
    records: Sequence[Mapping[str, object]],
    *,
    primary_or_scenario: bool = True,
) -> dict[str, object]:
    group = _group_summary(records)
    group.update(
        {
            "key": key,
            "label": key,
            "meaning": f"synthetic meaning for {key}",
        }
    )
    if primary_or_scenario:
        group["failure"] = f"synthetic failure meaning for {key}"
    return group


def _synthetic_api_parity(
    records: Sequence[Mapping[str, object]],
    summary: Mapping[str, object],
) -> dict[str, object]:
    by_purpose: dict[str, list[Mapping[str, object]]] = {}
    for record in records:
        by_purpose.setdefault(str(record["purpose"]), []).append(record)
    scenarios = [
        record for record in records if str(record["purpose"]) in SCENARIO_CATEGORIES
    ]
    primary_rows = {
        "bid_rag_scenarios": scenarios,
        **{
            key: by_purpose[key]
            for key in PRIMARY_CATEGORIES - {"bid_rag_scenarios"}
        },
    }
    visual = by_purpose["visual_table_figure"]
    visual_rows = {
        "hwp_table": visual[:3],
        "hwp_figure": visual[3:5],
        "pdf_table": visual[5:8],
        "pdf_figure": visual[8:],
    }
    unavailable = {
        "value": None,
        "eligible": 0,
        "coverage": 0.0,
        "available": False,
        "reason": "synthetic_fixture_does_not_collect_common_metric",
    }
    common = {
        section: {name: dict(unavailable) for name in names}
        for section, names in EXPECTED_METRIC_KEYS.items()
    }
    first_rank = {
        "observed_count": 0,
        "mean": None,
        "median": None,
        "min": None,
        "max": None,
    }
    objective = {
        "required_document_hit_count": 76,
        "required_document_recall": 0.678571,
        "required_document_total": 112,
        "set_exact_match_rate": 0.538462,
        "set_case_count": 13,
        "set_macro_precision": 0.608974,
        "set_macro_recall": 0.692308,
        "set_macro_f1": 0.630769,
        "set_micro_precision": 0.809524,
        "set_micro_recall": 0.34,
        "set_micro_f1": 0.478873,
        "set_true_positive_total": 17,
        "set_false_positive_total": 4,
        "set_false_negative_total": 33,
        "visual_evidence_availability_rate": 0.0,
        "visual_case_count": 10,
        "visual_target_page": {
            "eligible_case_count": 10,
            "hit_count": 6,
            "hit_rate": 0.6,
            "first_rank": dict(first_rank),
        },
        "visual_target_chunk": {
            "eligible_case_count": 3,
            "hit_count": 0,
            "hit_rate": 0.0,
            "first_rank": dict(first_rank),
        },
        "visual_target_object_bridge": {
            "eligible_case_count": 10,
            "hit_count": 0,
            "hit_rate": 0.0,
            "first_rank": dict(first_rank),
        },
        "analytics_numeric_evidence_availability_rate": 0.0,
        "analytics_case_count": 10,
        "analytics_deterministic_companion_case_count": 10,
        "analytics_deterministic_companion_pass_count": 10,
        "analytics_deterministic_companion_complete_rate": 1.0,
        "analytics_deterministic_case_pass_count": 10,
        "analytics_deterministic_case_pass_rate": 1.0,
        "analytics_deterministic_field_count": 139,
        "analytics_deterministic_field_pass_count": 139,
        "analytics_deterministic_field_pass_rate": 1.0,
        "analytics_numeric_evidence_field_count": 0,
        "analytics_numeric_evidence_fields_per_case": {
            "observed_case_count": 0,
            "mean": None,
            "min": None,
            "max": None,
        },
        "unknown_safe_abstention_pass_count": 7,
        "unknown_case_count": 10,
        "unknown_safe_abstention_rate": 0.7,
    }
    comparisons: list[dict[str, object]] = []
    for record in records:
        semantic = record.get("semantic_evaluation")
        parser = record["asset_type"] == "parser"
        score = None if parser else semantic["score"]  # type: ignore[index]
        verdict = "parser_passed" if parser else semantic["verdict"]  # type: ignore[index]
        status = record["candidate"]["status"]  # type: ignore[index]
        comparisons.append(
            {
                "case_id": record["case_id"],
                "asset_type": record["asset_type"],
                "lane": record["lane"],
                "purpose": record["purpose"],
                "api_score": score,
                "local_score": score,
                "score_delta_local_minus_api": None if parser else 0.0,
                "api_verdict": verdict,
                "local_verdict": verdict,
                "verdict_changed": False,
                "api_status": status,
                "local_status": status,
                "status_changed": False,
            }
        )
    overall = summary["overall"]  # type: ignore[index]
    return {
        "primary_categories": _primary_category_summaries(records),
        "scenario_breakdown": _scenario_summaries(records),
        "visual_subgroups": _visual_subgroup_summaries(records),
        "objective_companion_metrics": _objective_companion_metrics(records),
        "common_evaluation_metrics": _common_evaluation_metrics(records),
        "api_reference": {
            "baseline_id": "mini131-bundle-v1",
            "generator": "gpt-5-mini",
            "mean_semantic_score": 54.845,
            "accepted": 58,
            "rejected": 71,
            "rag_count": 129,
            "parser_count": 2,
            "case_records_sha256": (
                "6d8b0cb9c1b393ad5b7bfc749e6f69bc2e3dbcff9f759860296d3ad4948fa87e"
            ),
            "receipt_sha256": (
                "dabae64574285bd0efc7bfd31a280ba573ca375f38037a713abae261c36b2c2b"
            ),
        },
        "local_candidate": {
            "suite_id": "gcp-local-kure-qwen3-8b-awq-mini131-v1",
            "generator": "qwen3.8:27b-mlx",
            "embedding": "nlpai-lab/KURE-v1",
            "execution_profile": "mac_local_equivalent",
            "mean_semantic_score": overall["mean_semantic_score"],
            "accepted": overall["accepted"],
            "rejected": overall["rejected"],
            "rag_count": 129,
            "parser_count": 2,
        },
        "case_identity": {
            "validated": True,
            "case_count": 131,
            "rag_case_count": 129,
            "parser_case_count": 2,
            "question_expected_lane_exact_match": True,
            "api_case_records_sha256": (
                "6d8b0cb9c1b393ad5b7bfc749e6f69bc2e3dbcff9f759860296d3ad4948fa87e"
            ),
            "api_receipt_sha256": (
                "dabae64574285bd0efc7bfd31a280ba573ca375f38037a713abae261c36b2c2b"
            ),
        },
        "same_item_comparison": {
            "case_count": 131,
            "rag_case_count": 129,
            "parser_case_count": 2,
            "mean_score_delta": 0.0,
            "local_higher_score": 0,
            "api_higher_score": 0,
            "equal_score": 129,
            "verdict_same": 131,
            "verdict_changed": 0,
            "status_same": 131,
            "status_changed": 0,
            "cases": comparisons,
        },
    }


def _synthetic_report() -> dict[str, object]:
    records: list[dict[str, object]] = []
    for index, (lane, purpose, difficulty) in enumerate(_plan(), start=1):
        accepted = index % 5 != 0
        question = PRIVATE_QUESTION if index == 1 else f"question {index}"
        expected = PRIVATE_EXPECTED if index == 1 else f"expected {index}"
        answer = PRIVATE_CANDIDATE if index == 1 else f"answer {index}"
        evidence = PRIVATE_EVIDENCE if index == 1 else f"evidence {index}"
        rationale = PRIVATE_RATIONALE if index == 1 else f"rationale {index}"
        records.append(
            {
                "schema_version": RECORD_SCHEMA_VERSION,
                "case_id": f"SYN-{index:03d}",
                "asset_type": "rag",
                "lane": lane,
                "purpose": purpose,
                "difficulty": difficulty,
                "official": False,
                "gold_review_status": "draft",
                "evaluation_status": {
                    "record_complete": True,
                    "quality_pass": accepted,
                    "gold_approved": False,
                    "official_eligible": False,
                },
                "question": question,
                "expected": {
                    "key_points": [{"text": expected}],
                    "required_doc_ids": ["DOC-SYN"],
                    "gold": {
                        "decision": "abstain" if purpose == "unknown" else "answer",
                        "abstain_reason": (
                            "not_in_corpus" if purpose == "unknown" else None
                        ),
                        "required_doc_ids": ["DOC-SYN"],
                        "required_key_points": [{"point_id": "POINT-SYN"}],
                        "evidence_refs": [
                            {
                                "doc_id": "DOC-SYN",
                                "source_block_id": "BLOCK-SYN",
                            }
                        ],
                    },
                },
                "candidate": {
                    "status": "answered",
                    "answer": answer,
                    "chat": [],
                    "citations": [
                        {
                            "doc_id": "DOC-SYN",
                            "source_block_ids": ["BLOCK-SYN"],
                        }
                    ],
                    "selected_doc_ids": ["DOC-SYN"],
                    "abstention_reason": None,
                    "error_code": None,
                },
                "retrieval": {
                    "retrieved_docs": [
                        {
                            "doc_id": "DOC-SYN",
                            "rank": 1,
                            "source_block_ids": ["BLOCK-SYN"],
                        }
                    ],
                    "cited_docs": [],
                    "evidence": [{"text": evidence}],
                },
                "deterministic_metrics": {
                    "case_id": f"SYN-{index:03d}",
                    "lane": lane,
                    "status": "answered",
                    "citation_valid": True,
                },
                "semantic_evaluation": {
                    "score": 100.0 if accepted else 50.0,
                    "verdict": "accepted" if accepted else "rejected",
                    "final_judge_role": "primary",
                    "component_scores": {
                        name: None if name == "abstention_quality" else 1.0
                        for name in COMPONENTS
                    },
                    "matched_key_point_ids": ["POINT-SYN"],
                    "follow_up_success": True,
                    "safe_abstention": False,
                    "rationale": rationale,
                    "judgment_history": [],
                },
                "source_transcript": {
                    "timing_ms": {"total": 10.0, "retrieval": 2.0, "generation": 8.0},
                    "usage": {"cost_usd": 0.0},
                },
                "provenance": {"source_case_sha256": "a" * 64},
            }
        )
    visual_records = [
        row for row in records if row["purpose"] == "visual_table_figure"
    ]
    visual_shapes = (
        [("hwp", "table")] * 3
        + [("hwp", "figure")] * 2
        + [("pdf", "table")] * 3
        + [("pdf", "figure")] * 2
    )
    for record, (document_format, evidence_type) in zip(
        visual_records, visual_shapes, strict=True
    ):
        record["expected"]["document_format"] = document_format  # type: ignore[index]
        record["expected"]["evidence_type"] = evidence_type  # type: ignore[index]
    for index in range(1, 3):
        records.append(
            {
                "schema_version": RECORD_SCHEMA_VERSION,
                "case_id": f"PARSER-{index:03d}",
                "asset_type": "parser",
                "lane": "parser_regression",
                "purpose": "parser_regression",
                "difficulty": "not_applicable",
                "official": False,
                "gold_review_status": "not_applicable",
                "evaluation_status": {
                    "record_complete": True,
                    "quality_pass": True,
                    "gold_approved": False,
                    "official_eligible": False,
                },
                "question": f"parser check {index}",
                "expected": {"invariant": "preserved"},
                "candidate": {"status": "passed", "answer": "PASS"},
                "retrieval": {"retrieved_docs": [], "cited_docs": [], "evidence": []},
                "deterministic_metrics": {"passed": True, "checks": {}},
                "semantic_evaluation": None,
                "source_transcript": {},
                "provenance": {"parser_rerun_sha256": "b" * 64},
            }
        )

    rag = [row for row in records if row["asset_type"] == "rag"]
    difficulty_counts = dict(sorted(Counter(row["difficulty"] for row in rag).items()))
    summary = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "suite_id": "gcp-local-kure-qwen3-8b-awq-mini131-v1",
        "official": False,
        "evaluation_tier": "provisional_non_official",
        "gold_review_status": "draft",
        "evaluation_status": {
            "record_complete": True,
            "quality_pass": False,
            "gold_approved": False,
            "official_eligible": False,
        },
        "overall": _group_summary(records),
        "counts": {
            "total_assets": 131,
            "rag": 129,
            "parser": 2,
            "parser_passed": 2,
            "difficulty": difficulty_counts,
        },
        "by_difficulty": _partition(rag, "difficulty"),
        "by_purpose": _partition(records, "purpose"),
        "by_lane": _partition(records, "lane"),
        "failure_case_ids": {"runtime_error": [], "semantic_rejected": []},
        "frozen_aggregate_metrics": {},
        "limitations": {
            "human_gold_approved": False,
            "held_out_executed": False,
            "live_gcp_executed": False,
            "candidate_runtime": "mac_ollama_numpy",
            "judge_is_gold": False,
            "unreported_frozen_metrics_remain": True,
        },
    }
    summary["api_parity"] = _synthetic_api_parity(records, summary)
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "suite_id": "gcp-local-kure-qwen3-8b-awq-mini131-v1",
        "official": False,
        "records": records,
        "summary": summary,
        "source_hashes": {
            "candidates_sha256": "1" * 64,
            "deterministic_score_sha256": "2" * 64,
            "semantic_score_sha256": "3" * 64,
            "review_history_sha256": "4" * 64,
            "parser_rerun_sha256": "5" * 64,
        },
    }
    validate_performance_evaluation(report)
    return report


class LocalMini131PerformanceUnitTests(unittest.TestCase):
    def test_schema_and_default_paths_are_frozen(self) -> None:
        self.assertEqual(
            RECORD_SCHEMA_VERSION,
            "local-mini131-golden-evaluation-record.v1",
        )
        self.assertEqual(
            SUMMARY_SCHEMA_VERSION,
            "local-mini131-golden-performance-summary.v2",
        )
        self.assertEqual(
            REPORT_SCHEMA_VERSION,
            "local-mini131-golden-performance-report.v2",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            suite = SimpleNamespace(
                private_judge_input_path=(
                    root / "evaluation/private/local-mini131/suite/blind-inputs.jsonl"
                ),
                public_receipt_path=(
                    root / "evaluation/baselines/suite/deterministic-receipt.json"
                ),
            )
            paths = default_paths(suite)
        expected_root = root / "evaluation/private/local-mini131/suite/performance-v1"
        self.assertEqual(paths.root, expected_root)
        self.assertEqual(paths.records.name, "golden-evaluation-records.jsonl")
        self.assertEqual(paths.summary.name, "golden-performance-summary.json")
        self.assertEqual(paths.html.name, "golden-performance-report.html")
        self.assertEqual(
            paths.receipt.name,
            "mac-local-equivalent-performance-receipt.json",
        )

    def test_incomplete_131_ledger_fails_closed(self) -> None:
        report = _synthetic_report()
        report["records"] = report["records"][:-1]
        with self.assertRaisesRegex(
            ValueError,
            "local_mini131_performance_record_count_mismatch",
        ):
            validate_performance_evaluation(report)

    def test_v2_report_requires_api_parity_and_unknown_purpose_taxonomy(self) -> None:
        report = _synthetic_report()
        report["summary"].pop("api_parity")
        with self.assertRaisesRegex(
            ValueError,
            "local_mini131_performance_api_parity_invalid",
        ):
            validate_performance_evaluation(report)

        report = _synthetic_report()
        unknown = next(
            row for row in report["records"] if row["purpose"] == "unknown"
        )
        unknown["purpose"] = "abstention"
        with self.assertRaisesRegex(
            ValueError,
            "local_mini131_performance_purpose_partition_mismatch",
        ):
            validate_performance_evaluation(report)

    def test_private_modes_content_free_receipt_and_aggregate_reconciliation(self) -> None:
        report = _synthetic_report()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private_root = root / "evaluation/private/local-mini131/suite/performance-v1"
            paths = PerformancePaths(
                root=private_root,
                records=private_root / "golden-evaluation-records.jsonl",
                summary=private_root / "golden-performance-summary.json",
                html=private_root / "golden-performance-report.html",
                receipt=root / "evaluation/baselines/suite/performance-receipt.json",
            )
            receipt = write_performance_outputs(report, paths)

            for output in (paths.records, paths.summary, paths.html):
                with self.subTest(output=output.name):
                    self.assertTrue(output.is_file())
                    self.assertFalse(output.is_symlink())
                    self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(paths.receipt.stat().st_mode), 0o644)
            self.assertEqual(
                json.loads(paths.receipt.read_text(encoding="utf-8")),
                receipt,
            )
            self.assertEqual(
                receipt["artifact_hashes"]["private_summary_sha256"],
                sha256_file(paths.summary),
            )

        expected_mean = round(
            fmean(
                float(row["semantic_evaluation"]["score"])
                for row in report["records"]
                if row["asset_type"] == "rag"
            ),
            6,
        )
        self.assertEqual(report["summary"]["overall"]["rag_count"], 129)
        self.assertEqual(
            report["summary"]["overall"]["mean_semantic_score"],
            expected_mean,
        )
        self.assertEqual(receipt["metrics"]["overall"], report["summary"]["overall"])
        self.assertEqual(receipt["counts"], report["summary"]["counts"])
        unexpected_private_paths = _unexpected_public_private_key_paths(receipt)
        self.assertFalse(unexpected_private_paths, unexpected_private_paths)
        serialized = canonical_json(receipt)
        for value in (
            PRIVATE_QUESTION,
            PRIVATE_EXPECTED,
            PRIVATE_CANDIDATE,
            PRIVATE_EVIDENCE,
            PRIVATE_RATIONALE,
        ):
            self.assertNotIn(value, serialized)
        for flag in (
            "contains_case_ids",
            "contains_questions",
            "contains_expected_answers",
            "contains_candidate_answers",
            "contains_evidence",
            "contains_judge_rationales",
            "contains_private_paths",
        ):
            self.assertIs(receipt["privacy"][flag], False)
        for groups in (
            report["summary"]["by_difficulty"],
            report["summary"]["by_purpose"],
            report["summary"]["by_lane"],
        ):
            self.assertTrue(all("rag_count" in group for group in groups.values()))
        self.assertTrue(
            all(
                "eligible" in component
                for component in report["summary"]["overall"]["components"].values()
            )
        )

    def test_private_output_boundary_rejects_outside_and_symlink_paths(self) -> None:
        report = _synthetic_report()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private_root = root / "evaluation/private/local-mini131/suite/performance-v1"
            outside = root / "outside"
            outside.mkdir()
            private_root.mkdir(parents=True)
            (private_root / "escape").symlink_to(outside, target_is_directory=True)
            unsafe_records = (
                outside / "records.jsonl",
                private_root / "escape/records.jsonl",
            )
            for records in unsafe_records:
                paths = PerformancePaths(
                    root=private_root,
                    records=records,
                    summary=private_root / "summary.json",
                    html=private_root / "report.html",
                    receipt=root / "evaluation/baselines/suite/receipt.json",
                )
                with self.subTest(records=str(records.relative_to(root))):
                    with self.assertRaisesRegex(
                        ValueError,
                        r"local_mini131_performance_output_(?:not_private|symlink_forbidden)",
                    ):
                        write_performance_outputs(report, paths)
            self.assertFalse((outside / "records.jsonl").exists())

    def test_public_receipt_allowlist_rejects_or_drops_injected_private_content(self) -> None:
        report = _synthetic_report()
        report["summary"]["overall"]["question"] = PRIVATE_QUESTION
        report["summary"]["limitations"]["rationale"] = PRIVATE_RATIONALE
        report["summary"]["api_parity"]["same_item_comparison"][
            "answer"
        ] = PRIVATE_CANDIDATE
        receipt = content_free_receipt(report, {"records_sha256": "a" * 64})
        serialized = canonical_json(receipt)
        self.assertNotIn(PRIVATE_QUESTION, serialized)
        self.assertNotIn(PRIVATE_RATIONALE, serialized)
        self.assertNotIn(PRIVATE_CANDIDATE, serialized)
        self.assertNotIn("question", _nested_keys(receipt))
        self.assertNotIn("rationale", _nested_keys(receipt))

        report["summary"]["overall"]["mean_semantic_score"] = PRIVATE_CANDIDATE
        with self.assertRaisesRegex(
            ValueError,
            "local_mini131_performance_public_metric_invalid",
        ):
            content_free_receipt(report, {"records_sha256": "a" * 64})

        report = _synthetic_report()
        report["summary"]["limitations"]["candidate_runtime"] = PRIVATE_EVIDENCE
        with self.assertRaisesRegex(
            ValueError,
            "local_mini131_performance_public_limitations_invalid",
        ):
            content_free_receipt(report, {"records_sha256": "a" * 64})

        with self.assertRaisesRegex(
            ValueError,
            "local_mini131_performance_public_hash_invalid",
        ):
            content_free_receipt(_synthetic_report(), {"question": PRIVATE_QUESTION})

    def test_public_receipt_nested_allowlists_fail_closed(self) -> None:
        report = _synthetic_report()
        report["summary"]["api_parity"]["objective_companion_metrics"][  # type: ignore[index]
            "operator_note"
        ] = PRIVATE_RATIONALE
        with self.assertRaisesRegex(
            ValueError,
            "local_mini131_performance_public_objective_invalid",
        ):
            content_free_receipt(report, {"records_sha256": "a" * 64})

        report = _synthetic_report()
        report["summary"]["overall"]["deterministic_metrics"][  # type: ignore[index]
            "operator_note"
        ] = {"eligible": 1, "mean": 1.0}
        with self.assertRaisesRegex(
            ValueError,
            "local_mini131_performance_public_metric_invalid",
        ):
            content_free_receipt(report, {"records_sha256": "a" * 64})

        report = _synthetic_report()
        report["summary"]["api_parity"]["primary_categories"][  # type: ignore[index]
            "bid_rag_scenarios"
        ]["label"] = PRIVATE_RATIONALE
        with self.assertRaisesRegex(
            ValueError,
            "local_mini131_performance_public_api_group_invalid",
        ):
            content_free_receipt(report, {"records_sha256": "a" * 64})

        report = _synthetic_report()
        report["summary"]["api_parity"]["common_evaluation_metrics"][  # type: ignore[index]
            "operations"
        ]["response_contract_error_rate"]["reason"] = PRIVATE_RATIONALE
        with self.assertRaisesRegex(
            ValueError,
            "local_mini131_performance_public_common_metric_invalid",
        ):
            content_free_receipt(report, {"records_sha256": "a" * 64})

    def test_api_parity_aggregates_reconcile_to_private_records(self) -> None:
        report = _synthetic_report()
        report["summary"]["api_parity"]["primary_categories"][  # type: ignore[index]
            "bid_rag_scenarios"
        ]["mean_semantic_score"] = 12.34
        with self.assertRaisesRegex(
            ValueError,
            "local_mini131_performance_api_partition_reconciliation_failed",
        ):
            validate_performance_evaluation(report)

        report = _synthetic_report()
        report["summary"]["api_parity"]["same_item_comparison"]["cases"][0][  # type: ignore[index]
            "local_score"
        ] = 9999
        with self.assertRaisesRegex(
            ValueError,
            "local_mini131_performance_same_item_case_invalid",
        ):
            validate_performance_evaluation(report)

        report = _synthetic_report()
        report["summary"]["api_parity"]["same_item_comparison"][  # type: ignore[index]
            "local_higher_score"
        ] = 129
        with self.assertRaisesRegex(
            ValueError,
            "local_mini131_performance_same_item_reconciliation_failed",
        ):
            validate_performance_evaluation(report)

    def test_html_escapes_content_and_has_131_static_filterable_cards(self) -> None:
        rendered = render_html(_synthetic_report())
        self.assertIn("&lt;script&gt;privateQuestion()&lt;/script&gt;", rendered)
        self.assertNotIn(PRIVATE_QUESTION, rendered)
        self.assertEqual(
            len(re.findall(r'class="[^"]*\bcase\b[^"]*"', rendered)),
            131,
        )
        for control_id in ("search", "difficulty", "lane", "purpose", "verdict"):
            self.assertIn(f'id="{control_id}"', rendered)
        for attribute in (
            "data-difficulty=",
            "data-purpose=",
            "data-lane=",
            "data-verdict=",
        ):
            self.assertIn(attribute, rendered)
        self.assertNotRegex(rendered, r'(?i)<script[^>]+src=["\']https?://')
        self.assertNotRegex(rendered, r'(?i)<link[^>]+href=["\']https?://')


class LocalMini131PerformancePrivateIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[2]
        config_path = cls.repo_root / DEFAULT_CONFIG
        if not config_path.is_file():
            raise unittest.SkipTest("canonical private Mini131 artifacts unavailable")
        try:
            cls.suite = verify_suite(
                repo_root=cls.repo_root,
                config_path=config_path,
            )
        except FileNotFoundError as error:
            raise unittest.SkipTest(
                "canonical private Mini131 artifacts unavailable"
            ) from error
        paths = semantic_default_paths(cls.suite)
        cls.decision_paths = [
            paths.review_root / "primary-decisions-1.jsonl",
            paths.review_root / "primary-decisions-2.jsonl",
            paths.review_root / "primary-decisions-3.jsonl",
            paths.review_root / "secondary-decisions.jsonl",
            paths.review_root / "adjudicator-decisions.jsonl",
        ]
        required = [
            paths.candidates,
            paths.deterministic_score,
            paths.semantic_score,
            paths.review_inputs,
            paths.review_map,
            paths.review_root / "review-history.jsonl",
            paths.candidates.with_name("parser-rerun.json"),
            *cls.decision_paths,
        ]
        cls.api_case_records_path = (
            cls.repo_root
            / "evaluation/private/supplemental/runs/provisional-v1/case-records.jsonl"
        )
        cls.api_receipt_path = (
            cls.repo_root / "evaluation/baselines/mini131-bundle-v1/receipt.json"
        )
        required.extend([cls.api_case_records_path, cls.api_receipt_path])
        if any(not path.is_file() for path in required):
            raise unittest.SkipTest("canonical private Mini131 artifacts unavailable")
        try:
            cls.ledger = load_ledger(cls.suite)
        except PermissionError as error:
            raise unittest.SkipTest(
                "canonical private Mini131 artifacts are unavailable in this sandbox"
            ) from error
        cls.report = build_performance_evaluation(cls.ledger, cls.decision_paths)
        cls.api_records = read_jsonl(cls.api_case_records_path)
        cls.api_receipt = json.loads(
            cls.api_receipt_path.read_text(encoding="utf-8")
        )

    def test_api_and_local_use_the_exact_same_131_question_expected_lane_set(self) -> None:
        local_by_id = {row["case_id"]: row for row in self.report["records"]}
        api_by_id = {row["case_id"]: row for row in self.api_records}
        self.assertEqual(len(local_by_id), 131)
        self.assertEqual(set(local_by_id), set(api_by_id))
        for case_id in sorted(api_by_id):
            with self.subTest(case_id=case_id):
                api = api_by_id[case_id]
                local = local_by_id[case_id]
                self.assertEqual(local["question"], api["question"])
                self.assertEqual(local["expected"], api["expected"])
                self.assertEqual(local["lane"], api["lane"])
                self.assertEqual(local["asset_type"], api["case_type"])

        identity = self.report["summary"]["api_parity"]["case_identity"]
        self.assertEqual(
            set(identity),
            {
                "validated",
                "case_count",
                "rag_case_count",
                "parser_case_count",
                "question_expected_lane_exact_match",
                "api_case_records_sha256",
                "api_receipt_sha256",
            },
        )
        self.assertIs(identity["validated"], True)
        self.assertIs(identity["question_expected_lane_exact_match"], True)
        self.assertEqual(
            (identity["case_count"], identity["rag_case_count"], identity["parser_case_count"]),
            (131, 129, 2),
        )
        self.assertEqual(
            identity["api_case_records_sha256"],
            sha256_file(self.api_case_records_path),
        )
        self.assertEqual(
            identity["api_receipt_sha256"],
            sha256_file(self.api_receipt_path),
        )

    def test_api_parity_taxonomy_uses_seven_primary_four_scenario_and_four_visual_groups(self) -> None:
        parity = self.report["summary"]["api_parity"]
        self.assertEqual(set(parity), API_PARITY_KEYS)
        self.assertEqual(set(parity["primary_categories"]), PRIMARY_CATEGORIES)
        self.assertEqual(set(parity["scenario_breakdown"]), SCENARIO_CATEGORIES)
        self.assertEqual(set(parity["visual_subgroups"]), VISUAL_SUBGROUPS)
        self.assertEqual(
            {
                name: group["count"]
                for name, group in parity["primary_categories"].items()
            },
            {
                "bid_rag_scenarios": 40,
                "clause_fact_regression": 44,
                "conditional_all_list": 13,
                "gold_source_alignment": 12,
                "visual_table_figure": 10,
                "corpus_analytics": 10,
                "parser_regression": 2,
            },
        )
        self.assertEqual(
            {
                name: group["count"]
                for name, group in parity["scenario_breakdown"].items()
            },
            {name: 10 for name in SCENARIO_CATEGORIES},
        )
        self.assertEqual(
            {
                name: (
                    group["mean_semantic_score"],
                    group["accepted"],
                    group["rejected"],
                )
                for name, group in parity["scenario_breakdown"].items()
            },
            {
                "single_doc": (90.75, 8, 2),
                "multi_doc_compare": (55.75, 5, 5),
                "follow_up": (78.0, 8, 2),
                "unknown": (70.0, 7, 3),
            },
        )
        self.assertEqual(
            {
                name: group["count"]
                for name, group in parity["visual_subgroups"].items()
            },
            {"hwp_table": 3, "hwp_figure": 2, "pdf_table": 3, "pdf_figure": 2},
        )
        self.assertEqual(
            {
                name: (
                    group["mean_semantic_score"],
                    group["accepted"],
                    group["rejected"],
                )
                for name, group in parity["visual_subgroups"].items()
            },
            {
                "hwp_table": (66.67, 2, 1),
                "hwp_figure": (0.0, 0, 2),
                "pdf_table": (96.67, 3, 0),
                "pdf_figure": (0.0, 0, 2),
            },
        )
        rag_purposes = {
            row["purpose"]
            for row in self.report["records"]
            if row["asset_type"] == "rag"
        }
        self.assertIn("unknown", rag_purposes)
        self.assertNotIn("abstention", rag_purposes)
        self.assertEqual(
            sum(
                row["purpose"] == "unknown"
                for row in self.report["records"]
                if row["asset_type"] == "rag"
            ),
            10,
        )

    def test_api_and_local_reference_summaries_are_labeled_for_same_item_comparison(self) -> None:
        parity = self.report["summary"]["api_parity"]
        api = parity["api_reference"]
        local = parity["local_candidate"]
        self.assertEqual(
            set(api),
            {
                "baseline_id",
                "generator",
                "mean_semantic_score",
                "accepted",
                "rejected",
                "rag_count",
                "parser_count",
                "case_records_sha256",
                "receipt_sha256",
            },
        )
        self.assertEqual(api["baseline_id"], "mini131-bundle-v1")
        self.assertEqual(api["generator"], "gpt-5-mini")
        self.assertEqual(api["mean_semantic_score"], 54.845)
        self.assertEqual((api["accepted"], api["rejected"]), (58, 71))
        self.assertEqual((api["rag_count"], api["parser_count"]), (129, 2))
        self.assertEqual(api["case_records_sha256"], sha256_file(self.api_case_records_path))
        self.assertEqual(api["receipt_sha256"], sha256_file(self.api_receipt_path))
        self.assertEqual(
            set(local),
            {
                "suite_id",
                "generator",
                "embedding",
                "execution_profile",
                "mean_semantic_score",
                "accepted",
                "rejected",
                "rag_count",
                "parser_count",
            },
        )
        self.assertEqual(local["suite_id"], self.report["suite_id"])
        self.assertEqual(local["generator"], "qwen3.8:27b-mlx")
        self.assertEqual(local["embedding"], "nlpai-lab/KURE-v1")
        self.assertEqual(local["execution_profile"], "mac_local_equivalent")
        self.assertEqual(local["mean_semantic_score"], 70.135659)
        self.assertEqual((local["accepted"], local["rejected"]), (88, 41))
        self.assertEqual((local["rag_count"], local["parser_count"]), (129, 2))

    def test_local_semantic_score_uses_the_same_api_formula_and_component_items(self) -> None:
        for row in self.report["records"]:
            if row["asset_type"] != "rag":
                continue
            with self.subTest(case_id=row["case_id"]):
                semantic = row["semantic_evaluation"]
                components = semantic["component_scores"]
                self.assertEqual(set(components), COMPONENTS)
                abstention_quality = components["abstention_quality"]
                if abstention_quality is not None:
                    expected_score = round(100.0 * float(abstention_quality), 2)
                    self.assertTrue(all(
                        components[name] is None
                        for name in COMPONENTS - {"abstention_quality"}
                    ))
                else:
                    expected_score = round(
                        100.0
                        * (
                            0.35 * float(components["correctness"])
                            + 0.25 * float(components["faithfulness"])
                            + 0.20 * float(components["completeness"])
                            + 0.10 * float(components["factual_claim_coverage"])
                            + 0.10 * float(components["citation_validity"])
                        ),
                        2,
                    )
                self.assertEqual(float(semantic["score"]), expected_score)

    def test_objective_companion_metrics_keep_api_denominators_and_local_values(self) -> None:
        metrics = self.report["summary"]["api_parity"][
            "objective_companion_metrics"
        ]
        self.assertEqual(metrics["required_document_hit_count"], 76)
        self.assertEqual(metrics["required_document_total"], 112)
        self.assertEqual(metrics["required_document_recall"], 0.678571)
        self.assertEqual(metrics["set_case_count"], 13)
        self.assertEqual(metrics["set_exact_match_rate"], 0.538462)
        self.assertEqual(metrics["set_macro_precision"], 0.608974)
        self.assertEqual(metrics["set_macro_recall"], 0.692308)
        self.assertEqual(metrics["set_macro_f1"], 0.630769)
        self.assertEqual(metrics["set_micro_precision"], 0.809524)
        self.assertEqual(metrics["set_micro_recall"], 0.34)
        self.assertEqual(metrics["set_micro_f1"], 0.478873)
        self.assertEqual(metrics["set_true_positive_total"], 17)
        self.assertEqual(metrics["set_false_positive_total"], 4)
        self.assertEqual(metrics["set_false_negative_total"], 33)
        for name, expected in {
            "visual_target_page": (6, 10, 0.6),
            "visual_target_chunk": (0, 3, 0.0),
            "visual_target_object_bridge": (0, 10, 0.0),
        }.items():
            with self.subTest(metric=name):
                self.assertEqual(
                    (
                        metrics[name]["hit_count"],
                        metrics[name]["eligible_case_count"],
                        metrics[name]["hit_rate"],
                    ),
                    expected,
                )
        self.assertEqual(metrics["analytics_deterministic_field_pass_count"], 139)
        self.assertEqual(metrics["analytics_deterministic_field_count"], 139)
        self.assertEqual(metrics["analytics_deterministic_field_pass_rate"], 1.0)
        self.assertEqual(metrics["unknown_safe_abstention_pass_count"], 7)
        self.assertEqual(metrics["unknown_case_count"], 10)
        self.assertEqual(metrics["unknown_safe_abstention_rate"], 0.7)

    def test_common_evaluation_metrics_match_the_api_keyset_and_explain_nulls(self) -> None:
        common = self.report["summary"]["api_parity"][
            "common_evaluation_metrics"
        ]
        self.assertEqual(set(common), set(EXPECTED_METRIC_KEYS))
        unavailable = 0
        for section, expected_names in EXPECTED_METRIC_KEYS.items():
            self.assertEqual(set(common[section]), set(expected_names))
            for name, entry in common[section].items():
                with self.subTest(section=section, metric=name):
                    self.assertEqual(set(entry), COMMON_METRIC_ENTRY_KEYS)
                    self.assertIsInstance(entry["eligible"], int)
                    self.assertNotIsInstance(entry["eligible"], bool)
                    self.assertGreaterEqual(entry["eligible"], 0)
                    self.assertIsInstance(entry["coverage"], (int, float))
                    self.assertNotIsInstance(entry["coverage"], bool)
                    self.assertTrue(math.isfinite(float(entry["coverage"])))
                    self.assertGreaterEqual(float(entry["coverage"]), 0.0)
                    self.assertLessEqual(float(entry["coverage"]), 1.0)
                    self.assertIsInstance(entry["available"], bool)
                    if entry["available"]:
                        self.assertIsInstance(entry["value"], (int, float))
                        self.assertNotIsInstance(entry["value"], bool)
                        self.assertTrue(math.isfinite(float(entry["value"])))
                        self.assertIsNone(entry["reason"])
                    else:
                        unavailable += 1
                        self.assertIsNone(entry["value"])
                        self.assertIsInstance(entry["reason"], str)
                        self.assertTrue(entry["reason"].strip())
        self.assertGreater(unavailable, 0)
        response_contract = common["operations"]["response_contract_error_rate"]
        self.assertIs(response_contract["available"], False)
        self.assertIsNone(response_contract["value"])
        self.assertEqual(response_contract["eligible"], 0)
        self.assertEqual(response_contract["coverage"], 0.0)
        self.assertEqual(
            response_contract["reason"],
            "local_candidate_response_not_normalized_to_api_contract",
        )

    def test_same_item_comparison_and_parser_boundary_are_explicit(self) -> None:
        parity = self.report["summary"]["api_parity"]
        comparison = parity["same_item_comparison"]
        self.assertEqual(
            (comparison["case_count"], comparison["rag_case_count"], comparison["parser_case_count"]),
            (131, 129, 2),
        )
        self.assertEqual(
            comparison["local_higher_score"]
            + comparison["api_higher_score"]
            + comparison["equal_score"],
            129,
        )
        self.assertEqual(
            (
                comparison["local_higher_score"],
                comparison["api_higher_score"],
                comparison["equal_score"],
            ),
            (41, 26, 62),
        )
        self.assertEqual(comparison["mean_score_delta"], 15.290698)
        self.assertEqual(
            comparison["verdict_same"] + comparison["verdict_changed"],
            131,
        )
        self.assertEqual(
            (comparison["verdict_same"], comparison["verdict_changed"]),
            (91, 40),
        )
        self.assertEqual(
            comparison["status_same"] + comparison["status_changed"],
            131,
        )
        self.assertEqual(
            (comparison["status_same"], comparison["status_changed"]),
            (100, 31),
        )
        self.assertEqual(len(comparison["cases"]), 131)
        expected_case_fields = {
            "case_id",
            "asset_type",
            "lane",
            "purpose",
            "api_score",
            "local_score",
            "score_delta_local_minus_api",
            "api_verdict",
            "local_verdict",
            "verdict_changed",
            "api_status",
            "local_status",
            "status_changed",
        }
        self.assertTrue(
            all(set(row) == expected_case_fields for row in comparison["cases"])
        )
        self.assertEqual(
            {row["case_id"] for row in comparison["cases"]},
            {row["case_id"] for row in self.report["records"]},
        )
        parser_rows = [
            row for row in comparison["cases"] if row["asset_type"] == "parser"
        ]
        self.assertEqual(len(parser_rows), 2)
        self.assertTrue(all(row["api_score"] is None for row in parser_rows))
        self.assertTrue(all(row["local_score"] is None for row in parser_rows))
        self.assertTrue(
            all(
                row["score_delta_local_minus_api"] is None
                for row in parser_rows
            )
        )
        self.assertEqual(parity["primary_categories"]["parser_regression"]["count"], 2)
        self.assertIsNone(
            parity["primary_categories"]["parser_regression"][
                "mean_semantic_score"
            ]
        )

    def test_public_receipt_keeps_aggregate_parity_and_drops_private_comparison_rows(self) -> None:
        receipt = content_free_receipt(
            self.report,
            {"private_records_sha256": "a" * 64},
        )
        public = receipt["metrics"]["api_parity"]
        self.assertEqual(set(public), API_PARITY_KEYS)
        self.assertNotIn("cases", public["same_item_comparison"])
        self.assertEqual(public["same_item_comparison"]["case_count"], 131)
        self.assertEqual(public["same_item_comparison"]["rag_case_count"], 129)
        self.assertEqual(public["same_item_comparison"]["parser_case_count"], 2)
        self.assertEqual(
            set(public["common_evaluation_metrics"]),
            set(EXPECTED_METRIC_KEYS),
        )
        unexpected_private_paths = _unexpected_public_private_key_paths(receipt)
        self.assertFalse(unexpected_private_paths, unexpected_private_paths)

    def test_html_mirrors_api_sections_tables_and_filter_controls(self) -> None:
        rendered = render_html(self.report)
        for section_id in (
            "question-set-scope",
            "primary-category-results",
            "core40-scenario-results",
            "visual-subgroup-results",
            "common-metric-results",
            "api-vs-local-results",
            "overall-reference",
            "per-case-records",
        ):
            self.assertIn(f'id="{section_id}"', rendered)
        for control_id in (
            "search",
            "difficulty",
            "purpose",
            "lane",
            "asset-type",
            "execution-lineage",
            "verdict",
            "failures",
            "visible",
        ):
            self.assertEqual(rendered.count(f'id="{control_id}"'), 1)
        for heading in (
            "질문셋 출처와 평가 분모",
            "평가 목적별 결과",
            "입찰 RAG 시나리오 40 상세",
            "HWP/PDF 표·그림 10 상세",
            "공통 평가 지표",
            "API 기준선과 로컬 후보 동일 문항 비교",
            "문항별 상세 기록",
        ):
            self.assertIn(heading, rendered)
        for attribute in (
            "data-purpose=",
            "data-lane=",
            "data-type=",
            "data-lineage=",
            "data-verdict=",
            "data-failure=",
            "data-difficulty=",
        ):
            self.assertIn(attribute, rendered)
        self.assertNotIn('data-purpose="abstention"', rendered)
        self.assertIn('data-purpose="unknown"', rendered)

    def test_exact_131_join_difficulty_and_per_case_score_contract(self) -> None:
        records = self.report["records"]
        self.assertEqual(len(records), 131)
        self.assertEqual(len({row["case_id"] for row in records}), 131)
        self.assertEqual(
            Counter(row["asset_type"] for row in records),
            Counter({"rag": 129, "parser": 2}),
        )
        rag = [row for row in records if row["asset_type"] == "rag"]
        self.assertEqual(
            Counter(row["difficulty"] for row in rag),
            Counter({"easy": 41, "medium": 48, "hard": 40}),
        )
        for row in rag:
            with self.subTest(case_type="rag"):
                self.assertTrue(row["question"])
                self.assertIsNotNone(row["expected"])
                self.assertIn("answer", row["candidate"])
                self.assertIsInstance(row["retrieval"]["evidence"], list)
                self.assertIsInstance(row["deterministic_metrics"], Mapping)
                semantic = row["semantic_evaluation"]
                self.assertIsInstance(semantic["score"], (int, float))
                self.assertIn(semantic["verdict"], {"accepted", "rejected"})
                self.assertTrue(semantic["rationale"])
                self.assertEqual(set(semantic["component_scores"]), COMPONENTS)
                self.assertTrue(row["evaluation_status"]["record_complete"])
                self.assertFalse(row["evaluation_status"]["official_eligible"])
        self.assertTrue(
            all(
                row["semantic_evaluation"] is None
                and row["deterministic_metrics"]["passed"] is True
                for row in records
                if row["asset_type"] == "parser"
            )
        )

        summary = self.report["summary"]
        self.assertEqual(summary["counts"]["difficulty"], {
            "easy": 41,
            "medium": 48,
            "hard": 40,
        })
        self.assertEqual(
            {name: group["count"] for name, group in summary["by_purpose"].items()},
            {
                "unknown": 10,
                "clause_fact_regression": 44,
                "conditional_all_list": 13,
                "corpus_analytics": 10,
                "follow_up": 10,
                "gold_source_alignment": 12,
                "multi_doc_compare": 10,
                "parser_regression": 2,
                "single_doc": 10,
                "visual_table_figure": 10,
            },
        )
        self.assertTrue(summary["evaluation_status"]["record_complete"])
        self.assertFalse(summary["evaluation_status"]["quality_pass"])
        self.assertFalse(summary["official"])

    def test_final_adjudicator_and_aggregate_reconciliation(self) -> None:
        finals, histories, workflows = resolve_final_judgments(
            self.ledger,
            self.decision_paths,
        )
        adjudicated = [
            case_id
            for case_id, final in finals.items()
            if final["judge_role"] == "adjudicator"
        ]
        self.assertGreater(len(adjudicated), 0)
        for case_id in adjudicated:
            self.assertEqual(histories[case_id][-1]["judge_role"], "adjudicator")
            self.assertTrue(workflows[case_id]["adjudicator_required"])
            self.assertEqual(
                workflows[case_id]["final_judgment_id"],
                finals[case_id]["judgment_id"],
            )

        canonical = json.loads(
            self.ledger.paths.semantic_score.read_text(encoding="utf-8")
        )
        overall = self.report["summary"]["overall"]
        self.assertEqual(
            overall["mean_semantic_score"],
            canonical["metrics"]["mean_semantic_score"],
        )
        self.assertEqual(overall["accepted"], canonical["counts"]["accepted"])
        self.assertEqual(overall["rejected"], canonical["counts"]["rejected"])

    def test_deterministic_lane_mismatch_fails_closed(self) -> None:
        deterministic = json.loads(
            self.ledger.paths.deterministic_score.read_text(encoding="utf-8")
        )
        deterministic["per_case"][0]["lane"] = "tampered-lane"
        with tempfile.TemporaryDirectory() as directory:
            tampered = Path(directory) / "evaluation/private/tampered-score.json"
            _write_private(tampered, deterministic)
            paths = replace(self.ledger.paths, deterministic_score=tampered)
            ledger = replace(
                self.ledger,
                paths=paths,
                deterministic_score_sha256=sha256_file(tampered),
            )
            with self.assertRaisesRegex(
                ValueError,
                "local_mini131_performance_deterministic_binding_mismatch",
            ):
                build_performance_evaluation(ledger, self.decision_paths)

    def test_parser_rerun_must_match_frozen_receipt_exactly(self) -> None:
        source = self.ledger.paths.candidates.with_name("parser-rerun.json")
        payload = json.loads(source.read_text(encoding="utf-8"))
        payload["result"]["cases"][0]["observed"]["tampered"] = True
        with tempfile.TemporaryDirectory() as directory:
            private_root = (
                Path(directory)
                / "resources/data_refined/private/outputs/local/suite/run"
            )
            candidate_path = private_root / "candidates.jsonl"
            _write_private(candidate_path.with_name("parser-rerun.json"), payload)
            paths = replace(self.ledger.paths, candidates=candidate_path)
            ledger = replace(self.ledger, paths=paths)
            with self.assertRaisesRegex(
                ValueError,
                "local_mini131_performance_parser_rerun_invalid",
            ):
                _load_parser_results(ledger)

    def test_review_history_must_match_all_raw_decisions(self) -> None:
        history = read_jsonl(self.ledger.paths.review_root / "review-history.jsonl")
        history[0]["review_output"]["rationale"] += " tampered"
        history[0]["output_sha256"] = sha256_text(
            canonical_json(history[0]["review_output"])
        )
        history_without_hash = copy.deepcopy(history[0])
        history_without_hash.pop("history_sha256")
        history[0]["history_sha256"] = sha256_text(
            canonical_json(history_without_hash)
        )
        with tempfile.TemporaryDirectory() as directory:
            review_root = Path(directory) / "evaluation/private/review"
            decision_paths: list[Path] = []
            for source in self.decision_paths:
                target = review_root / source.name
                rows = read_jsonl(source)
                _write_private_jsonl(target, rows)
                decision_paths.append(target)
            _write_private_jsonl(review_root / "review-history.jsonl", history)
            paths = replace(self.ledger.paths, review_root=review_root)
            ledger = replace(self.ledger, paths=paths)
            with self.assertRaisesRegex(
                ValueError,
                "local_mini131_performance_review_history_decision_mismatch",
            ):
                resolve_final_judgments(ledger, decision_paths)


if __name__ == "__main__":
    unittest.main()
