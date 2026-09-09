# HOTLINE.VISUAL.1 - Merge existing OCR / visual retrieval / VLM

Date: 2026-09-09. Execution: solo; no delegated agents.

## User scope and fixed endpoints

User asked to bring the VLM branch's OCR, VLM and retrieval integration into the active hotline branch.
Target: `feat/hotline-runtime` at `c91f099` (initially clean).
Source: `origin/feat/vlm-visual-retrieval` at `88a9e62c907a11c6fefb226401c0c15c81c562c1`, equal to its clean local worktree.
Common base: `7ad229f8c85fb48ebb1c53f4424db4a224b562a7`.

## Plan and boundaries

1. Merge all four source commits with a non-fast-forward merge, retaining source history, not a copy of selected filenames without ancestry.
2. Resolve TODO and learn-from-log conflicts by keeping both sides' unique history; latest hotline/Evo direction remains authoritative. No product-source conflict was found in merge-tree simulation.
3. Preserve hotline and Evo Qwen3.5 policy code, the seven-action contract, original source/model worktrees and private assets. The imported VLM uses the same pinned Qwen3.5-9B-4bit family.
4. Keep OCR/layout text retrieval separate from pixel VLM inference. Retain verified crop provenance, uncertainty/abstention and human-review/nonpromotion flags.
5. Run imported OCR/index/VLM and neighboring visual tests, then the existing 212 hotline/Evo/runtime regressions in the same checkout and process where practical. Add integration coverage for coexistence/entrypoints if needed.
6. Verify CLI/import usability, privacy boundaries and exact merge scope. Record self-review in debate and the review folder; no independent-review claim. Commit and push the merge to the previously authorized hotline branch after valid checks.

## In scope

Pinned local OCR runtime/manifests and optional dependencies; persist/reload/search of KURE OCR/layout vectors; top-hit crop into local MLX VLM with structured answer and application-generated citations; public code, tests, contracts, redacted history and operating docs.

## Not implied by this merge

The existing visual CLI/API becomes available in the hotline checkout. This merge does not silently add policy actions, auto-enable visual routing in every text search, alter the default Streamlit bundle, convert VLM interpretation into verified source evidence, solve the known Evo follow-up failure, or claim trained SFT/GRPO performance. A new automatic multimodal policy route requires an explicit tool contract and support tests, rather than being asserted from a Git merge.

No raw documents, crops, weights, vectors, model responses or private evaluation material are copied or committed. No real OCR/VLM inference, downloads, environment upgrades, re-embedding, VM changes or corpus modifications are needed for this code-integration batch. Existing source smoke results remain historical and are not relabelled as a new live test.

## Acceptance

- The source tip is an ancestor of the final hotline merge; both source/target changes survive without conflict markers.
- Imported visual contracts/tests pass on the actual merged candidate; existing hotline/Evo selected tests pass and original core source hashes remain unchanged.
- Both text-only and visual CLI help/import paths work without loading models; OCR persistence -> search -> verified crop -> QA result is tested with explicitly synthetic providers/workers.
- Privacy scanner results and classified pre-existing hash false positives are disclosed; no private tree is in the index.
- New work and review records state the distinction between branch integration, explicit visual APIs and not-yet-wired automatic policy selection.

## Initial audit

Incoming commits: 5c732eb (OCR/runtime and local-first contract), a93af22 (persisted OCR embeddings), 0fd4932 (verification/publication record), 88a9e62 (retrieved image VLM QA). 31 incoming changed paths; only TODO and learn-from-log conflict. Existing failures/readiness under EVO35.2.FOLLOWUP remain unchanged.

Status: MERGE_PLANNED. Results and exact publication receipt follow actual execution.

## Merge operation
- Performed `git merge --no-commit --no-ff origin/feat/vlm-visual-retrieval`. Expected content conflicts were limited to2 documentation files/3 conflict blocks. Preserved both sides, retaining the current hotline/Evo queue and adding explicit historical labels. No product code conflict or automatic behavior switch.

## Implemented merge and executable surfaces

All31 incoming changed paths are included, plus target-side integration documentation and one coexistence test module. No automatic cross-modal action or router was invented as part of a Git merge.

