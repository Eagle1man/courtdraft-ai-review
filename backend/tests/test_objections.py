"""Проверка отражения позиции ответчика (п. 6, 11.5 разбора)."""

from app.agents.draft_agent import SectionDraft
from app.agents.evidence_pack import EvidenceItem, EvidencePack
from app.verification.engine import IssueType, verify_draft


def _pack(with_objections: bool) -> EvidencePack:
    pack = EvidencePack(case_number="T-0001")
    pack.items.append(
        EvidenceItem(
            category="claims",
            text="Взыскать задолженность по договору в размере 150 000 руб. 00 коп.",
            source_document="01_claim.txt",
            source_type="CLAIM",
            order=1,
        )
    )
    if with_objections:
        pack.items.append(
            EvidenceItem(
                category="objections",
                text="Ответчик просит отказать в иске: услуги не оказаны.",
                source_document="02_response.txt",
                source_type="RESPONSE",
                order=2,
            )
        )
    return pack


def _draft(text: str):
    draft_stub = type("D", (), {})()
    draft_stub.sections = [
        SectionDraft(key="operative", name="Резолютивная часть", text=text, is_mock=False)
    ]
    return draft_stub


class TestObjections:
    def test_objections_ignored_flagged(self) -> None:
        report = verify_draft(
            _draft("Взыскать с ответчика в пользу истца 150 000 руб."),
            _pack(with_objections=True),
        )
        types = [i.type for i in report.issues]
        assert IssueType.OBJECTIONS_UNADDRESSED in types

    def test_objections_addressed_not_flagged(self) -> None:
        report = verify_draft(
            _draft(
                "Доводы ответчика о неоказании услуг отклоняются, "
                "поскольку подтверждаются материалами дела."
            ),
            _pack(with_objections=True),
        )
        flagged = [i for i in report.issues if i.type is IssueType.OBJECTIONS_UNADDRESSED]
        assert not flagged

    def test_no_objections_silent(self) -> None:
        report = verify_draft(
            _draft("Взыскать с ответчика в пользу истца 150 000 руб."),
            _pack(with_objections=False),
        )
        flagged = [i for i in report.issues if i.type is IssueType.OBJECTIONS_UNADDRESSED]
        assert not flagged
