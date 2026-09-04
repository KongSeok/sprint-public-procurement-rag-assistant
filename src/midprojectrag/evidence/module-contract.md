# Evidence boundary — EH1.1~4

## Public API

`midprojectrag.evidence` exports `Locator`, `ProvenanceParent`, `Evidence`, `EvidenceStore`,
and `validate_evidence_store_snapshot`.
Each is a frozen, slotted dataclass with `to_dict()` and `from_dict()` methods.
Construction accepts list or tuple collection inputs and copies them to tuples.
Only validated immutable scalars and `Locator` instances are retained.

This module uses only Python's standard library. It performs no filesystem,
network, corpus, model, evaluator, parent lookup, or builder operations.

## Local validation

- `Locator.page` is absent or a positive, one-based integer; booleans are rejected.
- `bbox` is absent or four finite numbers `(x0, y0, x1, y1)`, normalized to floats.
  Inverted axes are rejected; zero-area boxes remain representable. Coordinate
  units and alignment with the source artifact are the builder's responsibility.
- `row_range` is absent or two zero-based inclusive integer endpoints with
  `0 <= start <= end`; booleans are rejected.
- Section path segments and optional flow/object identifiers are nonblank strings.
  Repeated section names are allowed. Raw identifiers and text are never trimmed
  or Unicode-normalized.
- Every parent and evidence requires a nonblank `doc_id`, supported `kind`, and
  nonempty, duplicate-free `source_block_ids`. Optional `source_chunk_ids` and
  `support_refs` are duplicate-free tuples of nonblank strings.
- A `hwp_section_flow` parent requires a `flow_id` and prohibits a physical page.
  Other parent kinds require a physical page. A rendered HWP page can also retain
  a flow identifier. The types never infer or fabricate page numbers.
- Parent text may be empty to describe a blank page. Figure evidence with a valid
  crop_ref may have empty text; do not invent captions for unread images. All
  other evidence text is nonblank.
- `char_range` is a nonempty, zero-based half-open parent text span. It preserves
  repeated-text occurrence identity. Store validation checks the actual slice.
- Evidence `parent_id` has the exact `pr_` plus 64 lowercase hex digit shape.
  Its existence and ownership are not checked by these types.
- `crop_ref` is absent or a literal local-relative POSIX file path. Absolute
  paths, backslashes, colons, URL query/fragment syntax, control characters,
  empty components, `.` components, and `..` traversal are rejected. No URI
  decoding or filesystem resolution occurs here.

Wrong value types raise `TypeError`; invalid values or altered identities raise
`ValueError`. These validations establish DTO shape, not provenance truth.

## Identity and JSON snapshots

`content_sha256` is the lowercase SHA-256 digest of the exact UTF-8 `text` bytes.
`parent_id` and `evidence_id` are respectively `pr_` and `ev_` followed by the
full SHA-256 digest of canonical JSON containing every constructor field,
including raw text, ordered source/support references, and the complete locator.
Canonical JSON uses sorted keys, compact separators, UTF-8 without ASCII
escaping, and disallows nonfinite values. Computed fields are not fed back into
their own identity. Source-reference order is significant and preserved.

`to_dict()` returns a fresh JSON-native snapshot with all fields, including null
or empty optional values, lists for tuples, and computed identities/hashes.
`from_dict()` requires exactly that field set at every level, JSON arrays for
collections, and recomputes and compares both the supplied ID and content hash.
Unknown or missing fields and forged snapshots are rejected. This is integrity
checking, not authentication: a party can create new content with a matching new
hash. `json.loads(json.dumps(value.to_dict()))` round-trips exactly.

## Store / builder / artifacts

`EvidenceStore` validates parent/doc/block/locator/text spans and acyclic support
references before freezing canonical maps. It rejects duplicate IDs, exposes
`get/parent/children/for_document/candidates/bridge`, and defaults to text-only
candidates. None/empty scope remains distinct. JSON graph identity is order-independent.
`validate_evidence_store_snapshot` additionally reconstructs the canonical graph and checks
the live parent/evidence keys, exact node types, child tuple membership/order, object identity,
and bundle hash before orchestration reuses a store. Index-only or stateful-iterable drift is
therefore rejected even when the serialized values and old bundle hash appear unchanged.

Public builder APIs are `SplitConfig`, `split_spans`, `children_from_parent`,
`build_store`, and `validate_chunking`. `build_store` uses the existing public
page chunk validator, accepts original source blocks, and checks non-whitespace
coverage, source config consistency and section binding. Original chunk IDs stay
in source_chunk_ids; character ranges distinguish repeated child occurrences.

Public persistence APIs in `artifacts.py` are `freeze_bundle/load_bundle` plus
private artifact helpers `private_path/file_sha/write_new_json`. Existing output
directories are rejected. Private-root/file symlink escapes, changed store/file
hashes, inconsistent child/config identities and count mismatches are rejected.
These helpers are shared with retrieval artifacts; no evaluator dependency.

Raw model types alone do not prove graph/source truth. Store validation does
not establish authenticity; trusted external manifest/receipt hashes remain the
caller boundary. Analytics parents, table correction and figure reader binding
are deferred to EH3, not disguised as completed page extraction.
