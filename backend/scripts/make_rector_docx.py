"""Одностраничный отчёт для руководства.

Отдельный документ, а не сокращение технического отчёта. Причина: аудитория
другая. Руководителю не нужны числа тестов и названия эндпоинтов — ему нужно
понять три вещи: что сделано, чего не сделано, и что нужно от него.

Поэтому здесь нет таблиц на двадцать строк и списков модулей. Есть четыре
коротких блока и одна просьба.
"""

from __future__ import annotations

from pathlib import Path

import docx
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

OUT = Path(r"D:\courtdraft-ai\docs\for-rector.docx")

NAVY = RGBColor(0x1F, 0x38, 0x64)
GREY = RGBColor(0x55, 0x55, 0x55)
RED = RGBColor(0x9C, 0x00, 0x06)

BOX_REQUEST = "EAF1F8"
BOX_LIMITS = "FDF3E3"


def set_font(run, *, size=11, bold=False, color=None, name="Calibri") -> None:
    """Шрифт с явным указанием для кириллицы.

    python-docx задаёт только латиницу; без eastAsia Word подставит свой
    шрифт и документ будет выглядеть собранным из двух разных.
    """
    run.font.name = name
    run.font.size = Pt(size)
    run.bold = bold
    if color is not None:
        run.font.color.rgb = color
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


