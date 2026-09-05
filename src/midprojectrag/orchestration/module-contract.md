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

`build_e1_followup_harness_state` is the only EH2.6.c1 initial projection boundary. It accepts
the exact `BoundFollowup` and already finalized `FollowupRetrievalOutcome`, validates exact store
identity plus registry-config/policy-SHA value authority, and never accepts a retriever, verifier, runtime, evaluator, or
gold input. Primary candidates precede optional-fallback candidates with first-seen dedupe;
`$answer_support` receives the complete candidate sequence and each actual required slot receives
only candidates whose sealed-store `doc_id` matches the slot. Every initial obligation remains
open with zero verified coverage. A metadata predicate requires the future EH3.1 filtered-scope
receipt and therefore fails closed here. The EH2.5 compatibility builder and generic replay keep
their existing semantics; controller start must rebuild E1 state through this dedicated boundary,
and persisted E1 replay remains an EH2.6.d5 responsibility.

Runtime authority here is an integrity boundary, not a Python sandbox. It must reject public-input
forgery, equal-looking clones, post-issuance object drift, mutable public dependency aliases, and a
single private registry/pin drift. Code already able to rewrite multiple coordinated private module
registries or closure cells in-process is equivalent to patching the implementation and is outside
this contract; deployment/process isolation and repository artifact verification own that threat.
This limit must be stated in reviews so same-process arbitrary-code mutation is not misreported as a
finite DTO hardening requirement.

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

EH2.6.c2 splits semantic verification ownership without exposing a verifier bridge. `execution_contracts.py`
owns factory-only semantic obligations, the exact runtime call, local at-most-once history, and authoritative
receipts. `action_effects.py` owns the closed typed-value schema and pure raw-result normalization; it does not
import execution private authority or receive a source owner, runtime, verifier, raw query, or gold/evaluator
input. The execution boundary pins the exact normalizer implementation and never returns the raw adapter result.

Fact and compare semantic obligations are derived only from one exact `RetrievalObligation` plus its same-round
dense, lexical, and nonempty fusion receipts. Follow-up obligations are derived only from an exact
`BoundFollowup` and finalized outcome after rebuilding and validating the c1 safe projection, selecting
`$answer_support` or an actual required slot. Public factories do not accept query, field, evidence IDs,
disposition, values, verifier output, or gold. The immutable public obligation stores hashes, the owner-derived
optional compare field, ordered supplied roles/IDs/anchors, and no evidence text. Candidate then bridge then
context is the only supply order; c2 initially issues candidate-only obligations, and context cannot be promoted.

The verifier protocol is one exact declared `verify(self, request)` method with no defaults, varargs, keyword-only
arguments, or instance override. Its factory-only private request carries the raw owner query and an ID-less content
projection of exact owner-ordered, contiguously indexed Evidence objects and cannot serialize. The exact raw dict keys are `schema_version`,
`disposition`, `support_indexes`, and `values`; each value has only `value_type`, `canonical_value`, and
`support_indexes`. The adapter never receives or returns evidence IDs; only the executor maps indexes back to
owner-issued IDs. Adapters return only `supported|unsupported|contradicted`; runtime unavailable alone creates an
`unavailable` zero-call receipt. Values use closed `text|krw_amount|kst_datetime|duration|boolean|number` canonical
strings, and one field-approved type: budget=krw_amount, duration=duration, deadline=kst_datetime,
joint_contract/subcontract=boolean, all other fields=text. Fieldless support/conflict has no values and uses only
nonempty disposition indexes. Field-bearing support has exactly one value whose nonempty support union equals
verified IDs; contradiction requires at least two distinct values of the approved type with pairwise-disjoint
nonempty supports whose union equals contradicted IDs. Unsupported and unavailable carry no IDs or values. Only
candidate/bridge supplied evidence is promotable.

Every available execution is claimed once per exact live semantic obligation. ABI or identity preflight rejection
dispatches zero calls and is not consumed as an execution attempt. After one direct class-method call, exact source/prerequisite/store/config/runtime dependencies are
revalidated before normalization or mint. Provider, malformed-result, and post-call drift failures are sanitized,
consume the local claim, and cannot be retried; concurrency has one winner and completion history outlives receipt
GC while the source authority remains live. c2 receipts are state-free: c3 owns effect/absence projection and d
owns global action budgets, deadline permits, transition order, and terminal semantics.

EH2.6.c3 closes source receipts before final effects. A parent context is a `ProvenanceParent`, not an Evidence;
its public receipt binds parent ID, seed Evidence ID/anchor, kind/doc and content/locator hashes while private
authority retains the exact parent object and text. It must never invent an evidence ID or become support/citation.
Bridge receipts are issued for each table/figure attempt over the config-bounded, evidence-ID-sorted immutable seed
prefix and contain only exact `store.bridge` linked Evidence IDs/anchors or an explicit empty outcome. Caller target
IDs are not accepted and bridge-added Evidence never becomes a recursive context seed.

