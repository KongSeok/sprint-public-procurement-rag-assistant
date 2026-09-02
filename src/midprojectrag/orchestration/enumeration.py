"""Bounded exhaustive document enumeration, independent of retrieval top-k.

The LLM supplies semantic hypotheses. This module only proves that the frozen
document universe and its canonical text were visited, validates returned refs,
and enforces budgets. It is not an answer-quality or gold-set judge.
"""
from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass

from midprojectrag.evidence import Evidence, EvidenceStore
from .llm import JSONBackend
from .types import QueryPlan


@dataclass(frozen=True)
class EnumerationConfig:
    max_calls: int = 128
    max_batch_chars: int = 6000
    max_reduce_chars: int = 12000
    max_total_chars: int = 500000
    max_documents: int = 10000
    citation_limit: int = 5
    timeout_seconds: float = 90.0

    def __post_init__(self) -> None:
        for name in ("max_calls", "max_batch_chars", "max_reduce_chars", "max_total_chars",
                     "max_documents", "citation_limit"):
            if type(getattr(self, name)) is not int or not 1 <= getattr(self, name) <= 10000000:
                raise ValueError("invalid_enumeration_budget")
        if (type(self.timeout_seconds) not in (int, float)
                or not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 600):
            raise ValueError("invalid_enumeration_timeout")


@dataclass(frozen=True)
class DocumentDecision:
    doc_id: str
    status: str
    evidence_ids: tuple[str, ...]
    scan_complete: bool
    reason: str


@dataclass(frozen=True)
class EnumerationEvent:
    phase: str
    doc_id: str
    fragments: tuple[tuple[str, int, int], ...]
    status: str
    evidence_ids: tuple[str, ...]
    scan_complete: bool
    chars_sent: int


@dataclass(frozen=True)
class EnumerationResult:
    complete: bool
    reason: str
    scoped_doc_ids: tuple[str, ...]
    scanned_doc_ids: tuple[str, ...]
    matched_doc_ids: tuple[str, ...]
    supporting_ids: tuple[str, ...]
    decisions: tuple[DocumentDecision, ...]
    events: tuple[EnumerationEvent, ...]
    calls: int
    chars_sent: int
    chars_scanned: int
    artifact_sha256: str


class _Incomplete(Exception):
    pass


