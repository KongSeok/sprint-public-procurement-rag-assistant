from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from midprojectrag.answering import RagPipeline
from midprojectrag.catalog import MetadataCatalog, materialize_catalog
from midprojectrag.indexing.budget import BudgetLedger
from midprojectrag.indexing.chunking import chunk_artifact_sha256
from midprojectrag.indexing.embeddings import EmbeddingCache, TokenCounter
from midprojectrag.indexing.exact_index import ExactDenseIndex
from midprojectrag.indexing.fusion import DualLaneIndex
from midprojectrag.ingest.common import read_jsonl, require_within, sha256_file
from midprojectrag.ingest.table_layout import table_layout_resolution_reason
from midprojectrag.observability import create_observer
from midprojectrag.stacks.api import (
    OpenAIEmbeddingProvider,
    OpenAIGenerator,
    TiktokenCounter,
    api_config_sha256,
    build_api_run_config,
)

from .config import FileArtifact, IndexArtifact, RagRuntimeConfig, load_runtime_config
from .service import (
    RagApplicationService,
    RuntimeDescriptor,
    document_summaries_from_catalog,
)


_DOC_ID_PATTERN = re.compile(r"^doc_[0-9a-f]{24}$")
_BLOCK_ID_PATTERN = re.compile(r"^block_[0-9a-f]{24}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_TABLE_LAYOUT_LEGACY_FIELDS = {
    "schema_version",
    "doc_id",
    "block_id",
    "structure_sha256",
    "page_start",
    "page_end",
    "page_bboxes",
    "coordinate_space",
    "render_key",
    "wrapper_flattened",
    "anchor_present",
    "status",
}
_TABLE_LAYOUT_FIELDS = _TABLE_LAYOUT_LEGACY_FIELDS | {"resolution_reason"}


@dataclass(frozen=True)
class _VerifiedBundle:
    chunks: list[dict[str, Any]]
    retrieval_rows: list[dict[str, Any]]
    catalog_rows: list[dict[str, Any]]
    correction_set: dict[str, Any] | None
    index: ExactDenseIndex | DualLaneIndex
    index_metadata: dict[str, Any]
    index_config_hash: str
    query_cache_dir: Path
    tokenizer_cache_dir: Path
    budget_path: Path


@dataclass(frozen=True)
class _VerifiedIndexLane:
    chunks: list[dict[str, Any]]
    index: ExactDenseIndex
    metadata: dict[str, Any]
    config_hash: str


def _load_project_dotenv() -> None:
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:
        return
    dotenv_path = find_dotenv(usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path, override=False)
    if not os.getenv("OPENAI_API_KEY", "").strip() and os.getenv(
        "OPENAI_API_KEY_PRIVATE", ""
    ).strip():
        os.environ["OPENAI_API_KEY"] = os.environ["OPENAI_API_KEY_PRIVATE"]


def _json_object(path: Path, error_code: str) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as source:
            value = json.load(source)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(error_code) from error
    if not isinstance(value, dict):
        raise ValueError(error_code)
    return value


def _verified_file(path: Path, expected_sha256: str, error_code: str) -> Path:
    if not path.is_file() or sha256_file(path) != expected_sha256:
        raise ValueError(error_code)
    return path


def _resolve_file(data_dir: Path, relpath: str, error_code: str) -> Path:
    return require_within(data_dir / relpath, data_dir, error_code)


def _resolve_under(
    data_dir: Path,
    relpath: str,
    relative_root: str,
    error_code: str,
) -> Path:
    root = require_within(data_dir / relative_root, data_dir, error_code)
    return require_within(data_dir / relpath, root, error_code)


def _validate_catalog_overlay(
    retrieval_rows: list[dict[str, Any]], catalog_rows: list[dict[str, Any]]
) -> None:
    def identities(rows: list[dict[str, Any]]) -> dict[str, tuple[Any, Any]]:
        result: dict[str, tuple[Any, Any]] = {}
        for row in rows:
            doc_id = row.get("doc_id")
            if not isinstance(doc_id, str) or doc_id in result:
                raise ValueError("invalid_or_duplicate_manifest_doc_id")
            result[doc_id] = (row.get("sha256"), row.get("normalized_filename"))
        return result

    if identities(retrieval_rows) != identities(catalog_rows):
        raise ValueError("catalog_source_identity_mismatch")


