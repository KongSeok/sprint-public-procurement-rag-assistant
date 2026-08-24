from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from midprojectrag.cli import main
from tests.ingest.helpers import write_hwp_stub, write_metadata_csv


class CliSmokeTests(unittest.TestCase):
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
