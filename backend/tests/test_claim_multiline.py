"""Тест склейки требования, разбитого на строки.

Дефект найден на живом прогоне демо. В исковом заявлении требование
печатается так:

    1. Взыскать с Фирма «...» в пользу Образцов
       задолженность по договору поставки
       в размере 150000 руб.

Пакет хранит предложения по отдельности, поэтому в резолютивную часть
попадала только первая строка — без суммы и без основания. Пункт
получался пустым, а демо показывало «требования истца не установлены»
при заполненном пакете.

Здесь зафиксировано поведение на точной формулировке из DEMO-001.
"""

from __future__ import annotations

from app.agents.evidence_pack import EvidenceItem, EvidencePack
from app.drafting.operative import build_operative
from app.drafting.requirements import extract_requirements

# Точный текст пунктов искового заявления из DEMO-001, разбитый так,
# как его раскладывает пакет доказательств: по одному предложению.
CLAIM_LINES = [
    "Взыскать с Фирма «Вымышленная Строй» в пользу Образцов Пётр Петрович",
    "задолженность по договору поставки № Д-2026/001",
    "в размере 150000 руб.",
    "Взыскать с ответчика расходы по уплате государственной пошлины",
    "в размере 5 100 руб.",
]


def claim_pack(lines: list[str], document: str = "01_claim.txt") -> EvidencePack:
    pack = EvidencePack(case_number="DEMO-001")
    for index, text in enumerate(lines):
        pack.items.append(
            EvidenceItem(
                category="claims",
                text=text,
                source_document=document,
                source_type="CLAIM",
            )
        )
        del index
    return pack


class TestClaimSpansMultipleLines:
    def test_debt_claim_recovers_amount(self) -> None:
        """Сумма из третьей строки должна дойти до пункта решения."""
        money, _, _ = extract_requirements(claim_pack(CLAIM_LINES))
        assert money
        assert money[0].basis == "задолженность по договору"
        assert money[0].amount == 150000

    def test_fee_not_treated_as_separate_claim(self) -> None:
        """Госпошлина — это расходы, а не самостоятельное требование.

        Иначе в резолютивной части появился бы пункт о взыскании
        пошлины как части суммы, и судья увидел бы двойное взыскание.
        """
        money, _, _ = extract_requirements(claim_pack(CLAIM_LINES))
        assert len(money) == 1
        assert money[0].basis != "расходы на представителя"

    def test_fee_extracted_separately(self) -> None:
        from app.drafting.requirements import extract_fee_and_costs

        pack = claim_pack(CLAIM_LINES)
        # Госпошлина ищется по всему пакету, а не только в «claims»,
        # поэтому добавляем её в материалах отдельной строкой.
        pack.items.append(
            EvidenceItem(
                category="evidence",
                text="Госпошлина: 5 100 руб.",
                source_document="01_claim.txt",
                source_type="CLAIM",
            )
        )
        fee, _ = extract_fee_and_costs(pack)
        assert fee == 5100

    def test_operative_section_gets_real_amount(self) -> None:
        """Сквозная проверка: в проекте решения стоит настоящая сумма."""
        money, _, _ = extract_requirements(claim_pack(CLAIM_LINES))
        result = build_operative(money, fee_paid=5100, budget="области")
        text = result.render()

        assert "150 000" in text
        assert "взыскать с ответчика в пользу истца" in text
        assert result.is_complete

    def test_unrecognised_is_empty_for_real_claim(self) -> None:
        """Хорошее требование не должно попадать в «непознанные»."""
        _, _, missed = extract_requirements(claim_pack(CLAIM_LINES))
        # Пункты про госпошлину и договорные условия разбираются
        # отдельно; неразобранным остаётся только то, что не является
        # требованием истца.
        assert all("Поставщик" not in item for item in missed)


class TestFeeNotDoubleCounted:
    """Пошлина выносится отдельным пунктом, а не повторяется дважды."""

    def test_fee_requirement_not_in_unrecognised(self) -> None:
        """«расходы по уплате государственной пошлины» — не требование.

        Раньше такая фраза попадала в список непознанных, хотя пошлина
        уже вынесена пунктом со ссылкой на ст. 98 ГПК РФ. Судья видел
        её дважды.
        """
        pack = EvidencePack(case_number="DEMO-001")
        pack.items.append(
            EvidenceItem(
                category="claims",
                text="Взыскать с ответчика расходы по уплате "
                     "государственной пошлины в размере 5 100 руб.",
                source_document="01_claim.txt",
                source_type="CLAIM",
                order=1,
            )
        )
        money, others, missed = extract_requirements(pack)
        assert not money
        assert not others
        assert not missed

    def test_real_unknown_claim_still_shown(self) -> None:
        """Настоящее непонятное требование показывается судье."""
        pack = EvidencePack(case_number="DEMO-001")
        pack.items.append(
            EvidenceItem(
                category="claims",
                text="Истец требует привлечь ответчика к ответственности "
                     "за загрязнение окружающей среды.",
                source_document="01_claim.txt",
                source_type="CLAIM",
                order=1,
            )
        )
        _, _, missed = extract_requirements(pack)
        assert missed
        assert "загрязнение" in missed[0]


