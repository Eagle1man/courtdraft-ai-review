"""Тест: расходы на представителя — самостоятельное требование.

Дефект найден на живом материале. Основание «расходы на
представителя» в коде было, но не срабатывало ни на одной реальной
формулировке: требование «на» вплотную к «представител», а в заявлениях
пишут «расходы на оплату услуг представителя». Итог был тот, что
требование уходило в непознанные, в резолюцию не попадало, и судья
получал решение без него — притом что это самое частое из требований,
заявляемых почти в каждом иске.

Проверяется на формулировках из материалов, а не на синтетике,
 специально подогнанной под регулярное выражение.
"""

from __future__ import annotations

import pytest

from app.agents.claim_phrases import claim_basis
from app.drafting.operative import build_operative
from app.drafting.requirements import extract_requirements

CLAIM = (
    "Прошу взыскать с Фирма «Вымышленная Строй» в пользу Образцов "
    "Пётр Петрович расходы на оплату услуг представителя в размере "
    "30 000 руб. 00 коп."
)


class TestRepresentativeCostsBasis:
    @pytest.mark.parametrize(
        "phrase",
        [
            "расходы на представителя",
            "расходы на оплату услуг представителя",
            "расходы на юридическую помощь представителя",
            "расходы на оплату услуг адвоката",
            "расходы на оплату услуг юриста",
            "возмещение расходов на представителя",
        ],
    )
    def test_phrase_recognised(self, phrase: str) -> None:
        text = f"Прошу взыскать с ответчика {phrase} в размере 30 000 руб."
        assert claim_basis(text) == "расходы на представителя"

    def test_claim_reaches_operative_part(self) -> None:
        """Главное: требование доходит до решения, а не теряется."""
        from app.agents.evidence_pack import EvidenceItem, EvidencePack

        pack = EvidencePack(
            items=[
                EvidenceItem(
                    category="claims",
                    text=CLAIM,
                    source_document="01_claim.txt",
                    source_type="иск",
                    order=1,
                )
            ]
        )
        money, others, unrecognised = extract_requirements(pack)

        assert [c.amount for c in money] == [30_000.0]
        assert money[0].basis == "расходы на представителя"
        assert not others
        assert not unrecognised

        text = build_operative(money, fee_stakes=False).render()
        assert "30 000 руб. 00 коп." in text
        assert "расходы на представителя" in text

    def test_not_confused_with_fee(self) -> None:
        """Расходы на представителя — не госпошлина.

        Это разные вещи: пошлину возвращают в бюджет по ст. 98, расходы
        на представителя — истцу по ст. 100. Если смешать, суд взыщет
        не ту сумму и не тому адресату.
        """
        from app.agents.evidence_pack import EvidenceItem, EvidencePack
        from app.drafting.requirements import extract_fee_and_costs

        pack = EvidencePack(
            items=[
                EvidenceItem(
                    category="claims",
                    text=CLAIM,
                    source_document="01_claim.txt",
                    source_type="иск",
                    order=1,
                )
            ]
        )
        fee, costs = extract_fee_and_costs(pack)
        assert fee is None
        assert costs is None
