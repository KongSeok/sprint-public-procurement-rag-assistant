"""Delivery regression: public CLI composition and per-role timing, no model/network."""
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from midprojectrag.evo_harness import cli
from midprojectrag.evo_harness.runtime import compose_runtime, synthetic_tools
from tests import test_evo_harness as fixtures


class EvoDeliveryTests(unittest.TestCase):
    def test_fixed_deadline_has_same_validation_as_policy(self):
        backend = fixtures.FakeBackend()
        runner = compose_runtime(backend, synthetic_tools())
        for bad in (float("nan"), float("inf"), True, "120"):
            with self.subTest(deadline=repr(bad)):
                with self.assertRaisesRegex(ValueError, "invalid_deadline"):
                    runner.run_fixed(fixtures.REQUEST, deadline=bad)
        self.assertEqual(backend.calls, [])

    def test_policy_tools_and_answer_time_are_disjoint(self):
        now = [1.0]
        backend = fixtures.FakeBackend([
            fixtures.search(), fixtures.read("e1", "e2"), fixtures.finish("e1", "e2")])
        backend.after_call = lambda: now.__setitem__(0, now[0] + 0.25)
        runner = compose_runtime(backend, synthetic_tools())
        runner.clock = lambda: now[0]
        result = runner.run(fixtures.REQUEST)
        self.assertEqual(result["status"], "answered", result)
        self.assertEqual(result["timings"]["policy_seconds"], 0.75)
        self.assertEqual(result["timings"]["answer_seconds"], 0.25)
        self.assertEqual(result["timings"]["tools_seconds"], 0.0)
        self.assertEqual(result["wall_seconds"], 1.0)

    def test_fixed_result_does_not_hide_synthetic_backend(self):
        result = compose_runtime(fixtures.FakeBackend(), synthetic_tools()).run_fixed(fixtures.REQUEST)
        self.assertEqual(result["status"], "answered", result)
        self.assertTrue(result["synthetic_backend"])
        self.assertFalse(result["trained_policy"])
        self.assertEqual(result["usage"]["policy_calls"], 0)

    def test_cli_worker_reaches_public_tools_and_private_result(self):
        backend = fixtures.FakeBackend([
            fixtures.search(), fixtures.read("e1", "e2"), fixtures.finish("e1", "e2")])
        backend.load_seconds = 0.0
        backend.manifest_sha256 = "c" * 64
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            output = data / "private" / "run"
            args = ["--data-dir", str(data), "--output-dir", str(output),
                    "--model-dir", str(data / "model"), "--model-manifest", str(data / "model-manifest.json"),
                    "--synthetic-corpus", "--worker-deadline", str(time.monotonic() + 20)]
            stream = io.StringIO()
            with patch.object(cli, "MLXBackend", return_value=backend) as factory, redirect_stdout(stream):
                exit_code = cli.main(args)
            self.assertEqual(exit_code, 0)
            factory.assert_called_once()
            result = json.loads((output / "result.json").read_text())
            self.assertEqual(result["status"], "answered", result)
            self.assertEqual(result["response"]["citations"], ["S1", "S2"])
            self.assertEqual(result["retrieval_kind"], "synthetic_public_hybrid")
            self.assertEqual(result["usage"]["policy_calls"], 3)
            self.assertEqual(result["usage"]["answer_calls"], 1)
            self.assertNotIn("trajectory", result)
            self.assertEqual((output / "result.json").stat().st_mode & 0o777, 0o600)
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            summary = json.loads(stream.getvalue().strip())
            self.assertNotIn("response", summary)
            with patch.object(cli, "MLXBackend") as factory:
                with self.assertRaises(FileExistsError):
                    cli.main(args)
                factory.assert_not_called()

    def test_final_error_is_terminal_and_counts_attempt(self):
        backend = fixtures.FakeBackend([
            fixtures.search(), fixtures.read("e1"), fixtures.finish("e1")], answer="not-json")
        result = compose_runtime(backend, synthetic_tools()).run(fixtures.REQUEST)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["usage"]["answer_calls"], 1)
        self.assertEqual(result["usage"]["policy_calls"], 3)
        self.assertEqual(result["actions"][-1]["outcome"], "error")


if __name__ == "__main__":
    unittest.main()
