"""Тест: встречный иск не путает стороны.

Встречный иск в решениях встречается редко (5 находок на 1 425
резолюций), но ошибка в нём не косметическая: при обратном
направлении платежа резолюция предписывает взыскать с истца вместо
ответчика, и такой проект решения влечёт реальные убытки стороне.

Поэтому проверяется в первую очередь направление платежа, а уже
всё остальное.
"""

from __future__ import annotations

import pytest

from app.drafting.operative import (
    CounterClaim,
    MoneyClaim,
    Outcome,
    Parties,
    build_operative,
)


@pytest.fixture
def named() -> Parties:
    return Parties(
        plaintiff="ООО «Поставщик»",
        defendant="Фирма «Вымышленная Строй»",
    )


class TestCounterClaimDirection:
    def test_payer_is_plaintiff(
        self, named: Parties
    ) -> None:
        """Главное: взыскивается с истца в пользу ответчика."""
        part = build_operative(
            [],
            counter_claims=[
                CounterClaim(amount=45_000.0, basis="ремонт", source="01.txt")
            ],
            fee_stakes=False,
            total_line=False,
            parties=named,
        )
        text = part.render()
        assert "с ООО «Поставщик» в пользу Фирма «Вымышленная Строй»" in text
        assert "45 000 руб. 00 коп." in text

    def test_not_charged_to_defendant(
        self, named: Parties
    ) -> None:
        """Ответчик по встречному требованию не платит."""
        part = build_operative(
            [],
            counter_claims=[
                CounterClaim(amount=45_000.0, basis="ремонт", source="01.txt")
            ],
            fee_stakes=False,
            total_line=False,
            parties=named,
        )
        counter_line = [
            line
            for line in part.render().splitlines()
            if "встречн" in line.lower()
        ]
        assert counter_line, "пункт по встречному требованию не выведен"
        assert "с Фирма" not in counter_line[0]


class TestCounterClaimOutcome:
    def test_denied_formulation(self, named: Parties) -> None:
        """Отказ пишут так, как пишут в решениях."""
        part = build_operative(
            [],
            counter_claims=[
                CounterClaim(
                    amount=None,
                    basis="ремонт",
                    source="01.txt",
                    outcome=Outcome.DENIED,
                )
            ],
            fee_stakes=False,
            total_line=False,
            parties=named,
        )
        text = part.render()
        assert "В удовлетворении встречных исковых требований" in text
        assert "отказать" in text

    def test_unknown_sum_is_marked(self, named: Parties) -> None:
        """Нет суммы — видна пометка, а не предписание взыскать ноль."""
        part = build_operative(
            [],
            counter_claims=[
                CounterClaim(amount=None, basis="ремонт", source="01.txt")
            ],
            fee_stakes=False,
            total_line=False,
            parties=named,
        )
        text = part.render()
        assert "ТРЕБУЕТ ПРОВЕРКИ СПЕЦИАЛИСТОМ" in text
        assert "0 руб" not in text


class TestCounterClaimTotals:
    def test_included_in_total_when_granted(
        self, named: Parties
    ) -> None:
        """Удовлетворённое встречное требование входит в итог."""
        part = build_operative(
            [
                MoneyClaim(
                    amount=100_000.0,
                    basis="долг",
                    source="01.txt",
                )
            ],
            counter_claims=[
                CounterClaim(amount=45_000.0, basis="ремонт", source="01.txt")
            ],
            fee_stakes=False,
            total_line=True,
            parties=named,
        )
        text = part.render()
        assert "145 000" in text

    def test_excluded_from_total_when_denied(
        self, named: Parties
    ) -> None:
        """Отказанное требование в итог не попадает."""
        part = build_operative(
            [
                MoneyClaim(
                    amount=100_000.0,
                    basis="долг",
                    source="01.txt",
                )
            ],
            counter_claims=[
                CounterClaim(
                    amount=45_000.0,
                    basis="ремонт",
                    source="01.txt",
                    outcome=Outcome.DENIED,
                )
            ],
            fee_stakes=False,
            total_line=True,
            parties=named,
        )
        text = part.render()
        assert "145 000" not in text
        assert "100 000" in text

    def test_comes_after_main_claims(self, named: Parties) -> None:
        """Порядок: сначала иск истца, потом встречное требование."""
        part = build_operative(
            [
                MoneyClaim(
                    amount=100_000.0,
                    basis="долг",
                    source="01.txt",
                )
            ],
            counter_claims=[
                CounterClaim(amount=45_000.0, basis="ремонт", source="01.txt")
            ],
            fee_stakes=False,
            total_line=False,
            parties=named,
        )
        text = part.render()
        assert text.index("100 000") < text.lower().index("встречн")


class TestCounterClaimNoEmptyOperative:
    def test_only_counter_claim_does_not_trigger_gap(
        self, named: Parties
    ) -> None:
        """Одного встречного требования достаточно для непустой части.

        Раньше при отсутствии требований истца функция возвращалась
        досрочно с пропуском, и встречный иск в резолюцию не попадал
        вовсе — а суд именно его и разрешал.
        """
        part = build_operative(
            [],
            counter_claims=[
                CounterClaim(amount=45_000.0, basis="ремонт", source="01.txt")
            ],
            fee_stakes=False,
            total_line=False,
            parties=named,
        )
        assert part.items
        assert "не найдено ни одного требования" not in " ".join(part.gaps)
