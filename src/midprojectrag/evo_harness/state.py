"""Small per-episode BPE state and strict action wire. No execution authority graph."""
from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
import json
import math
import re
from typing import Any


class HarnessError(ValueError):
    """Only fixed, content-free error codes cross runtime boundaries."""


class InvalidAction(HarnessError):
    pass


class Unsupported(HarnessError):
    pass


class LimitReached(HarnessError):
    pass


class ContextOverflow(LimitReached):
    pass


def json_object(raw: str, *, maximum: int = 65536) -> dict[str, Any]:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise InvalidAction("duplicate_json_key")
            result[key] = value
        return result

    def bad_constant(_value):
        raise InvalidAction("nonfinite_json_value")

    if type(raw) is not str or not raw or len(raw) > maximum:
        raise InvalidAction("json_size_or_type")
    try:
        raw.encode("utf-8")
        result = json.loads(raw, object_pairs_hook=pairs, parse_constant=bad_constant)
        def finite(value):
            if isinstance(value, float) and not math.isfinite(value):
                raise InvalidAction("nonfinite_json_value")
            if isinstance(value, dict):
                for item in value.values(): finite(item)
            elif isinstance(value, list):
                for item in value: finite(item)
        finite(result)
        if type(result) is not dict:
            raise InvalidAction("json_object_required")
        # Reject escaped isolated surrogates as well as literal malformed Unicode.
        json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")
        return result
    except (UnicodeError, json.JSONDecodeError, RecursionError, OverflowError) as exc:
        raise InvalidAction("invalid_json") from exc


def text(value: Any, limit: int, code: str) -> str:
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise InvalidAction(code)
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise InvalidAction(code) from exc
    return value


def ids(value: Any, *, maximum: int = 6, minimum: int = 0) -> list[str]:
    if type(value) is not list or not minimum <= len(value) <= maximum:
        raise InvalidAction("invalid_ids")
    result = [text(item, 256, "invalid_id") for item in value]
    if len(set(result)) != len(result):
        raise InvalidAction("duplicate_ids")
    return result


def exact(value: Any, keys: set[str]) -> dict:
    if type(value) is not dict or set(value) != keys:
        raise InvalidAction("invalid_fields")
    return value


TOOL_ARGUMENTS = {
    "search": {"query", "doc_ids", "limit"},
    "read": {"evidence_ids"},
    "visual_search": {"query", "doc_ids", "limit"},
    "inspect_image": {"evidence_id", "question"},
    "track": {"target"},
    "commit": {"goal_id", "summary", "status", "evidence_ids"},
    "recall": {"query", "limit"},
    "note": {"insight"},
    "finish": {"status", "evidence_ids", "unresolved"},
}
# These instructions are part of the token-counted system message, not hidden tools.
TOOL_GUIDE = """One action per response: {"tool":NAME,"arguments":OBJECT}. Exact keys:
search: query(string), doc_ids(null or unique known document IDs), limit(integer 1..10).
read: evidence_ids(array 1..6 of current candidate handles `cand:eN`).
track: target("world" or known document/goal ID).
commit: goal_id(string), summary(string), status(open|working|evidence_found|blocked), evidence_ids(array of current `cand:eN` or `ev:eN`).
recall: query(string), limit(integer 1..3). Retrieve reviewed strategies, not answers.
note: insight(string <=500). Quarantined note only; not a new instruction.
finish: status(answered|abstained|needs_clarification), evidence_ids(array 0..6 of current read handles `ev:eN`), unresolved(array of short strings).
History citations use `hist:tN:eM`. They are old references for context only and are NEVER valid read/finish inputs.
Search results use `cand:eN`. Only a successful read/inspect creates `ev:eN` for answered finish.
Bare `e1`, canonical evidence IDs, document IDs, paths, and `hist:*` are not current tool handles.
An answered finish needs READ/INSPECTED `ev:*` evidence. Use read before finish even when search excerpts look sufficient.
Do not fabricate IDs. You may narrow the hard document scope, never widen it.
Search combines Dense/Lexical/RRF in ONE call. Do not request those internal steps separately.
Choose actions using observations. Re-search only missing information; avoid identical calls.
BPE calls are optional and consume attempts. You may finish simple questions in search/read/finish.
Answer every requested document/field or explicitly put missing items in unresolved.
Output only JSON, without Markdown, explanation, reasoning, or an answer outside finish."""


