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
        assert any("разные суммы" in item for item in unrecognised)
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


class TestEqualSumsStayEqual:
    """Одинаковые суммы у разных оснований — это два требования.

    Регрессия после правила «сумма принадлежит одному основанию»:
    «взыскать убытки 5 000 рублей и неустойку 5 000 рублей» — два
    требования, и второе потеряло свою сумму.
    """

    def test_two_bases_with_same_sum_keep_it(self) -> None:
        money, _others, _unrecognised = _extract(
            "Взыскать с ответчика убытки 5000 рублей и неустойку 5000 рублей."
        )
        amounts = {claim.basis: claim.amount for claim in money}
        assert amounts.get("убытки") == 5000
        assert amounts.get("неустойка и санкции") == 5000
        total = sum(claim.amount for claim in money if claim.amount)
        assert total == 10000

    def test_sums_differing_by_kopecks_are_not_merged(self) -> None:
        money, _others, _unrecognised = _extract(
            "Взыскать с ответчика неустойку 2202 рубля 90 копеек "
            "и убытки 2202 рубля 00 копеек."
        )
        claims = {claim.basis: (claim.amount, claim.kopecks) for claim in money}
        assert claims.get("неустойка и санкции") == (2202, 90)
        assert claims.get("убытки") == (2202, 0)


class TestCourtDeterminationIsNotAClaim:
    """Сумма, названная судом, — не требование истца.

    В real-05 моральный вред 1 000 руб. взят из мотивировки:
    «суд считает необходимым взыскать …». Требование истца — 10 000
    руб. (протокол). В проект должен попасть 10 000.
    """

    def test_court_wording_before_verb_is_skipped(self) -> None:
        money, _others, _unrecognised = _extract(
            "Взыскать с ответчика убытки 1000 рублей. Суд считает "
            "необходимым взыскать компенсацию морального вреда 7777 рублей."
        )
        amounts = {claim.basis: claim.amount for claim in money}
        assert amounts.get("убытки") == 1000
        assert "компенсация морального вреда" not in amounts

    def test_court_formula_neobhodimo_vzyskat(self) -> None:
        money, _others, _unrecognised = _extract(
            "С ответчика в пользу истца необходимо взыскать компенсацию "
            "морального вреда в размере 2000 рублей, в остальной части "
            "в удовлетворении иска отказать."
        )
        assert money == []


class TestConflictNoteDetails:
    def test_note_keeps_kopecks(self) -> None:
        money, _others, unrecognised = _extract(
            "Взыскать с ответчика неустойку 2202 рубля 90 копеек "
            "и неустойку 10564 рубля 40 копеек."
        )
        notes = [item for item in unrecognised if "разные суммы" in item]
        assert notes, unrecognised
        assert "2 202,90" in notes[0]
        assert "10 564,40" in notes[0]

    def test_note_not_duplicated(self) -> None:
        pack = EvidencePack(case_number="T-REVIEW")
        for order in (1, 2):
            pack.items.append(
                EvidenceItem(
                    category="claims",
                    text=(
                        "Взыскать с ответчика убытки в размере 5000 рублей "
                        "и убытки в размере 3000 рублей."
                    ),
                    source_document="01_claim.txt",
                    source_type="CLAIM",
                    order=order,
                )
            )
        _money, _others, unrecognised = extract_requirements(pack)
        notes = [item for item in unrecognised if "разные суммы" in item]
        assert len(notes) == 1, unrecognised

    def test_note_across_documents_shows_both_sources(self) -> None:
        # Расхождение между документами истца (уточнённое требование)
        # видно, и в заметке стоят оба источника.
        pack = EvidencePack(case_number="T-REVIEW")
        pack.items.append(
            EvidenceItem(
                category="claims",
                text="Истец просит взыскать задолженность 11107 руб. 84 коп.",
                source_document="01_claim.txt",
                source_type="CLAIM",
                order=1,
            )
        )
        pack.items.append(
            EvidenceItem(
                category="claims",
                text="Истец просил взыскать задолженность 7919 руб. 17 коп.",
                source_document="05_protocol.txt",
                source_type="CLAIM",
                order=2,
            )
        )
        _money, _others, unrecognised = extract_requirements(pack)
        notes = [item for item in unrecognised if "разные суммы" in item]
        assert notes, unrecognised
        assert "01_claim.txt" in notes[0]
        assert "05_protocol.txt" in notes[0]
        # Формулировка осторожная: по основанию «задолженность» две
        # суммы могут быть разными требованиями, а не уточнением.
        assert "уточнение или разные требования" in notes[0]


