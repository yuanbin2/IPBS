# Knowledge Agent Desktop Launcher
# Starts backend, frontend, and opens Edge in app mode

$ErrorActionPreference = "Continue"
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $projectRoot) { $projectRoot = "E:\Desktop\MyProject\Blog-fixed-20260727\Blog" }

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Knowledge Agent - Desktop Mode" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Start backend
Write-Host "[1/3] Starting backend server..." -ForegroundColor Yellow
$backendDir = Join-Path $projectRoot "backend"
$backendProcess = Start-Process -FilePath "python" -ArgumentList "manage.py", "runserver", "127.0.0.1:8000" -WorkingDirectory $backendDir -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 3

# Start frontend
Write-Host "[2/3] Starting frontend dev server..." -ForegroundColor Yellow
$frontendDir = Join-Path $projectRoot "frontend"
$frontendProcess = Start-Process -FilePath "npm" -ArgumentList "run", "dev" -WorkingDirectory $frontendDir -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 5

# Open Edge in app mode
Write-Host "[3/3] Opening desktop window..." -ForegroundColor Yellow
$edgePath = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$edgeProfile = Join-Path $PSScriptRoot ".edge-profile"
$edgeProcess = Start-Process -FilePath $edgePath -ArgumentList "--app=http://127.0.0.1:5173", "--window-size=1400,900", "--window-position=100,100", "--user-data-dir=$edgeProfile" -PassThru

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Desktop app is running!" -ForegroundColor Green
Write-Host "  Press Ctrl+C to stop all servers." -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

# Wait for Edge to close
try {
    $edgeProcess.WaitForExit()
} finally {
    Write-Host ""
    Write-Host "Stopping servers..." -ForegroundColor Yellow
    Stop-Process -Id $backendProcess.Id -Force -ErrorAction SilentlyContinue
    Stop-Process -Id $frontendProcess.Id -Force -ErrorAction SilentlyContinue
    Write-Host "Done!" -ForegroundColor Green
}