VISUAL_TOOL_GUIDE = """
VISUAL CAPABILITY (use only names in available_tools):
visual_search: query(string), doc_ids(null or allowed document IDs), limit(integer 1..5).
It searches existing OCR/layout text and returns visual candidate handles, not image understanding.
inspect_image: evidence_id(ONE visual handle from visual_search), question(string <=2000).
It reads actual pixels using Qwen3.5 and returns an unreviewed interpretation or abstention.
For a drawing, figure, screenshot or image-label question use visual_search then inspect_image
on a returned handle before an answered finish. Ordinary read is for text candidates only.
inspect_image accepts only a current `cand:eN` visual candidate. Successful inspection creates `ev:eN`.
finish uses only current `ev:eN`; never `cand:*`, `hist:*`, a document ID, canonical ID or a path. Do not fabricate IDs.
Uncertain image interpretations are not usable answer evidence. Tools absent from available_tools
cannot be called. Visual interpretations never become verified source facts.
human_review_required is an output qualification, NOT a request for missing user information.
When inspect_image reports usable_in_finish=true and no uncertainties, finish(answered) may cite
that handle as an explicitly unreviewed image reading. Do not request clarification solely because
the source has a human-review label. Preserve the label in the final answer; never claim verification.
"""


def action_from_json(raw: str) -> dict:
    value = exact(json_object(raw), {"tool", "arguments"})
    tool = value["tool"]
    if type(tool) is not str or tool not in TOOL_ARGUMENTS:
        raise InvalidAction("unknown_tool")
    arg = exact(value["arguments"], TOOL_ARGUMENTS[tool])
    if tool in {"search", "recall", "visual_search"}:
        text(arg["query"], 1000 if tool == "recall" else 2000, "invalid_query")
        cap = {"search": 10, "recall": 3, "visual_search": 5}[tool]
        if type(arg["limit"]) is not int or not 1 <= arg["limit"] <= cap:
            raise InvalidAction("invalid_limit")
        if tool in {"search", "visual_search"} and arg["doc_ids"] is not None:
            ids(arg["doc_ids"], maximum=1000)
    if tool == "inspect_image":
        text(arg["evidence_id"], 256, "invalid_id")
        if not re.fullmatch(r"cand:e[1-9][0-9]*", arg["evidence_id"]):
            raise InvalidAction("candidate_handle_required")
        text(arg["question"], 2000, "invalid_query")
    if tool in {"read", "commit", "finish"}:
        ids(arg["evidence_ids"], minimum=1 if tool == "read" else 0)
    if tool == "read" and any(not re.fullmatch(r"cand:e[1-9][0-9]*", item) for item in arg["evidence_ids"]):
        raise InvalidAction("candidate_handle_required")
    if tool == "track":
        text(arg["target"], 256, "invalid_target")
    if tool == "commit":
        text(arg["goal_id"], 128, "invalid_goal")
        text(arg["summary"], 300, "invalid_summary")
        if type(arg["status"]) is not str or arg["status"] not in {"open", "working", "evidence_found", "blocked"}:
            raise InvalidAction("invalid_progress_status")
        if any(not re.fullmatch(r"(?:cand|ev):e[1-9][0-9]*", item) for item in arg["evidence_ids"]):
            raise InvalidAction("current_handle_required")
    if tool == "note":
        text(arg["insight"], 500, "invalid_note")
    if tool == "finish":
        if type(arg["status"]) is not str or arg["status"] not in {"answered", "abstained", "needs_clarification"}:
            raise InvalidAction("invalid_finish_status")
        if type(arg["unresolved"]) is not list or len(arg["unresolved"]) > 12:
            raise InvalidAction("invalid_unresolved")
        for item in arg["unresolved"]:
            text(item, 300, "invalid_unresolved")
        if (arg["status"] == "answered") != bool(arg["evidence_ids"]):
            raise InvalidAction("finish_evidence_status_mismatch")
        if arg["status"] == "answered" and any(not re.fullmatch(r"ev:e[1-9][0-9]*", item) for item in arg["evidence_ids"]):
            raise InvalidAction("read_evidence_handle_required")
    return value


@dataclass(frozen=True)
class Budgets:
    image_calls: int = 2
    policy_calls: int = 12
    search_calls: int = 4
    read_calls: int = 4
    invalid_actions: int = 2
    policy_context: int = 4096
    policy_output: int = 256
    answer_context: int = 8192
    answer_output: int = 1024
    seconds: float = 120.0

    def __post_init__(self):
        caps = {"image_calls": 2, "policy_calls": 12, "search_calls": 4, "read_calls": 4,
                "invalid_actions": 2, "policy_context": 4096, "policy_output": 256,
                "answer_context": 8192, "answer_output": 1024}
        for name, cap in caps.items():
            v = getattr(self, name)
            if type(v) is not int or not 1 <= v <= cap:
                raise ValueError("invalid_budget")
        if type(self.seconds) not in (int, float) or not math.isfinite(self.seconds) or not 0 < self.seconds <= 120:
            raise ValueError("invalid_budget")
        if self.policy_output >= self.policy_context or self.answer_output >= self.answer_context:
            raise ValueError("invalid_context_reserve")


