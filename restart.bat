@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set BACKEND_PORT=8001
set FRONTEND_PORT=5174

echo ============================================================
echo   智能个人博客系统 - 一键重启
echo   Backend : http://127.0.0.1:%BACKEND_PORT%
echo   Frontend: http://127.0.0.1:%FRONTEND_PORT%
echo ============================================================
echo.

echo [1/5] Stopping old dev servers ...
REM 清理目标端口及旧端口（5173/8888）上的残留进程
for %%P in (%BACKEND_PORT% %FRONTEND_PORT% 5173 8888) do (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr /r ":%%P .*LISTENING"') do (
        taskkill /f /pid %%a >nul 2>&1 && echo   - killed PID %%a on port %%P
    )
)
timeout /t 2 >nul
echo.

echo [2/5] Starting backend on 127.0.0.1:%BACKEND_PORT% ...
set BLOG_LOCAL_MODE=true
set LANGSMITH_TRACING=false
set LANGCHAIN_TRACING_V2=false
start "Blog Backend :%BACKEND_PORT%" cmd /c ".venv\Scripts\python.exe backend\manage.py runserver 127.0.0.1:%BACKEND_PORT% --noreload"
echo.

echo [3/5] Starting frontend on 127.0.0.1:%FRONTEND_PORT% ...
set VITE_API_PROXY_TARGET=http://127.0.0.1:%BACKEND_PORT%
set VITE_PORT=%FRONTEND_PORT%
start "Blog Frontend :%FRONTEND_PORT%" cmd /c "npm --prefix frontend run dev"
echo.

echo [4/5] Waiting for services to come up ...
timeout /t 10 >nul

echo [5/5] Health check ...
set BACKEND_OK=0
set FRONTEND_OK=0
curl -s -o nul -w "   backend  /api/health/ -> %%{http_code}\n" http://127.0.0.1:%BACKEND_PORT%/api/health/ | findstr 200 >nul && set BACKEND_OK=1
curl -s -o nul -w "   frontend /           -> %%{http_code}\n" http://127.0.0.1:%FRONTEND_PORT%/ | findstr 200 >nul && set FRONTEND_OK=1
echo.
if "%BACKEND_OK%"=="1" if "%FRONTEND_OK%"=="1" (
    echo Done! Open http://127.0.0.1:%FRONTEND_PORT% in your browser.
) else (
    echo WARNING: a service did not answer yet - check the two new windows.
    echo You can still open http://127.0.0.1:%FRONTEND_PORT% once they are ready.
)
echo.
pause
