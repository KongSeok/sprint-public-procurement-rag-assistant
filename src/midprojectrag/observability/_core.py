from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from threading import Lock
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from ._metadata import (
    safe_metadata_or_none,
    safe_observation_io_or_none,
    valid_observation_name,
    valid_observation_type,
    valid_score,
    valid_trace_id,
)


@dataclass(frozen=True)
class ObservationRecord:
    name: str
    as_type: str
    started_ns: int
    ended_ns: int
    metadata: Mapping[str, Any]
    input: Mapping[str, Any] | None = None
    output: Mapping[str, Any] | None = None

    @property
    def duration_ms(self) -> float:
        return (self.ended_ns - self.started_ns) / 1_000_000


@dataclass(frozen=True)
class ScoreRecord:
    trace_id: str
    name: str
    value: float | bool


@runtime_checkable
class Observation(Protocol):
    @property
    def trace_id(self) -> str | None: ...

    @property
    def observation_id(self) -> str | None: ...

    def update(
        self,
        metadata: object | None = None,
        *,
        input: object | None = None,
        output: object | None = None,
    ) -> None: ...

    def end(self, metadata: object | None = None, *, output: object | None = None) -> None: ...

    def __enter__(self) -> "Observation": ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool: ...


@runtime_checkable
class Observer(Protocol):
    def start_observation(
        self,
        name: str,
        *,
        as_type: str = "span",
        metadata: object | None = None,
        input: object | None = None,
    ) -> Observation: ...

    def score(self, trace_id: str, name: str, value: float | bool) -> None: ...

    def flush(self) -> None: ...


class NoopObservation:
    @property
    def trace_id(self) -> None:
        return None

    @property
    def observation_id(self) -> None:
        return None

    def update(
        self,
        metadata: object | None = None,
        *,
        input: object | None = None,
        output: object | None = None,
    ) -> None:
        return None

    def end(self, metadata: object | None = None, *, output: object | None = None) -> None:
        return None

    def __enter__(self) -> "NoopObservation":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        return False


class NoopObserver:
    """Default observer; performs no imports, I/O, logging or network access."""

    def start_observation(
        self,
        name: str,
        *,
        as_type: str = "span",
        metadata: object | None = None,
        input: object | None = None,
    ) -> NoopObservation:
        return NoopObservation()

    def start(
        self,
        name: str,
        *,
        as_type: str = "span",
        metadata: object | None = None,
        input: object | None = None,
    ) -> NoopObservation:
        return self.start_observation(name, as_type=as_type, metadata=metadata, input=input)

    def flush(self) -> None:
        return None

    def score(self, trace_id: str, name: str, value: float | bool) -> None:
        return None


class MemoryObserver:
    """In-memory, content-free sink for deterministic tests and diagnostics."""

    def __init__(self) -> None:
        self._records: list[ObservationRecord] = []
        self._scores: list[ScoreRecord] = []
        self._lock = Lock()
        self._dropped_count = 0
        self._flush_count = 0

    @property
    def records(self) -> tuple[ObservationRecord, ...]:
        with self._lock:
            return tuple(self._records)

    @property
    def dropped_count(self) -> int:
        with self._lock:
            return self._dropped_count

    @property
    def scores(self) -> tuple[ScoreRecord, ...]:
        with self._lock:
            return tuple(self._scores)

    @property
    def flush_count(self) -> int:
        with self._lock:
            return self._flush_count

    def start_observation(
        self,
        name: str,
        *,
        as_type: str = "span",
        metadata: object | None = None,
        input: object | None = None,
    ) -> Observation:
        if not valid_observation_name(name) or not valid_observation_type(as_type):
            with self._lock:
                self._dropped_count += 1
            return NoopObservation()
        safe = safe_metadata_or_none(metadata)
        safe_input = safe_observation_io_or_none(input)
        if safe is None or (input is not None and safe_input is None):
            with self._lock:
                self._dropped_count += 1
            return NoopObservation()
        return _MemoryObservation(self, name, as_type, safe, safe_input, time.monotonic_ns())

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
            self._flush_count += 1

    def score(self, trace_id: str, name: str, value: float | bool) -> None:
        if not valid_trace_id(trace_id) or not valid_score(name, value):
            with self._lock:
                self._dropped_count += 1
            return
        with self._lock:
            self._scores.append(ScoreRecord(trace_id=trace_id, name=name, value=value))

    def _append(self, record: ObservationRecord) -> None:
        with self._lock:
            self._records.append(record)


class _MemoryObservation:
    def __init__(
        self,
        owner: MemoryObserver,
        name: str,
        as_type: str,
        metadata: dict[str, Any],
        input: dict[str, Any] | None,
        started_ns: int,
    ) -> None:
        self._owner = owner
        self._name = name
        self._as_type = as_type
        self._metadata = metadata
        self._input = input
        self._output: dict[str, Any] | None = None
        self._started_ns = started_ns
        self._ended = False
        self._lock = Lock()

    @property
    def trace_id(self) -> None:
        return None

    @property
    def observation_id(self) -> None:
        return None

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
            with self._owner._lock:
                self._owner._dropped_count += 1
            return
        with self._lock:
            if not self._ended:
                self._metadata.update(safe)
                if input is not None:
                    self._input = safe_input
                if output is not None:
                    self._output = safe_output

    def end(self, metadata: object | None = None, *, output: object | None = None) -> None:
        safe = safe_metadata_or_none(metadata)
        safe_output = safe_observation_io_or_none(output)
        if safe is None or (output is not None and safe_output is None):
            with self._owner._lock:
                self._owner._dropped_count += 1
            safe = {}
            safe_output = None
        with self._lock:
            if self._ended:
                return
            self._metadata.update(safe)
            if output is not None:
                self._output = safe_output
            self._ended = True
            record = ObservationRecord(
                name=self._name,
                as_type=self._as_type,
                started_ns=self._started_ns,
                ended_ns=time.monotonic_ns(),
                metadata=MappingProxyType(dict(self._metadata)),
                input=MappingProxyType(dict(self._input)) if self._input is not None else None,
                output=MappingProxyType(dict(self._output)) if self._output is not None else None,
            )
        self._owner._append(record)

    def __enter__(self) -> "_MemoryObservation":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        self.end({"success": exc_type is None})
        return False
