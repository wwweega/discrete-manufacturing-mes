#!/usr/bin/env bash
# 初始化示例数据（幂等；加 --reset 可删库重建）
#   bash scripts/seed.sh
#   bash scripts/seed.sh --reset
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

VENV_PY="$ROOT/.venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="$ROOT/.venv/Scripts/python.exe"

cd backend
PYTHONPATH="$ROOT/backend" "$VENV_PY" -m scripts.seed "$@"
