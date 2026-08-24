---
name: just-bash-workflow
description: Run safe, sandboxed shell exploration using just-bash (TypeScript simulated bash + virtual filesystem) instead of the host shell. Use when asked to "use just-bash/just bash/jb", when doing read-only repo exploration (rg/ls/cat/jq/yq/sed), or when you want in-memory writes for quick transforms without touching disk.
---

# just-bash-workflow

## What It Is (Important)
- `just-bash` is **not** the host OS bash. It is a **TypeScript-implemented simulated bash**.
- CLI mounts the repo via **OverlayFS**:
  - Reads come from the real filesystem under `--root`.
  - Writes are **in-memory only** and are discarded after the command finishes.
- No network by default. In our CLI usage, `curl` is typically **not available**.

## Quick Start
Use repo wrappers (preferred):
```bash
# read-only exploration
./scripts/jb -c 'rg -n "predicate" -S . | head'

# in-memory writes (still not persisted to host disk)
./scripts/jbw -c 'echo hi > /tmp/x && cat /tmp/x'
```

If wrappers are missing, install them:
```bash
$CODEX_HOME/skills/just-bash-workflow/scripts/install_wrappers.sh --root .
```

## When To Use / Not Use
Use `just-bash` for:
- Fast, safe repo exploration: `rg`, `find`, `ls`, `cat`, `sed`, `jq`, `yq`, small pipelines
- Transforming data with temporary files (in-memory) to inspect results

Do not use `just-bash` for:
- Changes that must persist (code edits): use `apply_patch` or normal shell commands
- Long-running services (dev server), Docker/Gradle builds, or anything that needs real disk writes
- Network fetches (assume no network)

## Working Patterns
Repo search:
```bash
./scripts/jb -c 'rg -n "EventMapper" -S services | head -n 50'
```

Peek file sections:
```bash
./scripts/jb -c 'sed -n "1,160p" services/event-service/README.md'
```

JSON inspection:
```bash
./scripts/jb -c "cat package.json | jq '.scripts'"
```

Python (opt-in only):
```bash
just-bash --python -c 'python3 -V' --root .
```

## Guardrails
- Assume **all writes are ephemeral**. If you "created/edited" a file via `just-bash`, it did not change the host repo.
- If you need to persist edits: switch to `apply_patch` or normal shell + git diff.
- Keep output small (pipe to `head`, use focused `rg` queries) to reduce tool output noise.

