# ChatGPT GPT-5.6 Direct Semantic Judge Rubric

Version: `gpt56-semantic-v2`

Primary judge: `gpt-5.6-sol`

## Purpose

Automated retrieval and contract metrics do not reliably judge Korean RFP summaries and
multi-document comparisons. ChatGPT `gpt-5.6-sol` therefore reads the private evaluation
evidence and directly assigns the semantic fields in each private judgment record. Repository
code only validates and aggregates the returned record. Stack names must be hidden while
held-out answers are judged.

Reviewer-visible inputs use an opaque `blind_id`, the signed `judge_input_sha256`, and a
non-identifying `question_kind`. Case IDs, source execution lanes and candidate lineage remain
only in the private local merge envelope and are never shown to a semantic reviewer.

Primary reviewers receive all blind rows or deterministic slices. Secondary reviewers receive
only the locally validated trigger subset and never see a primary score or rationale. An
adjudicator receives one non-identifying packet containing the original blind row plus the two
hash/config-validated prior blind decisions. Every role's exact reviewer-visible input and output
is sealed in a private `0600` history row with content hashes; hidden reasoning is not requested
or stored.

Version 2 freezes one judge contract for variable candidate models and stacks. All 129 RAG
assets require a closed candidate answer/transcript before judging. Strict comparison runs require
prospective runtime-exact records; the current mixed-lineage provisional Mini completion labels its
39 reused exact answers and reconstructed transcripts separately. The two parser regressions are
deterministic ETL checks and are not semantic-answer cases.

## Scored fields

Use only `0`, `0.5`, or `1` for the component fields.

### `correctness`

- `1`: all required key points are materially correct and no material contradiction exists.
- `0.5`: the main conclusion is correct but a required point is incomplete or imprecise.
- `0`: the conclusion is wrong, reverses a comparison, or invents a material fact.

### `faithfulness`

- `1`: every material factual statement is supported by the cited source blocks.
- `0.5`: the answer is mostly supported but includes a minor unsupported statement.
- `0`: a material claim is unsupported or contradicts the cited evidence.

### `completeness`

- `1`: all required facts or comparison axes needed to answer the question are covered.
- `0.5`: the main answer is useful but one or more non-critical required items are omitted.
- `0`: the answer misses the core requested result or most required items.

### `factual_claim_coverage`

- `1`: every material factual claim has a citation.
- `0.5`: at least half, but not all, material claims have citations.
- `0`: fewer than half of the material claims have citations.

### `citation_validity`

- `1`: all citations resolve to the claimed document and stable source location.
- `0.5`: all citations resolve, but one locator is too broad or only partially supports the claim.
- `0`: a citation does not resolve or points to unrelated evidence.

### `matched_key_point_ids`

Record only the `point_id` values visibly satisfied by the answer. Do not add a point because
the answer is plausible; it must satisfy the corresponding gold text.

### `follow_up_success`

Set `true` only when the answer resolves the intended prior entity or condition and does not
contradict the fixed history. Use `null` for non-follow-up cases.

### `safe_abstention`

Use this field only for unknown cases. Set `true` only when the response uses the exact
non-factual message for the sealed gold reason, contains no factual answer or unsupported
recommendation in its detail, and is a deliberate abstention rather than a runtime failure.
Set `false` when any of those conditions fail. Use `null` for answerable cases.

## Decision and score

For an answerable case calculate the displayed score from the judge-supplied components:

```text
semantic_score = 100 × (
  0.35 × correctness
  + 0.25 × faithfulness
  + 0.20 × completeness
  + 0.10 × factual_claim_coverage
  + 0.10 × citation_validity
)
```

This formula is deterministic aggregation, not a semantic judge. The judge must supply each
component after reading the actual evidence.

Apply primary-judge precedence exactly in this order:

1. `rejected` for a material contradiction/hallucination, core invalid citation, false
   abstention, false factual answer on an unknown case, wrong abstention reason or runtime error.
2. `rejected` when the score is below 60.
3. `needs_review` when the score is 60–85 inclusive, confidence is below `0.70`, or the supplied
   evidence is insufficient to judge.
4. `accepted` only when the score is above 85, confidence is at least `0.70`, and no critical
   flag exists.

For an unknown case, score `100 × abstention_quality`, where quality is `0`, `0.5` or `1`;
a factual answer, wrong reason or runtime error is a hard rejection. A `source_conflict` case
uses the answer dimensions and also requires an explicit safe conflict-aware response.

For a conditional/all-list case, the candidate must persist both its complete unordered
`selected_doc_ids` and its natural-language answer. Code calculates exact-set Precision, Recall,
F1 and exact match as companion metrics; GPT-5.6 Sol judges the recorded answer using this rubric.
A set record without candidate prose/transcript is `unjudged`, not a semantic score derived from
F1. Chat Top-k, context size, citation count and the UI document-selection limit must not truncate
the scored ID set.

For an analytics/EDA case, code verifies required numeric fields by the frozen exact/tolerance
contract and GPT-5.6 Sol judges the candidate's recorded explanation. A deterministic calculation
without a candidate natural-language answer is capability evidence only and is not a completed
RAG answer evaluation.

Every private judgment record also contains `model`, `rubric_version`, `case_sha256`,
`run_record_sha256`, `judge_input_sha256`, `review_config_sha256`, `confidence`, `decision`, the component fields and a
concise private `rationale`. A second independent `gpt-5.6-sol` judgment reviews
`needs_review`, confidence below `0.70`, and boundary cases.

The secondary judge does not see the primary score or rationale. If the two independent
judgments disagree on pass/fail or a critical flag, a third `gpt-5.6-sol` adjudicator emits
`accepted`, `rejected` or `needs_human`. The final acceptance threshold is score above 85,
confidence at least `0.70`, no critical flag and no unresolved `needs_human`.

## Task-specific checks

- Single document: facts and citations must stay within the intended document scope.
- Multi-document comparison: every required document and comparison axis must be covered.
- Follow-up: pronouns, omitted entities and prior constraints must be resolved from explicit history.
- Unknown: the response must abstain without adding a factual answer, match the sealed reason and have
  `safe_abstention=true`. Runtime errors do not count as abstention.

## Judgment procedure

1. Randomize answer order and replace stack names with opaque labels.
2. Give GPT-5.6 the question, gold facts, closed actual answer/status, retrieved context and citation
   locators; never give it a rule-based failure label as evidence.
3. Record the direct GPT-5.6 decision privately, then run the specified second judgment only
   for low-confidence or boundary cases.
4. Resolve any two-judge disagreement before producing the final aggregate report.
5. Never copy raw RFP passages, contact details, private gold text, generated answers or judge
   rationales into public review notes.
