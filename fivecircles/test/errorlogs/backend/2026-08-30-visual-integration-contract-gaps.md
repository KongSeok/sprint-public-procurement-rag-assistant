# Visual retrieval and evaluation integration contract gaps

- Date: 2026-08-30
- Status: RESOLVED
- Impact: individually valid visual records could be dropped, over-promoted to answer support, or scored
  inconsistently after integration.

## Symptoms

- Applying caption caps before reading the full visual candidate set could hide later OCR/layout evidence.
- A full primary top-k left no bounded visual slot, while caption-only evidence could support an answer without
  verified claim refs.
- Visual citations lacked a closed gold identity and unannotated visual lanes could create false-zero precision.
- JSON Schema and manual validators disagreed on fusion metadata, stack fields and evidence ID prefixes.

## Root cause

The first implementation validated each visual component locally but had not frozen the cross-component
promotion, ranking and scoring invariants at retrieval/answer/evaluation boundaries.

## Resolution

- Overfetch the visual index before caps, reserve a bounded visual quota and prioritize OCR/layout over caption.
- Require supported caption claims with explicit refs; otherwise force safe abstention.
- Match visual gold on document, occurrence, evidence type and the exact evidence-ID set; ignore unannotated
  lanes in the precision denominator.
- Enforce `caption → cap_*`, `ocr/layout → ocr_*`, atomic fusion metadata and stack-specific field exclusions
  in both Schema and manual validation.

## Verification

- Focused visual/evaluation/CLI regression: 92/92 passed.
- Full suite: 493/493 passed; all 23 Draft 2020-12 schemas passed structural validation.
- Synthetic fixtures only were used in public tests and this incident record.

## Prevention

- Add differential Schema/manual tests whenever a cross-component evidence field changes.
- Test mixed primary/OCR/caption rankings, full primary top-k, caption-only answers and unannotated lanes.
- Treat claim promotion and evaluation identity as one closed contract, not separate local conveniences.
