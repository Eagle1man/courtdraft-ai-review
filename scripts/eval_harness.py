"""Оценочная ведомость для юриста (п. 78 разбора рецензента).

Рецензент: «Оценка качества на 20–30 делах с известным итогом: совпал ли
исход, суммы, применённые нормы. Целесообразно привлечь практикующих
юристов или студентов магистратуры под руководством преподавателя».

Система сама себя не оценивает. Скрипт собирает ведомость, где рядом
лежат три факта — как их увидела система и как их записал суд, — и
пустые графы для человека. «Совпало / не совпало» определяет оценщик:
совпадение суммы не доказывает правильного исхода, а его несовпадение
— ещё не ошибка (суд может отказать в обоснованной части).

Что скрипт считает сам:

- исход — маркеры по корням в обеих резолютивных («частичн», «полном
  объёме», «без удовлетворени», «отказать»). Грубая разметка для сверки,
  а не вывод о правоте сторон; неразобранное так и показывается;
- суммы: итог системы и все рублёвые суммы решения суда с контекстом,
  плюс чистое число-на-число «итог найден среди сумм суда»;
- нормы: статьи с каждой стороны и разность множеств;
- замечания проверки — справочно, чтобы оценщик видел, что система
  сама отметила неготовность.

Модель не вызывается: конвейер правил, тот же, что в
scripts/build_real_site.py, — десять дел гоняются за секунды.

Запуск:
    backend/.venv/Scripts/python.exe scripts/eval_harness.py
    ... --force            перезаписать незаполненную ведомость
    ... --out <путь>       куда писать
Больше дел: scripts/build_real_cases.py --count 30 (корпус с диска).
Выход по умолчанию: data/eval/eval_worksheet.md — в git не входит.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "data" / "eval" / "eval_worksheet.md"

#: Маркеры исхода: корень — первое, второе — как показывать в ведомости.
#: Корни, а не точные фразы: падежи и порядок слов в решениях разъезжаются.
OUTCOME_MARKERS: tuple[tuple[str, str], ...] = (
    ("частичн", "частичное удовлетворение"),
    ("в полном объёме", "полное удовлетворение"),
    ("полностью", "полное удовлетворение"),
    ("без удовлетворени", "отказ в иске"),
    ("отказать", "отказ (в части требований)"),
    ("признать", "признание требования"),
    ("обязать", "обязательство для стороны"),
)

#: «ст. 98 ГПК РФ», «ст.333.19 НК РФ», «ч. 1 ст. 320-322 ГПК РФ».
LAW_RE = re.compile(
    r"ст\.\s*(\d+(?:\.\d+)*(?:\s*[-–]\s*\d+)*)\s+"
    r"([А-ЯЁ][А-ЯЁа-яё]{1,}(?:\s+[А-ЯЁ][А-ЯЁа-яё]{1,})?)"
)

#: Рублёвые суммы: «11 551 руб.», «472 рубля», «11551,84 руб.».
#: Копейки после запятой в значение не входят — считается целая часть,
#: копейки видны в контексте. Иначе «11551,84» давало бы 1155184.
RUB_RE = re.compile(r"(\d[\d\s ]{0,20}[.,]?\d{0,2})\s*(?:рубл\w*|руб\.?)", re.I)

NEEDS_REVIEW = "ТРЕБУЕТ ПРОВЕРКИ СПЕЦИАЛИСТОМ"


def _load(name: str, filename: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"не найден скрипт {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def outcome_of(text: str) -> list[str]:
    """Какие маркеры исхода нашлись в резолютивной части."""
    lowered = text.lower()
    found: list[str] = []
    for root, label in OUTCOME_MARKERS:
        if root in lowered and label not in found:
            found.append(label)
    return found


def laws_in(text: str) -> dict[str, str]:
    """Статьи, упомянутые в тексте: ключ вида «98 ГПК РФ» -> как в тексте."""
    laws: dict[str, str] = {}
    for match in LAW_RE.finditer(text):
        number = re.sub(r"\s+", "", match.group(1))
        code = re.sub(r"\s+", " ", match.group(2).strip())
        key = f"{number} {code}".upper()
        laws.setdefault(key, f"ст. {number} {code}")
    return laws


def laws_diff(system: dict[str, str], court: dict[str, str]) -> dict[str, list[str]]:
    """Разность множеств статей: общие, только у системы, только у суда."""
    return {
        "both": sorted(system[key] for key in system.keys() & court.keys()),
        "system_only": sorted(system[key] for key in system.keys() - court.keys()),
        "court_only": sorted(court[key] for key in court.keys() - system.keys()),
    }


def rub_amounts(text: str) -> list[tuple[int, str]]:
    """Все рублёвые суммы с куском текста вокруг — для сверки человеком.

    Роль суммы (пошлина, ущерб, итог) скрипт не определяет: в чужом
    решении это можно только угадать, а угаданное в ведомости обманет
    оценщика. Роль читается по контексту.
    """
    amounts: list[tuple[int, str]] = []
    for match in RUB_RE.finditer(text):
        integer = re.split(r"[.,]", match.group(1), maxsplit=1)[0]
        digits = re.sub(r"[^\d]", "", integer)
        if not digits:
            continue
        context = re.sub(r"\s+", " ", text[max(0, match.start() - 40) : match.end() + 24])
        amounts.append((int(digits), context.strip()))
    return amounts


def found_in(value: float, amounts: list[tuple[int, str]]) -> bool:
    """Есть ли точное число среди сумм решения суда (число на число)."""
    target = int(round(value))
    return any(abs(amount - target) <= 1 for amount, _context in amounts)


def _checkbox_lines(options: tuple[str, ...]) -> list[str]:
    """Галочки отдельными строками: в Markdown подпункт списка рендерится,
    а те же галочки на одной строке — просто текст."""
    return [f"  - [ ] {option}" for option in options]


def case_block(
    slug: str,
    manifest: dict[str, Any],
    processed: dict[str, Any],
    court_text: str,
) -> str:
    """Ведомость по одному делу: три графы и пустой вывод оценщика."""
    rules = processed["rules"]
    system_text = processed.get("operative_text", "")
    verification = processed.get("verification", {})

    lines: list[str] = []
    lines.append(f"## {slug} — {manifest.get('category', '—')}")
    lines.append(
        f"Иск: {float(manifest.get('claim_amount') or 0):.0f} руб. · "
        f"документов: {len(manifest.get('documents', []))}"
    )
    lines.append("")

    # ── Исход ────────────────────────────────────────────────────────
    lines.append("### Исход")
    system_outcome = outcome_of(system_text)
    court_outcome = outcome_of(court_text)
    if not system_outcome:
        system_outcome = ["не разобрано" + (" (пометка о неготовности)" if NEEDS_REVIEW in system_text else "")]
    if not court_outcome:
        court_outcome = ["не разобрано"]
    lines.append(f"- система: {'; '.join(system_outcome)}")
    lines.append(f"- суд: {'; '.join(court_outcome)}")
    lines.append("- оценка:")
    lines.extend(_checkbox_lines(("совпал", "не совпал", "не определено")))
    lines.append("")

    # ── Суммы ────────────────────────────────────────────────────────
    lines.append("### Суммы")
    claims = rules.get("claims", [])
    lines.append(
        f"- система: требования {len(claims)} шт., пошлина "
        f"{float(rules.get('fee_paid') or 0):.0f} руб., итог "
        f"{float(rules.get('total') or 0):.2f} руб. "
        f"(с пошлиной {float(rules.get('total_with_fee') or 0):.2f} руб.)"
    )
    for claim in claims:
        lines.append(
            f"    - {float(claim.get('amount') or 0):.2f} руб. — "
            f"{claim.get('basis') or 'без основания'}"
            + (f" ({claim['source']})" if claim.get("source") else "")
        )
    court_amounts = rub_amounts(court_text)
    if court_amounts:
        lines.append("- суд (все суммы резолютивной, с контекстом):")
        for amount, context in court_amounts:
            lines.append(f"    - {amount} руб. — «…{context}…»")
    else:
        lines.append("- суд: рублёвых сумм в резолютивной не найдено")
    total_ok = found_in(float(rules.get("total_with_fee") or 0), court_amounts)
    claim_ok = found_in(float(manifest.get("claim_amount") or 0), court_amounts)
    lines.append(
        f"- число на число: итог системы среди сумм суда — "
        f"{'НАЙДЕН' if total_ok else 'не найден'}; "
        f"сумма иска — {'НАЙДЕНА' if claim_ok else 'не найдена'}"
    )
    lines.append("- оценка:")
    lines.extend(_checkbox_lines(("верно", "частично", "неверно")))
    lines.append("")

    # ── Нормы ────────────────────────────────────────────────────────
    lines.append("### Нормы")
    diff = laws_diff(laws_in(system_text), laws_in(court_text))
    lines.append(f"- совпали: {', '.join(diff['both']) or '—'}")
    lines.append(f"- только у системы: {', '.join(diff['system_only']) or '—'}")
    lines.append(f"- только у суда: {', '.join(diff['court_only']) or '—'}")
    lines.append("- оценка:")
    lines.extend(_checkbox_lines(("верно", "частично", "неверно")))
    lines.append("")

    # ── Справочно и вывод ────────────────────────────────────────────
    issues = verification.get("issues", [])
    by_severity: dict[str, int] = {}
    for issue in issues:
        by_severity[issue["severity"]] = by_severity.get(issue["severity"], 0) + 1
    severity_text = ", ".join(
        f"{level}: {count}" for level, count in sorted(by_severity.items())
    )
    lines.append("### Справочно: что отметила сама система")
    lines.append(
        f"статус {verification.get('status', '—')} · замечаний {len(issues)} "
        + (f"({severity_text})" if severity_text else "")
        + f" · утверждений без источника: {verification.get('unsupported_claims', 0)}"
    )
    for issue in issues[:5]:
        lines.append(f"- [{issue['severity']}] {issue['reason'][:220]}")
    if len(issues) > 5:
        lines.append(f"- … и ещё {len(issues) - 5}")
    lines.append("")
    lines.append("### Вывод оценщика")
    lines.append("ФИО / роль (юрист, студент магистратуры), дата: ______________")
    lines.append("")
    lines.append(
        "Общий вывод по делу (суммы и исход сошлись ли по существу, "
        "что система упустила):"
    )
    lines.append("")
    lines.append("______________________________________________________________")
    lines.append("")
    return "\n".join(lines)


HEADER = """# Оценочная ведомость по делам (п. 78 разбора рецензента)

