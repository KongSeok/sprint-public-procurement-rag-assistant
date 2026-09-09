# EVO35 typed/structured follow-up repair log

Date: 2026-09-09.

## Failure 1 - typed namespace without executable-action grammar

- Preserved synthetic Korean follow-up showed policy history as `hist:t1:e1/e2` and zero current candidates.
- Qwen generated nonexistent `cand:e0` for `read` twice. Runtime rejected both before retrieval; terminal `invalid_action_limit`.
- Cause: evidence lifetime was fixed, but the model could still generate state-impossible actions/handles.
- Repair: build a state-dependent JSON action schema from current scope/candidates/read evidence/budgets and apply it during policy decoding; keep server validation unchanged.

## Failure 2 - first structured schema compile

- First real structured run stopped before model output with `runtime_contract_error`.
- Direct compile isolated local llguidance error: `Unimplemented keys: ["uniqueItems"]`.
- Repair: remove `uniqueItems` from the decoding grammar only. Existing action parser still rejects duplicate IDs, so no behavior/safety rule was relaxed.

## Resolution

- Identical preserved follow-up then completed `search -> read -> finish` with 0 invalid actions and a cited Beta answer.
- Final regression: 380 impact tests PASS plus 13 training tests PASS.
- Recurrence rule: grammar schemas may be narrower than server validators; unsupported grammar keywords must never be removed from authoritative runtime validation merely to satisfy a decoder.
