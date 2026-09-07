---
name: 릴레이샷
description: 릴레이샷, relay-shot, relay shot, 원샷딜 마지막 릴레이, push-after-test relay without time limit. Use after doc-write, implementation, test, and push to inspect remaining TODOs, select the next implementable task, re-enter it into the one-shot delivery flow form, and continue without stopping after one or two cycles.
---

# 릴레이샷

## First step: resolve execution mode

Invoking relay-shot defaults to `philosopher-coder`: Astra Design, Sol Ultra
implementation, and fresh Astra Critic at the collaboration review gates.
Before selecting a task or starting implementation, record the resolved mode
in the active flow form. For philosopher-coder, read the collaboration entrypoint
and relay-cycle reference below. Editing or explaining this skill does not itself start a relay.

Use `solo` only when the user explicitly requests it for this run, for example
"단독으로 릴레이샷" or "solo relay-shot". Record that request with the mode.
An old form's implicit solo default is not an explicit user choice. Preserve an
explicit solo choice within the same run until the user changes it.
Carry the resolved mode into each next batch, one-shot form, and timed-relay
handoff; a deadline does not reset the mode. Separate one-shot/one-go requests
outside this relay keep their own selection rules.

Resolve the local `agent/skills/collaboration/SKILL.md` under the verified
fivecircles operating root (repository root for a standalone fivecircles repo,
`fivecircles/` inside a host project); otherwise use the installed sibling skill.
Its `references/relay-cycle.md` owns collaborative role routing, closeout order,
and re-entry. The ordinary lifecycle below applies to explicitly selected solo.
Higher-priority instructions, project authority, required validation, and user
scope still win. If philosopher-coder is selected and its dependency, model or delegation capability is
unavailable, report BLOCKED and request direction; do not silently fall back to
solo or substitute a model. Mode selection does not expand execution permissions.

The same main coordinator returns to DESIGN after closeout. Opening direction
assessment produces a DIRECTIVE, not a candidate PASS. Fresh candidate approval
is a later, separate gate. Do not recursively invoke another relay/root.

This is the default time-unlimited relay skill for one-shot delivery.

Use it at the end of the one-shot delivery flow after closeout report handling
when the user asked to keep going, continue, finish remaining TODOs, or run in
one-go.

In one-shot delivery, this skill also participates at the beginning of each
cycle: consume the latest `$mermaid-flow-report` target/current comparison and
score table, choose the highest safe next unit, and write that unit back into
the one-shot flow form before implementation starts.

Use `$스케줄릴레이샷` instead when the user provided a work-until time, stop time, deadline, or session end time.

## Invocation aliases

Use this skill when the user says or implies:

- 릴레이샷
- relay-shot
- relay shot
- 계속 릴레이
- 시간제한 없는 릴레이
- 원샷딜 마지막 릴레이
- 테스트/푸시 끝나고 남은 TODO 계속

## Core Rule

Relay has two one-shot delivery roles:

- Start-of-cycle: consume the latest `$mermaid-flow-report` score table,
  choose the highest safe next unit, and put that unit into the flow form before
  doc/implementation starts.
- End-of-cycle: after validation, push/publication, and closeout report, inspect
  the refreshed score table and either launch the next one-shot cycle or record
  the stop reason.

At the end of the current one-shot cycle:

1. Confirm documentation, implementation, validation, and push/publication phases reached terminal states.
2. Confirm the closeout `$mermaid-flow-report` has refreshed target/current
   diagrams and the done/not-done score table.
3. Inspect remaining TODOs, logs, plans, issue notes, failing tests, and unfinished acceptance criteria.
4. Select the highest-value concrete task that can be safely started now.
5. Re-enter the selected task into the One-Shot Delivery Flow Form below.
6. Record the explicit continuation decision:
   - `CONTINUE_WITH_NEXT_FORM` when the next task is selected and the fresh
     flow form has been filled.
   - `STOP_WITH_REASON` when relay stops, with the concrete stop reason and
     the next task that would have run if unblocked.
7. Invoke or follow the relevant one-shot execution skills for that filled form:
   - `doc-contract-writer` for contract/document work.
   - `one-go` for implementation.
   - `batch-sequential-runner` when a batch or recursive TODO exists.
   - `test-runner` for validation.
8. Continue through the full flow again: report, relay unit selection, doc-write, implementation, validation report, push, closeout report, relay.
9. Repeat until a Stop Condition is met. Do not stop merely because one or two relay cycles have completed.

