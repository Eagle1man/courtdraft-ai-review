"""Проверка досудебного порядка (п. 76 разбора, ст. 132, 135, 222 ГПК)."""

from app.agents.draft_agent import SectionDraft
from app.agents.evidence_pack import EvidenceItem, EvidencePack
from app.verification.engine import IssueType, verify_draft


def _pack(contract_text: str | None) -> EvidencePack:
    pack = EvidencePack(case_number="T-0001")
    if contract_text:
        pack.items.append(
            EvidenceItem(
                category="evidence",
                text=contract_text,
                source_document="03_contract.txt",
                source_type="CONTRACT",
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


class TestPretrial:
    def test_condition_in_materials_draft_silent_flagged(self) -> None:
        pack = _pack(
            "Споры разрешаются в досудебном порядке путём направления претензии."
        )
        report = verify_draft(_draft("Взыскать с ответчика в пользу истца 150 000 руб."), pack)
        flagged = [i for i in report.issues if i.type is IssueType.PRETRIAL_UNADDRESSED]
        assert flagged
        assert flagged[0].severity.value == "HIGH"

    def test_condition_addressed_not_flagged(self) -> None:
        pack = _pack(
            "Договором установлен претензионный порядок до обращения в суд."
        )
        report = verify_draft(
            _draft(
                "Досудебный порядок соблюден: претензия направлена ответчику, "
                "ответ не поступил."
            ),
            pack,
        )
        flagged = [i for i in report.issues if i.type is IssueType.PRETRIAL_UNADDRESSED]
        assert not flagged

    def test_no_condition_silent(self) -> None:
        pack = _pack(None)
        report = verify_draft(_draft("Взыскать 150 000 руб."), pack)
        flagged = [i for i in report.issues if i.type is IssueType.PRETRIAL_UNADDRESSED]
        assert not flagged

    def test_flagged_from_claim_mention_too(self) -> None:
        # Условие может быть и в иске: «истец направил претензию» —
        # проверка не привязана к договору, а смотрит на материалы целиком.
        pack = EvidencePack(case_number="T-0002")
        pack.items.append(
            EvidenceItem(
                category="claims",
                text="Истец 01.03.2020 направил ответчику претензию о погашении долга.",
                source_document="01_claim.txt",
                source_type="CLAIM",
                order=1,
            )
        )
        report = verify_draft(_draft("Взыскать 150 000 руб."), pack)
        flagged = [i for i in report.issues if i.type is IssueType.PRETRIAL_UNADDRESSED]
        assert flagged
