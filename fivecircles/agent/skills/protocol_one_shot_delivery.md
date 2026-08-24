# Skill: Protocol for One-Shot Delivery

## Purpose
Run software work end to end through this fixed flow: start flow report,
relay unit selection, doc-write, implementation, test/report validation,
repair, push/publication, closeout report, and relay into the next
implementable task.

This is the base one-shot delivery relay protocol. It is not time-limited by
itself: when a cycle finishes and the user asked to keep going, continue in
one-go, or complete remaining work, do not stop at TODO analysis. Select the
next highest-value remaining task from the mandatory report score table and
immediately continue through the full one-shot loop again.

Canonical target flow: for project-specific one-shot delivery work, resolve the
target flow report from the active workspace using repo-relative paths. The
default target flow is documented in the one-shot vs one-go flow report and its
HTML/PNG siblings. This protocol must follow that flow. If text here drifts
from the target report, update this protocol rather than bypassing the target.

Path convention:

- From this repo-local protocol file, use the skill-folder relative path
  `../../architecture/specs/AIConsolLayers/one-shot-vs-one-go-flow-report.md`.
- From the repository root, use the repo-relative path
  `fivecircles/architecture/specs/AIConsolLayers/one-shot-vs-one-go-flow-report.md`.
- In global mirrors under `~/.codex/skills` or `~/.agents/skills`, resolve
  repo-relative paths against the active workspace root. Do not hard-code
  personal, machine-local, or project-specific absolute paths.

`$릴레이샷` is the default time-unlimited relay skill. `$스케줄릴레이샷` is the separate time-limited relay gate. Use schedule relay only when the user provided a work-until time, stop time, deadline, or session end time.

## Usage
Execute this protocol when the user asks for "원샷딜", "원샷오케", "원샷딜리버리", "한번에 끝까지", "one-shot delivery", or asks to complete requirements, implementation, tests, and push without stopping early.

## Required Flow Form

At the beginning of every one-shot cycle, create a visible flow form and use it as the execution ledger.
Do this before implementation so the relay, push, validation, and repair phases are not forgotten.

Template:

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

Update a compact status block while working:

