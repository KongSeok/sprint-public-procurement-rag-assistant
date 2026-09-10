from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from midprojectrag.answering import PipelineResult
from midprojectrag.application import CatalogFilter, load_rag_application
from midprojectrag.application.composition import (
    _single_chunk_config_sha256,
    _validate_table_layout_binding,
)
from midprojectrag.ingest.common import (
    canonical_json,
    read_jsonl,
    sha256_file,
    sha256_text,
    write_json,
    write_jsonl,
)
from midprojectrag.ingest.table_layout import table_layout_resolution_reason
from midprojectrag.indexing.chunking import chunk_artifact_sha256
from midprojectrag.indexing.exact_index import ExactDenseIndex
from midprojectrag.indexing.fusion import DualLaneIndex
from midprojectrag.stacks.api import (
    api_config_sha256,
    build_api_index_config,
    build_api_run_config,
)


DOC_ID = "doc_000000000000000000000001"
BLOCK_ID = "block_000000000000000000000001"


class _Counter:
    def count(self, text: str) -> int:
        return max(1, len(text))


class _CapturedPipeline:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, object], dict[str, object]]] = []

    def query(self, request, *, trace_context=None) -> PipelineResult:
        self.calls.append((request, dict(trace_context or {})))
        return PipelineResult(
            response={
                "schema_version": "1.0",
                "request_id": request["request_id"],
                "status": "answered",
                "answer": "본문 근거 답변",
                "citations": [
                    {
                        "doc_id": DOC_ID,
                        "chunk_id": _chunk()["chunk_id"],
                        "source_block_ids": [BLOCK_ID],
                        "locator": {
                            "section_path": [],
                            "page_start": 1,
                            "page_end": 1,
                        },
                    }
                ],
                "abstention": None,
                "error": None,
                "trace_id": "trace-synthetic",
            },
            retrieval=[{"rank": 1, "doc_id": DOC_ID, "chunk_id": _chunk()["chunk_id"]}],
            timing_ms={"retrieval": 1.0, "generation": 2.0, "total": 3.0},
            usage={
                "input_tokens": 1,
                "output_tokens": 1,
                "embedding_tokens": 1,
                "cost_usd": 0.0,
            },
            cache_hit=False,
        )

    def flush_observability(self) -> None:
        return None


def _chunk() -> dict[str, object]:
    text = "테스트 예산은 10원"
    content_sha256 = sha256_text(text)
    config_sha256 = "1" * 64
    identity = {
        "block_id": BLOCK_ID,
        "config_sha256": config_sha256,
        "content_sha256": content_sha256,
        "doc_id": DOC_ID,
        "page_end": 1,
        "page_start": 1,
        "part_count": 1,
        "part_index": 0,
    }
    return {
        "schema_version": "1.0",
        "chunk_id": f"chunk_{sha256_text(canonical_json(identity))[:24]}",
        "doc_id": DOC_ID,
        "text": text,
        "source_block_ids": [BLOCK_ID],
        "section_path": [],
        "page_start": 1,
        "page_end": 1,
        "part_index": 0,
        "part_count": 1,
        "retrieval_role": "primary",
        "chunker_id": "page-v1",
        "config_sha256": config_sha256,
        "content_sha256": content_sha256,
    }


