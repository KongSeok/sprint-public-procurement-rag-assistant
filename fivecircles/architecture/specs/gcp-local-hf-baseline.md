# GCP Local HF Baseline Contract

Status: MAC_EQUIVALENT_MINI131_SEMANTIC_COMPLETE_HUMAN_GOLD_PENDING_NON_OFFICIAL
Decision date: 2026-08-31
Scope: refined98 page-only RAG baseline, 129 RAG + 2 parser full-suite local proof, GCP L4 execution

## 1. Goal

Implement one reproducible local Hugging Face RAG stack that reuses the active refined98 corpus and
the common MidProjectRAG request/response/evaluation contracts. Develop and contract-test it on the
Mac first, then execute the exact production profile on the assigned GCP `g2-standard-4` VM.

## 2. Background / Current Problem

The API baseline is operational. This contract now has a pinned KURE semantic index, loopback vLLM
adapter contract, GCP run-record builder, and resumable Mac-equivalent golden runner. The Mac uses
Ollama `qwen3.8:27b-mlx` only for an explicitly non-official execution proof; the official GCP-local
comparison still requires the assigned L4 and pinned Qwen3-8B-AWQ/vLLM runtime.

The Mac-equivalent run completed all 40 draft cases and a no-new-call replay resumed all 40. It
produced 25 answered, 14 abstained, and one strict generation-contract error. The content-free
receipt therefore remains `official=false`, `passed=false`, with draft gold and semantic judgment
`not_run`; no Mac NumPy measurement is presented as FAISS or GCP evidence.

That 40-case result is the retained core lane, not the complete project inventory. The separate
Mac-equivalent Mini131 run has now closed all 129 RAG assets on the same frozen KURE/page-v1
baseline and rerun both parser regressions at 2/2 PASS. Candidate coverage, lane-complete
deterministic diagnostics and the fresh blinded Sol aggregate are complete. Named human gold
approval and live GCP evidence remain separate pending gates, so no gold-approved or official GCP
result is claimed.

## 3. In Scope

- Existing refined98 `page-v1` body chunks: 98 documents and 9,331 chunks.
- `nlpai-lab/KURE-v1` semantic embedding, 1,024 dimensions, revision pinned by full commit SHA.
- CPU FAISS `IndexFlatIP` over L2-normalized vectors.
- `Qwen/Qwen3-8B-AWQ` generation through a loopback-only vLLM OpenAI-compatible endpoint.
- Non-thinking generation, 8,192-token model context, deterministic decoding, and strict JSON output.
- Existing `RagPipeline`, citation validation, abstention contract, and private artifact boundaries.
- Synthetic contract tests, Mac-local equivalent smoke, provisional refined98 golden-set scoring,
  GCP environment/GPU telemetry contract, and disk guards.
- The complete tracked inventory: 129 RAG candidates plus two parser/ETL regressions, reported as
  separate metric families rather than one blended semantic mean.

## 4. Out of Scope

- MMR, reranking, hybrid search, multi-query, table/visual semantic lanes, or model fine-tuning.
- Public HTTP serving, multi-user production deployment, Docker, Kubernetes, or self-hosted Langfuse.
- Treating Mac Ollama output as an official `gcp_local` result.
- Claiming multimodal visual understanding from the Mac page-text-only visual evaluation lane.
- Held-out execution before tuning and human approval are complete.
- Downloading multiple embedding or generation candidates at the same time.

## 5. Assumptions

- Local development runs on Apple Silicon without CUDA; vLLM/AWQ inference is therefore contract-
  tested or replaced by an explicitly labelled Mac-equivalent Ollama smoke.
- The assigned VM is `g2-standard-4`, 4 vCPU, 16 GB RAM, NVIDIA L4 24 GB, `us-central1`.
- The user-confirmed storage hard limit is 100 GB. The current 50 GB VM disk should be sufficient.
- Golden assets remain provisional until named human review. Structural/retrieval metrics may still
  be computed and labelled `provisional`.

## 6. Existing System Touchpoints

- `src/midprojectrag/indexing/embeddings.py`: provider port, cache, normalization, batching.
- `src/midprojectrag/indexing/exact_index.py`: exact NumPy/FAISS index and artifact hash gates.
- `src/midprojectrag/answering/generation.py`: generator port and shared answer-plan contract.
- `src/midprojectrag/answering/pipeline.py`: provider-neutral retrieval/generation orchestration.
- `src/midprojectrag/evaluation.py`: run-record validation, scoring, and API↔GCP comparison.
- `evaluation/schemas/run-record.schema.json`: reproducible environment and GPU-usage record.
- `resources/data_refined/private/chunks.page-v1.jsonl`: canonical private chunk input.

