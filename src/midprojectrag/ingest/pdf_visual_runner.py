from __future__ import annotations

import hashlib
import io
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from midprojectrag.ingest.common import canonical_json, sha256_file, sha256_text
from midprojectrag.ingest.pdf_visual_v2 import (
    DEFAULT_PDF_VISUAL_V2_LIMITS,
    PdfVisualV2Limits,
    materialize_pdf_visual_v2_corpus,
)


PDF_VISUAL_RUNNER_VERSION = "1.0"
PDF_VISUAL_RENDER_POLICY = "pypdfium2-rgba-top-left-v1"
PDF_VISUAL_GEOMETRY_POLICY = "pdfplumber-ruled-tables-strict-v1"

_DOC_ID_RE = re.compile(r"^doc_[0-9a-f]{24}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ABSOLUTE_RUNNER_LIMITS = {
    "max_manifest_bytes": 256 * 1024 * 1024,
    "max_manifest_records": 100_000,
    "max_source_bytes_per_document": 2 * 1024 * 1024 * 1024,
    "max_total_source_bytes": 8 * 1024 * 1024 * 1024,
    "max_rendered_pixels_per_page": 250_000_000,
    "max_page_render_bytes": 1024 * 1024 * 1024,
    "max_drawing_objects_per_page": 100_000,
}


class PdfVisualRunnerError(ValueError):
    """Content-free, stable failure raised by the local PDF v2 runner."""


@dataclass(frozen=True, slots=True)
class PdfVisualRunnerLimits:
    max_manifest_bytes: int = 64 * 1024 * 1024
    max_manifest_records: int = 10_000
    max_source_bytes_per_document: int = 512 * 1024 * 1024
    max_total_source_bytes: int = 2 * 1024 * 1024 * 1024
    max_rendered_pixels_per_page: int = 100_000_000
    max_page_render_bytes: int = 512 * 1024 * 1024
    max_drawing_objects_per_page: int = 5_000

    def __post_init__(self) -> None:
        for name, maximum in _ABSOLUTE_RUNNER_LIMITS.items():
            value = getattr(self, name)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 1
                or value > maximum
            ):
                raise PdfVisualRunnerError("pdf_visual_runner_limits_invalid")


DEFAULT_PDF_VISUAL_RUNNER_LIMITS = PdfVisualRunnerLimits()


def _raise(code: str) -> None:
    raise PdfVisualRunnerError(code)


def _safe_existing_directory(path: Path, code: str) -> Path:
    if not isinstance(path, Path) or not path.is_absolute():
        _raise(code)
    try:
        if path.is_symlink() or not path.is_dir():
            _raise(code)
        return path.resolve(strict=True)
    except OSError:
        _raise(code)


def _safe_contained_file(path: Path, root: Path, code: str) -> Path:
    if not isinstance(path, Path) or not path.is_absolute():
        _raise(code)
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root) or path.is_symlink() or not resolved.is_file():
            _raise(code)
        current = root
        for part in resolved.relative_to(root).parts:
            current = current / part
            if current.is_symlink():
                _raise(code)
        return resolved
    except OSError:
        _raise(code)


def _read_manifest(
    path: Path,
    *,
    limits: PdfVisualRunnerLimits,
) -> tuple[bytes, list[dict[str, Any]]]:
    try:
        if path.stat().st_size > limits.max_manifest_bytes:
            _raise("pdf_visual_runner_manifest_limit_exceeded")
        payload = path.read_bytes()
        if len(payload) > limits.max_manifest_bytes:
            _raise("pdf_visual_runner_manifest_limit_exceeded")
        text = payload.decode("utf-8")
    except PdfVisualRunnerError:
        raise
    except (OSError, UnicodeError):
        _raise("pdf_visual_runner_manifest_invalid")
    rows: list[dict[str, Any]] = []
    try:
        for line in text.splitlines():
            if not line.strip():
                _raise("pdf_visual_runner_manifest_invalid")
            value = json.loads(line)
            if not isinstance(value, dict):
                _raise("pdf_visual_runner_manifest_invalid")
            rows.append(value)
            if len(rows) > limits.max_manifest_records:
                _raise("pdf_visual_runner_manifest_limit_exceeded")
    except PdfVisualRunnerError:
        raise
    except json.JSONDecodeError:
        _raise("pdf_visual_runner_manifest_invalid")
    if not rows:
        _raise("pdf_visual_runner_manifest_empty")
    return payload, rows


