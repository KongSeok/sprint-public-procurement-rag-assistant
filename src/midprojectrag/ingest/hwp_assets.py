from __future__ import annotations

import hashlib
import json
import math
import os
import re
import selectors
import shutil
import struct
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from midprojectrag.ingest.common import canonical_json


ASSET_SCHEMA_VERSION = "1.0"
COORDINATE_SPACE = "rhwp_css_px_96dpi"
MAX_XML_BYTES = 64 * 1024 * 1024
MAX_ASSET_BYTES = 64 * 1024 * 1024
MAX_TOTAL_ASSET_BYTES = 256 * 1024 * 1024
MAX_ASSET_COUNT = 10_000
MAX_DOCLANG_STDOUT_BYTES = 1024 * 1024
MAX_IMAGE_DIMENSION = 100_000
MAX_IMAGE_PIXELS = 100_000_000
READ_CHUNK_BYTES = 64 * 1024
ASPECT_RATIO_RELATIVE_TOLERANCE = 0.03

_DOC_ID_PATTERN = re.compile(r"^doc_[0-9a-f]{24}$")
_OCCURRENCE_ID_PATTERN = re.compile(r"^occ_[0-9a-f]{24}$")
_RHWP_ASSET_PREFIX_PATTERN = re.compile(
    r"^(section-[0-9]+-block-[0-9]+)(?:-|\.)"
)
_RHWP_ASSET_COORDINATE_PATH_PATTERN = re.compile(
    r"^section-[0-9]+-block-[0-9]+"
    r"(?:(?:-block|-ldiv)-[0-9]+|-cell-[0-9]+-[0-9]+)+"
    r"\.[^.]+$"
)
_RHWP_ASSET_CELL_COORDINATE_PATTERN = re.compile(
    r"-cell-[0-9]+-[0-9]+(?=-block-)"
)
_BBOX_FIELDS = ("x", "y", "w", "h")


@dataclass(frozen=True)
class _Asset:
    ordinal: int
    sha256: str
    relpath: str
    media_type: str
    extension: str
    byte_size: int
    width: int
    height: int
    source_sha256: str
    source_byte_size: int
    source_media_type: str
    source_extension: str | None
    normalizations: tuple[str, ...]


@dataclass(frozen=True)
class _UnsupportedAsset:
    ordinal: int
    source_sha256: str
    source_byte_size: int
    source_media_type: str
    source_extension: str | None
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _InspectedImage:
    data: bytes
    media_type: str
    extension: str
    width: int
    height: int
    normalizations: tuple[str, ...]


@dataclass(frozen=True)
class _PictureReference:
    uri: str
    linear_cell_indices: tuple[int, ...] | None


def _is_integer(value: Any, *, minimum: int = 0) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= minimum
    )


def _normalize_bbox(value: Any, error_code: str) -> dict[str, float]:
    if not isinstance(value, Mapping) or set(value) != set(_BBOX_FIELDS):
        raise ValueError(error_code)
    result: dict[str, float] = {}
    for field in _BBOX_FIELDS:
        raw = value.get(field)
        if (
            not isinstance(raw, (int, float))
            or isinstance(raw, bool)
            or not math.isfinite(float(raw))
        ):
            raise ValueError(error_code)
        result[field] = float(raw)
    if result["w"] <= 0 or result["h"] <= 0:
        raise ValueError(error_code)
    return result


