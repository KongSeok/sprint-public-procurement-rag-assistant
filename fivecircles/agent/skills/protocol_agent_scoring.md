# Skill: Protocol for Agent Scoring

## Purpose
Quantitatively evaluate agent execution quality, ensure spec alignment, and promote operational efficiency through a structured scoring system.

## Usage
Execute this protocol after completing a significant implementation, bug fix, or session to record progress and identify optimizations.

## Protocol Steps

1.  **Gather Context**
    - Review the completed tasks in `todolist.md`.
    - Review logs in `update.md`, `errorlogs/`, and `mistakes-arrest.md`.

2.  **Calculate Score**
    - **A. Progress**: Score based on task completion (+30 per task, +15 per API, etc.).
    - **B. Quality**: Score based on testing and learning (+40 for tests, +35 for logged fixes).
    - **C. Spec Alignment (Penalty)**: Subtract points for violations (-120 for spec breach, -80 for path errors).
    - **D. Ops Efficiency**: Bonus for clean work (+10) or penalty for repetition (-30, -80).

3.  **Record Scoring Log**
    - Append the result to `fivecircles/scoring/log-score.md`.
    - **Format**:
      ```markdown
      ### Session: [Date] [Topic]
      - RESULT: [Success/Partial/Fail]
      - SCOPE: [Service Name]
      - SPEC: [Referenced Specs]
      - GAIN: [Points Added]
      - LOSS: [Points Subtracted]
      - TOTAL_POINTS: [Current Total]
      - REASON: [Brief justification]
      ```

4.  **Suggest Optimization**
    - If a better way was possible, record it in `fivecircles/scoring/optimization.md`.
    - If not, record "Optimization bonus +10" in the log.

5.  **Level Check**
    - Update current Level (Lv0-Lv3) based on Total Points.
    - Confirm capabilities (e.g., Lv2 allowed for cross-service work).
