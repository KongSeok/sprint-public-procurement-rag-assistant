Timestamp: 2026-08-28
Context: HWP 94-document visual asset rollout

Issue
- Source filenames did not reliably identify bytes: two `.jpg` files contained valid PNG data, one PNG had
  trailing bytes after IEND, and WMF/GIF records were outside the served-image contract.
- Trusting the suffix or silently rewriting bytes would either reject valid evidence or lose the relationship
  between the original source and the canonical object.

Resolution
- Detect canonical type from bounded magic/structure validation and use the canonical suffix for served objects.
- Preserve raw source SHA-256, size, detected MIME/suffix and an explicit normalization ledger on every source
  record. PNG trailer stripping records both raw and canonical identity.
- Preserve valid WMF/GIF as `unsupported_source_asset` provenance only; do not publish a served object or infer
  a page-render link. Unknown or malformed data remains fatal.
- When a document contains an unsupported source asset, keep every image in that document unlinked so a partial
  ordinal alignment cannot create false evidence.

Prevention
- Media type is magic-led, never extension-led.
- Strict bundle reuse must revalidate the canonical object bytes and status-specific render/link invariants,
  not only stored hash and size fields.
- Any future conversion of unsupported formats needs a separately pinned converter and dual source/derived
  provenance; a renamed or transcoded file is not the original evidence.