class TestCostsAmountBelongsToMarker:
    """Сумма иных расходов — та, что стоит после признака расходов.

    В протоколе real-04 в одной фразе перечислены и неустойка
    (10 564,40), и затраты на проведение экспертизы (3 000). Первой
    стоит неустойка, и «иные расходы» без привязки к признаку
    показывали 10 564.
    """

    def test_costs_taken_after_marker(self) -> None:
        from app.drafting.requirements import extract_fee_and_costs

        pack = EvidencePack(case_number="T-REVIEW")
        pack.items.append(
            EvidenceItem(
                category="claims",
                text=(
                    "Просит взыскать неустойку 10564 рубля 40 копеек, "
                    "затраты на проведение экспертизы в сумме 3000 рублей."
                ),
                source_document="05_protocol.txt",
                source_type="CLAIM",
                order=1,
            )
        )
        _fee, costs = extract_fee_and_costs(pack)
        assert costs == 3000


class TestClaimOfPlaintiffSurvivesCourtWording:
    """Требование истца не должно теряться из-за слов суда.

    Отсев определений суда не должен съедать требование: «истец
    считает необходимым взыскать …» — это требование истца, а
    «суд постановил взыскать …» — определение суда, и слова суда из
    соседнего предложения не делают требованием истца следующее окно.
    """

    def test_plaintiff_saying_necessary_is_kept(self) -> None:
        money, _others, _unrecognised = _extract(
            "Истец считает необходимым взыскать с ответчика задолженность "
            "в размере 5000 рублей."
        )
        amounts = {claim.basis: claim.amount for claim in money}
        assert amounts.get("задолженность по договору") == 5000

    def test_plaintiff_thinking_necessary_is_kept(self) -> None:
        money, _others, _unrecognised = _extract(
            "Истец считает, что необходимо взыскать с ответчика "
            "задолженность в размере 5000 рублей."
        )
        amounts = {claim.basis: claim.amount for claim in money}
        assert amounts.get("задолженность по договору") == 5000

    def test_court_wording_in_neighbouring_sentence_not_sticky(self) -> None:
        money, _others, _unrecognised = _extract(
            "Суд постановил взыскать с ответчика в пользу истца 1000 рублей. "
            "Истец просил взыскать с ответчика задолженность в размере "
            "5000 рублей."
        )
        amounts = {claim.basis: claim.amount for claim in money}
        assert amounts.get("задолженность по договору") == 5000
        assert "компенсация морального вреда" not in amounts

    def test_court_reasoning_is_skipped(self) -> None:
        money, _others, _unrecognised = _extract(
            "При определении размера компенсации морального вреда суд "
            "исходит из принципа разумности и справедливости, а также с "
            "учетом нравственных страданий считает необходимым взыскать "
            "с ответчика в пользу истца в счет компенсации морального "
            "вреда 7777 рублей."
        )
        assert money == []


class TestTotalCarriesKopecks:
    """Итог резолюции переносит копейки в рубли.

    20 921,53 + 10 460,76 = 41 382,29, а не 41 381,29: без переноса
    итог расходился с суммой перечисленных пунктов на один рубль.
    """

    def test_total_with_kopecks_carried(self) -> None:
        from app.drafting.operative import _sum_amounts

        rubles, kopecks = _sum_amounts([(20921, 53), (10460, 76), (10000, 0)])
        assert (rubles, kopecks) == (41382, 29)


class TestCostsSynonyms:
    def test_expenses_for_expertise_form(self) -> None:
        from app.drafting.requirements import extract_fee_and_costs

        pack = EvidencePack(case_number="T-REVIEW")
        pack.items.append(
            EvidenceItem(
                category="claims",
                text=(
                    "Просит взыскать расходы на проведение экспертизы "
                    "в сумме 3000 рублей."
                ),
                source_document="05_protocol.txt",
                source_type="CLAIM",
                order=1,
            )
        )
        _fee, costs = extract_fee_and_costs(pack)
        assert costs == 3000


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
