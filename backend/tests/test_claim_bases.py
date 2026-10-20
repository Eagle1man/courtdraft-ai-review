"""Тесты оснований требований, которые разбор решений выделил отдельно.

Три основания были объединены или потеряны:

1. Компенсация морального вреда (ст. 151 ГК РФ) — 131 резолюция
   из 1425 (9,2 %), то есть в каждой десятой;
2. Проценты за пользование чужими денежными средствами (ст. 395
   ГК РФ) — 63 резолюции (4,4 %). Они были смешаны с неустойкой,
   хотя основание и порядок расчёта у них разные;
3. «В полном объёме» — 289 резолюций (20,3 %). Самая частая
   формулировка, и её не было вовсе.
"""

from __future__ import annotations

from app.agents.claim_phrases import claim_basis, looks_like_claim
from app.drafting.operative import MoneyClaim, Outcome, build_operative

# Формулировки из настоящих резолюций.
MORAL_REAL = [
    "Взыскать с ответчика компенсацию морального вреда в размере 5000 руб.",
    "Истец просит взыскать с ЗАО «ЭР-Телеком Холдинг» возмещение "
    "материального и морального вреда.",
    "Требования о компенсации морального вреда подлежат удовлетворению.",
]

INTEREST_REAL = [
    "Взыскать с ответчика проценты за пользование чужими денежными "
    "средствами в размере 5654 руб.",
    "Истец просит взыскать проценты за пользование суммой займа по "
    "договору в сумме 10250 руб.",
    "Иск о взыскании убытков, процентов за пользование чужими "
    "денежными средствами, компенсации морального вреда — удовлетворить.",
]


class TestMoralDamage:
    """Компенсация морального вреда — самостоятельное основание."""

    def test_all_real_formulations_recognised(self) -> None:
        for text in MORAL_REAL:
            assert looks_like_claim(text), f"не опознано: {text}"

    def test_basis_is_moral_damage(self) -> None:
        for text in MORAL_REAL:
            assert claim_basis(text) == "компенсация морального вреда", (
                f"основание определено верно: {text} -> {claim_basis(text)}"
            )

    def test_separate_from_penalty(self) -> None:
        """Моральный вред не должен смешиваться с неустойкой."""
        assert claim_basis(
            "Взыскать с ответчика неустойку 1000 руб."
        ) == "неустойка и санкции"
        assert claim_basis(
            MORAL_REAL[0]
        ) == "компенсация морального вреда"

    def test_appears_in_operative_part(self) -> None:
        claim = MoneyClaim(
            amount=5000,
            basis="компенсация морального вреда",
            source="исковое заявление",
        )
        result = build_operative([claim], fee_paid=5100, budget="области")
        text = result.render()
        assert "5 000 руб." in text
        assert "морального вреда" in text


class TestInterestUnderArticle395:
    """Проценты по ст. 395 ГК РФ — не неустойка."""

    def test_all_real_formulations_recognised(self) -> None:
        for text in INTEREST_REAL:
            assert looks_like_claim(text), f"не опознано: {text}"

    def test_basis_is_interest(self) -> None:
        for text in INTEREST_REAL:
            assert (
                claim_basis(text) == "проценты за пользование денежными средствами"
            ), f"основание: {text} -> {claim_basis(text)}"

    def test_not_mixed_with_penalty(self) -> None:
        """Раньше «проценты» попадали в неустойку вместе с «пеня»."""
        assert claim_basis(
            "Взыскать с ответчика неустойку 500 руб."
        ) != "проценты за пользование денежными средствами"

    def test_interest_and_penalty_are_separate_claims(self) -> None:
        """В одном иске это два разных требования."""
        penalty = MoneyClaim(amount=50000, basis="неустойка и санкции",
                             source="договор")
        interest = MoneyClaim(
            amount=5654,
            basis="проценты за пользование денежными средствами",
            source="расчёт",
        )
        result = build_operative([penalty, interest], fee_paid=5100,
                                 budget="области")
        text = result.render()
        assert "50 000 руб." in text
        assert "5 654 руб." in text


class TestFullScope:
    """«В полном объёме» — самая частая формулировка в решениях."""

    def test_satisfied_mentions_full_scope(self) -> None:
        claim = MoneyClaim(amount=150000, basis="задолженность",
                           source="договор")
        text = build_operative([claim], fee_paid=5100, budget="области").render()
        assert "в полном объёме" in text

    def test_partial_does_not_claim_full_scope(self) -> None:
        """Частичное удовлетворение не говорит «в полном объёме»."""
        claim = MoneyClaim(amount=150000, granted_amount=90000,
                           basis="неустойка", source="договор",
                           outcome=Outcome.PARTIAL)
        text = build_operative([claim], fee_paid=5100, budget="области").render()
        assert "в полном объёме" not in text
        assert "частично" in text

    def test_denied_does_not_claim_full_scope(self) -> None:
        claim = MoneyClaim(amount=150000, basis="убытки", source="экспертиза",
                           outcome=Outcome.DENIED)
        text = build_operative([claim], fee_paid=5100, budget="области").render()
        assert "в полном объёме" not in text
