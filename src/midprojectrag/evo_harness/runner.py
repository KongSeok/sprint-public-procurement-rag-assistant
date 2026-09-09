"""A bounded single-action loop. State bookkeeping is not a learned policy."""
from __future__ import annotations

from dataclasses import asdict
import json
import math
import time
from typing import Callable

from .experience import Experience
from .policy import AnswerComposer, LLMPolicy
from .state import (Budgets, ContextOverflow, Episode, HarnessError, InvalidAction,
                    LimitReached, Unsupported, action_from_json)
from .tools import HotlineTools


class EpisodeRunner:
    def __init__(self, tools: HotlineTools, policy: LLMPolicy, answer: AnswerComposer,
                 *, budgets: Budgets | None = None, experience: Experience | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.tools, self.policy, self.answer = tools, policy, answer
        self.budgets, self.experience = budgets or Budgets(), experience or Experience()
        self.clock = clock
        if policy.backend.identity.canonical_model != answer.backend.identity.canonical_model:
            raise ValueError("policy_answer_model_mismatch")
        if policy.backend.identity != answer.backend.identity:
            raise ValueError("same_profile_policy_answer_required")

    def run(self, request: dict, *, follow_up: bool = False,
            deadline: float | None = None, record_trajectory: bool = False) -> dict:
        if deadline is not None and (type(deadline) not in (int,float) or not math.isfinite(deadline)):
            raise ValueError("invalid_deadline")
        started = self.clock()
        end = min(started+self.budgets.seconds, deadline) if deadline is not None else started+self.budgets.seconds
        episode = None
        events = []

        def remaining():
            value = end-self.clock()
            if value <= 0:
                raise TimeoutError("episode_deadline")
            return value

        def result(status, code=None, response=None):
            if events and events[-1]["outcome"] == "attempted" and status not in {"answered", "abstained", "needs_clarification"}:
                events[-1].update(outcome=status, code=code)
            output = {"status": status, "code": code, "response": response,
                      "wall_seconds": self.clock()-started, "controller_executed": False,
                      "policy_kind": "prompt_time", "trained_policy": False,
                      "synthetic_backend": self.policy.backend.identity.synthetic,
                      "model": asdict(self.policy.backend.identity),
                      "experience_version": self.experience.version,
                      "experience_sha256": self.experience.fingerprint,
                      "actions": events,
                      "timings": {name: sum(event.get(name, 0.0) for event in events)
                                  for name in ("policy_seconds", "tools_seconds", "answer_seconds")},
                      "usage": asdict(episode.usage) if episode is not None else {},
                      "semantic_verified": False}
            if episode is not None:
                output["quarantined_notes"] = list(episode.notes)
                output["progress"] = list(episode.goals.values())
                if record_trajectory:
                    output["trajectory"] = episode.trajectory
            return output

        try:
            remaining()
            episode = self.tools.begin(request, follow_up=follow_up)
            if episode.scope == frozenset():
                return result("abstained", "empty_scope", {"status": "abstained", "answer": "", "citations": []})
            while episode.usage.policy_calls < self.budgets.policy_calls:
                remaining()
                action = None
                event = {"ordinal": len(events)+1, "outcome": "attempted"}
                events.append(event)
                tick = self.clock()
                try:
                    phase_started = self.clock()
                    try:
                        raw = self.policy.propose(episode, self.budgets, remaining)
                    finally:
                        event["policy_seconds"] = self.clock()-phase_started
                    action = action_from_json(raw)
                    event.update(tool=action["tool"], arguments=action["arguments"])
                    remaining()
                    if action["tool"] == "finish":
                        args = action["arguments"]
                        if args["status"] != "answered":
                            event["outcome"] = "completed"
                            return result(args["status"], response={"status": args["status"], "answer": "",
                                          "citations": [], "unresolved": args["unresolved"]})
                        packet = self.tools.packet(episode, args["evidence_ids"])
                        try:
                            phase_started = self.clock()
                            try:
                                response = self.answer.compose(episode, packet, args["unresolved"], self.budgets, remaining)
                            finally:
                                event["answer_seconds"] = self.clock()-phase_started
                        except ContextOverflow:
                            episode.last_observation = {"error": "answer_context_budget_exceeded",
                                                        "omitted_evidence_ids": args["evidence_ids"],
                                                        "generation_attempted": False}
                            event["outcome"] = "context_overflow"
                            continue
                        event["outcome"] = "completed"
                        return result(response["status"], response=response)
                    phase_started = self.clock()
                    try:
                        observation = self.tools.dispatch(episode, action, self.budgets, remaining, self.experience)
                    finally:
                        event["tools_seconds"] = self.clock()-phase_started
                    remaining()
                    episode.last_observation = observation
                    event.update(outcome="completed", observation=observation)
                except InvalidAction as exc:
                    # Bad JSON/tool use may be corrected by the NEXT policy turn;
                    # this is not retrying an external operation or hiding failure.
                    episode.usage.invalid_actions += 1
                    episode.last_observation = {"error": str(exc), "invalid_actions": episode.usage.invalid_actions}
                    event.update(outcome="invalid_action", code=str(exc))
                    if episode.usage.invalid_actions >= self.budgets.invalid_actions:
                        return result("invalid_action_limit", str(exc))
                finally:
                    event["wall_seconds"] = self.clock()-tick
            return result("budget_exhausted", "policy_attempt_budget_exhausted")
        except TimeoutError:
            if events:
                events[-1]["outcome"] = "timeout"
            return result("timeout", "episode_deadline")
        except Unsupported as exc:
            return result("needs_clarification" if str(exc).startswith("followup_") else "unsupported", str(exc))
        except LimitReached as exc:
            return result("budget_exhausted", str(exc))
        except (HarnessError, ValueError, TypeError, KeyError) as exc:
            # Do not echo provider/source contents in exceptions. Known internal
            # HarnessError codes are fixed; other failures receive type-only code.
            code = str(exc) if isinstance(exc, HarnessError) else "runtime_contract_error"
            if events and events[-1]["outcome"] == "attempted":
                events[-1].update(outcome="error", code=code)
            return result("error", code)
        except Exception:
            if events and events[-1]["outcome"] == "attempted":
                events[-1].update(outcome="error", code="provider_error")
            return result("error", "provider_error")

    def run_fixed(self, request: dict, *, follow_up: bool = False,
                  deadline: float | None = None) -> dict:
        """Same tools/model/packet, one search/read/answer; no policy inference."""
        if deadline is not None and (type(deadline) not in (int, float) or not math.isfinite(deadline)):
            raise ValueError("invalid_deadline")
        started = self.clock()
        end = min(started+self.budgets.seconds, deadline) if deadline is not None else started+self.budgets.seconds
        episode = None

        def remaining():
            value = end-self.clock()
            if value <= 0:
                raise TimeoutError("episode_deadline")
            return value

        try:
            episode = self.tools.begin(request, follow_up=follow_up)
            remaining()
            observation = self.tools.search(episode, {"query": episode.request["question"], "doc_ids": None, "limit": 6},
                                            self.budgets, remaining)
            refs = [row["id"] for row in observation["candidates"]]
            if not refs:
                response = {"status": "abstained", "answer": "", "citations": []}
            else:
                self.tools.read(episode, {"evidence_ids": refs}, self.budgets, remaining)
                packet = self.tools.packet(episode, refs)
                response = self.answer.compose(episode, packet, [], self.budgets, remaining)
            return {"status": response["status"], "response": response,
                    "usage": asdict(episode.usage), "wall_seconds": self.clock()-started,
                    "policy_kind": "fixed_control", "controller_executed": False,
                    "synthetic_backend": self.answer.backend.identity.synthetic,
                    "trained_policy": False,
                    "model": asdict(self.answer.backend.identity), "semantic_verified": False}
        except Exception as exc:
            status = "timeout" if isinstance(exc, TimeoutError) else "budget_exhausted" if isinstance(exc, LimitReached) else "unsupported" if isinstance(exc, Unsupported) else "error"
            return {"status": status, "code": str(exc) if isinstance(exc, HarnessError) else "fixed_control_error",
                    "usage": asdict(episode.usage) if episode else {}, "wall_seconds": self.clock()-started,
                    "policy_kind": "fixed_control", "controller_executed": False}
