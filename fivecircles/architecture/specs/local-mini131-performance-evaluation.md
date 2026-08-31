# Local Mini131 Per-Question Performance Evaluation Contract

Status: ACTIVE — MAC_LOCAL_EQUIVALENT_PROVISIONAL
Decision date: 2026-09-01

## 1. Goal

Turn the already completed local Mini131 run into an inspectable performance evaluation. Every
golden asset must preserve the question or parser check, frozen expected result, actual local
candidate output, evidence, deterministic metrics, final Sol judgment, numeric score, and judgment
rationale in one private record.

## 2. Scope

- RAG: 129/129 records.
- Parser regression: 2/2 records, reported separately from the RAG semantic mean.
- Candidate: Mac-local-equivalent `qwen3.8:27b-mlx` over the frozen KURE/page-v1 stack.
- Judge: fresh blinded `gpt-5.6-sol`, rubric `gpt56-semantic-v2`.
- Gold state: draft; named human approval remains pending.

## 3. Private artifacts

Derived under `evaluation/private/local-mini131/<suite>/performance-v1/`:

- `golden-evaluation-records.jsonl`: 131 joined per-asset records.
- `golden-performance-summary.json`: overall, difficulty, purpose, lane, component, and deterministic aggregates.
- `golden-performance-report.html`: self-contained review UI with searchable per-question details.

All three files must be regular files with mode `0600`. They contain private questions, expected
answers, candidate answers, evidence, and judge rationales and must never be committed.

## 4. Join and score rules

1. Verify the frozen suite, 129 candidates, 129 deterministic rows, 129 semantic results, 136 judge
   history rows, and two live parser results before writing output.
2. Join only by validated `case_id` after checking source, candidate, judge-input, config, run, and
   score hashes. Missing, duplicate, stale, or lane/status-mismatched rows fail closed.
3. Record the actual answer and evidence shown to the judge. Do not regenerate, repair, or replace a
   failed candidate during reporting.
4. Use the final validated primary/secondary/adjudicator judgment. Preserve all component scores,
   confidence, critical flags, matched key points, final rationale, and judgment history.
5. Semantic score is 0–100 using the frozen rubric weights. Parser PASS/FAIL never enters this mean.
6. Aggregate by `easy`, `medium`, `hard`, evaluation purpose, and execution lane. Every aggregate
   carries its eligible denominator; unavailable metrics are null rather than silently treated as 0.
7. The parser rerun receipt hash and full result must exactly match the frozen parser receipt. Every
   one of the 136 history outputs must match its validated raw decision and its own output/history
   hashes; non-final review drift also fails closed.

## 5. Public receipt

Only a content-free receipt may be written under
`evaluation/baselines/gcp-local-kure-qwen3-8b-awq-mini131-v1/`. It may contain counts, aggregate
scores, artifact hashes, model/config identities, and privacy flags. It must contain no case ID,
question, expected answer, candidate answer, evidence, private path, or rationale.

The receipt is rebuilt through an explicit field allowlist. Aggregate scalars must be finite and in
their declared ranges, runtime is the fixed `mac_ollama_numpy` enum, artifact values must be SHA-256,
and injected summary fields are omitted or rejected before the public file is replaced.

## 6. Interpretation boundary

The result may be called a complete provisional Mac-local-equivalent Mini131 performance
evaluation. It is not an official human-approved gold score, held-out score, or GCP L4/vLLM/FAISS
score until the corresponding gates are completed.

## 7. Definition of done

- 129 RAG + 2 parser records validate and render.
- Every RAG record has question, expected result, actual answer/status, evidence, deterministic
  metrics, semantic score/verdict/rationale, and provenance hashes.
- Difficulty counts are exactly easy 41, medium 48, hard 40.
- Aggregate score reconciles exactly with the canonical semantic score and public receipt.
- Parser receipt/result, all 136 raw decisions/history outputs, and public allowlist mutation tests
  pass fail-closed checks.
- Unit/integration tests, HTML static checks, browser smoke, mode checks, and Git privacy audit pass.