def _manifest_page_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        doc_id = row.get("doc_id")
        page_count = row.get("page_count")
        if (
            not isinstance(doc_id, str)
            or _DOC_ID_PATTERN.fullmatch(doc_id) is None
            or doc_id in result
            or not isinstance(page_count, int)
            or isinstance(page_count, bool)
            or page_count < 1
        ):
            raise ValueError("invalid_manifest_page_count")
        result[doc_id] = page_count
    return result


def _validate_chunk_page_ranges(
    chunks: list[dict[str, Any]], page_counts: dict[str, int]
) -> None:
    for chunk in chunks:
        doc_id = chunk.get("doc_id")
        page_start = chunk.get("page_start")
        page_end = chunk.get("page_end")
        if doc_id not in page_counts:
            raise ValueError("chunk_document_not_in_manifest")
        if page_start is None and page_end is None:
            continue
        if (
            not isinstance(page_start, int)
            or isinstance(page_start, bool)
            or not isinstance(page_end, int)
            or isinstance(page_end, bool)
            or page_start < 1
            or page_end < page_start
            or page_end > page_counts[doc_id]
        ):
            raise ValueError("chunk_page_outside_manifest")


def _valid_layout_bbox(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {"x", "y", "w", "h"}:
        return False
    for field in ("x", "y", "w", "h"):
        item = value[field]
        if (
            not isinstance(item, (int, float))
            or isinstance(item, bool)
            or not math.isfinite(float(item))
            or (field in {"w", "h"} and item < 0)
        ):
            return False
    return True


def _validate_table_layout_binding(
    layout_rows: list[dict[str, Any]],
    table_chunks: list[dict[str, Any]],
    *,
    page_counts: dict[str, int],
) -> None:
    records: dict[str, dict[str, Any]] = {}
    for row in layout_rows:
        if not isinstance(row, dict) or (
            set(row) != _TABLE_LAYOUT_FIELDS
            and set(row) != _TABLE_LAYOUT_LEGACY_FIELDS
        ):
            raise ValueError("invalid_table_layout_artifact")
        doc_id = row.get("doc_id")
        block_id = row.get("block_id")
        structure_sha256 = row.get("structure_sha256")
        status = row.get("status")
        expected_resolution_reason = table_layout_resolution_reason(status)
        render_key = row.get("render_key")
        if (
            row.get("schema_version") != "1.0"
            or not isinstance(doc_id, str)
            or _DOC_ID_PATTERN.fullmatch(doc_id) is None
            or doc_id not in page_counts
            or not isinstance(block_id, str)
            or _BLOCK_ID_PATTERN.fullmatch(block_id) is None
            or block_id in records
            or not isinstance(structure_sha256, str)
            or _SHA256_PATTERN.fullmatch(structure_sha256) is None
            or status
            not in {
                "verified_render",
                "paragraph_anchor_candidate",
                "nonbody_unlinked",
            }
            or expected_resolution_reason is None
            or (
                "resolution_reason" in row
                and row.get("resolution_reason") != expected_resolution_reason
            )
            or row.get("coordinate_space") != "rhwp_css_px_96dpi"
            or not isinstance(row.get("wrapper_flattened"), bool)
            or not isinstance(row.get("anchor_present"), bool)
            or not isinstance(render_key, dict)
            or set(render_key) != {"section", "paragraph", "control"}
            or any(
                not isinstance(render_key[field], int)
                or isinstance(render_key[field], bool)
                or render_key[field] < 0
                for field in ("section", "paragraph", "control")
            )
        ):
            raise ValueError("invalid_table_layout_artifact")
        page_start = row.get("page_start")
        page_end = row.get("page_end")
        page_bboxes = row.get("page_bboxes")
        if not isinstance(page_bboxes, list):
            raise ValueError("invalid_table_layout_artifact")
        if status == "verified_render":
            if (
                not isinstance(page_start, int)
                or isinstance(page_start, bool)
                or page_start < 1
                or not isinstance(page_end, int)
                or isinstance(page_end, bool)
                or page_end < page_start
                or not page_bboxes
            ):
                raise ValueError("invalid_table_layout_artifact")
            bbox_pages: list[int] = []
            for item in page_bboxes:
                if (
                    not isinstance(item, dict)
                    or set(item) != {"page", "bbox", "page_bbox", "bbox_valid"}
                    or not isinstance(item.get("page"), int)
                    or isinstance(item.get("page"), bool)
                    or item["page"] < 1
                    or not _valid_layout_bbox(item.get("bbox"))
                    or not _valid_layout_bbox(item.get("page_bbox"))
                    or not isinstance(item.get("bbox_valid"), bool)
                ):
                    raise ValueError("invalid_table_layout_artifact")
                bbox_pages.append(item["page"])
            if min(bbox_pages) != page_start or max(bbox_pages) != page_end:
                raise ValueError("invalid_table_layout_artifact")
            if page_end > page_counts[doc_id] or any(
                page > page_counts[doc_id] for page in bbox_pages
            ):
                raise ValueError("table_layout_page_outside_manifest")
        elif page_start is not None or page_end is not None or page_bboxes:
            raise ValueError("invalid_table_layout_artifact")
        records[block_id] = row

    if not records:
        raise ValueError("empty_table_layout_artifact")
    indexed_block_ids: set[str] = set()
    for chunk in table_chunks:
        source_block_ids = chunk.get("source_block_ids")
        if not isinstance(source_block_ids, list) or len(source_block_ids) != 1:
            raise ValueError("invalid_table_layout_chunk_binding")
        record = records.get(source_block_ids[0])
        if record is None:
            raise ValueError("table_layout_chunk_block_missing")
        if (
            chunk.get("doc_id") != record["doc_id"]
            or chunk.get("source_structure_sha256")
            != record["structure_sha256"]
            or record["status"] == "nonbody_unlinked"
        ):
            raise ValueError("table_layout_chunk_source_mismatch")
        source_locator = chunk.get("source_locator")
        if not isinstance(source_locator, str) or not source_locator:
            raise ValueError("invalid_table_layout_chunk_binding")
        direct_flattened_child = (
            record["status"] == "verified_render"
            and record["wrapper_flattened"] is True
            and source_locator.count("/nested:") == 1
            and source_locator.endswith("/cell:0,0/nested:1")
        )
        expected_pages = (
            (None, None)
            if "/nested:" in source_locator and not direct_flattened_child
            else (record["page_start"], record["page_end"])
        )
        if (chunk.get("page_start"), chunk.get("page_end")) != expected_pages:
            raise ValueError("table_layout_chunk_page_mismatch")
        indexed_block_ids.add(source_block_ids[0])
    expected_block_ids = {
        block_id
        for block_id, record in records.items()
        if record["status"] != "nonbody_unlinked"
    }
    if indexed_block_ids != expected_block_ids:
        raise ValueError("table_layout_chunk_block_set_mismatch")


def _single_chunk_config_sha256(
    chunks: list[dict[str, Any]], *, error_prefix: str
) -> str:
    values: set[str] = set()
    for chunk in chunks:
        value = chunk.get("config_sha256")
        if (
            not isinstance(value, str)
            or _SHA256_PATTERN.fullmatch(value) is None
        ):
            raise ValueError(f"{error_prefix}index_expected_config_mismatch")
        values.add(value)
    if len(values) != 1:
        raise ValueError(f"{error_prefix}index_expected_config_mismatch")
    return next(iter(values))


def _verified_index_lane(
    config: RagRuntimeConfig,
    data_dir: Path,
    *,
    chunks_artifact: FileArtifact,
    index_artifact: IndexArtifact,
    error_prefix: str,
) -> _VerifiedIndexLane:
    chunks_path = _verified_file(
        _resolve_file(
            data_dir,
            chunks_artifact.relpath,
            f"{error_prefix}chunks_path_outside_data_dir",
        ),
        chunks_artifact.sha256,
        f"{error_prefix}chunks_file_hash_mismatch",
    )
    index_dir = _resolve_under(
        data_dir,
        index_artifact.relpath,
        "private/indexes/api",
        f"{error_prefix}api_index_path_outside_stack_root",
    )
    metadata_path = _verified_file(
        index_dir / "metadata.json",
        index_artifact.metadata_sha256,
        f"{error_prefix}index_metadata_hash_mismatch",
    )
    config_path = _verified_file(
        index_dir / "index-config.json",
        index_artifact.config_file_sha256,
        f"{error_prefix}index_config_file_hash_mismatch",
    )
    chunks = read_jsonl(chunks_path)
    index_metadata = _json_object(
        metadata_path,
        f"invalid_{error_prefix}index_metadata",
    )
    index_config = _json_object(
        config_path,
        f"invalid_{error_prefix}index_config",
    )
    index_config_hash = api_config_sha256(index_config)
    actual_chunk_hash = chunk_artifact_sha256(chunks)
    chunk_config_sha256 = _single_chunk_config_sha256(
        chunks, error_prefix=error_prefix
    )
    if (
        index_metadata.get("index_config_sha256") != index_config_hash
        or index_metadata.get("api_profile") != config.api_profile
        or index_config.get("api_profile") != config.api_profile
        or index_metadata.get("embedding_model") != config.embedding_model
        or index_config.get("embedding_model") != config.embedding_model
        or index_metadata.get("dimensions") != config.embedding_dimensions
        or index_config.get("embedding_dimensions") != config.embedding_dimensions
        or index_metadata.get("corpus_manifest_sha256")
        != config.retrieval_manifest.sha256
        or index_config.get("corpus_manifest_sha256")
        != config.retrieval_manifest.sha256
        or index_metadata.get("chunk_artifact_sha256") != actual_chunk_hash
        or index_config.get("chunk_artifact_sha256") != actual_chunk_hash
        or index_metadata.get("chunk_config_sha256") != chunk_config_sha256
        or index_config.get("chunk_config_sha256") != chunk_config_sha256
    ):
        raise ValueError(f"{error_prefix}index_expected_config_mismatch")
    index = ExactDenseIndex.load(
        index_dir,
        chunks,
        expected_embedding_model=config.embedding_model,
        expected_dimensions=config.embedding_dimensions,
        expected_api_profile=config.api_profile,
        expected_index_config_sha256=index_config_hash,
    )
    return _VerifiedIndexLane(
        chunks=chunks,
        index=index,
        metadata=index_metadata,
        config_hash=index_config_hash,
    )


def _dual_lane_config_sha256(
    config: RagRuntimeConfig,
    *,
    page_index_config_sha256: str,
    table_index_config_sha256: str,
) -> str:
    if (
        config.fusion is None
        or config.rrf_k is None
        or config.table_retrieval_cap is None
        or config.table_context_cap is None
        or config.table_layout is None
    ):
        raise ValueError("incomplete_dual_lane_runtime_config")
    return api_config_sha256(
        {
            "schema_version": "1.0",
            "architecture": "page-table-dual-lane",
            "page_index_config_sha256": page_index_config_sha256,
            "table_index_config_sha256": table_index_config_sha256,
            "table_layout_sha256": config.table_layout.sha256,
            "fusion": config.fusion,
            "rrf_k": config.rrf_k,
            "table_retrieval_cap": config.table_retrieval_cap,
            "table_context_cap": config.table_context_cap,
        }
    )


def _verified_bundle(
    config: RagRuntimeConfig, data_dir: Path
) -> _VerifiedBundle:
    retrieval_manifest_path = _verified_file(
        _resolve_file(
            data_dir,
            config.retrieval_manifest.relpath,
            "retrieval_manifest_path_outside_data_dir",
        ),
        config.retrieval_manifest.sha256,
        "retrieval_manifest_hash_mismatch",
    )
    catalog_path = _verified_file(
        _resolve_file(
            data_dir,
            config.catalog_manifest.relpath,
            "catalog_path_outside_data_dir",
        ),
        config.catalog_manifest.sha256,
        "catalog_manifest_hash_mismatch",
    )
    correction_path = None
    if config.correction_set is not None:
        correction_path = _verified_file(
            _resolve_file(
                data_dir,
                config.correction_set.relpath,
                "correction_set_path_outside_data_dir",
            ),
            config.correction_set.sha256,
            "correction_set_hash_mismatch",
        )
    query_cache_dir = _resolve_under(
        data_dir,
        config.query_cache_relpath,
        "private/caches/api",
        "api_cache_path_outside_stack_root",
    )
    tokenizer_cache_dir = _resolve_under(
        data_dir,
        config.tokenizer_cache_relpath,
        "private",
        "tokenizer_cache_path_outside_data_dir",
    )
    budget_path = _resolve_under(
        data_dir,
        config.budget_ledger_relpath,
        "private",
        "budget_path_outside_data_dir",
    )
    retrieval_rows = read_jsonl(retrieval_manifest_path)
    catalog_rows = read_jsonl(catalog_path)
    correction_set = (
        _json_object(correction_path, "correction_set_catalog_mismatch")
        if correction_path is not None
        else None
    )
    _validate_catalog_overlay(retrieval_rows, catalog_rows)
    page_counts = _manifest_page_counts(retrieval_rows)
    page_lane = _verified_index_lane(
        config,
        data_dir,
        chunks_artifact=config.chunks,
        index_artifact=config.index,
        error_prefix="",
    )
    _validate_chunk_page_ranges(page_lane.chunks, page_counts)
    index: ExactDenseIndex | DualLaneIndex = page_lane.index
    index_config_hash = page_lane.config_hash
    if config.schema_version == "1.2":
        if (
            config.table_chunks is None
            or config.table_layout is None
            or config.table_index is None
        ):
            raise ValueError("incomplete_dual_lane_runtime_config")
        table_lane = _verified_index_lane(
            config,
            data_dir,
            chunks_artifact=config.table_chunks,
            index_artifact=config.table_index,
            error_prefix="table_",
        )
        identity_fields = (
            "corpus_manifest_sha256",
            "embedding_model",
            "api_profile",
        )
        if any(
            page_lane.metadata.get(field) != table_lane.metadata.get(field)
            for field in identity_fields
        ) or page_lane.metadata.get("dimensions") != table_lane.metadata.get(
            "dimensions"
        ):
            raise ValueError("dual_lane_index_identity_mismatch")
        page_doc_ids = {chunk["doc_id"] for chunk in page_lane.chunks}
        table_doc_ids = {chunk["doc_id"] for chunk in table_lane.chunks}
        if not table_doc_ids.issubset(page_doc_ids):
            raise ValueError("table_document_set_not_subset")
        _validate_chunk_page_ranges(table_lane.chunks, page_counts)
        table_layout_path = _verified_file(
            _resolve_file(
                data_dir,
                config.table_layout.relpath,
                "table_layout_path_outside_data_dir",
            ),
            config.table_layout.sha256,
            "table_layout_file_hash_mismatch",
        )
        _validate_table_layout_binding(
            read_jsonl(table_layout_path),
            table_lane.chunks,
            page_counts=page_counts,
        )
        if config.fusion != "rrf-v1":
            raise ValueError("unsupported_dual_lane_fusion")
        if config.rrf_k is None or config.table_retrieval_cap is None:
            raise ValueError("incomplete_dual_lane_runtime_config")
        index = DualLaneIndex(
            page_lane.index,
            table_lane.index,
            rrf_k=config.rrf_k,
            table_retrieval_cap=config.table_retrieval_cap,
        )
        index_config_hash = _dual_lane_config_sha256(
            config,
            page_index_config_sha256=page_lane.config_hash,
            table_index_config_sha256=table_lane.config_hash,
        )
    return _VerifiedBundle(
        chunks=page_lane.chunks,
        retrieval_rows=retrieval_rows,
        catalog_rows=catalog_rows,
        correction_set=correction_set,
        index=index,
        index_metadata=page_lane.metadata,
        index_config_hash=index_config_hash,
        query_cache_dir=query_cache_dir,
        tokenizer_cache_dir=tokenizer_cache_dir,
        budget_path=budget_path,
    )


def load_rag_application(
    config_path: Path,
    data_dir: Path,
    *,
    embedding_client: Any | None = None,
    generator_client: Any | None = None,
    embedding_counter: TokenCounter | None = None,
    generation_counter: TokenCounter | None = None,
) -> RagApplicationService:
    config = load_runtime_config(config_path.resolve())
    if config.stack_id != "api":
        raise ValueError("unsupported_application_stack")
    if config.observability_backend != "disabled":
        raise ValueError("streamlit_observability_must_be_disabled")
    resolved_data_dir = data_dir.resolve()
    if not resolved_data_dir.is_dir():
        raise ValueError("runtime_data_dir_missing")
    bundle = _verified_bundle(config, resolved_data_dir)
    chunk_doc_ids = {chunk["doc_id"] for chunk in bundle.chunks}
    metadata_catalog: MetadataCatalog | None = None
    if bundle.correction_set is not None:
        metadata_catalog = materialize_catalog(
            bundle.catalog_rows,
            bundle.correction_set,
            bundle.retrieval_rows,
            expected_snapshot_id=config.catalog_manifest.snapshot_id,
        )
        if {
            card.doc_id for card in metadata_catalog.list_documents()
        } != chunk_doc_ids:
            raise ValueError("catalog_document_set_mismatch")
        documents = None
        document_count = len(metadata_catalog.list_documents())
    else:
        documents = document_summaries_from_catalog(
            bundle.catalog_rows,
            expected_doc_ids=chunk_doc_ids,
            expected_snapshot_id=config.catalog_manifest.snapshot_id,
        )
        document_count = len(documents)
    run_config = build_api_run_config(
        index_config_sha256=bundle.index_config_hash,
        generator_model=config.generator_model,
        retrieval_top_k=config.retrieval_top_k,
        context_top_k=config.context_top_k,
        max_output_tokens=config.max_output_tokens,
        max_citations=config.max_citations,
        case_interval_seconds=0,
        prompt_version=(
            "api-b1-page-table-v1"
            if config.schema_version == "1.2"
            else "api-b0-page-v1"
        ),
    )
    run_config_sha256 = api_config_sha256(run_config)

    def pipeline_factory() -> RagPipeline:
        _load_project_dotenv()
        if (
            (embedding_client is None or generator_client is None)
            and not os.getenv("OPENAI_API_KEY", "").strip()
        ):
            raise RuntimeError("openai_api_key_missing")
        embedding_provider = OpenAIEmbeddingProvider(
            client=embedding_client,
            model=config.embedding_model,
            dimensions=config.embedding_dimensions,
            api_profile=config.api_profile,
        )
        generator = OpenAIGenerator(
            client=generator_client,
            model=config.generator_model,
            max_output_tokens=config.max_output_tokens,
            max_citations=config.max_citations,
        )
        return RagPipeline(
            index=bundle.index,
            embedding_provider=embedding_provider,
            embedding_counter=embedding_counter
            or TiktokenCounter(
                config.embedding_model, cache_dir=bundle.tokenizer_cache_dir
            ),
            query_cache=EmbeddingCache(bundle.query_cache_dir),
            generator=generator,
            generation_counter=generation_counter
            or TiktokenCounter(
                config.generator_model, cache_dir=bundle.tokenizer_cache_dir
            ),
            budget=BudgetLedger(
                bundle.budget_path, limit_usd=config.budget_limit_usd
            ),
            corpus_manifest_sha256=bundle.index_metadata["corpus_manifest_sha256"],
            stack_id="api",
            observer=create_observer("disabled"),
            retrieval_top_k=config.retrieval_top_k,
            context_top_k=config.context_top_k,
            table_context_cap=config.table_context_cap,
        )
    runtime = RuntimeDescriptor(
        runtime_id=config.runtime_id,
        config_sha256=config.config_sha256,
        index_config_sha256=bundle.index_config_hash,
        run_config_sha256=run_config_sha256,
        api_profile=config.api_profile,
        embedding_model=config.embedding_model,
        embedding_dimensions=config.embedding_dimensions,
        generator_model=config.generator_model,
        retrieval_top_k=config.retrieval_top_k,
        context_top_k=config.context_top_k,
        max_citations=config.max_citations,
        retrieval_manifest_sha256=config.retrieval_manifest.sha256,
        catalog_manifest_sha256=config.catalog_manifest.sha256,
        catalog_snapshot_id=config.catalog_manifest.snapshot_id,
        document_count=document_count,
        observability_backend=config.observability_backend,
    )
    return RagApplicationService(
        pipeline_factory=pipeline_factory,
        documents=documents,
        metadata_catalog=metadata_catalog,
        runtime=runtime,
    )
