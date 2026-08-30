from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from midprojectrag.ingest.common import (
    canonical_json,
    sha256_file,
    sha256_text,
    write_json,
    write_jsonl,
)
from midprojectrag.ingest.hwp_assets import (
    MAX_ASSET_BYTES,
    _inspect_supported_image,
    _normalize_bbox,
    _normalize_preceding_text,
    _normalize_render_key,
    materialize_hwp_assets,
)
from midprojectrag.ingest.table_layout import load_rhwp_layout_inputs
from midprojectrag.ingest.visual_context import (
    COORDINATE_SPACE,
    build_body_image_evidence,
    build_ordered_visual_occurrences,
    build_table_visual_overlay,
)


VISUAL_BUNDLE_SCHEMA_VERSION = "1.0"
_DOC_ID_PATTERN = re.compile(r"^doc_[0-9a-f]{24}$")
_OCCURRENCE_ID_PATTERN = re.compile(r"^occ_[0-9a-f]{24}$")
_ASSET_ID_PATTERN = re.compile(r"^asset_[0-9a-f]{24}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_EXTENSION_PATTERN = re.compile(r"^\.[A-Za-z0-9]{1,16}$")
_ASSET_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/bmp": ".bmp",
    "image/tiff": ".tif",
}
_ASSET_SOURCE_EXTENSIONS = {
    "image/png": {".png"},
    "image/jpeg": {".jpg", ".jpeg"},
    "image/bmp": {".bmp"},
    "image/tiff": {".tif", ".tiff"},
}
_IMAGE_EVIDENCE_FIELDS = frozenset(
    {
        "schema_version",
        "occurrence_id",
        "doc_id",
        "ordinal",
        "node_type",
        "status",
        "asset_id",
        "asset_sha256",
        "asset_relpath",
        "media_type",
        "byte_size",
        "width",
        "height",
        "source_asset_sha256",
        "source_byte_size",
        "source_media_type",
        "source_extension",
        "normalizations",
        "page_start",
        "page_end",
        "bbox",
        "coordinate_space",
        "render_key",
        "sequence_in_page",
        "image_ordinal_in_page",
        "container_kind",
        "preceding_text",
        "link_method",
        "doclang_loss_count",
        "warnings",
    }
)


def _require_records(
    values: Sequence[Mapping[str, Any]], error_code: str
) -> list[Mapping[str, Any]]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError(error_code)
    if any(not isinstance(value, Mapping) for value in values):
        raise ValueError(error_code)
    return list(values)


def _require_sha256(value: Any, error_code: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(error_code)
    return value


def _safe_sha256_file(path: Path, error_code: str) -> str:
    try:
        return sha256_file(path)
    except OSError:
        raise ValueError(error_code) from None


def _private_root(path: Path) -> tuple[Path, Path]:
    if not isinstance(path, Path):
        raise ValueError("visual_bundle_private_root_invalid")
    lexical = Path(os.path.abspath(path))
    try:
        if path.is_symlink() or not path.is_dir():
            raise ValueError("visual_bundle_private_root_invalid")
        resolved = path.resolve(strict=True)
    except OSError:
        raise ValueError("visual_bundle_private_root_invalid") from None
    return lexical, resolved


def _private_path(
    path: Path,
    *,
    lexical_root: Path,
    resolved_root: Path,
    kind: str,
    error_code: str,
) -> Path:
    if not isinstance(path, Path) or kind not in {"file", "directory"}:
        raise ValueError(error_code)
    lexical = Path(os.path.abspath(path))
    try:
        relative = lexical.relative_to(lexical_root)
    except ValueError:
        raise ValueError(error_code) from None
    if not relative.parts:
        raise ValueError(error_code)

    current = lexical_root
    for index, part in enumerate(relative.parts):
        current = current / part
        if current.is_symlink():
            raise ValueError(error_code)
        if current.exists():
            is_last = index == len(relative.parts) - 1
            if not is_last and not current.is_dir():
                raise ValueError(error_code)
            if is_last and kind == "file" and not current.is_file():
                raise ValueError(error_code)
            if is_last and kind == "directory" and not current.is_dir():
                raise ValueError(error_code)
    try:
        resolved = lexical.resolve(strict=False)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError):
        raise ValueError(error_code) from None
    return resolved


def _safe_mkdir(path: Path, error_code: str) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise ValueError(error_code) from None


def _safe_canonical_hash(value: Any, error_code: str) -> str:
    try:
        return sha256_text(canonical_json(value))
    except (TypeError, ValueError):
        raise ValueError(error_code) from None


