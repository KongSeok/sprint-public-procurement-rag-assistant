from __future__ import annotations

import importlib
from collections.abc import Callable
from threading import Lock
from typing import Any

from ._core import NoopObservation, Observation
from ._metadata import (
    safe_metadata_or_none,
    safe_observation_io_or_none,
    valid_observation_name,
    valid_observation_type,
    valid_score,
    valid_trace_id,
)


class LangfuseObserver:
    """Lazy, manual Langfuse v4 exporter with privacy-safe observations.

    This adapter deliberately does not use Langfuse decorators, framework
    callbacks or OpenAI wrappers because those integrations can capture model
    input/output. Metadata and optional structured I/O pass through the same
    strict allowlist, so questions, prompts, source text and answers cannot be
    exported. Import, initialization and exporter failures are isolated from
    the application path.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._enabled = enabled
        self._client_factory = client_factory
        self._client: Any | None = None
        self._initialization_attempted = False
        self._failure_count = 0
        self._dropped_count = 0
        self._lock = Lock()

    @property
    def failure_count(self) -> int:
        with self._lock:
            return self._failure_count

    @property
    def dropped_count(self) -> int:
        with self._lock:
            return self._dropped_count

    @property
    def initialized(self) -> bool:
        with self._lock:
            return self._client is not None

    def start_observation(
        self,
        name: str,
        *,
        as_type: str = "span",
        metadata: object | None = None,
        input: object | None = None,
    ) -> Observation:
        if not self._enabled:
            return NoopObservation()
        if not valid_observation_name(name) or not valid_observation_type(as_type):
            self._increment_dropped()
            return NoopObservation()
        safe = safe_metadata_or_none(metadata)
        safe_input = safe_observation_io_or_none(input)
        if safe is None or (input is not None and safe_input is None):
            self._increment_dropped()
            return NoopObservation()
        client = self._get_client()
        if client is None:
            return NoopObservation()
        try:
            start_arguments: dict[str, Any] = {"name": name, "as_type": as_type, "metadata": safe}
            if safe_input is not None:
                start_arguments["input"] = safe_input
            trace_id = safe.get("trace_id")
            if name == "rag.query" and valid_trace_id(trace_id):
                start_arguments["trace_context"] = {"trace_id": trace_id}
            if as_type in {"generation", "embedding"}:
                model = safe.get("generator_model") or safe.get("embedding_model")
                if isinstance(model, str):
                    start_arguments["model"] = model
            context_manager = client.start_as_current_observation(**start_arguments)
            observation = context_manager.__enter__()
        except Exception:
            self._increment_failure()
            return NoopObservation()
        return _LangfuseObservation(self, observation, context_manager, as_type)

    def start(
        self,
        name: str,
        *,
        as_type: str = "span",
        metadata: object | None = None,
        input: object | None = None,
    ) -> Observation:
        return self.start_observation(name, as_type=as_type, metadata=metadata, input=input)

    def flush(self) -> None:
        with self._lock:
            client = self._client
        if client is None:
            return
        try:
            client.flush()
        except Exception:
            self._increment_failure()

    def score(self, trace_id: str, name: str, value: float | bool) -> None:
        if not valid_trace_id(trace_id) or not valid_score(name, value):
            self._increment_dropped()
            return
        client = self._get_client()
        if client is None:
            return
        try:
            score_value = float(value) if not isinstance(value, bool) else (1.0 if value else 0.0)
            client.create_score(
                trace_id=trace_id,
                name=name,
                value=score_value,
                data_type="BOOLEAN" if isinstance(value, bool) else "NUMERIC",
            )
        except Exception:
            self._increment_failure()

    def shutdown(self) -> None:
        with self._lock:
            client = self._client
        if client is None:
            return
        shutdown = getattr(client, "shutdown", None)
        if callable(shutdown):
            try:
                shutdown()
            except Exception:
                self._increment_failure()
            return
        self.flush()

    def _get_client(self) -> Any | None:
        with self._lock:
            if self._client is not None:
                return self._client
            if self._initialization_attempted:
                return None
            self._initialization_attempted = True
        try:
            factory = self._client_factory or _load_langfuse_client_factory()
            client = factory()
            if not callable(getattr(client, "start_as_current_observation", None)):
                raise TypeError("Langfuse v4 client must provide start_as_current_observation")
        except Exception:
            self._increment_failure()
            return None
        with self._lock:
            self._client = client
        return client

    def _increment_failure(self) -> None:
        with self._lock:
            self._failure_count += 1

    def _increment_dropped(self) -> None:
        with self._lock:
            self._dropped_count += 1


class _LangfuseObservation:
    def __init__(self, owner: LangfuseObserver, observation: Any, context_manager: Any, as_type: str) -> None:
        self._owner = owner
        self._observation = observation
        self._context_manager = context_manager
        self._as_type = as_type
        self._ended = False
        self._lock = Lock()

    @property
    def trace_id(self) -> str | None:
        try:
            value = self._observation.trace_id
        except Exception:
            self._owner._increment_failure()
            return None
        return value if isinstance(value, str) else None

    @property
    def observation_id(self) -> str | None:
        try:
            value = self._observation.id
        except Exception:
            self._owner._increment_failure()
            return None
        return value if isinstance(value, str) else None

    def update(
        self,
        metadata: object | None = None,
        *,
        input: object | None = None,
        output: object | None = None,
    ) -> None:
        safe = safe_metadata_or_none(metadata)
        safe_input = safe_observation_io_or_none(input)
        safe_output = safe_observation_io_or_none(output)
        if (
            safe is None
            or (input is not None and safe_input is None)
            or (output is not None and safe_output is None)
        ):
            self._owner._increment_dropped()
            return
        if not safe and safe_input is None and safe_output is None:
            return
        with self._lock:
            if self._ended:
                return
        try:
            self._observation.update(
                **self._update_arguments(safe, safe_input=safe_input, safe_output=safe_output)
            )
        except Exception:
            self._owner._increment_failure()

    def end(self, metadata: object | None = None, *, output: object | None = None) -> None:
        self._finish(metadata, output, None, None, None)

    def _finish(
        self,
        metadata: object | None,
        output: object | None,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        safe = safe_metadata_or_none(metadata)
        safe_output = safe_observation_io_or_none(output)
        if safe is None or (output is not None and safe_output is None):
            self._owner._increment_dropped()
            safe = {}
            safe_output = None
        with self._lock:
            if self._ended:
                return
            self._ended = True
        if safe or safe_output is not None:
            try:
                self._observation.update(
                    **self._update_arguments(safe, safe_output=safe_output)
                )
            except Exception:
                self._owner._increment_failure()
        try:
            # Never forward application exceptions to the exporter context.
            # Exception messages and tracebacks can contain provider payloads,
            # source text, or local paths. The wrapper still returns False from
            # __exit__, so the application exception propagates normally.
            self._context_manager.__exit__(None, None, None)
        except Exception:
            self._owner._increment_failure()

    def __enter__(self) -> "_LangfuseObservation":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        self._finish({"success": exc_type is None}, None, exc_type, exc, traceback)
        return False

    def _update_arguments(
        self,
        safe: dict[str, Any],
        *,
        safe_input: dict[str, Any] | None = None,
        safe_output: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {}
        if safe:
            arguments["metadata"] = safe
        if safe_input is not None:
            arguments["input"] = safe_input
        if safe_output is not None:
            arguments["output"] = safe_output
        if self._as_type not in {"generation", "embedding"}:
            return arguments
        usage: dict[str, int] = {}
        if self._as_type == "embedding" and isinstance(safe.get("embedding_tokens"), int):
            usage["input"] = safe["embedding_tokens"]
        if isinstance(safe.get("input_tokens"), int):
            usage["input"] = safe["input_tokens"]
        if isinstance(safe.get("output_tokens"), int):
            usage["output"] = safe["output_tokens"]
        if usage:
            arguments["usage_details"] = usage
        cost = safe.get("cost_usd")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            arguments["cost_details"] = {"total": float(cost)}
        return arguments


def _load_langfuse_client_factory() -> Callable[[], Any]:
    module = importlib.import_module("langfuse")
    factory = getattr(module, "get_client", None)
    if not callable(factory):
        raise ImportError("Langfuse v4 get_client is unavailable")
    return factory
