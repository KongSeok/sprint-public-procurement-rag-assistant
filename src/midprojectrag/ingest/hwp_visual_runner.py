"""Durable, offline HWP visual-v2 corpus runner.

The runner treats the JavaScript bridge as an untrusted, checksum-pinned
process.  It validates the bridge envelope and every referenced private asset,
converts placements through the shared HWP occurrence adapter, derives
deterministic page crops, and atomically publishes a corpus.  Returned metadata
contains aggregate counts and hashes only.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import selectors
import signal
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from midprojectrag.ingest.common import canonical_json, sha256_file, sha256_text
from midprojectrag.ingest.hwp_visual_v2 import recover_hwp_occurrences
from midprojectrag.ingest.visual_evidence import (
    build_visual_corpus_metadata,
    crop_page_region,
    load_jsonl_bounded,
    normalize_bbox,
    stable_id,
    validate_visual_occurrence,
    write_jsonl_artifact,
)
from midprojectrag.ingest.visual_gold import validate_visual_gold


HWP_VISUAL_RUNNER_VERSION = "1.0"
HWP_VISUAL_RUNNER_METHOD = "rhwp-core-local-visual-v2"
OCCURRENCE_ARTIFACT = "occurrences-v2.jsonl"
HELPER_MANIFEST_ARTIFACT = "helper-manifest-v2.jsonl"
OBJECT_MANIFEST_ARTIFACT = "object-manifest-v2.jsonl"
METADATA_ARTIFACT = "metadata.json"

_DOC_ID_RE = re.compile(r"^doc_[0-9a-f]{24}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HELPER_FIELDS = frozenset(
    {
        "schema_version",
        "helper",
        "doc_id",
        "source_sha256",
        "dependency_pins",
        "render_profile",
        "occurrences",
        "source_objects",
        "source_assets",
        "page_sizes",
        "page_renders",
        "unresolved",
        "counts",
    }
)
_SOURCE_ASSET_FIELDS = frozenset(
    {
        "source_ordinal",
        "source_image_key_sha256",
        "source_object_sha256",
        "source_object_media_type",
        "byte_size",
        "relpath",
    }
)
_PAGE_SIZE_FIELDS = frozenset(
    {"page", "width", "height", "coordinate_page_bbox"}
)
_PAGE_RENDER_FIELDS = frozenset(
    {
        "page",
        "width",
        "height",
        "coordinate_page_bbox",
        "page_render_sha256",
        "relpath",
        "render_profile",
    }
)
_HELPER_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "doc_id",
        "source_sha256",
        "blocks_sha256",
        "helper_output_sha256",
        "occurrences_sha256",
        "source_objects_sha256",
        "source_assets_sha256",
        "page_renders_sha256",
        "render_profile_sha256",
        "dependency_pins",
        "counts",
        "unresolved_counts",
    }
)
_OBJECT_MANIFEST_FIELDS = frozenset(
    {"relpath", "sha256", "byte_size", "media_type", "roles"}
)


class HwpVisualRunnerError(ValueError):
    """Sanitized, stable runner failure."""


@dataclass(frozen=True, slots=True)
class HwpVisualRunnerLimits:
    max_manifest_bytes: int = 64 * 1024 * 1024
    max_manifest_records: int = 10_000
    max_selection_bytes: int = 4 * 1024 * 1024
    max_gold_bytes: int = 16 * 1024 * 1024
    max_source_bytes_per_document: int = 512 * 1024 * 1024
    max_blocks_bytes_per_document: int = 128 * 1024 * 1024
    max_helper_output_bytes: int = 64 * 1024 * 1024
    max_subprocess_stdout_bytes: int = 1024 * 1024
    max_subprocess_stderr_bytes: int = 1024 * 1024
    max_occurrences: int = 100_000
    max_assets: int = 100_000

    def __post_init__(self) -> None:
        maxima = {
            "max_manifest_bytes": 256 * 1024 * 1024,
            "max_manifest_records": 100_000,
            "max_selection_bytes": 16 * 1024 * 1024,
            "max_gold_bytes": 64 * 1024 * 1024,
            "max_source_bytes_per_document": 2 * 1024 * 1024 * 1024,
            "max_blocks_bytes_per_document": 512 * 1024 * 1024,
            "max_helper_output_bytes": 128 * 1024 * 1024,
            "max_subprocess_stdout_bytes": 16 * 1024 * 1024,
            "max_subprocess_stderr_bytes": 16 * 1024 * 1024,
            "max_occurrences": 1_000_000,
            "max_assets": 1_000_000,
        }
        for name, maximum in maxima.items():
            value = getattr(self, name)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 1
                or value > maximum
            ):
                raise HwpVisualRunnerError("hwp_visual_runner_limits_invalid")


DEFAULT_HWP_VISUAL_RUNNER_LIMITS = HwpVisualRunnerLimits()


def _fail(code: str) -> None:
    raise HwpVisualRunnerError(code)


def _require_sha256(value: Any, code: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        _fail(code)
    return value


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _decode_json(payload: bytes, code: str) -> Any:
    try:
        return json.loads(
            payload.decode("utf-8"),
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
            object_pairs_hook=_strict_pairs,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError):
        _fail(code)


def _safe_existing_directory(path: Path, code: str) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or path.is_symlink():
        _fail(code)
    normalized = Path(os.path.abspath(str(path)))
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        _fail(code)
    if resolved != normalized or not resolved.is_dir():
        _fail(code)
    return resolved


def _reject_symlink_components(root: Path, relative: Path, code: str) -> None:
    cursor = root
    for component in relative.parts:
        cursor = cursor / component
        if cursor.is_symlink():
            _fail(code)


def _safe_contained_file(
    path: Path,
    root: Path,
    code: str,
    *,
    max_bytes: int | None = None,
) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or path.is_symlink():
        _fail(code)
    normalized = Path(os.path.abspath(str(path)))
    try:
        relative = normalized.relative_to(root)
        resolved = path.resolve(strict=True)
    except (OSError, ValueError):
        _fail(code)
    _reject_symlink_components(root, relative, code)
    if resolved != normalized or not resolved.is_file():
        _fail(code)
    if max_bytes is not None:
        try:
            size = resolved.stat().st_size
        except OSError:
            _fail(code)
        if size < 1 or size > max_bytes:
            _fail(f"{code}_size_exceeded")
    return resolved


def _safe_pinned_file(path: Path, expected_sha256: str, code: str) -> Path:
    expected = _require_sha256(expected_sha256, f"{code}_sha256_invalid")
    if not isinstance(path, Path) or not path.is_absolute() or path.is_symlink():
        _fail(code)
    normalized = Path(os.path.abspath(str(path)))
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        _fail(code)
    if resolved != normalized or not resolved.is_file():
        _fail(code)
    try:
        actual = sha256_file(resolved)
    except OSError:
        _fail(code)
    if actual != expected:
        _fail(f"{code}_hash_mismatch")
    return resolved


def _safe_output_target(output: Path, private_root: Path) -> Path:
    if not isinstance(output, Path) or not output.is_absolute() or output.is_symlink():
        _fail("hwp_visual_runner_output_invalid")
    normalized = Path(os.path.abspath(str(output)))
    try:
        relative = normalized.relative_to(private_root)
    except ValueError:
        _fail("hwp_visual_runner_output_escape")
    if not relative.parts:
        _fail("hwp_visual_runner_output_invalid")
    _reject_symlink_components(
        private_root, relative, "hwp_visual_runner_output_symlink_forbidden"
    )
    if normalized.exists() and not normalized.is_dir():
        _fail("hwp_visual_runner_output_invalid")
    return normalized


def _bounded_bytes(path: Path, maximum: int, code: str) -> bytes:
    try:
        size = path.stat().st_size
        if size < 1 or size > maximum:
            _fail(code)
        payload = path.read_bytes()
    except HwpVisualRunnerError:
        raise
    except OSError:
        _fail(code)
    if len(payload) != size:
        _fail(code)
    return payload


def _read_jsonl_bytes(
    payload: bytes, *, maximum_records: int, code: str
) -> list[dict[str, Any]]:
    try:
        text = payload.decode("utf-8")
    except UnicodeError:
        _fail(code)
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            _fail(code)
        value = _decode_json(line.encode("utf-8"), code)
        if not isinstance(value, dict):
            _fail(code)
        rows.append(value)
        if len(rows) > maximum_records:
            _fail(f"{code}_limit_exceeded")
    if not rows:
        _fail(code)
    return rows


def _safe_relative_asset(value: Any, root: Path, code: str) -> tuple[str, Path]:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or "\\" in value
    ):
        _fail(code)
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        _fail(code)
    native = Path(*relative.parts)
    destination = _safe_contained_file(root / native, root, code)
    return relative.as_posix(), destination


def _path_from_manifest(value: Any, data_root: Path, root: Path, code: str) -> Path:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or "\\" in value
    ):
        _fail(code)
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        _fail(code)
    candidate = data_root.joinpath(*relative.parts)
    return _safe_contained_file(candidate, root, code)


def _manifest_rows(
    manifest: Path, limits: HwpVisualRunnerLimits
) -> tuple[bytes, list[dict[str, Any]]]:
    payload = _bounded_bytes(
        manifest, limits.max_manifest_bytes, "hwp_visual_runner_manifest_invalid"
    )
    return payload, _read_jsonl_bytes(
        payload,
        maximum_records=limits.max_manifest_records,
        code="hwp_visual_runner_manifest_invalid",
    )


def _manifest_index(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        doc_id = row.get("doc_id")
        if not isinstance(doc_id, str) or _DOC_ID_RE.fullmatch(doc_id) is None:
            _fail("hwp_visual_runner_manifest_record_invalid")
        if doc_id in result:
            _fail("hwp_visual_runner_manifest_doc_duplicate")
        result[doc_id] = row
    return result


def _eligible_hwp(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    selected = [
        row
        for row in rows
        if row.get("extension") == ".hwp"
        and row.get("status") == "ok"
        and row.get("index_eligible") is True
    ]
    if not selected:
        _fail("hwp_visual_runner_no_eligible_hwp")
    return sorted(selected, key=lambda row: str(row["doc_id"]))


def _selection_ids(
    selection: Path,
    *,
    manifest_sha256: str,
    limits: HwpVisualRunnerLimits,
) -> tuple[str, list[str]]:
    payload = _bounded_bytes(
        selection,
        limits.max_selection_bytes,
        "hwp_visual_runner_selection_invalid",
    )
    value = _decode_json(payload, "hwp_visual_runner_selection_invalid")
    if not isinstance(value, Mapping) or value.get("schema_version") != "1.0":
        _fail("hwp_visual_runner_selection_invalid")
    if value.get("source_manifest_sha256") != manifest_sha256:
        _fail("hwp_visual_runner_selection_manifest_mismatch")
    documents = value.get("documents")
    if (
        not isinstance(documents, list)
        or isinstance(documents, (str, bytes))
        or not 1 <= len(documents) <= 5
    ):
        _fail("hwp_visual_runner_selection_invalid")
    doc_ids: list[str] = []
    for document in documents:
        doc_id = document.get("doc_id") if isinstance(document, Mapping) else None
        if not isinstance(doc_id, str) or _DOC_ID_RE.fullmatch(doc_id) is None:
            _fail("hwp_visual_runner_selection_invalid")
        doc_ids.append(doc_id)
    if len(doc_ids) != len(set(doc_ids)):
        _fail("hwp_visual_runner_selection_duplicate")
    return hashlib.sha256(payload).hexdigest(), doc_ids


def _validate_gold_gate(
    gold_path: Path,
    *,
    manifest_index: Mapping[str, Mapping[str, Any]],
    representative_doc_ids: Sequence[str],
    limits: HwpVisualRunnerLimits,
) -> str:
    payload = _bounded_bytes(
        gold_path, limits.max_gold_bytes, "hwp_visual_runner_gold_invalid"
    )
    annotations = _read_jsonl_bytes(
        payload,
        maximum_records=100_000,
        code="hwp_visual_runner_gold_invalid",
    )
    try:
        validate_visual_gold(
            annotations,
            require_reviewed=True,
            require_full_representative_gate=True,
        )
    except ValueError:
        _fail("hwp_visual_runner_gold_gate_failed")
    hwp_docs = {
        str(row["doc_id"])
        for row in annotations
        if row.get("source_format") == "hwp"
    }
    if hwp_docs != set(representative_doc_ids) or len(hwp_docs) != 5:
        _fail("hwp_visual_runner_gold_gate_failed")
    for annotation in annotations:
        manifest_row = manifest_index.get(str(annotation.get("doc_id")))
        if (
            manifest_row is None
            or manifest_row.get("sha256") != annotation.get("source_sha256")
        ):
            _fail("hwp_visual_runner_gold_manifest_mismatch")
    return hashlib.sha256(payload).hexdigest()


def _verified_document(
    row: Mapping[str, Any],
    *,
    data_root: Path,
    blocks_root: Path,
    limits: HwpVisualRunnerLimits,
) -> tuple[str, str, Path, Path, str]:
    doc_id = row.get("doc_id")
    source_sha256 = row.get("sha256")
    if not isinstance(doc_id, str) or _DOC_ID_RE.fullmatch(doc_id) is None:
        _fail("hwp_visual_runner_doc_id_invalid")
    _require_sha256(source_sha256, "hwp_visual_runner_source_sha256_invalid")
    source = _path_from_manifest(
        row.get("source_relpath"),
        data_root,
        data_root,
        "hwp_visual_runner_source_path_invalid",
    )
    blocks = _path_from_manifest(
        row.get("output_relpath"),
        data_root,
        blocks_root,
        "hwp_visual_runner_blocks_path_invalid",
    )
    try:
        source_size = source.stat().st_size
        blocks_size = blocks.stat().st_size
    except OSError:
        _fail("hwp_visual_runner_input_stat_failed")
    if source_size < 1 or source_size > limits.max_source_bytes_per_document:
        _fail("hwp_visual_runner_source_size_exceeded")
    if blocks_size < 1 or blocks_size > limits.max_blocks_bytes_per_document:
        _fail("hwp_visual_runner_blocks_size_exceeded")
    expected_size = row.get("size_bytes")
    if expected_size is not None and (
        not isinstance(expected_size, int)
        or isinstance(expected_size, bool)
        or expected_size != source_size
    ):
        _fail("hwp_visual_runner_source_size_mismatch")
    try:
        actual_source_sha256 = sha256_file(source)
        blocks_sha256 = sha256_file(blocks)
    except OSError:
        _fail("hwp_visual_runner_input_hash_failed")
    if actual_source_sha256 != source_sha256:
        _fail("hwp_visual_runner_source_hash_mismatch")
    return doc_id, source_sha256, source, blocks, blocks_sha256


def _kill_process(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            process.kill()
        except OSError:
            pass


def _bounded_subprocess(
    command: Sequence[str],
    *,
    timeout_seconds: float,
    stdout_limit: int,
    stderr_limit: int,
    cwd: Path,
) -> tuple[bytes, bytes]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT"}
    }
    environment.update(
        {
            "HTTP_PROXY": "",
            "HTTPS_PROXY": "",
            "ALL_PROXY": "",
            "NO_PROXY": "*",
            "MIDPROJECTRAG_NETWORK": "disabled",
        }
    )
    try:
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError:
        _fail("hwp_visual_runner_helper_start_failed")
    assert process.stdout is not None and process.stderr is not None
    streams = {process.stdout: (bytearray(), stdout_limit), process.stderr: (bytearray(), stderr_limit)}
    selector = selectors.DefaultSelector()
    for stream in streams:
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout_seconds
    overflow = False
    timed_out = False
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                _kill_process(process)
                break
            events = selector.select(min(remaining, 0.1))
            if not events and process.poll() is not None:
                events = [
                    (selector.get_key(stream), selectors.EVENT_READ)
                    for stream in list(streams)
                    if stream.fileno() in selector.get_map()
                ]
            for key, _ in events:
                stream = key.fileobj
                try:
                    chunk = os.read(stream.fileno(), 65_536)
                except BlockingIOError:
                    continue
                if not chunk:
                    try:
                        selector.unregister(stream)
                    except KeyError:
                        pass
                    continue
                buffer, maximum = streams[stream]
                buffer.extend(chunk)
                if len(buffer) > maximum:
                    overflow = True
                    _kill_process(process)
                    break
            if overflow:
                break
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            _kill_process(process)
            process.wait(timeout=2)
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()
    if timed_out:
        _fail("hwp_visual_runner_helper_timeout")
    if overflow:
        _fail("hwp_visual_runner_helper_stdio_limit_exceeded")
    stdout = bytes(streams[process.stdout][0])
    stderr = bytes(streams[process.stderr][0])
    if process.returncode != 0 or stderr.strip():
        _fail("hwp_visual_runner_helper_failed")
    return stdout, stderr


def _canonical_list_sha256(values: Sequence[Mapping[str, Any]]) -> str:
    return sha256_text("".join(canonical_json(value) + "\n" for value in values))


def _nonnegative_int(value: Any, code: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        _fail(code)
    return value


def _positive_number(value: Any, code: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0
    ):
        _fail(code)
    return float(value)


def _verify_png(path: Path, *, width: int, height: int, code: str) -> None:
    try:
        from PIL import Image
    except ImportError:
        _fail("hwp_visual_runner_pillow_unavailable")
    try:
        with Image.open(path) as image:
            image.load()
            if image.format != "PNG" or image.size != (width, height):
                _fail(code)
    except HwpVisualRunnerError:
        raise
    except (OSError, ValueError):
        _fail(code)


def _object_manifest_row(
    *, relpath: str, path: Path, digest: str, media_type: str, role: str
) -> dict[str, Any]:
    _require_sha256(digest, "hwp_visual_runner_asset_hash_invalid")
    try:
        size = path.stat().st_size
    except OSError:
        _fail("hwp_visual_runner_asset_invalid")
    return {
        "relpath": relpath,
        "sha256": digest,
        "byte_size": size,
        "media_type": media_type,
        "roles": [role],
    }


def _validate_helper_envelope(
    envelope: Any,
    *,
    doc_id: str,
    source_sha256: str,
    stage_root: Path,
    dependency_pins: Mapping[str, str],
    limits: HwpVisualRunnerLimits,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[int, dict[str, Any]], list[dict[str, Any]]]:
    code = "hwp_visual_runner_helper_contract_invalid"
    if not isinstance(envelope, Mapping) or set(envelope) != _HELPER_FIELDS:
        _fail(code)
    if (
        envelope.get("schema_version") != "1.0"
        or envelope.get("helper") != "rhwp_visual_helper"
        or envelope.get("doc_id") != doc_id
        or envelope.get("source_sha256") != source_sha256
        or envelope.get("dependency_pins")
        != {
            "core_js_sha256": dependency_pins["core_js_sha256"],
            "wasm_sha256": dependency_pins["wasm_sha256"],
            "canvas_entry_sha256": dependency_pins["canvas_entry_sha256"],
        }
        or envelope.get("render_profile")
        != {
            "profile": "screen",
            "omit_image_bytes": True,
            "coordinate_space": "rhwp_css_px_96dpi",
            "bbox_match_tolerance_px": 0.125,
        }
    ):
        _fail(code)
    occurrences = envelope.get("occurrences")
    source_objects = envelope.get("source_objects")
    source_assets = envelope.get("source_assets")
    page_sizes = envelope.get("page_sizes")
    page_renders = envelope.get("page_renders")
    if any(
        not isinstance(value, list)
        for value in (occurrences, source_objects, source_assets, page_sizes, page_renders)
    ):
        _fail(code)
    if len(occurrences) > limits.max_occurrences or len(source_assets) > limits.max_assets:
        _fail("hwp_visual_runner_helper_limit_exceeded")

    normalized_page_sizes: dict[int, dict[str, Any]] = {}
    for raw in page_sizes:
        if not isinstance(raw, Mapping) or set(raw) != _PAGE_SIZE_FIELDS:
            _fail(code)
        page = raw.get("page")
        if not isinstance(page, int) or isinstance(page, bool) or page < 1 or page in normalized_page_sizes:
            _fail(code)
        width = _positive_number(raw.get("width"), code)
        height = _positive_number(raw.get("height"), code)
        try:
            page_bbox = normalize_bbox(raw.get("coordinate_page_bbox"), error_code=code)
        except ValueError:
            _fail(code)
        if abs(page_bbox["w"] - width) > 0.125 or abs(page_bbox["h"] - height) > 0.125:
            _fail(code)
        normalized_page_sizes[page] = {
            "page": page,
            "width": width,
            "height": height,
            "coordinate_page_bbox": page_bbox,
        }
    if sorted(normalized_page_sizes) != list(range(1, len(normalized_page_sizes) + 1)):
        _fail(code)

    object_rows: list[dict[str, Any]] = []
    source_by_ordinal: dict[int, Mapping[str, Any]] = {}
    for raw in source_objects:
        if not isinstance(raw, Mapping):
            _fail(code)
        ordinal = raw.get("source_ordinal")
        if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 0 or ordinal in source_by_ordinal:
            _fail(code)
        source_by_ordinal[ordinal] = raw
    seen_asset_paths: set[str] = set()
    for raw in source_assets:
        if not isinstance(raw, Mapping) or set(raw) != _SOURCE_ASSET_FIELDS:
            _fail(code)
        ordinal = raw.get("source_ordinal")
        source = source_by_ordinal.get(ordinal) if isinstance(ordinal, int) else None
        digest = raw.get("source_object_sha256")
        media_type = raw.get("source_object_media_type")
        key_sha = raw.get("source_image_key_sha256")
        if (
            source is None
            or source.get("source_object_sha256") != digest
            or source.get("source_object_media_type") != media_type
            or not isinstance(media_type, str)
        ):
            _fail(code)
        source_key = source.get("source_image_key")
        expected_key_sha = None if source_key is None else sha256_text(str(source_key))
        if key_sha != expected_key_sha:
            _fail(code)
        _require_sha256(digest, code)
        relpath, asset_path = _safe_relative_asset(raw.get("relpath"), stage_root, code)
        if relpath in seen_asset_paths:
            _fail(code)
        seen_asset_paths.add(relpath)
        expected_size = raw.get("byte_size")
        if (
            not isinstance(expected_size, int)
            or isinstance(expected_size, bool)
            or expected_size < 1
            or asset_path.stat().st_size != expected_size
            or sha256_file(asset_path) != digest
        ):
            _fail("hwp_visual_runner_helper_asset_mismatch")
        object_rows.append(
            _object_manifest_row(
                relpath=relpath,
                path=asset_path,
                digest=digest,
                media_type=media_type,
                role="source_object",
            )
        )
    if set(source_by_ordinal) != {
        int(raw["source_ordinal"]) for raw in source_assets if isinstance(raw, Mapping)
    }:
        _fail(code)

    renders: dict[int, dict[str, Any]] = {}
    for raw in page_renders:
        if not isinstance(raw, Mapping) or set(raw) != _PAGE_RENDER_FIELDS:
            _fail(code)
        page = raw.get("page")
        size = normalized_page_sizes.get(page) if isinstance(page, int) else None
        width = raw.get("width")
        height = raw.get("height")
        digest = raw.get("page_render_sha256")
        profile = raw.get("render_profile")
        if (
            size is None
            or page in renders
            or not isinstance(width, int)
            or isinstance(width, bool)
            or not isinstance(height, int)
            or isinstance(height, bool)
            or width != math.ceil(size["width"])
            or height != math.ceil(size["height"])
            or raw.get("coordinate_page_bbox") != size["coordinate_page_bbox"]
            or profile
            != {
                "renderer": "rhwp_core_renderPageSvg+napi_canvas+data_uri_overlay",
                "profile": "screen",
                "scale": 1,
                "pixel_rounding": "ceil",
            }
        ):
            _fail(code)
        _require_sha256(digest, code)
        relpath, render_path = _safe_relative_asset(raw.get("relpath"), stage_root, code)
        if relpath in seen_asset_paths or sha256_file(render_path) != digest:
            _fail("hwp_visual_runner_page_render_mismatch")
        seen_asset_paths.add(relpath)
        _verify_png(
            render_path,
            width=width,
            height=height,
            code="hwp_visual_runner_page_render_invalid",
        )
        renders[page] = {
            "path": render_path,
            "relpath": relpath,
            "page_render_sha256": digest,
            "coordinate_page_bbox": size["coordinate_page_bbox"],
            "render_profile": dict(profile),
        }
        object_rows.append(
            _object_manifest_row(
                relpath=relpath,
                path=render_path,
                digest=digest,
                media_type="image/png",
                role="page_render",
            )
        )

    placed_pages = {
        raw.get("page") for raw in occurrences if isinstance(raw, Mapping)
    }
    if placed_pages != set(renders):
        _fail("hwp_visual_runner_page_render_coverage_mismatch")

    unresolved = envelope.get("unresolved")
    expected_unresolved = {
        "bbox_match_ambiguous",
        "source_anchor_unresolved",
        "source_key_not_listed",
        "inline_bytes_invalid",
    }
    if not isinstance(unresolved, Mapping) or set(unresolved) != expected_unresolved:
        _fail(code)
    normalized_unresolved = {
        key: _nonnegative_int(value, code) for key, value in unresolved.items()
    }
    counts = envelope.get("counts")
    count_fields = {
        "page_count",
        "pages_with_image_ops",
        "image_ops_total",
        "placed_occurrences",
        "unresolved_occurrences",
        "source_objects",
        "source_assets",
        "unsupported_source_objects",
        "page_renders",
    }
    if not isinstance(counts, Mapping) or set(counts) != count_fields:
        _fail(code)
    normalized_counts = {key: _nonnegative_int(value, code) for key, value in counts.items()}
    if (
        normalized_counts["page_count"] != len(page_sizes)
        or normalized_counts["placed_occurrences"] != len(occurrences)
        or normalized_counts["source_objects"] != len(source_objects)
        or normalized_counts["source_assets"] != len(source_assets)
        or normalized_counts["page_renders"] != len(page_renders)
        or normalized_counts["unsupported_source_objects"]
        != sum(
            1
            for raw in source_objects
            if isinstance(raw, Mapping) and raw.get("supported") is False
        )
        or normalized_counts["image_ops_total"]
        != normalized_counts["placed_occurrences"]
        + normalized_counts["unresolved_occurrences"]
        or not len(placed_pages)
        <= normalized_counts["pages_with_image_ops"]
        <= normalized_counts["page_count"]
    ):
        _fail(code)
    return (
        [dict(value) for value in occurrences],
        [dict(value) for value in source_objects],
        renders,
        sorted(object_rows, key=lambda row: str(row["relpath"])),
    )


def _merge_object_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_path: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping) or set(raw) != _OBJECT_MANIFEST_FIELDS:
            _fail("hwp_visual_runner_object_manifest_invalid")
        row = dict(raw)
        relpath = row["relpath"]
        existing = by_path.get(relpath)
        if existing is None:
            by_path[relpath] = row
        elif any(existing[field] != row[field] for field in ("sha256", "byte_size", "media_type")):
            _fail("hwp_visual_runner_object_collision")
        else:
            existing["roles"] = sorted(set(existing["roles"]) | set(row["roles"]))
    return [by_path[key] for key in sorted(by_path)]


def _atomic_write(path: Path, payload: bytes, code: str) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.name}-", suffix=".tmp", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        _fail(code)


def _adapter_code_sha256() -> str:
    from midprojectrag.ingest import hwp_visual_v2, visual_evidence

    return sha256_text(
        canonical_json(
            {
                "runner": sha256_file(Path(__file__).resolve()),
                "hwp_visual_v2": sha256_file(Path(hwp_visual_v2.__file__).resolve()),
                "visual_evidence": sha256_file(Path(visual_evidence.__file__).resolve()),
            }
        )
    )


def _metadata_identity_matches(
    metadata: Mapping[str, Any],
    *,
    source_manifest_sha256: str,
    adapter_code_sha256: str,
    config_sha256: str,
    dependency_versions: Mapping[str, str],
) -> bool:
    return (
        metadata.get("source_manifest_sha256") == source_manifest_sha256
        and metadata.get("adapter_code_sha256") == adapter_code_sha256
        and metadata.get("config_sha256") == config_sha256
        and metadata.get("dependency_versions") == dict(sorted(dependency_versions.items()))
    )


def _verify_existing(
    output_dir: Path,
    *,
    source_manifest_sha256: str,
    adapter_code_sha256: str,
    config: Mapping[str, Any],
    dependency_versions: Mapping[str, str],
    expected_existing_artifact_set_id: str | None,
) -> dict[str, Any]:
    metadata_path = output_dir / METADATA_ARTIFACT
    if not metadata_path.is_file() or metadata_path.is_symlink():
        _fail("hwp_visual_runner_stale_artifact_identity")
    payload = _bounded_bytes(
        metadata_path, 1024 * 1024, "hwp_visual_runner_stale_artifact_identity"
    )
    metadata = _decode_json(payload, "hwp_visual_runner_stale_artifact_identity")
    if not isinstance(metadata, Mapping):
        _fail("hwp_visual_runner_stale_artifact_identity")
    config_sha256 = sha256_text(canonical_json(config))
    if not _metadata_identity_matches(
        metadata,
        source_manifest_sha256=source_manifest_sha256,
        adapter_code_sha256=adapter_code_sha256,
        config_sha256=config_sha256,
        dependency_versions=dependency_versions,
    ):
        _fail("hwp_visual_runner_stale_artifact_identity")
    artifact_files = {
        "occurrences_v2_jsonl": OCCURRENCE_ARTIFACT,
        "helper_manifest_v2_jsonl": HELPER_MANIFEST_ARTIFACT,
        "object_manifest_v2_jsonl": OBJECT_MANIFEST_ARTIFACT,
    }
    hashes = metadata.get("artifact_hashes")
    if not isinstance(hashes, Mapping) or set(hashes) != set(artifact_files):
        _fail("hwp_visual_runner_artifact_reconciliation_failed")
    for key, filename in artifact_files.items():
        artifact = output_dir / filename
        if (
            not artifact.is_file()
            or artifact.is_symlink()
            or sha256_file(artifact) != hashes.get(key)
        ):
            _fail("hwp_visual_runner_artifact_reconciliation_failed")
    try:
        occurrences = load_jsonl_bounded(output_dir / OCCURRENCE_ARTIFACT)
        for occurrence in occurrences:
            validate_visual_occurrence(occurrence)
        helper_rows = load_jsonl_bounded(output_dir / HELPER_MANIFEST_ARTIFACT)
        object_rows = load_jsonl_bounded(output_dir / OBJECT_MANIFEST_ARTIFACT)
    except ValueError:
        _fail("hwp_visual_runner_artifact_reconciliation_failed")
    for row in helper_rows:
        if not isinstance(row, Mapping) or set(row) != _HELPER_MANIFEST_FIELDS:
            _fail("hwp_visual_runner_artifact_reconciliation_failed")
    for row in object_rows:
        if not isinstance(row, Mapping) or set(row) != _OBJECT_MANIFEST_FIELDS:
            _fail("hwp_visual_runner_artifact_reconciliation_failed")
        relpath, path = _safe_relative_asset(
            row.get("relpath"), output_dir, "hwp_visual_runner_artifact_reconciliation_failed"
        )
        roles = row.get("roles")
        if (
            relpath != row.get("relpath")
            or not isinstance(roles, list)
            or not roles
            or roles != sorted(set(roles))
            or path.stat().st_size != row.get("byte_size")
            or sha256_file(path) != row.get("sha256")
        ):
            _fail("hwp_visual_runner_artifact_reconciliation_failed")
    expected = build_visual_corpus_metadata(
        source_manifest_sha256=source_manifest_sha256,
        adapter_code_sha256=adapter_code_sha256,
        config=config,
        dependency_versions=dependency_versions,
        occurrences=occurrences,
        ocr_count=0,
        caption_count=0,
        chunk_count=0,
        artifact_hashes=dict(hashes),
    )
    if dict(metadata) != expected:
        _fail("hwp_visual_runner_stale_artifact_identity")
    if expected_existing_artifact_set_id is not None and (
        expected_existing_artifact_set_id != expected["artifact_set_id"]
    ):
        _fail("hwp_visual_runner_stale_artifact_identity")
    return expected


def run_hwp_visual_v2_from_manifest(
    *,
    manifest_path: Path,
    data_dir: Path,
    blocks_dir: Path,
    selection_path: Path,
    output_dir: Path,
    private_root: Path,
    node_executable: Path,
    node_sha256: str,
    helper_path: Path,
    helper_sha256: str,
    core_js_path: Path,
    core_js_sha256: str,
    wasm_path: Path,
    wasm_sha256: str,
    canvas_module_path: Path,
    canvas_module_sha256: str,
    mode: str = "representative",
    visual_gold_path: Path | None = None,
    timeout_seconds: float = 180.0,
    expected_existing_artifact_set_id: str | None = None,
    limits: HwpVisualRunnerLimits = DEFAULT_HWP_VISUAL_RUNNER_LIMITS,
) -> dict[str, Any]:
    """Build representative or gated full-corpus HWP visual-v2 artifacts.

    Representative mode processes one to five document IDs from the pinned
    selection file.  Corpus mode requires five-document/four-PDF reviewed gold
    and processes exactly all 94 eligible HWP manifest rows.
    """

    if mode not in {"representative", "corpus"}:
        _fail("hwp_visual_runner_mode_invalid")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(float(timeout_seconds))
        or not 1 <= float(timeout_seconds) <= 3600
    ):
        _fail("hwp_visual_runner_timeout_invalid")

    data_root = _safe_existing_directory(data_dir, "hwp_visual_runner_data_dir_invalid")
    private = _safe_existing_directory(private_root, "hwp_visual_runner_private_root_invalid")
    if private == data_root or not private.is_relative_to(data_root):
        _fail("hwp_visual_runner_private_root_invalid")
    blocks_root = _safe_existing_directory(blocks_dir, "hwp_visual_runner_blocks_dir_invalid")
    if not blocks_root.is_relative_to(private):
        _fail("hwp_visual_runner_blocks_dir_invalid")
    manifest = _safe_contained_file(
        manifest_path,
        private,
        "hwp_visual_runner_manifest_outside_private_root",
        max_bytes=limits.max_manifest_bytes,
    )
    selection = _safe_contained_file(
        selection_path,
        private,
        "hwp_visual_runner_selection_outside_private_root",
        max_bytes=limits.max_selection_bytes,
    )
    output = _safe_output_target(output_dir, private)

    node = _safe_pinned_file(
        node_executable, node_sha256, "hwp_visual_runner_node_invalid"
    )
    helper = _safe_pinned_file(
        helper_path, helper_sha256, "hwp_visual_runner_helper_invalid"
    )
    core_js = _safe_pinned_file(
        core_js_path, core_js_sha256, "hwp_visual_runner_core_js_invalid"
    )
    wasm = _safe_pinned_file(
        wasm_path, wasm_sha256, "hwp_visual_runner_wasm_invalid"
    )
    canvas = _safe_pinned_file(
        canvas_module_path,
        canvas_module_sha256,
        "hwp_visual_runner_canvas_invalid",
    )

    manifest_bytes, rows = _manifest_rows(manifest, limits)
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    index = _manifest_index(rows)
    eligible = _eligible_hwp(rows)
    eligible_by_id = {str(row["doc_id"]): row for row in eligible}
    selection_sha256, representative_ids = _selection_ids(
        selection, manifest_sha256=manifest_sha256, limits=limits
    )
    if any(doc_id not in eligible_by_id for doc_id in representative_ids):
        _fail("hwp_visual_runner_selection_not_eligible")

    gold_sha256: str | None = None
    if mode == "corpus":
        if visual_gold_path is None:
            _fail("hwp_visual_runner_gold_gate_required")
        gold = _safe_contained_file(
            visual_gold_path,
            private,
            "hwp_visual_runner_gold_outside_private_root",
            max_bytes=limits.max_gold_bytes,
        )
        gold_sha256 = _validate_gold_gate(
            gold,
            manifest_index=index,
            representative_doc_ids=representative_ids,
            limits=limits,
        )
        if len(eligible) != 94:
            _fail("hwp_visual_runner_corpus_count_mismatch")
        selected_rows = eligible
    else:
        if visual_gold_path is not None:
            _fail("hwp_visual_runner_gold_not_allowed_in_representative_mode")
        selected_rows = [eligible_by_id[doc_id] for doc_id in representative_ids]

    verified_documents = [
        _verified_document(
            row,
            data_root=data_root,
            blocks_root=blocks_root,
            limits=limits,
        )
        for row in selected_rows
    ]
    verified_documents.sort(key=lambda value: value[0])
    selected_inputs_sha256 = sha256_text(
        canonical_json(
            [
                {
                    "doc_id": doc_id,
                    "source_sha256": source_sha256,
                    "blocks_sha256": blocks_sha256,
                }
                for doc_id, source_sha256, _, _, blocks_sha256 in verified_documents
            ]
        )
    )
    pins = {
        "node_sha256": node_sha256,
        "helper_sha256": helper_sha256,
        "core_js_sha256": core_js_sha256,
        "wasm_sha256": wasm_sha256,
        "canvas_entry_sha256": canvas_module_sha256,
    }
    dependency_versions = {
        "node-executable": f"sha256:{node_sha256}",
        "rhwp-visual-helper": f"sha256:{helper_sha256}",
        "@rhwp/core-js": f"sha256:{core_js_sha256}",
        "@rhwp/core-wasm": f"sha256:{wasm_sha256}",
        "@napi-rs/canvas-entry": f"sha256:{canvas_module_sha256}",
        "runner": HWP_VISUAL_RUNNER_VERSION,
    }
    config = {
        "method": HWP_VISUAL_RUNNER_METHOD,
        "runner_version": HWP_VISUAL_RUNNER_VERSION,
        "mode": mode,
        "selection_sha256": selection_sha256,
        "gold_sha256": gold_sha256,
        "selected_inputs_sha256": selected_inputs_sha256,
        "document_count": len(verified_documents),
        "timeout_seconds": float(timeout_seconds),
        "limits": asdict(limits),
        "network": "disabled_by_contract",
        "render_profile": (
            "rhwp_core_renderPageSvg+napi_canvas+data_uri_overlay-screen-v1"
        ),
    }
    adapter_code_sha256 = _adapter_code_sha256()
    if output.exists():
        return _verify_existing(
            output,
            source_manifest_sha256=manifest_sha256,
            adapter_code_sha256=adapter_code_sha256,
            config=config,
            dependency_versions=dependency_versions,
            expected_existing_artifact_set_id=expected_existing_artifact_set_id,
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    output = _safe_output_target(output, private)
    if output.exists():
        return _verify_existing(
            output,
            source_manifest_sha256=manifest_sha256,
            adapter_code_sha256=adapter_code_sha256,
            config=config,
            dependency_versions=dependency_versions,
            expected_existing_artifact_set_id=expected_existing_artifact_set_id,
        )

    try:
        with tempfile.TemporaryDirectory(
            prefix=".hwp-visual-v2-stage-",
            dir=output.parent,
            ignore_cleanup_errors=True,
        ) as stage_name:
            stage = Path(stage_name).resolve(strict=True)
            all_occurrences: list[dict[str, Any]] = []
            helper_manifest: list[dict[str, Any]] = []
            object_rows: list[dict[str, Any]] = []
            for doc_id, source_sha256, source, blocks, blocks_sha256 in verified_documents:
                helper_output = stage / "helper-output" / f"{doc_id}.json"
                helper_output.parent.mkdir(parents=True, exist_ok=True)
                asset_dir = stage / "source-objects" / doc_id
                render_dir = stage / "page-renders" / doc_id
                command = [
                    str(node),
                    str(helper),
                    "--input",
                    str(source),
                    "--blocks",
                    str(blocks),
                    "--doc-id",
                    doc_id,
                    "--source-sha256",
                    source_sha256,
                    "--core-js",
                    str(core_js),
                    "--core-js-sha256",
                    core_js_sha256,
                    "--wasm",
                    str(wasm),
                    "--wasm-sha256",
                    wasm_sha256,
                    "--canvas-module",
                    str(canvas),
                    "--canvas-sha256",
                    canvas_module_sha256,
                    "--private-root",
                    str(stage),
                    "--output",
                    str(helper_output),
                    "--asset-dir",
                    str(asset_dir),
                    "--page-render-dir",
                    str(render_dir),
                ]
                stdout, _ = _bounded_subprocess(
                    command,
                    timeout_seconds=float(timeout_seconds),
                    stdout_limit=limits.max_subprocess_stdout_bytes,
                    stderr_limit=limits.max_subprocess_stderr_bytes,
                    cwd=helper.parent,
                )
                helper_bytes = _bounded_bytes(
                    helper_output,
                    limits.max_helper_output_bytes,
                    "hwp_visual_runner_helper_output_invalid",
                )
                helper_sha = hashlib.sha256(helper_bytes).hexdigest()
                summary = _decode_json(stdout, "hwp_visual_runner_helper_stdout_invalid")
                if (
                    not isinstance(summary, Mapping)
                    or set(summary)
                    != {"ok", "schema_version", "doc_id", "output_sha256", "counts"}
                    or summary.get("ok") is not True
                    or summary.get("schema_version") != "1.0"
                    or summary.get("doc_id") != doc_id
                    or summary.get("output_sha256") != helper_sha
                    or stdout != (canonical_json(summary) + "\n").encode("utf-8")
                ):
                    _fail("hwp_visual_runner_helper_stdout_invalid")
                envelope = _decode_json(
                    helper_bytes, "hwp_visual_runner_helper_output_invalid"
                )
                if helper_bytes != (canonical_json(envelope) + "\n").encode("utf-8"):
                    _fail("hwp_visual_runner_helper_output_not_canonical")
                helper_occurrences, source_objects, page_renders, doc_object_rows = (
                    _validate_helper_envelope(
                        envelope,
                        doc_id=doc_id,
                        source_sha256=source_sha256,
                        stage_root=stage,
                        dependency_pins=pins,
                        limits=limits,
                    )
                )
                if summary.get("counts") != envelope.get("counts"):
                    _fail("hwp_visual_runner_helper_stdout_invalid")
                try:
                    recovered = recover_hwp_occurrences(
                        doc_id=doc_id,
                        source_sha256=source_sha256,
                        helper_payload=helper_occurrences,
                        source_objects=source_objects,
                    )
                except ValueError:
                    _fail("hwp_visual_runner_recovery_failed")
                promoted: list[dict[str, Any]] = []
                for occurrence in recovered:
                    if occurrence["placement_status"] == "page_bbox_verified":
                        if occurrence["source_object_status"] == "unsupported":
                            promoted.append(occurrence)
                            continue
                        render = page_renders.get(occurrence["page"])
                        if render is None:
                            _fail("hwp_visual_runner_page_render_coverage_mismatch")
                        try:
                            occurrence = crop_page_region(
                                occurrence,
                                page_image=render["path"],
                                private_root=stage,
                                coordinate_page_bbox=render["coordinate_page_bbox"],
                                render_profile=render["render_profile"],
                            )
                        except ValueError:
                            _fail("hwp_visual_runner_crop_failed")
                    promoted.append(occurrence)
                promoted.sort(
                    key=lambda row: (
                        row["doc_id"],
                        row["page"] is None,
                        row["page"] or 0,
                        row["sequence_in_page"] if row["sequence_in_page"] is not None else -1,
                        row["occurrence_id"],
                    )
                )
                all_occurrences.extend(promoted)
                object_rows.extend(doc_object_rows)
                for occurrence in promoted:
                    crop_relpath = occurrence.get("crop_relpath")
                    if crop_relpath is not None:
                        relpath, crop_path = _safe_relative_asset(
                            crop_relpath, stage, "hwp_visual_runner_crop_asset_invalid"
                        )
                        object_rows.append(
                            _object_manifest_row(
                                relpath=relpath,
                                path=crop_path,
                                digest=occurrence["crop_sha256"],
                                media_type="image/png",
                                role="occurrence_crop",
                            )
                        )
                helper_manifest.append(
                    {
                        "schema_version": "1.0",
                        "doc_id": doc_id,
                        "source_sha256": source_sha256,
                        "blocks_sha256": blocks_sha256,
                        "helper_output_sha256": helper_sha,
                        "occurrences_sha256": _canonical_list_sha256(helper_occurrences),
                        "source_objects_sha256": _canonical_list_sha256(source_objects),
                        "source_assets_sha256": _canonical_list_sha256(
                            envelope["source_assets"]
                        ),
                        "page_renders_sha256": _canonical_list_sha256(
                            envelope["page_renders"]
                        ),
                        "render_profile_sha256": sha256_text(
                            canonical_json(envelope["render_profile"])
                        ),
                        "dependency_pins": dict(sorted(pins.items())),
                        "counts": dict(sorted(envelope["counts"].items())),
                        "unresolved_counts": dict(
                            sorted(envelope["unresolved"].items())
                        ),
                    }
                )
                helper_output.unlink(missing_ok=True)

            if len(all_occurrences) > limits.max_occurrences:
                _fail("hwp_visual_runner_occurrence_limit_exceeded")
            all_occurrences.sort(
                key=lambda row: (
                    row["doc_id"],
                    row["page"] is None,
                    row["page"] or 0,
                    row["sequence_in_page"] if row["sequence_in_page"] is not None else -1,
                    row["occurrence_id"],
                )
            )
            helper_manifest.sort(key=lambda row: str(row["doc_id"]))
            object_manifest = _merge_object_rows(object_rows)
            artifact_hashes = {
                "occurrences_v2_jsonl": write_jsonl_artifact(
                    all_occurrences,
                    output=stage / OCCURRENCE_ARTIFACT,
                    private_root=stage,
                ),
                "helper_manifest_v2_jsonl": write_jsonl_artifact(
                    helper_manifest,
                    output=stage / HELPER_MANIFEST_ARTIFACT,
                    private_root=stage,
                ),
                "object_manifest_v2_jsonl": write_jsonl_artifact(
                    object_manifest,
                    output=stage / OBJECT_MANIFEST_ARTIFACT,
                    private_root=stage,
                ),
            }
            metadata = build_visual_corpus_metadata(
                source_manifest_sha256=manifest_sha256,
                adapter_code_sha256=adapter_code_sha256,
                config=config,
                dependency_versions=dependency_versions,
                occurrences=all_occurrences,
                ocr_count=0,
                caption_count=0,
                chunk_count=0,
                artifact_hashes=artifact_hashes,
            )
            if expected_existing_artifact_set_id is not None and (
                expected_existing_artifact_set_id != metadata["artifact_set_id"]
            ):
                _fail("hwp_visual_runner_stale_artifact_identity")
            _atomic_write(
                stage / METADATA_ARTIFACT,
                (canonical_json(metadata) + "\n").encode("utf-8"),
                "hwp_visual_runner_publish_failed",
            )
            if output.exists():
                return _verify_existing(
                    output,
                    source_manifest_sha256=manifest_sha256,
                    adapter_code_sha256=adapter_code_sha256,
                    config=config,
                    dependency_versions=dependency_versions,
                    expected_existing_artifact_set_id=expected_existing_artifact_set_id,
                )
            os.rename(stage, output)
    except HwpVisualRunnerError:
        raise
    except OSError:
        _fail("hwp_visual_runner_publish_failed")
    return _verify_existing(
        output,
        source_manifest_sha256=manifest_sha256,
        adapter_code_sha256=adapter_code_sha256,
        config=config,
        dependency_versions=dependency_versions,
        expected_existing_artifact_set_id=expected_existing_artifact_set_id,
    )


__all__ = [
    "DEFAULT_HWP_VISUAL_RUNNER_LIMITS",
    "HELPER_MANIFEST_ARTIFACT",
    "HWP_VISUAL_RUNNER_METHOD",
    "HWP_VISUAL_RUNNER_VERSION",
    "HwpVisualRunnerError",
    "HwpVisualRunnerLimits",
    "METADATA_ARTIFACT",
    "OBJECT_MANIFEST_ARTIFACT",
    "OCCURRENCE_ARTIFACT",
    "run_hwp_visual_v2_from_manifest",
]