def _table_chunk(*, doc_id: str = DOC_ID) -> dict[str, object]:
    block_id = f"block_{sha256_text(f'table:{doc_id}')[:24]}"
    display_markdown = "| 항목 | 값 |\n| --- | --- |\n| 예산 | 10원 |"
    text = (
        "[사업명] 테스트 사업\n"
        "[발주기관] 테스트 기관\n"
        "[표 위치] section:0/paragraph:1/table:0\n\n"
        f"{display_markdown}"
    )
    content_sha256 = sha256_text(text)
    config_sha256 = "2" * 64
    table_structure_sha256 = "4" * 64
    identity = {
        "block_id": block_id,
        "config_sha256": config_sha256,
        "content_sha256": content_sha256,
        "doc_id": doc_id,
        "part_count": 1,
        "part_index": 0,
        "row_end": 1,
        "row_start": 1,
        "source_locator": "section:0/paragraph:1/table:0",
        "table_structure_sha256": table_structure_sha256,
    }
    return {
        "schema_version": "1.1",
        "chunk_id": f"chunk_{sha256_text(canonical_json(identity))[:24]}",
        "doc_id": doc_id,
        "text": text,
        "display_markdown": display_markdown,
        "source_block_ids": [block_id],
        "section_path": [],
        "page_start": 1,
        "page_end": 1,
        "source_locator": "section:0/paragraph:1/table:0",
        "row_start": 1,
        "row_end": 1,
        "part_index": 0,
        "part_count": 1,
        "retrieval_role": "structured_auxiliary",
        "chunker_id": "table-md-rowgroup-v1",
        "config_sha256": config_sha256,
        "content_sha256": content_sha256,
        "display_sha256": sha256_text(display_markdown),
        "source_structure_sha256": "3" * 64,
        "table_structure_sha256": table_structure_sha256,
        "header_source": "explicit",
    }


def _table_layout_record(
    chunk: dict[str, object], *, page: int = 1
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "doc_id": chunk["doc_id"],
        "block_id": chunk["source_block_ids"][0],
        "structure_sha256": chunk["source_structure_sha256"],
        "page_start": page,
        "page_end": page,
        "page_bboxes": [
            {
                "page": page,
                "bbox": {"x": 10.0, "y": 20.0, "w": 30.0, "h": 40.0},
                "page_bbox": {
                    "x": 0.0,
                    "y": 0.0,
                    "w": 100.0,
                    "h": 100.0,
                },
                "bbox_valid": True,
            }
        ],
        "coordinate_space": "rhwp_css_px_96dpi",
        "render_key": {"section": 0, "paragraph": 1, "control": 0},
        "wrapper_flattened": False,
        "anchor_present": True,
        "status": "verified_render",
        "resolution_reason": "exact_render_match",
    }


