# EVO35.3 training relay - start form

Run: `evo35-train-20260909`. Date: 2026-09-09. Contract: `evo35-train-eval-v1`.

## 0. Scope Intake
- 실행 모드: **solo**, explicit user request; no external Coder/Critic/delegation. Development/collaboration model restriction: none. Application experiment baseline remains Qwen3.5-9B for comparability.
- 요청 범위: training/eval pipeline -> follow-up ID confusion repair -> frozen Mini131 PRE -> non-golden collection -> SFT -> GRPO -> PRE/POST + sealed holdout.
- 브랜치: `feat/hotline-runtime`, start `a800ff0` and clean/tracking origin.
- 사용자 제약: Mini131 questions excluded from training; keep source/privacy/scope/citation guards; continue relay-shot solo.
- 완료 기준: each requested batch reaches COMPLETED/BLOCKED/FAILED_AFTER_RETRY/SKIPPED_WITH_REASON; no silent early stop.
- 위험: Mini131 is already exposed historical benchmark, not sealed holdout; serving Transformers<5 conflicts with current TRL agent environment requirements; actual training resource budget not yet frozen.

## 1. Start Report / Target Check
- 사용할 스킬: mermaid-flow-report, relay-shot, doc-contract-writer, one-go, batch-sequential-runner, test-runner.
- 기준 타겟: repaired typed episode state -> frozen PRE -> non-golden trajectory/split -> SFT -> bounded GRPO -> POST historical + new sealed holdout.
- 현재: Qwen3.5 prompt policy/text/OCR/VLM live; 378 scoped tests; follow-up ID confusion unresolved; no training files/runs.
- score candidates: 3b typed protocol 4+3+2+2-2=9; 3a training skeleton 4+3+2+2-1=10, but 3b schema must be fixed before exported positive training data. Execute contract/skeleton schemas and typed protocol in one sequential wave, then freeze.
- 상태: CONTINUE.

## 2. Relay Unit Selection
- TODO source: `fivecircles/architecture/todolist.md` EVO35, current conversation.
- 선택: `EVO35.3a + schema-defining subset of EVO35.3b`, sequential; typed protocol acceptance is the integration gate before 3c.
- 상태: SELECTED.

## 3. Doc / Contract
- New: `fivecircles/architecture/specs/evo-training-policy.md`.
- Update: D-029, current requirements, active TODO, spec inventory, this work form.
- Contract: Mini131 exclusion, hist/cand/ev types, split freezer, action-only SFT, externally gated reward, isolated TRL/Transformers training environment, PRE/POST discipline.
- 상태: IN_PROGRESS.

## 4. Implementation
- Execution mode: sequential.
- 3a: pure training schemas/exclusion/split/SFT exporter/reward/preflight scripts with no serving dependency upgrade.
- 3b: hist/cand/ev policy boundary; current candidate only for read/inspect and read/inspected evidence only for answered finish.
- 상태: PENDING_DOC.

## 5. Validation + Report
- Unit first, then existing Evo/visual/hotline impact suite.
- Real live follow-up only after same-candidate tests and model/artifact preflight; <=120s.
- Flow target/current + PNG/HTML/browser at delivery boundary.
- 상태: PENDING.

## 6. Repair Loop
- No prompt-only third retry for the old bug. If typed protocol still fails live, preserve failure and replan rather than weakening validators.

## 7. Push / Publication
- Commit only tested code/contracts/redacted summaries; raw datasets/trajectories/results private and ignored.
- Push to existing authorized `origin/feat/hotline-runtime`, verify exact SHA and clean worktree.

## 8. Closeout Report
- Must distinguish pipeline code, actual PRE run, actual training and final evaluation. No unrun stage is promoted by plan completion.

## 9. Relay Shot
- After 3a/b publication, re-score. Expected next: 3c Mini131 PRE if adapter/inventory is executable; otherwise exact blocker. Do not inspect PRE failures to design training data.

## 10. Initial Ledger
- Doc: IN_PROGRESS
- Implementation: PENDING
- Validation: PENDING
- Repair: NONE
- Push: PENDING
- Report: PENDING
- Relay: CONTINUE_WITH_NEXT_FORM
- Remaining risk: actual training resource budget and new non-golden data are not yet frozen.
## EVO35.3a/3b closeout amendment
- Doc: COMPLETED - D-029 + `evo-training-policy.md` + ordered TODO.
- Implementation: COMPLETED - training skeleton, typed hist/cand/ev lifecycle, state-dependent structured policy schema.
- Repair: COMPLETED - typed live cand:e0 failure isolated; llguidance `uniqueItems` incompatibility repaired without weakening server duplicate validation.
- Validation: COMPLETED - impact380 PASS + training13 PASS; actual Qwen Korean follow-up search/read/finish PASS; Mermaid/Chrome report PASS.
- Review: APPROVE_WITH_SCOPE_LIMITS, same-assistant solo review; no independent Critic claim.
- Publication safety: CLEAR_WITH_CLASSIFIED_HASH_FALSE_POSITIVES; stock scanner unchanged exit1, unresolved0.
- Push: PENDING_ACTUAL_GIT_RECEIPT; do not write a guessed commit SHA here.
- Flow diagram verification: GAP/PARTIAL for full D-029; EVO35.3a/3b MATCHED.
- Relay decision after publication: `CONTINUE_WITH_NEXT_FORM` -> EVO35.3c Mini131 PRE.
