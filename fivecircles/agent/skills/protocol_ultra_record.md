# Skill: Protocol for Task Completion (Ultra Record)

## Purpose
A high-level integrated protocol to definitively conclude a task. It enforces quality by requiring test success before logging and scoring.

## Usage
Execute this protocol when you believe a task is done.
Command: "Initiate ultra record" or "울트라 기록해".

## Protocol Steps

1.  **Step 1: Test Verification (Blocking)**
    - **Action**: Check if relevant tests (Frontend/Backend) have passed.
    - **Condition**:
        - **If Passed**: Proceed to Step 2.
        - **If Failed/Not Run**:
            1. Execute `protocol_test_execution.md`.
            2. Fix errors using `protocol_quick_debug.md`.
            3. **LOOP**: Repeat until tests pass. **No Scoring allowed until Success.**

2.  **Step 2: Push / Publication Gate**
    - **Action**: After tests pass, handle push/publication when the task has a repository, branch, PR, deployment branch, or user-requested publication target.
    - **Condition**:
        - **If Push Needed**: Stage only intended files, commit if needed, push the current branch, and record branch/remote/commit/PR or deployment URL.
        - **If Nothing to Push**: Mark `SKIPPED_WITH_REASON`.
        - **If Unsafe/Blocked**: Mark `BLOCKED` with exact reason, such as auth, branch policy, missing remote, failing required checks, or unrelated dirty changes.

3.  **Step 3: Schedule Relay Gate**
    - **Action**: If the user provided a work-until time, stop time, deadline, or session end time, invoke `$스케줄릴레이샷` after the push/publication gate.
    - **Condition**:
        - **If Time Remains**: Analyze remaining TODOs and continue the highest-value next task through `$one-shot-delivery-orchestrator`.
        - **If Time Passed**: Stop cleanly and report checked time, target time, and remaining work.

4.  **Step 4: Log & Summary**
    - **Reference**: `fivecircles/agent/skills/protocol_logging_summary.md`
    - **Action**:
        - Update `fivecircles/work/update.md` (What was done).
        - Update `fivecircles/architecture/todolist.md` (Task status).
        - Log any errors to `errorlogs/` and `mistakes-arrest.md`.
        - Update `fivecircles/agent/debate.md` with a summary.

5.  **Step 5: Scoring & Self-Correction**
    - **Reference**: `fivecircles/agent/skills/protocol_agent_scoring.md`
    - **Action**:
        - Calculate session score based on Progress, Quality, and Specs.
        - **Rule**: "Quality" points are valid ONLY if Step 1 (Tests) passed.
        - Record the score in `fivecircles/scoring/log-score.md`.
        - Propose optimizations in `fivecircles/scoring/optimization.md` if applicable.

6.  **Step 6: Final Sync**
    - **Action**:
        - Check `fivecircles/agent/sync.md` and update status if needed.
        - Confirm "Task Completed. Tests Passed. Total Score: [Score]. Ready for next task."
