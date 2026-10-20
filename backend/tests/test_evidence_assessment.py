r"""Оценка доказательств по ст. 67 ГПК РФ (п. 5 разбора).

Рецензент: нет оценки относимости, допустимости, достоверности и
достаточности в совокупности; заключение эксперта принимается без
оценки наравне с другими доказательствами (ч. 3 ст. 86 ГПК РФ).
Проверяется две честные вещи: таблица критериев в проекте и вопросы
наружу — позиция стороны как доказательство и эксперт без оценки.
"""

from app.agents.draft_agent import SectionDraft
from app.agents.evidence_pack import EvidenceItem, EvidencePack
from app.verification.engine import IssueType, Severity, verify_draft
from app.verification.evidence_assessment import (
    assessment_of,
    check_evidence_assessment,
)


def _pack(*texts: str) -> EvidencePack:
    pack = EvidencePack(case_number="T-0002")
    for index, text in enumerate(texts, start=1):
        pack.items.append(
            EvidenceItem(
                category="claim" if index == 1 else "objections",
                text=text,
                source_document=f"{index:02d}_doc.txt",
                source_type="OTHER",
                order=index,
            )
        )
    return pack


def _draft(text: str):
    draft_stub = type("D", (), {})()
    draft_stub.sections = [
        SectionDraft(
            key="findings", name="Мотивировочная часть", text=text, is_mock=False
        )
    ]
    return draft_stub


class TestAssessmentTable:
    def test_criteria_marked_by_roots(self) -> None:
        rows = assessment_of(
            "Доказательства относимы, допустимы и достоверны; "
            "совокупности доказательств достаточно."
        )
        assert all(row.covered for row in rows)

    def test_unmentioned_criterion_stays_uncovered(self) -> None:
        rows = assessment_of("Доказательства достоверны.")
        by_name = {row.criterion: row.covered for row in rows}
        assert by_name["достоверность"] is True
        assert by_name["относимость"] is False
        assert by_name["допустимость"] is False
        assert by_name["достаточность в совокупности"] is False

    def test_empty_draft_all_uncovered(self) -> None:
        assert not any(row.covered for row in assessment_of(""))


class TestPleadingAsEvidence:
    def test_claim_as_evidence_flagged(self) -> None:
        found = check_evidence_assessment(
            "Обстоятельства дела подтверждаются исковым заявлением.", []
        )
        assert [f.kind for f in found] == ["pleading_as_evidence"]

    def test_backward_order_flagged(self) -> None:
        found = check_evidence_assessment(
            "Заключение договора подтверждается исковым заявлением истца.", []
        )
        assert [f.kind for f in found] == ["pleading_as_evidence"]

    def test_response_as_evidence_flagged(self) -> None:
        found = check_evidence_assessment(
            "Ответчик ссылается на то, что отзыв подтверждает оплату.", []
        )
        assert [f.kind for f in found] == ["pleading_as_evidence"]

    def test_requirement_with_calculation_not_flagged(self) -> None:
        # Подтверждается расчёт, а не заявление: верная фраза.
        found = check_evidence_assessment(
            "Расчёт требований искового заявления подтверждается "
            "бухгалтерской справкой.",
            [],
        )
        assert found == []

    def test_party_explanations_not_flagged(self) -> None:
        # Объяснения сторон — доказательство по ч. 1 ст. 55 ГПК РФ.
        found = check_evidence_assessment(
            "Объяснения представителя подтверждают обстоятельства дела.", []
        )
        assert found == []

    def test_court_acceptance_not_flagged(self) -> None:
        # Дальняя ссылка в том же предложении — заявление ничего не
        # подтверждает, оно просто принято к производству. Вопрос
        # «доказательства не оцениваются» здесь возможен и по ст. 67,
        # но к позиции стороны отношения он не имеет.
        found = check_evidence_assessment(
            "Обстоятельства установлены судом по представленным "
            "доказательствам, исковое заявление принято к производству.",
            [],
        )
        assert not [f for f in found if f.kind == "pleading_as_evidence"]


class TestAssessmentQuestions:
    def test_evidence_without_assessment_question(self) -> None:
        found = check_evidence_assessment(
            "Выводы опираются на доказательства по делу.", []
        )
        assert [f.kind for f in found] == ["not_assessed"]

    def test_assessed_draft_no_question(self) -> None:
        found = check_evidence_assessment(
            "Представленные доказательства относимы, допустимы и достоверны.", []
        )
        assert found == []

    def test_expert_without_assessment_question(self) -> None:
        found = check_evidence_assessment(
            "По заключению эксперта размер долга составляет 150 000 руб.",
            ["В деле заключение судебной экспертизы по количеству товара."],
        )
        assert [f.kind for f in found] == ["expert_unassessed"]

    def test_expert_in_materials_draft_silent(self) -> None:
        found = check_evidence_assessment(
            "Проект опирается на договор и накладные.",
            ["В деле заключение судебной экспертизы."],
        )
        assert found == []

    def test_assessed_expert_no_question(self) -> None:
        found = check_evidence_assessment(
            "Достоверность заключения эксперта проверена наравне с "
            "другими доказательствами.",
            ["В деле заключение эксперта."],
        )
        assert found == []


class TestEngineIntegration:
    def test_pleading_flagged_high(self) -> None:
        report = verify_draft(
            _draft("Обстоятельства подтверждаются исковым заявлением."),
            _pack("Истец просит взыскать долг."),
        )
        flagged = [i for i in report.issues if i.type is IssueType.PLEADING_AS_EVIDENCE]
        assert flagged
        assert flagged[0].severity is Severity.HIGH

    def test_unassessed_evidence_question(self) -> None:
        report = verify_draft(
            _draft("Выводы опираются на доказательства по делу."),
            _pack("Истец просит взыскать долг по договору."),
        )
        flagged = [
            i for i in report.issues if i.type is IssueType.EVIDENCE_NOT_ASSESSED
        ]
        assert flagged
        assert flagged[0].severity is Severity.MEDIUM

    def test_assessment_table_in_report(self) -> None:
        report = verify_draft(
            _draft("Доказательства допустимы и достоверны."),
            _pack("Истец просит взыскать долг."),
        )
        by_name = {row.criterion: row.covered for row in report.assessment}
        assert by_name["допустимость"] is True
        assert by_name["достоверность"] is True
        assert by_name["относимость"] is False
        payload = report.to_dict()
        assert payload["evidence_assessment"] == [
            c.to_dict() for c in report.assessment
        ]

    def test_expert_unassessed_question(self) -> None:
        report = verify_draft(
            _draft("Размер долга определён заключением эксперта."),
            _pack("Истец просит взыскать долг.", "Назначена судебная экспертиза."),
        )
        flagged = [i for i in report.issues if i.type is IssueType.EXPERT_UNASSESSED]
        assert flagged
        assert flagged[0].severity is Severity.MEDIUM

    def test_mock_section_not_flagged_for_assessment(self) -> None:
        # Заглушка не содержит ни доказательств, ни критериев —
        # замечание о неоценке ей не положено.
        report = verify_draft(
            _draft("Раздел не сформирован: модель не вызвана."),
            _pack("Истец просит взыскать долг."),
        )
        assert not [
            i for i in report.issues if i.type is IssueType.EVIDENCE_NOT_ASSESSED
        ]
