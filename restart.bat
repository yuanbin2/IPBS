@echo off
chcp 65001 >nul
cd /d "%~dp0"

set BACKEND_PORT=8001
set FRONTEND_PORT=5174
set BACKEND_URL=http://127.0.0.1:%BACKEND_PORT%
set FRONTEND_URL=http://127.0.0.1:%FRONTEND_PORT%

echo ============================================================
echo   Smart Personal Blog - one-click restart
echo   Backend : %BACKEND_URL%
echo   Frontend: %FRONTEND_URL%
echo ============================================================
echo.

echo [1/4] Stopping old dev servers ...
REM 注意：PowerShell 命令内不能出现双引号（cmd 会吃掉），全部用单引号
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort %BACKEND_PORT%,%FRONTEND_PORT%,5173,8888,8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }"
ping -n 3 127.0.0.1 >nul
echo.

echo [2/4] Starting backend on %BACKEND_URL% ...
set "BLOG_LOCAL_MODE=true"
set "LANGSMITH_TRACING=false"
set "LANGCHAIN_TRACING_V2=false"
start "Blog Backend" ".venv\Scripts\python.exe" backend\manage.py runserver 127.0.0.1:%BACKEND_PORT% --noreload
echo.

echo [3/4] Starting frontend on %FRONTEND_URL% ...
set "VITE_API_PROXY_TARGET=%BACKEND_URL%"
set "VITE_PORT=%FRONTEND_PORT%"
start "Blog Frontend" npm --prefix frontend run dev
echo.

echo [4/4] Health check (up to 45s) ...
set /a TRIES=0
:wait_loop
ping -n 4 127.0.0.1 >nul
set /a TRIES+=1
curl -s -o nul %BACKEND_URL%/api/health/ >nul 2>&1
if errorlevel 1 (
    if !TRIES! LSS 15 goto wait_loop
)
curl -s -o nul -w "   backend  -^> %%{http_code}\n" %BACKEND_URL%/api/health/
curl -s -o nul -w "   frontend -^> %%{http_code}\n" %FRONTEND_URL%/
echo.
echo Done! Open %FRONTEND_URL% in your browser.
echo.
pause
