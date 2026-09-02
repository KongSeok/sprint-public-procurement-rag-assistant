"""Prepare offline harness learning records; never train, judge, or evolve code.

Only explicitly allowlisted nonofficial requests enter an export. Request
fingerprints intentionally exclude IDs, options, and document scopes: changing
metadata must not turn a heldout conversation into a training example. Exported
SFT targets are observed actions, not approved expert labels. RL rewards stay
unset until an external approved reward/receipt workflow supplies them.

Inputs/outputs contain private query/state data. The CLI owns private-root file
IO. This module performs no provider calls, model loading, code execution, or
semantic scoring. Seals establish manifest consistency, not measured quality.
"""

from __future__ import annotations

import copy
import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import fields
from typing import Any

from midprojectrag.evaluation import validate_request, validate_response
from midprojectrag.evidence import Evidence, EvidenceStore
from midprojectrag.orchestration.artifacts import digest
from midprojectrag.orchestration.types import Action, HarnessConfig, QueryPlan, Slot


_HASH = re.compile(r"[0-9a-f]{64}\Z")
_TRACE_FIELDS = {
    "schema_version", "request", "config", "config_sha256", "evidence_sha256",
    "policy_id", "synthetic", "official", "experience_enabled", "result",
    "provider_calls", "trace_sha256",
}
_STATE_FIELDS = {
    "plan", "verified", "missing", "candidate_ids", "rounds", "actions_spent",
    "allowed_actions", "contradictions", "terminal_reason",
}
_EVENT_FIELDS = {
    "action", "candidate_ids", "verified_ids", "pre_rerank_ids", "ranks",
    "elapsed_ms", "state_before", "state_after", "contradiction",
}
_SEALS = {"evidence_sha256", "gold_sha256", "judge_sha256", "config_sha256"}


