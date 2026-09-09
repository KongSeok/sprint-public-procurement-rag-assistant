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
- Actual pinned Qwen3.5 tokenizer/chat-template smoke, no model load: 4x1500-char server windows compacted to 4x768-char policy previews at 3413 input tokens + 256 reserve = 3669/4096; 6x1500-char windows plus bounded prior history compacted to 6x384 at 3436 + 256 = 3692/4096. Full server windows remained 1500 chars each. Network sandbox denied.

## VM35 staging - 2026-09-09

- User explicitly approved SSH-key issuance and VM35-first rollout; VM3/Qwen3-8B port remains deferred.
- GCP target verified: `rag-gpu-vm`, `us-central1-c`, `g2-standard-4`, 100 GB disk. A gcloud SSH key was generated and project metadata updated successfully.
- Repair branch cloned into the isolated owner path `/home/pio/MidProjectRAG-evo35-context-repair` at exact commit `f3e74fcf28d5cd43a13dd09ae27d2b27d803bce3`.
- Isolated test environment `/home/pio/.venvs/evo35-repair`; project/shared serving Python environments were not upgraded. Focused `tests.test_evo_harness tests.test_evo_mini131_pre`: 49/49 PASS on VM.
- Runtime inventory found no Qwen3.5 model/service on ports 8000-8003 or in accessible VM paths. Port 8002 identifies `Qwen/Qwen3-8B-AWQ`; the L4 is already occupied by processes owned by another VM user. Those processes were not signalled, restarted, modified or reconfigured.
- Root disk after isolated staging: 69/96 GB used (72%), below the 80 GB project warning threshold. No Qwen3.5 weights or heavyweight serving stack were downloaded.
- VM35 status is therefore code-staged + model-free-tested, not live-model-validated. Live replay remains blocked on an available Qwen3.5 VM runtime/GPU slot; do not reinterpret this as a Qwen3-8B patch.

## Relay state

`IMPLEMENTED_TESTED_PENDING_LIVE`. Do not merge into `feat/hotline-runtime` before PRE closeout. Next gate: PRE aggregate seal -> repaired runtime-failure replay -> accept/reject candidate -> merge/push if accepted.

## Local recorded-PRE runtime replay mode

Fresh KURE end-to-end replay remains the canonical final runtime check, but loading the pinned KURE/MPS stack exceeds the synchronous Chatty command execution window. Do not background that job. For the repair gate, use an additional deterministic isolation mode that freezes PRE search outputs and runs only the changed policy/runtime live:

- load the sealed PRE EvidenceStore without KURE inference;
- remap each PRE search candidate by exact `(doc_id, kind, excerpt)` to canonical evidence;
- require unique mapping and fail closed otherwise;
- replay those frozen search batches through real HotlineTools/read windows and the pinned Qwen3.5 policy; if the repaired policy performs more search calls than PRE recorded before failure, hold the final frozen batch and count each reuse explicitly;
- use a deterministic final-answer stub, because semantic answer quality is explicitly out of scope;
- keep all replay records private and publish only aggregate terminal-code deltas.

Private preflight over the 25 runtime-failure records found 380/380 recorded search candidates uniquely remappable. This mode does not claim retrieval quality, fresh KURE equivalence, or answer quality; it isolates whether the policy-context, duplicate-search and read-memory repairs remove their runtime terminal failures.
