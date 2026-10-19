"""Проверка родовой подсудности (п. 5 ч. 1 ст. 23 ГПК РФ).

Имущественный спор при цене иска до 100 000 руб. включительно
рассматривает мировой судья, свыше — районный суд. Проверка не решает
за судью: она сверяет цену иска с тем судом, который назван в
материалах, и расхождение показывает судье. Суд из материалов
не определяется — это признак, а не выдумка.

Подведомственность «арбитраж или общая юрисдикция» (ст. 27, 28 АПК РФ,
ч. 2.1 ст. 33 ГПК РФ) здесь не решается: она требует установления рода
деятельности сторон, который по текстам материалов уверенно не
определяется. Родовая подсудность — закрытое правило с числом, его
можно проверять честно.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Порог родовой подсудности: п. 5 ч. 1 ст. 23 ГПК РФ, цена иска
#: до 100 000 руб. включительно — мировой судья.
WORLD_LIMIT: float = 100_000.0

_WORLD_RE = re.compile(r"миров\w*\s+суд\w*", re.IGNORECASE)
_DISTRICT_RE = re.compile(r"районн\w*\s+суд\w*", re.IGNORECASE)


@dataclass(frozen=True)
class JurisdictionFinding:
    """Расхождение между ценой иска и судом в материалах."""

    expected: str  # «мировой судья» | «районный суд»
    found: str  # что написано в материалах
    reason: str  # готовый текст замечания


def expected_tier(price: float) -> str:
    """Какой суд должен рассматривать спор по цене иска."""
    if 0 < price <= WORLD_LIMIT:
        return "мировой судья"
    return "районный суд"


def _court_tier_in(text: str) -> str | None:
    if _WORLD_RE.search(text):
        return "мировой судья"
    if _DISTRICT_RE.search(text):
        return "районный суд"
    return None


def check_jurisdiction(
    court_texts: list[str], claim_total: float
) -> list[JurisdictionFinding]:
    """Сверить цену иска с судом, названным в материалах.

    Тексты материалов передаются списком: суд ищется по всем
    документам дела, а не по первому попавшемуся. Материалы не называют
    суд — проверка молчит: отсутствие признака не превращается в
    замечание.
    """
    if claim_total <= 0:
        return []
    expected = expected_tier(claim_total)
    for text in court_texts:
        found = _court_tier_in(text)
        if found is None:
            continue
        if found != expected:
            return [
                JurisdictionFinding(
                    expected=expected,
                    found=found,
                    reason=(
                        f"при цене иска {claim_total:.0f} руб. родовая "
                        f"подсудность — {expected} (п. 5 ч. 1 ст. 23 ГПК РФ), "
                        f"а в материалах дела указан {found}: проверить, "
                        "куда передано дело"
                    ),
                )
            ]
        return []
    return []
