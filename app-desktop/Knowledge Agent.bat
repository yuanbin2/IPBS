@echo off
title Knowledge Agent

:: Check if frontend is already running
curl -s http://127.0.0.1:5173 >nul 2>&1
if %errorlevel%==0 (
    :: Frontend already running, just open the window
    start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --app=http://127.0.0.1:5173 --window-size=1400,900 --window-position=100,100 --user-data-dir="%~dp0.edge-profile"
    exit
)

:: Start backend
cd /d "%~dp0..\backend"
start /b cmd /c "python manage.py runserver 127.0.0.1:8000 >nul 2>&1"

:: Start frontend
cd /d "%~dp0..\frontend"
start /b cmd /c "npm run dev >nul 2>&1"

:: Wait for frontend to be ready
:wait_loop
timeout /t 2 /nobreak >nul
curl -s http://127.0.0.1:5173 >nul 2>&1
if %errorlevel% neq 0 goto wait_loop

:: Open the app window
start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --app=http://127.0.0.1:5173 --window-size=1400,900 --window-position=100,100 --user-data-dir="%~dp0.edge-profile"
