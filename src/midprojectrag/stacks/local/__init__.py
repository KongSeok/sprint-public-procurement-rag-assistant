"""Public local-stack adapters."""

from .embeddings import (
    LOCAL_HASH_EMBEDDING_DIMENSIONS,
    LOCAL_HASH_EMBEDDING_MODEL,
    LocalHashEmbeddingProvider,
    LocalTextCounter,
)
from .generation import ALLOWED_OLLAMA_GENERATOR_MODELS, OLLAMA_MODEL_DIGESTS, OllamaGenerator

__all__ = [
    "ALLOWED_OLLAMA_GENERATOR_MODELS",
    "LOCAL_HASH_EMBEDDING_DIMENSIONS",
    "LOCAL_HASH_EMBEDDING_MODEL",
    "LocalHashEmbeddingProvider",
    "LocalTextCounter",
    "OllamaGenerator",
    "OLLAMA_MODEL_DIGESTS",
]