```txt
[원샷딜 플로우폼 상태]
0 Scope Intake: COMPLETED
1 Start Report / Target Check: IN_PROGRESS
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

- If a cycle was launched by `$릴레이샷`, the selected next TODO becomes the `요청 범위`.
- Do not skip the form just because the work appears small; mark irrelevant phases `SKIPPED_WITH_REASON`.
- Do not skip `Start Report / Target Check`, `Relay Unit Selection`,
  `Validation + Report`, or `Closeout Report` for workflow, routing,
  provider/privacy, API selection, wrapper, RAG, GraphDB, state-machine, or
  skill-orchestration work.
- If code edits have already started before the form exists, create the form immediately and continue from the actual current state.
- At final response time, the form should have terminal statuses or a clear blocker.

## Downstream Skills

- `$doc-contract-writer`
- `$one-go` for implementation
- `$test-runner`
- `$mermaid-flow-report` for start report, validation report, and closeout report
- `$릴레이샷` as the default final relay after push
- `$스케줄릴레이샷` only when the user provided a work-until time, used as the time gate before launching another full implementation cycle

## Terminal States

Every phase must end as one of:

- `COMPLETED`
- `BLOCKED`
- `FAILED_AFTER_RETRY`
- `SKIPPED_WITH_REASON`

Do not produce a final delivery report while any phase is only `TODO`, `NEXT`, `REMAINING`, or `FUTURE WORK`.

## Protocol Steps

1. **Scope Intake**
   - Parse the user request, target repository, branch, constraints, and acceptance criteria.
   - Build a delivery ledger with phases, status, owner, evidence, and open risks.
   - The initial plan must include this flow explicitly: `$mermaid-flow-report` -> `$릴레이샷` unit selection -> `$doc-contract-writer` -> `$one-go` -> `$test-runner` + `$mermaid-flow-report` -> repair if needed -> push/publication -> closeout `$mermaid-flow-report` -> `$릴레이샷` or `$스케줄릴레이샷`.
   - If this cycle was launched by a relay, treat the selected remaining TODO as the new concrete delivery scope.

2. **Start Report / Target Check**
   - Use `$mermaid-flow-report`.
   - Read or create the target/current flow report and score table.
   - The report identifies done/not-done items and scores the next unit candidates.
   - Mark the phase `COMPLETED`, `BLOCKED`, or `SKIPPED_WITH_REASON`.

3. **Relay Unit Selection**
   - Use `$릴레이샷`.
   - Select the highest safe next unit from the report score table.
   - Write that unit back into the one-shot flow form before implementation starts.
   - Mark the phase `COMPLETED`, `BLOCKED`, or `SKIPPED_WITH_REASON`.

4. **Documentation / Contract Phase**
   - Use `$doc-contract-writer`.
   - Produce or verify requirements, assumptions, contracts, acceptance criteria, implementation batches, and test plan.
   - Mark the phase `COMPLETED`, `BLOCKED`, or `SKIPPED_WITH_REASON`.

5. **Implementation Phase**
   - Use `$one-go` by default.
   - Execute implementation until the selected scope reaches a terminal state.
   - Use `$batch-sequential-runner` only when the work has already been decomposed into explicit batches or the user asked for batch execution.
   - Run targeted checks during implementation when useful.

6. **Validation + Report Phase**
   - Use `$test-runner`.
   - Run automated checks and actual behavior validation.
   - For UI/user-facing work, reproduce the user's real actions with Playwright, browser-use, screenshots, or Computer Use when available.
   - Use `$mermaid-flow-report` for workflow/routing/provider/privacy/API
     selection/wrapper/RAG/GraphDB/state-machine/skill orchestration validation.
   - Regenerate Mermaid PNG/HTML artifacts and verify the HTML with Playwright
     or browser when the report is part of the acceptance criteria.
   - Produce a verdict: `PASS`, `PASS_WITH_RISKS`, `FAIL`, or `BLOCKED`.

7. **Repair Loop**
   - If validation fails and the failure is fixable within scope, create a focused repair batch.
   - Use `$batch-sequential-runner` for the repair, then rerun `$test-runner`.
   - Stop after two unsuccessful repair attempts on the same failure unless the user explicitly asks to continue.
   - Mark persistent failures `FAILED_AFTER_RETRY` or `BLOCKED` with evidence.

8. **Push / Publication Phase**
   - Run after validation and repair/retest handling.
   - If the task has a repository, branch, PR, deployment branch, or user-requested publication target, push after tests complete.
   - If there is no push target or no git changes, mark `SKIPPED_WITH_REASON`.
   - If push is unsafe or impossible, mark `BLOCKED` with exact reason.
   - Do not include unrelated user changes in a commit or push.
   - Record branch, remote, commit, and PR/deployment URL when available.

9. **Closeout Report Phase**
   - Use `$mermaid-flow-report`.
   - Compare final current flow against the start target.
   - Refresh the done/not-done priority table and scoring criteria.
   - Mark remaining `GAP` or `PARTIAL` items before relay selection.

10. **Base Relay Phase**
   - If the user asked to continue, keep going, finish remaining TODOs, run in one-go, or otherwise implied an open-ended relay, analyze remaining TODOs after the closeout report.
   - Use `$릴레이샷`.
   - Choose the highest-value next task from the refreshed report score table
     that can be safely started.
   - Start the next task immediately as a new full one-shot cycle: scope intake, documentation/contract if needed, implementation, validation, repair, and push/publication.
   - Do not return only a plan for the next task unless the next task is unsafe, blocked, too ambiguous, or outside the requested scope.
   - Always record the relay continuation decision as
     `CONTINUE_WITH_NEXT_FORM` or `STOP_WITH_REASON`.
   - If continuing, fill the next one-shot flow form from the refreshed score
     table before ending the current response.
   - If stopping, record the exact stop reason and the next concrete task that
     would run if unblocked.
   - If the user provided a work-until time, stop time, deadline, or session end time, invoke `$스케줄릴레이샷` instead of using this open-ended base relay.

11. **Relay Loop Guard**
   - Continue base relay cycles while all are true:
     - the user intent allows continuing
     - the previous push/publication phase is `COMPLETED` or safely `SKIPPED_WITH_REASON`
     - a concrete remaining TODO exists
     - the next task can be completed or advanced safely without creating half-finished risky changes
   - Stop the base relay when no valuable TODO remains, the next task is unsafe, blocked, ambiguous, outside scope, or the user requested a stop.
   - For time-limited stopping, hand control to `$스케줄릴레이샷`.
   - When stopping, record why the relay stopped and what the next concrete task would be.

12. **Final Integration Review**
   - Confirm each phase has a terminal state.
   - Summarize commands run, validation evidence, push/publication result, schedule relay result, remaining risks, and files changed.
   - If any phase is blocked or failed after retry, state the next concrete unblock step.

## Push Safety

Before pushing:

- inspect `git status`
- identify intended files only
- avoid staging unrelated user changes
- verify branch and remote
- use project-specific PR/release workflow when present
- report when push is skipped or blocked

## Output Contract

Final report must include:

- phase status ledger
- tests and validation performed
- push/publication outcome
- relay outcome, including whether another implementation cycle was launched
- explicit relay continuation decision: `CONTINUE_WITH_NEXT_FORM` or
  `STOP_WITH_REASON`
- schedule relay outcome only when a time-limited relay was requested
- residual risks or blockers
- next required human action, if any
