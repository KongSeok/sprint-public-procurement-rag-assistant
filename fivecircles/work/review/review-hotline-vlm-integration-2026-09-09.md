# HOTLINE.VISUAL.1 merge review

Recorded: 2026-09-09T14:32:43+09:00. Reviewer: same assistant in explicitly selected solo mode; no independent Critic.

## Scope

Merge origin/feat/vlm-visual-retrieval88a9e62 into feat/hotline-runtime c91f099. Read incoming OCR runtime/manifests/scripts, persisted visual index, image QA, changed visual config validation, imported tests and operating contracts. Preserve all four source commits and existing target work.

## Findings and decisions

1. Product code merged without conflict. TODO and learn-from-log had3 blocks across2 files; both histories retained. D-027 makes source branch-local task instructions historical on this target.
2. Source OCR/layout text search is not pixel embedding. VLM reads a verified top-hit PNG and returns an explicitly unreviewed interpretation; uncertainty still produces abstention. No model inference text is inserted into source truth or the index.
3. Source uses the same Qwen3.5-9B MLX derivative/revision as the new Evo profile. Historical fixed hotline model and Evo sources are unchanged.
4. Visual retrieval has a separate query API/CLI, not an Evo tool. It has no hard document-scope argument and its VLM child has a180-second timeout. Therefore it must NOT be silently attached to a120-second scoped Evo episode. Separate future visual-tool routing must carry scope/budget; this merge makes no such integration claim.
5. Model/runtime environments and corpus assets are private and not Git content. Separate OCR/KURE/MLX environments stay external and are not installed or copied by this merge.
6. New coexistence tests run visual QA then Evo, Evo then visual abstention, profile compatibility and four CLI help entrypoints. OCR persistence/search/QA uses synthetic providers and a fake worker; no new real-model result is claimed.
7. First combined-test harness had an import-path error, not product failures. An externally staged Python script needed both source and repository root on PYTHONPATH; original30 loader errors were preserved, then352 real unique tests passed.

## Evidence

- Final same-process combined selection:352 tests,352 unique IDs, failures0/errors0/skips0, 8.882s, exit0. Imported visual53 and new coexistence4 are included, not added again to this count.
- Synthetic HTML preview on Chrome/Puppeteer desktop1280 and mobile390: one embedded fixture PNG1x1 loaded, answer visible, overflow0/page errors0/network requests0. This verifies rendering/wiring, not readable-image quality or the older private-source HTML.
- Hotline/Evo/Controller source hashes match the before-image. Imported main modules equal the source branch tip byte for byte. Original VLM worktree clean and unchanged.
- Publication content audit is recorded after final docs; stock scanner and false-positive classification remain distinct. No raw evidence/model files are staged.

## Decision

**APPROVE_WITH_SCOPE_LIMITS for branch merge**, self-review only. Existing explicit OCR search/image-answer path and code/tests are integrated. Automatic Evo visual actions, default UI activation, production corpus quality and known follow-up repair remain separate work. Final commit/push acknowledgement is an actual post-operation receipt, not assumed here.
