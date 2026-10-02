param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
$managePy = Join-Path $projectRoot 'backend\manage.py'
$viteJs = Join-Path $projectRoot 'frontend\node_modules\vite\bin\vite.js'
$frontendDir = Join-Path $projectRoot 'frontend'
$runDir = Join-Path $projectRoot '.run'
$backendUrl = 'http://127.0.0.1:8001'
$frontendUrl = 'http://127.0.0.1:5174'

if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf) -or
    -not (Test-Path -LiteralPath $viteJs -PathType Leaf)) {
    throw 'Missing local Python or frontend dependencies. Run start.bat once first.'
}
$nodeExe = (Get-Command node.exe -ErrorAction Stop).Source
New-Item -ItemType Directory -Path $runDir -Force | Out-Null

# Local mode deliberately uses the existing backend/db.sqlite3, even if a
# DATABASE_URL is present in the parent shell or .env file.
$env:BLOG_LOCAL_MODE = 'true'
$env:DJANGO_SETTINGS_MODULE = 'config.settings'
$env:LANGSMITH_TRACING = 'false'
$env:LANGCHAIN_TRACING_V2 = 'false'
$env:VITE_API_PROXY_TARGET = $backendUrl
$env:VITE_API_BASE_URL = ''
$env:VITE_PORT = '5174'

Write-Host "Preparing local database: $projectRoot\backend\db.sqlite3"
& $pythonExe $managePy migrate --noinput
if ($LASTEXITCODE -ne 0) { throw 'Database migration failed; servers were not restarted.' }
& $pythonExe $managePy check
if ($LASTEXITCODE -ne 0) { throw 'Backend check failed; servers were not restarted.' }

# A PID from a previous run is trusted only when its executable and start
# time match the recorded process. This avoids stopping a reused PID.
function Stop-RecordedProcess([string]$name, [string]$expectedPath) {
    $recordPath = Join-Path $runDir "$name.pid.json"
    if (-not (Test-Path -LiteralPath $recordPath)) { return }
    try {
        $record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
        $existing = Get-Process -Id ([int]$record.id) -ErrorAction Stop
        if ($existing.Path -ieq $expectedPath -and
            $existing.StartTime.ToUniversalTime().Ticks -eq [long]$record.startedUtcTicks) {
            Stop-Process -Id $existing.Id -Force
        } else {
            Write-Warning "Ignoring stale $name PID record."
        }
    } catch {
        Write-Warning "Could not verify previous $name process; leaving it untouched."
    }
    Remove-Item -LiteralPath $recordPath -Force
}

function Test-LocalPortAvailable([int]$port) {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $port)
    try {
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        $listener.Stop()
    }
}

Stop-RecordedProcess 'backend' $pythonExe
Stop-RecordedProcess 'frontend' $nodeExe
foreach ($port in @(8001, 5174)) {
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if (Test-LocalPortAvailable $port) { break }
        Start-Sleep -Milliseconds 250
    }
    if (-not (Test-LocalPortAvailable $port)) {
        throw "Port $port is occupied by another process; no replacement server was started."
    }
}

$backendProcess = $null
$frontendProcess = $null
try {
    $backendProcess = Start-Process -FilePath $pythonExe -ArgumentList @($managePy, 'runserver', '127.0.0.1:8001', '--noreload') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runDir 'backend.stdout.log') -RedirectStandardError (Join-Path $runDir 'backend.stderr.log')
    @{ id = $backendProcess.Id; startedUtcTicks = $backendProcess.StartTime.ToUniversalTime().Ticks } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runDir 'backend.pid.json')
    $frontendProcess = Start-Process -FilePath $nodeExe -ArgumentList @($viteJs, '--host', '127.0.0.1', '--port', '5174', '--strictPort') -WorkingDirectory $frontendDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runDir 'frontend.stdout.log') -RedirectStandardError (Join-Path $runDir 'frontend.stderr.log')
    @{ id = $frontendProcess.Id; startedUtcTicks = $frontendProcess.StartTime.ToUniversalTime().Ticks } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runDir 'frontend.pid.json')

    $ready = $false
    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        try {
            $backend = Invoke-WebRequest "$backendUrl/api/health/" -UseBasicParsing -TimeoutSec 2
            $frontend = Invoke-WebRequest "$frontendUrl/blog" -UseBasicParsing -TimeoutSec 2
            $proxied = Invoke-WebRequest "$frontendUrl/api/health/" -UseBasicParsing -TimeoutSec 2
            if ($backend.StatusCode -eq 200 -and $frontend.StatusCode -eq 200 -and $proxied.StatusCode -eq 200) {
                $ready = $true
                break
            }
        } catch { }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) {
        throw "Startup health checks failed. See $runDir\backend.stderr.log and frontend.stderr.log."
    }
} catch {
    if ($backendProcess) { Stop-Process -Id $backendProcess.Id -Force -ErrorAction SilentlyContinue }
    if ($frontendProcess) { Stop-Process -Id $frontendProcess.Id -Force -ErrorAction SilentlyContinue }
    Remove-Item -LiteralPath (Join-Path $runDir 'backend.pid.json'), (Join-Path $runDir 'frontend.pid.json') -Force -ErrorAction SilentlyContinue
    throw
}

Write-Host "Backend:  $backendUrl (existing local SQLite database)"
Write-Host "Frontend: $frontendUrl/blog"
Write-Host "Register: $frontendUrl/login"
if (-not $NoBrowser) { Start-Process "$frontendUrl/blog" }
