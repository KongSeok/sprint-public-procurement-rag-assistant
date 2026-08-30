from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol

from midprojectrag.ingest.common import canonical_json, read_jsonl, sha256_text


DOC_ID_RE = re.compile(r"^doc_[0-9a-f]{24}$")
BLOCK_ID_RE = re.compile(r"^block_[0-9a-f]{24}$")
CHUNK_ID_RE = re.compile(r"^chunk_[0-9a-f]{24}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PAGE_CHUNK_FIELDS = frozenset(
    {
        "schema_version",
        "chunk_id",
        "doc_id",
        "text",
        "source_block_ids",
        "section_path",
        "page_start",
        "page_end",
        "part_index",
        "part_count",
        "retrieval_role",
        "chunker_id",
        "config_sha256",
        "content_sha256",
    }
)
TABLE_CHUNK_FIELDS = frozenset(
    {
        "schema_version",
        "chunk_id",
        "doc_id",
        "text",
        "display_markdown",
        "source_block_ids",
        "section_path",
        "page_start",
        "page_end",
        "source_locator",
        "row_start",
        "row_end",
        "part_index",
        "part_count",
        "retrieval_role",
        "chunker_id",
        "config_sha256",
        "content_sha256",
        "display_sha256",
        "source_structure_sha256",
        "table_structure_sha256",
        "header_source",
    }
)


class TextCounter(Protocol):
    def count(self, text: str) -> int: ...


@dataclass(frozen=True)
class PageChunkConfig:
    """Configuration for the naive one-primary-page-per-chunk baseline."""

    chunker_id: str = "page-v1"
    max_chars: int = 24_000

    def __post_init__(self) -> None:
        if self.chunker_id != "page-v1":
            raise ValueError("unsupported_chunker_id")
        if self.max_chars < 256:
            raise ValueError("max_chars_too_small")

    @property
    def config_sha256(self) -> str:
        return sha256_text(
            canonical_json(
                {
                    "chunker_id": self.chunker_id,
                    "max_chars": self.max_chars,
                    "retrieval_role": "primary",
                    "split_policy": "last-newline-v1",
                }
            )
        )


@dataclass(frozen=True)
class TableChunkConfig:
    """Deterministic Markdown row groups for the structured table lane."""

    chunker_id: str = "table-md-rowgroup-v1"
    max_rows: int = 8
    max_chars: int = 2_400
    max_tokens: int = 600
    summary_chars: int = 320
    tokenizer_id: str = "cl100k_base-pinned"

    def __post_init__(self) -> None:
        if self.chunker_id != "table-md-rowgroup-v1":
            raise ValueError("unsupported_table_chunker_id")
        if not 1 <= self.max_rows <= 64:
            raise ValueError("invalid_table_max_rows")
        if not 256 <= self.max_chars <= 24_000:
            raise ValueError("invalid_table_max_chars")
        if not 64 <= self.max_tokens <= 8_192:
            raise ValueError("invalid_table_max_tokens")
        if not 0 <= self.summary_chars <= 2_000:
            raise ValueError("invalid_table_summary_chars")
        if not isinstance(self.tokenizer_id, str) or not self.tokenizer_id.strip():
            raise ValueError("invalid_table_tokenizer_id")

    @property
    def config_sha256(self) -> str:
        return sha256_text(
            canonical_json(
                {
                    "chunker_id": self.chunker_id,
                    "context_prefix_policy": "mandatory-caption-parent-summary-200token-v1",
                    "header_policy": "explicit-then-conservative-first-row-v1",
                    "markdown_escape_policy": "pipe-backslash-html-newline-v1",
                    "max_chars": self.max_chars,
                    "max_rows": self.max_rows,
                    "max_tokens": self.max_tokens,
                    "nested_policy": "sibling-table-chunks-v1",
                    "oversize_row_policy": "vertical-key-value-segments-v1",
                    "retrieval_role": "structured_auxiliary",
                    "span_policy": "repeat-covered-cell-v1",
                    "summary_chars": self.summary_chars,
                    "tokenizer_id": self.tokenizer_id,
                }
            )
        )