def _normalize_render_key(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != {
        "section",
        "paragraph",
        "control",
    }:
        raise ValueError("render_image_key_invalid")
    result: dict[str, int] = {}
    for field in ("section", "paragraph", "control"):
        raw = value.get(field)
        if not _is_integer(raw):
            raise ValueError("render_image_key_invalid")
        result[field] = raw
    return result


def _normalize_preceding_text(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {
        "text",
        "bbox",
        "render_key",
        "method",
    }:
        raise ValueError("render_image_preceding_text_invalid")
    text = value.get("text")
    method = value.get("method")
    raw_key = value.get("render_key")
    if (
        not isinstance(text, str)
        or not text.strip()
        or len(text) > 500
        or method != "nearest_prior_top_level_textline"
        or not isinstance(raw_key, Mapping)
        or set(raw_key) != {"section", "paragraph"}
        or not _is_integer(raw_key.get("section"))
        or not _is_integer(raw_key.get("paragraph"))
    ):
        raise ValueError("render_image_preceding_text_invalid")
    return {
        "text": text,
        "bbox": _normalize_bbox(
            value.get("bbox"), "render_image_preceding_text_invalid"
        ),
        "render_key": {
            "section": raw_key["section"],
            "paragraph": raw_key["paragraph"],
        },
        "method": method,
    }


def _normalize_render_images(
    render_images: Sequence[Mapping[str, Any]], doc_id: str
) -> list[dict[str, Any]]:
    if isinstance(render_images, (str, bytes)) or not isinstance(
        render_images, Sequence
    ):
        raise ValueError("render_images_invalid")
    normalized: list[dict[str, Any]] = []
    seen_occurrences: set[str] = set()
    previous_order: tuple[int, int] | None = None
    for ordinal, raw in enumerate(render_images):
        if not isinstance(raw, Mapping):
            raise ValueError("render_image_invalid")
        occurrence_id = raw.get("occurrence_id")
        page = raw.get("page")
        sequence_in_page = raw.get("sequence_in_page")
        image_ordinal_in_page = raw.get("image_ordinal_in_page")
        container_kind = raw.get("container_kind")
        if (
            raw.get("schema_version") != ASSET_SCHEMA_VERSION
            or raw.get("doc_id") != doc_id
            or raw.get("node_type") != "image"
            or raw.get("status") != "render_only_unlinked"
            or raw.get("extraction_method") != "rhwp_render_tree_body_v1"
            or not isinstance(occurrence_id, str)
            or _OCCURRENCE_ID_PATTERN.fullmatch(occurrence_id) is None
            or occurrence_id in seen_occurrences
            or not _is_integer(page, minimum=1)
            or not _is_integer(sequence_in_page)
            or not _is_integer(image_ordinal_in_page)
            or container_kind not in {"body", "table_nested"}
            or raw.get("coordinate_space") != COORDINATE_SPACE
        ):
            raise ValueError("render_image_contract_invalid")
        order = (page, image_ordinal_in_page)
        if previous_order is not None and order <= previous_order:
            raise ValueError("render_images_order_invalid")
        previous_order = order
        seen_occurrences.add(occurrence_id)
        normalized.append(
            {
                "ordinal": ordinal,
                "occurrence_id": occurrence_id,
                "page": page,
                "sequence_in_page": sequence_in_page,
                "image_ordinal_in_page": image_ordinal_in_page,
                "container_kind": container_kind,
                "bbox": _normalize_bbox(
                    raw.get("bbox"), "render_image_bbox_invalid"
                ),
                "coordinate_space": COORDINATE_SPACE,
                "render_key": (
                    None
                    if raw.get("render_key") is None
                    else _normalize_render_key(raw.get("render_key"))
                ),
                "preceding_text": _normalize_preceding_text(
                    raw.get("preceding_text")
                ),
            }
        )
    return normalized


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _run_export_doclang(
    command: str,
    source_path: Path,
    workdir: Path,
    timeout_seconds: int,
) -> bytes:
    candidate = shutil.which(command)
    if candidate is None:
        raise ValueError("rhwp_doclang_launch_failed")
    command_path = Path(candidate)
    if (
        not command_path.is_file()
        or command_path.is_symlink()
        or not os.access(command_path, os.X_OK)
    ):
        raise ValueError("rhwp_doclang_launch_failed")

    argv = [
        str(command_path.resolve()),
        "export-doclang",
        str(source_path),
        "-o",
        "document.xml",
        "--assets-dir",
        "assets",
        "--json",
    ]
    try:
        process = subprocess.Popen(
            argv,
            cwd=workdir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise ValueError("rhwp_doclang_launch_failed") from None

    assert process.stdout is not None and process.stderr is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    stdout = bytearray()
    deadline = time.monotonic() + timeout_seconds
    failure: str | None = None
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failure = "rhwp_doclang_timeout"
                break
            for key, _ in selector.select(timeout=min(remaining, 0.25)):
                stream = key.fileobj
                chunk = os.read(stream.fileno(), READ_CHUNK_BYTES)
                if not chunk:
                    selector.unregister(stream)
                    stream.close()
                    continue
                if key.data == "stdout":
                    if len(stdout) + len(chunk) > MAX_DOCLANG_STDOUT_BYTES:
                        failure = "rhwp_doclang_output_too_large"
                        break
                    stdout.extend(chunk)
                # stderr is deliberately consumed and discarded. It may contain
                # a private source path or source text.
            if failure is not None:
                break
    except OSError:
        failure = "rhwp_doclang_io_failed"
    finally:
        selector.close()

    if failure is not None:
        _stop_process(process)
        for stream in (process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()
        raise ValueError(failure)
    remaining = deadline - time.monotonic()
    if remaining <= 0 and process.poll() is None:
        _stop_process(process)
        raise ValueError("rhwp_doclang_timeout")
    try:
        return_code = process.wait(timeout=max(0.0, remaining))
    except subprocess.TimeoutExpired:
        _stop_process(process)
        raise ValueError("rhwp_doclang_timeout") from None
    if return_code != 0:
        raise ValueError("rhwp_doclang_failed")
    return bytes(stdout)


def _parse_metadata(stdout: bytes) -> dict[str, int]:
    try:
        value = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError("rhwp_doclang_metadata_invalid") from None
    if (
        not isinstance(value, Mapping)
        or value.get("schemaVersion") != "1.0"
        or value.get("format") != "doclang"
        or value.get("output") != "document.xml"
        or value.get("assetsDir") != "assets"
        or value.get("untrustedContent") is not False
        or value.get("untrustedFields") != []
        or not _is_integer(value.get("bytes"))
        or not _is_integer(value.get("assetCount"))
        or not _is_integer(value.get("lossCount"))
    ):
        raise ValueError("rhwp_doclang_metadata_invalid")
    if value["assetCount"] > MAX_ASSET_COUNT:
        raise ValueError("rhwp_doclang_asset_count_exceeded")
    return {
        "xml_bytes": value["bytes"],
        "asset_count": value["assetCount"],
        "loss_count": value["lossCount"],
    }


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _picture_linear_cell_indices(
    picture: ET.Element,
    parents: Mapping[ET.Element, ET.Element],
) -> tuple[int, ...] | None:
    """Return explicit outer-to-inner DocLang table-cell ordinals.

    The pinned rhwp DocLang OTSL writer emits ``fcel`` for a populated anchor,
    ``ched`` for a populated header anchor, and ``ecel`` for an empty position.
    Those tokens consume the linear position used by the v0.8.4 asset name;
    ``lcel``/``ucel``/``xcel`` are merge continuations and do not.  Content may
    belong only to ``fcel`` or ``ched``.  Structural recovery is disabled when
    an ancestor relationship is incomplete or content follows any other grid
    token.
    """

    indices: list[int] = []
    node = picture
    while node in parents:
        parent = parents[node]
        if _local_name(parent.tag) == "table":
            cell_ordinal = -1
            active_cell_kind: str | None = None
            found_child = False
            for child in parent:
                child_kind = _local_name(child.tag)
                if child_kind in {"fcel", "ched", "ecel"}:
                    cell_ordinal += 1
                    active_cell_kind = child_kind
                elif child_kind in {"lcel", "ucel", "xcel", "nl"}:
                    active_cell_kind = child_kind
                if child is node:
                    found_child = True
                    break
            if (
                not found_child
                or cell_ordinal < 0
                or active_cell_kind not in {"fcel", "ched"}
            ):
                return None
            indices.append(cell_ordinal)
        node = parent
    indices.reverse()
    return tuple(indices)


def _picture_references(xml_bytes: bytes) -> list[_PictureReference]:
    upper = xml_bytes.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError("rhwp_doclang_xml_unsafe")
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValueError("rhwp_doclang_xml_invalid") from None

    parents = {child: parent for parent in root.iter() for child in parent}
    references: list[_PictureReference] = []
    seen: set[str] = set()
    for element in root.iter():
        if _local_name(element.tag) != "picture":
            continue
        sources = [
            child
            for child in element
            if _local_name(child.tag) == "src"
        ]
        if len(sources) != 1 or set(sources[0].attrib) != {"uri"}:
            raise ValueError("rhwp_doclang_picture_invalid")
        uri = sources[0].get("uri")
        if (
            not isinstance(uri, str)
            or not uri
            or "\x00" in uri
            or "\\" in uri
            or "%" in uri
            or uri in seen
        ):
            raise ValueError("rhwp_doclang_asset_uri_invalid")
        path = PurePosixPath(uri)
        if path.is_absolute() or ":" in path.parts[0]:
            raise ValueError("rhwp_doclang_asset_uri_invalid")
        seen.add(uri)
        references.append(
            _PictureReference(
                uri=uri,
                linear_cell_indices=_picture_linear_cell_indices(
                    element, parents
                ),
            )
        )
        if len(references) > MAX_ASSET_COUNT:
            raise ValueError("rhwp_doclang_asset_count_exceeded")
    return references


def _structural_linear_asset_name(
    name: str,
    linear_cell_indices: tuple[int, ...] | None,
) -> str | None:
    if (
        linear_cell_indices is None
        or _RHWP_ASSET_COORDINATE_PATH_PATTERN.fullmatch(name) is None
    ):
        return None
    coordinate_count = len(_RHWP_ASSET_CELL_COORDINATE_PATTERN.findall(name))
    if coordinate_count == 0 or coordinate_count != len(linear_cell_indices):
        return None
    indices = iter(linear_cell_indices)
    return _RHWP_ASSET_CELL_COORDINATE_PATTERN.sub(
        lambda _match: f"-cell-{next(indices)}",
        name,
    )


def _inventory_assets(root: Path) -> list[Path]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("rhwp_doclang_assets_root_invalid")
    files: list[Path] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            raise ValueError("rhwp_doclang_asset_inventory_failed") from None
        for entry in entries:
            try:
                if entry.is_symlink():
                    raise ValueError("rhwp_doclang_asset_symlink")
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    files.append(Path(entry.path))
                    if len(files) > MAX_ASSET_COUNT:
                        raise ValueError("rhwp_doclang_asset_count_exceeded")
                else:
                    raise ValueError("rhwp_doclang_asset_not_regular")
            except OSError as exc:
                raise ValueError("rhwp_doclang_asset_inventory_failed") from None
    return sorted(files)


def _resolve_asset_uri(
    reference: _PictureReference,
    xml_dir: Path,
    assets_root: Path,
    inventory: Sequence[Path],
) -> Path:
    uri = reference.uri
    raw_path = PurePosixPath(uri)
    candidate = xml_dir.joinpath(*raw_path.parts)
    try:
        resolved_root = assets_root.resolve(strict=True)
        resolved_candidate = candidate.resolve(strict=False)
        resolved_candidate.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise ValueError("rhwp_doclang_asset_path_escape") from None

    if candidate.exists() or candidate.is_symlink():
        if candidate.is_symlink():
            raise ValueError("rhwp_doclang_asset_symlink")
        try:
            resolved = candidate.resolve(strict=True)
            relative = resolved.relative_to(resolved_root)
        except (OSError, ValueError) as exc:
            raise ValueError("rhwp_doclang_asset_path_escape") from None
        current = resolved_root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("rhwp_doclang_asset_symlink")
        if not resolved.is_file() or resolved.is_symlink():
            raise ValueError("rhwp_doclang_asset_not_regular")
        return resolved

    # rhwp v0.8.4 can serialize a table-cell coordinate in the XML URI while
    # naming the emitted file with the equivalent linear cell index. Recover
    # only from an exact filename reconstructed from the picture's OTSL table
    # ancestry. XML picture order remains authoritative; prefix uniqueness,
    # picture ordinals, filename sorting, and inventory order are never used to
    # choose an asset.
    prefix_match = _RHWP_ASSET_PREFIX_PATTERN.match(candidate.name)
    if prefix_match is None:
        raise ValueError("rhwp_doclang_asset_uri_missing")
    try:
        expected_parent = candidate.parent.resolve(strict=True)
        expected_parent.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise ValueError("rhwp_doclang_asset_path_escape") from None
    expected_prefix = prefix_match.group(1)
    expected_suffix = candidate.suffix.casefold()
    matches = [
        path
        for path in inventory
        if path.parent == expected_parent
        and path.suffix.casefold() == expected_suffix
        and (
            (match := _RHWP_ASSET_PREFIX_PATTERN.match(path.name)) is not None
            and match.group(1) == expected_prefix
        )
    ]
    if not matches:
        raise ValueError("rhwp_doclang_asset_uri_missing")
    structural_name = _structural_linear_asset_name(
        candidate.name,
        reference.linear_cell_indices,
    )
    structural_matches = (
        [path for path in matches if path.name == structural_name]
        if structural_name is not None
        else []
    )
    if len(structural_matches) != 1:
        raise ValueError("rhwp_doclang_asset_uri_ambiguous")
    return structural_matches[0]


def _bounded_dimensions(width: int, height: int, error_code: str) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        raise ValueError(error_code)
    if (
        width > MAX_IMAGE_DIMENSION
        or height > MAX_IMAGE_DIMENSION
        or width * height > MAX_IMAGE_PIXELS
    ):
        raise ValueError("rhwp_doclang_asset_dimensions_exceeded")
    return width, height


def _png_info(data: bytes) -> tuple[int, int, int] | None:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    index = 8
    width = height = 0
    seen_ihdr = False
    seen_idat = False
    while index < len(data):
        if index + 12 > len(data):
            raise ValueError("rhwp_doclang_asset_invalid_png")
        chunk_size = struct.unpack(">I", data[index : index + 4])[0]
        chunk_type = data[index + 4 : index + 8]
        chunk_end = index + 12 + chunk_size
        if chunk_end > len(data):
            raise ValueError("rhwp_doclang_asset_invalid_png")
        payload = data[index + 8 : index + 8 + chunk_size]
        expected_crc = struct.unpack(">I", data[index + 8 + chunk_size : chunk_end])[0]
        if zlib.crc32(chunk_type + payload) & 0xFFFFFFFF != expected_crc:
            raise ValueError("rhwp_doclang_asset_invalid_png")
        if not seen_ihdr:
            if chunk_type != b"IHDR" or chunk_size != 13:
                raise ValueError("rhwp_doclang_asset_invalid_png")
            width, height, bit_depth, color_type, compression, filtering, interlace = (
                struct.unpack(">IIBBBBB", payload)
            )
            valid_depths = {
                0: {1, 2, 4, 8, 16},
                2: {8, 16},
                3: {1, 2, 4, 8},
                4: {8, 16},
                6: {8, 16},
            }
            if (
                bit_depth not in valid_depths.get(color_type, set())
                or compression != 0
                or filtering != 0
                or interlace not in {0, 1}
            ):
                raise ValueError("rhwp_doclang_asset_invalid_png")
            _bounded_dimensions(width, height, "rhwp_doclang_asset_invalid_png")
            seen_ihdr = True
        elif chunk_type == b"IHDR":
            raise ValueError("rhwp_doclang_asset_invalid_png")
        elif chunk_type == b"IDAT":
            seen_idat = True
        elif chunk_type == b"IEND":
            if chunk_size != 0 or not seen_idat:
                raise ValueError("rhwp_doclang_asset_invalid_png")
            return width, height, chunk_end
        index = chunk_end
    raise ValueError("rhwp_doclang_asset_invalid_png")


def _png_dimensions(data: bytes) -> tuple[int, int] | None:
    info = _png_info(data)
    return None if info is None else info[:2]


def _next_jpeg_marker(data: bytes, index: int) -> tuple[int, int, int]:
    if index >= len(data) or data[index] != 0xFF:
        raise ValueError("rhwp_doclang_asset_invalid_jpeg")
    marker_start = index
    while index < len(data) and data[index] == 0xFF:
        index += 1
    if index >= len(data) or data[index] == 0x00:
        raise ValueError("rhwp_doclang_asset_invalid_jpeg")
    return marker_start, data[index], index + 1


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    if not data.startswith(b"\xff\xd8"):
        return None
    index = 2
    sof_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    dimensions: tuple[int, int] | None = None
    seen_scan = False
    while index < len(data):
        _marker_start, marker, index = _next_jpeg_marker(data, index)
        if marker == 0xD9:
            if dimensions is None or not seen_scan or index != len(data):
                raise ValueError("rhwp_doclang_asset_invalid_jpeg")
            return dimensions
        if marker in {0x01, 0xD8} or 0xD0 <= marker <= 0xD7:
            continue
        if index + 2 > len(data):
            raise ValueError("rhwp_doclang_asset_invalid_jpeg")
        segment_length = struct.unpack(">H", data[index : index + 2])[0]
        if segment_length < 2 or index + segment_length > len(data):
            raise ValueError("rhwp_doclang_asset_invalid_jpeg")
        if marker in sof_markers:
            if segment_length < 11:
                raise ValueError("rhwp_doclang_asset_invalid_jpeg")
            height, width = struct.unpack(">HH", data[index + 3 : index + 7])
            components = data[index + 7]
            if components == 0 or segment_length != 8 + 3 * components:
                raise ValueError("rhwp_doclang_asset_invalid_jpeg")
            dimensions = _bounded_dimensions(
                width, height, "rhwp_doclang_asset_invalid_jpeg"
            )
        if marker == 0xDA:
            components = data[index + 2]
            if components == 0 or segment_length != 6 + 2 * components:
                raise ValueError("rhwp_doclang_asset_invalid_jpeg")
            seen_scan = True
            index += segment_length
            while index < len(data):
                marker_offset = data.find(b"\xff", index)
                if marker_offset < 0:
                    raise ValueError("rhwp_doclang_asset_invalid_jpeg")
                cursor = marker_offset + 1
                while cursor < len(data) and data[cursor] == 0xFF:
                    cursor += 1
                if cursor >= len(data):
                    raise ValueError("rhwp_doclang_asset_invalid_jpeg")
                entropy_marker = data[cursor]
                if entropy_marker == 0x00 or 0xD0 <= entropy_marker <= 0xD7:
                    index = cursor + 1
                    continue
                index = marker_offset
                break
            continue
        index += segment_length
    raise ValueError("rhwp_doclang_asset_invalid_jpeg")


def _bmp_dimensions(data: bytes) -> tuple[int, int] | None:
    if not data.startswith(b"BM"):
        return None
    if len(data) < 26:
        raise ValueError("rhwp_doclang_asset_invalid_bmp")
    declared_size = struct.unpack("<I", data[2:6])[0]
    pixel_offset = struct.unpack("<I", data[10:14])[0]
    if declared_size != len(data):
        raise ValueError("rhwp_doclang_asset_invalid_bmp")
    dib_size = struct.unpack("<I", data[14:18])[0]
    if dib_size == 12:
        width, height = struct.unpack("<HH", data[18:22])
        planes, bits_per_pixel = struct.unpack("<HH", data[22:26])
        compression = 0
        image_size = 0
    elif dib_size >= 40:
        if 14 + dib_size > len(data):
            raise ValueError("rhwp_doclang_asset_invalid_bmp")
        width, signed_height = struct.unpack("<ii", data[18:26])
        height = abs(signed_height)
        planes, bits_per_pixel = struct.unpack("<HH", data[26:30])
        compression = struct.unpack("<I", data[30:34])[0]
        image_size = struct.unpack("<I", data[34:38])[0]
    else:
        raise ValueError("rhwp_doclang_asset_invalid_bmp")
    dimensions = _bounded_dimensions(
        width, height, "rhwp_doclang_asset_invalid_bmp"
    )
    if (
        planes != 1
        or bits_per_pixel not in {1, 4, 8, 16, 24, 32}
        or compression != 0
        or pixel_offset < 14 + dib_size
        or pixel_offset > len(data)
    ):
        raise ValueError("rhwp_doclang_asset_invalid_bmp")
    row_bytes = ((width * bits_per_pixel + 31) // 32) * 4
    expected_pixels = row_bytes * height
    if pixel_offset + expected_pixels > len(data):
        raise ValueError("rhwp_doclang_asset_invalid_bmp")
    if image_size not in {0, expected_pixels}:
        raise ValueError("rhwp_doclang_asset_invalid_bmp")
    return dimensions


_TIFF_TYPE_SIZES = {
    1: 1,
    2: 1,
    3: 2,
    4: 4,
    5: 8,
    6: 1,
    7: 1,
    8: 2,
    9: 4,
    10: 8,
    11: 4,
    12: 8,
}


def _tiff_unsigned_values(
    data: bytes,
    *,
    endian: str,
    value_type: int,
    count: int,
    field: bytes,
) -> list[int]:
    if value_type not in {3, 4} or count < 1 or count > MAX_ASSET_COUNT:
        raise ValueError("rhwp_doclang_asset_invalid_tiff")
    item_size = _TIFF_TYPE_SIZES[value_type]
    total_size = item_size * count
    if total_size <= 4:
        raw = field[:total_size]
    else:
        offset = struct.unpack(f"{endian}I", field)[0]
        if offset > len(data) or total_size > len(data) - offset:
            raise ValueError("rhwp_doclang_asset_invalid_tiff")
        raw = data[offset : offset + total_size]
    code = "H" if value_type == 3 else "I"
    return list(struct.unpack(f"{endian}{count}{code}", raw))


def _tiff_dimensions(data: bytes) -> tuple[int, int] | None:
    if data.startswith(b"II*\x00"):
        endian = "<"
    elif data.startswith(b"MM\x00*"):
        endian = ">"
    else:
        return None
    if len(data) < 8:
        raise ValueError("rhwp_doclang_asset_invalid_tiff")
    ifd_offset = struct.unpack(f"{endian}I", data[4:8])[0]
    if ifd_offset + 2 > len(data):
        raise ValueError("rhwp_doclang_asset_invalid_tiff")
    entry_count = struct.unpack(
        f"{endian}H", data[ifd_offset : ifd_offset + 2]
    )[0]
    if entry_count > 4096 or ifd_offset + 2 + entry_count * 12 + 4 > len(data):
        raise ValueError("rhwp_doclang_asset_invalid_tiff")
    tags: dict[int, list[int]] = {}
    for index in range(entry_count):
        offset = ifd_offset + 2 + index * 12
        tag, value_type, count = struct.unpack(
            f"{endian}HHI", data[offset : offset + 8]
        )
        type_size = _TIFF_TYPE_SIZES.get(value_type)
        if type_size is None or count > MAX_ASSET_BYTES // type_size:
            raise ValueError("rhwp_doclang_asset_invalid_tiff")
        total_size = type_size * count
        if total_size > 4:
            value_offset = struct.unpack(
                f"{endian}I", data[offset + 8 : offset + 12]
            )[0]
            if value_offset > len(data) or total_size > len(data) - value_offset:
                raise ValueError("rhwp_doclang_asset_invalid_tiff")
        if tag not in {256, 257, 258, 259, 273, 277, 278, 279, 284, 324, 325}:
            continue
        field = data[offset + 8 : offset + 12]
        tags[tag] = _tiff_unsigned_values(
            data,
            endian=endian,
            value_type=value_type,
            count=count,
            field=field,
        )
    width = tags.get(256, [0])[0]
    height = tags.get(257, [0])[0]
    dimensions = _bounded_dimensions(
        width, height, "rhwp_doclang_asset_invalid_tiff"
    )
    strip_offsets = tags.get(273)
    strip_counts = tags.get(279)
    tile_offsets = tags.get(324)
    tile_counts = tags.get(325)
    if tile_offsets is not None or tile_counts is not None:
        if not tile_offsets or not tile_counts or len(tile_offsets) != len(tile_counts):
            raise ValueError("rhwp_doclang_asset_invalid_tiff")
        ranges = zip(tile_offsets, tile_counts, strict=True)
    elif strip_offsets:
        if strip_counts is None:
            compression = tags.get(259, [1])[0]
            samples = tags.get(277, [1])[0]
            planar = tags.get(284, [1])[0]
            bits = tags.get(258, [1])
            rows_per_strip = tags.get(278, [height])[0]
            if (
                compression != 1
                or planar != 1
                or samples < 1
                or rows_per_strip < 1
                or len(bits) not in {1, samples}
            ):
                raise ValueError("rhwp_doclang_asset_invalid_tiff")
            bits_per_pixel = sum(bits) if len(bits) == samples else bits[0] * samples
            row_bytes = (width * bits_per_pixel + 7) // 8
            remaining_rows = height
            inferred_counts: list[int] = []
            for _offset in strip_offsets:
                rows = min(rows_per_strip, remaining_rows)
                if rows <= 0:
                    raise ValueError("rhwp_doclang_asset_invalid_tiff")
                inferred_counts.append(row_bytes * rows)
                remaining_rows -= rows
            if remaining_rows != 0:
                raise ValueError("rhwp_doclang_asset_invalid_tiff")
            strip_counts = inferred_counts
        if len(strip_offsets) != len(strip_counts):
            raise ValueError("rhwp_doclang_asset_invalid_tiff")
        ranges = zip(strip_offsets, strip_counts, strict=True)
    else:
        raise ValueError("rhwp_doclang_asset_invalid_tiff")
    for data_offset, byte_count in ranges:
        if (
            byte_count <= 0
            or data_offset > len(data)
            or byte_count > len(data) - data_offset
        ):
            raise ValueError("rhwp_doclang_asset_invalid_tiff")
    return dimensions


def _wmf_info(data: bytes) -> tuple[int, bool] | None:
    """Validate a classic WMF record stream without attempting to render it."""
    standard_offset = 0
    if data.startswith(b"\xd7\xcd\xc6\x9a"):
        if len(data) < 22:
            raise ValueError("rhwp_doclang_asset_invalid_wmf")
        checksum = 0
        for word in struct.unpack("<10H", data[:20]):
            checksum ^= word
        stored_checksum = struct.unpack("<H", data[20:22])[0]
        inch = struct.unpack("<H", data[14:16])[0]
        if checksum != stored_checksum or inch == 0:
            raise ValueError("rhwp_doclang_asset_invalid_wmf")
        standard_offset = 22
    elif len(data) >= 4:
        file_type, header_words = struct.unpack("<HH", data[:4])
        if file_type not in {1, 2} or header_words != 9:
            return None
    else:
        return None

    if standard_offset + 18 > len(data):
        raise ValueError("rhwp_doclang_asset_invalid_wmf")
    (
        file_type,
        header_words,
        version,
        file_size_words,
        _object_count,
        max_record_words,
        parameter_count,
    ) = struct.unpack(
        "<HHHIHIH", data[standard_offset : standard_offset + 18]
    )
    if (
        file_type not in {1, 2}
        or header_words != 9
        or version not in {0x0100, 0x0300}
        or file_size_words < 12
        or max_record_words < 3
        or parameter_count != 0
    ):
        raise ValueError("rhwp_doclang_asset_invalid_wmf")
    payload_end = standard_offset + file_size_words * 2
    if payload_end > len(data):
        raise ValueError("rhwp_doclang_asset_invalid_wmf")

    position = standard_offset + 18
    saw_eof = False
    while position < payload_end:
        if position + 6 > payload_end:
            raise ValueError("rhwp_doclang_asset_invalid_wmf")
        record_words, function = struct.unpack("<IH", data[position : position + 6])
        record_end = position + record_words * 2
        if (
            record_words < 3
            or record_words > max_record_words
            or record_end > payload_end
        ):
            raise ValueError("rhwp_doclang_asset_invalid_wmf")
        position = record_end
        if function == 0:
            if record_words != 3 or position != payload_end:
                raise ValueError("rhwp_doclang_asset_invalid_wmf")
            saw_eof = True
            break
    if not saw_eof or position != payload_end:
        raise ValueError("rhwp_doclang_asset_invalid_wmf")
    return payload_end, payload_end != len(data)


def _gif_subblocks(data: bytes, position: int) -> tuple[int, int]:
    payload_bytes = 0
    while True:
        if position >= len(data):
            raise ValueError("rhwp_doclang_asset_invalid_gif")
        block_size = data[position]
        position += 1
        if block_size == 0:
            return position, payload_bytes
        if block_size > len(data) - position:
            raise ValueError("rhwp_doclang_asset_invalid_gif")
        payload_bytes += block_size
        position += block_size


def _gif_dimensions(data: bytes) -> tuple[int, int] | None:
    if not data.startswith((b"GIF87a", b"GIF89a")):
        return None
    if len(data) < 13:
        raise ValueError("rhwp_doclang_asset_invalid_gif")
    width, height = struct.unpack("<HH", data[6:10])
    dimensions = _bounded_dimensions(
        width, height, "rhwp_doclang_asset_invalid_gif"
    )
    packed = data[10]
    position = 13
    if packed & 0x80:
        table_bytes = 3 * (1 << ((packed & 0x07) + 1))
        if table_bytes > len(data) - position:
            raise ValueError("rhwp_doclang_asset_invalid_gif")
        position += table_bytes

    frame_count = 0
    frame_pixels = 0
    while position < len(data):
        marker = data[position]
        position += 1
        if marker == 0x3B:
            if frame_count == 0 or position != len(data):
                raise ValueError("rhwp_doclang_asset_invalid_gif")
            return dimensions
        if marker == 0x21:
            if position >= len(data):
                raise ValueError("rhwp_doclang_asset_invalid_gif")
            position += 1  # extension label
            position, _ = _gif_subblocks(data, position)
            continue
        if marker != 0x2C or position + 9 > len(data):
            raise ValueError("rhwp_doclang_asset_invalid_gif")
        left, top, image_width, image_height = struct.unpack(
            "<HHHH", data[position : position + 8]
        )
        image_packed = data[position + 8]
        position += 9
        _bounded_dimensions(
            image_width, image_height, "rhwp_doclang_asset_invalid_gif"
        )
        if left + image_width > width or top + image_height > height:
            raise ValueError("rhwp_doclang_asset_invalid_gif")
        frame_count += 1
        frame_pixels += image_width * image_height
        if frame_count > MAX_ASSET_COUNT or frame_pixels > MAX_IMAGE_PIXELS:
            raise ValueError("rhwp_doclang_asset_dimensions_exceeded")
        if image_packed & 0x80:
            table_bytes = 3 * (1 << ((image_packed & 0x07) + 1))
            if table_bytes > len(data) - position:
                raise ValueError("rhwp_doclang_asset_invalid_gif")
            position += table_bytes
        if position >= len(data) or not 2 <= data[position] <= 8:
            raise ValueError("rhwp_doclang_asset_invalid_gif")
        position += 1
        position, payload_bytes = _gif_subblocks(data, position)
        if payload_bytes == 0:
            raise ValueError("rhwp_doclang_asset_invalid_gif")
    raise ValueError("rhwp_doclang_asset_invalid_gif")


def _inspect_supported_image(data: bytes, suffix: str) -> _InspectedImage | None:
    source_extension = suffix.casefold()
    png_info = _png_info(data)
    if png_info is not None:
        width, height, payload_end = png_info
        normalizations: list[str] = []
        if source_extension != ".png":
            normalizations.append("source_extension_canonicalized")
        if payload_end != len(data):
            normalizations.append("png_trailing_bytes_removed")
        return _InspectedImage(
            data=data[:payload_end],
            media_type="image/png",
            extension=".png",
            width=width,
            height=height,
            normalizations=tuple(normalizations),
        )

    probes = (
        (_jpeg_dimensions, "image/jpeg", ".jpg", {".jpg", ".jpeg"}),
        (_bmp_dimensions, "image/bmp", ".bmp", {".bmp"}),
        (_tiff_dimensions, "image/tiff", ".tif", {".tif", ".tiff"}),
    )
    for probe, media_type, canonical_extension, allowed_extensions in probes:
        dimensions = probe(data)
        if dimensions is None:
            continue
        normalizations = (
            ()
            if source_extension in allowed_extensions
            else ("source_extension_canonicalized",)
        )
        return _InspectedImage(
            data=data,
            media_type=media_type,
            extension=canonical_extension,
            width=dimensions[0],
            height=dimensions[1],
            normalizations=normalizations,
        )
    return None


def _inspect_image(data: bytes, suffix: str) -> tuple[str, str, int, int]:
    inspected = _inspect_supported_image(data, suffix)
    if inspected is None:
        raise ValueError("rhwp_doclang_asset_magic_unknown")
    return (
        inspected.media_type,
        inspected.extension,
        inspected.width,
        inspected.height,
    )


def _copy_content_addressed(
    *, data: bytes, output_root: Path, sha256: str, extension: str
) -> str:
    objects = output_root / "objects"
    try:
        objects.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError("rhwp_doclang_output_write_failed") from None
    if objects.is_symlink():
        raise ValueError("rhwp_doclang_output_symlink")
    destination = objects / f"{sha256}{extension}"
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_file():
            raise ValueError("rhwp_doclang_output_collision")
        try:
            existing_size = destination.stat().st_size
            if existing_size != len(data) or existing_size > MAX_ASSET_BYTES:
                raise ValueError("rhwp_doclang_output_collision")
            existing = destination.read_bytes()
        except OSError:
            raise ValueError("rhwp_doclang_output_write_failed") from None
        if hashlib.sha256(existing).hexdigest() != sha256 or existing != data:
            raise ValueError("rhwp_doclang_output_collision")
    else:
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{sha256}.", dir=objects
            )
        except OSError:
            raise ValueError("rhwp_doclang_output_write_failed") from None
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
        except OSError:
            raise ValueError("rhwp_doclang_output_write_failed") from None
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return destination.relative_to(output_root).as_posix()


def _load_assets(
    *,
    references: Sequence[_PictureReference],
    xml_dir: Path,
    assets_root: Path,
    output_root: Path,
) -> list[_Asset | _UnsupportedAsset]:
    try:
        inventory = [path.resolve(strict=True) for path in _inventory_assets(assets_root)]
    except OSError as exc:
        raise ValueError("rhwp_doclang_asset_inventory_failed") from None
    resolved_paths = [
        _resolve_asset_uri(reference, xml_dir, assets_root, inventory)
        for reference in references
    ]
    if len(set(resolved_paths)) != len(resolved_paths):
        raise ValueError("rhwp_doclang_asset_duplicate")
    if set(inventory) != set(resolved_paths):
        raise ValueError("rhwp_doclang_asset_inventory_mismatch")

    prepared: list[
        tuple[int, _InspectedImage, str, int, str | None] | _UnsupportedAsset
    ] = []
    total_bytes = 0
    for ordinal, path in enumerate(resolved_paths):
        try:
            byte_size = path.stat().st_size
        except OSError as exc:
            raise ValueError("rhwp_doclang_asset_read_failed") from None
        if byte_size > MAX_ASSET_BYTES:
            raise ValueError("rhwp_doclang_asset_too_large")
        total_bytes += byte_size
        if total_bytes > MAX_TOTAL_ASSET_BYTES:
            raise ValueError("rhwp_doclang_assets_total_too_large")
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ValueError("rhwp_doclang_asset_read_failed") from None
        if len(data) != byte_size:
            raise ValueError("rhwp_doclang_asset_size_changed")
        source_digest = hashlib.sha256(data).hexdigest()
        source_extension = path.suffix.casefold() or None
        inspected = _inspect_supported_image(data, path.suffix)
        if inspected is not None:
            prepared.append(
                (
                    ordinal,
                    inspected,
                    source_digest,
                    byte_size,
                    source_extension,
                )
            )
            continue

        wmf_info = _wmf_info(data)
        if wmf_info is not None:
            _payload_end, has_trailing_bytes = wmf_info
            warnings = ["image_format_unsupported"]
            if has_trailing_bytes:
                warnings.append("wmf_trailing_bytes_present")
            prepared.append(
                _UnsupportedAsset(
                    ordinal=ordinal,
                    source_sha256=source_digest,
                    source_byte_size=byte_size,
                    source_media_type="image/wmf",
                    source_extension=source_extension,
                    warnings=tuple(warnings),
                )
            )
            continue

        gif_dimensions = _gif_dimensions(data)
        if gif_dimensions is not None:
            prepared.append(
                _UnsupportedAsset(
                    ordinal=ordinal,
                    source_sha256=source_digest,
                    source_byte_size=byte_size,
                    source_media_type="image/gif",
                    source_extension=source_extension,
                    warnings=("image_format_unsupported",),
                )
            )
            continue
        raise ValueError("rhwp_doclang_asset_magic_unknown")

    # Validate every source asset before persisting any object. A malformed
    # later picture therefore cannot leave an apparently successful prefix.
    assets: list[_Asset | _UnsupportedAsset] = []
    for item in prepared:
        if isinstance(item, _UnsupportedAsset):
            assets.append(item)
            continue
        ordinal, inspected, source_digest, source_byte_size, source_extension = item
        digest = hashlib.sha256(inspected.data).hexdigest()
        relpath = _copy_content_addressed(
            data=inspected.data,
            output_root=output_root,
            sha256=digest,
            extension=inspected.extension,
        )
        assets.append(
            _Asset(
                ordinal=ordinal,
                sha256=digest,
                relpath=relpath,
                media_type=inspected.media_type,
                extension=inspected.extension,
                byte_size=len(inspected.data),
                width=inspected.width,
                height=inspected.height,
                source_sha256=source_digest,
                source_byte_size=source_byte_size,
                source_media_type=inspected.media_type,
                source_extension=source_extension,
                normalizations=inspected.normalizations,
            )
        )
    return assets


def _stable_id(prefix: str, value: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:24]}"


def _asset_fields(asset: _Asset | None, doc_id: str) -> dict[str, Any]:
    if asset is None:
        return {
            "asset_id": None,
            "asset_sha256": None,
            "asset_relpath": None,
            "media_type": None,
            "byte_size": None,
            "width": None,
            "height": None,
        }
    return {
        "asset_id": _stable_id(
            "asset", {"doc_id": doc_id, "asset_sha256": asset.sha256}
        ),
        "asset_sha256": asset.sha256,
        "asset_relpath": asset.relpath,
        "media_type": asset.media_type,
        "byte_size": asset.byte_size,
        "width": asset.width,
        "height": asset.height,
    }


def _source_fields(
    asset: _Asset | _UnsupportedAsset | None,
) -> dict[str, Any]:
    if asset is None:
        return {
            "source_asset_sha256": None,
            "source_byte_size": None,
            "source_media_type": None,
            "source_extension": None,
            "normalizations": [],
        }
    return {
        "source_asset_sha256": asset.source_sha256,
        "source_byte_size": asset.source_byte_size,
        "source_media_type": asset.source_media_type,
        "source_extension": asset.source_extension,
        "normalizations": (
            list(asset.normalizations) if isinstance(asset, _Asset) else []
        ),
    }


def _render_fields(render: Mapping[str, Any] | None) -> dict[str, Any]:
    if render is None:
        return {
            "page_start": None,
            "page_end": None,
            "bbox": None,
            "coordinate_space": None,
            "render_key": None,
            "sequence_in_page": None,
            "image_ordinal_in_page": None,
            "container_kind": None,
            "preceding_text": None,
        }
    return {
        "page_start": render["page"],
        "page_end": render["page"],
        "bbox": render["bbox"],
        "coordinate_space": render["coordinate_space"],
        "render_key": render["render_key"],
        "sequence_in_page": render["sequence_in_page"],
        "image_ordinal_in_page": render["image_ordinal_in_page"],
        "container_kind": render["container_kind"],
        "preceding_text": render["preceding_text"],
    }


def _aspect_ratio_matches(asset: _Asset, render: Mapping[str, Any]) -> bool:
    intrinsic = asset.width / asset.height
    display = render["bbox"]["w"] / render["bbox"]["h"]
    return (
        abs(intrinsic - display) / max(abs(intrinsic), abs(display))
        <= ASPECT_RATIO_RELATIVE_TOLERANCE
    )


def _linked_record(
    *,
    doc_id: str,
    asset: _Asset,
    render: Mapping[str, Any],
    loss_count: int,
) -> dict[str, Any]:
    return {
        "schema_version": ASSET_SCHEMA_VERSION,
        "occurrence_id": render["occurrence_id"],
        "doc_id": doc_id,
        "ordinal": asset.ordinal,
        "node_type": "image",
        "status": "verified_asset_render",
        **_asset_fields(asset, doc_id),
        **_source_fields(asset),
        **_render_fields(render),
        "link_method": "doclang_picture_render_image_global_ordinal_exact_count",
        "doclang_loss_count": loss_count,
        "warnings": [],
    }


def _asset_only_record(
    *,
    doc_id: str,
    asset: _Asset,
    loss_count: int,
    warning: str,
) -> dict[str, Any]:
    occurrence_id = _stable_id(
        "occ",
        {
            "doc_id": doc_id,
            "ordinal": asset.ordinal,
            "asset_sha256": asset.sha256,
            "status": "asset_only_unlinked",
        },
    )
    return {
        "schema_version": ASSET_SCHEMA_VERSION,
        "occurrence_id": occurrence_id,
        "doc_id": doc_id,
        "ordinal": asset.ordinal,
        "node_type": "image",
        "status": "asset_only_unlinked",
        **_asset_fields(asset, doc_id),
        **_source_fields(asset),
        **_render_fields(None),
        "link_method": "doclang_picture_unlinked",
        "doclang_loss_count": loss_count,
        "warnings": [warning],
    }


def _unsupported_source_record(
    *,
    doc_id: str,
    asset: _UnsupportedAsset,
    loss_count: int,
) -> dict[str, Any]:
    occurrence_id = _stable_id(
        "occ",
        {
            "doc_id": doc_id,
            "ordinal": asset.ordinal,
            "source_asset_sha256": asset.source_sha256,
            "status": "unsupported_source_asset",
        },
    )
    return {
        "schema_version": ASSET_SCHEMA_VERSION,
        "occurrence_id": occurrence_id,
        "doc_id": doc_id,
        "ordinal": asset.ordinal,
        "node_type": "image",
        "status": "unsupported_source_asset",
        **_asset_fields(None, doc_id),
        **_source_fields(asset),
        **_render_fields(None),
        "link_method": "doclang_picture_unsupported_unlinked",
        "doclang_loss_count": loss_count,
        "warnings": list(asset.warnings),
    }


def _render_only_record(
    *,
    doc_id: str,
    render: Mapping[str, Any],
    loss_count: int,
    warning: str,
) -> dict[str, Any]:
    return {
        "schema_version": ASSET_SCHEMA_VERSION,
        "occurrence_id": render["occurrence_id"],
        "doc_id": doc_id,
        "ordinal": render["ordinal"],
        "node_type": "image",
        "status": "render_only_missing_asset",
        **_asset_fields(None, doc_id),
        **_source_fields(None),
        **_render_fields(render),
        "link_method": "render_image_unlinked",
        "doclang_loss_count": loss_count,
        "warnings": [warning],
    }


def materialize_hwp_assets(
    *,
    command: str,
    source_path: Path,
    doc_id: str,
    render_images: Sequence[Mapping[str, Any]],
    output_root: Path,
    timeout_seconds: int = 120,
) -> list[dict[str, Any]]:
    """Extract HWP picture bytes and link them to independent render evidence.

    Linkage is deliberately all-or-nothing: every DocLang picture and Body
    RenderTree image must have the same global ordinal count and compatible
    aspect ratio. Page breaks in DocLang are never used as page evidence.
    Raised ``ValueError`` messages are stable error codes and contain no path or
    source content.
    """
    if not isinstance(doc_id, str) or _DOC_ID_PATTERN.fullmatch(doc_id) is None:
        raise ValueError("doc_id_invalid")
    if not isinstance(command, str) or not command or "\x00" in command:
        raise ValueError("rhwp_doclang_launch_failed")
    if not isinstance(source_path, Path):
        raise ValueError("hwp_asset_source_invalid")
    if (
        not source_path.is_file()
        or source_path.is_symlink()
        or not isinstance(timeout_seconds, int)
        or isinstance(timeout_seconds, bool)
        or timeout_seconds <= 0
    ):
        raise ValueError("hwp_asset_source_invalid")
    if not isinstance(output_root, Path):
        raise ValueError("hwp_asset_output_invalid")
    try:
        output_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError("hwp_asset_output_invalid") from None
    if not output_root.is_dir() or output_root.is_symlink():
        raise ValueError("hwp_asset_output_invalid")

    try:
        resolved_source = source_path.resolve(strict=True)
    except OSError:
        raise ValueError("hwp_asset_source_invalid") from None

    normalized_render = _normalize_render_images(render_images, doc_id)
    with tempfile.TemporaryDirectory(
        prefix="midprojectrag-hwp-assets-", ignore_cleanup_errors=True
    ) as name:
        workdir = Path(name)
        try:
            (workdir / "assets").mkdir()
        except OSError:
            raise ValueError("rhwp_doclang_assets_root_invalid") from None
        stdout = _run_export_doclang(
            command,
            resolved_source,
            workdir,
            timeout_seconds,
        )
        metadata = _parse_metadata(stdout)
        xml_path = workdir / "document.xml"
        try:
            xml_size = xml_path.stat().st_size
        except OSError as exc:
            raise ValueError("rhwp_doclang_xml_size_invalid") from None
        if (
            not xml_path.is_file()
            or xml_path.is_symlink()
            or xml_size > MAX_XML_BYTES
            or xml_size != metadata["xml_bytes"]
        ):
            raise ValueError("rhwp_doclang_xml_size_invalid")
        try:
            xml_bytes = xml_path.read_bytes()
        except OSError as exc:
            raise ValueError("rhwp_doclang_xml_read_failed") from None
        references = _picture_references(xml_bytes)
        if len(references) != metadata["asset_count"]:
            raise ValueError("rhwp_doclang_asset_count_mismatch")
        source_assets = _load_assets(
            references=references,
            xml_dir=workdir,
            assets_root=workdir / "assets",
            output_root=output_root,
        )

    loss_count = metadata["loss_count"]
    unsupported_assets = [
        asset for asset in source_assets if isinstance(asset, _UnsupportedAsset)
    ]
    assets = [asset for asset in source_assets if isinstance(asset, _Asset)]
    if unsupported_assets:
        warning = "image_unsupported_source_asset_present"
        source_records = [
            (
                _asset_only_record(
                    doc_id=doc_id,
                    asset=asset,
                    loss_count=loss_count,
                    warning=warning,
                )
                if isinstance(asset, _Asset)
                else _unsupported_source_record(
                    doc_id=doc_id,
                    asset=asset,
                    loss_count=loss_count,
                )
            )
            for asset in source_assets
        ]
        return [
            *source_records,
            *[
                _render_only_record(
                    doc_id=doc_id,
                    render=render,
                    loss_count=loss_count,
                    warning=warning,
                )
                for render in normalized_render
            ],
        ]

    counts_match = len(assets) == len(normalized_render)
    render_keys_present = counts_match and all(
        render.get("render_key") is not None for render in normalized_render
    )
    aspects_match = render_keys_present and all(
        _aspect_ratio_matches(asset, render)
        for asset, render in zip(assets, normalized_render, strict=True)
    )
    if counts_match and aspects_match:
        return [
            _linked_record(
                doc_id=doc_id,
                asset=asset,
                render=render,
                loss_count=loss_count,
            )
            for asset, render in zip(assets, normalized_render, strict=True)
        ]

    warning = (
        "image_count_mismatch"
        if not counts_match
        else (
            "image_render_key_missing"
            if not render_keys_present
            else "image_aspect_ratio_mismatch"
        )
    )
    return [
        *[
            _asset_only_record(
                doc_id=doc_id,
                asset=asset,
                loss_count=loss_count,
                warning=warning,
            )
            for asset in assets
        ],
        *[
            _render_only_record(
                doc_id=doc_id,
                render=render,
                loss_count=loss_count,
                warning=warning,
            )
            for render in normalized_render
        ],
    ]
