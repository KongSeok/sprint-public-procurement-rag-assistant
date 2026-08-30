Timestamp: 2026-08-28
Context: repository safety validation after visual-corpus rollout

Issue
- The OpenAI-key detector matched the `sk-` substring embedded inside a long non-secret policy slug. The value
  was not a credential, but the safety check correctly stopped publication until classified.

Resolution
- Keep the existing minimum key-body length and require `sk-` not to be immediately preceded by an identifier
  character. Use the PCRE2 engine for the fixed-width negative lookbehind.
- Re-run the complete repository safety scan; 514 files passed with no secret, PII or restricted-path finding.

Prevention
- Secret scanners should retain fail-closed behavior while distinguishing token starts from substrings inside
  ordinary identifiers.
- Diagnose findings with filename-only and redacted-context output. Never print the candidate value.
