# PDF visual v2 publish-root sandbox permission failure

- Date: 2026-08-30
- Status: RESOLVED
- Impact: the first four-document PDF v2 run completed document analysis but could not enter the atomic
  materialization phase, so that attempt published no completed corpus artifact.

## Symptom

After all input analysis had finished, creation of the materializer's `TemporaryDirectory` raised
`PermissionError`. The CLI returned the content-free error code `pdf_visual_v2_publish_failed`; it did not
print a source filename, private path, document text, or credential.

## Root cause

The requested private output root was outside the current task's writable sandbox roots. The failure
occurred before staged artifact creation and reflects the execution boundary, not a parser, reconciliation,
or materializer code defect.

## Resolution

- Preserved the code, configuration, and input identities from the failed attempt.
- Restarted the same run through the approved local execution path with permission to write the intended
  output root.
- Kept atomic staging and metadata-last publication intact rather than redirecting output to an
  uncontracted location.

## Verification

- Environment diagnosis is complete: the denied operation was temporary-directory creation under the
  publish root.
- The approved local rerun completed all 4 PDF documents and 570 pages with 1,110 occurrences.
- Immediate re-execution returned the same artifact-set identity and all three artifact hashes.
- Seven over-complex regions remained explicitly `ambiguous/withheld`; no guessed promotion was made.

## Prevention

- Add a content-free publish-root writability preflight before expensive document analysis.
- Keep atomic temporary staging inside the validated destination root and fail before processing when the
  root is not writable.
- Preserve stable error codes and aggregate-only diagnostics for permission failures.
- Classify environment recovery separately from end-to-end validation completion.
