"""Assemble the private Mini-131 evaluation bundle without provider calls.

The bundle deliberately separates blind judge input from execution metadata.
Candidate model, stack, provider, and configuration identities never enter the
``judge_input`` subtree.  Lineage remains in the private envelope so a later
merge can build the provenance-complete records consumed by
``midprojectrag.mini131_report``.

All private outputs are written atomically with mode ``0600``.  The tracked
receipt contains counts, hashes, cost totals, and objective companion metrics
only; it never contains questions, answers, source text, or case identifiers.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

from midprojectrag.ingest.common import canonical_json, read_jsonl, sha256_file, sha256_text
from midprojectrag.mini131_report import CASE_SCHEMA_VERSION, validate_records


SCHEMA_VERSION = "mini131-bundle.v1"
JUDGE_PACKET_SCHEMA_VERSION = "mini131-judge-packet.v1"
BLIND_JUDGE_INPUT_SCHEMA_VERSION = "mini131-blind-judge-input.v1"
BLIND_DECISION_SCHEMA_VERSION = "mini131-blind-decision.v1"
BLIND_ADJUDICATION_INPUT_SCHEMA_VERSION = (
    "mini131-blind-adjudication-input.v1"
)
BLIND_REVIEW_HISTORY_SCHEMA_VERSION = "mini131-blind-review-history.v1"
BASELINE_ID = "mini131-bundle-v1"
EXPECTED_COUNTS = {
    "rag": 129,
    "legacy_reconstructed": 39,
    "prospective_rerun": 90,
    "parser_local": 2,
    "total": 131,
}
EXPECTED_LANES = {
    "supplemental_answer_legacy": 39,
    "supplemental_answer_rerun": 17,
    "supplemental_set_rerun": 13,
    "core40": 40,
    "visual": 10,
    "corpus_analytics": 10,
}
JUDGE_MODEL = "gpt-5.6-sol"
JUDGE_RUBRIC = "gpt56-semantic-v2"
JUDGE_CONFIG_SCHEMA_VERSION = "mini131-judge-config.v1"
JUDGE_CONFIG_ID = "mini131-fixed-sol-v2"
CORE_RUNTIME_CONTRACT_AMENDMENT_ID = "core40-mixed-runtime-recovery-v1"
CORE_RECOVERED_CAPTURE_MODE = "prospective_runtime_with_offline_recovery"
GAP_RUNTIME_CONTRACT_AMENDMENT_ID = "gap30-set-schema-unique-items-400-v1"
GAP_RECOVERED_CAPTURE_MODE = (
    "prospective_runtime_exact_recovered_provider_rejection"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
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
JUDGE_IDENTITY_KEYS = frozenset({"case_id", "lane", "lineage"})

# Expose only task semantics to the reviewer. Source case identity, execution
# lane, and lineage remain in the private packet envelope and are recovered
# locally after the opaque judge-input hash is validated.
JUDGE_QUESTION_KINDS = {
    "supplemental_answer_legacy": "document_qa",
    "supplemental_answer_rerun": "document_qa",
    "supplemental_set_rerun": "document_set",
    "core40": "rag_qa",
    "visual": "visual_evidence_qa",
    "corpus_analytics": "corpus_analytics_qa",
}

JUDGE_WEIGHTS = {
    "correctness": 0.35,
    "faithfulness": 0.25,
    "completeness": 0.20,
    "factual_claim_coverage": 0.10,
    "citation_validity": 0.10,
}
JUDGMENT_SCORE_FIELDS = frozenset((*JUDGE_WEIGHTS, "abstention_quality"))
JUDGMENT_FIELDS = frozenset(
    {
        "schema_version",
        "judgment_id",
        "case_id",
        "case_sha256",
        "run_record_sha256",
        "judge_input_sha256",
        "review_config_sha256",
        "rubric_version",
        "reviewer_type",
        "model",
        "judge_role",
        "expected_behavior",
        "observed_status",
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
JUDGE_ROLES = frozenset({"primary", "secondary", "adjudicator"})
EXPECTED_BEHAVIORS = frozenset({"answer", "abstain", "source_conflict"})
OBSERVED_STATUSES = frozenset({"answered", "abstained", "error"})
ROLE_DECISIONS = {
    "primary": frozenset({"accepted", "needs_review", "rejected"}),
    "secondary": frozenset({"accepted", "needs_review", "rejected"}),
    "adjudicator": frozenset({"accepted", "rejected", "needs_human"}),
}
ALLOWED_COMPONENT_SCORES = frozenset({0, 0.5, 1})


@dataclass(frozen=True)
class BundlePaths:
    legacy_cases: Path
    legacy_runs: Path
    legacy_transcripts: Path
    legacy_config: Path
    legacy_receipt: Path
    gap_answer_cases: Path
    gap_set_cases: Path
    gap_answer_runs: Path
    gap_set_runs: Path
    gap_transcripts: Path
    gap_config: Path
    gap_receipt: Path
    core_cases: Path
    core_runs: Path
    core_transcripts: Path
    core_config: Path
    core_receipt: Path
    visual_cases: Path
    analytics_cases: Path
    analytics_calculations: Path
    visual_eda_runs: Path
    visual_eda_transcripts: Path
    visual_eda_config: Path
    visual_eda_receipt: Path
    parser_config: Path
    parser_receipt: Path
    rubric: Path
    judge_config: Path
    judge_packets: Path
    blind_judge_inputs: Path
    case_records: Path
    receipt: Path


def default_paths(repo_root: Path) -> BundlePaths:
    root = repo_root.resolve()

    def p(value: str) -> Path:
        return root / value

    return BundlePaths(
        legacy_cases=p("evaluation/private/supplemental/build-v1/rag-56.draft.jsonl"),
        legacy_runs=p("evaluation/private/supplemental/runs/provisional-v1/answer-56.runs.jsonl"),
        legacy_transcripts=p("evaluation/private/supplemental/runs/provisional-v1/chat-transcripts.jsonl"),
        legacy_config=p("evaluation/baselines/supplemental-provisional-v1/config.json"),
        legacy_receipt=p("evaluation/baselines/supplemental-provisional-v1/receipt.json"),
        gap_answer_cases=p("evaluation/private/supplemental/build-v1/rag-56.draft.jsonl"),
        gap_set_cases=p("evaluation/private/supplemental/build-v1/set-13.draft.jsonl"),
        gap_answer_runs=p("evaluation/private/supplemental/runs/mini-gap30-v1/answer-17.runs.jsonl"),
        gap_set_runs=p("evaluation/private/supplemental/runs/mini-gap30-v1/set-13.runs.jsonl"),
        gap_transcripts=p("evaluation/private/supplemental/runs/mini-gap30-v1/chat-transcripts.jsonl"),
        gap_config=p("evaluation/baselines/supplemental-mini-gap30-v1/config.json"),
        gap_receipt=p("evaluation/baselines/supplemental-mini-gap30-v1/receipt.json"),
        core_cases=p("golden-set-final/dev.refined.review-candidate.jsonl"),
        core_runs=p("evaluation/private/core40/runs/provisional-v1/run-records.jsonl"),
        core_transcripts=p("evaluation/private/core40/runs/provisional-v1/chat-transcripts.jsonl"),
        core_config=p("evaluation/baselines/core40-provisional-v1/config.json"),
        core_receipt=p("evaluation/baselines/core40-provisional-v1/receipt.json"),
        visual_cases=p("golden-set-final/document-structure-visual-qa.jsonl"),
        analytics_cases=p("golden-set-final/corpus-analytics-qa.jsonl"),
        analytics_calculations=p("evaluation/private/corpus-analytics/corpus-analytics-deterministic-v1/case-results.jsonl"),
        visual_eda_runs=p("evaluation/private/visual-eda-mini/runs/prospective-v1/run-records.jsonl"),
        visual_eda_transcripts=p("evaluation/private/visual-eda-mini/runs/prospective-v1/chat-transcripts.jsonl"),
        visual_eda_config=p("evaluation/baselines/visual-eda-mini-prospective-v1/config.json"),
        visual_eda_receipt=p("evaluation/baselines/visual-eda-mini-prospective-v1/receipt.json"),
        parser_config=p("evaluation/baselines/parser-regression-rhwp-v1/config.json"),
        parser_receipt=p("evaluation/baselines/parser-regression-rhwp-v1/receipt.json"),
        rubric=p("evaluation/rubric.md"),
        judge_config=p("evaluation/baselines/mini131-bundle-v1/judge-config.json"),
        judge_packets=p("evaluation/private/mini131/runs/baseline-v1/judge-packets.jsonl"),
        blind_judge_inputs=p("evaluation/private/mini131/runs/baseline-v1/blind-judge-inputs.jsonl"),
        case_records=p("evaluation/private/supplemental/runs/provisional-v1/case-records.jsonl"),
        receipt=p("evaluation/baselines/mini131-bundle-v1/receipt.json"),
    )


INPUT_FIELDS = (
    "legacy_cases",
    "legacy_runs",
    "legacy_transcripts",
    "legacy_config",
    "legacy_receipt",
    "gap_answer_cases",
    "gap_set_cases",
    "gap_answer_runs",
    "gap_set_runs",
    "gap_transcripts",
    "gap_config",
    "gap_receipt",
    "core_cases",
    "core_runs",
    "core_transcripts",
    "core_config",
    "core_receipt",
    "visual_cases",
    "analytics_cases",
    "analytics_calculations",
    "visual_eda_runs",
    "visual_eda_transcripts",
    "visual_eda_config",
    "visual_eda_receipt",
    "parser_config",
    "parser_receipt",
    "rubric",
    "judge_config",
)


def _atomic_private_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    content = "".join(canonical_json(dict(row)) + "\n" for row in rows)
    _atomic_text(path, content, mode=0o600)


def _atomic_public_json(path: Path, value: Mapping[str, Any]) -> None:
    _atomic_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        mode=0o644,
    )


def _atomic_text(path: Path, content: str, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode == 0o600:
        path.parent.chmod(0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        path.chmod(mode)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(code) from error
    if not isinstance(value, dict):
        raise ValueError(code)
    return value


def _index(rows: Sequence[Mapping[str, Any]], *, expected: int, code: str) -> dict[str, dict[str, Any]]:
    if len(rows) != expected:
        raise ValueError(f"{code}_count_mismatch")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or not case_id or case_id in result:
            raise ValueError(f"{code}_identity_invalid")
        result[case_id] = copy.deepcopy(dict(row))
    return result


def _string(value: Any, code: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(code)
    return value


def _question(case: Mapping[str, Any]) -> str:
    return _string(case.get("question"), "mini131_question_invalid")


def _expected(case: Mapping[str, Any], lane: str) -> dict[str, Any]:
    gold = case.get("gold")
    if lane != "supplemental_set_rerun" and not isinstance(gold, Mapping):
        raise ValueError("mini131_gold_missing")
    expected: dict[str, Any] = {}
    if isinstance(gold, Mapping):
        expected["gold"] = copy.deepcopy(dict(gold))
    if lane.startswith("supplemental_answer"):
        for key in ("required_doc_ids", "evidence_refs", "absence_scope_doc_ids", "task_type"):
            if key in case:
                expected[key] = copy.deepcopy(case[key])
    elif lane == "supplemental_set_rerun":
        for key in ("required_doc_ids", "required_fact_groups", "expected_count", "set_definition"):
            if key in case:
                expected[key] = copy.deepcopy(case[key])
    elif lane == "core40":
        for key in ("task_type", "document_scope", "history", "group_id"):
            if key in case:
                expected[key] = copy.deepcopy(case[key])
    elif lane == "visual":
        for key in (
            "document_scope",
            "document_format",
            "evidence_type",
            "retrieval_targets",
            "structure_or_visual_dependency",
            "page_reference_policy",
        ):
            if key in case:
                expected[key] = copy.deepcopy(case[key])
    elif lane == "corpus_analytics":
        for key in ("document_scope", "calculation_contract"):
            if key in case:
                expected[key] = copy.deepcopy(case[key])
    return expected


def _answer_status(run: Mapping[str, Any]) -> tuple[str, str]:
    response = run.get("response")
    source = response if isinstance(response, Mapping) else run
    status = _string(source.get("status"), "mini131_candidate_status_invalid")
    if status not in {"answered", "abstained", "error"}:
        raise ValueError("mini131_candidate_status_invalid")
    answer = _string(source.get("answer"), "mini131_candidate_answer_invalid", allow_empty=True)
    if status == "answered" and not answer.strip():
        raise ValueError("mini131_answered_without_answer")
    return status, answer


def _assistant_answer(transcript: Mapping[str, Any]) -> str | None:
    assistant = transcript.get("assistant")
    if not isinstance(assistant, Mapping):
        return None
    answer = assistant.get("final_answer")
    if isinstance(answer, str):
        return answer
    final = assistant.get("final_response")
    if isinstance(final, Mapping) and isinstance(final.get("answer"), str):
        return final["answer"]
    return None


def _blind_chat(question: str, answer: str, transcript: Mapping[str, Any]) -> list[dict[str, str]]:
    captured = _assistant_answer(transcript)
    if captured is not None and captured != answer:
        raise ValueError("mini131_transcript_answer_mismatch")
    return [
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer},
    ]


def _as_collection(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    return [copy.deepcopy(item) for item in value if isinstance(item, (str, Mapping))]


def _retrieval(run: Mapping[str, Any], transcript: Mapping[str, Any], lane: str) -> dict[str, Any]:
    raw_retrieval = run.get("retrieval")
    if not isinstance(raw_retrieval, list):
        raw_retrieval = transcript.get("retrieval")
    retrieved = _as_collection(raw_retrieval)
    if not retrieved:
        retrieved = _as_collection(run.get("retrieved_doc_ids"))
    if lane == "supplemental_set_rerun":
        retrieved = _as_collection(run.get("selected_doc_ids"))

    response = run.get("response")
    response_map = response if isinstance(response, Mapping) else run
    cited = _as_collection(response_map.get("citations"))
    if not cited:
        cited = _as_collection(run.get("cited_doc_ids"))
    if not cited:
        cited = _as_collection(run.get("cited_evidence_ids"))

    evidence = _as_collection(transcript.get("selected_context"))
    if not evidence:
        evidence = _as_collection(transcript.get("context_sources"))
    for key in ("visual_companion", "analytics_companion"):
        companion = transcript.get(key)
        if isinstance(companion, Mapping):
            evidence.append(copy.deepcopy(dict(companion)))
    if lane == "supplemental_set_rerun" and not evidence:
        evidence = copy.deepcopy(cited)
    return {
        "retrieved_docs": retrieved,
        "cited_docs": cited,
        "evidence": evidence,
    }


def _assert_blind(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).lower()
            if normalized in BANNED_JUDGE_KEYS or normalized.endswith("_model") or normalized.endswith("_stack"):
                raise ValueError("mini131_judge_identity_leak")
            _assert_blind(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_blind(nested)


def _without_judge_identity(value: Any) -> Any:
    """Remove source identifiers from a reviewer-visible projection."""

    if isinstance(value, Mapping):
        return {
            key: _without_judge_identity(nested)
            for key, nested in value.items()
            if str(key).lower() not in JUDGE_IDENTITY_KEYS
        }
    if isinstance(value, list):
        return [_without_judge_identity(nested) for nested in value]
    return copy.deepcopy(value)


def _packet(
    *,
    case: Mapping[str, Any],
    run: Mapping[str, Any],
    transcript: Mapping[str, Any],
    lane: str,
    lineage: str,
) -> dict[str, Any]:
    case_id = _string(case.get("case_id"), "mini131_case_id_invalid")
    if run.get("case_id") != case_id or transcript.get("case_id") != case_id:
        raise ValueError("mini131_source_case_mismatch")
    status, answer = _answer_status(run)
    question = _question(case)
    judge_input = _without_judge_identity({
        "question_kind": JUDGE_QUESTION_KINDS[lane],
        "question": question,
        "expected": _expected(case, lane),
        "candidate": {
            "status": status,
            "answer": answer,
            "chat": _blind_chat(question, answer, transcript),
        },
        "retrieval": _retrieval(run, transcript, lane),
    })
    _assert_blind(judge_input)
    source_transcript = copy.deepcopy(dict(transcript))
    hashes = {
        "case_sha256": sha256_text(canonical_json(case)),
        "run_sha256": sha256_text(canonical_json(run)),
        "transcript_sha256": sha256_text(canonical_json(source_transcript)),
        "judge_input_sha256": sha256_text(canonical_json(judge_input)),
    }
    return {
        "schema_version": JUDGE_PACKET_SCHEMA_VERSION,
        "case_id": case_id,
        "lane": lane,
        "lineage": lineage,
        "judge_input": judge_input,
        # Keep the complete execution transcript only in the private merge
        # envelope.  The blind projection below deliberately excludes it.
        "source_transcript": source_transcript,
        "hashes": hashes,
    }


def _load_rows(path: Path, code: str) -> list[dict[str, Any]]:
    try:
        return read_jsonl(path)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(code) from error


def _frozen_config_sha256(path: Path, expected_baseline_id: str) -> str:
    config = _read_json(path, "mini131_frozen_config_invalid")
    if config.get("baseline_id") != expected_baseline_id:
        raise ValueError("mini131_frozen_baseline_id_mismatch")
    return sha256_file(path)


def _expected_judge_config(rubric_sha256: str) -> dict[str, Any]:
    if not SHA256_RE.fullmatch(rubric_sha256):
        raise ValueError("mini131_rubric_sha256_invalid")
    return {
        "schema_version": JUDGE_CONFIG_SCHEMA_VERSION,
        "config_id": JUDGE_CONFIG_ID,
        "reviewer_type": "llm",
        "model": JUDGE_MODEL,
        "reasoning_effort": "high",
        "review_io": {
            "allowed_inputs": {
                "common": [
                    "evaluation/rubric.md",
                    "evaluation/baselines/mini131-bundle-v1/judge-config.json",
                ],
                "primary": {
                    "schema_version": BLIND_JUDGE_INPUT_SCHEMA_VERSION,
                    "source": "evaluation/private/mini131/runs/baseline-v1/blind-judge-inputs.jsonl",
                    "selection": "all_rows_or_deterministic_slice",
                    "prior_decisions": [],
                },
                "secondary": {
                    "schema_version": BLIND_JUDGE_INPUT_SCHEMA_VERSION,
                    "source": "evaluation/private/mini131/runs/baseline-v1/blind-judge-inputs.jsonl",
                    "selection": "validated_secondary_trigger_subset_or_deterministic_slice",
                    "prior_decisions": [],
                },
                "adjudicator": {
                    "schema_version": BLIND_ADJUDICATION_INPUT_SCHEMA_VERSION,
                    "source": "locally_validated_blind_adjudication_subset",
                    "selection": "validated_adjudication_trigger_subset_or_deterministic_slice",
                    "prior_decisions": ["primary", "secondary"],
                },
            },
            "forbidden_inputs": [
                "evaluation/private/mini131/runs/baseline-v1/judge-packets.jsonl",
            ],
            "blind_decision_schema_version": BLIND_DECISION_SCHEMA_VERSION,
            "review_history_schema_version": BLIND_REVIEW_HISTORY_SCHEMA_VERSION,
        },
        "rubric": {
            "version": JUDGE_RUBRIC,
            "sha256": rubric_sha256,
        },
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


def _judge_config_sha256(paths: BundlePaths) -> str:
    rubric_sha256 = sha256_file(paths.rubric)
    config = _read_json(paths.judge_config, "mini131_judge_config_invalid")
    if config != _expected_judge_config(rubric_sha256):
        raise ValueError("mini131_judge_config_mismatch")
    return sha256_file(paths.judge_config)


def _require_receipt_counts(
    receipt: Mapping[str, Any],
    expected: Mapping[str, int],
    *,
    code: str,
) -> None:
    counts = receipt.get("counts")
    if not isinstance(counts, Mapping):
        raise ValueError(f"{code}_counts_invalid")
    for field, value in expected.items():
        if counts.get(field) != value:
            raise ValueError(f"{code}_counts_mismatch")


def _require_receipt_artifacts(
    receipt: Mapping[str, Any],
    expected: Mapping[str, Path],
    *,
    code: str,
) -> None:
    artifacts = receipt.get("artifact_sha256s")
    if not isinstance(artifacts, Mapping):
        raise ValueError(f"{code}_artifacts_invalid")
    for field, path in expected.items():
        observed = artifacts.get(field)
        if (
            not isinstance(observed, str)
            or not SHA256_RE.fullmatch(observed)
            or observed != sha256_file(path)
        ):
            raise ValueError(f"{code}_{field}_sha256_mismatch")


def _validate_source_receipt(
    path: Path,
    *,
    baseline_id: str,
    config_sha256: str,
    expected_counts: Mapping[str, int],
    expected_artifacts: Mapping[str, Path],
    code: str,
    completion_field: str = "passed",
) -> dict[str, Any]:
    receipt = _read_json(path, f"{code}_invalid")
    if receipt.get("schema_version") != "1.0":
        raise ValueError(f"{code}_schema_version_mismatch")
    if receipt.get("baseline_id") != baseline_id:
        raise ValueError(f"{code}_baseline_id_mismatch")
    if receipt.get("config_sha256") != config_sha256:
        raise ValueError(f"{code}_config_sha256_mismatch")
    if receipt.get(completion_field) is not True:
        raise ValueError(f"{code}_not_complete")
    if "passed" in receipt and receipt.get("passed") is not True:
        raise ValueError(f"{code}_not_passed")
    _require_receipt_counts(receipt, expected_counts, code=code)
    _require_receipt_artifacts(receipt, expected_artifacts, code=code)
    budget = receipt.get("provider_budget")
    if isinstance(budget, Mapping) and budget.get("breached") is not False:
        raise ValueError(f"{code}_budget_invalid")
    return receipt


def _validate_core_runtime_contract_amendment(
    receipt: Mapping[str, Any],
    transcripts: Sequence[Mapping[str, Any]],
) -> None:
    amendment = receipt.get("runtime_contract_amendment")
    expected_fields = {
        "recovery_code_amendment_id",
        "source_runtime_contract_sha256",
        "target_runtime_contract_sha256",
        "failed_case_count",
        "failed_cases_retried",
        "provider_attempts_preserved",
        "provider_retries",
        "recovery_audit_count",
        "recovery_audit_sha256",
        "reserved_uncertain_usd",
    }
    if not isinstance(amendment, Mapping) or set(amendment) != expected_fields:
        raise ValueError("mini131_core_receipt_runtime_amendment_invalid")
    if (
        amendment.get("recovery_code_amendment_id")
        != CORE_RUNTIME_CONTRACT_AMENDMENT_ID
    ):
        raise ValueError("mini131_core_receipt_runtime_amendment_id_mismatch")
    for field in (
        "source_runtime_contract_sha256",
        "target_runtime_contract_sha256",
        "recovery_audit_sha256",
    ):
        value = amendment.get(field)
        if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
            raise ValueError(
                f"mini131_core_receipt_runtime_amendment_{field}_invalid"
            )
    if (
        type(amendment.get("failed_case_count")) is not int
        or amendment.get("failed_case_count") != 2
        or type(amendment.get("recovery_audit_count")) is not int
        or amendment.get("recovery_audit_count") != 2
    ):
        raise ValueError("mini131_core_receipt_runtime_amendment_count_mismatch")
    if amendment.get("failed_cases_retried") is not False:
        raise ValueError("mini131_core_receipt_runtime_amendment_retry_invalid")
    if amendment.get("provider_attempts_preserved") is not True:
        raise ValueError(
            "mini131_core_receipt_runtime_amendment_attempt_preservation_invalid"
        )
    if (
        type(amendment.get("provider_retries")) is not int
        or amendment.get("provider_retries") != 0
    ):
        raise ValueError("mini131_core_receipt_runtime_amendment_retry_count_invalid")

    budget = receipt.get("provider_budget")
    reserved = budget.get("reserved_usd") if isinstance(budget, Mapping) else None
    reserved_uncertain = amendment.get("reserved_uncertain_usd")
    if (
        not isinstance(reserved, (int, float))
        or isinstance(reserved, bool)
        or reserved <= 0
        or not isinstance(reserved_uncertain, (int, float))
        or isinstance(reserved_uncertain, bool)
        or reserved_uncertain != reserved
    ):
        raise ValueError("mini131_core_receipt_runtime_amendment_budget_mismatch")

    recovery_markers = 0
    for transcript in transcripts:
        if "recovery" not in transcript:
            if transcript.get("capture_mode") != "prospective_runtime_exact":
                raise ValueError("mini131_core_recovery_capture_mode_invalid")
            continue
        if (
            transcript.get("capture_mode") != CORE_RECOVERED_CAPTURE_MODE
            or not isinstance(transcript.get("recovery"), Mapping)
        ):
            raise ValueError("mini131_core_recovery_marker_invalid")
        recovery_markers += 1
    if (
        len(transcripts) != 40
        or recovery_markers != 2
        or recovery_markers != amendment["failed_case_count"]
    ):
        raise ValueError("mini131_core_recovery_marker_count_mismatch")


def _validate_gap_runtime_contract_amendment(
    receipt: Mapping[str, Any],
    *,
    answer_runs: Sequence[Mapping[str, Any]],
    set_runs: Sequence[Mapping[str, Any]],
    transcripts: Sequence[Mapping[str, Any]],
) -> None:
    if len(answer_runs) != 17:
        raise ValueError("mini131_gap_answer_runs_count_mismatch")
    if len(set_runs) != 13:
        raise ValueError("mini131_gap_set_runs_count_mismatch")
    amendment = receipt.get("runtime_contract_amendment")
    expected_fields = {
        "amendment_id",
        "source_runtime_contract_sha256",
        "target_runtime_contract_sha256",
        "failed_provider_attempt_preserved",
        "failed_case_retried",
        "private_amendment_sha256",
    }
    if not isinstance(amendment, Mapping) or set(amendment) != expected_fields:
        raise ValueError("mini131_gap_receipt_runtime_amendment_invalid")
    if amendment.get("amendment_id") != GAP_RUNTIME_CONTRACT_AMENDMENT_ID:
        raise ValueError("mini131_gap_receipt_runtime_amendment_id_mismatch")
    for field in (
        "source_runtime_contract_sha256",
        "target_runtime_contract_sha256",
        "private_amendment_sha256",
    ):
        value = amendment.get(field)
        if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
            raise ValueError(
                f"mini131_gap_receipt_runtime_amendment_{field}_invalid"
            )
    if amendment.get("failed_provider_attempt_preserved") is not True:
        raise ValueError(
            "mini131_gap_receipt_runtime_amendment_attempt_preservation_invalid"
        )
    if amendment.get("failed_case_retried") is not False:
        raise ValueError("mini131_gap_receipt_runtime_amendment_retry_invalid")

    runs = [*answer_runs, *set_runs]
    observed_statuses: Counter[str] = Counter()
    for run in runs:
        status, _answer = _answer_status(run)
        observed_statuses[status] += 1
    status_counts = receipt.get("status_counts")
    if (
        not isinstance(status_counts, Mapping)
        or set(status_counts) != {"answered", "abstained", "error"}
        or any(type(value) is not int for value in status_counts.values())
        or dict(status_counts)
        != {
            status: observed_statuses.get(status, 0)
            for status in ("answered", "abstained", "error")
        }
        or sum(observed_statuses.values()) != 30
    ):
        raise ValueError("mini131_gap_receipt_status_counts_mismatch")

    recovered: list[Mapping[str, Any]] = []
    for transcript in transcripts:
        capture_mode = transcript.get("capture_mode")
        if capture_mode == GAP_RECOVERED_CAPTURE_MODE:
            recovered.append(transcript)
        elif capture_mode != "prospective_runtime_exact":
            raise ValueError("mini131_gap_recovery_capture_mode_invalid")
        elif "runtime_contract_amendment" in transcript:
            raise ValueError("mini131_gap_recovery_marker_invalid")
    if len(transcripts) != 30 or len(recovered) != 1:
        raise ValueError("mini131_gap_recovery_marker_count_mismatch")

    transcript = recovered[0]
    private_amendment = transcript.get("runtime_contract_amendment")
    if (
        not isinstance(private_amendment, Mapping)
        or private_amendment.get("amendment_id")
        != GAP_RUNTIME_CONTRACT_AMENDMENT_ID
        or private_amendment.get("source_runtime_contract_sha256")
        != amendment["source_runtime_contract_sha256"]
        or private_amendment.get("target_runtime_contract_sha256")
        != amendment["target_runtime_contract_sha256"]
        or private_amendment.get("provider_attempt_policy")
        != "failed set case is preserved as error and never retried"
    ):
        raise ValueError("mini131_gap_recovery_marker_invalid")
    generation = transcript.get("provider_exchange")
    generation = (
        generation.get("generation") if isinstance(generation, Mapping) else None
    )
    error = generation.get("error") if isinstance(generation, Mapping) else None
    message = error.get("message") if isinstance(error, Mapping) else None
    final_response = transcript.get("assistant")
    final_response = (
        final_response.get("final_response")
        if isinstance(final_response, Mapping)
        else None
    )
    final_error = (
        final_response.get("error") if isinstance(final_response, Mapping) else None
    )
    if (
        not isinstance(generation, Mapping)
        or generation.get("attempt_number") != 1
        or generation.get("response") is not None
        or not isinstance(error, Mapping)
        or error.get("type") != "BadRequestError"
        or not isinstance(message, str)
        or "Error code: 400" not in message
        or "Invalid schema" not in message
        or "uniqueItems" not in message
        or "not permitted" not in message
        or transcript.get("runtime_error") != error
        or not isinstance(final_response, Mapping)
        or final_response.get("status") != "error"
        or not isinstance(final_error, Mapping)
        or final_error.get("code")
        != "gap30_set_schema_unique_items_provider_rejected"
        or final_error.get("type") != "BadRequestError"
        or final_error.get("message") != message
    ):
        raise ValueError("mini131_gap_recovery_provider_rejection_invalid")

    recovered_case_id = transcript.get("case_id")
    matched_runs = [run for run in set_runs if run.get("case_id") == recovered_case_id]
    if len(matched_runs) != 1 or _answer_status(matched_runs[0])[0] != "error":
        raise ValueError("mini131_gap_recovery_run_status_mismatch")


def _validate_source_integrity(paths: BundlePaths) -> dict[str, str]:
    config_sha256s = {
        "legacy": _frozen_config_sha256(
            paths.legacy_config, "supplemental-provisional-v1"
        ),
        "gap": _frozen_config_sha256(
            paths.gap_config, "supplemental-mini-gap30-v1"
        ),
        "core": _frozen_config_sha256(
            paths.core_config, "core40-provisional-v1"
        ),
        "visual_eda": _frozen_config_sha256(
            paths.visual_eda_config, "visual-eda-mini-prospective-v1"
        ),
    }
    _judge_config_sha256(paths)
    legacy_receipt = _validate_source_receipt(
        paths.legacy_receipt,
        baseline_id="supplemental-provisional-v1",
        config_sha256=config_sha256s["legacy"],
        expected_counts={
            "answer_cases": 56,
            "set_cases": 13,
            "total_cases": 69,
            "chat_transcripts": 69,
            "chat_transcripts_exact_persisted_answers": 39,
        },
        expected_artifacts={
            "answer_cases": paths.legacy_cases,
            "answer_runs": paths.legacy_runs,
            "set_cases": paths.gap_set_cases,
            "chat_transcripts": paths.legacy_transcripts,
        },
        code="mini131_legacy_receipt",
    )
    for section in ("answer_score", "set_score"):
        result = legacy_receipt.get(section)
        if (
            not isinstance(result, Mapping)
            or result.get("passed") is not True
            or result.get("suite_complete") is not True
        ):
            raise ValueError("mini131_legacy_receipt_not_complete")
    gap_receipt = _validate_source_receipt(
        paths.gap_receipt,
        baseline_id="supplemental-mini-gap30-v1",
        config_sha256=config_sha256s["gap"],
        expected_counts={
            "answer": 17,
            "set": 13,
            "transcripts": 30,
            "completed": 30,
            "remaining": 0,
            "total": 30,
        },
        expected_artifacts={
            "answer_runs": paths.gap_answer_runs,
            "set_runs": paths.gap_set_runs,
            "chat_transcripts": paths.gap_transcripts,
        },
        code="mini131_gap_receipt",
        completion_field="suite_complete",
    )
    _validate_gap_runtime_contract_amendment(
        gap_receipt,
        answer_runs=_load_rows(
            paths.gap_answer_runs, "mini131_gap_answer_runs_invalid"
        ),
        set_runs=_load_rows(paths.gap_set_runs, "mini131_gap_set_runs_invalid"),
        transcripts=_load_rows(
            paths.gap_transcripts, "mini131_gap_transcripts_invalid"
        ),
    )
    core_receipt = _validate_source_receipt(
        paths.core_receipt,
        baseline_id="core40-provisional-v1",
        config_sha256=config_sha256s["core"],
        expected_counts={"total": 40, "completed": 40, "remaining": 0},
        expected_artifacts={
            "run_records": paths.core_runs,
            "chat_transcripts": paths.core_transcripts,
        },
        code="mini131_core_receipt",
    )
    _validate_core_runtime_contract_amendment(
        core_receipt,
        _load_rows(paths.core_transcripts, "mini131_core_transcripts_invalid"),
    )
    _validate_source_receipt(
        paths.visual_eda_receipt,
        baseline_id="visual-eda-mini-prospective-v1",
        config_sha256=config_sha256s["visual_eda"],
        expected_counts={"total": 20, "completed": 20, "remaining": 0},
        expected_artifacts={
            "run_records": paths.visual_eda_runs,
            "chat_transcripts": paths.visual_eda_transcripts,
        },
        code="mini131_visual_eda_receipt",
    )
    return config_sha256s


def _validate_prospective_identity(
    run: Mapping[str, Any],
    transcript: Mapping[str, Any],
    *,
    baseline_id: str,
    config_sha256: str,
    allowed_capture_modes: frozenset[str] = frozenset(
        {"prospective_runtime_exact"}
    ),
) -> None:
    if transcript.get("baseline_id") != baseline_id:
        raise ValueError("mini131_transcript_baseline_id_mismatch")
    if transcript.get("config_sha256") != config_sha256:
        raise ValueError("mini131_transcript_config_sha256_mismatch")
    if transcript.get("capture_mode") not in allowed_capture_modes:
        raise ValueError("mini131_prospective_capture_mode_mismatch")
    # The three source harnesses predate one another and their compact run rows
    # do not all persist the same identity fields.  Any identity field a run
    # does persist is mandatory and must equal the frozen config; the exact
    # transcript supplies the complete baseline/config/capture binding.
    if "baseline_id" in run and run.get("baseline_id") != baseline_id:
        raise ValueError("mini131_run_baseline_id_mismatch")
    if "config_sha256" in run and run.get("config_sha256") != config_sha256:
        raise ValueError("mini131_run_config_sha256_mismatch")
    if "capture_mode" in run and run.get("capture_mode") not in allowed_capture_modes:
        raise ValueError("mini131_run_capture_mode_mismatch")


def _source_packets(paths: BundlePaths) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    config_sha256s = _validate_source_integrity(paths)
    gap_config_sha256 = config_sha256s["gap"]
    core_config_sha256 = config_sha256s["core"]
    visual_eda_config_sha256 = config_sha256s["visual_eda"]
    legacy_cases = _index(_load_rows(paths.legacy_cases, "mini131_legacy_cases_invalid"), expected=56, code="mini131_legacy_cases")
    legacy_runs = _index(_load_rows(paths.legacy_runs, "mini131_legacy_runs_invalid"), expected=56, code="mini131_legacy_runs")
    legacy_transcripts = _index(_load_rows(paths.legacy_transcripts, "mini131_legacy_transcripts_invalid"), expected=69, code="mini131_legacy_transcripts")
    gap_answer_cases = _index(_load_rows(paths.gap_answer_cases, "mini131_gap_answer_cases_invalid"), expected=56, code="mini131_gap_answer_cases")
    gap_set_cases = _index(_load_rows(paths.gap_set_cases, "mini131_gap_set_cases_invalid"), expected=13, code="mini131_gap_set_cases")
    gap_answer_runs = _index(_load_rows(paths.gap_answer_runs, "mini131_gap_answer_runs_invalid"), expected=17, code="mini131_gap_answer_runs")
    gap_set_runs = _index(_load_rows(paths.gap_set_runs, "mini131_gap_set_runs_invalid"), expected=13, code="mini131_gap_set_runs")
    gap_transcripts = _index(_load_rows(paths.gap_transcripts, "mini131_gap_transcripts_invalid"), expected=30, code="mini131_gap_transcripts")
    core_cases = _index(_load_rows(paths.core_cases, "mini131_core_cases_invalid"), expected=40, code="mini131_core_cases")
    core_runs = _index(_load_rows(paths.core_runs, "mini131_core_runs_invalid"), expected=40, code="mini131_core_runs")
    core_transcripts = _index(_load_rows(paths.core_transcripts, "mini131_core_transcripts_invalid"), expected=40, code="mini131_core_transcripts")
    visual_cases = _index(_load_rows(paths.visual_cases, "mini131_visual_cases_invalid"), expected=10, code="mini131_visual_cases")
    analytics_cases = _index(_load_rows(paths.analytics_cases, "mini131_analytics_cases_invalid"), expected=10, code="mini131_analytics_cases")
    analytics_calculations = _index(
        _load_rows(
            paths.analytics_calculations,
            "mini131_analytics_calculations_invalid",
        ),
        expected=10,
        code="mini131_analytics_calculations",
    )
    visual_eda_runs = _index(_load_rows(paths.visual_eda_runs, "mini131_visual_eda_runs_invalid"), expected=20, code="mini131_visual_eda_runs")
    visual_eda_transcripts = _index(_load_rows(paths.visual_eda_transcripts, "mini131_visual_eda_transcripts_invalid"), expected=20, code="mini131_visual_eda_transcripts")

    gap_answer_ids = set(gap_answer_runs)
    legacy_ids = set(legacy_cases) - gap_answer_ids
    if len(legacy_ids) != 39 or set(legacy_cases) != set(legacy_runs):
        raise ValueError("mini131_legacy39_ledger_mismatch")
    if set(gap_answer_cases) != set(legacy_cases) or not gap_answer_ids.issubset(gap_answer_cases):
        raise ValueError("mini131_gap_answer_ledger_mismatch")
    if set(gap_set_cases) != set(gap_set_runs):
        raise ValueError("mini131_gap_set_ledger_mismatch")
    if set(core_cases) != set(core_runs) or set(core_cases) != set(core_transcripts):
        raise ValueError("mini131_core40_ledger_mismatch")
    visual_ids, analytics_ids = set(visual_cases), set(analytics_cases)
    if visual_ids & analytics_ids or set(visual_eda_runs) != visual_ids | analytics_ids:
        raise ValueError("mini131_visual_eda_ledger_mismatch")
    if set(visual_eda_transcripts) != visual_ids | analytics_ids:
        raise ValueError("mini131_visual_eda_transcript_mismatch")
    if set(analytics_calculations) != analytics_ids:
        raise ValueError("mini131_analytics_calculation_ledger_mismatch")

    packets: list[dict[str, Any]] = []
    for case_id in sorted(legacy_ids):
        run = legacy_runs[case_id]
        if run.get("status") != "answered" or not run.get("answer"):
            raise ValueError("mini131_legacy_exact_answer_missing")
        transcript = legacy_transcripts.get(case_id)
        if transcript is None or transcript.get("capture_mode") != "posthoc_reconstructed":
            raise ValueError("mini131_legacy_reconstruction_missing")
        packets.append(_packet(case=legacy_cases[case_id], run=run, transcript=transcript, lane="supplemental_answer_legacy", lineage="legacy_reconstructed"))
    for case_id in sorted(gap_answer_ids):
        _validate_prospective_identity(
            gap_answer_runs[case_id],
            gap_transcripts[case_id],
            baseline_id="supplemental-mini-gap30-v1",
            config_sha256=gap_config_sha256,
        )
        packets.append(_packet(case=gap_answer_cases[case_id], run=gap_answer_runs[case_id], transcript=gap_transcripts[case_id], lane="supplemental_answer_rerun", lineage="prospective_rerun"))
    for case_id in sorted(gap_set_cases):
        _validate_prospective_identity(
            gap_set_runs[case_id],
            gap_transcripts[case_id],
            baseline_id="supplemental-mini-gap30-v1",
            config_sha256=gap_config_sha256,
            allowed_capture_modes=frozenset(
                {"prospective_runtime_exact", GAP_RECOVERED_CAPTURE_MODE}
            ),
        )
        packets.append(_packet(case=gap_set_cases[case_id], run=gap_set_runs[case_id], transcript=gap_transcripts[case_id], lane="supplemental_set_rerun", lineage="prospective_rerun"))
    for case_id in sorted(core_cases):
        _validate_prospective_identity(
            core_runs[case_id],
            core_transcripts[case_id],
            baseline_id="core40-provisional-v1",
            config_sha256=core_config_sha256,
            allowed_capture_modes=frozenset(
                {"prospective_runtime_exact", CORE_RECOVERED_CAPTURE_MODE}
            ),
        )
        packets.append(_packet(case=core_cases[case_id], run=core_runs[case_id], transcript=core_transcripts[case_id], lane="core40", lineage="prospective_rerun"))
    for case_id in sorted(visual_cases):
        _validate_prospective_identity(
            visual_eda_runs[case_id],
            visual_eda_transcripts[case_id],
            baseline_id="visual-eda-mini-prospective-v1",
            config_sha256=visual_eda_config_sha256,
        )
        packets.append(_packet(case=visual_cases[case_id], run=visual_eda_runs[case_id], transcript=visual_eda_transcripts[case_id], lane="visual", lineage="prospective_rerun"))
    for case_id in sorted(analytics_cases):
        transcript = visual_eda_transcripts[case_id]
        _validate_prospective_identity(
            visual_eda_runs[case_id],
            transcript,
            baseline_id="visual-eda-mini-prospective-v1",
            config_sha256=visual_eda_config_sha256,
        )
        companion = transcript.get("analytics_companion")
        if (
            not isinstance(companion, Mapping)
            or companion.get("numeric_evidence")
            != analytics_calculations[case_id].get("computed")
        ):
            raise ValueError("mini131_analytics_companion_calculation_mismatch")
        packets.append(_packet(case=analytics_cases[case_id], run=visual_eda_runs[case_id], transcript=visual_eda_transcripts[case_id], lane="corpus_analytics", lineage="prospective_rerun"))

    _validate_packets(packets)
    source_rows = [
        *(legacy_runs[case_id] for case_id in legacy_ids),
        *gap_answer_runs.values(),
        *gap_set_runs.values(),
        *core_runs.values(),
        *visual_eda_runs.values(),
    ]
    companion = _objective_companion(
        packets,
        analytics_calculations=analytics_calculations,
    )
    companion["candidate_cost_usd"] = round(sum(_cost(row) for row in source_rows), 8)
    return packets, companion


def _validate_packets(packets: Sequence[Mapping[str, Any]]) -> None:
    if len(packets) != EXPECTED_COUNTS["rag"]:
        raise ValueError("mini131_rag_count_mismatch")
    ids: set[str] = set()
    lanes: Counter[str] = Counter()
    lineages: Counter[str] = Counter()
    for packet in packets:
        if set(packet) != {
            "schema_version",
            "case_id",
            "lane",
            "lineage",
            "judge_input",
            "source_transcript",
            "hashes",
        }:
            raise ValueError("mini131_judge_packet_shape_invalid")
        if packet.get("schema_version") != JUDGE_PACKET_SCHEMA_VERSION:
            raise ValueError("mini131_judge_packet_schema_invalid")
        case_id = _string(packet.get("case_id"), "mini131_case_id_invalid")
        if case_id in ids:
            raise ValueError("mini131_duplicate_case_id")
        ids.add(case_id)
        lane = _string(packet.get("lane"), "mini131_lane_invalid")
        lineage = packet.get("lineage")
        if lineage not in {"legacy_reconstructed", "prospective_rerun"}:
            raise ValueError("mini131_lineage_invalid")
        judge_input = packet.get("judge_input")
        if not isinstance(judge_input, Mapping):
            raise ValueError("mini131_judge_input_invalid")
        source_transcript = packet.get("source_transcript")
        if not isinstance(source_transcript, Mapping):
            raise ValueError("mini131_source_transcript_invalid")
        if source_transcript.get("case_id") != case_id:
            raise ValueError("mini131_source_transcript_case_mismatch")
        _assert_blind(judge_input)
        if judge_input.get("question_kind") != JUDGE_QUESTION_KINDS.get(lane):
            raise ValueError("mini131_judge_input_identity_mismatch")
        hashes = packet.get("hashes")
        if not isinstance(hashes, Mapping) or set(hashes) != {"case_sha256", "run_sha256", "transcript_sha256", "judge_input_sha256"}:
            raise ValueError("mini131_packet_hashes_invalid")
        if any(not isinstance(value, str) or not SHA256_RE.fullmatch(value) for value in hashes.values()):
            raise ValueError("mini131_packet_hashes_invalid")
        if hashes["judge_input_sha256"] != sha256_text(canonical_json(judge_input)):
            raise ValueError("mini131_judge_input_hash_mismatch")
        if hashes["transcript_sha256"] != sha256_text(
            canonical_json(source_transcript)
        ):
            raise ValueError("mini131_source_transcript_hash_mismatch")
        lanes[lane] += 1
        lineages[str(lineage)] += 1
    if dict(lanes) != EXPECTED_LANES:
        raise ValueError("mini131_lane_ledger_mismatch")
    if lineages != Counter({"prospective_rerun": 90, "legacy_reconstructed": 39}):
        raise ValueError("mini131_lineage_ledger_mismatch")


def _blind_id(judge_input_sha256: str) -> str:
    """Return a stable opaque key that reveals neither case order nor lineage."""

    if not SHA256_RE.fullmatch(judge_input_sha256):
        raise ValueError("mini131_judge_input_hash_invalid")
    return sha256_text(
        f"{BLIND_JUDGE_INPUT_SCHEMA_VERSION}\n{judge_input_sha256}"
    )


def _blind_judge_rows(
    packets: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Build the only artifact a blind reviewer should receive.

    The complete packet remains private merge metadata.  This projection has
    no outer case id, source lane, or lineage and is sorted by an opaque digest
    rather than source/case order.  The embedded judge input is unchanged so
    the signed ``judge_input_sha256`` remains the single merge binding.
    """

    rows: list[dict[str, Any]] = []
    blind_ids: set[str] = set()
    for packet in packets:
        judge_input = packet.get("judge_input")
        hashes = packet.get("hashes")
        if not isinstance(judge_input, Mapping) or not isinstance(hashes, Mapping):
            raise ValueError("mini131_blind_judge_input_invalid")
        judge_input_sha256 = hashes.get("judge_input_sha256")
        if not isinstance(judge_input_sha256, str):
            raise ValueError("mini131_judge_input_hash_invalid")
        blind_id = _blind_id(judge_input_sha256)
        if blind_id in blind_ids:
            raise ValueError("mini131_duplicate_blind_id")
        blind_ids.add(blind_id)
        row = {
            "schema_version": BLIND_JUDGE_INPUT_SCHEMA_VERSION,
            "blind_id": blind_id,
            "judge_input_sha256": judge_input_sha256,
            "judge_input": copy.deepcopy(dict(judge_input)),
        }
        _assert_blind(row)
        if set(row) & {"case_id", "lane", "lineage"}:
            raise ValueError("mini131_blind_outer_identity_leak")
        rows.append(row)
    rows.sort(key=lambda row: row["blind_id"])
    if len(rows) != EXPECTED_COUNTS["rag"]:
        raise ValueError("mini131_blind_judge_input_count_mismatch")
    return rows


