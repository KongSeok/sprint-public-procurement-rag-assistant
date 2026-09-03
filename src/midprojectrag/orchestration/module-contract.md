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
