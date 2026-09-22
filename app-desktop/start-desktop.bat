@echo off
title Knowledge Agent Desktop
echo ========================================
echo   Knowledge Agent - Desktop Mode
echo ========================================
echo.

:: Start backend
echo [1/3] Starting backend server...
cd /d "%~dp0..\backend"
start /b cmd /c "python manage.py runserver 127.0.0.1:8000"
timeout /t 3 /nobreak >nul

:: Start frontend
echo [2/3] Starting frontend dev server...
cd /d "%~dp0..\frontend"
start /b cmd /c "npm run dev"
timeout /t 5 /nobreak >nul

:: Open in Edge app mode
echo [3/3] Opening desktop window...
start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --app=http://127.0.0.1:5173 --window-size=1400,900 --window-position=100,100 --user-data-dir="%~dp0.edge-profile"

echo.
echo ========================================
echo   Desktop app is running!
echo   Close this window to stop all servers.
echo ========================================
echo.
pause

:: Cleanup on exit
taskkill /F /IM python.exe >nul 2>&1
taskkill /F /IM node.exe >nul 2>&1