def _cost(row: Mapping[str, Any]) -> float:
    usage = row.get("usage")
    if not isinstance(usage, Mapping):
        return 0.0
    value = usage.get("cost_usd")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return float(value)
    return 0.0


def _doc_id(item: Any) -> str | None:
    if isinstance(item, str):
        return item
    if isinstance(item, Mapping) and isinstance(item.get("doc_id"), str):
        return item["doc_id"]
    return None


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _set_prf(required: set[str], returned: set[str]) -> tuple[float, float, float, int, int, int]:
    true_positive = len(required & returned)
    false_positive = len(returned - required)
    false_negative = len(required - returned)
    precision = (
        true_positive / len(returned)
        if returned
        else (1.0 if not required else 0.0)
    )
    recall = (
        true_positive / len(required)
        if required
        else (1.0 if not returned else 0.0)
    )
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1, true_positive, false_positive, false_negative


def _first_rank_summary(ranks: Sequence[int | float]) -> dict[str, Any]:
    values = [float(value) for value in ranks]
    if not values:
        return {
            "observed_count": 0,
            "mean": None,
            "median": None,
            "min": None,
            "max": None,
        }
    return {
        "observed_count": len(values),
        "mean": round(sum(values) / len(values), 6),
        "median": round(float(median(values)), 6),
        "min": min(values),
        "max": max(values),
    }