def _selected_pdf_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    limits: PdfVisualV2Limits,
) -> list[Mapping[str, Any]]:
    selected = [
        row
        for row in rows
        if row.get("extension") == ".pdf" and row.get("status") == "ok"
    ]
    if not selected:
        _raise("pdf_visual_runner_no_eligible_pdf")
    if len(selected) > limits.max_documents:
        _raise("pdf_visual_runner_document_limit_exceeded")
    return sorted(selected, key=lambda row: str(row.get("doc_id", "")))


def _source_path(entry: Mapping[str, Any], data_root: Path) -> Path:
    relpath = entry.get("source_relpath")
    if not isinstance(relpath, str) or not relpath or "\x00" in relpath:
        _raise("pdf_visual_runner_source_path_invalid")
    relative = Path(relpath)
    if relative.is_absolute() or ".." in relative.parts:
        _raise("pdf_visual_runner_source_outside_data_dir")
    return _safe_contained_file(
        data_root / relative,
        data_root,
        "pdf_visual_runner_source_outside_data_dir",
    )


def _read_verified_source(
    entry: Mapping[str, Any],
    *,
    data_root: Path,
    runner_limits: PdfVisualRunnerLimits,
) -> tuple[str, str, bytes]:
    doc_id = entry.get("doc_id")
    expected_sha256 = entry.get("sha256")
    if not isinstance(doc_id, str) or _DOC_ID_RE.fullmatch(doc_id) is None:
        _raise("pdf_visual_runner_doc_id_invalid")
    if (
        not isinstance(expected_sha256, str)
        or _SHA256_RE.fullmatch(expected_sha256) is None
    ):
        _raise("pdf_visual_runner_source_sha256_invalid")
    if entry.get("mime_type") not in (None, "application/pdf"):
        _raise("pdf_visual_runner_mime_invalid")
    source = _source_path(entry, data_root)
    try:
        size = source.stat().st_size
        if size < 5 or size > runner_limits.max_source_bytes_per_document:
            _raise("pdf_visual_runner_source_size_exceeded")
        payload = source.read_bytes()
    except PdfVisualRunnerError:
        raise
    except OSError:
        _raise("pdf_visual_runner_source_read_failed")
    if len(payload) != size or not payload.startswith(b"%PDF-"):
        _raise("pdf_visual_runner_source_invalid")
    expected_size = entry.get("size_bytes")
    if (
        expected_size is not None
        and (
            not isinstance(expected_size, int)
            or isinstance(expected_size, bool)
            or expected_size != len(payload)
        )
    ):
        _raise("pdf_visual_runner_source_size_mismatch")
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        _raise("pdf_visual_runner_source_hash_mismatch")
    return doc_id, expected_sha256, payload


def _dependency_versions() -> dict[str, str]:
    result: dict[str, str] = {}
    for distribution in ("pypdf", "pdfplumber", "pypdfium2", "Pillow"):
        try:
            result[distribution] = version(distribution)
        except PackageNotFoundError:
            _raise("pdf_visual_runner_dependency_unavailable")
    return dict(sorted(result.items()))


def _load_dependencies() -> tuple[Any, Any, Any, Any]:
    try:
        from PIL import Image
        from pypdf import PdfReader
        import pdfplumber
        import pypdfium2
    except (ImportError, ModuleNotFoundError):
        _raise("pdf_visual_runner_dependency_unavailable")
    return PdfReader, pdfplumber, pypdfium2, Image


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _bbox_from_object(value: Mapping[str, Any]) -> dict[str, float] | None:
    x0 = _finite(value.get("x0"))
    top = _finite(value.get("top"))
    x1 = _finite(value.get("x1"))
    bottom = _finite(value.get("bottom"))
    if None in (x0, top, x1, bottom):
        return None
    assert x0 is not None and top is not None and x1 is not None and bottom is not None
    if x1 <= x0 or bottom <= top:
        return None
    return {"x": x0, "y": top, "w": x1 - x0, "h": bottom - top}


