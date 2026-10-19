"""Склонение наименований сторон в резолютивной части.

В постановлении стороны стоят в родительном падеже: «взыскать с
Образцова Петра Петровича в пользу Образцова». Без склонения проект
содержит «с Образцов Пётр Петрович» — ошибка прямо в формуле.

Склонение устроено консервативно: юридическое лицо не склоняется
(«с ООО «Фирма Строй»» верно), человек склоняется только когда
известны все три окончания, иначе название остаётся как есть, а в
пропуски попадает требование проверить падеж.
"""

from __future__ import annotations

from app.drafting.inflection import can_decline, is_person, to_genitive
from app.drafting.operative import Parties, build_operative

PERSON = "Образцов Пётр Петрович"
ORGANISATION = 'ООО «Фирма Вымышленная Строй»'


class TestPersonDeclension:
    """Человеческое ФИО склоняется."""

    def test_full_name(self) -> None:
        assert to_genitive(PERSON) == "Образцова Пётра Петровича"

    def test_surname_in(self) -> None:
        assert to_genitive("Путин Владимир Владимирович") == "Путина Владимира Владимировича"

    def test_name_ending_soft_sign(self) -> None:
        assert to_genitive("Тарасов Игорь Игоревич") == "Тарасова Игоря Игоревича"

    def test_name_ending_y(self) -> None:
        assert to_genitive("Сидоров Андрей Андреевич") == "Сидорова Андрея Андреевича"

    def test_is_person(self) -> None:
        assert is_person(PERSON)
        assert not is_person(ORGANISATION)

    def test_can_decline_person(self) -> None:
        assert can_decline(PERSON)


class TestOrganisationNotDeclined:
    """Юридическое лицо склонению не подлежит."""

    def test_kept_as_is(self) -> None:
        assert to_genitive(ORGANISATION) == ORGANISATION

    def test_looks_like_organisation(self) -> None:
        assert not is_person(ORGANISATION)

    def test_nothing_to_decline(self) -> None:
        assert can_decline(ORGANISATION)


class TestUnknownDeclension:
    """Неизвестное окончание — не угадываем."""

    def test_feminine_name_left_alone(self) -> None:
        """«Никита» — форма именительного и родительного не совпадает.

        Гадать здесь нельзя: неверный падеж хуже отсутствия склонения,
        потому что выглядит как правка суда.
        """
        name = "Образцов Никита Никитич"
        assert to_genitive(name) == name

    def test_flagged_as_uncertain(self) -> None:
        parties = Parties(plaintiff="Образцов Никита Никитич")
        assert parties.uncertain_cases == ["Образцов Никита Никитич"]

    def test_organisation_is_not_uncertain(self) -> None:
        parties = Parties(defendant=ORGANISATION)
        assert parties.uncertain_cases == []


class TestOperativeUsesGenitive:
    """Резолютивная часть склоняет стороны."""

    def test_person_in_operative(self) -> None:
        from app.drafting.operative import MoneyClaim

        claim = MoneyClaim(
            amount=150000, basis="задолженность по договору", source="договор"
        )
        result = build_operative(
            [claim], parties=Parties(plaintiff=PERSON, defendant=ORGANISATION)
        )
        text = "\n".join(result.items)
        assert "Образцова Пётра Петровича" in text
        assert ORGANISATION in text

    def test_gap_reported_when_unsure(self) -> None:
        from app.drafting.operative import MoneyClaim

        claim = MoneyClaim(
            amount=150000, basis="задолженность по договору", source="договор"
        )
        result = build_operative(
            [claim], parties=Parties(plaintiff="Образцов Никита Никитич")
        )
        assert any("родительн" in gap for gap in result.gaps)
