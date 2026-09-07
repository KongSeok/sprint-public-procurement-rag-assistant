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

## EH2.6.c4.2.b.2 — Effect-bound first-fusion state reduction (2026-09-07)

### Prospective amendment and bounded goal

The preceding c4.2.b.1 sections describe the accepted dispatch-only revision at commit
a37562a774ea72281950102416c0b71f3a00e6fa and contract SHA256
088d1280b7ccae54370aeb5d5fbcb648d4eea857ee8b1663e8d228a8efd06d7c.
This b.2 amendment supersedes ONLY their state-stable revision3 and equal-fingerprint rules for
future first-fusion issuance. It completes the existing §16.10 fusion reducer prerequisite before ordinal4.
It does not rewrite historical artifacts, replay old dispatch, mutate any existing state or migrate persisted
receipts into live authority. Revision0/1/2 issuance, inputs and previous decisions remain unchanged.

The same private first-fusion entrypoint consumes the same selected revision2/ordinal3 fuse once.
After its exact effect is bound, reduce the first obligation and seal the resulting state in the same
revision3 transition. No extra action, decision, retrieval, fusion computation or revision4 is created.

### Exact effect-bound state ownership

- State creation belongs to harness_state.py; effect/claim/source execution authority stays in
  execution_contracts.py. Use a bounded sealed owner bridge consistent with existing module ownership.
  Do not share factory tokens, accept caller-chosen candidate IDs, or turn the structural ActionEffectReceipt
  validator into a live mint permit. Do not introduce a second generic controller/authority framework.
- The only mint input is the exact live before-state and the bound first-fusion effect authenticated by its
  existing controller claim and FusionReceipt/transition history, with exact store/config/runtime/root.
  Validate action=fuse, step3, first obligation, exact before-state SHA, applied|empty outcome and source evidence.
- New state provenance binds the exact effect, and belief.source_receipt_sha256 equals its effect_sha256
  as required by §16.10. Retain and revalidate the original root owner, original source receipts and before-state
  separately; do not pretend the effect is a planner trace or CompareCoverage.
- Public state validation and execution readback must recognize the effect-derived state through live authority.
  Serialized matching effect hashes, cloned values, arbitrary after-state/entry tuples and loose callback inputs
  cannot create or validate a controller state. Pin any cross-module bridge/callback dependencies.
- Retain authenticated predecessors and three sources while a successor remains live; avoid a circular
  requirement for an already-issued transition to mint the state that transition itself must seal.
  Mint after effect binding and before transition completion. Post-bind reduction/registration failure consumes
  the existing claim, exposes no usable partial successor or orphan authorizing state, and cannot rerun fusion.

### Deterministic first-obligation projection

Precondition: exact revision2 first-obligation fact/compare state is unsearched with no candidates or verified IDs.
All other obligations remain unsearched and untouched.

| Exact fusion effect | First entry stage | candidate_evidence_ids | verified_evidence_ids |
| --- | --- | --- | --- |
| applied | candidate | exact ordered fusion effect evidence IDs | empty |
| empty | provisional_missing | empty | empty |

Require applied to be nonempty and empty to have no candidates, using live source validation. Preserve source
scope, binding, query/plan metadata and obligation ordering. Preserve unchanged sibling entry objects.
The new Belief/Progress/State are owner-issued, not mutable patches to previous objects.

Progress is recomputed from the resulting entry map: all obligations remain open, verified/confirmed-missing/
contradicted remain empty, and only an empty first obligation enters provisional_missing_obligation_keys.
For this initial retrieval slice, slot_coverage_ratio remains 0.0, answerability=in_progress,
normal_stop_allowed=false and abstain_required=false. Candidate retrieval is not semantic support.
No absence receipt, context/rerank/verifier capability result, verified/confirmed-missing/ready/terminal state
is inferred, including both-empty and lexical-only rescue.

### Transition and no-progress checkpoint

- Preserve stable execution identity and initial_state, immediate revision2 predecessor, ordinal3 effect,
  previous transition2, action count3 and exactly the existing dense/lexical consumed lanes.
  No new action budget consumption, round or unavailable capability entry.
- Revision3 current state is the exact new effect-derived state; before/after state hashes and semantic
  fingerprints are separately computed and sealed in the existing transition. Effect.before_state stays revision2.
- Canonical semantic fingerprint contains ordered obligations with stage, candidate IDs, verified IDs and
  actual verifier-context IDs; it excludes provenance/effect/receipt hashes, ordinal, timestamps and counters.
  This slice has authenticated initial no-context history and admits no context-producing actions, so the
  before/after context ID sets are empty by that bounded history, not by a general capability/default assumption.
  Unsupported context-bearing histories are rejected rather than erased.
- Apply §16.10 at the first-obligation fuse checkpoint: if semantic fingerprint changes reset that obligation's
  no-progress streak to 0; if neither semantic state nor verifier-context changes increment its streak by 1.
  Preserve every sibling streak. Under this slice's valid inputs, unsearched -> candidate/provisional_missing
  always changes the fingerprint, hence streak remains 0. Do not widen inputs or fabricate a live no-change case
  just to exercise a branch reserved for future checkpoints. Provenance-only hash changes are not semantic progress.
- Initial/lexical transitions remain same-state and retain their existing fingerprint/no-progress behavior.
  Revision3 readback validates the effect-derived state and its exact transition; ordinal4 remains unsupported.

### Acceptance and integration

- Fact/compare four applied/empty lane combinations, rescue and both-empty, exact candidate order and sibling
  preservation; open/in_progress/nonterminal state, no semantic support or confirmed absence.
- Before-state and revision0/1/2/decisions unchanged; new state hashes/fingerprint/effect provenance bound;
  all source chains and derived-state validation survive required GC, with no redispatch or remint.
- Wrong/clone/mixed effect/state/store/root/candidate tuple, effect/source drift and direct unauthorized state
  creation fail closed. Reduction/registration failure after actual fusion yields no partial valid result or retry.
- Adapt existing first-fusion tests only where their b.1 same-state assertions are prospectively superseded.
  Keep temporal, exact dispatch-count, concurrency, error/budget, private-surface and predecessor regressions.
- Focused reducer plus impacted state/controller/fusion tests; main performs final frozen-candidate isolated/full
  checks once. Fresh deep review includes this changed state-owner boundary and all behavior contracts.
  No performance threshold/profiling/optimization is added.

### Explicit remaining scope

Ordinal4 selection and later context/rerank/verify execution require another Design after this state prerequisite.
No follow-up, later compare obligation, sibling tuple remint, deadline, terminal result or public start/step/run.
All nine first-fuse REVIEW constraints remain applicable, with state reduction explicitly selected by this b.2
directive. DIAG131 and its inputs/artifacts/communications remain separately owned. No real provider/model/API/
Langfuse/VLM/clock/private data, baseline/gold/evaluation/runtime configuration or dependency changes.
