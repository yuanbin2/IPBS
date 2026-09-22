@echo off
echo ========================================
echo Knowledge Agent Desktop - Development
echo ========================================
echo.

echo [1/3] Checking Node.js installation...
node --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js is not installed or not in PATH
    echo Please install Node.js from https://nodejs.org/
    pause
    exit /b 1
)
echo Node.js found:
node --version

echo.
echo [2/3] Installing dependencies...
call npm install
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)

echo.
echo [3/3] Starting development server...
echo.
echo The desktop app will open automatically.
echo Press Ctrl+C to stop the development server.
echo.
call npm run dev