def _visual_target_summary(
    companions: Sequence[Mapping[str, Any]],
    *,
    target_key: str,
    rank_key: str,
) -> dict[str, Any]:
    eligible = 0
    ranks: list[int | float] = []
    for companion in companions:
        targets = companion.get("retrieval_targets")
        target_rows = targets.get(target_key) if isinstance(targets, Mapping) else None
        if not isinstance(target_rows, list) or not target_rows:
            continue
        eligible += 1
        rank = companion.get(rank_key)
        if (
            isinstance(rank, (int, float))
            and not isinstance(rank, bool)
            and rank > 0
        ):
            ranks.append(rank)
    return {
        "eligible_case_count": eligible,
        "hit_count": len(ranks),
        "hit_rate": _ratio(len(ranks), eligible),
        "first_rank": _first_rank_summary(ranks),
    }


def _numeric_leaf_count(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, (int, float)):
        return 1
    if isinstance(value, Mapping):
        return sum(_numeric_leaf_count(nested) for nested in value.values())
    if isinstance(value, list):
        return sum(_numeric_leaf_count(nested) for nested in value)
    return 0


def _objective_companion(
    packets: Sequence[Mapping[str, Any]],
    *,
    analytics_calculations: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    retrieval_numerator = 0
    retrieval_denominator = 0
    set_exact = 0
    set_total = 0
    set_macro_precision = 0.0
    set_macro_recall = 0.0
    set_macro_f1 = 0.0
    set_true_positive = 0
    set_false_positive = 0
    set_false_negative = 0
    visual_with_evidence = 0
    visual_total = 0
    visual_companions: list[Mapping[str, Any]] = []
    analytics_with_numeric = 0
    analytics_total = 0
    analytics_deterministic = 0
    analytics_numeric_field_counts: list[int] = []
    for packet in packets:
        lane = packet["lane"]
        judge = packet["judge_input"]
        expected = judge["expected"]
        retrieval = judge["retrieval"]
        required = expected.get("required_doc_ids")
        if isinstance(required, list) and required:
            returned = {_doc_id(item) for item in retrieval["retrieved_docs"]}
            returned.discard(None)
            retrieval_numerator += sum(doc_id in returned for doc_id in required)
            retrieval_denominator += len(required)
            if lane == "supplemental_set_rerun":
                set_total += 1
                set_exact += set(required) == returned
                precision, recall, f1, true_positive, false_positive, false_negative = _set_prf(
                    {str(doc_id) for doc_id in required},
                    {str(doc_id) for doc_id in returned},
                )
                set_macro_precision += precision
                set_macro_recall += recall
                set_macro_f1 += f1
                set_true_positive += true_positive
                set_false_positive += false_positive
                set_false_negative += false_negative
        if lane == "visual":
            visual_total += 1
            visual_with_evidence += bool(retrieval["evidence"])
            visual_companions.extend(
                item for item in retrieval["evidence"] if isinstance(item, Mapping)
                and isinstance(item.get("retrieval_targets"), Mapping)
            )
        if lane == "corpus_analytics":
            analytics_total += 1
            companions = [
                item
                for item in retrieval["evidence"]
                if isinstance(item, Mapping) and item.get("numeric_evidence") is not None
            ]
            analytics_with_numeric += bool(companions)
            if companions:
                companion = companions[0]
                analytics_numeric_field_counts.append(
                    _numeric_leaf_count(companion.get("numeric_evidence"))
                )
                analytics_deterministic += (
                    companion.get("source")
                    == "executed_deterministic_refined98_calculation"
                )
    set_micro_precision = _ratio(
        set_true_positive, set_true_positive + set_false_positive
    )
    set_micro_recall = _ratio(
        set_true_positive, set_true_positive + set_false_negative
    )
    if set_micro_precision is None or set_micro_recall is None:
        set_micro_f1 = None
    elif set_micro_precision + set_micro_recall:
        set_micro_f1 = round(
            2
            * set_micro_precision
            * set_micro_recall
            / (set_micro_precision + set_micro_recall),
            6,
        )
    else:
        set_micro_f1 = 0.0
    numeric_total = sum(analytics_numeric_field_counts)
    calculation_rows = (
        list(analytics_calculations.values())
        if analytics_calculations is not None
        else []
    )
    deterministic_case_passed = sum(row.get("passed") is True for row in calculation_rows)
    deterministic_field_total = 0
    deterministic_field_passed = 0
    for row in calculation_rows:
        comparisons = row.get("comparisons")
        if not isinstance(comparisons, list):
            raise ValueError("mini131_analytics_comparisons_invalid")
        deterministic_field_total += len(comparisons)
        deterministic_field_passed += sum(
            isinstance(item, Mapping) and item.get("match") is True
            for item in comparisons
        )
    deterministic_companion_passed = min(
        analytics_deterministic,
        deterministic_case_passed,
    )
    return {
        "required_document_recall": (
            round(retrieval_numerator / retrieval_denominator, 6)
            if retrieval_denominator
            else None
        ),
        "required_document_total": retrieval_denominator,
        "set_exact_match_rate": round(set_exact / set_total, 6) if set_total else None,
        "set_case_count": set_total,
        "set_macro_precision": round(set_macro_precision / set_total, 6) if set_total else None,
        "set_macro_recall": round(set_macro_recall / set_total, 6) if set_total else None,
        "set_macro_f1": round(set_macro_f1 / set_total, 6) if set_total else None,
        "set_micro_precision": set_micro_precision,
        "set_micro_recall": set_micro_recall,
        "set_micro_f1": set_micro_f1,
        "set_true_positive_total": set_true_positive,
        "set_false_positive_total": set_false_positive,
        "set_false_negative_total": set_false_negative,
        "visual_evidence_availability_rate": round(visual_with_evidence / visual_total, 6) if visual_total else None,
        "visual_case_count": visual_total,
        "visual_target_page": _visual_target_summary(
            visual_companions,
            target_key="pages",
            rank_key="target_page_first_rank",
        ),
        "visual_target_chunk": _visual_target_summary(
            visual_companions,
            target_key="chunks",
            rank_key="target_chunk_first_rank",
        ),
        "visual_target_object_bridge": _visual_target_summary(
            visual_companions,
            target_key="objects",
            rank_key="target_object_bridge_first_rank",
        ),
        "analytics_numeric_evidence_availability_rate": round(analytics_with_numeric / analytics_total, 6) if analytics_total else None,
        "analytics_case_count": analytics_total,
        "analytics_deterministic_companion_case_count": analytics_deterministic,
        "analytics_deterministic_companion_pass_count": deterministic_companion_passed,
        "analytics_deterministic_companion_complete_rate": _ratio(
            analytics_deterministic, analytics_total
        ),
        "analytics_deterministic_case_pass_count": deterministic_case_passed,
        "analytics_deterministic_case_pass_rate": _ratio(
            deterministic_case_passed, len(calculation_rows)
        ),
        "analytics_deterministic_field_count": deterministic_field_total,
        "analytics_deterministic_field_pass_count": deterministic_field_passed,
        "analytics_deterministic_field_pass_rate": _ratio(
            deterministic_field_passed, deterministic_field_total
        ),
        "analytics_numeric_evidence_field_count": numeric_total,
        "analytics_numeric_evidence_fields_per_case": {
            "observed_case_count": len(analytics_numeric_field_counts),
            "mean": (
                round(numeric_total / len(analytics_numeric_field_counts), 6)
                if analytics_numeric_field_counts
                else None
            ),
            "min": min(analytics_numeric_field_counts) if analytics_numeric_field_counts else None,
            "max": max(analytics_numeric_field_counts) if analytics_numeric_field_counts else None,
        },
    }


def _input_hashes(paths: BundlePaths) -> dict[str, str]:
    return {field: sha256_file(getattr(paths, field)) for field in INPUT_FIELDS}


def _public_receipt(
    *,
    stage: str,
    paths: BundlePaths,
    packets: Sequence[Mapping[str, Any]],
    companion: Mapping[str, Any],
    judgments_path: Path | None = None,
    records: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    review_config_sha256 = _judge_config_sha256(paths)
    lineages = Counter(str(row["lineage"]) for row in packets)
    lanes = Counter(str(row["lane"]) for row in packets)
    status_counts = Counter(str(row["judge_input"]["candidate"]["status"]) for row in packets)
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "baseline_id": BASELINE_ID,
        "stage": stage,
        "passed": True,
        "counts": {
            "rag": len(packets),
            "parser": 2 if records is not None else 0,
            "total": len(records) if records is not None else len(packets),
            "by_lineage": dict(sorted(lineages.items())),
            "by_lane": dict(sorted(lanes.items())),
            "by_candidate_status": dict(sorted(status_counts.items())),
        },
        "artifact_sha256s": {
            "judge_packets": sha256_file(paths.judge_packets),
            "blind_judge_inputs": sha256_file(paths.blind_judge_inputs),
            "inputs": _input_hashes(paths),
        },
        "costs": {"candidate_provider_usd": companion["candidate_cost_usd"]},
        "objective_companion_metrics": {
            key: value for key, value in companion.items() if key != "candidate_cost_usd"
        },
        "semantic_judge": {
            "model": JUDGE_MODEL,
            "rubric_version": JUDGE_RUBRIC,
            "rubric_sha256": sha256_file(paths.rubric),
            "review_config_sha256": review_config_sha256,
            "status": "complete" if records is not None else "pending",
        },
        "privacy": {
            "contains_case_ids": False,
            "contains_questions": False,
            "contains_answers": False,
            "contains_gold": False,
            "contains_source_text": False,
            "contains_provider_payloads": False,
            "private_artifacts_tracked": False,
        },
    }
    if judgments_path is not None:
        receipt["artifact_sha256s"]["judgments"] = sha256_file(judgments_path)
    if records is not None:
        receipt["artifact_sha256s"]["case_records"] = sha256_file(paths.case_records)
        rag_records = [record for record in records if record["case_type"] == "rag"]
        numeric = [
            _judgment_semantic_score(record["judgment"])
            for record in rag_records
            if isinstance(record.get("judgment"), Mapping)
        ]
        if numeric:
            receipt["semantic_judge"]["mean_semantic_score"] = round(sum(numeric) / len(numeric), 4)
        receipt["counts"]["judge_decisions"] = dict(
            sorted(
                Counter(
                    str(record["judgment"]["judge_decision"])
                    for record in records
                    if record["case_type"] == "rag"
                ).items()
            )
        )
        history_rows = [
            row
            for record in rag_records
            for row in record.get("judgment_history", [])
            if isinstance(row, Mapping)
        ]
        workflows = [
            record.get("judgment_workflow")
            for record in rag_records
            if isinstance(record.get("judgment_workflow"), Mapping)
        ]
        receipt["counts"]["judgment_rows"] = len(history_rows)
        receipt["counts"]["judge_roles"] = dict(
            sorted(Counter(str(row["judge_role"]) for row in history_rows).items())
        )
        receipt["counts"]["secondary_triggered_cases"] = sum(
            bool(row.get("secondary_required")) for row in workflows
        )
        receipt["counts"]["adjudicated_cases"] = sum(
            bool(row.get("adjudicator_present")) for row in workflows
        )
        receipt["counts"]["unresolved_judgment_cases"] = 0
        receipt["counts"]["full_source_transcripts"] = sum(
            record["case_type"] == "rag"
            and isinstance(record.get("source_transcript"), Mapping)
            for record in records
        )
        receipt["semantic_judge"]["history_validated"] = True
        receipt["semantic_judge"]["trigger_resolution_complete"] = True
        receipt["counts"]["parser_passed"] = sum(
            record["case_type"] == "parser" and bool(record["parser_result"]["passed"])
            for record in records
        )
    return receipt


def build_judge_packets(paths: BundlePaths) -> dict[str, Any]:
    packets, companion = _source_packets(paths)
    blind_rows = _blind_judge_rows(packets)
    _atomic_private_jsonl(paths.judge_packets, packets)
    _atomic_private_jsonl(paths.blind_judge_inputs, blind_rows)
    receipt = _public_receipt(stage="judge_packets_ready", paths=paths, packets=packets, companion=companion)
    _atomic_public_json(paths.receipt, receipt)
    return receipt


def _judgment_semantic_score(judgment: Mapping[str, Any]) -> float:
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


def _expected_behavior(packet: Mapping[str, Any]) -> str:
    if packet.get("lane") == "supplemental_set_rerun":
        return "answer"
    judge_input = packet.get("judge_input")
    expected = judge_input.get("expected") if isinstance(judge_input, Mapping) else None
    gold = expected.get("gold") if isinstance(expected, Mapping) else None
    decision = gold.get("decision") if isinstance(gold, Mapping) else None
    if decision not in EXPECTED_BEHAVIORS:
        raise ValueError("mini131_expected_behavior_invalid")
    return str(decision)


def _valid_rfc3339(value: Any) -> bool:
    if not isinstance(value, str) or not RFC3339_RE.fullmatch(value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _judgment_id(row: Mapping[str, Any]) -> str:
    payload = {key: copy.deepcopy(value) for key, value in row.items() if key != "judgment_id"}
    return sha256_text(canonical_json(payload))


def _validate_judgment_scores(value: Any, *, expected_behavior: str) -> None:
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
    return (
        behavior_failure
        or observed_status == "error"
        or bool(row["critical_flags"])
    )


def _validate_judgment_decision(row: Mapping[str, Any]) -> None:
    role = str(row["judge_role"])
    decision = str(row["judge_decision"])
    semantic_score = _judgment_semantic_score(row)
    confidence = float(row["confidence"])
    hard_rejection = _judgment_hard_rejection(row)
    if role == "adjudicator":
        final_accept = (
            not hard_rejection
            and semantic_score > 85
            and confidence >= 0.70
        )
        allowed = (
            {"accepted", "needs_human"}
            if final_accept
            else {"rejected", "needs_human"}
        )
    elif hard_rejection or semantic_score < 60:
        allowed = {"rejected"}
    elif semantic_score <= 85 or confidence < 0.70:
        allowed = {"needs_review"}
    else:
        allowed = {"accepted"}
    if decision not in allowed:
        raise ValueError("mini131_judge_decision_inconsistent")


def _secondary_triggered(primary: Mapping[str, Any]) -> bool:
    semantic_score = _judgment_semantic_score(primary)
    return (
        primary.get("judge_decision") == "needs_review"
        or float(primary["confidence"]) < 0.70
        or semantic_score in {60.0, 85.0}
    )


def _binary_recommendation(row: Mapping[str, Any]) -> str:
    """Reduce a review to the pass/fail recommendation used for agreement.

    A primary boundary row can legitimately carry ``needs_review`` while its
    component scores still imply a provisional pass/fail recommendation.  The
    independent secondary resolves that boundary without an adjudicator only
    when its *resolved* decision agrees with this recommendation and its
    critical flags agree exactly.
    """

    passes = (
        not _judgment_hard_rejection(row)
        and _judgment_semantic_score(row) > 85
        and float(row["confidence"]) >= 0.70
    )
    return "accepted" if passes else "rejected"


def _validate_string_list(value: Any, *, code: str) -> None:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item for item in value)
        or len(value) != len(set(value))
    ):
        raise ValueError(code)


