from __future__ import annotations

import re
import threading
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence

from midprojectrag.answering import PipelineResult
from midprojectrag.catalog import (
    CatalogError,
    CatalogFilter,
    DocumentCard as CatalogDocumentCard,
    MetadataFact as CatalogMetadataFact,
    MetadataCatalog,
)
from midprojectrag.evaluation import validate_request
from midprojectrag.ingest.common import sha256_text


DOC_ID_RE = re.compile(r"^doc_[0-9a-f]{24}$")


@dataclass(frozen=True)
class ConversationTurn:
    role: str
    content: str
    cited_doc_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocumentSummary:
    doc_id: str
    project_name: str
    ordering_agency: str

    @property
    def label(self) -> str:
        return f"{self.project_name} · {self.ordering_agency} · …{self.doc_id[-6:]}"


@dataclass(frozen=True, slots=True)
class MetadataEvidence:
    """Application-safe provenance classification without an internal locator."""

    source_type: str

    @property
    def kind(self) -> str:
        return self.source_type

    def to_public_dict(self) -> dict[str, str]:
        return {"source_type": self.source_type}


@dataclass(frozen=True, slots=True)
class MetadataFact:
    """UI-safe copy of a catalog fact.

    Evidence locators intentionally do not cross the application boundary.  The
    catalog remains the only owner of those internal provenance coordinates.
    """

    fact_id: str
    doc_id: str
    field: str
    value: str | None
    normalized_value: str | None
    value_type: str
    state: str
    decision: str | None
    reason_code: str | None
    confidence: str | None
    correction_id: str | None
    checked_at: str | None
    evidence: tuple[MetadataEvidence, ...]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "doc_id": self.doc_id,
            "field": self.field,
            "value": self.value,
            "normalized_value": self.normalized_value,
            "value_type": self.value_type,
            "state": self.state,
            "decision": self.decision,
            "reason_code": self.reason_code,
            "confidence": self.confidence,
            "correction_id": self.correction_id,
            "checked_at": self.checked_at,
            "evidence": [item.to_public_dict() for item in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class DocumentCard:
    """Application-safe metadata card containing no evidence locator field."""

    doc_id: str
    facts: tuple[MetadataFact, ...]

    def get_fact(self, field: str) -> MetadataFact:
        for fact in self.facts:
            if fact.field == field:
                return fact
        raise CatalogError("invalid_metadata_field")

    @property
    def project_name(self) -> str | None:
        return self.get_fact("project_name").value

    @property
    def ordering_agency(self) -> str | None:
        return self.get_fact("ordering_agency").value

    @property
    def notice_number(self) -> str | None:
        return self.get_fact("notice_number").value

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "facts": [fact.to_public_dict() for fact in self.facts],
        }


@dataclass(frozen=True, slots=True)
class CatalogSearchResult:
    total_count: int
    documents: tuple[DocumentCard, ...]

    @property
    def cards(self) -> tuple[DocumentCard, ...]:
        return self.documents

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "total_count": self.total_count,
            "documents": [card.to_public_dict() for card in self.documents],
        }


def _public_metadata_fact(fact: CatalogMetadataFact) -> MetadataFact:
    return MetadataFact(
        fact_id=fact.fact_id,
        doc_id=fact.doc_id,
        field=fact.field,
        value=fact.value,
        normalized_value=fact.normalized_value,
        value_type=fact.value_type,
        state=fact.state,
        decision=fact.decision,
        reason_code=fact.reason_code,
        confidence=fact.confidence,
        correction_id=fact.correction_id,
        checked_at=fact.checked_at,
        evidence=tuple(
            MetadataEvidence(source_type=item.source_type) for item in fact.evidence
        ),
    )


def _public_document_card(card: CatalogDocumentCard) -> DocumentCard:
    return DocumentCard(
        doc_id=card.doc_id,
        facts=tuple(_public_metadata_fact(fact) for fact in card.facts),
    )


@dataclass(frozen=True)
class CitationSummary:
    doc_id: str
    chunk_id: str
    source_block_ids: tuple[str, ...]
    project_name: str
    ordering_agency: str
    section_path: tuple[str, ...]
    page_start: int | None
    page_end: int | None
    metadata_card: DocumentCard | None = None
    source_locator: str | None = None


