from __future__ import annotations

import io
import csv
import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from midprojectrag.cli import build_parser, main
from midprojectrag.ingest.common import canonical_json, sha256_file, sha256_text, write_jsonl
from tests.ingest.helpers import write_hwp_stub, write_metadata_csv
from midprojectrag.ingest.manifest import CSV_COLUMNS
from midprojectrag.ingest.metadata_corrections import source_row_sha256


class CliSmokeTests(unittest.TestCase):
    def test_visual_v2_commands_are_registered_with_fail_closed_inputs(self) -> None:
        parser = build_parser()
        pdf = parser.parse_args(
            [
                "pdf-visual-v2",
                "--data-dir",
                "/tmp/data",
                "--manifest",
                "/tmp/data/private/manifest.jsonl",
                "--output-dir",
                "/tmp/data/private/pdf-v2",
            ]
        )
        self.assertEqual(pdf.command, "pdf-visual-v2")
        self.assertEqual(pdf.render_scale, 2.0)

        hwp = parser.parse_args(
            [
                "hwp-visual-v2",
                "--data-dir",
                "/tmp/data",
                "--manifest",
                "/tmp/data/private/manifest.jsonl",
                "--blocks-dir",
                "/tmp/data/private/blocks",
                "--selection",
                "/tmp/data/private/selection.json",
                "--output-dir",
                "/tmp/data/private/hwp-v2",
                "--node-executable",
                "/usr/local/bin/node",
                "--node-sha256",
                "1" * 64,
                "--helper",
                "/tmp/helper.mjs",
                "--helper-sha256",
                "2" * 64,
                "--core-js",
                "/tmp/rhwp.js",
                "--core-js-sha256",
                "3" * 64,
                "--wasm",
                "/tmp/rhwp.wasm",
                "--wasm-sha256",
                "4" * 64,
                "--canvas-module",
                "/tmp/canvas.js",
                "--canvas-module-sha256",
                "5" * 64,
            ]
        )
        self.assertEqual(hwp.command, "hwp-visual-v2")
        self.assertEqual(hwp.mode, "representative")

        understanding = parser.parse_args(
            [
                "visual-understand",
                "--private-root",
                "/tmp/data/private",
                "--occurrences",
                "/tmp/data/private/occurrences.jsonl",
                "--output-root",
                "/tmp/data/private/understanding",
                "--ocr-config",
                "/tmp/data/private/ocr.json",
                "--ocr-command",
                "/tmp/data/private/ocr-command",
                "--ocr-command-sha256",
                "1" * 64,
                "--ocr-model-artifact",
                "/tmp/data/private/model-manifest.json",
                "--network-sandbox-backend",
                "darwin-sandbox-exec-v1",
                "--network-sandbox-command",
                "/usr/bin/sandbox-exec",
                "--network-sandbox-command-sha256",
                "2" * 64,
            ]
        )
        self.assertEqual(understanding.command, "visual-understand")
        self.assertEqual(understanding.caption_weight, 0.35)

    def test_pdf_visual_v2_stdout_is_aggregate_only(self) -> None:
        result = {
            "schema_version": "2.0",
            "artifact_set_id": "visualv2_" + "1" * 24,
            "document_count": 4,
            "occurrence_count": 12,
            "artifact_hashes": {"occurrences": "2" * 64},
        }
        output = io.StringIO()
        with (
            patch(
                "midprojectrag.ingest.pdf_visual_runner.run_pdf_visual_v2_from_manifest",
                return_value=result,
            ),
            redirect_stdout(output),
        ):
            code = main(
                [
                    "pdf-visual-v2",
                    "--data-dir",
                    "/private-canary/data",
                    "--manifest",
                    "/private-canary/data/private/manifest.jsonl",
                    "--output-dir",
                    "/private-canary/data/private/pdf-v2",
                ]
            )
        self.assertEqual(code, 0)
        summary = json.loads(output.getvalue())
        self.assertTrue(summary["passed"])
        self.assertEqual(summary["document_count"], 4)
        self.assertNotIn("private-canary", output.getvalue())

    def test_hwp_visual_v2_stdout_is_aggregate_only(self) -> None:
        result = {
            "schema_version": "2.0",
            "artifact_set_id": "visualv2_" + "1" * 24,
            "document_count": 5,
            "occurrence_count": 12,
            "artifact_hashes": {"occurrences": "2" * 64},
        }
        output = io.StringIO()
        with (
            patch(
                "midprojectrag.ingest.hwp_visual_runner.run_hwp_visual_v2_from_manifest",
                return_value=result,
            ),
            redirect_stdout(output),
        ):
            code = main(
                [
                    "hwp-visual-v2",
                    "--data-dir",
                    "/private-canary/data",
                    "--manifest",
                    "/private-canary/data/private/manifest.jsonl",
                    "--blocks-dir",
                    "/private-canary/data/private/blocks",
                    "--selection",
                    "/private-canary/data/private/selection.json",
                    "--output-dir",
                    "/private-canary/data/private/hwp-v2",
                    "--node-executable",
                    "/private-canary/tools/node",
                    "--node-sha256",
                    "1" * 64,
                    "--helper",
                    "/private-canary/tools/helper.mjs",
                    "--helper-sha256",
                    "2" * 64,
                    "--core-js",
                    "/private-canary/tools/rhwp.js",
                    "--core-js-sha256",
                    "3" * 64,
                    "--wasm",
                    "/private-canary/tools/rhwp.wasm",
                    "--wasm-sha256",
                    "4" * 64,
                    "--canvas-module",
                    "/private-canary/tools/canvas.js",
                    "--canvas-module-sha256",
                    "5" * 64,
                ]
            )
        self.assertEqual(code, 0)
        summary = json.loads(output.getvalue())
        self.assertTrue(summary["passed"])
        self.assertEqual(summary["document_count"], 5)
        self.assertNotIn("private-canary", output.getvalue())

    def test_table_layout_writes_only_aggregate_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            private = data_dir / "private"
            blocks_dir = private / "blocks"
            files_dir = data_dir / "files"
            blocks_dir.mkdir(parents=True)
            files_dir.mkdir()
            command = private / "rhwp"
            command.write_bytes(b"binary")
            source = files_dir / "private-layout-canary.hwp"
            source.write_bytes(b"source")
            doc_id = "doc_0123456789abcdef01234567"
            structure = {
                "index": 0,
                "section": 0,
                "paragraph": 7,
                "control": 0,
                "rows": 1,
                "cols": 1,
                "cell_count": 1,
                "cells": [
                    {
                        "row": 0,
                        "col": 0,
                        "row_span": 1,
                        "col_span": 1,
                        "is_header": False,
                        "text": "private-cell-canary",
                    }
                ],
            }
            manifest = private / "manifest.jsonl"
            write_jsonl(
                manifest,
                [
                    {
                        "doc_id": doc_id,
                        "status": "ok",
                        "index_eligible": True,
                        "extension": ".hwp",
                        "source_relpath": "files/private-layout-canary.hwp",
                        "sha256": sha256_file(source),
                    }
                ],
            )
            write_jsonl(
                blocks_dir / f"{doc_id}.jsonl",
                [
                    {
                        "doc_id": doc_id,
                        "block_id": "block_0123456789abcdef01234567",
                        "block_type": "table",
                        "structure_sha256": sha256_text(canonical_json(structure)),
                        "table_structure": structure,
                    }
                ],
            )
            dump_pages = {
                "schemaVersion": "1.0",
                "pageCount": 1,
                "pages": [
                    {
                        "pageIndex": 0,
                        "pageNumber": 88,
                        "section": 0,
                        "columns": [
                            {
                                "items": [
                                    {
                                        "kind": "table",
                                        "paraIndex": 7,
                                        "controlIndex": 0,
                                    }
                                ]
                            }
                        ],
                    }
                ],
            }
            render_trees = {
                0: {
                    "type": "Page",
                    "bbox": {"x": 0, "y": 0, "w": 100, "h": 100},
                    "children": [
                        {
                            "type": "Body",
                            "children": [
                                {
                                    "type": "Table",
                                    "pi": 7,
                                    "ci": 0,
                                    "rows": 1,
                                    "cols": 1,
                                    "bbox": {"x": 10, "y": 10, "w": 20, "h": 20},
                                    "children": [],
                                }
                            ],
                        }
                    ],
                }
            }
            output = private / "table-layout-v1.jsonl"
            stdout = io.StringIO()
            with (
                patch(
                    "midprojectrag.ingest.rhwp_adapter.resolve_rhwp_command",
                    return_value=str(command.resolve()),
                ),
                patch(
                    "midprojectrag.ingest.rhwp_adapter.rhwp_version",
                    return_value=(
                        "rhwp v0.8.4;adapter=1.0;sha256="
                        + "a" * 64
                        + ";verified=true;source=explicit"
                    ),
                ),
                patch(
                    "midprojectrag.ingest.table_layout.load_rhwp_layout_inputs",
                    return_value=(dump_pages, render_trees),
                ),
                redirect_stdout(stdout),
            ):
                code = main(
                    [
                        "table-layout",
                        "--data-dir",
                        str(data_dir),
                        "--manifest",
                        str(manifest),
                        "--blocks-dir",
                        str(blocks_dir),
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 0)
            summary = json.loads(stdout.getvalue())
            self.assertEqual(summary["page_linked"], 1)
            self.assertNotIn("private-layout-canary", stdout.getvalue())
            self.assertNotIn("private-cell-canary", stdout.getvalue())
            self.assertTrue(output.is_file())

    def test_correct_metadata_stdout_is_aggregate_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            source = data_dir / "data_list.csv"
            write_metadata_csv(source, ["sample.hwp"])
            with source.open("r", encoding="utf-8-sig", newline="") as input_file:
                row = next(csv.DictReader(input_file))
            fieldnames = list(CSV_COLUMNS.values())
            private_name = "private-source-name-canary.hwp"
            row["파일명"] = private_name
            with source.open("w", encoding="utf-8-sig", newline="") as output_file:
                writer = csv.DictWriter(output_file, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow(row)
            correction_set = data_dir / "private" / "corrections.json"
            correction_set.parent.mkdir(parents=True)
            correction_set.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "source_csv_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        "created_at": "2026-08-26T00:00:00Z",
                        "corrections": [
                            {
                                "correction_id": "corr_amount",
                                "csv_row_number": 2,
                                "row_sha256": source_row_sha256(row, fieldnames),
                                "field": "project_amount_raw",
                                "old_value": "1000000",
                                "new_value": "57000000",
                                "decision": "apply",
                                "reason_code": "official_source_confirmed",
                                "confidence": "high",
                                "checked_at": "2026-08-26",
                                "evidence": [
                                    {
                                        "source_type": "official_web",
                                        "locator": "https://example.org/private-canary",
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "correct-metadata",
                        "--data-dir",
                        str(data_dir),
                        "--corrections",
                        str(correction_set),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertNotIn(private_name, stdout.getvalue())
            self.assertNotIn("57000000", stdout.getvalue())
            self.assertNotIn("example.org", stdout.getvalue())

    def test_manifest_then_verify_pending_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            write_hwp_stub(data_dir / "files" / "Copy of sample.hwp")
            write_metadata_csv(data_dir / "data_list.csv", ["sample.hwp"])
            manifest_path = data_dir / "private" / "manifest.jsonl"

            with redirect_stdout(io.StringIO()):
                manifest_exit = main(
                    [
                        "manifest",
                        "--data-dir",
                        str(data_dir),
                        "--output",
                        str(manifest_path),
                        "--expected-documents",
                        "1",
                        "--expected-hwp",
                        "1",
                        "--expected-pdf",
                        "0",
                    ]
                )
                verify_exit = main(
                    [
                        "verify",
                        "--manifest",
                        str(manifest_path),
                        "--expected-documents",
                        "1",
                        "--expected-hwp",
                        "1",
                        "--expected-pdf",
                        "0",
                    ]
                )

            self.assertEqual(manifest_exit, 0)
            self.assertEqual(verify_exit, 0)
            self.assertTrue(manifest_path.is_file())

    @patch("midprojectrag.ingest.extract.shutil.which", return_value=None)
    def test_extract_stdout_does_not_disclose_private_absolute_path(self, _which: object) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            write_hwp_stub(data_dir / "files" / "Copy of sample.hwp")
            write_metadata_csv(data_dir / "data_list.csv", ["sample.hwp"])
            manifest_path = data_dir / "private" / "manifest.jsonl"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(
                        [
                            "manifest",
                            "--data-dir",
                            str(data_dir),
                            "--output",
                            str(manifest_path),
                            "--expected-documents",
                            "1",
                            "--expected-hwp",
                            "1",
                            "--expected-pdf",
                            "0",
                        ]
                    ),
                    0,
                )

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "extract",
                        "--manifest",
                        str(manifest_path),
                        "--data-dir",
                        str(data_dir),
                        "--output-dir",
                        str(data_dir / "private" / "blocks"),
                        "--output-manifest",
                        str(data_dir / "private" / "manifest.extracted.jsonl"),
                    ]
                )

            self.assertEqual(exit_code, 3)
            self.assertNotIn(str(data_dir), output.getvalue())


if __name__ == "__main__":
    unittest.main()
