from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from midprojectrag.ingest.common import canonical_json, sha256_file, sha256_text
from midprojectrag.ingest.visual_evidence import (
    MAX_JSONL_BYTES,
    MAX_JSONL_RECORDS,
    load_jsonl_bounded,
    validate_visual_occurrence,
    write_jsonl_artifact,
)
from midprojectrag.ingest.visual_understanding import (
    CAPTION_EVIDENCE_SCHEMA_VERSION,
    OCR_EVIDENCE_SCHEMA_VERSION,
    VISUAL_CHUNK_SCHEMA_VERSION,
    CaptionModelConfig,
    PpStructureV3Config,
    VisualRetrievalPolicy,
    VisualUnderstandingAdapter,
    build_visual_chunks,
    caption_cache_key,
    ocr_cache_key,
    run_local_caption,
    run_local_ocr,
)


VISUAL_UNDERSTANDING_BATCH_SCHEMA_VERSION = "1.0"
VISUAL_UNDERSTANDING_BATCH_METHOD = "local-visual-understanding-batch-v1"
MAX_CACHE_BYTES = 16 * 1024 * 1024
MAX_METADATA_BYTES = 1024 * 1024

_SHA256_FIELDS = frozenset(
    {
        "source_occurrences_sha256",
        "adapter_code_sha256",
        "ocr_config_sha256",
        "ocr_adapter_identity_sha256",
        "caption_config_sha256",
        "caption_adapter_identity_sha256",
        "policy_sha256",
        "run_identity_sha256",
    }
)


class VisualUnderstandingBatchError(ValueError):
    """Sanitized failure raised by the durable local understanding runner."""


def _fail(code: str) -> None:
    raise VisualUnderstandingBatchError(code)


