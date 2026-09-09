from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from midprojectrag.ingest import visual_model_manifest as model


class ModelManifestTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.file = self.root / "synthetic/inference.json"
        self.file.parent.mkdir()
        self.file.write_bytes(b"synthetic")
        expected = {"synthetic/inference.json": (9, hashlib.sha256(b"synthetic").hexdigest())}
        patcher = patch.object(model, "EXPECTED_FILES", expected)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_repeat_is_byte_identical_without_download_or_rewrite(self):
        with patch.object(model.urllib.request, "urlopen", side_effect=AssertionError("network")):
            first = model.provision(self.root)
            manifest = self.root / "model-manifest.json"
            before = manifest.read_bytes(), manifest.stat().st_mtime_ns
            self.assertEqual(model.provision(self.root, allow_download=True), first)
            self.assertEqual((manifest.read_bytes(), manifest.stat().st_mtime_ns), before)
            self.assertEqual(len(json.loads(manifest.read_text())["files"]), 1)

    def test_tampered_weight_does_not_repair_manifest(self):
        model.publish_manifest(self.root)
        manifest = (self.root / "model-manifest.json").read_bytes()
        self.file.write_bytes(b"tampered!")
        with self.assertRaisesRegex(model.ModelManifestError, "checksum"):
            model.provision(self.root)
        self.assertEqual((self.root / "model-manifest.json").read_bytes(), manifest)

    def test_missing_and_extra_files_fail(self):
        self.file.unlink()
        with self.assertRaisesRegex(model.ModelManifestError, "file_set"):
            model.publish_manifest(self.root)
        self.file.write_bytes(b"synthetic")
        (self.root / "unexpected").write_bytes(b"x")
        with self.assertRaisesRegex(model.ModelManifestError, "file_set"):
            model.publish_manifest(self.root)

    def test_manifest_self_entry_rejected_not_rewritten(self):
        model.publish_manifest(self.root)
        path = self.root / "model-manifest.json"
        value = json.loads(path.read_text())
        value["files"].append({"path": "model-manifest.json", "bytes": 1, "sha256": "0"*64})
        path.write_text(json.dumps(value))
        before = path.read_bytes()
        with self.assertRaisesRegex(model.ModelManifestError, "contract"):
            model.provision(self.root)
        self.assertEqual(path.read_bytes(), before)

    def test_symlink_weight_rejected(self):
        target = self.root / "target"
        target.write_bytes(self.file.read_bytes())
        self.file.unlink()
        self.file.symlink_to(target)
        with self.assertRaisesRegex(model.ModelManifestError, "symlink"):
            model.publish_manifest(self.root)

    def test_atomic_failure_has_no_partial_manifest(self):
        with patch.object(model.os, "link", side_effect=OSError("fixture")):
            with self.assertRaises(OSError):
                model.publish_manifest(self.root)
        self.assertFalse((self.root / "model-manifest.json").exists())
        self.assertEqual(list(self.root.glob(".manifest-*")), [])

    def test_duplicate_json_keys_rejected(self):
        with self.assertRaisesRegex(model.ModelManifestError, "duplicate"):
            model.strict_json('{"x":1,"x":2}')

    def test_missing_root_requires_download_approval(self):
        with patch.object(model.urllib.request, "urlopen", side_effect=AssertionError("network")):
            with self.assertRaisesRegex(model.ModelManifestError, "not_authorized"):
                model.provision(self.root / "new")


if __name__ == "__main__":
    unittest.main()
