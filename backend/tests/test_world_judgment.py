"""Шаблон для мирового судьи (п. 11.1 разбора, ч. 3–4 ст. 199 ГПК РФ)."""

import asyncio

import pytest

from app.agents.draft_agent import generate_draft
from app.agents.evidence_pack import EvidenceItem, EvidencePack, load_template


def _pack() -> EvidencePack:
    pack = EvidencePack(case_number="2-1234/2026", court_name="Мировой судья")
    pack.participants.append("Образцов Пётр Петрович (истец)")
    pack.items.append(
        EvidenceItem(
            category="claims",
            text="Взыскать задолженность 150 000 руб.",
            source_document="01_claim.txt",
            source_type="CLAIM",
            order=1,
        )
    )
    return pack


class _NoLLM:
    name = "no-llm"
    model = ""

    async def generate(self, request):  # noqa: ANN001, ANN201
        raise AssertionError("шаблон мирового судьи не должен звать модель")


class TestWorldJudgmentTemplate:
    def test_template_loads(self) -> None:
        template = load_template(name="world_judgment")
        keys = [s["key"] for s in template["sections"]]
        assert keys == ["introductory", "operative"]
        assert "ч. 3–4 ст. 199" in template["notes"]

    def test_draft_has_two_rules_built_sections(self) -> None:
        template = load_template(name="world_judgment")
        result = asyncio.run(generate_draft(_pack(), template, provider=_NoLLM()))
        keys = [s.key for s in result.sections]
        assert keys == ["introductory", "operative"]
        assert all(s.is_mock is False for s in result.sections)

    def test_no_motivating_part_in_text(self) -> None:
        template = load_template(name="world_judgment")
        result = asyncio.run(generate_draft(_pack(), template, provider=_NoLLM()))
        text = result.text
        assert "УСТАНОВИЛ" not in text
        assert "РЕШИЛ" in text

    def test_rejects_bad_name(self) -> None:
        with pytest.raises(ValueError):
            load_template(name="../secret")
        with pytest.raises(FileNotFoundError):
            load_template(name="unknown_template")