## Relay Re-entry Protocol

When a next task is found, do not just report it. Convert it into a new
one-shot cycle using this form, then start that cycle immediately when safe.

If multiple candidates exist, select one concrete task using this order:

1. User-explicit next task or active batch.
2. Failing test, broken runtime, or security regression.
3. Highest-priority open TODO with clear acceptance criteria.
4. Documentation/contract blocker for the next implementation batch.
5. Smallest safe task that unlocks later work.

Never launch multiple unrelated tasks at once. If the chosen task is too broad,
create a recursive TODO and run the first bounded subtask through the form.

## Target Flow Node Connection Scoring

When the remaining work involves workflow, routing, planner/provider behavior,
security/privacy, wrapper dispatch, RAG, GraphDB, or agent control flow, do not
select the next task by intuition alone. Score the remaining gaps against the
target Mermaid flow and choose the task that connects the highest upstream
unmatched node/edge with the fastest validated path to the target.

For project-specific Admin AI flow work, resolve the provider policy flow
validation ledger from the active workspace using repo-relative paths:

- Skill-folder relative path:
  `../../../architecture/specs/AIConsolLayers/provider-policy-flow-validation.md`
- Repository-root relative path:
  `fivecircles/architecture/specs/AIConsolLayers/provider-policy-flow-validation.md`

as the live flow ledger. At the end of each one-shot cycle, update that file's
current implemented Mermaid flow and path-check notes to reflect the exact
latest state from the just-finished work. Do this before claiming the relay
cycle is closed.

Path convention: global mirrors under `~/.codex/skills` or `~/.agents/skills`
must resolve repo-relative paths against the active workspace root. Do not
hard-code personal, machine-local, or project-specific absolute paths in this
skill.

Scoring protocol:

1. Read the target Mermaid from the authoritative flow document.
2. Read the current implemented Mermaid from the same file.
3. Walk the target graph from the top/root node downward.
4. For each unmatched or partial node/edge, assign:
   - `upstream_weight`: 0-4. Earlier/top-level nodes score higher because they
     affect every downstream route.
   - `connection_value`: 0-3. How many downstream target edges become reachable
     if this gap is closed.
   - `safety_value`: 0-2. Security/privacy/provider-boundary gaps score higher
     than copy/UI polish.
   - `validation_value`: 0-2. Higher when a small targeted test or Mermaid
     path-check can prove the fix quickly.
   - `risk_penalty`: 0 to -3. Subtract for broad migrations, production-data
     risk, or large unknown blast radius.
5. Compute `connection_score = upstream_weight + connection_value +
   safety_value + validation_value + risk_penalty`.
6. Choose the highest score that is still safe to start now.
7. If two scores tie, choose the earlier target-flow node. If still tied, choose
   the task with the smallest verifiable patch.

The selected next task must be written back into the One-Shot Delivery Flow
Form with its score and the target node/edge it connects.

## One-Shot Delivery Flow Form

Fill this form before launching the next cycle. Keep it concise, but every line
should have a useful value or an explicit `SKIPPED_WITH_REASON`.

