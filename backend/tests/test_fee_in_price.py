"""Госпошлина не входит в цену иска (п. 7 разбора, ч. 1 ст. 91 ГПК РФ)."""

from app.agents.draft_agent import SectionDraft
from app.agents.evidence_pack import EvidenceItem, EvidencePack
from app.verification.engine import IssueType, verify_draft


def _pack(claim_text: str | None) -> EvidencePack:
    pack = EvidencePack(case_number="T-0001")
    if claim_text:
        pack.items.append(
            EvidenceItem(
                category="claims",
                text=claim_text,
                source_document="01_claim.txt",
                source_type="CLAIM",
                order=1,
            )
        )
    return pack


def _draft(text: str):
    draft_stub = type("D", (), {})()
    draft_stub.sections = [
        SectionDraft(key="operative", name="Резолютивная часть", text=text, is_mock=False)
    ]
    return draft_stub


class TestFeeInClaimPrice:
    def test_draft_phrase_flagged(self) -> None:
        report = verify_draft(
            _draft("Цена иска составляет 150 000 руб., включая госпошлину."),
            _pack(None),
        )
        flagged = [i for i in report.issues if i.type is IssueType.FEE_IN_CLAIM_PRICE]
        assert flagged
        assert "ст. 91" in flagged[0].reason

    def test_claim_phrase_flagged(self) -> None:
        # Ошибка в самом иске: цена иска с пошлиной попадает в расчёт
        # по ст. 333.19 НК РФ, и судья должен увидеть расхождение.
        report = verify_draft(
            _draft("Взыскать с ответчика в пользу истца 155 500 руб."),
            _pack("Цена иска 155 500 руб., в том числе государственная пошлина."),
        )
        flagged = [i for i in report.issues if i.type is IssueType.FEE_IN_CLAIM_PRICE]
        assert flagged

    def test_clean_price_not_flagged(self) -> None:
        report = verify_draft(
            _draft("Взыскать 150 000 руб. Госпошлину взыскать с ответчика."),
            _pack("Взыскать задолженность 150 000 руб. Пошлина уплачена."),
        )
        flagged = [i for i in report.issues if i.type is IssueType.FEE_IN_CLAIM_PRICE]
        assert not flagged

    def test_with_accounting_uses_flagged(self) -> None:
        report = verify_draft(
            _draft("С учётом пошлины цена иска 150 000 руб."),
            _pack(None),
        )
        flagged = [i for i in report.issues if i.type is IssueType.FEE_IN_CLAIM_PRICE]
        assert flagged
