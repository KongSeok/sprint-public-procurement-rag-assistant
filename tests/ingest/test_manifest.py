from __future__ import annotations

import csv
import tempfile
import unicodedata
import unittest
from pathlib import Path

from midprojectrag.ingest.manifest import CSV_COLUMNS, OPTIONAL_CSV_COLUMNS, build_manifest
from midprojectrag.ingest.normalize import normalize_filename
from tests.ingest.helpers import write_hwp_stub, write_metadata_csv


class ManifestTests(unittest.TestCase):
    def test_normalize_filename_removes_one_transport_prefix_and_uses_nfc(self) -> None:
        decomposed = unicodedata.normalize("NFD", "가이드.hwp")
        self.assertEqual(normalize_filename(f"Copy of {decomposed}"), "가이드.hwp")
        self.assertEqual(normalize_filename(f"refined_{decomposed}"), "가이드.hwp")
        self.assertEqual(normalize_filename("Copy of Copy of sample.hwp"), "Copy of sample.hwp")
        self.assertEqual(normalize_filename("refined_refined_sample.hwp"), "refined_sample.hwp")
        self.assertEqual(normalize_filename("folder/sample.hwp"), "folder/sample.hwp")

    def test_manifest_joins_refined_prefix_without_changing_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            raw_dir = data_dir / "files"
            csv_path = data_dir / "refined_data_list.csv"
            write_hwp_stub(raw_dir / "refined_sample.hwp")
            write_metadata_csv(csv_path, ["refined_sample.hwp"])

            result = build_manifest(
                data_dir=data_dir,
                csv_path=csv_path,
                raw_dir=raw_dir,
                expected_documents=1,
                expected_hwp=1,
                expected_pdf=0,
            )

            self.assertTrue(result.passed)
            self.assertEqual(result.entries[0]["normalized_filename"], "sample.hwp")

    def test_manifest_accepts_materialized_body_larger_than_csv_default_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            raw_dir = data_dir / "files"
            csv_path = data_dir / "refined_data_list.csv"
            write_hwp_stub(raw_dir / "refined_sample.hwp")
            write_metadata_csv(csv_path, ["refined_sample.hwp"])
            content = csv_path.read_text(encoding="utf-8-sig")
            csv_path.write_text(
                content.replace("검색 본문으로 사용하지 않는 합성 미리보기", "가" * 150_000),
                encoding="utf-8-sig",
            )

            result = build_manifest(
                data_dir=data_dir,
                csv_path=csv_path,
                raw_dir=raw_dir,
                expected_documents=1,
                expected_hwp=1,
                expected_pdf=0,
            )

            self.assertTrue(result.passed)
            self.assertEqual(result.entries[0]["metadata"]["preview_chars"], 150_000)

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

    def test_manifest_preserves_optional_corrected_metadata_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            raw_dir = data_dir / "files"
            csv_path = data_dir / "data_list.csv"
            write_hwp_stub(raw_dir / "Copy of sample.hwp")
            write_metadata_csv(csv_path, ["sample.hwp"])
            with csv_path.open("r", encoding="utf-8-sig", newline="") as source:
                row = next(csv.DictReader(source))
            fieldnames = list(CSV_COLUMNS.values()) + list(OPTIONAL_CSV_COLUMNS.values())
            row.update(
                {
                    "공고 번호 체계": "g2b",
                    "개찰 일시": "2026-01-03 12:00:00",
                    "제안서 평가 일시": "2026-01-04 09:00:00",
                }
            )
            with csv_path.open("w", encoding="utf-8-sig", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow(row)

            result = build_manifest(
                data_dir=data_dir,
                csv_path=csv_path,
                raw_dir=raw_dir,
                expected_documents=1,
                expected_hwp=1,
                expected_pdf=0,
            )

            self.assertTrue(result.passed)
            metadata = result.entries[0]["metadata"]
            self.assertEqual(metadata["notice_id_namespace"], "g2b")
            self.assertEqual(metadata["bid_open_at"], "2026-01-03 12:00:00")
            self.assertEqual(metadata["proposal_evaluation_at"], "2026-01-04 09:00:00")


if __name__ == "__main__":
    unittest.main()