def _judgments(
    path: Path,
    packets: Mapping[str, Mapping[str, Any]],
    *,
    review_config_sha256: str,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    dict[str, dict[str, Any]],
]:
    rows = _load_rows(path, "mini131_judgments_invalid")
    if not EXPECTED_COUNTS["rag"] <= len(rows) <= EXPECTED_COUNTS["rag"] * len(JUDGE_ROLES):
        raise ValueError("mini131_judgments_count_mismatch")
    grouped: dict[str, list[dict[str, Any]]] = {}
    judgment_ids: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ValueError("mini131_judgments_invalid")
        row = copy.deepcopy(dict(raw))
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or case_id not in packets:
            raise ValueError("mini131_judgment_ledger_mismatch")
        grouped.setdefault(case_id, []).append(row)
    if set(grouped) != set(packets):
        raise ValueError("mini131_judgment_ledger_mismatch")
    for case_id, history in grouped.items():
      for row in history:
        if set(row) != JUDGMENT_FIELDS:
            raise ValueError("mini131_judgment_fields_invalid")
        if row.get("schema_version") != "1.0":
            raise ValueError("mini131_judgment_schema_invalid")
        if row.get("model") != JUDGE_MODEL:
            raise ValueError("mini131_judge_model_mismatch")
        if row.get("rubric_version") != JUDGE_RUBRIC:
            raise ValueError("mini131_judge_rubric_mismatch")
        if row.get("reviewer_type") != "llm":
            raise ValueError("mini131_judge_reviewer_type_mismatch")
        if row.get("judge_role") not in JUDGE_ROLES:
            raise ValueError("mini131_judge_role_invalid")
        if row.get("case_id") != case_id:
            raise ValueError("mini131_judgment_case_mismatch")
        packet = packets[case_id]
        hashes = packet["hashes"]
        expected_hash_fields = {
            "case_sha256": hashes["case_sha256"],
            "run_record_sha256": hashes["run_sha256"],
            "judge_input_sha256": hashes["judge_input_sha256"],
            "review_config_sha256": review_config_sha256,
        }
        for field, expected in expected_hash_fields.items():
            observed = row.get(field)
            if (
                not isinstance(observed, str)
                or not SHA256_RE.fullmatch(observed)
                or observed != expected
            ):
                error = (
                    "mini131_judgment_input_hash_mismatch"
                    if field == "judge_input_sha256"
                    else f"mini131_judgment_{field}_mismatch"
                )
                raise ValueError(error)
        expected_behavior = _expected_behavior(packet)
        if row.get("expected_behavior") != expected_behavior:
            raise ValueError("mini131_judgment_expected_behavior_mismatch")
        observed_status = packet["judge_input"]["candidate"]["status"]
        if observed_status not in OBSERVED_STATUSES:
            raise ValueError("mini131_candidate_status_invalid")
        if row.get("observed_status") != observed_status:
            raise ValueError("mini131_judgment_observed_status_mismatch")
        _validate_judgment_scores(
            row.get("scores"),
            expected_behavior=expected_behavior,
        )
        _validate_string_list(
            row.get("matched_key_point_ids"),
            code="mini131_matched_key_point_ids_invalid",
        )
        _validate_string_list(
            row.get("critical_flags"),
            code="mini131_critical_flags_invalid",
        )
        for field in ("follow_up_success", "safe_abstention"):
            value = row.get(field)
            if value is not None and not isinstance(value, bool):
                raise ValueError(f"mini131_{field}_invalid")
        confidence = row.get("confidence")
        if (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not 0 <= float(confidence) <= 1
        ):
            raise ValueError("mini131_judge_confidence_invalid")
        if row.get("judge_decision") not in ROLE_DECISIONS[str(row["judge_role"])]:
            raise ValueError("mini131_judge_decision_invalid")
        if not isinstance(row.get("rationale"), str) or not row["rationale"].strip():
            raise ValueError("mini131_judge_rationale_invalid")
        if not _valid_rfc3339(row.get("reviewed_at")):
            raise ValueError("mini131_judgment_reviewed_at_invalid")
        judgment_id = row.get("judgment_id")
        if (
            not isinstance(judgment_id, str)
            or not SHA256_RE.fullmatch(judgment_id)
            or judgment_id != _judgment_id(row)
        ):
            raise ValueError("mini131_judgment_id_mismatch")
        if judgment_id in judgment_ids:
            raise ValueError("mini131_duplicate_judgment_id")
        judgment_ids.add(judgment_id)
        if row.get("judge_input_sha256") != hashes["judge_input_sha256"]:
            raise ValueError("mini131_judgment_input_hash_mismatch")
        _validate_judgment_decision(row)

    finals: dict[str, dict[str, Any]] = {}
    workflow: dict[str, dict[str, Any]] = {}
    role_order = {"primary": 0, "secondary": 1, "adjudicator": 2}
    for case_id, history in grouped.items():
        by_role: dict[str, dict[str, Any]] = {}
        for row in history:
            role = str(row["judge_role"])
            if role in by_role:
                raise ValueError("mini131_duplicate_judge_role")
            by_role[role] = row
        primary = by_role.get("primary")
        if primary is None:
            raise ValueError("mini131_primary_judgment_missing")
        secondary = by_role.get("secondary")
        adjudicator = by_role.get("adjudicator")
        secondary_required = _secondary_triggered(primary)
        if secondary_required and secondary is None:
            raise ValueError("mini131_secondary_judgment_missing")
        if not secondary_required and secondary is not None:
            raise ValueError("mini131_untriggered_secondary")
        primary_recommendation = _binary_recommendation(primary)
        secondary_unresolved = bool(
            secondary is not None
            and secondary.get("judge_decision") == "needs_review"
        )
        disagreement = bool(
            secondary is not None
            and not secondary_unresolved
            and secondary.get("judge_decision") != primary_recommendation
        )
        critical_flag_mismatch = bool(
            secondary is not None
            and set(secondary.get("critical_flags", []))
            != set(primary.get("critical_flags", []))
        )
        adjudicator_required = bool(
            secondary_required
            and (secondary_unresolved or disagreement or critical_flag_mismatch)
        )
        if adjudicator_required and adjudicator is None:
            raise ValueError("mini131_adjudicator_judgment_missing")
        if adjudicator is not None and secondary is None:
            raise ValueError("mini131_adjudicator_without_secondary")
        if adjudicator is not None and not adjudicator_required:
            raise ValueError("mini131_untriggered_adjudicator")
        ordered = sorted(history, key=lambda row: role_order[str(row["judge_role"])])
        reviewed = [
            datetime.fromisoformat(str(row["reviewed_at"]).replace("Z", "+00:00"))
            for row in ordered
        ]
        if reviewed != sorted(reviewed):
            raise ValueError("mini131_judgment_history_order_invalid")
        final = (
            adjudicator
            if adjudicator is not None
            else secondary
            if secondary is not None
            else primary
        )
        if final.get("judge_decision") == "needs_human":
            raise ValueError("mini131_adjudication_unresolved")
        if final.get("judge_decision") not in {"accepted", "rejected"}:
            raise ValueError("mini131_final_judgment_unresolved")
        finals[case_id] = final
        grouped[case_id] = ordered
        workflow[case_id] = {
            "secondary_required": secondary_required,
            "secondary_present": secondary is not None,
            "adjudicator_required": adjudicator_required,
            "adjudicator_present": adjudicator is not None,
            "primary_binary_recommendation": primary_recommendation,
            "secondary_unresolved": secondary_unresolved,
            "disagreement": disagreement,
            "critical_flag_mismatch": critical_flag_mismatch,
            "final_judgment_id": final["judgment_id"],
        }
    return finals, grouped, workflow


