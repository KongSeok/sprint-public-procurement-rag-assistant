# Missing pypdf Test Runtime

- Date: 2026-08-24 18:12 KST
- Stage: Test
- Failing test: `test_textless_pdf_is_explicitly_rejected`
- Error message: `ModuleNotFoundError: pypdf` under the bare Homebrew Python 3.11 runtime.
- Root cause guess: project dependencies were declared but not installed in that interpreter.
- Fix summary: reran with the bundled Python 3.12 runtime containing declared `pypdf` 6.10.0.
- Pass evidence: full suite 53/53 passed; no package download or environment mutation used.
