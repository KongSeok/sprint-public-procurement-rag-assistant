# Skill: Protocol for Test Execution

## Purpose
Standardize the testing workflow for frontend, backend, integration, and browser checks.

## Usage
Execute this protocol when verifying features, running regression tests, or preparing for deployment.

## Protocol Steps

1.  **Identify Test Scope**
    - Determine if the task involves Frontend, Backend, or End-to-End integration.

2.  **Read Policy Documents**
    - Read `fivecircles/test/testpolicy.md`.
    - Read `fivecircles/test/error-policy.md` when present.
    - Read `fivecircles/work/workpolicy.md`.
    - Read relevant files under `fivecircles/architecture/specs/` when the test scope depends on a contract.
    - Read project-local equivalents when fivecircles policies are absent: `TESTING.md`, `AGENTS.md`, CI workflow files, Playwright notes, package scripts, or build files.

3.  **Create Missing Test Rules Before Broad Testing**
    - If no usable test rule document exists, create a minimal one before running broad validation.
    - Prefer `fivecircles/test/testpolicy.md` when the project has a `fivecircles/` directory; otherwise create `TESTING.md`.
    - If a test command already failed, read the error output first and encode what was learned.
    - Include:
        - working directory
        - test/build/typecheck/lint commands
        - prerequisites and environment variables
        - browser/Playwright or Computer Use expectations
        - known failure patterns or blockers
        - error log location
        - pass/fail/block criteria

4.  **Execute Tests**
    - Prefer existing package scripts and targeted tests for touched surfaces.
    - For browser-visible flows, run Playwright/browser smoke when available.
    - For user-facing changes, reproduce the user's real execution action when tools are available:
        - Use Playwright or browser-use to click, type, navigate, submit forms, and verify visible results.
        - Capture screenshots for important states, visual regressions, or before/after evidence.
        - Use Computer Use when the flow depends on OS dialogs, file upload/download pickers, native apps, or interactions outside the browser.
        - Validate happy path plus relevant empty, loading, error, invalid input, auth/permission, refresh, and responsive viewport states.

5.  **Log Results**
    - **Success**: Update `todolist.md` or `update.md`.
    - **Failure**:
        - Create a log in `fivecircles/test/errorlogs/`.
        - Create a `learn-from-log.md` entry if it's a recurring or structural issue.
    - Include commands run, real-user scenario steps reproduced, screenshot paths or visual observations, and remaining gaps.
