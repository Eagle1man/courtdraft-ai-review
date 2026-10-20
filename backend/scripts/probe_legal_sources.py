"""Проверить, есть ли законные источники гражданских решений судов общей
юрисдикции — и пригодны ли они для корпуса.

Контекст. Пользователь спросил, где законно взять образцы судебных
решений РФ по гражданским делам. Проверены условия использования
(robots.txt) и доступность официальных источников:

  publication.pravo.gov.ru — официальное опубликование правовых актов.
    robots запрещает только служебные разделы, НЕ тексты актов.
  vsrf.ru — Верховный Суд, robots открыт, запрещены /api/, /internal/.
  sudrf.ru — ГАС «Правосудие». /index.php?id=300 (суды общей
    юрисдикции) ЗАПРЕЩЁН robots. Остальное открыто.
  sudact.ru — открыт, но обезличивает.
  bsr.vedrf.ru — не резолвится с этой машины.

Что проверяется здесь: действительно ли у официальных источников есть
гражданские решения, а не только административные дела. Это решает,
существует ли вообще законный путь.

Запуск:
    .venv\\Scripts\\python.exe -X utf8 scripts\\probe_legal_sources.py
"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from pathlib import Path

# S310 — скрипт обращается к государственным сайтам по адресам со схемой
# http, зашитым в исходник. Схема не берётся извне.
# ruff: noqa: S310

REPORT = Path(
    r"C:\Users\diorl\AppData\Local\Temp\opencode\legal_sources.txt"
)

PAUSE_SEC = 4.0
TIMEOUT = 45
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CourtDraft-Research/0.1"

# Признаки гражданского иска: система работает с такими делами
# (ст. 209-211 ГПК РФ), а не с административными постановлениями.
CIVIL = ("истец", "ответчик", "исковые требования", "взыскать", "ОПРЕДЕЛИЛ")

TARGETS = [
    (
        "pravo_главная",
        "http://publication.pravo.gov.ru/",
        "официальное опубликование правовых актов",
    ),
    (
        "pravo_поиск",
        "http://publication.pravo.gov.ru/Search/Index",
        "поиск по опубликованным актам",
    ),
    (
        "vsrf_практика",
        "https://www.vsrf.ru/lk/practice",
        "судебная практика Верховного Суда",
    ),
    (
        "sudrf_открытый_раздел",
        "https://sudrf.ru/index.php?id=300&act=goToMS&ms_format=html",
        "открытая ветка ГАС (не запрещённая robots)",
    ),
    (
        "sudrf_карточка_дела",
        "https://sudrf.ru/robots.txt",
        "сама карточка: что отдаёт сервер на первый запрос",
    ),
]


def fetch(url: str) -> tuple[int, str]:
    request = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            status = response.status
            charset = response.headers.get_content_charset() or "utf-8"
            raw = response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception as exc:  # noqa: BLE001
        return 0, f"ОШИБКА: {type(exc).__name__}: {exc}"

    for candidate in (charset, "utf-8", "cp1251"):
        try:
            return status, raw.decode(candidate)
        except (UnicodeDecodeError, LookupError):
            continue
    return status, raw.decode("utf-8", errors="replace")


def clean(html: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = re.sub(r"&nbsp;", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def main() -> int:
    lines: list[str] = ["ЗАКОННЫЕ ИСТОЧНИКИ ГРАЖДАНСКИХ РЕШЕНИЙ\n"]
    lines.append("=" * 70 + "\n\n")

    for name, url, description in TARGETS:
        status, body = fetch(url)
        lines.append(f"--- {name}\n{url}\n    {description}\n")
        lines.append(f"    статус {status}, {len(body)} байт\n")

        if not body:
            lines.append(f"    {body[:160]}\n\n")
            time.sleep(PAUSE_SEC)
            continue

        if name == "sudrf_карточка_дела":
            lines.append("    это robots.txt, смотрим правила:\n")
            for rule in body.splitlines()[:8]:
                lines.append(f"      {rule}\n")
            lines.append("\n")
            time.sleep(PAUSE_SEC)
            continue

        text = clean(body)
        markers = {m: text.lower().count(m.lower()) for m in CIVIL}
        found = {k: v for k, v in markers.items() if v}
        lines.append(f"    признаков гражданского иска: {found or 'нет'}\n")
        lines.append(f"    упоминаний «суд общей юрисдикции»: "
                     f"{text.lower().count('общей юрисдикции')}\n")

        title = re.search(r"<title>(.*?)</title>", body, re.S | re.I)
        if title:
            lines.append(f"    заголовок: {title.group(1).strip()[:100]}\n")

        lines.append(f"    начало текста: {text[:300]}\n\n")
        time.sleep(PAUSE_SEC)

    REPORT.write_text("".join(lines), encoding="utf-8")
    print(f"записано: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
