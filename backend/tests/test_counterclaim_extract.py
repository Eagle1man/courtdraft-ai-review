"""Тест: встречный иск извлекается из материалов дела.

Проверяется не только сборка резолюции (test_counterclaim.py), но и
добыча самого требования: если признак «встречн» не распознан, резолюция
останется без пункта, как будто ответчик ничего не заявлял.

Текст взят по форме решений, найденной в разборе 1 425 резолюций:
    В удовлетворении встречных исковых требований Баранова <ФИО1>
    к ЗАО «ПТС-Сервис» о взыскании расходов на ремонт общего имущества
    многоквартирного дома отказать
"""

from __future__ import annotations

import pytest

from app.agents.evidence_pack import EvidenceItem, EvidencePack
from app.drafting.operative import Outcome
from app.drafting.requirements import extract_counter_claims


def _pack(text: str, source: str = "02_defence.txt") -> EvidencePack:
    return EvidencePack(
        items=[
            EvidenceItem(
                text=text,
                category="claims",
                source_document=source,
                source_type="возражение",
                order=1,
            )
        ]
    )


class TestExtractCounterClaims:
    def test_found_and_amount_parsed(self) -> None:
        pack = _pack(
            "Ответчик заявил встречный иск: взыскать с истца "
            "ООО «Поставщик» в свою пользу расходы на ремонт "
            "общего имущества многоквартирного дома в размере "
            "45 000 руб. 00 коп."
        )
        found = extract_counter_claims(pack)
        assert len(found) == 1, "встречный иск не распознан"
        claim = found[0]
        assert claim.amount == 45_000.0
        assert claim.kopecks == 0
        assert claim.source == "02_defence.txt"
        assert claim.outcome is Outcome.SATISFIED

    def test_denial_detected(self) -> None:
        pack = _pack(
            "В удовлетворении встречных исковых требований ответчика "
            "о взыскании с истца расходов на ремонт в размере "
            "45 000 руб. отказать."
        )
        found = extract_counter_claims(pack)
        assert len(found) == 1
        assert found[0].outcome is Outcome.DENIED

    def test_plain_claim_is_not_counter(self) -> None:
        """Обычное требование истца не должно попасть во встречные."""
        pack = _pack(
            "Прошу взыскать с ответчика Фирма «Вымышленная Строй» "
            "в пользу истца задолженность по договору в размере "
            "150 000 руб."
        )
        assert extract_counter_claims(pack) == []

    def test_missing_amount_stays_none(self) -> None:
        """Нет суммы — остаётся None, а не ноль."""
        pack = _pack(
            "Ответчик предъявил встречный иск о взыскании с истца "
            "расходов на ремонт общего имущества."
        )
        found = extract_counter_claims(pack)
        assert len(found) == 1
        assert found[0].amount is None

    @pytest.mark.parametrize(
        "text",
        [
            "Ответчик предъявил встречное исковое заявление.",
            "Встречный иск ответчика не заявлен.",
        ],
    )
    def test_no_counter_means_no_claims(self, text: str) -> None:
        pack = _pack(text)
        assert extract_counter_claims(pack) == []
