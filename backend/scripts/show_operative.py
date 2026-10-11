"""Показать резолютивную часть, собранную по правилам, на трёх случаях.

Скрипт существует, чтобы результат можно было увидеть глазами, а не
только по зелёным тестам: судья должен знать, что именно подставит
система в проект решения.

Запуск:
    .venv\\Scripts\\python.exe -X utf8 scripts\\show_operative.py
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.drafting import (  # noqa: E402
    Claimant,
    MoneyClaim,
    Outcome,
    build_operative,
)

OUT = pathlib.Path(
    r"C:\Users\diorl\AppData\Local\Temp\opencode\operative_demo.txt"
)


def main() -> int:
    lines: list[str] = []

    # 1. Обычное дело: полное удовлетворение, частичное, отказ по
    #    отдельному требованию, расходы.
    full = MoneyClaim(
        amount=150000,
        basis="неоплаченная по договору поставки",
        source="договор поставки № 14 от 15.05.2019, чек от 20.06.2019",
    )
    partial = MoneyClaim(
        amount=90000,
        granted_amount=60000,
        basis="неустойка за просрочку оплаты",
        source="расчёт истца от 01.07.2019",
        grounds=(
            "суд не принял во внимание период, по которому просрочка "
            "не наступила"
        ),
        outcome=Outcome.PARTIAL,
    )
    denied = Claimant(
        description="признать недействительным договор поставки",
        source="исковое заявление от 10.05.2019",
        outcome=Outcome.DENIED,
    )

    result = build_operative([full, partial], [denied], fee_paid=5100, costs=15000)
    lines.append("--- ОБЫЧНОЕ ДЕЛО ---")
    lines.append(result.render())
    lines.append("")
    lines.append(f"пропуски: {result.gaps if result.gaps else 'нет'}")
    lines.append("")

    # 2. Требования не установлены: раздел не выдумывается.
    lines.append("--- ТРЕБОВАНИЯ НЕ НАЙДЕНЫ ---")
    lines.append(build_operative([]).render())
    lines.append("")

    # 3. Сумма и пошлина неизвестны: остаются незаполненные места.
    unknown = MoneyClaim(
        amount=None,
        basis="расходы на представителя",
        source="",
    )
    lines.append("--- СУММА И ПОШЛИНА НЕИЗВЕСТНЫ ---")
    lines.append(build_operative([unknown], fee_paid=None).render())
    lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"записано: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
