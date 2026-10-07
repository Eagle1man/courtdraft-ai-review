<#
.SYNOPSIS
  Запуск CourtDraft AI (п.58).

.DESCRIPTION
  Поднимает backend на http://localhost:8000 и, при наличии фронтенда,
  dev-сервер на http://localhost:3000.

  Ollama НЕ запускается автоматически: в режиме разработки он не нужен.
#>

param(
    [switch]$BackendOnly,
    [switch]$FrontendOnly
)

. (Join-Path $PSScriptRoot 'lib.ps1')

Write-Step 'CourtDraft AI — запуск'

$mode = Get-CurrentMode
Write-Info "Режим ИИ: LLM=$($mode.LLM) Embeddings=$($mode.Embedding)"

if (-not (Test-Path $script:VenvPython)) {
    Write-Err 'venv не найден. Сначала выполните: .\scripts\install.ps1'
    exit 1
}

# ── Backend ────────────────────────────────────────────────────────────────
if (-not $FrontendOnly) {
    if (Test-PortInUse 8000) {
        Write-Info 'Backend уже слушает порт 8000, пропускаю.'
    } else {
        Write-Step 'Запуск backend'
        $logDir = Join-Path $script:BackendDir '.logs'
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null

        $outLog = Join-Path $logDir 'backend.out.log'
        $errLog = Join-Path $logDir 'backend.err.log'

        Start-Process -FilePath $script:VenvPython `
            -ArgumentList '-m', 'uvicorn', 'app.main:app',
                         '--host', '127.0.0.1', '--port', '8000' `
            -WorkingDirectory $script:BackendDir `
            -RedirectStandardOutput $outLog `
            -RedirectStandardError $errLog `
            -WindowStyle Hidden

        # Ждём готовности вместо фиксированной паузы.
        $ready = $false
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Seconds 1
            if (Invoke-Json -Url 'http://127.0.0.1:8000/api/health' -TimeoutSec 3) {
                $ready = $true
                break
            }
        }

        if ($ready) {
            Write-Ok 'Backend       OK    http://localhost:8000'
            Write-Info 'API docs:     http://localhost:8000/docs'
        } else {
            Write-Err 'Backend не поднялся.'
            Write-Info "Лог: $errLog"
            Get-Content $errLog -Tail 20 -ErrorAction SilentlyContinue |
                ForEach-Object { Write-Info $_ }
            exit 1
        }
    }
}

# ── Frontend ───────────────────────────────────────────────────────────────
if (-not $BackendOnly) {
    $frontendDir = Join-Path $script:ProjectRoot 'frontend'
    if (Test-Path (Join-Path $frontendDir 'package.json')) {
        if (Test-PortInUse 3000) {
            Write-Info 'Frontend уже слушает порт 3000, пропускаю.'
        } else {
            Write-Step 'Запуск frontend'
            $logDir = Join-Path $script:ProjectRoot '.logs'
            New-Item -ItemType Directory -Path $logDir -Force | Out-Null

            Push-Location $frontendDir
            Start-Process -FilePath 'npm' -ArgumentList 'run', 'dev' `
                -WorkingDirectory $frontendDir `
                -RedirectStandardOutput (Join-Path $logDir 'frontend.out.log') `
                -RedirectStandardError (Join-Path $logDir 'frontend.err.log') `
                -WindowStyle Hidden
            Pop-Location

            Start-Sleep -Seconds 8
            if (Test-PortInUse 3000) {
                Write-Ok 'Frontend      OK    http://localhost:3000'
            } else {
                Write-Warn 'Frontend не поднялся, проверьте .logs\frontend.err.log'
            }
        }
    } else {
        Write-Info 'Frontend ещё не создан (Фаза 11), пропускаю.'
    }
}

# ── Итог ───────────────────────────────────────────────────────────────────
Write-Step 'Готово'
Write-Info 'Проверить:  .\scripts\health.ps1'
Write-Info 'Остановить: .\scripts\stop.ps1'
if ($mode.LLM -eq 'mock') {
    Write-Info ''
    Write-Info 'Режим MOCK: реальная модель не вызывается.'
    Write-Info 'Это штатно для машины 8 GB без GPU.'
}
