# Skill: Read Log and Setup Task (톺아보기)

## Purpose
Systematically review project logs (`update.md`, `todolist.md`, `sync.md`, `debate.md`) to understand the recent context, identify the current state, and determine the immediate next steps. This is crucial for maintaining continuity across sessions.

## Usage
Execute this protocol when starting a new session or when asked to "read logs and setup task" or "톺아보기".

## Protocol Steps

1.  **Read Core Logs**
    - `fivecircles/work/update.md`: Check the latest completed tasks and their outcomes.
    - `fivecircles/architecture/todolist.md`: Identify pending tasks and active assignments.
    - `fivecircles/agent/sync.md` if present: Review recent announcements, sprint goals, and handover notes.
    - `fivecircles/requirements/debates/` if present: Check for ongoing or recently resolved debates that might affect the current work.

2.  **Check Request Queue**
    - If `fivecircles/agent/queue.json` exists, identify open tasks, owners, and blockers that require coordination.

3.  **Analyze Context**
    - **Recent Changes**: Identify what was changed last (e.g., "Frontend port changed to 3000").
    - **Current Goal**: Determine the active objective (e.g., "Deploy to bit-ts", "Verify V6 migration").
    - **Blockers/Risks**: Note any highlighted risks or issues (e.g., "Auth header mismatch").

4.  **Determine Action for Recent Changes**
    - Evaluate recent ad-hoc changes (like local config tweaks).
    - **Decision Criteria**:
        - *Keep*: If it's a necessary local dev configuration (e.g., `.env` setup).
        - *Formalize*: If it should be part of the shared repo (commit to git).
        - *Revert*: If it was a temporary experiment that is no longer needed.
    - **Action**: explicit statement on how to handle these changes in the next steps.

5.  **Setup Next Task**
    - precise definition of the next immediate task based on the analysis.
    - "Based on the logs, the next task is [Task Name]. I will [Action]."

## Example Output
"I have reviewed the logs.
- **Recent Context**: V2.5 UI implemented, Frontend port set to 3000 locally.
- **Current Goal**: Deploy to bit-ts and run E2E tests.
- **Decision on Port 3000**: Keep as local configuration for independent frontend testing.
- **Next Task**: Proceed with deploying the latest build to `bit-ts`."
