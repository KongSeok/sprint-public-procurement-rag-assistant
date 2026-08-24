# Skill: Protocol for Logging & Summary

## Purpose
Standardize the workflow for recording work progress, errors, and reviews to ensure traceability and collaboration among agents.

## Usage
Execute this protocol at the end of every significant task or session.

## Protocol Steps

1.  **Work Update (`fivecircles/work/update.md`)**
    - **Required**.
    - Log the Goal, Changes (files/logic), Status, and Next Steps.
    - Format: `## YYYY-MM-DD: <Topic>`

2.  **Todo Tracking (`fivecircles/architecture/todolist.md`)**
    - **Required**.
    - Mark completed tasks with `[x]`.
    - Add new pending tasks with `[ ]` if discovered/planned.

3.  **Agent Sync (`fivecircles/agent/sync.md`)**
    - **Required**.
    - Update your agent's status (Active -> Idle) or Current Task description.
    - Check for announcements from other agents.

4.  **Error Logging (Conditional)**
    - **Trigger**: Build failures, Runtime errors (Backend/Frontend), Test failures.
    - **Action 1**: Create detailed log in `fivecircles/test/errorlogs/<category>/YYYY-MM-DD-<issue>.md`.
    - **Action 2**: Add prevention/insight to `fivecircles/test/learn-from-log.md`.

4.  **Agent Mistake Logging (Conditional)**
    - **Trigger**: Agent hallucination, tool misuse, path/spec mismatch.
    - **Action**: Log the incident and arrest rule in `fivecircles/agent/mistakes-arrest.md` (or `mistakes-repeating.md`).

5.  **Debate & Summary (`fivecircles/agent/debate.md`)**
    - **Trigger**: After architectural changes, merges, or strategic shifts.
    - **Action**: Append a status report or discussion summary following the file's header manual.
    - **Format**: `> Author: <agent>-{role} | Date: ...`
