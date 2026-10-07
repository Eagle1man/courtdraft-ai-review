# API CourtDraft AI

Базовый адрес при локальном запуске: `http://localhost:8000`

Интерактивная документация: <http://localhost:8000/docs>
Схема OpenAPI: <http://localhost:8000/openapi.json>

---

## Общие правила

**Аутентификации нет.** Система рассчитана на запуск на локальной машине
одного пользователя. Выставление в сеть без реализации контроля доступа
недопустимо.

**Формат ошибок** — стандартный FastAPI:

```json
{ "detail": "Дело не найдено" }
```

**Коды ответов:**

| Код | Значение |
|---|---|
| `200` | успех |
| `201` | создан объект |
| `404` | объект не найден |
| `409` | конфликт: дубликат номера дела или документа |
| `422` | ошибка валидации входных данных |
| `503` | недоступен обязательный компонент (например, база данных) |

---

## Системные эндпоинты

### `GET /api/health`

Состояние всех компонентов. **Всегда отвечает `200`** с полным отчётом:
клиенту нужно видеть, что именно не работает.

Ключевое разделение — `required`. На ноутбуке разработки отсутствие
Ollama и GPU это `NOT REQUIRED`, на машине с RTX 3050 тот же компонент
станет `UNAVAILABLE` с `required: true`.

```json
{
  "status": "OK",
  "version": "0.1.0",
  "environment": "development",
  "components": [
    {
      "name": "Database",
      "state": "OK",
      "detail": "SQLite (MOCK-режим): sqlite:/D:/courtdraft-ai/data/cases/courtdraft.db",
      "required": true
    },
    {
      "name": "LLM",
      "state": "MOCK",
      "detail": "MockLLMProvider (реальная модель не вызывается)",
      "required": false
    },
    {
      "name": "Ollama",
      "state": "NOT_REQUIRED",
      "detail": "не требуется в режиме разработки",
      "required": false
    },
    {
      "name": "GPU",
      "state": "NOT_REQUIRED",
      "detail": "режим разработки, GPU не требуется",
      "required": false
    }
  ],
  "summary": {
    "Backend": "OK",
    "Database": "OK",
    "LLM": "MOCK",
    "Ollama": "NOT_REQUIRED",
    "GPU": "NOT_REQUIRED"
  },
  "warnings": []
}
```

Состояния компонента:

| Состояние | Значение |
|---|---|
| `OK` | работает |
| `MOCK` | работает в режиме заглушки — штатно на DEV-машине |
| `NOT_REQUIRED` | не нужно в текущем режиме |
| `UNAVAILABLE` | нужно, но отсутствует |
| `ERROR` | ошибка соединения |

Итоговый `status`: `OK` · `DEGRADED` · `ERROR`.

### `GET /api/info`

Идентификация сервиса и текущий режим. Содержит юридическое
предупреждение (п.70 ТЗ).

```json
{
  "name": "CourtDraft AI",
  "version": "0.1.0",
  "environment": "development",
  "llm_provider": "mock",
  "embedding_provider": "mock",
  "ollama_enabled": false,
  "disclaimer": "CourtDraft AI формирует проект судебного акта..."
}
```

### `GET /api/ready`

Для оркестратора. Возвращает `503`, только если сломан обязательный
компонент. Отсутствие Ollama в режиме разработки поводом отказать
в готовности не является.

---

## Дела

### `POST /api/cases`

Создать дело.

```json
{
  "case_number": "DEMO-001",
  "court_name": "Демо районный суд",
  "case_type": "civil",
  "category": "взыскание",
  "is_synthetic": true
}
```

| Поле | Обязательное | Описание |
|---|---|---|
| `case_number` | да | Номер дела. Уникален. |
| `court_name` | да | Наименование суда |
| `case_type` | да | Тип дела |
| `category` | нет | Категория |
| `is_synthetic` | нет | Помечает данные как синтетические. **Для демо обязательно `true`** |

Ответ `201`:

```json
{
  "id": "b1f4d0e2-...",
  "case_number": "DEMO-001",
  "status": "NEW",
  "is_synthetic": true,
  "participants": [],
  "documents": [],
  "document_count": 0,
  "created_at": "2026-10-08T10:00:00Z"
}
```

