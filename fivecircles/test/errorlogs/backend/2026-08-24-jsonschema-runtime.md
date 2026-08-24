# JSON Schema Engine Runtime

- Date: 2026-08-24 18:12 KST
- Stage: Test
- Failing test: optional Draft 2020-12 offline-engine smoke
- Error message: bundled Python 3.12 did not include the optional `jsonschema` package.
- Root cause guess: the core project intentionally uses standard-library validators and does not declare this QA-only package.
- Fix summary: reran the smoke in local Python 3.13 with `jsonschema` 4.26.0; no install or network access was used.
- Pass evidence: valid run resolved through the local registry; a reason/message mismatch was rejected.
