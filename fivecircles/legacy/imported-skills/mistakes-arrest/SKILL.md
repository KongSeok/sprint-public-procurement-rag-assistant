---
name: mistakes-arrest
description: Guardrail workflow to prevent API path mismatches after routing mistakes. Use when the user says "arrest", asks for alignment checks, or reports base URL/path mismatches across controllers, api-contract, or gateway.
---

# Mistakes Arrest

## Overview
Run a quick alignment sweep across controllers, specs, and gateway routes to fix path drift and prevent recurrence.

## Workflow (API Path Alignment)
1) Open guardrail notes:
   - `fivecircles/agent/mistakes-arrest.md`
2) Scan controller paths:
   - `rg -n "@RequestMapping|@GetMapping|@PostMapping" services/**/controller/*.java`
3) Scan specs:
   - `rg -n "Base URL|GET /|POST /" fivecircles/architecture/specs/api-contract.md`
   - `rg -n "GET /|POST /" fivecircles/architecture/specs/event-v2-api.md`
4) Scan gateway routes:
   - `services/api-gateway/src/main/resources/application-docker.yml`
5) Fix order:
   - controllers -> specs -> gateway
6) Scope guard:
   - If a file is outside my scope (e.g., drama/character), reset it to `origin/develop`.
7) Verify:
   - Run server curl tests for representative v1/v2 endpoints.
8) Log:
   - `fivecircles/work/update.md` and, when relevant, `fivecircles/scoring/optimization.md`.
