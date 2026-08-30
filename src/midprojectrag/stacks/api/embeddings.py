from __future__ import annotations

import base64
import hashlib
import os
import tempfile
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

from midprojectrag.ingest.common import sha256_file
from midprojectrag.indexing.embeddings import EmbeddingBatch


OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
OPENAI_EMBEDDING_MODEL_LARGE = "text-embedding-3-large"
OPENAI_EMBEDDING_MAX_TOKENS = 8191
DEFAULT_SDK_MAX_RETRIES = 2
OPENAI_EMBEDDING_USD_PER_MILLION = Decimal("0.02")


@dataclass(frozen=True)
class OpenAIEmbeddingModelSpec:
    default_dimensions: int
    max_dimensions: int
    usd_per_million_tokens: Decimal


OPENAI_EMBEDDING_MODEL_SPECS = {
    OPENAI_EMBEDDING_MODEL: OpenAIEmbeddingModelSpec(
        default_dimensions=1536,
        max_dimensions=1536,
        usd_per_million_tokens=Decimal("0.02"),
    ),
    OPENAI_EMBEDDING_MODEL_LARGE: OpenAIEmbeddingModelSpec(
        default_dimensions=3072,
        max_dimensions=3072,
        usd_per_million_tokens=Decimal("0.13"),
    ),
}
OPENAI_API_PROFILES = {
    "assignment": frozenset({OPENAI_EMBEDDING_MODEL}),
    "personal_experimental": frozenset(
        {OPENAI_EMBEDDING_MODEL, OPENAI_EMBEDDING_MODEL_LARGE}
    ),
}
TIKTOKEN_LIBRARY_VERSION = "0.13.0"
TIKTOKEN_ASSETS = {
    "cl100k_base": (
        "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken",
        "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7",
        2_000_000,
    ),
    "o200k_base": (
        "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken",
        "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d",
        4_000_000,
    ),
}
TIKTOKEN_ENCODING_SPECS = {
    "cl100k_base": {
        "pat_str": r"""'(?i:[sdmt]|ll|ve|re)|[^\r\n\p{L}\p{N}]?+\p{L}++|\p{N}{1,3}+| ?[^\s\p{L}\p{N}]++[\r\n]*+|\s++$|\s*[\r\n]|\s+(?!\S)|\s""",
        "special_tokens": {
            "<|endoftext|>": 100257,
            "<|fim_prefix|>": 100258,
            "<|fim_middle|>": 100259,
            "<|fim_suffix|>": 100260,
            "<|endofprompt|>": 100276,
        },
    },
    "o200k_base": {
        "pat_str": "|".join(
            [
                r"""[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]*[\p{Ll}\p{Lm}\p{Lo}\p{M}]+(?i:'s|'t|'re|'ve|'m|'ll|'d)?""",
                r"""[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]+[\p{Ll}\p{Lm}\p{Lo}\p{M}]*(?i:'s|'t|'re|'ve|'m|'ll|'d)?""",
                r"""\p{N}{1,3}""",
                r""" ?[^\s\p{L}\p{N}]+[\r\n/]*""",
                r"""\s*[\r\n]+""",
                r"""\s+(?!\S)""",
                r"""\s+""",
            ]
        ),
        "special_tokens": {
            "<|endoftext|>": 199999,
            "<|endofprompt|>": 200018,
        },
    },
}


def _load_local_tiktoken_encoding(
    encoding_name: str,
    cache_path: Path,
    expected_sha256: str,
) -> Any:
    """Build an Encoding from one verified local file; this code has no URL path."""

    try:
        import tiktoken
        from importlib.metadata import version
    except ImportError as error:
        raise RuntimeError("tiktoken_dependency_missing") from error
    if version("tiktoken") != TIKTOKEN_LIBRARY_VERSION:
        raise RuntimeError("tiktoken_version_mismatch")
    spec = TIKTOKEN_ENCODING_SPECS.get(encoding_name)
    if spec is None:
        raise ValueError("tiktoken_encoding_not_allowlisted")
    try:
        payload = cache_path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != expected_sha256:
            raise ValueError("tiktoken_encoding_hash_mismatch")
        mergeable_ranks: dict[bytes, int] = {}
        seen_ranks: set[int] = set()
        for line in payload.splitlines():
            if not line:
                continue
            encoded_token, raw_rank = line.split()
            token = base64.b64decode(encoded_token, validate=True)
            rank = int(raw_rank)
            if token in mergeable_ranks or rank in seen_ranks:
                raise ValueError("tiktoken_encoding_duplicate_rank")
            mergeable_ranks[token] = rank
            seen_ranks.add(rank)
        if not mergeable_ranks:
            raise ValueError("tiktoken_encoding_empty")
        return tiktoken.Encoding(
            name=encoding_name,
            pat_str=spec["pat_str"],
            mergeable_ranks=mergeable_ranks,
            special_tokens=spec["special_tokens"],
        )
    except Exception as error:
        raise RuntimeError("tiktoken_encoding_load_failed") from error


