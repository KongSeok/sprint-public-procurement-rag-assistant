# HWP Optional Dependency Test Isolation

- Date: 2026-08-24 19:34 KST
- Stage: Test
- Failure: the missing-HWP-dependency test changed result when pyhwp was installed in `.venv`.
- Fix: mock both executable lookup and package metadata so the test is independent of the host environment.
