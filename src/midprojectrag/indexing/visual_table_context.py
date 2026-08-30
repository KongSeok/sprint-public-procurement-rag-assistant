from __future__ import annotations

import json
import re
import tempfile
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from midprojectrag.ingest.common import (
    canonical_json,
    read_jsonl,
    require_sha256,
    require_within,
    sha256_file,
    sha256_text,
    write_json,
    write_jsonl,
)
from midprojectrag.ingest.visual_bundle import _publish_staged
from midprojectrag.indexing.chunking import chunk_artifact_sha256, validate_chunk


VISUAL_TABLE_CHUNKER_ID = "table-md-visual-context-v2"
VISUAL_TABLE_SCHEMA_VERSION = "1.2"
DEFAULT_MAX_VISUAL_CHARS = 1_200
DEFAULT_MAX_TOTAL_CHARS = 4_800

_DOC_ID_RE = re.compile(r"^doc_[0-9a-f]{24}$")
_BLOCK_ID_RE = re.compile(r"^block_[0-9a-f]{24}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _positive_limit(value: Any, error_code: str, *, minimum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(error_code)
    return value


def _compact(value: Any, *, limit: int) -> str:
    if not isinstance(value, str):
        raise ValueError("visual_context_text_invalid")
    normalized = unicodedata.normalize("NFC", value)
    compact = " ".join(normalized.replace("\r\n", "\n").replace("\r", "\n").split())
    if not compact or len(compact) > limit:
        raise ValueError("visual_context_text_invalid")
    return compact


def _ordered_records(values: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError("visual_overlay_records_invalid")
    if any(not isinstance(value, Mapping) for value in values):
        raise ValueError("visual_overlay_record_invalid")
    return sorted(
        values,
        key=lambda value: (
            str(value.get("doc_id", "")),
            str(value.get("block_id", "")),
        ),
    )


def _overlay_index(
    values: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Mapping[str, Any]], str]:
    records = _ordered_records(values)
    indexed: dict[str, Mapping[str, Any]] = {}
    for record in records:
        doc_id = record.get("doc_id")
        block_id = record.get("block_id")
        structure_sha256 = record.get("structure_sha256")
        status = record.get("status")
        if (
            record.get("schema_version") != "1.0"
            or not isinstance(doc_id, str)
            or _DOC_ID_RE.fullmatch(doc_id) is None
            or not isinstance(block_id, str)
            or _BLOCK_ID_RE.fullmatch(block_id) is None
            or block_id in indexed
            or not isinstance(structure_sha256, str)
            or _SHA256_RE.fullmatch(structure_sha256) is None
            or status
            not in {
                "layout_missing",
                "layout_unresolved",
                "render_occurrence_unresolved",
                "verified_render",
            }
            or not isinstance(record.get("page_contexts"), list)
            or not isinstance(record.get("schedule_facts"), list)
        ):
            raise ValueError("visual_overlay_record_invalid")
        indexed[block_id] = record
    artifact_sha256 = sha256_text(
        "".join(canonical_json(record) + "\n" for record in records)
    )
    return indexed, artifact_sha256


def _page_in_chunk(page: int, chunk: Mapping[str, Any]) -> bool:
    page_start = chunk.get("page_start")
    page_end = chunk.get("page_end")
    if page_start is None and page_end is None:
        return False
    return (
        isinstance(page_start, int)
        and not isinstance(page_start, bool)
        and isinstance(page_end, int)
        and not isinstance(page_end, bool)
        and page_start <= page <= page_end
    )


def _visual_lines(
    chunk: Mapping[str, Any],
    overlay: Mapping[str, Any],
) -> list[str]:
    if overlay.get("status") != "verified_render":
        return []
    if chunk.get("table_structure_sha256") != chunk.get("source_structure_sha256"):
        # Nested tables do not have an independently verified render owner.
        return []

    context_candidates: list[tuple[int, int, str]] = []
    for raw in overlay["page_contexts"]:
        if not isinstance(raw, Mapping):
            raise ValueError("visual_overlay_page_context_invalid")
        page = raw.get("page")
        sequence = raw.get("sequence_in_page")
        preceding = raw.get("preceding_text")
        if (
            not isinstance(page, int)
            or isinstance(page, bool)
            or page < 1
            or not isinstance(sequence, int)
            or isinstance(sequence, bool)
            or sequence < 0
        ):
            raise ValueError("visual_overlay_page_context_invalid")
        if preceding is None or not _page_in_chunk(page, chunk):
            continue
        if not isinstance(preceding, Mapping):
            raise ValueError("visual_overlay_page_context_invalid")
        context_candidates.append(
            (page, sequence, _compact(preceding.get("text"), limit=500))
        )

    contexts: list[str] = []
    seen_contexts: set[str] = set()
    for _page, _sequence, text in sorted(context_candidates):
        if text not in seen_contexts:
            seen_contexts.add(text)
            contexts.append(text)

    row_start = chunk.get("row_start")
    row_end = chunk.get("row_end")
    if (
        not isinstance(row_start, int)
        or isinstance(row_start, bool)
        or not isinstance(row_end, int)
        or isinstance(row_end, bool)
    ):
        raise ValueError("visual_table_chunk_row_invalid")
    facts: list[tuple[int, str]] = []
    seen_facts: set[str] = set()
    for raw in overlay["schedule_facts"]:
        if not isinstance(raw, Mapping):
            raise ValueError("visual_overlay_schedule_fact_invalid")
        row = raw.get("row")
        if not isinstance(row, int) or isinstance(row, bool) or row < 0:
            raise ValueError("visual_overlay_schedule_fact_invalid")
        if not row_start <= row <= row_end:
            continue
        text = _compact(raw.get("text"), limit=500)
        evidence = raw.get("evidence_cells")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("visual_overlay_schedule_fact_invalid")
        if any(
            not isinstance(cell, Mapping)
            or not isinstance(cell.get("page"), int)
            or isinstance(cell.get("page"), bool)
            or not _page_in_chunk(cell["page"], chunk)
            for cell in evidence
        ):
            raise ValueError("visual_overlay_schedule_fact_page_mismatch")
        if text not in seen_facts:
            seen_facts.add(text)
            facts.append((row, text))

    return [
        *(f"[인접 문맥] {text}" for text in contexts),
        *(f"[시각 일정] {text}" for _row, text in sorted(facts)),
    ]


def enrich_table_chunks_with_visual_context(
    table_chunks: Sequence[Mapping[str, Any]],
    overlay_records: Sequence[Mapping[str, Any]],
    *,
    max_visual_chars: int = DEFAULT_MAX_VISUAL_CHARS,
    max_total_chars: int = DEFAULT_MAX_TOTAL_CHARS,
) -> list[dict[str, Any]]:
    """Create search-ready v2 table chunks without mutating v1 artifacts.

    The output keeps the table Markdown and locators unchanged. Only verified,
    row-scoped visual context is prepended, and every content/config/chunk hash
    is re-issued so v1 vectors cannot be mistaken for v2 vectors.
    """

    visual_limit = _positive_limit(
        max_visual_chars, "visual_context_limit_invalid", minimum=1
    )
    total_limit = _positive_limit(
        max_total_chars, "visual_total_limit_invalid", minimum=256
    )
    if visual_limit >= total_limit:
        raise ValueError("visual_context_limit_invalid")
    if isinstance(table_chunks, (str, bytes)) or not isinstance(
        table_chunks, Sequence
    ):
        raise ValueError("visual_table_chunks_invalid")
    overlays, overlay_artifact_sha256 = _overlay_index(overlay_records)
    config_sha256 = sha256_text(
        canonical_json(
            {
                "chunker_id": VISUAL_TABLE_CHUNKER_ID,
                "max_total_chars": total_limit,
                "max_visual_chars": visual_limit,
                "overlay_artifact_sha256": overlay_artifact_sha256,
                "policy": "exact-block-prior-context-row-scoped-schedule-v1",
                "retrieval_role": "structured_auxiliary",
            }
        )
    )

    enriched: list[dict[str, Any]] = []
    seen_chunk_ids: set[str] = set()
    for raw in table_chunks:
        if not isinstance(raw, Mapping):
            raise ValueError("visual_table_chunk_invalid")
        chunk = dict(raw)
        validate_chunk(chunk)
        if chunk.get("chunker_id") != "table-md-rowgroup-v1":
            raise ValueError("visual_table_source_chunk_invalid")
        block_id = chunk["source_block_ids"][0]
        overlay = overlays.get(block_id)
        if overlay is None:
            raise ValueError("visual_overlay_block_missing")
        if (
            overlay.get("doc_id") != chunk.get("doc_id")
            or overlay.get("structure_sha256")
            != chunk.get("source_structure_sha256")
        ):
            raise ValueError("visual_overlay_source_mismatch")

        lines = _visual_lines(chunk, overlay)
        visual_text = "\n".join(lines)
        if len(visual_text) > visual_limit:
            raise ValueError("visual_context_budget_exceeded")
        original_text = chunk["text"]
        text = f"{visual_text}\n\n{original_text}" if visual_text else original_text
        if len(text) > total_limit:
            raise ValueError("visual_total_budget_exceeded")
        content_sha256 = sha256_text(text)
        identity = {
            "block_id": block_id,
            "config_sha256": config_sha256,
            "content_sha256": content_sha256,
            "doc_id": chunk["doc_id"],
            "part_count": chunk["part_count"],
            "part_index": chunk["part_index"],
            "row_end": chunk["row_end"],
            "row_start": chunk["row_start"],
            "source_locator": chunk["source_locator"],
            "table_structure_sha256": chunk["table_structure_sha256"],
        }
        chunk_id = f"chunk_{sha256_text(canonical_json(identity))[:24]}"
        if chunk_id in seen_chunk_ids:
            raise ValueError("duplicate_chunk_id")
        seen_chunk_ids.add(chunk_id)
        chunk.update(
            {
                "schema_version": VISUAL_TABLE_SCHEMA_VERSION,
                "chunk_id": chunk_id,
                "text": text,
                "chunker_id": VISUAL_TABLE_CHUNKER_ID,
                "config_sha256": config_sha256,
                "content_sha256": content_sha256,
            }
        )
        validate_chunk(chunk)
        enriched.append(chunk)
    if not enriched:
        raise ValueError("no_visual_table_chunks")
    return enriched


def _private_regular_file(path: Path, root: Path, error_code: str) -> Path:
    resolved = require_within(path, root, "visual_corpus_path_outside_private_root")
    if not path.is_file() or path.is_symlink() or not resolved.is_file():
        raise ValueError(error_code)
    return resolved


def _private_output(path: Path, root: Path) -> Path:
    resolved = require_within(path, root, "visual_corpus_path_outside_private_root")
    current = root
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        raise ValueError("visual_corpus_path_outside_private_root") from None
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("visual_corpus_path_outside_private_root")
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise ValueError("visual_corpus_output_invalid")
    return resolved


def materialize_visual_table_corpus(
    *,
    source_chunks_path: Path,
    overlay_paths: Sequence[Path],
    corpus_metadata_path: Path,
    output_path: Path,
    metadata_output: Path,
    private_root: Path,
) -> dict[str, Any]:
    """Publish one corpus-wide visual table chunk contract.

    Overlay file partitioning and record order never affect the output.  All
    records are canonicalized once, so the resulting chunks share one config
    hash and can be loaded into a single exact index.
    """

    if not isinstance(private_root, Path) or not private_root.is_dir() or private_root.is_symlink():
        raise ValueError("visual_corpus_private_root_invalid")
    resolved_root = private_root.resolve(strict=True)
    source_path = _private_regular_file(
        source_chunks_path, resolved_root, "visual_corpus_source_chunks_invalid"
    )
    corpus_path = _private_regular_file(
        corpus_metadata_path, resolved_root, "visual_corpus_metadata_invalid"
    )
    if (
        isinstance(overlay_paths, (str, bytes))
        or not isinstance(overlay_paths, Sequence)
        or not overlay_paths
    ):
        raise ValueError("visual_corpus_overlay_invalid")
    resolved_overlays = [
        _private_regular_file(
            path, resolved_root, "visual_corpus_overlay_invalid"
        )
        for path in overlay_paths
    ]
    if len(resolved_overlays) != len(set(resolved_overlays)):
        raise ValueError("visual_corpus_overlay_invalid")
    resolved_output = _private_output(output_path, resolved_root)
    resolved_metadata = _private_output(metadata_output, resolved_root)
    if (
        resolved_output == resolved_metadata
        or resolved_output in {source_path, corpus_path, *resolved_overlays}
        or resolved_metadata in {source_path, corpus_path, *resolved_overlays}
    ):
        raise ValueError("visual_corpus_output_invalid")

    try:
        source_chunks = read_jsonl(source_path)
        if not source_chunks:
            raise ValueError("visual_corpus_source_chunks_invalid")
        if sha256_file(source_path) != chunk_artifact_sha256(source_chunks):
            raise ValueError("visual_corpus_source_chunks_invalid")
        overlay_records = [
            record
            for path in resolved_overlays
            for record in read_jsonl(path)
        ]
        if not overlay_records:
            raise ValueError("visual_corpus_overlay_invalid")
        overlay_records.sort(
            key=lambda value: (
                str(value.get("doc_id", "")),
                str(value.get("block_id", "")),
            )
        )
        overlay_artifact_sha256 = sha256_text(
            "".join(canonical_json(record) + "\n" for record in overlay_records)
        )
        try:
            corpus_metadata = json.loads(corpus_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise ValueError("visual_corpus_metadata_invalid") from None
        if not isinstance(corpus_metadata, Mapping):
            raise ValueError("visual_corpus_metadata_invalid")
        source_manifest_sha256 = require_sha256(
            corpus_metadata.get("source_manifest_sha256"),
            "visual_corpus_metadata_invalid",
        )
        enriched = enrich_table_chunks_with_visual_context(
            source_chunks, overlay_records
        )
    except ValueError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
        raise ValueError("visual_corpus_read_failed") from None

    configs = {chunk.get("config_sha256") for chunk in enriched}
    if (
        len(enriched) != len(source_chunks)
        or len(configs) != 1
        or any(chunk.get("chunker_id") != VISUAL_TABLE_CHUNKER_ID for chunk in enriched)
    ):
        raise ValueError("visual_corpus_chunk_contract_invalid")
    config_sha256 = require_sha256(
        next(iter(configs)), "visual_corpus_chunk_contract_invalid"
    )
    table_status_counts = Counter(str(record.get("status", "")) for record in overlay_records)
    if "" in table_status_counts:
        raise ValueError("visual_overlay_record_invalid")
    metadata = {
        "schema_version": VISUAL_TABLE_SCHEMA_VERSION,
        "method": "exact-block-prior-context-row-scoped-schedule-v1",
        "chunker_id": VISUAL_TABLE_CHUNKER_ID,
        "retrieval_role": "structured_auxiliary",
        "source_manifest_sha256": source_manifest_sha256,
        "source_chunk_artifact_sha256": sha256_file(source_path),
        "overlay_artifact_sha256": overlay_artifact_sha256,
        "corpus_metadata_sha256": sha256_file(corpus_path),
        "chunk_artifact_sha256": chunk_artifact_sha256(enriched),
        "config_sha256": config_sha256,
        "documents": len({str(chunk["doc_id"]) for chunk in enriched}),
        "source_chunks": len(source_chunks),
        "chunks": len(enriched),
        "overlay_records": len(overlay_records),
        "context_counts": {
            "chunks_with_prior_context": sum(
                "[인접 문맥]" in str(chunk["text"]) for chunk in enriched
            ),
            "chunks_with_schedule_context": sum(
                "[시각 일정]" in str(chunk["text"]) for chunk in enriched
            ),
        },
        "table_status_counts": dict(sorted(table_status_counts.items())),
    }
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    resolved_metadata.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(
            prefix=".visual-table-corpus-stage-", dir=resolved_root
        ) as stage_name:
            stage = Path(stage_name)
            staged_chunks = stage / "chunks.jsonl"
            staged_metadata = stage / "metadata.json"
            write_jsonl(staged_chunks, enriched)
            if sha256_file(staged_chunks) != metadata["chunk_artifact_sha256"]:
                raise ValueError("visual_corpus_publish_failed")
            write_json(staged_metadata, metadata)
            _publish_staged(
                (
                    (
                        staged_chunks,
                        resolved_output,
                        metadata["chunk_artifact_sha256"],
                    ),
                    (
                        staged_metadata,
                        resolved_metadata,
                        sha256_file(staged_metadata),
                    ),
                ),
                backup_root=stage,
            )
    except ValueError:
        raise
    except OSError:
        raise ValueError("visual_corpus_publish_failed") from None
    if (
        sha256_file(resolved_output) != metadata["chunk_artifact_sha256"]
        or json.loads(resolved_metadata.read_text(encoding="utf-8")) != metadata
    ):
        raise ValueError("visual_corpus_publish_failed")
    return metadata


__all__ = [
    "DEFAULT_MAX_TOTAL_CHARS",
    "DEFAULT_MAX_VISUAL_CHARS",
    "VISUAL_TABLE_CHUNKER_ID",
    "VISUAL_TABLE_SCHEMA_VERSION",
    "enrich_table_chunks_with_visual_context",
    "materialize_visual_table_corpus",
]
