# Visual fusion rank assertion exceeded the retrieval contract

- Date: 2026-08-30
- Status: RESOLVED
- Impact: the first fusion unit test failed even though the implementation preserved the intended evidence
  ordering and caption cap.

## Symptom

The test asserted that an OCR hit must be absolute rank 1 after fusion. The frozen contract only requires
OCR evidence to rank ahead of caption-only evidence; an eligible text or table hit may legitimately remain
ahead of both.

## Root cause

The assertion encoded a stronger ranking policy than the contract. It confused relative ordering inside
the visual lane with global rank across all retrieval lanes.

## Resolution

- Changed the assertion to require OCR-before-caption ordering.
- Retained the contractual caption weight and result caps.
- Kept deterministic tie-breaking so equivalent scores remain reproducible.

## Verification

- The corrected test passes with a non-visual hit at rank 1, OCR ahead of caption, and caption bounds intact.
- The implementation was not changed to artificially boost OCR above stronger primary evidence.
- Synthetic fixture identifiers only were used; no private query or document text entered the log.

## Prevention

- Derive ranking assertions directly from contract invariants: relative order, caps, eligibility, and
  deterministic ties.
- Avoid asserting an absolute rank unless the contract fixes all competing lane scores.
- Include mixed primary/OCR/caption fixtures in fusion regression tests.
