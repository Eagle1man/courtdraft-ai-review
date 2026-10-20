"""Оценочная ведомость для юриста (п. 78 разбора рецензента).

Harness собирает три графы — исход, суммы, нормы, — и не оценивает сам.
Тесты держат именно механику: грубые маркеры исхода, извлечение статей,
рублёвых сумм и склейку ведомости. Скрипт лежит вне backend/, поэтому
грузится через importlib — как его грузит build_real_cases.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, filename: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"не найден скрипт {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


harness = _load("eval_harness", "eval_harness.py")


class TestOutcomeMarkers:
    """Маркеры исхода — корни слов, а не точные фразы."""

    def test_partial_satisfaction(self) -> None:
        text = "Удовлетворить исковые требования истца частично, в остальной части отказать."
        found = harness.outcome_of(text)
        assert "частичное удовлетворение" in found
        assert "отказ (в части требований)" in found

    def test_full_satisfaction(self) -> None:
        assert "полное удовлетворение" in harness.outcome_of(
            "Исковые требования истца удовлетворить в полном объёме."
        )

    def test_denial(self) -> None:
        assert "отказ в иске" in harness.outcome_of(
            "В удовлетворении исковых требований оставить без удовлетворения."
        )

    def test_unparsed_is_empty(self) -> None:
        # Неготовный текст не получает маркеров — в ведомости это
        # показывается как «не разобрано», а не подменяется угаданным.
        assert harness.outcome_of("ТРЕБУЕТ ПРОВЕРКИ СПЕЦИАЛИСТОМ") == []


class TestLaws:
    """Статьи: «ст. 98 ГПК РФ», «ст.333.19 НК РФ», «ч. 1 ст. 320-322 ГПК РФ»."""

    def test_basic_extraction(self) -> None:
        laws = harness.laws_in("на основании ст. 98 ГПК РФ взыскать расходы")
        assert "98 ГПК РФ" in laws

    def test_dotted_number_and_mixed_case_code(self) -> None:
        laws = harness.laws_in("штраф по ст. 333.19 НК РФ и ст. 12.15 КоАП РФ")
        assert "333.19 НК РФ" in laws
        assert "12.15 КОАП РФ" in laws

    def test_leading_part_and_range(self) -> None:
        laws = harness.laws_in("ч. 1 ст. 320-322 ГПК РФ не применяется")
        assert "320-322 ГПК РФ" in laws

    def test_duplicate_mentions_collapse(self) -> None:
        laws = harness.laws_in("ст. 98 ГПК РФ, а также ст. 98 ГПК РФ")
        assert list(laws.values()).count("ст. 98 ГПК РФ") == 1

    def test_diff_three_sets(self) -> None:
        system = harness.laws_in("ст. 98 ГПК РФ, ст. 103 ГПК РФ")
        court = harness.laws_in("ст. 98 ГПК РФ, ст. 198 ГПК РФ")
        diff = harness.laws_diff(system, court)
        assert diff["both"] == ["ст. 98 ГПК РФ"]
        assert diff["system_only"] == ["ст. 103 ГПК РФ"]
        assert diff["court_only"] == ["ст. 198 ГПК РФ"]


class TestRubAmounts:
    """Рублёвые суммы: целая часть, копейки — только в контексте."""

    def test_spaced_thousands(self) -> None:
        amounts = harness.rub_amounts("взыскать 11 551 руб. с ответчика")
        assert amounts and amounts[0][0] == 11551

    def test_decimal_keeps_integer_part(self) -> None:
        # «11551,84 руб.» раньше давало 1155184 — вся строка цифр
        # склеивалась вместе с копейками.
        amounts = harness.rub_amounts("взыскать 11551,84 руб.")
        assert amounts and amounts[0][0] == 11551

    def test_kopecks_not_counted_as_rubles(self) -> None:
        amounts = harness.rub_amounts("739 рублей 60 копеек")
        assert [value for value, _context in amounts] == [739]

    def test_context_is_attached(self) -> None:
        amounts = harness.rub_amounts("госпошлину в размере 444 руб. уплачен")
        assert amounts and "444" in amounts[0][1]


class TestFoundIn:
    def test_exact_and_rounding(self) -> None:
        court = [(11551, "…11 551 руб…")]
        assert harness.found_in(11551.0, court)
        assert harness.found_in(11551.84, court)  # копейки — в пределах 1 руб.

    def test_missing(self) -> None:
        assert not harness.found_in(11551.0, [(472, "…472 рубля…")])


def _processed() -> dict[str, Any]:
    """Срез, который process() реально отдаёт (см. build_real_site)."""
    return {
        "rules": {
            "claims": [
                {
                    "amount": 11107.0,
                    "basis": "задолженность по договору",
                    "source": "01_claim.txt",
                }
            ],
            "fee_paid": 444,
            "total": 11107.0,
            "total_with_fee": 11551.0,
        },
        "operative_text": (
            "Удовлетворить исковые требования истца в полном объёме. "
            "Взыскать 11 551 руб., в том числе 444 руб. госпошлины."
        ),
        "verification": {
            "status": "REVIEW_REQUIRED",
            "issues": [
                {
                    "type": "MONEY_MISMATCH",
                    "severity": "significant",
                    "reason": "сумма в резолютивной не совпала с требованием",
                    "section": "operative",
                }
            ],
            "unsupported_claims": 1,
        },
    }


class TestCaseBlock:
    MANIFEST = {
        "category": "взыскание долга",
        "claim_amount": 11107.0,
        "documents": [{"filename": "01_claim.txt"}],
    }
    COURT = (
        "Удовлетворить исковые требования частично. Взыскать 472 рубля. "
        "В остальной части отказать. На основании ст. 98 ГПК РФ."
    )

    def _block(self) -> str:
        return harness.case_block("real-01", self.MANIFEST, _processed(), self.COURT)

    def test_two_sides_of_outcome(self) -> None:
        block = self._block()
        assert "система: полное удовлетворение" in block
        assert "суд: частичное удовлетворение" in block

    def test_amounts_and_number_check(self) -> None:
        block = self._block()
        assert "итог 11107.00 руб. (с пошлиной 11551.00 руб.)" in block
        assert "472 руб." in block  # сумма суда с контекстом
        # Итога 11551 среди сумм суда (472) нет — это факт, не оценка.
        assert "не найден" in block

    def test_law_asymmetry_visible(self) -> None:
        block = self._block()
        assert "только у суда: ст. 98 ГПК РФ" in block

    def test_verification_summary_present(self) -> None:
        block = self._block()
        assert "REVIEW_REQUIRED" in block
        assert "утверждений без источника: 1" in block

    def test_verdict_fields_empty(self) -> None:
        # Ведомость ничего не заключает за оценщика.
        block = self._block()
        assert block.count("- [ ]") >= 9
        assert "### Вывод оценщика" in block

    def test_needs_review_note_when_unparsed(self) -> None:
        processed = _processed()
        processed["operative_text"] = "ТРЕБУЕТ ПРОВЕРКИ СПЕЦИАЛИСТОМ: иск не разобран."
        block = harness.case_block(
            "real-02", self.MANIFEST, processed, "удовлетворить частично."
        )
        assert "не разобрано (пометка о неготовности)" in block