@dataclass(frozen=True)
class RuntimeDescriptor:
    runtime_id: str
    config_sha256: str
    index_config_sha256: str
    run_config_sha256: str
    api_profile: str
    embedding_model: str
    embedding_dimensions: int
    generator_model: str
    retrieval_top_k: int
    context_top_k: int
    max_citations: int
    retrieval_manifest_sha256: str
    catalog_manifest_sha256: str
    catalog_snapshot_id: str
    document_count: int
    observability_backend: str


@dataclass(frozen=True)
class AnswerResult:
    status: str
    answer: str
    citations: tuple[CitationSummary, ...]
    abstention_reason: str | None
    abstention_detail: str | None
    error_code: str | None
    error_message: str | None
    trace_id: str
    retrieval_count: int
    retrieval_ms: float
    generation_ms: float
    total_ms: float
    input_tokens: int
    output_tokens: int
    embedding_tokens: int
    cost_usd: float
    cache_hit: bool

    @property
    def cited_doc_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(citation.doc_id for citation in self.citations))


class QueryPipeline(Protocol):
    def query(
        self,
        request: dict[str, Any],
        *,
        trace_context: Mapping[str, Any] | None = None,
    ) -> PipelineResult: ...

    def flush_observability(self) -> None: ...


def _display_text(value: Any, fallback: str, *, limit: int) -> str:
    if not isinstance(value, str):
        return fallback
    normalized = unicodedata.normalize("NFC", value)
    cleaned = "".join(
        character
        for character in normalized
        if not unicodedata.category(character).startswith("C")
    )
    collapsed = " ".join(cleaned.split())
    if not collapsed:
        return fallback
    return collapsed[:limit]


def document_summaries_from_catalog(
    rows: Sequence[dict[str, Any]],
    *,
    expected_doc_ids: set[str],
    expected_snapshot_id: str,
) -> tuple[DocumentSummary, ...]:
    documents: list[DocumentSummary] = []
    seen: set[str] = set()
    for row in rows:
        doc_id = row.get("doc_id")
        if (
            not isinstance(doc_id, str)
            or DOC_ID_RE.fullmatch(doc_id) is None
            or doc_id in seen
        ):
            raise ValueError("invalid_or_duplicate_catalog_doc_id")
        if row.get("snapshot_id") != expected_snapshot_id:
            raise ValueError("catalog_snapshot_mismatch")
        metadata = row.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError("invalid_catalog_metadata")
        seen.add(doc_id)
        documents.append(
            DocumentSummary(
                doc_id=doc_id,
                project_name=_display_text(
                    metadata.get("project_name"), "사업명 미상", limit=180
                ),
                ordering_agency=_display_text(
                    metadata.get("ordering_agency"), "발주기관 미상", limit=100
                ),
            )
        )
    if seen != expected_doc_ids:
        raise ValueError("catalog_document_set_mismatch")
    return tuple(
        sorted(
            documents,
            key=lambda item: (item.project_name, item.ordering_agency, item.doc_id),
        )
    )


def document_summaries_from_metadata_catalog(
    catalog: MetadataCatalog,
) -> tuple[DocumentSummary, ...]:
    documents: list[DocumentSummary] = []
    seen: set[str] = set()
    for card in catalog.list_documents():
        doc_id = card.doc_id
        if (
            not isinstance(doc_id, str)
            or DOC_ID_RE.fullmatch(doc_id) is None
            or doc_id in seen
        ):
            raise ValueError("invalid_or_duplicate_catalog_doc_id")
        seen.add(doc_id)
        documents.append(
            DocumentSummary(
                doc_id=doc_id,
                project_name=_display_text(
                    card.get_fact("project_name").value,
                    "사업명 미상",
                    limit=180,
                ),
                ordering_agency=_display_text(
                    card.get_fact("ordering_agency").value,
                    "발주기관 미상",
                    limit=100,
                ),
            )
        )
    return tuple(
        sorted(
            documents,
            key=lambda item: (item.project_name, item.ordering_agency, item.doc_id),
        )
    )


