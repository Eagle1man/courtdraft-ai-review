"""Проверки резолютивной части: только текст решения и метаданные дела.

Набор задан датасетом tests/data/resol_fixtures.json: каждое правило имеет хотя бы
одну фикстуру с меткой defect и ни одного ложного срабатывания на clean.

Правило без нужных метаданных молчит, а не угадывает: отсутствие данных в тексте
не равно отсутствию факта в деле.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

# Разбивка только перед заглавной буквой: «…2 000,00 руб. и расходов на …» — одно предложение.
_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[«А-ЯЁ])")
_MONEY = re.compile(r"(\d[\d\s]*[.,]\d{2})\s*руб")
_FEE_TOTAL = re.compile(r"всего подлежит взысканию\s+(\d[\d\s]*[.,]\d{2})", re.I)
_VYSK = re.compile(r"^взыскать\b", re.I)


@dataclass(frozen=True)
class Defect:
    """Одно срабатывание проверки в резолютивной части."""

    id: str
    severity: str
    fragment: str
    reason: str


def sentences(text: str) -> list[str]:
    """Разбивает резолютивную часть на предложения."""
    return [s.strip() for s in _SPLIT.split(text) if s.strip()]


def _amount(value: str) -> float:
    return float(value.replace(" ", "").replace("\u00a0", "").replace(",", "."))


def _no_costs(text: str, meta: Mapping[str, Any]) -> list[Defect]:
    """Проверки 1: распределение госпошлины и судебных издержек отсутствует."""
    if re.search(r"пошлин|судебн\w*\s*расход|издержк", text, re.I):
        return []
    return [
        Defect(
            "RESOL_NO_COSTS",
            "HIGH",
            "",
            "нет пункта о распределении государственной пошлины и судебных издержек",
        )
    ]


# Связки, которыми пошлина и иные издержки свалены в один пункт.
_MERGE_LINK = re.compile(
    r"состоящие из|а всего|в том числе|и расход\w* на|и судебн\w* издержк",
    re.I,
)


def _costs_merged(text: str, meta: Mapping[str, Any]) -> list[Defect]:
    """Проверки 2: госпошлина и иные издержки в одном пункте, а не раздельно."""
    out: list[Defect] = []
    for s in sentences(text):
        if not _VYSK.search(s):
            continue
        if not re.search(r"пошлин", s, re.I):
            continue
        if not re.search(r"представител|экспертиз|издержк", s, re.I):
            continue
        if _MERGE_LINK.search(s):
            out.append(
                Defect(
                    "RESOL_COSTS_MERGED",
                    "MEDIUM",
                    s[:120],
                    "госпошлина и иные издержки объединены в одном пункте",
                )
            )
    return out


def _total_mismatch(text: str, meta: Mapping[str, Any]) -> list[Defect]:
    """Проверки 3: строка «Всего подлежит взысканию» не равна сумме пунктов."""
    m = _FEE_TOTAL.search(text)
    if not m:
        return []
    total = _amount(m.group(1))
    parts = [s for s in sentences(text) if _VYSK.search(s)]
    computed = sum(_amount(a) for s in parts for a in _MONEY.findall(s))
    if abs(computed - total) <= 0.011:
        return []
    return [
        Defect(
            "RESOL_TOTAL_MISMATCH",
            "MEDIUM",
            m.group(0),
            f"сумма пунктов {computed:.2f} не равна заявленным {total:.2f}",
        )
    ]


def _no_amount(text: str, meta: Mapping[str, Any]) -> list[Defect]:
    """Проверки 4: имущественное требование без определённой суммы."""
    out: list[Defect] = []
    for s in sentences(text):
        if not re.search(r"в размере", s, re.I):
            continue
        if not re.search(r"подлежащем определению|подлежит установлению", s, re.I):
            continue
        if _MONEY.search(s):
            continue
        out.append(Defect("RESOL_NO_AMOUNT", "HIGH", s[:120], "размер требования не определён"))
    return out


def _fully_partially(text: str, meta: Mapping[str, Any]) -> list[Defect]:
    """Проверки 5: «удовлетворить полностью» вместе с отказом в остальной части."""
    if not re.search(r"удовлетворить полностью", text, re.I):
        return []
    if not re.search(r"в остальной части", text, re.I) or not re.search(r"отказать", text, re.I):
        return []
    return [
        Defect(
            "RESOL_FULLY_PARTIALLY",
            "HIGH",
            "",
            "полное удовлетворение совмещено с отказом в остальной части",
        )
    ]


Rule = Callable[[str, Mapping[str, Any]], list[Defect]]

# ── Пачка 2: стороны ───────────────────────────────────────────────────────
_PARTY_ORG = r"(?:ООО|АО|ПАО|ЗАО|ГУП|МУП)\s+«[^»]+»"
_PARTY_IP = r"ИП\s+[А-ЯЁ][а-яё-]+(?:\s+[А-ЯЁ][а-яё-]+){0,2}"
_PARTY_NAME = r"[А-ЯЁ][а-яё-]+\s+[А-ЯЁ][а-яё-]+(?:\s+[А-ЯЁ][а-яё-]+){1,2}"
_PARTY = rf"(?:{_PARTY_ORG}|{_PARTY_IP}|{_PARTY_NAME})"
_RECIPIENT = re.compile(rf"в пользу\s+({_PARTY})")
_DEBTOR = re.compile(rf"взыскать\s+с\s+({_PARTY})", re.I)
_ID = re.compile(r"ИНН|СНИЛС|паспорт|водительск|ОГРН", re.I)
_SIDE_STOP = re.compile(r"\s+в\s+|\s+и\s+|\s+доход\b|[,.;]")
_COSTS = re.compile(r"пошлин|расход|издержк|бюджет", re.I)


def _window(s: str, start: int) -> str:
    """Текст между концом имени стороны и ближайшим концом этой конструкции."""
    m = _SIDE_STOP.search(s, start)
    return s[start : m.start()] if m else s[start:]


def _no_whom(text: str, meta: Mapping[str, Any]) -> list[Defect]:
    """Проверки 6: взыскание без указания, с кого и в чью пользу."""
    out: list[Defect] = []
    for s in sentences(text):
        if not _VYSK.search(s) or _COSTS.search(s):
            continue
        if _RECIPIENT.search(s) or re.search(r"в\s+доход\b|\bс\s+[«А-ЯЁ]", s):
            continue
        out.append(
            Defect("RESOL_NO_WHOM", "HIGH", s[:120], "не указано, с кого и в чью пользу взыскание")
        )
    return out


def _no_id(text: str, meta: Mapping[str, Any]) -> list[Defect]:
    """Проверки 9: у стороны рядом с именем нет идентификатора.

    Лица с «года рождения» сторонами не считаются: в тексте они встречаются
    не после «с» и не после «в пользу».
    """
    out: list[Defect] = []
    for s in sentences(text):
        for pattern in (_DEBTOR, _RECIPIENT):
            for m in pattern.finditer(s):
                party = m.group(1)
                if _ID.search(_window(s, m.end())):
                    continue
                out.append(
                    Defect(
                        "RESOL_NO_ID",
                        "MEDIUM",
                        party,
                        "у стороны рядом с именем нет ИНН/СНИЛС/паспорта",
                    )
                )
    return out


def _no_shares(text: str, meta: Mapping[str, Any]) -> list[Defect]:
    """Проверки 10: несколько ответчиков в одном взыскании без долей и без солидарности."""
    out: list[Defect] = []
    for s in sentences(text):
        if not _VYSK.search(s) or re.search(r"солидарн", s, re.I):
            continue
        m = _DEBTOR.search(s)
        if not m:
            continue
        seg = s[m.start() :]
        seg = re.split(r" в пользу | в доход ", seg, maxsplit=1)[0]
        if re.search(r"\sи\s", seg) and not re.search(r"дол|1/\d", seg):
            out.append(
                Defect(
                    "RESOL_NO_SHARES",
                    "HIGH",
                    seg[:120],
                    "несколько ответчиков без солидарной ответственности или долей",
                )
            )
    return out


RULES: list[Rule] = [
    _no_costs,
    _costs_merged,
    _total_mismatch,
    _no_amount,
    _fully_partially,
    _no_whom,
    _no_id,
    _no_shares,
]


def check_resolution(text: str, meta: Mapping[str, Any] | None = None) -> list[Defect]:
    """Возвращает все срабатывания проверок для текста резолютивной части."""
    data: Mapping[str, Any] = meta or {}
    out: list[Defect] = []
    for rule in RULES:
        out.extend(rule(text, data))
    return out
