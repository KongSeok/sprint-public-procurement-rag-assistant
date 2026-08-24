# Skill: Protocol for Operation Initialization

## Purpose
Initialize the agent's mental model, operational boundaries, and context by loading the core project documentation in the correct order. Use this to minimize context loss when starting a new session.

## Usage
Execute this protocol at the beginning of a session or when instructed to "Initialize operational policy" (운영방침 초기화).

## Protocol Steps

1.  **Bootstrapping (`fivecircles/README.md`)**
    - Read the root documentation to understand the file structure, local skill inventory, and the "Five Circles" methodology.

2.  **Local Skills**
    - Confirm `fivecircles/agent/skills/` exists.
    - List available local skills and prefer them over similarly named global skills.

3.  **Workflow & Guidelines**
    - Read `fivecircles/architecture/specs/README.md` to define the project workflow.
    - Read `fivecircles/agent/README.md`.
    - Read `fivecircles/agent-guidelines.md` to load the legacy root execution guidance.
    - Read `fivecircles/agent/agent-guidelines.md` to understand behavioral rules and limits.
    - Read `fivecircles/agent/authority.md`, `workflow.md`, `policies.md`, `methodology.md`, and `operational-guidance.md`.

4.  **Load Current Status**
    - Read `fivecircles/work/workpolicy.md`.
    - Read `fivecircles/test/testpolicy.md`.
    - Read `fivecircles/work/update.md` to grasp the latest progress.
    - Read `fivecircles/architecture/todolist.md` to identify pending tasks.

5.  **Ready State**
    - After reading, confirm: "Operational context initialized. Current focus is [Task from Todo]. Relevant local skill is [Skill Name or none]."
