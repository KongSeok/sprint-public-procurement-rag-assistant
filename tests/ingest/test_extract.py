from __future__ import annotations

import importlib.metadata
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from midprojectrag.ingest.common import read_jsonl, write_jsonl
from midprojectrag.ingest.extract import _extract_pdf, extract_manifest
from midprojectrag.ingest.hwp_binary_text import main as hwp_binary_text_main
from midprojectrag.ingest.manifest import build_manifest
from midprojectrag.ingest.verify import verify_manifest
from tests.ingest.helpers import write_hwp_stub, write_metadata_csv


class ExtractionTests(unittest.TestCase):
    def _manifest(self, data_dir: Path) -> Path:
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
        manifest_path = data_dir / "private" / "manifest.jsonl"
        write_jsonl(manifest_path, result.entries)
        return manifest_path

    @patch(
        "midprojectrag.ingest.extract.importlib.metadata.version",
        side_effect=importlib.metadata.PackageNotFoundError,
    )
    @patch("midprojectrag.ingest.extract.shutil.which", return_value=None)
    def test_missing_hwp_dependency_is_a_manifest_failure_state(
        self,
        _which: object,
        _package_version: object,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            manifest_path = self._manifest(data_dir)
            output_dir = data_dir / "private" / "blocks"
            output_manifest = data_dir / "private" / "manifest.extracted.jsonl"

            summary = extract_manifest(
                manifest_path=manifest_path,
                data_dir=data_dir,
                output_dir=output_dir,
                output_manifest_path=output_manifest,
                timeout_seconds=10,
            )

            self.assertEqual(summary["status_counts"]["failed"], 1)
            entries = read_jsonl(output_manifest)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["error_code"], "hwp_extractor_unavailable")
            self.assertFalse(entries[0]["index_eligible"])

    @patch("midprojectrag.ingest.extract._hwp5txt_version", return_value="test-hwp5txt")
    @patch("midprojectrag.ingest.extract.shutil.which", return_value="/synthetic/hwp5txt")
    @patch("midprojectrag.ingest.extract.subprocess.run")
    def test_hwp_text_success_is_partial_until_page_table_provenance_exists(
        self,
        run: object,
        _which: object,
        _version: object,
    ) -> None:
        run.return_value = SimpleNamespace(returncode=0, stdout="첫 문단\n\n둘째 문단", stderr="")
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            manifest_path = self._manifest(data_dir)
            output_dir = data_dir / "private" / "blocks"
            output_manifest = data_dir / "private" / "manifest.extracted.jsonl"

            summary = extract_manifest(
                manifest_path=manifest_path,
                data_dir=data_dir,
                output_dir=output_dir,
                output_manifest_path=output_manifest,
                timeout_seconds=10,
            )

            self.assertEqual(summary["status_counts"]["partial"], 1)
            entries = read_jsonl(output_manifest)
            entry = entries[0]
            self.assertEqual(entry["block_count"], 2)
            self.assertTrue(entry["index_eligible"])
            self.assertIn("hwp_page_table_provenance_unavailable", entry["warnings"])

            report = verify_manifest(
                entries,
                blocks_dir=output_dir,
                expected_documents=1,
                expected_hwp=1,
                expected_pdf=0,
                require_extracted=True,
            )
            self.assertTrue(report["passed"])
            self.assertEqual(report["warnings"][0]["code"], "partial_extraction")

    @patch("midprojectrag.ingest.extract.importlib.metadata.version", return_value="0.1b15")
    @patch("midprojectrag.ingest.extract._hwp5txt_version", return_value="test-hwp5txt")
    @patch("midprojectrag.ingest.extract.shutil.which", return_value="/synthetic/hwp5txt")
    @patch("midprojectrag.ingest.extract.subprocess.run")
    def test_hwp_binary_model_fallback_recovers_primary_parser_failure(
        self,
        run: object,
        _which: object,
        _version: object,
        _package_version: object,
    ) -> None:
        run.side_effect = [
            SimpleNamespace(returncode=1, stdout="", stderr="primary failure"),
            SimpleNamespace(returncode=0, stdout="복구 문단\n\n둘째 문단", stderr=""),
        ]
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            manifest_path = self._manifest(data_dir)
            output_manifest = data_dir / "private" / "manifest.extracted.jsonl"

            summary = extract_manifest(
                manifest_path=manifest_path,
                data_dir=data_dir,
                output_dir=data_dir / "private" / "blocks",
                output_manifest_path=output_manifest,
                timeout_seconds=10,
            )

            self.assertEqual(summary["status_counts"]["partial"], 1)
            entry = read_jsonl(output_manifest)[0]
            self.assertEqual(entry["extractor"], "pyhwp-binmodel")
            self.assertEqual(entry["block_count"], 2)
            self.assertIn("hwp_binary_model_fallback", entry["warnings"])
            fallback_command = run.call_args_list[1].args[0]
            self.assertEqual(
                fallback_command[1:3],
                ["-m", "midprojectrag.ingest.hwp_binary_text"],
            )

    @patch("midprojectrag.ingest.extract.importlib.metadata.version", return_value="0.1b15")
    @patch("midprojectrag.ingest.extract._hwp5txt_version", return_value="test-hwp5txt")
    @patch("midprojectrag.ingest.extract.shutil.which", return_value="/synthetic/hwp5txt")
    @patch("midprojectrag.ingest.extract.subprocess.run")
    def test_hwp_fallback_parse_failure_has_distinct_safe_error(
        self,
        run: object,
        _which: object,
        _version: object,
        _package_version: object,
    ) -> None:
        run.side_effect = [
            SimpleNamespace(returncode=1, stdout="", stderr="primary failure"),
            SimpleNamespace(returncode=5, stdout="", stderr=""),
        ]
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            manifest_path = self._manifest(data_dir)
            output_manifest = data_dir / "private" / "manifest.extracted.jsonl"

            extract_manifest(
                manifest_path=manifest_path,
                data_dir=data_dir,
                output_dir=data_dir / "private" / "blocks",
                output_manifest_path=output_manifest,
                timeout_seconds=10,
            )

            entry = read_jsonl(output_manifest)[0]
            self.assertEqual(entry["error_code"], "hwp_fallback_parse_failed")
            self.assertFalse(entry["index_eligible"])

    @patch(
        "midprojectrag.ingest.hwp_binary_text.extract_paragraphs",
        side_effect=ModuleNotFoundError("dependency unavailable"),
    )
    def test_hwp_fallback_helper_reports_dependency_failure(self, _extract: object) -> None:
        self.assertEqual(hwp_binary_text_main(["synthetic.hwp"]), 4)

    @patch(
        "midprojectrag.ingest.hwp_binary_text.extract_paragraphs",
        side_effect=ValueError("private parser detail"),
    )
    def test_hwp_fallback_helper_reports_parse_failure_without_detail(
        self,
        _extract: object,
    ) -> None:
        self.assertEqual(hwp_binary_text_main(["synthetic.hwp"]), 5)

    @patch("midprojectrag.ingest.extract.shutil.which", return_value=None)
    def test_changed_source_hash_fails_before_adapter_runs(self, _which: object) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            manifest_path = self._manifest(data_dir)
            write_hwp_stub(data_dir / "files" / "Copy of sample.hwp", b"changed")
            output_manifest = data_dir / "private" / "manifest.extracted.jsonl"

            extract_manifest(
                manifest_path=manifest_path,
                data_dir=data_dir,
                output_dir=data_dir / "private" / "blocks",
                output_manifest_path=output_manifest,
            )

            entry = read_jsonl(output_manifest)[0]
            self.assertEqual(entry["error_code"], "source_hash_mismatch")
            self.assertFalse(entry["index_eligible"])

    def test_source_path_traversal_becomes_safe_failure_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            manifest_path = self._manifest(data_dir)
            entries = read_jsonl(manifest_path)
            entries[0]["source_relpath"] = "../outside.hwp"
            write_jsonl(manifest_path, entries)
            output_manifest = data_dir / "private" / "manifest.extracted.jsonl"

            extract_manifest(
                manifest_path=manifest_path,
                data_dir=data_dir,
                output_dir=data_dir / "private" / "blocks",
                output_manifest_path=output_manifest,
            )

            entry = read_jsonl(output_manifest)[0]
            self.assertEqual(entry["error_code"], "source_path_outside_data_dir")

    def test_output_path_cannot_escape_data_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_dir = root / "data"
            manifest_path = self._manifest(data_dir)

            with self.assertRaisesRegex(ValueError, "output_dir_outside_data_dir"):
                extract_manifest(
                    manifest_path=manifest_path,
                    data_dir=data_dir,
                    output_dir=root / "outside",
                    output_manifest_path=data_dir / "private" / "manifest.extracted.jsonl",
                )

    def test_textless_pdf_is_explicitly_rejected(self) -> None:
        from pypdf import PdfWriter

        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            raw_dir = data_dir / "files"
            raw_dir.mkdir(parents=True)
            pdf_path = raw_dir / "sample.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=72, height=72)
            with pdf_path.open("wb") as output:
                writer.write(output)
            csv_path = data_dir / "data_list.csv"
            write_metadata_csv(csv_path, ["sample.pdf"])
            result = build_manifest(
                data_dir=data_dir,
                csv_path=csv_path,
                raw_dir=raw_dir,
                expected_documents=1,
                expected_hwp=0,
                expected_pdf=1,
            )
            manifest_path = data_dir / "private" / "manifest.jsonl"
            write_jsonl(manifest_path, result.entries)
            output_manifest = data_dir / "private" / "manifest.extracted.jsonl"

            extract_manifest(
                manifest_path=manifest_path,
                data_dir=data_dir,
                output_dir=data_dir / "private" / "blocks",
                output_manifest_path=output_manifest,
            )

            entry = read_jsonl(output_manifest)[0]
            self.assertEqual(entry["error_code"], "pdf_no_text")
            self.assertIn("ocr_may_be_required", entry["warnings"])
            self.assertFalse(entry["index_eligible"])

    def test_large_pdf_result_is_received_before_worker_join(self) -> None:
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "large-result.pdf"
            writer = PdfWriter()
            page = writer.add_blank_page(width=612, height=792)
            page[NameObject("/Resources")] = DictionaryObject(
                {
                    NameObject("/Font"): DictionaryObject(
                        {
                            NameObject("/F1"): DictionaryObject(
                                {
                                    NameObject("/Type"): NameObject("/Font"),
                                    NameObject("/Subtype"): NameObject("/Type1"),
                                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                                }
                            )
                        }
                    )
                }
            )
            expected_text = "A" * (512 * 1024)
            content = DecodedStreamObject()
            content.set_data(f"BT /F1 12 Tf 10 700 Td ({expected_text}) Tj ET".encode("ascii"))
            page[NameObject("/Contents")] = writer._add_object(content)
            with pdf_path.open("wb") as output:
                writer.write(output)

            result = _extract_pdf(
                pdf_path,
                {"doc_id": "doc_111111111111111111111111"},
                timeout_seconds=10,
            )

            self.assertEqual(result.status, "ok")
            self.assertIsNone(result.error_code)
            self.assertGreaterEqual(sum(len(block["text"]) for block in result.blocks), len(expected_text))


if __name__ == "__main__":
    unittest.main()
