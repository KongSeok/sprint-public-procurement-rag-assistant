from __future__ import annotations

import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from midprojectrag.ingest.common import (
    canonical_json,
    require_within,
    sha256_file,
    sha256_text,
    utc_now,
)
from midprojectrag.ingest.normalize import clean_cell, normalize_amount, normalize_filename


CSV_COLUMNS = {
    "notice_number": "공고 번호",
    "notice_round": "공고 차수",
    "project_name": "사업명",
    "project_amount_raw": "사업 금액",
    "ordering_agency": "발주 기관",
    "published_at": "공개 일자",
    "bid_start_at": "입찰 참여 시작일",
    "bid_end_at": "입찰 참여 마감일",
    "project_summary": "사업 요약",
    "source_format": "파일형식",
    "source_filename": "파일명",
    "text_preview": "텍스트",
}

SUPPORTED_EXTENSIONS = {".hwp", ".hwpx", ".pdf"}
CFB_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")
PDF_SIGNATURE = b"%PDF-"


@dataclass(frozen=True)
class ManifestBuildResult:
    entries: list[dict[str, Any]]
    report: dict[str, Any]

    @property
    def passed(self) -> bool:
        return not self.report["errors"]


def detect_mime(path: Path) -> tuple[str, list[str]]:
    with path.open("rb") as source:
        header = source.read(8)

    extension = path.suffix.casefold()
    warnings: list[str] = []
    if extension == ".pdf":
        if not header.startswith(PDF_SIGNATURE):
            warnings.append("pdf_magic_mismatch")
        return "application/pdf", warnings
    if extension == ".hwp":
        if header != CFB_SIGNATURE:
            warnings.append("hwp_cfb_magic_mismatch")
        return "application/x-hwp-ole", warnings
    if extension == ".hwpx":
        if not header.startswith(b"PK"):
            warnings.append("hwpx_zip_magic_mismatch")
        return "application/vnd.hancom.hwpx", warnings
    return "application/octet-stream", ["unsupported_extension"]


def _read_csv_rows(csv_path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        fieldnames = reader.fieldnames or []
        missing_columns = [column for column in CSV_COLUMNS.values() if column not in fieldnames]
        rows = [{key: clean_cell(value) for key, value in row.items()} for row in reader]
    return rows, missing_columns


def _discover_documents(raw_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in raw_dir.rglob("*")
        if path.is_file() and path.suffix.casefold() in SUPPORTED_EXTENSIONS
    )


def _count_issue(code: str, count: int, expected: int | None = None) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "count": count}
    if expected is not None:
        issue["expected"] = expected
    return issue


