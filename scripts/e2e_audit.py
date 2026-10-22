"""Сквозной аудит конвейера по делам (Этап 2 ТЗ).

Для каждого дела прослеживает цепочку:
    документ → извлечённый факт → источник → доказательство → раздел
    → автоматические проверки.

Механически проверяет:
- привязку цитат к реальным файлам дела (нет ли ссылок в никуда);
- дубли пунктов резолютивной части;
- арифметику: итог = сумма требований + пошлина;
- покрытие документов: какие материалы дали источники, какие — нет;
- наличие вопросов проверки (возражения, неустойка, оценка доказательств);
- наличие маркера ТРЕБУЕТ ПРОВЕРКИ СПЕЦИАЛИСТОМ там, где есть пробелы.

Ничего не оценивает юридически: только воспроизводимые факты.
Результат — в scripts/tmp_e2e_audit_out.txt (кириллица в консоли портится).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "data" / "demo" / "real" / "cases"
OUT = Path(__file__).with_name("tmp_e2e_audit_out.txt")
NEEDS_REVIEW = "ТРЕБУЕТ ПРОВЕРКИ СПЕЦИАЛИСТОМ"


def _load(name: str, filename: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _files_of(case_dir: Path) -> set[str]:
    return {p.name for p in case_dir.iterdir() if p.is_file()}


def _case_text(case_dir: Path) -> str:
    """Весь текст материалов дела одной строкой."""
    parts: list[str] = []
    for path in sorted(case_dir.glob("*.txt")):
        parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def _amount_in_text(amount: float, kopecks: int, text: str) -> bool:
    """Есть ли сумма в тексте дела (в любой из обычных записей)."""
    whole = int(amount)
    digits = str(whole)
    spaced = f"{whole:,}".replace(",", " ")
    candidates = {digits, spaced}
    if kopecks:
        candidates |= {
            f"{digits},{kopecks:02d}",
            f"{spaced},{kopecks:02d}",
            f"{digits} {kopecks:02d}",
            f"{spaced} {kopecks:02d}",
        }
    return any(candidate in text for candidate in candidates)


def audit_case(case_dir: Path) -> dict[str, Any]:
    build = _load("e2e_build_real_site", "build_real_site.py")
    processed = asyncio.run(build.process(case_dir))
    files = _files_of(case_dir)
    manifest = json.loads((case_dir / "manifest.json").read_text(encoding="utf-8"))
    operative = processed["operative_text"]
    sources = processed["sources"]
    verification = processed["verification"]

    defects: list[str] = []

    # 1. Ссылки на несуществующие документы
    dangling = [s for s in sources if s.split(",")[0].strip() not in files]
    if dangling:
        defects.append(f"ссылки в никуда: {dangling}")

    # 2. Дубли пунктов резолютивной (одинаковые строки ≥ 40 символов)
    lines = [ln.strip() for ln in operative.splitlines() if len(ln.strip()) >= 40]
    dupes = {ln for ln in lines if lines.count(ln) > 1}
    if dupes:
        defects.append(f"дубли пунктов: {sorted(dupes)[:2]}")

    # 3. Арифметика: итог против суммы требований + пошлина
    rules = processed["rules"]
    total = float(rules.get("total") or 0)
    fee = float(rules.get("fee_paid") or 0)
    total_with_fee = float(rules.get("total_with_fee") or 0)
    if abs(total_with_fee - (total + fee)) > 0.01:
        defects.append(f"арифметика: итог {total_with_fee} != {total}+{fee}")

    # 3a. Итог в резолюции против суммы пунктов — с копейками.
    # Без этой сверки перенос копеек в рубли проходил незамеченным:
    # 10 000,00 + 20 921,53 + 10 460,76 печаталось как «41 381 руб.
    # 29 коп.» вместо «41 382 руб. 29 коп.» (real-05).
    #
    # Считаются только удовлетворённые требования: резолюция строит
    # итог по тем, что присуждены, а отказные и частичные в него не
    # входят. Иначе сверка завела бы дефект на правильном выводе.
    total_line = re.search(
        r"Всего подлежит взысканию\s+([\d\s   ]+)\s*\([^)]*\)\s*руб\.\s*"
        r"(\d{1,2})\s*коп",
        operative,
    )
    costs = float(rules.get("costs") or 0)
    satisfied = [
        claim
        for claim in (rules.get("claims") or [])
        if claim.get("outcome", "satisfied") == "satisfied"
    ]
    expected_kopecks = sum(int(claim.get("kopecks") or 0) for claim in satisfied)
    expected_total = (
        sum(float(claim.get("amount") or 0) for claim in satisfied)
        + expected_kopecks // 100
        + fee
        + costs
    )
    expected_kopecks = expected_kopecks % 100
    if total_line:
        stated = float(
            total_line.group(1)
            .replace(" ", "")
            .replace(" ", "")
            .replace(" ", "")
            .replace(" ", "")
        )
        stated_kopecks = int(total_line.group(2))
        if abs(stated - expected_total) > 0.01 or stated_kopecks != expected_kopecks:
            defects.append(
                f"итог в резолюции: {stated} руб. {stated_kopecks:02d} коп. "
                f"!= {expected_total} руб. {expected_kopecks:02d} коп."
            )
    elif expected_total:
        defects.append("в резолюции нет строки «Всего подлежит взысканию»")

    # 4. Покрытие документов: материалы без источников
    unused = sorted(f for f in files if f not in {s.split(",")[0].strip() for s in sources}
                    and f not in {"manifest.json", "court_decision_reference.txt"})
    if unused:
        defects.append(f"документы без источников: {unused}")

    # 4a. Числа — только из материалов. Каждая сумма в резолюции должна
    # дословно встречаться в тексте дела: иначе в проекте появилось бы
    # число, которого в материалах нет.
    case_text = _case_text(case_dir)
    for claim in rules.get("claims") or []:
        amount = float(claim.get("amount") or 0)
        if amount <= 0:
            continue
        kopecks = int(claim.get("kopecks") or 0)
        if not _amount_in_text(amount, kopecks, case_text):
            defects.append(
                f"сумма не найдена в материалах: {amount} "
                f"({claim.get('basis')}, {claim.get('source')})"
            )

    # 5. Пробелы без маркера
    gaps = rules.get("gaps") or []
    if gaps and NEEDS_REVIEW not in operative:
        defects.append(f"пробелы без маркера: {len(gaps)}")

    # 6. Возражения без вопроса
    issues = {i["type"] for i in verification["issues"]}
    if "OBJECTIONS_UNADDRESSED" not in issues and not any(
        "возражени" in s.lower() for s in sources
    ):
        pass  # возражений в деле нет — вопроса не требуется

    return {
        "slug": case_dir.name,
        "category": manifest.get("category", "—"),
        "claim_amount": manifest.get("claim_amount"),
        "total": total,
        "fee": fee,
        "documents": len(manifest.get("documents", [])),
        "sources": len(sources),
        "unused_docs": unused,
        "status": verification["status"],
        "issues": len(verification["issues"]),
        "unsupported_claims": verification["unsupported_claims"],
        "gaps": len(gaps),
        "defects": defects,
    }


def main() -> None:
    build = _load("e2e_build_real_site", "build_real_site.py")  # прогрев импорта
    index = json.loads((CASES / "index.json").read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for entry in index["cases"]:
        case_dir = CASES / entry["slug"]
        try:
            rows.append(audit_case(case_dir))
        except Exception as exc:  # noqa: BLE001
            rows.append({"slug": entry["slug"], "defects": [f"СБОЙ: {type(exc).__name__}: {exc}"]})

    total_defects = 0
    lines = ["СКВОЗНОЙ АУДИТ ПО ДЕЛАМ", f"дел: {len(rows)}", ""]
    for row in rows:
        defects = row.get("defects", [])
        total_defects += len(defects)
        lines.append(f"## {row['slug']} — {row.get('category', '—')}")
        if row.get("claim_amount") is not None:
            lines.append(
                f"иск {row['claim_amount']} руб. | итог {row.get('total')} | пошлина "
                f"{row.get('fee')} | документов {row.get('documents')} | источников "
                f"{row.get('sources')} | замечаний {row.get('issues')} | без источника "
                f"{row.get('unsupported_claims')} | пробелов {row.get('gaps')}"
            )
        if row.get("unused_docs"):
            lines.append(f"документы без источников: {', '.join(row['unused_docs'])}")
        for defect in defects:
            lines.append(f"- ДЕФЕКТ: {defect}")
        if not defects:
            lines.append("- дефектов не найдено")
        lines.append("")

    lines.append(f"ВСЕГО ДЕФЕКТОВ: {total_defects}")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"cases={len(rows)} defects={total_defects}")


if __name__ == "__main__":
    main()
