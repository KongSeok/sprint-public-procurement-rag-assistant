# Skill: Deploy Frontend (Local Dev Server)

## Purpose
Start the Vite dev server for the frontend with network access enabled, so it can be accessed from both localhost and mobile devices on the same network.

## Usage
Execute when the user says "프론트 띄워", "deploy front", "dev 서버", or `/deploy-front`.

## Dynamic Inputs

- `PROJECT_ROOT`: current repository root, resolved with `git rev-parse --show-toplevel` when possible, otherwise the current working directory.
- `FRONTEND_DIR`: detected frontend directory. Prefer `front/`, `frontend/`, `apps/web/`, `apps/frontend/`, then the repo root when it contains `package.json`.
- `DEV_PORT`: default `3000`, unless the user specifies another port or the project config already uses one.
- `NETWORK_HOST`: default `0.0.0.0` for LAN/mobile access.
- `STOP_CONTAINER`: optional. Only stop a Docker container when the current project has a known frontend container for the selected port.

## Protocol Steps

// turbo-all

1. **Resolve project paths**
   ```bash
   PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
   for candidate in front frontend apps/web apps/frontend .; do
     if [ -f "$PROJECT_ROOT/$candidate/package.json" ]; then
       FRONTEND_DIR="$PROJECT_ROOT/$candidate"
       break
     fi
   done
   : "${FRONTEND_DIR:=$PROJECT_ROOT}"
   : "${DEV_PORT:=3000}"
   ```

2. **Free the selected port only when needed**
   ```bash
   lsof -ti :"$DEV_PORT" | xargs kill -9 2>/dev/null || true
   ```

3. **Start dev server with network access**
   ```bash
   cd "$FRONTEND_DIR" && npm run dev -- --host "$NETWORK_HOST" --port "$DEV_PORT"
   ```

4. **Verify**
   - Confirm output shows a localhost URL and, when available, a network URL.
   - Report the resolved `FRONTEND_DIR`, local URL, and network/mobile URL to the user.

## Notes
- `--host 0.0.0.0` opens the server to all network interfaces (required for phone access).
- Phone must be on the same Wi-Fi/network as the dev machine.
- If a stable VPN/Tailscale IP is needed, derive it at runtime with `tailscale ip -4` or ask the user for the target address.
