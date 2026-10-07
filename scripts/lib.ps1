<#
.SYNOPSIS
  Общие функции скриптов CourtDraft AI.

.DESCRIPTION
  Вызывается из install/start/stop/health/demo. Здесь собрано то, что
  должно вести себя одинаково во всех скриптах.

  ВАЖНО: этот файл ASCII-only. Windows PowerShell 5.1 читает .ps1 без BOM
  как ANSI и ломает парсинг кириллицы. Проверено 07.10.2026.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Корень репозитория (на уровень выше scripts/)
$script:ProjectRoot = Split-Path -Parent $PSScriptRoot
$script:BackendDir = Join-Path $script:ProjectRoot 'backend'
$script:VenvDir = Join-Path $script:BackendDir '.venv'
$script:VenvPython = Join-Path $script:VenvDir 'Scripts\python.exe'

function Write-Step {
    param([string]$Message)
    Write-Host ''
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host "    [ok]   $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "    [--]   $Message" -ForegroundColor Yellow
}

function Write-Err {
    param([string]$Message)
    Write-Host "    [FAIL] $Message" -ForegroundColor Red
}

function Write-Info {
    param([string]$Message)
    Write-Host "    $Message" -ForegroundColor DarkGray
}

# ── Проверки окружения ─────────────────────────────────────────────────────

function Test-Command {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-PythonExecutable {
    # Рабочий интерпретатор: сначала venv, потом py -3.14, потом python.
    # На машине разработки 3.11 и 3.13 могут быть битыми Store-заглушками,
    # поэтому порядок важен.
    if (Test-Path $script:VenvPython) { return $script:VenvPython }

    foreach ($candidate in @('py -3.14', 'python')) {
        $parts = $candidate.Split(' ')
        $exe = $parts[0]
        $args = @()
        if ($parts.Count -gt 1) { $args = $parts[1..($parts.Count - 1)] }

        if (-not (Test-Command $exe)) { continue }
        try {
            & $exe @args -c "import sys" 2>$null
            if ($LASTEXITCODE -eq 0) { return $candidate }
        } catch { continue }
    }
    return $null
}

function Test-DockerAvailable {
    # Docker не обязателен на DEV-машине, но его наличие полезно знать.
    # На этой машине стоит Docker Toolbox 2019 года с мёртвым демоном,
    # поэтому проверяем работоспособность демона, а не наличие CLI.
    if (-not (Test-Command 'docker')) { return $false }
    try {
        $out = & docker info --format '{{.ServerVersion}}' 2>&1
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Test-PortInUse {
    param([int]$Port)
    return $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Get-EnvFileValue {
    <#
      Прочитать значение из .env без загрузки в процесс.
      Нужно скриптам, которые должны знать режим (MOCK/REAL), не
      изменяя окружение текущего сеанса.
    #>
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Name,
        [string]$Default = ''
    )
    if (-not (Test-Path $Path)) { return $Default }

    $line = Select-String -Path $Path -Pattern "^$Name\s*=" -ErrorAction SilentlyContinue |
            Select-Object -First 1
    if (-not $line) { return $Default }

    $value = ($line.Line -split '=', 2)[1].Trim()
    return $value.Trim('"').Trim("'")
}

function Get-CurrentMode {
    # ВНИМАНИЕ: в PowerShell """...""" — НЕ комментарий, а выводимая строка.
    # Такая ошибка молча превращает возвращаемый хэштаблет в Object[],
    # и обращение $mode.LLM падает с PropertyNotFoundStrict.
    # Режим ИИ из .env. Используется health.ps1 и demo.ps1.
    $envFile = Join-Path $script:ProjectRoot '.env'
    $llm = Get-EnvFileValue -Path $envFile -Name 'LLM_PROVIDER' -Default 'mock'
    $emb = Get-EnvFileValue -Path $envFile -Name 'EMBEDDING_PROVIDER' -Default 'mock'
    return @{ LLM = $llm; Embedding = $emb }
}

# ── HTTP-запросы ───────────────────────────────────────────────────────────

# На этой машине PowerShell/curl падают с SEC_E_INTERNAL_ERROR (Schannel),
# а Python работает нормально. Поэтому HTTP-проверки идут через Python.
function Invoke-Json {
    <#
      HTTP GET/POST, возвращающий разобранный JSON.
      Использует Python: сетевой стек Schannel на Windows здесь нездоров.
    #>
    param(
        [Parameter(Mandatory)][string]$Url,
        [ValidateSet('GET', 'POST')][string]$Method = 'GET',
        [string]$Body,
        [int]$TimeoutSec = 10
    )

    $python = Get-PythonExecutable
    if (-not $python) { return $null }

    $script = @"
import json, sys, urllib.request
url, method, timeout = sys.argv[1], sys.argv[2], int(sys.argv[3])
body = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] else None
data = body.encode('utf-8') if body else None
req = urllib.request.Request(url, data=data, method=method)
if data:
    req.add_header('Content-Type', 'application/json')
try:
    with urllib.request.urlopen(req, timeout=timeout) as r:
        print(r.read().decode('utf-8'))
except Exception as e:
    print('__ERROR__ ' + type(e).__name__ + ': ' + str(e), file=sys.stderr)
    sys.exit(1)
"@

    $tempFile = Join-Path $env:TEMP "cd_http_$([guid]::NewGuid().ToString('N')).py"
    Set-Content -Path $tempFile -Value $script -Encoding UTF8
    try {
        $parts = $python.Split(' ')
        $exe = $parts[0]
        $pre = @()
        if ($parts.Count -gt 1) { $pre = $parts[1..($parts.Count - 1)] }

        $result = & $exe @pre $tempFile $Url $Method $TimeoutSec $Body 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Verbose "HTTP $Method $Url failed: $result"
            return $null
        }
        $joined = ($result -join "`n")
        return $joined | ConvertFrom-Json
    } catch {
        Write-Verbose "Invoke-Json error: $_"
        return $null
    } finally {
        Remove-Item $tempFile -ErrorAction SilentlyContinue
    }
}
