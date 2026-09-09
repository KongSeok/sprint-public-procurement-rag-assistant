# Hotline/VLM merge test-harness import path

- Recorded: 2026-09-09T14:32:43+09:00
- Context: external staged run_merged_tests.py invoked from hotline root with PYTHONPATH=src only.
- Symptom:30 `_FailedTest.tests` loader errors; no real test modules loaded. Not30 product regressions and not missing installed dependencies.
- Cause: executing a script outside the repository sets sys.path[0] to the staging directory, unlike `python -m unittest` from the repo root.
- Fix: use PYTHONPATH="$PWD/src:$PWD" with the same established interpreter; no product/test assertion/package modification. Preserve initial outputs separately.
- Result:352 tests,352 unique IDs, failures0/errors0/skips0, exit0. New4 coexistence/CLI tests and imported53 visual tests are included.
- Prevention: for staged runners explicitly add source plus project test root; record unique discovery count and do not count loader errors as exercised tests.
- Merge conflict note: expected3 conflict blocks in TODO/learn-from-log were resolved preserving both histories; no product conflict.
