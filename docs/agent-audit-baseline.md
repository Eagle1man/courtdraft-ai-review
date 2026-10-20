# Базлайн аудита (Этап 0 ТЗ)

Дата: 2026-10-20. Ветка: `feat/phase-6-10-api-docs`. HEAD: `3fa9806`
(«Статус рецензента: восемь пунктов плана закрыты, сводка пересчитана»).
Рабочий каталог: `D:\courtdraft-ai`.

## Воспроизводимые команды и фактический результат

| Проверка | Команда | Результат |
|---|---|---|
| Тесты | `backend\.venv\Scripts\python.exe -m pytest -q -p no:warnings` | **688 passed, 0 failed, 0 errors**, exit 0 (junit: `scripts/tmp_junit_base.xml`) |
| Линтер | `... -m ruff check app tests` | чисто, exit 0 |
| Типы | `... -m mypy --strict app` | чисто, exit 0 |
| Состояние git | `git status --short`, `git log --oneline -3` | рабочее дерево чисто, кроме untracked `scripts/tmp_*` (диагностика, в git не идёт) |
| Секреты | `scripts/tmp_audit_secrets.py` → `scripts/tmp_audit_secrets_out.txt` | 204 отслеживаемых файла, 0 подозрительных имён |

## Аудит секретов и запрещённых данных

- Отслеживаемых файлов: **204**. Файлов с именами `.env`, `*.key`, `id_rsa`,
  `credentials.json` и т. п. в индексе — **нет**.
- Содержимое: 5 совпадений с признаками секретов, **все — заглушки**, проверены
  построчно:
  - `.env.example` → `SECRET_KEY=change-me-in-production`, `POSTGRES_PASSWORD=courtdraft`;
  - `docker-compose.yml` → `POSTGRES_PASSWORD:-courtdraft` (дефолт для локальной разработки);
  - `docs/deployment-rtx3050.md` → `POSTGRES_PASSWORD=выберите_свой_пароль` (инструкция);
  - `backend/app/db/session.py` → `defaults["postgres_password"].default` (код читает дефолт, значение не захардкожено).
- `.env` (реальный) на диске есть, **в git не отслеживается**.
- `git check-ignore` подтверждает игнорирование: `data/demo/real`, `data/eval`,
  `data/cases`, `data/lora` (в основном репозитории).
- Индексы корпуса и `.venv` в индексе отсутствуют.

## Недоступные проверки и инструменты

- **Ollama не установлен** (`ollama.exe` не найден, порт 11434 молчит).
  Локальный LLM-провайдер (`app/llm/ollama_provider.py`) сейчас нерабочий;
  QD-Court MVP проектируется без обязательной модели, с безопасным возвратом
  на конвейер без поиска (п. 8 ТЗ).
- **QD-Rec** (`github.com/SakanaAI/QD-Rec`, публичный, Apache-2.0) изучен:
  оригинал ходит в OpenRouter (`OPENROUTER_API_KEY`, облако) — локально без
  ключа не запускается. Перенимаются только архитектурные идеи: архив
  item–hypothesis, novelty-first admission, локальная конкуренция,
  explore/mutate, статус `active` у живых записей и сохранение вытесненных.
- Дополнительные методологические ссылки ТЗ (lawgent,
  legal-ai-hallucination-benchmark, legal-rag-eval) не запускались —
  это источники подхода, а не код для интеграции.

## Расхождения кода и документации

- `SECURITY.md` — актуален (пункт про аудит исправлен в `fa4efe0`).
- `README.md` — содержит строки `docs/legal-regime.md` и `docs/evaluation.md`.
- `docs/reviewer-status.md` — актуален (30/13/4), ссылается на коммиты до `be65af6`.
- Известные незакрытые пункты остаются как в `docs/reviewer-status.md`
  (пропорциональность расходов, возврат пошлины, вывод исхода, предмет
  доказывания других категорий, сквозная проверка на живых делах,
  сама юридическая оценка на 20–30 делах).

## Подтверждённые дефекты на этапе 0

Блокирующих дефектов не выявлено. Все проверки проходят; риски — те же,
что в `docs/reviewer-status.md` (ЧАСТИЧНО: покрытие доказательств, подбор
норм, подмена сумм; НЕ СДЕЛАНО: 4 пункта). Детальный разбор — в Этапе 1.