class TestShortSentencesSurvive:
    """Строка с суммой бывает короче порога отсечения.

    Дефект найден на прогоне демо: «в размере 150000 руб.» — это
    22 символа, а пакет отбрасывал всё короче 25. Сумма терялась на
    входе, и резолютивная часть оставалась без взыскания при полном
    пакете доказательств.
    """

    def test_amount_line_is_kept(self) -> None:
        from app.agents.evidence_pack import _sentences

        text = (
            "Взыскать с Фирма «Вымышленная Строй» в пользу Образцов\n"
            "   задолженность по договору поставки № Д-2026/001\n"
            "   в размере 150000 руб.\n"
            "Взыскать с ответчика расходы по уплате государственной пошлины\n"
            "   в размере 5 100 руб."
        )
        sentences = _sentences(text)
        assert any("150000" in s for s in sentences), (
            f"строка с суммой отброшена: {sentences}"
        )
        assert any("5 100" in s for s in sentences)

    def test_requirement_line_is_kept(self) -> None:
        """Короткая строка «Требую взыскать…» тоже не теряется."""
        from app.agents.evidence_pack import _sentences

        text = "Требую взыскать с ответчика\n  задолженность 150000 руб."
        assert any("Требую" in s for s in _sentences(text))

    def test_noise_still_dropped(self) -> None:
        """Порог не отменён: мусорные огрызки по-прежнему отбрасываются."""
        from app.agents.evidence_pack import _sentences

        text = "Суд.\nИ вот тут.\n\nА теперь длинное предложение о предмете иска."
        sentences = _sentences(text)
        assert sentences == ["А теперь длинное предложение о предмете иска."]

    def test_amount_reaches_operative_part(self) -> None:
        """Сквозная проверка: сумма доходит до проекта решения."""
        from app.agents.evidence_pack import _classify, _sentences

        text = (
            "Взыскать с Фирма «Вымышленная Строй» в пользу Образцов "
            "Пётр Петрович задолженность по договору поставки "
            "в размере 150000 руб."
        )
        pack = EvidencePack(case_number="DEMO-001")
        for index, sentence in enumerate(_sentences(text), start=1):
            pack.items.append(
                EvidenceItem(
                    category=_classify(sentence, "CLAIM"),
                    text=sentence,
                    source_document="01_claim.txt",
                    source_type="CLAIM",
                    order=index,
                )
            )
        money, _, _ = extract_requirements(pack)
        assert money and money[0].amount == 150000


class TestThroughRealClassifier:
    """Тот же случай, но через настоящую классификацию пакета.

    Дефект был найден прогоном демо, а не тестом: тесты строили пакет
    руками и клали все строки в «claims», а настоящая классификация
    относит продолжение требования к «evidence» — там есть слово «руб».
    Из-за этого склейка по одной категории брала только первую строку,
    и сумма 150 000 до резолютивной части не доходила.
    """

    def test_classifier_splits_claim_across_categories(self) -> None:
        """Префикс условия: документ разрыт между категориями."""
        from app.agents.evidence_pack import _classify

        prefix = "Взыскать с Фирма «Вымышленная Строй» в пользу Образцов"
        rest = "задолженность по договору поставки № Д-2026/001"
        assert _classify(prefix, "CLAIM") == "claims"
        assert _classify(rest, "CLAIM") == "evidence"

    def test_amount_survives_category_split(self) -> None:
        """Сумма достаётся, хотя лежит в другой категории."""
        pack = EvidencePack(case_number="DEMO-001")
        lines = [
            ("claims", "Взыскать с Фирма «Вымышленная Строй» "
                       "в пользу Образцов Пётр Петрович"),
            ("evidence", "задолженность по договору поставки № Д-2026/001"),
            ("evidence", "в размере 150000 руб."),
        ]
        for category, text in lines:
            pack.items.append(
                EvidenceItem(
                    category=category,
                    text=text,
                    source_document="01_claim.txt",
                    source_type="CLAIM",
                )
            )

        money, _, _ = extract_requirements(pack)
        assert money
        assert money[0].amount == 150000
        assert money[0].basis == "задолженность по договору"

    def test_other_document_still_excluded(self) -> None:
        """Склейка по всему пакету не переходит через границу документа."""
        pack = EvidencePack(case_number="DEMO-001")
        pack.items.append(
            EvidenceItem(
                category="claims",
                text="Взыскать с ответчика задолженность по договору",
                source_document="01_claim.txt",
                source_type="CLAIM",
            )
        )
        pack.items.append(
            EvidenceItem(
                category="evidence",
                text="в размере 999999 руб. — из другого документа",
                source_document="99_other.txt",
                source_type="CLAIM",
            )
        )
        money, _, _ = extract_requirements(pack)
        assert money[0].amount is None


