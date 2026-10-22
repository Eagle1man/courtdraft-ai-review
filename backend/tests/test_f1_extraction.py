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
                    "возместить разницу. Истец просит, чтобы требования "
                    "о компенсации морального вреда были удовлетворены."
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
                    "Истец просит взыскать с ответчика в пользу истца "
                    "в счет компенсации морального вреда 1000 руб."
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
                    "Истец просит взыскать с ответчика в пользу истца "
                    "в счет компенсации морального вреда 1000 руб."
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


class TestSumBelongsToItsBasis:
    """Сумма берётся та, что стоит после своего основания.

    В окне с несколькими пунктами первая сумма — соседняя: «взыскать
    долг 5000 руб. и неустойку 1000 руб.» отдавало неустойке 5000,
    а в real-03 сумма неустойки 18 390 доставалась компенсации
    морального вреда (в материалах моральный вред — 30 000).
    """

    def test_own_sum_taken_after_basis(self) -> None:
        # Окно с двумя пунктами: у каждого своё основание и своя сумма.
        # Заметьте: «рублей» без точки — сокращение «руб.» разрывает
        # связь «взыскать … основание» (ограничение _BETWEEN, см.
        # документацию), поэтому разбор идёт по пунктам перечисления.
        pack = _pack()
        pack.items.append(
            EvidenceItem(
                category="claims",
                text=(
                    "Взыскать с ответчика задолженность 5000 рублей "
                    "и неустойку 1000 рублей."
                ),
                source_document="01_claim.txt",
                source_type="CLAIM",
                order=1,
            )
        )
        money, _others, _unrecognised = extract_requirements(pack)
        assert [(claim.basis, claim.amount) for claim in money] == [
            ("задолженность по договору", 5000),
            ("неустойка и санкции", 1000),
        ]

    def test_sum_before_basis_still_found(self) -> None:
        # «взыскать 1000 рублей в возмещение убытков»: сумма стоит до
        # основания — берётся первая в окне, иначе сумма терялась бы.
        pack = _pack()
        pack.items.append(
            EvidenceItem(
                category="claims",
                text="Взыскать 1000 рублей в возмещение убытков.",
                source_document="01_claim.txt",
                source_type="CLAIM",
                order=1,
            )
        )
        money, _others, _unrecognised = extract_requirements(pack)
        assert [(claim.basis, claim.amount) for claim in money] == [
            ("убытки", 1000)
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
            "real-08": ("убытки", 10400),
            # real-03: моральному вреду достаётся своя сумма из иска
            # (30 000), а не сумма соседнего пункта (неустойка 18 390).
            "real-03": ("компенсация морального вреда", 30000),
            # real-05: моральный вред 10 000 — это требование истца из
            # протокола. Сумма 1 000 из 01_claim.txt относится к
            # определению суда («суд считает необходимым взыскать …»)
            # и требованием истца не является.
            "real-05": ("компенсация морального вреда", 10000),
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


class TestSeveralClaimsInOneWindow:
    """В одном окне перечислены несколько требований.

    Разбор окна целиком давал одно основание, и остальные суммы
    терялись: в real-03 не была извлечена неустойка 18 390, в
    real-04 — стоимость товара 10 490 и услуги представителя 7 000.
    """

    @staticmethod
    def _money(case: str) -> dict[str, int | None]:
        import importlib.util
        import sys

        spec = importlib.util.spec_from_file_location(
            "clt_build_real_site", ROOT / "scripts" / "build_real_site.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["clt_build_real_site"] = module
        spec.loader.exec_module(module)

        case_dir = CASES / case
        if not (case_dir / "01_claim.txt").exists():
            pytest.skip(f"локальные материалы {case} отсутствуют")
        settings = module.make_settings(case_dir)
        settings.ensure_dirs()
        pack = module.build_pack(case_dir, settings)
        money, _others, _unrecognised = extract_requirements(pack)
        return {claim.basis: claim.amount for claim in money}

    def test_real_03_penalty_and_moral_damage(self) -> None:
        # В иске real-03 просят 18 390 неустойкой и 30 000 моральным
        # вредом; обе суммы — из текста иска.
        found = self._money("real-03")
        assert found.get("неустойка и санкции") == 18390
        assert found.get("компенсация морального вреда") == 30000

    def test_real_04_enumerated_demands(self) -> None:
        # Протокол real-04: стоимость товара 10 490, неустойка 2 202
        # руб. 90 коп., моральный вред 10 000, услуги 7 000.
        found = self._money("real-04")
        assert found.get("задолженность по договору") == 10490
        assert found.get("неустойка и санкции") == 2202
        assert found.get("компенсация морального вреда") == 10000
        assert found.get("расходы на представителя") == 7000

    def test_real_06_penalty_moral_damage_and_losses(self) -> None:
        # Протокол real-06: стоимость телефона 6 890, неустойка 6 890,
        # моральный вред 7 000, убытки (кредит) 3 000, расходы на
        # юридические услуги и представительство 9 000.
        found = self._money("real-06")
        assert found.get("задолженность по договору") == 6890
        assert found.get("неустойка и санкции") == 6890
        assert found.get("компенсация морального вреда") == 7000
        assert found.get("убытки") == 3000
        assert found.get("расходы на представителя") == 9000

    def test_amount_of_neighbour_basis_not_taken(self) -> None:
        # «убытки, неустойку в сумме 2202 рублей»: у следующего
        # пункта своё основание — склеивать нельзя, сумма досталась бы
        # чужим требованиям.
        pack = _pack()
        pack.items.append(
            EvidenceItem(
                category="claims",
                text="Взыскать убытки и неустойку в сумме 2202 рублей.",
                source_document="01_claim.txt",
                source_type="CLAIM",
                order=1,
            )
        )
        money, _others, _unrecognised = extract_requirements(pack)
        amounts = {claim.basis: claim.amount for claim in money}
        assert amounts.get("неустойка и санкции") == 2202
        assert amounts.get("убытки") is None
