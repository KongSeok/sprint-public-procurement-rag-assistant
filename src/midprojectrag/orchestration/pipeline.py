"""Opt-in composition root; the legacy RagPipeline is unchanged."""
from __future__ import annotations

import time
from dataclasses import dataclass

from midprojectrag.answering.evidence_adapter import EvidenceAnswerAdapter, EvidenceAnswerResult
from midprojectrag.evaluation import validate_request
from .controller import Harness
from .types import HarnessResult, QueryPlan


@dataclass(frozen=True)
class EvidencePipelineResult:
    harness: HarnessResult
    answer: EvidenceAnswerResult


class EvidenceHarnessPipeline:
    def __init__(self, *, harness: Harness, answer_adapter: EvidenceAnswerAdapter) -> None:
        self.harness = harness
        self.answer_adapter = answer_adapter

    def query(self, request: dict, *, plan: QueryPlan, deadline: float | None = None,
              requires_pixels: bool = False) -> EvidencePipelineResult:
        if validate_request(request):
            raise ValueError("invalid_request")
        expected_scope = (frozenset(request["document_scope"]["doc_ids"])
                          if request["document_scope"]["mode"] == "explicit" else None)
        history = tuple((t["role"], t["content"]) for t in request["history"])
        if (plan.query != request["question"] or plan.history != history or plan.allowed_doc_ids != expected_scope):
            raise ValueError("plan_request_mismatch")
        started = time.monotonic()
        effective_deadline = min(deadline, started + self.harness.config.timeout_seconds) if deadline is not None else started + self.harness.config.timeout_seconds
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
        return EvidencePipelineResult(result, answer)
