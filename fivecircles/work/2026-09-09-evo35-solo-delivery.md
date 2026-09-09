# EVO35 solo delivery - Qwen3.5 policy over hotline

Date: 2026-09-09. Run: `evo35-hotline-20260909`. Branch: `feat/hotline-runtime`. Base: `2be2f46`.

## Verdict and contract

**EVO35.1: IMPLEMENTED / SCOPED_TESTS_PASS / SOLO_REVIEW.**
**EVO35.2: BLOCKED_TOOL_PREFLIGHT; application-model calls 0 in this continuation.**
Full target: `GAP/PARTIAL`. This is prompt-time infrastructure, not SFT/GRPO-trained EvoHarness, a real-model quality result, or completed UI delivery.

The contract follows the preceding accepted proposal: a Qwen next-action policy over hotline tools, light Belief/Progress/Experience, seven actions, multiple source windows and subsequent isolated SFT then GRPO. D-026 substitutes Qwen3.5-9B for the originally proposed model. The user's later explicit instruction changes only development execution to solo; no Coder/Critic is called. Local JSON wire, RAG tools and the starting budgets are project adaptations, not verbatim paper specifications.

Primary references rechecked: EvoHarness-RL arXiv:2608.05446v1 sections 2.1-2.4 and official Qwen/Qwen3.5-9B model card. The paper's original environment/model results are not claimed for this implementation.

## What was inspected and completed

The current worktree already contained the interrupted solo draft (eight package modules, configuration, entrypoint and two test modules). It was read and preserved, then finished through scoped review, new delivery regression, fixes, flow reporting and publication checks. No claim that these existing files were all newly authored in the continuation.

- `evo_harness/state.py`: strict one-action JSON, bounded per-episode BPE, usage counters and short local evidence handles.
- `tools.py`: existing public HybridChildRetriever search and EvidenceStore reads, explicit hard scope, verified prior-citation intersection for follow-up, request-local duplicate reuse, multi-window source mapping.
- `policy.py`: fully counted prompts for Qwen3.5, action adapter, separate one-attempt answer composer, exact S-label/source windows, unresolved and uncited-document reporting.
- `runner.py`: bounded observe/act loop and same-tools fixed control; no retired Controller action/ledger/transition recursion.
- `experience.py`: versioned reviewed snapshot and quarantined episode notes; no runtime promotion of notes into shared experience.
- `runtime.py`: optional local MLX composition with pinned converted-artifact manifest and no automatic downloads or CPU fallback. Implemented, not live-model validated in this continuation.
- `cli.py`, `scripts/run_evo_hotline.py`, project entrypoint and `configs/rag/evo-hotline-qwen35-v1.json`: policy/fixed modes, private outputs and owned-process budget.

Historical hotline.py, orchestration Controller, shared retrieval and evidence sources have no working-tree changes from this delivery. No shared model/VM service was replaced. No private corpus questions, old candidate answers or gold were used for inference.

## Review findings and repairs

1. The inherited fixed-control path did not validate nonfinite/boolean deadlines identically to policy mode. New regression reproduced inappropriate execution; fixed before calls.
2. The inherited runner reported combined action wall time only. Added separate policy/tools/answer durations, including failures, without a new profiling framework.
3. Fixed-control successful results did not explicitly flag a synthetic backend. Added the same explicit synthetic/trained-policy boundary as policy-mode results.
4. Added full model-free CLI worker composition through real public synthetic retrieval APIs and answer/citation output, no-overwrite and file-permission checks.

The new five-test delivery suite initially produced failures=4/errors=3 including subtest failures. The original RED output is preserved; it is not counted as passing. All delivery tests passed after the scoped runner changes.

## Validation evidence

Project Python 3.12 interpreter: original project's `.venv/bin/python`, with the hotline worktree as cwd, `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src`. No dependency installation.

```bash
python -m unittest -q tests.test_evo_harness tests.test_evo_harness_edges \
  tests.test_evo_harness_delivery tests.test_hotline_runtime tests.test_controller_quick_qa
# 95 tests, 1.093s, OK, exit0; no skips

python -m unittest -q tests.test_runtime_integrity tests.test_retrieval_obligations \
  tests.test_action_effect_receipts tests.test_semantic_verification \
  tests.test_e0_fusion tests.test_child_fusion
# 117 tests, 6.629s, OK, exit0; no skips
```

