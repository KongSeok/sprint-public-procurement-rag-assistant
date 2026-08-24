from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from midprojectrag.evaluation import _load_manifest_context, validate_dataset
from midprojectrag.ingest.common import write_jsonl
from tests.evaluation.helpers import make_cases


class DatasetValidationTests(unittest.TestCase):
    def test_balanced_synthetic_dataset_passes(self) -> None:
        minimums = {
            split: {task: 1 for task in ("single_doc", "multi_doc_compare", "follow_up", "unknown")}
            for split in ("dev", "heldout")
        }
        report = validate_dataset(make_cases("dev"), make_cases("heldout"), minimum_cases=minimums)
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["counts"]["total"], 8)
        self.assertEqual(len(report["dev_sha256"]), 64)
        self.assertEqual(len(report["heldout_sha256"]), 64)
        self.assertNotEqual(report["dev_sha256"], report["heldout_sha256"])

    def test_group_cannot_leak_between_splits(self) -> None:
        dev = make_cases("dev")
        heldout = make_cases("heldout")
        heldout[0]["group_id"] = dev[0]["group_id"]
        report = validate_dataset(dev, heldout)
        codes = {error["code"] for error in report["errors"]}
        self.assertFalse(report["passed"])
        self.assertIn("split_group_leakage", codes)

    def test_exact_question_cannot_leak_under_another_group(self) -> None:
        dev = make_cases("dev")
        heldout = make_cases("heldout")
        dev[0]["question"] = "  BUDGET   가  "
        heldout[0]["question"] = "budget 가"
        report = validate_dataset(dev, heldout)
        codes = {error["code"] for error in report["errors"]}
        self.assertIn("exact_question_leakage", codes)

    def test_evidence_locator_hash_must_match_stable_source_block(self) -> None:
        dev = make_cases("dev")
        heldout = make_cases("heldout")
        owners = {}
        locator_hashes = {}
        for case in dev + heldout:
            for reference in case["gold"]["evidence_refs"]:
                owners[reference["source_block_id"]] = reference["doc_id"]
                locator_hashes[reference["source_block_id"]] = reference["locator_hash"]
        dev[0]["gold"]["evidence_refs"][0]["locator_hash"] = "f" * 64

        report = validate_dataset(
            dev,
            heldout,
            block_owners=owners,
            block_locator_hashes=locator_hashes,
        )
        codes = {error["code"] for error in report["errors"]}
        self.assertIn("evidence_locator_hash_mismatch", codes)

    def test_non_object_row_returns_structured_failure(self) -> None:
        report = validate_dataset([None, *make_cases("dev")], make_cases("heldout"))
        codes = {error["code"] for error in report["errors"]}
        self.assertFalse(report["passed"])
        self.assertIn("invalid_case", codes)

    def test_unhashable_task_type_returns_structured_failure(self) -> None:
        dev = make_cases("dev")
        dev[0]["task_type"] = []
        report = validate_dataset(dev, make_cases("heldout"))
        self.assertFalse(report["passed"])
        self.assertIn("invalid_task_type", {error["code"] for error in report["errors"]})

    def test_blocks_symlink_cannot_escape_blocks_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.jsonl"
            blocks_dir = root / "blocks"
            blocks_dir.mkdir()
            write_jsonl(manifest, [{"doc_id": "doc_111111111111111111111111"}])
            outside = root / "outside.jsonl"
            write_jsonl(
                outside,
                [
                    {
                        "block_id": "block_111111111111111111111111",
                        "doc_id": "doc_111111111111111111111111",
                        "source_locator": "private-locator"
                    }
                ],
            )
            (blocks_dir / "linked.jsonl").symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "blocks_path_outside_directory"):
                _load_manifest_context(manifest, blocks_dir)


if __name__ == "__main__":
    unittest.main()
