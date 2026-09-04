# Orchestration module contract

`midprojectrag.orchestration` owns deterministic planning and bounded execution state.

EH2.1 exposes immutable `QueryPlan` and versioned `RuleRegistry` contracts only. The
registry is the single source for query-type budgets and generic routing signals.
Its canonical configuration hash must be bound to each plan. Unknown types, schema
drift, forged hashes, duplicate slots, and slots outside the resolved document scope
fail closed.

This package may depend on public runtime, evidence, retrieval, and specialist APIs.
It must never import evaluation cases, qrels, expected answers, private model details,
or gold document IDs. EH2.2 routing accepts only `RuntimeRequest` plus a content-hashed
production `PlanningCatalog`; the executable planner pins the approved registry SHA,
seals and revalidates catalog construction, enforces exact JSON array shapes, and records
production/synthetic, source, rule, and scope provenance. Ambiguous entity resolution
and explicit empty scope fail closed.

EH2.3 accepts follow-up authority only from the most recent assistant turn's exact
document/evidence citation arrays after resolving them against the active immutable
`EvidenceStore`. Explicit/entity scope is intersected with those citations and an empty
intersection stays empty. Primary retrieval is scope- and bundle-bound. A global lookup
may run once only when the original request was unfiltered, the option and plan both
authorize it, and a sealed `PrimaryEvidenceProgress` derived from verified primary
evidence is insufficient. Candidate count and caller-provided booleans are never
sufficiency evidence; primary and fallback results remain separate. Slot state and the
bounded controller remain later leaves.

EH2.4 uses separate compare-slot contracts; it does not reuse
`PrimaryEvidenceProgress`, whose follow-up semantics cannot represent candidate,
confirmed absence, and contradictory evidence independently. A compare binding must
replay the supplied runtime request through the same deterministic planner before it
can enrich a plan. The sealed binding records routing, catalog, compare-registry,
the complete canonical planning result/trace, planner execution kind, catalog source
kind/source hash, base/effective-plan, and evidence-bundle identities. Runtime entrypoints
accept only the unchanged `BoundCompare` object identity issued by that factory; rebuilding
or mutating an equal-looking object does not carry execution authority. Only an explicit multi-document
scope or at least two independently resolved single-document business entities may
become compare targets. A versioned generic field registry creates the complete
document-major Cartesian slot matrix; it never reads evaluator fields or inserts
unstated default axes. Explicit scope cannot silently discard an additional business
target named in the question. Field intent is positive-only: negated/excluded signals
are not selected, `만` is boundary-aware, and any unconsumed named target or requested
axis makes the binding unresolved instead of producing a partial matrix. Only the
registry-owned positive field phrase is sent to each singleton-scoped slot search.

Compare coverage is derived from immutable per-slot records bound to child search
results in the same `EvidenceStore`. Search receipts seal a field-specific Korean query,
the singleton document scope, a deterministic slot share of the query-level plan budgets,
slot ordinal, action/profile, result lane, and source-trace hash. Production validation
runs before query egress and requires loader-issued dense/lexical attestations plus a
factory-issued hybrid binding, matching store rows and artifact identities. Exact class
shape alone is not authority. Replay validates the complete deterministic receipt envelope
before re-execution, and canonical JSON comparison rejects bool/int and int/float type drift.
Retry and cumulative execution accounting remain EH2.6. Verification receipts
replay the fixed field rule and may only report `field_relevance_only` matches from their
own search receipt. A signal hit is not a verified claim/value and cannot complete a slot;
typed semantic support receipts remain a later leaf.
Raw `SearchResult` and caller-provided verified-ID maps are not authority. Missing and
contradiction states require bounded reason codes; raw candidate counts are not evidence
of absence. Untyped contradiction claims are rejected until a typed value receipt exists.
`CompareCoverage` itself is factory-identity-bound: validation recursively checks every slot
and document, re-derives every count, ratio, covered-document set, answerability, and stop flag,
and rejects raw or post-issuance drift even if public payload hashes were recomputed.
Normal stop requires
every slot in every required document to be verified or confirmed missing and forbids
confirmed contradictions. EH2.4 records provisional missing observations but cannot
mint an absence confirmation: they remain open until EH2.6 binds a bounded action
receipt. EH2.5 may adapt these records into Belief/Progress, but
downstream compare code must accept the sealed compare binding rather than a bare plan.

