"""Извлечь конструкции резолютивной части из книг.

Что выяснено предыдущим прогоном и почему нужен отдельный скрипт.

В трёх книгах маркеров резолютивной части немного: 21 в «Настольной
книге», 29 в «Образцах», 15 в «Разъяснениях». Это не ошибка поиска,
а свойство материала: книги объясняют судопроизводство и содержат
образцы ЗАЯВЛЕНИЙ, а не тексты решений. Разбирать их как сборник
решений бессмысленно.

Но именно резолютивная часть нам нужна больше всего, и в книгах она
есть — короткими конструкциями со ссылками на статьи ГПК РФ. Задача
этого скрипта: вытащить эти конструкции целиком, с соседним
контекстом, чтобы из них можно было собрать правила построения.

Результат: список конструкций с указанием книги и позиции.

Запуск:
    .venv\\Scripts\\python.exe -X utf8 scripts\\extract_resolutions.py
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document

KB = Path(r"D:\courtdraft-kb")
OUT = Path(
    r"C:\Users\diorl\AppData\Local\Temp\opencode\patterns\resolutions.txt"
)

BOOKS = [
    ("nastolnaya", "Настольная книга российского судьи по гражданскому"),
    ("obraztsi", "Все образцы судебных документов"),
    ("vsrf", "Разъяснения ВС РФ по гражданским делам"),
]

# Конструкции резолютивной части. Ищутся с привязкой к формулировкам,
# которыми реально заканчивается дело, а не к слову «иск».
RESOLUTION_PATTERNS = [
    r"удовлетворить\s+исковые\s+требования",
    r"удовлетворить\s+частично",
    r"отказать\s+в\s+удовлетворени[ии][^.]*иск",
    r"взыскать\s+в\s+пользу[^.]*рубл",
    r"исковые\s+расходы[^.]*пошлин",
    r"обеспечить\s+исполнение\s+решения",
    r"исполнительный\s+лист",
    r"Руководствуясь\s+ст\.\s*\d+[^.]*ГПК[^,]*,\s*суд\s+пр",
]

# Статьи ГПК, на которые опирается резолютивная часть. Их наличие в
# тексте рядом с формулировкой — признак, что пример настоящий.
GPK_ARTICLE = re.compile(r"ст\.\s*(\d+(?:\.\d+)?)\s*ГПК")


def book_text(title_part: str) -> tuple[str, list[str]]:
    files = sorted(KB.rglob(f"*{title_part}*.docx"))
    chunks: list[str] = []
    names: list[str] = []
    for path in files:
        try:
            document = Document(path)
        except Exception as exc:  # noqa: BLE001
            chunks.append(f"[не открыт: {exc}]")
            names.append(path.name)
            continue
        chunks.append("\n".join(p.text for p in document.paragraphs if p.text.strip()))
        names.append(path.name)
    return "\n".join(chunks), names


def sentences_around(text: str, position: int, before: int = 2, after: int = 2) -> str:
    """Контекст вокруг совпадения: соседние предложения."""
    start = text.rfind(". ", 0, position)
    start = start + 2 if start > 0 else max(0, position - 300)
    end = position
    for _ in range(after):
        found = text.find(". ", end)
        if found < 0:
            end = len(text)
            break
        end = found + 1

    chunk = text[start:end]
    # Предыдущие предложения для полноты картины
    prev_start = max(0, start - 600)
    prefix = text[prev_start:start]
    parts = [p.strip() for p in prefix.split(".") if len(p.strip()) > 30]
    if parts:
        return "... " + ". ".join(parts[-before:]) + ". " + chunk
    return chunk


def main() -> int:
    lines: list[str] = []
    lines.append("КОНСТРУКЦИИ РЕЗОЛЮТИВНОЙ ЧАСТИ\n")
    lines.append("=" * 70 + "\n\n")

    total = 0
    for key, title in BOOKS:
        text, names = book_text(title)
        lines.append(f"\n{'#' * 70}\n# {key}\n# ФАЙЛЫ: {', '.join(names)}\n")
        lines.append(f"{'#' * 70}\n\n")

        for pattern in RESOLUTION_PATTERNS:
            matches = list(re.finditer(pattern, text, re.I))
            if not matches:
                continue
            lines.append(f"--- ШАБЛОН: {pattern}\n")
            lines.append(f"    найдено: {len(matches)}\n\n")

            for match in matches[:6]:
                context = sentences_around(text, match.start())
                articles = sorted(set(GPK_ARTICLE.findall(context)))
                lines.append(f"  @{match.start()}\n")
                lines.append(f"  статьи ГПК рядом: {articles or 'не указаны'}\n")
                for line in context.splitlines():
                    lines.append(f"    {line.strip()}\n")
                lines.append("\n")
                total += 1

    lines.append(f"\n{'=' * 70}\nВСЕГО КОНСТРУКЦИЙ: {total}\n")

    OUT.write_text("".join(lines), encoding="utf-8")
    print(f"записано: {OUT}, конструкций {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
