from __future__ import annotations

import os
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import streamlit as st
from streamlit.testing.v1 import AppTest

from apps.streamlit_app import _runtime_paths, main
from midprojectrag.application import (
    AnswerResult,
    CitationSummary,
    RuntimeDescriptor,
)
from midprojectrag.catalog import (
    CatalogFilter,
    DocumentCard,
    MetadataCatalog,
    materialize_catalog,
)
from tests.catalog.helpers import SNAPSHOT_ID, artifacts


DOC_ID = "doc_000000000000000000000001"


def _runtime() -> RuntimeDescriptor:
    return RuntimeDescriptor(
        runtime_id="ui-test",
        config_sha256="1" * 64,
        index_config_sha256="2" * 64,
        run_config_sha256="3" * 64,
        api_profile="personal_experimental",
        embedding_model="text-embedding-3-small",
        embedding_dimensions=1536,
        generator_model="gpt-5-nano",
        retrieval_top_k=10,
        context_top_k=5,
        max_citations=3,
        retrieval_manifest_sha256="4" * 64,
        catalog_manifest_sha256="5" * 64,
        catalog_snapshot_id="snapshot_test",
        document_count=1,
        observability_backend="disabled",
    )


def _result(status: str) -> AnswerResult:
    answered = status == "answered"
    citation = CitationSummary(
        doc_id=DOC_ID,
        chunk_id="chunk_000000000000000000000001",
        source_block_ids=("block_000000000000000000000001",),
        project_name="테스트 사업",
        ordering_agency="테스트 기관",
        section_path=("사업 개요",),
        page_start=3,
        page_end=3,
    )
    return AnswerResult(
        status=status,
        answer=(
            "예산은 10원입니다."
            if answered
            else "제공된 문서에서 답변 근거를 찾지 못했습니다."
        ),
        citations=(citation,) if answered else (),
        abstention_reason=None if answered else "insufficient_evidence",
        abstention_detail=None if answered else "근거가 부족합니다.",
        error_code=None,
        error_message=None,
        trace_id="trace-1",
        retrieval_count=10,
        retrieval_ms=10.0,
        generation_ms=20.0,
        total_ms=30.0,
        input_tokens=100,
        output_tokens=20,
        embedding_tokens=5,
        cost_usd=0.00001,
        cache_hit=True,
    )


class _FakeService:
    def __init__(self, status: str) -> None:
        self.runtime = _runtime()
        self.status = status
        rows, corrections, retrieval = artifacts()
        self.catalog = materialize_catalog(
            rows,
            corrections,
            retrieval,
            expected_snapshot_id=SNAPSHOT_ID,
        )

    def list_documents(self):
        return self.catalog.list_documents()

    def list_document_cards(self):
        return self.catalog.list_documents()

    def search_documents(self, filters: CatalogFilter):
        return self.catalog.search(filters)

    def get_document_card(self, doc_id: str) -> DocumentCard:
        return self.catalog.get_document(doc_id)

    def ask(
        self,
        *,
        question,
        history=(),
        doc_ids=None,
        approve_external_corpus_egress=False,
    ):
        st.session_state["fake_call"] = {
            "question": question,
            "history_count": len(history),
            "doc_ids": list(doc_ids) if doc_ids is not None else None,
            "approved": approve_external_corpus_egress,
        }
        result = _result(self.status)
        if result.citations:
            result = replace(
                result,
                citations=(
                    replace(
                        result.citations[0],
                        metadata_card=self.catalog.get_document(DOC_ID),
                    ),
                ),
            )
        return result


class _TableFakeService(_FakeService):
    def ask(self, **kwargs):
        result = super().ask(**kwargs)
        citation = result.citations[0]
        return replace(
            result,
            citations=(
                replace(
                    citation,
                    page_start=None,
                    page_end=None,
                    source_locator="section:2/paragraph:7/table:1",
                ),
            ),
        )


class _MaliciousCatalogService(_FakeService):
    def __init__(self, status: str) -> None:
        super().__init__(status)
        rows, corrections, retrieval = artifacts()
        rows[0]["metadata"]["project_name"] = "![external](https://example.invalid/pixel)"
        rows[0]["metadata"]["ordering_agency"] = "[agency](https://example.invalid)"
        self.catalog = materialize_catalog(
            rows,
            corrections,
            retrieval,
            expected_snapshot_id=SNAPSHOT_ID,
        )

    def ask(self, **kwargs):
        result = super().ask(**kwargs)
        citation = result.citations[0]
        return AnswerResult(
            **{
                **result.__dict__,
                "citations": (
                    CitationSummary(
                        **{
                            **citation.__dict__,
                            "project_name": "![external](https://example.invalid/pixel)",
                            "ordering_agency": "[agency](https://example.invalid)",
                        }
                    ),
                ),
            }
        )


