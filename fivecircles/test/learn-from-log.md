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
- Drain multiprocessing Pipe results before joining workers; large serialized payloads can otherwise deadlock on the OS buffer.
- Keep a binary-model HWP fallback isolated and retain `partial` provenance warnings when XML/text transforms fail.
- Map fallback dependency, no-text, timeout and parse failures to distinct sanitized manifest codes.
- Mock every optional-dependency signal in absence tests so installed developer tools cannot change the expected path.
- Use explicit `PYTHONPATH=src` with the bundled runtime; its venv editable `.pth` may not activate in the sandbox.
- Treat legacy macOS `tidy` as HTML4-only; validate UTF-8 HTML5 with an HTML5-capable or tag-balance parser.

## Confirmed Incidents

- Batch 2 fail-closed audit: `errorlogs/backend/2026-08-24-evaluation-fail-closed-audit.md`
- Synthetic/production floor split: `errorlogs/backend/2026-08-24-evaluation-fixture-floor.md`
- Aggregate expectation refresh: `errorlogs/backend/2026-08-24-evaluation-aggregate-expectations.md`
- Missing PDF dependency runtime: `errorlogs/backend/2026-08-24-missing-pypdf-runtime.md`
- Optional Schema engine runtime: `errorlogs/backend/2026-08-24-jsonschema-runtime.md`
- PDF worker Pipe deadlock: `errorlogs/backend/2026-08-24-pdf-worker-pipe-deadlock.md`
- HWP binary-model fallback: `errorlogs/backend/2026-08-24-hwp-binary-fallback.md`
- Venv editable path: `errorlogs/backend/2026-08-24-venv-editable-path.md`
- Local validator runtime limits: `errorlogs/backend/2026-08-24-local-validator-runtime.md`
- HWP optional-dependency test isolation: `errorlogs/backend/2026-08-24-hwp-optional-dependency-test-isolation.md`