def _bbox_from_geometry(value: Mapping[str, Any]) -> dict[str, float] | None:
    """Return a small-area bbox for zero-width/height PDF drawing primitives."""

    x0 = _finite(value.get("x0"))
    top = _finite(value.get("top"))
    x1 = _finite(value.get("x1"))
    bottom = _finite(value.get("bottom"))
    if None in (x0, top, x1, bottom):
        return None
    assert x0 is not None and top is not None and x1 is not None and bottom is not None
    if x1 < x0 or bottom < top or (x1 == x0 and bottom == top):
        return None
    half_stroke = max(0.25, (_finite(value.get("linewidth")) or 0.5) / 2)
    if x1 == x0:
        x0 -= half_stroke
        x1 += half_stroke
    if bottom == top:
        top -= half_stroke
        bottom += half_stroke
    return {"x": x0, "y": top, "w": x1 - x0, "h": bottom - top}


def _bbox_from_tuple(value: Any) -> dict[str, float] | None:
    if (
        isinstance(value, (str, bytes, bytearray))
        or not isinstance(value, Sequence)
        or len(value) != 4
    ):
        return None
    numbers = [_finite(item) for item in value]
    if any(item is None for item in numbers):
        return None
    x0, top, x1, bottom = (float(item) for item in numbers)
    if x1 <= x0 or bottom <= top:
        return None
    return {"x": x0, "y": top, "w": x1 - x0, "h": bottom - top}


def _bbox_edges(bbox: Mapping[str, float]) -> tuple[float, float, float, float]:
    return (
        float(bbox["x"]),
        float(bbox["y"]),
        float(bbox["x"] + bbox["w"]),
        float(bbox["y"] + bbox["h"]),
    )


def _overlap_ratio(first: Mapping[str, float], second: Mapping[str, float]) -> float:
    ax0, ay0, ax1, ay1 = _bbox_edges(first)
    bx0, by0, bx1, by1 = _bbox_edges(second)
    width = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    height = max(0.0, min(ay1, by1) - max(ay0, by0))
    intersection = width * height
    denominator = max(1e-9, min((ax1 - ax0) * (ay1 - ay0), (bx1 - bx0) * (by1 - by0)))
    return intersection / denominator


def _placement_records(page: Any) -> list[dict[str, Any]]:
    placements: list[dict[str, Any]] = []
    for raw in getattr(page, "images", ()):
        if not isinstance(raw, Mapping):
            _raise("pdf_visual_runner_geometry_invalid")
        bbox = _bbox_from_object(raw)
        name = raw.get("name")
        if bbox is None or not isinstance(name, str) or not name:
            _raise("pdf_visual_runner_geometry_invalid")
        placement: dict[str, Any] = {"name": name, "bbox": bbox}
        source_size = raw.get("srcsize")
        if (
            isinstance(source_size, Sequence)
            and not isinstance(source_size, (str, bytes, bytearray))
            and len(source_size) == 2
            and all(
                isinstance(item, int) and not isinstance(item, bool) and item > 0
                for item in source_size
            )
        ):
            placement["srcsize"] = [int(source_size[0]), int(source_size[1])]
        stream = raw.get("stream")
        objid = getattr(stream, "objid", None)
        generation = getattr(stream, "genno", None)
        if isinstance(objid, int) and objid >= 1:
            placement["indirect_ref"] = {
                "idnum": objid,
                "generation": generation if isinstance(generation, int) and generation >= 0 else 0,
            }
        placements.append(placement)
    placements.sort(
        key=lambda row: (
            float(row["bbox"]["y"]),
            float(row["bbox"]["x"]),
            str(row["name"]),
            canonical_json(row.get("indirect_ref")),
        )
    )
    return placements


def _near(value: float, target: float, tolerance: float = 1.0) -> bool:
    return abs(value - target) <= tolerance