def _parser_records(paths: BundlePaths) -> list[dict[str, Any]]:
    config = _read_json(paths.parser_config, "mini131_parser_config_invalid")
    receipt = _read_json(paths.parser_receipt, "mini131_parser_receipt_invalid")
    if set(config) != {
        "schema_version",
        "baseline_id",
        "contract",
        "artifacts",
        "cases",
        "outputs",
    } or config.get("schema_version") != "1.0":
        raise ValueError("mini131_parser_config_invalid")
    if config.get("baseline_id") != "parser-regression-rhwp-v1":
        raise ValueError("mini131_parser_baseline_id_mismatch")
    contract = {
        "current_invariant": "canonical_rhwp_extraction_and_indexability",
        "legacy_fallback_activation_scored": False,
        "semantic_judge_required": False,
    }
    if config.get("contract") != contract:
        raise ValueError("mini131_parser_contract_mismatch")
    if config.get("outputs") != {
        "receipt": "evaluation/baselines/parser-regression-rhwp-v1/receipt.json"
    }:
        raise ValueError("mini131_parser_outputs_mismatch")
    artifacts = config.get("artifacts")
    if (
        not isinstance(artifacts, Mapping)
        or set(artifacts) != {"manifest", "manifest_sha256"}
        or not isinstance(artifacts.get("manifest"), str)
        or not artifacts["manifest"]
        or not isinstance(artifacts.get("manifest_sha256"), str)
        or not SHA256_RE.fullmatch(artifacts["manifest_sha256"])
    ):
        raise ValueError("mini131_parser_config_artifacts_invalid")
    if set(receipt) != {
        "schema_version",
        "baseline_id",
        "passed",
        "scoring_contract",
        "artifacts",
        "counts",
        "cases",
    } or receipt.get("schema_version") != "1.0":
        raise ValueError("mini131_parser_receipt_schema_mismatch")
    if receipt.get("baseline_id") != config["baseline_id"]:
        raise ValueError("mini131_parser_receipt_baseline_id_mismatch")
    receipt_artifacts = receipt.get("artifacts")
    if (
        not isinstance(receipt_artifacts, Mapping)
        or set(receipt_artifacts) != {"config_sha256", "manifest_sha256"}
    ):
        raise ValueError("mini131_parser_receipt_artifacts_invalid")
    if receipt_artifacts.get("config_sha256") != sha256_file(paths.parser_config):
        raise ValueError("mini131_parser_receipt_config_sha256_mismatch")
    if receipt_artifacts.get("manifest_sha256") != artifacts["manifest_sha256"]:
        raise ValueError("mini131_parser_receipt_manifest_sha256_mismatch")
    if receipt.get("scoring_contract") != {
        "lane": "deterministic_etl_regression",
        **contract,
    }:
        raise ValueError("mini131_parser_scoring_contract_mismatch")
    cases = config.get("cases")
    results = receipt.get("cases")
    if not isinstance(cases, list) or len(cases) != 2 or not isinstance(results, list) or len(results) != 2:
        raise ValueError("mini131_parser_count_mismatch")
    expected_case_fields = {
        "case_id",
        "doc_id",
        "input_sha256",
        "expected_extractor",
        "expected_status",
        "expected_index_eligible",
        "expected_block_count",
        "expected_primary_text_chars",
        "expected_page_count",
    }
    if any(not isinstance(row, Mapping) or set(row) != expected_case_fields for row in cases):
        raise ValueError("mini131_parser_cases_invalid")
    for row in cases:
        if (
            not isinstance(row.get("doc_id"), str)
            or not row["doc_id"]
            or not isinstance(row.get("input_sha256"), str)
            or not SHA256_RE.fullmatch(row["input_sha256"])
            or not isinstance(row.get("expected_extractor"), str)
            or not row["expected_extractor"]
            or not isinstance(row.get("expected_status"), str)
            or not row["expected_status"]
            or not isinstance(row.get("expected_index_eligible"), bool)
            or any(
                not isinstance(row.get(field), int)
                or isinstance(row.get(field), bool)
                or row[field] < 0
                for field in (
                    "expected_block_count",
                    "expected_primary_text_chars",
                    "expected_page_count",
                )
            )
        ):
            raise ValueError("mini131_parser_cases_invalid")
    expected = _index(cases, expected=2, code="mini131_parser_cases")
    observed = _index(results, expected=2, code="mini131_parser_results")
    if set(expected) != {"C21", "C22"} or set(observed) != set(expected):
        raise ValueError("mini131_parser_ledger_mismatch")
    counts = receipt.get("counts")
    if counts != {"total": 2, "passed": 2, "failed": 0}:
        raise ValueError("mini131_parser_receipt_counts_mismatch")
    if receipt.get("passed") is not True:
        raise ValueError("mini131_parser_receipt_not_passed")
    check_fields = {
        "manifest_row_present",
        "input_sha256_match",
        "status_match",
        "extractor_match",
        "index_eligible_match",
        "block_count_match",
        "primary_text_chars_match",
        "page_count_match",
        "error_absent",
        "block_file_present",
        "block_file_count_match",
    }
    observed_fields = {
        "status",
        "extractor",
        "index_eligible",
        "block_count",
        "primary_text_chars",
        "page_count",
        "block_file_sha256",
    }
    records: list[dict[str, Any]] = []
    for case_id in sorted(expected):
        expected_case = expected[case_id]
        result = observed[case_id]
        if set(result) != {"case_id", "doc_id", "passed", "checks", "observed"}:
            raise ValueError("mini131_parser_result_shape_invalid")
        if result.get("doc_id") != expected_case.get("doc_id"):
            raise ValueError("mini131_parser_doc_id_mismatch")
        checks = result.get("checks")
        if (
            not isinstance(checks, Mapping)
            or set(checks) != check_fields
            or any(value is not True for value in checks.values())
        ):
            raise ValueError("mini131_parser_checks_invalid")
        observed_values = result.get("observed")
        if not isinstance(observed_values, Mapping) or set(observed_values) != observed_fields:
            raise ValueError("mini131_parser_observed_invalid")
        expected_observed = {
            "status": expected_case["expected_status"],
            "extractor": expected_case["expected_extractor"],
            "index_eligible": expected_case["expected_index_eligible"],
            "block_count": expected_case["expected_block_count"],
            "primary_text_chars": expected_case["expected_primary_text_chars"],
            "page_count": expected_case["expected_page_count"],
        }
        if any(observed_values.get(key) != value for key, value in expected_observed.items()):
            raise ValueError("mini131_parser_observed_mismatch")
        block_file_sha256 = observed_values.get("block_file_sha256")
        if not isinstance(block_file_sha256, str) or not SHA256_RE.fullmatch(block_file_sha256):
            raise ValueError("mini131_parser_block_file_sha256_invalid")
        passed = result.get("passed")
        if passed is not True:
            raise ValueError("mini131_parser_passed_invalid")
        records.append(
            {
                "schema_version": CASE_SCHEMA_VERSION,
                "case_id": case_id,
                "case_type": "parser",
                "lane": "parser_regression",
                "question": f"현재 정본 파서가 회귀 사례 {case_id}를 정상 추출하고 인덱싱 가능한가?",
                "expected": {
                    "current_invariant": "canonical_rhwp_extraction_and_indexability",
                    "case": copy.deepcopy(expected_case),
                },
                "candidate": {
                    "status": "passed" if passed else "failed",
                    "answer": "local deterministic parser regression",
                    "lineage": "parser_local",
                    "chat": [],
                },
                "retrieval": {"retrieved_docs": [], "cited_docs": [], "evidence": []},
                "source_transcript": None,
                "source_transcript_sha256": None,
                "judgment": None,
                "judgment_history": [],
                "judgment_workflow": None,
                "parser_result": copy.deepcopy(result),
            }
        )
    return records


