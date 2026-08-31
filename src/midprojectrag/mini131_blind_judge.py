"""Translate blind Mini-131 review decisions into provenance-complete judgments.

The semantic reviewer is intentionally limited to three tracked inputs:

* ``blind-judge-inputs.jsonl``
* ``evaluation/rubric.md``
* ``evaluation/baselines/mini131-bundle-v1/judge-config.json``

It must never receive ``judge-packets.jsonl``.  This module is the local,
deterministic post-review bridge: it validates a closed decision schema keyed
only by ``blind_id`` and ``judge_input_sha256``, then joins those decisions to
the full private packets and emits the closed judgment rows accepted by
``midprojectrag.mini131_bundle``.  It performs no semantic scoring or inference.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from midprojectrag.ingest.common import (
    canonical_json,
    read_jsonl,
    sha256_file,
    sha256_text,
)
from midprojectrag.mini131_bundle import (
    BLIND_ADJUDICATION_INPUT_SCHEMA_VERSION,
    BLIND_DECISION_SCHEMA_VERSION,
    BLIND_JUDGE_INPUT_SCHEMA_VERSION,
    BLIND_REVIEW_HISTORY_SCHEMA_VERSION,
    JUDGE_MODEL,
    JUDGE_ROLES,
    JUDGE_RUBRIC,
    ROLE_DECISIONS,
    SHA256_RE,
    _atomic_private_jsonl,
    _blind_judge_rows,
    _expected_behavior,
    _expected_judge_config,
    _binary_recommendation,
    _judgment_id,
    _secondary_triggered,
    _validate_judgment_decision,
    _validate_judgment_scores,
    _validate_packets,
    _valid_rfc3339,
)


SCHEMA_VERSION = "mini131-blind-judge-io.v1"
FULL_JUDGMENT_SCHEMA_VERSION = "1.0"
REVIEWER_TYPE = "llm"
REASONING_EFFORT = "high"

BLIND_DECISION_FIELDS = frozenset(
    {
        "schema_version",
        "blind_id",
        "judge_input_sha256",
        "review_config_sha256",
        "rubric_version",
        "reviewer_type",
        "model",
        "judge_role",
        "scores",
        "matched_key_point_ids",
        "follow_up_success",
        "safe_abstention",
        "critical_flags",
        "confidence",
        "judge_decision",
        "rationale",
        "reviewed_at",
    }
)
FORBIDDEN_BLIND_DECISION_FIELDS = frozenset(
    {"case_id", "lane", "lineage", "case_sha256", "run_record_sha256"}
)
ROLE_ORDER = {"primary": 0, "secondary": 1, "adjudicator": 2}
IDENTITY_FIELDS = frozenset({"case_id", "lane", "lineage"})
ADJUDICATION_INPUT_FIELDS = frozenset(
    {
        "schema_version",
        "blind_id",
        "judge_input_sha256",
        "review_config_sha256",
        "blind_input",
        "primary_decision",
        "secondary_decision",
        "input_sha256",
    }
)
REVIEW_HISTORY_FIELDS = frozenset(
    {
        "schema_version",
        "blind_id",
        "judge_input_sha256",
        "review_config_sha256",
        "rubric_sha256",
        "reviewer_type",
        "model",
        "reasoning_effort",
        "judge_role",
        "input_schema_version",
        "input_sha256",
        "output_schema_version",
        "output_sha256",
        "review_input",
        "review_output",
        "history_sha256",
    }
)


@dataclass(frozen=True)
class BlindJudgePaths:
    blind_inputs: Path
    judge_packets: Path
    rubric: Path
    judge_config: Path
    judgments: Path


def default_paths(repo_root: Path) -> BlindJudgePaths:
    root = repo_root.resolve()
    run_root = root / "evaluation/private/mini131/runs/baseline-v1"
    return BlindJudgePaths(
        blind_inputs=run_root / "blind-judge-inputs.jsonl",
        judge_packets=run_root / "judge-packets.jsonl",
        rubric=root / "evaluation/rubric.md",
        judge_config=root
        / "evaluation/baselines/mini131-bundle-v1/judge-config.json",
        judgments=run_root / "judgments.jsonl",
    )


def _load_rows(path: Path, code: str) -> list[dict[str, Any]]:
    try:
        return read_jsonl(path)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(code) from error


def _read_json(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(code) from error
    if not isinstance(value, dict):
        raise ValueError(code)
    return value


def _assert_no_identity_fields(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).lower() in IDENTITY_FIELDS:
                raise ValueError("mini131_blind_identity_leak")
            _assert_no_identity_fields(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_identity_fields(nested)


def _content_sha256(value: Any) -> str:
    return sha256_text(canonical_json(value))


def _validate_string_list(value: Any, *, code: str) -> None:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item for item in value)
        or len(value) != len(set(value))
    ):
        raise ValueError(code)


def _review_config_sha256(paths: BlindJudgePaths) -> str:
    rubric_sha256 = sha256_file(paths.rubric)
    config = _read_json(paths.judge_config, "mini131_blind_judge_config_invalid")
    if config != _expected_judge_config(rubric_sha256):
        raise ValueError("mini131_blind_judge_config_mismatch")
    if config.get("reasoning_effort") != REASONING_EFFORT:
        raise ValueError("mini131_blind_reasoning_effort_mismatch")
    return sha256_file(paths.judge_config)


def _source_indexes(
    paths: BlindJudgePaths,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, int],
]:
    packets = _load_rows(paths.judge_packets, "mini131_blind_judge_packets_invalid")
    _validate_packets(packets)
    blind_rows = _load_rows(paths.blind_inputs, "mini131_blind_inputs_invalid")
    expected_blind_rows = _blind_judge_rows(packets)
    if blind_rows != expected_blind_rows:
        raise ValueError("mini131_blind_inputs_packet_mismatch")

    packet_by_input_hash: dict[str, dict[str, Any]] = {}
    packet_order: dict[str, int] = {}
    for index, packet in enumerate(packets):
        input_hash = packet["hashes"]["judge_input_sha256"]
        if input_hash in packet_by_input_hash:
            raise ValueError("mini131_blind_duplicate_input_hash")
        packet_by_input_hash[input_hash] = copy.deepcopy(packet)
        packet_order[input_hash] = index

    blind_by_id: dict[str, dict[str, Any]] = {}
    for row in blind_rows:
        blind_id = row.get("blind_id")
        if not isinstance(blind_id, str) or not SHA256_RE.fullmatch(blind_id):
            raise ValueError("mini131_blind_id_invalid")
        if blind_id in blind_by_id:
            raise ValueError("mini131_blind_duplicate_id")
        blind_by_id[blind_id] = copy.deepcopy(row)
    return blind_by_id, packet_by_input_hash, packet_order


def _validate_blind_decision(
    raw: Mapping[str, Any],
    *,
    blind_by_id: Mapping[str, Mapping[str, Any]],
    packet_by_input_hash: Mapping[str, Mapping[str, Any]],
    review_config_sha256: str,
) -> dict[str, Any]:
    row = copy.deepcopy(dict(raw))
    if set(row) != BLIND_DECISION_FIELDS:
        raise ValueError("mini131_blind_decision_fields_invalid")
    if set(row) & FORBIDDEN_BLIND_DECISION_FIELDS:
        raise ValueError("mini131_blind_decision_identity_leak")
    if row.get("schema_version") != BLIND_DECISION_SCHEMA_VERSION:
        raise ValueError("mini131_blind_decision_schema_invalid")

    blind_id = row.get("blind_id")
    input_hash = row.get("judge_input_sha256")
    if not isinstance(blind_id, str) or not SHA256_RE.fullmatch(blind_id):
        raise ValueError("mini131_blind_decision_id_invalid")
    if not isinstance(input_hash, str) or not SHA256_RE.fullmatch(input_hash):
        raise ValueError("mini131_blind_decision_input_hash_invalid")
    blind_input = blind_by_id.get(blind_id)
    if blind_input is None or blind_input.get("judge_input_sha256") != input_hash:
        raise ValueError("mini131_blind_decision_binding_mismatch")
    packet = packet_by_input_hash.get(input_hash)
    if packet is None:
        raise ValueError("mini131_blind_decision_packet_missing")

    if row.get("review_config_sha256") != review_config_sha256:
        raise ValueError("mini131_blind_decision_review_config_mismatch")
    if row.get("rubric_version") != JUDGE_RUBRIC:
        raise ValueError("mini131_blind_decision_rubric_mismatch")
    if row.get("reviewer_type") != REVIEWER_TYPE:
        raise ValueError("mini131_blind_decision_reviewer_type_mismatch")
    if row.get("model") != JUDGE_MODEL:
        raise ValueError("mini131_blind_decision_model_mismatch")
    role = row.get("judge_role")
    if role not in JUDGE_ROLES:
        raise ValueError("mini131_blind_decision_role_invalid")
    if row.get("judge_decision") not in ROLE_DECISIONS[str(role)]:
        raise ValueError("mini131_blind_decision_value_invalid")

    expected_behavior = _expected_behavior(packet)
    _validate_judgment_scores(
        row.get("scores"), expected_behavior=expected_behavior
    )
    _validate_string_list(
        row.get("matched_key_point_ids"),
        code="mini131_blind_matched_key_point_ids_invalid",
    )
    _validate_string_list(
        row.get("critical_flags"),
        code="mini131_blind_critical_flags_invalid",
    )
    for field in ("follow_up_success", "safe_abstention"):
        value = row.get(field)
        if value is not None and not isinstance(value, bool):
            raise ValueError(f"mini131_blind_{field}_invalid")
    confidence = row.get("confidence")
    if (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not 0 <= float(confidence) <= 1
    ):
        raise ValueError("mini131_blind_confidence_invalid")
    rationale = row.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("mini131_blind_rationale_invalid")
    if not _valid_rfc3339(row.get("reviewed_at")):
        raise ValueError("mini131_blind_reviewed_at_invalid")

    hashes = packet["hashes"]
    observed_status = packet["judge_input"]["candidate"]["status"]
    judgment: dict[str, Any] = {
        "schema_version": FULL_JUDGMENT_SCHEMA_VERSION,
        "judgment_id": "pending",
        "case_id": packet["case_id"],
        "case_sha256": hashes["case_sha256"],
        "run_record_sha256": hashes["run_sha256"],
        "judge_input_sha256": input_hash,
        "review_config_sha256": review_config_sha256,
        "rubric_version": row["rubric_version"],
        "reviewer_type": row["reviewer_type"],
        "model": row["model"],
        "judge_role": role,
        "expected_behavior": expected_behavior,
        "observed_status": observed_status,
        "scores": copy.deepcopy(row["scores"]),
        "matched_key_point_ids": copy.deepcopy(row["matched_key_point_ids"]),
        "follow_up_success": row["follow_up_success"],
        "safe_abstention": row["safe_abstention"],
        "critical_flags": copy.deepcopy(row["critical_flags"]),
        "confidence": row["confidence"],
        "judge_decision": row["judge_decision"],
        "rationale": row["rationale"],
        "reviewed_at": row["reviewed_at"],
    }
    _validate_judgment_decision(judgment)
    judgment["judgment_id"] = _judgment_id(judgment)
    return judgment


def _validated_decision_batch(
    paths: BlindJudgePaths,
    decision_paths: Sequence[Path],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, int],
    str,
]:
    if not decision_paths:
        raise ValueError("mini131_blind_decisions_required")
    review_config_sha256 = _review_config_sha256(paths)
    blind_by_id, packet_by_input_hash, packet_order = _source_indexes(paths)
    raw_decisions: list[dict[str, Any]] = []
    judgments: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for decision_path in decision_paths:
        rows = _load_rows(decision_path, "mini131_blind_decisions_invalid")
        for raw in rows:
            if not isinstance(raw, Mapping):
                raise ValueError("mini131_blind_decisions_invalid")
            blind_id = raw.get("blind_id")
            role = raw.get("judge_role")
            if not isinstance(blind_id, str) or not isinstance(role, str):
                raise ValueError("mini131_blind_decision_identity_invalid")
            identity = (blind_id, role)
            if identity in seen:
                raise ValueError("mini131_blind_duplicate_role_decision")
            seen.add(identity)
            raw_copy = copy.deepcopy(dict(raw))
            raw_decisions.append(raw_copy)
            judgments.append(
                _validate_blind_decision(
                    raw_copy,
                    blind_by_id=blind_by_id,
                    packet_by_input_hash=packet_by_input_hash,
                    review_config_sha256=review_config_sha256,
                )
            )

    order = sorted(
        range(len(raw_decisions)),
        key=lambda index: (
            packet_order[str(raw_decisions[index]["judge_input_sha256"])],
            ROLE_ORDER[str(raw_decisions[index]["judge_role"])],
        ),
    )
    return (
        [raw_decisions[index] for index in order],
        [judgments[index] for index in order],
        blind_by_id,
        packet_order,
        review_config_sha256,
    )


def translate_blind_decisions(
    paths: BlindJudgePaths,
    decision_paths: Sequence[Path],
    *,
    output_path: Path | None = None,
    write: bool = True,
) -> list[dict[str, Any]]:
    """Validate and translate one or more role batches without inference.

    A primary, secondary, or adjudicator batch may contain any subset of the
    blind ledger.  Multiple batches are combined only by the opaque binding;
    duplicate ``(blind_id, judge_role)`` pairs fail closed.  Workflow
    completeness remains the responsibility of ``mini131_bundle merge``.
    """

    _raw, decisions, _blind, _order, _config = _validated_decision_batch(
        paths,
        decision_paths,
    )
    if write:
        target = output_path or paths.judgments
        _protected_output(paths, target, decision_paths)
        _atomic_private_jsonl(target, decisions)
    return decisions


def slice_blind_inputs(
    paths: BlindJudgePaths,
    *,
    slice_number: int,
    slice_count: int,
    output_path: Path,
) -> list[dict[str, Any]]:
    """Write one deterministic, contiguous 1-based reviewer slice.

    Slices are exact rows from the already-blinded source artifact.  No packet
    metadata is added and no decision fields are pre-filled.
    """

    if (
        isinstance(slice_number, bool)
        or isinstance(slice_count, bool)
        or slice_count < 1
        or slice_number < 1
        or slice_number > slice_count
    ):
        raise ValueError("mini131_blind_slice_bounds_invalid")
    _blind_by_id, _packet_by_input_hash, _packet_order = _source_indexes(paths)
    blind_rows = _load_rows(paths.blind_inputs, "mini131_blind_inputs_invalid")
    start = len(blind_rows) * (slice_number - 1) // slice_count
    end = len(blind_rows) * slice_number // slice_count
    sliced = [copy.deepcopy(row) for row in blind_rows[start:end]]
    _protected_output(paths, output_path, [])
    _atomic_private_jsonl(output_path, sliced)
    return sliced


def shard_review_inputs(
    paths: BlindJudgePaths,
    *,
    input_path: Path,
    slice_number: int,
    slice_count: int,
    output_path: Path,
) -> list[dict[str, Any]]:
    """Deterministically shard a validated secondary/adjudicator input set."""

    if (
        isinstance(slice_number, bool)
        or isinstance(slice_count, bool)
        or slice_count < 1
        or slice_number < 1
        or slice_number > slice_count
    ):
        raise ValueError("mini131_blind_slice_bounds_invalid")
    rows = _load_rows(input_path, "mini131_review_inputs_invalid")
    if not rows:
        raise ValueError("mini131_review_inputs_empty")
    first_schema = rows[0].get("schema_version")
    role = (
        "adjudicator"
        if first_schema == BLIND_ADJUDICATION_INPUT_SCHEMA_VERSION
        else "secondary"
    )
    validated = _review_input_rows(paths, role, [input_path])
    if len(validated) != len(rows) or any(
        validated.get(str(row.get("blind_id"))) != row for row in rows
    ):
        raise ValueError("mini131_review_inputs_invalid")
    start = len(rows) * (slice_number - 1) // slice_count
    end = len(rows) * slice_number // slice_count
    sliced = [copy.deepcopy(row) for row in rows[start:end]]
    _protected_output(paths, output_path, [input_path])
    _atomic_private_jsonl(output_path, sliced)
    return sliced


def _protected_output(
    paths: BlindJudgePaths,
    target: Path,
    source_paths: Sequence[Path],
) -> None:
    try:
        target.resolve().relative_to(paths.blind_inputs.parent.resolve())
    except ValueError as error:
        raise ValueError("mini131_blind_output_not_private") from error
    protected = {
        paths.blind_inputs.resolve(),
        paths.judge_packets.resolve(),
        paths.rubric.resolve(),
        paths.judge_config.resolve(),
        *(path.resolve() for path in source_paths),
    }
    if target.resolve() in protected:
        raise ValueError("mini131_blind_output_path_invalid")


def seal_blind_decisions(
    paths: BlindJudgePaths,
    decision_paths: Sequence[Path],
    *,
    output_path: Path,
) -> list[dict[str, Any]]:
    """Validate and atomically seal reviewer output without adding identities."""

    raw, _judgments, _blind, _order, _config = _validated_decision_batch(
        paths,
        decision_paths,
    )
    _protected_output(paths, output_path, decision_paths)
    _atomic_private_jsonl(output_path, raw)
    return raw


def select_secondary_inputs(
    paths: BlindJudgePaths,
    primary_decision_paths: Sequence[Path],
    *,
    output_path: Path,
) -> list[dict[str, Any]]:
    """Build the exact blind subset requiring an independent secondary review."""

    raw, judgments, blind_by_id, _order, _config = _validated_decision_batch(
        paths,
        primary_decision_paths,
    )
    if any(row["judge_role"] != "primary" for row in raw):
        raise ValueError("mini131_secondary_selector_primary_only")
    primary_by_id = {row["blind_id"]: row for row in raw}
    if set(primary_by_id) != set(blind_by_id):
        raise ValueError("mini131_primary_decision_ledger_incomplete")
    judgment_by_hash = {
        row["judge_input_sha256"]: row for row in judgments
    }
    selected = [
        copy.deepcopy(blind_by_id[blind_id])
        for blind_id in sorted(blind_by_id)
        if _secondary_triggered(
            judgment_by_hash[primary_by_id[blind_id]["judge_input_sha256"]]
        )
    ]
    for row in selected:
        _assert_no_identity_fields(row)
    _protected_output(paths, output_path, primary_decision_paths)
    _atomic_private_jsonl(output_path, selected)
    return selected


def _adjudication_required(
    primary: Mapping[str, Any],
    secondary: Mapping[str, Any],
) -> bool:
    secondary_unresolved = secondary.get("judge_decision") == "needs_review"
    disagreement = bool(
        not secondary_unresolved
        and secondary.get("judge_decision") != _binary_recommendation(primary)
    )
    critical_flag_mismatch = set(secondary.get("critical_flags", [])) != set(
        primary.get("critical_flags", [])
    )
    return bool(secondary_unresolved or disagreement or critical_flag_mismatch)


def _adjudication_payload_sha256(value: Mapping[str, Any]) -> str:
    payload = {
        key: copy.deepcopy(nested)
        for key, nested in value.items()
        if key != "input_sha256"
    }
    return _content_sha256(payload)


def _validate_adjudication_input(
    paths: BlindJudgePaths,
    raw: Mapping[str, Any],
) -> dict[str, Any]:
    row = copy.deepcopy(dict(raw))
    if set(row) != ADJUDICATION_INPUT_FIELDS:
        raise ValueError("mini131_adjudication_input_fields_invalid")
    _assert_no_identity_fields(row)
    if row.get("schema_version") != BLIND_ADJUDICATION_INPUT_SCHEMA_VERSION:
        raise ValueError("mini131_adjudication_input_schema_invalid")
    if row.get("input_sha256") != _adjudication_payload_sha256(row):
        raise ValueError("mini131_adjudication_input_hash_mismatch")

    review_config_sha256 = _review_config_sha256(paths)
    if row.get("review_config_sha256") != review_config_sha256:
        raise ValueError("mini131_adjudication_review_config_mismatch")
    blind_by_id, packet_by_input_hash, _packet_order = _source_indexes(paths)
    blind_id = row.get("blind_id")
    input_hash = row.get("judge_input_sha256")
    if not isinstance(blind_id, str) or not isinstance(input_hash, str):
        raise ValueError("mini131_adjudication_binding_invalid")
    blind_input = blind_by_id.get(blind_id)
    if (
        blind_input is None
        or blind_input.get("judge_input_sha256") != input_hash
        or row.get("blind_input") != blind_input
    ):
        raise ValueError("mini131_adjudication_binding_invalid")

    validated: dict[str, dict[str, Any]] = {}
    for role, field in (
        ("primary", "primary_decision"),
        ("secondary", "secondary_decision"),
    ):
        decision = row.get(field)
        if not isinstance(decision, Mapping) or decision.get("judge_role") != role:
            raise ValueError("mini131_adjudication_prior_decision_invalid")
        if (
            decision.get("blind_id") != blind_id
            or decision.get("judge_input_sha256") != input_hash
        ):
            raise ValueError("mini131_adjudication_prior_binding_mismatch")
        validated[role] = _validate_blind_decision(
            decision,
            blind_by_id=blind_by_id,
            packet_by_input_hash=packet_by_input_hash,
            review_config_sha256=review_config_sha256,
        )
    if not _secondary_triggered(validated["primary"]):
        raise ValueError("mini131_adjudication_secondary_not_triggered")
    if not _adjudication_required(validated["primary"], validated["secondary"]):
        raise ValueError("mini131_adjudication_not_triggered")
    return row


def select_adjudication_inputs(
    paths: BlindJudgePaths,
    decision_paths: Sequence[Path],
    *,
    output_path: Path,
) -> list[dict[str, Any]]:
    """Build non-identifying adjudicator packets for unresolved cases only."""

    raw, judgments, blind_by_id, _order, review_config_sha256 = (
        _validated_decision_batch(paths, decision_paths)
    )
    if any(row["judge_role"] not in {"primary", "secondary"} for row in raw):
        raise ValueError("mini131_adjudication_selector_roles_invalid")
    raw_by_role = {
        role: {
            row["blind_id"]: row
            for row in raw
            if row["judge_role"] == role
        }
        for role in ("primary", "secondary")
    }
    judgment_by_role = {
        role: {
            row["judge_input_sha256"]: row
            for row in judgments
            if row["judge_role"] == role
        }
        for role in ("primary", "secondary")
    }
    if set(raw_by_role["primary"]) != set(blind_by_id):
        raise ValueError("mini131_primary_decision_ledger_incomplete")
    expected_secondary = {
        blind_id
        for blind_id, primary in raw_by_role["primary"].items()
        if _secondary_triggered(
            judgment_by_role["primary"][primary["judge_input_sha256"]]
        )
    }
    if set(raw_by_role["secondary"]) != expected_secondary:
        raise ValueError("mini131_secondary_decision_ledger_mismatch")

    selected: list[dict[str, Any]] = []
    for blind_id in sorted(expected_secondary):
        primary_raw = raw_by_role["primary"][blind_id]
        secondary_raw = raw_by_role["secondary"][blind_id]
        primary = judgment_by_role["primary"][
            primary_raw["judge_input_sha256"]
        ]
        secondary = judgment_by_role["secondary"][
            secondary_raw["judge_input_sha256"]
        ]
        if not _adjudication_required(primary, secondary):
            continue
        payload: dict[str, Any] = {
            "schema_version": BLIND_ADJUDICATION_INPUT_SCHEMA_VERSION,
            "blind_id": blind_id,
            "judge_input_sha256": primary_raw["judge_input_sha256"],
            "review_config_sha256": review_config_sha256,
            "blind_input": copy.deepcopy(blind_by_id[blind_id]),
            "primary_decision": copy.deepcopy(primary_raw),
            "secondary_decision": copy.deepcopy(secondary_raw),
        }
        payload["input_sha256"] = _content_sha256(payload)
        selected.append(_validate_adjudication_input(paths, payload))
    _protected_output(paths, output_path, decision_paths)
    _atomic_private_jsonl(output_path, selected)
    return selected


def _review_input_rows(
    paths: BlindJudgePaths,
    role: str,
    input_paths: Sequence[Path],
) -> dict[str, dict[str, Any]]:
    if not input_paths:
        raise ValueError("mini131_review_inputs_required")
    blind_by_id, _packet_by_hash, _order = _source_indexes(paths)
    inputs: dict[str, dict[str, Any]] = {}
    for input_path in input_paths:
        for raw in _load_rows(input_path, "mini131_review_inputs_invalid"):
            if not isinstance(raw, Mapping):
                raise ValueError("mini131_review_inputs_invalid")
            if role == "adjudicator":
                row = _validate_adjudication_input(paths, raw)
            else:
                row = copy.deepcopy(dict(raw))
                _assert_no_identity_fields(row)
                blind_id = row.get("blind_id")
                if (
                    row.get("schema_version") != BLIND_JUDGE_INPUT_SCHEMA_VERSION
                    or not isinstance(blind_id, str)
                    or blind_by_id.get(blind_id) != row
                ):
                    raise ValueError("mini131_review_blind_input_invalid")
            blind_id = str(row["blind_id"])
            if blind_id in inputs:
                raise ValueError("mini131_review_duplicate_input")
            inputs[blind_id] = row
    return inputs


def _history_sha256(value: Mapping[str, Any]) -> str:
    payload = {
        key: copy.deepcopy(nested)
        for key, nested in value.items()
        if key != "history_sha256"
    }
    return _content_sha256(payload)


def build_review_history(
    paths: BlindJudgePaths,
    *,
    role: str,
    input_paths: Sequence[Path],
    decision_paths: Sequence[Path],
    output_path: Path,
) -> list[dict[str, Any]]:
    """Persist exact reviewer-visible input/output pairs with hash binding."""

    if role not in JUDGE_ROLES:
        raise ValueError("mini131_review_role_invalid")
    inputs = _review_input_rows(paths, role, input_paths)
    raw, _judgments, _blind, _order, review_config_sha256 = (
        _validated_decision_batch(paths, decision_paths)
    )
    decisions = {
        row["blind_id"]: row for row in raw if row["judge_role"] == role
    }
    if len(decisions) != len(raw):
        raise ValueError("mini131_review_decision_role_mismatch")
    if set(inputs) != set(decisions):
        raise ValueError("mini131_review_io_ledger_mismatch")
    rubric_sha256 = sha256_file(paths.rubric)
    histories: list[dict[str, Any]] = []
    for blind_id in sorted(inputs):
        review_input = copy.deepcopy(inputs[blind_id])
        review_output = copy.deepcopy(decisions[blind_id])
        input_schema = str(review_input["schema_version"])
        row: dict[str, Any] = {
            "schema_version": BLIND_REVIEW_HISTORY_SCHEMA_VERSION,
            "blind_id": blind_id,
            "judge_input_sha256": review_output["judge_input_sha256"],
            "review_config_sha256": review_config_sha256,
            "rubric_sha256": rubric_sha256,
            "reviewer_type": REVIEWER_TYPE,
            "model": JUDGE_MODEL,
            "reasoning_effort": REASONING_EFFORT,
            "judge_role": role,
            "input_schema_version": input_schema,
            "input_sha256": _content_sha256(review_input),
            "output_schema_version": BLIND_DECISION_SCHEMA_VERSION,
            "output_sha256": _content_sha256(review_output),
            "review_input": review_input,
            "review_output": review_output,
        }
        row["history_sha256"] = _history_sha256(row)
        if set(row) != REVIEW_HISTORY_FIELDS:
            raise ValueError("mini131_review_history_fields_invalid")
        _assert_no_identity_fields(row)
        histories.append(row)
    _protected_output(
        paths,
        output_path,
        [*input_paths, *decision_paths],
    )
    _atomic_private_jsonl(output_path, histories)
    return histories


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and translate blind Mini-131 judge decisions"
    )
    parser.add_argument(
        "command",
        choices=(
            "slice",
            "shard",
            "seal",
            "select-secondary",
            "select-adjudication",
            "history",
            "validate",
            "translate",
        ),
    )
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--decisions", type=Path, action="append")
    parser.add_argument("--inputs", type=Path, action="append")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--role", choices=tuple(sorted(JUDGE_ROLES)))
    parser.add_argument("--slice-number", type=int)
    parser.add_argument("--slice-count", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = default_paths(args.repo_root)
    try:
        if args.command == "slice":
            if (
                args.decisions
                or args.inputs
                or args.role is not None
                or args.output is None
                or args.slice_number is None
                or args.slice_count is None
            ):
                raise ValueError("mini131_blind_slice_arguments_invalid")
            slice_blind_inputs(
                paths,
                slice_number=args.slice_number,
                slice_count=args.slice_count,
                output_path=args.output,
            )
            return 0
        if args.command == "shard":
            if (
                not args.inputs
                or len(args.inputs) != 1
                or args.decisions
                or args.role is not None
                or args.output is None
                or args.slice_number is None
                or args.slice_count is None
            ):
                raise ValueError("mini131_blind_shard_arguments_invalid")
            shard_review_inputs(
                paths,
                input_path=args.inputs[0],
                slice_number=args.slice_number,
                slice_count=args.slice_count,
                output_path=args.output,
            )
            return 0
        if args.command == "history":
            if (
                not args.decisions
                or not args.inputs
                or args.output is None
                or args.role is None
                or args.slice_number is not None
                or args.slice_count is not None
            ):
                raise ValueError("mini131_blind_history_arguments_invalid")
            build_review_history(
                paths,
                role=args.role,
                input_paths=args.inputs,
                decision_paths=args.decisions,
                output_path=args.output,
            )
            return 0
        if not args.decisions:
            raise ValueError("mini131_blind_decisions_required")
        if (
            args.inputs
            or args.role is not None
            or args.slice_number is not None
            or args.slice_count is not None
        ):
            raise ValueError("mini131_blind_slice_arguments_forbidden")
        if args.command in {
            "seal",
            "select-secondary",
            "select-adjudication",
        } and args.output is None:
            raise ValueError("mini131_blind_output_required")
        if args.command == "seal":
            seal_blind_decisions(
                paths,
                args.decisions,
                output_path=args.output,
            )
            return 0
        if args.command == "select-secondary":
            select_secondary_inputs(
                paths,
                args.decisions,
                output_path=args.output,
            )
            return 0
        if args.command == "select-adjudication":
            select_adjudication_inputs(
                paths,
                args.decisions,
                output_path=args.output,
            )
            return 0
        if args.command == "validate" and args.output is not None:
            raise ValueError("mini131_blind_validate_output_forbidden")
        translate_blind_decisions(
            paths,
            args.decisions,
            output_path=args.output,
            write=args.command == "translate",
        )
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        code = str(error)
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", code):
            code = "mini131_blind_judge_failed"
        print(code, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
