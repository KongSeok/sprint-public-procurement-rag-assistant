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
- HTML5 validator mismatch: `errorlogs/frontend/2026-09-05-c1-html-validation-tooling.md`
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

### EH-RC0 runtime/scorer boundary (2026-09-03)

- Leakage 검증은 금지 key 검색만 하지 말고 gold 변경 전후 runtime 직렬화/hash 불변을 확인한다.
- TDD module-missing red와 기능 실패를 구분한다. filename suffix/숫자 association/극성 회귀를 유지한다.
- 저장 답변 재채점은 실물 fact shape와 source-case hash를 확인하며, candidate companion을 gold로 사용하지 않는다.
- refs: errorlogs/backend/2026-09-03-eh-rc0-tdd.md, errorlogs/backend/2026-09-03-eh-rc0-scorer-replay.md.

### Evidence child artifact boundaries (2026-09-03)

- 반복 문구는 내용 hash만으로 occurrence를 구별할 수 없다. parent 기준 half-open char_range를 canonical ID에 포함한다.
- splitter receipt는 config 자체 hash만 맞춰서는 안 된다. 저장 child를 선언된 splitter로 재구성해 ID 집합까지 검증한다.
- multipart page source는 같은 config/section/doc/page여야 하며 원문의 비공백 gap을 허용하지 않는다.
- private 하위 경로 검사 전에 private root symlink 자체를 거부한다. 새 artifact는 O_EXCL/새 디렉터리로만 쓴다.
- child dense와 page control을 ID/granularity로 분리한다. empty scope는 encoder/tokenizer/lane 호출 전에 종료한다.
- 실제 lane smoke의 후보 수는 품질 점수가 아니다. 같은 gold/config로 retrieval 평가 전에는 성능 향상을 주장하지 않는다.
- ref: errorlogs/backend/2026-09-03-eh-rc0-evidence.md.
### EH2.5 aggregate authority boundary (2026-09-04)
Cause:
- frozen top-level identity와 저장 hash만으로 live nested payload와 equal-payload 객체 교체를 막지 못했다.

Preventive rule:
- aggregate DTO는 중첩 identity를 먼저 검사하고 live store canonical payload를 별도 재해시한다.
- 직렬화/hash 전 bomb test와 equal-looking replacement 회귀를 함께 유지한다.

Reference:
- `errorlogs/backend/2026-09-04-eh25-store-payload-authority.md`
- `errorlogs/backend/2026-09-04-eh25-bound-compare-nested-authority.md`

### EH2.6.b1 live authority precheck (2026-09-04)
Cause:
- frozen DTO도 `object.__setattr__`로 mapping/index/scalar subclass가 주입되면 직렬화가 악성 메서드를 먼저 호출할 수 있었다.

Preventive rule:
- constructor-issued identity와 exact child type을 먼저 검사하고, 그 뒤에만 mapping 순회·hash·비교·직렬화를 수행한다.
- bind/replay 모두 bomb mapping/string 호출 0회와 derived store index identity 회귀를 유지한다.

Reference:
- `errorlogs/backend/2026-09-04-eh26-b1-live-authority.md`

### EH2.6.b2 zero-dispatch authority gates (2026-09-04)
Cause:
- Outer validator identity alone did not seal mutable checker defaults, coordinated aliases, transitive helpers, class methods, or registry-entry dereference order.

Preventive rule:
- Public bind/validate/search preflight must authenticate exact checker code/globals/defaults and the complete reachable callable/class/registry surface before traversal.
- Validate exact registry entry type and weakref type before dereference; test coordinated replacements as well as one-name patches with `calls == []`.
- Runtime authority validation remains provider-free; Langfuse stays disabled until real E2E/golden execution.

Reference:
- `errorlogs/backend/2026-09-04-eh26-b2-runtime-authority.md`

### EH2.6.b4 callback and replay authority (2026-09-05)

Cause:
- 호출 전 callable 검증만으로는 untrusted provider callback 이후의 global 교체를 막지 못했다.
- 결과 receipt 수명이나 단일 mutable progress map에 replay 이력을 기대면 GC·부분 변조 뒤 다시 열릴 수 있다.
- mirror를 직접 교란하는 테스트는 teardown이 비대칭이면 다른 실행 순서에 stale state를 남긴다.

Preventive rule:
- provider 반환 뒤 dependency gate, exact DTO type, public receipt validator를 다시 실행한다.
- 단계별 obligation 순서를 lane claim 전에 검증한다.
- ledger-lifetime 완료 이력은 동일 immutable entry identity를 공유하는 이중 private mirror로 보존한다.
- private-state 회귀는 두 mirror를 대칭 복구하고 정·역순 반복으로 isolation을 검증한다.

Reference:
- `errorlogs/backend/2026-09-05-eh26-b4-fusion-e0-integrity.md`

### One-shot relay must re-enter execution (2026-09-05)

Cause:
- `CONTINUE_WITH_NEXT_FORM` was recorded after push, but leaf closeout was treated as turn completion.

