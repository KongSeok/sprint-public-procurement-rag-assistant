"""Scope-safe reciprocal-rank fusion for explicit retrieval lanes."""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from midprojectrag.evidence import EvidenceStore
from midprojectrag.retrieval.types import (
    Candidate,
    Retriever,
    positive_int,
    validate_candidates,
    validate_lane,
    validate_query,
    validate_scope,
)


@dataclass(frozen=True)
class HybridSearchResult:
    candidates: tuple[Candidate, ...]
    by_lane: tuple[tuple[str, tuple[Candidate, ...]], ...]


class HybridRetriever:
    """Fuses enabled lanes; an absent visual lane never silently activates one.

    Lane results are validated, re-scoped, deduplicated, and re-ranked before
    fusion. Per-lane results are returned by search_with_lanes for private
    diagnostics without mutable last-search state or cross-request leakage.
    """

    def __init__(
        self,
        store: EvidenceStore,
        lanes: Mapping[str, Retriever],
        rrf_k: int = 60,
    ) -> None:
        self._store = store
        self.rrf_k = positive_int(rrf_k, "invalid_rrf_k")
        if not isinstance(lanes, Mapping) or not lanes:
            raise ValueError("invalid_retrieval_lanes")
        validated = []
        seen: set[str] = set()
        for lane, retriever in lanes.items():
            validate_lane(lane)
            if lane in seen or not callable(getattr(retriever, "search", None)):
                raise ValueError("invalid_retrieval_lanes")
            seen.add(lane)
            validated.append((lane, retriever))
        self._lanes = tuple(sorted(validated, key=lambda item: item[0]))

    @property
    def lane_names(self) -> tuple[str, ...]:
        return tuple(lane for lane, _ in self._lanes)

    def search(
        self,
        query: str,
        *,
        limit: int,
        allowed_doc_ids: frozenset[str] | None = None,
    ) -> tuple[Candidate, ...]:
        return self.search_with_lanes(
            query, limit=limit, allowed_doc_ids=allowed_doc_ids
        ).candidates

    def search_with_lanes(
        self,
        query: str,
        *,
        limit: int,
        allowed_doc_ids: frozenset[str] | None = None,
    ) -> HybridSearchResult:
        validate_query(query)
        positive_int(limit, "invalid_retrieval_limit")
        scope = validate_scope(allowed_doc_ids)
        if scope == frozenset():
            return HybridSearchResult((), tuple((lane, ()) for lane, _ in self._lanes))
        contributions: dict[str, list[float]] = {}
        lane_results: list[tuple[str, tuple[Candidate, ...]]] = []
        for lane, retriever in self._lanes:
            hits = validate_candidates(
                retriever.search(query, limit=limit, allowed_doc_ids=scope)
            )
            if len(hits) > limit:
                raise ValueError("retrieval_lane_limit_exceeded")
            seen: set[str] = set()
            scoped = []
            for hit in sorted(hits, key=lambda item: (item.rank, item.evidence_id)):
                if hit.lane != lane:
                    raise ValueError("retrieval_lane_identity_mismatch")
                evidence = self._store.get(hit.evidence_id)
                if scope is not None and evidence.doc_id not in scope:
                    continue
                if hit.evidence_id in seen:
                    continue
                seen.add(hit.evidence_id)
                rank = len(scoped) + 1
                scoped.append(Candidate(hit.evidence_id, hit.score, lane, rank))
                contributions.setdefault(hit.evidence_id, []).append(1.0 / (self.rrf_k + rank))
            lane_results.append((lane, tuple(scoped)))
        fused = sorted(
            ((evidence_id, math.fsum(parts)) for evidence_id, parts in contributions.items()),
            key=lambda item: (-item[1], item[0]),
        )
        return HybridSearchResult(
            tuple(
                Candidate(evidence_id, score, "hybrid", rank)
                for rank, (evidence_id, score) in enumerate(fused[:limit], 1)
            ),
            tuple(lane_results),
        )