class RagApplicationService:
    def __init__(
        self,
        *,
        pipeline: QueryPipeline | None = None,
        pipeline_factory: Callable[[], QueryPipeline] | None = None,
        documents: Sequence[DocumentSummary] | None = None,
        metadata_catalog: MetadataCatalog | None = None,
        runtime: RuntimeDescriptor,
    ) -> None:
        if (pipeline is None) == (pipeline_factory is None):
            raise ValueError("invalid_pipeline_source")
        if documents is None and metadata_catalog is not None:
            documents = document_summaries_from_metadata_catalog(metadata_catalog)
        if not documents:
            raise ValueError("empty_document_catalog")
        self._pipeline = pipeline
        self._pipeline_factory = pipeline_factory
        self._pipeline_lock = threading.Lock()
        self._documents = tuple(documents)
        self._metadata_catalog = metadata_catalog
        self._document_by_id = {document.doc_id: document for document in documents}
        if len(self._document_by_id) != len(self._documents):
            raise ValueError("duplicate_document_catalog")
        if metadata_catalog is None:
            self._metadata_cards: tuple[DocumentCard, ...] = ()
            self._metadata_card_by_id: dict[str, DocumentCard] = {}
        else:
            catalog_cards = metadata_catalog.list_documents()
            if {card.doc_id for card in catalog_cards} != set(self._document_by_id):
                raise ValueError("catalog_document_set_mismatch")
            self._metadata_cards = tuple(
                _public_document_card(card) for card in catalog_cards
            )
            self._metadata_card_by_id = {
                card.doc_id: card for card in self._metadata_cards
            }
        self.runtime = runtime

    def _get_pipeline(self) -> QueryPipeline:
        pipeline = self._pipeline
        if pipeline is not None:
            return pipeline
        with self._pipeline_lock:
            pipeline = self._pipeline
            if pipeline is not None:
                return pipeline
            factory = self._pipeline_factory
            if factory is None:
                raise RuntimeError("pipeline_factory_missing")
            pipeline = factory()
            self._pipeline = pipeline
            self._pipeline_factory = None
            return pipeline

    def list_documents(self) -> tuple[DocumentSummary, ...]:
        return self._documents

    def _require_metadata_catalog(self) -> MetadataCatalog:
        catalog = self._metadata_catalog
        if catalog is None:
            raise RuntimeError("metadata_catalog_unavailable")
        return catalog

    def list_document_cards(self) -> tuple[DocumentCard, ...]:
        self._require_metadata_catalog()
        return self._metadata_cards

    def search_documents(self, filters: CatalogFilter) -> CatalogSearchResult:
        result = self._require_metadata_catalog().search(filters)
        try:
            documents = tuple(
                self._metadata_card_by_id[card.doc_id] for card in result.documents
            )
        except KeyError as error:
            raise RuntimeError("catalog_document_set_mismatch") from error
        if result.total_count != len(documents):
            raise RuntimeError("catalog_document_set_mismatch")
        return CatalogSearchResult(
            total_count=result.total_count,
            documents=documents,
        )

    def get_document_card(self, doc_id: str) -> DocumentCard:
        card = self._require_metadata_catalog().get_document(doc_id)
        try:
            return self._metadata_card_by_id[card.doc_id]
        except KeyError as error:
            raise RuntimeError("catalog_document_set_mismatch") from error

    def _history_payload(
        self, history: Sequence[ConversationTurn]
    ) -> list[dict[str, Any]]:
        selected = list(history[-20:])
        payload: list[dict[str, Any]] = []
        for index, turn in enumerate(selected, start=1):
            if not isinstance(turn, ConversationTurn) or turn.role not in {
                "user",
                "assistant",
            }:
                raise ValueError("invalid_conversation_history")
            if not isinstance(turn.content, str) or not 1 <= len(turn.content) <= 12_000:
                raise ValueError("invalid_conversation_history")
            cited = tuple(dict.fromkeys(turn.cited_doc_ids))
            if (
                (turn.role == "user" and cited)
                or any(doc_id not in self._document_by_id for doc_id in cited)
            ):
                raise ValueError("invalid_conversation_history")
            item: dict[str, Any] = {
                "turn_id": (
                    f"hist-{index}-{sha256_text(f'{turn.role}:{turn.content}')[:16]}"
                ),
                "role": turn.role,
                "content": turn.content,
            }
            if cited:
                item["cited_doc_ids"] = list(cited)
            payload.append(item)
        return payload

    def ask(
        self,
        *,
        question: str,
        history: Sequence[ConversationTurn] = (),
        doc_ids: Sequence[str] | None = None,
        approve_external_corpus_egress: bool = False,
    ) -> AnswerResult:
        if approve_external_corpus_egress is not True:
            raise PermissionError("external_corpus_egress_not_approved")
        if not isinstance(question, str) or not question.strip() or len(question) > 4_000:
            raise ValueError("invalid_question")
        if doc_ids is None and self._metadata_catalog is not None:
            raise ValueError("invalid_document_scope")
        if doc_ids is None:
            document_scope = {"mode": "all", "doc_ids": []}
        else:
            selected_doc_ids = list(dict.fromkeys(doc_ids))
            if (
                not selected_doc_ids
                or len(selected_doc_ids) > 20
                or len(selected_doc_ids) != len(doc_ids)
                or any(doc_id not in self._document_by_id for doc_id in selected_doc_ids)
            ):
                raise ValueError("invalid_document_scope")
            document_scope = {"mode": "explicit", "doc_ids": selected_doc_ids}
        request = {
            "schema_version": "1.0",
            "request_id": f"ui-{uuid.uuid4().hex}",
            "question": question.strip(),
            "history": self._history_payload(history),
            "document_scope": document_scope,
            "options": {"max_citations": self.runtime.max_citations},
        }
        if validate_request(request):
            raise RuntimeError("application_request_contract_failed")
        result = self._get_pipeline().query(
            request,
            trace_context={
                "api_profile": self.runtime.api_profile,
                "index_config_sha256": self.runtime.index_config_sha256,
                "config_sha256": self.runtime.run_config_sha256,
            },
        )
        return self._answer_result(result)

    def _answer_result(self, result: PipelineResult) -> AnswerResult:
        response = result.response
        citations: list[CitationSummary] = []
        for citation in response["citations"]:
            document = self._document_by_id.get(citation["doc_id"])
            if document is None:
                raise RuntimeError("citation_catalog_join_failed")
            locator = citation["locator"]
            citations.append(
                CitationSummary(
                    doc_id=citation["doc_id"],
                    chunk_id=citation["chunk_id"],
                    source_block_ids=tuple(citation["source_block_ids"]),
                    project_name=document.project_name,
                    ordering_agency=document.ordering_agency,
                    section_path=tuple(locator["section_path"]),
                    page_start=locator["page_start"],
                    page_end=locator["page_end"],
                    metadata_card=(
                        self._metadata_card_by_id[citation["doc_id"]]
                        if self._metadata_catalog is not None
                        else None
                    ),
                    source_locator=(
                        _display_text(
                            locator.get("source_locator"),
                            "",
                            limit=1_000,
                        )
                        or None
                    ),
                )
            )
        abstention = response["abstention"]
        error = response["error"]
        return AnswerResult(
            status=response["status"],
            answer=response["answer"],
            citations=tuple(citations),
            abstention_reason=abstention["reason"] if abstention else None,
            abstention_detail=abstention["detail"] if abstention else None,
            error_code=error["code"] if error else None,
            error_message=error["message"] if error else None,
            trace_id=response["trace_id"],
            retrieval_count=len(result.retrieval),
            retrieval_ms=float(result.timing_ms["retrieval"]),
            generation_ms=float(result.timing_ms["generation"]),
            total_ms=float(result.timing_ms["total"]),
            input_tokens=int(result.usage["input_tokens"]),
            output_tokens=int(result.usage["output_tokens"]),
            embedding_tokens=int(result.usage["embedding_tokens"]),
            cost_usd=float(result.usage["cost_usd"]),
            cache_hit=bool(result.cache_hit),
        )

    def flush(self) -> None:
        pipeline = self._pipeline
        if pipeline is not None:
            pipeline.flush_observability()