def shade(cell, fill: str) -> None:
    element = OxmlElement("w:shd")
    element.set(qn("w:val"), "clear")
    element.set(qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(element)


def box(document, lines: list[tuple[str, str]], fill: str) -> None:
    """Врезка: заголовок + абзацы, в рамке с заливкой."""
    table = document.add_table(rows=1, cols=1)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = table.cell(0, 0)
    shade(cell, fill)

    cell.text = ""
    head = cell.paragraphs[0]
    head.paragraph_format.space_after = Pt(4)
    run = head.add_run(lines[0][0])
    set_font(run, size=12, bold=True, color=NAVY)

    for title, body in lines[1:]:
        paragraph = cell.add_paragraph()
        paragraph.paragraph_format.space_after = Pt(3)
        if title:
            run = paragraph.add_run(f"{title}. ")
            set_font(run, size=10.5, bold=True)
        run = paragraph.add_run(body)
        set_font(run, size=10.5)

    document.add_paragraph()


def body(document, text: str, *, size=10.5, space_after=5, color=None) -> None:
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_after = Pt(space_after)
    paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    run = paragraph.add_run(text)
    set_font(run, size=size, color=color)


def bullet(document, text: str) -> None:
    paragraph = document.add_paragraph(style="List Bullet")
    paragraph.paragraph_format.space_after = Pt(2)
    paragraph.paragraph_format.left_indent = Cm(0.6)
    run = paragraph.add_run(text)
    set_font(run, size=10.5)


def build() -> int:
    document = docx.Document()

    for section in document.sections:
        section.top_margin = Cm(1.4)
        section.bottom_margin = Cm(1.2)
        section.left_margin = Cm(1.8)
        section.right_margin = Cm(1.8)

    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")

    # ── Шапка ────────────────────────────────────────────────
    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_after = Pt(2)
    run = title.add_run("CourtDraft — система подготовки проектов судебных решений")
    set_font(run, size=16, bold=True, color=NAVY)

    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.paragraph_format.space_after = Pt(10)
    run = subtitle.add_run("Состояние на 8 октября 2026 года · доклад на одну страницу")
    set_font(run, size=10, color=GREY)

    # ── Суть ─────────────────────────────────────────────────
    body(
        document,
        "Система готовит черновик проекта судебного решения по материалам дела: "
        "принимает документы, находит в них факты и доказательства, составляет "
        "текст решения по установленной структуре и проверяет, что каждое "
        "утверждение опирается на реальный документ дела.",
        space_after=6,
    )

    emphasize = document.add_paragraph()
    emphasize.paragraph_format.space_after = Pt(8)
    emphasize.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = emphasize.add_run(
        "Система не принимает решений. Она готовит проект, решение принимает судья."
    )
    set_font(run, size=11, bold=True, color=RED)

    # ── Готово ───────────────────────────────────────────────
    head = document.add_paragraph()
    head.paragraph_format.space_after = Pt(3)
    set_font(head.add_run("Что уже работает"), size=12, bold=True, color=NAVY)

    bullet(document, "приём и разбор материалов дела: PDF, Word, текст, таблицы;")
    bullet(document, "поиск по материалам дела с указанием источника каждой находки;")
    bullet(
        document,
        "составление проекта решения настоящей языковой моделью, запущенной "
        "локально на компьютере;",
    )
    bullet(
        document,
        "автоматическая проверка проекта: система отмечает всё, чего нет в "
        "материалах дела, — выдуманные суммы, ссылки на несуществующие нормы, "
        "пробелы;",
    )
    bullet(
        document,
        "полный цикл отработал на демонстрационном деле за две с половиной минуты "
        "без интернета и без видеокарты.",
    )

    # ── Объём работы ─────────────────────────────────────────
    body(
        document,
        "Работа выполнена с нуля силами одного разработчика — без привлечения "
        "подрядчиков и без закупки лицензий. Начата 7 октября, основной объём "
        "закрыт 8 октября:",
        space_after=4,
    )

    stats = [
        ("9 700", "строк кода"),
        ("315", "автоматических проверок"),
        ("14", "таблиц базы данных"),
        ("182", "издания проработано"),
    ]
    strip = document.add_table(rows=2, cols=len(stats))
    strip.style = "Table Grid"
    strip.alignment = WD_TABLE_ALIGNMENT.CENTER
    for column, (value, caption) in enumerate(stats):
        top = strip.cell(0, column)
        top.text = ""
        shade(top, BOX_REQUEST)
        paragraph = top.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.space_after = Pt(0)
        set_font(paragraph.add_run(value), size=16, bold=True, color=NAVY)

        bottom = strip.cell(1, column)
        bottom.text = ""
        paragraph = bottom.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.space_after = Pt(0)
        set_font(paragraph.add_run(caption), size=8.5, color=GREY)

    document.add_paragraph()

    note = document.add_paragraph()
    note.paragraph_format.space_after = Pt(8)
    note.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(
        note.add_run(
            "Все 315 проверок проходят. Исходный код открыт и находится "
            "внутри организации: данные не покидают её."
        ),
        size=9.5,
        color=GREY,
    )

    # ── Чего нет ─────────────────────────────────────────────
    box(
        document,
        [
            ("Чего пока нет", ""),
            (
                "Интерфейс",
                "программа работает как служебный сценарий, а не как приложение. "
                "Пользоваться ею может только разработчик.",
            ),
            (
                "Хранение",
                "проект решения не сохраняется в базе данных — нет истории "
                "версий и правок, которая обязательна для судебного акта.",
            ),
            (
                "Качество текста",
                "модель небольшого размера ошибается: путает стороны дела, "
                "придумывает состав суда. Автоматическая проверка такие ошибки "
                "пока не видит.",
            ),
        ],
        BOX_LIMITS,
    )

    # ── Просьба ──────────────────────────────────────────────
    box(
        document,
        [
            ("Что нужно от руководства", ""),
            (
                "Компьютер с видеокартой NVIDIA RTX 3050",
                "обязателен. Без видеокарты невозможно проверить модель, "
                "заявленную в проекте, и настоящие векторные эмбеддинги. "
                "Вся остальная работа на текущем компьютере уже ведётся и "
                "результат есть.",
            ),
            (
                "Срок",
                "один рабочий день на перенос и проверку. Без машины "
                "заявленные показатели качества останутся неподтверждёнными, "
                "и подтвердить их будет нечем.",
            ),
            (
                "Второй комплект материалов",
                "один реальный комплект документов дела, обезличенный. "
                "На вымышленном деле оценить качество работы системы нельзя.",
            ),
        ],
        BOX_REQUEST,
    )

    # ── Итог ─────────────────────────────────────────────────
    head = document.add_paragraph()
    head.paragraph_format.space_before = Pt(4)
    head.paragraph_format.space_after = Pt(3)
    set_font(head.add_run("Что предстоит сделать"), size=12, bold=True, color=NAVY)

    steps = [
        ("1 неделя", "веб-интерфейс, сохранение проектов с историей версий, "
                     "проверка ошибок модели."),
        ("2–3 неделя", "повышение качества текста, проверка на реальных делах, "
                       "подключение видеокарты."),
        ("1–2 месяца", "расширение на другие категории дел, экспорт в формате "
                       "судопроизводства."),
    ]
    for when, what in steps:
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.space_after = Pt(3)
        paragraph.paragraph_format.left_indent = Cm(0.3)
        run = paragraph.add_run(f"{when}. ")
        set_font(run, size=10.5, bold=True)
        set_font(paragraph.add_run(what), size=10.5)

    document.save(OUT)
    print(f"готово: {OUT}")
    print(f"размер: {OUT.stat().st_size // 1024} КБ")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
