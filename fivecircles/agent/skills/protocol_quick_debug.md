# Skill: Protocol for Quick Debugging (빠른 디버깅)

## Purpose
Accelerate error resolution by leveraging historical failure data (mistakes, lessons, optimizations) before attempting deep investigation. "Don't solve the same bug twice."

## Usage
Execute this protocol immediately when an error (Compile, Runtime, Test) occurs.

## Protocol Steps

1.  **Scan Knowledge Base**
    - Read `fivecircles/agent/mistakes-arrest.md`: Check for recurrent agent/operational mistakes (e.g., path mismatch, DTO mapping).
    - Read `fivecircles/test/learn-from-log.md`: Check for previously solved technical issues.
    - Read `fivecircles/scoring/optimization.md`: Check for suggested performance/structure improvements that might relate to the bug.

2.  **Pattern Matching**
    - **Keyword Search**: Use `grep` or search on the error message against these files.
    - **Match Found?**: Apply the documented "Arrest" or "Solution" strategy immediately.
    - **No Match?**: Proceed to standard investigation (Logs -> Code -> Test).

3.  **Apply & Verify**
    - Implement the fix.
    - Run the specific test case that failed.

4.  **Update Knowledge**
    - If the error was **NEW**: Create a new entry in `fivecircles/test/learn-from-log.md` with the Symptom, Cause, and Solution.
    - If the error was **REPEATED**: Increment the occurrence count in the existing log (and penalize score via `ultra_record`).
