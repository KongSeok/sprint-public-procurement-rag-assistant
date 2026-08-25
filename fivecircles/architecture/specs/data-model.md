# RAG Data Model

This document defines logical entities. Storage may remain JSONL/files for the project baseline.

## CorpusSnapshot

An immutable view of the 100-document corpus used by one experiment.

Fields: `snapshot_id`, `manifest_sha256`, `document_count`, `created_at`, `schema_version`.

## Document

A source RFP plus normalized metadata and extraction state.

Identity rule: `doc_id` is deterministic and pseudonymous; public outputs do not expose source names or Drive IDs.

Fields: `doc_id`, normalized metadata, source hash, MIME, parser/version, extraction status, warning codes, block counts.

## SourceBlock

A stable, citation-addressable structural unit created before experiment-specific chunking.

Fields: `block_id`, `doc_id`, `sequence`, `block_type`, `retrieval_role`, `section_path`, page range, bbox, text, content hash, source locator. Structured table blocks additionally carry caption, normalized cells, spans, header flags, nested container paths/tables and a structure hash committed into the block ID.

Invariant: the same corpus snapshot, extraction identity and retrieval role must produce the same block IDs. The baseline indexes `primary` blocks only; `structured_auxiliary` blocks remain a separate experimental lane.

## Chunk

A retrieval unit derived from one or more source blocks under a named chunking configuration.

Fields: `chunk_id`, `doc_id`, `source_block_ids`, text, token/character counts, chunking config hash, metadata.

Invariant: every chunk maps back to at least one source block; chunks are restricted artifacts.

## Citation

A response reference to retrieved evidence.

Fields: `doc_id`, `chunk_id`, `source_block_ids`, section/page locator.

Invariant: an answered factual response has at least one valid citation; citations resolve against the active snapshot.

## RagRequest / RagResponse

Provider-independent public contracts defined by JSON Schema under `contracts/`.
Conversation history is explicit in a request for reproducibility.

## EvaluationCase

A question, fixed context, document scope and stable gold evidence with a `dev` or `heldout` split.
All cases sharing a `group_id` belong to one split.

## RunRecord

Private evidence for one case execution: stack/model/config/corpus/eval hashes, retrieval ranks,
response, latency, token/cost or GPU resource measurements and errors.

Invariant: raw source text, prompts, completions and PII are not stored in public run records.
