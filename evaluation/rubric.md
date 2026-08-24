# Human Evaluation Rubric

## Purpose

Automated retrieval and contract metrics do not reliably judge Korean RFP summaries and
multi-document comparisons. Reviewers therefore assign the normalized fields in each
private run record. Stack names must be hidden while held-out answers are reviewed.

## Scored fields

Use only `0`, `0.5`, or `1` unless the team records a stricter pre-agreed rubric.

### `correctness`

- `1`: all required key points are materially correct and no material contradiction exists.
- `0.5`: the main conclusion is correct but a required point is incomplete or imprecise.
- `0`: the conclusion is wrong, reverses a comparison, or invents a material fact.

### `faithfulness`

- `1`: every material factual statement is supported by the cited source blocks.
- `0.5`: the answer is mostly supported but includes a minor unsupported statement.
- `0`: a material claim is unsupported or contradicts the cited evidence.

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

## Task-specific checks

- Single document: facts and citations must stay within the intended document scope.
- Multi-document comparison: every required document and comparison axis must be covered.
- Follow-up: pronouns, omitted entities and prior constraints must be resolved from explicit history.
- Unknown: the response must abstain without adding a factual answer, match the sealed reason and have
  `safe_abstention=true`. Runtime errors do not count as abstention.

## Review procedure

1. Randomize answer order and replace stack names with opaque labels.
2. Two team members independently score every held-out response, including abstentions.
3. Resolve disagreements before producing the final aggregate report.
4. Never copy raw RFP passages, contact details or private gold text into public review notes.