Генератор: scripts/eval_harness.py. Дата сборки: {date}. Дел: {count}.

Как заполнять:

- три графы на дело — исход, суммы, нормы. Слева — как увидела система
  (правила, без модели), справа/выше — как записано в решении суда;
- «число на число» и множества статей — механика, не оценка: совпадение
  суммы не доказывает правильного исхода, а его несовпадение — ещё не
  ошибка системы;
- решение «совпал / не совпал» принимает оценщик, а не скрипт;
- маркеры исхода грубые (корни слов): если стоит «не разобрано»,
  решение читается вручную;
- графа «Вывод оценщика» обязательна — без неё дело не считается
  оценённым.

Подробности запуска и расширения выборки: docs/evaluation.md.
Результат не является юридическим заключением.

"""


async def build_worksheet(cases_dir: Path) -> tuple[str, int]:
    harness = _load("eval_build_real_site", "build_real_site.py")
    index_path = cases_dir / "index.json"
    if not index_path.exists():
        raise FileNotFoundError(f"нет {index_path}: сначала scripts/build_real_cases.py")
    index = json.loads(index_path.read_text(encoding="utf-8"))

    parts: list[str] = []
    done = 0
    for entry in index["cases"]:
        slug = entry["slug"]
        case_dir = cases_dir / slug
        try:
            processed = await harness.process(case_dir)
        except Exception as exc:  # noqa: BLE001
            parts.append(
                f"## {slug}\n\nНе посчитан: {type(exc).__name__}: {exc}\n"
            )
            continue
        manifest = json.loads((case_dir / "manifest.json").read_text(encoding="utf-8"))
        court_text = (case_dir / "court_decision_reference.txt").read_text(
            encoding="utf-8"
        )
        parts.append(case_block(slug, manifest, processed, court_text))
        done += 1

    header = HEADER.format(
        date=datetime.now().strftime("%Y-%m-%d %H:%M"), count=done
    )
    return header + "\n".join(parts), done


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ведомость оценки для юриста")
    parser.add_argument(
        "--out", default=str(DEFAULT_OUT), help="куда писать ведомость"
    )
    parser.add_argument(
        "--force", action="store_true", help="перезаписать существующий файл"
    )
    parser.add_argument(
        "--cases-dir",
        default=str(ROOT / "data" / "demo" / "real" / "cases"),
        help="каталог дел",
    )
    args = parser.parse_args(argv)

    out = Path(args.out)
    if out.exists() and not args.force:
        print(f"УЖЕ ЕСТЬ: {out} — не затираю заполненную оценку ( --force )")
        return 1

    text, done = asyncio.run(build_worksheet(Path(args.cases_dir)))
    if not done:
        print("ОШИБКА: ни одно дело не посчитано")
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"дел в ведомости: {done}\nфайл: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
