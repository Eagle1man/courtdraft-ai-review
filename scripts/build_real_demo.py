"""Собрать демо-дело из настоящего судебного решения.

Зачем: синтетическое дело показывает конвейер, но не показывает
продукт. Заказчику интереснее смотреть, как система работает с
настоящим делом — тем более, что рядом можно показать, как именно
это дело суд решил.

Что делает скрипт:

1. Берёт решение из корпуса реальных решений (Hugging Face
   TryDotAtwo/russian-legal-ner). Корпус уже частично обезличен:
   фамилии заменены на <ФИО1>, адреса на <АДРЕС>. Судьи, секретари и
   названия организаций в нём не обезличены — это обезличивает скрипт
   сам.
2. Раскладывает решение на материалы дела: иск, возражения ответчика,
   ход заседания, установленные судом обстоятельства. Резолютивная
   часть в материалы НЕ попадает: её система должна построить сама,
   иначе демо показывает пересказ чужого решения, а не работу системы.
3. Сохраняет резолютивную часть суда отдельно — как эталон для
   сравнения.

ПРАВИЛО ОБ ПУБЛИКАЦИИ

Материалы дел не должны покидать машину. Решение из корпуса — не
материал клиента, но лицензия корпуса («other», права не определены)
не даёт права публиковать его фрагменты на публичном сайте. Поэтому
скрипт помечает демо как ЛОКАЛЬНОЕ, а сборщик сайта отказывается
публиковать такие данные. Публичная версия демо остаётся на
синтетическом деле.

Запуск:
    python scripts/build_real_demo.py
    python scripts/build_real_demo.py --check-only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = ROOT / "data" / "demo"
#: Реальное дело живёт отдельно от синтетического: у них разные
#: правила публикации, и смешивать их в одном каталоге нельзя.
REAL_DIR = DEMO_DIR / "real"
PARQUET_URL = (
    "https://huggingface.co/datasets/TryDotAtwo/russian-legal-ner/"
    "resolve/main/data/test.parquet"
)
DEFAULT_PARQUET = Path(r"D:\ollama\hf_test.parquet")

#: Тип документа по имени файла: конвейер различает иск, возражения,
#: договор и прочее по типу, а не по имени.
DOCUMENT_TYPES = {
    "00_case_info.txt": "CASE_INFO",
    "01_claim.txt": "CLAIM",
    "02_response.txt": "RESPONSE",
    "05_protocol.txt": "PROTOCOL",
    "06_court_findings.txt": "FINDINGS",
}

#: Что считаем настоящим решением по гражданскому делу.
CIVIL_MARKERS = ("гражданское дело", "Гражданское дело", "ГРАЖДАНСКОЕ ДЕЛО")
OPERATIVE_MARKERS = ("РЕШИЛ:", "ОПРЕДЕЛИЛ:", "И СЧИТАЮ ВОЗМЕННЫМ", "РЕШИЛ :")
FINDINGS_MARKERS = ("УСТАНОВИЛ", "находит иск", "Исследовав материалы дела")

# ── Обезличивание ──────────────────────────────────────────────────────
#
# Порядок важен: сначала организации и ФИО, потом номера дел и города.
# Иначе маска города наезжала бы на уже замаскированное имя.
ANONYMISATION_RULES: list[tuple[re.Pattern[str], str]] = [
    # Организации: ООО «Газпром межрегионгаз Волгоград» и подобные.
    (
        re.compile(
            r"(?:Обществ\w*|Открыт\w*|Закрыт\w*|Публичн\w*|Акционерн\w*|"
            r"Государственн\w*|Муниципальн\w*)[^.\n]{0,60}?"
            r"[\"«][^\"»\n]{2,60}[\"»]"
        ),
        "Организация",
    ),
    (re.compile(r"\b(?:ООО|ОАО|ЗАО|ПАО|ГУП|МУП)\b"), "Организация"),
    # Название в кавычках после уже заменённой аббревиатуры: без этого
    # «Организация «ПТС-Сервис»» оставалось с настоящим названием.
    (
        re.compile(r"(Организация)\s*[\"«][^\"»\n]{2,60}[\"»]"),
        r"\1",
    ),
    # Фамилия И.О. и Фамилия И.И. — судьи, секретари, представители.
    # Между инициалами в подписях стоят неразрывные пробелы и их пара
    # («Н.Ю.\xa0 Лямин»), поэтому `\s*`, а не `\s?`: с одним символом
    # фамилия судьи оставалась в опубликованных манифестах.
    (
        re.compile(
            r"[А-ЯЁ][а-яё]{2,}(?:-[А-ЯЁ][а-яё]{2,})?\s+"
            r"[А-ЯЁ]\.\s*[А-ЯЁ]\.?"
        ),
        "ФИО",
    ),
    # И.О. Фамилия: в подписях встречается без пробела — «Э.Н.Грищенко».
    (
        re.compile(r"[А-ЯЁ]\.\s*[А-ЯЁ]\.\s*[А-ЯЁ][а-яё]{2,}"),
        "ФИО",
    ),
    # Фамилия с одним инициалом: поле court в манифесте обрезалось по
    # первой точке («Синяева И.О.» → «Синяева И»), и такая обрубленная
    # фамилия уходила наружу. Точка после буквы здесь не исключается —
    # отдельного правила для «Фамилия И.» нет, а это та же утечка.
    (
        re.compile(r"[А-ЯЁ][а-яё]{2,}\s+[А-ЯЁ](?![а-яёА-ЯЁ])"),
        "ФИО",
    ),
    # Фамилия с меткой корпуса: «Мездрика <ФИО1>» — фамилия осталась
    # настоящей, метка закрыла только имя. Пробела перед меткой может
    # не быть: в корпусе встречается «Романова<ФИО>», и с требованием
    # пробела фамилия оставалась в опубликованных материалах дела.
    (re.compile(r"[А-ЯЁ][а-яё]{2,}\s*<ФИО\d*>"), "ФИО"),
    # Полные ФИО: Фамилия Имя Отчество.
    (
        re.compile(
            r"[А-ЯЁ][а-яё]{2,}\s+[А-ЯЁ][а-яё]{2,}\s+[А-ЯЁ][а-яё]{2,}"
        ),
        "ФИО",
    ),
    # Номер дела.
    (re.compile(r"(Дело\s*№\s*)[^\s,;\n]{1,30}"), r"\1<НОМЕР>"),
    (re.compile(r"\b\d{2}-\d{3,4}[-/]\d{2,4}\b"), "<НОМЕР>"),
    # Города и населённые пункты.
    (re.compile(r"\bг\.\s*[А-ЯЁ][а-яё-]{3,40}"), "город"),
    (re.compile(r"\bг\.о\.[А-ЯЁ][а-яё-]{3,40}"), "город"),
    (re.compile(r"\bг\.[А-ЯЁ][а-яё-]{3,40}\b"), "город"),
    (re.compile(r"\bс\.\s*[А-ЯЁ][а-яё-]{3,40}"), "село"),
    (re.compile(r"\bпос\.\s*[А-ЯЁ][а-яё-]{3,40}"), "посёлок"),
]

#: Признаки, по которым проверяется, что в тексте не осталось людей.
LEAK_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"[А-ЯЁ][а-яё]{2,}(?:-[А-ЯЁ][а-яё]{2,})?\s+[А-ЯЁ]\.\s*[А-ЯЁ]\.?"
        ),
        "фамилия с инициалами",
    ),
    (
        re.compile(r"[А-ЯЁ][а-яё]{2,}\s+[А-ЯЁ][а-яё]{2,}\s+[А-ЯЁ][а-яё]{2,}"),
        "фамилия, имя, отчество",
    ),
    (re.compile(r"(?:ООО|ОАО|ЗАО|ПАО|ГУП|МУП)\s*[\"«]"), "название организации"),
    (
        re.compile(r"[А-ЯЁ][а-яё]{2,}\s+<ФИО\d*>"),
        "фамилия при метке корпуса",
    ),
    (
        re.compile(r"[А-ЯЁ]\.\s*[А-ЯЁ]\.\s*[А-ЯЁ][а-яё]{2,}"),
        "подпись судьи",
    ),
    # Обрубленная фамилия с одним инициалом: так court_of обрезал поле
    # court по первой точке, и фамилия судьи уходила в манифест.
    (
        re.compile(r"[А-ЯЁ][а-яё]{2,}\s+[А-ЯЁ](?![а-яёА-ЯЁ])"),
        "фамилия с одним инициалом",
    ),
]


def anonymize(text: str) -> str:
    """Обезличить текст решения."""
    cleaned = text
    for pattern, replacement in ANONYMISATION_RULES:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned


def find_leaks(text: str) -> list[str]:
    """Что осталось похожего на персональные данные."""
    found: list[str] = []
    for pattern, label in LEAK_PATTERNS:
        for match in pattern.finditer(text):
            found.append(f"{label}: {match.group(0).strip()[:60]}")
    return found


def load_documents(path: Path) -> list[str]:
    """Загрузить решения из parquet."""
    import pandas as pd

    frame = pd.read_parquet(path)
    return [str(value) for value in frame["text"].tolist()]


def download_parquet(target: Path) -> None:
    """Скачать тестовую часть корпуса, если её нет на машине."""
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"качаю {PARQUET_URL}")
    with urllib.request.urlopen(PARQUET_URL, timeout=600) as response:
        target.write_bytes(response.read())


def split_decision(text: str) -> dict[str, str]:
    """Разложить решение по абзацам на части.

    Решение в корпусе — это плоский текст: заголовок, описание хода
    заседания, обстоятельства, мотивировка, резолютивная часть. Делится
    по абзацам, и каждый абзац относится к части по тому, что в нём
    говорится.
    """
    operative_at = -1
    for marker in OPERATIVE_MARKERS:
        index = text.find(marker)
        if index != -1 and (operative_at == -1 or index < operative_at):
            operative_at = index

    if operative_at == -1:
        return {}

    body = text[:operative_at]
    operative = text[operative_at:]

    # В этих документах абзацы разделены одиночным переводом строки,
    # а не пустой строкой. По пустым строкам текст делился на два
    # огромных куска, и весь разбор бессмысленно уезжал в одну часть.
    paragraphs = [p.strip() for p in body.splitlines() if p.strip()]

    claim: list[str] = []
    defence: list[str] = []
    procedure: list[str] = []
    findings: list[str] = []

    for paragraph in paragraphs:
        lowered = paragraph.lower()
        # Порядок проверок значим: в решениях один и тот же абзац
        # упоминает истца, ответчика и ход заседания, и при неверном
        # порядке половина текста уезжала в «возражения», а требования
        # истца не попадали никуда.
        if any(
            marker in lowered
            for marker in (
                "в судебном заседании",
                "рассмотрев",
                "при секретаре",
                "представител",
                "не явил",
                "заслушали",
                "объявлено",
            )
        ):
            procedure.append(paragraph)
        elif any(
            marker in lowered
            for marker in (
                "обратил",
                "исковые требования",
                "предъявил иск",
                "иск истца",
                "требования истца",
                "просит суд",
            )
        ):
            claim.append(paragraph)
        elif any(
            marker in lowered
            for marker in (
                "возраж",
                "не признает",
                "не согласен",
                "по мнению ответчика",
                "ответчик полагает",
                "в отзыве",
            )
        ):
            defence.append(paragraph)
        else:
            findings.append(paragraph)

    # Реквизиты дела: суд, дата, участники, предмет спора. Отдельно
    # от материалов, потому что именно из них вводная часть.
    header = body[: body.find("УСТАНОВИЛ")] if "УСТАНОВИЛ" in body else ""
    if not header.strip():
        header = paragraphs[0] if paragraphs else ""
    if "рассмотрев" in header:
        before, _, after = header.partition("рассмотрев")
        subject = "рассмотрев" + after
        if subject.strip():
            claim.insert(0, subject.strip())
        header = before

    return {
        "header": header.strip(),
        "claim": "\n\n".join(claim),
        "defence": "\n\n".join(defence),
        "procedure": "\n\n".join(procedure),
        "findings": "\n\n".join(findings),
        "operative": operative.strip(),
    }


def score_candidate(text: str) -> int:
    """Насколько решение годится для демонстрации.

    Важно: оценивается содержание, а не длина. Решение в одну страницу
    без мотивировки показывать нечего.
    """
    if not any(marker in text for marker in CIVIL_MARKERS):
        return 0
    if not any(marker in text for marker in OPERATIVE_MARKERS):
        return 0
    if "заочное" in text.lower():
        # Заочное решение: ответчика не было, спорить не о чем. Для
        # демонстрации хуже, чем обычное дело с возражениями.
        return 0
    if "мирового судьи" not in text and "Мировой судья" not in text:
        return 0

    score = 0
    if "возраж" in text.lower():
        score += 3
    if re.search(r"взыскать.{0,80}руб", text, re.I):
        score += 3
    if "удовлетворить" in text.lower():
        score += 2
    if "отказать" in text.lower():
        score += 2
    if "частично" in text.lower():
        score += 3
    if "экспертиз" in text.lower():
        score += 2
    if "исковые требования" in text.lower():
        score += 1
    if len(text) > 6000:
        score += 2
    if len(text) < 3500:
        score -= 2
    # Слишком много разных норм — демо станет кашей.
    if len(set(re.findall(r"ст\.\s?\d+", text))) > 12:
        score -= 2
    return score


def pick_candidate(documents: list[str]) -> tuple[int, str] | None:
    """Выбрать решение для демо."""
    best: tuple[int, str] | None = None
    best_score = 4
    for index, text in enumerate(documents):
        score = score_candidate(text)
        if score > best_score:
            best = (index, text)
            best_score = score
    return best


def write_materials(parts: dict[str, str], source_index: int) -> None:
    """Записать материалы дела и эталон решения суда."""
    REAL_DIR.mkdir(parents=True, exist_ok=True)

    files = {
        "00_case_info.txt": (
            "СВЕДЕНИЯ О ДЕЛЕ\n"
            "(по материалам дела)\n\n"
            + parts["header"]
        ),
        "01_claim.txt": (
            "ИСКОВОЕ ЗАЯВЛЕНИЕ ИСТЦА\n"
            "(изложение требований по материалам дела)\n\n"
            + parts["claim"]
        ),
        "02_response.txt": (
            "ВОЗРАЖЕНИЯ ОТВЕТЧИКА\n"
            "(изложение позиции ответчика по материалам дела)\n\n"
            + parts["defence"]
        ),
        "05_protocol.txt": (
            "ХОД СУДЕБНОГО ЗАСЕДАНИЯ\n"
            "(по материалам дела)\n\n"
            + parts["procedure"]
        ),
        "06_court_findings.txt": (
            "ОБСТОЯТЕЛЬСТВА, УСТАНОВЛЕННЫЕ СУДОМ\n"
            "(изложение по материалам дела)\n\n"
            + parts["findings"]
        ),
    }

    for name, content in files.items():
        text = content.strip()
        if not text:
            continue
        (REAL_DIR / name).write_text(text + "\n", encoding="utf-8")

    (REAL_DIR / "court_decision_reference.txt").write_text(
        parts["operative"].strip() + "\n", encoding="utf-8"
    )

    # Старые файлы синтетического дела в этом каталоге — лишние: в деле
    # не должно быть документов, которых в деле нет.
    for stale in REAL_DIR.glob("*.txt"):
        if stale.name not in files and stale.name != "court_decision_reference.txt":
            stale.unlink()

    print(f"  строк в корпусе рассмотрено: {source_index + 1}")


def write_manifest(parts: dict[str, str]) -> None:
    """Манифест дела: как его читает конвейер и сборщик сайта."""
    documents = []
    for name in (
        "00_case_info.txt",
        "01_claim.txt",
        "02_response.txt",
        "05_protocol.txt",
        "06_court_findings.txt",
    ):
        path = REAL_DIR / name
        if not path.exists():
            continue
        documents.append(
            {
                "filename": name,
                "title": path.read_text(encoding="utf-8").split("\n")[0],
                "document_type": DOCUMENT_TYPES.get(name, "OTHER"),
                "characters": len(path.read_text(encoding="utf-8")),
            }
        )

    amounts = sorted(
        {
            match.replace(" ", "")
            for match in re.findall(r"\d[\d\s]{2,}\s*руб", parts["claim"], re.I)
        }
    )
    claim_amount = 0.0
    for candidate in amounts:
        digits = re.sub(r"[^\d]", "", candidate)
        if digits:
            claim_amount = float(digits)
            break

    manifest = {
        "warning": (
            "ОБЕЗЛИЧЕННОЕ РЕАЛЬНОЕ СУДЕБНОЕ РЕШЕНИЕ — ЛОКАЛЬНОЕ ДЕМО. "
            "Данные не подлежат публикации: лицензия корпуса решений не "
            "определяет права на распространение."
        ),
        "case_number": "REAL-001",
        "court": "Суд общей юрисдикции (обезличено)",
        "category": "жилищно-коммунальные споры",
        "hearing_date": "2013 год",
        "plaintiff": "Организация",
        "defendant": "ФИО",
        "claim_amount": claim_amount,
        "documents": documents,
    }
    (REAL_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  манифест: {REAL_DIR / 'manifest.json'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Собрать демо из реального решения")
    parser.add_argument(
        "--parquet",
        default=str(DEFAULT_PARQUET),
        help="путь к parquet корпуса (качается, если не найден)",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="только проверить, ничего не записывая",
    )
    args = parser.parse_args(argv)

    parquet = Path(args.parquet)
    if not parquet.exists():
        try:
            download_parquet(parquet)
        except Exception as exc:  # noqa: BLE001
            print(f"ОШИБКА: не удалось скачать корпус: {exc}")
            return 1

    print(f"корпус: {parquet}")
    documents = load_documents(parquet)
    print(f"решений в корпусе: {len(documents)}")

    picked = pick_candidate(documents)
    if picked is None:
        print("ОШИБКА: подходящее решение не нашлось")
        return 1

    index, raw = picked
    parts = split_decision(raw)
    if not parts or not parts.get("operative"):
        print("ОШИБКА: у решения не нашлась резолютивная часть")
        return 1

    cleaned = {key: anonymize(value) for key, value in parts.items()}
    leaks: list[str] = []
    for key, value in cleaned.items():
        leaks.extend(f"{key}: {leak}" for leak in find_leaks(value))
    if leaks:
        print("ОШИБКА: в тексте остались персональные данные:")
        for leak in leaks[:20]:
            print(f"   - {leak}")
        return 1

    print(f"выбрано решение № {index}, оценка {score_candidate(raw)}")
    print(
        "части: иск "
        f"{len(cleaned['claim'])} симв., возражения "
        f"{len(cleaned['defence'])}, ход "
        f"{len(cleaned['procedure'])}, обстоятельства "
        f"{len(cleaned['findings'])}, резолютивная "
        f"{len(cleaned['operative'])}"
    )

    if args.check_only:
        print("OK — материалы обезличены и пригодны.")
        return 0

    write_materials(cleaned, index)
    write_manifest(cleaned)
    print(f"материалы записаны в {REAL_DIR}")
    print(
        "ВАЖНО: эти данные ЛОКАЛЬНЫЕ. Сборщик сайта не публикует "
        "решения из корпуса: лицензия корпуса не даёт на это права."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