def merge_judgments(paths: BundlePaths, judgments_path: Path) -> dict[str, Any]:
    packets = _load_rows(paths.judge_packets, "mini131_judge_packets_invalid")
    _validate_packets(packets)
    blind_rows = _load_rows(
        paths.blind_judge_inputs,
        "mini131_blind_judge_inputs_invalid",
    )
    if blind_rows != _blind_judge_rows(packets):
        raise ValueError("mini131_blind_judge_inputs_mismatch")
    # Rebuild the complete private envelope before merging.  A source mutation
    # after blind packet creation must never be silently paired with judgments
    # produced against an older candidate or gold payload.
    refreshed_packets, companion = _source_packets(paths)
    if packets != refreshed_packets:
        raise ValueError("mini131_source_drift_after_packet_build")
    packets_by_id = {row["case_id"]: row for row in packets}
    judgments, judgment_histories, judgment_workflows = _judgments(
        judgments_path,
        packets_by_id,
        review_config_sha256=_judge_config_sha256(paths),
    )
    records: list[dict[str, Any]] = []
    for packet in packets:
        judge_input = packet["judge_input"]
        records.append(
            {
                "schema_version": CASE_SCHEMA_VERSION,
                "case_id": packet["case_id"],
                "case_type": "rag",
                "lane": packet["lane"],
                "question": judge_input["question"],
                "expected": copy.deepcopy(judge_input["expected"]),
                "candidate": {
                    "status": judge_input["candidate"]["status"],
                    "answer": judge_input["candidate"]["answer"],
                    "lineage": packet["lineage"],
                    "chat": copy.deepcopy(judge_input["candidate"]["chat"]),
                },
                "retrieval": copy.deepcopy(judge_input["retrieval"]),
                "source_transcript": copy.deepcopy(packet["source_transcript"]),
                "source_transcript_sha256": packet["hashes"][
                    "transcript_sha256"
                ],
                "judgment": copy.deepcopy(judgments[packet["case_id"]]),
                "judgment_history": copy.deepcopy(
                    judgment_histories[packet["case_id"]]
                ),
                "judgment_workflow": copy.deepcopy(
                    judgment_workflows[packet["case_id"]]
                ),
                "parser_result": None,
            }
        )
    records.extend(_parser_records(paths))
    checked = validate_records(records)
    _atomic_private_jsonl(paths.case_records, checked)
    receipt = _public_receipt(
        stage="case_records_ready",
        paths=paths,
        packets=packets,
        companion=companion,
        judgments_path=judgments_path,
        records=checked,
    )
    _atomic_public_json(paths.receipt, receipt)
    return receipt


