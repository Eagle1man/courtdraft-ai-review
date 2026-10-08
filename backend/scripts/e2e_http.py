"""Сквозной прогон через HTTP на настоящей модели.

Проверяет то, ради чего делалась Фаза 11: проект, который раньше жил
только в памяти скрипта, теперь появляется по HTTP и остаётся в базе.

Порядок проверок соответствует пути пользователя:
создать дело -> загрузить материалы -> сформировать проект -> получить
результат -> увидеть версии -> внести правку -> убедиться, что первая
версия не пропала.

Запуск:
    .venv\\Scripts\\python.exe scripts\\e2e_http.py
    .venv\\Scripts\\python.exe scripts\\e2e_http.py --provider mock
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import httpx  # noqa: E402

from app.config import AppEnv, Settings  # noqa: E402
from app.db.bootstrap import ensure_schema  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services.case_service import db  # noqa: E402

REPO = BACKEND.parent
DEMO = REPO / "data" / "demo"


def say(text: str = "") -> None:
    print(text, flush=True)


def banner(step: str, title: str) -> None:
    say()
    say("=" * 76)
    say(f"  {step}. {title}")
    say("=" * 76)


def make_settings(provider: str, workdir: Path) -> Settings:
    return Settings(
        app_env=AppEnv.DEVELOPMENT,
        llm_provider=provider,  # type: ignore[arg-type]
        ollama_enabled=provider != "mock",
        ollama_model="qwen2.5:1.5b",
        ollama_base_url="http://127.0.0.1:11434",
        ollama_timeout_sec=1800,
        ollama_num_ctx=2048,
        database_url=f"sqlite+aiosqlite:///{(workdir / 'e2e.db').as_posix()}",
        storage_dir=workdir,
        documents_dir=workdir / "documents",
        demo_dir=DEMO,
        laws_dir=REPO / "data" / "laws",
        templates_dir=REPO / "data" / "templates",
    )


async def run(provider: str) -> int:
    started = time.perf_counter()
    workdir = REPO / "data" / "demo" / "e2e"
    if workdir.exists():
        for item in workdir.iterdir():
            if item.is_file():
                item.unlink(missing_ok=True)
    workdir.mkdir(parents=True, exist_ok=True)

    settings = make_settings(provider, workdir)
    settings.ensure_dirs()

    banner("1", "ПОДКЛЮЧЕНИЕ")
    if not await db.connect(settings):
        say("  БД недоступна — прогон невозможен")
        return 1
    await ensure_schema()
    say(f"  БД: {db.url}")

    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)

    # Событие старта приложения: lifespan поднимает каталоги и проверяет
    # подключения. Без него сценарий шёл бы мимо кода, который работает
    # при настоящем запуске.
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        return await scenario(client, provider, started)


async def scenario(client: httpx.AsyncClient, provider: str, started: float) -> int:
    banner("2", "СОЗДАНИЕ ДЕЛА И ЗАГРУЗКА МАТЕРИАЛОВ")

    manifest = json.loads((DEMO / "manifest.json").read_text(encoding="utf-8"))

    response = await client.post(
        "/api/cases",
        json={
            "case_number": manifest["case_number"],
            "court_name": manifest["court"],
            "case_type": "civil",
            "category": manifest["category"],
            "is_synthetic": True,
        },
    )
    if response.status_code != 201:
        say(f"  ОШИБКА создания дела: {response.status_code} {response.text[:300]}")
        return 1

    case_id = response.json()["id"]
    say(f"  дело создано: {case_id}")

    for entry in manifest["documents"]:
        path = DEMO / entry["filename"]
        doc = await client.post(
            f"/api/cases/{case_id}/documents",
            json={
                "filename": entry["filename"],
                "document_type": entry["document_type"],
                "mime_type": "text/plain",
                "text": path.read_text(encoding="utf-8"),
            },
        )
        state = "загружен" if doc.status_code == 201 else f"ОШИБКА {doc.status_code}"
        say(f"  {entry['filename']:<26} {state}")

    banner("3", "ФОРМИРОВАНИЕ ПРОЕКТА (фоновая задача)")

    response = await client.post(
        f"/api/cases/{case_id}/draft",
        json={"actor": "judge"},
    )
    if response.status_code != 202:
        say(f"  ОШИБКА: {response.status_code} {response.text[:400]}")
        return 1

    job_id = response.json()["job_id"]
    say(f"  задача принята: {job_id}")
    say("  ожидание (на процессоре это 2-3 минуты)…")

    deadline = time.perf_counter() + 900
    state = "PENDING"
    while time.perf_counter() < deadline:
        await asyncio.sleep(5)
        poll = await client.get(f"/api/jobs/{job_id}")
        body = poll.json()
        state = body["state"]
        if state in {"DONE", "FAILED"}:
            break
        say(f"    состояние: {state}")

    if state == "FAILED":
        say(f"  ЗАДАЧА НЕ ВЫПОЛНЕНА: {body.get('error')}")
        return 1

    say(f"  задача завершена: {state}, проверка — {body.get('verification')}")

    banner("4", "ПРОЕКТ СОХРАНЁН В БАЗЕ")

    response = await client.get(f"/api/cases/{case_id}/draft")
    if response.status_code != 200 or response.json() is None:
        say(f"  ОШИБКА чтения проекта: {response.status_code}")
        return 1

    draft = response.json()
    say(f"  статус:        {draft['status']}")
    say(f"  версия:        {draft['current_version']}")
    say(f"  разделов:      {len(draft['sections'])}")
    say(f"  символов:      {len(draft['text'])}")
    say(f"  источников:    {len(draft['sources'])}")
    say(f"  помечен как проект: {draft['is_draft']}")

    verification = draft.get("verification") or {}
    say(f"  проверка:      {verification.get('status', '—')}")
    say(f"  замечаний:     {len(verification.get('issues', []))}")
    say(f"  без источника: {verification.get('unsupported_claims', '—')}")

    say()
    say("  разделы проекта:")
    for section in draft["sections"]:
        flag = "требует проверки" if section["needs_review"] else "без пометки"
        source = "MOCK" if section["is_mock"] else "REAL"
        say(f"    [{source}] {section['name']:<24} {len(section['text']):>5} симв. · {flag}")

    banner("5", "ПАКЕТ ДОКАЗАТЕЛЬСТВ")

    response = await client.get(f"/api/cases/{case_id}/evidence")
    evidence = response.json()
    say(f"  фактов: {evidence['facts']}")

    by_category: dict[str, int] = {}
    for item in evidence["items"]:
        by_category[item["category"]] = by_category.get(item["category"], 0) + 1
    for category, count in sorted(by_category.items()):
        say(f"    {category:<24} {count:>3}")

    if evidence["items"]:
        sample = evidence["items"][0]
        say()
        say(f"  пример факта: {sample['content'][:90]}")
        say(f"  источник:     {sample['source'].get('citation', '—')}")

    banner("6", "ВЕРСИИ И ПРАВКА")

    response = await client.get(f"/api/cases/{case_id}/draft/versions")
    versions = response.json()
    say(f"  версий: {len(versions['versions'])}")

    draft_id = draft["id"]
    first_text = draft["text"]

    edit = await client.post(
        f"/api/drafts/{draft_id}/versions",
        json={
            "text": first_text + "\n\nДОБАВЛЕНО РЕДАКТОРОМ ВРУЧНУЮ.",
            "author": "judge",
            "comment": "правка судьи для проверки сохранения версий",
        },
    )
    if edit.status_code != 201:
        say(f"  ОШИБКА правки: {edit.status_code} {edit.text[:200]}")
        return 1
    say(f"  версия {edit.json()['version']} создана автором {edit.json()['author']}")

    response = await client.get(f"/api/cases/{case_id}/draft/versions")
    versions = response.json()["versions"]
    say(f"  версий после правки: {len(versions)}")

    first = versions[0]
    say(f"    v{first['version']} автор {first['author']}, {len(first['text'])} симв.")
    say(f"    v{versions[-1]['version']} автор {versions[-1]['author']}, "
        f"{len(versions[-1]['text'])} симв.")

    if first["text"] != first_text:
        say()
        say("  ОШИБКА: первая версия изменилась — правка затёрла исходный текст")
        return 1
    say()
    say("  первая версия не изменилась после правки — версии хранятся целиком")

    elapsed = time.perf_counter() - started
    banner("ИТОГ", "СКВОЗНОЙ ПРОГОН ПРОЙДЕН")
    say(f"  режим:        {provider}")
    say(f"  общее время:  {elapsed:.1f} с")
    say()
    say("  Проект получен по HTTP, сохранён в базе, версии сохраняются целиком.")
    say("  Это ПРОЕКТ, а не решение суда. Решение принимает человек.")
    return 0


def main() -> int:
    # Логи httpx зас��оняют отчёт: запросы и так видно по этапам.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    parser = argparse.ArgumentParser(description="Сквозной прогон CourtDraft по HTTP")
    parser.add_argument(
        "--provider", choices=["ollama", "mock"], default="ollama",
        help="ollama — настоящая модель; mock — мгновенная заглушка",
    )
    args = parser.parse_args()

    try:
        return asyncio.run(run(args.provider))
    except KeyboardInterrupt:
        say("\nПрервано.")
        return 130
    finally:
        asyncio.run(db.disconnect())


if __name__ == "__main__":
    raise SystemExit(main())
