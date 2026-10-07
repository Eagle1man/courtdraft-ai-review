"""Проверка статического сайта без браузера.

Проверяет то, что реально ломает страницу: битые внутренние ссылки,
незакрытые теги, отсутствующие файлы, пустые обязательные атрибуты
доступности. Визуально здесь ничего не проверяется — для этого нужен
браузер; скрипт ловит ошибки, которые иначе видны только пользователю.
"""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr"}


class Checker(HTMLParser):
    """Собирает ссылки, id и незакрытые теги."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.unclosed: list[tuple[str, int]] = []
        self.ids: set[str] = set()
        self.hrefs: list[str] = []
        self.lang: str | None = None
        self.title: str | None = None
        self.in_title = False
        self.imgs_without_alt = 0
        self.h1_count = 0
        self.tables_with_caption = 0
        self.tables = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)

        if tag == "html":
            self.lang = attr.get("lang")
        if tag == "title":
            self.in_title = True
        if attr.get("id"):
            self.ids.add(attr["id"] or "")
        if tag == "a" and attr.get("href"):
            self.hrefs.append(attr["href"] or "")
        if tag == "img" and "alt" not in attr:
            self.imgs_without_alt += 1
        if tag == "h1":
            self.h1_count += 1
        if tag == "table":
            self.tables += 1
        if tag == "caption":
            self.tables_with_caption += 1

        if tag not in VOID:
            self.stack.append((tag, self.getpos()[0]))

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if tag in VOID:
            return
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                for orphan in self.stack[index + 1:]:
                    self.unclosed.append(orphan)
                del self.stack[index:]
                return
        self.unclosed.append((tag, self.getpos()[0]))

    def handle_data(self, data: str) -> None:
        if self.in_title and self.title is None:
            stripped = data.strip()
            if stripped:
                self.title = stripped


def main() -> int:
    problems: list[str] = []

    index = SITE / "index.html"
    if not index.exists():
        print(f"НЕТ ФАЙЛА: {index}")
        return 1

    html = index.read_text(encoding="utf-8")
    checker = Checker()
    checker.feed(html)
    checker.close()

    for tag, line in checker.unclosed:
        problems.append(f"незакрытый тег <{tag}> (строка {line})")

    if checker.lang != "ru":
        problems.append(f"lang должен быть 'ru', получено {checker.lang!r}")

    if not checker.title:
        problems.append("нет <title>")
    elif len(checker.title) > 70:
        problems.append(f"<title> слишком длинный ({len(checker.title)} символов)")

    if checker.h1_count != 1:
        problems.append(f"должен быть ровно один <h1>, найдено {checker.h1_count}")

    if checker.imgs_without_alt:
        problems.append(f"изображений без alt: {checker.imgs_without_alt}")

    if checker.tables and checker.tables != checker.tables_with_caption:
        problems.append("таблица без <caption>")

    # Внутренние якоря и ссылки на файлы
    for href in checker.hrefs:
        if href.startswith("#"):
            if href[1:] not in checker.ids:
                problems.append(f"битый якорь {href}")
        elif href.startswith(("http://", "https://", "mailto:", "//")):
            continue
        elif href.endswith(".css") or href.endswith(".js"):
            target = SITE / href.lstrip("/")
            if not target.exists():
                problems.append(f"отсутствует файл {href}")

    # Ресурсы из разметки, которые не являются ссылками
    for src in re.findall(r'(?:src|href)="([^"#]+)"', html):
        if src.startswith(("http", "mailto:", "//", "data:")):
            continue
        if src.startswith("#"):
            continue
        target = SITE / src.lstrip("/")
        if not target.exists():
            problems.append(f"отсутствует ресурс {src}")

    # Внешние ссылки должны быть https
    for match in re.finditer(r'href="(http://[^"]+)"', html):
        problems.append(f"внешняя ссылка без https: {match.group(1)}")

    print(f"проверено: {index}")
    print(f"  размер html      : {len(html):,} байт")
    print(f"  тегов <a>        : {len(checker.hrefs)}")
    print(f"  id               : {len(checker.ids)}")
    print(f"  h1               : {checker.h1_count}")
    print()

    if problems:
        print(f"ПРОБЛЕМЫ ({len(problems)}):")
        for p in problems:
            print(f"  - {p}")
        return 1

    print("OK — вёрстка целостна, ссылки и ресурсы на месте.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
