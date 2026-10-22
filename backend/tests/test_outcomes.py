"""Тест: исход требования отражается из материалов дела, а не по умолчанию.

Дефект (реальное дело real-06): суд взыскал моральный вред 2 000 руб.
из заявленных 7 000 руб., неустойку и стоимость телефона — полностью,
в остальной части иска отказал. Проект писал про каждое требование
«удовлетворить в полном объёме» — система выдавала отказ суда за
полное удовлетворение.

Правила (resolve_outcomes), проверяемые здесь:
1. Установительная часть подтверждает сумму требования — исход
   удовлетворён.
2. Установительная часть называет меньшую сумму — частичное
   удовлетворение с суммой, установленной судом.
3. Материалы прямо говорят о частичном удовлетворении, а суммы по
   основанию нет — исход неизвестен: требование помечается частичным
   без суммы (в резолюции появляется пробел для судьи).
4. Установительной части нет (дело не решено) — исход не меняется.

Отдельный тест: файл court_decision_reference.txt — ключ к делу, и
чтение исхода из него превратило бы проверку в самопроверку.
"""

from __future__ import annotations

from app.agents.evidence_pack import EvidenceItem, EvidencePack
from app.drafting.operative import Outcome
from app.drafting.requirements import extract_requirements

CLAIM = (
    "Прошу взыскать с ответчика в пользу истца: стоимость сотового "
    "телефона 6 890 руб., неустойку 6 890 руб., компенсацию морального "
    "вреда 7 000 руб., убытки 3 000 руб., расходы на оплату услуг "
    "представителя 9 000 руб."
)

# Установительная часть — те же фразы, что в реальном деле real-06,
# включая заголовок отдельной строкой: без него документ не считается
# установительной частью — иначе протокол заседания с цитатой иска
# подтверждал бы исход требования самим иском.
FINDINGS = (
    "УСТАНОВИЛ:\n"
    "Суд, заслушав объяснения истца, проверив материалы дела, "
    "считает иск обоснованным, и подлежащим удовлетворению частично.\n"
    "Согласно представленных суду документов установлено, что "
    "24 ноября 2011 года истец приобрел сотовый телефон стоимостью "
    "6890 рублей.\n"
    "Требование о возмещении неустойки в размере 6890 рублей не "
    "превышает стоимости товара.\n"
    "Учитывая, степень перенесенных истцом физических и нравственных "
    "страданий, суд взыскивает моральный вред в сумме 2000 рублей.\n"
    "В соответствии со ст. 15 ГК РФ, лицо, право которого нарушено, "
    "может требовать полного возмещения причиненных ему убытков.\n"
)

# Ключ к делу: операционная часть настоящего решения. Читаться не должна.
REFERENCE = (
    "РЕШИЛ: Взыскать стоимость сотового телефона 6890 руб., неустойку "
    "6890 руб., в возмещение морального вреда 2000 руб., убытки "
    "3000 руб., штраф 3445 руб. В остальной части иска отказать."
)


def _pack(*, findings: bool = False, reference: bool = False) -> EvidencePack:
    items = [
        EvidenceItem(
            category="claims",
            text=CLAIM,
            source_document="01_claim.txt",
            source_type="иск",
            amounts=["6890", "7000", "3000", "9000"],
            order=1,
        )
    ]
    if findings:
        items.append(
            EvidenceItem(
                category="protocol_findings",
                text=FINDINGS,
                source_document="06_court_findings.txt",
                source_type="мотивировочная часть",
                amounts=["6890", "2000"],
                order=1,
            )
        )
    if reference:
        items.append(
            EvidenceItem(
                category="evidence",
                text=REFERENCE,
                source_document="court_decision_reference.txt",
                source_type="решение суда (ключ)",
                amounts=["6890", "2000", "3445"],
                order=2,
            )
        )
    return EvidencePack(items=items, amounts=["6890", "7000", "3000", "9000"])


def _money_by_basis(pack: EvidencePack) -> dict[str, object]:
    money, _others, _unrecognised = extract_requirements(pack)
    return {claim.basis: claim for claim in money}