def _write_version_1_1_bundle(root: Path) -> tuple[Path, Path, Path, str]:
    data_dir = root / "corpus"
    private = data_dir / "private"
    index_dir = private / "indexes" / "api" / "personal_experimental" / "small-2"
    chunks_path = private / "chunks.jsonl"
    retrieval_path = private / "manifest.jsonl"
    catalog_path = private / "catalog.jsonl"
    correction_path = private / "metadata-corrections" / "corrections.json"
    snapshot_id = "snapshot_test"
    canary = "CATALOG_ONLY_CANARY_7291"
    identity = {
        "doc_id": DOC_ID,
        "sha256": "a" * 64,
        "normalized_filename": "test.hwp",
        "snapshot_id": snapshot_id,
    }
    write_jsonl(retrieval_path, [{**identity, "page_count": 1}])
    write_jsonl(
        catalog_path,
        [
            {
                **identity,
                "csv_row_number": 2,
                "metadata": {
                    "notice_id_namespace": "g2b",
                    "notice_number": canary,
                    "notice_round": "00",
                    "project_name": "테스트 사업",
                    "project_amount_raw": "1000",
                    "project_amount_value": "1000",
                    "ordering_agency": "테스트 기관",
                    "published_at": "2026-01-01 09:00:00",
                    "bid_start_at": "",
                    "bid_end_at": "2026-01-03 17:00:00",
                    "bid_open_at": "",
                    "proposal_evaluation_at": "",
                    "source_format": "hwp",
                },
            }
        ],
    )
    correction_set = {
        "schema_version": "1.0",
        "source_csv_sha256": "b" * 64,
        "created_at": "2026-08-26T00:00:00Z",
        "corrections": [
            {
                "correction_id": "corr_notice_number_canary",
                "csv_row_number": 2,
                "row_sha256": "c" * 64,
                "field": "notice_number",
                "old_value": None,
                "new_value": canary,
                "decision": "apply",
                "reason_code": "official_source_confirmed",
                "confidence": "high",
                "checked_at": "2026-08-26",
                "evidence": [
                    {
                        "source_type": "official_web",
                        "locator": "https://example.test/private-canary",
                    }
                ],
            }
        ],
    }
    write_json(correction_path, correction_set)
    chunks = [_chunk()]
    write_jsonl(chunks_path, chunks)
    manifest_sha256 = sha256_file(retrieval_path)
    index_config = build_api_index_config(
        api_profile="personal_experimental",
        corpus_manifest_sha256=manifest_sha256,
        chunk_artifact_sha256=chunk_artifact_sha256(chunks),
        chunk_config_sha256="1" * 64,
        embedding_model="text-embedding-3-small",
        embedding_dimensions=2,
        index_engine="numpy",
        batch_size=1,
    )
    index_config_hash = api_config_sha256(index_config)
    ExactDenseIndex(
        chunks,
        np.asarray([[1.0, 0.0]], dtype=np.float32),
        engine="numpy",
    ).save(
        index_dir,
        corpus_manifest_sha256=manifest_sha256,
        embedding_model="text-embedding-3-small",
        api_profile="personal_experimental",
        index_config_sha256=index_config_hash,
    )
    write_json(index_dir / "index-config.json", index_config)
    config = {
        "schema_version": "1.1",
        "runtime_id": "synthetic-small-nano-metadata",
        "stack_id": "api",
        "api_profile": "personal_experimental",
        "embedding": {"model": "text-embedding-3-small", "dimensions": 2},
        "generation": {"model": "gpt-5-nano", "max_output_tokens": 2000},
        "retrieval": {"top_k": 10, "context_top_k": 5, "max_citations": 3},
        "artifacts": {
            "retrieval_manifest": {
                "path": "private/manifest.jsonl",
                "sha256": manifest_sha256,
            },
            "chunks": {
                "path": "private/chunks.jsonl",
                "sha256": sha256_file(chunks_path),
            },
            "catalog_manifest": {
                "path": "private/catalog.jsonl",
                "sha256": sha256_file(catalog_path),
                "snapshot_id": snapshot_id,
            },
            "correction_set": {
                "path": "private/metadata-corrections/corrections.json",
                "sha256": sha256_file(correction_path),
            },
            "index": {
                "path": "private/indexes/api/personal_experimental/small-2",
                "metadata_sha256": sha256_file(index_dir / "metadata.json"),
                "config_file_sha256": sha256_file(index_dir / "index-config.json"),
            },
            "query_cache_path": "private/caches/api/personal_experimental/small-2",
            "tokenizer_cache_path": "private/tiktoken-cache",
            "budget_ledger_path": "private/api-budget.streamlit.json",
        },
        "budget": {"limit_usd": "5.00"},
        "observability": {"backend": "disabled"},
    }
    config_path = root / "runtime-1.1.json"
    config_path.write_text(json.dumps(config) + "\n", encoding="utf-8")
    return config_path, data_dir, correction_path, canary


