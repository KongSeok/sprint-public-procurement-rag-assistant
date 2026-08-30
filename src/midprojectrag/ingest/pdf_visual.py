from __future__ import annotations

import hashlib
import math
import os
import re
import stat
import tempfile
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from pathlib import Path
from types import MappingProxyType
from typing import Any, BinaryIO

from midprojectrag.ingest.common import canonical_json, require_sha256, sha256_text


PDF_VISUAL_SCHEMA_VERSION = "1.0"
COORDINATE_SPACE = "pdf_points_top_left"
EXTRACTION_METHOD = "pdfplumber_lines_v1"
CONTEXT_METHOD = "nearest_prior_same_page_textline_outside_tables"
SCHEDULE_GEOMETRY_METHOD = "pdfplumber_word_rowband_fill_overlap_v1"

_DOC_ID_PATTERN = re.compile(r"^doc_[0-9a-f]{24}$")
_PERIOD_HEADER_PATTERN = re.compile(r"^M(?:\+(\d+))?$")
_BBOX_FIELDS = ("x", "y", "w", "h")
_MIN_SUBSTANTIVE_FILL_SIDE = 1.5
_MIN_SUBSTANTIVE_FILL_AREA = 8.0
_NEAR_WHITE_COMPONENT = 0.97
_MIN_PERIOD_HEADER_COUNT = 2
_MIN_PERIOD_FILL_COVERAGE = 0.20
_OBVIOUS_FRAME_MIN_WIDTH_RATIO = 0.85
_OBVIOUS_FRAME_MIN_HEIGHT_RATIO = 0.85
_ROW_BOUNDARY_Y_TOLERANCE = 3.0
_ROW_BOUNDARY_LEFT_TOLERANCE = 3.0
_DISTINCT_ROW_BOUNDARY_TOLERANCE = 1.0
_MIN_EXTERNAL_ROW_BOUNDARIES = 2
_MILESTONE_MARKERS = frozenset({"★", "▲", "●", "◆", "■", "▼"})
_ABSOLUTE_LIMITS = {
    "max_file_bytes": 4 * 1024 * 1024 * 1024,
    "max_pages": 10_000,
    "max_page_objects": 1_000_000,
    "max_tables_per_page": 10_000,
    "max_images_per_page": 100_000,
    "max_table_rows": 10_000,
    "max_table_cols": 10_000,
    "max_table_cells": 1_000_000,
    "max_cell_chars": 100_000,
    "max_context_chars": 10_000,
    "max_text_chars_per_page": 10_000_000,
    "max_text_chars_per_document": 100_000_000,
    "max_fills_per_table": 1_000_000,
    "max_geometry_comparisons": 20_000_000,
    "max_visual_records_per_document": 2_000_000,
    "max_analyses_per_document": 2_000_000,
}

# Keep every setting explicit so upgrades cannot silently switch the detector
# away from ruled-line tables.
LINES_TABLE_SETTINGS: Mapping[str, Any] = MappingProxyType(
    {
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
        "snap_tolerance": 3,
        "join_tolerance": 3,
        "edge_min_length": 3,
        "min_words_vertical": 3,
        "min_words_horizontal": 1,
        "intersection_tolerance": 3,
        "text_x_tolerance": 3,
        "text_y_tolerance": 3,
    }
)
LINES_TABLE_SETTINGS_SHA256 = sha256_text(
    canonical_json(dict(LINES_TABLE_SETTINGS))
)


class PdfVisualError(ValueError):
    """A stable, non-sensitive PDF visual extraction error."""


@dataclass(frozen=True, slots=True)
class PdfWordEvidence:
    """A normalized native-PDF word and its top-left point-space bbox."""

    text: str
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class PdfScheduleRowEvidence:
    """Best-effort schedule evidence retained outside the schema-v1 record."""

    row_index: int
    label: str
    label_bbox: tuple[float, float, float, float]
    active_periods: tuple[str, ...]
    milestone_periods: tuple[str, ...]
    role: str
    confidence: float
    recovered_matrix_cell: bool


@dataclass(frozen=True, slots=True)
class PdfTableGeometryAnalysis:
    """In-memory analysis for callers that explicitly request provenance.

    The persisted v1 record is intentionally unchanged because its JSON Schema
    is strict.  Callers may pass ``analysis_sink`` to
    :func:`extract_pdf_visual_evidence` to receive these objects after the
    source checksum has been reverified.
    """

    page: int
    table_ordinal: int
    bbox: tuple[float, float, float, float]
    matrix: tuple[tuple[str | None, ...], ...]
    inside_words: tuple[PdfWordEvidence, ...]
    schedule_rows: tuple[PdfScheduleRowEvidence, ...]
    recovered_cell_texts: tuple[str, ...]
    confidence: float
    provenance: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PdfVisualLimits:
    max_file_bytes: int = 512 * 1024 * 1024
    max_pages: int = 2_000
    max_page_objects: int = 250_000
    max_tables_per_page: int = 1_000
    max_images_per_page: int = 10_000
    max_table_rows: int = 2_000
    max_table_cols: int = 2_000
    max_table_cells: int = 250_000
    max_cell_chars: int = 20_000
    max_context_chars: int = 500
    max_text_chars_per_page: int = 2_000_000
    max_text_chars_per_document: int = 20_000_000
    max_fills_per_table: int = 100_000
    max_geometry_comparisons: int = 2_000_000
    max_visual_records_per_document: int = 250_000
    max_analyses_per_document: int = 100_000

    def validate(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 1
                or value > _ABSOLUTE_LIMITS[field.name]
            ):
                raise PdfVisualError("pdf_visual_limits_invalid")


@dataclass(slots=True)
class _TextBudget:
    limits: PdfVisualLimits
    document_chars: int = 0
    page_chars: int = 0

    def start_page(self) -> None:
        self.page_chars = 0

    def consume(self, value: str) -> None:
        length = len(value)
        self.page_chars += length
        self.document_chars += length
        if self.page_chars > self.limits.max_text_chars_per_page:
            raise PdfVisualError("pdf_page_text_limit_exceeded")
        if self.document_chars > self.limits.max_text_chars_per_document:
            raise PdfVisualError("pdf_document_text_limit_exceeded")


@dataclass(slots=True)
class _GeometryBudget:
    limit: int
    comparisons: int = 0

    def consume(self, count: int = 1) -> None:
        if count < 0:
            raise PdfVisualError("pdf_geometry_work_limit_exceeded")
        self.comparisons += count
        if self.comparisons > self.limit:
            raise PdfVisualError("pdf_geometry_work_limit_exceeded")


@dataclass(slots=True)
class _DocumentVisualBudget:
    limits: PdfVisualLimits
    record_count: int = 0
    analysis_count: int = 0

    def consume_record(self) -> None:
        if self.record_count >= self.limits.max_visual_records_per_document:
            raise PdfVisualError("pdf_visual_record_limit_exceeded")
        self.record_count += 1

    def consume_analysis(self) -> None:
        if self.analysis_count >= self.limits.max_analyses_per_document:
            raise PdfVisualError("pdf_analysis_limit_exceeded")
        self.analysis_count += 1


def _open_pdf(source: BinaryIO) -> Any:
    """Import pdfplumber only when the optional PDF fidelity lane is used."""

    try:
        import pdfplumber  # type: ignore[import-not-found]
    except (ImportError, ModuleNotFoundError):
        raise PdfVisualError("pdfplumber_unavailable") from None
    try:
        return pdfplumber.open(source)
    except Exception:
        raise PdfVisualError("pdf_parse_failed") from None


def _sha256_stream(source: BinaryIO) -> str:
    try:
        source.seek(0)
        digest = hashlib.sha256()
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
        source.seek(0)
        return digest.hexdigest()
    except Exception:
        raise PdfVisualError("pdf_source_hash_failed") from None


