from __future__ import annotations

import importlib.metadata
import multiprocessing
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from midprojectrag.ingest.common import (
    read_jsonl,
    require_within,
    sha256_file,
    sha256_text,
    utc_now,
    write_json,
    write_jsonl,
)


EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_PATTERN = re.compile(
    r"(?:01[016789]-?[0-9]{3,4}-?[0-9]{4}|0(?:2|[3-6][1-5])-?[0-9]{3,4}-?[0-9]{4})"
)
DOC_ID_PATTERN = re.compile(r"^doc_[0-9a-f]{24}$")


@dataclass(frozen=True)
class ExtractionResult:
    status: str
    extractor: str
    extractor_version: str
    blocks: list[dict[str, Any]]
    page_count: int | None = None
    error_code: str | None = None
    warnings: tuple[str, ...] = ()


def _block(
    *,
    doc_id: str,
    sequence: int,
    block_type: str,
    text: str,
    extractor: str,
    extractor_version: str,
    page_start: int | None,
    page_end: int | None,
    source_locator: str,
) -> dict[str, Any]:
    content_sha256 = sha256_text(text)
    block_id = "block_" + sha256_text(f"{doc_id}:{sequence}:{content_sha256}")[:24]
    return {
        "schema_version": "1.0",
        "block_id": block_id,
        "doc_id": doc_id,
        "sequence": sequence,
        "block_type": block_type,
        "section_path": [],
        "page_start": page_start,
        "page_end": page_end,
        "bbox": None,
        "text": text,
        "content_sha256": content_sha256,
        "extractor": extractor,
        "extractor_version": extractor_version,
        "source_locator": source_locator,
    }


def _extract_pdf_in_process(path: Path, entry: dict[str, Any]) -> ExtractionResult:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ExtractionResult(
            status="failed",
            extractor="pypdf",
            extractor_version="unavailable",
            blocks=[],
            error_code="pdf_extractor_unavailable",
        )

    try:
        version = importlib.metadata.version("pypdf")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"

    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            return ExtractionResult(
                status="failed",
                extractor="pypdf",
                extractor_version=version,
                blocks=[],
                error_code="pdf_encrypted",
            )

        blocks: list[dict[str, Any]] = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if not text:
                continue
            blocks.append(
                _block(
                    doc_id=entry["doc_id"],
                    sequence=len(blocks),
                    block_type="page_text",
                    text=text,
                    extractor="pypdf",
                    extractor_version=version,
                    page_start=page_number,
                    page_end=page_number,
                    source_locator=f"page:{page_number}",
                )
            )
    except Exception:
        return ExtractionResult(
            status="failed",
            extractor="pypdf",
            extractor_version=version,
            blocks=[],
            error_code="pdf_parse_failed",
        )

    if not blocks:
        return ExtractionResult(
            status="failed",
            extractor="pypdf",
            extractor_version=version,
            blocks=[],
            page_count=len(reader.pages),
            error_code="pdf_no_text",
            warnings=("ocr_may_be_required",),
        )
    return ExtractionResult(
        status="ok",
        extractor="pypdf",
        extractor_version=version,
        blocks=blocks,
        page_count=len(reader.pages),
    )


def _pdf_worker(path_value: str, doc_id: str, sender: Any) -> None:
    try:
        sender.send(_extract_pdf_in_process(Path(path_value), {"doc_id": doc_id}))
    finally:
        sender.close()


