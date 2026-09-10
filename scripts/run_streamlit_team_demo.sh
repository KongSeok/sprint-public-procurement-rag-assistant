#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${BIDFIT_REPO_DIR:-$HOME/sprint-public-procurement-rag-assistant}"
VENV_DIR="${BIDFIT_VENV_DIR:-$HOME/myenv}"
PORT="${BIDFIT_STREAMLIT_PORT:-8010}"

cd "$REPO_DIR"
source "$VENV_DIR/bin/activate"
exec streamlit run streamlit_demo/app.py \
  --server.address 127.0.0.1 \
  --server.port "$PORT" \
  --server.headless true
