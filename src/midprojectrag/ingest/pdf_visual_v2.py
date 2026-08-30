from __future__ import annotations

import io
import json
import math
import os
import re
import tempfile
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePosixPath
from typing import Any

from midprojectrag.ingest.common import (
    canonical_json,
    sha256_bytes,
    sha256_file,
    sha256_text,
    write_json,
    write_jsonl,
)
from midprojectrag.ingest.visual_evidence import (
    occurrence_id as visual_occurrence_id,
    source_object_id as visual_source_object_id,
    validate_visual_occurrence,
)


PDF_VISUAL_V2_SCHEMA_VERSION = "2.0"
PDF_VISUAL_V2_METHOD = "local-visual-occurrence-understanding-v2"
PDF_COORDINATE_SPACE = "pdf_points_top_left"

RESOURCE_ARTIFACT = "pdf-resources-v2.jsonl"
OCCURRENCE_ARTIFACT = "visual-occurrences-v2.jsonl"
OBJECT_MANIFEST_ARTIFACT = "object-manifest-v2.jsonl"
METADATA_ARTIFACT = "visual-corpus-v2-metadata.json"

_DOC_ID_RE = re.compile(r"^doc_[0-9a-f]{24}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_WARNING_RE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_REGION_KINDS = (
    "raster_image",
    "inline_image",
    "vector_diagram",
    "table",
    "table_child_image",
    "decorative",
    "ambiguous",
)
_SOURCE_STATUSES = (
    "exact_resource_link",
    "verified_exact_visual_match",
    "render_only",
    "unsupported",
    "missing",
    "ambiguous",
)
_RETRIEVAL_STATUSES = ("eligible", "withheld", "quarantined")
_MEDIA_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jp2": ".jp2",
    "image/tiff": ".tif",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/webp": ".webp",
    "application/octet-stream": ".bin",
}
_ABSOLUTE_LIMITS = {
    "max_documents": 10_000,
    "max_total_pages": 1_000_000,
    "max_total_occurrences": 10_000_000,
    "max_pages_per_document": 100_000,
    "max_resources_per_page": 100_000,
    "max_placements_per_page": 100_000,
    "max_regions_per_page": 100_000,
    "max_image_bytes": 512 * 1024 * 1024,
    "max_mask_bytes": 512 * 1024 * 1024,
    "max_total_asset_bytes": 16 * 1024 * 1024 * 1024,
    "max_pixels": 250_000_000,
    "max_resource_path_parts": 56,
    "max_string_chars": 4_096,
}


class PdfVisualV2Error(ValueError):
    """Stable, content-free failure raised by the PDF visual v2 adapter."""


@dataclass(frozen=True, slots=True)
class PdfVisualV2Limits:
    max_documents: int = 1_000
    max_total_pages: int = 100_000
    max_total_occurrences: int = 2_000_000
    max_pages_per_document: int = 10_000
    max_resources_per_page: int = 10_000
    max_placements_per_page: int = 20_000
    max_regions_per_page: int = 20_000
    max_image_bytes: int = 128 * 1024 * 1024
    max_mask_bytes: int = 128 * 1024 * 1024
    max_total_asset_bytes: int = 4 * 1024 * 1024 * 1024
    max_pixels: int = 100_000_000
    max_resource_path_parts: int = 56
    max_string_chars: int = 1_024

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 1
                or value > _ABSOLUTE_LIMITS[field.name]
            ):
                raise PdfVisualV2Error("pdf_visual_v2_limits_invalid")


DEFAULT_PDF_VISUAL_V2_LIMITS = PdfVisualV2Limits()


@dataclass(frozen=True, slots=True)
class PdfImageResource:
    """One pypdf image resource and the bytes needed for durable publication.

    ``resource_id`` identifies a document-local PDF resource.  The separate
    ``source_object_id`` is content-addressed, so one object may be referenced
    by many resources and placements.
    """

    record: dict[str, Any]
    source_bytes: bytes
    canonical_bytes: bytes | None
    mask_payloads: tuple[tuple[str, bytes], ...] = ()

    def as_record(self) -> dict[str, Any]:
        return json.loads(canonical_json(self.record))

    def asset_payloads(self) -> tuple[tuple[str, bytes, str, str], ...]:
        payloads: list[tuple[str, bytes, str, str]] = [
            (
                str(self.record["source_asset_relpath"]),
                self.source_bytes,
                str(self.record["source_media_type"]),
                "pdf_resource_raw",
            )
        ]
        canonical_path = self.record.get("canonical_asset_relpath")
        canonical_media_type = self.record.get("canonical_media_type")
        if (
            isinstance(canonical_path, str)
            and isinstance(canonical_media_type, str)
            and self.canonical_bytes is not None
        ):
            payloads.append(
                (
                    canonical_path,
                    self.canonical_bytes,
                    canonical_media_type,
                    "canonical_visual_object",
                )
            )
        mask_by_path = dict(self.mask_payloads)
        for mask in self.record["mask_provenance"]:
            relpath = mask.get("asset_relpath")
            media_type = mask.get("media_type")
            if isinstance(relpath, str) and relpath in mask_by_path:
                payloads.append(
                    (
                        relpath,
                        mask_by_path[relpath],
                        str(media_type or "application/octet-stream"),
                        "pdf_image_mask",
                    )
                )
        return tuple(payloads)


@dataclass(frozen=True, slots=True)
class PdfVisualPageRecovery:
    resources: tuple[PdfImageResource, ...]
    occurrences: tuple[dict[str, Any], ...]


def _raise(code: str) -> None:
    raise PdfVisualV2Error(code)


