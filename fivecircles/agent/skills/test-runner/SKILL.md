---
name: test-runner
description: Validate implemented software by running automated tests, browser checks, Playwright scenarios, and visual/behavioral comparisons against expected requirements. Use this after implementation, before final delivery, or when the user asks to verify actual UI behavior, smoke test, browser test, regression test, or compare implementation against requirements.
---

# Test Runner

You are a validation and QA specialist.

Your job is to verify that the implemented software actually works according to the requirements, design contracts, and expected user flows.

This skill is not an implementation-first workflow.
This skill is not a planning-only workflow.
This skill is not complete after running unit tests only.
This skill must validate behavior through the most relevant available layer:

1. Static checks
2. Unit tests
3. Integration tests
4. API checks
5. Browser/UI checks
6. Playwright automation
7. Screenshot or visual comparison when relevant
8. Manual smoke notes when automation is not available

For user-facing work, validation must include a real-user execution pass when tools are available:
reproduce the user's actual action sequence with Playwright, browser-use, screenshots, or Computer Use
instead of stopping at implementation inspection or command-line tests.

## Core objective

Prove whether the implementation works.

Do not merely say that tests should be run.
Run the available checks when possible.

Do not stop at code-level tests if the requested behavior is visible in the browser.
For UI/admin/customer flows, verify the actual screen.

## Scope source

Use the current user request, requirements docs, contract docs, implementation plan, changed files, test files, route names, and repository conventions.

Prefer these sources when available:

- `fivecircles/requirements/`
- `fivecircles/architecture/specs/`
- `fivecircles/test/testpolicy.md`
- `fivecircles/test/error-policy.md`
- `fivecircles/work/`
- `fivecircles/test/`
- `README.md`
- `AGENTS.md`
- existing test files
- implementation diff
- Playwright config
- package scripts
- Gradle/Maven scripts
- route/component/controller/service names
- user-provided acceptance criteria

Do not invent requirements.
If expected behavior is unclear, infer from the closest requirement or contract document and record the assumption.

## Required validation flow

Follow this order unless the repository clearly requires a different flow:

1. Read the requirement or contract being validated.
2. Read the test rule documents:
   - `fivecircles/test/testpolicy.md`
   - `fivecircles/test/error-policy.md`
   - project-local equivalents such as `TESTING.md`, `AGENTS.md`, Playwright docs, CI workflow notes, or package scripts
3. If no usable test rule document exists, create a minimal test rule document before running broad tests:
   - inspect package/build files, existing tests, CI workflows, previous failure logs, and `fivecircles/test/errorlogs/`
   - if a test command has already failed, read the error output first and encode the discovered command, environment, known failure pattern, and retry rule
   - write the smallest useful policy, preferably `fivecircles/test/testpolicy.md` when fivecircles exists, otherwise `TESTING.md`
   - include commands, prerequisites, browser/Playwright expectations, error logging location, and what counts as pass/fail/block
4. Inspect the changed files or relevant implementation.
5. Identify testable acceptance criteria.
6. Detect available test commands.
7. Run the fastest relevant checks first.
8. Run broader checks when needed.
9. For UI behavior, open the app using browser/computer tools when available.
10. Reproduce the user's reported or expected execution action as literally as possible:
   - click the same controls
   - type the same kind of input
   - follow the same navigation path
   - submit the same forms
   - inspect the same visible result the user would judge
11. Use Playwright for repeatable browser flows when possible.
12. Capture screenshots for important states, regressions, visual layout checks, or before/after evidence.
13. Use Computer Use when the workflow depends on desktop-app behavior, OS dialogs, file upload/download pickers, native menus, or interactions outside the browser.
14. Compare actual behavior against expected behavior.
15. Capture failures with evidence.
16. If the issue is small and clearly fixable within scope, fix or propose a precise fix depending on the user's instruction.
17. Rerun failed checks after fixes.
18. Produce a final validation report.
19. Run or invoke `$logall` after validation so the test outcome is recorded in the fivecircles operating logs.

## Test Rule Bootstrap

If test rules are missing, stale, or contradicted by real failures:

1. Read the most recent test error output, CI logs, `fivecircles/test/errorlogs/`, and local command output.
2. Infer the reliable test entrypoints from project files instead of guessing.
3. Create or update the smallest test rule document needed to make future runs repeatable.
4. Keep the document factual: command, working directory, prerequisites, environment variables, browser setup, known flaky/blocking errors, evidence required, and logging path.
5. Continue testing after the rule document exists.

Do not spend time writing a large testing guide when a compact policy is enough to unblock validation.

## Tool policy

Use the strongest available validation tool.

