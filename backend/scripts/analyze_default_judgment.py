"""Разбор заочного производства и порядка построения резолюции.

При разборе 1 425 гражданских резолюций обнаружилось, что чаще всего
резолюция начинается не с «взыскать», а с определения о порядке
рассмотрения дела:

    рассмотреть дело в отсутствие ответчика, признав причину его
    неявки неуважительной, в порядке заочного производства

Это не украшение: без такой строки заочное решение незаконно. Суд
обязан указать, что ответчик извещён и не явился.

Скрипт считает, сколько резолюций так начинается, и смотрит, какими
формулировками описываются последствия заочного решения.

Запуск:
    .venv\\Scripts\\python.exe -X utf8 scripts\\analyze_default_judgment.py
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.extract_rules import OPERATIVE_START, is_civil  # noqa: E402

OUT = Path(r"C:\Users\diorl\AppData\Local\Temp\opencode\rules\default_judgment.txt")
PARQUET = Path(r"C:\Users\diorl\AppData\Local\Temp\opencode\hf_test.parquet")

# Признаки заочного производства.
DEFAULT_MARKERS = (
    "заочн",
    "в отсутствие ответчик",
    "в отсутствие истца",
    "признав причину",
    "не явился",
    "не явилась",
)

# Что суд пишет про последствия заочного решения.
CONSEQUENCE_MARKERS = (
    "отмен",
    "заявление об отмене",
    "семи дней",
    "заочное решение",
)


def main() -> int:
    import pandas as pd

    if not PARQUET.exists():
        print(f"нет файла: {PARQUET}")
        return 1

    df = pd.read_parquet(PARQUET)
    lines: list[str] = ["ЗАОЧНОЕ ПРОИЗВОДСТВО В РЕЗОЛЮТИВНОЙ ЧАСТИ", "=" * 60, ""]

    total_civil = 0
    with_operative = 0
    with_default = 0
    openers: Counter[str] = Counter()
    consequences: Counter[str] = Counter()

    for text in df["text"].tolist():
        if not is_civil(text):
            continue
        total_civil += 1

        match = OPERATIVE_START.search(text)
        if not match:
            continue
        with_operative += 1
        operative = text[match.end() :]

        low = operative.lower()
        is_default = any(marker in low for marker in DEFAULT_MARKERS)
        if is_default:
            with_default += 1
            # Первая фраза — как именно начинается резолюция.
            first = re.split(r"(?<=[.;])\s+", operative.strip())[0][:110]
            openers[first] += 1
            for marker in CONSEQUENCE_MARKERS:
                if marker in low:
                    consequences[marker] += 1

    lines.append(f"гражданских дел:                    {total_civil}")
    lines.append(f"с резолютивной частью:              {with_operative}")
    lines.append(
        f"с признаками заочного/absence:      {with_default} "
        f"({with_default / with_operative * 100:.1f}% от резолюций)"
    )
    lines.append("")
    lines.append("=== НАЧАЛО РЕЗОЛЮЦИИ (топ-15) ===")
    for text, count in openers.most_common(15):
        lines.append(f"  {count:>4}  {text}")
    lines.append("")
    lines.append("=== ЧТО ПИШУТ О ПОСЛЕДСТВИЯХ ===")
    for marker, count in consequences.most_common():
        lines.append(f"  {count:>4}  «{marker}»")
    lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"записано: {OUT}")
    print(
        f"заочных среди резолюций: {with_default} из {with_operative} "
        f"({with_default / with_operative * 100:.1f}%)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
