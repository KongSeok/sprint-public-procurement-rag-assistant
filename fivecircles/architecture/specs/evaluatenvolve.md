# Evaluate and Evolve

This document describes how the system should evolve into better versions
without breaking core specifications.

## Reference

- Promoted implementation constraints live in `fivecircles/architecture/specs/implementation-rules.md`.

## Evolution Goal

- Reduce repeat failures by turning costly error fixes into design rules.
- Preserve the active RAG contracts and data boundaries.
- Improve implementation efficiency while keeping behavior stable.

## Evaluation Criteria

Use these criteria when deciding whether to update specs or fix post-implementation:

- Frequency: Will this error reappear across services?
- Cost: Does the fix require changes in multiple layers?
- Risk: Does it affect data integrity or workflow correctness?
- Scope: Is this a systemic rule or a local environment issue?

## Decision Rule

- If Frequency + Cost + Risk are high, update specs.
- If Scope is local or environment-specific, fix in code and document in test/learn-from-log.md.

## Conflict Policy (Mandatory)

- New rules must not conflict with existing specs.
- If a conflict is discovered, explain why the change is beneficial and request user approval before modifying the original rule.

## Controlled Evolution Loop

1) Observe: Capture runtime errors and root cause.
2) Classify: Decide if the issue is systemic.
3) Promote: Add systemic rules to specs if cost-effective.
   - If promoted, record them in `fivecircles/architecture/specs/implementation-rules.md`.
4) Implement: Apply fixes consistently across services.
5) Verify: Confirm behavior still matches the active requirements and contracts.

## Repeatable Error Cycle (Mandatory)

When a runtime error is confirmed:

1) Log the issue in test/learn-from-log.md.
2) Evaluate with the criteria above.
3) If systemic, promote into specs/implementation-rules.md.
4) Apply changes to all relevant services.
5) Re-test and record results.

## Pre-Test Check (Mandatory)

- Before any test execution, review test/testpolicy.md and test/learn-from-log.md to avoid repeating known failures.

## Examples

Promote to specs:
- Deterministic manifest and source-block IDs
- Parser timeout and explicit failure states
- Citation and evaluation reference invariants

Keep in error folder:
- Local parser installation timing
- Developer machine constraints
