---
name: read-log
description: Analyze recent logs (update, todo, sync) to understand context and recent changes. Use when the user says "톺아보기", "read log", or when resuming work.
---

# Read Log (톺아보기)

This skill reads and analyzes project logs to restore context.

## When to Use

- When resuming work after a break
- When the user says "톺아보기" or "read log"
- To understand recent changes

## Analysis Flow

1. Read `fivecircles/work/update.md` (recent changes)
2. Read `fivecircles/architecture/todolist.md` (pending work)
3. Read `fivecircles/agent/sync.md` (team status)
4. Analyze recent changes (e.g., port changes, API updates)
5. Prepare context for next work

See the full protocol in `../protocol_read_log_setup.md`.
