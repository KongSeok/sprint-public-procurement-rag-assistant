# EVO35.3a/3b solo review

Date: 2026-09-09. Reviewer: same assistant under explicit solo relay-shot; no independent Critic.

## Candidate

Base `a800ff0`; scope is D-029 training/eval skeleton plus typed follow-up handles and state-dependent policy grammar. Serving dependency pins and the existing Qwen3.5 application model identity are unchanged.

## Findings

1. Historical citations are projected to `hist:*` only in the policy view; canonical IDs remain in the original request/server state for scope validation and final citation provenance.
2. Current search candidates and read/inspected evidence use separate `cand:*` and `ev:*` namespaces. `read`/`inspect_image` and answered `finish` reject the wrong lifetime before external calls.
3. The dynamic policy JSON Schema exposes only currently executable tools/handles. It is an inference grammar, not authorization: existing strict JSON, scope, duplicate, budget, provenance and citation checks remain active.
4. Local llguidance does not implement JSON Schema `uniqueItems`; the grammar schema therefore omits it while `action_from_json` continues to reject duplicate IDs. No safety rule was weakened.
5. Actual Qwen3.5 follow-up now executes search -> read -> finish with zero invalid actions on the preserved synthetic case. This is a runtime/protocol acceptance result, not private-corpus quality evidence.
6. Training data contracts recursively reject gold/qrels/expected/evaluator fields, block Mini131 fingerprints, enforce train/dev/sealed group/question/conversation/doc-pair separation, and forbid sealed-holdout SFT export.
7. SFT code targets policy action JSON only. GRPO remains preflight-gated because project JSON-action rollouts are not yet frozen into the trainer adapter; no fake RL completion claim is made.
8. Raw trajectories/model outputs stay private/ignored. Public artifacts contain only contracts, code, aggregate test facts and synthetic examples.

## Evidence

- Impact regression: 380 unique tests PASS, errors/failures/skips 0.
- Training pipeline: 13 tests PASS.
- Mermaid target/current render PASS; Chrome report check loads both images and gap/priority tables.
- Real Qwen3.5 structured follow-up: PASS, 3 policy calls, 1 search, 1 read, 1 answer, invalid actions 0, total worker 10.488s.
- Stock safety scanner still exits 1 on historical digest-pattern false positives; publication classification is required separately.

## Verdict

**APPROVE_WITH_SCOPE_LIMITS for EVO35.3a/3b publication.** Next relay unit is EVO35.3c Mini131 PRE from the frozen published candidate. No actual SFT/GRPO or training-data collection has occurred yet.
