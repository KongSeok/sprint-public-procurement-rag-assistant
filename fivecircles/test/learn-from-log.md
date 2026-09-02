# MidProjectRAG Test Learnings

Review this file before implementation and test execution.

## Active Preventive Rules

- Use synthetic data in public tests; private corpus tests are opt-in.
- Never print document text or PII while diagnosing an extractor failure.
- Record failed extraction rows in the manifest instead of dropping them.
- Validate JSON Schemas and cross-reference IDs before computing metrics.
- Treat every nested JSON value as untrusted even after recording a validation issue; guard iteration, hashing and membership by type.
- Enforce frozen case floors and scoring gates inside `score`, not only in a separate dataset-validation command.
- Recompute threshold truth from metric values when comparing reports; stored `passed` flags are evidence, not authority.
- Run the full suite in an interpreter with declared project dependencies; a bare system Python is not verification evidence.
- On this Mac, do not assume `python3` is the project runtime: verify `python --version` first because Xcode Python 3.9 may be first on PATH.
- Drain multiprocessing Pipe results before joining workers; large serialized payloads can otherwise deadlock on the OS buffer.
- Keep a binary-model HWP fallback isolated and retain `partial` provenance warnings when XML/text transforms fail.
- Map fallback dependency, no-text, timeout and parse failures to distinct sanitized manifest codes.
- Mock every optional-dependency signal in absence tests so installed developer tools cannot change the expected path.
- Use explicit `PYTHONPATH=src` and `unittest discover -t .` with the bundled runtime for every scoped or full discovery command; its venv editable `.pth` may not activate in the sandbox.
- Treat legacy macOS `tidy` as HTML4-only; validate UTF-8 HTML5 with an HTML5-capable or tag-balance parser.
- Keep `rhwp` page text, logical tables and render-tree bbox as separate contracts; do not claim a canonical join until its measured success rate passes QA.
- Mock primary-command discovery separately from legacy-command discovery when testing an ordered parser fallback chain.
- Pin external parser binaries by version and checksum, keep them outside Git, and include the local adapter version in the manifest input hash.
- Require `rhwp export-text` to report no truncation, zero omitted characters and a complete zero-based page index set before accepting page blocks.
- Validate `export-tables` cell count and non-overlapping spans, but treat `containerPath` coordinates as kind-dependent: header/footer omit `cell`, while `tableCell` requires it.
- Keep overlapping page text and structured tables in separate retrieval roles; baseline metrics and PII counts use the primary lane only.
- Never let a token counter populate its own network cache. Warm allowlisted static vocab assets under a separate approval gate, pin size and SHA-256, then construct encodings from verified local paths only.
- Keep `python -m package.module` entrypoints under an explicit `if __name__ == "__main__"` guard and test the module invocation, not only the console script.
- Treat Ollama structured output as untrusted: use JSON mode plus the complete Schema in the system contract, then validate shape and citation IDs in the application before persistence.
- For local model calls, allow literal loopback only, disable proxy use and redirects, and verify the installed model digest before sending private context.
- Keep experimental local retrieval artifacts and official API artifacts in separate source, test, index, cache and output paths; enforce the boundary with AST tests.
- When tightening a production path contract, migrate synthetic fixtures to the exact same private root before interpreting the expected boundary failure as a runtime regression.
- In dotenv tests, remove both the standard OpenAI key and its private alias before loading a fixture; an explicitly present empty variable still wins when `override=False`.
- Pin observability mode explicitly in tests whose purpose is an earlier path or provider gate, so a developer `.env` cannot change which contract is exercised.
- Audit live Langfuse traces for field completeness, not only observation existence; ingestion/read-model projection can lag after `flush()`.
- Treat Langfuse model visibility as dual evidence: verify the outgoing OTEL model attribute and retain the allowlisted model metadata when the Observations v2 projection is incomplete.
- Keep OpenAI Structured Outputs' root as an object; put answer/abstention unions below a required envelope and enforce citation uniqueness in application validation instead of unsupported Schema keywords.
- Derive structured-output citation bounds from the runtime context limit so provider Schema and application validation cannot disagree.
- Distinguish a completed Responses payload from merely receiving HTTP success; preserve usage on incomplete output and give valid structured JSON enough output budget.
- Use bounded provider retries for transient connection, 408/409/429 and 5xx failures, while keeping deterministic contract errors non-retryable and the cost ledger authoritative.
- Treat unknown Langfuse read-model fields as schema drift: fail closed without printing field names or values until their semantics and privacy class are reviewed.
- Separate retrieval identity from display metadata identity: matching `doc_id` and source hashes permit vector reuse for a metadata-only catalog overlay, but do not mean the metadata values are unchanged.
- When a corrected manifest introduces optional fields on every row, report semantic source-cell changes and null transitions separately from raw nested-object diff counts.
- Treat `Streamlit AppTest.from_function` as an isolated script context: import app dependencies inside the wrapper instead of relying on the test module's globals.
- Keep runnable top-level app package names distinct from `unittest discover` subpackages; `tests/apps` can shadow a root `apps` package when the tests directory is on `sys.path`.
- Do not treat an in-app browser localhost policy denial as an application failure or bypass it; preserve health/AppTest evidence and report the visual browser pass as environment-blocked.
- Loading and hash-verifying a corrected catalog does not prove its fields reach retrieval or generation; test the actual prompt/context path and document the active field scope.
- Do not attach locator-free catalog values to an arbitrary page chunk citation. Define metadata provenance and citation semantics before exposing those values as grounded answers.
- Trace `config_sha256` must identify the effective retrieval/generation run config, not merely the launcher bundle that points at artifacts.
- Corpus-egress consent must enumerate conversation history whenever retrieval or generation sends history to the provider.
- Render untrusted catalog and locator labels as plain text unless Markdown behavior is explicitly required and escaped/tested.
- Exact index load acquires a shared `.index.lock`; actual-bundle verification therefore needs write access to the private index directory even when no index mutation or provider call occurs.
- A local server started outside the managed sandbox may require the matching approved loopback environment for health checks; do not interpret the isolated namespace refusal as an application outage.
- For Streamlit BaseWeb radio/checkbox controls, click the visible text or enclosing label and verify checked state; forced clicks on the underlying input may not commit controlled state.
- If a managed external-egress gate requests renewed destination-specific private-corpus consent, stop before provider execution and leave the live smoke approval-pending rather than retrying indirectly.
- Treat private-corpus egress consent as batch-specific: enumerate destination, exact payload classes, provider-call ceiling and USD hard cap; an earlier smoke approval never carries forward implicitly.
- If any provider request was attempted and the candidate result ends in `error`, persist an interrupted checkpoint and require a manual budget audit even when the HTTP response itself was successful.
- Give the semantic judge only an opaque blind-input artifact; keep case ID, candidate lineage and execution lane in a separate merge envelope bound by SHA-256.
- In a shared multi-agent worktree, compare failing-file mtimes and diffs after a previously green full suite; do not repair or stage another active task's concurrent schema drift.
- Separate live transport/contract success from answer-quality success: a schema-valid abstention proves the E2E path, while a cited answer still requires a known-answerable gold case.
- Budget repeated table metadata together with Markdown rows; bound optional prefix fields before splitting oversized rows and never truncate canonical cell text to make a chunk fit.
- Keep each chunking policy in its own lane config hash and assert existing page-v1 hash stability whenever adding a table-only rule.
- Bind table layout to the exact indexed body-block set and manifest page count; nested tables must not inherit a parent page without an independent render join.
- Apply subpixel border tolerance only inside a bounded HWP cell/header/fill join; geometry fuzz must never create a schedule fact without an unambiguous `M`/`M+n` header and direct fill evidence.
- Reconcile DocLang assets only by an exact relative path or an exact reconstruction from pinned OTSL cell ancestry; unique-prefix and ordinal filename fallbacks are not structural proof.
- Detect source media from bounded magic/structure validation, preserve raw and canonical identities for every normalization, and keep unsupported source formats provenance-only until a pinned converter exists.
- Strict visual-bundle reuse must revalidate object magic, MIME, dimensions and status-specific render/link fields; stored hashes and metadata values are claims, not independent evidence.
- Bind a full visual-v2 corpus to the complete eligible HWP manifest set; retain legacy subset semantics only in the explicitly versioned legacy loader.
- Secret-key signatures must require a token boundary so ordinary identifiers containing `sk-` do not block safety checks; diagnose candidates with filename-only or redacted output.
- Apply secret/PII regexes to textual/source-like files, not raw raster/font bytes; keep restricted-path and extension policy over the complete file inventory.
- Publish multi-file visual evidence metadata last after source/parser pre-post hashes, private-root containment, strict image structure and artifact reconciliation all pass.
- Treat `pdfplumber` line detections as geometry candidates, not verified tables; diagram boxes and schedule grids require separate human fidelity calibration.
- OCR or caption cannot repair missing object provenance. Require a verified page/bbox crop first; keep page-less assets quarantined and generated claims separate.
- Bind derived visual corpora to adapter/code and config identities and provide a durable runner; a passing newer unit path does not refresh older persisted artifacts.
- Overfetch visual candidates before caption caps, reserve a bounded visual quota, and keep OCR/layout ahead of descriptive captions without displacing all primary evidence.
- Treat caption claims as answer support only when every claim is `supported` and carries valid support refs; descriptive-only caption answers must abstain.
- Compare visual citations by document, occurrence, evidence type and evidence-ID set; exclude unannotated evidence lanes from precision denominators.
- Keep JSON Schema and manual validation in differential tests, including field dependencies, stack-specific exclusions and evidence-type ID prefixes.
- Environment offline flags and executable checksums do not enforce no-egress; require a verified OS network sandbox for every private model subprocess.
- Do not carry a previous closeout's green test count forward after visual code or fixtures change; rerun the current tree and report optional-lane failures separately from the page Dense baseline.
- A valid PNG hash and dimension do not prove usable visual evidence; composite alpha over the target background, reject semantic blanks, and visually compare representative crops with the source renderer.
- When SVG data images are overlaid outside the SVG loader, preserve nested viewBox, rect clips and observed pixel effects; fail closed on unsupported transforms, masks, styles or filter forms.
- Treat CSS selectors, hidden SVG ancestors and definition-only images as non-rendering structure; reject them unless the overlay compositor models their exact visibility and paint semantics.
- When a provider attempt ends in an unknown transport state, preserve the exact attempt as `error`, do not retry under a no-retry baseline, and reserve the verified worst-case cost per affected case until billing is certain.
- Treat reviewer-supplied timestamps as untrusted metadata. Preserve the original semantic decision, derive any ordering correction from an audited filesystem timestamp, and prove a semantic hash excluding the timestamp is unchanged before merge.
- A chat-complete evaluation report must fail closed unless every RAG case has a source transcript and a complete primary/secondary/adjudicator history for every role that was triggered.
- Tests that require ignored private artifacts must skip only those private integration cases when the artifacts are absent; keep synthetic contract tests mandatory and verify the staged clean-checkout snapshot separately.

