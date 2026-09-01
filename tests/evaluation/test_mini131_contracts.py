from __future__ import annotations

import json
import unittest
from pathlib import Path

from midprojectrag import mini131_bundle, mini131_report
from midprojectrag.eval_contracts.mini131.judge import (
    JUDGE_ROLES,
    JUDGE_WEIGHTS,
    ROLE_DECISIONS,
    expected_judge_config,
    judgment_semantic_score,
)
from midprojectrag.eval_contracts.mini131.scorecard import (
    SCORECARD_CONTRACT_PATH,
    expected_contract,
    validate_contract,
)
from midprojectrag.eval_contracts.mini131.taxonomy import (
    PRIMARY_CATEGORY_ORDER,
    SCENARIO_PURPOSES,
    VISUAL_SUBGROUP_DEFINITIONS,
)
from midprojectrag.evaluation import EXPECTED_METRIC_KEYS
from midprojectrag.ingest.common import sha256_file


ROOT = Path(__file__).resolve().parents[2]


class Mini131ContractsTest(unittest.TestCase):
    def test_scorecard_json_is_exact_provider_neutral_contract(self) -> None:
        path = ROOT / SCORECARD_CONTRACT_PATH
        value = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(validate_contract(value), expected_contract())
        self.assertRegex(sha256_file(path), r"^[0-9a-f]{64}$")

    def test_judge_config_is_exact_and_has_no_provider_run_paths(self) -> None:
        path = ROOT / "evaluation/contracts/mini131/judge-config.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        rubric = ROOT / "evaluation/rubric.md"
        self.assertEqual(value, expected_judge_config(sha256_file(rubric)))
        serialized = json.dumps(value, sort_keys=True)
        self.assertNotIn("baselines/", serialized)
        self.assertNotIn("evaluation/private/", serialized)

    def test_api_judge_config_is_neutral_contract_plus_private_io_only(self) -> None:
        path = ROOT / "evaluation/baselines/mini131-bundle-v1/judge-config.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        review_io = value.pop("review_io")
        rubric = ROOT / "evaluation/rubric.md"

        self.assertEqual(value, expected_judge_config(sha256_file(rubric)))
        self.assertEqual(
            set(review_io),
            {
                "allowed_inputs",
                "forbidden_inputs",
                "blind_decision_schema_version",
                "review_history_schema_version",
            },
        )
        self.assertIn("evaluation/private/mini131/", json.dumps(review_io))

    def test_api_runner_and_report_bind_the_neutral_judge_contract(self) -> None:
        self.assertIs(mini131_bundle.JUDGE_WEIGHTS, JUDGE_WEIGHTS)
        self.assertEqual(mini131_report.ANSWER_SCORE_FIELDS, tuple(JUDGE_WEIGHTS))
        self.assertEqual(mini131_report.JUDGE_ROLES, set(JUDGE_ROLES))
        self.assertEqual(
            mini131_report.ROLE_DECISIONS,
            {role: set(decisions) for role, decisions in ROLE_DECISIONS.items()},
        )
        judgment = {
            "scores": {
                **{field: 1.0 for field in JUDGE_WEIGHTS},
                "abstention_quality": None,
            }
        }
        self.assertEqual(
            mini131_report._score_from_judgment(judgment),
            judgment_semantic_score(judgment),
        )

    def test_scorecard_has_exact_7_4_4_taxonomy_and_metric_keyset(self) -> None:
        contract = expected_contract()
        self.assertEqual(len(PRIMARY_CATEGORY_ORDER), 7)
        self.assertEqual(len(SCENARIO_PURPOSES), 4)
        self.assertEqual(len(VISUAL_SUBGROUP_DEFINITIONS), 4)
        self.assertEqual(
            contract["metric_keys"],
            {
                section: sorted(keys)
                for section, keys in EXPECTED_METRIC_KEYS.items()
            },
        )

    def test_api_public_receipt_binds_content_free_scorecard_contract(self) -> None:
        receipt_path = ROOT / "evaluation/baselines/mini131-bundle-v1/receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        contract_sha256 = sha256_file(ROOT / SCORECARD_CONTRACT_PATH)

        self.assertEqual(receipt["scorecard_contract_sha256"], contract_sha256)
        self.assertEqual(
            receipt["artifact_sha256s"]["inputs"]["scorecard_contract"],
            contract_sha256,
        )
        self.assertTrue(all(value is False for value in receipt["privacy"].values()))
        self.assertNotIn("evaluation/private/", json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
