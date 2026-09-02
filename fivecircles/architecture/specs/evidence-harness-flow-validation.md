# Evidence-Harness Target / Current
2026-09-02 · RELAY EH1–EH4 · Flow diagram verification: CORE PATH VALIDATED / PROMOTION GAP

[Target](evidence-harness-target-flow.mmd) · [Current](evidence-harness-current-flow.mmd)

| Node/edge | Status | Upstream | Connection | Safety | Validation | Risk | Score | Next |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| evidence → retrieval/bridge | VALIDATED | 4 | 4 | 2 | 3 | -1 | 12 | keep explicit visual mapping |
| search → fusion/rerank | VALIDATED | 3 | 4 | 2 | 3 | -1 | 11 | add real dense/visual providers when pinned |
| plan → state → action → verify loop | VALIDATED | 4 | 4 | 2 | 3 | -1 | 12 | external policy remains optional |
| verified state → retained pack → generator | VALIDATED | 3 | 4 | 2 | 3 | -1 | 11 | run approved provider smoke |
| trained policy / weights / real promotion | GAP | 2 | 2 | 2 | 0 | -3 | 3 | EH5/EH6 preflight |
| visual reader / multimodal embedding | CAPABILITY GAP | 2 | 2 | 3 | 2 | -2 | 7 | provider + pixel fidelity QA |
Score = upstream + connection + safety + validation - risk magnitude. Scores are relay prioritization, not quality metrics.
Green validated local path; blue model/provider; amber local/private/conditional; red unsupported/gap; gray branch.
Current diagram reflects the committed base plus this branch's opt-in implementation; uncommitted original-folder work is not imported.

## Evidence of validation

- New synthetic suites: evidence 40, retrieval 36, answering 39, orchestration 36, offline 24.
- Existing indexing regression: 71 pass. Repository safety: 605 files scanned, PASS.
- Full discovery: 786 run, 776 pass, 8 expected private skips, 2 pre-existing evaluation-tree errors recorded separately.
- Local `/api/tags` confirmed the pinned Mac model name/digest. No private question or gold payload was sent; live synthetic run is pending execution approval.

## Visual gate

`query_type=visual` is forced to `capability_gap` until a verified visual reader is injected. An OCR/caption child,
even when provenance-valid, cannot be treated as pixel evidence. `visual` lane API and bridge can be tested with
synthetic records, but no multimodal embedding quality or score is claimed.
