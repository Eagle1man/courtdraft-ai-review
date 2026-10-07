# Развёртывание на компьютере с RTX 3050

Пошаговая инструкция для машины, где запускается реальная AI-часть.

Требования: Windows 10/11, NVIDIA RTX 3050, 8 ГБ ОЗУ или больше, SSD.

> **Важно.** Инструкция описывает перенос проекта, разработанного на
> ноутбуке 8 ГБ без видеокарты. **Исходный код при переносе не меняется** —
> различия только в `.env`. Это и есть главный критерий переносимости.

---

## 1. Драйвер NVIDIA

Проверить, установлен ли драйвер и видна ли карта:

```powershell
nvidia-smi
```

Должны быть `Driver Version` и `CUDA Version`. Если команда не найдена —
установите драйвер с [nvidia.com/drivers](https://www.nvidia.com/drivers)
(«Studio Driver» для стабильности).

Требуемая версия: **527 или новее** для поддержки Ollama на Windows.

---

## 2. Docker Desktop

Нужен для PostgreSQL и Qdrant.

1. Скачать: [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)
2. При установке оставить галочку **Use WSL 2 instead of Hyper-V**
3. После установки перезагрузить компьютер
4. Проверить:

```powershell
docker version
docker compose version
```

> Если Docker Desktop не устанавливается, PostgreSQL и Qdrant можно
> поставить нативно — проект это поддерживает. См. раздел 8.

---

## 3. Ollama

1. Скачать: [ollama.com/download](https://ollama.com/download/windows)
2. Установить и **перезагрузить компьютер**
3. Проверить:

```powershell
ollama --version
ollama serve          # в отдельном окне
```

### Загрузить модель

```powershell
# Основная модель проекта (проверено: тег существует в реестре Ollama)
ollama pull qwen3.5:4b

# Модель эмбеддингов для RAG
ollama pull bge-m3
```

Проверить, что модель загрузилась:

```powershell
ollama list
```

**Требуется примерно 8–10 ГБ на диске** под `qwen3.5:4b` и `bge-m3`.

---

## 4. Склонировать репозиторий

```powershell
cd C:\projects
git clone <адрес-репозитория> courtdraft-ai
cd courtdraft-ai
```

---

## 5. Настроить `.env`

```powershell
Copy-Item .env.example .env
notepad .env
```

Заменить значения:

```env
# ── Переключение в реальный режим ───────────────────────────
LLM_PROVIDER=ollama
EMBEDDING_PROVIDER=local
OLLAMA_ENABLED=true
OLLAMA_MODEL=qwen3.5:4b
APP_ENV=runtime

# ── Ollama на хосте ─────────────────────────────────────────
# host.docker.internal нужен, чтобы контейнер backend увидел
# Ollama, запущенный на самой машине
OLLAMA_BASE_URL=http://host.docker.internal:11434

# ── PostgreSQL вместо SQLite ────────────────────────────────
DATABASE_URL=postgresql+asyncpg://courtdraft:courtdraft@localhost:5432/courtdraft
POSTGRES_DB=courtdraft
POSTGRES_USER=courtdraft
POSTGRES_PASSWORD=выберите_свой_пароль

# ── Qdrant вместо встроенного режима ───────────────────────
QDRANT_MODE=server
QDRANT_URL=http://localhost:6333

# ── Эмбеддинги ──────────────────────────────────────────────
EMBEDDING_MODEL=bge-m3
# Размерность вектора должна соответствовать модели.
# Для bge-m3 — 1024. Если используете другую модель, измените
# и размерность здесь: она определяет индекс Qdrant.
EMBEDDING_DIM=1024
EMBEDDINGS_OPTIONAL=true
```

> ⚠️ **Пароль в `.env` — это пароль локальной базы.** Для машины
> разработки годится, для общей машины стоит задать свой.

### Проверить, что режим переключился

```powershell
cd backend
..\.venv\Scripts\python.exe -c "from app.config import get_settings; s=get_settings(); print(s.llm_provider, s.app_env, s.qdrant_mode)"
```

Ожидаемо: `ollama runtime server`

---

## 6. Установить зависимости

```powershell
.\scripts\install.ps1
```

Скрипт проверит Python, Node, Docker и Ollama, создаст `.venv`
и поставит зависимости из `pyproject.toml`.

---

## 7. Запустить

```powershell
# Поднять базу данных и векторное хранилище
docker compose up -d postgres qdrant

# Запустить backend и фронтенд
.\scripts\start.ps1
```

Ожидаемые адреса:

| Что | Адрес |
|---|---|
| Интерфейс | <http://localhost:3000> |
| API | <http://localhost:8000/docs> |
| Qdrant | <http://localhost:6333/dashboard> |

---

## 8. Проверить состояние

```powershell
.\scripts\health.ps1
```

Ожидаемый вывод в реальном режиме:

```
    [ok]   Backend       OK
    [ok]   PostgreSQL    OK
    [ok]   Qdrant        OK
    [ok]   Ollama        OK
    [ok]   LLM           OK
    [ok]   Embeddings    OK
    [ok]   GPU           NVIDIA RTX 3050
```

Если компонент показан как `UNAVAILABLE`, детали будут рядом с ним —
например, `нет ответа от http://host.docker.internal:11434`.

### Частые проблемы

**`UNAVAILABLE: нет ответа от Ollama`**

Ollama запущен не в том режиме или слушает только `127.0.0.1`.
Проверьте:

```powershell
$env:OLLAMA_HOST = "0.0.0.0:11434"
ollama serve
```

**`Embeddings: UNAVAILABLE`**

Модель эмбеддингов не загружена или её имя указано неверно:

```powershell
ollama list
```

Система продолжит работу в degraded-режиме — это предусмотрено.
Но полноценный RAG без эмбеддингов работать не будет.

**`Qdrant: UNAVAILABLE`**

```powershell
docker compose ps
docker compose logs qdrant
```

**PostgreSQL вместо Docker (нативная установка)**

Если Docker недоступен, поставьте PostgreSQL 16 и создайте базу:

```sql
CREATE DATABASE courtdraft;
CREATE USER courtdraft WITH PASSWORD 'ваш_пароль';
GRANT ALL PRIVILEGES ON DATABASE courtdraft TO courtdraft;
```

Для Qdrant скачайте готовую сборку с
[qdrant.tech/documentation/quickstart](https://qdrant.tech/documentation/quickstart/)
или оставьте `QDRANT_MODE=memory` — для одиночной работы разницы
в качестве нет, но данные не переживут перезапуск.

---

## 9. Применить миграции

```powershell
cd backend
..\.venv\Scripts\alembic.exe upgrade head
```

Проверить, что схема создана:

```powershell
..\.venv\Scripts\alembic.exe current
```

Откат, если понадобится:

```powershell
..\.venv\Scripts\alembic.exe downgrade base
```

---

## 10. Запустить демонстрацию

После того как заработают Фазы 6–16, демонстрация запускается одной
командой и проходит **весь** путь: дело → документы → разбор → поиск →
анализ → проект акта → проверка → правка.

```powershell
.\scripts\demo.ps1
```

Все данные демонстрации **вымышленные** — реальных судебных дел
в репозитории нет.

---

## 11. Открыть интерфейс

<http://localhost:3000>

Порядок работы:

1. создать дело;
2. загрузить материалы;
3. запустить анализ;
4. посмотреть пакет доказательств и матрицу;
5. открыть проект акта;
6. изучить замечания проверки;
7. внести правки, сохранить версию.

> Финальное действие — всегда за человеком. Система не имеет функции
> утверждения решения.

---

## Диагностика

### Сбросить состояние

```powershell
.\scripts\stop.ps1
.\scripts\reset.ps1       # очистить базу и индекс
.\scripts\start.ps1
```

### Логи

```powershell
Get-Content backend\.logs\backend.err.log -Tail 50
docker compose logs -f backend
```

### Проверить связь с Ollama вручную

```powershell
Invoke-RestMethod http://localhost:11434/api/tags | Select-Object -ExpandProperty models
```

### Проверить, что модель отвечает

```powershell
$body = @{ model = "qwen3.5:4b"; prompt = "Ответь одним словом: работает?"; stream = $false } |
        ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:11434/api/generate -Method Post `
                  -Body $body -ContentType "application/json"
```

---

## Перенос обратно на ноутбук

Достаточно вернуть значения в `.env`:

```env
LLM_PROVIDER=mock
EMBEDDING_PROVIDER=mock
OLLAMA_ENABLED=false
APP_ENV=development
DATABASE_URL=
QDRANT_MODE=memory
```

Код не меняется.

---

## Если что-то не работает

1. `.\scripts\health.ps1` — покажет, какой компонент недоступен и почему.
2. `docs/api.md` — контракт эндпоинтов.
3. `docs/architecture.md` — проектные решения и известные ограничения.

Убедитесь, что Ollama отвечает на порту 11434 **до** запуска Docker —
иначе контейнер backend не сможет до него добраться.
