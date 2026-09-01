"""Public local-stack adapters."""

from .embeddings import (
    LOCAL_HASH_EMBEDDING_DIMENSIONS,
    LOCAL_HASH_EMBEDDING_MODEL,
    LocalHashEmbeddingProvider,
    LocalTextCounter,
)
from .generation import ALLOWED_OLLAMA_GENERATOR_MODELS, OLLAMA_MODEL_DIGESTS, OllamaGenerator
from .gcp_config import KURE_DIMENSIONS, KURE_MODEL_ID, KURE_MODEL_REVISION
from .hf_embeddings import HuggingFaceTokenCounter, KureEmbeddingProvider
from .qwen_tokenizer import PinnedQwenChatTokenCounter
from .run_records import build_gcp_run_record
from .vllm_generation import QWEN3_AWQ_MODEL, QWEN3_AWQ_REVISION, VllmGenerator

__all__ = [
    "ALLOWED_OLLAMA_GENERATOR_MODELS",
    "LOCAL_HASH_EMBEDDING_DIMENSIONS",
    "LOCAL_HASH_EMBEDDING_MODEL",
    "HuggingFaceTokenCounter",
    "KURE_DIMENSIONS",
    "KURE_MODEL_ID",
    "KURE_MODEL_REVISION",
    "KureEmbeddingProvider",
    "LocalHashEmbeddingProvider",
    "LocalTextCounter",
    "OllamaGenerator",
    "OLLAMA_MODEL_DIGESTS",
    "PinnedQwenChatTokenCounter",
    "QWEN3_AWQ_MODEL",
    "QWEN3_AWQ_REVISION",
    "VllmGenerator",
    "build_gcp_run_record",
]
