from __future__ import annotations

import csv
import json
import os
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from midprojectrag.ingest.common import (
    canonical_json,
    require_sha256,
    require_within,
    sha256_file,
    sha256_text,
    write_json,
)
from midprojectrag.ingest.manifest import CSV_COLUMNS
from midprojectrag.ingest.normalize import clean_cell


OPEN_AT_COLUMN = "개찰 일시"
FIELD_TO_COLUMN = {
    "notice_number": CSV_COLUMNS["notice_number"],
    "notice_round": CSV_COLUMNS["notice_round"],
    "notice_id_namespace": "공고 번호 체계",
    "project_amount_raw": CSV_COLUMNS["project_amount_raw"],
    "ordering_agency": CSV_COLUMNS["ordering_agency"],
    "bid_start_at": CSV_COLUMNS["bid_start_at"],
    "bid_end_at": CSV_COLUMNS["bid_end_at"],
    "bid_open_at": OPEN_AT_COLUMN,
    "proposal_evaluation_at": "제안서 평가 일시",
}
DATE_FIELDS = {"bid_start_at", "bid_end_at", "bid_open_at", "proposal_evaluation_at"}
PRIMARY_EVIDENCE_TYPES = {
    "official_web",
    "official_attachment",
    "local_source_block",
}
EVIDENCE_TYPES = PRIMARY_EVIDENCE_TYPES | {"secondary_web", "local_audit"}
APPLY_REASONS = {
    "official_source_confirmed",
    "official_attachment_confirmed",
    "local_source_confirmed",
    "cross_source_confirmed",
    "date_mapping_corrected",
}
NULL_REASONS = {"source_not_stated", "not_applicable", "unverified"}
CLEAR_REASONS = {
    "sentinel_not_yet_finalized",
    "sentinel_undisclosed",
    "sentinel_exact_value_not_stated",
    "semantic_field_mismatch",
}
TOP_LEVEL_KEYS = {"schema_version", "source_csv_sha256", "created_at", "corrections"}
CORRECTION_KEYS = {
    "correction_id",
    "csv_row_number",
    "row_sha256",
    "field",
    "old_value",
    "new_value",
    "decision",
    "reason_code",
    "confidence",
    "checked_at",
    "evidence",
}
EVIDENCE_KEYS = {"source_type", "locator"}
CANONICAL_DATETIME = "%Y-%m-%d %H:%M:%S"
NOTICE_ID_NAMESPACES = {
    "g2b",
    "kwater.ebid",
    "korail.ebid",
    "koica.nebid",
    "kogas.ebid",
    "kr.ebid",
    "pre_disclosure",
}


def _nullable_cell(value: Any) -> str | None:
    cleaned = clean_cell(value)
    return cleaned or None


def source_row_sha256(row: Mapping[str, Any], fieldnames: Sequence[str]) -> str:
    """Hash a normalized source row without exposing its values."""

    payload = {
        "columns": list(fieldnames),
        "values": [_nullable_cell(row.get(column)) for column in fieldnames],
    }
    return sha256_text(canonical_json(payload))


def _read_source_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        fieldnames = reader.fieldnames or []
        missing = [column for column in CSV_COLUMNS.values() if column not in fieldnames]
        if missing:
            raise ValueError("correction_source_columns_missing")
        rows: list[dict[str, str]] = []
        for row in reader:
            if None in row:
                raise ValueError("correction_source_row_invalid")
            rows.append({column: row.get(column, "") for column in fieldnames})
    return fieldnames, rows


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], code: str) -> None:
    if set(value) != expected:
        raise ValueError(code)


def _validate_datetime(value: str) -> None:
    try:
        parsed = datetime.strptime(value, CANONICAL_DATETIME)
    except ValueError as error:
        raise ValueError("correction_datetime_invalid") from error
    if parsed.strftime(CANONICAL_DATETIME) != value:
        raise ValueError("correction_datetime_invalid")


def _validate_applied_value(field: str, value: str) -> None:
    if field in DATE_FIELDS:
        _validate_datetime(value)
        return
    if field == "project_amount_raw":
        if not re.fullmatch(r"[0-9]+", value) or int(value) <= 0:
            raise ValueError("correction_amount_invalid")
        return
    if field == "notice_round":
        if not re.fullmatch(r"[0-9A-Za-z._-]{1,32}", value):
            raise ValueError("correction_notice_round_invalid")
        return
    if field == "notice_id_namespace":
        if value not in NOTICE_ID_NAMESPACES:
            raise ValueError("correction_notice_namespace_invalid")
        return
    if field == "ordering_agency":
        if len(value) > 128 or "\n" in value or "\r" in value:
            raise ValueError("correction_ordering_agency_invalid")
        return
    if field == "notice_number":
        if len(value) > 128 or "\n" in value or "\r" in value:
            raise ValueError("correction_notice_number_invalid")
        return


