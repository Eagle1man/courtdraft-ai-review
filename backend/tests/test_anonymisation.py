r"""Обезличивание реальных дел (п. 8 разбора).

Рецензент поймал фамилию в опубликованном деле: court_of обрезал поле
court по первой точке («Синяева И.О.» → «Синяева И»), а между инициалами
и фамилией в подписях стоят неразрывные пробелы, из-за которых паттерн
`\s?` не срабатывал. Скрипты лежат вне backend/, поэтому загружаются
через importlib — как их грузит build_real_cases.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, filename: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"не найден скрипт {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


demo = _load("build_real_demo", "build_real_demo.py")
cases = _load("build_real_cases", "build_real_cases.py")


class TestInitialsAcrossNbsp:
    r"""Подписи судей содержат \xa0 + пробел — один символ \s? не берёт."""

    SIGNED = "Мировой судья Н.Ю.\xa0 Лямин"

    def test_anonymise_removes_surname(self) -> None:
        cleaned = demo.anonymize(self.SIGNED)
        assert "Лямин" not in cleaned
        assert "ФИО" in cleaned

    def test_find_leaks_sees_raw_signature(self) -> None:
        assert demo.find_leaks(self.SIGNED)

    def test_cleaned_text_passes_gate(self) -> None:
        assert demo.find_leaks(demo.anonymize(self.SIGNED)) == []


class TestCourtOf:
    """Поле court уходит в манифест — раньше оно обходило find_leaks."""

    def test_initials_not_cut_by_dot(self) -> None:
        # Старый паттерн рвал строку на первой точке: «Синяева И»
        # оставалось в манифесте и не ловилось ни одним правилом.
        text = (
            "Мировой судья Судебного участка № 44 Самарской области "
            "Синяева И.О., при секретаре ФИО"
        )
        court = cases.court_of(text)
        assert "Синяева" not in court
        assert court.endswith("ФИО")

    def test_mid_word_cut_masked(self) -> None:
        # Лимит окна рвёт слово посередине: обрубок вроде «области Чер»
        # неотличим от настоящего текста, поэтому неполная строка
        # заменяется честной маской, а не публикуется.
        text = "Мировой судья " + "а" * 130 + "Чернышёва И.О."
        assert cases.court_of(text) == "Суд (обезличено)"

    def test_no_court_in_text_masked(self) -> None:
        assert cases.court_of("решение без упоминания судьи") == "Суд (обезличено)"

    def test_safe_court_masks_leak(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Страховка: даже если court_of вернёт фамилию, мимо проверки
        # поле не пройдёт.
        monkeypatch.setattr(
            cases, "court_of", lambda _text: "Мировой судья участка Сидорова И"
        )
        assert cases.safe_court("любой текст") == "Суд (обезличено)"

    def test_safe_court_passes_clean_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        clean = "Мировой судья судебного участка № 1"
        monkeypatch.setattr(cases, "court_of", lambda _text: clean)
        assert cases.safe_court("любой текст") == clean


class TestLeakPatterns:
    """Проверка должна ловить то, что правила не заменили."""

    @pytest.mark.parametrize(
        "raw",
        [
            "Мировой судья Синяева И",
            "Мировой судья участка № 36 Лямин Н",
            "судья: Н.А.Тремасова",
            "Иск Романова<ФИО> к ООО «ДНС»",
        ],
        ids=["один инициал", "фамилия инициал", "без пробела", "метка корпуса"],
    )
    def test_cleaned_text_passes_gate(self, raw: str) -> None:
        assert demo.find_leaks(demo.anonymize(raw)) == []

    @pytest.mark.parametrize(
        "raw",
        ["Мировой судья Синяева И", "подпись Э.Н.Грищенко", "Романова <ФИО1>"],
        ids=["обрубок", "подпись", "фамилия при метке"],
    )
    def test_leak_detected_before_cleaning(self, raw: str) -> None:
        assert demo.find_leaks(raw)
