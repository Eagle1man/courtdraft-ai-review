<#
.SYNOPSIS
  Установка CourtDraft AI в режиме разработки (п.57).

.DESCRIPTION
  Проверяет окружение, создаёт venv, ставит зависимости из pyproject.toml,
  создаёт .env из .env.example.

  Ollama НЕ требуется. PostgreSQL не обязателен: система стартует
  в degraded-режиме и сообщает об отсутствии БД в /api/health.

  Docker не требуется: на машине разработки его демон может быть
  недоступен, поэтому все проверки HTTP идут через Python.
#>

param(
    [switch]$SkipFrontend
)

. (Join-Path $PSScriptRoot 'lib.ps1')

Write-Step 'CourtDraft AI — установка (режим разработки)'

# ── 1. Python ──────────────────────────────────────────────────────────────
$python = Get-PythonExecutable
if (-not $python) {
    Write-Err 'Рабочий Python не найден. Установите Python 3.12 или новее.'
    exit 1
}
Write-Ok "Python: $python"
& $python --version 2>&1 | ForEach-Object { Write-Info $_ }

# ── 2. Node ────────────────────────────────────────────────────────────────
if (Test-Command 'node') {
    $nodeVersion = & node --version
    Write-Ok "Node.js: $nodeVersion"
} else {
    Write-Warn 'Node.js не найден — фронтенд собрать не получится.'
    Write-Info 'Установите Node.js 20+ с https://nodejs.org'
}

# ── 3. Git ─────────────────────────────────────────────────────────────────
if (Test-Command 'git') {
    Write-Ok "Git: $(& git --version)"
} else {
    Write-Warn 'Git не найден (нужен для контроля версий).'
}

# ── 4. Docker (необязательно) ──────────────────────────────────────────────
if (Test-DockerAvailable) {
    Write-Ok 'Docker: демон отвечает'
} else {
    Write-Info 'Docker недоступен — это НОРМАЛЬНО для машины разработки.'
    Write-Info 'PostgreSQL и Qdrant можно поднять нативно или не поднимать вовсе.'
}

# ── 5. Ollama (необязательно) ──────────────────────────────────────────────
if (Test-Command 'ollama') {
    Write-Ok "Ollama: $(& ollama --version 2>&1)"
    Write-Info 'На ноутбуке реальная модель не используется (LLM_PROVIDER=mock).'
} else {
    Write-Info 'Ollama не установлен. Это нормально для DEVELOPMENT.'
}

# ── 6. .env ────────────────────────────────────────────────────────────────
$envFile = Join-Path $script:ProjectRoot '.env'
$envExample = Join-Path $script:ProjectRoot '.env.example'
if (Test-Path $envFile) {
    Write-Ok '.env уже существует — не перезаписываю.'
} else {
    if (-not (Test-Path $envExample)) {
        Write-Err '.env.example не найден, нечего копировать.'
        exit 1
    }
    Copy-Item $envExample $envFile
    Write-Ok '.env создан из .env.example (режим MOCK)'
}

# ── 7. Python-окружение ────────────────────────────────────────────────────
Write-Step 'Установка зависимостей'
if (Test-Path $script:VenvPython) {
    Write-Info 'venv уже существует, пропускаю создание.'
} else {
    Write-Info 'Создаю venv (может занять минуту)...'
    & $python -m venv $script:VenvDir
    if ($LASTEXITCODE -ne 0) {
        Write-Err 'Не удалось создать venv.'
        exit 1
    }
    Write-Ok 'venv создан'
}

Write-Info 'Обновляю pip...'
& $script:VenvPython -m pip install --quiet --upgrade pip

Write-Info 'Ставлю зависимости из pyproject.toml (включая dev)...'
& $script:VenvPython -m pip install --quiet -e "$script:BackendDir[dev]"
if ($LASTEXITCODE -ne 0) {
    Write-Err 'Установка зависимостей не удалась.'
    exit 1
}
Write-Ok 'Зависимости установлены'

# ── 8. Каталоги данных ─────────────────────────────────────────────────────
Write-Step 'Подготовка каталогов данных'
Push-Location $script:BackendDir
& $script:VenvPython -c "from app.config import get_settings; get_settings().ensure_dirs(); print('  каталоги созданы')" 2>&1 |
    ForEach-Object { Write-Info $_ }
Pop-Location

# ── 9. Фронтенд (необязательно) ────────────────────────────────────────────
if ($SkipFrontend) {
    Write-Info 'Фронтенд пропущен (-SkipFrontend)'
} else {
    $frontendDir = Join-Path $script:ProjectRoot 'frontend'
    if (Test-Path (Join-Path $frontendDir 'package.json')) {
        if (Test-Command 'npm') {
            Write-Step 'Установка зависимостей фронтенда'
            Push-Location $frontendDir
            & npm install --no-fund --no-audit 2>&1 | Select-Object -Last 5 |
                ForEach-Object { Write-Info $_ }
            Pop-Location
            Write-Ok 'Фронтенд установлен'
        } else {
            Write-Warn 'npm недоступен, фронтенд пропущен.'
        }
    } else {
        Write-Info 'Фронтенд ещё не создан (Фаза 11).'
    }
}

# ── Итог ───────────────────────────────────────────────────────────────────
Write-Step 'Проверка установки'
$mode = Get-CurrentMode
Write-Info "Режим ИИ:  LLM=$($mode.LLM)  Embeddings=$($mode.Embedding)"
Write-Info "Запуск:   .\scripts\start.ps1"
Write-Info "Проверка: .\scripts\health.ps1"
Write-Ok 'Установка завершена'
Write-Info 'PostgreSQL и Qdrant можно поднять позже (Фазы 3-4).'
