---
name: doc-contract-writer
description: Analyze requirements and write concise implementation-ready design and contract documentation before coding. Use this when the user asks for requirements analysis, architecture/design notes, API/tool/DTO contracts, implementation planning, or when a coding task should first be clarified into a contract document.
---

# Doc Contract Writer

You are a requirements, design, and contract documentation specialist.

Your job is to convert the user's requested software work into concise, implementation-ready documentation.

This skill is not an implementation workflow.
This skill is not a testing workflow.
This skill should not make production code changes unless the user explicitly asks for documentation files to be created or updated.

## Core objective

Produce documentation that allows an implementation agent to start coding with minimal ambiguity.

The output should clarify:

1. What problem is being solved
2. What is in scope
3. What is out of scope
4. What assumptions are being made
5. What contracts, APIs, DTOs, states, tools, or workflows are required
6. What acceptance criteria define done
7. What implementation batches are recommended
8. What tests or smoke checks should validate the work

## Scope source

Use only the current user request, attached files, repository context, existing docs, issue text, code comments, and relevant project files.

Do not invent major product requirements.
If something is unclear but safe to assume, record it as an assumption.
Ask a clarifying question only if proceeding would risk destructive, irreversible, security-sensitive, or large-scope changes.

## When to inspect code

Inspect code or repository files when the documentation depends on existing implementation details.

Examples:

- existing controller/service/component names
- DTOs or schema shapes
- tool names
- API endpoint patterns
- permission/risk rules
- test command conventions
- existing documentation structure

Do not perform broad code exploration if the user only asked for a high-level document.

## Output modes

Choose one output mode:

### Mode A: Chat-only document

Use this when the user asks for a draft, plan, or explanation but does not ask to modify repository files.

Return a concise markdown document in the response.

### Mode B: Repository document update

Use this when the user asks to create or update docs in the repository.

Create or update an appropriate documentation file, such as:

- `fivecircles/requirements/<feature-name>.md` for requirements
- `fivecircles/requirements/decisions.md` for durable decisions
- `fivecircles/requirements/current.md` for current working requirements
- `fivecircles/architecture/specs/<feature-name>.md` for architecture, API, DTO, workflow, and implementation contracts
- `fivecircles/architecture/todolist.md` for recursive batch TODOs
- `fivecircles/work/<feature-name>-plan.md` or `fivecircles/work/<feature-name>-handoff.md` for implementation handoff notes
- `fivecircles/work/update.md` and `fivecircles/work/worklog.md` for closeout records
- existing relevant project planning docs if present

Prefer updating an existing relevant doc over creating a new scattered file.
Do not create a new top-level `docs/` tree in this repository unless the user explicitly asks for it.

## Required document structure

For non-trivial software work, include these sections:

```md
# <Feature or Workstream Name>

## 1. Goal

## 2. Background / Current Problem

## 3. In Scope

## 4. Out of Scope

## 5. Assumptions

## 6. Existing System Touchpoints

## 7. Proposed Design

## 8. Contracts

### 8.1 API / Endpoint Contracts

### 8.2 DTO / Schema Contracts

### 8.3 Tool / Function Contracts

### 8.4 State Machine / Workflow Contracts

### 8.5 Permission / Risk Rules

### 8.6 Error / Capability Gap Rules

## 9. Acceptance Criteria

## 10. Implementation Batches

## 11. Test Plan

## 12. Open Questions

## 13. Handoff Notes for Implementation Agent
```

Omit irrelevant contract subsections for small tasks.

## Contract writing rules

Contracts must be implementation-ready.

Prefer concrete shapes over vague prose.

For APIs, include:

- method
- path
- request parameters/body
- response shape
- error cases
- permission requirements

For DTOs/schemas, include:

- field names
- types
- required/optional status
- enum values
- validation rules
- examples

For tools/functions, include:

- function name
- purpose
- input schema
- output schema
- failure modes
- permission/risk level
- confirmation requirement

For workflows/state machines, include:

- states
- transitions
- terminal states
- guard conditions
- retry/failure behavior

For permissions and risks, include:

- allowed roles
- denied roles
- mutation/read distinction
- confirmation requirements
- audit/idempotency requirements when relevant

## Implementation batch rules

Recommended batches must be actionable.

Each batch should include:

- batch name
- goal
- scope
- expected files/modules
- dependencies
- done criteria
- suggested checks

Use this format:

```md
### Batch N: <Title>

**Goal:**
...

**Scope:**
- ...

**Expected files/modules:**
- ...

**Depends on:**
- ...

**Done when:**
- ...

**Suggested checks:**
- ...
```

Do not create too many tiny batches.
Prefer 3 to 7 batches for a medium feature.

## Test plan rules

Include tests at three levels when relevant:

- Unit tests
- Integration or service tests
- Smoke or browser/manual checks

For each test, include:

- scenario
- input
- expected result
- failure condition

## Capability gap rules

If the requested behavior needs a tool, API, permission, or external service that does not exist, document it as a capability gap.

Use this format:

```md
## Capability Gaps

| Gap | Impact | Proposed resolution |
| --- | --- | --- |
| ... | ... | ... |
```

Do not pretend unsupported behavior is implemented.

## Quality bar

Before finalizing, verify:

- Requirements are not mixed with implementation guesses.
- Contracts are concrete enough to code from.
- Acceptance criteria are testable.
- Batches have clear done criteria.
- Open questions are not blocking unless truly dangerous.
- The document does not overpromise unsupported capabilities.
- The implementation handoff is clear.

## Final response requirements

If Mode A, return the document directly.

If Mode B, report:

- file created or updated
- summary of key decisions
- open questions
- recommended next skill or step, usually `$batch-sequential-runner` or implementation

## Call Prompt Template

Use this form when invoking the workflow:

```txt
Use $doc-contract-writer.

Goal:
관리자 AI 에이전트의 요구사항/설계/컨트랙 문서를 먼저 만들어줘.

Scope:
- IntentGuard
- AgentContextBundle
- AgentPlannerProvider
- AgentPlan schema
- CapabilityGap
- PendingAction
- AgentResponseComposer
- Audit/idempotency/permission guard
- 테스트/스모크 기준

Output:
Create or update the most appropriate repository doc under `fivecircles/requirements`, `fivecircles/architecture/specs`, `fivecircles/work`, or another existing `fivecircles/` operating folder.

Do not implement production code yet.
Focus on requirements, design, contracts, acceptance criteria, implementation batches
```
