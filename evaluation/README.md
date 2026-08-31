# Evaluation Tooling

This directory contains offline, standard-library-only validation and scoring tools. The tools
do not call model providers, download data or inspect the private corpus unless an explicit
local manifest/block path is supplied to `validate`.

## Private and public files

- Keep real `dev.jsonl`, `heldout.jsonl`, run records and answer-level reports under
  `evaluation/private/` or `artifacts/evaluation/`. Both locations are ignored by Git.
- Commit only schemas, synthetic `*.example.jsonl` templates and reviewed aggregate results.
- Gold evidence stores stable IDs and locator hashes, never raw source quotations.

## Validate

Validate the synthetic examples with a one-case structural floor:

```bash
PYTHONPATH=src python -m midprojectrag.evaluation validate \
  --dev evaluation/templates/dev.example.jsonl \
  --held-out evaluation/templates/heldout.example.jsonl \
  --minimum-per-task 1
```

Validate a real private set against the agreed 40/20 floor and, when available, the private
corpus inventory:

```bash
PYTHONPATH=src python -m midprojectrag.evaluation validate \
  --dev evaluation/private/dev.jsonl \
  --held-out evaluation/private/heldout.jsonl \
  --manifest /private/path/manifest.jsonl \
  --blocks-dir /private/path/blocks \
  --config evaluation/config/metrics.json \
  --output artifacts/evaluation/validation.json
```

`--minimum-per-task` is a synthetic-template escape hatch and cannot be combined with
`--config`. A real config cannot reduce the frozen 10-per-task dev and 5-per-task held-out
floors.

## Score

`score` reads already-produced local run records. It does not generate answers:

```bash
PYTHONPATH=src python -m midprojectrag.evaluation score \
  --cases evaluation/private/dev.jsonl \
  --runs artifacts/evaluation/api-dev-runs.jsonl \
  --config evaluation/config/metrics.json \
  --output artifacts/evaluation/api-dev-metrics.json
```

The `eval_set_sha256` in every run must equal the deterministic hash of the supplied case set.
The run's corpus manifest hash must also equal the hash recorded by its case.
`config_sha256` identifies that stack's retrieval/generation configuration; the score report
separately records the hash of `metrics.json` as `scoring_config_sha256`.
The scoring config is mandatory. Missing, malformed or weakened thresholds fail closed.

## Compare

Only passed reports for one API stack and one GCP-local stack with the same corpus,
evaluation and scoring-config hashes can be compared:

```bash
PYTHONPATH=src python -m midprojectrag.evaluation compare \
  --baseline artifacts/evaluation/api-heldout-metrics.json \
  --candidate artifacts/evaluation/gcp-heldout-metrics.json \
  --output artifacts/evaluation/heldout-comparison.json
```

The comparison reports numeric deltas without claiming a winner. Quality direction, latency,
API cost and GPU cost must be interpreted together in the final report.

## Supplemental provisional baseline (69 cases)

The frozen baseline binds the 56 answer cases and 13 set-retrieval cases to the refined
98-document page index. Human review still controls promotion to official gold; it does not
block a clearly labelled provisional score.

Verify every pinned input and the index without making a provider call. The checked-in
`preflight-receipt.json` records this exact offline verification:

```bash
PYTHONPATH=src python -m midprojectrag.supplemental_baseline --preflight-only
```

Score previously produced local runs without network access:

```bash
PYTHONPATH=src python -m midprojectrag.supplemental_baseline --score-existing
```

Run the frozen OpenAI baseline only after explicitly approving the stated data flow. This
sends the 69 private golden questions and each query's retrieved RFP excerpts to the OpenAI
API, uses the USD 2.00 ledger ceiling in the frozen config, and resumes case by case:

```bash
PYTHONPATH=src python -m midprojectrag.supplemental_baseline \
  --run-openai \
  --approve-private-corpus-egress
```

Questions, answers, run records and per-case metrics remain under ignored private paths. After
a complete run, `baselines/supplemental-provisional-v1/receipt.json` contains only hashes,
counts and aggregate metrics and can be reviewed for Git publication. Preflight and
`--score-existing` are deliberately offline; the provider path is fail-closed unless the
explicit egress flag is present.

## Offline schema registry

`schemas/registry.json` maps every schema `$id` and external `$ref` to a checked-in local file.
Schema validation must use that registry and must never resolve `midprojectrag.local` over the
network.

## Tests

```bash
PYTHONPATH=src python -m unittest discover -s tests/evaluation -v
```
