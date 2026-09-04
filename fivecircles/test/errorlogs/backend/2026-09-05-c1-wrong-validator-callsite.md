# 2026-09-05 — C1 dependency gate applied to compatibility call site

## Symptom

The first validator-integrity repair changed the existing EH2.5
`build_followup_harness_state` call site instead of the new E1-only builder. The new attack test
therefore still accepted a patched-validator clone.

## Cause

The patch matched the first identical `validate_followup_retrieval_outcome(...)` block in the file
without anchoring the enclosing function name.

## Resolution

- Restored the EH2.5 builder to its original validation call.
- Applied the dependency gate only inside `build_e1_followup_harness_state`.
- Kept the failing attack test and reran it after the corrected patch.

## Prevention

- When a file contains repeated calls, patch with the enclosing function signature as context.
- Verify the changed line range before interpreting a red test as an implementation defect.
