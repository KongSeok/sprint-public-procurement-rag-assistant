# Evaluation Aggregate Expectations

- Date: 2026-08-24 18:12 KST
- Stage: Test
- Failing test: aggregate latency, citation and safe-abstention expectations
- Error message: assertions retained four-case values after floor-complete fixtures were introduced.
- Root cause guess: fixture size changed without updating percentile/rate expectations.
- Fix summary: assert 40-case percentiles and proportional held-out/citation degradation at frozen gates.
- Pass evidence: evaluation metric suite passes with full scoring floors.