EH2.5 adds only a pure state/action projection. `Belief`, `Progress`, and `HarnessState`
must be reconstructed from an identity-authorized `BoundCompare` + `CompareCoverage` or
an identity-authorized `BoundFollowup` + primary progress + retrieval outcome. They bind
request, plan, config, store, source-receipt, scope, entities/constraints, and ordered
obligation/evidence identities without copying question text. Follow-up uses the reserved
`$answer_support` obligation so an empty plan slot list cannot become vacuous completion;
empty or unavailable fallback output remains provisional, not confirmed absence.

Actions are closed identifiers, never caller-supplied queries or scopes. Retrieval/fusion/
rerank/verify actions target one obligation, expansion/bridge actions additionally target
an evidence ID already present in that obligation's candidate set, and terminal actions have
no target. EH2.5 derives a deterministic allowed-action order and a hash-chained
`ActionDecisionTrace`; it performs no retrieval, verification, reranking, model call, retry,
deadline accounting, or absence confirmation. `fuse` remains a declared type but is not
eligible until EH2.6 has a lane-execution ledger. Runtime use and persisted replay require
factory-issued object identity plus canonical full-payload reconstruction. Gold/evaluator
fields are not accepted by any state or action API.

EH2.5 has no state reducer, transition, or action-effect receipt; all three belong to EH2.6.
Its exact terminal gates are source-derived: compare copies `normal_stop_allowed` and
`abstain_required` from the sealed `CompareCoverage`; follow-up permits normal stop only when
the sealed primary progress is sufficient and the complete outcome chain is valid. EH2.5
cannot create confirmed absence, so every other insufficient follow-up remains provisional/
open rather than forced abstention. Normal-stop state allows only `stop`; forced-abstention
state allows only `abstain`; otherwise exactly one untargeted `abstain` follows the eligible
nonterminal actions.

Allowed actions are ordered first by the sealed canonical obligation order and then by
`retrieve_dense`, `retrieve_lexical`, `expand_parent`, `bridge_table`, `bridge_figure`,
`rerank`, `verify_slot`; bridge/expand targets are ordered by evidence ID. Compare unsearched
or provisional-missing obligations allow the two retrieval actions. Compare candidates and
follow-up candidates allow eligible expansion/bridges followed by rerank and verify. A
follow-up provisional-missing obligation allows no new retrieval because EH2.3 already
finalized its primary and optional fallback. Verified/confirmed-missing obligations allow no
nonterminal action and contradicted state enters the global abstention gate. A parent expansion
is eligible only when the candidate's `parent_id` resolves in the sealed store. Table and
figure bridges are eligible only when the store itself derives at least one linked
`table_row_group` or `figure_object` respectively through `store.bridge`; callers cannot
supply kind or lineage. The deterministic decision selects the first allowed action.

EH2.6 adds a separate ledger-aware execution chain; EH2.5 `ActionDecisionTrace` remains
a single-state preview and must not be reused across changed states. A controller decision
binds the exact state and execution ledger and links to the previous transition. EH2.3 and
EH2.4 receipts are immutable audit roots. EH2.3 primary progress is a compatibility receipt
whose caller-supplied candidate IDs and config hash are not terminal semantic authority.
EH2.5 follow-up verified/stop projection therefore cannot enter E1 directly. Every E1 belief
change must be authorized by an exact action-effect receipt and reducer-issued transition.

E1 supports fact, compare, and follow-up. `bind_fact` issues factory-only `BoundFact` authority
after exact request/planner/registry/catalog/store types and live payloads pass validation and
the supplied plan exactly matches a fresh deterministic replay. Restricted document IDs must
exist in the catalog universe and store; empty/unresolved/metadata-dependent bindings remain
not-ready. Only a ready binding starts one unsearched `$answer_support` obligation. Compare and
fact run dense and lexical lanes independently and fuse only two
same-round receipts with matching query, scope, store, and runtime identities. A hybrid
one-shot call must not be mislabeled as one lane. Follow-up consumes its already finalized
primary/optional-fallback candidates and makes zero additional retrieval calls. Unverified
follow-up slots receive only candidates whose evidence document matches the slot document;
all EH2.3 claimed verified IDs are downgraded to candidates until a new runtime-bound semantic
receipt verifies them. Fact and follow-up metadata predicates fail closed until EH3.1 provides
an exact filtered-scope receipt. Restricted fact IDs must exist in both the sealed catalog
universe and exact live, canonically rehashed evidence store.

