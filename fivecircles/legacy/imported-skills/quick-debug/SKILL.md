---
name: quick-debug
description: Fast error resolution by searching mistakes-arrest and learn-from-log first. Use when the user says "빠른 디버깅", "quick debug", or when encountering errors.
---

# Quick Debug

This skill prioritizes known solutions before investigating new errors.

## When to Use

- When encountering errors or bugs
- When the user says "빠른 디버깅해" or "quick debug"
- Before diving into deep debugging

## Protocol

1. Check `fivecircles/agent/mistakes-arrest.md` for guardrails
2. Search `fivecircles/test/learn-from-log.md` for similar issues
3. Search `fivecircles/test/errorlogs/` for past solutions
4. If no match found, proceed with standard debugging
5. Document new solutions in learn-from-log

See the full protocol in `../protocol_quick_debug.md`.
