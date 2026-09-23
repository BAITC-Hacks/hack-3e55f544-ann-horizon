@echo off
setlocal
set "PYTHONUTF8=1"
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0setup_env.py" %*
) else (
    python "%~dp0setup_env.py" %*
)
exit /b %errorlevel%
