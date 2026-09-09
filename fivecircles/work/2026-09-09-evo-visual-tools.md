# HOTLINE.VISUAL.2 - Automatic policy visual tools

2026-09-09. User asked to attach the merged visual functions and test them. Solo mode, actual hotline worktree, start bca3a64.

Plan: explicit two-tool contract -> narrow adapter and deadline/model reuse seams -> focused and combined regression -> bounded actual local Qwen/KURE/image episode -> self-review and selective publication.

No former Controller, source truth promotion, silent corpus/model changes, policy training or default UI rollout. Existing private one-occurrence index is an integration fixture, not a ranking-quality benchmark. Raw evidence stays private; failed runs are recorded separately. Initial source snapshots are preserved.

Status: IMPLEMENTING. Results follow actual checks.

## Final implementation

Completed the explicit opt-in policy connection, not merely a branch merge:

```text
question / allowed document scope
 -> Qwen3.5 policy selects visual_search
 -> existing OCR/layout index, actual KURE query on MPS, pre-ranking scope filter
 -> policy selects inspect_image on a returned current-episode handle
 -> verified original PNG / actual pixels / same loaded Qwen3.5 model
 -> typed unreviewed visual_inference or explicit abstention
 -> policy selects finish -> final answer + application-owned image citation
```

Text and visual tools can coexist in the same episode. `--visual-only` is explicit when text artifacts are not loaded. The old text-only guide/default remains unchanged when visual capability is off. Two-source mixed text/visual packets were tested with synthetic providers; this batch's live run used the existing visual-only index.

- `evo_harness/visual.py`: adapter, current visual handles, request-local cache, shared search/read budgets, image-attempt cap2, exact image provenance and typed windows.
- `evo_harness/visual_runtime.py`: separate existing KURE Python/cache, bounded query child and OS network denial. Failed calls never become cached empty success.
- `evo_harness/runtime.py` and imported `visual_qa.infer_loaded`: reuse the policy's existing pinned MLX model and processor for actual image pixels. No second9B model is loaded for an image.
- `visual_ocr_index.search`: additive allowed_doc_ids parameter passed to the already scoped vector index before top-k; default standalone behavior preserved.
- `state/policy/tools/cli`: strict two-action schema, capabilities, image usage, mixed citations and no-egress120-second owned-worker setup. Existing seven text/state actions remain available when configured.
- No restored Controller authority/ledger/history graph, corpus rebuild, OCR rerun, caption indexing, automatic source truth promotion, default Streamlit switch or training.

## Validation

Final combined selection: **378 tests /378 unique IDs**, failures0/errors0/skips0, 8.565s, native exit0. This is the previous352 impact selection plus26 new visual-policy cases, not the whole repository suite. The early96/25/95 focused runs are overlapping checks, not additional unique tests.

New cases cover scoped top-k, empty/unknown/widened scope, current handles, read-before-inspect rejection, original PNG binding, uncertainty withholding, mixed text/image citations, duplicate caching, different-question cache restoration, failed/late call accounting, image/common budget caps, virtualenv preservation, same loaded backend objects, bounded no-egress query child, unavailable text capability, explicit historical visual citation scope and CLI option errors. Existing text/hotline/visual regression stayed green.

Command: established Python3.12 project interpreter from the hotline root, `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src:$PWD"` and the same selected-module runner. No package installation or test-assertion weakening. Exact module/ID list and raw logs are in ignored diagnostics. No product UI was changed; CLI and same-process output/citation interfaces were exercised.

## Actual model tests, all attempts retained

| Run | Outcome | Policy / image / final calls | Supervisor total |
|---|---|---:|---:|
| live-001 | runtime error before KURE embedding | 1 / 0 / 0 | 7.834s |
| live-002 | search and image reading executed; policy requested clarification | 4 / 1 / 0 | 22.689s |
| live-003 | answered, image citation1, invalid actions0 | 3 / 1 / 1 | **18.680s** |

These are different repaired candidates, not a success-rate or speedup benchmark. The three bounded episodes contain8 policy model calls,2 actual image calls and1 final text generation. All are actual Qwen calls, not scripted responses. The first failed query worker never embedded the query. Actual successful KURE query runs used mps:0 with no CPU fallback and existing weights only.