Preventive rule:
- An open continuation request plus a safe READY TODO requires a fresh flow form and immediate next-cycle start.
- A relay may stop only with an explicit, evidence-backed `STOP_WITH_REASON`.

Reference:
- `errorlogs/backend/2026-09-05-one-shot-relay-reentry.md`

### Patch anchors must be byte-exact (2026-09-05)

Cause:
- A multiline patch anchor was copied from a truncated view with a different line wrap.

Preventive rule:
- Read narrow exact context and split unrelated file patches before editing.

Reference:
- `errorlogs/backend/2026-09-05-c1-contract-patch-context.md`

### Repeated call sites require function-scoped patches (2026-09-05)

Cause:
- A validator repair matched the first identical call and touched the EH2.5 compatibility builder.

Preventive rule:
- Anchor repeated-call patches on the enclosing function and inspect the resulting line range before rerunning tests.

Reference:
- `errorlogs/backend/2026-09-05-c1-wrong-validator-callsite.md`

### Authority roots cannot share mutable aliases (2026-09-05)

Cause:
- The live validator and its trust anchor were both replaceable module globals; the first closure left the validator cell unpinned.

Preventive rule:
- Capture the authority root privately, pin every captured callable, and delete direct unvalidated implementation aliases.
- Keep coordinated global/code/default/dependency/closure attacks in the focused gate.

Reference:
- `errorlogs/backend/2026-09-05-c1-validator-root-authority.md`

### `py_compile` is not write-free (2026-09-05)

Cause:
- `py_compile` writes `__pycache__` despite `PYTHONDONTWRITEBYTECODE=1`.

Preventive rule:
- In a read-only authority root, rely on write-free unittest imports instead of bytecode compilation.

Reference:
- `errorlogs/backend/2026-09-05-c1-pycompile-cache-permission.md`

### Tests must not depend on deleted initialization helpers (2026-09-05)

Cause:
- A regression fixture called a private pin helper that production deletes after initialization.

Preventive rule:
- Reconstruct fixture-only immutable shapes inside the test instead of depending on deleted private helpers.

Reference:
- `errorlogs/backend/2026-09-05-c1-deleted-pin-helper-test.md`

### Harness tests must use the repository runtime (2026-09-05)

Cause:
- A focused c2 preflight used Homebrew system Python, which lacked the repository's numpy dependency and collected zero tests.

Preventive rule:
- Run harness tests with `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m unittest ...`.
- Distinguish import-time environment failure from a product-code test failure in reports.

Reference:
- `errorlogs/backend/2026-09-05-c2-system-python-dependency.md`

### Semantic gates must pin transitive globals and close receipts before completion (2026-09-05)

Cause:
- c2의 semantic dependency gate가 새 call graph에서 사용하는 schema constant, config/hash validator와
  Unicode module attribute를 처음에는 전부 봉인하지 않았다.
- execution history를 completed로 바꾼 뒤 receipt를 mint하면 mint 실패 시 완료 기록만 남을 수 있었다.

Preventive rule:
- provider boundary가 추가될 때는 새 함수뿐 아니라 reachable constant, validator, imported module attribute를
  global rebinding 관점에서 다시 감사한다.
- receipt를 먼저 성공적으로 mint/register한 뒤 completion으로 전환하고, mint 실패는 consumed failed로 닫는다.
- at-most-once history는 receipt GC보다 오래 살아야 하지만 owner source보다 영구히 오래 살면 안 된다. source
  weak lifetime에 묶어 cleanup하고 object ID 재사용을 차단한다.
- private request DTO는 일반 constructor뿐 아니라 pickle/copy reduction protocol도 닫고 token factory-only로
  발급한다.
- sealed synthetic component의 관찰·재진입 fixture는 instance/global state를 바꾸지 말고 외부 임시 파일과
  importlib reentry module 패턴을 사용한다.

Reference:
- `errorlogs/backend/2026-09-05-c2-semantic-integrity-review.md`

### Report browser checks must use the bundled module path and an installed browser (2026-09-05)

Cause:
- global Node에는 Playwright package가 없었고 bundled Playwright의 기본 Chromium revision도 설치되지 않았다.

Preventive rule:
- workspace dependency tool이 돌려준 Node/package 경로를 사용하고, 이미 설치된 Chrome을 명시적으로
  선택한 뒤 동일 검증을 재실행한다. 새 브라우저 다운로드로 우회하지 않는다.

Reference:
- `errorlogs/frontend/2026-09-05-report-playwright-runtime-discovery.md`

### At-most-once history must follow the root authority lifetime (2026-09-05)

Cause:
- c3.1 context receipt history was initially keyed to an intermediate semantic obligation object. That object could be
  garbage-collected while the owning retrieval/follow-up source remained live, allowing an equivalent obligation to
  mint a second authority with the same payload.

Preventive rule:
- Bind claim, completion cache, and retry tombstones to the exact root source issuance authority, not to a replaceable
  intermediate receipt or obligation.
