---
name: operation-init
description: Initialize operational context by reading core project documentation. Use when the user says "운영방침 초기화", "초기화", "operation init", or when starting a new session.
---

# Operation Initialization

This skill initializes the agent's operational context by loading core project documentation in the correct order.

## When to Use

- At the beginning of a new session
- When the user says "운영방침 초기화" or "초기화"
- When context needs to be refreshed

## Protocol

Follow the protocol defined in `fivecircles/agent/skills/protocol_operation_init.md`:

1. Read `fivecircles/readme.md`
2. Read `fivecircles/architecture/specs/README.md`
3. Read `fivecircles/agent/agent-guidelines.md`
4. Read `fivecircles/agent/멀티에이전트설명서.md`
5. Read `fivecircles/work/update.md`
6. Read `fivecircles/architecture/todolist.md`
7. Confirm ready state with role and current task

See the full protocol in `../protocol_operation_init.md`.
