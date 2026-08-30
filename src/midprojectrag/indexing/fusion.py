from __future__ import annotations

from dataclasses import dataclass
from math import fsum
from typing import Any, Sequence

import numpy as np

from midprojectrag.indexing.exact_index import ExactDenseIndex, IndexSearchHit


@dataclass(frozen=True)
class DualLaneSearchHit(IndexSearchHit):
    """An RRF-ranked hit with its representative retrieval lane."""

    lane: str
    lane_rank: int
    dense_score: float


@dataclass
class _FusionCandidate:
    hit: IndexSearchHit
    lane: str
    lane_priority: int
    lane_rank: int
    contributions: list[float]


def _positive_int(value: Any, error_code: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(error_code)
    return value


class DualLaneIndex:
    """Search page and table indexes with one vector and fuse their ranks."""

    def __init__(
        self,
        page_index: ExactDenseIndex,
        table_index: ExactDenseIndex,
        *,
        rrf_k: int = 60,
        table_retrieval_cap: int = 5,
    ) -> None:
        if page_index.dimensions != table_index.dimensions:
            raise ValueError("dual_lane_dimension_mismatch")
        self.page_index = page_index
        self.table_index = table_index
        self.rrf_k = _positive_int(rrf_k, "invalid_rrf_k")
        self.table_retrieval_cap = _positive_int(
            table_retrieval_cap,
            "invalid_table_retrieval_cap",
        )

    @property
    def dimensions(self) -> int:
        return self.page_index.dimensions

    def search(
        self,
        query_vector: Sequence[float] | np.ndarray,
        *,
        top_k: int = 10,
        allowed_doc_ids: set[str] | None = None,
    ) -> list[DualLaneSearchHit]:
        limit = _positive_int(top_k, "invalid_top_k")
        page_hits = self.page_index.search(
            query_vector,
            top_k=limit,
            allowed_doc_ids=allowed_doc_ids,
        )
        table_hits = self.table_index.search(
            query_vector,
            top_k=min(limit, self.table_retrieval_cap),
            allowed_doc_ids=allowed_doc_ids,
        )

        candidates: dict[str, _FusionCandidate] = {}
        for lane, lane_priority, hits in (
            ("page", 0, page_hits),
            ("table", 1, table_hits),
        ):
            seen_in_lane: set[str] = set()
            for lane_rank, hit in enumerate(hits, start=1):
                chunk_id = hit.chunk.get("chunk_id")
                if not isinstance(chunk_id, str) or not chunk_id:
                    raise ValueError("invalid_fusion_chunk_id")
                if chunk_id in seen_in_lane:
                    continue
                seen_in_lane.add(chunk_id)
                contribution = 1.0 / (self.rrf_k + lane_rank)
                existing = candidates.get(chunk_id)
                if existing is None:
                    candidates[chunk_id] = _FusionCandidate(
                        hit=hit,
                        lane=lane,
                        lane_priority=lane_priority,
                        lane_rank=lane_rank,
                        contributions=[contribution],
                    )
                    continue
                if existing.hit.chunk != hit.chunk:
                    raise ValueError("fusion_chunk_identity_mismatch")
                existing.contributions.append(contribution)

        fused = [
            DualLaneSearchHit(
                row_id=candidate.hit.row_id,
                score=fsum(candidate.contributions),
                chunk=candidate.hit.chunk,
                lane=candidate.lane,
                lane_rank=candidate.lane_rank,
                dense_score=candidate.hit.score,
            )
            for candidate in candidates.values()
        ]
        fused.sort(
            key=lambda hit: (
                -hit.score,
                0 if hit.lane == "page" else 1,
                hit.lane_rank,
                hit.chunk["chunk_id"],
                hit.row_id,
            )
        )
        return fused[:limit]
