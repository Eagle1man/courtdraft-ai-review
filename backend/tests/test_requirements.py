"""Тесты извлечения требований из пакета доказательств.

Проверяется не «нашлось хоть что-то», а соответствие тому, как судья
пишет резолютивную часть: требование входит в неё один раз, с суммой
из материалов и с указанием документа. Всё остальное — помечается как
неп��ознанное, а не попадает в проект решения по догадке.
"""

from __future__ import annotations

from app.agents.evidence_pack import EvidenceItem, EvidencePack
from app.drafting.operative import build_operative
from app.drafting.requirements import extract_requirements


def pack_with(*texts: str, category: str = "claims") -> EvidencePack:
    """Пакет из заданных фраз."""
    pack = EvidencePack(case_number="5-1/2019")
    for index, text in enumerate(texts):
        pack.items.append(
            EvidenceItem(
                category=category,
                text=text,
                source_document=f"документ {index + 1}.txt",
                source_type="CLAIM",
            )
        )
    return pack


class TestClaimRecognition:
    """Основные виды требований должны узнаваться."""

    def test_debt_claim(self) -> None:
        pack = pack_with(
            "Истец требует взыскать с ответчика задолженность по договору "
            "поставки в размере 150000 рублей."
        )
        money, others, missed = extract_requirements(pack)
        assert len(money) == 1
        assert money[0].amount == 150000
        assert money[0].basis == "задолженность по договору"
        assert not others
        assert not missed

    def test_penalty_claim_precedes_generic(self) -> None:
        """«Неустойка» не должна попадать под общее правило.

        Порядок шаблонов задаёт приоритет: более конкретное основание
        проверяется первым, иначе все требования сводились бы к одному.
        """
        pack = pack_with(
            "Истец просит взыскать неустойку за просрочку оплаты "
            "в размере 90000 рублей."
        )
        money, _, _ = extract_requirements(pack)
        assert money[0].basis == "неустойка и санкции"

    def test_costs_for_representative(self) -> None:
        pack = pack_with(
            "Истец требует возместить расходы на представителя "
            "в размере 20000 рублей."
        )
        money, _, _ = extract_requirements(pack)
        assert money[0].basis == "расходы на представителя"

    def test_non_money_claim(self) -> None:
        """Признание договора недействительным денег не имеет."""
        pack = pack_with(
            "Истец просит признать недействительным договор поставки."
        )
        money, others, _ = extract_requirements(pack)
        assert not money
        assert len(others) == 1
        assert others[0].basis if hasattr(others[0], "basis") else True
        assert "недействительным" in others[0].description


class TestNotFabricated:
    """Главное: не выдумывать то, чего в материалах нет."""

    def test_claim_without_amount_kept_as_gap(self) -> None:
        """Требование есть, суммы нет — сумма остаётся незаполненной."""
        pack = pack_with(
            "Истец требует взыскать с ответчика задолженность по договору."
        )
        money, _, _ = extract_requirements(pack)
        assert len(money) == 1
        assert money[0].amount is None

        result = build_operative(money, fee_paid=5100)
        assert not result.is_complete
        assert "ТРЕБУЕТ ПРОВЕРКИ" in result.render()

    def test_year_not_taken_as_amount(self) -> None:
        """Год и номер дела не должны становиться суммой взыскания."""
        pack = pack_with(
            "Истец требует взыскать задолженность по договору "
            "за 2019 год."
        )
        money, _, _ = extract_requirements(pack)
        assert money[0].amount is None

    def test_unrecognised_claim_is_reported(self) -> None:
        """Непонятное требование попадает в список непознанных."""
        pack = pack_with(
            "Истец требует привлечь ответчика к ответственности "
            "за загрязнение окружающей среды."
        )
        money, others, missed = extract_requirements(pack)
        assert not money
        assert not others
        assert missed
        assert "загрязнение" in missed[0]

    def test_argument_is_not_a_claim(self) -> None:
        """Обоснование в резолютивную часть не попадает."""
        pack = pack_with(
            "Истец считает, что ответчик действует недобросовестно "
            "и уклоняется от исполнения обязательства."
        )
        money, others, missed = extract_requirements(pack)
        assert not money
        assert not others
        assert not missed

    def test_empty_pack_gives_empty_result(self) -> None:
        money, others, missed = extract_requirements(EvidencePack())
        assert not money and not others and not missed


class TestDeduplication:
    """Одно требование — один пункт в резолютивной части."""

    def test_same_basis_twice_gives_one_claim(self) -> None:
        pack = pack_with(
            "Истец требует взыскать задолженность 150000 рублей.",
            "Повторно: взыскать задолженность по договору 150000 рублей.",
        )
        money, _, _ = extract_requirements(pack)
        assert len(money) == 1

    def test_different_bases_stay_separate(self) -> None:
        pack = pack_with(
            "Истец требует взыскать задолженность 150000 рублей.",
            "Истец требует взыскать неустойку 90000 рублей.",
        )
        money, _, _ = extract_requirements(pack)
        assert len(money) == 2

    def test_source_recorded(self) -> None:
        """Каждое требование помнит документ, из которого взято."""
        pack = pack_with("Истец требует взыскать задолженность 150000 рублей.")
        money, _, _ = extract_requirements(pack)
        assert money[0].source
        assert "документ" in money[0].source


class TestEndToEnd:
    """Сквозной путь: пакет -> требования -> резолютивная часть."""

    def test_full_pipeline(self) -> None:
        pack = pack_with(
            "Истец требует взыскать с ответчика задолженность по договору "
            "поставки в размере 150000 рублей.",
            "Истец требует взыскать неустойку за просрочку в размере 90000 рублей.",
            "Истец просит признать недействительным договор поставки.",
        )
        money, others, missed = extract_requirements(pack)
        assert not missed

        result = build_operative(money, others, fee_paid=5100)
        text = result.render()

        assert "150 000" in text
        assert "90 000" in text
        assert "недействительным" in text
        # Направление платежа задано конструкцией, а не текстом модели.
        assert "взыскать с ответчика в пользу истца" in text
