from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from midprojectrag.ingest.rhwp_adapter import (
    _normalize_pages,
    _normalize_table,
    _run_bounded,
    extract_rhwp,
    rhwp_version,
)


class RhwpAdapterTests(unittest.TestCase):
    def test_page_contract_rejects_truncation_and_missing_indices(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_pages(
                {
                    "pageCount": 1,
                    "truncated": True,
                    "omittedCount": 4,
                    "pages": [{"page": 0, "text": "잘린 본문"}],
                }
            )

        with self.assertRaises(ValueError):
            _normalize_pages(
                {
                    "pageCount": 2,
                    "truncated": False,
                    "omittedCount": 0,
                    "pages": [{"page": 0, "text": "첫 쪽"}],
                }
            )

    def test_table_contract_rejects_cell_count_mismatch_and_overlap(self) -> None:
        base_table = {
            "index": 0,
            "section": 0,
            "paragraph": 0,
            "rows": 2,
            "cols": 2,
            "cellCount": 1,
            "cells": [
                {
                    "row": 0,
                    "col": 0,
                    "rowSpan": 1,
                    "colSpan": 1,
                    "isHeader": False,
                    "text": "값",
                }
            ],
        }
        count_mismatch = dict(base_table)
        count_mismatch["cellCount"] = 2
        with self.assertRaises(ValueError):
            _normalize_table(count_mismatch)

        overlapping = dict(base_table)
        overlapping["cellCount"] = 2
        overlapping["cells"] = [
            {
                "row": 0,
                "col": 0,
                "rowSpan": 1,
                "colSpan": 2,
                "isHeader": True,
                "text": "병합",
            },
            {
                "row": 0,
                "col": 1,
                "rowSpan": 1,
                "colSpan": 1,
                "isHeader": False,
                "text": "겹침",
            },
        ]
        with self.assertRaises(ValueError):
            _normalize_table(overlapping)

        header_table = dict(base_table)
        header_table["containerPath"] = [
            {"kind": "header", "paragraph": 0, "control": 0}
        ]
        normalized = _normalize_table(header_table)
        self.assertNotIn("cell", normalized["container_path"][0])

    def test_bounded_runner_stops_oversized_stdout(self) -> None:
        returncode, output, error = _run_bounded(
            [sys.executable, "-c", "import sys; sys.stdout.write('x' * 4096)"],
            timeout_seconds=5,
            max_stdout_bytes=16,
        )
        self.assertIsNone(returncode)
        self.assertLessEqual(len(output), 16)
        self.assertEqual(error, "stdout_too_large")

    @patch("midprojectrag.ingest.rhwp_adapter._run_bounded")
    def test_checksum_mismatch_is_not_executed(self, run_bounded: object) -> None:
        with patch.dict(
            os.environ,
            {
                "MIDPROJECTRAG_RHWP_BIN": sys.executable,
                "MIDPROJECTRAG_RHWP_SHA256": "0" * 64,
            },
        ):
            identity = rhwp_version(sys.executable)

        self.assertIn("not_run;adapter=1.0", identity)
        self.assertIn("verified=false;source=explicit", identity)
        run_bounded.assert_not_called()

    @patch("midprojectrag.ingest.rhwp_adapter._run_json")
    @patch(
        "midprojectrag.ingest.rhwp_adapter.rhwp_version",
        return_value=(
            "not_run;adapter=1.0;sha256="
            + "0" * 64
            + ";verified=false;source=explicit"
        ),
    )
    def test_unverified_production_identity_stops_before_document_parse(
        self,
        _version: object,
        run_json: object,
    ) -> None:
        with patch.dict(
            os.environ,
            {"MIDPROJECTRAG_RHWP_SHA256": "a" * 64},
        ):
            attempt = extract_rhwp("/synthetic/rhwp", Path("synthetic.hwp"), 5)

        self.assertEqual(attempt.status, "failed")
        self.assertEqual(attempt.error_code, "rhwp_binary_unverified")
        run_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()
