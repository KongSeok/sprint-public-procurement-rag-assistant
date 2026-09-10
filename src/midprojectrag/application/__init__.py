"""Public application facade shared by interactive and future HTTP clients."""

from midprojectrag.catalog import CatalogFilter

from .composition import load_rag_application
from .config import RagRuntimeConfig, load_runtime_config
from .service import (
    AnswerResult,
    CatalogSearchResult,
    CitationSummary,
    ConversationTurn,
    DocumentCard,
    DocumentSummary,
    MetadataEvidence,
    MetadataFact,
    RagApplicationService,
    RuntimeDescriptor,
)

__all__ = [
    "AnswerResult",
    "CatalogFilter",
    "CatalogSearchResult",
    "CitationSummary",
    "ConversationTurn",
    "DocumentCard",
    "DocumentSummary",
    "MetadataEvidence",
    "MetadataFact",
    "RagApplicationService",
    "RagRuntimeConfig",
    "RuntimeDescriptor",
    "load_rag_application",
    "load_runtime_config",
]
