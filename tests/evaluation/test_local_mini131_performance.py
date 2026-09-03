from __future__ import annotations

import copy
import json
import unittest
from collections.abc import Mapping
from pathlib import Path

from midprojectrag.eval_contracts.mini131.scorecard import SCORECARD_CONTRACT_PATH
from midprojectrag.evaluation import EXPECTED_METRIC_KEYS
from midprojectrag.ingest.common import read_jsonl, sha256_file
from midprojectrag.local_mini131_performance import (
    EXPECTED_DIFFICULTY_COUNTS,
    EXPECTED_PRIMARY_COUNTS,
    EXPECTED_VISUAL_SUBGROUP_COUNTS,
    REPORT_SCHEMA_VERSION,
    SCENARIO_KEYS,
    build_summary,
    content_free_receipt,
    render_html,
    validate_performance_evaluation,
)


ROOT = Path(__file__).resolve().parents[2]
RECORDS = (
    ROOT
    / "evaluation/private/local-mini131"
    / "gcp-local-kure-qwen3-8b-awq-mini131-v1"
    / "performance-v1/golden-evaluation-records.jsonl"
)
FORBIDDEN_KEYS = {
    "api" + "_reference",
    "same_item" + "_comparison",
    "api" + "_parity",
    "api_case_records" + "_sha256",
    "api_receipt" + "_sha256",
}


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


@unittest.skipUnless(RECORDS.is_file(), "private local Mini131 records unavailable")
class LocalMini131PerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records = read_jsonl(RECORDS)
        cls.summary = build_summary(cls.records)
        cls.report = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "suite_id": "gcp-local-kure-qwen3-8b-awq-mini131-v1",
            "official": False,
            "records": cls.records,
            "summary": cls.summary,
            "source_hashes": {"local_records_input_sha256": sha256_file(RECORDS)},
        }

    def test_local_only_report_is_complete_and_reconciled(self) -> None:
        validate_performance_evaluation(self.report)
        self.assertEqual(self.summary["counts"]["total_assets"], 131)
        self.assertEqual(self.summary["counts"]["difficulty"], EXPECTED_DIFFICULTY_COUNTS)
        self.assertEqual(self.summary["counts"]["parser_passed"], 2)
        self.assertEqual(self.summary["overall"]["mean_semantic_score"], 70.135659)
        self.assertEqual(
            (self.summary["overall"]["accepted"], self.summary["overall"]["rejected"]),
            (88, 41),
        )

    def test_scorecard_keeps_shared_categories_without_provider_results(self) -> None:
        scorecard = self.summary["scorecard"]
        self.assertEqual(
            {key: value["count"] for key, value in scorecard["primary_categories"].items()},
            EXPECTED_PRIMARY_COUNTS,
        )
        self.assertEqual(
            {key: scorecard["scenario_breakdown"][key]["count"] for key in SCENARIO_KEYS},
            {key: 10 for key in SCENARIO_KEYS},
        )
        self.assertEqual(
            {key: value["count"] for key, value in scorecard["visual_subgroups"].items()},
            EXPECTED_VISUAL_SUBGROUP_COUNTS,
        )
        self.assertEqual(
            {
                section: set(metrics)
                for section, metrics in scorecard["common_evaluation_metrics"].items()
            },
            {section: set(keys) for section, keys in EXPECTED_METRIC_KEYS.items()},
        )
        self.assertFalse(FORBIDDEN_KEYS & _nested_keys(self.report))

    def test_html_is_local_only(self) -> None:
        rendered = render_html(self.report)
        self.assertIn("Local Qwen Mini131 성능평가", rendered)
        self.assertIn('id="local-candidate-results"', rendered)
        self.assertIn('id="reproduction-stack"', rendered)
        self.assertIn("nlpai-lab/KURE-v1", rendered)
        self.assertIn("qwen3.8:27b-mlx", rendered)
        self.assertIn("Qwen/Qwen3-8B-AWQ", rendered)
        self.assertIn("vLLM 0.8.5.post1", rendered)
        self.assertIn("page-v1 9,331 chunks", rendered)
        self.assertIn("midprojectrag.local_mini131_baseline", rendered)
        self.assertIn("mac_local_equivalent", rendered)
        self.assertNotIn("동일 문항 비교", rendered)
        self.assertNotIn("api-vs-local-results", rendered)

    def test_public_receipt_is_content_free_and_contract_bound(self) -> None:
        digest = sha256_file(ROOT / SCORECARD_CONTRACT_PATH)
        receipt = content_free_receipt(
            self.report,
            {
                "private_records_sha256": "1" * 64,
                "private_summary_sha256": "2" * 64,
                "private_html_sha256": "3" * 64,
                "local_records_input_sha256": sha256_file(RECORDS),
                "scorecard_contract_sha256": digest,
            },
        )
        self.assertEqual(receipt["scorecard_contract_sha256"], digest)
        self.assertEqual(receipt["metrics"]["scorecard"]["local_candidate"]["accepted"], 88)
        self.assertFalse(FORBIDDEN_KEYS & _nested_keys(receipt))
        serialized = json.dumps(receipt, ensure_ascii=False)
        self.assertNotIn(str(self.records[0]["case_id"]), serialized)
        self.assertNotIn(str(self.records[0]["question"]), serialized)

    def test_scorecard_tampering_fails_closed(self) -> None:
        report = copy.deepcopy(self.report)
        report["summary"]["scorecard"]["primary_categories"]["bid_rag_scenarios"]["count"] = 39
        with self.assertRaisesRegex(
            ValueError, "local_mini131_performance_scorecard_partition_invalid"
        ):
            validate_performance_evaluation(report)


if __name__ == "__main__":
    unittest.main()
