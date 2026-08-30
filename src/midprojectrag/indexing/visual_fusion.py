from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from midprojectrag.ingest.common import canonical_json, sha256_text
from midprojectrag.ingest.visual_understanding import VisualRetrievalPolicy
from midprojectrag.indexing.exact_index import IndexSearchHit


_DOC_ID_RE = re.compile(r"^doc_[0-9a-f]{24}$")
_CHUNK_ID_RE = re.compile(r"^vchunk_[0-9a-f]{24}$")
_OCCURRENCE_ID_RE = re.compile(r"^vocc2_[0-9a-f]{24}$")
_OCR_EVIDENCE_ID_RE = re.compile(r"^ocr_[0-9a-f]{24}$")
_CAPTION_EVIDENCE_ID_RE = re.compile(r"^cap_[0-9a-f]{24}$")
_SUPPORT_REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CHUNKERS = {
    "ocr": "image-ocr-v1",
    "layout": "image-layout-v1",
    "caption": "image-caption-v1",
}
_BASE_FIELDS = frozenset(
    {
        "schema_version",
        "chunk_id",
        "doc_id",
        "occurrence_id",
        "evidence_ids",
        "text",
        "evidence_type",
        "page",
        "bbox",
        "crop_sha256",
        "retrieval_role",
        "chunker_id",
        "retrieval_weight",
        "citation",
        "content_sha256",
    }
)
_ANSWER_SUPPORT_FIELDS = frozenset({"status", "support_refs"})


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _valid_bbox(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"x", "y", "w", "h"}
        and all(_finite_number(value.get(field)) for field in ("x", "y", "w", "h"))
        and float(value["w"]) > 0
        and float(value["h"]) > 0
    )


def validate_visual_chunk(value: Any) -> None:
    """Validate the independent visual-chunk-v1 contract before indexing."""

    if not isinstance(value, dict) or set(value) not in {
        _BASE_FIELDS,
        _BASE_FIELDS | {"answer_support"},
    }:
        raise ValueError("invalid_visual_chunk_shape")
    if value.get("schema_version") != "1.0":
        raise ValueError("invalid_visual_chunk_schema_version")
    doc_id = value.get("doc_id")
    chunk_id = value.get("chunk_id")
    occurrence_id = value.get("occurrence_id")
    content_sha256 = value.get("content_sha256")
    crop_sha256 = value.get("crop_sha256")
    if not isinstance(doc_id, str) or _DOC_ID_RE.fullmatch(doc_id) is None:
        raise ValueError("invalid_visual_chunk_doc_id")
    if not isinstance(chunk_id, str) or _CHUNK_ID_RE.fullmatch(chunk_id) is None:
        raise ValueError("invalid_visual_chunk_id")
    if (
        not isinstance(occurrence_id, str)
        or _OCCURRENCE_ID_RE.fullmatch(occurrence_id) is None
    ):
        raise ValueError("invalid_visual_chunk_occurrence_id")
    if (
        not isinstance(content_sha256, str)
        or _SHA256_RE.fullmatch(content_sha256) is None
        or not isinstance(crop_sha256, str)
        or _SHA256_RE.fullmatch(crop_sha256) is None
    ):
        raise ValueError("invalid_visual_chunk_hash")
    text = value.get("text")
    if (
        not isinstance(text, str)
        or not text.strip()
        or len(text) > 24_000
        or sha256_text(text) != content_sha256
    ):
        raise ValueError("invalid_visual_chunk_text")
    page = value.get("page")
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        raise ValueError("invalid_visual_chunk_page")
    bbox = value.get("bbox")
    if not _valid_bbox(bbox):
        raise ValueError("invalid_visual_chunk_bbox")
    evidence_type = value.get("evidence_type")
    chunker_id = value.get("chunker_id")
    if evidence_type not in _CHUNKERS or chunker_id != _CHUNKERS[evidence_type]:
        raise ValueError("invalid_visual_chunk_type")
    if value.get("retrieval_role") != "visual_auxiliary":
        raise ValueError("invalid_visual_chunk_role")
    weight = value.get("retrieval_weight")
    if not _finite_number(weight) or not 0 < float(weight) <= 1:
        raise ValueError("invalid_visual_chunk_weight")
    if evidence_type == "caption" and float(weight) > 0.35:
        raise ValueError("visual_caption_weight_exceeded")
    evidence_ids = value.get("evidence_ids")
    evidence_id_pattern = (
        _CAPTION_EVIDENCE_ID_RE
        if evidence_type == "caption"
        else _OCR_EVIDENCE_ID_RE
    )
    if (
        not isinstance(evidence_ids, list)
        or not evidence_ids
        or evidence_ids != sorted(set(evidence_ids))
        or any(
            not isinstance(item, str) or evidence_id_pattern.fullmatch(item) is None
            for item in evidence_ids
        )
    ):
        raise ValueError("invalid_visual_chunk_evidence_ids")
    answer_support = value.get("answer_support")
    if answer_support is not None:
        if evidence_type != "caption":
            raise ValueError("visual_answer_support_type_mismatch")
        if (
            not isinstance(answer_support, dict)
            or set(answer_support) != _ANSWER_SUPPORT_FIELDS
        ):
            raise ValueError("invalid_visual_answer_support")
        support_status = answer_support.get("status")
        support_refs = answer_support.get("support_refs")
        if (
            support_status not in {"supported", "descriptive_only"}
            or not isinstance(support_refs, list)
            or len(support_refs) > 256
            or support_refs != sorted(set(support_refs))
            or any(
                not isinstance(item, str)
                or _SUPPORT_REFERENCE_RE.fullmatch(item) is None
                for item in support_refs
            )
            or (support_status == "supported" and not support_refs)
            or (support_status == "descriptive_only" and support_refs)
        ):
            raise ValueError("invalid_visual_answer_support")
    citation = value.get("citation")
    expected_citation = {
        "doc_id": doc_id,
        "page": page,
        "bbox": bbox,
        "occurrence_id": occurrence_id,
        "crop_sha256": crop_sha256,
        "evidence_ids": evidence_ids,
    }
    if citation != expected_citation:
        raise ValueError("visual_chunk_citation_mismatch")
    identity = {
        "doc_id": doc_id,
        "occurrence_id": occurrence_id,
        "evidence_ids": evidence_ids,
        "content_sha256": content_sha256,
        "evidence_type": evidence_type,
        "chunker_id": chunker_id,
    }
    if answer_support is not None:
        identity["answer_support"] = answer_support
    if chunk_id != "vchunk_" + sha256_text(canonical_json(identity))[:24]:
        raise ValueError("visual_chunk_identity_mismatch")


