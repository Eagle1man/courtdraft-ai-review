<#
.SYNOPSIS
    Проверка контракта веб-интерфейса на временной базе.

.DESCRIPTION
    Поднимает сервис на свободном порту с отдельной временной базой,
    прогоняет сквозную проверку вызовов интерфейса и гасит сервис.

    Почему отдельная база: проверка создаёт дела и документы. Если запустить
    её против рабочей базы, в списке дел накопится мусор из тестовых
    производств — и на демонстрации это выглядит как неисправность.

.PARAMETER Port
    Порт сервиса. По умолчанию 8011, чтобы не мешать уже запущенному.

.PARAMETER WaitSeconds
    Сколько ждать готовности сервиса.
#>
[CmdletBinding()]
param(
    [int]$Port = 8011,
    [int]$WaitSeconds = 40
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$backend = Split-Path -Parent $PSScriptRoot
$root = Split-Path -Parent $backend
Set-Location $backend

$python = Join-Path $backend '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    throw "Не найден интерпретатор: $python. Выполните .\scripts\install.ps1"
}

$workdir = Join-Path $env:TEMP "courtdraft-ui-$Port"
if (Test-Path $workdir) { Remove-Item $workdir -Recurse -Force }
New-Item -ItemType Directory -Path $workdir -Force | Out-Null

$dbPath = (Join-Path $workdir 'ui-check.db') -replace '\\', '/'

# Отдельная база и режим заглушки: проверять контракт страницы не требует
# ни настоящей модели, ни рабочих данных.
$env:DATABASE_URL = "sqlite+aiosqlite:///$dbPath"
$env:STORAGE_DIR = Join-Path $workdir 'storage'
$env:LLM_PROVIDER = 'mock'
$env:EMBEDDING_PROVIDER = 'mock'

Write-Host "База проверки: $dbPath" -ForegroundColor DarkGray
Write-Host "Порт:         $Port" -ForegroundColor DarkGray

$stdout = Join-Path $workdir 'server.out'
$stderr = Join-Path $workdir 'server.err'

$process = Start-Process -FilePath $python `
    -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$Port" `
    -WorkingDirectory $backend `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -WindowStyle Hidden `
    -PassThru

$exitCode = 1
try {
    # Ждём готовности: без этого проверка стартует раньше, чем сервис
    # поднимется, и упадёт на первом же запросе.
    $ready = $false
    for ($i = 0; $i -lt $WaitSeconds; $i++) {
        Start-Sleep -Seconds 1
        try {
            $response = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 3
            if ($response.status) { $ready = $true; break }
        } catch {
            # Сервис ещё поднимается — это ожидаемо, не повод падать.
        }
    }

    if (-not $ready) {
        Write-Host "Сервис не поднялся за $WaitSeconds с. Лог:" -ForegroundColor Red
        if (Test-Path $stderr) { Get-Content $stderr -Tail 20 }
        throw 'Сервис не готов'
    }

    Write-Host ''
    Write-Host '--- Проверка контракта ---' -ForegroundColor Cyan
    & $python 'scripts\check_ui_contract.py' --base "http://127.0.0.1:$Port"
    $exitCode = $LASTEXITCODE
}
finally {
    if ($process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        Write-Host ''
        Write-Host 'Сервис остановлен, временная база не тронута.' -ForegroundColor DarkGray
    }
}

exit $exitCode