The v1 controller permits one retrieval round per obligation because no distinct-query
rewrite policy exists. Its immutable config bounds nonterminal actions, no-progress, and an
integer-millisecond monotonic-clock deadline; terminal receipts do not consume that budget.
Effects are closed, sanitize provider failures, and cannot turn late, unavailable,
or errored work into evidence. Parent expansion is verifier context only; bridges add only
store-derived linked evidence; reranking is a subset/permutation; semantic verification can
promote only supplied evidence. Compare contradiction requires typed canonical values with
independent support. Field relevance and caller booleans/ID maps are not semantic authority.
The runtime binding retains exact hybrid/dense/lexical and verifier/optional-reranker object
identities, classes, attestations/config hashes, capabilities, and method-override absence.
These checks happen before query derivation or egress, and approved class methods are invoked
directly. Only executor code can mint semantic/rerank receipts from adapter output; synthetic
adapters are test-only and cannot authorize production sources.

EH2.6.b2 implements this boundary as factory-issued `HarnessExecutionConfig` and
`HarnessRuntimeBinding`. The config is a closed, hash-bound `e0_once|e1_bounded` snapshot with
the v1 one-round rule, `rrf_k=60`, positive action/no-progress/context-target/deadline limits,
and exact JSON replay. Production binding accepts only loader-attested KURE+Kiwi+RRF objects,
the internal monotonic clock, and currently unavailable verifier/reranker capabilities;
synthetic adapters and clocks are available only through `HarnessRuntimeBinding.for_test`.
Bind, validate, serialize, dense/lexical/fusion preflight, and evidence-store snapshot entry
gates authenticate their complete issued callable/class/registry surface before traversal and
make zero retriever, tokenizer, model, verifier, reranker, or clock calls.

EH2.6.b3 issues `RetrievalObligation` only from exact live `BoundFact`/`BoundCompare` owner
authority. Raw query and evaluator data remain private; public payloads retain only their hashes,
source receipt, scope, budgets, and exact store/config/runtime bindings. One issuance owns one
hash-chained ledger whose canonical global order is dense then lexical for each obligation. A lane
can be claimed and closed once. Closing mints a single-use transition permit, and closure-sealed
executor methods reject direct ledger mutation, forged permits, global-spoofed caller checks, and
receipt reminting without the public lane executor. Typed provider and pre/post-call contract
failures preserve truthful `call_performed` state. A dense provider failure permits only the
untouched lexical diagnostic lane, after which execution terminates without fusion. Stable text
anchors carry both store-local evidence-locator hashes and chunk-invariant source-block join
hashes. Issuance, obligation, ledger, permit, and receipt authorities use weak cleanup with no
request/query retention after the request graph is collected. Fusion and the E0 aggregate are
implemented by EH2.6.b4.

EH2.6.b4 adds factory-issued `FusionReceipt`, `E0ObligationResult`, and `E0ControlReceipt` through
public `execute_*`/`validate_*` boundaries in `execution_contracts.py`. Fusion is checkpoint ordinal
four because the evaluation stage contract reserves ordinal three for an optional visual lane. It
accepts only the exact live normal dense/lexical receipts for one obligation and validates the RRF
union, score/order, scope, text-evidence anchors, and lane partitions before projecting a trace-free
receipt. A closure-private, ledger-lifetime fusion claim rejects replay, concurrency, skipped fusion,
and copied-globals executor clones without changing the b3 lane ledger retrospectively. Completion
is mirrored into two closure-private maps as the same immutable tuple object, so deleting the receipt
or mutating only the visible progress cell cannot reopen a live ledger pair. Runtime dependency pins
also bind closure-cell contents, not only code/default/global identities.

