# Test Policy

## Development Cycle Alignment

This policy belongs to the Test phase of the development cycle
(Requirements, Design, Implementation, Test, Maintenance).

## Mandatory Pre-Test Check

- (See work/workpolicy.md) This check is required before implementation begins.

## Scope

- Applies to local runs, CI runs, and ad-hoc manual testing.
- Does not change product behavior; it prevents repeatable test failures.

## Local Python Runtime (2026-09-06)

- Run from `/Users/pio/Documents/AIENGINEERCOURSE/MidProjectRAG` with `.venv/bin/python` (current Mac: Python 3.12).
  Check the existing venv before diagnosing dependencies as missing; bare `python` may select Miniconda 3.13.
- Provision full-suite extras using the README installation command; base `pip install -e .` is insufficient.
  Preserve `requirements/gcp-local-lock.txt` pins on this macOS/arm64 runtime and run `.venv/bin/python -m pip check`.
- Full regression command:

  ```bash
  PATH="$PWD/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
    .venv/bin/python -m unittest discover -s tests -t . -p 'test*.py'
  ```

- Focused runs use the same interpreter and `tests.*` module names. `-t .` keeps fixture imports consistent.
- `.index.lock` and macOS `sandbox-exec` integration checks require their actual OS permissions.
  Rerun affected tests with available permissions; do not weaken assertions or count blocked checks as PASS.
- Record the unittest summary, process exit status, skips and reasons. Module import failures can hide additional
  test cases, so a repaired environment may collect more cases than the failing run.

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
