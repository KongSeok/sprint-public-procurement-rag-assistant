"""Provider-neutral, evidence-addressed retrieval contracts."""
from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real
from typing import Protocol


def positive_int(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(code)
    return value


def validate_query(query: object) -> str:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("invalid_retrieval_query")
    return query


def validate_scope(scope: object) -> frozenset[str] | None:
    if scope is None:
        return None
    if not isinstance(scope, frozenset) or any(
        not isinstance(doc_id, str) or not doc_id.strip() for doc_id in scope
    ):
        raise ValueError("invalid_retrieval_scope")
    return scope


def validate_lane(lane: object) -> str:
    if not isinstance(lane, str) or not lane.strip() or len(lane) > 80:
        raise ValueError("invalid_retrieval_lane")
    return lane


@dataclass(frozen=True)
class Candidate:
    evidence_id: str
    score: float
    lane: str
    rank: int

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_id, str) or not self.evidence_id.strip():
            raise ValueError("invalid_candidate_evidence_id")
        if (
            isinstance(self.score, bool)
            or not isinstance(self.score, Real)
            or not math.isfinite(self.score)
        ):
            raise ValueError("invalid_candidate_score")
        validate_lane(self.lane)
        positive_int(self.rank, "invalid_candidate_rank")


class Retriever(Protocol):
    def search(
        self,
        query: str,
        *,
        limit: int,
        allowed_doc_ids: frozenset[str] | None = None,
    ) -> tuple[Candidate, ...]: ...


class Reranker(Protocol):
    def rerank(
        self, query: str, candidates: tuple[Candidate, ...]
    ) -> tuple[Candidate, ...]: ...


def validate_candidates(candidates: object) -> tuple[Candidate, ...]:
    if not isinstance(candidates, tuple) or any(
        not isinstance(candidate, Candidate) for candidate in candidates
    ):
        raise ValueError("invalid_retrieval_candidates")
    # Recheck frozen objects at adapter boundaries, including deserialized or
    # externally constructed instances which may have bypassed __init__.
    for candidate in candidates:
        candidate.__post_init__()
    return candidates


def validate_reranked(
    original: tuple[Candidate, ...], reranked: tuple[Candidate, ...]
) -> tuple[Candidate, ...]:
    """A reranker may reorder or drop supplied refs, but cannot invent support."""
    validate_candidates(original)
    validate_candidates(reranked)
    allowed = {candidate.evidence_id for candidate in original}
    seen: set[str] = set()
    for candidate in reranked:
        if candidate.evidence_id not in allowed:
            raise ValueError("reranker_unknown_evidence")
        if candidate.evidence_id in seen:
            raise ValueError("reranker_duplicate_evidence")
        seen.add(candidate.evidence_id)
    return reranked


class IdentityReranker:
    """Explicit no-op comparison policy; this is NOT a learned reranker."""

    policy_id = "identity-reranker-v1"
    is_learned = False

    def rerank(
        self, query: str, candidates: tuple[Candidate, ...]
    ) -> tuple[Candidate, ...]:
        validate_query(query)
        return validate_reranked(candidates, candidates)
