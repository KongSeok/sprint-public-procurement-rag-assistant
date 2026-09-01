from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from midprojectrag.ingest.common import canonical_json
from midprojectrag.indexing.embeddings import EmbeddingBatch

from .gcp_config import (
    KURE_DIMENSIONS,
    KURE_DOCUMENT_PROMPT,
    KURE_MAX_INPUT_TOKENS,
    KURE_MODEL_ID,
    KURE_MODEL_REVISION,
    KURE_POOLING,
    KURE_PROMPT_VERSION,
)


TokenizerLoader = Callable[..., Any]
EncoderLoader = Callable[..., Any]


def _default_tokenizer_loader(**kwargs: Any) -> Any:
    try:
        from transformers import AutoTokenizer
    except ImportError as error:
        raise RuntimeError("transformers_dependency_missing") from error
    try:
        return AutoTokenizer.from_pretrained(**kwargs)
    except Exception as error:
        raise RuntimeError("hf_tokenizer_load_failed") from error


def _default_encoder_loader(**kwargs: Any) -> Any:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as error:
        raise RuntimeError("sentence_transformers_dependency_missing") from error
    try:
        return SentenceTransformer(**kwargs)
    except Exception as error:
        raise RuntimeError("hf_embedding_model_load_failed") from error


def _validate_identity(
    *,
    model: str,
    revision: str,
    local_files_only: bool,
    trust_remote_code: bool,
) -> None:
    if model != KURE_MODEL_ID:
        raise ValueError("embedding_model_not_allowlisted")
    if revision != KURE_MODEL_REVISION:
        raise ValueError("embedding_revision_not_allowlisted")
    if local_files_only is not True:
        raise ValueError("local_files_only_required")
    if trust_remote_code is not False:
        raise ValueError("trust_remote_code_not_allowed")


class HuggingFaceTokenCounter:
    """Lazy, pinned tokenizer counter with no implicit network path."""

    def __init__(
        self,
        *,
        model: str = KURE_MODEL_ID,
        revision: str = KURE_MODEL_REVISION,
        tokenizer: Any | None = None,
        tokenizer_loader: TokenizerLoader | None = None,
        local_files_only: bool = True,
        trust_remote_code: bool = False,
    ) -> None:
        _validate_identity(
            model=model,
            revision=revision,
            local_files_only=local_files_only,
            trust_remote_code=trust_remote_code,
        )
        self.model = model
        self.revision = revision
        self.local_files_only = local_files_only
        self.trust_remote_code = trust_remote_code
        self._tokenizer = tokenizer
        self._tokenizer_loader = tokenizer_loader or _default_tokenizer_loader

    def _get_tokenizer(self) -> Any:
        if self._tokenizer is None:
            self._tokenizer = self._tokenizer_loader(
                pretrained_model_name_or_path=self.model,
                revision=self.revision,
                local_files_only=True,
                trust_remote_code=False,
                use_fast=True,
            )
        return self._tokenizer

    def count(self, text: str) -> int:
        if not isinstance(text, str):
            raise ValueError("invalid_counter_input")
        payload = self._get_tokenizer()(
            text,
            add_special_tokens=True,
            return_attention_mask=False,
            return_token_type_ids=False,
            truncation=False,
        )
        if not isinstance(payload, Mapping):
            raise ValueError("tokenizer_output_invalid")
        input_ids = payload.get("input_ids")
        if (
            not isinstance(input_ids, Sequence)
            or isinstance(input_ids, (str, bytes))
            or any(isinstance(item, Sequence) for item in input_ids)
        ):
            raise ValueError("tokenizer_output_invalid")
        count = len(input_ids)
        if count < 1:
            raise ValueError("tokenizer_output_invalid")
        return count


