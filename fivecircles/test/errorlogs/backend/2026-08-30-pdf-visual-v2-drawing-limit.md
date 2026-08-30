# PDF visual v2 drawing-limit overflow

- Date: 2026-08-30
- Status: RESOLVED
- Impact: the first all-document PDF v2 run stopped on a page whose drawing count exceeded the bounded
  vector-grouping limit; an unhandled page would have made the corpus incomplete.

## Symptom

One page in the bounded full run contained more drawing primitives than the adapter permits for detailed
grouping. The initial behavior raised at the limit. Aggregate-only evidence confirmed the limit condition
without logging the source filename, page text, private path, or drawing content.

## Root cause

The safety bound correctly prevented unbounded vector clustering, but the adapter had no explicit
fail-closed occurrence for a page that exceeded that bound. Aborting, dropping the page, or silently
raising the limit would each violate a different part of the completeness/safety contract.

## Resolution

- Preserved the fixed drawing bound.
- Emitted one explicit full-page occurrence classified as ambiguous and withheld for the affected page.
- Recorded the bounded recovery reason so downstream OCR, captioning, and retrieval cannot treat it as
  verified visual evidence.
- Continued the all-document run without dropping the page.

## Verification

- The all-document PDF run completed with every input page accounted for.
- The overflow page is represented by a full-page ambiguous/withheld occurrence.
- No unbounded drawing grouping, private-content logging, or silent omission was introduced.

## Prevention

- Every bounded extractor needs a terminal, queryable fail-closed record for limit exceedance.
- Regression tests must assert both continued corpus completion and downstream withholding.
- Do not raise safety limits based on a single corpus page; tune them only with measured resource budgets
  and explicit contract review.