Reranking receives an ID-less contiguous projection of owner-derived candidate plus bridge Evidence and returns
only a unique nonempty index subsequence/permutation. The executor maps indexes to exact IDs, validates the runtime
again after the call, and keeps provider text private. Only a derived semantic obligation may add these bridge
Evidence and private parent contexts; parent items are auxiliary verifier context without support indexes. The
closed `ActionEffectReceipt` DTO/validator is defined in c3, but minting execution/step/decision/action/before-state
bindings stays fail-closed until the EH2.6.d2 `ControllerDecisionReceipt` permit exists. The EH2.5 preview trace is
never substituted for that permit. Consequently c4 reducer/effect mint is dependency-blocked by d1/d2, not by an
untrusted temporary decision field.
The c3.4 type lives in `action_effects.py` as a schema-only value object. Its exact closed payload binds execution,
step, controller decision, action/target, before-state, source kind and typed source-receipt hash, sanitized outcome,
ordered evidence IDs, parent/bridge receipt hashes, optional absence hash, call status, and the canonical effect hash.
Stable anchors and store/config/runtime hashes remain single-sourced in the exact typed source receipt and are not
duplicated in the effect. The package exports only `ActionEffectReceipt` and the pure
`validate_action_effect_receipt` shape/hash validator. That validator is explicitly not runtime authority and cannot
authorize a reducer, transition, terminal answer, or citation. There is no public create/issue/mint/execute/from-dict
surface before d2; the module-private token constructor exists only for schema fixtures and the future c4 internal
issuer after an exact d2 permit. `_create` registers no authority and is not a Python security boundary; c4 must use a
separate exact decision-permit authority and dereference the live source receipt before reduction.
Controller-decision and primary absence sources carry empty parent/bridge context tuples. Post-call rerank or verify
failure provenance belongs to the later live source-authority check rather than this structural DTO.
C3.5 is a negative non-authority gate, not a provisional issuer. Until d2/c4, the package has no effect consumer other
than the pure structural validator; it accepts no source receipt, store, config, runtime, or decision-permit argument.
Equal-hash structural recreations remain distinct non-authorizing values and register no replay claim. Their `repr`
must not emit payload fields, while the exact allowlisted `to_dict` adds no dedicated raw query, text/value, provider
detail, gold/qrels, path/key, transition, answer/citation, readiness, or authority field. Structural ID strings are not
secret-scanned and must be rebound to live provenance by c4. C3.5 also regresses the existing seven source validators'
exact receipt/dependency authority and provider-free mixed-graph rejection. Future effect-source dereference, exact
decision permit, one-step issuance, and effect replay authority remain exclusively d2/c4 responsibilities.
EH2.6.d1 adds the controller-level `ExecutionLedger` and `HarnessExecution` aggregate in
`execution_contracts.py`; it does not expose or rename b3's private `_RetrievalExecutionLedger`.
The controller ledger is an immutable snapshot whose canonical obligation order comes from the exact initial
`HarnessState`. It seals aligned retrieval-round and no-progress counters plus ordered, unique action, lane, and
unavailable-capability consumption. D1 can issue only the revision-zero snapshot: every counter is zero, every
consumption tuple is empty, and `previous_ledger_sha256` is null. Authenticated advancement remains c4 work.

`issue_harness_execution` accepts only an exact live state/store/config/runtime graph, derives source binding and
source-receipt hashes from that state, requires `e1_bounded`, and calls no clock, retriever, verifier, reranker,
model, or provider. The aggregate binds one stable execution identity, exact initial/current state and ledger
identities, and a null last transition at step zero. Repeated live issuance is idempotent and concurrent callers
share one winner; an equal-payload rebuilt state, mixed config/runtime/store, aggregate or nested clone, post-issue
drift, and a reissue after aggregate collection while the original state root remains live fail closed. Public
serialization contains only hashes, counters, and closed keys, never recursive state text or provider data.
The stable root is `execution_identity_sha256`; the changing aggregate digest is
`execution_snapshot_sha256`. Future `ActionEffectReceipt.execution_sha256` must bind the former, never the
snapshot digest.
Constructors, copy/deepcopy, pickle, and `from_dict` are unavailable. D1 exports no decision, effect issuer,
reducer, transition, consume, advance, start/step/run, or terminal authority: d2 owns the state+ledger decision
permit, c4 owns live effect mint and authenticated ledger/state transition, and d3-d5 own execution and replay.
EH2.6.d2 introduces `ControllerAction` and `ControllerDecisionReceipt`; EH2.5 `HarnessAction|ActionDecisionTrace`
stay state-only previews and are exact-type rejected as effect permits. The first d2.i slice accepts only an exact
live revision-zero execution whose source is fact or compare and whose obligations are all unsearched. It derives
obligation-major dense→lexical actions plus one untargeted abstain and selects the first. Follow-up, candidate, and
nonzero snapshots fail closed until c4.0 supplies source/outcome authority. No caller action, query, scope,
evidence ID, previous chain, counter, capability, gold, or qrels field is accepted.

