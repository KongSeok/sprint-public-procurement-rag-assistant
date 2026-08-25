from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from midprojectrag.ingest.common import sha256_text, write_jsonl
from midprojectrag.ingest.verify import verify_manifest
from midprojectrag.ingest.verify import REQUIRED_MANIFEST_FIELDS


VERIFIED_RHWP_IDENTITY = (
    "rhwp v0.8.4;adapter=1.0;sha256=" + "a" * 64 + ";verified=true;source=explicit"
)


class VerificationTests(unittest.TestCase):
    def _entry(self, **overrides: object) -> dict[str, object]:
        entry: dict[str, object] = {
            "schema_version": "1.0",
            "snapshot_id": "snapshot_" + "a" * 24,
            "doc_id": "doc_" + "b" * 24,
            "source_relpath": "files/sample.hwp",
            "source_filename": "sample.hwp",
            "normalized_filename": "sample.hwp",
            "extension": ".hwp",
            "mime_type": "application/x-hwp-ole",
            "size_bytes": 8,
            "sha256": "c" * 64,
            "csv_row_number": 2,
            "metadata": {},
            "extractor": "test",
            "extractor_version": "1",
            "input_hash": "d" * 64,
            "status": "ok",
            "error_code": None,
            "warnings": [],
            "page_count": None,
            "block_count": 1,
            "text_chars": 3,
            "primary_text_chars": 3,
            "auxiliary_text_chars": 0,
            "output_relpath": "private/blocks/doc_bbbbbbbbbbbbbbbbbbbbbbbb.jsonl",
            "index_eligible": True,
            "pii_counts": {},
            "created_at": "2026-08-24T00:00:00Z",
        }
        entry.update(overrides)
        return entry

    def test_count_mismatch_fails_closed(self) -> None:
        report = verify_manifest([], expected_documents=1, expected_hwp=1, expected_pdf=0)
        self.assertFalse(report["passed"])
        codes = {error["code"] for error in report["errors"]}
        self.assertIn("document_count_mismatch", codes)
        self.assertIn("hwp_count_mismatch", codes)

    def test_contract_schema_files_are_valid_json_and_have_required_keys(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        for filename in ("manifest.schema.json", "source-block.schema.json"):
            schema = json.loads((project_root / "contracts" / filename).read_text(encoding="utf-8"))
            self.assertEqual(schema["type"], "object")
            self.assertIn("schema_version", schema["required"])
            self.assertFalse(schema["additionalProperties"])
        manifest_schema = json.loads(
            (project_root / "contracts" / "manifest.schema.json").read_text(encoding="utf-8")
        )
        source_block_schema = json.loads(
            (project_root / "contracts" / "source-block.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(REQUIRED_MANIFEST_FIELDS <= set(manifest_schema["required"]))
        self.assertEqual(len(manifest_schema["allOf"]), 3)
        self.assertIn("table_structure", source_block_schema["properties"])
        self.assertIn("structure_sha256", source_block_schema["properties"])
        self.assertIn("retrieval_role", source_block_schema["required"])
        self.assertIn("tableStructure", source_block_schema["$defs"])

    def test_require_extracted_needs_blocks_directory(self) -> None:
        report = verify_manifest(
            [],
            expected_documents=0,
            expected_hwp=0,
            expected_pdf=0,
            require_extracted=True,
        )
        self.assertFalse(report["passed"])
        self.assertIn("blocks_dir_required", {error["code"] for error in report["errors"]})

    def test_primary_hwp_gate_rejects_legacy_partial_manifest(self) -> None:
        entry = self._entry(
            status="partial",
            extractor="hwp5txt",
            extractor_version="test-hwp5txt",
            warnings=["hwp_page_table_provenance_unavailable"],
        )
        report = verify_manifest(
            [entry],
            expected_documents=1,
            expected_hwp=1,
            expected_pdf=0,
            require_primary_hwp=True,
            expected_rhwp_sha256="a" * 64,
        )
        codes = {error["code"] for error in report["errors"]}
        self.assertIn("hwp_primary_not_ok", codes)
        self.assertIn("hwp_primary_extractor_required", codes)
        self.assertIn("hwp_primary_version_mismatch", codes)

    def test_primary_hwp_gate_also_requires_block_verification(self) -> None:
        entry = self._entry(
            extractor="rhwp",
            extractor_version=VERIFIED_RHWP_IDENTITY,
        )
        report = verify_manifest(
            [entry],
            expected_documents=1,
            expected_hwp=1,
            expected_pdf=0,
            require_primary_hwp=True,
            expected_rhwp_sha256="a" * 64,
        )
        self.assertIn(
            "blocks_dir_required",
            {error["code"] for error in report["errors"]},
        )

    def test_primary_hwp_gate_rejects_non_allowlisted_checksum(self) -> None:
        entry = self._entry(
            extractor="rhwp",
            extractor_version=VERIFIED_RHWP_IDENTITY,
        )
        report = verify_manifest(
            [entry],
            expected_documents=1,
            expected_hwp=1,
            expected_pdf=0,
            require_primary_hwp=True,
            expected_rhwp_sha256="f" * 64,
        )
        self.assertIn(
            "hwp_primary_checksum_mismatch",
            {error["code"] for error in report["errors"]},
        )

    def test_primary_hwp_gate_requires_checksum_allowlist(self) -> None:
        entry = self._entry(
            extractor="rhwp",
            extractor_version=VERIFIED_RHWP_IDENTITY,
        )
        report = verify_manifest(
            [entry],
            expected_documents=1,
            expected_hwp=1,
            expected_pdf=0,
            require_primary_hwp=True,
        )
        self.assertIn(
            "hwp_primary_checksum_required",
            {error["code"] for error in report["errors"]},
        )

    @patch("midprojectrag.ingest.verify.read_jsonl")
    def test_invalid_doc_id_never_becomes_a_blocks_path(self, read_jsonl: object) -> None:
        entry = self._entry(doc_id="../../outside")
        report = verify_manifest(
            [entry],
            blocks_dir=Path("/unused"),
            expected_documents=1,
            expected_hwp=1,
            expected_pdf=0,
            require_extracted=True,
        )
        self.assertFalse(report["passed"])
        self.assertIn("invalid_doc_id", {error["code"] for error in report["errors"]})
        read_jsonl.assert_not_called()

    def test_invalid_block_provenance_fails_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            blocks_dir = Path(directory)
            entry = self._entry()
            doc_id = str(entry["doc_id"])
            text = "본문"
            write_jsonl(
                blocks_dir / f"{doc_id}.jsonl",
                [
                    {
                        "schema_version": "1.0",
                        "block_id": "not-a-block-id",
                        "doc_id": doc_id,
                        "sequence": 0,
                        "block_type": "paragraph",
                        "section_path": [],
                        "page_start": None,
                        "page_end": None,
                        "bbox": None,
                        "text": text,
                        "content_sha256": sha256_text(text),
                        "extractor": "",
                        "extractor_version": "",
                        "source_locator": "",
                        "retrieval_role": "primary",
                    }
                ],
            )
            entry["text_chars"] = len(text)
            entry["primary_text_chars"] = len(text)

            report = verify_manifest(
                [entry],
                blocks_dir=blocks_dir,
                expected_documents=1,
                expected_hwp=1,
                expected_pdf=0,
                require_extracted=True,
            )

            codes = {error["code"] for error in report["errors"]}
            self.assertIn("invalid_block_id", codes)
            self.assertIn("block_extractor_missing", codes)
            self.assertIn("block_locator_missing", codes)

    def test_malformed_manifest_returns_report_instead_of_raising(self) -> None:
        report = verify_manifest(
            [{"status": "pending", "doc_id": [], "extension": []}],
            expected_documents=1,
            expected_hwp=0,
            expected_pdf=0,
            require_extracted=True,
        )
        self.assertFalse(report["passed"])
        codes = {error["code"] for error in report["errors"]}
        self.assertIn("manifest_required_fields_missing", codes)
        self.assertIn("invalid_doc_id", codes)

    def test_valid_shape_but_forged_block_provenance_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            blocks_dir = Path(directory)
            entry = self._entry()
            doc_id = str(entry["doc_id"])
            text = "본문"
            write_jsonl(
                blocks_dir / f"{doc_id}.jsonl",
                [
                    {
                        "schema_version": "1.0",
                        "block_id": "block_" + "e" * 24,
                        "doc_id": doc_id,
                        "sequence": 0,
                        "block_type": "paragraph",
                        "section_path": [],
                        "page_start": None,
                        "page_end": None,
                        "bbox": None,
                        "text": text,
                        "content_sha256": sha256_text(text),
                        "extractor": "forged-parser",
                        "extractor_version": "999",
                        "source_locator": "paragraph:1",
                        "retrieval_role": "primary",
                    }
                ],
            )
            entry["text_chars"] = len(text)
            entry["primary_text_chars"] = len(text)

            report = verify_manifest(
                [entry],
                blocks_dir=blocks_dir,
                expected_documents=1,
                expected_hwp=1,
                expected_pdf=0,
                require_extracted=True,
            )

            codes = {error["code"] for error in report["errors"]}
            self.assertIn("block_id_mismatch", codes)
            self.assertIn("block_extractor_mismatch", codes)
            self.assertIn("block_extractor_version_mismatch", codes)

    def test_blocks_symlink_cannot_escape_blocks_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blocks_dir = root / "blocks"
            blocks_dir.mkdir()
            entry = self._entry()
            doc_id = str(entry["doc_id"])
            outside = root / "outside.jsonl"
            write_jsonl(outside, [])
            (blocks_dir / f"{doc_id}.jsonl").symlink_to(outside)

            report = verify_manifest(
                [entry],
                blocks_dir=blocks_dir,
                expected_documents=1,
                expected_hwp=1,
                expected_pdf=0,
                require_extracted=True,
            )

            self.assertFalse(report["passed"])
            self.assertIn(
                "blocks_path_outside_directory",
                {error["code"] for error in report["errors"]},
            )


if __name__ == "__main__":
    unittest.main()
