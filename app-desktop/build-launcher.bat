@echo off
setlocal
cd /d "%~dp0"

set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" (
    echo [ERROR] .NET Framework compiler not found: %CSC%
    exit /b 1
)

echo Building Knowledge Agent.exe ...
"%CSC%" -nologo -target:winexe -win32icon:icon.ico -optimize+ -out:"Knowledge Agent.exe" Launcher.cs
if errorlevel 1 exit /b 1

echo Done! Knowledge Agent.exe built with the embedded app icon.
endlocal
