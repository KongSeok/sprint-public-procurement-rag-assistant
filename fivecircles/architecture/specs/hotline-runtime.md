# Hotline local runtime - HOTLINE.2

## Goal and authority
D-025 / user direction 2026-09-09: use the fixed hotline rather than expanding recursive Controller machinery. This contract changes the serving entrypoint, not the public retrieval invariants.

## Implementation
- Extract the existing verified fixed path and local helpers into `src/midprojectrag/hotline.py`.
- Export a callable request executor and `python -m midprojectrag.hotline`. Add a console entrypoint and a thin `scripts/run_hotline.py` launcher.
- The old quick-QA launcher delegates to the same module. Its `--path` accepts only `hotline`; `controller` fails before any initialization or model call. Do not retain a callable four-step Controller implementation in the new module.
- Keep existing public lane/fusion/parent APIs and their checks. No Controller execution/decision/claim/ledger/retained-transition API on the active path. Shared low-level code may still be imported.
- Remove dependency on a hard-coded historical Controller source SHA. Record relevant source hashes once before/after a run; do not scan them on every action.
- Keep bounded private JSON input/output, no overwrite, strict answer/citation shape, at-most-one generation POST and no automatic retry.
- CLI defaults to a 120-second total budget with an owned-process-group supervisor. Existing external supervisors may provide a finite monotonic deadline; it must not exceed the local budget. Model transport and stage deadlines remain enforced. No shared model service is terminated.

## Scope and non-goals
Initial scope is the existing fact query with one selected parent window. Do not redesign ranking, token packing, provider/device selection, retrieval state, or corpus artifacts in this migration. The old Controller implementation, diagnostics and historical tests are retained for reference only. Streamlit, GCP/Qwen VM runs and frozen Mini131 outputs are not modified or rerun. This is not learned EvoHarness policy or a semantic verifier.

## Acceptance
1. Existing source/scope/citation, provider failure, empty result, privacy and budget checks pass.
2. Hotline is the sole CLI path and the default callable path; migration wrapper and installed entrypoint agree.
3. A synthetic full request reaches actual public retrieval/parent APIs and the answer adapter with dense/lexical/generator each once; Controller execution functions are never called.
4. Expired/nonfinite/oversized budgets and obsolete Controller selection fail before model initialization.
5. Standalone process timeout stops only its owned worker group, records timeout without claiming an answer and leaves shared Ollama intact.
6. Source checks and logs distinguish implementation tests from actual private model latency/quality; no fake independent review or full-suite PASS.

## Validation and rollback
Use project `.venv/bin/python`, `PYTHONPATH=src`, `PYTHONDONTWRITEBYTECODE=1`. Run focused existing and new regression plus model-free CLI and supervisor smoke. Preserve before-images and review exact changes; leave commit/push to a separately validated integration boundary. Local serving migration can be rolled back independently of corpus, baselines and Controller source.
