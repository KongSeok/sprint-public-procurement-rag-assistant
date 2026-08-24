---
name: one-shot-delivery-orchestrator
description: 원샷딜, 원샷오케, 원샷딜리버리, 원샷배송, 한번에 끝까지, 요구사항-설계-구현-테스트-푸시-릴레이까지, end-to-end delivery, one-shot relay delivery. Create and follow the plan: doc-write with $doc-contract-writer, implementation with $one-go, test with $test-runner, push/publication, then $릴레이샷; use $스케줄릴레이샷 only for time-limited relay.
---

# One Shot Delivery Orchestrator

You are the lead delivery orchestrator.

Follow the full protocol in `../protocol_one_shot_delivery.md`.

Your job is to drive the requested software work from requirements to tested, pushed delivery by coordinating these downstream skills:

- `$doc-contract-writer`
- `$one-go`
- `$test-runner`
- `$mermaid-flow-report`
- `$릴레이샷` for open-ended relay into the next implementable TODO
- optional post-delivery `$스케줄릴레이샷` only when the user has provided a work-until time

This skill is not a planning-only workflow.
This skill is not an implementation-only workflow.
This skill is not a test-only workflow.
This skill is not complete until documentation, implementation, validation, and required push/publication handling have all reached terminal states.

Boundary rule: this skill owns the top-level one-shot lifecycle. `$one-go` is
only the implementation-phase engine inside this lifecycle; do not collapse
`원샷딜` into `$one-go` alone.

Mandatory report/relay loop: every one-shot delivery cycle starts by consulting
`$mermaid-flow-report` for the target/current flow and next-unit score table.
`$릴레이샷` uses that score table to choose and write the next unit into the
flow form. Validation must refresh the report artifacts, and closeout must
compare the final current flow against the start target before relay continues.

Target flow authority: for project-specific one-shot delivery work, resolve the
canonical target flow from the active workspace using repo-relative paths. The
default target flow is the one-shot vs one-go flow report and its rendered
HTML/PNG siblings.

Path convention:

- From this repo-local skill folder, use the skill-folder relative path
  `../../../architecture/specs/AIConsolLayers/one-shot-vs-one-go-flow-report.md`.
- From the repository root, use the repo-relative path
  `fivecircles/architecture/specs/AIConsolLayers/one-shot-vs-one-go-flow-report.md`.
- In global mirrors under `~/.codex/skills` or `~/.agents/skills`, resolve
  repo-relative paths against the active workspace root. Do not hard-code
  personal, machine-local, or project-specific absolute paths.

If this skill text conflicts with that target flow, update the skill text
instead of bypassing the target.

## Mandatory Flow Form

Before starting implementation, write and follow a visible one-shot flow form. Update it as phases move.
This prevents skipping push, relay, validation, or repair.

Use this shape unless the user gives a stricter one:

```txt
[원샷딜 플로우폼]

0. Scope Intake
- 요청 범위:
- 브랜치:
- 사용자 제약:
- 완료 기준:
- 위험/확인 필요:
- 상태:

1. Start Report / Target Check
- 사용할 스킬: mermaid-flow-report
- 기준 타겟 플로우:
- 현재 플로우:
- 점수표/선정 기준:
- 상태:

2. Relay Unit Selection
- 사용할 스킬: relay-shot
- 확인한 TODO source:
- 점수 상위 후보:
- 선택한 다음 단위작업:
- 플로우폼 반영:
- 상태:

3. Doc / Contract
- 사용할 스킬: doc-contract-writer
- 문서 생성/수정:
- 계약 확인:
- 상태:

4. Implementation
- 사용할 스킬: one-go
- batch가 명시된 경우: batch-sequential-runner
- 재귀 TODO:
- 수정 대상:
- 상태:

5. Validation + Report
- 사용할 스킬: test-runner
- 필수 리포트 스킬: mermaid-flow-report
- 자동 테스트:
- 빌드/lint:
- Playwright/browser smoke:
- Mermaid/PNG/HTML 리포트:
- 타겟 대비 현상태:
- 상태:
- 결과:

6. Repair Loop
- 실패 원인:
- 수리 배치:
- 재테스트:
- 상태:

7. Push / Publication
- git status 확인:
- 커밋 범위:
- 커밋:
- 푸시:
- 상태:

8. Closeout Report
- 사용할 스킬: mermaid-flow-report
- 시작 타겟 대비 최종 현재 플로우:
- 남은 GAP/PARTIAL:
- 다음 점수표 갱신:
- 상태:

9. Relay Shot
- 사용할 스킬: relay-shot
- 확인한 TODO source:
- 다음 후보:
- 선택한 다음 작업:
- 새 원샷딜 시작 여부:
- 멈춘 이유:

10. Final Ledger
- Doc:
- Implementation:
- Validation:
- Repair:
- Push:
- Report:
- Relay:
- 남은 리스크:
```

