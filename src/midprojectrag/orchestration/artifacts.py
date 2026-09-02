"""Private versioned traces, with bounded IO and no automatic external sink."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path

from .types import HarnessConfig


def jsonable(value):
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted(jsonable(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def digest(value) -> str:
    return hashlib.sha256(json.dumps(jsonable(value), sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def trace_record(*, request: dict, store, config: HarnessConfig, policy_id: str, result,
                 provider_calls: list[dict] | None = None, synthetic: bool = False) -> dict:
    record = {"schema_version": "evidence-harness-trace-v1", "request": request,
              "config": jsonable(config), "config_sha256": digest(config),
              "evidence_sha256": digest(store.to_dict()), "policy_id": policy_id,
              "synthetic": synthetic, "official": False, "experience_enabled": False,
              "result": jsonable(result), "provider_calls": provider_calls or []}
    record["trace_sha256"] = digest(record)
    return record


def write_private_json(path: Path, value, *, private_root: Path) -> None:
    # Check before mkdir/open. Never follow an output symlink outside the approved tree.
    root = private_root.absolute()
    if "private" not in root.parts or root.is_symlink():
        raise ValueError("private_root_required")
    target = path.absolute()
    if not target.resolve().is_relative_to(root.resolve()) or target == root:
        raise ValueError("private_output_required")
    for parent in (target, *target.parents):
        if parent == root.parent:
            break
        if parent.is_symlink():
            raise ValueError("private_output_symlink")
    content = json.dumps(jsonable(value), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode()
    if len(content) > 64 * 1024 * 1024:
        raise ValueError("trace_too_large")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def read_json(path: Path, *, max_bytes: int = 64 * 1024 * 1024):
    with path.open("rb") as source:
        raw = source.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("input_too_large")
    def reject_constant(_):
        raise ValueError("non_finite_json")
    return json.loads(raw, parse_constant=reject_constant)
