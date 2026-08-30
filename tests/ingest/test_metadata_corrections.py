from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from midprojectrag.ingest.manifest import CSV_COLUMNS
from midprojectrag.ingest.metadata_corrections import (
    OPEN_AT_COLUMN,
    apply_metadata_corrections,
    source_row_sha256,
)


FIELDNAMES = list(CSV_COLUMNS.values())


def _row(*, start: str = "", end: str = "2026-01-03 12:00:00") -> dict[str, str]:
    return {
        "공고 번호": "NOTICE-001",
        "공고 차수": "00",
        "사업명": "합성 사업",
        "사업 금액": "1000000",
        "발주 기관": "합성 기관",
        "공개 일자": "2026-01-01 00:00:00",
        "입찰 참여 시작일": start,
        "입찰 참여 마감일": end,
        "사업 요약": "공개 테스트용 합성 요약",
        "파일형식": "hwp",
        "파일명": "sample.hwp",
        "텍스트": "검색에 사용하지 않는 합성 미리보기",
    }


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def _evidence(source_type: str = "official_web") -> list[dict[str, str]]:
    return [{"source_type": source_type, "locator": "https://example.org/notice/1"}]


def _correction(
    row: dict[str, str],
    *,
    correction_id: str,
    field: str,
    old_value: str | None,
    new_value: str | None,
    decision: str = "apply",
    reason_code: str = "official_source_confirmed",
    confidence: str = "high",
    evidence: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "correction_id": correction_id,
        "csv_row_number": 2,
        "row_sha256": source_row_sha256(row, FIELDNAMES),
        "field": field,
        "old_value": old_value,
        "new_value": new_value,
        "decision": decision,
        "reason_code": reason_code,
        "confidence": confidence,
        "checked_at": "2026-08-26",
        "evidence": evidence if evidence is not None else _evidence(),
    }


