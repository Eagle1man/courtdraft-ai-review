"""Заявления, меняющие исход (п. 76 разбора, ст. 199 ГК и ст. 333 ГК)."""

from app.agents.draft_agent import SectionDraft
from app.agents.evidence_pack import EvidenceItem, EvidencePack
from app.verification.engine import IssueType, verify_draft


def _pack(objection_text: str) -> EvidencePack:
    pack = EvidencePack(case_number="T-0001")
    pack.items.append(
        EvidenceItem(
            category="objections",
            text=objection_text,
            source_document="02_response.txt",
            source_type="RESPONSE",
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


class TestLimitationStatement:
    def test_limitation_in_materials_draft_silent_flagged(self) -> None:
        pack = _pack("Ответчик заявляет о пропуске срока исковой давности.")
        report = verify_draft(_draft("Взыскать 150 000 руб."), pack)
        flagged = [i for i in report.issues if i.type is IssueType.STATEMENT_LIMITATION]
        assert flagged
        assert flagged[0].severity.value == "HIGH"

    def test_limitation_addressed_not_flagged(self) -> None:
        pack = _pack("Ответчик ссылается на пропуск срока исковой давности.")
        report = verify_draft(
            _draft("Срок исковой давности не пропущен: обязательство подтверждено."),
            pack,
        )
        flagged = [i for i in report.issues if i.type is IssueType.STATEMENT_LIMITATION]
        assert not flagged

    def test_no_limitation_statement_silent(self) -> None:
        pack = _pack("Ответчик возражает против удовлетворения иска по существу.")
        report = verify_draft(_draft("Взыскать 150 000 руб."), pack)
        flagged = [i for i in report.issues if i.type is IssueType.STATEMENT_LIMITATION]
        assert not flagged


class TestPenaltyReductionStatement:
    def test_reduction_in_materials_draft_silent_flagged(self) -> None:
        pack = _pack("Ответчик просит снизить неустойку на основании ст. 333 ГК РФ.")
        report = verify_draft(_draft("Взыскать 150 000 руб."), pack)
        flagged = [
            i for i in report.issues if i.type is IssueType.STATEMENT_PENALTY_REDUCTION
        ]
        assert flagged

    def test_reduction_addressed_not_flagged(self) -> None:
        pack = _pack("Ответчик ходатайствует о снижении неустойки (ст. 333 ГК).")
        report = verify_draft(
            _draft("Оснований для снижения неустойки по ст. 333 ГК РФ не установлено."),
            pack,
        )
        flagged = [
            i for i in report.issues if i.type is IssueType.STATEMENT_PENALTY_REDUCTION
        ]
        assert not flagged

    def test_no_reduction_statement_silent(self) -> None:
        pack = _pack("Ответчик не согласен с размером долга.")
        report = verify_draft(_draft("Взыскать 150 000 руб."), pack)
        flagged = [
            i for i in report.issues if i.type is IssueType.STATEMENT_PENALTY_REDUCTION
        ]
        assert not flagged


class TestSplitMarkers:
    def test_marker_across_fragments_no_crash(self) -> None:
        # Маркер собран из разных фрагментов: «пропуск срока» в одном,
        # «исковой давности» в другом. Выбор источника не должен падать.
        pack = EvidencePack(case_number="T-0002")
        pack.items.append(
            EvidenceItem(
                category="objections",
                text="Ответчик заявляет о пропуске срока.",
                source_document="02a.txt",
                source_type="RESPONSE",
                order=1,
            )
        )
        pack.items.append(
            EvidenceItem(
                category="protocol_findings",
                text="В протоколе заявление о давности зафиксировано.",
                source_document="05.txt",
                source_type="PROTOCOL",
                order=2,
            )
        )
        report = verify_draft(_draft("Взыскать 150 000 руб."), pack)
        flagged = [i for i in report.issues if i.type is IssueType.STATEMENT_LIMITATION]
        assert flagged
