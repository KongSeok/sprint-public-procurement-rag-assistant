# Supplemental evaluation contract drift

- Timestamp: 2026-08-31 14:52:00 +0900
- Failure: CLI signature and DTO field-set edits briefly diverged; one diagnostic also reused zsh's read-only `status` name.
- Fix: aligned parser/function/schema/manual validators/tests and used `eval_exit_code`; focused 61/61 and full 524/524 passed.