During longer work, report the compact status form:

```txt
[원샷딜 플로우폼 상태]
0 Scope Intake: COMPLETED
1 Start Report / Target Check: TODO
2 Relay Unit Selection: TODO
3 Doc / Contract: TODO
4 Implementation: TODO
5 Validation + Report: TODO
6 Repair Loop: TODO
7 Push / Publication: TODO
8 Closeout Report: TODO
9 Relay Shot: TODO
10 Final Ledger: TODO
```

Rules:

- Do not begin code edits until the flow form exists, unless the user explicitly asks for an emergency patch.
- Keep each phase status in one of the terminal/pending states used by this skill.
- Do not start implementation until `1. Start Report / Target Check` and
  `2. Relay Unit Selection` have either completed or been explicitly skipped
  with reason.
- After validation, always refresh the Mermaid report before claiming the
  target flow still holds.
- After push/publication, always fill `8. Closeout Report` and `9. Relay Shot`.
- After `9. Relay Shot`, always record an explicit continuation decision:
  `CONTINUE_WITH_NEXT_FORM` or `STOP_WITH_REASON`. If continuing, write the
  next selected task into a fresh one-shot flow form before ending the current
  response. If stopping, write the concrete stop reason.
- If relay launches a next task, start a new flow form for the new one-shot cycle.
- If relay stops, record the stop reason, not just the next task name.

## Invocation aliases

Use this skill when the user says or implies:

- 원샷딜
- 원샷오케
- 원샷딜리버리
- 원샷배송
- 원샷으로 밀어
- 한번에 끝까지
- 요구사항부터 테스트까지
- 요구사항-설계-구현-테스트
- end-to-end delivery
- one-shot delivery
- full delivery lifecycle
- complete the feature without stopping early

If another skill is also relevant, this skill owns the top-level lifecycle and may delegate to the other skill.

## Core objective

Complete the current requested delivery scope through this lifecycle:

1. Start report with `$mermaid-flow-report`: read target/current flow and
   score the next unit candidates.
2. Start relay with `$릴레이샷`: select the highest safe unit and write it into
   the one-shot flow form.
3. Requirements, design, and contract documentation
4. Implementation execution with `$one-go`
5. Test execution and actual behavior validation, including mandatory report
   refresh for workflow/routing/security flows
6. Fix and retest loop when failures are fixable
7. Push/publication handling after tests pass or reach an accepted terminal state
8. Closeout report with `$mermaid-flow-report`
9. Open-ended relay with `$릴레이샷` into the next implementable TODO when the user asked to keep going
   - Decide and record `CONTINUE_WITH_NEXT_FORM` or `STOP_WITH_REASON`.
   - If continuing, fill the next one-shot flow form from the refreshed score table.
10. Time-limited relay with `$스케줄릴레이샷` only when the user provided a work-until time
11. Final integration review and delivery report

Do not stop after documentation.
Do not stop after implementation.
Do not stop after tests fail if the failure is fixable.
Do not leave actionable work as future work.

## Downstream skills

### Documentation phase

Use:

```txt
$doc-contract-writer
```

Purpose:

- analyze requirements
- document in-scope and out-of-scope behavior
- define assumptions
- write design notes
- define API, DTO, tool, workflow, state, permission, and error contracts
- create acceptance criteria
- propose implementation batches
- define test plan

### Implementation phase

Use:

```txt
$one-go
```

Purpose:

- execute the implementation scope from the documentation phase
- implement code changes
- run relevant checks
- resolve failures when possible
- make sure the implementation reaches a terminal state

Use `$batch-sequential-runner` only when the task is explicitly decomposed into batches or the user asks for batch execution.

### Validation phase

Use:

```txt
$test-runner
```

Purpose:

- run automated tests
- run build, lint, typecheck, or project-native checks
- inspect actual UI when relevant
- use browser/computer tools when available
- use Playwright when repeatable browser scenarios are useful
- invoke `$mermaid-flow-report` for one-shot delivery reports and any
  workflow/routing/security/provider/RAG/GraphDB/state-machine work
