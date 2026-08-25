from __future__ import annotations

import hashlib
import json
import os
import re
import selectors
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


RHWP_SCHEMA_VERSION = "1.0"
RHWP_ADAPTER_VERSION = "1.0"
RHWP_BINARY_VERSION = "rhwp v0.8.4"
MAX_NESTED_TABLE_DEPTH = 8
MAX_RHWP_STDOUT_BYTES = 64 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
VERIFIED_IDENTITY_PATTERN = re.compile(
    r"^rhwp v0\.8\.4;adapter=1\.0;sha256=([0-9a-f]{64});verified=true;source=explicit$"
)


@dataclass(frozen=True)
class RhwpPage:
    page_index: int
    text: str


@dataclass(frozen=True)
class RhwpAttempt:
    status: str
    extractor_version: str
    pages: tuple[RhwpPage, ...]
    tables: tuple[dict[str, Any], ...]
    page_count: int | None = None
    error_code: str | None = None
    warnings: tuple[str, ...] = ()


def _integer(value: Any, *, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def resolve_rhwp_command() -> str | None:
    override = os.environ.get("MIDPROJECTRAG_RHWP_BIN")
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_absolute() and candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
        return None
    return shutil.which("rhwp")


def _sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _run_bounded(
    argv: list[str],
    *,
    timeout_seconds: int,
    max_stdout_bytes: int,
) -> tuple[int | None, bytes, str | None]:
    """Run a command without allowing stdout/stderr to grow without bound."""
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError:
        return None, b"", "launch_failed"

    assert process.stdout is not None and process.stderr is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    stdout = bytearray()
    deadline = time.monotonic() + max(timeout_seconds, 0)
    failure: str | None = None
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failure = "timeout"
                break
            events = selector.select(timeout=min(remaining, 0.25))
            for key, _ in events:
                stream = key.fileobj
                chunk = os.read(stream.fileno(), READ_CHUNK_BYTES)
                if not chunk:
                    selector.unregister(stream)
                    stream.close()
                    continue
                if key.data == "stdout":
                    if len(stdout) + len(chunk) > max_stdout_bytes:
                        failure = "stdout_too_large"
                        break
                    stdout.extend(chunk)
                # stderr is intentionally consumed and discarded so parser or
                # source details cannot leak into public reports.
            if failure is not None:
                break
    finally:
        selector.close()

    if failure is not None:
        _stop_process(process)
        for stream in (process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()
        return None, bytes(stdout), failure
    returncode = process.wait()
    return returncode, bytes(stdout), None


def _explicit_source(command: str) -> bool:
    override = os.environ.get("MIDPROJECTRAG_RHWP_BIN")
    if not override:
        return False
    try:
        return Path(override).expanduser().resolve() == Path(command).resolve()
    except OSError:
        return False


def rhwp_version(command: str) -> str:
    command_path = Path(command)
    source = "explicit" if _explicit_source(command) else "path"
    digest = _sha256_file(command_path)
    digest_value = digest or "unavailable"
    expected_digest = os.environ.get("MIDPROJECTRAG_RHWP_SHA256", "").casefold()
    checksum_verified = (
        SHA256_PATTERN.fullmatch(expected_digest) is not None
        and digest is not None
        and digest == expected_digest
    )

    # When an expected checksum is supplied, never execute a mismatched binary.
    if expected_digest and not checksum_verified:
        value = "not_run"
    else:
        returncode, stdout, run_error = _run_bounded(
            [command, "--version"],
            timeout_seconds=5,
            max_stdout_bytes=1024,
        )
        if run_error is not None or returncode != 0:
            value = "unknown"
        else:
            lines = stdout.decode("utf-8", errors="replace").strip().splitlines()
            value = lines[0][:80] if lines else "unknown"

    verified = (
        source == "explicit"
        and checksum_verified
        and value == RHWP_BINARY_VERSION
    )
    return (
        f"{value};adapter={RHWP_ADAPTER_VERSION};sha256={digest_value};"
        f"verified={'true' if verified else 'false'};source={source}"
    )


def is_verified_rhwp_identity(value: Any) -> bool:
    return isinstance(value, str) and VERIFIED_IDENTITY_PATTERN.fullmatch(value) is not None


def verified_rhwp_sha256(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = VERIFIED_IDENTITY_PATTERN.fullmatch(value)
    return match.group(1) if match is not None else None


def _run_json(
    command: str,
    subcommand: str,
    path: Path,
    timeout_seconds: int,
    error_prefix: str,
) -> tuple[dict[str, Any] | None, str | None]:
    returncode, stdout, run_error = _run_bounded(
        [command, subcommand, str(path), "--json"],
        timeout_seconds=timeout_seconds,
        max_stdout_bytes=MAX_RHWP_STDOUT_BYTES,
    )
    if run_error == "timeout":
        return None, f"rhwp_{error_prefix}_timeout"
    if run_error == "stdout_too_large":
        return None, f"rhwp_{error_prefix}_output_too_large"
    if run_error is not None:
        return None, "rhwp_launch_failed"

    if returncode != 0:
        return None, f"rhwp_{error_prefix}_failed"
    try:
        value = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return None, f"rhwp_{error_prefix}_invalid_json"
    if not isinstance(value, dict) or value.get("schemaVersion") != RHWP_SCHEMA_VERSION:
        return None, f"rhwp_{error_prefix}_contract_invalid"
    return value, None


def _normalize_pages(payload: dict[str, Any]) -> tuple[int, tuple[RhwpPage, ...]]:
    page_count = payload.get("pageCount")
    raw_pages = payload.get("pages")
    if (
        not _integer(page_count)
        or not isinstance(raw_pages, list)
        or payload.get("truncated") is not False
        or payload.get("omittedCount") != 0
        or len(raw_pages) != page_count
    ):
        raise ValueError("invalid page envelope")

    pages: list[RhwpPage] = []
    seen: set[int] = set()
    for raw_page in raw_pages:
        if not isinstance(raw_page, dict):
            raise ValueError("invalid page")
        page_index = raw_page.get("page")
        text = raw_page.get("text")
        if (
            not _integer(page_index)
            or page_index >= page_count
            or page_index in seen
            or not isinstance(text, str)
        ):
            raise ValueError("invalid page fields")
        seen.add(page_index)
        cleaned = text.strip()
        if cleaned:
            pages.append(RhwpPage(page_index=page_index, text=cleaned))
    if seen != set(range(page_count)):
        raise ValueError("incomplete page index set")
    pages.sort(key=lambda page: page.page_index)
    return page_count, tuple(pages)


def _normalize_container_path(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("invalid table container path")
    normalized: list[dict[str, Any]] = []
    for raw_item in value:
        if not isinstance(raw_item, dict) or not isinstance(raw_item.get("kind"), str):
            raise ValueError("invalid table container path item")
        item: dict[str, Any] = {"kind": raw_item["kind"]}
        for field in ("paragraph", "control"):
            field_value = raw_item.get(field)
            if not _integer(field_value):
                raise ValueError("invalid table container coordinate")
            item[field] = field_value
        if "cell" in raw_item:
            if not _integer(raw_item.get("cell")):
                raise ValueError("invalid table container cell")
            item["cell"] = raw_item["cell"]
        if item["kind"] == "tableCell" and "cell" not in item:
            raise ValueError("missing table container cell")
        normalized.append(item)
    return normalized


def _normalize_table(raw_table: Any, *, depth: int = 0) -> dict[str, Any]:
    if depth > MAX_NESTED_TABLE_DEPTH or not isinstance(raw_table, dict):
        raise ValueError("invalid nested table")

    normalized: dict[str, Any] = {}
    for source_key, target_key in (
        ("index", "index"),
        ("section", "section"),
        ("paragraph", "paragraph"),
        ("rows", "rows"),
        ("cols", "cols"),
    ):
        value = raw_table.get(source_key)
        if not _integer(value):
            raise ValueError("invalid table coordinate")
        normalized[target_key] = value

    cell_count = raw_table.get("cellCount")
    if not _integer(cell_count):
        raise ValueError("invalid table cell count")
    normalized["cell_count"] = cell_count
    if "caption" in raw_table:
        caption = raw_table.get("caption")
        if not isinstance(caption, str):
            raise ValueError("invalid table caption")
        normalized["caption"] = caption.strip()
    if "control" in raw_table:
        control = raw_table.get("control")
        if not _integer(control):
            raise ValueError("invalid table control")
        normalized["control"] = control
    if "containerPath" in raw_table:
        normalized["container_path"] = _normalize_container_path(
            raw_table.get("containerPath")
        )

    raw_cells = raw_table.get("cells")
    if not isinstance(raw_cells, list) or len(raw_cells) != cell_count:
        raise ValueError("invalid table cells")
    cells: list[dict[str, Any]] = []
    covered_coordinates: set[tuple[int, int]] = set()
    for raw_cell in raw_cells:
        if not isinstance(raw_cell, dict):
            raise ValueError("invalid table cell")
        row = raw_cell.get("row")
        col = raw_cell.get("col")
        row_span = raw_cell.get("rowSpan")
        col_span = raw_cell.get("colSpan")
        is_header = raw_cell.get("isHeader")
        text = raw_cell.get("text")
        if (
            not _integer(row)
            or not _integer(col)
            or not _integer(row_span, minimum=1)
            or not _integer(col_span, minimum=1)
            or row >= normalized["rows"]
            or col >= normalized["cols"]
            or row + row_span > normalized["rows"]
            or col + col_span > normalized["cols"]
            or not isinstance(is_header, bool)
            or not isinstance(text, str)
        ):
            raise ValueError("invalid table cell fields")
        cell: dict[str, Any] = {
            "row": row,
            "col": col,
            "row_span": row_span,
            "col_span": col_span,
            "is_header": is_header,
            "text": text.strip(),
        }
        cell_coordinates = {
            (covered_row, covered_col)
            for covered_row in range(row, row + row_span)
            for covered_col in range(col, col + col_span)
        }
        if covered_coordinates & cell_coordinates:
            raise ValueError("overlapping table cells")
        covered_coordinates.update(cell_coordinates)
        raw_nested = raw_cell.get("nested")
        if raw_nested is not None:
            if not isinstance(raw_nested, list):
                raise ValueError("invalid nested tables")
            cell["nested"] = [
                _normalize_table(nested, depth=depth + 1) for nested in raw_nested
            ]
        cells.append(cell)
    cells.sort(key=lambda cell: (cell["row"], cell["col"]))
    normalized["cells"] = cells
    return normalized


def _normalize_tables(payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    table_count = payload.get("tableCount")
    raw_tables = payload.get("tables")
    if not _integer(table_count) or not isinstance(raw_tables, list):
        raise ValueError("invalid table envelope")
    if table_count != len(raw_tables):
        raise ValueError("table count mismatch")
    return tuple(_normalize_table(table) for table in raw_tables)


def extract_rhwp(
    command: str,
    path: Path,
    timeout_seconds: int,
) -> RhwpAttempt:
    version = rhwp_version(command)
    if os.environ.get("MIDPROJECTRAG_RHWP_SHA256") and not is_verified_rhwp_identity(
        version
    ):
        return RhwpAttempt(
            status="failed",
            extractor_version=version,
            pages=(),
            tables=(),
            error_code="rhwp_binary_unverified",
        )
    text_payload, text_error = _run_json(
        command,
        "export-text",
        path,
        timeout_seconds,
        "text",
    )
    if text_payload is None:
        return RhwpAttempt(
            status="failed",
            extractor_version=version,
            pages=(),
            tables=(),
            error_code=text_error,
        )
    try:
        page_count, pages = _normalize_pages(text_payload)
    except ValueError:
        return RhwpAttempt(
            status="failed",
            extractor_version=version,
            pages=(),
            tables=(),
            error_code="rhwp_text_contract_invalid",
        )
    if not pages:
        return RhwpAttempt(
            status="failed",
            extractor_version=version,
            pages=(),
            tables=(),
            page_count=page_count,
            error_code="rhwp_no_text",
        )

    table_payload, table_error = _run_json(
        command,
        "export-tables",
        path,
        timeout_seconds,
        "tables",
    )
    if table_payload is None:
        return RhwpAttempt(
            status="partial",
            extractor_version=version,
            pages=pages,
            tables=(),
            page_count=page_count,
            warnings=(str(table_error),),
        )
    try:
        tables = _normalize_tables(table_payload)
    except ValueError:
        return RhwpAttempt(
            status="partial",
            extractor_version=version,
            pages=pages,
            tables=(),
            page_count=page_count,
            warnings=("rhwp_tables_contract_invalid",),
        )
    return RhwpAttempt(
        status="ok",
        extractor_version=version,
        pages=pages,
        tables=tables,
        page_count=page_count,
    )


def table_text(table: dict[str, Any]) -> str:
    lines: list[str] = []

    if table.get("caption"):
        lines.append(f"[caption] {table['caption']}")

    def visit(value: dict[str, Any], prefix: str) -> None:
        for cell in value["cells"]:
            coordinate = f"{prefix}r{cell['row'] + 1}c{cell['col'] + 1}"
            flags = [coordinate]
            if cell["row_span"] > 1:
                flags.append(f"rowspan={cell['row_span']}")
            if cell["col_span"] > 1:
                flags.append(f"colspan={cell['col_span']}")
            if cell["is_header"]:
                flags.append("header")
            if cell["text"]:
                lines.append(f"[{' '.join(flags)}] {cell['text']}")
            for nested_index, nested in enumerate(cell.get("nested", []), start=1):
                visit(nested, f"{coordinate}.t{nested_index}.")

    visit(table, "")
    return "\n".join(lines)
