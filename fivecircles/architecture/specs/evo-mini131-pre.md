# EvoHarness Mini131 PRE Contract

Contract ID: `evo35-mini131-pre-v1`
Date: 2026-09-09
Candidate freeze: `52c2e24ba59c23653617cf04cab6e070d98ec646`
Authority: D-029 / EVO35.3c / explicit solo relay-shot.

## 1. Goal

Measure the untrained prompt-time Qwen3.5 EvoHarness at the frozen PRE candidate before non-golden trajectory collection or training. Mini131 remains a historical benchmark, not a new sealed holdout and not a curriculum source.

## 2. Source and runtime isolation

- Read Mini131 inventory/questions/gold only from the existing original checkout; do not write there.
- Clone required private runtime artifacts into the hotline ignored diagnostics tree using copy-on-write. Record source/snapshot hashes.
- Set the cloned HF cache before importing Transformers/SentenceTransformers; no downloads or egress.
- Retrieval executes in the established project venv (KURE/MPS + Kiwi). Qwen3.5 runs in a persistent child process using the existing MLX venv. Do not install either environment into the other.
- The Qwen worker loads once per batch and serves token-count plus structured policy/final completions. Parent deadlines remain authoritative.

## 3. Inventory / support matrix

The 131 assets remain in the denominator and are reported by lane.

| Lane | Count | PRE treatment |
| --- | ---: | --- |
| core40 | 40 | Current text EvoHarness. 30 direct; 10 follow-up use a separately reported end-to-end prior-turn replay because the historical fixed history has cited document IDs but no current-runtime evidence IDs. |
| supplemental answer | 56 | Current text EvoHarness directly. |
| supplemental exhaustive set | 13 | `unsupported_specialist`: no exhaustive-set/catalog operator in the current policy toolset. |
| visual | 10 | `unsupported_specialist`: current persisted OCR/VLM index is only one document/one occurrence and is not a valid Mini131 visual-10 corpus. |
| corpus analytics | 10 | `unsupported_specialist`: no deterministic analytics tool in current EvoHarness. |
| parser regression | 2 | Report separately as ETL, never blend into RAG semantic mean. Execute only from an isolated snapshot; otherwise explicitly NOT_RUN. |

Unsupported items are never silently removed or scored as successful abstentions.

## 4. Follow-up evaluation mode

Mini131 fixed-history follow-up turns do not contain current-runtime `cited_evidence_ids`, while D-029 intentionally requires them. The PRE adapter must not fabricate canonical evidence IDs from gold/qrels.

For each of the ten follow-up cases:
1. replay the fixed prior user question with the same explicit document scope through the frozen candidate;
2. use only that candidate's actual prior answer/cited IDs as the assistant history turn;
3. execute the golden follow-up question with `follow_up=true`;
4. label the result `end_to_end_followup`, separate from the historical fixed-history score.

If the prior turn fails, the follow-up is a runtime failure, not a gold-assisted repair.

## 5. Metrics

Without semantic-judge completion, publish only objective/operational aggregates:
- attempted/supported/unsupported counts by lane;
- terminal status counts, timeout/error/invalid-action rates;
- gold decision match (answer vs abstain) where the case contract defines it;
- required-document citation recall and all-required-docs-cited rate;
- retrieved required-document coverage from recorded search observations;
- policy/search/read/answer calls and token counts;
- p50/p95/mean worker/episode latency.

Answer semantic correctness remains `unjudged` until the fixed GPT-5.6 Sol blind-judge contract is applied. Do not replace it with lexical similarity or Qwen self-judgment.

## 6. Leakage / inspection boundary

- Raw questions, gold, candidate answers, trajectories and per-case metrics remain private/ignored.
- Public files may contain only hashes, lane counts, aggregate metrics and limitations.
- After PRE completion, the relay may inspect aggregate results and execution/system failures needed to validate the runner. It must not inspect individual wrong answers or gold differences to choose training examples, prompts, rewards or experience notes.
- The full Mini131 exclusion manifest remains active for subsequent non-golden data collection.

## 7. Acceptance

EVO35.3c is complete when:
1. candidate commit and source/snapshot hashes are frozen;
2. current text runner preflight demonstrates real KURE/MPS search and persistent Qwen3.5 structured generation with no egress;
3. all 131 assets receive an explicit terminal classification (`executed`, `unsupported_specialist`, or separate ETL status);
4. supported text cases finish or record real runtime terminal failures without retrying from gold;
5. private per-case output and an aggregate PRE receipt are written atomically;
6. impact tests and runner tests pass, self-review and publication safety complete;
7. aggregate PRE is committed/pushed before EVO35.3d data collection begins.