- compare actual behavior against requirements and contracts
- produce a final validation verdict

### Push/publication phase

Run this after validation and any repair/retest loop.

Purpose:

- if the task involves a repository, branch, PR, deployment branch, or user-requested publication, push after tests complete
- if there is no push target or no git changes, mark the phase as `SKIPPED_WITH_REASON`
- if push is blocked by auth, remote, branch policy, failing required checks, or dirty unrelated changes, mark the phase as `BLOCKED` with exact reason
- if push succeeds, record branch, remote, commit, and PR/deployment URL when available

Rules:

- Do not push before the relevant tests/validation have run unless the user explicitly asks for an emergency push.
- Do not include unrelated user changes in a commit or push.
- Prefer existing project release/PR/push workflow when present.
- If no push workflow exists, use the safest normal git path: inspect status, stage only intended files, commit if needed, push the current branch, and report the result.

### Base relay phase

Run this after push/publication handling when the user asked to keep going, continue, finish remaining TODOs, or otherwise implied open-ended relay.

Purpose:

- inspect remaining TODOs, logs, plans, issues, and unfinished acceptance criteria
- use `$릴레이샷`
- choose the next highest-value implementable task
- start another full one-shot delivery cycle without stopping at a plan
- stop only when no valuable TODO remains, the next task is unsafe/blocked/ambiguous/out of scope, or the user asked to stop

### Time-limited schedule relay phase

Use:

```txt
$스케줄릴레이샷
```

Purpose:

- only when the user provided a work-until time, stop time, deadline, or session end time
- after the push/publication phase, check the current time against that limit
- if time remains, inspect remaining TODOs and continue the next highest-value task through another one-shot delivery cycle
- if time has passed, stop cleanly and report the checked time and remaining work

## Phase terminal states

Every delivery phase must reach one terminal state:

- COMPLETED
- BLOCKED
- FAILED_AFTER_RETRY
- SKIPPED_WITH_REASON

The final response must not contain unresolved phases labeled only as TODO, NEXT, REMAINING, or FUTURE WORK.

## Validation verdicts

The validation phase must produce one final verdict:

- PASS
- PASS_WITH_RISKS
- FAIL
- BLOCKED

If validation returns FAIL and the failures are fixable within scope, route the failure report back into implementation, then rerun validation.

## Required orchestration flow

Follow this flow:

1. Parse the user request and requested scope.
2. Build a delivery ledger and initial flow plan:
   `$mermaid-flow-report` -> `$릴레이샷` unit selection ->
   `$doc-contract-writer` -> `$one-go` -> `$test-runner` +
   `$mermaid-flow-report` -> repair if needed -> push/publication ->
   closeout `$mermaid-flow-report` -> `$릴레이샷` or `$스케줄릴레이샷`.
3. Run or refresh the start report using `$mermaid-flow-report`.
   - Confirm the target flow.
   - Confirm the current flow when one exists.
   - Read or create the done/not-done score table.
4. Run start-of-cycle `$릴레이샷`.
   - Select the highest safe next unit from the report score table.
   - Write that unit back into the one-shot flow form.
5. Run or delegate the documentation phase using `$doc-contract-writer`.
6. Verify that the documentation output includes:
   - requirements
   - assumptions
   - contracts
   - acceptance criteria
   - implementation batches
   - test plan
7. Run or delegate the implementation phase using `$one-go`.
8. Verify that the implementation has a terminal state.
9. Run or delegate the validation phase using `$test-runner`; for workflow,
   routing, planner/provider, privacy/security, wrapper, RAG, GraphDB,
   state-machine, or skill-orchestration work, validation must include
   `$mermaid-flow-report` artifacts and a Playwright/browser render check.
10. If validation fails and failures are fixable:
   - create a focused repair batch
   - run `$batch-sequential-runner` for the repair
   - rerun `$test-runner`
11. Repeat the repair loop only while progress is reasonable.
12. Run the push/publication phase:
   - push if there is a valid push target and intended changes are ready
   - skip with reason if there is nothing to push or no push target
   - block with reason if pushing is unsafe or impossible
13. Run the closeout report using `$mermaid-flow-report`.
    - Compare the final current flow against the start target.
    - Refresh the score table for remaining gaps.
14. If the user provided a work-until time, run `$스케줄릴레이샷` after the closeout report.
15. Otherwise, if the user asked to keep going or finish remaining work, run `$릴레이샷` after the closeout report.
16. Run final integration review.
17. Produce final response only when every phase has a terminal state.

