@echo off
chcp 65001 >nul
REM 运行后端单元测试（临时 SQLite，不污染本地数据）
REM   scripts\test.bat
REM   scripts\test.bat -k idempotency

setlocal
cd /d "%~dp0.."
set ROOT=%CD%
cd backend
set PYTHONPATH=%ROOT%\backend
"..\.venv\Scripts\python.exe" -m pytest %*
endlocal
