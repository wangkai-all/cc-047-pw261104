#!/usr/bin/env bash
# Start the Vite frontend dev server (run from repo root).
set -euo pipefail
cd "$(dirname "$0")/../frontend"

if [ ! -d node_modules ]; then
  npm install --cache /tmp/npm-cache-wsdemo
fi

exec npm run dev -- --host 127.0.0.1