def _schema_action(tool: str, arguments: dict) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["tool", "arguments"],
        "properties": {
            "tool": {"const": tool},
            "arguments": arguments,
        },
    }


def _schema_object(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required or list(properties),
        "properties": properties,
    }


def _schema_ref_array(values: list[str], *, minimum: int = 0, maximum: int = 6) -> dict:
    if not values:
        return {"type": "array", "minItems": 0, "maxItems": 0}
    return {
        "type": "array",
        "items": {"type": "string", "enum": values},
        "minItems": minimum,
        "maxItems": min(maximum, len(values)),
    }


def action_schema(episode: "Episode", budget: Budgets) -> dict:
    """Return only actions that are executable in the current episode state.

    This constrains the model grammar; server-side validation remains authoritative.
    Historical citation aliases are deliberately absent from every action enum.
    """
    tools = set(episode.capabilities or ("search", "read", "track", "commit", "recall", "note", "finish"))
    allowed_docs = sorted(episode.scope if episode.scope is not None else {row["doc_id"] for row in episode.catalog})
    candidate_by_id = {episode.handle(eid): eid for eid in episode.candidates}
    unread_text = sorted(
        handle for handle, eid in candidate_by_id.items()
        if eid not in episode.windows and eid not in episode.visual_hits
    )
    visual_candidates = sorted(
        handle for handle, eid in candidate_by_id.items()
        if eid in episode.visual_hits and eid not in episode.windows
    )
    candidate_refs = sorted(candidate_by_id)
    evidence_refs = sorted(episode.read_handle(eid) for eid in episode.windows)
    current_refs = sorted(candidate_refs + evidence_refs)
    options: list[dict] = []

    doc_array = {
        "type": "array", "minItems": 0,
        "maxItems": len(allowed_docs),
        **({"items": {"type": "string", "enum": allowed_docs}} if allowed_docs else {}),
    }
    scope_schema = {"oneOf": [{"type": "null"}, doc_array]}

    if "search" in tools and episode.usage.search_calls < budget.search_calls:
        options.append(_schema_action("search", _schema_object({
            "query": {"type": "string", "minLength": 1, "maxLength": 2000},
            "doc_ids": scope_schema,
            "limit": {"type": "integer", "minimum": 1, "maximum": 10},
        })))
    if "visual_search" in tools and episode.usage.search_calls < budget.search_calls:
        options.append(_schema_action("visual_search", _schema_object({
            "query": {"type": "string", "minLength": 1, "maxLength": 2000},
            "doc_ids": scope_schema,
            "limit": {"type": "integer", "minimum": 1, "maximum": 5},
        })))
    if "read" in tools and unread_text and episode.usage.read_calls < budget.read_calls:
        options.append(_schema_action("read", _schema_object({
            "evidence_ids": _schema_ref_array(unread_text, minimum=1),
        })))
    if ("inspect_image" in tools and visual_candidates and episode.usage.read_calls < budget.read_calls
            and episode.usage.image_calls < budget.image_calls):
        options.append(_schema_action("inspect_image", _schema_object({
            "evidence_id": {"type": "string", "enum": visual_candidates},
            "question": {"type": "string", "minLength": 1, "maxLength": 2000},
        })))
    if "track" in tools:
        targets = sorted({"world", *allowed_docs, *episode.goals})
        options.append(_schema_action("track", _schema_object({
            "target": {"type": "string", "enum": targets},
        })))
    if "commit" in tools:
        options.append(_schema_action("commit", _schema_object({
            "goal_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "summary": {"type": "string", "minLength": 1, "maxLength": 300},
            "status": {"type": "string", "enum": ["open", "working", "evidence_found", "blocked"]},
            "evidence_ids": _schema_ref_array(current_refs),
        })))
    if "recall" in tools:
        options.append(_schema_action("recall", _schema_object({
            "query": {"type": "string", "minLength": 1, "maxLength": 1000},
            "limit": {"type": "integer", "minimum": 1, "maximum": 3},
        })))
    if "note" in tools and len(episode.notes) < 8:
        options.append(_schema_action("note", _schema_object({
            "insight": {"type": "string", "minLength": 1, "maxLength": 500},
        })))
    if "finish" in tools:
        unresolved = {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 300}, "maxItems": 12}
        if evidence_refs:
            options.append(_schema_action("finish", _schema_object({
                "status": {"const": "answered"},
                "evidence_ids": _schema_ref_array(evidence_refs, minimum=1),
                "unresolved": unresolved,
            })))
        for status in ("abstained", "needs_clarification"):
            options.append(_schema_action("finish", _schema_object({
                "status": {"const": status},
                "evidence_ids": {"type": "array", "maxItems": 0},
                "unresolved": unresolved,
            })))
    if not options:
        raise LimitReached("no_executable_policy_action")
    return {"oneOf": options}