## 7. Proposed Design

```text
refined98 page-v1 chunks
        |
        v
KURE-v1 (pinned, 1024-d) --> normalized vectors/cache
        |                            |
        +----------------------------v
                         FAISS IndexFlatIP (CPU)
                                    |
question --> KURE query embedding --> top-10 --> context top-5
                                                |
                                                v
                           Qwen3-8B-AWQ / vLLM loopback
                                                |
                                                v
                         strict RagResponse + citations + run record
```

The embedding process may use GPU for offline indexing on GCP, but online query embedding defaults
to CPU so vLLM owns the L4 memory budget. Only one model pair is stored. The app sends private text
only to literal loopback endpoints and never through proxies or redirects.

## 8. Contracts

### 8.1 Runtime Profile Contract

| Field | Fixed value |
| --- | --- |
| `stack_id` | `gcp_local` only on the exact GCP environment |
| corpus | refined98, manifest SHA pinned |
| chunker | `page-v1`, 9,331 primary chunks |
| embedding model | `nlpai-lab/KURE-v1` |
| embedding revision | `4ed4540949c70b7da2c74004a915e1f2d5e46e4f` |
| dimensions | `1024` |
| generation model | `Qwen/Qwen3-8B-AWQ` |
| generation revision | `4da05a8edb55c6046cce958586c33b61da07bb79` |
| quantization | `awq-int4` |
| runtime | `vllm` |
| runtime version | `0.8.5.post1` |
| model context | `8192` |
| max output | `1024` |
| thinking | disabled |
| temperature | `0` |
| retrieval | exact dense top-10, context top-5, max citations 3 |
| disk | maximum 100 GB, warning at 80 GB, minimum 10 GB free |

### 8.2 Embedding Provider Contract

`KureEmbeddingProvider.embed(texts) -> EmbeddingBatch`

- Requires non-empty strings and rejects any input over 8,192 tokenizer tokens before encoding.
- Loads only the allowlisted model and exact revision; `main` or an unpinned revision is invalid.
- Returns finite shape `(n, 1024)` vectors. Core code performs canonical L2 normalization.
- `requires_budget=false`, cost is exactly zero, and no private text is logged.
- `local_files_only=true` is required after the explicit model-download stage.

`HuggingFaceTokenCounter.count(text) -> int`

- Uses the tokenizer from the same pinned KURE revision.
- Counts special tokens without truncation and returns a positive integer.

### 8.3 Generation Provider Contract

`VllmGenerator.generate(prompt) -> (plan, input_tokens, output_tokens)`

- Accepts only a literal `http://127.0.0.1:<port>` or `http://[::1]:<port>` endpoint.
- Disables environment proxies and HTTP redirects.
- Verifies `/v1/models` contains the exact served model before sending private context.
- Sends the shared system instructions and JSON Schema, with Qwen thinking disabled.
- Rejects missing/invalid JSON, model mismatch, truncation, response overflow, and invalid usage.
- Returns zero estimated monetary cost. GPU time and peak VRAM are recorded separately.

`PinnedQwenChatTokenCounter.count_chat(system, prompt) -> int`

- Loads tokenizer/config assets only from the exact Qwen revision, without model weights.
- Applies the model chat template with `enable_thinking=false` and the full transmitted system/user
  messages. Input tokens plus the reserved 1,024 output tokens must not exceed 8,192.

### 8.4 Run Record Contract

Official `gcp_local` records require:

- exact model IDs, both pinned revisions, `awq-int4`, `vllm`, and embedding dimension 1,024;
- exact vLLM package version `0.8.5.post1`; any upgrade requires a new recorded decision and smoke;
- the builder must receive the observed runtime version and rejects it unless it is exactly
  `0.8.5.post1`; it may not synthesize the version from a constant alone;
- exact machine/region/CPU/RAM/L4/disk constraints;
- non-null `gpu_seconds` and `peak_vram_gb` for every executed case;
- dependency-lock, corpus, evaluation, scoring, index-config, and Git commit hashes;
- no `api_profile`, API reasoning metadata, API cost, or Mac-equivalent environment claims.

Mac development results use `mac_local_equivalent` receipts outside the official run-record series.
They may prove contracts and produce provisional diagnostics, but API↔GCP compare must reject them.
Every candidate is bound to config/evaluation hashes and the verified index-config, row, vector, and
metadata hashes. Resume and scoring fail closed on any mismatch.

