# Architecture Decision Notes

> Author: Codex-integration | Date: 2026-09-02

The user agreed to defer multimodal embeddings/actual visual reading and continue nonvisual work.
We reuse the existing KURE page-part vectors without relabelling them as child vectors, and put
typed bounded orchestration above page-dense/child-lexical retrieval. List membership uses an
exhaustive scoped scan plus reduction, independent of retrieval top-k. The runtime LLM supplies
provisional semantic decisions; the frozen ChatGPT quality judge remains outside runtime.

Tradeoff: enumeration completeness is checked structurally, but its budget may be insufficient
for the whole corpus. The untrained LLM policy may misroute queries. We preserve failures,
unknowns and time limits instead of interpreting a successful test fixture as general quality.
The CLI gives generation only verified mandatory evidence to avoid irrelevant optional context.

Decision references: [contract](../architecture/specs/evidence-harness-contract.md),
[local runbook](../work/evidence-harness-local-runbook.md),
[live findings](../test/errorlogs/backend/2026-09-02-harness-live-routing-budget.md).
