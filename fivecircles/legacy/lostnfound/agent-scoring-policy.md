Agent Scoring Policy (Authoritative)

Purpose

This policy defines a quantitative incentive system for agent execution quality.
It does not define system behavior.
All behavioral authority remains in higher-level specs.

Scoring Dimensions

Total Score = Progress + Quality + Spec Alignment + Ops Efficiency

A. Progress
Event	Score
Complete 1 task from architecture/todolist.md	+30
Implement 1 API endpoint defined in api-contract.md	+15
Complete 1 frontend route with proper guards	+20
Schema change aligned with lnf-migration.sql	+20

B. Quality
Event	Score
Mandatory test scenario passed	+40
Error fixed + logged in learn-from-log.md	+35
Core evaluation axis verified (role / state / sorting)	+50

C. Spec Alignment (Critical)
Violation	Score
Violate workflow.md / data-model.md / api-contract.md	-120
Invent API path or omit /api prefix	-80
Violate matching sort rules	-70
Break runtime stack policy	-60

D. Ops Efficiency
Event	Score
Single-layer focused change	+10
Same error repeated twice	-30
Same error repeated three times	-80
Skip pre-test check	-50
Ignore explicit user instruction	-20

Level System
Level	Requirement	Capability
Lv0	0–99	Single task only
Lv1	100–299	Multi-step task
Lv2	300–599	Cross-service work
Lv3	600+	Spec evolution proposal allowed

Level drops by 1 if any critical spec violation occurs in the last 10 events.

Log Requirement

Each task must record:

RESULT:
SCOPE:
SPEC:
POINTS:
REASON:

Scoring Timing

- Scores are recorded only after successful implementation or verified completion.
- Attempts or incomplete changes are not scored.
GAIN:
LOSS:
TOTAL_POINTS:
UPGRADE:

If no higher-score path exists, record: "Optimization bonus +10" in UPGRADE.
If a higher-score path exists, record it in `scoring/optimization.md`.

Notes

This policy is non-behavioral

It must not override higher-priority specs

Conflicts must be reported, not resolved here
