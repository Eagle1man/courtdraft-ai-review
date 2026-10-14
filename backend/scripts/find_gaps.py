"""Что ещё есть в настоящих резолюциях, чего нет в нашем коде.

Скрипт ищет конструкции, не реализованные в app.drafting.operative,
и считает, насколько они частые. Задача — не «сделать всё», а найти
то, что встречается часто и влияет на законность решения.

Запуск:
    .venv\\Scripts\\python.exe -X utf8 scripts\\find_gaps.py
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.extract_rules import OPERATIVE_START, is_civil  # noqa: E402

OUT = Path(r"C:\Users\diorl\AppData\Local\Temp\opencode\rules\gaps.txt")
PARQUET = Path(r"C:\Users\diorl\AppData\Local\Temp\opencode\hf_test.parquet")

# Конструкции, которых в нашем коде нет. Отбираются те, что меняют
# юридический смысл решения, а не оформление.
PROBES: dict[str, re.Pattern[str]] = {
    "отмена заочного решения": re.compile(r"отмени\w+\s+(?:заочное\s+)?решени", re.I),
    "восстановление срока": re.compile(r"восстанови\w*\s+(?:срок|пропущенн)", re.I),
    "признание права собственности": re.compile(
        r"признать\s+(?:право\s+)?собственност", re.I
    ),
    "признание договора недействительным": re.compile(
        r"признать\s+(?:недействительн|ничтожн|незаключённ)", re.I
    ),
    "обязать совершить действие": re.compile(
        r"обязать\s+\S+\s+(?:перечислить|уплатить|выдать|передать)", re.I
    ),
    "исполнительный лист": re.compile(r"выдать\s+исполнительн\w*\s+лист", re.I),
    "встречный иск": re.compile(r"встречн\w*\s+иск|удовлетворить\s+встречн", re.I),
    "подсчёт и взыскание": re.compile(r"произвести\s+подсч[её]т", re.I),
    "приостановление производства": re.compile(r"приостановить\s+производств", re.I),
    "оставление без рассмотрения": re.compile(
        r"оставить\s+без\s+рассмотрения", re.I
    ),
    "удовлетворение частично": re.compile(
        r"удовлетворить\s+(?:исковые\s+)?требования\s+частично|"
        r"удовлетворить\s+частично", re.I
    ),
    "полное удовлетворение": re.compile(
        r"в\s+полном\s+объ[её]м|удовлетворить\s+полностью", re.I
    ),
    "взыскание госпошлины в бюджет": re.compile(
        r"в\s+доход\s+бюджета|взыскать\s+госпошлин\w*\s+в\s+доход", re.I
    ),
    "срок исполнения": re.compile(r"в\s+течение\s+\d+\s+(?:месяц|день|рабоч)", re.I),
    "без ограничения срока исполнения": re.compile(
        r"без\s+ограничения\s+срока\s+исполнения|бессрочн", re.I
    ),
    "копия решения": re.compile(r"копи\w*\s+решени\w+\s+направить", re.I),
    "разъяснение права": re.compile(r"разъяснить\s+(?:ответчику|истцу)", re.I),
    "подписание протокола": re.compile(r"протокол\w*\s+подпис", re.I),
    "расходы на представителя": re.compile(
        r"расход\w*\s+на\s+(?:представител|юрист|адвокат)", re.I
    ),
    "компенсация морального вреда": re.compile(r"моральн\w*\s+вред", re.I),
    "неустойка за пользование деньгами": re.compile(
        r"процент\w*\s+за\s+пользовани\w+\s+(?:чужими\s+)?денежн", re.I
    ),
}


def main() -> int:
    import pandas as pd

    if not PARQUET.exists():
        print(f"нет файла: {PARQUET}")
        return 1

    df = pd.read_parquet(PARQUET)
    operands: list[str] = []
    for text in df["text"].tolist():
        if not is_civil(text):
            continue
        match = OPERATIVE_START.search(text)
        if match:
            operands.append(text[match.end() :])

    total = len(operands)
    counts: Counter[str] = Counter()
    for name, pattern in PROBES.items():
        counts[name] = sum(1 for op in operands if pattern.search(op))

    lines: list[str] = [
        "ЧТО ЕСТЬ В РЕЗОЛЮЦИЯХ И НЕТ У НАС",
        f"база: {total} гражданских резолюций",
        "=" * 60,
        "",
    ]
    lines.append(f"{'конструкция':<40} {'документов':>10}  {'%':>6}")
    lines.append("-" * 60)
    for name, count in counts.most_common():
        share = count / total * 100 if total else 0
        lines.append(f"{name:<40} {count:>10}  {share:>5.1f}%")
    lines.append("")
    lines.append("Порог внимания: конструкции выше 5% меняют юридический")
    lines.append("смысл решения и требуют правил в коде.")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"записано: {OUT}")
    print(f"резолюций в базе: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
