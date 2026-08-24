---
name: test-execution
description: Execute tests per test policy using standardized commands, environment, and real-user workflow validation. Use when the user says "테스트 실행", "test exec", asks for browser/GUI verification, or after code changes.
---

# Test Execution

This skill runs tests according to project test policies.

## When to Use

- After code changes
- When the user says "테스트 실행" or "test exec"
- When the user asks to verify user-facing behavior, browser flows, screenshots, or desktop interactions
- Before deployment

## Test Flow

1. Read project test policies when present:
   - `fivecircles/architecture/specs/test-server-policy-4C.md`
   - `fivecircles/architecture/specs/test-front-policy-4c.md`
2. Execute the relevant automated test commands from the project policy or package scripts.
3. For user-facing changes, add a real-user validation pass:
   - Start the app in the same way a user or reviewer would.
   - Use Playwright or the browser-use plugin to click, type, navigate, submit forms, and inspect visible UI states.
   - Capture screenshots for important states, regressions, visual layout checks, or before/after evidence.
   - Use Computer Use when the workflow depends on desktop-app behavior, OS dialogs, uploads/downloads, native menus, or interactions outside the browser.
   - Reproduce the user's reported action sequence as literally as possible before inventing narrower technical checks.
4. Check implementation completeness from the user's point of view:
   - Confirm the main happy path works end to end.
   - Exercise likely edge states: empty data, invalid input, loading, error, permission/auth, refresh, and mobile/desktop viewport differences when relevant.
   - Verify that text, controls, focus, scrolling, overlays, and responsive layout do not block the task.
5. If failures appear, fix the implementation and rerun the smallest reliable automated and real-user checks that cover the change.
6. Document failures in `test/errorlogs/` when that directory or project policy exists.
7. Update test results with:
   - Commands run and outcomes.
   - Real-user scenario steps reproduced.
   - Screenshot paths or browser/Computer Use observations.
   - Remaining gaps or checks that could not be run.

If a referenced policy file is missing, continue with the repository's available scripts and note the missing policy in the final result.
