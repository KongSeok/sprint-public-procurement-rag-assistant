---
name: peer-review
description: Review changes and decisions using debate.md as the reference, and also record a human-readable review doc under fivecircles/work/review/. Use when the user says "리뷰해", "리뷰해줘", "peer review", or before merging changes.
---

# Peer Review

This skill performs comprehensive review of changes and architectural decisions.

## Review Checklist

0) Queue first
- Read `fivecircles/agent/queue.json` (and `fivecircles/agent/sync.md` if needed) to identify the current review request(s) and scope.

1) Debate context
- Read `fivecircles/agent/debate.md` for context.

2) Load referenced docs/code
- Follow file refs from debate/review docs/specs and verify actual implementation.

3) Evaluate
- Alignment with specs (`fivecircles/architecture/specs/*`)
- Safety (side effects, schema/routing breaks)
- Completeness (edge cases, rollout)
- Test coverage gaps

4) Record the review in TWO places
- `fivecircles/agent/debate.md`: append a short review block with status and key points.
- `fivecircles/work/review/`: create/update a dated review doc.
  - Path: `fivecircles/work/review/review-<topic>-YYYY-MM-DD.md`
  - Include: Scope, Findings (ordered), Decision (APPROVE/REQUEST_CHANGES), Next actions.

5) If you requested changes
- Update the plan/spec with concrete edits or TODO entries, and re-review the plan for holes.
