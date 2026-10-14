"""Тесты: госпошлина взыскивается в доход бюджета, а не в пользу истца.

Это юридическая ошибка, а не оформление. По ст. 98 ГПК РФ пошлина
возвращается бюджету: истец её не платил — её уплатил бюджет, и
возврат ему этих денег законом не предусмотрен. Раньше код писал
«взыскать с ответчика в пользу истца расходы по уплате
государственной пошлины», то есть предписывал отдать истцу деньги,
которые бюджету причитаются.

Подтверждено разбором 1 425 гражданских резолюций: «в доход бюджета»
встречается в 98 документах (6,9 %).
"""

from __future__ import annotations

from app.agents.evidence_pack import EvidenceItem, EvidencePack
from app.drafting.operative import REVIEW, MoneyClaim, build_operative
from app.drafting.requirements import extract_budget


def claim() -> MoneyClaim:
    return MoneyClaim(
        amount=150000,
        basis="задолженность по договору поставки",
        source="договор поставки № 14",
    )


def pack_with(*texts: str) -> EvidencePack:
    pack = EvidencePack(case_number="DEMO-001")
    for index, text in enumerate(texts, start=1):
        pack.items.append(
            EvidenceItem(
                category="evidence",
                text=text,
                source_document="01_claim.txt",
                source_type="CLAIM",
                order=index,
            )
        )
    return pack


class TestFeeGoesToBudget:
    """Пункт о пошлине — в доход бюджета."""

    def test_not_to_plaintiff(self) -> None:
        """Главное: пошлина не в пользу истца."""
        result = build_operative([claim()], fee_paid=5100, budget="городского округа Самара")
        fee_item = next(i for i in result.items if "пошлин" in i)
        assert "в пользу истца" not in fee_item
        assert "доход бюджета" in fee_item

    def test_budget_named(self) -> None:
        """Адресат бюджета обязателен: без него пошлина никуда не взыскана."""
        result = build_operative([claim()], fee_paid=5100, budget="городского округа Самара")
        fee_item = next(i for i in result.items if "пошлин" in i)
        assert "городского округа Самара" in fee_item

    def test_cites_article_98(self) -> None:
        result = build_operative([claim()], fee_paid=5100, budget="муниципального образования")
        fee_item = next(i for i in result.items if "пошлин" in i)
        assert "ст. 98 ГПК РФ" in fee_item

    def test_unknown_budget_flagged(self) -> None:
        """Без бюджета — видимая пометка, а не выдуманное название."""
        result = build_operative([claim()], fee_paid=5100, budget="")
        assert not result.is_complete
        assert any("бюджет" in gap for gap in result.gaps)
        fee_item = next(i for i in result.items if "пошлин" in i)
        assert REVIEW in fee_item

    def test_other_costs_still_to_plaintiff(self) -> None:
        """Иные расходы возвращаются истцу — он их понёс.

        Это не пошлина: расходы на представителя и почту истец
        оплатил сам, и они ему возвращаются (ст. 100 ГПК РФ).
        """
        result = build_operative([claim()], fee_paid=5100, costs=15000,
                                 budget="городского округа Самара")
        costs_item = next(i for i in result.items if "иные расходы" in i)
        assert "в пользу истца" in costs_item
        assert "ст. 100 ГПК РФ" in costs_item

    def test_claim_still_to_plaintiff(self) -> None:
        """Требование по делу возвращается истцу — как и было."""
        result = build_operative([claim()], fee_paid=5100, budget="области")
        debt_item = next(i for i in result.items if "задолженность" in i)
        assert "в пользу истца" in debt_item


class TestBudgetFromMaterials:
    """Бюджет берётся из материалов дела."""

    def test_explicit_budget_taken(self) -> None:
        pack = pack_with(
            "Государственная пошлина подлежит взысканию в доход бюджета "
            "городского округа Самара."
        )
        assert extract_budget(pack) == "городского округа Самара"

    def test_region_as_fallback(self) -> None:
        pack = pack_with(
            "Взыскать госпошлину в доход бюджета Самарской области."
        )
        assert extract_budget(pack) == "Самарской области"

    def test_absent_gives_empty(self) -> None:
        """Нет бюджета в материалах — пусто, а не выдумано."""
        assert extract_budget(pack_with("Исковое заявление без реквизитов")) == ""

    def test_empty_pack_gives_empty(self) -> None:
        assert extract_budget(EvidencePack()) == ""