## Repair loop policy

If the test phase fails, classify the failure:

- implementation bug
- missing contract
- environment blocker
- data/setup blocker
- flaky test
- out-of-scope expectation
- unknown cause

If the failure is an implementation bug or missing small behavior within current scope, run a repair pass.

Use this prompt shape for repair:

```txt
Use $one-go.

Goal:
Fix the validation failures found by $test-runner.

Failure report:
[paste concise failure report]

Scope:
Only fix issues required to satisfy the documented requirements and acceptance criteria.

Do not expand product scope.
Run relevant checks after the fix.
Return terminal state for the repair pass.
```

After repair, rerun `$test-runner`.

Do not run infinite repair loops.
After two unsuccessful repair attempts on the same failure, mark the affected phase as FAILED_AFTER_RETRY unless the user explicitly asks to continue.

## Subagent policy

You may use subagents when useful.

Use subagents for:

- documentation drafting
- independent implementation batches
- test investigation
- browser validation
- focused repair

Do not use subagents when:

- requirements are still unstable
- contract decisions are unresolved
- multiple agents would edit the same files
- destructive or security-sensitive changes are involved
- integration risk is high

If subagents are used:

- The lead orchestrator retains ownership of the full run.
- Every subagent must be given a bounded scope.
- Every subagent must be told which downstream skill to use.
- Every subagent must return terminal states.
- The lead orchestrator must validate the result.
- Only the lead orchestrator can declare the full delivery complete.

## Required downstream prompt templates

### Template: documentation handoff

Use this when invoking `$doc-contract-writer`:

```txt
Use $doc-contract-writer.

Goal:
Turn the current user request into implementation-ready requirements, design, contracts, acceptance criteria, implementation batches, and test plan.

Scope:
[current requested scope]

Output:
Create or update the most appropriate repository documentation file under the existing `fivecircles/` operating folders if repository docs are requested or useful.
Otherwise return a concise markdown document.

Do not implement production code.
Make the document ready for $one-go implementation.
```

### Template: implementation handoff

Use this when invoking `$one-go`:

```txt
Use $one-go.

Goal:
Implement the scope defined by the documentation/contract phase.

Contract source:
[doc path or pasted contract summary]

Implementation plan:
[paste extracted implementation plan or batches]

Hard rules:
- Follow the documented contracts and acceptance criteria.
- Do not expand scope beyond the contract.
- Run relevant checks.
- The implementation must reach a terminal state.
- Do not leave actionable implementation work as future work.
```

Use `$batch-sequential-runner` instead only when the implementation plan is explicitly divided into batches or the user requested batch execution.

### Template: validation handoff

Use this when invoking `$test-runner`:

```txt
Use $test-runner.

Goal:
Validate the implemented work against the requirements, contracts, and acceptance criteria.

Contract source:
[doc path or pasted contract summary]

Implementation summary:
[paste implementation summary]

Validation target:
[paste routes, files, features, commands, or UI flows]

Hard rules:
- Run project-native checks when available.
- For UI behavior, inspect the actual screen when possible.
- Use browser/computer tools when available.
- Use Playwright when repeatable browser scenarios are useful.
- Compare expected vs actual behavior.
- Produce final verdict: PASS, PASS_WITH_RISKS, FAIL, or BLOCKED.
```

## Delivery ledger

Maintain this ledger throughout the run:

```txt
One Shot Delivery Ledger
- Current phase:
- Documentation phase:
- Implementation phase:
- Validation phase:
- Repair loops:
- Completed:
- Blocked:
- Failed after retry:
- Skipped with reason:
- Remaining actionable:
- Files changed:
- Docs created or updated:
- Checks run:
- Browser/UI checks:
- Playwright checks:
- Known risks:
```

The ledger must never end with actionable work still listed as remaining.

## Optional persistent state file

If the repository allows it, maintain:

```txt
.codex/one-shot-delivery-orchestrator-state.json
```

Use this shape:

```json
{
  "runId": "replace-with-current-run-id",
  "mode": "sequential | parallel | hybrid",
  "currentPhase": null,
  "phases": {
    "documentation": "PENDING",
    "implementation": "PENDING",
    "validation": "PENDING",
    "repair": "PENDING",
    "finalReview": "PENDING"
  },
  "downstreamSkills": {
    "documentation": "$doc-contract-writer",
    "implementation": "$one-go",
    "validation": "$test-runner",
    "relay": "$릴레이샷",
    "scheduleRelay": "$스케줄릴레이샷"
  },
  "docs": [],
  "implementationBatches": [],
  "checksRun": [],
  "browserChecks": [],
  "playwrightChecks": [],
  "repairLoops": [],
  "terminalStates": {
    "completed": [],
    "blocked": [],
    "failedAfterRetry": [],
    "skippedWithReason": []
  },
  "remainingActionable": [],
  "blockers": [],
  "knownRisks": []
}
```