### 8.5 Storage and Security Rules

- Hard disk maximum: 100 GB; warning threshold: 80 GB; abort when free space is under 10 GB.
- Keep one `HF_HOME`; install without a persistent pip wheel cache; do not use Docker images.
- Do not copy the full 3.7 GB visual/raw tree to GCP. Transfer only code, page chunks, required
  metadata/manifest, index artifacts, and the selected private evaluation cases.
- Model weights, private chunks, vectors, prompts, answers, keys, and run records stay out of Git.
- Langfuse remains optional metadata-only and disabled by default.

### 8.6 Error / Capability Gap Rules

| Error | Required behavior |
| --- | --- |
| dependency/model absent | fail before corpus processing with a stable code |
| unpinned model revision | reject configuration |
| non-loopback generation URL | reject before sending prompt |
| disk >=80 GB used | warn and record; do not download another model |
| disk <10 GB free or disk >100 GB | fail closed |
| CUDA/L4 absent | forbid official `gcp_local` label; allow Mac-equivalent smoke only |
| GPU telemetry absent | run-record validation fails |
| golden case unapproved | allow only explicitly provisional evaluation |
| fixed Sol judge unavailable | structural/retrieval score only; semantic verdict remains blocked |

### 8.7 Full Mini131 Mac-equivalent Execution Contract

The full local suite is a coverage expansion of the Mac-equivalent path, not a replacement for the
official L4/vLLM profile in section 8.1.

| Evaluation lane | Count | Local execution adapter |
| --- | ---: | --- |
| Bid RAG scenarios | 40 | retained, hash-validated Core40 candidate transcript |
| Clause/fact answer regression | 44 | KURE page retrieval + Ollama Qwen generation |
| Conditional/all-list retrieval | 13 | complete-catalog map-reduce + natural-language answer |
| Gold/source alignment review | 12 | KURE page retrieval + Ollama Qwen generation; gold remains draft |
| HWP/PDF table/figure QA | 10 | page-text retrieval + Qwen only; no pixel/object/OCR input |
| Full-corpus analytics/EDA | 10 | deterministic case evidence + Qwen explanation |
| **RAG subtotal** | **129** | deterministic lane metrics; semantic score is a separate post-run step |
| Parser regression C21/C22 | 2 | live pinned-parser rerun, separate ETL PASS/FAIL |
| **Coverage total** | **131** | never average parser PASS/FAIL into the 129-case semantic mean |

The adapter rules are binding:

- Page-answer lanes use the verified 9,331-row KURE index with exact top-10 retrieval and top-5
  context. The reusable Core40 rows must match request, response, adapter, system-prompt and source
  hashes before resume accepts them.
- Each set case scans all 98 document catalog rows in deterministic batches of at most 14. Qwen maps
  every batch to candidate document IDs, then a final Qwen consolidation selects the complete global
  set. A simple union is invalid for maximum/minimum, comparison and exclusion questions. Precision,
  recall, F1, exact match and count accuracy are deterministic companion metrics.
- The ten visual cases exercise only searchable page text in this baseline. Image pixels, table-cell
  matrices, object crops, OCR and visual embeddings are not provided to Qwen; a miss measures the
  page-text baseline's capability gap and must not be described as multimodal performance.
- Each analytics prompt receives only the case-scoped deterministic evidence needed for the frozen
  operation and a `calculation:<case_id>` citation identity. Gold expected values, pass/fail flags and
  prior judgments are excluded. Qwen must still produce the recorded user-facing explanation.
- Parser cases rerun the current pinned parser and indexability checks. A historical receipt alone is
  insufficient, and their two PASS/FAIL results remain outside RAG answer-quality aggregation.
- Resume is candidate-atomic and fail-closed on suite, config, evaluation, source, prompt or adapter
  drift. Runtime errors and truncations are retained as measured failures rather than silently repaired.
- The disk guard applies before model/index work: hard maximum 100 GB, warning at 80 GB used and abort
  below 10 GB free. The current Mac working set remains a local measurement, not GCP disk evidence.
- All 129 candidates, deterministic scoring and the fixed-Sol ledger aggregate are now closed. Until
  gold receives named human approval, the result remains `mac_local_equivalent`, `official=false`
  and provisional. It is not eligible for an official API↔GCP comparison without live GCP evidence.
