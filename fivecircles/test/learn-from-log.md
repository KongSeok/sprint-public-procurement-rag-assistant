# MidProjectRAG Test Learnings

Review this file before implementation and test execution.

## Active Preventive Rules

- Use synthetic data in public tests; private corpus tests are opt-in.
- Never print document text or PII while diagnosing an extractor failure.
- Record failed extraction rows in the manifest instead of dropping them.
- Validate JSON Schemas and cross-reference IDs before computing metrics.
- Treat every nested JSON value as untrusted even after recording a validation issue; guard iteration, hashing and membership by type.
- Enforce frozen case floors and scoring gates inside `score`, not only in a separate dataset-validation command.
- Recompute threshold truth from metric values when comparing reports; stored `passed` flags are evidence, not authority.
- Run the full suite in an interpreter with declared project dependencies; a bare system Python is not verification evidence.

## Confirmed Incidents

- Batch 2 fail-closed audit: `errorlogs/backend/2026-08-24-evaluation-fail-closed-audit.md`
- Synthetic/production floor split: `errorlogs/backend/2026-08-24-evaluation-fixture-floor.md`
- Aggregate expectation refresh: `errorlogs/backend/2026-08-24-evaluation-aggregate-expectations.md`
- Missing PDF dependency runtime: `errorlogs/backend/2026-08-24-missing-pypdf-runtime.md`
- Optional Schema engine runtime: `errorlogs/backend/2026-08-24-jsonschema-runtime.md`
