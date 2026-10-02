@echo off
setlocal
rem Some shells pass both PATH and Path. Start-Process cannot copy that
rem duplicate environment, so keep one canonical PATH before launching it.
set "BLOG_RESTART_PATH=%PATH%"
set "PATH="
set "Path="
set "PATH=%BLOG_RESTART_PATH%"
set "BLOG_RESTART_PATH="
rem Restart the local Django API and the Vue frontend from this checkout.
rem The PowerShell implementation checks port ownership before stopping anything.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\restart-local.ps1" %*
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
  echo.
  echo Restart failed. See the error above; existing unrelated services were left alone.
  pause
)
exit /b %RESULT%
