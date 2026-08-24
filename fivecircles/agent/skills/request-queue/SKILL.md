---
name: request-queue
description: Add tasks to fivecircles/agent/queue.json for other agents (e.g., Antigravity). Use when asked to "요청", "큐 넣기", "안티그래비티 큐", or to enqueue work items with id/title/description/assignee/priority.
---

# request-queue (요청/큐 넣기)

## Scope
- 다른 에이전트에게 작업을 요청할 때, `fivecircles/agent/queue.json`에 태스크를 추가한다.
- Agent-Bridge(MCP) 요청 파일은 Antigravity가 못 읽을 수 있으므로, 기본은 `queue.json`을 Source of Truth로 사용한다.

## Guardrails
- `queue.json`의 기존 태스크를 임의로 삭제하지 않는다.
- `id`는 `TASK-###` 포맷을 유지하고 중복되지 않게 증가시킨다.
- `lastUpdated`, `createdAt`, `updatedAt`은 UTC ISO-8601(`YYYY-MM-DDTHH:MM:SSZ`)로 기록한다.

## Workflow
1. `fivecircles/agent/queue.json`을 확인한다.
2. 새 태스크를 추가한다:
   - 기본: status=`pending`, dependencies=`[]`
   - 필수 필드: title, description, assignedTo, assignedZone, priority
3. `lastUpdated`를 현재 시각(UTC)으로 갱신한다.
4. 필요하면 `fivecircles/agent/sync.md`에 “큐에 넣었음”을 한 줄로 알린다(수동).

## Script (Recommended)
Use the script to avoid id/timestamp mistakes.

```bash
python3 fivecircles/agent/skills/request-queue/scripts/enqueue_task.py \
  --title "QA UI: Related Characters Aggregate (ALLY/ADVERSARY)" \
  --description "..." \
  --assigned-to antigravity \
  --assigned-zone frontend \
  --priority high
```

Options
- `--status` (default: pending)
- `--dependencies TASK-008 TASK-009 ...`
- `--created-by` (default: codex)

## Manual Fallback (If script unavailable)
- Open `fivecircles/agent/queue.json`
- Find max TASK number, increment by 1
- Append task object with required fields
- Update `lastUpdated` and the new task’s `createdAt/updatedAt`

