---
name: ultra-record
description: Comprehensive session logging including update log, todo sync, error recording, and scoring. Use when the user says "울트라 기록", "울트라 기록해", "ultra record", or when ending a work session.
---

# Ultra Record

This skill performs comprehensive end-of-session logging in one command.

## When to Use

- At the end of a work session
- When the user says "울트라 기록해" or "ultra record"
- When comprehensive documentation is needed

## What It Does

Executes all logging tasks in sequence:
1. Update log (`work/update.md`)
2. Todo list sync (`architecture/todolist.md`)
3. Error logs (`test/errorlogs/`)
4. Learn-from-log updates
5. Agent scoring (`scoring/log-score.md`)
6. Sync documentation

See the full protocol in `../protocol_ultra_record.md`.
