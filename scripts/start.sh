#!/usr/bin/env bash
# 本地直跑后端（默认 SQLite，无需 MySQL / Redis）
#   bash scripts/start.sh
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

if [ ! -d ".venv" ]; then
  echo "[1/3] 创建虚拟环境 .venv ..."
  python3 -m venv .venv
fi

VENV_PY="$ROOT/.venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="$ROOT/.venv/Scripts/python.exe"

echo "[2/3] 安装后端依赖 ..."
"$VENV_PY" -m pip install -q -r backend/requirements.txt

echo "[3/3] 启动服务 http://localhost:8000  （Swagger: /docs，前端: /）"
cd backend
PYTHONPATH="$ROOT/backend" "$VENV_PY" -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
