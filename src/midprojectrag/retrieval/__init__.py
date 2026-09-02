"""Opt-in evidence-addressed retrieval; independent of the baseline indexes."""

from midprojectrag.retrieval.context import select_context
from midprojectrag.retrieval.dense import DenseRetriever
from midprojectrag.retrieval.hybrid import HybridRetriever, HybridSearchResult
from midprojectrag.retrieval.lexical import BM25Retriever
from midprojectrag.retrieval.types import (
    Candidate,
    IdentityReranker,
    Reranker,
    Retriever,
    validate_reranked,
)

__all__ = [
    "BM25Retriever",
    "Candidate",
    "DenseRetriever",
    "HybridRetriever",
    "HybridSearchResult",
    "IdentityReranker",
    "Reranker",
    "Retriever",
    "select_context",
    "validate_reranked",
]
