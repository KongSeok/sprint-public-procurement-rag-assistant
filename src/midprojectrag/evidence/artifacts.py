"""Private, append-only evidence bundle persistence with verified identities."""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Mapping

from .builder import SplitConfig, validate_chunking
from .store import EvidenceStore


def private_path(path: Path, data_root: Path) -> Path:
    data = Path(data_root).resolve()
    if (data / "private").is_symlink():
        raise ValueError("private_root_symlink_not_allowed")
    root, target = (data / "private").resolve(), Path(path).resolve()
    if target == root or not target.is_relative_to(root):
        raise ValueError("artifact_requires_private_child_directory")
    return target


def file_sha(path: Path) -> str:
    value = sha256()
    with path.open("rb") as source:
        for part in iter(lambda: source.read(1024 * 1024), b""):
            value.update(part)
    return value.hexdigest()


def write_new_json(path: Path, value: object) -> None:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(payload)


def _hashes(value: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value or any(
        type(k) is not str or not k or type(v) is not str or len(v) != 64
        or any(c not in "0123456789abcdef" for c in v) for k, v in value.items()
    ):
        raise ValueError("invalid_source_artifact_hashes")
    return dict(sorted(value.items()))


def freeze_bundle(store: EvidenceStore, config: SplitConfig, input_hashes: Mapping[str, str], *,
                  output_dir: Path, data_root: Path) -> dict:
    inputs = _hashes(input_hashes)
    validate_chunking(store, config)
    target = private_path(output_dir, data_root)
    target.mkdir(parents=True, exist_ok=False, mode=0o700)
    write_new_json(target / "store.json", store.to_dict())
    receipt = {"schema_version": "1.0", "bundle_sha256": store.bundle_sha256,
               "store_file_sha256": file_sha(target / "store.json"),
               "chunk_config": config.to_dict(), "chunk_config_sha256": config.config_sha256,
               "input_hashes": inputs, "parent_count": len(store.parents),
               "evidence_count": len(store.evidence), "doc_count": len(store.doc_ids)}
    write_new_json(target / "receipt.json", receipt)
    return receipt


def load_bundle(output_dir: Path, *, data_root: Path) -> tuple[EvidenceStore, dict]:
    target = private_path(output_dir, data_root)
    if any(not (target / name).resolve().is_relative_to(target) for name in ("receipt.json", "store.json")):
        raise ValueError("bundle_file_symlink_escape")
    receipt = json.loads((target / "receipt.json").read_text(encoding="utf-8"))
    fields = {"schema_version", "bundle_sha256", "store_file_sha256", "chunk_config", "chunk_config_sha256",
              "input_hashes", "parent_count", "evidence_count", "doc_count"}
    if type(receipt) is not dict or set(receipt) != fields or receipt["schema_version"] != "1.0":
        raise ValueError("invalid_bundle_receipt")
    _hashes(receipt["input_hashes"])
    raw = receipt["chunk_config"]
    if type(raw) is not dict or set(raw) != {"chunker_id", "max_chars", "version"} or raw["version"] != "1.0":
        raise ValueError("invalid_chunk_config")
    config = SplitConfig(raw["chunker_id"], raw["max_chars"])
    if config.config_sha256 != receipt["chunk_config_sha256"] or file_sha(target / "store.json") != receipt["store_file_sha256"]:
        raise ValueError("bundle_artifact_hash_mismatch")
    store = EvidenceStore.from_dict(json.loads((target / "store.json").read_text(encoding="utf-8")))
    validate_chunking(store, config)
    if (store.bundle_sha256, len(store.parents), len(store.evidence), len(store.doc_ids)) != (
        receipt["bundle_sha256"], receipt["parent_count"], receipt["evidence_count"], receipt["doc_count"]
    ):
        raise ValueError("bundle_identity_count_mismatch")
    return store, receipt