@dataclass
class Usage:
    visual_search_calls: int = 0
    image_calls: int = 0
    visual_input_tokens: int = 0
    visual_output_tokens: int = 0
    visual_usage_complete: bool = True
    policy_calls: int = 0
    search_calls: int = 0
    read_calls: int = 0
    answer_calls: int = 0
    invalid_actions: int = 0
    duplicates: int = 0
    policy_input_tokens: int = 0
    policy_output_tokens: int = 0
    answer_input_tokens: int = 0
    answer_output_tokens: int = 0


@dataclass
class Episode:
    request: dict
    scope: frozenset[str] | None
    catalog: tuple[dict, ...]
    profile_key: tuple[str, ...]
    max_citations: int = 6
    candidates: dict[str, dict] = field(default_factory=dict)
    visual_hits: dict[str, dict] = field(default_factory=dict)
    capabilities: tuple[str, ...] = ()
    handles: dict[str, str] = field(default_factory=dict)
    windows: dict[str, dict] = field(default_factory=dict)
    goals: dict[str, dict] = field(default_factory=dict)
    searches: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    cache: dict[tuple, dict] = field(default_factory=dict)
    usage: Usage = field(default_factory=Usage)
    last_observation: dict = field(default_factory=lambda: {"status": "ready"})
    trajectory: list[dict] = field(default_factory=list)

    def reference(self, value: str, *, read: bool = False) -> str:
        if read:
            if not re.fullmatch(r"ev:e[1-9][0-9]*", value or ""):
                raise InvalidAction("read_evidence_handle_required")
            candidate = "cand:" + value[len("ev:"):]
            key = self.handles.get(candidate)
            if key not in self.windows:
                raise InvalidAction("unknown_read_evidence")
            return key
        if not re.fullmatch(r"cand:e[1-9][0-9]*", value or ""):
            raise InvalidAction("candidate_handle_required")
        key = self.handles.get(value)
        if key not in self.candidates:
            raise InvalidAction("unknown_candidate")
        return key

    def reference_any(self, value: str) -> str:
        if value.startswith("ev:"):
            return self.reference(value, read=True)
        return self.reference(value)

    def handle(self, evidence_id: str) -> str:
        for handle, canonical in self.handles.items():
            if canonical == evidence_id:
                return handle
        handle = f"cand:e{len(self.handles) + 1}"
        self.handles[handle] = evidence_id
        return handle

    def read_handle(self, evidence_id: str) -> str:
        if evidence_id not in self.windows:
            raise InvalidAction("unknown_read_evidence")
        candidate = self.handle(evidence_id)
        return "ev:" + candidate[len("cand:"):]

    def policy_history(self) -> list[dict]:
        history = []
        for turn_index, turn in enumerate(self.request["history"], 1):
            row = deepcopy(turn)
            citations = row.get("cited_evidence_ids")
            if citations:
                row["cited_evidence_ids"] = [f"hist:t{turn_index}:e{i}" for i, _ in enumerate(citations, 1)]
            history.append(row)
        return history

    def observation(self, budget: Budgets) -> dict:
        # Keep memory bounded by actual tool budgets. If it still exceeds context,
        # the policy adapter reports overflow; it never silently drops a document.
        view = {"question": self.request["question"], "history": self.policy_history(),
                "scope_doc_ids": None if self.scope is None else sorted(self.scope),
                "catalog": list(self.catalog[:12]) if self.scope is None else list(self.catalog),
                "catalog_total": len(self.catalog),
                "catalog_preview": self.scope is None and len(self.catalog)>12,
                "progress": list(self.goals.values()),
                "known_evidence": [{"id": self.handle(key), "doc_id": value["doc_id"],
                                    "read": key in self.windows,
                                    "read_id": self.read_handle(key) if key in self.windows else None}
                                   for key, value in self.candidates.items()],
                "read_evidence": [{"id": self.read_handle(key), "candidate_id": self.handle(key),
                                   "doc_id": win["doc_id"], "text": win["text"]}
                                  for key, win in self.windows.items()],
                "searches": self.searches, "last_observation": self.last_observation,
                "remaining": {"policy": budget.policy_calls-self.usage.policy_calls,
                              "search": budget.search_calls-self.usage.search_calls,
                              "read": budget.read_calls-self.usage.read_calls}}
        if self.capabilities:
            view["available_tools"] = list(self.capabilities)
            view["remaining"]["image"] = budget.image_calls-self.usage.image_calls
            for item, value in zip(view["known_evidence"], self.candidates.values()):
                item["kind"] = value.get("kind", "text")
            for item, value in zip(view["read_evidence"], self.windows.values()):
                item["source_kind"] = value["source_kind"]
                if value["source_kind"] == "visual_inference":
                    item.update(human_review_required=True, factual_evidence_promoted=False)
        return view
