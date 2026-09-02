# Optimization Notes (Scoring)

Purpose
- Collect score-maximizing optimizations discovered during work.
- Reference this file when scoring to capture any applicable upgrade paths.

Log format (append each optimization):

Timestamp:
Area:
Optimization:
Why it increases score:
When to apply:
Related tasks/files:

Timestamp: 2026-09-02
Area: Evidence-Harness runtime validation
Optimization: Smoke-test true list membership and history-dependent multi-attribute routing separately;
deduplicate exact same-source text before verification and generate from mandatory verified evidence only.
Why it increases score: Prevents synthetic transport success from being mistaken for corpus/runtime quality;
reduces irrelevant generation context without dropping planned support.
When to apply: Before nonofficial local-profile comparison or future model promotion.
Related tasks/files: orchestration/llm.py, controller.py, local_runtime.py and the live-routing-budget error log.
