# Fivecircles - Specification Index

This folder contains technical analysis and implementation contracts derived
from confirmed requirements. Operational guidance belongs in `fivecircles/agent/`;
this folder is for product, API, data, architecture, security, performance, and
workflow contracts.

## Boot Order

- Read `fivecircles/agent-guidelines.md` for root compatibility guidance.
- Read `fivecircles/agent/README.md` and `fivecircles/agent/agent-guidelines.md`.
- Read the relevant local skill under `fivecircles/agent/skills/` before execution.
- Use this README to locate the authoritative technical contract for the task.

## Authority

The single authority order is defined in `fivecircles/agent/authority.md`.
Do not duplicate or reinterpret that order in specification files.

## Spec Inventory

- `agent-orchestrator.md`: active agent roles and session management.
- `system-overview.md`: RAG component boundaries and A/B stack architecture.
- `source-data-contract.md`: source, normalization, manifest, extraction and provenance contract.
- `data-model.md`: corpus, document, source block, chunk, citation and run semantics.
- `api-contract.md`: **active from Batch 2** common request/response contract entrypoint.
- `evaluation-contract.md`: **active from Batch 2** evaluation split, metrics and A/B fairness rules.
- `security.md`: restricted data, secret, PII and model egress controls.
- `git.md`: repository tracking and pre-publication safety rules.
- `implementation-rules.md`: preventive implementation invariants.
- `docker.md`: optional container/runtime boundary; not a product requirement.
- `performance.md`: **active from Batch 2** latency, cost and resource measurement contract.
- `frontend.md`: **not active yet** demo UI contract when a frontend batch is activated.
- `buisiness-workflow.md`: **not active yet** consultant-facing workflow (legacy spelling retained for stable path).

## Language Policy

- Technical contracts should be clear enough for implementation without chat context.
- English file names are preferred for stable references.
- Korean notes are allowed when they preserve user intent or domain nuance.

## Agent Constraint

- Do not modify requirements, specs, policy files, or `architecture/todolist.md`
  unless the user asks for planning/docs work or the current task requires
  those updates.
- Do not place agent behavior rules in spec files; put them under
  `fivecircles/agent/`.
- Do not create parallel spec folders unless the user explicitly asks.

## Work Folder Policy

- Planning tasks are tracked in `fivecircles/architecture/todolist.md`.
- Implementation logs and closeout notes are recorded under `fivecircles/work/`.
- Runtime failures and regression learnings are recorded under `fivecircles/test/`.
- Work logs must align with confirmed requirements and relevant spec contracts.

## Development Cycle

1. Requirements: clarify or confirm under `fivecircles/requirements/`.
2. Design: update relevant files under `fivecircles/architecture/specs/`.
3. Planning: decompose into batches in `fivecircles/architecture/todolist.md`.
4. Implementation: change code in the smallest safe slice.
5. Test: run targeted tests, smoke checks, and browser/Playwright checks when relevant.
6. Integrate: record results in `fivecircles/work/` and update TODO status.
7. Maintenance: feed repeated failures into specs or `test/learn-from-log.md`.

## Requirements Governance

- New requests start with requirements analysis unless they are direct fixes.
- Confirmed decisions are recorded in `fivecircles/requirements/decisions.md`.
- Based on confirmed rules, tasks are extracted into `architecture/todolist.md`.
- After implementation, tests and error logs must update the todo state.
- Repeated failures should become either spec constraints or learn-from-log entries.

## Runtime Stack Policy

- Follow the runtime stack documented in the relevant specs.
- Scenario B is implemented first; Scenario A follows the same public contract.
- Runtime/model choices belong to configuration and run records, not hidden notebook state.
- Browser automation should use Playwright when repeatable UI evidence is needed.

## Test Policy

- Test policy is defined in `fivecircles/test/testpolicy.md`.
- Runtime lessons are recorded in `fivecircles/test/learn-from-log.md` when present.
- For browser behavior, prefer repeatable browser evidence over chat-only claims.

## Agent Scoring

- Use scoring only when the active workflow asks for it.
- Record scoring under `fivecircles/scoring/` when applicable.
- Optimize for correct, verified, logged work with the fewest avoidable retries.
