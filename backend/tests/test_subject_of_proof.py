"""Таблица «обстоятельство — доказательства» (п. 5.4 разбора)."""

from app.agents.evidence_pack import EvidenceItem, EvidencePack
from app.verification.engine import verify_draft
from app.verification.subject_of_proof import subject_of_proof


def _item(document: str, text: str, order: int) -> EvidenceItem:
    return EvidenceItem(
        category="evidence",
        text=text,
        source_document=document,
        source_type="EVIDENCE",
        order=order,
    )


class TestSubjectOfProof:
    def test_covered_circumstance_lists_document(self) -> None:
        pack = EvidencePack(case_number="T-1")
        pack.items.append(_item("01_claim.txt", "Между сторонами заключён договор.", 1))
        pack.items.append(_item("02_bill.txt", "Накладная на отгрузку товара.", 2))
        facts = subject_of_proof(pack.items)
        contract = facts[0]
        assert contract.covered
        assert contract.docs == ("01_claim.txt",)
        delivery = facts[1]
        assert delivery.docs == ("02_bill.txt",)

    def test_uncovered_circumstance_reported(self) -> None:
        facts = subject_of_proof(
            [_item("01_claim.txt", "Истец просит взыскать долг.", 1)]
        )
        penalty = facts[-1]
        assert not penalty.covered
        assert not penalty.docs

    def test_no_duplicate_documents(self) -> None:
        pack = EvidencePack(case_number="T-2")
        pack.items.append(
            _item("01_claim.txt", "Договор от 5 марта 2013 года. Долг по договору.", 1)
        )
        facts = subject_of_proof(pack.items)
        assert facts[0].docs == ("01_claim.txt",)
        assert facts[2].docs == ("01_claim.txt",)

    def test_report_serializes_facts(self) -> None:
        pack = EvidencePack(case_number="T-3")
        pack.items.append(_item("01_claim.txt", "Договор оставлен без оплаты.", 1))
        draft = type("D", (), {})()
        draft.sections = []
        report = verify_draft(draft, pack)
        data = report.to_dict()
        assert len(data["subject_of_proof"]) == 5

    def test_uncovered_facts_in_summary(self) -> None:
        pack = EvidencePack(case_number="T-4")
        draft = type("D", (), {})()
        draft.sections = []
        report = verify_draft(draft, pack)
        summary = report.human_summary()
        assert "Ни одним документом не подтверждено" in summary
        assert "заключение договора" in summary
