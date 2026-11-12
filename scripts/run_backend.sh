#!/usr/bin/env bash
# Start the FastAPI backend (run from repo root).
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r backend/requirements.txt
fi

# 0.4s per row makes the background import observable in the UI. Set
# IMPORT_ROW_DELAY=0 to make imports effectively instant.
export IMPORT_ROW_DELAY="${IMPORT_ROW_DELAY:-0.4}"
export APP_DATA_DIR="${APP_DATA_DIR:-$(pwd)/data}"

exec .venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
