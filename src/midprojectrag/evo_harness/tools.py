"""RAG actions over existing public hybrid retrieval and EvidenceStore APIs."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Callable

from midprojectrag.runtime_integrity import RuntimeRequest, ResolvedScope
from midprojectrag.retrieval.contracts import SearchResult

from .experience import Experience
from .state import Budgets, Episode, HarnessError, InvalidAction, LimitReached, Unsupported


class HotlineTools:
    def __init__(self, store, retriever, *, catalog: dict[str, str] | None = None,
                 identity: str = "hotline-public-hybrid-v1", window_chars: int = 1600,
                 lane_k: int = 10):
        if type(window_chars) is not int or not 128 <= window_chars <= 6000:
            raise ValueError("invalid_window_budget")
        if type(lane_k) is not int or not 1 <= lane_k <= 50:
            raise ValueError("invalid_lane_budget")
        self.store, self.retriever = store, retriever
        self.window_chars, self.lane_k = window_chars, lane_k
        self.universe = frozenset(store.doc_ids)
        catalog = catalog or {}
        if set(catalog) - self.universe:
            raise ValueError("catalog_scope_mismatch")
        self.catalog = tuple({"doc_id": doc_id, "title": str(catalog.get(doc_id, ""))[:180]}
                             for doc_id in sorted(self.universe))
        self.profile_key = (str(store.bundle_sha256), identity, str(window_chars), str(lane_k))

    def _document_of(self, evidence_id):
        return self.store.get(evidence_id).doc_id

    def begin(self, raw: dict, *, follow_up: bool = False) -> Episode:
        request = RuntimeRequest.from_dict(raw).to_dict()
        if request["metadata_filters"]:
            raise Unsupported("metadata_filters_not_implemented")
        options = request["options"]
        if options.get("allow_global_fallback", False):
            raise Unsupported("global_fallback_not_implemented")
        if options.get("profile", "evo-hotline-qwen35-v1") != "evo-hotline-qwen35-v1":
            raise Unsupported("unsupported_profile")
        maximum = options.get("max_citations", 6)
        if maximum > 6:
            raise Unsupported("citation_limit_exceeds_profile")
        scope = None if request["document_scope"]["mode"] == "all" else frozenset(request["document_scope"]["doc_ids"])
        if scope is not None and not scope <= self.universe:
            raise InvalidAction("unknown_scope_document")
        if follow_up or request["prior_citation_state"] is not None:
            assistants = [turn for turn in request["history"] if turn["role"] == "assistant"]
            if not assistants:
                raise Unsupported("followup_citations_required")
            last = assistants[-1]
            prior_ids = last.get("cited_evidence_ids", [])
            prior_docs = frozenset(last.get("cited_doc_ids", []))
            if not prior_ids or not prior_docs or not prior_docs <= self.universe:
                raise Unsupported("followup_citations_required")
            try:
                actual_docs = frozenset(self._document_of(eid) for eid in prior_ids)
            except (KeyError, ValueError) as exc:
                raise Unsupported("followup_citations_invalid") from exc
            if actual_docs != prior_docs:
                raise Unsupported("followup_citations_invalid")
            # Prior state is merely a consistency assertion. The latest explicit
            # assistant's actual store-resolved citations determine the scope.
            prior = request["prior_citation_state"]
            if prior is not None:
                if (frozenset(prior.get("cited_doc_ids", [])) != prior_docs
                        or set(prior.get("cited_evidence_ids", [])) != set(prior_ids)
                        or (prior.get("assistant_turn_id") is not None
                            and prior["assistant_turn_id"] != last.get("turn_id"))):
                    raise Unsupported("followup_state_mismatch")
            scope = prior_docs if scope is None else scope & prior_docs
        catalog = tuple(row for row in self.catalog if scope is None or row["doc_id"] in scope)
        return Episode(request=request, scope=scope, catalog=catalog,
                       profile_key=self.profile_key, max_citations=maximum)

    def _scope(self, episode: Episode, doc_ids: list[str] | None) -> frozenset[str] | None:
        if doc_ids is None:
            return episode.scope
        narrowed = frozenset(doc_ids)
        if not narrowed <= self.universe:
            raise InvalidAction("unknown_scope_document")
        if episode.scope is not None and not narrowed <= episode.scope:
            raise InvalidAction("scope_escape")
        return narrowed

    def dispatch(self, episode: Episode, action: dict, budget: Budgets,
                 remaining: Callable[[], float], experience: Experience) -> dict:
        tool, arg = action["tool"], action["arguments"]
        if tool == "search":
            return self.search(episode, arg, budget, remaining)
        if tool == "read":
            return self.read(episode, arg, budget, remaining)
        if tool == "track":
            target = arg["target"]
            if target != "world" and target not in episode.goals and target not in {r["doc_id"] for r in episode.catalog}:
                raise InvalidAction("unknown_track_target")
            return {"target": target, "goals": list(episode.goals.values()),
                    "evidence": [{"id": episode.handle(eid), "doc_id": row["doc_id"],
                                  "read": eid in episode.windows} for eid, row in episode.candidates.items()],
                    "searches": deepcopy(episode.searches), "semantic_verified": False}
        if tool == "commit":
            if arg["goal_id"] not in episode.goals and len(episode.goals) >= 12:
                raise InvalidAction("progress_capacity")
            evidence = [episode.reference(eid) for eid in arg["evidence_ids"]]
            row = {**arg, "evidence_ids": [episode.handle(eid) for eid in evidence], "semantic_verified": False}
            episode.goals[arg["goal_id"]] = row
            return {"goal": deepcopy(row)}
        if tool == "recall":
            return experience.recall(arg["query"], arg["limit"])
        if tool == "note":
            if len(episode.notes) >= 8:
                raise InvalidAction("note_capacity")
            episode.notes.append(arg["insight"])
            return {"status": "quarantined", "count": len(episode.notes), "bank_modified": False}
        raise InvalidAction("unsupported_dispatch_tool")

    def search(self, episode: Episode, arg: dict, budget: Budgets, remaining: Callable[[], float]) -> dict:
        scope = self._scope(episode, arg["doc_ids"])
        key = ("search", *episode.profile_key, arg["query"],
               None if scope is None else tuple(sorted(scope)), arg["limit"])
        if key in episode.cache:
            episode.usage.duplicates += 1
            return {**deepcopy(episode.cache[key]), "duplicate": True}
        remaining()
        if scope == frozenset():
            result = {"candidates": [], "scope_doc_ids": [], "empty_scope": True, "duplicate": False}
            episode.cache[key] = deepcopy(result)
            return result
        if episode.usage.search_calls >= budget.search_calls:
            raise LimitReached("search_budget_exhausted")
        episode.usage.search_calls += 1
        resolved = ResolvedScope.from_allowed(scope, origin="combined" if scope is not None else "all")
        # This is the same public hybrid used by hotline composition; no
        # Controller decision, execution, claim, obligation or history is created.
        raw = self.retriever.search(arg["query"], dense_k=self.lane_k,
                                    lexical_k=self.lane_k, scope=resolved)
        remaining()
        if type(raw) is not SearchResult:
            raise HarnessError("invalid_retrieval_result")
        selected = raw.candidates[:arg["limit"]]
        rows = []
        for candidate in selected:
            try:
                evidence = self.store.get(candidate.evidence_id)
            except (KeyError, ValueError) as exc:
                raise HarnessError("retrieval_evidence_missing") from exc
            if (evidence.doc_id != candidate.doc_id or candidate.doc_id not in self.universe
                    or (scope is not None and candidate.doc_id not in scope)):
                raise HarnessError("retrieval_scope_mismatch")
            row = {"evidence_id": evidence.evidence_id, "doc_id": evidence.doc_id,
                   "locator": evidence.locator.to_dict(), "kind": evidence.kind,
                   "excerpt": evidence.text[:280]}
            rows.append(row)
        # Commit only a fully checked result, never a partial invalid response.
        for row in rows:
            episode.candidates[row["evidence_id"]] = row
        result = {"candidates": [{"id": episode.handle(row["evidence_id"]), "doc_id": row["doc_id"],
                                  "excerpt": row["excerpt"], "kind": row["kind"]} for row in rows],
                  "scope_doc_ids": None if scope is None else sorted(scope), "duplicate": False}
        episode.searches.append({"query": arg["query"], "doc_ids": result["scope_doc_ids"],
                                 "found": [row["id"] for row in result["candidates"]]})
        episode.cache[key] = deepcopy(result)
        return result

    def read(self, episode: Episode, arg: dict, budget: Budgets, remaining: Callable[[], float]) -> dict:
        evidence_ids = tuple(episode.reference(eid) for eid in arg["evidence_ids"])
        if len(set(evidence_ids)) != len(evidence_ids):
            raise InvalidAction("duplicate_evidence_alias")
        key = ("read", *episode.profile_key, evidence_ids)
        if key in episode.cache:
            episode.usage.duplicates += 1
            return {**deepcopy(episode.cache[key]), "duplicate": True}
        if len(set(episode.windows) | set(evidence_ids)) > 6:
            raise InvalidAction("read_memory_capacity")
        remaining()
        if episode.usage.read_calls >= budget.read_calls:
            raise LimitReached("read_budget_exhausted")
        episode.usage.read_calls += 1
        windows = {}
        for eid in evidence_ids:
            seed = self.store.get(eid)
            if seed.kind not in {"text", "page"}:
                raise Unsupported("specialist_evidence_not_supported")
            parent = self.store.parent(seed.parent_id)
            span = seed.locator.char_range
            if (seed.doc_id != parent.doc_id or (episode.scope is not None and seed.doc_id not in episode.scope)
                    or span is None or len(span) != 2):
                raise HarnessError("read_provenance_invalid")
            start, end = span
            if not 0 <= start < end <= len(parent.text) or parent.text[start:end] != seed.text:
                raise HarnessError("read_source_span_mismatch")
            if end-start > self.window_chars:
                raise LimitReached("read_window_budget_exceeded")
            low = max(0, start-(self.window_chars-(end-start))//2)
            high = min(len(parent.text), low+self.window_chars)
            low = max(0, high-self.window_chars)
            locator = parent.locator.to_dict()
            locator["char_range"] = [low, high]
            windows[eid] = {"evidence_id": eid, "doc_id": seed.doc_id, "parent_id": parent.parent_id,
                            "text": parent.text[low:high], "source_block_ids": list(parent.source_block_ids),
                            "retrieval_seed_chunk_ids": list(seed.source_chunk_ids), "locator": locator,
                            "source_kind": "parent_window",
                            "char_range_base": "parent_text", "seed_locator": seed.locator.to_dict(),
                            "content_sha256": sha256(parent.text[low:high].encode()).hexdigest(),
                            "truncated": low > 0 or high < len(parent.text), "semantic_verified": False}
        remaining()
        episode.windows.update(windows)
        # The complete read text is in Episode.observation.read_evidence. Avoid
        # sending it twice in last_observation.
        result = {"read": [episode.handle(eid) for eid in evidence_ids], "duplicate": False,
                  "semantic_verified": False}
        episode.cache[key] = deepcopy(result)
        return result

    def packet(self, episode: Episode, references: list[str]) -> list[dict]:
        canonical = [episode.reference(eid, read=True) for eid in references]
        if len(set(canonical)) != len(canonical):
            raise InvalidAction("duplicate_evidence_alias")
        packet, seen = [], {}
        for eid in canonical:
            window = deepcopy(episode.windows[eid])
            key = (("visual_inference", eid) if window["source_kind"] == "visual_inference"
                   else (window["parent_id"], tuple(window["locator"]["char_range"])))
            if key in seen:
                # All seed IDs remain explicitly mapped to the same actual window.
                packet[seen[key]]["evidence_ids"].append(eid)
                continue
            seen[key] = len(packet)
            window.update(label=f"S{len(packet)+1}", evidence_ids=[eid])
            packet.append(window)
        return packet
