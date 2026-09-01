"""Blind GPT-5.6 Sol review bridge for the prospective local Mini131 run.

The local candidate runner deliberately stops at deterministic metrics.  This
module prepares a fresh, identity-free reviewer ledger and validates the fixed
Sol v2 decision workflow without performing inference itself.  Semantic output
is written beside, never over, the deterministic score so an unavailable judge
cannot invalidate already-computed metrics.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import fmean
from typing import Any

from midprojectrag.ingest.common import (
    canonical_json,
    read_jsonl,
    sha256_file,
    sha256_text,
)
from midprojectrag.eval_contracts.mini131.judge import (
    BLIND_ADJUDICATION_INPUT_SCHEMA_VERSION,
    BLIND_DECISION_FIELDS,
    BLIND_DECISION_SCHEMA_VERSION,
    BLIND_JUDGE_INPUT_SCHEMA_VERSION,
    BLIND_REVIEW_HISTORY_SCHEMA_VERSION,
    EXPECTED_BEHAVIORS,
    FORBIDDEN_BLIND_DECISION_FIELDS,
    JUDGE_MODEL,
    JUDGE_ROLES,
    JUDGE_RUBRIC,
    ROLE_DECISIONS,
    SHA256_RE,
    assert_blind as _assert_blind,
    binary_recommendation as _binary_recommendation,
    blind_id as _blind_id,
    expected_judge_config as _expected_judge_config,
    judgment_id as _judgment_id,
    judgment_semantic_score as _judgment_semantic_score,
    secondary_triggered as _secondary_triggered,
    validate_judgment_decision as _validate_judgment_decision,
    validate_judgment_scores as _validate_judgment_scores,
    valid_rfc3339 as _valid_rfc3339,
)
from midprojectrag.local_mini131_baseline import (
    DEFAULT_CONFIG,
    EXPECTED_COUNTS,
    SUITE_ID,
    SourceCase,
    VerifiedSuite,
    _expected,
    _expected_behavior,
    _load_candidates,
    _public_write_json,
    _read_json,
    _run_id,
    current_mac_index_provenance,
    validate_candidate,
    verify_suite,
)


SOURCE_INPUT_SCHEMA_VERSION = "local-mini131-blind-input.v1"
SOURCE_MAP_SCHEMA_VERSION = "local-mini131-blind-map.v1"
REVIEW_BINDING_SCHEMA_VERSION = "local-mini131-fresh-review-binding.v1"
REVIEW_MAP_SCHEMA_VERSION = "local-mini131-review-map.v1"
SEMANTIC_REPORT_SCHEMA_VERSION = "local-mini131-semantic-report.v1"
PUBLIC_SEMANTIC_RECEIPT_SCHEMA_VERSION = "local-mini131-semantic-receipt.v1"
PUBLIC_SEMANTIC_RECEIPT_FILENAME = "mac-local-equivalent-semantic-receipt.json"
FULL_JUDGMENT_SCHEMA_VERSION = "1.0"
RAG_COUNT = EXPECTED_COUNTS["rag"]
QUESTION_KINDS = {
    "core40": "rag_qa",
    "supplemental_answer_legacy": "document_qa",
    "supplemental_answer_rerun": "document_qa",
    "supplemental_set_rerun": "document_set",
    "visual": "visual_evidence_qa",
    "corpus_analytics": "corpus_analytics_qa",
}
SOURCE_ROW_FIELDS = frozenset(
    {"schema_version", "opaque_id", "judge_input", "judge_input_sha256"}
)
SOURCE_MAP_FIELDS = frozenset(
    {
        "schema_version",
        "opaque_id",
        "case_id",
        "lane",
        "candidate_sha256",
        "judge_input_sha256",
    }
)
REVIEW_MAP_FIELDS = frozenset(
    {
        "schema_version",
        "blind_id",
        "case_id",
        "lane",
        "candidate_sha256",
        "source_opaque_id",
        "source_judge_input_sha256",
        "judge_input_sha256",
        "fresh_review_binding_sha256",
    }
)
IDENTITY_KEYS = frozenset({"case_id", "lane", "lineage"})
ROLE_ORDER = {"primary": 0, "secondary": 1, "adjudicator": 2}


@dataclass(frozen=True)
class SemanticPaths:
    source_inputs: Path
    source_map: Path
    candidates: Path
    deterministic_score: Path
    rubric: Path
    judge_config: Path
    adapter_config: Path
    review_root: Path
    review_inputs: Path
    review_map: Path
    semantic_score: Path


@dataclass(frozen=True)
class SemanticLedger:
    suite: VerifiedSuite
    paths: SemanticPaths
    review_config_sha256: str
    inherited_judge_config_sha256: str
    rubric_sha256: str
    run_id: str
    review_rows: tuple[dict[str, Any], ...]
    review_by_id: dict[str, dict[str, Any]]
    map_by_id: dict[str, dict[str, Any]]
    candidate_by_case: dict[str, dict[str, Any]]
    deterministic_score_sha256: str


def default_paths(suite: VerifiedSuite) -> SemanticPaths:
    review_root = suite.private_judge_input_path.parent / "semantic-review-v2"
    return SemanticPaths(
        source_inputs=suite.private_judge_input_path,
        source_map=suite.private_judge_input_path.with_name("blind-map.jsonl"),
        candidates=suite.candidate_path,
        deterministic_score=suite.private_score_path,
        rubric=suite.repo_root / "evaluation/rubric.md",
        judge_config=suite.repo_root
        / "evaluation/contracts/mini131/judge-config.json",
        adapter_config=suite.repo_root
        / f"evaluation/baselines/{SUITE_ID}/semantic-review-adapter.json",
        review_root=review_root,
        review_inputs=review_root / "primary-inputs.jsonl",
        review_map=review_root / "review-map.jsonl",
        semantic_score=suite.candidate_path.with_name("semantic-score.json"),
    )


def _secure_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            for row in rows:
                output.write(canonical_json(dict(row)) + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _secure_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _public_semantic_receipt_path(paths: SemanticPaths) -> Path:
    return paths.adapter_config.parent / PUBLIC_SEMANTIC_RECEIPT_FILENAME


def _public_semantic_receipt(
    report: Mapping[str, Any],
    semantic_score_path: Path,
) -> dict[str, Any]:
    """Project the private semantic report into an aggregate-only receipt."""

    judge = report["judge"]
    receipt = {
        "schema_version": PUBLIC_SEMANTIC_RECEIPT_SCHEMA_VERSION,
        "suite_id": SUITE_ID,
        "official": False,
        "evaluation_tier": "provisional_non_official",
        "gold_review_status": "draft",
        "semantic_judgment": report["semantic_judgment"],
        "counts": copy.deepcopy(report["counts"]),
        "metrics": copy.deepcopy(report["metrics"]),
        "judge": {
            "model": judge["model"],
            "reasoning_effort": "high",
            "rubric_version": judge["rubric_version"],
            "rubric_sha256": judge["rubric_sha256"],
            "inherited_judge_config_sha256": judge[
                "inherited_judge_config_sha256"
            ],
            "review_config_sha256": judge["review_config_sha256"],
        },
        "hashes": {
            "suite_config_sha256": report["suite_config_sha256"],
            "eval_set_sha256": report["eval_set_sha256"],
            "deterministic_score_sha256": report["deterministic_score_sha256"],
            "review_inputs_sha256": report["review_inputs_sha256"],
            "review_map_sha256": report["review_map_sha256"],
            "review_history_sha256": report["review_history_sha256"],
            "decisions_sha256": report["decisions_sha256"],
            "private_semantic_score_sha256": sha256_file(semantic_score_path),
        },
        "privacy": {
            "private": False,
            "contains_case_ids": False,
            "contains_questions": False,
            "contains_answers": False,
            "contains_source_text": False,
            "contains_judge_rationales": False,
            "contains_blind_ids": False,
            "contains_private_paths": False,
        },
    }
    return receipt


def _private_regular_file(path: Path, code: str) -> None:
    if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError(code)


def _within_review_root(paths: SemanticPaths, path: Path) -> None:
    try:
        path.resolve().relative_to(paths.review_root.resolve())
    except ValueError as error:
        raise ValueError("local_mini131_semantic_output_not_private") from error
    protected = {
        paths.source_inputs.resolve(),
        paths.source_map.resolve(),
        paths.candidates.resolve(),
        paths.deterministic_score.resolve(),
        paths.rubric.resolve(),
        paths.judge_config.resolve(),
        paths.adapter_config.resolve(),
        paths.review_inputs.resolve(),
        paths.review_map.resolve(),
    }
    if path.resolve() in protected:
        raise ValueError("local_mini131_semantic_output_protected")


def _fixed_judge_hashes(paths: SemanticPaths) -> tuple[str, str, str]:
    rubric_sha256 = sha256_file(paths.rubric)
    config = _read_json(paths.judge_config, "local_mini131_judge_config_invalid")
    if config != _expected_judge_config(rubric_sha256):
        raise ValueError("local_mini131_judge_config_mismatch")
    inherited_hash = sha256_file(paths.judge_config)
    adapter = _read_json(
        paths.adapter_config,
        "local_mini131_semantic_adapter_invalid",
    )
    expected_adapter = {
        "schema_version": "local-mini131-semantic-adapter.v1",
        "adapter_id": "gcp-local-kure-qwen3-8b-awq-mini131-sol-v2",
        "suite_id": SUITE_ID,
        "inherits": {
            "judge_config": "evaluation/contracts/mini131/judge-config.json",
            "judge_config_sha256": inherited_hash,
            "rubric": "evaluation/rubric.md",
            "rubric_sha256": rubric_sha256,
            "model": JUDGE_MODEL,
            "reasoning_effort": "high",
            "semantic_policy_overrides": [],
        },
        "review_io": {
            "primary_source": f"evaluation/private/local-mini131/{SUITE_ID}/semantic-review-v2/primary-inputs.jsonl",
            "private_identity_map": f"evaluation/private/local-mini131/{SUITE_ID}/semantic-review-v2/review-map.jsonl",
            "identity_map_visible_to_reviewer": False,
            "candidate_output_visible_to_reviewer": False,
            "past_judgments_reusable": False,
            "fresh_binding": "sha256(candidate_sha256, source_judge_input_sha256, suite_config_sha256, rubric_sha256, semantic_adapter_sha256)",
            "decision_schema_version": BLIND_DECISION_SCHEMA_VERSION,
            "review_history_schema_version": BLIND_REVIEW_HISTORY_SCHEMA_VERSION,
        },
        "merge": {
            "deterministic_score_policy": "read_only_preserve",
            "semantic_output": "resources/data_refined/private/outputs/local/gcp-local-kure-qwen3-8b-awq-mini131-v1/mac-local-equivalent/semantic-score.json",
            "requires_complete_primary_ledger": True,
            "requires_triggered_secondary_and_adjudicator_resolution": True,
        },
    }
    if adapter != expected_adapter:
        raise ValueError("local_mini131_semantic_adapter_mismatch")
    return rubric_sha256, inherited_hash, sha256_file(paths.adapter_config)


def _source_judge_input(
    suite: VerifiedSuite,
    candidate: Mapping[str, Any],
    source_case: SourceCase,
) -> dict[str, Any]:
    response = candidate["response"]
    evidence = (
        [copy.deepcopy(candidate["companion"])]
        if source_case.lane == "corpus_analytics"
        else copy.deepcopy(candidate["generation"]["prompts"])
    )
    return {
        "question_kind": QUESTION_KINDS[source_case.lane],
        "question": source_case.source["question"],
        "expected": _expected(source_case),
        "candidate": {
            "status": response["status"],
            "answer": response["answer"],
            "chat": [
                {"role": "user", "content": source_case.source["question"]},
                {"role": "assistant", "content": response["answer"]},
            ],
        },
        "retrieval": {
            "retrieved_docs": copy.deepcopy(candidate["retrieval"]),
            "cited_docs": copy.deepcopy(response["citations"]),
            "evidence": evidence,
        },
    }


def _replace_case_identity(value: Any, case_id: str) -> Any:
    """Hide case IDs embedded in locator strings without changing semantics."""

    if isinstance(value, Mapping):
        for key in value:
            if str(key).lower() in IDENTITY_KEYS:
                raise ValueError("local_mini131_semantic_identity_key_leak")
        return {
            str(key): _replace_case_identity(nested, case_id)
            for key, nested in value.items()
        }
    if isinstance(value, list):
        return [_replace_case_identity(nested, case_id) for nested in value]
    if isinstance(value, str):
        return value.replace(case_id, "opaque-case")
    return copy.deepcopy(value)


def _assert_no_identity_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).lower() in IDENTITY_KEYS:
                raise ValueError("local_mini131_semantic_identity_key_leak")
            _assert_no_identity_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_identity_keys(nested)


def _fresh_review_projection(
    judge_input: Mapping[str, Any],
    *,
    case_id: str,
    candidate_sha256: str,
    source_judge_input_sha256: str,
    suite_config_sha256: str,
    rubric_sha256: str,
    review_config_sha256: str,
) -> tuple[dict[str, Any], str]:
    binding_payload = {
        "schema_version": REVIEW_BINDING_SCHEMA_VERSION,
        "candidate_sha256": candidate_sha256,
        "source_judge_input_sha256": source_judge_input_sha256,
        "suite_config_sha256": suite_config_sha256,
        "rubric_sha256": rubric_sha256,
        "review_config_sha256": review_config_sha256,
    }
    binding_sha256 = sha256_text(canonical_json(binding_payload))
    projected = _replace_case_identity(judge_input, case_id)
    projected["evaluation_context"] = {
        "schema_version": REVIEW_BINDING_SCHEMA_VERSION,
        "fresh_review_binding_sha256": binding_sha256,
    }
    _assert_blind(projected)
    return projected, binding_sha256


def _candidate_identity_tokens(suite: VerifiedSuite, run_id: str) -> set[str]:
    generation = suite.stack.config.get("generation", {})
    embedding = suite.stack.config.get("embedding", {})
    values = {
        SUITE_ID,
        run_id,
        str(generation.get("mac_equivalent_model", "")),
        str(generation.get("gcp_model", "")),
        str(embedding.get("model", "")),
    }
    return {value.lower() for value in values if len(value) >= 6}


def _assert_no_candidate_identity(
    value: Mapping[str, Any], suite: VerifiedSuite, run_id: str
) -> None:
    serialized = canonical_json(value).lower()
    if any(token in serialized for token in _candidate_identity_tokens(suite, run_id)):
        raise ValueError("local_mini131_semantic_candidate_identity_leak")


def _validated_deterministic_score(suite: VerifiedSuite, paths: SemanticPaths) -> str:
    _private_regular_file(
        paths.deterministic_score,
        "local_mini131_deterministic_score_not_private",
    )
    score = _read_json(
        paths.deterministic_score,
        "local_mini131_deterministic_score_invalid",
    )
    counts = score.get("counts")
    blind = score.get("blind_judge_inputs")
    if (
        score.get("suite_id") != SUITE_ID
        or score.get("suite_config_sha256") != suite.config_sha256
        or score.get("eval_set_sha256") != suite.eval_set_sha256
        or score.get("suite_complete") is not True
        or score.get("semantic_judgment") != "not_run"
        or not isinstance(counts, Mapping)
        or counts.get("rag_scored") != RAG_COUNT
        or counts.get("parser_passed") != EXPECTED_COUNTS["parser"]
        or not isinstance(blind, Mapping)
        or blind.get("count") != RAG_COUNT
        or blind.get("blind_inputs_sha256") != sha256_file(paths.source_inputs)
        or blind.get("blind_map_sha256") != sha256_file(paths.source_map)
    ):
        raise ValueError("local_mini131_deterministic_score_invalid")
    return sha256_file(paths.deterministic_score)


def load_ledger(suite: VerifiedSuite) -> SemanticLedger:
    paths = default_paths(suite)
    rubric_sha256, inherited_judge_config_sha256, review_config_sha256 = (
        _fixed_judge_hashes(paths)
    )
    for path, code in (
        (paths.source_inputs, "local_mini131_source_inputs_not_private"),
        (paths.source_map, "local_mini131_source_map_not_private"),
        (paths.candidates, "local_mini131_candidates_not_private"),
    ):
        _private_regular_file(path, code)
    deterministic_score_sha256 = _validated_deterministic_score(suite, paths)

    index_provenance = current_mac_index_provenance(suite.stack)
    run_id = _run_id(suite, index_provenance)
    candidates = _load_candidates(paths.candidates)
    if len(candidates) != RAG_COUNT:
        raise ValueError("local_mini131_semantic_candidate_count_mismatch")
    candidate_by_case: dict[str, dict[str, Any]] = {}
    for raw in candidates:
        candidate = validate_candidate(
            raw,
            suite=suite,
            run_id=run_id,
            index_provenance=index_provenance,
        )
        case_id = str(candidate["case_id"])
        if case_id in candidate_by_case:
            raise ValueError("local_mini131_semantic_duplicate_candidate")
        candidate_by_case[case_id] = candidate
    if set(candidate_by_case) != set(suite.cases_by_id):
        raise ValueError("local_mini131_semantic_candidate_ledger_mismatch")

    source_rows = read_jsonl(paths.source_inputs)
    source_maps = read_jsonl(paths.source_map)
    if len(source_rows) != RAG_COUNT or len(source_maps) != RAG_COUNT:
        raise ValueError("local_mini131_semantic_source_count_mismatch")
    source_by_opaque: dict[str, dict[str, Any]] = {}
    for row in source_rows:
        if set(row) != SOURCE_ROW_FIELDS or row.get("schema_version") != SOURCE_INPUT_SCHEMA_VERSION:
            raise ValueError("local_mini131_semantic_source_input_invalid")
        opaque_id = row.get("opaque_id")
        judge_input = row.get("judge_input")
        input_hash = row.get("judge_input_sha256")
        if (
            not isinstance(opaque_id, str)
            or not re.fullmatch(r"judge-[0-9a-f]{24}", opaque_id)
            or not isinstance(judge_input, Mapping)
            or not isinstance(input_hash, str)
            or not SHA256_RE.fullmatch(input_hash)
            or input_hash != sha256_text(canonical_json(judge_input))
            or opaque_id != f"judge-{input_hash[:24]}"
            or opaque_id in source_by_opaque
        ):
            raise ValueError("local_mini131_semantic_source_input_invalid")
        _assert_blind(judge_input)
        source_by_opaque[opaque_id] = copy.deepcopy(row)

    map_by_opaque: dict[str, dict[str, Any]] = {}
    for row in source_maps:
        if set(row) != SOURCE_MAP_FIELDS or row.get("schema_version") != SOURCE_MAP_SCHEMA_VERSION:
            raise ValueError("local_mini131_semantic_source_map_invalid")
        opaque_id = row.get("opaque_id")
        case_id = row.get("case_id")
        if (
            not isinstance(opaque_id, str)
            or opaque_id in map_by_opaque
            or opaque_id not in source_by_opaque
            or not isinstance(case_id, str)
            or case_id not in candidate_by_case
        ):
            raise ValueError("local_mini131_semantic_source_map_invalid")
        candidate = candidate_by_case[case_id]
        source_case = suite.cases_by_id[case_id]
        source_row = source_by_opaque[opaque_id]
        expected_judge_input = _source_judge_input(suite, candidate, source_case)
        candidate_sha256 = sha256_text(canonical_json(candidate))
        if (
            row.get("lane") != source_case.lane
            or row.get("candidate_sha256") != candidate_sha256
            or row.get("judge_input_sha256") != source_row["judge_input_sha256"]
            or source_row["judge_input"] != expected_judge_input
        ):
            raise ValueError("local_mini131_semantic_source_binding_mismatch")
        map_by_opaque[opaque_id] = copy.deepcopy(row)
    if set(map_by_opaque) != set(source_by_opaque):
        raise ValueError("local_mini131_semantic_source_ledger_mismatch")

    review_rows: list[dict[str, Any]] = []
    review_maps: list[dict[str, Any]] = []
    for opaque_id in sorted(source_by_opaque):
        source_row = source_by_opaque[opaque_id]
        source_map = map_by_opaque[opaque_id]
        case_id = str(source_map["case_id"])
        judge_input, binding_hash = _fresh_review_projection(
            source_row["judge_input"],
            case_id=case_id,
            candidate_sha256=str(source_map["candidate_sha256"]),
            source_judge_input_sha256=str(source_row["judge_input_sha256"]),
            suite_config_sha256=suite.config_sha256,
            rubric_sha256=rubric_sha256,
            review_config_sha256=review_config_sha256,
        )
        _assert_no_candidate_identity(judge_input, suite, run_id)
        judge_hash = sha256_text(canonical_json(judge_input))
        blind_id = _blind_id(judge_hash)
        review_rows.append(
            {
                "schema_version": BLIND_JUDGE_INPUT_SCHEMA_VERSION,
                "blind_id": blind_id,
                "judge_input_sha256": judge_hash,
                "judge_input": judge_input,
            }
        )
        review_maps.append(
            {
                "schema_version": REVIEW_MAP_SCHEMA_VERSION,
                "blind_id": blind_id,
                "case_id": case_id,
                "lane": source_map["lane"],
                "candidate_sha256": source_map["candidate_sha256"],
                "source_opaque_id": opaque_id,
                "source_judge_input_sha256": source_row["judge_input_sha256"],
                "judge_input_sha256": judge_hash,
                "fresh_review_binding_sha256": binding_hash,
            }
        )
    review_rows.sort(key=lambda row: row["blind_id"])
    review_maps.sort(key=lambda row: row["blind_id"])
    if len({row["blind_id"] for row in review_rows}) != RAG_COUNT:
        raise ValueError("local_mini131_semantic_duplicate_blind_id")
    if any(set(row) != REVIEW_MAP_FIELDS for row in review_maps):
        raise ValueError("local_mini131_semantic_review_map_invalid")

    _secure_jsonl(paths.review_inputs, review_rows)
    _secure_jsonl(paths.review_map, review_maps)
    review_by_id = {str(row["blind_id"]): row for row in review_rows}
    map_by_id = {str(row["blind_id"]): row for row in review_maps}
    return SemanticLedger(
        suite=suite,
        paths=paths,
        review_config_sha256=review_config_sha256,
        inherited_judge_config_sha256=inherited_judge_config_sha256,
        rubric_sha256=rubric_sha256,
        run_id=run_id,
        review_rows=tuple(review_rows),
        review_by_id=review_by_id,
        map_by_id=map_by_id,
        candidate_by_case=candidate_by_case,
        deterministic_score_sha256=deterministic_score_sha256,
    )


def _validate_string_list(value: Any, code: str) -> list[str]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item for item in value)
        or len(value) != len(set(value))
    ):
        raise ValueError(code)
    return list(value)


def _point_ids(review_row: Mapping[str, Any]) -> set[str]:
    result: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            point_id = value.get("point_id")
            if isinstance(point_id, str) and point_id:
                result.add(point_id)
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(review_row["judge_input"].get("expected"))
    return result


def _validate_decision(
    ledger: SemanticLedger,
    raw: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    decision = copy.deepcopy(dict(raw))
    if set(decision) != BLIND_DECISION_FIELDS:
        raise ValueError("local_mini131_semantic_decision_fields_invalid")
    if set(decision) & FORBIDDEN_BLIND_DECISION_FIELDS:
        raise ValueError("local_mini131_semantic_decision_identity_leak")
    if decision.get("schema_version") != BLIND_DECISION_SCHEMA_VERSION:
        raise ValueError("local_mini131_semantic_decision_schema_invalid")
    blind_id = decision.get("blind_id")
    review_row = ledger.review_by_id.get(str(blind_id))
    mapping = ledger.map_by_id.get(str(blind_id))
    if (
        review_row is None
        or mapping is None
        or decision.get("judge_input_sha256") != review_row["judge_input_sha256"]
        or decision.get("review_config_sha256") != ledger.review_config_sha256
    ):
        raise ValueError("local_mini131_semantic_decision_binding_mismatch")
    if (
        decision.get("rubric_version") != JUDGE_RUBRIC
        or decision.get("reviewer_type") != "llm"
        or decision.get("model") != JUDGE_MODEL
    ):
        raise ValueError("local_mini131_semantic_fixed_judge_mismatch")
    role = decision.get("judge_role")
    if role not in JUDGE_ROLES or decision.get("judge_decision") not in ROLE_DECISIONS[str(role)]:
        raise ValueError("local_mini131_semantic_decision_role_invalid")

    source_case = ledger.suite.cases_by_id[str(mapping["case_id"])]
    expected_behavior = _expected_behavior(source_case)
    if expected_behavior not in EXPECTED_BEHAVIORS:
        raise ValueError("local_mini131_semantic_expected_behavior_invalid")
    _validate_judgment_scores(decision.get("scores"), expected_behavior=expected_behavior)
    matched = _validate_string_list(
        decision.get("matched_key_point_ids"),
        "local_mini131_semantic_matched_points_invalid",
    )
    if not set(matched) <= _point_ids(review_row):
        raise ValueError("local_mini131_semantic_matched_points_unknown")
    _validate_string_list(
        decision.get("critical_flags"),
        "local_mini131_semantic_critical_flags_invalid",
    )
    for field in ("follow_up_success", "safe_abstention"):
        value = decision.get(field)
        if value is not None and not isinstance(value, bool):
            raise ValueError(f"local_mini131_semantic_{field}_invalid")
    follow_up = source_case.source.get("task_type") == "follow_up"
    if follow_up != isinstance(decision.get("follow_up_success"), bool):
        raise ValueError("local_mini131_semantic_follow_up_scope_invalid")
    confidence = decision.get("confidence")
    if (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not 0 <= float(confidence) <= 1
        or not isinstance(decision.get("rationale"), str)
        or not decision["rationale"].strip()
        or not _valid_rfc3339(decision.get("reviewed_at"))
    ):
        raise ValueError("local_mini131_semantic_decision_metadata_invalid")

    candidate = ledger.candidate_by_case[source_case.case_id]
    observed_status = candidate["response"]["status"]
    judgment: dict[str, Any] = {
        "schema_version": FULL_JUDGMENT_SCHEMA_VERSION,
        "judgment_id": "pending",
        "case_id": source_case.case_id,
        "case_sha256": source_case.source_sha256,
        "run_record_sha256": mapping["candidate_sha256"],
        "judge_input_sha256": review_row["judge_input_sha256"],
        "review_config_sha256": ledger.review_config_sha256,
        "rubric_version": JUDGE_RUBRIC,
        "reviewer_type": "llm",
        "model": JUDGE_MODEL,
        "judge_role": role,
        "expected_behavior": expected_behavior,
        "observed_status": observed_status,
        "scores": copy.deepcopy(decision["scores"]),
        "matched_key_point_ids": matched,
        "follow_up_success": decision["follow_up_success"],
        "safe_abstention": decision["safe_abstention"],
        "critical_flags": copy.deepcopy(decision["critical_flags"]),
        "confidence": confidence,
        "judge_decision": decision["judge_decision"],
        "rationale": decision["rationale"],
        "reviewed_at": decision["reviewed_at"],
    }
    _validate_judgment_decision(judgment)
    judgment["judgment_id"] = _judgment_id(judgment)
    return decision, judgment


def validate_decisions(
    ledger: SemanticLedger,
    decision_paths: Sequence[Path],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not decision_paths:
        raise ValueError("local_mini131_semantic_decisions_required")
    raw_rows: list[dict[str, Any]] = []
    judgments: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for path in decision_paths:
        _within_review_root(ledger.paths, path)
        _private_regular_file(
            path,
            "local_mini131_semantic_decisions_not_private",
        )
        for raw in read_jsonl(path):
            identity = (str(raw.get("blind_id")), str(raw.get("judge_role")))
            if identity in seen:
                raise ValueError("local_mini131_semantic_duplicate_role_decision")
            seen.add(identity)
            decision, judgment = _validate_decision(ledger, raw)
            raw_rows.append(decision)
            judgments.append(judgment)
    order = sorted(
        range(len(raw_rows)),
        key=lambda index: (
            str(raw_rows[index]["blind_id"]),
            ROLE_ORDER[str(raw_rows[index]["judge_role"])],
        ),
    )
    return (
        [raw_rows[index] for index in order],
        [judgments[index] for index in order],
    )


def slice_primary_inputs(
    ledger: SemanticLedger,
    *,
    slice_number: int,
    slice_count: int,
    output_path: Path,
) -> list[dict[str, Any]]:
    if slice_count < 1 or slice_number < 1 or slice_number > slice_count:
        raise ValueError("local_mini131_semantic_slice_invalid")
    _within_review_root(ledger.paths, output_path)
    start = len(ledger.review_rows) * (slice_number - 1) // slice_count
    end = len(ledger.review_rows) * slice_number // slice_count
    rows = [copy.deepcopy(row) for row in ledger.review_rows[start:end]]
    _secure_jsonl(output_path, rows)
    return rows


def select_secondary_inputs(
    ledger: SemanticLedger,
    decision_paths: Sequence[Path],
    *,
    output_path: Path,
) -> list[dict[str, Any]]:
    raw, judgments = validate_decisions(ledger, decision_paths)
    if len(raw) != RAG_COUNT or any(row["judge_role"] != "primary" for row in raw):
        raise ValueError("local_mini131_semantic_primary_ledger_incomplete")
    by_hash = {row["judge_input_sha256"]: row for row in judgments}
    rows = [
        copy.deepcopy(ledger.review_by_id[str(row["blind_id"])])
        for row in raw
        if _secondary_triggered(by_hash[str(row["judge_input_sha256"])])
    ]
    _within_review_root(ledger.paths, output_path)
    _secure_jsonl(output_path, rows)
    return rows


def _adjudication_required(
    primary: Mapping[str, Any], secondary: Mapping[str, Any]
) -> bool:
    unresolved = secondary.get("judge_decision") == "needs_review"
    disagreement = not unresolved and secondary.get("judge_decision") != _binary_recommendation(primary)
    flags_differ = set(primary.get("critical_flags", [])) != set(secondary.get("critical_flags", []))
    return bool(unresolved or disagreement or flags_differ)


def _adjudication_packet(
    ledger: SemanticLedger,
    blind_id: str,
    primary_raw: Mapping[str, Any],
    secondary_raw: Mapping[str, Any],
) -> dict[str, Any]:
    packet: dict[str, Any] = {
        "schema_version": BLIND_ADJUDICATION_INPUT_SCHEMA_VERSION,
        "blind_id": blind_id,
        "judge_input_sha256": primary_raw["judge_input_sha256"],
        "review_config_sha256": ledger.review_config_sha256,
        "blind_input": copy.deepcopy(ledger.review_by_id[blind_id]),
        "primary_decision": copy.deepcopy(dict(primary_raw)),
        "secondary_decision": copy.deepcopy(dict(secondary_raw)),
    }
    packet["input_sha256"] = sha256_text(canonical_json(packet))
    _assert_no_identity_keys(packet)
    return packet


def select_adjudication_inputs(
    ledger: SemanticLedger,
    decision_paths: Sequence[Path],
    *,
    output_path: Path,
) -> list[dict[str, Any]]:
    raw, judgments = validate_decisions(ledger, decision_paths)
    if any(row["judge_role"] not in {"primary", "secondary"} for row in raw):
        raise ValueError("local_mini131_semantic_adjudication_roles_invalid")
    raw_by_role = {
        role: {row["blind_id"]: row for row in raw if row["judge_role"] == role}
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
    if set(raw_by_role["primary"]) != set(ledger.review_by_id):
        raise ValueError("local_mini131_semantic_primary_ledger_incomplete")
    expected_secondary = {
        blind_id
        for blind_id, row in raw_by_role["primary"].items()
        if _secondary_triggered(judgment_by_role["primary"][row["judge_input_sha256"]])
    }
    if set(raw_by_role["secondary"]) != expected_secondary:
        raise ValueError("local_mini131_semantic_secondary_ledger_mismatch")
    result: list[dict[str, Any]] = []
    for blind_id in sorted(expected_secondary):
        primary_raw = raw_by_role["primary"][blind_id]
        secondary_raw = raw_by_role["secondary"][blind_id]
        primary = judgment_by_role["primary"][primary_raw["judge_input_sha256"]]
        secondary = judgment_by_role["secondary"][secondary_raw["judge_input_sha256"]]
        if not _adjudication_required(primary, secondary):
            continue
        result.append(
            _adjudication_packet(
                ledger,
                blind_id,
                primary_raw,
                secondary_raw,
            )
        )
    _within_review_root(ledger.paths, output_path)
    _secure_jsonl(output_path, result)
    return result


def merge_semantic_score(
    ledger: SemanticLedger,
    decision_paths: Sequence[Path],
    *,
    output_path: Path | None = None,
) -> dict[str, Any]:
    deterministic_before = sha256_file(ledger.paths.deterministic_score)
    if deterministic_before != ledger.deterministic_score_sha256:
        raise ValueError("local_mini131_deterministic_score_changed")
    raw, judgments = validate_decisions(ledger, decision_paths)
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for judgment in judgments:
        grouped.setdefault(str(judgment["case_id"]), {})[str(judgment["judge_role"])] = judgment
    if set(grouped) != set(ledger.candidate_by_case):
        raise ValueError("local_mini131_semantic_judgment_ledger_incomplete")

    finals: dict[str, dict[str, Any]] = {}
    workflow: dict[str, dict[str, Any]] = {}
    for case_id in sorted(grouped):
        by_role = grouped[case_id]
        primary = by_role.get("primary")
        if primary is None:
            raise ValueError("local_mini131_semantic_primary_missing")
        secondary = by_role.get("secondary")
        adjudicator = by_role.get("adjudicator")
        secondary_required = _secondary_triggered(primary)
        if secondary_required != (secondary is not None):
            raise ValueError("local_mini131_semantic_secondary_workflow_invalid")
        adjudicator_required = bool(
            secondary is not None and _adjudication_required(primary, secondary)
        )
        if adjudicator_required != (adjudicator is not None):
            raise ValueError("local_mini131_semantic_adjudication_workflow_invalid")
        history = [by_role[role] for role in ROLE_ORDER if role in by_role]
        reviewed = [
            datetime.fromisoformat(str(row["reviewed_at"]).replace("Z", "+00:00"))
            for row in history
        ]
        if reviewed != sorted(reviewed):
            raise ValueError("local_mini131_semantic_review_order_invalid")
        final = adjudicator or secondary or primary
        if final["judge_decision"] not in {"accepted", "rejected"}:
            raise ValueError("local_mini131_semantic_final_unresolved")
        finals[case_id] = final
        workflow[case_id] = {
            "secondary_required": secondary_required,
            "adjudicator_required": adjudicator_required,
            "final_judgment_id": final["judgment_id"],
        }

    raw_by_identity = {
        (str(row["blind_id"]), str(row["judge_role"])): row for row in raw
    }
    history_rows: list[dict[str, Any]] = []
    for case_id in sorted(grouped):
        mapping = next(
            value for value in ledger.map_by_id.values() if value["case_id"] == case_id
        )
        blind_id = str(mapping["blind_id"])
        by_role = grouped[case_id]
        for role in ROLE_ORDER:
            if role not in by_role:
                continue
            review_output = copy.deepcopy(raw_by_identity[(blind_id, role)])
            if role == "adjudicator":
                review_input = _adjudication_packet(
                    ledger,
                    blind_id,
                    raw_by_identity[(blind_id, "primary")],
                    raw_by_identity[(blind_id, "secondary")],
                )
            else:
                review_input = copy.deepcopy(ledger.review_by_id[blind_id])
            history: dict[str, Any] = {
                "schema_version": BLIND_REVIEW_HISTORY_SCHEMA_VERSION,
                "blind_id": blind_id,
                "judge_input_sha256": review_output["judge_input_sha256"],
                "review_config_sha256": ledger.review_config_sha256,
                "rubric_sha256": ledger.rubric_sha256,
                "reviewer_type": "llm",
                "model": JUDGE_MODEL,
                "reasoning_effort": "high",
                "judge_role": role,
                "input_schema_version": review_input["schema_version"],
                "input_sha256": sha256_text(canonical_json(review_input)),
                "output_schema_version": BLIND_DECISION_SCHEMA_VERSION,
                "output_sha256": sha256_text(canonical_json(review_output)),
                "review_input": review_input,
                "review_output": review_output,
            }
            history["history_sha256"] = sha256_text(canonical_json(history))
            _assert_no_identity_keys(history)
            history_rows.append(history)
    history_path = ledger.paths.review_root / "review-history.jsonl"
    _secure_jsonl(history_path, history_rows)

    scores = [_judgment_semantic_score(row) for row in finals.values()]
    accepted = sum(row["judge_decision"] == "accepted" for row in finals.values())
    lane_counts: dict[str, Counter[str]] = {
        lane: Counter() for lane in EXPECTED_COUNTS["lanes"]
    }
    cases: list[dict[str, Any]] = []
    for case_id in sorted(finals):
        final = finals[case_id]
        lane = ledger.suite.cases_by_id[case_id].lane
        lane_counts[lane][str(final["judge_decision"])] += 1
        cases.append(
            {
                "case_id": case_id,
                "lane": lane,
                "semantic_score": _judgment_semantic_score(final),
                "final_decision": final["judge_decision"],
                "final_judge_role": final["judge_role"],
                "final_judgment_id": final["judgment_id"],
                "workflow": workflow[case_id],
            }
        )
    report = {
        "schema_version": SEMANTIC_REPORT_SCHEMA_VERSION,
        "suite_id": SUITE_ID,
        "official": False,
        "evaluation_tier": "provisional_non_official",
        "gold_review_status": "draft",
        "semantic_judgment": "complete",
        "judge": {
            "model": JUDGE_MODEL,
            "rubric_version": JUDGE_RUBRIC,
            "rubric_sha256": ledger.rubric_sha256,
            "inherited_judge_config_sha256": ledger.inherited_judge_config_sha256,
            "review_config_sha256": ledger.review_config_sha256,
        },
        "run_id": ledger.run_id,
        "suite_config_sha256": ledger.suite.config_sha256,
        "eval_set_sha256": ledger.suite.eval_set_sha256,
        "deterministic_score_sha256": ledger.deterministic_score_sha256,
        "review_inputs_sha256": sha256_file(ledger.paths.review_inputs),
        "review_map_sha256": sha256_file(ledger.paths.review_map),
        "review_history_sha256": sha256_file(history_path),
        "decisions_sha256": sha256_text(canonical_json(raw)),
        "counts": {
            "rag_total": RAG_COUNT,
            "accepted": accepted,
            "rejected": RAG_COUNT - accepted,
            "judge_roles": dict(sorted(Counter(row["judge_role"] for row in judgments).items())),
            "lanes": {
                lane: dict(sorted(counts.items()))
                for lane, counts in lane_counts.items()
            },
        },
        "metrics": {
            "mean_semantic_score": round(fmean(scores), 6),
            "acceptance_rate": round(accepted / RAG_COUNT, 6),
        },
        "cases": cases,
        "privacy": {
            "private": True,
            "contains_case_ids": True,
            "contains_judge_rationales": False,
            "past_judgments_reusable": False,
        },
    }
    target = output_path or ledger.paths.semantic_score
    if target.resolve() != ledger.paths.semantic_score.resolve():
        _within_review_root(ledger.paths, target)
    _secure_json(target, report)
    if sha256_file(ledger.paths.deterministic_score) != deterministic_before:
        raise ValueError("local_mini131_deterministic_score_changed")
    if target.resolve() == ledger.paths.semantic_score.resolve():
        public_receipt = _public_semantic_receipt(report, target)
        _public_write_json(
            _public_semantic_receipt_path(ledger.paths),
            public_receipt,
        )
    return report


def _merge_cli_result(report: Mapping[str, Any], output_path: Path) -> dict[str, Any]:
    return {
        "passed": True,
        "semantic_judgment": report["semantic_judgment"],
        "counts": copy.deepcopy(report["counts"]),
        "metrics": copy.deepcopy(report["metrics"]),
        "semantic_score_sha256": sha256_file(output_path),
    }


def _safe_error(error: BaseException) -> str:
    message = str(error)
    if re.fullmatch(r"[a-z][a-z0-9_]{0,127}", message or ""):
        return message
    return "local_mini131_semantic_failed"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Blind Sol review for local Mini131")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--slice-count", type=int, default=1)
    validate = commands.add_parser("validate")
    validate.add_argument("--decisions", type=Path, action="append", required=True)
    secondary = commands.add_parser("select-secondary")
    secondary.add_argument("--decisions", type=Path, action="append", required=True)
    secondary.add_argument("--output", type=Path, required=True)
    adjudication = commands.add_parser("select-adjudication")
    adjudication.add_argument("--decisions", type=Path, action="append", required=True)
    adjudication.add_argument("--output", type=Path, required=True)
    merge = commands.add_parser("merge")
    merge.add_argument("--decisions", type=Path, action="append", required=True)
    merge.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    config = (args.config or (repo_root / DEFAULT_CONFIG)).resolve()
    try:
        suite = verify_suite(repo_root=repo_root, config_path=config)
        ledger = load_ledger(suite)
        if args.command == "prepare":
            if args.slice_count < 1:
                raise ValueError("local_mini131_semantic_slice_invalid")
            for number in range(1, args.slice_count + 1):
                slice_primary_inputs(
                    ledger,
                    slice_number=number,
                    slice_count=args.slice_count,
                    output_path=ledger.paths.review_root
                    / f"primary-inputs-{number}-of-{args.slice_count}.jsonl",
                )
            result = {
                "passed": True,
                "count": len(ledger.review_rows),
                "slice_count": args.slice_count,
                "review_inputs_sha256": sha256_file(ledger.paths.review_inputs),
                "review_config_sha256": ledger.review_config_sha256,
            }
        elif args.command == "validate":
            rows, _judgments = validate_decisions(ledger, args.decisions)
            result = {"passed": True, "decision_count": len(rows)}
        elif args.command == "select-secondary":
            rows = select_secondary_inputs(
                ledger, args.decisions, output_path=args.output.resolve()
            )
            result = {"passed": True, "selected": len(rows)}
        elif args.command == "select-adjudication":
            rows = select_adjudication_inputs(
                ledger, args.decisions, output_path=args.output.resolve()
            )
            result = {"passed": True, "selected": len(rows)}
        elif args.command == "merge":
            semantic_output = (
                args.output.resolve() if args.output else ledger.paths.semantic_score
            )
            report = merge_semantic_score(
                ledger,
                args.decisions,
                output_path=semantic_output,
            )
            result = _merge_cli_result(report, semantic_output)
        else:
            raise ValueError("local_mini131_semantic_command_invalid")
    except (ValueError, OSError, RuntimeError, json.JSONDecodeError) as error:
        print(json.dumps({"passed": False, "error": _safe_error(error)}, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