def build_manifest(
    *,
    data_dir: Path,
    csv_path: Path,
    raw_dir: Path,
    expected_documents: int = 100,
    expected_hwp: int = 96,
    expected_pdf: int = 4,
) -> ManifestBuildResult:
    data_dir = data_dir.resolve()
    csv_path = require_within(csv_path, data_dir, "csv_path_outside_data_dir")
    raw_dir = require_within(raw_dir, data_dir, "raw_dir_outside_data_dir")

    rows, missing_columns = _read_csv_rows(csv_path)
    discovered_documents = _discover_documents(raw_dir)
    errors: list[dict[str, Any]] = []

    documents: list[Path] = []
    escaped_documents = 0
    for document in discovered_documents:
        resolved_document = document.resolve()
        if not resolved_document.is_relative_to(data_dir):
            escaped_documents += 1
            continue
        documents.append(resolved_document)

    if escaped_documents:
        errors.append(_count_issue("source_path_outside_data_dir", escaped_documents))

    if missing_columns:
        errors.append({"code": "csv_columns_missing", "count": len(missing_columns)})

    raw_index: dict[str, list[Path]] = defaultdict(list)
    for document in documents:
        raw_index[normalize_filename(document.name)].append(document)

    csv_index: dict[str, list[tuple[int, dict[str, str]]]] = defaultdict(list)
    filename_column = CSV_COLUMNS["source_filename"]
    for row_number, row in enumerate(rows, start=2):
        csv_index[normalize_filename(row.get(filename_column, ""))].append((row_number, row))

    raw_collisions = {name: values for name, values in raw_index.items() if len(values) != 1}
    csv_collisions = {name: values for name, values in csv_index.items() if len(values) != 1}
    if raw_collisions:
        errors.append(_count_issue("raw_filename_collision", len(raw_collisions)))
    if csv_collisions:
        errors.append(_count_issue("csv_filename_collision", len(csv_collisions)))

    raw_names = set(raw_index)
    csv_names = set(csv_index)
    missing_raw = sorted(csv_names - raw_names)
    extra_raw = sorted(raw_names - csv_names)
    if missing_raw:
        errors.append(_count_issue("csv_rows_without_raw_file", len(missing_raw)))
    if extra_raw:
        errors.append(_count_issue("raw_files_without_csv_row", len(extra_raw)))

    extension_counts = Counter(path.suffix.casefold() for path in documents)
    expected_counts = {
        "csv_rows": (len(rows), expected_documents),
        "raw_documents": (len(documents), expected_documents),
        "hwp_documents": (extension_counts[".hwp"], expected_hwp),
        "pdf_documents": (extension_counts[".pdf"], expected_pdf),
    }
    for code, (actual, expected) in expected_counts.items():
        if actual != expected:
            errors.append(_count_issue(f"{code}_mismatch", actual, expected))

    matched_names = sorted(
        name
        for name in raw_names & csv_names
        if name not in raw_collisions and name not in csv_collisions
    )

    staged_entries: list[dict[str, Any]] = []
    for normalized_name in matched_names:
        source_path = raw_index[normalized_name][0]
        row_number, row = csv_index[normalized_name][0]
        file_sha256 = sha256_file(source_path)
        doc_id = "doc_" + sha256_text(f"{normalized_name}\0{file_sha256}")[:24]
        mime_type, format_warnings = detect_mime(source_path)
        amount_raw = row.get(CSV_COLUMNS["project_amount_raw"], "")
        amount_value, amount_warnings = normalize_amount(amount_raw)
        preview = row.get(CSV_COLUMNS["text_preview"], "")

        metadata = {
            key: row.get(column, "")
            for key, column in CSV_COLUMNS.items()
            if key not in {"text_preview", "project_amount_raw", "source_filename"}
        }
        metadata.update(
            {
                "project_amount_raw": amount_raw,
                "project_amount_value": amount_value,
                "preview_chars": len(preview),
                "preview_sha256": sha256_text(preview) if preview else None,
            }
        )

        staged_entries.append(
            {
                "schema_version": "1.0",
                "snapshot_id": "pending",
                "doc_id": doc_id,
                "source_relpath": source_path.relative_to(data_dir).as_posix(),
                "source_filename": source_path.name,
                "normalized_filename": normalized_name,
                "extension": source_path.suffix.casefold(),
                "mime_type": mime_type,
                "size_bytes": source_path.stat().st_size,
                "sha256": file_sha256,
                "csv_row_number": row_number,
                "metadata": metadata,
                "extractor": None,
                "extractor_version": None,
                "input_hash": file_sha256,
                "status": "pending",
                "error_code": None,
                "warnings": sorted(set(format_warnings + amount_warnings)),
                "page_count": None,
                "block_count": 0,
                "text_chars": 0,
                "output_relpath": None,
                "index_eligible": False,
                "pii_counts": {},
                "created_at": utc_now(),
            }
        )

    snapshot_payload = [
        {
            "doc_id": entry["doc_id"],
            "sha256": entry["sha256"],
            "name": entry["normalized_filename"],
            "metadata_sha256": sha256_text(canonical_json(entry["metadata"])),
        }
        for entry in staged_entries
    ]
    snapshot_id = "snapshot_" + sha256_text(canonical_json(snapshot_payload))[:24]
    for entry in staged_entries:
        entry["snapshot_id"] = snapshot_id

    report = {
        "schema_version": "1.0",
        "snapshot_id": snapshot_id,
        "passed": not errors,
        "counts": {
            "csv_rows": len(rows),
            "raw_documents": len(documents),
            "matched_documents": len(staged_entries),
            "hwp_documents": extension_counts[".hwp"],
            "hwpx_documents": extension_counts[".hwpx"],
            "pdf_documents": extension_counts[".pdf"],
        },
        "errors": errors,
        "private_details": {
            "missing_raw_normalized_filenames": missing_raw,
            "extra_raw_normalized_filenames": extra_raw,
            "raw_collision_normalized_filenames": sorted(raw_collisions),
            "csv_collision_normalized_filenames": sorted(csv_collisions),
            "missing_csv_columns": missing_columns,
        },
    }
    return ManifestBuildResult(entries=staged_entries, report=report)
