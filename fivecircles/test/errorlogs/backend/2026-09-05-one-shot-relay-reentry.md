# 2026-09-05 — one-shot relay re-entry omission

## Context

- Branch: `feat/total-integration`
- Previous leaf: `EH2.6.b5`
- Required relay: `CONTINUE_WITH_NEXT_FORM` → `EH2.6.c1`

## Symptom

The B5 implementation, validation, logall, commit, and push completed, and the relay record named
`EH2.6.c1`. The turn still ended without opening a fresh one-shot flow form or starting that READY
leaf.

## Root cause

Leaf closeout was incorrectly treated as the terminal condition for an open-ended relay request.
The post-push relay decision was written as documentation but was not enforced as an execution
transition.

## Resolution

- Re-read the repository one-shot protocol, relay-shot skill, logall policy, and test/work policy.
- Opened Cycle 4 with a complete flow form and numeric relay score.
- Selected `EH2.6.c1` and entered its contract/test/implementation cycle immediately.

## Prevention

- With an open continuation request and a safe actionable TODO, `CONTINUE_WITH_NEXT_FORM` forbids a
  final response after push.
- A continuing cycle is complete only after the next cycle's fresh flow form is durably recorded
  and execution has begun.
- Stop only with an explicit `STOP_WITH_REASON` backed by a blocker, unsafe action, ambiguity that
  changes scope, or absence of valuable READY work.