def _split_at_newlines(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    parts: list[str] = []
    cursor = 0
    while cursor < len(text):
        limit = min(cursor + max_chars, len(text))
        if limit < len(text):
            minimum_cut = cursor + max_chars // 2
            double_newline = text.rfind("\n\n", minimum_cut, limit)
            single_newline = text.rfind("\n", minimum_cut, limit)
            cut = double_newline if double_newline >= minimum_cut else single_newline
            if cut < minimum_cut:
                cut = limit
        else:
            cut = limit
        part = text[cursor:cut].strip()
        if part:
            parts.append(part)
        cursor = cut
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
    if not parts:
        raise ValueError("empty_chunk_after_split")
    return parts


def _require_string(value: Any, error_code: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(error_code)
    return value


def _validate_common_chunk(chunk: dict[str, Any]) -> tuple[str, str, str, str, list[str]]:
    doc_id = chunk.get("doc_id")
    chunk_id = chunk.get("chunk_id")
    if not isinstance(doc_id, str) or DOC_ID_RE.fullmatch(doc_id) is None:
        raise ValueError("invalid_chunk_doc_id")
    if not isinstance(chunk_id, str) or CHUNK_ID_RE.fullmatch(chunk_id) is None:
        raise ValueError("invalid_chunk_id")
    text = chunk.get("text")
    content_sha256 = chunk.get("content_sha256")
    config_sha256 = chunk.get("config_sha256")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("invalid_chunk_text")
    if not isinstance(content_sha256, str) or SHA256_RE.fullmatch(content_sha256) is None:
        raise ValueError("invalid_chunk_content_hash")
    if sha256_text(text) != content_sha256:
        raise ValueError("chunk_content_hash_mismatch")
    if not isinstance(config_sha256, str) or SHA256_RE.fullmatch(config_sha256) is None:
        raise ValueError("invalid_chunk_config_hash")
    source_block_ids = chunk.get("source_block_ids")
    if (
        not isinstance(source_block_ids, list)
        or len(source_block_ids) != 1
        or any(not isinstance(item, str) or BLOCK_ID_RE.fullmatch(item) is None for item in source_block_ids)
        or len(source_block_ids) != len(set(source_block_ids))
    ):
        raise ValueError("invalid_chunk_source_block_ids")
    section_path = chunk.get("section_path")
    if not isinstance(section_path, list) or any(
        not isinstance(item, str) or not item for item in section_path
    ):
        raise ValueError("invalid_chunk_section_path")
    return doc_id, chunk_id, content_sha256, config_sha256, source_block_ids


def _validate_part(chunk: dict[str, Any]) -> tuple[int, int]:
    part_index = chunk.get("part_index")
    part_count = chunk.get("part_count")
    if (
        not isinstance(part_index, int)
        or isinstance(part_index, bool)
        or part_index < 0
        or not isinstance(part_count, int)
        or isinstance(part_count, bool)
        or part_count < 1
        or part_index >= part_count
    ):
        raise ValueError("invalid_chunk_part")
    return part_index, part_count


def _validate_page_chunk(chunk: dict[str, Any]) -> None:
    if set(chunk) != PAGE_CHUNK_FIELDS:
        raise ValueError("invalid_chunk_shape")
    if chunk.get("schema_version") != "1.0":
        raise ValueError("invalid_chunk_schema_version")
    doc_id, chunk_id, content_sha256, config_sha256, source_block_ids = (
        _validate_common_chunk(chunk)
    )
    page_start = chunk.get("page_start")
    page_end = chunk.get("page_end")
    if (
        not isinstance(page_start, int)
        or isinstance(page_start, bool)
        or page_start < 1
        or not isinstance(page_end, int)
        or isinstance(page_end, bool)
        or page_end < page_start
    ):
        raise ValueError("invalid_chunk_page_range")
    part_index, part_count = _validate_part(chunk)
    if chunk.get("retrieval_role") != "primary" or chunk.get("chunker_id") != "page-v1":
        raise ValueError("invalid_chunk_role_or_chunker")
    identity = {
        "block_id": source_block_ids[0],
        "config_sha256": config_sha256,
        "content_sha256": content_sha256,
        "doc_id": doc_id,
        "page_end": page_end,
        "page_start": page_start,
        "part_count": part_count,
        "part_index": part_index,
    }
    expected_chunk_id = f"chunk_{sha256_text(canonical_json(identity))[:24]}"
    if chunk_id != expected_chunk_id:
        raise ValueError("chunk_identity_mismatch")


def _validate_table_chunk(chunk: dict[str, Any]) -> None:
    if set(chunk) != TABLE_CHUNK_FIELDS:
        raise ValueError("invalid_chunk_shape")
    schema_version = chunk.get("schema_version")
    chunker_id = chunk.get("chunker_id")
    valid_contracts = {
        ("1.1", "table-md-rowgroup-v1"),
        ("1.2", "table-md-visual-context-v2"),
    }
    if (schema_version, chunker_id) not in valid_contracts:
        raise ValueError("invalid_chunk_schema_version")
    doc_id, chunk_id, content_sha256, config_sha256, source_block_ids = (
        _validate_common_chunk(chunk)
    )
    display_markdown = chunk.get("display_markdown")
    display_sha256 = chunk.get("display_sha256")
    if not isinstance(display_markdown, str) or not display_markdown.strip():
        raise ValueError("invalid_table_display_markdown")
    if not isinstance(display_sha256, str) or SHA256_RE.fullmatch(display_sha256) is None:
        raise ValueError("invalid_table_display_hash")
    if sha256_text(display_markdown) != display_sha256:
        raise ValueError("table_display_hash_mismatch")
    for field in ("source_structure_sha256", "table_structure_sha256"):
        value = chunk.get(field)
        if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
            raise ValueError("invalid_table_structure_hash")
    source_locator = chunk.get("source_locator")
    if not isinstance(source_locator, str) or not source_locator.strip():
        raise ValueError("invalid_table_source_locator")
    page_start = chunk.get("page_start")
    page_end = chunk.get("page_end")
    if (page_start is None) != (page_end is None):
        raise ValueError("invalid_chunk_page_range")
    if page_start is not None and (
        not isinstance(page_start, int)
        or isinstance(page_start, bool)
        or page_start < 1
        or not isinstance(page_end, int)
        or isinstance(page_end, bool)
        or page_end < page_start
    ):
        raise ValueError("invalid_chunk_page_range")
    row_start = chunk.get("row_start")
    row_end = chunk.get("row_end")
    if (
        not isinstance(row_start, int)
        or isinstance(row_start, bool)
        or row_start < 0
        or not isinstance(row_end, int)
        or isinstance(row_end, bool)
        or row_end < row_start
    ):
        raise ValueError("invalid_table_row_range")
    part_index, part_count = _validate_part(chunk)
    if (
        chunk.get("retrieval_role") != "structured_auxiliary"
        or chunker_id not in {"table-md-rowgroup-v1", "table-md-visual-context-v2"}
    ):
        raise ValueError("invalid_chunk_role_or_chunker")
    if chunk.get("header_source") not in {"explicit", "inferred", "generic"}:
        raise ValueError("invalid_table_header_source")
    identity = {
        "block_id": source_block_ids[0],
        "config_sha256": config_sha256,
        "content_sha256": content_sha256,
        "doc_id": doc_id,
        "part_count": part_count,
        "part_index": part_index,
        "row_end": row_end,
        "row_start": row_start,
        "source_locator": source_locator,
        "table_structure_sha256": chunk["table_structure_sha256"],
    }
    expected_chunk_id = f"chunk_{sha256_text(canonical_json(identity))[:24]}"
    if chunk_id != expected_chunk_id:
        raise ValueError("chunk_identity_mismatch")


def validate_chunk(chunk: Any) -> None:
    """Validate page-v1 or structured table chunks before any provider call."""

    if not isinstance(chunk, dict):
        raise ValueError("invalid_chunk_shape")
    chunker_id = chunk.get("chunker_id")
    if chunker_id == "page-v1":
        _validate_page_chunk(chunk)
    elif chunker_id in {"table-md-rowgroup-v1", "table-md-visual-context-v2"}:
        _validate_table_chunk(chunk)
    else:
        raise ValueError("invalid_chunk_role_or_chunker")


def _validate_primary_block(block: dict[str, Any], seen_block_ids: set[str]) -> None:
    block_id = _require_string(block.get("block_id"), "invalid_source_block_id")
    if block_id in seen_block_ids:
        raise ValueError("duplicate_source_block_id")
    seen_block_ids.add(block_id)
    _require_string(block.get("doc_id"), "invalid_source_doc_id")
    text = _require_string(block.get("text"), "empty_source_block_text")
    if block.get("block_type") != "page_text":
        raise ValueError("primary_block_not_page_text")
    page_start = block.get("page_start")
    page_end = block.get("page_end")
    if not isinstance(page_start, int) or page_start < 1:
        raise ValueError("primary_page_missing")
    if not isinstance(page_end, int) or page_end < page_start:
        raise ValueError("primary_page_range_invalid")
    section_path = block.get("section_path")
    if not isinstance(section_path, list) or not all(
        isinstance(item, str) and bool(item) for item in section_path
    ):
        raise ValueError("invalid_section_path")
    expected_hash = _require_string(block.get("content_sha256"), "source_content_hash_missing")
    if sha256_text(text) != expected_hash:
        raise ValueError("source_content_hash_mismatch")


def _compact_text(value: Any, *, max_chars: int | None = None) -> str:
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFC", value)
    compact = " ".join(normalized.replace("\r\n", "\n").replace("\r", "\n").split())
    if max_chars is not None and len(compact) > max_chars:
        if max_chars == 0:
            return ""
        compact = compact[: max_chars - 1].rstrip() + "…"
    return compact


def _markdown_cell(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in normalized.split("\n")]
    escaped_lines = []
    for line in lines:
        escaped = line.replace("\\", "\\\\").replace("|", "\\|")
        escaped = escaped.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        escaped_lines.append(escaped)
    return "<br>".join(escaped_lines) or " "


def _expanded_table_grid(
    structure: dict[str, Any],
) -> tuple[list[list[str]], list[list[bool]], bool]:
    rows = structure.get("rows")
    cols = structure.get("cols")
    cells = structure.get("cells")
    if (
        not isinstance(rows, int)
        or isinstance(rows, bool)
        or rows < 1
        or not isinstance(cols, int)
        or isinstance(cols, bool)
        or cols < 1
        or not isinstance(cells, list)
        or not cells
        or structure.get("cell_count") != len(cells)
    ):
        raise ValueError("invalid_table_structure")
    grid = [["" for _ in range(cols)] for _ in range(rows)]
    owners: list[list[tuple[int, int] | None]] = [[None for _ in range(cols)] for _ in range(rows)]
    explicit_header_grid = [[False for _ in range(cols)] for _ in range(rows)]
    has_explicit_header = False
    for cell in cells:
        if not isinstance(cell, dict):
            raise ValueError("invalid_table_cell")
        row = cell.get("row")
        col = cell.get("col")
        row_span = cell.get("row_span")
        col_span = cell.get("col_span")
        text = cell.get("text")
        is_header = cell.get("is_header")
        if (
            not isinstance(row, int)
            or isinstance(row, bool)
            or row < 0
            or not isinstance(col, int)
            or isinstance(col, bool)
            or col < 0
            or not isinstance(row_span, int)
            or isinstance(row_span, bool)
            or row_span < 1
            or not isinstance(col_span, int)
            or isinstance(col_span, bool)
            or col_span < 1
            or row + row_span > rows
            or col + col_span > cols
            or not isinstance(text, str)
            or not isinstance(is_header, bool)
        ):
            raise ValueError("invalid_table_cell")
        if is_header:
            has_explicit_header = True
        value = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n").strip()
        for target_row in range(row, row + row_span):
            for target_col in range(col, col + col_span):
                if owners[target_row][target_col] is not None:
                    raise ValueError("overlapping_table_cell_span")
                owners[target_row][target_col] = (row, col)
                grid[target_row][target_col] = value
                explicit_header_grid[target_row][target_col] = is_header
    return grid, explicit_header_grid, has_explicit_header


_NUMERICISH_RE = re.compile(r"^[\s+\-()\[\]0-9０-９.,:/%₩원억만천백십일年月日년월일시분초]+$")


def _table_headers(
    grid: list[list[str]],
    explicit_header_grid: list[list[bool]],
    has_explicit_header: bool,
) -> tuple[list[str], list[int], str]:
    rows = len(grid)
    cols = len(grid[0])
    header_count = 0
    header_source = "generic"
    if has_explicit_header:
        for row_index, values in enumerate(grid):
            populated = [col for col, value in enumerate(values) if _compact_text(value)]
            if not populated or not all(explicit_header_grid[row_index][col] for col in populated):
                break
            header_count += 1
        if header_count >= rows:
            header_count = 0
        elif header_count:
            header_source = "explicit"
    if header_count == 0 and not has_explicit_header and rows > 1:
        first = [_compact_text(value) for value in grid[0]]
        nonempty = [value for value in first if value]
        textlike = [value for value in nonempty if _NUMERICISH_RE.fullmatch(value) is None]
        if (
            len(nonempty) == cols
            and len(set(nonempty)) == cols
            and max(map(len, nonempty), default=0) <= 80
            and len(textlike) >= max(1, (cols + 1) // 2)
        ):
            header_count = 1
            header_source = "inferred"
    if header_count:
        headers: list[str] = []
        for col in range(cols):
            values: list[str] = []
            for row in range(header_count):
                value = _compact_text(grid[row][col])
                if value and (not values or values[-1] != value):
                    values.append(value)
            headers.append(" > ".join(values) or f"열{col + 1}")
        body_rows = list(range(header_count, rows))
    else:
        headers = [f"열{col + 1}" for col in range(cols)]
        body_rows = list(range(rows))
    if not body_rows:
        raise ValueError("table_has_no_body_rows")
    return headers, body_rows, header_source


def _render_table_markdown(
    headers: list[str], grid: list[list[str]], row_indexes: list[int]
) -> str:
    header = "| " + " | ".join(_markdown_cell(value) for value in headers) + " |"
    separator = "| " + " | ".join("---" for _ in headers) + " |"
    rows = [
        "| " + " | ".join(_markdown_cell(value) for value in grid[row]) + " |"
        for row in row_indexes
    ]
    return "\n".join([header, separator, *rows])


def _render_vertical_row_markdown(pairs: list[tuple[str, str]]) -> str:
    rows = [
        f"| {_markdown_cell(header)} | {_markdown_cell(value)} |"
        for header, value in pairs
    ]
    return "\n".join(["| 열 | 값 |", "| --- | --- |", *rows])


def _split_vertical_pair(
    *,
    header: str,
    value: str,
    fits: Any,
) -> list[list[tuple[str, str]]]:
    if fits(_render_vertical_row_markdown([(header, value)])):
        return [[(header, value)]]
    if not value:
        raise ValueError("table_row_budget_exceeded")
    segments: list[str] = []
    continuation_header = f"{header} (계속)"
    cursor = 0
    while cursor < len(value):
        low = 1
        high = len(value) - cursor
        best = 0
        while low <= high:
            middle = (low + high) // 2
            segment = value[cursor : cursor + middle]
            if fits(_render_vertical_row_markdown([(continuation_header, segment)])):
                best = middle
                low = middle + 1
            else:
                high = middle - 1
        if best < 1:
            raise ValueError("table_row_budget_exceeded")
        segments.append(value[cursor : cursor + best])
        cursor += best
    return [[(continuation_header, segment)] for segment in segments]


def _vertical_row_parts(
    *,
    headers: list[str],
    values: list[str],
    fits: Any,
) -> list[str]:
    parts: list[str] = []
    group: list[tuple[str, str]] = []
    for header, value in zip(headers, values, strict=True):
        candidate = [*group, (header, value)]
        candidate_markdown = _render_vertical_row_markdown(candidate)
        if fits(candidate_markdown):
            group = candidate
            continue
        if group:
            parts.append(_render_vertical_row_markdown(group))
            group = []
        split = _split_vertical_pair(header=header, value=value, fits=fits)
        if len(split) == 1 and split[0] == [(header, value)]:
            group = split[0]
        else:
            parts.extend(_render_vertical_row_markdown(item) for item in split)
    if group:
        parts.append(_render_vertical_row_markdown(group))
    if not parts:
        raise ValueError("table_row_budget_exceeded")
    return parts


def _table_embedding_text(
    *,
    context: Mapping[str, Any],
    source_locator: str,
    caption: str,
    parent_context: str,
    display_markdown: str,
    summary_chars: int,
) -> str:
    lines: list[str] = []
    project_name = _compact_text(context.get("project_name"))
    ordering_agency = _compact_text(context.get("ordering_agency"))
    project_summary = _compact_text(context.get("project_summary"), max_chars=summary_chars)
    if project_name:
        lines.append(f"[사업명] {project_name}")
    if ordering_agency:
        lines.append(f"[발주기관] {ordering_agency}")
    if project_summary:
        lines.append(f"[사업요약] {project_summary}")
    lines.append(f"[표 위치] {source_locator}")
    if caption:
        lines.append(f"[표 제목] {_compact_text(caption, max_chars=200)}")
    if parent_context:
        lines.append(f"[상위 셀] {_compact_text(parent_context, max_chars=200)}")
    return "\n".join([*lines, "", display_markdown])


def _bounded_table_prefix(
    *,
    context: Mapping[str, Any],
    source_locator: str,
    caption: str,
    parent_context: str,
    summary_chars: int,
    counter: TextCounter,
    max_tokens: int,
) -> str:
    mandatory: list[str] = []
    project_name = _compact_text(context.get("project_name"), max_chars=200)
    ordering_agency = _compact_text(context.get("ordering_agency"), max_chars=200)
    if project_name:
        mandatory.append(f"[사업명] {project_name}")
    if ordering_agency:
        mandatory.append(f"[발주기관] {ordering_agency}")
    mandatory.append(f"[표 위치] {_compact_text(source_locator, max_chars=1_000)}")
    if counter.count("\n".join(mandatory)) > max_tokens:
        raise ValueError("table_context_budget_exceeded")

    optional = [
        ("표 제목", _compact_text(caption, max_chars=200)),
        ("상위 셀", _compact_text(parent_context, max_chars=200)),
        ("사업요약", _compact_text(context.get("project_summary"), max_chars=summary_chars)),
    ]
    selected = list(mandatory)
    for label, value in optional:
        if not value:
            continue
        low = 0
        high = len(value)
        best = ""
        while low <= high:
            middle = (low + high) // 2
            candidate_value = _compact_text(value, max_chars=middle)
            candidate_lines = (
                [*selected, f"[{label}] {candidate_value}"]
                if candidate_value
                else selected
            )
            candidate = "\n".join(candidate_lines)
            if counter.count(candidate) <= max_tokens:
                best = candidate_value
                low = middle + 1
            else:
                high = middle - 1
        if best:
            selected.append(f"[{label}] {best}")
    return "\n".join(selected)


def _iter_table_nodes(
    structure: dict[str, Any],
    source_locator: str,
    *,
    parent_context: str = "",
) -> Iterable[tuple[dict[str, Any], str, str]]:
    yield structure, source_locator, parent_context
    cells = structure.get("cells")
    if not isinstance(cells, list):
        return
    ordered = sorted(
        (cell for cell in cells if isinstance(cell, dict)),
        key=lambda cell: (cell.get("row", -1), cell.get("col", -1)),
    )
    for cell in ordered:
        nested = cell.get("nested")
        if not isinstance(nested, list):
            continue
        for nested_index, child in enumerate(nested):
            if not isinstance(child, dict):
                raise ValueError("invalid_nested_table_structure")
            child_locator = (
                f"{source_locator}/cell:{cell.get('row')},{cell.get('col')}"
                f"/nested:{nested_index + 1}"
            )
            yield from _iter_table_nodes(
                child,
                child_locator,
                parent_context=_compact_text(cell.get("text"), max_chars=200),
            )


def _validate_table_block(block: dict[str, Any], seen_block_ids: set[str]) -> None:
    block_id = _require_string(block.get("block_id"), "invalid_source_block_id")
    if BLOCK_ID_RE.fullmatch(block_id) is None:
        raise ValueError("invalid_source_block_id")
    if block_id in seen_block_ids:
        raise ValueError("duplicate_source_block_id")
    seen_block_ids.add(block_id)
    doc_id = _require_string(block.get("doc_id"), "invalid_source_doc_id")
    if DOC_ID_RE.fullmatch(doc_id) is None:
        raise ValueError("invalid_source_doc_id")
    text = _require_string(block.get("text"), "empty_source_block_text")
    if block.get("block_type") != "table" or block.get("retrieval_role") != "structured_auxiliary":
        raise ValueError("auxiliary_block_not_table")
    if sha256_text(text) != _require_string(
        block.get("content_sha256"), "source_content_hash_missing"
    ):
        raise ValueError("source_content_hash_mismatch")
    structure = block.get("table_structure")
    if not isinstance(structure, dict):
        raise ValueError("invalid_table_structure")
    structure_sha256 = _require_string(
        block.get("structure_sha256"), "source_structure_hash_missing"
    )
    if sha256_text(canonical_json(structure)) != structure_sha256:
        raise ValueError("source_structure_hash_mismatch")
    source_locator = _require_string(
        block.get("source_locator"), "invalid_table_source_locator"
    )
    if len(source_locator) > 1_000:
        raise ValueError("invalid_table_source_locator")
    section_path = block.get("section_path")
    if not isinstance(section_path, list) or any(
        not isinstance(item, str) or not item for item in section_path
    ):
        raise ValueError("invalid_section_path")
    page_start = block.get("page_start")
    page_end = block.get("page_end")
    if (page_start is None) != (page_end is None):
        raise ValueError("invalid_table_page_range")
    if page_start is not None and (
        not isinstance(page_start, int)
        or isinstance(page_start, bool)
        or page_start < 1
        or not isinstance(page_end, int)
        or isinstance(page_end, bool)
        or page_end < page_start
    ):
        raise ValueError("invalid_table_page_range")


def _table_layout_by_block(
    layout_records: Iterable[dict[str, Any]] | None,
    table_blocks: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    if layout_records is None:
        return {}
    records: dict[str, dict[str, Any]] = {}
    for record in layout_records:
        if not isinstance(record, dict) or record.get("schema_version") != "1.0":
            raise ValueError("invalid_table_layout_record")
        block_id = record.get("block_id")
        doc_id = record.get("doc_id")
        structure_sha256 = record.get("structure_sha256")
        status = record.get("status")
        if (
            not isinstance(block_id, str)
            or BLOCK_ID_RE.fullmatch(block_id) is None
            or block_id in records
            or not isinstance(doc_id, str)
            or DOC_ID_RE.fullmatch(doc_id) is None
            or not isinstance(structure_sha256, str)
            or SHA256_RE.fullmatch(structure_sha256) is None
            or status
            not in {"verified_render", "paragraph_anchor_candidate", "nonbody_unlinked"}
        ):
            raise ValueError("invalid_table_layout_record")
        page_start = record.get("page_start")
        page_end = record.get("page_end")
        if status == "verified_render":
            if (
                not isinstance(page_start, int)
                or isinstance(page_start, bool)
                or page_start < 1
                or not isinstance(page_end, int)
                or isinstance(page_end, bool)
                or page_end < page_start
            ):
                raise ValueError("invalid_table_layout_record")
        elif page_start is not None or page_end is not None:
            raise ValueError("invalid_table_layout_record")
        records[block_id] = record
    expected = {block["block_id"] for block in table_blocks}
    if set(records) != expected:
        raise ValueError("table_layout_block_set_mismatch")
    for block in table_blocks:
        record = records[block["block_id"]]
        if (
            record["doc_id"] != block["doc_id"]
            or record["structure_sha256"] != block["structure_sha256"]
        ):
            raise ValueError("table_layout_source_mismatch")
    return records


def build_page_chunks(
    source_blocks: Iterable[dict[str, Any]],
    config: PageChunkConfig | None = None,
) -> list[dict[str, Any]]:
    config = config or PageChunkConfig()
    primary_blocks = [block for block in source_blocks if block.get("retrieval_role") == "primary"]
    primary_blocks.sort(
        key=lambda block: (
            str(block.get("doc_id", "")),
            block.get("page_start") if isinstance(block.get("page_start"), int) else -1,
            block.get("sequence") if isinstance(block.get("sequence"), int) else -1,
            str(block.get("block_id", "")),
        )
    )
    chunks: list[dict[str, Any]] = []
    seen_block_ids: set[str] = set()
    seen_chunk_ids: set[str] = set()
    for block in primary_blocks:
        _validate_primary_block(block, seen_block_ids)
        text_parts = _split_at_newlines(block["text"], config.max_chars)
        part_count = len(text_parts)
        for part_index, text in enumerate(text_parts):
            content_sha256 = sha256_text(text)
            identity = {
                "block_id": block["block_id"],
                "config_sha256": config.config_sha256,
                "content_sha256": content_sha256,
                "doc_id": block["doc_id"],
                "page_end": block["page_end"],
                "page_start": block["page_start"],
                "part_count": part_count,
                "part_index": part_index,
            }
            chunk_id = f"chunk_{sha256_text(canonical_json(identity))[:24]}"
            if chunk_id in seen_chunk_ids:
                raise ValueError("duplicate_chunk_id")
            seen_chunk_ids.add(chunk_id)
            chunk = {
                    "schema_version": "1.0",
                    "chunk_id": chunk_id,
                    "doc_id": block["doc_id"],
                    "text": text,
                    "source_block_ids": [block["block_id"]],
                    "section_path": list(block["section_path"]),
                    "page_start": block["page_start"],
                    "page_end": block["page_end"],
                    "part_index": part_index,
                    "part_count": part_count,
                    "retrieval_role": "primary",
                    "chunker_id": config.chunker_id,
                    "config_sha256": config.config_sha256,
                    "content_sha256": content_sha256,
                }
            validate_chunk(chunk)
            chunks.append(chunk)
    if not chunks:
        raise ValueError("no_primary_blocks")
    return chunks


def build_table_chunks(
    source_blocks: Iterable[dict[str, Any]],
    document_contexts: Mapping[str, Mapping[str, Any]],
    *,
    counter: TextCounter,
    config: TableChunkConfig | None = None,
    layout_records: Iterable[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    config = config or TableChunkConfig()
    all_table_blocks = [
        block
        for block in source_blocks
        if block.get("retrieval_role") == "structured_auxiliary"
        and block.get("block_type") == "table"
    ]
    layout_by_block = _table_layout_by_block(layout_records, all_table_blocks)
    table_blocks = []
    for block in all_table_blocks:
        if (
            block.get("retrieval_role") != "structured_auxiliary"
            or block.get("block_type") != "table"
        ):
            continue
        structure = block.get("table_structure")
        # Repeated header/footer tables do not have a unique body-page owner.
        # Keep them in canonical source blocks, but exclude them from table-v1.
        if isinstance(structure, dict) and structure.get("container_path"):
            continue
        table_blocks.append(block)
    table_blocks.sort(
        key=lambda block: (
            str(block.get("doc_id", "")),
            block.get("sequence") if isinstance(block.get("sequence"), int) else -1,
            str(block.get("block_id", "")),
        )
    )
    chunks: list[dict[str, Any]] = []
    seen_block_ids: set[str] = set()
    seen_chunk_ids: set[str] = set()
    for block in table_blocks:
        _validate_table_block(block, seen_block_ids)
        doc_id = block["doc_id"]
        context = document_contexts.get(doc_id)
        if not isinstance(context, Mapping):
            raise ValueError("table_document_context_missing")
        source_structure_sha256 = block["structure_sha256"]
        for structure, source_locator, parent_context in _iter_table_nodes(
            block["table_structure"], block["source_locator"]
        ):
            grid, explicit_header_grid, has_explicit_header = _expanded_table_grid(structure)
            headers, body_rows, header_source = _table_headers(
                grid,
                explicit_header_grid,
                has_explicit_header,
            )
            caption = structure.get("caption") if isinstance(structure.get("caption"), str) else ""
            prefix = _bounded_table_prefix(
                context=context,
                source_locator=source_locator,
                caption=caption,
                parent_context=parent_context,
                summary_chars=config.summary_chars,
                counter=counter,
                max_tokens=min(200, max(32, config.max_tokens // 3)),
            )
            parts: list[tuple[list[int], str]] = []

            def fits(display_markdown: str) -> bool:
                embedding_text = f"{prefix}\n\n{display_markdown}"
                return (
                    len(embedding_text) <= config.max_chars
                    and counter.count(embedding_text) <= config.max_tokens
                )

            cursor = 0
            while cursor < len(body_rows):
                group: list[int] = []
                while cursor < len(body_rows) and len(group) < config.max_rows:
                    candidate = [*group, body_rows[cursor]]
                    display_markdown = _render_table_markdown(headers, grid, candidate)
                    if fits(display_markdown):
                        group = candidate
                        cursor += 1
                        continue
                    if not group:
                        row_index = body_rows[cursor]
                        for vertical_markdown in _vertical_row_parts(
                            headers=headers,
                            values=grid[row_index],
                            fits=fits,
                        ):
                            parts.append(([row_index], vertical_markdown))
                        cursor += 1
                    break
                if group:
                    parts.append((group, _render_table_markdown(headers, grid, group)))
            part_count = len(parts)
            table_structure_sha256 = sha256_text(canonical_json(structure))
            is_top_level = source_locator == block["source_locator"]
            if is_top_level:
                chunk_page_start = (
                    layout_by_block[block["block_id"]]["page_start"]
                    if layout_by_block
                    else block["page_start"]
                )
                chunk_page_end = (
                    layout_by_block[block["block_id"]]["page_end"]
                    if layout_by_block
                    else block["page_end"]
                )
            else:
                # A parent table's page does not independently prove where a
                # nested table rendered. Keep only its structural locator.
                chunk_page_start = None
                chunk_page_end = None
            for part_index, (row_indexes, display_markdown) in enumerate(parts):
                text = f"{prefix}\n\n{display_markdown}"
                content_sha256 = sha256_text(text)
                identity = {
                    "block_id": block["block_id"],
                    "config_sha256": config.config_sha256,
                    "content_sha256": content_sha256,
                    "doc_id": doc_id,
                    "part_count": part_count,
                    "part_index": part_index,
                    "row_end": row_indexes[-1],
                    "row_start": row_indexes[0],
                    "source_locator": source_locator,
                    "table_structure_sha256": table_structure_sha256,
                }
                chunk_id = f"chunk_{sha256_text(canonical_json(identity))[:24]}"
                if chunk_id in seen_chunk_ids:
                    raise ValueError("duplicate_chunk_id")
                seen_chunk_ids.add(chunk_id)
                chunk = {
                    "schema_version": "1.1",
                    "chunk_id": chunk_id,
                    "doc_id": doc_id,
                    "text": text,
                    "display_markdown": display_markdown,
                    "source_block_ids": [block["block_id"]],
                    "section_path": list(block["section_path"]),
                    "page_start": chunk_page_start,
                    "page_end": chunk_page_end,
                    "source_locator": source_locator,
                    "row_start": row_indexes[0],
                    "row_end": row_indexes[-1],
                    "part_index": part_index,
                    "part_count": part_count,
                    "retrieval_role": "structured_auxiliary",
                    "chunker_id": config.chunker_id,
                    "config_sha256": config.config_sha256,
                    "content_sha256": content_sha256,
                    "display_sha256": sha256_text(display_markdown),
                    "source_structure_sha256": source_structure_sha256,
                    "table_structure_sha256": table_structure_sha256,
                    "header_source": header_source,
                }
                validate_chunk(chunk)
                chunks.append(chunk)
    if not chunks:
        raise ValueError("no_table_blocks")
    return chunks


def build_page_chunks_from_manifest(
    manifest_path: Path,
    blocks_dir: Path,
    config: PageChunkConfig | None = None,
) -> list[dict[str, Any]]:
    manifest_rows = read_jsonl(manifest_path)
    blocks: list[dict[str, Any]] = []
    seen_doc_ids: set[str] = set()
    for row in sorted(manifest_rows, key=lambda item: str(item.get("doc_id", ""))):
        doc_id = _require_string(row.get("doc_id"), "invalid_manifest_doc_id")
        if doc_id in seen_doc_ids:
            raise ValueError("duplicate_manifest_doc_id")
        seen_doc_ids.add(doc_id)
        if row.get("status") != "ok" or row.get("index_eligible") is not True:
            raise ValueError("manifest_document_not_index_eligible")
        block_path = blocks_dir / f"{doc_id}.jsonl"
        if not block_path.is_file():
            raise ValueError("source_block_file_missing")
        document_blocks = read_jsonl(block_path)
        for block in document_blocks:
            if block.get("doc_id") != doc_id:
                raise ValueError("source_block_doc_id_mismatch")
        blocks.extend(document_blocks)
    return build_page_chunks(blocks, config)


def build_table_chunks_from_manifest(
    manifest_path: Path,
    blocks_dir: Path,
    *,
    counter: TextCounter,
    config: TableChunkConfig | None = None,
    layout_records: Iterable[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    manifest_rows = read_jsonl(manifest_path)
    blocks: list[dict[str, Any]] = []
    contexts: dict[str, Mapping[str, Any]] = {}
    seen_doc_ids: set[str] = set()
    for row in sorted(manifest_rows, key=lambda item: str(item.get("doc_id", ""))):
        doc_id = _require_string(row.get("doc_id"), "invalid_manifest_doc_id")
        if doc_id in seen_doc_ids:
            raise ValueError("duplicate_manifest_doc_id")
        seen_doc_ids.add(doc_id)
        if row.get("status") != "ok" or row.get("index_eligible") is not True:
            raise ValueError("manifest_document_not_index_eligible")
        metadata = row.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError("invalid_manifest_metadata")
        contexts[doc_id] = {
            "project_name": metadata.get("project_name", ""),
            "ordering_agency": metadata.get("ordering_agency", ""),
            "project_summary": metadata.get("project_summary", ""),
        }
        block_path = blocks_dir / f"{doc_id}.jsonl"
        if not block_path.is_file():
            raise ValueError("source_block_file_missing")
        document_blocks = read_jsonl(block_path)
        for block in document_blocks:
            if block.get("doc_id") != doc_id:
                raise ValueError("source_block_doc_id_mismatch")
        blocks.extend(document_blocks)
    return build_table_chunks(
        blocks,
        contexts,
        counter=counter,
        config=config,
        layout_records=layout_records,
    )


def chunk_artifact_sha256(chunks: Iterable[dict[str, Any]]) -> str:
    return sha256_text("".join(canonical_json(chunk) + "\n" for chunk in chunks))
