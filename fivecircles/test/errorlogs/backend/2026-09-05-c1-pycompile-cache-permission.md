# 2026-09-05 — C1 py_compile cache permission recurrence

## Symptom

`python -m py_compile` failed with `Operation not permitted` while attempting to create a temporary
file under `src/midprojectrag/orchestration/__pycache__` in the actual repository root.

## Cause

`py_compile` explicitly writes bytecode even when `PYTHONDONTWRITEBYTECODE=1` is set. The current
sandbox can execute/read the authority repository but cannot create that cache file.

## Resolution

- Used write-free unittest imports and executions as the syntax/runtime gate.
- Kept all test commands on `PYTHONDONTWRITEBYTECODE=1`.
- Did not request a broader filesystem permission merely to create cache artifacts.

## Prevention

- Do not use `py_compile` as a write-free check outside the writable root.
- Prefer the focused and full unittest imports already required by the test policy.
