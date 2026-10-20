"""Сравнение режимов A/B/C QD-Court (Этап 6 ТЗ).

A — существующий конвейер без поиска (базлайн: новых направлений 0).
B — генерация направлений без архива: explore + verify, без новизны и
    сохранения (повторы возможны).
C — QD-Court: архив, мутации, novelty-first admission.

Одинаковые входные материалы, одинаковый предлагающий и проверяющий,
сопоставимый бюджет. Метрики технические: юридическую полезность без
разметки человека не утверждаем.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "data" / "demo" / "real" / "cases"
EVAL_ROOT = ROOT / "data" / "exploration" / "_eval"
OUT = Path(__file__).with_name("tmp_qd_eval_out.txt")

def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    import shutil

    shutil.rmtree(EVAL_ROOT, ignore_errors=True)  # свежий архив на каждый прогон
    build = _load("qde_build_real_site", "build_real_site.py")
    from app.exploration import ExplorationBudget, ExplorationService
    from app.exploration.proposer import DirectionProposer
    from app.exploration.verification import HypothesisVerifier

    proposer = DirectionProposer()
    verifier = HypothesisVerifier()
    index = json.loads((CASES / "index.json").read_text(encoding="utf-8"))

    lines = [
        "СРАВНЕНИЕ РЕЖИМОВ A/B/C",
        "A = конвейер без поиска (базлайн, новых направлений 0)",
        "",
        "дело | B: предл. | B: подтв. | C: гипотез | C: подтв. | C: повторов | C: итер.",
    ]
    totals = {"b_candidates": 0, "b_supported": 0, "c_all": 0, "c_supported": 0,
              "c_rejected": 0, "c_iterations": 0, "fallbacks": 0}

    for entry in index["cases"]:
        slug = entry["slug"]
        case_dir = CASES / slug
        settings = build.make_settings(case_dir)
        settings.ensure_dirs()
        pack = build.build_pack(case_dir, settings)

        # Режим B: без архива и новизны
        candidates = proposer.explore(pack)
        verified_b = [verifier.verify(c, pack) for c in candidates]
        b_supported = sum(1 for h in verified_b if h.status.value == "SUPPORTED")

        # Режим C: полный сервис с архивом
        service = ExplorationService(EVAL_ROOT, ExplorationBudget())
        report = service.run(slug, pack)
        c_supported = sum(
            1 for h in report.hypotheses if h.status.value == "SUPPORTED"
        )
        c_rejected = sum(
            1 for h in report.hypotheses if h.status.value == "REJECTED"
        )
        if report.fallback:
            totals["fallbacks"] += 1

        totals["b_candidates"] += len(candidates)
        totals["b_supported"] += b_supported
        totals["c_all"] += len(report.hypotheses)
        totals["c_supported"] += c_supported
        totals["c_rejected"] += c_rejected
        totals["c_iterations"] += report.iterations

        lines.append(
            f"{slug} | {len(candidates)} | {b_supported} | "
            f"{len(report.hypotheses)} | {c_supported} | {c_rejected} | "
            f"{report.iterations}"
        )

    lines += [
        "",
        f"ИТОГО B: предложено {totals['b_candidates']}, "
        f"подтверждено {totals['b_supported']}",
        f"ИТОГО C: гипотез {totals['c_all']}, подтверждено "
        f"{totals['c_supported']}, отклонено-повторов {totals['c_rejected']}, "
        f"итераций {totals['c_iterations']}, fallback {totals['fallbacks']}",
    ]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("eval ok")


if __name__ == "__main__":
    main()
