from __future__ import annotations

from dataclasses import dataclass
import unittest

from midprojectrag.answering import PipelineResult
from midprojectrag.application.service import (
    ConversationTurn,
    DocumentSummary,
    RagApplicationService,
    RuntimeDescriptor,
    document_summaries_from_catalog,
)


DOC_1 = "doc_000000000000000000000001"
DOC_2 = "doc_000000000000000000000002"
CHUNK_1 = "chunk_000000000000000000000001"
BLOCK_1 = "block_000000000000000000000001"


def _runtime() -> RuntimeDescriptor:
    return RuntimeDescriptor(
        runtime_id="test-runtime",
        config_sha256="1" * 64,
        index_config_sha256="2" * 64,
        run_config_sha256="3" * 64,
        api_profile="personal_experimental",
        embedding_model="text-embedding-3-small",
        embedding_dimensions=2,
        generator_model="gpt-5-nano",
        retrieval_top_k=10,
        context_top_k=5,
        max_citations=3,
        retrieval_manifest_sha256="4" * 64,
        catalog_manifest_sha256="5" * 64,
        catalog_snapshot_id="snapshot_test",
        document_count=2,
        observability_backend="disabled",
    )


def _pipeline_result(status: str = "answered") -> PipelineResult:
    if status == "answered":
        response = {
            "schema_version": "1.0",
            "request_id": "req-1",
            "status": "answered",
            "answer": "예산은 10원입니다.",
            "citations": [
                {
                    "doc_id": DOC_1,
                    "chunk_id": CHUNK_1,
                    "source_block_ids": [BLOCK_1],
                    "locator": {
                        "section_path": ["사업 개요"],
                        "page_start": 2,
                        "page_end": 2,
                    },
                }
            ],
            "abstention": None,
            "error": None,
            "trace_id": "trace-1",
        }
    else:
        response = {
            "schema_version": "1.0",
            "request_id": "req-1",
            "status": "abstained",
            "answer": "제공된 문서에서 답변 근거를 찾지 못했습니다.",
            "citations": [],
            "abstention": {
                "reason": "insufficient_evidence",
                "detail": "근거가 부족합니다.",
            },
            "error": None,
            "trace_id": "trace-1",
        }
    return PipelineResult(
        response=response,
        retrieval=[{"rank": 1, "doc_id": DOC_1, "chunk_id": CHUNK_1}],
        timing_ms={"retrieval": 4.0, "generation": 6.0, "total": 10.0},
        usage={
            "input_tokens": 100,
            "output_tokens": 20,
            "embedding_tokens": 5,
            "cost_usd": 0.00001,
        },
        cache_hit=True,
    )


class _Pipeline:
    def __init__(self, result: PipelineResult | None = None) -> None:
        self.result = result or _pipeline_result()
        self.calls: list[tuple[dict, dict]] = []
        self.flushed = False

    def query(self, request, *, trace_context=None):
        self.calls.append((request, dict(trace_context or {})))
        return self.result

    def flush_observability(self):
        self.flushed = True


@dataclass(frozen=True)
class _Evidence:
    source_type: str
    locator: str


@dataclass(frozen=True)
class _Fact:
    field: str
    value: str | None
    normalized_value: str | None = None
    value_type: str = "text"
    state: str = "source_recorded"
    decision: str | None = None
    reason_code: str | None = None
    confidence: str | None = None
    correction_id: str | None = None
    checked_at: str | None = None
    fact_id: str = "fact_000000000000000000000001"
    doc_id: str = DOC_1
    evidence: tuple[_Evidence, ...] = (
        _Evidence("official_web", "https://private.example.test/evidence"),
    )


@dataclass(frozen=True)
class _Card:
    doc_id: str
    project_name: str
    ordering_agency: str

    @property
    def facts(self) -> tuple[_Fact, ...]:
        return (
            _Fact(
                field="project_name",
                value=self.project_name,
                normalized_value=self.project_name,
                doc_id=self.doc_id,
            ),
            _Fact(
                field="ordering_agency",
                value=self.ordering_agency,
                normalized_value=self.ordering_agency,
                fact_id="fact_000000000000000000000002",
                doc_id=self.doc_id,
            ),
        )

    def get_fact(self, field: str) -> _Fact:
        return next(fact for fact in self.facts if fact.field == field)


@dataclass(frozen=True)
class _SearchResult:
    total_count: int
    documents: tuple[_Card, ...]


