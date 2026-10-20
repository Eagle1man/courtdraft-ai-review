"""Тесты: направление государственной пошлины в резолютивной части.

Пошлина уплачивается истцом в бюджет. Если иск удовлетворён, суд
присуждает истцу понесённые им расходы — то есть взыскивает пошлину
с ответчика В ПОЛЬЗУ ИСТЦА (ч. 1 ст. 98 ГПК РФ). В доход бюджета
пошлина идёт только тогда, когда истец был освобождён от её уплаты
(ч. 1 ст. 103 ГПК РФ).

Раньше код был обратным и обосновывал это частотой: «в доход бюджета»
встречается в 98 решениях из 1 425. Частота в практике — не довод,
правило задаёт закон. Ошибка была и дорогой, и заметной: пункт
отправлял пошлину в бюджет, а итог «а всего» включал её в сумму,
взыскиваемую в пользу истца, то есть проект противоречил сам себе.
"""

from __future__ import annotations

from app.agents.evidence_pack import EvidenceItem, EvidencePack
from app.drafting.operative import REVIEW, MoneyClaim, build_operative
from app.drafting.requirements import extract_budget, extract_requirements


def claim() -> MoneyClaim:
    return MoneyClaim(
        amount=150000,
        basis="задолженность по договору поставки",
        source="договор поставки № 14",
    )


def fee_item_of(result: object) -> str:
    return next(item for item in result.items if "пошлин" in item)  # type: ignore[attr-defined]


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


class TestFeeGoesToPlaintiff:
    """По умолчанию пошлина идёт истцу — он её платил."""

    def test_to_plaintiff(self) -> None:
        result = build_operative([claim()], fee_paid=5100)
        fee_item = fee_item_of(result)
        assert "в пользу" in fee_item
        assert "доход бюджета" not in fee_item

    def test_cites_article_98(self) -> None:
        result = build_operative([claim()], fee_paid=5100)
        assert "ст. 98 ГПК РФ" in fee_item_of(result)

    def test_budget_argument_ignored_without_exemption(self) -> None:
        """Название бюджета из материалов не перенаправляет пошлину.

        Пока не известно, что истец освобождён от уплаты, бюджет не
        имеет значения: пошлина возвращается плательщику.
        """
        result = build_operative([claim()], fee_paid=5100, budget="городского округа Самара")
        assert "доход бюджета" not in fee_item_of(result)

    def test_total_includes_fee_consistently(self) -> None:
        """Пошлина входит в итог так же, как в самом пункте.

        Раньше пункт уводил пошлину в бюджет, а «а всего» складывало её
        в сумму в пользу истца. Проект говорил две разные вещи.
        """
        result = build_operative([claim()], fee_paid=5100, total_line=True)
        total_item = next(item for item in result.items if "Всего подлежит" in item)
        assert "155" in total_item


class TestFeeGoesToBudgetWhenExempt:
    """В доход бюджета — только при освобождении истца от уплаты."""

    def test_to_budget(self) -> None:
        result = build_operative(
            [claim()], fee_paid=5100, fee_exempt=True, budget="городского округа Самара"
        )
        fee_item = fee_item_of(result)
        assert "в доход бюджета" in fee_item
        assert "ст. 103 ГПК РФ" in fee_item

    def test_budget_named(self) -> None:
        result = build_operative(
            [claim()], fee_paid=5100, fee_exempt=True, budget="городского округа Самара"
        )
        assert "городского округа Самара" in fee_item_of(result)

    def test_unknown_budget_flagged(self) -> None:
        """Без бюджета — видимая пометка, а не выдуманное название."""
        result = build_operative([claim()], fee_paid=5100, fee_exempt=True, budget="")
        assert not result.is_complete
        assert any("бюджет" in gap for gap in result.gaps)
        assert REVIEW in fee_item_of(result)


class TestOtherCosts:
    """Иные расходы возвращаются истцу — он их понёс."""

    def test_other_costs_still_to_plaintiff(self) -> None:
        result = build_operative([claim()], fee_paid=5100, costs=15000)
        costs_item = next(i for i in result.items if "иные расходы" in i)
        assert "в пользу истца" in costs_item
        assert "ст. 100 ГПК РФ" in costs_item

    def test_claim_still_to_plaintiff(self) -> None:
        result = build_operative([claim()], fee_paid=5100, budget="области")
        debt_item = next(i for i in result.items if "задолженность" in i)
        assert "в пользу истца" in debt_item


class TestFeeIsNotADebt:
    """Пошлина не должна попадать в требования по существу."""

    def test_fee_not_counted_as_money_claim(self) -> None:
        """Сумма долга и пошлина не смешиваются.

        Раньше проверка на пошлину стояла после определения основания,
        поэтому предложение с узнаваемым основанием проскакивало в
        требования. В деле real-08 система назвала размер пошлины
        задолженностью и постановила 416 руб. вместо 10 148 руб.
        """
        pack = pack_with(
            "Прошу взыскать задолженность по договору поставки "
            "в размере 10 148 руб. 00 коп., а также государственную "
            "пошлину в размере 416 руб. 00 коп."
        )
        money, _others, _unrecognised = extract_requirements(pack)
        amounts = {c.amount for c in money}
        assert 10148 in amounts
        assert 416 not in amounts

    def test_fee_amount_still_extracted(self) -> None:
        """Размер пошлины при этом должен находиться: он идёт в ст. 98."""
        from app.drafting.requirements import extract_fee_and_costs

        pack = pack_with(
            "Прошу взыскать задолженность по договору поставки "
            "в размере 10 148 руб. 00 коп. Государственная пошлина "
            "уплачена в размере 416 руб. 00 коп."
        )
        fee, _costs = extract_fee_and_costs(pack)
        assert fee == 416


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
