"""Publication policy regressions in disposable Git repositories, never the real index."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("git") and shutil.which("rg"), "git and ripgrep required")
class ResourcesPublicationPolicyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="resources-policy-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root / "scripts").mkdir()
        shutil.copyfile(PROJECT_ROOT / ".gitignore", self.root / ".gitignore")
        shutil.copyfile(PROJECT_ROOT / "scripts/validate_repo_safety.sh",
                        self.root / "scripts/validate_repo_safety.sh")
        self.command("git", "init", "-q", check=True)

    def command(self, *args, check=False):
        return subprocess.run(args, cwd=self.root, capture_output=True, text=True,
                              timeout=15, check=check)

    def fixture(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic fixture, no source data\n", encoding="utf-8")

    def test_entire_resources_tree_is_ignored_regardless_of_format(self):
        for relative in ("resources/shared_team/chunks.pkl", "resources/shared_team/report.md",
                         "resources/novel_folder/metadata.json", "resources/archive.zip",
                         "resources/data_refined/fixture.txt"):
            with self.subTest(relative=relative):
                self.fixture(relative)
                result = self.command("git", "check-ignore", "-v", "--", relative)
                self.assertEqual(result.returncode, 0)
                self.assertIn("/resources/", result.stdout)
        result = self.command("git", "ls-files", "--others", "--exclude-standard", "--", "resources")
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.command("bash", "scripts/validate_repo_safety.sh").returncode, 0)

    def test_force_added_resource_fails_even_without_pii(self):
        relative = "resources/shared_team/synthetic.json"
        self.fixture(relative)
        self.command("git", "add", "-f", "--", relative, check=True)
        result = self.command("bash", "scripts/validate_repo_safety.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FORBIDDEN_TRACKED_PATHS_FOUND count=1", result.stdout)
        self.assertIn("Repository safety check: FAIL", result.stdout)
        self.assertTrue((self.root / relative).is_file())

    def test_operating_docs_outside_resources_remain_versionable(self):
        relative = "fivecircles/architecture/specs/synthetic.md"
        self.fixture(relative)
        self.assertEqual(self.command("git", "check-ignore", "--", relative).returncode, 1)


if __name__ == "__main__":
    unittest.main()