def _extract_pdf(path: Path, entry: dict[str, Any], timeout_seconds: int) -> ExtractionResult:
    if timeout_seconds <= 0:
        return ExtractionResult(
            status="failed",
            extractor="pypdf",
            extractor_version="not_run",
            blocks=[],
            error_code="pdf_extract_timeout",
        )

    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_pdf_worker,
        args=(str(path), str(entry.get("doc_id", "invalid")), sender),
        daemon=True,
    )
    try:
        process.start()
    except (OSError, RuntimeError):
        receiver.close()
        sender.close()
        return ExtractionResult(
            status="failed",
            extractor="pypdf",
            extractor_version="not_run",
            blocks=[],
            error_code="pdf_worker_launch_failed",
        )
    sender.close()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join()
        receiver.close()
        process.close()
        return ExtractionResult(
            status="failed",
            extractor="pypdf",
            extractor_version="unknown",
            blocks=[],
            error_code="pdf_extract_timeout",
        )

    try:
        if not receiver.poll(1):
            raise EOFError
        result = receiver.recv()
    except (EOFError, OSError):
        result = ExtractionResult(
            status="failed",
            extractor="pypdf",
            extractor_version="unknown",
            blocks=[],
            error_code="pdf_worker_failed",
        )
    finally:
        receiver.close()
        process.close()
    return result