class _ManyCatalogService(_FakeService):
    def __init__(self, status: str) -> None:
        super().__init__(status)
        template = self.catalog.get_document(DOC_ID)
        cards: list[DocumentCard] = []
        for doc_index in range(1, 26):
            doc_id = f"doc_{doc_index:024x}"
            facts = tuple(
                replace(
                    fact,
                    fact_id=f"fact_{doc_index * 100 + fact_index:024x}",
                    doc_id=doc_id,
                )
                for fact_index, fact in enumerate(template.facts, start=1)
            )
            cards.append(DocumentCard(doc_id=doc_id, facts=facts))
        self.catalog = MetadataCatalog(tuple(cards))
        self.runtime = replace(self.runtime, document_count=len(cards))


def _answered_app() -> None:
    from apps.streamlit_app import main as run_app
    from tests.ui.test_streamlit_app import _FakeService as FakeService

    run_app(FakeService("answered"))


def _abstained_app() -> None:
    from apps.streamlit_app import main as run_app
    from tests.ui.test_streamlit_app import _FakeService as FakeService

    run_app(FakeService("abstained"))


def _table_answered_app() -> None:
    from apps.streamlit_app import main as run_app
    from tests.ui.test_streamlit_app import _TableFakeService as TableFakeService

    run_app(TableFakeService("answered"))


def _malicious_catalog_app() -> None:
    from apps.streamlit_app import main as run_app
    from tests.ui.test_streamlit_app import (
        _MaliciousCatalogService as MaliciousCatalogService,
    )

    run_app(MaliciousCatalogService("answered"))


def _many_catalog_app() -> None:
    from apps.streamlit_app import main as run_app
    from tests.ui.test_streamlit_app import _ManyCatalogService as ManyCatalogService

    run_app(ManyCatalogService("answered"))


