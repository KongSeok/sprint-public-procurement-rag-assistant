# 2026-09-05 — C1 validator root-of-trust bypasses

## Symptom

Independent attack reviews found two ways to mint an E1 state from a foreign, equal-looking
`FollowupRetrievalOutcome` clone:

1. replace the projection module's validator global with a no-op;
2. after a global-pin repair, replace both the mutable trust alias and validator, or replace the
   public function's captured validator cell together with its global alias.

## Root cause

The new projection relied on a validator whose comparison value and trust anchor were both
reachable through mutable module globals. The first closure repair still left the captured
validator uniquely unpinned and exposed a direct unvalidated implementation alias.

## Resolution

- Captured the validator, its full follow-up module surface pin, pin validators, and implementation
  in the public factory closure.
- Validate identity, code, defaults, kwdefaults, globals, and closure before use.
- Pin the captured validator itself and delete the direct implementation alias after closure bind.
- Added no-op global, dual alias, code/default, internal dependency, helper-code/pin, and
  validator-cell/global coordinated drift attacks; all fail before state projection.

## Prevention

- A mutable global cannot serve as both the live dependency and its trust root.
- Public authority boundaries must pin every captured callable, including the final validator, and
  remove unvalidated implementation aliases after factory binding.
- Independent attack review remains mandatory before closing an authority leaf.