def _hwp5txt_version(command: str) -> str:
    try:
        completed = subprocess.run(
            [command, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    output = (completed.stdout or completed.stderr or "").strip().splitlines()
    return output[0][:80] if output else "unknown"


def _extract_hwp(path: Path, entry: dict[str, Any], timeout_seconds: int) -> ExtractionResult:
    command = shutil.which("hwp5txt")
    if command is None:
        return ExtractionResult(
            status="failed",
            extractor="hwp5txt",
            extractor_version="unavailable",
            blocks=[],
            error_code="hwp_extractor_unavailable",
        )

    version = _hwp5txt_version(command)
    try:
        completed = subprocess.run(
            [command, str(path)],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ExtractionResult(
            status="failed",
            extractor="hwp5txt",
            extractor_version=version,
            blocks=[],
            error_code="hwp_extract_timeout",
        )
    except OSError:
        return ExtractionResult(
            status="failed",
            extractor="hwp5txt",
            extractor_version=version,
            blocks=[],
            error_code="hwp_extract_launch_failed",
        )

    if completed.returncode != 0:
        return ExtractionResult(
            status="failed",
            extractor="hwp5txt",
            extractor_version=version,
            blocks=[],
            error_code="hwp_parse_failed",
        )

    paragraphs = [value.strip() for value in re.split(r"\n\s*\n", completed.stdout) if value.strip()]
    if not paragraphs:
        return ExtractionResult(
            status="failed",
            extractor="hwp5txt",
            extractor_version=version,
            blocks=[],
            error_code="hwp_no_text",
        )

    blocks = [
        _block(
            doc_id=entry["doc_id"],
            sequence=sequence,
            block_type="paragraph",
            text=text,
            extractor="hwp5txt",
            extractor_version=version,
            page_start=None,
            page_end=None,
            source_locator=f"paragraph:{sequence + 1}",
        )
        for sequence, text in enumerate(paragraphs)
    ]
    return ExtractionResult(
        status="partial",
        extractor="hwp5txt",
        extractor_version=version,
        blocks=blocks,
        warnings=("hwp_page_table_provenance_unavailable",),
    )


ADAPTERS: dict[str, Callable[[Path, dict[str, Any], int], ExtractionResult]] = {
    ".pdf": _extract_pdf,
    ".hwp": _extract_hwp,
}


def _pii_counts(blocks: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"email": 0, "phone": 0}
    for block in blocks:
        text = block["text"]
        counts["email"] += len(EMAIL_PATTERN.findall(text))
        counts["phone"] += len(PHONE_PATTERN.findall(text))
    return {key: value for key, value in counts.items() if value}


def _entry_input_hash(entry: dict[str, Any], result: ExtractionResult) -> str:
    return sha256_text(
        f"{entry.get('sha256', 'invalid')}:{result.extractor}:{result.extractor_version}"
    )


def extract_manifest(
    *,
    manifest_path: Path,
    data_dir: Path,
    output_dir: Path,
    output_manifest_path: Path,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    data_dir = data_dir.resolve()
    manifest_path = require_within(
        manifest_path,
        data_dir,
        "manifest_path_outside_data_dir",
    )
    output_dir = require_within(output_dir, data_dir, "output_dir_outside_data_dir")
    output_manifest_path = require_within(
        output_manifest_path,
        data_dir,
        "output_manifest_outside_data_dir",
    )
    entries = read_jsonl(manifest_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    updated_entries: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {"ok": 0, "partial": 0, "failed": 0}

    for original in entries:
        entry = dict(original)
        extension = entry.get("extension")
        doc_id = entry.get("doc_id")
        valid_doc_id = isinstance(doc_id, str) and DOC_ID_PATTERN.fullmatch(doc_id) is not None
        adapter = ADAPTERS.get(extension) if isinstance(extension, str) else None
        try:
            source_path = require_within(
                data_dir / str(entry.get("source_relpath", "")),
                data_dir,
                "source_path_outside_data_dir",
            )
            source_path_error = None
        except ValueError as error:
            source_path = data_dir
            source_path_error = str(error)

        if not valid_doc_id:
            result = ExtractionResult(
                status="failed",
                extractor="none",
                extractor_version="none",
                blocks=[],
                error_code="invalid_doc_id",
            )
        elif source_path_error is not None:
            result = ExtractionResult(
                status="failed",
                extractor="none",
                extractor_version="none",
                blocks=[],
                error_code=source_path_error,
            )
        elif adapter is None:
            result = ExtractionResult(
                status="failed",
                extractor="none",
                extractor_version="none",
                blocks=[],
                error_code="unsupported_format",
            )
        elif not source_path.is_file():
            result = ExtractionResult(
                status="failed",
                extractor=adapter.__name__,
                extractor_version="unavailable",
                blocks=[],
                error_code="source_file_missing",
            )
        else:
            try:
                source_hash = sha256_file(source_path)
            except OSError:
                result = ExtractionResult(
                    status="failed",
                    extractor=adapter.__name__,
                    extractor_version="not_run",
                    blocks=[],
                    error_code="source_read_failed",
                )
            else:
                if source_hash != entry.get("sha256"):
                    result = ExtractionResult(
                        status="failed",
                        extractor=adapter.__name__,
                        extractor_version="not_run",
                        blocks=[],
                        error_code="source_hash_mismatch",
                    )
                else:
                    result = adapter(source_path, entry, timeout_seconds)

        block_path = output_dir / f"{doc_id}.jsonl" if valid_doc_id else None
        metadata_path = output_dir / f"{doc_id}.meta.json" if valid_doc_id else None
        input_hash = _entry_input_hash(entry, result)
        if result.status in {"ok", "partial"}:
            assert block_path is not None and metadata_path is not None
            write_jsonl(block_path, result.blocks)
            write_json(
                metadata_path,
                {
                    "schema_version": "1.0",
                    "doc_id": entry["doc_id"],
                    "input_hash": input_hash,
                    "extractor": result.extractor,
                    "extractor_version": result.extractor_version,
                    "block_count": len(result.blocks),
                },
            )
            output_relpath = block_path.relative_to(data_dir).as_posix()
        else:
            if block_path is not None:
                block_path.unlink(missing_ok=True)
            if metadata_path is not None:
                metadata_path.unlink(missing_ok=True)
            output_relpath = None

        text_chars = sum(len(block["text"]) for block in result.blocks)
        entry.update(
            {
                "extractor": result.extractor,
                "extractor_version": result.extractor_version,
                "input_hash": input_hash,
                "status": result.status,
                "error_code": result.error_code,
                "warnings": sorted(set(entry.get("warnings", [])) | set(result.warnings)),
                "page_count": result.page_count,
                "block_count": len(result.blocks),
                "text_chars": text_chars,
                "output_relpath": output_relpath,
                "index_eligible": result.status in {"ok", "partial"} and text_chars > 0,
                "pii_counts": _pii_counts(result.blocks),
                "extracted_at": utc_now(),
            }
        )
        updated_entries.append(entry)
        status_counts[result.status] = status_counts.get(result.status, 0) + 1

    write_jsonl(output_manifest_path, updated_entries)
    return {
        "schema_version": "1.0",
        "documents": len(updated_entries),
        "status_counts": status_counts,
        "output_manifest_written": True,
    }
