<#
.SYNOPSIS
  Остановка CourtDraft AI (п.56).

.DESCRIPTION
  Останавливает backend и frontend. Ollama и PostgreSQL не трогает:
  они могут быть нужны для других задач.
#>

. (Join-Path $PSScriptRoot 'lib.ps1')

Write-Step 'CourtDraft AI — остановка'

# ── Backend ────────────────────────────────────────────────────────────────
$stopped = 0

if (Test-PortInUse 8000) {
    $pids = @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
              Select-Object -ExpandProperty OwningProcess -Unique)
    foreach ($pid in $pids) {
        if ($pid -and $pid -ne 0) {
            try {
                Stop-Process -Id $pid -Force -ErrorAction Stop
                $stopped++
                Write-Ok "Остановлен процесс backend (PID $pid)"
            } catch {
                Write-Warn "Не удалось остановить PID $pid : $($_.Exception.Message)"
            }
        }
    }
}

if ($stopped -eq 0) {
    Write-Info 'Backend не был запущен.'
}

# ── Frontend ───────────────────────────────────────────────────────────────
if (Test-Path (Join-Path $script:ProjectRoot 'frontend\package.json')) {
    $nodeProcs = @(Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
                   Where-Object { $_.CommandLine -match 'vite' -and $_.CommandLine -match 'courtdraft' })
    foreach ($proc in $nodeProcs) {
        try {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
            Write-Ok "Остановлен frontend (PID $($proc.ProcessId))"
        } catch {
            Write-Warn "Не удалось остановить frontend PID $($proc.ProcessId)"
        }
    }
}

# ── Проверка ───────────────────────────────────────────────────────────────
Start-Sleep -Seconds 2
$stillUp = (Test-PortInUse 8000) -or (Test-PortInUse 3000)

Write-Step 'Готово'
if ($stillUp) {
    Write-Warn 'Что-то ещё слушает порты 8000 или 3000.'
    Write-Info 'Проверьте: Get-NetTCPConnection -LocalPort 8000,3000 -State Listen'
} else {
    Write-Ok 'Все компоненты остановлены.'
}
Write-Info 'Ollama и PostgreSQL не трогались.'