## Confirmed Incidents

- Harness list-vs-attribute routing and local verification deadline: `errorlogs/backend/2026-09-02-harness-live-routing-budget.md`.
- Missing private fixtures must not disable public synthetic contracts; config/hash failures remain errors: `errorlogs/2026-09-02-evidence-harness-full-suite.md`.

- Streamlit AppTest isolated globals: `errorlogs/frontend/2026-08-26-streamlit-apptest-function-globals.md`
- Streamlit test package shadow: `errorlogs/frontend/2026-08-26-streamlit-test-package-shadow.md`
- In-app browser localhost policy: `errorlogs/frontend/2026-08-26-in-app-browser-localhost-policy.md`
- Corrected catalog disconnected from answer context: `errorlogs/backend/2026-08-26-corrected-catalog-answer-boundary.md`
- Catalog scoped discovery import path: `errorlogs/backend/2026-08-26-catalog-test-discovery-pythonpath.md`
- Actual index shared-lock sandbox permission: `errorlogs/backend/2026-08-26-actual-index-lock-sandbox.md`
- Supplemental DTO changes must update CLI signatures, schema, manual field sets and fixtures together; use task-specific shell variables. (`errorlogs/backend/2026-08-31-supplemental-evaluation-contract-drift.md`)
- Live API corpus egress re-approval: `errorlogs/backend/2026-08-26-live-api-corpus-egress-reapproval.md`
- Live API grounded abstention: `errorlogs/backend/2026-08-27-live-smoke-insufficient-evidence.md`
- Table prefix token budget: `errorlogs/backend/2026-08-28-table-prefix-token-budget.md`
- Table config hash placement: `errorlogs/backend/2026-08-28-table-config-hash-placement.md`
- HWP schedule visual join: `errorlogs/backend/2026-08-28-hwp-schedule-visual-join.md`
- rhwp DocLang asset URI drift: `errorlogs/backend/2026-08-28-rhwp-doclang-asset-uri-drift.md`
- HWP source asset format/provenance drift: `errorlogs/backend/2026-08-28-hwp-asset-format-provenance.md`
- Visual-v2 full-HWP coverage gate: `errorlogs/backend/2026-08-28-visual-v2-hwp-coverage-gate.md`
- Secret-pattern token-boundary false positive: `errorlogs/backend/2026-08-28-secret-pattern-token-boundary.md`
- Repository safety binary-pattern false positive: `errorlogs/backend/2026-08-28-repository-safety-binary-pattern.md`
- HWP visual bundle contract audit: `errorlogs/backend/2026-08-28-visual-bundle-contract-audit.md`
- PDF line-table over-detection: `errorlogs/backend/2026-08-28-pdf-line-table-overdetection.md`
- PDF visual artifact stale after recovery code: `errorlogs/backend/2026-08-30-pdf-visual-artifact-stale.md`
- Streamlit health sandbox namespace: `errorlogs/backend/2026-08-26-localhost-health-sandbox-namespace.md`
- Streamlit custom browser control: `errorlogs/frontend/2026-08-26-streamlit-custom-control-browser-click.md`
- Visual adapter network isolation: `errorlogs/backend/2026-08-30-visual-adapter-network-isolation.md`
- Visual integration contract gaps: `errorlogs/backend/2026-08-30-visual-integration-contract-gaps.md`
- Flow report local-file browser policy: `errorlogs/frontend/2026-08-30-flow-report-file-url-policy.md`
- Current-tree visual crop blank regression: `errorlogs/backend/2026-08-31-visual-crop-blank-regression.md`
- Mini131 live provider recovery: `errorlogs/backend/2026-08-31-mini131-live-provider-recovery.md`
- Mini131 judge timestamp ordering: `errorlogs/backend/2026-08-31-mini131-judge-timestamp-order.md`
- Mini131 clean-checkout private fixture: `errorlogs/backend/2026-08-31-mini131-clean-checkout-private-fixture.md`