`ControllerAction` binds its closed kind/target and policy to the stable execution identity; its stable action hash
does not include a snapshot/state hash so a later ledger can filter the same action. `ControllerDecisionReceipt`
binds stable execution identity, current snapshot/state/ledger SHA and revision, owner-derived previous transition,
ordinal=`step_index+1`, exact actions/hash, selected-first action, reason, and its own hash. Same-snapshot issuance is
same-object idempotent and single-winner. Clone, nested action/tuple replacement, mixed/rebuilt dependencies,
post-issue drift, or GC/remint while the execution root is live fail closed. Serialization contains no recursive
state/ledger, effect, answer, or citation.

D2 remains partial after d2.i. Ledger lane keys do not distinguish normal outcomes from provider/contract/deadline
failures, and the aggregate cannot yet recover `Bound*`, follow-up outcome, or owner budget. C4.0 must add opaque
source-owner authority, ordered exact outcome/transition history, one-action per-target context issuance, and a
formal structural-effect creation bridge. Only then may d2.x filter consumed stable actions/lanes and authorize
fuse/context. An untried unavailable capability remains selectable once so c4 can record a zero-call unavailable
effect; only its ledger-recorded stable action is removed later. D2.i does not mint effects, claim/consume a permit,
advance a ledger, reduce state, call a provider/clock, or expose start/step/run.

C4.0 is implemented as five ordered leaves: source-owner authority, typed source/outcome resolution, one-step
claim/history, per-target context issuance with a canonical batch accumulator, and a closure-private structural
effect bridge plus adversarial gate. The source-owner leaf captures the exact `BoundFact|BoundCompare|BoundFollowup`
and compare coverage or follow-up outcome/progress/registry/policy at state creation. It changes no public state or
execution payload/signature; an execution inherits the owner only through exact initial-state identity. An equal hash
from another root, retroactive attachment, compatibility follow-up promotion, or caller-supplied source/hash is not
authority. C4.0 itself makes zero provider/clock calls and cannot mint a live effect, advance the ledger, reduce
state, or produce a transition.
C4.0.a removes source inputs from the raw state factory and atomically seals state creation plus owner registration
behind a closure-held boundary. Registrar/reader module aliases are deleted after initialization; an exact-identity
owner-to-origin-state mirror and owner-lifetime tombstone reject reuse by any other root, including equal hashes.
C4.0.b adds one module-private typed resolver over lane, fusion, parent, bridge, rerank, semantic, absence, and
controller-decision receipts. Its caller supplies only the exact execution, decision, receipt, store, config, and
runtime graph. Source kind, native/effect outcome, evidence/context/absence IDs, call status, and hashes are derived
only after the exact decision permit, inherited source owner, receipt authority, recovered prerequisites, and the
existing live validator all agree with the selected action's kind, obligation, target, and root identity. The result
is an immutable non-serializable projection retaining exact object identities; it is not exported and grants no
effect, claim/history, reducer, ledger/state transition, provider, or clock authority. Semantic supported and
contradicted dispositions normalize to applied while retaining the native disposition and corresponding evidence;
unsupported deliberately carries no absence SHA at this leaf and still requires a later exact
`bounded_no_verified_support` absence binding before any effect can be authorized. Only the resolver's exact code
may invoke the projection issuer. Issuance is identity-mirrored and tombstoned; the authority reader and builder
aliases are deleted after initialization. The sealed reader re-runs the exact resolver, so ordinary or forced
attribute mutation, structural/equal-payload clones, cross-owner roots, and validator/runtime dependency replacement
cannot turn the projection into effect authority.
C4.0.c adds a closure-private one-step history keyed by stable execution identity, decision ordinal, the before
snapshot, and exact selected-action identity. Its only live edges in this leaf are pristine-to-claimed,
claim-authorized prepare-to-source, and an explicit or automatic nonterminal-to-failed tombstone. Prepared is a
private weak-bound substate while the public status remains claimed. Calling the C4.0.b resolver directly grants no
step authority. Exact decision and owner preflight happen before history creation; source validation happens only
through the exact claim during prepare and bind. The claim and source projection are immutable, non-serializable
exact-object capabilities; duplicate/concurrent claim, reordered binding, forced mutation, structural/equal-payload
clones, cross-root graphs, post-child dependency drift, and claim/projection/execution GC remint fail closed for the
execution lifetime. Lane dispatch and claim share a monotonic epoch fence, so a live LaneSearchReceipt from an
attempt that began at or before the claim cutoff cannot be attached retroactively. Failed receipt mint explicitly
discards its pending permit, while callback-free weak registry rows are mirror-validated and passively pruned. Only
live lane receipts and terminal controller decisions have temporal source authority here; other C4.0.b source kinds
remain fail-closed until their exact dispatch hooks exist. Effect-bound and transitioned are reserved states, but
their entry points stay dormant until C4.0.e and C4.1 seal exact effect and transition authorities; passing an
arbitrary structural object cannot advance the history. The bookkeeping boundary performs no provider/clock call,
effect mint, reducer work, ledger advance, or state transition.
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
capability, unresolved scope, or an empty top-k alone. Its reason is owner-derived, never a
caller argument. `bounded_no_candidate` is fact/compare-only and requires the exact same
retrieval obligation's normal-empty dense and lexical receipts plus their normal-empty fusion.
`bounded_no_verified_support` accepts fact/compare/follow-up only from an exact reranked-derived
semantic obligation whose verifier was actually called and returned unsupported; base semantic,
unavailable, supported, contradicted, and provider/contract failure are not absence authority.
An unavailable optional reranker is not itself absence, but its identity-derived verifier receipt
may qualify after a real unsupported result.

