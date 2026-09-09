# HOTLINE.2 - hotline-only local runtime migration

## Decision and scope
2026-09-09 user directive recorded as D-025. New local serving development uses the fixed hotline; Controller decision, execution ledger and recursive retained-transition history are removed from the active entrypoint. Controller source/history remain archived, not deleted or marked complete. Existing public retrieval validation remains enabled.

## Delivered
- `src/midprojectrag/hotline.py`: promoted fixed pipeline, default request executor, configurable private input/output paths and finite total-budget CLI.
- `scripts/run_hotline.py` and console entrypoint `midprojectrag-hotline` in pyproject. Console registration requires a later package installation; no dependency install was performed.
- `scripts/run_controller_quick_qa.py`: compatibility shim only. Controller selection rejected before initialization; no legacy four_steps callable exported.
- Standalone CLI owns a worker process group, kills/reaps only that group on timeout or leader exit, and writes a supervisor receipt when an output directory exists. External supervisors may pass a deadline; it cannot expand the local time budget.
- Removed a hard-coded historical Controller-code hash gate from the new entrypoint. Source hashes are still recorded once at run boundaries. No validation stubs, global PASS cache, runtime self-modification, or changes to shared core/store/retriever code.

## Evidence
1. Before migration: existing 16 adapter tests PASS (tool output).
2. Expected RED: new migration test import failed because `midprojectrag.hotline` did not exist. This is an expected missing-module RED, not a dependency failure.
3. After implementation: `tests.test_controller_quick_qa tests.test_hotline_runtime` -> 30 tests, 0.888 seconds, OK, exit0.
4. Shared runtime/retrieval/scope/public-parent regression -> 64 tests, 5.203 seconds, OK, exit0.
5. New tests include complete synthetic worker CLI, answer/citation output, no-overwrite/private permissions, obsolete route rejection, invalid budgets/deadlines, explicit scope/gold rejection, process success/error/timeout, and CLI help.
6. Python call tracing during a successful synthetic request observed zero Controller execution/decision/successor validation entry calls. Dense/lexical/generation each ran once. This is not a claim that all shared API validation disappeared.
7. AST comparison with the saved original: fixed_public_pipeline, parent_context, validate_answer, RecordingOpener and device-probe helper unchanged. Ranking/model selection/context policy are not retuned in this migration.

Commands use `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m unittest -q ...` from the actual project root. Raw post-change logs are in the Git-ignored `resources/data_refined/private/diagnostics/hotline-migration-20260909-001/` directory. Tests contain synthetic data only; old private questions/answers/runs are untouched.

## Remaining boundaries
This is a narrow runtime promotion, not full product completion. Current hotline still uses the existing fact-only single-parent context and Mac MPS/Ollama model. Compare/follow-up/multiple evidence, long-lived runtime reuse, application facade/Streamlit and GCP provider integration remain HOTLINE.3/4. Public API checks may still be expensive; this migration does not claim a new measured speedup or semantic-quality PASS.

No real-model/API/GPU/VM run, frozen Mini131 rerun, package installation, corpus/index edit, UI change, branch switch, commit or push. Full regression and independent review were not performed; focused/shared regression must not be presented as those gates. Existing dirty changes and ongoing work are preserved.

## Status
IMPLEMENTED_AND_SCOPED_TESTED. D-025 is architecture direction, not an A/B winner. Integration/publication remains unperformed. Static/diff/repository-safety checks are recorded below after execution.

## Final checks - 2026-09-09T11:48:48+09:00
- Five changed Python files parsed successfully; module/new CLI help passed. Scoped git diff --check passed.
- Full repository safety: FAIL / PII_PATTERN_FOUND. Four existing collaboration JSON files matched; none was edited by this batch and no current batch file matched. Three match in HEAD too; one is a pre-existing untracked QUICKQA.1 report. Matching contents were not printed. Pattern matches are not proof of genuine PII.
- Historical records and the scanner were not modified to manufacture a PASS. No publication/commit/push. This is a repository publication blocker, not a failed hotline functional test.
- HEAD remains fc03a4e; execution_contracts.py and retrieval/fusion.py have no working-tree diff.
- A final documentation command exceeded the connector's 4000-character schema limit and was rejected before execution. It was replaced with this staged script; no repository changes occurred from the rejected call.

## Feature branch publication preparation - 2026-09-09T11:56:03+09:00

- User explicitly requested a new hotline branch and push. Target: `origin/feat/hotline-runtime`; base: `fc03a4e`. A separate `MidProjectRAG-hotline` worktree leaves the existing integration checkout and index untouched.
- Only the six hotline runtime/launcher/test/package files and this migration's governance/log additions are included. Other uncommitted source, retrieval optimizations, application/UI, notebooks, private data and VM/evaluation work are excluded. Historical committed Controller source stays in the base; no Controller execution is re-enabled.
- D-025 restates the preserved comparison/semantic-quality obligations directly so this branch does not depend on uncommitted D-022/D-024 sections in the source checkout. No product requirement is relaxed.
- Exact isolated candidate: focused30 PASS (0.991s), shared82 PASS (4.205s), fusion35 PASS (2.123s): 147 tests, no failures/errors/skips. Nine runtime import checks resolve inside this new checkout; CLI help and syntax/diff checks pass. These results supersede neither the earlier 94-test source-checkout evidence nor unrelated full-suite gates.
- Tests use `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src` and the existing project virtualenv interpreter from the separate worktree. Modules: `tests.test_controller_quick_qa`, `tests.test_hotline_runtime`, `tests.test_runtime_integrity`, `tests.test_retrieval_obligations`, `tests.test_action_effect_receipts`, `tests.test_semantic_verification`, `tests.test_e0_fusion`, `tests.test_child_fusion`.
- No real model, external API, corpus/index rebuild, UI smoke, full suite or independent model review is claimed. This is user-requested feature-branch publication, not final product/quality acceptance or deployment.

### Publication safety classification

The unmodified repository scanner still returns `PII_PATTERN_FOUND` / exit1. The three candidate-tree hits are phone-shaped digit substrings inside complete 64-character hexadecimal JSON SHA-256 fields, not phone/contact fields. The source checkout's fourth hit belongs to an unrelated untracked report and is not included.

| Existing file suffix | JSON field | Classification |
| --- | --- | --- |
| `batches/EH2.6.c4.2.b.2/candidate.json` | `artifacts.untracked_diff.sha256` | Exact SHA-256 value |
| `messages/EH2.6.c4.2.b.2/002-first-fuse-state-implementation-report-1.json` | `body.candidate_manifest.new_test_diff_sha256` | Exact SHA-256 value |
| `messages/QUICKQA.2/002-combined-implementation-report.json` | `body.evidence_files[22].sha256` | Exact SHA-256 value |

A separate content review scans the complete candidate tree and incoming ancestor blobs for restricted paths, secret patterns and the same PII pattern. Every classified exception requires a parsed JSON field ending in `sha256`, an exact full 64-hex value, and the raw match to be inside that string token. All other matches remain blocking. Result: zero unresolved hits; classified hash false positives only. No checker, archived record, hash value or runtime validation is changed. This is a reviewed false-positive clearance, not a claim that the original scanner returned PASS.

Raw test logs and the content-audit manifest are retained outside the published worktree. Actual commit/push acknowledgement and local/remote hash equality are checked after this record is committed; no future push result is prefilled here.
