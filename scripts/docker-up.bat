@echo off
chcp 65001 >nul
REM Docker Compose 一键部署
REM   scripts\docker-up.bat           完整版：MySQL 8 + Redis 7 + API(+前端)
REM   scripts\docker-up.bat lite      轻量版：单容器 + SQLite
REM   scripts\docker-up.bat down      停止并清理

setlocal
cd /d "%~dp0.."
set MODE=%1
if "%MODE%"=="" set MODE=full

if "%MODE%"=="lite" (
  docker compose -f docker-compose.lite.yml up -d --build
  docker compose -f docker-compose.lite.yml exec api python -m scripts.seed
  echo 完成：http://localhost:8000/
) else if "%MODE%"=="down" (
  docker compose down -v
  docker compose -f docker-compose.lite.yml down -v
) else (
  docker compose up -d --build
  echo 完成：http://localhost:8000/
)
endlocal
