#!/usr/bin/env python3
import argparse
import datetime as dt
import os
import re
import sys
from collections import defaultdict
from typing import Optional


def fail(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def resolve_root(root: Optional[str]) -> str:
    base = os.path.abspath(root or os.getcwd())
    if not os.path.isdir(os.path.join(base, "fivecircles")):
        fail("fivecircles/ not found under current directory; pass --root")
    return base


def load_policy(path: str) -> str:
    if not os.path.exists(path):
        fail(f"policy file missing: {path}")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    if not content.strip():
        fail(f"policy file empty: {path}")
    return content


def validate_policies(root: str, *, test: bool = False, work: bool = False, scoring: bool = False, skip: bool = False) -> None:
    if skip:
        return
    if test:
        load_policy(os.path.join(root, "fivecircles", "test", "testpolicy.md"))
    if work:
        load_policy(os.path.join(root, "fivecircles", "work", "workpolicy.md"))
    if scoring:
        load_policy(os.path.join(root, "fivecircles", "scoring", "agent-scoring-policy.md"))


def ensure_parent(path: str) -> None:
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)


def append_block(path: str, block: str) -> None:
    ensure_parent(path)
    needs_newline = False
    if os.path.exists(path):
        with open(path, "rb") as f:
            data = f.read()
            if data and not data.endswith(b"\n"):
                needs_newline = True
    with open(path, "a", encoding="utf-8") as f:
        if needs_newline:
            f.write("\n")
        f.write(block)
        if not block.endswith("\n"):
            f.write("\n")


