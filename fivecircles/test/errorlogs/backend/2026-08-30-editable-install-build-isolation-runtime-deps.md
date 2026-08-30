# Editable install build-isolation dependency failure

- Date: 2026-08-30
- Status: RESOLVED
- Impact: the visual recovery runtime could not be prepared through an editable project install, delaying
  local PDF fidelity checks without changing the source tree or private corpus.

## Symptom

The first editable-install attempt failed while build isolation tried to resolve build requirements through
the restricted network. A no-build-isolation retry then failed on the available setuptools/build backend
combination. Sanitized evidence contained only dependency and failure classes.

## Root cause

The editable install coupled runtime-library preparation to build-environment provisioning. That path
required network/build tooling not guaranteed by the controlled local environment, although the required
runtime packages could be installed independently.

## Resolution

- Stopped retrying the editable build path.
- Installed only the explicitly pinned runtime dependencies needed by the PDF recovery lane.
- Kept the dependency constraints in the project configuration so the tested runtime remains reproducible.

## Verification

- The pinned PDF/runtime libraries imported successfully in the project virtual environment.
- Focused PDF visual tests passed using those installed versions.
- No private document was uploaded and no secret or private path was printed.

## Prevention

- Separate project build/install validation from optional runtime dependency provisioning.
- Pin visual-fidelity dependencies and record their versions in generated metadata.
- If build isolation fails, diagnose network and backend compatibility independently; do not broaden or
  repeatedly bypass the controlled environment.
