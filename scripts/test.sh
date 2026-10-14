#!/usr/bin/env bash
# 运行后端单元测试（临时 SQLite，不污染本地数据）
#   bash scripts/test.sh
#   bash scripts/test.sh -k idempotency
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

VENV_PY="$ROOT/.venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="$ROOT/.venv/Scripts/python.exe"

cd backend
PYTHONPATH="$ROOT/backend" "$VENV_PY" -m pytest "$@"
