"""Сборка Word-отчёта из markdown-исходника.

Зачем отдельный скрипт, а не ручная вёрстка: отчёт в .md — источник истины,
версия для чтения, .docx — производная. Чтобы они не разошлись, .docx
собирается из того же файла.

Что учитывает оформление:
- заголовки уровня 1 и 2 идут как Heading 1 и Heading 2;
- таблицы в pipe-разметке превращаются в настоящие таблицы Word;
- блоки кода получают моноширинный шрифт и серую заливку;
- строка `---` превращается в разделительную линию, а не остаётся текстом.

Кириллица в Python 3.14: байтовые литералы с кириллицей запрещены, поэтому
строки собираются как обычный str и кодируются только при записи.
"""

from __future__ import annotations

import re
from pathlib import Path

import docx
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

DOC = Path(r"D:\courtdraft-ai\docs\report-mvp.md")
OUT = Path(r"D:\courtdraft-ai\docs\report-mvp.docx")

ACCENT = RGBColor(0x1F, 0x38, 0x64)
DANGER = RGBColor(0x9C, 0x00, 0x06)
MUTED = RGBColor(0x59, 0x59, 0x59)
CODE_BG = "F2F2F2"
WARN_BG = "FFF4E5"

TABLE_HEADER_FILL = "1F3864"
ZEBRA_FILL = "F7F7F7"


def _set_font(run, *, name: str = "Calibri", size: int = 11, bold: bool = False,
              color: RGBColor | None = None) -> None:
    """Задать шрифт.

    python-docx задаёт шрифт только для латиницы. Для кириллицы нужно
    отдельно указать тот же шрифт в eastAsia, иначе Word подставит свой
    шрифт и документ будет выглядеть собранным из двух разных.
    """
    run.font.name = name
    run.font.size = Pt(size)
    run.bold = bold
    if color is not None:
        run.font.color.rgb = color
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


def _shade(cell, hex_fill: str) -> None:
    """Залить ячейку цветом."""
    from docx.oxml import OxmlElement

    shading = OxmlElement("w:shd")
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:fill"), hex_fill)
    cell._tc.get_or_add_tcPr().append(shading)


def _add_rich(paragraph, text: str, *, base_size: int = 11) -> None:
    """Добавить текст, разбирая **жирный** и `моноширинный`."""
    for part in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            run = paragraph.add_run(part[2:-2])
            _set_font(run, size=base_size, bold=True)
        elif part.startswith("`") and part.endswith("`"):
            run = paragraph.add_run(part[1:-1])
            _set_font(run, name="Consolas", size=base_size - 1)
            run.font.color.rgb = RGBColor(0xA3, 0x1D, 0x1D)
        else:
            run = paragraph.add_run(part)
            _set_font(run, size=base_size)


def _parse_row(line: str) -> list[str]:
    cells = line.strip().strip("|").split("|")
    return [c.strip() for c in cells]


def _is_separator(line: str) -> bool:
    return bool(re.fullmatch(r"\|[\s:\-|]+\|", line.strip()))


def add_table(document, rows: list[list[str]]) -> None:
    """Настоящая таблица Word."""
    width = max(len(r) for r in rows)
    table = document.add_table(rows=len(rows), cols=width)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    for row_index, row in enumerate(rows):
        for col_index in range(width):
            cell = table.cell(row_index, col_index)
            cell.text = ""
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_before = Pt(2)
            paragraph.paragraph_format.space_after = Pt(2)
            value = row[col_index] if col_index < len(row) else ""
            is_header = row_index == 0
            _add_rich(paragraph, value, base_size=10)
            for run in paragraph.runs:
                run.bold = is_header
                if is_header:
                    run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            if is_header:
                _shade(cell, TABLE_HEADER_FILL)
            elif row_index % 2 == 0:
                _shade(cell, ZEBRA_FILL)

    document.add_paragraph()


