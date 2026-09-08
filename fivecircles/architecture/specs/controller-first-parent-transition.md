# EH2.6.c4.2.b.3 — First parent execution and revision4

Status: prospective bounded implementation contract, Cycle25, 2026-09-07.
Authority: bidfit-evidence-harness-v1-rc0.md section16.10; controller-next-decision.md
EH2.6.d2.x.b.2; controller-first-fusion-transition.md including its b.2 amendment.
This contract opens only the first selected parent execution after revision3. Earlier contracts,
receipts, same-candidate PASS and native failures retain their historical meanings.

## Goal, scope and private surface

Add private _execute_controller_first_parent_step(execution, decision, store, config, runtime)
returning the authentic revision4 HarnessExecution, and private
_require_controller_first_parent_transition(execution, store, config, runtime) returning its
exact effect and transition. No caller-provided obligation, batch, receipt, outcome, target, hash,
after-state or progress value. No public/package API addition.

Only fact/compare first-obligation applied fusion with its exact ordinal4 expand_parent permit
is admitted. No empty verify_slot execution, abstain execution, later parent/compare target,
bridge action execution, rerank, verifier, absence, derived semantic verification, ordinal5
decision, deadline or terminal execution. Controller/E2E and parent TODOs stay PARTIAL.

## Existing dependencies and exact admission

Reuse execution/decision/source-owner validators, retained revision3 fusion-state record,
revision2 lexical and revision1 dense predecessor records, existing semantic obligation factories,
complete target-context accumulator, source resolver, temporal claim fence, structural bridge,
effect and successor registries. Do not build a parallel authority framework.

Before claiming or issuing context, require exact revision3/count3, decision ordinal4, selected
expand_parent identity, first obligation key, remaining action budget, applied authenticated
FusionReceipt and the exact candidate state derived from that effect. Recover the original
RetrievalObligation and both applied/empty lane receipts from retained authorities, not SHA lookup.
All three receipts must share exact owner, obligation, round1, store/config/runtime. Preserve
dense provider-error plus diagnostic lexical ineligibility. Round cap remains pinned to1;
cap2, budget3, empty fusion and any wrong/nonselected action fail before child dispatch.

Derive target as the first seed of the complete existing bounded prefix:
sorted(candidate IDs)[:min(config context limit, owner final_evidence_budget, owner rerank_k,
candidate_count)]. This selects context, never reorders fusion/state candidates. Validate the
global compare plan and first-obligation query against their own original projections, without
equating their different fingerprints or reminting the compare retrieval tuple.

## Complete batch provenance, not single-seed authority

After the winning controller claim, obtain the existing base SemanticVerificationObligation from
issue_fact_semantic_verification_obligation or issue_compare_semantic_verification_obligation
using that same retained first RetrievalObligation and exact FusionReceipt. It is context
preparation authority only, not semantic verification or answerability. A previously authentic
cached base obligation may be retained; cloned, expired/tombstoned or cross-root obligations may
not be recreated to evade source lifetime. Retain the base obligation in the transition graph.

Call the existing _accumulate_controller_target_context for expand_parent and the selected seed.
It issues and validates BOTH complete parent and table/figure bridge batch tuples for the
bounded seed prefix, retaining original tuple/receipt identities and canonical seed/role order.
Do not slice/remake these tuples, manually mint a selected-only receipt, widen the prefix, or
replace the complete-context prerequisite with count/hash equality.

The accumulator's selected exact ParentContextReceipt is the only source consumed by this
Controller action. Complete sibling parent/bridge receipts are bounded store-backed preparation
materials, NOT additional Controller actions/effects, verifier-ready context, supporting evidence,
later-target permission or bridge execution transitions. No retriever/reranker/verifier/model/
clock is called. Preserve existing batch applied/empty bridge behavior without promoting it.
A valid selected parent receipt is applied; there is no invented empty/error parent receipt.

## Temporal source fence and once-only failure

Extend the existing shared monotonic source-attempt registry and atomic claim cutoff to the
exact parent batch issuer/minter/module/source-kind boundary. The parent attempt starts before
batch work and strictly after the winning claim; each parent receipt binds that real attempt.
The selected receipt must prove this temporal origin in addition to its complete batch authority.
Registering an old receipt at context selection time is forbidden. Existing lane/fusion admission
and module/code/default/closure integrity protections remain intact.

