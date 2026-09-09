"""Hotline migration regression. No real model, network or private corpus."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import inspect
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from midprojectrag import hotline
from tests import test_controller_quick_qa as legacy_tests


class HotlineRuntimeTests(unittest.TestCase):
    def case(self, folder):
        loaded, request, specs, dense_log, lexical_log = legacy_tests.QuickQaTests().public_case(folder)
        calls = []
        def generate(prompt):
            calls.append(prompt)
            return {"status": "answered", "answer": "Synthetic answer", "citations": ["S1"]}, 10, 3
        loaded["generator"] = SimpleNamespace(generate=generate)
        loaded["opener"] = SimpleNamespace(generation_calls=0, payload=None)
        return loaded, request, calls, dense_log, lexical_log

    def test_default_executor_is_hotline_and_never_enters_controller(self):
        with tempfile.TemporaryDirectory() as folder:
            loaded, request, calls, dense_log, lexical_log = self.case(folder)
            forbidden = {"issue_harness_execution", "validate_harness_execution",
                         "decide_controller_action", "validate_controller_decision_receipt",
                         "require_successor_record", "execute_controller_first_parent_step"}
            entered = []
            def profile(frame, event, arg):
                if event == "call" and frame.f_code.co_name in forbidden:
                    entered.append(frame.f_code.co_name)
            previous = sys.getprofile()
            try:
                sys.setprofile(profile)
                with redirect_stdout(io.StringIO()):
                    result = hotline.execute_question(request, loaded, hotline.Timer())
            finally:
                sys.setprofile(previous)
            self.assertEqual(entered, [])
            self.assertEqual(legacy_tests._calls(dense_log), ("dense",))
            self.assertEqual(legacy_tests._calls(lexical_log), ("lexical",))
            self.assertEqual(len(calls), 1)
            self.assertEqual(result["response"]["status"], "answered")
            self.assertFalse(result["trajectory"]["controller_executed"])
            self.assertFalse(result["trajectory"]["verifier_executed"])
            self.assertFalse(hasattr(hotline, "four_steps"))

    def test_legacy_launcher_delegates_without_a_controller_default(self):
        self.assertIs(legacy_tests.quickqa.execute_question, hotline.execute_question)
        self.assertIs(legacy_tests.quickqa.fixed_public_pipeline, hotline.fixed_public_pipeline)
        self.assertIs(legacy_tests.quickqa.main, hotline.main)
        self.assertFalse(hasattr(legacy_tests.quickqa, "four_steps"))

    def test_controller_option_is_rejected_before_initialization(self):
        with patch.object(hotline, "initialize") as initialize:
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                hotline.main(["--request", "unused.json", "--output-dir", "unused", "--path", "controller"])
        self.assertEqual(raised.exception.code, 2)
        initialize.assert_not_called()

    def test_bad_budget_is_rejected_before_initialization(self):
        for value in ("0", "-1", "nan", "inf", "121"):
            with self.subTest(value=value), patch.object(hotline, "initialize") as initialize:
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    hotline.main(["--request", "unused.json", "--output-dir", "unused", "--timeout-seconds", value])
                initialize.assert_not_called()

    def test_bad_external_deadline_is_rejected_before_initialization(self):
        for value in ("nan", "inf", "-1"):
            with self.subTest(value=value), patch.object(hotline, "initialize") as initialize:
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    hotline.main(["--request", "unused.json", "--output-dir", "unused", "--deadline-monotonic", value])
                initialize.assert_not_called()

    def test_phase_cannot_succeed_after_deadline(self):
        clock = [1.0]
        timer = hotline.Timer(lambda: clock[0], deadline=2.0)
        with redirect_stdout(io.StringIO()), self.assertRaises(TimeoutError):
            with timer.phase("work"):
                clock[0] = 2.5
        self.assertEqual(timer.phases[-1]["status"], "FAIL")

    def test_gold_and_unknown_scope_never_generate(self):
        for change in ("gold", "unknown_scope", "empty_scope"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                loaded, request, calls, dense_log, lexical_log = self.case(folder)
                if change == "gold":
                    request["expected_answer"] = "do not use"
                else:
                    request["document_scope"]["doc_ids"] = ["not-in-corpus"] if change == "unknown_scope" else []
                with redirect_stdout(io.StringIO()), self.assertRaises((ValueError, TypeError)):
                    hotline.execute_question(request, loaded, hotline.Timer())
                self.assertEqual(calls, [])
                self.assertEqual(legacy_tests._calls(dense_log), ())
                self.assertEqual(legacy_tests._calls(lexical_log), ())

    def test_explicit_scope_survives_to_citation(self):
        with tempfile.TemporaryDirectory() as folder:
            loaded, request, calls, _dense, _lexical = self.case(folder)
            with redirect_stdout(io.StringIO()):
                result = hotline.execute_question(request, loaded, hotline.Timer())
            self.assertEqual(result["context"]["doc_id"], "doc-a")
            self.assertEqual(result["response"]["citation_sources"][0]["doc_id"], "doc-a")
            self.assertFalse(result["context"]["semantically_verified"])

    def test_synthetic_complete_worker_cli_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            private = data / "private"
            private.mkdir()
            loaded, request, calls, _dense, _lexical = self.case(folder)
            request_path = private / "request.json"
            request_path.write_text(json.dumps(request))
            output = private / "outputs/local/hotline/run1"
            args = ["--data-dir", str(data), "--request", str(request_path), "--output-dir", str(output),
                    "--deadline-monotonic", str(time.monotonic() + 30)]
            with patch.object(hotline, "initialize", return_value=loaded), redirect_stdout(io.StringIO()):
                code = hotline.main(args)
            self.assertEqual(code, 0)
            result = json.loads((output / "result.json").read_text())
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["response"]["status"], "answered")
            self.assertEqual(len(calls), 1)
            self.assertFalse(result["controller_executed"])
            self.assertTrue(result["source_unchanged"])
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            self.assertEqual((output / "result.json").stat().st_mode & 0o777, 0o600)
            with patch.object(hotline, "initialize") as initialize, self.assertRaises(FileExistsError):
                hotline.main(args)
            initialize.assert_not_called()

    def test_request_outside_private_root_fails_before_initialization(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            request = data / "public.json"
            request.write_text('{}')
            with patch.object(hotline, "initialize") as initialize, self.assertRaisesRegex(ValueError, "private_run_paths_required"):
                hotline.main(["--data-dir", str(data), "--request", str(request),
                              "--output-dir", str(data / "private/output"),
                              "--deadline-monotonic", str(time.monotonic() + 10)])
            initialize.assert_not_called()

    def test_supervisor_success_and_timeout_are_distinct(self):
        ok = hotline.run_supervised([sys.executable, "-c", "pass"], timeout_seconds=5)
        self.assertEqual(ok["status"], "COMPLETED")
        self.assertEqual(ok["exit_code"], 0)
        with redirect_stdout(io.StringIO()):
            timeout = hotline.run_supervised([sys.executable, "-c", "import time; time.sleep(5)"], timeout_seconds=0.05)
        self.assertEqual(timeout["status"], "TIMEOUT")
        self.assertEqual(timeout["exit_code"], 124)
        self.assertLess(timeout["wall_seconds"], 3)
        self.assertNotEqual(timeout["pid"], os.getpid())

    def test_supervisor_worker_error_is_not_a_success(self):
        result = hotline.run_supervised([sys.executable, "-c", "raise SystemExit(7)"], timeout_seconds=5)
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["exit_code"], 7)

    def test_supervisor_validates_budget_before_spawn(self):
        for value in (0, -1, math.nan, math.inf, 121):
            with self.subTest(value=value), patch.object(hotline.subprocess, "Popen") as popen:
                with self.assertRaises(ValueError):
                    hotline.run_supervised([sys.executable, "-c", "pass"], timeout_seconds=value)
                popen.assert_not_called()

    def test_console_entrypoint_and_new_launcher(self):
        root = Path(__file__).resolve().parents[1]
        self.assertIn('midprojectrag-hotline = "midprojectrag.hotline:main"', (root / "pyproject.toml").read_text())
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(root / "src")}
        for command in ([sys.executable, "-m", "midprojectrag.hotline", "--help"],
                        [sys.executable, str(root / "scripts/run_hotline.py"), "--help"]):
            result = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--timeout-seconds", result.stdout)
            self.assertIn("{hotline}", result.stdout)
            self.assertNotIn("{controller", result.stdout)


if __name__ == "__main__":
    unittest.main()
