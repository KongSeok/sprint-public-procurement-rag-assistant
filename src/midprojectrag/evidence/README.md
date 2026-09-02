# Evidence module contract

Owner: source identity, immutable evidence graph and explicitly linked object bridges.
Consumers use `Evidence`, `EvidenceStore`, and `build_from_chunks` from this package.
No gold, provider, file reads, model downloads or semantic judging occur here.

`Evidence.create` derives the `ev_` identity from the exact UTF-8 text hash,
document/page, source block/chunk IDs, parent, object, bbox, crop reference, section
path, evidence type, support references and row range.
`Evidence.from_dict` and `EvidenceStore.from_dict` revalidate every hash and
link. `store.artifact_sha256` is independent of insertion order. Exported nested
lists/dictionaries are detached copies, not mutable views of stored records.

BBox is `(left, top, right, bottom)` in the source coordinate system. Table and
figure children require `object_id`; roots are pages. Bridge returns only
explicitly linked table/figure descendants. A crop reference is provenance, not
proof that a text-only generator has seen the pixels.

## Legacy builder input

Raw page-v1 chunks pass the existing public chunk validator. Inputs must include
every split part, agree on config/source/section, and identify one actual page.
Page parents join ordered legacy part text with `\n\n`. This separator is a
representation delimiter: whitespace discarded by the old chunker cannot be
recovered. Paragraph children retain exact input substrings and source block
IDs. Every parent records all source chunk IDs in part order; each paragraph
records the exact source chunk it came from. Equal child text in the same source
chunk is deduplicated, but equal text in different source chunks stays distinct.

Table and visual chunks require this envelope:

```json
{
  "chunk": {"...": "complete, valid legacy auxiliary chunk"},
  "parent_source_block_id": "block_<actual page block identity>",
  "source_block_ids": ["block_<actual object source identity>"],
  "crop_ref": "optional private relative reference"
}
```

`source_block_ids` is required for visual chunks, which otherwise carry derived
OCR/caption IDs, and optional for table chunks; supplied table IDs must exactly
match the validated canonical chunk. The parent lookup uses all of document,
page and explicit parent source block. A coincident page number never creates a
bridge. Multi-page or page-less auxiliary chunks fail closed. Tables retain
their row-group text and logical object identity, without inventing a bbox.
Visual xywh is converted to LTRB without geometry inference. OCR/layout chunks
retain existing source text. Without an explicit crop reference, the visual crop
SHA-256 is retained as a `sha256:<digest>` content reference, never a guessed path.
Caption chunks are accepted only with the existing
validated `answer_support.status=supported` and nonempty support references;
descriptive-only or unreviewed captions are rejected until the domain carries
separate non-answerable descriptive evidence.

The caller must supply provenance-verified chunks/envelopes. Structural validity
does not prove that an upstream source claim is true; this adapter does not read
original files or perform semantic fidelity verification.

## Additive provenance fields

- `source_chunk_ids: tuple[str, ...] = ()`: exact validated original chunk IDs;
  part order on page parents and one source chunk on a paragraph/object child.
- `evidence_type: str | None = None`: exact visual source type (`ocr`, `layout`,
  or `caption`); not inferred from text. Other nonempty explicit types are allowed
  for later adapters; the three visual types require figure kind.
- `support_refs: tuple[str, ...] = ()`: literal upstream OCR/caption evidence IDs,
  supported caption references, and `crop-sha256:<validated digest>` for pixels.
  The builder uses sorted unique strings. This is lineage, not an answer-support
  verdict; the runtime verifier must still verify the requested claim. Existing
  source schemas allow only strings, so nested objects fail instead of being
  silently converted to hash references.
- `row_range: tuple[int, int] | None = None`: exact table row-start/row-end pair,
  inclusive and zero-based, copied from the validated table chunk. It is absent
  for all other kinds. Identical text on different source rows therefore remains
  distinct evidence while sharing the canonical table object identity.

These fields participate in identity and serialization. No already-published
evidence-v1 artifact is migrated in place; this implementation is still opt-in
and has not frozen or promoted an evidence artifact.
