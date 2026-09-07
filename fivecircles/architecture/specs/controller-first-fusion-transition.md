# EH2.6.c4.2.b.1 — First-obligation fusion execution and revision3

Status: bounded implementation contract, 2026-09-07.
Sources: bidfit-evidence-harness-v1-rc0.md §16.10, controller-next-decision.md d2.x.b.1,
controller-initial-transition.md and controller-lexical-transition.md.
This extends their historical bounded slices; it does not change revision0/1/2 behavior.

## Goal and private surface

- Add private `_execute_controller_first_fusion_step(execution, decision, store, config, runtime) -> HarnessExecution`.
  Accept only the exact revision2 fact/compare first-obligation execution and its exact ordinal3 selected fuse permit.
  Caller supplies no obligation, lane receipt, outcome, evidence, hash, effect or after-state.
- Add private `_require_controller_first_fusion_transition(execution, store, config, runtime)` returning
  the exact (ActionEffectReceipt, HarnessTransitionReceipt) for revision3 only.
  Existing initial and lexical readers stay revision1-only and revision2-only.
- No public start/step/run, ordinal4 decision, terminal result, later obligation or semantic reducer.

## Authority and preflight

1. Reuse live execution and decision validators. Require ordinal3, selected-first fuse targeting the first
   obligation, revision2/count2, remaining nonterminal budget and the exact transition2 chain.
   Existing decision budget -> contract-error -> provider-error -> normal priority remains unchanged.
2. Read the retained revision2 lexical transition and its exact revision1 predecessor/dense transition.
   Obtain the first obligation and both lane receipts from those existing authenticated source authorities.
   Require same exact obligation/round1/query/scope/store/config/runtime and normal applied/empty outcomes.
   Ledger counts and serialized receipt/hash fields are consistency checks, never replacement authority.
3. Never remint the compare obligation tuple. No later compare obligation is selected or dispatched.
   Full canonical sibling-obligation lifetime remains deferred.
4. Reject cloned/mixed/stale/drifted inputs and abstain/error/budget permits before fusion dispatch.
   Dense provider_error with successful diagnostic lexical remains ineligible; preserve both error histories.

## Existing temporal source fence and once-only execution

- The generic resolver already supports FusionReceipt, but current controller prepare/attempt admission is
  lane-only. Extend that existing shared attempt registry, caller seals and source preparation to exact fusion
  attempts and receipts. Keep one shared monotonic attempt epoch and atomic claim cutoff; no clock is read.
- Preserve exact approved executor/minter code and module-global checks and source-kind/attempt binding.
  A fusion attempt starts only after the controller claim; an already-started or completed pre-claim fusion
  cannot be wrapped into the later controller step. Receipt creation time alone is not sufficient.
- Reuse `execute_retrieval_fusion` and its existing child-ledger claim/close/fail and RRF validation.
  Sequence: validated controller claim -> fusion attempt/dispatch -> authenticated FusionReceipt ->
  prepare projection -> source bind -> existing structural bridge -> effect/transition/successor.
  Dense and lexical are not dispatched again.
- Controller claim admits at most one winner; duplicate/concurrent calls produce at most one fusion dispatch
  and one authentic successor. Repeated completed calls may return the same successor or reject consumption.
  Receipt/successor GC does not restore consumed execution rights while the relevant root remains live.
- Once claimed, any execution/binding/issuance failure consumes that controller step as failed and returns no
  partial successor or retriable permit. If child fusion executed or failed, its own once-only consumption
  remains intact. Existing sanitized fusion_contract_error behavior is preserved; no error FusionReceipt,
  failure effect, terminal result or revision3 is invented for a failed operation.

## Effect, ledger and revision3

- Applied/empty FusionReceipt is the sole source of effect outcome, call_performed, ordered evidence IDs and
  receipt hash. Effect uses action_kind=fuse, source_receipt_kind=fusion, step_index=3, stable execution
  identity, exact decision hash, first obligation and before-state. Existing schema requires call_performed=true
  for a successful pure fusion computation; this is not a model/provider call.
- Copy the revision2 ledger, set revision=3 and previous_ledger_sha256 to exact revision2, append precisely the
  fuse action SHA to consumed_action_sha256s, and set nonterminal_action_count=3.
  Preserve consumed_lane_keys unchanged (dense and lexical only), round indexes, unavailable actions,
  no-progress streaks and other obligations. Fusion is not a new retrieval lane or round.
- Transition3 binds exact transition2, decision/effect, before/after ledger hashes and stable root.
  after.state is before.state; semantic fingerprint is unchanged; operational_progress=true.
  Fusion evidence remains in its authenticated receipt/effect, without semantic state promotion.
- Successor authority retains stable initial root separately from immediate revision2 predecessor.
  Revision0/1/2/3 and prior decisions stay valid. Revision3 readback recursively revalidates both lane
  sources plus fusion source and all predecessor transitions. Extend existing bounded mint/readback seals;
  do not introduce a second registry/framework or public issuer.

## Acceptance and tests

- Fact and compare: all four applied/empty lane pairs, lexical-only rescue and both-empty.
  Exactly dense1/lexical1/fusion1; expected fused evidence/order/partition follows existing RRF authority.
  Both-empty yields empty effect, not confirmed absence, verified readiness or answerability.
- Budget2 and all authenticated error-derived abstain permits yield fusion0; budget3 accepts the selected fuse.
  Clone/mixed/wrong snapshot/action/dependency and prior source drift also yield fusion0.
- Exact chain/count/lane tuple/state preservation; private API containment; ordinal4 remains unsupported.
  Concurrent/duplicate, retained predecessor/source GC, no remint, source/effect/ledger/transition drift.
- Temporal fusion admission: reject pre-claim attempts/receipts and wrong-source binding; preserve existing
  lane epoch/claim tests and E0/public fusion behavior. Include failure after fusion before successor return,
  with no partial result and no retry/second computation.
- Run new focused tests and impacted existing controller history/transition plus fusion/E0/obligation suites.
  Main runs same-candidate isolated and full synthetic regression once at the final integration boundary.
  Fresh review covers product and contract changes before commit; no full suite per small internal leaf.

## Exclusions and next step

No real model/API/provider/Langfuse/VLM/clock/private-data execution. Baseline, corpus, gold, evaluation,
runtime config and dependencies remain unchanged. The separately authorized 131 retrieval comparison is
another task, not an execution permission for this batch. Do not overlap performance measurements with heavy
regression runs without coordination. No context/rerank/verify/semantic reducer/follow-up/deadline/terminal
or later compare execution. Parent c4.2.b/d2.x.b/Controller/E2E remain PARTIAL.
After this batch, select post-fusion eligibility/state handling through a separate complete Design.
