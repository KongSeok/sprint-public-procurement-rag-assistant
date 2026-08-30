Timestamp: 2026-08-28
Context: repository safety scan of rendered flow-report PNG

Issue
- Quiet regex scanning treated arbitrary bytes in a generated PNG as a phone-number pattern before binary
  detection stopped the search. The report contained no user PII, but publication remained fail-closed.

Resolution
- Keep restricted-path and extension checks over every tracked/unignored file.
- Limit secret/PII regex inspection to textual and source-like files by excluding raster/font binary extensions
  from the regex input set. SVG and other text formats remain scanned.
- Re-run shell syntax and the complete repository scan successfully.

Prevention
- Do not interpret chance byte sequences in raster/font files as textual PII evidence.
- Protect binary artifacts through path/extension policy and artifact provenance; protect textual files through
  secret/PII regex scanning.
- Continue diagnosing with filename-only output until a candidate is classified.
