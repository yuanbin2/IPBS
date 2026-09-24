@echo off
setlocal
cd /d "%~dp0"

set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" (
    echo [ERROR] .NET Framework compiler not found: %CSC%
    exit /b 1
)

echo Building 智能个人博客系统.exe ...
"%CSC%" -nologo -target:winexe -win32icon:icon.ico -optimize+ -out:"智能个人博客系统.exe" Launcher.cs
if errorlevel 1 exit /b 1

echo Done! 智能个人博客系统.exe built with the embedded app icon.
endlocal
