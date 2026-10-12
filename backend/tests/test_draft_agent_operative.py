"""Тест того, что резолютивная часть собирается правилами, а не моделью.

Проверяется не сам модуль сборки (он покрыт в test_operative.py), а
граница между ним и агентом: раздел должен уходить модели в том числе
тогда, когда модель ответила бы иначе. Иначе правило легко сломать
правкой цикла и никто этого не заметит.
"""

from __future__ import annotations

import pytest

from app.agents.draft_agent import (
    RULES_BUILT_SECTIONS,
    generate_draft,
)
from app.agents.evidence_pack import EvidenceItem, EvidencePack
from app.llm.base import LLMProvider, LLMRequest, LLMResponse


class WrongLLM(LLMProvider):
    """Модель, которая пишет в резолютивную часть ерунду.

    Нужна, чтобы доказать: агент вообще не спрашивает её про раздел
    «РЕШИЛ», и текст модели не может попасть в результат.
    """

    name = "wrong"
    calls: list[str] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        type(self).calls.append(request.messages[-1].content)
        return LLMResponse(
            text="Ответчик ничего не должен истцу, всё выдумано.",
            is_mock=False,
            model="wrong",
        )

    async def health(self) -> bool:
        return True

    @property
    def model_name(self) -> str:
        return "wrong"


@pytest.fixture
def pack() -> EvidencePack:
    result = EvidencePack(case_number="5-1/2019", court_name="Суд")
    for text in (
        "Истец требует взыскать с ответчика задолженность по договору "
        "поставки в размере 150000 рублей.",
        "Истец требует взыскать неустойку за просрочку оплаты "
        "в размере 90000 рублей.",
    ):
        result.items.append(
            EvidenceItem(
                category="claims",
                text=text,
                source_document="исковое заявление.txt",
                source_type="CLAIM",
            )
        )
    return result


@pytest.fixture
def template() -> dict[str, object]:
    return {
        "sections": [
            {"key": "operative", "name": "РЕШИЛ", "purpose": "", "required_fields": []},
        ]
    }


class TestOperativeIsNotModelGenerated:
    @pytest.mark.asyncio
    async def test_llm_not_called_for_operative(
        self, pack: EvidencePack, template: dict[str, object]
    ) -> None:
        WrongLLM.calls = []
        await generate_draft(pack, template, provider=WrongLLM())

        assert WrongLLM.calls == [], (
            "резолютивная часть не должна запрашиваться у модели"
        )

    @pytest.mark.asyncio
    async def test_model_text_never_appears(
        self, pack: EvidencePack, template: dict[str, object]
    ) -> None:
        result = await generate_draft(pack, template, provider=WrongLLM())
        text = result.sections[0].text
        assert "ничего не должен" not in text
        assert "выдумано" not in text

    @pytest.mark.asyncio
    async def test_section_has_amounts_from_materials(
        self, pack: EvidencePack, template: dict[str, object]
    ) -> None:
        result = await generate_draft(pack, template, provider=WrongLLM())
        text = result.sections[0].text
        assert "150 000" in text
        assert "90 000" in text

    @pytest.mark.asyncio
    async def test_direction_of_payment_is_explicit(
        self, pack: EvidencePack, template: dict[str, object]
    ) -> None:
        """Именно тот дефект, ради которого всё затевалось."""
        result = await generate_draft(pack, template, provider=WrongLLM())
        assert "взыскать с ответчика в пользу истца" in result.sections[0].text

    def test_section_key_is_registered(self) -> None:
        """Ключ раздела обязан быть в списке правильных.

        Иначе правило молча перестанет работать при переименовании
        раздела в шаблоне — и это заметят только по резолюции.
        """
        assert "operative" in RULES_BUILT_SECTIONS


class TestUnrecognisedClaimsAreVisible:
    @pytest.mark.asyncio
    async def test_unknown_requirement_mentioned_in_text(self) -> None:
        """Непознанное требование показывается судье, а не теряется."""
        pack = EvidencePack(case_number="5-1/2019")
        pack.items.append(
            EvidenceItem(
                category="claims",
                text="Истец требует привлечь ответчика к ответственности "
                     "за загрязнение окружающей среды.",
                source_document="исковое заявление.txt",
                source_type="CLAIM",
            )
        )
        template = {
            "sections": [
                {"key": "operative", "name": "РЕШИЛ",
                 "purpose": "", "required_fields": []},
            ]
        }
        result = await generate_draft(pack, template, provider=WrongLLM())
        section = result.sections[0]
        assert section.needs_review
        assert "загрязнение" in section.text

    @pytest.mark.asyncio
    async def test_missing_fee_marks_section_for_review(self) -> None:
        """Пошлина не указана в материалах — раздел требует проверки."""
        pack = EvidencePack(case_number="5-1/2019")
        pack.items.append(
            EvidenceItem(
                category="claims",
                text="Истец требует взыскать задолженность 150000 рублей.",
                source_document="исковое заявление.txt",
                source_type="CLAIM",
            )
        )
        template = {
            "sections": [
                {"key": "operative", "name": "РЕШИЛ",
                 "purpose": "", "required_fields": []},
            ]
        }
        result = await generate_draft(pack, template, provider=WrongLLM())
        assert result.sections[0].needs_review
        assert "ТРЕБУЕТ ПРОВЕРКИ СПЕЦИАЛИСТОМ" in result.sections[0].text


class TestOtherSectionsStillUseModel:
    @pytest.mark.asyncio
    async def test_motivating_still_generated(self, pack: EvidencePack) -> None:
        """Замена касается только резолютивной части."""
        template = {
            "sections": [
                {"key": "operative", "name": "РЕШИЛ",
                 "purpose": "", "required_fields": []},
                {"key": "motivating", "name": "Мотивировочная часть",
                 "purpose": "", "required_fields": []},
            ]
        }
        WrongLLM.calls = []
        result = await generate_draft(pack, template, provider=WrongLLM())

        assert WrongLLM.calls, "остальные разделы должны идти через модель"
        assert len(result.sections) == 2
        assert result.sections[1].key == "motivating"


class TestTimestamps:
    @pytest.mark.asyncio
    async def test_operative_section_has_no_latency(
        self, pack: EvidencePack, template: dict[str, object]
    ) -> None:
        """У раздела, собранного без модели, задержки обращения быть не
        должно: ноль миллисекунд честнее, чем выдуманное время."""
        result = await generate_draft(pack, template, provider=WrongLLM())
        assert result.sections[0].latency_ms == 0
