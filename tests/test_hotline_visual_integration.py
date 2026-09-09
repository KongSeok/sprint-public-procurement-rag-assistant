"""Merged visual/text paths coexist; synthetic corpus/providers/workers only."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from midprojectrag import hotline
from midprojectrag.evo_harness import policy
from midprojectrag.evo_harness.runtime import compose_runtime, synthetic_tools
from midprojectrag.indexing import visual_ocr_index as visual
from midprojectrag.stacks.local import visual_qa
from tests import test_evo_harness as evo_fixtures
from tests.indexing import test_visual_ocr_index as visual_fixtures
from tests.stacks.local import test_visual_qa as qa_fixtures

ROOT = Path(__file__).resolve().parents[1]


class HotlineVisualIntegrationTests(unittest.TestCase):
    setUp = visual_fixtures.VisualOCRIndexTests.setUp
    write_inputs = visual_fixtures.VisualOCRIndexTests.write_inputs
    build = visual_fixtures.VisualOCRIndexTests.build

    def text_episode(self):
        backend = evo_fixtures.FakeBackend([
            evo_fixtures.search(), evo_fixtures.read("e1", "e2"), evo_fixtures.finish("e1", "e2")])
        return compose_runtime(backend, synthetic_tools()).run(evo_fixtures.REQUEST)

    def visual_episode(self, *, uncertain=False):
        self.build()
        result = visual.search(provider=visual_fixtures.FakeProvider(),
                               query="Read the synthetic figure label", **self.common)
        output = self.root / "qa-output"
        manifest = self.root / "fake-model-manifest.json"
        manifest.write_text("{}")
        dispatched = []

        def fake_worker(command, **kwargs):
            dispatched.append(command)
            request_path = Path(command[command.index("--worker-request") + 1])
            request = json.loads(request_path.read_text())
            self.assertNotIn("text", request)
            self.assertNotIn("ocr", request)
            self.assertEqual(request["crop_sha256"], result["hits"][0]["citation"]["crop_sha256"])
            self.assertEqual(kwargs["timeout"], 180)
            self.assertEqual(command[2], "(version 1) (allow default) (deny network*)")
            raw = qa_fixtures.raw_answer()
            raw["runtime"]["crop_sha256"] = request["crop_sha256"]
            if uncertain:
                answer = json.loads(raw["raw_text"])
                answer["uncertainties"] = ["Synthetic line is unclear"]
                raw["raw_text"] = json.dumps(answer)
            visual._write(Path(command[command.index("--worker-output") + 1]), raw)
            return subprocess.CompletedProcess(command, 0)

        with patch.object(visual_qa, "SANDBOX", Path(sys.executable)), \
             patch.object(visual_qa.subprocess, "run", side_effect=fake_worker):
            answer = visual_qa.answer_retrieval(
                result, **self.common, output=output, python_executable=Path(sys.executable),
                model_dir=self.root, manifest_path=manifest)
        self.assertEqual(len(dispatched), 1)
        return result, answer, output

    def test_same_process_visual_qa_then_evo_keeps_evidence_and_controller_boundaries(self):
        forbidden = {"issue_harness_execution", "validate_harness_execution", "decide_controller_action",
                     "validate_controller_decision_receipt", "require_successor_record",
                     "execute_controller_first_parent_step"}
        entered = []
        previous = sys.getprofile()
        def observe(frame, event, arg):
            if event == "call" and frame.f_code.co_name in forbidden:
                entered.append(frame.f_code.co_name)
        try:
            sys.setprofile(observe)
            result, answer, output = self.visual_episode()
            text = self.text_episode()
        finally:
            sys.setprofile(previous)
        self.assertEqual(entered, [])
        self.assertEqual(answer["status"], "answered")
        self.assertEqual(answer["citation"], result["hits"][0]["citation"])
        self.assertTrue(answer["human_review_required"])
        self.assertFalse(answer["factual_evidence_promoted"])
        self.assertEqual(text["status"], "answered", text)
        self.assertEqual(set(text["response"]["cited_doc_ids"]), {"alpha", "beta"})
        self.assertEqual(text["usage"]["policy_calls"], 3)
        self.assertEqual(text["usage"]["answer_calls"], 1)
        self.assertTrue(text["synthetic_backend"])
        self.assertFalse(text["controller_executed"])
        self.assertEqual((output / "answer.json").stat().st_mode & 0o777, 0o600)

    def test_evo_then_visual_uncertainty_does_not_become_factual_evidence(self):
        text = self.text_episode()
        before = json.dumps(text, sort_keys=True)
        _, answer, output = self.visual_episode(uncertain=True)
        self.assertEqual(answer["status"], "abstained")
        self.assertEqual(answer["evidence_type"], "visual_inference")
        self.assertFalse(answer["factual_evidence_promoted"])
        self.assertEqual(answer["interpretation"]["visible_details"], [])
        self.assertEqual(json.dumps(text, sort_keys=True), before)
        self.assertTrue((output / "index.html").is_file())

    def test_merged_model_profiles_share_qwen35_derivative_without_replacing_control(self):
        self.assertEqual(policy.MODEL_ID, "Qwen/Qwen3.5-9B")
        self.assertEqual(visual_qa.MODEL, policy.DERIVATIVE_ID)
        self.assertEqual(visual_qa.REVISION, "8b2b98c00a6b4d291155e4890773ca8f769aee53")
        self.assertEqual(hotline.MODEL, "qwen3.8:27b-mlx")
        self.assertNotEqual(hotline.MODEL, visual_qa.MODEL)

    def test_all_cli_help_paths_are_available_without_loading_models(self):
        environment = dict(os.environ, PYTHONPATH=str(ROOT / "src"),
                           PYTHONDONTWRITEBYTECODE="1", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        for module, expected in [
            ("midprojectrag.hotline", "--timeout-seconds"),
            ("midprojectrag.evo_harness.cli", "--model-manifest"),
            ("midprojectrag.indexing.visual_ocr_index", "build,search,answer"),
            ("midprojectrag.stacks.local.visual_qa", "--worker-request")]:
            with self.subTest(module=module):
                done = subprocess.run([sys.executable, "-m", module, "--help"],
                    cwd=ROOT, env=environment, text=True, capture_output=True, timeout=20)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertIn(expected, done.stdout)


if __name__ == "__main__":
    unittest.main()
