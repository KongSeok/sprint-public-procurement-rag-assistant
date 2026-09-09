# EVO35.2 - Solo live Qwen3.5 smoke

Date: 2026-09-09. Run: evo35-hotline-20260909. Mode: solo, explicitly requested again by the user: execute relay-shot in solo mode.

## 0. Scope Intake
- Branch: feat/hotline-runtime, start e961149; initially clean.
- Execute the actual pinned local Qwen3.5-9B MLX derivative on the existing two-document synthetic corpus. No private RFP/gold inputs, downloads, model-server replacement, extra agents or training.
- Each live worker has the existing 120-second total limit including load; policy<=12, search<=4, read<=4, final answer<=1. No automatic provider retry. Bounded manual repair/rerun is allowed only for a diagnosed same-scope defect; preserve every failed run.
- Completion: observe actual model-selected search/read/finish and a factually correct comparison with citations to both synthetic documents. Absence of a crash alone is not success.

## 1. Start Report / Target Check
- Existing report: 2026-09-09-evo35-solo-delivery.md and its target/current flow. Reuse diagrams until the live result changes an edge.
- Current: 212 model-free tests; MLX adapter and policy code implemented; live-model link unverified.
- Previous turn confirmed the 13-file artifact inventory/size/SHA and a Metal GPU operation. Current profile still pins derivative 8b2b98c00a6b4d291155e4890773ca8f769aee53. Backend verifies it again during normal loading.
- No new product quality or training conclusion follows from preflight.

## 2. Relay Unit Selection
- Authoritative TODO: EVO35.2. Score 7 (3+3+2+1-2); explicit user task wins.
- Next: actual local-model policy -> public synthetic retrieval -> multi-evidence answer.
- Later SFT/GRPO is dependent on actual data split/environment/resource budget and remains out of this live smoke.

## 3. Doc / Contract
- Reuse evo-hotline-qwen35-v1/D-026, explicit solo amendment. Mark old tool-preflight blocker historical; no return to old Coder requirement.
- Actual loaded artifact is the manifest-pinned MLX conversion. Canonical family is Qwen/Qwen3.5-9B; an unknown upstream commit must not be invented or presented as directly verified canonical weights.

## 4. Implementation
- First execute the published code unchanged. If an installed API mismatch or local adapter defect occurs, record a focused reproduction, perform a minimal in-scope repair and relevant tests before a fresh output-directory rerun.
- Preserve historical hotline, Controller, shared retrieval/evidence source and other worktrees.

## 5. Validation + Report
- Model runtime: existing qwen35-9b-mlx .venv-mlx; PYTHONPATH points only to the hotline branch source. Record actual installed origin/version, no guessed Python site-packages path.
- CLI: explicit --synthetic-corpus --record-trajectory --timeout-seconds 120; separate private capture and new run directory.
- Record native exit, supervisor status, actions, exact comparison/citations, policy/answer usage, setup/tool/model timings and failure reasons.
- Browser scope: refresh the existing flow report after a result. No product UI changed.

## 6. Repair Loop
- Same-scope only, no blind retries or output coercion. No substitution of synthetic policy responses for actual model behavior. Retain initial failures and final checks separately.

## 7. Push / Publication
- Existing hotline-branch publication authorization carries through the relay. Selective tested code and redacted reports only; private raw model transcripts/results are excluded. Check actual local/remote hashes afterward.

## 8. Closeout Report
- Update matched live edges without calling all RAG support, training or UI complete. Report scoped smoke versus full evaluation separately.

## 9. Relay Shot
- Reinspect TODO after closure. Continue safe highest-value work with this solo mode; stop with an exact remaining prerequisite when later training/real-private evaluation lacks frozen data/resource authorization.

## 10. Initial Ledger
Doc: start recorded. Implementation: published candidate first. Validation: ready for live run. Repair: not yet needed. Push: pending actual result. Report: current code-only report reused. Relay: CONTINUE_WITH_NEXT_FORM into EVO35.2.

## EVO35.2 continuation - fixed reference and explicit follow-up
- First unchanged policy smoke completed, native exit0: four policy calls, one search/read/answer, both documents correctly compared. One premature finish was rejected and the actual model selected read then finish.
- Next bounded validation uses the unchanged model/profile/code: fixed reference for the same question, then one Korean follow-up restricted to Beta using actual prior citation IDs. Each worker <=120 seconds; separate new outputs. No post-result prompt tuning or automatic retry.
- This connects fixed-reference and explicit-history/scope edges within the same approved synthetic-only live-smoke scope. No private RFP or training is introduced.

## Repair re-entry - current-episode tool preconditions
- Observed failure: unchanged Korean follow-up issued read twice with prior-answer full IDs, including a document outside the current narrowed scope. The dispatcher rejected both before retrieval/read/generation; invalid_action_limit, exit1. No guard was bypassed.
- Diagnosis: the model-visible observation carries raw historical citation IDs but gives no explicit current-action input lists. The generic guide already mentions found/read handles, yet the real model confuses the two lifetimes.
- Bounded repair: add small current-episode read/finish input lists to the observation and a generic explanation that historical citations do not populate them. Do not inject any question-specific action, fact or expected answer. Existing scope/evidence validators, invalid-action cap, tools, model, answer prompt and retrieval results remain unchanged.
- This is an explicit prompt/observation revision after a failed test, not an unchanged-profile benchmark. Preserve original successful comparison, fixed result and failed follow-up. Regress the existing guards before one fresh follow-up and comparison smoke.
- Source scope: evo_harness/state.py plus new regression tests and these logs. No recursive validation machinery or Controller restoration.

## Repair re-entry 2 - separate historical machine IDs from policy inputs
- First repair passed99 model-free tests but live followup-002 repeated the same two historical IDs and failed. No success is inferred from code regression alone.
- Revised diagnosis: raw long canonical citation IDs in explicit history remain actionable-looking distractors despite current-handle lists. Preserve the full original history for scope resolution, consistency checks, audit and final-answer input; only the policy observation projects historical turns without the machine-only cited_evidence_ids field.
- Keep all user/assistant text, role, turn ID and cited document IDs. Do not hide user content, current candidates, missing fields or token overflow. The policy still receives current scope and current valid handles and must choose its own actions.
- No historical evidence becomes a current candidate. Scope, read and finish validation and attempt limits remain unchanged. Add projection regression and do one same-input live rerun; a further failure requires replan rather than blind looping.

## Final form / actual disposition
- Documentation: actual model, outcomes and rejected candidates recorded in 2026-09-09-evo35-live-report.md.
- Implementation: no product change adopted; tested patches preserved privately then restored.
- Validation: comparison/fixed scoped PASS; follow-up FAIL across original and two candidates. Restored212 regression PASS.
- Repair: two unsuccessful candidates rejected, not silently converted to successful work.
- Publication: documentation/evidence only, actual push acknowledgement saved afterward; no raw transcripts tracked.
- Report: unchanged target reused, current graph reflects real comparison and follow-up failure.
- Relay: STOP_WITH_REASON / REPLAN at EVO35.2.FOLLOWUP. No accepted policy fix; new protocol/learning design needed and later training resource/data gates remain.
- Flow diagram verification: GAP/PARTIAL. No active worker or deferred background task.
