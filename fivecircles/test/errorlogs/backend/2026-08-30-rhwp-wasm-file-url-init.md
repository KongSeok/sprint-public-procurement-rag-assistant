# @rhwp/core WASM file-URL initialization failure

- Date: 2026-08-30
- Status: RESOLVED
- Impact: the first local HWP helper probe could not initialize the parser, so no page/control/image
  structure could be inspected through that invocation.

## Symptom

Passing a local `file:` URL to the Node runtime caused the parser's fetch-based WASM initialization to
fail. The sanitized error showed an unsupported local-fetch path; it did not contain a private document
name, document text, or credential.

## Root cause

The Node fetch implementation used by the package initialization path does not provide the same local
`file:` loading behavior as a browser-hosted URL. The parser needed verified module bytes rather than a
filesystem URL.

## Resolution

- Read the pinned WASM artifact locally as bytes.
- Verified its expected digest before initialization.
- Passed the verified `Uint8Array` to `@rhwp/core` and kept document bytes local as well.

## Verification

- The byte-based initialization completed and exposed page, layer, control-layout, and source-image APIs.
- Representative structural probes completed without corpus egress.
- The helper contract now requires explicit package/WASM identity rather than an unverified URL.

## Prevention

- Initialize Node-hosted WASM from digest-verified bytes when local URL fetching is not guaranteed.
- Fail closed on package or WASM identity mismatch.
- Cover URL rejection and byte-based initialization with helper-level tests that use synthetic fixtures.
