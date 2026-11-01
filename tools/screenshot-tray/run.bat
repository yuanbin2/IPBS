@echo off
rem Start the tray screenshot tool with the project venv pythonw (no console window)
set "ROOT=%~dp0..\.."
if not exist "%ROOT%\.venv\Scripts\pythonw.exe" (
    echo [BlogScreenshotTool] Project venv not found: "%ROOT%\.venv\Scripts\pythonw.exe"
    pause
    exit /b 1
)
start "BlogScreenshotTool" "%ROOT%\.venv\Scripts\pythonw.exe" "%~dp0main.py"
