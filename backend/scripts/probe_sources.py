"""Разведка источников судебных актов: где лежат решения и пригодны ли они.

Скрипт проверен на живых сайтах и печатает отчёт с фактами. Хранится
не для повторного обхода, а как запись того, что выяснено при работе:
чтобы не открывать заново то, что уже установлено, и чтобы выводы
не выглядели догадками.

ЗАПУСК
    .venv\\Scripts\\python.exe -X utf8 scripts\\probe_sources.py

ВЫВОД
    C:\\Users\\diorl\\AppData\\Local\\Temp\\opencode\\sources_report.txt

УСТАНОВЛЕНО ПРОВЕРКОЙ (2026-10)
------------------------------------------------------------------
1. ГАС «Правосудие» sudrf.ru — список участков отдаётся, но карточка
   участка (/index.php?id=61MS0001) не отдаётся: таймаут даже с cookie,
   Referer и ожиданием 120 секунд. Источник непригоден для обхода.

2. sudact.ru — единственный рабочий источник, путь найден полностью:
       /magistrate/area/OITmobeLEuxJ/   Ростовская область
       /magistrate/court/<id>/           участок, ~230 на область
       /magistrate/doc/<id>/             текст дела
   Карточка суда отдаёт ровно 10 дел, ссылок пагинации нет.
   Поисковая форма раздела (/magistrate/) возвращает 0 дел при любом
   запросе — то есть фильтры там не работают.

3. Тексты обезличены. Вместо ФИО печатается «ФИО2» (12 вхождений в
   первом документе), дни и номера вырезаны: «в минут», «с минут
   по часов», пустые ОГРН, ИНН, адреса. Даты вида «13 июля 2017 года»
   сохраняются, а числа — нет.

4. Это административные постановления (ст. 12.7, 12.8, 19.7 КоАП),
   а не гражданские решения по ГПК РФ. Маркер «истец» в выборке не
   встречается ни разу.

ВЫВОД
   Собирать корпус из этого источника для дообучения нельзя. Тексты
   обезличены до неузнаваемости реквизитов — модель, обученная на них,
   выучит пустоты на месте ФИО, дат и сумм, то есть ровно то, чего
   система обязана не выдумывать. И нужных нам гражданских дел там
   нет: под мировыми судьями в выдаче лежат административные дела.

   Полезно это может быть только как способ проверить разметку и
   структуру реквизитов — не как обучающая выборка.

ПРАВИЛА ОБХОДА, ПРИМЕНЁННЫЕ ЗДЕСЬ
   Пауза между запросами 3-5 секунд, один поток, никакого параллелизма.
   Сайты государственные; десяток параллельных запросов означал бы
   и невежливость, и блокировку.
"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from pathlib import Path

# S310 — весь смысл скрипта в обращении к государственным сайтам по
# адресам со схемой http, зашитым в исходник. Схема не берётся извне.
# ruff: noqa: S310

REPORT = Path(
    r"C:\Users\diorl\AppData\Local\Temp\opencode\sources_report.txt"
)

# Пауза между запросами. Сайты государственные: обходить их десятками
# параллельных соединений нельзя — это и невежливо, и приводит к
# блокировке. Один поток с паузой — единственный приемлемый режим.
PAUSE_SEC = 4.0
TIMEOUT = 60

# Идентификатор латиницей: заголовки HTTP обязаны быть в latin-1,
# кириллица в User-Agent ломает запрос ещё до отправки.
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CourtDraft-Research/0.1"

ROSTOV_AREA = "https://sudact.ru/magistrate/area/OITmobeLEuxJ/"
SAMPLE_COURT = "https://sudact.ru/magistrate/court/tjIxQBnK6vdX/"

# Признаки обезличивания: сайт вычистил персональные данные.
ANONYMISATION = r"ФИО\d"

# Признаки гражданского иска. Наша система работает с такими делами
# (ст. 209-211 ГПК РФ), а не с административными постановлениями.
CIVIL_MARKERS = (
    "истец",
    "ответчик",
    "исковые требования",
    "взыскать",
    "ОПРЕДЕЛИЛ",
    "ГПК",
)


def fetch(url: str, referer: str | None = None) -> tuple[int, str]:
    """Забрать страницу. Кодировку определяем по заголовку ответа."""
    headers = {"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9"}
    if referer:
        headers["Referer"] = referer
    request = urllib.request.Request(url, headers=headers)
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
    """Текст страницы без разметки."""
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = re.sub(r"&nbsp;", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def main() -> int:
    lines: list[str] = ["РАЗВЕДКА ИСТОЧНИКОВ СУДЕБНЫХ АКТОВ\n"]
    lines.append("=" * 70 + "\n\n")

    # 1. Карточка участка на sudact: сколько дел и есть ли пагинация.
    status, html = fetch(SAMPLE_COURT)
    docs = sorted(set(re.findall(r"/magistrate/doc/([\w-]+)/", html)))
    links = re.findall(r"href=['\"]([^'\"]+)['\"]", html, re.I)
    pager = [
        link for link in links if re.search(r"(page|start|offset|p=)", link, re.I)
    ]
    lines.append(f"1. КАРТОЧКА УЧАСТКА\n{SAMPLE_COURT}\n")
    lines.append(f"   статус {status}, дел {len(docs)}, ссылок пагинации {len(pager)}\n")
    lines.append(f"   пагинация отсутствует: {not pager}\n\n")

    # 2. Берём тексты дел и смотрим, что в них осталось от реквизитов.
    lines.append("2. ТЕКСТЫ ДЕЛ\n")
    for doc in docs[:3]:
        status, body = fetch(f"https://sudact.ru/magistrate/doc/{doc}/", SAMPLE_COURT)
        text = clean(body) if body else ""
        anonymised = len(re.findall(ANONYMISATION, text, re.I))
        holes = len(re.findall(r"в\s+минут", text, re.I))
        civil = {m: text.lower().count(m.lower()) for m in CIVIL_MARKERS}
        admin = text.lower().count("административн")

        title = re.search(r"<title>(.*?)</title>", body or "", re.S | re.I)
        lines.append(f"   дело {doc}: статус {status}, {len(text)} симв.\n")
        if title:
            lines.append(f"      {title.group(1).strip()[:90]}\n")
        lines.append(f"      «ФИО<n>» (обезличено): {anonymised}\n")
        lines.append(f"      «в минут» (дыры в реквизитах): {holes}\n")
        lines.append(f"      упоминаний «административн»: {admin}\n")
        lines.append(f"      признаков гражданского иска: "
                     f"{ {k: v for k, v in civil.items() if v} }\n\n")
        time.sleep(PAUSE_SEC)

    # 3. Границы пригодности — вывод, который важнее самих цифр.
    lines.append("3. ВЫВОД\n")
    lines.append(
        "   Источник найден и технически обходится, но для обучения\n"
        "   непригоден по двум причинам:\n\n"
        "   а) тексты обезличены до неузнаваемости реквизитов — вместо\n"
        "      ФИО стоит «ФИО<n>», вырезаны дни, номера, суммы и адреса.\n"
        "      Модель, обученная на таком, выучит пустоты на месте\n"
        "      ФИО, дат и сумм — то есть ровно то, чего система обязана\n"
        "      не выдумывать;\n"
        "   б) в выдаче под мировыми судьями лежат административные\n"
        "      постановления (ст. 12.7, 12.8, 19.7 КоАП), а нужны\n"
        "      гражданские решения по ГПК РФ.\n\n"
        "   Дополнительное ограничение: карточка суда отдаёт ровно\n"
        "   10 дел без пагинации, а поисковая форма возвращает ноль\n"
        "   при любом запросе. Сколько-нибудь полный корпус не собрать.\n"
    )

    REPORT.write_text("".join(lines), encoding="utf-8")
    print(f"записано: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