def _validate_evidence(value: Any) -> set[str]:
    if not isinstance(value, list) or not value:
        raise ValueError("correction_evidence_missing")
    source_types: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("correction_evidence_invalid")
        _require_exact_keys(item, EVIDENCE_KEYS, "correction_evidence_keys_invalid")
        source_type = item.get("source_type")
        locator = item.get("locator")
        if source_type not in EVIDENCE_TYPES:
            raise ValueError("correction_evidence_type_invalid")
        if (
            not isinstance(locator, str)
            or not locator.strip()
            or len(locator) > 2048
            or "\n" in locator
            or "\r" in locator
        ):
            raise ValueError("correction_evidence_locator_invalid")
        source_types.add(source_type)
    return source_types


def _load_and_validate_corrections(
    path: Path,
    *,
    source_csv_sha256: str,
    fieldnames: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError("correction_set_invalid")
    _require_exact_keys(value, TOP_LEVEL_KEYS, "correction_set_keys_invalid")
    if value.get("schema_version") != "1.0":
        raise ValueError("correction_schema_version_invalid")
    expected_source_hash = require_sha256(
        value.get("source_csv_sha256"), "correction_source_hash_invalid"
    )
    if expected_source_hash != source_csv_sha256:
        raise ValueError("correction_source_hash_mismatch")
    if not isinstance(value.get("created_at"), str) or not value["created_at"].strip():
        raise ValueError("correction_created_at_invalid")
    corrections = value.get("corrections")
    if not isinstance(corrections, list) or not corrections:
        raise ValueError("correction_rows_missing")

    seen_ids: set[str] = set()
    seen_targets: set[tuple[int, str]] = set()
    validated: list[dict[str, Any]] = []
    for correction in corrections:
        if not isinstance(correction, dict):
            raise ValueError("correction_row_invalid")
        _require_exact_keys(correction, CORRECTION_KEYS, "correction_row_keys_invalid")

        correction_id = correction.get("correction_id")
        if not isinstance(correction_id, str) or not re.fullmatch(
            r"corr_[a-z0-9_]{1,64}", correction_id
        ):
            raise ValueError("correction_id_invalid")
        if correction_id in seen_ids:
            raise ValueError("correction_id_duplicate")
        seen_ids.add(correction_id)

        row_number = correction.get("csv_row_number")
        if not isinstance(row_number, int) or isinstance(row_number, bool):
            raise ValueError("correction_row_number_invalid")
        row_index = row_number - 2
        if row_index < 0 or row_index >= len(rows):
            raise ValueError("correction_row_number_invalid")

        field = correction.get("field")
        if field not in FIELD_TO_COLUMN:
            raise ValueError("correction_field_invalid")
        target = (row_number, field)
        if target in seen_targets:
            raise ValueError("correction_target_duplicate")
        seen_targets.add(target)

        expected_row_hash = require_sha256(
            correction.get("row_sha256"), "correction_row_hash_invalid"
        )
        actual_row_hash = source_row_sha256(rows[row_index], fieldnames)
        if expected_row_hash != actual_row_hash:
            raise ValueError("correction_row_hash_mismatch")

        column = FIELD_TO_COLUMN[field]
        actual_old = _nullable_cell(rows[row_index].get(column))
        recorded_old = _nullable_cell(correction.get("old_value"))
        if actual_old != recorded_old:
            raise ValueError("correction_old_value_mismatch")

        decision = correction.get("decision")
        reason_code = correction.get("reason_code")
        confidence = correction.get("confidence")
        new_value = _nullable_cell(correction.get("new_value"))
        source_types = _validate_evidence(correction.get("evidence"))
        if confidence not in {"high", "medium", "low"}:
            raise ValueError("correction_confidence_invalid")
        if not isinstance(correction.get("checked_at"), str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}", correction["checked_at"]
        ):
            raise ValueError("correction_checked_at_invalid")

        if decision == "apply":
            if reason_code not in APPLY_REASONS:
                raise ValueError("correction_apply_reason_invalid")
            if confidence != "high":
                raise ValueError("correction_apply_confidence_invalid")
            if new_value is None:
                raise ValueError("correction_new_value_missing")
            if not source_types & PRIMARY_EVIDENCE_TYPES:
                raise ValueError("correction_primary_evidence_missing")
            _validate_applied_value(field, new_value)
        elif decision == "clear":
            if reason_code not in CLEAR_REASONS:
                raise ValueError("correction_clear_reason_invalid")
            if confidence != "high":
                raise ValueError("correction_clear_confidence_invalid")
            if actual_old is None or new_value is not None:
                raise ValueError("correction_clear_value_invalid")
            if not source_types & PRIMARY_EVIDENCE_TYPES:
                raise ValueError("correction_primary_evidence_missing")
        elif decision == "retain_null":
            if reason_code not in NULL_REASONS:
                raise ValueError("correction_null_reason_invalid")
            if actual_old is not None or new_value is not None:
                raise ValueError("correction_retain_null_value_invalid")
        else:
            raise ValueError("correction_decision_invalid")

        normalized = dict(correction)
        normalized["old_value"] = recorded_old
        normalized["new_value"] = new_value
        validated.append(normalized)
    return validated


