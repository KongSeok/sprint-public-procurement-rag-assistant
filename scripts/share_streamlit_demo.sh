#!/usr/bin/env bash
set -euo pipefail

PORT="${BIDFIT_STREAMLIT_PORT:-8010}"

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared가 없습니다. 먼저 GCP VM에 cloudflared를 설치하세요." >&2
  exit 1
fi

echo "아래에 출력되는 https://...trycloudflare.com 주소를 팀원에게 공유하세요."
exec cloudflared tunnel --url "http://127.0.0.1:${PORT}"
