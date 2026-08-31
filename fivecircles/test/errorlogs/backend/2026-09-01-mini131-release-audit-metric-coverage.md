# Mini131 release-audit metric coverage gap

- Date: 2026-09-01 00:52 KST
- Stage: local Mini131 release audit
- Scope: aggregate scorer and preflight completeness; no private case content

## Issue

- The completed 129-RAG score omitted set count accuracy, visual target-granularity metrics and analytics exact/tolerance aggregates.
- Preflight covered set map batches but did not report the worst-case global consolidation prompt budget.

## Root cause

- Suite completion and generic retrieval/contract metrics were wired before every lane-specific acceptance metric was projected into the aggregate receipt.

## Resolution

- Added the missing lane aggregates and metric-coverage counts while keeping candidate errors in their original denominators.
- Added global-set token accounting with a fail-closed overflow policy before model transport.

## Pass evidence

- Scorer rerun and content-free receipt validation passed with `metric_coverage.complete=true`.
- Set-map preflight is 5,094 tokens; the 102,687-token worst-case final stress probe is rejected before transport.

## Prevention

- Release review must map every frozen lane requirement to an aggregate metric key and test preflight for both map and global-reduce prompts.
