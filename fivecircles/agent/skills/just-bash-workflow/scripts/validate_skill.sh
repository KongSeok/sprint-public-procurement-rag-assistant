#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_MD="${ROOT}/SKILL.md"

fail() {
  echo "[FAIL] $*" >&2
  exit 1
}

[[ -f "$SKILL_MD" ]] || fail "Missing SKILL.md at: $SKILL_MD"

head20="$(sed -n '1,20p' "$SKILL_MD")"
printf '%s\n' "$head20" | rg -q "^---$" || fail "SKILL.md must start with YAML frontmatter delimiter ---"
printf '%s\n' "$head20" | rg -q "^name:\\s*[^\\[]+" || fail "Frontmatter must include name:"
printf '%s\n' "$head20" | rg -q "^description:\\s*[^\\[]+" || fail "Frontmatter must include description:"

# Ensure frontmatter closes near the top (avoid huge accidental blocks).
delims="$(rg -n "^---$" "$SKILL_MD" | head -n 3 | wc -l | tr -d '[:space:]')"
[[ "$delims" == "2" ]] || fail "Frontmatter must have opening and closing --- near the top"

echo "[OK] Basic SKILL.md frontmatter checks passed: $SKILL_MD"
