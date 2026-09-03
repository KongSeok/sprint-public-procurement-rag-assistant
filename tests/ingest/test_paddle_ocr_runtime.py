from __future__ import annotations

import json
import platform
import subprocess
import sys
import unittest
from pathlib import Path

from midprojectrag.ingest import paddle_ocr_runtime as runtime


class PaddleOcrRuntimeTests(unittest.TestCase):
    @unittest.skipUnless(platform.system() == "Darwin", "macOS sandbox smoke")
    def test_actual_os_sandbox_denies_loopback_bind(self):
        program = "import socket,sys\ntry:\n s=socket.socket(); s.bind(('127.0.0.1',0))\nexcept PermissionError:\n print('NETWORK_DENIED'); sys.exit(0)\nsys.exit(2)"
        completed = subprocess.run(["/usr/bin/sandbox-exec", "-p",
            "(version 1) (allow default) (deny network*)", sys.executable, "-I", "-c", program],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "NETWORK_DENIED")

    def test_disabled_optional_models_and_batch_one(self):
        options = runtime.pipeline_options(Path("/synthetic"), {"text_rec_score_thresh": 0.5})
        for key in ("use_doc_orientation_classify", "use_doc_unwarping", "use_textline_orientation",
                    "enable_hpi", "enable_mkldnn"):
            self.assertIs(options[key], False)
        self.assertEqual(options["text_recognition_batch_size"], 1)
        self.assertEqual(options["cpu_threads"], 1)
        self.assertEqual(options["device"], "cpu")
        self.assertEqual(options["text_det_limit_type"], "max")
        self.assertNotIn("layout_detection_model_dir", options)

    def test_protocol_mapping_keeps_polygon_and_no_table_claim(self):
        result = runtime.normalize_prediction({"rec_texts": ["합성 자료"], "rec_scores": [0.9],
            "rec_polys": [[[0, 0], [40, 0], [40, 10], [0, 10]]]}, maximum=10, width=50, height=20)
        self.assertEqual(result["text_items"][0]["reading_order"], 0)
        self.assertEqual(result["text_items"][0]["text"], "합성 자료")
        self.assertEqual(result["table_cells"], [])
        self.assertIn("ocr_only_no_document_layout", result["warnings"])
        json.dumps(result, allow_nan=False)

    def test_empty_result_is_not_success(self):
        result = runtime.normalize_prediction({"rec_texts": [], "rec_scores": [], "rec_polys": []},
                                              maximum=10, width=50, height=20)
        self.assertEqual(result["status"], "low_confidence")

    def test_mismatched_lengths_and_off_crop_geometry_rejected(self):
        for polygon, scores in [([[[0,0],[1,0],[1,1],[0,1]]], []),
                                ([[[0,0],[999,0],[999,1],[0,1]]], [0.9])]:
            with self.assertRaises(ValueError):
                runtime.normalize_prediction({"rec_texts": ["test"], "rec_scores": scores,
                    "rec_polys": polygon}, maximum=10, width=50, height=20)

    def test_optional_profile_refused_before_model_access(self):
        config = json.loads((Path(__file__).resolve().parents[2] /
            "configs/visual/ppocrv5-cpu-minimal.json").read_text())
        config.pop("schema_version")
        config["config_contract"] = "pp-structure-v3-korean-ppocrv5-v1"
        for flag in runtime.DISABLED:
            candidate = {**config, flag: True}
            envelope = {"schema_version":"1.0", "operation":"ocr_layout_v1", "model_artifact_path":"/missing",
                "request": {"schema_version":"1.0", "crop_path":"/missing", "crop_sha256":"0"*64,
                "occurrence_id":"fixture", "page":1, "bbox":{}, "coordinate_space":"fixture", "config":candidate}}
            with self.assertRaisesRegex(ValueError, "minimal_profile"):
                runtime.validate_request(envelope)


if __name__ == "__main__":
    unittest.main()