class _Catalog:
    def __init__(self, cards: tuple[_Card, ...]) -> None:
        self.cards = cards

    def list_documents(self) -> tuple[_Card, ...]:
        return self.cards

    def search(self, _filters) -> _SearchResult:
        return _SearchResult(total_count=len(self.cards), documents=self.cards)

    def get_document(self, doc_id: str) -> _Card:
        return next(card for card in self.cards if card.doc_id == doc_id)


class ApplicationServiceTests(unittest.TestCase):
    def _service(self, pipeline: _Pipeline) -> RagApplicationService:
        return RagApplicationService(
            pipeline=pipeline,
            documents=(
                DocumentSummary(DOC_1, "테스트 사업", "테스트 기관"),
                DocumentSummary(DOC_2, "다른 사업", "다른 기관"),
            ),
            runtime=_runtime(),
        )

    def test_egress_is_required_before_pipeline_call(self) -> None:
        pipeline = _Pipeline()
        with self.assertRaisesRegex(PermissionError, "external_corpus_egress_not_approved"):
            self._service(pipeline).ask(question="예산은?")
        self.assertEqual(pipeline.calls, [])

    def test_lazy_pipeline_is_created_once_only_after_approved_ask(self) -> None:
        pipeline = _Pipeline()
        factory_calls: list[str] = []

        def factory() -> _Pipeline:
            factory_calls.append("created")
            return pipeline

        service = RagApplicationService(
            pipeline_factory=factory,
            documents=(
                DocumentSummary(DOC_1, "CATALOG_ONLY_CANARY", "기관"),
                DocumentSummary(DOC_2, "다른 사업", "다른 기관"),
            ),
            runtime=_runtime(),
        )
        self.assertEqual(service.list_documents()[0].project_name, "CATALOG_ONLY_CANARY")
        service.flush()
        self.assertEqual(factory_calls, [])

        with self.assertRaisesRegex(PermissionError, "external_corpus_egress_not_approved"):
            service.ask(question="본문 질문")
        self.assertEqual(factory_calls, [])

        service.ask(question="본문 질문", approve_external_corpus_egress=True)
        service.ask(question="다른 본문 질문", approve_external_corpus_egress=True)
        self.assertEqual(factory_calls, ["created"])
        self.assertEqual(len(pipeline.calls), 2)
        request, trace_context = pipeline.calls[0]
        self.assertNotIn("CATALOG_ONLY_CANARY", repr(request))
        self.assertNotIn("CATALOG_ONLY_CANARY", repr(trace_context))

        service.flush()
        self.assertTrue(pipeline.flushed)

    def test_catalog_lookup_and_citation_card_stay_out_of_provider_payloads(self) -> None:
        canary = "CATALOG_ONLY_CANARY_7291"
        card = _Card(DOC_1, canary, "감사 기관")
        catalog = _Catalog((card, _Card(DOC_2, "다른 사업", "다른 기관")))
        pipeline = _Pipeline()
        service = RagApplicationService(
            pipeline=pipeline,
            metadata_catalog=catalog,
            runtime=_runtime(),
        )

        public_cards = service.list_document_cards()
        self.assertIsNot(public_cards[0], card)
        self.assertEqual(public_cards[0].project_name, canary)
        self.assertEqual(service.search_documents(object()).total_count, 2)
        public_card = service.get_document_card(DOC_1)
        self.assertEqual(public_card.doc_id, DOC_1)
        self.assertFalse(hasattr(public_card.facts[0].evidence[0], "locator"))
        self.assertNotIn("private.example.test", repr(public_card))
        self.assertEqual(service.list_documents()[0].project_name, canary)

        result = service.ask(
            question="본문에 적힌 내용을 요약해줘",
            doc_ids=(DOC_1,),
            approve_external_corpus_egress=True,
        )
        request, trace_context = pipeline.calls[0]
        self.assertNotIn(canary, repr(request))
        self.assertNotIn(canary, repr(trace_context))
        self.assertEqual(result.citations[0].metadata_card, public_card)

    def test_metadata_catalog_requires_explicit_scope_before_lazy_pipeline(self) -> None:
        factory_calls: list[str] = []

        def factory() -> _Pipeline:
            factory_calls.append("created")
            return _Pipeline()

        service = RagApplicationService(
            pipeline_factory=factory,
            metadata_catalog=_Catalog((_Card(DOC_1, "사업", "기관"),)),
            runtime=_runtime(),
        )
        with self.assertRaisesRegex(ValueError, "invalid_document_scope"):
            service.ask(
                question="본문 질문",
                approve_external_corpus_egress=True,
            )
        self.assertEqual(factory_calls, [])

    def test_legacy_service_rejects_typed_catalog_lookup(self) -> None:
        service = self._service(_Pipeline())
        for operation in (
            service.list_document_cards,
            lambda: service.search_documents(object()),
            lambda: service.get_document_card(DOC_1),
        ):
            with self.assertRaisesRegex(RuntimeError, "metadata_catalog_unavailable"):
                operation()

    def test_requires_exactly_one_pipeline_source(self) -> None:
        documents = (DocumentSummary(DOC_1, "테스트 사업", "테스트 기관"),)
        with self.assertRaisesRegex(ValueError, "invalid_pipeline_source"):
            RagApplicationService(documents=documents, runtime=_runtime())
        with self.assertRaisesRegex(ValueError, "invalid_pipeline_source"):
            RagApplicationService(
                pipeline=_Pipeline(),
                pipeline_factory=_Pipeline,
                documents=documents,
                runtime=_runtime(),
            )

    def test_builds_authoritative_all_scope_request_and_catalog_citation(self) -> None:
        pipeline = _Pipeline()
        result = self._service(pipeline).ask(
            question=" 예산은? ", approve_external_corpus_egress=True
        )
        request, trace_context = pipeline.calls[0]
        self.assertEqual(request["question"], "예산은?")
        self.assertEqual(request["document_scope"], {"mode": "all", "doc_ids": []})
        self.assertEqual(request["options"], {"max_citations": 3})
        self.assertEqual(trace_context["index_config_sha256"], "2" * 64)
        self.assertEqual(trace_context["config_sha256"], "3" * 64)
        self.assertEqual(result.citations[0].project_name, "테스트 사업")
        self.assertEqual(result.citations[0].page_start, 2)
        self.assertEqual(result.cited_doc_ids, (DOC_1,))

    def test_table_citation_preserves_verified_structure_locator(self) -> None:
        pipeline_result = _pipeline_result()
        locator = pipeline_result.response["citations"][0]["locator"]
        locator.update(
            {
                "page_start": None,
                "page_end": None,
                "source_locator": "section:2/paragraph:7/table:1",
            }
        )
        result = self._service(_Pipeline(pipeline_result)).ask(
            question="표의 항목은?",
            approve_external_corpus_egress=True,
        )

        citation = result.citations[0]
        self.assertIsNone(citation.page_start)
        self.assertIsNone(citation.page_end)
        self.assertEqual(
            citation.source_locator,
            "section:2/paragraph:7/table:1",
        )

    def test_explicit_scope_and_history_are_bounded(self) -> None:
        pipeline = _Pipeline(_pipeline_result("abstained"))
        history = tuple(
            ConversationTurn(role="user", content=f"질문 {index}")
            for index in range(25)
        )
        result = self._service(pipeline).ask(
            question="후속 질문",
            history=history,
            doc_ids=(DOC_2,),
            approve_external_corpus_egress=True,
        )
        request = pipeline.calls[0][0]
        self.assertEqual(
            request["document_scope"], {"mode": "explicit", "doc_ids": [DOC_2]}
        )
        self.assertEqual(len(request["history"]), 20)
        self.assertEqual(request["history"][0]["content"], "질문 5")
        self.assertEqual(result.abstention_reason, "insufficient_evidence")

    def test_unknown_or_duplicate_explicit_scope_fails_before_pipeline(self) -> None:
        pipeline = _Pipeline()
        service = self._service(pipeline)
        for doc_ids in ((DOC_1, DOC_1), ("doc_ffffffffffffffffffffffff",)):
            with self.assertRaisesRegex(ValueError, "invalid_document_scope"):
                service.ask(
                    question="질문",
                    doc_ids=doc_ids,
                    approve_external_corpus_egress=True,
                )
        self.assertEqual(pipeline.calls, [])

    def test_catalog_labels_are_sanitized_and_snapshot_bound(self) -> None:
        rows = [
            {
                "doc_id": DOC_1,
                "snapshot_id": "snapshot_test",
                "metadata": {
                    "project_name": "  사업\u202e명  ",
                    "ordering_agency": "기관\n이름",
                },
            }
        ]
        documents = document_summaries_from_catalog(
            rows,
            expected_doc_ids={DOC_1},
            expected_snapshot_id="snapshot_test",
        )
        self.assertEqual(documents[0].project_name, "사업명")
        self.assertEqual(documents[0].ordering_agency, "기관이름")
        self.assertTrue(documents[0].label.endswith("…000001"))


if __name__ == "__main__":
    unittest.main()