def _shape(value: Any, keys: set[str], code: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(code)
    return value


def _hash(value: Any, code: str) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise ValueError(code)
    return value


def _finite(value: Any, code: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(code)


def _ids(value: Any, store: EvidenceStore, code: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(code)
    if len(set(value)) != len(value):
        raise ValueError(code)
    for item in value:
        try:
            store.get(item)
        except ValueError:
            raise ValueError("trajectory_unknown_evidence") from None
    return tuple(value)


def _fingerprint_set(value: Any, code: str) -> frozenset[str]:
    if not isinstance(value, frozenset):
        raise ValueError(code)
    for item in value:
        _hash(item, code)
    return value


def request_fingerprint(request: dict) -> str:
    """Hash normalized question/history independently of IDs/options/scopes."""
    if validate_request(request):
        raise ValueError("invalid_training_request")
    normalize = lambda text: " ".join(unicodedata.normalize("NFKC", text).split())
    return digest({
        "fingerprint_version": "conversation-content-v1",
        "question": normalize(request["question"]),
        "history": [{"role": turn["role"], "content": normalize(turn["content"])}
                    for turn in request["history"]],
    })


def _action(value: Any) -> Action:
    _shape(value, {"kind", "slot_key", "query", "evidence_id"}, "trajectory_action_invalid")
    try:
        return Action(**value)
    except (ValueError, TypeError):
        raise ValueError("trajectory_action_invalid") from None


def _plan(value: Any, request: dict) -> QueryPlan:
    _shape(value, {"query", "slots", "query_type", "history", "allowed_doc_ids"}, "trajectory_plan_invalid")
    if not isinstance(value["slots"], list) or not isinstance(value["history"], list):
        raise ValueError("trajectory_plan_invalid")
    slots = []
    for row in value["slots"]:
        _shape(row, {"key", "query", "doc_id", "kind"}, "trajectory_plan_invalid")
        slots.append(Slot(**row))
    expected_history = [[t["role"], t["content"]] for t in request["history"]]
    scope = request["document_scope"]
    expected_scope = sorted(scope["doc_ids"]) if scope["mode"] == "explicit" else None
    if (value["query"] != request["question"] or value["history"] != expected_history
            or value["allowed_doc_ids"] != expected_scope):
        raise ValueError("trajectory_request_mismatch")
    try:
        return QueryPlan(value["query"], tuple(slots), value["query_type"],
                         tuple(tuple(t) for t in value["history"]),
                         frozenset(expected_scope) if expected_scope is not None else None)
    except (ValueError, TypeError):
        raise ValueError("trajectory_plan_invalid") from None


def _state(value: Any, *, request: dict, store: EvidenceStore, config: HarnessConfig) -> dict:
    if value is None:
        raise ValueError("trajectory_state_missing")
    _shape(value, _STATE_FIELDS, "trajectory_state_invalid")
    plan = _plan(value["plan"], request)
    slot_map = {slot.key: slot for slot in plan.slots}
    candidate_ids = _ids(value["candidate_ids"], store, "trajectory_candidates_invalid")
    if plan.allowed_doc_ids is not None and any(store.get(i).doc_id not in plan.allowed_doc_ids for i in candidate_ids):
        raise ValueError("trajectory_scope_violation")
    verified: dict[str, tuple[str, ...]] = {}
    if not isinstance(value["verified"], list):
        raise ValueError("trajectory_verified_invalid")
    for pair in value["verified"]:
        if (not isinstance(pair, list) or len(pair) != 2 or not isinstance(pair[0], str)
                or pair[0] not in slot_map or pair[0] in verified):
            raise ValueError("trajectory_verified_invalid")
        ids = _ids(pair[1], store, "trajectory_verified_invalid")
        if not ids or not set(ids).issubset(candidate_ids):
            raise ValueError("trajectory_verified_invalid")
        slot = slot_map[pair[0]]
        for item in ids:
            ev = store.get(item)
            if (slot.doc_id is not None and ev.doc_id != slot.doc_id) or (slot.kind is not None and ev.kind != slot.kind):
                raise ValueError("trajectory_scope_violation")
        verified[pair[0]] = ids
    if value["missing"] != [s.key for s in plan.slots if s.key not in verified]:
        raise ValueError("trajectory_missing_mismatch")
    if not isinstance(value["rounds"], list) or len(value["rounds"]) != len(slot_map):
        raise ValueError("trajectory_rounds_invalid")
    rounds = {}
    for pair in value["rounds"]:
        if (not isinstance(pair, list) or len(pair) != 2 or not isinstance(pair[0], str)
                or pair[0] not in slot_map or pair[0] in rounds
                or type(pair[1]) is not int or not 0 <= pair[1] <= config.max_rounds):
            raise ValueError("trajectory_rounds_invalid")
        rounds[pair[0]] = pair[1]
    spent = value["actions_spent"]
    if type(spent) is not int or not 0 <= spent <= config.max_actions:
        raise ValueError("trajectory_actions_invalid")
    contradictions = value["contradictions"]
    if (not isinstance(contradictions, list) or any(not isinstance(i, str) or i not in slot_map for i in contradictions)
            or len(set(contradictions)) != len(contradictions)):
        raise ValueError("trajectory_contradictions_invalid")
    terminal = value["terminal_reason"]
    if terminal is not None and (not isinstance(terminal, str) or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", terminal) is None):
        raise ValueError("trajectory_terminal_invalid")
    if not isinstance(value["allowed_actions"], list):
        raise ValueError("trajectory_actions_invalid")
    actions = tuple(_action(row) for row in value["allowed_actions"])
    if len(set(actions)) != len(actions):
        raise ValueError("trajectory_actions_invalid")
    if terminal is not None and actions:
        raise ValueError("trajectory_terminal_actions")
    for action in actions:
        if action.slot_key is not None and action.slot_key not in slot_map:
            raise ValueError("trajectory_action_slot_invalid")
        if action.kind == "stop" and (value["missing"] or contradictions):
            raise ValueError("trajectory_premature_stop")
        if action.kind == "bridge":
            page = store.get(action.evidence_id)
            if page.kind != "page":
                raise ValueError("trajectory_bridge_invalid")
            slot = slot_map[action.slot_key]
            if (plan.allowed_doc_ids is not None and page.doc_id not in plan.allowed_doc_ids) or (slot.doc_id and page.doc_id != slot.doc_id):
                raise ValueError("trajectory_scope_violation")
    return {"raw": value, "plan": plan, "verified": verified, "rounds": rounds, "actions": actions}


def _harness_result(trace: dict) -> dict:
    result = trace["result"]
    if isinstance(result, dict) and set(result) == {"harness", "answer"}:
        answer = result["answer"]
        _shape(answer, {"response", "usage", "citation_map", "prompt_sha256", "terminal_reason"}, "trajectory_answer_invalid")
        if validate_response(answer["response"]):
            raise ValueError("trajectory_answer_invalid")
        result = result["harness"]
    return _shape(result, {"status", "reason", "context", "required_ids", "state", "events", "elapsed_ms"}, "trajectory_result_invalid")


def export_training_rows(
    trace: dict, *, store: EvidenceStore, training_allowlist: frozenset[str],
    heldout_fingerprints: frozenset[str], allow_synthetic: bool = False,
) -> dict:
    """Validate an action trajectory and prepare unapproved SFT/RL records.

    Legacy traces without decision snapshots fail closed. The exporter does not
    reconstruct missing state from the final state or infer rewards from status.
    """
    _shape(trace, _TRACE_FIELDS, "training_trace_invalid")
    if trace["schema_version"] != "evidence-harness-trace-v1":
        raise ValueError("training_trace_schema_unsupported")
    claimed_hash = _hash(trace["trace_sha256"], "invalid_trace_sha256")
    try:
        if digest({k: v for k, v in trace.items() if k != "trace_sha256"}) != claimed_hash:
            raise ValueError("trace_sha256_mismatch")
    except (TypeError, OverflowError):
        raise ValueError("training_trace_invalid") from None
    if type(allow_synthetic) is not bool or type(trace["synthetic"]) is not bool:
        raise ValueError("invalid_synthetic_marker")
    if trace["official"] is not False or trace["experience_enabled"] is not False:
        raise ValueError("official_or_online_experience_trace_forbidden")
    if trace["synthetic"] and not allow_synthetic:
        raise ValueError("synthetic_training_trace_forbidden")
    if not isinstance(trace["policy_id"], str) or not trace["policy_id"].strip():
        raise ValueError("training_policy_invalid")
    if not isinstance(trace["provider_calls"], list) or any(not isinstance(c, dict) for c in trace["provider_calls"]):
        raise ValueError("training_provider_calls_invalid")
    explicitly_synthetic = "synthetic" in trace["policy_id"].lower() or any(
        isinstance(c.get("model"), str) and "synthetic" in c["model"].lower() for c in trace["provider_calls"])
    if explicitly_synthetic and not trace["synthetic"]:
        raise ValueError("synthetic_marker_missing")
    train = _fingerprint_set(training_allowlist, "invalid_training_allowlist")
    heldout = _fingerprint_set(heldout_fingerprints, "invalid_heldout_fingerprints")
    if not train or not heldout:
        raise ValueError("explicit_train_and_heldout_sets_required")
    if train & heldout:
        raise ValueError("training_heldout_overlap")
    fingerprint = request_fingerprint(trace["request"])
    if fingerprint in heldout:
        raise ValueError("heldout_training_trace_forbidden")
    if fingerprint not in train:
        raise ValueError("request_not_allowlisted_for_training")
    if not isinstance(store, EvidenceStore) or digest(store.to_dict()) != trace["evidence_sha256"]:
        raise ValueError("training_evidence_seal_mismatch")
    _shape(trace["config"], {field.name for field in fields(HarnessConfig)}, "training_config_invalid")
    try:
        config = HarnessConfig(**trace["config"])
    except (ValueError, TypeError):
        raise ValueError("training_config_invalid") from None
    if digest(trace["config"]) != trace["config_sha256"]:
        raise ValueError("training_config_seal_mismatch")
    result = _harness_result(trace)
    # An exporter target must be a completed, evidence-backed episode.  Error
    # and abstention episodes remain useful operational diagnostics, but they
    # are not silently promoted into policy-training targets by this helper.
    if result["status"] != "READY":
        raise ValueError("error_trajectory_not_training_ready")
    _finite(result["elapsed_ms"], "trajectory_time_invalid")
    final = _state(result["state"], request=trace["request"], store=store, config=config)
    if final["raw"]["terminal_reason"] != result["reason"]:
        raise ValueError("trajectory_terminal_mismatch")
    required = _ids(result["required_ids"], store, "trajectory_required_invalid")
    if required != tuple(dict.fromkeys(i for ids in final["verified"].values() for i in ids)):
        raise ValueError("trajectory_required_mismatch")
    if not isinstance(result["context"], list):
        raise ValueError("trajectory_context_invalid")
    context = tuple(Evidence.from_dict(row) for row in result["context"])
    if (len({e.evidence_id for e in context}) != len(context)
            or any(e != store.get(e.evidence_id) for e in context)):
        raise ValueError("trajectory_context_invalid")
    if result["status"] == "READY":
        if (final["raw"]["missing"] or final["raw"]["contradictions"]
                or not required or not set(required).issubset(e.evidence_id for e in context)):
            raise ValueError("trajectory_ready_without_support")
    # The status check above intentionally makes this branch unreachable.  Keep
    # the context assertion next to the READY invariant so a future status
    # extension cannot accidentally export an unsupported episode.
    events = result["events"]
    if not isinstance(events, list) or not 1 <= len(events) <= config.max_actions:
        raise ValueError("trajectory_events_missing")
    if len(events) != final["raw"]["actions_spent"]:
        raise ValueError("trajectory_actions_missing")
    rows = []
    previous = None
    for index, event in enumerate(events):
        if not isinstance(event, dict) or event.get("state_before") is None or event.get("state_after") is None:
            raise ValueError("trajectory_state_missing")
        _shape(event, _EVENT_FIELDS, "trajectory_event_invalid")
        _finite(event["elapsed_ms"], "trajectory_time_invalid")
        before = _state(event["state_before"], request=trace["request"], store=store, config=config)
        after = _state(event["state_after"], request=trace["request"], store=store, config=config)
        if previous is not None and before["raw"] != previous:
            raise ValueError("trajectory_chronology_mismatch")
        if index == 0 and (before["raw"]["actions_spent"] != 0 or before["verified"]
                           or before["raw"]["candidate_ids"] or any(before["rounds"].values())):
            raise ValueError("trajectory_initial_state_invalid")
        if before["raw"]["terminal_reason"] is not None:
            raise ValueError("trajectory_action_after_terminal")
        if (after["raw"]["actions_spent"] != before["raw"]["actions_spent"] + 1
                or before["raw"]["plan"] != after["raw"]["plan"]):
            raise ValueError("trajectory_transition_invalid")
        action = _action(event["action"])
        legal = action in before["actions"]
        if action.kind == "search":
            legal = any(a.kind == "search" and a.slot_key == action.slot_key for a in before["actions"])
        if not legal:
            raise ValueError("trajectory_illegal_action")
        candidate_ids = _ids(event["candidate_ids"], store, "trajectory_candidates_invalid")
        verified_ids = _ids(event["verified_ids"], store, "trajectory_verified_invalid")
        pre_rerank = _ids(event["pre_rerank_ids"], store, "trajectory_candidates_invalid")
        # ``max_candidates`` is the per-search/bridge ceiling.  Do not let a
        # larger context budget accidentally widen the trajectory action
        # budget; otherwise a forged trace could train on unbounded batches.
        if len(candidate_ids) > config.max_candidates:
            raise ValueError("trajectory_candidate_limit")
        if not set(verified_ids).issubset(candidate_ids) or type(event["contradiction"]) is not bool:
            raise ValueError("trajectory_verification_invalid")
        slots = {s.key: s for s in before["plan"].slots}
        if action.slot_key is not None:
            slot = slots[action.slot_key]
            for evidence_id in (*candidate_ids, *pre_rerank):
                ev = store.get(evidence_id)
                if ((slot.doc_id is not None and ev.doc_id != slot.doc_id)
                        or (before["plan"].allowed_doc_ids is not None and ev.doc_id not in before["plan"].allowed_doc_ids)):
                    raise ValueError("trajectory_scope_violation")
        if not isinstance(event["ranks"], list):
            raise ValueError("trajectory_rank_invalid")
        for rank in event["ranks"]:
            if (not isinstance(rank, list) or len(rank) != 4 or not isinstance(rank[1], str)
                    or not rank[1] or type(rank[2]) is not int or rank[2] < 1):
                raise ValueError("trajectory_rank_invalid")
            _ids([rank[0]], store, "trajectory_rank_invalid")
            if isinstance(rank[3], bool) or not isinstance(rank[3], (int, float)) or not math.isfinite(rank[3]):
                raise ValueError("trajectory_rank_invalid")
        expected_rounds = dict(before["rounds"])
        expected_verified = dict(before["verified"])
        if action.kind == "search":
            expected_rounds[action.slot_key] += 1
            if not set(candidate_ids).issubset(pre_rerank) or verified_ids or event["contradiction"]:
                raise ValueError("trajectory_search_invalid")
        elif action.kind == "verify":
            if not set(candidate_ids).issubset(before["raw"]["candidate_ids"]):
                raise ValueError("trajectory_verification_invalid")
            if after["raw"]["candidate_ids"] != before["raw"]["candidate_ids"]:
                raise ValueError("trajectory_verification_invalid")
            if verified_ids and not event["contradiction"]:
                expected_verified[action.slot_key] = verified_ids
        elif verified_ids or event["contradiction"]:
            raise ValueError("trajectory_verification_invalid")
        if after["rounds"] != expected_rounds or after["verified"] != expected_verified:
            raise ValueError("trajectory_transition_invalid")
        # Search and bridge actions add/replace candidates in the aggregate
        # snapshot; verify/terminal actions cannot invent an aggregate set.
        if action.kind in ("search", "bridge") and not set(candidate_ids).issubset(after["raw"]["candidate_ids"]):
            raise ValueError("trajectory_transition_invalid")
        if action.kind in ("stop",) and not set(candidate_ids).issubset(after["raw"]["candidate_ids"]):
            raise ValueError("trajectory_transition_invalid")
        if action.kind == "bridge":
            page = store.get(action.evidence_id)
            linked = {e.evidence_id for e in store.bridge(page.evidence_id)}
            if not set(candidate_ids).issubset(linked | set(before["raw"]["candidate_ids"])):
                raise ValueError("trajectory_bridge_invalid")
        if event["contradiction"] and action.slot_key not in after["raw"]["contradictions"]:
            raise ValueError("trajectory_contradiction_missing")
        terminal = index == len(events) - 1
        if not terminal and (after["raw"]["terminal_reason"] is not None or action.kind in ("stop", "abstain")):
            raise ValueError("trajectory_early_terminal")
        if terminal and after["raw"] != final["raw"]:
            raise ValueError("trajectory_final_state_mismatch")
        rows.append({
            "transition_id": digest([claimed_hash, index]), "trace_sha256": claimed_hash,
            "request_fingerprint": fingerprint, "step": index,
            "state": copy.deepcopy(before["raw"]),
            "allowed_actions": copy.deepcopy(before["raw"]["allowed_actions"]),
            "chosen_action": copy.deepcopy(event["action"]),
            "next_state": copy.deepcopy(after["raw"]),
            "next_observation": {key: copy.deepcopy(event[key]) for key in (
                "candidate_ids", "verified_ids", "pre_rerank_ids", "ranks", "elapsed_ms", "contradiction")},
            "done": terminal,
        })
        previous = after["raw"]
    sft = [{**copy.deepcopy(row), "target_status": "observed_action_requires_expert_approval"} for row in rows]
    rl = [{**copy.deepcopy(row), "reward": None, "reward_status": "external_approved_receipt_required"} for row in rows]
    return {
        "schema_version": "evidence-harness-training-preparation-v1",
        "preparation_only": True, "ready_for_training": False, "learned_checkpoint": None,
        "synthetic": trace["synthetic"], "official": False,
        "trace_sha256": claimed_hash, "request_fingerprint": fingerprint,
        # Keep both names: ``manifest_sha256`` is the public preparation
        # contract, while the split-specific alias is retained for callers
        # that want to make the train/heldout nature explicit.
        "manifest_sha256": digest({"training": sorted(train), "heldout": sorted(heldout)}),
        "split_manifest_sha256": digest({"training": sorted(train), "heldout": sorted(heldout)}),
        "evidence_sha256": trace["evidence_sha256"], "config_sha256": trace["config_sha256"],
        "policy_id": trace["policy_id"], "sft_rows": sft, "rl_rows": rl,
        "readiness": "requires_expert_action_approval_and_external_reward_receipt",
    }


def validate_evolution_candidate(baseline_manifest: dict, candidate_manifest: dict) -> dict:
    """Check immutable seals; this never executes or approves candidate code."""
    keys = {"schema_version", "policy_code_sha256", *_SEALS}
    for manifest in (baseline_manifest, candidate_manifest):
        _shape(manifest, keys, "evolution_manifest_invalid")
        if manifest["schema_version"] != "evidence-harness-evolution-manifest-v1":
            raise ValueError("evolution_manifest_schema_unsupported")
        for key in _SEALS | {"policy_code_sha256"}:
            _hash(manifest[key], "evolution_manifest_hash_invalid")
    if any(baseline_manifest[key] != candidate_manifest[key] for key in _SEALS):
        raise ValueError("evolution_immutable_artifact_changed")
    return {
        "schema_version": "evidence-harness-evolution-gate-v1",
        "preparation_only": True, "eligible_for_offline_evaluation": True,
        "approved_for_runtime": False, "executed": False,
        "policy_changed": baseline_manifest["policy_code_sha256"] != candidate_manifest["policy_code_sha256"],
        "baseline_manifest_sha256": digest(baseline_manifest),
        "candidate_manifest_sha256": digest(candidate_manifest),
        "readiness": "sealed_candidate_requires_external_evaluation",
    }