class MetadataCorrectionTests(unittest.TestCase):
    def _paths(self, directory: str) -> tuple[Path, Path, Path, Path, Path]:
        data_dir = Path(directory)
        return (
            data_dir,
            data_dir / "data_list.csv",
            data_dir / "private" / "corrections.json",
            data_dir / "private" / "data_list.corrected.csv",
            data_dir / "private" / "corrections.report.json",
        )

    def _write_set(
        self, path: Path, source_path: Path, corrections: list[dict[str, object]]
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        value = {
            "schema_version": "1.0",
            "source_csv_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "created_at": "2026-08-26T00:00:00Z",
            "corrections": corrections,
        }
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def test_applies_window_and_splits_bid_open_without_changing_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir, source, correction_set, output, report = self._paths(directory)
            row = _row()
            _write_csv(source, [row])
            source_before = source.read_bytes()
            corrections = [
                _correction(
                    row,
                    correction_id="corr_start",
                    field="bid_start_at",
                    old_value=None,
                    new_value="2026-01-03 09:00:00",
                ),
                _correction(
                    row,
                    correction_id="corr_end",
                    field="bid_end_at",
                    old_value="2026-01-03 12:00:00",
                    new_value="2026-01-03 11:00:00",
                    reason_code="date_mapping_corrected",
                ),
                _correction(
                    row,
                    correction_id="corr_open",
                    field="bid_open_at",
                    old_value=None,
                    new_value="2026-01-03 12:00:00",
                    reason_code="date_mapping_corrected",
                ),
            ]
            self._write_set(correction_set, source, corrections)

            result = apply_metadata_corrections(
                data_dir=data_dir,
                source_csv_path=source,
                corrections_path=correction_set,
                output_csv_path=output,
                report_path=report,
            )

            self.assertEqual(source.read_bytes(), source_before)
            with output.open("r", encoding="utf-8-sig", newline="") as corrected:
                rows = list(csv.DictReader(corrected))
            self.assertEqual(rows[0]["입찰 참여 시작일"], "2026-01-03 09:00:00")
            self.assertEqual(rows[0]["입찰 참여 마감일"], "2026-01-03 11:00:00")
            self.assertEqual(rows[0][OPEN_AT_COLUMN], "2026-01-03 12:00:00")
            self.assertEqual(result["source_row_count"], 1)
            self.assertEqual(result["output_row_count"], 1)
            self.assertEqual(result["decision_counts"], {"apply": 3})

    def test_records_retained_null_without_filling_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir, source, correction_set, output, report = self._paths(directory)
            row = _row(start="", end="")
            _write_csv(source, [row])
            correction = _correction(
                row,
                correction_id="corr_null",
                field="bid_start_at",
                old_value=None,
                new_value=None,
                decision="retain_null",
                reason_code="source_not_stated",
                evidence=_evidence("local_audit"),
            )
            self._write_set(correction_set, source, [correction])

            result = apply_metadata_corrections(
                data_dir=data_dir,
                source_csv_path=source,
                corrections_path=correction_set,
                output_csv_path=output,
                report_path=report,
            )

            self.assertEqual(result["decision_counts"], {"retain_null": 1})
            self.assertEqual(result["reason_counts"], {"source_not_stated": 1})

    def test_clears_confirmed_sentinel_with_primary_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir, source, correction_set, output, report = self._paths(directory)
            row = _row()
            row["사업 금액"] = "1"
            _write_csv(source, [row])
            correction = _correction(
                row,
                correction_id="corr_clear_amount",
                field="project_amount_raw",
                old_value="1",
                new_value=None,
                decision="clear",
                reason_code="sentinel_undisclosed",
                evidence=_evidence("local_source_block"),
            )
            self._write_set(correction_set, source, [correction])

            result = apply_metadata_corrections(
                data_dir=data_dir,
                source_csv_path=source,
                corrections_path=correction_set,
                output_csv_path=output,
                report_path=report,
            )

            with output.open("r", encoding="utf-8-sig", newline="") as corrected:
                corrected_row = next(csv.DictReader(corrected))
            self.assertEqual(corrected_row["사업 금액"], "")
            self.assertEqual(result["decision_counts"], {"clear": 1})
            self.assertEqual(result["changed_field_counts"], {"project_amount_raw": 1})

    def test_rejects_source_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir, source, correction_set, output, report = self._paths(directory)
            row = _row()
            _write_csv(source, [row])
            correction = _correction(
                row,
                correction_id="corr_start",
                field="bid_start_at",
                old_value=None,
                new_value="2026-01-03 09:00:00",
            )
            self._write_set(correction_set, source, [correction])
            source.write_bytes(source.read_bytes() + b"\n")

            with self.assertRaisesRegex(ValueError, "correction_source_hash_mismatch"):
                apply_metadata_corrections(
                    data_dir=data_dir,
                    source_csv_path=source,
                    corrections_path=correction_set,
                    output_csv_path=output,
                    report_path=report,
                )

    def test_rejects_duplicate_target_and_old_value_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir, source, correction_set, output, report = self._paths(directory)
            row = _row()
            _write_csv(source, [row])
            first = _correction(
                row,
                correction_id="corr_one",
                field="bid_start_at",
                old_value=None,
                new_value="2026-01-03 09:00:00",
            )
            second = dict(first, correction_id="corr_two")
            self._write_set(correction_set, source, [first, second])
            with self.assertRaisesRegex(ValueError, "correction_target_duplicate"):
                apply_metadata_corrections(
                    data_dir=data_dir,
                    source_csv_path=source,
                    corrections_path=correction_set,
                    output_csv_path=output,
                    report_path=report,
                )

            first["old_value"] = "wrong"
            self._write_set(correction_set, source, [first])
            with self.assertRaisesRegex(ValueError, "correction_old_value_mismatch"):
                apply_metadata_corrections(
                    data_dir=data_dir,
                    source_csv_path=source,
                    corrections_path=correction_set,
                    output_csv_path=output,
                    report_path=report,
                )

    def test_rejects_non_primary_apply_and_reversed_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir, source, correction_set, output, report = self._paths(directory)
            row = _row()
            _write_csv(source, [row])
            start = _correction(
                row,
                correction_id="corr_start",
                field="bid_start_at",
                old_value=None,
                new_value="2026-01-03 13:00:00",
                evidence=_evidence("secondary_web"),
            )
            self._write_set(correction_set, source, [start])
            with self.assertRaisesRegex(ValueError, "correction_primary_evidence_missing"):
                apply_metadata_corrections(
                    data_dir=data_dir,
                    source_csv_path=source,
                    corrections_path=correction_set,
                    output_csv_path=output,
                    report_path=report,
                )

            start["evidence"] = _evidence()
            self._write_set(correction_set, source, [start])
            with self.assertRaisesRegex(ValueError, "correction_bid_window_reversed"):
                apply_metadata_corrections(
                    data_dir=data_dir,
                    source_csv_path=source,
                    corrections_path=correction_set,
                    output_csv_path=output,
                    report_path=report,
                )

    def test_forbids_in_place_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir, source, correction_set, _output, report = self._paths(directory)
            row = _row()
            _write_csv(source, [row])
            correction = _correction(
                row,
                correction_id="corr_start",
                field="bid_start_at",
                old_value=None,
                new_value="2026-01-03 09:00:00",
            )
            self._write_set(correction_set, source, [correction])

            with self.assertRaisesRegex(ValueError, "correction_source_overwrite_forbidden"):
                apply_metadata_corrections(
                    data_dir=data_dir,
                    source_csv_path=source,
                    corrections_path=correction_set,
                    output_csv_path=source,
                    report_path=report,
                )


if __name__ == "__main__":
    unittest.main()
