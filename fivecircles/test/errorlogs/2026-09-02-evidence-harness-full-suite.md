# Evidence-Harness full-suite follow-up — 2026-09-02

## Scope

The new branch adds opt-in evidence/orchestration modules. The complete discovery run
used the declared Python 3.12 runtime and `PYTHONPATH=src`.

## Initial result (historical)

- 799 tests ran; 789 passed and 8 expected private-artifact skips remain.
- Two pre-existing evaluation-tree errors are outside this branch's EH1–EH4 scope:
  `baseline_artifact_missing` in the private local-Mini131 contract setup, and an
  import mismatch for `PRIMARY_CATEGORY_ORDER` in the existing performance report.
- New evidence (40), retrieval (36), answering (39), orchestration (35), offline
  diagnostics/gates (24) scoped tests and existing indexing (71) all pass.

## Initial decision (superseded below)

Do not modify the frozen evaluation baseline or manufacture private artifacts to make
the full suite green. Keep these two errors as a pre-existing follow-up for the
baseline owner; the new path's acceptance uses the passing scoped suites plus safety.

## Resolution — EH10

- A missing private suite no longer skips the entire contract class. Only cases that request
  the private fixture skip; synthetic contracts always run. Missing public config and bad hashes still fail.
- Restored four public presentation taxonomy constants expected by the local/API comparison module.
  This changes no gold, answer, score, or semantic rule.
- Final discovery after nonvisual integration: **938 run, 920 passed, 18 private skips, 0 errors**.
  The 18 skips include the original 8 plus 9 private baseline cases and one private performance class.
- New regression distinguishes unavailable ignored data from a real integrity/configuration failure.

The prior two errors are resolved; neither private corpus artifacts nor passing answers were fabricated.