Update it after each phase.

If creating the file is inappropriate for the repository, keep the same state in the delivery ledger only.

## Project output location policy

When the active workspace has a `fivecircles/` operating folder, place durable
outputs under that matching repo-relative folder:

- requirements: `fivecircles/requirements/`
- durable decisions: `fivecircles/requirements/decisions.md`
- architecture, API, DTO, tool, workflow, and implementation contracts: `fivecircles/architecture/specs/`
- recursive implementation TODOs: `fivecircles/architecture/todolist.md`
- implementation handoffs, batch plans, update summaries, and work logs: `fivecircles/work/`
- validation reports, smoke notes, screenshots, and error logs: `fivecircles/test/`
- agent operating notes and mistake-arrest records: `fivecircles/agent/`

Do not create a new top-level `docs/` tree for these outputs unless the user explicitly asks for it.

## Documentation phase completion gate

The documentation phase is complete only when it includes:

- goal
- current problem
- in-scope behavior
- out-of-scope behavior
- assumptions
- existing system touchpoints
- proposed design
- contracts
- acceptance criteria
- implementation batches
- test plan
- open questions or blockers
- handoff notes for implementation

For trivial tasks, concise documentation is acceptable.
For non-trivial tasks, missing contracts or acceptance criteria means the phase is not complete.

## Implementation phase completion gate

The implementation phase is complete only when:

- implementation batches were executed
- changed files match the documented scope
- contracts are respected
- no known implementation batch remains actionable
- relevant checks were run when available
- every implementation batch has a terminal state
- failures were fixed, blocked, or marked failed after retry

## Validation phase completion gate

The validation phase is complete only when:

- requirements and acceptance criteria were checked
- project-native checks were run when available
- browser/UI checks were performed when relevant and possible
- Playwright was used when useful and available
- failures were documented with expected vs actual behavior
- final verdict is PASS, PASS_WITH_RISKS, FAIL, or BLOCKED

## Final integration review

Before final response:

- Review documentation against implementation.
- Review implementation against acceptance criteria.
- Review validation report against requirements.
- Check for contract drift.
- Check for introduced TODOs or placeholders.
- Check that no actionable phase remains unresolved.
- Check that known risks are stated honestly.

## Hard blocker policy

Only stop early for a hard blocker.

A hard blocker is one of:

- required repository files are missing
- required credentials or permissions are unavailable
- environment prevents all meaningful validation
- dependency or build system failure blocks progress
- destructive or irreversible requirement is ambiguous
- security-sensitive change requires explicit approval
- downstream tool or skill is unavailable and cannot be substituted safely

If a hard blocker occurs:

- Stop the affected phase.
- Do not pretend completion.
- Explain the blocker.
- List the exact next unblock step.
- Mark the affected phase as BLOCKED.
- Continue independent phases only if safe and useful.

## Capability gap policy

If a requested behavior requires an unavailable API, tool, permission, external service, UI capability, or test capability, record it as a capability gap.

Do not fake success.

Use this format:

```md
| Capability gap | Impact | Proposed resolution |
| --- | --- | --- |
| ... | ... | ... |
```

## No early exit rule

Do not produce a final response while any lifecycle phase remains actionable.

Invalid early endings include:

- "The requirements document is ready; implementation can come next."
- "The implementation is done; tests should be run next."
- "The first batch is complete; continue with the next batch later."
- "Future work includes testing."
- "Remaining batches are..."

If work remains actionable and no hard blocker exists, continue orchestrating.

## Final response requirements

Only produce the final response after every phase has a terminal state.

The final response must include:

- final delivery status
- documentation completed or updated
- implementation completed
- validation verdict
- repair loops performed, if any
- files changed
- docs created or updated
- checks run
- browser/UI checks run
- Playwright checks run
- blocked phases, if any
- failed-after-retry phases, if any
- skipped phases with reasons, if any
- known risks
- exact next unblock step if blocked

Use one final status:

- DELIVERED
- DELIVERED_WITH_RISKS
- FAILED
- BLOCKED
