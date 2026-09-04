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
