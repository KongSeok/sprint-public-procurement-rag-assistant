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
and explicit empty scope fail closed. Citation inheritance, slot state, and bounded
controller behavior remain later leaves.
