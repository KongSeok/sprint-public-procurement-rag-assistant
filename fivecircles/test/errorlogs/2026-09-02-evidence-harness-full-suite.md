# Evidence-Harness full-suite follow-up — 2026-09-02

## Scope

The new branch adds opt-in evidence/orchestration modules. The complete discovery run
used the declared Python 3.12 runtime and `PYTHONPATH=src`.

## Result

- 786 tests ran; 776 passed and 8 expected private-artifact skips remain.
- Two pre-existing evaluation-tree errors are outside this branch's EH1–EH4 scope:
  `baseline_artifact_missing` in the private local-Mini131 contract setup, and an
  import mismatch for `PRIMARY_CATEGORY_ORDER` in the existing performance report.
- New evidence (40), retrieval (36), answering (39), orchestration (35), offline
  diagnostics/gates (24) scoped tests and existing indexing (71) all pass.

## Decision

Do not modify the frozen evaluation baseline or manufacture private artifacts to make
the full suite green. Keep these two errors as a pre-existing follow-up for the
baseline owner; the new path's acceptance uses the passing scoped suites plus safety.
