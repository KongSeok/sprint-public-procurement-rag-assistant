# Evaluation Contract

Status: ACTIVE_GPT56_SEMANTIC_JUDGE

Version: 1.2

Date: 2026-08-31

External calls: baseline provider calls require the existing destination/payload/cost approval;
ChatGPT workspace judgment stays private and does not publish evaluation text

## 1. Goal

Define one reproducible evaluation contract for the OpenAI API stack and the GCP L4 local
Hugging Face stack. It must measure the four required behaviors separately:

1. single-document question answering
2. multi-document comparison
3. follow-up questions using explicit conversation history
4. abstention for unknown, unsupported or ambiguous questions

The contract separates retrieval quality, answer quality, citation quality, abstention and
operational cost. The semantic judge is fixed; the candidate generation model and RAG stack are
deliberately variable experiment inputs. `gpt-5-mini` is the current first integrated candidate
baseline, not the fixed system under test.

## 2. Scope and exclusions

In scope:

- private dev and held-out case contracts
- stack-neutral query and response contracts
- offline validation, scoring and A/B aggregate comparison
- deterministic snapshot and configuration hashes
- ChatGPT `gpt-5.6-sol` direct semantic judgment for Korean long-form answers

Out of scope:

- unapproved model calls, embeddings or corpus downloads
- code, lexical, regex or embedding-similarity rules acting as the semantic answer judge
- model-written changes to gold questions, reference answers or qrels
- hidden server session state
- production latency SLOs not supplied by the assignment
- committing raw RFP text, source-level chunks, private gold text or answer-level traces

### 2.1 Frozen judge and variable system-under-test

The following separation is binding for every baseline, ablation and stack comparison.

| Role | Frozen or variable | Contract |
| --- | --- | --- |
| Semantic judge | Frozen | ChatGPT `gpt-5.6-sol` |
| Judge rubric | Frozen | `evaluation/rubric.md` version `gpt56-semantic-v2`, including its prompt/schema, thresholds and adjudication rules |
| Gold and scoring inputs | Frozen within one experiment series | question order, reference answers, required fact groups, qrels, corpus snapshot and scoring hashes |
| Candidate generator | Variable | current first integrated run: `gpt-5-mini`; later API and local models may be compared |
| Candidate RAG/ETL stack | Variable | parser, normalization, chunking, embedding, index, retrieval, filters, Top-k, reranking/MMR, context builder, generation prompt and citation behavior |

Each candidate configuration must produce and persist its own answer transcript before semantic
judgment begins. The transcript binds the exact question/history, retrieval results, selected
context, candidate model response, final answer/status and citations to hashes. GPT-5.6 Sol judges
that recorded candidate output; it must not regenerate, repair, supplement or replace the
candidate answer. A missing candidate answer or transcript is `unjudged`/runtime failure until the
candidate run is executed and recorded.

Changing the judge model, rubric version, judge prompt/schema, score thresholds or adjudication
rules starts a new evaluation series. Scores from different judge contracts must not be mixed in
one comparison table.

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
Every held-out response requires a primary GPT-5.6 judgment. Boundary, low-confidence and
disputed cases require the independent secondary/adjudication path defined in section 13.

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

The current project-wide inventory is broader than that original 60-case target. The table below
is the tracked binding count contract; `golden-set-final/golden-set-count-contract.md` is its
local audit source:

| Evaluation lane | Count | Primary scoring path |
| --- | ---: | --- |
| Bid RAG scenarios | 40 | recorded candidate answer judged by fixed GPT-5.6 Sol |
| Clause/fact answer regression | 44 | recorded candidate answer judged by fixed GPT-5.6 Sol |
| Conditional/all-list retrieval | 13 | complete document-set P/R/F1 and exact match plus required recorded candidate answer judged by Sol |
| Gold/source alignment review | 12 | recorded candidate answer judged by Sol; gold approval remains a separate human-review state |
| HWP/PDF table/figure QA | 10 | retrieval/object metrics plus recorded candidate answer judged by Sol |
| Full-corpus analytics/EDA | 10 | exact/tolerance numeric checks plus required recorded candidate explanation judged by Sol |
| **RAG evaluation assets** | **129** | lane-specific RAG scores |
| Parser fallback regression | 2 | deterministic ETL execution PASS/FAIL, reported separately |
| **Total test/review assets** | **131** | coverage total only; do not blend ETL PASS/FAIL into the RAG semantic mean |