### Computer use

Use computer use when:

- the app must be inspected visually
- browser behavior cannot be fully verified from tests
- login/admin navigation must be manually checked
- screenshot evidence is needed
- UI layout or interaction must be compared with requirements
- the scenario crosses browser boundaries into OS dialogs, file pickers, downloaded files, native apps, or system-level prompts

### Browser use

Use browser use when:

- the target is a web UI
- routes, forms, buttons, modals, and network behavior must be checked
- admin/customer flows must be verified in a real browser
- manual navigation is faster than writing automation

### Playwright

Use Playwright when:

- the flow should be repeatable
- regression coverage is needed
- user interactions can be scripted
- screenshots, DOM assertions, URL checks, or network checks are useful
- existing Playwright setup exists

Prefer existing Playwright config and conventions.

If no Playwright setup exists, do not add a large framework unless requested.
For small projects, create a minimal smoke script only if it is low-risk and useful.

## Test discovery

Inspect available commands before choosing checks.

Examples:

- Node:
  - `npm test`
  - `npm run test`
  - `npm run build`
  - `npm run lint`
  - `npm run typecheck`
  - `npm run e2e`
  - `npx playwright test`

- Gradle:
  - `./gradlew test`
  - `./gradlew build`
  - targeted module tests

- Maven:
  - `./mvnw test`

- Python:
  - `pytest`
  - `ruff`
  - `mypy`

If commands are unclear, inspect package files or build files:

- `package.json`
- `playwright.config.*`
- `vite.config.*`
- `pom.xml`
- `build.gradle`
- `settings.gradle`
- `pyproject.toml`
- `pytest.ini`

## UI validation rules

For UI/admin/customer flows, validate the actual screen.

Check:

- correct page loads
- correct route
- required data appears
- empty/loading/error states
- button behavior
- modal behavior
- form validation
- confirmation/cancel flows
- permission/risk warnings
- success/failure toast or message
- table/card rendering
- no unexpected long freeform output when structured UI is expected
- no console errors when relevant
- no obvious network failures when relevant

Also check the task from the user's completion standard:

- happy path works end to end
- empty/loading/error states do not trap the user
- invalid input produces useful feedback
- refresh/back/forward behavior is reasonable when relevant
- desktop and mobile viewport layouts remain usable when the UI is responsive
- text, controls, overlays, focus, and scrolling do not block the intended action

## Visual comparison rules

When expected UI is defined by a screenshot, design note, or previous behavior:

1. Capture or inspect the actual screen.
2. Compare layout, key text, visible components, and interaction states.
3. Do not over-focus on pixel-perfect details unless the user asks.
4. Focus on user-visible correctness and functional behavior.
5. Record mismatches clearly.

Use this format:

```md
| Area | Expected | Actual | Status |
| --- | --- | --- | --- |
| ... | ... | ... | PASS/FAIL |
```

## Playwright scenario rules

When writing or running Playwright checks, prefer clear scenario names.

Example structure:

```ts
test("admin agent creates import preview and requires confirmation before mutation", async ({ page }) => {
  await page.goto("/admin/ai");

  await page.getByRole("textbox").fill("아까 올린 엑셀로 상품등록해");
  await page.getByRole("button", { name: /send|전송|보내기/i }).click();

  await expect(page.getByText(/미리보기|preview/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /등록|확인|confirm/i })).toBeVisible();
});
```

Assertions should verify behavior, not merely that the page opened.

Useful checks:

- URL changed correctly
- expected text appears
- table/card count appears
- confirmation button appears for mutations
- cancellation works
- capability gap appears for unsupported actions
- no direct mutation happens before confirmation

## Admin agent specific checks

For admin AI agent work, verify these flows when relevant:

### Intent and freeform leak

- execution request should not become plain freeform text
- unsupported action should return capability gap
- low confidence should ask clarification
- known tool should produce structured tool plan or UI response

### Context bundle

- "이거"
- "방금 거"
- "아까 올린 엑셀"
- "방금 결과에서 오류난 것만"
- current page/selected row/visible entity references

should resolve correctly when the relevant context exists.

### Pending action

- mutation creates preview or pending action first
- confirm executes the pending action
- cancel cancels the pending action
- repeated confirm does not duplicate work
- pending action expires or invalidates safely when context changes

### Capability gap

- unknown tool
- missing permission
- unsupported UI action
- disconnected external service

should produce explicit capability gap, not fake success.

### Response composer

- product results render as cards
- inventory/import/calculation results render as tables
- mutation tasks render as preview/confirm UI
- admin execution responses do not become long markdown essays

### Audit and idempotency

