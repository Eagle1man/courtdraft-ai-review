"""Тесты пакета доказательств, Draft Agent и Verification (Фазы 8-10).

Ключевое, что здесь проверяется: модель не может выдумать сумму
и проверка это ловит. Это центральное требование продукта — проект
без проверки на источник опаснее, чем отсутствие проекта.
"""

from __future__ import annotations

from app.agents.draft_agent import (
    NEEDS_REVIEW,
    DraftResult,
    SectionDraft,
    _postprocess,
    build_section_prompt,
)
from app.agents.evidence_pack import (
    EvidenceItem,
    EvidencePack,
    extract_dates,
    extract_money,
)
from app.llm.base import LLMMessage, LLMProvider, LLMRequest, LLMResponse, LLMRole
from app.verification.engine import (
    IssueType,
    Severity,
    VerificationStatus,
    compare_versions,
    verify_draft,
)

TEMPLATE = {
    "name": "civil_judgment",
    "sections": [
        {
            "key": "introductory",
            "name": "Вводная часть",
            "purpose": "суд, дата, стороны",
            "prompt_hint": "Перечисли.",
            "evidence_categories": ["case_metadata", "participants"],
        },
        {
            "key": "motivating",
            "name": "Мотивировочная часть",
            "purpose": "обоснование",
            "prompt_hint": "Обоснуй.",
            "evidence_categories": ["legal_position"],
        },
    ],
}


def make_pack() -> EvidencePack:
    pack = EvidencePack(
        case_number="DEMO-001",
        court_name="Демо суд",
        category="договорные споры",
        participants=["Образцов П. П. (истец)", "Фирма «Вымышленная» (ответчик)"],
        amounts=["150000", "120000"],
        dates=["15 мая 2026"],
    )
    pack.items = [
        EvidenceItem(
            category="legal_position",
            text="В силу статьи 310 ГК РФ обязательства должны быть исполнены надлежащим образом",
            source_document="01_claim.txt",
            source_type="CLAIM",
            amounts=["150000"],
        ),
        EvidenceItem(
            category="case_metadata",
            text="Исковое заявление о взыскании задолженности 150000 руб.",
            source_document="01_claim.txt",
            source_type="CLAIM",
        ),
    ]
    return pack


class TestMoneyExtraction:
    def test_simple_amount(self) -> None:
        assert "150000" in extract_money("сумма 150 000 руб.")

    def test_kopecks_discarded(self) -> None:
        """«120 000,00 руб.» — сумма 120000, а не 00."""
        found = extract_money("перечислено 120 000,00 руб.")
        assert "120000" in found
        assert "00" not in found

    def test_thousands_suffix(self) -> None:
        assert "120000" in extract_money("неустойка 120 тыс. рублей")

    def test_no_money(self) -> None:
        assert extract_money("текст без сумм") == []

    def test_article_numbers_not_money(self) -> None:
        """Номер статьи не должен попадать в суммы."""
        assert extract_money("статья 310 ГК РФ") == []


class TestDateExtraction:
    def test_basic(self) -> None:
        assert "15 мая 2026" in extract_dates("договор от 15 мая 2026 года")

    def test_multiple(self) -> None:
        found = extract_dates("1 июня 2026 года и 3 июля 2026 года")
        assert len(found) == 2

    def test_none(self) -> None:
        assert extract_dates("без дат") == []


class TestSectionPrompt:
    def test_contains_only_material(self) -> None:
        """В подсказке модели не должно быть фактов вне пакета."""
        pack = make_pack()
        prompt, citations = build_section_prompt(TEMPLATE["sections"][1], pack)
        assert "статьи 310" in prompt
        assert "DEMO-001" in prompt
        assert citations

    def test_gaps_are_shown_to_model(self) -> None:
        """Пробелы передаются модели явно, чтобы она не выдумывала."""
        pack = make_pack()
        pack.gaps.append("нет данных: установленные обстоятельства")
        prompt, _ = build_section_prompt(TEMPLATE["sections"][0], pack)
        assert "установленные обстоятельства" in prompt

    def test_amounts_from_pack_not_invented(self) -> None:
        pack = make_pack()
        prompt, _ = build_section_prompt(TEMPLATE["sections"][0], pack)
        assert "150000" in prompt


class TestPostprocess:
    def test_strips_repeated_heading(self) -> None:
        """Модель часто повторяет заголовок — это ломает структуру."""
        cleaned, _ = _postprocess(
            "МОТИВИРОВОЧНАЯ ЧАСТЬ\n\nТекст раздела.", TEMPLATE["sections"][1]
        )
        assert not cleaned.startswith("МОТИВИРОВОЧНАЯ")
        assert "Текст раздела" in cleaned

    def test_detects_review_marker(self) -> None:
        _, needs = _postprocess(f"Данных нет. {NEEDS_REVIEW}", TEMPLATE["sections"][1])
        assert needs is True

    def test_empty_gets_marker(self) -> None:
        cleaned, needs = _postprocess("", TEMPLATE["sections"][1])
        assert needs is True
        assert NEEDS_REVIEW in cleaned

    def test_strips_service_prefix(self) -> None:
        cleaned, _ = _postprocess("Раздел: текст", TEMPLATE["sections"][1])
        assert cleaned.startswith("текст")


