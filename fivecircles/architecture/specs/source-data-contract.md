# Source Data and Extraction Contract

## 1. Snapshot Layout

The runtime receives a private path through `MIDPROJECTRAG_DATA_DIR` or `--data-dir`.
The repository never assumes an absolute user path and never downloads corpus data as an import side effect.
Inputs and generated artifacts must resolve beneath that data root. Path traversal and
symlinks escaping it are rejected before any external file is read or written.

Expected logical inputs:

- one metadata CSV equivalent to `data_list.csv`
- one raw document directory containing 96 HWP and 4 PDF files

## 2. File Matching

`normalized_filename` is produced by:

1. trimming surrounding whitespace without discarding any directory component
2. removing one leading `Copy of `
3. applying Unicode NFC normalization
4. preserving the extension for exact matching

The join must report missing, extra, duplicate and collision entries. It must not use fuzzy matching silently.
CSV values containing a directory component therefore do not silently match a raw file
that merely shares the same basename.

## 3. Private Manifest

One JSON object per source document with at least:

- schema and snapshot IDs
- pseudonymous `doc_id`
- source/normalized file names and relative path
- extension, detected MIME, size and SHA-256
- CSV row number and normalized metadata
- extractor name/version and input hash
- status: `pending | ok | partial | failed`
- error code, warning codes, page/block/character counts
- total, primary-retrieval and structured-auxiliary character counts
- output relative path and `index_eligible`
- primary retrieval lane의 PII type counts without values
- creation timestamp

Manifest rows are never dropped because extraction failed.
The extractor recomputes each source SHA-256 before parsing and marks hash drift as a
failure. CLI stdout contains aggregate counts and error codes only; private paths,
filenames, text and matched PII values remain in ignored artifacts.

## 4. Source Blocks

Extraction produces stable blocks before retrieval chunking:

- `block_id`, `doc_id`, sequence
- type: heading, paragraph, table or page_text
- section path
- page range or null
- bounding box or null
- text and content SHA-256
- extractor/version, source locator and `retrieval_role`
- structured table blocks also include canonical `table_structure` and `structure_sha256`; their
  block IDs commit to both searchable text and cell/span/header structure

Evaluation gold evidence references stable source blocks rather than experiment-specific chunks.

For `rhwp` extraction:

- `export-text --json` page index is zero-based at the tool boundary and is converted to the
  one-based `page_start`, `page_end` and `page:<number>` locator used by this project.
- page text becomes `page_text` blocks in page order.
- `export-tables --json` becomes `table` blocks after page blocks. Caption, cell row/column,
  row/column span, header flag, kind-dependent container path and recursively nested tables remain
  structured metadata rather than being inferred again from flattened text.
- table locators use one-based `section:<n>/paragraph:<n>/table:<n>` components. Page and bbox
  remain null until the separately emitted render tree is joined with a measured success rate.
- page-text and structured-table blocks overlap in source wording but do not yet share a page/bbox
  locator. Page text is therefore `retrieval_role=primary`; table blocks are
  `retrieval_role=structured_auxiliary`. The naive baseline embeds primary blocks only. A later
  structure-search experiment may use the auxiliary lane separately, but must not naively index
  both representations into one ranking pool.

## 5. Parser Adapters

- HWP/HWPX primary: checksum-verified `rhwp v0.8.4` Release binary at an explicit absolute path.
  Production records the executable SHA-256 in extractor identity/input hash and rejects PATH,
  version or checksum drift. Use
  `export-text --json` and `export-tables --json` through bounded subprocesses and accept only
  the documented `schemaVersion: "1.0"` envelope. Page extraction rejects truncation, nonzero
  omitted count or incomplete page indices. Table extraction requires exact `cellCount`, valid
  spans and non-overlapping anchors.
- HWP5 fallback: `hwp5txt`, then the isolated `pyhwp` binary-model reader. A successful fallback
  remains `partial` because page/table provenance is unavailable.
- HWP visual/layout QA: use `export-render-tree` and `export-svg` only for selected pages. Treat
  Hancom-rendered PDF as the oracle when page or pixel fidelity matters.
- HWP→PDF→layout parsing: special-document fallback only, never the default corpus conversion.
- PDF: `pypdf` for page text plus `pdfplumber` for tables/bounding boxes.
- CSV text: `preview_only=true`, `index_eligible=false`.
- DRM/password/corrupt/scanned inputs: explicit failed or pending-OCR status, never silent fallback to the CSV preview.

## 6. Validation Gates

- CSV rows=100, raw files=100, HWP=96, PDF=4
- normalized matches=100, collisions/missing/extra=0
- magic header agrees with the claimed format
- manifest rows=100 and status totals=100
- failed=0 for production indexing unless an explicit exception is recorded
- suspiciously short output and poor preview overlap produce warnings
- manual QA covers five stratified HWP samples and all four PDFs
- `rhwp` corpus gate requires HWP text success=96/96, table success=96/96 and manifest failures=0
- production verification uses `verify --require-primary-hwp`; the gate implies block verification
  and rejects non-`ok`, non-`rhwp`, non-explicit, version-drifted or checksum-drifted HWP/HWPX rows
- source-block validation reconciles total characters with separate primary and auxiliary counts
- table↔render-tree bbox join failures and Hancom page drift are recorded explicitly rather than guessed
