# API Mini131 clean branch: shared embedding cache namespace dependency

- Date: 2026-09-01
- Branch: `feat/api-gpt5mini-mini131-eval`
- Symptom: the clean API-only history failed while importing `core40_baseline` because `embedding_cache_namespace` was unavailable.
- Cause: the API baseline commit imported a provider-neutral helper that had previously arrived only through the excluded local GCP baseline commit.
- Resolution: restored the helper directly in the shared embedding module, retained byte-identical model keys for providers without a custom namespace, and added document/query role tests.
- Boundary decision: do not cherry-pick the local baseline commit to satisfy a shared API dependency; move only the provider-neutral helper and its focused tests.
- Verification: the evaluation suite and complete repository suite pass from the reconstructed API branch.
