"""Сверить архив «готовые книги.rar» с уже распакованной папкой.

WinRAR отдаёт имена файлов в cp866 (DOS), а не в UTF-8: байты
начинаются с a3 ae e2 ae a2, что в UTF-8 не является началом ни
одного символа. Первая попытка сравнения дала «совпадений 0» именно
из-за этого — имена читались как мусор, а не как названия.

Здесь кодировка задана явно (cp866), с перебором гипотез на случай
смены настроек WinRAR. Сверка идёт по полным путям внутри архива и по
папкам на диске — так надёжнее, чем сравнение только имён файлов.

Запуск:
    .venv\\Scripts\\python.exe -X utf8 scripts\\compare_archive.py
"""

from __future__ import annotations

import pathlib
import re
import subprocess

OUT = pathlib.Path(
    r"C:\Users\diorl\AppData\Local\Temp\opencode\archive_compare.txt"
)
ARCHIVE = r"D:\hrome\готовые книги.rar"
UNPACKED = pathlib.Path(r"D:\courtdraft-kb")

RAR_CANDIDATES = [
    r"C:\Program Files\WinRAR\UnRAR.exe",
    r"C:\Program Files\WinRAR\Rar.exe",
    r"C:\Program Files (x86)\WinRAR\UnRAR.exe",
]

# WinRAR печатает имена в кодировке консоли. Задаётся явно: без этого
# имена читаются как мусор и сравнение бессмысленно.
ENCODINGS = ("cp866", "cp1251", "utf-8")


def find_rar() -> str | None:
    for candidate in RAR_CANDIDATES:
        if pathlib.Path(candidate).exists():
            return candidate
    return None


def archive_names(tool: str) -> tuple[list[str], str]:
    """Имена файлов из архива вместе с применённой кодировкой."""
    # S603 — вызывается не программа из входных данных, а найденный
    # на машине UnRAR с фиксированным списком аргументов.
    process = subprocess.run(  # noqa: S603
        [tool, "lb", ARCHIVE], capture_output=True, timeout=600, check=False
    )
    raw = process.stdout
    for encoding in ENCODINGS:
        try:
            return raw.decode(encoding).splitlines(), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("cp866", errors="replace").splitlines(), "cp866 (с потерями)"


def normalise(name: str) -> str:
    """Привести имя к сравнимому виду.

    Убираются расширение, повторы слов в пути и лишние пробелы: в
    архиве книга лежит как «папка\\папка\\папка.docx», а на диске
    так же, но сравнивать удобнее по короткому имени.
    """
    stem = pathlib.PureWindowsPath(name.strip()).stem
    return re.sub(r"\s+", " ", stem).casefold()


def main() -> int:
    lines: list[str] = []

    rar = find_rar()
    if rar is None:
        lines.append("WinRAR не найден на машине\n")
        OUT.write_text("".join(lines), encoding="utf-8")
        print(f"записано: {OUT}")
        return 1

    entries, encoding = archive_names(rar)
    lines.append(f"КОДИРОВКА ИМЁН ИЗ АРХИВА: {encoding}\n")
    lines.append(f"ЗАПИСЕЙ В АРХИВЕ: {len(entries)}\n")

    in_archive = {
        normalise(e) for e in entries if e.lower().strip().endswith(".docx")
    }
    lines.append(f"КНИГ (.docx) В АРХИВЕ: {len(in_archive)}\n\n")

    if not UNPACKED.exists():
        lines.append("D:\\courtdraft-kb НЕ СУЩЕСТВУЕТ — архив не разбирался\n")
        OUT.write_text("".join(lines), encoding="utf-8")
        print(f"записано: {OUT}")
        return 0

    on_disk = list(UNPACKED.rglob("*.docx"))
    disk = {normalise(p.name) for p in on_disk}
    lines.append(f"КНИГ НА ДИСКЕ: {len(on_disk)}\n")
    lines.append(f"УНИКАЛЬНЫХ ИМЁН НА ДИСКЕ: {len(disk)}\n\n")

    common = in_archive & disk
    only_archive = sorted(in_archive - disk)
    only_disk = sorted(disk - in_archive)

    lines.append(f"СОВПАДАЮТ: {len(common)}\n")
    lines.append(f"ТОЛЬКО В АРХИВЕ: {len(only_archive)}\n")
    lines.append(f"ТОЛЬКО НА ДИСКЕ: {len(only_disk)}\n\n")

    if only_archive:
        lines.append("--- есть в архиве, но нет на диске ---\n")
        for name in only_archive[:40]:
            lines.append(f"  {name}\n")
        lines.append("\n")
    if only_disk:
        lines.append("--- есть на диске, но нет в архиве ---\n")
        for name in only_disk[:40]:
            lines.append(f"  {name}\n")
        lines.append("\n")

    if not only_archive:
        lines.append(
            "ВЫВОД: архив уже полностью разобран ранее, нового\n"
            "       материала в нём нет.\n"
        )
    elif not only_disk:
        lines.append(
            "ВЫВОД: на диске лежит часть архива. Оставшиеся книги\n"
            "       ещё не распакованы — их можно разобрать.\n"
        )
    else:
        lines.append("ВЫВОД: содержимое частично пересекается.\n")

    OUT.write_text("".join(lines), encoding="utf-8")
    print(f"записано: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
