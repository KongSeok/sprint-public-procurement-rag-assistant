# Local report temporary-worktree fixture hash drift

- Date: 2026-09-01
- Scope: Local Mini131 reproduction-report change
- Command: `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
- Result: report-related tests passed, while seven unrelated supplemental baseline tests rejected copied private index metadata with `index_metadata_hash_mismatch` / `gap30_index_metadata_hash_mismatch`.
- Cause: the isolated report worktree did not own the historical API private index fixture; a fixture copied from another worktree did not match the frozen supplemental receipt hashes.
- Resolution: no production or receipt hash was weakened. The relevant local Mini131 contract, semantic, performance, and shared-scorecard suite passed `35/35`. The complete suite must be rerun from a clean checkout with the exact historical private API index fixture.
