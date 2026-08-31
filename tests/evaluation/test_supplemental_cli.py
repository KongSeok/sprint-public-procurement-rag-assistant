from __future__ import annotations

import io
import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from midprojectrag.supplemental_evaluation import main, prepare_supplemental
from tests.evaluation.supplemental_helpers import (
    attach_eval_hash,
    create_preparation_fixture,
    make_answer_case,
    make_answer_run,
    make_set_case,
    make_set_run,
    source_sha,
    write_jsonl,
)


class SupplementalCliTests(unittest.TestCase):
    def write_manifest(self, path: Path, document_ids: list[str]) -> str:
        write_jsonl(
            path,
            [
                {
                    "sha256": source_sha(9000 + index),
                    "doc_id": document_id,
                    "index_eligible": True,
                    "status": "ok",
                    "snapshot_id": "snapshot_cli",
                    "normalized_filename": f"cli-{index}.hwp",
                }
                for index, document_id in enumerate(document_ids)
            ],
        )
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_validate_cli_accepts_draft_but_require_approved_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = create_preparation_fixture(root)
            draft_dir = root / "draft"
            build_report = prepare_supplemental(
                source_path=fixture["source_path"],
                disposition_path=fixture["disposition_path"],
                overrides_path=fixture["overrides_path"],
                legacy_csv_path=fixture["legacy_csv_path"],
                manifest_path=fixture["manifest_path"],
                blocks_dir=fixture["blocks_dir"],
                output_dir=draft_dir,
                expected_hashes=None,
            )
            self.assertTrue(build_report["passed"], build_report["errors"])
            answer_path = draft_dir / "rag-56.draft.jsonl"
            set_path = draft_dir / "set-13.draft.jsonl"

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "validate-supplemental",
                        "--rag-cases",
                        str(answer_path),
                        "--set-cases",
                        str(set_path),
                    ]
                )
            report = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(report["passed"])
            self.assertEqual(report["evaluation_tier"], "provisional")
            self.assertFalse(report["official_gold_ready"])
            self.assertEqual(report["counts"], {"answer": 56, "set": 13})

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "validate-supplemental",
                        "--rag-cases",
                        str(answer_path),
                        "--set-cases",
                        str(set_path),
                        "--require-approved",
                        "--manifest",
                        str(fixture["manifest_path"]),
                        "--legacy-csv",
                        str(fixture["legacy_csv_path"]),
                        "--blocks-dir",
                        str(fixture["blocks_dir"]),
                    ]
                )
            report = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 2)
            self.assertFalse(report["passed"])
            self.assertEqual(report["evaluation_tier"], "official")
            self.assertFalse(report["official_gold_ready"])
            self.assertEqual(
                sum(item["code"] == "case_not_approved" for item in report["errors"]),
                69,
            )

    def test_score_set_cli_writes_machine_readable_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.jsonl"
            temporary = make_set_case(0, status="approved")
            manifest_hash = self.write_manifest(
                manifest_path, temporary["required_doc_ids"]
            )
            cases = [
                make_set_case(
                    0, status="approved", manifest_sha256=manifest_hash
                )
            ]
            runs = [make_set_run(cases[0])]
            attach_eval_hash(cases, runs)
            cases_path = root / "cases.jsonl"
            runs_path = root / "runs.jsonl"
            output_path = root / "report.json"
            write_jsonl(cases_path, cases)
            write_jsonl(runs_path, runs)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "score-set",
                        "--cases",
                        str(cases_path),
                        "--runs",
                        str(runs_path),
                        "--manifest",
                        str(manifest_path),
                        "--output",
                        str(output_path),
                    ]
                )
            streamed = json.loads(stdout.getvalue())
            stored = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertTrue(streamed["passed"])
            self.assertEqual(streamed["evaluation_tier"], "provisional")
            self.assertFalse(streamed["official_gold_ready"])
            self.assertFalse(streamed["suite_complete"])
            self.assertEqual(streamed, stored)

    def test_score_set_cli_runs_draft_provisionally_but_official_gate_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.jsonl"
            temporary = make_set_case(0)
            manifest_hash = self.write_manifest(
                manifest_path, temporary["required_doc_ids"]
            )
            cases = [make_set_case(0, manifest_sha256=manifest_hash)]
            runs = [make_set_run(cases[0])]
            attach_eval_hash(cases, runs)
            cases_path = root / "cases.jsonl"
            runs_path = root / "runs.jsonl"
            write_jsonl(cases_path, cases)
            write_jsonl(runs_path, runs)
            base_args = [
                "score-set",
                "--cases",
                str(cases_path),
                "--runs",
                str(runs_path),
                "--manifest",
                str(manifest_path),
            ]

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(base_args)
            report = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(report["passed"], report["errors"])
            self.assertEqual(report["evaluation_tier"], "provisional")
            self.assertFalse(report["official_gold_ready"])

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main([*base_args, "--require-approved"])
            report = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 2)
            self.assertFalse(report["passed"])
            self.assertEqual(report["evaluation_tier"], "official")
            codes = {item["code"] for item in report["errors"]}
            self.assertIn("case_not_approved", codes)
            self.assertIn("official_suite_incomplete", codes)

    def test_score_answer_cli_runs_draft_provisionally(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.jsonl"
            temporary = make_answer_case(0)
            manifest_hash = self.write_manifest(
                manifest_path, temporary["scope_doc_ids"]
            )
            cases = [make_answer_case(0, manifest_sha256=manifest_hash)]
            runs = [make_answer_run(cases[0])]
            attach_eval_hash(cases, runs)
            cases_path = root / "answer-cases.jsonl"
            runs_path = root / "answer-runs.jsonl"
            write_jsonl(cases_path, cases)
            write_jsonl(runs_path, runs)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "score-answer",
                        "--cases",
                        str(cases_path),
                        "--runs",
                        str(runs_path),
                        "--manifest",
                        str(manifest_path),
                    ]
                )
            report = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(report["passed"], report["errors"])
            self.assertEqual(report["evaluation_tier"], "provisional")
            self.assertEqual(report["config_sha256"], "a" * 64)
            self.assertEqual(report["counts"]["scored"], 1)

    def test_cli_parse_failure_does_not_echo_private_input_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret = "PRIVATE_QUESTION_MUST_NOT_LEAK"
            cases_path = root / "cases.jsonl"
            runs_path = root / "runs.jsonl"
            manifest_path = root / "manifest.jsonl"
            self.write_manifest(manifest_path, ["doc_" + "1" * 24])
            cases_path.write_text('{"question":"' + secret + '"', encoding="utf-8")
            runs_path.write_text("", encoding="utf-8")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "score-set",
                        "--cases",
                        str(cases_path),
                        "--runs",
                        str(runs_path),
                        "--manifest",
                        str(manifest_path),
                    ]
                )
            payload = stdout.getvalue()
            self.assertEqual(exit_code, 3)
            self.assertNotIn(secret, payload)
            self.assertEqual(
                json.loads(payload)["error"],
                "invalid_supplemental_evaluation_input",
            )


if __name__ == "__main__":
    unittest.main()
