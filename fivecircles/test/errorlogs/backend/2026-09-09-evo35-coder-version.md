# EVO35.1 - requested Coder rejected by installed Codex

- Recorded date: 2026-09-09 (Asia/Seoul).
- Probe diagnostic timestamp: 2026-09-09T13:06:08+09:00; server/client logs are saved separately.
- Target: `feat/hotline-runtime`, inspected base `2be2f46`.
- Local CLI: `codex-cli 0.142.5`.
- Requested role: `gpt-5.6-sol`, `model_reasoning_effort="ultra"`, as required by the explicitly invoked local relay-shot/collaboration skills.
- Probe flags: read-only sandbox, ephemeral session, JSON event output, no tools or file changes requested. This was only a capability check, not a Coder implementation dispatch.
- Actual thread: `01a08458-34ff-7552-b617-a1d27a06effe`.

## Observed failure

The saved event stream records server HTTP400:

> The 'gpt-5.6-sol' model requires a newer version of Codex. Please upgrade to the latest app or CLI and try again.

The stream ends with `turn.failed`. No final response file exists. The connector reported an unknown command exit, so no native exit code is inferred. No still-running capability-probe process was found in the follow-up check.

Secondary startup messages report a model-cache schema mismatch (`base_instructions`) and two pre-existing missing-frontmatter skill warnings. These were not edited, and their repair was not treated as a substitute for the server's model-version rejection.

## Scope and disposition

- STOP_WITH_REASON / BLOCKED_CODER_VERSION. The full `evo35-directive-001` remains prepared but not dispatched.
- Main completed the requested Design contract, model decision, authoritative TODO and relay/start record. No product implementation, fresh Critic, product tests, application-model execution, SFT/GRPO, commit or push.
- No weaker/substitute model, solo implementation, auth/permission modification, version spoofing or package upgrade was used.
- Standard Codex.app locations checked did not provide an installed alternative binary. The existing CLI installation and authentication remain unchanged.
- Resume with a supported installation that can dispatch the exact Coder/effort and fresh Critic, or an explicit user change to collaboration mode/models. Recheck branch/contract before using the existing prepared directive; do not invent an approval or reuse the failed probe as completed work.
- Raw diagnostic files: `resources/data_refined/private/diagnostics/evo35-relay-20260909/`, Git-ignored. No corpus, secrets or user question text was included in the capability prompt.
