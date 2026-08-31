# Local Mini131 Per-Question Performance Validation

Date: 2026-09-01
Verdict: PASS — provisional record complete; official quality gate not passed

## Scope

- Candidate: Mac Ollama `qwen3.8:27b-mlx` + frozen KURE page-v1 retrieval.
- RAG records: 129/129.
- Parser regression: 2/2, kept outside the RAG semantic mean.
- Judge: fresh blinded `gpt-5.6-sol`, primary 129 / secondary 4 / adjudicator 3.
- Gold status: draft, named human approval pending.

## Joined record readback

- Private JSONL contains 131 unique records: 129 RAG + 2 parser.
- Every RAG row has question, frozen expected result, actual candidate answer/status, evidence,
  deterministic metrics, final semantic score/verdict/rationale, full review history and provenance.
- Difficulty partition is exactly easy 41 / medium 48 / hard 40.
- Final semantic aggregate reconciles to mean `70.135659`, accepted 88, rejected 41.
- Candidate outcomes are answered 87 / abstained 36 / error 6; runtime error rate `0.046512`.
- Parser is 2/2 PASS and does not enter the semantic mean.

## Quality readback

| Slice | Cases | Accepted | Rejected | Mean |
| --- | ---: | ---: | ---: | ---: |
| easy | 41 | 34 | 7 | 84.207317 |
| medium | 48 | 31 | 17 | 67.239583 |
| hard | 40 | 23 | 17 | 59.187500 |
| single document | 10 | 8 | 2 | 90.750000 |
| multi-document comparison | 10 | 5 | 5 | 55.750000 |
| follow-up | 10 | 8 | 2 | 78.000000 |
| abstention | 10 | 7 | 3 | 70.000000 |
| clause/fact regression | 44 | 24 | 20 | 58.693182 |
| conditional all-list | 13 | 9 | 4 | 69.230769 |
| gold/source alignment audit | 12 | 12 | 0 | 97.500000 |
| visual table/figure | 10 | 5 | 5 | 49.000000 |
| corpus analytics | 10 | 10 | 0 | 96.000000 |

Component means are correctness `0.692308`, faithfulness `0.722222`, completeness `0.628205`,
factual-claim coverage `0.739316`, semantic citation validity `0.739316`, and abstention quality
`0.75`. Follow-up success is 8/10 and safe abstention is 9/12. Deterministic document Recall@5
is `0.987589`; conditional all-list F1 is `0.630769`.

## Integrity and privacy

- Parser rerun receipt hash and complete result match the frozen parser receipt exactly.
- All 136 review-history outputs match the validated raw decisions, output hashes and history hashes.
- Private records, summary and HTML are regular mode `0600` files; their directory is mode `0700`.
- Private outputs are ignored by Git and tracked private artifacts are zero.
- The public receipt is produced through an explicit field allowlist. Mutation tests prove injected
  question/rationale fields are dropped and private scalar/path or invalid hash injection fails closed.
- Public receipt mode is `0644`; it contains aggregate numbers and hashes only.

Final artifact SHA-256:

- records: `0e8dc05112b4171823dadece1e2ca27a90d6b30da72754a68cbd5b24962905f0`
- summary: `72c967c40a383099caf363bda5449d19f1fe0362d498bad3dae2edb736a62868`
- HTML: `503521d02a336efd011fb71693483e420e9b5eb888f5aef3af32611a6c9e4651`
- public receipt: `108aef0a64950c23dd3e5055c2ca13a756d66a0eff25281c6cd135d8d10269a5`

## Validation

- Focused performance tests: 11/11 PASS, including canonical private integration and mutation cases.
- Evaluation suite: 250/250 PASS before final three hardening cases; all are included in the full run.
- Full repository regression: 773/773 PASS in 33.462 seconds.
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
