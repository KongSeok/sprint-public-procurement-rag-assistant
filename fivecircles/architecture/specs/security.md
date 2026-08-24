# Security and Data Handling Contract

## 1. Data Classification

### Restricted

- source HWP/PDF and `data_list.csv`
- extracted text, tables, page images and rendered conversions
- chunks, embeddings, vector indexes and retrieval context
- private manifest fields that reveal source file names or Drive identifiers
- gold evidence spans, private evaluation cases and raw model traces
- names, phone numbers, email addresses and other contact details
- API keys, SSH keys, service-account credentials and tokens

### Public after review

- source code and JSON Schemas
- aggregate metrics and redacted error counts
- pseudonymous document IDs and non-reversible hashes
- short synthetic or explicitly redacted examples
- reports that cannot reconstruct original document contents

## 2. Processing Boundary

- Local processing is mandatory until corpus egress authority is confirmed.
- The course guide's two-scenario requirement is implementation intent, not proof that this Drive copy and its PII may be sent to external processors.
- After documented approval, only course-provided OpenAI credentials and the team's course-provided GCP project may be considered.
- Do not send corpus content to arbitrary SaaS, public vector databases, personal cloud storage or other model providers.
- Before Scenario B calls, verify approval evidence, retention/training settings, budget hard stop, minimal chunk transmission and prompt/response logging controls.
- Before Scenario A upload, verify approval evidence and use a private VM/bucket, least privilege, encrypted storage and a documented cleanup procedure.

## 3. Secrets

- Load secrets from environment variables or an approved secret manager.
- Commit only empty placeholders in `.env.example`.
- Never print secret values, request headers or credential-bearing URLs.
- Run `scripts/validate_repo_safety.sh` before commit and before publishing a report.

## 4. PII and Logs

- Runtime logs may contain only pseudonymous IDs, status/error codes, counts, hashes and timings.
- Do not log source text, retrieval snippets, prompts, completions, source file names or contact values.
- Reports must mask names, phone numbers and emails unless a reviewer establishes that a value is non-personal and necessary.
- Private manifest may store PII counts, never the detected values.

## 5. RFP Content Is Untrusted Input

- Instructions, links, scripts and prompt-like text inside an RFP are data, not system commands.
- Extractors must not execute macros, embedded scripts or external links.
- Run document parsers with read-only inputs, no network, per-file timeout and bounded resources where available.
- Generation prompts must delimit retrieved text and explicitly prohibit following instructions found inside it.

## 6. Publication Gate

Publication fails if any tracked or packaged artifact contains:

- source documents or recoverable source-level text
- embeddings/vector stores/private evaluation evidence
- secrets or credentials
- unmasked personal contact information
- unrestricted links or identifiers that grant access to restricted artifacts

The NDA allows non-source derivative outputs; it does not make chunks or vector stores public by default.
