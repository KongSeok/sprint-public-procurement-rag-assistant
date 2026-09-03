# Local Mini131 Per-Question Performance Evaluation Contract

Status: ACTIVE — MAC_LOCAL_EQUIVALENT_PROVISIONAL
Decision date: 2026-09-01
Implementation branch: `feat/local-qwen-mini131-eval-clean`

## Goal and boundary

The local Qwen run owns its execution code, private records, aggregate summary, HTML report and
public receipt. It does not read or publish another candidate provider's receipt, private result
ledger, score or per-question comparison. Cross-provider comparison is a separate downstream
artifact.

Only the provider-neutral Mini131 contracts are shared:

- suite composition: 129 RAG assets plus two deterministic parser regressions;
- scorecard taxonomy: seven primary areas, four core scenarios and four visual subgroups;
- exact five-section metric keyset;
- blind-judge schema, weights, acceptance threshold and rubric identity.

## Inputs and outputs

- Candidate: Mac-local-equivalent `qwen3.8:27b-mlx` with KURE/page-v1 retrieval.
- Judge: freshly blinded `gpt-5.6-sol`, rubric `gpt56-semantic-v2`.
- Gold state: draft; named human approval remains pending.
- Private output root: `evaluation/private/local-mini131/<suite>/performance-v1/`.
- Public receipt root: `evaluation/baselines/gcp-local-kure-qwen3-8b-awq-mini131-v1/`.

Private records, summary and HTML are mode `0600` and remain untracked. The public receipt contains
only counts, aggregates, content-free hashes, privacy flags and the exact scorecard-contract hash.

## Scoring and reporting rules

1. Record all 129 local RAG candidates and both parser results.
2. Join local source, candidate, deterministic score and blinded judgment only after hash and lane
   validation. Missing, duplicate or stale rows fail closed.
3. Preserve actual local answers, retrieval evidence, component scores, rationale and review
   history in private records; never regenerate a failed candidate during reporting.
4. Use correctness 35%, faithfulness 25%, completeness 20%, factual-claim coverage 10% and
   citation validity 10%. Abstention cases use abstention quality. Parser PASS/FAIL is excluded from
   the semantic mean.
5. Report seven primary categories, four core scenarios, four visual subgroups and the exact common
   metric keyset from `evaluation/contracts/mini131/scorecard-v1.json`.
6. Unmeasured metrics remain `null`, eligible `0`, coverage `0`, with an allowlisted reason. A
   different metric may not be substituted.
7. The local public receipt and HTML contain local results only.

## Frozen readback

- Total: 131 assets; RAG 129; parser 2/2 PASS.
- Difficulty: easy 41, medium 48, hard 40.
- Semantic mean: `70.135659`; accepted 88; rejected 41.
- Primary counts: 40 / 44 / 13 / 12 / 10 / 10 / 2.
- Core scenarios: 10 each.
- Visual subgroups: HWP table 3, HWP figure 2, PDF table 3, PDF figure 2.

## Definition of done

- Clean checkout imports all three local modules without provider-bound runner imports.
- Local config does not read a combined candidate-result ledger.
- The 131 records reconcile to the frozen readback and shared scorecard contract.
- Public receipt recursively excludes case IDs, questions, expected answers, candidate answers,
  evidence, rationales and all cross-provider result fields.
- Local focused tests, contract tests, HTML static checks, file-mode checks and Git privacy audit pass.
