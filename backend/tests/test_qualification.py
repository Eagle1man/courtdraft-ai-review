"""Квалификация договора и подведомственность (п. 3–4 разбора)."""

from app.agents.draft_agent import SectionDraft
from app.agents.evidence_pack import EvidenceItem, EvidencePack
from app.verification.engine import IssueType, verify_draft
from app.verification.qualification import check_qualification


def _texts(*parts: str) -> list[str]:
    return list(parts)


class TestQualification:
    def test_supply_natural_person_flags_qualification(self) -> None:
        findings = check_qualification(
            _texts("Договор поставки № 12 от 15.03.2026."),
            plaintiff="Образцов Пётр Петрович",
            defendant="ООО «Фирма-Трейд»",
        )
        kinds = [f.kind for f in findings]
        assert "qualification" in kinds
        q = next(f for f in findings if f.kind == "qualification")
        assert "ст. 506" in q.reason and "купля-продажа" in q.reason

    def test_ip_marked_no_qualification_flag(self) -> None:
        findings = check_qualification(
            _texts("Договор поставки. Истец — индивидуальный предприниматель."),
            plaintiff="Образцов Пётр Петрович",
            defendant="ООО «Фирма»",
        )
        assert all(f.kind != "qualification" for f in findings)

    def test_ip_and_org_flags_arbitration(self) -> None:
        findings = check_qualification(
            _texts("Договор поставки, поставщик — ИП Сидоров."),
            plaintiff="ИП Сидоров",
            defendant="ООО «Фирма»",
        )
        kinds = [f.kind for f in findings]
        assert "arbitration" in kinds
        a = next(f for f in findings if f.kind == "arbitration")
        assert "27, 28 АПК" in a.reason and "33 ГПК" in a.reason

    def test_not_supply_silent(self) -> None:
        findings = check_qualification(
            _texts("Договор оказания услуг."),
            plaintiff="Образцов Пётр Петрович",
            defendant="ООО «Фирма»",
        )
        assert findings == []

    def test_org_plaintiff_silent(self) -> None:
        findings = check_qualification(
            _texts("Договор поставки."),
            plaintiff="ООО «Истец»",
            defendant="ООО «Фирма»",
        )
        # Истец — организация, признака ИП нет: вопрос о квалификации
        # не строится, об арбитраже тоже (нет ИП).
        assert findings == []

    def test_no_false_positive_on_ip_substring(self) -> None:
        # «заявитель», «писание» содержат «ип», но это не ИП.
        findings = check_qualification(
            _texts("Договор поставки. Заявитель просит, писание не ведётся."),
            plaintiff="Образцов Пётр Петрович",
            defendant="ООО «Фирма»",
        )
        kinds = [f.kind for f in findings]
        assert "arbitration" not in kinds


class TestQualificationInReport:
    def _pack(self, contract_text: str, plaintiff: str, defendant: str) -> EvidencePack:
        pack = EvidencePack(case_number="T-0001")
        pack.participants.append(f"{plaintiff} (истец)")
        pack.participants.append(f"{defendant} (ответчик)")
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

    def _draft(self):
        draft_stub = type("D", (), {})()
        draft_stub.sections = [
            SectionDraft(
                key="operative",
                name="Резолютивная часть",
                text="Взыскать 150 000 руб.",
                is_mock=False,
            )
        ]
        return draft_stub

    def test_qualification_reaches_report(self) -> None:
        pack = self._pack(
            "Договор поставки № 1.", "Образцов Пётр Петрович", "ООО «Фирма»"
        )
        report = verify_draft(self._draft(), pack)
        flagged = [i for i in report.issues if i.type is IssueType.CONTRACT_QUALIFICATION]
        assert flagged
        assert flagged[0].severity.value == "MEDIUM"