class TestOutcomeFromFindings:
    def test_same_amount_is_satisfied(self) -> None:
        """Сумма суда совпала с требованием — удовлетворено."""
        claims = _money_by_basis(_pack(findings=True))
        claim = claims["возмещение стоимости имущества"]
        assert claim.outcome is Outcome.SATISFIED
        assert claim.amount == 6890

    def test_penalty_confirmed_by_findings(self) -> None:
        claims = _money_by_basis(_pack(findings=True))
        assert claims["неустойка и санкции"].outcome is Outcome.SATISFIED

    def test_smaller_amount_is_partial(self) -> None:
        """Моральный вред: 2 000 из 7 000 — частичное удовлетворение."""
        claims = _money_by_basis(_pack(findings=True))
        claim = claims["компенсация морального вреда"]
        assert claim.outcome is Outcome.PARTIAL
        assert claim.granted_amount == 2000
        assert claim.granted_kopecks == 0

    def test_absent_in_granted_list_is_unknown(self) -> None:
        """Убытки и представитель в установительной части не названы.

        Материалы говорят о частичном удовлетворении, но суммы по этим
        основаниям суд не называл. Исход остаётся неизвестным — это
        частичное удовлетворение без суммы, то есть пробел для судьи,
        а не «в полном объёме».
        """
        claims = _money_by_basis(_pack(findings=True))
        for basis in ("убытки", "расходы на представителя"):
            claim = claims[basis]
            assert claim.outcome is Outcome.PARTIAL, basis
            assert claim.granted_amount is None, basis

    def test_partial_without_findings_keeps_claim(self) -> None:
        """Установительной части нет — дело не решено, исход не трогаем."""
        claims = _money_by_basis(_pack())
        for basis, claim in claims.items():
            assert claim.outcome is Outcome.SATISFIED, basis

    def test_reference_document_is_not_read(self) -> None:
        """Ключ к делу не источник исхода.

        В файле reference есть и «В остальной части иска отказать»,
        и суммы суда. Если бы их прочитали, убытки получили бы исход
        по ключу, и проверка подтверждала бы себя саму.
        """
        claims = _money_by_basis(_pack(reference=True))
        assert claims["убытки"].outcome is Outcome.SATISFIED
        assert claims["расходы на представителя"].outcome is Outcome.SATISFIED
        # Моральный вред в ключе — 2 000, но ключ источником не является.
        assert claims["компенсация морального вреда"].outcome is Outcome.SATISFIED

    def test_findings_and_reference_together(self) -> None:
        """Наличие ключа не мешает чтению настоящей установительной."""
        claims = _money_by_basis(_pack(findings=True, reference=True))
        claim = claims["компенсация морального вреда"]
        assert claim.outcome is Outcome.PARTIAL
        assert claim.granted_amount == 2000

    def test_protocol_without_heading_is_not_findings(self) -> None:
        """Протокол заседания не считается установительной частью.

        Дефект, найденный на живом прогоне real-06: в протоколе
        цитируется иск («просит взыскать ... 9 000 руб.»), и цитата
        подтверждала исход требования самим иском — суд «удовлетворял»
        то, что истец просил, хотя решение ещё не принято. Требование
        заголовка («УСТАНОВИЛ:») отделяет настоящую установительную
        часть от протокола.
        """
        protocol_only = EvidencePack(
            items=[
                EvidenceItem(
                    category="claims",
                    text=CLAIM,
                    source_document="01_claim.txt",
                    source_type="иск",
                    amounts=["7000"],
                    order=1,
                ),
                EvidenceItem(
                    category="objections",
                    text=(
                        "Представитель истца в заседании просил взыскать "
                        "7 000 руб. компенсации морального вреда."
                    ),
                    source_document="05_protocol.txt",
                    source_type="протокол",
                    amounts=["7000"],
                    order=2,
                ),
            ],
            amounts=["7000"],
            documents={
                "01_claim.txt": CLAIM,
                "05_protocol.txt": (
                    "ПРОТОКОЛ СУДЕБНОГО ЗАСЕДАНИЯ\n"
                    "Представитель истца пояснил, что просит взыскать "
                    "7 000 руб. компенсации морального вреда."
                ),
            },
        )
        claims = _money_by_basis(protocol_only)
        # Исход из протокола не читается: требование остаётся тем,
        # что просил истец, пока нет настоящей установительной части.
        for basis, claim in claims.items():
            assert claim.outcome is Outcome.SATISFIED, basis