- In the semantic adapter, `candidate_output_visible_to_reviewer=false` means that the reviewer
  cannot access the raw candidate artifact, file path, case ID or lineage metadata. The sanctioned,
  hash-bound blind projection still includes the candidate answer/status, required chat context and
  retrieved/cited evidence because those fields are necessary to apply the frozen rubric.

### 8.8 Measured Full Mini131 Mac-equivalent Evidence (2026-09-01)

- Coverage closed at 129/129 RAG candidates plus 2/2 fresh parser regressions. The parser results are
  not included in any RAG mean.
- Candidate outcomes were 87 answered, 36 abstained and 6 runtime/contract errors. The measured error
  rate is `0.046512`; failures remain in the denominator.
- Document retrieval measured Recall@1/5/10 `0.921986/0.987589/0.991135` and MRR@10 `1.0`.
- The thirteen complete-catalog set cases measured count accuracy `0.538462`, precision `0.608974`,
  recall `0.692308`, F1 `0.630769` and exact-match rate `0.538462`.
- Visual retrieval measured document Recall@1/5/10 and MRR@10 at `1.0`; page scores were
  `0.35/0.6/0.6` and `0.475`, while chunk-or-block and object scores were all `0`, preserving the
  page-text-only capability gap.
- Analytics exact/tolerance checks passed at `1.0` for 10/10 cases and all 139 comparisons
  (46 exact, 93 tolerance).
- Response-contract validity and citation validity were both `1.0` for validated applicable records.
  Median total latency was `33,405.49 ms`; p95 was `263,840.61 ms` because every set question scans
  seven catalog batches and may run a global consolidation.
- The frozen suite output ceiling is 1,200 tokens while the reused stack generation cap is 1,024;
  the receipt records both values and verifies that the runtime cap stays inside the suite ceiling.
- Set-map preflight is within context at 5,094 tokens. The 98-row × 400-character worst-case final
  probe is 102,687 tokens and intentionally records `context_ok=false`; it is a non-readiness stress
  probe because runtime rejects overflow before transport.
- Fresh fixed-Sol review closed at 88 accepted and 41 rejected, acceptance `0.682171` and mean score
  `70.135659`, with role counts primary 129, secondary 4 and adjudicator 3. The content-free evidence
  is the [public semantic receipt](../../../evaluation/baselines/gcp-local-kure-qwen3-8b-awq-mini131-v1/mac-local-equivalent-semantic-receipt.json).
- This evidence is a Mac Ollama/NumPy exact run, not L4/vLLM/FAISS telemetry. The content-free receipt
  is `evaluation/baselines/gcp-local-kure-qwen3-8b-awq-mini131-v1/mac-local-equivalent-receipt.json`.
  It remains `official=false`, `passed=false`, draft-gold and provisional while named human gold
  approval and live GCP evidence are outstanding.

## 9. Acceptance Criteria

1. Shared request/response/citation tests pass unchanged.
2. KURE adapter produces deterministic finite 1,024-d embeddings and cache reuse works.
3. vLLM adapter rejects external URLs, redirects, model mismatch, malformed JSON, and truncation.
4. The 100 GB schema/validator boundary rejects 100.1 GB and accepts 100 GB.
5. A synthetic request completes through semantic embedder, exact index, generator, and citation gate.
6. Mac-local equivalent smoke is labelled non-official and cannot pass API↔GCP comparison.
7. The full Mac-equivalent pass persists 129 RAG candidates and two live parser results, validates
   every lane adapter, and produces only private transcripts plus a content-free aggregate receipt.
   Partial checkpoints are resumable but never labelled complete.
8. GCP execution records 100% GPU-seconds/peak-VRAM coverage and stays below 22 GB peak VRAM.
9. Flow target/current report, tests, safety scan, work logs, and a scoped commit are produced.

## 10. Implementation Batches

### Batch 5.1: Contract and Flow Freeze

**Goal:** Freeze model, storage, runtime, artifact, and evaluation boundaries.
**Done when:** this contract, decision, TODO, and target/current flow report agree.
**Checks:** config/schema examples and Mermaid render/static HTML validation.

### Batch 5.2: Provider and Run-Record TDD

**Goal:** Add pinned KURE, loopback vLLM, GCP telemetry/run-record adapters, and 100 GB gate.
**Done when:** provider/error/security/schema unit tests pass without model downloads.
**Checks:** stack boundary tests and evaluation contract tests.

### Batch 5.3: Local Semantic Retrieval

**Goal:** Prepare KURE locally, build the 9,331-row exact index, and measure retrieval.
**Done when:** index save/load/hash checks and provisional retrieval scoring complete.
**Checks:** cache rerun, Recall@1/3/5/10, MRR@10, nDCG@10.