def errorlog(args: argparse.Namespace) -> None:
    root = resolve_root(args.root)
    validate_policies(root, test=True, skip=args.skip_policy)
    area = args.area
    if area not in ("backend", "frontend"):
        fail("--area must be backend or frontend")
    slug = args.slug or "issue"
    date_str = args.date or dt.datetime.now().strftime("%Y-%m-%d")
    time_str = args.time or dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    filename = f"{date_str}-{slug}.md"
    path = os.path.join(root, "fivecircles", "test", "errorlogs", area, filename)

    format_mode = args.format
    if format_mode == "auto":
        format_mode = "frontend" if area == "frontend" else "backend"

    if format_mode == "backend":
        lines = [f"Timestamp: {time_str}"]
        if args.context:
            lines.append(f"Context: {args.context}")
        lines.append("")
        lines.append("Issues")
        issues = args.issue or []
        if not issues and not args.full:
            fail("backend format requires at least one --issue (use --full to allow empty)")
        if issues:
            for idx, item in enumerate(issues, 1):
                lines.append(f"{idx}) {item}")
        elif args.full:
            lines.append("- ")
        lines.append("")
        lines.append("Resolution")
        resolutions = args.resolution or []
        if not resolutions and not args.full:
            fail("backend format requires at least one --resolution (use --full to allow empty)")
        if resolutions:
            for item in resolutions:
                lines.append(f"- {item}")
        elif args.full:
            lines.append("- ")
        lines.append("")
        lines.append("Prevention")
        preventions = args.prevention or []
        if not preventions and not args.full:
            fail("backend format requires at least one --prevention (use --full to allow empty)")
        if preventions:
            for item in preventions:
                lines.append(f"- {item}")
        elif args.full:
            lines.append("- ")
    elif format_mode == "frontend":
        lines = [f"timestamp: {time_str}", "area: frontend"]
        if args.page:
            lines.append(f"page: {args.page}")
        lines.append("")
        lines.append("summary:")
        summaries = args.summary or []
        if not summaries and not args.full:
            fail("frontend format requires at least one --summary (use --full to allow empty)")
        if summaries:
            for item in summaries:
                lines.append(f"- {item}")
        elif args.full:
            lines.append("- ")
        lines.append("")
        lines.append("symptoms:")
        symptoms = args.symptom or []
        if not symptoms and not args.full:
            fail("frontend format requires at least one --symptom (use --full to allow empty)")
        if symptoms:
            for item in symptoms:
                lines.append(f"- {item}")
        elif args.full:
            lines.append("- ")
        lines.append("")
        lines.append("root_cause:")
        root_causes = args.root_cause or []
        if not root_causes and not args.full:
            fail("frontend format requires at least one --root-cause (use --full to allow empty)")
        if root_causes:
            for item in root_causes:
                lines.append(f"- {item}")
        elif args.full:
            lines.append("- ")
        lines.append("")
        lines.append("fix:")
        fixes = args.fix or []
        if not fixes and not args.full:
            fail("frontend format requires at least one --fix (use --full to allow empty)")
        if fixes:
            for item in fixes:
                lines.append(f"- {item}")
        elif args.full:
            lines.append("- ")
        lines.append("")
        lines.append("result:")
        results = args.result or []
        if not results and not args.full:
            fail("frontend format requires at least one --result (use --full to allow empty)")
        if results:
            for item in results:
                lines.append(f"- {item}")
        elif args.full:
            lines.append("- ")
    else:
        fail("--format must be auto, backend, or frontend")

    content = "\n".join(lines) + "\n"
    if os.path.exists(path) and not args.force:
        fail(f"error log already exists: {path} (use --force to overwrite)")
    ensure_parent(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(path)


def learn(args: argparse.Namespace) -> None:
    root = resolve_root(args.root)
    validate_policies(root, test=True, skip=args.skip_policy)
    path = os.path.join(root, "fivecircles", "test", "learn-from-log.md")
    title = args.title or "(title)"
    lines = [f"### {title}", "Cause:"]
    causes = args.cause or []
    if not causes and not args.full:
        fail("learn requires at least one --cause (use --full to allow empty)")
    if causes:
        for item in causes:
            lines.append(f"- {item}")
    elif args.full:
        lines.append("- ")
    lines.append("")
    lines.append("Preventive rule:")
    preventions = args.prevention or []
    if not preventions and not args.full:
        fail("learn requires at least one --prevention (use --full to allow empty)")
    if preventions:
        for item in preventions:
            lines.append(f"- {item}")
    elif args.full:
        lines.append("- ")
    block = "\n".join(lines) + "\n"
    append_block(path, block)
    print(path)


def update_log(args: argparse.Namespace) -> None:
    root = resolve_root(args.root)
    validate_policies(root, work=True, skip=args.skip_policy)
    path = os.path.join(root, "fivecircles", "work", "update.md")
    date_str = args.date or dt.datetime.now().strftime("%Y-%m-%d")
    header = f"## Addendum ({date_str})"
    if args.title:
        header += f" - {args.title}"
    sections = defaultdict(list)
    for raw in args.section or []:
        if "|" not in raw:
            fail("--section must be 'Section|Item'")
        section, item = raw.split("|", 1)
        section = section.strip()
        item = item.strip()
        if not section or not item:
            fail("--section requires non-empty section and item")
        sections[section].append(item)
    if not sections:
        fail("at least one --section is required")
    lines = [header]
    for section in sections:
        lines.append(f"### {section}")
        for item in sections[section]:
            lines.append(f"- {item}")
        lines.append("")
    block = "\n".join(lines).rstrip() + "\n"
    append_block(path, block)
    print(path)


def todo(args: argparse.Namespace) -> None:
    root = resolve_root(args.root)
    validate_policies(root, work=True, skip=args.skip_policy)
    path = os.path.join(root, "fivecircles", "architecture", "todolist.md")
    if not os.path.exists(path):
        fail(f"todo file missing: {path}")
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    status = args.status
    items = args.item or []
    if not items:
        fail("--item required (repeatable)")

    def find_section(header: str) -> int:
        for i, line in enumerate(lines):
            if line.strip().lower() == header.lower():
                return i
        return -1

    done_idx = find_section("## Done")
    pending_idx = find_section("## Pending")
    if done_idx == -1 or pending_idx == -1:
        fail("could not find '## Done' or '## Pending' headings")

    def next_heading(start: int) -> int:
        for i in range(start + 1, len(lines)):
            if lines[i].startswith("## "):
                return i
        return len(lines)

    if status == "done":
        insert_at = pending_idx
        new_lines = [f"- {item}" for item in items]
        lines[insert_at:insert_at] = new_lines
    elif status == "pending":
        end_idx = next_heading(pending_idx)
        max_num = 0
        number_re = re.compile(r"^(\d+)\)")
        for line in lines[pending_idx:end_idx]:
            m = number_re.match(line.strip())
            if m:
                max_num = max(max_num, int(m.group(1)))
        new_lines = []
        for item in items:
            max_num += 1
            new_lines.append(f"{max_num}) {item}")
        lines[end_idx:end_idx] = new_lines
    else:
        fail("--status must be done or pending")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(path)


def parse_int(value: str) -> int:
    cleaned = value.strip().replace(",", "")
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]
    return int(cleaned)


