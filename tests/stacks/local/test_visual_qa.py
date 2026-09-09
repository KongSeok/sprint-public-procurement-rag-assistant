"""Image QA contracts with synthetic pixels and a fake isolated worker."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

import numpy as np

from midprojectrag.stacks.local import visual_qa as qa
from midprojectrag.indexing import visual_ocr_index as store
from tests.indexing import test_visual_ocr_index as index_tests
from tests.indexing.test_visual_ocr_index import FakeProvider


def raw_answer(abstained=False):
    return {"raw_text": json.dumps({"answer": "Synthetic answer", "visible_details": ["Synthetic label"],
                                    "uncertainties": [], "abstained": abstained}),
            "runtime": {"finish_reason": "stop", "image_count": 1, "pixel_values_shape": [1, 3, 28, 28],
                        "ocr_text_supplied": False, "model": qa.MODEL, "revision": qa.REVISION,
                        "device": "Device(gpu, 0)", "mlx_vlm": "0.7.0", "actual_prompt_tokens": 12,
                        "input_tokens": 12, "output_tokens": 10}}


class VisualQATests(unittest.TestCase):
    setUp = index_tests.VisualOCRIndexTests.setUp
    write_inputs = index_tests.VisualOCRIndexTests.write_inputs
    build = index_tests.VisualOCRIndexTests.build

    def retrieval(self):
        self.build()
        return store.search(provider=FakeProvider(), query="Describe the synthetic drawing", **self.common)

    def test_selection_binds_original_citation_and_excludes_ocr(self):
        result = self.retrieval()
        selected = qa.verified_selection(result, **self.common)
        self.assertEqual(selected["crop_sha256"], result["hits"][0]["citation"]["crop_sha256"])
        self.assertNotIn("text", selected)
        self.assertNotIn("ocr", selected)

    def test_forged_citation_and_path_fail(self):
        result = self.retrieval()
        forged = copy.deepcopy(result)
        forged["hits"][0]["citation"]["page"] = 99
        with self.assertRaisesRegex(ValueError, "citation_mismatch"):
            qa.verified_selection(forged, **self.common)
        result["hits"][0]["crop_path"] = str(self.root / "other.png")
        with self.assertRaisesRegex(ValueError, "path_mismatch"):
            qa.verified_selection(result, **self.common)

    def test_empty_hits_rejected(self):
        with self.assertRaisesRegex(ValueError, "visual_retrieval_empty"):
            qa.verified_selection({"hits": []}, **self.common)

    def test_pixels_passed_to_generator_without_substitution(self):
        pixels = np.ones((1, 3, 28, 28), dtype=np.float32)
        inputs = {"input_ids": np.ones((1, 12), dtype=int), "pixel_values": pixels,
                  "attention_mask": np.ones((1, 12), dtype=int), "image_grid_thw": [1, 1, 1]}
        kwargs, receipt = qa.generation_inputs(inputs)
        self.assertIs(kwargs["pixel_values"], pixels)
        self.assertEqual(receipt["pixel_values_shape"], [1, 3, 28, 28])
        self.assertEqual(receipt["input_tokens"], 12)
        self.assertIs(kwargs["mask"], inputs["attention_mask"])

    def test_text_only_and_overflow_inputs_fail(self):
        with self.assertRaisesRegex(ValueError, "visual_pixels_missing"):
            qa.generation_inputs({"input_ids": np.ones((1, 12))})
        with self.assertRaisesRegex(ValueError, "visual_context_budget_exceeded"):
            qa.generation_inputs({"input_ids": np.ones((1, 8192)), "pixel_values": np.ones((1, 3))})

    def test_answer_is_inference_not_source_truth(self):
        answer = qa.validate_generation(raw_answer())
        self.assertEqual(answer["status"], "answered")
        self.assertTrue(answer["human_review_required"])
        self.assertFalse(answer["factual_evidence_promoted"])
        self.assertEqual(qa.validate_generation(raw_answer(True))["status"], "abstained")

    def test_truncation_invalid_json_and_no_pixels_fail(self):
        for mutate in (lambda r:r["runtime"].update(finish_reason="length"),
                       lambda r:r.update(raw_text="not JSON"),
                       lambda r:r["runtime"].update(pixel_values_shape=[])):
            raw = raw_answer()
            mutate(raw)
            with self.assertRaises(ValueError):
                qa.validate_generation(raw)

    def test_extra_citation_field_cannot_be_model_generated(self):
        value = json.loads(raw_answer()["raw_text"])
        value["citation"] = "invented"
        with self.assertRaises(Exception):
            qa.validate_answer(value)

    def test_runtime_and_crop_identity_are_bound(self):
        for key, value in (("model", "other"), ("device", "cpu"), ("pixel_values_shape", [0]),
                           ("actual_prompt_tokens", 13), ("output_tokens", 0)):
            raw = raw_answer()
            raw["runtime"][key] = value
            with self.assertRaises(ValueError):
                qa.validate_generation(raw)
        with self.assertRaisesRegex(ValueError, "visual_generation_crop_mismatch"):
            qa.validate_generation(raw_answer(), "a"*64)

    def test_uncertainty_withholds_confident_interpretation(self):
        raw = raw_answer()
        value = json.loads(raw["raw_text"])
        value.update(answer="Unsupported confident relation", uncertainties=["Connection unclear"])
        raw["raw_text"] = json.dumps(value)
        answer = qa.validate_generation(raw)
        self.assertEqual(answer["status"], "abstained")
        self.assertEqual(answer["quality_gate"], "uncertainty_abstention")
        self.assertNotIn("Unsupported", answer["interpretation"]["answer"])
        self.assertEqual(answer["interpretation"]["visible_details"], [])

    def test_model_identity_or_text_only_model_rejected(self):
        model_dir = self.root / "model"
        model_dir.mkdir()
        manifest_path = self.root / "model-manifest.json"
        manifest_path.write_text(json.dumps({"repo": "unapproved", "revision": qa.REVISION}))
        with self.assertRaisesRegex(ValueError, "visual_model_identity_mismatch"):
            qa.verify_model(model_dir, manifest_path)
        manifest_path.write_text(json.dumps({"repo": qa.MODEL, "revision": qa.REVISION, "files": {}}))
        with self.assertRaisesRegex(ValueError, "visual_model_files_missing"):
            qa.verify_model(model_dir, manifest_path)

    def test_crop_bytes_must_match_hash(self):
        selected = qa.verified_selection(self.retrieval(), **self.common)
        self.crop.write_bytes(self.crop.read_bytes()+b"altered")
        with self.assertRaisesRegex(ValueError, "visual_input_checksum_mismatch"):
            qa.decode_crop(selected)

    def worker_args(self, output):
        manifest = self.root / "fake-manifest.json"
        manifest.write_text("{}")
        return dict(**self.common, output=output, python_executable=Path(sys.executable),
                    model_dir=self.root, manifest_path=manifest)

    def test_isolated_worker_persists_answer_and_sanitizes_html(self):
        result = self.retrieval()
        output = self.root / "answer-001"

        def worker(command, **kwargs):
            self.assertEqual(command[2], "(version 1) (allow default) (deny network*)")
            self.assertEqual(kwargs["timeout"], 180)
            self.assertNotIn("OPENAI_API_KEY", kwargs["env"])
            target = Path(command[command.index("--worker-output")+1])
            value = raw_answer()
            value["runtime"]["crop_sha256"] = result["hits"][0]["citation"]["crop_sha256"]
            answer = json.loads(value["raw_text"])
            answer["answer"] = "<script>untrusted</script>"
            value["raw_text"] = json.dumps(answer)
            store._write(target, value)
            return subprocess.CompletedProcess(command, 0)

        with mock.patch.object(qa, "SANDBOX", Path(sys.executable)), mock.patch.object(qa.subprocess, "run", side_effect=worker):
            answer = qa.answer_retrieval(result, **self.worker_args(output))
        self.assertEqual(answer["citation"], result["hits"][0]["citation"])
        document = (output / "index.html").read_text()
        self.assertNotIn("<script>", document)
        self.assertIn("&lt;script&gt;", document)
        self.assertNotIn("VLM 해석·LLM 답변이 아닙니다", document)
        self.assertTrue((output / "answer.json").is_file())
        self.assertEqual((output / "answer.json").stat().st_mode & 0o777, 0o600)

    def test_worker_failure_persists_failure_without_answer(self):
        result = self.retrieval()
        output = self.root / "failed-answer"
        with mock.patch.object(qa, "SANDBOX", Path(sys.executable)), mock.patch.object(qa.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaisesRegex(ValueError, "visual_worker_failed"):
                qa.answer_retrieval(result, **self.worker_args(output))
        self.assertTrue((output / "failure.json").is_file())
        self.assertFalse((output / "answer.json").exists())

    def test_existing_output_is_not_overwritten(self):
        result = self.retrieval()
        output = self.root / "existing"
        output.mkdir()
        with self.assertRaisesRegex(ValueError, "output_already_exists"):
            qa.answer_retrieval(result, **self.worker_args(output))


if __name__ == "__main__":
    unittest.main()
