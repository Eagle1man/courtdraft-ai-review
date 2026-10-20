"""Прогон QD-Court по делам демо-набора (Этап 6 ТЗ).

Собирает пакеты тем же конвейером, что и демо (build_real_site.build_pack),
гоняет ExplorationService и кладёт архивы в data/exploration/.
Сводка — в scripts/tmp_qd_run_out.txt (кириллица в консоли портится).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "data" / "demo" / "real" / "cases"
ARCHIVE = ROOT / "data" / "exploration"
OUT = Path(__file__).with_name("tmp_qd_run_out.txt")


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    build = _load("qd_build_real_site", "build_real_site.py")
    from app.exploration import ExplorationBudget, ExplorationService

    service = ExplorationService(ARCHIVE, ExplorationBudget())
    index = json.loads((CASES / "index.json").read_text(encoding="utf-8"))

    lines: list[str] = []
    total_hypotheses = 0
    total_supported = 0
    for entry in index["cases"]:
        slug = entry["slug"]
        case_dir = CASES / slug
        settings = build.make_settings(case_dir)
        settings.ensure_dirs()
        pack = build.build_pack(case_dir, settings)
        report = service.run(slug, pack)
        supported = [h for h in report.hypotheses if h.status.value == "SUPPORTED"]
        total_hypotheses += len(report.hypotheses)
        total_supported += len(supported)
        lines.append(
            f"## {slug}: итераций {report.iterations}, гипотез "
            f"{len(report.hypotheses)}, подтверждено {len(supported)}, "
            f"fallback={report.fallback}"
        )
        for hypothesis in supported[:4]:
            lines.append(f"- [{hypothesis.kind}] {hypothesis.text[:140]}")
        lines.append("")

    lines.append(f"ИТОГО: гипотез {total_hypotheses}, подтверждено {total_supported}")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"cases={len(index['cases'])} hypotheses={total_hypotheses}")


if __name__ == "__main__":
    main()
