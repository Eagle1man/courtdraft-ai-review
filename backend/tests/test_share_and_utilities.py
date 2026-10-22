"""Тест: требования, найденные на живых прогонах 22.10.2026.

Два дефекта, которые система не видела на synthetic-тестах:

1. real-10: требование «взыскать 1/3 часть от суммы 55 021,47» —
   рублёвой суммы требования в материалах нет (обезличена), и окно
   уходило в нераспознанные. Проект выдавал «резолютивная часть не
   сформирована» — иск выглядел не поданным, хотя он подан.

2. real-01: «задолженность за ЖКУ 11 107,84» и уточнение «задолженность
   по оплате за ремонт и содержание жилья 7 919,17» схлопывались в
   одно основание «задолженность по договору», и проект требовал
   выбрать одну из двух сумм вместо двух пунктов.
"""

from __future__ import annotations

from app.agents.claim_phrases import claim_basis
from app.agents.evidence_pack import EvidenceItem, EvidencePack
from app.drafting.operative import Outcome
from app.drafting.requirements import extract_requirements


def _money(text: str) -> dict[str, object]:
    pack = EvidencePack(
        items=[
            EvidenceItem(
                category="claims",
                text=text,
                source_document="01_claim.txt",
                source_type="иск",
                order=1,
            )
        ],
    )
    money, _others, _unrecognised = extract_requirements(pack)
    return {claim.basis: claim for claim in money}


class TestShareClaim:
    """Долевое требование — требование, а не пустое место."""

    SHARE = (
        "Просит взыскать с ответчика 1/3 часть, то есть часть "
        "пропорциональную его доли в праве общей долевой собственности, "
        "от суммы уплаченной за услуги газоснабжения, составляющей "
        "55021 рубль 47 копеек."
    )

    def test_share_claim_extracted(self) -> None:
        claims = _money(self.SHARE)
        assert "расходы в долевой части 1/3" in claims

    def test_share_claim_has_no_amount(self) -> None:
        """Сумма требования — доля, а не рубль: системы не считает её.

        Число, которого нет в материалах, система не выдумывает:
        сумма остаётся None, и в резолютивной части судья видит
        ТРЕБУЕТ ПРОВЕРКИ СПЕЦИАЛИСТОМ.
        """
        claim = _money(self.SHARE)["расходы в долевой части 1/3"]
        assert claim.amount is None

    def test_share_claim_renders_for_judge(self) -> None:
        """Требование не пропадает из резолютивной части."""
        pack = EvidencePack(
            items=[
                EvidenceItem(
                    category="claims",
                    text=self.SHARE,
                    source_document="01_claim.txt",
                    source_type="иск",
                    order=1,
                )
            ],
        )
        money, _others, _unrec = extract_requirements(pack)
        from app.drafting.operative import build_operative

        text = build_operative(money).render()
        assert "расходы в долевой части 1/3" in text
        assert "ТРЕБУЕТ ПРОВЕРКИ СПЕЦИАЛИСТОМ" in text

    def test_two_fractions_are_two_claims(self) -> None:
        """Две доли в одном иске — два пункта, а не один.

        Находка независимого ревью: ключ «расходы в долевой части» был
        фиксированным, и «1/3 часть» + «1/2 часть» схлопывались в один
        пункт — вторая доля из резолютивной части исчезала.
        """
        claims = _money(
            "Просит взыскать 1/3 часть от суммы 55021 руб. 47 копеек, "
            "а также 1/2 часть от суммы 12000 рублей."
        )
        assert "расходы в долевой части 1/3" in claims
        assert "расходы в долевой части 1/2" in claims


class TestUtilitiesVsRepair:
    """ЖКУ и ремонт — разные требования, а не одна задолженность."""

    def test_claim_basis_split(self) -> None:
        assert (
            claim_basis("взыскать задолженность за жилищно-коммунальные "
                        "услуги в размере 11107 руб.")
            == "задолженность за жилищно-коммунальные услуги"
        )
        assert (
            claim_basis("взыскать задолженность по оплате за ремонт "
                        "и содержание жилья в размере 7919 руб.")
            == "задолженность за ремонт и содержание жилья"
        )

    def test_generic_debt_still_works(self) -> None:
        """Общий якорь не ослаблен: простая задолженность не изменилась."""
        assert claim_basis("взыскать задолженность по договору в размере "
                           "150000 руб.") == "задолженность по договору"

    def test_split_needs_only_one_word_after_debt(self) -> None:
        """Разбор по пунктам режет «ремонт и содержание» по «и».

        Окно «задолженность по оплате за ремонт и содержание жилья ...
        7 919 руб., по оплате коммунальных услуг ... 3 188 руб.»
        дробится, и кусок доходит как «задолженность ... за ремонт».
        Шаблон обязан узнавать основание и по одному слову.
        """
        assert (
            claim_basis("взыскать задолженность по оплате за ремонт "
                        "в размере 7919 руб.")
            == "задолженность за ремонт и содержание жилья"
        )


class TestBothDebtsInOneWindow:
    def test_two_debts_two_claims(self) -> None:
        """Два требования в одном окне дают два пункта, не конфликт."""
        claims = _money(
            "Просит взыскать с ответчика задолженность за жилищно-"
            "коммунальные услуги в размере 11107 рублей 84 копейки."
        )
        assert "задолженность за жилищно-коммунальные услуги" in claims
        claim = claims["задолженность за жилищно-коммунальные услуги"]
        assert claim.amount == 11107
        assert claim.outcome is Outcome.SATISFIED