def _source_stat_signature(value: os.stat_result) -> tuple[int, int, int, int, int]:
    """Return the source identity and mutation-sensitive metadata."""

    try:
        return (
            int(value.st_dev),
            int(value.st_ino),
            int(value.st_size),
            int(value.st_mtime_ns),
            int(value.st_ctime_ns),
        )
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise PdfVisualError("pdf_source_stat_invalid") from None


def _bounded_source_snapshot(source: BinaryIO, *, max_bytes: int) -> BinaryIO:
    """Copy at most ``max_bytes + 1`` bytes into an anonymous immutable input.

    Parsing and hashing use this snapshot.  The original descriptor remains
    open solely so its metadata can be rechecked after parsing.
    """

    snapshot: BinaryIO | None = None
    try:
        source.seek(0)
        snapshot = tempfile.TemporaryFile(mode="w+b")
        total = 0
        while total <= max_bytes:
            remaining = max_bytes + 1 - total
            chunk = source.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            if not isinstance(chunk, bytes):
                raise PdfVisualError("pdf_source_snapshot_failed")
            total += len(chunk)
            if total > max_bytes:
                raise PdfVisualError("pdf_file_size_limit_exceeded")
            snapshot.write(chunk)
        snapshot.flush()
        snapshot.seek(0)
        source.seek(0)
        return snapshot
    except PdfVisualError:
        if snapshot is not None:
            snapshot.close()
        raise
    except Exception:
        if snapshot is not None:
            try:
                snapshot.close()
            except Exception:
                pass
        raise PdfVisualError("pdf_source_snapshot_failed") from None