The final model chose `visual_search -> inspect_image -> finish` without a coded forced schedule. Initial setup 4.255s; policy inference 5.434s; tools 7.650s; final answer 1.131s. Worker total 18.470s; supervisor total 18.680s. Averages/p50/p95 and a warmed server are not measured.

Model: `mlx-community/Qwen3.5-9B-4bit`, revision8b2b98c00a6b4d291155e4890773ca8f769aee53. Device `Device(gpu, 0)`, MLX-VLM0.7.0. Actual image_count1, pixels shape [1748, 1536], image input tokens727, actual prompt count identical, output tokens58, finish_reason=stop; OCR text supplied to VLM=false. Policy/answer reused the same loaded backend. Observed MLX peak memory 7.209GB is this runtime's reported peak, not total machine memory.

Policy input/output tokens 3073/105; image 727/58; final answer 517/38. Search/read/image/final attempt counts1/1/1/1 stayed within shared budgets. The whole visual parent and KURE child executed under OS network denial; no external model/API was called.

## Defects found and corrected

1. CLI used Path.resolve on the KURE virtualenv executable. That selected the base interpreter and lost installed Torch. Preserve the invocation path for --visual-python while still canonicalizing data paths. Added a failing symlink regression, then fixed it; no dependency install or interpreter substitution. Original error and RED output are retained.
2. The policy interpreted human_review_required as missing user input. It had actually read the pixels but requested clarification after one invalid JSON action. Clarified the generic distinction: usable_in_finish with no uncertainties permits a qualified image-reading answer; review status is still attached. No image text, user question, uncertainty validator, evidence guard or completion status was hard-coded/overridden.

Final source hashes match both the final378-test candidate and the live003 execution. Existing source index metadata/chunks/occurrences/vectors remain byte-identical; image hash is verified again before/after inference. Other worktrees/models/services are unchanged.

## Quality and scope limits

**Live wiring and citation return passed; image recognition correctness is not established.** The reused OCR index contains2 chunks from1 image occurrence. This cannot validate ranking recall or whole-corpus OCR quality. The image-reading wording differed between the two successful image attempts (their model-selected subquestions differed); neither is a human-approved reference answer. Do not call this a Korean OCR/VLM accuracy improvement or claim deterministic same-input accuracy from it.

The final JSON still carries human_review_required=true, factual_evidence_promoted=false and semantic_verified=false. UI consumers must display the review state; the application must not present a bare generated label as independently verified source truth. If image uncertainty is returned, no finish-usable window is created.

Mixed text+visual behavior was tested in code; actual private text artifacts were not co-loaded in this live003 visual-only run. Generic topic routing, other images, all BPE strategies, current follow-up failures, SFT/GRPO, golden131 and default UI integration remain separate work. OCR itself was not rerun: the existing OCR-derived index was queried.

## Publication and handoff

Self-review in user-selected solo mode, no independent Critic. Publish source/tests/contract and redacted run summaries only. Raw queries, OCR text, original images, model completions, token transcripts and private file paths remain in ignored `resources/data_refined/private/diagnostics/hotline-visual-policy-20260909-001/`. Actual commit, remote match and clean status are recorded after Git operations.

Status: IMPLEMENTED /378 TESTS PASS / LIVE VISUAL ROUTE ANSWERED / SEMANTIC QUALITY UNVERIFIED.

### Final pre-publication recheck
- 2026-09-09T15:28+09:00 이후 동일 후보를 다시 검증: final-source.sha256 13/13 일치, selected combined 378/378 unique tests PASS, failures0/errors0/skips0, 8.700s, exit0.
- Stock safety checker still reports PII_PATTERN_FOUND. Existing read-only classifier inspected1000 candidate/incoming objects and found exactly3 numeric matches wholly inside pre-existing exact SHA-256 JSON fields; unresolved findings0. Scanner/history were not modified to create a pass.
- Publication scope remains source/tests/contracts/redacted summaries only; raw visual/model diagnostics remain ignored. No extra model run or environment change in this recheck.