def _status_counts(records: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        status = record.get("status")
        if not isinstance(status, str) or not status:
            raise ValueError("visual_bundle_status_invalid")
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _validate_page_ranges(
    records: Sequence[Mapping[str, Any]], *, page_count: int
) -> None:
    for record in records:
        page_start = record.get("page_start")
        page_end = record.get("page_end")
        if page_start is None and page_end is None:
            continue
        if (
            not isinstance(page_start, int)
            or isinstance(page_start, bool)
            or not isinstance(page_end, int)
            or isinstance(page_end, bool)
            or page_start < 1
            or page_end < page_start
            or page_end > page_count
        ):
            raise ValueError("visual_bundle_page_reference_invalid")


def _validate_image_source_contract(
    records: Sequence[Mapping[str, Any]],
) -> None:
    error_code = "visual_bundle_image_contract_invalid"
    statuses: set[str] = set()
    for record in records:
        if set(record) != _IMAGE_EVIDENCE_FIELDS:
            raise ValueError(error_code)
        status = record.get("status")
        ordinal = record.get("ordinal")
        loss_count = record.get("doclang_loss_count")
        warnings = record.get("warnings")
        normalizations = record.get("normalizations")
        if (
            record.get("schema_version") != "1.0"
            or not isinstance(record.get("occurrence_id"), str)
            or _OCCURRENCE_ID_PATTERN.fullmatch(record["occurrence_id"]) is None
            or not isinstance(record.get("doc_id"), str)
            or _DOC_ID_PATTERN.fullmatch(record["doc_id"]) is None
            or record.get("node_type") != "image"
            or status
            not in {
                "verified_asset_render",
                "asset_only_unlinked",
                "unsupported_source_asset",
                "render_only_missing_asset",
            }
            or not isinstance(ordinal, int)
            or isinstance(ordinal, bool)
            or ordinal < 0
            or not isinstance(loss_count, int)
            or isinstance(loss_count, bool)
            or loss_count < 0
            or not isinstance(warnings, list)
            or len(warnings) != len(set(warnings))
            or any(not isinstance(value, str) or not value for value in warnings)
            or not isinstance(normalizations, list)
            or len(normalizations) != len(set(normalizations))
            or any(
                value
                not in {
                    "source_extension_canonicalized",
                    "png_trailing_bytes_removed",
                }
                for value in normalizations
            )
        ):
            raise ValueError(error_code)
        statuses.add(status)

        source_digest = record.get("source_asset_sha256")
        source_size = record.get("source_byte_size")
        source_media_type = record.get("source_media_type")
        source_extension = record.get("source_extension")
        if source_extension is not None and (
            not isinstance(source_extension, str)
            or _SOURCE_EXTENSION_PATTERN.fullmatch(source_extension) is None
        ):
            raise ValueError(error_code)

        if status in {"verified_asset_render", "asset_only_unlinked"}:
            try:
                _require_sha256(source_digest, error_code)
            except ValueError:
                raise ValueError(error_code) from None
            media_type = record.get("media_type")
            asset_digest = record.get("asset_sha256")
            byte_size = record.get("byte_size")
            if (
                source_media_type not in _ASSET_SOURCE_EXTENSIONS
                or source_media_type != media_type
                or not isinstance(source_size, int)
                or isinstance(source_size, bool)
                or source_size < 1
                or source_size > MAX_ASSET_BYTES
                or not isinstance(byte_size, int)
                or isinstance(byte_size, bool)
                or byte_size < 1
                or byte_size > MAX_ASSET_BYTES
                or not isinstance(asset_digest, str)
                or not isinstance(record.get("asset_id"), str)
                or _ASSET_ID_PATTERN.fullmatch(record["asset_id"]) is None
            ):
                raise ValueError(error_code)
            expected_normalizations: list[str] = []
            if source_extension not in _ASSET_SOURCE_EXTENSIONS[source_media_type]:
                expected_normalizations.append("source_extension_canonicalized")
            if source_size != byte_size:
                if (
                    source_media_type != "image/png"
                    or source_size <= byte_size
                    or source_digest == asset_digest
                ):
                    raise ValueError(error_code)
                expected_normalizations.append("png_trailing_bytes_removed")
            elif source_digest != asset_digest:
                raise ValueError(error_code)
            if normalizations != expected_normalizations:
                raise ValueError(error_code)
            if status == "verified_asset_render":
                try:
                    _normalize_bbox(record.get("bbox"), error_code)
                    _normalize_render_key(record.get("render_key"))
                    _normalize_preceding_text(record.get("preceding_text"))
                except ValueError:
                    raise ValueError(error_code) from None
                if (
                    not isinstance(record.get("page_start"), int)
                    or isinstance(record.get("page_start"), bool)
                    or record["page_start"] < 1
                    or record.get("page_end") != record["page_start"]
                    or record.get("coordinate_space") != COORDINATE_SPACE
                    or not isinstance(record.get("sequence_in_page"), int)
                    or isinstance(record.get("sequence_in_page"), bool)
                    or record["sequence_in_page"] < 0
                    or not isinstance(record.get("image_ordinal_in_page"), int)
                    or isinstance(record.get("image_ordinal_in_page"), bool)
                    or record["image_ordinal_in_page"] < 0
                    or record.get("container_kind") not in {"body", "table_nested"}
                    or record.get("link_method")
                    != "doclang_picture_render_image_global_ordinal_exact_count"
                    or warnings
                ):
                    raise ValueError(error_code)
            else:
                null_render_fields = {
                    "page_start",
                    "page_end",
                    "bbox",
                    "coordinate_space",
                    "render_key",
                    "sequence_in_page",
                    "image_ordinal_in_page",
                    "container_kind",
                    "preceding_text",
                }
                if (
                    any(record.get(field) is not None for field in null_render_fields)
                    or record.get("link_method") != "doclang_picture_unlinked"
                    or not warnings
                ):
                    raise ValueError(error_code)
            continue

        null_asset_fields = {
            "asset_id",
            "asset_sha256",
            "asset_relpath",
            "media_type",
            "byte_size",
            "width",
            "height",
        }
        if any(record.get(field) is not None for field in null_asset_fields):
            raise ValueError(error_code)
        if status == "unsupported_source_asset":
            try:
                _require_sha256(source_digest, error_code)
            except ValueError:
                raise ValueError(error_code) from None
            null_render_fields = {
                "page_start",
                "page_end",
                "bbox",
                "coordinate_space",
                "render_key",
                "sequence_in_page",
                "image_ordinal_in_page",
                "container_kind",
                "preceding_text",
            }
            if (
                source_media_type not in {"image/wmf", "image/gif"}
                or not isinstance(source_size, int)
                or isinstance(source_size, bool)
                or source_size < 1
                or source_size > MAX_ASSET_BYTES
                or normalizations
                or record.get("link_method")
                != "doclang_picture_unsupported_unlinked"
                or "image_format_unsupported" not in warnings
                or any(record.get(field) is not None for field in null_render_fields)
            ):
                raise ValueError(error_code)
            continue

        if (
            source_digest is not None
            or source_size is not None
            or source_media_type is not None
            or source_extension is not None
            or normalizations
        ):
            raise ValueError(error_code)
        try:
            _normalize_bbox(record.get("bbox"), error_code)
            if record.get("render_key") is not None:
                _normalize_render_key(record.get("render_key"))
            _normalize_preceding_text(record.get("preceding_text"))
        except ValueError:
            raise ValueError(error_code) from None
        if (
            not isinstance(record.get("page_start"), int)
            or isinstance(record.get("page_start"), bool)
            or record["page_start"] < 1
            or record.get("page_end") != record["page_start"]
            or record.get("coordinate_space") != COORDINATE_SPACE
            or not isinstance(record.get("sequence_in_page"), int)
            or isinstance(record.get("sequence_in_page"), bool)
            or record["sequence_in_page"] < 0
            or not isinstance(record.get("image_ordinal_in_page"), int)
            or isinstance(record.get("image_ordinal_in_page"), bool)
            or record["image_ordinal_in_page"] < 0
            or record.get("container_kind") not in {"body", "table_nested"}
            or record.get("link_method") != "render_image_unlinked"
            or not warnings
        ):
            raise ValueError(error_code)

    # The producer links image evidence as a single global ordinal set.  A
    # document is therefore either fully verified or fully unlinked; persisted
    # bundles that mix verified and unresolved/unsupported states are legacy or
    # tampered and must never be reused.
    if "verified_asset_render" in statuses and statuses != {"verified_asset_render"}:
        raise ValueError(error_code)


def _asset_manifest(
    records: Sequence[Mapping[str, Any]], *, asset_root: Path
) -> tuple[list[dict[str, Any]], int]:
    by_sha256: dict[str, dict[str, Any]] = {}
    paths: dict[str, str] = {}
    reference_count = 0
    for record in records:
        digest = record.get("asset_sha256")
        if digest is None:
            continue
        _require_sha256(digest, "visual_bundle_asset_reference_invalid")
        relpath = record.get("asset_relpath")
        byte_size = record.get("byte_size")
        width = record.get("width")
        height = record.get("height")
        media_type = record.get("media_type")
        if (
            not isinstance(relpath, str)
            or not isinstance(byte_size, int)
            or isinstance(byte_size, bool)
            or byte_size < 1
            or not isinstance(width, int)
            or isinstance(width, bool)
            or width < 1
            or not isinstance(height, int)
            or isinstance(height, bool)
            or height < 1
            or media_type not in _ASSET_EXTENSIONS
            or relpath != f"objects/{digest}{_ASSET_EXTENSIONS[media_type]}"
        ):
            raise ValueError("visual_bundle_asset_reference_invalid")
        relative = Path(relpath)
        candidate = asset_root / relative
        current = asset_root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("visual_bundle_asset_reference_invalid")
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(asset_root)
            size = resolved.stat().st_size
        except (OSError, ValueError):
            raise ValueError("visual_bundle_asset_reference_invalid") from None
        if (
            not resolved.is_file()
            or resolved.is_symlink()
            or size != byte_size
            or size > MAX_ASSET_BYTES
        ):
            raise ValueError("visual_bundle_asset_reference_invalid")
        try:
            data = resolved.read_bytes()
        except OSError:
            raise ValueError("visual_bundle_asset_reference_invalid") from None
        if (
            len(data) != size
            or len(data) > MAX_ASSET_BYTES
            or hashlib.sha256(data).hexdigest() != digest
        ):
            raise ValueError("visual_bundle_asset_reference_invalid")
        try:
            inspected = _inspect_supported_image(data, resolved.suffix)
        except ValueError:
            raise ValueError("visual_bundle_asset_reference_invalid") from None
        if (
            inspected is None
            or inspected.data != data
            or inspected.normalizations
            or inspected.media_type != media_type
            or inspected.extension != _ASSET_EXTENSIONS[media_type]
            or inspected.width != width
            or inspected.height != height
        ):
            raise ValueError("visual_bundle_asset_reference_invalid")
        entry = {
            "asset_sha256": digest,
            "asset_relpath": relpath,
            "byte_size": byte_size,
            "media_type": media_type,
            "width": width,
            "height": height,
        }
        prior = by_sha256.get(digest)
        if prior is not None and prior != entry:
            raise ValueError("visual_bundle_asset_reference_conflict")
        prior_digest = paths.get(relpath)
        if prior_digest is not None and prior_digest != digest:
            raise ValueError("visual_bundle_asset_reference_conflict")
        by_sha256[digest] = entry
        paths[relpath] = digest
        reference_count += 1
    return sorted(by_sha256.values(), key=lambda value: value["asset_sha256"]), reference_count


def _write_jsonl_checked(
    path: Path, records: Sequence[dict[str, Any]], error_code: str
) -> str:
    try:
        expected = sha256_text(
            "".join(canonical_json(record) + "\n" for record in records)
        )
        write_jsonl(path, records)
    except (OSError, TypeError, ValueError):
        raise ValueError(error_code) from None
    if _safe_sha256_file(path, error_code) != expected:
        raise ValueError(error_code)
    return expected


def _write_json_checked(path: Path, value: Mapping[str, Any], error_code: str) -> str:
    try:
        write_json(path, value)
    except (OSError, TypeError, ValueError):
        raise ValueError(error_code) from None
    return _safe_sha256_file(path, error_code)


def _publish_staged(
    pairs: Sequence[tuple[Path, Path, str]], *, backup_root: Path
) -> None:
    backups: dict[Path, Path | None] = {}
    published: list[Path] = []
    try:
        for index, (_staged, destination, _expected) in enumerate(pairs):
            if destination.is_symlink() or (
                destination.exists() and not destination.is_file()
            ):
                raise OSError("unsafe destination")
            backup: Path | None = None
            if destination.exists():
                backup = backup_root / f"backup-{index}"
                os.link(destination, backup)
            backups[destination] = backup
        for staged, destination, _expected in pairs:
            os.replace(staged, destination)
            published.append(destination)
        for _staged, destination, expected in pairs:
            if sha256_file(destination) != expected:
                raise OSError("published checksum mismatch")
    except (OSError, ValueError):
        rollback_failed = False
        for destination in reversed(published):
            backup = backups.get(destination)
            try:
                if backup is None:
                    destination.unlink(missing_ok=True)
                else:
                    os.replace(backup, destination)
            except OSError:
                rollback_failed = True
        if rollback_failed:
            raise ValueError("visual_bundle_publish_rollback_failed") from None
        raise ValueError("visual_bundle_publish_failed") from None


def materialize_hwp_visual_bundle(
    *,
    command: str,
    source_path: Path,
    doc_id: str,
    blocks: Sequence[Mapping[str, Any]],
    layout_records: Sequence[Mapping[str, Any]],
    table_output: Path,
    image_output: Path,
    ordered_output: Path,
    metadata_output: Path,
    asset_root: Path,
    private_root: Path,
    config_sha256: str,
    expected_source_sha256: str,
    expected_rhwp_sha256: str,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """Build one deterministic private HWP visual evidence bundle.

    The canonical source blocks are inputs and are never rewritten. This
    function intentionally returns aggregate metadata only; private context and
    paths remain in the requested JSONL files beneath the caller's private root.
    """
    if not isinstance(doc_id, str) or _DOC_ID_PATTERN.fullmatch(doc_id) is None:
        raise ValueError("doc_id_invalid")
    normalized_blocks = _require_records(blocks, "visual_bundle_blocks_invalid")
    normalized_layouts = _require_records(
        layout_records, "visual_bundle_layout_records_invalid"
    )
    config_sha256 = _require_sha256(
        config_sha256, "visual_bundle_config_sha256_invalid"
    )
    expected_source_sha256 = _require_sha256(
        expected_source_sha256, "visual_bundle_source_sha256_invalid"
    )
    expected_rhwp_sha256 = _require_sha256(
        expected_rhwp_sha256, "visual_bundle_rhwp_sha256_invalid"
    )
    if not isinstance(command, str) or not Path(command).is_absolute():
        raise ValueError("visual_bundle_rhwp_command_invalid")
    raw_command_path = Path(command)
    if (
        not raw_command_path.is_file()
        or raw_command_path.is_symlink()
        or not os.access(raw_command_path, os.X_OK)
    ):
        raise ValueError("visual_bundle_rhwp_command_invalid")
    try:
        command_path = raw_command_path.resolve(strict=True)
    except OSError:
        raise ValueError("visual_bundle_rhwp_command_invalid") from None
    binary_sha256 = _safe_sha256_file(
        command_path, "visual_bundle_rhwp_read_failed"
    )
    if binary_sha256 != expected_rhwp_sha256:
        raise ValueError("visual_bundle_rhwp_checksum_mismatch")
    if (
        not isinstance(source_path, Path)
        or not source_path.is_file()
        or source_path.is_symlink()
    ):
        raise ValueError("visual_bundle_source_invalid")
    if (
        not isinstance(timeout_seconds, int)
        or isinstance(timeout_seconds, bool)
        or timeout_seconds < 1
    ):
        raise ValueError("visual_bundle_timeout_invalid")
    try:
        resolved_source = source_path.resolve(strict=True)
    except OSError:
        raise ValueError("visual_bundle_source_invalid") from None
    source_sha256 = _safe_sha256_file(
        resolved_source, "visual_bundle_source_read_failed"
    )
    if source_sha256 != expected_source_sha256:
        raise ValueError("visual_bundle_source_checksum_mismatch")

    lexical_private_root, resolved_private_root = _private_root(private_root)
    path_specs = (
        (table_output, "visual_bundle_table_output_invalid"),
        (image_output, "visual_bundle_image_output_invalid"),
        (ordered_output, "visual_bundle_ordered_output_invalid"),
        (metadata_output, "visual_bundle_metadata_output_invalid"),
    )
    resolved_outputs = [
        _private_path(
            path,
            lexical_root=lexical_private_root,
            resolved_root=resolved_private_root,
            kind="file",
            error_code=error_code,
        )
        for path, error_code in path_specs
    ]
    if (
        len(set(resolved_outputs)) != len(resolved_outputs)
        or resolved_source in resolved_outputs
        or command_path in resolved_outputs
    ):
        raise ValueError("visual_bundle_output_collision")
    resolved_asset_root = _private_path(
        asset_root,
        lexical_root=lexical_private_root,
        resolved_root=resolved_private_root,
        kind="directory",
        error_code="visual_bundle_asset_root_invalid",
    )
    if resolved_asset_root in resolved_outputs or any(
        output.is_relative_to(resolved_asset_root) for output in resolved_outputs
    ):
        raise ValueError("visual_bundle_output_collision")
    for output in resolved_outputs:
        _safe_mkdir(output.parent, "visual_bundle_output_parent_invalid")
    _safe_mkdir(resolved_asset_root, "visual_bundle_asset_root_invalid")

    # Recheck after directory creation so a pre-existing or raced symlink
    # cannot move a private artifact outside the authorized root.
    resolved_outputs = [
        _private_path(
            path,
            lexical_root=lexical_private_root,
            resolved_root=resolved_private_root,
            kind="file",
            error_code=error_code,
        )
        for path, error_code in path_specs
    ]
    resolved_asset_root = _private_path(
        asset_root,
        lexical_root=lexical_private_root,
        resolved_root=resolved_private_root,
        kind="directory",
        error_code="visual_bundle_asset_root_invalid",
    )

    blocks_sha256 = _safe_canonical_hash(
        normalized_blocks, "visual_bundle_blocks_invalid"
    )
    layout_records_sha256 = _safe_canonical_hash(
        normalized_layouts, "visual_bundle_layout_records_invalid"
    )

    try:
        dump_pages, render_trees = load_rhwp_layout_inputs(
            str(command_path), resolved_source, timeout_seconds=timeout_seconds
        )
    except OSError:
        raise ValueError("visual_bundle_extraction_io_failed") from None
    if not isinstance(dump_pages, Mapping) or not isinstance(render_trees, Mapping):
        raise ValueError("visual_bundle_layout_contract_invalid")
    page_count = dump_pages.get("pageCount")
    if (
        not isinstance(page_count, int)
        or isinstance(page_count, bool)
        or page_count < 0
        or len(render_trees) != page_count
    ):
        raise ValueError("visual_bundle_page_count_invalid")
    table_records = build_table_visual_overlay(
        doc_id=doc_id,
        blocks=normalized_blocks,
        layout_records=normalized_layouts,
        dump_pages=dump_pages,
        render_trees=render_trees,
    )
    render_images = build_body_image_evidence(
        doc_id=doc_id,
        dump_pages=dump_pages,
        render_trees=render_trees,
    )
    image_records = materialize_hwp_assets(
        command=str(command_path),
        source_path=resolved_source,
        doc_id=doc_id,
        render_images=render_images,
        output_root=resolved_asset_root,
        timeout_seconds=timeout_seconds,
    )
    _validate_image_source_contract(image_records)
    ordered_records = build_ordered_visual_occurrences(
        doc_id=doc_id,
        dump_pages=dump_pages,
        render_trees=render_trees,
        table_records=table_records,
        image_records=image_records,
    )

    table_records.sort(key=lambda record: (record["doc_id"], record["block_id"]))
    image_records.sort(
        key=lambda record: (
            int(record.get("ordinal", 0)),
            str(record.get("status", "")),
            str(record.get("occurrence_id", "")),
        )
    )
    ordered_records.sort(
        key=lambda record: (
            int(record.get("page", 0)),
            int(record.get("sequence_in_page", 0)),
            str(record.get("node_type", "")),
            str(record.get("ordered_occurrence_id", "")),
        )
    )
    _validate_page_ranges(table_records, page_count=page_count)
    _validate_page_ranges(image_records, page_count=page_count)
    if any(
        not isinstance(record.get("page"), int)
        or isinstance(record.get("page"), bool)
        or record["page"] < 1
        or record["page"] > page_count
        for record in ordered_records
    ):
        raise ValueError("visual_bundle_page_reference_invalid")
    asset_manifest, asset_reference_count = _asset_manifest(
        image_records, asset_root=resolved_asset_root
    )
    asset_manifest_sha256 = _safe_canonical_hash(
        asset_manifest, "visual_bundle_asset_manifest_invalid"
    )
    asset_bytes = sum(entry["byte_size"] for entry in asset_manifest)

    # Parsing invokes the binary and reads the source multiple times. Both
    # identities must still match the required values before publication.
    if (
        _safe_sha256_file(resolved_source, "visual_bundle_source_read_failed")
        != expected_source_sha256
    ):
        raise ValueError("visual_bundle_source_changed_during_extraction")
    if (
        _safe_sha256_file(command_path, "visual_bundle_rhwp_read_failed")
        != expected_rhwp_sha256
    ):
        raise ValueError("visual_bundle_rhwp_changed_during_extraction")

    try:
        with tempfile.TemporaryDirectory(
            prefix=".visual-bundle-stage-",
            dir=resolved_private_root,
            ignore_cleanup_errors=True,
        ) as stage_name:
            stage = Path(stage_name)
            staged_table = stage / "table.jsonl"
            staged_image = stage / "image.jsonl"
            staged_ordered = stage / "ordered.jsonl"
            staged_metadata = stage / "metadata.json"
            table_sha256 = _write_jsonl_checked(
                staged_table,
                table_records,
                "visual_bundle_table_stage_invalid",
            )
            image_sha256 = _write_jsonl_checked(
                staged_image,
                image_records,
                "visual_bundle_image_stage_invalid",
            )
            ordered_sha256 = _write_jsonl_checked(
                staged_ordered,
                ordered_records,
                "visual_bundle_ordered_stage_invalid",
            )
            identity = {
                "doc_id": doc_id,
                "source_sha256": source_sha256,
                "rhwp_binary_sha256": binary_sha256,
                "config_sha256": config_sha256,
                "blocks_sha256": blocks_sha256,
                "layout_records_sha256": layout_records_sha256,
                "table_artifact_sha256": table_sha256,
                "image_artifact_sha256": image_sha256,
                "ordered_artifact_sha256": ordered_sha256,
                "asset_object_manifest_sha256": asset_manifest_sha256,
                "page_count": page_count,
            }
            metadata = {
                "schema_version": VISUAL_BUNDLE_SCHEMA_VERSION,
                "doc_id": doc_id,
                "method": "rhwp-ordered-visual-evidence-v1",
                "coordinate_space": COORDINATE_SPACE,
                "source_sha256": source_sha256,
                "rhwp_binary_sha256": binary_sha256,
                "config_sha256": config_sha256,
                "blocks_sha256": blocks_sha256,
                "layout_records_sha256": layout_records_sha256,
                "table_artifact_sha256": table_sha256,
                "image_artifact_sha256": image_sha256,
                "ordered_artifact_sha256": ordered_sha256,
                "asset_object_manifest_sha256": asset_manifest_sha256,
                "artifact_set_id": "visual_"
                + _safe_canonical_hash(
                    identity, "visual_bundle_identity_invalid"
                )[:24],
                "page_count": page_count,
                "tables": len(table_records),
                "images": len(image_records),
                "ordered_occurrences": len(ordered_records),
                "asset_count": len(asset_manifest),
                "asset_reference_count": asset_reference_count,
                "asset_bytes": asset_bytes,
                "asset_references_reconciled": True,
                "table_status_counts": _status_counts(table_records),
                "image_status_counts": _status_counts(image_records),
                "ordered_status_counts": _status_counts(ordered_records),
            }
            metadata_sha256 = _write_json_checked(
                staged_metadata,
                metadata,
                "visual_bundle_metadata_stage_invalid",
            )
            # A last identity check closes the staging window. Metadata is
            # published last so readers that verify hashes fail closed during
            # the small multi-file replace window.
            if (
                _safe_sha256_file(
                    resolved_source, "visual_bundle_source_read_failed"
                )
                != expected_source_sha256
            ):
                raise ValueError("visual_bundle_source_changed_during_extraction")
            if (
                _safe_sha256_file(command_path, "visual_bundle_rhwp_read_failed")
                != expected_rhwp_sha256
            ):
                raise ValueError("visual_bundle_rhwp_changed_during_extraction")
            final_outputs = [
                _private_path(
                    path,
                    lexical_root=lexical_private_root,
                    resolved_root=resolved_private_root,
                    kind="file",
                    error_code=error_code,
                )
                for path, error_code in path_specs
            ]
            final_asset_root = _private_path(
                asset_root,
                lexical_root=lexical_private_root,
                resolved_root=resolved_private_root,
                kind="directory",
                error_code="visual_bundle_asset_root_invalid",
            )
            if (
                final_outputs != resolved_outputs
                or final_asset_root != resolved_asset_root
            ):
                raise ValueError("visual_bundle_private_path_changed")
            _publish_staged(
                (
                    (staged_table, resolved_outputs[0], table_sha256),
                    (staged_image, resolved_outputs[1], image_sha256),
                    (staged_ordered, resolved_outputs[2], ordered_sha256),
                    (staged_metadata, resolved_outputs[3], metadata_sha256),
                ),
                backup_root=stage,
            )
    except ValueError:
        raise
    except OSError:
        raise ValueError("visual_bundle_stage_failed") from None
    return metadata


_VISUAL_METADATA_FIELDS = frozenset(
    {
        "schema_version",
        "doc_id",
        "method",
        "coordinate_space",
        "source_sha256",
        "rhwp_binary_sha256",
        "config_sha256",
        "blocks_sha256",
        "layout_records_sha256",
        "table_artifact_sha256",
        "image_artifact_sha256",
        "ordered_artifact_sha256",
        "asset_object_manifest_sha256",
        "artifact_set_id",
        "page_count",
        "tables",
        "images",
        "ordered_occurrences",
        "asset_count",
        "asset_reference_count",
        "asset_bytes",
        "asset_references_reconciled",
        "table_status_counts",
        "image_status_counts",
        "ordered_status_counts",
    }
)


def _read_json_object(path: Path, error_code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError(error_code) from None
    if not isinstance(value, dict):
        raise ValueError(error_code)
    return value


def _read_jsonl_objects(path: Path, error_code: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as source:
            for line in source:
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(error_code)
                records.append(value)
    except ValueError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError(error_code) from None
    return records


def verify_hwp_visual_bundle(
    *,
    command: str,
    source_path: Path,
    doc_id: str,
    blocks: Sequence[Mapping[str, Any]],
    layout_records: Sequence[Mapping[str, Any]],
    table_output: Path,
    image_output: Path,
    ordered_output: Path,
    metadata_output: Path,
    asset_root: Path,
    private_root: Path,
    config_sha256: str,
    expected_source_sha256: str,
    expected_rhwp_sha256: str,
    expected_page_count: int | None = None,
) -> dict[str, Any]:
    """Strictly rescan one published bundle before it may be reused.

    The verifier intentionally trusts neither file existence nor the persisted
    metadata.  It recomputes every artifact and asset identity and checks the
    canonical block/layout inputs without invoking the parser.
    """

    if not isinstance(doc_id, str) or _DOC_ID_PATTERN.fullmatch(doc_id) is None:
        raise ValueError("doc_id_invalid")
    normalized_blocks = _require_records(blocks, "visual_bundle_blocks_invalid")
    normalized_layouts = _require_records(
        layout_records, "visual_bundle_layout_records_invalid"
    )
    config_sha256 = _require_sha256(
        config_sha256, "visual_bundle_config_sha256_invalid"
    )
    expected_source_sha256 = _require_sha256(
        expected_source_sha256, "visual_bundle_source_sha256_invalid"
    )
    expected_rhwp_sha256 = _require_sha256(
        expected_rhwp_sha256, "visual_bundle_rhwp_sha256_invalid"
    )
    if (
        not isinstance(command, str)
        or not Path(command).is_absolute()
        or not Path(command).is_file()
        or Path(command).is_symlink()
    ):
        raise ValueError("visual_bundle_rhwp_command_invalid")
    command_path = Path(command).resolve(strict=True)
    if _safe_sha256_file(command_path, "visual_bundle_rhwp_read_failed") != expected_rhwp_sha256:
        raise ValueError("visual_bundle_rhwp_checksum_mismatch")
    if (
        not isinstance(source_path, Path)
        or not source_path.is_file()
        or source_path.is_symlink()
    ):
        raise ValueError("visual_bundle_source_invalid")
    resolved_source = source_path.resolve(strict=True)
    if _safe_sha256_file(resolved_source, "visual_bundle_source_read_failed") != expected_source_sha256:
        raise ValueError("visual_bundle_source_checksum_mismatch")
    if expected_page_count is not None and (
        not isinstance(expected_page_count, int)
        or isinstance(expected_page_count, bool)
        or expected_page_count < 0
    ):
        raise ValueError("visual_bundle_page_count_invalid")

    lexical_private_root, resolved_private_root = _private_root(private_root)
    resolved_outputs = [
        _private_path(
            path,
            lexical_root=lexical_private_root,
            resolved_root=resolved_private_root,
            kind="file",
            error_code=error_code,
        )
        for path, error_code in (
            (table_output, "visual_bundle_table_output_invalid"),
            (image_output, "visual_bundle_image_output_invalid"),
            (ordered_output, "visual_bundle_ordered_output_invalid"),
            (metadata_output, "visual_bundle_metadata_output_invalid"),
        )
    ]
    resolved_asset_root = _private_path(
        asset_root,
        lexical_root=lexical_private_root,
        resolved_root=resolved_private_root,
        kind="directory",
        error_code="visual_bundle_asset_root_invalid",
    )
    if any(
        not output.is_file() or output.is_symlink() for output in resolved_outputs
    ) or not resolved_asset_root.is_dir():
        raise ValueError("visual_bundle_artifact_missing")

    metadata = _read_json_object(
        resolved_outputs[3], "visual_bundle_metadata_invalid"
    )
    if set(metadata) != _VISUAL_METADATA_FIELDS:
        raise ValueError("visual_bundle_metadata_invalid")
    table_records = _read_jsonl_objects(
        resolved_outputs[0], "visual_bundle_table_artifact_invalid"
    )
    image_records = _read_jsonl_objects(
        resolved_outputs[1], "visual_bundle_image_artifact_invalid"
    )
    _validate_image_source_contract(image_records)
    ordered_records = _read_jsonl_objects(
        resolved_outputs[2], "visual_bundle_ordered_artifact_invalid"
    )

    blocks_sha256 = _safe_canonical_hash(
        normalized_blocks, "visual_bundle_blocks_invalid"
    )
    layouts_sha256 = _safe_canonical_hash(
        normalized_layouts, "visual_bundle_layout_records_invalid"
    )
    table_sha256 = _safe_sha256_file(
        resolved_outputs[0], "visual_bundle_table_artifact_invalid"
    )
    image_sha256 = _safe_sha256_file(
        resolved_outputs[1], "visual_bundle_image_artifact_invalid"
    )
    ordered_sha256 = _safe_sha256_file(
        resolved_outputs[2], "visual_bundle_ordered_artifact_invalid"
    )
    page_count = metadata.get("page_count")
    if (
        not isinstance(page_count, int)
        or isinstance(page_count, bool)
        or page_count < 0
        or (expected_page_count is not None and page_count != expected_page_count)
    ):
        raise ValueError("visual_bundle_page_count_invalid")

    expected_table_ids = {
        block.get("block_id")
        for block in normalized_blocks
        if block.get("block_type") == "table"
    }
    actual_table_ids = [record.get("block_id") for record in table_records]
    if (
        None in expected_table_ids
        or len(expected_table_ids) != sum(
            block.get("block_type") == "table" for block in normalized_blocks
        )
        or len(actual_table_ids) != len(set(actual_table_ids))
        or set(actual_table_ids) != expected_table_ids
        or any(record.get("doc_id") != doc_id for record in table_records)
    ):
        raise ValueError("visual_bundle_table_reconciliation_failed")
    if any(record.get("doc_id") != doc_id for record in image_records):
        raise ValueError("visual_bundle_image_reconciliation_failed")
    occurrence_ids = [record.get("occurrence_id") for record in image_records]
    if None in occurrence_ids or len(occurrence_ids) != len(set(occurrence_ids)):
        raise ValueError("visual_bundle_image_reconciliation_failed")

    ordered_keys: list[tuple[int, int, str, str]] = []
    ordered_ids: list[Any] = []
    for record in ordered_records:
        page = record.get("page")
        sequence = record.get("sequence_in_page")
        if (
            record.get("doc_id") != doc_id
            or not isinstance(page, int)
            or isinstance(page, bool)
            or not 1 <= page <= page_count
            or not isinstance(sequence, int)
            or isinstance(sequence, bool)
            or sequence < 0
        ):
            raise ValueError("visual_bundle_ordered_reconciliation_failed")
        ordered_ids.append(record.get("ordered_occurrence_id"))
        ordered_keys.append(
            (
                page,
                sequence,
                str(record.get("node_type", "")),
                str(record.get("ordered_occurrence_id", "")),
            )
        )
    if (
        None in ordered_ids
        or len(ordered_ids) != len(set(ordered_ids))
        or ordered_keys != sorted(ordered_keys)
    ):
        raise ValueError("visual_bundle_ordered_reconciliation_failed")
    _validate_page_ranges(table_records, page_count=page_count)
    _validate_page_ranges(image_records, page_count=page_count)

    asset_manifest, asset_reference_count = _asset_manifest(
        image_records, asset_root=resolved_asset_root
    )
    asset_manifest_sha256 = _safe_canonical_hash(
        asset_manifest, "visual_bundle_asset_manifest_invalid"
    )
    identity = {
        "doc_id": doc_id,
        "source_sha256": expected_source_sha256,
        "rhwp_binary_sha256": expected_rhwp_sha256,
        "config_sha256": config_sha256,
        "blocks_sha256": blocks_sha256,
        "layout_records_sha256": layouts_sha256,
        "table_artifact_sha256": table_sha256,
        "image_artifact_sha256": image_sha256,
        "ordered_artifact_sha256": ordered_sha256,
        "asset_object_manifest_sha256": asset_manifest_sha256,
        "page_count": page_count,
    }
    expected_metadata = {
        "schema_version": VISUAL_BUNDLE_SCHEMA_VERSION,
        "doc_id": doc_id,
        "method": "rhwp-ordered-visual-evidence-v1",
        "coordinate_space": COORDINATE_SPACE,
        "source_sha256": expected_source_sha256,
        "rhwp_binary_sha256": expected_rhwp_sha256,
        "config_sha256": config_sha256,
        "blocks_sha256": blocks_sha256,
        "layout_records_sha256": layouts_sha256,
        "table_artifact_sha256": table_sha256,
        "image_artifact_sha256": image_sha256,
        "ordered_artifact_sha256": ordered_sha256,
        "asset_object_manifest_sha256": asset_manifest_sha256,
        "artifact_set_id": "visual_"
        + _safe_canonical_hash(identity, "visual_bundle_identity_invalid")[:24],
        "page_count": page_count,
        "tables": len(table_records),
        "images": len(image_records),
        "ordered_occurrences": len(ordered_records),
        "asset_count": len(asset_manifest),
        "asset_reference_count": asset_reference_count,
        "asset_bytes": sum(entry["byte_size"] for entry in asset_manifest),
        "asset_references_reconciled": True,
        "table_status_counts": _status_counts(table_records),
        "image_status_counts": _status_counts(image_records),
        "ordered_status_counts": _status_counts(ordered_records),
    }
    if metadata != expected_metadata:
        raise ValueError("visual_bundle_metadata_mismatch")
    return metadata


__all__ = [
    "VISUAL_BUNDLE_SCHEMA_VERSION",
    "materialize_hwp_visual_bundle",
    "verify_hwp_visual_bundle",
]
