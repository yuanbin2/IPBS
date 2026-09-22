@echo off
echo ========================================
echo Knowledge Agent Desktop - Build
echo ========================================
echo.

echo [1/4] Checking Node.js installation...
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
echo [2/4] Installing dependencies...
call npm install
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)

echo.
echo [3/4] Building application...
call npm run build
if errorlevel 1 (
    echo ERROR: Build failed
    pause
    exit /b 1
)

echo.
echo [4/4] Packaging for Windows...
call npm run package:win
if errorlevel 1 (
    echo ERROR: Packaging failed
    pause
    exit /b 1
)

echo.
echo ========================================
echo Build completed successfully!
echo.
echo The installer is located in the 'release' folder.
echo ========================================
pause
