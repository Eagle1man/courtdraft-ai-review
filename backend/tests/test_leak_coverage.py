"""Покрытие детектора утечек: телефон, e-mail, ИНН, СНИЛС, паспорт (D5).

Скрипт лежит вне backend/, грузится через importlib — как в
test_anonymisation.py.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, filename: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


demo = _load("build_real_demo_leaks", "build_real_demo.py")


def _labels(text: str) -> list[str]:
    return [entry.split(":", 1)[0] for entry in demo.find_leaks(text)]


class TestLeakCoverage:
    def test_phone_detected(self) -> None:
        assert "телефон" in _labels("тел. +7 917 123-45-67")

    def test_phone_local_format_detected(self) -> None:
        assert "телефон" in _labels("звонить: 8-917-123-45-67")

    def test_email_detected(self) -> None:
        assert "e-mail" in _labels("почта истца ivanov@mail.ru")

    def test_inn_detected(self) -> None:
        assert "ИНН/ОГРН" in _labels("ИНН 7701234567")

    def test_snils_detected(self) -> None:
        assert "СНИЛС" in _labels("СНИЛС 123-456-789 01")

    def test_passport_requisites_detected(self) -> None:
        assert "паспортные реквизиты" in _labels("паспорт серия 4501 номер 123456")

    def test_clean_legal_text_not_flagged(self) -> None:
        # Ссылки на кодексы и статьи — не персональные данные.
        assert demo.find_leaks("Руководствуясь ст. 98 ГПК РФ, суд решил.") == []
