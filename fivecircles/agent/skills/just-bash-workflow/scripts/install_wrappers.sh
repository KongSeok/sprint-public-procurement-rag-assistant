#!/usr/bin/env bash
set -euo pipefail

ROOT="."
while [[ $# -gt 0 ]]; do
  case "$1" in
    --root)
      ROOT="$2"
      shift 2
      ;;
    *)
      echo "Unknown arg: $1" >&2
      echo "Usage: install_wrappers.sh [--root <path>]" >&2
      exit 2
      ;;
  esac
done

ROOT="$(cd "$ROOT" && pwd)"
mkdir -p "${ROOT}/scripts"

cat > "${ROOT}/scripts/jb" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

# Convenience wrapper for just-bash:
# - Pins --root to this repo.
# - Defaults to read-only (just-bash default).

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# If user already provided --root, respect it.
if command -v rg >/dev/null 2>&1; then
  if printf '%s\n' "$@" | rg -q -- '--root'; then
    exec just-bash "$@"
  fi
else
  if printf '%s\n' "$@" | grep -q -- '--root'; then
    exec just-bash "$@"
  fi
fi

exec just-bash --root "$ROOT" "$@"
EOF

cat > "${ROOT}/scripts/jbw" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

# Same as scripts/jb, but enables in-memory writes (no host FS writes).

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if command -v rg >/dev/null 2>&1; then
  if printf '%s\n' "$@" | rg -q -- '--root'; then
    exec just-bash --allow-write "$@"
  fi
else
  if printf '%s\n' "$@" | grep -q -- '--root'; then
    exec just-bash --allow-write "$@"
  fi
fi

exec just-bash --allow-write --root "$ROOT" "$@"
EOF

chmod +x "${ROOT}/scripts/jb" "${ROOT}/scripts/jbw"

echo "Installed:"
echo "  ${ROOT}/scripts/jb"
echo "  ${ROOT}/scripts/jbw"

