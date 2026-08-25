# rhwp Container Path Contract

- Date: 2026-08-25
- Stage: strict 100-document `rhwp` production extraction
- Failure: the first strict rerun produced 94 `ok` and 6 `partial` rows because ten nested tables failed container-path validation.
- Root cause: the adapter required a `cell` coordinate on every container-path item. Actual v0.8.4 output uses `paragraph` and `control` for header/footer containers, while only `tableCell` containers include and require `cell`.
- Fix: make `cell` kind-dependent in normalization, runtime verification and JSON Schema; add header-without-cell and nested-table regression coverage.
- Verification: the next two full runs each produced 100 `ok`, 0 `partial`, 0 `failed`; strict primary verification passed and both block/meta directories were byte-for-byte identical.
- Prevention: derive optional structural fields from the version-pinned corpus envelope and preserve kind-specific invariants instead of assuming one coordinate shape for every container.