`followup_approved_paths_exhausted` requires the c1 safe projection for the target obligation to
have no candidates after a normally completed primary path. If fallback was authorized it must
also be present, executed, normally completed, and empty for that target; if it was not authorized,
primary is the only approved path. Empty is per-obligation: a required slot filters candidates to
its document, whereas `$answer_support` covers the whole result. Empty/unresolved scope, uncalled
primary, ignored metadata predicates, partial or mixed lineage, and a skipped authorized fallback
cannot mint absence.

Three module-only issuers derive these reasons without accepting reason, Evidence IDs,
timeout/deadline,
budget-exhaustion, action, state, effect, gold, or qrels input:
`issue_retrieval_absence_confirmation`, `issue_semantic_absence_confirmation`, and
`issue_followup_absence_confirmation`; the follow-up issuer may accept its owner-derived
`obligation_key` target. The package root exports only the factory-issued frozen
`AbsenceConfirmationReceipt` DTO and pure
`validate_absence_confirmation_receipt(*, receipt, store, config, runtime)`. The closed receipt
contains source/query/scope/owner-budget and runtime hashes, an exact reason-specific nullable
proof-SHA matrix, and exact counts. No-candidate and follow-up exhaustion have candidate,
supplied, and support counts of zero. No-verified-support has candidate count equal to its
derived candidate-role count (possibly zero for bridge-only), nonzero supplied count equal to
the derived supplied tuple, and zero support count. It also records
`call_performed=false`; it contains no query text, Evidence ID/anchor/text, value, parent, citation,
state/effect/readiness, or abstention authority. Issuers and validator call retriever, verifier,
reranker, provider, and clock zero times.

Absence issuance is root-lifetime, keyed by the exact BoundFact/BoundCompare/BoundFollowup,
obligation key, derived reason, prerequisite hash, and exact store/config/runtime. A lock/CAS mints
one winner and an exact repeat while its prerequisite objects remain live returns the same receipt
object. Intermediate receipt or semantic-obligation GC never opens remint; a post-GC issuer repeat
fails closed because it cannot supply the exact prerequisite, while the already-issued absence
receipt remains validatable from the root-owned completion projection. The completion cache may
strongly retain only the absence receipt; root and
prerequisite objects are weakly held with immutable issued projections so cleanup is not defeated by
an authority cycle. Live dependencies are revalidated by identity/hash, GC'd intermediates by the
root-owned completion projection and prerequisite hash for validation of the existing receipt only,
and root GC removes cache/history/authority.
Clone, rebuilt-equal, subset/reorder, or mixed root/store/config/runtime input fails before calls.
The receipt remains state-free and cannot mint effect/transition/terminal authority before d2.

The public follow-up retrieval boundary owns one root-lifetime execution chain per exact
`BoundFollowup`: `primary_pending -> primary_done -> progress_pending -> progress_done ->
finalize_pending -> finalized`. Preflight ABI or identity rejection does not consume the chain,
but provider/post-call failure closes it terminally as `primary_failed`, `progress_failed`, or
`finalize_failed`. One lock/CAS gives concurrent or re-entrant callers a single winner, intermediate
primary/progress GC cannot reopen the chain while the root lives, and root GC alone removes both
the visible and closure-private claim authority. Validation is pure and never calls a provider or
advances this state machine.

Reducer transitions are monotonic and
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