class TestPackOrderMatters:
    """Пакет упорядочен по категориям, а не по документу.

    Дефект найден диагностикой scripts/inspect_pack.py на прогоне демо:
    первый элемент списка — требование о задолженности, второй — сразу
    требование о госпошлине, а продолжение первого («задолженность по
    договору поставки», «в размере 150000 руб.») лежало в конце
    списка, в группе evidence. Склейка по соседству брала чужую строку
    и теряла сумму.
    """

    def test_claim_split_across_pack_order(self) -> None:
        pack = EvidencePack(case_number="DEMO-001")
        # Порядок документа — как в настоящем исковом заявлении:
        # требование о задолженности идёт раньше требования о пошлине.
        # Категории при этом перемешаны: продолжение требования
        # относится к evidence, а не к claims.
        rows = [
            ("claims", 1, "Взыскать с Фирма «Вымышленная Строй» "
                          "в пользу Образцов Пётр Петрович"),
            ("evidence", 2, "задолженность по договору поставки "
                            "№ Д-2026/001"),
            ("evidence", 3, "в размере 150000 руб."),
            ("claims", 4, "Взыскать с ответчика расходы по уплате "
                          "государственной пошлины"),
            ("evidence", 5, "в размере 5 100 руб."),
        ]
        for category, order, text in rows:
            pack.items.append(
                EvidenceItem(
                    category=category,
                    text=text,
                    source_document="01_claim.txt",
                    source_type="CLAIM",
                    order=order,
                )
            )

        money, _, _ = extract_requirements(pack)
        debt = [m for m in money if m.basis == "задолженность по договору"]
        assert debt, f"требование о задолженности не найдено: {money}"
        assert debt[0].amount == 150000

    def test_fee_not_merged_into_debt(self) -> None:
        """Госпошлина не должна становиться частью взыскания долга."""
        pack = EvidencePack(case_number="DEMO-001")
        rows = [
            ("claims", 1, "Взыскать с Фирма «Вымышленная Строй» "
                          "в пользу Образцов Пётр Петрович"),
            ("evidence", 2, "задолженность по договору поставки"),
            ("evidence", 3, "в размере 150000 руб."),
            ("claims", 4, "Взыскать с ответчика расходы по уплате "
                          "государственной пошлины"),
            ("evidence", 5, "в размере 5 100 руб."),
        ]
        for category, order, text in rows:
            pack.items.append(
                EvidenceItem(
                    category=category,
                    text=text,
                    source_document="01_claim.txt",
                    source_type="CLAIM",
                    order=order,
                )
            )

        money, _, _ = extract_requirements(pack)
        debt = [m for m in money if m.basis == "задолженность по договору"]
        assert debt and debt[0].amount == 150000

    def test_items_without_order_still_work(self) -> None:
        """Факты, созданные вне пакета, склеиваются как раньше."""
        pack = EvidencePack(case_number="DEMO-001")
        pack.items.append(
            EvidenceItem(
                category="claims",
                text="Истец требует взыскать задолженность 150000 рублей.",
                source_document="a.txt",
                source_type="CLAIM",
            )
        )
        money, _, _ = extract_requirements(pack)
        assert money and money[0].amount == 150000


class TestDirectionOfPaymentFromRealCase:
    def test_payment_from_plaintiff_is_not_a_claim(self) -> None:
        """«Взыскать с истца расходы на представителя».

        Это возражение ответчика, а не требование истца. Если такая
        фраза станет требованием, резолютивная часть перевернёт стороны:
        именно такой дефект проверка помечала как CRITICAL.
        """
        pack = claim_pack(
            ["Взыскать с истца расходы на представителя в размере 20000 руб."],
            document="02_response.txt",
        )
        money, others, _ = extract_requirements(pack)
        assert not money
        assert not others

    def test_contract_clause_is_not_a_claim(self) -> None:
        """«Поставщик обязуется передать товар» — условие договора."""
        pack = claim_pack(
            ["Поставщик обязуется передать в собственность Покупателя товар,"],
            document="03_contract.txt",
        )
        money, others, _ = extract_requirements(pack)
        assert not money
        assert not others

    def test_other_documents_not_swallowed(self) -> None:
        """Склейка не должна переходить через границу документа."""
        pack = EvidencePack(case_number="DEMO-001")
        pack.items.append(
            EvidenceItem(
                category="claims",
                text="Взыскать с ответчика задолженность",
                source_document="01_claim.txt",
                source_type="CLAIM",
            )
        )
        pack.items.append(
            EvidenceItem(
                category="claims",
                text="в размере 150000 руб. — из другого документа",
                source_document="99_other.txt",
                source_type="CLAIM",
            )
        )
        money, _, _ = extract_requirements(pack)
        # Сумма из чужого документа подтянута быть не должна.
        assert money[0].amount is None
