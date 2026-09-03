# Git and Publication Contract

## Repository Root

The repository root is `/Users/pio/Documents/AIENGINEERCOURSE/MidProjectRAG`.
Git commands and safety checks run from this directory.

## Tracked Content

- source code, tests and configuration templates
- requirements, architecture contracts and work logs
- schemas and synthetic fixtures
- redacted aggregate evaluation results and reviewed reports

## Never Track

- Entire root `resources/**`, regardless of extension (including team shares and model weights).
- `.env*` except `.env.example`, API/SSH/service-account credentials
- source HWP/PDF and `data_list.csv`
- extracted text, rendered documents, chunks and embeddings
- FAISS/Chroma/SQLite vector stores and runtime caches
- `evaluation/private/` and raw prompts/completions/traces
- PII-bearing logs, screenshots or notebook outputs

## Required Checks

Before commit or publication:

```bash
./scripts/validate_repo_safety.sh
git status --short
git check-ignore -v data/private/example.hwp evaluation/private/dev.jsonl .env
```

When Git is initialized, the safety script scans tracked and unignored untracked files and rejects
forced tracked `resources/**` independently of ignore rules. Before initialization it scans the working tree.

## Commit Policy

- Commit by a validated batch boundary.
- Do not commit a failing test state as a completed batch.
- Do not push unless the user asks or the active integration workflow explicitly requires it.
- Generated reports require a separate redaction review before tracking.
