"""Проверка контракта интерфейса.

Интерфейс — это приложение.js, и у него нет тестов: браузерные тесты
требуют отдельного стека. Но у него есть контракт — последовательность
вызовов API. Этот скрипт повторяет её ровно так, как делает страница,
и падает на первом несовпадении.

Что проверяется по шагам:
1. /api/info — версия и режим в шапке;
2. /api/cases — список дел в боковой панели;
3. /api/demo/manifest + /api/demo/{файл} — кнопка «Создать демо-дело»;
4. POST /api/cases и POST /api/cases/{id}/documents — то же, из интерфейса;
5. GET /api/cases/{id}/documents — список материалов;
6. POST /api/cases/{id}/draft — запуск формирования;
7. GET /api/jobs/{id} — опрос состояния;
8. GET /api/cases/{id}/draft — то, что рисует страница;
9. GET /api/cases/{id}/draft/versions — история версий;
10. POST /api/drafts/{id}/versions — сохранение правки;
11. GET /api/cases/{id}/evidence — источники по разделам.

Запуск:
    .venv\\Scripts\\python.exe scripts\\check_ui_contract.py
    .venv\\Scripts\\python.exe scripts\\check_ui_contract.py --base http://127.0.0.1:8010
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# S310 — весь смысл этого файла в обращении к локальному HTTP-сервису по
# адресу, переданному в командной строке. Схема проверяется в _open():
# допускаются только http и https.
# ruff: noqa: S310

DEFAULT_BASE = "http://127.0.0.1:8010"

failures: list[str] = []
step_number = 0


def _open(request: urllib.request.Request):  # noqa: ANN201 - соединение
    """Открыть соединение к локальному сервису.

    Отдельная функция нужна не для красоты: линтер справедливо требует
    проверять схему URL, а здесь она всегда http — параметр адреса
    приходит из командной строки, и молчаливый вызов без проверки схемы
    дал бы возможность открыть произвольный обработчик.
    """
    parsed = urllib.parse.urlparse(request.full_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Допустимы только http и https, получено: {parsed.scheme!r}")
    return urllib.request.urlopen(request, timeout=300)


def step(title: str) -> None:
    global step_number
    step_number += 1
    print(f"\n{step_number}. {title}")


def check(condition: bool, message: str) -> bool:
    if condition:
        print(f"   ok   {message}")
    else:
        print(f"   FAIL {message}")
        failures.append(message)
    return condition


def get(base: str, path: str):  # noqa: ANN201 - ответ сервера
    request = urllib.request.Request(base + path, method="GET")
    try:
        with _open(request) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def post(base: str, path: str, payload: dict):  # noqa: ANN201
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        base + path, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with _open(request) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка контракта интерфейса")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    base = args.base.rstrip("/")

    print(f"Проверка контракта интерфейса: {base}")

    step("Шапка: /api/info")
    status, raw = get(base, "/api/info")
    check(status == 200, "информация о сервисе получена")
    info = json.loads(raw) if status == 200 else {}
    check("version" in info, "есть версия для шапки")
    check(bool(info.get("llm_provider")), "есть режим модели для шапки")

    step("Боковая панель: /api/cases")
    status, raw = get(base, "/api/cases?limit=50")
    check(status == 200, "список дел получен")
    cases = json.loads(raw) if status == 200 else {}
    check("items" in cases, "список дел в формате items")

    step("Кнопка «Создать демо-дело»: /api/demo/manifest")
    status, raw = get(base, "/api/demo/manifest")
    check(status == 200, "манифест демо-дела получен")
    manifest = json.loads(raw) if status == 200 else {}
    check(bool(manifest.get("warning")), "манифест помечен как синтетический")
    documents = manifest.get("documents", [])
    check(len(documents) > 0, f"манифест перечисляет документы ({len(documents)})")

    step("Загрузка материалов демо-дела")
    first = documents[0]["filename"]
    status, raw = get(base, f"/api/demo/{first}")
    check(status == 200, f"файл {first} отдаётся")
    check(len(raw) > 100, f"файл {first} непустой")

    step("Обход каталога невозможен")
    status, _ = get(base, "/api/demo/..%2F..%2F.env")
    check(status == 404, "чтение файла вне демо-каталога запрещено")

    step("Создание дела через API")
    number = f"UI-{int(time.time()) % 100000}"
    status, raw = post(base, "/api/cases", {
        "case_number": number,
        "court_name": "Проверка интерфейса",
        "case_type": "civil",
        "category": "договорные споры",
        "is_synthetic": True,
    })
    check(status == 201, f"дело {number} создано")
    case = json.loads(raw) if status == 201 else {}
    case_id = case.get("id", "")

    step("Загрузка материалов дела")
    uploaded = 0
    upload_errors: list[str] = []
    for entry in documents:
        file_status, file_raw = get(base, f"/api/demo/{entry['filename']}")
        if file_status != 200:
            upload_errors.append(
                f"{entry['filename']}: чтение демо-файла вернуло {file_status}"
            )
            continue

        status, error_raw = post(base, f"/api/cases/{case_id}/documents", {
            "filename": entry["filename"],
            "document_type": entry["document_type"],
            "mime_type": "text/plain",
            "text": file_raw.decode("utf-8"),
        })
        if status == 201:
            uploaded += 1
        else:
            # Причина обязана попасть в вывод: молчаливый счётчик
            # «загружено 0 из 6» не позволяет понять, что именно сломалось.
            upload_errors.append(
                f"{entry['filename']}: HTTP {status} "
                f"{error_raw[:200].decode('utf-8', errors='replace')}"
            )

    check(
        uploaded == len(documents),
        f"загружено {uploaded} из {len(documents)}"
        + (f" — {upload_errors[0]}" if upload_errors else ""),
    )

    status, raw = get(base, f"/api/cases/{case_id}/documents")
    listed = json.loads(raw) if status == 200 else []
    check(len(listed) == len(documents), "список материалов дела совпадает")

    step("Кнопка «Сформировать проект»")
    status, raw = post(base, f"/api/cases/{case_id}/draft", {"actor": "judge"})
    check(status == 202, "формалирование принято в фоне")
    job = json.loads(raw) if status == 202 else {}
    check(bool(job.get("job_id")), "возвращён job_id для опроса")
    check(job.get("is_draft") is True, "ответ помечен как проект")
    check("не решение суда" in str(job.get("disclaimer", "")), "есть предупреждение")

    step("Опрос состояния задачи")
    state = "PENDING"
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        _, raw = get(base, f"/api/jobs/{job.get('job_id')}")
        state = json.loads(raw).get("state", "")
        if state in {"DONE", "FAILED"}:
            break
        time.sleep(5)
    check(state == "DONE", f"задача завершилась успешно (состояние: {state})")

    step("Показ проекта: /api/cases/{id}/draft")
    status, raw = get(base, f"/api/cases/{case_id}/draft")
    check(status == 200, "проект получен")

    parsed: object = json.loads(raw) if status == 200 else None
    if not isinstance(parsed, dict):
        # Ответ может быть null: это законный ответ, когда проекта нет.
        # Дальше идти бессмысленно, но сказать об этом нужно явно.
        check(False, f"проект вернул не объект: {str(parsed)[:120]}")
        print("\n" + "=" * 70)
        print(f"ПРОВАЛЕНО проверок: {len(failures)}")
        for item in failures:
            print(f"  - {item}")
        return 1
    draft: dict = parsed
    check(len(draft.get("sections", [])) > 0, "есть разделы для отрисовки")
    check(bool(draft.get("text")), "есть текст проекта")
    check(draft.get("is_draft") is True, "проект помечен как проект")
    check("не решение суда" in str(draft.get("disclaimer", "")), "есть предупреждение")

    verification = draft.get("verification") or {}
    check(bool(verification.get("status")), "есть результат проверки для блока")
    check("issues" in verification, "есть список замечаний")
    check("unsupported_claims" in verification, "есть счётчик без источника")

    flagged = [s for s in draft.get("sections", []) if s.get("needs_review")]
    check(
        len(flagged) > 0,
        f"есть разделы с пометкой «требует проверки» ({len(flagged)})",
    )

    step("Источники по разделам")
    check(len(draft.get("sources", [])) > 0, "есть список источников")
    status, raw = get(base, f"/api/cases/{case_id}/evidence")
    evidence = json.loads(raw) if status == 200 else {}
    check(evidence.get("facts", 0) > 0, "пакет доказательств отдан")
    if evidence.get("items"):
        item = evidence["items"][0]
        check(bool(item.get("source", {}).get("document")), "у факта есть источник")

    step("История версий")
    status, raw = get(base, f"/api/cases/{case_id}/draft/versions")
    versions_body = json.loads(raw) if status == 200 else {}
    versions = versions_body.get("versions", [])
    check(len(versions) == 1, f"версия одна ({len(versions)})")
    if versions:
        check(versions[0].get("author") == "ai", "автор первой версии — модель")

    step("Сохранение правки из редактора")
    edited = draft.get("text", "") + "\n\nПРАВКА ИЗ ИНТЕРФЕЙСА."
    status, raw = post(base, f"/api/drafts/{draft.get('id')}/versions", {
        "text": edited,
        "author": "judge",
        "comment": "правка из интерфейса",
    })
    check(status == 201, "правка сохранена")
    new_version = json.loads(raw) if status == 201 else {}
    check(new_version.get("version") == 2, "создана вторая версия")

    status, raw = get(base, f"/api/cases/{case_id}/draft/versions")
    versions = json.loads(raw).get("versions", [])
    check(len(versions) == 2, "обе версии на месте")
    if len(versions) == 2:
        check(
            versions[0]["text"] != versions[1]["text"],
            "первая версия не затёрта второй",
        )
        check(versions[1]["author"] == "judge", "автор правки — судья")

    print()
    print("=" * 70)
    if failures:
        print(f"ПРОВАЛЕНО проверок: {len(failures)}")
        for item in failures:
            print(f"  - {item}")
        return 1

    print(f"Все {step_number} шагов контракта интерфейса пройдены.")
    print("Интерфейс может выполнять весь путь: дело -> проект -> проверка -> правка.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