def _verified_ruled_table(page: Any, table: Any) -> dict[str, Any] | None:
    bbox = _bbox_from_tuple(getattr(table, "bbox", None))
    raw_cells = getattr(table, "cells", None)
    if bbox is None or not isinstance(raw_cells, Sequence):
        return None
    cells = [
        candidate
        for candidate in (_bbox_from_tuple(cell) for cell in raw_cells)
        if candidate
    ]
    if len(cells) < 4:
        return None
    x_boundaries = sorted(
        {round(edge, 3) for cell in cells for edge in (cell["x"], cell["x"] + cell["w"])}
    )
    y_boundaries = sorted(
        {round(edge, 3) for cell in cells for edge in (cell["y"], cell["y"] + cell["h"])}
    )
    if len(x_boundaries) < 3 or len(y_boundaries) < 3:
        return None
    bx0, by0, bx1, by1 = _bbox_edges(bbox)
    vertical: list[Mapping[str, Any]] = []
    horizontal: list[Mapping[str, Any]] = []
    for edge in getattr(page, "edges", ()):
        if not isinstance(edge, Mapping):
            continue
        orientation = edge.get("orientation")
        x0 = _finite(edge.get("x0"))
        top = _finite(edge.get("top"))
        x1 = _finite(edge.get("x1"))
        bottom = _finite(edge.get("bottom"))
        if None in (x0, top, x1, bottom):
            continue
        assert x0 is not None and top is not None and x1 is not None and bottom is not None
        if x1 < bx0 - 1 or x0 > bx1 + 1 or bottom < by0 - 1 or top > by1 + 1:
            continue
        if orientation == "v" and bottom > top:
            vertical.append(edge)
        elif orientation == "h" and x1 > x0:
            horizontal.append(edge)
    vertical_positions = [
        float(edge["x0"])
        for edge in vertical
        if _finite(edge.get("x0")) is not None and _finite(edge.get("x1")) is not None
    ]
    horizontal_positions = [
        float(edge["top"])
        for edge in horizontal
        if _finite(edge.get("top")) is not None and _finite(edge.get("bottom")) is not None
    ]
    required_x = (bx0, bx1, *x_boundaries[1:-1])
    required_y = (by0, by1, *y_boundaries[1:-1])
    if not all(
        any(_near(position, target) for position in vertical_positions)
        for target in required_x
    ):
        return None
    if not all(
        any(_near(position, target) for position in horizontal_positions)
        for target in required_y
    ):
        return None
    return {
        "bbox": bbox,
        "verified": True,
        "cell_grid_verified": True,
        "container_anchor": "pdf-ruled-table:"
        + sha256_text(
            canonical_json({"bbox": bbox, "x": x_boundaries, "y": y_boundaries})
        )[:24],
    }


def _table_candidates(page: Any) -> list[dict[str, Any]]:
    try:
        finder = page.find_tables(
            table_settings={
                "vertical_strategy": "lines",
                "horizontal_strategy": "lines",
                "snap_tolerance": 3,
                "join_tolerance": 3,
                "intersection_tolerance": 3,
            }
        )
        tables = list(getattr(finder, "tables", finder))
    except Exception:
        _raise("pdf_visual_runner_table_detection_failed")
    result = [
        candidate
        for candidate in (_verified_ruled_table(page, table) for table in tables)
        if candidate
    ]
    deduplicated = {canonical_json(candidate["bbox"]): candidate for candidate in result}
    return [deduplicated[key] for key in sorted(deduplicated)]


def _expanded_overlap(
    first: Mapping[str, float],
    second: Mapping[str, float],
    padding: float = 4.0,
) -> bool:
    ax0, ay0, ax1, ay1 = _bbox_edges(first)
    bx0, by0, bx1, by1 = _bbox_edges(second)
    return not (
        ax1 + padding < bx0
        or bx1 + padding < ax0
        or ay1 + padding < by0
        or by1 + padding < ay0
    )


