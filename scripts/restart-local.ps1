param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
$managePy = Join-Path $projectRoot 'backend\manage.py'
$viteJs = Join-Path $projectRoot 'frontend\node_modules\vite\bin\vite.js'
$frontendDir = Join-Path $projectRoot 'frontend'
$runDir = Join-Path $projectRoot '.run'
$backendPort = 8001
$frontendPort = 5174

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
$env:VITE_API_BASE_URL = ''

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

# Wait for the recorded processes to release their preferred ports. When an
# untracked process keeps holding a port, fall back to the next free port in
# the allowed range instead of failing.
function Wait-PortReleased([int]$port) {
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if (Test-LocalPortAvailable $port) { return $true }
        Start-Sleep -Milliseconds 250
    }
    return (Test-LocalPortAvailable $port)
}

function Select-FreePort([int]$preferred, [int]$max) {
    for ($p = $preferred; $p -le $max; $p++) {
        if (Test-LocalPortAvailable $p) { return $p }
    }
    throw "No free port found in range $preferred..$max."
}

if (-not (Wait-PortReleased 8001)) {
    $backendPort = Select-FreePort 8002 8011
    Write-Warning "Port 8001 is still occupied by another process; backend will use port $backendPort instead."
}
if (-not (Wait-PortReleased 5174)) {
    $frontendPort = Select-FreePort 5175 5184
    Write-Warning "Port 5174 is still occupied by another process; frontend will use port $frontendPort instead."
}

$backendUrl = "http://127.0.0.1:$backendPort"
$frontendUrl = "http://127.0.0.1:$frontendPort"
$env:VITE_API_PROXY_TARGET = $backendUrl
$env:VITE_PORT = "$frontendPort"

# PowerShell 5.1's Start-Process throws a duplicate-key error when the
# environment block contains case-variant twins (e.g. http_proxy/HTTP_PROXY).
# Normalize them: delete every variant, then keep a single uppercase entry
# with the original value so proxy settings are preserved.
foreach ($name in @('http_proxy', 'https_proxy', 'no_proxy')) {
    $value = [Environment]::GetEnvironmentVariable($name, 'Process')
    if ($null -eq $value) { continue }
    [Environment]::SetEnvironmentVariable($name, $null, 'Process')
    [Environment]::SetEnvironmentVariable($name, $null, 'Process')
    [Environment]::SetEnvironmentVariable($name.ToUpperInvariant(), $value, 'Process')
}

$backendProcess = $null
$frontendProcess = $null
try {
    $backendProcess = Start-Process -FilePath $pythonExe -ArgumentList @($managePy, 'runserver', "127.0.0.1:$backendPort", '--noreload') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runDir 'backend.stdout.log') -RedirectStandardError (Join-Path $runDir 'backend.stderr.log')
    @{ id = $backendProcess.Id; startedUtcTicks = $backendProcess.StartTime.ToUniversalTime().Ticks } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runDir 'backend.pid.json')
    $frontendProcess = Start-Process -FilePath $nodeExe -ArgumentList @($viteJs, '--host', '127.0.0.1', '--port', "$frontendPort", '--strictPort') -WorkingDirectory $frontendDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runDir 'frontend.stdout.log') -RedirectStandardError (Join-Path $runDir 'frontend.stderr.log')
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
