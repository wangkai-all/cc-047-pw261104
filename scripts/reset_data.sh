#!/usr/bin/env bash
# Wipe all runtime data (sqlite db + stored upload/error files) for a clean demo.
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf ./data
echo "已清理 ./data，下次启动后端会自动重建空数据库。"