class KureEmbeddingProvider:
    """Pinned KURE encoder. Core indexing owns canonical L2 normalization."""

    requires_budget = False
    max_input_tokens = KURE_MAX_INPUT_TOKENS

    def __init__(
        self,
        *,
        model: str = KURE_MODEL_ID,
        revision: str = KURE_MODEL_REVISION,
        dimensions: int = KURE_DIMENSIONS,
        pooling: str = KURE_POOLING,
        prompt_version: str = KURE_PROMPT_VERSION,
        prompt: str = KURE_DOCUMENT_PROMPT,
        batch_size: int = 32,
        device: str = "cpu",
        tokenizer: Any | None = None,
        encoder: Any | None = None,
        tokenizer_loader: TokenizerLoader | None = None,
        encoder_loader: EncoderLoader | None = None,
        local_files_only: bool = True,
        trust_remote_code: bool = False,
    ) -> None:
        _validate_identity(
            model=model,
            revision=revision,
            local_files_only=local_files_only,
            trust_remote_code=trust_remote_code,
        )
        if dimensions != KURE_DIMENSIONS or isinstance(dimensions, bool):
            raise ValueError("invalid_embedding_dimensions")
        if pooling != KURE_POOLING:
            raise ValueError("embedding_pooling_not_allowlisted")
        if prompt_version != KURE_PROMPT_VERSION:
            raise ValueError("embedding_prompt_version_not_allowlisted")
        if prompt != KURE_DOCUMENT_PROMPT:
            raise ValueError("embedding_prompt_not_allowlisted")
        if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size < 1:
            raise ValueError("invalid_embedding_batch_size")
        if not isinstance(device, str) or not device:
            raise ValueError("invalid_embedding_device")
        self.model = model
        self.revision = revision
        self.dimensions = dimensions
        self.pooling = pooling
        self.prompt_version = prompt_version
        self.prompt = prompt
        self.batch_size = batch_size
        self.device = device
        self.local_files_only = local_files_only
        self.trust_remote_code = trust_remote_code
        self._counter = HuggingFaceTokenCounter(
            model=model,
            revision=revision,
            tokenizer=tokenizer,
            tokenizer_loader=tokenizer_loader,
            local_files_only=local_files_only,
            trust_remote_code=trust_remote_code,
        )
        self._encoder = encoder
        self._encoder_loader = encoder_loader or _default_encoder_loader

    def _get_encoder(self) -> Any:
        if self._encoder is None:
            self._encoder = self._encoder_loader(
                model_name_or_path=self.model,
                revision=self.revision,
                device=self.device,
                local_files_only=True,
                trust_remote_code=False,
            )
        return self._encoder

    def cache_namespace(self, *, role: str) -> str:
        if role not in {"document", "query"}:
            raise ValueError("embedding_role_not_supported")
        return canonical_json(
            {
                "backend": "sentence-transformers",
                "model": self.model,
                "pooling": self.pooling,
                "prompt": self.prompt,
                "prompt_version": self.prompt_version,
                "revision": self.revision,
                "role": role,
            }
        )

    def estimate_cost(self, input_tokens: int) -> Decimal:
        return Decimal("0")

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
        if (
            not texts
            or isinstance(texts, (str, bytes))
            or any(not isinstance(text, str) or not text for text in texts)
        ):
            raise ValueError("invalid_embedding_input")
        ordered_texts = list(texts)
        token_counts = [self._counter.count(text) for text in ordered_texts]
        if any(count > self.max_input_tokens for count in token_counts):
            raise ValueError("embedding_input_token_limit_exceeded")
        vectors = self._get_encoder().encode(
            ordered_texts,
            batch_size=self.batch_size,
            convert_to_numpy=True,
            normalize_embeddings=False,
            prompt=self.prompt,
            show_progress_bar=False,
        )
        matrix = np.asarray(vectors, dtype=np.float32)
        if matrix.shape != (len(ordered_texts), self.dimensions):
            raise ValueError("embedding_shape_mismatch")
        if not np.isfinite(matrix).all():
            raise ValueError("embedding_non_finite")
        if np.any(np.linalg.norm(matrix, axis=1) == 0):
            raise ValueError("embedding_zero_vector")
        return EmbeddingBatch(
            vectors=np.ascontiguousarray(matrix, dtype=np.float32),
            input_tokens=sum(token_counts),
        )
