---
name: one-go
description: End-to-end project execution workflow for Codex. Use when the user asks to proceed "in one go", finish a batch, act as orchestrator, create/update plans and TODOs, coordinate subagents, document decisions, implement changes, run tests/smoke/browser checks, verify, and report completion.
---

# One Go

## Core Workflow

Use this skill to move a project batch from intent to verified outcome without stopping at a proposal.

When the user asks for the Korean shorthand "설계-문서-투두-원고" or "설계-문서-투두-구현",
interpret it as:

1. 설계: decide the approach and contracts first.
2. 문서: write the decision into the project requirements/specification/contract docs.
3. 투두: update the project TODO list with concrete tasks, DoD, and validation.
4. 구현: implement, test, smoke/browser-check, log, and close without stopping at a proposal.

1. Rebuild context.
   - Read the project README, active requirements, specs, TODO list, and recent work logs before editing.
   - Prefer `rg` and targeted file reads.
   - Identify the current batch, completed work, open risks, and likely next development step.

2. Plan the batch.
   - Write a short execution plan with task batches, DoD, tests, dependencies, and risks.
   - If the repo uses a project-specific planning location, update that location instead of inventing a new one.
   - Keep the plan migration-friendly: boundaries, contracts, and data ownership must be explicit.

3. Create or update TODOs.
   - Add concrete tasks with owners or surfaces, DoD, and validation.
   - Mark status incrementally as work completes.
   - Preserve old completed history unless the user explicitly asks for cleanup.

4. Orchestrate subagents when authorized.
   - Split independent work into bounded tasks with disjoint file ownership.
   - Use explorers for read-only discovery and workers for patches.
   - Tell workers they are not alone in the codebase and must not revert others' edits.
   - Keep urgent blocking work local unless the user asks the main agent to coordinate only.

5. Implement.
   - Follow existing architecture, naming, code style, API contracts, and test policy.
   - Edit files with `apply_patch` for manual changes.
   - Keep changes scoped to the documented batch.

6. Verify.
   - Run the smallest meaningful checks first, then broaden based on risk.
   - Always run the relevant automated tests for touched surfaces unless blocked; record any blocker explicitly.
   - For frontend work, run lint/build and inspect the running UI.
   - For interactive UI changes, run a browser smoke check at the end. Prefer Playwright when available; otherwise use the in-app browser/computer-use or an equivalent documented manual smoke.
   - For backend work, run relevant tests and smoke APIs against the configured database, not only an in-memory fallback, unless the configured database is unavailable and the blocker is logged.
   - For full-stack work, verify the actual browser talks to the intended API base URL and that auth/session-dependent UI updates after login/logout.
   - Treat screenshots, console/network checks, API smoke output, or Playwright assertions as closeout evidence.

7. Record and close.
   - Update TODO statuses, work logs, and any contract/spec documents touched by implementation.
   - Summarize what changed, what passed, what smoke/browser evidence was collected, what remains, and exact commands or URLs needed.

## Batch Document Pattern

When adding a new project batch, include:

- Objective
- Scope in/out
- Workstreams
- API/data/UI contract impact
- DoD
- Validation
- Final smoke/browser check
- Risks/open questions
- Migration notes for later separation or scaling

## Final Verification Checklist

Before reporting completion, make a best-effort pass through:

- Automated checks: targeted tests plus broader suite when risk justifies it.
- Frontend checks: lint/build and a running-app inspection.
- Browser smoke: Playwright if installed/available; otherwise in-app browser/computer-use or an explicitly described manual smoke.
- API smoke: real configured service/database and representative happy path/error path.
- Integration sanity: confirm configured ports/base URLs, auth/session refresh, and visible UI state such as badges/toasts/navigation.
- Evidence: record commands, URLs, important outputs, and any screenshots or console/network observations in the project log.

## Subagent Prompt Pattern

Use concise prompts like:

```txt
You own <files/surface>. Edit only that surface. You are not alone in the codebase; do not revert edits by others. Implement <task>. Return changed paths, verification run, and residual risks.
```

For explorers:

```txt
Do not edit files. Inspect <surface>. Return implemented vs missing, file paths, and recommended next tasks.
```

## Stop Conditions

Ask the user before continuing only when:

- A required business decision cannot be inferred safely.
- The next action is destructive or would affect production data.
- The user explicitly asked for a proposal only.

Otherwise, continue through implementation, verification, and closeout.
