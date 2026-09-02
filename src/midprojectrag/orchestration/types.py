"""Versioned, immutable runtime hypotheses; no evaluation labels belong here."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Protocol

from midprojectrag.evidence import Evidence


def _text(value: object, code: str, maximum: int = 12000) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(code)


@dataclass(frozen=True)
class Slot:
    key: str
    query: str
    doc_id: str | None = None
    kind: str | None = None

    def __post_init__(self) -> None:
        _text(self.key, "invalid_slot_key", 80)
        _text(self.query, "invalid_slot_query")
        if self.doc_id is not None:
            _text(self.doc_id, "invalid_slot_doc")
        if self.kind is not None and self.kind not in ("page", "text", "table", "figure"):
            raise ValueError("invalid_slot_kind")


@dataclass(frozen=True)
class QueryPlan:
    query: str
    slots: tuple[Slot, ...]
    query_type: str = "fact"
    history: tuple[tuple[str, str], ...] = ()
    allowed_doc_ids: frozenset[str] | None = None

    def __post_init__(self) -> None:
        _text(self.query, "invalid_plan_query")
        if not isinstance(self.slots, tuple) or not 1 <= len(self.slots) <= 20:
            raise ValueError("invalid_plan_slots")
        if any(not isinstance(s, Slot) for s in self.slots):
            raise ValueError("invalid_plan_slots")
        if len({s.key for s in self.slots}) != len(self.slots):
            raise ValueError("duplicate_slot_key")
        if self.query_type not in ("fact", "compare", "list", "visual", "followup"):
            raise ValueError("invalid_query_type")
        if not isinstance(self.history, tuple) or len(self.history) > 50:
            raise ValueError("invalid_plan_history")
        for turn in self.history:
            if not isinstance(turn, tuple) or len(turn) != 2 or turn[0] not in ("user", "assistant"):
                raise ValueError("invalid_plan_history")
            _text(turn[1], "invalid_plan_history")
        if self.allowed_doc_ids is not None:
            if not isinstance(self.allowed_doc_ids, frozenset) or not self.allowed_doc_ids:
                raise ValueError("invalid_plan_scope")
            for doc in self.allowed_doc_ids:
                _text(doc, "invalid_plan_scope")
            if any(s.doc_id is not None and s.doc_id not in self.allowed_doc_ids for s in self.slots):
                raise ValueError("slot_outside_scope")


@dataclass(frozen=True)
class Verification:
    evidence_ids: tuple[str, ...]
    contradiction: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_ids, tuple) or any(not isinstance(i, str) for i in self.evidence_ids):
            raise ValueError("invalid_verification_ids")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("duplicate_verification_ids")
        if not isinstance(self.contradiction, bool):
            raise ValueError("invalid_contradiction")


class Verifier(Protocol):
    def verify(self, slot: Slot, evidence: tuple[Evidence, ...]) -> Verification: ...


class EnumerationVerifier(Protocol):
    """An explicit exhaustive-enumeration capability, NOT top-k saturation."""
    def is_complete(self, plan: QueryPlan, evidence: tuple[Evidence, ...]) -> bool: ...


@dataclass(frozen=True)
class HarnessConfig:
    max_actions: int = 24
    max_rounds: int = 3
    max_candidates: int = 20
    max_context_chars: int = 9000
    max_context_items: int = 12
    max_per_doc: int = 6
    timeout_seconds: float = 90.0

    def __post_init__(self) -> None:
        for name in ("max_actions", "max_rounds", "max_candidates", "max_context_chars", "max_context_items", "max_per_doc"):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= 100000:
                raise ValueError("invalid_harness_budget")
        if (isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float))
                or not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 600):
            raise ValueError("invalid_harness_timeout")


@dataclass(frozen=True)
class Action:
    kind: Literal["search", "bridge", "verify", "stop", "abstain"]
    slot_key: str | None = None
    query: str | None = None
    evidence_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("search", "bridge", "verify", "stop", "abstain"):
            raise ValueError("unknown_action")
        if self.kind in ("stop", "abstain"):
            if any(v is not None for v in (self.slot_key, self.query, self.evidence_id)):
                raise ValueError("invalid_terminal_action")
        else:
            _text(self.slot_key, "invalid_action_slot", 80)
            if self.kind == "search":
                _text(self.query, "invalid_action_query")
                if self.evidence_id is not None:
                    raise ValueError("invalid_action_evidence")
            elif self.kind == "bridge":
                _text(self.evidence_id, "invalid_action_evidence")
                if self.query is not None:
                    raise ValueError("invalid_action_query")
            elif self.query is not None or self.evidence_id is not None:
                raise ValueError("invalid_verify_action")


@dataclass(frozen=True)
class Snapshot:
    plan: QueryPlan
    verified: tuple[tuple[str, tuple[str, ...]], ...]
    missing: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    rounds: tuple[tuple[str, int], ...]
    actions_spent: int
    allowed_actions: tuple[Action, ...]
    contradictions: tuple[str, ...] = ()
    terminal_reason: str | None = None


class Policy(Protocol):
    policy_id: str
    def choose(self, state: Snapshot) -> Action: ...


class BoundedPolicy:
    """Untrained deterministic control baseline, never a semantic verifier."""
    policy_id = "bounded-control-v1-untrained"

    def choose(self, state: Snapshot) -> Action:
        return state.allowed_actions[0]


@dataclass(frozen=True)
class Event:
    action: Action
    candidate_ids: tuple[str, ...] = ()
    verified_ids: tuple[str, ...] = ()
    pre_rerank_ids: tuple[str, ...] = ()
    ranks: tuple[tuple[str, str, int, float], ...] = ()
    elapsed_ms: float = 0
    state_before: Snapshot | None = None
    state_after: Snapshot | None = None
    contradiction: bool = False


@dataclass(frozen=True)
class HarnessResult:
    status: str
    reason: str
    context: tuple[Evidence, ...]
    required_ids: tuple[str, ...]
    state: Snapshot
    events: tuple[Event, ...]
    elapsed_ms: float