The 60 authored automatic inputs are a subset of the 129 RAG assets, not an additional suite to
add to 129. All draft/approval states remain visible in reports.

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

Every answer-level private experiment artifact set includes:

- opaque experiment/run ID and candidate-stack label
- stack, generator and embedding model/revision
- parser, chunking, index, retrieval, reranking, context and prompt configuration
- Git commit, corpus manifest hash, evaluation-set hash and configuration hash
- Python/platform, dependency-lock hash, vCPU/RAM/GPU/disk environment snapshot
- ranked chunk hits mapped back to stable source blocks
- immutable candidate transcript/response and a separately attributable private ChatGPT
  `gpt-5.6-sol` semantic judgment
- retrieval/generation/total latency
- API tokens/USD or GPU seconds/peak VRAM
- seed, temperature and cache state; unsupported generation controls are recorded as null
- exact candidate transcript hash and frozen judge-config hash

The legacy `run-record.schema.json` v1 compatibility artifact may embed the finalized judgment
after the separate judgment step. It is a scored join artifact, not evidence that the judge ran
before the candidate answer was closed; the candidate transcript hash and content remain
immutable.

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
- blinded ChatGPT `gpt-5.6-sol` correctness, completeness and faithfulness
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
- answerable GPT-5.6 semantic-judgment coverage: 1.0
- API cost or local GPU-usage coverage, as applicable: 1.0

These targets, their operators, stack scopes, task floors and Recall@1/3/5/10 cutoffs are
frozen before stack experiments. Missing, malformed or weakened gates fail scoring. Missing a
target is reported as a result; held-out data is not retuned to make a target pass.

## 12. A/B protocol

Every candidate stack uses the same corpus snapshot, evaluation-set hash, question order,
explicit history, gold contract and frozen judge configuration. Use deterministic decoding and a
recorded seed when supported. Only the candidate model/stack configuration may vary within the
comparison series.

For an explicit document scope, both retrieval hits and response citations outside the listed
document IDs are contract failures.

Report two comparisons when feasible:

1. controlled context comparison with identical retrieved source blocks, isolating generation
2. end-to-end comparison using each stack's retrieval and generation configuration

The aggregate comparison reports deltas rather than declaring a winner. The final decision
must weigh quality, latency, API spend, GPU usage and operational constraints together.

## 13. GPT-5.6 semantic judgment protocol

Answer meaning is judged directly by ChatGPT `gpt-5.6-sol`; no repository function may infer
correctness, completeness, faithfulness, citation quality or abstention quality from lexical,
regex or embedding similarity. Such values may remain visible only as `diagnostic_only`.

For each answer case the judge reads the private question, reference answer and required facts,
the actual model answer or abstention, the retrieved context and cited/expected evidence. It
records the rubric version/hash, case hash, run-record hash, exact judge-input hash, model ID,
decision, component scores, confidence and a concise rationale in a private judgment JSONL. Code may validate this closed
record, check hashes and aggregate its supplied scores; code does not create or revise the
semantic decision.

Judgment order is fixed:

1. execute the candidate stack on the frozen question set
2. persist the exact candidate transcript, answer/status, citations and retrieved evidence
3. hash and close the candidate run record
4. give the closed record plus frozen gold/evidence to GPT-5.6 Sol
5. persist the Sol judgment separately and aggregate without rewriting the candidate record

The candidate may be Mini, Nano, another API model or a local model. Candidate identity is hidden from
the judge where feasible and never changes the rubric.

The semantic reviewer receives only an opaque `blind_id`, a signed judge-input hash and a
non-identifying `question_kind` with the review content. Case IDs, source execution lanes and
candidate lineage stay exclusively in the private local merge envelope; local code restores them
only after validating the opaque binding.

