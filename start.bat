@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python 3.12 or newer was not found in PATH.
  echo Install Python from https://www.python.org/downloads/ and enable "Add Python to PATH".
  exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Node.js and npm were not found in PATH.
  echo Install Node.js 20 or newer from https://nodejs.org/.
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/4] Creating the Python virtual environment...
  python -m venv .venv
  if errorlevel 1 exit /b 1
)

echo [2/4] Installing backend dependencies...
".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
if errorlevel 1 exit /b 1

echo [3/4] Installing and building frontend dependencies...
call npm --prefix frontend install --no-audit --no-fund
if errorlevel 1 exit /b 1
call npm --prefix frontend run build
if errorlevel 1 exit /b 1

echo [4/4] Starting backend and frontend...
rem restart.bat delegates to scripts\restart-local.ps1, which runs migrations,
rem starts both servers with automatic port fallback and health checks.
call "%~dp0restart.bat" %*
set "RESULT=%ERRORLEVEL%"
endlocal & exit /b %RESULT%