### Batch 5.4: Local Equivalent End-to-End

**Goal:** Use the existing verified Ollama model only as a Mac-equivalent generator to validate the
full RAG contract, first on Core40 and then across all 129 RAG assets plus two parser regressions.
**Done when:** all lanes have validated private transcripts/results and a content-free provisional
receipt; parser results are separate and the Mac label cannot enter official comparison.
**Checks:** response/citation/abstention, complete-set map-reduce, visual page-text limitation,
analytics evidence projection, parser live rerun, cold/warm latency, no-content stdout/Git audit.

### Batch 5.5: GCP L4 Execution

**Goal:** Start the VM only when explicitly authorized, install the pinned runtime, run Qwen3-8B-AWQ
through vLLM, execute the provisional set, and stop the VM.
**Done when:** valid `gcp_local` records include GPU telemetry and API↔GCP comparable hashes.
**Checks:** VRAM <22 GB, disk guard, FAISS save/load, 2-case smoke then bounded/full provisional run.

## 11. Test Plan

- Unit: dependency gates, tokenizer count, vector shape, pinned revision, loopback URL, JSON parsing,
  telemetry, environment limits, and content-free error behavior.
- Integration: fake embedding/generation adapters through the shared pipeline and exact index.
- Local model smoke: KURE query/document similarity and Ollama strict-answer generation.
- Private provisional: retrieval first, then bounded E2E cases; store only private case/run records.
- GCP smoke: CUDA identity, model load, 8K context, peak VRAM, cold/warm latency, disk usage.
- Regression: stack boundary, evaluation contracts, full repository suite, compile, diff, safety.

## 12. Open Questions

- Named human review and held-out 20 remain external review gates, not implementation blockers.
- Absolute latency SLO remains unset; the first measured GCP run establishes the comparison baseline.
- If Qwen3-8B-AWQ fails on the pinned vLLM/L4 combination, fallback selection requires a new recorded
  decision; it may not silently change this baseline.

## 13. Measured Mac-equivalent Core40 Evidence

- Frozen inputs: refined98 `page-v1`, 9,331 chunks, KURE 1,024-d, config SHA
  `980e6777bc90d47fe8b5f1a51c007059a32aa67d4594aff2ad11628e09011f1e`.
- Execution: 40/40 persisted; completion used 38 new + 2 resumed candidates; replay used 0 new +
  40 resumed candidates.
- Retrieval: document recall@1 `0.833333`, recall@3/5/10 `1.0`, MRR@10 `1.0`, nDCG@10
  `0.991972`; source-block recall@1/3/5/10 `0.578889/0.69/0.753333/0.865556`.
- Contract/behavior: citation validity `1.0`, response contract validity `1.0`, abstention match
  `0.775`, runtime error rate `0.025`.
- Latency: total p50 `34,996.577458 ms`, p95 `65,119.728166 ms`.
- Failure retained: one `generation_abstention_invalid`; the model returned `abstained` with a
  non-empty answer. No post-hoc coercion or mixed-prompt single-case rerun was applied.
- Storage: 9,169,366,585-byte working set; 100 GB/free-space preflight passed without warning.
- Public receipt SHA-256:
  `c77c0aa6409b24517ae94b219148202a4bb129c21e2f6b4003a22aa1244928da`.

These measurements describe only the completed 40-case core run. They must not replace or be
presented as the aggregate result of the separately completed 131-asset coverage run.

## 14. Remaining Evidence Gates

- Batch 5.5 still needs explicit VM authorization, a pinned Linux/CUDA/vLLM environment, FAISS CPU,
  a Linux-resolved dependency lock, Qwen3-8B-AWQ inference, and measured GPU telemetry. The
  committed arm64 lock is evidence for the Mac-equivalent run, not a Linux lock.
- The 129-RAG + 2-parser Mac-equivalent run, deterministic aggregate report and content-free receipt
  are complete. They remain non-official Mac evidence and do not satisfy the live GCP gate.
- The fresh fixed-Sol ledger aggregate is complete. Named human gold approval remains external, so
  the semantic result stays provisional and cannot become a gold-approved quality verdict.

## 15. Handoff Notes for Implementation Agent

Implement provider adapters under `stacks/local` without importing API modules. Preserve the current
Mac hash/Ollama path. Keep all model/data loading lazy so unit tests need no weights. Add a dedicated
GCP-local runner/config instead of overloading `local-index`/`local-query`, and never emit an official
GCP record from a non-L4 machine.