def _union_bbox(values: Sequence[Mapping[str, float]]) -> dict[str, float]:
    edges = [_bbox_edges(value) for value in values]
    x0 = min(value[0] for value in edges)
    y0 = min(value[1] for value in edges)
    x1 = max(value[2] for value in edges)
    y1 = max(value[3] for value in edges)
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def _vector_candidates(
    page: Any,
    *,
    excluded: Sequence[Mapping[str, float]],
    max_drawing_objects: int,
) -> list[dict[str, Any]]:
    geometries: list[tuple[str, dict[str, float]]] = []
    drawing_count = sum(
        len(collection)
        for collection in (
            getattr(page, "rects", ()),
            getattr(page, "lines", ()),
            getattr(page, "curves", ()),
        )
    )
    if drawing_count > max_drawing_objects:
        page_width = _finite(getattr(page, "width", None))
        page_height = _finite(getattr(page, "height", None))
        if (
            page_width is None
            or page_height is None
            or page_width <= 0
            or page_height <= 0
        ):
            _raise("pdf_visual_runner_page_geometry_invalid")
        # Preserve an explicit, page-local withheld occurrence instead of either
        # exhausting quadratic geometry grouping or silently dropping the page.
        # The downstream v2 reconciler classifies this unverified region as
        # ambiguous, so it is cropped for review but never becomes retrievable.
        bbox = {"x": 0.0, "y": 0.0, "w": page_width, "h": page_height}
        return [
            {
                "bbox": bbox,
                "verified": False,
                "region_kind": "ambiguous",
                "container_anchor": "pdf-vector-complexity-withheld:"
                + sha256_text(
                    canonical_json(
                        {
                            "bbox": bbox,
                            "drawing_count": drawing_count,
                            "limit": max_drawing_objects,
                        }
                    )
                )[:24],
            }
        ]
    for kind, collection in (
        ("rect", getattr(page, "rects", ())),
        ("line", getattr(page, "lines", ())),
        ("curve", getattr(page, "curves", ())),
    ):
        for raw in collection:
            if not isinstance(raw, Mapping):
                continue
            bbox = _bbox_from_geometry(raw)
            if bbox is None or any(_overlap_ratio(bbox, item) >= 0.8 for item in excluded):
                continue
            geometries.append((kind, bbox))
    if not geometries:
        return []
    parents = list(range(len(geometries)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    ordered = sorted(
        range(len(geometries)),
        key=lambda index: (_bbox_edges(geometries[index][1])[0], index),
    )
    for position, left in enumerate(ordered):
        left_right = _bbox_edges(geometries[left][1])[2]
        for right in ordered[position + 1 :]:
            if _bbox_edges(geometries[right][1])[0] > left_right + 4.0:
                break
            if _expanded_overlap(geometries[left][1], geometries[right][1]):
                union(left, right)
    groups: dict[int, list[tuple[str, dict[str, float]]]] = {}
    for index, geometry in enumerate(geometries):
        groups.setdefault(find(index), []).append(geometry)
    page_width = float(page.width)
    page_height = float(page.height)
    page_area = max(page_width * page_height, 1.0)
    result: list[dict[str, Any]] = []
    for group in groups.values():
        kinds = [kind for kind, _ in group]
        if kinds.count("rect") < 2 or len(group) < 6 or sum(kind != "rect" for kind in kinds) < 3:
            continue
        bbox = _union_bbox([value for _, value in group])
        area = bbox["w"] * bbox["h"]
        if bbox["w"] < 48 or bbox["h"] < 36 or area > page_area * 0.9:
            continue
        result.append(
            {
                "bbox": bbox,
                "verified": True,
                "region_kind": "vector_diagram",
                "container_anchor": "pdf-vector-geometry:"
                + sha256_text(canonical_json({"bbox": bbox, "kinds": sorted(kinds)}))[:24],
            }
        )
    result.sort(key=lambda row: (row["bbox"]["y"], row["bbox"]["x"], row["container_anchor"]))
    return result


def _canonical_png(image: Any, *, max_bytes: int) -> bytes:
    try:
        canonical = image.convert("RGBA")
        output = io.BytesIO()
        canonical.save(output, format="PNG", optimize=False, compress_level=9)
        payload = output.getvalue()
    except (AttributeError, OSError, TypeError, ValueError):
        _raise("pdf_visual_runner_render_failed")
    if not payload or len(payload) > max_bytes:
        _raise("pdf_visual_runner_render_limit_exceeded")
    return payload


def _add_page_crops(
    candidates: Sequence[Mapping[str, Any]],
    *,
    rendered: Any,
    page_width: float,
    page_height: float,
    page_render_sha256: str,
    render_profile_sha256: str,
    limits: PdfVisualV2Limits,
) -> list[dict[str, Any]]:
    if page_width <= 0 or page_height <= 0:
        _raise("pdf_visual_runner_page_geometry_invalid")
    pixel_width, pixel_height = rendered.size
    scale_x = pixel_width / page_width
    scale_y = pixel_height / page_height
    result: list[dict[str, Any]] = []
    for candidate in candidates:
        bbox_value = candidate.get("bbox")
        if not isinstance(bbox_value, Mapping):
            _raise("pdf_visual_runner_geometry_invalid")
        x = _finite(bbox_value.get("x"))
        y = _finite(bbox_value.get("y"))
        width = _finite(bbox_value.get("w"))
        height = _finite(bbox_value.get("h"))
        if None in (x, y, width, height):
            _raise("pdf_visual_runner_geometry_invalid")
        assert x is not None and y is not None and width is not None and height is not None
        tolerance = 0.01
        if (
            width <= 0
            or height <= 0
            or x < -tolerance
            or y < -tolerance
            or x + width > page_width + tolerance
            or y + height > page_height + tolerance
        ):
            _raise("pdf_visual_runner_geometry_outside_page")
        left = max(0, math.floor(max(0.0, x) * scale_x))
        top = max(0, math.floor(max(0.0, y) * scale_y))
        right = min(pixel_width, math.ceil(min(page_width, x + width) * scale_x))
        bottom = min(pixel_height, math.ceil(min(page_height, y + height) * scale_y))
        if right <= left or bottom <= top or (right - left) * (bottom - top) > limits.max_pixels:
            _raise("pdf_visual_runner_crop_limit_exceeded")
        crop_bytes = _canonical_png(
            rendered.crop((left, top, right, bottom)),
            max_bytes=limits.max_image_bytes,
        )
        enriched = dict(candidate)
        enriched.update(
            {
                "crop_bytes": crop_bytes,
                "page_render_sha256": page_render_sha256,
                "render_profile_sha256": render_profile_sha256,
            }
        )
        result.append(enriched)
    return result


def _render_page(
    pdfium_page: Any,
    *,
    page_width: float,
    page_height: float,
    render_scale: float,
    runner_limits: PdfVisualRunnerLimits,
) -> tuple[Any, str]:
    expected_width = math.ceil(page_width * render_scale)
    expected_height = math.ceil(page_height * render_scale)
    if (
        expected_width < 1
        or expected_height < 1
        or expected_width * expected_height > runner_limits.max_rendered_pixels_per_page
    ):
        _raise("pdf_visual_runner_render_limit_exceeded")
    try:
        bitmap = pdfium_page.render(scale=render_scale, rotation=0)
        image = bitmap.to_pil().convert("RGBA")
    except Exception:
        _raise("pdf_visual_runner_render_failed")
    if image.width * image.height > runner_limits.max_rendered_pixels_per_page:
        _raise("pdf_visual_runner_render_limit_exceeded")
    expected_aspect = page_width / page_height
    actual_aspect = image.width / image.height
    if abs(expected_aspect - actual_aspect) / expected_aspect > 0.01:
        _raise("pdf_visual_runner_render_geometry_mismatch")
    page_png = _canonical_png(image, max_bytes=runner_limits.max_page_render_bytes)
    return image, hashlib.sha256(page_png).hexdigest()


def _adapter_code_sha256() -> str:
    from midprojectrag.ingest import pdf_visual_v2

    runner_path = Path(__file__).resolve()
    adapter_path = Path(pdf_visual_v2.__file__).resolve()
    return sha256_text(
        canonical_json(
            {
                "runner": sha256_file(runner_path),
                "adapter": sha256_file(adapter_path),
            }
        )
    )


def run_pdf_visual_v2_from_manifest(
    *,
    manifest_path: Path,
    data_dir: Path,
    output_dir: Path,
    private_root: Path | None = None,
    render_scale: float = 2.0,
    expected_existing_artifact_set_id: str | None = None,
    limits: PdfVisualV2Limits = DEFAULT_PDF_VISUAL_V2_LIMITS,
    runner_limits: PdfVisualRunnerLimits = DEFAULT_PDF_VISUAL_RUNNER_LIMITS,
) -> dict[str, Any]:
    """Build the local PDF visual-v2 corpus from a private extracted manifest.

    Only ``.pdf`` rows whose extraction status is exactly ``ok`` are selected.
    The source path, byte size, SHA-256 and parser page counts are rechecked
    before any artifact is published.  Rendering, geometry recovery and crop
    generation are local-only; the returned value is aggregate metadata and
    never contains document names, paths, text, or image bytes.
    """

    if (
        isinstance(render_scale, bool)
        or not isinstance(render_scale, (int, float))
        or not math.isfinite(float(render_scale))
        or not 0.5 <= float(render_scale) <= 4.0
    ):
        _raise("pdf_visual_runner_render_scale_invalid")
    data_root = _safe_existing_directory(data_dir, "pdf_visual_runner_data_dir_invalid")
    if private_root is None:
        private_root = (data_root / "private").resolve(strict=False)
    private = _safe_existing_directory(private_root, "pdf_visual_runner_private_root_invalid")
    if private == data_root or not private.is_relative_to(data_root):
        _raise("pdf_visual_runner_private_root_invalid")
    manifest = _safe_contained_file(
        manifest_path,
        private,
        "pdf_visual_runner_manifest_outside_private_root",
    )
    manifest_bytes, manifest_rows = _read_manifest(manifest, limits=runner_limits)
    selected = _selected_pdf_rows(manifest_rows, limits=limits)
    PdfReader, pdfplumber, pypdfium2, _ = _load_dependencies()
    dependency_versions = _dependency_versions()
    render_profile = {
        "policy": PDF_VISUAL_RENDER_POLICY,
        "scale": float(render_scale),
        "rotation": 0,
        "coordinate_space": "pdf_points_top_left",
        "color_mode": "RGBA",
    }
    render_profile_sha256 = sha256_text(canonical_json(render_profile))
    config = {
        "runner_version": PDF_VISUAL_RUNNER_VERSION,
        "geometry_policy": PDF_VISUAL_GEOMETRY_POLICY,
        "render_profile": render_profile,
        "runner_limits": asdict(runner_limits),
        "visual_limits": asdict(limits),
        "eligible_manifest_status": "ok",
    }
    config_sha256 = sha256_text(canonical_json(config))
    documents: list[dict[str, Any]] = []
    source_buffers: list[io.BytesIO] = []
    total_source_bytes = 0
    total_pages = 0

    for entry in selected:
        doc_id, source_sha256, payload = _read_verified_source(
            entry,
            data_root=data_root,
            runner_limits=runner_limits,
        )
        total_source_bytes += len(payload)
        if total_source_bytes > runner_limits.max_total_source_bytes:
            _raise("pdf_visual_runner_total_source_bytes_exceeded")
        pypdf_buffer = io.BytesIO(payload)
        plumber_buffer = io.BytesIO(payload)
        source_buffers.extend((pypdf_buffer, plumber_buffer))
        pdfium_document = None
        plumber_document = None
        try:
            reader = PdfReader(pypdf_buffer, strict=False)
            if bool(getattr(reader, "is_encrypted", False)):
                _raise("pdf_visual_runner_encrypted_pdf")
            pdfium_document = pypdfium2.PdfDocument(payload)
            plumber_document = pdfplumber.open(plumber_buffer)
        except PdfVisualRunnerError:
            if pdfium_document is not None:
                pdfium_document.close()
            raise
        except Exception:
            if plumber_document is not None:
                plumber_document.close()
            if pdfium_document is not None:
                pdfium_document.close()
            _raise("pdf_visual_runner_open_failed")
        assert pdfium_document is not None and plumber_document is not None
        try:
            page_count = len(reader.pages)
            if (
                page_count < 1
                or len(plumber_document.pages) != page_count
                or len(pdfium_document) != page_count
            ):
                _raise("pdf_visual_runner_page_count_mismatch")
            manifest_page_count = entry.get("page_count")
            if (
                not isinstance(manifest_page_count, int)
                or isinstance(manifest_page_count, bool)
                or manifest_page_count != page_count
            ):
                _raise("pdf_visual_runner_manifest_page_count_mismatch")
            total_pages += page_count
            if (
                total_pages > limits.max_total_pages
                or page_count > limits.max_pages_per_document
            ):
                _raise("pdf_visual_runner_page_limit_exceeded")
            pages: list[dict[str, Any]] = []
            for page_index in range(page_count):
                plumber_page = plumber_document.pages[page_index]
                width = float(plumber_page.width)
                height = float(plumber_page.height)
                if (
                    not math.isfinite(width)
                    or not math.isfinite(height)
                    or width <= 0
                    or height <= 0
                ):
                    _raise("pdf_visual_runner_page_geometry_invalid")
                placements = _placement_records(plumber_page)
                tables = _table_candidates(plumber_page)
                excluded = [
                    *(candidate["bbox"] for candidate in tables),
                    *(candidate["bbox"] for candidate in placements),
                ]
                vectors = _vector_candidates(
                    plumber_page,
                    excluded=excluded,
                    max_drawing_objects=runner_limits.max_drawing_objects_per_page,
                )
                if len(placements) > limits.max_placements_per_page:
                    _raise("pdf_visual_runner_placement_limit_exceeded")
                if len(tables) + len(vectors) > limits.max_regions_per_page:
                    _raise("pdf_visual_runner_region_limit_exceeded")
                if placements or tables or vectors:
                    rendered, page_render_sha256 = _render_page(
                        pdfium_document[page_index],
                        page_width=width,
                        page_height=height,
                        render_scale=float(render_scale),
                        runner_limits=runner_limits,
                    )
                    placements = _add_page_crops(
                        placements,
                        rendered=rendered,
                        page_width=width,
                        page_height=height,
                        page_render_sha256=page_render_sha256,
                        render_profile_sha256=render_profile_sha256,
                        limits=limits,
                    )
                    tables = _add_page_crops(
                        tables,
                        rendered=rendered,
                        page_width=width,
                        page_height=height,
                        page_render_sha256=page_render_sha256,
                        render_profile_sha256=render_profile_sha256,
                        limits=limits,
                    )
                    vectors = _add_page_crops(
                        vectors,
                        rendered=rendered,
                        page_width=width,
                        page_height=height,
                        page_render_sha256=page_render_sha256,
                        render_profile_sha256=render_profile_sha256,
                        limits=limits,
                    )
                pages.append(
                    {
                        "page_number": page_index + 1,
                        "pypdf_page": reader.pages[page_index],
                        "placements": placements,
                        "table_candidates": tables,
                        "vector_candidates": vectors,
                    }
                )
            documents.append(
                {
                    "doc_id": doc_id,
                    "source_sha256": source_sha256,
                    "pages": pages,
                }
            )
        finally:
            try:
                plumber_document.close()
            except Exception:
                pass
            try:
                pdfium_document.close()
            except Exception:
                pass

    metadata = materialize_pdf_visual_v2_corpus(
        documents=documents,
        output_dir=output_dir,
        private_root=private,
        source_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        adapter_code_sha256=_adapter_code_sha256(),
        config_sha256=config_sha256,
        dependency_versions=dependency_versions,
        expected_existing_artifact_set_id=expected_existing_artifact_set_id,
        limits=limits,
    )
    source_buffers.clear()
    return metadata


__all__ = [
    "DEFAULT_PDF_VISUAL_RUNNER_LIMITS",
    "PDF_VISUAL_GEOMETRY_POLICY",
    "PDF_VISUAL_RENDER_POLICY",
    "PDF_VISUAL_RUNNER_VERSION",
    "PdfVisualRunnerError",
    "PdfVisualRunnerLimits",
    "run_pdf_visual_v2_from_manifest",
]
