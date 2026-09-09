# Evo visual runtime integration findings

- Recorded: 2026-09-09T15:04:39+09:00
- live001: visual_search was selected, but child exited with ModuleNotFoundError: torch. CLI had resolved a virtualenv Python symlink into its base interpreter. Fixed by preserving the invoked --visual-python path; no install. Dedicated test first failed then passed.
- live002: real KURE and actual pixels ran successfully, but policy confused the human-review flag with missing user information. One invalid JSON action, then needs_clarification. No final answer was generated.
- Generic guide now distinguishes an allowed qualified interpretation from verified truth. Uncertainty rejection and metadata remain unchanged; live003 answered with1 citation and0 invalid actions.
- Final378 tests passed, all raw failures and candidate versions retained. This is wiring/contract evidence, not Korean recognition accuracy.
- refs: ../../../work/2026-09-09-evo-visual-tools.md.
