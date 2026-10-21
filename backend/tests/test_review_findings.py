"""Регрессионные тесты по находкам независимого ревью (D1-D5).

Каждый тест закрывает конкретную ошибку, найденную ревьюером на
собственных коммитах разбора требований:

D1 — одна сумма требования засчитывалась дважды под двумя
     основаниями (проект требовал 10 000 руб. вместо 5 000);
D2 — сумма из мотивировки суда становилась требованием;
D3 — по одному основанию две разные суммы в материалах: расхождение
     не показывалось судье;
D4 — требование без своей суммы исчезало молча;
D5 — сумма прописью в скобках не извлекалась.
"""

from __future__ import annotations

from app.agents.evidence_pack import EvidenceItem, EvidencePack
from app.drafting.requirements import extract_requirements


def _pack(text: str) -> EvidencePack:
    pack = EvidencePack(case_number="T-REVIEW")
    pack.items.append(
        EvidenceItem(
            category="claims",
            text=text,
            source_document="01_claim.txt",
            source_type="CLAIM",
            order=1,
        )
    )
    return pack


def _extract(text: str) -> tuple[list, list, list]:
    money, others, unrecognised = extract_requirements(_pack(text))
    return money, others, unrecognised


class TestNoDoubleCounting:
    def test_one_sum_not_counted_twice(self) -> None:
        # D1: «взыскать задолженность 5000 рублей и убытки» — сумма
        # одна, оснований два. Второе основание остаётся видимым, но
        # без своей суммы.
        money, _others, _unrecognised = _extract(
            "Взыскать с ответчика задолженность 5000 рублей и убытки."
        )
        amounts = {claim.basis: claim.amount for claim in money}
        assert amounts.get("задолженность по договору") == 5000
        assert amounts.get("убытки") is None
        total = sum(claim.amount for claim in money if claim.amount)
        assert total == 5000

    def test_neighbour_basis_keeps_its_own_sum(self) -> None:
        money, _others, _unrecognised = _extract(
            "Взыскать с ответчика убытки 5000 рублей и неустойку."
        )
        amounts = {claim.basis: claim.amount for claim in money}
        assert amounts.get("убытки") == 5000
        assert amounts.get("неустойка и санкции") is None
        total = sum(claim.amount for claim in money if claim.amount)
        assert total == 5000


class TestNarrativeIsNotAClaim:
    def test_sum_from_court_reasoning_not_claimed(self) -> None:
        # D2: «судом установлено, что ущерб составил 7777 рублей» —
        # это обстоятельства, а не требование истца.
        money, _others, _unrecognised = _extract(
            "Взыскать с ответчика неустойку 1000 рублей. Судом установлено, "
            "что ущерб истцу составил 7777 рублей."
        )
        amounts = {claim.basis: claim.amount for claim in money}
        assert amounts == {"неустойка и санкции": 1000}


class TestConflictingAmountsAreVisible:
    def test_two_sums_for_one_basis_reported(self) -> None:
        # D3: два требования с одним основанием и разными суммами —
        # судья должен увидеть расхождение.
        money, _others, unrecognised = _extract(
            "Взыскать с ответчика убытки в размере 5000 рублей "
            "и убытки в размере 3000 рублей."
        )
        amounts = {claim.basis: claim.amount for claim in money}
        assert amounts.get("убытки") == 5000
        assert any("две суммы" in item for item in unrecognised)
        assert any("5 000" in item and "3 000" in item for item in unrecognised)


class TestClaimWithoutAmountStaysVisible:
    def test_requirement_without_own_sum_is_not_lost(self) -> None:
        # D4: «взыскать убытки и неустойку в сумме 2202 рублей» —
        # требование «убытки» без своей суммы не исчезает: в
        # резолюции по нему будет пробел «не указана сумма».
        money, _others, _unrecognised = _extract(
            "Взыскать убытки и неустойку в сумме 2202 рублей."
        )
        amounts = {claim.basis: claim.amount for claim in money}
        assert amounts.get("неустойка и санкции") == 2202
        assert "убытки" in amounts
        assert amounts.get("убытки") is None


class TestAmountSpelledOutInBrackets:
    def test_sum_with_words_in_brackets(self) -> None:
        # D5: «15 191 (Пятнадцать тысяч сто девяносто один) рубль
        # 40 копеек» — цифры есть, между ними и словом «рубль»
        # стоит пропись в скобках.
        money, _others, _unrecognised = _extract(
            "Взыскать с ответчика убытки в размере 15 191 "
            "(Пятнадцать тысяч сто девяносто один) рубль 40 копеек."
        )
        claims = {claim.basis: (claim.amount, claim.kopecks) for claim in money}
        assert claims.get("убытки") == (15191, 40)

    def test_brackets_with_digits_break_the_link(self) -> None:
        # В скобках с цифрами — ссылка на норму, а не пропись суммы
        # («в размере 5 000 (в том числе 3 000) рублей»: какая сумма
        # просительная — неоднозначно). Связь числа и «рублей» при
        # такой форме не устанавливается, и фраза остаётся видимой
        # в непознанных, а не превращается в выдуманную сумму.
        money, _others, unrecognised = _extract(
            "Взыскать с ответчика убытки в размере 15 191 "
            "(статья 395 ГК РФ) рублей."
        )
        claims = {claim.basis: (claim.amount, claim.kopecks) for claim in money}
        # Требование остаётся видимым, но без своей суммы: в
        # резолюции по нему — пробел «не указана сумма». Выдуманной
        # суммы в проекте не появляется.
        assert claims["убытки"][0] is None
        assert not unrecognised