| Layer | Imported module / configuration | Purpose |
|---|---|---|
| Local OCR | ingest/paddle_ocr_runtime.py, visual_model_manifest.py, configs/visual/ppocrv5-cpu-minimal.json | Pinned OCR-only CPU detection/recognition, no table/semantic inference claim |
| OCR retrieval | indexing/visual_ocr_index.py | KURE OCR/layout vectors, private build/load/search, occurrence dedup and exact crop provenance |
| Image answer | stacks/local/visual_qa.py | Top-hit original PNG -> pinned Qwen3.5 MLX image input -> structured interpretation/application citation |
| Baselines | hotline.py and evo_harness/* unchanged | Existing fixed hotline and Qwen3.5 policy continue without old recursive Controller |

The source code's actual VLM is `mlx-community/Qwen3.5-9B-4bit`, revision8b2b98c00a6b4d291155e4890773ca8f769aee53. OCR indexing embeds recognized text, not image pixels. VLM sees image pixels, not a substituted OCR-only prompt. Original source branch's label-read successes and relation hallucination risks remain historical evidence, not this merge's new model results.

```text
existing text hotline / Evo policy (unchanged)

explicit visual preparation: image crop -> local OCR/layout -> KURE vector index
explicit visual question: query -> OCR-vector search -> top-hit PNG -> Qwen3.5 VLM
                        -> cited visual_inference / uncertainty abstention
```

## Final regression and smoke

Combined30-module selection: **352 tests**,352 unique IDs, failures0/errors0/skip0, 8.882s, exit0. This includes original212 hotline/Evo/core checks, imported visual53, new coexistence4 and neighboring visual/KURE83. It is impact-based regression, not the entire repository suite or a quality benchmark.

The separate initial53 visual tests and4 coexistence tests were repeated inside the final352 and are not counted again. First external test-harness attempt loaded30 error placeholders because tests/ was absent from sys.path. The corrected command includes the verified source tree and repository root; no product assertions or dependencies were changed to pass.

Runtime: established project Python3.12.14, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH="$PWD/src:$PWD"` from the hotline root. Exact selected module list and unique test IDs are in ignored merged-tests-summary.json/merged-test-ids.txt. Four CLI help paths work without model loads: hotline, evo_harness.cli, visual_ocr_index and visual_qa.

New same-process tests execute persisted OCR index build/load/search -> verified image selection -> fake isolated VLM worker -> actual output/citation adapter and an Evo text episode in both orders. They confirm zero retired Controller execution/decision/history-reader calls, image interpretation remains unreviewed/nonpromoted and separate evidence objects cannot contaminate the text result.

Chrome via Puppeteer: desktop1280/mobile390 synthetic preview PASS. Embedded fixture PNG1x1 decoded, synthetic answer visible, no horizontal overflow, page errors or network requests. This is a new synthetic HTML rendering check, not a retry around historical private-browser restrictions and not an image OCR accuracy test. The product Streamlit UI was not changed.

## Known boundaries

- The visual index uses its source API and standalone `build|search|answer` CLI. Existing seven-action Evo policy does not automatically select it after a branch merge.
- Automatic policy tool integration must explicitly add hard document-scope filtering and propagate episode time budgets. Source visual QA's180-second child limit is not equivalent to the existing120-second Evo budget.
- Private OCR weights, indexes, images and model environments remain at their existing external locations. Merging source does not provision a new `.venv-ocr` or copy artifacts into this worktree.
- No new OCR, KURE query embedding, VLM inference, private RFP/golden131 run, model download, environment upgrade or SFT/GRPO was executed.
- Existing EVO35.2.FOLLOWUP failure/REPLAN remains; importing visual code does not fix it or mark learned policy complete.

## Review and publication

Self-review: `review/review-hotline-vlm-integration-2026-09-09.md`. Approved branch integration with the explicit limitations above, not an independent Critic or full-product-quality PASS.

Expected final merge has c91f099 and88a9e62 as parents. Actual final SHA/remote equality/clean worktree and source-worktree preservation are recorded only after commit and push in a private publication receipt. Native logs, initial failure, synthetic preview and before-source hashes stay under ignored `resources/data_refined/private/diagnostics/hotline-vlm-merge-20260909-001/`.

Status: MERGED_AND_SCOPED_TESTED_PENDING_PUBLICATION.

### Publication content check
- Stock safety remains FAIL/PII_PATTERN_FOUND on three pre-existing exact SHA-256 JSON values; the existing read-only classifier identified only numeric substrings in those digest fields. Unresolved sensitive-path/secret/PII findings0.
- The merge imports the source branch's stricter rule excluding ALL resources/**, not a scanner relaxation. No rule was changed to suppress the historical SHA false positives and no historical digest record was altered.
- Source code, image contracts and tests were reviewed in solo mode. Raw model/data assets are not in the index; the source VLM worktree remains clean at88a9e62.
