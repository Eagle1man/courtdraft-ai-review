<#
.SYNOPSIS
  Demo stand: build the case data and open the UI on it.

.DESCRIPTION
  Prepares a clean stand for showing the product and starts the backend
  on the demo database, so the UI shows one prepared case with a real
  draft instead of an empty list.

  The stand database is separate from the working one on purpose: the
  working database accumulates leftovers from manual checks, and a
  customer demo must not show them.

  NOTE: this file is ASCII-only. Windows PowerShell 5.1 reads .ps1
  without BOM as ANSI and breaks on Cyrillic parsing.

.PARAMETER Rebuild
  Rebuild the stand from scratch even if it already exists.

.PARAMETER Port
  Port for the backend. Default 8000.

.EXAMPLE
  powershell -File scripts\start-demo.ps1 -Rebuild
#>

param(
    [switch]$Rebuild,
    [int]$Port = 8000
)

. (Join-Path $PSScriptRoot 'lib.ps1')

$standDb = Join-Path $script:ProjectRoot 'data\demo\output\demo.db'

function Get-DemoProvider {
    $envFile = Join-Path $script:ProjectRoot '.env'
    return Get-EnvFileValue -Path $envFile -Name 'LLM_PROVIDER' -Default 'mock'
}

Write-Step 'CourtDraft AI - demo stand'

if (-not (Test-Path $script:VenvPython)) {
    Write-Err 'venv not found. Run .\scripts\install.ps1 first.'
    exit 1
}

$needBuild = $Rebuild -or -not (Test-Path $standDb)
if ($needBuild) {
    $provider = Get-DemoProvider
    Write-Step "Building demo case (provider: $provider)"
    Push-Location $script:BackendDir
    try {
        & $script:VenvPython 'scripts\demo.py' '--provider' $provider `
            '--log' '..\data\demo\demo_stand.log'
        if ($LASTEXITCODE -ne 0) {
            Write-Err "demo.py failed with exit code $LASTEXITCODE"
            exit 1
        }
    } finally {
        Pop-Location
    }
} else {
    Write-Info 'Demo database exists, reusing it (use -Rebuild to rebuild).'
}

if (Test-PortInUse $Port) {
    Write-Err "Port $Port is already in use. Stop it with .\scripts\stop.ps1 first."
    Write-Err 'A demo stand must be shown on its own database, not on a running copy.'
    exit 1
}

Write-Step 'Starting backend on the demo database'
$logDir = Join-Path $script:BackendDir '.logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$outLog = Join-Path $logDir 'demo.out.log'
$errLog = Join-Path $logDir 'demo.err.log'

# The child process inherits this environment, and only this process:
# setting it here does not change the interactive shell of the operator.
#
# The path is absolute on purpose. A relative SQLite URL is resolved by
# SQLAlchemy against the CURRENT WORKING DIRECTORY, and the backend is
# started from backend\, so "./data/demo/output/demo.db" pointed at
# backend\data\demo\output\ and every query failed with
# "unable to open database file" while the server itself looked healthy.
$env:DATABASE_URL = 'sqlite+aiosqlite:///' + $standDb.Replace('\', '/')

Start-Process -FilePath $script:VenvPython `
    -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', $Port `
    -WorkingDirectory $script:BackendDir `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -WindowStyle Hidden

$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    if (Invoke-Json -Url "http://127.0.0.1:$Port/api/health" -TimeoutSec 3) {
        $ready = $true
        break
    }
}

if (-not $ready) {
    Write-Err 'Backend did not start.'
    Write-Info "Log: $errLog"
    Get-Content $errLog -Tail 20 -ErrorAction SilentlyContinue |
        ForEach-Object { Write-Info $_ }
    exit 1
}

Write-Step 'Demo stand is ready'
Write-Ok "UI:            http://localhost:$Port/"
# Parentheses are required: without them PowerShell passes '+', $Port and
# '/docs' as separate arguments and prints only the first string.
Write-Info ("API docs:     http://localhost:{0}/docs" -f $Port)
Write-Info "Database:     $standDb"
Write-Info "Logs:         $outLog"
Write-Info 'Stop:         .\scripts\stop.ps1'
Write-Info ''
Write-Info 'The case data is SYNTHETIC. It is not a real court case.'
Write-Info 'This is a draft project, not a court decision.'