def _size(payload: dict) -> int:
    return len(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _fragment(evidence: Evidence, start: int, end: int) -> dict:
    return {"evidence_id": evidence.evidence_id, "doc_id": evidence.doc_id,
            "kind": evidence.kind, "page": evidence.page, "start": start, "end": end,
            "total_chars": len(evidence.text), "text": evidence.text[start:end],
            "content_sha256": evidence.content_sha256}


class BoundedListEnumerator:
    """One full scan plus a bounded semantic reduction for each scoped document.

    ``scan`` no_match means *no facts relevant to ANY query predicate*. A partial
    predicate must be unknown with refs, so facts on separate pages can meet in
    ``reduce``. Every positive and partial fragment is retained for that reduction;
    exceeding its budget never silently drops a fragment. All scan calls complete
    before a document may be a final match, allowing later conflicting facts to
    reach the reducer. A backend must enforce its own per-call timeout, as the
    shared deadline here can only reject a returned late result.
    """

    def __init__(self, store: EvidenceStore, backend: JSONBackend, *,
                 config: EnumerationConfig = EnumerationConfig(),
                 clock: Callable[[], float] = time.monotonic) -> None:
        if not isinstance(store, EvidenceStore) or not isinstance(config, EnumerationConfig):
            raise ValueError("invalid_enumerator_configuration")
        self.store = store
        self.backend = backend
        self.config = config
        self.clock = clock

    def _canonical(self, doc_id: str) -> tuple[Evidence, ...]:
        records = []
        for evidence in self.store.all():
            if evidence.doc_id != doc_id or evidence.kind == "figure":
                continue
            # A page already contains these exact characters. This is structural
            # coverage, never a relevance/answer judgment. Preserve any extra text
            # not represented by its ancestors, including explicit table children.
            duplicate = False
            if evidence.kind == "text":
                parent_id = evidence.parent_id
                while parent_id is not None:
                    parent = self.store.get(parent_id)
                    if parent.kind in {"page", "table"} and evidence.text in parent.text:
                        duplicate = True
                        break
                    parent_id = parent.parent_id
            if not duplicate:
                records.append(evidence)
        return tuple(sorted(records, key=lambda e: (e.page or 0, e.kind, e.evidence_id)))

    @staticmethod
    def _base(plan: QueryPlan, doc_id: str, phase: str) -> dict:
        return {"phase": phase, "document_id": doc_id, "question": plan.query,
                "history": [{"role": role, "content": text} for role, text in plan.history],
                "slots": [asdict(slot) for slot in plan.slots], "evidence": []}

    def _batches(self, base: dict, records: tuple[Evidence, ...]) -> Iterator[dict]:
        batch: list[dict] = []
        limit = self.config.max_batch_chars
        for evidence in records:
            start = 0
            while start < len(evidence.text):
                remaining = len(evidence.text) - start
                low, high = 0, remaining
                # Count the entire serialized payload, including repeated question,
                # history and provenance, rather than just the document text.
                while low < high:
                    length = (low + high + 1) // 2
                    payload = {**base, "evidence": [*batch, _fragment(evidence, start, start + length)]}
                    if _size(payload) <= limit and self._fits(payload):
                        low = length
                    else:
                        high = length - 1
                if low == 0:
                    if not batch:
                        minimum = {**base, "evidence": [_fragment(evidence, start, start + 1)]}
                        raise _Incomplete("batch_character_budget_exceeded" if _size(minimum) > limit
                                          else "enumeration_context_budget_exceeded")
                    yield {**base, "evidence": batch}
                    batch = []
                    continue
                batch.append(_fragment(evidence, start, start + low))
                start += low
                if low < remaining:
                    yield {**base, "evidence": batch}
                    batch = []
        if batch:
            yield {**base, "evidence": batch}

    def _fits(self, payload: dict) -> bool:
        """An optional backend-specific, side-effect-free prompt capacity check."""
        fits = getattr(self.backend, "fits", None)
        if not callable(fits):
            return True
        try:
            return fits("enumerate", payload) is True
        except Exception:
            raise _Incomplete("enumeration_context_budget_exceeded") from None

    @staticmethod
    def _decision(value: object, payload: dict) -> tuple[str, tuple[str, ...], bool]:
        if (not isinstance(value, dict) or set(value) != {"status", "evidence_ids", "scan_complete"}
                or not isinstance(value["status"], str)
                or value["status"] not in {"match", "no_match", "unknown"}
                or not isinstance(value["evidence_ids"], list)
                or any(not isinstance(i, str) for i in value["evidence_ids"])
                or type(value["scan_complete"]) is not bool):
            raise _Incomplete("invalid_enumeration_response")
        ids = tuple(value["evidence_ids"])
        supplied = {fragment["evidence_id"] for fragment in payload["evidence"]}
        if len(ids) != len(set(ids)) or any(i not in supplied for i in ids):
            raise _Incomplete("enumeration_reference_outside_supplied_evidence")
        status = value["status"]
        if status == "match" and not ids:
            raise _Incomplete("enumeration_match_without_support")
        if payload["phase"] == "scan" and status == "no_match" and ids:
            raise _Incomplete("enumeration_unrelated_scan_has_support")
        return status, ids, value["scan_complete"]

    def enumerate(self, plan: QueryPlan, *, request_deadline: float | None = None,
                  citation_limit: int | None = None) -> EnumerationResult:
        if not isinstance(plan, QueryPlan) or plan.query_type != "list":
            raise ValueError("enumeration_requires_list_plan")
        if request_deadline is not None and (
            type(request_deadline) not in (int, float) or not math.isfinite(request_deadline)
        ):
            raise ValueError("invalid_enumeration_deadline")
        cap = self.config.citation_limit if citation_limit is None else citation_limit
        if type(cap) is not int or not 1 <= cap <= self.config.citation_limit:
            raise ValueError("invalid_enumeration_citation_limit")
        deadline = self.clock() + self.config.timeout_seconds
        if request_deadline is not None:
            deadline = min(deadline, request_deadline)
        actual_docs = frozenset(e.doc_id for e in self.store.all())
        scoped_docs = tuple(sorted(plan.allowed_doc_ids if plan.allowed_doc_ids is not None else actual_docs))
        decisions: list[DocumentDecision] = []
        events: list[EnumerationEvent] = []
        scanned: list[str] = []
        calls = chars_sent = chars_scanned = 0

        def finish(complete: bool, reason: str) -> EnumerationResult:
            matches = tuple(d.doc_id for d in decisions if d.status == "match")
            supporting = tuple(dict.fromkeys(i for d in decisions if d.status == "match" for i in d.evidence_ids))
            return EnumerationResult(complete, reason, scoped_docs, tuple(scanned), matches, supporting,
                                     tuple(decisions), tuple(events), calls, chars_sent, chars_scanned,
                                     self.store.artifact_sha256)

        def guard() -> None:
            if self.clock() >= deadline:
                raise _Incomplete("deadline_exceeded")

        def ask(payload: dict, maximum: int) -> tuple[str, tuple[str, ...], bool]:
            nonlocal calls, chars_sent
            guard()
            size = _size(payload)
            if size > maximum:
                raise _Incomplete("reduce_character_budget_exceeded")
            if not self._fits(payload):
                raise _Incomplete("enumeration_context_budget_exceeded")
            if calls >= self.config.max_calls:
                raise _Incomplete("call_budget_exhausted")
            if chars_sent + size > self.config.max_total_chars:
                raise _Incomplete("total_character_budget_exceeded")
            calls += 1
            chars_sent += size
            try:
                value = self.backend.ask("enumerate", payload)
            except TimeoutError:
                guard()
                raise _Incomplete("backend_budget_exhausted") from None
            except Exception:
                raise _Incomplete("enumeration_backend_error") from None
            guard()
            status, ids, complete = self._decision(value, payload)
            events.append(EnumerationEvent(
                payload["phase"], payload["document_id"],
                tuple((e["evidence_id"], e["start"], e["end"]) for e in payload["evidence"]),
                status, ids, complete, size))
            return status, ids, complete

        if not scoped_docs:
            return finish(False, "empty_document_universe")
        if any(doc_id not in actual_docs for doc_id in scoped_docs):
            return finish(False, "document_scope_missing_from_store")
        if len(scoped_docs) > self.config.max_documents:
            return finish(False, "document_budget_exceeded")
        if any(slot.kind == "figure" for slot in plan.slots):
            return finish(False, "enumeration_visual_capability_gap")
        try:
            for doc_id in scoped_docs:
                guard()
                records = self._canonical(doc_id)
                if not records:
                    return finish(False, "canonical_document_evidence_missing")
                if any(not evidence.text.strip() for evidence in records):
                    return finish(False, "canonical_document_text_missing")
                relevant: dict[tuple[str, int, int], dict] = {}
                unresolved = False
                batch_count = 0
                for payload in self._batches(self._base(plan, doc_id, "scan"), records):
                    status, refs, complete = ask(payload, self.config.max_batch_chars)
                    batch_count += 1
                    if not complete:
                        return finish(False, "document_scan_incomplete")
                    chars_scanned += sum(len(e["text"]) for e in payload["evidence"])
                    if status == "unknown" and not refs:
                        unresolved = True
                    for fragment in payload["evidence"]:
                        if fragment["evidence_id"] in refs:
                            relevant[(fragment["evidence_id"], fragment["start"], fragment["end"])] = fragment
                scanned.append(doc_id)
                if unresolved:
                    decisions.append(DocumentDecision(doc_id, "unknown", (), True, "unlocated_partial_evidence"))
                    continue
                payload = self._base(plan, doc_id, "reduce")
                payload["evidence"] = list(relevant.values())
                payload["scan_summary"] = {"batches": batch_count, "all_batches_scanned": True,
                                           "canonical_evidence_count": len(records),
                                           "all_unrelated": not relevant}
                status, refs, complete = ask(payload, self.config.max_reduce_chars)
                decisions.append(DocumentDecision(doc_id, status, refs, complete,
                                                   "document_reduced" if complete and status != "unknown"
                                                   else "document_reduction_incomplete"))
            guard()
        except _Incomplete as exc:
            return finish(False, str(exc))
        if any(not d.scan_complete or d.status == "unknown" for d in decisions):
            return finish(False, "document_decision_unknown")
        supporting = {i for d in decisions if d.status == "match" for i in d.evidence_ids}
        if len(supporting) > cap:
            return finish(False, "citation_budget_exceeded")
        return finish(True, "all_scoped_documents_enumerated")

    def is_complete(self, plan: QueryPlan, evidence: tuple[Evidence, ...]) -> bool:
        """Compatibility gate: a top-k context cannot omit an enumerated match.

        New composition roots should call ``enumerate`` before retrieval/packing
        so the complete positive set can become mandatory context.
        """
        if not isinstance(evidence, tuple) or any(not isinstance(e, Evidence) for e in evidence):
            raise ValueError("invalid_enumeration_evidence")
        supplied = set()
        for item in evidence:
            if self.store.get(item.evidence_id) != item:
                raise ValueError("enumeration_evidence_mismatch")
            supplied.add(item.evidence_id)
        receipt = self.enumerate(plan)
        return receipt.complete and bool(receipt.supporting_ids) and set(receipt.supporting_ids) <= supplied
