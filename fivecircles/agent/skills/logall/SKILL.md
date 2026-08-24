---
name: logall
description: Update project logs per policy without scoring. Use when asked to write or update error logs, learn-from-log, update.md, or todolist under fivecircles, but do not touch scoring files.
---

# logall

## Scope
- Maintain project documentation under `fivecircles/` (excluding scoring):
  - Test policy: `fivecircles/test/testpolicy.md`
  - Error logs: `fivecircles/test/errorlogs/backend/`, `fivecircles/test/errorlogs/frontend/`
  - Learn-from-log: `fivecircles/test/learn-from-log.md`
  - Update log: `fivecircles/work/update.md`
  - Work/update policy: `fivecircles/work/workpolicy.md`
  - Todo list: `fivecircles/architecture/todolist.md`
 - **Scope-bound logging**: Only log and update todos for the work actually handled in this repository/session.

## Workflow
1) Read the policy files before editing anything:
   - `fivecircles/test/testpolicy.md`
   - `fivecircles/work/workpolicy.md`
   If any policy file is missing or unclear, stop and ask for guidance.

2) Determine which documents to update based on the user request and actual work performed.

3) Error logs
   - Choose backend vs frontend directory based on the source of the error.
   - Follow existing filename/format conventions in the directory.
   - If no obvious convention exists, use `YYYY-MM-DD-<short-topic>.md`.
   - Log the minimal reproducible context, cause, and fix, following the test policy.

4) Learn-from-log
   - Update `fivecircles/test/learn-from-log.md` with key takeaways and cross-reference the error log entry.

5) Update log
   - Append a dated addendum in `fivecircles/work/update.md` with concise bullets of changes.
   - Follow the work policy’s format/section rules.

6) Todo list
   - Update `fivecircles/architecture/todolist.md` only if the change impacts pending work or newly discovered tasks.

## Scripts
Use `$CODEX_HOME/skills/logall/scripts/logall.py` (or copy it into your repo). Run from the repo root, or pass `--root`.

Policy auto-load + validation is ON by default. Add `--skip-policy` to bypass checks.

Token-lite is the default: required fields must be provided. Use `--full` to allow empty sections and add placeholders.

Examples:
- Error log (frontend, frontend format)
  - `$CODEX_HOME/skills/logall/scripts/logall.py errorlog --area frontend --format frontend --slug notif-badge-count --page "Navbar/NotificationBell" --summary "Unread badge count drifts" --symptom "Badge increments on read/unread toggle" --root-cause "Unread count updated without syncing allNotifications" --fix "Centralize read/unread updates" --result "Badge reflects true unread count"`
- Error log (backend, backend format)
  - `$CODEX_HOME/skills/logall/scripts/logall.py errorlog --area backend --format backend --slug login-invalid-credentials --context "Auth login" --issue "403 Invalid credentials for test users" --resolution "Reset hashes" --prevention "Use bcrypt hashes for seed users"`
- Learn-from-log
  - `$CODEX_HOME/skills/logall/scripts/logall.py learn --title "Notification badge drift" --cause "List + badge out of sync" --prevention "Centralize read/unread state updates"`
- Update log
  - `$CODEX_HOME/skills/logall/scripts/logall.py update --title "Notification badge count fix" --section "Frontend|Notification bell read/unread toggle now updates unread badge"`
- Todo list
  - `$CODEX_HOME/skills/logall/scripts/logall.py todo --status pending --item "Notifications: verify badge count sync after read/unread toggle"`

## Guardrails
- Do not update scoring files in this skill.
- Always follow the policies’ formatting and content rules.
- Keep entries concise and factual; avoid duplicating large content across files.
- Use absolute dates (YYYY-MM-DD) in log headers.
- Do not add todos or error logs for unrelated work outside the current repository/session scope.
