from __future__ import annotations

import math
import re
import unicodedata
import zlib
from collections import Counter
from decimal import Decimal
from typing import Sequence

import numpy as np

from midprojectrag.indexing.embeddings import EmbeddingBatch


LOCAL_HASH_EMBEDDING_MODEL = "local-hash-char-v1"
LOCAL_HASH_EMBEDDING_DIMENSIONS = 2048
LOCAL_HASH_EMBEDDING_MAX_CHARACTERS = 65_536
_LOCAL_TOKEN_RE = re.compile(r"[0-9a-z가-힣]+")


class LocalTextCounter:
    """Deterministic conservative counter for the offline experimental path."""

    def count(self, text: str) -> int:
        if not isinstance(text, str):
            raise ValueError("invalid_counter_input")
        return max(1, len(unicodedata.normalize("NFC", text)))


class LocalHashEmbeddingProvider:
    """Dependency-free lexical hashing; intentionally not a semantic model."""

    model = LOCAL_HASH_EMBEDDING_MODEL
    requires_budget = False
    max_input_tokens = LOCAL_HASH_EMBEDDING_MAX_CHARACTERS

    def __init__(self, *, dimensions: int = LOCAL_HASH_EMBEDDING_DIMENSIONS) -> None:
        if dimensions != LOCAL_HASH_EMBEDDING_DIMENSIONS:
            raise ValueError("invalid_local_hash_dimensions")
        self.dimensions = dimensions

    @staticmethod
    def _features(text: str) -> Counter[str]:
        normalized = unicodedata.normalize("NFC", text).casefold()
        tokens = _LOCAL_TOKEN_RE.findall(normalized)
        if not tokens:
            tokens = [normalized.strip() or "__blank__"]
        features: Counter[str] = Counter()
        for token in tokens:
            features[f"w:{token}"] += 1
            for size in (2, 3):
                for start in range(0, max(0, len(token) - size + 1)):
                    features[f"c{size}:{token[start:start + size]}"] += 1
        return features

    def estimate_cost(self, input_tokens: int) -> Decimal:
        return Decimal("0")

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
        if not texts or any(not isinstance(text, str) or not text for text in texts):
            raise ValueError("invalid_embedding_input")
        matrix = np.zeros((len(texts), self.dimensions), dtype=np.float32)
        input_characters = 0
        for row_index, text in enumerate(texts):
            normalized = unicodedata.normalize("NFC", text)
            input_characters += len(normalized)
            for feature, count in self._features(normalized).items():
                hashed = zlib.crc32(feature.encode("utf-8"))
                bucket = hashed % self.dimensions
                sign = 1.0 if hashed & 0x80000000 else -1.0
                base_weight = 2.0 if feature.startswith("w:") else 1.0
                matrix[row_index, bucket] += sign * base_weight * (1.0 + math.log1p(count))
            if not np.any(matrix[row_index]):
                raise ValueError("embedding_zero_vector")
        return EmbeddingBatch(vectors=matrix, input_tokens=input_characters)