class VisualExactDenseIndex:
    """Independent exact-cosine index for visual-chunk-v1 records."""

    def __init__(self, chunks: Sequence[dict[str, Any]], vectors: np.ndarray) -> None:
        if not chunks:
            raise ValueError("empty_visual_index")
        matrix = np.asarray(vectors, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[0] != len(chunks) or matrix.shape[1] < 1:
            raise ValueError("visual_index_shape_mismatch")
        if not np.isfinite(matrix).all():
            raise ValueError("visual_index_non_finite")
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        if np.any(norms == 0):
            raise ValueError("visual_index_zero_vector")
        seen: set[str] = set()
        for chunk in chunks:
            validate_visual_chunk(chunk)
            if chunk["chunk_id"] in seen:
                raise ValueError("duplicate_visual_chunk_id")
            seen.add(chunk["chunk_id"])
        self.chunks = [dict(chunk) for chunk in chunks]
        self.vectors = np.ascontiguousarray(matrix / norms, dtype=np.float32)

    @property
    def dimensions(self) -> int:
        return int(self.vectors.shape[1])

    def search(
        self,
        query_vector: Sequence[float] | np.ndarray,
        *,
        top_k: int = 10,
        allowed_doc_ids: set[str] | None = None,
    ) -> list[IndexSearchHit]:
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
            raise ValueError("invalid_top_k")
        query = np.asarray(query_vector, dtype=np.float32)
        if query.shape != (self.dimensions,) or not np.isfinite(query).all():
            raise ValueError("invalid_query_vector")
        norm = float(np.linalg.norm(query))
        if norm == 0 or not math.isfinite(norm):
            raise ValueError("query_zero_vector")
        rows = [
            index
            for index, chunk in enumerate(self.chunks)
            if allowed_doc_ids is None or chunk["doc_id"] in allowed_doc_ids
        ]
        if not rows:
            return []
        candidate_rows = np.asarray(rows, dtype=np.int64)
        scores = self.vectors[candidate_rows] @ (query / norm)
        order = np.argsort(-scores, kind="stable")[: min(top_k, len(rows))]
        return [
            IndexSearchHit(
                row_id=int(candidate_rows[offset]),
                score=float(scores[offset]),
                chunk=self.chunks[int(candidate_rows[offset])],
            )
            for offset in order
        ]


@dataclass(frozen=True)
class VisualLaneSearchHit(IndexSearchHit):
    lane: str
    lane_rank: int
    dense_score: float


class VisualAugmentedIndex:
    """Fuse an existing page/table index with the independent visual lane."""

    def __init__(
        self,
        base_index: Any,
        visual_index: VisualExactDenseIndex,
        *,
        rrf_k: int = 60,
        visual_retrieval_cap: int = 5,
        policy: VisualRetrievalPolicy | None = None,
    ) -> None:
        if base_index.dimensions != visual_index.dimensions:
            raise ValueError("visual_lane_dimension_mismatch")
        if not isinstance(rrf_k, int) or isinstance(rrf_k, bool) or rrf_k < 1:
            raise ValueError("invalid_visual_rrf_k")
        if (
            not isinstance(visual_retrieval_cap, int)
            or isinstance(visual_retrieval_cap, bool)
            or visual_retrieval_cap < 1
        ):
            raise ValueError("invalid_visual_retrieval_cap")
        self.base_index = base_index
        self.visual_index = visual_index
        self.rrf_k = rrf_k
        self.visual_retrieval_cap = visual_retrieval_cap
        self.policy = policy or VisualRetrievalPolicy()

    @property
    def dimensions(self) -> int:
        return self.base_index.dimensions

    def search(
        self,
        query_vector: Sequence[float] | np.ndarray,
        *,
        top_k: int = 10,
        allowed_doc_ids: set[str] | None = None,
    ) -> list[VisualLaneSearchHit]:
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
            raise ValueError("invalid_top_k")
        base_hits = self.base_index.search(
            query_vector,
            top_k=top_k,
            allowed_doc_ids=allowed_doc_ids,
        )
        # Caption caps are post-filters. Inspect the complete exact-index result so
        # an arbitrarily long prefix of filtered captions cannot hide later OCR or
        # layout evidence. The exact index already scores every eligible row.
        raw_visual_hits = self.visual_index.search(
            query_vector,
            top_k=len(self.visual_index.chunks),
            allowed_doc_ids=allowed_doc_ids,
        )
        non_caption_hits: list[IndexSearchHit] = []
        caption_hits: list[IndexSearchHit] = []
        caption_total = 0
        caption_by_document: dict[str, int] = {}
        for hit in raw_visual_hits:
            chunk = hit.chunk
            if chunk["evidence_type"] == "caption":
                doc_id = chunk["doc_id"]
                if caption_total >= self.policy.caption_per_query:
                    continue
                if caption_by_document.get(doc_id, 0) >= self.policy.caption_per_document:
                    continue
                caption_total += 1
                caption_by_document[doc_id] = caption_by_document.get(doc_id, 0) + 1
                caption_hits.append(hit)
            else:
                non_caption_hits.append(hit)

        # Reserve a bounded visual quota even when the base lane fills top_k, but
        # never evict every base hit. OCR/layout take priority; when both classes
        # exist and at least two visual slots are available, reserve one for a
        # policy-capped caption so captions can augment rather than dominate.
        visual_quota = min(self.visual_retrieval_cap, top_k)
        if base_hits:
            visual_quota = min(visual_quota, max(0, top_k - 1))
        caption_reserve = (
            1
            if caption_hits
            and non_caption_hits
            and visual_quota >= 2
            else 0
        )
        selected_non_caption = non_caption_hits[: visual_quota - caption_reserve]
        remaining_visual_slots = visual_quota - len(selected_non_caption)
        selected_captions = caption_hits[:remaining_visual_slots]
        remaining_visual_slots -= len(selected_captions)
        if remaining_visual_slots:
            selected_non_caption.extend(
                non_caption_hits[
                    len(selected_non_caption) : len(selected_non_caption)
                    + remaining_visual_slots
                ]
            )

        fused_base: list[VisualLaneSearchHit] = []
        for rank, hit in enumerate(base_hits, start=1):
            lane = getattr(hit, "lane", "base")
            lane_rank = getattr(hit, "lane_rank", rank)
            dense_score = getattr(hit, "dense_score", hit.score)
            fused_base.append(
                VisualLaneSearchHit(
                    row_id=hit.row_id,
                    score=1.0 / (self.rrf_k + rank),
                    chunk=hit.chunk,
                    lane=str(lane),
                    lane_rank=int(lane_rank),
                    dense_score=float(dense_score),
                )
            )

        fused_non_caption: list[VisualLaneSearchHit] = []
        for rank, hit in enumerate(selected_non_caption, start=1):
            weight = float(hit.chunk["retrieval_weight"])
            score = weight / (self.rrf_k + rank)
            fused_non_caption.append(
                VisualLaneSearchHit(
                    row_id=hit.row_id,
                    score=score,
                    chunk=hit.chunk,
                    lane="visual",
                    lane_rank=rank,
                    dense_score=hit.score,
                )
            )

        # Captions are always ordered below retained base and OCR/layout evidence.
        caption_ceiling_sources = [
            hit.score for hit in (*fused_base, *fused_non_caption)
        ]
        caption_ceiling = (
            math.nextafter(min(caption_ceiling_sources), -math.inf)
            if caption_ceiling_sources
            else None
        )
        fused_captions: list[VisualLaneSearchHit] = []
        for offset, hit in enumerate(selected_captions, start=1):
            rank = len(selected_non_caption) + offset
            score = float(hit.chunk["retrieval_weight"]) / (self.rrf_k + rank)
            if caption_ceiling is not None:
                score = min(score, caption_ceiling)
            fused_captions.append(
                VisualLaneSearchHit(
                    row_id=hit.row_id,
                    score=score,
                    chunk=hit.chunk,
                    lane="visual",
                    lane_rank=rank,
                    dense_score=hit.score,
                )
            )

        selected_visual = [*fused_non_caption, *fused_captions]
        retained_base_count = max(0, top_k - len(selected_visual))
        fused = [*fused_base[:retained_base_count], *selected_visual]
        fused.sort(
            key=lambda hit: (
                -hit.score,
                1 if hit.lane == "visual" else 0,
                hit.lane_rank,
                hit.chunk["chunk_id"],
            )
        )
        return fused[:top_k]
