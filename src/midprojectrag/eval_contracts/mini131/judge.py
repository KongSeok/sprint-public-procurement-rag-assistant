"""Provider-neutral blind-judge contract for Mini131 candidates."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from midprojectrag.ingest.common import canonical_json, sha256_text


BLIND_JUDGE_INPUT_SCHEMA_VERSION = "mini131-blind-judge-input.v1"
BLIND_DECISION_SCHEMA_VERSION = "mini131-blind-decision.v1"
BLIND_ADJUDICATION_INPUT_SCHEMA_VERSION = "mini131-blind-adjudication-input.v1"
BLIND_REVIEW_HISTORY_SCHEMA_VERSION = "mini131-blind-review-history.v1"
JUDGE_MODEL = "gpt-5.6-sol"
JUDGE_RUBRIC = "gpt56-semantic-v2"
JUDGE_CONFIG_SCHEMA_VERSION = "mini131-judge-config.v1"
JUDGE_CONFIG_ID = "mini131-fixed-sol-v2"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
JUDGE_ROLES = frozenset({"primary", "secondary", "adjudicator"})
EXPECTED_BEHAVIORS = frozenset({"answer", "abstain", "source_conflict"})
ROLE_DECISIONS = {
    "primary": frozenset({"accepted", "needs_review", "rejected"}),
    "secondary": frozenset({"accepted", "needs_review", "rejected"}),
    "adjudicator": frozenset({"accepted", "rejected", "needs_human"}),
}
JUDGE_WEIGHTS = {
    "correctness": 0.35,
    "faithfulness": 0.25,
    "completeness": 0.20,
    "factual_claim_coverage": 0.10,
    "citation_validity": 0.10,
}
JUDGMENT_SCORE_FIELDS = frozenset((*JUDGE_WEIGHTS, "abstention_quality"))
ALLOWED_COMPONENT_SCORES = frozenset({0, 0.5, 1})
BANNED_JUDGE_KEYS = {
    "api_profile",
    "baseline_id",
    "case_id",
    "candidate_stack",
    "config_sha256",
    "embedding_model",
    "generator_model",
    "git_commit",
    "lane",
    "lineage",
    "model",
    "provider",
    "provider_exchange",
    "reasoning_effort",
    "run_id",
    "stack",
    "stack_id",
}
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


def assert_blind(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).lower()
            if (
                normalized in BANNED_JUDGE_KEYS
                or normalized.endswith("_model")
                or normalized.endswith("_stack")
            ):
                raise ValueError("mini131_judge_identity_leak")
            assert_blind(nested)
    elif isinstance(value, list):
        for nested in value:
            assert_blind(nested)


def blind_id(judge_input_sha256: str) -> str:
    if not SHA256_RE.fullmatch(judge_input_sha256):
        raise ValueError("mini131_judge_input_hash_invalid")
    return sha256_text(f"{BLIND_JUDGE_INPUT_SCHEMA_VERSION}\n{judge_input_sha256}")


def judgment_semantic_score(judgment: Mapping[str, Any]) -> float:
    scores = judgment.get("scores")
    if not isinstance(scores, Mapping):
        raise ValueError("mini131_judge_scores_invalid")
    abstention = scores.get("abstention_quality")
    if abstention is not None:
        return round(100.0 * float(abstention), 2)
    return round(
        100.0
        * sum(float(scores[field]) * weight for field, weight in JUDGE_WEIGHTS.items()),
        2,
    )


def valid_rfc3339(value: Any) -> bool:
    if not isinstance(value, str) or not RFC3339_RE.fullmatch(value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def judgment_id(row: Mapping[str, Any]) -> str:
    payload = {
        key: copy.deepcopy(value)
        for key, value in row.items()
        if key != "judgment_id"
    }
    return sha256_text(canonical_json(payload))


def validate_judgment_scores(value: Any, *, expected_behavior: str) -> None:
    if not isinstance(value, Mapping) or set(value) != JUDGMENT_SCORE_FIELDS:
        raise ValueError("mini131_judge_score_fields_invalid")
    for score in value.values():
        if score is not None and (
            isinstance(score, bool) or score not in ALLOWED_COMPONENT_SCORES
        ):
            raise ValueError("mini131_judge_score_value_invalid")
    abstention = value.get("abstention_quality")
    if expected_behavior == "abstain":
        if abstention is None:
            raise ValueError("mini131_abstention_quality_missing")
        if any(value.get(field) is not None for field in JUDGE_WEIGHTS):
            raise ValueError("mini131_abstention_answer_components_forbidden")
        return
    if expected_behavior not in {"answer", "source_conflict"}:
        raise ValueError("mini131_expected_behavior_invalid")
    if abstention is not None:
        raise ValueError("mini131_answer_abstention_quality_forbidden")
    if any(value.get(field) is None for field in JUDGE_WEIGHTS):
        raise ValueError("mini131_answer_component_missing")


def _judgment_hard_rejection(row: Mapping[str, Any]) -> bool:
    expected_behavior = str(row["expected_behavior"])
    observed_status = str(row["observed_status"])
    safe_abstention = row.get("safe_abstention")
    if expected_behavior == "abstain":
        if not isinstance(safe_abstention, bool):
            raise ValueError("mini131_safe_abstention_required")
        behavior_failure = observed_status != "abstained" or safe_abstention is not True
    else:
        if safe_abstention is not None:
            raise ValueError("mini131_safe_abstention_scope_invalid")
        behavior_failure = observed_status != "answered"
    return behavior_failure or observed_status == "error" or bool(row["critical_flags"])


def validate_judgment_decision(row: Mapping[str, Any]) -> None:
    role = str(row["judge_role"])
    decision = str(row["judge_decision"])
    semantic_score = judgment_semantic_score(row)
    confidence = float(row["confidence"])
    hard_rejection = _judgment_hard_rejection(row)
    if role == "adjudicator":
        final_accept = not hard_rejection and semantic_score > 85 and confidence >= 0.70
        allowed = {"accepted", "needs_human"} if final_accept else {"rejected", "needs_human"}
    elif hard_rejection or semantic_score < 60:
        allowed = {"rejected"}
    elif semantic_score <= 85 or confidence < 0.70:
        allowed = {"needs_review"}
    else:
        allowed = {"accepted"}
    if decision not in allowed:
        raise ValueError("mini131_judge_decision_inconsistent")


def secondary_triggered(primary: Mapping[str, Any]) -> bool:
    semantic_score = judgment_semantic_score(primary)
    return (
        primary.get("judge_decision") == "needs_review"
        or float(primary["confidence"]) < 0.70
        or semantic_score in {60.0, 85.0}
    )


def binary_recommendation(row: Mapping[str, Any]) -> str:
    passes = (
        not _judgment_hard_rejection(row)
        and judgment_semantic_score(row) > 85
        and float(row["confidence"]) >= 0.70
    )
    return "accepted" if passes else "rejected"


def expected_judge_config(rubric_sha256: str) -> dict[str, Any]:
    if not SHA256_RE.fullmatch(rubric_sha256):
        raise ValueError("mini131_rubric_sha256_invalid")
    return {
        "schema_version": JUDGE_CONFIG_SCHEMA_VERSION,
        "config_id": JUDGE_CONFIG_ID,
        "reviewer_type": "llm",
        "model": JUDGE_MODEL,
        "reasoning_effort": "high",
        "rubric": {"version": JUDGE_RUBRIC, "sha256": rubric_sha256},
        "weights": copy.deepcopy(JUDGE_WEIGHTS),
        "decision_policy": {
            "role_decisions": {
                role: sorted(decisions) for role, decisions in ROLE_DECISIONS.items()
            },
            "primary_precedence": [
                "hard_rejection",
                "score_below_60",
                "needs_review_60_through_85_or_low_confidence",
                "accepted_above_85",
            ],
            "acceptance": {
                "score_operator": "greater_than",
                "score_threshold": 85,
                "minimum_confidence": 0.70,
                "critical_flags": "none",
            },
            "secondary_triggers": [
                "needs_review",
                "confidence_below_0_70",
                "boundary_case",
            ],
            "final_acceptance": {
                "score_operator": "greater_than",
                "score_threshold": 85,
                "minimum_confidence": 0.70,
                "critical_flags": "none",
                "unresolved_needs_human": False,
                "allowed_final_roles": ["adjudicator", "primary", "secondary"],
                "unresolved_needs_review": False,
            },
        },
        "blinding": {
            "hidden_fields": [
                "candidate_model",
                "candidate_stack",
                "case_id",
                "execution_lane",
                "provider",
                "lineage",
            ],
            "visible_fields": [
                "question_kind",
                "question",
                "expected",
                "candidate_status",
                "candidate_answer",
                "retrieval_evidence",
            ],
            "binding": "judge_input_sha256",
        },
        "roles": {
            "primary": {
                "model": JUDGE_MODEL,
                "independent": True,
                "sees_prior_judgment": False,
            },
            "secondary": {
                "model": JUDGE_MODEL,
                "independent": True,
                "sees_prior_judgment": False,
            },
            "adjudicator": {
                "model": JUDGE_MODEL,
                "independent": True,
                "sees_prior_judgment": True,
            },
        },
    }
