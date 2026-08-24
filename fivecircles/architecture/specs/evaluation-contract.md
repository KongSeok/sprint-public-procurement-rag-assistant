# Evaluation Contract

Status: Batch 2 baseline contract

Version: 1.0

External calls: prohibited during Batch 2

## 1. Goal

Define one reproducible evaluation contract for the OpenAI API stack and the GCP L4 local
Hugging Face stack. It must measure the four required behaviors separately:

1. single-document question answering
2. multi-document comparison
3. follow-up questions using explicit conversation history
4. abstention for unknown, unsupported or ambiguous questions

The contract separates retrieval quality, answer quality, citation quality, abstention and
operational cost. It does not select a model or retrieval technique.

## 2. Scope and exclusions

In scope:

- private dev and held-out case contracts
- stack-neutral query and response contracts
- offline validation, scoring and A/B aggregate comparison
- deterministic snapshot and configuration hashes
- human-review fields for Korean long-form answers

Out of scope:

- model calls, embeddings or corpus downloads
- automatic LLM-as-judge evaluation
- hidden server session state
- production latency SLOs not supplied by the assignment
- committing raw RFP text, source-level chunks, private gold text or answer-level traces

## 3. Contract files

- `contracts/rag-request.schema.json`
- `contracts/rag-response.schema.json`
- `evaluation/schemas/eval-case.schema.json`
- `evaluation/schemas/run-record.schema.json`
- `evaluation/schemas/registry.json`
- `evaluation/config/metrics.json`
- `evaluation/rubric.md`

The JSON Schemas are provider-neutral interchange contracts. The Python validator enforces
the task-specific and cross-file invariants using the standard library only.

## 4. Query contract

A query contains a portable request ID, question, explicit history, document scope and maximum
citation count. `document_scope.mode=all` requires an empty `doc_ids` list. `explicit` requires
one or more pseudonymous document IDs.

Evaluation always transmits history explicitly. A product layer may resolve a conversation ID
to history, but the resulting request snapshot must be self-contained before evaluation.

## 5. Response contract

Every response has exactly one state:

- `answered`: non-empty answer, one or more citations, no abstention or error object
- `abstained`: safe explanatory message, supported abstention reason, no citations or error
- `error`: runtime error object, no citations or abstention

A runtime failure never counts as a successful abstention. Citations contain pseudonymous
document and chunk IDs, stable source block IDs, section path and nullable page range. They do
not contain raw excerpts or contact information.

An abstention uses the exact non-factual message associated with its reason. For an unknown
case, that reason must match the sealed gold reason and `judgment.safe_abstention` must be true.
Every held-out response, including an abstention, requires two reviewers.

## 6. Evaluation case contract

Every case records:

- unique `case_id` and leakage-control `group_id`
- `dev` or `heldout` split
- one of the four task types
- question, explicit history and document scope
- answer/abstain decision
- short private reference answer and key-point IDs
- required document IDs and stable source-block evidence references
- comparison axes or abstention reason when applicable
- corpus manifest SHA-256 and two-person authorship/review state

Gold evidence references `source_block_id`, not experiment-specific `chunk_id`. Chunking,
overlap, MMR or reranking can therefore change without rewriting the gold set. Locator hashes
verify a private locator without copying source text into the evaluation file.

## 7. Task invariants

### Single document

- exactly one required document
- at least one key point and evidence reference
- `gold.decision=answer`

### Multi-document comparison

- at least two required documents
- at least one comparison axis
- evidence from every required document
- `gold.decision=answer`

### Follow-up

- non-empty fixed history
- conversation/turn metadata and dependencies resolving to explicit prior turn IDs
- stable history for the controlled A/B comparison
- `gold.decision=answer`

An additional end-to-end conversation run may feed each stack its own prior answer, but it is
reported separately because the input contexts are no longer identical.

### Unknown

- `gold.decision=abstain`
- one of `insufficient_evidence`, `out_of_scope` or `ambiguous`
- no reference answer, required documents, evidence, key points or comparison axes

## 8. Dataset construction and leakage control

The initial target is 60 approved questions:

- dev: 10 per task, 40 total
- held-out: 5 per task, 20 total

Paraphrases, related comparison variants and every turn from one conversation share a
`group_id`. A group may appear in only one split. Multi-document pairs must not be duplicated
across splits under different wording.

Validation also rejects exact normalized question reuse and repeated multi-document pairs even
when their `group_id` values differ. Paraphrase review remains a required human check.

The held-out file is hashed and sealed before retrieval or prompt tuning. Dev may be run
repeatedly. Held-out is run once after configuration freeze; any rerun and its reason must be
reported explicitly.

