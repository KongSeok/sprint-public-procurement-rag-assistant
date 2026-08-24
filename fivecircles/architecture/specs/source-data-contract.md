# Source Data and Extraction Contract

## 1. Snapshot Layout

The runtime receives a private path through `MIDPROJECTRAG_DATA_DIR` or `--data-dir`.
The repository never assumes an absolute user path and never downloads corpus data as an import side effect.

Expected logical inputs:

- one metadata CSV equivalent to `data_list.csv`
- one raw document directory containing 96 HWP and 4 PDF files

## 2. File Matching

`normalized_filename` is produced by:

1. taking the basename only
2. removing one leading `Copy of `
3. applying Unicode NFC normalization
4. preserving the extension for exact matching

The join must report missing, extra, duplicate and collision entries. It must not use fuzzy matching silently.

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
- output relative path and `index_eligible`
- PII type counts without values
- creation timestamp

Manifest rows are never dropped because extraction failed.

## 4. Source Blocks

Extraction produces stable blocks before retrieval chunking:

- `block_id`, `doc_id`, sequence
- type: heading, paragraph, table or page_text
- section path
- page range or null
- bounding box or null
- text and content SHA-256
- extractor/version and source locator

Evaluation gold evidence references stable source blocks rather than experiment-specific chunks.

## 5. Parser Adapters

- HWP5 primary candidate: pinned `pyhwp`/`hwp5txt` in an isolated Python 3.11 environment.
- HWP page/table fallback: HWP5→HTML/ODT, then isolated headless office rendering to PDF, then `pdfplumber`.
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
