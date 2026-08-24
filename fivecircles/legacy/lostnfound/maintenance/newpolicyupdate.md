# Policy Update Record

- Maintenance includes updating specs/implementation rules when repeatable lessons are found cost-effective.
- Promote runtime learnings from error logs into specs where appropriate.
- Track resulting tasks in `architecture/` (e.g., `architecture/todolist.md`, `work/frontend-plan.md`).
- Hotfix/bugfix is a small cycle (log error → fix → retest → log learning); full requirements analysis is only for new/changed requests.

## 2025-12-22 Policy Adjustments
- Dual-role model: users may hold LOSER and FINDER simultaneously; roles are add-only via `/auth/roles` or automatic add on lost/found creation.
- User-facing role edits are limited to adding the missing LOSER/FINDER role; other roles are display-only.
