"""Provider-free draft settings for three local retrieval controls.

This is not a frozen evaluation approval or proof of artifact availability.
Validate again at recorder entry; the returned JSON projection is detached.
"""
from __future__ import annotations

from .stage_checkpoints import canonical_sha
from .stage_evaluation import _hash
from .stacks.local.gcp_config import KURE_MODEL_ID, KURE_MODEL_REVISION, KURE_DIMENSIONS

SCHEMA = "retrieval-experiment-draft-v1"
ARTIFACT_KEYS = {"input_inventory", "source_snapshot", "evidence_store", "page_index", "child_dense", "child_lexical"}
ARM_IDS = ("page_kure", "child_kure", "child_bm25_rrf")
QUERY_POLICY = {"policy_id": "legacy_pipeline_retrieval_query_v1", "history_turns": 4,
                "max_input_tokens": 8192, "embedding_model": KURE_MODEL_ID,
                "embedding_revision": KURE_MODEL_REVISION, "dimensions": KURE_DIMENSIONS,
                "query_prompt": ""}


def _closed(value, keys):
    if type(value) is not dict or set(value) != keys:
        raise ValueError("invalid_retrieval_experiment_fields")


def _positive(value):
    if type(value) is not int or value < 1:
        raise ValueError("invalid_retrieval_experiment_budget")


def validate_draft(payload: dict) -> str:
    _closed(payload, {"schema_version", "status", "measurement_kind", "formal_comparison_authorized",
                      "artifact_hashes", "query_policy", "scope_policy", "return_k", "arms", "context",
                      "timing_policy", "config_sha256"})
    if (payload["schema_version"] != SCHEMA or payload["status"] != "draft"
            or payload["measurement_kind"] != "retrieval_only" or payload["formal_comparison_authorized"] is not False):
        raise ValueError("retrieval_draft_not_formal_authority")
    _closed(payload["artifact_hashes"], ARTIFACT_KEYS)
    for value in payload["artifact_hashes"].values():
        _hash(value)
    if (type(payload["query_policy"]) is not dict or payload["query_policy"] != QUERY_POLICY
            or payload["scope_policy"] != "original_user_scope_no_gold_fallback_v1"
            or payload["timing_policy"] != "separate_load_query_build_lane_fusion_context_v1"):
        raise ValueError("retrieval_experiment_common_policy_mismatch")
    if any(type(payload["query_policy"][key]) is not int for key in ("history_turns", "max_input_tokens", "dimensions")):
        raise ValueError("retrieval_query_policy_integer_required")
    _positive(payload["return_k"])
    context = payload["context"]
    _closed(context, {"selector", "final_k", "max_per_doc", "char_budget", "parent_max_chars"})
    if context["selector"] != "shared_select_context_v1":
        raise ValueError("retrieval_context_policy_mismatch")
    for key in ("final_k", "max_per_doc", "char_budget", "parent_max_chars"):
        _positive(context[key])
    if context["max_per_doc"] > context["final_k"] or context["final_k"] > payload["return_k"]:
        raise ValueError("retrieval_context_budget_order")
    arms = payload["arms"]
    if type(arms) is not list or len(arms) != 3:
        raise ValueError("retrieval_experiment_three_arms_required")
    for arm, expected in zip(arms, ARM_IDS):
        _closed(arm, {"arm_id", "granularity", "dense_k", "lexical_k", "rrf_k", "pre_context_stage"})
        hybrid = expected == "child_bm25_rrf"
        if (arm["arm_id"] != expected or arm["granularity"] != ("page" if expected == "page_kure" else "child")
                or arm["pre_context_stage"] != ("fusion" if hybrid else "lane_dense")):
            raise ValueError("retrieval_experiment_arm_mismatch")
        _positive(arm["dense_k"])
        if arm["dense_k"] < payload["return_k"]:
            raise ValueError("retrieval_candidate_budget_order")
        if type(arm["lexical_k"]) is not int:
            raise ValueError("invalid_lexical_budget")
        if hybrid:
            if arm["lexical_k"] < payload["return_k"] or type(arm["rrf_k"]) is not int or arm["rrf_k"] != 60:
                raise ValueError("retrieval_hybrid_budget_mismatch")
        elif arm["lexical_k"] != 0 or arm["rrf_k"] is not None:
            raise ValueError("retrieval_dense_only_has_fusion")
    if len({arm["dense_k"] for arm in arms}) != 1:
        raise ValueError("retrieval_dense_budgets_not_comparable")
    expected_hash = canonical_sha({k: v for k, v in payload.items() if k != "config_sha256"})
    if payload["config_sha256"] != expected_hash:
        raise ValueError("retrieval_experiment_hash_mismatch")
    return expected_hash


def make_draft(artifact_hashes: dict) -> dict:
    """Smoke defaults, not measured winners; does not load artifacts or models."""
    result = {"schema_version": SCHEMA, "status": "draft", "measurement_kind": "retrieval_only",
              "formal_comparison_authorized": False, "artifact_hashes": dict(artifact_hashes),
              "query_policy": dict(QUERY_POLICY), "scope_policy": "original_user_scope_no_gold_fallback_v1",
              "return_k": 10, "arms": [
                  {"arm_id": name, "granularity": "page" if name == "page_kure" else "child",
                   "dense_k": 50, "lexical_k": 50 if name == "child_bm25_rrf" else 0,
                   "rrf_k": 60 if name == "child_bm25_rrf" else None,
                   "pre_context_stage": "fusion" if name == "child_bm25_rrf" else "lane_dense"}
                  for name in ARM_IDS],
              "context": {"selector": "shared_select_context_v1", "final_k": 5, "max_per_doc": 5,
                          "char_budget": 12000, "parent_max_chars": 2400},
              "timing_policy": "separate_load_query_build_lane_fusion_context_v1"}
    result["config_sha256"] = canonical_sha(result)
    validate_draft(result)
    return result
