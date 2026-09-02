"""Opt-in composition root; the legacy RagPipeline is unchanged."""
from __future__ import annotations

import time
import math
from dataclasses import dataclass, replace

from midprojectrag.answering.evidence_adapter import EvidenceAnswerAdapter, EvidenceAnswerResult
from midprojectrag.evaluation import validate_request
from midprojectrag.evidence import Evidence
from midprojectrag.retrieval import Candidate, select_context
from .controller import Harness
from .enumeration import BoundedListEnumerator, EnumerationResult
from .types import HarnessResult, QueryPlan


@dataclass(frozen=True)
class EvidencePipelineResult:
    harness: HarnessResult
    answer: EvidenceAnswerResult


@dataclass(frozen=True)
class ListPipelineResult:
    enumeration: EnumerationResult
    answer: EvidenceAnswerResult
    status: str
    reason: str
    context: tuple[Evidence, ...]
    required_ids: tuple[str, ...]


def _operational_error(answer: EvidenceAnswerResult, reason: str) -> EvidenceAnswerResult:
    # Keep the standard transport DTO; do not relabel provider/scope errors as
    # an ordinary lack of evidence. Reason comes from fixed controller codes.
    response = {**answer.response, "status": "error", "answer": "", "citations": [],
                "abstention": None, "error": {"code": reason, "message": "근거 제어 흐름 실행에 실패했습니다."}}
    return replace(answer, response=response, terminal_reason=reason)


class EvidenceHarnessPipeline:
    def __init__(self, *, harness: Harness, answer_adapter: EvidenceAnswerAdapter,
                 enumerator: BoundedListEnumerator | None = None) -> None:
        self.harness = harness
        self.answer_adapter = answer_adapter
        self.enumerator = enumerator
        if enumerator is not None and enumerator.store is not harness.store:
            raise ValueError("enumeration_store_mismatch")

    def query(self, request: dict, *, plan: QueryPlan, deadline: float | None = None,
              requires_pixels: bool = False) -> EvidencePipelineResult | ListPipelineResult:
        if validate_request(request):
            raise ValueError("invalid_request")
        if type(requires_pixels) is not bool or (deadline is not None and (
                type(deadline) not in (int, float) or not math.isfinite(deadline))):
            raise ValueError("invalid_pipeline_budget")
        expected_scope = (frozenset(request["document_scope"]["doc_ids"])
                          if request["document_scope"]["mode"] == "explicit" else None)
        history = tuple((t["role"], t["content"]) for t in request["history"])
        if (plan.query != request["question"] or plan.history != history or plan.allowed_doc_ids != expected_scope):
            raise ValueError("plan_request_mismatch")
        started = time.monotonic()
        effective_deadline = min(deadline, started + self.harness.config.timeout_seconds) if deadline is not None else started + self.harness.config.timeout_seconds
        if plan.query_type == "list" and self.enumerator is not None and not requires_pixels:
            return self._list_query(request, plan, effective_deadline)
        result = self.harness.run(plan, request_deadline=effective_deadline)
        # Empty context is an explicit safe abstention, never an unsupported generation.
        answer = self.answer_adapter.answer(
            request, result.context if result.status == "READY" else (),
            required_ids=result.required_ids if result.status == "READY" else (),
            trace_id=request["request_id"],
            # Until a verified visual reader is injected, every visual plan is
            # capability-gapped. OCR text remains usable only for non-pixel slots.
            requires_pixels=requires_pixels or plan.query_type == "visual",
            deadline=effective_deadline)
        if result.status == "ERROR":
            answer = _operational_error(answer, result.reason)
        return EvidencePipelineResult(result, answer)

    def _list_query(self, request: dict, plan: QueryPlan, deadline: float) -> ListPipelineResult:
        receipt = self.enumerator.enumerate(plan, request_deadline=deadline,
                    citation_limit=min(request["options"]["max_citations"], self.enumerator.config.citation_limit))
        context = ()
        required = receipt.supporting_ids
        status = "ABSTAINED"
        reason = receipt.reason
        if receipt.complete and required:
            try:
                candidates = tuple(Candidate(i, 1.0, "enumeration", n + 1) for n, i in enumerate(required))
                config = self.harness.config
                context = select_context(self.harness.store, candidates,
                            max_chars=config.max_context_chars, max_items=config.max_context_items,
                            per_doc_limit=config.max_per_doc, required_ids=required)
                status = "READY"
            except ValueError:
                reason = "enumeration_context_budget_exceeded"
        elif receipt.complete:
            # An exhaustive negative receipt is not an affirmative, cited answer.
            reason = "enumeration_no_matches"
        if receipt.reason in {"enumeration_backend_error", "invalid_enumeration_response",
                "enumeration_reference_outside_supplied_evidence", "enumeration_match_without_support",
                "enumeration_unrelated_scan_has_support"}:
            status = "ERROR"
        answer = self.answer_adapter.answer(request, context,
                    required_ids=required if status == "READY" else (),
                    trace_id=request["request_id"], deadline=deadline)
        if status == "ERROR":
            answer = _operational_error(answer, reason)
        return ListPipelineResult(receipt, answer, status, reason, context, required)
