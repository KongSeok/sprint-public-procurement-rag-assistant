from __future__ import annotations

import copy
import json
import math
import os
import platform
import re
import selectors
import signal
import subprocess
import time
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from midprojectrag.ingest.common import (
    canonical_json,
    require_sha256,
    sha256_file,
    sha256_text,
)


OCR_EVIDENCE_SCHEMA_VERSION = "1.0"
CAPTION_EVIDENCE_SCHEMA_VERSION = "1.0"
VISUAL_CHUNK_SCHEMA_VERSION = "1.0"
LOCAL_ADAPTER_PROTOCOL_VERSION = "1.0"
DARWIN_NETWORK_SANDBOX = "darwin-sandbox-exec-v1"
LINUX_NETWORK_SANDBOX = "linux-bwrap-v1"
NETWORK_SANDBOX_BACKENDS = (DARWIN_NETWORK_SANDBOX, LINUX_NETWORK_SANDBOX)
_DARWIN_SANDBOX_PROFILE = "(version 1) (allow default) (deny network*)"

PP_STRUCTURE_PIPELINE = "PP-StructureV3"
PP_OCR_VERSION = "PP-OCRv5"
PP_OCR_LANGUAGE = "korean"

MAX_ADAPTER_REQUEST_BYTES = 1024 * 1024
MAX_ADAPTER_STDOUT_BYTES = 8 * 1024 * 1024
MAX_ADAPTER_STDERR_BYTES = 64 * 1024
MAX_ADAPTER_TIMEOUT_SECONDS = 300.0
MAX_CROP_BYTES = 128 * 1024 * 1024
MAX_CHUNK_CHARS = 24_000
MAX_CAPTION_WEIGHT = 0.35
MAX_CAPTION_PER_QUERY = 2
MAX_CAPTION_PER_DOCUMENT = 1
READ_CHUNK_BYTES = 64 * 1024

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DOC_ID_RE = re.compile(r"^doc_[0-9a-f]{24}$")
_OCCURRENCE_ID_RE = re.compile(r"^vocc2_[0-9a-f]{24}$")
_OCR_EVIDENCE_ID_RE = re.compile(r"^ocr_[0-9a-f]{24}$")
_CAPTION_EVIDENCE_ID_RE = re.compile(r"^cap_[0-9a-f]{24}$")
_OCR_ITEM_ID_RE = re.compile(r"^ocri_[0-9a-f]{24}$")
_CLAIM_ID_RE = re.compile(r"^claim_[0-9a-f]{24}$")
_SAFE_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")
_SAFE_REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}$")
_CROP_RE = re.compile(r"^crops/([0-9a-f]{64})\.png$")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_BBOX_FIELDS = ("x", "y", "w", "h")

_FACTUAL_CLAIM_RE = re.compile(
    r"(?:"
    r"[0-9]|[%₩$€¥]|(?:->|<-|<->|→|←|↔)|"
    r"(?:연결|연계|전달|승인|소속|담당|보고|입력|출력|호출|저장|수신|송신|"
    r"상위|하위|내부|외부|운영|대기|주서버|보조서버)|"
    r"(?:기관|부서|센터|연구소|연구원|공단|공사|정부|국방부|서버|데이터베이스|DB)"
    r")",
    re.IGNORECASE,
)


class VisualUnderstandingError(ValueError):
    """Sanitized, stable failure raised by the local visual-understanding lane."""


def _fail(code: str) -> None:
    raise VisualUnderstandingError(code)


def _require_sha256(value: Any, error_code: str) -> str:
    try:
        return require_sha256(value, error_code)
    except ValueError:
        _fail(error_code)


def _safe_label(value: Any, error_code: str, *, maximum: int = 200) -> str:
    if not isinstance(value, str):
        _fail(error_code)
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized or len(normalized) > maximum or "\x00" in normalized:
        _fail(error_code)
    return normalized


def _safe_text(value: Any, error_code: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        _fail(error_code)
    normalized = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized) > maximum or "\x00" in normalized:
        _fail(error_code)
    for character in normalized:
        if unicodedata.category(character) == "Cc" and character not in "\n\t":
            _fail(error_code)
    return normalized


def _safe_warnings(value: Any, error_code: str) -> list[str]:
    if not isinstance(value, list) or len(value) > 128:
        _fail(error_code)
    warnings: list[str] = []
    for item in value:
        if not isinstance(item, str) or _SAFE_CODE_RE.fullmatch(item) is None:
            _fail(error_code)
        if item not in warnings:
            warnings.append(item)
    return sorted(warnings)


def _safe_json(value: Any, error_code: str, *, depth: int = 0) -> Any:
    if depth > 32:
        _fail(error_code)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail(error_code)
        return value
    if isinstance(value, list):
        return [_safe_json(item, error_code, depth=depth + 1) for item in value]
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or key in normalized:
                _fail(error_code)
            normalized[key] = _safe_json(item, error_code, depth=depth + 1)
        return normalized
    _fail(error_code)


def _json_object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate_json_key")
        value[key] = item
    return value


