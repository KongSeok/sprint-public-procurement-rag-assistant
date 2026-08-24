# Evaluation Fixture Floor

- Date: 2026-08-24 18:12 KST
- Stage: Test
- Failing test: balanced synthetic dataset and production scorer fixtures
- Error message: one-case-per-task fixtures conflicted with frozen dev 10/held-out 5 floors.
- Root cause guess: structural examples were reused as production scoring fixtures.
- Fix summary: keep explicit one-case validation only for templates; score with floor-complete 40/20 synthetic sets.
- Pass evidence: config override and undersized-score regressions pass.
