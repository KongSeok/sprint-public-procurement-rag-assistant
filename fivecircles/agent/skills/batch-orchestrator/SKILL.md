---
name: batch-orchestrator
description: Use when the user asks for "batch-orchestrator", "배치 오케스트레이터", "원툴원고", or wants one orchestrator to split work into batches, assign one subagent per batch, run each batch in one-go style, implement, verify, update TODOs/docs/logs, integrate results, and keep going until the full batch set is complete. This is an execution skill, not a docs-only writing skill.
---

# Batch Orchestrator

Use this skill when the user wants one orchestrator to supervise multiple batch agents and turn a broad goal into executable batches, recursive TODOs, implementation, verification, and closeout.

This skill extends `one-go`: `one-go` is the per-batch execution engine; `batch-orchestrator` is the top-level coordination pattern for many one-go batches.

## Trigger Meaning

When the user says "batch-orchestrator", "배치 오케스트레이터", or the older shorthand "원툴원고", interpret it as:

```txt
One orchestrator
-> one subagent per batch or workstream
-> each batch uses one-go discipline
-> each batch produces or updates an execution brief when needed
-> orchestrator integrates, verifies, logs, and continues until complete
```

## Core Workflow

1. Rebuild context.
   - Read the active requirements, specs, TODO list, recent worklog, and any existing batch execution briefs or plans.
   - Identify completed batches, open batches, blockers, and the next critical path.

2. Define the batch map.
   - Split the work into batches with clear objectives, scope in/out, owners, files, DoD, and validation.
   - Prefer vertical slices that can be tested end to end.
   - Mark dependencies explicitly.

3. Create or update execution briefs.
   - Each batch must have an execution brief or a clearly labeled section in an existing plan/TODO.
   - This is not docs-only prose. The brief must drive implementation: design, contract impact, recursive TODOs, implementation plan, validation, smoke checks, risks, and closeout criteria.

4. Orchestrate subagents only when authorized.
   - If the user explicitly asked for orchestration, subagents, agents per batch, or "원툴원고", spawn one bounded subagent per independent batch/workstream.
   - Give each subagent disjoint ownership over files or surfaces.
   - Tell every subagent: "You are not alone in the codebase; do not revert edits by others."
   - Do not delegate the immediate critical-path task if the main rollout is blocked on it.

5. Integrate.
   - Wait for subagents only when their outputs are needed.
   - Review changed files quickly.
   - Resolve API/type/docs mismatches yourself.
   - Keep contracts aligned across backend, frontend, tests, and docs.

6. Verify.
   - Run targeted tests for each touched surface.
   - Run broader checks when the blast radius is large.
   - For backend work, smoke against the configured local service/database when feasible.
   - For frontend work, run typecheck/lint/build as appropriate and inspect the running UI when relevant.

7. Record and close.
   - Update TODO statuses incrementally.
   - Write worklog entries with commands, results, smoke evidence, remaining risks, and next batch.
   - Final answer must state what completed, what passed, what remains, and the current local URLs/processes if relevant.

## Batch Execution Brief Template

Each execution brief should include:

- Objective
- Current state
- Scope in/out
- Architecture/data/API/UI contract impact
- Recursive TODOs
- Implementation ownership
- Validation commands
- Runtime smoke plan
- DoD
- Risks and fallback
- Closeout evidence requirements

## Recursive TODO Pattern

Use levels when the work is multi-step:

```txt
L1. Batch objective
  L2-A. Backend contract
    L3. DTO/schema
    L3. tests
  L2-B. Domain wrapper
    L3. preview
    L3. commit
    L3. stale/idempotency
  L2-C. UI integration
  L2-D. docs/worklog
```

Mark completed items as soon as they are genuinely done. Do not mark implementation complete from a docs-only pass.

## Subagent Prompt Pattern

```txt
Batch <N> owner: <surface>.
Working dir <path>.
You are not alone in the codebase; do not revert edits by others.
Edit only <files/surfaces>.
Implement <specific outcome>.
Return changed paths, tests run, smoke evidence, and residual risks.
```

For docs-only agents:

```txt
Batch <N> docs owner.
Edit only <docs/todo/worklog paths>.
Do not claim implementation completion without code/test evidence.
Return changed paths and remaining implementation risks.
```

## Stop Conditions

Ask the user before continuing only if:

- A required business decision cannot be inferred safely.
- The next action is destructive or production-affecting.
- Required credentials or services are unavailable.
- The user explicitly asks for planning only.

Otherwise continue through orchestration, implementation, verification, and closeout.
