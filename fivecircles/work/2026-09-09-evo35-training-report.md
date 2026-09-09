# EVO35.3a/3b Training Pipeline + Follow-up Protocol Closeout

Date: 2026-09-09. Mode: solo relay-shot, user-explicit; no external Coder/Critic.

## Scope

Close EVO35.3a training/evaluation skeleton and EVO35.3b follow-up evidence-lifetime repair before any golden PRE run. Qwen/Qwen3.5-9B remains the application policy/final-answer model. Serving dependency pins are unchanged.

## Implemented

- New D-029 contract and ordered relay queue: pipeline -> typed follow-up repair -> freeze -> Mini131 PRE -> non-golden collection -> SFT -> reduced GRPO -> POST/new sealed holdout.
- Policy-visible IDs are disjoint: historical citations `hist:tN:eN`, current search candidates `cand:eN`, successfully read/inspected evidence `ev:eN`. Canonical evidence IDs remain server-side for provenance/citations.
- `read` accepts only current `cand:*`; answered `finish` accepts only current `ev:*`. Visual inspection follows the same candidate/evidence lifetime.
- Qwen policy generation now receives a state-dependent JSON Schema. Impossible actions and unavailable evidence handles are removed from the model grammar before generation; `action_from_json`, scope and budget validation remain authoritative.
- Training skeleton: trajectory validation, Mini131 exclusion fingerprints, train/dev/sealed split freeze, action-only SFT export, external success-gated reward contract, isolated SFT preflight/trainer entrypoint and GRPO preflight gate.
- SFT path is adapter-only and isolated from serving. GRPO actual execution stays blocked until the project JSON-action rollout adapter is frozen; no silent switch to a different native tool-call wire.

## Failures preserved and repaired

1. Typed namespace live trial removed the old canonical-ID confusion but Qwen invented `cand:e0` before any search. Runtime rejected it twice; no retrieval/generation occurred.
2. First structured-generation trial failed before model output because local llguidance does not implement JSON Schema `uniqueItems`. The grammar schema dropped `uniqueItems`; server validation still enforces duplicate-ID rejection.
3. The next identical live follow-up succeeded without prompt/gold injection or guard relaxation.

## Actual Qwen follow-up result

Question: `그중 Beta 사업의 예산과 수행기간만 다시 알려줘.` using the preserved synthetic prior turn and explicit Beta scope.

Observed policy path: `search -> read -> finish`.

- search query: `Beta 사업 예산 수행기간`, scope `beta`, candidate `cand:e1`
- read: `cand:e1 -> ev:e1`
- finish: answered with `ev:e1`
- invalid actions: 0
- policy calls: 3; search calls: 1; read calls: 1; answer calls: 1
- worker total: 10.488s; setup: 4.211s; episode wall: 6.276s
- answer: Beta budget 80 million KRW, performance period 4 months, citation S1
- run: ignored private diagnostics `evo35-train-20260909-001/followup-typed-structured-002/`

This proves the synthetic explicit follow-up path, not private-RFP quality or learned-policy improvement.

## Validation

- Dynamic-schema/typed/training focused set: 104 tests PASS before schema-specific additions.
- Final existing impact runner after schema tests: 380 unique tests PASS, failures/errors/skips 0, 8.965s.
- Training pipeline module: 13 tests PASS, 2.444s.
- Real local schema compile: PASS after removing unsupported grammar-only `uniqueItems`.
- Actual Qwen follow-up: PASS as above.
- Stock repository safety scanner remains exit1 on historical digest-pattern false positives; no scanner relaxation is part of this batch. Publication audit must classify before push.

## Target vs current gap

| Target edge | Current status | Evidence / next action |
| --- | --- | --- |
| Contract -> typed evidence lifecycle | MATCHED | hist/cand/ev tests + live prompt state |
| State -> executable action grammar -> Qwen | MATCHED | real llguidance compile and live structured policy |
| Explicit follow-up -> scoped search/read/finish | MATCHED_SCOPED | actual synthetic Qwen run, invalid actions 0 |
| Training data leakage/split/SFT skeleton | MATCHED_SCOPED | 13 training tests; no actual training yet |
| Freeze -> Mini131 PRE | GAP | next relay unit EVO35.3c |
| Non-golden collection -> SFT -> GRPO -> POST/holdout | GAP | intentionally downstream |

## Done / not-done priority

| Unit | Status | Connection score | Reason |
| --- | --- | ---: | --- |
| EVO35.3a | DONE | 10 | unlocks all learning stages; validated skeleton |
| EVO35.3b | DONE | 11 | upstream runtime correctness; actual Qwen PASS |
| EVO35.3c Mini131 PRE | NEXT | 9 | required freeze baseline before data collection |
| EVO35.3d collection | NOT_STARTED | 7 | depends on PRE freeze |
| EVO35.3e SFT | NOT_STARTED | 6 | depends on non-golden data/dev |
| EVO35.4 GRPO | NOT_STARTED | 4 | depends on accepted SFT + rollout adapter |

Scoring uses upstream_weight + connection_value + safety_value + validation_value + risk_penalty per relay-shot.

## Flow diagram verification

Target: `2026-09-09-evo35-training-target-flow.mmd/png`.
Current: `2026-09-09-evo35-training-current-flow.mmd/png`.

Verdict: **GAP/PARTIAL for full D-029**, while **EVO35.3a/3b are MATCHED**. The next concrete gap is the frozen Mini131 PRE baseline.

## Publication audit

Read-only candidate audit checked 1018 files/objects: unresolved findings 0; three matches were classified as the existing phone-regex-inside-exact-SHA256 false positives. The stock scanner remains unchanged and still exits 1. Raw private diagnostics are ignored and not publication candidates.

Chrome flow-report verification: both rendered Mermaid PNGs loaded with nonzero dimensions and target/current/gap/priority sections visible; screenshot: `../test/playwright-screenshots/evo35-training-report.png`.
