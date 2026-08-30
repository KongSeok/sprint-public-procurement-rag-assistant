# One Shot Delivery Ledger — HWP Visual Corpus Rollout

Run ID: `2026-08-28-hwp-visual-corpus-rollout-v1`
Mode: sequential, contract-first, local-only until explicit egress approval
Selected relay unit: **5-document fidelity gate + resumable 94-HWP visual rollout** (score 10)

## Flow form

| Phase | State | Evidence / exit condition |
| --- | --- | --- |
| 0 Scope intake | COMPLETED | User confirmed 5 representative types → 94 full corpus → proceed if green |
| 1 Start report / target check | COMPLETED | Target/current flow and explicit external boundary fixed |
| 2 Relay unit selection | COMPLETED | Highest safe local unit, score 10, selected |
| 3 Documentation / contract | COMPLETED | Inputs, outputs, fidelity gates, failure semantics and tests frozen |
| 4 Implementation | COMPLETED | Resumable bundle runner, exact asset resolver, provenance policy, v2 corpus and local index |
| 5 Validation + report | COMPLETED | 5/5, 94/94, all-reuse, full artifact/schema/index audit, 388 tests, browser QA |
| 6 Repair loop | COMPLETED | Corpus failures and independent strict-reuse P1 findings repaired and reverified |
| 7 Push / publication | SKIPPED_WITH_REASON | No Git remote; shared worktree contains extensive unrelated user changes |
| 8 Closeout report | COMPLETED | Mermaid/PNG/HTML end report and aggregate quality boundary updated |
| 9 Relay shot | BLOCKED | Human fidelity and external semantic activation require user review/approval |
| 10 Final ledger | COMPLETED | Every phase terminal; no unclassified local action remains |

## Completed batches

1. strict bundle verifier, corpus report Schema and resumable sequential CLI
2. deterministic five-document selection and two-run hash/fidelity gate
3. exact 94/94 rollout and immediate all-reuse run
4. full-overlay visual-context v2 chunk materialization
5. provider-free index, RRF/citation smoke, independent full audit and report QA

## Delivery ledger

- Documentation phase: COMPLETED
- Implementation phase: COMPLETED
- Validation phase: COMPLETED
- Repair loop: COMPLETED
- Blocked: five-document human fidelity gold; external embedding/index/default-runtime activation until
  explicit destination-specific private corpus egress and cost approval
- Failed after retry: none
- Skipped with reason: commit/push/publication; repository has no configured remote and the shared worktree
  includes unrelated user work that must not be bundled into an inferred commit
- Remaining actionable in the approved local scope: none

## Gate evidence

- Gate A: 5/5 materialized, failed 0; second run 5/5 reused with identical digest. Known p.7 schedule
  and p.8 image occurrence regressions passed.
- Gate B: 94/94 succeeded, failed 0; second run 94/94 reused. Pages 8,762, tables 10,787,
  images 950, ordered occurrences 77,607. Corpus digest
  `54e84f5311c66f7c03c8298686a6ceb24c82cb949176db54060c417c8b418ad2`.
- Asset evidence: supported source references 440, per-document unique sum 410, global canonical objects
  406, unsupported WMF/GIF source records 12. Strict render links 58; asset-only 382; render-only 498.
- Gate C: 94 documents and 35,128 visual-context v2 chunks, prior context 19,828, strict schedule
  context 70. Two runs share chunk SHA
  `70444db8b0fb6a26138f3c2d53b701009141e713c879750ba2ec6c928c6b66e0`.
- Local index: 35,128 × 2,048 float32 vectors; second build 35,128/35,128 cache hits. Independent
  reconstruction found zero vector mismatches. Three known-query variants put the target fact at table rank 1;
  fused matching evidence occupied ranks 1–3 and the cited table was rank 2.
- Full independent audit: 124,568 Schema instances, errors 0; 94/94 strict bundle verification; v2
  record regeneration and local index identity matched.

## Repair history

The first 94-document diagnostic completed 68 and isolated 26 failures without partial success claims:

- 17 ambiguous DocLang URIs: replaced filename prefix/ordinal guessing with exact path or exact pinned-OTSL
  ancestry reconstruction; all 452 picture references reconciled structurally.
- 4 out-of-page image bboxes: preserved ordered occurrence but forced render/link identity to null.
- 5 source-format cases: magic-led canonical type, raw/canonical dual provenance, PNG trailer normalization,
  and explicit WMF/GIF unsupported source records.
- Independent format audit found strict reuse trusted persisted object dimensions and incomplete status fields.
  Reuse now re-parses canonical bytes, enforces status-specific render/link proof and rejects mixed
  verified/unsupported ordinal states.
- Independent loader audit found `.hwpx` could expand the frozen exact-94 `.hwp` set. Visual-v2 completeness
  now binds to `.hwp` only while legacy table-v1 subset behavior remains unchanged.
- Repository safety initially matched the `sk-` substring inside a policy slug. The detector now requires a
  token boundary without weakening real secret-key detection; safety then passed.

## Verification

- Focused ingest, indexing, format and retrieval reviews passed.
- Full `unittest`: 388/388.
- `compileall`, `git diff --check`, shell syntax and repository safety passed; safety scanned 516 files.
- Chromium report QA at 1,440, 1,024 and 390 px: zero overflow, all images loaded, page errors 0.
- External parser/embedding/search API calls: 0. External cost: USD 0.
- Canonical page/table/source identity changed by this rollout: 0.

## Quality and approval boundary

Local completion means source assets are preserved and only provable table/image links are exposed. It does not
mean OCR, diagram semantics, every image page placement, PDF verified tables, or default runtime activation.
Those claims remain blocked until private human comparison and the relevant destination/cost approval.
