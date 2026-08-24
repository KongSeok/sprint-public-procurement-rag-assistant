from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import re
from typing import Any

from midprojectrag.ingest.common import read_jsonl, sha256_text


DOC_ID_PATTERN = re.compile(r"^doc_[0-9a-f]{24}$")
BLOCK_ID_PATTERN = re.compile(r"^block_[0-9a-f]{24}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SNAPSHOT_ID_PATTERN = re.compile(r"^snapshot_[0-9a-f]{24}$")
REQUIRED_MANIFEST_FIELDS = {
    "schema_version",
    "snapshot_id",
    "doc_id",
    "source_relpath",
    "source_filename",
    "normalized_filename",
    "extension",
    "mime_type",
    "size_bytes",
    "sha256",
    "csv_row_number",
    "metadata",
    "extractor",
    "extractor_version",
    "input_hash",
    "status",
    "error_code",
    "warnings",
    "page_count",
    "block_count",
    "text_chars",
    "output_relpath",
    "index_eligible",
    "pii_counts",
    "created_at",
}
VALID_STATUSES = {"pending", "ok", "partial", "failed"}
VALID_EXTENSIONS = {".hwp", ".hwpx", ".pdf"}
VALID_BLOCK_TYPES = {"heading", "paragraph", "table", "page_text"}
REQUIRED_BLOCK_FIELDS = {
    "schema_version",
    "block_id",
    "doc_id",
    "sequence",
    "block_type",
    "section_path",
    "page_start",
    "page_end",
    "bbox",
    "text",
    "content_sha256",
    "extractor",
    "extractor_version",
    "source_locator",
}


def _issue(code: str, count: int, doc_ids: list[str] | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"code": code, "count": count}
    if doc_ids:
        value["doc_ids"] = sorted(doc_ids)
    return value


def _row_id(entry: dict[str, Any], index: int) -> str:
    doc_id = entry.get("doc_id")
    if isinstance(doc_id, str) and DOC_ID_PATTERN.fullmatch(doc_id) is not None:
        return doc_id
    return f"row_{index + 1}"


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _relative_path(value: Any) -> bool:
    if not _nonempty_string(value):
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def verify_manifest(
    entries: list[dict[str, Any]],
    *,
    blocks_dir: Path | None = None,
    expected_documents: int = 100,
    expected_hwp: int = 96,
    expected_pdf: int = 4,
    require_extracted: bool = False,
    max_failed: int = 0,
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    manifest_contract_issues: defaultdict[str, list[str]] = defaultdict(list)
    row_ids: list[str] = []
    for index, entry in enumerate(entries):
        safe_id = _row_id(entry, index)
        row_ids.append(safe_id)
        doc_id = entry.get("doc_id")
        if REQUIRED_MANIFEST_FIELDS - set(entry):
            manifest_contract_issues["manifest_required_fields_missing"].append(safe_id)
        if entry.get("schema_version") != "1.0":
            manifest_contract_issues["invalid_manifest_schema_version"].append(safe_id)
        snapshot_id = entry.get("snapshot_id")
        if not isinstance(snapshot_id, str) or SNAPSHOT_ID_PATTERN.fullmatch(snapshot_id) is None:
            manifest_contract_issues["invalid_snapshot_id"].append(safe_id)
        if not isinstance(doc_id, str) or DOC_ID_PATTERN.fullmatch(doc_id) is None:
            manifest_contract_issues["invalid_doc_id"].append(safe_id)
        sha256 = entry.get("sha256")
        if not isinstance(sha256, str) or SHA256_PATTERN.fullmatch(sha256) is None:
            manifest_contract_issues["invalid_source_hash"].append(safe_id)
        input_hash = entry.get("input_hash")
        if not isinstance(input_hash, str) or SHA256_PATTERN.fullmatch(input_hash) is None:
            manifest_contract_issues["invalid_input_hash"].append(safe_id)
        if not _relative_path(entry.get("source_relpath")):
            manifest_contract_issues["invalid_source_relpath"].append(safe_id)
        extension = entry.get("extension")
        if not isinstance(extension, str) or extension not in VALID_EXTENSIONS:
            manifest_contract_issues["invalid_extension"].append(safe_id)
        status = entry.get("status")
        if not isinstance(status, str) or status not in VALID_STATUSES:
            manifest_contract_issues["invalid_status"].append(safe_id)
        output_relpath = entry.get("output_relpath")
        if output_relpath is not None and not _relative_path(output_relpath):
            manifest_contract_issues["invalid_output_relpath"].append(safe_id)
        warnings_value = entry.get("warnings")
        if not isinstance(warnings_value, list) or not all(
            isinstance(value, str) for value in warnings_value
        ):
            manifest_contract_issues["invalid_manifest_warnings"].append(safe_id)
        pii_counts = entry.get("pii_counts")
        if not isinstance(pii_counts, dict) or not all(
            isinstance(key, str)
            and isinstance(value, int)
            and not isinstance(value, bool)
            and value >= 0
            for key, value in pii_counts.items()
        ):
            manifest_contract_issues["invalid_pii_counts"].append(safe_id)

        extractor = entry.get("extractor")
        extractor_version = entry.get("extractor_version")
        error_code = entry.get("error_code")
        block_count = entry.get("block_count")
        text_chars = entry.get("text_chars")
        index_eligible = entry.get("index_eligible")
        if status == "pending" and (
            extractor is not None
            or extractor_version is not None
            or error_code is not None
            or block_count != 0
            or text_chars != 0
            or output_relpath is not None
            or index_eligible is not False
        ):
            manifest_contract_issues["invalid_pending_state"].append(safe_id)
        elif isinstance(status, str) and status in {"ok", "partial"} and (
            not _nonempty_string(extractor)
            or not _nonempty_string(extractor_version)
            or error_code is not None
            or not isinstance(block_count, int)
            or isinstance(block_count, bool)
            or block_count < 1
            or not isinstance(text_chars, int)
            or isinstance(text_chars, bool)
            or text_chars < 1
            or not _relative_path(output_relpath)
            or (
                isinstance(doc_id, str)
                and isinstance(output_relpath, str)
                and Path(output_relpath).name != f"{doc_id}.jsonl"
            )
            or index_eligible is not True
            or not _nonempty_string(entry.get("extracted_at"))
        ):
            manifest_contract_issues["invalid_extracted_state"].append(safe_id)
        elif status == "failed" and (
            not _nonempty_string(extractor)
            or not _nonempty_string(extractor_version)
            or not _nonempty_string(error_code)
            or block_count != 0
            or text_chars != 0
            or output_relpath is not None
            or index_eligible is not False
            or not _nonempty_string(entry.get("extracted_at"))
        ):
            manifest_contract_issues["invalid_failed_state"].append(safe_id)

    for code, owners in sorted(manifest_contract_issues.items()):
        errors.append(_issue(code, len(owners), sorted(set(owners))))

    if len(entries) != expected_documents:
        errors.append(_issue("document_count_mismatch", len(entries)))

    extension_counts = Counter(
        value if isinstance(value, str) else "<invalid>"
        for value in (entry.get("extension") for entry in entries)
    )
    if extension_counts[".hwp"] != expected_hwp:
        errors.append(_issue("hwp_count_mismatch", extension_counts[".hwp"]))
    if extension_counts[".pdf"] != expected_pdf:
        errors.append(_issue("pdf_count_mismatch", extension_counts[".pdf"]))

    doc_id_counts = Counter(
        value
        for value in (entry.get("doc_id") for entry in entries)
        if isinstance(value, str) and DOC_ID_PATTERN.fullmatch(value) is not None
    )
    duplicate_doc_ids = [doc_id for doc_id, count in doc_id_counts.items() if doc_id and count > 1]
    if duplicate_doc_ids:
        errors.append(_issue("duplicate_doc_id", len(duplicate_doc_ids), duplicate_doc_ids))

    filename_counts = Counter(
        value
        for value in (entry.get("normalized_filename") for entry in entries)
        if isinstance(value, str) and value
    )
    duplicate_filenames = [name for name, count in filename_counts.items() if name and count > 1]
    if duplicate_filenames:
        errors.append(_issue("duplicate_normalized_filename", len(duplicate_filenames)))

    status_counts = Counter(
        value if isinstance(value, str) else "<invalid>"
        for value in (entry.get("status") for entry in entries)
    )
    failed_doc_ids = [
        row_ids[index]
        for index, entry in enumerate(entries)
        if entry.get("status") == "failed"
    ]
    pending_doc_ids = [
        row_ids[index]
        for index, entry in enumerate(entries)
        if entry.get("status") == "pending"
    ]
    if require_extracted and pending_doc_ids:
        errors.append(_issue("pending_extraction", len(pending_doc_ids), pending_doc_ids))
    if require_extracted and len(failed_doc_ids) > max_failed:
        errors.append(_issue("failed_extraction_over_limit", len(failed_doc_ids), failed_doc_ids))
    if require_extracted and blocks_dir is None:
        errors.append(_issue("blocks_dir_required", 1))

    block_ids: defaultdict[str, list[str]] = defaultdict(list)
    block_contract_issues: defaultdict[str, list[str]] = defaultdict(list)
    if blocks_dir is not None:
        resolved_blocks_dir = blocks_dir.resolve()
        for entry in entries:
            if entry.get("status") not in ("ok", "partial"):
                continue
            doc_id = entry.get("doc_id")
            if not isinstance(doc_id, str) or DOC_ID_PATTERN.fullmatch(doc_id) is None:
                continue
            block_path = resolved_blocks_dir / f"{doc_id}.jsonl"
            try:
                resolved_block_path = block_path.resolve()
            except (OSError, RuntimeError):
                errors.append(_issue("blocks_file_invalid", 1, [doc_id]))
                continue
            if not resolved_block_path.is_relative_to(resolved_blocks_dir):
                errors.append(_issue("blocks_path_outside_directory", 1, [doc_id]))
                continue
            if not resolved_block_path.is_file():
                errors.append(_issue("blocks_file_missing", 1, [doc_id]))
                continue
            try:
                blocks = read_jsonl(resolved_block_path)
            except (OSError, ValueError):
                errors.append(_issue("blocks_file_invalid", 1, [doc_id]))
                continue

            if len(blocks) != entry.get("block_count"):
                errors.append(_issue("block_count_mismatch", 1, [doc_id]))
            calculated_chars = 0
            for expected_sequence, block in enumerate(blocks):
                block_id = block.get("block_id")
                if REQUIRED_BLOCK_FIELDS - set(block):
                    block_contract_issues["block_required_fields_missing"].append(doc_id)
                if not isinstance(block_id, str) or BLOCK_ID_PATTERN.fullmatch(block_id) is None:
                    block_contract_issues["invalid_block_id"].append(doc_id)
                else:
                    block_ids[block_id].append(doc_id)
                if block.get("schema_version") != "1.0":
                    block_contract_issues["invalid_block_schema_version"].append(doc_id)
                if block.get("doc_id") != doc_id:
                    block_contract_issues["block_doc_id_mismatch"].append(doc_id)
                if block.get("sequence") != expected_sequence:
                    block_contract_issues["block_sequence_mismatch"].append(doc_id)
                block_type = block.get("block_type")
                if not isinstance(block_type, str) or block_type not in VALID_BLOCK_TYPES:
                    block_contract_issues["invalid_block_type"].append(doc_id)
                section_path = block.get("section_path")
                if not isinstance(section_path, list) or not all(
                    isinstance(value, str) for value in section_path
                ):
                    block_contract_issues["invalid_section_path"].append(doc_id)
                page_start = block.get("page_start")
                page_end = block.get("page_end")
                if page_start is not None and (
                    not isinstance(page_start, int) or isinstance(page_start, bool) or page_start < 1
                ):
                    block_contract_issues["invalid_page_start"].append(doc_id)
                if page_end is not None and (
                    not isinstance(page_end, int) or isinstance(page_end, bool) or page_end < 1
                ):
                    block_contract_issues["invalid_page_end"].append(doc_id)
                if isinstance(page_start, int) and isinstance(page_end, int) and page_start > page_end:
                    block_contract_issues["invalid_page_range"].append(doc_id)
                bbox = block.get("bbox")
                if bbox is not None and (
                    not isinstance(bbox, list)
                    or len(bbox) != 4
                    or not all(
                        isinstance(value, (int, float)) and not isinstance(value, bool)
                        for value in bbox
                    )
                ):
                    block_contract_issues["invalid_bbox"].append(doc_id)
                for field, code in (
                    ("extractor", "block_extractor_missing"),
                    ("extractor_version", "block_extractor_version_missing"),
                    ("source_locator", "block_locator_missing"),
                ):
                    if not isinstance(block.get(field), str) or not block[field]:
                        block_contract_issues[code].append(doc_id)
                if _nonempty_string(block.get("extractor")) and (
                    block.get("extractor") != entry.get("extractor")
                ):
                    block_contract_issues["block_extractor_mismatch"].append(doc_id)
                if _nonempty_string(block.get("extractor_version")) and (
                    block.get("extractor_version") != entry.get("extractor_version")
                ):
                    block_contract_issues["block_extractor_version_mismatch"].append(doc_id)
                text = block.get("text")
                if not isinstance(text, str) or not text:
                    block_contract_issues["block_text_empty"].append(doc_id)
                    continue
                calculated_chars += len(text)
                content_sha256 = sha256_text(text)
                if block.get("content_sha256") != content_sha256:
                    block_contract_issues["block_content_hash_mismatch"].append(doc_id)
                expected_block_id = "block_" + sha256_text(
                    f"{doc_id}:{expected_sequence}:{content_sha256}"
                )[:24]
                if block_id != expected_block_id:
                    block_contract_issues["block_id_mismatch"].append(doc_id)
            if calculated_chars != entry.get("text_chars"):
                errors.append(_issue("text_char_count_mismatch", 1, [doc_id]))

    for code, owners in sorted(block_contract_issues.items()):
        errors.append(_issue(code, len(owners), sorted(set(owners))))

    duplicate_block_ids = [block_id for block_id, owners in block_ids.items() if len(owners) > 1]
    if duplicate_block_ids:
        errors.append(_issue("duplicate_block_id", len(duplicate_block_ids)))

    partial_doc_ids = [
        row_ids[index]
        for index, entry in enumerate(entries)
        if entry.get("status") == "partial"
    ]
    if partial_doc_ids:
        warnings.append(_issue("partial_extraction", len(partial_doc_ids), partial_doc_ids))

    return {
        "schema_version": "1.0",
        "passed": not errors,
        "counts": {
            "documents": len(entries),
            "hwp": extension_counts[".hwp"],
            "pdf": extension_counts[".pdf"],
            "status": dict(sorted(status_counts.items(), key=lambda item: str(item[0]))),
        },
        "errors": errors,
        "warnings": warnings,
    }
