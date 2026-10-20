<#
.SYNOPSIS
  Проверка состояния CourtDraft AI (п.59).

.DESCRIPTION
  Показывает блок в формате ТЗ:

      Backend       OK
      PostgreSQL    OK
      Qdrant        OK
      Frontend      OK
      LLM           MOCK
      Embeddings    MOCK
      GPU           NOT REQUIRED

  HTTP-запросы идут через Python: сетевой стек Schannel на этой машине
  отдаёт SEC_E_INTERNAL_ERROR, а urllib работает нормально.

  Exit code: 0 — всё в порядке или degraded; 1 — есть ERROR.
#>

. (Join-Path $PSScriptRoot 'lib.ps1')

Write-Step 'CourtDraft AI — состояние'

$mode = Get-CurrentMode
$problems = 0

# ── Backend ────────────────────────────────────────────────────────────────
$health = $null
if (Test-PortInUse 8000) {
    $health = Invoke-Json -Url 'http://127.0.0.1:8000/api/health' -TimeoutSec 10
}

if ($health) {
    Write-Ok 'Backend       OK'

    foreach ($c in $health.components) {
        $line = '{0,-14} {1}' -f $c.name, $c.state
        switch ($c.state) {
            'OK'            { Write-Ok $line }
            'MOCK'          { Write-Info ($line + '   (заглушка, штатно для разработки)') }
            'NOT_REQUIRED'  { Write-Info ($line + '   (не нужно в этом режиме)') }
            'UNAVAILABLE'   {
                if ($c.required) { Write-Warn ($line + '   ' + $c.detail); $problems++ }
                else { Write-Info ($line + '   ' + $c.detail) }
            }
            'ERROR'         { Write-Err ($line + '   ' + $c.detail); $problems++ }
            default         { Write-Info $line }
        }
    }

    Write-Info ''
    Write-Info ("Итог: " + $health.status + "  (окружение: " + $health.environment + ")")
} else {
    if (Test-PortInUse 8000) {
        Write-Warn 'Backend       ОТВЕЧАЕТ, НО /api/health НЕ ОТВЕЧАЕТ'
    } else {
        Write-Warn 'Backend       НЕ ЗАПУЩЕН'
    }
    Write-Info 'Запустить: .\scripts\start.ps1'
    $problems++
}

# ── Frontend ───────────────────────────────────────────────────────────────
$frontendDir = Join-Path $script:ProjectRoot 'frontend'
if (Test-Path (Join-Path $frontendDir 'package.json')) {
    if (Test-PortInUse 3000) {
        Write-Ok 'Frontend      OK  (http://localhost:3000)'
    } else {
        Write-Warn 'Frontend      НЕ ЗАПУЩЕН  (http://localhost:3000)'
        Write-Info 'Запустить: .\scripts\start.ps1'
    }
} else {
    Write-Info 'Frontend      ещё не создан (Фаза 11)'
}

# ── Режим ИИ ───────────────────────────────────────────────────────────────
Write-Info ''
Write-Info 'Режим ИИ (из .env):'
if ($mode.LLM -eq 'mock') {
    Write-Info 'LLM           MOCK'
} else {
    Write-Info ("LLM           " + $mode.LLM.ToUpper())
}
if ($mode.Embedding -eq 'mock') {
    Write-Info 'Embeddings    MOCK'
} else {
    Write-Info ("Embeddings    " + $mode.Embedding.ToUpper())
}

# ── GPU ────────────────────────────────────────────────────────────────────
$gpus = @(Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue |
         Where-Object { $_.Name -match 'NVIDIA' })
if ($gpus.Count -gt 0) {
    Write-Info ("GPU           NVIDIA " + ($gpus[0].Name -replace '.*NVIDIA\s*', ''))
} else {
    Write-Info 'GPU           NOT REQUIRED'
}

# ── Итог ───────────────────────────────────────────────────────────────────
Write-Info ''
if ($problems -eq 0) {
    Write-Ok 'Всё работает в текущем режиме.'
    exit 0
}
Write-Warn ("Не готово: " + $problems + " компонент(ов) требуют внимания.")
exit 1
