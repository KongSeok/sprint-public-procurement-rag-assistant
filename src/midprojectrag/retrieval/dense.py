"""Exact cosine retrieval over caller-supplied evidence-aligned embeddings."""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from numbers import Real

from midprojectrag.evidence import EvidenceStore
from midprojectrag.retrieval.lexical import selected_records
from midprojectrag.retrieval.types import (
    Candidate,
    positive_int,
    validate_lane,
    validate_query,
    validate_scope,
)


def _unit_vector(value: object, *, dimensions: int | None, code: str) -> tuple[float, ...]:
    if isinstance(value, (str, bytes, dict)):
        raise ValueError(code)
    try:
        length = len(value)  # type: ignore[arg-type]
    except (TypeError, AttributeError) as exc:
        raise ValueError(code) from exc
    if length < 1 or (dimensions is not None and length != dimensions):
        raise ValueError(code)
    components = []
    for index in range(length):
        try:
            component = value[index]  # type: ignore[index]
        except (TypeError, KeyError, IndexError) as exc:
            raise ValueError(code) from exc
        if isinstance(component, bool) or not isinstance(component, Real):
            raise ValueError(code)
        if not math.isfinite(component):
            raise ValueError(code)
        components.append(float(component))
    # Scale before normalization so valid finite large/subnormal coordinates do
    # not overflow or disappear when squared.
    scale = max(abs(component) for component in components)
    if scale == 0:
        raise ValueError(code)
    scaled = tuple(component / scale for component in components)
    norm = math.hypot(*scaled)
    return tuple(component / norm for component in scaled)


class DenseRetriever:
    """No model lookup, network request, or cache population occurs implicitly."""

    def __init__(
        self,
        store: EvidenceStore,
        vectors: Sequence[Sequence[float]],
        query_embedder: Callable[[str], Sequence[float]],
        *,
        evidence_ids: Sequence[str] | None = None,
        lane: str = "dense",
    ) -> None:
        self.lane = validate_lane(lane)
        self._records = selected_records(store, evidence_ids)
        if not callable(query_embedder):
            raise ValueError("invalid_query_embedder")
        self._query_embedder = query_embedder
        if isinstance(vectors, (str, bytes, dict)):
            raise ValueError("invalid_dense_vectors")
        try:
            vector_count = len(vectors)
        except (TypeError, AttributeError) as exc:
            raise ValueError("invalid_dense_vectors") from exc
        if vector_count != len(self._records) or not vector_count:
            raise ValueError("dense_evidence_alignment_mismatch")
        normalized: list[tuple[float, ...]] = []
        dimensions = None
        for index in range(vector_count):
            vector = _unit_vector(
                vectors[index], dimensions=dimensions, code="invalid_dense_vector"
            )
            dimensions = len(vector)
            normalized.append(vector)
        self._vectors = tuple(normalized)
        self.dimensions = len(self._vectors[0])

    def search(
        self,
        query: str,
        *,
        limit: int,
        allowed_doc_ids: frozenset[str] | None = None,
    ) -> tuple[Candidate, ...]:
        validate_query(query)
        positive_int(limit, "invalid_retrieval_limit")
        scope = validate_scope(allowed_doc_ids)
        indices = tuple(
            index
            for index, record in enumerate(self._records)
            if scope is None or record.doc_id in scope
        )
        if not indices:
            return ()
        query_vector = _unit_vector(
            self._query_embedder(query),
            dimensions=self.dimensions,
            code="invalid_query_vector",
        )
        scores = []
        for index in indices:
            score = math.fsum(
                left * right for left, right in zip(query_vector, self._vectors[index])
            )
            scores.append((max(-1.0, min(1.0, score)), self._records[index].evidence_id))
        scores.sort(key=lambda row: (-row[0], row[1]))
        return tuple(
            Candidate(evidence_id, score, self.lane, rank)
            for rank, (score, evidence_id) in enumerate(scores[:limit], 1)
        )
