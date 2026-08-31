# Local Mini131 API-Parity Performance Validation

Date: 2026-09-01
Verdict: PASS — 131-item provisional evaluation complete and API-scorecard compatible; official quality gate not passed

## Branch isolation

- Local Qwen implementation and evaluation live on `feat/local-qwen-mini131-eval`.
- The prior HWP branch was content-cleaned without force push at corrective commit
  `83c712050c280e07409451d51ae679ee57fe9d89` and retained only as recoverable legacy history.
- Merge work uses `feat/hwp-visual-corpus-rollout-clean`, rooted at the HWP-only commit
  `4e6f04d2087f477def87bd86b2407fdcda0b4e15`. The local branch is a separate downstream line;
  no force push or history deletion was used. User-owned working-tree changes were not staged.

## Scope

- Candidate: Mac Ollama `qwen3.8:27b-mlx` + frozen KURE page-v1 retrieval.
- API reference: `mini131-bundle-v1`, generator `gpt-5-mini`.
- All 131 case IDs, questions, expected objects, lanes and asset types exactly match the API ledger.
- API case-record SHA-256: `6d8b0cb9c1b393ad5b7bfc749e6f69bc2e3dbcff9f759860296d3ad4948fa87e`.
- RAG records: 129/129.
- Parser regression: 2/2, kept outside the RAG semantic mean.
- Judge: fresh blinded `gpt-5.6-sol`, primary 129 / secondary 4 / adjudicator 3.
- Gold status: draft, named human approval pending.

## Scoring parity contract

- Answerable cases use the API weights: correctness `0.35`, faithfulness `0.25`, completeness
  `0.20`, factual claim coverage `0.10`, and citation validity `0.10`.
- Unknown/unanswerable cases use abstention quality. Component values are `0`, `0.5`, or `1`.
- Acceptance requires score `>85`, confidence `>=0.70`, and no hard flag.
- Report taxonomy matches the API: seven primary categories, four Core40 scenarios, four visual
  subgroups, and the five common metric sections (retrieval, answer, abstention, task success,
  operations).
- The local response was not normalized to the API response schema, so
  `response_contract_error_rate` is explicitly unavailable (`eligible=0`, `coverage=0`) rather than
  being mislabeled as `0.0`. API cost and live GCP GPU telemetry are handled the same fail-closed way.

## Joined record readback

- Private JSONL contains 131 unique records: 129 RAG + 2 parser.
- Every RAG row has question, frozen expected result, actual candidate answer/status, evidence,
  deterministic metrics, final semantic score/verdict/rationale, full review history and provenance.
- Difficulty partition is exactly easy 41 / medium 48 / hard 40.
- Final semantic aggregate reconciles to mean `70.135659`, accepted 88, rejected 41.
- Candidate outcomes are answered 87 / abstained 36 / error 6; runtime error rate `0.046512`.
- Parser is 2/2 PASS and does not enter the semantic mean.

## Same-item API comparison

| Candidate | RAG cases | Accepted | Rejected | Mean semantic score |
| --- | ---: | ---: | ---: | ---: |
| API `gpt-5-mini` | 129 | 58 | 71 | 54.845000 |
| Local `qwen3.8:27b-mlx` | 129 | 88 | 41 | 70.135659 |

Across all 131 assets, local scores are higher on 41 RAG cases, API scores are higher on 26, and 62
are equal; parser 2 cases have no semantic score. Verdict is unchanged on 91 cases and changed on 40;
execution status is unchanged on 100 and changed on 31. This is diagnostic evidence from the same
frozen question/expected ledger, not an official GCP winner declaration.

## Quality readback

