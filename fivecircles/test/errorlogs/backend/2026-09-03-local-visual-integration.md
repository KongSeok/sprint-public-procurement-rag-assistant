# Local visual integration validation corrections

- Timestamp: 2026-09-03 12:46 KST
- Scope: clean local integration worktree; no private source copied and no live model calls.

## Issues / fixes

- Initial full discovery failed at Mini131 class setup: ignored private artifacts were absent.
  Made suite loading lazy so only the nine artifact-dependent tests skip; six synthetic tests still run.
  Missing/corrupt artifacts in an existing private root still fail verification; no hash checks relaxed.
- Composition first lived under answering/, violating the existing provider-neutral core import test.
  Moved it to top-level local_application.py; left the boundary assertion unchanged.
- New test fixtures initially used retrieval_records instead of PipelineResult.retrieval and supplied
  a plan instead of vLLM models/chat envelopes. Corrected fixtures against existing adapter contracts.

## Verification / recurrence prevention

- Focused pipeline/provider/OCR/safety suite 82/82 passed before final location cleanup.
- Final full discovery: 680 discovered, 658 passed, 22 explicitly skipped; no errors/failures.
- Keep provider composition outside answering/indexing. Load private test fixtures only in tests that
  consume them. Rerun full discovery on the final tree, not just targeted tests or a dirty source tree.
