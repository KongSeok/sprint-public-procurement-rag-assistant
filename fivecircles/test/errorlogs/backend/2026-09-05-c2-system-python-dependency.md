# EH2.6.c2 system Python dependency mismatch

- Date: 2026-09-05
- Scope: semantic-verification preflight regression

## Symptom

`PYTHONPATH=src python3 -m unittest tests.test_execution_contracts -q` failed during import with
`ModuleNotFoundError: No module named 'numpy'` and ran zero tests.

## Cause

The shell's Homebrew system Python is not the repository's declared bundled runtime and does not contain the
project dependency set. The failure happened before collection and was not a product-code regression.

## Fix and verification

The same focused suite was rerun with the documented repository runtime:

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m unittest tests.test_execution_contracts -q`

Result: 17/17 PASS.

## Prevention

Use `.venv/bin/python` plus explicit `PYTHONPATH=src` for every harness unittest command. Treat a system-Python
import failure as an environment mismatch and never report it as a failing product test.
