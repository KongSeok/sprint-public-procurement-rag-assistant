"""Policy-selected visual tools; reuse the imported index and image QA contracts."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from midprojectrag.evidence import EvidenceStore
from midprojectrag.indexing import visual_ocr_index as index_api
from midprojectrag.stacks.local import visual_qa

from .state import HarnessError, InvalidAction, LimitReached, Unsupported
from .tools import HotlineTools


class VisualAccess:
    """Loaded index identity plus injected bounded search and pixel inference.

    Search may run in the existing KURE Python; image inference uses the same
    loaded backend as the policy. Neither function is a model-selected path.
    """
    def __init__(self, *, index_dir, private_root, crop_root, searcher, inspector):
        self.common = dict(index_dir=Path(index_dir), private_root=Path(private_root),
                           crop_root=Path(crop_root))
        index, _bound, metadata = index_api.load(**self.common)
        self.chunks = {row["chunk_id"]: row for row in index.chunks}
        self.doc_ids = frozenset(row["doc_id"] for row in index.chunks)
        self.identity = sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
        self.searcher, self.inspector = searcher, inspector

    @staticmethod
    def evidence_id(chunk_id):
        return "visual/" + chunk_id

    def document_of(self, evidence_id):
        if not evidence_id.startswith("visual/"):
            raise KeyError(evidence_id)
        return self.chunks[evidence_id[len("visual/"):]]["doc_id"]

    def search(self, query, scope, limit, remaining):
        remaining()
        result = self.searcher(query=query, allowed_doc_ids=scope, top_k=limit, remaining=remaining)
        remaining()
        if type(result) is not dict or result.get("query") != query or type(result.get("hits")) is not list:
            raise HarnessError("visual_search_result_invalid")
        if len(result["hits"]) > limit:
            raise HarnessError("visual_search_limit_violation")
        occurrences = set()
        for hit in result["hits"]:
            chunk = self.chunks.get(hit.get("chunk_id"))
            if (chunk is None or hit.get("citation") != chunk["citation"]
                    or hit.get("text") != chunk["text"] or hit.get("evidence_type") != chunk["evidence_type"]
                    or (scope is not None and chunk["doc_id"] not in scope)):
                raise HarnessError("visual_search_scope_or_source_mismatch")
            if chunk["occurrence_id"] in occurrences:
                raise HarnessError("visual_duplicate_occurrence")
            occurrences.add(chunk["occurrence_id"])
        return result

    def selection(self, hit, question):
        return visual_qa.verified_selection({"query": question, "hits": [hit]}, **self.common)


class VisualHotlineTools(HotlineTools):
    """Opt-in extension. Absent text artifacts are explicit, not a fake retriever."""
    def __init__(self, visual: VisualAccess, *, base: HotlineTools | None = None):
        if base is None:
            super().__init__(EvidenceStore([], []), None, identity="visual-only-v1")
        else:
            super().__init__(base.store, base.retriever,
                catalog={row["doc_id"]: row["title"] for row in base.catalog},
                identity=base.profile_key[1], window_chars=base.window_chars, lane_k=base.lane_k)
        self.text_enabled = base is not None
        self.visual = visual
        self.universe = self.universe | visual.doc_ids
        titles = {row["doc_id"]: row["title"] for row in self.catalog}
        self.catalog = tuple({"doc_id": key, "title": titles.get(key, "Indexed visual document")}
                             for key in sorted(self.universe))
        self.profile_key = (*self.profile_key, visual.identity)

    def _document_of(self, evidence_id):
        if evidence_id.startswith("visual/"):
            return self.visual.document_of(evidence_id)
        return super()._document_of(evidence_id)

    def begin(self, raw, *, follow_up=False):
        episode = super().begin(raw, follow_up=follow_up)
        episode.capabilities = tuple((["search", "read"] if self.text_enabled else []) +
            ["visual_search", "inspect_image", "track", "commit", "recall", "note", "finish"])
        return episode

    def search(self, episode, arg, budget, remaining):
        if not self.text_enabled:
            raise Unsupported("text_retrieval_unavailable")
        return super().search(episode, arg, budget, remaining)

    def read(self, episode, arg, budget, remaining):
        canonical = [episode.reference(key) for key in arg["evidence_ids"]]
        if any(key in episode.visual_hits for key in canonical):
            raise InvalidAction("use_inspect_image_for_visual_evidence")
        return super().read(episode, arg, budget, remaining)

    def dispatch(self, episode, action, budget, remaining, experience):
        if action["tool"] == "visual_search":
            result = self.visual_search(episode, action["arguments"], budget, remaining)
            if not result.get("duplicate", False):
                episode.duplicate_search_cooldown = None
                episode.track_available = True
            return result
        if action["tool"] == "inspect_image":
            result = self.inspect_image(episode, action["arguments"], budget, remaining)
            if not result.get("duplicate", False):
                episode.duplicate_search_cooldown = None
                episode.track_available = True
            return result
        return super().dispatch(episode, action, budget, remaining, experience)

    def visual_search(self, episode, arg, budget, remaining):
        remaining()
        requested_scope = self._scope(episode, arg["doc_ids"])
        scope = self.visual.doc_ids if requested_scope is None else requested_scope & self.visual.doc_ids
        key = ("visual_search", *episode.profile_key, arg["query"], tuple(sorted(scope)), arg["limit"])
        if key in episode.cache:
            episode.usage.duplicates += 1
            return {**deepcopy(episode.cache[key]), "duplicate": True}
        if not scope:
            return {"candidates": [], "empty_scope": True, "duplicate": False}
        if episode.usage.search_calls >= budget.search_calls:
            raise LimitReached("search_budget_exhausted")
        episode.usage.search_calls += 1
        episode.usage.visual_search_calls += 1
        result = self.visual.search(arg["query"], scope, arg["limit"], remaining)
        rows = []
        for hit in result["hits"]:
            citation = hit["citation"]
            eid = self.visual.evidence_id(hit["chunk_id"])
            rows.append((eid, hit, {"evidence_id": eid, "doc_id": citation["doc_id"],
                        "kind": "visual_ocr", "locator": deepcopy(citation), "excerpt": hit["text"][:280]}))
        remaining()
        for eid, hit, row in rows:
            episode.candidates[eid] = row
            episode.visual_hits[eid] = deepcopy(hit)
        observation = {"candidates": [{"id": episode.handle(eid), "doc_id": row["doc_id"],
                         "kind": row["kind"], "excerpt": row["excerpt"],
                         "page": row["locator"].get("page")} for eid, _hit, row in rows],
                       "scope_doc_ids": sorted(scope), "duplicate": False,
                       "meaning": "OCR text retrieval; inspect_image is required for pixel interpretation"}
        episode.searches.append({"tool": "visual_search", "query": arg["query"],
                                "doc_ids": sorted(scope), "found": [x["id"] for x in observation["candidates"]]})
        episode.cache[key] = deepcopy(observation)
        return observation

    def inspect_image(self, episode, arg, budget, remaining):
        remaining()
        eid = episode.reference(arg["evidence_id"])
        hit = episode.visual_hits.get(eid)
        if hit is None:
            raise InvalidAction("visual_candidate_required")
        doc = hit["citation"]["doc_id"]
        if episode.scope is not None and doc not in episode.scope:
            raise InvalidAction("scope_escape")
        key = ("inspect_image", *episode.profile_key, eid, arg["question"])
        if key in episode.cache:
            saved = deepcopy(episode.cache[key])
            if saved["window"] is None:
                episode.windows.pop(eid, None)
            else:
                episode.windows[eid] = saved["window"]
            episode.usage.duplicates += 1
            return {**saved["observation"], "duplicate": True}
        if episode.usage.read_calls >= budget.read_calls:
            raise LimitReached("read_budget_exhausted")
        if episode.usage.image_calls >= budget.image_calls:
            raise LimitReached("image_budget_exhausted")
        if len(set(episode.windows) | {eid}) > 6:
            raise InvalidAction("read_memory_capacity")
        request = self.visual.selection(hit, arg["question"])
        remaining()
        episode.usage.read_calls += 1
        episode.usage.image_calls += 1
        row = {"kind": "visual", "attempt": episode.usage.image_calls,
               "candidate_id": episode.handle(eid), "outcome": "attempted"}
        episode.trajectory.append(row)
        try:
            raw = self.visual.inspector(request, remaining=remaining)
        except Exception:
            episode.usage.visual_usage_complete = False
            raise
        runtime = raw.get("runtime", {}) if type(raw) is dict else {}
        for name, attr in (("actual_prompt_tokens", "visual_input_tokens"), ("output_tokens", "visual_output_tokens")):
            value = runtime.get(name)
            if type(value) is int and value >= 0:
                setattr(episode.usage, attr, getattr(episode.usage, attr) + value)
            else:
                episode.usage.visual_usage_complete = False
        row.update(runtime=deepcopy(runtime), output=raw.get("raw_text") if type(raw) is dict else None)
        remaining()
        generation = visual_qa.validate_generation(raw, request["crop_sha256"])
        if self.visual.selection(hit, arg["question"]) != request:
            raise HarnessError("visual_source_changed")
        remaining()
        row["outcome"] = generation["status"]
        window = None
        if generation["status"] == "answered":
            body = json.dumps({"interpretation": generation["interpretation"]["answer"],
                               "visible_details": generation["interpretation"]["visible_details"],
                               "question": arg["question"]}, ensure_ascii=False)
            window = {"evidence_id": eid, "doc_id": doc, "text": body,
                      "locator": deepcopy(request["citation"]), "source_kind": "visual_inference",
                      "content_sha256": sha256(body.encode()).hexdigest(),
                      "human_review_required": True, "factual_evidence_promoted": False,
                      "semantic_verified": False, "image_model": runtime.get("model"),
                      "image_model_revision": runtime.get("revision")}
            episode.windows[eid] = window
        else:
            episode.windows.pop(eid, None)
        observation = {"candidate_id": episode.handle(eid),
                       "finish_evidence_id": episode.read_handle(eid) if window is not None else None,
                       "status": generation["status"], "usable_in_finish": window is not None, "duplicate": False,
                       "human_review_required": True, "factual_evidence_promoted": False,
                       "uncertainties": generation["interpretation"]["uncertainties"],
                       "image_count": runtime.get("image_count"), "ocr_text_supplied": runtime.get("ocr_text_supplied")}
        episode.cache[key] = {"observation": deepcopy(observation), "window": deepcopy(window)}
        return observation
