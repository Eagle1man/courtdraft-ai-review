"""Извлечение структуры решений суда из книг.

Зачем. Нужен не корпус для обучения модели, а знание о том, как судья
пишет: из каких частей состоит решение, в каком порядке они идут и
какими словами. Это извлекается из книг, а не из текстов дел, потому
что открытых текстов гражданских дел не существует, а учебные
пособия содержат ровно то, что нужно, — проверенные формулировки.

Книги остаются вне репозитория (D:\\courtdraft-kb). В код попадают
только извлечённые правила, без текстов книг: иначе это будет
копирование авторских материалов.

ЗАПУСК
    .venv\\Scripts\\python.exe -X utf8 scripts\\extract_patterns.py

ВЫВОД
    C:\\Users\\diorl\\AppData\\Local\\Temp\\opencode\\patterns\\*.txt

ЧТО ИЩЕМ
    Границы частей решения — «УСТАНОВИЛ», «ОПРЕДЕЛИЛ», «РЕШИЛ»,
    «ИСКОВЫЕ ТРЕБОВАНИЯ УДОВЛЕТВОРЕНЫ», вводная часть, мотивировка.
    Из этих маркеров собирается порядок частей и словарь оборотов.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from docx import Document

KB = Path(r"D:\courtdraft-kb")
OUT = Path(r"C:\Users\diorl\AppData\Local\Temp\opencode\patterns")
OUT.mkdir(parents=True, exist_ok=True)

BOOKS = [
    (
        "nastolnaya",
        "Настольная книга российского судьи по гражданскому судопроизводству",
    ),
    (
        "obraztsi",
        "Все образцы судебных документов по гражданским делам "
        "и административным делам",
    ),
    (
        "vsrf",
        "Разъяснения ВС РФ по гражданским делам и экономическим спорам",
    ),
]

# Маркеры частей решения. Порядок в списке не важен: порядок частей
# определяется тем, как они следуют в тексте.
SECTION_MARKERS: dict[str, list[str]] = {
    "вводная_часть": [
        "Именем Российской Федерации",
        "Рассмотрев исковое заявление",
        "в порядке гражданского судопроизводства",
        "участиствующ",
    ],
    "обстоятельства_дела": [
        "Истец обратился в суд с иском",
        "В обоснование иска указано",
        "Ответчик в судебное заседание",
        "Суд считает",
        "Установлено",
    ],
    "мотивировка": [
        "Согласно",
        "В соответствии со",
        "руководствуясь",
        "Представитель истца",
        "Представитель ответчика",
    ],
    "резолютивная_часть": [
        "ОПРЕДЕЛИЛ",
        "РЕШИЛ",
        "ПОСТАНОВИЛ",
        "исковые требования",
        "удовлетворить",
        "отказать в удовлетворении",
        "взыскать",
    ],
}

# Обороты, которые повторяются в решениях и задают их тон.
PHRASES = [
    "Исковые требования",
    "удовлетворить частично",
    "в полном объеме",
    "отказать в удовлетворении",
    "Согласно",
    "В соответствии с",
    "руководствуясь",
    "Учитывая",
    "Таким образом",
    "На основании изложенного",
    "исковые расходы",
    "государственной пошлины",
]


def book_text(root: Path, title: str) -> tuple[str, list[str]]:
    """Текст книги целиком. Возвращает текст и имена найденных файлов."""
    files = sorted(root.rglob(f"*{title}*.docx"))
    chunks: list[str] = []
    names: list[str] = []
    for path in files:
        try:
            document = Document(path)
        except Exception as exc:  # noqa: BLE001
            chunks.append(f"[не удалось открыть: {exc}]")
            names.append(path.name)
            continue
        parts = [p.text for p in document.paragraphs if p.text.strip()]
        chunks.append("\n".join(parts))
        names.append(path.name)
    return "\n".join(chunks), names


def find_sections(text: str) -> list[tuple[str, int, str]]:
    """Найти вхождения маркеров частей решения.

    Возвращаются (название части, позиция, ближайшая строка) — по
    позициям восстанавливается порядок следования частей.
    """
    found: list[tuple[str, int, str]] = []
    for section, markers in SECTION_MARKERS.items():
        for marker in markers:
            for match in re.finditer(re.escape(marker), text, re.I):
                line_start = text.rfind("\n", 0, match.start()) + 1
                line_end = text.find("\n", match.end())
                line = text[line_start : line_end if line_end > 0 else len(text)]
                found.append((section, match.start(), line.strip()[:160]))
    return found


def main() -> int:
    all_text: dict[str, str] = {}

    for key, title in BOOKS:
        text, names = book_text(KB, title)
        all_text[key] = text
        lines: list[str] = []
        lines.append(f"КНИГА: {title}\n")
        lines.append(f"ФАЙЛЫ ({len(names)}):\n")
        for name in names:
            lines.append(f"  {name}\n")
        lines.append(f"\nСИМВОЛОВ: {len(text)}\n")
        lines.append(f"СИМВОЛОВ С ПРОБЕЛАМИ: {len(text.split())}\n\n")

        sections = find_sections(text)
        lines.append(f"НАЙДЕНО МАРКЕРОВ: {len(sections)}\n\n")

        counts = Counter(name for name, _, _ in sections)
        lines.append("ЧАСТОТА ПО ЧАСТЯМ:\n")
        for section, count in counts.most_common():
            lines.append(f"  {section:24} {count:>5}\n")
        lines.append("\n")

        lines.append("ПРИМЕРЫ КАЖДОЙ ЧАСТИ (по порядку появления):\n\n")
        seen: Counter[str] = Counter()
        for section, position, line in sorted(sections, key=lambda x: x[1]):
            if seen[section] >= 3:
                continue
            seen[section] += 1
            lines.append(f"  [{section}] @{position}\n    {line}\n\n")

        lines.append("ЧАСТОТА ОБОРОТОВ:\n")
        for phrase in PHRASES:
            count = len(re.findall(re.escape(phrase), text, re.I))
            if count:
                lines.append(f"  {count:>5}  {phrase}\n")

        (OUT / f"{key}.txt").write_text("".join(lines), encoding="utf-8")
        print(f"{key}: {len(text)} символов, маркеров {len(sections)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
