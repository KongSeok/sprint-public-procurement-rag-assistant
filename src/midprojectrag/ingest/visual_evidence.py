from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from midprojectrag.ingest.common import canonical_json, sha256_file


VISUAL_OCCURRENCE_SCHEMA_VERSION = "2.0"
VISUAL_CORPUS_SCHEMA_VERSION = "2.0"
VISUAL_CORPUS_METHOD = "local-visual-occurrence-understanding-v2"
MAX_JSONL_BYTES = 256 * 1024 * 1024
MAX_JSONL_RECORDS = 1_000_000
MAX_PAGE_PIXELS = 120_000_000
MAX_CROP_PIXELS = 40_000_000

_DOC_ID = re.compile(r"^doc_[0-9a-f]{24}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OCCURRENCE_ID = re.compile(r"^vocc2_[0-9a-f]{24}$")
_OBJECT_ID = re.compile(r"^vobj_[0-9a-f]{24}$")

PLACEMENT_STATUSES = frozenset(
    {"page_bbox_verified", "doc_only_unlinked", "ambiguous", "missing"}
)
SOURCE_OBJECT_STATUSES = frozenset(
    {
        "exact_resource_link",
        "verified_exact_visual_match",
        "render_only",
        "unsupported",
        "missing",
        "ambiguous",
    }
)
UNDERSTANDING_STATUSES = frozenset(
    {"none", "ocr_ready", "layout_ready", "caption_ready", "failed"}
)
RETRIEVAL_STATUSES = frozenset({"eligible", "withheld", "quarantined"})
REGION_KINDS = frozenset(
    {
        "raster_image",
        "inline_image",
        "vector_diagram",
        "table",
        "table_child_image",
        "decorative",
        "ambiguous",
    }
)
EVIDENCE_ORIGINS = frozenset(
    {"source_object", "page_render_crop", "resource_and_page_crop"}
)
LINK_METHODS = frozenset(
    {
        "document_resource_key",
        "raw_sha256_bbox_exact",
        "rgba_sha256_bbox_exact",
        "render_region_only",
        "none",
    }
)
MATCH_EVIDENCE = frozenset(
    {
        "document_resource_key",
        "raw_sha256",
        "normalized_rgba_sha256",
        "bbox_exact",
        "unique_candidate",
        "page_render",
    }
)
COORDINATE_SPACES = frozenset({"rhwp_css_px_96dpi", "pdf_points_top_left"})

VISUAL_OCCURRENCE_FIELDS = frozenset(
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


class VisualEvidenceError(ValueError):
    """A sanitized, stable visual-evidence contract error."""


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def stable_id(prefix: str, value: Any) -> str:
    if not isinstance(prefix, str) or not prefix or not prefix.endswith("_"):
        raise VisualEvidenceError("visual_id_prefix_invalid")
    return prefix + canonical_sha256(value)[:24]


def normalize_bbox(value: Mapping[str, Any], *, error_code: str = "visual_bbox_invalid") -> dict[str, float]:
    if not isinstance(value, Mapping) or set(value) != {"x", "y", "w", "h"}:
        raise VisualEvidenceError(error_code)
    normalized: dict[str, float] = {}
    for name in ("x", "y", "w", "h"):
        raw = value.get(name)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise VisualEvidenceError(error_code)
        number = float(raw)
        if not math.isfinite(number) or (name in {"w", "h"} and number <= 0):
            raise VisualEvidenceError(error_code)
        normalized[name] = round(number, 6)
    return normalized


def source_object_id(source_object_sha256: str) -> str:
    _require_sha256(source_object_sha256, "visual_source_object_sha256_invalid")
    return stable_id("vobj_", {"sha256": source_object_sha256})


def occurrence_id(
    *,
    doc_id: str,
    source_sha256: str,
    page: int | None,
    bbox: Mapping[str, Any] | None,
    region_kind: str,
    container_path: Sequence[str],
    sequence_in_page: int | None,
) -> str:
    _require_doc_id(doc_id)
    _require_sha256(source_sha256, "visual_source_sha256_invalid")
    normalized_bbox = None if bbox is None else normalize_bbox(bbox)
    if region_kind not in REGION_KINDS:
        raise VisualEvidenceError("visual_region_kind_invalid")
    path = _normalize_container_path(container_path)
    _require_optional_index(page, minimum=1, error_code="visual_page_invalid")
    _require_optional_index(
        sequence_in_page, minimum=0, error_code="visual_sequence_invalid"
    )
    return stable_id(
        "vocc2_",
        {
            "doc_id": doc_id,
            "source_sha256": source_sha256,
            "page": page,
            "bbox": normalized_bbox,
            "region_kind": region_kind,
            "container_path": path,
            "sequence_in_page": sequence_in_page,
        },
    )


def make_visual_occurrence(
    *,
    doc_id: str,
    source_sha256: str,
    page: int | None,
    bbox: Mapping[str, Any] | None,
    coordinate_space: str | None,
    sequence_in_page: int | None,
    container_path: Sequence[str],
    source_anchor: Mapping[str, Any] | None,
    region_kind: str,
    placement_status: str,
    source_object_status: str = "missing",
    evidence_origin: str = "source_object",
    source_image_key: str | None = None,
    source_object_sha256: str | None = None,
    source_object_media_type: str | None = None,
    link_method: str = "none",
    match_evidence: Sequence[str] = (),
    parent_occurrence_id: str | None = None,
    warnings: Sequence[str] = (),
    nearby_title: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_bbox = None if bbox is None else normalize_bbox(bbox)
    object_id = (
        None
        if source_object_sha256 is None
        else source_object_id(source_object_sha256)
    )
    record = {
        "schema_version": VISUAL_OCCURRENCE_SCHEMA_VERSION,
        "occurrence_id": occurrence_id(
            doc_id=doc_id,
            source_sha256=source_sha256,
            page=page,
            bbox=normalized_bbox,
            region_kind=region_kind,
            container_path=container_path,
            sequence_in_page=sequence_in_page,
        ),
        "doc_id": doc_id,
        "source_sha256": source_sha256,
        "page": page,
        "bbox": normalized_bbox,
        "coordinate_space": coordinate_space,
        "sequence_in_page": sequence_in_page,
        "container_path": _normalize_container_path(container_path),
        "source_anchor": None if source_anchor is None else dict(source_anchor),
        "region_kind": region_kind,
        "evidence_origin": evidence_origin,
        "page_render_sha256": None,
        "render_profile_sha256": None,
        "crop_sha256": None,
        "crop_relpath": None,
        "crop_media_type": None,
        "parent_occurrence_id": parent_occurrence_id,
        "source_image_key": source_image_key,
        "source_object_id": object_id,
        "source_object_sha256": source_object_sha256,
        "source_object_media_type": source_object_media_type,
        "source_object_status": source_object_status,
        "link_method": link_method,
        "match_evidence": sorted(set(match_evidence)),
        "placement_status": placement_status,
        "understanding_status": "none",
        "retrieval_status": "withheld",
        "nearby_title": None if nearby_title is None else dict(nearby_title),
        "warnings": sorted(set(warnings)),
    }
    validate_visual_occurrence(record)
    return record


def validate_visual_occurrence(record: Mapping[str, Any]) -> None:
    error_code = "visual_occurrence_contract_invalid"
    if not isinstance(record, Mapping) or set(record) != VISUAL_OCCURRENCE_FIELDS:
        raise VisualEvidenceError(error_code)
    if record.get("schema_version") != VISUAL_OCCURRENCE_SCHEMA_VERSION:
        raise VisualEvidenceError(error_code)
    occurrence = record.get("occurrence_id")
    if not isinstance(occurrence, str) or _OCCURRENCE_ID.fullmatch(occurrence) is None:
        raise VisualEvidenceError(error_code)
    _require_doc_id(record.get("doc_id"), error_code)
    _require_sha256(record.get("source_sha256"), error_code)
    page = record.get("page")
    sequence = record.get("sequence_in_page")
    _require_optional_index(page, minimum=1, error_code=error_code)
    _require_optional_index(sequence, minimum=0, error_code=error_code)
    bbox = record.get("bbox")
    if bbox is not None:
        normalize_bbox(bbox, error_code=error_code)
    coordinate_space = record.get("coordinate_space")
    if coordinate_space is not None and coordinate_space not in COORDINATE_SPACES:
        raise VisualEvidenceError(error_code)
    path = _normalize_container_path(record.get("container_path"), error_code)
    if path != list(record.get("container_path", [])):
        raise VisualEvidenceError(error_code)
    _validate_source_anchor(record.get("source_anchor"), error_code)
    if record.get("region_kind") not in REGION_KINDS:
        raise VisualEvidenceError(error_code)
    if record.get("evidence_origin") not in EVIDENCE_ORIGINS:
        raise VisualEvidenceError(error_code)
    if record.get("placement_status") not in PLACEMENT_STATUSES:
        raise VisualEvidenceError(error_code)
    if record.get("source_object_status") not in SOURCE_OBJECT_STATUSES:
        raise VisualEvidenceError(error_code)
    if record.get("understanding_status") not in UNDERSTANDING_STATUSES:
        raise VisualEvidenceError(error_code)
    if record.get("retrieval_status") not in RETRIEVAL_STATUSES:
        raise VisualEvidenceError(error_code)
    if record.get("link_method") not in LINK_METHODS:
        raise VisualEvidenceError(error_code)
    _validate_string_list(record.get("match_evidence"), MATCH_EVIDENCE, error_code)
    _validate_string_list(record.get("warnings"), None, error_code)

    for field in (
        "page_render_sha256",
        "render_profile_sha256",
        "crop_sha256",
        "source_object_sha256",
    ):
        value = record.get(field)
        if value is not None:
            _require_sha256(value, error_code)
    crop_relpath = record.get("crop_relpath")
    if crop_relpath is not None and (
        not isinstance(crop_relpath, str)
        or re.fullmatch(r"crops/[0-9a-f]{64}\.png", crop_relpath) is None
    ):
        raise VisualEvidenceError(error_code)
    if record.get("crop_media_type") not in {None, "image/png"}:
        raise VisualEvidenceError(error_code)
    parent = record.get("parent_occurrence_id")
    if parent is not None and (
        not isinstance(parent, str)
        or _OCCURRENCE_ID.fullmatch(parent) is None
        or parent == occurrence
    ):
        raise VisualEvidenceError(error_code)
    key = record.get("source_image_key")
    if key is not None and (
        not isinstance(key, str) or not key or len(key) > 256 or "\x00" in key
    ):
        raise VisualEvidenceError(error_code)
    object_id = record.get("source_object_id")
    if object_id is not None and (
        not isinstance(object_id, str) or _OBJECT_ID.fullmatch(object_id) is None
    ):
        raise VisualEvidenceError(error_code)
    media_type = record.get("source_object_media_type")
    if media_type is not None and (
        not isinstance(media_type, str)
        or re.fullmatch(r"(?:image|application)/[A-Za-z0-9.+-]+", media_type)
        is None
    ):
        raise VisualEvidenceError(error_code)
    _validate_nearby_title(record.get("nearby_title"), error_code)

    placement = record["placement_status"]
    if placement == "page_bbox_verified" and (
        page is None
        or bbox is None
        or coordinate_space is None
        or sequence is None
    ):
        raise VisualEvidenceError(error_code)
    if placement in {"doc_only_unlinked", "missing"} and any(
        value is not None for value in (page, bbox, coordinate_space, sequence)
    ):
        raise VisualEvidenceError(error_code)

    source_status = record["source_object_status"]
    source_digest = record.get("source_object_sha256")
    if source_status in {"exact_resource_link", "verified_exact_visual_match"}:
        if object_id is None or source_digest is None or media_type is None:
            raise VisualEvidenceError(error_code)
        if object_id != source_object_id(source_digest):
            raise VisualEvidenceError(error_code)
    if source_status == "exact_resource_link" and (
        key is None
        or record["link_method"] != "document_resource_key"
        or "document_resource_key" not in record["match_evidence"]
    ):
        raise VisualEvidenceError(error_code)
    if source_status == "verified_exact_visual_match" and (
        record["link_method"]
        not in {"raw_sha256_bbox_exact", "rgba_sha256_bbox_exact"}
        or "bbox_exact" not in record["match_evidence"]
        or "unique_candidate" not in record["match_evidence"]
    ):
        raise VisualEvidenceError(error_code)

    retrieval = record["retrieval_status"]
    crop_fields = (
        record.get("page_render_sha256"),
        record.get("render_profile_sha256"),
        record.get("crop_sha256"),
        crop_relpath,
        record.get("crop_media_type"),
    )
    if retrieval == "eligible" and (
        placement != "page_bbox_verified"
        or any(value is None for value in crop_fields)
        or source_status in {"ambiguous", "unsupported"}
    ):
        raise VisualEvidenceError(error_code)
    crop_presence = [value is not None for value in crop_fields]
    if any(crop_presence) and not all(crop_presence):
        raise VisualEvidenceError(error_code)

    expected_occurrence = occurrence_id(
        doc_id=record["doc_id"],
        source_sha256=record["source_sha256"],
        page=page,
        bbox=bbox,
        region_kind=record["region_kind"],
        container_path=record["container_path"],
        sequence_in_page=sequence,
    )
    if occurrence != expected_occurrence:
        raise VisualEvidenceError(error_code)


def crop_page_region(
    occurrence: Mapping[str, Any],
    *,
    page_image: Path,
    private_root: Path,
    coordinate_page_bbox: Mapping[str, Any],
    render_profile: Mapping[str, Any],
) -> dict[str, Any]:
    """Create a deterministic private PNG crop and promote page evidence.

    ``page_image`` is produced by a pinned local HWP/PDF renderer. The function
    never invokes a renderer or network service itself.
    """

    validate_visual_occurrence(occurrence)
    if occurrence["placement_status"] != "page_bbox_verified":
        raise VisualEvidenceError("visual_crop_placement_missing")
    page_path = _safe_existing_file(page_image, "visual_crop_page_invalid")
    root = _safe_private_root(private_root)
    page_box = normalize_bbox(
        coordinate_page_bbox, error_code="visual_crop_page_bbox_invalid"
    )
    box = normalize_bbox(occurrence["bbox"], error_code="visual_crop_bbox_invalid")
    if (
        box["x"] < page_box["x"]
        or box["y"] < page_box["y"]
        or box["x"] + box["w"] > page_box["x"] + page_box["w"] + 1e-6
        or box["y"] + box["h"] > page_box["y"] + page_box["h"] + 1e-6
    ):
        raise VisualEvidenceError("visual_crop_bbox_outside_page")
    profile_sha256 = canonical_sha256(render_profile)
    page_sha256 = sha256_file(page_path)

    try:
        from PIL import Image, ImageChops
    except ImportError:
        raise VisualEvidenceError("visual_crop_pillow_unavailable") from None
    try:
        with Image.open(page_path) as image:
            image.load()
            width, height = image.size
            if (
                width < 1
                or height < 1
                or width * height > MAX_PAGE_PIXELS
            ):
                raise VisualEvidenceError("visual_crop_page_pixels_exceeded")
            scale_x = width / page_box["w"]
            scale_y = height / page_box["h"]
            left = math.floor((box["x"] - page_box["x"]) * scale_x)
            top = math.floor((box["y"] - page_box["y"]) * scale_y)
            right = math.ceil((box["x"] + box["w"] - page_box["x"]) * scale_x)
            bottom = math.ceil((box["y"] + box["h"] - page_box["y"]) * scale_y)
            left = max(0, min(left, width - 1))
            top = max(0, min(top, height - 1))
            right = max(left + 1, min(right, width))
            bottom = max(top + 1, min(bottom, height))
            if (right - left) * (bottom - top) > MAX_CROP_PIXELS:
                raise VisualEvidenceError("visual_crop_pixels_exceeded")
            cropped = image.crop((left, top, right, bottom)).convert("RGBA")
            visible = Image.alpha_composite(
                Image.new("RGBA", cropped.size, (255, 255, 255, 255)), cropped
            ).convert("RGB")
            if ImageChops.difference(
                visible, Image.new("RGB", visible.size, (255, 255, 255))
            ).getbbox() is None:
                raise VisualEvidenceError("visual_crop_blank")
            output = io.BytesIO()
            cropped.save(output, format="PNG", optimize=False, compress_level=9)
            crop_bytes = output.getvalue()
    except VisualEvidenceError:
        raise
    except (OSError, ValueError):
        raise VisualEvidenceError("visual_crop_page_decode_failed") from None

    crop_sha256 = hashlib.sha256(crop_bytes).hexdigest()
    relative = Path("crops") / f"{crop_sha256}.png"
    destination = _safe_output_file(root, relative, "visual_crop_output_invalid")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise VisualEvidenceError("visual_crop_output_invalid")
    if destination.exists():
        if not destination.is_file() or sha256_file(destination) != crop_sha256:
            raise VisualEvidenceError("visual_crop_existing_mismatch")
    else:
        try:
            with tempfile.NamedTemporaryFile(
                prefix=".crop-", suffix=".png", dir=destination.parent, delete=False
            ) as handle:
                temporary = Path(handle.name)
                handle.write(crop_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            if sha256_file(temporary) != crop_sha256:
                temporary.unlink(missing_ok=True)
                raise VisualEvidenceError("visual_crop_write_mismatch")
            os.replace(temporary, destination)
        except VisualEvidenceError:
            raise
        except OSError:
            raise VisualEvidenceError("visual_crop_write_failed") from None

    promoted = dict(occurrence)
    promoted.update(
        {
            "page_render_sha256": page_sha256,
            "render_profile_sha256": profile_sha256,
            "crop_sha256": crop_sha256,
            "crop_relpath": relative.as_posix(),
            "crop_media_type": "image/png",
            "evidence_origin": (
                "resource_and_page_crop"
                if occurrence["source_object_status"]
                in {"exact_resource_link", "verified_exact_visual_match"}
                else "page_render_crop"
            ),
            "retrieval_status": (
                "withheld"
                if occurrence["source_object_status"] in {"ambiguous", "unsupported"}
                else "eligible"
            ),
            "match_evidence": sorted(
                set(occurrence["match_evidence"]) | {"page_render"}
            ),
        }
    )
    if promoted["source_object_status"] == "missing":
        promoted["source_object_status"] = "render_only"
        promoted["link_method"] = "render_region_only"
    validate_visual_occurrence(promoted)
    return promoted


def load_jsonl_bounded(
    path: Path,
    *,
    max_bytes: int = MAX_JSONL_BYTES,
    max_records: int = MAX_JSONL_RECORDS,
) -> list[dict[str, Any]]:
    source = _safe_existing_file(path, "visual_jsonl_invalid")
    try:
        size = source.stat().st_size
    except OSError:
        raise VisualEvidenceError("visual_jsonl_invalid") from None
    if size > max_bytes or max_bytes < 1 or max_records < 1:
        raise VisualEvidenceError("visual_jsonl_limit_exceeded")
    records: list[dict[str, Any]] = []
    try:
        with source.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    raise VisualEvidenceError("visual_jsonl_blank_line")
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise VisualEvidenceError("visual_jsonl_record_invalid")
                records.append(value)
                if len(records) > max_records:
                    raise VisualEvidenceError("visual_jsonl_limit_exceeded")
    except VisualEvidenceError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise VisualEvidenceError("visual_jsonl_invalid") from None
    return records


def write_jsonl_artifact(
    records: Iterable[Mapping[str, Any]],
    *,
    output: Path,
    private_root: Path,
) -> str:
    root = _safe_private_root(private_root)
    try:
        relative = output.relative_to(private_root)
    except ValueError:
        raise VisualEvidenceError("visual_artifact_output_invalid") from None
    destination = _safe_output_file(root, relative, "visual_artifact_output_invalid")
    destination.parent.mkdir(parents=True, exist_ok=True)
    normalized = [dict(record) for record in records]
    payload = b"".join(
        (canonical_json(record) + "\n").encode("utf-8") for record in normalized
    )
    if len(payload) > MAX_JSONL_BYTES or len(normalized) > MAX_JSONL_RECORDS:
        raise VisualEvidenceError("visual_artifact_limit_exceeded")
    digest = hashlib.sha256(payload).hexdigest()
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".visual-", suffix=".jsonl", dir=destination.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except OSError:
        raise VisualEvidenceError("visual_artifact_write_failed") from None
    if sha256_file(destination) != digest:
        raise VisualEvidenceError("visual_artifact_write_mismatch")
    return digest


def build_visual_corpus_metadata(
    *,
    source_manifest_sha256: str,
    adapter_code_sha256: str,
    config: Mapping[str, Any],
    dependency_versions: Mapping[str, str],
    occurrences: Sequence[Mapping[str, Any]],
    ocr_count: int,
    caption_count: int,
    chunk_count: int,
    artifact_hashes: Mapping[str, str],
) -> dict[str, Any]:
    for value, code in (
        (source_manifest_sha256, "visual_manifest_sha256_invalid"),
        (adapter_code_sha256, "visual_adapter_sha256_invalid"),
    ):
        _require_sha256(value, code)
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in (ocr_count, caption_count, chunk_count)
    ):
        raise VisualEvidenceError("visual_corpus_count_invalid")
    for occurrence in occurrences:
        validate_visual_occurrence(occurrence)
    hashes = dict(sorted(artifact_hashes.items()))
    if not hashes or any(
        not isinstance(name, str)
        or not name
        or _SHA256.fullmatch(value) is None
        for name, value in hashes.items()
    ):
        raise VisualEvidenceError("visual_corpus_artifact_hash_invalid")
    versions = dict(sorted(dependency_versions.items()))
    if any(
        not isinstance(name, str)
        or not name
        or not isinstance(version, str)
        or not version
        for name, version in versions.items()
    ):
        raise VisualEvidenceError("visual_dependency_version_invalid")
    config_sha256 = canonical_sha256(config)
    identity = {
        "source_manifest_sha256": source_manifest_sha256,
        "adapter_code_sha256": adapter_code_sha256,
        "config_sha256": config_sha256,
        "dependency_versions": versions,
        "artifact_hashes": hashes,
    }
    counts = Counter(
        f"placement:{record['placement_status']}" for record in occurrences
    )
    counts.update(
        f"source:{record['source_object_status']}" for record in occurrences
    )
    counts.update(f"retrieval:{record['retrieval_status']}" for record in occurrences)
    return {
        "schema_version": VISUAL_CORPUS_SCHEMA_VERSION,
        "artifact_set_id": stable_id("visualv2_", identity),
        "method": VISUAL_CORPUS_METHOD,
        "source_manifest_sha256": source_manifest_sha256,
        "adapter_code_sha256": adapter_code_sha256,
        "config_sha256": config_sha256,
        "dependency_versions": versions,
        "document_count": len({record["doc_id"] for record in occurrences}),
        "occurrence_count": len(occurrences),
        "ocr_count": ocr_count,
        "caption_count": caption_count,
        "chunk_count": chunk_count,
        "status_counts": dict(sorted(counts.items())),
        "artifact_hashes": hashes,
        "external_api_calls": 0,
        "private_egress": False,
        "strict_reuse_eligible": True,
    }


def _require_doc_id(value: Any, error_code: str = "visual_doc_id_invalid") -> None:
    if not isinstance(value, str) or _DOC_ID.fullmatch(value) is None:
        raise VisualEvidenceError(error_code)


def _require_sha256(value: Any, error_code: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise VisualEvidenceError(error_code)


def _require_optional_index(
    value: Any, *, minimum: int, error_code: str
) -> None:
    if value is None:
        return
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise VisualEvidenceError(error_code)


def _normalize_container_path(
    value: Any, error_code: str = "visual_container_path_invalid"
) -> list[str]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) > 64
    ):
        raise VisualEvidenceError(error_code)
    result = list(value)
    if any(
        not isinstance(item, str)
        or not item
        or len(item) > 256
        or "\x00" in item
        for item in result
    ):
        raise VisualEvidenceError(error_code)
    return result


def _validate_string_list(
    value: Any, allowlist: frozenset[str] | None, error_code: str
) -> None:
    if not isinstance(value, list) or len(value) != len(set(value)):
        raise VisualEvidenceError(error_code)
    if any(
        not isinstance(item, str)
        or not item
        or len(item) > 128
        or (allowlist is not None and item not in allowlist)
        for item in value
    ):
        raise VisualEvidenceError(error_code)


def _validate_source_anchor(value: Any, error_code: str) -> None:
    if value is None:
        return
    fields = {
        "kind",
        "section_index",
        "paragraph_index",
        "control_index",
        "table_block_id",
        "cell_path",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise VisualEvidenceError(error_code)
    if value["kind"] not in {
        "body",
        "table_nested",
        "page_overlay",
        "pdf_resource",
        "pdf_geometry",
    }:
        raise VisualEvidenceError(error_code)
    for field in ("section_index", "paragraph_index", "control_index"):
        _require_optional_index(value[field], minimum=0, error_code=error_code)
    block_id = value["table_block_id"]
    if block_id is not None and (
        not isinstance(block_id, str)
        or re.fullmatch(r"block_[0-9a-f]{24}", block_id) is None
    ):
        raise VisualEvidenceError(error_code)
    cell_path = value["cell_path"]
    if not isinstance(cell_path, list) or len(cell_path) > 32:
        raise VisualEvidenceError(error_code)
    for segment in cell_path:
        expected = {
            "control_index",
            "cell_index",
            "cell_paragraph_index",
            "row",
            "column",
        }
        if not isinstance(segment, Mapping) or set(segment) != expected:
            raise VisualEvidenceError(error_code)
        for field in ("control_index", "cell_index", "cell_paragraph_index"):
            _require_optional_index(segment[field], minimum=0, error_code=error_code)
            if segment[field] is None:
                raise VisualEvidenceError(error_code)
        for field in ("row", "column"):
            _require_optional_index(segment[field], minimum=0, error_code=error_code)


def _validate_nearby_title(value: Any, error_code: str) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping) or set(value) != {
        "text",
        "text_sha256",
        "bbox",
        "method",
    }:
        raise VisualEvidenceError(error_code)
    text = value["text"]
    if not isinstance(text, str) or not text or len(text) > 500:
        raise VisualEvidenceError(error_code)
    _require_sha256(value["text_sha256"], error_code)
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != value["text_sha256"]:
        raise VisualEvidenceError(error_code)
    normalize_bbox(value["bbox"], error_code=error_code)
    if value["method"] != "nearest_prior_heading_bounded_v1":
        raise VisualEvidenceError(error_code)


def _safe_existing_file(path: Path, error_code: str) -> Path:
    if not isinstance(path, Path) or path.is_symlink() or not path.is_file():
        raise VisualEvidenceError(error_code)
    try:
        return path.resolve(strict=True)
    except OSError:
        raise VisualEvidenceError(error_code) from None


def _safe_private_root(path: Path) -> Path:
    if not isinstance(path, Path):
        raise VisualEvidenceError("visual_private_root_invalid")
    try:
        path.mkdir(parents=True, exist_ok=True)
        resolved = path.resolve(strict=True)
    except OSError:
        raise VisualEvidenceError("visual_private_root_invalid") from None
    if path.is_symlink() or not resolved.is_dir():
        raise VisualEvidenceError("visual_private_root_invalid")
    return resolved


def _safe_output_file(root: Path, relative: Path, error_code: str) -> Path:
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise VisualEvidenceError(error_code)
    destination = root.joinpath(relative)
    try:
        parent = destination.parent.resolve(strict=False)
    except OSError:
        raise VisualEvidenceError(error_code) from None
    if parent != root and root not in parent.parents:
        raise VisualEvidenceError(error_code)
    return destination


__all__ = [
    "VisualEvidenceError",
    "build_visual_corpus_metadata",
    "canonical_sha256",
    "crop_page_region",
    "load_jsonl_bounded",
    "make_visual_occurrence",
    "normalize_bbox",
    "occurrence_id",
    "source_object_id",
    "stable_id",
    "validate_visual_occurrence",
    "write_jsonl_artifact",
]