```md
0. Scope Intake
- 실행 모드: philosopher-coder (기본) / solo (명시적 사용자 요청 근거):
- 협업 선택 시: philosopher-coder / run_id / batch_id / 실제 역할 agent/model/effort:
- 요청 범위:
- 브랜치:
- 사용자 제약:
- 완료 기준:
- 위험/확인 필요:

1. Start Report / Target Check
- 협업 선택 시: Design 방향 판단 / selected_task_ref / DIRECTIVE / 보고 재사용 fingerprint:
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
- 상태: TODO / COMPLETED / SKIPPED_WITH_REASON / BLOCKED

4. Implementation
- 사용할 스킬: one-go
- batch가 명시된 경우: batch-sequential-runner
- 재귀 TODO:
- 수정 대상:
- 상태:

5. Validation + Report
- 협업 선택 시: candidate_id / contract_id / test_evidence_id:
- 사용할 스킬: test-runner
- 필수 리포트 스킬: mermaid-flow-report
- 자동 테스트:
- 빌드/lint:
- Playwright/browser smoke:
- 현상태 Mermaid 플로우맵:
- 도달 경로 체크:
- provider-policy-flow-validation.md 갱신:
- 타겟 노드 연결 점수:
- 상태:
- 결과:

6. Repair Loop
- 협업 선택 시: fresh REVIEW 참조 / 동일 후보 결속 / 미해결 QUESTION / 재검수:
- 실패 원인:
- 수리 배치:
- 재테스트:
- 상태:

7. Push / Publication
- 협업 선택 시 선행 마감: closeout report + logall 참조(batch_id 중복 확인):
- 협업 선택 시 통합 권한·실제 receipt 참조 또는 SKIPPED/BLOCKED 이유:
- git status 확인:
- 커밋 범위:
- 커밋:
- 푸시:
- 상태:

8. Closeout Report
- 협업 선택 시: 통합 전 보고 확인·사후 receipt 연결(중복 생성/자기 SHA 커밋 금지):
- 사용할 스킬: mermaid-flow-report
- 시작 타겟 대비 최종 현재 플로우:
- 남은 GAP/PARTIAL:
- 다음 점수표 갱신:
- 상태:

9. Relay Shot
- 협업 선택 시: CONTINUE_WITH_NEXT_FORM / STOP_WITH_REASON 및 실제 다음 dispatch 참조:
- 사용할 스킬: relay-shot
- 확인한 TODO source:
- 다음 후보:
- 선택한 다음 작업:
- 새 원샷딜 시작 여부:
- 멈춘 이유, 있으면:

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

## Anti Premature Stop Rule

The relay is time-unlimited by default. After push/publication, always inspect
the TODO sources again and run the re-entry protocol. Stopping after one or two
cycles is a failure unless a Stop Condition is explicitly true.

## Flow Diagram Verification Gate

Before declaring any target workflow "reached", "done", "closed", or
"aligned", the final validation must include a flow-diagram comparison. Do not
close by prose or checklist alone.

When producing that comparison, invoke or follow `$mermaid-flow-report` so the
validation creates or updates both the Markdown ledger and the browser-readable
HTML report with Mermaid-generated PNGs.

Required closeout evidence:

1. Include or link the target Mermaid flow diagram.
2. Include or link the current implemented Mermaid flow diagram.
3. For project-specific Admin AI flow work, update
   `../../../architecture/specs/AIConsolLayers/provider-policy-flow-validation.md`
   from the repo-local skill folder, or the repo-root relative
   `fivecircles/architecture/specs/AIConsolLayers/provider-policy-flow-validation.md`
   from the active workspace root.
   with the latest current implemented Mermaid flow from the final state of the
   just-finished work.
4. Compare the diagrams node-by-node and edge-by-edge.
5. Mark each mismatch as one of:
   - `MATCHED`
   - `INTENTIONAL_SERVER_CONTROL_EXCEPTION`
   - `PARTIAL`
   - `GAP`
6. If any `GAP` remains, do not claim target reached. Create or update the next
   recursive TODO and relay into that work.
7. If a shortcut, fast-path, deterministic route, retriever, RAG, semantic
   memory, GraphDB, or provider call appears earlier than the target diagram
   allows, it is a `GAP` unless the diagram labels it as an exact
   server-owned control such as confirm, dismiss, cancel, or active-preview
   revision.
8. Score remaining gaps using Target Flow Node Connection Scoring and select
   the next relay task from the highest safe score, not from prose preference.
9. The final ledger must state: `Flow diagram verification: MATCHED` or
   `Flow diagram verification: GAP/PARTIAL`, with the reason.

## Stop Conditions

Stop instead of launching the next cycle when:

- no valuable remaining TODO exists
- the next task is ambiguous or outside the requested scope
- the next task is unsafe to start without user input
- the previous push/publication phase is `BLOCKED`
- the user asked to stop
- a time limit exists, in which case hand off to `$스케줄릴레이샷`

## Remaining Work Sources

Inspect the most relevant available sources:

- `todolist.md`
- `TODO.md`
- `fivecircles/architecture/todolist.md`
- `fivecircles/work/`
- `fivecircles/test/errorlogs/`
- `fivecircles/requirements/`
- `fivecircles/architecture/specs/`
- issue or PR notes
- current conversation acceptance criteria

## Output Contract

Report:

- previous phase statuses
- TODO source inspected
- selected next task, if any
- the filled One-Shot Delivery Flow Form for the selected task
- the explicit continuation decision: `CONTINUE_WITH_NEXT_FORM` or
  `STOP_WITH_REASON`
- whether another one-shot cycle was launched
- outcome or stop reason
- final flow diagram verification result when the task touches workflow,
  routing, planner, provider, security, wrapper, RAG, GraphDB, or agent control
  flow
