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
