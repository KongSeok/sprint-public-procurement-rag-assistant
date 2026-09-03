"""검색·생성·근거 검증을 연결하는 통합 RAG 실행기."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .evidence import EvidenceRecord, build_evidence_records
from .generation.generation import ABSTENTION_PHRASE, build_context, extract_cited_doc_ids
from .generation.providers import AnswerGenerator
from .retrieval.query_filters import build_metadata_filter


@dataclass(frozen=True)
class IntegratedAnswer:
    query: str
    answer: str
    provider: str
    model: str
    abstained: bool
    cited_doc_ids: tuple[str, ...]
    unsupported_citations: tuple[str, ...]
    evidence: tuple[EvidenceRecord, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


class IntegratedRAGPipeline:
    """동일한 검색 결과에 서로 다른 생성 모델을 연결한다."""

    def __init__(
        self,
        index: Any,
        generator: AnswerGenerator,
        *,
        top_k: int = 5,
        vector_weight: float = 0.5,
        bm25_weight: float = 0.5,
        expand_to_parent: bool = True,
        auto_query_filter: bool = True,
    ) -> None:
        if top_k < 1:
            raise ValueError("top_k는 1 이상이어야 합니다")
        if vector_weight < 0 or bm25_weight < 0 or vector_weight + bm25_weight <= 0:
            raise ValueError("검색 가중치는 0 이상이며 합이 0보다 커야 합니다")
        total = vector_weight + bm25_weight
        self.index = index
        self.generator = generator
        self.top_k = top_k
        self.vector_weight = vector_weight / total
        self.bm25_weight = bm25_weight / total
        self.expand_to_parent = expand_to_parent
        self.auto_query_filter = auto_query_filter

    def answer(self, query: str, *, organization: str | None = None) -> IntegratedAnswer:
        if not query or not query.strip():
            raise ValueError("질문을 입력해야 합니다")
        meta_filter = (
            build_metadata_filter(query, organization=organization)
            if self.auto_query_filter or organization
            else None
        )
        hits = self.index.hybrid_search(
            query,
            k=self.top_k,
            meta_filter=meta_filter,
            vector_weight=self.vector_weight,
            bm25_weight=self.bm25_weight,
            expand_to_parent=self.expand_to_parent,
        )
        evidence = build_evidence_records(hits)
        if not hits:
            answer = ABSTENTION_PHRASE
        else:
            answer = self.generator.generate(query, build_context(hits))

        cited = tuple(extract_cited_doc_ids(answer))
        available = {item.doc_id for item in evidence}
        unsupported = tuple(doc_id for doc_id in cited if doc_id not in available)
        return IntegratedAnswer(
            query=query,
            answer=answer,
            provider=self.generator.provider,
            model=self.generator.model,
            abstained=not hits or ABSTENTION_PHRASE in answer,
            cited_doc_ids=cited,
            unsupported_citations=unsupported,
            evidence=evidence,
        )