def _require_sha256(value: Any, error_code: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        _fail(error_code)
    return value


def _strict_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _safe_private_root(private_root: Path) -> Path:
    if not isinstance(private_root, Path) or not private_root.is_absolute() or private_root.is_symlink():
        _fail("visual_batch_private_root_invalid")
    normalized = Path(os.path.abspath(str(private_root)))
    try:
        resolved = private_root.resolve(strict=True)
    except OSError:
        _fail("visual_batch_private_root_invalid")
    if resolved != normalized or not resolved.is_dir():
        _fail("visual_batch_private_root_invalid")
    return resolved


def _reject_symlink_components(root: Path, relative: Path, error_code: str) -> None:
    cursor = root
    for component in relative.parts:
        cursor = cursor / component
        if cursor.is_symlink():
            _fail(error_code)


def _safe_input_file(path: Path, private_root: Path) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or path.is_symlink():
        _fail("visual_batch_input_path_invalid")
    normalized = Path(os.path.abspath(str(path)))
    try:
        resolved = path.resolve(strict=True)
        relative = normalized.relative_to(private_root)
    except (OSError, ValueError):
        _fail("visual_batch_input_path_invalid")
    _reject_symlink_components(private_root, relative, "visual_batch_input_symlink_forbidden")
    if resolved != normalized or not resolved.is_file():
        _fail("visual_batch_input_path_invalid")
    return resolved


def _safe_output_root(output_root: Path, private_root: Path) -> Path:
    if not isinstance(output_root, Path) or not output_root.is_absolute() or output_root.is_symlink():
        _fail("visual_batch_output_root_invalid")
    normalized = Path(os.path.abspath(str(output_root)))
    try:
        relative = normalized.relative_to(private_root)
    except ValueError:
        _fail("visual_batch_output_root_escape")
    if not relative.parts:
        _fail("visual_batch_output_root_invalid")
    _reject_symlink_components(private_root, relative, "visual_batch_output_symlink_forbidden")
    try:
        normalized.mkdir(parents=True, exist_ok=True)
        resolved = normalized.resolve(strict=True)
    except OSError:
        _fail("visual_batch_output_root_invalid")
    if resolved != normalized or not resolved.is_dir():
        _fail("visual_batch_output_root_invalid")
    return resolved


def _safe_output_file(path: Path, *, output_root: Path, error_code: str) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or path.is_symlink():
        _fail(error_code)
    normalized = Path(os.path.abspath(str(path)))
    try:
        relative = normalized.relative_to(output_root)
    except ValueError:
        _fail(error_code)
    if not relative.parts:
        _fail(error_code)
    _reject_symlink_components(output_root, relative, error_code)
    if normalized.exists() and not normalized.is_file():
        _fail(error_code)
    return normalized


def _read_bounded(
    path: Path, *, limit: int, error_code: str, allow_empty: bool = False
) -> bytes:
    if path.is_symlink() or not path.is_file():
        _fail(error_code)
    try:
        size = path.stat().st_size
        if (size < 1 and not allow_empty) or size > limit:
            _fail(error_code)
        payload = path.read_bytes()
    except OSError:
        _fail(error_code)
    if len(payload) != size:
        _fail(error_code)
    return payload


def _read_json_object(path: Path, *, limit: int, error_code: str) -> dict[str, Any]:
    payload = _read_bounded(path, limit=limit, error_code=error_code)
    try:
        value = json.loads(
            payload.decode("utf-8"),
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
            object_pairs_hook=_strict_json_pairs,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError):
        _fail(error_code)
    if not isinstance(value, dict):
        _fail(error_code)
    return value


def _atomic_write(path: Path, payload: bytes, *, error_code: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        _fail(error_code)
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
        _fail(error_code)


def _write_or_verify_bytes(path: Path, payload: bytes, *, error_code: str) -> str:
    digest = hashlib.sha256(payload).hexdigest()
    if path.exists():
        existing = _read_bounded(path, limit=max(len(payload), 1), error_code=error_code)
        if existing != payload:
            _fail(error_code)
        return digest
    _atomic_write(path, payload, error_code=error_code)
    if sha256_file(path) != digest:
        _fail(error_code)
    return digest


def _adapter_identity_sha256(
    adapter: VisualUnderstandingAdapter,
    *,
    expected_model_sha256: str,
    error_code: str,
) -> str:
    try:
        identity = dict(adapter.identity)
        model_sha256 = adapter.model_artifact_sha256
        serialized = canonical_json(identity)
    except (AttributeError, TypeError, ValueError):
        _fail(error_code)
    if (
        model_sha256 != expected_model_sha256
        or identity.get("model_artifact_sha256") != expected_model_sha256
        or identity.get("adapter_kind")
        not in {
            "checksum-pinned-local-json-command-v2",
            "deterministic-fixture-v1",
        }
        or identity.get("network") not in {"os_sandbox_enforced", "not_used"}
    ):
        _fail(error_code)
    return sha256_text(serialized)


def _policy_identity(policy: VisualRetrievalPolicy) -> dict[str, Any]:
    return {
        "ocr_weight": round(float(policy.ocr_weight), 6),
        "layout_weight": round(float(policy.layout_weight), 6),
        "caption_weight": round(float(policy.caption_weight), 6),
        "caption_per_query": policy.caption_per_query,
        "caption_per_document": policy.caption_per_document,
    }


def _eligible_occurrence(record: Mapping[str, Any]) -> bool:
    return (
        record.get("retrieval_status") == "eligible"
        and record.get("placement_status") == "page_bbox_verified"
        and record.get("page") is not None
        and record.get("bbox") is not None
        and record.get("crop_sha256") is not None
        and record.get("crop_relpath") is not None
        and record.get("crop_media_type") == "image/png"
    )


def _validate_ocr_cache_evidence(
    evidence: Any,
    *,
    occurrence: Mapping[str, Any],
    config: PpStructureV3Config,
    adapter_identity_sha256: str,
    policy: VisualRetrievalPolicy,
) -> dict[str, Any]:
    expected_fields = {
        "schema_version",
        "evidence_id",
        "occurrence_id",
        "crop_sha256",
        "status",
        "text_items",
        "table_cells",
        "model",
        "config_sha256",
        "warnings",
    }
    if not isinstance(evidence, Mapping) or set(evidence) != expected_fields:
        _fail("visual_batch_ocr_cache_corrupt")
    record = dict(evidence)
    if (
        record.get("schema_version") != OCR_EVIDENCE_SCHEMA_VERSION
        or record.get("occurrence_id") != occurrence["occurrence_id"]
        or record.get("crop_sha256") != occurrence["crop_sha256"]
        or record.get("config_sha256") != config.config_sha256
        or record.get("model") != config.model_record
    ):
        _fail("visual_batch_ocr_cache_identity_mismatch")
    identity = {
        "occurrence_id": record["occurrence_id"],
        "crop_sha256": record["crop_sha256"],
        "status": record["status"],
        "text_items": record["text_items"],
        "table_cells": record["table_cells"],
        "model": record["model"],
        "config_sha256": record["config_sha256"],
        "adapter_identity_sha256": adapter_identity_sha256,
        "warnings": record["warnings"],
    }
    if record.get("evidence_id") != "ocr_" + sha256_text(canonical_json(identity))[:24]:
        _fail("visual_batch_ocr_cache_corrupt")
    try:
        build_visual_chunks(occurrence, ocr_evidence=record, policy=policy)
    except ValueError:
        _fail("visual_batch_ocr_cache_corrupt")
    return record


def _rebind_cached_ocr_evidence(
    evidence: Mapping[str, Any],
    *,
    occurrence: Mapping[str, Any],
    config: PpStructureV3Config,
    adapter_identity_sha256: str,
    policy: VisualRetrievalPolicy,
) -> dict[str, Any]:
    if evidence.get("crop_sha256") != occurrence["crop_sha256"]:
        _fail("visual_batch_ocr_cache_identity_mismatch")
    source_occurrence = dict(occurrence)
    source_occurrence["occurrence_id"] = evidence.get("occurrence_id")
    source = _validate_ocr_cache_evidence(
        evidence,
        occurrence=source_occurrence,
        config=config,
        adapter_identity_sha256=adapter_identity_sha256,
        policy=policy,
    )
    if source["occurrence_id"] == occurrence["occurrence_id"]:
        return source

    rebound = copy.deepcopy(source)
    rebound["occurrence_id"] = occurrence["occurrence_id"]
    item_id_map: dict[str, str] = {}
    for item in rebound["text_items"]:
        old_item_id = item["item_id"]
        item_identity = {
            "occurrence_id": occurrence["occurrence_id"],
            "crop_sha256": occurrence["crop_sha256"],
            "polygon": item["polygon"],
            "text": item["text"],
            "confidence": item["confidence"],
            "reading_order": item["reading_order"],
        }
        item["item_id"] = "ocri_" + sha256_text(canonical_json(item_identity))[:24]
        item_id_map[old_item_id] = item["item_id"]
    for cell in rebound["table_cells"]:
        try:
            cell["source_item_ids"] = sorted(
                {item_id_map[item_id] for item_id in cell["source_item_ids"]}
            )
        except KeyError:
            _fail("visual_batch_ocr_cache_corrupt")
    identity = {
        "occurrence_id": rebound["occurrence_id"],
        "crop_sha256": rebound["crop_sha256"],
        "status": rebound["status"],
        "text_items": rebound["text_items"],
        "table_cells": rebound["table_cells"],
        "model": rebound["model"],
        "config_sha256": rebound["config_sha256"],
        "adapter_identity_sha256": adapter_identity_sha256,
        "warnings": rebound["warnings"],
    }
    rebound["evidence_id"] = "ocr_" + sha256_text(canonical_json(identity))[:24]
    return _validate_ocr_cache_evidence(
        rebound,
        occurrence=occurrence,
        config=config,
        adapter_identity_sha256=adapter_identity_sha256,
        policy=policy,
    )


def _validate_caption_cache_evidence(
    evidence: Any,
    *,
    occurrence: Mapping[str, Any],
    config: CaptionModelConfig,
    adapter_identity_sha256: str,
    ocr_evidence: Mapping[str, Any],
    policy: VisualRetrievalPolicy,
) -> dict[str, Any]:
    expected_fields = {
        "schema_version",
        "evidence_id",
        "occurrence_id",
        "crop_sha256",
        "description",
        "claims",
        "model",
        "weights_sha256",
        "prompt_sha256",
        "decode_config_sha256",
        "status",
        "warnings",
    }
    if not isinstance(evidence, Mapping) or set(evidence) != expected_fields:
        _fail("visual_batch_caption_cache_corrupt")
    record = dict(evidence)
    if (
        record.get("schema_version") != CAPTION_EVIDENCE_SCHEMA_VERSION
        or record.get("occurrence_id") != occurrence["occurrence_id"]
        or record.get("crop_sha256") != occurrence["crop_sha256"]
        or record.get("model") != f"{config.model_name}@{config.model_version}"
        or record.get("weights_sha256") != config.weights_sha256
        or record.get("prompt_sha256") != config.prompt_sha256
        or record.get("decode_config_sha256") != config.decode_config_sha256
    ):
        _fail("visual_batch_caption_cache_identity_mismatch")
    identity = {
        "occurrence_id": record["occurrence_id"],
        "crop_sha256": record["crop_sha256"],
        "description": record["description"],
        "claims": record["claims"],
        "model": record["model"],
        "weights_sha256": record["weights_sha256"],
        "prompt_sha256": record["prompt_sha256"],
        "decode_config_sha256": record["decode_config_sha256"],
        "adapter_identity_sha256": adapter_identity_sha256,
        "status": record["status"],
        "warnings": record["warnings"],
    }
    if record.get("evidence_id") != "cap_" + sha256_text(canonical_json(identity))[:24]:
        _fail("visual_batch_caption_cache_corrupt")
    try:
        build_visual_chunks(
            occurrence,
            ocr_evidence=ocr_evidence,
            caption_evidence=record,
            policy=policy,
        )
    except ValueError:
        _fail("visual_batch_caption_cache_corrupt")
    return record


def _cache_envelope(
    *,
    cache_kind: str,
    cache_key: str,
    occurrence: Mapping[str, Any],
    config_sha256: str,
    adapter_identity_sha256: str,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    identity = {
        "cache_kind": cache_kind,
        "cache_key": cache_key,
        "crop_sha256": occurrence["crop_sha256"],
        "config_sha256": config_sha256,
        "adapter_identity_sha256": adapter_identity_sha256,
    }
    if cache_kind == "caption":
        identity["occurrence_id"] = occurrence["occurrence_id"]
    return {
        "schema_version": VISUAL_UNDERSTANDING_BATCH_SCHEMA_VERSION,
        "cache_contract": "content-addressed-local-evidence-v1",
        "identity": identity,
        "identity_sha256": sha256_text(canonical_json(identity)),
        "evidence": dict(evidence),
    }


def _load_cache(
    path: Path,
    *,
    expected: Mapping[str, Any],
    error_prefix: str,
) -> Mapping[str, Any] | None:
    if not path.exists():
        return None
    envelope = _read_json_object(
        path, limit=MAX_CACHE_BYTES, error_code=f"{error_prefix}_corrupt"
    )
    if set(envelope) != {
        "schema_version",
        "cache_contract",
        "identity",
        "identity_sha256",
        "evidence",
    }:
        _fail(f"{error_prefix}_corrupt")
    identity = envelope.get("identity")
    if (
        envelope.get("schema_version") != VISUAL_UNDERSTANDING_BATCH_SCHEMA_VERSION
        or envelope.get("cache_contract") != "content-addressed-local-evidence-v1"
        or not isinstance(identity, Mapping)
        or dict(identity) != dict(expected)
        or envelope.get("identity_sha256") != sha256_text(canonical_json(expected))
    ):
        _fail(f"{error_prefix}_identity_mismatch")
    evidence = envelope.get("evidence")
    if not isinstance(evidence, Mapping):
        _fail(f"{error_prefix}_corrupt")
    return evidence


def _write_cache(path: Path, envelope: Mapping[str, Any], *, error_code: str) -> None:
    payload = (canonical_json(envelope) + "\n").encode("utf-8")
    if len(payload) > MAX_CACHE_BYTES:
        _fail(error_code)
    _write_or_verify_bytes(path, payload, error_code=error_code)


def _jsonl_payload(records: Sequence[Mapping[str, Any]]) -> bytes:
    if len(records) > MAX_JSONL_RECORDS:
        _fail("visual_batch_artifact_limit_exceeded")
    payload = b"".join(
        (canonical_json(record) + "\n").encode("utf-8") for record in records
    )
    if len(payload) > MAX_JSONL_BYTES:
        _fail("visual_batch_artifact_limit_exceeded")
    return payload


def _verify_strict_jsonl_source(
    path: Path, records: Sequence[Mapping[str, Any]]
) -> None:
    index = 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip() or index >= len(records):
                    _fail("visual_batch_input_jsonl_corrupt")
                value = json.loads(
                    line,
                    parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
                    object_pairs_hook=_strict_json_pairs,
                )
                if not isinstance(value, dict) or value != records[index]:
                    _fail("visual_batch_input_jsonl_corrupt")
                index += 1
    except VisualUnderstandingBatchError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        _fail("visual_batch_input_jsonl_corrupt")
    if index != len(records):
        _fail("visual_batch_input_jsonl_corrupt")


def _write_or_verify_jsonl(
    records: Sequence[Mapping[str, Any]],
    *,
    path: Path,
    private_root: Path,
) -> str:
    payload = _jsonl_payload(records)
    if path.exists():
        existing = _read_bounded(
            path,
            limit=max(len(payload), 1),
            error_code="visual_batch_artifact_corrupt_or_stale",
            allow_empty=True,
        )
        if existing != payload:
            _fail("visual_batch_artifact_corrupt_or_stale")
        return hashlib.sha256(payload).hexdigest()
    digest = write_jsonl_artifact(records, output=path, private_root=private_root)
    if digest != hashlib.sha256(payload).hexdigest():
        _fail("visual_batch_artifact_write_mismatch")
    return digest


def _validate_committed_metadata(
    metadata: Mapping[str, Any],
    *,
    run_identity_sha256: str,
    expected_artifacts: set[str],
    output_root: Path,
) -> None:
    expected_fields = {
        "schema_version",
        "method",
        "run_identity_sha256",
        "source_occurrences_sha256",
        "adapter_code_sha256",
        "ocr_config_sha256",
        "ocr_adapter_identity_sha256",
        "caption_enabled",
        "caption_config_sha256",
        "caption_adapter_identity_sha256",
        "policy_sha256",
        "counts",
        "status_counts",
        "artifact_hashes",
        "external_api_calls",
        "private_egress",
        "strict_reuse_eligible",
    }
    if set(metadata) != expected_fields:
        _fail("visual_batch_metadata_corrupt")
    if (
        metadata.get("schema_version") != VISUAL_UNDERSTANDING_BATCH_SCHEMA_VERSION
        or metadata.get("method") != VISUAL_UNDERSTANDING_BATCH_METHOD
        or metadata.get("run_identity_sha256") != run_identity_sha256
        or metadata.get("external_api_calls") != 0
        or metadata.get("private_egress") is not False
        or metadata.get("strict_reuse_eligible") is not True
    ):
        _fail("visual_batch_stale_identity")
    caption_expected = "caption-evidence-v1.jsonl" in expected_artifacts
    if (
        not isinstance(metadata.get("caption_enabled"), bool)
        or metadata.get("caption_enabled") != caption_expected
        or (
            caption_expected
            and (
                metadata.get("caption_config_sha256") is None
                or metadata.get("caption_adapter_identity_sha256") is None
            )
        )
        or (
            not caption_expected
            and (
                metadata.get("caption_config_sha256") is not None
                or metadata.get("caption_adapter_identity_sha256") is not None
            )
        )
    ):
        _fail("visual_batch_metadata_corrupt")
    for field in _SHA256_FIELDS:
        value = metadata.get(field)
        if field.startswith("caption_") and value is None:
            continue
        _require_sha256(value, "visual_batch_metadata_corrupt")
    counts = metadata.get("counts")
    status_counts = metadata.get("status_counts")
    if (
        not isinstance(counts, Mapping)
        or not isinstance(status_counts, Mapping)
        or any(
            not isinstance(key, str)
            or not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            for source in (counts, status_counts)
            for key, value in source.items()
        )
    ):
        _fail("visual_batch_metadata_corrupt")
    artifact_hashes = metadata.get("artifact_hashes")
    if not isinstance(artifact_hashes, Mapping) or set(artifact_hashes) != expected_artifacts:
        _fail("visual_batch_metadata_corrupt")
    for filename, digest in artifact_hashes.items():
        _require_sha256(digest, "visual_batch_metadata_corrupt")
        path = _safe_output_file(
            output_root / filename,
            output_root=output_root,
            error_code="visual_batch_artifact_corrupt_or_stale",
        )
        if not path.exists() or sha256_file(path) != digest:
            _fail("visual_batch_artifact_corrupt_or_stale")


def run_visual_understanding_batch(
    *,
    private_root: Path,
    occurrences_path: Path,
    output_root: Path,
    adapter_code_sha256: str,
    ocr_adapter: VisualUnderstandingAdapter,
    ocr_config: PpStructureV3Config,
    policy: VisualRetrievalPolicy,
    caption_adapter: VisualUnderstandingAdapter | None = None,
    caption_config: CaptionModelConfig | None = None,
    additional_support_refs: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    """Run an offline, resumable, content-addressed OCR/caption batch.

    All paths are confined to ``private_root``. The returned summary and committed
    metadata contain counts and immutable hashes only; recognized text remains in
    private evidence and chunk artifacts.
    """

    root = _safe_private_root(private_root)
    source = _safe_input_file(occurrences_path, root)
    destination = _safe_output_root(output_root, root)
    adapter_code_sha256 = _require_sha256(
        adapter_code_sha256, "visual_batch_adapter_code_hash_invalid"
    )
    if not isinstance(ocr_config, PpStructureV3Config) or not isinstance(policy, VisualRetrievalPolicy):
        _fail("visual_batch_config_invalid")
    caption_enabled = caption_adapter is not None or caption_config is not None
    if (caption_adapter is None) != (caption_config is None):
        _fail("visual_batch_caption_config_incomplete")

    source_occurrences_sha256 = sha256_file(source)
    records = load_jsonl_bounded(source)
    _verify_strict_jsonl_source(source, records)
    occurrence_ids: set[str] = set()
    for record in records:
        validate_visual_occurrence(record)
        occurrence_id = record["occurrence_id"]
        if occurrence_id in occurrence_ids:
            _fail("visual_batch_duplicate_occurrence")
        occurrence_ids.add(occurrence_id)
    records.sort(key=lambda record: record["occurrence_id"])

    support_by_occurrence: dict[str, tuple[str, ...]] = {}
    if additional_support_refs is not None:
        if not isinstance(additional_support_refs, Mapping):
            _fail("visual_batch_support_refs_invalid")
        for occurrence_id, refs in additional_support_refs.items():
            if occurrence_id not in occurrence_ids or isinstance(refs, (str, bytes)) or not isinstance(refs, Sequence):
                _fail("visual_batch_support_refs_invalid")
            normalized: list[str] = []
            for ref in refs:
                if not isinstance(ref, str) or not ref or len(ref) > 256 or "\x00" in ref:
                    _fail("visual_batch_support_refs_invalid")
                normalized.append(ref)
            support_by_occurrence[occurrence_id] = tuple(sorted(set(normalized)))

    ocr_adapter_hash = _adapter_identity_sha256(
        ocr_adapter,
        expected_model_sha256=ocr_config.weights_sha256,
        error_code="visual_batch_ocr_adapter_identity_invalid",
    )
    caption_adapter_hash: str | None = None
    caption_config_hash: str | None = None
    if caption_enabled:
        assert caption_adapter is not None and caption_config is not None
        caption_adapter_hash = _adapter_identity_sha256(
            caption_adapter,
            expected_model_sha256=caption_config.weights_sha256,
            error_code="visual_batch_caption_adapter_identity_invalid",
        )
        caption_config_hash = sha256_text(canonical_json(caption_config.identity))
    policy_sha256 = sha256_text(canonical_json(_policy_identity(policy)))
    run_identity = {
        "batch_contract": VISUAL_UNDERSTANDING_BATCH_SCHEMA_VERSION,
        "source_occurrences_sha256": source_occurrences_sha256,
        "adapter_code_sha256": adapter_code_sha256,
        "ocr_config_sha256": ocr_config.config_sha256,
        "ocr_adapter_identity_sha256": ocr_adapter_hash,
        "caption_enabled": caption_enabled,
        "caption_config_sha256": caption_config_hash,
        "caption_adapter_identity_sha256": caption_adapter_hash,
        "policy_sha256": policy_sha256,
        "support_refs_sha256": sha256_text(canonical_json(support_by_occurrence)),
    }
    run_identity_sha256 = sha256_text(canonical_json(run_identity))

    artifacts = {
        "ocr-evidence-v1.jsonl": destination / "ocr-evidence-v1.jsonl",
        "visual-chunks-v1.jsonl": destination / "visual-chunks-v1.jsonl",
    }
    if caption_enabled:
        artifacts["caption-evidence-v1.jsonl"] = destination / "caption-evidence-v1.jsonl"
    elif (destination / "caption-evidence-v1.jsonl").exists():
        _fail("visual_batch_artifact_corrupt_or_stale")
    for path in artifacts.values():
        _safe_output_file(
            path,
            output_root=destination,
            error_code="visual_batch_artifact_output_invalid",
        )

    metadata_path = _safe_output_file(
        destination / "visual-understanding-batch-v1.json",
        output_root=destination,
        error_code="visual_batch_metadata_path_invalid",
    )
    if metadata_path.exists():
        committed = _read_json_object(
            metadata_path,
            limit=MAX_METADATA_BYTES,
            error_code="visual_batch_metadata_corrupt",
        )
        _validate_committed_metadata(
            committed,
            run_identity_sha256=run_identity_sha256,
            expected_artifacts=set(artifacts),
            output_root=destination,
        )

    cache_root = destination / "cache"
    ocr_cache_root = cache_root / "ocr"
    caption_cache_root = cache_root / "caption"
    for directory in (cache_root, ocr_cache_root):
        _safe_output_root(directory, root)
    if caption_enabled:
        _safe_output_root(caption_cache_root, root)

    ocr_records: list[dict[str, Any]] = []
    caption_records: list[dict[str, Any]] = []
    chunk_records: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    eligible_count = 0
    skipped_count = 0

    for occurrence in records:
        if not _eligible_occurrence(occurrence):
            skipped_count += 1
            status_counts[f"skipped:{occurrence['retrieval_status']}"] += 1
            continue
        eligible_count += 1
        ocr_key = ocr_cache_key(occurrence, ocr_config, ocr_adapter)
        ocr_identity = {
            "cache_kind": "ocr",
            "cache_key": ocr_key,
            "crop_sha256": occurrence["crop_sha256"],
            "config_sha256": ocr_config.config_sha256,
            "adapter_identity_sha256": ocr_adapter_hash,
        }
        ocr_cache_path = _safe_output_file(
            ocr_cache_root / f"{ocr_key}.json",
            output_root=destination,
            error_code="visual_batch_ocr_cache_path_invalid",
        )
        cached_ocr = _load_cache(
            ocr_cache_path,
            expected=ocr_identity,
            error_prefix="visual_batch_ocr_cache",
        )
        if cached_ocr is None:
            ocr = run_local_ocr(
                occurrence,
                private_root=root,
                adapter=ocr_adapter,
                config=ocr_config,
            )
            ocr = _validate_ocr_cache_evidence(
                ocr,
                occurrence=occurrence,
                config=ocr_config,
                adapter_identity_sha256=ocr_adapter_hash,
                policy=policy,
            )
            _write_cache(
                ocr_cache_path,
                _cache_envelope(
                    cache_kind="ocr",
                    cache_key=ocr_key,
                    occurrence=occurrence,
                    config_sha256=ocr_config.config_sha256,
                    adapter_identity_sha256=ocr_adapter_hash,
                    evidence=ocr,
                ),
                error_code="visual_batch_ocr_cache_write_failed",
            )
        else:
            ocr = _rebind_cached_ocr_evidence(
                cached_ocr,
                occurrence=occurrence,
                config=ocr_config,
                adapter_identity_sha256=ocr_adapter_hash,
                policy=policy,
            )
        ocr_records.append(ocr)
        status_counts[f"ocr:{ocr['status']}"] += 1

        caption: dict[str, Any] | None = None
        if caption_enabled:
            assert caption_adapter is not None and caption_config is not None
            assert caption_adapter_hash is not None and caption_config_hash is not None
            caption_key = caption_cache_key(occurrence, ocr, caption_config, caption_adapter)
            caption_identity = {
                "cache_kind": "caption",
                "cache_key": caption_key,
                "occurrence_id": occurrence["occurrence_id"],
                "crop_sha256": occurrence["crop_sha256"],
                "config_sha256": caption_config_hash,
                "adapter_identity_sha256": caption_adapter_hash,
            }
            caption_cache_path = _safe_output_file(
                caption_cache_root / f"{caption_key}.json",
                output_root=destination,
                error_code="visual_batch_caption_cache_path_invalid",
            )
            cached_caption = _load_cache(
                caption_cache_path,
                expected=caption_identity,
                error_prefix="visual_batch_caption_cache",
            )
            if cached_caption is None:
                caption = run_local_caption(
                    occurrence,
                    ocr,
                    private_root=root,
                    adapter=caption_adapter,
                    config=caption_config,
                    additional_support_refs=support_by_occurrence.get(
                        occurrence["occurrence_id"], ()
                    ),
                )
                caption = _validate_caption_cache_evidence(
                    caption,
                    occurrence=occurrence,
                    config=caption_config,
                    adapter_identity_sha256=caption_adapter_hash,
                    ocr_evidence=ocr,
                    policy=policy,
                )
                _write_cache(
                    caption_cache_path,
                    _cache_envelope(
                        cache_kind="caption",
                        cache_key=caption_key,
                        occurrence=occurrence,
                        config_sha256=caption_config_hash,
                        adapter_identity_sha256=caption_adapter_hash,
                        evidence=caption,
                    ),
                    error_code="visual_batch_caption_cache_write_failed",
                )
            else:
                caption = _validate_caption_cache_evidence(
                    cached_caption,
                    occurrence=occurrence,
                    config=caption_config,
                    adapter_identity_sha256=caption_adapter_hash,
                    ocr_evidence=ocr,
                    policy=policy,
                )
            caption_records.append(caption)
            status_counts[f"caption:{caption['status']}"] += 1

        chunks = build_visual_chunks(
            occurrence,
            ocr_evidence=ocr,
            caption_evidence=caption,
            policy=policy,
        )
        for chunk in chunks:
            if chunk.get("schema_version") != VISUAL_CHUNK_SCHEMA_VERSION:
                _fail("visual_batch_chunk_contract_invalid")
            status_counts[f"chunk:{chunk['evidence_type']}"] += 1
        chunk_records.extend(chunks)

    ocr_records.sort(key=lambda record: (record["occurrence_id"], record["evidence_id"]))
    caption_records.sort(key=lambda record: (record["occurrence_id"], record["evidence_id"]))
    chunk_records.sort(
        key=lambda record: (
            record["occurrence_id"],
            record["evidence_type"],
            record["chunk_id"],
        )
    )

    artifact_hashes: dict[str, str] = {}
    for filename, path in sorted(artifacts.items()):
        if filename == "ocr-evidence-v1.jsonl":
            artifact_records = ocr_records
        elif filename == "caption-evidence-v1.jsonl":
            artifact_records = caption_records
        else:
            artifact_records = chunk_records
        artifact_hashes[filename] = _write_or_verify_jsonl(
            artifact_records,
            path=path,
            private_root=root,
        )

    counts = {
        "occurrence_total": len(records),
        "eligible_occurrence": eligible_count,
        "skipped_ineligible": skipped_count,
        "ocr_evidence": len(ocr_records),
        "caption_evidence": len(caption_records),
        "visual_chunk": len(chunk_records),
    }
    metadata = {
        "schema_version": VISUAL_UNDERSTANDING_BATCH_SCHEMA_VERSION,
        "method": VISUAL_UNDERSTANDING_BATCH_METHOD,
        "run_identity_sha256": run_identity_sha256,
        "source_occurrences_sha256": source_occurrences_sha256,
        "adapter_code_sha256": adapter_code_sha256,
        "ocr_config_sha256": ocr_config.config_sha256,
        "ocr_adapter_identity_sha256": ocr_adapter_hash,
        "caption_enabled": caption_enabled,
        "caption_config_sha256": caption_config_hash,
        "caption_adapter_identity_sha256": caption_adapter_hash,
        "policy_sha256": policy_sha256,
        "counts": counts,
        "status_counts": dict(sorted(status_counts.items())),
        "artifact_hashes": dict(sorted(artifact_hashes.items())),
        "external_api_calls": 0,
        "private_egress": False,
        "strict_reuse_eligible": True,
    }
    metadata_payload = (canonical_json(metadata) + "\n").encode("utf-8")
    if len(metadata_payload) > MAX_METADATA_BYTES:
        _fail("visual_batch_metadata_limit_exceeded")
    _write_or_verify_bytes(
        metadata_path,
        metadata_payload,
        error_code="visual_batch_metadata_corrupt_or_stale",
    )
    return metadata
