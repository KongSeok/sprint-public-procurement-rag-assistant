# Evidence-Harness Relay

## Earlier cycle EH0–EH6 (historical)

Core interfaces, bounded loop, evidence adapter, diagnostics and offline export gates were committed
in `bd9a991` / `876eea6` and pushed. They were predominantly synthetic-tested. The prior statement
that empty artifact pins left no implementation work was too broad: local KURE artifacts existed,
and the CLI had neither the dense adapter nor a real list enumeration route.

## Resumed cycle EH7–EH10 — 2026-09-02

0. Scope: user confirmed multimodal embedding/actual visual reader deferred; continue nonvisual runtime.
1. Docs: updated [plan](evidence-harness-transition-plan.md),
   [contract](../architecture/specs/evidence-harness-contract.md) and [TODO](../architecture/todolist.md).
2. Artifact check: 98 docs / 9,331 page vectors / 18,844 Evidence verified with pinned hashes;
   read-only original corpus/cache, no document re-embedding.
3. Implementation: page-dense + child-lexical RRF; exhaustive scoped list scan/reduce;
   bounded verifier preparation; mandatory-only generation context; v2 runtime config seals.
4. Validation: full suite **938 run, 920 pass, 18 expected private skips, 0 errors**; compile PASS.
   Baseline configs, legacy pipeline and pinned provider transport remain unchanged from the branch base.
5. Live: synthetic fact answered; synthetic list scanned 3/3, returned/cited both matching documents.
   Corpus followup outcomes and hashes are maintained in the [report](evidence-harness-report.html).
6. Repairs: private fixture class-level skip narrowed; taxonomy import restored;
   list-vs-attributes planner ambiguity corrected; verify failure input retained; call timeout explicit;
   optional duplicate/irrelevant generation context excluded by the CLI policy.
7. Report: both target/current PNG available and visually inspected. Local HTML browser access remains
   policy-blocked; static structure, links and images are checked without bypassing the browser policy.
8. Delivery: only feature-owned public source/tests/docs staged. Private corpus, requests and traces stay ignored.
   Delivery commit is recorded on `feat/evidence-harness-v1`; remote status is checked after push.
9. Third-golden-set binding: `third-integrated-evaluation-inventory-v3` preflight now validates the lane-specific package and produces 109 nonvisual runtime requests. Gold/qrels stay outside runtime requests; visual 10, analytics 10 and parser 2 remain separate lanes. The package is provisional (approved 0/131).
10. Response execution is pending local Ollama availability: the attempt to bind `127.0.0.1:11434` was blocked by the current sandbox, so no fabricated answers or score were written. The private request pack is preserved; Sol semantic scoring remains a TODO.
11. Next scope: same-gold quality/resource comparison, learned reranker/policy, GCP execution and visual activation
   are separate unfinished experiments, not automatically approved production rollout.

## Completion meaning

This is nonvisual local implementation and diagnostic validation, not a trained evoHarness policy,
full-corpus list latency guarantee, semantic-score improvement, or baseline promotion.
Failures remain in private receipts; public docs disclose outcome and limits without source text.
