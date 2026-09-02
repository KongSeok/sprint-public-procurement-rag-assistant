import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from midprojectrag.offline_harness.gates import ROLES, inspect_artifacts


class GateTests(unittest.TestCase):
    def manifest(self): return {"schema_version": "evidence-harness-artifacts-v1", "artifacts": dict.fromkeys(ROLES)}
    def test_missing_artifacts_not_approval(self):
        result = inspect_artifacts(self.manifest(), base_dir=Path.cwd())
        self.assertEqual(len(result["gaps"]), len(ROLES))
        self.assertFalse(result["approved_for_runtime"])
    def test_hash_verified_still_not_promotion(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_text('{}')
            manifest = self.manifest()
            manifest["artifacts"] = {role: {"path": path.name, "sha256": hashlib.sha256(b'{}').hexdigest()} for role in ROLES}
            result = inspect_artifacts(manifest, base_dir=Path(tmp))
            self.assertTrue(result["artifact_manifests_present"])
            self.assertFalse(result["approved_for_runtime"])
    def test_wrong_hash_and_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_text('{}')
            manifest = self.manifest()
            manifest["artifacts"][ROLES[0]] = {"path": str(path), "sha256": "1"*64}
            self.assertEqual(inspect_artifacts(manifest, base_dir=Path(tmp))["checks"][0]["status"], "hash_mismatch")
            link = Path(tmp) / "alias.json"
            link.symlink_to(path)
            manifest["artifacts"][ROLES[0]]["path"] = str(link)
            self.assertEqual(inspect_artifacts(manifest, base_dir=Path(tmp))["checks"][0]["status"], "invalid_manifest_file")
    def test_malformed_manifest(self):
        for value in ([], {}, {"schema_version": "wrong", "artifacts": {}}):
            with self.assertRaises(ValueError): inspect_artifacts(value, base_dir=Path.cwd())


if __name__ == "__main__": unittest.main()