- Add a regression that drops only the intermediate semantic object, forces GC, reissues the equivalent semantic
  obligation, and requires exact receipt tuple/item identity reuse while the root source remains live.

Reference:
- `errorlogs/backend/2026-09-05-c3-context-source-lifetime.md`

### Reranker exception paths need the same post-call gate

Cause:
- Exceptional control flow bypassed the dependency revalidation shared by normal returns.

Preventive rule:
- After any attempted provider call, validate exact lineage and component state before classifying outcome or minting a receipt.

### Fast-path authority and replay history must remain root-bound (2026-09-05)

Cause:
- Absence cache hits skipped the full authority gate, while follow-up stage methods could be replayed on the same live root.

Preventive rule:
- Revalidate cached receipts exactly like newly minted receipts and keep a closure-private authority shadow.
- Bind the whole primary→progress→finalize claim chain and production/synthetic runtime kind to the exact root lifetime.

Reference:
- `errorlogs/backend/2026-09-05-c3-absence-authority-followup-replay.md`

### Full tests with private locks need the intended permission boundary (2026-09-05)

Cause:
- The default tool sandbox blocked an ignored private index lock and nested OS sandbox probe.

Preventive rule:
- Rerun only the affected tests with project permission first; if both pass, repeat the full gate under that same boundary and record both results.

Reference:
- `errorlogs/backend/2026-09-05-full-regression-sandbox-boundary.md`

### Closed value matrices must gate semantic actions, not only receipt variants (2026-09-05)

Cause:
- A follow-up restriction was attached to lane/fusion receipt kinds, so controller-decision control rows bypassed it.
- Serialization returned fields before revalidating a drifted frozen object.

Preventive rule:
- Exhaust closed matrices across action, source receipt, outcome, call status, and source kind independently.
- Revalidate frozen receipt structure and canonical hash at every public serialization boundary.

Reference:
- `errorlogs/backend/2026-09-05-c3-action-effect-structural-boundary.md`

### 단계별 평가의 inventory와 가용성을 분리 (2026-09-05)

- Mini131 전체 수량 guard와 부분 결과 표기를 분리하고 suite 명칭을 닫아 전용 평가의 평균 혼입을 막는다.
- fixture ID와 테스트 모듈명을 먼저 확인한다. HTML 브라우저 차단은 PNG 생성 성공으로 덮지 않는다.
- 참조: `errorlogs/backend/2026-09-05-stage-evaluation-validation.md`, `errorlogs/frontend/2026-09-05-stage-report-browser-policy.md`.

### 전체 회귀의 환경 권한과 코드 실패 구분 (2026-09-06)

- private 인덱스 읽기도 lock 파일 쓰기를 요구한다. 중첩 macOS sandbox 거절도 별도 환경 사유로 기록한다.
- 실패한 테스트만 승인된 권한으로 재검증하며 최초 전체 실행을 소급해 전부 PASS로 바꾸지 않는다.
- 참조: `errorlogs/backend/2026-09-06-search-first-test-permissions.md`.

### 기존 골든셋의 위치 가용성과 검수 이력 분리 (2026-09-06)

- source-block ready는 의미 승인이 아니다. 자동 검색 후보·CSV 보조 참조를 확정 qrels로 승격하지 않는다.
- private 감사는 원문 출력 대신 키/집계/hash만 조회한다. refs: `errorlogs/backend/2026-09-06-stage-inputs-validation.md`.

### 검색 관측 단위와 실행 비용 구분 (2026-09-06)

- retrieval granularity(child)와 Evidence.kind(text)를 같은 enum으로 보지 않는다. 실제 builder fixture로 정상 경로를 검사한다.
- 관측기 validation은 호출 timer 밖에 둔다. 실패/미측정을 0으로 덮지 않고 기존 UTF-8 query hash 규칙을 재사용한다.
- 테스트 파일명을 추정하지 않고 rg 목록으로 확인한다. refs: `errorlogs/backend/2026-09-06-stage-recorder-validation.md`.

### Offline 모델 cache는 프로세스 시작 전에 고정 (2026-09-06)

- 라이브러리 pin import가 HF 상수를 먼저 만든다. 이후 env 변경으로 해결하려 하지 말고 Hub/Transformers effective cache를 함께 검사한다.
- 실패 실행은 보존하고 신규 namespace에서 재검증한다. 실측 시작 뒤 추가한 guard를 해당 실행에 소급 적용하지 않는다.
- refs: `errorlogs/backend/2026-09-06-retrieval-smoke-runtime.md`.

### 문서 정답 분모와 위치 정답 분모 분리 (2026-09-06)

- doc qrels는 원래 inventory에서 검증하고 anchor owner로 추정하지 않는다. partial 위치 결측으로 원래 정답 수를 줄이지 않는다.
- 보고/계약 경로는 rg 목록으로 확인한다. 미측정과 0, 구조적 가용성과 사람 승인도 분리한다.
- refs: `errorlogs/backend/2026-09-06-stage-ranking-validation.md`.