| Slice | Cases | Accepted | Rejected | Mean |
| --- | ---: | ---: | ---: | ---: |
| easy | 41 | 34 | 7 | 84.207317 |
| medium | 48 | 31 | 17 | 67.239583 |
| hard | 40 | 23 | 17 | 59.187500 |
| single document | 10 | 8 | 2 | 90.750000 |
| multi-document comparison | 10 | 5 | 5 | 55.750000 |
| follow-up | 10 | 8 | 2 | 78.000000 |
| unknown / safe abstention | 10 | 7 | 3 | 70.000000 |
| clause/fact regression | 44 | 24 | 20 | 58.693182 |
| conditional all-list | 13 | 9 | 4 | 69.230769 |
| gold/source alignment audit | 12 | 12 | 0 | 97.500000 |
| visual table/figure | 10 | 5 | 5 | 49.000000 |
| corpus analytics | 10 | 10 | 0 | 96.000000 |

Component means are correctness `0.692308`, faithfulness `0.722222`, completeness `0.628205`,
factual-claim coverage `0.739316`, semantic citation validity `0.739316`, and abstention quality
`0.75`. Follow-up success is 8/10 and safe abstention is 9/12. Deterministic document Recall@5
is `0.987589`; conditional all-list F1 is `0.630769`.

API-aligned visual subgroup means use the same two-decimal half-up display rule: HWP table `66.67`
(2/3 accepted), HWP figure `0.00` (0/2), PDF table `96.67` (3/3), and PDF figure `0.00`
(0/2). Required-document recall is 76/112 (`0.678571`); conditional-list micro F1 is `0.478873`.
Visual target-page hit rate is 6/10, while target-object and target-chunk bridges remain 0/10 and 0/3.

## Integrity and privacy

- Parser rerun receipt hash and complete result match the frozen parser receipt exactly.
- All 136 review-history outputs match the validated raw decisions, output hashes and history hashes.
- Private records, summary and HTML are regular mode `0600` files; their directory is mode `0700`.
- Private outputs are ignored by Git and tracked private artifacts are zero.
- The public receipt is produced through explicit top-level and nested field allowlists. Mutation
  tests prove injected objective notes, deterministic metric names, labels, reasons, questions,
  rationales, private paths and invalid hashes fail closed or are dropped as contracted.
- Primary/scenario/visual summaries, objective metrics, common metrics and per-case local comparison
  fields are recalculated from the 131 private rows during validation; aggregate tampering fails.
- Public receipt mode is `0644`; it contains aggregate numbers and hashes only.

Final artifact SHA-256:

- records: `97c4011de0f2c2127ae143743c0466b0d23273be437ab1e75e8eb9fbade9136d`
- summary: `11ea02ae6fb9a987dc70ea6c94092a5e42458b4b520fa5db9de4ac74b8c4ac41`
- HTML: `ed253665a28abb2f9d1fa2d12e298f60d54bcc669f470fe059e4604d6f09c6e2`
- public receipt: `ceae2daa1dd1a6a71ede4fede09e90d79b0de95aa3075902a459c773dfef2b7a`

## Validation

- Focused performance/API-parity tests: 23/23 PASS, including canonical private integration,
  nested allowlist mutation, aggregate reconciliation and response-contract boundary cases.
- Full repository regression: 785/785 PASS in 28.720 seconds.
- HTML static QA: 131 unique cards; balanced markup; inline JavaScript parses; all filters and combined
  filters return the expected counts; summary cards and four aggregate tables reconcile to JSON.
- Mermaid target/current PNGs rendered with `mmdc 11.15.0`; two non-empty images, 12 gap rows and
  seven priority rows pass static readback. Visual inspection confirms the new per-question node.
- Automated in-app browser navigation to the private `file://` report was blocked by browser URL
  policy. No alternate-browser workaround was used; the report remains available for direct local
  opening, with static HTML/JS verification recorded above.

## Interpretation boundary

`record_complete=true`, but `quality_pass=false`, `gold_approved=false` and
`official_eligible=false`. This is a complete provisional Mac-local-equivalent evaluation, not a
human-approved gold result, held-out result or live GCP L4/vLLM/FAISS result.

Flow diagram verification: PARTIAL. The requested Mac-local per-question evaluation path is matched;
named human approval, live GCP telemetry and official API-to-GCP comparison remain explicit gaps.
