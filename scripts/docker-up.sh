#!/usr/bin/env bash
# Docker Compose 一键部署
#   bash scripts/docker-up.sh            # 完整版：MySQL 8 + Redis 7 + API(+前端)
#   bash scripts/docker-up.sh lite       # 轻量版：单容器 + SQLite（无需 MySQL/Redis）
#   bash scripts/docker-up.sh down       # 停止并清理
set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:-full}"

case "$MODE" in
  lite)
    echo "==> 轻量模式：docker compose -f docker-compose.lite.yml up -d --build"
    docker compose -f docker-compose.lite.yml up -d --build
    echo "==> 写入示例数据 ..."
    docker compose -f docker-compose.lite.yml exec api python -m scripts.seed
    echo "==> 完成：http://localhost:8000/"
    ;;
  down)
    docker compose down -v
    docker compose -f docker-compose.lite.yml down -v
    ;;
  full|*)
    echo "==> 完整模式：docker compose up -d --build"
    docker compose up -d --build
    echo "==> 完成：http://localhost:8000/ （示例数据由 seeder 服务自动写入）"
    ;;
esac
