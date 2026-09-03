"""Extractive child builder; original page chunks and IDs are never rewritten."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from hashlib import sha256
import json
import re
from typing import Iterable, Mapping

from midprojectrag.indexing.chunking import validate_chunk
from .model import Evidence, Locator, ProvenanceParent
from .store import EvidenceStore


@dataclass(frozen=True, slots=True)
class SplitConfig:
    chunker_id: str = "compat-newline-1600-v1"
    max_chars: int = 1600

    def __post_init__(self):
        if self.chunker_id not in {"compat-newline-1600-v1", "heading-paragraph-v1"}:
            raise ValueError("unsupported_child_chunker")
        if type(self.max_chars) is not int or self.max_chars < 64:
            raise ValueError("invalid_child_max_chars")

    def to_dict(self) -> dict:
        return {"chunker_id": self.chunker_id, "max_chars": self.max_chars, "version": "1.0"}

    @property
    def config_sha256(self) -> str:
        return sha256(json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def split_spans(text: str, config: SplitConfig = SplitConfig()) -> tuple[tuple[int, int], ...]:
    if not isinstance(text, str) or not text.strip():
        return ()
    if config.chunker_id == "heading-paragraph-v1":
        # Versioned generic structure rules, never gold/case-specific text.
        boundaries = {0, len(text)}
        boundaries.update(m.end() for m in re.finditer(r"\n[ \t]*\n", text))
        boundaries.update(m.start() for m in re.finditer(r"(?m)^(?:#{1,6}\s+|제\s*\d+\s*[장절]\s*|\d+[.)]\s+)", text))
        cuts = sorted(boundaries)
        result = []
        for begin, end in zip(cuts, cuts[1:]):
            while begin < end and text[begin].isspace():
                begin += 1
            while end > begin and text[end-1].isspace():
                end -= 1
            result.extend((begin+s, begin+e) for s, e in split_spans(
                text[begin:end], SplitConfig(max_chars=config.max_chars)))
        return tuple(result)
    maximum = config.max_chars
    if len(text) <= maximum:
        return ((0, len(text)),)
    result, cursor = [], 0
    while cursor < len(text):
        limit = min(cursor + maximum, len(text))
        cut = limit
        if limit < len(text):
            minimum = cursor + maximum // 2
            double = text.rfind("\n\n", minimum, limit)
            single = text.rfind("\n", minimum, limit)
            cut = double if double >= minimum else single
            if cut < minimum:
                cut = limit
        start, end = cursor, cut
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start < end:
            result.append((start, end))
        cursor = cut
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
    return tuple(result)


def children_from_parent(parent: ProvenanceParent, config: SplitConfig = SplitConfig(),
                         *, source_chunk_ids: tuple[str, ...] = ()) -> tuple[Evidence, ...]:
    return tuple(Evidence(parent.doc_id, "text", parent.text[start:end], parent.parent_id,
                          parent.source_block_ids, replace(parent.locator, char_range=(start, end)),
                          source_chunk_ids=source_chunk_ids) for start, end in split_spans(parent.text, config))


def build_store(chunks: Iterable[dict], config: SplitConfig = SplitConfig(), *,
                source_blocks: Iterable[dict] | None = None,
                parent_kinds: Mapping[str, str] | None = None) -> EvidenceStore:
    groups, seen = defaultdict(list), set()
    for row in chunks:
        validate_chunk(row)
        if row["chunker_id"] != "page-v1" or row["page_start"] != row["page_end"]:
            raise ValueError("child_builder_requires_single_page_chunks")
        if row["chunk_id"] in seen:
            raise ValueError("duplicate_source_chunk")
        seen.add(row["chunk_id"])
        groups[row["source_block_ids"][0]].append(row)
    blocks = None
    if source_blocks is not None:
        blocks = {}
        for block in source_blocks:
            key = block["block_id"]
            if key in blocks:
                raise ValueError("duplicate_source_block")
            blocks[key] = block
    parents, evidence = [], []
    for block_id, rows in sorted(groups.items()):
        rows.sort(key=lambda r: r["part_index"])
        first = rows[0]
        if ([r["part_index"] for r in rows] != list(range(first["part_count"])) or any(
            (r["doc_id"], r["page_start"], r["part_count"], r["section_path"], r["config_sha256"]) !=
            (first["doc_id"], first["page_start"], first["part_count"], first["section_path"], first["config_sha256"]) for r in rows
        )):
            raise ValueError("incomplete_or_mixed_source_parts")
        if blocks is None:
            if len(rows) != 1:
                raise ValueError("multipart_requires_original_source_block")
            text = first["text"]
        else:
            block = blocks.get(block_id)
            if block is None or (block.get("doc_id"), block.get("page_start"), block.get("page_end")) != (
                first["doc_id"], first["page_start"], first["page_end"]
            ):
                raise ValueError("source_block_binding_mismatch")
            text = block["text"]
            if not isinstance(text, str) or sha256(text.encode()).hexdigest() != block.get("content_sha256"):
                raise ValueError("source_block_content_hash_mismatch")
            if "section_path" in block and block["section_path"] != first["section_path"]:
                raise ValueError("source_block_section_mismatch")
        locator = Locator(page=first["page_start"], section_path=tuple(first["section_path"]))
        parent = ProvenanceParent(first["doc_id"], (parent_kinds or {}).get(first["doc_id"], "page_v1"),
                                  text, (block_id,), locator)
        parents.append(parent)
        cursor = 0
        for row in rows:
            offset = text.find(row["text"], cursor)
            if offset < 0:
                raise ValueError("source_chunk_text_binding_mismatch")
            if text[cursor:offset].strip():
                raise ValueError("source_text_coverage_gap")
            end = offset + len(row["text"])
            cursor = end
            evidence.append(Evidence(row["doc_id"], "page", row["text"], parent.parent_id, (block_id,),
                                     replace(locator, char_range=(offset, end)), source_chunk_ids=(row["chunk_id"],)))
            for start, stop in split_spans(row["text"], config):
                evidence.append(Evidence(row["doc_id"], "text", row["text"][start:stop], parent.parent_id,
                                         (block_id,), replace(locator, char_range=(offset+start, offset+stop)),
                                         source_chunk_ids=(row["chunk_id"],)))
        if text[cursor:].strip():
            raise ValueError("source_text_coverage_gap")
    return EvidenceStore(parents, evidence)


def validate_chunking(store: EvidenceStore, config: SplitConfig) -> None:
    """Prove declared config from legacy page evidence, not caller labels."""
    expected = set()
    for page in store.candidates(kinds=("page",)):
        if page.locator.char_range is None:
            raise ValueError("chunk_receipt_requires_page_span")
        offset = page.locator.char_range[0]
        for start, end in split_spans(page.text, config):
            child = Evidence(page.doc_id, "text", page.text[start:end], page.parent_id, page.source_block_ids,
                             replace(page.locator, char_range=(offset+start, offset+end)),
                             source_chunk_ids=page.source_chunk_ids)
            expected.add(child.evidence_id)
    if expected != {e.evidence_id for e in store.candidates()}:
        raise ValueError("chunk_config_does_not_match_store")