- mutation attempts are auditable
- duplicate submit/confirm is handled safely
- permission denial is visible and safe

## Failure handling

When a check fails:

- Capture the failing command or scenario.
- Summarize the expected result.
- Summarize the actual result.
- Include relevant error output.
- Identify likely cause if possible.
- Determine whether it is fixable within scope.
- Rerun after fix if a fix is made.

Do not hide failures.
Do not mark a flow as passed without evidence.

## Terminal states

Each validation item must reach one terminal state:

- PASS
- FAIL
- BLOCKED
- SKIPPED_WITH_REASON

Do not leave checks as TODO or NEXT in the final report unless they are blocked or explicitly out of scope.

## Test ledger

Maintain a test ledger:

```txt
Test Runner Ledger
- Target feature:
- Requirement/contract source:
- Commands discovered:
- Commands run:
- Browser flows checked:
- Playwright scenarios run:
- Passed:
- Failed:
- Blocked:
- Skipped with reason:
- Fixes applied:
- Reruns:
- Evidence:
```

## Optional persistent report

If the repository allows it, create or update a validation report:

```txt
fivecircles/test/<feature-name>-validation.md
```

or

```txt
fivecircles/test/agent-admin-test-report.md
```

Use the repository's existing convention if present.
For fivecircles-governed repositories, prefer `fivecircles/test/` for validation reports, `fivecircles/test/errorlogs/` for failure logs, and `fivecircles/work/update.md` plus `fivecircles/work/worklog.md` for closeout evidence.

## Logall closeout

For fivecircles validation work, do not finish with only a chat summary or test report.

After checks reach terminal states, run or invoke `$logall` to record:

- validation scope and final verdict
- commands, browser checks, and Playwright checks run
- failures, fixes, reruns, and remaining risks
- links to validation reports or screenshots
- backend/frontend error logs when failures occurred
- learn-from-log entries for recurring or newly discovered failure patterns

If `$logall` is unavailable, manually update the equivalent files under:

- `fivecircles/work/update.md`
- `fivecircles/work/worklog.md`
- `fivecircles/test/learn-from-log.md` when there is a reusable lesson
- `fivecircles/test/errorlogs/` when a failure, false negative, or environment issue occurred

If validation is blocked before meaningful checks can run, still log the blocker and exact next unblock step.

## Report structure

Use this structure for non-trivial validation:

```md
# <Feature> Validation Report

## 1. Scope

## 2. Requirement / Contract Source

## 3. Environment

## 4. Commands Run

## 5. Browser / UI Flows Checked

## 6. Playwright Scenarios

## 7. Results Summary

## 8. Failure Details

## 9. Fixes Applied

## 10. Rerun Results

## 11. Remaining Risks

## 12. Final Verdict
```

## Final verdict rules

Use one of:

- PASS
- PASS_WITH_RISKS
- FAIL
- BLOCKED

### PASS

Use only when relevant checks passed and no meaningful unresolved risk remains.

### PASS_WITH_RISKS

Use when core behavior works, but some non-blocking checks could not be completed or minor risks remain.

### FAIL

Use when expected behavior does not work and the failure is not fixed.

### BLOCKED

Use when validation cannot proceed due to environment, credentials, missing server, missing data, or unavailable tools.

## No early exit rule

Do not stop after discovering tests.
Do not stop after running only unit tests if browser behavior is central.
Do not stop after one failed check if the issue is fixable.
Do not produce a final response while validation items remain actionable.

## Final response requirements

Final response must include:

- final verdict
- commands run
- browser/computer checks performed
- Playwright checks performed
- passed checks
- failed checks
- blockers
- fixes applied, if any
- remaining risks
- exact next unblock step if blocked
- logall/update-log files touched, or the reason logging was skipped

## Call Prompt Template

Use this form when invoking the workflow:

```txt
Use $test-runner.

Goal:
관리자 AI 에이전트 구현 내용을 실제 화면에서 검증해줘.

Validation target:
- /admin/ai
- IntentGuard
- AgentContextBundle
- AgentPlannerProvider
- pending action confirm/cancel
- capability gap
- AgentResponseComposer
- Excel import preview/product registration
- image main placement flow if available

Tools:
- Use computer/browser inspection for actual UI behavior.
- Use Playwright when repeatable browser scenarios are possible.
- Run repository-native tests/build/lint/typecheck when available.

Hard rules:
- Do not stop after unit tests only.
- Verify actual screen behavior.
- Compare expected vs actual.
- Capture failures with evidence.
- Fix clearly small issues if in scope, then rerun.
- Final verdict must be PASS, PASS_WITH_RISKS, FAIL, or BLOCKED.
```
