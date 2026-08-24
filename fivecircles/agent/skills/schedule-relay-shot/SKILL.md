---
name: 스케줄릴레이샷
description: 스케줄릴레이샷, schedule-relay-shot, schedule relay shot, time relay shot, 시간조건 릴레이, 푸시 후 릴레이, push-after-test relay. Use at the end of one-shot delivery after validation and push/publication; check the current time against the user-designated stop time, then launch the next implementable remaining TODO with $one-shot-delivery-orchestrator if time remains.
---

# 스케줄릴레이샷

This is the time-limited relay skill for the end of a work cycle.

The base one-shot relay is not time-limited and lives in `$one-shot-delivery-orchestrator`.
Use this skill only when the user supplied a time limit.

## Invocation aliases

Use this skill when the user says or implies:

- 스케줄릴레이샷
- schedule-relay-shot
- schedule relay shot
- time relay shot
- 시간조건 릴레이
- 푸시 후 릴레이
- push-after-test relay
- 테스트/푸시 끝나고 시간 남으면 계속

Use it after validation and push/publication handling when the user has provided a work-until time, stop time, deadline, session end time, or similar time condition.

In the one-shot delivery package, this skill runs after the push/publication phase. If there was nothing to push, it runs after that phase is explicitly marked `SKIPPED_WITH_REASON`.

## Core Rule

At the end of the current task:

1. Check the current time with a reliable command or tool.
2. Resolve the user's target time into an exact date, time, and timezone.
3. If the target time has passed or no actionable time remains, stop and report completion.
4. Confirm the previous push/publication phase reached `COMPLETED`, `SKIPPED_WITH_REASON`, or `BLOCKED`.
5. If the target time has not passed and the previous block does not make continued work unsafe, inspect remaining TODOs, logs, plans, issue notes, or unfinished acceptance criteria.
6. Choose the highest-value remaining task that can reasonably fit the remaining time.
7. Invoke or follow `$one-shot-delivery-orchestrator` to continue that task end to end through implementation, validation, repair, and push/publication.

## Time Handling

- Use the user's timezone when known.
- If the user gives a relative time such as "until 6" or "before dinner", convert it to a concrete timestamp before deciding.
- If the target time is ambiguous and the remaining work could be risky, ask one concise clarification.
- If the target time is clear, do not ask; continue or stop based on the comparison.

## Remaining Work Sources

Inspect the most relevant available sources:

- `todolist.md`
- `TODO.md`
- `fivecircles/work/`
- `fivecircles/test/errorlogs/`
- `fivecircles/requirements/`
- `fivecircles/architecture/specs/`
- issue or PR notes
- the current conversation's unfinished acceptance criteria
- failing test output or validation gaps

## Relay Selection

Prefer work that:

- unblocks the current delivery
- fixes known test, build, validation, or user-flow failures
- completes an already-started batch
- reduces deployment or push risk
- is explicitly marked next, urgent, or remaining

Avoid starting broad refactors, speculative features, or unrelated cleanup just because time remains.

## Output Contract

When the relay stops, report:

- current time checked
- target time used
- previous push/publication phase status
- whether the relay continued or stopped
- TODO source inspected
- task selected, if any
- outcome of the follow-on one-shot delivery cycle, including implementation/test/push status
- remaining gaps or why no further work was started
