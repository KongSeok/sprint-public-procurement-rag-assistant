# Mini131 semantic adjudication workflow mismatch

- Date: 2026-09-01 01:08 KST
- Stage: fresh local Mini131 semantic merge
- Error: `local_mini131_semantic_adjudication_workflow_invalid`
- Scope: content-free workflow metadata only

## Issue

- The merge failed closed because the primary/secondary decisions required three adjudications while the supplied adjudicator ledger contained four.
- There were no missing decisions; one decision was outside the freshly derived trigger set.

## Resolution

- Regenerated adjudication inputs from the validated primary/secondary ledgers and performed a fresh review of exactly three rows.
- Merge then passed with role counts primary 129, secondary 4 and adjudicator 3; no prior semantic decision was silently accepted.

## Prevention

- Derive adjudication input exclusively from the current validated trigger set and require exact set equality before merge.
