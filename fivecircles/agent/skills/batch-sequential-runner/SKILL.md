---
name: batch-sequential-runner
description: Drive a multi-step or multi-batch coding plan to completion. Use this when the user asks to execute batches, phases, or implementation steps end-to-end without stopping early. Parallel work is allowed when safe, but every requested batch must reach a terminal state before the final response.
---

# Batch Sequential Runner

You are the lead orchestrator and implementation owner.

Your job is to drive the user's requested batches, phases, or implementation steps to completion.

This skill is not a planning-only workflow.
This skill is not a "do one batch and leave the rest" workflow.
This skill is not a "summarize remaining work as future work" workflow.

## Core objective

Complete all requested work in the current scope.

Do not stop early while requested batches remain actionable.

A run is complete only when every requested batch reaches one terminal state:

- COMPLETED
- BLOCKED
- FAILED_AFTER_RETRY
- SKIPPED_WITH_REASON

The final response must not contain unprocessed batches labeled only as TODO, NEXT, REMAINING, or FUTURE WORK.

## Scope source

The concrete batch list must come from the user's current request, an attached plan, a repository file, or a batch plan file such as:

- `batches.yaml`
- `batch-plan.md`
- `TODO.md`
- issue description
- user-provided batch list

Do not invent batch numbers or batch contents.
Do not reuse batch numbers from previous runs unless they are present in the current request.

## Execution mode policy

Before implementation, choose one execution mode:

- `sequential`
- `parallel`
- `hybrid`

Sequential execution is preferred when:

- one batch depends on another batch's output
- batches edit the same files or tightly coupled modules
- one batch defines schemas, contracts, or interfaces that later batches consume
- integration risk is high

Parallel execution is allowed when batches are independent.

Parallel execution is not allowed when:

- dependency order is unclear
- multiple batches would edit the same files
- changes could conflict
- validation would become unreliable

If parallel execution is used:

1. The lead orchestrator must keep ownership of the full run.
2. Every batch must be tracked in the ledger.
3. Every batch must reach a terminal state.
4. Integration checks must run after parallel work is merged.
5. The final response must not be sent until all batches are resolved.

## Required orchestration flow

1. Parse the requested batch list.
2. Build a batch ledger.
3. Identify dependencies between batches.
4. Choose execution mode:
   - sequential
   - parallel
   - hybrid
5. Execute actionable batches.
6. Validate each completed batch.
7. Retry or fix failed checks when possible.
8. Run integration checks after related batches complete.
9. Continue until every batch reaches a terminal state.
10. Only then produce the final response.

## Batch ledger

Maintain this ledger throughout the run:

```txt
Batch Sequential Runner Ledger
- Run mode:
- Current wave:
- Completed:
- In progress:
- Blocked:
- Failed after retry:
- Skipped with reason:
- Remaining actionable:
- Files changed:
- Checks run:
- Integration checks:
```

The ledger must never end with actionable work still listed as remaining.

## Batch terminal states

### COMPLETED

Use when:

- the batch scope was implemented
- relevant files were inspected or changed
- relevant checks were run
- failures were fixed or accepted with clear explanation
- the result was integrated with related work

### BLOCKED

Use only when progress is impossible due to:

- missing required files
- missing credentials or permissions
- broken dependency or environment
- ambiguous destructive requirement
- external service unavailable

When blocked, do not silently skip. Explain the blocker and exact next unblock step.

### FAILED_AFTER_RETRY

Use when:

- implementation was attempted
- relevant checks failed
- reasonable fixes were attempted
- failure remains

Include commands, error summary, and files involved.

### SKIPPED_WITH_REASON

Use only when:

- the batch is no longer applicable
- another completed batch fully superseded it
- the user-specified scope makes it irrelevant

Do not use this to avoid hard work.

## Completion gate

A batch is not terminal until one of the terminal-state criteria is met.

A completed batch must satisfy:

- scope matched
- relevant files changed or explicitly inspected
- relevant tests, build, lint, typecheck, or smoke checks run when available
- failures fixed or documented
- no unresolved integration conflict remains
- ledger updated

## No early exit rule

Do not stop after one batch if additional requested batches remain actionable.

Do not produce a final response that says:

- "Next batches remain"
- "Future work includes"
- "The remaining batches should be done later"
- "Batch N is complete, continue with Batch N+1 next"

unless those remaining batches are blocked, failed after retry, or skipped with a specific reason.

If work remains actionable, continue working.

## Optional persistent state file

If the repository allows it, maintain:

```txt
.codex/batch-sequential-runner-state.json
```

Use this shape:

```json
{
  "runId": "replace-with-current-run-id",
  "mode": "sequential | parallel | hybrid",
  "allowParallel": true,
  "currentWave": null,
  "batches": [],
  "terminalStates": {
    "completed": [],
    "blocked": [],
    "failedAfterRetry": [],
    "skippedWithReason": []
  },
  "remainingActionable": [],
  "checksRun": [],
  "integrationChecks": [],
  "blockers": []
}
```

Update it after every wave or completed batch.
For fivecircles-governed repository artifacts, prefer durable outputs under `fivecircles/`: implementation handoffs and closeout notes in `fivecircles/work/`, recursive batch TODOs in `fivecircles/architecture/todolist.md`, contracts in `fivecircles/architecture/specs/`, requirements in `fivecircles/requirements/`, and validation evidence in `fivecircles/test/`.

## Validation policy

Prefer repository-native checks.

Examples:

- Gradle: `./gradlew test`, `./gradlew build`, targeted module tests.
- Maven: `./mvnw test`.
- Node: `npm test`, `npm run build`, `npm run lint`, `npm run typecheck`.
- Python: `pytest`, `ruff`, `mypy`.
- Browser/admin flows: smoke checks when relevant.

If no clear check exists, perform the most relevant lightweight validation and state exactly what was checked.

## Final response requirements

Only provide the final response after every requested batch has a terminal state.

The final response must include:

- Execution mode used
- Completed batches
- Blocked batches, if any
- Failed-after-retry batches, if any
- Skipped batches with reasons, if any
- Files changed
- Checks run
- Integration checks run
- Known risks

## Call Prompt Template

Use this form when invoking the workflow:

```txt
Use $batch-sequential-runner.

Goal:
Drive the following batches to completion.

Parallel execution is allowed when safe, but do not abandon any batch.
Every batch must reach a terminal state:
- COMPLETED
- BLOCKED
- FAILED_AFTER_RETRY
- SKIPPED_WITH_REASON

Do not end with unresolved TODO/NEXT/REMAINING work.

Before implementation:
- build a batch ledger
- identify dependencies
- choose sequential, parallel, or hybrid execution mode

After implementation:
- run per-batch checks
- run integration checks
- produce the final response only when every batch has a terminal state

Batches:
[paste this run's batch list here]
```