- Batch 2 fail-closed audit: `errorlogs/backend/2026-08-24-evaluation-fail-closed-audit.md`
- Synthetic/production floor split: `errorlogs/backend/2026-08-24-evaluation-fixture-floor.md`
- Aggregate expectation refresh: `errorlogs/backend/2026-08-24-evaluation-aggregate-expectations.md`
- Missing PDF dependency runtime: `errorlogs/backend/2026-08-24-missing-pypdf-runtime.md`
- Optional Schema engine runtime: `errorlogs/backend/2026-08-24-jsonschema-runtime.md`
- PDF worker Pipe deadlock: `errorlogs/backend/2026-08-24-pdf-worker-pipe-deadlock.md`
- HWP binary-model fallback: `errorlogs/backend/2026-08-24-hwp-binary-fallback.md`
- Venv editable path: `errorlogs/backend/2026-08-24-venv-editable-path.md`
- Local validator runtime limits: `errorlogs/backend/2026-08-24-local-validator-runtime.md`
- HWP optional-dependency test isolation: `errorlogs/backend/2026-08-24-hwp-optional-dependency-test-isolation.md`
- rhwp test-double routing: `errorlogs/backend/2026-08-25-rhwp-test-double-routing.md`
- rhwp container path contract: `errorlogs/backend/2026-08-25-rhwp-container-path-contract.md`
- Baseline test runtime selection: `errorlogs/backend/2026-08-25-python39-baseline-test-runtime.md`
- tiktoken implicit vocabulary download: `errorlogs/backend/2026-08-25-tiktoken-implicit-download.md`
- Staging test import path: `errorlogs/backend/2026-08-25-staging-pythonpath.md`
- CLI module entrypoint no-op: `errorlogs/backend/2026-08-25-cli-module-noop.md`
- Compile pycache permission: `errorlogs/backend/2026-08-25-compileall-pycache-permission.md`
- Qwen private output outside JSON: `errorlogs/backend/2026-08-25-qwen-private-output-not-json.md`
- Stack artifact fixture root mismatch: `errorlogs/backend/2026-08-25-stack-artifact-fixture-root.md`
- Dotenv environment precedence: `errorlogs/backend/2026-08-26-dotenv-test-environment-precedence.md`
- CLI dotenv observability precedence: `errorlogs/backend/2026-08-26-cli-dotenv-test-observability-precedence.md`
- Langfuse v2 eventual field projection: `errorlogs/backend/2026-08-26-langfuse-observations-v2-eventual-projection.md`
- OpenAI Structured Outputs contract: `errorlogs/backend/2026-08-26-openai-structured-output-contract.md`
- OpenAI API matrix runtime resilience: `errorlogs/backend/2026-08-26-openai-api-matrix-runtime-resilience.md`
- Langfuse audit schema drift: `errorlogs/backend/2026-08-26-langfuse-audit-schema-drift.md`
### Streamlit startup skill side effect
Cause:
- A non-headless PTY startup exposed the environment-only agent-skill installer.

Preventive rule:
- Run the local demo with --server.headless true and verify no project-local skill symlinks appear.
### Batch-style TODO logging
Cause:
- The generic logall todo command assumes flat Done/Pending headings.

Preventive rule:
- Inspect todolist structure first and use a scoped patch when the repository organizes work by dated batches.
### Refined CSV full-body field limit
Cause:
- Python csv defaults to 128 KiB per field while canonical PDF bodies are larger

Preventive rule:
- Use MAX_CSV_FIELD_BYTES for every canonical-body CSV reader and keep a greater-than-default regression case