def _write_version_1_2_bundle(
    root: Path,
    *,
    table_doc_id: str = DOC_ID,
    table_corpus_manifest_sha256: str | None = None,
) -> tuple[Path, Path, str, str]:
    legacy_path, data_dir, _correction_path, _canary = _write_version_1_1_bundle(
        root
    )
    with legacy_path.open("r", encoding="utf-8") as source:
        config = json.load(source)
    private = data_dir / "private"
    table_chunks_path = private / "table-chunks.jsonl"
    table_layout_path = private / "table-layout-v1.jsonl"
    table_index_dir = (
        private / "indexes" / "api" / "personal_experimental" / "small-2-table"
    )
    table_chunks = [_table_chunk(doc_id=table_doc_id)]
    write_jsonl(table_chunks_path, table_chunks)
    write_jsonl(table_layout_path, [_table_layout_record(table_chunks[0])])
    manifest_sha256 = sha256_file(private / "manifest.jsonl")
    table_manifest_sha256 = table_corpus_manifest_sha256 or manifest_sha256
    table_index_config = build_api_index_config(
        api_profile="personal_experimental",
        corpus_manifest_sha256=table_manifest_sha256,
        chunk_artifact_sha256=chunk_artifact_sha256(table_chunks),
        chunk_config_sha256="2" * 64,
        embedding_model="text-embedding-3-small",
        embedding_dimensions=2,
        index_engine="numpy",
        batch_size=1,
    )
    table_index_config_hash = api_config_sha256(table_index_config)
    ExactDenseIndex(
        table_chunks,
        np.asarray([[0.9, 0.1]], dtype=np.float32),
        engine="numpy",
    ).save(
        table_index_dir,
        corpus_manifest_sha256=table_manifest_sha256,
        embedding_model="text-embedding-3-small",
        api_profile="personal_experimental",
        index_config_sha256=table_index_config_hash,
    )
    write_json(table_index_dir / "index-config.json", table_index_config)
    page_index_dir = private / "indexes" / "api" / "personal_experimental" / "small-2"
    page_index_config = json.loads(
        (page_index_dir / "index-config.json").read_text(encoding="utf-8")
    )
    page_index_config_hash = api_config_sha256(page_index_config)

    config["schema_version"] = "1.2"
    config["runtime_id"] = "synthetic-small-nano-table"
    config["retrieval"].update(
        {
            "fusion": "rrf-v1",
            "rrf_k": 60,
            "table_retrieval_cap": 3,
            "table_context_cap": 2,
        }
    )
    del config["artifacts"]["correction_set"]
    config["artifacts"]["table_chunks"] = {
        "path": "private/table-chunks.jsonl",
        "sha256": sha256_file(table_chunks_path),
    }
    config["artifacts"]["table_layout"] = {
        "path": "private/table-layout-v1.jsonl",
        "sha256": sha256_file(table_layout_path),
    }
    config["artifacts"]["table_index"] = {
        "path": "private/indexes/api/personal_experimental/small-2-table",
        "metadata_sha256": sha256_file(table_index_dir / "metadata.json"),
        "config_file_sha256": sha256_file(table_index_dir / "index-config.json"),
    }
    config_path = root / "runtime-1.2.json"
    config_path.write_text(json.dumps(config) + "\n", encoding="utf-8")
    return (
        config_path,
        data_dir,
        page_index_config_hash,
        table_index_config_hash,
    )


