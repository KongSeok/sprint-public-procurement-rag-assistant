from __future__ import annotations

import tempfile
import unicodedata
import unittest
from pathlib import Path

from midprojectrag.ingest.manifest import build_manifest
from midprojectrag.ingest.normalize import normalize_filename
from tests.ingest.helpers import write_hwp_stub, write_metadata_csv


class ManifestTests(unittest.TestCase):
    def test_normalize_filename_removes_one_copy_prefix_and_uses_nfc(self) -> None:
        decomposed = unicodedata.normalize("NFD", "가이드.hwp")
        self.assertEqual(normalize_filename(f"Copy of {decomposed}"), "가이드.hwp")
        self.assertEqual(normalize_filename("Copy of Copy of sample.hwp"), "Copy of sample.hwp")
        self.assertEqual(normalize_filename("folder/sample.hwp"), "folder/sample.hwp")

    def test_manifest_joins_copy_prefix_and_hashes_preview(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            raw_dir = data_dir / "files"
            csv_path = data_dir / "data_list.csv"
            write_hwp_stub(raw_dir / "Copy of sample.hwp")
            write_metadata_csv(csv_path, ["sample.hwp"])

            result = build_manifest(
                data_dir=data_dir,
                csv_path=csv_path,
                raw_dir=raw_dir,
                expected_documents=1,
                expected_hwp=1,
                expected_pdf=0,
            )

            self.assertTrue(result.passed)
            self.assertEqual(len(result.entries), 1)
            entry = result.entries[0]
            self.assertEqual(entry["normalized_filename"], "sample.hwp")
            self.assertEqual(entry["status"], "pending")
            self.assertFalse(entry["index_eligible"])
            self.assertGreater(entry["metadata"]["preview_chars"], 0)
            self.assertNotIn("text_preview", entry["metadata"])

    def test_manifest_reports_normalized_filename_collision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            raw_dir = data_dir / "files"
            csv_path = data_dir / "data_list.csv"
            write_hwp_stub(raw_dir / "sample.hwp", b"one")
            write_hwp_stub(raw_dir / "Copy of sample.hwp", b"two")
            write_metadata_csv(csv_path, ["sample.hwp"])

            result = build_manifest(
                data_dir=data_dir,
                csv_path=csv_path,
                raw_dir=raw_dir,
                expected_documents=2,
                expected_hwp=2,
                expected_pdf=0,
            )

            codes = {error["code"] for error in result.report["errors"]}
            self.assertIn("raw_filename_collision", codes)
            self.assertFalse(result.passed)
            self.assertEqual(result.entries, [])

    def test_manifest_rejects_symlink_escape_without_reading_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_dir = root / "data"
            raw_dir = data_dir / "files"
            csv_path = data_dir / "data_list.csv"
            outside = root / "outside.hwp"
            write_hwp_stub(outside)
            raw_dir.mkdir(parents=True)
            (raw_dir / "outside.hwp").symlink_to(outside)
            write_metadata_csv(csv_path, ["outside.hwp"])

            result = build_manifest(
                data_dir=data_dir,
                csv_path=csv_path,
                raw_dir=raw_dir,
                expected_documents=1,
                expected_hwp=1,
                expected_pdf=0,
            )

            codes = {error["code"] for error in result.report["errors"]}
            self.assertIn("source_path_outside_data_dir", codes)
            self.assertEqual(result.entries, [])

    def test_manifest_rejects_raw_directory_outside_data_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_dir = root / "data"
            data_dir.mkdir()
            csv_path = data_dir / "data_list.csv"
            write_metadata_csv(csv_path, [])
            outside_raw = root / "files"
            outside_raw.mkdir()

            with self.assertRaisesRegex(ValueError, "raw_dir_outside_data_dir"):
                build_manifest(
                    data_dir=data_dir,
                    csv_path=csv_path,
                    raw_dir=outside_raw,
                    expected_documents=0,
                    expected_hwp=0,
                    expected_pdf=0,
                )

    def test_snapshot_changes_when_csv_metadata_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            raw_dir = data_dir / "files"
            csv_path = data_dir / "data_list.csv"
            write_hwp_stub(raw_dir / "sample.hwp")
            write_metadata_csv(csv_path, ["sample.hwp"])
            first = build_manifest(
                data_dir=data_dir,
                csv_path=csv_path,
                raw_dir=raw_dir,
                expected_documents=1,
                expected_hwp=1,
                expected_pdf=0,
            )

            csv_content = csv_path.read_text(encoding="utf-8-sig")
            csv_path.write_text(
                csv_content.replace("합성 사업 1", "변경된 합성 사업"),
                encoding="utf-8-sig",
            )
            second = build_manifest(
                data_dir=data_dir,
                csv_path=csv_path,
                raw_dir=raw_dir,
                expected_documents=1,
                expected_hwp=1,
                expected_pdf=0,
            )

            self.assertNotEqual(first.report["snapshot_id"], second.report["snapshot_id"])


if __name__ == "__main__":
    unittest.main()
