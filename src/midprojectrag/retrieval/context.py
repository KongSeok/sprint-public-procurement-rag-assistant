"""Bounded source expansion and evidence selection; parents are never candidates."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
from midprojectrag.evidence import EvidenceStore
from .contracts import Candidate, freeze, thaw


@dataclass(frozen=True, slots=True)
class ParentWindow:
    parent_id: str
    child_evidence_id: str
    char_range: tuple[int, int]
    text: str
    parent_truncated: bool

    def to_dict(self):
        return {"parent_id": self.parent_id, "child_evidence_id": self.child_evidence_id,
                "char_range": list(self.char_range), "text": self.text, "parent_truncated": self.parent_truncated}


def expand_parents(candidates: tuple[Candidate, ...], store: EvidenceStore, *, max_chars=2400) -> tuple[ParentWindow, ...]:
    if type(max_chars) is not int or max_chars < 1:
        raise ValueError("invalid_parent_context_budget")
    windows, seen = [], set()
    for candidate in candidates:
        e = store.get(candidate.evidence_id)
        if e.doc_id != candidate.doc_id:
            raise ValueError("context_candidate_identity_mismatch")
        p = store.parent(e.parent_id)
        if p.parent_id in seen or e.locator.char_range is None:
            continue
        start, end = e.locator.char_range
        if end-start > max_chars:
            continue  # Never trim the cited child just to pretend it fits.
        spare = max_chars - (end-start)
        low = max(0, start-spare//2)
        high = min(len(p.text), low+max_chars)
        low = max(0, high-max_chars)
        windows.append(ParentWindow(p.parent_id, e.evidence_id, (low, high), p.text[low:high],
                                    low > 0 or high < len(p.text)))
        seen.add(p.parent_id)
    return tuple(windows)


@dataclass(frozen=True, slots=True)
class ContextPack:
    evidence_ids: tuple[str, ...]
    parent_windows: tuple[ParentWindow, ...]
    trace: Mapping

    def __post_init__(self):
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))
        object.__setattr__(self, "parent_windows", tuple(self.parent_windows))
        object.__setattr__(self, "trace", freeze(self.trace))

    def to_dict(self):
        return {"evidence_ids": list(self.evidence_ids), "parent_windows": [w.to_dict() for w in self.parent_windows],
                "trace": thaw(self.trace)}


def select_context(candidates: tuple[Candidate, ...], store: EvidenceStore, *, final_k=6, max_per_doc=6,
                   char_budget=12000, parent_max_chars=2400, mandatory_ids=(), required_docs=()) -> ContextPack:
    if any(type(v) is not int or v < 1 for v in (final_k, max_per_doc, char_budget, parent_max_chars)):
        raise ValueError("invalid_context_budget")
    rows = tuple(candidates)
    if len({c.evidence_id for c in rows}) != len(rows):
        raise ValueError("duplicate_context_candidate")
    for c in rows:
        if store.get(c.evidence_id).doc_id != c.doc_id:
            raise ValueError("context_candidate_identity_mismatch")
    mandatory, required = frozenset(mandatory_ids), frozenset(required_docs)
    selected, ids, counts, used = [], set(), {}, 0

    def add(c):
        nonlocal used
        if c.evidence_id in ids:
            return True
        size = len(store.get(c.evidence_id).text)
        if len(selected) >= final_k or counts.get(c.doc_id, 0) >= max_per_doc or used + size > char_budget:
            return False
        selected.append(c)
        ids.add(c.evidence_id)
        counts[c.doc_id] = counts.get(c.doc_id, 0) + 1
        used += size
        return True

    for c in rows:
        if c.evidence_id in mandatory:
            add(c)
    # Required document coverage is attempted before filling high-ranking duplicates.
    for doc in sorted(required):
        if doc not in counts:
            for c in rows:
                if c.doc_id == doc and add(c):
                    break
    for c in rows:
        add(c)
    windows = []
    for window in expand_parents(tuple(selected), store, max_chars=parent_max_chars):
        if used + len(window.text) <= char_budget:
            windows.append(window)
            used += len(window.text)
    return ContextPack(tuple(c.evidence_id for c in selected), tuple(windows), {
        "bundle_sha256": store.bundle_sha256, "pre_count": len(rows), "post_count": len(selected),
        "pre_distinct_docs": len({c.doc_id for c in rows}), "post_distinct_docs": len(counts),
        "retention": len(selected)/len(rows) if rows else None,
        "mandatory_count": len(mandatory), "mandatory_retained": len(mandatory & ids),
        "missing_mandatory_ids": sorted(mandatory-ids), "missing_required_docs": sorted(required-set(counts)),
        "char_budget": char_budget, "used_chars": used, "parent_context_citable": False,
        "selected_child_chars": sum(len(store.get(i).text) for i in ids)})
