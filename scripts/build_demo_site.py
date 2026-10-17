"""Собрать статическое демо для сайта.

Заказчику показывают сайт, а не свою машину: онлайн-схемы нет, ставить
код на чужой компьютер заказчик не станет. Поэтому демо на сайте должно
работать само, без сервера и без модели.

Собирается оно из настоящего выхода демо-стенда
(data/demo/output/result.json), а не пишется руками. Причина: руками
написанное демо через месяц перестаёт совпадать с продуктом, и на
встрече выясняется, что показывали не то.

ОДНО ЖЁСТКОЕ ПРАВИЛО: В САЙТ ПОПАДАЮТ ТОЛЬКО СИНТЕТИЧЕСКИЕ МАТЕРИАЛЫ.

Материалы дел не выходят с машины, это требование продукта. Скрипт
проверяет маркер синтетичности в выходных данных и отказывается
собирать сайт, если маркера нет: одна ошибка в этом месте означала бы
публикацию чужих персональных данных на публичном сайте.

Запуск:
    python scripts/build_demo_site.py

    python scripts/build_demo_site.py --check-only
        Только проверка, ничего не пишется. Именно этот режим запускает
        публикация сайта: пропустить в публикацию данные, которые не
        прошли проверку на синтетичность, нельзя.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "demo" / "output" / "result.json"
DEMO_DIR = ROOT / "data" / "demo"
SITE_DEMO = ROOT / "site" / "demo"
APP_STYLES = ROOT / "frontend" / "styles.css"

#: Что должно быть в маркере синтетичности. Проверяется без учёта
#: регистра и лишних пробелов: строка приходит из манифеста демо.
SYNTHETIC_MARKERS = ("synthetic", "синтетич")


def fail(message: str) -> int:
    print(f"ОШИБКА: {message}")
    return 1


def check_synthetic(data: dict[str, Any]) -> str | None:
    """Убедиться, что данные демонстрационные.

    None — данные годятся. Иначе — причина отказа.
    """
    warning = str(data.get("warning", "")).lower()
    if not any(marker in warning for marker in SYNTHETIC_MARKERS):
        return (
            "в выходных данных нет маркера синтетичности "
            f"(warning={data.get('warning')!r}). Публиковать такие данные "
            "на публичном сайте нельзя: материалы дел не покидают машину."
        )

    for item in data.get("evidence_pack", {}).get("items", []):
        if not item.get("text"):
            return "в пакете доказательств есть факт без текста"
    return None


def build_documents(
    items: list[dict[str, Any]], manifest: dict[str, Any]
) -> list[dict[str, str]]:
    """Документы дела: имя, тип и число фактов, взятых из них.

    Список берётся из манифеста, а не из пакета доказательств: пакет
    содержит только те документы, из которых удалось что-то извлечь, и
    на сайте исчезли бы материалы, по которым фактов не нашлось. Для
    показа это неверно — судья видит все материалы дела, включая те,
    из которых ничего извлечь не удалось.
    """
    facts_per_document: dict[str, int] = {}
    types: dict[str, str] = {}
    for item in items:
        name = str(item.get("source", ""))
        if not name:
            continue
        facts_per_document[name] = facts_per_document.get(name, 0) + 1
        types.setdefault(name, str(item.get("document_type", "")))

    documents: list[dict[str, str]] = []
    for entry in manifest.get("documents", []):
        name = str(entry.get("filename", ""))
        if not name:
            continue
        documents.append(
            {
                "name": name,
                "title": str(entry.get("title", "")),
                "document_type": str(
                    entry.get("document_type") or types.get(name, "")
                ),
                "characters": str(entry.get("characters", "")),
                "facts": str(facts_per_document.get(name, 0)),
            }
        )

    # Документы, которых нет в манифесте, но которые есть в пакете:
    # молча пропускать их нельзя, иначе сайт разойдётся с продуктом.
    known = {d["name"] for d in documents}
    for name in sorted(set(facts_per_document) - known):
        documents.append(
            {
                "name": name,
                "title": "",
                "document_type": types.get(name, ""),
                "characters": "",
                "facts": str(facts_per_document[name]),
            }
        )
    return documents


def build(
    payload: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, Any]:
    """Собрать данные статического демо из выхода стенда."""
    pack = payload.get("evidence_pack", {})
    draft = payload.get("draft", {})
    verification = payload.get("verification", {})

    sections = [
        {
            "key": section.get("key", ""),
            "name": section.get("name", ""),
            "text": section.get("text", ""),
            "is_mock": bool(section.get("is_mock", False)),
            "needs_review": bool(section.get("needs_review", False)),
            "citations": [str(c) for c in section.get("citations", [])],
        }
        for section in draft.get("sections", [])
    ]

    return {
        "warning": payload.get("warning", ""),
        "mode": payload.get("mode", ""),
        "model": payload.get("model", ""),
        "case_number": payload.get("case_number", ""),
        "court_name": str(manifest.get("court") or pack.get("court_name", "")),
        "category": str(manifest.get("category", "")),
        "hearing_date": str(manifest.get("hearing_date", "")),
        "claim_amount": manifest.get("claim_amount", 0),
        "plaintiff": str(manifest.get("plaintiff", "")),
        "defendant": str(manifest.get("defendant", "")),
        "participants": [str(p) for p in pack.get("participants", [])],
        "documents": build_documents(pack.get("items", []), manifest),
        "sections": sections,
        "sources": [str(s) for s in draft.get("sources", [])],
        "verification": {
            "status": verification.get("status", ""),
            "sections_checked": verification.get("sections_checked", 0),
            "claims_checked": verification.get("claims_checked", 0),
            "unsupported_claims": verification.get("unsupported_claims", 0),
            "by_severity": verification.get("by_severity", {}),
            "issues": [
                {
                    "type": issue.get("type", ""),
                    "severity": issue.get("severity", ""),
                    "reason": issue.get("reason", ""),
                    "section": issue.get("section", ""),
                }
                for issue in verification.get("issues", [])
            ],
        },
    }


def check_only(data: dict[str, Any]) -> int:
    """Проверить опубликованные данные, ничего не записывая.

    Публикация сайта запускает только этот режим. Он отвечает на два
    вопроса, и оба обязательные:

    1. Опубликованные данные синтетические. Их читает уже не сборщик,
       а любой посетитель сайта, поэтому проверка повторяется на том
       файле, который попадёт наружу.
    2. Опубликованные данные совпадают с последним прогоном стенда.
       Разошлись — значит на сайте лежит устаревшее демо, а заказчику
       показывают не то, что система выдаёт сейчас.
    """
    published_path = SITE_DEMO / "demo-data.json"
    if not published_path.exists():
        return fail(
            f"нет {published_path}. Соберите демо: python scripts/build_demo_site.py"
        )

    published = json.loads(published_path.read_text(encoding="utf-8"))
    problem = check_synthetic(published)
    if problem is not None:
        return fail("опубликованные данные не прошли проверку: " + problem)

    if published != data:
        return fail(
            "опубликованное демо разошлось с последним прогоном стенда. "
            "Пересоберите: python scripts/build_demo_site.py и закоммитьте "
            "site/demo/demo-data.json"
        )

    # Копия стилей интерфейса тоже должна совпадать с оригиналом.
    # Она попадает в публикацию как готовый файл, поэтому расхождение
    # означало бы, что на сайте демо выглядит не так, как продукт.
    published_css = SITE_DEMO / "app.css"
    if not published_css.exists():
        return fail(
            f"нет {published_css}. Пересоберите: python scripts/build_demo_site.py"
        )
    if published_css.read_text(encoding="utf-8") != APP_STYLES.read_text(
        encoding="utf-8"
    ):
        return fail(
            "site/demo/app.css разошёлся с frontend/styles.css. "
            "Пересоберите: python scripts/build_demo_site.py"
        )

    print("OK — опубликованное демо синтетическое и совпадает со стендом.")
    print(f"  дело       : {published['case_number']}")
    print(f"  разделов   : {len(published['sections'])}")
    print(f"  проверка   : {published['verification']['status']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    check = "--check-only" in args

    if not SOURCE.exists():
        return fail(
            f"нет {SOURCE}. Сначала соберите стенд: "
            "powershell -File scripts\\start-demo.ps1 -Rebuild"
        )

    payload = json.loads(SOURCE.read_text(encoding="utf-8"))

    manifest_path = DEMO_DIR / "manifest.json"
    if not manifest_path.exists():
        return fail(f"нет {manifest_path}: без манифеста не собрать материалы дела")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    problem = check_synthetic(payload)
    if problem is not None:
        return fail(problem)

    data = build(payload, manifest)
    if not data["sections"]:
        return fail("в выходных данных нет ни одного раздела проекта")

    if check:
        return check_only(data)

    SITE_DEMO.mkdir(parents=True, exist_ok=True)
    data_path = SITE_DEMO / "demo-data.json"
    data_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Стили интерфейса копируются, а не переписываются: демо на сайте
    # должно выглядеть как продукт, иначе это макет, а не демонстрация.
    shutil.copyfile(APP_STYLES, SITE_DEMO / "app.css")

    mock_count = sum(1 for s in data["sections"] if s["is_mock"])
    print(f"демо собрано: {SITE_DEMO}")
    print(f"  дело            : {data['case_number']}")
    print(f"  документов      : {len(data['documents'])}")
    print(f"  разделов        : {len(data['sections'])} (из них заглушек: {mock_count})")
    print(f"  источников      : {len(data['sources'])}")
    print(
        f"  проверка        : {data['verification']['status']}, "
        f"замечаний: {len(data['verification']['issues'])}"
    )
    print(f"  данные          : {data_path}")
    if mock_count:
        print()
        print(
            "  ВНИМАНИЕ: часть разделов — служебные заглушки, модель не "
            "подключена."
        )
        print("  Это честное состояние стенда, на сайте оно и подано.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
