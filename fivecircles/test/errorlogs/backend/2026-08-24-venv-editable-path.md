# Venv Editable Path Not Activated

- Date: 2026-08-24 19:12 KST
- Stage: Test
- Failing command: `.venv/bin/python -m unittest tests.ingest.test_extract -v`
- Error: `ModuleNotFoundError: midprojectrag`; the editable `.pth` path was not added by the bundled runtime.
- Fix plan: run repository tests with explicit `PYTHONPATH=src`; keep `.venv` for declared extractor dependencies.
