"""Scope-aware retrieval and citation-safe answer generation."""

from midprojectrag.answering.pipeline import PipelineResult, RagPipeline

__all__ = ["PipelineResult", "RagPipeline", "EvidenceAnswerAdapter", "EvidenceAnswerResult"]


def __getattr__(name: str):
    # Keep the opt-in evidence modules outside baseline import initialization.
    if name in {"EvidenceAnswerAdapter", "EvidenceAnswerResult"}:
        from .evidence_adapter import EvidenceAnswerAdapter, EvidenceAnswerResult
        return {"EvidenceAnswerAdapter": EvidenceAnswerAdapter,
                "EvidenceAnswerResult": EvidenceAnswerResult}[name]
    raise AttributeError(name)
