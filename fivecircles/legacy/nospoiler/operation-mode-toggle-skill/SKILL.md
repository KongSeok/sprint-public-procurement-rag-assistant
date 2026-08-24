---
name: operation-mode-toggle
description: Toggle operation mode ON/OFF for this repo. Use when user says "운영모드 온/오프", "operation mode on/off", "개발모드 on", or asks to keep dev auth backdoor out of PR by stashing it before push.
---

# operation-mode-toggle

## Purpose
- Keep local dev-auth backdoor convenient during development.
- Ensure PR/push safety by stashing backdoor files before review/merge.
- Prevent false-positive state where working tree changed but running gateway still uses old image.

## Commands
Run from repo root:

```bash
# 개발모드 ON: 스태시 적용 + api-gateway 재빌드/재기동 + 우회 검증
./scripts/operation-mode-on.sh

# 운영모드 OFF: 백도어 스태시 + api-gateway 재빌드/재기동 + 차단 검증
./scripts/operation-mode-off.sh
```

Optional (skip container sync):

```bash
./scripts/operation-mode-on.sh --no-runtime
./scripts/operation-mode-off.sh --no-runtime
```

## Runtime Verify Rule
- ON success condition:
  - same request without auth header => `401`
  - same request with `X-Dev-Bypass: true` => not `401`
- OFF success condition:
  - both plain and bypass request => `401`

Probe defaults:
- `GATEWAY_URL=http://localhost:8080`
- `PROBE_PATH=/api/wiki/v1/submissions?dramaId=10`

You can override with env vars if needed.

## Rules
- Before creating PR or pushing release-bound commits, run OFF first.
- ON/OFF only touches the following files:
  - `front/App.tsx`
  - `front/.env.example`
  - `front/vite.config.ts`
  - `services/api-gateway/src/main/java/com/nospoiler/apigateway/security/JwtAuthenticationFilter.java`
  - `services/api-gateway/src/main/resources/application.yml`
  - `services/api-gateway/src/main/resources/application-docker.yml`
  - `services/auth-service/src/main/java/com/nospoiler/authservice/security/JwtTokenProvider.java`
- Stash label is fixed: `dev-auth-backdoor-toggle`.

## Quick Verify
```bash
git stash list | head -n 5
git status -sb
docker compose -f infra/docker-compose.yml ps api-gateway
```

