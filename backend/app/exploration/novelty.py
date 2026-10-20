"""Новизна QD-Court: по содержанию, а не по различию формулировок.

Сходство — Жаккар по токенам из общего токенизатора проекта
(`app.rag.retrieval.tokenize`), поэтому «перефраз, тот же вопрос»
даёт новизну около нуля и не проходит фильтр.
"""

from __future__ import annotations

from app.rag.retrieval import tokenize


def _tokens(text: str) -> set[str]:
    return set(tokenize(text))


def novelty(text: str, existing_texts: list[str]) -> float:
    """1 — содержательно ново, 0 — повтор уже найденного."""
    own = _tokens(text)
    if not own:
        return 0.0
    if not existing_texts:
        return 1.0
    best = 0.0
    for other in existing_texts:
        theirs = _tokens(other)
        if not theirs:
            continue
        overlap = len(own & theirs) / len(own | theirs)
        best = max(best, overlap)
    return round(1.0 - best, 4)