def _number(value: Any, error_code: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        raise PdfVisualError(error_code)
    normalized = round(float(value), 6)
    return 0.0 if normalized == 0 else normalized


def _bbox(value: Any, error_code: str) -> dict[str, float]:
    if isinstance(value, Mapping):
        if all(field in value for field in ("x0", "top", "x1", "bottom")):
            x0, top, x1, bottom = (
                value["x0"],
                value["top"],
                value["x1"],
                value["bottom"],
            )
        elif set(value) == set(_BBOX_FIELDS):
            x = _number(value["x"], error_code)
            y = _number(value["y"], error_code)
            width = _number(value["w"], error_code)
            height = _number(value["h"], error_code)
            if width <= 0 or height <= 0:
                raise PdfVisualError(error_code)
            return {"x": x, "y": y, "w": width, "h": height}
        else:
            raise PdfVisualError(error_code)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if len(value) != 4:
            raise PdfVisualError(error_code)
        x0, top, x1, bottom = value
    else:
        raise PdfVisualError(error_code)

    left = _number(x0, error_code)
    upper = _number(top, error_code)
    right = _number(x1, error_code)
    lower = _number(bottom, error_code)
    if right <= left or lower <= upper:
        raise PdfVisualError(error_code)
    return {
        "x": left,
        "y": upper,
        "w": _number(right - left, error_code),
        "h": _number(lower - upper, error_code),
    }


def _bbox_sort_key(value: Mapping[str, float]) -> tuple[float, float, float, float]:
    return (value["y"], value["x"], value["h"], value["w"])


def _intersects(left: Mapping[str, float], right: Mapping[str, float]) -> bool:
    return (
        min(left["x"] + left["w"], right["x"] + right["w"])
        > max(left["x"], right["x"])
        and min(left["y"] + left["h"], right["y"] + right["h"])
        > max(left["y"], right["y"])
    )


def _contains(outer: Mapping[str, float], inner: Mapping[str, float]) -> bool:
    tolerance = 0.01
    return (
        inner["x"] >= outer["x"] - tolerance
        and inner["y"] >= outer["y"] - tolerance
        and inner["x"] + inner["w"]
        <= outer["x"] + outer["w"] + tolerance
        and inner["y"] + inner["h"]
        <= outer["y"] + outer["h"] + tolerance
    )


def _normalize_text(value: Any, *, error_code: str, max_chars: int) -> str:
    if not isinstance(value, str):
        raise PdfVisualError(error_code)
    if len(value) > max_chars:
        raise PdfVisualError(error_code)
    return " ".join(unicodedata.normalize("NFC", value).replace("\x00", "").split())


def _normalize_color(value: Any) -> str | float | list[float] | None:
    # This is deliberately raw normalization, not a color-name interpretation.
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isfinite(float(value)):
            return _number(value, "pdf_rect_color_invalid")
        return None
    if isinstance(value, str):
        normalized = value.strip()
        return normalized[:64] if normalized else None
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if not 1 <= len(value) <= 8:
            return None
        result: list[float] = []
        for component in value:
            if (
                not isinstance(component, (int, float))
                or isinstance(component, bool)
                or not math.isfinite(float(component))
            ):
                return None
            result.append(_number(component, "pdf_rect_color_invalid"))
        return result
    return None


def _bbox_tuple(value: Mapping[str, float]) -> tuple[float, float, float, float]:
    return (value["x"], value["y"], value["w"], value["h"])


def _bbox_from_tuple(value: Sequence[float]) -> dict[str, float]:
    if len(value) != 4:
        raise PdfVisualError("pdf_geometry_bbox_invalid")
    return {"x": value[0], "y": value[1], "w": value[2], "h": value[3]}


def _bbox_center(value: Mapping[str, float]) -> tuple[float, float]:
    return (value["x"] + value["w"] / 2, value["y"] + value["h"] / 2)


def _clipped_bbox(
    inner: Mapping[str, float], outer: Mapping[str, float]
) -> dict[str, float] | None:
    left = max(inner["x"], outer["x"])
    top = max(inner["y"], outer["y"])
    right = min(inner["x"] + inner["w"], outer["x"] + outer["w"])
    bottom = min(inner["y"] + inner["h"], outer["y"] + outer["h"])
    if right <= left or bottom <= top:
        return None
    return {"x": left, "y": top, "w": right - left, "h": bottom - top}


def _rectangle_union_area(
    rectangles: Sequence[Mapping[str, float]], *, budget: _GeometryBudget
) -> float:
    """Return exact union area so overlapping fill objects count once."""

    if not rectangles:
        return 0.0
    x_values = sorted(
        {
            value
            for rectangle in rectangles
            for value in (rectangle["x"], rectangle["x"] + rectangle["w"])
        }
    )
    budget.consume(max(0, len(x_values) - 1) * len(rectangles))
    area = 0.0
    for left, right in zip(x_values, x_values[1:], strict=False):
        if right <= left:
            continue
        intervals = sorted(
            (
                rectangle["y"],
                rectangle["y"] + rectangle["h"],
            )
            for rectangle in rectangles
            if rectangle["x"] < right
            and rectangle["x"] + rectangle["w"] > left
        )
        if not intervals:
            continue
        covered_y = 0.0
        current_top, current_bottom = intervals[0]
        for top, bottom in intervals[1:]:
            if top <= current_bottom:
                current_bottom = max(current_bottom, bottom)
            else:
                covered_y += current_bottom - current_top
                current_top, current_bottom = top, bottom
        covered_y += current_bottom - current_top
        area += (right - left) * covered_y
    return area


def _normalized_color_channels(
    value: str | float | list[float] | None,
) -> tuple[float, float, float] | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        component = float(value)
        if not 0.0 <= component <= 1.0:
            return None
        return (component, component, component)
    if isinstance(value, list):
        if len(value) == 1:
            component = float(value[0])
            if not 0.0 <= component <= 1.0:
                return None
            return (component, component, component)
        if len(value) == 3 and all(0.0 <= float(item) <= 1.0 for item in value):
            return (float(value[0]), float(value[1]), float(value[2]))
        if len(value) == 4 and all(0.0 <= float(item) <= 1.0 for item in value):
            cyan, magenta, yellow, black = (float(item) for item in value)
            return (
                (1.0 - cyan) * (1.0 - black),
                (1.0 - magenta) * (1.0 - black),
                (1.0 - yellow) * (1.0 - black),
            )
    return None


def _is_neutral_fill(value: str | float | list[float] | None) -> bool:
    channels = _normalized_color_channels(value)
    if channels is None:
        return False
    return min(channels) >= _NEAR_WHITE_COMPONENT


def _page_words(
    page: Any,
    *,
    page_bbox: Mapping[str, float],
    limits: PdfVisualLimits,
    budget: _TextBudget,
) -> tuple[PdfWordEvidence, ...]:
    """Return bounded native words with pinned settings or fail closed."""

    extractor = getattr(page, "extract_words", None)
    if not callable(extractor):
        raise PdfVisualError("pdf_word_extractor_unavailable")
    try:
        raw_words = extractor(
            x_tolerance=2,
            y_tolerance=2,
            keep_blank_chars=False,
            use_text_flow=False,
        )
    except Exception:
        raise PdfVisualError("pdf_word_extraction_failed") from None
    if not isinstance(raw_words, list):
        raise PdfVisualError("pdf_words_invalid")
    if len(raw_words) > limits.max_page_objects:
        raise PdfVisualError("pdf_page_objects_limit_exceeded")

    result: list[PdfWordEvidence] = []
    for raw in raw_words:
        if not isinstance(raw, Mapping):
            raise PdfVisualError("pdf_word_invalid")
        text = _normalize_text(
            raw.get("text"),
            error_code="pdf_word_text_limit_exceeded",
            max_chars=limits.max_cell_chars,
        )
        if not text:
            continue
        budget.consume(text)
        word_bbox = _bbox(raw, "pdf_word_bbox_invalid")
        if not _contains(page_bbox, word_bbox):
            raise PdfVisualError("pdf_word_bbox_outside_page")
        result.append(PdfWordEvidence(text=text, bbox=_bbox_tuple(word_bbox)))
    return tuple(
        sorted(
            result,
            key=lambda item: (
                item.bbox[1],
                item.bbox[0],
                item.bbox[3],
                item.bbox[2],
                item.text,
            ),
        )
    )


def _page_object_count(page: Any) -> int:
    try:
        objects = getattr(page, "objects", None)
    except Exception:
        raise PdfVisualError("pdf_page_objects_invalid") from None
    if isinstance(objects, Mapping):
        count = 0
        for values in objects.values():
            if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
                raise PdfVisualError("pdf_page_objects_invalid")
            count += len(values)
        return count

    count = 0
    for attribute in ("chars", "lines", "rects", "curves", "images"):
        try:
            values = getattr(page, attribute, [])
        except Exception:
            raise PdfVisualError("pdf_page_objects_invalid") from None
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise PdfVisualError("pdf_page_objects_invalid")
        count += len(values)
    return count


def _text_lines(
    page: Any,
    *,
    table_bboxes: Sequence[Mapping[str, float]],
    limits: PdfVisualLimits,
    budget: _TextBudget,
    geometry_budget: _GeometryBudget,
) -> list[dict[str, Any]]:
    extractor = getattr(page, "extract_text_lines", None)
    if not callable(extractor):
        raise PdfVisualError("pdf_text_line_extractor_unavailable")
    try:
        raw_lines = extractor(layout=False, strip=True, return_chars=False)
    except Exception:
        raise PdfVisualError("pdf_text_line_extraction_failed") from None
    if not isinstance(raw_lines, list):
        raise PdfVisualError("pdf_text_lines_invalid")
    if len(raw_lines) > limits.max_page_objects:
        raise PdfVisualError("pdf_page_objects_limit_exceeded")

    result: list[dict[str, Any]] = []
    for raw in raw_lines:
        if not isinstance(raw, Mapping):
            raise PdfVisualError("pdf_text_line_invalid")
        text = _normalize_text(
            raw.get("text"),
            error_code="pdf_text_line_limit_exceeded",
            max_chars=limits.max_text_chars_per_page,
        )
        budget.consume(text)
        if not text:
            continue
        line_bbox = _bbox(raw, "pdf_text_line_bbox_invalid")
        geometry_budget.consume(len(table_bboxes))
        if any(_intersects(line_bbox, table_bbox) for table_bbox in table_bboxes):
            continue
        result.append({"text": text, "bbox": line_bbox})

    return sorted(result, key=lambda item: (*_bbox_sort_key(item["bbox"]), item["text"]))


def _preceding_text(
    lines: Sequence[Mapping[str, Any]],
    visual_bbox: Mapping[str, float],
    *,
    max_chars: int,
    geometry_budget: _GeometryBudget,
) -> dict[str, Any] | None:
    geometry_budget.consume(len(lines))
    candidates = [
        line
        for line in lines
        if line["bbox"]["y"] + line["bbox"]["h"] <= visual_bbox["y"] + 0.01
    ]
    if not candidates:
        return None
    selected = max(candidates, key=lambda item: _bbox_sort_key(item["bbox"]))
    text = selected["text"][:max_chars]
    return {
        "text": text,
        "text_sha256": sha256_text(text),
        "bbox": dict(selected["bbox"]),
        "method": CONTEXT_METHOD,
    }


def _direct_fill_evidence(
    rects: Any,
    *,
    table_bbox: Mapping[str, float],
    limits: PdfVisualLimits,
    geometry_budget: _GeometryBudget,
) -> list[dict[str, Any]]:
    if not isinstance(rects, Sequence) or isinstance(rects, (str, bytes)):
        raise PdfVisualError("pdf_rects_invalid")
    geometry_budget.consume(len(rects))
    result: list[dict[str, Any]] = []
    for raw in rects:
        if not isinstance(raw, Mapping):
            raise PdfVisualError("pdf_rect_invalid")
        fill_present = raw.get("fill") is True
        if not fill_present:
            continue
        rect_bbox = _bbox(raw, "pdf_rect_bbox_invalid")
        if not _contains(table_bbox, rect_bbox):
            continue
        if (
            min(rect_bbox["w"], rect_bbox["h"])
            < _MIN_SUBSTANTIVE_FILL_SIDE
            or rect_bbox["w"] * rect_bbox["h"] < _MIN_SUBSTANTIVE_FILL_AREA
        ):
            continue
        color = _normalize_color(raw.get("non_stroking_color"))
        # Black is a substantive Gantt encoding in real schedules.  Geometry
        # removes hairlines, while only near-white fills are color-filtered.
        if _is_neutral_fill(color):
            continue
        result.append(
            {
                "bbox": rect_bbox,
                "fill_present": True,
                "raw_non_stroking_color": color,
            }
        )
        if len(result) > limits.max_fills_per_table:
            raise PdfVisualError("pdf_table_fill_limit_exceeded")
    return sorted(
        result,
        key=lambda item: (
            *_bbox_sort_key(item["bbox"]),
            canonical_json(item["raw_non_stroking_color"]),
        ),
    )


def _read_table_matrix(
    table: Any, *, limits: PdfVisualLimits
) -> tuple[list[Sequence[Any]], int, int]:
    try:
        raw_matrix = table.extract()
    except Exception:
        raise PdfVisualError("pdf_table_extraction_failed") from None
    if not isinstance(raw_matrix, list) or not raw_matrix:
        raise PdfVisualError("pdf_table_matrix_invalid")
    if len(raw_matrix) > limits.max_table_rows:
        raise PdfVisualError("pdf_table_row_limit_exceeded")

    columns = 0
    for raw_row in raw_matrix:
        if not isinstance(raw_row, Sequence) or isinstance(raw_row, (str, bytes)):
            raise PdfVisualError("pdf_table_matrix_invalid")
        columns = max(columns, len(raw_row))
        if columns > limits.max_table_cols:
            raise PdfVisualError("pdf_table_column_limit_exceeded")
    if columns < 1:
        raise PdfVisualError("pdf_table_matrix_invalid")
    if len(raw_matrix) * columns > limits.max_table_cells:
        raise PdfVisualError("pdf_table_cell_limit_exceeded")

    raw_cells = getattr(table, "cells", None)
    if raw_cells is not None:
        if not isinstance(raw_cells, Sequence) or isinstance(raw_cells, (str, bytes)):
            raise PdfVisualError("pdf_table_cells_invalid")
        if len(raw_cells) > limits.max_table_cells:
            raise PdfVisualError("pdf_table_cell_limit_exceeded")
    return raw_matrix, len(raw_matrix), columns


def _normalize_table_matrix(
    raw_matrix: Sequence[Sequence[Any]],
    *,
    columns: int,
    limits: PdfVisualLimits,
    budget: _TextBudget,
) -> list[list[str | None]]:
    rows: list[list[str | None]] = []
    for raw_row in raw_matrix:
        row: list[str | None] = []
        for raw_cell in raw_row:
            if raw_cell is None:
                row.append(None)
                continue
            text = _normalize_text(
                raw_cell,
                error_code="pdf_table_cell_text_limit_exceeded",
                max_chars=limits.max_cell_chars,
            )
            budget.consume(text)
            row.append(text)
        rows.append(row)
    for row in rows:
        row.extend([None] * (columns - len(row)))
    return rows


def _table_matrix(
    table: Any, *, limits: PdfVisualLimits, budget: _TextBudget
) -> tuple[list[list[str | None]], int, int]:
    raw_matrix, rows, columns = _read_table_matrix(table, limits=limits)
    normalized = _normalize_table_matrix(
        raw_matrix,
        columns=columns,
        limits=limits,
        budget=budget,
    )
    return normalized, rows, columns


def _is_obvious_page_frame(
    *,
    table_bbox: Mapping[str, float],
    page_bbox: Mapping[str, float],
    rows: int,
    columns: int,
    raw_matrix: Sequence[Sequence[Any]],
    page_words: Sequence[PdfWordEvidence],
    geometry_budget: _GeometryBudget,
) -> bool:
    """Reject only empty, very large, very low-dimensional page frames."""

    if rows > 2 or columns > 2:
        return False
    if any(
        value is not None and (not isinstance(value, str) or value.strip())
        for row in raw_matrix
        for value in row
    ):
        return False
    width_ratio = table_bbox["w"] / page_bbox["w"]
    height_ratio = table_bbox["h"] / page_bbox["h"]
    spans_page = (
        width_ratio >= _OBVIOUS_FRAME_MIN_WIDTH_RATIO
        and height_ratio >= _OBVIOUS_FRAME_MIN_HEIGHT_RATIO
    )
    if not spans_page:
        return False
    geometry_budget.consume(len(page_words))
    return not any(_word_is_inside(word, table_bbox) for word in page_words)


def _period_number(value: str | None) -> tuple[str, int] | None:
    if not isinstance(value, str):
        return None
    compact = re.sub(r"\s+", "", value).upper()
    match = _PERIOD_HEADER_PATTERN.fullmatch(compact)
    if match is None:
        return None
    suffix = match.group(1)
    return compact, 0 if suffix is None else int(suffix)


def _table_row_cells(
    table: Any, *, limits: PdfVisualLimits
) -> tuple[tuple[dict[str, float] | None, ...], ...]:
    try:
        raw_rows = getattr(table, "rows")
    except AttributeError:
        raise PdfVisualError("pdf_table_rows_unavailable") from None
    except Exception:
        raise PdfVisualError("pdf_table_rows_invalid") from None
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
        raise PdfVisualError("pdf_table_rows_invalid")
    if len(raw_rows) > limits.max_table_rows:
        raise PdfVisualError("pdf_table_row_limit_exceeded")

    result: list[tuple[dict[str, float] | None, ...]] = []
    cell_count = 0
    for raw_row in raw_rows:
        try:
            raw_cells = getattr(raw_row, "cells")
        except AttributeError:
            raise PdfVisualError("pdf_table_row_cells_unavailable") from None
        except Exception:
            raise PdfVisualError("pdf_table_row_cells_invalid") from None
        if not isinstance(raw_cells, Sequence) or isinstance(
            raw_cells, (str, bytes)
        ):
            raise PdfVisualError("pdf_table_row_cells_invalid")
        normalized: list[dict[str, float] | None] = []
        for raw_cell in raw_cells:
            cell_count += 1
            if cell_count > limits.max_table_cells:
                raise PdfVisualError("pdf_table_cell_limit_exceeded")
            if raw_cell is None:
                normalized.append(None)
            else:
                normalized.append(_bbox(raw_cell, "pdf_table_cell_bbox_invalid"))
        result.append(tuple(normalized))
    return tuple(result)


def _word_is_inside(
    word: PdfWordEvidence, outer: Mapping[str, float], *, tolerance: float = 0.01
) -> bool:
    word_bbox = _bbox_from_tuple(word.bbox)
    center_x, center_y = _bbox_center(word_bbox)
    return (
        outer["x"] - tolerance
        <= center_x
        <= outer["x"] + outer["w"] + tolerance
        and outer["y"] - tolerance
        <= center_y
        <= outer["y"] + outer["h"] + tolerance
    )


def _combine_word_bbox(
    words: Sequence[PdfWordEvidence], *, fallback: Mapping[str, float]
) -> tuple[float, float, float, float]:
    if not words:
        return _bbox_tuple(fallback)
    boxes = [_bbox_from_tuple(word.bbox) for word in words]
    left = min(item["x"] for item in boxes)
    top = min(item["y"] for item in boxes)
    right = max(item["x"] + item["w"] for item in boxes)
    bottom = max(item["y"] + item["h"] for item in boxes)
    return (left, top, right - left, bottom - top)


def _words_to_text(words: Sequence[PdfWordEvidence]) -> str:
    if not words:
        return ""
    ordered = sorted(
        words,
        key=lambda item: (
            item.bbox[1] + item.bbox[3] / 2,
            item.bbox[0],
            item.text,
        ),
    )
    lines: list[list[PdfWordEvidence]] = []
    line_centers: list[float] = []
    line_heights: list[float] = []
    for word in ordered:
        center_y = word.bbox[1] + word.bbox[3] / 2
        if lines:
            tolerance = max(2.0, min(word.bbox[3], line_heights[-1]) * 0.45)
            if abs(center_y - line_centers[-1]) <= tolerance:
                lines[-1].append(word)
                count = len(lines[-1])
                line_centers[-1] = (
                    line_centers[-1] * (count - 1) + center_y
                ) / count
                line_heights[-1] = max(line_heights[-1], word.bbox[3])
                continue
        lines.append([word])
        line_centers.append(center_y)
        line_heights.append(word.bbox[3])

    line_texts = [
        " ".join(item.text for item in sorted(line, key=lambda item: item.bbox[0]))
        for line in lines
    ]
    return " ".join(part for part in line_texts if part)


def _contains_milestone(value: Any) -> bool:
    return isinstance(value, str) and any(
        marker in value for marker in _MILESTONE_MARKERS
    )


def _horizontal_label_left(
    page_lines: Any,
    *,
    table_bbox: Mapping[str, float],
    first_period_x: float,
    row_boundary_ys: Sequence[float],
    geometry_budget: _GeometryBudget,
) -> float:
    """Find an extension supported by two aligned, distinct row boundaries."""

    if not isinstance(page_lines, Sequence) or isinstance(page_lines, (str, bytes)):
        raise PdfVisualError("pdf_lines_invalid")
    geometry_budget.consume(len(page_lines) * max(1, len(row_boundary_ys)))
    table_right = table_bbox["x"] + table_bbox["w"]
    table_bottom = table_bbox["y"] + table_bbox["h"]
    candidates: list[tuple[float, int]] = []
    for raw in page_lines:
        if not isinstance(raw, Mapping):
            raise PdfVisualError("pdf_line_invalid")
        x0 = _number(raw.get("x0"), "pdf_line_bbox_invalid")
        x1 = _number(raw.get("x1"), "pdf_line_bbox_invalid")
        top = _number(raw.get("top"), "pdf_line_bbox_invalid")
        bottom = _number(raw.get("bottom"), "pdf_line_bbox_invalid")
        orientation = raw.get("orientation")
        if orientation != "h" and abs(bottom - top) > 0.5:
            continue
        y = (top + bottom) / 2
        if not table_bbox["y"] - 3 <= y <= table_bottom + 3:
            continue
        if not row_boundary_ys:
            continue
        boundary_index = min(
            range(len(row_boundary_ys)),
            key=lambda index: abs(row_boundary_ys[index] - y),
        )
        if abs(row_boundary_ys[boundary_index] - y) > _ROW_BOUNDARY_Y_TOLERANCE:
            continue
        line_left = min(x0, x1)
        line_right = max(x0, x1)
        if (
            line_left < first_period_x - 1
            and line_right >= table_right - 3
        ):
            candidates.append((line_left, boundary_index))

    supported_lefts: list[float] = []
    geometry_budget.consume(len(candidates) * len(candidates))
    for anchor_left, _ in candidates:
        cluster = [
            candidate
            for candidate in candidates
            if abs(candidate[0] - anchor_left) <= _ROW_BOUNDARY_LEFT_TOLERANCE
        ]
        if len({boundary_index for _, boundary_index in cluster}) >= (
            _MIN_EXTERNAL_ROW_BOUNDARIES
        ):
            supported_lefts.append(min(line_left for line_left, _ in cluster))
    return min(supported_lefts, default=table_bbox["x"])


def _schedule_geometry_analysis(
    *,
    page: int,
    table_ordinal: int,
    table: Any,
    table_bbox: Mapping[str, float],
    matrix: Sequence[Sequence[str | None]],
    page_words: Sequence[PdfWordEvidence],
    fill_evidence: Sequence[Mapping[str, Any]],
    page_lines: Any,
    limits: PdfVisualLimits,
    geometry_budget: _GeometryBudget,
) -> PdfTableGeometryAnalysis:
    geometry_budget.consume(len(page_words))
    inside_words = tuple(
        word for word in page_words if _word_is_inside(word, table_bbox)
    )
    mutable_matrix = [list(row) for row in matrix]
    row_cells = _table_row_cells(table, limits=limits)
    base_provenance = [
        "pdfplumber.Table.extract",
        f"pdfplumber.find_tables.settings_sha256:{LINES_TABLE_SETTINGS_SHA256}",
    ]
    base_reasons: list[str] = []
    recovered_positions: set[tuple[int, int]] = set()
    recovered_texts: list[str] = []
    if inside_words:
        base_provenance.append("pdfplumber.Page.extract_words")

    if (
        mutable_matrix
        and row_cells
        and len(row_cells) == len(mutable_matrix)
        and all(
            len(cells) == len(mutable_matrix[row_index])
            for row_index, cells in enumerate(row_cells)
        )
    ):
        for row_index, cells in enumerate(row_cells):
            for column, cell_bbox in enumerate(cells):
                existing = mutable_matrix[row_index][column]
                if cell_bbox is None or (
                    isinstance(existing, str) and existing.strip()
                ):
                    continue
                geometry_budget.consume(len(inside_words))
                cell_words = tuple(
                    word for word in inside_words if _word_is_inside(word, cell_bbox)
                )
                recovered_text = _words_to_text(cell_words)
                if not recovered_text:
                    continue
                if len(recovered_text) > limits.max_cell_chars:
                    raise PdfVisualError("pdf_table_cell_text_limit_exceeded")
                mutable_matrix[row_index][column] = recovered_text
                recovered_positions.add((row_index, column))
                recovered_texts.append(recovered_text)
        if recovered_texts:
            base_reasons.append("cell_text_recovered_from_word_bboxes")

    if (
        not mutable_matrix
        or not row_cells
        or len(row_cells) != len(mutable_matrix)
        or len(row_cells[0]) != len(mutable_matrix[0])
    ):
        return PdfTableGeometryAnalysis(
            page=page,
            table_ordinal=table_ordinal,
            bbox=_bbox_tuple(table_bbox),
            matrix=tuple(tuple(row) for row in mutable_matrix),
            inside_words=inside_words,
            schedule_rows=(),
            recovered_cell_texts=tuple(recovered_texts),
            confidence=0.55 if recovered_texts else 0.0,
            provenance=tuple(base_provenance),
            reasons=tuple([*base_reasons, "schedule_geometry_unavailable"]),
        )

    geometry_budget.consume(len(mutable_matrix[0]))
    periods: list[tuple[int, str, int, dict[str, float]]] = []
    for column, (text, cell_bbox) in enumerate(
        zip(mutable_matrix[0], row_cells[0], strict=True)
    ):
        parsed = _period_number(text)
        if parsed is None or cell_bbox is None:
            continue
        label, number = parsed
        periods.append((column, label, number, cell_bbox))
    if len(periods) < _MIN_PERIOD_HEADER_COUNT:
        return PdfTableGeometryAnalysis(
            page=page,
            table_ordinal=table_ordinal,
            bbox=_bbox_tuple(table_bbox),
            matrix=tuple(tuple(row) for row in mutable_matrix),
            inside_words=inside_words,
            schedule_rows=(),
            recovered_cell_texts=tuple(recovered_texts),
            confidence=0.55 if recovered_texts else 0.0,
            provenance=tuple(base_provenance),
            reasons=tuple([*base_reasons, "temporal_header_absent"]),
        )

    period_numbers = [item[2] for item in periods]
    if period_numbers[0] != 0 or period_numbers != list(range(len(periods))):
        return PdfTableGeometryAnalysis(
            page=page,
            table_ordinal=table_ordinal,
            bbox=_bbox_tuple(table_bbox),
            matrix=tuple(tuple(row) for row in mutable_matrix),
            inside_words=inside_words,
            schedule_rows=(),
            recovered_cell_texts=tuple(recovered_texts),
            confidence=0.55 if recovered_texts else 0.0,
            provenance=tuple(base_provenance),
            reasons=tuple([*base_reasons, "temporal_header_ambiguous"]),
        )

    first_period_column, _, _, first_period_bbox = periods[0]
    concrete_row_cells = [
        cell for cells in row_cells for cell in cells if cell is not None
    ]
    geometry_budget.consume(len(concrete_row_cells))
    raw_boundary_ys = sorted(
        boundary
        for cell in concrete_row_cells
        for boundary in (cell["y"], cell["y"] + cell["h"])
    )
    row_boundary_ys: list[float] = []
    for boundary in raw_boundary_ys:
        if (
            not row_boundary_ys
            or boundary - row_boundary_ys[-1] > _DISTINCT_ROW_BOUNDARY_TOLERANCE
        ):
            row_boundary_ys.append(boundary)
    label_left = _horizontal_label_left(
        page_lines,
        table_bbox=table_bbox,
        first_period_x=first_period_bbox["x"],
        row_boundary_ys=row_boundary_ys,
        geometry_budget=geometry_budget,
    )
    geometry_budget.consume(first_period_column)
    label_candidates = [
        (column, cell_bbox)
        for column, cell_bbox in enumerate(row_cells[0][:first_period_column])
        if cell_bbox is not None
        and cell_bbox["x"] + cell_bbox["w"] <= first_period_bbox["x"] + 0.01
    ]
    label_column: int | None
    if label_candidates:
        label_column, _ = max(label_candidates, key=lambda item: item[1]["w"])
    elif first_period_column == 0 and label_left < first_period_bbox["x"] - 1:
        # Some schedules have horizontal row rules across the label region but
        # no left vertical cell.  pdfplumber then starts the table at M while
        # the row labels live immediately to its left.  Such labels are valid
        # analysis evidence but never belong in the persisted M column.
        label_column = None
        base_reasons.append("external_row_labels_analysis_only")
    else:
        return PdfTableGeometryAnalysis(
            page=page,
            table_ordinal=table_ordinal,
            bbox=_bbox_tuple(table_bbox),
            matrix=tuple(tuple(row) for row in mutable_matrix),
            inside_words=inside_words,
            schedule_rows=(),
            recovered_cell_texts=tuple(recovered_texts),
            confidence=0.55 if recovered_texts else 0.0,
            provenance=tuple(base_provenance),
            reasons=tuple(
                [*base_reasons, "schedule_label_region_unavailable"]
            ),
        )
    label_x_limit = first_period_bbox["x"]
    if label_left < table_bbox["x"] - 0.01:
        base_provenance.append("pdfplumber.Page.lines")
    schedule_bbox = {
        "x": label_left,
        "y": table_bbox["y"],
        "w": table_bbox["x"] + table_bbox["w"] - label_left,
        "h": table_bbox["h"],
    }
    geometry_budget.consume(len(page_words))
    inside_words = tuple(
        word for word in page_words if _word_is_inside(word, schedule_bbox)
    )
    if inside_words and "pdfplumber.Page.extract_words" not in base_provenance:
        base_provenance.append("pdfplumber.Page.extract_words")

    schedule_rows: list[PdfScheduleRowEvidence] = []
    recovered_count = 0
    fact_count = 0
    fill_fact_count = 0
    marker_fact_count = 0
    for row_index, cells in enumerate(row_cells[1:], start=1):
        concrete_cells = [cell for cell in cells if cell is not None]
        if not concrete_cells or row_index >= len(mutable_matrix):
            continue
        row_top = min(cell["y"] for cell in concrete_cells)
        row_bottom = max(cell["y"] + cell["h"] for cell in concrete_cells)
        row_bbox = {
            "x": label_left,
            "y": row_top,
            "w": label_x_limit - label_left,
            "h": row_bottom - row_top,
        }
        if row_bbox["w"] <= 0 or row_bbox["h"] <= 0:
            continue

        geometry_budget.consume(len(inside_words))
        label_words = tuple(
            word for word in inside_words if _word_is_inside(word, row_bbox)
        )
        geometry_label = _words_to_text(label_words)
        recovered = False
        if label_column is None:
            label = geometry_label
        else:
            existing_label = mutable_matrix[row_index][label_column]
            recovered = (row_index, label_column) in recovered_positions
            if not isinstance(existing_label, str) or not existing_label.strip():
                if geometry_label:
                    if len(geometry_label) > limits.max_cell_chars:
                        raise PdfVisualError("pdf_table_cell_text_limit_exceeded")
                    mutable_matrix[row_index][label_column] = geometry_label
                    existing_label = geometry_label
                    recovered = True
                    recovered_positions.add((row_index, label_column))
                    recovered_texts.append(geometry_label)
                    if "cell_text_recovered_from_word_bboxes" not in base_reasons:
                        base_reasons.append("cell_text_recovered_from_word_bboxes")
            label = (
                existing_label.strip() if isinstance(existing_label, str) else ""
            )
        if not label:
            continue
        if recovered:
            recovered_count += 1
        label_geometry_matches = bool(label_words) and geometry_label == label
        label_conflict = bool(geometry_label) and geometry_label != label
        fallback_label_bbox = row_bbox
        if (
            label_column is not None
            and label_column < len(cells)
            and cells[label_column] is not None
        ):
            fallback_label_bbox = cells[label_column]
        label_bbox = (
            _combine_word_bbox(label_words, fallback=fallback_label_bbox)
            if label_geometry_matches
            else _bbox_tuple(fallback_label_bbox)
        )
        if label_conflict and "matrix_geometry_label_conflict" not in base_reasons:
            base_reasons.append("matrix_geometry_label_conflict")

        active_periods: list[str] = []
        milestone_periods: list[str] = []
        for period_column, period_label, _, period_bbox in periods:
            period_row_bbox = {
                "x": period_bbox["x"],
                "y": row_top,
                "w": period_bbox["w"],
                "h": row_bottom - row_top,
            }
            period_area = period_row_bbox["w"] * period_row_bbox["h"]
            geometry_budget.consume(len(fill_evidence))
            clipped_fills: list[dict[str, float]] = []
            for fill in fill_evidence:
                fill_bbox = fill.get("bbox")
                if not isinstance(fill_bbox, Mapping):
                    continue
                _, center_y = _bbox_center(fill_bbox)
                if not row_top + 0.01 < center_y < row_bottom - 0.01:
                    continue
                clipped = _clipped_bbox(fill_bbox, period_row_bbox)
                if clipped is not None:
                    clipped_fills.append(clipped)
            covered_area = _rectangle_union_area(
                clipped_fills,
                budget=geometry_budget,
            )
            if period_area > 0 and covered_area / period_area >= _MIN_PERIOD_FILL_COVERAGE:
                active_periods.append(period_label)
                fill_fact_count += 1

            geometry_budget.consume(len(inside_words))
            word_marker_found = any(
                _contains_milestone(word.text)
                and _word_is_inside(word, period_row_bbox)
                for word in inside_words
            )
            matrix_marker_found = (
                period_column < len(mutable_matrix[row_index])
                and _contains_milestone(mutable_matrix[row_index][period_column])
            )
            marker_found = word_marker_found or matrix_marker_found
            if marker_found:
                milestone_periods.append(period_label)
                marker_fact_count += 1

        if len(active_periods) == len(periods):
            role = "full_span"
        elif active_periods:
            role = "activity"
        elif milestone_periods:
            role = "milestone"
        else:
            role = "label_only"
        if active_periods or milestone_periods:
            fact_count += 1
        row_confidence = 0.75
        if label_geometry_matches:
            row_confidence += 0.10
        elif label_conflict:
            row_confidence -= 0.10
        if active_periods or milestone_periods:
            row_confidence += 0.10
        schedule_rows.append(
            PdfScheduleRowEvidence(
                row_index=row_index,
                label=label,
                label_bbox=label_bbox,
                active_periods=tuple(active_periods),
                milestone_periods=tuple(milestone_periods),
                role=role,
                confidence=min(0.95, row_confidence),
                recovered_matrix_cell=recovered,
            )
        )

    reasons = [*base_reasons, "temporal_header_sequence"]
    provenance = [
        *base_provenance,
        "pdfplumber.Table.rows",
        SCHEDULE_GEOMETRY_METHOD,
    ]
    confidence = 0.65
    if recovered_count:
        reasons.append("row_labels_recovered_from_word_bboxes")
        confidence += 0.15
    if fill_fact_count:
        reasons.append("period_fills_mapped_from_filtered_rectangles")
        provenance.append("pdfplumber.Page.rects")
    if marker_fact_count:
        reasons.append("period_milestones_mapped_from_words_or_cells")
    if fact_count:
        confidence += 0.10
    if not schedule_rows:
        reasons.append("schedule_rows_unresolved")
        confidence = min(confidence, 0.40)
    return PdfTableGeometryAnalysis(
        page=page,
        table_ordinal=table_ordinal,
        bbox=_bbox_tuple(table_bbox),
        matrix=tuple(tuple(row) for row in mutable_matrix),
        inside_words=inside_words,
        schedule_rows=tuple(schedule_rows),
        recovered_cell_texts=tuple(recovered_texts),
        confidence=min(0.95, confidence),
        provenance=tuple(dict.fromkeys(provenance)),
        reasons=tuple(reasons),
    )


def _record(
    *,
    doc_id: str,
    source_sha256: str,
    page: int,
    sequence_in_page: int,
    node_type: str,
    bbox: Mapping[str, float],
    page_bbox: Mapping[str, float],
    preceding_text: Mapping[str, Any] | None,
    content: Mapping[str, Any],
) -> dict[str, Any]:
    content_sha256 = sha256_text(canonical_json(content))
    status = (
        "line_table_candidate"
        if node_type == "table"
        else "image_geometry_candidate"
    )
    record_seed = canonical_json(
        {
            "schema_version": PDF_VISUAL_SCHEMA_VERSION,
            "doc_id": doc_id,
            "source_sha256": source_sha256,
            "page": page,
            "sequence_in_page": sequence_in_page,
            "node_type": node_type,
            "status": status,
            "bbox": dict(bbox),
            "page_bbox": dict(page_bbox),
            "coordinate_space": COORDINATE_SPACE,
            "method": EXTRACTION_METHOD,
            "table_settings_sha256": LINES_TABLE_SETTINGS_SHA256,
            "preceding_text": (
                dict(preceding_text) if preceding_text is not None else None
            ),
            "content_sha256": content_sha256,
        }
    )
    return {
        "schema_version": PDF_VISUAL_SCHEMA_VERSION,
        "record_id": f"pdfvis_{sha256_text(record_seed)[:24]}",
        "doc_id": doc_id,
        "page": page,
        "sequence_in_page": sequence_in_page,
        "node_type": node_type,
        "status": status,
        "bbox": dict(bbox),
        "page_bbox": dict(page_bbox),
        "coordinate_space": COORDINATE_SPACE,
        "method": EXTRACTION_METHOD,
        "source_sha256": source_sha256,
        "content_sha256": content_sha256,
        "preceding_text": dict(preceding_text) if preceding_text is not None else None,
        "content": dict(content),
    }


def _extract_page(
    page_object: Any,
    *,
    doc_id: str,
    source_sha256: str,
    page_number: int,
    limits: PdfVisualLimits,
    budget: _TextBudget,
    document_budget: _DocumentVisualBudget,
    analysis_output: list[PdfTableGeometryAnalysis] | None,
) -> list[dict[str, Any]]:
    if _page_object_count(page_object) > limits.max_page_objects:
        raise PdfVisualError("pdf_page_objects_limit_exceeded")
    page_bbox = _bbox(getattr(page_object, "bbox", None), "pdf_page_bbox_invalid")
    geometry_budget = _GeometryBudget(limits.max_geometry_comparisons)
    budget.start_page()
    page_words = _page_words(
        page_object,
        page_bbox=page_bbox,
        limits=limits,
        budget=budget,
    )

    finder = getattr(page_object, "find_tables", None)
    if not callable(finder):
        raise PdfVisualError("pdf_table_finder_unavailable")
    try:
        finder_result = finder(table_settings=dict(LINES_TABLE_SETTINGS))
    except Exception:
        raise PdfVisualError("pdf_table_detection_failed") from None
    # pdfplumber 0.11 returns TableFinder; accepting a direct sequence keeps
    # deterministic fakes and minor compatible adapters straightforward.
    raw_tables = getattr(finder_result, "tables", finder_result)
    if not isinstance(raw_tables, Sequence) or isinstance(raw_tables, (str, bytes)):
        raise PdfVisualError("pdf_tables_invalid")
    if len(raw_tables) > limits.max_tables_per_page:
        raise PdfVisualError("pdf_table_count_limit_exceeded")

    tables: list[dict[str, Any]] = []
    for ordinal, table in enumerate(raw_tables):
        table_bbox = _bbox(getattr(table, "bbox", None), "pdf_table_bbox_invalid")
        if not _contains(page_bbox, table_bbox):
            raise PdfVisualError("pdf_table_bbox_outside_page")
        raw_matrix, matrix_rows, matrix_columns = _read_table_matrix(
            table, limits=limits
        )
        if _is_obvious_page_frame(
            table_bbox=table_bbox,
            page_bbox=page_bbox,
            rows=matrix_rows,
            columns=matrix_columns,
            raw_matrix=raw_matrix,
            page_words=page_words,
            geometry_budget=geometry_budget,
        ):
            continue
        tables.append(
            {
                "ordinal": ordinal,
                "object": table,
                "bbox": table_bbox,
                "raw_matrix": raw_matrix,
                "rows": matrix_rows,
                "columns": matrix_columns,
            }
        )

    try:
        raw_images = getattr(page_object, "images", [])
    except Exception:
        raise PdfVisualError("pdf_images_invalid") from None
    if not isinstance(raw_images, Sequence) or isinstance(raw_images, (str, bytes)):
        raise PdfVisualError("pdf_images_invalid")
    if len(raw_images) > limits.max_images_per_page:
        raise PdfVisualError("pdf_image_count_limit_exceeded")
    images: list[dict[str, Any]] = []
    for ordinal, image in enumerate(raw_images):
        if not isinstance(image, Mapping):
            raise PdfVisualError("pdf_image_invalid")
        image_bbox = _bbox(image, "pdf_image_bbox_invalid")
        if not _contains(page_bbox, image_bbox):
            raise PdfVisualError("pdf_image_bbox_outside_page")
        images.append(
            {
                "ordinal": ordinal,
                "object": image,
                "bbox": image_bbox,
            }
        )

    text_lines = _text_lines(
        page_object,
        table_bboxes=[item["bbox"] for item in tables],
        limits=limits,
        budget=budget,
        geometry_budget=geometry_budget,
    )
    try:
        rects = getattr(page_object, "rects", [])
    except Exception:
        raise PdfVisualError("pdf_rects_invalid") from None
    if not isinstance(rects, Sequence) or isinstance(rects, (str, bytes)):
        raise PdfVisualError("pdf_rects_invalid")
    try:
        page_lines = getattr(page_object, "lines")
    except AttributeError:
        raise PdfVisualError("pdf_lines_unavailable") from None
    except Exception:
        raise PdfVisualError("pdf_lines_invalid") from None
    if not isinstance(page_lines, Sequence) or isinstance(page_lines, (str, bytes)):
        raise PdfVisualError("pdf_lines_invalid")
    visual_nodes = [
        *({"node_type": "table", **item} for item in tables),
        *({"node_type": "image", **item} for item in images),
    ]
    priority = {"table": 0, "image": 1}
    visual_nodes.sort(
        key=lambda item: (
            *_bbox_sort_key(item["bbox"]),
            priority[item["node_type"]],
            item["ordinal"],
        )
    )

    records: list[dict[str, Any]] = []
    for sequence_in_page, node in enumerate(visual_nodes):
        document_budget.consume_record()
        preceding = _preceding_text(
            text_lines,
            node["bbox"],
            max_chars=limits.max_context_chars,
            geometry_budget=geometry_budget,
        )
        if node["node_type"] == "table":
            document_budget.consume_analysis()
            matrix = _normalize_table_matrix(
                node["raw_matrix"],
                columns=node["columns"],
                limits=limits,
                budget=budget,
            )
            rows = node["rows"]
            columns = node["columns"]
            fill_evidence = _direct_fill_evidence(
                rects,
                table_bbox=node["bbox"],
                limits=limits,
                geometry_budget=geometry_budget,
            )
            analysis = _schedule_geometry_analysis(
                page=page_number,
                table_ordinal=node["ordinal"],
                table=node["object"],
                table_bbox=node["bbox"],
                matrix=matrix,
                page_words=page_words,
                fill_evidence=fill_evidence,
                page_lines=page_lines,
                limits=limits,
                geometry_budget=geometry_budget,
            )
            for recovered_text in analysis.recovered_cell_texts:
                budget.consume(recovered_text)
            matrix = [list(row) for row in analysis.matrix]
            if analysis_output is not None:
                analysis_output.append(analysis)
            content: dict[str, Any] = {
                "kind": "table_cell_matrix",
                "rows": rows,
                "cols": columns,
                "cell_count": rows * columns,
                "matrix": matrix,
                "matrix_sha256": sha256_text(canonical_json(matrix)),
                "direct_fill_evidence": fill_evidence,
            }
        else:
            signature = {
                "bbox": node["bbox"],
                "page": page_number,
                "ordinal_on_page": node["ordinal"],
            }
            content = {
                "kind": "image_geometry",
                "image_signature_sha256": sha256_text(canonical_json(signature)),
            }
        records.append(
            _record(
                doc_id=doc_id,
                source_sha256=source_sha256,
                page=page_number,
                sequence_in_page=sequence_in_page,
                node_type=node["node_type"],
                bbox=node["bbox"],
                page_bbox=page_bbox,
                preceding_text=preceding,
                content=content,
            )
        )
    return records


def extract_pdf_visual_evidence(
    *,
    source_path: Path,
    doc_id: str,
    expected_sha256: str | None = None,
    limits: PdfVisualLimits | None = None,
    analysis_sink: list[PdfTableGeometryAnalysis] | None = None,
) -> list[dict[str, Any]]:
    """Extract bounded local PDF table/image candidates without OCR or semantics.

    ``lines`` detections are deliberately reported as candidates. A returned
    count is therefore a candidate count, not a verified table/image aggregate.

    Errors intentionally use stable codes only: neither source paths nor parsed
    private text are interpolated into exception messages.

    ``analysis_sink`` is an explicit, in-memory opt-in for native word bboxes,
    reconstructed schedule rows, confidence and provenance.  Only an exact
    built-in ``list`` is accepted so publication cannot dispatch user-defined
    mutation hooks.  It is populated only after every source check succeeds;
    the persisted schema-v1 record remains backward compatible.
    """

    if not isinstance(source_path, Path):
        raise PdfVisualError("pdf_path_invalid")
    if not isinstance(doc_id, str) or not _DOC_ID_PATTERN.fullmatch(doc_id):
        raise PdfVisualError("pdf_doc_id_invalid")
    if expected_sha256 is not None:
        try:
            expected_sha256 = require_sha256(
                expected_sha256, "pdf_expected_sha256_invalid"
            )
        except ValueError:
            raise PdfVisualError("pdf_expected_sha256_invalid") from None
    selected_limits = limits or PdfVisualLimits()
    if not isinstance(selected_limits, PdfVisualLimits):
        raise PdfVisualError("pdf_visual_limits_invalid")
    selected_limits.validate()
    if analysis_sink is not None and type(analysis_sink) is not list:
        raise PdfVisualError("pdf_analysis_sink_invalid")

    try:
        initial_stat = source_path.lstat()
    except OSError:
        raise PdfVisualError("pdf_path_unreadable") from None
    if stat.S_ISLNK(initial_stat.st_mode):
        raise PdfVisualError("pdf_path_symlink_forbidden")
    if not stat.S_ISREG(initial_stat.st_mode):
        raise PdfVisualError("pdf_path_not_regular")
    if initial_stat.st_size > selected_limits.max_file_bytes:
        raise PdfVisualError("pdf_file_size_limit_exceeded")
    initial_signature = _source_stat_signature(initial_stat)

    descriptor: int | None = None
    source: BinaryIO | None = None
    snapshot: BinaryIO | None = None
    pdf: Any = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(source_path, flags)
        opened_stat = os.fstat(descriptor)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise PdfVisualError("pdf_path_not_regular")
        if opened_stat.st_size > selected_limits.max_file_bytes:
            raise PdfVisualError("pdf_file_size_limit_exceeded")
        opened_signature = _source_stat_signature(opened_stat)
        if opened_signature != initial_signature:
            raise PdfVisualError("pdf_source_changed")
        source = os.fdopen(descriptor, "rb")
        descriptor = None
        snapshot = _bounded_source_snapshot(
            source,
            max_bytes=selected_limits.max_file_bytes,
        )
        try:
            copied_stat = os.fstat(source.fileno())
        except OSError:
            raise PdfVisualError("pdf_source_changed") from None
        if _source_stat_signature(copied_stat) != opened_signature:
            raise PdfVisualError("pdf_source_changed")

        source_sha256 = _sha256_stream(snapshot)
        if expected_sha256 is not None and source_sha256 != expected_sha256:
            raise PdfVisualError("pdf_source_checksum_mismatch")

        pdf = _open_pdf(snapshot)
        try:
            pages = getattr(pdf, "pages", None)
            if not isinstance(pages, Sequence) or isinstance(pages, (str, bytes)):
                raise PdfVisualError("pdf_pages_invalid")
            if len(pages) > selected_limits.max_pages:
                raise PdfVisualError("pdf_page_limit_exceeded")
            budget = _TextBudget(selected_limits)
            document_budget = _DocumentVisualBudget(selected_limits)
            records: list[dict[str, Any]] = []
            collected_analyses: list[PdfTableGeometryAnalysis] | None = (
                [] if analysis_sink is not None else None
            )
            for page_index, page_object in enumerate(pages):
                records.extend(
                    _extract_page(
                        page_object,
                        doc_id=doc_id,
                        source_sha256=source_sha256,
                        page_number=page_index + 1,
                        limits=selected_limits,
                        budget=budget,
                        document_budget=document_budget,
                        analysis_output=collected_analyses,
                    )
                )
        except PdfVisualError:
            raise
        except Exception:
            raise PdfVisualError("pdf_parse_failed") from None

        post_sha256 = _sha256_stream(snapshot)
        try:
            final_stat = source_path.lstat()
            opened_final_stat = os.fstat(source.fileno())
        except OSError:
            raise PdfVisualError("pdf_source_changed") from None
        if (
            stat.S_ISLNK(final_stat.st_mode)
            or not stat.S_ISREG(final_stat.st_mode)
            or _source_stat_signature(final_stat) != opened_signature
            or _source_stat_signature(opened_final_stat) != opened_signature
            or post_sha256 != source_sha256
            or (expected_sha256 is not None and post_sha256 != expected_sha256)
        ):
            raise PdfVisualError("pdf_source_changed")
        if analysis_sink is not None and collected_analyses is not None:
            try:
                analysis_sink.extend(collected_analyses)
            except Exception:
                raise PdfVisualError("pdf_analysis_sink_invalid") from None
        return records
    except PdfVisualError:
        raise
    except OSError:
        raise PdfVisualError("pdf_path_unreadable") from None
    except Exception:
        raise PdfVisualError("pdf_parse_failed") from None
    finally:
        if pdf is not None:
            close = getattr(pdf, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        if source is not None:
            try:
                source.close()
            except Exception:
                pass
        if snapshot is not None:
            try:
                snapshot.close()
            except Exception:
                pass
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


__all__ = [
    "COORDINATE_SPACE",
    "EXTRACTION_METHOD",
    "LINES_TABLE_SETTINGS",
    "LINES_TABLE_SETTINGS_SHA256",
    "PDF_VISUAL_SCHEMA_VERSION",
    "SCHEDULE_GEOMETRY_METHOD",
    "PdfScheduleRowEvidence",
    "PdfTableGeometryAnalysis",
    "PdfVisualError",
    "PdfVisualLimits",
    "PdfWordEvidence",
    "extract_pdf_visual_evidence",
]
