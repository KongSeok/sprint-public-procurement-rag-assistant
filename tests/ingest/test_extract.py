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


VERIFIED_RHWP_IDENTITY = (
    "rhwp v0.8.4;adapter=1.0;sha256=" + "a" * 64 + ";verified=true;source=explicit"
)


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

    @patch("midprojectrag.ingest.extract.resolve_rhwp_command", return_value=None)
    @patch("midprojectrag.ingest.extract._hwp5txt_version", return_value="test-hwp5txt")
    @patch("midprojectrag.ingest.extract.shutil.which", return_value="/synthetic/hwp5txt")
    @patch("midprojectrag.ingest.extract.subprocess.run")
    def test_hwp_text_success_is_partial_until_page_table_provenance_exists(
        self,
        run: object,
        _which: object,
        _version: object,
        _rhwp: object,
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

    @patch(
        "midprojectrag.ingest.extract.resolve_rhwp_command",
        return_value="/synthetic/rhwp",
    )
    @patch(
        "midprojectrag.ingest.rhwp_adapter.rhwp_version",
        return_value=VERIFIED_RHWP_IDENTITY,
    )
    @patch("midprojectrag.ingest.rhwp_adapter._run_json")
    def test_rhwp_preserves_page_and_merged_table_contracts(
        self,
        run: object,
        _version: object,
        _resolve: object,
    ) -> None:
        text_payload = {
            "schemaVersion": "1.0",
            "pageCount": 2,
            "truncated": False,
            "omittedCount": 0,
            "pages": [
                {"page": 0, "text": "첫 페이지"},
                {"page": 1, "text": "둘째 페이지"},
            ],
        }
        table_payload = {
            "schemaVersion": "1.0",
            "tableCount": 1,
            "tables": [
                {
                    "index": 0,
                    "section": 0,
                    "paragraph": 7,
                    "rows": 2,
                    "cols": 3,
                    "cellCount": 2,
                    "caption": "지원 대상",
                    "cells": [
                        {
                            "row": 0,
                            "col": 0,
                            "rowSpan": 1,
                            "colSpan": 3,
                            "isHeader": True,
                            "text": "병합 헤더",
                        },
                        {
                            "row": 1,
                            "col": 0,
                            "rowSpan": 1,
                            "colSpan": 1,
                            "isHeader": False,
                            "text": "셀 값",
                            "nested": [
                                {
                                    "index": 0,
                                    "section": 0,
                                    "paragraph": 7,
                                    "rows": 1,
                                    "cols": 1,
                                    "cellCount": 1,
                                    "caption": "중첩 표",
                                    "control": 4,
                                    "containerPath": [
                                        {
                                            "kind": "tableCell",
                                            "paragraph": 7,
                                            "control": 3,
                                            "cell": 1,
                                        }
                                    ],
                                    "cells": [
                                        {
                                            "row": 0,
                                            "col": 0,
                                            "rowSpan": 1,
                                            "colSpan": 1,
                                            "isHeader": False,
                                            "text": "중첩 값",
                                        }
                                    ],
                                }
                            ],
                        },
                    ],
                }
            ],
        }
        run.side_effect = [(text_payload, None), (table_payload, None)]

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

            self.assertEqual(summary["status_counts"]["ok"], 1)
            entry = read_jsonl(output_manifest)[0]
            self.assertEqual(entry["extractor"], "rhwp")
            self.assertEqual(entry["page_count"], 2)
            self.assertEqual(entry["block_count"], 3)
            self.assertGreater(entry["primary_text_chars"], 0)
            self.assertGreater(entry["auxiliary_text_chars"], 0)
            self.assertEqual(
                entry["text_chars"],
                entry["primary_text_chars"] + entry["auxiliary_text_chars"],
            )
            self.assertIn("rhwp_table_page_bbox_unlinked", entry["warnings"])
            blocks = read_jsonl(output_dir / f"{entry['doc_id']}.jsonl")
            self.assertEqual(blocks[0]["source_locator"], "page:1")
            self.assertEqual(blocks[0]["page_start"], 1)
            self.assertEqual(blocks[1]["page_start"], 2)
            self.assertEqual(blocks[2]["block_type"], "table")
            self.assertEqual(blocks[0]["retrieval_role"], "primary")
            self.assertEqual(blocks[2]["retrieval_role"], "structured_auxiliary")
            self.assertEqual(
                blocks[2]["source_locator"],
                "section:1/paragraph:8/table:1",
            )
            self.assertEqual(
                blocks[2]["table_structure"]["cells"][0]["col_span"],
                3,
            )
            self.assertEqual(blocks[2]["table_structure"]["caption"], "지원 대상")
            nested = blocks[2]["table_structure"]["cells"][1]["nested"][0]
            self.assertEqual(nested["cell_count"], 1)
            self.assertEqual(nested["container_path"][0]["kind"], "tableCell")

            report = verify_manifest(
                [entry],
                blocks_dir=output_dir,
                expected_documents=1,
                expected_hwp=1,
                expected_pdf=0,
                require_extracted=True,
                require_primary_hwp=True,
                expected_rhwp_sha256="a" * 64,
            )
            self.assertTrue(report["passed"])

            blocks[2]["table_structure"]["cells"][0]["is_header"] = False
            write_jsonl(output_dir / f"{entry['doc_id']}.jsonl", blocks)
            forged_report = verify_manifest(
                [entry],
                blocks_dir=output_dir,
                expected_documents=1,
                expected_hwp=1,
                expected_pdf=0,
                require_extracted=True,
            )
            self.assertIn(
                "table_structure_hash_mismatch",
                {issue["code"] for issue in forged_report["errors"]},
            )

            blocks[2]["table_structure"]["cells"][0]["is_header"] = True
            blocks[2]["table_structure"]["cells"][0]["col_span"] = 0
            write_jsonl(output_dir / f"{entry['doc_id']}.jsonl", blocks)
            invalid_report = verify_manifest(
                [entry],
                blocks_dir=output_dir,
                expected_documents=1,
                expected_hwp=1,
                expected_pdf=0,
                require_extracted=True,
            )
            self.assertIn(
                "invalid_table_structure",
                {issue["code"] for issue in invalid_report["errors"]},
            )

    @patch(
        "midprojectrag.ingest.extract.resolve_rhwp_command",
        return_value="/synthetic/rhwp",
    )
    @patch(
        "midprojectrag.ingest.rhwp_adapter.rhwp_version",
        return_value=VERIFIED_RHWP_IDENTITY,
    )
    @patch("midprojectrag.ingest.rhwp_adapter._run_json")
    def test_rhwp_table_failure_keeps_page_text_as_partial(
        self,
        run: object,
        _version: object,
        _resolve: object,
    ) -> None:
        run.side_effect = [
            (
                {
                    "schemaVersion": "1.0",
                    "pageCount": 1,
                    "truncated": False,
                    "omittedCount": 0,
                    "pages": [{"page": 0, "text": "사용 가능한 페이지"}],
                },
                None,
            ),
            (None, "rhwp_tables_failed"),
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
            self.assertEqual(entry["status"], "partial")
            self.assertEqual(entry["extractor"], "rhwp")
            self.assertEqual(entry["block_count"], 1)
            self.assertIn("rhwp_tables_failed", entry["warnings"])

    @patch(
        "midprojectrag.ingest.extract.resolve_rhwp_command",
        return_value="/synthetic/rhwp",
    )
    @patch("midprojectrag.ingest.extract._hwp5txt_version", return_value="test-hwp5txt")
    @patch("midprojectrag.ingest.extract.shutil.which", return_value="/synthetic/hwp5txt")
    @patch(
        "midprojectrag.ingest.rhwp_adapter.rhwp_version",
        return_value=VERIFIED_RHWP_IDENTITY,
    )
    @patch("midprojectrag.ingest.rhwp_adapter._run_json")
    @patch("midprojectrag.ingest.extract.subprocess.run")
    def test_rhwp_primary_failure_uses_legacy_hwp_fallback(
        self,
        legacy_run: object,
        run_json: object,
        _rhwp_version: object,
        _which: object,
        _hwp5txt_version: object,
        _resolve: object,
    ) -> None:
        run_json.return_value = (None, "rhwp_text_failed")
        legacy_run.return_value = SimpleNamespace(
            returncode=0,
            stdout="legacy paragraph",
            stderr="",
        )
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
            self.assertEqual(entry["status"], "partial")
            self.assertEqual(entry["extractor"], "hwp5txt")
            self.assertIn("rhwp_primary_failed", entry["warnings"])
            self.assertIn("rhwp_text_failed", entry["warnings"])

    @patch("midprojectrag.ingest.extract.resolve_rhwp_command", return_value=None)
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
        _rhwp: object,
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

    @patch("midprojectrag.ingest.extract.resolve_rhwp_command", return_value=None)
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
        _rhwp: object,
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
