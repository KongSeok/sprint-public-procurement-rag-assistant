# EVO35.2 - Actual Qwen3.5 live smoke and follow-up replan

Recorded: 2026-09-09T14:12:12+09:00. Mode: **solo**, explicitly requested; no development-agent calls.
Branch: `feat/hotline-runtime`. Runtime baseline: `e961149`.
Contract: `evo-hotline-qwen35-v1` / D-026.

## Verdict

**Actual local model and two-document comparison: PASS. Korean follow-up: FAIL / REPLAN.**
Overall EVO35.2 is PARTIAL, not a full RAG or learned-policy success. Two small prompt/observation repair candidates did not solve follow-up and were rejected. Product code and the original contract behavior were restored, with matching runtime hashes and 212 regression tests passing.

## Actual setup

Qwen3.5-9B was really loaded and called, not a scripted policy. Loaded artifact: `mlx-community/Qwen3.5-9B-4bit`, revision `8b2b98c00a6b4d291155e4890773ca8f769aee53`; backend MLX-VLM0.7.0 / MLX0.32.2 / Transformers5.16.1 / Tokenizers0.23.2, device `gpu:0` (Metal), 4-bit. The exact derivative manifest and tokenizer/template were checked by the normal backend. Canonical family is Qwen/Qwen3.5-9B; no unknown upstream checkpoint SHA is invented.

Each foreground worker had the unchanged120-second limit including setup, temperature0 and seed0, policy12/search4/read4/final-answer1 maximum, invalid-action limit2 and no automatic model retry. Existing model services and weights were not changed or downloaded. Inputs were only the built-in two-document synthetic corpus and an explicit follow-up built from its own prior citations; retrieval lanes are fake even though the store/hybrid APIs and Qwen are real. This is not KURE/BM25 production retrieval latency or Mini131 evaluation.

## Runs - all outcomes preserved

| Run | Result | Policy / answer calls | Total supervisor seconds |
|---|---|---:|---:|
| Published policy / comparison | answered | 4 / 1 | 11.085 |
| Same-model fixed control | answered | 0 / 1 | 5.918 |
| Original Korean follow-up | invalid_action_limit | 2 / 0 | 9.204 |
| Candidate A: current-ID lists/guide | invalid_action_limit | 2 / 0 | 8.893 |
| Candidate B: policy history projection | invalid_action_limit | 2 / 0 | 5.943 |

There are five diagnostic episodes with differing purposes and two candidate revisions. **Do not turn 2 answered / 5 runs into an accuracy benchmark.** Across them there were 10 actual policy calls and 2 final generation calls, no training and no private RFP inference. All five ended normally under supervision; failure exits1 mean invalid-action termination, not worker timeouts.

## What worked

The original comparison selected search, tried finish too early, received unknown_read_evidence, then independently selected read and finish. Its one search/read and one answer cited both synthetic documents. Manual inspection against the known synthetic source facts found the budget/period pairs correct: Alpha120 million KRW/6 months and Beta80 million KRW/4 months. This is the assistant's scoped inspection, not a newly implemented automatic semantic verifier; runtime semantic_verified remains false.

Original comparison: setup 4.981s, question processing 5.872s, supervisor total 11.085s. Policy inference4.437s and final generation1.433s are inside question processing. Fixed control returned the same answer with0 policy calls, setup 4.158s and question processing 1.532s. The two single-run totals are reference observations with different setup/cache scheduling, not a p50/p95 or generalized speedup. They show no benefit from additional policy calls for this already-complete simple example.

## Follow-up failure and rejected repairs

The Korean follow-up narrowed the hard scope to Beta and supplied actual previous assistant citations. On the original runtime, Qwen selected read with previous full evidence IDs twice instead of searching for current-episode handles. These included an out-of-scope prior reference; validation stopped before any retrieval, read or answer. No out-of-scope document was exposed through a tool.

Candidate A added current read/finish handle lists and general ID-lifetime instructions. Its4 new tests and the99-test selected suite passed, but the actual same-input follow-up still repeated the historical IDs and failed.

Candidate B additionally projected machine-only historical cited_evidence_ids out of the policy prompt while preserving the full original history for validation and final answering. Unit tests passed; the live model instead used the document ID as an evidence ID, then emitted malformed JSON. It again stopped at2 invalid actions with0 search/read/answer.

No guard, scope or invalid-action limit was relaxed and no invalid output was coerced into success. No question-specific facts or correct next action were injected. Since neither candidate demonstrated the intended live repair, both edits and their new tests were removed from the active tree after preserving patches, exact sources and raw output in ignored diagnostics. The unsuccessful proposals remain historical in the relay form, not active contract requirements. There was no third blind repair loop.

## Validation

Restored runtime-source hash check: all eight package modules and profile match the initial published candidate. Product files under src/tests/configs/scripts and pyproject have no diff. Native selected regression:212 tests,6.962s,OK,exit0,skip0; command uses the established project Python with `PYTHONPATH=src` and `PYTHONDONTWRITEBYTECODE=1`. The failed TDD outputs and both99-test candidate runs remain separately saved and are not substituted for the restored candidate's evidence.

