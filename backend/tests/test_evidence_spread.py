"""Каждый документ дела должен попадать в пакет доказательств.

Лимит на число фрагментов стоял на категорию, а не на документ. Категория
заполнялась первыми предложениями первого файла — иска, — а документы в
 конце списка не давали ничего. В деле из шести документов факты шли
только из иска, протокола и отзыва: договор, платёжное поручение и
заключение эксперта оказывались вне пакета, хотя их тип распознавался
верно. В споре о долге договор — доказательство, и молчание о нём хуже,
чем лишняя цитата.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import Counter

from app.agents.evidence_pack import PER_DOCUMENT_LIMIT, build_evidence_pack
from app.models.entities import CaseDocument

CONTRACT = (
    "Договор поставки № 14 заключён между Образцовым и ООО «Фирма "
    "Вымышленная Строй». Поставщик обязуется передать товар в течение "
    "двух месяцев с момента заключения договора. Цена договора "
    "составляет 120 000 руб. Оплата производится в течение десяти дней "
    "с момента поставки товара. Договор заключён в городе. Порядок "
    "поставки определён разделом второй. Ответчик обязуется оплатить "
    "товар в срок. Стороны согласовали график поставок."
)

RECEIPT = (
    "Платёжное поручение № 118 от 12 марта по оплате товара. Платёж "
    "на сумму 120 000 руб. Платёж перечислен. Назначение платежа: "
    "оплата по договору поставки. Банк исполнил поручение. Расчётный "
    "счёт получателя. Платёж зачтён. Остаток задолженности отсутствует "
    "по состоянию на дату платежа."
)

EXPERT = (
    "Заключение судебной экспертизы. Эксперт установил, что стоимость "
    "товара составляет 30 000 руб. Эксперт пришёл к выводу о ненадлежащем "
    "качестве товара. Заключение эксперта не оспорено сторонами. "
    "Эксперт поддержал ранее заявленные требования. Выводы эксперта "
    "соответствуют обстоятельствам дела. Эксперт не указал иное."
)


def make_document(filename: str, text: str, doc_type: str) -> CaseDocument:
    return CaseDocument(
        id=uuid.uuid4(),
        case_id=uuid.uuid4(),
        filename=filename,
        document_type=doc_type,
        mime_type="text/plain",
        page_count=1,
        text=text,
        metadata_json={},
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def build_pack():
    claim = (
        "Прошу взыскать задолженность по договору поставки в размере "
        "150 000 руб. 00 коп. Истец Образцов Пётр Петрович обращается в "
        "суд с иском к ООО «Фирма Вымышленная Строй». Исковые требования "
        "подтверждаются договором и платёжным поручением. "
        "Государственная пошлина уплачена в размере 5 100 руб."
    )
    documents = [
        make_document("01_claim.txt", claim, "CLAIM"),
        make_document("03_contract.txt", CONTRACT, "CONTRACT"),
        make_document("04_receipt.txt", RECEIPT, "RECEIPT"),
        make_document("06_expert_opinion.txt", EXPERT, "EXPERT_OPINION"),
    ]
    return build_evidence_pack("T-0001", "Тестовый суд", "договорные споры", documents)


class TestEveryDocumentContributes:
    """Ни один документ дела не остаётся без фактов."""

    def test_contract_is_used(self) -> None:
        pack = build_pack()
        sources = {item.source_document for item in pack.items}
        assert "03_contract.txt" in sources

    def test_receipt_is_used(self) -> None:
        pack = build_pack()
        sources = {item.source_document for item in pack.items}
        assert "04_receipt.txt" in sources

    def test_expert_opinion_is_used(self) -> None:
        pack = build_pack()
        sources = {item.source_document for item in pack.items}
        assert "06_expert_opinion.txt" in sources

    def test_all_documents_present(self) -> None:
        pack = build_pack()
        assert {item.source_document for item in pack.items} == {
            "01_claim.txt",
            "03_contract.txt",
            "04_receipt.txt",
            "06_expert_opinion.txt",
        }

    def test_document_type_is_kept(self) -> None:
        """Тип документа доезжает до факта: по нему судья видит, что это."""
        pack = build_pack()
        types = {item.source_type for item in pack.items}
        assert "CONTRACT" in types
        assert "EXPERT_OPINION" in types


class TestLimitIsPerDocument:
    """Лимит не должен никого обделить."""

    def test_no_document_starved(self) -> None:
        pack = build_pack()
        counter = Counter(item.source_document for item in pack.items)
        assert min(counter.values()) > 0

    def test_limit_respected(self) -> None:
        pack = build_pack()
        counter = Counter(item.source_document for item in pack.items)
        assert max(counter.values()) <= PER_DOCUMENT_LIMIT
