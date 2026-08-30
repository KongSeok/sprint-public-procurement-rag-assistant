Timestamp: 2026-08-28
Context: local visual-context v2 index loading

Issue
- A metadata-valid visual-v2 corpus could be accepted when it covered only a subset of eligible HWP documents.
  That behavior was valid for the legacy table-v1 subset contract but violated the new 94-document corpus gate.

Resolution
- Detect the closed visual-v2 metadata shape and require its document ID set to equal the eligible `.hwp`/`.hwpx`
  manifest set exactly.
- Verify metadata count/hash, raw JSONL SHA-256, canonical record hash and aggregate identity before index load.
- Preserve legacy table-v1 subset behavior under its original contract instead of changing it implicitly.

Prevention
- Artifact versions with different coverage semantics need separate loader branches and tests.
- A correct per-record schema and aggregate hash do not prove corpus completeness; bind every full-corpus artifact
  to the authoritative manifest document set.
