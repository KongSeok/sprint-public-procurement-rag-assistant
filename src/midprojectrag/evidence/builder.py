"""One-way adapters from validated legacy chunks into the evidence graph.

Auxiliary inputs must use an explicit JSON envelope, not a guessed page join::

    {"chunk": legacy_chunk, "parent_source_block_id": page_block_id,
     "source_block_ids": [actual_figure_block_id], "crop_ref": optional_ref}

``source_block_ids`` is mandatory for visual chunks (which otherwise only carry
derived OCR IDs); a table already carries its canonical source block. A crop_ref
is retained as provenance only: this module never opens files or fetches URLs.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
import hashlib
import re
from typing import Any

from .model import Evidence, EvidenceStore


_BLOCK = re.compile(r"block_[0-9a-f]{24}\Z")
_LINK_FIELDS = frozenset({"chunk", "parent_source_block_id", "source_block_ids", "crop_ref"})


def _source_ids(value: Any) -> tuple[str, ...]:
    if (not isinstance(value, list) or not value
            or any(not isinstance(item, str) or not _BLOCK.fullmatch(item) for item in value)
            or len(value) != len(set(value))):
        raise ValueError("invalid_auxiliary_source_mapping")
    return tuple(value)


def _pieces(text: str, max_chars: int) -> tuple[str, ...]:
    # Do not normalize/strip content: every emitted piece is an exact substring.
    # Prefer paragraph/newline cuts, while long paragraphs remain bounded.
    pieces = []
    cursor = 0
    while cursor < len(text):
        end = min(cursor + max_chars, len(text))
        if end < len(text):
            cut = text.rfind("\n\n", cursor + 1, end)
            if cut < 0:
                cut = text.rfind("\n", cursor + 1, end)
            if cut >= cursor + 1:
                end = cut + 1
        piece = text[cursor:end]
        if piece.strip():
            pieces.append(piece)
        cursor = end
    return tuple(pieces)


def build_from_chunks(chunks: Iterable[Mapping[str, Any]], *, max_chars: int = 1600) -> EvidenceStore:
    """Build deterministic page parents, text children and explicit object links.

    A page split into legacy parts is represented by those texts in part order,
    joined with ``\n\n``; discarded legacy whitespace cannot be reconstructed.
    No document text or page number is fabricated. Incomplete split sets and
    ambiguous page/source mappings fail. Identical child text from the same
    source is deduplicated; the complete page representation remains available.
    """
    if type(max_chars) is not int or max_chars < 1:
        raise ValueError("invalid_evidence_max_chars")
    if isinstance(chunks, (str, bytes, Mapping)):
        raise ValueError("invalid_evidence_chunks")
    try:
        items = tuple(chunks)
    except TypeError:
        raise ValueError("invalid_evidence_chunks") from None
    if not items:
        raise ValueError("no_primary_evidence_chunks")
    # Existing validators are imported inside the ingestion adapter. The domain
    # model/store have no dependency on vector packages or legacy indexing.
    from midprojectrag.indexing.chunking import validate_chunk

    primary: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    auxiliaries: list[tuple[dict[str, Any], Mapping[str, Any]]] = []
    seen_ids: set[str] = set()
    for item in items:
        if not isinstance(item, Mapping):
            raise ValueError("invalid_evidence_chunk")
        is_envelope = "chunk" in item
        if is_envelope:
            if (not set(item) <= _LINK_FIELDS
                    or not {"chunk", "parent_source_block_id"} <= set(item)
                    or not isinstance(item["chunk"], dict)):
                raise ValueError("invalid_auxiliary_mapping_shape")
            chunk = item["chunk"]
            parent_source = item["parent_source_block_id"]
            if not isinstance(parent_source, str) or not _BLOCK.fullmatch(parent_source):
                raise ValueError("invalid_auxiliary_parent_source")
            if "crop_ref" in item and item["crop_ref"] is not None and (
                not isinstance(item["crop_ref"], str) or not item["crop_ref"].strip()
            ):
                raise ValueError("invalid_auxiliary_crop_ref")
        else:
            chunk = dict(item)
        role = chunk.get("retrieval_role")
        if role == "visual_auxiliary":
            # This optional validator pulls in numpy only for visual ingestion.
            from midprojectrag.indexing.visual_fusion import validate_visual_chunk
            # Guard the legacy validator's nested set comparisons from hostile
            # unhashable JSON before calling it.
            evidence_ids = chunk.get("evidence_ids")
            if not isinstance(evidence_ids, list) or any(not isinstance(x, str) for x in evidence_ids):
                raise ValueError("invalid_visual_source_refs")
            support = chunk.get("answer_support")
            if support is not None and (
                not isinstance(support, dict)
                or not isinstance(support.get("support_refs"), list)
                or any(not isinstance(x, str) for x in support["support_refs"])
            ):
                raise ValueError("invalid_visual_answer_support")
            try:
                validate_visual_chunk(chunk)
            except (TypeError, KeyError, OverflowError):
                raise ValueError("invalid_visual_chunk") from None
            if chunk["evidence_type"] == "caption" and (
                not isinstance(support, dict) or support.get("status") != "supported"
            ):
                raise ValueError("descriptive_caption_not_answer_evidence")
        else:
            try:
                validate_chunk(chunk)
            except (TypeError, KeyError):
                raise ValueError("invalid_legacy_chunk") from None
        if chunk["chunk_id"] in seen_ids:
            raise ValueError("duplicate_input_chunk_id")
        seen_ids.add(chunk["chunk_id"])
        if role == "primary":
            if is_envelope:
                raise ValueError("unexpected_primary_mapping")
            if chunk["page_start"] != chunk["page_end"]:
                raise ValueError("primary_chunk_single_page_required")
            primary[(chunk["doc_id"], chunk["page_start"], chunk["source_block_ids"][0])].append(chunk)
        else:
            if not is_envelope:
                raise ValueError("auxiliary_parent_mapping_required")
            auxiliaries.append((chunk, item))
    if not primary:
        raise ValueError("no_primary_evidence_chunks")
    records: dict[str, Evidence] = {}
    parents: dict[tuple[str, int, str], Evidence] = {}
    pages: set[tuple[str, int]] = set()
    for key, parts in sorted(primary.items()):
        doc_id, page, source_id = key
        if (doc_id, page) in pages:
            raise ValueError("ambiguous_primary_page_source")
        pages.add((doc_id, page))
        parts.sort(key=lambda part: part["part_index"])
        count = parts[0]["part_count"]
        if (len(parts) != count or [part["part_index"] for part in parts] != list(range(count))
                or any(part["part_count"] != count for part in parts)
                or any(part["config_sha256"] != parts[0]["config_sha256"] for part in parts)
                or any(part["section_path"] != parts[0]["section_path"] for part in parts)):
            raise ValueError("incomplete_or_inconsistent_page_parts")
        parent = Evidence.create(
            doc_id=doc_id, page=page, kind="page", text="\n\n".join(part["text"] for part in parts),
            source_block_ids=(source_id,), section_path=tuple(parts[0]["section_path"]),
            source_chunk_ids=tuple(part["chunk_id"] for part in parts),
        )
        records[parent.evidence_id] = parent
        parents[key] = parent
        for part in parts:
            for piece in _pieces(part["text"], max_chars):
                child = Evidence.create(
                    doc_id=doc_id, page=page, kind="text", text=piece,
                    source_block_ids=(source_id,), parent_id=parent.evidence_id,
                    section_path=tuple(part["section_path"]),
                    source_chunk_ids=(part["chunk_id"],),
                )
                records[child.evidence_id] = child
    for chunk, mapping in auxiliaries:
        visual = chunk["retrieval_role"] == "visual_auxiliary"
        page = chunk.get("page") if visual else chunk["page_start"]
        if type(page) is not int or page < 1 or (not visual and page != chunk["page_end"]):
            raise ValueError("auxiliary_single_page_required")
        parent = parents.get((chunk["doc_id"], page, mapping["parent_source_block_id"]))
        if parent is None:
            raise ValueError("auxiliary_parent_mapping_not_found")
        if visual:
            source_ids = _source_ids(mapping.get("source_block_ids"))
            box = chunk["bbox"]
            bbox = (box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"])
            object_id = chunk["occurrence_id"]
            # Keep generated caption claims distinguishable from OCR/layout in
            # source-bound text; descriptive-only captions are rejected above.
            text = chunk["text"]
            section_path: tuple[str, ...] = ()
            evidence_type = chunk["evidence_type"]
            # Retain original OCR/caption references and accepted caption support
            # lineage. Crop hash binds identity even if a crop path is reused.
            # Unsupported nested objects fail the source schema above; they are
            # not laundered into apparently valid hashed support references.
            support_refs = tuple(sorted({
                *chunk["evidence_ids"], *(chunk.get("answer_support") or {}).get("support_refs", []),
                "crop-sha256:" + chunk["crop_sha256"],
            }))
            row_range = None
        else:
            source_ids = _source_ids(chunk["source_block_ids"])
            if "source_block_ids" in mapping and _source_ids(mapping["source_block_ids"]) != source_ids:
                raise ValueError("auxiliary_source_mapping_mismatch")
            bbox = None  # A logical table locator is not proof of a pixel box.
            object_key = f'{chunk["doc_id"]}:{source_ids[0]}:{chunk["source_locator"]}:{chunk["table_structure_sha256"]}'
            object_id = "table_" + hashlib.sha256(object_key.encode("utf-8")).hexdigest()[:24]
            text = chunk["text"]
            section_path = tuple(chunk["section_path"])
            evidence_type = None
            support_refs = ()
            row_range = (chunk["row_start"], chunk["row_end"])
        record = Evidence.create(
            doc_id=chunk["doc_id"], page=page, kind="figure" if visual else "table",
            text=text, source_block_ids=source_ids, parent_id=parent.evidence_id,
            object_id=object_id, bbox=bbox,
            crop_ref=mapping.get("crop_ref") or ("sha256:" + chunk["crop_sha256"] if visual else None),
            section_path=section_path, source_chunk_ids=(chunk["chunk_id"],),
            evidence_type=evidence_type, support_refs=support_refs, row_range=row_range,
        )
        records[record.evidence_id] = record
    return EvidenceStore(records.values())
