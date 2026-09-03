#!/usr/bin/env bash
set -euo pipefail
# Existing weights: verify offline without rewriting. New root: require --download.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VISUAL_MODEL_ROOT="${MIDPROJECTRAG_VISUAL_MODEL_ROOT:-$PROJECT_ROOT/resources/data_refined/private/models/pp-structure-v3}"
VISUAL_PYTHON="${MIDPROJECTRAG_VISUAL_PYTHON:-$PROJECT_ROOT/.venv/bin/python}"
export PYTHONPATH="$PROJECT_ROOT/src"
exec "$VISUAL_PYTHON" -m midprojectrag.ingest.visual_model_manifest --root "$VISUAL_MODEL_ROOT" "$@"
