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
  echo [1/5] Creating the Python virtual environment...
  python -m venv .venv
  if errorlevel 1 exit /b 1
)

echo [2/5] Installing backend dependencies...
".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
if errorlevel 1 exit /b 1

echo [3/5] Installing and building frontend dependencies...
call npm --prefix frontend install --no-audit --no-fund
if errorlevel 1 exit /b 1
call npm --prefix frontend run build
if errorlevel 1 exit /b 1

set "BLOG_LOCAL_MODE=true"
set "LANGSMITH_TRACING=false"
set "LANGCHAIN_TRACING_V2=false"

echo [4/5] Preparing the local SQLite database...
".venv\Scripts\python.exe" backend\manage.py migrate --noinput
if errorlevel 1 exit /b 1

echo [5/5] Starting the project...
echo Open http://127.0.0.1:8000/ in your browser.
".venv\Scripts\python.exe" backend\manage.py runserver 127.0.0.1:8000 --noreload

endlocal
