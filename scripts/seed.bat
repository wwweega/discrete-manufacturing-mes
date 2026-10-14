@echo off
chcp 65001 >nul
REM 初始化示例数据（幂等；加 --reset 可删库重建）
REM   scripts\seed.bat
REM   scripts\seed.bat --reset

setlocal
cd /d "%~dp0.."
set ROOT=%CD%
cd backend
set PYTHONPATH=%ROOT%\backend
"..\.venv\Scripts\python.exe" -m scripts.seed %*
endlocal
