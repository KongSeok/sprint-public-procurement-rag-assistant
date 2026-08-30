"""Pure, additive HWP visual-v2 occurrence recovery.

The optional helper emits strict JSON/JSONL render rows containing a 1-based
page, CSS-pixel bbox, sequence, document-local source key and exact HWP source
anchor.  Keyless rows may additionally carry an embedded raw digest or a
normalized RGBA digest plus the independently reconciled bbox.  Source-object
inventory rows remain separate, so one resource key can serve many placements
and unused or unsupported objects remain explicit document-only evidence.

Helper rows use ``source_resource_sha256`` for bytes fetched by the stable key
and ``embedded_raw_sha256``/``normalized_rgba_sha256`` for visual fallback.
Source inventory rows provide ``source_ordinal``, ``source_image_key``, content
SHA, MIME, optional RGBA SHA, ``supported`` and an optional source anchor.

This module does not invoke rhwp, decode images, crop pages, mutate v1 records,
or perform OCR.  Those boundaries let callers pin the helper/decoder/renderer
while this layer remains deterministic and network-free.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from midprojectrag.ingest.common import canonical_json, require_sha256
from midprojectrag.ingest.visual_evidence import (
    occurrence_id as visual_occurrence_id,
    source_object_id as visual_source_object_id,
    validate_visual_occurrence,
)


VISUAL_OCCURRENCE_SCHEMA_VERSION = "2.0"
HWP_HELPER_SCHEMA_VERSION = "1.0"
COORDINATE_SPACE = "rhwp_css_px_96dpi"

MAX_HELPER_BYTES = 16 * 1024 * 1024
MAX_OCCURRENCES = 100_000
MAX_SOURCE_OBJECTS = 100_000
MAX_PAGE = 10_000
MAX_INDEX = 2_147_483_647
MAX_CONTAINER_DEPTH = 64
MAX_CELL_PATH_DEPTH = 32
MAX_KEY_CHARS = 256

_DOC_ID_PATTERN = re.compile(r"^doc_[0-9a-f]{24}$")
_BLOCK_ID_PATTERN = re.compile(r"^block_[0-9a-f]{24}$")
_MEDIA_TYPE_PATTERN = re.compile(r"^(?:image|application)/[A-Za-z0-9.+-]+$")
_BBOX_FIELDS = frozenset({"x", "y", "w", "h"})
_SOURCE_ANCHOR_FIELDS = frozenset(
    {
        "kind",
        "section_index",
        "paragraph_index",
        "control_index",
        "table_block_id",
        "cell_path",
    }
)
_CELL_PATH_FIELDS = frozenset(
    {
        "control_index",
        "cell_index",
        "cell_paragraph_index",
        "row",
        "column",
    }
)
_HELPER_FIELDS = frozenset(
    {
        "schema_version",
        "doc_id",
        "render_occurrence_key",
        "page",
        "bbox",
        "coordinate_space",
        "sequence_in_page",
        "source_image_key",
        "source_resource_sha256",
        "embedded_raw_sha256",
        "normalized_rgba_sha256",
        "match_bbox",
        "source_anchor",
    }
)
_SOURCE_OBJECT_FIELDS = frozenset(
    {
        "schema_version",
        "doc_id",
        "source_ordinal",
        "source_image_key",
        "source_object_sha256",
        "source_object_media_type",
        "normalized_rgba_sha256",
        "supported",
        "source_anchor",
    }
)
_V2_FIELDS = frozenset(
    {
        "schema_version",
        "occurrence_id",
        "doc_id",
        "source_sha256",
        "page",
        "bbox",
        "coordinate_space",
        "sequence_in_page",
        "container_path",
        "source_anchor",
        "region_kind",
        "evidence_origin",
        "page_render_sha256",
        "render_profile_sha256",
        "crop_sha256",
        "crop_relpath",
        "crop_media_type",
        "parent_occurrence_id",
        "source_image_key",
        "source_object_id",
        "source_object_sha256",
        "source_object_media_type",
        "source_object_status",
        "link_method",
        "match_evidence",
        "placement_status",
        "understanding_status",
        "retrieval_status",
        "nearby_title",
        "warnings",
    }
)


class HwpVisualV2Error(ValueError):
    """A stable, content-free HWP visual-v2 contract error."""


def _is_integer(
    value: Any, *, minimum: int = 0, maximum: int = MAX_INDEX
) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and minimum <= value <= maximum
    )


def _require_doc_id(value: Any) -> str:
    if not isinstance(value, str) or _DOC_ID_PATTERN.fullmatch(value) is None:
        raise HwpVisualV2Error("hwp_visual_v2_doc_id_invalid")
    return value


def _require_digest(value: Any, error_code: str) -> str:
    try:
        return require_sha256(value, error_code)
    except ValueError:
        raise HwpVisualV2Error(error_code) from None


def _optional_digest(value: Any, error_code: str) -> str | None:
    if value is None:
        return None
    return _require_digest(value, error_code)


def _optional_nonnegative_integer(value: Any, error_code: str) -> int | None:
    if value is None:
        return None
    if not _is_integer(value):
        raise HwpVisualV2Error(error_code)
    return value


def _normalize_number(value: Any, error_code: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        raise HwpVisualV2Error(error_code)
    normalized = round(float(value), 6)
    return 0.0 if normalized == 0 else normalized


def _normalize_bbox(value: Any, error_code: str) -> dict[str, float]:
    if not isinstance(value, Mapping) or set(value) != _BBOX_FIELDS:
        raise HwpVisualV2Error(error_code)
    result = {
        field: _normalize_number(value.get(field), error_code)
        for field in ("x", "y", "w", "h")
    }
    if result["w"] <= 0 or result["h"] <= 0:
        raise HwpVisualV2Error(error_code)
    return result


def _bbox_key(value: Mapping[str, float]) -> tuple[float, float, float, float]:
    return tuple(value[field] for field in ("x", "y", "w", "h"))  # type: ignore[return-value]


def _normalize_key(value: Any, error_code: str) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_KEY_CHARS
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise HwpVisualV2Error(error_code)
    return value


def _normalize_cell_path(value: Any) -> list[dict[str, int | None]]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or len(value) > MAX_CELL_PATH_DEPTH
    ):
        raise HwpVisualV2Error("hwp_visual_v2_cell_path_invalid")
    result: list[dict[str, int | None]] = []
    for segment in value:
        if not isinstance(segment, Mapping) or set(segment) != _CELL_PATH_FIELDS:
            raise HwpVisualV2Error("hwp_visual_v2_cell_path_invalid")
        control_index = segment.get("control_index")
        cell_index = segment.get("cell_index")
        cell_paragraph_index = segment.get("cell_paragraph_index")
        if not all(
            _is_integer(item)
            for item in (control_index, cell_index, cell_paragraph_index)
        ):
            raise HwpVisualV2Error("hwp_visual_v2_cell_path_invalid")
        result.append(
            {
                "control_index": control_index,
                "cell_index": cell_index,
                "cell_paragraph_index": cell_paragraph_index,
                "row": _optional_nonnegative_integer(
                    segment.get("row"), "hwp_visual_v2_cell_path_invalid"
                ),
                "column": _optional_nonnegative_integer(
                    segment.get("column"), "hwp_visual_v2_cell_path_invalid"
                ),
            }
        )
    return result


def _normalize_source_anchor(
    value: Any, *, optional: bool = False
) -> dict[str, Any] | None:
    if value is None and optional:
        return None
    if not isinstance(value, Mapping) or set(value) != _SOURCE_ANCHOR_FIELDS:
        raise HwpVisualV2Error("hwp_visual_v2_source_anchor_invalid")
    kind = value.get("kind")
    table_block_id = value.get("table_block_id")
    if kind not in {"body", "table_nested"}:
        raise HwpVisualV2Error("hwp_visual_v2_source_anchor_invalid")
    if table_block_id is not None and (
        not isinstance(table_block_id, str)
        or _BLOCK_ID_PATTERN.fullmatch(table_block_id) is None
    ):
        raise HwpVisualV2Error("hwp_visual_v2_source_anchor_invalid")
    cell_path = _normalize_cell_path(value.get("cell_path"))
    if kind == "body" and (table_block_id is not None or cell_path):
        raise HwpVisualV2Error("hwp_visual_v2_source_anchor_invalid")
    if kind == "table_nested" and (table_block_id is None or not cell_path):
        raise HwpVisualV2Error("hwp_visual_v2_source_anchor_invalid")
    return {
        "kind": kind,
        "section_index": _optional_nonnegative_integer(
            value.get("section_index"), "hwp_visual_v2_source_anchor_invalid"
        ),
        "paragraph_index": _optional_nonnegative_integer(
            value.get("paragraph_index"), "hwp_visual_v2_source_anchor_invalid"
        ),
        "control_index": _optional_nonnegative_integer(
            value.get("control_index"), "hwp_visual_v2_source_anchor_invalid"
        ),
        "table_block_id": table_block_id,
        "cell_path": cell_path,
    }


def _container_path(anchor: Mapping[str, Any] | None) -> list[str]:
    if anchor is None:
        return []
    location = [
        f"section:{'null' if anchor['section_index'] is None else anchor['section_index']}",
        f"paragraph:{'null' if anchor['paragraph_index'] is None else anchor['paragraph_index']}",
        f"control:{'null' if anchor['control_index'] is None else anchor['control_index']}",
    ]
    if anchor["kind"] == "body":
        return ["body", *location]
    path = [f"table:{anchor['table_block_id']}", *location]
    for segment in anchor["cell_path"]:
        row = "null" if segment["row"] is None else str(segment["row"])
        column = "null" if segment["column"] is None else str(segment["column"])
        path.append(
            "cell:"
            f"{segment['control_index']}:"
            f"{segment['cell_index']}:"
            f"{segment['cell_paragraph_index']}:"
            f"{row}:{column}"
        )
    if len(path) > MAX_CONTAINER_DEPTH:
        raise HwpVisualV2Error("hwp_visual_v2_container_path_invalid")
    return path


def _source_object_id(digest: str) -> str:
    # The source-object identity is intentionally content-only and global.
    return visual_source_object_id(digest)


def _helper_rows_from_payload(payload: Any) -> list[Any]:
    if payload is None:
        return []
    decoded: Any = payload
    if isinstance(payload, (bytes, bytearray)):
        if len(payload) > MAX_HELPER_BYTES:
            raise HwpVisualV2Error("hwp_visual_v2_helper_size_exceeded")
        try:
            decoded = bytes(payload).decode("utf-8")
        except UnicodeDecodeError:
            raise HwpVisualV2Error("hwp_visual_v2_helper_utf8_invalid") from None
    if isinstance(decoded, str):
        if len(decoded.encode("utf-8")) > MAX_HELPER_BYTES:
            raise HwpVisualV2Error("hwp_visual_v2_helper_size_exceeded")
        if not decoded.strip():
            raise HwpVisualV2Error("hwp_visual_v2_helper_json_invalid")
        try:
            decoded = json.loads(decoded)
        except (json.JSONDecodeError, RecursionError):
            rows: list[Any] = []
            try:
                for line in decoded.splitlines():
                    if line.strip():
                        rows.append(json.loads(line))
            except (json.JSONDecodeError, RecursionError):
                raise HwpVisualV2Error("hwp_visual_v2_helper_json_invalid") from None
            decoded = rows
    if isinstance(decoded, Mapping):
        if set(decoded) == {"schema_version", "occurrences"}:
            if decoded.get("schema_version") != HWP_HELPER_SCHEMA_VERSION:
                raise HwpVisualV2Error("hwp_visual_v2_helper_schema_invalid")
            decoded = decoded.get("occurrences")
        else:
            decoded = [decoded]
    if (
        not isinstance(decoded, Sequence)
        or isinstance(decoded, (str, bytes, bytearray))
    ):
        raise HwpVisualV2Error("hwp_visual_v2_helper_json_invalid")
    if len(decoded) > MAX_OCCURRENCES:
        raise HwpVisualV2Error("hwp_visual_v2_occurrence_limit_exceeded")
    return list(decoded)


def _normalize_helper_row(value: Any, doc_id: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _HELPER_FIELDS:
        raise HwpVisualV2Error("hwp_visual_v2_helper_record_invalid")
    if (
        value.get("schema_version") != HWP_HELPER_SCHEMA_VERSION
        or value.get("doc_id") != doc_id
    ):
        raise HwpVisualV2Error("hwp_visual_v2_helper_record_invalid")
    render_occurrence_key = _normalize_key(
        value.get("render_occurrence_key"),
        "hwp_visual_v2_render_occurrence_key_invalid",
    )
    if render_occurrence_key is None:
        raise HwpVisualV2Error("hwp_visual_v2_render_occurrence_key_invalid")
    page = value.get("page")
    sequence_in_page = value.get("sequence_in_page")
    if (
        not _is_integer(page, minimum=1, maximum=MAX_PAGE)
        or not _is_integer(sequence_in_page)
    ):
        raise HwpVisualV2Error("hwp_visual_v2_helper_placement_invalid")
    if value.get("coordinate_space") != COORDINATE_SPACE:
        raise HwpVisualV2Error("hwp_visual_v2_helper_placement_invalid")
    source_image_key = _normalize_key(
        value.get("source_image_key"), "hwp_visual_v2_source_image_key_invalid"
    )
    source_resource_sha256 = _optional_digest(
        value.get("source_resource_sha256"),
        "hwp_visual_v2_source_resource_sha256_invalid",
    )
    if source_image_key is not None and source_resource_sha256 is None:
        raise HwpVisualV2Error("hwp_visual_v2_source_resource_sha256_missing")
    embedded_raw_sha256 = _optional_digest(
        value.get("embedded_raw_sha256"),
        "hwp_visual_v2_embedded_raw_sha256_invalid",
    )
    normalized_rgba_sha256 = _optional_digest(
        value.get("normalized_rgba_sha256"),
        "hwp_visual_v2_normalized_rgba_sha256_invalid",
    )
    match_bbox_raw = value.get("match_bbox")
    match_bbox = (
        None
        if match_bbox_raw is None
        else _normalize_bbox(match_bbox_raw, "hwp_visual_v2_match_bbox_invalid")
    )
    if (
        embedded_raw_sha256 is not None or normalized_rgba_sha256 is not None
    ) and match_bbox is None:
        raise HwpVisualV2Error("hwp_visual_v2_match_bbox_missing")
    return {
        "schema_version": HWP_HELPER_SCHEMA_VERSION,
        "doc_id": doc_id,
        "render_occurrence_key": render_occurrence_key,
        "page": page,
        "bbox": _normalize_bbox(
            value.get("bbox"), "hwp_visual_v2_helper_bbox_invalid"
        ),
        "coordinate_space": COORDINATE_SPACE,
        "sequence_in_page": sequence_in_page,
        "source_image_key": source_image_key,
        "source_resource_sha256": source_resource_sha256,
        "embedded_raw_sha256": embedded_raw_sha256,
        "normalized_rgba_sha256": normalized_rgba_sha256,
        "match_bbox": match_bbox,
        "source_anchor": _normalize_source_anchor(value.get("source_anchor")),
    }


def parse_hwp_helper_occurrences(
    payload: Any, *, doc_id: str
) -> list[dict[str, Any]]:
    """Parse optional rhwp helper JSON/JSONL into strict normalized occurrences.

    ``None`` means that the optional helper is unavailable.  Non-null payloads
    fail closed.  Every helper row carries one exact render placement and an
    exact HWP source anchor.  A document-local ``source_image_key`` may repeat
    across any number of placements, but ``render_occurrence_key`` may not.
    """

    normalized_doc_id = _require_doc_id(doc_id)
    rows = [
        _normalize_helper_row(row, normalized_doc_id)
        for row in _helper_rows_from_payload(payload)
    ]
    seen_render_keys: set[str] = set()
    seen_placements: set[str] = set()
    for row in rows:
        render_key = row["render_occurrence_key"]
        if render_key in seen_render_keys:
            raise HwpVisualV2Error("hwp_visual_v2_render_occurrence_key_duplicate")
        seen_render_keys.add(render_key)
        placement_identity = canonical_json(
            {
                "page": row["page"],
                "bbox": row["bbox"],
                "sequence_in_page": row["sequence_in_page"],
                "source_anchor": row["source_anchor"],
            }
        )
        if placement_identity in seen_placements:
            raise HwpVisualV2Error("hwp_visual_v2_occurrence_identity_duplicate")
        seen_placements.add(placement_identity)
    rows.sort(
        key=lambda row: (
            row["page"],
            row["sequence_in_page"],
            _bbox_key(row["bbox"]),
            row["render_occurrence_key"],
        )
    )
    return rows


def _normalize_source_objects(
    values: Sequence[Mapping[str, Any]], doc_id: str
) -> list[dict[str, Any]]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise HwpVisualV2Error("hwp_visual_v2_source_objects_invalid")
    if len(values) > MAX_SOURCE_OBJECTS:
        raise HwpVisualV2Error("hwp_visual_v2_source_object_limit_exceeded")
    result: list[dict[str, Any]] = []
    seen_ordinals: set[int] = set()
    seen_keys: set[str] = set()
    for value in values:
        if not isinstance(value, Mapping) or set(value) != _SOURCE_OBJECT_FIELDS:
            raise HwpVisualV2Error("hwp_visual_v2_source_object_invalid")
        ordinal = value.get("source_ordinal")
        supported = value.get("supported")
        media_type = value.get("source_object_media_type")
        if (
            value.get("schema_version") != HWP_HELPER_SCHEMA_VERSION
            or value.get("doc_id") != doc_id
            or not _is_integer(ordinal)
            or ordinal in seen_ordinals
            or not isinstance(supported, bool)
            or not isinstance(media_type, str)
            or len(media_type) > 128
            or _MEDIA_TYPE_PATTERN.fullmatch(media_type) is None
        ):
            raise HwpVisualV2Error("hwp_visual_v2_source_object_invalid")
        seen_ordinals.add(ordinal)
        source_image_key = _normalize_key(
            value.get("source_image_key"), "hwp_visual_v2_source_image_key_invalid"
        )
        if source_image_key is not None:
            if source_image_key in seen_keys:
                raise HwpVisualV2Error("hwp_visual_v2_source_image_key_duplicate")
            seen_keys.add(source_image_key)
        source_digest = _require_digest(
            value.get("source_object_sha256"),
            "hwp_visual_v2_source_object_sha256_invalid",
        )
        result.append(
            {
                "schema_version": HWP_HELPER_SCHEMA_VERSION,
                "doc_id": doc_id,
                "source_ordinal": ordinal,
                "source_image_key": source_image_key,
                "source_object_id": _source_object_id(source_digest),
                "source_object_sha256": source_digest,
                "source_object_media_type": media_type,
                "normalized_rgba_sha256": _optional_digest(
                    value.get("normalized_rgba_sha256"),
                    "hwp_visual_v2_source_rgba_sha256_invalid",
                ),
                "supported": supported,
                "source_anchor": _normalize_source_anchor(
                    value.get("source_anchor"), optional=True
                ),
            }
        )
    result.sort(key=lambda item: item["source_ordinal"])
    return result


def _page_occurrence_id(
    *, source_sha256: str, occurrence: Mapping[str, Any]
) -> str:
    anchor = occurrence["source_anchor"]
    region_kind = (
        "table_child_image" if anchor["kind"] == "table_nested" else "raster_image"
    )
    return visual_occurrence_id(
        doc_id=occurrence["doc_id"],
        source_sha256=source_sha256,
        page=occurrence["page"],
        bbox=occurrence["bbox"],
        region_kind=region_kind,
        container_path=_container_path(anchor),
        sequence_in_page=occurrence["sequence_in_page"],
    )


def _source_only_container_path(source: Mapping[str, Any]) -> list[str]:
    path = _container_path(source["source_anchor"])
    path.append(f"source-reference:{source['source_ordinal']}")
    if len(path) > MAX_CONTAINER_DEPTH:
        raise HwpVisualV2Error("hwp_visual_v2_container_path_invalid")
    return path


def _source_only_occurrence_id(
    *, doc_id: str, source_sha256: str, source: Mapping[str, Any]
) -> str:
    anchor = source["source_anchor"]
    return visual_occurrence_id(
        doc_id=doc_id,
        source_sha256=source_sha256,
        page=None,
        bbox=None,
        region_kind=(
            "table_child_image"
            if anchor is not None and anchor["kind"] == "table_nested"
            else "raster_image"
        ),
        container_path=_source_only_container_path(source),
        sequence_in_page=None,
    )


def _page_record(
    *, doc_id: str, source_sha256: str, occurrence: Mapping[str, Any]
) -> dict[str, Any]:
    anchor = occurrence["source_anchor"]
    return {
        "schema_version": VISUAL_OCCURRENCE_SCHEMA_VERSION,
        "occurrence_id": _page_occurrence_id(
            source_sha256=source_sha256, occurrence=occurrence
        ),
        "doc_id": doc_id,
        "source_sha256": source_sha256,
        "page": occurrence["page"],
        "bbox": dict(occurrence["bbox"]),
        "coordinate_space": COORDINATE_SPACE,
        "sequence_in_page": occurrence["sequence_in_page"],
        "container_path": _container_path(anchor),
        "source_anchor": anchor,
        "region_kind": (
            "table_child_image"
            if anchor["kind"] == "table_nested"
            else "raster_image"
        ),
        "evidence_origin": "page_render_crop",
        "page_render_sha256": None,
        "render_profile_sha256": None,
        "crop_sha256": None,
        "crop_relpath": None,
        "crop_media_type": None,
        "parent_occurrence_id": None,
        "source_image_key": occurrence["source_image_key"],
        "source_object_id": None,
        "source_object_sha256": None,
        "source_object_media_type": None,
        "source_object_status": "render_only",
        "link_method": "render_region_only",
        "match_evidence": ["bbox_exact"],
        "placement_status": "page_bbox_verified",
        "understanding_status": "none",
        "retrieval_status": "withheld",
        "nearby_title": None,
        "warnings": [],
    }


def _attach_source(
    record: dict[str, Any],
    source: Mapping[str, Any],
    *,
    status: str,
    link_method: str,
    match_evidence: list[str],
) -> None:
    record.update(
        {
            "evidence_origin": "resource_and_page_crop",
            "source_image_key": source["source_image_key"],
            "source_object_id": source["source_object_id"],
            "source_object_sha256": source["source_object_sha256"],
            "source_object_media_type": source["source_object_media_type"],
            "source_object_status": status,
            "link_method": link_method,
            "match_evidence": match_evidence,
        }
    )


def _fallback_match(
    occurrence: Mapping[str, Any],
    sources: Sequence[Mapping[str, Any]],
) -> tuple[str, Mapping[str, Any] | None, list[str], list[str]]:
    match_bbox = occurrence["match_bbox"]
    raw_digest = occurrence["embedded_raw_sha256"]
    rgba_digest = occurrence["normalized_rgba_sha256"]
    if raw_digest is None and rgba_digest is None:
        return (
            "render_only",
            None,
            [],
            ["source_identity_evidence_missing"],
        )
    if match_bbox is None or _bbox_key(match_bbox) != _bbox_key(occurrence["bbox"]):
        warning = (
            "exact_visual_match_bbox_missing"
            if match_bbox is None
            else "exact_visual_match_bbox_mismatch"
        )
        return "render_only", None, ["bbox_exact"], [warning]

    supported_sources = [source for source in sources if source["supported"]]
    if raw_digest is not None:
        raw_candidates = [
            source
            for source in supported_sources
            if source["source_object_sha256"] == raw_digest
        ]
        if len(raw_candidates) == 1:
            return (
                "raw",
                raw_candidates[0],
                ["raw_sha256", "bbox_exact", "unique_candidate"],
                [],
            )
        if len(raw_candidates) > 1:
            return (
                "ambiguous",
                None,
                ["raw_sha256", "bbox_exact"],
                ["raw_sha256_candidate_ambiguous"],
            )

    if rgba_digest is not None:
        rgba_candidates = [
            source
            for source in supported_sources
            if source["normalized_rgba_sha256"] == rgba_digest
        ]
        if len(rgba_candidates) == 1:
            return (
                "rgba",
                rgba_candidates[0],
                ["normalized_rgba_sha256", "bbox_exact", "unique_candidate"],
                [],
            )
        if len(rgba_candidates) > 1:
            return (
                "ambiguous",
                None,
                ["normalized_rgba_sha256", "bbox_exact"],
                ["normalized_rgba_sha256_candidate_ambiguous"],
            )

    return (
        "render_only",
        None,
        ["bbox_exact"],
        ["source_object_exact_match_missing"],
    )


def _source_only_record(
    *, doc_id: str, source_sha256: str, source: Mapping[str, Any]
) -> dict[str, Any]:
    anchor = source["source_anchor"]
    warnings = ["source_object_without_render_occurrence"]
    if not source["supported"]:
        status = "unsupported"
        link_method = "none"
        match_evidence: list[str] = []
        retrieval_status = "quarantined"
        warnings.append("source_object_unsupported")
    elif source["source_image_key"] is not None:
        status = "exact_resource_link"
        link_method = "document_resource_key"
        match_evidence = ["document_resource_key"]
        retrieval_status = "withheld"
    else:
        status = "missing"
        link_method = "none"
        match_evidence = []
        retrieval_status = "withheld"
        warnings.append("source_image_key_missing")
    return {
        "schema_version": VISUAL_OCCURRENCE_SCHEMA_VERSION,
        "occurrence_id": _source_only_occurrence_id(
            doc_id=doc_id, source_sha256=source_sha256, source=source
        ),
        "doc_id": doc_id,
        "source_sha256": source_sha256,
        "page": None,
        "bbox": None,
        "coordinate_space": None,
        "sequence_in_page": None,
        "container_path": _source_only_container_path(source),
        "source_anchor": anchor,
        "region_kind": (
            "table_child_image"
            if anchor is not None and anchor["kind"] == "table_nested"
            else "raster_image"
        ),
        "evidence_origin": "source_object",
        "page_render_sha256": None,
        "render_profile_sha256": None,
        "crop_sha256": None,
        "crop_relpath": None,
        "crop_media_type": None,
        "parent_occurrence_id": None,
        "source_image_key": source["source_image_key"],
        "source_object_id": source["source_object_id"],
        "source_object_sha256": source["source_object_sha256"],
        "source_object_media_type": source["source_object_media_type"],
        "source_object_status": status,
        "link_method": link_method,
        "match_evidence": match_evidence,
        "placement_status": "doc_only_unlinked",
        "understanding_status": "none",
        "retrieval_status": retrieval_status,
        "nearby_title": None,
        "warnings": sorted(warnings),
    }


def link_hwp_source_objects(
    occurrences: Sequence[Mapping[str, Any]],
    source_objects: Sequence[Mapping[str, Any]],
    *,
    doc_id: str,
    source_sha256: str,
) -> list[dict[str, Any]]:
    """Reconcile HWP render placements and source objects occurrence by occurrence.

    Resource-key evidence wins and permits 1:N placement reuse.  Keyless rows
    may use a unique raw-byte or decoded-RGBA fingerprint only when the
    fingerprint was observed at the exact occurrence bbox.  Ties remain
    ambiguous.  Unused source objects are retained as document-only records,
    so count mismatches and unsupported media never poison their siblings.
    """

    normalized_doc_id = _require_doc_id(doc_id)
    normalized_source_sha256 = _require_digest(
        source_sha256, "hwp_visual_v2_source_sha256_invalid"
    )
    # Revalidate public inputs even if they came from the parser above.
    normalized_occurrences = parse_hwp_helper_occurrences(
        list(occurrences), doc_id=normalized_doc_id
    )
    normalized_sources = _normalize_source_objects(source_objects, normalized_doc_id)
    sources_by_key = {
        source["source_image_key"]: source
        for source in normalized_sources
        if source["source_image_key"] is not None
    }
    used_source_ordinals: set[int] = set()
    records: list[dict[str, Any]] = []

    for occurrence in normalized_occurrences:
        record = _page_record(
            doc_id=normalized_doc_id,
            source_sha256=normalized_source_sha256,
            occurrence=occurrence,
        )
        source_image_key = occurrence["source_image_key"]
        if source_image_key is not None:
            source = sources_by_key.get(source_image_key)
            if source is None:
                record["source_object_status"] = "missing"
                record["link_method"] = "none"
                record["match_evidence"] = []
                record["warnings"] = ["source_image_key_unresolved"]
            elif occurrence["source_resource_sha256"] != source["source_object_sha256"]:
                record["source_object_status"] = "ambiguous"
                record["link_method"] = "none"
                record["match_evidence"] = []
                record["warnings"] = ["source_image_key_digest_conflict"]
            elif source["supported"]:
                _attach_source(
                    record,
                    source,
                    status="exact_resource_link",
                    link_method="document_resource_key",
                    match_evidence=["document_resource_key"],
                )
                used_source_ordinals.add(source["source_ordinal"])
            else:
                _attach_source(
                    record,
                    source,
                    status="unsupported",
                    link_method="none",
                    match_evidence=[],
                )
                record["retrieval_status"] = "quarantined"
                record["warnings"] = ["source_object_unsupported"]
                used_source_ordinals.add(source["source_ordinal"])
        else:
            match_kind, source, match_evidence, warnings = _fallback_match(
                occurrence, normalized_sources
            )
            if match_kind in {"raw", "rgba"} and source is not None:
                _attach_source(
                    record,
                    source,
                    status="verified_exact_visual_match",
                    link_method=(
                        "raw_sha256_bbox_exact"
                        if match_kind == "raw"
                        else "rgba_sha256_bbox_exact"
                    ),
                    match_evidence=match_evidence,
                )
                used_source_ordinals.add(source["source_ordinal"])
            elif match_kind == "ambiguous":
                record["source_object_status"] = "ambiguous"
                record["link_method"] = "none"
                record["match_evidence"] = match_evidence
                record["warnings"] = warnings
            else:
                record["warnings"] = warnings
        records.append(record)

    records.extend(
        _source_only_record(
            doc_id=normalized_doc_id,
            source_sha256=normalized_source_sha256,
            source=source,
        )
        for source in normalized_sources
        if source["source_ordinal"] not in used_source_ordinals
    )
    occurrence_ids = [record["occurrence_id"] for record in records]
    if len(occurrence_ids) != len(set(occurrence_ids)):
        raise HwpVisualV2Error("hwp_visual_v2_occurrence_id_duplicate")
    try:
        for record in records:
            validate_visual_occurrence(record)
    except ValueError:
        raise HwpVisualV2Error("hwp_visual_v2_output_contract_invalid") from None
    return records


def recover_hwp_occurrences(
    *,
    doc_id: str,
    source_sha256: str,
    helper_payload: Any,
    source_objects: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Parse the optional helper payload and build additive HWP v2 records."""

    occurrences = parse_hwp_helper_occurrences(helper_payload, doc_id=doc_id)
    return link_hwp_source_objects(
        occurrences,
        source_objects,
        doc_id=doc_id,
        source_sha256=source_sha256,
    )