The E0 entry requires `mode=e0_once`, validates the complete canonical obligation set before any
provider call, atomically claims the run, and executes dense, lexical, then fusion for each obligation
before moving to the next. While that claim is pending, child lane/fusion entry accepts only the exact
E0 executor caller. It captures child executors and validators at entry, revalidates the dependency
gate after every provider return, and accepts only exact typed receipts that pass their public
validators. A provider-time global swap or a lane advance before the preceding fusion therefore
fails closed without an aggregate receipt. Per-obligation results retain only child receipt hashes and a closed
`retrieved|empty|unavailable|error` status; untouched work after an execution error is explicitly
`error/execution_terminated_before_obligation`. Aggregate precedence is error, unavailable, all-empty,
then retrieved, and `execution_complete` is true only for retrieved/empty-only runs. The payload is a
state-free retrieval control checkpoint: it neither claims semantic readiness nor accepts or stores
gold, qrels, expected answers, raw queries, source text, or provider traces.
An E1 compare seed must be all-unsearched; already hybrid-searched EH2.4 coverage cannot be
relabeled as independent lane execution. Once all approved retrieval paths close with no
candidates, controller-only `verify_slot` performs a zero-provider exhaustion check that may
mint absence. Fact metadata predicates remain not-ready until EH3.1 supplies a filtered-scope
receipt.
Every attempted lane outcome consumes that obligation/round/lane exactly once with no v1
automatic retry. Deadline and integrity failure terminate immediately. An ordinary dense
provider failure may be followed by the untouched lexical lane once, but it cannot authorize
fusion and the run then ends with a sanitized error.

Confirmed absence means only that all approved actions for one sealed query/scope/budget were
exhausted without support. It cannot be minted from timeout, provider error, unavailable
capability, unresolved scope, or an empty top-k alone. Reducer transitions are monotonic and
change at most one obligation. Lane, parent-context, and terminal effects retain the exact same
state object; only a semantic state change mints a new state whose source receipt is the effect.
No-progress uses a semantic fingerprint that excludes hashes, ordinals, time, and counters;
required lane prerequisites are operational progress and do not increment its streak. Only
fuse/verify checkpoints with unchanged semantic state and verifier context increment it.
Only all-verified state is ready; mixed verified and confirmed
missing is partial abstention, all confirmed missing or contradiction is abstention. Replay
must use exact live source/config/store/effect authority and perform zero provider, retriever,
verifier, reranker, or clock calls. E0 is a one-shot retrieval control receipt, not semantic
readiness; generation, analytics/list execution, E2 policy, learning, and query rewrite remain
outside EH2.6. Execution payloads use ordered SHA references and bounded summaries rather than
recursively nesting prior receipts; the top-level receipt bundle carries each payload once.
Raw persisted JSON can be structurally audited but cannot remint provider-execution authority.
Late raw provider output is discarded before parsing or projection. Optional bridge/reranker
unavailability may be skipped once; required semantic-verifier unavailability terminates with
a capability-gap reason. Missing abstention is a run result, not the contradiction-only
`Progress.abstain_required` gate.

EH2.6 defines a separate factory-issued `ControllerAction` with the same closed kind/target
shape as EH2.5 actions. Context actions target only a config-bounded prefix of immutable
retrieval seed candidates and never bridge-added evidence, preventing graph recursion and
action explosion. Owner modules expose sealed `RetrievalObligation` projections and the
retrieval package exposes independent lane/fusion execution. The controller must not import
another module's underscore helpers or factory tokens. Fact binding owns fact authority,
the compare owner derives slot query/budget, harness state owns fact initialization and the safe
E1 follow-up projection, and execution-contract/effect/reducer/controller modules retain their
single responsibilities.

E0 preserves ordered per-obligation statuses and aggregate precedence of error, unavailable,
all-empty, then retrieved. It records each status partition and reports execution complete only
when every obligation boundedly ended as retrieved or empty; mixed compare slots are never
collapsed into an unqualified success.

EH2.6.b5 is a focused acceptance gate over the b3/b4 production surface, not a new execution layer.
It fixes four distinctions: a normal empty dense lane can be rescued by a valid lexical-only fusion;
an all-empty fact E0 is retrieval-complete but carries no semantic-ready state; pre-call contract
rejection performs no provider side effect and produces no lexical/fusion child; and lexical work
after a dense provider error is diagnostic only and never authorizes fusion.
