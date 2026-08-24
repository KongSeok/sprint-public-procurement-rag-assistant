# Test Policy

## Development Cycle Alignment

This policy belongs to the Test phase of the development cycle
(Requirements, Design, Implementation, Test, Maintenance).

## Mandatory Pre-Test Check

- (See work/workpolicy.md) This check is required before implementation begins.

## Scope

- Applies to local runs, CI runs, and ad-hoc manual testing.
- Does not change product behavior; it prevents repeatable test failures.

## Log Formatting (Mandatory)

- Every test error log must include a timestamp (local date and time).
- Write each error summary as a separate text file under `test/errorlogs/`.
- Separate backend and frontend logs into `test/errorlogs/backend/` and `test/errorlogs/frontend/`.
- After tests, record error logs and fixes in the appropriate folder.
- When an error is resolved, record the resolution in `test/learn-from-log.md`.

## Token-lite Logging (Default)

- Keep error logs concise and avoid duplicating long explanations from update logs.
- Use 1–2 bullets per section; link to related files instead of repeating details.
- Prefer short, actionable root cause and fix statements.

## Test Results (Mandatory)

- On SUCCESS, record the result in `work/update.md`.
- On FAIL, write an error log under `test/errorlogs/` and record the resolution in `test/learn-from-log.md` once fixed.
- On SUCCESS after a resolved failure, add a recurrence-prevention rule to `test/learn-from-log.md`.

## Docker-backed Tests (Mandatory)

- If a test requires Docker commands, follow `fivecircles/architecture/specs/docker.md` and the active environment constraints.
