# 2026-09-05 — C1 contract patch context mismatch

## Symptom

The first atomic documentation patch was rejected before writing because its expected
`module-contract.md` context began at a different wrapped line.

## Cause

The patch used a semantically correct but not byte-exact multiline anchor after inspecting a
larger truncated output.

## Resolution

- Confirmed that the failed atomic patch changed no file.
- Re-read the exact target lines and applied smaller, independently verifiable patches.
- A later patch also rejected duplicate `Update File` operations for one path; combined its hunks
  under one operation before retrying.

## Prevention

- Before a multi-file patch, read exact narrow anchors for every target.
- Split mixed append/insert work so one wrapping mismatch cannot cancel an otherwise valid batch.
