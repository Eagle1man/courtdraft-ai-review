"""Извлечение правил построения резолютивной части из настоящих решений.

Источник: датасет TryDotAtwo/russian-legal-ner (HuggingFace), тестовая
выборка 10 000 документов. Из них гражданских с полной резолютивной
частью — 1 194. Это единственный доступный источник настоящих текстов
гражданских решений: открытых текстов судов общей юрисдикции не
существует, а учебники содержат теорию, а не образцы.

ЧТО ДЕЛАЕТ СКРИПТ
    1. Отбирает гражданские дела с резолютивной частью.
    2. Вырезает текст от «РЕШИЛ/ОПРЕДЕЛИЛ» до конца документа.
    3. Считает структуру: сколько пунктов, как пишутся суммы, как
       оформляется пошлина, как называются стороны.
    4. Печатает типовые формулировки — по ним видно, что в нашем
       коде сделано верно, а что нет.

ЗАПУСК
    .venv\\Scripts\\python.exe -X utf8 scripts\\extract_rules.py

ВЫВОД
    C:\\Users\\diorl\\AppData\\Local\\Temp\\opencode\\rules\\*.txt
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pandas as pd

PARQUET = Path(r"C:\Users\diorl\AppData\Local\Temp\opencode\hf_test.parquet")
OUT = Path(r"C:\Users\diorl\AppData\Local\Temp\opencode\rules")
OUT.mkdir(parents=True, exist_ok=True)

# Границы резолютивной части. Суд пишет по-разному: «РЕШИЛ:»,
# «ОПРЕДЕЛИЛ:», «ПОСТАНОВИЛ:», «ИСКОВЫЕ ТРЕБОВАНИЯ УДОВЛЕТВОРЕНЫ».
OPERATIVE_START = re.compile(
    r"(?:РЕШИЛ|ОПРЕДЕЛИЛ|ПОСТАНОВИЛ|ИСКОВЫЕ\s+ТРЕБОВАНИЯ\s+УДОВЛЕТВОРЕНЫ)"
    r"\s*:?\s*",
    re.I,
)

# Конец резолютивной части: обжалование, подписи, печать.
OPERATIVE_END = re.compile(
    r"(?:обжалован\w*\s+в\s+апелляционн|обжалован\w*\s+в\s+кассационн|"
    r"может\s+быть\s+обжалован|в\s+течение\s+\d+\s+(?:дней|суток|месяца)|"
    r"Мировой\s+судья|Судья\s+[А-ЯЁ])",
    re.I,
)

# Признаки гражданского дела.
CIVIL_MARKERS = (
    "исковые требования",
    "истец обратился в суд",
    "обратился в суд с иском",
    "о взыскании",
    "задолженност",
    "неустойк",
    "убытк",
    "признании права",
)


def is_civil(text: str) -> bool:
    low = text.lower()
    return sum(low.count(m) for m in CIVIL_MARKERS) >= 2


def cut_operative(text: str) -> str | None:
    """Вырезать резолютивную часть из документа."""
    start = OPERATIVE_START.search(text)
    if not start:
        return None
    rest = text[start.end() :]
    end = OPERATIVE_END.search(rest)
    if end:
        rest = rest[: end.start()]
    return rest.strip()


def main() -> int:
    df = pd.read_parquet(PARQUET)
    texts = df["text"].tolist()

    civil = [t for t in texts if is_civil(t)]
    operatives = [(t, cut_operative(t)) for t in civil]
    operatives = [(t, o) for t, o in operatives if o]

    lines: list[str] = []
    lines.append("ИЗВЛЕЧЕНИЕ ПРАВИЛ РЕЗОЛЮТИВНОЙ ЧАСТИ")
    lines.append("=" * 70)
    lines.append(f"документов в выборке:        {len(texts)}")
    lines.append(f"гражданских:                 {len(civil)}")
    lines.append(f"с резолютивной частью:       {len(operatives)}")
    lines.append("")

    # 1. Как начинается резолютивная часть.
    openers = Counter()
    for _, op in operatives:
        first = op[:80].strip()
        openers[first] += 1
    lines.append("=== НАЧАЛО РЕЗОЛЮТИВНОЙ ЧАСТИ (топ-20) ===")
    for text, count in openers.most_common(20):
        lines.append(f"  {count:>5}  {text}")
    lines.append("")

    # 2. Направление платежа.
    lines.append("=== НАПРАВЛЕНИЕ ПЛАТЕЖА ===")
    patterns = {
        "взыскать с X в пользу Y": re.compile(r"взыскать\s+с\s+\S+.*в\s+пользу", re.I),
        "взыскать с X (без в пользу)": re.compile(r"взыскать\s+с\s+\S+", re.I),
        "удовлетворить требования": re.compile(r"удовлетворить\s+.*требован", re.I),
        "отказать в удовлетворении": re.compile(r"отказать\s+в\s+удовлетворени", re.I),
        "признать (без взыскания)": re.compile(r"признать\s+(?:право|недействительн)", re.I),
    }
    for name, pattern in patterns.items():
        count = sum(1 for _, op in operatives if pattern.search(op))
        lines.append(f"  {count:>5}  {name}")
    lines.append("")

    # 3. Суммы: как оформляются.
    lines.append("=== ОФОРМЛЕНИЕ СУММ ===")
    amount_forms = {
        "цифрами + руб.": re.compile(r"\d[\d\s\u00a0]{2,}\s*руб", re.I),
        "цифрами + коп.": re.compile(r"\d+\s*коп", re.I),
        "прописью в скобках": re.compile(r"\(\s*[а-яё]+\s+тысяч", re.I),
        "всего (итог)": re.compile(r"всего\s+\d", re.I),
    }
    for name, pattern in amount_forms.items():
        count = sum(1 for _, op in operatives if pattern.search(op))
        lines.append(f"  {count:>5}  {name}")
    lines.append("")

    # 4. Пошлина и расходы.
    lines.append("=== ПОШЛИНА И РАСХОДЫ ===")
    fee_forms = {
        "расходы по уплате госпошлины": re.compile(
            r"расход\w*\s+по\s+уплат\w*\s+государственн\w*\s+пошлин", re.I
        ),
        "государственная пошлина": re.compile(
            r"государственн\w*\s+пошлин\w*", re.I
        ),
        "судебные расходы": re.compile(r"судебн\w*\s+расход\w*", re.I),
        "ст. 98 ГПК": re.compile(r"ст\.?\s*98\s*ГПК", re.I),
        "ст. 100 ГПК": re.compile(r"ст\.?\s*100\s*ГПК", re.I),
    }
    for name, pattern in fee_forms.items():
        count = sum(1 for _, op in operatives if pattern.search(op))
        lines.append(f"  {count:>5}  {name}")
    lines.append("")

    # 5. Стороны: как называются.
    lines.append("=== КАК НАЗЫВАЮТ СТОРОН ===")
    party_forms = {
        "ФИО (Абдулиной <ФИО1>)": re.compile(r"[А-ЯЁ][а-яё]+\s*<ФИО\d+>"),
        "название организации": re.compile(r"(?:ООО|АО|ПАО|ИП)\s+[«»\"]"),
        "истец/ответчик (словами)": re.compile(r"\bистец\w*\b|\bответчик\w*\b"),
    }
    for name, pattern in party_forms.items():
        count = sum(1 for _, op in operatives if pattern.search(op))
        lines.append(f"  {count:>5}  {name}")
    lines.append("")

    # 6. Структура: сколько предложений в резолюции.
    lines.append("=== СТРУКТУРА РЕЗОЛЮЦИИ ===")
    sentence_counts = []
    for _, op in operatives:
        parts = [p for p in re.split(r"(?<=[.;])\s+", op) if len(p.strip()) > 10]
        sentence_counts.append(len(parts))
    if sentence_counts:
        sentence_counts.sort()
        lines.append(f"  предложений: мин {sentence_counts[0]}, "
                     f"медиана {sentence_counts[len(sentence_counts)//2]}, "
                     f"макс {sentence_counts[-1]}")
    lines.append("")

    # 7. Примеры целиком — по три на каждый тип.
    lines.append("=== ПРИМЕРЫ РЕЗОЛЮТИВНЫХ ЧАСТЕЙ ===")
    shown = 0
    for _, op in operatives:
        if "взыскать с" in op.lower() and "в пользу" in op.lower():
            lines.append("-" * 70)
            lines.append(op[:1500])
            lines.append("")
            shown += 1
            if shown >= 5:
                break

    (OUT / "analysis.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"записано: {OUT / 'analysis.txt'}")
    print(f"гражданских с резолюцией: {len(operatives)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
