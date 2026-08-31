from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from midprojectrag.ingest.common import sha256_file
from midprojectrag.parser_regression_baseline import run


class ParserRegressionBaselineTest(unittest.TestCase):
    def _fixture(self, root: Path) -> Path:
        (root / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0'\n", encoding="utf-8")
        blocks_root = root / "resources/data_refined/private/blocks"
        blocks_root.mkdir(parents=True)
        cases = []
        manifest = []
        for index, case_id in enumerate(("C21", "C22"), start=1):
            doc_id = f"doc_{index}"
            block_path = blocks_root / f"{doc_id}.jsonl"
            block_path.write_text(json.dumps({"block_id": f"b{index}"}) + "\n", encoding="utf-8")
            input_hash = str(index) * 64
            cases.append(
                {
                    "case_id": case_id,
                    "doc_id": doc_id,
                    "input_sha256": input_hash,
                    "expected_extractor": "rhwp",
                    "expected_status": "ok",
                    "expected_index_eligible": True,
                    "expected_block_count": 1,
                    "expected_primary_text_chars": 100 + index,
                    "expected_page_count": 10 + index,
                }
            )
            manifest.append(
                {
                    "doc_id": doc_id,
                    "input_hash": input_hash,
                    "status": "ok",
                    "extractor": "rhwp",
                    "index_eligible": True,
                    "block_count": 1,
                    "primary_text_chars": 100 + index,
                    "page_count": 10 + index,
                    "error_code": None,
                    "output_relpath": f"private/blocks/{doc_id}.jsonl",
                }
            )
        manifest_path = root / "resources/data_refined/private/manifest.extracted.jsonl"
        manifest_path.write_text("".join(json.dumps(row) + "\n" for row in manifest), encoding="utf-8")
        config = {
            "schema_version": "1.0",
            "baseline_id": "parser-regression-rhwp-v1",
            "contract": {
                "current_invariant": "canonical_rhwp_extraction_and_indexability",
                "legacy_fallback_activation_scored": False,
                "semantic_judge_required": False,
            },
            "artifacts": {
                "manifest": "resources/data_refined/private/manifest.extracted.jsonl",
                "manifest_sha256": sha256_file(manifest_path),
            },
            "cases": cases,
            "outputs": {"receipt": "evaluation/baselines/parser-regression-rhwp-v1/receipt.json"},
        }
        config_path = root / "evaluation/baselines/parser-regression-rhwp-v1/config.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(json.dumps(config), encoding="utf-8")
        return config_path

    def test_two_current_rhwp_cases_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._fixture(Path(directory))
            receipt = run(config_path)
            self.assertTrue(receipt["passed"])
            self.assertEqual(receipt["counts"], {"total": 2, "passed": 2, "failed": 0})
            self.assertFalse(receipt["scoring_contract"]["legacy_fallback_activation_scored"])

    def test_manifest_hash_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._fixture(Path(directory))
            manifest = Path(directory) / "resources/data_refined/private/manifest.extracted.jsonl"
            manifest.write_text(manifest.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "parser_regression_manifest_hash_mismatch"):
                run(config_path)


if __name__ == "__main__":
    unittest.main()