Primary review may use deterministic blind-row slices. Secondary review receives only the
locally computed primary-trigger subset and no prior judgment content. Adjudication receives a
closed non-identifying packet containing the original blind row and the hash/config-validated
primary and secondary blind decisions. The exact visible input and returned decision for every
role are sealed atomically at mode `0600` in a hash-bound private review-history artifact.

Only prospectively persisted, runtime-exact candidate transcripts are eligible for a Version 1.2
comparison score. Post-hoc reconstructed transcripts and records with unavailable or elided final
answers remain legacy diagnostics and must be re-executed before scoring in this series. In
particular, `supplemental-provisional-v1` used `gpt-5-mini`, reconstructed all 69 transcripts after
execution and lacks the exact final answer for 30 records. The current Mini 131 completion may reuse
only its 39 exact answers as a clearly labelled mixed-lineage provisional diagnostic; the other 90
RAG answers are prospectively rerun. It is not a fully prospective Version 1.2 baseline.

The primary semantic judge is `gpt-5.6-sol`. A second independent `gpt-5.6-sol` judgment is
required when the primary returns `needs_review`, low confidence, or a boundary score. Retrieval rank, set overlap, latency, usage and cost remain
deterministic metrics because they are exact measurements rather than semantic judgments.

Gold/qrel approval and generated-run quality are separate contracts. A gold-review decision
binds to the case only. An answer-quality judgment binds to the case, generated run and exact
evidence bundle, and must never approve, edit or replace the gold asset.

The frozen scoring details are in `evaluation/rubric.md`. Raw questions, gold answers, source
text, generated answers and rationales stay under ignored private evaluation paths. Public
artifacts contain aggregate counts, scores and hashes only.

### 13.1 Lane-specific deterministic metrics

Deterministic code may calculate facts that do not require semantic interpretation:

- conditional/all-list cases compare the complete `selected_doc_ids` set using Precision,
  Recall, F1 and exact match; chat Top-k, context size, citation count and the UI 20-document
  selection limit must not truncate this scoring response
- the current 13 list cases contain at most 12 gold documents; inability to return the complete
  set is recorded as a candidate capability failure, not attributed to the UI limit
- list metrics do not replace the required candidate natural-language answer or Sol judgment;
  missing prose/transcript leaves the RAG case `unjudged`
- analytics cases compare required numeric fields by exact match or frozen tolerance; GPT-5.6 Sol
  judges the recorded natural-language explanation, not the arithmetic produced by code
- a deterministic analytics result without the candidate explanation is capability evidence, not
  a completed end-to-end RAG score
- the two legacy fallback cases now verify the current invariant—pinned `rhwp` extraction succeeds,
  block files match the manifest and both documents are indexable. Obsolete pyhwp/native fallback
  activation is not claimed or scored; ETL PASS/FAIL remains outside the 129-case RAG semantic mean

Set and numeric measurements supplement the fixed Sol judgment and never act as a rule-based
substitute for semantic correctness. Parser PASS/FAIL is a separate ETL lane rather than a
semantic companion metric.

## 14. Privacy and egress rules

Baseline generation egress follows the destination/payload/cost approval recorded for that
run. Direct ChatGPT GPT-5.6 judgment is authorized for this evaluation contract and operates on
private local artifacts. Private evaluation files and run records remain outside Git.

Questions, gold answers and reviewer notes must be redacted before publication. Public artifacts
may contain schemas, code, hashes, aggregate metrics and synthetic examples, but not raw excerpts,
PII, source-level chunks or answer traces that reconstruct restricted material.

## 15. Failure behavior

- invalid JSONL, schema violations or split leakage return a non-zero exit code
- score reports record missing/duplicate runs and response-contract violations
- comparison refuses mismatched corpus or evaluation hashes
- comparison refuses same-stack, failed, fabricated or scoring-config-mismatched reports
- external schema references resolve only through `evaluation/schemas/registry.json`
- no validator prints question text, source blocks or raw model prompts in its issue messages