def read_last_total(path: str) -> int:
    if not os.path.exists(path):
        return 0
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    for line in reversed(lines):
        if line.strip().startswith("TOTAL:"):
            try:
                return parse_int(line.split(":", 1)[1])
            except Exception:
                continue
    for line in lines:
        if line.strip().startswith("Current total:"):
            try:
                return parse_int(line.split(":", 1)[1])
            except Exception:
                continue
    return 0


def update_score_header(path: str, total: int, timestamp: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    updated = False
    for i, line in enumerate(lines):
        if line.startswith("Current total:"):
            lines[i] = f"Current total: {total}"
            updated = True
        elif line.startswith("Last update:"):
            lines[i] = f"Last update: {timestamp}"
            updated = True
    if updated:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


def score(args: argparse.Namespace) -> None:
    root = resolve_root(args.root)
    validate_policies(root, scoring=True, skip=args.skip_policy)
    path = os.path.join(root, "fivecircles", "scoring", "log-score.md")
    timestamp = args.timestamp or dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_points = args.total_points
    total_value = args.total
    if args.auto_total:
        prev_total = read_last_total(path)
        gain = parse_int(args.gain)
        loss = parse_int(args.loss)
        computed = prev_total + gain - loss
        if total_points is None:
            total_points = str(computed)
        if total_value is None:
            total_value = str(computed)
    required = {
        "RESULT": args.result,
        "SCOPE": args.scope,
        "SPEC": args.spec,
        "POINTS": args.points,
        "REASON": args.reason,
        "GAIN": args.gain,
        "LOSS": args.loss,
        "TOTAL_POINTS": total_points,
        "UPGRADE": args.upgrade,
        "TOTAL": total_value,
    }
    missing = [k for k, v in required.items() if v is None]
    if missing:
        fail(f"missing fields: {', '.join(missing)}")
    lines = [f"Timestamp: {timestamp}"]
    for key, value in required.items():
        lines.append(f"{key}: {value}")
    block = "\n".join(lines) + "\n"
    append_block(path, block)
    if args.auto_total:
        update_score_header(path, parse_int(required["TOTAL"]), timestamp)
    print(path)


def optimization(args: argparse.Namespace) -> None:
    root = resolve_root(args.root)
    validate_policies(root, scoring=True, skip=args.skip_policy)
    path = os.path.join(root, "fivecircles", "scoring", "optimization.md")
    timestamp = args.timestamp or dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    required = {
        "Area": args.area,
        "Optimization": args.optimization,
        "Why it increases score": args.why,
        "When to apply": args.when,
        "Related tasks/files": args.related,
    }
    missing = [k for k, v in required.items() if v is None]
    if missing:
        fail(f"missing fields: {', '.join(missing)}")
    lines = [f"Timestamp: {timestamp}"]
    for key, value in required.items():
        lines.append(f"{key}: {value}")
    block = "\n".join(lines) + "\n"
    append_block(path, block)
    print(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Append log/update entries for fivecircles docs.")
    parser.add_argument("--root", help="Project root (contains fivecircles/)")
    parser.add_argument("--skip-policy", action="store_true", help="skip policy file checks")

    subs = parser.add_subparsers(dest="cmd", required=True)

    p_error = subs.add_parser("errorlog", help="Create a backend/frontend error log file")
    p_error.add_argument("--area", required=True, help="backend or frontend")
    p_error.add_argument("--slug", required=True, help="short slug for filename")
    p_error.add_argument("--format", default="auto", help="auto, backend, or frontend")
    p_error.add_argument("--full", action="store_true", help="allow empty sections and add placeholders")
    p_error.add_argument("--date", help="YYYY-MM-DD")
    p_error.add_argument("--time", help="YYYY-MM-DD HH:MM")
    p_error.add_argument("--context", help="short context line")
    p_error.add_argument("--issue", action="append", help="issue line (repeatable)")
    p_error.add_argument("--resolution", action="append", help="resolution line (repeatable)")
    p_error.add_argument("--prevention", action="append", help="prevention line (repeatable)")
    p_error.add_argument("--page", help="frontend page/screen name")
    p_error.add_argument("--summary", action="append", help="frontend summary line (repeatable)")
    p_error.add_argument("--symptom", action="append", help="frontend symptom line (repeatable)")
    p_error.add_argument("--root-cause", dest="root_cause", action="append", help="frontend root cause line (repeatable)")
    p_error.add_argument("--fix", action="append", help="frontend fix line (repeatable)")
    p_error.add_argument("--result", action="append", help="frontend result line (repeatable)")
    p_error.add_argument("--force", action="store_true", help="overwrite if exists")
    p_error.set_defaults(func=errorlog)

    p_learn = subs.add_parser("learn", help="Append to learn-from-log.md")
    p_learn.add_argument("--title", required=True, help="entry title")
    p_learn.add_argument("--cause", action="append", help="cause line (repeatable)")
    p_learn.add_argument("--prevention", action="append", help="preventive rule line (repeatable)")
    p_learn.add_argument("--full", action="store_true", help="allow empty sections and add placeholders")
    p_learn.set_defaults(func=learn)

    p_update = subs.add_parser("update", help="Append addendum to work/update.md")
    p_update.add_argument("--title", help="addendum title")
    p_update.add_argument("--date", help="YYYY-MM-DD")
    p_update.add_argument("--section", action="append", help="Section|Item (repeatable)")
    p_update.set_defaults(func=update_log)

    p_todo = subs.add_parser("todo", help="Append to todolist.md")
    p_todo.add_argument("--status", required=True, help="done or pending")
    p_todo.add_argument("--item", action="append", help="item text (repeatable)")
    p_todo.set_defaults(func=todo)

    p_score = subs.add_parser("score", help="Append a scoring log entry")
    p_score.add_argument("--timestamp", help="YYYY-MM-DD HH:MM:SS")
    p_score.add_argument("--result", required=True)
    p_score.add_argument("--scope", required=True)
    p_score.add_argument("--spec", required=True)
    p_score.add_argument("--points", required=True)
    p_score.add_argument("--reason", required=True)
    p_score.add_argument("--gain", required=True)
    p_score.add_argument("--loss", required=True)
    p_score.add_argument("--total-points")
    p_score.add_argument("--upgrade", required=True)
    p_score.add_argument("--total")
    p_score.add_argument("--no-auto-total", action="store_false", dest="auto_total", help="disable auto total calc")
    p_score.set_defaults(auto_total=True)
    p_score.set_defaults(func=score)

    p_opt = subs.add_parser("opt", help="Append an optimization note")
    p_opt.add_argument("--timestamp", help="YYYY-MM-DD HH:MM:SS")
    p_opt.add_argument("--area", required=True)
    p_opt.add_argument("--optimization", required=True)
    p_opt.add_argument("--why", required=True)
    p_opt.add_argument("--when", required=True)
    p_opt.add_argument("--related", required=True)
    p_opt.set_defaults(func=optimization)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
