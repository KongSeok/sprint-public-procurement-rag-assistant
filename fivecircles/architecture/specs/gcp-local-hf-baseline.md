# GCP Local HF Baseline Contract

Status: LOCAL_EQUIVALENT_40_EXECUTED_WITH_1_RUNTIME_ERROR
Decision date: 2026-08-31
Scope: refined98 page-only RAG baseline, local development proof, GCP L4 execution

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

## 3. In Scope

- Existing refined98 `page-v1` body chunks: 98 documents and 9,331 chunks.
- `nlpai-lab/KURE-v1` semantic embedding, 1,024 dimensions, revision pinned by full commit SHA.
- CPU FAISS `IndexFlatIP` over L2-normalized vectors.
- `Qwen/Qwen3-8B-AWQ` generation through a loopback-only vLLM OpenAI-compatible endpoint.
- Non-thinking generation, 8,192-token model context, deterministic decoding, and strict JSON output.
- Existing `RagPipeline`, citation validation, abstention contract, and private artifact boundaries.
- Synthetic contract tests, Mac-local equivalent smoke, provisional refined98 golden-set scoring,
  GCP environment/GPU telemetry contract, and disk guards.

## 4. Out of Scope

- MMR, reranking, hybrid search, multi-query, table/visual semantic lanes, or model fine-tuning.
- Public HTTP serving, multi-user production deployment, Docker, Kubernetes, or self-hosted Langfuse.
- Treating Mac Ollama output as an official `gcp_local` result.
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

## 9. Acceptance Criteria

1. Shared request/response/citation tests pass unchanged.
2. KURE adapter produces deterministic finite 1,024-d embeddings and cache reuse works.
3. vLLM adapter rejects external URLs, redirects, model mismatch, malformed JSON, and truncation.
4. The 100 GB schema/validator boundary rejects 100.1 GB and accepts 100 GB.
5. A synthetic request completes through semantic embedder, exact index, generator, and citation gate.
6. Mac-local equivalent smoke is labelled non-official and cannot pass API↔GCP comparison.
7. Available provisional golden cases produce private candidate records and aggregate retrieval/
   contract metrics without leaking content to stdout or Git.
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
full RAG contract and generate a bounded provisional candidate set.
**Done when:** synthetic plus selected golden cases have private transcripts and aggregate receipts.
**Checks:** response/citation/abstention, cold/warm latency, no-content stdout/Git audit.

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

## 13. Measured Mac-equivalent Evidence

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

## 14. Remaining Evidence Gates

- Batch 5.5 still needs explicit VM authorization, a pinned Linux/CUDA/vLLM environment, FAISS CPU,
  a Linux-resolved dependency lock, Qwen3-8B-AWQ inference, and measured GPU telemetry. The
  committed arm64 lock is evidence for the Mac-equivalent run, not a Linux lock.
- Human approval and the fixed semantic judge remain external. Until they run, the score is
  provisional diagnostics rather than a semantic quality verdict.

## 15. Handoff Notes for Implementation Agent

Implement provider adapters under `stacks/local` without importing API modules. Preserve the current
Mac hash/Ollama path. Keep all model/data loading lazy so unit tests need no weights. Add a dedicated
GCP-local runner/config instead of overloading `local-index`/`local-query`, and never emit an official
GCP record from a non-L4 machine.
