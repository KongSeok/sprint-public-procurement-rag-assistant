from __future__ import annotations

import json
import unittest
from pathlib import Path

from midprojectrag.eval_contracts.mini131.judge import expected_judge_config
from midprojectrag.eval_contracts.mini131.scorecard import (
    SCORECARD_CONTRACT_PATH,
    expected_contract,
    validate_contract,
)
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


if __name__ == "__main__":
    unittest.main()