def preflight(paths: BundlePaths) -> dict[str, Any]:
    missing = [field for field in INPUT_FIELDS if not getattr(paths, field).is_file()]
    output = {
        "schema_version": SCHEMA_VERSION,
        "baseline_id": BASELINE_ID,
        "ready": not missing,
        "required_input_count": len(INPUT_FIELDS),
        "present_input_count": len(INPUT_FIELDS) - len(missing),
        "missing_inputs": missing,
        "expected_counts": copy.deepcopy(EXPECTED_COUNTS),
        "private_content_exposed": False,
    }
    if not missing:
        try:
            packets, _companion = _source_packets(paths)
            output["validated_rag_count"] = len(packets)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            output["ready"] = False
            code = str(error)
            output["validation_error"] = code if re.fullmatch(r"[a-z][a-z0-9_]{0,127}", code) else "mini131_preflight_failed"
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Assemble and merge the private Mini-131 evaluation bundle")
    parser.add_argument("command", choices=("preflight", "prepare", "merge"))
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--judgments", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = default_paths(args.repo_root)
    try:
        if args.command == "preflight":
            result = preflight(paths)
            print(canonical_json(result))
            return 0 if result["ready"] else 1
        if args.command == "prepare":
            result = build_judge_packets(paths)
        else:
            if args.judgments is None:
                raise ValueError("mini131_judgments_path_required")
            result = merge_judgments(paths, args.judgments)
        print(canonical_json({
            "schema_version": SCHEMA_VERSION,
            "stage": result["stage"],
            "passed": result["passed"],
            "counts": result["counts"],
            "receipt_sha256": sha256_file(paths.receipt),
            "private_content_exposed": False,
        }))
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        code = str(error)
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", code):
            code = "mini131_bundle_failed"
        print(canonical_json({"schema_version": SCHEMA_VERSION, "passed": False, "error": {"code": code}, "private_content_exposed": False}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