def _exact_keys(value: Any, keys: set[str], error_code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        _fail(error_code)
    return value


def _normalize_bbox(value: Any, error_code: str) -> dict[str, float]:
    if not isinstance(value, Mapping) or set(value) != set(_BBOX_FIELDS):
        _fail(error_code)
    bbox: dict[str, float] = {}
    for field in _BBOX_FIELDS:
        raw = value.get(field)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            _fail(error_code)
        number = float(raw)
        if not math.isfinite(number):
            _fail(error_code)
        bbox[field] = round(number, 6)
    if bbox["w"] <= 0 or bbox["h"] <= 0:
        _fail(error_code)
    return bbox


def _normalize_polygon(value: Any, error_code: str) -> list[list[float]]:
    if not isinstance(value, list) or not 4 <= len(value) <= 64:
        _fail(error_code)
    polygon: list[list[float]] = []
    for point in value:
        if not isinstance(point, list) or len(point) != 2:
            _fail(error_code)
        normalized: list[float] = []
        for raw in point:
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                _fail(error_code)
            number = float(raw)
            if not math.isfinite(number):
                _fail(error_code)
            normalized.append(round(number, 6))
        polygon.append(normalized)
    return polygon


def _require_int(value: Any, error_code: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _fail(error_code)
    return value


def _require_confidence(value: Any, error_code: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(error_code)
    confidence = float(value)
    if not math.isfinite(confidence) or confidence < 0 or confidence > 1:
        _fail(error_code)
    return round(confidence, 6)


def _validated_occurrence(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("visual_occurrence_invalid")
    doc_id = value.get("doc_id")
    occurrence_id = value.get("occurrence_id")
    if not isinstance(doc_id, str) or _DOC_ID_RE.fullmatch(doc_id) is None:
        _fail("visual_occurrence_doc_id_invalid")
    if not isinstance(occurrence_id, str) or _OCCURRENCE_ID_RE.fullmatch(occurrence_id) is None:
        _fail("visual_occurrence_id_invalid")
    if value.get("placement_status") != "page_bbox_verified":
        _fail("visual_occurrence_page_bbox_required")
    if value.get("retrieval_status") != "eligible":
        _fail("visual_occurrence_retrieval_ineligible")
    page = _require_int(value.get("page"), "visual_occurrence_page_invalid", minimum=1)
    bbox = _normalize_bbox(value.get("bbox"), "visual_occurrence_bbox_invalid")
    crop_sha256 = _require_sha256(value.get("crop_sha256"), "visual_occurrence_crop_hash_invalid")
    crop_relpath = value.get("crop_relpath")
    match = _CROP_RE.fullmatch(crop_relpath) if isinstance(crop_relpath, str) else None
    if match is None or match.group(1) != crop_sha256:
        _fail("visual_occurrence_crop_path_invalid")
    if value.get("crop_media_type") != "image/png":
        _fail("visual_occurrence_crop_media_type_invalid")
    coordinate_space = _safe_label(
        value.get("coordinate_space"), "visual_occurrence_coordinate_space_invalid"
    )
    return {
        "doc_id": doc_id,
        "occurrence_id": occurrence_id,
        "page": page,
        "bbox": bbox,
        "coordinate_space": coordinate_space,
        "crop_sha256": crop_sha256,
        "crop_relpath": crop_relpath,
    }


def _resolve_crop(occurrence: Mapping[str, Any], private_root: Path) -> Path:
    if not isinstance(private_root, Path) or not private_root.is_absolute() or private_root.is_symlink():
        _fail("visual_private_root_invalid")
    try:
        resolved_root = private_root.resolve(strict=True)
    except OSError:
        _fail("visual_private_root_invalid")
    if resolved_root != Path(os.path.abspath(str(private_root))) or not resolved_root.is_dir():
        _fail("visual_private_root_invalid")
    candidate = resolved_root / occurrence["crop_relpath"]
    cursor = resolved_root
    for component in Path(occurrence["crop_relpath"]).parts:
        cursor = cursor / component
        if cursor.is_symlink():
            _fail("visual_crop_symlink_forbidden")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        _fail("visual_crop_unavailable")
    if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
        _fail("visual_crop_path_escape")
    size = resolved.stat().st_size
    if size < len(_PNG_SIGNATURE) or size > MAX_CROP_BYTES:
        _fail("visual_crop_size_invalid")
    with resolved.open("rb") as source:
        if source.read(len(_PNG_SIGNATURE)) != _PNG_SIGNATURE:
            _fail("visual_crop_png_invalid")
    if sha256_file(resolved) != occurrence["crop_sha256"]:
        _fail("visual_crop_checksum_mismatch")
    return resolved


def _normalized_absolute_file(
    path: Path,
    *,
    expected_sha256: str,
    executable: bool,
    error_prefix: str,
) -> Path:
    expected_sha256 = _require_sha256(expected_sha256, f"{error_prefix}_checksum_invalid")
    if not isinstance(path, Path) or not path.is_absolute() or path.is_symlink():
        _fail(f"{error_prefix}_path_invalid")
    normalized = Path(os.path.abspath(str(path)))
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        _fail(f"{error_prefix}_unavailable")
    if resolved != normalized or not resolved.is_file():
        _fail(f"{error_prefix}_symlink_forbidden")
    if executable and not os.access(resolved, os.X_OK):
        _fail(f"{error_prefix}_not_executable")
    if sha256_file(resolved) != expected_sha256:
        _fail(f"{error_prefix}_checksum_mismatch")
    return resolved


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        process.terminate()
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            process.kill()
        process.wait()


def _run_bounded_json(
    argv: Sequence[str],
    request: bytes,
    *,
    timeout_seconds: float,
    max_stdout_bytes: int,
    max_stderr_bytes: int,
    cwd: Path,
) -> dict[str, Any]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT"}
    }
    environment.update(
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "MIDPROJECTRAG_NETWORK_DISABLED": "1",
            "NO_PROXY": "*",
            "no_proxy": "*",
        }
    )
    try:
        process = subprocess.Popen(
            list(argv),
            cwd=cwd,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
            start_new_session=True,
        )
    except OSError:
        _fail("local_adapter_launch_failed")
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    for stream in (process.stdin, process.stdout, process.stderr):
        os.set_blocking(stream.fileno(), False)

    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
    stdout = bytearray()
    stderr_bytes = 0
    written = 0
    deadline = time.monotonic() + timeout_seconds
    failure: str | None = None
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failure = "local_adapter_timeout"
                break
            for key, _ in selector.select(timeout=min(remaining, 0.1)):
                stream = key.fileobj
                if key.data == "stdin":
                    try:
                        count = os.write(stream.fileno(), request[written : written + READ_CHUNK_BYTES])
                    except (BlockingIOError, InterruptedError):
                        continue
                    except BrokenPipeError:
                        count = 0
                        if written < len(request):
                            failure = "local_adapter_stdin_closed"
                    written += count
                    if written >= len(request) or failure is not None:
                        selector.unregister(stream)
                        stream.close()
                    if failure is not None:
                        break
                    continue

                try:
                    chunk = os.read(stream.fileno(), READ_CHUNK_BYTES)
                except (BlockingIOError, InterruptedError):
                    continue
                if not chunk:
                    selector.unregister(stream)
                    stream.close()
                    continue
                if key.data == "stdout":
                    if len(stdout) + len(chunk) > max_stdout_bytes:
                        failure = "local_adapter_stdout_limit_exceeded"
                        break
                    stdout.extend(chunk)
                else:
                    stderr_bytes += len(chunk)
                    if stderr_bytes > max_stderr_bytes:
                        failure = "local_adapter_stderr_limit_exceeded"
                        break
            if failure is not None:
                break
    finally:
        selector.close()

    if failure is not None:
        _stop_process(process)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()
        _fail(failure)
    try:
        returncode = process.wait(timeout=max(0.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        _stop_process(process)
        _fail("local_adapter_timeout")
    if returncode != 0:
        _fail("local_adapter_failed")
    try:
        decoded = stdout.decode("utf-8")
        value = json.loads(
            decoded,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
            object_pairs_hook=_json_object_without_duplicates,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        _fail("local_adapter_json_invalid")
    if not isinstance(value, dict):
        _fail("local_adapter_contract_invalid")
    return _safe_json(value, "local_adapter_contract_invalid")


class VisualUnderstandingAdapter(Protocol):
    @property
    def identity(self) -> Mapping[str, Any]: ...

    @property
    def model_artifact_sha256(self) -> str: ...

    def infer(self, operation: str, request: Mapping[str, Any]) -> Mapping[str, Any]: ...


class PinnedLocalJsonCommandAdapter:
    """Invoke a local JSON adapter with pinned executable and model-manifest hashes.

    ``model_artifact`` is expected to be a small immutable manifest that pins every
    model file used by the wrapper. The wrapper receives its absolute path, but paths
    are deliberately excluded from the persistent adapter identity.
    """

    def __init__(
        self,
        *,
        command: Path,
        command_sha256: str,
        model_artifact: Path,
        model_artifact_sha256: str,
        network_sandbox_backend: str,
        network_sandbox_command: Path,
        network_sandbox_command_sha256: str,
        arguments: Sequence[str] = (),
        timeout_seconds: float = 120.0,
        max_stdout_bytes: int = MAX_ADAPTER_STDOUT_BYTES,
        max_stderr_bytes: int = MAX_ADAPTER_STDERR_BYTES,
    ) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or float(timeout_seconds) <= 0
            or float(timeout_seconds) > MAX_ADAPTER_TIMEOUT_SECONDS
        ):
            _fail("local_adapter_timeout_invalid")
        if not isinstance(max_stdout_bytes, int) or not 1 <= max_stdout_bytes <= MAX_ADAPTER_STDOUT_BYTES:
            _fail("local_adapter_stdout_limit_invalid")
        if not isinstance(max_stderr_bytes, int) or not 1 <= max_stderr_bytes <= MAX_ADAPTER_STDERR_BYTES:
            _fail("local_adapter_stderr_limit_invalid")
        normalized_arguments: list[str] = []
        for argument in arguments:
            if not isinstance(argument, str) or "\x00" in argument or len(argument) > 4096:
                _fail("local_adapter_argument_invalid")
            normalized_arguments.append(argument)
        self._expected_command_sha256 = _require_sha256(
            command_sha256, "local_adapter_command_checksum_invalid"
        )
        self._expected_model_sha256 = _require_sha256(
            model_artifact_sha256, "model_artifact_checksum_invalid"
        )
        self._command = _normalized_absolute_file(
            command,
            expected_sha256=self._expected_command_sha256,
            executable=True,
            error_prefix="local_adapter_command",
        )
        self._model_artifact = _normalized_absolute_file(
            model_artifact,
            expected_sha256=self._expected_model_sha256,
            executable=False,
            error_prefix="model_artifact",
        )
        if network_sandbox_backend not in NETWORK_SANDBOX_BACKENDS:
            _fail("network_sandbox_backend_invalid")
        expected_system = (
            "Darwin"
            if network_sandbox_backend == DARWIN_NETWORK_SANDBOX
            else "Linux"
        )
        if platform.system() != expected_system:
            _fail("network_sandbox_backend_unavailable")
        self._network_sandbox_backend = network_sandbox_backend
        self._expected_network_sandbox_sha256 = _require_sha256(
            network_sandbox_command_sha256,
            "network_sandbox_command_checksum_invalid",
        )
        self._network_sandbox_command = _normalized_absolute_file(
            network_sandbox_command,
            expected_sha256=self._expected_network_sandbox_sha256,
            executable=True,
            error_prefix="network_sandbox_command",
        )
        allowed_paths = (
            {Path("/usr/bin/sandbox-exec")}
            if network_sandbox_backend == DARWIN_NETWORK_SANDBOX
            else {Path("/usr/bin/bwrap"), Path("/bin/bwrap")}
        )
        if self._network_sandbox_command not in allowed_paths:
            _fail("network_sandbox_command_not_allowlisted")
        self._arguments = tuple(normalized_arguments)
        self._timeout_seconds = float(timeout_seconds)
        self._max_stdout_bytes = max_stdout_bytes
        self._max_stderr_bytes = max_stderr_bytes

    @property
    def model_artifact_sha256(self) -> str:
        return self._expected_model_sha256

    @property
    def identity(self) -> Mapping[str, Any]:
        return {
            "adapter_kind": "checksum-pinned-local-json-command-v2",
            "protocol_version": LOCAL_ADAPTER_PROTOCOL_VERSION,
            "command_sha256": self._expected_command_sha256,
            "model_artifact_sha256": self._expected_model_sha256,
            "network_sandbox_backend": self._network_sandbox_backend,
            "network_sandbox_command_sha256": self._expected_network_sandbox_sha256,
            "arguments": list(self._arguments),
            "timeout_seconds": self._timeout_seconds,
            "max_stdout_bytes": self._max_stdout_bytes,
            "max_stderr_bytes": self._max_stderr_bytes,
            "network": "os_sandbox_enforced",
        }

    def _verify_pins(self) -> None:
        _normalized_absolute_file(
            self._command,
            expected_sha256=self._expected_command_sha256,
            executable=True,
            error_prefix="local_adapter_command",
        )
        _normalized_absolute_file(
            self._model_artifact,
            expected_sha256=self._expected_model_sha256,
            executable=False,
            error_prefix="model_artifact",
        )
        _normalized_absolute_file(
            self._network_sandbox_command,
            expected_sha256=self._expected_network_sandbox_sha256,
            executable=True,
            error_prefix="network_sandbox_command",
        )

    def _sandboxed_argv(self) -> tuple[str, ...]:
        command = (str(self._command), *self._arguments)
        if self._network_sandbox_backend == DARWIN_NETWORK_SANDBOX:
            return (
                str(self._network_sandbox_command),
                "-p",
                _DARWIN_SANDBOX_PROFILE,
                *command,
            )
        if self._network_sandbox_backend == LINUX_NETWORK_SANDBOX:
            return (
                str(self._network_sandbox_command),
                "--unshare-net",
                "--die-with-parent",
                "--ro-bind",
                "/",
                "/",
                "--dev",
                "/dev",
                "--proc",
                "/proc",
                "--chdir",
                str(self._command.parent),
                "--",
                *command,
            )
        _fail("network_sandbox_backend_invalid")

    def infer(self, operation: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        operation = _safe_label(operation, "local_adapter_operation_invalid", maximum=80)
        normalized_request = _safe_json(request, "local_adapter_request_invalid")
        envelope = {
            "schema_version": LOCAL_ADAPTER_PROTOCOL_VERSION,
            "operation": operation,
            "model_artifact_path": str(self._model_artifact),
            "request": normalized_request,
        }
        payload = (canonical_json(envelope) + "\n").encode("utf-8")
        if len(payload) > MAX_ADAPTER_REQUEST_BYTES:
            _fail("local_adapter_request_limit_exceeded")
        self._verify_pins()
        result = _run_bounded_json(
            self._sandboxed_argv(),
            payload,
            timeout_seconds=self._timeout_seconds,
            max_stdout_bytes=self._max_stdout_bytes,
            max_stderr_bytes=self._max_stderr_bytes,
            cwd=self._command.parent,
        )
        self._verify_pins()
        return result


class DeterministicFixtureAdapter:
    """Public-CI adapter returning immutable, content-addressed fixture output."""

    def __init__(
        self,
        *,
        responses: Mapping[str, Mapping[str, Any]],
        model_artifact_sha256: str,
    ) -> None:
        self._model_artifact_sha256 = _require_sha256(
            model_artifact_sha256, "fixture_model_checksum_invalid"
        )
        if not isinstance(responses, Mapping) or not responses:
            _fail("fixture_responses_invalid")
        normalized: dict[str, dict[str, Any]] = {}
        for operation, response in responses.items():
            operation_name = _safe_label(operation, "fixture_operation_invalid", maximum=80)
            if operation_name in normalized or not isinstance(response, Mapping):
                _fail("fixture_responses_invalid")
            normalized[operation_name] = _safe_json(response, "fixture_response_invalid")
        self._responses = normalized
        self._fixture_sha256 = sha256_text(canonical_json(normalized))

    @property
    def model_artifact_sha256(self) -> str:
        return self._model_artifact_sha256

    @property
    def identity(self) -> Mapping[str, Any]:
        return {
            "adapter_kind": "deterministic-fixture-v1",
            "protocol_version": LOCAL_ADAPTER_PROTOCOL_VERSION,
            "model_artifact_sha256": self._model_artifact_sha256,
            "fixture_sha256": self._fixture_sha256,
            "network": "not_used",
        }

    def infer(self, operation: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        del request
        if operation not in self._responses:
            _fail("fixture_operation_unavailable")
        return copy.deepcopy(self._responses[operation])


def _adapter_identity(adapter: VisualUnderstandingAdapter) -> dict[str, Any]:
    try:
        identity = _safe_json(adapter.identity, "visual_adapter_identity_invalid")
        model_sha256 = _require_sha256(
            adapter.model_artifact_sha256, "visual_adapter_model_checksum_invalid"
        )
    except AttributeError:
        _fail("visual_adapter_identity_invalid")
    if not isinstance(identity, dict) or identity.get("model_artifact_sha256") != model_sha256:
        _fail("visual_adapter_identity_invalid")
    return identity


@dataclass(frozen=True)
class PpStructureV3Config:
    model_version: str
    weights_sha256: str
    runtime: str
    device: str
    text_rec_score_thresh: float = 0.5
    use_doc_orientation_classify: bool = True
    use_textline_orientation: bool = True
    use_table_recognition: bool = True
    use_ocr_results_with_table_cells: bool = True
    max_text_items: int = 10_000
    max_table_cells: int = 10_000

    def __post_init__(self) -> None:
        object.__setattr__(self, "model_version", _safe_label(self.model_version, "ocr_model_version_invalid"))
        object.__setattr__(self, "weights_sha256", _require_sha256(self.weights_sha256, "ocr_weights_hash_invalid"))
        object.__setattr__(self, "runtime", _safe_label(self.runtime, "ocr_runtime_invalid"))
        object.__setattr__(self, "device", _safe_label(self.device, "ocr_device_invalid"))
        _require_confidence(self.text_rec_score_thresh, "ocr_score_threshold_invalid")
        for field in (
            self.use_doc_orientation_classify,
            self.use_textline_orientation,
            self.use_table_recognition,
            self.use_ocr_results_with_table_cells,
        ):
            if not isinstance(field, bool):
                _fail("ocr_boolean_config_invalid")
        if (
            isinstance(self.max_text_items, bool)
            or not isinstance(self.max_text_items, int)
            or not 1 <= self.max_text_items <= 10_000
            or isinstance(self.max_table_cells, bool)
            or not isinstance(self.max_table_cells, int)
            or not 0 <= self.max_table_cells <= 10_000
        ):
            _fail("ocr_record_limit_invalid")

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "config_contract": "pp-structure-v3-korean-ppocrv5-v1",
            "pipeline": PP_STRUCTURE_PIPELINE,
            "ocr_version": PP_OCR_VERSION,
            "language": PP_OCR_LANGUAGE,
            "model_version": self.model_version,
            "weights_sha256": self.weights_sha256,
            "runtime": self.runtime,
            "device": self.device,
            "text_rec_score_thresh": round(float(self.text_rec_score_thresh), 6),
            "use_doc_orientation_classify": self.use_doc_orientation_classify,
            "use_textline_orientation": self.use_textline_orientation,
            "use_table_recognition": self.use_table_recognition,
            "use_ocr_results_with_table_cells": self.use_ocr_results_with_table_cells,
            "max_text_items": self.max_text_items,
            "max_table_cells": self.max_table_cells,
            "model_download": "forbidden",
        }

    @property
    def config_sha256(self) -> str:
        return sha256_text(canonical_json(self.identity))

    @property
    def model_record(self) -> dict[str, str]:
        return {
            "name": PP_STRUCTURE_PIPELINE,
            "version": self.model_version,
            "weights_sha256": self.weights_sha256,
            "runtime": self.runtime,
            "device": self.device,
            "language": PP_OCR_LANGUAGE,
        }


@dataclass(frozen=True)
class CaptionModelConfig:
    model_name: str
    model_version: str
    weights_sha256: str
    runtime: str
    device: str
    prompt: str
    max_new_tokens: int = 512
    seed: int = 0
    temperature: float = 0.0
    do_sample: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "model_name", _safe_label(self.model_name, "caption_model_name_invalid"))
        object.__setattr__(self, "model_version", _safe_label(self.model_version, "caption_model_version_invalid"))
        object.__setattr__(self, "weights_sha256", _require_sha256(self.weights_sha256, "caption_weights_hash_invalid"))
        object.__setattr__(self, "runtime", _safe_label(self.runtime, "caption_runtime_invalid"))
        object.__setattr__(self, "device", _safe_label(self.device, "caption_device_invalid"))
        object.__setattr__(self, "prompt", _safe_text(self.prompt, "caption_prompt_invalid", maximum=20_000))
        if not self.prompt:
            _fail("caption_prompt_invalid")
        if (
            isinstance(self.max_new_tokens, bool)
            or not isinstance(self.max_new_tokens, int)
            or not 1 <= self.max_new_tokens <= 4096
        ):
            _fail("caption_token_limit_invalid")
        _require_int(self.seed, "caption_seed_invalid")
        if (
            isinstance(self.temperature, bool)
            or not isinstance(self.temperature, (int, float))
            or not math.isfinite(float(self.temperature))
            or float(self.temperature) != 0.0
            or self.do_sample is not False
        ):
            _fail("caption_decode_nondeterministic")

    @property
    def prompt_sha256(self) -> str:
        return sha256_text(self.prompt)

    @property
    def decode_config(self) -> dict[str, Any]:
        return {
            "max_new_tokens": self.max_new_tokens,
            "seed": self.seed,
            "temperature": 0.0,
            "do_sample": False,
        }

    @property
    def decode_config_sha256(self) -> str:
        return sha256_text(canonical_json(self.decode_config))

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "config_contract": "local-caption-supported-claims-v1",
            "model_name": self.model_name,
            "model_version": self.model_version,
            "weights_sha256": self.weights_sha256,
            "runtime": self.runtime,
            "device": self.device,
            "prompt_sha256": self.prompt_sha256,
            "decode_config_sha256": self.decode_config_sha256,
            "model_download": "forbidden",
        }


def _require_adapter_model(config_sha256: str, adapter: VisualUnderstandingAdapter) -> dict[str, Any]:
    adapter_identity = _adapter_identity(adapter)
    if adapter.model_artifact_sha256 != config_sha256:
        _fail("model_artifact_config_mismatch")
    return adapter_identity


def ocr_cache_key(
    occurrence: Mapping[str, Any],
    config: PpStructureV3Config,
    adapter: VisualUnderstandingAdapter,
) -> str:
    placement = _validated_occurrence(occurrence)
    adapter_identity = _require_adapter_model(config.weights_sha256, adapter)
    return sha256_text(
        canonical_json(
            {
                "cache_contract": "local-ocr-crop-v1",
                "crop_sha256": placement["crop_sha256"],
                "config_sha256": config.config_sha256,
                "adapter_identity_sha256": sha256_text(canonical_json(adapter_identity)),
            }
        )
    )


def _normalize_ocr_payload(
    payload: Any,
    *,
    occurrence: Mapping[str, Any],
    config: PpStructureV3Config,
    adapter_identity: Mapping[str, Any],
) -> dict[str, Any]:
    value = _exact_keys(
        payload,
        {"schema_version", "status", "text_items", "table_cells", "warnings"},
        "ocr_adapter_contract_invalid",
    )
    if value.get("schema_version") != OCR_EVIDENCE_SCHEMA_VERSION:
        _fail("ocr_adapter_contract_invalid")
    status = value.get("status")
    if status not in {"success", "low_confidence", "failed"}:
        _fail("ocr_status_invalid")
    raw_items = value.get("text_items")
    raw_cells = value.get("table_cells")
    if not isinstance(raw_items, list) or len(raw_items) > config.max_text_items:
        _fail("ocr_text_item_limit_exceeded")
    if not isinstance(raw_cells, list) or len(raw_cells) > config.max_table_cells:
        _fail("ocr_table_cell_limit_exceeded")
    if status == "failed" and (raw_items or raw_cells):
        _fail("ocr_failed_payload_not_empty")

    text_items: list[dict[str, Any]] = []
    by_order: dict[int, str] = {}
    for raw_item in raw_items:
        item = _exact_keys(
            raw_item,
            {"polygon", "text", "confidence", "reading_order"},
            "ocr_text_item_invalid",
        )
        order = _require_int(item.get("reading_order"), "ocr_reading_order_invalid")
        if order in by_order:
            _fail("ocr_reading_order_duplicate")
        normalized = {
            "polygon": _normalize_polygon(item.get("polygon"), "ocr_polygon_invalid"),
            "text": _safe_text(item.get("text"), "ocr_text_invalid", maximum=10_000),
            "confidence": _require_confidence(item.get("confidence"), "ocr_confidence_invalid"),
            "reading_order": order,
        }
        if not normalized["text"]:
            _fail("ocr_text_invalid")
        item_id = "ocri_" + sha256_text(
            canonical_json(
                {
                    "occurrence_id": occurrence["occurrence_id"],
                    "crop_sha256": occurrence["crop_sha256"],
                    **normalized,
                }
            )
        )[:24]
        normalized["item_id"] = item_id
        by_order[order] = item_id
        text_items.append(normalized)
    text_items.sort(key=lambda item: (item["reading_order"], item["item_id"]))

    table_cells: list[dict[str, Any]] = []
    seen_cells: set[tuple[int, int]] = set()
    for raw_cell in raw_cells:
        cell = _exact_keys(
            raw_cell,
            {
                "row",
                "column",
                "row_span",
                "column_span",
                "polygon",
                "text",
                "confidence",
                "source_reading_orders",
            },
            "ocr_table_cell_invalid",
        )
        row = _require_int(cell.get("row"), "ocr_table_cell_position_invalid")
        column = _require_int(cell.get("column"), "ocr_table_cell_position_invalid")
        if (row, column) in seen_cells:
            _fail("ocr_table_cell_duplicate")
        seen_cells.add((row, column))
        source_orders = cell.get("source_reading_orders")
        if not isinstance(source_orders, list) or any(
            isinstance(order, bool) or not isinstance(order, int) or order not in by_order
            for order in source_orders
        ):
            _fail("ocr_table_cell_source_invalid")
        table_cells.append(
            {
                "row": row,
                "column": column,
                "row_span": _require_int(cell.get("row_span"), "ocr_table_cell_span_invalid", minimum=1),
                "column_span": _require_int(cell.get("column_span"), "ocr_table_cell_span_invalid", minimum=1),
                "polygon": _normalize_polygon(cell.get("polygon"), "ocr_table_cell_polygon_invalid"),
                "text": _safe_text(cell.get("text"), "ocr_table_cell_text_invalid", maximum=10_000),
                "confidence": _require_confidence(cell.get("confidence"), "ocr_table_cell_confidence_invalid"),
                "source_item_ids": sorted({by_order[order] for order in source_orders}),
            }
        )
    table_cells.sort(key=lambda cell: (cell["row"], cell["column"]))

    warnings = _safe_warnings(value.get("warnings"), "ocr_warnings_invalid")
    if status != "failed" and (
        any(item["confidence"] < config.text_rec_score_thresh for item in text_items)
        or any(cell["confidence"] < config.text_rec_score_thresh for cell in table_cells)
    ):
        status = "low_confidence"
        warnings = sorted({*warnings, "ocr_below_configured_threshold"})

    identity = {
        "occurrence_id": occurrence["occurrence_id"],
        "crop_sha256": occurrence["crop_sha256"],
        "status": status,
        "text_items": text_items,
        "table_cells": table_cells,
        "model": config.model_record,
        "config_sha256": config.config_sha256,
        "adapter_identity_sha256": sha256_text(canonical_json(adapter_identity)),
        "warnings": warnings,
    }
    return {
        "schema_version": OCR_EVIDENCE_SCHEMA_VERSION,
        "evidence_id": "ocr_" + sha256_text(canonical_json(identity))[:24],
        "occurrence_id": occurrence["occurrence_id"],
        "crop_sha256": occurrence["crop_sha256"],
        "status": status,
        "text_items": text_items,
        "table_cells": table_cells,
        "model": config.model_record,
        "config_sha256": config.config_sha256,
        "warnings": warnings,
    }


def run_local_ocr(
    occurrence: Mapping[str, Any],
    *,
    private_root: Path,
    adapter: VisualUnderstandingAdapter,
    config: PpStructureV3Config,
) -> dict[str, Any]:
    placement = _validated_occurrence(occurrence)
    crop_path = _resolve_crop(placement, private_root)
    adapter_identity = _require_adapter_model(config.weights_sha256, adapter)
    request = {
        "schema_version": OCR_EVIDENCE_SCHEMA_VERSION,
        "crop_path": str(crop_path),
        "crop_sha256": placement["crop_sha256"],
        "occurrence_id": placement["occurrence_id"],
        "page": placement["page"],
        "bbox": placement["bbox"],
        "coordinate_space": placement["coordinate_space"],
        "config": config.identity,
    }
    payload = adapter.infer("ocr_layout_v1", request)
    return _normalize_ocr_payload(
        payload,
        occurrence=placement,
        config=config,
        adapter_identity=adapter_identity,
    )


def _validated_ocr_evidence(
    evidence: Any, occurrence: Mapping[str, Any]
) -> tuple[dict[str, Any], set[str]]:
    if not isinstance(evidence, Mapping):
        _fail("ocr_evidence_invalid")
    if evidence.get("schema_version") != OCR_EVIDENCE_SCHEMA_VERSION:
        _fail("ocr_evidence_invalid")
    evidence_id = evidence.get("evidence_id")
    if not isinstance(evidence_id, str) or _OCR_EVIDENCE_ID_RE.fullmatch(evidence_id) is None:
        _fail("ocr_evidence_id_invalid")
    if evidence.get("occurrence_id") != occurrence["occurrence_id"] or evidence.get("crop_sha256") != occurrence["crop_sha256"]:
        _fail("ocr_evidence_occurrence_mismatch")
    if evidence.get("status") not in {"success", "low_confidence", "failed"}:
        _fail("ocr_evidence_invalid")
    items = evidence.get("text_items")
    cells = evidence.get("table_cells")
    if not isinstance(items, list) or not isinstance(cells, list):
        _fail("ocr_evidence_invalid")
    item_ids: set[str] = set()
    for item in items:
        if not isinstance(item, Mapping):
            _fail("ocr_evidence_invalid")
        item_id = item.get("item_id")
        if not isinstance(item_id, str) or _OCR_ITEM_ID_RE.fullmatch(item_id) is None or item_id in item_ids:
            _fail("ocr_evidence_item_id_invalid")
        _normalize_polygon(item.get("polygon"), "ocr_evidence_invalid")
        if not _safe_text(item.get("text"), "ocr_evidence_invalid", maximum=10_000):
            _fail("ocr_evidence_invalid")
        _require_confidence(item.get("confidence"), "ocr_evidence_invalid")
        _require_int(item.get("reading_order"), "ocr_evidence_invalid")
        item_ids.add(item_id)
    for cell in cells:
        if not isinstance(cell, Mapping):
            _fail("ocr_evidence_invalid")
        _require_int(cell.get("row"), "ocr_evidence_invalid")
        _require_int(cell.get("column"), "ocr_evidence_invalid")
        _require_int(cell.get("row_span"), "ocr_evidence_invalid", minimum=1)
        _require_int(cell.get("column_span"), "ocr_evidence_invalid", minimum=1)
        _normalize_polygon(cell.get("polygon"), "ocr_evidence_invalid")
        _safe_text(cell.get("text"), "ocr_evidence_invalid", maximum=10_000)
        _require_confidence(cell.get("confidence"), "ocr_evidence_invalid")
        refs = cell.get("source_item_ids")
        if not isinstance(refs, list) or any(ref not in item_ids for ref in refs):
            _fail("ocr_evidence_invalid")
    return dict(evidence), item_ids


def caption_cache_key(
    occurrence: Mapping[str, Any],
    ocr_evidence: Mapping[str, Any],
    config: CaptionModelConfig,
    adapter: VisualUnderstandingAdapter,
) -> str:
    placement = _validated_occurrence(occurrence)
    validated_ocr, _ = _validated_ocr_evidence(ocr_evidence, placement)
    adapter_identity = _require_adapter_model(config.weights_sha256, adapter)
    return sha256_text(
        canonical_json(
            {
                "cache_contract": "local-caption-crop-ocr-v1",
                "crop_sha256": placement["crop_sha256"],
                "ocr_evidence_sha256": sha256_text(canonical_json(validated_ocr)),
                "caption_config": config.identity,
                "adapter_identity_sha256": sha256_text(canonical_json(adapter_identity)),
            }
        )
    )


def _looks_factual(text: str) -> bool:
    return _FACTUAL_CLAIM_RE.search(text) is not None


def _normalize_support_refs(value: Any, error_code: str) -> list[str]:
    if not isinstance(value, list) or len(value) > 256:
        _fail(error_code)
    refs: set[str] = set()
    for ref in value:
        if not isinstance(ref, str) or _SAFE_REFERENCE_RE.fullmatch(ref) is None:
            _fail(error_code)
        refs.add(ref)
    return sorted(refs)


def _sanitize_caption_description(
    description: str, claims: Sequence[Mapping[str, Any]]
) -> tuple[str, bool]:
    supported = {
        unicodedata.normalize("NFC", str(claim["text"])).strip()
        for claim in claims
        if claim.get("status") == "supported"
    }
    rejected = {
        unicodedata.normalize("NFC", str(claim["text"])).strip()
        for claim in claims
        if claim.get("status") == "rejected"
    }
    kept: list[str] = []
    omitted = False
    for sentence in re.split(r"(?<=[.!?。])\s+|\n+", description):
        sentence = sentence.strip()
        if not sentence:
            continue
        if any(value and value in sentence for value in rejected):
            omitted = True
            continue
        if _looks_factual(sentence) and not any(
            sentence == value or sentence in value or value in sentence for value in supported
        ):
            omitted = True
            continue
        kept.append(sentence)
    return " ".join(kept), omitted


def _normalize_caption_payload(
    payload: Any,
    *,
    occurrence: Mapping[str, Any],
    allowed_support_refs: set[str],
    config: CaptionModelConfig,
    adapter_identity: Mapping[str, Any],
) -> dict[str, Any]:
    value = _exact_keys(
        payload,
        {"schema_version", "status", "description", "claims", "warnings"},
        "caption_adapter_contract_invalid",
    )
    if value.get("schema_version") != CAPTION_EVIDENCE_SCHEMA_VERSION:
        _fail("caption_adapter_contract_invalid")
    raw_status = value.get("status")
    if raw_status not in {"success", "failed"}:
        _fail("caption_status_invalid")
    description = _safe_text(value.get("description"), "caption_description_invalid", maximum=20_000)
    raw_claims = value.get("claims")
    if not isinstance(raw_claims, list) or len(raw_claims) > 1000:
        _fail("caption_claim_limit_exceeded")
    if raw_status == "failed" and (description or raw_claims):
        _fail("caption_failed_payload_not_empty")
    warnings = _safe_warnings(value.get("warnings"), "caption_warnings_invalid")

    claims: list[dict[str, Any]] = []
    for raw_claim in raw_claims:
        claim = _exact_keys(raw_claim, {"text", "support_refs"}, "caption_claim_invalid")
        text = _safe_text(claim.get("text"), "caption_claim_text_invalid", maximum=5000)
        if not text:
            _fail("caption_claim_text_invalid")
        support_refs = _normalize_support_refs(
            claim.get("support_refs"), "caption_support_refs_invalid"
        )
        unknown_refs = set(support_refs) - allowed_support_refs
        if unknown_refs:
            status = "rejected"
            warnings = sorted({*warnings, "caption_unknown_support_ref"})
        elif support_refs:
            status = "supported"
        elif _looks_factual(text):
            status = "rejected"
            warnings = sorted({*warnings, "caption_unsupported_factual_claim"})
        else:
            status = "descriptive_only"
        identity = {
            "occurrence_id": occurrence["occurrence_id"],
            "crop_sha256": occurrence["crop_sha256"],
            "text": text,
            "support_refs": support_refs,
            "status": status,
        }
        claims.append(
            {
                "claim_id": "claim_" + sha256_text(canonical_json(identity))[:24],
                "text": text,
                "support_refs": support_refs,
                "status": status,
            }
        )
    claims.sort(key=lambda claim: claim["claim_id"])
    description, omitted = _sanitize_caption_description(description, claims)
    if omitted:
        warnings = sorted({*warnings, "caption_unsupported_description_omitted"})

    if raw_status == "failed":
        status = "failed"
    elif any(claim["status"] == "supported" for claim in claims):
        status = "success"
    elif description or any(claim["status"] == "descriptive_only" for claim in claims):
        status = "descriptive_only"
    else:
        status = "failed"
        warnings = sorted({*warnings, "caption_no_eligible_content"})

    identity = {
        "occurrence_id": occurrence["occurrence_id"],
        "crop_sha256": occurrence["crop_sha256"],
        "description": description,
        "claims": claims,
        "model": f"{config.model_name}@{config.model_version}",
        "weights_sha256": config.weights_sha256,
        "prompt_sha256": config.prompt_sha256,
        "decode_config_sha256": config.decode_config_sha256,
        "adapter_identity_sha256": sha256_text(canonical_json(adapter_identity)),
        "status": status,
        "warnings": warnings,
    }
    return {
        "schema_version": CAPTION_EVIDENCE_SCHEMA_VERSION,
        "evidence_id": "cap_" + sha256_text(canonical_json(identity))[:24],
        "occurrence_id": occurrence["occurrence_id"],
        "crop_sha256": occurrence["crop_sha256"],
        "description": description,
        "claims": claims,
        "model": f"{config.model_name}@{config.model_version}",
        "weights_sha256": config.weights_sha256,
        "prompt_sha256": config.prompt_sha256,
        "decode_config_sha256": config.decode_config_sha256,
        "status": status,
        "warnings": warnings,
    }


def run_local_caption(
    occurrence: Mapping[str, Any],
    ocr_evidence: Mapping[str, Any],
    *,
    private_root: Path,
    adapter: VisualUnderstandingAdapter,
    config: CaptionModelConfig,
    additional_support_refs: Sequence[str] = (),
) -> dict[str, Any]:
    placement = _validated_occurrence(occurrence)
    crop_path = _resolve_crop(placement, private_root)
    validated_ocr, item_ids = _validated_ocr_evidence(ocr_evidence, placement)
    extra_refs = _normalize_support_refs(
        list(additional_support_refs), "caption_additional_support_refs_invalid"
    )
    allowed_refs = {*item_ids, *extra_refs}
    adapter_identity = _require_adapter_model(config.weights_sha256, adapter)
    request = {
        "schema_version": CAPTION_EVIDENCE_SCHEMA_VERSION,
        "crop_path": str(crop_path),
        "crop_sha256": placement["crop_sha256"],
        "occurrence_id": placement["occurrence_id"],
        "page": placement["page"],
        "bbox": placement["bbox"],
        "coordinate_space": placement["coordinate_space"],
        "ocr_evidence": validated_ocr,
        "allowed_support_refs": sorted(allowed_refs),
        "prompt": config.prompt,
        "decode_config": config.decode_config,
        "model": config.identity,
    }
    payload = adapter.infer("caption_v1", request)
    return _normalize_caption_payload(
        payload,
        occurrence=placement,
        allowed_support_refs=allowed_refs,
        config=config,
        adapter_identity=adapter_identity,
    )


@dataclass(frozen=True)
class VisualRetrievalPolicy:
    ocr_weight: float = 1.0
    layout_weight: float = 0.8
    caption_weight: float = MAX_CAPTION_WEIGHT
    caption_per_query: int = MAX_CAPTION_PER_QUERY
    caption_per_document: int = MAX_CAPTION_PER_DOCUMENT

    def __post_init__(self) -> None:
        for value, code in (
            (self.ocr_weight, "visual_ocr_weight_invalid"),
            (self.layout_weight, "visual_layout_weight_invalid"),
            (self.caption_weight, "visual_caption_weight_invalid"),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not 0 < float(value) <= 1
            ):
                _fail(code)
        if self.caption_weight > MAX_CAPTION_WEIGHT:
            _fail("visual_caption_weight_exceeded")
        if (
            isinstance(self.caption_per_query, bool)
            or not isinstance(self.caption_per_query, int)
            or not 0 <= self.caption_per_query <= MAX_CAPTION_PER_QUERY
        ):
            _fail("visual_caption_query_cap_exceeded")
        if (
            isinstance(self.caption_per_document, bool)
            or not isinstance(self.caption_per_document, int)
            or not 0 <= self.caption_per_document <= MAX_CAPTION_PER_DOCUMENT
        ):
            _fail("visual_caption_document_cap_exceeded")


def _bounded_chunk_text(parts: Sequence[str]) -> str:
    text = "\n".join(part.strip() for part in parts if part.strip()).strip()
    if len(text) > MAX_CHUNK_CHARS:
        text = text[:MAX_CHUNK_CHARS].rstrip()
    return text


def _make_visual_chunk(
    occurrence: Mapping[str, Any],
    *,
    evidence_ids: Sequence[str],
    text: str,
    evidence_type: str,
    chunker_id: str,
    retrieval_weight: float,
    answer_support: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not text:
        _fail("visual_chunk_text_empty")
    evidence_ids = sorted(set(evidence_ids))
    content_sha256 = sha256_text(text)
    identity = {
        "doc_id": occurrence["doc_id"],
        "occurrence_id": occurrence["occurrence_id"],
        "evidence_ids": evidence_ids,
        "content_sha256": content_sha256,
        "evidence_type": evidence_type,
        "chunker_id": chunker_id,
    }
    normalized_answer_support: dict[str, Any] | None = None
    if answer_support is not None:
        if evidence_type != "caption" or set(answer_support) != {
            "status",
            "support_refs",
        }:
            _fail("visual_chunk_answer_support_invalid")
        status = answer_support.get("status")
        refs = _normalize_support_refs(
            answer_support.get("support_refs"),
            "visual_chunk_answer_support_invalid",
        )
        if (
            status not in {"supported", "descriptive_only"}
            or (status == "supported" and not refs)
            or (status == "descriptive_only" and refs)
        ):
            _fail("visual_chunk_answer_support_invalid")
        normalized_answer_support = {"status": status, "support_refs": refs}
        identity["answer_support"] = normalized_answer_support
    citation = {
        "doc_id": occurrence["doc_id"],
        "page": occurrence["page"],
        "bbox": occurrence["bbox"],
        "occurrence_id": occurrence["occurrence_id"],
        "crop_sha256": occurrence["crop_sha256"],
        "evidence_ids": evidence_ids,
    }
    chunk = {
        "schema_version": VISUAL_CHUNK_SCHEMA_VERSION,
        "chunk_id": "vchunk_" + sha256_text(canonical_json(identity))[:24],
        "doc_id": occurrence["doc_id"],
        "occurrence_id": occurrence["occurrence_id"],
        "evidence_ids": evidence_ids,
        "text": text,
        "evidence_type": evidence_type,
        "page": occurrence["page"],
        "bbox": occurrence["bbox"],
        "crop_sha256": occurrence["crop_sha256"],
        "retrieval_role": "visual_auxiliary",
        "chunker_id": chunker_id,
        "retrieval_weight": round(float(retrieval_weight), 6),
        "citation": citation,
        "content_sha256": content_sha256,
    }
    if normalized_answer_support is not None:
        chunk["answer_support"] = normalized_answer_support
    return chunk


def build_visual_chunks(
    occurrence: Mapping[str, Any],
    *,
    ocr_evidence: Mapping[str, Any] | None = None,
    caption_evidence: Mapping[str, Any] | None = None,
    policy: VisualRetrievalPolicy | None = None,
) -> list[dict[str, Any]]:
    placement = _validated_occurrence(occurrence)
    policy = policy or VisualRetrievalPolicy()
    chunks: list[dict[str, Any]] = []

    if ocr_evidence is not None:
        ocr, _ = _validated_ocr_evidence(ocr_evidence, placement)
        if ocr.get("status") != "failed":
            ordered_items = sorted(
                ocr["text_items"], key=lambda item: (item["reading_order"], item["item_id"])
            )
            ocr_text = _bounded_chunk_text([str(item["text"]) for item in ordered_items])
            if ocr_text:
                chunks.append(
                    _make_visual_chunk(
                        placement,
                        evidence_ids=[ocr["evidence_id"]],
                        text=ocr_text,
                        evidence_type="ocr",
                        chunker_id="image-ocr-v1",
                        retrieval_weight=policy.ocr_weight,
                    )
                )
            layout_parts = [
                (
                    f"cell r{cell['row']} c{cell['column']} "
                    f"rs{cell['row_span']} cs{cell['column_span']}: {cell['text']}"
                ).rstrip()
                for cell in ocr["table_cells"]
                if cell["text"]
            ]
            if not layout_parts and len(ordered_items) > 1:
                layout_parts = [
                    f"order {item['reading_order']}: {item['text']}" for item in ordered_items
                ]
            layout_text = _bounded_chunk_text(layout_parts)
            if layout_text:
                chunks.append(
                    _make_visual_chunk(
                        placement,
                        evidence_ids=[ocr["evidence_id"]],
                        text=layout_text,
                        evidence_type="layout",
                        chunker_id="image-layout-v1",
                        retrieval_weight=policy.layout_weight,
                    )
                )

    if caption_evidence is not None:
        if not isinstance(caption_evidence, Mapping):
            _fail("caption_evidence_invalid")
        evidence_id = caption_evidence.get("evidence_id")
        if not isinstance(evidence_id, str) or _CAPTION_EVIDENCE_ID_RE.fullmatch(evidence_id) is None:
            _fail("caption_evidence_id_invalid")
        if caption_evidence.get("occurrence_id") != placement["occurrence_id"] or caption_evidence.get("crop_sha256") != placement["crop_sha256"]:
            _fail("caption_evidence_occurrence_mismatch")
        caption_status = caption_evidence.get("status")
        if caption_status not in {"success", "descriptive_only", "failed"}:
            _fail("caption_evidence_invalid")
        if caption_status != "failed":
            claims = caption_evidence.get("claims")
            if not isinstance(claims, list):
                _fail("caption_evidence_invalid")
            validated_claims: list[dict[str, Any]] = []
            claim_ids: set[str] = set()
            for claim in claims:
                if not isinstance(claim, Mapping):
                    _fail("caption_evidence_invalid")
                claim_id = claim.get("claim_id")
                if (
                    not isinstance(claim_id, str)
                    or _CLAIM_ID_RE.fullmatch(claim_id) is None
                    or claim_id in claim_ids
                ):
                    _fail("caption_evidence_invalid")
                claim_ids.add(claim_id)
                text = _safe_text(
                    claim.get("text"), "caption_evidence_invalid", maximum=5000
                )
                if not text:
                    _fail("caption_evidence_invalid")
                support_refs = _normalize_support_refs(
                    claim.get("support_refs"), "caption_evidence_invalid"
                )
                claim_status = claim.get("status")
                if claim_status not in {"supported", "descriptive_only", "rejected"}:
                    _fail("caption_evidence_invalid")
                if claim_status == "supported" and not support_refs:
                    _fail("caption_evidence_invalid")
                if claim_status == "descriptive_only" and _looks_factual(text):
                    _fail("caption_unsupported_factual_claim")
                validated_claims.append(
                    {"text": text, "support_refs": support_refs, "status": claim_status}
                )
            supported_claims = [
                claim for claim in validated_claims if claim.get("status") == "supported"
            ]
            caption_parts: list[str] = []
            support_refs: list[str] = []
            if supported_claims:
                for claim in supported_claims:
                    caption_parts.append(str(claim["text"]))
                    support_refs.extend(str(value) for value in claim["support_refs"])
                answer_support = {
                    "status": "supported",
                    "support_refs": sorted(set(support_refs)),
                }
            else:
                description = caption_evidence.get("description")
                if isinstance(description, str) and description.strip():
                    sanitized_description, _ = _sanitize_caption_description(
                        _safe_text(
                            description,
                            "caption_evidence_invalid",
                            maximum=20_000,
                        ),
                        validated_claims,
                    )
                    if sanitized_description:
                        caption_parts.append(sanitized_description)
                for claim in validated_claims:
                    if claim.get("status") == "descriptive_only":
                        caption_parts.append(str(claim["text"]))
                answer_support = {
                    "status": "descriptive_only",
                    "support_refs": [],
                }
            caption_text = _bounded_chunk_text(list(dict.fromkeys(caption_parts)))
            if caption_text:
                chunks.append(
                    _make_visual_chunk(
                        placement,
                        evidence_ids=[evidence_id],
                        text=caption_text,
                        evidence_type="caption",
                        chunker_id="image-caption-v1",
                        retrieval_weight=policy.caption_weight,
                        answer_support=answer_support,
                    )
                )
    return chunks


def apply_caption_caps(
    ranked_chunks: Sequence[Mapping[str, Any]],
    *,
    policy: VisualRetrievalPolicy | None = None,
) -> list[dict[str, Any]]:
    """Keep rank order while enforcing hard caption query/document caps."""
    if not isinstance(ranked_chunks, Sequence) or isinstance(ranked_chunks, (str, bytes)):
        _fail("visual_ranked_chunks_invalid")
    policy = policy or VisualRetrievalPolicy()
    selected: list[dict[str, Any]] = []
    caption_total = 0
    caption_by_doc: dict[str, int] = {}
    for raw_chunk in ranked_chunks:
        if not isinstance(raw_chunk, Mapping):
            _fail("visual_ranked_chunk_invalid")
        chunk = dict(raw_chunk)
        if chunk.get("evidence_type") != "caption":
            selected.append(chunk)
            continue
        weight = chunk.get("retrieval_weight")
        if (
            isinstance(weight, bool)
            or not isinstance(weight, (int, float))
            or not math.isfinite(float(weight))
            or float(weight) <= 0
            or float(weight) > MAX_CAPTION_WEIGHT
        ):
            _fail("visual_caption_chunk_weight_invalid")
        doc_id = chunk.get("doc_id")
        if not isinstance(doc_id, str) or _DOC_ID_RE.fullmatch(doc_id) is None:
            _fail("visual_caption_chunk_doc_id_invalid")
        if caption_total >= policy.caption_per_query:
            continue
        if caption_by_doc.get(doc_id, 0) >= policy.caption_per_document:
            continue
        selected.append(chunk)
        caption_total += 1
        caption_by_doc[doc_id] = caption_by_doc.get(doc_id, 0) + 1
    return selected
