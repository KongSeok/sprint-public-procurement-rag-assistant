---
name: fivecircles
description: Run the fivecircles project workflow for this repo. Use when the user says "fivecircles", "run fivecircles", "skill fivecircles", or asks to start or activate the fivecircles process.
---

# Fivecircles workflow

- Read `fivecircles/README.md` first; treat it as the folder index and skill inventory pointer.
- Read `fivecircles/agent-guidelines.md`, `fivecircles/agent/README.md`, `fivecircles/agent/agent-guidelines.md`, and `fivecircles/agent/operational-guidance.md` next.
- Check `fivecircles/agent/skills/` and load the local `SKILL.md` that matches the user request.
- Follow the authority order from `fivecircles/agent/authority.md`; resolve conflicts by higher priority.
- Keep context lean: open only the specific spec files needed for the current task.
- Use the development cycle and policies defined in `fivecircles/agent/workflow.md`; update `architecture/todolist.md`, `work/` logs, `test/errorlogs/`, and `scoring/log-score.md` as required.
- Use `rg -n "keyword" fivecircles/architecture/specs` to locate authoritative technical details quickly.
