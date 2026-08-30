"""Fail-closed, content-free observability for the RAG pipeline.

The default factory result is a no-op observer. Enabling Langfuse is an
explicit caller decision and never enables raw prompt/response instrumentation.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ._core import (
    MemoryObserver,
    NoopObservation,
    NoopObserver,
    Observation,
    ObservationRecord,
    Observer,
    ScoreRecord,
)
from ._langfuse import LangfuseObserver
from ._metadata import (
    ALLOWED_OBSERVATION_NAMES,
    ALLOWED_OBSERVATION_TYPES,
    ALLOWED_SCORE_NAMES,
    SAFE_METADATA_KEYS,
    safe_observation_io_or_none,
    safe_metadata_or_none,
    sanitize_metadata,
)


def create_observer(
    provider: str | None = None,
    *,
    client_factory: Callable[[], Any] | None = None,
) -> Observer:
    """Create an observer without implicit external connectivity.

    ``None``, ``disabled`` and unknown providers return ``NoopObserver``.
    ``langfuse`` returns a lazy adapter; the package is not imported and a
    client is not constructed until the first valid observation starts.
    """

    normalized = provider.strip().lower() if isinstance(provider, str) else "disabled"
    if normalized == "memory":
        return MemoryObserver()
    if normalized == "langfuse":
        return LangfuseObserver(client_factory=client_factory)
    return NoopObserver()


__all__ = [
    "ALLOWED_OBSERVATION_NAMES",
    "ALLOWED_OBSERVATION_TYPES",
    "ALLOWED_SCORE_NAMES",
    "LangfuseObserver",
    "MemoryObserver",
    "NoopObservation",
    "NoopObserver",
    "Observation",
    "ObservationRecord",
    "Observer",
    "SAFE_METADATA_KEYS",
    "ScoreRecord",
    "create_observer",
    "safe_metadata_or_none",
    "safe_observation_io_or_none",
    "sanitize_metadata",
]