class TiktokenCounter:
    def __init__(
        self,
        model: str = OPENAI_EMBEDDING_MODEL,
        *,
        cache_dir: Path | None = None,
    ) -> None:
        try:
            from tiktoken.model import encoding_name_for_model
        except ImportError as error:
            raise RuntimeError("tiktoken_dependency_missing") from error
        try:
            encoding_name = encoding_name_for_model(model)
        except KeyError as error:
            raise ValueError("tiktoken_model_not_supported") from error
        requirement = TIKTOKEN_ASSETS.get(encoding_name)
        if requirement is None:
            raise ValueError("tiktoken_encoding_not_allowlisted")
        configured_cache = cache_dir or (
            Path(os.environ["TIKTOKEN_CACHE_DIR"])
            if os.environ.get("TIKTOKEN_CACHE_DIR")
            else None
        )
        if configured_cache is None:
            raise RuntimeError("tiktoken_cache_dir_required")
        configured_cache = configured_cache.resolve()
        url, expected_sha256, _max_bytes = requirement
        cache_key = hashlib.sha1(url.encode("utf-8")).hexdigest()
        cache_path = configured_cache / cache_key
        if not cache_path.is_file() or sha256_file(cache_path) != expected_sha256:
            raise RuntimeError("tiktoken_encoding_cache_missing")
        self._encoding = _load_local_tiktoken_encoding(
            encoding_name,
            cache_path,
            expected_sha256,
        )

    def count(self, text: str) -> int:
        return len(self._encoding.encode(text, disallowed_special=()))


def resolve_embedding_dimensions(model: str, dimensions: int | None) -> int:
    spec = OPENAI_EMBEDDING_MODEL_SPECS.get(model)
    if spec is None:
        raise ValueError("embedding_model_not_allowlisted")
    resolved = spec.default_dimensions if dimensions is None else dimensions
    if (
        not isinstance(resolved, int)
        or isinstance(resolved, bool)
        or resolved < 1
        or resolved > spec.max_dimensions
    ):
        raise ValueError("invalid_embedding_dimensions")
    return resolved


def warm_tiktoken_cache(cache_dir: Path) -> dict[str, str]:
    """Download only allowlisted public vocab assets and verify pinned hashes."""

    cache_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, str] = {}
    for encoding_name, (url, expected_sha256, max_bytes) in TIKTOKEN_ASSETS.items():
        cache_key = hashlib.sha1(url.encode("utf-8")).hexdigest()
        destination = cache_dir / cache_key
        if destination.is_file() and sha256_file(destination) == expected_sha256:
            result[encoding_name] = expected_sha256
            continue
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                payload = response.read(max_bytes + 1)
        except Exception as error:
            raise RuntimeError("tokenizer_download_failed") from error
        if len(payload) > max_bytes:
            raise ValueError("tokenizer_asset_too_large")
        if hashlib.sha256(payload).hexdigest() != expected_sha256:
            raise ValueError("tokenizer_asset_hash_mismatch")
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{cache_key}.", dir=cache_dir)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(payload)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        result[encoding_name] = expected_sha256
    return result


class OpenAIEmbeddingProvider:
    requires_budget = True
    max_input_tokens = OPENAI_EMBEDDING_MAX_TOKENS

    def __init__(
        self,
        *,
        client: Any | None = None,
        model: str = OPENAI_EMBEDDING_MODEL,
        dimensions: int | None = None,
        api_profile: str = "assignment",
    ) -> None:
        profile_models = OPENAI_API_PROFILES.get(api_profile)
        if profile_models is None:
            raise ValueError("api_profile_not_allowlisted")
        if model not in profile_models:
            raise ValueError("embedding_model_not_allowlisted")
        resolved_dimensions = resolve_embedding_dimensions(model, dimensions)
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as error:
                raise RuntimeError("openai_dependency_missing") from error
            client = OpenAI(max_retries=DEFAULT_SDK_MAX_RETRIES, timeout=120.0)
        self._client = client
        self.model = model
        self.dimensions = resolved_dimensions
        self.api_profile = api_profile

    def estimate_cost(self, input_tokens: int) -> Decimal:
        spec = OPENAI_EMBEDDING_MODEL_SPECS[self.model]
        return (
            Decimal(input_tokens)
            * spec.usd_per_million_tokens
            / Decimal(1_000_000)
        ).quantize(Decimal("0.000000001"))

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
        if not texts or any(not isinstance(text, str) or not text for text in texts):
            raise ValueError("invalid_embedding_input")
        response = self._client.embeddings.create(
            model=self.model,
            input=list(texts),
            dimensions=self.dimensions,
            encoding_format="float",
        )
        data = sorted(response.data, key=lambda item: item.index)
        if [item.index for item in data] != list(range(len(texts))):
            raise ValueError("embedding_response_index_mismatch")
        vectors = [item.embedding for item in data]
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "total_tokens", None)
        if input_tokens is not None and (
            not isinstance(input_tokens, int) or isinstance(input_tokens, bool) or input_tokens < 0
        ):
            raise ValueError("invalid_embedding_usage")
        return EmbeddingBatch(vectors=vectors, input_tokens=input_tokens)
