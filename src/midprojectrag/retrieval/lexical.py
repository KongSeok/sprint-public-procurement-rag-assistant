"""Local BM25 candidate retrieval. Scores never certify answer correctness."""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from numbers import Real

from midprojectrag.evidence import Evidence, EvidenceStore
from midprojectrag.retrieval.types import (
    Candidate,
    positive_int,
    validate_lane,
    validate_query,
    validate_scope,
)


def selected_records(
    store: EvidenceStore, evidence_ids: Sequence[str] | None
) -> tuple[Evidence, ...]:
    if evidence_ids is None:
        return store.all()
    if isinstance(evidence_ids, (str, bytes)) or not isinstance(evidence_ids, Sequence):
        raise ValueError("invalid_index_evidence_ids")
    records = []
    seen: set[str] = set()
    for evidence_id in evidence_ids:
        if not isinstance(evidence_id, str) or evidence_id in seen:
            raise ValueError("invalid_or_duplicate_index_evidence_id")
        records.append(store.get(evidence_id))
        seen.add(evidence_id)
    return tuple(records)


def _tokens(text: str) -> tuple[str, ...]:
    # Unicode word tokens are intentionally simple and deterministic. A Korean
    # morphology model is a separately selected capability, not an implicit load.
    return tuple(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold()))


class BM25Retriever:
    """BM25 over explicitly selected evidence (all records if IDs are omitted)."""

    def __init__(
        self,
        store: EvidenceStore,
        *,
        evidence_ids: Sequence[str] | None = None,
        lane: str = "lexical",
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.lane = validate_lane(lane)
        if (
            isinstance(k1, bool)
            or not isinstance(k1, Real)
            or not math.isfinite(k1)
            or k1 <= 0
            or isinstance(b, bool)
            or not isinstance(b, Real)
            or not math.isfinite(b)
            or not 0 <= b <= 1
        ):
            raise ValueError("invalid_bm25_parameters")
        self.k1 = float(k1)
        self.b = float(b)
        self._records = selected_records(store, evidence_ids)
        self._terms = tuple(Counter(_tokens(record.text)) for record in self._records)
        self._lengths = tuple(sum(terms.values()) for terms in self._terms)
        self._average_length = (
            sum(self._lengths) / len(self._lengths) if self._lengths else 0.0
        )
        self._document_frequency: Counter[str] = Counter()
        for terms in self._terms:
            self._document_frequency.update(terms.keys())

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
        query_terms = set(_tokens(query))
        if not query_terms or not self._average_length or scope == frozenset():
            return ()
        scores: list[tuple[float, str]] = []
        count = len(self._records)
        for record, terms, length in zip(self._records, self._terms, self._lengths):
            if scope is not None and record.doc_id not in scope:
                continue
            normalization = self.k1 * (
                1 - self.b + self.b * length / self._average_length
            )
            parts = []
            for term in sorted(query_terms):
                frequency = terms.get(term, 0)
                if not frequency:
                    continue
                document_frequency = self._document_frequency[term]
                inverse_frequency = math.log1p(
                    (count - document_frequency + 0.5) / (document_frequency + 0.5)
                )
                parts.append(
                    inverse_frequency
                    * frequency
                    * (self.k1 + 1)
                    / (frequency + normalization)
                )
            score = math.fsum(parts)
            if score > 0:
                scores.append((score, record.evidence_id))
        scores.sort(key=lambda row: (-row[0], row[1]))
        return tuple(
            Candidate(evidence_id, score, self.lane, rank)
            for rank, (score, evidence_id) in enumerate(scores[:limit], 1)
        )
