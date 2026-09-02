"""Offline stage diagnostics over an immutable run and explicit frozen labels.

This module must not be imported by runtime orchestration. It performs set-based
retrieval accounting, never semantic answer judging or automatic error grading.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from midprojectrag.evidence import Evidence, EvidenceStore
from midprojectrag.orchestration.types import Action, Event, HarnessResult, Snapshot


def _ids(value: object, code: str, *, frozen: bool = False) -> None:
    expected_type = frozenset if frozen else tuple
    if not isinstance(value, expected_type) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(code)


@dataclass(frozen=True)
class FrozenQrels:
    """Explicit label sets; None/empty means recall is not defined, not zero.

    The fingerprint identifies these labels, but does not assert human approval,
    source provenance, or benchmark sealing. Those are separate promotion gates.
    """

    required_evidence_ids: frozenset[str] | None = None
    required_doc_ids: frozenset[str] | None = None

    def __post_init__(self) -> None:
        for values in (self.required_evidence_ids, self.required_doc_ids):
            if values is not None:
                _ids(values, "invalid_frozen_qrels", frozen=True)

    @property
    def fingerprint_sha256(self) -> str:
        payload = {
            "required_evidence_ids": sorted(self.required_evidence_ids)
            if self.required_evidence_ids is not None else None,
            "required_doc_ids": sorted(self.required_doc_ids)
            if self.required_doc_ids is not None else None,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True)
class RecallMeasurement:
    status: str
    value: float | None
    matched_count: int | None
    required_count: int | None
    reason: str | None = None


@dataclass(frozen=True)
class DocumentRecallAtK:
    k: int
    before_rerank: RecallMeasurement
    after_rerank: RecallMeasurement


@dataclass(frozen=True)
class SearchDiagnostic:
    event_index: int
    slot_key: str
    before_rerank_ids: tuple[str, ...]
    after_rerank_ids: tuple[str, ...]
    required_evidence_recall_before_rerank: RecallMeasurement
    required_evidence_recall_after_rerank: RecallMeasurement
    required_dropped_by_rerank_ids: tuple[str, ...] | None
    document_recall_at_k: tuple[DocumentRecallAtK, ...]


@dataclass(frozen=True)
class HarnessDiagnostics:
    schema_version: str
    qrels_fingerprint_sha256: str
    runtime_status: str
    runtime_reason: str
    aggregation: str
    required_evidence_recall_before_rerank: RecallMeasurement
    required_evidence_recall_after_rerank: RecallMeasurement
    required_evidence_recall_after_context_selection: RecallMeasurement
    operational_verified_evidence_retention: RecallMeasurement
    iterative_first_seen_document_recall_at_k: tuple[DocumentRecallAtK, ...]
    per_search: tuple[SearchDiagnostic, ...]
    before_rerank_ids: tuple[str, ...]
    after_rerank_ids: tuple[str, ...]
    bridge_candidate_ids: tuple[str, ...]
    final_candidate_ids: tuple[str, ...]
    context_ids: tuple[str, ...]
    required_never_observed_in_retrieval_ids: tuple[str, ...] | None
    required_dropped_by_rerank_ids: tuple[str, ...] | None
    required_rerank_drops_recovered_by_bridge_ids: tuple[str, ...] | None
    required_available_not_in_context_ids: tuple[str, ...] | None
    verified_not_in_context_ids: tuple[str, ...]
    context_produced: bool
    generation_attribution: str

    def to_dict(self) -> dict:
        """JSON-compatible nested structure; identifiers only, no source text."""
        return asdict(self)


def _ordered_union(groups) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for group in groups for item in group))


def _unavailable_reason(required: frozenset[str] | None, known: frozenset[str]) -> str | None:
    if required is None:
        return "qrels_missing"
    if not required:
        return "qrels_empty_recall_undefined"
    if not required.issubset(known):
        return "qrel_mapping_incomplete"
    return None


def _recall(
    observed: tuple[str, ...],
    required: frozenset[str] | None,
    unavailable: str | None,
) -> RecallMeasurement:
    if unavailable is not None:
        return RecallMeasurement("not_available", None, None, None, unavailable)
    assert required
    matched = len(required.intersection(observed))
    return RecallMeasurement("available", matched / len(required), matched, len(required))


def diagnose_harness_result(
    result: HarnessResult,
    store: EvidenceStore,
    qrels: FrozenQrels,
) -> HarnessDiagnostics:
    """Compare exact evidence IDs; no inferred page/child/object equivalence.

    The two pre/post-rerank primary measurements are the union of SEARCH events.
    Bridge results are separate because they never pass through search reranking.
    Iterative document @k is first-seen order across searches, NOT a single ranked
    query; per_search provides conventional one-search document Recall@k.

    Availability-to-context losses are observations, not an automatic diagnosis
    of a defective packer: verification, replacement, abort, or budgets may cause
    them. No runtime status proves generator success or failure.
    """
    if not isinstance(result, HarnessResult) or not isinstance(qrels, FrozenQrels):
        raise ValueError("invalid_diagnostic_input")
    qrels.__post_init__()
    if not isinstance(result.state, Snapshot):
        raise ValueError("invalid_diagnostic_state")
    if not isinstance(result.events, tuple) or any(not isinstance(event, Event) for event in result.events):
        raise ValueError("invalid_diagnostic_events")
    known_evidence = frozenset(evidence.evidence_id for evidence in store.all())
    known_documents = frozenset(evidence.doc_id for evidence in store.all())
    evidence_unavailable = _unavailable_reason(qrels.required_evidence_ids, known_evidence)
    document_unavailable = _unavailable_reason(qrels.required_doc_ids, known_documents)

    def checked(values: object) -> tuple[str, ...]:
        _ids(values, "invalid_runtime_evidence_ids")
        if any(value not in known_evidence for value in values):
            raise ValueError("unknown_runtime_evidence")
        return values

    checked(result.required_ids)
    checked(result.state.candidate_ids)
    if not isinstance(result.context, tuple) or any(not isinstance(evidence, Evidence) for evidence in result.context):
        raise ValueError("invalid_runtime_context")
    context_ids = tuple(evidence.evidence_id for evidence in result.context)
    checked(context_ids)
    if len(set(context_ids)) != len(context_ids):
        raise ValueError("duplicate_runtime_context")
    for evidence in result.context:
        if evidence != store.get(evidence.evidence_id):
            raise ValueError("runtime_context_identity_mismatch")
    for event in result.events:
        if not isinstance(event.action, Action):
            raise ValueError("invalid_diagnostic_action")
        event.action.__post_init__()
        checked(event.pre_rerank_ids)
        checked(event.candidate_ids)
        checked(event.verified_ids)
        if event.action.kind == "search" and not set(event.candidate_ids).issubset(event.pre_rerank_ids):
            raise ValueError("invalid_search_stage_evidence")

    def documents(values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(store.get(value).doc_id for value in values))

    def document_metrics(before: tuple[str, ...], after: tuple[str, ...]) -> tuple[DocumentRecallAtK, ...]:
        before_docs, after_docs = documents(before), documents(after)
        return tuple(
            DocumentRecallAtK(
                k,
                _recall(before_docs[:k], qrels.required_doc_ids, document_unavailable),
                _recall(after_docs[:k], qrels.required_doc_ids, document_unavailable),
            )
            for k in (5, 10, 20, 50)
        )

    def qrel_intersection(values: set[str] | frozenset[str]) -> tuple[str, ...] | None:
        if evidence_unavailable is not None:
            return None
        assert qrels.required_evidence_ids
        return tuple(sorted(qrels.required_evidence_ids.intersection(values)))

    searches = tuple((index, event) for index, event in enumerate(result.events) if event.action.kind == "search")
    before = _ordered_union(event.pre_rerank_ids for _, event in searches)
    after = _ordered_union(event.candidate_ids for _, event in searches)
    bridge = _ordered_union(event.candidate_ids for event in result.events if event.action.kind == "bridge")
    final_candidates = tuple(dict.fromkeys(result.state.candidate_ids))
    required = tuple(dict.fromkeys(result.required_ids))
    verified_retention = _recall(
        context_ids, frozenset(required),
        None if required else "no_runtime_verified_evidence",
    )
    dropped_by_rerank = set(before) - set(after)
    observed_retrieval = set(before) | set(after) | set(bridge)
    # Required IDs may have survived from a previous round and are explicitly
    # eligible for final packing even when absent from the latest candidates.
    available_for_context = set(final_candidates) | set(required)
    per_search = tuple(
        SearchDiagnostic(
            index,
            event.action.slot_key,
            event.pre_rerank_ids,
            event.candidate_ids,
            _recall(event.pre_rerank_ids, qrels.required_evidence_ids, evidence_unavailable),
            _recall(event.candidate_ids, qrels.required_evidence_ids, evidence_unavailable),
            qrel_intersection(set(event.pre_rerank_ids) - set(event.candidate_ids)),
            document_metrics(event.pre_rerank_ids, event.candidate_ids),
        )
        for index, event in searches
    )
    never_observed = (
        None if evidence_unavailable is not None
        else tuple(sorted(qrels.required_evidence_ids - observed_retrieval))
    )
    return HarnessDiagnostics(
        "1.0",
        qrels.fingerprint_sha256,
        result.status,
        result.reason,
        "search_event_union;document_at_k=iterative_first_seen_not_single_ranking;bridge_separate",
        _recall(before, qrels.required_evidence_ids, evidence_unavailable),
        _recall(after, qrels.required_evidence_ids, evidence_unavailable),
        _recall(context_ids, qrels.required_evidence_ids, evidence_unavailable),
        verified_retention,
        document_metrics(before, after),
        per_search,
        before,
        after,
        bridge,
        final_candidates,
        context_ids,
        never_observed,
        qrel_intersection(dropped_by_rerank),
        qrel_intersection(dropped_by_rerank.intersection(bridge)),
        qrel_intersection(available_for_context - set(context_ids)),
        tuple(sorted(set(required) - set(context_ids))),
        result.status == "READY" and bool(context_ids),
        "not_assessed_requires_answer_and_external_semantic_judgment",
    )