Ошибки: `409` — дело с таким номером уже существует; `422` — ошибка
валидации, в том числе **при неизвестном поле** (`extra: forbid` —
опечатка должна быть видна, а не проигнорирована).

### `GET /api/cases`

Список дел.

| Параметр | По умолчанию | Описание |
|---|---|---|
| `status` | — | Фильтр по статусу |
| `limit` | `50` | 1–200 |
| `offset` | `0` | Смещение |

```json
{ "items": [ ... ], "total": 42 }
```

`total` соответствует применённому фильтру, а не общему числу дел.

### `GET /api/cases/{case_id}` — одно дело, `404` если не найдено.

### `PATCH /api/cases/{case_id}`

```json
{ "status": "UNDER_REVIEW" }
{ "category": "договорные споры" }
```

Статусы дела:

```
NEW → PROCESSING → DRAFT_READY → UNDER_REVIEW
    → CORRECTED → READY_FOR_APPROVAL → ARCHIVED
```

---

## Документы дела

### `POST /api/cases/{case_id}/documents`

Зарегистрировать документ.

```json
{
  "filename": "01_claim.pdf",
  "document_type": "CLAIM",
  "mime_type": "application/pdf",
  "page_count": 3,
  "text": "Исковое заявление о взыскании..."
}
```

Типы документов **расширяемы**: поле `document_type` принимает любое
значение. В ответе поле `is_known_type` покажет, входит ли оно в базовый
перечень.

| Тип | Значение |
|---|---|
| Иск | `CLAIM` |
| Отзыв | `RESPONSE` |
| Договор | `CONTRACT` |
| Платёжный документ | `RECEIPT` |
| Акт | `ACT` |
| Заключение эксперта | `EXPERT_OPINION` |
| Доказательство | `EVIDENCE` |
| Ходатайство | `MOTION` |
| Протокол | `PROTOCOL` |
| Прочее | `OTHER` |

`409` — документ с таким SHA256 уже загружен (защита от дублей).

### `GET /api/cases/{case_id}/documents`

Параметр `type` фильтрует по типу документа.

---

## Участники дела

### `GET /api/cases/{case_id}/participants`
### `POST /api/cases/{case_id}/participants`

```json
{ "name": "Иванов И. И.", "role": "истец", "is_anonymized": false }
```

---

## Что ещё не реализовано

Эндпоинты ниже перечислены в ТЗ, но ещё не сделаны. Здесь они отмечены,
чтобы клиент заранее знал ожидаемый контракт — **это не рабочие ручки**:

| Эндпоинт | Фаза |
|---|---|
| `POST /api/cases/{id}/analyze` | 6–7 |
| `GET /api/cases/{id}/analysis` | 7 |
| `POST /api/cases/{id}/draft` | 8 |
| `GET /api/cases/{id}/draft` | 8 |
| `POST /api/drafts/{id}/verify` | 9 |
| `POST /api/drafts/{id}/revise` | 9 |
| `GET /api/drafts/{id}/sources` | 10 |
| `GET /api/drafts/{id}/versions` | 10 |

---

## Пример полного цикла (MOCK-режим)

```powershell
$api = "http://localhost:8000"

# 1. Создать дело
curl.exe -s -X POST "$api/api/cases" -H "Content-Type: application/json" `
  -d '{\"case_number\":\"DEMO-001\",\"court_name\":\"Демо суд\",\"case_type\":\"civil\",\"is_synthetic\":true}'

# 2. Добавить документ
curl.exe -s -X POST "$api/api/cases/<ID>/documents" -H "Content-Type: application/json" `
  -d '{\"filename\":\"01_claim.pdf\",\"document_type\":\"CLAIM\",\"text\":\"Исковое заявление\"}'

# 3. Проверить состояние
curl.exe -s "$api/api/health"
```

> **Примечание для разработки.** На этой машине `curl.exe` и
> `Invoke-WebRequest` падают с `SEC_E_INTERNAL_ERROR 0x80090304`
> (проблема сетевого стека Windows). Скрипты проекта выполняют
> HTTP-запросы через Python — `.\scripts\health.ps1` работает корректно.