def top_level_hwp_occurrences(
    records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return page-placed body images for the top-level ordered stream.

    Table-child images remain attached to their canonical table/cell anchor and
    are never emitted a second time as top-level image occurrences.  Source-only
    inventory records also have no reading-order placement and are excluded.
    """

    if isinstance(records, (str, bytes, bytearray)) or not isinstance(
        records, Sequence
    ):
        raise HwpVisualV2Error("hwp_visual_v2_records_invalid")
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for value in records:
        if not isinstance(value, Mapping) or set(value) != _V2_FIELDS:
            raise HwpVisualV2Error("hwp_visual_v2_record_invalid")
        occurrence_id = value.get("occurrence_id")
        if not isinstance(occurrence_id, str) or not re.fullmatch(
            r"vocc2_[0-9a-f]{24}", occurrence_id
        ):
            raise HwpVisualV2Error("hwp_visual_v2_record_invalid")
        if occurrence_id in seen_ids:
            raise HwpVisualV2Error("hwp_visual_v2_occurrence_id_duplicate")
        seen_ids.add(occurrence_id)
        if value.get("schema_version") != VISUAL_OCCURRENCE_SCHEMA_VERSION:
            raise HwpVisualV2Error("hwp_visual_v2_record_invalid")
        anchor = _normalize_source_anchor(value.get("source_anchor"), optional=True)
        if value.get("placement_status") != "page_bbox_verified":
            continue
        if (
            value.get("region_kind") == "table_child_image"
            or (anchor is not None and anchor["kind"] == "table_nested")
        ):
            continue
        result.append(dict(value))
    return result


__all__ = [
    "COORDINATE_SPACE",
    "HWP_HELPER_SCHEMA_VERSION",
    "VISUAL_OCCURRENCE_SCHEMA_VERSION",
    "HwpVisualV2Error",
    "link_hwp_source_objects",
    "parse_hwp_helper_occurrences",
    "recover_hwp_occurrences",
    "top_level_hwp_occurrences",
]