def add_code_block(document, lines: list[str]) -> None:
    """Блок кода: моноширинный шрифт, серая заливка, без интервала."""
    table = document.add_table(rows=1, cols=1)
    table.style = "Table Grid"
    cell = table.cell(0, 0)
    _shade(cell, CODE_BG)
    cell.text = ""

    for index, raw in enumerate(lines):
        paragraph = cell.paragraphs[0] if index == 0 else cell.add_paragraph()
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.space_after = Pt(0)
        run = paragraph.add_run(raw if raw else " ")
        _set_font(run, name="Consolas", size=9)

    document.add_paragraph()


def add_note(document, text: str) -> None:
    """Врезка с предупреждением."""
    table = document.add_table(rows=1, cols=1)
    table.style = "Table Grid"
    cell = table.cell(0, 0)
    _shade(cell, WARN_BG)
    cell.text = ""

    paragraph = cell.paragraphs[0]
    _add_rich(paragraph, text, base_size=10)
    for run in paragraph.runs:
        run.bold = True
        run.font.color.rgb = DANGER

    document.add_paragraph()


def build() -> int:
    source = DOC.read_text(encoding="utf-8")
    lines = source.split("\n")

    document = docx.Document()

    # Поля страницы: текст с таблицами не должен упираться в края.
    for section in document.sections:
        section.left_margin = Pt(56)
        section.right_margin = Pt(56)
        section.top_margin = Pt(56)
        section.bottom_margin = Pt(56)

    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")

    index = 0
    total = len(lines)
    heading_count = 0

    while index < total:
        line = lines[index]
        stripped = line.strip()

        # ── Разделительная линия ──────────────────────────────
        if stripped == "---":
            index += 1
            continue

        # ── Кодовый блок ──────────────────────────────────────
        if stripped.startswith("```"):
            index += 1
            block: list[str] = []
            while index < total and not lines[index].strip().startswith("```"):
                block.append(lines[index])
                index += 1
            index += 1
            add_code_block(document, block)
            continue

        # ── Таблица ───────────────────────────────────────────
        if stripped.startswith("|") and index + 1 < total and _is_separator(lines[index + 1]):
            rows = [_parse_row(stripped)]
            index += 2
            while index < total and lines[index].strip().startswith("|"):
                rows.append(_parse_row(lines[index]))
                index += 1
            add_table(document, rows)
            continue

        # ── Заголовки ─────────────────────────────────────────
        if stripped.startswith("### "):
            heading = document.add_heading(level=3)
            _add_rich(heading, stripped[4:], base_size=12)
            heading_count += 1
            index += 1
            continue

        if stripped.startswith("## "):
            heading = document.add_heading(level=2)
            _add_rich(heading, stripped[3:], base_size=15)
            heading_count += 1
            index += 1
            continue

        if stripped.startswith("# "):
            paragraph = document.add_paragraph()
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = paragraph.add_run(stripped[2:])
            _set_font(run, size=22, bold=True, color=ACCENT)
            heading_count += 1
            index += 1
            continue

        # ── Нумерованный список ───────────────────────────────
        numbered = re.match(r"^(\d+)\.\s+(.*)$", stripped)
        if numbered:
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.left_indent = Pt(20)
            run = paragraph.add_run(f"{numbered.group(1)}. ")
            _set_font(run, bold=True)
            _add_rich(paragraph, numbered.group(2))
            index += 1
            continue

        # ── Маркированный список ──────────────────────────────
        if stripped.startswith("- "):
            paragraph = document.add_paragraph(style="List Bullet")
            paragraph.paragraph_format.space_after = Pt(3)
            _add_rich(paragraph, stripped[2:])
            index += 1
            continue

        # ── Врезка-предупреждение ─────────────────────────────
        if stripped.startswith("> "):
            add_note(document, stripped[2:])
            index += 1
            continue

        # ── Обычный текст ─────────────────────────────────────
        if stripped:
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.space_after = Pt(6)
            _add_rich(paragraph, stripped)
        index += 1

    document.save(OUT)
    size_kb = OUT.stat().st_size // 1024
    print(f"готово: {OUT}")
    print(f"размер: {size_kb} КБ")
    print(f"заголовков: {heading_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