Validation returns separate `dev_sha256`, `heldout_sha256` and combined `dataset_sha256`
values plus order-sensitive combined/dev/held-out sequence hashes. Exact-question leakage uses
Unicode NFC, collapsed whitespace and case-folding before hashing; semantic paraphrases still
require human review.

## 9. Run record and reproducibility

Every answer-level private run record includes:

- stack, generator and embedding model/revision
- Git commit, corpus manifest hash, evaluation-set hash and configuration hash
- Python/platform, dependency-lock hash, vCPU/RAM/GPU/disk environment snapshot
- ranked chunk hits mapped back to stable source blocks
- contract response and offline human judgments
- retrieval/generation/total latency
- API tokens/USD or GPU seconds/peak VRAM
- seed, temperature and cache state

One score report contains only one stack, corpus snapshot and configuration. A/B comparison
accepts exactly one passed API report and one passed GCP-local report and fails closed if corpus,
evaluation or scoring-config hashes differ or required metric evidence is incomplete.

The run `config_sha256` identifies retrieval/generation settings. The aggregate
`scoring_config_sha256` separately identifies the metric thresholds used to score the run, and
must match between A/B reports.

## 10. Metrics

Retrieval:

- document Recall@1/3/5/10
- source-block Recall@1/3/5/10
- MRR@10 and nDCG@10
- multi-document all-required-doc recall

Answer and citation:

- required key-point coverage
- blinded human correctness and faithfulness
- factual-claim citation coverage
- citation validity and gold-evidence citation precision
- follow-up task success

Abstention:

- precision and recall
- false-answer rate on unknown cases
- false-abstain rate on answerable cases
- safe-abstention rate, including reason match and required reviewer coverage

Operations:

- contract/runtime error rate
- p50/p95 total latency and component p50 latency
- API total/mean USD cost
- local total/mean GPU seconds and peak VRAM
- reviewed-judgment and stack-specific usage coverage

Document Recall@k uses the document IDs present in the first k ranked chunk hits. Repeated hits
from one document do not increase recall and do not pull a document below rank k into the set.

Latency is a comparison metric until the team freezes an SLO. The API USD 20 cap and GCP
4 vCPU/16 GB/L4/100 GB limits remain hard assignment constraints.

## 11. Initial acceptance targets

- structural schema, reference integrity and split isolation: 100%
- document Recall@5: at least 0.90
- multi-document all-required-doc Recall@10: at least 0.80
- key-point coverage and follow-up success: at least 0.80
- citation validity: at least 0.95
- faithfulness: at least 0.90
- unknown recall: at least 0.80
- unknown false-answer rate: at most 0.20
- reviewed safe-abstention rate: 1.0
- response contract and runtime error rate: 0
- API total: at most USD 20
- answerable human-judgment coverage: 1.0
- API cost or local GPU-usage coverage, as applicable: 1.0

These targets, their operators, stack scopes, task floors and Recall@1/3/5/10 cutoffs are
frozen before stack experiments. Missing, malformed or weakened gates fail scoring. Missing a
target is reported as a result; held-out data is not retuned to make a target pass.

## 12. A/B protocol

Both stacks use the same corpus snapshot, evaluation-set hash, question order, explicit history
and output contract. Use deterministic decoding and a recorded seed when supported.

For an explicit document scope, both retrieval hits and response citations outside the listed
document IDs are contract failures.

Report two comparisons when feasible:

1. controlled context comparison with identical retrieved source blocks, isolating generation
2. end-to-end comparison using each stack's retrieval and generation configuration

The aggregate comparison reports deltas rather than declaring a winner. The final decision
must weigh quality, latency, API spend, GPU usage and operational constraints together.

## 13. Privacy and egress rules

The Drive corpus access level and provider egress permission are not assumed. Until the pending
egress decision is resolved, this batch performs local schema validation and synthetic tests
only. Private evaluation files and run records remain outside Git.

Questions, gold answers and reviewer notes must be redacted before publication. Public artifacts
may contain schemas, code, hashes, aggregate metrics and synthetic examples, but not raw excerpts,
PII, source-level chunks or answer traces that reconstruct restricted material.

## 14. Failure behavior

- invalid JSONL, schema violations or split leakage return a non-zero exit code
- score reports record missing/duplicate runs and response-contract violations
- comparison refuses mismatched corpus or evaluation hashes
- comparison refuses same-stack, failed, fabricated or scoring-config-mismatched reports
- external schema references resolve only through `evaluation/schemas/registry.json`
- no validator prints question text, source blocks or raw model prompts in its issue messages