def _validate_date_order(rows: Sequence[Mapping[str, Any]]) -> None:
    columns = {
        "start": FIELD_TO_COLUMN["bid_start_at"],
        "end": FIELD_TO_COLUMN["bid_end_at"],
        "open": FIELD_TO_COLUMN["bid_open_at"],
        "evaluation": FIELD_TO_COLUMN["proposal_evaluation_at"],
    }
    for row in rows:
        values: dict[str, datetime | None] = {}
        for key, column in columns.items():
            raw = _nullable_cell(row.get(column))
            if raw is None:
                values[key] = None
                continue
            _validate_datetime(raw)
            values[key] = datetime.strptime(raw, CANONICAL_DATETIME)
        if values["start"] and values["end"] and values["start"] > values["end"]:
            raise ValueError("correction_bid_window_reversed")
        if values["end"] and values["open"] and values["end"] > values["open"]:
            raise ValueError("correction_bid_open_precedes_end")
        if values["end"] and values["evaluation"] and values["end"] > values["evaluation"]:
            raise ValueError("correction_evaluation_precedes_end")


def _write_csv(path: Path, fieldnames: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8-sig", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def apply_metadata_corrections(
    *,
    data_dir: Path,
    source_csv_path: Path,
    corrections_path: Path,
    output_csv_path: Path,
    report_path: Path,
) -> dict[str, Any]:
    data_dir = data_dir.resolve()
    source_csv_path = require_within(
        source_csv_path, data_dir, "correction_source_path_outside_data_dir"
    )
    corrections_path = require_within(
        corrections_path, data_dir, "correction_set_path_outside_data_dir"
    )
    output_csv_path = require_within(
        output_csv_path, data_dir, "correction_output_path_outside_data_dir"
    )
    report_path = require_within(
        report_path, data_dir, "correction_report_path_outside_data_dir"
    )
    if source_csv_path == output_csv_path:
        raise ValueError("correction_source_overwrite_forbidden")

    source_hash = sha256_file(source_csv_path)
    fieldnames, source_rows = _read_source_csv(source_csv_path)
    corrections = _load_and_validate_corrections(
        corrections_path,
        source_csv_sha256=source_hash,
        fieldnames=fieldnames,
        rows=source_rows,
    )

    output_fieldnames = list(fieldnames)
    for extra_field in (
        "notice_id_namespace",
        "bid_open_at",
        "proposal_evaluation_at",
    ):
        if any(item["field"] == extra_field for item in corrections):
            extra_column = FIELD_TO_COLUMN[extra_field]
            if extra_column not in output_fieldnames:
                output_fieldnames.append(extra_column)
    output_rows = [dict(row) for row in source_rows]
    for row in output_rows:
        for column in output_fieldnames:
            row.setdefault(column, "")

    for correction in corrections:
        if correction["decision"] not in {"apply", "clear"}:
            continue
        row_index = correction["csv_row_number"] - 2
        output_rows[row_index][FIELD_TO_COLUMN[correction["field"]]] = (
            correction["new_value"] or ""
        )

    _validate_date_order(output_rows)
    _write_csv(output_csv_path, output_fieldnames, output_rows)
    output_hash = sha256_file(output_csv_path)

    decision_counts = Counter(item["decision"] for item in corrections)
    field_counts = Counter(item["field"] for item in corrections)
    applied_field_counts = Counter(
        item["field"] for item in corrections if item["decision"] == "apply"
    )
    changed_field_counts = Counter(
        item["field"] for item in corrections if item["decision"] in {"apply", "clear"}
    )
    reason_counts = Counter(item["reason_code"] for item in corrections)
    report = {
        "schema_version": "1.0",
        "passed": True,
        "source_csv_sha256": source_hash,
        "output_csv_sha256": output_hash,
        "source_row_count": len(source_rows),
        "output_row_count": len(output_rows),
        "correction_count": len(corrections),
        "decision_counts": dict(sorted(decision_counts.items())),
        "field_counts": dict(sorted(field_counts.items())),
        "applied_field_counts": dict(sorted(applied_field_counts.items())),
        "changed_field_counts": dict(sorted(changed_field_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
        "applied_correction_ids": sorted(
            item["correction_id"] for item in corrections if item["decision"] == "apply"
        ),
    }
    write_json(report_path, report)
    return report