Live command pattern:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  "$MLX_PYTHON" -u -m midprojectrag.evo_harness.cli \
  --data-dir resources/data_refined --model-dir "$MODEL_DIR" --model-manifest "$MODEL_MANIFEST" \
  --output-dir "$NEW_PRIVATE_RUN" --synthetic-corpus --record-trajectory --timeout-seconds 120
```

Fixed mode adds `--mode fixed`; follow-up adds `--request` with the saved synthetic request and `--follow-up`. All exact run outputs and per-candidate source hashes are under ignored `resources/data_refined/private/diagnostics/evo35-live-20260909-001/`. No full raw transcript is published. The whole-repository suite and independent Critic were not run; self-review is explicit. No active smoke process remained after execution.

A grouped read-only inspection call received a tool safety-status error; later narrower ordinary read-only inspection succeeded without altered credentials or permissions. An initial grep assumed an outdated installed module-file layout; actual import metadata resolved the installed package. A minimal patch needed the proper zero-context application flag; the first rejected patch had no product effect. These operational failures are distinct from the actual model failures.

## Target Flow

Reuse the unchanged target source/image: `2026-09-09-evo35-solo-target-flow.mmd` / `.png`, originally reviewed at e961149. The target architecture has not changed.

## Current Implementation Flow

`2026-09-09-evo35-live-current-flow.mmd` / `.png` show the demonstrated comparison path and the explicit failed follow-up edge. Browser report: `2026-09-09-evo35-live-report.html`.

## Target vs Current Gap

| Connection | Verdict | Evidence / limitation |
|---|---|---|
| Pinned local Qwen -> next-action wire | MATCHED, scoped | Actual GPU policy responses and exact token-count checks |
| Policy -> synthetic search/read -> two-source answer | MATCHED, scoped | Correct comparison and both citations; one rejected premature finish recovered |
| Same-model fixed control -> answer | MATCHED, scoped | Correct same comparison, no policy calls |
| Explicit history -> reliable constrained follow-up | GAP | Original plus two repair candidates failed; scope guards held |
| All BPE actions used appropriately by real model | PARTIAL | Implemented/tested, not comprehensively exercised by these live cases |
| Private RFP retrieval/quality and full support matrix | GAP | Not executed; synthetic lane results are not production ranking evidence |
| Trajectory split -> SFT -> GRPO / UI | GAP | No frozen training data/resource profile or training execution |

## Done / Not Done Priority

Weights: upstream0..4 + connection0..3 + safety0..2 + validation0..2 + risk0..-3; task-selection scores, not quality.

| Task | Score | State / next step |
|---|---:|---|
| EVO35.2.FOLLOWUP | 4+3+2+1-2=8 | REPLAN: next-action protocol/recovery must be redesigned or learned, not patched with another untested prompt |
| EVO35.2 private representative run | 3+3+2+1-2=7 | Later, not a substitute for unresolved follow-up behavior |
| EVO35.3 trajectory/SFT preparation | 1+2+2+1-3=3 | Frozen split, separate environment and concrete resource budget required before training |
| EVO35.4 GRPO | 0+2+2+1-3=2 | Depends on successful policy/data/reward/resource gates |

## Color Semantics

Green: demonstrated normal path in the stated synthetic scope. Amber: local model/state interface. Red: failed, unsupported or unvalidated edge. Gray: exact fixed control. A green synthetic search node is not production retrieval quality.

## Relay disposition

**STOP_WITH_REASON / REPLAN at EVO35.2.FOLLOWUP.** The first live-model edge is verified, but the follow-up acceptance fails and two bounded repair candidates have not yielded an acceptable implementation. The next task needs a new bounded policy/recovery design or a separately frozen learning experiment, not indefinite reruns or automatic changes to training scope. Existing policy training still lacks a concrete dataset/split/runtime/resource budget; it is not dispatched under a smoke test. No background work is running.

Flow diagram verification: **GAP/PARTIAL**. Publish factual run findings, not a failing feature as completed. Post-commit publication evidence is recorded separately after the actual push.

## Browser and publication checks

- Unchanged target PNG reused; current PNG rendered with Mermaid. Chrome/Puppeteer desktop1280 and mobile390: both images loaded, required headings and3 tables present, page errors0 and horizontal overflow0. Screenshots are in the existing playwright-screenshots folder; the actual engine was Puppeteer, not Playwright.
- Stock repository scanner still reports PII_PATTERN_FOUND. Classify exact SHA-256 false positives using the existing read-only classifier; never rewrite historical evidence or weaken the scanner. Final audit and actual push result are kept in the private publication receipt.
- Only documentation, summarized evidence and flow images are published. Product source/tests/config and historical control behavior have no diff; raw model prompts/completions, candidate patches and failure outputs remain ignored.
