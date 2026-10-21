"""Ведомость разметки направлений QD-Court для юриста.

Что размечается: направления (B) и гипотезы (C) по каждому из 10 дел —
длинные метрики из scripts/qd_court_eval.py бесполезны без текстов.
Разметка отвечает только на один вопрос: помогает ли направление
судье найти проверяемый вопрос по материалам дела. Юридическую
валидность направления разметка не подтверждает — это отдельная
оценка юриста на 20–30 делах (docs/evaluation.md).

Ведомость — коммитится (data/eval/); архив гипотез
(data/exploration/_eval/) в git не идёт и пересобирается прогоном.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "data" / "demo" / "real" / "cases"
EVAL_ROOT = ROOT / "data" / "exploration" / "_eval"
SHEET = ROOT / "data" / "eval" / "qd_labeling_sheet.md"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    import shutil

    shutil.rmtree(EVAL_ROOT, ignore_errors=True)  # свежий архив на каждый прогон
    build = _load("qdl_build_real_site", "build_real_site.py")
    from app.exploration import ExplorationBudget, ExplorationService
    from app.exploration.proposer import DirectionProposer
    from app.exploration.verification import HypothesisVerifier

    proposer = DirectionProposer()
    verifier = HypothesisVerifier()
    index = json.loads((CASES / "index.json").read_text(encoding="utf-8"))

    lines: list[str] = [
        "# Ведомость разметки направлений QD-Court",
        "",
        "Заполняет юрист. Одна строка — одно направление системы.",
        "",
        "**Шкала в колонке «Оценка юриста»** (и только эти значения):",
        "",
        "- `полезно` — направление помогает найти проверяемый вопрос по",
        "  материалам дела (что стоит проверить, где искать);",
        "- `не полезно` — вопрос тривиален, очевиден из описания дела или",
        "  не ведёт ни к чему проверяемому;",
        "- `не относится` — направление вне предмета данного дела.",
        "",
        "Колонку «Комментарий» заполнять только для «не полезно» и",
        "«не относится» — одной фразой.",
        "",
        "Важно: оценивается **полезность направления как ориентира судье**,",
        "не юридическая правильность вывода. Система выводы не делает",
        "(принцип: решает судья), поэтому «верно/неверно юридически» —",
        "это другая проверка (docs/evaluation.md, 20–30 дел).",
        "",
        "Режим B — генерация без архива (без фильтра новизны, повторы",
        "возможны); режим C — QD-Court (архив, мутации, novelty). Один и",
        "тот же случай может иметь похожие направления в обоих режимах —",
        "размечать каждое отдельно, схожие оценивать одинаково.",
        "",
        "| # | Дело | Режим | ID | Направление | Статус системы | Оценка юриста | Комментарий |",
        "|---|---|---|---|---|---|---|---|",
    ]

    counter = 0
    for entry in index["cases"]:
        slug = entry["slug"]
        case_dir = CASES / slug
        settings = build.make_settings(case_dir)
        settings.ensure_dirs()
        pack = build.build_pack(case_dir, settings)

        for candidate in proposer.explore(pack):
            counter += 1
            verified = verifier.verify(candidate, pack)
            text = str(getattr(candidate, "text", candidate)).replace("|", "\\|")
            lines.append(
                f"| {counter} | {slug} | B | {getattr(candidate, 'id', '?')} "
                f"| {text} | {verified.status.value} | | |"
            )

        service = ExplorationService(EVAL_ROOT, ExplorationBudget())
        report = service.run(slug, pack)
        for hypothesis in report.hypotheses:
            counter += 1
            text = hypothesis.text.replace("|", "\\|")
            lines.append(
                f"| {counter} | {slug} | C | {hypothesis.id} "
                f"| {text} | {hypothesis.status.value} | | |"
            )

    lines += [
        "",
        f"Итого строк для разметки: {counter}.",
        "",
        "Скрипт пересборки ведомости:",
        "`backend\\.venv\\Scripts\\python.exe scripts\\qd_label_sheet.py`.",
    ]
    SHEET.write_text("\n".join(lines), encoding="utf-8")
    print(f"rows={counter}")


if __name__ == "__main__":
    main()
