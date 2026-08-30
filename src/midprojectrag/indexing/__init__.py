"""Deterministic chunking, embeddings, and exact-vector index artifacts."""

from midprojectrag.indexing.chunking import (
    PageChunkConfig,
    TableChunkConfig,
    build_page_chunks,
    build_page_chunks_from_manifest,
    build_table_chunks,
    build_table_chunks_from_manifest,
    chunk_artifact_sha256,
)
from midprojectrag.indexing.visual_fusion import (
    VisualAugmentedIndex,
    VisualExactDenseIndex,
    VisualLaneSearchHit,
    validate_visual_chunk,
)

__all__ = [
    "PageChunkConfig",
    "TableChunkConfig",
    "build_page_chunks",
    "build_page_chunks_from_manifest",
    "build_table_chunks",
    "build_table_chunks_from_manifest",
    "chunk_artifact_sha256",
    "VisualAugmentedIndex",
    "VisualExactDenseIndex",
    "VisualLaneSearchHit",
    "validate_visual_chunk",
]