class TestVerification:
    def test_detects_invented_amount(self) -> None:
        """ГЛАВНАЯ проверка: сумма, которой нет в материалах."""
        pack = make_pack()
        draft = DraftResult(
            case_number="DEMO-001",
            sections=[
                SectionDraft(
                    key="operative",
                    name="РЕШИЛ",
                    text="Взыскать 999 999 рублей задолженности.",
                    is_mock=False,
                    citations=["01_claim.txt"],
                )
            ],
        )
        report = verify_draft(draft, pack)
        assert report.unsupported_claims >= 1
        invented = [i for i in report.issues if i.type is IssueType.UNSUPPORTED_CLAIM]
        assert any("999" in i.reason for i in invented)
        assert report.status is VerificationStatus.REVIEW_REQUIRED

    def test_amount_from_pack_passes(self) -> None:
        pack = make_pack()
        draft = DraftResult(
            case_number="DEMO-001",
            sections=[
                SectionDraft(
                    key="operative",
                    name="РЕШИЛ",
                    text="Взыскать 150000 рублей.",
                    is_mock=False,
                    citations=["01_claim.txt"],
                )
            ],
        )
        report = verify_draft(draft, pack)
        assert report.unsupported_claims == 0

    def test_detects_unsupported_law(self) -> None:
        pack = make_pack()
        draft = DraftResult(
            case_number="DEMO-001",
            sections=[
                SectionDraft(
                    key="motivating",
                    name="Мотивировочная часть",
                    text="Согласно статье 1234 ГК РФ требование удовлетворяется.",
                    is_mock=False,
                    citations=["01_claim.txt"],
                )
            ],
        )
        report = verify_draft(draft, pack)
        assert any(i.type is IssueType.LAW_NOT_FOUND for i in report.issues)

    def test_detects_missing_source(self) -> None:
        pack = make_pack()
        draft = DraftResult(
            case_number="DEMO-001",
            sections=[
                SectionDraft(
                    key="unknown_section",
                    name="Неизвестный раздел",
                    text="Текст без источника вообще.",
                    is_mock=False,
                    citations=[],
                )
            ],
        )
        report = verify_draft(draft, pack)
        assert any(i.type is IssueType.MISSING_SOURCE for i in report.issues)

    def test_detects_generation_error(self) -> None:
        draft = DraftResult(
            case_number="DEMO-001",
            sections=[
                SectionDraft(
                    key="operative",
                    name="РЕШИЛ",
                    text="Не сгенерировано.",
                    error="timeout",
                )
            ],
        )
        report = verify_draft(draft, make_pack())
        assert any(i.severity is Severity.HIGH for i in report.issues)

    def test_clean_draft_passes(self) -> None:
        """Идеальный раздел, полностью опирающийся на материалы."""
        pack = make_pack()
        draft = DraftResult(
            case_number="DEMO-001",
            sections=[
                SectionDraft(
                    key="motivating",
                    name="Мотивировочная часть",
                    text="В силу статьи 310 ГК РФ обязательства должны быть исполнены надлежащим образом.",
                    is_mock=False,
                    citations=["01_claim.txt"],
                )
            ],
        )
        report = verify_draft(draft, pack)
        assert report.unsupported_claims == 0
        assert report.status is VerificationStatus.PASS


class TestDraftText:
    def test_sections_joined_in_order(self) -> None:
        draft = DraftResult(
            case_number="DEMO-001",
            sections=[
                SectionDraft(key="introductory", name="Вводная часть", text="Первый."),
                SectionDraft(key="operative", name="РЕШИЛ", text="Второй."),
            ],
        )
        text = draft.text
        assert text.index("ВВОДНАЯ ЧАСТЬ") < text.index("РЕШИЛ")

    def test_stats(self) -> None:
        draft = DraftResult(
            case_number="DEMO-001",
            sections=[
                SectionDraft(key="a", name="A", text="x", citations=["d1.txt"]),
                SectionDraft(key="b", name="B", text="y", citations=["d1.txt", "d2.txt"]),
            ],
        )
        assert draft.stats()["citations"] == 2

    def test_needs_review_collected(self) -> None:
        draft = DraftResult(
            case_number="DEMO-001",
            sections=[
                SectionDraft(key="a", name="A", text="x", needs_review=True),
                SectionDraft(key="b", name="B", text="y"),
            ],
        )
        assert len(draft.sections_needing_review) == 1


class TestVersionCompare:
    def test_detects_changes(self) -> None:
        before = "Суд решил взыскать 150000 рублей. Решение вступило в силу."
        after = "Суд решил взыскать 120000 рублей. Решение вступило в силу."
        diff = compare_versions(before, after)
        assert diff["removed"] == 1
        assert diff["added"] == 1
        assert diff["unchanged"] == 1


class TestMockProviderUsedForTests:
    """Провайдер-заглушка для проверки конвейера агентов."""

    async def test_satisfies_protocol(self) -> None:
        from app.llm.mock import MockLLMProvider

        assert isinstance(MockLLMProvider(), LLMProvider)

    async def test_json_mode(self) -> None:
        from app.llm.mock import MockLLMProvider

        provider = MockLLMProvider()
        response = await provider.generate(
            LLMRequest(
                messages=[LLMMessage(role="user", content="Извлеки факты и требования")],
                role=LLMRole.EXTRACTION,
                json_mode=True,
            )
        )
        assert isinstance(response, LLMResponse)
        assert response.is_mock