class CompositionTests(unittest.TestCase):
    def test_table_layout_resolution_reason_is_bounded(self) -> None:
        self.assertEqual(
            table_layout_resolution_reason("verified_render"),
            "exact_render_match",
        )
        self.assertEqual(
            table_layout_resolution_reason("nonbody_unlinked"),
            "nonbody_excluded",
        )
        self.assertEqual(
            table_layout_resolution_reason("paragraph_anchor_candidate"),
            "render_match_missing",
        )
        self.assertIsNone(table_layout_resolution_reason("unexpected"))
        self.assertIsNone(table_layout_resolution_reason(None))

    def test_chunk_config_gate_rejects_unhashable_value_as_value_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "index_expected_config_mismatch"):
            _single_chunk_config_sha256(
                [{"config_sha256": []}],
                error_prefix="",
            )

    def test_table_layout_binding_requires_exact_body_block_coverage(self) -> None:
        chunk = _table_chunk()
        extra = dict(_table_layout_record(chunk))
        extra["block_id"] = "block_ffffffffffffffffffffffff"
        with self.assertRaisesRegex(
            ValueError,
            "table_layout_chunk_block_set_mismatch",
        ):
            _validate_table_layout_binding(
                [_table_layout_record(chunk), extra],
                [chunk],
                page_counts={DOC_ID: 1},
            )

    def test_table_layout_binding_rejects_page_outside_manifest(self) -> None:
        chunk = _table_chunk()
        with self.assertRaisesRegex(
            ValueError,
            "table_layout_page_outside_manifest",
        ):
            _validate_table_layout_binding(
                [_table_layout_record(chunk, page=2)],
                [chunk],
                page_counts={DOC_ID: 1},
            )

    def test_table_layout_binding_accepts_only_direct_flattened_nested_page(self) -> None:
        direct = _table_chunk()
        direct["source_locator"] += "/cell:0,0/nested:1"
        layout = _table_layout_record(direct)
        layout["wrapper_flattened"] = True

        _validate_table_layout_binding(
            [layout],
            [direct],
            page_counts={DOC_ID: 1},
        )

        deep = dict(direct)
        deep["source_locator"] += "/cell:1,0/nested:1"
        with self.assertRaisesRegex(ValueError, "table_layout_chunk_page_mismatch"):
            _validate_table_layout_binding(
                [layout],
                [deep],
                page_counts={DOC_ID: 1},
            )

    def test_loads_verified_bundle_before_provider_use(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_dir = root / "corpus"
            private = data_dir / "private"
            index_dir = private / "indexes" / "api" / "personal_experimental" / "small-2"
            chunks_path = private / "chunks.jsonl"
            retrieval_path = private / "manifest.jsonl"
            catalog_path = private / "catalog.jsonl"
            snapshot_id = "snapshot_test"
            source_row = {
                "doc_id": DOC_ID,
                "sha256": "a" * 64,
                "normalized_filename": "test.hwp",
                "snapshot_id": snapshot_id,
                "page_count": 1,
            }
            write_jsonl(retrieval_path, [source_row])
            write_jsonl(
                catalog_path,
                [
                    {
                        **source_row,
                        "metadata": {
                            "project_name": "테스트 사업",
                            "ordering_agency": "테스트 기관",
                        },
                    }
                ],
            )
            chunks = [_chunk()]
            write_jsonl(chunks_path, chunks)
            manifest_sha256 = sha256_file(retrieval_path)
            index_config = build_api_index_config(
                api_profile="personal_experimental",
                corpus_manifest_sha256=manifest_sha256,
                chunk_artifact_sha256=chunk_artifact_sha256(chunks),
                chunk_config_sha256="1" * 64,
                embedding_model="text-embedding-3-small",
                embedding_dimensions=2,
                index_engine="numpy",
                batch_size=1,
            )
            index_config_hash = api_config_sha256(index_config)
            ExactDenseIndex(
                chunks,
                np.asarray([[1.0, 0.0]], dtype=np.float32),
                engine="numpy",
            ).save(
                index_dir,
                corpus_manifest_sha256=manifest_sha256,
                embedding_model="text-embedding-3-small",
                api_profile="personal_experimental",
                index_config_sha256=index_config_hash,
            )
            write_json(index_dir / "index-config.json", index_config)
            config = {
                "schema_version": "1.0",
                "runtime_id": "synthetic-small-nano",
                "stack_id": "api",
                "api_profile": "personal_experimental",
                "embedding": {"model": "text-embedding-3-small", "dimensions": 2},
                "generation": {"model": "gpt-5-nano", "max_output_tokens": 2000},
                "retrieval": {"top_k": 10, "context_top_k": 5, "max_citations": 3},
                "artifacts": {
                    "retrieval_manifest": {
                        "path": "private/manifest.jsonl",
                        "sha256": manifest_sha256,
                    },
                    "chunks": {
                        "path": "private/chunks.jsonl",
                        "sha256": sha256_file(chunks_path),
                    },
                    "catalog_manifest": {
                        "path": "private/catalog.jsonl",
                        "sha256": sha256_file(catalog_path),
                        "snapshot_id": snapshot_id,
                    },
                    "index": {
                        "path": "private/indexes/api/personal_experimental/small-2",
                        "metadata_sha256": sha256_file(index_dir / "metadata.json"),
                        "config_file_sha256": sha256_file(index_dir / "index-config.json"),
                    },
                    "query_cache_path": "private/caches/api/personal_experimental/small-2",
                    "tokenizer_cache_path": "private/tiktoken-cache",
                    "budget_ledger_path": "private/api-budget.streamlit.json",
                },
                "budget": {"limit_usd": "5.00"},
                "observability": {"backend": "disabled"},
            }
            config_path = root / "runtime.json"
            config_path.write_text(json.dumps(config) + "\n", encoding="utf-8")
            with (
                mock.patch(
                    "midprojectrag.application.composition._load_project_dotenv",
                    side_effect=AssertionError("dotenv loaded during local browse"),
                ),
                mock.patch(
                    "midprojectrag.application.composition.OpenAIEmbeddingProvider",
                    side_effect=AssertionError("embedding provider constructed eagerly"),
                ),
                mock.patch(
                    "midprojectrag.application.composition.OpenAIGenerator",
                    side_effect=AssertionError("generator constructed eagerly"),
                ),
            ):
                service = load_rag_application(config_path, data_dir)
        self.assertEqual(service.runtime.embedding_model, "text-embedding-3-small")
        self.assertEqual(service.runtime.generator_model, "gpt-5-nano")
        self.assertEqual(service.runtime.index_config_sha256, index_config_hash)
        self.assertEqual(service.list_documents()[0].project_name, "테스트 사업")

    def test_version_1_1_materializes_catalog_without_provider_or_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path, data_dir, _correction_path, canary = _write_version_1_1_bundle(
                Path(directory)
            )
            with (
                mock.patch(
                    "midprojectrag.application.composition._load_project_dotenv",
                    side_effect=AssertionError("dotenv loaded during metadata lookup"),
                ),
                mock.patch(
                    "midprojectrag.application.composition.OpenAIEmbeddingProvider",
                    side_effect=AssertionError("embedding provider constructed eagerly"),
                ),
                mock.patch(
                    "midprojectrag.application.composition.OpenAIGenerator",
                    side_effect=AssertionError("generator constructed eagerly"),
                ),
            ):
                service = load_rag_application(config_path, data_dir)
                cards = service.list_document_cards()
                result = service.search_documents(CatalogFilter(notice_number=canary))
                selected = service.get_document_card(DOC_ID)

        self.assertEqual(len(cards), 1)
        self.assertEqual(result.total_count, 1)
        self.assertIs(result.documents[0], selected)
        self.assertEqual(selected.get_fact("notice_number").state, "confirmed")
        self.assertNotIn("example.test", repr(selected.to_public_dict()))

    def test_correction_hash_fails_before_materialization_or_provider_use(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path, data_dir, correction_path, _canary = _write_version_1_1_bundle(
                Path(directory)
            )
            correction_path.write_text("{}\n", encoding="utf-8")
            with (
                mock.patch(
                    "midprojectrag.application.composition.OpenAIEmbeddingProvider",
                    side_effect=AssertionError("provider reached before hash gate"),
                ),
                mock.patch(
                    "midprojectrag.application.composition.OpenAIGenerator",
                    side_effect=AssertionError("provider reached before hash gate"),
                ),
            ):
                with self.assertRaisesRegex(ValueError, "correction_set_hash_mismatch"):
                    load_rag_application(config_path, data_dir)

    def test_composed_lazy_pipeline_keeps_catalog_canary_out_of_request_and_trace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path, data_dir, _correction_path, canary = _write_version_1_1_bundle(
                Path(directory)
            )
            captured = _CapturedPipeline()
            embedding_provider = mock.Mock()
            generator = mock.Mock()
            with (
                mock.patch(
                    "midprojectrag.application.composition.OpenAIEmbeddingProvider",
                    return_value=embedding_provider,
                ) as embedding_constructor,
                mock.patch(
                    "midprojectrag.application.composition.OpenAIGenerator",
                    return_value=generator,
                ) as generator_constructor,
                mock.patch(
                    "midprojectrag.application.composition.RagPipeline",
                    return_value=captured,
                ) as pipeline_constructor,
            ):
                service = load_rag_application(
                    config_path,
                    data_dir,
                    embedding_client=object(),
                    generator_client=object(),
                    embedding_counter=_Counter(),
                    generation_counter=_Counter(),
                )
                self.assertFalse(embedding_constructor.called)
                self.assertFalse(generator_constructor.called)
                self.assertFalse(pipeline_constructor.called)

                with self.assertRaisesRegex(ValueError, "invalid_document_scope"):
                    service.ask(
                        question="본문 근거를 요약해줘",
                        approve_external_corpus_egress=True,
                    )
                self.assertFalse(embedding_constructor.called)
                self.assertFalse(generator_constructor.called)
                self.assertFalse(pipeline_constructor.called)

                answer = service.ask(
                    question="본문 근거를 요약해줘",
                    doc_ids=(DOC_ID,),
                    approve_external_corpus_egress=True,
                )
                self.assertEqual(embedding_constructor.call_count, 1)
                self.assertEqual(generator_constructor.call_count, 1)
                self.assertEqual(pipeline_constructor.call_count, 1)

            request, trace_context = captured.calls[0]
            self.assertNotIn(canary, repr(request))
            self.assertNotIn(canary, repr(trace_context))
            self.assertEqual(
                answer.citations[0].metadata_card.get_fact("notice_number").value,
                canary,
            )
            self.assertFalse(
                hasattr(
                    answer.citations[0]
                    .metadata_card.get_fact("notice_number")
                    .evidence[0],
                    "locator",
                )
            )
            self.assertNotIn("example.test", repr(answer.citations[0]))

    def test_version_1_2_composes_verified_dual_lane_and_binds_composite_run_hash(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (
                config_path,
                data_dir,
                page_index_config_hash,
                table_index_config_hash,
            ) = _write_version_1_2_bundle(Path(directory))
            expected_composite_hash = api_config_sha256(
                {
                    "schema_version": "1.0",
                    "architecture": "page-table-dual-lane",
                    "page_index_config_sha256": page_index_config_hash,
                    "table_index_config_sha256": table_index_config_hash,
                    "table_layout_sha256": sha256_file(
                        data_dir / "private" / "table-layout-v1.jsonl"
                    ),
                    "fusion": "rrf-v1",
                    "rrf_k": 60,
                    "table_retrieval_cap": 3,
                    "table_context_cap": 2,
                }
            )
            expected_run_hash = api_config_sha256(
                build_api_run_config(
                    index_config_sha256=expected_composite_hash,
                    generator_model="gpt-5-nano",
                    retrieval_top_k=10,
                    context_top_k=5,
                    max_output_tokens=2000,
                    max_citations=3,
                    case_interval_seconds=0,
                    prompt_version="api-b1-page-table-v1",
                )
            )
            captured = _CapturedPipeline()
            with (
                mock.patch(
                    "midprojectrag.application.composition.OpenAIEmbeddingProvider",
                    return_value=mock.Mock(),
                ) as embedding_constructor,
                mock.patch(
                    "midprojectrag.application.composition.OpenAIGenerator",
                    return_value=mock.Mock(),
                ) as generator_constructor,
                mock.patch(
                    "midprojectrag.application.composition.RagPipeline",
                    return_value=captured,
                ) as pipeline_constructor,
            ):
                service = load_rag_application(
                    config_path,
                    data_dir,
                    embedding_client=object(),
                    generator_client=object(),
                    embedding_counter=_Counter(),
                    generation_counter=_Counter(),
                )
                self.assertFalse(embedding_constructor.called)
                self.assertFalse(generator_constructor.called)
                self.assertFalse(pipeline_constructor.called)
                service.ask(
                    question="표의 예산을 알려줘",
                    doc_ids=(DOC_ID,),
                    approve_external_corpus_egress=True,
                )

            pipeline_arguments = pipeline_constructor.call_args.kwargs
            dual_index = pipeline_arguments["index"]
            self.assertIsInstance(dual_index, DualLaneIndex)
            self.assertEqual(dual_index.rrf_k, 60)
            self.assertEqual(dual_index.table_retrieval_cap, 3)
            self.assertEqual(pipeline_arguments["table_context_cap"], 2)
            self.assertEqual(service.runtime.index_config_sha256, expected_composite_hash)
            self.assertEqual(service.runtime.run_config_sha256, expected_run_hash)
            self.assertEqual(len(service.list_documents()), 1)

    def test_version_1_2_rejects_table_documents_outside_page_catalog_before_provider(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path, data_dir, _page_hash, _table_hash = (
                _write_version_1_2_bundle(
                    Path(directory),
                    table_doc_id="doc_ffffffffffffffffffffffff",
                )
            )
            with (
                mock.patch(
                    "midprojectrag.application.composition.OpenAIEmbeddingProvider",
                    side_effect=AssertionError("provider reached before subset gate"),
                ),
                mock.patch(
                    "midprojectrag.application.composition.OpenAIGenerator",
                    side_effect=AssertionError("provider reached before subset gate"),
                ),
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "table_document_set_not_subset",
                ):
                    load_rag_application(config_path, data_dir)

    def test_version_1_2_rejects_layout_page_outside_manifest_before_provider(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path, data_dir, _page_hash, _table_hash = (
                _write_version_1_2_bundle(Path(directory))
            )
            layout_path = data_dir / "private" / "table-layout-v1.jsonl"
            layout_rows = read_jsonl(layout_path)
            layout_rows[0]["page_start"] = 2
            layout_rows[0]["page_end"] = 2
            layout_rows[0]["page_bboxes"][0]["page"] = 2
            write_jsonl(layout_path, layout_rows)
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["artifacts"]["table_layout"]["sha256"] = sha256_file(
                layout_path
            )
            config_path.write_text(json.dumps(config) + "\n", encoding="utf-8")
            with (
                mock.patch(
                    "midprojectrag.application.composition.OpenAIEmbeddingProvider",
                    side_effect=AssertionError("provider reached before layout gate"),
                ),
                mock.patch(
                    "midprojectrag.application.composition.OpenAIGenerator",
                    side_effect=AssertionError("provider reached before layout gate"),
                ),
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "table_layout_page_outside_manifest",
                ):
                    load_rag_application(config_path, data_dir)

    def test_version_1_2_rejects_table_index_manifest_drift_before_provider(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path, data_dir, _page_hash, _table_hash = (
                _write_version_1_2_bundle(
                    Path(directory),
                    table_corpus_manifest_sha256="f" * 64,
                )
            )
            with (
                mock.patch(
                    "midprojectrag.application.composition.OpenAIEmbeddingProvider",
                    side_effect=AssertionError("provider reached before identity gate"),
                ),
                mock.patch(
                    "midprojectrag.application.composition.OpenAIGenerator",
                    side_effect=AssertionError("provider reached before identity gate"),
                ),
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "table_index_expected_config_mismatch",
                ):
                    load_rag_application(config_path, data_dir)

    def test_version_1_2_rejects_declared_table_chunk_config_drift(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path, data_dir, _page_hash, _table_hash = (
                _write_version_1_2_bundle(Path(directory))
            )
            index_dir = (
                data_dir
                / "private"
                / "indexes"
                / "api"
                / "personal_experimental"
                / "small-2-table"
            )
            index_config_path = index_dir / "index-config.json"
            index_config = json.loads(
                index_config_path.read_text(encoding="utf-8")
            )
            index_config["chunk_config_sha256"] = "f" * 64
            write_json(index_config_path, index_config)
            metadata_path = index_dir / "metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["chunk_config_sha256"] = "f" * 64
            metadata["index_config_sha256"] = api_config_sha256(index_config)
            write_json(metadata_path, metadata)
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["artifacts"]["table_index"].update(
                {
                    "metadata_sha256": sha256_file(metadata_path),
                    "config_file_sha256": sha256_file(index_config_path),
                }
            )
            config_path.write_text(json.dumps(config) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError,
                "table_index_expected_config_mismatch",
            ):
                load_rag_application(config_path, data_dir)


if __name__ == "__main__":
    unittest.main()
