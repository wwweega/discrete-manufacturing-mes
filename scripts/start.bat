@echo off
chcp 65001 >nul
REM 本地直跑后端（Windows，默认 SQLite，无需 MySQL / Redis）
REM   scripts\start.bat

setlocal
cd /d "%~dp0.."
set ROOT=%CD%

if not exist ".venv" (
  echo [1/3] 创建虚拟环境 .venv ...
  python -m venv .venv
)

echo [2/3] 安装后端依赖 ...
".venv\Scripts\python.exe" -m pip install -q -r backend\requirements.txt

echo [3/3] 启动服务 http://localhost:8000  (Swagger: /docs)
cd backend
set PYTHONPATH=%ROOT%\backend
"..\venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
endlocal
