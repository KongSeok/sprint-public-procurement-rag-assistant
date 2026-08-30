# PDF visual v2 common identity contract mismatch

- Date: 2026-08-30
- Status: RESOLVED
- Impact: early PDF v2 records could not be safely joined with the shared visual evidence lane because
  occurrence IDs, source-object IDs, and crop provenance did not all follow the frozen common contract.

## Symptom

Review found three related mismatches: locally constructed identifiers diverged from the shared canonical
builders, source-object material was represented as though it were a page crop, and some metadata identity
inputs exceeded the frozen contract. This was caught before publishing the v2 corpus.

## Root cause

The PDF adapter initially encoded resource extraction and page placement in one PDF-specific shape. The
common contract treats reusable source bytes, per-page occurrences, and rendered page crops as separate
objects with distinct identities and provenance.

## Resolution

- Replaced local ID construction with the common source-object and occurrence ID builders.
- Kept canonical source PNGs in source-object fields and reserved crop fields for verified page regions.
- Required every emitted PDF occurrence to pass the shared semantic validator.
- Aligned metadata artifact identity with the frozen common identity inputs.
- Classified verified page-crop-only evidence as render-only and withheld ambiguous regions.

## Verification

- Focused PDF v2 tests passed, including common semantic validation and render-only eligibility.
- Source-object reuse and per-placement occurrence identity remain distinct.
- No incompatible v2 artifact was promoted to retrieval or understanding input.

## Prevention

- All format adapters must call the shared canonical ID builders and validator at their output boundary.
- Tests must assert semantic validity, not only JSON shape.
- Never use a decoded source object as a substitute for a page crop; provenance fields must identify the
  coordinate space and recovery method explicitly.