class TestRefusalAndAnomalies:
    """Находки независимого ревью (снимок 49 коммитов).

    1. Отказная формулировка с основанием и суммой не подтверждает
       исход — она его отрицает. Раньше «Требование о взыскании
       неустойки в размере 6 890 руб. удовлетворению не подлежит»
       содержала и основание, и сумму, и считалась подтверждением:
       проект писал «в полном объёме» там, где суд отказал.
    2. Сумма суда больше заявленной — не «в полном объёме», а видимое
       расхождение: раньше оставался дефолт SATISFIED без пометки.
    """

    REFUSAL_FINDINGS = (
        "УСТАНОВИЛ:\n"
        "Суд, заслушав объяснения истца, проверив материалы дела, "
        "считает иск подлежащим удовлетворению частично.\n"
        "Требование истца о взыскании неустойки в размере 6890 рублей "
        "удовлетворению не подлежит.\n"
        "Удовлетворению не подлежит и требование о компенсации "
        "морального вреда в размере 7000 рублей.\n"
    )

    def _refusal_pack(self) -> EvidencePack:
        return EvidencePack(
            items=[
                EvidenceItem(
                    category="claims",
                    text=CLAIM,
                    source_document="01_claim.txt",
                    source_type="иск",
                    amounts=["6890", "7000"],
                    order=1,
                ),
                EvidenceItem(
                    category="protocol_findings",
                    text=self.REFUSAL_FINDINGS,
                    source_document="06_court_findings.txt",
                    source_type="мотивировочная часть",
                    amounts=["6890", "7000"],
                    order=1,
                ),
            ],
            amounts=["6890", "7000"],
        )

    def test_refusal_is_denied(self) -> None:
        """«Удовлетворению не подлежит» — отказ, а не подтверждение."""
        claims = _money_by_basis(self._refusal_pack())
        claim = claims["неустойка и санкции"]
        assert claim.outcome is Outcome.DENIED
        assert claim.granted_amount is None

    def test_refusal_inverted_word_order(self) -> None:
        """«Удовлетворению не подлежит и требование о ...» — тоже отказ."""
        claims = _money_by_basis(self._refusal_pack())
        assert (
            claims["компенсация морального вреда"].outcome is Outcome.DENIED
        )

    def test_unmatched_claims_stay_partial_without_sum(self) -> None:
        """Требования без суммы в установительной части — частичные.

        Частичный сигнал общий («удовлетворению частично»), суммы по
        основанию нет — исход неизвестен, но «в полном объёме» не
        печатается.
        """
        claims = _money_by_basis(self._refusal_pack())
        assert claims["убытки"].outcome is Outcome.PARTIAL
        assert claims["убытки"].granted_amount is None

    def test_refusal_no_grounds_is_denied(self) -> None:
        """«Оснований для взыскания … не имеется» — отказ.

        Форма из real-01: суд отказал по ремонту 7 919,17 именно так.
        """
        pack = EvidencePack(
            items=[
                EvidenceItem(
                    category="claims",
                    text="Прошу взыскать задолженность за ремонт и "
                    "содержание жилья в размере 7919 руб. 17 копеек.",
                    source_document="01_claim.txt",
                    source_type="иск",
                    amounts=["7919"],
                    order=1,
                ),
                EvidenceItem(
                    category="protocol_findings",
                    text=(
                        "УСТАНОВИЛ:\n"
                        "Суд, заслушав объяснения истца, проверив "
                        "материалы дела, установил.\n"
                        "Оснований для взыскания с ответчика "
                        "задолженности за ремонт и содержание жилья "
                        "в размере 7919 рублей 17 копеек не имеется."
                    ),
                    source_document="06_court_findings.txt",
                    source_type="мотивировочная часть",
                    amounts=["7919"],
                    order=1,
                ),
            ],
            amounts=["7919"],
        )
        claim = _money_by_basis(pack)["задолженность за ремонт и содержание жилья"]
        assert claim.outcome is Outcome.DENIED

    def test_kopecks_only_sum_is_read(self) -> None:
        """Сумма-копейки: real-01 суд взыскал ЖКУ «72 копейки».

        Без этой формы требование оставалось «в полном объёме» на
        11 107,84 руб. — ложь в ту же сторону, что и отказ.
        """
        pack = EvidencePack(
            items=[
                EvidenceItem(
                    category="claims",
                    text="Прошу взыскать задолженность за жилищно-"
                    "коммунальные услуги в размере 11107 руб. 84 копейки.",
                    source_document="01_claim.txt",
                    source_type="иск",
                    amounts=["11107"],
                    order=1,
                ),
                EvidenceItem(
                    category="protocol_findings",
                    text=(
                        "УСТАНОВИЛ:\n"
                        "Суд, заслушав объяснения истца, проверив "
                        "материалы дела, установил.\n"
                        "Взысканию с ответчика подлежит задолженность "
                        "по оплате жилья и коммунальных услуг в размере "
                        "72 копейки."
                    ),
                    source_document="06_court_findings.txt",
                    source_type="мотивировочная часть",
                    amounts=["72"],
                    order=1,
                ),
            ],
            amounts=["11107"],
        )
        claim = _money_by_basis(pack)["задолженность за жилищно-коммунальные услуги"]
        assert claim.outcome is Outcome.PARTIAL
        assert claim.granted_amount == 0
        assert claim.granted_kopecks == 72

    def test_court_sum_bigger_than_claim_is_visible(self) -> None:
        """Сумма суда больше заявленной — расхождение видно судье.

        Дефект ревью: комментарий обещал «требование остаётся без
        исхода», а код оставлял дефолт SATISFIED — резолютивная писала
        «в полном объёме» там, где суд взыскал не то, что просили.
        """
        pack = EvidencePack(
            items=[
                EvidenceItem(
                    category="claims",
                    text="Прошу взыскать убытки в размере 3000 руб.",
                    source_document="01_claim.txt",
                    source_type="иск",
                    amounts=["3000"],
                    order=1,
                ),
                EvidenceItem(
                    category="protocol_findings",
                    text=(
                        "УСТАНОВИЛ:\n"
                        "Суд, заслушав объяснения истца, проверив "
                        "материалы дела, взыскивает с ответчика убытки "
                        "в размере 5000 рублей."
                    ),
                    source_document="06_court_findings.txt",
                    source_type="мотивировочная часть",
                    amounts=["5000"],
                    order=1,
                ),
            ],
            amounts=["3000"],
        )
        claim = _money_by_basis(pack)["убытки"]
        assert claim.outcome is Outcome.PARTIAL
        assert claim.granted_amount == 5000
        assert "сумма суда больше заявленной" in (claim.grounds or "")