Total: **212** tests in disjoint selected modules, not an entire-repository regression. Newly added Evo suites account for 65; existing hotline/related regression accounts for 147. The synthetic backend is labelled as a test double, not a trained or live policy.

A successful synthetic episode reaches search/read/finish and two actual source-window citations with policy calls=3 and final generation calls=1. Call tracing checks zero retired Controller execution/decision/history-reader entries. The observation-driven test revisits only the remaining document. Failure consumption, invalid-action limits, scope, unknown evidence, no gold projection, context overflow, explicit history and quarantine tests passed.

Native raw logs: `resources/data_refined/private/diagnostics/evo35-solo-20260909-continue/`, excluded from Git. They contain synthetic test data only. Preserve the initial/RED/final logs separately.

Browser report: Mermaid target/current PNGs generated. Chrome through Puppeteer verified desktop1280 and mobile390: both images loaded (1568x1254 and 1568x1540), required headings/tables present, no horizontal overflow or page errors. Screenshots are under `fivecircles/test/playwright-screenshots/2026-09-09-evo35-solo-{desktop,mobile}.png`; this folder name does not imply Playwright was the engine. Product UI was not changed or tested.

## Target/current and priority

- Target: `2026-09-09-evo35-solo-target-flow.mmd` and `.png`.
- Current: `2026-09-09-evo35-solo-current-flow.mmd` and `.png`.
- Browser report: `2026-09-09-evo35-solo-delivery.html`.
- Green: implemented/model-free tested code; amber: local model interface; red: unresolved live/training gaps; gray: fixed control/future experiments.

| Connection | Status | Evidence / next step |
|---|---|---|
| Request/scope/history -> Episode | MATCHED, code | Focused scope/follow-up tests |
| Policy interface -> tools/BPE -> observation | MATCHED, synthetic | State-dependent next-action tests and real public tool APIs |
| Multiple windows -> citations | MATCHED, synthetic | S1/S2, parent-window provenance, unresolved reporting |
| Actual Qwen3.5 weights -> policy actions | PARTIAL/BLOCKED | Model artifact preflight tool request was blocked before execution |
| Trajectories -> SFT -> GRPO | GAP | Frozen split, compatible training environment and resource budget are not established |
| Real RFP quality and UI | GAP | Not evaluated or connected in this batch |

Selection weights: upstream0..4 + connection0..3 + safety0..2 + validation0..2 + risk0..-3. EVO35.1 score9 closes the first code gap. EVO35.2 score7 is next but blocked. EVO35.3 score3 and EVO35.4 score2 depend on the missing runtime/data/resource prerequisites. Scores are not model quality.

## EVO35.2 re-entry and stop condition

After code validation, the next selected unit was exact existing local Qwen3.5 artifact/runtime preflight and a synthetic-document-only live smoke within the 120-second limit. A request combining model-manifest metadata, installed MLX interface inspection and shared tests was blocked by the tool with: "we couldn't determine the safety status of the request." No model metadata result, native exit, hash validation or application inference was obtained from that call. The unrelated model-free shared tests were subsequently run on their own and passed.

Do not infer missing weights, a broken GPU, a bad model or low quality from this access failure. Do not treat the read-only public prior experiment record as current artifact verification. The blocked model-artifact action was not rerouted through another account, agent or tool, and no model download/service replacement was used. No live Qwen3.5 success is claimed.

Continuation: **STOP_WITH_REASON at EVO35.2**. Resume the same solo run after permitted artifact preflight is available. Training is not dispatched merely because the code tests passed; data/split/environment/resource prerequisites remain separate. No background job is left running.

## Publication

Same hotline branch and selective feature files only. Final git/safety/remote acknowledgement is recorded after the actual commands. No independent Critic or whole-suite PASS is claimed. Existing numeric SHA-256 false positives in the repository scanner must remain disclosed rather than changing historical evidence or the scanner.

### Final publication checks
- Source identities after tests matched for all eight modules, three Evo test files and the model profile. Control hotline, Controller and shared retrieval/evidence code remain unchanged.
- Stock scanner remains FAIL/PII_PATTERN_FOUND. Separate existing-classifier review found only three phone-pattern substrings entirely inside exact SHA-256 JSON fields; unresolved privacy/secret/restricted-path findings0. Neither scanner nor historical records were changed.
- Publication is the user's existing hotline-branch instruction carried through solo relay. Same-candidate self-review and impact regression apply; no independent Critic is claimed.
- Actual local/remote commit acknowledgement belongs to the post-commit private publication receipt; this report does not prefill a future hash.
