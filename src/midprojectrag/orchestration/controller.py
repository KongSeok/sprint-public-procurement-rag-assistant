"""Request-local, bounded search/bridge/verify controller."""
from __future__ import annotations

import time
import math
from collections.abc import Callable
from dataclasses import replace

from midprojectrag.evidence import EvidenceStore
from midprojectrag.retrieval import Candidate, IdentityReranker, select_context
from .types import (
    Action, BoundedPolicy, EnumerationVerifier, Event, HarnessConfig,
    HarnessResult, Policy, QueryPlan, Slot, Snapshot, Verification, Verifier,
)


class _DeadlineExceeded(Exception):
    pass


class Harness:
    def __init__(self, *, store: EvidenceStore, retriever, verifier: Verifier,
                 reranker=None, policy: Policy | None = None,
                 enumeration: EnumerationVerifier | None = None,
                 pack_verified_only: bool = False,
                 config: HarnessConfig = HarnessConfig(),
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.store = store
        self.retriever = retriever
        self.verifier = verifier
        self.reranker = reranker or IdentityReranker()
        self.policy = policy or BoundedPolicy()
        self.enumeration = enumeration
        if type(pack_verified_only) is not bool:
            raise ValueError("invalid_context_policy")
        self.pack_verified_only = pack_verified_only
        self.config = config
        self.clock = clock

    def run(self, plan: QueryPlan, *, request_deadline: float | None = None) -> HarnessResult:
        if not isinstance(plan, QueryPlan):
            raise ValueError("invalid_query_plan")
        if request_deadline is not None and (isinstance(request_deadline, bool)
                or not isinstance(request_deadline, (int, float)) or not math.isfinite(request_deadline)):
            raise ValueError("invalid_request_deadline")
        started = self.clock()
        deadline = min(request_deadline, started + self.config.timeout_seconds) if request_deadline is not None else started + self.config.timeout_seconds
        verified: dict[str, tuple[str, ...]] = {}
        candidates: dict[str, tuple[Candidate, ...]] = {}
        rounds = {s.key: 0 for s in plan.slots}
        pending: set[str] = set()
        bridged: set[tuple[str, str]] = set()
        executed: set[Action] = set()
        events: list[Event] = []
        actions_spent = 0
        slots = {s.key: s for s in plan.slots}
        contradictions: list[str] = []
        current_action = None
        state = None

        def allowed() -> tuple[Action, ...]:
            if len(verified) == len(slots):
                return (Action("stop"), Action("abstain"))
            options: list[Action] = []
            for slot in plan.slots:
                key = slot.key
                if key in verified:
                    continue
                if key in pending:
                    options.append(Action("verify", key))
                elif rounds[key] == 0:
                    options.append(Action("search", key, slot.query))
                else:
                    # Explicit provenance links only. A child can bridge through its parent.
                    for candidate in candidates.get(key, ()):
                        ev = self.store.get(candidate.evidence_id)
                        while ev.kind != "page" and ev.parent_id is not None:
                            ev = self.store.get(ev.parent_id)
                        page_id = ev.evidence_id if ev.kind == "page" else None
                        if page_id and (key, page_id) not in bridged:
                            if self.store.bridge(page_id, kind=slot.kind if slot.kind in ("table", "figure") else None):
                                options.append(Action("bridge", key, evidence_id=page_id))
                    if rounds[key] < self.config.max_rounds:
                        # A learned policy can choose a bounded slot-specific rewrite.
                        options.append(Action("search", key, slot.query))
            options.append(Action("abstain"))
            return tuple(dict.fromkeys(options))

        def snapshot() -> Snapshot:
            return Snapshot(plan, tuple(verified.items()),
                            tuple(s.key for s in plan.slots if s.key not in verified),
                            tuple(dict.fromkeys(c.evidence_id for cs in candidates.values() for c in cs)),
                            tuple(rounds.items()), actions_spent, allowed(), tuple(contradictions))

        def record(event: Event) -> None:
            events.append(replace(event, state_before=state, state_after=snapshot()))

        def finish(status: str, reason: str, context=()) -> HarnessResult:
            terminal = replace(snapshot(), allowed_actions=(), terminal_reason=reason)
            if current_action is not None and (not events or events[-1].state_before != state):
                events.append(Event(current_action, state_before=state, state_after=terminal))
            elif events:
                events[-1] = replace(events[-1], state_after=terminal)
            required = tuple(dict.fromkeys(i for ids in verified.values() for i in ids))
            return HarnessResult(status, reason, tuple(context), required, terminal, tuple(events),
                                 max(0, self.clock() - started) * 1000)

        def guard() -> None:
            if self.clock() >= deadline:
                raise _DeadlineExceeded("deadline_exceeded")

        def checked(cs, slot: Slot, *, before=None) -> tuple[Candidate, ...]:
            if not isinstance(cs, tuple) or len(cs) > self.config.max_candidates:
                raise ValueError("invalid_candidate_batch")
            seen: set[str] = set()
            for c in cs:
                if not isinstance(c, Candidate) or c.evidence_id in seen:
                    raise ValueError("invalid_candidate")
                ev = self.store.get(c.evidence_id)
                if ((plan.allowed_doc_ids is not None and ev.doc_id not in plan.allowed_doc_ids)
                        or (slot.doc_id and ev.doc_id != slot.doc_id)):
                    raise ValueError("candidate_outside_scope")
                if before is not None and c.evidence_id not in before:
                    raise ValueError("reranker_invented_evidence")
                seen.add(c.evidence_id)
            return cs

        try:
            while actions_spent < self.config.max_actions:
                current_action = None
                guard()
                state = snapshot()
                action = self.policy.choose(state)
                guard()
                if not isinstance(action, Action):
                    return finish("ERROR", "invalid_policy_action")
                legal = action in state.allowed_actions
                if action.kind == "search" and action.slot_key in slots:
                    legal = any(a.kind == "search" and a.slot_key == action.slot_key for a in state.allowed_actions)
                if not legal:
                    return finish("ERROR", "illegal_policy_action")
                actions_spent += 1
                current_action = action
                action_started = self.clock()
                if action.kind == "abstain":
                    record(Event(action))
                    return finish("ABSTAINED", "insufficient_evidence")
                if action.kind == "stop":
                    if state.missing:
                        return finish("ERROR", "premature_stop")
                    required = tuple(dict.fromkeys(i for ids in verified.values() for i in ids))
                    if plan.query_type == "list":
                        if self.enumeration is None:
                            return finish("ABSTAINED", "enumeration_capability_missing")
                        complete = self.enumeration.is_complete(plan, tuple(self.store.get(i) for i in required))
                        guard()
                        if complete is not True:
                            return finish("ABSTAINED", "enumeration_incomplete")
                    # Repack all verified refs, even if rerank would otherwise drop a document.
                    unique = {c.evidence_id: c for cs in candidates.values() for c in cs}
                    if self.pack_verified_only:
                        unique = {i: c for i, c in unique.items() if i in required}
                    packed = select_context(self.store, tuple(unique.values()),
                                            max_chars=self.config.max_context_chars,
                                            max_items=self.config.max_context_items,
                                            per_doc_limit=self.config.max_per_doc, required_ids=required)
                    guard()
                    record(Event(action, candidate_ids=tuple(e.evidence_id for e in packed)))
                    return finish("READY", "planned_support_retained", packed)

                key = action.slot_key
                slot = slots[key]
                if action.kind == "search":
                    if action in executed:
                        return finish("ABSTAINED", "no_progress")
                    executed.add(action)
                    scope = frozenset({slot.doc_id}) if slot.doc_id else plan.allowed_doc_ids
                    lane_ranks = ()
                    if callable(getattr(self.retriever, "search_with_lanes", None)):
                        batch = self.retriever.search_with_lanes(action.query, limit=self.config.max_candidates, allowed_doc_ids=scope)
                        cs = batch.candidates
                        lane_ranks = tuple((c.evidence_id, name, c.rank, c.score) for name, lane in batch.by_lane for c in lane)
                    else:
                        cs = self.retriever.search(action.query, limit=self.config.max_candidates, allowed_doc_ids=scope)
                    guard()
                    cs = checked(cs, slot)
                    before = tuple(c.evidence_id for c in cs)
                    record(Event(action, pre_rerank_ids=before,
                                 ranks=lane_ranks or tuple((c.evidence_id, c.lane, c.rank, c.score) for c in cs)))
                    ranked = self.reranker.rerank(action.query, cs)
                    guard()
                    ranked = checked(ranked, slot, before=frozenset(before))
                    candidates[key] = ranked
                    rounds[key] += 1
                    pending.add(key)
                    events[-1] = replace(events[-1], candidate_ids=tuple(c.evidence_id for c in ranked),
                                         elapsed_ms=(self.clock() - action_started) * 1000,
                                         state_after=snapshot())
                elif action.kind == "bridge":
                    parent = self.store.get(action.evidence_id)
                    if ((slot.doc_id and parent.doc_id != slot.doc_id)
                            or (plan.allowed_doc_ids is not None and parent.doc_id not in plan.allowed_doc_ids)):
                        return finish("ERROR", "bridge_outside_scope")
                    linked = self.store.bridge(action.evidence_id, kind=slot.kind if slot.kind in ("table", "figure") else None)
                    bridged.add((key, action.evidence_id))
                    # Linked objects first, retain source candidates within a hard count cap.
                    merged = {e.evidence_id: Candidate(e.evidence_id, 1.0, "bridge", n + 1) for n, e in enumerate(linked)}
                    for c in candidates.get(key, ()):
                        merged.setdefault(c.evidence_id, c)
                    candidates[key] = checked(tuple(merged.values())[:self.config.max_candidates], slot)
                    pending.add(key)
                    guard()
                    record(Event(action, tuple(c.evidence_id for c in candidates[key]),
                                        elapsed_ms=(self.clock() - action_started) * 1000))
                elif action.kind == "verify":
                    evs = tuple(self.store.get(c.evidence_id) for c in candidates.get(key, ()))
                    # A parent page may locate a table but does not satisfy a table-only slot.
                    supplied = tuple(e for e in evs if (slot.kind is None or e.kind == slot.kind) and e.text.strip())
                    prepare = getattr(self.verifier, "prepare", None)
                    if callable(prepare):
                        prepared = prepare(slot, supplied)
                        if (not isinstance(prepared, tuple) or any(e not in supplied for e in prepared)
                                or len({e.evidence_id for e in prepared}) != len(prepared)):
                            return finish("ERROR", "invalid_verifier_preparation")
                        supplied = prepared
                    guard()
                    # Preserve the actual input even when the provider times out.
                    record(Event(action, tuple(e.evidence_id for e in supplied)))
                    decision = self.verifier.verify(slot, supplied) if supplied else Verification(())
                    guard()
                    if not isinstance(decision, Verification):
                        return finish("ERROR", "invalid_verification")
                    if any(i not in {e.evidence_id for e in supplied} for i in decision.evidence_ids):
                        return finish("ERROR", "verification_outside_supplied_evidence")
                    pending.discard(key)
                    if decision.contradiction:
                        contradictions.append(key)
                        events[-1] = replace(events[-1], verified_ids=decision.evidence_ids,
                                     elapsed_ms=(self.clock() - action_started) * 1000, contradiction=True,
                                     state_after=snapshot())
                        return finish("ABSTAINED", "contradictory_evidence")
                    if decision.evidence_ids:
                        verified[key] = decision.evidence_ids
                    events[-1] = replace(events[-1], verified_ids=decision.evidence_ids,
                                 elapsed_ms=(self.clock() - action_started) * 1000, state_after=snapshot())
            return finish("ABSTAINED", "action_budget_exhausted")
        except _DeadlineExceeded:
            return finish("ABSTAINED", "deadline_exceeded")
        except TimeoutError:
            return finish("ERROR", "provider_or_contract_error")
        except Exception as error:
            # Provider messages may contain source text/paths/credentials. Do not expose them.
            if isinstance(error, ValueError) and str(error) == "context_budget_exceeded":
                return finish("ABSTAINED", "context_budget_exceeded")
            return finish("ERROR", "provider_or_contract_error")