def _require_sha256(value: Any, code: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        _raise(code)
    return value


def _require_doc_id(value: Any) -> str:
    if not isinstance(value, str) or _DOC_ID_RE.fullmatch(value) is None:
        _raise("pdf_visual_v2_doc_id_invalid")
    return value


def _canonical_hash(value: Any, code: str = "pdf_visual_v2_value_invalid") -> str:
    try:
        return sha256_text(canonical_json(value))
    except (TypeError, ValueError):
        _raise(code)


def _require_sequence(value: Any, code: str, maximum: int) -> list[Any]:
    if (
        isinstance(value, (str, bytes, bytearray))
        or not isinstance(value, Sequence)
        or len(value) > maximum
    ):
        _raise(code)
    return list(value)


def _bounded_text(value: Any, limits: PdfVisualV2Limits, code: str) -> str:
    if not isinstance(value, str):
        _raise(code)
    normalized = unicodedata.normalize("NFC", value).strip()
    if (
        not normalized
        or len(normalized) > limits.max_string_chars
        or any(unicodedata.category(character) == "Cc" for character in normalized)
    ):
        _raise(code)
    return normalized


def _safe_warning(value: str) -> str:
    if _SAFE_WARNING_RE.fullmatch(value) is None:
        _raise("pdf_visual_v2_warning_invalid")
    return value


def _round_coordinate(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _raise("pdf_visual_v2_bbox_invalid")
    number = float(value)
    if not math.isfinite(number) or abs(number) > 10_000_000:
        _raise("pdf_visual_v2_bbox_invalid")
    rounded = round(number, 6)
    return 0.0 if rounded == 0 else rounded


def _bbox(raw: Any) -> dict[str, float]:
    if isinstance(raw, Mapping) and isinstance(raw.get("bbox"), (Mapping, list, tuple)):
        return _bbox(raw["bbox"])
    if isinstance(raw, Mapping) and all(key in raw for key in ("x", "y", "w", "h")):
        x = _round_coordinate(raw["x"])
        y = _round_coordinate(raw["y"])
        width = _round_coordinate(raw["w"])
        height = _round_coordinate(raw["h"])
    elif isinstance(raw, Mapping) and all(
        key in raw for key in ("x0", "top", "x1", "bottom")
    ):
        x = _round_coordinate(raw["x0"])
        y = _round_coordinate(raw["top"])
        width = _round_coordinate(float(raw["x1"]) - float(raw["x0"]))
        height = _round_coordinate(float(raw["bottom"]) - float(raw["top"]))
    elif isinstance(raw, Mapping) and all(
        key in raw for key in ("left", "top", "right", "bottom")
    ):
        x = _round_coordinate(raw["left"])
        y = _round_coordinate(raw["top"])
        width = _round_coordinate(float(raw["right"]) - float(raw["left"]))
        height = _round_coordinate(float(raw["bottom"]) - float(raw["top"]))
    elif (
        isinstance(raw, Sequence)
        and not isinstance(raw, (str, bytes, bytearray))
        and len(raw) == 4
    ):
        x = _round_coordinate(raw[0])
        y = _round_coordinate(raw[1])
        width = _round_coordinate(float(raw[2]) - float(raw[0]))
        height = _round_coordinate(float(raw[3]) - float(raw[1]))
    else:
        _raise("pdf_visual_v2_bbox_invalid")
    if width <= 0 or height <= 0:
        _raise("pdf_visual_v2_bbox_invalid")
    return {"x": x, "y": y, "w": width, "h": height}


def _bbox_sort_key(value: Mapping[str, Any]) -> tuple[float, float, float, float]:
    return (
        float(value["y"]),
        float(value["x"]),
        float(value["h"]),
        float(value["w"]),
    )


def _contains(outer: Mapping[str, Any], inner: Mapping[str, Any]) -> bool:
    tolerance = 0.000001
    return (
        float(inner["x"]) >= float(outer["x"]) - tolerance
        and float(inner["y"]) >= float(outer["y"]) - tolerance
        and float(inner["x"]) + float(inner["w"])
        <= float(outer["x"]) + float(outer["w"]) + tolerance
        and float(inner["y"]) + float(inner["h"])
        <= float(outer["y"]) + float(outer["h"]) + tolerance
    )


def _resource_path(key: Any, limits: PdfVisualV2Limits) -> tuple[str, ...]:
    if isinstance(key, Sequence) and not isinstance(key, (str, bytes, bytearray)):
        raw_parts = list(key)
    else:
        raw_parts = [key]
    if not raw_parts or len(raw_parts) > limits.max_resource_path_parts:
        _raise("pdf_visual_v2_resource_path_invalid")
    parts: list[str] = []
    for raw in raw_parts:
        if isinstance(raw, int) and not isinstance(raw, bool):
            text = f"inline:{raw}"
        else:
            text = _bounded_text(str(raw), limits, "pdf_visual_v2_resource_path_invalid")
        text = text.lstrip("/")
        if not text:
            _raise("pdf_visual_v2_resource_path_invalid")
        parts.append(text)
    if len("/".join(parts)) > 256:
        _raise("pdf_visual_v2_resource_path_invalid")
    return tuple(parts)


def _match_name(value: Any, limits: PdfVisualV2Limits) -> str | None:
    if value is None:
        return None
    text = _bounded_text(str(value), limits, "pdf_visual_v2_resource_name_invalid")
    text = text.lstrip("/")
    lower = text.lower()
    for extension in (".jpeg", ".jpg", ".png", ".jp2", ".tiff", ".tif", ".gif", ".bmp", ".webp"):
        if lower.endswith(extension):
            text = text[: -len(extension)]
            break
    return text or None


def _indirect_ref(value: Any) -> dict[str, int] | None:
    if value is None:
        return None
    idnum = getattr(value, "idnum", None)
    generation = getattr(value, "generation", None)
    if isinstance(value, Mapping):
        idnum = value.get("idnum", value.get("object_number", idnum))
        generation = value.get("generation", generation)
    if isinstance(idnum, int) and not isinstance(idnum, bool) and idnum >= 1:
        if generation is None:
            generation = 0
        if isinstance(generation, int) and not isinstance(generation, bool) and generation >= 0:
            return {"idnum": idnum, "generation": generation}
    nested = getattr(value, "indirect_reference", None)
    if nested is not None and nested is not value:
        return _indirect_ref(nested)
    return None


def _resolve_object(value: Any) -> Any:
    getter = getattr(value, "get_object", None)
    if callable(getter):
        try:
            return getter()
        except Exception:
            _raise("pdf_visual_v2_resource_decode_failed")
    return value


def _raw_entry(value: Any, key: str) -> Any:
    raw_get = getattr(value, "raw_get", None)
    if callable(raw_get):
        try:
            return raw_get(key)
        except (KeyError, TypeError):
            pass
        except Exception:
            _raise("pdf_visual_v2_resource_decode_failed")
    if isinstance(value, Mapping):
        for candidate in (key, key.lstrip("/")):
            try:
                if candidate in value:
                    return value[candidate]
            except Exception:
                _raise("pdf_visual_v2_resource_decode_failed")
    return None


def _stream_data(value: Any, maximum: int, code: str) -> bytes | None:
    getter = getattr(value, "get_data", None)
    if not callable(getter):
        return None
    try:
        data = getter()
    except Exception:
        _raise(code)
    if isinstance(data, str):
        data = data.encode("latin-1", errors="strict")
    if not isinstance(data, (bytes, bytearray)) or len(data) > maximum:
        _raise(code)
    return bytes(data)


def _positive_dimension(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number > 0 else None


def _dimensions(value: Any) -> tuple[int | None, int | None]:
    image = getattr(value, "image", None)
    size = getattr(image, "size", None)
    if isinstance(size, Sequence) and len(size) == 2:
        return _positive_dimension(size[0]), _positive_dimension(size[1])
    width = _raw_entry(value, "/Width")
    height = _raw_entry(value, "/Height")
    return _positive_dimension(width), _positive_dimension(height)


def _pillow_image_from_mask(
    mask_object: Any,
    data: bytes | None,
    width: int | None,
    height: int | None,
) -> Any:
    image = getattr(mask_object, "image", None)
    if image is not None and getattr(image, "size", None) is not None:
        return image
    for method_name in ("decode_as_image", "to_pil"):
        method = getattr(mask_object, method_name, None)
        if callable(method):
            try:
                candidate = method()
            except Exception:
                return None
            if candidate is not None and getattr(candidate, "size", None) is not None:
                return candidate
    if data is None or width is None or height is None or len(data) != width * height:
        return None
    try:
        from PIL import Image

        return Image.frombytes("L", (width, height), data)
    except (ImportError, OSError, ValueError):
        return None


def _mask_inventory(
    xobject: Any,
    limits: PdfVisualV2Limits,
) -> tuple[list[dict[str, Any]], Any, tuple[tuple[str, bytes], ...], list[str]]:
    provenance: list[dict[str, Any]] = []
    payloads: list[tuple[str, bytes]] = []
    alpha_image = None
    warnings: list[str] = []
    for pdf_key, kind in (("/SMask", "soft_mask"), ("/Mask", "explicit_mask")):
        raw_mask = _raw_entry(xobject, pdf_key)
        if raw_mask is None:
            continue
        if isinstance(raw_mask, Sequence) and not isinstance(
            raw_mask, (str, bytes, bytearray, Mapping)
        ):
            values = list(raw_mask)
            if len(values) > 256 or any(
                isinstance(item, bool) or not isinstance(item, (int, float)) for item in values
            ):
                _raise("pdf_visual_v2_mask_invalid")
            provenance.append(
                {
                    "kind": "color_key_mask",
                    "indirect_ref": None,
                    "decoded_sha256": _canonical_hash(values),
                    "byte_size": 0,
                    "width": None,
                    "height": None,
                    "media_type": None,
                    "asset_relpath": None,
                    "color_key": values,
                }
            )
            continue
        mask_ref = _indirect_ref(raw_mask)
        mask_object = _resolve_object(raw_mask)
        if mask_ref is None:
            mask_ref = _indirect_ref(mask_object)
        data = _stream_data(
            mask_object,
            limits.max_mask_bytes,
            "pdf_visual_v2_mask_bytes_invalid",
        )
        width, height = _dimensions(mask_object)
        if width is not None and height is not None and width * height > limits.max_pixels:
            _raise("pdf_visual_v2_mask_pixels_exceeded")
        digest = sha256_bytes(data) if data is not None else None
        relpath = f"resources/masks/{digest}.bin" if digest is not None else None
        provenance.append(
            {
                "kind": kind,
                "indirect_ref": mask_ref,
                "decoded_sha256": digest,
                "byte_size": len(data) if data is not None else 0,
                "width": width,
                "height": height,
                "media_type": "application/octet-stream" if data is not None else None,
                "asset_relpath": relpath,
                "color_key": None,
            }
        )
        if data is not None and relpath is not None:
            payloads.append((relpath, data))
        if kind == "soft_mask":
            alpha_image = _pillow_image_from_mask(mask_object, data, width, height)
            if alpha_image is None:
                warnings.append("soft_mask_pixels_unavailable")
    return provenance, alpha_image, tuple(payloads), warnings


def _canonical_png(
    image: Any,
    mask_image: Any,
    limits: PdfVisualV2Limits,
) -> tuple[bytes | None, int | None, int | None, list[str]]:
    if image is None:
        return None, None, None, ["canonical_rgba_unavailable"]
    try:
        size = image.size
        width = _positive_dimension(size[0])
        height = _positive_dimension(size[1])
    except (AttributeError, IndexError, TypeError):
        return None, None, None, ["canonical_rgba_unavailable"]
    if width is None or height is None or width * height > limits.max_pixels:
        _raise("pdf_visual_v2_image_pixels_exceeded")
    warnings: list[str] = []
    try:
        canonical = image.copy()
        canonical.load()
        if mask_image is not None and "A" not in canonical.getbands():
            if tuple(mask_image.size) != tuple(canonical.size):
                warnings.append("soft_mask_dimension_mismatch")
            else:
                alpha = mask_image.convert("L")
                canonical = canonical.convert("RGBA")
                canonical.putalpha(alpha)
        canonical = canonical.convert("RGBA")
        output = io.BytesIO()
        canonical.save(output, format="PNG", optimize=False, compress_level=9)
        data = output.getvalue()
    except (AttributeError, OSError, TypeError, ValueError):
        return None, width, height, [*warnings, "canonical_rgba_unavailable"]
    if len(data) > limits.max_image_bytes:
        _raise("pdf_visual_v2_image_bytes_exceeded")
    return data, width, height, warnings


def _source_media_type(data: bytes, name: str) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"BM"):
        return "image/bmp"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    lowered = name.lower()
    if lowered.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith((".tif", ".tiff")):
        return "image/tiff"
    if lowered.endswith(".jp2"):
        return "image/jp2"
    if lowered.endswith(".gif"):
        return "image/gif"
    if lowered.endswith(".bmp"):
        return "image/bmp"
    if lowered.endswith(".webp"):
        return "image/webp"
    return "application/octet-stream"


def _media_extension(media_type: str) -> str:
    return _MEDIA_EXTENSIONS.get(media_type, ".bin")


def collect_pypdf_image_resources(
    page: Any,
    *,
    doc_id: str,
    source_sha256: str,
    page_number: int,
    limits: PdfVisualV2Limits = DEFAULT_PDF_VISUAL_V2_LIMITS,
) -> list[PdfImageResource]:
    """Collect actual pypdf image bytes without importing pdfplumber.

    The function deliberately accepts a page object instead of opening a file.
    Callers own PDF parsing and supply geometry separately.  This also makes the
    extraction contract testable with public synthetic page doubles.
    """

    doc_id = _require_doc_id(doc_id)
    source_sha256 = _require_sha256(
        source_sha256, "pdf_visual_v2_source_sha256_invalid"
    )
    if (
        not isinstance(page_number, int)
        or isinstance(page_number, bool)
        or page_number < 1
        or page_number > limits.max_pages_per_document
    ):
        _raise("pdf_visual_v2_page_invalid")
    images = getattr(page, "images", None)
    if images is None:
        _raise("pdf_visual_v2_pypdf_page_invalid")
    keys_method = getattr(images, "keys", None)
    try:
        keys = list(keys_method()) if callable(keys_method) else list(range(len(images)))
    except Exception:
        _raise("pdf_visual_v2_resource_inventory_failed")
    if len(keys) > limits.max_resources_per_page:
        _raise("pdf_visual_v2_resource_count_exceeded")

    resources: list[PdfImageResource] = []
    seen_resource_ids: set[str] = set()
    for index, key in enumerate(keys):
        try:
            image_file = images[key] if callable(keys_method) else images[index]
        except Exception:
            _raise("pdf_visual_v2_resource_inventory_failed")
        path = _resource_path(key, limits)
        decoded_name = _bounded_text(
            str(getattr(image_file, "name", path[-1])),
            limits,
            "pdf_visual_v2_resource_name_invalid",
        )
        source_data = getattr(image_file, "data", None)
        if (
            not isinstance(source_data, (bytes, bytearray))
            or not source_data
            or len(source_data) > limits.max_image_bytes
        ):
            _raise("pdf_visual_v2_image_bytes_exceeded")
        source_data = bytes(source_data)
        source_digest = sha256_bytes(source_data)
        source_media_type = _source_media_type(source_data, decoded_name)
        source_relpath = (
            f"resources/raw/{source_digest}{_media_extension(source_media_type)}"
        )

        indirect = getattr(image_file, "indirect_reference", None)
        indirect_record = _indirect_ref(indirect)
        xobject = _resolve_object(indirect) if indirect is not None else None
        mask_records: list[dict[str, Any]] = []
        mask_image = None
        mask_payloads: tuple[tuple[str, bytes], ...] = ()
        warnings: list[str] = []
        if xobject is not None:
            mask_records, mask_image, mask_payloads, mask_warnings = _mask_inventory(
                xobject, limits
            )
            warnings.extend(mask_warnings)

        canonical_data, width, height, canonical_warnings = _canonical_png(
            getattr(image_file, "image", None), mask_image, limits
        )
        warnings.extend(canonical_warnings)
        if width is None or height is None:
            x_width, x_height = _dimensions(xobject)
            width = width or x_width
            height = height or x_height
        if width is not None and height is not None and width * height > limits.max_pixels:
            _raise("pdf_visual_v2_image_pixels_exceeded")

        if canonical_data is not None:
            object_digest = sha256_bytes(canonical_data)
            object_media_type = "image/png"
            canonical_relpath: str | None = f"crops/{object_digest}.png"
            canonical_size: int | None = len(canonical_data)
        else:
            object_digest = source_digest
            object_media_type = source_media_type
            canonical_relpath = None
            canonical_size = None
        source_object_id = visual_source_object_id(object_digest)
        source_image_key = "/".join(path)
        identity = {
            "doc_id": doc_id,
            "source_sha256": source_sha256,
            "page": page_number,
            "resource_path": list(path),
            "indirect_ref": indirect_record,
            "is_inline": bool(getattr(image_file, "is_inline", False)),
            "source_object_sha256": object_digest,
        }
        resource_id = "pdfres_" + _canonical_hash(identity)[:24]
        if resource_id in seen_resource_ids:
            _raise("pdf_visual_v2_resource_identity_collision")
        seen_resource_ids.add(resource_id)
        record = {
            "schema_version": PDF_VISUAL_V2_SCHEMA_VERSION,
            "record_type": "pdf_image_resource",
            "resource_id": resource_id,
            "doc_id": doc_id,
            "source_sha256": source_sha256,
            "page": page_number,
            "resource_path": list(path),
            "source_image_key": source_image_key,
            "resource_name": path[-1],
            "decoded_name": decoded_name,
            "indirect_ref": indirect_record,
            "is_inline": bool(getattr(image_file, "is_inline", False)),
            "is_displayed": bool(getattr(image_file, "is_displayed", False)),
            "intrinsic_width": width,
            "intrinsic_height": height,
            "source_sha256_digest": source_digest,
            "source_byte_size": len(source_data),
            "source_media_type": source_media_type,
            "source_asset_relpath": source_relpath,
            "source_object_id": source_object_id,
            "source_object_sha256": object_digest,
            "source_object_media_type": object_media_type,
            "canonical_sha256": object_digest if canonical_data is not None else None,
            "canonical_byte_size": canonical_size,
            "canonical_media_type": "image/png" if canonical_data is not None else None,
            "canonical_asset_relpath": canonical_relpath,
            "mask_provenance": mask_records,
            "warnings": sorted({_safe_warning(value) for value in warnings}),
        }
        resources.append(
            PdfImageResource(
                record=record,
                source_bytes=source_data,
                canonical_bytes=canonical_data,
                mask_payloads=mask_payloads,
            )
        )
    resources.sort(
        key=lambda resource: (
            tuple(resource.record["resource_path"]),
            canonical_json(resource.record["indirect_ref"]),
            resource.record["resource_id"],
        )
    )
    return resources


inventory_pypdf_page_resources = collect_pypdf_image_resources


def _resource_record(value: PdfImageResource | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(value, PdfImageResource):
        return value.record
    if isinstance(value, Mapping):
        return value
    _raise("pdf_visual_v2_resource_record_invalid")


def _placement_dimensions(value: Mapping[str, Any]) -> tuple[int, int] | None:
    raw = value.get("srcsize", value.get("intrinsic_size"))
    if (
        isinstance(raw, Sequence)
        and not isinstance(raw, (str, bytes, bytearray))
        and len(raw) == 2
    ):
        width = _positive_dimension(raw[0])
        height = _positive_dimension(raw[1])
    else:
        width = _positive_dimension(value.get("intrinsic_width"))
        height = _positive_dimension(value.get("intrinsic_height"))
    if width is None or height is None:
        return None
    return width, height


def _placement_path(
    placement: Mapping[str, Any], limits: PdfVisualV2Limits
) -> tuple[str, ...] | None:
    raw = placement.get("resource_path", placement.get("object_path"))
    if raw is None:
        return None
    return _resource_path(raw, limits)


def _placement_ref(placement: Mapping[str, Any]) -> dict[str, int] | None:
    direct = placement.get("indirect_ref", placement.get("indirect_reference"))
    result = _indirect_ref(direct)
    if result is not None:
        return result
    return _indirect_ref(placement.get("stream"))


def _match_resource(
    placement: Mapping[str, Any],
    resources: Sequence[PdfImageResource | Mapping[str, Any]],
    limits: PdfVisualV2Limits,
) -> tuple[list[Mapping[str, Any]], list[str]]:
    records = [_resource_record(resource) for resource in resources]
    path = _placement_path(placement, limits)
    if path is not None:
        candidates = [
            record for record in records if tuple(record.get("resource_path", ())) == path
        ]
        return candidates, ["document_resource_key"] if candidates else []
    indirect = _placement_ref(placement)
    if indirect is not None:
        candidates = [record for record in records if record.get("indirect_ref") == indirect]
        return candidates, ["document_resource_key"] if candidates else []
    name = _match_name(placement.get("name", placement.get("resource_name")), limits)
    if name is not None:
        candidates = [
            record
            for record in records
            if name
            in {
                _match_name(record.get("resource_name"), limits),
                _match_name(record.get("decoded_name"), limits),
            }
        ]
        dimensions = _placement_dimensions(placement)
        if dimensions is not None:
            candidates = [
                record
                for record in candidates
                if (
                    record.get("intrinsic_width"),
                    record.get("intrinsic_height"),
                )
                == dimensions
            ]
        return candidates, ["document_resource_key"] if candidates else []
    return [], []


def _candidate_png(
    candidate: Mapping[str, Any], limits: PdfVisualV2Limits
) -> tuple[bytes | None, str | None, str | None, str | None, str | None]:
    raw = candidate.get("crop_bytes")
    if raw is None:
        return None, None, None, None, None
    if not isinstance(raw, (bytes, bytearray)) or len(raw) > limits.max_image_bytes:
        _raise("pdf_visual_v2_crop_bytes_invalid")
    try:
        from PIL import Image

        with Image.open(io.BytesIO(bytes(raw))) as image:
            canonical, _, _, warnings = _canonical_png(image, None, limits)
    except (ImportError, OSError, ValueError):
        _raise("pdf_visual_v2_crop_bytes_invalid")
    if canonical is None or warnings:
        _raise("pdf_visual_v2_crop_bytes_invalid")
    crop_sha256 = sha256_bytes(canonical)
    page_render_sha256 = _require_sha256(
        candidate.get("page_render_sha256"),
        "pdf_visual_v2_page_render_sha256_invalid",
    )
    render_profile_sha256 = _require_sha256(
        candidate.get("render_profile_sha256"),
        "pdf_visual_v2_render_profile_sha256_invalid",
    )
    return (
        canonical,
        crop_sha256,
        f"crops/{crop_sha256}.png",
        page_render_sha256,
        render_profile_sha256,
    )


def _container_path(value: Any, *, default: Sequence[str]) -> list[str]:
    raw = default if value is None else value
    if isinstance(raw, (str, bytes, bytearray)) or not isinstance(raw, Sequence):
        _raise("pdf_visual_v2_container_path_invalid")
    result: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item or len(item) > 256:
            _raise("pdf_visual_v2_container_path_invalid")
        result.append(item)
    if len(result) > 64:
        _raise("pdf_visual_v2_container_path_invalid")
    return result


def _source_anchor(kind: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "section_index": None,
        "paragraph_index": None,
        "control_index": None,
        "table_block_id": None,
        "cell_path": [],
    }


def _verified_table(value: Mapping[str, Any]) -> bool:
    return bool(
        value.get("verified") is True
        or value.get("human_verified") is True
        or value.get("cell_grid_verified") is True
        or value.get("status") in {"verified_table", "human_verified"}
    )


def _explicit_region_kind(value: Mapping[str, Any]) -> str | None:
    kind = value.get("region_kind", value.get("classification"))
    return str(kind) if kind in _REGION_KINDS else None


def _nearby_title(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        _raise("pdf_visual_v2_nearby_title_invalid")
    text = value.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > 500:
        _raise("pdf_visual_v2_nearby_title_invalid")
    normalized = unicodedata.normalize("NFC", text).strip()
    title_bbox = _bbox(value)
    return {
        "text": normalized,
        "text_sha256": sha256_text(normalized),
        "bbox": title_bbox,
        "method": "nearest_prior_heading_bounded_v1",
    }


def _draft_sort_key(value: Mapping[str, Any]) -> tuple[Any, ...]:
    kind_order = {
        "table": 0,
        "vector_diagram": 1,
        "raster_image": 2,
        "inline_image": 2,
        "table_child_image": 2,
        "decorative": 3,
        "ambiguous": 4,
    }
    return (
        *_bbox_sort_key(value["bbox"]),
        kind_order[str(value["region_kind"])],
        str(value["_sort_identity"]),
    )


def _occurrence_id(
    *,
    doc_id: str,
    source_sha256: str,
    page: int,
    bbox: Mapping[str, Any],
    region_kind: str,
    container_path: Sequence[str],
    sequence: int,
) -> str:
    return visual_occurrence_id(
        doc_id=doc_id,
        source_sha256=source_sha256,
        page=page,
        bbox=bbox,
        region_kind=region_kind,
        container_path=container_path,
        sequence_in_page=sequence,
    )


def reconcile_pdf_visual_occurrences(
    *,
    doc_id: str,
    source_sha256: str,
    page_number: int,
    resources: Sequence[PdfImageResource | Mapping[str, Any]],
    placements: Sequence[Mapping[str, Any]],
    table_candidates: Sequence[Mapping[str, Any]] = (),
    vector_candidates: Sequence[Mapping[str, Any]] = (),
    limits: PdfVisualV2Limits = DEFAULT_PDF_VISUAL_V2_LIMITS,
) -> list[dict[str, Any]]:
    """Reconcile supplied pdfplumber-like placements with pypdf resources.

    Matching is fail-closed: only a unique resource path/reference/name match is
    promoted.  Every placement remains a separate occurrence, even when many
    placements resolve to the same content-addressed source object.
    """

    doc_id = _require_doc_id(doc_id)
    source_sha256 = _require_sha256(
        source_sha256, "pdf_visual_v2_source_sha256_invalid"
    )
    if (
        not isinstance(page_number, int)
        or isinstance(page_number, bool)
        or not 1 <= page_number <= limits.max_pages_per_document
    ):
        _raise("pdf_visual_v2_page_invalid")
    resource_values = _require_sequence(
        resources, "pdf_visual_v2_resources_invalid", limits.max_resources_per_page
    )
    placement_values = _require_sequence(
        placements, "pdf_visual_v2_placements_invalid", limits.max_placements_per_page
    )
    table_values = _require_sequence(
        table_candidates, "pdf_visual_v2_tables_invalid", limits.max_regions_per_page
    )
    vector_values = _require_sequence(
        vector_candidates, "pdf_visual_v2_vectors_invalid", limits.max_regions_per_page
    )
    if len(placement_values) + len(table_values) + len(vector_values) > limits.max_regions_per_page:
        _raise("pdf_visual_v2_region_count_exceeded")
    if any(
        not isinstance(value, Mapping)
        for value in (*placement_values, *table_values, *vector_values)
    ):
        _raise("pdf_visual_v2_geometry_record_invalid")

    drafts: list[dict[str, Any]] = []
    table_drafts: list[dict[str, Any]] = []
    for index, candidate in enumerate(table_values):
        candidate_bbox = _bbox(candidate)
        verified = _verified_table(candidate)
        crop_bytes, crop_sha, crop_relpath, page_render_sha, profile_sha = _candidate_png(
            candidate, limits
        )
        anchor = str(
            candidate.get("container_anchor")
            or "pdf-table:" + _canonical_hash({"bbox": candidate_bbox, "index": index})[:24]
        )
        container = _container_path(
            candidate.get("container_path"),
            default=("pdf", f"page:{page_number}", anchor),
        )
        draft = {
            "_token": anchor,
            "_parent_token": None,
            "_crop_bytes": crop_bytes,
            "_sort_identity": _canonical_hash(
                {"kind": "table", "bbox": candidate_bbox, "anchor": anchor, "verified": verified}
            ),
            "bbox": candidate_bbox,
            "container_path": container,
            "source_anchor": _source_anchor("pdf_geometry"),
            "region_kind": "table" if verified else "ambiguous",
            "evidence_origin": "page_render_crop",
            "page_render_sha256": page_render_sha,
            "render_profile_sha256": profile_sha,
            "crop_sha256": crop_sha,
            "crop_relpath": crop_relpath,
            "crop_media_type": "image/png" if crop_sha is not None else None,
            "source_image_key": None,
            "source_object_id": None,
            "source_object_sha256": None,
            "source_object_media_type": None,
            "source_object_status": "render_only" if crop_sha is not None else "missing",
            "link_method": "render_region_only" if crop_sha is not None else "none",
            "match_evidence": [
                "bbox_exact",
                *(["page_render"] if crop_sha is not None else []),
            ],
            "placement_status": "page_bbox_verified",
            "understanding_status": "none",
            "retrieval_status": (
                "eligible"
                if crop_sha is not None and verified
                else "withheld"
            ),
            "nearby_title": _nearby_title(candidate.get("nearby_title")),
            "warnings": [] if verified else ["table_classifier_unverified"],
        }
        drafts.append(draft)
        table_drafts.append(draft)

    for index, candidate in enumerate(vector_values):
        candidate_bbox = _bbox(candidate)
        explicit_kind = _explicit_region_kind(candidate)
        if explicit_kind == "decorative":
            kind = "decorative"
        elif explicit_kind == "vector_diagram" or candidate.get("verified") is True:
            kind = "vector_diagram"
        else:
            kind = "ambiguous"
        crop_bytes, crop_sha, crop_relpath, page_render_sha, profile_sha = _candidate_png(
            candidate, limits
        )
        anchor = str(
            candidate.get("container_anchor")
            or "pdf-vector:" + _canonical_hash({"bbox": candidate_bbox, "index": index})[:24]
        )
        container = _container_path(
            candidate.get("container_path"),
            default=("pdf", f"page:{page_number}", anchor),
        )
        drafts.append(
            {
                "_token": anchor,
                "_parent_token": None,
                "_crop_bytes": crop_bytes,
                "_sort_identity": _canonical_hash(
                    {"kind": kind, "bbox": candidate_bbox, "anchor": anchor}
                ),
                "bbox": candidate_bbox,
                "container_path": container,
                "source_anchor": _source_anchor("pdf_geometry"),
                "region_kind": kind,
                "evidence_origin": "page_render_crop",
                "page_render_sha256": page_render_sha,
                "render_profile_sha256": profile_sha,
                "crop_sha256": crop_sha,
                "crop_relpath": crop_relpath,
                "crop_media_type": "image/png" if crop_sha is not None else None,
                "source_image_key": None,
                "source_object_id": None,
                "source_object_sha256": None,
                "source_object_media_type": None,
                "source_object_status": "render_only" if crop_sha is not None else "missing",
                "link_method": "render_region_only" if crop_sha is not None else "none",
                "match_evidence": [
                    "bbox_exact",
                    *(["page_render"] if crop_sha is not None else []),
                ],
                "placement_status": "page_bbox_verified",
                "understanding_status": "none",
                "retrieval_status": (
                    "eligible"
                    if crop_sha is not None and kind == "vector_diagram"
                    else "withheld"
                ),
                "nearby_title": _nearby_title(candidate.get("nearby_title")),
                "warnings": [] if kind != "ambiguous" else ["vector_classifier_unverified"],
            }
        )

    for index, placement in enumerate(placement_values):
        placement_bbox = _bbox(placement)
        candidates, evidence = _match_resource(placement, resource_values, limits)
        matched = candidates[0] if len(candidates) == 1 else None
        parents = [
            table
            for table in table_drafts
            if table["region_kind"] == "table" and _contains(table["bbox"], placement_bbox)
        ]
        warnings: list[str] = []
        if len(candidates) > 1:
            warnings.append("pdf_resource_match_ambiguous")
        elif not candidates:
            warnings.append("pdf_resource_match_missing")
        if len(parents) > 1:
            warnings.append("table_parent_ambiguous")

        explicit_kind = _explicit_region_kind(placement)
        if matched is None:
            kind = "ambiguous"
        elif len(parents) > 1:
            kind = "ambiguous"
        elif explicit_kind == "decorative":
            kind = "decorative"
        elif len(parents) == 1:
            kind = "table_child_image"
        elif bool(matched.get("is_inline")) or placement.get("is_inline") is True:
            kind = "inline_image"
        else:
            kind = "raster_image"

        supplied_crop, crop_sha, crop_relpath, page_render_sha, profile_sha = _candidate_png(
            placement, limits
        )
        if matched is None and not candidates and len(parents) <= 1 and supplied_crop is not None:
            if explicit_kind == "decorative":
                kind = "decorative"
            elif len(parents) == 1:
                kind = "table_child_image"
            elif placement.get("is_inline") is True:
                kind = "inline_image"
            else:
                kind = "raster_image"
        if supplied_crop is not None:
            evidence_origin = (
                "resource_and_page_crop"
                if matched is not None
                else "page_render_crop"
            )
            crop_bytes = supplied_crop
        elif matched is not None and isinstance(matched.get("canonical_sha256"), str):
            evidence_origin = "source_object"
            # A canonical source-object PNG is not a verified page-render crop.
            # Keep occurrence crop fields empty until the caller supplies a
            # page-render checksum, render profile and exact bbox crop together.
            crop_sha = None
            crop_relpath = None
            crop_bytes = None
        else:
            evidence_origin = "source_object" if matched is not None else "page_render_crop"
            crop_sha = None
            crop_relpath = None
            crop_bytes = None
        parent_token = (
            parents[0]["_token"]
            if len(parents) == 1 and kind == "table_child_image"
            else None
        )
        default_container = ["pdf", f"page:{page_number}"]
        if matched is not None:
            default_container.extend(["resource", *list(matched["resource_path"])])
        else:
            default_container.append(f"placement:{index}")
        if parent_token is not None:
            default_container.extend(["table-child", str(parent_token)])
        container = _container_path(placement.get("container_path"), default=default_container)
        exact = matched is not None
        match_evidence = sorted(
            set(
                [
                    *evidence,
                    *(["unique_candidate"] if exact else []),
                    *(["bbox_exact", "page_render"] if supplied_crop is not None else []),
                ]
            )
        )
        if exact:
            source_status = "exact_resource_link"
            link_method = "document_resource_key"
        elif candidates or len(parents) > 1:
            source_status = "ambiguous"
            link_method = "none"
        elif supplied_crop is not None:
            source_status = "render_only"
            link_method = "render_region_only"
        else:
            source_status = "missing"
            link_method = "none"
        retrieval_status = (
            "eligible"
            if supplied_crop is not None
            and source_status not in {"ambiguous", "unsupported"}
            and kind not in {"ambiguous", "decorative"}
            else "withheld"
        )
        anchor_kind = "pdf_resource" if exact else "pdf_geometry"
        drafts.append(
            {
                "_token": "pdf-placement:"
                + _canonical_hash(
                    {"bbox": placement_bbox, "index": index, "container": container}
                )[:24],
                "_parent_token": parent_token,
                "_crop_bytes": crop_bytes,
                "_sort_identity": _canonical_hash(
                    {
                        "kind": kind,
                        "bbox": placement_bbox,
                        "container": container,
                        "resource_id": matched.get("resource_id") if matched is not None else None,
                    }
                ),
                "bbox": placement_bbox,
                "container_path": container,
                "source_anchor": _source_anchor(anchor_kind),
                "region_kind": kind,
                "evidence_origin": evidence_origin,
                "page_render_sha256": page_render_sha,
                "render_profile_sha256": profile_sha,
                "crop_sha256": crop_sha,
                "crop_relpath": crop_relpath,
                "crop_media_type": "image/png" if crop_sha is not None else None,
                "source_image_key": (
                    matched.get("source_image_key") if matched is not None else None
                ),
                "source_object_id": (
                    matched.get("source_object_id") if matched is not None else None
                ),
                "source_object_sha256": (
                    matched.get("source_object_sha256")
                    if matched is not None
                    else None
                ),
                "source_object_media_type": (
                    matched.get("source_object_media_type")
                    if matched is not None
                    else None
                ),
                "source_object_status": source_status,
                "link_method": link_method,
                "match_evidence": match_evidence,
                "placement_status": "page_bbox_verified",
                "understanding_status": "none",
                "retrieval_status": retrieval_status,
                "nearby_title": _nearby_title(placement.get("nearby_title")),
                "warnings": warnings,
            }
        )

    drafts.sort(key=_draft_sort_key)
    token_to_occurrence: dict[str, str] = {}
    for sequence, draft in enumerate(drafts):
        occurrence_id = _occurrence_id(
            doc_id=doc_id,
            source_sha256=source_sha256,
            page=page_number,
            bbox=draft["bbox"],
            region_kind=str(draft["region_kind"]),
            container_path=draft["container_path"],
            sequence=sequence,
        )
        if occurrence_id in token_to_occurrence.values():
            _raise("pdf_visual_v2_occurrence_identity_collision")
        token_to_occurrence[str(draft["_token"])] = occurrence_id
        draft["_occurrence_id"] = occurrence_id
        draft["_sequence"] = sequence

    occurrences: list[dict[str, Any]] = []
    for draft in drafts:
        parent_token = draft["_parent_token"]
        parent_occurrence_id = token_to_occurrence.get(str(parent_token)) if parent_token else None
        record = {
            "schema_version": PDF_VISUAL_V2_SCHEMA_VERSION,
            "occurrence_id": draft["_occurrence_id"],
            "doc_id": doc_id,
            "source_sha256": source_sha256,
            "page": page_number,
            "bbox": draft["bbox"],
            "coordinate_space": PDF_COORDINATE_SPACE,
            "sequence_in_page": draft["_sequence"],
            "container_path": draft["container_path"],
            "source_anchor": draft["source_anchor"],
            "region_kind": draft["region_kind"],
            "evidence_origin": draft["evidence_origin"],
            "page_render_sha256": draft["page_render_sha256"],
            "render_profile_sha256": draft["render_profile_sha256"],
            "crop_sha256": draft["crop_sha256"],
            "crop_relpath": draft["crop_relpath"],
            "crop_media_type": draft["crop_media_type"],
            "parent_occurrence_id": parent_occurrence_id,
            "source_image_key": draft["source_image_key"],
            "source_object_id": draft["source_object_id"],
            "source_object_sha256": draft["source_object_sha256"],
            "source_object_media_type": draft["source_object_media_type"],
            "source_object_status": draft["source_object_status"],
            "link_method": draft["link_method"],
            "match_evidence": draft["match_evidence"],
            "placement_status": draft["placement_status"],
            "understanding_status": draft["understanding_status"],
            "retrieval_status": draft["retrieval_status"],
            "nearby_title": draft["nearby_title"],
            "warnings": sorted({_safe_warning(value) for value in draft["warnings"]}),
        }
        try:
            validate_visual_occurrence(record)
        except ValueError:
            _raise("pdf_visual_v2_output_contract_invalid")
        occurrences.append(record)
    return occurrences


def recover_pdf_visual_page(
    *,
    page: Any,
    doc_id: str,
    source_sha256: str,
    page_number: int,
    placements: Sequence[Mapping[str, Any]],
    table_candidates: Sequence[Mapping[str, Any]] = (),
    vector_candidates: Sequence[Mapping[str, Any]] = (),
    limits: PdfVisualV2Limits = DEFAULT_PDF_VISUAL_V2_LIMITS,
) -> PdfVisualPageRecovery:
    resources = collect_pypdf_image_resources(
        page,
        doc_id=doc_id,
        source_sha256=source_sha256,
        page_number=page_number,
        limits=limits,
    )
    occurrences = reconcile_pdf_visual_occurrences(
        doc_id=doc_id,
        source_sha256=source_sha256,
        page_number=page_number,
        resources=resources,
        placements=placements,
        table_candidates=table_candidates,
        vector_candidates=vector_candidates,
        limits=limits,
    )
    return PdfVisualPageRecovery(tuple(resources), tuple(occurrences))


def _default_dependency_versions() -> dict[str, str]:
    result = {"placement_adapter": "supplied-records-v1"}
    for distribution in ("pypdf", "Pillow"):
        try:
            result[distribution] = version(distribution)
        except PackageNotFoundError:
            result[distribution] = "unavailable"
    return dict(sorted(result.items()))


def _dependency_versions(value: Mapping[str, Any] | None) -> dict[str, str]:
    raw = _default_dependency_versions() if value is None else value
    if not isinstance(raw, Mapping) or not raw:
        _raise("pdf_visual_v2_dependency_versions_invalid")
    result: dict[str, str] = {}
    for key, item in raw.items():
        if (
            not isinstance(key, str)
            or not key
            or len(key) > 128
            or not isinstance(item, str)
            or not item
            or len(item) > 256
        ):
            _raise("pdf_visual_v2_dependency_versions_invalid")
        result[key] = item
    return dict(sorted(result.items()))


def _private_output_dir(output_dir: Path, private_root: Path) -> tuple[Path, Path]:
    if (
        not isinstance(private_root, Path)
        or not private_root.is_absolute()
        or not private_root.is_dir()
        or private_root.is_symlink()
    ):
        _raise("pdf_visual_v2_private_root_invalid")
    resolved_root = private_root.resolve(strict=True)
    if not isinstance(output_dir, Path) or not output_dir.is_absolute():
        _raise("pdf_visual_v2_output_dir_invalid")
    resolved_output = output_dir.resolve(strict=False)
    if resolved_output == resolved_root or not resolved_output.is_relative_to(resolved_root):
        _raise("pdf_visual_v2_output_outside_private_root")
    relative = resolved_output.relative_to(resolved_root)
    current = resolved_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            _raise("pdf_visual_v2_output_outside_private_root")
    if output_dir.exists() and (output_dir.is_symlink() or not output_dir.is_dir()):
        _raise("pdf_visual_v2_output_dir_invalid")
    return resolved_root, resolved_output


def _asset_relpath(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        _raise("pdf_visual_v2_asset_path_invalid")
    return path


def _add_payload(
    payloads: dict[str, tuple[bytes, str, set[str]]],
    relpath: str,
    data: bytes,
    media_type: str,
    role: str,
) -> None:
    _asset_relpath(relpath)
    existing = payloads.get(relpath)
    if existing is not None:
        if existing[0] != data or existing[1] != media_type:
            _raise("pdf_visual_v2_asset_identity_collision")
        existing[2].add(role)
        return
    payloads[relpath] = (data, media_type, {role})


def _artifact_text_hash(rows: Sequence[Mapping[str, Any]]) -> str:
    return sha256_text("".join(canonical_json(row) + "\n" for row in rows))


def _status_counts(
    occurrences: Sequence[Mapping[str, Any]], resource_count: int
) -> dict[str, int]:
    counts: dict[str, int] = {"pdf_resources": resource_count}
    for prefix, field, values in (
        ("region", "region_kind", _REGION_KINDS),
        ("source", "source_object_status", _SOURCE_STATUSES),
        ("retrieval", "retrieval_status", _RETRIEVAL_STATUSES),
    ):
        actual = Counter(str(row.get(field, "")) for row in occurrences)
        for value in values:
            counts[f"{prefix}.{value}"] = actual[value]
    return dict(sorted(counts.items()))


def _read_json_object(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        _raise(code)
    if not isinstance(value, dict):
        _raise(code)
    return value


def _verify_existing(
    output_dir: Path,
    expected_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    metadata_path = output_dir / METADATA_ARTIFACT
    if not metadata_path.is_file() or metadata_path.is_symlink():
        _raise("pdf_visual_v2_stale_artifact_identity")
    metadata = _read_json_object(metadata_path, "pdf_visual_v2_stale_artifact_identity")
    identity_fields = (
        "schema_version",
        "method",
        "source_manifest_sha256",
        "adapter_code_sha256",
        "config_sha256",
        "dependency_versions",
    )
    if any(metadata.get(field) != expected_metadata.get(field) for field in identity_fields):
        _raise("pdf_visual_v2_stale_artifact_identity")
    if metadata != dict(expected_metadata):
        _raise("pdf_visual_v2_stale_artifact_identity")
    artifact_files = {
        "occurrences_v2_jsonl": OCCURRENCE_ARTIFACT,
        "pdf_resources_v2_jsonl": RESOURCE_ARTIFACT,
        "object_manifest_v2_jsonl": OBJECT_MANIFEST_ARTIFACT,
    }
    for key, filename in artifact_files.items():
        path = output_dir / filename
        if (
            not path.is_file()
            or path.is_symlink()
            or sha256_file(path) != metadata["artifact_hashes"].get(key)
        ):
            _raise("pdf_visual_v2_artifact_reconciliation_failed")
    try:
        manifest_rows = [
            json.loads(line)
            for line in (output_dir / OBJECT_MANIFEST_ARTIFACT).read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
    except (OSError, UnicodeError, json.JSONDecodeError):
        _raise("pdf_visual_v2_artifact_reconciliation_failed")
    for row in manifest_rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("relpath"), str):
            _raise("pdf_visual_v2_artifact_reconciliation_failed")
        relative = _asset_relpath(str(row["relpath"]))
        path = output_dir.joinpath(*relative.parts)
        if (
            not path.is_file()
            or path.is_symlink()
            or sha256_file(path) != row.get("sha256")
            or path.stat().st_size != row.get("byte_size")
        ):
            _raise("pdf_visual_v2_artifact_reconciliation_failed")
    return metadata


def materialize_pdf_visual_v2_corpus(
    *,
    documents: Sequence[Mapping[str, Any]],
    output_dir: Path,
    private_root: Path,
    source_manifest_sha256: str,
    adapter_code_sha256: str,
    config_sha256: str,
    dependency_versions: Mapping[str, Any] | None = None,
    expected_existing_artifact_set_id: str | None = None,
    limits: PdfVisualV2Limits = DEFAULT_PDF_VISUAL_V2_LIMITS,
) -> dict[str, Any]:
    """Recover and atomically publish a bounded PDF visual v2 corpus.

    Each document mapping contains ``doc_id``, ``source_sha256`` and ``pages``.
    Each page mapping contains ``page_number``, ``pypdf_page`` (or
    ``page_object``), and supplied ``placements`` plus optional
    ``table_candidates`` and ``vector_candidates``.  Existing output is never
    overwritten: reuse requires exact input identity and output reconciliation.
    """

    source_manifest_sha256 = _require_sha256(
        source_manifest_sha256, "pdf_visual_v2_source_manifest_sha256_invalid"
    )
    adapter_code_sha256 = _require_sha256(
        adapter_code_sha256, "pdf_visual_v2_adapter_code_sha256_invalid"
    )
    config_sha256 = _require_sha256(
        config_sha256, "pdf_visual_v2_config_sha256_invalid"
    )
    versions = _dependency_versions(dependency_versions)
    document_values = _require_sequence(
        documents, "pdf_visual_v2_documents_invalid", limits.max_documents
    )
    resolved_root, resolved_output = _private_output_dir(output_dir, private_root)

    all_resources: list[PdfImageResource] = []
    all_occurrences: list[dict[str, Any]] = []
    seen_docs: set[str] = set()
    total_asset_input_bytes = 0
    normalized_documents: list[tuple[str, str, list[Mapping[str, Any]]]] = []
    total_pages = 0
    for raw_document in document_values:
        if not isinstance(raw_document, Mapping):
            _raise("pdf_visual_v2_document_invalid")
        doc_id = _require_doc_id(raw_document.get("doc_id"))
        if doc_id in seen_docs:
            _raise("pdf_visual_v2_document_duplicate")
        seen_docs.add(doc_id)
        source_sha256 = _require_sha256(
            raw_document.get("source_sha256"),
            "pdf_visual_v2_source_sha256_invalid",
        )
        pages = _require_sequence(
            raw_document.get("pages"),
            "pdf_visual_v2_pages_invalid",
            limits.max_pages_per_document,
        )
        if any(not isinstance(page, Mapping) for page in pages):
            _raise("pdf_visual_v2_page_input_invalid")
        total_pages += len(pages)
        if total_pages > limits.max_total_pages:
            _raise("pdf_visual_v2_total_pages_exceeded")
        normalized_documents.append((doc_id, source_sha256, pages))

    for doc_id, source_sha256, pages in sorted(normalized_documents):
        seen_pages: set[int] = set()
        sorted_pages: list[tuple[int, Mapping[str, Any]]] = []
        for raw_page in pages:
            page_number = raw_page.get("page_number", raw_page.get("page"))
            if (
                not isinstance(page_number, int)
                or isinstance(page_number, bool)
                or not 1 <= page_number <= limits.max_pages_per_document
                or page_number in seen_pages
            ):
                _raise("pdf_visual_v2_page_input_invalid")
            seen_pages.add(page_number)
            sorted_pages.append((page_number, raw_page))
        for page_number, raw_page in sorted(sorted_pages):
            pypdf_page = raw_page.get("pypdf_page", raw_page.get("page_object"))
            if pypdf_page is None:
                _raise("pdf_visual_v2_pypdf_page_invalid")
            recovery = recover_pdf_visual_page(
                page=pypdf_page,
                doc_id=doc_id,
                source_sha256=source_sha256,
                page_number=page_number,
                placements=raw_page.get("placements", raw_page.get("image_placements", ())),
                table_candidates=raw_page.get("table_candidates", raw_page.get("tables", ())),
                vector_candidates=raw_page.get("vector_candidates", raw_page.get("vectors", ())),
                limits=limits,
            )
            all_resources.extend(recovery.resources)
            all_occurrences.extend(recovery.occurrences)
            if len(all_occurrences) > limits.max_total_occurrences:
                _raise("pdf_visual_v2_total_occurrences_exceeded")
            total_asset_input_bytes += sum(
                len(resource.source_bytes)
                + (len(resource.canonical_bytes) if resource.canonical_bytes else 0)
                + sum(len(data) for _, data in resource.mask_payloads)
                for resource in recovery.resources
            )
            if total_asset_input_bytes > limits.max_total_asset_bytes:
                _raise("pdf_visual_v2_total_asset_bytes_exceeded")

    resource_records = [resource.as_record() for resource in all_resources]
    resource_records.sort(
        key=lambda row: (str(row["doc_id"]), int(row["page"]), str(row["resource_id"]))
    )
    all_occurrences.sort(
        key=lambda row: (
            str(row["doc_id"]),
            int(row["page"]),
            int(row["sequence_in_page"]),
            str(row["occurrence_id"]),
        )
    )

    payloads: dict[str, tuple[bytes, str, set[str]]] = {}
    for resource in all_resources:
        for relpath, data, media_type, role in resource.asset_payloads():
            _add_payload(payloads, relpath, data, media_type, role)
    # Supplied page-render crops are carried only in reconciliation drafts, so
    # recover them deterministically from the input records here.
    for _, _, pages in sorted(normalized_documents):
        for _, raw_page in sorted(
            (
                (int(page.get("page_number", page.get("page"))), page)
                for page in pages
            ),
            key=lambda item: item[0],
        ):
            for collection_name, fallback in (
                ("placements", "image_placements"),
                ("table_candidates", "tables"),
                ("vector_candidates", "vectors"),
            ):
                values = raw_page.get(collection_name, raw_page.get(fallback, ()))
                for candidate in _require_sequence(
                    values,
                    "pdf_visual_v2_geometry_record_invalid",
                    limits.max_regions_per_page,
                ):
                    if isinstance(candidate, Mapping) and candidate.get("crop_bytes") is not None:
                        crop_bytes, crop_sha, crop_relpath, _, _ = _candidate_png(candidate, limits)
                        if (
                            crop_bytes is None
                            or crop_sha is None
                            or crop_relpath is None
                        ):
                            _raise("pdf_visual_v2_crop_bytes_invalid")
                        _add_payload(
                            payloads,
                            crop_relpath,
                            crop_bytes,
                            "image/png",
                            "page_render_crop",
                        )

    if sum(len(value[0]) for value in payloads.values()) > limits.max_total_asset_bytes:
        _raise("pdf_visual_v2_total_asset_bytes_exceeded")
    object_manifest = [
        {
            "relpath": relpath,
            "sha256": sha256_bytes(data),
            "byte_size": len(data),
            "media_type": media_type,
            "roles": sorted(roles),
        }
        for relpath, (data, media_type, roles) in sorted(payloads.items())
    ]
    artifact_hashes = {
        "object_manifest_v2_jsonl": _artifact_text_hash(object_manifest),
        "occurrences_v2_jsonl": _artifact_text_hash(all_occurrences),
        "pdf_resources_v2_jsonl": _artifact_text_hash(resource_records),
    }
    identity = {
        "source_manifest_sha256": source_manifest_sha256,
        "adapter_code_sha256": adapter_code_sha256,
        "config_sha256": config_sha256,
        "dependency_versions": versions,
        "artifact_hashes": artifact_hashes,
    }
    metadata = {
        "schema_version": PDF_VISUAL_V2_SCHEMA_VERSION,
        "artifact_set_id": "visualv2_" + _canonical_hash(identity)[:24],
        "method": PDF_VISUAL_V2_METHOD,
        "source_manifest_sha256": source_manifest_sha256,
        "adapter_code_sha256": adapter_code_sha256,
        "config_sha256": config_sha256,
        "dependency_versions": versions,
        "document_count": len(normalized_documents),
        "occurrence_count": len(all_occurrences),
        "ocr_count": 0,
        "caption_count": 0,
        "chunk_count": 0,
        "status_counts": _status_counts(all_occurrences, len(resource_records)),
        "artifact_hashes": artifact_hashes,
        "external_api_calls": 0,
        "private_egress": False,
        "strict_reuse_eligible": True,
    }
    if expected_existing_artifact_set_id is not None and (
        not isinstance(expected_existing_artifact_set_id, str)
        or expected_existing_artifact_set_id != metadata["artifact_set_id"]
    ):
        _raise("pdf_visual_v2_stale_artifact_identity")
    if resolved_output.exists():
        return _verify_existing(resolved_output, metadata)

    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    _, rechecked_output = _private_output_dir(resolved_output, resolved_root)
    if rechecked_output.exists():
        return _verify_existing(rechecked_output, metadata)
    try:
        with tempfile.TemporaryDirectory(
            prefix=".pdf-visual-v2-stage-",
            dir=rechecked_output.parent,
            ignore_cleanup_errors=True,
        ) as stage_name:
            stage = Path(stage_name)
            write_jsonl(stage / RESOURCE_ARTIFACT, resource_records)
            write_jsonl(stage / OCCURRENCE_ARTIFACT, all_occurrences)
            write_jsonl(stage / OBJECT_MANIFEST_ARTIFACT, object_manifest)
            for relpath, (data, _, _) in payloads.items():
                relative = _asset_relpath(relpath)
                destination = stage.joinpath(*relative.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
                if sha256_file(destination) != sha256_bytes(data):
                    _raise("pdf_visual_v2_publish_failed")
            write_json(stage / METADATA_ARTIFACT, metadata)
            if (
                sha256_file(stage / RESOURCE_ARTIFACT)
                != artifact_hashes["pdf_resources_v2_jsonl"]
                or sha256_file(stage / OCCURRENCE_ARTIFACT)
                != artifact_hashes["occurrences_v2_jsonl"]
                or sha256_file(stage / OBJECT_MANIFEST_ARTIFACT)
                != artifact_hashes["object_manifest_v2_jsonl"]
            ):
                _raise("pdf_visual_v2_publish_failed")
            if rechecked_output.exists():
                return _verify_existing(rechecked_output, metadata)
            os.rename(stage, rechecked_output)
    except PdfVisualV2Error:
        raise
    except OSError:
        _raise("pdf_visual_v2_publish_failed")
    return _verify_existing(rechecked_output, metadata)


__all__ = [
    "DEFAULT_PDF_VISUAL_V2_LIMITS",
    "METADATA_ARTIFACT",
    "OBJECT_MANIFEST_ARTIFACT",
    "OCCURRENCE_ARTIFACT",
    "PDF_COORDINATE_SPACE",
    "PDF_VISUAL_V2_METHOD",
    "PDF_VISUAL_V2_SCHEMA_VERSION",
    "RESOURCE_ARTIFACT",
    "PdfImageResource",
    "PdfVisualPageRecovery",
    "PdfVisualV2Error",
    "PdfVisualV2Limits",
    "collect_pypdf_image_resources",
    "inventory_pypdf_page_resources",
    "materialize_pdf_visual_v2_corpus",
    "reconcile_pdf_visual_occurrences",
    "recover_pdf_visual_page",
]
