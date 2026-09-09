# EVO35.3c.R1 Policy Context / Stagnation Repair

Date: 2026-09-09. Mode: solo relay-shot, user-explicit. Branch: `feat/evo35-context-repair`. Base: `803a30f`.

## Goal

Repair the runtime exhaustion classes observed during the frozen Mini131 PRE without modifying, restarting, or reinterpreting that PRE candidate.

## Current failure classes

Aggregate/runtime inspection only, not answer-quality inspection:

- `policy_context_budget_exceeded`: policy input plus the 256-token output reserve no longer fits the fixed 4096-token policy context after search/read state grows.
- `policy_attempt_budget_exhausted`: repeated cached searches can consume the 12 policy attempts without new evidence.

Search/read/image hard budgets, scope validation, canonical evidence provenance, answer context, and the frozen PRE candidate remain unchanged.

## Design

1. **Bounded policy projection**
   - Keep full evidence windows server-side for final answer/citation.
   - For policy observation only, progressively shorten read-window previews and then search excerpts until exact backend token count plus output reserve fits 4096.
   - Preserve IDs, document identity, truncation metadata and centered provenance-seed context where available.
   - If the smallest safe projection still does not fit, keep fail-closed `policy_context_budget_exceeded`; do not silently drop an evidence item/document.

2. **Duplicate-search stagnation guard**
   - First identical cached search remains a valid observation and is recorded as duplicate.
   - Until another non-search action advances state, remove `search` from the dynamic policy action schema for that exact stagnant state.
   - A direct repeated duplicate that bypasses the grammar fails `stagnant_duplicate_search`.
   - Any non-search action clears the cooldown; a later search remains possible.

## Out of scope

- increasing `policy_context` above 4096;
- increasing policy/search/read attempt caps;
- changing Qwen model, retrieval, RRF, final-answer packet, or Mini131 PRE outputs;
- using individual wrong answers, qrels or gold deltas to tune the repair.

## DoD / validation

- Unit: long read windows compact before overflow while canonical `episode.windows` remain intact.
- Unit: duplicate search becomes temporarily unavailable and recovers after state advancement.
- Existing Evo/training/PRE runner tests pass.
- Broad current impact selection passes without real external inference.
- After the frozen PRE finishes and the MLX resource is free, rerun the PRE runtime-failure IDs only as a repair regression; report terminal-code deltas, not answer/gold quality.
- Merge/push to hotline only after the frozen PRE aggregate is sealed, so PRE remains an exact `52c2e24` historical baseline.

## Current validation evidence

- Reused the already isolated repair candidate `8075b67` onto base `803a30f` as `890a9b3`; no PRE worktree/runtime files changed.
- Focused Evo/training/PRE/visual set: 109 tests PASS.
- Existing hotline/visual/retrieval impact set after the two new regression tests: 382 tests PASS.
- Training + PRE auxiliary after terminal-code-only replay selection test: 20 tests PASS.
- `git diff --check`: PASS.
- Frozen PRE snapshot at 70 records: 16 budget-exhausted terminals = 13 `policy_context_budget_exceeded` + 3 `policy_attempt_budget_exhausted`. These execution codes define the live repair regression set; answer/gold deltas are not inspected.
- Live repaired-Qwen regression: PENDING until the frozen PRE releases the MLX resource.

## Relay state

`IMPLEMENTED_TESTED_PENDING_LIVE`. Do not merge into `feat/hotline-runtime` before PRE closeout. Next gate: PRE aggregate seal -> repaired runtime-failure replay -> accept/reject candidate -> merge/push if accepted.
