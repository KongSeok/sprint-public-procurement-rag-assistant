#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional


def fail(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def repo_root_from_cwd() -> str:
    base = os.path.abspath(os.getcwd())
    if not os.path.isdir(os.path.join(base, "fivecircles")):
        fail("fivecircles/ not found under current directory (run from repo root)")
    return base


def load_queue(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        fail(f"queue.json not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "tasks" not in data:
        fail("invalid queue.json: missing root object/tasks")
    if not isinstance(data["tasks"], list):
        fail("invalid queue.json: tasks must be a list")
    return data


def next_task_id(tasks: List[Dict[str, Any]]) -> str:
    max_n = 0
    pat = re.compile(r"^TASK-(\d+)$")
    for t in tasks:
        tid = t.get("id")
        if not isinstance(tid, str):
            continue
        m = pat.match(tid.strip())
        if not m:
            continue
        max_n = max(max_n, int(m.group(1)))
    return f"TASK-{max_n + 1:03d}"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Enqueue a task into fivecircles/agent/queue.json")
    p.add_argument("--queue", default=None, help="Path to queue.json (default: repo fivecircles/agent/queue.json)")
    p.add_argument("--title", required=True)
    p.add_argument("--description", required=True)
    p.add_argument("--assigned-to", required=True)
    p.add_argument("--assigned-zone", required=True)
    p.add_argument("--priority", required=True, choices=["low", "medium", "high", "urgent"])
    p.add_argument("--status", default="pending", choices=["pending", "in_progress", "review", "done", "blocked"])
    p.add_argument("--dependencies", nargs="*", default=[])
    p.add_argument("--created-by", default="codex")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    root = repo_root_from_cwd()
    queue_path = args.queue or os.path.join(root, "fivecircles", "agent", "queue.json")

    queue = load_queue(queue_path)
    tasks: List[Dict[str, Any]] = queue["tasks"]

    new_id = next_task_id(tasks)
    now = utc_now_iso()

    task: Dict[str, Any] = {
        "id": new_id,
        "title": args.title,
        "description": args.description,
        "assignedTo": args.assigned_to,
        "assignedZone": args.assigned_zone,
        "priority": args.priority,
        "status": args.status,
        "dependencies": args.dependencies or [],
        "createdBy": args.created_by,
        "createdAt": now,
        "updatedAt": now,
    }

    if args.dry_run:
        print(json.dumps(task, ensure_ascii=False, indent=2))
        return

    tasks.append(task)
    queue["lastUpdated"] = now

    with open(queue_path, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(new_id)


if __name__ == "__main__":
    main()

