# MidProjectRAG Implementation Rules

## Reproducibility

- Every run records code revision when available, corpus/eval/config hashes, model identifiers and seed.
- Runtime behavior comes from versioned configuration, not hidden notebook state.
- IDs and file joins are deterministic across machines.

## Data Safety

- Runtime paths are injected; do not hard-code the user's Drive or private data path in application code.
- Importing a module must not download data, call a model API or build an index.
- Logs contain IDs, counts, timings and error codes only.
- Extraction failure is data, not an exception to silently skip.

## Architecture

- Keep ingestion, retrieval, generation and evaluation provider-independent.
- Provider adapters must implement the shared request/response contracts.
- Source blocks remain stable while chunking strategies vary.
- Add one retrieval improvement per ablation so cause and cost remain measurable.

## Testing

- Unit tests use synthetic fixtures only.
- Private corpus integration tests are opt-in through an environment variable and never run in public CI.
- Schema, split leakage, citation resolution, budget and safety gates fail closed.
