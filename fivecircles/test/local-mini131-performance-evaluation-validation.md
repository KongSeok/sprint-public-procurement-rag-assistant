# Local Mini131 Performance Validation

Date: 2026-09-01
Verdict: PASS — local-only 131-asset provisional report regenerated

## Provider boundary

- Branch: `feat/local-qwen-mini131-eval-clean`.
- Local execution, private records, summary, HTML and public receipt are owned by this branch.
- Shared dependencies are restricted to the provider-neutral Mini131 suite, judge, taxonomy and
  scorecard contracts.
- The local report reads no other candidate receipt, private result ledger or score. It publishes no
  per-question cross-provider comparison.

## Frozen result

- Candidate: Mac Ollama `qwen3.8:27b-mlx` + KURE page-v1 retrieval.
- RAG: 129/129; parser regression: 2/2 PASS.
- Difficulty: easy 41 / medium 48 / hard 40.
- Mean semantic score: `70.135659`; accepted 88; rejected 41.
- Candidate outcomes: answered 87 / abstained 36 / error 6.
- Seven primary category counts: 40 / 44 / 13 / 12 / 10 / 10 / 2.
- Four core scenarios: 10 each.
- Four visual subgroup counts: 3 / 2 / 3 / 2.

## Contract and privacy evidence

- Shared scorecard: `evaluation/contracts/mini131/scorecard-v1.json`.
- The public receipt publishes the exact scorecard SHA-256.
- Private records, summary and HTML remain untracked mode `0600` artifacts.
- The tracked receipt contains only local aggregates and content-free hashes.
- Recursive boundary checks reject cross-provider result fields and private content.

## Validation commands

- Provider-neutral contract tests: PASS.
- Local baseline focused tests: PASS.
- Local semantic focused tests: PASS.
- Local performance focused tests: PASS.
- Clean import/compile checks: PASS.
- Local-only report regeneration from the frozen 131 private records: PASS.

This remains a provisional Mac-local-equivalent result. It is not a human-approved gold score,
held-out score or live GCP L4/vLLM/FAISS result.
