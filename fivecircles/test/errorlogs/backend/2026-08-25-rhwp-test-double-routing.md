# rhwp Test-double Routing

- Date: 2026-08-25 09:19 KST
- Stage: `rhwp` primary adapter regression tests
- Failure: two legacy fallback tests exhausted their mocked subprocess results after the new primary-command lookup reused a broad `shutil.which` mock.
- Root cause: the tests mocked all executable discovery with one return value, so an HWP5 path was incorrectly presented as the `rhwp` command and consumed an extra subprocess result.
- Fix: mock `resolve_rhwp_command` independently in legacy-path tests and add explicit primary-success, table-partial and primary-failure fallback tests.
- Prevention: each parser stage owns a distinct discovery seam; tests must mock the complete ordered chain rather than a shared optional-dependency signal.
