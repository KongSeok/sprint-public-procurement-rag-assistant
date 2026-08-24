from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from midprojectrag.evaluation import main, score_runs
from midprojectrag.ingest.common import write_json, write_jsonl
from tests.evaluation.helpers import METRICS_CONFIG_PATH, make_cases, make_runs, make_scoring_cases, scoring_kwargs


class EvaluationCliTests(unittest.TestCase):
    def test_validate_score_and_compare_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dev = make_scoring_cases("dev")
            heldout = make_cases("heldout")
            dev_path = root / "dev.jsonl"
            heldout_path = root / "heldout.jsonl"
            runs_path = root / "runs.jsonl"
            score_path = root / "score.json"
            candidate_path = root / "candidate.json"
            comparison_path = root / "comparison.json"
            write_jsonl(dev_path, dev)
            write_jsonl(heldout_path, heldout)
            write_jsonl(runs_path, make_runs(dev))

            with redirect_stdout(io.StringIO()):
                validate_exit = main(
                    [
                        "validate",
                        "--dev",
                        str(dev_path),
                        "--held-out",
                        str(heldout_path),
                        "--minimum-per-task",
                        "1",
                    ]
                )
                score_exit = main(
                    [
                        "score",
                        "--cases",
                        str(dev_path),
                        "--runs",
                        str(runs_path),
                        "--config",
                        str(METRICS_CONFIG_PATH),
                        "--output",
                        str(score_path),
                    ]
                )

            baseline = json.loads(score_path.read_text(encoding="utf-8"))
            candidate = score_runs(dev, make_runs(dev, stack_id="gcp_local"), **scoring_kwargs())
            write_json(candidate_path, candidate)
            with redirect_stdout(io.StringIO()):
                compare_exit = main(
                    [
                        "compare",
                        "--baseline",
                        str(score_path),
                        "--candidate",
                        str(candidate_path),
                        "--output",
                        str(comparison_path),
                    ]
                )

            self.assertEqual(validate_exit, 0)
            self.assertEqual(score_exit, 0)
            self.assertEqual(compare_exit, 0)
            self.assertTrue(baseline["passed"])
            self.assertTrue(json.loads(comparison_path.read_text(encoding="utf-8"))["passed"])

    def test_missing_private_path_is_not_disclosed(self) -> None:
        private_path = Path("/restricted/team/private-evaluation.jsonl")
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = main(
                [
                    "validate",
                    "--dev",
                    str(private_path),
                    "--held-out",
                    str(private_path),
                    "--minimum-per-task",
                    "1",
                ]
            )
        self.assertEqual(exit_code, 3)
        self.assertNotIn(str(private_path), stdout.getvalue())

    def test_frozen_config_cannot_be_bypassed_with_synthetic_minimum(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dev_path = root / "dev.jsonl"
            heldout_path = root / "heldout.jsonl"
            write_jsonl(dev_path, make_cases("dev"))
            write_jsonl(heldout_path, make_cases("heldout"))
            with redirect_stdout(io.StringIO()):
                exit_code = main(
                    [
                        "validate",
                        "--dev",
                        str(dev_path),
                        "--held-out",
                        str(heldout_path),
                        "--config",
                        str(METRICS_CONFIG_PATH),
                        "--minimum-per-task",
                        "1",
                    ]
                )
        self.assertEqual(exit_code, 3)


if __name__ == "__main__":
    unittest.main()