class StreamlitAppTests(unittest.TestCase):
    @staticmethod
    def _text_input(app: AppTest, label: str):
        return next(item for item in app.text_input if item.label == label)

    @staticmethod
    def _multiselect(app: AppTest, label: str):
        return next(item for item in app.multiselect if item.label == label)

    def test_default_paths_activate_refined98_page_bundle(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            config_path, data_dir = _runtime_paths()
        root = Path(__file__).resolve().parents[2]
        self.assertEqual(
            config_path,
            root
            / "configs"
            / "rag"
            / "api-small-nano-streamlit-refined98-page-v2.json",
        )
        self.assertEqual(data_dir, root / "resources" / "data_refined")

    def test_runtime_path_environment_overrides_remain_supported(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "MIDPROJECTRAG_STREAMLIT_CONFIG": "/tmp/custom-runtime.json",
                "MIDPROJECTRAG_DATA_DIR": "/tmp/custom-data",
            },
            clear=True,
        ):
            config_path, data_dir = _runtime_paths()
        self.assertEqual(config_path, Path("/tmp/custom-runtime.json"))
        self.assertEqual(data_dir, Path("/tmp/custom-data"))

    def test_answered_flow_renders_verified_page_citation(self) -> None:
        app = AppTest.from_function(_answered_app).run()
        self.assertEqual(len(app.exception), 0)
        self._multiselect(app, "검색할 문서 (최대 20건)").set_value([DOC_ID]).run()
        app.checkbox[0].set_value(True).run()
        app.chat_input[0].set_value("예산은?").run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.session_state["fake_call"]["question"], "예산은?")
        self.assertTrue(app.session_state["fake_call"]["approved"])
        rendered_markdown = "\n".join(item.value for item in app.markdown)
        rendered_text = "\n".join(item.value for item in app.text)
        self.assertIn("예산은 10원입니다.", rendered_markdown)
        self.assertIn("테스트 사업", rendered_text)
        self.assertIn("p.3", rendered_text)
        self.assertEqual(len(app.session_state["messages"]), 2)
        self.assertEqual(len(app.session_state["history"]), 2)

    def test_table_citation_renders_verified_structure_locator_without_page(self) -> None:
        app = AppTest.from_function(_table_answered_app).run()
        self.assertEqual(len(app.exception), 0)
        self._multiselect(app, "검색할 문서 (최대 20건)").set_value([DOC_ID]).run()
        app.checkbox[0].set_value(True).run()
        app.chat_input[0].set_value("표의 항목은?").run()

        self.assertEqual(len(app.exception), 0)
        rendered_text = "\n".join(item.value for item in app.text)
        self.assertIn("구조 위치: section:2/paragraph:7/table:1", rendered_text)
        self.assertNotIn("페이지 정보 없음", rendered_text)

    def test_explicit_scope_passes_only_selected_doc_id(self) -> None:
        app = AppTest.from_function(_answered_app).run()
        app.radio[0].set_value("explicit").run()
        app.multiselect[0].set_value([DOC_ID]).run()
        app.checkbox[0].set_value(True).run()
        app.chat_input[0].set_value("요구사항은?").run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.session_state["fake_call"]["doc_ids"], [DOC_ID])

    def test_metadata_filter_browses_locally_then_routes_selected_document(self) -> None:
        app = AppTest.from_function(_answered_app).run()
        app.radio[0].set_value("metadata").run()
        self._text_input(app, "발주 기관").set_value("가각").run()
        metrics = {item.label: item.value for item in app.metric}
        self.assertEqual(metrics["조건 일치"], "1")
        self.assertNotIn("fake_call", app.session_state)

        self._multiselect(app, "질문에 사용할 문서 (최대 20건)").set_value(
            [DOC_ID]
        ).run()
        rendered_text = "\n".join(item.value for item in app.text)
        self.assertIn("AI 관제 구축", rendered_text)
        self.assertIn("공고 번호: N-001", rendered_text)
        self.assertIn("official_web", rendered_text)
        self.assertNotIn("example.test", rendered_text)

        app.checkbox[0].set_value(True).run()
        app.chat_input[0].set_value("요구사항은?").run()
        self.assertEqual(app.session_state["fake_call"]["doc_ids"], [DOC_ID])

    def test_metadata_filter_change_clears_selection_and_history(self) -> None:
        app = AppTest.from_function(_answered_app).run()
        app.radio[0].set_value("metadata").run()
        self._multiselect(app, "질문에 사용할 문서 (최대 20건)").set_value(
            [DOC_ID]
        ).run()
        app.session_state["history"] = ["stale"]
        app.session_state["messages"] = ["stale"]
        self._text_input(app, "발주 기관").set_value("나나").run()
        self.assertEqual(list(app.session_state["metadata_doc_ids"]), [])
        self.assertEqual(list(app.session_state["history"]), [])
        self.assertEqual(list(app.session_state["messages"]), [])

    def test_metadata_results_over_twenty_are_counted_without_truncation(self) -> None:
        app = AppTest.from_function(_many_catalog_app).run()
        app.radio[0].set_value("metadata").run()
        metrics = {item.label: item.value for item in app.metric}
        self.assertEqual(metrics["조건 일치"], "25")
        selector = self._multiselect(app, "질문에 사용할 문서 (최대 20건)")
        self.assertEqual(len(selector.options), 25)
        captions = "\n".join(item.value for item in app.caption)
        self.assertIn("결과를 자동으로 자르지 않았습니다", captions)

    def test_abstention_is_visible_without_citations(self) -> None:
        app = AppTest.from_function(_abstained_app).run()
        self._multiselect(app, "검색할 문서 (최대 20건)").set_value([DOC_ID]).run()
        app.checkbox[0].set_value(True).run()
        app.chat_input[0].set_value("없는 정보는?").run()
        self.assertEqual(len(app.exception), 0)
        warnings = "\n".join(item.value for item in app.warning)
        self.assertIn("제공된 문서에서 답변 근거를 찾지 못했습니다.", warnings)
        self.assertNotIn("근거 문서", "\n".join(item.label for item in app.expander))

    def test_catalog_citation_is_rendered_as_plain_text(self) -> None:
        app = AppTest.from_function(_malicious_catalog_app).run()
        self._multiselect(app, "검색할 문서 (최대 20건)").set_value([DOC_ID]).run()
        app.checkbox[0].set_value(True).run()
        app.chat_input[0].set_value("예산은?").run()
        rendered_text = "\n".join(item.value for item in app.text)
        self.assertIn("![external](https://example.invalid/pixel)", rendered_text)


if __name__ == "__main__":
    unittest.main()
