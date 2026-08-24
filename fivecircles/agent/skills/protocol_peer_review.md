# Skill: Protocol for Peer Review (동료 리뷰)

## Purpose
Standardize the process of reviewing plans, code changes, or architectural decisions made by other agents. Use `debate.md` as the central hub for this activity.

## Usage
Execute this protocol when asked to "Review" (리뷰해) or when you detect a major change in `debate.md`.

## Protocol Steps

0.  **Check Review Requests (Queue First)**
    - Read `fivecircles/agent/queue.json` to find tasks with:
      - `assignedTo` = you (e.g. `codex-ops`) and/or
      - `assignedZone` = `review` and/or
      - `status` indicating review is needed (`review`, `pending` with a review title), and/or
      - references to a review doc under `fivecircles/work/review/`.
    - Optional: read `fivecircles/agent/sync.md` for any additional review announcements or context.
    - Select the highest-priority relevant review request(s) as the target scope for this review run.

1.  **Load Debate Context**
    - Read `fivecircles/agent/debate.md`.
    - Identify the current topic, decision, and the `Author` of the proposal.

2.  **Load Reference Documents**
    - Scan the debate content for file references (e.g., `specs/v2.5-def-plan.md`, `EventServiceImpl.java`).
    - **Action**: Read the referenced files to verify the actual implementation or specification.

3.  **Evaluation Criteria**
    - **Alignment**: Does the code/plan match the project specs (`readme.md`, `api-contract`)?
    - **Consistency**: Is the logic consistent with the `Decision` in `debate.md`? (e.g., "Did they actually use `INVOLVED` instead of `PARTICIPANT`?")
    - **Safety**: Are there potential side effects (Schema breaks, locking issues)?

4.  **Submit Review**
    - Append your review to `fivecircles/agent/debate.md`.
    - **Format**:
      ```markdown
      ### Review by [Agent]
      > Reviewer: <agent>-{role} | Date: [YYYY-MM-DD]
      - [Status]: Agreed / Changes Requested
      - [Comment]: ...
      ```