Previously started/completed parent batches or a cached pre-claim context cannot be retroactively
attached. Detect available consumed/batch status in preflight; a concurrent race after claim fails
closed and consumes the claim. Do not clear child histories or discard old valid receipts to retry.
Only parent_context becomes newly admissible to this Controller step; bridge_context remains
unadmitted as an executed Controller source.

One winner may perform at most one parent batch and one bridge preparation batch and issue one
effect/successor. Concurrent/repeated executions either return the same authentic successor or
reject consumed status without extra child work. Preserve child failure tombstones and shared
claim failure semantics. Once claimed, any issuance/binding/drift/transition-registration failure
returns no partial authentic successor and leaves a failed non-retriable step. Revoke partial
effect/transition authority using existing rollback; do not invalidate earlier accepted history.
Post-failure surviving preparation receipts cannot authorize another Controller execution.

## Effect, same-state transition and live readback

Bind action_kind=expand_parent, source_receipt_kind=parent_context, exact selected target,
first obligation and decision ordinal4 through the existing structural bridge. Derive outcome,
receipt SHA and parent receipt SHA tuple from the exact selected receipt. Existing parent
projection uses applied, ordered_evidence_ids=(), no absence and call_performed=true; the latter
means store-backed work, not provider/model use. Unselected batch receipts do not enter this
effect's parent/bridge receipt lists or promote evidence.

Use the EXACT same HarnessState object before/after, as section16.10 requires for parent context.
Preserve original/effect-bound state owner, candidate order, all sibling identities, coverage0.0,
open progress, in_progress and false terminal gates. Do not invoke fusion/semantic reducer.
Copy ledger with revision4, predecessor ledger hash, one appended selected action SHA and
nonterminal_action_count4. Preserve lane keys, round indexes, unavailable actions and every
no-progress streak. Parent is operational progress, not a fuse/verify no-progress checkpoint.

Transition4 seals exact transition3, decision/effect, before/after state/ledger and canonical
semantic progress fingerprints. Both fingerprints are equal: parent context is auxiliary and
this slice has issued no derived verifier-context evidence IDs. Provenance, receipt hashes,
counts and ordinal remain excluded from semantic fingerprint. Do not populate verifier context
from parent text or unselected bridge preparation. This statement describes current absence,
not future rerank readiness or a generic default for later stages.

Keep immediate revision3 predecessor and initial root separately, with all old executions,
decisions, three source receipts, the base semantic obligation, complete context tuple graph,
selected context and effect live-authentic. Readback revalidates this graph and source bindings;
serialized fields/counts alone never authorize it. Public execution validation can validate this
exact revision4 successor, but public initial-root mint cannot recreate it. Old readers keep their
revision-specific boundaries. Decision issuance for revision4/ordinal5 remains unsupported.
GC cannot remint consumed steps while their governing root lives; passive cleanup must preserve
existing lifetime rules and avoid callback-driven authority repair.

## Acceptance and one implementation batch

Synthetic fact and first compare end-to-end dense -> lexical -> fusion/state -> ordinal4 ->
parent -> revision4 cover applied/applied, dense-only and lexical-rescue candidates; both-empty
and error/budget permit refusals issue zero context. Include multiple seeds and table/figure
linked/unlinked materials so complete batch identity/order versus selected-only effect is proven.
Test owner/config bounded target, mismatched target/source/query/owner/dependencies, prestarted
and precompleted batch rejection, cached context rejection, temporal race, concurrent one winner,
GC/remint, registration failure/no retry, all old readbacks and zero extra provider/model/clock
work. Actual call counters must distinguish complete preparation batches from one Controller
effect. Preserve all existing context/rerank/source/decision tests and public non-authority.

Implement and focus-test as one cohesive slice. Freeze once for adjacent plus isolated and full
integration evidence and fresh deep cross-module review. No full suite per internal leaf.
No performance/profile, GPU, GCP, baseline/corpus/gold/config/dependency change is included.
Validation-only frozen analytics location is governed by the accompanying Design directive,
not a durable product locator change. Any authority or batch semantic conflict requires QUESTION
before broadening. No historical accepted contract or evidence is rewritten.
