"""Регрессионные тесты F1: извлечение сумм, топящихся пошлиной и окнами.

Два механизма потери суммы, найденных при сквозной проверке (Этап 2 ТЗ):

* пошлина, стоящая в одном предложении с требованием, прежде
  пропускала всё окно целиком — в real-08 вместе с «госпошлиной в
  размере 416 руб.» терялся ущерб 10 400 руб.;
* окно базы без суммы занимало базу навсегда — в real-05 фраза
  «требования истца о компенсации морального вреда являются
  обоснованными» (без числа) стояла раньше окна с «взыскать …
  1000 руб.», и сумма не вставлялась.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.evidence_pack import EvidenceItem, EvidencePack
from app.drafting.requirements import extract_requirements

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "data" / "demo" / "real" / "cases"


def _pack() -> EvidencePack:
    return EvidencePack(case_number="T-F1")


class TestFeeDoesNotSwallowClaim:
    def test_fee_fragment_removed_claim_kept(self) -> None:
        pack = _pack()
        pack.items.append(
            EvidenceItem(
                category="claims",
                text=(
                    "Просит взыскать с ответчика ФИО материальный ущерб "
                    "в размере 10400 руб., расходы по оплате госпошлины "
                    "в размере 416 руб."
                ),
                source_document="01_claim.txt",
                source_type="CLAIM",
                order=1,
            )
        )
        money, _others, _unrecognised = extract_requirements(pack)
        assert [(claim.basis, claim.amount) for claim in money] == [
            ("убытки", 10400)
        ]

    def test_fee_without_separator_keeps_claim(self) -> None:
        # D1: раньше жадная голова regexp съедала всё от начала окна,
        # если перед пошлиной не было запятой — «взыскать госпошлину и
        # ущерб 10400 руб.» пропадало целиком и молча.
        pack = _pack()
        pack.items.append(
            EvidenceItem(
                category="claims",
                text="Взыскать госпошлину и ущерб 10400 руб.",
                source_document="01_claim.txt",
                source_type="CLAIM",
                order=1,
            )
        )
        money, _others, unrecognised = extract_requirements(pack)
        assert [(claim.basis, claim.amount) for claim in money] == [
            ("убытки", 10400)
        ]
        assert unrecognised == []

    def test_fee_payment_form_keeps_debt(self) -> None:
        # D3 (форма «расходы по уплате … пошлины» не вырезалась
        # общим regexp и топила окно целиком).
        pack = _pack()
        pack.items.append(
            EvidenceItem(
                category="claims",
                text=(
                    "Взыскать долг 5000 руб., расходы по уплате "
                    "государственной пошлины в размере 400 руб."
                ),
                source_document="01_claim.txt",
                source_type="CLAIM",
                order=1,
            )
        )
        money, _others, _unrecognised = extract_requirements(pack)
        assert [(claim.basis, claim.amount) for claim in money] == [
            ("задолженность по договору", 5000)
        ]

    def test_court_costs_form_keeps_claim(self) -> None:
        # D3 (форма «судебные расходы» в перечислении после «а также»).
        pack = _pack()
        pack.items.append(
            EvidenceItem(
                category="claims",
                text=(
                    "Просит взыскать с ответчика материальный ущерб в "
                    "размере 10400 руб., а также судебные расходы на "
                    "оплату экспертизы в размере 6000 руб."
                ),
                source_document="01_claim.txt",
                source_type="CLAIM",
                order=1,
            )
        )
        money, _others, _unrecognised = extract_requirements(pack)
        assert [(claim.basis, claim.amount) for claim in money] == [
            ("убытки", 10400)
        ]

    def test_fee_only_window_still_skipped(self) -> None:
        pack = _pack()
        pack.items.append(
            EvidenceItem(
                category="claims",
                text="Истец просит взыскать госпошлину в размере 416 руб.",
                source_document="01_claim.txt",
                source_type="CLAIM",
                order=1,
            )
        )
        money, _others, unrecognised = extract_requirements(pack)
        assert money == []
        # чисто пошлинное окно не загромождает непознанное
        assert unrecognised == []


class TestSumlessWindowDoesNotBlock:
    def test_later_window_with_sum_upgrades_amount(self) -> None:
        pack = _pack()
        pack.items.append(
            EvidenceItem(
                category="claims",
                text=(
                    "Потерпевший вновь обратился к ответчику с требованием "
                    "возместить разницу. Суд считает, что требования истца "
                    "о компенсации морального вреда являются обоснованными."
                ),
                source_document="01_claim.txt",
                source_type="CLAIM",
                order=1,
            )
        )
        pack.items.append(
            EvidenceItem(
                category="claims",
                text=(
                    "Суд считает необходимым взыскать с ответчика в пользу "
                    "истца в счет компенсации морального вреда 1000 руб."
                ),
                source_document="01_claim.txt",
                source_type="CLAIM",
                order=2,
            )
        )
        money, _others, _unrecognised = extract_requirements(pack)
        assert [(claim.basis, claim.amount) for claim in money] == [
            ("компенсация морального вреда", 1000)
        ]

    def test_existing_amount_not_overwritten_by_none(self) -> None:
        # Сумма, найденная по настоящему, не сбрасывается пустым окном:
        # порядок окон в потоке не гарантия качества суммы.
        pack = _pack()
        pack.items.append(
            EvidenceItem(
                category="claims",
                text=(
                    "Суд считает необходимым взыскать с ответчика в пользу "
                    "истца в счет компенсации морального вреда 1000 руб."
                ),
                source_document="01_claim.txt",
                source_type="CLAIM",
                order=1,
            )
        )
        pack.items.append(
            EvidenceItem(
                category="claims",
                text=(
                    "Требования истца о компенсации морального вреда "
                    "обоснованы, о возмещении истцом природных ценностей "
                    "возмещать нечего."
                ),
                source_document="01_claim.txt",
                source_type="CLAIM",
                order=2,
            )
        )
        money, _others, _unrecognised = extract_requirements(pack)
        assert [(claim.basis, claim.amount) for claim in money] == [
            ("компенсация морального вреда", 1000)
        ]


class TestRealCases:
    """Живые материалы: суммы, которые прежде терялись."""

    def test_real_fee_and_amount_extracted(self) -> None:
        import importlib.util
        import sys

        spec = importlib.util.spec_from_file_location(
            "f1t_build_real_site", ROOT / "scripts" / "build_real_site.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["f1t_build_real_site"] = module
        spec.loader.exec_module(module)

        expected = {
            "real-05": ("компенсация морального вреда", 1000),
            "real-08": ("убытки", 10400),
        }
        for slug, (basis, amount) in expected.items():
            case_dir = CASES / slug
            if not (case_dir / "01_claim.txt").exists():
                pytest.skip(f"локальные материалы {slug} отсутствуют")
            settings = module.make_settings(case_dir)
            settings.ensure_dirs()
            pack = module.build_pack(case_dir, settings)
            money, _others, _unrecognised = extract_requirements(pack)
            found = {claim.basis: claim.amount for claim in money}
            assert found.get(basis) == amount, f"{slug}: {found}"
