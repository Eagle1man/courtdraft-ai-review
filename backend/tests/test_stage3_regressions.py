"""Регрессионные тесты Этапа 3: дефекты D1, D2, D4, D6, F1.

D3 (источник замечания) оказался недостижимой веткой: при склейке
фрагментов через пробел маркер, найденный в объединённом тексте, всегда
содержится в одном фрагменте. Код всё равно заменён на явное «источник
неизвестен» (engine.py), а здесь — страховочный тест корректной привязки.
"""

from __future__ import annotations

from app.agents.draft_agent import DraftResult, SectionDraft
from app.agents.evidence_pack import EvidenceItem, EvidencePack
from app.verification.engine import IssueType, verify_draft
from app.verification.evidence_assessment import check_evidence_assessment


def _draft(text: str = "Взыскать 150 000 руб."):
    stub = type("D", (), {})()
    stub.sections = [
        SectionDraft(
            key="operative", name="Резолютивная часть", text=text, is_mock=False
        )
    ]
    return stub


def _draft_with_citations(citations: list[str]):
    stub = type("D", (), {})()
    stub.sections = [
        SectionDraft(
            key="operative",
            name="Резолютивная часть",
            text="Взыскать 1000 руб.",
            is_mock=False,
            citations=citations,
        )
    ]
    return stub


class TestD1SourcesDedup:
    """Страница в скобках — вариант того же документа, а не новый источник."""

    def test_parenthesized_page_is_one_source(self) -> None:
        agent = object.__new__(DraftResult)
        agent.sections = [
            SectionDraft(
                key="operative",
                name="РЕШИЛ",
                text="Взыскать.",
                is_mock=False,
                citations=["03_contract.txt (стр. 3)"],
            ),
            SectionDraft(
                key="motivation",
                name="М",
                text="Обосновано.",
                is_mock=False,
                citations=["03_contract.txt"],
            ),
        ]
        assert len(agent.sources()) == 1

    def test_different_documents_stay_separate(self) -> None:
        agent = object.__new__(DraftResult)
        agent.sections = [
            SectionDraft(
                key="operative",
                name="РЕШИЛ",
                text="Взыскать.",
                is_mock=False,
                citations=["01_claim.txt", "02_response.txt"],
            ),
        ]
        assert len(agent.sources()) == 2


class TestD2DanglingCitation:
    def test_citation_to_missing_document_flagged(self) -> None:
        pack = EvidencePack(case_number="T-0003")
        pack.items.append(
            EvidenceItem(
                category="claims",
                text="Задолженность составила 10148 рублей.",
                source_document="01_claim.txt",
                source_type="CLAIM",
                amounts=["10148"],
                order=1,
            )
        )
        report = verify_draft(
            _draft_with_citations(["01_claim.txt", "99_missing.txt"]), pack
        )
        assert any(i.type is IssueType.CITATION_DANGLING for i in report.issues)

    def test_real_citation_not_flagged(self) -> None:
        pack = EvidencePack(case_number="T-0003b")
        pack.items.append(
            EvidenceItem(
                category="claims",
                text="Задолженность составила 10148 рублей.",
                source_document="01_claim.txt",
                source_type="CLAIM",
                amounts=["10148"],
                order=1,
            )
        )
        report = verify_draft(_draft_with_citations(["01_claim.txt"]), pack)
        assert not any(i.type is IssueType.CITATION_DANGLING for i in report.issues)


class TestD3StatementSourceAttribution:
    """Источник замечания — фрагмент, содержащий заявление."""

    def test_marker_in_second_fragment_cites_second(self) -> None:
        pack = EvidencePack(case_number="T-0004")
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
        report = verify_draft(_draft(), pack)
        flagged = [i for i in report.issues if i.type is IssueType.STATEMENT_LIMITATION]
        assert flagged
        assert flagged[0].text.startswith("В протоколе")


class TestD4PenaltyReductionFalsePositive:
    def test_number_333_is_not_article(self) -> None:
        # «333 рубля» — сумма, а не ссылка на ст. 333 ГК: замечания быть
        # не должно (дефект D4 — ложное срабатывание на числе).
        pack = EvidencePack(case_number="T-0005")
        pack.items.append(
            EvidenceItem(
                category="objections",
                text="Ответчик оспаривает неустойку 333 рубля как несоразмерную.",
                source_document="02_response.txt",
                source_type="RESPONSE",
                order=1,
            )
        )
        report = verify_draft(_draft(), pack)
        assert not [
            i for i in report.issues if i.type is IssueType.STATEMENT_PENALTY_REDUCTION
        ]

    def test_article_333_still_flagged(self) -> None:
        pack = EvidencePack(case_number="T-0005b")
        pack.items.append(
            EvidenceItem(
                category="objections",
                text="Ответчик просит снизить неустойку на основании ст. 333 ГК РФ.",
                source_document="02_response.txt",
                source_type="RESPONSE",
                order=1,
            )
        )
        report = verify_draft(_draft(), pack)
        assert [
            i for i in report.issues if i.type is IssueType.STATEMENT_PENALTY_REDUCTION
        ]


class TestD6ExpertQuestionIndependent:
    def test_expert_question_not_suppressed_by_criterion(self) -> None:
        # Упоминание критерия в одной строке не отменяет вопрос об оценке
        # заключения эксперта в деле (дефект D6).
        findings = check_evidence_assessment(
            "Суд оценил относимость доказательств. Заключение эксперта получено.",
            ["В деле имеется заключение эксперта."],
        )
        assert any(f.kind == "expert_unassessed" for f in findings)

    def test_assessed_draft_without_expert_stays_silent(self) -> None:
        findings = check_evidence_assessment(
            "Доказательства оцениваются по относимости и достоверности.",
            ["Договор и платёжное поручение."],
        )
        assert not [f for f in findings if f.kind == "expert_unassessed"]


class TestF1UnparsedClaimAmount:
    def test_amount_in_claim_but_no_money_claim_flagged(self) -> None:
        pack = EvidencePack(case_number="T-0006")
        pack.items.append(
            EvidenceItem(
                category="claims",
                text="Задолженность составила 10148 рублей.",
                source_document="01_claim.txt",
                source_type="CLAIM",
                amounts=["10148"],
                order=1,
            )
        )
        report = verify_draft(_draft("Взыскать 150 000 руб."), pack)
        assert any(i.type is IssueType.CLAIM_AMOUNT_UNPARSED for i in report.issues)

    def test_parsed_claim_not_flagged(self) -> None:
        pack = EvidencePack(case_number="T-0006b")
        pack.items.append(
            EvidenceItem(
                category="claims",
                text="Истец просит взыскать с ответчика 10148 рублей долга.",
                source_document="01_claim.txt",
                source_type="CLAIM",
                amounts=["10148"],
                order=1,
            )
        )
        report = verify_draft(_draft("Взыскать 150 000 руб."), pack)
        assert not any(
            i.type is IssueType.CLAIM_AMOUNT_UNPARSED for i in report.issues
        )
