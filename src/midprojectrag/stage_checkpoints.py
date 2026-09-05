"""Content-free offline stage projections; these do not certify live authority."""
from __future__ import annotations

from hashlib import sha256
import json
from typing import Any

from midprojectrag.evidence import EvidenceStore, validate_evidence_store_snapshot
from midprojectrag.retrieval.context import ContextPack


SCHEMA = "stage-evaluation-v1"
STAGES = {
    "lane_dense": 1, "lane_lexical": 2, "lane_visual": 3,
    "fusion": 4, "rerank": 5, "final_context": 6,
}
_BINDING_FIELDS = frozenset({
    "query_sha256", "scope_sha256", "evidence_store_sha256",
    "run_config_sha256", "execution_key_sha256",
})
_CHECKPOINT_FIELDS = frozenset({
    "schema_version", "stage", "stage_ordinal", "binding",
    "stage_config_sha256", "source_receipt_sha256", "ordered_evidence_ids",
    "ordered_stable_anchors", "candidate_count", "call_performed", "outcome",
    "projection_sha256",
})


def canonical_sha(value: Any) -> str:
    return sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _hash(value: object) -> None:
    if (type(value) is not str or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise ValueError("invalid_stage_sha256")


def _identifier(value: object) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError("invalid_stage_identifier")


def _binding(value: object) -> dict[str, str]:
    if type(value) is not dict or set(value) != _BINDING_FIELDS:
        raise ValueError("invalid_stage_binding")
    for digest in value.values():
        _hash(digest)
    return dict(value)


def source_block_anchor_sha(doc_id: str, block_id: str) -> str:
    _identifier(doc_id)
    _identifier(block_id)
    return canonical_sha({
        "schema_version": "1.0", "anchor_kind": "source_block",
        "doc_id": doc_id, "source_block_id": block_id,
    })


def stable_projection(store: EvidenceStore, evidence_id: str) -> dict[str, Any]:
    """Read only identity fields, never source text or gold labels."""
    if type(store) is not EvidenceStore:
        raise TypeError("stage_evidence_store_required")
    _identifier(evidence_id)
    try:
        evidence = EvidenceStore.get(store, evidence_id)
    except KeyError as exc:
        raise ValueError("stage_evidence_missing") from exc
    return {
        "doc_id": evidence.doc_id,
        "source_block_ids": list(evidence.source_block_ids),
        "source_block_anchor_sha256s": [
            source_block_anchor_sha(evidence.doc_id, block_id)
            for block_id in evidence.source_block_ids
        ],
        "evidence_kind": evidence.kind,
    }


def make_checkpoint(
    stage: str, ordered_evidence_ids: list[str] | tuple[str, ...], *,
    store: EvidenceStore, binding: dict[str, str], stage_config_sha256: str,
    source_receipt_sha256: str, call_performed: bool = True, outcome: str = "ok",
) -> dict[str, Any]:
    if type(stage) is not str or stage not in STAGES:
        raise ValueError("invalid_checkpoint_stage")
    if type(ordered_evidence_ids) not in (list, tuple):
        raise ValueError("invalid_checkpoint_evidence_ids")
    ids = list(ordered_evidence_ids)
    for evidence_id in ids:
        _identifier(evidence_id)
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate_checkpoint_evidence")
    frozen_binding = _binding(binding)
    _hash(stage_config_sha256)
    _hash(source_receipt_sha256)
    if type(call_performed) is not bool:
        raise ValueError("invalid_checkpoint_call_performed")
    if type(outcome) is not str or outcome not in {"ok", "unavailable", "error"}:
        raise ValueError("invalid_checkpoint_outcome")
    if (outcome == "ok" and not call_performed) or (outcome != "ok" and ids):
        raise ValueError("checkpoint_outcome_candidates_mismatch")
    if type(store) is not EvidenceStore:
        raise TypeError("stage_evidence_store_required")
    validate_evidence_store_snapshot(store, frozen_binding["evidence_store_sha256"])
    payload = {
        "schema_version": SCHEMA, "stage": stage, "stage_ordinal": STAGES[stage],
        "binding": frozen_binding, "stage_config_sha256": stage_config_sha256,
        "source_receipt_sha256": source_receipt_sha256,
        "ordered_evidence_ids": ids,
        "ordered_stable_anchors": [stable_projection(store, item) for item in ids],
        "candidate_count": len(ids), "call_performed": call_performed,
        "outcome": outcome,
    }
    return {**payload, "projection_sha256": canonical_sha(payload)}


def validate_checkpoint(
    checkpoint: dict[str, Any], store: EvidenceStore,
    expected_binding: dict[str, str],
) -> None:
    if type(checkpoint) is not dict or set(checkpoint) != _CHECKPOINT_FIELDS:
        raise ValueError("invalid_checkpoint_fields")
    if checkpoint["schema_version"] != SCHEMA:
        raise ValueError("invalid_checkpoint_schema")
    if type(checkpoint["stage_ordinal"]) is not int:
        raise ValueError("invalid_checkpoint_ordinal")
    if type(checkpoint["candidate_count"]) is not int:
        raise ValueError("invalid_checkpoint_count")
    if (type(checkpoint["ordered_evidence_ids"]) is not list
            or type(checkpoint["ordered_stable_anchors"]) is not list):
        raise ValueError("invalid_checkpoint_arrays")
    expected = _binding(expected_binding)
    if _binding(checkpoint["binding"]) != expected:
        raise ValueError("checkpoint_binding_mismatch")
    _hash(checkpoint["projection_sha256"])
    rebuilt = make_checkpoint(
        checkpoint["stage"], checkpoint["ordered_evidence_ids"], store=store,
        binding=expected, stage_config_sha256=checkpoint["stage_config_sha256"],
        source_receipt_sha256=checkpoint["source_receipt_sha256"],
        call_performed=checkpoint["call_performed"], outcome=checkpoint["outcome"],
    )
    if checkpoint != rebuilt:
        raise ValueError("checkpoint_projection_mismatch")


def _runtime_anchor(store: EvidenceStore, evidence_id: str) -> dict[str, Any]:
    evidence = EvidenceStore.get(store, evidence_id)
    payload = {
        "schema_version": "1.0", **stable_projection(store, evidence_id),
        "locator_identity_sha256": canonical_sha(evidence.locator.to_dict()),
    }
    return {**payload, "anchor_sha256": canonical_sha(payload)}


def checkpoint_from_receipt(receipt: object, *, store: EvidenceStore) -> dict[str, Any]:
    """Project exact receipt DTOs after offline hash/store checks, not live replay."""
    from midprojectrag.orchestration import FusionReceipt, LaneSearchReceipt

    if type(receipt) not in (LaneSearchReceipt, FusionReceipt):
        raise TypeError("stage_lane_or_fusion_receipt_required")
    payload = type(receipt).to_dict(receipt)
    binding = {
        "query_sha256": payload["query_sha256"],
        "scope_sha256": payload["scope_sha256"],
        "evidence_store_sha256": payload["evidence_store_sha256"],
        "run_config_sha256": payload["execution_config_sha256"],
        "execution_key_sha256": canonical_sha({
            key: payload[key] for key in (
                "execution_binding_sha256", "obligation_sha256", "round_index",
            )
        }),
    }
    ids = payload["ordered_evidence_ids"]
    checkpoint = make_checkpoint(
        payload["stage"], ids, store=store, binding=binding,
        stage_config_sha256=payload["retrieval_config_sha256"],
        source_receipt_sha256=payload["receipt_sha256"],
        call_performed=payload["call_performed"],
        outcome="ok" if payload["outcome"] in {"applied", "empty"} else "error",
    )
    if (payload["candidate_count"] != len(ids)
            or payload["ordered_stable_anchors"] != [_runtime_anchor(store, item) for item in ids]):
        raise ValueError("source_receipt_evidence_mismatch")
    return checkpoint


def final_context_checkpoint(
    context: ContextPack, *, store: EvidenceStore, binding: dict[str, str],
    stage_config_sha256: str, source_receipt_sha256: str,
) -> dict[str, Any]:
    """Project selected IDs; parent windows and their text remain private."""
    if type(context) is not ContextPack:
        raise TypeError("stage_context_pack_required")
    if type(store) is not EvidenceStore:
        raise TypeError("stage_evidence_store_required")
    if context.trace.get("bundle_sha256") != store.bundle_sha256:
        raise ValueError("context_store_hash_mismatch")
    if "post_count" in context.trace and (
        type(context.trace["post_count"]) is not int
        or context.trace["post_count"] != len(context.evidence_ids)
    ):
        raise ValueError("context_selected_count_mismatch")
    return make_checkpoint(
        "final_context", context.evidence_ids, store=store, binding=binding,
        stage_config_sha256=stage_config_sha256,
        source_receipt_sha256=source_receipt_sha256,
    )
